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
    ]

    phases = ["L1","L2","L3"] if phase_count == 3 else ["L1"]
    for ph in phases:
        entities.append(CloudEMSPhaseCurrentSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseVoltageSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhasePowerSensor(coordinator, entry, ph))

    if phase_count == 3:
        entities.append(CloudEMSPhaseBalanceSensor(coordinator, entry))

    # Per-inverter sensors (peak, clipping, forecast)
    for inv in inv_cfgs:
        entities.append(CloudEMSInverterSensor(coordinator, entry, inv))

    # EPEX cheap-hour binary sensors
    for rank in [1, 2, 3]:
        entities.append(CloudEMSCheapHourBinarySensor(coordinator, entry, rank))

    async_add_entities(entities)

    # Dynamically add NILM device sensors when detected
    registered_nilm_ids: set = set()

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
        return d.get("power_w") or d.get("grid_power_w")

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
        text = (self.coordinator.data or {}).get("insights", "")
        # HA state max 255 chars — show first tip only
        if text and " | " in text:
            return text.split(" | ")[0][:255]
        return (text or "Bezig met laden...")[:255]

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
            "peak_power_w":    d.get("peak_w", 0),
            "estimated_wp":    d.get("estimated_wp", 0),
            "utilisation_pct": d.get("utilisation_pct", 0),
            "clipping":        d.get("clipping", False),
            "phase":           d.get("phase","unknown"),
            "phase_certain":   d.get("phase_certain", False),
            "samples":         d.get("samples", 0),
            "confident":       d.get("confident", False),
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
        return {
            "devices":         devices,
            "active_mode":     d.get("nilm_mode","database"),
            "confirmed_count": sum(1 for dv in devices if dv.get("confirmed")),
            "pending_count":   sum(1 for dv in devices if dv.get("pending")),
            "active_count":    sum(1 for dv in devices if dv.get("is_on")),
            "total_power_w":   sum(dv.get("current_power",0) for dv in devices if dv.get("is_on")),
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
    def extra_state_attributes(self):
        dev = self._dev
        if not dev:
            return {}
        return {
            "device_id":        dev.device_id,
            "device_type":      dev.display_type,
            "is_on":            dev.is_on,
            "confidence_pct":   round(dev.effective_confidence * 100, 1),
            "source":           dev.source,
            "confirmed":        dev.confirmed,
            "user_feedback":    dev.user_feedback,
            "phase":            dev.phase,
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
        p = (self.coordinator.data or {}).get("energy_price", {}).get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "is_negative":    ep.get("is_negative", False),
            "is_cheap":       ep.get("is_cheap_hour", False),
            "rank_today":     ep.get("rank_today"),
            "min_today":      ep.get("min_today"),
            "max_today":      ep.get("max_today"),
            "avg_today":      ep.get("avg_today"),
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
                    "name":       d.get("name", "Unknown"),
                    "type":       d.get("device_type", "unknown"),
                    "confirmed":  d.get("confirmed", False),
                    "confidence": round(d.get("confidence", 0) * 100, 0),
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
                    "name":       d.get("name", "Unknown"),
                    "type":       d.get("device_type", "unknown"),
                    "power_w":    round(d.get("current_power", 0), 1),
                    "confirmed":  d.get("confirmed", False),
                    "confidence": round(d.get("confidence", 0) * 100, 0),
                }
                for d in sorted(running, key=lambda x: x.get("current_power", 0), reverse=True)
            ],
        }


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
            # Recent event log (last 20)
            "recent_events":     diag.get("recent_events", []),
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
