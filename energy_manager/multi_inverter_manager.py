"""
CloudEMS Multi-Inverter Manager — v1.3.0

Beheert meerdere solar omvormers (strings) als één logische eenheid,
met PID-regeling per fase om oscillatie te voorkomen.

Sturing-prioriteit:
  1. Fase-overbelasting (import/export te hoog)
     → dim EERST de omvormer(s) op de overbelaste fase (via geleerde fase)
     → PID regelt geleidelijk terug naar setpoint (geen bang-bang)
  2. Negatieve EPEX-prijs
     → alle omvormers dimmen naar 0 (of minimum)
  3. Normaal bedrijf
     → alle omvormers op vol vermogen

Per omvormer:
  - Configureerbaar als number-entity (0-100% power) of switch (aan/uit)
  - Prioriteit instellen (welke string eerst terug)
  - Minimaal vermogen (bijv. 200W houden voor eigen verbruik)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .solar_learner import SolarPowerLearner, InverterProfile
from .pid_controller import PIDController

_LOGGER = logging.getLogger(__name__)

# PID default parameters voor fase-stroom regeling
# Setpoint = 90% van max fase-stroom → biedt 10% marge
PID_SETPOINT_RATIO  = 0.90
PID_KP              = 3.0    # Snel reageren op overschrijding
PID_KI              = 0.4    # Langzame opbouw compenseert blijvende afwijking
PID_KD              = 0.8    # Demping bij snelle stijging
PID_DEADBAND_PCT    = 2.0    # 2% output-wijziging minimaal nodig om door te sturen
PID_SAMPLE_TIME_S   = 8.0    # Elke 8 seconden nieuwe berekening

# Herstel-hysteresis: omvormer wordt pas hersteld als stroom HYSTERESIS_A
# onder het setpoint zit (voorkomt direct terug-oscilleren)
RESTORE_HYSTERESIS_A = 2.0


@dataclass
class InverterControl:
    """
    Koppelt een omvormer-sensor aan zijn schakelaar/dimmer.

    entity_id       : sensor die het huidige PV-vermogen leest
    control_entity  : switch.xxx (aan/uit) of number.xxx (0-100%)
    label           : vriendelijke naam
    priority        : 1 = eerder dimmen bij fase-conflict
    min_power_pct   : minimaal output-percentage (0 = volledig uitzetten)
    """
    entity_id: str
    control_entity: str
    label: str           = ""
    priority: int        = 1
    min_power_pct: float = 0.0


@dataclass
class DimDecision:
    """Resultaat van één sturing-ronde."""
    inverter_id: str
    label: str
    action: str                # "dim_pid", "dim_full", "restore", "hold", "negative_price"
    target_pct: float          # 0–100
    reason: str
    pid_state: dict | None = None


class MultiInverterManager:
    """
    Centrale controller voor meerdere PV-omvormers.

    Gebruik vanuit coordinator:
        mgr = MultiInverterManager(hass, entry, controls, learner, max_phase_currents)
        await mgr.async_setup()
        # elke 10s:
        results = await mgr.async_evaluate(phase_currents, current_epex_price)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        inverter_controls: list[InverterControl],
        learner: SolarPowerLearner,
        max_phase_currents: dict[str, float],    # {"L1": 25.0, "L2": 25.0, "L3": 25.0}
        negative_price_threshold: float = 0.0,
    ) -> None:
        self.hass = hass
        self.entry = entry  # may be None when called from coordinator
        self._controls = sorted(inverter_controls, key=lambda x: x.priority)
        self._learner  = learner
        self._max_phase_a = max_phase_currents
        self._neg_threshold = negative_price_threshold

        # Één PID-regelaar per fase
        self._phase_pids: dict[str, PIDController] = {}

        # Huidige output per omvormer (0–100)
        self._current_pct: dict[str, float] = {
            c.entity_id: 100.0 for c in inverter_controls
        }

        self._negative_price_active = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Maak een PID-regelaar aan per geconfigureerde fase."""
        for phase, max_a in self._max_phase_a.items():
            setpoint = max_a * PID_SETPOINT_RATIO
            self._phase_pids[phase] = PIDController(
                kp=PID_KP,
                ki=PID_KI,
                kd=PID_KD,
                setpoint=setpoint,
                output_min=0.0,
                output_max=100.0,
                deadband=PID_DEADBAND_PCT,
                sample_time=PID_SAMPLE_TIME_S,
                label=f"fase_{phase}",
            )
        _LOGGER.info(
            "MultiInverterManager klaar: %d omvormers, fasen: %s",
            len(self._controls),
            {p: f"setpoint={a * PID_SETPOINT_RATIO:.1f}A" for p, a in self._max_phase_a.items()},
        )

    # ── Hoofd-evaluatie ────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        phase_currents: dict[str, float],
        current_epex_price: float | None = None,
    ) -> list[DimDecision]:
        """
        Evalueer alle omvormers en stuur bij waar nodig.
        Geeft lijst van acties terug (voor logging/sensor attributes).
        """
        decisions: list[DimDecision] = []

        # ── 1. Negatieve EPEX-prijs → alles uit ───────────────────────────────
        if current_epex_price is not None and current_epex_price <= self._neg_threshold:
            if not self._negative_price_active:
                _LOGGER.info(
                    "MultiInverterMgr: negatieve prijs %.4f €/kWh — alle omvormers dimmen",
                    current_epex_price,
                )
            self._negative_price_active = True

            for ctrl in self._controls:
                target = ctrl.min_power_pct
                if self._current_pct[ctrl.entity_id] != target:
                    await self._set_output(ctrl, target)
                    decisions.append(DimDecision(
                        inverter_id=ctrl.entity_id,
                        label=ctrl.label or ctrl.entity_id,
                        action="negative_price",
                        target_pct=target,
                        reason=f"EPEX {current_epex_price:.4f} <= {self._neg_threshold:.4f} €/kWh",
                    ))
            return decisions

        # Negatieve prijs voorbij → reset PID's en herstel
        if self._negative_price_active:
            _LOGGER.info("MultiInverterMgr: prijs genormaliseerd — omvormers herstellen")
            self._negative_price_active = False
            for ctrl in self._controls:
                await self._set_output(ctrl, 100.0)
                for pid in self._phase_pids.values():
                    pid.reset()

        # ── 2. Per fase PID-regeling ───────────────────────────────────────────
        phase_decisions = await self._evaluate_phase_limits(phase_currents)
        decisions.extend(phase_decisions)

        # ── 3. Omvormers zonder fase-conflict → herstel naar 100% ─────────────
        controlled_ids = {d.inverter_id for d in decisions}
        for ctrl in self._controls:
            if ctrl.entity_id not in controlled_ids:
                if self._current_pct[ctrl.entity_id] < 100.0:
                    # Controleer of de betrokken fase echt vrij is
                    profile = self._learner.get_profile(ctrl.entity_id)
                    phase = profile.detected_phase if (profile and profile.phase_certain) else None

                    if phase and phase in phase_currents:
                        max_a   = self._max_phase_a.get(phase, 25.0)
                        current = phase_currents[phase]
                        if current < (max_a * PID_SETPOINT_RATIO - RESTORE_HYSTERESIS_A):
                            await self._set_output(ctrl, 100.0)
                            decisions.append(DimDecision(
                                inverter_id=ctrl.entity_id,
                                label=ctrl.label or ctrl.entity_id,
                                action="restore",
                                target_pct=100.0,
                                reason=f"{phase} vrij: {current:.1f}A < {max_a * PID_SETPOINT_RATIO - RESTORE_HYSTERESIS_A:.1f}A",
                            ))
                    else:
                        # Fase onbekend: herstel voorzichtig
                        if all(
                            phase_currents.get(p, 0) < self._max_phase_a.get(p, 25) * PID_SETPOINT_RATIO - RESTORE_HYSTERESIS_A
                            for p in self._max_phase_a
                        ):
                            await self._set_output(ctrl, 100.0)
                            decisions.append(DimDecision(
                                inverter_id=ctrl.entity_id,
                                label=ctrl.label or ctrl.entity_id,
                                action="restore",
                                target_pct=100.0,
                                reason="alle fasen vrij",
                            ))

        return decisions

    # ── Fase-PID sturing ──────────────────────────────────────────────────────

    async def _evaluate_phase_limits(
        self, phase_currents: dict[str, float]
    ) -> list[DimDecision]:
        """
        Per fase: gebruik PID om de meest logische omvormer(s) te dimmen.

        Principe:
          - Bereken PID-output op basis van gemeten fase-stroom
          - PID output 100 = omvormer vol aan, 0 = volledig uit
          - Dim ALLEEN de omvormer(s) die op de overbelaste fase zitten
          - Als fase onbekend: dim in prioriteitsvolgorde
        """
        decisions: list[DimDecision] = []

        for phase, pid in self._phase_pids.items():
            current_a = phase_currents.get(phase)
            if current_a is None:
                continue

            pid_output = pid.compute(current_a)
            if pid_output is None:
                continue  # Sample-time nog niet verstreken

            max_a = self._max_phase_a.get(phase, 25.0)

            # Alleen actie bij overschrijding (PID output < 100 betekent: te hoog)
            if pid_output >= 100.0:
                continue

            # Welke omvormers zitten op deze fase?
            phase_inverters = self._get_inverters_for_phase(phase)
            if not phase_inverters:
                # Fase onbekend voor alle omvormers → gebruik prioriteitsvolgorde
                phase_inverters = self._controls[:1]  # Hoogste prioriteit eerst

            for ctrl in phase_inverters:
                target = max(ctrl.min_power_pct, pid_output)
                if abs(target - self._current_pct[ctrl.entity_id]) >= PID_DEADBAND_PCT:
                    await self._set_output(ctrl, target)
                    decisions.append(DimDecision(
                        inverter_id=ctrl.entity_id,
                        label=ctrl.label or ctrl.entity_id,
                        action="dim_pid",
                        target_pct=round(target, 1),
                        reason=(
                            f"{phase}: {current_a:.1f}A > setpoint {max_a * PID_SETPOINT_RATIO:.1f}A"
                            f" → PID output {pid_output:.1f}%"
                        ),
                        pid_state=pid.to_dict(),
                    ))

        return decisions

    def _get_inverters_for_phase(self, phase: str) -> list[InverterControl]:
        """
        Geeft de omvormers die op de opgegeven fase zitten (via leer-model).
        Sorteert op prioriteit (laagste = eerst dimmen).
        """
        result = []
        for ctrl in self._controls:
            profile = self._learner.get_profile(ctrl.entity_id)
            if profile and profile.phase_certain and profile.detected_phase == phase:
                result.append(ctrl)
        return sorted(result, key=lambda c: c.priority)

    # ── Hardware-aanroepen ────────────────────────────────────────────────────

    async def _set_output(self, ctrl: InverterControl, target_pct: float) -> None:
        """
        Stuur de omvormer aan:
          - number.xxx  → set_value met 0-100
          - switch.xxx  → turn_on (>50%) of turn_off (<=50%)
        """
        target_pct = max(0.0, min(100.0, target_pct))
        entity_id  = ctrl.control_entity
        domain     = entity_id.split(".")[0]

        try:
            if domain == "number":
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": round(target_pct, 1)},
                    blocking=False,
                )
            elif domain == "switch":
                service = "turn_on" if target_pct > 50.0 else "turn_off"
                await self.hass.services.async_call(
                    "switch", service, {"entity_id": entity_id}, blocking=False,
                )
            else:
                # Generiek: probeer set_value, anders turn_on/turn_off
                await self.hass.services.async_call(
                    domain, "set_value",
                    {"entity_id": entity_id, "value": round(target_pct, 1)},
                    blocking=False,
                )
        except Exception as err:
            _LOGGER.warning(
                "MultiInverterMgr: aansturen '%s' mislukt: %s", entity_id, err
            )

        self._current_pct[ctrl.entity_id] = target_pct
        _LOGGER.debug(
            "MultiInverterMgr: '%s' → %.1f%%", ctrl.label or entity_id, target_pct
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "inverters": [
                {
                    "id":            ctrl.entity_id,
                    "label":         ctrl.label,
                    "current_pct":   self._current_pct.get(ctrl.entity_id, 100.0),
                    "priority":      ctrl.priority,
                    "detected_phase": (
                        (self._learner.get_profile(ctrl.entity_id) or {}).detected_phase
                        if self._learner.get_profile(ctrl.entity_id) else None
                    ),
                }
                for ctrl in self._controls
            ],
            "phase_pids": {
                phase: pid.to_dict()
                for phase, pid in self._phase_pids.items()
            },
            "negative_price_active": self._negative_price_active,
        }
