"""
CloudEMS AI Outcome Tracker — v1.0.0

Closes the feedback loop: after every AI decision, measures the actual outcome
N minutes later and feeds a reward/penalty signal back to the model.

Examples:
  - Decided charge_battery at 14:00 → SOC went up 8% → reward +1.0
  - Decided charge_battery but price spiked → reward -0.5
  - Decided run_boiler → boiler reached setpoint → reward +1.0
  - Decided idle but solar was wasted → reward -0.3

This turns the k-NN from a pattern-matcher into a reinforcement-learner.
The reward signal is used to weight samples during training — good decisions
get more weight, bad decisions get less.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# How long to wait before measuring the outcome (seconds)
OUTCOME_DELAY_S = {
    "charge_battery":    600,   # 10 min — check if SOC rose
    "discharge_battery": 600,   # 10 min — check if SOC dropped as expected
    "run_boiler":        900,   # 15 min — check if boiler temp rose
    "defer_load":        1800,  # 30 min — check if price was indeed high
    "export_surplus":    300,   # 5 min — check if export happened
    "idle":              300,   # 5 min — check nothing was missed
}

MAX_PENDING = 50  # max decisions awaiting outcome


@dataclass
class PendingDecision:
    """A decision waiting for its outcome measurement."""
    label:      str
    confidence: float
    ts:         float           # when the decision was made
    features:   list[float]     # feature vector at decision time
    context:    dict            # snapshot of relevant state
    reward:     float = 0.0     # filled in after outcome
    measured:   bool  = False


class OutcomeTracker:
    """
    Tracks AI decisions and measures their outcomes.

    Usage:
        tracker.record(label, confidence, features, context_snapshot)
        # ... time passes ...
        rewards = tracker.tick(current_state)  # returns completed decisions with rewards
    """

    def __init__(self) -> None:
        self._pending: list[PendingDecision] = []
        self._completed: list[PendingDecision] = []
        self._total_reward = 0.0
        self._n_measured = 0

    def record(
        self,
        label:      str,
        confidence: float,
        features:   list[float],
        context:    dict,
    ) -> None:
        """Record a new AI decision for later outcome measurement."""
        if len(self._pending) >= MAX_PENDING:
            # Drop oldest
            self._pending = self._pending[-MAX_PENDING//2:]

        self._pending.append(PendingDecision(
            label=label, confidence=confidence,
            ts=time.time(), features=features, context=context,
        ))

    def tick(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Check pending decisions. Returns list of completed ones with reward signals.
        Call every coordinator tick.
        """
        now = time.time()
        completed = []

        for dec in self._pending[:]:
            delay = OUTCOME_DELAY_S.get(dec.label, 600)
            if now - dec.ts < delay:
                continue

            reward = self._measure_outcome(dec, state)
            dec.reward   = reward
            dec.measured = True
            self._total_reward += reward
            self._n_measured  += 1

            completed.append({
                "label":      dec.label,
                "confidence": dec.confidence,
                "features":   dec.features,
                "reward":     reward,
                "weight":     max(0.1, 0.5 + reward),  # 0.1–1.5 weight for training
                "age_s":      now - dec.ts,
            })

            self._pending.remove(dec)
            self._completed.append(dec)
            if len(self._completed) > 200:
                self._completed = self._completed[-200:]

            _LOGGER.debug(
                "CloudEMS AI outcome: %s → reward=%.2f (confidence was %.0f%%)",
                dec.label, reward, dec.confidence * 100
            )

        return completed

    def _measure_outcome(self, dec: PendingDecision, state: dict) -> float:
        """
        Compute reward for a past decision based on current state.
        Returns -1.0 (bad) to +1.0 (good).
        """
        label = dec.label
        ctx   = dec.context

        # Battery decisions
        if label == "charge_battery":
            soc_before = ctx.get("soc_pct", 50.0) or 50.0
            soc_now    = float(state.get("battery_soc", state.get("battery_soc_pct", 50.0)) or 50.0)
            delta_soc  = soc_now - soc_before
            # Good if SOC rose, bad if it didn't (wasted opportunity)
            if delta_soc > 5:  return min(1.0, delta_soc / 20.0)
            if delta_soc < -2: return -0.5
            return 0.1

        if label == "discharge_battery":
            soc_before = ctx.get("soc_pct", 50.0) or 50.0
            soc_now    = float(state.get("battery_soc", state.get("battery_soc_pct", 50.0)) or 50.0)
            price_now  = float(state.get("epex_price_now", state.get("current_price", 0.15)) or 0.15)
            price_then = ctx.get("epex_price", 0.15) or 0.15
            # Good if price was indeed high and battery discharged
            delta_soc  = soc_before - soc_now
            price_good = price_then > price_now * 0.9  # price was at least as high
            if delta_soc > 3 and price_good: return min(1.0, delta_soc / 15.0)
            if delta_soc < 0: return -0.3  # battery actually charged — wrong direction
            return 0.0

        # Boiler decisions
        if label == "run_boiler":
            temp_before = ctx.get("boiler_temp", 50.0) or 50.0
            temp_now    = float(state.get("boiler_temp_c", 50.0) or 50.0)
            delta_temp  = temp_now - temp_before
            if delta_temp > 3:  return min(1.0, delta_temp / 10.0)
            if delta_temp < -1: return -0.2
            return 0.1

        # Defer load — was price actually high later?
        if label == "defer_load":
            price_then = ctx.get("epex_price", 0.15) or 0.15
            price_now  = float(state.get("epex_price_now", state.get("current_price", 0.15)) or 0.15)
            # Good if price dropped (we successfully deferred to a cheaper time)
            if price_now < price_then * 0.85: return 0.7
            if price_now > price_then:        return -0.3
            return 0.0

        # Export surplus
        if label == "export_surplus":
            export_now = float(state.get("export_power", 0.0) or 0.0)
            if export_now > 200: return 0.6
            return 0.0

        # Idle — was there a missed opportunity?
        if label == "idle":
            solar_w = float(state.get("solar_power", 0.0) or 0.0)
            soc_now = float(state.get("battery_soc", 100.0) or 100.0)
            export  = float(state.get("export_power", 0.0) or 0.0)
            # Penalty if we exported a lot while battery wasn't full (missed charge)
            if export > 500 and soc_now < 90: return -0.4
            return 0.3  # idle is usually fine

        return 0.0

    @property
    def stats(self) -> dict:
        return {
            "pending":       len(self._pending),
            "completed":     len(self._completed),
            "n_measured":    self._n_measured,
            "avg_reward":    round(self._total_reward / max(1, self._n_measured), 3),
        }
