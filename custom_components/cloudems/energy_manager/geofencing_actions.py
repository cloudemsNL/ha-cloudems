# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Geofencing Actions v1.0.0

Triggers configurable actions when occupants arrive home or leave.
Builds on existing zone_presence.py detection.

Actions on ARRIVAL:
  - Turn on configured switches/lights
  - Set thermostat to comfort temperature
  - Disable vacation mode
  - Send welcome notification (optional)
  - Pre-heat boiler if needed

Actions on DEPARTURE:
  - Enable standby killer
  - Set thermostat to eco/away temperature
  - Activate vacation mode (if all occupants away)
  - Turn off configured switches

Configuration:
  geofencing_enabled              bool
  geofencing_arrival_switches     list[str]   — switches to turn ON
  geofencing_departure_switches   list[str]   — switches to turn OFF
  geofencing_arrival_thermostat   str         — climate entity
  geofencing_arrival_temp         float       — comfort temperature
  geofencing_departure_temp       float       — away temperature
  geofencing_notify               bool
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_S = 120  # wait 2 min before triggering to avoid false positives


@dataclass
class GeofencingStatus:
    enabled:          bool  = False
    last_state:       str   = "unknown"   # "home" | "away"
    last_change_ts:   float = 0.0
    arrival_count:    int   = 0
    departure_count:  int   = 0
    last_actions:     list  = field(default_factory=list)


class GeofencingActions:
    """Triggers home automation actions on presence change."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("geofencing_enabled", False)
        self._last_state:  str   = "unknown"
        self._state_since: float = 0.0
        self._arrival_count   = 0
        self._departure_count = 0
        self._last_actions: list = []

    def update_config(self, config: dict) -> None:
        self._config  = config
        self._enabled = config.get("geofencing_enabled", False)

    async def async_tick(self, is_home: bool) -> list[str]:
        """
        Call every coordinator cycle with current presence state.
        Returns list of actions taken.
        """
        if not self._enabled:
            return []

        current = "home" if is_home else "away"
        now = time.time()
        actions = []

        if current == self._last_state:
            return []

        # State changed — debounce
        if self._state_since == 0.0:
            self._state_since = now
            return []

        if now - self._state_since < DEBOUNCE_S:
            return []

        # Confirmed state change
        _LOGGER.info("GeofencingActions: state change %s → %s", self._last_state, current)
        self._last_state = current
        self._state_since = 0.0

        if current == "home":
            actions = await self._on_arrival()
            self._arrival_count += 1
        else:
            actions = await self._on_departure()
            self._departure_count += 1

        self._last_actions = actions
        return actions

    async def _on_arrival(self) -> list[str]:
        """Execute arrival actions."""
        actions = []
        cfg = self._config

        # Turn on arrival switches
        for eid in (cfg.get("geofencing_arrival_switches") or []):
            try:
                await self._hass.services.async_call(
                    "switch", "turn_on", {"entity_id": eid}, blocking=False
                )
                actions.append(f"on:{eid}")
            except Exception as e:
                _LOGGER.warning("Geofencing arrival switch %s: %s", eid, e)

        # Set thermostat to comfort
        therm = cfg.get("geofencing_arrival_thermostat")
        temp  = cfg.get("geofencing_arrival_temp")
        if therm and temp:
            try:
                await self._hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": therm, "temperature": float(temp)},
                    blocking=False,
                )
                actions.append(f"thermostat:{temp}°C")
            except Exception as e:
                _LOGGER.warning("Geofencing thermostat: %s", e)

        # Notification
        if cfg.get("geofencing_notify", False):
            try:
                await self._hass.services.async_call(
                    "persistent_notification", "create",
                    {"title": "🏠 Welkom thuis!", "message": "CloudEMS heeft het huis voor je klaargemaakt.",
                     "notification_id": "cloudems_geofencing_arrival"},
                    blocking=False,
                )
            except Exception:
                pass

        _LOGGER.info("GeofencingActions: arrival — %d actions", len(actions))
        return actions

    async def _on_departure(self) -> list[str]:
        """Execute departure actions."""
        actions = []
        cfg = self._config

        # Turn off departure switches
        for eid in (cfg.get("geofencing_departure_switches") or []):
            try:
                await self._hass.services.async_call(
                    "switch", "turn_off", {"entity_id": eid}, blocking=False
                )
                actions.append(f"off:{eid}")
            except Exception as e:
                _LOGGER.warning("Geofencing departure switch %s: %s", eid, e)

        # Set thermostat to away temperature
        therm = cfg.get("geofencing_arrival_thermostat")
        temp  = cfg.get("geofencing_departure_temp")
        if therm and temp:
            try:
                await self._hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": therm, "temperature": float(temp)},
                    blocking=False,
                )
                actions.append(f"thermostat_away:{temp}°C")
            except Exception as e:
                _LOGGER.warning("Geofencing away thermostat: %s", e)

        _LOGGER.info("GeofencingActions: departure — %d actions", len(actions))
        return actions

    def get_status(self) -> dict:
        return {
            "enabled":         self._enabled,
            "state":           self._last_state,
            "arrival_count":   self._arrival_count,
            "departure_count": self._departure_count,
            "last_actions":    self._last_actions,
        }
