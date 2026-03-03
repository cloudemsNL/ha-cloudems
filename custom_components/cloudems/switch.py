"""CloudEMS switch platform."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu
from __future__ import annotations
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, ATTRIBUTION
from .coordinator import CloudEMSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        CloudEMSSolarDimmerSwitch(coordinator, entry),
        CloudEMSSmartEVSwitch(coordinator, entry),
    ])


class CloudEMSSolarDimmerSwitch(CoordinatorEntity, SwitchEntity):
    """Schakelaar voor zonne-energie dimmen bij negatieve prijs."""
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:solar-power-variant-outline"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_dimmer"
        self._attr_name = "CloudEMS Zonne-energie Dimmer"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        # Lees de toestand uit de limiter
        return self.coordinator._limiter._negative_price_mode

    async def async_turn_on(self, **kwargs):
        self.coordinator._limiter.set_negative_price_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self.coordinator._limiter.set_negative_price_mode(False)
        self.async_write_ha_state()


class CloudEMSSmartEVSwitch(CoordinatorEntity, SwitchEntity):
    """Schakelaar voor slim EV laden op zonne-overschot."""
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_smart_ev"
        self._attr_name = "CloudEMS Slim EV Laden"
        self._smart_ev_enabled = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def is_on(self) -> bool:
        return self._smart_ev_enabled

    async def async_turn_on(self, **kwargs):
        self._smart_ev_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._smart_ev_enabled = False
        self.async_write_ha_state()
