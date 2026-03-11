# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS Testmodus / Simulator.

Overschrijft live sensorwaarden met gesimuleerde input.
Injecteert virtuele HA states voor zone-temperaturen en houtkachels,
zodat SmartClimateManager, WoodStoveDetector en alle andere modules
volledig transparant gesimuleerde waarden zien — zonder extra code
in die modules.

Leerprocessen worden BEVROREN zolang de simulator actief is.
Historische data en leermodellen worden nooit aangeraakt.

Gebruik:
    # Energie + zone-temperaturen + houtkachel tegelijk:
    service: cloudems.simulator_set
    data:
      grid_w: 4000
      pv_w: 1200
      outdoor_temp_c: 5
      zone_temps:
        woonkamer: 17.5
        slaapkamer: 15.0
      stove_temps:
        woonkamer: 145.0   # graden kachelpijp — boven drempel = brandend
      timeout_min: 30
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

SIMULATOR_TIMEOUT_DEFAULT_MIN = 30

# Velden die direct in de coordinator data dict worden overschreven
SIMULATABLE_FIELDS = [
    "grid_w",
    "pv_w",
    "battery_soc",
    "battery_w",
    "l1_w",
    "l2_w",
    "l3_w",
    "gas_m3h",
    "outdoor_temp_c",
    "epex_now",
]

_VIRTUAL_ZONE_TEMP_PREFIX = "sensor.cloudems_sim_zone_"
_VIRTUAL_STOVE_PREFIX     = "sensor.cloudems_sim_stove_"


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


@dataclass
class SimulatorState:
    active: bool = False
    activated_at: Optional[datetime] = None
    timeout_s: int = SIMULATOR_TIMEOUT_DEFAULT_MIN * 60
    overrides: dict = field(default_factory=dict)
    zone_temps: dict = field(default_factory=dict)
    stove_temps: dict = field(default_factory=dict)
    note: str = ""


class CloudEMSSimulator:
    """Test-mode simulator met virtual state injection voor klimaatzones.

    - Energie/prijs/batterij waarden worden in coordinator data overschreven.
    - Zone- en kacheltemperaturen worden als echte HA states geinjected via
      hass.states.async_set(), zodat SmartClimateManager en WoodStoveDetector
      ze transparant oppikken.
    - Bij deactivatie worden virtuele states verwijderd.
    - Leerprocessen worden bevroren via coordinator.learning_frozen.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        self._state = SimulatorState()
        self._virtual_entities: set = set()
        # Zone naam -> lijst van echte sensor entity IDs
        self._zone_temp_sensors: dict = {}
        # Zone naam -> echte stove sensor entity ID of None
        self._zone_stove_sensors: dict = {}

    # ------------------------------------------------------------------
    # Registratie
    # ------------------------------------------------------------------

    def register_zones(self, smart_climate_manager: Any) -> None:
        """Registreer zones zodat we de juiste sensoren kunnen injecteren.
        Wordt aangeroepen door coordinator na SmartClimateManager.async_setup().
        """
        if smart_climate_manager is None:
            return
        try:
            for zone in smart_climate_manager._zones:
                name = zone._name
                self._zone_temp_sensors[name] = list(getattr(zone, "_temp_sensors", []))
                stove_sensor = None
                if getattr(zone, "_stove", None):
                    stove_sensor = zone._stove._sensor
                self._zone_stove_sensors[name] = stove_sensor
            _LOGGER.debug(
                "Simulator: %d zones geregistreerd: %s",
                len(self._zone_temp_sensors),
                list(self._zone_temp_sensors.keys()),
            )
        except Exception as err:
            _LOGGER.debug("register_zones fout (niet fataal): %s", err)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._state.active

    @property
    def remaining_seconds(self) -> int:
        if not self._state.active or self._state.activated_at is None:
            return 0
        elapsed = (datetime.now() - self._state.activated_at).total_seconds()
        return max(0, int(self._state.timeout_s - elapsed))

    @property
    def remaining_min(self) -> int:
        return self.remaining_seconds // 60

    def activate(
        self,
        overrides: dict,
        zone_temps: Optional[dict] = None,
        stove_temps: Optional[dict] = None,
        timeout_min: int = SIMULATOR_TIMEOUT_DEFAULT_MIN,
        note: str = "",
    ) -> None:
        """Activeer de simulator."""
        self._state = SimulatorState(
            active=True,
            activated_at=datetime.now(),
            timeout_s=timeout_min * 60,
            overrides={k: v for k, v in overrides.items() if k in SIMULATABLE_FIELDS},
            zone_temps=dict(zone_temps or {}),
            stove_temps=dict(stove_temps or {}),
            note=note,
        )
        _LOGGER.warning(
            "CloudEMS TESTMODUS ACTIEF — energie: %s | zones: %s | kachels: %s | timeout: %d min",
            list(self._state.overrides.keys()),
            list(self._state.zone_temps.keys()),
            list(self._state.stove_temps.keys()),
            timeout_min,
        )
        if self._hass:
            self._hass.async_create_task(self._inject_all_virtual_states())
        self._send_notification()

    def update_zone_temp(self, zone: str, temp_c: float) -> None:
        """Update zone-temperatuur terwijl simulator actief is."""
        if not self._state.active:
            _LOGGER.warning("simulator_zone_temp: simulator is niet actief")
            return
        self._state.zone_temps[zone] = temp_c
        if self._hass:
            self._hass.async_create_task(self._inject_zone_temp(zone, temp_c))

    def update_stove_temp(self, zone: str, temp_c: float) -> None:
        """Update houtkachel-temperatuur terwijl simulator actief is."""
        if not self._state.active:
            _LOGGER.warning("simulator_stove_temp: simulator is niet actief")
            return
        self._state.stove_temps[zone] = temp_c
        if self._hass:
            self._hass.async_create_task(self._inject_stove_temp(zone, temp_c))

    def deactivate(self, reason: str = "handmatig") -> None:
        """Deactiveer en verwijder virtual states."""
        if self._state.active:
            _LOGGER.warning("CloudEMS testmodus gestopt (%s)", reason)
            self._state.active = False
            if self._hass:
                self._hass.async_create_task(self._remove_virtual_states())
            self._clear_notification()

    def apply(self, data: dict) -> dict:
        """Pas gesimuleerde energie/prijs/batterij waarden toe op data dict."""
        if not self._state.active:
            return data

        if self.remaining_seconds <= 0:
            self.deactivate("auto-timeout")
            return data

        data["_simulated"] = True
        data["_sim_remaining_min"] = self.remaining_min
        data["_sim_fields"] = (
            list(self._state.overrides.keys())
            + [f"zone:{z}" for z in self._state.zone_temps]
            + [f"stove:{z}" for z in self._state.stove_temps]
        )

        for key, val in self._state.overrides.items():
            data[key] = val

        return data

    def get_status(self) -> dict:
        return {
            "active":           self._state.active,
            "remaining_min":    self.remaining_min,
            "simulated_fields": (
                list(self._state.overrides.keys())
                + [f"zone:{z}" for z in self._state.zone_temps]
                + [f"stove:{z}" for z in self._state.stove_temps]
            ),
            "zone_temps":       dict(self._state.zone_temps),
            "stove_temps":      dict(self._state.stove_temps),
            "overrides":        dict(self._state.overrides),
            "note":             self._state.note,
            "known_zones":      list(self._zone_temp_sensors.keys()),
        }

    # ------------------------------------------------------------------
    # Virtual state injection
    # ------------------------------------------------------------------

    async def _inject_all_virtual_states(self) -> None:
        for zone, temp_c in self._state.zone_temps.items():
            await self._inject_zone_temp(zone, temp_c)
        for zone, temp_c in self._state.stove_temps.items():
            await self._inject_stove_temp(zone, temp_c)

    async def _inject_zone_temp(self, zone: str, temp_c: float) -> None:
        """Injecteer zone-temp als HA state.

        Gebruikt de bestaande geconfigureerde sensor van de zone als die er is.
        Anders: virtueel entity + patch ZoneController._temp_sensors.
        """
        sensors = self._zone_temp_sensors.get(zone, [])
        if sensors:
            entity_id = sensors[0]
        else:
            entity_id = f"{_VIRTUAL_ZONE_TEMP_PREFIX}{_slug(zone)}"
            self._virtual_entities.add(entity_id)
            await self._patch_zone_temp_sensor(zone, entity_id)

        _LOGGER.debug("Sim injecteert zone-temp %s = %.1f via %s", zone, temp_c, entity_id)
        self._hass.states.async_set(
            entity_id,
            str(round(temp_c, 1)),
            {
                "unit_of_measurement": "°C",
                "device_class":        "temperature",
                "friendly_name":       f"[SIM] {zone}",
                "_cloudems_sim":       True,
            },
        )

    async def _inject_stove_temp(self, zone: str, temp_c: float) -> None:
        """Injecteer houtkachel-sensor temp als HA state.

        WoodStoveDetector leest hass.states.get(self._sensor) — als we
        die state zetten ziet de detector automatisch de gesimuleerde temp.
        Als er geen sensor geconfigureerd is: patch WoodStoveDetector._sensor.
        """
        sensor = self._zone_stove_sensors.get(zone)
        if sensor:
            entity_id = sensor
        else:
            entity_id = f"{_VIRTUAL_STOVE_PREFIX}{_slug(zone)}"
            self._virtual_entities.add(entity_id)
            await self._patch_zone_stove_sensor(zone, entity_id)

        _LOGGER.debug("Sim injecteert kachel-temp %s = %.1f via %s", zone, temp_c, entity_id)
        self._hass.states.async_set(
            entity_id,
            str(round(temp_c, 1)),
            {
                "unit_of_measurement": "°C",
                "device_class":        "temperature",
                "friendly_name":       f"[SIM] {zone} kachel",
                "_cloudems_sim":       True,
            },
        )

    async def _remove_virtual_states(self) -> None:
        """Verwijder alle door simulator aangemaakte virtual states."""
        for entity_id in list(self._virtual_entities):
            try:
                self._hass.states.async_remove(entity_id)
                _LOGGER.debug("Sim virtual state verwijderd: %s", entity_id)
            except Exception:
                pass
        self._virtual_entities.clear()

    async def _patch_zone_temp_sensor(self, zone: str, entity_id: str) -> None:
        """Voeg virtual entity toe aan ZoneController._temp_sensors zodat
        _read_temp() hem pikt de volgende coordinatorcyclus.
        """
        try:
            for domain_data in self._hass.data.get("cloudems", {}).values():
                sc = getattr(domain_data, "_smart_climate", None)
                if sc is None:
                    continue
                for z in getattr(sc, "_zones", []):
                    if z._name == zone and entity_id not in getattr(z, "_temp_sensors", []):
                        z._temp_sensors.append(entity_id)
                        z._temp_sensor = z._temp_sensors[0]
                        self._zone_temp_sensors[zone] = list(z._temp_sensors)
                        _LOGGER.debug("Gepatch zone '%s' temp_sensor → %s", zone, entity_id)
        except Exception as err:
            _LOGGER.debug("_patch_zone_temp_sensor fout (niet fataal): %s", err)

    async def _patch_zone_stove_sensor(self, zone: str, entity_id: str) -> None:
        """Zet WoodStoveDetector._sensor als die None was."""
        try:
            for domain_data in self._hass.data.get("cloudems", {}).values():
                sc = getattr(domain_data, "_smart_climate", None)
                if sc is None:
                    continue
                for z in getattr(sc, "_zones", []):
                    if z._name == zone and getattr(z, "_stove", None):
                        if z._stove._sensor is None:
                            z._stove._sensor = entity_id
                            self._zone_stove_sensors[zone] = entity_id
                            _LOGGER.debug("Gepatch zone '%s' stove_sensor → %s", zone, entity_id)
        except Exception as err:
            _LOGGER.debug("_patch_zone_stove_sensor fout (niet fataal): %s", err)

    # ------------------------------------------------------------------
    # HA Notifications
    # ------------------------------------------------------------------

    def _send_notification(self) -> None:
        if not self._hass:
            return
        energie = ", ".join(self._state.overrides.keys()) or "geen"
        zones   = ", ".join(f"{z}: {t}°C" for z, t in self._state.zone_temps.items()) or "geen"
        kachels = ", ".join(f"{z}: {t}°C" for z, t in self._state.stove_temps.items()) or "geen"
        self._hass.async_create_task(
            self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "notification_id": "cloudems_testmodus",
                    "title": "⚠️ CloudEMS TESTMODUS ACTIEF",
                    "message": (
                        f"CloudEMS reageert nu op gesimuleerde waarden.\n\n"
                        f"**Energie/prijs:** {energie}\n"
                        f"**Zone-temperaturen:** {zones}\n"
                        f"**Houtkachels:** {kachels}\n"
                        f"**Auto-stop:** over {self._state.timeout_s // 60} minuten\n\n"
                        f"Historische data en leerprocessen worden **niet** beïnvloed.\n"
                        f"Stop via: *Developer Tools → Services → cloudems.simulator_clear*"
                    ),
                },
            )
        )

    def _clear_notification(self) -> None:
        if not self._hass:
            return
        self._hass.async_create_task(
            self._hass.services.async_call(
                "persistent_notification", "dismiss",
                {"notification_id": "cloudems_testmodus"},
            )
        )
