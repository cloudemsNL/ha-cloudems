"""CloudEMS - Energy Management System for Home Assistant — v1.4.1."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
# BUG FIX: Platform.BINARY_SENSOR was missing from PLATFORMS list
from __future__ import annotations
import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import DOMAIN, VERSION
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)

# FIX: Added Platform.BINARY_SENSOR — was missing in v1.4.0, causing cheap-hour
#      binary sensors to never be registered
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,   # ← FIX
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up CloudEMS integration v%s", VERSION)

    coordinator = CloudEMSCoordinator(hass, {**entry.data, **entry.options})
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _register_services(hass: HomeAssistant, entry: ConfigEntry, coordinator: CloudEMSCoordinator):

    async def confirm_device(call: ServiceCall):
        coordinator.confirm_nilm_device(
            call.data["device_id"],
            call.data["device_type"],
            call.data.get("name", call.data["device_type"]),
        )

    async def dismiss_device(call: ServiceCall):
        coordinator.dismiss_nilm_device(call.data["device_id"])

    # FIX: New service for feedback (correct/incorrect/maybe)
    async def nilm_feedback(call: ServiceCall):
        coordinator.set_nilm_feedback(
            call.data["device_id"],
            call.data["feedback"],          # correct | incorrect | maybe
            call.data.get("name",""),
            call.data.get("device_type",""),
        )

    async def set_phase_max_current(call: ServiceCall):
        coordinator._limiter.set_max_current(
            call.data["phase"],
            float(call.data["max_current"]),
        )

    async def force_price_update(call: ServiceCall):
        if coordinator._prices:
            await coordinator._prices.update()

    async def generate_report(call: ServiceCall):
        from .diagnostics import async_generate_report
        await async_generate_report(hass, entry)

    async def boiler_override(call: ServiceCall):
        """Manually force a boiler on or off."""
        if coordinator._boiler_ctrl:
            entity_id = call.data["entity_id"]
            state     = call.data.get("state", "on")
            domain    = entity_id.split(".")[0]
            await hass.services.async_call(
                domain, f"turn_{state}", {"entity_id": entity_id}, blocking=False
            )

    hass.services.async_register(DOMAIN, "confirm_device",         confirm_device)
    hass.services.async_register(DOMAIN, "dismiss_device",         dismiss_device)
    hass.services.async_register(DOMAIN, "nilm_feedback",          nilm_feedback)
    hass.services.async_register(DOMAIN, "set_phase_max_current",  set_phase_max_current)
    hass.services.async_register(DOMAIN, "force_price_update",     force_price_update)
    hass.services.async_register(DOMAIN, "generate_report",        generate_report)
    hass.services.async_register(DOMAIN, "boiler_override",        boiler_override)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()   # FIX: now exists
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass, config_entry) -> bool:
    _LOGGER.debug("CloudEMS: migration from version %s", config_entry.version)
    return True
