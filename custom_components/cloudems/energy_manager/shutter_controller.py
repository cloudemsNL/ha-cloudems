# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Shutter Controller v1.0
Beheert rolluiken op basis van thermisch comfort, zonnewarmte en energiebesparing.
Koppelt aan zone_climate_manager, pv_forecast en de HA cover entiteiten.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    SHUTTER_ACTION_OPEN, SHUTTER_ACTION_CLOSE,
    SHUTTER_ACTION_POSITION, SHUTTER_ACTION_STOP, SHUTTER_ACTION_IDLE,
    SHUTTER_REASON_MANUAL, SHUTTER_REASON_THERMAL,
    SHUTTER_REASON_SOLAR_GAIN, SHUTTER_REASON_OVERHEAT,
    SHUTTER_REASON_NIGHT, SHUTTER_REASON_MORNING, SHUTTER_REASON_PID,
    SHUTTER_REASON_WIND, SHUTTER_REASON_PV_SURPLUS,
    SHUTTER_REASON_STORM, SHUTTER_REASON_AWAY, SHUTTER_REASON_SUNRISE, SHUTTER_REASON_SEASON,
    SHUTTER_ORIENTATION_UNKNOWN, SHUTTER_STORAGE_KEY,
    DEFAULT_SHUTTER_OVERRIDE_H,
    DEFAULT_SHUTTER_NIGHT_CLOSE, DEFAULT_SHUTTER_MORNING_OPEN, DEFAULT_SHUTTER_SETPOINT,
    DEFAULT_SHUTTER_SUNRISE_OFFSET, DEFAULT_SHUTTER_AWAY_POSITION,
    DEFAULT_SHUTTER_SUMMER_OFFSET, DEFAULT_SHUTTER_WINTER_OFFSET,
    SHUTTER_SUMMER_MONTHS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ShutterConfig:
    """Configuratie voor één rolluik."""
    index: int
    entity_id: str                          # cover.xxx
    label: str                              # gebruikersnaam
    area_id: str = ""                       # HA area ID (auto-koppeling)
    area_name: str = ""                     # leesbare naam
    orientation: str = SHUTTER_ORIENTATION_UNKNOWN  # leren via ShutterThermalLearner
    group: str = ""                         # groepnaam (optioneel)

    # Temperatuursensor fallback (gebruikt als er geen zone climate is voor deze ruimte)
    temp_sensor: str = ""                   # sensor.xxx met device_class temperature

    # Rookmelder per rolluik/ruimte (optioneel — naast de globale sensor)
    smoke_sensor: str = ""                  # binary_sensor.xxx, on = rook gedetecteerd

    # Gedragsopties
    auto_thermal: bool = True               # automatisch op thermisch comfort
    auto_solar_gain: bool = True            # openen voor passieve zonnewarmte
    auto_overheat: bool = True              # sluiten bij oververhitting
    min_position: int = 0                   # minimale openstand (%)
    max_position: int = 100                 # maximale openstand (%)

    # Tijdschema
    night_close_time: str = "20:00"         # start default, learned schedule takes over
    morning_open_time: str = "08:00"        # start default, learned schedule takes over
    schedule_learning: bool = True          # v4.6.153: learn open/close times from observations
    default_setpoint: float = 20.0          # fallback setpoint als geen klimaat beschikbaar
    smoke_sensor: str = ""                  # optioneel: binary_sensor per rolluik/ruimte

    # PID instellingen (positie-sturing)
    pid_kp: float = 15.0                    # proportionele versterking
    pid_ki: float = 0.5                     # integratieve versterking
    pid_kd: float = 2.0                     # differentiële versterking


@dataclass
class ShutterState:
    """Actuele toestand van één rolluik."""
    entity_id: str
    current_position: int = -1             # -1 = onbekend
    is_closed: bool = False
    override_until: Optional[datetime] = None
    override_action: str = SHUTTER_ACTION_IDLE
    last_action: str = SHUTTER_ACTION_IDLE
    last_reason: str = ""
    last_changed: Optional[datetime] = None
    auto_enabled: bool = True              # False = automaat uitgeschakeld voor dit rolluik
    auto_disabled_until: Optional[datetime] = None  # None = permanent, anders tijdelijk
    # PID state
    pid_integral: float = 0.0
    pid_prev_error: float = 0.0
    pid_last_time: float = 0.0
    # v4.5.86: shadow decision — wat de automaat zou doen bij override/uit
    shadow_action: str = ""
    shadow_reason: str = ""
    shadow_position: Optional[int] = None
    pid_last_output: float = 50.0           # start op 50% (half open)


@dataclass
class ShutterDecision:
    """Beslissing voor één rolluik."""
    entity_id: str
    action: str                             # open/close/position/idle
    position: Optional[int] = None         # alleen bij action=position
    reason: str = ""
    priority: int = 0                       # hogere waarde = hogere prioriteit
    # v4.5.86: shadow decision — wat de automaat zou doen als hij aan stond
    # Altijd berekend, ook bij override of automaat-uit.
    shadow_action: str = ""                 # wat de automaat zou doen
    shadow_reason: str = ""                 # waarom
    shadow_position: Optional[int] = None  # doelpositie bij shadow_action=position


@dataclass
class ShutterGroup:
    """Groep van rolluiken die samen bediend worden."""
    name: str
    entity_ids: list[str] = field(default_factory=list)
    label: str = ""


class ShutterController:
    """Hoofdcontroller voor alle rolluiken.

    Prioriteitslagen (hoog → laag):
    1. Handmatige override (tijdelijk, X uur)
    2. Oververhitting voorkomen (> max temp)
    3. Thermisch comfort (kamer te warm → sluiten)
    4. Passieve zonnewarmte (kamer te koud + zon → openen)
    5. Niets doen (idle)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        configs: list[dict],
        groups: list[dict] | None = None,
    ) -> None:
        self.hass = hass
        self._configs: list[ShutterConfig] = []
        self._groups: list[ShutterGroup] = []
        self._states: dict[str, ShutterState] = {}
        self._learner: Any = None           # ShutterThermalLearner (optioneel)
        self._last_evaluation: Optional[datetime] = None

        # v4.3.7: nieuwe features
        self._weather_entity: str | None = None          # weer-integratie
        self._is_storm: bool = False                     # storm gedetecteerd
        self._global_smoke_sensor: str | None = None         # optioneel: 1 algemene rookmelder sensor
        self._presence_entities: list[str] = []          # person.* / device_tracker.*
        self._anyone_home: bool = True                   # iemand thuis?

        self._parse_configs(configs)
        self._parse_groups(groups or [])
        self._init_states()
        # Externe bediening detectie: bijhouden wanneer CloudEMS zelf een commando stuurde
        # key = entity_id, value = timestamp van laatste CloudEMS-commando
        self._cloudems_commands: dict[str, float] = {}
        self._external_detection_unsub = None   # unsubscribe handle voor state listener
        self._coordinator: Any = None            # gekoppeld na aanmaken door coordinator
        self._store = Store(hass, 1, SHUTTER_STORAGE_KEY)
        self._last_timer_save: datetime | None = None   # periodieke save elke 5 min
        # Grace period: als positie verandert binnen N seconden na CloudEMS-commando → géén externe detectie
        self._EXTERNAL_GRACE_S = 15

        # v4.6.153: Schedule learner
        from .shutter_learner import ShutterScheduleLearner
        self._schedule_learner = ShutterScheduleLearner()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _parse_configs(self, raw: list[dict]) -> None:
        for i, c in enumerate(raw):
            self._configs.append(ShutterConfig(
                index=i,
                entity_id=c.get("entity_id", ""),
                label=c.get("label", f"Rolluik {i+1}"),
                area_id=c.get("area_id", ""),
                area_name=c.get("area_name", ""),
                orientation=c.get("orientation", SHUTTER_ORIENTATION_UNKNOWN),
                group=c.get("group", ""),
                temp_sensor=c.get("temp_sensor", ""),
                auto_thermal=c.get("auto_thermal", True),
                auto_solar_gain=c.get("auto_solar_gain", True),
                auto_overheat=c.get("auto_overheat", True),
                min_position=c.get("min_position", 0),
                max_position=c.get("max_position", 100),
                night_close_time=c.get("night_close_time", DEFAULT_SHUTTER_NIGHT_CLOSE),
                morning_open_time=c.get("morning_open_time", DEFAULT_SHUTTER_MORNING_OPEN),
                default_setpoint=float(c.get("default_setpoint", DEFAULT_SHUTTER_SETPOINT)),
                smoke_sensor=c.get("smoke_sensor", ""),
                schedule_learning=c.get("schedule_learning", True),
                pid_kp=float(c.get("pid_kp", 15.0)),
                pid_ki=float(c.get("pid_ki", 0.5)),
                pid_kd=float(c.get("pid_kd", 2.0)),
            ))

    def _parse_groups(self, raw: list[dict]) -> None:
        for g in raw:
            self._groups.append(ShutterGroup(
                name=g.get("name", ""),
                entity_ids=g.get("entity_ids", []),
                label=g.get("label", g.get("name", "")),
            ))

    def _init_states(self) -> None:
        for cfg in self._configs:
            if cfg.entity_id:
                self._states[cfg.entity_id] = ShutterState(entity_id=cfg.entity_id)
        # Snelle opzoektabel voor set_* methoden
        self._cfg_by_id: dict[str, ShutterConfig] = {
            c.entity_id: c for c in self._configs if c.entity_id
        }

    async def async_setup(self) -> None:
        """Start de state-listener voor externe bediening detectie."""
        # Gebruik async_track_state_change_event voor betrouwbare cover-tracking
        from homeassistant.helpers.event import async_track_state_change_event
        cover_ids = [c.entity_id for c in self._configs if c.entity_id]
        if cover_ids:
            self._external_detection_unsub = async_track_state_change_event(
                self.hass,
                cover_ids,
                self._async_on_cover_state_changed,
            )
            _LOGGER.info(
                "CloudEMS Shutters: externe bediening detectie actief voor %d covers: %s",
                len(cover_ids), cover_ids,
            )
        else:
            _LOGGER.warning("CloudEMS Shutters: geen cover entity_ids gevonden voor externe detectie")

    async def async_shutdown(self) -> None:
        """Stop de state-listener."""
        if self._external_detection_unsub:
            self._external_detection_unsub()
            self._external_detection_unsub = None

    @callback
    def _async_on_cover_state_changed(self, event) -> None:
        """Detecteer als een rolluik buiten CloudEMS om bewogen wordt.

        Logica:
        - Alleen als automaat AAN staat
        - Positie of state moet echt veranderd zijn
        - CloudEMS stuurde geen commando in de afgelopen _EXTERNAL_GRACE_S seconden
        → Automatisch 4 uur pauze instellen
        """
        entity_id = event.data.get("entity_id", "")

        # Haal ShutterState op
        shutter_state = self._states.get(entity_id)
        if shutter_state is None:
            _LOGGER.debug("CloudEMS externe detectie: geen state voor %s", entity_id)
            return

        # Automaat al uitgeschakeld? Niets te doen
        # Gebruik get_auto_enabled() zodat verlopen timers automatisch worden hervat
        if not self.get_auto_enabled(entity_id):
            return

        # Binnen grace period na CloudEMS commando? → negeren
        last_cmd = self._cloudems_commands.get(entity_id)
        if last_cmd is not None and (time.monotonic() - last_cmd) < self._EXTERNAL_GRACE_S:
            _LOGGER.debug(
                "CloudEMS externe detectie: %s binnen grace period (%.0fs), negeren",
                entity_id, time.monotonic() - last_cmd,
            )
            return

        new_ha_state = event.data.get("new_state")
        old_ha_state = event.data.get("old_state")
        if new_ha_state is None or old_ha_state is None:
            return

        try:
            new_pos = new_ha_state.attributes.get("current_position")
            old_pos = old_ha_state.attributes.get("current_position")
            new_st  = new_ha_state.state
            old_st  = old_ha_state.state
        except Exception:
            return

        # Significante positieverandering (>2%) of state-flip open/closed
        position_changed = (
            new_pos is not None and old_pos is not None
            and abs(int(new_pos) - int(old_pos)) > 2
        )
        state_changed = (
            new_st != old_st
            and new_st not in ("unavailable", "unknown")
            and old_st not in ("unavailable", "unknown")
        )

        if not (position_changed or state_changed):
            return

        cfg   = self._cfg_by_id.get(entity_id)
        label = cfg.label if cfg else entity_id
        _LOGGER.info(
            "CloudEMS Shutters: externe bediening gedetecteerd op '%s' (%s) "
            "positie %s→%s state %s→%s — automaat 4 uur gepauzeerd",
            label, entity_id, old_pos, new_pos, old_st, new_st,
        )
        self.set_auto_enabled(entity_id, False, hours=4.0)

        # v4.6.153: Learn from this external action
        self._learn_from_state_change(entity_id, new_pos, new_st, old_pos, old_st, source="external")

        # Forceer coordinator refresh zodat switch-entities direct updaten
        if self._coordinator is not None:
            self.hass.async_create_task(
                self._coordinator.async_request_refresh(),
                name=f"cloudems_shutter_ext_detect_{entity_id}",
            )

    def set_learner(self, learner: Any) -> None:
        """Koppel de ShutterThermalLearner."""
        self._learner = learner

    def set_wind_speed(self, wind_ms: float | None, threshold_ms: float = 12.0) -> None:
        """Update actuele windsnelheid (m/s) en drempel. Wordt door coordinator aangeroepen."""
        self._current_wind_speed = wind_ms
        self._wind_threshold_ms  = threshold_ms

    def set_global_smoke_sensor(self, entity_id: str | None) -> None:
        """Koppel een algemene rookmelder binary_sensor (geldt voor alle rolluiken)."""
        self._global_smoke_sensor = entity_id

    def _smoke_detected(self, cfg: "ShutterConfig") -> bool:
        """True als globale rookmelder OF rolluik-specifieke rookmelder actief is."""
        def _is_on(eid: str) -> bool:
            if not eid:
                return False
            state = self.hass.states.get(eid)
            return state is not None and state.state == "on"
        return _is_on(self._global_smoke_sensor or "") or _is_on(cfg.smoke_sensor)

    def set_weather_entity(self, entity_id: str | None) -> None:
        """Koppel een HA weather entiteit voor storm/wind detectie."""
        self._weather_entity = entity_id

    def set_presence_entities(self, entity_ids: list[str]) -> None:
        """Stel de te monitoren aanwezigheids-entiteiten in (person.* / device_tracker.*)."""
        self._presence_entities = list(entity_ids)

    def poll_weather(self) -> None:
        """Lees actuele weerstatus uit HA (aanroepen elke coordinator-cyclus).

        Detecteert storm via weather.condition én windsnelheid in attributen.
        Stormbedreigde condities: lightning, lightning-rainy, hail, exceptional.
        """
        if not self._weather_entity:
            return
        state = self.hass.states.get(self._weather_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return

        STORM_CONDITIONS = {
            "lightning", "lightning-rainy", "hail", "exceptional",
            "tornado", "hurricane", "extreme",
        }
        condition = state.state.lower()
        self._is_storm = condition in STORM_CONDITIONS

        # Windsnelheid uit weer-attribuut als geen aparte windsnelheid is ingesteld
        if not hasattr(self, '_current_wind_speed') or self._current_wind_speed is None:
            wind = state.attributes.get("wind_speed")
            if wind is not None:
                try:
                    # HA levert wind_speed in km/h voor de meeste weather integrations
                    wind_ms = float(wind) / 3.6
                    self.set_wind_speed(wind_ms)
                except (ValueError, TypeError):
                    pass

    def poll_presence(self) -> None:
        """Lees aanwezigheid van geconfigureerde entiteiten.

        anyone_home = True als ≥1 persoon 'home' is.
        Ondersteunt: person.* (state='home'/'not_home') en
                     device_tracker.* (state='home').
        """
        if not self._presence_entities:
            self._anyone_home = True  # geen entities = geen detectie = altijd thuis
            return
        for eid in self._presence_entities:
            state = self.hass.states.get(eid)
            if state and state.state in ("home", "Home"):
                self._anyone_home = True
                return
        self._anyone_home = False

    def update_temp_sensor(self, entity_id: str, temp_sensor: str) -> bool:
        """Wijs een (automatisch ontdekte) temperatuursensor toe aan een rolluik.

        Geeft True terug als de config is bijgewerkt, False als het rolluik
        niet gevonden is of al een sensor heeft.
        """
        for cfg in self._configs:
            if cfg.entity_id == entity_id:
                if not cfg.temp_sensor:
                    cfg.temp_sensor = temp_sensor
                    _LOGGER.info(
                        "CloudEMS Shutters: temperatuursensor %s automatisch gekoppeld aan %s (%s)",
                        temp_sensor, cfg.label, cfg.entity_id,
                    )
                    return True
        return False

    def _read_temp_sensor(self, sensor_entity_id: str) -> float | None:
        """Lees actuele temperatuur van een HA sensor entiteit."""
        if not sensor_entity_id:
            return None
        state = self.hass.states.get(sensor_entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    # ── Publieke API ─────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        outdoor_temp_c: float | None = None,
        solar_elevation_deg: float | None = None,
        solar_azimuth_deg: float | None = None,
        pv_surplus_w: float = 0.0,
        room_temps: dict[str, float] | None = None,   # area_id → °C
        room_setpoints: dict[str, float] | None = None,
    ) -> list[ShutterDecision]:
        """Evalueer alle rolluiken en geef beslissingen terug."""
        self._last_evaluation = dt_util.now()

        # v4.5.12: log ontbrekende inputs als waarschuwing zodat ze in de logs zichtbaar zijn.
        if solar_elevation_deg is None:
            _LOGGER.warning(
                "ShutterController: solar_elevation_deg is None — "
                "koppel sun.sun in de CloudEMS configuratie voor thermische sturing op basis van zonnestand. "
                "Rolluiken vallen terug op tijdschema."
            )
        if outdoor_temp_c is None:
            _LOGGER.warning(
                "ShutterController: outdoor_temp_c is None — "
                "koppel een buitentemperatuursensor in de CloudEMS configuratie. "
                "Thermisch comfort-sturing is beperkt zonder buitentemperatuur."
            )
        # Periodiek opslaan (elke 5 minuten) als backup bij crash of harde reboot
        if self._last_timer_save is None or (dt_util.now() - self._last_timer_save).total_seconds() >= 300:
            self._last_timer_save = dt_util.now()
            self._schedule_save_timers()
        room_temps = room_temps or {}
        room_setpoints = room_setpoints or {}
        decisions: list[ShutterDecision] = []

        await self._refresh_states()

        for cfg in self._configs:
            if not cfg.entity_id:
                continue
            # Kamertemperatuur: eerst via zone climate manager, dan via geconfigureerde sensor
            room_temp = room_temps.get(cfg.area_id)
            if room_temp is None and cfg.temp_sensor:
                room_temp = self._read_temp_sensor(cfg.temp_sensor)

            decision = self._evaluate_one(
                cfg,
                outdoor_temp_c=outdoor_temp_c,
                solar_elevation_deg=solar_elevation_deg,
                solar_azimuth_deg=solar_azimuth_deg,
                pv_surplus_w=pv_surplus_w,
                room_temp=room_temp,
                room_setpoint=room_setpoints.get(cfg.area_id),
            )
            decisions.append(decision)
            # v4.5.86: shadow altijd opslaan op state zodat get_status() het kan tonen
            _sh_state = self._states.get(cfg.entity_id)
            if _sh_state and decision.shadow_action:
                _sh_state.shadow_action   = decision.shadow_action
                _sh_state.shadow_reason   = decision.shadow_reason
                _sh_state.shadow_position = decision.shadow_position

        await self._apply_decisions(decisions)
        return decisions

    async def async_manual_override(
        self,
        entity_id: str,
        action: str,
        position: int | None = None,
        hours: float = DEFAULT_SHUTTER_OVERRIDE_H,
    ) -> None:
        """Stel handmatige override in voor X uur.

        action='idle': blokkeer automatische sturing zonder fysieke actie.
        """
        state = self._states.get(entity_id)
        if state is None:
            _LOGGER.warning("CloudEMS Shutters: onbekende entity %s", entity_id)
            return

        state.override_until  = dt_util.now() + timedelta(hours=max(0.1, hours))
        state.override_action = action
        self._schedule_save_timers()
        _LOGGER.info(
            "CloudEMS Shutters: handmatige override %s → %s voor %.1f uur",
            entity_id, action, hours,
        )
        # 'idle' = alleen blokkeren, geen fysieke actie uitvoeren
        if action != SHUTTER_ACTION_IDLE:
            await self._execute_action(entity_id, action, position, SHUTTER_REASON_MANUAL)

    async def async_group_command(
        self,
        group_name: str,
        action: str,
        position: int | None = None,
        hours: float = DEFAULT_SHUTTER_OVERRIDE_H,
    ) -> None:
        """Stuur commando naar alle rolluiken in een groep."""
        group = next((g for g in self._groups if g.name == group_name), None)
        if group is None:
            _LOGGER.warning("CloudEMS Shutters: onbekende groep %s", group_name)
            return
        tasks = [
            self.async_manual_override(eid, action, position, hours)
            for eid in group.entity_ids
        ]
        await asyncio.gather(*tasks)

    async def async_load_timers(self) -> None:
        """Load persisted timers and learned schedules after restart."""
        try:
            data = await self._store.async_load()
            if not data:
                return
            for eid, t in data.get("auto_disabled_until", {}).items():
                state = self._states.get(eid)
                if state and t:
                    until = dt_util.parse_datetime(t)
                    if until and dt_util.now() < until:
                        state.auto_disabled_until = until
                        state.auto_enabled = False
                        _LOGGER.info("CloudEMS Shutters: pauze hersteld voor %s tot %s", eid, until)
            for eid, t in data.get("override_until", {}).items():
                state = self._states.get(eid)
                if state and t:
                    until = dt_util.parse_datetime(t)
                    if until and dt_util.now() < until:
                        state.override_until = until
                        _LOGGER.info("CloudEMS Shutters: override hersteld voor %s tot %s", eid, until)
            # v4.6.153: load learned schedules
            learned = data.get("learned_schedules")
            if learned:
                from .shutter_learner import ShutterScheduleLearner
                self._schedule_learner = ShutterScheduleLearner.from_dict(learned)
                _LOGGER.info("CloudEMS ShutterLearner: loaded %d schedules", len(learned))
        except Exception as exc:
            _LOGGER.warning("CloudEMS Shutters: kon timers niet laden: %s", exc)

    def _schedule_save_timers(self) -> None:
        """Sla timers op — alleen aanroepen bij wijziging."""
        self.hass.async_create_task(self._async_save_timers())

    async def _async_save_timers(self) -> None:
        """Sla auto_disabled_until, override_until en learned schedules op."""
        auto_disabled = {}
        overrides = {}
        for eid, state in self._states.items():
            if state.auto_disabled_until:
                auto_disabled[eid] = state.auto_disabled_until.isoformat()
            if state.override_until:
                overrides[eid] = state.override_until.isoformat()
        payload: dict = {
            "auto_disabled_until": auto_disabled,
            "override_until": overrides,
        }
        # v4.6.153: save learned schedules if dirty
        if self._schedule_learner.dirty:
            payload["learned_schedules"] = self._schedule_learner.to_dict()
        await self._store.async_save(payload)

    def set_auto_enabled(self, entity_id: str, enabled: bool, hours: float = 0.0) -> None:
        """Schakel automaat in of uit. hours>0 = tijdelijk uitschakelen."""
        state = self._states.setdefault(entity_id, ShutterState(entity_id=entity_id))
        state.auto_enabled = enabled
        if not enabled and hours > 0:
            state.auto_disabled_until = dt_util.now() + timedelta(hours=hours)
            _LOGGER.info("CloudEMS Shutters: automaat %s UIT voor %.1fh", entity_id, hours)
        else:
            state.auto_disabled_until = None
        self._schedule_save_timers()

    def get_auto_enabled(self, entity_id: str) -> bool:
        """Geef terug of automaat aan is. Hervatten als timer verlopen is."""
        state = self._states.get(entity_id)
        if state is None:
            return True
        if not state.auto_enabled and state.auto_disabled_until is not None:
            if dt_util.now() >= state.auto_disabled_until:
                state.auto_enabled = True
                state.auto_disabled_until = None
                _LOGGER.info("CloudEMS Shutters: automaat %s automatisch hervat", entity_id)
        return state.auto_enabled

    def reset_schedule(self, entity_id: str) -> int:
        """v4.6.154: Reset learned schedule for a shutter. Returns cleared count."""
        cleared = self._schedule_learner.reset(entity_id)
        if cleared:
            self._schedule_save_timers()
            _LOGGER.info("CloudEMS ShutterLearner: reset %d schedules for %s", cleared, entity_id)
        return cleared

    def set_schedule_learning(self, entity_id: str, enabled: bool) -> None:
        """v4.6.157: Zet tijdschema-leren aan of uit voor een rolluik."""
        for cfg in self._configs:
            if cfg.entity_id == entity_id:
                cfg.schedule_learning = enabled
                _LOGGER.info("CloudEMS ShutterLearner: leren %s voor %s",
                             "ingeschakeld" if enabled else "uitgeschakeld", entity_id)
                return

    def get_schedule_learning(self, entity_id: str) -> bool:
        """v4.6.157: Geef terug of tijdschema-leren aan is voor een rolluik."""""
        for cfg in self._configs:
            if cfg.entity_id == entity_id:
                return cfg.schedule_learning
        return True

    def get_auto_disabled_until(self, entity_id: str):
        """Geef datetime waarop automaat hervat, of None."""
        state = self._states.get(entity_id)
        return state.auto_disabled_until if state else None

    def cancel_override(self, entity_id: str) -> None:
        """Annuleer handmatige override."""
        state = self._states.get(entity_id)
        if state:
            state.override_until = None
            state.override_action = SHUTTER_ACTION_IDLE
            _LOGGER.debug("CloudEMS Shutters: override geannuleerd voor %s", entity_id)
            self._schedule_save_timers()

    # ── Evaluatie logica ─────────────────────────────────────────────────────

    # Anti-pendel constanten
    _MIN_MOVE_INTERVAL_S = 600   # minimaal 10 min tussen bewegingen per rolluik
    _MIN_POSITION_STEP   = 5     # minimaal 5% positiewijziging om te sturen
    _TEMP_DEADBAND       = 0.3   # °C: afwijking kleiner dan dit → niets doen

    def _parse_hhmm(self, t: str) -> int:
        """Zet "HH:MM" om naar minuten-since-midnight."""
        try:
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return 0

    # ── Live-aanpasbare instellingen (gezet via text/number entiteiten) ─────

    def set_night_close(self, entity_id: str, value: str) -> None:
        """Zet nachtsluittijd live (aangeroepen door CloudEMSShutterTime entiteit)."""
        cfg = self._cfg_by_id.get(entity_id)
        if cfg:
            cfg.night_close_time = value

    def set_morning_open(self, entity_id: str, value: str) -> None:
        """Zet ochtend-openingstijd live (aangeroepen door CloudEMSShutterTime entiteit)."""
        cfg = self._cfg_by_id.get(entity_id)
        if cfg:
            cfg.morning_open_time = value

    def set_default_setpoint(self, entity_id: str, value: float) -> None:
        """Zet fallback setpoint live (aangeroepen door CloudEMSShutterSetpoint entiteit)."""
        cfg = self._cfg_by_id.get(entity_id)
        if cfg:
            cfg.default_setpoint = value

    def _safe_id(self, cfg: ShutterConfig) -> str:
        return cfg.entity_id.split(".")[-1].replace("-", "_")

    def _read_input_text(self, cfg: ShutterConfig, suffix: str, fallback: str) -> str:
        """Lees input_text helper; val terug op fallback als niet beschikbaar."""
        eid   = f"input_text.cloudems_shutter_{self._safe_id(cfg)}_{suffix}"
        state = self.hass.states.get(eid)
        if state and state.state not in ("unknown", "unavailable", ""):
            return state.state.strip()
        return fallback

    def _read_input_number(self, cfg: ShutterConfig, suffix: str, fallback: float) -> float:
        """Lees input_number helper; val terug op fallback als niet beschikbaar."""
        eid   = f"input_number.cloudems_shutter_{self._safe_id(cfg)}_{suffix}"
        state = self.hass.states.get(eid)
        if state and state.state not in ("unknown", "unavailable", ""):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return fallback

    # Compat alias gebruikt door externe code
    def _read_helper_float(self, cfg: ShutterConfig, suffix: str, fallback: float) -> float:
        return self._read_input_number(cfg, suffix, fallback)

    def _night_close(self, cfg: ShutterConfig) -> str:
        """Return close time — learned time takes priority if confident and learning enabled."""
        manual = self._read_input_text(cfg, "night_close", cfg.night_close_time)
        if cfg.schedule_learning:
            from .shutter_learner import EVENT_CLOSE
            now = dt_util.now()
            learned = self._schedule_learner.get_learned_time(
                cfg.entity_id, EVENT_CLOSE, now.weekday(), month=now.month)
            if learned is not None:
                return learned.strftime("%H:%M")
        return manual

    def _morning_open(self, cfg: ShutterConfig) -> str:
        """Open time: learned > helper > sunrise > config default."""
        if cfg.schedule_learning:
            from .shutter_learner import EVENT_OPEN
            now = dt_util.now()
            learned = self._schedule_learner.get_learned_time(
                cfg.entity_id, EVENT_OPEN, now.weekday(), month=now.month)
            if learned is not None:
                return learned.strftime("%H:%M")
        val = self._read_input_text(cfg, "morning_open", cfg.morning_open_time)
        if val == "00:00":
            return self._sunrise_open_time(cfg)
        return val

    def _learn_from_state_change(
        self,
        entity_id: str,
        new_pos: Optional[int],
        new_st: str,
        old_pos: Optional[int],
        old_st: str,
        source: str = "external",
    ) -> None:
        """Determine action from state change and record a learning observation."""
        # Respect per-shutter learning toggle
        cfg = self._cfg_by_id.get(entity_id)
        if cfg and not cfg.schedule_learning:
            return

        from .shutter_learner import EVENT_OPEN, EVENT_CLOSE
        now = dt_util.now()

        # Determine action: closing (pos goes down or state=closed) or opening
        action = None
        if new_st == "closed" and old_st != "closed":
            action = EVENT_CLOSE
        elif new_st in ("open", "opening") and old_st not in ("open", "opening"):
            action = EVENT_OPEN
        elif new_pos is not None and old_pos is not None:
            if new_pos < old_pos - 10:
                action = EVENT_CLOSE
            elif new_pos > old_pos + 10:
                action = EVENT_OPEN

        if action is None:
            return

        self._schedule_learner.observe(entity_id, action, now, source=source)
        cfg = self._cfg_by_id.get(entity_id)
        label = cfg.label if cfg else entity_id
        conf = self._schedule_learner.get_confidence(entity_id, action, now.weekday())
        _LOGGER.info(
            "ShutterLearner: observed %s %s on %s at %02d:%02d "
            "(source=%s, confidence=%.0f%%)",
            label, action, now.strftime("%A"),
            now.hour, now.minute, source, conf * 100,
        )

    def _sunrise_open_time(self, cfg: ShutterConfig) -> str:
        """Bereken openingstijd op basis van zonsopgang (sun.sun) + offset."""
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return cfg.morning_open_time
        try:
            from homeassistant.util.dt import parse_datetime, as_local
            rising_str = sun.attributes.get("next_rising") or sun.attributes.get("rising")
            if not rising_str:
                return cfg.morning_open_time
            rising_utc = parse_datetime(rising_str)
            if rising_utc is None:
                return cfg.morning_open_time
            offset_min = int(self._read_input_number(cfg, "sunrise_offset", DEFAULT_SHUTTER_SUNRISE_OFFSET))
            open_time  = as_local(rising_utc) + timedelta(minutes=offset_min)
            return open_time.strftime("%H:%M")
        except Exception:
            return cfg.morning_open_time

    def _is_summer(self) -> bool:
        """True als huidige maand in de zomerperiode valt (april t/m september)."""
        return dt_util.now().month in SHUTTER_SUMMER_MONTHS

    def _seasonal_setpoint_offset(self, cfg: ShutterConfig) -> float:
        """Zomer: setpoint lager (koeler houden), winter: hoger."""
        if self._is_summer():
            return -self._read_input_number(cfg, "summer_offset", DEFAULT_SHUTTER_SUMMER_OFFSET)
        return self._read_input_number(cfg, "winter_offset", DEFAULT_SHUTTER_WINTER_OFFSET)

    def _setpoint(self, cfg: ShutterConfig, room_setpoint: float | None) -> float:
        """Effectief setpoint: klimaat > helper > config default + seizoens-offset."""
        base = room_setpoint if room_setpoint is not None else                self._read_input_number(cfg, "setpoint", cfg.default_setpoint)
        return base + self._seasonal_setpoint_offset(cfg)

    def _away_position(self, cfg: ShutterConfig) -> int:
        """Doelpositie bij niemand thuis."""
        return int(self._read_input_number(cfg, "away_position", DEFAULT_SHUTTER_AWAY_POSITION))

    def _is_night(self, cfg: ShutterConfig) -> bool:
        """True als nu binnen de nachtperiode valt (sluit_tijd t/m ochtend_tijd)."""
        now_m  = dt_util.now().hour * 60 + dt_util.now().minute
        close  = self._parse_hhmm(self._night_close(cfg))
        open_  = self._parse_hhmm(self._morning_open(cfg))
        if close > open_:          # wraps over middernacht (normaal geval)
            return now_m >= close or now_m < open_
        return close <= now_m < open_

    def _morning_blocked(self, cfg: ShutterConfig) -> bool:
        """True als het voor de ingestelde ochtend-openingstijd is."""
        now_m = dt_util.now().hour * 60 + dt_util.now().minute
        return now_m < self._parse_hhmm(self._morning_open(cfg))

    def _pid_position(
        self,
        cfg: ShutterConfig,
        state: "ShutterState",
        room_temp: float,
        setpoint: float,
        pv_surplus_w: float,
        solar_on_window: bool,
    ) -> int | None:
        """
        PID-regelaar die een rolluikpositie (0-100%) berekent.

        Principe:
          error > 0  → kamer TE WARM  → sluiten (lage positie)
          error < 0  → kamer TE KOUD  → openen  (hoge positie)

        PV-surplus bonus:
          Bij > 500 W overschot accepteren we de kamer iets warmer
          (gratis zonnewarmte meenemen, airco/verwarming bespaart).

        Anti-pendel:
          - Deadband ±0.3°C: onder deze afwijking niets doen
          - Minimaal 10 minuten tussen elke beweging
          - Minimale stapgrootte 5%: kleinere wijziging wordt genegeerd
        """
        import time as _time

        # PV-surplus: verhoog effectief setpoint zodat gratis warmte benut wordt
        bonus = 0.0
        if pv_surplus_w > 500 and solar_on_window:
            # max +1.5°C bij 2500W+ surplus, lineair tussenin
            bonus = min(1.5, (pv_surplus_w - 500) / 1333)
        effective_sp = setpoint + bonus

        error = room_temp - effective_sp

        # Deadband — bij kleine afwijking niets doen
        if abs(error) < self._TEMP_DEADBAND:
            state.pid_integral = 0.0      # reset integral in deadband
            return None

        # Anti-pendel tijdscheck
        now_ts = _time.monotonic()
        elapsed = now_ts - state.pid_last_time
        if state.pid_last_time > 0 and elapsed < self._MIN_MOVE_INTERVAL_S:
            return None

        # PID berekening
        dt = max(elapsed, 60.0) if state.pid_last_time > 0 else 300.0

        p_term = cfg.pid_kp * error
        state.pid_integral += error * dt
        state.pid_integral  = max(-300.0, min(300.0, state.pid_integral))  # anti-windup
        i_term = cfg.pid_ki * state.pid_integral
        d_term = cfg.pid_kd * (error - state.pid_prev_error) / dt

        raw_output = p_term + i_term + d_term   # positief = te warm = sluiten

        # Omrekenen naar positie: 50% baseline, error>0 = dichter
        target_pos = int(50 - raw_output)
        target_pos = max(cfg.min_position, min(cfg.max_position, target_pos))

        # Anti-pendel stapgrootte: minimaal 5% verschil met huidige positie
        current_pos = state.current_position if state.current_position >= 0 else 50
        if abs(target_pos - current_pos) < self._MIN_POSITION_STEP:
            return None

        # Commit PID state
        state.pid_prev_error  = error
        state.pid_last_time   = now_ts
        state.pid_last_output = target_pos

        _LOGGER.debug(
            "PID[%s] temp=%.1f sp=%.1f(+%.1f) err=%.2f "
            "p=%.1f i=%.1f d=%.1f → pos=%d (was %d)",
            cfg.label, room_temp, setpoint, bonus, error,
            p_term, i_term, d_term, target_pos, current_pos,
        )
        return target_pos

    def _evaluate_one(
        self,
        cfg: ShutterConfig,
        outdoor_temp_c: float | None,
        solar_elevation_deg: float | None,
        solar_azimuth_deg: float | None,
        pv_surplus_w: float,
        room_temp: float | None,
        room_setpoint: float | None,
    ) -> ShutterDecision:
        state    = self._states.get(cfg.entity_id)
        is_night = self._is_night(cfg)
        night_window   = f"{self._night_close(cfg)}–{self._morning_open(cfg)}"
        _wind_speed    = getattr(self, '_current_wind_speed', None)
        _wind_thr      = getattr(self, '_wind_threshold_ms', 12.0)
        wind_active    = _wind_speed is not None and _wind_speed >= _wind_thr
        storm_active   = getattr(self, '_is_storm', False)

        # ── Prio 0: Rookmelder — altijd OPEN, dag én nacht ───────────────────
        if self._smoke_detected(cfg):
            _LOGGER.warning("ShutterController [%s]: rookmelder actief → open", cfg.entity_id)
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_OPEN,
                reason="rookmelder actief",
                priority=255,
            )

        # ── Prio 1: Automaat uitgeschakeld ────────────────────────────────────
        if state and not self.get_auto_enabled(cfg.entity_id):
            until  = state.auto_disabled_until
            reason = "automaat uitgeschakeld"
            if until:
                reason = f"automaat uit tot {until.strftime('%d-%m %H:%M')}"
            shadow = self._evaluate_shadow(cfg, outdoor_temp_c, solar_elevation_deg,
                                           solar_azimuth_deg, pv_surplus_w, room_temp, room_setpoint)
            return ShutterDecision(
                entity_id    = cfg.entity_id,
                action       = SHUTTER_ACTION_IDLE,
                reason       = reason,
                priority     = 0,
                shadow_action  = shadow.action,
                shadow_reason  = shadow.reason,
                shadow_position= shadow.position,
            )

        # ── Prio 2: Handmatige override — dag én nacht ───────────────────────
        if state and state.override_until and dt_util.now() < state.override_until:
            shadow = self._evaluate_shadow(cfg, outdoor_temp_c, solar_elevation_deg,
                                           solar_azimuth_deg, pv_surplus_w, room_temp, room_setpoint)
            _LOGGER.debug(
                "[shutter_shadow] %s override actief → automaat zou: %s (%s)",
                cfg.entity_id, shadow.action, shadow.reason,
            )
            return ShutterDecision(
                entity_id    = cfg.entity_id,
                action       = state.override_action,
                reason       = SHUTTER_REASON_MANUAL,
                priority     = 150,
                shadow_action  = shadow.action,
                shadow_reason  = shadow.reason,
                shadow_position= shadow.position,
            )

        # ── Prio 3: Nachtschema (night_close t/m morning_open per rolluik) ───
        # Binnen deze tijden: automaat bevroren — geen thermisch, geen afwezig.
        # Wind/storm → dicht (of al dicht = IDLE). Niets gaat open.
        if is_night:
            if wind_active or storm_active:
                wind_reason = (
                    f"windbeveiliging 's nachts ({_wind_speed:.0f} m/s)"
                    if wind_active else "storm 's nachts"
                )
                current = state.current_position if state else -1
                if current != 0:
                    _LOGGER.info("ShutterController [%s]: %s — sluit naar 0", cfg.entity_id, wind_reason)
                    return ShutterDecision(
                        entity_id=cfg.entity_id,
                        action=SHUTTER_ACTION_POSITION,
                        position=0,
                        reason=wind_reason,
                        priority=200,
                    )
                return ShutterDecision(
                    entity_id=cfg.entity_id,
                    action=SHUTTER_ACTION_IDLE,
                    reason=f"{wind_reason} — al gesloten",
                    priority=0,
                )
            # Geen wind/storm: éénmalig sluiten, daarna IDLE
            current = state.current_position if state else -1
            if current != 0:
                _LOGGER.info("ShutterController [%s]: nacht (%s) — sluit naar 0", cfg.entity_id, night_window)
                return ShutterDecision(
                    entity_id=cfg.entity_id,
                    action=SHUTTER_ACTION_POSITION,
                    position=0,
                    reason=f"nacht ({night_window})",
                    priority=120,
                )
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_IDLE,
                reason=f"nacht ({night_window}) — bevroren",
                priority=0,
            )

        # ── Vanaf hier: overdag ───────────────────────────────────────────────

        # ── Prio 4: Wind/storm overdag → volledig open ────────────────────────
        if wind_active:
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_OPEN,
                reason=f"windbeveiliging ({_wind_speed:.0f} m/s)",
                priority=200,
            )
        if storm_active:
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_OPEN,
                reason=SHUTTER_REASON_STORM,
                priority=195,
            )

        # ── Prio 4: Ochtend geblokkeerd — wacht op openingstijd ──────────────
        if self._morning_blocked(cfg):
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_IDLE,
                reason=f"wacht op ochtend ({self._morning_open(cfg)})",
                priority=0,
            )

        # ── Prio 4b: Afwezig-modus — niemand thuis → energiestand ─────────────
        if not getattr(self, '_anyone_home', True):
            away_pos = self._away_position(cfg)
            current  = state.current_position if state else -1
            if current != away_pos:
                return ShutterDecision(
                    entity_id=cfg.entity_id,
                    action=SHUTTER_ACTION_POSITION,
                    position=away_pos,
                    reason=SHUTTER_REASON_AWAY,
                    priority=90,
                )
            return ShutterDecision(
                entity_id=cfg.entity_id,
                action=SHUTTER_ACTION_IDLE,
                reason=f"{SHUTTER_REASON_AWAY} — al op {away_pos}%",
                priority=0,
            )

        # ── Hieronder: volledig automatisch op thermisch comfort + PV ─────────

        # Setpoint: klimaat > dashboard helper > config default + seizoens-offset
        setpoint = self._setpoint(cfg, room_setpoint)

        # Fallback kamertemperatuur: lees rechtstreeks van sensor
        if room_temp is None and cfg.temp_sensor:
            room_temp = self._read_temp_sensor(cfg.temp_sensor)

        sun_on_window = self._sun_hits_window(
            cfg.orientation, solar_azimuth_deg, solar_elevation_deg
        )

        # ── Prio 5: Oververhitting noodstop (>3°C boven setpoint) ────────────
        if cfg.auto_overheat and room_temp is not None:
            if room_temp > setpoint + 3.0:
                return ShutterDecision(
                    entity_id=cfg.entity_id,
                    action=SHUTTER_ACTION_POSITION,
                    position=cfg.min_position,
                    reason=f"oververhitting ({room_temp:.1f}°C > {setpoint+3:.1f}°C)",
                    priority=100,
                )

        # ── Prio 6: PID positie-sturing ──────────────────────────────────────
        # Regelt de positie continu op basis van kamertemperatuur vs setpoint.
        # Houdt rekening met PV-surplus en of de zon op het raam schijnt.
        if room_temp is not None and state is not None:
            pid_pos = self._pid_position(
                cfg, state, room_temp, setpoint, pv_surplus_w, sun_on_window
            )
            if pid_pos is not None:
                reason = f"PID temp={room_temp:.1f}°C sp={setpoint:.1f}°C → {pid_pos}%"
                if pv_surplus_w > 500:
                    reason += f" (+PV {pv_surplus_w:.0f}W)"
                return ShutterDecision(
                    entity_id=cfg.entity_id,
                    action=SHUTTER_ACTION_POSITION,
                    position=pid_pos,
                    reason=reason,
                    priority=60,
                )

        # ── Niets te doen ─────────────────────────────────────────────────────
        return ShutterDecision(
            entity_id=cfg.entity_id,
            action=SHUTTER_ACTION_IDLE,
            reason="binnen comfort — geen actie",
            priority=0,
        )

    def _evaluate_shadow(
        self,
        cfg: "ShutterConfig",
        outdoor_temp_c,
        solar_elevation_deg,
        solar_azimuth_deg,
        pv_surplus_w: float,
        room_temp,
        room_setpoint,
    ) -> "ShutterDecision":
        """
        Berekent wat de automaat zou doen als hij aan stond (shadow decision).

        Wordt gebruikt bij manual override of automaat-uit zodat het dashboard
        kan tonen: "Automaat zou sluiten — oververhitting 27°C"
        Slaat prio 1 (automaat-uit) en prio 2 (override) over.
        """
        state    = self._states.get(cfg.entity_id)
        setpoint = self._setpoint(cfg, room_setpoint)
        if room_temp is None and cfg.temp_sensor:
            room_temp = self._read_temp_sensor(cfg.temp_sensor)
        sun_on_window = self._sun_hits_window(
            cfg.orientation, solar_azimuth_deg, solar_elevation_deg
        )
        if self._is_night(cfg):
            current = state.current_position if state else -1
            if current != 0:
                return ShutterDecision(
                    entity_id=cfg.entity_id, action=SHUTTER_ACTION_POSITION,
                    position=0, reason="nacht — zou sluiten", priority=120,
                )
            return ShutterDecision(cfg.entity_id, SHUTTER_ACTION_IDLE,
                                   reason="nacht — al gesloten", priority=0)
        if self._morning_blocked(cfg):
            return ShutterDecision(cfg.entity_id, SHUTTER_ACTION_IDLE,
                                   reason=f"zou wachten op ochtend ({self._morning_open(cfg)})", priority=0)
        if cfg.auto_overheat and room_temp is not None and room_temp > setpoint + 3.0:
            return ShutterDecision(
                entity_id=cfg.entity_id, action=SHUTTER_ACTION_POSITION,
                position=cfg.min_position,
                reason=f"oververhitting ({room_temp:.1f}°C > {setpoint+3:.1f}°C)", priority=100,
            )
        if room_temp is not None and state is not None:
            pid_pos = self._pid_position(cfg, state, room_temp, setpoint, pv_surplus_w, sun_on_window)
            if pid_pos is not None:
                return ShutterDecision(
                    entity_id=cfg.entity_id, action=SHUTTER_ACTION_POSITION,
                    position=pid_pos,
                    reason=f"PID temp={room_temp:.1f}°C sp={setpoint:.1f}°C → {pid_pos}%", priority=60,
                )
        return ShutterDecision(cfg.entity_id, SHUTTER_ACTION_IDLE,
                               reason="binnen comfort — geen actie", priority=0)

    @staticmethod
    def _sun_hits_window(
        orientation: str,
        azimuth: float | None,
        elevation: float | None,
    ) -> bool:
        """Checkt of de zon op het raam schijnt op basis van oriëntatie."""
        if azimuth is None or elevation is None or elevation < 5:
            return False
        # Azimuth-bereik per raamoriëntatie (graden)
        windows = {
            "north": (315, 45),
            "east":  (45, 135),
            "south": (135, 225),
            "west":  (225, 315),
        }
        rng = windows.get(orientation)
        if rng is None:
            return False
        lo, hi = rng
        if lo < hi:
            return lo <= azimuth <= hi
        # noord wraps around 0°
        return azimuth >= lo or azimuth <= hi

    # ── HA interactie ─────────────────────────────────────────────────────────

    async def _refresh_states(self) -> None:
        """Lees actuele positie van alle covers."""
        for entity_id, state in self._states.items():
            ha_state = self.hass.states.get(entity_id)
            if ha_state is None:
                continue
            try:
                pos = ha_state.attributes.get("current_position")
                state.current_position = int(pos) if pos is not None else -1
                state.is_closed = ha_state.state == "closed"
            except (ValueError, TypeError):
                pass

    async def _apply_decisions(self, decisions: list[ShutterDecision]) -> None:
        """Pas beslissingen toe — sla idle over en vermijd onnodige herhalingen."""
        for d in decisions:
            if d.action == SHUTTER_ACTION_IDLE:
                continue
            state = self._states.get(d.entity_id)
            if state and state.last_action == d.action and d.action != SHUTTER_ACTION_POSITION:
                continue  # al in gewenste toestand
            await self._execute_action(d.entity_id, d.action, d.position, d.reason)

    async def _execute_action(
        self,
        entity_id: str,
        action: str,
        position: int | None,
        reason: str,
    ) -> None:
        """Stuur commando naar HA cover entiteit."""
        state = self._states.get(entity_id)
        # Registreer dit commando zodat de state-listener het herkent als CloudEMS-actie
        self._cloudems_commands[entity_id] = time.monotonic()

        if action == SHUTTER_ACTION_OPEN:
            await self.hass.services.async_call(
                "cover", "open_cover", {"entity_id": entity_id}, blocking=False
            )
        elif action == SHUTTER_ACTION_CLOSE:
            await self.hass.services.async_call(
                "cover", "close_cover", {"entity_id": entity_id}, blocking=False
            )
        elif action == SHUTTER_ACTION_STOP:
            await self.hass.services.async_call(
                "cover", "stop_cover", {"entity_id": entity_id}, blocking=False
            )
        elif action == SHUTTER_ACTION_POSITION and position is not None:
            await self.hass.services.async_call(
                "cover", "set_cover_position",
                {"entity_id": entity_id, "position": position},
                blocking=False,
            )

        # v4.6.153: learn from CloudEMS-initiated schedule actions (night_close / morning_open)
        if action in (SHUTTER_ACTION_CLOSE, SHUTTER_ACTION_OPEN) and "schema" in reason.lower():
            from .shutter_learner import EVENT_OPEN, EVENT_CLOSE
            learn_action = EVENT_CLOSE if action == SHUTTER_ACTION_CLOSE else EVENT_OPEN
            self._schedule_learner.observe(entity_id, learn_action, dt_util.now(), source="cloudems")
            if self._schedule_learner.dirty:
                self._schedule_save_timers()

        if state:
            state.last_action = action
            state.last_reason = reason
            state.last_changed = dt_util.now()

        _LOGGER.info(
            "CloudEMS Shutters: %s → %s (reden: %s)",
            entity_id, action, reason,
        )

    # ── Status export ─────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Geef status terug voor dashboard sensor."""
        shutters = []
        for cfg in self._configs:
            state = self._states.get(cfg.entity_id, ShutterState(entity_id=cfg.entity_id))
            override_active = (
                state.override_until is not None
                and dt_util.now() < state.override_until
            )
            shutters.append({
                "entity_id":       cfg.entity_id,
                "label":           cfg.label,
                "area_name":       cfg.area_name,
                "orientation":     cfg.orientation,
                "group":           cfg.group,
                "position":        state.current_position,
                "is_closed":       state.is_closed,
                "last_action":     state.last_action,
                "last_reason":     state.last_reason,
                "override_active": override_active,
                "override_until":  state.override_until.isoformat() if state.override_until else None,
                "auto_enabled":    self.get_auto_enabled(cfg.entity_id),
                "automaat":        self.get_auto_enabled(cfg.entity_id) and not override_active,
                "auto_disabled_until": state.auto_disabled_until.isoformat() if state.auto_disabled_until else None,
                # v4.5.86: shadow — wat de automaat zou doen (tonen als advies op dashboard)
                "shadow_action":   state.shadow_action,
                "shadow_reason":   state.shadow_reason,
                "shadow_position": state.shadow_position,
                "night_close_time":    self._night_close(cfg),
                "morning_open_time":   self._morning_open(cfg),
                "default_setpoint":    self._read_helper_float(cfg, "setpoint", cfg.default_setpoint),
                "is_night":            self._is_night(cfg),
                "is_summer":           self._is_summer(),
                "anyone_home":         getattr(self, "_anyone_home", True),
                "is_storm":            getattr(self, "_is_storm", False),
                "external_detected":   False,  # runtime vlag, zie _async_on_cover_state_changed
                "sunrise_open_time":   self._sunrise_open_time(cfg),
                "away_position":       self._away_position(cfg),
                "seasonal_offset":     self._seasonal_setpoint_offset(cfg),
                "temp_sensor":         cfg.temp_sensor or "",
                "orientation_learned": (
                    self._learner.get_orientation(cfg.area_id)
                    if self._learner and cfg.area_id else cfg.orientation
                ),
                "orientation_confident": (
                    self._learner._rooms.get(cfg.area_id, None) is not None
                    and getattr(self._learner._rooms.get(cfg.area_id), "orientation_confident", False)
                    if self._learner and cfg.area_id else False
                ),
                # v4.6.153: learned schedule status
                "schedule_learning": cfg.schedule_learning,
                "schedule_learned": self._schedule_learner.get_status(cfg.entity_id) if cfg.schedule_learning else {},
                # v4.6.154: today's active times and first-time hint
                "schedule_open_today":  self._morning_open(cfg),
                "schedule_close_today": self._night_close(cfg),
                "schedule_needs_data":  self._schedule_learner.needs_more_data(cfg.entity_id) if cfg.schedule_learning else 0,
            })
        # Learner voortgang per kamer
        learner_status = self._learner.get_status() if self._learner else []
        return {
            "shutter_count":   len(self._configs),
            "shutters":        shutters,
            "groups": [
                {"name": g.name, "label": g.label, "count": len(g.entity_ids)}
                for g in self._groups
            ],
            "last_evaluation": self._last_evaluation.isoformat() if self._last_evaluation else None,
            "learner":         learner_status,
        }
