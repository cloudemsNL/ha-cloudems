"""CloudEMS - Energy Management System for Home Assistant."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu
# https://buymeacoffee.com/cloudems

from __future__ import annotations
import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, VERSION, PLATFORM_SENSOR, PLATFORM_SWITCH, PLATFORM_NUMBER, PLATFORM_BUTTON
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CloudEMS from a config entry."""
    _LOGGER.info("Setting up CloudEMS integration v%s", VERSION)

    coordinator = CloudEMSCoordinator(hass, entry.data)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    _register_services(hass, coordinator)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _register_services(hass: HomeAssistant, coordinator: CloudEMSCoordinator):
    """Register CloudEMS HA services."""

    async def confirm_device(call: ServiceCall):
        """Service: confirm a NILM-detected device."""
        coordinator.confirm_nilm_device(
            call.data["device_id"],
            call.data["device_type"],
            call.data.get("name", call.data["device_type"]),
        )

    async def dismiss_device(call: ServiceCall):
        """Service: dismiss a NILM-detected device."""
        coordinator.dismiss_nilm_device(call.data["device_id"])

    async def set_phase_max_current(call: ServiceCall):
        """Service: set max current for a phase."""
        coordinator._limiter.set_max_current(
            call.data["phase"],
            float(call.data["max_current"]),
        )

    async def force_price_update(call: ServiceCall):
        """Service: force energy price update."""
        if coordinator._prices:
            await coordinator._prices.update()

    async def generate_report(call):
        """Service: generate a diagnostic report notification."""
        from .diagnostics import async_generate_report
        await async_generate_report(hass, entry)

    hass.services.async_register(DOMAIN, "confirm_device", confirm_device)
    hass.services.async_register(DOMAIN, "dismiss_device", dismiss_device)
    hass.services.async_register(DOMAIN, "set_phase_max_current", set_phase_max_current)
    hass.services.async_register(DOMAIN, "force_price_update", force_price_update)
    hass.services.async_register(DOMAIN, "generate_report", generate_report)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload CloudEMS config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload CloudEMS entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass, config_entry) -> bool:
    """Migrate old config entries to current version."""
    _LOGGER.debug("CloudEMS: migratie van versie %s", config_entry.version)
    return True
