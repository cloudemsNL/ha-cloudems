# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Sleep Group Switch v1.0.0

When sleep mode is detected, turns off a configured group of non-essential
devices and optionally activates security mode (arm alarm).

Builds on existing sleep_detector.py — listens for sleep_active flag.

Off on sleep:
  - Configured switch group (TV, media, lights, etc.)
  - Optional: thermostat setback

Restore on wake:
  - Restore switches that were automatically turned off
  - Restore thermostat to comfort temperature

Configuration:
  sleep_switch_enabled       bool
  sleep_switch_entities      list[str]
  sleep_thermostat_entity    str
  sleep_thermostat_setpoint  float      — setback temperature (default 17°C)
  sleep_restore_on_wake      bool
"""
from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class SleepGroupSwitch:
    """Cuts power to non-essential devices when sleep is detected."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("sleep_switch_enabled", False)
        self._was_sleeping = False
        self._cut_ts: float = 0.0
        self._restored_entities: list = []

    def update_config(self, config: dict) -> None:
        self._config  = config
        self._enabled = config.get("sleep_switch_enabled", False)

    async def async_tick(self, is_sleeping: bool) -> list[str]:
        """Call every coordinator cycle."""
        if not self._enabled:
            return []

        actions = []

        if is_sleeping and not self._was_sleeping:
            # Just fell asleep
            actions = await self._on_sleep()
            self._was_sleeping = True
            self._cut_ts = time.time()

        elif not is_sleeping and self._was_sleeping:
            # Just woke up
            actions = await self._on_wake()
            self._was_sleeping = False

        return actions

    async def _on_sleep(self) -> list[str]:
        """Turn off configured entities for sleep."""
        cfg = self._config
        actions = []
        entities = cfg.get("sleep_switch_entities") or []
        self._restored_entities = []

        for eid in entities:
            state = self._hass.states.get(eid)
            if state and state.state == "on":
                try:
                    await self._hass.services.async_call(
                        "switch", "turn_off", {"entity_id": eid}, blocking=False
                    )
                    self._restored_entities.append(eid)  # remember for wake
                    actions.append(f"sleep_off:{eid}")
                except Exception as e:
                    _LOGGER.warning("SleepGroupSwitch off %s: %s", eid, e)

        # Thermostat setback
        therm   = cfg.get("sleep_thermostat_entity")
        setback = float(cfg.get("sleep_thermostat_setpoint", 17.0))
        if therm:
            try:
                await self._hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": therm, "temperature": setback},
                    blocking=False,
                )
                actions.append(f"thermostat_setback:{setback}°C")
            except Exception as e:
                _LOGGER.warning("SleepGroupSwitch thermostat: %s", e)

        _LOGGER.info("SleepGroupSwitch: sleep — %d devices off", len(self._restored_entities))
        return actions

    async def _on_wake(self) -> list[str]:
        """Restore entities after wake."""
        cfg = self._config
        actions = []

        if not cfg.get("sleep_restore_on_wake", True):
            return []

        for eid in self._restored_entities:
            try:
                await self._hass.services.async_call(
                    "switch", "turn_on", {"entity_id": eid}, blocking=False
                )
                actions.append(f"wake_on:{eid}")
            except Exception as e:
                _LOGGER.warning("SleepGroupSwitch restore %s: %s", eid, e)

        self._restored_entities = []
        _LOGGER.info("SleepGroupSwitch: wake — restored %d devices", len(actions))
        return actions

    def get_status(self) -> dict:
        return {
            "enabled":       self._enabled,
            "is_sleeping":   self._was_sleeping,
            "cut_ts":        self._cut_ts,
            "auto_cut_count":len(self._restored_entities),
        }
