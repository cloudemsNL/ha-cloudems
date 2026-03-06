# -*- coding: utf-8 -*-
"""CloudEMS button platform — v1.3.0."""
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
        # v1.22: NILM cleanup knoppen
        CloudEMSNILMCleanupFullButton(coordinator),
        CloudEMSNILMCleanup7DaysButton(coordinator),
        CloudEMSNILMCleanup30DaysButton(coordinator),
        CloudEMSNILMCleanupEnergyButton(coordinator),
        CloudEMSNILMCleanupWeekButton(coordinator),
        CloudEMSNILMCleanupMonthButton(coordinator),
        CloudEMSNILMCleanupYearButton(coordinator),
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
        await self.coordinator.async_request_refresh()


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


# ── v1.22: NILM Cleanup knoppen ───────────────────────────────────────────────

class _NILMCleanupBase(CoordinatorEntity, ButtonEntity):
    """Basis klasse voor NILM cleanup knoppen."""

    _cleanup_scope: str = "full"
    _cleanup_days:  int = 0

    def __init__(self, coordinator: CloudEMSCoordinator):
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        result = self.coordinator.nilm.cleanup(
            scope=self._cleanup_scope,
            days=self._cleanup_days,
        )
        await self.coordinator.nilm.async_save()
        persistent_notification.async_create(
            self.hass,
            title="🧹 CloudEMS NILM Cleanup",
            message=(
                f"**Scope:** `{result['scope']}`"
                + (f"  ·  **Dagen:** {result['days']}" if result["days"] else "")
                + f"\n\n"
                f"- Verwijderd: **{result['removed_devices']}** apparaten\n"
                f"- Gereset: **{result['reset_energy']}** energietellers\n"
                f"- Resterend: **{result['devices_remaining']}** apparaten"
            ),
            notification_id="cloudems_nilm_cleanup",
        )
        _LOGGER.info(
            "NILM cleanup via knop: scope=%s days=%d → %s",
            result["scope"], result["days"], result,
        )


class CloudEMSNILMCleanupFullButton(_NILMCleanupBase):
    """Verwijder alle NILM-apparaten — schone start."""
    _attr_icon = "mdi:delete-sweep"
    _cleanup_scope = "full"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_full"
        self._attr_name = "CloudEMS NILM Volledig opruimen"


class CloudEMSNILMCleanup7DaysButton(_NILMCleanupBase):
    """Verwijder onbevestigde apparaten van de laatste 7 dagen."""
    _attr_icon = "mdi:calendar-week"
    _cleanup_scope = "last_x_days"
    _cleanup_days  = 7

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_7d"
        self._attr_name = "CloudEMS NILM Opruimen (laatste 7 dagen)"


class CloudEMSNILMCleanup30DaysButton(_NILMCleanupBase):
    """Verwijder onbevestigde apparaten van de laatste 30 dagen."""
    _attr_icon = "mdi:calendar-month"
    _cleanup_scope = "last_x_days"
    _cleanup_days  = 30

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_30d"
        self._attr_name = "CloudEMS NILM Opruimen (laatste 30 dagen)"


class CloudEMSNILMCleanupEnergyButton(_NILMCleanupBase):
    """Reset alle energietellers (kWh)."""
    _attr_icon = "mdi:counter"
    _cleanup_scope = "energy"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_energy"
        self._attr_name = "CloudEMS NILM Energietellers resetten"


class CloudEMSNILMCleanupWeekButton(_NILMCleanupBase):
    """Reset week-kWh tellers."""
    _attr_icon = "mdi:calendar-week-begin"
    _cleanup_scope = "week"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_week"
        self._attr_name = "CloudEMS NILM Week resetten"


class CloudEMSNILMCleanupMonthButton(_NILMCleanupBase):
    """Reset maand-kWh tellers."""
    _attr_icon = "mdi:calendar-month-outline"
    _cleanup_scope = "month"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_month"
        self._attr_name = "CloudEMS NILM Maand resetten"


class CloudEMSNILMCleanupYearButton(_NILMCleanupBase):
    """Reset jaar-kWh tellers."""
    _attr_icon = "mdi:calendar-year"
    _cleanup_scope = "year"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_nilm_cleanup_year"
        self._attr_name = "CloudEMS NILM Jaar resetten"

