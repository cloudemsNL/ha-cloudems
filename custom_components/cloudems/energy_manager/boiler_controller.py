# -*- coding: utf-8 -*-
"""
CloudEMS Smart Boiler / Socket Controller — v3.0.0

v1.x  Enkelvoudige boilers, aan/uit op basis van goedkope uren / PV-surplus.
v2.0  Cascade-groepen: sequential / parallel / priority / auto.
v2.1  Zelflerend leveringsboiler-detectie (temp + energie).
v3.0  Volledig intelligent systeem:
        - cycle_kwh persistent over HA-restarts
        - Gebruikspatroon per uur (voorspellend opwarmen)
        - Thermische verliescompensatie (afkoelsnelheid per boiler)
        - Vraaggestuurde prioriteit via flow-sensor / debietmeter
        - Seizoenspatroon (automatisch zomer/winter setpoints)
        - Netcongestie koppeling (comfort vs buffer prioriteit)
        - Proportionele dimmer sturing (kW-nauwkeurig op PV-surplus)

Copyright 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# ─── Sturingmodi ─────────────────────────────────────────────────────────────
MODE_CHEAP_HOURS    = "cheap_hours"
MODE_NEGATIVE_PRICE = "negative_price"
MODE_PV_SURPLUS     = "pv_surplus"
MODE_EXPORT_REDUCE  = "export_reduce"
MODE_HEAT_DEMAND    = "heat_demand"
MODE_CONGESTION_OFF = "congestion_off"

CASCADE_SEQUENTIAL  = "sequential"
CASCADE_PARALLEL    = "parallel"
CASCADE_PRIORITY    = "priority"
CASCADE_AUTO        = "auto"
CASCADE_STANDBY     = "standby"

# ─── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_SURPLUS_THRESHOLD_W = 300
DEFAULT_EXPORT_THRESHOLD_A  = 1.0
DEFAULT_HEAT_DEMAND_TEMP_C  = 5.0
DEFAULT_MIN_ON_MINUTES      = 10
DEFAULT_MIN_OFF_MINUTES     = 5
STAGGER_DEFAULT_S           = 45
SAFETY_MAX_C                = 80.0
HYSTERESIS_C                = 2.0

# ─── Leerdata ────────────────────────────────────────────────────────────────
LEARN_FILE           = "/config/.storage/cloudems_boiler_learn.json"
DELIVERY_MIN_EVENTS  = 5
DELIVERY_CONFIDENCE  = 0.65
DELIVERY_DECAY_HOURS = 168

# ─── Seizoen ─────────────────────────────────────────────────────────────────
SEASON_SUMMER_C  = 15.0
SEASON_WINTER_C  = 8.0
SEASON_DELTA_C   = -5.0
SEASON_HYST_DAYS = 3

# ─── Thermisch verlies ────────────────────────────────────────────────────────
THERMAL_WINDOW_S  = 3600
THERMAL_MIN_DELTA = 0.3

# ─── Proportionele dimmer ─────────────────────────────────────────────────────
DIMMER_MIN_PCT  = 10.0
DIMMER_UPDATE_S = 30


@dataclass
class BoilerDecision:
    entity_id:     str
    label:         str
    action:        str
    reason:        str
    current_state: bool
    group_id:      str   = ""
    power_pct:     float = 0.0


@dataclass
class BoilerState:
    entity_id:           str
    label:               str
    phase:               str   = "L1"
    power_w:             float = 1000.0
    min_on_s:            float = DEFAULT_MIN_ON_MINUTES  * 60
    min_off_s:           float = DEFAULT_MIN_OFF_MINUTES * 60
    modes:               list  = field(default_factory=lambda: [
        MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE, MODE_PV_SURPLUS, MODE_EXPORT_REDUCE])
    cheap_hours_rank:    int   = 3
    temp_sensor:         str   = ""
    energy_sensor:       str   = ""
    flow_sensor:         str   = ""
    setpoint_c:          float = 60.0
    min_temp_c:          float = 40.0
    comfort_floor_c:     float = 50.0
    setpoint_summer_c:   float = 0.0
    setpoint_winter_c:   float = 0.0
    priority:            int   = 0
    last_on_ts:          float = 0.0
    last_off_ts:         float = 0.0
    current_temp_c:      Optional[float] = None
    current_power_w:     Optional[float] = None
    cycle_kwh:           float = 0.0
    active_setpoint_c:   float = 0.0
    is_delivery:         bool  = False
    outside_temp_c:      Optional[float] = None
    heat_demand_temp_c:  float = DEFAULT_HEAT_DEMAND_TEMP_C
    congestion_active:   bool  = False
    thermal_loss_c_h:    float = 0.0
    last_demand_ts:      float = 0.0
    stagger_ticks:       int   = 0
    control_mode:        str   = "switch"
    surplus_setpoint_c:  float = 75.0    # setpoint bij PV-surplus (setpoint_boost modus)
    preset_on:           str   = "boost"
    preset_off:          str   = "green"
    dimmer_on_pct:       float = 100.0
    dimmer_off_pct:      float = 0.0
    dimmer_proportional: bool  = False
    post_saldering_mode: bool  = False
    delta_t_optimize:    bool  = False
    _temp_history:       list  = field(default_factory=list, repr=False)
    _energy_kwh_last:    Optional[float] = field(default=None, repr=False)
    _energy_ts_last:     Optional[float] = field(default=None, repr=False)
    _dimmer_last_pct:    float = field(default=0.0, repr=False)
    _dimmer_last_ts:     float = field(default=0.0, repr=False)

    @property
    def needs_heat(self) -> bool:
        """True als de boiler verwarming nodig heeft t.o.v. het actieve setpoint.

        Zonder temperatuursensor (current_temp_c is None): altijd True zodat
        triggers (PV-surplus, goedkope uren) de boiler kunnen aansturen.
        """
        if self.current_temp_c is None:
            return True   # geen sensor → vertrouw op triggers
        sp = self.active_setpoint_c or self.setpoint_c
        return self.current_temp_c < (sp - HYSTERESIS_C)

    @property
    def temp_deficit_c(self) -> float:
        sp = self.active_setpoint_c or self.setpoint_c
        if self.current_temp_c is None:
            return 0.0
        return max(0.0, sp - self.current_temp_c)

    @property
    def minutes_to_setpoint(self) -> Optional[float]:
        if self.current_temp_c is None or self.temp_deficit_c <= 0:
            return 0.0
        if self.power_w <= 0:
            return None
        kwh_needed = self.temp_deficit_c * 50 * 4.18 / 3600
        return (kwh_needed / (self.power_w / 1000.0)) * 60


@dataclass
class CascadeGroup:
    id:              str
    name:            str
    mode:            str               = CASCADE_AUTO
    boilers:         list[BoilerState] = field(default_factory=list)
    stagger_delay_s: float             = STAGGER_DEFAULT_S
    learner:         Optional[object]  = field(default=None, repr=False)

    @property
    def total_power_w(self) -> float:
        return sum(b.power_w for b in self.boilers)

    @property
    def avg_temp_c(self) -> Optional[float]:
        temps = [b.current_temp_c for b in self.boilers if b.current_temp_c is not None]
        return round(sum(temps) / len(temps), 1) if temps else None

    def get_sequential_order(self) -> list[BoilerState]:
        delivery_eid = self.learner.get_delivery_entity(self.boilers) if self.learner else None

        def sort_key(b: BoilerState):
            is_delivery = (b.entity_id == delivery_eid) if delivery_eid else False
            return (0 if is_delivery else 1, b.priority, -(b.current_temp_c or 0))

        return sorted(self.boilers, key=sort_key)


# ─── BoilerLearner ────────────────────────────────────────────────────────────

class BoilerLearner:
    """
    Persistent leergeheugen voor één cascade-groep.
    Bevat: leveringsboiler-detectie, gebruikspatroon per uur,
    thermisch verlies per boiler, seizoensstatus, cycle_kwh.
    """

    def __init__(self, group_id: str) -> None:
        self._gid  = group_id
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(LEARN_FILE):
                with open(LEARN_FILE) as f:
                    self._data = json.load(f)
        except Exception as exc:
            _LOGGER.warning("BoilerLearner: load fout: %s", exc)
            self._data = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(LEARN_FILE), exist_ok=True)
            with open(LEARN_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            _LOGGER.warning("BoilerLearner: save fout: %s", exc)

    def _g(self) -> dict:
        return self._data.setdefault(self._gid, {})

    # ── 1. Leveringsboiler ────────────────────────────────────────────────────

    def record_cycle_start(self, boilers: list) -> None:
        now = time.time()
        temp_cands = [b for b in boilers if b.current_temp_c is not None and b.needs_heat]
        if temp_cands:
            winner = max(temp_cands, key=lambda b: b.temp_deficit_c)
            score  = winner.temp_deficit_c
            method = "temp"
        else:
            kwh_cands = [b for b in boilers if b.cycle_kwh > 0.05]
            if not kwh_cands:
                return
            winner = max(kwh_cands, key=lambda b: b.cycle_kwh)
            score  = winner.cycle_kwh * 10.0
            method = "energy"

        events  = self._g().setdefault("delivery_events", {})
        eid_evs = events.setdefault(winner.entity_id, [])
        eid_evs.append({"ts": now, "score": score, "method": method})
        events[winner.entity_id] = eid_evs[-200:]
        _LOGGER.debug("BoilerLearner [%s]: cyclus → %s (%.2f, %s)", self._gid, winner.label, score, method)

        kwh_store = self._g().setdefault("cycle_kwh", {})
        for b in boilers:
            kwh_store[b.entity_id] = 0.0
            b.cycle_kwh = 0.0
        self._save()

    def restore_cycle_kwh(self, boilers: list) -> None:
        store = self._g().get("cycle_kwh", {})
        for b in boilers:
            b.cycle_kwh = float(store.get(b.entity_id, 0.0))

    def update_cycle_kwh(self, boilers: list) -> None:
        store   = self._g().setdefault("cycle_kwh", {})
        changed = False
        for b in boilers:
            old = store.get(b.entity_id, 0.0)
            if abs(b.cycle_kwh - old) > 0.005:
                store[b.entity_id] = round(b.cycle_kwh, 4)
                changed = True
        if changed:
            self._save()

    def get_delivery_entity(self, boilers: list) -> Optional[str]:
        events = self._g().get("delivery_events", {})
        if not events:
            return None
        now     = time.time()
        decay_s = DELIVERY_DECAY_HOURS * 3600
        eids    = [b.entity_id for b in boilers]
        weighted: dict[str, float] = {}
        total_w = 0.0
        for eid in eids:
            w = sum(e.get("score", 1.0) * (0.5 ** ((now - e["ts"]) / decay_s))
                    for e in events.get(eid, []))
            weighted[eid] = w
            total_w += w
        if total_w < 1e-6:
            return None
        if sum(len(events.get(eid, [])) for eid in eids) < DELIVERY_MIN_EVENTS:
            return None
        best = max(weighted, key=weighted.__getitem__)
        return best if weighted[best] / total_w >= DELIVERY_CONFIDENCE else None

    # ── 2. Gebruikspatroon per uur + dag van de week ──────────────────────────

    def record_demand(self, hour: int) -> None:
        """Registreer warm-water gebruik: globaal patroon + dag-van-de-week matrix."""
        # Globaal 24-uurs patroon (achterwaarts compatibel)
        pattern = self._g().setdefault("usage_pattern", [0.0] * 24)
        pattern[hour] = pattern[hour] * 0.85 + 0.15
        self._g()["usage_pattern"] = pattern

        # Dag-van-de-week matrix: 7 × 24, index 0 = maandag
        weekday = datetime.now().weekday()
        dow = self._g().setdefault("usage_pattern_dow", [[0.0] * 24 for _ in range(7)])
        dow[weekday][hour] = dow[weekday][hour] * 0.90 + 0.10
        self._g()["usage_pattern_dow"] = dow

        # Anomalie-teller: cycli per dag
        today_key = datetime.now().strftime("%Y-%m-%d")
        anomaly   = self._g().setdefault("anomaly", {"date": today_key, "count": 0, "alerted": False})
        if anomaly["date"] != today_key:
            anomaly = {"date": today_key, "count": 0, "alerted": False}
        anomaly["count"] += 1
        self._g()["anomaly"] = anomaly
        self._save()

    def get_usage_pattern(self) -> list:
        return self._g().get("usage_pattern", [0.0] * 24)

    def get_usage_pattern_dow(self) -> list:
        """7 × 24 matrix: dow[weekdag][uur]."""
        return self._g().get("usage_pattern_dow", [[0.0] * 24 for _ in range(7)])

    def should_preheat(self, hour_now: int, minutes_to_setpoint: Optional[float]) -> bool:
        """Controleer of preventief opwarmen nodig is op basis van dag+uur patroon."""
        if minutes_to_setpoint is None or minutes_to_setpoint <= 0:
            return False
        lookahead = max(1, int(minutes_to_setpoint / 60) + 1)

        # Dag-van-de-week patroon heeft prioriteit als er voldoende data is
        dow     = self.get_usage_pattern_dow()
        weekday = datetime.now().weekday()
        day_pat = dow[weekday]
        day_sum = sum(day_pat)
        if day_sum > 0.5:
            future = sum(day_pat[(hour_now + i) % 24] for i in range(1, lookahead + 1))
            avg    = day_sum / 24
            if future > max(0.15, avg * 1.4):
                _LOGGER.debug("BoilerLearner [%s]: preheat via dag-%d patroon", self._gid, weekday)
                return True

        # Fallback: globaal 24-uurs patroon
        pattern       = self.get_usage_pattern()
        future_demand = sum(pattern[(hour_now + i) % 24] for i in range(1, lookahead + 1))
        avg_demand    = sum(pattern) / 24 if any(pattern) else 0.0
        return future_demand > max(0.2, avg_demand * 1.5)

    def optimal_start_before_minutes(self, hour_target: int, minutes_to_setpoint: float) -> float:
        """
        Bereken hoeveel minuten vóór het verwachte piekuur gestart moet worden.
        Geeft 0 terug als er geen opwarmtijd nodig is.
        """
        if minutes_to_setpoint <= 0:
            return 0.0
        # Zoek het eerstvolgende piekuur op basis van dag-van-de-week patroon
        dow     = self.get_usage_pattern_dow()
        weekday = datetime.now().weekday()
        day_pat = dow[weekday]
        avg     = sum(day_pat) / 24 if any(day_pat) else 0.0
        # Vind de eerstvolgende piek na huidig uur
        for offset in range(1, 13):
            h = (hour_target + offset) % 24
            if day_pat[h] > max(0.15, avg * 1.4):
                # Start `minutes_to_setpoint` minuten vóór dat uur
                return max(0.0, offset * 60 - minutes_to_setpoint)
        return 0.0

    # ── Afwijkingsdetectie ────────────────────────────────────────────────────

    def check_anomaly(self, boilers: list) -> Optional[str]:
        """
        Detecteer ongewoon hoog verbruik (bijv. lekkage, logeerpartij).
        Geeft een notificatiebericht terug als er een anomalie is, anders None.
        """
        anom = self._g().get("anomaly", {})
        today_key = datetime.now().strftime("%Y-%m-%d")
        if anom.get("date") != today_key or anom.get("alerted"):
            return None

        count = anom.get("count", 0)
        # Bereken gemiddeld dagelijks verbruik uit historische data
        dow      = self.get_usage_pattern_dow()
        weekday  = datetime.now().weekday()
        day_sum  = sum(dow[weekday])
        # Schat normaal aantal cycli: als day_sum > 0.5 dan hebben we data
        # Elke 0.1 eenheid ≈ 1 cyclus; threshold bij 2.5× normaal
        normal_cycles = max(2.0, day_sum * 10)
        if count > normal_cycles * 2.5:
            # Markeer als gestuurd
            anom["alerted"] = True
            self._g()["anomaly"] = anom
            self._save()
            label_list = ", ".join(b.label for b in boilers)
            return (f"CloudEMS Boiler Cascade [{self._gid}]: ongewoon hoog verbruik vandaag — "
                    f"{int(count)} cycli (normaal ~{int(normal_cycles)}). "
                    f"Controleer boilers: {label_list}.")

    # ── 3. Thermisch verlies ──────────────────────────────────────────────────

    def update_thermal_loss(self, boiler: BoilerState) -> None:
        if boiler.current_temp_c is None:
            return
        now  = time.time()
        hist = boiler._temp_history
        hist.append((now, boiler.current_temp_c))
        boiler._temp_history = hist[-30:]
        if len(hist) < 2:
            return
        dt_s    = hist[-1][0] - hist[0][0]
        delta_c = hist[0][1] - hist[-1][1]
        if dt_s < THERMAL_WINDOW_S * 0.5 or delta_c < THERMAL_MIN_DELTA:
            return
        boiler.thermal_loss_c_h = round(delta_c / (dt_s / 3600.0), 3)
        losses = self._g().setdefault("thermal_loss", {})
        losses[boiler.entity_id] = boiler.thermal_loss_c_h
        self._save()

    def restore_thermal_loss(self, boilers: list) -> None:
        losses = self._g().get("thermal_loss", {})
        for b in boilers:
            if b.entity_id in losses:
                b.thermal_loss_c_h = float(losses[b.entity_id])

    def time_until_cold(self, boiler: BoilerState) -> Optional[float]:
        if boiler.thermal_loss_c_h <= 0 or boiler.current_temp_c is None:
            return None
        margin = boiler.current_temp_c - boiler.comfort_floor_c
        return None if margin < 0 else (margin / boiler.thermal_loss_c_h) * 60.0

    # ── 4. Seizoenspatroon ────────────────────────────────────────────────────

    def update_season(self, outside_temp_c: Optional[float]) -> str:
        if outside_temp_c is None:
            return self.get_season()
        sd      = self._g().setdefault("season_data", {"season": "winter", "transition_days": 0, "last_ts": 0.0})
        now_day  = int(time.time() / 86400)
        last_day = int(sd.get("last_ts", 0) / 86400)
        current  = sd.get("season", "winter")
        if now_day != last_day:
            sd["last_ts"] = time.time()
            target = "summer" if outside_temp_c > SEASON_SUMMER_C else ("winter" if outside_temp_c < SEASON_WINTER_C else current)
            if target != current:
                sd["transition_days"] = sd.get("transition_days", 0) + 1
                if sd["transition_days"] >= SEASON_HYST_DAYS:
                    sd["season"] = target
                    sd["transition_days"] = 0
                    _LOGGER.info("BoilerLearner [%s]: seizoen → %s (%.1f°C)", self._gid, target, outside_temp_c)
            else:
                sd["transition_days"] = 0
            self._save()
        return sd.get("season", "winter")

    def get_season(self) -> str:
        return self._g().get("season_data", {}).get("season", "winter")

    # ── Status ────────────────────────────────────────────────────────────────

    def get_learn_status(self, boilers: list) -> dict:
        events  = self._g().get("delivery_events", {})
        now     = time.time()
        decay_s = DELIVERY_DECAY_HOURS * 3600
        result: dict = {}
        total_w = 0.0
        for b in boilers:
            evs = events.get(b.entity_id, [])
            w   = sum(e.get("score", 1.0) * (0.5 ** ((now - e["ts"]) / decay_s)) for e in evs)
            result[b.entity_id] = {"label": b.label, "events": len(evs), "weight": round(w, 2),
                                   "loss_c_h": b.thermal_loss_c_h, "cycle_kwh": round(b.cycle_kwh, 3)}
            total_w += w
        if total_w > 0:
            for eid in result:
                result[eid]["confidence_pct"] = round(result[eid]["weight"] / total_w * 100, 1)
        return {
            "delivery_events":      result,
            "usage_pattern":        self.get_usage_pattern(),
            "usage_pattern_dow":    self.get_usage_pattern_dow(),
            "season":               self.get_season(),
            "total_events":         sum(r["events"] for r in result.values()),
            "anomaly":              self._g().get("anomaly", {}),
        }

    def reset(self) -> None:
        self._data.pop(self._gid, None)
        self._save()
        _LOGGER.info("BoilerLearner [%s]: leerdata gewist", self._gid)


# ─── BoilerController ─────────────────────────────────────────────────────────

class BoilerController:
    """CloudEMS boiler/stopcontact controller v3.0."""

    def __init__(self, hass: HomeAssistant, boiler_configs: list[dict]) -> None:
        self._hass    = hass
        self._boilers: list[BoilerState]  = []
        self._groups:  list[CascadeGroup] = []
        self._p1_surplus_w: float = 0.0
        self._p1_last_ts:   float = 0.0
        self._weekly_kwh:   dict  = {}  # entity_id → {week_key: kwh}
        for cfg in boiler_configs:
            # Groep-dict heeft "units" (lijst van boilers) en optioneel "id"/"name"
            # Enkelvoudige boiler-dict heeft "entity_id" direct
            if cfg.get("units") is not None or cfg.get("group"):
                self._groups.append(self._build_group(cfg))
            elif cfg.get("entity_id"):
                self._boilers.append(self._build_boiler(cfg))
            else:
                _LOGGER.warning(
                    "BoilerController: onbekende config-structuur overgeslagen: %s",
                    list(cfg.keys())[:6]
                )
        _LOGGER.info("BoilerController v3.1: %d enkelvoudig + %d cascade (%d groepen)",
                     len(self._boilers), sum(len(g.boilers) for g in self._groups), len(self._groups))
        self._power_store = Store(hass, 1, "cloudems_boiler_learned_power_v1")
        self._power_dirty = False
        self._power_last_save = 0.0

    def _build_boiler(self, cfg: dict) -> BoilerState:
        return BoilerState(
            entity_id          = cfg["entity_id"],
            label              = cfg.get("label", cfg["entity_id"]),
            phase              = cfg.get("phase", "L1"),
            power_w            = float(cfg.get("power_w", 1000.0)),
            min_on_s           = float(cfg.get("min_on_minutes",  DEFAULT_MIN_ON_MINUTES))  * 60,
            min_off_s          = float(cfg.get("min_off_minutes", DEFAULT_MIN_OFF_MINUTES)) * 60,
            modes              = cfg.get("modes", [MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE, MODE_PV_SURPLUS, MODE_EXPORT_REDUCE]),
            cheap_hours_rank   = int(cfg.get("cheap_hours_rank", 3)),
            temp_sensor        = cfg.get("temp_sensor", ""),
            energy_sensor      = cfg.get("energy_sensor", ""),
            flow_sensor        = cfg.get("flow_sensor", ""),
            setpoint_c         = float(cfg.get("setpoint_c", 60.0)),
            min_temp_c         = float(cfg.get("min_temp_c", 40.0)),
            comfort_floor_c    = float(cfg.get("comfort_floor_c", 50.0)),
            setpoint_summer_c  = float(cfg.get("setpoint_summer_c", 0.0)),
            setpoint_winter_c  = float(cfg.get("setpoint_winter_c", 0.0)),
            priority           = int(cfg.get("priority", 0)),
            control_mode       = cfg.get("control_mode", "switch"),
            surplus_setpoint_c = float(cfg.get("surplus_setpoint_c", 75.0)),
            preset_on          = cfg.get("preset_on",  "boost"),
            preset_off         = cfg.get("preset_off", "green"),
            dimmer_on_pct      = float(cfg.get("dimmer_on_pct",  100.0)),
            dimmer_off_pct      = float(cfg.get("dimmer_off_pct", 0.0)),
            dimmer_proportional = bool(cfg.get("dimmer_proportional", False)),
            post_saldering_mode = bool(cfg.get("post_saldering_mode", False)),
            delta_t_optimize    = bool(cfg.get("delta_t_optimize", False)),
        )

    def _build_group(self, cfg: dict) -> CascadeGroup:
        group_id = cfg.get("id", "group")
        learner  = BoilerLearner(group_id)
        raw_units = cfg.get("units", [])
        skipped = [u for u in raw_units if not u.get("entity_id")]
        if skipped:
            _LOGGER.warning(
                "BoilerController: %d unit(s) in groep '%s' overgeslagen — entity_id ontbreekt. "                "Controleer de boiler-configuratie.",
                len(skipped), cfg.get("name", "?")
            )
        boilers  = [self._build_boiler(u) for u in raw_units if u.get("entity_id")]
        learner.restore_cycle_kwh(boilers)
        learner.restore_thermal_loss(boilers)
        return CascadeGroup(
            id              = group_id,
            name            = cfg.get("name", "Cascade groep"),
            mode            = cfg.get("mode", CASCADE_AUTO),
            boilers         = boilers,
            stagger_delay_s = float(cfg.get("stagger_delay_s", STAGGER_DEFAULT_S)),
            learner         = learner,
        )

    async def async_setup(self) -> None:
        """Laad eerder geleerde vermogens uit opslag."""
        import time as _time
        saved = await self._power_store.async_load() or {}
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            stored_w = saved.get(b.entity_id)
            if stored_w and float(stored_w) > 50:
                b.power_w = float(stored_w)
                _LOGGER.debug(
                    "BoilerController: geleerd vermogen hersteld voor %s: %.0fW",
                    b.label, b.power_w,
                )
        if saved:
            _LOGGER.info("BoilerController: vermogensgeheugen geladen (%d boilers)", len(saved))

    async def _async_save_power(self) -> None:
        """Sla geleerde vermogens op — max 1x per 5 minuten."""
        import time as _time
        if not self._power_dirty:
            return
        if (_time.time() - self._power_last_save) < 300:
            return
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        await self._power_store.async_save(
            {b.entity_id: round(b.power_w, 0) for b in all_b if b.power_w > 50}
        )
        self._power_dirty     = False
        self._power_last_save = _time.time()

    # ── Hoofdevaluatie ────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_info:          dict,
        solar_surplus_w:     float = 0.0,
        phase_currents:      Optional[dict] = None,
        phase_max_currents:  Optional[dict] = None,
        surplus_threshold_w: float = DEFAULT_SURPLUS_THRESHOLD_W,
        export_threshold_a:  float = DEFAULT_EXPORT_THRESHOLD_A,
    ) -> list[BoilerDecision]:
        phase_currents = phase_currents or {}
        decisions: list[BoilerDecision] = []

        # P1 directe respons: gebruik de meest recente P1-waarde als die recent is (< 90s)
        now = time.time()
        effective_surplus = solar_surplus_w
        if self._p1_surplus_w > 0 and (now - self._p1_last_ts) < 90:
            effective_surplus = max(solar_surplus_w, self._p1_surplus_w)

        await self._read_sensors()

        # Tijdens PV-surplus: gebruik maximaal setpoint om zoveel mogelijk zonne-energie op te slaan
        surplus_active = effective_surplus >= surplus_threshold_w

        for b in self._boilers:
            if surplus_active and MODE_PV_SURPLUS in b.modes:
                # Sla zo veel mogelijk zon op: zet setpoint naar maximum (veiligheidsgrens - 2°C)
                b.active_setpoint_c = SAFETY_MAX_C - 2.0
            else:
                b.active_setpoint_c = self._delta_t_setpoint(b, b.setpoint_c)
            decisions.append(await self._evaluate_single(
                b, price_info, effective_surplus, phase_currents, surplus_threshold_w, export_threshold_a))

        for group in self._groups:
            if group.learner:
                outside_c = next((b.outside_temp_c for b in group.boilers if b.outside_temp_c is not None), None)
                season    = group.learner.update_season(outside_c)
                for b in group.boilers:
                    if surplus_active and MODE_PV_SURPLUS in b.modes:
                        # PV-surplus: maximaal opladen met zonne-energie
                        b.active_setpoint_c = SAFETY_MAX_C - 2.0
                    else:
                        sp = self._seasonal_setpoint(b, season)
                        b.active_setpoint_c = self._delta_t_setpoint(b, sp)

                # Anomalie check — notificatie sturen als nodig
                msg = group.learner.check_anomaly(group.boilers)
                if msg:
                    _LOGGER.warning("BoilerController anomalie: %s", msg)
                    try:
                        await self._hass.services.async_call(
                            "persistent_notification", "create",
                            {"title": "CloudEMS — Boiler anomalie", "message": msg,
                             "notification_id": f"cloudems_boiler_anomaly_{group.id}"},
                            blocking=False)
                    except Exception:
                        pass

            decisions.extend(await self._evaluate_group(group, price_info, effective_surplus, surplus_threshold_w))

        # Weekbudget bijwerken
        self._update_weekly_kwh()

        return decisions

    def _delta_t_setpoint(self, b: BoilerState, base_sp: float) -> float:
        """
        Delta-T optimalisatie: verlaag het setpoint dynamisch als de boiler nog
        ruim boven de comfort-grens zit, om onnodige warmte-overschotten te vermijden.
        Alleen actief als delta_t_optimize=True en thermal_loss_c_h bekend is.
        """
        if not b.delta_t_optimize or b.thermal_loss_c_h <= 0 or b.current_temp_c is None:
            return base_sp
        margin = b.current_temp_c - b.comfort_floor_c
        if margin < 5:
            return base_sp  # Te krap — normaal setpoint
        # Verlaag setpoint proportioneel: max 8°C lager bij grote marge
        reduction = min(8.0, margin * 0.25)
        optimized = max(b.comfort_floor_c + 5, base_sp - reduction)
        _LOGGER.debug("DeltaT [%s]: setpoint %.1f→%.1f°C (marge %.1f°C)",
                      b.label, base_sp, optimized, margin)
        return optimized

    def _weekly_budget_key(self) -> str:
        now = datetime.now()
        return f"{now.year}-W{now.isocalendar()[1]:02d}"

    def _update_weekly_kwh(self) -> None:
        week = self._weekly_budget_key()
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            eid = b.entity_id
            if eid not in self._weekly_kwh:
                self._weekly_kwh[eid] = {}
            self._weekly_kwh[eid][week] = self._weekly_kwh[eid].get(week, 0.0) + b.cycle_kwh

    def get_weekly_budget(self) -> dict:
        """Geeft per boiler het kWh-verbruik van de huidige en vorige week."""
        week     = self._weekly_budget_key()
        all_b    = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        result   = {}
        for b in all_b:
            wdata = self._weekly_kwh.get(b.entity_id, {})
            weeks = sorted(wdata.keys(), reverse=True)[:4]
            result[b.entity_id] = {
                "label":        b.label,
                "current_week": round(wdata.get(week, 0.0), 3),
                "history":      {w: round(wdata[w], 3) for w in weeks},
                "cycle_kwh":    round(b.cycle_kwh, 3),
            }
        return result

    def _seasonal_setpoint(self, b: BoilerState, season: str) -> float:
        if season == "summer":
            return b.setpoint_summer_c if b.setpoint_summer_c > 0 else max(b.min_temp_c + 5, b.setpoint_c + SEASON_DELTA_C)
        return b.setpoint_winter_c if b.setpoint_winter_c > 0 else b.setpoint_c

    def auto_calibrate_season(self, outside_temp_c: float) -> None:
        """
        v1.32: Pas boilersetpoints automatisch aan op basis van buitentemperatuur.
        Alleen actief als de gebruiker GEEN expliciete zomer/winter setpoints heeft
        geconfigureerd (setpoint_summer_c == 0 of setpoint_winter_c == 0).

        Logica:
          - Warm buiten (>= 15°C): zomersetpoint = setpoint_c - 5°C (minder legionella-risico,
            minder stilstandsverlies, sneller opgewarmd door zon)
          - Koud buiten (<= 5°C):  wintersetpoint = setpoint_c + 3°C (extra buffer voor
            piekverbruik verwarming, grotere thermische massa beschikbaar)
        """
        import logging as _l
        log = _l.getLogger(__name__)
        for b in getattr(self, "_boilers", []):
            changed = False
            if outside_temp_c >= 15.0 and b.setpoint_summer_c == 0:
                new_sp = max(b.min_temp_c + 5, b.setpoint_c - 5.0)
                if abs(new_sp - b.setpoint_c) > 0.5:
                    b.setpoint_summer_c = round(new_sp, 1)
                    changed = True
                    log.info(
                        "BoilerController '%s': auto zomersetpoint %.1f°C "
                        "(buiten %.1f°C)",
                        b.name, b.setpoint_summer_c, outside_temp_c,
                    )
            elif outside_temp_c <= 5.0 and b.setpoint_winter_c == 0:
                new_sp = min(b.setpoint_c + 3.0, 70.0)
                if abs(new_sp - b.setpoint_c) > 0.5:
                    b.setpoint_winter_c = round(new_sp, 1)
                    changed = True
                    log.info(
                        "BoilerController '%s': auto wintersetpoint %.1f°C "
                        "(buiten %.1f°C)",
                        b.name, b.setpoint_winter_c, outside_temp_c,
                    )

    # ── Enkelvoudige boiler ───────────────────────────────────────────────────

    async def _evaluate_single(self, b, price_info, solar_surplus_w,
                                phase_currents, surplus_threshold_w, export_threshold_a):
        now     = time.time()
        is_on   = self._is_on(b.entity_id, b)
        want_on = False
        reason  = ""

        if MODE_NEGATIVE_PRICE in b.modes and price_info.get("is_negative"):
            want_on = True; reason = f"Negatieve prijs: {price_info.get('current', 0):.4f} €/kWh"
        if not want_on and MODE_CHEAP_HOURS in b.modes and price_info.get(f"in_cheapest_{b.cheap_hours_rank}h"):
            want_on = True; reason = f"Goedkoopste {b.cheap_hours_rank}u ({price_info.get('current', 0):.4f} €/kWh)"

        # Post-saldering modus: agressiever op PV-surplus sturen, minder afhankelijk van goedkope uren
        eff_threshold = (surplus_threshold_w * 0.4) if b.post_saldering_mode else surplus_threshold_w
        if not want_on and MODE_PV_SURPLUS in b.modes and solar_surplus_w >= eff_threshold:
            tag = " [post-saldering]" if b.post_saldering_mode and solar_surplus_w < surplus_threshold_w else ""
            want_on = True; reason = f"PV surplus {solar_surplus_w:.0f}W{tag}"

        if not want_on and MODE_EXPORT_REDUCE in b.modes:
            pc = phase_currents.get(b.phase, 0.0)
            if pc < -export_threshold_a:
                want_on = True; reason = f"Export afschaven: {b.phase} {abs(pc):.2f}A"
        if not want_on and MODE_HEAT_DEMAND in b.modes and b.outside_temp_c is not None:
            if b.outside_temp_c < b.heat_demand_temp_c:
                if price_info.get("current", 0.5) < price_info.get("avg_today", 0.5) * 1.5 or solar_surplus_w > 200:
                    want_on = True; reason = f"Warmtevraag: {b.outside_temp_c:.1f}°C"
        if MODE_CONGESTION_OFF in b.modes and b.congestion_active:
            want_on = False; reason = "Netcongestie — uitgesteld"
        if b.current_temp_c is not None and b.current_temp_c >= SAFETY_MAX_C:
            want_on = False; reason = f"Veiligheidslimiet {b.current_temp_c:.1f}°C"

        action = self._apply_timers(b, want_on, is_on, now, reason)
        if action == "turn_on":
            await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
        if action == "turn_off":
            await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
        return BoilerDecision(entity_id=b.entity_id, label=b.label,
                              action=action, reason=reason, current_state=is_on)

    # ── Cascade evaluatie ─────────────────────────────────────────────────────

    async def _evaluate_group(self, group, price_info, solar_surplus_w, surplus_threshold_w):
        mode = group.mode
        if mode == CASCADE_AUTO:
            if price_info.get("is_negative") or solar_surplus_w >= group.total_power_w * 0.8:
                mode = CASCADE_PARALLEL
            elif price_info.get("in_cheapest_3h") or solar_surplus_w >= surplus_threshold_w:
                mode = CASCADE_SEQUENTIAL
            elif self._should_preheat_group(group):
                mode = CASCADE_SEQUENTIAL
            else:
                mode = CASCADE_STANDBY

        if mode == CASCADE_SEQUENTIAL: return await self._group_sequential(group, solar_surplus_w)
        if mode == CASCADE_PARALLEL:   return await self._group_parallel(group, solar_surplus_w)
        if mode == CASCADE_PRIORITY:   return await self._group_priority(group, solar_surplus_w)
        return self._group_standby(group)

    def _should_preheat_group(self, group: CascadeGroup) -> bool:
        if not group.learner:
            return False
        now_dt   = datetime.now()
        hour_now = now_dt.hour
        for b in group.boilers:
            if not b.needs_heat:
                continue
            mts = b.minutes_to_setpoint
            if group.learner.should_preheat(hour_now, mts):
                _LOGGER.debug("BoilerController [%s]: preventief opwarmen geactiveerd (dag-%d patroon)",
                              group.id, now_dt.weekday())
                return True
            # Optimal start: check of we nu moeten beginnen voor het volgende piekuur
            if mts and mts > 0:
                wait_min = group.learner.optimal_start_before_minutes(hour_now, mts)
                if wait_min <= 5:  # binnen 5 minuten van ideale starttijd
                    _LOGGER.debug("BoilerController [%s]: optimal start geactiveerd (wacht %.0f min)",
                                  group.id, wait_min)
                    return True
        return False

    async def _group_sequential(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        order = group.get_sequential_order()
        decisions = []

        delivery_eid = group.learner.get_delivery_entity(group.boilers) if group.learner else None
        for b in order:
            b.is_delivery = (b.entity_id == delivery_eid) if delivery_eid else (b is order[0])

        if group.learner:
            group.learner.record_cycle_start(group.boilers)
            group.learner.update_cycle_kwh(group.boilers)

        active = None
        for b in order:
            is_on = self._is_on(b.entity_id, b)

            # Netcongestie: leveringsboiler wel, buffers niet
            if b.congestion_active and not b.is_delivery:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Netcongestie — buffer uitgesteld", is_on, group.id, 0.0))
                continue

            if b.current_temp_c is not None and b.current_temp_c >= SAFETY_MAX_C:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label, "turn_off",
                    f"Veiligheidslimiet {b.current_temp_c:.1f}°C", is_on, group.id))
                continue

            if not b.needs_heat:
                if not is_on and group.learner:
                    group.learner.update_thermal_loss(b)
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                if b.current_temp_c is not None:
                    t = f"{b.current_temp_c:.1f}°C"
                    reden = f"Op setpoint ({t})"
                else:
                    reden = "Op setpoint (geen temp.sensor)"
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", reden, is_on, group.id, 0.0))
                continue

            if active is None:
                tag    = " [geleerd]" if delivery_eid else " [standaard]"
                suffix = f" [levering{tag}]" if b.is_delivery else ""
                reason = f"seq{suffix}: {b.temp_deficit_c:.1f}°C onder setpoint"
                action = self._apply_timers(b, True, is_on, now, reason)
                if action == "turn_on":
                    await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, 100.0))
                active = b
            else:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label, "hold_off",
                    f"seq: wacht op {active.label}", is_on, group.id, 0.0))

        return decisions

    async def _group_parallel(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        decisions = []
        needs = [b for b in group.boilers if b.needs_heat and (b.current_temp_c is None or b.current_temp_c < SAFETY_MAX_C)]
        if not needs:
            return self._group_standby(group)
        total = sum(b.temp_deficit_c for b in needs) or 1.0
        slot  = 0
        for b in group.boilers:
            is_on = self._is_on(b.entity_id, b)
            if b not in needs:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Op setpoint", is_on, group.id, 0.0))
                continue
            if not is_on and b.stagger_ticks <= 0:
                b.stagger_ticks = slot * int(group.stagger_delay_s); slot += 1
            if b.stagger_ticks > 0:
                b.stagger_ticks -= 1
                decisions.append(BoilerDecision(b.entity_id, b.label, "hold_off",
                    f"parallel: stagger {b.stagger_ticks}s", is_on, group.id, 0.0))
                continue
            pct    = round(b.temp_deficit_c / total * 100, 1)
            reason = f"parallel: {pct:.0f}% (tekort {b.temp_deficit_c:.1f}°C)"
            action = self._apply_timers(b, True, is_on, now, reason)
            if action == "turn_on":
                await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
            decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, pct))
        return decisions

    async def _group_priority(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        decisions = []
        candidates = sorted(
            [b for b in group.boilers if b.needs_heat and (b.current_temp_c is None or b.current_temp_c < SAFETY_MAX_C)],
            key=lambda b: (b.priority, -b.temp_deficit_c))
        for b in group.boilers:
            is_on = self._is_on(b.entity_id, b)
            if b not in candidates:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Op setpoint", is_on, group.id, 0.0))
                continue
            reason = f"prio={b.priority}, tekort {b.temp_deficit_c:.1f}°C"
            action = self._apply_timers(b, True, is_on, now, reason)
            if action == "turn_on":
                await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
            decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, 100.0))
        await self._async_save_power()
        return decisions

    def _group_standby(self, group: CascadeGroup) -> list[BoilerDecision]:
        return [BoilerDecision(b.entity_id, b.label, "hold_off", "Standby — geen trigger",
                               self._is_on(b.entity_id, b), group.id, 0.0) for b in group.boilers]

    # ── Sensoren lezen ────────────────────────────────────────────────────────

    async def _read_sensors(self) -> None:
        now = time.time()
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            if b.temp_sensor:
                s = self._hass.states.get(b.temp_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        b.current_temp_c = float(s.state)
                    except (ValueError, TypeError):
                        pass

            if b.energy_sensor:
                s = self._hass.states.get(b.energy_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        val  = float(s.state)
                        unit = (s.attributes.get("unit_of_measurement") or "").lower()
                        prev_ts = b._energy_ts_last
                        if "kwh" in unit:
                            prev = b._energy_kwh_last
                            b._energy_kwh_last = val
                            if prev is not None and val >= prev and prev_ts is not None:
                                delta = val - prev
                                dt_h  = (now - prev_ts) / 3600
                                b.cycle_kwh += delta
                                measured_w = (delta / dt_h * 1000) if dt_h > 0 else 0
                                if measured_w > 50:
                                    # Leer het vermogen als exponentieel voortschrijdend gemiddelde
                                    b.power_w = round(b.power_w * 0.85 + measured_w * 0.15, 0)
                                    self._power_dirty = True
                                b.current_power_w = measured_w
                        else:
                            b.current_power_w = val
                            if val > 50:
                                b.power_w = round(b.power_w * 0.85 + val * 0.15, 0)
                            if prev_ts is not None:
                                b.cycle_kwh += val * ((now - prev_ts) / 3_600_000)
                        b._energy_ts_last = now
                    except (ValueError, TypeError):
                        pass
            else:
                # Geen energiesensor: gebruik huidige schakelaarstatus als schatting
                # current_power_w = power_w als aan, 0 als uit (voor dashboardweergave)
                is_currently_on = self._is_on(b.entity_id, b)
                b.current_power_w = b.power_w if is_currently_on else 0.0

            if b.flow_sensor:
                s = self._hass.states.get(b.flow_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        flow_active = s.state in ("on", "true", "1") or float(s.state) > 0.5
                        if flow_active:
                            b.last_demand_ts = now
                            for g in self._groups:
                                if b in g.boilers and g.learner:
                                    g.learner.record_demand(datetime.now().hour)
                    except (ValueError, TypeError):
                        pass

    # ── Timers ────────────────────────────────────────────────────────────────

    def _apply_timers(self, b, want_on, is_on, now, reason):
        if want_on  and not is_on: return "turn_on"  if now - b.last_off_ts >= b.min_off_s else "hold_off"
        if want_on  and is_on:     return "hold_on"
        if not want_on and is_on:  return "turn_off" if now - b.last_on_ts  >= b.min_on_s  else "hold_on"
        return "hold_off"

    # ── Is-on detectie ────────────────────────────────────────────────────────

    def _is_on(self, entity_id: str, boiler: Optional[BoilerState] = None) -> bool:
        s = self._hass.states.get(entity_id)
        if s is None:
            return False
        domain = entity_id.split(".")[0]
        ctrl   = boiler.control_mode if boiler else "switch"

        if ctrl == "preset":
            preset_on = boiler.preset_on if boiler else "boost"
            return s.attributes.get("preset_mode", s.state) == preset_on

        if ctrl == "dimmer":
            off_pct = boiler.dimmer_off_pct if boiler else 0.0
            if domain == "light":
                bri_pct = s.attributes.get("brightness_pct")
                if bri_pct is None:
                    bri_pct = round(s.attributes.get("brightness", 0) / 2.55)
                return float(bri_pct) > (off_pct + 2.0)
            try:
                return float(s.state) > (off_pct + 2.0)
            except (ValueError, TypeError):
                return False

        if ctrl in ("setpoint", "setpoint_boost"):
            if domain in ("climate", "water_heater"):
                return s.state not in ("off", "unavailable", "unknown")
            return s.state == "on"

        return s.state == "on"

    # ── Schakelaar / dimmer ───────────────────────────────────────────────────

    async def _switch_smart(self, entity_id: str, on: bool,
                             boiler: Optional[BoilerState] = None,
                             solar_surplus_w: float = 0.0) -> None:
        if on and boiler and boiler.control_mode == "dimmer" and boiler.dimmer_proportional:
            await self._switch_dimmer_prop(entity_id, boiler, solar_surplus_w)
            return
        await self._switch(entity_id, on, boiler)

    async def _switch_dimmer_prop(self, entity_id: str, boiler: BoilerState,
                                   solar_surplus_w: float) -> None:
        now = time.time()
        if now - boiler._dimmer_last_ts < DIMMER_UPDATE_S:
            return
        domain  = entity_id.split(".")[0]
        raw_pct = (solar_surplus_w / boiler.power_w * 100.0) if solar_surplus_w > 0 else DIMMER_MIN_PCT
        pct     = max(DIMMER_MIN_PCT, min(boiler.dimmer_on_pct, raw_pct))
        pct     = round(pct / 5) * 5
        if abs(pct - boiler._dimmer_last_pct) < 5.0:
            return
        boiler._dimmer_last_pct = pct
        boiler._dimmer_last_ts  = now
        if domain == "light":
            await self._hass.services.async_call("light", "turn_on",
                {"entity_id": entity_id, "brightness_pct": round(pct)}, blocking=False)
        else:
            await self._hass.services.async_call("number", "set_value",
                {"entity_id": entity_id, "value": pct}, blocking=False)
        _LOGGER.debug("Dimmer prop %s → %.0f%% (surplus %.0fW)", entity_id, pct, solar_surplus_w)

    async def _switch(self, entity_id: str, on: bool,
                      boiler: Optional[BoilerState] = None) -> None:
        domain = entity_id.split(".")[0] if "." in entity_id else "switch"
        ctrl   = boiler.control_mode if boiler else "switch"

        if ctrl == "preset" and domain == "climate":
            preset = (boiler.preset_on if on else boiler.preset_off) if boiler else ("boost" if on else "green")
            await self._hass.services.async_call("climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": preset}, blocking=False)
            return

        if ctrl in ("setpoint", "setpoint_boost"):
            sp = ((boiler.active_setpoint_c or boiler.setpoint_c) if on else boiler.min_temp_c) if boiler else (60.0 if on else 40.0)
            svc_domain = domain if domain in ("climate", "water_heater") else None
            if svc_domain:
                # water_heater.set_temperature bestaat alleen als de water_heater-platform
                # geladen is. Bij ontbrekende service terugvallen op turn_on/off zodat de
                # coordinator niet crasht.
                if self._hass.services.has_service(svc_domain, "set_temperature"):
                    await self._hass.services.async_call(svc_domain, "set_temperature",
                        {"entity_id": entity_id, "temperature": sp}, blocking=False)
                else:
                    _LOGGER.warning(
                        "BoilerController [%s]: service %s.set_temperature niet beschikbaar "
                        "— teruggevallen op turn_%s. Controleer of de %s-integratie actief is.",
                        boiler.label if boiler else entity_id, svc_domain,
                        "on" if on else "off", svc_domain,
                    )
                    fallback_svc = "turn_on" if on else "turn_off"
                    if self._hass.services.has_service(svc_domain, fallback_svc):
                        await self._hass.services.async_call(
                            svc_domain, fallback_svc, {"entity_id": entity_id}, blocking=False
                        )
                # setpoint_boost: bij surplus ook preset op boost zetten voor maximale opwarming
                if ctrl == "setpoint_boost" and on and domain == "climate":
                    surplus_sp = boiler.surplus_setpoint_c if boiler else 75.0
                    _is_surplus = (boiler.active_setpoint_c or 0) > (boiler.setpoint_c or 0) if boiler else False
                    if _is_surplus:
                        await self._hass.services.async_call("climate", "set_preset_mode",
                            {"entity_id": entity_id,
                             "preset_mode": boiler.preset_on if boiler else "boost"},
                            blocking=False)
                        _LOGGER.debug("BoilerController [%s]: setpoint_boost → preset=%s + %.0f°C",
                                      boiler.label if boiler else entity_id,
                                      boiler.preset_on if boiler else "boost", surplus_sp)
                    else:
                        # Normaal gebruik: preset terug naar off/green
                        await self._hass.services.async_call("climate", "set_preset_mode",
                            {"entity_id": entity_id,
                             "preset_mode": boiler.preset_off if boiler else "green"},
                            blocking=False)
                return

        if ctrl == "dimmer":
            pct = (boiler.dimmer_on_pct if on else boiler.dimmer_off_pct) if boiler else (100.0 if on else 0.0)
            if domain == "light":
                if pct <= 0:
                    await self._hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=False)
                else:
                    await self._hass.services.async_call("light", "turn_on",
                        {"entity_id": entity_id, "brightness_pct": round(pct)}, blocking=False)
            else:
                await self._hass.services.async_call("number", "set_value",
                    {"entity_id": entity_id, "value": pct}, blocking=False)
            return

        await self._hass.services.async_call(domain, "turn_on" if on else "turn_off",
            {"entity_id": entity_id}, blocking=False)

    # ── Externe updates ───────────────────────────────────────────────────────

    def update_outside_temp(self, temp_c: Optional[float]) -> None:
        for b in self._boilers: b.outside_temp_c = temp_c
        for g in self._groups:
            for b in g.boilers: b.outside_temp_c = temp_c

    def update_congestion_state(self, active: bool) -> None:
        for b in self._boilers: b.congestion_active = active
        for g in self._groups:
            for b in g.boilers: b.congestion_active = active

    def update_power_from_nilm(self, nilm_devices: list[dict]) -> None:
        """Leer boilervermogen uit NILM-metingen (wordt aangeroepen vanuit coordinator)."""
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            if b.energy_sensor:
                continue  # Energiesensor heeft prioriteit boven NILM
            eid = b.entity_id
            # Zoek dit apparaat op in de NILM-lijst op entity_id of naam
            for dev in nilm_devices:
                dev_eid = dev.get("source_entity_id", "") or dev.get("entity_id", "")
                dev_name = (dev.get("name") or dev.get("label") or "").lower()
                b_name = b.label.lower()
                if (dev_eid and dev_eid == eid) or (b_name and b_name in dev_name) or (dev_name and dev_name in b_name):
                    power_w = float(dev.get("current_power") or dev.get("power_w") or 0)
                    if power_w > 50 and dev.get("is_on"):
                        # EMA-update van geleerd vermogen via NILM
                        b.power_w = round(b.power_w * 0.90 + power_w * 0.10, 0)
                        b.current_power_w = power_w
                        self._power_dirty = True
                        _LOGGER.debug(
                            "BoilerController [%s]: vermogen geleerd via NILM: %.0fW (EMA→%.0fW)",
                            b.label, power_w, b.power_w
                        )
                    break

    def async_p1_update(self, net_power_w: float) -> None:
        """
        Directe P1-telegramupdate (< 1s responstijd).
        net_power_w: positief = verbruik van net, negatief = teruglevering.
        Bij teruglevering wordt surplus gebruikt voor boiler-sturing bij volgende evaluatie.
        """
        surplus = max(0.0, -net_power_w)
        if surplus > 100:
            self._p1_surplus_w = surplus
            self._p1_last_ts   = time.time()
            _LOGGER.debug("P1 update: teruglevering %.0fW → boiler surplus bijgewerkt", surplus)

    # ── Status output ─────────────────────────────────────────────────────────

    def get_status(self) -> list[dict]:
        return [
            {"entity_id": b.entity_id, "label": b.label,
             "is_on": self._is_on(b.entity_id, b),
             "temp_c": b.current_temp_c, "setpoint_c": b.active_setpoint_c or b.setpoint_c,
             "power_w": b.current_power_w, "cycle_kwh": round(b.cycle_kwh, 3),
             "thermal_loss_c_h": b.thermal_loss_c_h, "control_mode": b.control_mode,
             "post_saldering_mode": b.post_saldering_mode, "delta_t_optimize": b.delta_t_optimize}
            for b in self._boilers
        ]

    def get_groups_status(self) -> list[dict]:
        hour_now = datetime.now().hour
        return [
            {"id": g.id, "name": g.name, "mode": g.mode,
             "avg_temp_c": g.avg_temp_c, "total_power_w": g.total_power_w,
             "boiler_count": len(g.boilers),
             "active_count": sum(1 for b in g.boilers if self._is_on(b.entity_id, b)),
             "delivery_entity":  (g.learner.get_delivery_entity(g.boilers) if g.learner else None),
             "delivery_learned": bool(g.learner and g.learner.get_delivery_entity(g.boilers)),
             "season":           (g.learner.get_season() if g.learner else "unknown"),
             "learn_status":     (g.learner.get_learn_status(g.boilers) if g.learner else {}),
             "boilers": [
                 {"label": b.label, "entity_id": b.entity_id,
                  "is_on": self._is_on(b.entity_id, b),
                  "temp_c": b.current_temp_c, "setpoint_c": b.active_setpoint_c or b.setpoint_c,
                  "is_delivery": b.is_delivery, "priority": b.priority,
                  "control_mode": b.control_mode, "power_w": b.current_power_w,
                  "cycle_kwh": round(b.cycle_kwh, 3),
                  "thermal_loss_c_h": b.thermal_loss_c_h,
                  "minutes_to_cold": g.learner.time_until_cold(b) if g.learner else None,
                  "post_saldering_mode": b.post_saldering_mode,
                  "delta_t_optimize": b.delta_t_optimize,
                  "optimal_start_min": (
                      g.learner.optimal_start_before_minutes(hour_now, b.minutes_to_setpoint or 0)
                      if g.learner and b.minutes_to_setpoint else None),
                  "minutes_to_setpoint": b.minutes_to_setpoint}
                 for b in g.boilers
             ]}
            for g in self._groups
        ]

    def get_full_status(self) -> dict:
        """Gecombineerde status inclusief weekly budget en P1-direct state."""
        return {
            "boilers":        self.get_status(),
            "groups":         self.get_groups_status(),
            "weekly_budget":  self.get_weekly_budget(),
            "p1_surplus_w":   round(self._p1_surplus_w, 1),
            "p1_active":      (time.time() - self._p1_last_ts) < 90 and self._p1_surplus_w > 0,
        }

    def reset_delivery_learning(self, group_id: Optional[str] = None) -> None:
        for g in self._groups:
            if g.learner and (group_id is None or g.id == group_id):
                g.learner.reset()
        _LOGGER.info("BoilerLearner: leerdata gewist voor %s", group_id or "alle groepen")
