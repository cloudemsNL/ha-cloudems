# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Wallbox Provider — v1.0.0

HA integratie: HACS wallbox (populair NL/BE)

Entity patronen:
  sensor.wallbox_*_charging_power   (W)
  sensor.wallbox_*_added_energy     (kWh, sessie)
  sensor.wallbox_*_status           (string)
  number.wallbox_*_max_charging_current (A)
  lock.wallbox_*                    (locked/unlocked)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_POWER_P   = ["charging_power", "wallbox_power"]
_ENERGY_P  = ["added_energy", "session_energy", "cumulative_energy"]
_STATUS_P  = ["status", "charging_status"]
_CURRENT_P = ["max_charging_current", "max_current"]


def _find_wb(hass, patterns, domain="sensor"):
    for st in hass.states.async_all(domain):
        s = st.entity_id.lower()
        if "wallbox" not in s: continue
        for p in patterns:
            if p in s: return st.entity_id
    return None


def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None


class WallboxProvider(BatteryProvider):
    """Wallbox EV lader provider."""

    PROVIDER_ID    = "wallbox"
    PROVIDER_LABEL = "Wallbox"
    PROVIDER_ICON  = "mdi:ev-station"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._power_eid   = config.get("wallbox_power_sensor")
        self._energy_eid  = config.get("wallbox_energy_sensor")
        self._current_eid = config.get("wallbox_current_entity")
        self._status_eid  = config.get("wallbox_status_sensor")
        self._last_state  = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        if not self._power_eid:   self._power_eid   = _find_wb(self._hass, _POWER_P)
        if not self._energy_eid:  self._energy_eid  = _find_wb(self._hass, _ENERGY_P)
        if not self._current_eid: self._current_eid = _find_wb(self._hass, _CURRENT_P, "number")
        if not self._status_eid:  self._status_eid  = _find_wb(self._hass, _STATUS_P)
        _LOGGER.info("WallboxProvider: detected=%s power=%s current_ctrl=%s",
                     self._detected, self._power_eid, self._current_eid)

    async def async_detect(self):
        if not self._power_eid: self._power_eid = _find_wb(self._hass, _POWER_P)
        return bool(self._power_eid)

    def read_state(self):
        power_w = _rf(self._hass, self._power_eid) or 0.0
        energy  = _rf(self._hass, self._energy_eid)
        status  = ""
        if self._status_eid:
            st = self._hass.states.get(self._status_eid)
            status = st.state if st else ""
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=self._power_eid is not None,
            raw={"power_w": power_w, "energy_kwh": energy, "status": status},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None) -> bool:
        if not self._current_eid: return False
        if power_w and power_w > 0:
            current_a = round(min(32, max(6, power_w / 230)), 1)
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": self._current_eid, "value": current_a},
                blocking=False)
            return True
        return False

    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="Wallbox lader gedetecteerd",
            description="Wallbox EV lader via HACS wallbox integratie.",
            icon="mdi:ev-station",
        )

    def get_power_w(self): return self._last_state.raw.get("power_w", 0.0)


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(WallboxProvider)
