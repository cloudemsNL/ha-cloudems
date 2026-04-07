# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
PaybackTracker — v1.0.0

Tracks the payback period of a home battery system.

Calculation:
  purchase_price - already_earned = remaining
  remaining / daily_rate = days_remaining

Purchase price:
  1. User configures exact amount
  2. Estimate: capacity_kwh × market_price_per_kwh
     - 2024: ~€850/kWh for complete installation
     - Age correction: -€50/kWh per year (depreciation)

Already earned (for existing installations):
  - If purchase date is known: extrapolate backwards using current daily rate
  - If unknown: show "unknown past, future projection only"

Persistence: cumulative revenue stored in HA Store.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

MARKET_PRICE_PER_KWH   = 850.0   # €/kWh complete installation (2024)
DEPRECIATION_PER_YEAR  = 50.0    # €/kWh per year (technical depreciation)
STORE_KEY = "cloudems_payback_tracker_v1"


class PaybackTracker:
    """Tracks payback period based on cumulative daily arbitrage revenue."""

    def __init__(self, hass, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._store   = None
        self._cumulative_eur:     float = 0.0
        self._tracking_start:     Optional[date] = None
        self._monthly_history:    list  = []
        self._daily_revenues:     list  = []

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, 1, STORE_KEY)
        await self._load()

    async def _load(self) -> None:
        try:
            saved = await self._store.async_load()
            if saved:
                self._cumulative_eur  = float(saved.get("cumulative_eur", 0))
                self._tracking_start  = (date.fromisoformat(saved["tracking_start"])
                                         if saved.get("tracking_start") else None)
                self._monthly_history = saved.get("monthly_history", [])
                self._daily_revenues  = saved.get("daily_revenues", [])
        except Exception as e:
            _LOGGER.debug("PaybackTracker load error: %s", e)

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "cumulative_eur":  round(self._cumulative_eur, 4),
                "tracking_start":  self._tracking_start.isoformat() if self._tracking_start else None,
                "monthly_history": self._monthly_history[-24:],
                "daily_revenues":  self._daily_revenues[-90:],
            })
        except Exception as e:
            _LOGGER.debug("PaybackTracker save error: %s", e)

    def feed_zonneplan_data(self,
                           total_earned_eur:   float,
                           today_eur:          float,
                           monthly_history:    list,
                           yearly_history:     list,
                           install_date:       str   = "",
                           days_since_install: int   = 0) -> None:
        """
        Feed real Zonneplan earnings directly into the tracker.

        All values come from Zonneplan integration sensors — no estimation needed.

        Args:
            total_earned_eur:   All-time battery earnings (e.g. €827.17)
            today_eur:          Today's earnings
            monthly_history:    Monthly breakdown from result_this_month
            yearly_history:     Yearly breakdown from result_this_year
            install_date:       ISO date from first_measured_at (e.g. "2024-12-13")
            days_since_install: Days since first_measured_at
        """
        from datetime import date
        self._zonneplan_total_earned    = total_earned_eur
        self._zonneplan_today           = today_eur
        self._zonneplan_install_date    = install_date
        self._zonneplan_days_installed  = days_since_install

        if monthly_history or yearly_history:
            self._zonneplan_monthly_history = monthly_history or yearly_history

        # Use Zonneplan install date as tracking start if available
        if install_date and not self._tracking_start:
            try:
                self._tracking_start = date.fromisoformat(install_date)
            except ValueError:
                self._tracking_start = date.today()
        elif not self._tracking_start:
            self._tracking_start = date.today()

    def record_daily_revenue(self, revenue_eur: float, charge_kwh: float,
                             discharge_kwh: float) -> None:
        """Record daily revenue — call at midnight rollover."""
        today = date.today()
        if not self._tracking_start:
            self._tracking_start = today

        self._cumulative_eur += revenue_eur
        self._daily_revenues.append({
            "date":          today.isoformat(),
            "revenue_eur":   round(revenue_eur, 4),
            "charge_kwh":    round(charge_kwh, 3),
            "discharge_kwh": round(discharge_kwh, 3),
        })
        self._daily_revenues = self._daily_revenues[-90:]

        month_key = today.strftime("%Y-%m")
        existing  = next((m for m in self._monthly_history if m["month"] == month_key), None)
        if existing:
            existing["revenue_eur"]   += revenue_eur
            existing["charge_kwh"]    += charge_kwh
            existing["discharge_kwh"] += discharge_kwh
        else:
            self._monthly_history.append({
                "month":          month_key,
                "revenue_eur":    round(revenue_eur, 4),
                "charge_kwh":     round(charge_kwh, 3),
                "discharge_kwh":  round(discharge_kwh, 3),
            })

    def get_purchase_price(self, capacity_kwh: float) -> dict:
        """Return purchase price — configured or estimated from capacity and age."""
        cfg_price = self._config.get("battery_purchase_price_eur")
        cfg_date  = self._config.get("battery_purchase_date", "")

        if cfg_price and float(cfg_price) > 0:
            return {
                "source": "configured",
                "price":  float(cfg_price),
                "note":   "Configured purchase price",
            }

        base_price   = capacity_kwh * MARKET_PRICE_PER_KWH
        years_old    = 0.0
        if cfg_date:
            try:
                years_old = (date.today() - date.fromisoformat(cfg_date)).days / 365.25
            except ValueError:
                pass
        depreciation = years_old * DEPRECIATION_PER_YEAR * capacity_kwh
        est_price    = max(base_price * 0.3, base_price - depreciation)

        return {
            "source":      "estimated",
            "price":       round(est_price, 0),
            "base_price":  round(base_price, 0),
            "years_old":   round(years_old, 1),
            "depreciation": round(depreciation, 0),
            "note":        (f"Estimate: {capacity_kwh:.1f} kWh × €{MARKET_PRICE_PER_KWH:.0f}/kWh"
                           + (f" - {years_old:.1f} yr depreciation" if years_old > 0 else "")
                           + " — set purchase price for exact value"),
        }

    def get_daily_rate(self) -> float:
        """Average daily revenue (€/day) over last 30 days."""
        recent = self._daily_revenues[-30:]
        if not recent:
            return 0.0
        return sum(d.get("revenue_eur", 0) for d in recent) / len(recent)

    def to_dict(self, capacity_kwh: float = 10.0) -> dict:
        from datetime import date
        purchase      = self.get_purchase_price(capacity_kwh)
        purchase_p    = purchase["price"]

        # Prefer real Zonneplan earnings over our estimated P&L
        zp_total = getattr(self, "_zonneplan_total_earned", None)
        zp_today = getattr(self, "_zonneplan_today", None)
        zp_monthly = getattr(self, "_zonneplan_monthly_history", [])

        if zp_total is not None:
            # Use Zonneplan's actual cumulative earnings
            _LOGGER.info(
                "PaybackTracker: using live Zonneplan data — "
                "total_earned=€%.2f, today=€%.4f, monthly_months=%d",
                zp_total, zp_today or 0, len(zp_monthly),
            )
            total_earned   = zp_total
            already_earned = 0.0  # already included in total_earned

            # Best daily rate: total_earned / days_since_install (most accurate)
            zp_days = getattr(self, "_zonneplan_days_installed", 0)
            if zp_days and zp_days > 7 and zp_total > 0:
                # Primary: actual average since installation date
                daily_rate  = zp_total / zp_days
                rate_basis  = f"avg over {zp_days} days since install"
            elif zp_monthly:
                # Secondary: last 3 months from Zonneplan monthly data
                recent_months = zp_monthly[-3:]
                total_days    = sum(len(m.get("days", [])) or 30 for m in recent_months
                                    if isinstance(m, dict))
                total_rev     = sum(float(m.get("total_result", 0) or 0)
                                    for m in recent_months if isinstance(m, dict))
                daily_rate    = (total_rev / total_days) if total_days > 0 else (zp_today or 0)
                rate_basis    = "avg over last 3 months"
            else:
                # Fallback: today's earnings
                daily_rate = zp_today if zp_today else self.get_daily_rate()
                rate_basis = "today only (limited data)"

            data_source = "zonneplan_live"
        else:
            _LOGGER.info(
                "PaybackTracker: using CloudEMS estimated P&L — "
                "cumulative=€%.2f, daily_rate=€%.4f. "
                "Install ha-zonneplan-one for live data.",
                self._cumulative_eur, self.get_daily_rate(),
            )
            # Fallback to our own tracking
            daily_rate     = self.get_daily_rate()
            cfg_date       = self._config.get("battery_purchase_date", "")
            already_earned = 0.0
            if cfg_date and self._tracking_start and daily_rate > 0:
                try:
                    days_before   = (self._tracking_start - date.fromisoformat(cfg_date)).days
                    already_earned = max(0, daily_rate * days_before)
                except ValueError:
                    pass
            total_earned  = self._cumulative_eur + already_earned
            data_source   = "cloudems_estimated"
        remaining    = max(0.0, purchase_p - total_earned)
        tracking_days = ((date.today() - self._tracking_start).days
                         if self._tracking_start else 0)
        data_source_note = (
            "Based on live Zonneplan earnings data" if data_source == "zonneplan_live"
            else "Based on CloudEMS estimated arbitrage P&L — install ha-zonneplan-one for accuracy"
        )

        days_remaining   = (remaining / daily_rate) if daily_rate > 0.001 else None
        payback_date     = ((date.today() + timedelta(days=days_remaining)).isoformat()
                            if days_remaining else None)
        months_remaining = (days_remaining / 30.44) if days_remaining else None
        payback_pct      = min(100.0, total_earned / purchase_p * 100) if purchase_p > 0 else 0

        return {
            "purchase_price_eur":  purchase_p,
            "purchase_source":     purchase["source"],
            "purchase_note":       purchase["note"],
            "total_earned_eur":    round(total_earned, 2),
            "cumulative_eur":      round(self._cumulative_eur, 2),
            "already_earned_eur":  round(already_earned, 2),
            "remaining_eur":       round(remaining, 2),
            "daily_rate_eur":      round(daily_rate, 4),
            "monthly_rate_eur":    round(daily_rate * 30.44, 2),
            "payback_pct":         round(payback_pct, 1),
            "days_remaining":      round(days_remaining, 0) if days_remaining else None,
            "months_remaining":    round(months_remaining, 1) if months_remaining else None,
            "payback_date":        payback_date,
            "tracking_days":       tracking_days,
            "monthly_history":     self._monthly_history[-12:],
            "daily_revenues":      self._daily_revenues[-30:],
            "data_source":         data_source,
            "data_source_note":    data_source_note,
            "install_date":        getattr(self, "_zonneplan_install_date", None),
            "days_since_install":  getattr(self, "_zonneplan_days_installed", None),
            "rate_basis":          locals().get("rate_basis", "estimated"),
        }
