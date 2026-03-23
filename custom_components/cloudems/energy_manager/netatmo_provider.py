# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Netatmo Sensor Provider — v1.0.0

Levert kamertemperaturen van Netatmo weerstations aan CloudEMS modules:
  - ShutterThermalLearner: kamertemperatuur per ruimte
  - ZoneClimateManager: actuele temperatuur per zone

HA integratie: homeassistant.components.netatmo (standaard, geen HACS)

Entity patronen:
  sensor.*netatmo*_temperature        (°C, kamer/buiten temperatuur)
  sensor.*netatmo*_humidity           (%, luchtvochtigheid)
  sensor.*netatmo*_co2                (ppm, CO2 niveau)
  sensor.*netatmo*_pressure           (hPa, luchtdruk — buiten)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)


@dataclass
class NetatmoRoom:
    name:      str
    temp_eid:  Optional[str] = None
    hum_eid:   Optional[str] = None
    co2_eid:   Optional[str] = None
    temp_c:    Optional[float] = None
    humidity:  Optional[float] = None
    co2_ppm:   Optional[float] = None


def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None


class NetatmoProvider(BatteryProvider):
    """Netatmo weerstation provider — levert kamertemperaturen aan CloudEMS.

    Geen batterij/solar functionaliteit — puur sensordata voor
    ShutterThermalLearner en ZoneClimateManager.
    """

    PROVIDER_ID    = "netatmo"
    PROVIDER_LABEL = "Netatmo"
    PROVIDER_ICON  = "mdi:thermometer"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._rooms: list[NetatmoRoom] = []
        self._outdoor_temp_eid: Optional[str] = None
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        self._discover_rooms()
        _LOGGER.info("NetatmoProvider: detected=%s rooms=%d",
                     self._detected, len(self._rooms))

    def _discover_rooms(self):
        """Detecteer alle Netatmo kamers via temperature sensoren."""
        seen_bases = set()
        self._rooms = []
        for st in self._hass.states.async_all("sensor"):
            s = st.entity_id.lower()
            if "netatmo" not in s or "temperature" not in s:
                continue
            # Basis-naam: alles voor _temperature
            base = s.replace("sensor.", "").replace("_temperature", "")
            if base in seen_bases:
                continue
            seen_bases.add(base)
            room = NetatmoRoom(
                name     = base.replace("netatmo_", "").replace("_", " ").title(),
                temp_eid = st.entity_id,
            )
            # Zoek humidity en CO2 voor dezelfde kamer
            for st2 in self._hass.states.async_all("sensor"):
                s2 = st2.entity_id.lower()
                if base not in s2: continue
                if "humidity" in s2:    room.hum_eid = st2.entity_id
                elif "co2" in s2:       room.co2_eid  = st2.entity_id
            # Detecteer buiten-module
            if "outdoor" in base or "buiten" in base or "outside" in base:
                self._outdoor_temp_eid = st.entity_id
            else:
                self._rooms.append(room)

    async def async_detect(self) -> bool:
        self._discover_rooms()
        return len(self._rooms) > 0

    def read_state(self) -> BatteryProviderState:
        for room in self._rooms:
            room.temp_c   = _rf(self._hass, room.temp_eid)
            room.humidity = _rf(self._hass, room.hum_eid)
            room.co2_ppm  = _rf(self._hass, room.co2_eid)

        outdoor_c = _rf(self._hass, self._outdoor_temp_eid)

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=any(r.temp_c is not None for r in self._rooms),
            raw={
                "rooms": [
                    {"name": r.name, "temp_c": r.temp_c,
                     "humidity": r.humidity, "co2_ppm": r.co2_ppm,
                     "temp_eid": r.temp_eid}
                    for r in self._rooms
                ],
                "outdoor_temp_c": outdoor_c,
            },
        )
        return self._last_state

    # Geen batterijsturing
    async def async_set_charge(self, power_w=None): return False
    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title=f"Netatmo gevonden ({len(self._rooms)} kamers)",
            description=(
                f"Kamertemperaturen van {len(self._rooms)} Netatmo modules beschikbaar. "
                "Wordt gebruikt door ShutterThermalLearner en klimaatbeheer."
            ),
            icon="mdi:thermometer",
        )

    def get_room_temps(self) -> dict[str, float]:
        """Geef {kamer_naam: temp_c} dict voor ShutterThermalLearner."""
        result = {}
        for room in self._rooms:
            if room.temp_c is not None:
                result[room.name] = room.temp_c
        return result

    def get_room_temp_entities(self) -> dict[str, str]:
        """Geef {kamer_naam: entity_id} dict."""
        return {r.name: r.temp_eid for r in self._rooms if r.temp_eid}

    def get_outdoor_temp_c(self) -> Optional[float]:
        return self._last_state.raw.get("outdoor_temp_c")


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(NetatmoProvider)
