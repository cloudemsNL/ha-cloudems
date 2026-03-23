# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
SubsidyAdvisor — v1.1.0

Calculates the personal financial impact of net metering phase-out (2025–2027)
and provides concrete battery investment advice.

Uses the household's actual historical data (via SelfConsumptionTracker and
BillSimulator) to calculate:
  1. How much is currently netted per year (kWh)
  2. What that net metering is worth in euros
  3. What is lost per phase of the phase-out
  4. Which battery size most efficiently limits the damage
  5. When that battery pays itself back

Subsidies tracked:
  - Net metering WEK (statutory phase-out schedule, NL)
  - SDE++ (not applicable to small consumers)
  - VAT exemption solar panels (NL 2023+)

NL net metering phase-out (Wet Elektriciteitsproductie Kleinschalig):
  2025 → 64% of purchase price compensated for feed-in
  2026 → 36%
  2027 →  0% (fully abolished)

Output:
  - Current annual net metering benefit (€)
  - Loss per year in 2025/2026/2027 (€)
  - Optimal battery size + payback period
  - Plain-language advice
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Net metering phase-out schedule per year (fraction of purchase price paid for feed-in)
NET_METERING_SCHEDULE: dict[str, dict[int, float]] = {
    "NL": {2024: 1.00, 2025: 0.64, 2026: 0.36, 2027: 0.00},
    "BE": {2024: 1.00, 2025: 1.00, 2026: 1.00, 2027: 1.00},  # no phase-out
    "DE": {2024: 0.00, 2025: 0.00, 2026: 0.00, 2027: 0.00},  # no net metering
    "FR": {2024: 1.00, 2025: 1.00, 2026: 1.00, 2027: 1.00},
    "GB": {2024: 0.50, 2025: 0.50, 2026: 0.50, 2027: 0.50},
}

BATTERY_PRICE_EUR_KWH    = 800    # €/kWh installed (market average 2025)
SELF_CONS_GAIN_PER_KWH   = 0.07   # extra self-consumption per kWh battery (ECN/RVO)


@dataclass
class NetMeteringImpact:
    year:               int
    pct:                float
    export_kwh:         float
    buy_price_eur_kwh:  float
    old_revenue_eur:    float   # at 100% net metering
    new_revenue_eur:    float   # at this %
    loss_eur:           float   # annual loss vs current


@dataclass
class BatteryAdvice:
    battery_kwh:         int
    extra_self_cons_pct: float
    annual_saving_eur:   float   # vs no battery at 0% net metering
    investment_eur:      float
    payback_years:       Optional[float]
    recommended:         bool


class SubsidyAdvisor:
    """Calculates net metering impact and battery investment advice."""

    def __init__(self, config: dict) -> None:
        self._config  = config
        self._country = config.get("country", "NL").upper()

    def calculate(
        self,
        annual_export_kwh:     float,
        annual_import_kwh:     float,
        annual_pv_kwh:         float,
        current_buy_price_eur: float,
        current_sell_price_eur: float,
        existing_battery_kwh:  float = 0.0,
    ) -> dict:
        """
        Full net metering + battery investment analysis.

        Parameters:
          annual_export_kwh      — kWh fed into the grid last year
          annual_import_kwh      — kWh purchased from the grid
          annual_pv_kwh          — total PV production
          current_buy_price_eur  — all-in purchase price €/kWh (incl. taxes)
          current_sell_price_eur — current feed-in tariff €/kWh
          existing_battery_kwh   — already installed battery capacity (kWh)
        """
        if annual_export_kwh <= 0 or annual_pv_kwh <= 0:
            return {"error": "insufficient_data"}

        schedule          = NET_METERING_SCHEDULE.get(self._country, NET_METERING_SCHEDULE["NL"])
        current_self_cons = (annual_pv_kwh - annual_export_kwh) / annual_pv_kwh

        # Current value of net metering (at 100%)
        current_nm_value  = annual_export_kwh * current_buy_price_eur

        # Impact per year
        impacts: list[NetMeteringImpact] = []
        current_year = datetime.now(timezone.utc).year
        for year in range(max(current_year, 2025), 2029):
            pct     = schedule.get(year, 0.0)
            old_rev = annual_export_kwh * current_buy_price_eur
            new_rev = annual_export_kwh * current_sell_price_eur
            loss    = old_rev - new_rev if pct < 1.0 else 0.0
            impacts.append(NetMeteringImpact(
                year              = year,
                pct               = pct,
                export_kwh        = annual_export_kwh,
                buy_price_eur_kwh = current_buy_price_eur,
                old_revenue_eur   = old_rev,
                new_revenue_eur   = new_rev,
                loss_eur          = max(0.0, loss),
            ))

        loss_at_zero = annual_export_kwh * (current_buy_price_eur - current_sell_price_eur)

        # Battery advice — simulate 5/10/15/20 kWh extra on top of existing
        battery_sizes = [0, 5, 10, 15, 20]
        advices: list[BatteryAdvice] = []
        for extra_kwh in battery_sizes:
            total_kwh      = existing_battery_kwh + extra_kwh
            extra_self     = min(0.95 - current_self_cons, total_kwh * SELF_CONS_GAIN_PER_KWH)
            new_self_cons  = current_self_cons + extra_self
            new_export_kwh = annual_pv_kwh * (1 - new_self_cons)
            reduced_export = annual_export_kwh - new_export_kwh

            # Saving at 0% net metering: less export × (buy - sell)
            annual_saving  = reduced_export * (current_buy_price_eur - current_sell_price_eur)
            investment     = extra_kwh * BATTERY_PRICE_EUR_KWH
            payback        = investment / annual_saving if annual_saving > 0 and extra_kwh > 0 else None
            recommended    = (payback is not None and payback <= 10 and extra_kwh > 0)

            advices.append(BatteryAdvice(
                battery_kwh         = int(extra_kwh),
                extra_self_cons_pct = round(extra_self * 100, 1),
                annual_saving_eur   = round(annual_saving, 2),
                investment_eur      = investment,
                payback_years       = round(payback, 1) if payback else None,
                recommended         = recommended,
            ))

        best = next((a for a in advices if a.recommended), None)
        if not best and advices:
            best = max(advices, key=lambda a: a.annual_saving_eur)

        return {
            "country":                    self._country,
            "annual_export_kwh":          round(annual_export_kwh, 0),
            "annual_pv_kwh":              round(annual_pv_kwh, 0),
            "current_self_cons_pct":      round(current_self_cons * 100, 1),
            "current_nm_value_eur":       round(current_nm_value, 2),
            "loss_at_zero_pct_eur":       round(loss_at_zero, 2),
            "impacts": [
                {
                    "year":     i.year,
                    "pct":      round(i.pct * 100),
                    "loss_eur": round(i.loss_eur, 2),
                }
                for i in impacts
            ],
            "battery_advice": [
                {
                    "extra_kwh":        a.battery_kwh,
                    "annual_saving_eur": a.annual_saving_eur,
                    "investment_eur":   a.investment_eur,
                    "payback_years":    a.payback_years,
                    "recommended":      a.recommended,
                }
                for a in advices
            ],
            "best_advice": {
                "extra_kwh":     best.battery_kwh if best else 0,
                "payback_years": best.payback_years if best else None,
                "annual_saving": best.annual_saving_eur if best else 0,
            },
        }
