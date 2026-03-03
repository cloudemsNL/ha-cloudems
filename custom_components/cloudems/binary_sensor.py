"""CloudEMS binary sensor platform."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, MANUFACTURER, VERSION, WEBSITE
from .coordinator import CloudEMSCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    phase_count = int(entry.data.get("phase_count", 1))
    entities = [
        NegativePriceBinarySensor(coordinator, entry),
        CheapHourBinarySensor(coordinator, entry),
    ]
    for phase in range(1, (phase_count + 1) if phase_count == 3 else 2):
        entities.append(PhaseLimitedBinarySensor(coordinator, entry, phase))
    async_add_entities(entities)


class CloudEMSBaseBinary(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=NAME, manufacturer=MANUFACTURER,
            model=f"CloudEMS v{VERSION}", configuration_url=WEBSITE,
        )


class NegativePriceBinarySensor(CloudEMSBaseBinary):
    _attr_name = "CloudEMS Negatieve Energieprijs"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:currency-eur-off"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_negative_price"

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("is_negative_price", False)


class CheapHourBinarySensor(CloudEMSBaseBinary):
    _attr_name = "CloudEMS Goedkoop Uur"
    _attr_icon = "mdi:piggy-bank"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cheap_hour"

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("is_cheap_hour", False)


class PhaseLimitedBinarySensor(CloudEMSBaseBinary):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry, phase):
        super().__init__(coordinator, entry)
        self._phase = phase
        self._attr_name = f"CloudEMS L{phase} Begrensd"
        self._attr_unique_id = f"{entry.entry_id}_limited_l{phase}"
        self._attr_icon = "mdi:current-ac"

    @property
    def is_on(self):
        phases = (self.coordinator.data or {}).get("phase_status", {})
        return phases.get(self._phase, {}).get("limited", False)
