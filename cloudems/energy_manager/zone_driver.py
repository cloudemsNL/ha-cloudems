# -*- coding: utf-8 -*-
"""CloudEMS — Zone Entiteit Driver (v2.6).

Auto-detecteert het type van elke climate-entiteit in een zone en
stuurt het juiste commando:

  TYPE_VT       Versatile Thermostat — stuurt via set_preset_mode
                Presets worden 1:1 gemapt naar VT preset-namen.
                Gebruiker kan mapping overschrijven in config.

  TYPE_TRV      TRV / generic thermostat — stuurt via set_temperature
                (direct setpoint)

  TYPE_AIRCO    Airco / split-unit — stuurt via set_hvac_mode + set_temperature
                Koelen of verwarmen op basis van preset + buitentemperatuur

  TYPE_SWITCH   Relais / switch — aan/uit op basis van heat_demand
                (voor eenvoudige CV-zone schakelaars)

Detectie-prioriteit:
  1. Config-override: zone_entity_types: {"climate.trv_x": "trv"}
  2. Integratie-platform (versatile_thermostat → vt)
  3. HVAC-modes (cool/dry → airco)
  4. Naam-keywords (trv, valve, airco, split, ...)
  5. Temperatuurbereik heuristiek

Copyright 2025 CloudEMS
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TYPE_VT     = "vt"       # Versatile Thermostat
TYPE_TRV    = "trv"      # Directe TRV / generic thermostat
TYPE_AIRCO  = "airco"    # Split-unit airco
TYPE_SWITCH = "switch"   # Relais aan/uit

# CloudEMS preset → Versatile Thermostat preset naam
# Gebruiker kan dit overschrijven via zone_vt_preset_map
DEFAULT_VT_PRESET_MAP: dict[str, str] = {
    "comfort":    "comfort",
    "eco":        "eco",
    "boost":      "boost",
    "sleep":      "sleep",
    "away":       "away",
    "solar":      "comfort",    # VT heeft geen solar-preset
    "houtfire":   "eco",        # kachel actief → TRV minimaal
    "eco_window": "frost",      # raam open → VT frost preset
}

VT_PLATFORMS = {"versatile_thermostat", "versatile_thermostat_climate"}

# Import bridge (lazy om circulaire imports te vermijden)
_VTHERM_COMMANDER = None

def _get_commander():
    global _VTHERM_COMMANDER
    if _VTHERM_COMMANDER is None:
        from .vtherm_bridge import VThermCommander
        _VTHERM_COMMANDER = VThermCommander()
    return _VTHERM_COMMANDER

AIRCO_NAME_KW = {"airco", "air_condition", "split", "warmtepomp",
                 "heat_pump", "heatpump", "daikin", "mitsubishi",
                 "sensibo", "toshiba", "panasonic", "lg_thinq"}
TRV_NAME_KW   = {"trv", "radiator", "klep", "valve", "kraan",
                 "thermkop", "tado", "eq3", "eurotronic"}


def _detect_entity_type(
    entity_id: str,
    state,
    platform: str,
    override: str | None = None,
) -> str:
    if override:
        return override

    if entity_id.startswith("switch."):
        return TYPE_SWITCH

    # Versatile Thermostat via platform
    if any(vtp in (platform or "").lower() for vtp in VT_PLATFORMS):
        return TYPE_VT

    hvac_modes = state.attributes.get("hvac_modes", []) if state else []
    name = (state.attributes.get("friendly_name") or entity_id).lower().replace(" ", "_") if state else entity_id.lower()

    # Airco: heeft cool/dry mode
    if any(m in hvac_modes for m in ("cool", "dry", "fan_only")):
        return TYPE_AIRCO
    if any(kw in name for kw in AIRCO_NAME_KW):
        return TYPE_AIRCO

    # TRV naam-keywords
    if any(kw in name for kw in TRV_NAME_KW):
        return TYPE_TRV

    # Heuristiek: heat-only + klein bereik → TRV
    if state:
        min_t = state.attributes.get("min_temp", 7)
        max_t = state.attributes.get("max_temp", 30)
        step  = state.attributes.get("target_temp_step", 0.5)
        if (set(hvac_modes) <= {"heat", "off"} and max_t <= 30
                and min_t >= 5 and step <= 0.5):
            return TYPE_TRV

    return TYPE_TRV  # veilige default voor climate.*


class ZoneEntityDriver:
    """Stuurt alle climate/switch entiteiten in één zone aan.

    Detecteert automatisch het type per entiteit en kiest de juiste
    HA-service-aanroep. Ondersteunt VT, TRV, airco en switch in dezelfde zone.
    """

    def __init__(
        self,
        zone_name: str,
        entity_ids: list[str],
        vt_preset_map: dict[str, str] | None = None,
        entity_type_overrides: dict[str, str] | None = None,
    ) -> None:
        self._zone        = zone_name
        self._entity_ids  = entity_ids
        self._vt_map      = {**DEFAULT_VT_PRESET_MAP, **(vt_preset_map or {})}
        self._overrides   = entity_type_overrides or {}
        # Cache: entity_id → detected type (herdetecteer als None)
        self._type_cache: dict[str, str] = {}

    def _get_type(self, eid: str, hass: "HomeAssistant") -> str:
        if eid in self._type_cache:
            return self._type_cache[eid]

        override = self._overrides.get(eid)
        state    = hass.states.get(eid)
        platform = self._get_platform(eid, hass)
        typ      = _detect_entity_type(eid, state, platform, override)
        self._type_cache[eid] = typ
        _LOGGER.debug("Zone %s: %s gedetecteerd als %s", self._zone, eid, typ)
        return typ

    def _get_platform(self, eid: str, hass: "HomeAssistant") -> str:
        try:
            from homeassistant.helpers import entity_registry as er
            entry = er.async_get(hass).async_get(eid)
            return entry.platform if entry else ""
        except Exception:
            return ""

    async def async_apply(
        self,
        hass: "HomeAssistant",
        preset_name: str,       # CloudEMS preset string
        target_temp: float,     # berekend doeltemperatuur (°C)
        heat_demand: bool,
        cool_demand: bool,
        outside_temp: float | None = None,
    ) -> list[str]:
        """Stuur alle entiteiten aan. Geeft lijst van aangestuurde entity_ids terug."""
        applied = []

        for eid in self._entity_ids:
            state = hass.states.get(eid)
            typ   = self._get_type(eid, hass)

            try:
                if typ == TYPE_VT:
                    await self._apply_vt(hass, eid, preset_name, state)
                    applied.append(eid)

                elif typ == TYPE_TRV:
                    await self._apply_trv(hass, eid, target_temp, state)
                    applied.append(eid)

                elif typ == TYPE_AIRCO:
                    await self._apply_airco(
                        hass, eid, preset_name, target_temp,
                        heat_demand, cool_demand, outside_temp, state
                    )
                    applied.append(eid)

                elif typ == TYPE_SWITCH:
                    await self._apply_switch(hass, eid, heat_demand)
                    applied.append(eid)

            except Exception as err:
                _LOGGER.warning("Zone %s: %s aansturen mislukt (%s): %s",
                                self._zone, eid, typ, err)

        return applied

    # ── VT aansturen ─────────────────────────────────────────────────────────

    async def _apply_vt(
        self, hass: "HomeAssistant", eid: str, preset_name: str, state
    ) -> None:
        """Stuur VTherm preset via VThermCommander (met conflict guard, lock check, fallback)."""
        commander = _get_commander()
        # Overschrijf preset map als zone een eigen map heeft
        if self._vt_map != DEFAULT_VT_PRESET_MAP:
            from .vtherm_bridge import VThermCommander
            commander = VThermCommander(preset_map=self._vt_map)

        available = list((state.attributes.get("preset_modes") or [])) if state else []
        await commander.async_set_preset(
            hass, eid, preset_name,
            available_presets=available,
            skip_if_overpowering=True,   # Niet ingrijpen als VTherm al power shedding doet
        )

    # ── TRV aansturen ────────────────────────────────────────────────────────

    async def _apply_trv(
        self, hass: "HomeAssistant", eid: str, target_temp: float, state
    ) -> None:
        if not state:
            return

        modes = state.attributes.get("hvac_modes", [])

        # HVAC mode
        target_hvac = "heat" if "heat" in modes else ("auto" if "auto" in modes else state.state)

        if state.state != target_hvac and target_hvac in modes:
            await hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": eid, "hvac_mode": target_hvac},
                blocking=False,
            )

        # Setpoint — alleen sturen als afwijking > 0.3°C
        cur_set = state.attributes.get("temperature")
        if cur_set is None or abs(float(cur_set) - target_temp) > 0.3:
            # Clamp naar entiteit min/max
            min_t = float(state.attributes.get("min_temp", 5))
            max_t = float(state.attributes.get("max_temp", 30))
            temp  = max(min_t, min(max_t, target_temp))
            # Rond af naar stapgrootte entiteit
            step  = float(state.attributes.get("target_temp_step", 0.5))
            temp  = round(round(temp / step) * step, 1)
            await hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": eid, "temperature": temp},
                blocking=False,
            )

    # ── Airco aansturen ──────────────────────────────────────────────────────

    async def _apply_airco(
        self, hass: "HomeAssistant", eid: str, preset_name: str,
        target_temp: float, heat_demand: bool, cool_demand: bool,
        outside_temp: float | None, state
    ) -> None:
        if not state:
            return

        modes = state.attributes.get("hvac_modes", [])

        # Bepaal HVAC mode voor airco
        if preset_name == "away":
            # Airco uit bij afwezigheid — tenzij vorstbeveiliging
            target_hvac = "off"
        elif preset_name == "eco_window":
            target_hvac = "off"   # raam open → airco uit
        elif cool_demand and "cool" in modes:
            target_hvac = "cool"
        elif cool_demand and "heat_cool" in modes:
            target_hvac = "heat_cool"
        elif heat_demand and "heat" in modes:
            target_hvac = "heat"
        elif heat_demand and "heat_cool" in modes:
            target_hvac = "heat_cool"
        elif preset_name in ("boost", "comfort", "solar") and "heat" in modes:
            # Airco als verwarming in winter
            target_hvac = "heat" if (outside_temp is None or outside_temp < 15) else "cool"
        else:
            target_hvac = "off"

        if state.state != target_hvac:
            if target_hvac == "off" and state.state == "off":
                pass  # Al uit
            else:
                await hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": eid, "hvac_mode": target_hvac},
                    blocking=False,
                )

        if target_hvac != "off":
            cur_set = state.attributes.get("temperature")
            if cur_set is None or abs(float(cur_set) - target_temp) > 0.5:
                min_t = float(state.attributes.get("min_temp", 16))
                max_t = float(state.attributes.get("max_temp", 30))
                temp  = max(min_t, min(max_t, target_temp))
                await hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": eid, "temperature": temp},
                    blocking=False,
                )

    # ── Switch aansturen ─────────────────────────────────────────────────────

    async def _apply_switch(
        self, hass: "HomeAssistant", eid: str, heat_demand: bool
    ) -> None:
        service = "turn_on" if heat_demand else "turn_off"
        st = hass.states.get(eid)
        cur = (st.state == "on") if st else None
        if cur is None or cur != heat_demand:
            await hass.services.async_call(
                "homeassistant", service, {"entity_id": eid}, blocking=False
            )

    def get_entity_types(self, hass: "HomeAssistant") -> dict[str, str]:
        """Geef huidige type-detectie terug voor alle entiteiten."""
        return {eid: self._get_type(eid, hass) for eid in self._entity_ids}

    def invalidate_cache(self) -> None:
        """Reset type-cache — aanroepen na config-wijziging."""
        self._type_cache.clear()
