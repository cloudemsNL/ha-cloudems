# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Huawei Luna 2000 Battery Provider v1.0.0

Supports Huawei Luna 2000 via the huawei_solar HACS integratie.

Entity patronen (huawei_solar):
  sensor.battery_state_of_capacity          → SOC (%)
  sensor.battery_charge_discharge_power     → Vermogen (W)
  sensor.battery_bus_voltage                → Spanning
  select.storage_working_mode_settings      → How it workssmodus
  number.storage_maximum_charging_power     → Max laadvermogen
  number.storage_maximum_discharging_power  → Max ontlaadvermogen
  switch.storage_forcible_charge_discharge  → Forceer laden/ontladen
"""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant

from .battery_provider import BatteryProvider, BatteryProviderState, BatteryProviderRegistry, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_HUAWEI_SOC_ENTITIES   = (
    "sensor.battery_state_of_capacity",
    "sensor.huawei_battery_soc",
    "sensor.luna2000_soc",
)
_HUAWEI_POWER_ENTITIES = (
    "sensor.battery_charge_discharge_power",
    "sensor.huawei_battery_power",
    "sensor.luna2000_power",
)
_HUAWEI_MODE_SELECT    = (
    "select.storage_working_mode_settings",
    "select.huawei_storage_mode",
)

# Huawei Luna werkingsmodi
MODE_MAXIMIZE_SELF_CONSUMPTION = "Maximise Self Consumption"
MODE_FULLY_FED_TO_GRID         = "Fully Fed To Grid"
MODE_TIME_OF_USE               = "Time Of Use (LG)"
MODE_FIXED_CHARGE              = "Fixed charge and discharge"


class HuaweiLunaProvider(BatteryProvider):
    """Huawei Luna 2000 batterij-provider via huawei_solar HACS."""

    PROVIDER_ID    = "huawei_luna"
    PROVIDER_LABEL = "Huawei Luna 2000"
    PROVIDER_ICON  = "mdi:battery-charging-80"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._soc_entity:   Optional[str] = None
        self._power_entity: Optional[str] = None
        self._mode_entity:  Optional[str] = None
        self._max_charge_entity:    Optional[str] = None
        self._max_discharge_entity: Optional[str] = None

    async def async_detect(self) -> bool:
        """Detect Huawei Luna entities."""
        # Zoek bekende entity IDs
        for eid in _HUAWEI_SOC_ENTITIES:
            if self._hass.states.get(eid):
                self._soc_entity = eid
                break

        for eid in _HUAWEI_POWER_ENTITIES:
            if self._hass.states.get(eid):
                self._power_entity = eid
                break

        for eid in _HUAWEI_MODE_SELECT:
            if self._hass.states.get(eid):
                self._mode_entity = eid
                break

        # Also search by patterns (als entity_id anders is genaamd)
        if not self._soc_entity:
            for state in self._hass.states.async_all("sensor"):
                eid = state.entity_id.lower()
                if ("huawei" in eid or "luna" in eid) and ("soc" in eid or "capacity" in eid):
                    self._soc_entity = state.entity_id
                    break

        # Find max charge/discharge number entities
        for state in self._hass.states.async_all("number"):
            eid = state.entity_id.lower()
            if "storage_maximum_charging_power" in eid or ("huawei" in eid and "max_charge" in eid):
                self._max_charge_entity = state.entity_id
            if "storage_maximum_discharging_power" in eid or ("huawei" in eid and "max_discharge" in eid):
                self._max_discharge_entity = state.entity_id

        detected = self._soc_entity is not None
        if detected:
            _LOGGER.info("HuaweiLunaProvider: gedetecteerd soc=%s power=%s mode=%s",
                         self._soc_entity, self._power_entity, self._mode_entity)
        return detected

    def read_state(self) -> BatteryProviderState:
        soc_pct = power_w = None
        active_mode = "unknown"

        if self._soc_entity:
            s = self._hass.states.get(self._soc_entity)
            if s and s.state not in ("unavailable", "unknown"):
                try: soc_pct = float(s.state)
                except (ValueError, TypeError): pass

        if self._power_entity:
            s = self._hass.states.get(self._power_entity)
            if s and s.state not in ("unavailable", "unknown"):
                try: power_w = float(s.state)
                except (ValueError, TypeError): pass

        if self._mode_entity:
            s = self._hass.states.get(self._mode_entity)
            if s and s.state not in ("unavailable", "unknown"):
                active_mode = s.state

        return BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc_pct,
            power_w        = power_w,
            is_charging    = (power_w or 0) > 10,
            is_discharging = (power_w or 0) < -10,
            active_mode    = active_mode,
            available_modes= [
                MODE_MAXIMIZE_SELF_CONSUMPTION,
                MODE_TIME_OF_USE,
                MODE_FIXED_CHARGE,
                MODE_FULLY_FED_TO_GRID,
            ],
            is_online = soc_pct is not None,
        )

    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        """Huawei charging — via Time of Use mode + optional max power."""
        if self._max_charge_entity and power_w:
            try:
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self._max_charge_entity, "value": round(power_w)},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.warning("Huawei: max laadvermogen instellen mislukt: %s", e)

        return await self.async_set_mode(MODE_TIME_OF_USE)

    async def async_set_discharge(self, power_w: Optional[float] = None) -> bool:
        """Huawei discharge."""
        if self._max_discharge_entity and power_w:
            try:
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self._max_discharge_entity, "value": round(abs(power_w))},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.warning("Huawei: max ontlaadvermogen instellen mislukt: %s", e)

        return await self.async_set_mode(MODE_FIXED_CHARGE)

    async def async_set_auto(self) -> bool:
        """Restore self-consumption mode (standaard)."""
        return await self.async_set_mode(MODE_MAXIMIZE_SELF_CONSUMPTION)

    async def async_set_mode(self, mode: str, **kwargs) -> bool:
        """Set Huawei operating mode."""
        if not self._mode_entity:
            _LOGGER.warning("Huawei: geen mode select entity gevonden")
            return False
        try:
            await self._hass.services.async_call(
                "select", "select_option",
                {"entity_id": self._mode_entity, "option": mode},
                blocking=True,
            )
            _LOGGER.info("Huawei Luna: modus ingesteld op '%s'", mode)
            return True
        except Exception as e:
            _LOGGER.warning("Huawei Luna: modus instellen mislukt (%s): %s", mode, e)
            return False

    def get_available_modes(self) -> list[dict]:
        return [
            {"id": MODE_MAXIMIZE_SELF_CONSUMPTION, "label": "Zelfconsumptie maximaliseren", "icon": "mdi:solar-power"},
            {"id": MODE_TIME_OF_USE,               "label": "Time of Use (EPEX)",           "icon": "mdi:clock-outline"},
            {"id": MODE_FIXED_CHARGE,              "label": "Geforceerd laden/ontladen",     "icon": "mdi:battery-charging"},
            {"id": MODE_FULLY_FED_TO_GRID,         "label": "Alles terug naar net",          "icon": "mdi:transmission-tower-export"},
        ]

    def get_wizard_hint(self) -> ProviderWizardHint:
        return ProviderWizardHint(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            detected       = self.is_detected,
            enabled        = self.is_enabled,
            hint           = "Huawei Luna 2000 gedetecteerd via huawei_solar integratie. CloudEMS kan EPEX-gestuurd laden en ontladen.",
            setup_url      = "https://github.com/wlcrs/huawei_solar",
        )


BatteryProviderRegistry.register_provider(HuaweiLunaProvider)
