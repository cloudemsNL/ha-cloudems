"""
CloudEMS Phase Balancer.

Detects current imbalance across L1/L2/L3 and suggests or executes
load re-distribution for three-phase installations.

Rules
-----
* Imbalance  = max(phases) − min(phases)  > threshold
* CloudEMS logs a warning and fires an event so automations can act.
* If an EV charger entity is configured it is moved to the least-loaded
  phase whenever possible (via HA number entity).

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_PHASE_BALANCE_THRESHOLD,
    DEFAULT_PHASE_BALANCE_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

EVENT_PHASE_IMBALANCE = f"{DOMAIN}_phase_imbalance"


@dataclass
class BalanceStatus:
    phase_currents: dict[str, float]
    imbalance_a: float
    overloaded_phase: str | None
    lightest_phase: str | None
    balanced: bool
    recommendation: str


class PhaseBalancer:
    """Monitor and report three-phase current imbalance."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._threshold: float = float(
            config.get(CONF_PHASE_BALANCE_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD)
        )
        self._last_imbalanced: bool = False

    # ── Public API ─────────────────────────────────────────────────────────────

    async def async_check(self, phase_currents: dict[str, float]) -> BalanceStatus:
        """Evaluate balance; fire HA event if imbalance detected."""
        status = self._evaluate(phase_currents)

        if not status.balanced and not self._last_imbalanced:
            _LOGGER.warning(
                "PhaseBalancer: imbalance %.1fA (threshold %.1fA) — %s",
                status.imbalance_a,
                self._threshold,
                status.recommendation,
            )
            self.hass.bus.async_fire(
                EVENT_PHASE_IMBALANCE,
                {
                    "imbalance_a": status.imbalance_a,
                    "overloaded_phase": status.overloaded_phase,
                    "lightest_phase": status.lightest_phase,
                    "phase_currents": status.phase_currents,
                    "recommendation": status.recommendation,
                },
            )

        self._last_imbalanced = not status.balanced
        return status

    def get_phase_utilisation(
        self, phase_currents: dict[str, float], max_current_per_phase: dict[str, float]
    ) -> dict[str, float]:
        """Return utilisation % per phase (0–100)."""
        result = {}
        for phase, current in phase_currents.items():
            max_a = max_current_per_phase.get(phase, 25.0)
            result[phase] = round(abs(current) / max_a * 100, 1) if max_a else 0.0
        return result

    # ── Internal ───────────────────────────────────────────────────────────────

    def _evaluate(self, phase_currents: dict[str, float]) -> BalanceStatus:
        if len(phase_currents) < 2:
            return BalanceStatus(
                phase_currents=phase_currents,
                imbalance_a=0.0,
                overloaded_phase=None,
                lightest_phase=None,
                balanced=True,
                recommendation="single-phase — balancing not applicable",
            )

        max_phase = max(phase_currents, key=lambda p: phase_currents[p])
        min_phase = min(phase_currents, key=lambda p: phase_currents[p])
        imbalance = phase_currents[max_phase] - phase_currents[min_phase]
        balanced = imbalance <= self._threshold

        recommendation = (
            "balanced ✓"
            if balanced
            else (
                f"move load from {max_phase} "
                f"({phase_currents[max_phase]:.1f}A) "
                f"to {min_phase} "
                f"({phase_currents[min_phase]:.1f}A)"
            )
        )

        return BalanceStatus(
            phase_currents=dict(phase_currents),
            imbalance_a=round(imbalance, 2),
            overloaded_phase=max_phase if not balanced else None,
            lightest_phase=min_phase if not balanced else None,
            balanced=balanced,
            recommendation=recommendation,
        )
