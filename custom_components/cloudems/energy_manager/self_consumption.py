# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Zelfconsumptie Tracker — v1.0.0

Houdt bij welk percentage van de PV-productie direct zelf wordt verbruikt
versus teruggeleverd aan het net.

Formule:
  zelfconsumptie_ratio = (pv_totaal − export) / pv_totaal
  = directe_consumptie / pv_totaal

Aanvullend:
  • Trackt per uur welke NILM-apparaten draaiden tijdens PV-piekproductie
  • Berekent potentiële besparing als apparaten verschoven worden naar piektijd
  • Geeft concrete aanbeveling met geschatte maandelijkse besparing

Salderingscontext (NL 2025):
  Terugleververgoeding ≈ EPEX (variabel) maar doorgaans lager dan inkoopprijs.
  Verschil inkoop vs teruglevering = de directe besparing van hogere zelfconsumptie.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_self_consumption_v1"
STORAGE_VERSION = 1

SAVE_INTERVAL_S = 120  # Save every 2 minutes during active PV production
MIN_PV_W        = 50     # Minimale PV-productie voor meting
# Aanname: verschil inkoop vs teruglevering (€/kWh)
PRICE_SPREAD_EUR_KWH = 0.08   # indicatief voordeel per kWh zelfverbruik


@dataclass
class HourlyConsumptionSlot:
    """Bijgehouden statistieken per uur van de dag (0-23)."""
    pv_wh:     float = 0.0    # PV energie in dit uur (Wh)
    export_wh: float = 0.0    # Teruggeleverd in dit uur (Wh)
    import_wh: float = 0.0    # Afgenomen van net in dit uur (Wh)
    samples:   int   = 0      # Aantal 10s-ticks


@dataclass
class SelfConsumptionData:
    """Output van de zelfconsumptie-tracker."""
    ratio_pct: float              # % direct verbruikt van PV
    export_pct: float             # % teruggeleverd
    pv_today_kwh: float
    self_consumed_kwh: float
    exported_kwh: float
    best_solar_hour: Optional[int]    # uur met hoogste PV-productie
    best_solar_hour_label: str
    advice: str
    monthly_saving_eur: float     # geschatte extra maandelijkse besparing bij optimale verschuiving
    hourly_pv_wh: list[float]     # 24-uurs profiel van PV (Wh)


class SelfConsumptionTracker:
    """
    Houdt zelfconsumptieratio bij en berekent optimalisatiepotentieel.

    Gebruik vanuit coordinator (elke 10s):
        tracker.tick(pv_w=2400, import_w=0, export_w=800)
        data = tracker.get_data()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Huidige dag accumulatie
        self._today_pv_wh     = 0.0
        self._today_export_wh = 0.0
        self._today_import_wh = 0.0
        self._today_date       = ""

        # Uurprofiel (rolling 30-dag gemiddelde)
        self._hourly: list[HourlyConsumptionSlot] = [HourlyConsumptionSlot() for _ in range(24)]

        self._dirty    = False
        self._last_save = 0.0
        self._tick_interval_s = 10.0

    async def async_setup(self) -> None:
        # Initialiseer datum altijd zodat async_save nooit een lege datum opslaat
        from datetime import datetime, timezone
        self._today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved: dict = await self._store.async_load() or {}
        hourly_raw  = saved.get("hourly", [])
        if len(hourly_raw) == 24:
            self._hourly = [
                HourlyConsumptionSlot(**h) for h in hourly_raw
            ]
        _LOGGER.info("SelfConsumptionTracker: geladen (%d uur-slots)", len(self._hourly))
        # Herstel dagaccumulatie vanuit opgeslagen dagdata (overleeft herstart)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved_today = saved.get("today", {})
        if saved_today.get("date") == today:
            _pv   = float(saved_today.get("pv_wh", 0.0))
            _exp  = float(saved_today.get("export_wh", 0.0))
            _imp  = float(saved_today.get("import_wh", 0.0))
            # v4.6.593: sanity check verwijderd — export=0 terwijl PV>1kWh is een
            # geldige situatie als batterij alles absorbeert. De oorspronkelijke bug
            # (export_w altijd 0) is gefixed in v4.6.578, deze check is niet meer nodig.
            self._today_date      = today
            # Sanity check: export can never exceed PV (physically impossible).
            # Corrupted storage from a previous bug would cause ratio=0% forever.
            if _pv > 100 and _exp > _pv:
                _LOGGER.warning(
                    "SelfConsumptionTracker: export_wh (%.0f) > pv_wh (%.0f) — "
                    "corrupt storage detected, resetting today's accumulation",
                    _exp, _pv,
                )
                _exp = 0.0
            self._today_pv_wh     = _pv
            self._today_export_wh = _exp
            self._today_import_wh = _imp
            _LOGGER.info(
                "SelfConsumptionTracker: dag-data hersteld: PV %.2f kWh, export %.2f kWh",
                self._today_pv_wh / 1000, self._today_export_wh / 1000,
            )

    def tick(self, pv_w: float, import_w: float, export_w: float) -> None:
        """
        Verwerk één 10-secondenmeting.

        Parameters
        ----------
        pv_w      : huidig PV-vermogen (W)
        import_w  : huidig netvermogen import (W, >= 0)
        export_w  : huidig netvermogen export (W, >= 0)
        """
        now  = datetime.now(timezone.utc)
        hour = now.hour
        today = now.strftime("%Y-%m-%d")

        # Dag-reset
        if today != self._today_date:
            self._today_pv_wh     = 0.0
            self._today_export_wh = 0.0
            self._today_import_wh = 0.0
            self._today_date      = today

        # Accumuleer Wh (10s interval → /360 uur)
        factor = self._tick_interval_s / 3600.0

        if pv_w >= MIN_PV_W:
            self._today_pv_wh     += pv_w     * factor
            self._today_export_wh += export_w  * factor
            self._today_import_wh += import_w  * factor
            # Physical constraint: can never export more than produced
            if self._today_export_wh > self._today_pv_wh:
                self._today_export_wh = self._today_pv_wh
            self._dirty = True

        # Update uurprofiel (exponentieel voortschrijdend gemiddelde)
        slot = self._hourly[hour]
        alpha = 0.05   # trage leer-snelheid
        if slot.samples == 0:
            slot.pv_wh     = pv_w * factor
            slot.export_wh = export_w * factor
            slot.import_wh = import_w * factor
        else:
            slot.pv_wh     = alpha * pv_w * factor     + (1 - alpha) * slot.pv_wh
            slot.export_wh = alpha * export_w * factor + (1 - alpha) * slot.export_wh
            slot.import_wh = alpha * import_w * factor + (1 - alpha) * slot.import_wh
        slot.samples += 1

    def get_data(self) -> SelfConsumptionData:
        """Geef huidige zelfconsumptie-analyse."""
        pv_kwh  = round(self._today_pv_wh / 1000, 3)
        exp_kwh = round(self._today_export_wh / 1000, 3)
        sc_kwh  = round(max(0.0, pv_kwh - exp_kwh), 3)

        ratio_pct  = round(sc_kwh / pv_kwh * 100, 1) if pv_kwh > 0 else 0.0
        export_pct = round(100.0 - ratio_pct, 1)

        # Beste zonne-uur
        best_hour = max(range(24), key=lambda h: self._hourly[h].pv_wh)
        best_wh   = self._hourly[best_hour].pv_wh
        if best_wh < 1:
            best_hour = None
            best_label = "Onbekend"
        else:
            best_label = f"{best_hour:02d}:00–{(best_hour + 1) % 24:02d}:00"

        # Schatting maandelijks voordeel bij verschuiven apparaten
        # Als export_pct > 30%: gemiddeld 1 apparaatcyclus per dag is verschuifbaar (~1.5 kWh)
        shiftable_kwh_day = max(0.0, (export_pct - 20) / 100 * pv_kwh * 0.5)
        monthly_saving    = round(shiftable_kwh_day * 30 * PRICE_SPREAD_EUR_KWH, 2)

        if pv_kwh < 0.1:
            advice = "Vandaag nog geen PV-productie gemeten."
        elif ratio_pct >= 70:
            advice = f"Uitstekend! Je verbruikt {ratio_pct:.0f}% van je PV-productie direct zelf."
        elif ratio_pct >= 40:
            advice = (
                f"Je zelfconsumptiegraad is {ratio_pct:.0f}%. Door apparaten zoals wasmachine of vaatwasser "
                f"te plannen rond {best_label} kun je dit verder verbeteren."
            )
        else:
            advice = (
                f"Je stuurt {export_pct:.0f}% van je PV-productie terug. "
                f"Piekproductie is rond {best_label}. "
                f"Verschuif energieverbruik naar dit uur voor ~€{monthly_saving:.2f}/maand extra besparing."
            )

        return SelfConsumptionData(
            ratio_pct          = ratio_pct,
            export_pct         = export_pct,
            pv_today_kwh       = pv_kwh,
            self_consumed_kwh  = sc_kwh,
            exported_kwh       = exp_kwh,
            best_solar_hour    = best_hour,
            best_solar_hour_label = best_label,
            advice             = advice,
            monthly_saving_eur = monthly_saving,
            hourly_pv_wh       = [round(self._hourly[h].pv_wh * 100, 1) for h in range(24)],
        )

    def forecast_self_consumption(self, pv_forecast_hourly: list[float]) -> dict:
        """
        v4.6.283: Voorspel zelfconsumptie voor morgen op basis van:
        - PV-uurforecast (Wh per uur, 24 punten)
        - Geleerd verbruiksprofiel (_hourly[h].import_wh als proxy voor huisverbruik)

        Formule per uur:
          self_consumed_wh = min(pv_wh, house_wh)
          export_wh        = max(0, pv_wh - house_wh)
          import_wh        = max(0, house_wh - pv_wh)

        Geeft dict met:
          total_pv_kwh, self_consumed_kwh, export_kwh, self_consumption_pct,
          hourly (24 dicts met pv_wh, house_wh, self_wh, export_wh)
        """
        if not pv_forecast_hourly or len(pv_forecast_hourly) < 24:
            return {}

        # Gemiddeld huisverbruik per uur uit geleerd profiel (Wh)
        # import_wh = wat van het net gehaald werd; als PV 0 is = huisverbruik
        # Als er wel PV was: house = pv_wh - export_wh + import_wh
        house_profile: list[float] = []
        for h in range(24):
            slot = self._hourly[h]
            if slot.samples > 0:
                # Reconstruct house_wh: pv + import - export
                house_wh = slot.pv_wh + slot.import_wh - slot.export_wh
                house_profile.append(max(0.0, house_wh))
            else:
                house_profile.append(200.0)  # fallback 200Wh/uur als geen data

        hourly = []
        total_pv = 0.0
        total_self = 0.0
        total_export = 0.0

        for h in range(24):
            pv_wh    = float(pv_forecast_hourly[h]) if h < len(pv_forecast_hourly) else 0.0
            house_wh = house_profile[h]
            self_wh  = min(pv_wh, house_wh)
            exp_wh   = max(0.0, pv_wh - house_wh)
            total_pv    += pv_wh
            total_self  += self_wh
            total_export += exp_wh
            hourly.append({
                "hour":     h,
                "pv_wh":   round(pv_wh, 0),
                "house_wh": round(house_wh, 0),
                "self_wh":  round(self_wh, 0),
                "export_wh": round(exp_wh, 0),
            })

        sc_pct = round(total_self / total_pv * 100, 1) if total_pv > 0 else 0.0

        return {
            "total_pv_kwh":          round(total_pv   / 1000, 2),
            "self_consumed_kwh":     round(total_self  / 1000, 2),
            "export_kwh":            round(total_export/ 1000, 2),
            "self_consumption_pct":  sc_pct,
            "hourly":                hourly,
            "has_profile":           any(s.samples > 0 for s in self._hourly),
        }

    async def async_save(self) -> None:
        """Force save immediately, regardless of dirty flag or interval."""
        await self._store.async_save({
            "hourly": [
                {"pv_wh": s.pv_wh, "export_wh": s.export_wh,
                 "import_wh": s.import_wh, "samples": s.samples}
                for s in self._hourly
            ],
            "today": {
                "date":       self._today_date,
                "pv_wh":      round(self._today_pv_wh, 2),
                "export_wh":  round(self._today_export_wh, 2),
                "import_wh":  round(self._today_import_wh, 2),
            },
        })
        self._dirty     = False
        self._last_save = time.time()

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "hourly": [
                    {"pv_wh": s.pv_wh, "export_wh": s.export_wh,
                     "import_wh": s.import_wh, "samples": s.samples}
                    for s in self._hourly
                ],
                "today": {
                    "date":       self._today_date,
                    "pv_wh":      round(self._today_pv_wh, 2),
                    "export_wh":  round(self._today_export_wh, 2),
                    "import_wh":  round(self._today_import_wh, 2),
                },
            })
            self._dirty     = False
            self._last_save = time.time()
