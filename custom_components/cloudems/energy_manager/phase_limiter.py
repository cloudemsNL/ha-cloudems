"""
CloudEMS Phase Current Limiter.

Monitors per-phase current (import & export) and throttles/disconnects
controllable loads: solar inverter, battery, EV charger.

Supports 1-phase and 3-phase installations.
Copyright © 2025 CloudEMS — https://cloudems.eu
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_MAX_CURRENT_IMPORT,
    CONF_MAX_CURRENT_EXPORT,
    CONF_SOLAR_INVERTER_SWITCH,
    CONF_EV_CHARGER_SWITCH,
    CONF_BATTERY_SWITCH,
    CONF_PHASE_COUNT,
    DEFAULT_MAX_CURRENT_IMPORT,
    DEFAULT_MAX_CURRENT_EXPORT,
    PHASES,
)

_LOGGER = logging.getLogger(__name__)

# Hysteresis: re-enable when current drops below limit - HYSTERESIS_A
HYSTERESIS_A = 1.5  # Ampere
# Minimum time (seconds) before re-enabling a throttled device
MIN_THROTTLE_TIME_S = 30


@dataclass
class PhaseLimit:
    phase: str
    max_import_a: float
    max_export_a: float
    current_a: float = 0.0
    throttled: bool = False
    last_throttle_ts: float = 0.0


class PhaseLimiter:
    """Per-phase import/export current limiter with device control."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = {**entry.data, **entry.options}

        self.limits: dict[str, PhaseLimit] = {}
        self._phase_count = int(self.config.get(CONF_PHASE_COUNT, 3))

    async def async_setup(self) -> None:
        """Initialize per-phase limits from config."""
        from ..const import (
            CONF_MAX_CURRENT_L1, CONF_MAX_CURRENT_L2, CONF_MAX_CURRENT_L3,
        )

        default_import = float(self.config.get(CONF_MAX_CURRENT_IMPORT, DEFAULT_MAX_CURRENT_IMPORT))
        default_export = float(self.config.get(CONF_MAX_CURRENT_EXPORT, DEFAULT_MAX_CURRENT_EXPORT))

        # Per-phase import limits — fall back to the single value if not set
        per_phase_import = {
            "L1": float(self.config.get(CONF_MAX_CURRENT_L1, default_import) or default_import),
            "L2": float(self.config.get(CONF_MAX_CURRENT_L2, default_import) or default_import),
            "L3": float(self.config.get(CONF_MAX_CURRENT_L3, default_import) or default_import),
        }

        phases = PHASES[:self._phase_count]
        for phase in phases:
            self.limits[phase] = PhaseLimit(
                phase=phase,
                max_import_a=per_phase_import[phase],
                max_export_a=default_export,
            )

        _LOGGER.info(
            "PhaseLimiter ready: %d phase(s) — limits: %s",
            self._phase_count,
            {p: f"{lim.max_import_a:.1f}A" for p, lim in self.limits.items()},
        )

    async def async_check_and_limit(self) -> None:
        """Check current readings and throttle if needed."""
        import time

        phase_currents = self.coordinator.phase_currents

        for phase, limit in self.limits.items():
            current = phase_currents.get(phase, 0.0)
            limit.current_a = current
            now = time.time()

            # IMPORT over-limit
            if current > limit.max_import_a:
                if not limit.throttled:
                    _LOGGER.warning(
                        "Phase %s import OVER LIMIT: %.1fA > %.1fA — throttling",
                        phase, current, limit.max_import_a,
                    )
                    await self._throttle_loads(phase, direction="import")
                    limit.throttled = True
                    limit.last_throttle_ts = now

            # EXPORT over-limit (negative current = export on some sensors)
            elif current < -limit.max_export_a:
                if not limit.throttled:
                    _LOGGER.warning(
                        "Phase %s export OVER LIMIT: %.1fA > %.1fA — throttling",
                        phase, abs(current), limit.max_export_a,
                    )
                    await self._throttle_loads(phase, direction="export")
                    limit.throttled = True
                    limit.last_throttle_ts = now

            # Within limits + hysteresis → re-enable
            elif (
                limit.throttled
                and abs(current) < (limit.max_import_a - HYSTERESIS_A)
                and (now - limit.last_throttle_ts) > MIN_THROTTLE_TIME_S
            ):
                _LOGGER.info(
                    "Phase %s current normalised (%.1fA) — re-enabling loads", phase, current
                )
                await self._restore_loads(phase)
                limit.throttled = False

    async def _throttle_loads(self, phase: str, direction: str) -> None:
        """Throttle controllable loads in priority order."""
        # Priority: EV charger first, then battery, then solar inverter
        if direction == "import":
            await self._control_entity(CONF_EV_CHARGER_SWITCH, "turn_off")
            await self._control_entity(CONF_BATTERY_SWITCH, "turn_off")
        elif direction == "export":
            await self._control_entity(CONF_SOLAR_INVERTER_SWITCH, "turn_off")
            await self._control_entity(CONF_BATTERY_SWITCH, "turn_off")

    async def _restore_loads(self, phase: str) -> None:
        """Re-enable loads after over-limit condition resolved."""
        await self._control_entity(CONF_BATTERY_SWITCH, "turn_on")
        await self._control_entity(CONF_EV_CHARGER_SWITCH, "turn_on")
        await self._control_entity(CONF_SOLAR_INVERTER_SWITCH, "turn_on")

    async def _control_entity(self, config_key: str, service: str) -> None:
        """Call HA service on a configured entity."""
        entity_id = self.config.get(config_key)
        if not entity_id:
            return
        domain = entity_id.split(".")[0]
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id}, blocking=False
            )
            _LOGGER.debug("PhaseLimiter: %s → %s", entity_id, service)
        except Exception as err:
            _LOGGER.warning("PhaseLimiter control failed (%s): %s", entity_id, err)

    async def set_limit(self, phase: str, limit_amps: float, direction: str) -> None:
        """Dynamically update current limit via service call."""
        targets = PHASES[:self._phase_count] if phase == "all" else [phase.upper()]
        for p in targets:
            if p in self.limits:
                if direction in ("import", "both"):
                    self.limits[p].max_import_a = limit_amps
                if direction in ("export", "both"):
                    self.limits[p].max_export_a = limit_amps
                _LOGGER.info(
                    "Phase limit updated: %s %s → %.1fA", p, direction, limit_amps
                )

    def get_status(self) -> dict[str, Any]:
        """Return current limiter status for sensors."""
        return {
            phase: {
                "current_a": lim.current_a,
                "max_import_a": lim.max_import_a,
                "max_export_a": lim.max_export_a,
                "throttled": lim.throttled,
                "utilisation_pct": (
                    round(abs(lim.current_a) / lim.max_import_a * 100, 1)
                    if lim.max_import_a
                    else 0.0
                ),
            }
            for phase, lim in self.limits.items()
        }
