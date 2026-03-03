"""CloudEMS number platform — stroom-limiters per fase en PID-tuning."""
# Copyright (c) 2024-2025 CloudEMS - https://cloudems.eu
from __future__ import annotations
import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, MANUFACTURER, ATTRIBUTION, DEFAULT_MAX_CURRENT, ALL_PHASES,
    DEFAULT_PID_PHASE_KP, DEFAULT_PID_PHASE_KI, DEFAULT_PID_PHASE_KD,
    DEFAULT_PID_EV_KP, DEFAULT_PID_EV_KI, DEFAULT_PID_EV_KD,
    DEFAULT_PRICE_THRESHOLD_CHEAP, DEFAULT_NILM_THRESHOLD_W,
)
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)


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


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — PID tuning number entities
# ═══════════════════════════════════════════════════════════════════════════════

def _add_pid_entities(coordinator, entry, entities: list) -> None:
    """Add PID tuning number entities for phase limiter and EV charger."""
    from .const import (
        DEFAULT_PID_PHASE_KP, DEFAULT_PID_PHASE_KI, DEFAULT_PID_PHASE_KD,
        DEFAULT_PID_EV_KP, DEFAULT_PID_EV_KI, DEFAULT_PID_EV_KD,
        DEFAULT_PRICE_THRESHOLD_CHEAP, DEFAULT_NILM_THRESHOLD_W,
    )
    entities += [
        # Phase PID
        CloudEMSPIDNumber(coordinator, entry, "pid_phase_kp",
                          "CloudEMS Fase PID · Kp", DEFAULT_PID_PHASE_KP, 0.1, 20.0, 0.1,
                          "mdi:tune", "phase_pid_kp"),
        CloudEMSPIDNumber(coordinator, entry, "pid_phase_ki",
                          "CloudEMS Fase PID · Ki", DEFAULT_PID_PHASE_KI, 0.0, 5.0, 0.01,
                          "mdi:tune-variant", "phase_pid_ki"),
        CloudEMSPIDNumber(coordinator, entry, "pid_phase_kd",
                          "CloudEMS Fase PID · Kd", DEFAULT_PID_PHASE_KD, 0.0, 5.0, 0.01,
                          "mdi:tune-vertical", "phase_pid_kd"),
        # EV PID
        CloudEMSPIDNumber(coordinator, entry, "pid_ev_kp",
                          "CloudEMS EV PID · Kp", DEFAULT_PID_EV_KP, 0.001, 1.0, 0.001,
                          "mdi:ev-plug-type2", "ev_pid_kp"),
        CloudEMSPIDNumber(coordinator, entry, "pid_ev_ki",
                          "CloudEMS EV PID · Ki", DEFAULT_PID_EV_KI, 0.0, 0.5, 0.001,
                          "mdi:ev-plug-type2", "ev_pid_ki"),
        CloudEMSPIDNumber(coordinator, entry, "pid_ev_kd",
                          "CloudEMS EV PID · Kd", DEFAULT_PID_EV_KD, 0.0, 0.5, 0.001,
                          "mdi:ev-plug-type2", "ev_pid_kd"),
        # Price threshold
        CloudEMSPIDNumber(coordinator, entry, "price_threshold_cheap",
                          "CloudEMS Prijs · Goedkoop drempel", DEFAULT_PRICE_THRESHOLD_CHEAP,
                          0.0, 0.5, 0.005,
                          "mdi:currency-eur", "price_threshold"),
        # NILM sensitivity
        CloudEMSPIDNumber(coordinator, entry, "nilm_threshold_w",
                          "CloudEMS NILM · Gevoeligheid (W)", DEFAULT_NILM_THRESHOLD_W,
                          5.0, 150.0, 1.0,
                          "mdi:motion-sensor", "nilm_threshold"),
    ]


# Patch async_setup_entry to include PID entities
_original_setup = async_setup_entry


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        CloudEMSPhaseCurrentLimiter(coordinator, entry, phase)
        for phase in ALL_PHASES
    ]
    entities.append(CloudEMSEVCurrentTarget(coordinator, entry))
    _add_pid_entities(coordinator, entry, entities)
    async_add_entities(entities)


class CloudEMSPIDNumber(CoordinatorEntity, NumberEntity):
    """
    Instelbaar getal voor PID-parameters en drempelwaarden.
    
    Wijzigingen worden direct doorgegeven aan het bijbehorende subsysteem
    zodat het gedrag live aanpast zonder HA-herstart.
    """
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, config_key: str, name: str,
                 default: float, min_val: float, max_val: float, step: float,
                 icon: str, uid_suffix: str):
        super().__init__(coordinator)
        self._entry      = entry
        self._config_key = config_key
        self._default    = default
        self._current    = default
        self._attr_unique_id  = f"{entry.entry_id}_{uid_suffix}"
        self._attr_name       = name
        self._attr_icon       = icon
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step      = step
        self._attr_entity_category  = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": MANUFACTURER,
        }

    @property
    def native_value(self) -> float:
        # Read from coordinator config first, then default
        return float(self.coordinator._config.get(self._config_key, self._default))

    async def async_set_native_value(self, value: float) -> None:
        self._current = value
        # Write into live coordinator config
        self.coordinator._config[self._config_key] = value
        # Apply live to relevant subsystem
        self._apply_live(value)
        self.async_write_ha_state()
        _LOGGER.info("CloudEMS %s → %.4f", self._config_key, value)

    def _apply_live(self, value: float) -> None:
        """Apply the new value to the running subsystem immediately."""
        coord = self.coordinator
        key   = self._config_key
        try:
            if key.startswith("pid_phase_") and coord._multi_inv_manager:
                # Update all phase PIDs
                mgr = coord._multi_inv_manager
                kp  = float(coord._config.get("pid_phase_kp", DEFAULT_PID_PHASE_KP))
                ki  = float(coord._config.get("pid_phase_ki", DEFAULT_PID_PHASE_KI))
                kd  = float(coord._config.get("pid_phase_kd", DEFAULT_PID_PHASE_KD))
                for pid in mgr._phase_pids.values():
                    pid.kp = kp; pid.ki = ki; pid.kd = kd
            elif key.startswith("pid_ev_") and coord._ev_pid:
                kp = float(coord._config.get("pid_ev_kp", DEFAULT_PID_EV_KP))
                ki = float(coord._config.get("pid_ev_ki", DEFAULT_PID_EV_KI))
                kd = float(coord._config.get("pid_ev_kd", DEFAULT_PID_EV_KD))
                coord._ev_pid.set_pid_params(kp, ki, kd)
            elif key == "price_threshold_cheap" and coord._dynamic_loader:
                coord._dynamic_loader.update_threshold(value)
        except Exception as err:
            _LOGGER.warning("CloudEMS PID live update [%s] mislukt: %s", key, err)
