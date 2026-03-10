# -*- coding: utf-8 -*-
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
        # Moved from sensor.py so entity_ids use binary_sensor.* domain
        CloudEMSOccupancyBinarySensor(coordinator, entry),
        CloudEMSAnomalyBinarySensor(coordinator, entry),
        CloudEMSCheapHourRankedBinarySensor(coordinator, entry, 1),
        CloudEMSCheapHourRankedBinarySensor(coordinator, entry, 2),
        CloudEMSCheapHourRankedBinarySensor(coordinator, entry, 3),
        CloudEMSCheapHourRankedBinarySensor(coordinator, entry, 4),
        CloudEMSSimulatorBinarySensor(coordinator, entry),
    ]
    for phase in range(1, (phase_count + 1) if phase_count == 3 else 2):
        entities.append(PhaseLimitedBinarySensor(coordinator, entry, phase))
    async_add_entities(entities, update_before_add=False)


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


# ── Moved from sensor.py so entity_ids correctly use binary_sensor.* domain ──

class CloudEMSCheapHourRankedBinarySensor(CloudEMSBaseBinary):
    """True when the current hour is in the N cheapest hours of the day."""
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:clock-check"

    def __init__(self, coordinator, entry, rank: int):
        super().__init__(coordinator, entry)
        self._rank = rank
        self._attr_name = f"CloudEMS Energy · Cheapest {rank}h"
        self._attr_unique_id = f"{entry.entry_id}_cheap_hour_{rank}"

    @property
    def is_on(self) -> bool:
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return bool(ep.get(f"in_cheapest_{self._rank}h", False))

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "hours": ep.get(f"cheapest_{self._rank}h_hours", []),
            "current_price": ep.get("current"),
        }


class CloudEMSOccupancyBinarySensor(CloudEMSBaseBinary):
    """ON when home consumption pattern indicates someone is probably home."""
    _attr_name = "CloudEMS Aanwezigheid (op basis van stroom)"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_occupancy"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("baseline", {}).get("is_home", False))

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        return {
            "current_w":   b.get("current_w"),
            "standby_w":   b.get("standby_w"),
            "model_ready": b.get("model_ready", False),
            "method":      "power_based",
        }


class CloudEMSAnomalyBinarySensor(CloudEMSBaseBinary):
    """ON when power consumption is significantly above the learned normal."""
    _attr_name = "CloudEMS Verbruik Anomalie"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_anomaly"

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("baseline", {}).get("anomaly", False))

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        return {
            "current_w":   b.get("current_w"),
            "expected_w":  b.get("expected_w"),
            "deviation_w": b.get("deviation_w"),
            "sigma_w":     b.get("sigma_w"),
            "model_ready": b.get("model_ready", False),
        }


class CloudEMSSimulatorBinarySensor(CloudEMSBaseBinary):
    """Binary sensor: testmodus actief (binary_sensor.cloudems_testmodus)."""

    _attr_name = "CloudEMS Testmodus"
    _attr_icon = "mdi:test-tube"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_testmodus"

    @property
    def is_on(self) -> bool:
        sim = (self.coordinator.data or {}).get("simulator", {})
        return bool(sim.get("active", False))

    @property
    def extra_state_attributes(self):
        sim = (self.coordinator.data or {}).get("simulator", {})
        return {
            "remaining_min":    sim.get("remaining_min", 0),
            "simulated_fields": sim.get("simulated_fields", []),
            "note":             sim.get("note", ""),
            "overrides":        sim.get("overrides", {}),
        }
