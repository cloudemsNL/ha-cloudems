# -*- coding: utf-8 -*-
"""CloudEMS SensorEMALayer — v1.15.0.

Smooths delayed cloud sensor readings (e.g. Zonneplan battery: 30-300s updates)
to prevent NILM false triggers from sudden large steps.

Key behaviours
--------------
* Tracks wall-clock time between real value changes per entity.
* Adapts EMA alpha:  fast P1 sensor (< 5s) → α=1.0 (no smoothing)
                     cloud battery (60s)    → α≈0.25
* Blocks spikes > SPIKE_MULTIPLIER × running average (returns prev EMA value).
* Exposes diagnostics: slow sensors, blocked spikes, estimated update interval.
"""
from __future__ import annotations
import time
import logging
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

SPIKE_MULTIPLIER = 5.0      # block if new value > 5× running mean
MIN_SAMPLES_FOR_SPIKE = 8   # need at least 8 samples before spike detection
FAST_UPDATE_S  = 5.0        # ≤ 5 s → α = 1.0 (passthrough)
SLOW_UPDATE_S  = 120.0      # ≥ 120 s → α = 0.10


def _alpha_from_interval(interval_s: float) -> float:
    """Map measured update interval to EMA alpha (higher = faster response)."""
    if interval_s <= FAST_UPDATE_S:
        return 1.0
    if interval_s >= SLOW_UPDATE_S:
        return 0.10
    # Linear interpolation in log space
    t = (interval_s - FAST_UPDATE_S) / (SLOW_UPDATE_S - FAST_UPDATE_S)
    return round(1.0 - t * 0.90, 4)


class _SensorState:
    __slots__ = ("ema", "raw_prev", "last_change_ts", "interval_ema",
                 "sample_count", "spikes_blocked", "alpha")

    def __init__(self, initial: float):
        self.ema: float = initial
        self.raw_prev: float = initial
        self.last_change_ts: float = time.time()
        self.interval_ema: float = 10.0   # assume 10s to start
        self.sample_count: int = 1
        self.spikes_blocked: int = 0
        self.alpha: float = 1.0


class SensorEMALayer:
    """
    EMA smoothing layer for all sensor readings ingested by CloudEMS.

    Usage::

        ema = SensorEMALayer()
        smoothed = ema.update("sensor.battery_power", raw_value)
        diag = ema.get_diagnostics()
    """

    def __init__(self):
        self._states: Dict[str, _SensorState] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def update(self, entity_id: str, raw: Optional[float]) -> Optional[float]:
        """Return EMA-smoothed value. Returns raw unchanged if no entity_id given."""
        if raw is None or not entity_id:
            return raw

        now = time.time()

        if entity_id not in self._states:
            self._states[entity_id] = _SensorState(raw)
            return raw

        st = self._states[entity_id]
        st.sample_count += 1

        # Track real change interval
        if abs(raw - st.raw_prev) > 0.5:
            interval = now - st.last_change_ts
            if interval > 0.5:
                # EMA on interval to avoid outliers from HA restarts
                st.interval_ema = st.interval_ema * 0.85 + interval * 0.15
                st.alpha = _alpha_from_interval(st.interval_ema)
            st.last_change_ts = now
            st.raw_prev = raw

        # Spike guard (only after enough samples)
        if (st.sample_count >= MIN_SAMPLES_FOR_SPIKE
                and st.ema != 0
                and abs(raw) > abs(st.ema) * SPIKE_MULTIPLIER
                and abs(raw) > 200):          # only for significant magnitudes
            st.spikes_blocked += 1
            _LOGGER.debug(
                "EMA spike blocked for %s: raw=%.1f ema=%.1f (×%.1f)",
                entity_id, raw, st.ema, abs(raw) / abs(st.ema)
            )
            return st.ema  # return previous EMA, skip the spike

        # Apply EMA
        st.ema = st.alpha * raw + (1.0 - st.alpha) * st.ema
        return round(st.ema, 2)

    def get_diagnostics(self) -> dict:
        """Return dict with per-sensor diagnostics for the Diagnosis tab."""
        slow = []
        for eid, st in self._states.items():
            if st.interval_ema > FAST_UPDATE_S:
                slow.append({
                    "entity_id":       eid,
                    "alpha":           round(st.alpha, 3),
                    "interval_s":      round(st.interval_ema, 1),
                    "spikes_blocked":  st.spikes_blocked,
                    "sample_count":    st.sample_count,
                    "frozen":          (time.time() - st.last_change_ts) > 300,
                })
        total_spikes = sum(st.spikes_blocked for st in self._states.values())
        frozen = [s["entity_id"] for s in slow if s["frozen"]]
        return {
            "slow_sensors":   slow,
            "total_sensors":  len(self._states),
            "spikes_blocked": total_spikes,
            "frozen_sensors": frozen,
        }

    def reset(self, entity_id: str) -> None:
        """Remove EMA state for an entity (e.g. after sensor reconfiguration)."""
        self._states.pop(entity_id, None)
