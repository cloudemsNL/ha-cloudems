"""CloudEMS number platform — stroom-limiters per fase."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu
from __future__ import annotations
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, ATTRIBUTION, DEFAULT_MAX_CURRENT, ALL_PHASES
from .coordinator import CloudEMSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        CloudEMSPhaseCurrentLimiter(coordinator, entry, phase)
        for phase in ALL_PHASES
    ]
    entities.append(CloudEMSEVCurrentTarget(coordinator, entry))
    async_add_entities(entities)


class CloudEMSPhaseCurrentLimiter(CoordinatorEntity, NumberEntity):
    """Instelbare stroom-limiet per fase."""
    _attr_attribution = ATTRIBUTION
    _attr_native_min_value = 6.0
    _attr_native_max_value = 63.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "A"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:current-ac"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry, phase: str):
        super().__init__(coordinator)
        self._phase = phase
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_max_current_{phase.lower()}"
        self._attr_name = f"CloudEMS Max Stroom Fase {phase}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "CloudEMS",
            "manufacturer": MANUFACTURER,
        }

    @property
    def native_value(self) -> float:
        phase_state = self.coordinator._limiter._phases.get(self._phase)
        return phase_state.max_ampere if phase_state else DEFAULT_MAX_CURRENT

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator._limiter.set_max_current(self._phase, value)
        self.async_write_ha_state()


class CloudEMSEVCurrentTarget(CoordinatorEntity, NumberEntity):
    """Doel EV laadstroom."""
    _attr_attribution = ATTRIBUTION
    _attr_native_min_value = 0.0
    _attr_native_max_value = 32.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "A"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_target_current"
        self._attr_name = "CloudEMS EV Doel Laadstroom"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def native_value(self) -> float:
        return self.coordinator._limiter._ev_target_current

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator._limiter._ev_target_current = value
        await self.coordinator._set_ev_current(value)
        self.async_write_ha_state()
