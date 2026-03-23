# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CO2FootprintTracker — v1.1.0

Tracks the CO2 footprint of household energy consumption and savings,
compared to the average household in the configured country.

Three streams:
  import_co2_g   — CO2 from grid import (grid_intensity × kWh_import)
  export_co2_g   — CO2 avoided by feed-in (grid × kWh_export)
  solar_co2_g    — CO2 avoided by self-consumption (grid × kWh_self_consumed)

NL average household: ~2800 kWh/year net import → ~560 kg CO2/year
(CBS 2024, average intensity 200 g/kWh)

Displays:
  - CO2 today (grams)
  - CO2 saved today vs country average (grams)
  - CO2 this year (kg)
  - Equivalents: kg beef, car kilometres, flights
  - Badge: Excellent / Good / Average / Above average
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_co2_footprint_v1"
STORAGE_VERSION = 1

# Average household daily CO2 (grams) per country
AVG_DAILY_CO2_G: dict[str, float] = {
    "NL": 1534.0,   # 560 kg/year ÷ 365
    "DE": 2329.0,   # 850 kg/year ÷ 365
    "BE": 1315.0,   # 480 kg/year ÷ 365
    "FR": 493.0,    # 180 kg/year ÷ 365
    "GB": 1644.0,   # 600 kg/year ÷ 365
}
DEFAULT_AVG_DAILY_CO2_G = 1534.0

# Default grid CO2 intensity (g/kWh) per country
DEFAULT_INTENSITY_G_KWH: dict[str, float] = {
    "NL": 200.0,
    "DE": 350.0,
    "BE": 170.0,
    "FR": 65.0,
    "GB": 180.0,
}

# CO2 equivalents for user-friendly display
CO2_KG_PER_KG_BEEF        = 27.0    # kg CO2 per kg beef (Our World in Data)
CO2_KG_PER_CAR_KM         = 0.170   # kg CO2 per km (average EU petrol car)
CO2_KG_PER_FLIGHT_AMS_BCN = 130.0   # kg CO2 Amsterdam–Barcelona return


class CO2FootprintTracker:
    """Accumulates CO2 emissions and savings per day and year."""

    def __init__(self, hass, country: str = "NL") -> None:
        self._hass    = hass
        self._country = country.upper()
        self._store   = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Today
        self._today_date         = ""
        self._today_import_g     = 0.0   # CO2 from grid import
        self._today_export_g     = 0.0   # CO2 avoided via feed-in
        self._today_solar_g      = 0.0   # CO2 avoided via self-consumption
        self._today_import_kwh   = 0.0
        self._today_export_kwh   = 0.0
        self._today_solar_kwh    = 0.0

        # Year
        self._year               = 0
        self._year_import_g      = 0.0
        self._year_export_g      = 0.0
        self._year_solar_g       = 0.0

        self._dirty     = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        year  = datetime.now(timezone.utc).year

        if saved.get("today_date") == today:
            self._today_date       = today
            self._today_import_g   = float(saved.get("today_import_g", 0))
            self._today_export_g   = float(saved.get("today_export_g", 0))
            self._today_solar_g    = float(saved.get("today_solar_g", 0))
            self._today_import_kwh = float(saved.get("today_import_kwh", 0))
            self._today_export_kwh = float(saved.get("today_export_kwh", 0))
            self._today_solar_kwh  = float(saved.get("today_solar_kwh", 0))

        if saved.get("year") == year:
            self._year          = year
            self._year_import_g = float(saved.get("year_import_g", 0))
            self._year_export_g = float(saved.get("year_export_g", 0))
            self._year_solar_g  = float(saved.get("year_solar_g", 0))
        else:
            self._year = year

        _LOGGER.info(
            "CO2FootprintTracker: loaded (today import=%.0fg, solar=%.0fg)",
            self._today_import_g, self._today_solar_g
        )

    def tick(
        self,
        interval_s:    float,
        import_w:      float,
        export_w:      float,
        solar_w:       float,
        co2_intensity: float,   # g CO2/kWh current grid
    ) -> None:
        """Process one measurement (10-second interval)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        year  = datetime.now(timezone.utc).year

        # New day reset
        if self._today_date and self._today_date != today:
            self._today_import_g   = 0.0
            self._today_export_g   = 0.0
            self._today_solar_g    = 0.0
            self._today_import_kwh = 0.0
            self._today_export_kwh = 0.0
            self._today_solar_kwh  = 0.0
        self._today_date = today

        # New year reset
        if self._year != year:
            self._year_import_g = 0.0
            self._year_export_g = 0.0
            self._year_solar_g  = 0.0
            self._year = year

        # kWh this interval
        factor   = interval_s / 3_600_000.0   # W → kWh
        imp_kwh  = max(0.0, import_w) * factor
        exp_kwh  = max(0.0, export_w) * factor
        sol_kwh  = max(0.0, solar_w)  * factor

        # Self-consumption = solar - export (what stays in the house)
        self_kwh = max(0.0, sol_kwh - exp_kwh)

        # CO2 grams
        imp_g = imp_kwh  * co2_intensity
        exp_g = exp_kwh  * co2_intensity   # avoided by feed-in
        sol_g = self_kwh * co2_intensity   # avoided by self-consumption

        self._today_import_g   += imp_g
        self._today_export_g   += exp_g
        self._today_solar_g    += sol_g
        self._today_import_kwh += imp_kwh
        self._today_export_kwh += exp_kwh
        self._today_solar_kwh  += sol_kwh

        self._year_import_g += imp_g
        self._year_export_g += exp_g
        self._year_solar_g  += sol_g

        self._dirty = True

    # ── Derived values ────────────────────────────────────────────────────────

    @property
    def today_net_co2_g(self) -> float:
        """Net CO2 today (grams): import - export_avoided - solar_avoided."""
        return max(0.0, self._today_import_g - self._today_export_g - self._today_solar_g)

    @property
    def today_saved_vs_avg_g(self) -> float:
        """Savings vs country average household (grams). Positive = better than average."""
        avg = AVG_DAILY_CO2_G.get(self._country, DEFAULT_AVG_DAILY_CO2_G)
        return avg - self.today_net_co2_g

    @property
    def year_net_co2_kg(self) -> float:
        """Net CO2 this year (kg)."""
        return max(0.0, self._year_import_g - self._year_export_g - self._year_solar_g) / 1000.0

    @property
    def badge(self) -> str:
        avg = AVG_DAILY_CO2_G.get(self._country, DEFAULT_AVG_DAILY_CO2_G)
        pct = self.today_net_co2_g / avg if avg else 0
        if pct < 0.50:  return "excellent"
        if pct < 0.85:  return "good"
        if pct < 1.15:  return "average"
        return "above_average"

    def get_equivalents(self) -> dict:
        """CO2 in recognisable units."""
        kg = self.year_net_co2_kg
        return {
            "kg_beef":            round(kg / CO2_KG_PER_KG_BEEF, 1),
            "car_km":             round(kg / CO2_KG_PER_CAR_KM, 0),
            "flights_ams_bcn":    round(kg / CO2_KG_PER_FLIGHT_AMS_BCN, 2),
        }

    def get_data(self) -> dict:
        eq  = self.get_equivalents()
        avg = AVG_DAILY_CO2_G.get(self._country, DEFAULT_AVG_DAILY_CO2_G)
        return {
            "today_net_co2_g":      round(self.today_net_co2_g, 0),
            "today_import_g":       round(self._today_import_g, 0),
            "today_solar_saved_g":  round(self._today_solar_g, 0),
            "today_export_saved_g": round(self._today_export_g, 0),
            "today_vs_avg_g":       round(self.today_saved_vs_avg_g, 0),
            "year_net_co2_kg":      round(self.year_net_co2_kg, 2),
            "badge":                self.badge,
            "avg_daily_g":          avg,
            "eq_beef_kg":           eq["kg_beef"],
            "eq_car_km":            eq["car_km"],
            "eq_flights":           eq["flights_ams_bcn"],
            "country":              self._country,
        }

    async def async_maybe_save(self) -> None:
        if not self._dirty or (time.monotonic() - self._last_save) < 300:
            return
        await self._store.async_save({
            "today_date":       self._today_date,
            "today_import_g":   round(self._today_import_g, 2),
            "today_export_g":   round(self._today_export_g, 2),
            "today_solar_g":    round(self._today_solar_g, 2),
            "today_import_kwh": round(self._today_import_kwh, 4),
            "today_export_kwh": round(self._today_export_kwh, 4),
            "today_solar_kwh":  round(self._today_solar_kwh, 4),
            "year":             self._year,
            "year_import_g":    round(self._year_import_g, 2),
            "year_export_g":    round(self._year_export_g, 2),
            "year_solar_g":     round(self._year_solar_g, 2),
        })
        self._dirty     = False
        self._last_save = time.monotonic()
