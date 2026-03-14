# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS number platform — stroom-limiters per fase en PID-tuning."""
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
from .sub_devices import sub_device_info, SUB_PV_DIMMER, SUB_SHUTTER
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)


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


# ── Definitieve setup (9 vaste dimmer-slots) ─────────────────────────────────
# De eerste async_setup_entry definitie hierboven wordt overschreven door deze.
# We definiëren hem opnieuw zodat altijd precies 9 slider-slots worden aangemaakt,
# ongeacht hoeveel omvormers geconfigureerd zijn. Slots zonder omvormer zijn unavailable.


class CloudEMSShutterSetpoint(CoordinatorEntity, NumberEntity):
    """Instelbaar temperatuur-setpoint per rolluik."""

    _attr_attribution         = ATTRIBUTION
    _attr_native_min_value    = 10.0
    _attr_native_max_value    = 30.0
    _attr_native_step         = 0.5
    _attr_native_unit_of_measurement = "°C"
    _attr_mode                = NumberMode.SLIDER
    _attr_icon                = "mdi:thermometer"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry,
                 shutter_entity_id: str, label: str, default_setpoint: float) -> None:
        super().__init__(coordinator)
        self._entry           = entry
        self._shutter_eid     = shutter_entity_id
        self._default         = default_setpoint
        self._current         = default_setpoint

        safe_id = shutter_entity_id.split(".")[-1].replace("-", "_")
        self._attr_unique_id  = f"{entry.entry_id}_shutterv2_{safe_id}_setpoint"
        self._attr_name       = f"CloudEMS Rolluik {label} Setpoint"
        self._attr_device_info = sub_device_info(entry, SUB_SHUTTER)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Herstel opgeslagen waarde via state machine
        last = self.hass.states.get(self.entity_id)
        if last and last.state not in ("unknown", "unavailable", ""):
            try:
                self._current = float(last.state)
            except (ValueError, TypeError):
                pass
        self._push_to_controller()

    @property
    def native_value(self) -> float:
        return self._current

    async def async_set_native_value(self, value: float) -> None:
        self._current = value
        self._push_to_controller()
        self.async_write_ha_state()

    def _push_to_controller(self) -> None:
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return
        sc.set_default_setpoint(self._shutter_eid, self._current)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    from .const import CONF_INVERTER_CONFIGS
    _inv_cfg_src = {**entry.data, **entry.options}
    inv_cfgs = _inv_cfg_src.get(CONF_INVERTER_CONFIGS, [])
    entities = [
        CloudEMSPhaseCurrentLimiter(coordinator, entry, phase)
        for phase in ALL_PHASES
    ]
    entities.append(CloudEMSEVCurrentTarget(coordinator, entry))
    _add_pid_entities(coordinator, entry, entities)
    # Altijd 9 dimmer-slider slots — unavailable als slot niet geconfigureerd is
    for slot in range(1, 10):
        inv_cfg = inv_cfgs[slot - 1] if slot <= len(inv_cfgs) else None
        entities.append(CloudEMSInverterDimSlider(coordinator, entry, slot, inv_cfg))
    # Shutter setpoint entiteiten
    from .const import CONF_SHUTTER_CONFIGS, CONF_SHUTTER_COUNT
    cfg_src = {**entry.data, **entry.options}
    shutter_count = int(cfg_src.get(CONF_SHUTTER_COUNT, 0))
    shutter_configs = cfg_src.get(CONF_SHUTTER_CONFIGS, [])
    for sh in shutter_configs:
        eid   = sh.get("entity_id", "")
        label = sh.get("label", eid.split(".")[-1])
        if not eid:
            continue
        entities.append(CloudEMSShutterSetpoint(
            coordinator, entry, eid, label,
            float(sh.get("default_setpoint", 20.0)),
        ))
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


# ═══════════════════════════════════════════════════════════════════════════════
# v1.24.0 — Per-inverter solar dimmer slider
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInverterDimSlider(CoordinatorEntity, NumberEntity):
    """Zonnedimmer slider voor omvormer slot 1-9.

    Altijd aangemaakt voor alle 9 slots. Slots zonder geconfigureerde omvormer
    zijn unavailable en worden verborgen in HA. Zo blijven entity_ids stabiel
    ongeacht herconfiguratie — geen losse entities per omvormer nodig.
    """
    _attr_attribution            = ATTRIBUTION
    _attr_native_min_value       = 0.0
    _attr_native_max_value       = 100.0
    _attr_native_step            = 1.0
    _attr_native_unit_of_measurement = "%"
    _attr_mode                   = NumberMode.SLIDER
    _attr_icon                   = "mdi:solar-power-variant"
    # Geconfigureerde slots zichtbaar; lege slots verborgen totdat omvormer geconfigureerd is
    _attr_entity_registry_enabled_default = True  # overschreven in __init__ als leeg slot

    def __init__(
        self,
        coordinator: "CloudEMSCoordinator",
        entry: "ConfigEntry",
        slot: int,            # 1-9
        inv_cfg: dict | None, # None = slot niet geconfigureerd
    ) -> None:
        super().__init__(coordinator)
        self._slot    = slot
        self._inv_cfg = inv_cfg
        self._inv_eid = inv_cfg.get("entity_id", "") if inv_cfg else ""
        label = inv_cfg.get("label", f"Omvormer {slot}") if inv_cfg else f"Omvormer {slot}"
        self._attr_unique_id = f"{entry.entry_id}_inv_dim_slider_{slot}"
        self._attr_name      = f"CloudEMS PV Dimmer {label}"
        self.entity_id       = f"number.cloudems_zonnedimmer_{slot}"
        self._entry = entry
        # Verberg lege slots in de entity registry totdat ze geconfigureerd worden
        if not self._inv_eid:
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_PV_DIMMER)

    @property
    def available(self) -> bool:
        """Alleen beschikbaar als dit slot een geconfigureerde omvormer heeft."""
        return bool(self._inv_eid)

    @property
    def native_value(self) -> float:
        if not self._inv_eid:
            return 100.0
        mgr = self.coordinator._multi_inv_manager
        if mgr is None:
            return 100.0
        state = mgr.get_dimmer_state(self._inv_eid)
        manual = state.get("manual_pct")
        return manual if manual is not None else state.get("current_pct", 100.0)

    async def async_set_native_value(self, value: float) -> None:
        if not self._inv_eid:
            return
        mgr = self.coordinator._multi_inv_manager
        if mgr is None:
            return
        mgr.set_manual_dim(self._inv_eid, None if value >= 99.9 else value)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        base = {
            "slot":        self._slot,
            "inverter_id": self._inv_eid or None,
            "label":       self._inv_cfg.get("label") if self._inv_cfg else None,
        }
        if not self._inv_eid:
            return base
        mgr = self.coordinator._multi_inv_manager
        if mgr is None:
            return base
        return {**base, **mgr.get_dimmer_state(self._inv_eid)}
