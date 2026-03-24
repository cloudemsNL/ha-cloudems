"""
CloudEMS Nexus Latency Learner — v1.0.0

Learns the response characteristics of the Zonneplan Nexus battery:
  - Command latency: how long after a command does power actually change?
  - Power accuracy: how close is actual vs requested power?
  - Cloud dependency: does latency vary by time-of-day (cloud load)?
  - Efficiency curve: actual kWh delivered vs commanded

This allows the BatteryDecisionEngine to:
  1. Send commands N seconds EARLY (before a price change)
  2. Request slightly higher power to compensate for undershoot
  3. Skip commands when latency would make them useless

The Nexus typically has 30-90s latency via Zonneplan cloud.
Bad times (cloud congestion) can be 120s+.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_nexus_latency_v1"
STORAGE_VERSION = 1

# Measurement window: how long to watch for power change after command
MEASURE_WINDOW_S = 120
# Minimum power change to count as "responded"
# Max measurements to keep
# Min measurements before predictions are used
MIN_MEASUREMENTS = 5


@dataclass
class LatencyMeasurement:
    """One measured command→response cycle."""
    commanded_w:    float   # power we asked for (+ = charge, - = discharge)
    actual_w:       float   # power actually delivered
    latency_s:      float   # seconds until response was detected
    hour:           int     # hour of day (0-23)
    dow:            int     # day of week (0=mon)
    cloud_ok:       bool    # True if Zonneplan cloud responded quickly
    ts:             float   # unix timestamp


@dataclass
class PendingCommand:
    """A command that's been sent but not yet confirmed."""
    commanded_w:    float
    sent_ts:        float
    power_before:   float
    hour:           int
    dow:            int


class NexusLatencyLearner:
    """
    Learns Nexus response characteristics from observed command/response pairs.

    Usage:
        # When sending a command to Nexus:
        learner.record_command(commanded_w=2000, current_power_w=0)

        # Every coordinator tick:
        learner.tick(current_power_w=battery_power)

        # Get prediction for next command:
        pred = learner.predict_latency()
        # pred = {'latency_s': 55, 'accuracy_pct': 87, 'confidence': 0.8}
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass    = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self._measurements: list[LatencyMeasurement] = []
        self._pending: Optional[PendingCommand] = None
        self._dirty  = False
        self._last_save_ts = 0.0

        # Rolling stats (updated after each measurement)
        self._avg_latency_s:   float = 60.0  # default assumption
        self._avg_accuracy_pct: float = 90.0
        self._p90_latency_s:   float = 90.0  # 90th percentile — worst case

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for m in saved.get("measurements", []):
            try:
                self._measurements.append(LatencyMeasurement(**m))
            except Exception:
                pass
        self._update_stats()
        _LOGGER.info(
            "Nexus Latency Learner: loaded %d measurements, avg latency=%.0fs",
            len(self._measurements), self._avg_latency_s
        )

    def record_command(self, commanded_w: float, current_power_w: float) -> None:
        """
        Call when a charge/discharge command is sent to the Nexus.
        commanded_w: positive = charge, negative = discharge
        """
        now = time.time()
        dt  = datetime.fromtimestamp(now, tz=timezone.utc)

        # If there's already a pending command, discard it (superseded)
        if self._pending:
            _LOGGER.debug("Nexus: superseding previous pending command")

        self._pending = PendingCommand(
            commanded_w  = commanded_w,
            sent_ts      = now,
            power_before = current_power_w,
            hour         = dt.hour,
            dow          = dt.weekday(),
        )
        _LOGGER.debug(
            "Nexus: recorded command %.0fW (current: %.0fW)",
            commanded_w, current_power_w
        )

    def tick(self, current_power_w: float) -> Optional[LatencyMeasurement]:
        """
        Call every coordinator tick with current battery power.
        Returns a LatencyMeasurement if a response was detected.
        """
        if not self._pending:
            return None

        p = self._pending
        now = time.time()
        elapsed = now - p.sent_ts

        # Timeout — command never responded
        if elapsed > MEASURE_WINDOW_S:
            _LOGGER.debug(
                "Nexus: command %.0fW timed out after %.0fs",
                p.commanded_w, elapsed
            )
            self._pending = None
            return None

        # Check if power has changed significantly in the right direction
        delta = current_power_w - p.power_before
        expected_direction = 1 if p.commanded_w > 0 else -1
        actual_direction   = 1 if delta > 0 else (-1 if delta < 0 else 0)

        if abs(delta) < MIN_POWER_DELTA_W or actual_direction != expected_direction:
            return None  # not yet responded

        # Response detected!
        accuracy_pct = min(100.0, abs(delta) / max(1.0, abs(p.commanded_w)) * 100.0)
        cloud_ok     = elapsed < 45.0  # fast = cloud was responsive

        m = LatencyMeasurement(
            commanded_w  = p.commanded_w,
            actual_w     = current_power_w,
            latency_s    = elapsed,
            hour         = p.hour,
            dow          = p.dow,
            cloud_ok     = cloud_ok,
            ts           = now,
        )
        self._measurements.append(m)
        if len(self._measurements) > MAX_MEASUREMENTS:
            self._measurements = self._measurements[-MAX_MEASUREMENTS:]

        self._pending = None
        self._update_stats()
        self._dirty = True

        _LOGGER.info(
            "Nexus: response detected — latency=%.0fs accuracy=%.0f%% cloud=%s",
            elapsed, accuracy_pct, "ok" if cloud_ok else "slow"
        )
        return m

    def predict_latency(self, hour: Optional[int] = None) -> dict:
        """
        Predict latency and accuracy for the next command.
        Returns dict with latency_s, accuracy_pct, advance_s, confidence.
        """
        if len(self._measurements) < MIN_MEASUREMENTS:
            return {
                "latency_s":   self._avg_latency_s,
                "accuracy_pct": self._avg_accuracy_pct,
                "advance_s":   self._avg_latency_s,  # send this many seconds early
                "p90_latency_s": self._p90_latency_s,
                "confidence":  0.0,
                "n_samples":   len(self._measurements),
            }

        # Filter by time-of-day if we have enough data
        if hour is not None:
            hour_samples = [
                m for m in self._measurements
                if abs(m.hour - hour) <= 2 or abs(m.hour - hour) >= 22
            ]
            if len(hour_samples) >= 3:
                use_samples = hour_samples
            else:
                use_samples = self._measurements
        else:
            use_samples = self._measurements

        # Recent samples weighted higher
        now_ts = time.time()
        weights = [math.exp(-(now_ts - m.ts) / (7 * 86400)) for m in use_samples]
        total_w = sum(weights)

        avg_lat = sum(m.latency_s * w for m, w in zip(use_samples, weights)) / total_w
        avg_acc = sum(
            min(100.0, abs(m.actual_w) / max(1.0, abs(m.commanded_w)) * 100.0) * w
            for m, w in zip(use_samples, weights)
        ) / total_w

        # P90 for worst-case planning
        sorted_lat = sorted(m.latency_s for m in use_samples)
        p90 = sorted_lat[int(len(sorted_lat) * 0.9)]

        confidence = min(0.95, len(use_samples) / 20.0)

        return {
            "latency_s":     round(avg_lat, 1),
            "accuracy_pct":  round(avg_acc, 1),
            "advance_s":     round(avg_lat + 5, 0),  # slight buffer
            "p90_latency_s": round(p90, 1),
            "confidence":    round(confidence, 3),
            "n_samples":     len(use_samples),
            "cloud_ok_pct":  round(
                sum(1 for m in use_samples if m.cloud_ok) / len(use_samples) * 100, 1
            ),
        }

    def get_power_correction(self, requested_w: float) -> float:
        """
        Return corrected power request accounting for Nexus undershoot.
        E.g. if Nexus delivers 87% of requested, request 115% to hit target.
        """
        if len(self._measurements) < MIN_MEASUREMENTS or self._avg_accuracy_pct >= 98:
            return requested_w

        # Don't overcorrect too aggressively
        correction = min(1.15, 100.0 / max(70.0, self._avg_accuracy_pct))
        corrected  = requested_w * correction

        _LOGGER.debug(
            "Nexus power correction: %.0fW → %.0fW (accuracy=%.0f%%)",
            requested_w, corrected, self._avg_accuracy_pct
        )
        return corrected

    def _update_stats(self) -> None:
        if not self._measurements:
            return
        lats = [m.latency_s for m in self._measurements]
        accs = [
            min(100.0, abs(m.actual_w) / max(1.0, abs(m.commanded_w)) * 100.0)
            for m in self._measurements
        ]
        self._avg_latency_s    = sum(lats) / len(lats)
        self._avg_accuracy_pct = sum(accs) / len(accs)
        sorted_lats = sorted(lats)
        self._p90_latency_s    = sorted_lats[int(len(sorted_lats) * 0.9)]

    async def async_maybe_save(self) -> None:
        now = time.time()
        if self._dirty and (now - self._last_save_ts) >= 300:
            await self._save()

    async def async_save(self) -> None:
        await self._save()

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "measurements": [
                    {
                        "commanded_w":  m.commanded_w,
                        "actual_w":     m.actual_w,
                        "latency_s":    m.latency_s,
                        "hour":         m.hour,
                        "dow":          m.dow,
                        "cloud_ok":     m.cloud_ok,
                        "ts":           m.ts,
                    }
                    for m in self._measurements
                ]
            })
            self._last_save_ts = time.time()
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("Nexus Latency save error: %s", exc)

    @property
    def stats(self) -> dict:
        pred = self.predict_latency()
        return {
            "n_measurements":  len(self._measurements),
            "ready":           len(self._measurements) >= MIN_MEASUREMENTS,
            "avg_latency_s":   round(self._avg_latency_s, 1),
            "p90_latency_s":   round(self._p90_latency_s, 1),
            "avg_accuracy_pct": round(self._avg_accuracy_pct, 1),
            "confidence":      pred["confidence"],
            "cloud_ok_pct":    pred.get("cloud_ok_pct", 0),
        }
