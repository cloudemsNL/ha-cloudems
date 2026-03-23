# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Alpha ESS Provider — v1.0.0
HA integratie: HACS alpha_ess (populair NL alternatief)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)
_SOLAR_P  = ["alpha_ess_ppv", "alpha_ess_solar", "alpha_ess_pv_power"]
_GRID_P   = ["alpha_ess_pgrid", "alpha_ess_grid_power"]
_BAT_P    = ["alpha_ess_pbat", "alpha_ess_battery_power"]
_SOC_P    = ["alpha_ess_soc", "alpha_ess_battery_soc"]
_ENERGY_P = ["alpha_ess_pv_today", "alpha_ess_daily_pv"]

def _find(hass, patterns):
    for st in hass.states.async_all("sensor"):
        s = st.entity_id.lower()
        if "alpha" not in s and "alpha_ess" not in s: continue
        for p in patterns:
            if p in s: return st.entity_id
    return None

def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None

class AlphaESSProvider(BatteryProvider):
    PROVIDER_ID    = "alpha_ess"
    PROVIDER_LABEL = "Alpha ESS"
    PROVIDER_ICON  = "mdi:battery-charging"

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._solar_eid   = config.get("alpha_ess_solar_sensor")
        self._grid_eid    = config.get("alpha_ess_grid_sensor")
        self._battery_eid = config.get("alpha_ess_battery_sensor")
        self._soc_eid     = config.get("alpha_ess_soc_sensor")
        self._energy_eid  = config.get("alpha_ess_energy_sensor")
        self._last_state  = BatteryProviderState(provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        if not self._solar_eid:   self._solar_eid   = _find(self._hass, _SOLAR_P)
        if not self._grid_eid:    self._grid_eid    = _find(self._hass, _GRID_P)
        if not self._battery_eid: self._battery_eid = _find(self._hass, _BAT_P)
        if not self._soc_eid:     self._soc_eid     = _find(self._hass, _SOC_P)
        if not self._energy_eid:  self._energy_eid  = _find(self._hass, _ENERGY_P)
        _LOGGER.info("AlphaESSProvider: detected=%s solar=%s grid=%s battery=%s",
                     self._detected, self._solar_eid, self._grid_eid, self._battery_eid)

    async def async_detect(self):
        if not self._solar_eid: self._solar_eid = _find(self._hass, _SOLAR_P)
        return bool(self._solar_eid or self._battery_eid)

    def read_state(self):
        solar_w   = _rf(self._hass, self._solar_eid)
        grid_w    = _rf(self._hass, self._grid_eid)
        battery_w = _rf(self._hass, self._battery_eid)
        soc_pct   = _rf(self._hass, self._soc_eid)
        energy_wh = None
        if self._energy_eid:
            ev = _rf(self._hass, self._energy_eid)
            if ev is not None:
                st = self._hass.states.get(self._energy_eid)
                unit = (st.attributes.get("unit_of_measurement") or "").lower() if st else ""
                energy_wh = ev * 1000 if "kwh" in unit else ev
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            soc_pct=soc_pct, power_w=battery_w,
            is_charging=battery_w is not None and battery_w > 10,
            is_discharging=battery_w is not None and battery_w < -10,
            active_mode="auto", available_modes=["auto"],
            is_online=solar_w is not None or battery_w is not None,
            raw={"solar_w": solar_w, "grid_w": grid_w, "battery_w": battery_w, "energy_wh": energy_wh},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None): return False
    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="Alpha ESS gedetecteerd",
            description="Alpha ESS omvormer/batterij via HACS alpha_ess integratie.",
            icon="mdi:battery-charging",
        )

    def get_solar_w(self): return self._last_state.raw.get("solar_w")
    def get_grid_w(self):  return self._last_state.raw.get("grid_w")
    def get_energy_today_wh(self): return self._last_state.raw.get("energy_wh")

from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(AlphaESSProvider)
