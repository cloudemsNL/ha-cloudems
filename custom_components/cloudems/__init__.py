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

LOVELACE_RESOURCE_URL  = f"/cloudems/cloudems-card.js?v={VERSION}"
LOVELACE_RESOURCE_TYPE = "module"


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register the CloudEMS card JS as a Lovelace resource if not already present."""
    try:
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.debug("CloudEMS: lovelace not available yet, skipping resource registration")
            return

        resources = lovelace.get("resources")
        if resources is None:
            _LOGGER.debug("CloudEMS: lovelace resources not available, skipping")
            return

        await resources.async_load()
        existing = [r for r in resources.async_items() if "cloudems-card.js" in r.get("url", "")]
        if existing:
            item = existing[0]
            if item.get("url") != LOVELACE_RESOURCE_URL:
                await resources.async_update_item(item["id"], {
                    "res_type": LOVELACE_RESOURCE_TYPE,
                    "url": LOVELACE_RESOURCE_URL,
                })
                _LOGGER.info("CloudEMS: Lovelace resource updated → %s", LOVELACE_RESOURCE_URL)
            else:
                _LOGGER.debug("CloudEMS: Lovelace resource already up-to-date")
            return

        await resources.async_create_item({
            "res_type": LOVELACE_RESOURCE_TYPE,
            "url": LOVELACE_RESOURCE_URL,
        })
        _LOGGER.info("CloudEMS: Lovelace resource registered → %s", LOVELACE_RESOURCE_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("CloudEMS: could not auto-register Lovelace resource: %s", err)


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

    # Auto-register the Lovelace card resource so users don't have to do it manually
    hass.async_create_task(_async_register_lovelace_resource(hass))

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

    async def rename_nilm_device(call: ServiceCall):
        """v1.20: Rename a NILM device (display name + optional type)."""
        coordinator.rename_nilm_device(
            call.data["device_id"],
            call.data["name"],
            call.data.get("device_type", ""),
        )

    async def hide_nilm_device(call: ServiceCall):
        """v1.20: Hide or unhide a NILM device from dashboards."""
        coordinator.hide_nilm_device(
            call.data["device_id"],
            call.data.get("hidden", True),
        )

    async def suppress_nilm_device(call: ServiceCall):
        """v1.20: Decline/suppress a NILM device — never show again."""
        coordinator.suppress_nilm_device(call.data["device_id"])

    async def assign_device_to_room(call: ServiceCall):
        """v1.20: Manually assign a NILM device to a room."""
        coordinator.assign_device_to_room(
            call.data["device_id"],
            call.data.get("room", ""),
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
    hass.services.async_register(DOMAIN, "rename_nilm_device",     rename_nilm_device)
    hass.services.async_register(DOMAIN, "hide_nilm_device",       hide_nilm_device)
    hass.services.async_register(DOMAIN, "suppress_nilm_device",   suppress_nilm_device)
    hass.services.async_register(DOMAIN, "assign_device_to_room",  assign_device_to_room)
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

    # ── v1.18.1: Nieuwe services ──────────────────────────────────────────────

    async def export_learning_data(call: ServiceCall) -> None:
        """
        Exporteer alle geleerde data naar /config/cloudems_export.json.
        Gebruik bij HA-migratie of nieuwe installatie om opnieuw te beginnen.
        """
        import json, os, time as _time
        export = {
            "version":   "1.18.1",
            "exported":  _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "modules":   {},
        }
        sl = getattr(coordinator, "_solar_learner", None)
        if sl:
            export["modules"]["solar_learner"] = sl._build_save_data()

        pv = getattr(coordinator, "_pv_forecast", None)
        if pv:
            pv_data = {}
            for eid, p in pv._profiles.items():
                pv_data[eid] = {
                    "learned_azimuth":       p.learned_azimuth,
                    "learned_tilt":          p.learned_tilt,
                    "orientation_confident": p.orientation_confident,
                    "clear_sky_samples":     p.clear_sky_samples,
                    "hourly_yield_fraction": p.hourly_yield_fraction,
                    "peak_wp":               p._peak_wp,
                }
            export["modules"]["pv_forecast"] = pv_data

        path = os.path.join(hass.config.config_dir, "cloudems_export.json")
        try:
            def _write():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(export, f, indent=2, default=str)
            await hass.async_add_executor_job(_write)
            _LOGGER.info("CloudEMS: leerdata geëxporteerd naar %s", path)
            from homeassistant.components.persistent_notification import async_create
            async_create(hass, f"Leerdata opgeslagen in `{path}`",
                         title="CloudEMS Export", notification_id="cloudems_export")
        except Exception as exc:
            _LOGGER.error("CloudEMS export mislukt: %s", exc)

    async def import_learning_data(call: ServiceCall) -> None:
        """
        Importeer eerder geëxporteerde leerdata.
        Parameters:
          path (optional): pad naar het JSON-bestand (default: /config/cloudems_export.json)
        """
        import json, os
        path = call.data.get("path") or os.path.join(hass.config.config_dir, "cloudems_export.json")
        try:
            def _read():
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            export = await hass.async_add_executor_job(_read)
        except Exception as exc:
            _LOGGER.error("CloudEMS import lezen mislukt (%s): %s", path, exc)
            return

        modules = export.get("modules", {})
        imported = []

        sl = getattr(coordinator, "_solar_learner", None)
        if sl and "solar_learner" in modules:
            store_data = modules["solar_learner"]
            await sl._store.async_save(store_data)
            await sl.async_setup(backup=getattr(coordinator, "_learning_backup", None))
            imported.append("solar_learner")

        pv = getattr(coordinator, "_pv_forecast", None)
        if pv and "pv_forecast" in modules:
            await pv._store.async_save(modules["pv_forecast"])
            await pv.async_setup(backup=getattr(coordinator, "_learning_backup", None))
            imported.append("pv_forecast")

        _LOGGER.info("CloudEMS import: %s geladen uit %s", imported, path)
        from homeassistant.components.persistent_notification import async_create
        async_create(hass,
            f"Leerdata hersteld: {', '.join(imported)} (uit `{path}`)",
            title="CloudEMS Import", notification_id="cloudems_import")

    async def register_isolation_investment(call: ServiceCall) -> None:
        """Registreer een isolatie-investering voor gasverbruikstracking."""
        gas = getattr(coordinator, "_gas_analysis", None)
        if gas:
            gas.register_isolation_investment(call.data.get("date", ""))
            _LOGGER.info("CloudEMS: isolatie-investering geregistreerd")

    async def health_check(call: ServiceCall) -> None:
        """Log de status van alle zelflerende modules als persistent_notification."""
        lines = ["## 🩺 CloudEMS Health Check", ""]
        mods = {
            "solar_learner":   getattr(coordinator, "_solar_learner", None),
            "pv_forecast":     getattr(coordinator, "_pv_forecast", None),
            "battery_degrad":  getattr(coordinator, "_battery_degradation", None),
            "thermal_model":   getattr(coordinator, "_thermal_model", None),
            "hp_cop":          getattr(coordinator, "_hp_cop", None),
            "gas_analysis":    getattr(coordinator, "_gas_analysis", None),
            "clipping_loss":   getattr(coordinator, "_clipping_loss", None),
            "shadow_detect":   getattr(coordinator, "_shadow_detector", None),
            "device_drift":    getattr(coordinator, "_device_drift", None),
            "pv_health":       getattr(coordinator, "_pv_health", None),
            "pv_accuracy":     getattr(coordinator, "_pv_accuracy", None),
            "cost_forecaster": getattr(coordinator, "_cost_forecaster", None),
        }
        for name, mod in mods.items():
            if mod is None:
                lines.append(f"- ⬜ **{name}**: niet actief")
            else:
                dirty = getattr(mod, "_dirty", None)
                last  = getattr(mod, "_last_save", None)
                import time as _t
                age   = f"{int((_t.time() - last) / 60)}m geleden" if last else "?"
                lines.append(f"- ✅ **{name}**: actief | dirty={dirty} | opgeslagen: {age}")

        from homeassistant.components.persistent_notification import async_create
        async_create(hass, "\n".join(lines), title="CloudEMS Health", notification_id="cloudems_health")
        _LOGGER.info("CloudEMS health check uitgevoerd")

    hass.services.async_register(DOMAIN, "export_learning_data",         export_learning_data)
    hass.services.async_register(DOMAIN, "import_learning_data",         import_learning_data)
    hass.services.async_register(DOMAIN, "register_isolation_investment", register_isolation_investment)
    hass.services.async_register(DOMAIN, "health_check",                 health_check)


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
