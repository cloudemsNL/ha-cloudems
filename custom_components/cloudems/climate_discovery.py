# -*- coding: utf-8 -*-
"""CloudEMS — Klimaat Auto-Discovery (v2.6).

Scant alle climate.* entiteiten in HA en classificeert ze automatisch als:
  trv         Thermostatische radiatorkraan (Zigbee, Z-Wave, Tuya)
  airco       Airconditioning / split-unit warmtepomp
  thermostat  Centrale thermostaat (Nest, Honeywell, Tado, OTGateway)

Classificatie-basis (prioriteitsvolgorde):
  1. Integratie-platform naam (tado, nest, daikin, ...)
  2. HVAC-modes (cool/dry/fan_only → airco)
  3. Naam-keywords (trv, radiator, klep, airco, split, ...)
  4. Supported features (aux_heat → airco)
  5. Temperatuurbereik + stapgrootte heuristiek (5-30°C, 0.5 stap → TRV)

Per entiteit wordt ook de HA Area (kamer) opgehaald als die is ingesteld,
zodat de wizard zones automatisch kan voorstellen.
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TYPE_TRV        = "trv"
TYPE_AIRCO      = "airco"
TYPE_THERMOSTAT = "thermostat"
TYPE_UNKNOWN    = "unknown"

FEATURE_AUX_HEAT = 8

PLATFORM_TYPE: dict[str, str] = {
    "eq3btsmart": TYPE_TRV, "generic_thermostat": TYPE_TRV,
    "mqtt": TYPE_TRV, "zha": TYPE_TRV, "z2m": TYPE_TRV,
    "zigbee2mqtt": TYPE_TRV, "zwave_js": TYPE_TRV, "tuya": TYPE_TRV,
    "daikin": TYPE_AIRCO, "mitsubishi": TYPE_AIRCO, "midea_ac": TYPE_AIRCO,
    "panasonic_cc": TYPE_AIRCO, "toshiba_ac": TYPE_AIRCO,
    "lg_thinq": TYPE_AIRCO, "sensibo": TYPE_AIRCO,
    "intesishome": TYPE_AIRCO, "hisense_ac": TYPE_AIRCO, "broadlink": TYPE_AIRCO,
    "nest": TYPE_THERMOSTAT, "tado": TYPE_THERMOSTAT,
    "honeywell_home": TYPE_THERMOSTAT, "netatmo": TYPE_THERMOSTAT,
    "ecobee": TYPE_THERMOSTAT, "opentherm_gw": TYPE_THERMOSTAT,
    "otgw": TYPE_THERMOSTAT, "evohome": TYPE_THERMOSTAT,
    "homematic": TYPE_THERMOSTAT, "devireg": TYPE_THERMOSTAT,
}

NAME_KEYWORDS: list[tuple[str, str]] = [
    ("trv", TYPE_TRV), ("radiator", TYPE_TRV), ("klep", TYPE_TRV),
    ("valve", TYPE_TRV), ("kraan", TYPE_TRV), ("thermkop", TYPE_TRV),
    ("airco", TYPE_AIRCO), ("air_condition", TYPE_AIRCO),
    ("split", TYPE_AIRCO), ("warmtepomp", TYPE_AIRCO),
    ("heat_pump", TYPE_AIRCO), ("heatpump", TYPE_AIRCO),
    ("daikin", TYPE_AIRCO), ("mitsubishi", TYPE_AIRCO), ("sensibo", TYPE_AIRCO),
    ("nest", TYPE_THERMOSTAT), ("tado", TYPE_THERMOSTAT),
    ("honeywell", TYPE_THERMOSTAT), ("netatmo", TYPE_THERMOSTAT),
    ("otgw", TYPE_THERMOSTAT), ("opentherm", TYPE_THERMOSTAT),
    ("boiler", TYPE_THERMOSTAT), ("_cv", TYPE_THERMOSTAT), ("ketel", TYPE_THERMOSTAT),
]


def classify_climate_entity(entity_id: str, state, platform: str) -> str:
    name = ((state.attributes.get("friendly_name") or entity_id)
            .lower().replace(" ", "_"))
    hvac_modes = state.attributes.get("hvac_modes", [])

    # 1. Platform
    for plat, typ in PLATFORM_TYPE.items():
        if plat in (platform or "").lower():
            return typ

    # 2. HVAC-modes → airco
    if any(m in hvac_modes for m in ("cool", "dry", "fan_only", "heat_cool")):
        return TYPE_AIRCO

    # 3. Naam-keywords
    for kw, typ in NAME_KEYWORDS:
        if kw in name:
            return typ

    # 4. Supported features
    if state.attributes.get("supported_features", 0) & FEATURE_AUX_HEAT:
        return TYPE_AIRCO

    # 5. Bereik-heuristiek (TRV: heat-only, bereik 5-30°C, stap 0.5)
    min_t = state.attributes.get("min_temp", 7)
    max_t = state.attributes.get("max_temp", 30)
    step  = state.attributes.get("target_temp_step", 0.5)
    if (max_t <= 30 and min_t >= 5 and step <= 0.5
            and set(hvac_modes) <= {"heat", "off"}):
        return TYPE_TRV

    return TYPE_UNKNOWN


async def async_discover_climate_entities(hass: "HomeAssistant") -> list[dict]:
    """Scan alle climate.* entities.

    Geeft lijst van dicts terug:
      entity_id, friendly_name, type, area_id, area_name,
      hvac_modes, current_temp, target_temp, platform
    """
    from homeassistant.helpers import entity_registry as er, area_registry as ar, device_registry as dr

    ent_reg  = er.async_get(hass)
    area_reg = ar.async_get(hass)
    dev_reg  = dr.async_get(hass)

    # Platforms die virtuele/scheduling climate entities maken — nooit opnemen
    _VIRTUAL_PLATFORMS = frozenset({
        "cloudems", "climate_scheduler", "scheduler",
        "generic_thermostat", "climate_template",
    })
    _VIRTUAL_PATTERNS = ("climate_schedule", "climate_scheduler", "_schedule_", "_scheduler_")

    results = []
    for state in hass.states.async_all("climate"):
        eid = state.entity_id

        # Platform ophalen via entity registry
        entry    = ent_reg.async_get(eid)
        platform = ""
        area_id  = None
        if entry:
            if entry.disabled:
                continue
            platform = entry.platform or ""
            # Sla virtuele platforms over
            if platform in _VIRTUAL_PLATFORMS:
                continue
            area_id  = entry.area_id
            # Area via device als niet direct ingesteld
            if not area_id and entry.device_id:
                dev = dev_reg.async_get(entry.device_id)
                if dev:
                    area_id = dev.area_id

        # Sla entities over waarvan de entity_id op een scheduler/schedule wijst
        if any(pat in eid.lower() for pat in _VIRTUAL_PATTERNS):
            continue

        area_name = ""
        if area_id:
            area = area_reg.async_get_area(area_id)
            if area:
                area_name = area.name

        climate_type = classify_climate_entity(eid, state, platform)

        results.append({
            "entity_id":    eid,
            "friendly_name": state.attributes.get("friendly_name", eid),
            "type":         climate_type,
            "area_id":      area_id or "",
            "area_name":    area_name,
            "hvac_modes":   state.attributes.get("hvac_modes", []),
            "current_temp": state.attributes.get("current_temperature"),
            "target_temp":  state.attributes.get("temperature"),
            "platform":     platform,
        })

    results.sort(key=lambda x: (x["area_name"], x["type"], x["friendly_name"]))
    _LOGGER.info(
        "ClimateDiscovery: %d entiteiten gevonden (%d TRV, %d airco, %d thermostaat, %d onbekend)",
        len(results),
        sum(1 for r in results if r["type"] == TYPE_TRV),
        sum(1 for r in results if r["type"] == TYPE_AIRCO),
        sum(1 for r in results if r["type"] == TYPE_THERMOSTAT),
        sum(1 for r in results if r["type"] == TYPE_UNKNOWN),
    )
    return results


async def async_suggest_zones(hass: "HomeAssistant") -> list[dict]:
    """Groepeer ontdekte entiteiten per HA Area als zone-suggesties.

    Alleen entiteiten met een toegewezen HA-ruimte worden opgenomen.
    Systeemcontroles (ketelbesturing, warm water, handmatige modi) worden gefilterd.
    """
    entities = await async_discover_climate_entities(hass)

    # Naam-patronen die op systeembesturing wijzen, niet op een kamer-zone
    _SYSTEM_PATTERNS = (
        "central heating", "domestic hot water", "manual mode",
        "heating manual", "heating mode", "boiler mode", "zone valve",
        "hot water", "warm water", "warmwater", "tapwater",
        "cv water", "cv mode",
    )

    zones: dict[str, dict] = {}

    for e in entities:
        # Entiteiten zonder kamer-toewijzing zijn geen zones
        if not e["area_id"]:
            continue
        # Systeemcontroles uitsluiten op basis van naam
        fname_lower = e["friendly_name"].lower()
        if any(pat in fname_lower for pat in _SYSTEM_PATTERNS):
            _LOGGER.debug("ClimateDiscovery: sla systeemcontrol over: %s", e["entity_id"])
            continue

        area = e["area_name"]
        if area not in zones:
            zones[area] = {
                "zone_name":             area.lower().replace(" ", "_"),
                "zone_display_name":     area,
                "zone_climate_entities": [],
                "zone_heating_type":     "cv",
                "has_trv":   False,
                "has_airco": False,
                "has_thermostat": False,
            }

        zones[area]["zone_climate_entities"].append(e["entity_id"])
        if e["type"] == TYPE_TRV:
            zones[area]["has_trv"] = True
        elif e["type"] == TYPE_AIRCO:
            zones[area]["has_airco"] = True
        elif e["type"] == TYPE_THERMOSTAT:
            zones[area]["has_thermostat"] = True

    # Stel heating_type voor
    for z in zones.values():
        has_cv    = z["has_trv"] or z["has_thermostat"]
        has_airco = z["has_airco"]
        if has_cv and has_airco:
            z["zone_heating_type"] = "both"
        elif has_airco:
            z["zone_heating_type"] = "airco"
        else:
            z["zone_heating_type"] = "cv"

    return list(zones.values())
