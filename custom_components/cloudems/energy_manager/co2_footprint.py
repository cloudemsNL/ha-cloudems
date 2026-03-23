# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CO2FootprintTracker — v1.1.0

Tracks the CO2 footprint of household energy consumption.

Uses real-time CO2 intensity from NationalGridMonitor (if configured) or
country-specific average values as fallback.

Metrics:
  - CO2 today (g) — based on grid import × intensity
  - CO2 avoided today (g) — based on solar production
  - CO2 per kWh current (g/kWh) — real-time grid intensity
  - Equivalent car kilometres (for easy communication to users)
  - Badge: own_emissions vs nl_average_household for comparison

NL average household: ~3.5 MWh/year grid import → ~805 kg CO2/year
                       → ~2200 g CO2/day
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Average household CO2 per day per country (g) — for badge comparison
AVG_HOUSEHOLD_CO2_DAY_G: dict[str, float] = {
    "NL": 2200.0,
    "DE": 3100.0,
    "BE": 1900.0,
    "FR": 700.0,
    "GB": 2100.0,
}

# Average grid CO2 intensity (g/kWh) per country — used if no live data
DEFAULT_INTENSITY: dict[str, float] = {
    "NL": 230.0,
    "DE": 350.0,
    "BE": 170.0,
    "FR": 65.0,
    "GB": 180.0,
}

# Car emission factor (g CO2/km) — EU average petrol car
CAR_CO2_G_PER_KM = 120.0


class CO2FootprintTracker:
    """Tracks household CO2 footprint from energy consumption."""

    def __init__(self, country: str = "NL") -> None:
        self._country   = country.upper()
        self._today_g   = 0.0    # CO2 emitted today (g)
        self._avoided_g = 0.0    # CO2 avoided by solar today (g)
        self._last_hour = -1

    def tick(
        self,
        grid_import_kwh_this_hour: float,
        solar_kwh_this_hour:       float,
        co2_intensity_g_kwh:       Optional[float] = None,
    ) -> dict:
        """
        Update footprint for the current hour's energy.

        grid_import_kwh_this_hour — energy drawn from grid this hour (kWh)
        solar_kwh_this_hour       — solar production this hour (kWh)
        co2_intensity_g_kwh       — live grid intensity; uses country default if None
        """
        now_hour  = datetime.now(timezone.utc).hour
        intensity = co2_intensity_g_kwh if co2_intensity_g_kwh is not None \
                    else DEFAULT_INTENSITY.get(self._country, 250.0)

        if now_hour != self._last_hour:
            # Accumulate hourly totals
            self._today_g   += grid_import_kwh_this_hour * intensity
            # Avoided = solar that displaces grid (assume same intensity)
            self._avoided_g += solar_kwh_this_hour * intensity
            self._last_hour  = now_hour

        # Reset at midnight
        if now_hour == 0 and self._last_hour > 0:
            self._today_g   = 0.0
            self._avoided_g = 0.0

        avg_day_g    = AVG_HOUSEHOLD_CO2_DAY_G.get(self._country, 2200.0)
        badge_pct    = round((self._today_g / max(avg_day_g, 1)) * 100, 1)
        car_km_equiv = round(self._today_g / CAR_CO2_G_PER_KM, 1)

        return {
            "today_g":          round(self._today_g, 0),
            "avoided_g":        round(self._avoided_g, 0),
            "intensity_g_kwh":  round(intensity, 1),
            "badge_pct":        badge_pct,          # 100 = average household
            "car_km_equiv":     car_km_equiv,
            "country":          self._country,
        }

    def reset_day(self) -> None:
        self._today_g   = 0.0
        self._avoided_g = 0.0

    @property
    def today_g(self) -> float:
        return self._today_g

    @property
    def avoided_g(self) -> float:
        return self._avoided_g

    def get_data(self) -> dict:
        """Return current CO2 footprint data as dict."""
        return {
            "today_g":   round(self.today_g, 1),
            "avoided_g": round(self.avoided_g, 1),
            "today_kg":  round(self.today_g / 1000, 3),
        }
