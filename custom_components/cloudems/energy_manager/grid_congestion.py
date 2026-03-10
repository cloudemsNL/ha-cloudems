# -*- coding: utf-8 -*-
"""
CloudEMS Grid Congestion Detector — v1.10.1

Detects grid overload / congestion situations and recommends load shedding.

Strategy:
  - Monitor import power against a user-defined congestion threshold (W).
  - If grid_import > threshold AND EPEX price is high → congestion_active = True.
  - Recommend actions (in priority order):
      1. Reduce EV charging to minimum (6 A)
      2. Delay boiler / sheddable loads
      3. Reduce solar export if battery can absorb it
  - Auto-clears when import drops below (threshold - hysteresis).
  - Tracks congestion events per day/month for dashboard reporting.

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

STORAGE_KEY     = "cloudems_congestion_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 300  # 5 minutes — persist even without a clean HA shutdown

DEFAULT_CONGESTION_THRESHOLD_W   = 5000   # W — alert when import > this
DEFAULT_PRICE_THRESHOLD_EUR_KWH  = 0.25   # EUR/kWh — only flag when price is also high
HYSTERESIS_W                     = 300    # W — clear event only when below threshold - this


@dataclass
class CongestionEvent:
    started_at:  str   # ISO timestamp
    ended_at:    Optional[str]
    peak_import_w: float
    actions_taken: list


@dataclass
class CongestionResult:
    congestion_active: bool
    import_w:          float
    threshold_w:       float
    utilisation_pct:   float    # import / threshold * 100
    price_eur_kwh:     float
    actions:           list     # recommended actions
    today_events:      int
    month_events:      int
    peak_today_w:      float


class GridCongestionDetector:
    """
    Monitors grid import power and flags congestion.

    Usage in coordinator:
        gcd = GridCongestionDetector(hass, config)
        await gcd.async_setup()
        result = await gcd.async_evaluate(grid_import_w, price_eur_kwh)
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass      = hass
        self._threshold = float(config.get("congestion_threshold_w", DEFAULT_CONGESTION_THRESHOLD_W))
        self._price_thr = float(config.get("congestion_price_threshold", DEFAULT_PRICE_THRESHOLD_EUR_KWH))
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._history: dict = {"daily": {}, "monthly": {}, "events": []}
        self._active        = False
        self._event_start:  Optional[float] = None
        self._peak_today_w: float = 0.0
        self._dirty:        bool  = False
        self._last_save:    float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if data:
            self._history = data
        _LOGGER.debug("GridCongestionDetector ready (threshold=%.0f W)", self._threshold)

    async def async_save(self) -> None:
        await self._store.async_save(self._history)
        self._dirty     = False
        self._last_save = time.time()

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()

    # ── Evaluation ────────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        grid_import_w: float,
        price_eur_kwh: float,
    ) -> CongestionResult:
        """Evaluate congestion state and return recommended actions."""
        now      = datetime.now(timezone.utc)
        day_key  = now.strftime("%Y-%m-%d")
        month_key= now.strftime("%Y-%m")

        # Track peak
        if grid_import_w > self._peak_today_w:
            self._peak_today_w = grid_import_w

        # Update daily history
        daily = self._history.setdefault("daily", {})
        monthly = self._history.setdefault("monthly", {})
        if day_key not in daily:
            daily[day_key] = {"peak_w": 0.0, "events": 0}
            # Reset peak on new day
            self._peak_today_w = grid_import_w
        daily[day_key]["peak_w"] = max(daily[day_key]["peak_w"], grid_import_w)
        if daily[day_key]["peak_w"] > (daily[day_key].get("peak_w", 0) - 1):
            self._dirty = True
        if month_key not in monthly:
            monthly[month_key] = {"events": 0}

        utilisation = (grid_import_w / max(self._threshold, 1.0)) * 100.0
        clear_level = self._threshold - HYSTERESIS_W
        actions     = []

        # Detect congestion
        price_high = price_eur_kwh >= self._price_thr
        over_limit = grid_import_w > self._threshold

        if over_limit and not self._active:
            # New congestion event
            self._active       = True
            self._event_start  = time.time()
            daily[day_key]["events"]   += 1
            monthly[month_key]["events"] += 1
            self._dirty = True
            _LOGGER.warning(
                "Grid congestion detected: %.0f W > %.0f W threshold (price %.3f €/kWh)",
                grid_import_w, self._threshold, price_eur_kwh,
            )

        elif grid_import_w < clear_level and self._active:
            # Event cleared
            self._active      = False
            self._event_start = None
            _LOGGER.info("Grid congestion cleared (%.0f W)", grid_import_w)

        # Build recommended actions (ordered by impact, least intrusive first)
        # Capaciteitstarief-bewuste actie: al bij 80% utilisation adviseren
        if utilisation > 80 or self._active:
            actions.append({
                "action":   "reduce_ev_charging",
                "priority": 1,
                "reason":   f"Net op {utilisation:.0f}% — verminder EV-lader naar minimum",
                "urgency":  "now" if self._active else ("soon" if utilisation > 90 else "advisory"),
            })
        if self._active and price_high:
            actions.append({
                "action":   "defer_boiler",
                "priority": 2,
                "reason":   f"Congestie + hoge prijs ({price_eur_kwh:.3f} €/kWh) — boiler pauzeren",
                "urgency":  "now",
            })
        if self._active and utilisation > 110:
            actions.append({
                "action":   "shed_flexible_loads",
                "priority": 3,
                "reason":   f"Zware congestie ({utilisation:.0f}%) — schakel lasten onmiddellijk uit",
                "urgency":  "now",
            })
        # Capaciteitstarief-specifiek: waarschuw als maandpiek dreigt
        if utilisation > 95 and not self._active:
            actions.append({
                "action":   "capacity_tariff_warning",
                "priority": 0,  # hoogste prioriteit
                "reason":   (f"Nadert congestiegrens ({utilisation:.0f}%) — "
                             f"risico voor capaciteitstarief maandpiek"),
                "urgency":  "advisory",
            })

        # Periodic save — persist even without a clean HA shutdown
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()

        return CongestionResult(
            congestion_active = self._active,
            import_w          = grid_import_w,
            threshold_w       = self._threshold,
            utilisation_pct   = round(utilisation, 1),
            price_eur_kwh     = price_eur_kwh,
            actions           = actions,
            today_events      = daily.get(day_key, {}).get("events", 0),
            month_events      = monthly.get(month_key, {}).get("events", 0),
            peak_today_w      = round(self._peak_today_w, 1),
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._active

    @property
    def threshold_w(self) -> float:
        return self._threshold

    def get_monthly_summary(self) -> list:
        monthly = self._history.get("monthly", {})
        daily   = self._history.get("daily", {})
        result  = []
        for month, mdata in sorted(monthly.items(), reverse=True)[:6]:
            peak = max(
                (d["peak_w"] for k, d in daily.items() if k.startswith(month)),
                default=0.0,
            )
            result.append({
                "month":   month,
                "events":  mdata.get("events", 0),
                "peak_w":  round(peak, 1),
            })
        return result
