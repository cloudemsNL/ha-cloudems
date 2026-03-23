# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Phase Outlet Detector v1.0.0

Automatically determines which electrical phase (L1/L2/L3) each smart plug
or NILM device is connected to, without requiring manual configuration.

How it works:
  1. When a device switches ON (detected by NILM or smart plug power spike),
     record the simultaneous change in L1/L2/L3 phase currents from P1/limiter.
  2. The phase that shows the largest current increase matches the device.
  3. Repeat for several on/off cycles to build confidence.
  4. Once confidence >= threshold, mark the outlet's phase as known.

This replaces the manual "which phase is this device on?" question in the wizard.
The result feeds back into NILM phase-attribution and peak shaving.

Requirements:
  - Per-phase current data (from P1 DSMR or phase current sensors)
  - At least 3 on/off cycles per device for reliable detection
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Minimum current change to consider as "this phase reacted" (Ampere)
MIN_CURRENT_DELTA_A     = 0.3
# Minimum confidence (0-1) before marking phase as known
MIN_CONFIDENCE          = 0.75
# Number of on/off cycles to observe before making a decision
MIN_OBSERVATIONS        = 3
# Max age of an observation in seconds (discard stale data)
MAX_OBS_AGE_S           = 300.0


@dataclass
class PhaseObservation:
    """Single on/off event with phase current snapshot."""
    timestamp:  float
    delta_l1:   float   # current change on L1 (A)
    delta_l2:   float
    delta_l3:   float
    power_w:    float   # device power at the time


@dataclass
class OutletPhaseResult:
    """Detected phase assignment for one outlet/device."""
    entity_id:   str
    device_name: str
    phase:       Optional[str]   = None   # "L1" / "L2" / "L3" / None
    confidence:  float           = 0.0   # 0.0 – 1.0
    observations: int            = 0
    locked:      bool            = False  # True once confidence >= threshold
    votes:       dict            = field(default_factory=lambda: {"L1": 0, "L2": 0, "L3": 0})


class PhaseOutletDetector:
    """
    Detects which phase each smart plug / NILM device is connected to
    by correlating power-on events with phase current changes.
    """

    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass    = hass
        # entity_id → list of observations
        self._obs:    dict[str, list[PhaseObservation]] = {}
        # entity_id → result
        self._results: dict[str, OutletPhaseResult] = {}
        # Last known phase currents snapshot
        self._prev_currents: dict[str, float] = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
        self._prev_ts: float = 0.0

    def update_phase_currents(self, l1_a: float, l2_a: float, l3_a: float) -> None:
        """Call every coordinator cycle with current phase currents."""
        self._prev_currents = {"L1": l1_a, "L2": l2_a, "L3": l3_a}
        self._prev_ts = time.time()

    def on_device_power_change(self, entity_id: str, device_name: str,
                                power_before_w: float, power_after_w: float,
                                current_l1: float, current_l2: float, current_l3: float) -> None:
        """
        Call when a device switches on/off.
        Compares current phase currents with the snapshot before the change.
        """
        result = self._results.get(entity_id)
        if result and result.locked:
            return  # Already confident, skip

        # Only process power-on events (delta > 20W)
        delta_w = power_after_w - power_before_w
        if delta_w < 20:
            return

        # Delta per phase vs previous snapshot
        delta_l1 = current_l1 - self._prev_currents["L1"]
        delta_l2 = current_l2 - self._prev_currents["L2"]
        delta_l3 = current_l3 - self._prev_currents["L3"]

        obs = PhaseObservation(
            timestamp = time.time(),
            delta_l1  = delta_l1,
            delta_l2  = delta_l2,
            delta_l3  = delta_l3,
            power_w   = delta_w,
        )

        if entity_id not in self._obs:
            self._obs[entity_id] = []
        self._obs[entity_id].append(obs)

        # Prune old observations
        cutoff = time.time() - MAX_OBS_AGE_S * 10  # keep longer for slow devices
        self._obs[entity_id] = [o for o in self._obs[entity_id] if o.timestamp > cutoff]

        # Update result
        self._evaluate(entity_id, device_name)

    def _evaluate(self, entity_id: str, device_name: str) -> None:
        """Re-evaluate phase assignment based on all observations."""
        observations = self._obs.get(entity_id, [])
        if not observations:
            return

        votes: dict[str, int] = {"L1": 0, "L2": 0, "L3": 0}
        valid = 0

        for obs in observations:
            # Find the phase with the largest positive current increase
            deltas = {"L1": obs.delta_l1, "L2": obs.delta_l2, "L3": obs.delta_l3}
            best_phase = max(deltas, key=lambda k: deltas[k])
            best_delta = deltas[best_phase]

            if best_delta >= MIN_CURRENT_DELTA_A:
                votes[best_phase] += 1
                valid += 1

        if valid < MIN_OBSERVATIONS:
            # Not enough valid observations yet
            result = self._results.get(entity_id, OutletPhaseResult(
                entity_id=entity_id, device_name=device_name
            ))
            result.observations = valid
            result.votes = votes
            self._results[entity_id] = result
            return

        # Determine winning phase
        winning_phase = max(votes, key=lambda k: votes[k])
        confidence    = votes[winning_phase] / valid

        result = self._results.get(entity_id, OutletPhaseResult(
            entity_id=entity_id, device_name=device_name
        ))
        result.phase        = winning_phase if confidence >= MIN_CONFIDENCE else None
        result.confidence   = round(confidence, 2)
        result.observations = valid
        result.votes        = votes
        result.locked       = confidence >= MIN_CONFIDENCE

        if result.locked:
            _LOGGER.info(
                "PhaseOutletDetector: %s (%s) → %s (confidence=%.0f%%, %d obs)",
                device_name, entity_id, winning_phase,
                confidence * 100, valid,
            )

        self._results[entity_id] = result

    def get_phase(self, entity_id: str) -> Optional[str]:
        """Get detected phase for an entity, or None if not yet determined."""
        result = self._results.get(entity_id)
        return result.phase if result and result.locked else None

    def get_all_results(self) -> list[dict]:
        """All results for coordinator data / dashboard."""
        return [
            {
                "entity_id":   r.entity_id,
                "device_name": r.device_name,
                "phase":       r.phase,
                "confidence":  r.confidence,
                "observations":r.observations,
                "locked":      r.locked,
                "votes":       r.votes,
            }
            for r in sorted(self._results.values(), key=lambda x: x.device_name)
        ]

    def get_summary(self) -> dict:
        """Summary for sensor attribute."""
        results = list(self._results.values())
        locked  = [r for r in results if r.locked]
        return {
            "total_devices":   len(results),
            "locked_devices":  len(locked),
            "l1_devices":      sum(1 for r in locked if r.phase == "L1"),
            "l2_devices":      sum(1 for r in locked if r.phase == "L2"),
            "l3_devices":      sum(1 for r in locked if r.phase == "L3"),
            "devices":         self.get_all_results(),
        }
