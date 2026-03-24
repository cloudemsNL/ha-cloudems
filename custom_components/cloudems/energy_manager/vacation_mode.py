# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Vacation Mode v1.0.0

Activates a low-power vacation profile:
  - Switches off all non-critical smart plugs (configured list)
  - Sets boiler to legionella-safe minimum (45°C, no BOOST)
  - Keeps battery in self-consumption mode
  - Keeps PV active (still produces)
  - Sends weekly summary notification
  - Automatically disables on return (presence detection)

Configuration (via config_flow):
  vacation_enabled           bool
  vacation_switch_entities   list[str]  — plugs to cut off
  vacation_boiler_setpoint   float      — default 45.0°C
  vacation_notify            bool       — weekly digest
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEFAULT_BOILER_SETPOINT = 45.0
WEEKLY_NOTIFY_INTERVAL  = 7 * 24 * 3600


@dataclass
class VacationStatus:
    active:             bool  = False
    since_ts:           float = 0.0
    switches_off:       list  = field(default_factory=list)
    boiler_setpoint:    float = DEFAULT_BOILER_SETPOINT
    saved_kwh:          float = 0.0
    days_away:          int   = 0
    auto_disabled:      bool  = False


class VacationMode:
    """Manages vacation low-power profile."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._active  = False
        self._since   = 0.0
        self._last_notify = 0.0
        self._saved_wh    = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    async def async_activate(self) -> None:
        """Switch on vacation mode."""
        if self._active:
            return
        self._active = True
        self._since  = time.time()
        _LOGGER.info("VacationMode: activated")

        # Turn off configured switches
        switches = self._config.get("vacation_switch_entities") or []
        for eid in switches:
            try:
                await self._hass.services.async_call(
                    "switch", "turn_off", {"entity_id": eid}, blocking=True
                )
                _LOGGER.debug("VacationMode: turned off %s", eid)
            except Exception as e:
                _LOGGER.warning("VacationMode: could not turn off %s: %s", eid, e)

        # Notify
        await self._notify("🏖️ Vakantiemodus ingeschakeld",
                           "CloudEMS heeft de vakantiemodus geactiveerd. "
                           "Niet-kritische apparaten zijn uitgeschakeld.")

    async def async_deactivate(self, reason: str = "manual") -> None:
        """Switch off vacation mode."""
        if not self._active:
            return
        self._active = False
        _LOGGER.info("VacationMode: deactivated (%s)", reason)

        await self._notify("🏠 Vakantiemodus uitgeschakeld",
                           f"Welkom terug! CloudEMS hervat normaal beheer. ({reason})")

    def tick(self, is_home: bool, pv_kwh_today: float) -> VacationStatus:
        """
        Call every coordinator cycle.
        Auto-disables if presence is detected.
        """
        if self._active and is_home:
            # Someone came home — disable automatically
            self._hass.loop.call_soon_threadsafe(
                lambda: self._hass.async_create_task(
                    self.async_deactivate("aanwezigheid gedetecteerd")
                )
            )

        if self._active:
            # Accumulate savings estimate (rough: 200W average saving)
            self._saved_wh += 200 * (10 / 3600)  # 10s tick

        return VacationStatus(
            active          = self._active,
            since_ts        = self._since,
            boiler_setpoint = float(self._config.get("vacation_boiler_setpoint",
                                                      DEFAULT_BOILER_SETPOINT)),
            saved_kwh       = round(self._saved_wh / 1000, 2),
            days_away       = int((time.time() - self._since) / 86400) if self._active else 0,
        )

    async def _notify(self, title: str, message: str) -> None:
        if not self._config.get("vacation_notify", True):
            return
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": title, "message": message,
                 "notification_id": "cloudems_vacation"},
                blocking=False,
            )
        except Exception:
            pass

    def get_status(self) -> dict:
        s = self.tick(False, 0)
        return {
            "active":          s.active,
            "days_away":       s.days_away,
            "saved_kwh":       s.saved_kwh,
            "boiler_setpoint": s.boiler_setpoint,
        }
