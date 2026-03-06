# -*- coding: utf-8 -*-
"""
CloudEMS Smart Boiler / Socket Controller — v1.4.1

Controls a power socket (e.g. warm water boiler, heat pump, dishwasher) based on:
  1. EPEX cheap hours   — turn on during cheapest N hours of day
  2. Negative price     — always on when exporting at negative price
  3. PV surplus         — turn on when solar surplus > threshold
  4. Export reduction   — if a phase is exporting (current flowing back) and the
                          boiler is on that phase, turn on to consume the export
                          and reduce reverse current

Multiple boilers can be configured, each with:
  - entity_id          : switch or outlet to control
  - phase              : L1 / L2 / L3 (for export-reduction logic)
  - power_w            : rated power of the load in Watts
  - min_on_minutes     : minimum runtime before switching off again
  - min_off_minutes    : minimum off time before switching on again
  - modes              : list of enabled control modes

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Control modes
MODE_CHEAP_HOURS    = "cheap_hours"
MODE_NEGATIVE_PRICE = "negative_price"
MODE_PV_SURPLUS     = "pv_surplus"
MODE_EXPORT_REDUCE  = "export_reduce"
MODE_HEAT_DEMAND    = "heat_demand"    # Turn on when outside temp < setpoint (HP/CV priority)
MODE_CONGESTION_OFF = "congestion_off" # Turn off during grid congestion events

DEFAULT_SURPLUS_THRESHOLD_W  = 300   # W — minimum PV surplus to trigger
DEFAULT_EXPORT_THRESHOLD_A   = 1.0   # A — minimum export current on phase to trigger
DEFAULT_HEAT_DEMAND_TEMP_C   = 5.0   # °C — below this outside temp, heat demand is active
DEFAULT_MIN_ON_MINUTES       = 10
DEFAULT_MIN_OFF_MINUTES      = 5


@dataclass
class BoilerDecision:
    """Result of one evaluation cycle for a boiler."""
    entity_id:   str
    label:       str
    action:      str    # "turn_on" | "turn_off" | "hold_on" | "hold_off"
    reason:      str
    current_state: bool  # True = on


@dataclass
class BoilerState:
    outside_temp_c:    Optional[float] = None   # updated by coordinator
    heat_demand_temp_c: float = 5.0             # trigger below this °C
    congestion_active:  bool  = False           # set by GridCongestionDetector
    """Runtime state per boiler."""
    entity_id:        str
    label:            str
    phase:            str   = "L1"
    power_w:          float = 1000.0
    min_on_s:         float = DEFAULT_MIN_ON_MINUTES * 60
    min_off_s:        float = DEFAULT_MIN_OFF_MINUTES * 60
    modes:            list  = field(default_factory=lambda: [
        MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE, MODE_PV_SURPLUS, MODE_EXPORT_REDUCE
    ])
    cheap_hours_rank: int   = 3   # in cheapest N hours

    # Runtime
    last_on_ts:  float = 0.0
    last_off_ts: float = 0.0
    forced_on:   bool  = False


class BoilerController:
    """
    Smart socket/boiler controller.

    Usage from coordinator:
        ctrl = BoilerController(hass, boiler_configs)
        await ctrl.async_setup()
        decisions = await ctrl.async_evaluate(
            price_info=...,
            solar_surplus_w=...,
            phase_currents=...,
            phase_max_currents=...,
        )
    """

    def __init__(self, hass: HomeAssistant, boiler_configs: list[dict]) -> None:
        self._hass    = hass
        self._boilers: list[BoilerState] = []
        for cfg in boiler_configs:
            self._boilers.append(BoilerState(
                entity_id        = cfg["entity_id"],
                label            = cfg.get("label", cfg["entity_id"]),
                phase            = cfg.get("phase", "L1"),
                power_w          = float(cfg.get("power_w", 1000.0)),
                min_on_s         = float(cfg.get("min_on_minutes",  DEFAULT_MIN_ON_MINUTES))  * 60,
                min_off_s        = float(cfg.get("min_off_minutes", DEFAULT_MIN_OFF_MINUTES)) * 60,
                modes            = cfg.get("modes", [
                    MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE,
                    MODE_PV_SURPLUS,  MODE_EXPORT_REDUCE,
                ]),
                cheap_hours_rank = int(cfg.get("cheap_hours_rank", 3)),
            ))
        _LOGGER.info("BoilerController: %d boilers configured", len(self._boilers))

    async def async_setup(self) -> None:
        pass  # Nothing to load for now

    async def async_evaluate(
        self,
        price_info:         dict,
        solar_surplus_w:    float = 0.0,
        phase_currents:     Optional[dict] = None,
        phase_max_currents: Optional[dict] = None,
        surplus_threshold_w:float = DEFAULT_SURPLUS_THRESHOLD_W,
        export_threshold_a: float = DEFAULT_EXPORT_THRESHOLD_A,
    ) -> list[BoilerDecision]:
        """Evaluate all boilers and switch as needed. Returns list of decisions."""
        decisions: list[BoilerDecision] = []
        phase_currents     = phase_currents     or {}
        phase_max_currents = phase_max_currents or {}
        now = time.time()

        for b in self._boilers:
            is_on    = self._is_on(b.entity_id)
            want_on  = False
            reason   = ""

            # ── Check each enabled mode ────────────────────────────────────────

            # 1. Negative price → always on
            if MODE_NEGATIVE_PRICE in b.modes:
                if price_info.get("is_negative", False):
                    want_on = True
                    reason  = f"Negatieve prijs: {price_info.get('current', 0):.4f} €/kWh"

            # 2. Cheap hours
            if not want_on and MODE_CHEAP_HOURS in b.modes:
                in_cheap = price_info.get(f"in_cheapest_{b.cheap_hours_rank}h", False)
                if in_cheap:
                    want_on = True
                    price   = price_info.get("current", 0)
                    reason  = f"Goedkoopste {b.cheap_hours_rank} uur (nu {price:.4f} €/kWh)"

            # 3. PV surplus
            if not want_on and MODE_PV_SURPLUS in b.modes:
                if solar_surplus_w >= surplus_threshold_w:
                    want_on = True
                    reason  = f"PV surplus {solar_surplus_w:.0f}W >= {surplus_threshold_w:.0f}W"

            # 4. Export reduction on phase
            if not want_on and MODE_EXPORT_REDUCE in b.modes:
                phase_current = phase_currents.get(b.phase, 0.0)
                # Negative current = export (power flowing back to grid)
                if phase_current < -export_threshold_a:
                    want_on = True
                    reason  = (
                        f"Export afschaven: {b.phase} exporteert {abs(phase_current):.2f}A "
                        f"— schakel {b.label} in om te verbruiken"
                    )

            # 5. Heat demand (heat pump / CV boiler priority)
            #    Turn on when outside temperature is below setpoint AND PV or cheap hours
            #    allow it. This ensures heat pumps run when heat is actually needed.
            if not want_on and MODE_HEAT_DEMAND in b.modes:
                outside_temp = b.outside_temp_c   # updated separately via update_outside_temp()
                setpoint     = float(getattr(b, "heat_demand_temp_c", DEFAULT_HEAT_DEMAND_TEMP_C))
                if outside_temp is not None and outside_temp < setpoint:
                    # Only activate if price is reasonable (< 2x current price avg) or PV available
                    price_ok = price_info.get("current", 0.5) < price_info.get("avg_today", 0.5) * 1.5
                    if price_ok or solar_surplus_w > 200:
                        want_on = True
                        reason  = (
                            f"Warmtevraag: buitentemp {outside_temp:.1f}°C < {setpoint:.1f}°C setpoint"
                        )

            # 6. Congestion override — force off regardless of other modes
            if MODE_CONGESTION_OFF in b.modes and getattr(b, "congestion_active", False):
                want_on = False
                reason  = "Netcongestie actief — belasting uitgesteld"

            # ── Apply min on/off timers ────────────────────────────────────────
            action = "hold_off"

            if want_on and not is_on:
                # Check min-off timer
                if now - b.last_off_ts >= b.min_off_s:
                    action = "turn_on"
                else:
                    remaining = b.min_off_s - (now - b.last_off_ts)
                    reason   += f" (min-uit timer: nog {remaining:.0f}s)"
                    action    = "hold_off"

            elif want_on and is_on:
                action = "hold_on"

            elif not want_on and is_on:
                # Check min-on timer
                if now - b.last_on_ts >= b.min_on_s:
                    action = "turn_off"
                    reason = "Geen reden meer om aan te zijn"
                else:
                    remaining = b.min_on_s - (now - b.last_on_ts)
                    action    = "hold_on"
                    reason    = f"Min-aan timer: nog {remaining:.0f}s"

            # ── Execute ────────────────────────────────────────────────────────
            if action == "turn_on":
                await self._switch(b.entity_id, True)
                b.last_on_ts = now
                _LOGGER.info("BoilerController: %s AAN — %s", b.label, reason)
            elif action == "turn_off":
                await self._switch(b.entity_id, False)
                b.last_off_ts = now
                _LOGGER.info("BoilerController: %s UIT — %s", b.label, reason)

            decisions.append(BoilerDecision(
                entity_id    = b.entity_id,
                label        = b.label,
                action       = action,
                reason       = reason,
                current_state= is_on,
            ))

        return decisions

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_on(self, entity_id: str) -> bool:
        state = self._hass.states.get(entity_id)
        return state is not None and state.state == "on"

    async def _switch(self, entity_id: str, on: bool) -> None:
        service = "turn_on" if on else "turn_off"
        domain  = entity_id.split(".")[0] if "." in entity_id else "switch"
        await self._hass.services.async_call(
            domain, service, {"entity_id": entity_id}, blocking=False
        )

    def update_outside_temp(self, temp_c: Optional[float]) -> None:
        """Update outside temperature for heat demand mode."""
        for b in self._boilers:
            b.outside_temp_c = temp_c

    def update_congestion_state(self, active: bool) -> None:
        """Inform boilers about grid congestion state."""
        for b in self._boilers:
            b.congestion_active = active

    def get_status(self) -> list[dict]:
        """Return status of all boilers for sensor attributes."""
        return [
            {
                "entity_id":  b.entity_id,
                "label":      b.label,
                "phase":      b.phase,
                "power_w":    b.power_w,
                "is_on":      self._is_on(b.entity_id),
                "modes":      b.modes,
            }
            for b in self._boilers
        ]
