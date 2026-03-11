# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Versatile Thermostat Bridge (v1.0.0).

Volledige integratie tussen CloudEMS en Versatile Thermostat (VTherm).

WAT DEZE MODULE DOET
════════════════════
  1. State Reader      — leest alle rijke VTherm-attributen per entiteit
                         (on_percent, ema_temp, slope, window_state, presence_state,
                          overpowering_state, is_device_active, regulation_accumulated_error,
                          device_actives, nb_device_actives, safety_state, ...)
  2. Central Boiler    — luistert naar binary_sensor.central_configuration_central_boiler
                         (en sensor.nb_device_active_for_boiler,
                          sensor.total_power_active_for_boiler)
  3. Conflict Guard    — detecteert als VTherm al overpowering actief heeft
                         → CloudEMS sloeg dan eigen power-shedding over voor die zone
  4. Timed Preset      — stuurt VTherm.set_preset_mode met duration (v8.4.2+)
  5. EMA Slope Reader  — levert slope (°C/uur) per zone voor CloudEMS preheat-logica
                         zodat CloudEMS geen eigen helling hoeft te berekenen
  6. Sync Detector     — detecteert "Follow underlying temp change" conflicten
  7. Event Listener    — luistert naar versatile_thermostat_* HA events en logt ze
  8. Auto-start/stop   — leest is_auto_start_stop_enabled + last_auto_start_stop_date
  9. Lock state        — leest is_locked per VTherm
 10. Safety Mode       — leest safety_state en notificeert bij active safety mode
 11. Multi-underlying  — levert per-apparaat status (device_actives lijst)
 12. Central Mode      — stuurt climate.set_hvac_mode op central_configuration VTherm
                         om alle zones tegelijk te besturen (away, eco, heat, off)

PRESET MAPPING (CloudEMS → VTherm)
═══════════════════════════════════
  comfort     → comfort
  eco         → eco
  boost       → boost
  sleep       → sleep    (als beschikbaar, anders eco)
  away        → away     (als beschikbaar, anders frost)
  solar       → comfort
  houtfire    → eco      (TRV minimaal terwijl kachel brandt)
  eco_window  → frost    (raam open → vorstbeveiliging)
  activity    → activity (als VTherm activity preset heeft)
  pre_heat    → comfort + timed duration

TIMED PRESET (VTherm v8.4.2+)
══════════════════════════════
  CloudEMS kan tijdelijke presets sturen met automatische terugval:
    set_timed_preset(eid, preset, duration_min)
  → roept versatile_thermostat.set_preset_mode aan met preset + end_datetime
  Ondersteunde presets: alle standaard VTherm presets

Copyright 2025-2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── VTherm platform identifiers ───────────────────────────────────────────────
VT_PLATFORMS = frozenset({
    "versatile_thermostat",
    "versatile_thermostat_climate",
})

# ── Standaard Central Configuration entiteit namen (VTherm v6+) ───────────────
CENTRAL_BOILER_BINARY  = "binary_sensor.central_configuration_central_boiler"
CENTRAL_NB_DEVICES     = "sensor.nb_device_active_for_boiler"
CENTRAL_TOTAL_POWER    = "sensor.total_power_active_for_boiler"
CENTRAL_BOILER_THRESHOLD = "number.boiler_power_activation_threshold"

# ── CloudEMS preset → VTherm preset naam ─────────────────────────────────────
DEFAULT_PRESET_MAP: dict[str, str] = {
    "comfort":    "comfort",
    "eco":        "eco",
    "boost":      "boost",
    "sleep":      "sleep",
    "away":       "away",
    "solar":      "comfort",
    "houtfire":   "eco",
    "eco_window": "frost",
    "activity":   "activity",
    "pre_heat":   "comfort",
    "frost":      "frost",
    "none":       "none",
}

# ── Fallback volgorde als een preset niet beschikbaar is ─────────────────────
PRESET_FALLBACKS: dict[str, list[str]] = {
    "sleep":    ["eco", "comfort"],
    "away":     ["frost", "eco", "none"],
    "activity": ["comfort", "boost"],
    "frost":    ["eco", "none"],
    "boost":    ["comfort"],
    "solar":    ["comfort"],
}


@dataclass
class VThermState:
    """Volledige state-snapshot van één VTherm entiteit."""
    entity_id: str

    # Basis
    hvac_mode:            str   = "off"
    hvac_action:          str   = "off"
    preset_mode:          str   = "none"
    current_temperature:  Optional[float] = None
    target_temperature:   Optional[float] = None
    preset_modes:         list[str] = field(default_factory=list)

    # VTherm-specifiek: algoritme
    on_percent:           float = 0.0   # 0.0–1.0 fractie actieve cyclus
    mean_cycle_power:     float = 0.0   # W gemiddeld per cyclus
    total_energy:         float = 0.0   # kWh totaal

    # VTherm-specifiek: temperatuur
    ema_temp:             Optional[float] = None  # EMA-gefilterde kamertemp (°C)
    ext_current_temperature: Optional[float] = None  # buitentemperatuur die VTherm gebruikt

    # VTherm-specifiek: slope
    slope:                Optional[float] = None  # °C/uur — positief = stijgend

    # VTherm-specifiek: features actief
    window_state:         Optional[str]  = None   # "on" / "off" / None
    window_auto_state:    bool = False
    motion_state:         Optional[str]  = None   # "on" / "off" / None
    presence_state:       Optional[str]  = None   # "on" / "off" / None
    overpowering_state:   bool = False            # True = VTherm doet al power shedding
    safety_state:         bool = False            # True = VTherm in veiligheidsmodus
    is_window_bypass:     bool = False

    # VTherm-specifiek: apparaten
    is_device_active:     bool = False
    device_actives:       list = field(default_factory=list)
    nb_device_actives:    int  = 0

    # VTherm-specifiek: regulatie
    regulation_accumulated_error: float = 0.0
    is_regulated:         bool = False

    # VTherm-specifiek: auto-start/stop
    is_auto_start_stop_enabled: bool = False
    auto_start_stop_level: Optional[str] = None   # "slow" / "medium" / "fast"

    # VTherm-specifiek: lock
    is_locked:            bool = False

    # VTherm-specifiek: central mode
    is_controlled_by_central_mode: bool = False
    last_central_mode:    Optional[str] = None

    # Preset temperaturen (alle bekende)
    eco_temp:             Optional[float] = None
    comfort_temp:         Optional[float] = None
    boost_temp:           Optional[float] = None
    frost_temp:           Optional[float] = None
    sleep_temp:           Optional[float] = None
    away_temp:            Optional[float] = None

    # Meta
    vtherm_type:          Optional[str]  = None   # "over_switch" / "over_climate" / "over_valve"
    is_used_by_central:   bool = False

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class VThermZoneSummary:
    """Aggregatie van alle VTherm-entiteiten in één CloudEMS-zone."""
    zone_name: str
    entities: list[VThermState] = field(default_factory=list)

    @property
    def any_window_open(self) -> bool:
        return any(e.window_state == "on" for e in self.entities)

    @property
    def any_overpowering(self) -> bool:
        """True als minstens één VTherm al power shedding doet."""
        return any(e.overpowering_state for e in self.entities)

    @property
    def any_safety(self) -> bool:
        return any(e.safety_state for e in self.entities)

    @property
    def any_presence(self) -> bool:
        return any(e.presence_state == "on" for e in self.entities)

    @property
    def mean_on_percent(self) -> float:
        vals = [e.on_percent for e in self.entities if e.on_percent > 0]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    @property
    def mean_slope(self) -> Optional[float]:
        vals = [e.slope for e in self.entities if e.slope is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    @property
    def ema_temp(self) -> Optional[float]:
        """Gemiddelde EMA-temperatuur van alle VTherms in de zone."""
        vals = [e.ema_temp for e in self.entities if e.ema_temp is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    @property
    def heat_demand(self) -> bool:
        """True als on_percent > 0 OF hvac_action heating."""
        return any(
            e.on_percent > 0 or e.hvac_action in ("heating", "heat")
            for e in self.entities
        )

    @property
    def total_mean_cycle_power_w(self) -> float:
        return sum(e.mean_cycle_power for e in self.entities)

    def to_dict(self) -> dict:
        return {
            "zone_name":        self.zone_name,
            "any_window_open":  self.any_window_open,
            "any_overpowering": self.any_overpowering,
            "any_safety":       self.any_safety,
            "any_presence":     self.any_presence,
            "mean_on_percent":  self.mean_on_percent,
            "mean_slope":       self.mean_slope,
            "ema_temp":         self.ema_temp,
            "heat_demand":      self.heat_demand,
            "total_mean_cycle_power_w": self.total_mean_cycle_power_w,
            "entities":         [e.to_dict() for e in self.entities],
        }


class VThermStateReader:
    """Leest de volledige VTherm state van één entiteit uit HA."""

    @staticmethod
    def read(hass: "HomeAssistant", entity_id: str) -> Optional[VThermState]:
        state = hass.states.get(entity_id)
        if not state:
            return None

        attrs = state.attributes
        result = VThermState(entity_id=entity_id)

        # Basis climate state
        result.hvac_mode   = state.state or "off"
        result.hvac_action = attrs.get("hvac_action", "off")
        result.preset_mode = attrs.get("preset_mode", "none")
        result.preset_modes = list(attrs.get("preset_modes") or [])

        try:
            result.current_temperature = float(attrs["current_temperature"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            result.target_temperature = float(attrs["temperature"])
        except (KeyError, TypeError, ValueError):
            pass

        # Algoritme
        result.on_percent       = float(attrs.get("on_percent", 0) or 0)
        result.mean_cycle_power = float(attrs.get("mean_cycle_power", 0) or 0)
        result.total_energy     = float(attrs.get("total_energy", 0) or 0)

        # Temperatuur
        result.ema_temp = _safe_float(attrs.get("ema_temp"))
        result.ext_current_temperature = _safe_float(attrs.get("ext_current_temperature"))

        # Slope — VTherm levert dit als sensor attribuut of als "slope"
        result.slope = _safe_float(attrs.get("slope"))

        # Features
        result.window_state      = attrs.get("window_state")
        result.window_auto_state = bool(attrs.get("window_auto_state", False))
        result.motion_state      = attrs.get("motion_state")
        result.presence_state    = attrs.get("presence_state")
        result.overpowering_state= bool(attrs.get("overpowering_state", False))
        result.safety_state      = bool(attrs.get("safety_state", False))
        result.is_window_bypass  = bool(attrs.get("is_window_bypass", False))

        # Apparaten
        result.is_device_active  = bool(attrs.get("is_device_active", False))
        result.device_actives    = list(attrs.get("device_actives") or [])
        result.nb_device_actives = int(attrs.get("nb_device_actives", 0) or 0)

        # Regulatie
        result.regulation_accumulated_error = float(
            attrs.get("regulation_accumulated_error", 0) or 0
        )
        result.is_regulated = bool(attrs.get("is_regulated", False))

        # Auto-start/stop
        result.is_auto_start_stop_enabled = bool(
            attrs.get("is_auto_start_stop_enabled", False)
        )
        result.auto_start_stop_level = attrs.get("auto_start_stop_level")

        # Lock
        result.is_locked = bool(attrs.get("is_locked", False))

        # Central mode
        result.is_controlled_by_central_mode = bool(
            attrs.get("is_controlled_by_central_mode", False)
        )
        result.last_central_mode = attrs.get("last_central_mode")

        # Preset temperaturen
        for name in ("eco", "comfort", "boost", "frost", "sleep", "away"):
            val = _safe_float(attrs.get(f"{name}_temp"))
            if val is not None:
                setattr(result, f"{name}_temp", val)

        # Type
        result.vtherm_type      = attrs.get("type")
        result.is_used_by_central = bool(attrs.get("is_used_by_central", False))

        return result

    @staticmethod
    def is_vtherm(hass: "HomeAssistant", entity_id: str) -> bool:
        """Controleer of entity_id een Versatile Thermostat is."""
        try:
            from homeassistant.helpers import entity_registry as er
            entry = er.async_get(hass).async_get(entity_id)
            if entry and entry.platform in VT_PLATFORMS:
                return True
        except Exception:
            pass
        # Fallback: check attributen
        state = hass.states.get(entity_id)
        if state:
            attrs = state.attributes
            # VTherm-specifieke attributen die normale thermostaten niet hebben
            vt_markers = {"on_percent", "ema_temp", "is_device_active",
                          "overpowering_state", "regulation_accumulated_error"}
            if vt_markers & set(attrs.keys()):
                return True
        return False


class VThermCentralBoilerReader:
    """Leest de VTherm Central Boiler status."""

    def __init__(
        self,
        boiler_entity: str = CENTRAL_BOILER_BINARY,
        nb_devices_entity: str = CENTRAL_NB_DEVICES,
        total_power_entity: str = CENTRAL_TOTAL_POWER,
        threshold_entity: str = CENTRAL_BOILER_THRESHOLD,
    ) -> None:
        self._boiler_eid    = boiler_entity
        self._nb_eid        = nb_devices_entity
        self._power_eid     = total_power_entity
        self._threshold_eid = threshold_entity

    def read(self, hass: "HomeAssistant") -> dict:
        boiler_st    = hass.states.get(self._boiler_eid)
        nb_st        = hass.states.get(self._nb_eid)
        power_st     = hass.states.get(self._power_eid)
        threshold_st = hass.states.get(self._threshold_eid)

        boiler_active = (
            boiler_st is not None
            and boiler_st.state not in ("unavailable", "unknown", "none", "")
            and boiler_st.state == "on"
        )
        available = boiler_st is not None and boiler_st.state not in (
            "unavailable", "unknown", "none", ""
        )

        nb_devices   = _safe_int(nb_st.state if nb_st else None, 0)
        total_power  = _safe_float(power_st.state if power_st else None) or 0.0
        threshold    = _safe_float(threshold_st.state if threshold_st else None) or 0.0

        return {
            "available":      available,
            "boiler_active":  boiler_active,
            "nb_devices":     nb_devices,
            "total_power_w":  total_power,
            "threshold_w":    threshold,
            "entity_id":      self._boiler_eid,
        }


class VThermCommander:
    """Stuurt VTherm entiteiten aan via HA services."""

    def __init__(
        self,
        preset_map: dict[str, str] | None = None,
    ) -> None:
        self._map = {**DEFAULT_PRESET_MAP, **(preset_map or {})}

    def resolve_preset(
        self,
        cloudems_preset: str,
        available_presets: list[str],
    ) -> str:
        """Vertaal CloudEMS preset naar beste beschikbare VTherm preset."""
        vt_preset = self._map.get(cloudems_preset, cloudems_preset)

        if not available_presets:
            return vt_preset

        if vt_preset in available_presets:
            return vt_preset

        # Probeer fallbacks
        for fallback in PRESET_FALLBACKS.get(cloudems_preset, []):
            mapped = self._map.get(fallback, fallback)
            if mapped in available_presets:
                _LOGGER.debug(
                    "VTherm: preset '%s' niet beschikbaar, fallback → '%s'",
                    vt_preset, mapped
                )
                return mapped

        # Laatste redmiddel: eco of eerste beschikbare
        for safe in ("eco", "none"):
            if safe in available_presets:
                return safe
        return available_presets[0] if available_presets else vt_preset

    async def async_set_preset(
        self,
        hass: "HomeAssistant",
        entity_id: str,
        cloudems_preset: str,
        available_presets: list[str] | None = None,
        skip_if_overpowering: bool = True,
    ) -> bool:
        """
        Stuur VTherm preset.

        skip_if_overpowering=True: sla over als VTherm al power shedding doet
        Geeft True terug als actie uitgevoerd is.
        """
        state = hass.states.get(entity_id)
        if not state:
            return False

        attrs = state.attributes

        # Conflict guard: VTherm doet al power shedding
        if skip_if_overpowering and bool(attrs.get("overpowering_state", False)):
            _LOGGER.debug(
                "VTherm %s: overpowering actief — CloudEMS sloeg preset '%s' over",
                entity_id, cloudems_preset,
            )
            return False

        # Slot: locked VTherm niet aansturen
        if bool(attrs.get("is_locked", False)):
            _LOGGER.debug("VTherm %s: gelocked — aansturen overgeslagen", entity_id)
            return False

        presets = available_presets or list(attrs.get("preset_modes") or [])
        vt_preset = self.resolve_preset(cloudems_preset, presets)

        # Al correct ingesteld?
        current = attrs.get("preset_mode")
        if current == vt_preset:
            return False  # Niets te doen

        try:
            await hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": vt_preset},
                blocking=False,
            )
            _LOGGER.debug(
                "VTherm %s: preset '%s' → '%s'",
                entity_id, cloudems_preset, vt_preset,
            )
            return True
        except Exception as err:
            _LOGGER.warning("VTherm %s: preset aansturen mislukt: %s", entity_id, err)
            return False

    async def async_set_timed_preset(
        self,
        hass: "HomeAssistant",
        entity_id: str,
        cloudems_preset: str,
        duration_min: int,
        available_presets: list[str] | None = None,
    ) -> bool:
        """
        Stuur tijdelijke VTherm preset via versatile_thermostat.set_preset_mode.
        Werkt alleen met VTherm v8.4.2+.
        Geeft automatisch terug naar vorige preset na duration_min minuten.
        """
        state = hass.states.get(entity_id)
        if not state:
            return False

        presets = available_presets or list(state.attributes.get("preset_modes") or [])
        vt_preset = self.resolve_preset(cloudems_preset, presets)

        end_dt = datetime.now(timezone.utc) + timedelta(minutes=duration_min)
        end_str = end_dt.isoformat()

        # Probeer eerst de VTherm-specifieke service (v8.4.2+)
        try:
            await hass.services.async_call(
                "versatile_thermostat", "set_preset_mode",
                {
                    "entity_id":    entity_id,
                    "preset_mode":  vt_preset,
                    "end_datetime": end_str,
                },
                blocking=False,
            )
            _LOGGER.debug(
                "VTherm %s: timed preset '%s' voor %d min (tot %s)",
                entity_id, vt_preset, duration_min, end_str,
            )
            return True
        except Exception:
            pass

        # Fallback: gewone preset (geen timer)
        try:
            await hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": vt_preset},
                blocking=False,
            )
            _LOGGER.debug(
                "VTherm %s: timed preset niet beschikbaar, gewone preset '%s' gesteld",
                entity_id, vt_preset,
            )
            return True
        except Exception as err:
            _LOGGER.warning("VTherm %s: timed preset mislukt: %s", entity_id, err)
            return False

    async def async_set_central_mode(
        self,
        hass: "HomeAssistant",
        hvac_mode: str,          # "heat" / "off" / "eco" / "away"
        central_entity: str = "climate.central_configuration",
    ) -> bool:
        """
        Stuur alle VTherms tegelijk via Central Mode (VTherm v6+).
        Gebruikt versatile_thermostat.set_hvac_mode op central_configuration.
        """
        try:
            await hass.services.async_call(
                "versatile_thermostat", "set_central_mode",
                {"hvac_mode": hvac_mode},
                blocking=False,
            )
            _LOGGER.info("VTherm Central Mode → '%s'", hvac_mode)
            return True
        except Exception:
            pass

        # Fallback: direct op central_configuration climate entiteit
        try:
            await hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": central_entity, "hvac_mode": hvac_mode},
                blocking=False,
            )
            return True
        except Exception as err:
            _LOGGER.warning("VTherm Central Mode mislukt: %s", err)
            return False

    async def async_set_hvac_mode(
        self,
        hass: "HomeAssistant",
        entity_id: str,
        hvac_mode: str,
    ) -> bool:
        try:
            await hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": hvac_mode},
                blocking=False,
            )
            return True
        except Exception as err:
            _LOGGER.warning("VTherm %s: hvac_mode '%s' mislukt: %s",
                            entity_id, hvac_mode, err)
            return False


class VThermEventListener:
    """
    Luistert naar versatile_thermostat_* HA events en aggregeert ze.

    Events die VTherm stuurt:
      versatile_thermostat_central_boiler_event  — ketel aan/uit
      versatile_thermostat_hvac_mode_event       — HVAC mode wijziging
      versatile_thermostat_preset_event          — preset wijziging
      versatile_thermostat_temperature_event     — temperatuur update
      versatile_thermostat_security_event        — veiligheidsmodus
      versatile_thermostat_power_event           — overpowering
      versatile_thermostat_window_event          — raam open/dicht
      versatile_thermostat_motion_event          — beweging
    """

    def __init__(self) -> None:
        self._recent: list[dict] = []  # max 50 events
        self._unsubscribes: list = []
        self._security_active_entities: set[str] = set()
        self._overpowering_entities:    set[str] = set()

    def setup(self, hass: "HomeAssistant") -> None:
        """Registreer event listeners."""
        events = [
            "versatile_thermostat_central_boiler_event",
            "versatile_thermostat_hvac_mode_event",
            "versatile_thermostat_preset_event",
            "versatile_thermostat_temperature_event",
            "versatile_thermostat_security_event",
            "versatile_thermostat_power_event",
            "versatile_thermostat_window_event",
            "versatile_thermostat_motion_event",
        ]
        for evt in events:
            unsub = hass.bus.async_listen(evt, self._handle_event)
            self._unsubscribes.append(unsub)
        _LOGGER.debug("VThermEventListener: luistert naar %d event types", len(events))

    def _handle_event(self, event) -> None:
        try:
            data = dict(event.data)
            data["_event_type"] = event.event_type
            data["_ts"] = datetime.now(timezone.utc).isoformat()

            entity_id = data.get("entity_id", "")

            # Security tracking
            if event.event_type == "versatile_thermostat_security_event":
                if data.get("security_state"):
                    self._security_active_entities.add(entity_id)
                else:
                    self._security_active_entities.discard(entity_id)

            # Overpowering tracking
            if event.event_type == "versatile_thermostat_power_event":
                if data.get("overpowering_state"):
                    self._overpowering_entities.add(entity_id)
                else:
                    self._overpowering_entities.discard(entity_id)

            self._recent.append(data)
            if len(self._recent) > 50:
                self._recent.pop(0)

            _LOGGER.debug("VTherm event: %s — %s", event.event_type, data)
        except Exception as err:
            _LOGGER.warning("VThermEventListener fout: %s", err)

    def teardown(self) -> None:
        for unsub in self._unsubscribes:
            try:
                unsub()
            except Exception:
                pass
        self._unsubscribes.clear()

    @property
    def recent_events(self) -> list[dict]:
        return list(self._recent)

    @property
    def security_entities(self) -> set[str]:
        return frozenset(self._security_active_entities)

    @property
    def overpowering_entities(self) -> set[str]:
        return frozenset(self._overpowering_entities)

    def get_status(self) -> dict:
        return {
            "recent_events_count":   len(self._recent),
            "security_active":       list(self._security_active_entities),
            "overpowering_active":   list(self._overpowering_entities),
            "last_event":            self._recent[-1] if self._recent else None,
        }


class VThermBridge:
    """
    Hoofd-interface voor CloudEMS ↔ Versatile Thermostat integratie.

    Gebruik vanuit coordinator:
        bridge = VThermBridge(hass, config)
        bridge.setup()
        # elke tick:
        result = bridge.update(vtherm_entity_ids_per_zone)
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass      = hass
        self._config    = config
        self._reader    = VThermStateReader()
        self._commander = VThermCommander(
            preset_map=config.get("vtherm_preset_map")
        )
        self._central_boiler = VThermCentralBoilerReader(
            boiler_entity=config.get(
                "vtherm_central_boiler_entity", CENTRAL_BOILER_BINARY
            ),
            nb_devices_entity=config.get(
                "vtherm_nb_devices_entity", CENTRAL_NB_DEVICES
            ),
            total_power_entity=config.get(
                "vtherm_total_power_entity", CENTRAL_TOTAL_POWER
            ),
        )
        self._events    = VThermEventListener()
        self._enabled   = bool(config.get("vtherm_bridge_enabled", True))
        # Cache van laatste zone summaries
        self._zone_cache: dict[str, VThermZoneSummary] = {}

    def setup(self) -> None:
        if self._enabled:
            self._events.setup(self._hass)
            _LOGGER.info("VThermBridge: actief")

    def teardown(self) -> None:
        self._events.teardown()

    def update_zone(
        self,
        zone_name: str,
        entity_ids: list[str],
    ) -> VThermZoneSummary:
        """Lees alle VTherm-entiteiten in een zone en geef samenvatting."""
        states = []
        for eid in entity_ids:
            if not eid.startswith("climate."):
                continue
            if not VThermStateReader.is_vtherm(self._hass, eid):
                continue
            st = VThermStateReader.read(self._hass, eid)
            if st:
                states.append(st)

        summary = VThermZoneSummary(zone_name=zone_name, entities=states)
        self._zone_cache[zone_name] = summary
        return summary

    def read_central_boiler(self) -> dict:
        return self._central_boiler.read(self._hass)

    async def async_set_zone_preset(
        self,
        zone_name: str,
        entity_ids: list[str],
        cloudems_preset: str,
        skip_if_overpowering: bool = True,
    ) -> list[str]:
        """Stuur preset naar alle VTherm-entiteiten in zone. Geeft aangestuurde IDs terug."""
        applied = []
        for eid in entity_ids:
            if not eid.startswith("climate."):
                continue
            if not VThermStateReader.is_vtherm(self._hass, eid):
                continue
            ok = await self._commander.async_set_preset(
                self._hass, eid, cloudems_preset,
                skip_if_overpowering=skip_if_overpowering,
            )
            if ok:
                applied.append(eid)
        return applied

    async def async_set_zone_timed_preset(
        self,
        zone_name: str,
        entity_ids: list[str],
        cloudems_preset: str,
        duration_min: int,
    ) -> list[str]:
        """Stuur tijdelijke preset naar alle VTherm-entiteiten in zone."""
        applied = []
        for eid in entity_ids:
            if not eid.startswith("climate."):
                continue
            if not VThermStateReader.is_vtherm(self._hass, eid):
                continue
            ok = await self._commander.async_set_timed_preset(
                self._hass, eid, cloudems_preset, duration_min
            )
            if ok:
                applied.append(eid)
        return applied

    async def async_central_mode(self, hvac_mode: str) -> bool:
        """Stuur alle VTherms tegelijk via Central Mode."""
        return await self._commander.async_set_central_mode(
            self._hass, hvac_mode
        )

    def is_zone_overpowering(self, zone_name: str) -> bool:
        """True als VTherm al power shedding doet in deze zone."""
        summary = self._zone_cache.get(zone_name)
        if summary:
            return summary.any_overpowering
        # Geen cache → snel checken via events
        return False

    def get_zone_slope(self, zone_name: str) -> Optional[float]:
        """Geef EMA-slope (°C/uur) terug voor zone — None als onbekend."""
        summary = self._zone_cache.get(zone_name)
        return summary.mean_slope if summary else None

    def get_zone_ema_temp(self, zone_name: str) -> Optional[float]:
        """Geef EMA-gefilterde kamertemperatuur terug — nauwkeuriger dan raw."""
        summary = self._zone_cache.get(zone_name)
        return summary.ema_temp if summary else None

    def get_zone_heat_demand(self, zone_name: str) -> bool:
        """True als VTherm in deze zone actief verwarmt."""
        summary = self._zone_cache.get(zone_name)
        return summary.heat_demand if summary else False

    def get_all_zones(self) -> dict[str, dict]:
        return {
            name: summary.to_dict()
            for name, summary in self._zone_cache.items()
        }

    def get_event_status(self) -> dict:
        return self._events.get_status()

    def get_status(self) -> dict:
        return {
            "enabled":         self._enabled,
            "zones":           len(self._zone_cache),
            "central_boiler":  self._central_boiler.read(self._hass),
            "events":          self._events.get_status(),
        }


# ── Hulpfuncties ─────────────────────────────────────────────────────────────

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default
