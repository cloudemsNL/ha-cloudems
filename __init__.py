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
    # Use async_refresh (not first_refresh) so a slow/failing first update
    # does NOT mark all entities unavailable — they will recover on the next poll.
    try:
        await coordinator.async_refresh()
    except Exception:  # noqa: BLE001
        _LOGGER.warning("CloudEMS: first refresh failed, entities will recover on next poll")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

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

    async def reset_drift_baseline(call: ServiceCall):
        """Reset the drift baseline for a device (e.g. after replacement).
        
        Parameters:
          device_id (optional): specific device id to reset. If omitted, resets ALL devices.
        """
        tracker = getattr(coordinator, "_device_drift", None)
        if not tracker:
            _LOGGER.warning("CloudEMS reset_drift_baseline: drift tracker not initialised")
            return
        device_id = call.data.get("device_id")
        if device_id:
            tracker._profiles.pop(device_id, None)
            _LOGGER.info("CloudEMS: drift baseline reset for device '%s'", device_id)
        else:
            tracker._profiles.clear()
            _LOGGER.info("CloudEMS: ALL drift baselines reset")
        tracker._dirty = True
        await tracker.async_maybe_save()

    async def mute_alert(call: ServiceCall):
        """Mute a CloudEMS alert by its key (suppresses for 24h).
        
        Parameters:
          alert_key: the alert key, e.g. 'device_drift:my_device_id'
        """
        engine = getattr(coordinator, "_notification_engine", None)
        if not engine:
            return
        key = call.data.get("alert_key", "")
        if key:
            engine.mute(key)
            _LOGGER.info("CloudEMS: alert '%s' muted", key)

    hass.services.async_register(DOMAIN, "reset_drift_baseline",   reset_drift_baseline)
    hass.services.async_register(DOMAIN, "mute_alert",             mute_alert)


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
    """Migrate old config entries to current version.

    v1 → v2: removes legacy top-level inv/bat sensor keys that moved into
              CONF_INVERTER_CONFIGS / CONF_BATTERY_CONFIGS lists.
    v2 → v3: renames entity_ids that changed slug in v1.15
              (e.g. Efficientiedrift, device_drift unique_id normalisation).
    """
    version = config_entry.version
    _LOGGER.info("CloudEMS: migrating from version %s", version)

    if version == 1:
        # v1→v2: remove stale top-level sensor keys that are now inside nested configs
        stale_keys = [
            "solar_sensor_legacy", "battery_sensor_legacy",
            "inverter_entity", "bat_power_entity",
        ]
        new_data = {k: v for k, v in config_entry.data.items() if k not in stale_keys}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        version = 2
        _LOGGER.info("CloudEMS: migrated to version 2")

    if version == 2:
        # v2→v3: fix unique_id renames from v1.13→v1.15
        # Rename entity registry entries for slugs that changed
        slug_renames = {
            # old unique_id suffix → new unique_id suffix
            "_efficientiedrift":        "_device_drift",
            "_apparaat_efficientiedrift": "_device_drift",
            "_aanwezigheid":            "_occupancy",
            "_verbruik_anomalie":       "_anomaly",
        }
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        entry_id = config_entry.entry_id
        renamed = 0
        for old_suffix, new_suffix in slug_renames.items():
            old_uid = f"{entry_id}{old_suffix}"
            entity = ent_reg.async_get_entity_id("sensor", DOMAIN, old_uid) or                      ent_reg.async_get_entity_id("binary_sensor", DOMAIN, old_uid)
            if entity:
                ent_reg.async_update_entity(entity, new_unique_id=f"{entry_id}{new_suffix}")
                renamed += 1
                _LOGGER.info("CloudEMS migrate: renamed %s → %s", old_uid, f"{entry_id}{new_suffix}")
        if renamed:
            _LOGGER.info("CloudEMS: migrated %d entity unique_ids", renamed)
        hass.config_entries.async_update_entry(config_entry, version=3)
        _LOGGER.info("CloudEMS: migrated to version 3")

    return True
