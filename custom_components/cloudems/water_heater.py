# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Water Heater platform (v1.0.0)

HA laadt dit bestand als het water_heater platform opstart.
De echte implementatie zit in virtual_boiler.py.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .virtual_boiler import async_setup_entry as _vboiler_setup


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Delegeer naar virtual_boiler.async_setup_entry."""
    await _vboiler_setup(hass, entry, async_add_entities)
