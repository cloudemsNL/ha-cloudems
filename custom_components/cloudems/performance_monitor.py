"""
CloudEMS Adaptive Performance Monitor — v4.6.152

Tracks coordinator cycle times and automatically scales back CloudEMS
activity to prevent HA overload.

Modes (auto-adaptive):
  NORMAL   < 300ms  — everything on, 10s interval, full logging
  REDUCED  300-600ms — NILM learning paused, 15s interval, normal logging
  MINIMAL  600-1000ms — NILM off, 20s interval, high logging only
  CRITICAL > 1000ms  — core only, 30s interval, high logging only + warning

Recovery: upscale only after 5 consecutive cycles below threshold (hysteresis).
"""

from __future__ import annotations

import time
import logging
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# ── Thresholds (ms) ──────────────────────────────────────────────────────────
THRESHOLD_REDUCED  = 300
THRESHOLD_MINIMAL  = 600
THRESHOLD_CRITICAL = 1000

# Hysteresis: how many consecutive good cycles before upgrading mode
RECOVERY_CYCLES = 5

# Mode names
MODE_NORMAL   = "NORMAL"
MODE_REDUCED  = "REDUCED"
MODE_MINIMAL  = "MINIMAL"
MODE_CRITICAL = "CRITICAL"

# Interval (seconds) per mode
INTERVAL_BY_MODE = {
    MODE_NORMAL:   10,
    MODE_REDUCED:  15,
    MODE_MINIMAL:  20,
    MODE_CRITICAL: 30,
}

_MODE_ORDER = [MODE_NORMAL, MODE_REDUCED, MODE_MINIMAL, MODE_CRITICAL]


class PerformanceMonitor:
    """Tracks cycle times and derives the current performance mode."""

    def __init__(self) -> None:
        self._samples: deque[float] = deque(maxlen=20)   # last 20 cycle times in ms
        self._mode: str = MODE_NORMAL
        self._recovery_count: int = 0                    # consecutive good cycles
        self._last_mode_change: float = 0.0
        self._cycle_start: float = 0.0

    # ── Cycle timing ─────────────────────────────────────────────────────────

    def start_cycle(self) -> None:
        """Call at the start of _async_update_data."""
        self._cycle_start = time.perf_counter()

    def end_cycle(self) -> float:
        """Call at the end of _async_update_data. Returns cycle time in ms."""
        if self._cycle_start == 0.0:
            return 0.0
        elapsed_ms = (time.perf_counter() - self._cycle_start) * 1000
        self._cycle_start = 0.0
        self._samples.append(elapsed_ms)
        self._update_mode(elapsed_ms)
        return elapsed_ms

    # ── Mode logic ────────────────────────────────────────────────────────────

    def _update_mode(self, latest_ms: float) -> None:
        """Update performance mode based on latest cycle time."""
        # Determine target mode from latest sample
        if latest_ms >= THRESHOLD_CRITICAL:
            target = MODE_CRITICAL
        elif latest_ms >= THRESHOLD_MINIMAL:
            target = MODE_MINIMAL
        elif latest_ms >= THRESHOLD_REDUCED:
            target = MODE_REDUCED
        else:
            target = MODE_NORMAL

        current_idx = _MODE_ORDER.index(self._mode)
        target_idx  = _MODE_ORDER.index(target)

        if target_idx > current_idx:
            # Degrading — immediate
            old = self._mode
            self._mode = target
            self._recovery_count = 0
            self._last_mode_change = time.time()
            _LOGGER.warning(
                "CloudEMS performance: %s → %s (cycle=%.0fms)",
                old, target, latest_ms,
            )
        elif target_idx < current_idx:
            # Recovering — need RECOVERY_CYCLES consecutive good cycles
            self._recovery_count += 1
            if self._recovery_count >= RECOVERY_CYCLES:
                # Step up one level at a time
                new_idx = current_idx - 1
                old = self._mode
                self._mode = _MODE_ORDER[new_idx]
                self._recovery_count = 0
                self._last_mode_change = time.time()
                _LOGGER.info(
                    "CloudEMS performance: %s → %s (recovered after %d cycles)",
                    old, self._mode, RECOVERY_CYCLES,
                )
        else:
            # Same level
            self._recovery_count = 0

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def interval_s(self) -> int:
        return INTERVAL_BY_MODE[self._mode]

    @property
    def nilm_learning_enabled(self) -> bool:
        """NILM learning active in NORMAL and REDUCED mode."""
        return self._mode in (MODE_NORMAL, MODE_REDUCED)

    @property
    def nilm_enabled(self) -> bool:
        """Full NILM active only in NORMAL and REDUCED mode."""
        return self._mode in (MODE_NORMAL, MODE_REDUCED)

    @property
    def full_logging(self) -> bool:
        """Normal/low logging only in NORMAL mode."""
        return self._mode == MODE_NORMAL

    @property
    def avg_ms(self) -> float:
        if not self._samples:
            return 0.0
        return round(sum(self._samples) / len(self._samples), 1)

    @property
    def max_ms(self) -> float:
        if not self._samples:
            return 0.0
        return round(max(self._samples), 1)

    @property
    def p95_ms(self) -> float:
        if not self._samples:
            return 0.0
        s = sorted(self._samples)
        idx = max(0, int(len(s) * 0.95) - 1)
        return round(s[idx], 1)

    @property
    def recovery_progress(self) -> int:
        """How many recovery cycles completed out of RECOVERY_CYCLES."""
        return self._recovery_count

    def get_status_dict(self) -> dict:
        return {
            "mode":              self._mode,
            "avg_ms":            self.avg_ms,
            "max_ms":            self.max_ms,
            "p95_ms":            self.p95_ms,
            "interval_s":        self.interval_s,
            "nilm_learning":     self.nilm_learning_enabled,
            "nilm_enabled":      self.nilm_enabled,
            "full_logging":      self.full_logging,
            "recovery_progress": self._recovery_count,
            "recovery_needed":   RECOVERY_CYCLES,
            "samples":           len(self._samples),
        }


# ── Force-update priority thresholds per mode ─────────────────────────────────
# Returns the minimum priority level that still gets force_update=True
# Priority 1 = most critical, 3 = least critical
FORCE_UPDATE_PRIORITY_BY_MODE = {
    MODE_NORMAL:   3,   # all sensors
    MODE_REDUCED:  2,   # priority 1+2 only
    MODE_MINIMAL:  1,   # priority 1 only
    MODE_CRITICAL: 0,   # none
}


class AdaptiveForceUpdateMixin:
    """
    Mixin for CoordinatorEntity sensors that makes force_update adaptive.

    Set _force_update_priority on the class:
      1 = critical input sensor (always force_update when possible)
      2 = live display sensor
      3 = analytical output sensor (first to lose force_update)

    Usage:
        class Mysensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
            _force_update_priority = 2
    """

    _force_update_priority: int = 3  # default: lowest priority

    @property
    def force_update(self) -> bool:
        """Dynamically determine force_update based on performance mode."""
        perf = getattr(getattr(self, "coordinator", None), "_perf", None)
        if perf is None:
            return True
        threshold = FORCE_UPDATE_PRIORITY_BY_MODE.get(perf.mode, 3)
        return self._force_update_priority <= threshold
