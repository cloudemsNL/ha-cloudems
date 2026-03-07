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
        # v2.4.14: vaste review-queue knoppen
        CloudEMSNILMReviewConfirmButton(coordinator, entry),
        CloudEMSNILMReviewDismissButton(coordinator, entry),
        CloudEMSNILMReviewSkipButton(coordinator, entry),
        CloudEMSNILMReviewPreviousButton(coordinator, entry),
    ])

    # v2.4.14: dynamische bevestig/afwijs-knoppen per gedetecteerd NILM-apparaat
    from homeassistant.helpers import entity_registry as er
    from homeassistant.core import callback

    _er = er.async_get(hass)
    registered_btn_ids: set = {
        e.unique_id
        for e in er.async_entries_for_config_entry(_er, entry.entry_id)
    }

    @callback
    def _nilm_buttons_updated():
        new_btns = []
        for dev in coordinator.nilm.get_devices():
            uid_ok = f"{entry.entry_id}_nilm_confirm_{dev.device_id}"
            uid_no = f"{entry.entry_id}_nilm_reject_{dev.device_id}"
            if uid_ok not in registered_btn_ids:
                new_btns.append(CloudEMSNILMConfirmButton(coordinator, entry, dev))
                new_btns.append(CloudEMSNILMRejectButton(coordinator, entry, dev))
                registered_btn_ids.add(uid_ok)
                registered_btn_ids.add(uid_no)
        if new_btns:
            async_add_entities(new_btns)

    coordinator.async_add_listener(_nilm_buttons_updated)


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



# ── v2.4.14: Dynamische NILM bevestig/afwijs-knoppen ─────────────────────────

class _NILMFeedbackBase(CoordinatorEntity, ButtonEntity):
    """Basisklasse voor NILM bevestig/afwijs-knoppen."""

    def __init__(self, coordinator: CloudEMSCoordinator, entry, device) -> None:
        super().__init__(coordinator)
        self._entry      = entry
        self._device_id  = device.device_id
        self._device_type = device.device_type
        self._device_name = device.name or device.device_type

    @property
    def device_info(self):
        from homeassistant.helpers.entity import DeviceInfo
        from .const import NAME, MANUFACTURER, WEBSITE, VERSION
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=f"CloudEMS v{VERSION}",
            configuration_url=WEBSITE,
        )


class CloudEMSNILMConfirmButton(_NILMFeedbackBase):
    """Bevestig dat dit NILM-apparaat correct is gedetecteerd."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator, entry, device) -> None:
        super().__init__(coordinator, entry, device)
        self._attr_unique_id = f"{entry.entry_id}_nilm_confirm_{device.device_id}"
        self._attr_name      = f"✅ Bevestig: {self._device_name}"

    async def async_press(self) -> None:
        self.coordinator.confirm_nilm_device(
            self._device_id,
            self._device_type,
            self._device_name,
        )
        _LOGGER.info("NILM: gebruiker bevestigde apparaat '%s' (%s)", self._device_name, self._device_id)


class CloudEMSNILMRejectButton(_NILMFeedbackBase):
    """Wijs dit NILM-apparaat af als fout-positief."""

    _attr_icon = "mdi:close-circle-outline"

    def __init__(self, coordinator, entry, device) -> None:
        super().__init__(coordinator, entry, device)
        self._attr_unique_id = f"{entry.entry_id}_nilm_reject_{device.device_id}"
        self._attr_name      = f"❌ Afwijzen: {self._device_name}"

    async def async_press(self) -> None:
        self.coordinator.dismiss_nilm_device(self._device_id)
        _LOGGER.info("NILM: gebruiker wees apparaat af '%s' (%s)", self._device_name, self._device_id)


# ── v2.4.14: Vaste review-queue knoppen (werken altijd op het eerste onbevestigde apparaat) ──

class _NILMReviewQueueBase(CoordinatorEntity, ButtonEntity):
    """Basisklasse voor review-queue knoppen met vaste entity_id."""

    def __init__(self, coordinator: CloudEMSCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        from homeassistant.helpers.entity import DeviceInfo
        from .const import NAME, MANUFACTURER, WEBSITE, VERSION
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=NAME, manufacturer=MANUFACTURER,
            model=f"CloudEMS v{VERSION}", configuration_url=WEBSITE,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.get_review_current() is not None


class CloudEMSNILMReviewConfirmButton(_NILMReviewQueueBase):
    """Bevestig het eerste onbevestigde NILM-apparaat."""
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_confirm"
        self.entity_id       = "button.cloudems_nilm_review_confirm"

    @property
    def name(self) -> str:
        dev = self.coordinator.get_review_current()
        label = dev.name or dev.device_type if dev else "—"
        return f"✅ Bevestig: {label}"

    async def async_press(self) -> None:
        did = self.coordinator.review_confirm_current()
        if did:
            _LOGGER.info("NILM review: bevestigd '%s'", did)
            await self.coordinator.async_request_refresh()


class CloudEMSNILMReviewDismissButton(_NILMReviewQueueBase):
    """Wijs het eerste onbevestigde NILM-apparaat af als fout-positief."""
    _attr_icon = "mdi:close-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_dismiss"
        self.entity_id       = "button.cloudems_nilm_review_dismiss"

    @property
    def name(self) -> str:
        dev = self.coordinator.get_review_current()
        label = dev.name or dev.device_type if dev else "—"
        return f"❌ Afwijzen: {label}"

    async def async_press(self) -> None:
        did = self.coordinator.review_dismiss_current()
        if did:
            _LOGGER.info("NILM review: afgewezen '%s'", did)
            await self.coordinator.async_request_refresh()


class CloudEMSNILMReviewSkipButton(_NILMReviewQueueBase):
    """Sla het huidige apparaat tijdelijk over — komt terug na herstart."""
    _attr_icon = "mdi:skip-next-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_skip"
        self.entity_id       = "button.cloudems_nilm_review_skip"
        self._attr_name      = "⏭ Volgende"

    async def async_press(self) -> None:
        did = self.coordinator.review_skip_current()
        if did:
            _LOGGER.info("NILM review: overgeslagen '%s'", did)
            self.async_write_ha_state()


class CloudEMSNILMReviewPreviousButton(_NILMReviewQueueBase):
    """Ga terug naar het vorige overgeslagen apparaat."""
    _attr_icon = "mdi:skip-previous-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_previous"
        self.entity_id       = "button.cloudems_nilm_review_previous"
        self._attr_name      = "⏮ Vorige"

    @property
    def available(self) -> bool:
        return bool(self.coordinator._review_skip_history)

    async def async_press(self) -> None:
        did = self.coordinator.review_previous()
        if did:
            _LOGGER.info("NILM review: terug naar '%s'", did)
            self.async_write_ha_state()
