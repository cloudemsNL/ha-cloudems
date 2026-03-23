# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — LG ThinQ & Mitsubishi MelCloud klimaat-sturing v1.0.0

Voegt merkspecifieke EPEX-sturing toe voor:
  - LG ThinQ airco (lg_thinq HA integratie)
  - Mitsubishi MelCloud (melcloud HACS integratie)
  - Toshiba AC (toshiba_ac HACS integratie)

Works together with zone_climate_manager.py — deze module levert
merkspecifieke entity-detectie en vermogensdata.

LG ThinQ entity patronen:
  climate.lg_*                     → Klimaatentiteit
  sensor.lg_*_energy_current_consumption  → Actueel verbruik (W)
  sensor.lg_*_total_energy_used    → Dagtotaal (kWh)

MelCloud entity patronen:
  climate.melcloud_*               → Klimaatentiteit
  sensor.melcloud_*_wifi_signal_strength → Verbindingsstatus

Toshiba AC entity patronen:
  climate.toshiba_*                → Klimaatentiteit
  sensor.toshiba_*_indoor_temperature → Kamertemperatuur
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── Brand detection patterns ────────────────────────────────────────────────────

BRAND_PATTERNS = {
    "lg_thinq": {
        "label":        "LG ThinQ",
        "icon":         "mdi:air-conditioner",
        "climate_prefix": ("lg_", "lgthinq_"),
        "power_keywords": ("energy_current_consumption", "power_consumption", "current_power"),
        "energy_keywords": ("total_energy_used", "energy_total"),
        "setup_url":    "https://www.home-assistant.io/integrations/lg_thinq/",
        "tip":          "LG ThinQ: real-time verbruik beschikbaar per unit.",
    },
    "melcloud": {
        "label":        "Mitsubishi MelCloud",
        "icon":         "mdi:air-conditioner",
        "climate_prefix": ("melcloud_",),
        "power_keywords": ("daily_energy_consumed", "power"),
        "energy_keywords": ("daily_energy_consumed",),
        "setup_url":    "https://github.com/kilowatt/ha-melcloud",
        "tip":          "MelCloud: verbruik beschikbaar als dagkWh. Realtime W via Shelly/smart plug aanbevolen.",
    },
    "toshiba_ac": {
        "label":        "Toshiba AC",
        "icon":         "mdi:air-conditioner",
        "climate_prefix": ("toshiba_",),
        "power_keywords": ("power_selection", "power"),
        "energy_keywords": ("energy",),
        "setup_url":    "https://github.com/h4de5/home-assistant-toshiba_ac",
        "tip":          "Toshiba AC: basisverbruik via geschat vermogen op basis van setpoint en modus.",
    },
}


@dataclass
class BrandClimateDevice:
    """One detected merkspecifiek klimaatapparaat."""
    brand:          str
    brand_label:    str
    climate_entity: str
    power_entity:   Optional[str]   = None
    energy_entity:  Optional[str]   = None
    area_id:        Optional[str]   = None
    area_name:      str             = ""
    tip:            str             = ""


class LGMitsubishiClimateDetector:
    """
    Detecteert LG ThinQ, Mitsubishi MelCloud en Toshiba AC apparaten
    en koppelt ze aan vermogenssensoren voor EPEX-gestuurde sturing.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass    = hass
        self._devices: list[BrandClimateDevice] = []

    async def async_detect(self) -> list[BrandClimateDevice]:
        """Detecteer alle merkspecifieke klimaatapparaten."""
        from homeassistant.helpers import entity_registry as er, area_registry as ar

        ent_reg  = er.async_get(self._hass)
        area_reg = ar.async_get(self._hass)
        devices  = []

        for brand_id, pattern in BRAND_PATTERNS.items():
            prefixes = pattern["climate_prefix"]

            # Zoek climate entiteiten voor dit merk
            for state in self._hass.states.async_all("climate"):
                eid = state.entity_id.lower()
                if not any(p in eid for p in prefixes):
                    continue

                # Haal area op
                entry    = ent_reg.async_get(state.entity_id)
                area_id  = entry.area_id if entry else None
                area_name = ""
                if area_id:
                    area = area_reg.async_get_area(area_id)
                    if area:
                        area_name = area.name

                # Find associated power sensor
                power_entity  = self._find_sensor(state.entity_id, pattern["power_keywords"])
                energy_entity = self._find_sensor(state.entity_id, pattern["energy_keywords"])

                device = BrandClimateDevice(
                    brand          = brand_id,
                    brand_label    = pattern["label"],
                    climate_entity = state.entity_id,
                    power_entity   = power_entity,
                    energy_entity  = energy_entity,
                    area_id        = area_id,
                    area_name      = area_name,
                    tip            = pattern["tip"],
                )
                devices.append(device)
                _LOGGER.info(
                    "LGMitsubishiClimateDetector: %s gevonden: %s (power=%s, area=%s)",
                    brand_id, state.entity_id, power_entity, area_name
                )

        self._devices = devices
        return devices

    def _find_sensor(self, climate_entity: str, keywords: tuple) -> Optional[str]:
        """Zoek sensor die bij klimaatentiteit hoort op basis van naam en keywords."""
        # Get base name (bijv. "lg_woonkamer" uit "climate.lg_woonkamer")
        base = climate_entity.split(".")[-1].lower()
        # Strip known suffixes
        for suffix in ("_climate", "_ac", "_airco", "_heat_pump"):
            base = base.replace(suffix, "")

        for state in self._hass.states.async_all("sensor"):
            eid = state.entity_id.lower()
            if base in eid and any(k in eid for k in keywords):
                return state.entity_id
        return None

    @property
    def devices(self) -> list[BrandClimateDevice]:
        return list(self._devices)

    def get_power_w(self, device: BrandClimateDevice) -> Optional[float]:
        """Get current power for a device (W)."""
        if not device.power_entity:
            return None
        state = self._hass.states.get(device.power_entity)
        if not state or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def get_summary(self) -> list[dict]:
        """Overview for coordinator data / dashboard."""
        result = []
        for d in self._devices:
            power_w = self.get_power_w(d)
            cs = self._hass.states.get(d.climate_entity)
            result.append({
                "brand":          d.brand,
                "brand_label":    d.brand_label,
                "entity_id":      d.climate_entity,
                "area_name":      d.area_name,
                "hvac_mode":      cs.state if cs else "unknown",
                "power_w":        power_w,
                "power_entity":   d.power_entity,
                "tip":            d.tip,
            })
        return result
