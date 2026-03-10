# -*- coding: utf-8 -*-
"""
CloudEMS Energy Auto-Discover — v1.0.0

Leest de HA Energy dashboard configuratie en vertaalt die naar CloudEMS
config-flow velden. Wordt aangeroepen in async_step_user zodat de wizard
al ingevuld is met wat HA al weet.

HA Energy dashboard structuur (homeassistant.components.energy.data):
  grid_sources:
    - flow_from: [{stat_energy_from, stat_power_grid_consumption}]
    - flow_to:   [{stat_energy_to,   stat_power_grid_production}]
  solar_sources:
    - stat_power_production   (W sensor)
    - stat_energy_from_grid   (kWh sensor)
  battery_storage:
    - stat_energy_to:   batterij laden (kWh)
    - stat_energy_from: batterij ontladen (kWh)
    - flow_to_entity:   vermogen -> batterij
    - flow_from_entity: vermogen <- batterij
  device_consumption: [...]

Wat CloudEMS nodig heeft vs. wat Energy levert:
  grid_power_sensor   ← grid_sources[0].flow_from[0].stat_power_grid_consumption
  solar_sensor        ← solar_sources[0].stat_power_production (W) of afleiden uit kWh
  battery_sensor      ← battery_storage[0].flow_to_entity / flow_from_entity

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyDiscovery:
    """Resultaat van de Energy dashboard scan."""

    # Grid
    grid_power_sensor:    Optional[str] = None   # W sensor (netto)
    import_power_sensor:  Optional[str] = None   # W import (als apart)
    export_power_sensor:  Optional[str] = None   # W export (als apart)
    grid_energy_import:   Optional[str] = None   # kWh sensor (ter info)
    grid_energy_export:   Optional[str] = None   # kWh sensor (ter info)

    # Solar
    solar_sensors:        list[str] = field(default_factory=list)  # vermogen W per omvormer
    solar_energy_sensors: list[str] = field(default_factory=list)  # kWh sensoren (fallback)

    # Battery
    battery_power_in:     Optional[str] = None   # W laden
    battery_power_out:    Optional[str] = None   # W ontladen
    battery_energy_in:    Optional[str] = None   # kWh
    battery_energy_out:   Optional[str] = None   # kWh

    # Meta
    found_sources: list[str] = field(default_factory=list)   # welke bronnen gevonden
    confidence:    str = "none"   # none / partial / full

    def summary(self) -> str:
        """Korte samenvatting voor logging."""
        parts = []
        if self.grid_power_sensor: parts.append(f"grid={self.grid_power_sensor}")
        if self.solar_sensors:     parts.append(f"solar={len(self.solar_sensors)}x")
        if self.battery_power_in:  parts.append("battery=ja")
        return ", ".join(parts) if parts else "niets gevonden"

    def to_config_prefill(self) -> dict:
        """
        Vertaal naar CloudEMS config-dict die als pre-fill gebruikt kan worden.
        Alleen gevulde waarden worden teruggegeven.
        """
        result = {}

        # Grid
        if self.grid_power_sensor:
            result["grid_sensor"] = self.grid_power_sensor
        if self.import_power_sensor and self.export_power_sensor:
            result["use_separate_import_export"] = True
            result["import_power_sensor"]        = self.import_power_sensor
            result["export_power_sensor"]        = self.export_power_sensor

        # Solar — eerste omvormer als hoofd-PV sensor
        if self.solar_sensors:
            result["solar_sensor"] = self.solar_sensors[0]

        # Battery
        if self.battery_power_in or self.battery_power_out:
            # CloudEMS gebruikt één sensor met teken: + laden, - ontladen
            # Als er twee aparte zijn, nemen we 'in' als primair
            result["battery_sensor"] = self.battery_power_in or self.battery_power_out

        return result


async def async_discover_from_energy_dashboard(hass: HomeAssistant) -> EnergyDiscovery:
    """
    Lees de HA Energy dashboard configuratie en retourneer een EnergyDiscovery.

    Werkt ook als de energy component niet geladen is (geeft lege discovery terug).
    """
    disc = EnergyDiscovery()

    try:
        from homeassistant.components.energy import data as energy_data

        manager = await energy_data.async_get_manager(hass)
        prefs   = manager.data
        if prefs is None:
            _LOGGER.debug("CloudEMS auto-discover: Energy dashboard niet geconfigureerd")
            return disc

        _scan_grid(prefs, disc, hass)
        _scan_solar(prefs, disc, hass)
        _scan_battery(prefs, disc, hass)

        # Confidence bepalen
        found = sum([
            bool(disc.grid_power_sensor or disc.import_power_sensor),
            bool(disc.solar_sensors),
            bool(disc.battery_power_in or disc.battery_power_out),
        ])
        disc.confidence = ["none", "partial", "partial", "full"][min(found, 3)]

        _LOGGER.info(
            "CloudEMS auto-discover: %s (confidence=%s)",
            disc.summary(), disc.confidence,
        )

    except ImportError:
        _LOGGER.debug("CloudEMS auto-discover: energy component niet beschikbaar")
    except Exception as err:
        _LOGGER.warning("CloudEMS auto-discover: fout: %s", err)

    return disc


# ── Interne scan helpers ───────────────────────────────────────────────────────

def _scan_grid(prefs, disc: EnergyDiscovery, hass: HomeAssistant) -> None:
    """Scan grid_sources voor vermogenssensoren."""
    sources = getattr(prefs, "energy_sources", []) or []

    for src in sources:
        src_type = getattr(src, "type", None) or src.get("type", "")
        if src_type != "grid":
            continue

        disc.found_sources.append("grid")

        # flow_from = afname van net
        flow_from = getattr(src, "flow_from", None) or src.get("flow_from", []) or []
        for flow in flow_from:
            # Vermogenssensor (W) — dit is wat CloudEMS primair nodig heeft
            power = _get_attr(flow, "stat_power_grid_consumption")
            if power and _is_power_sensor(hass, power):
                if not disc.grid_power_sensor:
                    disc.grid_power_sensor = power
                else:
                    disc.import_power_sensor = power

            # kWh sensor (backup info)
            energy = _get_attr(flow, "stat_energy_from")
            if energy and not disc.grid_energy_import:
                disc.grid_energy_import = energy
                # Probeer een bijbehorende W sensor te raden als er nog geen is
                if not disc.grid_power_sensor:
                    guessed = _guess_power_from_energy(hass, energy)
                    if guessed:
                        disc.grid_power_sensor = guessed

        # flow_to = teruglevering
        flow_to = getattr(src, "flow_to", None) or src.get("flow_to", []) or []
        for flow in flow_to:
            power = _get_attr(flow, "stat_power_grid_production")
            if power and _is_power_sensor(hass, power):
                disc.export_power_sensor = power

            energy = _get_attr(flow, "stat_energy_to")
            if energy and not disc.grid_energy_export:
                disc.grid_energy_export = energy

        # Als we zowel import als export W hebben → separate mode
        if disc.import_power_sensor and disc.export_power_sensor:
            disc.grid_power_sensor = None  # laat separate mode prevaleren


def _scan_solar(prefs, disc: EnergyDiscovery, hass: HomeAssistant) -> None:
    """Scan solar_sources voor PV-vermogenssensoren."""
    sources = getattr(prefs, "energy_sources", []) or []

    for src in sources:
        src_type = getattr(src, "type", None) or src.get("type", "")
        if src_type != "solar":
            continue

        disc.found_sources.append("solar")

        # Vermogenssensor (W) — primair
        power = _get_attr(src, "stat_power_production")
        if power and _is_power_sensor(hass, power):
            if power not in disc.solar_sensors:
                disc.solar_sensors.append(power)
            continue

        # kWh sensor (fallback) — probeer W equivalent te raden
        energy = _get_attr(src, "stat_energy_from_grid") or _get_attr(src, "stat_energy_from")
        if energy:
            disc.solar_energy_sensors.append(energy)
            guessed = _guess_power_from_energy(hass, energy)
            if guessed and guessed not in disc.solar_sensors:
                disc.solar_sensors.append(guessed)


def _scan_battery(prefs, disc: EnergyDiscovery, hass: HomeAssistant) -> None:
    """Scan battery_storage voor vermogenssensoren."""
    sources = getattr(prefs, "energy_sources", []) or []

    for src in sources:
        src_type = getattr(src, "type", None) or src.get("type", "")
        if src_type != "battery":
            continue

        disc.found_sources.append("battery")

        # Vermogenssensoren
        power_in  = _get_attr(src, "flow_to_entity")   # W naar batterij
        power_out = _get_attr(src, "flow_from_entity")  # W uit batterij

        if power_in and _is_power_sensor(hass, power_in):
            disc.battery_power_in = power_in
        if power_out and _is_power_sensor(hass, power_out):
            disc.battery_power_out = power_out

        # kWh
        disc.battery_energy_in  = _get_attr(src, "stat_energy_to")
        disc.battery_energy_out = _get_attr(src, "stat_energy_from")


# ── Utility helpers ───────────────────────────────────────────────────────────

def _get_attr(obj, key: str):
    """Haal attribuut op uit dataclass of dict."""
    if hasattr(obj, key):
        return getattr(obj, key) or None
    if isinstance(obj, dict):
        return obj.get(key) or None
    return None


def _is_power_sensor(hass: HomeAssistant, entity_id: str) -> bool:
    """
    Controleer of entity_id waarschijnlijk een vermogenssensor (W/kW) is,
    niet een energiesensor (kWh).
    """
    if not entity_id:
        return False
    # kWh-sensoren eindigen vrijwel altijd op _energy, _kwh, of staan in statistics
    lower = entity_id.lower()
    if any(s in lower for s in ("_energy", "_kwh", "_wh", "consumption", "production_total")):
        return False

    state = hass.states.get(entity_id)
    if state is None:
        return True  # geef benefit of the doubt

    unit = (state.attributes.get("unit_of_measurement") or "").lower()
    # Accepteer W en kW, afwijzen van kWh/MWh/Wh
    if unit in ("w", "kw", "mw"):
        return True
    if unit in ("kwh", "mwh", "wh"):
        return False
    # Geen unit → accepteren (kan een berekende sensor zijn)
    return True


def _guess_power_from_energy(hass: HomeAssistant, energy_entity: str) -> Optional[str]:
    """
    Probeer vanuit een kWh-sensor de bijbehorende W-sensor te raden.
    Strategie: vervang '_energy' → '_power', '_kwh' → '_power', etc.
    en controleer of de entity bestaat.
    """
    candidates = []
    base = energy_entity

    for suffix, replacement in [
        ("_energy_kwh", "_power"),
        ("_energy",     "_power"),
        ("_kwh",        "_power_w"),
        ("_total",      "_power"),
    ]:
        if base.endswith(suffix):
            candidate = base[:-len(suffix)] + replacement
            candidates.append(candidate)

    # Probeer ook simpele vervanging in de naam
    for old, new in [("energy", "power"), ("kwh", "power"), ("wh", "power")]:
        if old in base:
            candidates.append(base.replace(old, new))

    for c in candidates:
        state = hass.states.get(c)
        if state and _is_power_sensor(hass, c):
            return c

    return None
