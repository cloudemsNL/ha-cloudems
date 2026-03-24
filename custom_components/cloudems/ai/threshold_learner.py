"""
CloudEMS Threshold Learner — v1.0.0

All thresholds in CloudEMS start as defaults from const.py.
This module adapts them based on observed outcomes.

Principle:
  - Every threshold has a default (from const.py)
  - Every threshold has a learned value (from this module)
  - The system uses: learned_value if confidence >= MIN_CONFIDENCE else default
  - Thresholds are never adapted beyond safe bounds (min/max per threshold)

Examples:
  BATTERY_STALE_THRESHOLD_S: starts at 90s, adapts to actual Nexus response time
  AI_MIN_CONFIDENCE: starts at 0.65, adapts based on how often AI was right
  PHASE_IMBALANCE_THRESHOLD_A: starts at 4A, adapts based on actual limiter trips
  NILM_MIN_THRESHOLD_W: starts at 25W, adapts to actual noise floor of this home
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_threshold_learner_v1"
STORAGE_VERSION = 1

# How many observations before we trust a learned threshold
MIN_OBSERVATIONS = 10

# Bounds: (min_value, max_value, description)
THRESHOLD_BOUNDS: dict[str, tuple[float, float, str]] = {
    "BATTERY_STALE_THRESHOLD_S":   (20.0,  180.0, "Battery data stale after N seconds"),
    "P1_STALE_THRESHOLD_S":        (30.0,  180.0, "P1 data stale after N seconds"),
    "AI_MIN_CONFIDENCE":           (0.40,   0.90, "Min AI confidence before influencing decisions"),
    "AI_BATTERY_MIN_CONFIDENCE":   (0.40,   0.90, "Min confidence for battery hints"),
    "AI_BOILER_MIN_CONFIDENCE":    (0.40,   0.90, "Min confidence for boiler hints"),
    "AI_SHUTTER_MIN_CONFIDENCE":   (0.35,   0.85, "Min confidence for shutter hints"),
    "AI_EV_MIN_CONFIDENCE":        (0.30,   0.80, "Min confidence for EV predictions"),
    "PHASE_IMBALANCE_THRESHOLD_A": (2.0,    8.0,  "Ampère delta before phase imbalance warning"),
    "NILM_MIN_THRESHOLD_W":        (5.0,   80.0,  "Min watt change for NILM detection"),
    "NEXUS_MEASURE_WINDOW_S":      (60.0,  300.0, "Max wait for Nexus response"),
    "NEXUS_MIN_POWER_DELTA_W":     (50.0,  500.0, "Min power change to count as Nexus response"),
    "AI_PRICE_NUDGE_EUR_KWH":      (0.005,  0.05, "EPEX price nudge per AI hint"),
    "BOILER_SURPLUS_NUDGE_W":      (50.0,  500.0, "Surplus threshold reduction for boiler AI"),
    "PRICE_CHEAP_EUR_KWH":         (0.03,   0.20, "EPEX below this = cheap, charge battery"),
    "PRICE_EXPENSIVE_EUR_KWH":     (0.15,   0.50, "EPEX above this = expensive, discharge battery"),
}


@dataclass
class ThresholdRecord:
    """One threshold with its learned value and statistics."""
    name:          str
    default:       float
    learned:       float
    n_observations: int   = 0
    n_good:        int    = 0   # times using this threshold led to good outcome
    n_bad:         int    = 0   # times it led to bad outcome
    last_updated:  float  = 0.0
    # EMA of "reward" when using this threshold
    reward_ema:    float  = 0.0

    @property
    def confidence(self) -> float:
        return min(0.95, self.n_observations / MIN_OBSERVATIONS)

    @property
    def active_value(self) -> float:
        """Return learned value if confident, else default."""
        if self.confidence >= 0.8:
            return self.learned
        # Blend: default × (1-conf) + learned × conf
        return self.default * (1 - self.confidence) + self.learned * self.confidence

    @property
    def accuracy(self) -> float:
        total = self.n_good + self.n_bad
        return self.n_good / total if total > 0 else 0.5


class ThresholdLearner:
    """
    Adaptive threshold manager for all CloudEMS tunable parameters.

    Usage:
        # Get current best value for a threshold:
        stale_s = learner.get("BATTERY_STALE_THRESHOLD_S")

        # Report an outcome (was using this threshold good or bad?):
        learner.report_outcome("BATTERY_STALE_THRESHOLD_S", good=True, context={"age_s": 45})

        # Directly update a threshold from a measurement:
        learner.update_from_measurement("BATTERY_STALE_THRESHOLD_S", measured_value=42.0)
    """

    def __init__(self, hass: HomeAssistant, defaults: dict[str, float]) -> None:
        self.hass      = hass
        self._store    = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._defaults = defaults
        self._records: dict[str, ThresholdRecord] = {}
        # Initialize with defaults
        for name, default in defaults.items():
            self._records[name] = ThresholdRecord(
                name=name, default=default, learned=default
            )
        self._dirty = False

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for name, data in saved.get("records", {}).items():
            if name in self._records:
                r = self._records[name]
                r.learned        = float(data.get("learned", r.default))
                r.n_observations = int(data.get("n_observations", 0))
                r.n_good         = int(data.get("n_good", 0))
                r.n_bad          = int(data.get("n_bad", 0))
                r.reward_ema     = float(data.get("reward_ema", 0.0))
                r.last_updated   = float(data.get("last_updated", 0.0))
        learned = sum(1 for r in self._records.values() if r.n_observations >= MIN_OBSERVATIONS)
        _LOGGER.info(
            "ThresholdLearner: loaded %d thresholds, %d already learned",
            len(self._records), learned
        )

    def get(self, name: str) -> float:
        """Get the current best value for a threshold."""
        r = self._records.get(name)
        if r is None:
            return self._defaults.get(name, 0.0)
        return self._clamp(name, r.active_value)

    def get_default(self, name: str) -> float:
        return self._defaults.get(name, 0.0)

    def update_from_measurement(self, name: str, measured_value: float) -> None:
        """
        Directly update a threshold based on a measured value.
        E.g. Nexus responded after 45s → update BATTERY_STALE_THRESHOLD_S toward 45s.
        """
        r = self._records.get(name)
        if r is None:
            return
        alpha = max(0.05, 1.0 / max(1, r.n_observations + 1))
        old = r.learned
        r.learned = self._clamp(name, r.learned * (1 - alpha) + measured_value * alpha)
        r.n_observations += 1
        r.last_updated = time.time()
        self._dirty = True
        _LOGGER.debug(
            "ThresholdLearner: %s updated %.2f → %.2f (obs=%d)",
            name, old, r.learned, r.n_observations
        )

    def report_outcome_for_hour(self, name: str, hour: int, good: bool, reward: float = 0.0) -> None:
        """
        Report outcome tagged with hour-of-day.
        Allows ThresholdLearner to learn time-of-day patterns.
        Stored as weighted adjustments per hour in the threshold record.
        """
        r = self._records.get(name)
        if r is None:
            return
        # Store hour-weights as extra field if not present
        if not hasattr(r, '_hour_rewards'):
            r._hour_rewards = [0.0] * 24
            r._hour_counts  = [0] * 24
        rew = reward if reward != 0.0 else (1.0 if good else -1.0)
        alpha = 0.1
        r._hour_rewards[hour % 24] = r._hour_rewards[hour % 24] * (1-alpha) + rew * alpha
        r._hour_counts[hour % 24] += 1
        # Also update global record
        self.report_outcome(name, good, reward)

    def get_hour_weight(self, name: str, hour: int) -> float:
        """Get the learned confidence weight for a threshold at a specific hour."""
        r = self._records.get(name)
        if r is None or not hasattr(r, '_hour_rewards'):
            return 1.0
        hr = r._hour_rewards[hour % 24]
        # Scale: reward -1→+1 maps to weight 0.7→1.3
        return round(max(0.7, min(1.3, 1.0 + hr * 0.3)), 3)

    def report_outcome(self, name: str, good: bool, reward: float = 0.0) -> None:
        """
        Report whether using a threshold led to a good or bad outcome.
        reward: -1.0 (bad) to +1.0 (good), or just pass good=True/False.
        """
        r = self._records.get(name)
        if r is None:
            return
        if good:
            r.n_good += 1
        else:
            r.n_bad += 1
        r.n_observations += 1
        # EMA of reward
        rew = reward if reward != 0.0 else (1.0 if good else -1.0)
        alpha = 0.1
        r.reward_ema = r.reward_ema * (1 - alpha) + rew * alpha
        r.last_updated = time.time()

        # Adaptive update: if consistently bad, nudge threshold
        if r.n_observations >= 5 and r.reward_ema < -0.3:
            # Threshold is performing poorly — adjust toward better behavior
            # For confidence thresholds: lower = more permissive (bad) → raise
            # For stale thresholds: if too often stale → lower the threshold
            self._auto_adjust(name, r)

        self._dirty = True

    def _auto_adjust(self, name: str, r: ThresholdRecord) -> None:
        """Automatically adjust a threshold when outcomes are consistently bad."""
        bounds = THRESHOLD_BOUNDS.get(name)
        if not bounds:
            return
        lo, hi, _ = bounds

        # Confidence thresholds: bad outcomes → we were too permissive → raise
        if "CONFIDENCE" in name and r.reward_ema < -0.3:
            nudge = (hi - r.learned) * 0.05  # move 5% toward max
            r.learned = self._clamp(name, r.learned + nudge)
            _LOGGER.debug("ThresholdLearner: %s raised to %.3f (reward_ema=%.2f)", name, r.learned, r.reward_ema)

        # Stale thresholds: if stale detection was wrong → adjust
        elif "STALE" in name and r.reward_ema < -0.3:
            nudge = (r.learned - lo) * 0.05  # move 5% toward min
            r.learned = self._clamp(name, r.learned - nudge)
            _LOGGER.debug("ThresholdLearner: %s lowered to %.1f (reward_ema=%.2f)", name, r.learned, r.reward_ema)

    def _clamp(self, name: str, value: float) -> float:
        bounds = THRESHOLD_BOUNDS.get(name)
        if not bounds:
            return value
        return max(bounds[0], min(bounds[1], value))

    @property
    def all_values(self) -> dict[str, float]:
        return {name: self.get(name) for name in self._records}

    @property
    def stats(self) -> dict:
        return {
            "n_thresholds": len(self._records),
            "n_learned":    sum(1 for r in self._records.values() if r.n_observations >= MIN_OBSERVATIONS),
            "thresholds":   {
                name: {
                    "default":  round(r.default, 4),
                    "learned":  round(r.learned, 4),
                    "active":   round(r.active_value, 4),
                    "confidence": round(r.confidence, 3),
                    "accuracy": round(r.accuracy, 3),
                    "n_obs":    r.n_observations,
                }
                for name, r in self._records.items()
            }
        }

    async def async_maybe_save(self) -> None:
        if self._dirty:
            await self._save()

    async def async_save(self) -> None:
        await self._save()

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "records": {
                    name: {
                        "learned":        r.learned,
                        "n_observations": r.n_observations,
                        "n_good":         r.n_good,
                        "n_bad":          r.n_bad,
                        "reward_ema":     r.reward_ema,
                        "last_updated":   r.last_updated,
                    }
                    for name, r in self._records.items()
                }
            })
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("ThresholdLearner save error: %s", exc)
