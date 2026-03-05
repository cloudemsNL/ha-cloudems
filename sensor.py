"""CloudEMS sensor + binary_sensor platform — v1.5.0."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
from __future__ import annotations
import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower, UnitOfElectricCurrent, UnitOfElectricPotential,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, NAME, MANUFACTURER, VERSION, WEBSITE, ATTRIBUTION,
    ICON_NILM, ICON_LIMITER, ICON_PRICE, ICON_SOLAR, ICON_VOLTAGE,
    ICON_POWER, ICON_FORECAST, ICON_ENERGY, ICON_PEAK,
    CONF_PHASE_COUNT, CONF_INVERTER_CONFIGS,
    DEVICE_ICONS,
    GAS_KWH_PER_M3, GAS_BOILER_EFFICIENCY,
    DEFAULT_BOILER_EFFICIENCY, DEFAULT_HEAT_PUMP_COP, DEFAULT_GAS_PRICE_EUR_M3,
    CONF_GAS_PRICE_SENSOR, CONF_GAS_PRICE_FIXED, CONF_BOILER_EFFICIENCY, CONF_HEAT_PUMP_COP,
    CONF_HEAT_PUMP_ENTITY,
)
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    phase_count = int(entry.data.get(CONF_PHASE_COUNT, 1))
    inv_cfgs    = entry.data.get(CONF_INVERTER_CONFIGS, [])

    entities: list = [
        CloudEMSPowerSensor(coordinator, entry),
        # CloudEMSGridNetPowerSensor removed – CloudEMSPowerSensor already owns
        # sensor.cloudems_grid_net_power (unique_id _power). Adding a second
        # sensor with the same name caused entity_id conflicts (_2 suffix).
        CloudEMSGridImportPowerSensor(coordinator, entry),
        CloudEMSGridExportPowerSensor(coordinator, entry),
        CloudEMSGridImportEnergySensor(coordinator, entry, tariff=1),
        CloudEMSGridImportEnergySensor(coordinator, entry, tariff=2),
        CloudEMSGridExportEnergySensor(coordinator, entry, tariff=1),
        CloudEMSGridExportEnergySensor(coordinator, entry, tariff=2),
        # v1.10.2: NILM top-5 highest-power running devices
        *[CloudEMSNILMTopDeviceSensor(coordinator, entry, rank) for rank in range(1, 16)],
        # v1.10.3: Solar ROI sensor
        CloudEMSSolarROISensor(coordinator, entry),
        # v1.10.3: Self-learning intelligence sensors (zero-config)
        CloudEMSHomeBaselineSensor(coordinator, entry),
        CloudEMSStandbyHunterSensor(coordinator, entry),  # occupancy + anomaly → binary_sensor.py
        CloudEMSEVSessionSensor(coordinator, entry),
        CloudEMSNILMScheduleSensor(coordinator, entry),
        CloudEMSWeatherCalibrationSensor(coordinator, entry),
        # v1.11.0: 8 new intelligence sensors
        CloudEMSThermalModelSensor(coordinator, entry),
        CloudEMSFlexScoreSensor(coordinator, entry),
        CloudEMSPVHealthSensor(coordinator, entry),
        CloudEMSGasSensor(coordinator, entry),
        CloudEMSEnergySourceSensor(coordinator, entry),
        CloudEMSSelfConsumptionSensor(coordinator, entry),
        CloudEMSDayTypeSensor(coordinator, entry),
        CloudEMSDeviceDriftSensor(coordinator, entry),
        CloudEMSPhaseMigrationSensor(coordinator, entry),
        CloudEMSMicroMobilitySensor(coordinator, entry),
        CloudEMSNotificationSensor(coordinator, entry),
        CloudEMSClippingLossSensor(coordinator, entry),
        CloudEMSConsumptionCategoriesSensor(coordinator, entry),
        CloudEMSSolarSystemSensor(coordinator, entry),
        # v1.5: dedicated previous / current / next-hour price sensors
        CloudEMSPriceSensor(coordinator, entry),
        CloudEMSPricePreviousHourSensor(coordinator, entry),
        CloudEMSPriceCurrentSensor(coordinator, entry),
        CloudEMSPriceNextHourSensor(coordinator, entry),
        CloudEMSNILMStatsSensor(coordinator, entry),
        # v1.5: NILM running-devices list sensors (plain + with power)
        CloudEMSNILMRunningDevicesSensor(coordinator, entry),
        CloudEMSNILMRunningDevicesPowerSensor(coordinator, entry),
        CloudEMSCostSensor(coordinator, entry),
        CloudEMSP1Sensor(coordinator, entry),
        CloudEMSForecastSensor(coordinator, entry),
        CloudEMSForecastTomorrowSensor(coordinator, entry),
        CloudEMSForecastPeakSensor(coordinator, entry),
        CloudEMSPeakShavingSensor(coordinator, entry),
        CloudEMSGridCongestionSensor(coordinator, entry),
        CloudEMSBatteryHealthSensor(coordinator, entry),
        CloudEMSMonthlyPeakSensor(coordinator, entry),
        CloudEMSNILMDatabaseSensor(coordinator, entry),
        CloudEMSSensorHintsSensor(coordinator, entry),
        CloudEMSScaleInfoSensor(coordinator, entry),
        CloudEMSInsightsSensor(coordinator, entry),
        CloudEMSDecisionLogSensor(coordinator, entry),
        CloudEMSBoilerStatusSensor(coordinator, entry),
        # v1.5: AI / NILM status sensor
        CloudEMSAIStatusSensor(coordinator, entry),
        # v1.6: EPEX all-hours chart sensor
        CloudEMSEPEXTodaySensor(coordinator, entry),
        # v1.7: NILM Diagnostics sensor
        CloudEMSNILMDiagSensor(coordinator, entry),
        # v1.8: PID diagnostics sensor
        CloudEMSPIDDiagSensor(coordinator, entry),
        # v1.8: NILM sensor input info
        CloudEMSNILMInputSensor(coordinator, entry),
        # v1.9: CO2 intensity
        CloudEMSCO2Sensor(coordinator, entry),
        # v1.9: energy cost forecast
        CloudEMSCostForecastSensor(coordinator, entry),
        # v1.9: battery EPEX schedule
        CloudEMSBatteryScheduleSensor(coordinator, entry),
        # v1.15.4: new intelligence sensors (absence detector, climate preheat, PV accuracy, EMA diag, sanity)
        CloudEMSAbsenceDetectorSensor(coordinator, entry),
        CloudEMSClimatePreheatSensor(coordinator, entry),
        CloudEMSPVForecastAccuracySensor(coordinator, entry),
        CloudEMSEMADiagnosticsSensor(coordinator, entry),
        CloudEMSSanitySensor(coordinator, entry),
        # v1.16.0: schaduwdetectie & clipping-voorspelling
        CloudEMSShadowDetectionSensor(coordinator, entry),
        CloudEMSClippingForecastSensor(coordinator, entry),
        # v1.16.0: Ollama AI diagnostics
        CloudEMSOllamaDiagSensor(coordinator, entry),
        # v1.17.0: Hybride NILM diagnostics
        CloudEMSHybridNILMSensor(coordinator, entry),
    ]

    phases = ["L1","L2","L3"] if phase_count == 3 else ["L1"]
    for ph in phases:
        entities.append(CloudEMSPhaseCurrentSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseVoltageSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhasePowerSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseImportPowerSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseExportPowerSensor(coordinator, entry, ph))

    if phase_count == 3:
        entities.append(CloudEMSPhaseBalanceSensor(coordinator, entry))

    # Per-inverter sensors (peak, clipping, forecast)
    for inv in inv_cfgs:
        entities.append(CloudEMSInverterSensor(coordinator, entry, inv))

    # EPEX cheap-hour binary sensors (registered in binary_sensor.py for correct binary_sensor.* entity_ids)
    # for rank in [1, 2, 3]: entities.append(CloudEMSCheapHourBinarySensor(...))

    async_add_entities(entities)

    # Pre-populate registered sets from the HA entity registry so that on HA
    # restart, already-known dynamic entities are not re-added (which causes
    # "ID already exists - ignoring" warnings in the log).
    from homeassistant.helpers import entity_registry as er
    _er = er.async_get(hass)
    _existing_uids: set = {
        e.unique_id
        for e in er.async_entries_for_config_entry(_er, entry.entry_id)
    }

    # Dynamically add NILM device sensors when detected
    registered_nilm_ids: set = set(_existing_uids)

    @callback
    def _nilm_updated():
        new_ents = []
        for dev in coordinator.nilm.get_devices():
            uid = f"{entry.entry_id}_nilm_{dev.device_id}"
            if uid not in registered_nilm_ids:
                new_ents.append(CloudEMSNILMDeviceSensor(coordinator, entry, dev))
                registered_nilm_ids.add(uid)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_nilm_updated)

    # Dynamically add per-inverter profile sensors and clipping binary sensors
    registered_inv_ids: set = set(_existing_uids)

    @callback
    def _inverters_updated():
        new_ents = []
        for inv in (coordinator.data or {}).get("inverter_data", []):
            eid = inv.get("entity_id", "")
            uid_sensor  = f"{entry.entry_id}_inv_profile_{eid}"
            uid_clip    = f"{entry.entry_id}_inv_clipping_{eid}"
            if uid_sensor not in registered_inv_ids:
                new_ents.append(CloudEMSInverterProfileSensor(coordinator, entry, eid))
                new_ents.append(CloudEMSInverterClippingBinarySensor(coordinator, entry, eid))
                registered_inv_ids.add(uid_sensor)
                registered_inv_ids.add(uid_clip)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_inverters_updated)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME, manufacturer=MANUFACTURER,
        model=f"CloudEMS v{VERSION}", sw_version=VERSION,
        configuration_url=WEBSITE,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Core sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPowerSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · Net Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        # BUG FIX: use `is not None` so value 0 is returned correctly (or → falsy on 0)
        v = d.get("power_w")
        if v is not None:
            return v
        return d.get("grid_power_w", 0)

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "solar_power_w":   d.get("solar_power_w", 0),
            "import_power_w":  d.get("import_power_w", 0),
            "export_power_w":  d.get("export_power_w", 0),
            "solar_surplus_w": d.get("solar_surplus_w", 0),
            "ev_current_a":    d.get("ev_decision", {}).get("target_current_a", 0),
        }


class CloudEMSPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Energy · Price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_price"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("energy_price", {}).get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "is_negative":       ep.get("is_negative", False),
            "min_today":         ep.get("min_today"),
            "max_today":         ep.get("max_today"),
            "avg_today":         ep.get("avg_today"),
            "next_hours":        ep.get("next_hours", []),
            "cheapest_hour_1":   ep.get("cheapest_hour_1"),
            "cheapest_hour_2":   ep.get("cheapest_hour_2"),
            "cheapest_hour_3":   ep.get("cheapest_hour_3"),
            "cheapest_2h_start": ep.get("cheapest_2h_start"),
            "cheapest_3h_start": ep.get("cheapest_3h_start"),
            "cheapest_4h_start": ep.get("cheapest_4h_start"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NEW v1.4.1 — Insights + Decision log + Boiler
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInsightsSensor(CoordinatorEntity, SensorEntity):
    """Text sensor: human-readable insights and advice (inzicht & advies)."""
    _attr_name = "CloudEMS Energy · Insights"
    _attr_icon = "mdi:lightbulb-on"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_insights"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        text = data.get("insights", "")
        # If coordinator has no data yet: show helpful startup message, not "unavailable"
        if not data:
            return "⏳ CloudEMS start op — even geduld..."
        if not text:
            return "✅ Bezig met leren — over enkele minuten verschijnen hier tips."
        # HA state max 255 chars — show first tip only
        if " | " in text:
            return text.split(" | ")[0][:255]
        return text[:255]

    @property
    def extra_state_attributes(self):
        text = (self.coordinator.data or {}).get("insights", "")
        tips = text.split(" | ") if text else []
        return {
            "all_tips":   tips,
            "tip_count":  len(tips),
            "full_text":  text,
        }


class CloudEMSDecisionLogSensor(CoordinatorEntity, SensorEntity):
    """Text sensor: why CloudEMS dimmed solar / switched devices."""
    _attr_name = "CloudEMS System · Decision Log"
    _attr_icon  = "mdi:text-box-multiple"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_attribution = ATTRIBUTION

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_decision_log"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        log = (self.coordinator.data or {}).get("decision_log", [])
        if log:
            return log[0].get("message","")[:255]
        return "Geen acties"

    @property
    def extra_state_attributes(self):
        log = (self.coordinator.data or {}).get("decision_log", [])
        return {
            "last_10": log[:10],
            "count":   len(log),
        }


class CloudEMSBoilerStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor: boiler/socket controller status."""
    _attr_name = "CloudEMS Boiler · Status"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_boiler_status"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        boilers = (self.coordinator.data or {}).get("boiler_status", [])
        on_count = sum(1 for b in boilers if b.get("is_on"))
        return f"{on_count}/{len(boilers)} aan"

    @property
    def extra_state_attributes(self):
        return {
            "boilers": (self.coordinator.data or {}).get("boiler_status", []),
            "log":     [(d["ts"], d["message"]) for d in
                        (self.coordinator.data or {}).get("decision_log", [])
                        if d.get("category") == "boiler"][:5],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Per-phase sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPhaseCurrentSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = ICON_LIMITER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Current"
        self._attr_unique_id = f"{entry.entry_id}_current_{phase.lower()}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        a = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("current_a")
        return round(a, 3) if a is not None else None

    @property
    def extra_state_attributes(self):
        pd = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{})
        return {
            "max_current_a":    pd.get("max_import_a"),
            "utilisation_pct":  pd.get("utilisation_pct"),
            "limited":          pd.get("limited", False),
            "power_w":          pd.get("power_w"),
            "voltage_v":        pd.get("voltage_v"),
            "derived_from":     pd.get("derived_from","direct"),
        }


class CloudEMSPhaseVoltageSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_icon = ICON_VOLTAGE

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Voltage"
        self._attr_unique_id = f"{entry.entry_id}_voltage_{phase.lower()}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        v = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("voltage_v")
        return round(v, 1) if v is not None else None


class CloudEMSPhasePowerSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Power"
        self._attr_unique_id = f"{entry.entry_id}_power_{phase.lower()}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        w = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("power_w")
        return round(w, 1) if w is not None else None


class CloudEMSPhaseBalanceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · Phase Imbalance"
    _attr_icon  = "mdi:scale-unbalanced"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_phase_balance"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("phase_balance",{}).get("imbalance_a")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("phase_balance", {})


# ═══════════════════════════════════════════════════════════════════════════════
# NEW v1.4.1 — Per-inverter sensor (peak power + clipping)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInverterSensor(CoordinatorEntity, SensorEntity):
    """
    Shows current PV output, learned peak power, clipping status,
    estimated Wp, utilisation — for each inverter.
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, inv_cfg: dict):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_cfg.get("entity_id","")
        self._label  = inv_cfg.get("label", self._inv_id)
        self._attr_name = f"CloudEMS Solar · {self._label}"
        self._attr_unique_id = f"{entry.entry_id}_inverter_{self._inv_id}"

    @property
    def device_info(self): return _device_info(self._entry)

    def _inv_data(self) -> dict:
        for inv in (self.coordinator.data or {}).get("inverter_data", []):
            if inv.get("entity_id") == self._inv_id:
                return inv
        return {}

    @property
    def native_value(self):
        d = self._inv_data()
        return d.get("current_w")

    @property
    def extra_state_attributes(self):
        d = self._inv_data()
        return {
            "peak_power_w":        d.get("peak_w", 0),
            "estimated_wp":        d.get("estimated_wp", 0),
            "utilisation_pct":     d.get("utilisation_pct", 0),
            "clipping":            d.get("clipping", False),
            "clipping_ceiling_w":  d.get("clipping_ceiling_w"),
            "phase":               d.get("phase", "unknown"),
            "phase_certain":       d.get("phase_certain", False),
            "phase_display":       d.get("phase_display"),
            "phase_confidence":    d.get("phase_confidence", 0.0),
            "phase_provisional":   d.get("phase_provisional", True),
            "samples":             d.get("samples", 0),
            "confident":           d.get("confident", False),
            # Learning progress — how far along the self-learning cycle is (%)
            "learn_confidence_pct": d.get("orientation_learning_pct", 0),
            "orientation_learned":  d.get("orientation_confident", False),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Forecast + Peak shaving
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSForecastSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Solar · PV Forecast Today"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_today"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("pv_forecast_today_kwh")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "hourly":   d.get("pv_forecast_hourly", []),
            "profiles": d.get("inverter_profiles", []),
        }


class CloudEMSForecastTomorrowSensor(CoordinatorEntity, SensorEntity):
    """PV forecast for tomorrow in kWh — with per-hour breakdown."""
    _attr_name = "CloudEMS Solar · PV Forecast Tomorrow"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_tomorrow"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("pv_forecast_tomorrow_kwh")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "hourly_tomorrow": d.get("pv_forecast_hourly_tomorrow", []),
            "profiles":        d.get("inverter_profiles", []),
        }


class CloudEMSForecastPeakSensor(CoordinatorEntity, SensorEntity):
    """Peak PV power expected today in Watt (best single hour)."""
    _attr_name = "CloudEMS Solar · PV Forecast Peak Today"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_peak_today"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        hourly = (self.coordinator.data or {}).get("pv_forecast_hourly", [])
        if not hourly:
            return None
        # hourly is a list of dicts with key "wh" or a list of float values
        try:
            values = [h["wh"] if isinstance(h, dict) else h for h in hourly]
            return max(values) if values else None
        except (KeyError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {"hourly": d.get("pv_forecast_hourly", [])}


class CloudEMSGridCongestionSensor(CoordinatorEntity, SensorEntity):
    """Grid utilisation percentage — triggers congestion alerts."""
    _attr_name  = "CloudEMS Grid · Congestion Utilisation"
    _attr_icon  = "mdi:transmission-tower-export"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_congestion"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("congestion", {})
        return d.get("utilisation_pct")

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("congestion", {})
        return {
            "active":          d.get("active", False),
            "import_w":        d.get("import_w"),
            "threshold_w":     d.get("threshold_w"),
            "actions":         d.get("actions", []),
            "today_events":    d.get("today_events", 0),
            "month_events":    d.get("month_events", 0),
            "peak_today_w":    d.get("peak_today_w"),
            "monthly_summary": d.get("monthly_summary", []),
        }


class CloudEMSBatteryHealthSensor(CoordinatorEntity, SensorEntity):
    """Battery State of Health (SoH) in percent."""
    _attr_name  = "CloudEMS Battery · State of Health"
    _attr_icon  = "mdi:battery-heart"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_soh"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("battery_degradation", {})
        return d.get("soh_pct")

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("battery_degradation", {})
        return {
            "capacity_kwh":   d.get("capacity_kwh"),
            "total_cycles":   d.get("total_cycles"),
            "cycles_per_day": d.get("cycles_per_day"),
            "alert_level":    d.get("alert_level"),
            "alert_message":  d.get("alert_message"),
            "soc_low_events": d.get("soc_low_events"),
            "days_tracked":   d.get("days_tracked"),
        }


class CloudEMSMonthlyPeakSensor(CoordinatorEntity, SensorEntity):
    """Peak grid import power this month — relevant for capacity tariffs (Belgium / NL 2025)."""
    _attr_name  = "CloudEMS Grid · Monthly Peak Import"
    _attr_icon  = ICON_PEAK
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_monthly_peak_import"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        ps = (self.coordinator.data or {}).get("peak_shaving", {})
        return ps.get("peak_month_w") or ps.get("peak_this_month_w")

    @property
    def extra_state_attributes(self):
        cong = (self.coordinator.data or {}).get("congestion", {})
        ps   = (self.coordinator.data or {}).get("peak_shaving", {})
        return {
            "peak_today_w":    ps.get("peak_today_w") or cong.get("peak_today_w"),
            "monthly_history": cong.get("monthly_summary", []),
        }


class CloudEMSSensorHintsSensor(CoordinatorEntity, SensorEntity):
    """Active sensor configuration hints — unconfigured PV, battery, phase sensors."""
    _attr_name  = "CloudEMS · Sensor Hints"
    _attr_icon  = "mdi:lightbulb-alert"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sensor_hints"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        hints = (self.coordinator.data or {}).get("sensor_hints", [])
        active = [h for h in hints if not h.get("dismissed")]
        return len(active)

    @property
    def extra_state_attributes(self):
        hints = (self.coordinator.data or {}).get("sensor_hints", [])
        return {
            "hints":        hints,
            "active_count": sum(1 for h in hints if not h.get("dismissed")),
        }


class CloudEMSScaleInfoSensor(CoordinatorEntity, SensorEntity):
    """Power scale diagnostics — shows W/kW detection result per sensor."""
    _attr_name  = "CloudEMS · Power Scale Info"
    _attr_icon  = "mdi:scale"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scale_info"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        # Returns number of entities whose scale is confirmed (not pending)
        si = (self.coordinator.data or {}).get("scale_info", {})
        return sum(1 for v in si.values() if v.get("source") != "pending")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("scale_info", {})


class CloudEMSNILMDatabaseSensor(CoordinatorEntity, SensorEntity):
    """NILM database status — total signatures, community count, remote feed health."""
    _attr_name  = "CloudEMS NILM · Database"
    _attr_icon  = "mdi:database-check"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_db"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        stats = (self.coordinator.data or {}).get("nilm_db_stats", {})
        return stats.get("total")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("nilm_db_stats", {})


class CloudEMSPeakShavingSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · Peak Shaving"
    _attr_icon  = ICON_PEAK
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_peak_shaving"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("peak_shaving",{}).get("peak_today_w")

    @property
    def extra_state_attributes(self):
        ps = (self.coordinator.data or {}).get("peak_shaving", {})
        return {
            "active":       ps.get("active", False),
            "limit_w":      ps.get("limit_w"),
            "headroom_w":   ps.get("headroom_w"),
            "peak_today_w": ps.get("peak_today_w"),
            "peak_month_w": ps.get("peak_month_w"),
            "history":      ps.get("peak_history", []),
            "last_action":  ps.get("action","none"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EPEX cheap-hour binary sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCheapHourBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:clock-check"

    def __init__(self, coord, entry, rank: int):
        super().__init__(coord)
        self._entry = entry
        self._rank  = rank
        self._attr_name = f"CloudEMS Energy · Cheapest {rank}h"
        self._attr_unique_id = f"{entry.entry_id}_cheap_hour_{rank}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def is_on(self) -> bool:
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return bool(ep.get(f"in_cheapest_{self._rank}h", False))

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            f"hours":        ep.get(f"cheapest_{self._rank}h_hours", []),
            "current_price": ep.get("current"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NILM sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMStatsSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS NILM · Devices"
    _attr_icon  = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_stats"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("nilm_devices", []))

    @property
    def extra_state_attributes(self):
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        d = self.coordinator.data or {}
        # v1.16.1: trim to essential fields only to stay under HA recorder 16 KB limit
        _src_map = {"smart_plug":"smart_plug","injected":"smart_plug",
                    "cloud_ai":"cloud_ai","ollama":"ollama","local_ai":"local_ai"}
        slim_devices = [
            {
                "name":          dv.get("name", "Unknown"),
                "device_type":   dv.get("device_type", "unknown"),
                "type":          dv.get("device_type", "unknown"),   # alias for card
                "is_on":         dv.get("is_on", False),
                "state":         "on" if dv.get("is_on") else "off",
                "running":       dv.get("is_on", False),
                "power_w":       round(dv.get("current_power", 0), 1),
                "power_min":     round(dv.get("power_min", dv.get("current_power", 0)), 1),
                "confidence":    round(dv.get("confidence", 0) * 100, 0),
                "confirmed":     dv.get("confirmed", False),
                "on_events":     dv.get("on_events", 0),
                "dismissed":     dv.get("dismissed", False),
                # v1.17: fase + bron
                "phase":         dv.get("phase", "L1") or "L1",
                "phase_label":   dv.get("phase", "L1") if dv.get("phase","L1") not in ("ALL","") else "3∅",
                "phase_confirmed": dv.get("phase_confirmed", False),
                "source":        dv.get("source", "database"),
                "source_type":   _src_map.get(dv.get("source",""), "nilm"),
            }
            for dv in devices
        ]
        return {
            "devices":         slim_devices,
            "active_mode":     d.get("nilm_mode", "database"),
            "confirmed_count": sum(1 for dv in devices if dv.get("confirmed")),
            "pending_count":   sum(1 for dv in devices if dv.get("pending")),
            "active_count":    sum(1 for dv in devices if dv.get("is_on")),
            "total_power_w":   sum(dv.get("current_power", 0) for dv in devices if dv.get("is_on")),
        }


class CloudEMSNILMDeviceSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry, device):
        super().__init__(coord)
        self._entry     = entry
        self._device_id = device.device_id
        self._attr_name = f"CloudEMS NILM · {device.display_name}"
        self._attr_icon      = DEVICE_ICONS.get(device.device_type, "mdi:help-circle")
        self._attr_unique_id = f"{entry.entry_id}_nilm_{device.device_id}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _dev(self):
        return self.coordinator.nilm.get_device(self._device_id)

    @property
    def native_value(self):
        dev = self._dev
        return round(dev.current_power, 1) if dev else None

    @property
    @staticmethod
    def _source_type(source: str) -> str:
        return {
            "smart_plug": "smart_plug", "injected": "smart_plug",
            "cloud_ai": "cloud_ai", "ollama": "ollama",
            "local_ai": "local_ai", "database": "nilm",
            "community": "nilm", "builtin": "nilm",
        }.get(source, "nilm")

    def extra_state_attributes(self):
        dev = self._dev
        if not dev:
            return {}
        src_type = self._source_type(dev.source)
        return {
            "device_id":        dev.device_id,
            "device_type":      dev.display_type,
            "is_on":            dev.is_on,
            "confidence_pct":   round(dev.effective_confidence * 100, 1),
            "source":           dev.source,
            # v1.17: bron-type + fase voor dashboard
            "source_type":      src_type,
            "source_label":     {
                "smart_plug": "Stekker", "nilm": "NILM",
                "local_ai": "Lokale AI", "cloud_ai": "Cloud AI", "ollama": "Ollama",
            }.get(src_type, "NILM"),
            "confirmed":        dev.confirmed,
            "user_feedback":    dev.user_feedback,
            "phase":            dev.phase,
            "phase_label":      dev.phase if dev.phase not in ("ALL", "") else "3∅",
            "on_events":        dev.on_events,
            "energy_today_kwh": dev.energy.today_kwh,
            "energy_week_kwh":  dev.energy.week_kwh,
            "energy_month_kwh": dev.energy.month_kwh,
            "energy_year_kwh":  dev.energy.year_kwh,
            "energy_total_kwh": dev.energy.total_kwh,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Cost / P1
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCostSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Energy · Cost"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/h"
    _attr_icon  = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_cost"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cost_per_hour")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "cost_today_eur": d.get("cost_today_eur", 0.0),
            "cost_month_eur": d.get("cost_month_eur", 0.0),
        }


class CloudEMSP1Sensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · P1 Net Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_p1_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("p1_data",{}).get("net_power_w")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("p1_data", {})


# ═══════════════════════════════════════════════════════════════════════════════
# Grid Import / Export sensors (power + energy totals per tariff)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSGridNetPowerSensor(CoordinatorEntity, SensorEntity):
    """Current net grid power in Watt. Positive = import, negative = export.

    BUG FIX v1.13.0: This sensor was referenced in the dashboard as
    sensor.cloudems_grid_net_power but never registered, causing a
    Configuratiefout.  The value is always available in coordinator data
    as 'grid_power' regardless of whether the user configured a net sensor
    or separate import/export sensors.
    """
    _attr_name = "CloudEMS Grid · Net Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_net_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d  = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # P1 net power takes priority; fall back to coordinator-computed grid_power
        v = p1.get("net_power_w")
        if v is not None:
            return v
        v = d.get("grid_power")
        return v if v is not None else 0

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        return {
            "import_power_w": d.get("import_power_w", 0),
            "export_power_w": d.get("export_power_w", 0),
            "source":         "p1" if d.get("p1_data", {}).get("net_power_w") is not None else "calculated",
        }


class CloudEMSGridImportPowerSensor(CoordinatorEntity, SensorEntity):
    """Current grid import power in Watt (Energieverbruik)."""
    _attr_name = "CloudEMS Grid · Import Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_import_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def available(self) -> bool:
        return True  # Always available; returns 0 when no import is happening

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # BUG FIX: or-chain skips 0 (falsy) → use is-not-None priority chain
        for v in (p1.get("power_import_w"), d.get("import_power_w"), d.get("import_power")):
            if v is not None:
                return v
        return 0

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {
            "energy_total_kwh":  p1.get("energy_import_kwh"),
            "energy_t1_kwh":     p1.get("energy_import_t1_kwh"),
            "energy_t2_kwh":     p1.get("energy_import_t2_kwh"),
            "tariff":            p1.get("tariff"),
        }


class CloudEMSGridExportPowerSensor(CoordinatorEntity, SensorEntity):
    """Current grid export power in Watt (Energieproductie)."""
    _attr_name = "CloudEMS Grid · Export Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_export_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def available(self) -> bool:
        return True  # Always available; returns 0 when no export is happening

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # BUG FIX: or-chain skips 0 (falsy) → use is-not-None priority chain
        for v in (p1.get("power_export_w"), d.get("export_power_w"), d.get("export_power")):
            if v is not None:
                return v
        return 0

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {
            "energy_total_kwh":  p1.get("energy_export_kwh"),
            "energy_t1_kwh":     p1.get("energy_export_t1_kwh"),
            "energy_t2_kwh":     p1.get("energy_export_t2_kwh"),
            "tariff":            p1.get("tariff"),
        }


class CloudEMSGridImportEnergySensor(CoordinatorEntity, SensorEntity):
    """Total grid import energy in kWh for a single tariff (meter reading)."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coord, entry, tariff: int):
        super().__init__(coord)
        self._entry = entry
        self._tariff = tariff
        self._attr_name = f"CloudEMS Grid · Import Energy Tariff {tariff}"
        self._attr_unique_id = f"{entry.entry_id}_grid_import_energy_t{tariff}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return p1.get(f"energy_import_t{self._tariff}_kwh")

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {"tariff": self._tariff, "total_all_tariffs_kwh": p1.get("energy_import_kwh")}


class CloudEMSGridExportEnergySensor(CoordinatorEntity, SensorEntity):
    """Total grid export energy in kWh for a single tariff (meter reading)."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coord, entry, tariff: int):
        super().__init__(coord)
        self._entry = entry
        self._tariff = tariff
        self._attr_name = f"CloudEMS Grid · Export Energy Tariff {tariff}"
        self._attr_unique_id = f"{entry.entry_id}_grid_export_energy_t{tariff}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return p1.get(f"energy_export_t{self._tariff}_kwh")

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {"tariff": self._tariff, "total_all_tariffs_kwh": p1.get("energy_export_kwh")}


# ═══════════════════════════════════════════════════════════════════════════════
# Per-phase import / export power sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPhaseImportPowerSensor(CoordinatorEntity, SensorEntity):
    """Per-phase import power in Watt — zero when exporting (Energieverbruik Fase Lx)."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Import Power"
        self._attr_unique_id = f"{entry.entry_id}_import_power_{phase.lower()}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        ph_key = f"power_{self._phase.lower()}_import_w"
        # Prefer direct P1 per-phase import; fall back to max(0, net phase power)
        val = p1.get(ph_key)
        if val is not None and val > 0:
            return round(val, 1)
        net = d.get("phases", {}).get(self._phase, {}).get("power_w")
        if net is not None:
            return round(max(0.0, net), 1)
        return None


class CloudEMSPhaseExportPowerSensor(CoordinatorEntity, SensorEntity):
    """Per-phase export power in Watt — zero when importing (Energieproductie Fase Lx)."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Export Power"
        self._attr_unique_id = f"{entry.entry_id}_export_power_{phase.lower()}"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        ph_key = f"power_{self._phase.lower()}_export_w"
        # Prefer direct P1 per-phase export (DSMR5); fall back to max(0, -net phase power)
        val = p1.get(ph_key)
        if val is not None and val > 0:
            return round(val, 1)
        net = d.get("phases", {}).get(self._phase, {}).get("power_w")
        if net is not None:
            return round(max(0.0, -net), 1)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — Price: Previous / Current / Next hour sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPricePreviousHourSensor(CoordinatorEntity, SensorEntity):
    """Price of the previous hour — useful for comparison on dashboards."""
    _attr_name = "CloudEMS Energy · Price Previous Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_prev_hour"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        prev = ep.get("prev_hour_price")
        return round(prev, 5) if prev is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        cur = ep.get("current")
        prev = ep.get("prev_hour_price")
        delta = None
        if cur is not None and prev is not None:
            delta = round(cur - prev, 5)
        return {"delta_vs_current_eur_kwh": delta}


class CloudEMSPriceCurrentSensor(CoordinatorEntity, SensorEntity):
    """Current EPEX price — dedicated sensor for dashboard cards."""
    _attr_name = "CloudEMS Energy · Price Current Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_current_hour"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        # Show all-in price (with tax/BTW/markup) if toggles are on, else base EPEX
        p = ep.get("current_display") or ep.get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "is_negative":         ep.get("is_negative", False),
            "is_cheap":            ep.get("is_cheap_hour", False),
            "rank_today":          ep.get("rank_today"),
            "min_today":           ep.get("min_today"),
            "max_today":           ep.get("max_today"),
            "avg_today":           ep.get("avg_today"),
            # Tax breakdown
            "base_epex_price":     ep.get("current"),
            "price_all_in":        ep.get("current_all_in"),
            "tax_per_kwh":         ep.get("tax_per_kwh"),
            "vat_rate":            ep.get("vat_rate"),
            "supplier_markup_kwh": ep.get("supplier_markup_kwh"),
            "price_include_tax":   ep.get("price_include_tax", False),
            "price_include_btw":   ep.get("price_include_btw", False),
        }


class CloudEMSPriceNextHourSensor(CoordinatorEntity, SensorEntity):
    """Price of the next hour — helps decide when to shift loads."""
    _attr_name = "CloudEMS Energy · Price Next Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_next_hour"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        next_hours = (self.coordinator.data or {}).get("energy_price", {}).get("next_hours", [])
        if next_hours:
            return round(next_hours[0].get("price", 0), 5)
        return None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        next_hours = ep.get("next_hours", [])
        cur = ep.get("current")
        nxt = next_hours[0].get("price") if next_hours else None
        delta = round(nxt - cur, 5) if (nxt is not None and cur is not None) else None
        return {
            "hour":                   next_hours[0].get("hour") if next_hours else None,
            "delta_vs_current_eur_kwh": delta,
            "next_2h":                [{"hour": h.get("hour"), "price": h.get("price")} for h in next_hours[:2]],
            "cheapest_2h_start":      ep.get("cheapest_2h_start"),
            "cheapest_3h_start":      ep.get("cheapest_3h_start"),
            "cheapest_4h_start":      ep.get("cheapest_4h_start"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — NILM: Running devices list sensors (for dashboard)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMRunningDevicesSensor(CoordinatorEntity, SensorEntity):
    """
    State = number of devices currently ON.
    Attributes contain a clean list of running device names — suitable for
    dashboard display cards (e.g. Markdown card, custom:auto-entities).
    """
    _attr_name = "CloudEMS NILM · Running Devices"
    _attr_icon = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_running"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _running(self) -> list:
        return [d for d in (self.coordinator.data or {}).get("nilm_devices", []) if d.get("is_on")]

    @property
    def native_value(self):
        return len(self._running)

    @property
    def extra_state_attributes(self):
        running = self._running
        return {
            "device_names": [d.get("name", d.get("device_type", "Unknown")) for d in running],
            "device_list": [
                {
                    "name":         d.get("name", "Unknown"),
                    "type":         d.get("device_type", "unknown"),
                    "confirmed":    d.get("confirmed", False),
                    "confidence":   round(d.get("confidence", 0) * 100, 0),
                    # v1.17: fase + bron voor dashboard
                    "phase":        d.get("phase", "L1"),
                    "phase_label":  d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3∅",
                    "source":       d.get("source", "database"),
                    "source_type":  {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "power_w":      round(d.get("current_power", 0), 1),
                    "running":      True,
                    "state":        "on",
                }
                for d in running
            ],
            "nilm_mode": (self.coordinator.data or {}).get("nilm_mode", "database"),
            # Backward-compat alias: oudere kaartversies lezen "devices"
            "devices": [
                {
                    "name":         d.get("name", "Unknown"),
                    "device_type":  d.get("device_type", "unknown"),
                    "type":         d.get("device_type", "unknown"),
                    "state":        "on",
                    "running":      True,
                    "power_w":      round(d.get("current_power", 0), 1),
                    "confidence":   round(d.get("confidence", 0) * 100, 0),
                    "phase":        d.get("phase", "L1"),
                    "phase_label":  d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3\u2205",
                    "source":       d.get("source", "database"),
                    "source_type":  {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "confirmed":    d.get("confirmed", False),
                }
                for d in running
            ],
        }


class CloudEMSNILMRunningDevicesPowerSensor(CoordinatorEntity, SensorEntity):
    """
    State = total power of all detected running devices (W).
    Attributes contain a per-device power breakdown — suitable for
    energy breakdown dashboard cards.
    """
    _attr_name = "CloudEMS NILM · Running Devices Power"
    _attr_icon = ICON_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_running_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _running(self) -> list:
        return [d for d in (self.coordinator.data or {}).get("nilm_devices", []) if d.get("is_on")]

    @property
    def native_value(self):
        return round(sum(d.get("current_power", 0) for d in self._running), 1)

    @property
    def extra_state_attributes(self):
        running = self._running
        return {
            "devices": [
                {
                    "name":        d.get("name", "Unknown"),
                    "type":        d.get("device_type", "unknown"),
                    "power_w":     round(d.get("current_power", 0), 1),
                    "confirmed":   d.get("confirmed", False),
                    "confidence":  round(d.get("confidence", 0) * 100, 0),
                    # v1.17: fase + bron
                    "phase":       d.get("phase", "L1"),
                    "phase_label": d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3∅",
                    "source":      d.get("source", "database"),
                    "source_type": {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "state":       "on",
                    "running":     True,
                }
                for d in sorted(running, key=lambda x: x.get("current_power", 0), reverse=True)
            ],
        }


class CloudEMSNILMTopDeviceSensor(CoordinatorEntity, SensorEntity):
    """
    Nth most power-hungry NILM device currently running — for dashboard gauges.

    State = power in Watt of the Nth highest-consuming active device.
    Attributes contain its name, type, confidence and phase.

    Use 5 of these (rank 1–5) in an entities card or horizontal-stack
    to always see your top power consumers at a glance, sorted high→low.
    Returns None (unavailable) when fewer than N devices are active.
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_NILM

    def __init__(self, coord, entry, rank: int):
        super().__init__(coord)
        self._entry = entry
        self._rank  = rank
        self._attr_name      = f"CloudEMS NILM · Top {rank} Device"
        self._attr_unique_id = f"{entry.entry_id}_nilm_top_{rank}"

    @property
    def device_info(self): return _device_info(self._entry)

    def _sorted_running(self) -> list:
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        running = [d for d in devices if d.get("is_on") and d.get("current_power", 0) > 0]
        return sorted(running, key=lambda x: x.get("current_power", 0), reverse=True)

    @property
    def native_value(self):
        top = self._sorted_running()
        if len(top) >= self._rank:
            return round(top[self._rank - 1].get("current_power", 0), 1)
        return None

    @property
    def extra_state_attributes(self):
        top = self._sorted_running()
        if len(top) >= self._rank:
            d = top[self._rank - 1]
            return {
                "name":       d.get("name", d.get("device_type", "Unknown")),
                "type":       d.get("device_type", "unknown"),
                "confirmed":  d.get("confirmed", False),
                "confidence": round(d.get("confidence", 0) * 100, 1),
                "phase":      d.get("phase", "unknown"),
                "rank":       self._rank,
                "total_running": len(top),
            }
        return {"rank": self._rank, "name": None, "total_running": len(top)}


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — AI / NILM status sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSAIStatusSensor(CoordinatorEntity, SensorEntity):
    """
    Shows the active AI provider and self-learning status.
    Helps users understand which AI backend is running and how well
    the system has learned so far.
    """
    _attr_name = "CloudEMS AI · Status"
    _attr_icon = "mdi:robot"
    # Note: NOT DIAGNOSTIC — users need to see this to understand NILM state

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ai_status"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("nilm_mode", "database")

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        ai = d.get("ai_status", {})
        return {
            "provider":           d.get("nilm_mode", "database"),
            "api_calls_total":    ai.get("call_count", 0),
            "provider_available": ai.get("available", True),
            "confidence_threshold_pct": round(ai.get("min_confidence", 0.65) * 100, 0),
            "devices_confirmed":  ai.get("confirmed_count", 0),
            "devices_total":      ai.get("total_devices", 0),
            "solar_learning": {
                "profiles":      ai.get("solar_profiles", 0),
                "total_peak_w":  ai.get("solar_peak_w", 0),
                "estimated_kwp": round(ai.get("solar_peak_w", 0) / 1000, 2),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.6.0 — EPEX today all-hours price sensor (for dashboard charts)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEPEXTodaySensor(CoordinatorEntity, SensorEntity):
    """
    State  = current EPEX spot price (EUR/kWh).
    Attributes contain the full list of today's hourly prices — ideal for
    a Lovelace ApexCharts card or custom:plotly-graph.

    Example attribute value:
        today_prices: [{hour: 0, price: 0.082}, {hour: 1, price: 0.071}, ...]
    """
    _attr_name = "CloudEMS Energy · EPEX Today"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_epex_today"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("energy_price", {}).get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        today_all = ep.get("today_all", [])
        tomorrow_all = ep.get("tomorrow_all", [])
        cur = ep.get("current")
        avg = ep.get("avg_today")
        return {
            "today_prices":       today_all,
            "tomorrow_prices":    tomorrow_all,
            "tomorrow_available": ep.get("tomorrow_available", False),
            "next_hours":         ep.get("next_hours", []),
            "min_today":          ep.get("min_today"),
            "max_today":          ep.get("max_today"),
            "avg_today":          avg,
            "is_cheap_now":       (cur < avg) if (cur is not None and avg is not None) else None,
            "is_negative":        ep.get("is_negative", False),
            "cheapest_hour_1":    ep.get("cheapest_hour_1"),
            "cheapest_hour_2":    ep.get("cheapest_hour_2"),
            "cheapest_hour_3":    ep.get("cheapest_hour_3"),
            "cheapest_2h_start":  ep.get("cheapest_2h_start"),
            "cheapest_3h_start":  ep.get("cheapest_3h_start"),
            "cheapest_4h_start":  ep.get("cheapest_4h_start"),
            "data_source":        ep.get("source", "unknown"),
            "country":            ep.get("country", ""),
            "slot_count":         ep.get("slot_count", 0),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.7.0 — NILM Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMDiagSensor(CoordinatorEntity, SensorEntity):
    """
    NILM diagnostics sensor — shows exactly what the detector is doing.

    State  = classification success rate (%)
    Attributes contain:
      - Total events detected / classified / missed
      - Per-phase baseline power (what NILM thinks is always-on load)
      - Last 20 power events with timestamps, delta W and classification result
      - Power threshold and debounce settings

    Use this to diagnose WHY NILM is or isn't detecting devices:
      - Is the threshold too high? (small appliances missed)
      - Is baseline drifting? (noisy grid)
      - Are events classified but below confidence threshold?
    """
    _attr_name = "CloudEMS NILM · Diagnostics"
    _attr_icon = "mdi:stethoscope"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_diag"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        return diag.get("classification_rate_pct", 0.0)

    @property
    def extra_state_attributes(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        # v1.16.1: limit recent_events to 10 entries with essential fields only (16 KB recorder limit)
        raw_events = diag.get("recent_events", [])
        slim_events = [
            {
                "ts":        e.get("ts", ""),
                "phase":     e.get("phase", ""),
                "delta_w":   e.get("delta_w", 0),
                "result":    e.get("result", ""),
            }
            for e in raw_events[:10]
        ]
        return {
            # Summary counters
            "events_total":            diag.get("events_total", 0),
            "events_classified":       diag.get("events_classified", 0),
            "events_missed":           diag.get("events_missed", 0),
            "classification_rate_pct": diag.get("classification_rate_pct", 0.0),
            # Last event info
            "last_event_ts":       diag.get("last_event_ts"),
            "last_event_delta_w":  diag.get("last_event_delta_w", 0.0),
            "last_match":          diag.get("last_match", ""),
            # Per-phase baselines — shows what NILM sees as always-on load
            "baseline_l1_w":  diag.get("baselines_w", {}).get("L1", 0.0),
            "baseline_l2_w":  diag.get("baselines_w", {}).get("L2", 0.0),
            "baseline_l3_w":  diag.get("baselines_w", {}).get("L3", 0.0),
            # Device counts
            "devices_known":     diag.get("devices_known", 0),
            "devices_confirmed": diag.get("devices_confirmed", 0),
            "ai_mode":           diag.get("ai_mode", "database"),
            # Settings
            "power_threshold_w": diag.get("power_threshold_w", 25),
            "debounce_s":        diag.get("debounce_s", 2.0),
            # Recent event log (last 10, trimmed)
            "recent_events":     slim_events,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — PID Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPIDDiagSensor(CoordinatorEntity, SensorEntity):
    """
    Toont de live toestand van alle PID-regelaars in CloudEMS:
      - Fase-begrenzing PID (L1/L2/L3)
      - EV-laadstroom PID
      - Auto-tune status

    State = EV PID huidige uitgang in Ampere (handig als quick-view).
    Attributen bevatten de volledige PID-toestand per controller.
    """
    _attr_name = "CloudEMS System · PID Diagnostics"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "A"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pid_diag"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        ev = (self.coordinator.data or {}).get("ev_pid_state", {})
        return ev.get("last_output_a")

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        ev   = data.get("ev_pid_state", {})
        ph   = data.get("phase_pid_states", {})

        def _pid_attrs(d: dict) -> dict:
            if not d: return {}
            return {
                "kp": d.get("kp"), "ki": d.get("ki"), "kd": d.get("kd"),
                "setpoint":    d.get("setpoint"),
                "integral":    d.get("integral"),
                "last_error":  d.get("last_error"),
                "last_output": d.get("last_output"),
                "last_state":  d.get("last_state"),
            }

        return {
            "ev_pid":         _pid_attrs(ev),
            "ev_target_grid_w":   ev.get("target_grid_w"),
            "ev_auto_tuner":  ev.get("auto_tuner"),
            "phase_pids":     {phase: _pid_attrs(pstate) for phase, pstate in ph.items()},
            "pid_settings": {
                "phase_kp": self.coordinator._config.get("pid_phase_kp"),
                "phase_ki": self.coordinator._config.get("pid_phase_ki"),
                "phase_kd": self.coordinator._config.get("pid_phase_kd"),
                "ev_kp":    self.coordinator._config.get("pid_ev_kp"),
                "ev_ki":    self.coordinator._config.get("pid_ev_ki"),
                "ev_kd":    self.coordinator._config.get("pid_ev_kd"),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — NILM Sensor Input sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMInputSensor(CoordinatorEntity, SensorEntity):
    """
    Laat zien welke sensoren NILM gebruikt als invoer.

    State = invoermodus ('per_phase' / 'total_split' / 'total_l1')
    Attributen tonen per fase de gebruikte bron en de adaptieve drempel.

    Gebruik dit om snel te zien of NILM de beste data krijgt:
      per_phase   → ideaal: aparte stroomsensoren per fase
      total_split → OK: totaal netverbruik gelijkmatig verdeeld
      total_l1    → basis: enkelfasig, alles via L1
    """
    _attr_name = "CloudEMS NILM · Sensor Input"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_input"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        inputs = diag.get("sensor_inputs", {})
        # If all phases use per_phase → best mode
        modes = set(inputs.values())
        if "per_phase" in modes and len(modes) == 1:
            return "per_phase"
        if "total_split" in modes:
            return "total_split"
        if "total_l1" in modes:
            return "total_l1"
        return "unknown"

    @property
    def extra_state_attributes(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        thresh = diag.get("adaptive_threshold", {})
        return {
            "sensor_per_phase": diag.get("sensor_inputs", {}),
            "adaptive_threshold_w":   thresh.get("threshold_w"),
            "threshold_adapted":      thresh.get("adapted", False),
            "noise_p80_w":            thresh.get("noise_p80_w"),
            "threshold_samples":      thresh.get("samples", 0),
            "recommendation": (
                "✅ Per-fase sensoren actief — beste NILM nauwkeurigheid"
                if self.native_value == "per_phase"
                else "⚠️ Geen fase-sensoren — voeg stroomsensoren (A) per fase toe voor betere NILM"
                if self.native_value in ("total_split", "total_l1")
                else "❓ NILM invoer onbekend"
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — CO2 Intensity sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCO2Sensor(CoordinatorEntity, SensorEntity):
    """
    Huidige CO2-intensiteit van het elektriciteitsnet (gCO2/kWh).

    State = huidige intensiteit in gCO2eq/kWh.
    Attributen tonen of het netwerk groen of vuil is, en de databron.

    Gebruikt automatisch de beste beschikbare bron:
      1. Electricity Maps (gratis, geen API-sleutel nodig)
      2. CO2 Signal API (gratis token)
      3. Statisch Europees gemiddelde (EEA 2023, altijd beschikbaar)

    Gebruik in automaties:
      - Verschuif EV-laden naar groene uren (< 200 gCO2/kWh)
      - Toon CO2-besparingen van zelfopwekking
    """
    _attr_name = "CloudEMS Net · CO2 Intensiteit"
    _attr_icon = "mdi:molecule-co2"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "g/kWh"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_co2_intensity"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("co2_info", {}).get("current_gco2_kwh")

    @property
    def extra_state_attributes(self):
        info = (self.coordinator.data or {}).get("co2_info", {})
        return {
            "label":            info.get("label"),
            "is_green":         info.get("is_green"),
            "is_dirty":         info.get("is_dirty"),
            "source":           info.get("source"),
            "is_live":          info.get("is_live"),
            "country":          info.get("country"),
            "static_default_g": info.get("static_default_g"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — Energy Cost Forecast sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCostForecastSensor(CoordinatorEntity, SensorEntity):
    """
    Verwachte energiekosten voor vandaag en morgen.

    State = verwachte totale dagkosten vandaag (EUR).
    Attributen tonen reeds betaalde kosten, resterende verwachting en morgen.

    Het model leert jouw verbruikspatroon per uur en wordt steeds nauwkeuriger
    naarmate het meer dagen meet. Na ~5 dagen is het bruikbaar, na 14+ dagen
    betrouwbaar.

    Gebruik in dashboards:
      - "Vandaag naar verwachting €{state}" kaart
      - Vergelijk met gisteren/vorige week
    """
    _attr_name = "CloudEMS Energie · Kosten Verwachting"
    _attr_icon = "mdi:currency-eur"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cost_forecast"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cost_forecast", {}).get("today_forecast_eur")

    @property
    def extra_state_attributes(self):
        fc = (self.coordinator.data or {}).get("cost_forecast", {})
        return {
            "today_actual_eur":     fc.get("today_actual_eur"),
            "today_remaining_eur":  fc.get("today_remaining_eur"),
            "tomorrow_forecast_eur":fc.get("tomorrow_forecast_eur"),
            "today_kwh_actual":     fc.get("today_kwh_actual"),
            "model_trained":        fc.get("model_trained"),
            "trained_hours":        fc.get("trained_hours"),
            "mape_pct":             fc.get("mape_pct"),
            "peak_consumption_hour":fc.get("peak_consumption_hour"),
            # hourly_patterns useful for ApexCharts
            "hourly_patterns":      fc.get("hourly_patterns", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — Battery EPEX Schedule sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBatteryScheduleSensor(CoordinatorEntity, SensorEntity):
    """
    Huidige batterij-actie op basis van EPEX-schema.

    State = huidige actie ('charge' / 'discharge' / 'idle').
    Attributen tonen het volledige schema voor vandaag.

    Gebruik in dashboards:
      - Toon planning als tabel / tijdlijn
      - Trigger automaties op basis van batterij-actie
    """
    _attr_name = "CloudEMS Batterij · EPEX Schema"
    _attr_icon = "mdi:battery-clock"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_schedule"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("battery_schedule", {}).get("action", "idle")

    @property
    def extra_state_attributes(self):
        bs = (self.coordinator.data or {}).get("battery_schedule", {})
        return {
            "action":           bs.get("action"),
            "reason":           bs.get("reason"),
            "soc_pct":          bs.get("soc_pct"),
            "schedule_date":    bs.get("schedule_date"),
            "schedule":         bs.get("schedule", []),
            "charge_hours":     bs.get("charge_hours"),
            "discharge_hours":  bs.get("discharge_hours"),
            "plan_accuracy_pct":bs.get("plan_accuracy_pct"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.10.2 — Solar Intelligence: per-inverter profile + system overview
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSSolarSystemSensor(CoordinatorEntity, SensorEntity):
    """
    Fleet-wide solar intelligence overview.

    State = total current PV production (W).
    Attributes expose the combined learned knowledge across all inverters:
      - Total estimated panel capacity (Wp)
      - All-time peak production (W)
      - How many inverters are confident / learning
      - Whether any inverter is clipping right now
      - Total orientation learning progress (%)

    This is the 'wow' sensor: shows what the system has learned automatically
    without any manual configuration.
    """
    _attr_name = "CloudEMS Solar · System Intelligence"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_system"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _invs(self) -> list:
        return (self.coordinator.data or {}).get("inverter_data", [])

    @property
    def native_value(self):
        return round(sum(i.get("current_w", 0) for i in self._invs), 1) or None

    @property
    def extra_state_attributes(self):
        invs = self._invs
        total_wp    = sum(i.get("estimated_wp", 0) for i in invs)
        total_peak  = sum(i.get("peak_w", 0) for i in invs)
        n_confident = sum(1 for i in invs if i.get("confident"))
        n_orient    = sum(1 for i in invs if i.get("orientation_confident"))
        clipping_any = any(i.get("clipping") for i in invs)
        avg_orient_pct = (
            round(sum(i.get("orientation_learning_pct", 0) for i in invs) / len(invs))
            if invs else 0
        )
        phases_known = {i.get("label"): i.get("phase") for i in invs if i.get("phase_certain")}
        return {
            "inverter_count":         len(invs),
            "total_estimated_wp":     round(total_wp, 0),
            "total_peak_w":           round(total_peak, 1),
            "inverters_confident":    n_confident,
            "inverters_orient_known": n_orient,
            "clipping_active":        clipping_any,
            "orientation_progress_pct": avg_orient_pct,
            "phases_detected":        phases_known,
            "inverters": [
                {
                    "label":                    i.get("label"),
                    "current_w":                i.get("current_w"),
                    "peak_w":                   i.get("peak_w"),
                    "peak_w_7d":                i.get("peak_w_7d"),
                    "rated_power_w":            i.get("rated_power_w"),
                    "clipping_ceiling_w":       i.get("clipping_ceiling_w"),
                    "utilisation_pct":          i.get("utilisation_pct"),
                    "estimated_wp":             i.get("estimated_wp"),
                    "azimuth_compass":          i.get("azimuth_compass"),
                    "azimuth_learned":          i.get("azimuth_learned"),
                    "tilt_deg":                 i.get("tilt_deg"),
                    "tilt_learned":             i.get("tilt_learned"),
                    "phase":                    i.get("phase"),
                    "phase_certain":            i.get("phase_certain"),
                    "phase_display":            i.get("phase_display"),
                    "phase_confidence":         i.get("phase_confidence", 0.0),
                    "phase_provisional":        i.get("phase_provisional", True),
                    "clipping":                 i.get("clipping"),
                    "orientation_confident":    i.get("orientation_confident"),
                    "clear_sky_samples":        i.get("clear_sky_samples"),
                    "orientation_samples_needed": i.get("orientation_samples_needed"),
                }
                for i in invs
            ],
        }


class CloudEMSInverterProfileSensor(CoordinatorEntity, SensorEntity):
    """
    Deep solar intelligence for a single PV inverter.

    State = current power (W).

    Attributes show everything the system has learned automatically:
      • Peak Wp estimate (no nameplate needed!)
      • Phase detection via current correlation + vote counts
      • Azimuth & tilt (manual override OR self-learned from yield curve)
      • Compass direction label (Z, ZZW, etc.)
      • Per-hour yield fraction curve (for visualisation)
      • Peak production hour of the day
      • Orientation learning progress (%)
      • Clipping detection
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, inv_entity_id: str):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_entity_id
        self._attr_unique_id = f"{entry.entry_id}_inv_profile_{inv_entity_id}"

    @property
    def device_info(self): return _device_info(self._entry)

    def _inv(self) -> dict:
        for i in (self.coordinator.data or {}).get("inverter_data", []):
            if i.get("entity_id") == self._inv_id:
                return i
        return {}

    @property
    def name(self):
        label = self._inv().get("label") or self._inv_id
        return f"CloudEMS Solar · {label} Profiel"

    @property
    def native_value(self):
        return self._inv().get("current_w")

    @property
    def extra_state_attributes(self):
        i = self._inv()
        az = i.get("azimuth_deg")
        az_l = i.get("azimuth_learned")
        ti = i.get("tilt_deg")
        ti_l = i.get("tilt_learned")
        confident = i.get("orientation_confident", False)
        n_samples = i.get("clear_sky_samples", 0)

        # Effective values: manual config > learned > None
        az_eff = az if az is not None else az_l
        ti_eff = ti if ti is not None else ti_l

        if az is not None and az != az_l:
            az_source = "manueel"
        elif az_l is not None:
            az_source = "bevestigd" if confident else f"voorlopig ({n_samples} metingen)"
        else:
            az_source = "onbekend"

        if ti is not None and ti != ti_l:
            ti_source = "manueel"
        elif ti_l is not None:
            ti_source = "bevestigd" if confident else f"voorlopig ({n_samples} metingen)"
        else:
            ti_source = "onbekend"

        # Compass label for provisional azimuth
        def _az_compass(deg):
            if deg is None:
                return "onbekend"
            dirs = ["N","NNO","NO","ONO","O","OZO","ZO","ZZO","Z","ZZW","ZW","WZW","W","WNW","NW","NNW"]
            return dirs[round(deg / 22.5) % 16]

        az_compass = i.get("azimuth_compass") or _az_compass(az_eff)
        votes = i.get("phase_votes") or {}
        total_v = i.get("phase_total_votes", 0) or 1
        return {
            # Power & utilisation
            "utilisation_pct":        i.get("utilisation_pct"),
            "clipping":               i.get("clipping", False),
            "clipping_ceiling_w":     i.get("clipping_ceiling_w"),
            "rated_power_w":          i.get("rated_power_w"),
            "peak_w_alltime":         i.get("peak_w"),
            "peak_w_7d":              i.get("peak_w_7d"),
            "estimated_wp":           i.get("estimated_wp"),
            # Orientation
            "azimuth_deg":            az_eff,
            "azimuth_learned":        az_l,
            "azimuth_source":         az_source,
            "azimuth_compass":        az_compass,
            "tilt_deg":               ti_eff,
            "tilt_learned":           ti_l,
            "tilt_source":            ti_source,
            "orientation_confident":  i.get("orientation_confident", False),
            "clear_sky_days":         i.get("clear_sky_samples", 0),
            "clear_sky_days_needed":  i.get("orientation_samples_needed", 30),
            "orientation_progress_pct": i.get("orientation_learning_pct", 0),
            "peak_production_hour":   i.get("peak_production_hour"),
            "hourly_yield_fraction":  i.get("hourly_yield_fraction", {}),
            # Phase
            "phase":                  i.get("phase", "unknown"),
            "phase_certain":          i.get("phase_certain", False),
            "phase_vote_l1_pct":      round(votes.get("L1", 0) / total_v * 100, 0),
            "phase_vote_l2_pct":      round(votes.get("L2", 0) / total_v * 100, 0),
            "phase_vote_l3_pct":      round(votes.get("L3", 0) / total_v * 100, 0),
            "phase_total_votes":      i.get("phase_total_votes", 0),
            # Learning
            "learning_samples":       i.get("samples", 0),
            "learning_confident":     i.get("confident", False),
        }


class CloudEMSInverterClippingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    ON when an inverter is actively clipping (panels generate more than inverter capacity).
    Use in automations or alerts: dim the inverter, alert the user, or log for diagnostics.
    """
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:solar-panel"

    def __init__(self, coord, entry, inv_entity_id: str):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_entity_id
        self._attr_unique_id = f"{entry.entry_id}_inv_clipping_{inv_entity_id}"

    @property
    def device_info(self): return _device_info(self._entry)

    def _inv(self) -> dict:
        for i in (self.coordinator.data or {}).get("inverter_data", []):
            if i.get("entity_id") == self._inv_id:
                return i
        return {}

    @property
    def name(self):
        label = self._inv().get("label") or self._inv_id
        return f"CloudEMS Solar · {label} Clipping"

    @property
    def is_on(self) -> bool:
        return bool(self._inv().get("clipping", False))

    @property
    def extra_state_attributes(self):
        i = self._inv()
        return {
            "current_w":       i.get("current_w"),
            "peak_w":          i.get("peak_w"),
            "utilisation_pct": i.get("utilisation_pct"),
            "estimated_wp":    i.get("estimated_wp"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.10.3 — Self-learning Intelligence Sensors (zero-config)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSHomeBaselineSensor(CoordinatorEntity, SensorEntity):
    """
    State = current deviation from learned normal (W, positive = more than usual).
    Anomaly = True when consuming significantly more than the learned pattern.

    Attributes contain the full picture: expected, current, standby baseline,
    occupancy inference, and standby-hunters (always-on wasters).
    """
    _attr_name      = "CloudEMS Home Baseline Anomalie"  # slug → sensor.cloudems_home_baseline_anomalie
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:home-lightning-bolt-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_home_baseline"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _bl(self) -> dict:
        return (self.coordinator.data or {}).get("baseline", {})

    @property
    def native_value(self):
        return self._bl.get("deviation_w", 0.0)

    @property
    def extra_state_attributes(self):
        b = self._bl
        return {
            "anomaly":           b.get("anomaly", False),
            "current_w":         b.get("current_w"),
            "expected_w":        b.get("expected_w"),
            "deviation_w":       b.get("deviation_w"),
            "sigma_w":           b.get("sigma_w"),
            "sigma_threshold":   b.get("sigma_threshold", 2.5),
            "standby_w":         b.get("standby_w"),
            "standby_samples":   b.get("standby_samples"),
            "is_home":           b.get("is_home"),
            "model_ready":       b.get("model_ready", False),
            "trained_slots":     b.get("trained_slots", 0),
            "total_slots":       168,
            "training_pct":      round(b.get("trained_slots", 0) / 168 * 100, 0),
            "standby_hunters":   b.get("standby_hunters", []),
        }


class CloudEMSOccupancyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    ON when home consumption indicates someone is probably home.
    Derived purely from power: no motion sensors, no GPS, no phone tracking.
    Confidence increases as the standby baseline is refined.
    """
    _attr_name        = "CloudEMS Aanwezigheid (op basis van stroom)"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon        = "mdi:home-account"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_occupancy"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("baseline", {}).get("is_home", False))

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        return {
            "current_w":     b.get("current_w"),
            "standby_w":     b.get("standby_w"),
            "model_ready":   b.get("model_ready", False),
            "method":        "power_based",
        }


class CloudEMSAnomalyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    ON when power consumption is significantly above the learned normal for
    this time of day and weekday. Useful for alerts and automations.
    """
    _attr_name        = "CloudEMS Verbruik Anomalie"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon        = "mdi:alert-circle-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_anomaly"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("baseline", {}).get("anomaly", False))

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        return {
            "current_w":    b.get("current_w"),
            "expected_w":   b.get("expected_w"),
            "deviation_w":  b.get("deviation_w"),
            "sigma_w":      b.get("sigma_w"),
            "model_ready":  b.get("model_ready", False),
        }


class CloudEMSStandbyHunterSensor(CoordinatorEntity, SensorEntity):
    """
    State = estimated always-on standby load (W).
    Attributes list individual appliances that appear to never switch off
    during deep-night hours — candidates for energy waste.
    """
    _attr_name = "CloudEMS Standby Verbruik (Altijd Aan)"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:power-sleep"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_standby_hunter"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("baseline", {}).get("standby_w")

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        hunters = b.get("standby_hunters", [])
        return {
            "standby_w":       b.get("standby_w"),
            "standby_samples": b.get("standby_samples", 0),
            "suspicious_devices": hunters,
            "suspicious_count":   len(hunters),
            "tip": "Apparaten die 's nachts meer verbruiken dan de standby-drempel — controleer of ze uit kunnen.",
        }


class CloudEMSEVSessionSensor(CoordinatorEntity, SensorEntity):
    """
    State = predicted kWh for the next EV charging session (learned from history).
    When a session is active, state = kWh loaded so far.

    Attributes include typical schedule, cost history, and current session info.
    """
    _attr_name = "CloudEMS EV · Sessie Leermodel"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_session"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _ev(self) -> dict:
        return (self.coordinator.data or {}).get("ev_session", {})

    @property
    def native_value(self):
        ev = self._ev
        if ev.get("session_active"):
            return ev.get("session_kwh_so_far", 0.0)
        return ev.get("predicted_kwh")

    @property
    def extra_state_attributes(self):
        ev = self._ev
        return {
            "session_active":       ev.get("session_active", False),
            "session_current_a":    ev.get("session_current_a"),
            "session_kwh_so_far":   ev.get("session_kwh_so_far"),
            "session_cost_so_far":  ev.get("session_cost_so_far"),
            "predicted_kwh":        ev.get("predicted_kwh"),
            "predicted_duration_h": ev.get("predicted_duration_h"),
            "typical_start_hour":   ev.get("typical_start_hour"),
            "typical_weekdays":     ev.get("typical_weekdays", []),
            "sessions_total":       ev.get("sessions_total", 0),
            "model_ready":          ev.get("model_ready", False),
            "avg_cost_per_session": ev.get("avg_cost_per_session"),
            "recent_sessions":      ev.get("recent_sessions", []),
        }


class CloudEMSNILMScheduleSensor(CoordinatorEntity, SensorEntity):
    """
    State = number of NILM devices with a reliable learned schedule.
    Attributes contain the full schedule summary per device:
    which weekday + hour they typically run.
    """
    _attr_name = "CloudEMS NILM · Apparaat Schemas"
    _attr_icon = "mdi:calendar-clock"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_schedule"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _schedules(self) -> list:
        return (self.coordinator.data or {}).get("nilm_schedule", [])

    @property
    def native_value(self) -> int:
        return sum(1 for s in self._schedules if s.get("ready"))

    @property
    def extra_state_attributes(self):
        schedules = self._schedules
        # Flag any devices running at unusual times right now
        unusual = [
            d for d in (self.coordinator.data or {}).get("nilm_devices", [])
            if d.get("schedule_unusual")
        ]
        return {
            "schedules":         [
                # v1.16.1: only summary fields — hourly_pattern excluded (too large for recorder)
                {k: v for k, v in s.items() if k != "hourly_pattern"}
                for s in schedules
            ],
            "total_devices":     len(schedules),
            "schedules_ready":   sum(1 for s in schedules if s.get("ready")),
            "unusual_now":       [d.get("name", d.get("device_type")) for d in unusual],
            "unusual_count":     len(unusual),
        }


class CloudEMSWeatherCalibrationSensor(CoordinatorEntity, SensorEntity):
    """
    State = overall weather calibration factor (actual / open-meteo-expected).
    <1.0 means the installation produces less than the model expects
    (e.g. partial shading, non-optimal tilt).
    >1.0 means it over-performs (e.g. cooler climate, very clean panels).

    After ~30 sunny days this calibration makes the PV forecast significantly
    more accurate than a generic irradiance model.
    """
    _attr_name = "CloudEMS PV · Weerkalibratie"
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_weather_calibration"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def _calib(self) -> dict:
        return (self.coordinator.data or {}).get("weather_calibration", {})

    @property
    def native_value(self):
        invs = self._calib.get("inverters", [])
        factors = [i["calib_factor"] for i in invs if i.get("calib_factor") is not None]
        if not factors:
            return None
        return round(sum(factors) / len(factors), 3)

    @property
    def extra_state_attributes(self):
        c = self._calib
        return {
            "global_confident":  c.get("global_confident", False),
            "global_samples":    c.get("global_samples", 0),
            "samples_needed":    30,
            "progress_pct":      round(min(100, c.get("global_samples", 0) / 30 * 100), 0),
            "inverters":         c.get("inverters", []),
            "interpretation":    (
                "installatie presteert beter dan model verwacht" if (self.native_value or 1) > 1.05
                else "installatie presteert slechter dan model verwacht" if (self.native_value or 1) < 0.90
                else "installatie presteert conform model"
            ),
        }


class CloudEMSSolarROISensor(CoordinatorEntity, SensorEntity):
    """
    State = total euro saved / earned by the solar installation since CloudEMS
    started tracking (self-import saving + export revenue).

    Attributes show the daily/monthly rate and an extrapolated payback estimate.
    This requires no installation cost input — it simply tracks value generated.
    """
    _attr_name = "CloudEMS PV · Opbrengst & Terugverdientijd"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:cash-plus"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_roi"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        # Use cost tracking data as proxy for cumulative savings
        d = self.coordinator.data or {}
        cost_month = d.get("cost_month_eur", 0.0)
        # Export revenue estimate: export_kwh × avg_price
        price_info = d.get("energy_price") or {}
        avg_price  = price_info.get("avg_today") or 0.12
        invs = d.get("inverter_data", [])
        total_peak_w = sum(i.get("peak_w", 0) for i in invs)
        # Very rough: daily PV value ≈ peak_kWp × 3h_equivalent × avg_price
        if total_peak_w > 0:
            daily_eur = (total_peak_w / 1000) * 3.0 * avg_price
            return round(daily_eur, 2)
        return None

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        pi = d.get("energy_price") or {}
        avg_price = pi.get("avg_today") or 0.12
        invs = d.get("inverter_data", [])
        total_wp = sum(i.get("estimated_wp", 0) for i in invs)
        total_peak_w = sum(i.get("peak_w", 0) for i in invs)
        # Rough annual yield: kWp × 850 kWh (NL average)
        annual_kwh = (total_wp / 1000) * 850 if total_wp > 0 else None
        annual_eur = round(annual_kwh * avg_price, 0) if annual_kwh else None
        cf = d.get("cost_forecast") or {}
        return {
            "estimated_wp_total":      round(total_wp, 0),
            "peak_w_alltime":          round(total_peak_w, 1),
            "annual_yield_kwh_est":    round(annual_kwh, 0) if annual_kwh else None,
            "annual_value_eur_est":    annual_eur,
            "avg_price_eur_kwh":       round(avg_price, 4),
            "daily_forecast_cost_eur": cf.get("today_forecast_eur"),
            "monthly_cost_eur":        d.get("cost_month_eur"),
            "note": "Schatting op basis van gemeten piekvermogen × NL-gemiddeld zonuren × actuele EPEX prijs",
        }


# ══════════════════════════════════════════════════════════════════════════════
# v1.11.0 — 8 New Intelligence Sensors
# ══════════════════════════════════════════════════════════════════════════════

class CloudEMSThermalModelSensor(CoordinatorEntity, SensorEntity):
    """Thermische verliescoëfficiënt van het huis in W/°C."""
    _attr_name = "CloudEMS · Thermisch Huismodel"
    _attr_native_unit_of_measurement = "W/K"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_thermal_model"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        t = (self.coordinator.data or {}).get("thermal_model", {})
        v = t.get("w_per_k", 0.0)
        return round(v, 1) if v else None

    @property
    def extra_state_attributes(self):
        t = (self.coordinator.data or {}).get("thermal_model", {})
        return {
            "rating":              t.get("rating", "onbekend"),
            "advice":              t.get("advice", ""),
            "samples":             t.get("samples", 0),
            "samples_needed":      t.get("samples_needed", 20),
            "progress_pct":        t.get("progress_pct", 0),
            "reliable":            t.get("reliable", False),
            "heating_days":        t.get("heating_days", 0),
            "last_heating_w":      t.get("last_heating_w", 0),
            "last_outside_temp_c": t.get("last_outside_temp_c"),
            "benchmark_excellent": 100,
            "benchmark_good":      200,
            "benchmark_average":   350,
        }


class CloudEMSFlexScoreSensor(CoordinatorEntity, SensorEntity):
    """Beschikbaar flexibel vermogen in kW."""
    _attr_name = "CloudEMS · Flexibel Vermogen"
    _attr_native_unit_of_measurement = "kW"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_flex_score"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        f = (self.coordinator.data or {}).get("flex_score", {})
        return f.get("total_kw", 0.0)

    @property
    def extra_state_attributes(self):
        f = (self.coordinator.data or {}).get("flex_score", {})
        return {
            "battery_kw":   f.get("battery_kw", 0.0),
            "ev_kw":        f.get("ev_kw", 0.0),
            "boiler_kw":    f.get("boiler_kw", 0.0),
            "nilm_kw":      f.get("nilm_kw", 0.0),
            "breakdown":    f.get("breakdown", ""),
            "components":   f.get("components", []),
        }


class CloudEMSPVHealthSensor(CoordinatorEntity, SensorEntity):
    """PV paneel gezondheid — soiling en degradatie detectie."""
    _attr_name = "CloudEMS PV · Paneelgezondheid"
    _attr_icon = "mdi:solar-panel"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_health"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("pv_health", {})
        if p.get("any_alert"):
            return "alert"
        invs = p.get("inverters", [])
        if not invs:
            return "onbekend"
        avg_ratio = sum(i.get("ratio", 1.0) for i in invs) / len(invs)
        return f"{avg_ratio * 100:.0f}%"

    @property
    def extra_state_attributes(self):
        p = (self.coordinator.data or {}).get("pv_health", {})
        return {
            "any_alert":  p.get("any_alert", False),
            "summary":    p.get("summary", ""),
            "inverters":  p.get("inverters", []),
        }


class CloudEMSGasSensor(CoordinatorEntity, SensorEntity):
    """Gasverbruik meter (m³) uit P1 telegram."""
    _attr_name = "CloudEMS Gasstand"  # slug → sensor.cloudems_gasstand
    _attr_native_unit_of_measurement = "m³"
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.GAS
    _attr_icon = "mdi:fire"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_gas_m3"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        g = (self.coordinator.data or {}).get("gas_data", {})
        v = g.get("gas_m3", 0.0)
        return round(v, 3) if v else None

    @property
    def extra_state_attributes(self):
        g = (self.coordinator.data or {}).get("gas_data", {})
        return {
            "gas_kwh":           round(g.get("gas_kwh", 0.0), 3),
            "conversion_factor": 9.769,
            "source":            "P1 DSMR (OBIS 0-1:24.2.1)",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.13.0 — Energie bronvergelijking: elektriciteit vs. gas per kWh warmte
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEnergySourceSensor(CoordinatorEntity, SensorEntity):
    """
    Vergelijkt de actuele kosten van elektriciteit vs. gas per kWh warmte.

    Rekent gas om van €/m³ → €/kWh (calorische waarde 9,769 kWh/m³, NL-standaard)
    en houdt rekening met rendementen:
      - Gas CV-ketel:         90% rendement → effectief €/kWh = (€/m³ / 9,769) / 0,90
      - Elektrische boiler:   95% rendement (instelbaar)
      - Warmtepomp:           COP 3,5 (instelbaar)

    State = "elektriciteit" | "gas" | "gelijk"
    Gebruik dit voor automaties: verhit boiler via stroom als sensor = "elektriciteit".
    """
    _attr_name      = "CloudEMS · Goedkoopste Warmtebron"
    _attr_icon      = "mdi:heat-wave"
    _attr_device_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_source_compare"

    @property
    def device_info(self): return _device_info(self._entry)

    def _get_electricity_price(self) -> Optional[float]:
        """Current electricity price from EPEX sensor (€/kWh, incl. tax)."""
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return ep.get("current")

    def _get_gas_price_m3(self) -> float:
        """Gas price per m³. Try HA sensor first, then fixed config, then default."""
        cfg = self.coordinator._config
        # 1. HA sensor (energy provider app, DSMR, etc.)
        sensor_eid = cfg.get(CONF_GAS_PRICE_SENSOR, "")
        if sensor_eid:
            state = self.hass.states.get(sensor_eid)
            if state and state.state not in ("unavailable", "unknown", ""):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        # 2. Fixed value from config
        fixed = cfg.get(CONF_GAS_PRICE_FIXED, 0.0)
        if fixed and float(fixed) > 0:
            return float(fixed)
        # 3. Default NL indicative price
        return DEFAULT_GAS_PRICE_EUR_M3

    @property
    def native_value(self) -> Optional[str]:
        elec = self._get_electricity_price()
        if elec is None:
            return None

        gas_m3        = self._get_gas_price_m3()
        cfg           = self.coordinator._config
        boiler_eff    = float(cfg.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))
        hp_cop        = float(cfg.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))
        has_hp        = bool(cfg.get(CONF_HEAT_PUMP_ENTITY, ""))

        # Gas CV-ketel: €/kWh warmte
        gas_kwh_heat  = (gas_m3 / GAS_KWH_PER_M3) / GAS_BOILER_EFFICIENCY

        # Elektrische boiler (resistief, COP ≈ 1): altijd beschikbaar
        elec_boiler   = elec / boiler_eff

        # Warmtepomp: alleen meenemen als er een WP geconfigureerd is.
        # Zonder WP-entiteit berekenen we de kosten WEL voor de attributen (informatief),
        # maar baseren we de state NIET op de WP — dat zou misleidend zijn.
        elec_hp       = elec / hp_cop

        # Vergelijking: staat = goedkoopste BESCHIKBARE elektrische optie vs. gas
        if has_hp:
            best_elec_kwh    = min(elec_boiler, elec_hp)
            best_elec_source = "warmtepomp" if elec_hp <= elec_boiler else "elektrische_boiler"
        else:
            # Alleen resistief beschikbaar — vergelijk enkel boiler vs. gas
            best_elec_kwh    = elec_boiler
            best_elec_source = "elektrische_boiler"

        if best_elec_kwh < gas_kwh_heat * 0.98:
            return "elektriciteit"
        elif gas_kwh_heat < best_elec_kwh * 0.98:
            return "gas"
        else:
            return "gelijk"

    @property
    def extra_state_attributes(self) -> dict:
        elec = self._get_electricity_price()
        gas_m3 = self._get_gas_price_m3()
        cfg = self.coordinator._config
        boiler_eff = float(cfg.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))
        hp_cop     = float(cfg.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))
        has_hp     = bool(cfg.get(CONF_HEAT_PUMP_ENTITY, ""))

        gas_kwh_raw    = round(gas_m3 / GAS_KWH_PER_M3, 5)
        gas_kwh_heat   = round(gas_kwh_raw / GAS_BOILER_EFFICIENCY, 5)
        elec_boiler    = round(elec / boiler_eff, 5) if elec else None
        elec_hp        = round(elec / hp_cop, 5) if elec else None

        # Savings: positief = elektrisch goedkoper, negatief = gas goedkoper
        savings_boiler = round(gas_kwh_heat - elec_boiler, 5) if elec_boiler else None
        savings_hp     = round(gas_kwh_heat - elec_hp, 5) if elec_hp else None

        # Cheapest available electric source
        if has_hp and elec_hp and elec_boiler:
            cheapest_elec_source = "warmtepomp" if elec_hp <= elec_boiler else "elektrische_boiler"
            cheapest_elec_kwh    = min(elec_boiler, elec_hp)
        else:
            cheapest_elec_source = "elektrische_boiler"
            cheapest_elec_kwh    = elec_boiler

        # Recommendation: specific about WHICH option and WHY
        state = self.native_value
        if state == "elektriciteit":
            if cheapest_elec_source == "warmtepomp":
                recommendation = (
                    f"Warmtepomp is goedkoopst: €{elec_hp:.4f}/kWh warmte "
                    f"vs. gas €{gas_kwh_heat:.4f}/kWh — besparing {savings_hp*100:.1f} ct/kWh."
                )
            else:
                recommendation = (
                    f"Elektrische boiler is goedkoper dan gas: €{elec_boiler:.4f}/kWh warmte "
                    f"vs. gas €{gas_kwh_heat:.4f}/kWh — besparing {savings_boiler*100:.1f} ct/kWh."
                )
        elif state == "gas":
            if has_hp:
                cheapest_electric_str = f"warmtepomp €{elec_hp:.4f}" if elec_hp < elec_boiler else f"boiler €{elec_boiler:.4f}"
                recommendation = (
                    f"Gas is goedkoper: CV €{gas_kwh_heat:.4f}/kWh warmte "
                    f"vs. {cheapest_electric_str}/kWh — gebruik gas."
                )
            else:
                recommendation = (
                    f"Gas is goedkoper: CV €{gas_kwh_heat:.4f}/kWh warmte "
                    f"vs. elektrische boiler €{elec_boiler:.4f}/kWh — gebruik gas."
                )
        else:
            recommendation = "Elektriciteit en gas zijn nagenoeg even duur per kWh warmte."

        source_eid = cfg.get(CONF_GAS_PRICE_SENSOR, "")
        source = "sensor" if source_eid else ("config" if cfg.get(CONF_GAS_PRICE_FIXED) else "default")

        return {
            # Elektriciteit
            "elec_price_kwh":                 elec,
            "elec_boiler_per_kwh_heat":       elec_boiler,
            "elec_hp_per_kwh_heat":           elec_hp if has_hp else None,
            "electric_boiler_efficiency_pct": round(boiler_eff * 100),
            "heat_pump_cop":                  hp_cop if has_hp else None,
            "has_heat_pump":                  has_hp,
            "cheapest_electric_source":       cheapest_elec_source,
            # Gas
            "gas_price_m3":                   round(gas_m3, 4),
            "gas_kwh_per_m3":                 GAS_KWH_PER_M3,
            "gas_price_per_kwh_raw":          gas_kwh_raw,
            "gas_cv_efficiency_pct":          round(GAS_BOILER_EFFICIENCY * 100),
            "gas_per_kwh_heat":               gas_kwh_heat,
            "gas_price_source":               source,
            # Vergelijking
            "savings_electric_boiler_vs_gas": savings_boiler,
            "savings_heat_pump_vs_gas":       savings_hp if has_hp else None,
            "recommendation":                 recommendation,
        }


class CloudEMSSelfConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Zelfconsumptiegraad: % van PV-productie direct verbruikt."""
    _attr_name = "CloudEMS PV · Zelfconsumptiegraad"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_self_consumption"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        return sc.get("ratio_pct", None)

    @property
    def extra_state_attributes(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        return {
            "export_pct":         sc.get("export_pct"),
            "pv_today_kwh":       sc.get("pv_today_kwh"),
            "self_consumed_kwh":  sc.get("self_consumed_kwh"),
            "exported_kwh":       sc.get("exported_kwh"),
            "best_solar_hour":    sc.get("best_solar_hour"),
            "best_solar_label":   sc.get("best_solar_label"),
            "advice":             sc.get("advice", ""),
            "monthly_saving_eur": sc.get("monthly_saving_eur"),
        }


class CloudEMSDayTypeSensor(CoordinatorEntity, SensorEntity):
    """Dag-type classificatie: werkdag-thuis, kantoor, weekend, vakantie."""
    _attr_name = "CloudEMS · Dag-type Classificatie"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_day_type"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        dt = (self.coordinator.data or {}).get("day_type", {})
        return dt.get("today_type", "unknown")

    @property
    def extra_state_attributes(self):
        dt = (self.coordinator.data or {}).get("day_type", {})
        return {
            "today_label":        dt.get("today_label", "Onbekend"),
            "confidence":         dt.get("confidence", 0.0),
            "expected_kwh":       dt.get("expected_kwh"),
            "total_days_learned": dt.get("total_days_learned", 0),
            "advice":             dt.get("advice", ""),
        }


class CloudEMSDeviceDriftSensor(CoordinatorEntity, SensorEntity):
    """Apparaat efficiëntie drift detectie — slijtage, kalk, defect."""
    _attr_name = "CloudEMS · Apparaat Efficientiedrift"
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_device_drift"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("device_drift", {})
        if d.get("any_alert"):
            return "alert"
        if d.get("any_warning"):
            return "warning"
        devs = d.get("devices", [])
        return f"ok ({len(devs)} apparaten)" if devs else "geen data"

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("device_drift", {})
        return {
            "any_alert":    d.get("any_alert", False),
            "any_warning":  d.get("any_warning", False),
            "summary":      d.get("summary", ""),
            "trained_count":d.get("trained_count", 0),
            "total_count":  d.get("total_count", 0),
            "devices":     d.get("devices", []),
        }


class CloudEMSPhaseMigrationSensor(CoordinatorEntity, SensorEntity):
    """Fase-migratie advies voor betere fase-balans."""
    _attr_name = "CloudEMS · Fase-Migratie Advies"
    _attr_icon = "mdi:swap-horizontal-bold"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_phase_migration"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        pm = (self.coordinator.data or {}).get("phase_migration", {})
        if pm.get("has_advice"):
            top = (pm.get("advices") or [{}])[0]
            return (
                f"Verplaats {top.get('device_label','?')} "
                f"van {top.get('from_phase','?')} naar {top.get('to_phase','?')} "
                f"(+{top.get('balance_gain_pct',0):.0f}%)"
            )
        return pm.get("summary", "geen advies")

    @property
    def extra_state_attributes(self):
        pm = (self.coordinator.data or {}).get("phase_migration", {})
        return {
            "has_advice":       pm.get("has_advice", False),
            "summary":          pm.get("summary", ""),
            "overloaded_phase": pm.get("overloaded_phase"),
            "lightest_phase":   pm.get("lightest_phase"),
            "imbalance_a":      pm.get("imbalance_a", 0.0),
            "advices":          pm.get("advices", []),
        }


class CloudEMSMicroMobilitySensor(CoordinatorEntity, SensorEntity):
    """E-bike en scooter laadtracker voor het gezin."""
    _attr_name = "CloudEMS Micro-Mobiliteit"  # slug → sensor.cloudems_micro_mobiliteit
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:bicycle-electric"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_micro_mobility"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        m = (self.coordinator.data or {}).get("micro_mobility", {})
        return m.get("total_kwh", None)

    @property
    def extra_state_attributes(self):
        m = (self.coordinator.data or {}).get("micro_mobility", {})
        return {
            "vehicles_today":   m.get("vehicles_today", 0),
            "kwh_today":        m.get("kwh_today", 0.0),
            "cost_today_eur":   m.get("cost_today_eur", 0.0),
            "active_sessions":  m.get("active_sessions", []),
            "sessions_today":   m.get("sessions_today", []),
            "vehicle_profiles": m.get("vehicle_profiles", []),
            "best_charge_hour": m.get("best_charge_hour"),
            "advice":           m.get("advice", ""),
            "total_sessions":   m.get("total_sessions", 0),
            "weekly_kwh_avg":   m.get("weekly_kwh_avg", 0.0),
        }


class CloudEMSNotificationSensor(CoordinatorEntity, SensorEntity):
    """Telt actieve CloudEMS-meldingen en toont ze als attributen."""
    _attr_name = "CloudEMS · Actieve Meldingen"
    _attr_native_unit_of_measurement = "meldingen"
    _attr_icon = "mdi:bell-ring"
    _attr_state_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_notifications"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("notifications", {}).get("active_count", 0)

    @property
    def state_class(self):
        return None

    @property
    def extra_state_attributes(self):
        n = (self.coordinator.data or {}).get("notifications", {})
        return {
            "critical_count":  n.get("critical_count", 0),
            "warning_count":   n.get("warning_count", 0),
            "info_count":      n.get("info_count", 0),
            "muted_count":     n.get("muted_count", 0),
            "active_alerts":   n.get("active_alerts", []),
        }


class CloudEMSClippingLossSensor(CoordinatorEntity, SensorEntity):
    """Geschat financieel verlies door PV-clipping per jaar."""
    _attr_name = "CloudEMS · Clipping Verlies"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power-variant-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clipping_loss"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("clipping_loss", {}).get("total_kwh_lost_30d", None)

    @property
    def extra_state_attributes(self):
        c = (self.coordinator.data or {}).get("clipping_loss", {})
        return {
            "total_eur_lost_year":  c.get("total_eur_lost_year", 0.0),
            "worst_inverter":       c.get("worst_inverter", ""),
            "expansion_roi_years":  c.get("expansion_roi_years"),
            "any_curtailment":      c.get("any_curtailment", False),
            "inverters":            c.get("inverters", []),
            "advice":               c.get("advice", ""),
        }


class CloudEMSConsumptionCategoriesSensor(CoordinatorEntity, SensorEntity):
    """Verbruik uitgesplitst per categorie (verwarming, mobiliteit, wit goed, enz.)."""
    _attr_name = "CloudEMS Verbruik Categorien"  # slug → sensor.cloudems_verbruik_categorien
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-pie"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_consumption_categories"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("consumption_categories", {}).get("total_kwh_today", None)

    @property
    def extra_state_attributes(self):
        c = (self.coordinator.data or {}).get("consumption_categories", {})
        return {
            "total_kwh_today":   c.get("total_kwh_today", 0.0),   # v1.16 fix: was missing, dashboard showed 0.0
            "top_category":      c.get("top_category", ""),
            "top_category_pct":  c.get("top_category_pct", 0.0),
            "breakdown_pct":     c.get("breakdown_pct", {}),
            "breakdown_kwh":     c.get("breakdown_kwh", {}),
            "breakdown_w_now":   c.get("breakdown_w_now", {}),
            "total_w_now":       c.get("total_w_now", 0.0),
            "pie_data":          c.get("pie_data", []),
            "dominant_insight":  c.get("dominant_insight", ""),
            "avg_breakdown_pct": c.get("avg_breakdown_pct", {}),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.15.4: NEW HA Sensor entities voor absence/occupancy, climate preheat,
#          PV forecast accuracy, EMA diagnostics en sensor sanity guard.
#          Deze modules bestonden al in coordinator maar hadden geen HA entiteiten.
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSAbsenceDetectorSensor(CoordinatorEntity, SensorEntity):
    """Aanwezigheidsstatus via AbsenceDetector (verbruikspatroon-gebaseerd).
    
    Meldt: home / away / sleeping / vacation.
    Attributes: confidence, standby_w, vacation_hours, advice.
    """
    _attr_name  = "CloudEMS Occupancy"
    _attr_icon  = "mdi:home-account"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_absence_detector"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("occupancy", {}).get("state", "unknown")

    @property
    def extra_state_attributes(self):
        o = (self.coordinator.data or {}).get("occupancy", {})
        return {
            "confidence":     o.get("confidence", 0.0),
            "state":          o.get("state", "unknown"),
            "standby_w":      o.get("standby_w"),
            "vacation_hours": o.get("vacation_hours", 0),
            "advice":         o.get("advice", ""),
        }


class CloudEMSClimatePreheatSensor(CoordinatorEntity, SensorEntity):
    """Verwarmingsadvies van ClimatePreHeatAdvisor.
    
    Meldt: pre_heat / reduce / normal.
    Attributes: setpoint_offset_c, reason, price_ratio, w_per_k, reliable.
    """
    _attr_name  = "CloudEMS Climate Preheat"
    _attr_icon  = "mdi:thermometer-auto"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate_preheat"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("climate_preheat", {}).get("mode", "normal")

    @property
    def extra_state_attributes(self):
        p = (self.coordinator.data or {}).get("climate_preheat", {})
        return {
            "mode":              p.get("mode", "normal"),
            "setpoint_offset_c": p.get("setpoint_offset_c", 0.0),
            "reason":            p.get("reason", ""),
            "price_ratio":       p.get("price_ratio"),
            "w_per_k":           p.get("w_per_k"),
            "reliable":          p.get("reliable", False),
        }


class CloudEMSPVForecastAccuracySensor(CoordinatorEntity, SensorEntity):
    """PV prognose nauwkeurigheid (MAPE 14d / 30d, biasfactor).
    
    State = MAPE 14d in %.
    """
    _attr_name  = "CloudEMS PV Forecast Accuracy"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon  = "mdi:weather-sunny-alert"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_accuracy"

    @property
    def device_info(self): return _device_info(self._entry)

    @staticmethod
    def _acc_dict(raw) -> dict:
        """Normalise pv_accuracy to a plain dict.

        The coordinator now always returns a dict, but during the very first
        async_write_ha_state (called inside async_add_entities before the
        coordinator has run with the new code) the value may still be a
        PVAccuracyData dataclass from the initial coordinator run.
        This helper handles both cases gracefully.
        """
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        # PVAccuracyData dataclass — map fields to the expected dict keys
        return {
            "mape_14d_pct":      getattr(raw, "mape_14d", None),
            "mape_30d_pct":      getattr(raw, "mape_30d", None),
            "bias_factor":       getattr(raw, "bias_factor", None),
            "samples":           getattr(raw, "days_with_data", 0),
            "last_day_mape":     getattr(raw, "last_day_error_pct", None),
            "quality_label":     getattr(raw, "quality_label", None),
            "advice":            getattr(raw, "advice", None),
            "days_tracked":      getattr(raw, "days_tracked", 0),
            "calibration_month": getattr(raw, "calibration_month", None),
            "consecutive_over":  getattr(raw, "consecutive_over", 0),
            "consecutive_under": getattr(raw, "consecutive_under", 0),
            "monthly_bias":      getattr(raw, "monthly_bias", {}),
        }

    @property
    def native_value(self):
        a = self._acc_dict((self.coordinator.data or {}).get("pv_accuracy"))
        mape = a.get("mape_14d_pct")
        if mape is None:
            return None
        try:
            return round(float(mape), 1)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        a = self._acc_dict((self.coordinator.data or {}).get("pv_accuracy"))
        return {
            "mape_14d_pct":   a.get("mape_14d_pct"),
            "mape_30d_pct":   a.get("mape_30d_pct"),
            "bias_factor":    a.get("bias_factor"),
            "samples":        a.get("samples", 0),
            "last_day_mape":  a.get("last_day_mape"),
        }


class CloudEMSEMADiagnosticsSensor(CoordinatorEntity, SensorEntity):
    """EMA (Exponential Moving Average) diagnostiek voor vertraagde cloud-sensoren.
    
    State = totaal geblokkeerde spikes.
    Attributes: frozen_sensors, slow_sensors, spikes_blocked.
    """
    _attr_name  = "CloudEMS EMA Diagnostics"
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_icon  = "mdi:chart-bell-curve"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ema_diagnostics"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("ema_diagnostics", {}).get("spikes_blocked", 0)

    @property
    def extra_state_attributes(self):
        e = (self.coordinator.data or {}).get("ema_diagnostics", {})
        return {
            "spikes_blocked":  e.get("spikes_blocked", 0),
            "frozen_sensors":  e.get("frozen_sensors", []),
            "slow_sensors":    e.get("slow_sensors", []),
            "tracked_sensors": e.get("tracked_sensors", 0),
            "summary":         e.get("summary", ""),
        }


class CloudEMSSanitySensor(CoordinatorEntity, SensorEntity):
    """Sensor sanity guard — detecteert misconfigureerde sensoren (kW/W verwarring, te hoge waarden, enz.).
    
    State = totaal actieve issues.
    Attributes: issues (lijst), summary, has_critical, has_warning.
    """
    _attr_name  = "CloudEMS Sensor Sanity"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon  = "mdi:shield-check"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sensor_sanity"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        s = (self.coordinator.data or {}).get("sensor_sanity", {})
        issues = s.get("issues", [])
        return len(issues) if isinstance(issues, list) else 0

    @property
    def extra_state_attributes(self):
        s = (self.coordinator.data or {}).get("sensor_sanity", {})
        return {
            "has_critical": s.get("has_critical", False),
            "has_warning":  s.get("has_warning", False),
            "summary":      s.get("summary", "Alle sensoren OK"),
            "issues":       s.get("issues", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.16.0: Schaduwdetectie & Clipping-voorspelling
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSShadowDetectionSensor(CoordinatorEntity, SensorEntity):
    """Structurele schaduwdetectie per omvormer.

    State  = geschat totaal dagelijks verlies door schaduw (kWh).
    Attributes:
        any_shadow          — True als er schaduw gedetecteerd is
        summary             — leesbare samenvatting
        inverters           — per-omvormer details:
            label, shadowed_hours, partial_hours, direction,
            severity, lost_kwh_day_est, advice
    """
    _attr_name       = "CloudEMS Schaduwdetectie"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon       = "mdi:weather-partly-cloudy"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_shadow_detection"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        s = (self.coordinator.data or {}).get("shadow_detection", {})
        return s.get("total_lost_kwh_day", None)

    @property
    def extra_state_attributes(self):
        s = (self.coordinator.data or {}).get("shadow_detection", {})
        return {
            "any_shadow":    s.get("any_shadow", False),
            "summary":       s.get("summary", "Onvoldoende data voor schaduwanalyse."),
            "trained_hours": s.get("trained_hours", 0),
            "total_hours":   s.get("total_hours", 0),
            "progress_pct":  s.get("progress_pct", 0),
            "inverters":     s.get("inverters", []),
        }


class CloudEMSClippingForecastSensor(CoordinatorEntity, SensorEntity):
    """Clipping-voorspelling voor morgen op basis van PV-forecast en geleerde omvormergrens.

    State  = totaal verwacht geclipte energie morgen (kWh, som over alle omvormers).
    Attributes:
        forecasts           — per-omvormer:
            ceiling_w, predicted_clip_kwh, clipped_hours, advice
        total_clipped_kwh   — som over alle omvormers
        advice              — gecombineerd advies
    """
    _attr_name       = "CloudEMS Clipping Voorspelling Morgen"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon       = "mdi:solar-power-variant-outline"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clipping_forecast"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        forecasts = (
            (self.coordinator.data or {})
            .get("clipping_loss", {})
            .get("clipping_forecast_tomorrow", [])
        )
        if not forecasts:
            return None
        return round(sum(f.get("predicted_clip_kwh", 0.0) for f in forecasts), 2)

    @property
    def extra_state_attributes(self):
        forecasts = (
            (self.coordinator.data or {})
            .get("clipping_loss", {})
            .get("clipping_forecast_tomorrow", [])
        )
        total = round(sum(f.get("predicted_clip_kwh", 0.0) for f in forecasts), 2)
        # Combineer adviezen — toon alleen omvormers met verwachte clipping
        clipping_fcasts = [f for f in forecasts if f.get("predicted_clip_kwh", 0) > 0.05]
        if clipping_fcasts:
            advice = " | ".join(f.get("advice", "") for f in clipping_fcasts)
        elif forecasts:
            advice = "Geen significante clipping verwacht morgen."
        else:
            advice = "Onvoldoende data voor voorspelling."
        return {
            "forecasts":          forecasts,
            "total_clipped_kwh":  total,
            "advice":             advice,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.16.0 — Ollama AI Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSOllamaDiagSensor(CoordinatorEntity, SensorEntity):
    """Ollama health + NILM activity diagnostics.

    State  = online / offline / timeout / error / disabled
    Attributes:
        host, port, model              — configured Ollama endpoint
        active_model_found             — is the configured model loaded in Ollama?
        models_available               — list of all models Ollama reports
        last_check_ts                  — ISO timestamp of last health-check
        last_error                     — last error string, if any
        calls_total                    — number of NILM events sent to Ollama (session)
        calls_success                  — successful responses
        calls_failed                   — failed/timeout responses
        success_rate_pct               — success %
        last_success_ts                — ISO timestamp of last successful call
        last_response_ms               — last round-trip time (ms)
        avg_response_ms                — rolling average round-trip (ms)
        fallback_to_database           — True when Ollama is down and DB is used
        recent_calls                   — ring buffer last 20 Ollama queries
    """
    _attr_name  = "CloudEMS Ollama · Diagnostics"
    _attr_icon  = "mdi:head-cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ollama_diagnostics"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        health = (self.coordinator.data or {}).get("ollama_health", {})
        diag   = (self.coordinator.data or {}).get("ollama_diagnostics", {})
        if not diag.get("enabled"):
            return "disabled"
        return health.get("status", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        d      = self.coordinator.data or {}
        health = d.get("ollama_health", {})
        diag   = d.get("ollama_diagnostics", {})

        enabled     = diag.get("enabled", False)
        total       = diag.get("calls_total", 0)
        success     = diag.get("calls_success", 0)
        status      = health.get("status", "unknown")
        fallback    = enabled and status != "online"

        return {
            # Connection info
            "host":                 diag.get("host", "localhost"),
            "port":                 diag.get("port", 11434),
            "model":                diag.get("model", "llama3"),
            "active_model_found":   health.get("active_model_found", False),
            "models_available":     health.get("models_available", []),
            "last_check_ts":        health.get("last_check_ts"),
            "last_error":           health.get("last_error") or diag.get("last_error"),
            # Call stats
            "calls_total":          total,
            "calls_success":        success,
            "calls_failed":         diag.get("calls_failed", 0),
            "success_rate_pct":     diag.get("success_rate_pct", 0.0),
            "last_success_ts":      diag.get("last_success_ts"),
            "last_response_ms":     diag.get("last_response_ms", 0),
            "avg_response_ms":      diag.get("avg_response_ms", 0),
            # Fallback indicator
            "fallback_to_database": fallback,
            "nilm_active_mode":     d.get("nilm_mode", "database"),
            # Recent activity
            "recent_calls":         diag.get("recent_calls", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.17.0 — Hybride NILM sensor (ankers + weer + diagnostics)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSHybridNILMSensor(CoordinatorEntity, SensorEntity):
    """
    Toont de status van de Hybride NILM-laag:
      • Aantal actieve smart-plug ankers
      • Actuele buitentemperatuur (voor contextpriors)
      • Seizoen
      • Statistieken: enrich-calls, anchor hits, prior boosts/penalties, fase-hints
    """
    _attr_name       = "CloudEMS NILM · Hybride Status"
    _attr_icon       = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_hybrid_nilm"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("hybrid_nilm", {})
        return d.get("anchors_active", 0)

    @property
    def native_unit_of_measurement(self): return "ankers"

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("hybrid_nilm", {})
        stats = d.get("stats", {})
        return {
            "anchors_total":           d.get("anchors_total", 0),
            "anchors_active":          d.get("anchors_active", 0),
            "weather_temperature_c":   d.get("weather_temperature_c"),
            "weather_season":          d.get("weather_season"),
            "weather_irradiance_w":    d.get("weather_irradiance_w"),
            "weather_sensors":         d.get("weather_sensors", []),
            "anchors":                 d.get("anchors", []),
            # stats
            "stat_enrich_calls":       stats.get("enrich_calls", 0),
            "stat_anchor_hits":        stats.get("anchor_hits", 0),
            "stat_prior_boosts":       stats.get("prior_boosts", 0),
            "stat_prior_penalties":    stats.get("prior_penalties", 0),
            "stat_phase_balance_hints":stats.get("phase_balance_hints", 0),
            "stat_discoveries":        stats.get("discoveries", 0),
        }
