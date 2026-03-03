"""CloudEMS sensor platform — v1.3.0"""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
from __future__ import annotations
import logging

from homeassistant.components.sensor import (
    SensorEntity, SensorDeviceClass, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfElectricCurrent, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, NAME, MANUFACTURER, VERSION, WEBSITE,
    ATTR_PROBABILITY, ATTR_DEVICE_TYPE, ATTR_CONFIRMED,
    ICON_NILM, ICON_LIMITER, ICON_PRICE,
    CONF_PHASE_COUNT,
)
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        CloudEMSPowerSensor(coordinator, entry),
        CloudEMSPriceSensor(coordinator, entry),
        CloudEMSNILMStatsSensor(coordinator, entry),
        CloudEMSCostSensor(coordinator, entry),
        CloudEMSDynamicLoaderSensor(coordinator, entry),
        CloudEMSP1Sensor(coordinator, entry),
    ]

    # Fase-sensoren
    phase_count = int(entry.data.get(CONF_PHASE_COUNT, 1))
    for phase in (["L1", "L2", "L3"] if phase_count == 3 else ["L1"]):
        entities.append(CloudEMSPhaseSensor(coordinator, entry, phase))

    # Phase balance sensor alleen bij 3 fasen
    if phase_count == 3:
        entities.append(CloudEMSPhaseBalanceSensor(coordinator, entry))

    # v1.3: Solar learner sensoren per omvormer
    inverter_cfgs = entry.data.get("inverter_configs", [])
    for inv in inverter_cfgs:
        entities.append(CloudEMSInverterLearnedSensor(coordinator, entry, inv))

    async_add_entities(entities)

    # Dynamisch NILM-sensoren toevoegen bij detectie
    @callback
    def _nilm_updated():
        existing_ids = {e.unique_id for e in entities}
        new_ents = []
        for dev in coordinator.nilm.get_devices():
            uid = f"{entry.entry_id}_nilm_{dev.device_id}"
            if uid not in existing_ids:
                new_ents.append(CloudEMSNILMDeviceSensor(coordinator, entry, dev))
                existing_ids.add(uid)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_nilm_updated)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME,
        manufacturer=MANUFACTURER,
        model=f"CloudEMS v{VERSION}",
        sw_version=VERSION,
        configuration_url=WEBSITE,
    )


# ── Basisklassen ──────────────────────────────────────────────────────────────

class CloudEMSPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Netspanning Vermogen"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_power"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        return d.get("power_w") or d.get("grid_power_w")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "solar_power_w":      d.get("solar_power_w", 0),
            "ev_charging_current": d.get("ev_current", 0),
            "solar_curtailment":  d.get("solar_curtailment", 0),
        }


class CloudEMSPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Energieprijs"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_price"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        p = ep.get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "is_negative":  ep.get("is_negative", False),
            "min_today":    ep.get("min_today"),
            "max_today":    ep.get("max_today"),
            "avg_today":    ep.get("avg_today"),
            "next_hours":   ep.get("next_hours", []),
        }


class CloudEMSPhaseSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = ICON_LIMITER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Fase {phase} Stroom"
        self._attr_unique_id = f"{entry.entry_id}_current_{phase.lower()}"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        phases = (self.coordinator.data or {}).get("phases", {})
        pd = phases.get(self._phase, {})
        a = pd.get("current_a")
        return round(a, 2) if a is not None else None

    @property
    def extra_state_attributes(self):
        phases = (self.coordinator.data or {}).get("phases", {})
        pd = phases.get(self._phase, {})
        return {
            "max_current_a":    pd.get("max_import_a"),
            "utilisation_pct":  pd.get("utilisation_pct"),
            "limited":          pd.get("limited", False),
            "power_w":          pd.get("power_w"),
        }


class CloudEMSNILMStatsSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS NILM Status"
    _attr_icon = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_stats"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        return sum(1 for d in devices if d.get("confirmed"))

    @property
    def extra_state_attributes(self):
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        return {
            "confirmed_devices": sum(1 for d in devices if d.get("confirmed")),
            "pending_devices":   sum(1 for d in devices if d.get("pending")),
            "total_devices":     len(devices),
            "nilm_mode":         (self.coordinator.data or {}).get("nilm_mode", ""),
        }


class CloudEMSNILMDeviceSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry, device):
        super().__init__(coord)
        self._entry = entry
        self._device_id = device.device_id
        self._attr_name = f"CloudEMS {device.name}"
        self._attr_unique_id = f"{entry.entry_id}_nilm_{device.device_id}"
        self._attr_icon = ICON_NILM

    @property
    def device_info(self):
        return _device_info(self._entry)

    def _get_device(self):
        devs = (self.coordinator.data or {}).get("nilm_devices", [])
        return next((d for d in devs if d["device_id"] == self._device_id), None)

    @property
    def native_value(self):
        d = self._get_device()
        return d.get("power") if d else None

    @property
    def extra_state_attributes(self):
        d = self._get_device()
        if not d:
            return {}
        return {
            ATTR_PROBABILITY:  round(d.get("confidence", 0) * 100, 1),
            ATTR_DEVICE_TYPE:  d.get("device_type"),
            ATTR_CONFIRMED:    d.get("confirmed", False),
            "source":          d.get("source"),
            "phase":           d.get("phase"),
            "energy_today_kwh": d.get("energy_today", 0),
        }

    @property
    def available(self):
        return self._get_device() is not None


# ── v1.2 sensoren ─────────────────────────────────────────────────────────────

class CloudEMSCostSensor(CoordinatorEntity, SensorEntity):
    """Live energiekosten op basis van huidig vermogen en EPEX-prijs."""
    _attr_name = "CloudEMS Energiekosten nu"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/h"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cost_now"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        cost = d.get("cost_eur_per_hour")
        return round(cost, 4) if cost is not None else None

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        ep = d.get("energy_price", {})
        return {
            "price_eur_kwh": ep.get("current", 0),
            "power_w":       d.get("power_w") or d.get("grid_power_w"),
            "is_negative":   ep.get("is_negative", False),
        }


class CloudEMSPhaseBalanceSensor(CoordinatorEntity, SensorEntity):
    """Fase-onbalans in Ampere (alleen 3-fase installaties)."""
    _attr_name = "CloudEMS Fase-onbalans"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_phase_imbalance"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        balance = (self.coordinator.data or {}).get("phase_balance", {})
        v = balance.get("imbalance_a")
        return round(v, 2) if v is not None else None

    @property
    def extra_state_attributes(self):
        balance = (self.coordinator.data or {}).get("phase_balance", {})
        return {
            "balanced":         balance.get("balanced", True),
            "overloaded_phase": balance.get("overloaded_phase"),
            "lightest_phase":   balance.get("lightest_phase"),
            "recommendation":   balance.get("recommendation", ""),
        }


class CloudEMSDynamicLoaderSensor(CoordinatorEntity, SensorEntity):
    """Dynamisch EV laadstroom besluit (EPEX + zonne-energie)."""
    _attr_name = "CloudEMS EV Laadstroom (dynamisch)"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:ev-station"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_dynamic_current"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        dl = (self.coordinator.data or {}).get("dynamic_loader", {})
        return dl.get("target_current_a")

    @property
    def extra_state_attributes(self):
        dl = (self.coordinator.data or {}).get("dynamic_loader", {})
        return {
            "reason":          dl.get("reason", ""),
            "price_eur_kwh":   dl.get("price_eur_kwh"),
            "solar_surplus_w": dl.get("solar_surplus_w", 0),
        }


class CloudEMSP1Sensor(CoordinatorEntity, SensorEntity):
    """Live netspanning vanuit P1 slimme meter."""
    _attr_name = "CloudEMS P1 Netmeter"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:meter-electric"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_p1_power"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        p1 = (self.coordinator.data or {}).get("p1", {})
        return p1.get("net_power_w")

    @property
    def available(self):
        p1 = (self.coordinator.data or {}).get("p1", {})
        return bool(p1)

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1", {})
        return {
            "import_w":          p1.get("power_import_w"),
            "export_w":          p1.get("power_export_w"),
            "energy_import_kwh": p1.get("energy_import_kwh"),
            "energy_export_kwh": p1.get("energy_export_kwh"),
            "current_l1":        p1.get("current_l1"),
            "current_l2":        p1.get("current_l2"),
            "current_l3":        p1.get("current_l3"),
            "tariff":            p1.get("tariff"),
        }


# ── v1.3 sensoren ─────────────────────────────────────────────────────────────

class CloudEMSInverterLearnedSensor(CoordinatorEntity, SensorEntity):
    """Geleerd piekvermogen + fase per omvormer."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:solar-power"

    def __init__(self, coord, entry, inv_cfg: dict):
        super().__init__(coord)
        self._entry   = entry
        self._inv_id  = inv_cfg["entity_id"]
        self._label   = inv_cfg.get("label", self._inv_id)
        self._attr_name = f"CloudEMS {self._label} Geleerde Piek"
        self._attr_unique_id = f"{entry.entry_id}_inv_peak_{self._inv_id.replace('.', '_')}"

    @property
    def device_info(self):
        return _device_info(self._entry)

    @property
    def native_value(self):
        sl = (self.coordinator.data or {}).get("solar_learner", {})
        profile = sl.get(self._inv_id, {})
        v = profile.get("peak_power_w")
        return round(v, 1) if v else None

    @property
    def extra_state_attributes(self):
        sl = (self.coordinator.data or {}).get("solar_learner", {})
        p  = sl.get(self._inv_id, {})
        mi = (self.coordinator.data or {}).get("multi_inverter", {})
        inv_list = mi.get("inverters", [])
        inv_status = next(
            (i for i in inv_list if i.get("id") == self._inv_id), {}
        )
        return {
            "estimated_wp":   p.get("estimated_wp"),
            "samples":        p.get("samples", 0),
            "confident":      p.get("confident", False),
            "detected_phase": p.get("detected_phase"),
            "phase_certain":  p.get("phase_certain", False),
            "phase_votes":    p.get("phase_votes", {}),
            "current_output_pct": inv_status.get("current_pct"),
            "last_updated":   p.get("last_updated"),
        }
