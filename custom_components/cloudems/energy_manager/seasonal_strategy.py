# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Battery Seasonal Strategy — v1.20.0

Adapts the BatteryEPEXScheduler charge/discharge plan based on the current
season (summer / winter / transition) and available PV data.

Problem solved:
  The default EPEX scheduler always picks the N cheapest hours for charging.
  In summer this often means charging at night (cheap) while the sun would
  charge the battery anyway by 10:00 — wasting a cycle and skipping a real
  opportunity to discharge during the expensive evening peak.
  In winter, solar is negligible, so pure EPEX scheduling is optimal.

Strategy per season:
  ┌─────────────┬──────────────────────────────────────────────────────────┐
  │ SUMMER      │ • Skip night charging when PV forecast covers > threshold │
  │             │ • Shift discharge window to evening peak (17-22h)         │
  │             │ • Increase discharge hours to 4 (more peak opportunity)   │
  ├─────────────┼──────────────────────────────────────────────────────────┤
  │ WINTER      │ • Full EPEX strategy (more charge hours: up to 5)         │
  │             │ • Discharge concentrated 17-20h (heating peak)            │
  │             │ • No PV skip logic                                        │
  ├─────────────┼──────────────────────────────────────────────────────────┤
  │ TRANSITION  │ • Hybrid: reduce charge hours if PV partially covers      │
  │             │ • Standard discharge window                               │
  └─────────────┴──────────────────────────────────────────────────────────┘

Season detection:
  Uses day length (calculated from latitude + day-of-year) and the 14-day
  rolling average PV output as a % of the learned peak capacity:
    - Summer:     day_length >= 14h  OR  pv_avg_14d >= 60% of peak
    - Winter:     day_length <= 9h   AND pv_avg_14d <= 15% of peak
    - Transition: everything else

Override:
  Users can disable auto-detection and force a season via the HA options
  flow (stored as CONF_BATTERY_SEASON_OVERRIDE).

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Season constants ──────────────────────────────────────────────────────────
SEASON_SUMMER     = "summer"
SEASON_WINTER     = "winter"
SEASON_TRANSITION = "transition"

# Day-length thresholds (hours of daylight)
SUMMER_DAY_LENGTH_H  = 14.0   # >= this → summer-like
WINTER_DAY_LENGTH_H  =  9.0   # <= this → winter-like

# PV output thresholds (% of learned peak_power_w)
SUMMER_PV_PCT  = 60.0   # >= this → summer-like
WINTER_PV_PCT  = 15.0   # <= this → winter-like

# Charge/discharge hours per season
CHARGE_HOURS: dict[str, int] = {
    SEASON_SUMMER:     2,   # PV does the heavy lifting
    SEASON_WINTER:     5,   # Need more cheap-rate charging
    SEASON_TRANSITION: 3,   # Default
}
DISCHARGE_HOURS: dict[str, int] = {
    SEASON_SUMMER:     4,   # Long evening peak
    SEASON_WINTER:     3,   # Shorter heating peak
    SEASON_TRANSITION: 3,
}

# Preferred discharge window per season (hours, inclusive)
DISCHARGE_WINDOW: dict[str, tuple[int, int]] = {
    SEASON_SUMMER:     (17, 22),   # Long summer evening
    SEASON_WINTER:     (16, 20),   # Earlier heating peak
    SEASON_TRANSITION: (17, 21),
}

# PV forecast threshold: if expected solar > this fraction of battery
# max charge power, skip the scheduled charge slot (solar will do it)
PV_SKIP_CHARGE_RATIO = 0.55


@dataclass
class SeasonalParameters:
    """Parameters the BatteryEPEXScheduler uses for the current season."""
    season:           str          # summer | winter | transition
    charge_hours:     int
    discharge_hours:  int
    discharge_window: tuple[int, int]   # (start_hour, end_hour) inclusive
    skip_pv_hours:    list[int]    # hours where PV is expected to charge battery
    reason:           str          # human-readable explanation
    auto_detected:    bool         # False when user forced override


def day_length_hours(latitude_deg: float, day_of_year: int) -> float:
    """Calculate approximate daylight hours for a given latitude and day.

    Uses the standard sunrise-equation approximation (Spencer 1971).
    Accurate to ±10 minutes for |lat| < 65°.

    Args:
        latitude_deg: Geographic latitude in degrees (-90..90).
        day_of_year:  Day number (1=Jan 1, 365=Dec 31).

    Returns:
        Daylight hours (0..24).
    """
    lat_rad = math.radians(latitude_deg)

    # Solar declination (radians)
    B = math.radians((360 / 365) * (day_of_year - 81))
    decl = math.radians(23.45 * math.sin(B))

    # Hour angle at sunrise/sunset
    cos_ha = -math.tan(lat_rad) * math.tan(decl)

    # Clamp to [-1, 1] to avoid domain errors near poles
    cos_ha = max(-1.0, min(1.0, cos_ha))

    ha_deg = math.degrees(math.acos(cos_ha))
    return round(2 * ha_deg / 15.0, 2)   # convert hour-angle to hours


def detect_season(
    latitude_deg: float,
    pv_avg_14d_w: Optional[float],
    pv_peak_w:    Optional[float],
) -> str:
    """Determine current season from day-length and PV history.

    Args:
        latitude_deg:  HA's configured latitude.
        pv_avg_14d_w:  14-day rolling average PV output (W). None if unknown.
        pv_peak_w:     Learned all-time peak PV output (W). None if unknown.

    Returns:
        SEASON_SUMMER | SEASON_WINTER | SEASON_TRANSITION
    """
    doy       = date.today().timetuple().tm_yday
    day_len   = day_length_hours(latitude_deg, doy)
    pv_pct    = None

    if pv_avg_14d_w is not None and pv_peak_w and pv_peak_w > 0:
        pv_pct = (pv_avg_14d_w / pv_peak_w) * 100.0

    # Summer: long days OR lots of PV
    is_summer = day_len >= SUMMER_DAY_LENGTH_H or (pv_pct is not None and pv_pct >= SUMMER_PV_PCT)
    # Winter: short days AND little PV (or unknown)
    is_winter = day_len <= WINTER_DAY_LENGTH_H and (pv_pct is None or pv_pct <= WINTER_PV_PCT)

    if is_summer:
        return SEASON_SUMMER
    if is_winter:
        return SEASON_WINTER
    return SEASON_TRANSITION


def build_seasonal_parameters(
    *,
    latitude_deg:     float,
    pv_avg_14d_w:     Optional[float],
    pv_peak_w:        Optional[float],
    pv_forecast_today_kwh: Optional[float],
    battery_capacity_kwh:  float,
    battery_max_charge_w:  float,
    pv_forecast_hourly:    list,        # [{hour, forecast_w, ...}]
    override:         Optional[str],    # "summer" | "winter" | "transition" | None
) -> SeasonalParameters:
    """Build the full seasonal parameter set for the battery scheduler.

    Args:
        latitude_deg:          HA latitude (from hass.config.latitude).
        pv_avg_14d_w:          14-day rolling average PV output in W.
        pv_peak_w:             All-time peak PV output in W.
        pv_forecast_today_kwh: Today's total PV forecast in kWh.
        battery_capacity_kwh:  Usable battery capacity in kWh.
        battery_max_charge_w:  Maximum charge rate in W.
        pv_forecast_hourly:    Hourly PV forecast list from coordinator.
        override:              Forced season string or None for auto-detect.

    Returns:
        SeasonalParameters ready to hand to the scheduler.
    """
    doy     = date.today().timetuple().tm_yday
    day_len = day_length_hours(latitude_deg, doy)

    if override and override in (SEASON_SUMMER, SEASON_WINTER, SEASON_TRANSITION):
        season       = override
        auto_detected = False
        reason_prefix = f"Handmatig ingesteld op {season}"
    else:
        season        = detect_season(latitude_deg, pv_avg_14d_w, pv_peak_w)
        auto_detected = True

        pv_pct = None
        if pv_avg_14d_w is not None and pv_peak_w and pv_peak_w > 0:
            pv_pct = (pv_avg_14d_w / pv_peak_w) * 100.0

        if season == SEASON_SUMMER:
            reason_prefix = (
                f"Zomer gedetecteerd (daglengte {day_len:.1f}u"
                + (f", PV avg {pv_pct:.0f}% van piek" if pv_pct is not None else "")
                + ")"
            )
        elif season == SEASON_WINTER:
            reason_prefix = (
                f"Winter gedetecteerd (daglengte {day_len:.1f}u"
                + (f", PV avg {pv_pct:.0f}% van piek" if pv_pct is not None else "")
                + ")"
            )
        else:
            reason_prefix = f"Overgang gedetecteerd (daglengte {day_len:.1f}u)"

    c_hours   = CHARGE_HOURS[season]
    d_hours   = DISCHARGE_HOURS[season]
    d_window  = DISCHARGE_WINDOW[season]

    # Build list of hours where PV is expected to charge battery
    # (so we can skip net-charging in those hours)
    skip_pv_hours: list[int] = []
    if season in (SEASON_SUMMER, SEASON_TRANSITION) and pv_forecast_hourly:
        for slot in pv_forecast_hourly:
            h     = slot.get("hour", -1)
            fc_w  = slot.get("forecast_w", 0)
            # Skip this hour for net-charging if PV covers > threshold of charge rate
            if 0 <= h <= 23 and fc_w >= battery_max_charge_w * PV_SKIP_CHARGE_RATIO:
                if h not in skip_pv_hours:
                    skip_pv_hours.append(h)

    # Extra info in reason
    if skip_pv_hours:
        reason_prefix += f" — PV dekt laden op uren {sorted(skip_pv_hours)}"

    _LOGGER.debug(
        "SeasonalStrategy: season=%s auto=%s charge_h=%d disch_h=%d skip=%s",
        season, auto_detected, c_hours, d_hours, skip_pv_hours,
    )

    return SeasonalParameters(
        season           = season,
        charge_hours     = c_hours,
        discharge_hours  = d_hours,
        discharge_window = d_window,
        skip_pv_hours    = skip_pv_hours,
        reason           = reason_prefix,
        auto_detected    = auto_detected,
    )
