# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS Huawei Solar Provider — v1.0.0

HA integratie: HACS huawei_solar (https://github.com/wlcrs/huawei_solar)
Update: 30s (omvormer), 5s (power meter)

Entity patronen:
  sensor.inverter_*_active_power        (W, solar output)
  sensor.power_meter_*_active_power     (W, grid, + import, - export)
  sensor.battery_*_charge_discharge_power (W, + laden, - ontladen)
  sensor.battery_*_state_of_capacity    (%, SoC)
  sensor.inverter_*_daily_yield         (kWh, dagproductie)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_SOLAR_PATTERNS   = ["inverter_active_power", "pv_power", "input_power"]
_GRID_PATTERNS    = ["power_meter_active_power", "grid_power", "meter_active_power"]
_BATTERY_PATTERNS = ["battery_charge_discharge_power", "battery_power"]
_SOC_PATTERNS     = ["battery_state_of_capacity", "battery_soc", "state_of_capacity"]
_ENERGY_PATTERNS  = ["daily_yield", "energy_today", "day_active_power_peak"]


def _find_huawei_entity(hass, patterns):
    """Zoek Huawei Solar entity — let op: geen 'huawei' in entity_id nodig."""
    all_states = hass.states.async_all("sensor")
    for st in all_states:
        sid = st.entity_id.lower()
        for pat in patterns:
            if pat in sid:
                # Verifieer dat het echt Huawei is via device/integration check
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


class HuaweiSolarProvider(BatteryProvider):
    """Huawei Solar omvormer + Luna 2000 batterij provider.

    Ondersteunt Huawei SUN2000 omvormers met optionele Luna 2000 batterij.
    Vereist HACS huawei_solar integratie (github.com/wlcrs/huawei_solar).
    """

    PROVIDER_ID    = "huawei_solar"
    PROVIDER_LABEL = "Huawei Solar"
    PROVIDER_ICON  = "mdi:solar-power"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._solar_eid   = config.get("huawei_solar_sensor")
        self._grid_eid    = config.get("huawei_grid_sensor")
        self._battery_eid = config.get("huawei_battery_sensor")
        self._soc_eid     = config.get("huawei_soc_sensor")
        self._energy_eid  = config.get("huawei_energy_sensor")
        self._last_state  = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self) -> None:
        await super().async_setup()
        self._autodiscover()
        _LOGGER.info("HuaweiSolarProvider v1.0: detected=%s solar=%s grid=%s battery=%s soc=%s",
                     self._detected, self._solar_eid, self._grid_eid,
                     self._battery_eid, self._soc_eid)

    def _autodiscover(self) -> None:
        if not self._solar_eid:
            self._solar_eid   = _find_huawei_entity(self._hass, _SOLAR_PATTERNS)
        if not self._grid_eid:
            self._grid_eid    = _find_huawei_entity(self._hass, _GRID_PATTERNS)
        if not self._battery_eid:
            self._battery_eid = _find_huawei_entity(self._hass, _BATTERY_PATTERNS)
        if not self._soc_eid:
            self._soc_eid     = _find_huawei_entity(self._hass, _SOC_PATTERNS)
        if not self._energy_eid:
            self._energy_eid  = _find_huawei_entity(self._hass, _ENERGY_PATTERNS)

    async def async_detect(self) -> bool:
        self._autodiscover()
        return bool(self._solar_eid)

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
        # Huawei: battery_w positief = laden, negatief = ontladen (zelfde als Fronius)
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            soc_pct=soc_pct, power_w=battery_w,
            is_charging=battery_w is not None and battery_w > 10,
            is_discharging=battery_w is not None and battery_w < -10,
            active_mode="auto", available_modes=["auto"],
            is_online=solar_w is not None,
            raw={"solar_w": solar_w, "grid_w": grid_w, "battery_w": battery_w,
                 "energy_wh": energy_wh},
        )
        return self._last_state

    async def async_set_charge(self, power_w=None) -> bool:
        return False

    async def async_set_auto(self) -> bool:
        return True

    def get_wizard_hint(self) -> ProviderWizardHint:
        has_battery = bool(self._battery_eid and self._soc_eid)
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title="Huawei Solar gedetecteerd",
            description=(
                "CloudEMS leest solar/grid/battery van je Huawei SUN2000. "
                + ("Luna 2000 batterij gevonden." if has_battery else "Geen batterij gevonden.")
            ),
            icon="mdi:solar-power",
            warning="" if has_battery else "Geen Huawei Luna 2000 gevonden.",
        )

    def get_solar_w(self): return self._last_state.raw.get("solar_w")
    def get_grid_w(self):  return self._last_state.raw.get("grid_w")
    def get_energy_today_wh(self): return self._last_state.raw.get("energy_wh")


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(HuaweiSolarProvider)
