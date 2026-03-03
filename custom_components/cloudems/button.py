"""CloudEMS button platform — v1.2.0."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components import persistent_notification

from .const import DOMAIN, MANUFACTURER, BUY_ME_COFFEE_URL
from .coordinator import CloudEMSCoordinator
from .diagnostics import build_markdown_report

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        CloudEMSForceUpdateButton(coordinator),
        CloudEMSDiagnosticsButton(coordinator, entry),
        CloudEMSBuyMeCoffeeButton(coordinator),
    ])


def _device_info(coordinator):
    return {"identifiers": {(DOMAIN, "cloudems_hub")}, "manufacturer": MANUFACTURER}


class CloudEMSForceUpdateButton(CoordinatorEntity, ButtonEntity):
    """Force an immediate data refresh."""
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: CloudEMSCoordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_force_update"
        self._attr_name = "CloudEMS Bijwerken"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class CloudEMSDiagnosticsButton(CoordinatorEntity, ButtonEntity):
    """
    Generate a human-readable diagnostics report.

    Pressing this button creates a persistent HA notification with
    a full Markdown report of phase status, prices, NILM devices, etc.
    The user can copy or share this report for troubleshooting.
    """
    _attr_icon = "mdi:clipboard-pulse"

    def __init__(self, coordinator: CloudEMSCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_diagnostics"
        self._attr_name = "CloudEMS Diagnoserapport"
        self._attr_device_info = _device_info(coordinator)
        self._entry = entry

    async def async_press(self) -> None:
        data = self.coordinator.data or {}
        config = {**self._entry.data, **self._entry.options}
        report_md = build_markdown_report(data, config)

        persistent_notification.async_create(
            self.hass,
            title="🔍 CloudEMS Diagnoserapport",
            message=report_md,
            notification_id="cloudems_diagnostics",
        )
        _LOGGER.info("CloudEMS diagnostics report generated")


class CloudEMSBuyMeCoffeeButton(CoordinatorEntity, ButtonEntity):
    """Shortcut to the Buy Me a Coffee page."""
    _attr_icon = "mdi:coffee"

    def __init__(self, coordinator: CloudEMSCoordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_buy_me_coffee"
        self._attr_name = "CloudEMS ☕ Buy Me a Coffee"
        self._attr_device_info = _device_info(coordinator)
        self._attr_extra_state_attributes = {"url": BUY_ME_COFFEE_URL}

    async def async_press(self) -> None:
        pass  # URL shown in attributes
