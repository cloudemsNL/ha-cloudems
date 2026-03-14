# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.


"""
CloudEMS — Virtuele Boiler Water Heater (v2.0.0)

Maakt één water_heater entity per geconfigureerde boiler aan in HA.
Gebruikt WaterHeaterEntity (zelfde platform-type als Ariston Lydos Hybrid),
zodat de UI en het entity-type overeenstemmen met de werkelijke hardware.

Entity-ID patroon:  water_heater.cloudems_boiler_<slug>
                    bijv. water_heater.cloudems_boiler_ariston_lydos

Copyright 2025-2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sub_devices import sub_device_info, SUB_BOILER

_LOGGER = logging.getLogger(__name__)

# ── Operatiemodus definities ──────────────────────────────────────────────────
OP_AUTO       = "auto"
OP_MANUAL     = "manual"
OP_ECO        = "eco"
OP_BOOST      = "boost"
OP_LEGIONELLA = "legionella"
OP_STALL      = "stall"

BOILER_OPERATIONS = [OP_AUTO, OP_MANUAL, OP_ECO, OP_BOOST, OP_LEGIONELLA, OP_STALL]

MANUAL_OVERRIDE_S = 4 * 3600   # 4 uur


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Registreer één water_heater entity per geconfigureerde boiler."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    boiler_ctrl = getattr(coordinator, "_boiler_ctrl", None)
    if not boiler_ctrl:
        _LOGGER.debug("CloudEMS virtual_boiler: geen boiler_ctrl — geen entities aangemaakt")
        return

    all_boilers = list(getattr(boiler_ctrl, "_boilers", [])) + [
        b for g in getattr(boiler_ctrl, "_groups", []) for b in g.boilers
    ]

    if not all_boilers:
        status_list = (coordinator.data or {}).get("boiler_status", [])
        if not status_list:
            _LOGGER.debug("CloudEMS virtual_boiler: geen boilers geconfigureerd")
            return
        _LOGGER.debug(
            "CloudEMS virtual_boiler: boiler_ctrl._boilers leeg, "
            "gebruik boiler_status uit data (%d items)",
            len(status_list),
        )

    entities = [
        CloudEMSBoilerWaterHeater(coordinator, entry, boiler)
        for boiler in all_boilers
    ]

    async_add_entities(entities, update_before_add=True)
    _LOGGER.info(
        "CloudEMS virtual_boiler: %d virtuele boiler water_heater(s) aangemaakt: %s",
        len(entities),
        [e.entity_id for e in entities],
    )

    try:
        from .entity_device_log import get_entity_device_log
        log = get_entity_device_log(hass, entry)
        if log:
            for e in entities:
                log.register("water_heater", e.entity_id, e.unique_id, "virtual_boiler")
    except Exception:
        pass


class CloudEMSBoilerWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    """
    Virtuele water heater voor één CloudEMS-gestuurde boiler.

    Zelfde entity-type als Ariston Lydos Hybrid, zodat de UI klopt.
    Operatiemodi: auto (CloudEMS), manual (4u override), eco, boost,
    legionella, stall (informatief — door CloudEMS gezet).
    """

    _attr_has_entity_name    = False
    _attr_temperature_unit   = UnitOfTemperature.CELSIUS
    _attr_min_temp           = 30.0
    _attr_max_temp           = 75.0
    _attr_precision          = 1.0
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator, entry: ConfigEntry, boiler) -> None:
        super().__init__(coordinator)
        self._entry   = entry
        self._boiler  = boiler
        slug          = _slugify(boiler.label or boiler.entity_id.split(".")[-1])
        self._attr_unique_id = f"{entry.entry_id}_vboiler_{boiler.entity_id}"
        self._attr_name      = f"CloudEMS \u00b7 {boiler.label}"
        self.entity_id       = f"water_heater.cloudems_boiler_{slug}"

        self._override_until:    float        = 0.0
        self._override_setpoint: float | None = None
        self._original_setpoint: float        = boiler.setpoint_c
        self._current_op:        str          = OP_AUTO

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_BOILER)

    def _boiler_status(self) -> dict | None:
        for b in (self.coordinator.data or {}).get("boiler_status", []):
            if b.get("entity_id") == self._boiler.entity_id:
                return b
        return None

    @property
    def operation_list(self) -> list[str]:
        return BOILER_OPERATIONS

    @property
    def current_operation(self) -> str:
        st = self._boiler_status()
        if not st:
            return self._current_op

        # Stall en legionella zijn informatieve states van CloudEMS — altijd tonen
        if st.get("stall_active", False):
            return OP_STALL
        temp = st.get("temp_c")
        if temp and temp >= 65.0 and st.get("is_on", False) and self._current_op == OP_AUTO:
            return OP_LEGIONELLA

        # Gebruikerskeuze heeft altijd prioriteit: auto/manual/eco tonen wat de gebruiker koos
        # Niet overschrijven met actual_mode (boost/green) — dat is interne CloudEMS staat
        return self._current_op

    @property
    def current_temperature(self) -> float | None:
        st = self._boiler_status()
        if st:
            return st.get("temp_c")
        return self._boiler.current_temp_c

    @property
    def target_temperature(self) -> float | None:
        if self._override_until > time.time() and self._override_setpoint is not None:
            return self._override_setpoint
        st = self._boiler_status()
        if st:
            sp = st.get("active_setpoint_c") or st.get("setpoint_c")
            return sp if sp else self._boiler.setpoint_c
        return self._boiler.active_setpoint_c or self._boiler.setpoint_c

    @property
    def max_temp(self) -> float:
        hw = getattr(self._boiler, "hardware_max_c", 0.0) or 0.0
        if hw > 0:
            return hw
        boost_max = getattr(self._boiler, "max_setpoint_boost_c", 0.0) or 0.0
        if boost_max > 0:
            return boost_max
        return 75.0

    @property
    def extra_state_attributes(self) -> dict:
        st = self._boiler_status() or {}
        attrs: dict[str, Any] = {
            "entity_id":           self._boiler.entity_id,
            "boiler_type":         st.get("boiler_type", self._boiler.boiler_type),
            "control_mode":        st.get("control_mode", self._boiler.control_mode),
            "power_w":             st.get("power_w", 0.0),
            "cycle_kwh":           st.get("cycle_kwh", 0.0),
            "is_heating":          st.get("is_heating", False),
            "is_on":               st.get("is_on", False),
            "actual_mode":         st.get("actual_mode", ""),
            "stall_active":        st.get("stall_active", False),
            "legionella_days":     st.get("legionella_days"),
            "cop_at_current_temp": st.get("cop_at_current_temp"),
            "thermal_loss_c_h":    st.get("thermal_loss_c_h", 0.0),
        }
        if self._override_until > time.time():
            remaining_min = round((self._override_until - time.time()) / 60)
            attrs["override_remaining_min"] = remaining_min
            attrs["override_setpoint_c"]    = self._override_setpoint
        else:
            attrs["override_remaining_min"] = 0
            attrs["override_setpoint_c"]    = None
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp = float(temp)
        # v4.6.23: als CloudEMS al actief BOOST/ECO stuurt, sla setpoint op als
        # permanent nieuw streefpunt (geen tijdelijke 4u-override, want de boiler
        # wordt toch al door CloudEMS beheerd). Dit zorgt dat het dashboard-setpoint
        # zichtbaar verandert en bij de volgende cyclus actief wordt.
        st = self._boiler_status() or {}
        actual_mode = st.get("actual_mode", "").lower()
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        if actual_mode in ("boost", "green", "eco"):
            # CloudEMS in native preset-modus: sla op + stuur direct naar echte boiler
            _LOGGER.info(
                "CloudEMS VirtualBoiler [%s]: setpoint bijgewerkt naar %.1f°C (manual override)",
                self._boiler.label, temp,
            )
            if ctrl:
                ctrl.set_manual_override(self._boiler.entity_id, temp, MANUAL_OVERRIDE_S)
                async def _send_manual_sp():
                    try:
                        await ctrl.send_now(self._boiler.entity_id, True, temp)
                    except Exception as _err:
                        _LOGGER.warning("VirtualBoiler send_now (manual sp) fout: %s", _err)
                self.hass.async_create_task(_send_manual_sp())
            self._override_setpoint = temp
            self._override_until    = time.time() + MANUAL_OVERRIDE_S
            self._current_op        = OP_MANUAL
            self.async_write_ha_state()
            return
        _LOGGER.info(
            "CloudEMS VirtualBoiler [%s]: handmatige setpoint-override → %.1f°C (4u)",
            self._boiler.label, temp,
        )
        if self._override_until == 0.0:
            self._original_setpoint = self._boiler.setpoint_c
        self._override_setpoint = temp
        self._override_until    = time.time() + MANUAL_OVERRIDE_S
        self._current_op        = OP_MANUAL
        if ctrl:
            ctrl.set_manual_override(self._boiler.entity_id, temp, MANUAL_OVERRIDE_S)
            async def _send_now_safe():
                try:
                    await ctrl.send_now(self._boiler.entity_id, True, temp)
                except Exception as _err:
                    _LOGGER.warning("VirtualBoiler send_now fout: %s", _err)
            self.hass.async_create_task(_send_now_safe())
        self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        _LOGGER.info(
            "CloudEMS VirtualBoiler [%s]: operation_mode \u2192 %s",
            self._boiler.label, operation_mode,
        )
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        if operation_mode == OP_AUTO:
            # Auto = CloudEMS neemt volledig over: hef boost-pauze op
            self._override_until    = 0.0
            self._override_setpoint = None
            self._current_op        = OP_AUTO
            if ctrl:
                ctrl.resume_boost(self._boiler.entity_id)
                ctrl.clear_manual_override(self._boiler.entity_id)
                ctrl.update_setpoint(self._boiler.entity_id, self._original_setpoint)
        elif operation_mode == OP_ECO:
            # ECO = pauzeer BOOST voor 4 uur → CloudEMS blijft in GREEN/ECO
            self._override_until    = 0.0
            self._override_setpoint = None
            self._current_op        = OP_ECO
            if ctrl:
                ctrl.pause_boost(self._boiler.entity_id, seconds=4 * 3600)
        elif operation_mode == OP_MANUAL:
            if self._override_until == 0.0:
                self._original_setpoint = self._boiler.setpoint_c
            self._override_until = time.time() + MANUAL_OVERRIDE_S
            self._current_op     = OP_MANUAL
            # v4.6.26: direct commando sturen zodat de echte boiler meteen reageert
            if ctrl:
                sp = self._override_setpoint or self._boiler.setpoint_c
                async def _send_now_safe_op():
                    try:
                        await ctrl.send_now(self._boiler.entity_id, True, sp)
                    except Exception as _err:
                        _LOGGER.warning("VirtualBoiler send_now (op_mode) fout: %s", _err)
                self.hass.async_create_task(_send_now_safe_op())
        elif operation_mode == OP_BOOST:
            # BOOST = forceer maximale temperatuur voor 4 uur
            if self._override_until == 0.0:
                self._original_setpoint = self._boiler.setpoint_c
            self._override_until = time.time() + MANUAL_OVERRIDE_S
            self._current_op     = OP_BOOST
            if ctrl:
                ctrl.force_boost_once(self._boiler.entity_id, seconds=MANUAL_OVERRIDE_S)
                async def _send_boost():
                    try:
                        sp = self._boiler.max_setpoint_boost_c or self._boiler.hw_ceiling
                        await ctrl.send_now(self._boiler.entity_id, True, sp)
                    except Exception as _err:
                        _LOGGER.warning("VirtualBoiler send_now (boost) fout: %s", _err)
                self.hass.async_create_task(_send_boost())
        elif operation_mode == OP_LEGIONELLA:
            # LEGIONELLA = forceer cyclus op ≥65°C voor 2 uur
            if self._override_until == 0.0:
                self._original_setpoint = self._boiler.setpoint_c
            self._override_until = time.time() + 2 * 3600
            self._current_op     = OP_LEGIONELLA
            if ctrl:
                ctrl.force_legionella(self._boiler.entity_id)
                async def _send_leg():
                    try:
                        leg_sp = max(65.0, self._boiler.max_setpoint_boost_c or 65.0)
                        await ctrl.send_now(self._boiler.entity_id, True, leg_sp)
                    except Exception as _err:
                        _LOGGER.warning("VirtualBoiler send_now (legionella) fout: %s", _err)
                self.hass.async_create_task(_send_leg())
        elif operation_mode == OP_STALL:
            # STALL = reset stall-detectie en stuur boiler opnieuw aan
            self._current_op = OP_AUTO
            if ctrl:
                ctrl.force_stall_reset(self._boiler.entity_id)
                async def _send_stall():
                    try:
                        sp = self._boiler.active_setpoint_c or self._boiler.setpoint_c
                        await ctrl.send_now(self._boiler.entity_id, True, sp)
                    except Exception as _err:
                        _LOGGER.warning("VirtualBoiler send_now (stall reset) fout: %s", _err)
                self.hass.async_create_task(_send_stall())
        else:
            _LOGGER.debug(
                "CloudEMS VirtualBoiler [%s]: operatiemodus '%s' onbekend — geen actie",
                self._boiler.label, operation_mode,
            )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        self._override_until    = 0.0
        self._override_setpoint = None
        self._current_op        = OP_AUTO
        if ctrl:
            ctrl.update_setpoint(self._boiler.entity_id, self._original_setpoint)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.info(
            "CloudEMS VirtualBoiler [%s]: handmatig uitgeschakeld (24u override)",
            self._boiler.label,
        )
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        if self._override_until == 0.0:
            self._original_setpoint = self._boiler.setpoint_c
        self._override_until    = time.time() + 24 * 3600
        self._override_setpoint = self._boiler.min_temp_c
        self._current_op        = OP_MANUAL
        if ctrl:
            ctrl.update_setpoint(self._boiler.entity_id, self._boiler.min_temp_c)
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        # Manual/boost/legionella override verlopen → terug naar auto
        if self._override_until > 0 and time.time() > self._override_until:
            _LOGGER.info(
                "CloudEMS VirtualBoiler [%s]: override verlopen \u2014 CloudEMS neemt het over, "
                "setpoint hersteld naar %.1f\u00b0C",
                self._boiler.label, self._original_setpoint,
            )
            if ctrl:
                ctrl.update_setpoint(self._boiler.entity_id, self._original_setpoint)
                ctrl.clear_manual_override(self._boiler.entity_id)
            self._override_until    = 0.0
            self._override_setpoint = None
            self._current_op        = OP_AUTO
        # ECO/boost-pauze verlopen → terug naar auto
        if self._current_op == OP_ECO and ctrl:
            all_b = list(getattr(ctrl, "_boilers", [])) + [
                b for g in getattr(ctrl, "_groups", []) for b in g.boilers
            ]
            for b in all_b:
                if b.entity_id == self._boiler.entity_id:
                    if b._boost_paused_until <= time.time():
                        self._current_op = OP_AUTO
                    break
        super()._handle_coordinator_update()
