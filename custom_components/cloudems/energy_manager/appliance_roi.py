# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
appliance_roi.py — CloudEMS v4.3.4
=====================================
Berekent de kosten per NILM-apparaat en het potentieel besparing
als dat apparaat op een goedkoper tijdstip had gedraaid.

Per apparaat:
  - Kosten vandaag/maand/jaar (kWh × EPEX prijs op dat moment)
  - Gemiste besparing: als het apparaat op de goedkoopste 4u had gedraaid
  - Aanbeveling: verschuif X naar 02:00–06:00 → bespaar €Y/mnd

Wordt berekend vanuit coordinator bij DailySummary en in _generate_insights().
Geen eigen Store — output is stateless (altijd herberekend).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Minimaal verbruik om ROI te berekenen (watt gemiddeld)
MIN_DEVICE_POWER_W = 20
# Minimale prijs-spreiding om "verschuifbaar" te noemen (cent/kWh)
MIN_PRICE_SPREAD_EUR = 0.03


@dataclass
class ApplianceROI:
    device_id:          str
    device_name:        str
    device_type:        str
    avg_power_w:        float
    runtime_h_today:    float
    kwh_today:          float
    cost_today_eur:     float
    cost_month_eur:     float    # extrapolatie: × 30
    cost_year_eur:      float    # extrapolatie: × 365
    optimal_hours:      list     # goedkoopste uren (0-23)
    missed_saving_eur:  float    # potentieel besparing per dag
    shiftable:          bool     # kan dit apparaat verschoven worden?
    tip:                str      = ""


def calculate_appliance_roi(
    devices:             list,        # CloudEMSDevice objecten
    price_hour_history:  list,        # [{ts, price}, ...]
    current_price:       float,
) -> list[ApplianceROI]:
    """
    Berekent ROI voor alle NILM-apparaten met voldoende data.

    Returns: gesorteerd op cost_year_eur desc (duurste eerst)
    """
    if not devices or not price_hour_history:
        return []

    # Bouw uurprijs-lookup: gemiddelde per uur van de dag (laatste 7 dgn)
    from datetime import datetime, timezone
    hour_prices: dict[int, list[float]] = {h: [] for h in range(24)}
    recent = price_hour_history[-168:]  # 7 dagen
    for entry in recent:
        try:
            h     = datetime.fromtimestamp(entry["ts"], tz=timezone.utc).hour
            price = float(entry.get("price", 0) or 0)
            if price > 0:
                hour_prices[h].append(price)
        except Exception:
            continue

    hour_avg: dict[int, float] = {
        h: sum(p) / len(p) for h, p in hour_prices.items() if p
    }
    if not hour_avg:
        return []

    global_avg = sum(hour_avg.values()) / len(hour_avg)
    sorted_hours = sorted(hour_avg.items(), key=lambda x: x[1])
    cheapest_4h  = {h for h, _ in sorted_hours[:4]}
    cheapest_avg = sum(hour_avg[h] for h in cheapest_4h) / 4 if cheapest_4h else global_avg
    price_spread = max(hour_avg.values()) - min(hour_avg.values())

    results = []
    for dev in devices:
        avg_w = getattr(dev, "avg_power_w", None) or getattr(dev, "power_w", 0) or 0
        if avg_w < MIN_DEVICE_POWER_W:
            continue

        # Schat daily runtime: gebruik confirmed events als beschikbaar
        runtime_h = getattr(dev, "daily_runtime_h", None)
        if runtime_h is None:
            # Fallback: schat op basis van device type
            _type = (getattr(dev, "device_type", "") or "").lower()
            runtime_h = {
                "washing_machine": 1.5,
                "dishwasher": 1.2,
                "dryer": 1.0,
                "oven": 0.8,
                "fridge": 8.0,
                "freezer": 10.0,
                "boiler": 3.0,
                "ev_charger": 2.0,
                "heat_pump": 6.0,
            }.get(_type, 1.0)

        kwh_today    = round(avg_w * runtime_h / 1000.0, 3)
        cost_today   = round(kwh_today * current_price, 4)
        cost_month   = round(cost_today * 30, 2)
        cost_year    = round(cost_today * 365, 2)

        # Verschuifbare apparaten (niet continu)
        _type = (getattr(dev, "device_type", "") or "").lower()
        _non_shiftable = {"fridge", "freezer", "lighting", "router", "tv_standby"}
        shiftable = _type not in _non_shiftable and price_spread >= MIN_PRICE_SPREAD_EUR

        missed = 0.0
        tip    = ""
        optimal = sorted(cheapest_4h)

        if shiftable and cheapest_avg < current_price:
            saving_per_kwh = current_price - cheapest_avg
            missed = round(kwh_today * saving_per_kwh, 4)
            if missed >= 0.005:  # minimaal 0.5 cent
                hour_strs = ", ".join(f"{h:02d}:00" for h in optimal[:3])
                tip = (
                    f"Verschuif naar {hour_strs} voor ~€{missed * 30:.2f}/mnd besparing"
                )

        results.append(ApplianceROI(
            device_id         = getattr(dev, "device_id", ""),
            device_name       = getattr(dev, "display_name", "") or getattr(dev, "name", ""),
            device_type       = _type,
            avg_power_w       = round(avg_w, 1),
            runtime_h_today   = round(runtime_h, 2),
            kwh_today         = kwh_today,
            cost_today_eur    = cost_today,
            cost_month_eur    = cost_month,
            cost_year_eur     = cost_year,
            optimal_hours     = optimal,
            missed_saving_eur = round(missed, 4),
            shiftable         = shiftable,
            tip               = tip,
        ))

    results.sort(key=lambda x: -x.cost_year_eur)
    return results


def to_dict_list(rois: list[ApplianceROI]) -> list[dict]:
    return [
        {
            "device_id":          r.device_id,
            "device_name":        r.device_name,
            "device_type":        r.device_type,
            "avg_power_w":        r.avg_power_w,
            "kwh_today":          r.kwh_today,
            "cost_today_eur":     r.cost_today_eur,
            "cost_month_eur":     r.cost_month_eur,
            "cost_year_eur":      r.cost_year_eur,
            "missed_saving_eur":  r.missed_saving_eur,
            "shiftable":          r.shiftable,
            "optimal_hours":      r.optimal_hours,
            "tip":                r.tip,
        }
        for r in rois
    ]


class ApplianceROICalculator:
    """
    Wrapper klasse met persistente cumulatieve besparingstracking.

    v1.32: Houdt per apparaat bij hoeveel er over alle sessies bespaard is
    (t.o.v. een dag-tarief baseline). Na een jaar geeft CloudEMS een
    overzicht: "je EV-laadsessies bespaarden €340 dit jaar."
    """

    STORE_KEY     = "cloudems_appliance_roi_v1"
    STORE_VERSION = 1

    def __init__(self, hass=None) -> None:
        self._hass   = hass
        self._store  = None
        # Cumulatieve besparing per device_id (€)
        self._cumulative: dict[str, float] = {}
        # Cumulatieve kWh per device_id
        self._cumulative_kwh: dict[str, float] = {}
        # Datum eerste meting per device_id
        self._first_seen: dict[str, str] = {}
        self._dirty     = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        if not self._hass:
            return
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, self.STORE_VERSION, self.STORE_KEY)
        try:
            raw = await self._store.async_load() or {}
            self._cumulative      = {k: float(v) for k, v in raw.get("cumulative", {}).items()}
            self._cumulative_kwh  = {k: float(v) for k, v in raw.get("cumulative_kwh", {}).items()}
            self._first_seen      = raw.get("first_seen", {})
            import logging as _l
            _l.getLogger(__name__).debug(
                "ApplianceROICalculator: %d apparaten met cumulatieve tracking geladen",
                len(self._cumulative),
            )
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("ApplianceROICalculator: laden mislukt: %s", exc)

    async def _async_save(self) -> None:
        import time as _t
        if not self._store or not self._dirty or _t.time() - self._last_save < 3600:
            return
        try:
            await self._store.async_save({
                "cumulative":     self._cumulative,
                "cumulative_kwh": self._cumulative_kwh,
                "first_seen":     self._first_seen,
            })
            self._dirty     = False
            self._last_save = _t.time()
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("ApplianceROICalculator: opslaan mislukt: %s", exc)

    def calculate(
        self,
        nilm_devices: list,
        price_eur_kwh: float,
        price_hour_history: Optional[list] = None,
    ) -> list:
        rois = calculate_appliance_roi(
            nilm_devices,
            price_hour_history or [],
            price_eur_kwh,
        )
        # v1.32: accumuleer dagelijkse besparing per apparaat
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for roi in rois:
            did = roi.device_id
            if not did:
                continue
            if did not in self._first_seen:
                self._first_seen[did] = today
                self._dirty = True
            # missed_saving_eur is de dagelijkse besparing vs suboptimale timing
            daily_saving = roi.missed_saving_eur or 0.0
            if daily_saving > 0:
                self._cumulative[did]     = self._cumulative.get(did, 0.0) + daily_saving
                self._cumulative_kwh[did] = self._cumulative_kwh.get(did, 0.0) + roi.kwh_today
                self._dirty = True
        return rois

    def to_sensor_dict(self, rois: list) -> dict:
        items = to_dict_list(rois)
        # Verrijk met cumulatieve data
        for item in items:
            did = item.get("device_id", "")
            item["cumulative_saving_eur"] = round(self._cumulative.get(did, 0.0), 2)
            item["cumulative_kwh"]        = round(self._cumulative_kwh.get(did, 0.0), 2)
            item["tracking_since"]        = self._first_seen.get(did)
        total_saved = round(sum(self._cumulative.values()), 2)
        return {
            "items":         items,
            "count":         len(rois),
            "total_saved_eur": total_saved,
        }

    def get_lifetime_summary(self) -> list[dict]:
        """Geef lifetime besparingsoverzicht per apparaat (voor dashboard/rapport)."""
        result = []
        for did, saved_eur in sorted(
            self._cumulative.items(), key=lambda x: -x[1]
        ):
            result.append({
                "device_id":           did,
                "cumulative_saving_eur": round(saved_eur, 2),
                "cumulative_kwh":        round(self._cumulative_kwh.get(did, 0.0), 2),
                "tracking_since":        self._first_seen.get(did),
            })
        return result
