# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS NRGkick Gen2 Provider — v1.0.0

HA integratie: homeassistant.components.nrgkick (standaard HA 2026.2)
Lokaal, 3-fase data, geen cloud vereist.

Entity patronen:
  sensor.nrgkick_*_charging_power  (W)
  sensor.nrgkick_*_session_energy  (kWh)
  sensor.nrgkick_*_phase_*_current (A, per fase)
  binary_sensor.nrgkick_*_charging (aan/uit)
  number.nrgkick_*_max_current     (A, max laadstroom)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_POWER_P   = ["charging_power", "nrgkick_power"]
_ENERGY_P  = ["session_energy", "energy_charged"]
_CURRENT_P = ["max_current", "charge_current"]
_STATUS_P  = ["charging"]


def _find_nrgkick(hass, patterns, domain="sensor"):
    for st in hass.states.async_all(domain):
        s = st.entity_id.lower()
        if "nrgkick" not in s: continue
        for p in patterns:
            if p in s: return st.entity_id
    return None


def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None


class NRGkickProvider(BatteryProvider):
    """NRGkick Gen2 EV lader provider — directe lader zonder EVCC."""

    PROVIDER_ID    = "nrgkick"
    PROVIDER_LABEL = "NRGkick"
    PROVIDER_ICON  = "mdi:ev-plug-type2"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._power_eid   = config.get("nrgkick_power_sensor")
        self._energy_eid  = config.get("nrgkick_energy_sensor")
        self._current_eid = config.get("nrgkick_current_entity")
        self._status_eid  = config.get("nrgkick_status_sensor")
        # 3-fase stroom sensoren
        self._l1_eid = config.get("nrgkick_l1_sensor")
        self._l2_eid = config.get("nrgkick_l2_sensor")
        self._l3_eid = config.get("nrgkick_l3_sensor")
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        if not self._power_eid:   self._power_eid   = _find_nrgkick(self._hass, _POWER_P)
        if not self._energy_eid:  self._energy_eid  = _find_nrgkick(self._hass, _ENERGY_P)
        if not self._current_eid: self._current_eid = _find_nrgkick(self._hass, _CURRENT_P, "number")
        if not self._status_eid:  self._status_eid  = _find_nrgkick(self._hass, _STATUS_P, "binary_sensor")
        # 3-fase stroom
        for st in self._hass.states.async_all("sensor"):
            s = st.entity_id.lower()
            if "nrgkick" not in s: continue
            if "phase_1_current" in s or "l1_current" in s: self._l1_eid = st.entity_id
            elif "phase_2_current" in s or "l2_current" in s: self._l2_eid = st.entity_id
            elif "phase_3_current" in s or "l3_current" in s: self._l3_eid = st.entity_id
        _LOGGER.info("NRGkickProvider: detected=%s power=%s 3phase=%s",
                     self._detected, self._power_eid,
                     bool(self._l1_eid and self._l2_eid and self._l3_eid))

    async def async_detect(self):
        if not self._power_eid: self._power_eid = _find_nrgkick(self._hass, _POWER_P)
        return bool(self._power_eid)

    def read_state(self):
        power_w  = _rf(self._hass, self._power_eid) or 0.0
        energy   = _rf(self._hass, self._energy_eid)
        l1 = _rf(self._hass, self._l1_eid)
        l2 = _rf(self._hass, self._l2_eid)
        l3 = _rf(self._hass, self._l3_eid)
        charging = False
        if self._status_eid:
            st = self._hass.states.get(self._status_eid)
            charging = st is not None and st.state == "on"
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=self._power_eid is not None,
            raw={"power_w": power_w, "energy_kwh": energy, "charging": charging,
                 "l1_a": l1, "l2_a": l2, "l3_a": l3},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None) -> bool:
        if not self._current_eid: return False
        phases = sum(1 for v in [_rf(self._hass, self._l1_eid),
                                  _rf(self._hass, self._l2_eid),
                                  _rf(self._hass, self._l3_eid)] if v)
        phases = max(1, phases)
        if power_w and power_w > 0:
            current_a = round(min(32, max(6, power_w / (phases * 230))), 1)
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": self._current_eid, "value": current_a},
                blocking=False)
            _LOGGER.info("NRGkickProvider: laadstroom → %.1f A (%d fasen)", current_a, phases)
            return True
        return False

    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        has3phase = bool(self._l1_eid and self._l2_eid and self._l3_eid)
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="NRGkick Gen2 gedetecteerd",
            description=(
                "NRGkick EV lader gevonden. "
                + ("3-fase stroom data beschikbaar." if has3phase else "")
            ),
            icon="mdi:ev-plug-type2",
        )

    def get_power_w(self): return self._last_state.raw.get("power_w", 0.0)


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(NRGkickProvider)
