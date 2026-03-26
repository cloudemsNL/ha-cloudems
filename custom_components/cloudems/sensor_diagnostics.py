"""
CloudEMS Sensor Diagnostics — v1.3
Controleert bij opstarten of kritieke sensoren bestaan.
Detecteert en repareert orphaned entity_registry entries van oude installaties.
Re-enablet automatisch door HA uitgeschakelde sensoren.
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Alleen sensoren met expliciete entity_id — gegarandeerd stabiel
_CRITICAL_SENSORS: dict[str, list[str]] = {
    "Kern": [
        "sensor.cloudems_status",
        "sensor.cloudems_watchdog",
        "sensor.cloudems_solar_system",
        "sensor.cloudems_battery_so_c",
        "sensor.cloudems_battery_power",
        "sensor.cloudems_home_rest",
        "sensor.cloudems_price_current_hour",
        "sensor.cloudems_zon_vermogen",
    ],
    "AI & Leren": [
        "sensor.cloudems_ai_status",
        "sensor.cloudems_self_consumption",
        "sensor.cloudems_nilm_devices",
        "sensor.cloudems_nilm_running_devices",
        "sensor.cloudems_nilm_groups",
    ],
    "Fase & Grid": [
        "sensor.cloudems_flexibel_vermogen",
        "sensor.cloudems_kwartier_piek",
    ],
    "Boiler & Klimaat": [
        "sensor.cloudems_boiler_status",
        "sensor.cloudems_climate_epex_status",
        "sensor.cloudems_energy_demand",
    ],
}


async def async_check_sensors(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
    """
    Controleert na setup welke sensoren ontbreken, disabled of orphaned zijn.
    
    Orphaned entries: sensor staat in entity_registry maar gekoppeld aan een
    oud/ander config_entry_id. HA weigert de nieuwe registratie dan stil —
    sensor verschijnt nooit in hass.states. We verwijderen de orphaned entry
    zodat de sensor bij de volgende herstart opnieuw geregistreerd kan worden.
    """
    from homeassistant.helpers import entity_registry as er

    _er = er.async_get(hass)

    # Huidige entry entities
    entry_entities = {
        e.entity_id: e
        for e in er.async_entries_for_config_entry(_er, entry.entry_id)
    }

    # Globale entity registry (alle entries, alle config_entries)
    all_registry = {e.entity_id: e for e in _er.entities.values()}

    missing:     list[str] = []
    reenabled:   list[str] = []
    orphaned:    list[str] = []
    user_disabled: list[str] = []
    ok_count = 0
    needs_restart = False

    for category, sensor_ids in _CRITICAL_SENSORS.items():
        for eid in sensor_ids:
            state     = hass.states.get(eid)
            reg_entry = entry_entities.get(eid)
            global_entry = all_registry.get(eid)

            if state is not None and reg_entry is not None and not reg_entry.disabled_by:
                # Alles OK
                ok_count += 1

            elif reg_entry and reg_entry.disabled_by:
                disabled_by = str(reg_entry.disabled_by)
                if "user" in disabled_by:
                    user_disabled.append(f"{eid} [{category}]")
                else:
                    try:
                        _er.async_update_entity(eid, disabled_by=None)
                        reenabled.append(f"{eid} [{category}] (was: {disabled_by})")
                    except Exception as _e:
                        _LOGGER.warning("CloudEMS sensor check: kon %s niet re-enablen: %s", eid, _e)

            elif global_entry is not None and global_entry.config_entry_id != entry.entry_id:
                # Orphaned: staat in registry maar gekoppeld aan ander config_entry_id
                # Verwijder de orphaned entry zodat herstart hem opnieuw registreert
                try:
                    _er.async_remove(eid)
                    orphaned.append(
                        f"{eid} [{category}] "
                        f"(oud entry_id: {global_entry.config_entry_id[:8]}...)"
                    )
                    needs_restart = True
                except Exception as _e:
                    _LOGGER.warning(
                        "CloudEMS sensor check: kon orphaned entry %s niet verwijderen: %s", eid, _e
                    )

            elif state is None and reg_entry is None and global_entry is None:
                # Echt ontbrekend — nooit geregistreerd
                missing.append(f"{eid} [{category}]")

            else:
                ok_count += 1

    total = sum(len(v) for v in _CRITICAL_SENSORS.values())
    _LOGGER.info("CloudEMS sensor check: %d/%d kritieke sensoren OK", ok_count, total)

    if orphaned:
        _LOGGER.warning(
            "CloudEMS sensor check — %d verouderde sensor-registraties verwijderd "
            "(HA herstart nodig om ze opnieuw te registreren): %s",
            len(orphaned), " | ".join(orphaned),
        )

    if reenabled:
        _LOGGER.warning(
            "CloudEMS sensor check — %d sensoren automatisch opnieuw ingeschakeld: %s",
            len(reenabled), " | ".join(reenabled),
        )

    if missing:
        _LOGGER.error(
            "CloudEMS sensor check — ONTBREKEND (%d): %s",
            len(missing), " | ".join(missing),
        )

    if user_disabled:
        _LOGGER.info(
            "CloudEMS sensor check — uitgeschakeld door gebruiker (%d): %s",
            len(user_disabled), " | ".join(user_disabled),
        )

    if needs_restart:
        _LOGGER.warning(
            "CloudEMS sensor check — verouderde registraties verwijderd. "
            "Herstart HA zodat de sensoren opnieuw aangemeld worden."
        )

    _check_duplicate_registrations(entry_entities)


def _check_duplicate_registrations(entry_entities: dict) -> None:
    seen: dict[str, list[str]] = {}
    for eid, reg_entry in entry_entities.items():
        seen.setdefault(eid, []).append(reg_entry.unique_id)
    for eid, uids in seen.items():
        if len(uids) > 1:
            _LOGGER.error(
                "CloudEMS sensor conflict: %s heeft %d registraties (unique_ids: %s)",
                eid, len(uids), ", ".join(uids),
            )
