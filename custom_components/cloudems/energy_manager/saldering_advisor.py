# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
NetMeteringAdvisor — v1.1.0

Provides personalised advice on the impact of net metering phase-out
based on the household's actual historical export.

Difference from NetMeteringSimulator:
  NetMeteringSimulator: technical calculation (€/year per scenario)
  NetMeteringAdvisor:   plain-language personal advice + action plan

Advice structure:
  1. What will I lose? (€/year at 0% net metering in 2027)
  2. What does my current battery already cover? (%)
  3. What is the recommendation? (concrete action plan)
  4. ROI calculation for extra battery capacity

Country-specific phase-out schedules:
  NL (WEK, Staatsblad 2023): 2025→64% | 2026→36% | 2027→0%
  BE: no net metering phase-out (capacity tariff replaces it in Flanders)
  DE: no net metering (feed-in tariff model)
  FR/other: configurable
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Phase-out schedule per country, per year (fraction of export that is netted)
PHASE_OUT_SCHEDULE: dict[str, dict[int, float]] = {
    "NL": {2025: 0.64, 2026: 0.36, 2027: 0.00},
    "BE": {2025: 1.00, 2026: 1.00, 2027: 1.00},  # no phase-out
    "DE": {2025: 0.00, 2026: 0.00, 2027: 0.00},  # no net metering in DE
    "FR": {2025: 1.00, 2026: 1.00, 2027: 1.00},
    "GB": {2025: 0.50, 2026: 0.50, 2027: 0.50},  # SEG flat rate
}
DEFAULT_SCHEDULE = {2025: 1.00, 2026: 1.00, 2027: 1.00}

# Expected feed-in compensation rate at 0% net metering (EUR/kWh)
FEED_IN_RATE_EUR_KWH = 0.06

# Extra self-consumption per kWh of battery capacity (average NL, ECN/RVO)
SELF_CONS_GAIN_PER_KWH = 0.07

# Battery cost per kWh of usable capacity (EUR/kWh, 2026 estimate)
BATTERY_EUR_PER_KWH = 650.0


class NetMeteringAdvisor:
    """Provides personalised net metering phase-out advice."""

    def __init__(self, country: str = "NL") -> None:
        self._last_result: Optional[dict] = None
        self._last_calc_hour: int = -1
        self._country = country.upper()

    def advise(
        self,
        annual_export_kwh:     float,
        annual_import_kwh:     float,
        avg_buy_price_eur_kwh: float,
        battery_capacity_kwh:  float = 0.0,
        current_self_cons_pct: float = 0.0,
    ) -> dict:
        """
        Calculate personalised net metering advice.

        annual_export_kwh     — annual feed-in (kWh)
        annual_import_kwh     — annual grid purchase (kWh)
        avg_buy_price_eur_kwh — average purchase price (€/kWh)
        battery_capacity_kwh  — usable battery capacity (kWh)
        current_self_cons_pct — current self-consumption ratio (0.0–1.0)
        """
        schedule = PHASE_OUT_SCHEDULE.get(self._country, DEFAULT_SCHEDULE)
        current_year = datetime.now(timezone.utc).year

        # Current value of net metering
        current_value_eur = annual_export_kwh * avg_buy_price_eur_kwh

        # Value at 0% net metering
        feed_in_value_eur = annual_export_kwh * FEED_IN_RATE_EUR_KWH

        # Annual loss when phase-out is complete
        annual_loss_eur = current_value_eur - feed_in_value_eur

        # Percentage covered by current battery
        if battery_capacity_kwh > 0:
            daily_buffer_kwh  = battery_capacity_kwh * 0.85  # usable SoC swing
            annual_buffer_kwh = daily_buffer_kwh * 300        # ~300 solar days/year
            battery_cover_pct = min(1.0, annual_buffer_kwh / max(annual_export_kwh, 1))
        else:
            battery_cover_pct = 0.0

        # Remaining uncovered export (kWh/year)
        uncovered_kwh = annual_export_kwh * (1 - battery_cover_pct)
        uncovered_loss_eur = uncovered_kwh * (avg_buy_price_eur_kwh - FEED_IN_RATE_EUR_KWH)

        # Extra battery capacity needed to fully cover remaining export
        if uncovered_kwh > 0:
            extra_kwh_needed = uncovered_kwh / (SELF_CONS_GAIN_PER_KWH * 300)
            extra_cost_eur   = extra_kwh_needed * BATTERY_EUR_PER_KWH
            roi_years        = extra_cost_eur / max(uncovered_loss_eur, 1)
        else:
            extra_kwh_needed = 0.0
            extra_cost_eur   = 0.0
            roi_years        = 0.0

        # Phase value by year
        phase_values = {}
        for year, fraction in schedule.items():
            if year >= current_year:
                netted_eur   = annual_export_kwh * fraction * avg_buy_price_eur_kwh
                feed_in_eur  = annual_export_kwh * (1 - fraction) * FEED_IN_RATE_EUR_KWH
                phase_values[year] = round(netted_eur + feed_in_eur, 2)

        # Urgency level
        if annual_loss_eur > 500:
            urgency = "high"
        elif annual_loss_eur > 200:
            urgency = "medium"
        else:
            urgency = "low"

        # Advice text (translated at UI level via strings.json)
        action_key = "add_battery" if roi_years < 7 and extra_kwh_needed > 1 else "no_action_needed"

        result = {
            "country":              self._country,
            "annual_export_kwh":    round(annual_export_kwh, 1),
            "annual_loss_eur":      round(annual_loss_eur, 2),
            "battery_cover_pct":    round(battery_cover_pct * 100, 1),
            "uncovered_loss_eur":   round(uncovered_loss_eur, 2),
            "extra_kwh_needed":     round(extra_kwh_needed, 1),
            "extra_cost_eur":       round(extra_cost_eur, 0),
            "roi_years":            round(roi_years, 1),
            "urgency":              urgency,
            "action_key":           action_key,
            "phase_values":         phase_values,
            "feed_in_rate":         FEED_IN_RATE_EUR_KWH,
        }
        self._last_result = result
        return result

    def get_cached(self) -> Optional[dict]:
        return self._last_result


# Backwards-compatible alias
SalderingAdvisor = NetMeteringAdvisor
