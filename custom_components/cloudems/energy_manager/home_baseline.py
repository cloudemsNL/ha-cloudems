"""
CloudEMS Home Baseline Learner — v1.0.0

Learns three related things from the grid power signal alone:

1. BASELINE MODEL  (HourlyPattern per weekday×hour, 7×24 = 168 buckets)
   Tracks mean + σ of consumption for every slot.
   After ~14 days the model becomes reliable.

2. ANOMALY DETECTION
   If the current consumption deviates more than N×σ from the learned
   average for this slot → anomaly sensor fires.
   "It's Tuesday 3 AM and you're using 900W more than normal."

3. STANDBY + OCCUPANCY
   Nightly minimum (midnight-4h) converges to the true standby load.
   If consumption is significantly above standby → someone is probably home.
   The standby baseline itself surfaces "always-on" appliance load.

4. STANDBY HUNTERS
   Devices that appear always-on across several nights are flagged as
   potential energy wasters (e.g. old set-top-box, forgotten electric heater).

All learning is zero-config: nothing for the user to set.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_home_baseline_v1"
STORAGE_VERSION = 1

# Anomaly: flag if current > mean + SIGMA_THRESHOLD × σ
SIGMA_THRESHOLD = 2.5
# Minimum samples before anomaly detection activates for a slot
MIN_SAMPLES_FOR_ANOMALY = 7
# Standby learning: hours considered "deep night" (no intentional activity)
NIGHT_HOURS = {0, 1, 2, 3, 4}
# Standby: occupancy is probable if consumption > standby × OCCUPANCY_RATIO
OCCUPANCY_RATIO = 2.2
# Standby hunter: flag if night-average > STANDBY_HUNTER_W watts
STANDBY_HUNTER_W = 50.0
# EMA alpha for standby model (slow, stable)
STANDBY_ALPHA = 0.05
# Save interval
SAVE_INTERVAL_S = 300


@dataclass
class SlotStats:
    """Running mean + variance for one weekday×hour slot (Welford's algorithm)."""
    count: int   = 0
    mean:  float = 0.0
    m2:    float = 0.0     # sum of squared deviations from mean

    def update(self, value: float) -> None:
        self.count += 1
        delta  = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def std(self) -> float:
        if self.count < 2:
            return max(50.0, self.mean * 0.2)   # prior: 20% or 50W min
        return math.sqrt(self.m2 / (self.count - 1))

    def to_dict(self) -> dict:
        return {"count": self.count, "mean": round(self.mean, 1), "m2": round(self.m2, 1)}

    @classmethod
    def from_dict(cls, d: dict) -> "SlotStats":
        s = cls()
        s.count = d.get("count", 0)
        s.mean  = d.get("mean", 0.0)
        s.m2    = d.get("m2", 0.0)
        return s


class HomeBaselineLearner:
    """
    Learns household baseline consumption and detects anomalies.

    Usage in coordinator:
        bl = HomeBaselineLearner(hass)
        await bl.async_setup()
        # Every 10s:
        result = bl.update(power_w)
        # result keys: anomaly, deviation_w, expected_w, sigma,
        #              standby_w, is_home, standby_hunters
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass  = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # 7 weekdays × 24 hours
        self._slots: dict[tuple, SlotStats] = {
            (wd, h): SlotStats() for wd in range(7) for h in range(24)
        }
        self._standby_w: float = 80.0          # initial prior: 80W
        self._standby_samples: int = 0
        self._night_buffer: list[float] = []   # power readings this night hour
        self._current_night_hour: Optional[int] = None
        self._last_save: float = 0.0
        self._dirty: bool = False

        # Anomaly state
        self._anomaly: bool = False
        self._deviation_w: float = 0.0
        self._expected_w: float = 0.0
        self._sigma: float = 0.0

        # Slot accumulator (for hourly update, not every 10s)
        self._slot_buffer: list[float] = []
        self._slot_key: Optional[tuple] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for key_str, d in saved.get("slots", {}).items():
            wd, h = map(int, key_str.split("_"))
            self._slots[(wd, h)] = SlotStats.from_dict(d)
        self._standby_w       = float(saved.get("standby_w", 80.0))
        self._standby_samples = int(saved.get("standby_samples", 0))
        trained = sum(1 for s in self._slots.values() if s.count >= MIN_SAMPLES_FOR_ANOMALY)
        _LOGGER.info(
            "CloudEMS HomeBaseline: geladen — %d/%d slots getraind, standby %.0fW",
            trained, len(self._slots), self._standby_w,
        )

    async def _async_save(self) -> None:
        await self._store.async_save({
            "slots": {
                f"{wd}_{h}": s.to_dict()
                for (wd, h), s in self._slots.items()
            },
            "standby_w":       round(self._standby_w, 1),
            "standby_samples": self._standby_samples,
        })
        self._dirty = False
        self._last_save = time.time()

    # ── Main update (call every ~10s from coordinator) ────────────────────────

    def update(self, power_w: float) -> dict:
        now  = datetime.now(timezone.utc)
        wd   = now.weekday()   # 0=Monday … 6=Sunday
        h    = now.hour
        slot = (wd, h)
        slot_key_changed = slot != self._slot_key

        # ── Slot accumulator: collect readings, learn at end of each hour ──
        if slot_key_changed:
            if self._slot_key is not None and self._slot_buffer:
                avg = sum(self._slot_buffer) / len(self._slot_buffer)
                self._slots[self._slot_key].update(avg)
                self._dirty = True
            self._slot_buffer = []
            self._slot_key = slot
        self._slot_buffer.append(max(0.0, power_w))

        # ── Anomaly detection ──────────────────────────────────────────────
        s = self._slots[slot]
        self._expected_w = s.mean
        self._sigma      = s.std
        if s.count >= MIN_SAMPLES_FOR_ANOMALY and s.mean > 5.0:
            dev = power_w - s.mean
            self._deviation_w = round(dev, 1)
            self._anomaly = dev > SIGMA_THRESHOLD * s.std
        else:
            self._anomaly     = False
            self._deviation_w = 0.0

        # ── Standby learning: use deep-night readings ──────────────────────
        if h in NIGHT_HOURS and power_w > 0:
            if h != self._current_night_hour:
                if self._night_buffer:
                    night_avg = sum(self._night_buffer) / len(self._night_buffer)
                    # Only use if plausible standby range (< 500W, > 5W)
                    if 5.0 < night_avg < 500.0:
                        self._standby_w = (
                            (1 - STANDBY_ALPHA) * self._standby_w
                            + STANDBY_ALPHA * night_avg
                        )
                        self._standby_samples += 1
                        self._dirty = True
                self._night_buffer = [power_w]
                self._current_night_hour = h
            else:
                self._night_buffer.append(power_w)

        # ── Occupancy: consumption significantly above standby? ────────────
        is_home = power_w > self._standby_w * OCCUPANCY_RATIO

        # ── Standby hunters: slots that are always above hunter threshold ──
        # Report night slots whose mean is > STANDBY_HUNTER_W
        hunters = [
            {"weekday": wd2, "hour": h2, "avg_w": round(s2.mean, 0)}
            for (wd2, h2), s2 in self._slots.items()
            if h2 in NIGHT_HOURS
            and s2.count >= MIN_SAMPLES_FOR_ANOMALY
            and s2.mean > STANDBY_HUNTER_W + self._standby_w
        ]

        # ── Periodic save ──────────────────────────────────────────────────
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            self.hass.async_create_task(self._async_save())

        trained_slots = sum(1 for s in self._slots.values() if s.count >= MIN_SAMPLES_FOR_ANOMALY)

        return {
            "anomaly":          self._anomaly,
            "deviation_w":      self._deviation_w,
            "expected_w":       round(self._expected_w, 1),
            "current_w":        round(power_w, 1),
            "sigma_w":          round(self._sigma, 1),
            "sigma_threshold":  SIGMA_THRESHOLD,
            "standby_w":        round(self._standby_w, 1),
            "standby_samples":  self._standby_samples,
            "is_home":          is_home,
            "trained_slots":    trained_slots,
            "total_slots":      168,
            "model_ready":      trained_slots >= 96,   # at least 4 weekday-days fully trained
            "standby_hunters":  hunters,
        }
