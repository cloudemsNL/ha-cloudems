# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Climate Platform (v1.0.0)

Registreert één climate.cloudems_<zone> entity per ontdekte zone.
CloudEMS IS de thermostaat — onderliggend stuurt het TRV's, airco's
en de CV-ketel aan via de bestaande VirtualZone/ZoneEntityDriver.

Entity-ID patroon:  climate.cloudems_woonkamer
Friendly name:      CloudEMS · Woonkamer
HVAC modes:         heat  /  off  /  auto
Presets:            comfort  eco  boost  sleep  away  solar

Stroom:
  HA-gebruiker zet setpoint of preset
    → CloudEMSClimateEntity roept zone.set_temp / zone.set_override aan
    → VirtualZone neemt het over in de volgende coordinator-update
    → Onderliggende TRV/airco worden aangestuurd

Copyright 2025-2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.components.climate.const import PRESET_NONE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sub_devices import sub_device_info, SUB_ZONE_CLIMATE

_LOGGER = logging.getLogger(__name__)

# CloudEMS preset → HA preset string (wat HA toont in UI)
PRESET_MAP: dict[str, str] = {
    "comfort":    "comfort",
    "eco":        "eco",
    "boost":      "boost",
    "sleep":      "sleep",
    "away":       "away",
    "solar":      "solar",
    "eco_window": "eco_window",
    "houtfire":   "houtfire",
}
HA_PRESETS = list(PRESET_MAP.values())

# HVAC mode → CloudEMS preset bij handmatige mode-wijziging
HVAC_TO_PRESET = {
    HVACMode.HEAT: "comfort",
    HVACMode.AUTO: "comfort",
    HVACMode.OFF:  "away",
}

# CloudEMS preset → HVAC mode (voor de state die HA toont)
PRESET_TO_HVAC = {
    "comfort":    HVACMode.HEAT,
    "eco":        HVACMode.HEAT,
    "boost":      HVACMode.HEAT,
    "sleep":      HVACMode.HEAT,
    "solar":      HVACMode.AUTO,
    "away":       HVACMode.OFF,
    "eco_window": HVACMode.OFF,
    "houtfire":   HVACMode.HEAT,
}

# Preset → HVAC action (wat HA toont als de zone actief is)
def _hvac_action(snap) -> str:
    if snap is None:
        return HVACAction.IDLE
    if snap.heat_demand:
        return HVACAction.HEATING
    if snap.cool_demand:
        return HVACAction.COOLING
    return HVACAction.IDLE


def _slugify(name: str) -> str:
    """Woonkamer → woonkamer, 'Slaap kamer' → slaap_kamer."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _zone_slug(area_name: str, area_entry=None) -> str:
    """
    Genereer een entity_id slug met optionele verdieping.
    Als de HA area een floor_id heeft: climate.cloudems_<floor>_<room>
    Anders: climate.cloudems_<room>
    Voorbeeld: climate.cloudems_begane_grond_woonkamer
    """
    room_slug = _slugify(area_name)
    if area_entry is not None:
        floor_id = getattr(area_entry, "floor_id", None)
        if floor_id:
            floor_slug = _slugify(str(floor_id))
            return f"{floor_slug}_{room_slug}"
    return room_slug


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Registreer één climate entity per ontdekte zone."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Wacht tot de zone_climate manager beschikbaar is
    zone_mgr = getattr(coordinator, "_zone_climate", None)
    if not zone_mgr:
        _LOGGER.debug("CloudEMS climate: zone_climate_manager niet actief — geen entities")
        return

    zones = getattr(zone_mgr, "_zones", [])
    if not zones:
        _LOGGER.debug("CloudEMS climate: geen zones ontdekt")
        return

    # Filter zones op basis van climate_zones_enabled (per-zone toggle in flow)
    from .const import CONF_CLIMATE_ZONES_ENABLED
    cfg_all = {**entry.data, **entry.options}
    enabled_zones = cfg_all.get(CONF_CLIMATE_ZONES_ENABLED)  # None = alles aan (backwards compat)

    def _is_enabled(zone) -> bool:
        if not enabled_zones:
            return True  # niets geconfigureerd → alles aan
        import re as _re
        slug = _re.sub(r"[^a-z0-9]+", "_", zone._area_name.lower()).strip("_")
        return zone._area_id in enabled_zones or slug in enabled_zones

    active_zones = [z for z in zones if _is_enabled(z)]

    if not active_zones:
        _LOGGER.debug("CloudEMS climate: alle zones uitgeschakeld in config")
        return

    # Hub parent device + zone entities
    entities = [CloudEMSClimateHub(coordinator, entry)]
    entities += [
        CloudEMSClimateEntity(coordinator, entry, zone)
        for zone in active_zones
    ]
    _LOGGER.info(
        "CloudEMS climate: hub + %d zone-entities aangemaakt (%d van %d zones actief)",
        len(active_zones), len(active_zones), len(zones),
    )
    async_add_entities(entities, update_before_add=True)



class CloudEMSClimateHub(CoordinatorEntity, ClimateEntity):
    """
    Virtueel hub-device 'CloudEMS Klimaat'.
    Fungeert als parent voor alle Zone Thermostaat entities zodat ze
    netjes gegroepeerd zijn in HA onder één device.
    Toont de gemiddelde temperatuur van alle actieve zones.
    """
    _attr_has_entity_name         = False
    _attr_name                    = "CloudEMS Klimaat"
    _attr_temperature_unit        = UnitOfTemperature.CELSIUS
    _attr_hvac_modes              = [HVACMode.AUTO, HVACMode.OFF]
    _attr_supported_features      = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    _attr_min_temp                = 5.0
    _attr_max_temp                = 30.0

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate_hub"
        self.entity_id       = "climate.cloudems_hub"

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_ZONE_CLIMATE)

    @property
    def current_temperature(self) -> float | None:
        zone_data = (self.coordinator.data or {}).get("zone_climate", {})
        snaps = zone_data.get("zones", {}) if isinstance(zone_data, dict) else {}
        temps = [s.current_temp for s in snaps.values()
                 if hasattr(s, "current_temp") and s.current_temp is not None]
        return round(sum(temps) / len(temps), 1) if temps else None

    @property
    def target_temperature(self) -> float | None:
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.AUTO

    @property
    def hvac_action(self) -> str:
        zone_data = (self.coordinator.data or {}).get("zone_climate", {})
        snaps = zone_data.get("zones", {}) if isinstance(zone_data, dict) else {}
        heating = any(getattr(s, "heat_demand", False) for s in snaps.values())
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        zone_data = (self.coordinator.data or {}).get("zone_climate", {})
        snaps = zone_data.get("zones", {}) if isinstance(zone_data, dict) else {}
        return {"actieve_zones": sum(1 for s in snaps.values() if getattr(s, "heat_demand", False)),
                "totaal_zones":  len(snaps)}

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        pass  # Hub heeft geen eigen sturing

    async def async_turn_on(self) -> None:
        pass

    async def async_turn_off(self) -> None:
        pass


class CloudEMSClimateEntity(CoordinatorEntity, ClimateEntity):
    """
    Een CloudEMS zone als native HA climate entity.

    Eén entity per VirtualZone (= HA area).
    Ontvangt updates via CoordinatorEntity push.
    Setpoint- en presetwijzigingen worden direct doorgegeven
    aan de VirtualZone voor verwerking in de volgende update-cyclus.
    """

    _attr_has_entity_name          = False
    _attr_temperature_unit         = UnitOfTemperature.CELSIUS
    _attr_hvac_modes               = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
    _attr_preset_modes             = HA_PRESETS
    _attr_supported_features       = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp                 = 5.0
    _attr_max_temp                 = 30.0
    _attr_target_temperature_step  = 0.5

    def __init__(self, coordinator, entry: ConfigEntry, zone) -> None:
        super().__init__(coordinator)
        self._entry      = entry
        self._zone       = zone          # VirtualZone object
        self._area_id    = zone._area_id
        self._area_name  = zone._area_name
        area_entry = getattr(zone, "_area_entry", None)
        slug             = _zone_slug(self._area_name, area_entry)
        self._attr_unique_id     = f"{entry.entry_id}_climate_{self._area_id}"
        self._attr_name          = f"CloudEMS · {self._area_name}"
        self.entity_id           = f"climate.cloudems_{slug}"
        self._pending_preset: str | None = None
        self._pending_temp:   float | None = None

    # ── Device info ─────────────────────────────────────────────────────────

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_ZONE_CLIMATE)


    # ── State lezen uit coordinator data ────────────────────────────────────

    @property
    def _snap(self):
        """Laatste ZoneSnapshot voor deze zone."""
        zone_data = (self.coordinator.data or {}).get("zone_climate", {})
        # zone_climate is een dict area_id → ZoneSnapshot (of serialized dict)
        snaps = zone_data.get("zones", {}) if isinstance(zone_data, dict) else {}
        return snaps.get(self._area_id) or self._zone._last_snap

    @property
    def current_temperature(self) -> float | None:
        snap = self._snap
        if snap and hasattr(snap, "current_temp"):
            return snap.current_temp
        return self._zone._last_temp

    @property
    def target_temperature(self) -> float | None:
        snap = self._snap
        if snap and hasattr(snap, "target_temp"):
            return snap.target_temp
        # Fallback: lees uit zone presettemp
        preset = self._zone._preset
        return self._zone._temps.get(preset, 20.0)

    @property
    def hvac_mode(self) -> HVACMode:
        snap = self._snap
        preset = (snap.preset.value if snap and hasattr(snap, "preset") else "comfort")
        return PRESET_TO_HVAC.get(preset, HVACMode.HEAT)

    @property
    def hvac_action(self) -> str:
        return _hvac_action(self._snap)

    @property
    def preset_mode(self) -> str:
        snap = self._snap
        if snap and hasattr(snap, "preset"):
            return snap.preset.value
        return self._zone._preset.value if self._zone._preset else "comfort"

    @property
    def extra_state_attributes(self) -> dict:
        snap = self._snap
        if not snap:
            return {"zone": self._area_name}
        attrs: dict[str, Any] = {
            "zone":            self._area_name,
            "preset_reason":   snap.reason if hasattr(snap, "reason") else "",
            "heat_demand":     snap.heat_demand if hasattr(snap, "heat_demand") else False,
            "cool_demand":     snap.cool_demand if hasattr(snap, "cool_demand") else False,
            "best_source":     snap.best_source if hasattr(snap, "best_source") else "",
            "source_reason":   snap.source_reason if hasattr(snap, "source_reason") else "",
            "cost_today_eur":  snap.cost_today if hasattr(snap, "cost_today") else 0.0,
            "cost_month_eur":  snap.cost_month if hasattr(snap, "cost_month") else 0.0,
            "window_open":     snap.window_open if hasattr(snap, "window_open") else False,
            "preheat_min":     snap.preheat_min if hasattr(snap, "preheat_min") else 0,
            "entities":        snap.entities if hasattr(snap, "entities") else [],
        }
        if hasattr(snap, "stove_advice") and snap.stove_advice and snap.stove_advice.should_light:
            attrs["stove_advice"]      = snap.stove_advice.reason
            attrs["stove_saving_day"]  = snap.stove_advice.saving_eur_day
        # v4.2.1: toon welke fysieke apparaten deze zone aanstuurt (zichtbaar in HA entiteit)
        zone_entities = getattr(self._zone, "_entities", {})
        attrs["gekoppelde_apparaten"] = [
            eid for eid in zone_entities.keys()
            if not eid.startswith("climate.cloudems_")
        ]
        return attrs

    # ── Commando's van HA ────────────────────────────────────────────────────

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Gebruiker zet handmatig setpoint in HA UI."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp = round(float(temp) * 2) / 2   # afronden op 0.5°C
        _LOGGER.debug("CloudEMS %s: setpoint → %.1f°C", self._area_name, temp)

        # Zet het comfort-setpoint van de zone + activeer comfort override
        from .energy_manager.zone_climate_manager import Preset
        self._zone.set_temp(Preset.COMFORT, temp)
        self._zone.set_override(Preset.COMFORT, hours=4.0)
        self._pending_temp = temp
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Gebruiker kiest preset in HA UI."""
        _LOGGER.debug("CloudEMS %s: preset → %s", self._area_name, preset_mode)
        from .energy_manager.zone_climate_manager import Preset
        try:
            p = Preset(preset_mode)
        except ValueError:
            _LOGGER.warning("CloudEMS %s: onbekende preset '%s'", self._area_name, preset_mode)
            return
        self._zone.set_override(p, hours=4.0)
        self._pending_preset = preset_mode
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Gebruiker schakelt HVAC mode."""
        _LOGGER.debug("CloudEMS %s: hvac_mode → %s", self._area_name, hvac_mode)
        from .energy_manager.zone_climate_manager import Preset
        preset_name = HVAC_TO_PRESET.get(hvac_mode, "comfort")
        try:
            p = Preset(preset_name)
        except ValueError:
            return
        # OFF = away (vorstbeveiliging actief), AUTO/HEAT = resume comfort
        hours = 24.0 if hvac_mode == HVACMode.OFF else 4.0
        self._zone.set_override(p, hours=hours)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # ── CoordinatorEntity callback ───────────────────────────────────────────

    def _handle_coordinator_update(self) -> None:
        """Coordinator heeft nieuwe data — reset pending state."""
        self._pending_preset = None
        self._pending_temp   = None
        super()._handle_coordinator_update()
