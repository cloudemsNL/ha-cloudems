# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
battery_efficiency.py — CloudEMS v4.0.5
=========================================
Bijhoudt het werkelijke rendement van de thuisbatterij.

Meting:
  - Elke cyclus: meet kWh ingeladen en uitgeladen
  - Round-trip efficiency = uitgeladen / ingeladen
  - Afwijking van nominaal (bijv. 92%) → degradatie-signaal

Persistent via HA Store (rolling 90-dagen buffer).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
STORAGE_KEY_BATTERY_EFF = "cloudems_battery_efficiency_v1"

NOMINAL_EFFICIENCY = 0.92       # 92% round-trip
WARN_THRESHOLD     = 0.80       # waarschuw als < 80%
MIN_CYCLE_KWH      = 0.2        # minimale cyclusmaat om op te slaan


@dataclass
class CycleRecord:
    date:        str
    charged_kwh: float
    discharged_kwh: float
    efficiency:  float
    eur_benefit: float = 0.0    # optioneel: berekend voordeel


@dataclass
class BatteryEfficiencyStatus:
    avg_efficiency_pct:   float   # gemiddeld over 30 dgn
    last_efficiency_pct:  float   # laatste cyclus
    nominal_pct:          float   = NOMINAL_EFFICIENCY * 100
    degradation_pct:      float   = 0.0   # afwijking t.o.v. nominaal
    total_charged_kwh:    float   = 0.0
    total_discharged_kwh: float   = 0.0
    cycle_count:          int     = 0
    warn:                 bool    = False
    cycles_sample:        list    = field(default_factory=list)
    roi_advice:           dict    = field(default_factory=dict)  # v5.5.77

    def to_dict(self) -> dict:
        return {
            "avg_efficiency_pct":   round(self.avg_efficiency_pct, 1),
            "last_efficiency_pct":  round(self.last_efficiency_pct, 1),
            "nominal_pct":          round(self.nominal_pct, 1),
            "degradation_pct":      round(self.degradation_pct, 1),
            "total_charged_kwh":    round(self.total_charged_kwh, 2),
            "total_discharged_kwh": round(self.total_discharged_kwh, 2),
            "cycle_count":          self.cycle_count,
            "warn":                 self.warn,
            "cycles_sample":        self.cycles_sample[-5:],
            "roi_advice":           self.roi_advice,
        }


class BatteryEfficiencyTracker:
    """
    Bijhoudt ingeladen/uitgeladen kWh en berekent real-time efficiency.

    Gebruik in coordinator (elke cyclus):
        tracker.observe(battery_power_w, dt_s=UPDATE_INTERVAL)

    Bij dagwisseling:
        tracker.close_day()
        await tracker.async_save()
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        self._cycles: list[dict] = []
        # Accumulatoren voor lopende dag
        self._charged_today_kwh    = 0.0
        self._discharged_today_kwh = 0.0
        self._loaded = False
        # Datum-guard: detecteer dagwissel zonder afhankelijkheid van periodieke code
        from datetime import date as _d
        self._last_date: str = str(_d.today())

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw:
                self._cycles = raw.get("cycles", [])[-90:]
                self._charged_today_kwh    = float(raw.get("charged_today_kwh",    0))
                self._discharged_today_kwh = float(raw.get("discharged_today_kwh", 0))
        except Exception as err:
            _LOGGER.warning("BatteryEfficiencyTracker: laden mislukt: %s", err)
        self._loaded = True

    async def async_save(self) -> None:
        try:
            await self._store.async_save({
                "cycles":               self._cycles[-90:],
                "charged_today_kwh":    self._charged_today_kwh,
                "discharged_today_kwh": self._discharged_today_kwh,
            })
        except Exception as err:
            _LOGGER.warning("BatteryEfficiencyTracker: opslaan mislukt: %s", err)

    def observe(self, battery_power_w: float, dt_s: float) -> None:
        """
        Aanroepen elke update-cyclus.
        battery_power_w > 0 = laden, < 0 = ontladen.

        Detecteert ook een dagwissel zonder afhankelijkheid van de periodieke
        dagelijkse code — zodat charged_today / discharged_today altijd correct
        worden gereset, ook als de coordinator op middernacht gefreezesd was.
        """
        from datetime import date as _d
        today_str = str(_d.today())
        if today_str != self._last_date:
            # Dag is gewisseld maar close_day() is nog niet aangeroepen.
            # Reset accumulatoren zodat vandaag schoon begint.
            _LOGGER.info(
                "BatteryEfficiencyTracker: dagwissel gedetecteerd in observe() "
                "(%s → %s), accumulatoren gereset.",
                self._last_date, today_str,
            )
            self._charged_today_kwh    = 0.0
            self._discharged_today_kwh = 0.0
            self._last_date = today_str

        kwh = abs(battery_power_w) * dt_s / 3600.0 / 1000.0
        if battery_power_w > 10:
            self._charged_today_kwh    += kwh
        elif battery_power_w < -10:
            self._discharged_today_kwh += kwh

    def close_day(self, date_str: str, eur_benefit: float = 0.0) -> Optional[CycleRecord]:
        """
        Sla dagcyclus op. Aanroepen bij DailySummary.
        Geeft CycleRecord terug als de cyclus groot genoeg was.
        """
        c_kwh = self._charged_today_kwh
        d_kwh = self._discharged_today_kwh
        self._charged_today_kwh    = 0.0
        self._discharged_today_kwh = 0.0

        if c_kwh < MIN_CYCLE_KWH or d_kwh < MIN_CYCLE_KWH:
            return None

        eff = round(d_kwh / c_kwh, 4) if c_kwh > 0 else 0.0
        rec = {
            "date":           date_str,
            "charged_kwh":    round(c_kwh, 3),
            "discharged_kwh": round(d_kwh, 3),
            "efficiency":     eff,
            "eur_benefit":    round(eur_benefit, 3),
        }
        self._cycles.append(rec)
        _LOGGER.info(
            "Batterij cyclus %s: %.2f kWh in → %.2f kWh uit (η=%.1f%%)",
            date_str, c_kwh, d_kwh, eff * 100,
        )
        return CycleRecord(**rec)


    def _calc_roi_advice(
        self,
        avg_eff: float,
        total_charged_kwh: float,
        total_discharged_kwh: float,
    ) -> dict:
        """Bereken vervangingsadvies op basis van gemeten efficiëntieverlies.

        Vergelijkt huidige gemeten efficiëntie met moderne Li-Ion standaard (94%).
        Berekent jaarlijks verlies in kWh en €, en terugverdientijd voor vervanging.
        """
        if total_charged_kwh < 10 or avg_eff <= 0:
            return {}

        # Moderne Li-Ion benchmark (bijv. Zonneplan Nexus, Huawei LUNA)
        MODERN_EFF       = 0.94
        MODERN_COST_EUR  = 4500.0   # Typische prijs inclusief installatie
        AVG_PRICE_EUR_KWH = 0.28    # Gemiddelde stroomprijs NL 2026

        # Jaarlijks verlies tov moderne accu
        # Stel dagelijks X kWh door de accu gaat
        days_measured = max(len(self._cycles), 1)
        daily_kwh = total_charged_kwh / days_measured

        # Verlies per kWh cyclus = (modern_eff - current_eff)
        loss_per_kwh = max(0.0, MODERN_EFF - avg_eff)
        annual_loss_kwh = daily_kwh * 365 * loss_per_kwh
        annual_loss_eur = round(annual_loss_kwh * AVG_PRICE_EUR_KWH, 2)

        if annual_loss_kwh < 5:
            # Minder dan 5 kWh/jaar verschil — geen advies nodig
            return {
                "status": "ok",
                "avg_efficiency_pct": round(avg_eff * 100, 1),
                "message": f"Accu presteert goed ({avg_eff*100:.1f}% round-trip efficiency).",
            }

        payback_years = round(MODERN_COST_EUR / annual_loss_eur, 1) if annual_loss_eur > 0 else None

        result = {
            "status":              "degraded" if avg_eff < WARN_THRESHOLD else "suboptimal",
            "avg_efficiency_pct":  round(avg_eff * 100, 1),
            "annual_loss_kwh":     round(annual_loss_kwh, 1),
            "annual_loss_eur":     annual_loss_eur,
            "modern_efficiency_pct": MODERN_EFF * 100,
            "modern_cost_eur":     MODERN_COST_EUR,
            "payback_years":       payback_years,
        }

        if payback_years and payback_years <= 5:
            result["message"] = (
                f"Je accu verliest ~{annual_loss_kwh:.0f} kWh/jaar door inefficiëntie "
                f"(€{annual_loss_eur:.0f}/jaar). Een moderne accu verdient zich in "
                f"±{payback_years} jaar terug."
            )
            result["recommend_replacement"] = True
        elif payback_years:
            result["message"] = (
                f"Je accu verliest ~{annual_loss_kwh:.0f} kWh/jaar t.o.v. moderne accu "
                f"(€{annual_loss_eur:.0f}/jaar). Terugverdientijd ±{payback_years} jaar — "
                f"afwachten tot garantie-einde."
            )
            result["recommend_replacement"] = False
        else:
            result["message"] = "Onvoldoende data voor terugverdienberekening."

        return result

    def get_status(self, days: int = 30) -> BatteryEfficiencyStatus:
        recent = self._cycles[-days:] if len(self._cycles) > days else self._cycles
        if not recent:
            return BatteryEfficiencyStatus(
                avg_efficiency_pct  = NOMINAL_EFFICIENCY * 100,
                last_efficiency_pct = NOMINAL_EFFICIENCY * 100,
            )
        effs = [r["efficiency"] for r in recent if r.get("efficiency", 0) > 0]
        avg_eff = (sum(effs) / len(effs)) if effs else NOMINAL_EFFICIENCY
        last_eff = recent[-1].get("efficiency", NOMINAL_EFFICIENCY)
        total_c = sum(r.get("charged_kwh", 0) for r in self._cycles)
        total_d = sum(r.get("discharged_kwh", 0) for r in self._cycles)
        degradation = round((NOMINAL_EFFICIENCY - avg_eff) * 100, 1)

        status = BatteryEfficiencyStatus(
            avg_efficiency_pct   = round(avg_eff * 100, 1),
            last_efficiency_pct  = round(last_eff * 100, 1),
            degradation_pct      = degradation,
            total_charged_kwh    = round(total_c, 2),
            total_discharged_kwh = round(total_d, 2),
            cycle_count          = len(self._cycles),
            warn                 = avg_eff < WARN_THRESHOLD,
            cycles_sample        = recent[-5:],
        )
        # v5.5.77: ROI-advies op basis van gemeten efficiëntieverlies
        status.roi_advice = self._calc_roi_advice(avg_eff, total_c, total_d)
        return status
