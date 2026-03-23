# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Multi-Inverter Manager — v1.4.0

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

Nieuw in v1.4.0:
  - PhaseProber: actieve fase-detectie via korte dim-pulsen.
    Werkt alleen voor omvormers met een control_entity (dimmer-regelaar).
    Stelt detected_phase/phase_certain in via SolarPowerLearner.
    Roep async_tick() aan elke coordinator-cyclus.

Per omvormer:
  - Configureerbaar als number-entity (0-100% power of 0-rated_power_w W) of switch (aan/uit)
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
from homeassistant.helpers.event import async_call_later

from .solar_learner import SolarPowerLearner, InverterProfile
from .pid_controller import PIDController
from .phase_prober import PhaseProber

_LOGGER = logging.getLogger(__name__)

# PID default parameters voor fase-stroom regeling
# Setpoint = 97% van max fase-stroom.
# B-karakteristiek automaten verdragen tijdelijk 1.13×–1.45× de nominale stroom
# voordat ze uitschakelen. De PID reageert binnen enkele seconden, ruim binnen
# de thermische tijdconstante van de automaat. 97% geeft voldoende marge terwijl
# PV-opbrengst maximaal benut wordt.
PID_SETPOINT_RATIO  = 0.97
PID_KP              = 3.0    # Snel reageren op overschrijding
PID_KI              = 0.4    # Langzame opbouw compenseert blijvende afwijking
PID_KD              = 0.8    # Demping bij snelle stijging
PID_DEADBAND_PCT    = 2.0    # 2% output-wijziging minimaal nodig om door te sturen
PID_SAMPLE_TIME_S   = 8.0    # Elke 8 seconden nieuwe berekening

# Herstel-hysteresis: omvormer wordt pas hersteld als stroom HYSTERESIS_A
# onder het setpoint zit (voorkomt direct terug-oscilleren)
RESTORE_HYSTERESIS_A = 4.0   # v4.6.508: verhoogd van 2.0 → 4.0A (was te klein)

# v4.6.508: minimum tijd (seconden) dat een omvormer gedimmed blijft voordat
# herstel naar 100% mag plaatsvinden. Voorkomt PID-jacht / heen-en-weer oscilleren.
MIN_DIM_DURATION_S = 60

# Handmatige dim-override: na deze tijd hervat de automatische sturing
# 30 minuten — genoeg om handmatig te testen, kort genoeg om nooit surplus te missen
MANUAL_DIM_RESUME_DELAY_S = 1800  # 30 minuten

# Zekeringshiërarchie voor pre-warning meldingen
# B-karakteristiek automaten (groepenkast): schakelt uit bij 1.13–1.45× nominaal (thermisch)
# gG/gL hoofdzekering (aansluitkast): smelt bij 1.45× nominaal gedurende langere tijd
# De PID reageert binnen 8s — ruim binnen de thermische tijdconstante van beide.
B_CHAR_FACTOR = 1.13   # B-automaat nadert thermisch gebied (waarschuwing)
GG_CHAR_FACTOR = 1.45  # gG hoofdzekering nadert smeltgebied (kritisch — mag NOOIT)


@dataclass
class InverterControl:
    """
    Koppelt een omvormer-sensor aan zijn schakelaar/dimmer.

    entity_id       : sensor die het huidige PV-vermogen leest
    control_entity  : switch.xxx (aan/uit) of number.xxx (0-100% of 0-rated_power_w W)
    label           : vriendelijke naam
    priority        : 1 = eerder dimmen bij fase-conflict
    min_power_pct   : minimaal output-percentage (0 = volledig uitzetten)
    rated_power_w   : nominaal piek-vermogen (W); indien ingesteld én de control-entity
                      heeft een max > 100, dan wordt in Watt aangestuurd i.p.v. procent
    """
    entity_id: str
    control_entity: str
    label: str           = ""
    priority: int        = 1
    min_power_pct: float = 0.0
    rated_power_w: float | None = None


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

        # Manual-override per inverter: user can temporarily set a dim level
        # via the dashboard slider. Auto-control resumes next evaluate cycle.
        # _manual_dim_pct: None = no override, 0–100 = forced setpoint
        self._manual_dim_timers: dict[str, object] = {}
        self._manual_dim_pct: dict[str, float | None] = {
            c.entity_id: None for c in inverter_controls
        }
        self._manual_dim_set_at: dict[str, float] = {}  # timestamp when manual dim was set
        # Last decision per inverter for dashboard display
        self._last_decision: dict[str, DimDecision | None] = {
            c.entity_id: None for c in inverter_controls
        }
        # Per-inverter dimmer enable flag (mirrors the config "solar_dimmer" flag
        # but can be toggled at runtime via the dashboard switch)
        self._dimmer_enabled: dict[str, bool] = {
            c.entity_id: getattr(c, "solar_dimmer", True) for c in inverter_controls
        }
        # v4.6.508: tijdstip van laatste dim-actie per omvormer —
        # herstel naar 100% mag pas na MIN_DIM_DURATION_S
        self._last_dim_ts: dict[str, float] = {
            c.entity_id: 0.0 for c in inverter_controls
        }
        # Phase prober — aangemaakt in async_setup
        self._phase_prober: "PhaseProber | None" = None
        # Over-setpoint tracking per fase — voor pre-warning countdown in dashboard
        # _over_setpoint_since: timestamp waarop fase voor het eerst boven setpoint ging
        # _last_warn_level: 0=geen, 1=nominaal, 2=B-kar, 3=gG (alleen loggen bij wijziging)
        self._over_setpoint_since: dict[str, float | None] = {}
        self._last_warn_level: dict[str, int] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Maak een PID-regelaar aan per geconfigureerde fase en start PhaseProber."""
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
        # Initialiseer PhaseProber voor omvormers met een dimmer-regelaar
        probeable = [c for c in self._controls if c.control_entity]
        if probeable:
            self._phase_prober = PhaseProber(self.hass, self, self._learner)
            _LOGGER.info(
                "MultiInverterManager: PhaseProber actief voor %d omvormer(s) met dimmer",
                len(probeable),
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

        # ── 0. PhaseProber tick (actieve fase-detectie via dim-pulsen) ─────────
        # Alleen uitvoeren als er geen overbelasting of handmatige override actief is.
        # De prober stuurt zelf nooit tijdens negatieve prijs.
        if self._phase_prober:
            neg_active = (
                current_epex_price is not None
                and current_epex_price <= self._neg_threshold
            )
            await self._phase_prober.async_tick(
                phase_currents=phase_currents,
                negative_price_active=neg_active,
            )

        # ── 1. Negatieve EPEX-prijs → alles uit ───────────────────────────────
        if current_epex_price is not None and current_epex_price <= self._neg_threshold:
            if not self._negative_price_active:
                _LOGGER.info(
                    "MultiInverterMgr: negatieve all-in prijs %.4f €/kWh — alle omvormers dimmen",
                    current_epex_price,
                )
            self._negative_price_active = True

            for ctrl in self._controls:
                # v4.5.106: respecteer schakelaar — uitgeschakelde omvormer niet dimmen
                if not self._dimmer_enabled.get(ctrl.entity_id, True):
                    if self._current_pct[ctrl.entity_id] < 100.0:
                        await self._set_output(ctrl, 100.0)
                    continue
                target = ctrl.min_power_pct
                if self._current_pct[ctrl.entity_id] != target:
                    await self._set_output(ctrl, target)
                    decisions.append(DimDecision(
                        inverter_id=ctrl.entity_id,
                        label=ctrl.label or ctrl.entity_id,
                        action="negative_price",
                        target_pct=target,
                        reason=f"all-in {current_epex_price:.4f} <= {self._neg_threshold:.4f} €/kWh",
                    ))
            return decisions

        # Negatieve prijs voorbij → reset PID's en herstel
        if self._negative_price_active:
            _LOGGER.info("MultiInverterMgr: prijs genormaliseerd — omvormers herstellen")
            self._negative_price_active = False
            for ctrl in self._controls:
                # v4.5.106: uitgeschakelde omvormer laten staan op 100% (al gedaan door 1b)
                if self._dimmer_enabled.get(ctrl.entity_id, True):
                    await self._set_output(ctrl, 100.0)
                for pid in self._phase_pids.values():
                    pid.reset()

        # ── 1b. Dimmer uitgeschakeld per omvormer → forceer 100% ─────────────
        for ctrl in self._controls:
            if not self._dimmer_enabled.get(ctrl.entity_id, True):
                if self._current_pct[ctrl.entity_id] < 100.0:
                    await self._set_output(ctrl, 100.0)
                continue  # skip PID for this inverter

        # ── 1c. Handmatige dim-override (tijdelijk vanuit dashboard) ──────────
        # Manual override takes precedence over PID but not over negative price.
        for ctrl in self._controls:
            manual = self._manual_dim_pct.get(ctrl.entity_id)
            if manual is not None:
                if abs(manual - self._current_pct[ctrl.entity_id]) >= 1.0:
                    await self._set_output(ctrl, manual)
                    decisions.append(DimDecision(
                        inverter_id=ctrl.entity_id,
                        label=ctrl.label or ctrl.entity_id,
                        action="manual_override",
                        target_pct=manual,
                        reason="Handmatige instelling via dashboard",
                    ))

        # ── 2. Per fase PID-regeling ───────────────────────────────────────────
        phase_decisions = await self._evaluate_phase_limits(phase_currents)
        decisions.extend(phase_decisions)

        # ── 3. Omvormers zonder fase-conflict → herstel naar 100% ─────────────
        controlled_ids = {d.inverter_id for d in decisions}
        _now = __import__("time").time()
        for ctrl in self._controls:
            if ctrl.entity_id not in controlled_ids:
                if self._current_pct[ctrl.entity_id] < 100.0:
                    # v4.6.508: wacht minimaal MIN_DIM_DURATION_S na laatste dim
                    # voordat we herstellen — voorkomt PID-jacht
                    elapsed_since_dim = _now - self._last_dim_ts.get(ctrl.entity_id, 0.0)
                    if elapsed_since_dim < MIN_DIM_DURATION_S:
                        continue  # nog te vroeg — blijf gedimmed

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

        # v4.5.108: sla laatste beslissing op per omvormer voor dashboard display
        for d in decisions:
            self._last_decision[d.inverter_id] = d
        # Omvormers zonder beslissing dit rondje → actie = "idle" (op vol vermogen)
        for ctrl in self._controls:
            if ctrl.entity_id not in {d.inverter_id for d in decisions}:
                self._last_decision[ctrl.entity_id] = DimDecision(
                    inverter_id=ctrl.entity_id,
                    label=ctrl.label or ctrl.entity_id,
                    action="idle",
                    target_pct=self._current_pct.get(ctrl.entity_id, 100.0),
                    reason="✅ Automatisch beheer — vol vermogen",
                )

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
        import time as _time
        decisions: list[DimDecision] = []

        for phase, pid in self._phase_pids.items():
            current_a = phase_currents.get(phase)
            if current_a is None:
                # Fase verdwenen → reset tracking
                self._over_setpoint_since.pop(phase, None)
                self._last_warn_level.pop(phase, None)
                continue

            max_a = self._max_phase_a.get(phase, 25.0)
            setpoint_a = max_a * PID_SETPOINT_RATIO

            # ── Pre-warning: fase boven setpoint maar PID-sample nog niet verstreken ──
            if current_a > setpoint_a:
                now = _time.time()
                if self._over_setpoint_since.get(phase) is None:
                    self._over_setpoint_since[phase] = now

                elapsed = now - self._over_setpoint_since[phase]
                remaining = max(0.0, PID_SAMPLE_TIME_S - elapsed)

                # Bepaal waarschuwingsniveau
                if current_a >= max_a * GG_CHAR_FACTOR:
                    level = 3  # kritisch
                elif current_a >= max_a * B_CHAR_FACTOR:
                    level = 2  # B-kar grens
                else:
                    level = 1  # boven setpoint, binnen nominaal

                prev_level = self._last_warn_level.get(phase, 0)
                if level != prev_level:
                    self._last_warn_level[phase] = level
                    b_lim = max_a * B_CHAR_FACTOR
                    gg_lim = max_a * GG_CHAR_FACTOR
                    msg = (
                        f"Fase {phase}: {current_a:.1f}A > setpoint {setpoint_a:.1f}A — "
                        f"dimmer grijpt in over {remaining:.0f}s "
                        f"(B-kar veilig tot {b_lim:.1f}A, gG tot {gg_lim:.1f}A)"
                    )
                    if level == 3:
                        _LOGGER.error("⛔ ZonneDimmer KRITISCH: %s", msg)
                    elif level == 2:
                        _LOGGER.warning("⚠️ ZonneDimmer: %s", msg)
                    else:
                        _LOGGER.info("ℹ️ ZonneDimmer: %s", msg)
            else:
                # Fase weer onder setpoint → reset tracking
                self._over_setpoint_since[phase] = None
                self._last_warn_level[phase] = 0

            pid_output = pid.compute(current_a)
            if pid_output is None:
                continue  # Sample-time nog niet verstreken

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
                    self._last_dim_ts[ctrl.entity_id] = __import__("time").time()  # v4.6.508
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
          - number.xxx  → set_value in Watt (als rated_power_w bekend is of entity-max > 100)
                          of in procent (0-100) als de entity puur procentueel werkt.
          - switch.xxx  → turn_on (>50%) of turn_off (<=50%)

        Detectie-volgorde voor Watt-modus:
          1. rated_power_w is ingesteld in config -> altijd Watt, entity-max begrenst.
          2. rated_power_w niet ingesteld maar entity-max > 100 -> Watt (bijv. GoodWe 0-5000 W).
          3. Geen van beide -> procent (0-100).
        """
        target_pct = max(0.0, min(100.0, target_pct))
        entity_id  = ctrl.control_entity
        domain     = entity_id.split(".")[0]

        try:
            if domain == "number":
                # Lees entity-max voor begrenzing en fallback-detectie
                entity_max = 100.0
                state = self.hass.states.get(entity_id)
                if state:
                    try:
                        entity_max = float(state.attributes.get("max", 100))
                    except (TypeError, ValueError):
                        pass

                # Bepaal modus: Watt of procent
                if ctrl.rated_power_w:
                    # Configuratie zegt expliciet wat het nominaal vermogen is -> Watt
                    target_w = round(min(target_pct / 100.0 * ctrl.rated_power_w, entity_max), 0)
                    set_val  = target_w
                    _LOGGER.debug(
                        "MultiInverterMgr: '%s' Watt-modus (rated %.0fW) -> %.0fW",
                        ctrl.label or entity_id, ctrl.rated_power_w, target_w,
                    )
                elif entity_max > 100:
                    # Geen rated_power_w maar entity werkt in Watt -> gebruik entity_max als schaal
                    target_w = round(target_pct / 100.0 * entity_max, 0)
                    set_val  = target_w
                    _LOGGER.debug(
                        "MultiInverterMgr: '%s' Watt-modus (entity-max %.0fW) -> %.0fW",
                        ctrl.label or entity_id, entity_max, target_w,
                    )
                else:
                    # Procent-modus (0-100)
                    set_val = round(target_pct, 1)

                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": set_val},
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
        import time as _time
        now = _time.time()
        # Over-setpoint info per fase voor dashboard pre-warning
        over_sp: dict[str, dict] = {}
        for phase, since in self._over_setpoint_since.items():
            if since is not None:
                max_a = self._max_phase_a.get(phase, 25.0)
                elapsed = now - since
                remaining = max(0.0, PID_SAMPLE_TIME_S - elapsed)
                level = self._last_warn_level.get(phase, 0)
                over_sp[phase] = {
                    "elapsed_s":   round(elapsed, 1),
                    "remaining_s": round(remaining, 1),
                    "level":       level,  # 1=nominaal, 2=B-kar, 3=gG
                    "warn_bchar":  level >= 2,
                    "warn_gg":     level >= 3,
                    "max_a":       max_a,
                    "setpoint_a":  round(max_a * PID_SETPOINT_RATIO, 2),
                    "bchar_a":     round(max_a * B_CHAR_FACTOR, 2),
                    "gg_a":        round(max_a * GG_CHAR_FACTOR, 2),
                }
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
            "phase_probe_status": self._phase_prober.get_status() if self._phase_prober else {},
            "manual_dim": {
                eid: self._manual_dim_pct.get(eid)
                for eid in self._manual_dim_pct
            },
            "dimmer_enabled": dict(self._dimmer_enabled),
            "over_setpoint":  over_sp,
        }

    # ── Dashboard controls ────────────────────────────────────────────────────

    def set_manual_dim(self, entity_id: str, pct: float | None) -> None:
        """Set a temporary manual dim override for one inverter.

        pct=None  → clear override, resume automatic control
        pct=0-100 → force this output level for MANUAL_DIM_RESUME_DELAY_S seconds,
                    then automatically resume automatic control.
        """
        if entity_id not in self._manual_dim_pct:
            return

        # Cancel any existing resume timer
        cancel = self._manual_dim_timers.pop(entity_id, None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass

        self._manual_dim_pct[entity_id] = (
            max(0.0, min(100.0, float(pct))) if pct is not None else None
        )
        if pct is not None:
            import time as _time
            self._manual_dim_set_at[entity_id] = _time.time()
        else:
            self._manual_dim_set_at.pop(entity_id, None)
        _LOGGER.info(
            "MultiInverterMgr: handmatige dim '%s' → %s",
            entity_id, f"{pct:.0f}%" if pct is not None else "auto",
        )

        import asyncio
        if pct is not None:
            # Apply immediately so the slider feels responsive
            ctrl = next((c for c in self._controls if c.entity_id == entity_id), None)
            if ctrl:
                asyncio.ensure_future(self._set_output(ctrl, float(pct)))

            # Schedule auto-resume after delay
            def _resume_auto(_now=None):
                self._manual_dim_pct[entity_id] = None
                self._manual_dim_timers.pop(entity_id, None)
                _LOGGER.info(
                    "MultiInverterMgr: handmatige dim '%s' verlopen → automatisch beheer hervat",
                    entity_id,
                )

            if self.hass:
                self._manual_dim_timers[entity_id] = async_call_later(
                    self.hass, MANUAL_DIM_RESUME_DELAY_S, _resume_auto
                )

    def trigger_phase_probe(self, inverter_id: str | None = None) -> None:
        """
        Herstart de phase-probe voor één of alle omvormers.

        inverter_id=None  → reset alle sessies (herstart volledig leerproces)
        inverter_id=<eid> → reset alleen die omvormer
        """
        if not self._phase_prober:
            _LOGGER.warning("MultiInverterMgr: PhaseProber niet beschikbaar (geen dimmer-regelaars?)")
            return
        if inverter_id:
            self._phase_prober.reset_session(inverter_id)
            _LOGGER.info("MultiInverterMgr: phase-probe herstart voor '%s'", inverter_id)
        else:
            for ctrl in self._controls:
                self._phase_prober.reset_session(ctrl.entity_id)
            _LOGGER.info("MultiInverterMgr: phase-probe herstart voor alle omvormers")

    def set_dimmer_enabled(self, entity_id: str, enabled: bool) -> None:
        """Enable or disable the solar dimmer for one inverter at runtime."""
        if entity_id in self._dimmer_enabled:
            self._dimmer_enabled[entity_id] = enabled
            _LOGGER.info(
                "MultiInverterMgr: zonnedimmer '%s' → %s",
                entity_id, "aan" if enabled else "uit",
            )
            # When disabling, immediately restore to 100%
            if not enabled:
                ctrl = next((c for c in self._controls if c.entity_id == entity_id), None)
                if ctrl:
                    import asyncio
                    asyncio.ensure_future(self._set_output(ctrl, 100.0))
                self._current_pct[entity_id] = 100.0

    def get_dimmer_state(self, entity_id: str) -> dict:
        """Return current dim state for one inverter (for HA entity state)."""
        import time as _time
        manual_pct  = self._manual_dim_pct.get(entity_id)
        current_pct = self._current_pct.get(entity_id, 100.0)
        ctrl = next((c for c in self._controls if c.entity_id == entity_id), None)
        active_pct  = manual_pct if manual_pct is not None else current_pct

        # Compute setpoint in Watt or percent
        if ctrl and ctrl.rated_power_w:
            setpoint_str = f"{round(active_pct / 100.0 * ctrl.rated_power_w, 0):.0f} W"
        else:
            setpoint_str = f"{active_pct:.1f} %"

        # Resterende tijd handmatige override
        resume_in_s = None
        if manual_pct is not None:
            set_at = self._manual_dim_set_at.get(entity_id)
            if set_at:
                elapsed = _time.time() - set_at
                remaining = max(0, MANUAL_DIM_RESUME_DELAY_S - elapsed)
                resume_in_s = int(remaining)

        # Laatste beslissing voor duidelijke status
        last = self._last_decision.get(entity_id)
        action_labels = {
            "idle":           "✅ Vol vermogen — automatisch",
            "restore":        "🔼 Hersteld naar 100%",
            "dim_pid":        "📉 Dimmen — fase-overbelasting",
            "dim_full":       "⬇️ Volledig gedimd",
            "negative_price": "🔴 Gedimd — negatieve stroomprijs",
            "manual_override": f"🖐 Handmatig {active_pct:.0f}% — hervat over {resume_in_s//60 if resume_in_s else '?'} min",
        }
        status_label = action_labels.get(last.action, last.action) if last else "⏳ Wachten op eerste cyclus"

        return {
            "current_pct":    current_pct,
            "manual_pct":     manual_pct,
            "manual_active":  manual_pct is not None,
            "setpoint":       setpoint_str,
            "auto_resume_in": f"{resume_in_s}s" if resume_in_s else None,
            "dimmer_enabled": self._dimmer_enabled.get(entity_id, True),
            "status":         status_label,
            "last_action":    last.action if last else None,
            "last_reason":    last.reason if last else None,
        }

