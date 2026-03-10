# -*- coding: utf-8 -*-
"""CloudEMS text platform — instelbare tijden per rolluik (nacht/ochtend)."""
# Copyright (c) 2024-2025 CloudEMS - https://cloudems.eu
from __future__ import annotations
import logging
import re

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, MANUFACTURER, ATTRIBUTION, CONF_SHUTTER_CONFIGS, CONF_SHUTTER_COUNT
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CloudEMSShutterTime(RestoreEntity, TextEntity):
    """Instelbare HH:MM tijd voor een rolluik (nacht sluiten of ochtend openen)."""

    _attr_attribution  = ATTRIBUTION
    _attr_mode         = TextMode.TEXT
    _attr_native_min   = 5
    _attr_native_max   = 5
    _attr_pattern      = r"^([01]\d|2[0-3]):[0-5]\d$"
    _attr_should_poll  = False
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: CloudEMSCoordinator,
        entry: ConfigEntry,
        shutter_entity_id: str,
        label: str,
        suffix: str,           # "night_close" of "morning_open"
        default_value: str,
        icon: str,
        friendly_suffix: str,
    ) -> None:
        self._coordinator     = coordinator
        self._entry           = entry
        self._shutter_eid     = shutter_entity_id
        self._suffix          = suffix
        self._default         = default_value
        self._current_value   = default_value

        safe_id = shutter_entity_id.split(".")[-1].replace("-", "_")
        self._attr_unique_id  = f"{entry.entry_id}_shutterv2_{safe_id}_{suffix}"
        self._attr_name       = f"CloudEMS Rolluik {label} {friendly_suffix}"
        self._attr_icon       = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "CloudEMS",
            "manufacturer": MANUFACTURER,
        }

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state not in ("unknown", "unavailable", ""):
            self._current_value = last.state
        self._push_to_controller()

    @property
    def native_value(self) -> str:
        return self._current_value

    def set_value(self, value: str) -> None:
        if not _TIME_PATTERN.match(value):
            _LOGGER.warning("CloudEMS: ongeldige tijd '%s' voor %s", value, self._attr_name)
            return
        self._current_value = value
        self._push_to_controller()
        self.schedule_update_ha_state()

    def _push_to_controller(self) -> None:
        """Stuur de waarde direct door naar de ShutterController."""
        sc = getattr(self._coordinator, "_shutter_ctrl", None)
        if sc is None:
            return
        if self._suffix == "night_close":
            sc.set_night_close(self._shutter_eid, self._current_value)
        else:
            sc.set_morning_open(self._shutter_eid, self._current_value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: any,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    cfg_src = {**entry.data, **entry.options}
    shutter_count = int(cfg_src.get(CONF_SHUTTER_COUNT, 0))
    shutter_configs = cfg_src.get(CONF_SHUTTER_CONFIGS, [])

    _LOGGER.debug(
        "CloudEMS text platform setup: shutter_count=%s, configs=%s",
        shutter_count, len(shutter_configs)
    )

    if not shutter_configs:
        _LOGGER.debug("CloudEMS text platform: geen shutter_configs, skip")
        return
    if shutter_count == 0:
        shutter_count = len(shutter_configs)

    entities: list[CloudEMSShutterTime] = []
    for sh in shutter_configs:
        eid   = sh.get("entity_id", "")
        label = sh.get("label", eid.split(".")[-1])
        if not eid:
            continue
        entities.append(CloudEMSShutterTime(
            coordinator, entry, eid, label,
            suffix="night_close",
            default_value=sh.get("night_close_time", "23:00"),
            icon="mdi:weather-night",
            friendly_suffix="Nacht sluiten",
        ))
        entities.append(CloudEMSShutterTime(
            coordinator, entry, eid, label,
            suffix="morning_open",
            default_value=sh.get("morning_open_time", "07:30"),
            icon="mdi:weather-sunrise",
            friendly_suffix="Ochtend openen",
        ))

    _LOGGER.debug("CloudEMS text platform: %s entities aangemaakt", len(entities))
    async_add_entities(entities)
