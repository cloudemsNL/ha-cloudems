# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS SMA Solar Provider — v1.0.0

HA integratie: homeassistant.components.sma (standaard, geen HACS)
Update: 30s via WebConnect API

Entity patronen:
  sensor.sma_*_pv_power / sma_*_total_yield  (W / kWh)
  sensor.sma_*_grid_power                    (W, + import, - export)
  sensor.sma_*_battery_power                 (W)
  sensor.sma_*_battery_soc                   (%)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_SOLAR_PATTERNS   = ["pv_power", "total_yield", "sma_power", "ac_power"]
_GRID_PATTERNS    = ["grid_power", "grid_feed_in", "metering_power"]
_BATTERY_PATTERNS = ["battery_power", "bat_power"]
_SOC_PATTERNS     = ["battery_soc", "bat_soc", "state_of_charge"]
_ENERGY_PATTERNS  = ["energy_today", "daily_yield", "today_yield"]


def _find_sma_entity(hass, patterns):
    for st in hass.states.async_all("sensor"):
        sid = st.entity_id.lower()
        if "sma" not in sid:
            continue
        for pat in patterns:
            if pat in sid:
                return st.entity_id
    return None


def _read_float(hass, entity_id):
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if not st or st.state in ("unavailable", "unknown", ""):
        return None
    try:
        return float(st.state)
    except (ValueError, TypeError):
        return None


class SMAProvider(BatteryProvider):
    """SMA omvormer provider — leest solar/grid/battery via HA SMA integratie."""

    PROVIDER_ID    = "sma"
    PROVIDER_LABEL = "SMA Solar"
    PROVIDER_ICON  = "mdi:solar-power"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._solar_eid    = config.get("sma_solar_sensor")
        self._grid_eid     = config.get("sma_grid_sensor")
        self._battery_eid  = config.get("sma_battery_sensor")
        self._soc_eid      = config.get("sma_soc_sensor")
        self._energy_eid   = config.get("sma_energy_sensor")
        self._last_state   = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self) -> None:
        await super().async_setup()
        self._autodiscover()
        _LOGGER.info("SMAProvider v1.0: detected=%s solar=%s grid=%s battery=%s",
                     self._detected, self._solar_eid, self._grid_eid, self._battery_eid)

    def _autodiscover(self) -> None:
        if not self._solar_eid:
            self._solar_eid   = _find_sma_entity(self._hass, _SOLAR_PATTERNS)
        if not self._grid_eid:
            self._grid_eid    = _find_sma_entity(self._hass, _GRID_PATTERNS)
        if not self._battery_eid:
            self._battery_eid = _find_sma_entity(self._hass, _BATTERY_PATTERNS)
        if not self._soc_eid:
            self._soc_eid     = _find_sma_entity(self._hass, _SOC_PATTERNS)
        if not self._energy_eid:
            self._energy_eid  = _find_sma_entity(self._hass, _ENERGY_PATTERNS)

    async def async_detect(self) -> bool:
        self._autodiscover()
        return bool(self._solar_eid or self._grid_eid)

    def read_state(self) -> BatteryProviderState:
        solar_w   = _read_float(self._hass, self._solar_eid)
        grid_w    = _read_float(self._hass, self._grid_eid)
        battery_w = _read_float(self._hass, self._battery_eid)
        soc_pct   = _read_float(self._hass, self._soc_eid)
        energy_wh = None
        if self._energy_eid:
            ev = _read_float(self._hass, self._energy_eid)
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
            is_online=solar_w is not None or grid_w is not None,
            raw={"solar_w": solar_w, "grid_w": grid_w, "battery_w": battery_w,
                 "energy_wh": energy_wh},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None) -> bool:
        return False

    async def async_set_auto(self) -> bool:
        return True

    def get_wizard_hint(self) -> ProviderWizardHint:
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="SMA omvormer gedetecteerd",
            description="CloudEMS leest solar/grid/battery van je SMA via WebConnect.",
            icon="mdi:solar-power",
        )

    def get_solar_w(self): return self._last_state.raw.get("solar_w")
    def get_grid_w(self):  return self._last_state.raw.get("grid_w")
    def get_energy_today_wh(self): return self._last_state.raw.get("energy_wh")


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(SMAProvider)
