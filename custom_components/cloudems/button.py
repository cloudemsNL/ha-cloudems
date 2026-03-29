# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS button platform — v1.3.0."""

from __future__ import annotations
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components import persistent_notification

from .const import DOMAIN, MANUFACTURER, BUY_ME_COFFEE_URL
from .sub_devices import sub_device_info, SUB_NILM, SUB_SHUTTER
from .coordinator import CloudEMSCoordinator
from .diagnostics import build_markdown_report

_LOGGER = logging.getLogger(__name__)


def _eid(entry, entity_id: str) -> str:
    """Demo-aware entity_id helper."""
    from .const import WIZARD_MODE_DEMO, CONF_WIZARD_MODE
    data = {**entry.data, **entry.options}
    if data.get(CONF_WIZARD_MODE) == WIZARD_MODE_DEMO:
        for prefix in ("sensor.", "switch.", "number.", "button.", "climate.", "water_heater."):
            if entity_id.startswith(prefix + "cloudems_"):
                return entity_id.replace(
                    prefix + "cloudems_",
                    prefix + "cloudems_demo_", 1)
    return entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        CloudEMSForceUpdateButton(coordinator),
        CloudEMSDiagnosticsButton(coordinator, entry),
        CloudEMSBuyMeCoffeeButton(coordinator),
        CloudEMSSliderCalibrateButton(coordinator),
        CloudEMSSliderMaxProbeButton(coordinator),
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
        CloudEMSNILMReviewMaybeButton(coordinator, entry),   # v4.5.15: weet ik niet
        CloudEMSNILMReviewSkipButton(coordinator, entry),
        CloudEMSNILMReviewPreviousButton(coordinator, entry),
    ]

    # Dynamische rolluik-knoppen op basis van geconfigureerde shutters
    shutter_cfgs = entry.options.get("shutter_configs") or entry.data.get("shutter_configs", [])
    for s_cfg in shutter_cfgs:
        eid   = s_cfg.get("entity_id", "")
        label = s_cfg.get("label", eid)
        if not eid:
            continue
        for action, action_label, hours in _SHUTTER_ACTIONS:
            entities.append(
                CloudEMSShutterButton(coordinator, eid, label, action, action_label, hours, entry)
            )

    async_add_entities(entities)

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
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_force_update"
        self.entity_id = _eid(coordinator.config_entry, "button.cloudems_bijwerken")
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
        self._attr_unique_id = f"{entry.entry_id}_diagnostics"
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
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_buy_me_coffee"
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
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_full"
        self._attr_name = "CloudEMS NILM Volledig opruimen"


class CloudEMSNILMCleanup7DaysButton(_NILMCleanupBase):
    """Verwijder onbevestigde apparaten van de laatste 7 dagen."""
    _attr_icon = "mdi:calendar-week"
    _cleanup_scope = "last_x_days"
    _cleanup_days  = 7

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_7d"
        self._attr_name = "CloudEMS NILM Opruimen (laatste 7 dagen)"


class CloudEMSNILMCleanup30DaysButton(_NILMCleanupBase):
    """Verwijder onbevestigde apparaten van de laatste 30 dagen."""
    _attr_icon = "mdi:calendar-month"
    _cleanup_scope = "last_x_days"
    _cleanup_days  = 30

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_30d"
        self._attr_name = "CloudEMS NILM Opruimen (laatste 30 dagen)"


class CloudEMSNILMCleanupEnergyButton(_NILMCleanupBase):
    """Reset alle energietellers (kWh)."""
    _attr_icon = "mdi:counter"
    _cleanup_scope = "energy"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_energy"
        self._attr_name = "CloudEMS NILM Energietellers resetten"


class CloudEMSNILMCleanupWeekButton(_NILMCleanupBase):
    """Reset week-kWh tellers."""
    _attr_icon = "mdi:calendar-week-begin"
    _cleanup_scope = "week"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_week"
        self._attr_name = "CloudEMS NILM Week resetten"


class CloudEMSNILMCleanupMonthButton(_NILMCleanupBase):
    """Reset maand-kWh tellers."""
    _attr_icon = "mdi:calendar-month-outline"
    _cleanup_scope = "month"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_month"
        self._attr_name = "CloudEMS NILM Maand resetten"


class CloudEMSNILMCleanupYearButton(_NILMCleanupBase):
    """Reset jaar-kWh tellers."""
    _attr_icon = "mdi:calendar-year"
    _cleanup_scope = "year"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nilm_cleanup_year"
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
        return sub_device_info(self._entry, SUB_NILM)


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
        return sub_device_info(self._entry, SUB_NILM)

    @property
    def available(self) -> bool:
        return self.coordinator.get_review_current() is not None


class CloudEMSNILMReviewConfirmButton(_NILMReviewQueueBase):
    """Bevestig het eerste onbevestigde NILM-apparaat."""
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_confirm"
        self.entity_id = _eid(entry, "button.cloudems_nilm_review_confirm")

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
        self.entity_id = _eid(entry, "button.cloudems_nilm_review_dismiss")

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


class CloudEMSNILMReviewMaybeButton(_NILMReviewQueueBase):
    """Markeer het huidige NILM-apparaat als 'weet ik niet' — blijft zichtbaar, wordt later opnieuw aangeboden."""
    _attr_icon = "mdi:help-circle-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_maybe"
        self.entity_id = _eid(entry, "button.cloudems_nilm_review_maybe")
        self._attr_name      = "❓ Weet ik niet"

    async def async_press(self) -> None:
        did = self.coordinator.review_maybe_current()
        if did:
            _LOGGER.info("NILM review: misschien '%s'", did)
            self.async_write_ha_state()


class CloudEMSNILMReviewSkipButton(_NILMReviewQueueBase):
    """Sla het huidige apparaat tijdelijk over — komt terug na herstart."""
    _attr_icon = "mdi:skip-next-circle"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_skip"
        self.entity_id = _eid(entry, "button.cloudems_nilm_review_skip")
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
        self.entity_id = _eid(entry, "button.cloudems_nilm_review_previous")
        self._attr_name      = "⏮ Vorige"

    @property
    def available(self) -> bool:
        return bool(self.coordinator._review_skip_history)

    async def async_press(self) -> None:
        did = self.coordinator.review_previous()
        if did:
            _LOGGER.info("NILM review: terug naar '%s'", did)
            self.async_write_ha_state()


# ═══════════════════════════════════════════════════════════════════════════════
# v1.4.0 — Rolluik actie-knoppen (dynamisch per geconfigureerde shutter)
# ═══════════════════════════════════════════════════════════════════════════════

_SHUTTER_ACTIONS = [
    ("open",       "⬆️ Openen",              2.0),
    ("stop",       "⏹️ Stoppen",              0.0),
    ("close",      "⬇️ Sluiten",             2.0),
    ("cancel",     "✅ Automaat hervatten",   0.0),
    ("pause_4h",   "⏸ Pauze 4 uur",          0.0),
    ("pause_24h",  "⏸ Pauze 1 dag",          0.0),
    ("pause_72h",  "⏸ Pauze 3 dagen",        0.0),
    ("pause_168h", "⏸ Pauze 1 week",         0.0),
]


class CloudEMSShutterButton(CoordinatorEntity, ButtonEntity):
    """Één actie-knop voor een geconfigureerd rolluik."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: "CloudEMSCoordinator",
        cover_entity_id: str,
        label: str,
        action: str,
        action_label: str,
        hours: float,
        entry: "ConfigEntry",
    ) -> None:
        super().__init__(coordinator)
        self._cover_entity_id = cover_entity_id
        self._action          = action
        self._hours           = hours
        self._entry_obj       = entry
        self._entry_id        = entry.entry_id
        safe_id               = cover_entity_id.split(".")[-1].replace("-", "_")
        self._attr_unique_id  = f"{entry.entry_id}_shutter_{safe_id}_{action}"
        self.entity_id = _eid(entry, f"button.cloudems_shutter_{safe_id}_{action}")
        self._attr_name       = f"{label} — {action_label}"
        self._attr_icon       = {
            "open":      "mdi:arrow-up-box",
            "stop":      "mdi:stop",
            "close":     "mdi:arrow-down-box",
            "cancel":    "mdi:robot",
            "pause_4h":  "mdi:timer-pause",
            "pause_24h": "mdi:timer-pause",
            "pause_72h": "mdi:timer-pause",
            "pause_168h":"mdi:timer-pause",
        }.get(action, "mdi:blinds")

    @property
    def device_info(self):
        return sub_device_info(self._entry_obj, SUB_SHUTTER)

    async def async_press(self) -> None:
        sc = self.coordinator._shutter_ctrl
        if sc is None:
            _LOGGER.warning("CloudEMS ShutterButton: ShutterController niet actief")
            return
        if self._action == "cancel":
            sc.cancel_override(self._cover_entity_id)
            sc.set_auto_enabled(self._cover_entity_id, True)
        elif self._action.startswith("pause_"):
            hours = float(self._action.replace("pause_", "").replace("h", ""))
            sc.set_auto_enabled(self._cover_entity_id, False, hours=hours)
        else:
            await sc.async_manual_override(
                self._cover_entity_id, self._action,
                None, self._hours
            )
        self.coordinator.async_update_listeners()



class CloudEMSSliderCalibrateButton(CoordinatorEntity, ButtonEntity):
    """Forceert direct een slider-beslissing op basis van huidige situatie."""

    _attr_name       = "CloudEMS Slider kalibratie"
    _attr_icon       = "mdi:tune-variant"
    # unique_id set in __init__ for multi-instance support
    # # unique_id via __init__: f"{entry_id}_slider_kalibratie"
    entity_id        = "button.cloudems_slider_kalibratie"

    def __init__(self, coordinator: CloudEMSCoordinator) -> None:
        super().__init__(coordinator)
        _eid_sfx = "slider_kalibratie"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{_eid_sfx}"
        self.entity_id = _eid(coordinator.config_entry, "button.cloudems_slider_kalibratie")

    @property
    def device_info(self):
        return _device_info(self.coordinator)

    @property
    def available(self) -> bool:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        return zb is not None and getattr(zb, "is_available", False)

    async def async_press(self) -> None:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        if zb is None:
            _LOGGER.warning("CloudEMS SliderKalibratie: geen Zonneplan bridge actief")
            return
        result = await zb.async_force_slider_calibrate()
        _LOGGER.info("CloudEMS SliderKalibratie resultaat: %s", result)
        if result.get("error"):
            msg = f"⚠️ Kalibratie mislukt: {result['error']}"
        else:
            msg = (
                f"**⚡ Slider kalibratie uitgevoerd**\n\n"
                f"| Slider | Waarde | Reden |\n"
                f"|---|---|---|\n"
                + (f"| ⬇️ Leveren aan huis | **{result['deliver_to_home_w']} W** "
                   f"| {result['deliver_reason']} |\n" if result.get("has_deliver") else "")
                + (f"| ☀️ Zonneladen | **{result['solar_charge_w']} W** "
                   f"| {result['solar_reason']} |\n" if result.get("has_solar") else "")
                + f"\nSoC: {result['soc_pct']:.0f}% · PV surplus: {result['surplus_w']:.0f}W"
            )
        persistent_notification.async_create(
            self.coordinator.hass,
            msg,
            title="CloudEMS — Slider kalibratie",
            notification_id="cloudems_slider_calibrate",
        )
        self.coordinator.async_update_listeners()


class CloudEMSSliderMaxProbeButton(CoordinatorEntity, ButtonEntity):
    """Herleest de slider-maxima uit de HA entiteit-attributen (max-attribuut van number entity)."""

    _attr_name      = "CloudEMS Slider max vernieuwen"
    _attr_icon      = "mdi:refresh"

    def __init__(self, coordinator: CloudEMSCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_slider_max_probe"
        self.entity_id = _eid(coordinator.config_entry, "button.cloudems_slider_max_probe")

    @property
    def device_info(self):
        return _device_info(self.coordinator)

    @property
    def available(self) -> bool:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        return zb is not None and getattr(zb, "is_available", False)

    async def async_press(self) -> None:
        zb = getattr(self.coordinator, "_zonneplan_bridge", None)
        if zb is None:
            return
        zb._read_slider_maxima()
        msg = (
            f"**✅ Slider maxima bijgewerkt**\n\n"
            f"| | |\n|---|---|\n"
            f"| **Leveren aan huis** | {zb._slider_max_deliver_w:.0f} W |\n"
            f"| **Zonnestroom opslaan** | {zb._slider_max_solar_w:.0f} W |\n\n"
            f"*Uitgelezen uit HA entiteit-attributen.*"
        )
        persistent_notification.async_create(
            self.coordinator.hass,
            msg,
            title="CloudEMS — Slider maxima",
            notification_id="cloudems_slider_max_probe",
        )
        self.coordinator.async_update_listeners()
