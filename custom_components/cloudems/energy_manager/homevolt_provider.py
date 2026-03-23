# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Homevolt Battery Provider — v1.0.0
HA integratie: homeassistant.components.homevolt (standaard HA 2026.3)
Lokaal, geen cloud vereist.
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)
_POWER_P  = ["homevolt_power", "homevolt_battery_power"]
_SOC_P    = ["homevolt_state_of_charge", "homevolt_soc"]
_ENERGY_P = ["homevolt_energy", "homevolt_today"]

def _find(hass, patterns, domain="sensor"):
    for st in hass.states.async_all(domain):
        s = st.entity_id.lower()
        if "homevolt" not in s: continue
        for p in patterns:
            if p in s: return st.entity_id
    return None

def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None

class HomevoltProvider(BatteryProvider):
    PROVIDER_ID    = "homevolt"
    PROVIDER_LABEL = "Homevolt"
    PROVIDER_ICON  = "mdi:home-battery"

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._power_eid  = config.get("homevolt_power_sensor")
        self._soc_eid    = config.get("homevolt_soc_sensor")
        self._energy_eid = config.get("homevolt_energy_sensor")
        self._last_state = BatteryProviderState(provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        if not self._power_eid:  self._power_eid  = _find(self._hass, _POWER_P)
        if not self._soc_eid:    self._soc_eid    = _find(self._hass, _SOC_P)
        if not self._energy_eid: self._energy_eid = _find(self._hass, _ENERGY_P)
        _LOGGER.info("HomevoltProvider: detected=%s power=%s soc=%s", self._detected, self._power_eid, self._soc_eid)

    async def async_detect(self):
        if not self._power_eid: self._power_eid = _find(self._hass, _POWER_P)
        return bool(self._power_eid)

    def read_state(self):
        pw  = _rf(self._hass, self._power_eid)
        soc = _rf(self._hass, self._soc_eid)
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            soc_pct=soc, power_w=pw,
            is_charging=pw is not None and pw > 10,
            is_discharging=pw is not None and pw < -10,
            active_mode="auto", available_modes=["auto"],
            is_online=pw is not None,
            raw={"power_w": pw, "soc_pct": soc},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None): return False
    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="Homevolt batterij gedetecteerd",
            description="Lokale Homevolt batterij — geen cloud vereist (nieuw in HA 2026.3).",
            icon="mdi:home-battery",
        )

from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(HomevoltProvider)
