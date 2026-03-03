"""CloudEMS Select platform — EPEX land selectie."""
# Copyright 2025 CloudEMS — https://cloudems.eu
from __future__ import annotations
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, VERSION, NAME, EPEX_AREAS
from .coordinator import CloudEMSCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CloudEMSEPEXCountrySelect(coordinator, entry)])


class CloudEMSEPEXCountrySelect(CoordinatorEntity, SelectEntity):
    _attr_name = "CloudEMS EPEX Prijszone"
    _attr_icon = "mdi:map-marker"
    _attr_options = list(EPEX_AREAS.keys())

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_epex_country"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=f"CloudEMS v{VERSION}",
            name=NAME,
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator._prices:
            return getattr(self.coordinator._prices, "_country", None)
        return self._entry.data.get("energy_prices_country")

    async def async_select_option(self, option: str) -> None:
        if self.coordinator._prices:
            self.coordinator._prices._country = option
            await self.coordinator._prices.update()
        self.async_write_ha_state()
