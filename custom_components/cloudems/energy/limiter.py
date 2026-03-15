# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Current Limiter — energy/limiter.py v1.4.1

BUG FIXES vs v1.4.0:
  - _PhaseState now has voltage_v + derived_from fields (coordinator sets them)
  - update_phase: accepts current_a directly instead of deriving from P/230 V
  - get_phase_summary: returns voltage_v + derived_from
  - Hardcoded GRID_VOLTAGE removed from current derivation (handled by power_calculator)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

_LOGGER = logging.getLogger(__name__)

HYSTERESIS_A   = 2.0
MIN_THROTTLE_S = 20
GRID_VOLTAGE   = 230.0   # fallback only when no sensor available


@dataclass
class _PhaseState:
    """Runtime state per phase."""
    max_ampere:    float = 25.0
    current_a:     float = 0.0
    power_w:       float = 0.0
    voltage_v:     float = GRID_VOLTAGE   # ← FIX: was missing in v1.4.0
    voltage_ema:   float = 0.0            # EMA voor afgevlakte spanning (0 = nog niet geïnitialiseerd)
    derived_from:  str   = "direct"       # ← FIX: was missing in v1.4.0
    solar_w:       float = 0.0
    battery_w:     float = 0.0
    limited:       bool  = False
    last_limit_ts: float = 0.0
    has_data:      bool  = False          # reserved


class CurrentLimiter:
    """
    Central current limiter for CloudEMS.

    Interface expected by coordinator / platforms:
        evaluate_and_act()
        update_phase(phase, current_a, power_w, voltage_v, derived_from)
        optimize_ev_charging(solar_surplus_w)
        set_negative_price_mode(bool)
        set_max_current(phase, ampere)
        get_phase_summary() -> dict
        ev_charging_current     (property)
        solar_curtailment_percent (property)
        phase_currents          (property)
        _phases                 (dict[str, _PhaseState])
    """

    def __init__(
        self,
        max_current_per_phase: float = 25.0,
        ev_charger_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        solar_inverter_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self._max_current = max_current_per_phase
        self._ev_cb       = ev_charger_callback
        self._solar_cb    = solar_inverter_callback

        self._phases: dict[str, _PhaseState] = {
            "L1": _PhaseState(max_ampere=max_current_per_phase),
            "L2": _PhaseState(max_ampere=max_current_per_phase),
            "L3": _PhaseState(max_ampere=max_current_per_phase),
        }

        self._negative_price_mode:   bool  = False
        self._ev_target_current:     float = 0.0
        self._solar_curtailment_pct: float = 0.0

    # ── Update ────────────────────────────────────────────────────────────────

    def update_phase(
        self,
        phase: str,
        current_a: float = 0.0,
        power_w:   float = 0.0,
        voltage_v: float = GRID_VOLTAGE,
        derived_from: str = "direct",
        solar_w:   float = 0.0,
        battery_w: float = 0.0,
    ) -> None:
        """Update phase readings. current_a is the authoritative value."""
        p = self._phases.get(phase)
        if not p:
            return
        p.current_a    = current_a
        p.power_w      = power_w
        p.derived_from = derived_from
        p.has_data     = True
        p.solar_w      = solar_w
        p.battery_w    = battery_w
        # EMA spanning (α=0.15 ≈ ~13 samples tijdconstante bij 10s polling)
        # Hiermee worden korte P1-telegram pieken/dalen weggefilterd.
        raw_v = voltage_v if voltage_v and voltage_v > 50 else GRID_VOLTAGE
        _EMA_ALPHA = 0.15
        if p.voltage_ema < 50:
            p.voltage_ema = raw_v   # initialiseer met eerste meting
        else:
            p.voltage_ema = _EMA_ALPHA * raw_v + (1 - _EMA_ALPHA) * p.voltage_ema
        p.voltage_v = round(p.voltage_ema, 1)

    # ── Evaluate ──────────────────────────────────────────────────────────────

    async def evaluate_and_act(self) -> None:
        now = time.time()
        for phase, p in self._phases.items():
            over_limit = abs(p.current_a) > p.max_ampere
            if over_limit and not p.limited:
                _LOGGER.warning(
                    "Phase %s current %.1fA > limit %.1fA — limiting",
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
                _LOGGER.info("Phase %s normalised — limit released", phase)
                p.limited = False

    async def optimize_ev_charging(self, solar_surplus_w: float) -> None:
        if not self._ev_cb:
            return
        voltage   = self._phases["L1"].voltage_v or GRID_VOLTAGE
        solar_a   = solar_surplus_w / voltage
        headroom  = min(p.max_ampere - abs(p.current_a) for p in self._phases.values())
        target    = max(6.0, min(32.0, solar_a, self._ev_target_current + headroom))
        if abs(target - self._ev_target_current) >= 1.0:
            self._ev_target_current = target
            await self._ev_cb(target)

    def set_negative_price_mode(self, active: bool) -> None:
        self._negative_price_mode    = active
        self._solar_curtailment_pct  = 100.0 if active else 0.0
        if self._solar_cb:
            import asyncio
            asyncio.ensure_future(self._solar_cb(self._solar_curtailment_pct))

    def set_max_current(self, phase: str, ampere: float) -> None:
        targets = list(self._phases.keys()) if phase.lower() == "all" else [phase.upper()]
        for pk in targets:
            if pk in self._phases:
                self._phases[pk].max_ampere = ampere
                _LOGGER.info("Phase %s limit updated → %.1fA", pk, ampere)

    def get_phase_summary(self) -> dict[str, Any]:
        return {
            phase: {
                "current_a":     round(p.current_a, 3),
                "max_import_a":  p.max_ampere,
                "power_w":       round(p.power_w, 1),
                "voltage_v":     round(p.voltage_v, 1),   # ← FIX
                "derived_from":  p.derived_from,           # ← FIX
                "limited":       p.limited,
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
        return {phase: p.current_a for phase, p in self._phases.items()}

    @property
    def phase_voltages(self) -> dict[str, float]:
        return {phase: p.voltage_v for phase, p in self._phases.items()}

    def get_voltage_ema(self, phase: str) -> float | None:
        """Geef de EMA-spanning voor een fase terug, of None als nog niet geïnitialiseerd."""
        p = self._phases.get(phase)
        return p.voltage_ema if (p and p.voltage_ema > 50) else None
