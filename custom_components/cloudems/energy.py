# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — HA Energy Dashboard integratie (v2.4.18).

Registreert CloudEMS als `energy_platform` zodat alle gemeten
energiedata automatisch verschijnt in het standaard HA energiedashboard.

HA verwacht één of meer objecten die `async_get_solar_forecast` en/of
`async_get_cost_stat_id` implementeren. Wij bieden een minimale implementatie
die de geconfigureerde sensoren rapporteert als energiebronnen.

Documentatie:
  https://developers.home-assistant.io/docs/core/entity/energy
"""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.energy.data import (
    EnergyPreferencesUpdate,
    GridSourceType,
    SolarSourceType,
    GasSourceType,
    FlowFromGridType,
    FlowToGridType,
)
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_GRID_SENSOR, CONF_SOLAR_SENSOR, CONF_GAS_SENSOR,
    CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR,
    CONF_USE_SEPARATE_IE,
)

_LOGGER = logging.getLogger(__name__)


async def async_get_energy_info(hass: HomeAssistant) -> dict | None:
    """Geef CloudEMS-sensorinfo terug voor het HA energiedashboard.

    Geeft een dict terug compatibel met EnergyPreferencesUpdate.
    Wordt aangeroepen door HA's energy component bij initialisatie
    en wanneer de configuratie wijzigt.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None

    config = entries[0].data
    use_sep = config.get(CONF_USE_SEPARATE_IE, False)

    # ── Grid bron ─────────────────────────────────────────────────────────────
    grid_source: GridSourceType = {"type": "grid", "flow_from": [], "flow_to": [], "cost_adjustment_day": 0}

    if use_sep:
        import_eid = config.get(CONF_IMPORT_SENSOR, "")
        export_eid = config.get(CONF_EXPORT_SENSOR, "")
        if import_eid:
            grid_source["flow_from"].append({
                "type": "flow_from",
                "stat_energy_from": import_eid,
                "stat_cost": None,
                "entity_energy_price": None,
                "number_energy_price": None,
            })
        if export_eid:
            grid_source["flow_to"].append({
                "type": "flow_to",
                "stat_energy_to": export_eid,
                "stat_compensation": None,
                "entity_energy_price": None,
                "number_energy_price": None,
            })
    else:
        grid_eid = config.get(CONF_GRID_SENSOR, "")
        if grid_eid:
            grid_source["flow_from"].append({
                "type": "flow_from",
                "stat_energy_from": grid_eid,
                "stat_cost": None,
                "entity_energy_price": None,
                "number_energy_price": None,
            })

    sources: list = []
    if grid_source["flow_from"] or grid_source["flow_to"]:
        sources.append(grid_source)

    # ── Zonnepanelen ──────────────────────────────────────────────────────────
    solar_eid = config.get(CONF_SOLAR_SENSOR, "")
    if solar_eid:
        sources.append({
            "type": "solar",
            "stat_energy_from": solar_eid,
            "config_entry_solar_forecast": [],
        })

    # ── Gas ───────────────────────────────────────────────────────────────────
    gas_eid = config.get(CONF_GAS_SENSOR, "")
    if gas_eid:
        sources.append({
            "type": "gas",
            "stat_energy_from": gas_eid,
            "stat_cost": None,
            "entity_energy_price": None,
            "number_energy_price": None,
        })

    if not sources:
        _LOGGER.debug("CloudEMS energy platform: geen bronnen gevonden, slaat registratie over")
        return None

    _LOGGER.info(
        "CloudEMS energy platform: %d bron(nen) geregistreerd voor HA energiedashboard",
        len(sources),
    )
    return {"energy_sources": sources}
