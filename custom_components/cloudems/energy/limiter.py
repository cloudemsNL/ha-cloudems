"""
CloudEMS Current Limiter — energy/limiter.py

Provides the CurrentLimiter class used by the coordinator.
Handles per-phase import/export limiting, EV charging current
management and solar curtailment.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

_LOGGER = logging.getLogger(__name__)

HYSTERESIS_A   = 2.0    # A — stroom moet dit ver onder limiet komen voor herstel
MIN_THROTTLE_S = 20     # s — minimale tijd voor een re-enable
GRID_VOLTAGE   = 230.0  # V


@dataclass
class _PhaseState:
    """Runtime toestand per fase."""
    max_ampere:    float = 25.0
    current_a:     float = 0.0
    power_w:       float = 0.0
    solar_w:       float = 0.0
    battery_w:     float = 0.0
    limited:       bool  = False
    last_limit_ts: float = 0.0


class CurrentLimiter:
    """
    Centrale stroom-limiter voor CloudEMS.

    Interface verwacht door coordinator / platforms:
        evaluate_and_act()
        update_phase(phase, power_w, solar_w, battery_w)
        optimize_ev_charging(solar_surplus_w)
        set_negative_price_mode(bool)
        set_max_current(phase, ampere)
        get_phase_summary() -> dict
        ev_charging_current     (property)
        solar_curtailment_percent (property)
        _negative_price_mode    (attribute)
        _phases                 (dict[str, _PhaseState])
        _ev_target_current      (attribute)
    """

    def __init__(
        self,
        max_current_per_phase: float = 25.0,
        ev_charger_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        solar_inverter_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self._max_current = max_current_per_phase
        self._ev_cb = ev_charger_callback
        self._solar_cb = solar_inverter_callback

        self._phases: dict[str, _PhaseState] = {
            "L1": _PhaseState(max_ampere=max_current_per_phase),
            "L2": _PhaseState(max_ampere=max_current_per_phase),
            "L3": _PhaseState(max_ampere=max_current_per_phase),
        }

        self._negative_price_mode: bool = False
        self._ev_target_current:   float = 0.0
        self._solar_curtailment_pct: float = 0.0

    # ── Coordinator-facing API ────────────────────────────────────────────────

    def update_phase(
        self,
        phase: str,
        power_w: float,
        solar_w: float = 0.0,
        battery_w: float = 0.0,
    ) -> None:
        """Verwerk nieuwe sensorwaarden voor één fase."""
        p = self._phases.get(phase)
        if not p:
            return
        p.power_w   = power_w
        p.solar_w   = solar_w
        p.battery_w = battery_w
        p.current_a = power_w / GRID_VOLTAGE if GRID_VOLTAGE else 0.0

    async def evaluate_and_act(self) -> None:
        """Controleer alle fasen en stuur bij waar nodig."""
        now = time.time()
        for phase, p in self._phases.items():
            over_limit = abs(p.current_a) > p.max_ampere
            if over_limit and not p.limited:
                _LOGGER.warning(
                    "Fase %s stroom %.1fA > limiet %.1fA — beperken",
                    phase, p.current_a, p.max_ampere,
                )
                p.limited       = True
                p.last_limit_ts = now
                if self._ev_cb and self._ev_target_current > 6.0:
                    new_ev = max(6.0, self._ev_target_current - 2.0)
                    self._ev_target_current = new_ev
                    await self._ev_cb(new_ev)
            elif (
                p.limited
                and abs(p.current_a) < (p.max_ampere - HYSTERESIS_A)
                and (now - p.last_limit_ts) > MIN_THROTTLE_S
            ):
                _LOGGER.info("Fase %s stroom genormaliseerd — limiet opgeheven", phase)
                p.limited = False

    async def optimize_ev_charging(self, solar_surplus_w: float) -> None:
        """Pas EV laadstroom aan op zonne-energie overschot."""
        if not self._ev_cb:
            return
        solar_current = solar_surplus_w / GRID_VOLTAGE
        min_headroom  = min(
            (p.max_ampere - abs(p.current_a)) for p in self._phases.values()
        )
        target = max(6.0, min(32.0, solar_current, self._ev_target_current + min_headroom))
        if abs(target - self._ev_target_current) >= 1.0:
            self._ev_target_current = target
            await self._ev_cb(target)

    def set_negative_price_mode(self, active: bool) -> None:
        """Activeer/deactiveer zonne-energie afschakeling bij negatieve prijs."""
        self._negative_price_mode = active
        self._solar_curtailment_pct = 100.0 if active else 0.0
        if self._solar_cb:
            import asyncio
            asyncio.ensure_future(self._solar_cb(self._solar_curtailment_pct))

    def set_max_current(self, phase: str, ampere: float) -> None:
        """Pas maximale stroom aan voor een fase (of 'all')."""
        targets = list(self._phases.keys()) if phase.lower() == "all" else [phase.upper()]
        for p_key in targets:
            if p_key in self._phases:
                self._phases[p_key].max_ampere = ampere
                _LOGGER.info("Fase %s limiet bijgewerkt → %.1fA", p_key, ampere)

    def get_phase_summary(self) -> dict[str, Any]:
        """Overzicht per fase — gebruikt door coordinator en sensors."""
        return {
            phase: {
                "current_a":      round(p.current_a, 2),
                "max_import_a":   p.max_ampere,
                "power_w":        round(p.power_w, 1),
                "limited":        p.limited,
                "utilisation_pct": (
                    round(abs(p.current_a) / p.max_ampere * 100, 1)
                    if p.max_ampere else 0.0
                ),
            }
            for phase, p in self._phases.items()
        }

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def ev_charging_current(self) -> float:
        return self._ev_target_current

    @property
    def solar_curtailment_percent(self) -> float:
        return self._solar_curtailment_pct

    @property
    def phase_currents(self) -> dict[str, float]:
        """Stroom per fase — gebruikt door energy_manager submodules."""
        return {phase: p.current_a for phase, p in self._phases.items()}
