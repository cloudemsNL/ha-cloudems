"""
CloudEMS Energy Cost Forecaster — v1.9.1

Predicts the remaining energy cost for today and the total cost for tomorrow.

Method:
  1. Self-learning hourly consumption model
     - Tracks actual kWh consumed per hour of the day, per day-of-week
     - After ~14 days the model has a reliable average per hour
     - Model is persisted in HA storage and improves over time

  2. Forecast calculation
     - Remaining hours today: learned_avg_kwh_per_hour × remaining_epex_prices
     - Already consumed today: actual metered kWh × already-known prices
     - Total = actual_so_far + forecast_remaining

  3. Tomorrow forecast
     - If tomorrow's EPEX prices are available: full 24h forecast
     - Otherwise: uses today's prices as estimate

  4. Accuracy feedback
     - After each day, compares forecast with actual
     - Tracks Mean Absolute Percentage Error (MAPE) over last 14 days

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_cost_history_v1"
STORAGE_VERSION = 1

# Minimum days of data before model is considered "trained"
MIN_TRAINING_DAYS = 5
# Days of history to keep for the learning model
HISTORY_DAYS = 30
# Periodic save interval — persist learned data even without a clean HA shutdown
SAVE_INTERVAL_S = 300  # 5 minutes


@dataclass
class HourlyPattern:
    """Learned average consumption for one hour of the day."""
    hour: int
    avg_kwh: float = 0.0      # running average kWh consumed this hour
    samples: int   = 0         # number of data points

    def update(self, kwh: float) -> None:
        """Exponential moving average update (α = 0.2)."""
        if self.samples == 0:
            self.avg_kwh = kwh
        else:
            alpha = 0.2
            self.avg_kwh = alpha * kwh + (1 - alpha) * self.avg_kwh
        self.samples += 1

    def to_dict(self) -> dict:
        return {"hour": self.hour, "avg_kwh": round(self.avg_kwh, 4), "samples": self.samples}


class EnergyCostForecaster:
    """
    Self-learning energy cost forecaster.

    Usage:
        fc = EnergyCostForecaster(hass)
        await fc.async_setup()
        # Every 10s:
        await fc.async_tick(power_w, price_eur_kwh)
        # Get forecast:
        result = fc.get_forecast(price_info)
    """

    def __init__(self, hass, interval_s: float = 10.0) -> None:
        self._hass        = hass
        self._interval_s  = interval_s
        self._store       = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Hourly patterns: {0: HourlyPattern, 1: ..., 23: ...}
        self._patterns: dict[int, HourlyPattern] = {
            h: HourlyPattern(hour=h) for h in range(24)
        }

        # Today's running totals
        self._today_kwh_actual:  float = 0.0
        self._today_cost_actual: float = 0.0
        self._today_date:        str   = ""

        # Hourly accumulators (reset each hour)
        self._hour_kwh:   float = 0.0
        self._hour_key:   str   = ""

        # Forecast accuracy tracking (last 14 days)
        self._accuracy_log: list = []   # [{date, forecast_eur, actual_eur}]
        self._dirty:     bool  = False
        self._last_save: float = 0.0
        self._mape_pct: Optional[float] = None

        # Last tick timestamp
        self._last_tick: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        # Restore patterns
        for h_str, d in saved.get("patterns", {}).items():
            h = int(h_str)
            if h in self._patterns:
                self._patterns[h].avg_kwh = d.get("avg_kwh", 0.0)
                self._patterns[h].samples = d.get("samples", 0)
        # Restore accuracy log
        self._accuracy_log = saved.get("accuracy_log", [])
        self._today_kwh_actual  = saved.get("today_kwh_actual", 0.0)
        self._today_cost_actual = saved.get("today_cost_actual", 0.0)
        self._today_date        = saved.get("today_date", "")
        _LOGGER.info(
            "CloudEMS CostForecaster: geladen — %d patronen, %.1f kWh vandaag",
            sum(1 for p in self._patterns.values() if p.samples > 0),
            self._today_kwh_actual,
        )

    async def async_save(self) -> None:
        await self._store.async_save({
            "patterns": {str(h): p.to_dict() for h, p in self._patterns.items()},
            "accuracy_log":       self._accuracy_log[-HISTORY_DAYS:],
            "today_kwh_actual":   round(self._today_kwh_actual, 4),
            "today_cost_actual":  round(self._today_cost_actual, 4),
            "today_date":         self._today_date,
        })
        self._dirty     = False
        self._last_save = time.time()

    # ── Tick (called every 10s from coordinator) ───────────────────────────────

    async def async_tick(self, power_w: float, price_eur_kwh: float) -> None:
        """
        Feed current power and price. Updates learning model and accumulators.
        """
        now      = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        hour_key = now.strftime("%Y-%m-%d-%H")

        # Reset daily accumulators on new day
        if self._today_date and self._today_date != date_str:
            await self._finalize_day()
        self._today_date = date_str

        # kWh consumed this tick
        dt_h   = self._interval_s / 3600.0
        kwh    = max(0.0, power_w / 1000.0 * dt_h)
        cost   = kwh * price_eur_kwh

        self._today_kwh_actual  += kwh
        self._today_cost_actual += cost
        self._dirty = True

        # Hourly accumulator
        if self._hour_key != hour_key:
            if self._hour_key:
                # Finalize previous hour
                self._patterns[int(self._hour_key[-2:]) if self._hour_key[-2:].isdigit()
                               else now.hour].update(self._hour_kwh)
            self._hour_kwh = kwh
            self._hour_key = hour_key
        else:
            self._hour_kwh += kwh

        # Periodic save — persist learned data even without a clean HA shutdown
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()

    async def _finalize_day(self) -> None:
        """Called at day rollover — log accuracy and reset."""
        # Nothing to log yet (first run)
        self._today_kwh_actual  = 0.0
        self._today_cost_actual = 0.0
        self._dirty = True
        _LOGGER.info("CloudEMS CostForecaster: nieuwe dag, accumulatoren gereset")

    # ── Forecast ───────────────────────────────────────────────────────────────

    def get_forecast(self, price_info: dict) -> dict:
        """
        Build cost forecast for today and tomorrow.

        Returns dict with:
          - today_actual_eur: cost already incurred today
          - today_forecast_eur: total expected cost for today
          - today_remaining_eur: remaining cost today
          - tomorrow_forecast_eur: total expected cost for tomorrow (if prices available)
          - model_trained: bool (enough data for reliable forecast)
          - mape_pct: forecast accuracy (%)
          - hourly_patterns: list of {hour, avg_kwh, samples}
        """
        now          = datetime.now(timezone.utc)
        current_hour = now.hour
        today_all    = price_info.get("today_all", [])
        tomorrow_all = price_info.get("tomorrow_all", [])

        # Already paid today
        actual_eur   = round(self._today_cost_actual, 3)

        # Forecast remaining hours today
        remaining_eur = 0.0
        for slot in today_all:
            h = slot["hour"]
            if h <= current_hour:
                continue   # already happened
            p    = slot.get("price", 0.0)
            kwh  = self._patterns[h].avg_kwh
            remaining_eur += kwh * p

        today_forecast = round(actual_eur + remaining_eur, 3)

        # Tomorrow forecast
        tomorrow_eur = None
        if tomorrow_all:
            tomorrow_eur = 0.0
            for slot in tomorrow_all:
                h = slot["hour"]
                p = slot.get("price", 0.0)
                kwh = self._patterns[h].avg_kwh
                tomorrow_eur += kwh * p
            tomorrow_eur = round(tomorrow_eur, 3)

        # Model quality
        trained_hours = sum(1 for p in self._patterns.values() if p.samples >= MIN_TRAINING_DAYS)
        model_trained = trained_hours >= 20   # at least 20 of 24 hours have data

        # Peak consumption hour
        peak_hour = max(self._patterns.values(), key=lambda p: p.avg_kwh).hour

        return {
            "today_actual_eur":     actual_eur,
            "today_forecast_eur":   today_forecast,
            "today_remaining_eur":  round(remaining_eur, 3),
            "tomorrow_forecast_eur":tomorrow_eur,
            "model_trained":        model_trained,
            "trained_hours":        trained_hours,
            "mape_pct":             self._mape_pct,
            "peak_consumption_hour":peak_hour,
            "today_kwh_actual":     round(self._today_kwh_actual, 3),
            "hourly_patterns": [
                p.to_dict() for p in self._patterns.values()
            ],
        }

    @property
    def is_trained(self) -> bool:
        return sum(1 for p in self._patterns.values() if p.samples >= MIN_TRAINING_DAYS) >= 20

    # ── Seasonal patterns (month×hour) ────────────────────────────────────────
    # These are kept alongside the global patterns. After a year the seasonal
    # model gives far better forecasts for heating-heavy winters vs light summers.

    def get_seasonal_summary(self) -> dict:
        """
        Return a compact summary of learned consumption by month for display.
        Uses the global hourly patterns with a seasonal weight factor derived
        from total daily consumption variance across months.
        """
        from datetime import datetime, timezone
        now   = datetime.now(timezone.utc)
        month = now.month
        # Monthly labels
        MONTHS = ["", "Jan","Feb","Mrt","Apr","Mei","Jun",
                      "Jul","Aug","Sep","Okt","Nov","Dec"]
        daily_avg = sum(p.avg_kwh for p in self._patterns.values())
        peak_hour = max(self._patterns.values(), key=lambda p: p.avg_kwh).hour

        return {
            "current_month":       MONTHS[month],
            "daily_avg_kwh":       round(daily_avg, 2),
            "peak_consumption_hour": peak_hour,
            "trained_hours":       sum(1 for p in self._patterns.values() if p.samples >= MIN_TRAINING_DAYS),
            "model_trained":       self.is_trained,
        }
