# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Slaapstand Detector (v2.6).

Detecteert dat iedereen slaapt op basis van:
  • Geen beweging in de laatste N minuten (motion sensors)
  • Lichten zijn uit
  • Optioneel: person.* entities zijn thuis + geen activiteit

Bij detectie:
  • Stuurt een HA-notificatie (optioneel)
  • Schakelt geconfigureerde "overbodige" switches uit
  • Zet sensor.cloudems_slaapstand op 'aan'

Standaard uitgeschakeld — inschakelen via switch.cloudems_slaapstand_actief.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Standaard inactieve tijd voordat slaapstand actief wordt (minuten)
DEFAULT_INACTIVITY_MINUTES = 30
DEFAULT_MOTION_DOMAINS     = ("binary_sensor",)
MOTION_DEVICE_CLASSES      = ("motion", "occupancy", "presence")
LIGHT_DOMAIN               = "light"


class SleepDetector:
    """Detecteert slaapstand en schakelt overbodige verbruikers uit."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("sleep_detector_enabled", False)
        self._sleep_active   = False
        self._sleep_since: datetime | None = None
        self._last_activity: datetime      = datetime.now(timezone.utc)
        self._notified_this_session        = False

        # Switches die worden uitgeschakeld bij slaapstand
        self._cutoff_switches: list[str] = config.get("sleep_cutoff_switches", [])
        self._inactivity_min = int(config.get("sleep_inactivity_minutes", DEFAULT_INACTIVITY_MINUTES))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        if not value and self._sleep_active:
            self._sleep_active = False
            self._sleep_since  = None
            _LOGGER.info("CloudEMS slaapstand: uitgeschakeld, slaapstand gereset")

    @property
    def sleep_active(self) -> bool:
        return self._sleep_active

    def get_status(self) -> dict:
        return {
            "enabled":       self._enabled,
            "sleep_active":  self._sleep_active,
            "sleep_since":   self._sleep_since.isoformat() if self._sleep_since else None,
            "last_activity": self._last_activity.isoformat(),
            "inactivity_min": self._inactivity_min,
            "cutoff_switches": self._cutoff_switches,
        }

    async def async_update(self) -> dict:
        """Evalueer slaapstand. Aanroepen elke coordinator-cyclus."""
        if not self._enabled:
            return self.get_status()

        now = datetime.now(timezone.utc)
        motion_active = self._check_motion()
        lights_on     = self._check_lights()

        # Activiteit gedetecteerd → reset timer
        if motion_active or lights_on:
            self._last_activity = now
            if self._sleep_active:
                await self._wake_up()
            return self.get_status()

        # Geen activiteit — check inactiviteitsdrempel
        idle_minutes = (now - self._last_activity).total_seconds() / 60
        if idle_minutes >= self._inactivity_min and not self._sleep_active:
            await self._enter_sleep()
        elif idle_minutes < self._inactivity_min and self._sleep_active:
            # Zou niet moeten, maar als motion reset is
            await self._wake_up()

        return self.get_status()

    def _check_motion(self) -> bool:
        """Controleer of er een bewegingssensor actief is."""
        for state in self._hass.states.async_all("binary_sensor"):
            dc = state.attributes.get("device_class", "")
            if dc in MOTION_DEVICE_CLASSES and state.state == "on":
                return True
        return False

    def _check_lights(self) -> bool:
        """Controleer of er lichten aan zijn."""
        for state in self._hass.states.async_all("light"):
            if state.state == "on":
                return True
        return False

    async def _enter_sleep(self) -> None:
        """Activeer slaapstand."""
        self._sleep_active = True
        self._sleep_since  = datetime.now(timezone.utc)
        self._notified_this_session = False
        _LOGGER.info("CloudEMS: slaapstand geactiveerd")

        # Schakel geconfigureerde switches uit
        turned_off = []
        for switch_id in self._cutoff_switches:
            state = self._hass.states.get(switch_id)
            if state and state.state == "on":
                try:
                    domain = switch_id.split(".")[0]
                    await self._hass.services.async_call(
                        domain, "turn_off", {"entity_id": switch_id}, blocking=False
                    )
                    turned_off.append(switch_id)
                except Exception as err:
                    _LOGGER.warning("CloudEMS slaapstand: kon %s niet uitschakelen: %s", switch_id, err)

        # Stuur notificatie
        if not self._notified_this_session:
            msg = "😴 Slaapstand geactiveerd"
            if turned_off:
                names = [s.split(".")[-1].replace("_", " ") for s in turned_off]
                msg += f" — uitgeschakeld: {', '.join(names)}"
            try:
                from homeassistant.components.persistent_notification import async_create
                async_create(
                    self._hass,
                    message=msg,
                    title="CloudEMS Slaapstand",
                    notification_id="cloudems_sleep_mode",
                )
            except Exception:
                pass
            self._notified_this_session = True

    async def _wake_up(self) -> None:
        """Deactiveer slaapstand."""
        duration_min = 0
        if self._sleep_since:
            duration_min = int((datetime.now(timezone.utc) - self._sleep_since).total_seconds() / 60)
        self._sleep_active = False
        self._sleep_since  = None
        self._last_activity = datetime.now(timezone.utc)
        _LOGGER.info("CloudEMS: slaapstand beeindigd na %d minuten", duration_min)
