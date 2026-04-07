# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS / AdaptiveHome (https://cloudems.eu)
"""
CloudEMS — Circuit Breaker Panel (Groepenkast)

Digitale twin van de fysieke groepenkast met volledige hiërarchie.

Ondersteunde topologieën:
  Hoofd → Aardlek → Automaten          (modern)
  Hoofd → Aardlekautomaat (RCBO)       (elk circuit eigen beveiliging)
  Hoofd → Automaten (geen aardlek)     (oud, veel in NL)
  Hoofd → Aardlek → Tussenmeter → ...  (bijgebouw, garage, etc.)
  Combinaties                          (gemengd)

Tussenmeter (SubMeter):
  Meetpunt met voltage + current sensing.
  Leert kabelweerstand uit spanningsval bij hoge belasting:
    R = ΔV / I  →  schat kabeldikte via ρ_Cu = 0.0175 Ω·mm²/m
  NEN1010: max 3% spanningsval (230V → min 223V)

NEN1010 toetsing:
  Rood   — overtreding (veiligheidsrisico)
  Oranje — sterke aanbeveling
  Geel   — advies (kabeldikte, comfort)
  Groen  — conform

Leerproces + kruis-validatie fasen:
  Circuit fase bevestigd  → NILM-devices die verdwijnen krijgen fase-boost
  NILM device fase zeker  → circuit dat schakelaar lost krijgt fase-bevestiging
  Meerdere devices L2     → Bayesiaans gecombineerde confidence bij schakelen
  Resultaat: virtueuze cirkel — elke meting verhoogt de volgende

Uitvalsdetectie:
  P1-fasedelta per cyclus → plotselinge daling
  → notificatie met ruimtes + waarschijnlijke oorzaak (hoogst-verbruikend device)
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger("cloudems.circuit_panel")

# ── Constanten ────────────────────────────────────────────────────────────────

MEASURE_WAIT_S          = 30   # v5.5.128: 30s — 2× DSMR P1 interval (10s) + cloud buffer
CONFIDENCE_THRESHOLD    = 0.65
DOUBLE_MEAS_THRESHOLD   = 0.40
MIN_POWER_DELTA_W       = 15
OUTAGE_MIN_POWER_W      = 50
OUTAGE_DROP_PCT         = 0.40
LIMIT_WARN_PCT          = 0.80
LIMIT_ALERT_PCT         = 0.95
STORAGE_KEY             = "cloudems_circuit_panel_v1"

RHO_CU                  = 0.0175   # Ω·mm²/m soortelijke weerstand koper
CABLE_LEARN_MIN_I       = 3.0      # minimale stroom voor betrouwbare R-meting (A)
CABLE_LEARN_MIN_DV      = 0.5      # minimale spanningsval (V)
VOLTAGE_DROP_YELLOW_PCT = 0.01
VOLTAGE_DROP_ORANGE_PCT = 0.03     # NEN1010 grens
VOLTAGE_DROP_RED_PCT    = 0.05

NEN1010_MAX_GROUPS_PER_RCD = 4  # NL standaard; wordt overschreven door country config

# Maximaal groepen per aardlek per land (gebaseerd op HD 60364 implementaties)
MAX_GROUPS_PER_COUNTRY: dict = {
    "NL": 4,   # NEN 1010 art. 531.3
    "BE": 8,   # AREI art. 86
    "DE": 6,   # DIN VDE 0100
    "FR": 8,   # NF C 15-100 art. 771
    "GB": 8,   # BS 7671
    "IE": 8,   # IS 10101
    "AT": 6,   # ÖVE/ÖNORM E 8001
    "CH": 6,   # NIV / NIN 2020
    "ES": 6,   # REBT ITC-BT
    "IT": 6,   # CEI 64-8
    "PT": 6,   # RTIEBT
    "SE": 8,   # SS-EN 60364
    "NO": 8,   # NEK 400
    "DK": 8,   # DS Stærkstrøm
    "FI": 8,   # SFS 6000
    "LU": 8,   # NF C 15-100
    "MT": 8,   # BS 7671
    "CY": 8,   # BS 7671
}
NEN1010_LIGHT_POINT_W      = 60
NEN1010_MAX_LIGHT_POINTS   = 20
NEN1010_CABLE_ADVICE = {
    10: 1.5, 16: 2.5, 20: 2.5, 25: 4.0, 32: 6.0, 40: 10.0, 63: 16.0,
}

DEVICE_KW_EV      = {"ev", "laad", "charger", "wallbox", "laadpaal"}
DEVICE_KW_PV      = {"solar", "pv", "omvormer", "inverter", "zon"}
DEVICE_KW_WASHING = {"wasmachine", "washer", "washing", "droger", "dryer",
                     "vaatwasser", "dishwasher"}
DEVICE_KW_COOKING = {"kookplaat", "oven", "magnetron", "cooker", "induction"}
DEVICE_KW_BATH    = {"badkamer", "bathroom", "douche", "shower", "toilet"}
DEVICE_KW_OUTSIDE = {"tuin", "garden", "buiten", "outdoor", "garage", "schuur"}


class NodeType:
    MAIN     = "main"
    RCD      = "rcd"
    RCBO     = "rcbo"
    MCB      = "mcb"
    MCB3F    = "mcb_3f"
    SUBMETER = "submeter"


class RCDType:
    TYPE_A  = "type_a"
    TYPE_B  = "type_b"
    TYPE_F  = "type_f"
    UNKNOWN = "unknown"


class LearningState:
    IDLE        = "idle"
    WAITING_OFF = "waiting_off"
    MEASURING   = "measuring"
    WAITING_ON  = "waiting_on"
    CONFIRMING  = "confirming"
    DONE        = "done"


class NEN1010Severity:
    RED    = "red"
    ORANGE = "orange"
    YELLOW = "yellow"
    GREEN  = "green"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class NEN1010Finding:
    severity: str
    code:     str
    message:  str
    detail:   str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PhaseBoost:
    """
    Kruis-validatie resultaat: een node of NILM-device krijgt fase-boost.
    Coordinator stuurt dit door naar NILM-module.
    """
    target_id:    str    # node_id of NILM device_id
    target_type:  str    # "circuit" of "nilm_device"
    phase:        str    # L1 / L2 / L3
    confidence:   float  # nieuwe confidence
    source:       str    # wat de boost gaf ("circuit_learning" / "nilm_cross")
    bayesian_n:   int = 1  # aantal devices/circuits dat bijdroeg


@dataclass
class CircuitBreaker:
    id              : str
    name            : str
    node_type       : str   = NodeType.MCB
    ampere          : int   = 16
    phase           : str   = ""
    phase_confidence: float = 0.0
    parent_id       : str   = ""
    position        : int   = 0
    switch_entity   : str   = ""
    energy_entity   : str   = ""   # optioneel: HA kWh-sensor (echte meter)
    rcd_type        : str   = RCDType.UNKNOWN
    kar             : str   = "B"    # B / C / D karakteristiek
    ma              : int   = 30    # gevoeligheid in mA (aardlekken)
    card_type       : str   = ""    # v5.5.129: exacte kaarttype (main_4p, rcd_4p_b etc.)
    parent_main_id  : str   = ""    # v5.5.153: parent hoofdschakelaar (serie-schakeling)
    rail_index      : int   = 0     # v5.5.153: rail-nummer voor multi-rail herstel
    linked_devices  : List[str] = field(default_factory=list)
    linked_rooms    : List[str] = field(default_factory=list)
    linked_power_w  : float = 0.0
    confidence      : float = 0.0
    measurement_count: int  = 0
    last_learned    : Optional[float] = None
    notes           : str   = ""
    current_power_w : float = field(default=0.0, repr=False)

    @property
    def is_rcd_family(self) -> bool:
        return self.node_type in (NodeType.RCD, NodeType.RCBO, NodeType.MAIN)

    @property
    def has_rcd_protection(self) -> bool:
        return self.node_type in (NodeType.RCD, NodeType.RCBO)

    @property
    def has_overload_protection(self) -> bool:
        return self.node_type in (NodeType.RCBO, NodeType.MCB, NodeType.MCB3F, NodeType.MAIN)

    @property
    def is_3phase(self) -> bool:
        return self.node_type == NodeType.MCB3F or self.phase == "3F"

    @property
    def rated_power_w(self) -> float:
        return self.ampere * 230.0 * (3 if self.is_3phase else 1)

    @property
    def load_pct(self) -> float:
        return min(1.0, self.current_power_w / self.rated_power_w) if self.rated_power_w > 0 else 0.0

    @property
    def cable_advice_mm2(self) -> Optional[float]:
        return NEN1010_CABLE_ADVICE.get(self.ampere)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("current_power_w", None)
        return d

    @property
    def has_physical_meter(self) -> bool:
        return bool(self.meter_entity)

    @classmethod
    def from_dict(cls, d: dict) -> "CircuitBreaker":
        valid = set(cls.__dataclass_fields__) - {"current_power_w"}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class SubMeter:
    id               : str
    name             : str
    node_type        : str   = NodeType.SUBMETER
    parent_id        : str   = ""
    position         : int   = 0
    voltage_entity   : str   = ""
    current_entity   : str   = ""
    power_entity     : str   = ""
    energy_entity    : str   = ""   # optioneel: HA kWh-sensor (echte meter)
    switch_entity    : str   = ""
    cable_length_m   : float = 0.0
    r_cable_ohm      : Optional[float] = None
    r_samples        : int   = 0
    estimated_mm2    : Optional[float] = None
    voltage_drop_pct : Optional[float] = None
    linked_devices   : List[str] = field(default_factory=list)
    linked_rooms     : List[str] = field(default_factory=list)
    confidence       : float = 0.0
    measurement_count: int   = 0
    last_learned     : Optional[float] = None
    notes            : str   = ""
    current_voltage_v: float = field(default=0.0, repr=False)
    current_power_w  : float = field(default=0.0, repr=False)
    current_current_a: float = field(default=0.0, repr=False)

    @property
    def is_rcd_family(self) -> bool:
        return False

    @property
    def has_rcd_protection(self) -> bool:
        return False

    @property
    def rated_power_w(self) -> float:
        return 0.0

    @property
    def load_pct(self) -> float:
        return 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("current_voltage_v", "current_power_w", "current_current_a"):
            d.pop(k, None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SubMeter":
        skip = {"current_voltage_v", "current_power_w", "current_current_a"}
        valid = set(cls.__dataclass_fields__) - skip
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class LearningSession:
    node_id           : str
    node_type         : str   = NodeType.MCB
    state             : str   = LearningState.IDLE
    snapshot_before   : Dict[str, float] = field(default_factory=dict)
    phase_w_before    : Dict[str, float] = field(default_factory=dict)
    submeter_v_before : Dict[str, float] = field(default_factory=dict)
    snapshot_after    : Dict[str, float] = field(default_factory=dict)
    phase_w_after     : Dict[str, float] = field(default_factory=dict)
    submeter_v_after  : Dict[str, float] = field(default_factory=dict)
    nilm_phases_before: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    started_at        : float = 0.0
    measurement_num   : int   = 1
    candidates        : List[dict] = field(default_factory=list)
    detected_phase    : str   = ""
    phase_confidence  : float = 0.0


# ── Hoofdklasse ───────────────────────────────────────────────────────────────

CircuitNode = CircuitBreaker  # type alias (SubMeter ook geldig)


class CircuitBreakerPanel:
    """
    Digitale twin van de groepenkast.

    Coördinator-integratie:
        panel = CircuitBreakerPanel(store, hass)
        await panel.async_load()

        # Elke cyclus:
        nilm_snap     = {d["id"]: float(d.get("current_power_w", 0)) for d in nilm_devices}
        nilm_phases   = {d["id"]: (d.get("phase",""), float(d.get("phase_confidence",0)))
                         for d in nilm_devices}
        phase_w_snap  = {"L1": p1_l1_w, "L2": p1_l2_w, "L3": p1_l3_w}
        phase_v_snap  = {"L1": v_l1, "L2": v_l2, "L3": v_l3}
        submeter_snap = panel.read_submeters(hass)

        notifications, phase_boosts = panel.tick(
            nilm_snap, nilm_phases, phase_w_snap, phase_v_snap,
            submeter_snap, nilm_devices
        )
        # phase_boosts → doorsturen naar NILM-module voor fase-confidence update
    """

    def __init__(self, store, hass=None) -> None:
        self._store    = store
        self._hass     = hass
        self._breakers : Dict[str, CircuitBreaker] = {}
        self._submeters: Dict[str, SubMeter]       = {}
        self._session  : Optional[LearningSession] = None
        self._prev_phase_w: Dict[str, float] = {}
        self._prev_phase_v: Dict[str, float] = {}
        self._loaded   = False
        self._hierarchy_learner  = HierarchyLearner()
        self._group_meter        = GroupMeter()
        self._current_price      = 0.25
        self._simultaneity       = SimultaneityTracker()
        self._anomaly_detector   = AnomalyDetector()
        self._meter_readings: Dict[str, dict] = {}

    # ── Persistentie ──────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            self._loaded = True
            return
        for d in data.get("breakers", []):
            try:
                b = CircuitBreaker.from_dict(d)
                self._breakers[b.id] = b
            except Exception as err:
                _LOGGER.warning("Groep laden: %s — %s", d.get("id"), err)
        for d in data.get("submeters", []):
            try:
                s = SubMeter.from_dict(d)
                self._submeters[s.id] = s
            except Exception as err:
                _LOGGER.warning("Tussenmeter laden: %s — %s", d.get("id"), err)
        if "hierarchy" in (data or {}):
            self._hierarchy_learner = HierarchyLearner.from_dict(data["hierarchy"])
        if "simultaneity" in (data or {}):
            self._simultaneity = SimultaneityTracker.from_dict(data["simultaneity"])
        if "anomaly" in (data or {}):
            self._anomaly_detector = AnomalyDetector.from_dict(data["anomaly"])
        self._loaded = True
        # Laad sub-modules
        for key, cls_from, attr in [
            ("hierarchy_learner", HierarchyLearner,      "_hierarchy_learner"),
            ("group_meter",       GroupMeter,             "_group_meter"),
            ("simultaneity",      SimultaneityTracker,    "_simultaneity"),
            ("anomaly_detector",  AnomalyDetector,        "_anomaly_detector"),
        ]:
            raw = data.get(key) if data else None
            if raw:
                try:
                    setattr(self, attr, cls_from.from_dict(raw))
                except Exception as err:
                    _LOGGER.debug("%s laden mislukt: %s", key, err)
        _LOGGER.debug("Groepenkast: %d groepen, %d tussenmeters",
                      len(self._breakers), len(self._submeters))

    async def async_save(self) -> None:
        await self._store.async_save({
            "breakers":    [b.to_dict() for b in self._breakers.values()],
            "submeters":   [s.to_dict() for s in self._submeters.values()],
            "hierarchy":   self._hierarchy_learner.to_dict(),
            "simultaneity": self._simultaneity.to_dict(),
            "anomaly":     self._anomaly_detector.to_dict(),
            "version":     3,
        })

    # ── Boom navigatie ────────────────────────────────────────────────────────

    def _all_nodes(self) -> Dict[str, object]:
        return {**self._breakers, **self._submeters}

    def get_all_sorted(self) -> list:
        return sorted(self._all_nodes().values(), key=lambda n: n.position)

    def get_node(self, node_id: str):
        return self._breakers.get(node_id) or self._submeters.get(node_id)

    def get_children(self, parent_id: str) -> list:
        return [n for n in self.get_all_sorted() if n.parent_id == parent_id]

    def get_roots(self) -> list:
        ids = set(self._all_nodes().keys())
        return [n for n in self.get_all_sorted()
                if not n.parent_id or n.parent_id not in ids]

    def get_ancestors(self, node_id: str) -> list:
        result, visited = [], set()
        current_id = self.get_node(node_id)
        current_id = current_id.parent_id if current_id else ""
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = self.get_node(current_id)
            if node is None:
                break
            result.append(node)
            current_id = node.parent_id
        return result

    def get_all_leaves(self, parent_id: str) -> List[CircuitBreaker]:
        result = []
        for child in self.get_children(parent_id):
            if isinstance(child, CircuitBreaker) and not child.is_rcd_family:
                result.append(child)
            else:
                result.extend(self.get_all_leaves(child.id))
        return result

    def node_is_protected_by_rcd(self, node_id: str) -> bool:
        return any(isinstance(a, CircuitBreaker) and a.has_rcd_protection
                   for a in self.get_ancestors(node_id))

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_breaker(self, b: CircuitBreaker) -> None:
        self._breakers[b.id] = b

    def add_submeter(self, s: SubMeter) -> None:
        self._submeters[s.id] = s

    def remove_node(self, node_id: str) -> None:
        for child in self.get_children(node_id):
            self.remove_node(child.id)
        self._breakers.pop(node_id, None)
        self._submeters.pop(node_id, None)

    def update_node(self, node_id: str, **kwargs) -> bool:
        node = self.get_node(node_id)
        if node is None:
            return False
        for k, v in kwargs.items():
            if hasattr(node, k):
                setattr(node, k, v)
        return True

    def set_device_link(self, node_id: str, device_id: str, linked: bool) -> None:
        node = self.get_node(node_id)
        if node is None:
            return
        if linked and device_id not in node.linked_devices:
            node.linked_devices.append(device_id)
        elif not linked and device_id in node.linked_devices:
            node.linked_devices.remove(device_id)

    def set_room_link(self, node_id: str, room: str, linked: bool) -> None:
        node = self.get_node(node_id)
        if node is None:
            return
        if linked and room not in node.linked_rooms:
            node.linked_rooms.append(room)
        elif not linked and room in node.linked_rooms:
            node.linked_rooms.remove(room)

    # ── Submeters uitlezen ────────────────────────────────────────────────────

    def read_submeters(self, hass) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        if hass is None:
            return result
        for sm_id, sm in self._submeters.items():
            v = i = p = 0.0
            for entity, attr in ((sm.voltage_entity, "v"), (sm.current_entity, "i"),
                                  (sm.power_entity, "p")):
                if not entity:
                    continue
                try:
                    state = hass.states.get(entity)
                    if state and state.state not in ("unavailable", "unknown"):
                        val = float(state.state)
                        if attr == "v":
                            v = val
                        elif attr == "i":
                            i = val
                        else:
                            p = val
                except (ValueError, TypeError):
                    pass
            if v > 0 and i == 0 and p > 0:
                i = p / v
            elif v > 0 and p == 0 and i > 0:
                p = v * i
            sm.current_voltage_v  = v
            sm.current_current_a  = i
            sm.current_power_w    = p
            result[sm_id] = {"voltage_v": v, "current_a": i, "power_w": p}
        return result

    # ── Coordinator tick ──────────────────────────────────────────────────────

    def tick(
        self,
        nilm_snapshot : Dict[str, float],
        nilm_phases   : Dict[str, Tuple[str, float]],
        phase_w_snap  : Dict[str, float],
        phase_v_snap  : Dict[str, float],
        submeter_snap : Dict[str, dict],
        nilm_devices  : List[dict],
    ) -> Tuple[List[dict], List[PhaseBoost]]:
        """
        Aanroepen elke coordinator-cyclus.
        Returns: (notifications, phase_boosts)
        phase_boosts → doorsturen naar NILM-module
        """
        notifications: List[dict]       = []
        phase_boosts : List[PhaseBoost] = []

        # ── Verbruik per circuit bijwerken ────────────────────────────────────
        device_power = {d.get("id", ""): float(d.get("current_power_w", 0) or 0)
                        for d in nilm_devices}
        for b in self._breakers.values():
            if not b.is_rcd_family:
                b.current_power_w = sum(device_power.get(dev, 0)
                                        for dev in b.linked_devices)
        for sm in self._submeters.values():
            sm.current_power_w = submeter_snap.get(sm.id, {}).get("power_w", 0.0)
        for node in self.get_all_sorted():
            if isinstance(node, CircuitBreaker) and node.is_rcd_family:
                node.current_power_w = sum(
                    c.current_power_w for c in self.get_children(node.id)
                )

        # ── Kabelweerstand leren ──────────────────────────────────────────────
        for sm_id, snap in submeter_snap.items():
            self._learn_cable_resistance(sm_id, snap, phase_v_snap)

        # ── Kruis-validatie fasen ─────────────────────────────────────────────
        phase_boosts.extend(
            self._cross_validate_phases(nilm_phases, device_power)
        )

        # ── Uitvalsdetectie ───────────────────────────────────────────────────
        if self._prev_phase_w:
            notifications.extend(
                self._detect_outages(phase_w_snap, device_power, nilm_devices)
            )

        # Passief hiërarchie leren vanuit uitvalsdetectie
        for notif in notifications:
            if notif.get("type") == "circuit_outage":
                sug = self._hierarchy_learner.record_outage(notif["node_id"], notif["ts"])
                if sug:
                    _LOGGER.debug("HierarchyLearner: %d suggesties", len(sug))
        sug_flush = self._hierarchy_learner.flush()
        if sug_flush:
            changes = self._hierarchy_learner.apply_to_panel(self)
            if changes:
                _LOGGER.info("HierarchyLearner: %d hiërarchie-wijzigingen", len(changes))

        # Gelijktijdigheidsfactor
        import datetime as _dt
        _hour = _dt.datetime.fromtimestamp(time.time()).hour

        # Anomalie-detectie
        if self._meter_readings:
            anomalies = self._anomaly_detector.tick(self._meter_readings, self, time.time())
            for a in anomalies:
                notifications.append({
                    "type":     "group_anomaly",
                    "severity": "warning",
                    "node_id":  a.node_id,
                    "node_name": a.node_name,
                    "delta_w":  a.delta_w,
                    "sigma":    a.sigma,
                    "cause":    a.likely_cause,
                    "message":  (f"Onverklaard verbruik op groep '{a.node_name}': "
                                 f"+{round(a.delta_w)}W ({a.sigma:.1f}σ) — "
                                 f"mogelijke oorzaak: {a.likely_cause}"),
                    "ts":       a.ts,
                })

        self._prev_phase_w = dict(phase_w_snap)
        self._prev_phase_v = dict(phase_v_snap)

        # ── HierarchyLearner: passief hiërarchie leren uit outages ────────────
        for notif in notifications:
            if notif.get("type") == "circuit_outage":
                node_id  = notif.get("node_id", "")
                children = self.get_all_leaves(notif.get("node_id", ""))
                # Record zowel de hoofdgroep als eventuele siblings
                related = [node_id] + [c.id for c in children if c.id != node_id]
                for rid in related:
                    suggestions = self._hierarchy_learner.record_outage(rid, time.time())
                    for a, b, conf in suggestions:
                        if self._hierarchy_learner.should_auto_link(a, b):
                            # Auto-koppelen: zoek gemeenschappelijke parent of maak nieuwe RCD
                            node_a = self.get_node(a)
                            node_b = self.get_node(b)
                            if node_a and node_b and not node_a.parent_id and not node_b.parent_id:
                                _LOGGER.info(
                                    "Hiërarchie geleerd: '%s' en '%s' zitten waarschijnlijk "
                                    "op hetzelfde aardlek (conf %.0f%%)",
                                    a, b, conf * 100,
                                )
                                notifications.append({
                                    "type":       "hierarchy_learned",
                                    "severity":   "info",
                                    "node_ids":   [a, b],
                                    "confidence": conf,
                                    "message":    (
                                        f"Groepen '{node_a.name}' en '{node_b.name}' "
                                        f"vallen altijd tegelijk uit — waarschijnlijk "
                                        f"zelfde aardlek ({round(conf*100)}% zekerheid)"
                                    ),
                                    "ts": time.time(),
                                })
        self._hierarchy_learner.flush()

        # ── GroupMeter: kWh per groep bijhouden ───────────────────────────────
        price = 0.25  # fallback; coordinator kan dit updaten via update_price()
        self._meter_readings = self._group_meter.tick(
            self.get_all_sorted(), device_power, price, time.time(), self._hass
        ) or {}

        # ── SimultaneityTracker ───────────────────────────────────────────────
        self._simultaneity.tick(self, hour_of_day=__import__('datetime').datetime.now().hour)

        # ── AnomalyDetector ───────────────────────────────────────────────────
        anomaly_alerts = self._anomaly_detector.tick(self._meter_readings, self, time.time())
        notifications.extend(anomaly_alerts)

        return notifications, phase_boosts

    # ── Kruis-validatie fasen ─────────────────────────────────────────────────

    def _cross_validate_phases(
        self,
        nilm_phases : Dict[str, Tuple[str, float]],
        device_power: Dict[str, float],
    ) -> List[PhaseBoost]:
        """
        Kruis-validatie tussen bevestigde circuit-fasen en NILM-device fasen.

        Richting 1: Circuit fase bevestigd → devices gekoppeld aan dit circuit
                    krijgen fase-boost als hun fase nog onzeker is.

        Richting 2: Meerdere NILM-devices met hoge fase-confidence op L2,
                    allemaal gekoppeld aan circuit X → circuit X krijgt L2 bevestiging
                    via Bayesiaans combineren.
        """
        boosts: List[PhaseBoost] = []

        for b in self._breakers.values():
            if b.is_rcd_family or not b.phase or b.phase_confidence < 0.70:
                continue

            # Richting 1: circuit → NILM devices
            for dev_id in b.linked_devices:
                nil_phase, nil_conf = nilm_phases.get(dev_id, ("", 0.0))
                if nil_conf >= 0.70:
                    continue  # al zeker genoeg
                # Boost: device erft circuit-fase-confidence
                new_conf = min(0.90, b.phase_confidence * 0.85)
                boosts.append(PhaseBoost(
                    target_id   = dev_id,
                    target_type = "nilm_device",
                    phase       = b.phase,
                    confidence  = new_conf,
                    source      = "circuit_learning",
                ))

        # Richting 2: NILM-devices → circuit fase (Bayesiaans)
        for b in self._breakers.values():
            if b.is_rcd_family or b.phase_confidence >= 0.85:
                continue  # al zeker

            # Verzamel fase-stemmen van gekoppelde devices met hoge confidence
            phase_evidence: Dict[str, List[float]] = {}
            for dev_id in b.linked_devices:
                nil_phase, nil_conf = nilm_phases.get(dev_id, ("", 0.0))
                if nil_conf >= 0.70 and nil_phase in ("L1", "L2", "L3"):
                    phase_evidence.setdefault(nil_phase, []).append(nil_conf)

            if not phase_evidence:
                continue

            # Bayesiaans combineren: P(L1|e1,e2,...) ∝ ∏ P(Li|ej)
            best_phase    = ""
            best_combined = 0.0
            for phase, confs in phase_evidence.items():
                # Log-som vermijdt underflow bij veel kleine kansen
                log_combined = sum(math.log(max(c, 1e-9)) for c in confs)
                combined     = math.exp(log_combined / len(confs))
                # Bonus: meer bewijs = hogere confidence
                combined     = min(0.95, combined * (1 + 0.05 * len(confs)))
                if combined > best_combined:
                    best_combined = combined
                    best_phase    = phase

            if best_phase and best_combined > (b.phase_confidence or 0.0):
                boosts.append(PhaseBoost(
                    target_id   = b.id,
                    target_type = "circuit",
                    phase       = best_phase,
                    confidence  = round(best_combined, 3),
                    source      = "nilm_cross",
                    bayesian_n  = len(phase_evidence.get(best_phase, [])),
                ))
                # Direct toepassen op het circuit
                b.phase            = best_phase
                b.phase_confidence = round(best_combined, 3)

        return boosts

    # ── Kabelweerstand leren ──────────────────────────────────────────────────

    def _learn_cable_resistance(
        self,
        sm_id       : str,
        snap        : dict,
        phase_v_snap: Dict[str, float],
    ) -> None:
        sm = self._submeters.get(sm_id)
        if sm is None:
            return
        v_sub = snap.get("voltage_v", 0.0)
        i     = snap.get("current_a", 0.0)
        if v_sub < 100 or i < CABLE_LEARN_MIN_I:
            return

        # Zoek spanning bovenliggende fase
        sm_phase = ""
        for ancestor in self.get_ancestors(sm_id):
            if isinstance(ancestor, CircuitBreaker) and ancestor.phase:
                sm_phase = ancestor.phase
                break
        if sm_phase not in ("L1", "L2", "L3"):
            return

        v_main = phase_v_snap.get(sm_phase, 0.0)
        if v_main < 100:
            return

        dv = v_main - v_sub
        if dv < CABLE_LEARN_MIN_DV:
            return

        r_meas = dv / i
        alpha  = 0.10
        sm.r_cable_ohm = (r_meas if sm.r_cable_ohm is None
                          else alpha * r_meas + (1 - alpha) * sm.r_cable_ohm)
        sm.r_samples        += 1
        sm.voltage_drop_pct  = round(dv / v_main, 4)

        if sm.cable_length_m > 0 and sm.r_cable_ohm > 0:
            # R = ρ × 2L / A  →  A = ρ × 2L / R
            sm.estimated_mm2 = round(
                (RHO_CU * 2 * sm.cable_length_m) / sm.r_cable_ohm, 2
            )

    # ── Uitvalsdetectie ───────────────────────────────────────────────────────

    def _detect_outages(
        self,
        current_phase_w : Dict[str, float],
        device_power    : Dict[str, float],
        nilm_devices    : List[dict],
    ) -> List[dict]:
        notifications: List[dict] = []
        device_map = {d.get("id", ""): d for d in nilm_devices}

        for phase, prev_w in self._prev_phase_w.items():
            curr_w = current_phase_w.get(phase, 0.0)
            drop   = prev_w - curr_w
            if prev_w < OUTAGE_MIN_POWER_W or drop < OUTAGE_MIN_POWER_W:
                continue
            if (drop / max(prev_w, 1.0)) < OUTAGE_DROP_PCT:
                continue

            candidates = [
                b for b in self._breakers.values()
                if b.phase == phase and not b.is_rcd_family and b.linked_power_w > 0
            ]
            if not candidates:
                continue

            likely = max(candidates, key=lambda b: b.linked_power_w)
            rooms  = likely.linked_rooms[:]

            rcd_name = ""
            for ancestor in self.get_ancestors(likely.id):
                if isinstance(ancestor, CircuitBreaker) and ancestor.has_rcd_protection:
                    rcd_name = ancestor.name
                    break

            cause_device = None
            cause_power  = 0.0
            for dev_id in likely.linked_devices:
                pwr = device_power.get(dev_id, 0.0)
                if pwr > cause_power:
                    cause_power  = pwr
                    cause_device = device_map.get(dev_id)

            cause_text = ""
            if cause_device and cause_power > 100:
                cn = cause_device.get("name") or cause_device.get("id", "")
                cause_text = (
                    f"controleer {cn} — "
                    f"dit lijkt de piek veroorzaakt te hebben ({round(cause_power)}W)"
                )

            rooms_label = " en ".join(rooms) if rooms else f"groep '{likely.name}'"
            msg = f"Groep '{likely.name}' uitgevallen"
            if rooms:
                heeft = "heeft" if len(rooms) == 1 else "hebben"
                msg  += f": {rooms_label} {heeft} nu geen stroom"
            if rcd_name:
                msg += f" (via aardlek '{rcd_name}')"
            if cause_text:
                msg += f", {cause_text}"

            notifications.append({
                "type":          "circuit_outage",
                "severity":      "error",
                "node_id":       likely.id,
                "node_name":     likely.name,
                "phase":         phase,
                "drop_w":        round(drop, 0),
                "rooms":         rooms,
                "rcd_name":      rcd_name,
                "cause_device":  cause_device.get("name", "") if cause_device else "",
                "cause_power_w": round(cause_power, 0),
                "message":       msg,
                "ts":            time.time(),
            })

        return notifications

    # ── Leerproces ────────────────────────────────────────────────────────────

    def start_learning(
        self,
        node_id        : str,
        nilm_snapshot  : Dict[str, float],
        phase_w_snap   : Dict[str, float],
        submeter_snap  : Dict[str, dict],
        nilm_phases    : Optional[Dict[str, Tuple[str, float]]] = None,
    ) -> dict:
        node = self.get_node(node_id)
        if node is None:
            return {"error": f"Node {node_id} niet gevonden"}

        meas_num = (2 if self._session
                    and self._session.state == LearningState.CONFIRMING else 1)

        self._session = LearningSession(
            node_id           = node_id,
            node_type         = getattr(node, "node_type", NodeType.MCB),
            state             = LearningState.WAITING_OFF,
            snapshot_before   = dict(nilm_snapshot),
            phase_w_before    = dict(phase_w_snap),
            submeter_v_before = {k: v.get("voltage_v", 0.0) for k, v in submeter_snap.items()},
            nilm_phases_before= dict(nilm_phases or {}),
            started_at        = time.time(),
            measurement_num   = meas_num,
        )

        if isinstance(node, CircuitBreaker) and node.is_rcd_family:
            instr = (f"Zet aardlek '{node.name}' UIT. "
                     f"Alle automaten eronder worden tegelijk geleerd.")
        elif isinstance(node, SubMeter):
            instr = (f"Schakel het circuit voor '{node.name}' uit. "
                     f"Spanning en kabelweerstand worden gemeten.")
        else:
            instr = f"Zet groep '{node.name}' UIT en klik 'Meting starten'."

        return {
            "state":         LearningState.WAITING_OFF,
            "node_id":       node_id,
            "node_name":     node.name,
            "measurement":   meas_num,
            "instruction":   instr,
            "auto_switch":   bool(getattr(node, "switch_entity", "")),
            "switch_entity": getattr(node, "switch_entity", ""),
        }

    def confirm_off(
        self,
        nilm_snapshot : Dict[str, float],
        phase_w_snap  : Dict[str, float],
        submeter_snap : Dict[str, dict],
    ) -> dict:
        if not self._session or self._session.state != LearningState.WAITING_OFF:
            return {"error": "Geen actieve leersessie"}
        self._session.snapshot_after   = dict(nilm_snapshot)
        self._session.phase_w_after    = dict(phase_w_snap)
        self._session.submeter_v_after = {k: v.get("voltage_v", 0.0)
                                           for k, v in submeter_snap.items()}
        self._session.state            = LearningState.MEASURING
        return {"state": LearningState.MEASURING, "wait_seconds": MEASURE_WAIT_S}

    def finish_learning(
        self,
        nilm_snapshot : Dict[str, float],
        phase_w_snap  : Dict[str, float],
        submeter_snap : Dict[str, dict],
        nilm_devices  : List[dict],
        nilm_phases   : Optional[Dict[str, Tuple[str, float]]] = None,
    ) -> dict:
        if not self._session or self._session.state != LearningState.MEASURING:
            return {"error": "Geen actieve meting"}

        s    = self._session
        node = self.get_node(s.node_id)

        # ── NILM-delta ────────────────────────────────────────────────────────
        candidates: List[dict] = []
        for dev_id, pwr_before in s.snapshot_before.items():
            pwr_after = nilm_snapshot.get(dev_id, 0.0)
            delta     = pwr_before - pwr_after
            if delta >= MIN_POWER_DELTA_W:
                rel = delta / max(pwr_before, 1.0)
                candidates.append({
                    "device_id":    dev_id,
                    "power_before": round(pwr_before, 1),
                    "power_after":  round(pwr_after, 1),
                    "delta_w":      round(delta, 1),
                    "relative":     round(rel, 2),
                })

        # ── Fase-detectie P1 ──────────────────────────────────────────────────
        detected_phase   = ""
        phase_confidence = 0.0
        if isinstance(node, CircuitBreaker) and not node.is_rcd_family:
            best_drop = 0.0
            for ph in ("L1", "L2", "L3"):
                drop = ((s.phase_w_before.get(ph, 0.0) or 0.0)
                        - (s.phase_w_after.get(ph, 0.0) or 0.0))
                if drop > best_drop:
                    best_drop      = drop
                    detected_phase = ph
            if best_drop > MIN_POWER_DELTA_W:
                total = sum(
                    max(0.0, (s.phase_w_before.get(ph, 0.0) or 0.0)
                            - (s.phase_w_after.get(ph, 0.0) or 0.0))
                    for ph in ("L1", "L2", "L3")
                )
                phase_confidence = best_drop / max(total, 1.0)

        # ── Fase-confidence boost vanuit NILM (kruis-validatie) ───────────────
        phase_boosts: List[PhaseBoost] = []
        if candidates and nilm_phases:
            phase_boosts = self._compute_learning_phase_boosts(
                candidates, nilm_phases, detected_phase, phase_confidence,
                s.node_id,
            )
            # Als NILM Bayesiaans een betere fase geeft dan P1 → gebruik die
            circuit_boost = next(
                (b for b in phase_boosts
                 if b.target_type == "circuit" and b.target_id == s.node_id), None
            )
            if circuit_boost and circuit_boost.confidence > phase_confidence:
                detected_phase   = circuit_boost.phase
                phase_confidence = circuit_boost.confidence

        # ── RCD-kinderen leren ────────────────────────────────────────────────
        rcd_children: List[str] = []
        if isinstance(node, CircuitBreaker) and node.is_rcd_family:
            for leaf in self.get_all_leaves(node.id):
                for dev_id, pwr_before in s.snapshot_before.items():
                    delta = pwr_before - nilm_snapshot.get(dev_id, 0.0)
                    if delta >= MIN_POWER_DELTA_W:
                        if dev_id not in leaf.linked_devices:
                            leaf.linked_devices.append(dev_id)
                        if leaf.id not in rcd_children:
                            rcd_children.append(leaf.id)

        # ── Confidence ────────────────────────────────────────────────────────
        if not candidates:
            confidence = 0.10 if best_drop > MIN_POWER_DELTA_W else 0.0
        else:
            avg_rel    = sum(c["relative"] for c in candidates) / len(candidates)
            fully_gone = sum(1 for c in candidates if c["relative"] > 0.90)
            confidence = min(1.0,
                             avg_rel * 0.60
                             + (fully_gone / max(len(candidates), 1)) * 0.30
                             + (0.10 if phase_confidence > 0.70 else 0.0))

        # Tweede meting: bonus voor overlap
        if s.measurement_num == 2 and isinstance(node, CircuitBreaker) and node.linked_devices:
            prev_ids = set(node.linked_devices)
            new_ids  = {c["device_id"] for c in candidates}
            if prev_ids & new_ids:
                confidence = min(1.0, confidence + 0.20)

        total_delta = sum(c["delta_w"] for c in candidates)
        s.candidates     = candidates
        s.detected_phase = detected_phase
        s.phase_confidence = phase_confidence

        if confidence >= CONFIDENCE_THRESHOLD or s.measurement_num >= 2:
            result = self._apply_learning(
                node, candidates, confidence, total_delta,
                detected_phase, phase_confidence, nilm_devices,
            )
            result["phase_boosts"] = [
                {"target_id": b.target_id, "target_type": b.target_type,
                 "phase": b.phase, "confidence": b.confidence,
                 "source": b.source, "bayesian_n": b.bayesian_n}
                for b in phase_boosts
            ]
            result["rcd_children_learned"] = rcd_children
            self._session = None
            return result

        elif confidence >= DOUBLE_MEAS_THRESHOLD:
            self._session.state = LearningState.CONFIRMING
            self._apply_learning(
                node, candidates, confidence, total_delta,
                detected_phase, phase_confidence, nilm_devices,
                provisional=True,
            )
            b_name = node.name if node else s.node_id
            return {
                "state":                   LearningState.CONFIRMING,
                "confidence":              round(confidence, 2),
                "candidates":              candidates,
                "detected_phase":          detected_phase,
                "need_second_measurement": True,
                "instruction": (
                    f"Confidence {round(confidence*100)}% — zet '{b_name}' "
                    f"weer AAN en herhaal de meting voor betere zekerheid."
                ),
            }

        else:
            result = self._apply_learning(
                node, candidates, confidence, total_delta,
                detected_phase, phase_confidence, nilm_devices,
            )
            result["phase_boosts"] = []
            self._session = None
            return result

    def _compute_learning_phase_boosts(
        self,
        candidates     : List[dict],
        nilm_phases    : Dict[str, Tuple[str, float]],
        detected_phase : str,
        phase_conf     : float,
        node_id        : str,
    ) -> List[PhaseBoost]:
        """
        Bereken fase-boosts na een leer-sessie.
        Combineert circuit-fase (P1) met NILM-device fasen Bayesiaans.
        """
        boosts: List[PhaseBoost] = []

        # Devices die verdwenen zijn maar al een hoge fase-confidence hebben
        device_phase_evidence: Dict[str, List[float]] = {}
        for c in candidates:
            dev_id          = c["device_id"]
            nil_phase, nil_conf = nilm_phases.get(dev_id, ("", 0.0))
            if nil_conf >= 0.65 and nil_phase in ("L1", "L2", "L3"):
                device_phase_evidence.setdefault(nil_phase, []).append(nil_conf)
            elif detected_phase and phase_conf >= 0.65:
                # Device had onzekere fase → boost vanuit bevestigd circuit
                new_conf = min(0.90, phase_conf * 0.85)
                boosts.append(PhaseBoost(
                    target_id   = dev_id,
                    target_type = "nilm_device",
                    phase       = detected_phase,
                    confidence  = new_conf,
                    source      = "circuit_learning",
                ))

        # Bayesiaans circuit-fase bepalen vanuit device-fasen
        for phase, confs in device_phase_evidence.items():
            log_comb = sum(math.log(max(c, 1e-9)) for c in confs)
            combined = math.exp(log_comb / len(confs))
            combined = min(0.97, combined * (1 + 0.05 * len(confs)))
            if combined > phase_conf:
                boosts.append(PhaseBoost(
                    target_id   = node_id,
                    target_type = "circuit",
                    phase       = phase,
                    confidence  = round(combined, 3),
                    source      = "nilm_cross",
                    bayesian_n  = len(confs),
                ))

        return boosts

    def _apply_learning(
        self,
        node         ,
        candidates   : List[dict],
        confidence   : float,
        total_delta_w: float,
        detected_phase   : str,
        phase_confidence : float,
        nilm_devices     : List[dict],
        provisional      : bool = False,
    ) -> dict:
        if node is None:
            return {"error": "Node niet gevonden"}

        for c in candidates:
            dev_id = c["device_id"]
            if dev_id not in node.linked_devices:
                node.linked_devices.append(dev_id)

        if detected_phase and phase_confidence >= 0.60:
            if isinstance(node, CircuitBreaker):
                node.phase            = detected_phase
                node.phase_confidence = round(phase_confidence, 2)

        # Ruimte-inferentie
        device_map  = {d.get("id", ""): d for d in nilm_devices}
        room_votes  : List[str] = []
        for dev_id in node.linked_devices:
            dev  = device_map.get(dev_id, {})
            room = dev.get("room") or dev.get("area") or ""
            if room:
                room_votes.append(room)
        if room_votes:
            for room, _ in Counter(room_votes).most_common():
                if room and room not in node.linked_rooms:
                    node.linked_rooms.append(room)

        node.linked_power_w = round(total_delta_w, 1)
        node.confidence     = round(confidence, 2)
        node.last_learned   = time.time()
        if not provisional:
            node.measurement_count += 1

        return {
            "state":             LearningState.DONE,
            "node_id":           node.id,
            "devices":           [c["device_id"] for c in candidates],
            "confidence":        round(confidence, 2),
            "delta_w":           round(total_delta_w, 1),
            "detected_phase":    detected_phase,
            "phase_confidence":  round(phase_confidence, 2),
            "rooms":             node.linked_rooms[:],
            "success":           True,
        }

    def cancel_learning(self) -> None:
        self._session = None

    # ── NEN1010 toetsing ──────────────────────────────────────────────────────

    def check_nen1010(self, nilm_devices: Optional[List[dict]] = None,
                     country: str = "NL") -> List[NEN1010Finding]:
        findings: List[NEN1010Finding] = []
        nilm_map = {d.get("id", ""): d for d in (nilm_devices or [])}
        max_groups = MAX_GROUPS_PER_COUNTRY.get(country.upper(), NEN1010_MAX_GROUPS_PER_RCD)

        for node in self.get_all_sorted():
            if not isinstance(node, CircuitBreaker):
                continue

            if node.is_rcd_family and not (node.node_type == NodeType.MAIN):
                # NEN1010 art. 531.3: max 4 eindgroepen per 30mA aardlekschakelaar
                # Uitzondering: RCBO's (eigen aardlekautomaat per groep) tellen NIET mee
                # omdat elk circuit individueel beschermd is.
                leaves = self.get_all_leaves(node.id)
                # Alleen MCB's zonder eigen RCD-bescherming tellen mee
                unprotected_leaves = [
                    l for l in leaves
                    if l.node_type in (NodeType.MCB, NodeType.MCB3F)
                ]
                # RCBO's tellen niet mee — die hebben eigen aardlekbeveiliging
                if len(unprotected_leaves) > max_groups:
                    severity = (NEN1010Severity.RED
                                if len(unprotected_leaves) > max_groups + 2
                                else NEN1010Severity.ORANGE)
                    _norm_name = {"NL":"NEN 1010","BE":"AREI","DE":"DIN VDE 0100",
                                  "FR":"NF C 15-100","GB":"BS 7671"}.get(country.upper(), "HD 60364")
                    findings.append(NEN1010Finding(
                        severity = severity,
                        code     = "INSTALL-531.3",
                        message  = f"Te veel groepen op aardlek '{node.name}'",
                        detail   = (
                            f"{len(unprotected_leaves)} groepen — max {max_groups} "                            f"per 30mA aardlekschakelaar ({_norm_name}). "                            f"RCBO's ({len(leaves) - len(unprotected_leaves)}x) tellen niet mee."
                        ),
                    ))
                # Waarschuwing: 100mA aardlek heeft andere regels (bv. voor PV/EV)
                if node.ma is not None and int(node.ma) >= 100 and len(unprotected_leaves) > 0:
                    findings.append(NEN1010Finding(
                        severity = NEN1010Severity.ORANGE,
                        code     = "NEN1010-531.3-100mA",
                        message  = f"Aardlek '{node.name}' (100mA): beperkte personenbeveiliging",
                        detail   = "100mA aardlek beschermt niet tegen elektrische schok — alleen brandbeveiliging.",
                    ))
                continue

            if node.is_rcd_family:
                continue

            protected = self.node_is_protected_by_rcd(node.id)
            device_names = " ".join(
                (nilm_map.get(d, {}).get("name", d) or d).lower()
                for d in node.linked_devices
            )
            rooms_lower  = " ".join(r.lower() for r in node.linked_rooms)

            # Badkamer/buiten verplicht aardlek
            needs_rcd = (any(kw in device_names or kw in rooms_lower
                             for kw in DEVICE_KW_BATH | DEVICE_KW_OUTSIDE))
            if needs_rcd and not protected:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.RED,
                    code     = "NEN1010-701",
                    message  = f"Groep '{node.name}' vereist aardlek",
                    detail   = "Badkamer/buiten-groepen verplicht aardlekbeveiliging (NEN1010 art. 701/702)",
                ))

            # EV-lader
            has_ev = any(kw in device_names for kw in DEVICE_KW_EV)
            if has_ev:
                if not protected:
                    findings.append(NEN1010Finding(
                        severity = NEN1010Severity.RED,
                        code     = "NEN1010-722",
                        message  = f"Groep '{node.name}' (EV): geen aardlek",
                        detail   = "EV-lader verplicht eigen RCBO (NEN1010 art. 722.531)",
                    ))
                elif node.node_type != NodeType.RCBO:
                    findings.append(NEN1010Finding(
                        severity = NEN1010Severity.ORANGE,
                        code     = "NEN1010-722-RCBO",
                        message  = f"EV op aardlek '{node.name}': aanbevolen RCBO",
                        detail   = "EV-lader bij voorkeur op eigen RCBO type B ipv gedeeld aardlek",
                    ))
                if node.rcd_type not in (RCDType.TYPE_B, RCDType.UNKNOWN):
                    findings.append(NEN1010Finding(
                        severity = NEN1010Severity.ORANGE,
                        code     = "NEN1010-722-TYPEB",
                        message  = f"EV op '{node.name}': type B aardlek vereist",
                        detail   = "EV-laders met gelijkstroom-lekstroom vereisen type B aardlek",
                    ))

            # PV-omvormer
            has_pv = any(kw in device_names for kw in DEVICE_KW_PV)
            if has_pv and not protected:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.ORANGE,
                    code     = "NEN1010-PV",
                    message  = f"PV-omvormer op '{node.name}' zonder aardlek",
                    detail   = "Aanbevolen: eigen RCBO voor PV-omvormer",
                ))

            # Wasmachine/droger/vaatwasser op gedeelde groep
            has_washing = any(kw in device_names for kw in DEVICE_KW_WASHING)
            if has_washing and len(node.linked_devices) > 1:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.ORANGE,
                    code     = "NEN1010-WASH",
                    message  = f"Wasgoed apparaat deelt groep '{node.name}'",
                    detail   = "Wasmachine/droger/vaatwasser aanbevolen op eigen groep",
                ))

            # Kookplaat op gedeelde groep
            has_cooking = any(kw in device_names for kw in DEVICE_KW_COOKING)
            if has_cooking and len(node.linked_devices) > 1:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.YELLOW,
                    code     = "NEN1010-COOK",
                    message  = f"Kookplaat deelt groep '{node.name}'",
                    detail   = "Kookplaat aanbevolen op eigen groep (hoog vermogen)",
                ))

            # Te veel lichtpunten (schatting)
            est_points = int(node.linked_power_w / NEN1010_LIGHT_POINT_W) if node.linked_power_w else 0
            if est_points > NEN1010_MAX_LIGHT_POINTS:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.YELLOW,
                    code     = "NEN1010-LIGHT",
                    message  = f"Groep '{node.name}': mogelijk >20 lichtpunten",
                    detail   = (f"Geschat {est_points} lichtpunten op basis van vermogen. "
                                f"Max 20 aanbevolen (NEN1010 art. 524)"),
                ))

            # Kabeldikte advies
            if node.cable_advice_mm2:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.YELLOW,
                    code     = "NEN1010-CABLE",
                    message  = f"Groep '{node.name}' ({node.ampere}A): controleer kabeldikte",
                    detail   = (f"Aanbevolen kabeldikte bij {node.ampere}A: "
                                f"{node.cable_advice_mm2}mm². "
                                f"Daadwerkelijke dikte niet meetbaar — visueel controleren."),
                ))

        # Submeters: spanningsval
        for sm in self._submeters.values():
            if sm.voltage_drop_pct is None:
                continue
            drop = sm.voltage_drop_pct
            if drop >= VOLTAGE_DROP_RED_PCT:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.RED,
                    code     = "NEN1010-VDROP-RED",
                    message  = f"Tussenmeter '{sm.name}': gevaarlijke spanningsval",
                    detail   = (f"Gemeten spanningsval {drop*100:.1f}% > 5%. "
                                f"Mogelijke oorzaak: te dunne of beschadigde kabel."),
                ))
            elif drop >= VOLTAGE_DROP_ORANGE_PCT:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.ORANGE,
                    code     = "NEN1010-VDROP-ORANGE",
                    message  = f"Tussenmeter '{sm.name}': spanningsval > 3% (NEN1010 grens)",
                    detail   = (f"Gemeten {drop*100:.1f}% — NEN1010 staat max 3% toe. "
                                f"Overweeg dikkere kabel."),
                ))
            elif drop >= VOLTAGE_DROP_YELLOW_PCT:
                findings.append(NEN1010Finding(
                    severity = NEN1010Severity.YELLOW,
                    code     = "NEN1010-VDROP-YELLOW",
                    message  = f"Tussenmeter '{sm.name}': kleine spanningsval",
                    detail   = f"Gemeten {drop*100:.1f}% — binnen norm maar controleerbaar.",
                ))

        # ── Globale checks op kast-niveau ─────────────────────────────────────
        all_nodes = self.get_all_sorted()
        mains  = [n for n in all_nodes if n.node_type == NodeType.MAIN]
        rcds   = [n for n in all_nodes if n.node_type in (NodeType.RCD, NodeType.RCBO)]
        mcbs   = [n for n in all_nodes if n.node_type in (NodeType.MCB, NodeType.MCB3F)]

        # Geen hoofdschakelaar
        if not mains:
            findings.append(NEN1010Finding(
                severity = NEN1010Severity.RED,
                code     = "NEN1010-HS",
                message  = "Geen hoofdschakelaar geconfigureerd",
                detail   = "Een installatiegroepenkast vereist een hoofdschakelaar (NEN1010 art. 462)",
            ))

        # Groepen zonder aardlekbeveiliging
        unprotected_mcbs = [n for n in mcbs if not self.node_is_protected_by_rcd(n.id)]
        if unprotected_mcbs:
            findings.append(NEN1010Finding(
                severity = NEN1010Severity.ORANGE,
                code     = "NEN1010-531-NO-RCD",
                message  = f"{len(unprotected_mcbs)} groep(en) zonder aardlekbeveiliging",
                detail   = ("Aanbevolen: alle eindgroepen achter een 30mA aardlekschakelaar "                            "(NEN1010 art. 531.2 best practice voor woningen)."),
            ))

        return findings

    # ── Status voor coordinator / sensor ──────────────────────────────────────

    def set_group_meter(self, tracker: "GroupMeterTracker") -> None:
        """Koppel de GroupMeterTracker zodat get_status() de data erbij kan voegen."""
        self._group_meter = tracker

    def update_meter_readings(
        self,
        readings     : Dict[str, "GroupMeterReading"],
        device_data  : List[dict],
        price_eur_kwh: float,
        ts           : float,
        hass         = None,
    ) -> None:
        """Aanroepen elke cyclus — berekent virtuele groepsmeters."""
        self._meter_readings = readings

    def generate_nen1010_report(
        self,
        address      : str = "",
        nilm_devices : Optional[List[dict]] = None,
        extra_info   : str = "",
    ) -> str:
        """Genereer HTML NEN1010 rapport."""
        gen = NEN1010ReportGenerator()
        return gen.generate(self, address=address, nilm_devices=nilm_devices, extra_info=extra_info)

    def update_price(self, price_eur_kwh: float) -> None:
        """Coordinator roept dit aan met actuele energieprijs voor kostenberekening."""
        self._current_price = price_eur_kwh

    def generate_report_html(self, address: str = "") -> str:
        """Genereer NEN1010 HTML rapport voor installateur."""
        return NEN1010ReportGenerator.generate_html(
            self.get_status(), address=address
        )

    def generate_report_markdown(self) -> str:
        return NEN1010ReportGenerator.to_markdown(self.get_status())

    def get_status(self, nilm_devices: Optional[List[dict]] = None) -> dict:
        findings  = self.check_nen1010(nilm_devices, country=getattr(self, '_country', 'NL'))
        all_nodes = self.get_all_sorted()

        session_data = None
        if self._session:
            session_data = {
                "node_id":       self._session.node_id,
                "state":         self._session.state,
                "measurement_n": self._session.measurement_num,
            }

        price       = getattr(self, "_current_price", 0.25)
        meter_data  = self._group_meter.get_all_data(price)
        simult      = self._simultaneity.get_status()
        hier_stats  = self._hierarchy_learner.get_stats()

        return {
            "node_count":    len(all_nodes),
            "circuit_count": len(self._breakers),
            "submeter_count": len(self._submeters),
            "learned_count": sum(1 for n in all_nodes if n.confidence > 0),
            "total_devices": sum(len(n.linked_devices) for n in all_nodes),
            "nen1010_red":   sum(1 for f in findings if f.severity == NEN1010Severity.RED),
            "nen1010_orange": sum(1 for f in findings if f.severity == NEN1010Severity.ORANGE),
            "nen1010_yellow": sum(1 for f in findings if f.severity == NEN1010Severity.YELLOW),
            "nen1010_findings": [f.to_dict() for f in findings],
            "active_session":    session_data,
            "hierarchy_learner": self._hierarchy_learner.get_stats(),
            "meter_readings":    {
                nid: {
                    "power_w":      r.power_w,
                    "kwh_today":    r.kwh_today,
                    "kwh_month":    r.kwh_month,
                    "cost_today":   r.cost_today,
                    "cost_month":   r.cost_month,
                    "source":       r.source,
                    "is_estimated": r.is_estimated,
                }
                for nid, r in self._meter_readings.items()
            },
            "simultaneity_factor":   simult["simultaneity_factor"],
            "nen1010_simult_factor": simult["nen1010_factor"],
            "simult_deviation":      simult["nen1010_deviation"],
            "simult_sufficient":     simult["sufficient_data"],
            "hierarchy_stats":       hier_stats,
            "meter_data":            meter_data,
            "nodes": [
                {
                    "id":              n.id,
                    "name":            n.name,
                    "node_type":       n.node_type,
                    "card_type":       getattr(n, "card_type", ""),
                    "kar":             getattr(n, "kar", "B"),
                    "ma":              getattr(n, "ma", 30),
                    "parent_main_id":  getattr(n, "parent_main_id", ""),
                    "rail_index":      getattr(n, "rail_index", 0),
                    "parent_id":       n.parent_id,
                    "position":        n.position,
                    "ampere":          getattr(n, "ampere", None),
                    "phase":           getattr(n, "phase", ""),
                    "phase_confidence": getattr(n, "phase_confidence", 0.0),
                    "switch_entity":   getattr(n, "switch_entity", ""),
                    "rcd_type":        getattr(n, "rcd_type", ""),
                    "linked_devices":  n.linked_devices,
                    "linked_rooms":    n.linked_rooms,
                    "linked_power_w":  n.linked_power_w if hasattr(n, "linked_power_w") else 0.0,
                    "confidence":      n.confidence,
                    "measurement_count": n.measurement_count,
                    "last_learned":    n.last_learned,
                    "current_power_w": n.current_power_w,
                    "load_pct":        n.load_pct,
                    "rated_power_w":   n.rated_power_w,
                    "notes":           n.notes,
                    # Meter data
                    "meter": meter_data.get(n.id, {}),
                    # Anomalie baseline
                    "anomaly": self._anomaly_detector.get_stats(n.id),
                    # SubMeter specifiek
                    "r_cable_ohm":     getattr(n, "r_cable_ohm", None),
                    "estimated_mm2":   getattr(n, "estimated_mm2", None),
                    "voltage_drop_pct": getattr(n, "voltage_drop_pct", None),
                    "r_samples":       getattr(n, "r_samples", 0),
                    "current_voltage_v": getattr(n, "current_voltage_v", None),
                    "cable_length_m":  getattr(n, "cable_length_m", None),
                }
                for n in all_nodes
            ],
        }

    # ── Foto-herkenning stub ──────────────────────────────────────────────────

    @staticmethod
    async def async_recognize_from_photo(image_bytes: bytes) -> List[dict]:
        """
        Herken groepen uit een foto van de groepenkast.

        Stub — implementeer via Anthropic API:
            import anthropic, base64
            client = anthropic.AsyncAnthropic()
            b64    = base64.standard_b64encode(image_bytes).decode()
            resp   = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg", "data": b64}},
                        {"type": "text", "text":
                            "Analyseer deze groepenkast foto. "
                            "Geef een JSON-lijst terug (geen markdown) met voor elke groep: "
                            "name (string), node_type (main/rcd/rcbo/mcb/mcb_3f), "
                            "ampere (int), rcd_type (type_a/type_b/unknown), "
                            "parent_name (string of null). "
                            "Reageer ALLEEN met JSON."}
                    ],
                }]
            )
            import json
            return json.loads(resp.content[0].text)

        Returns: lijst van dicts geschikt voor CircuitBreaker.from_dict()
        """
        _LOGGER.info("Foto-herkenning stub — implementeer via Anthropic API")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PASSIEF HIËRARCHIE LEREN
# ══════════════════════════════════════════════════════════════════════════════

COOCCUR_WINDOW_S       = 2.0
COOCCUR_MIN_EVENTS     = 3
COOCCUR_SUGGEST_THRESH = 0.70
COOCCUR_AUTO_THRESH    = 0.90


class HierarchyLearner:
    """
    Leert aardlek-hiërarchie passief uit co-occurrence van groep-uitvallen.

    Bij een echte RCD-trip vallen meerdere groepen binnen COOCCUR_WINDOW_S
    tegelijk uit. Die correlatie onthult welke automaten achter dezelfde RCD zitten.

    Gebruik:
        learner = HierarchyLearner()

        # In tick() na uitvalsdetectie:
        for outage in outages:
            suggestions = learner.record_outage(outage["node_id"], outage["ts"])
            for child_id, sibling_id, conf in suggestions:
                # Suggereer of pas automatisch toe op de panel-boom
                ...

        # Einde van cyclus:
        learner.flush()

        # Query:
        groups = learner.get_sibling_groups()  # nodes die steeds samen uitvallen
    """

    def __init__(self) -> None:
        self._pair_counts:   Dict[str, Dict[str, int]] = {}
        self._cooccur:       Dict[str, int] = {}   # str(sorted list) → count
        self._pending:       List[str]  = []
        self._pending_ts:    float      = 0.0
        self._total_outages: int        = 0

    def record_outage(self, node_id: str, ts: float) -> List[Tuple[str, str, float]]:
        """Registreer één uitgevallen node. Geeft suggesties terug als venster sluit."""
        if self._pending and (ts - self._pending_ts) > COOCCUR_WINDOW_S:
            result = self._close_event()
            self._pending    = [node_id]
            self._pending_ts = ts
            return result
        if node_id not in self._pending:
            self._pending.append(node_id)
        if not self._pending_ts:
            self._pending_ts = ts
        return []

    def flush(self) -> List[Tuple[str, str, float]]:
        """Sluit openstaand venster — aanroepen einde coordinator-cyclus."""
        return self._close_event()

    def _close_event(self) -> List[Tuple[str, str, float]]:
        nodes = list(self._pending)
        self._pending    = []
        self._pending_ts = 0.0
        if len(nodes) < 2:
            self._total_outages += len(nodes)
            return []

        self._total_outages += 1
        key = str(sorted(nodes))
        self._cooccur[key] = self._cooccur.get(key, 0) + 1

        for i, a in enumerate(nodes):
            for b in nodes[i+1:]:
                self._pair_counts.setdefault(a, {}).setdefault(b, 0)
                self._pair_counts[a][b] += 1
                self._pair_counts.setdefault(b, {}).setdefault(a, 0)
                self._pair_counts[b][a] += 1

        return self._compute_suggestions()

    def _compute_suggestions(self) -> List[Tuple[str, str, float]]:
        if self._total_outages < COOCCUR_MIN_EVENTS:
            return []
        suggestions, seen = [], set()
        for a, partners in self._pair_counts.items():
            for b, count in partners.items():
                pair = tuple(sorted([a, b]))
                if pair in seen:
                    continue
                seen.add(pair)
                conf = count / max(self._total_outages, 1)
                if conf >= COOCCUR_SUGGEST_THRESH:
                    suggestions.append((a, b, round(conf, 3)))
        return suggestions

    def get_sibling_groups(
        self, min_confidence: float = COOCCUR_SUGGEST_THRESH
    ) -> List[List[str]]:
        """Nodes die vaak samen uitvallen gegroepeerd via union-find."""
        if self._total_outages < COOCCUR_MIN_EVENTS:
            return []
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for a, partners in self._pair_counts.items():
            for b, count in partners.items():
                if count / max(self._total_outages, 1) >= min_confidence:
                    union(a, b)

        groups: Dict[str, List[str]] = {}
        for node in set(parent.keys()):
            root = find(node)
            groups.setdefault(root, []).append(node)

        return [sorted(g) for g in groups.values() if len(g) > 1]

    def apply_to_panel(self, panel: "CircuitBreakerPanel") -> List[dict]:
        """
        Pas geleerde hiërarchie toe op de panel-boom.
        Zoekt een geschikte RCD-parent voor elke sibling-groep.
        Geeft lijst van doorgevoerde wijzigingen terug.
        """
        changes: List[dict] = []
        for group in self.get_sibling_groups(min_confidence=COOCCUR_AUTO_THRESH):
            # Zoek of er al een gemeenschappelijke RCD-parent is
            rcd_parents = set()
            for node_id in group:
                for ancestor in panel.get_ancestors(node_id):
                    if (isinstance(ancestor, CircuitBreaker)
                            and ancestor.has_rcd_protection):
                        rcd_parents.add(ancestor.id)
                        break

            if len(rcd_parents) == 1:
                # Alle nodes al onder zelfde RCD — bevestig alleen
                changes.append({
                    "action":    "confirmed",
                    "nodes":     group,
                    "parent_id": next(iter(rcd_parents)),
                })
                continue

            if len(rcd_parents) == 0:
                # Geen RCD bekend — maak een nieuwe aan als placeholder
                _LOGGER.info(
                    "HierarchyLearner: %d nodes vaak samen — suggestie voor nieuwe aardlek: %s",
                    len(group), group,
                )
                changes.append({
                    "action":    "suggest_new_rcd",
                    "nodes":     group,
                    "parent_id": None,
                })
                continue

            # Meerdere RCDs — kies de meest voorkomende
            rcd_vote = Counter(
                ancestor.id
                for node_id in group
                for ancestor in panel.get_ancestors(node_id)
                if isinstance(ancestor, CircuitBreaker) and ancestor.has_rcd_protection
            )
            best_rcd = rcd_vote.most_common(1)[0][0]
            for node_id in group:
                node = panel.get_node(node_id)
                if node and node.parent_id != best_rcd:
                    old_parent = node.parent_id
                    node.parent_id = best_rcd
                    changes.append({
                        "action":     "reparented",
                        "node_id":    node_id,
                        "old_parent": old_parent,
                        "new_parent": best_rcd,
                    })
                    _LOGGER.info(
                        "HierarchyLearner: '%s' verplaatst naar aardlek '%s' (confidence ≥%.0f%%)",
                        node_id, best_rcd, COOCCUR_AUTO_THRESH * 100,
                    )

        return changes

    def get_stats(self) -> dict:
        return {
            "total_outages":  self._total_outages,
            "pair_count":     sum(len(v) for v in self._pair_counts.values()) // 2,
            "sibling_groups": self.get_sibling_groups(),
            "auto_threshold": COOCCUR_AUTO_THRESH,
        }

    def to_dict(self) -> dict:
        return {
            "pair_counts":   self._pair_counts,
            "cooccur":       self._cooccur,
            "total_outages": self._total_outages,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HierarchyLearner":
        hl = cls()
        hl._total_outages = int(d.get("total_outages", 0))
        hl._pair_counts   = d.get("pair_counts", {})
        hl._cooccur       = d.get("cooccur", {})
        return hl


# ══════════════════════════════════════════════════════════════════════════════
# VIRTUELE GROEPSMETER — met databron-hiërarchie
# ══════════════════════════════════════════════════════════════════════════════

class MeterSource:
    """Databron-prioriteit per groep."""
    PHYSICAL_BUILTIN  = "physical_builtin"   # meter OP de automaat (Shelly EM e.d.)
    PHYSICAL_SUBMETER = "physical_submeter"  # SubMeter achter de automaat
    SMART_PLUG        = "smart_plug"         # slimme stekkers van gekoppelde devices
    NILM              = "nilm"               # NILM-optelling (geschat)
    NONE              = "none"               # geen data


@dataclass
class GroupMeterReading:
    node_id     : str
    power_w     : float
    kwh_today   : float
    kwh_month   : float
    kwh_total   : float
    cost_today  : float
    cost_month  : float
    source      : str    # MeterSource waarde
    source_entity: str   # HA entity als physical, anders ""
    is_estimated: bool


class GroupMeterTracker:
    """
    Houdt kWh en kosten bij per groep — gebruikt de beste beschikbare databron.

    Databron-hiërarchie (hoogste prioriteit eerst):
      1. physical_builtin  — HA entity op de CircuitBreaker zelf (meter_entity)
      2. physical_submeter — SubMeter-kind van de groep
      3. smart_plug        — Som van smart-plug devices (source="smart_plug" in NILM)
      4. nilm              — Som van alle gekoppelde NILM-devices

    Gebruik:
        tracker = GroupMeterTracker(store)
        await tracker.async_load()

        # Elke cyclus:
        readings = tracker.tick(panel, device_data, price_eur_kwh, ts)
        # readings: {node_id: GroupMeterReading}
    """

    def __init__(self, store=None) -> None:
        self._store     = store
        self._kwh_today : Dict[str, float] = {}
        self._kwh_month : Dict[str, float] = {}
        self._kwh_total : Dict[str, float] = {}
        self._last_ts   : float = 0.0
        self._last_date : str   = ""
        self._last_month: str   = ""
        self._loaded    = False

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._kwh_today  = data.get("kwh_today",  {})
        self._kwh_month  = data.get("kwh_month",  {})
        self._kwh_total  = data.get("kwh_total",  {})
        self._last_date  = data.get("last_date",  "")
        self._last_month = data.get("last_month", "")
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save({
            "kwh_today":  self._kwh_today,
            "kwh_month":  self._kwh_month,
            "kwh_total":  self._kwh_total,
            "last_date":  self._last_date,
            "last_month": self._last_month,
        })

    def get_all_data(self, price_eur_kwh: float = 0.25) -> dict:
        """Geef alle meter-data terug als dict (compat met get_status)."""
        all_ids = set(self._kwh_total.keys())
        return {nid: {
            "kwh_today":    round(self._kwh_today.get(nid, 0.0), 3),
            "kwh_month":    round(self._kwh_month.get(nid, 0.0), 3),
            "kwh_total":    round(self._kwh_total.get(nid, 0.0), 3),
            "cost_today":   round(self._kwh_today.get(nid, 0.0) * price_eur_kwh, 3),
            "cost_month":   round(self._kwh_month.get(nid, 0.0) * price_eur_kwh, 3),
            "meter_source": "virtual_nilm",
        } for nid in all_ids}


    def tick(
        self,
        panel        : "CircuitBreakerPanel",
        device_data  : List[dict],
        price_eur_kwh: float,
        ts           : float,
        hass         = None,
    ) -> Dict[str, GroupMeterReading]:
        import datetime as _dt

        if self._last_ts == 0.0:
            self._last_ts = ts
            return {}

        dt_h = (ts - self._last_ts) / 3600.0
        self._last_ts = ts

        now   = _dt.datetime.fromtimestamp(ts)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        # Dag/maand reset
        if today != self._last_date and self._last_date:
            self._kwh_today.clear()
        if month != self._last_month and self._last_month:
            self._kwh_month.clear()
        self._last_date  = today
        self._last_month = month

        # Device lookup
        device_map = {d.get("id", ""): d for d in device_data}

        readings: Dict[str, GroupMeterReading] = {}

        for node in panel.get_all_sorted():
            if isinstance(node, CircuitBreaker) and node.is_rcd_family:
                continue  # RCD-nodes krijgen geen eigen meter — som van children
            if isinstance(node, SubMeter):
                continue  # SubMeters worden direct uitgelezen

            power_w, source, source_entity = self._read_best_source(
                node, panel, device_map, hass
            )

            # Accumuleer kWh
            kwh_delta = power_w / 1000.0 * dt_h
            nid = node.id
            self._kwh_today[nid]  = self._kwh_today.get(nid, 0.0)  + kwh_delta
            self._kwh_month[nid]  = self._kwh_month.get(nid, 0.0)  + kwh_delta
            self._kwh_total[nid]  = self._kwh_total.get(nid, 0.0)  + kwh_delta

            cost_today = self._kwh_today[nid]  * price_eur_kwh
            cost_month = self._kwh_month[nid]  * price_eur_kwh

            readings[nid] = GroupMeterReading(
                node_id       = nid,
                power_w       = round(power_w, 1),
                kwh_today     = round(self._kwh_today[nid], 4),
                kwh_month     = round(self._kwh_month[nid], 3),
                kwh_total     = round(self._kwh_total[nid], 3),
                cost_today    = round(cost_today, 4),
                cost_month    = round(cost_month, 3),
                source        = source,
                source_entity = source_entity,
                is_estimated  = source in (MeterSource.NILM, MeterSource.NONE),
            )

        return readings

    def _read_best_source(
        self,
        node      : CircuitBreaker,
        panel     : "CircuitBreakerPanel",
        device_map: Dict[str, dict],
        hass,
    ) -> Tuple[float, str, str]:
        """Geef (power_w, source, source_entity) terug voor de beste databron."""

        # 1. Fysieke meter OP de automaat
        meter_entity = getattr(node, "meter_entity", "") or ""
        if meter_entity and hass:
            try:
                state = hass.states.get(meter_entity)
                if state and state.state not in ("unavailable", "unknown"):
                    return float(state.state), MeterSource.PHYSICAL_BUILTIN, meter_entity
            except (ValueError, TypeError):
                pass

        # 2. SubMeter als direct kind van deze node
        for child in panel.get_children(node.id):
            if isinstance(child, SubMeter) and child.current_power_w > 0:
                return child.current_power_w, MeterSource.PHYSICAL_SUBMETER, child.id

        # 3. Slimme stekkers (source="smart_plug" in NILM)
        smart_plug_w = sum(
            float(device_map[dev_id].get("current_power_w", 0) or 0)
            for dev_id in node.linked_devices
            if dev_id in device_map
            and device_map[dev_id].get("source") == "smart_plug"
        )
        if smart_plug_w > 0:
            return smart_plug_w, MeterSource.SMART_PLUG, ""

        # 4. NILM-optelling van alle gekoppelde apparaten
        nilm_w = sum(
            float(device_map[dev_id].get("current_power_w", 0) or 0)
            for dev_id in node.linked_devices
            if dev_id in device_map
        )
        if node.linked_devices:
            return nilm_w, MeterSource.NILM, ""

        return 0.0, MeterSource.NONE, ""


# ══════════════════════════════════════════════════════════════════════════════
# GELIJKTIJDIGHEIDSFACTOR
# ══════════════════════════════════════════════════════════════════════════════

NEN1010_SIMULTANEITY = 0.60   # NEN1010 aanname voor woningen



# Alias voor backward compatibiliteit
GroupMeter = GroupMeterTracker

class SimultaneityTracker:
    """
    Meet de werkelijke gelijktijdigheidsfactor per aardlek/hoofdschakelaar.

    NEN1010 rekent met factor 0.60 voor woningen maar de werkelijke factor
    is vaak lager (0.3-0.45) overdag en hoger (0.7-0.9) op piekavond.

    Dit geeft betere piekschaving dan de worst-case aanname.

    Per aardlek bijgehouden:
      - factor_ema: geleerde factor (EMA alpha=0.05, traag leren)
      - factor_peak: gemeten piekfactor (hogere alpha bij piek)
      - factor_by_hour: per uur van de dag
    """

    def __init__(self) -> None:
        self._factor_ema  : Dict[str, float] = {}  # node_id → EMA factor
        self._factor_peak : Dict[str, float] = {}
        self._factor_hour : Dict[str, List[float]] = {}  # node_id → 24 uur EMA
        self._samples     : Dict[str, int]   = {}

    def tick(
        self,
        panel         : "CircuitBreakerPanel",
        hour_of_day   : int,
    ) -> Dict[str, dict]:
        """
        Bereken en update gelijktijdigheidsfactor per RCD-node.
        Geeft {node_id: {factor, factor_peak, vs_nen1010_pct}} terug.
        """
        result: Dict[str, dict] = {}
        alpha      = 0.05
        alpha_peak = 0.10

        for node in panel.get_all_sorted():
            if not (isinstance(node, CircuitBreaker) and node.is_rcd_family):
                continue

            leaves = panel.get_all_leaves(node.id)
            if len(leaves) < 2:
                continue

            # Maximaal mogelijk vermogen = som van alle groepen op vol vermogen
            max_total_w = sum(l.rated_power_w for l in leaves)
            if max_total_w <= 0:
                continue

            # Gemeten som
            actual_w = sum(l.current_power_w for l in leaves)
            factor   = actual_w / max_total_w

            nid = node.id
            self._factor_ema[nid] = (
                factor if nid not in self._factor_ema
                else alpha * factor + (1 - alpha) * self._factor_ema[nid]
            )
            cur_peak = self._factor_peak.get(nid, 0.0)
            self._factor_peak[nid] = (
                alpha_peak * factor + (1 - alpha_peak) * cur_peak
                if factor > cur_peak else cur_peak
            )
            if nid not in self._factor_hour:
                self._factor_hour[nid] = [0.0] * 24
            h = self._factor_hour[nid]
            h[hour_of_day] = alpha * factor + (1 - alpha) * h[hour_of_day]
            self._samples[nid] = self._samples.get(nid, 0) + 1

            learned = self._factor_ema[nid]
            result[nid] = {
                "factor_ema":       round(learned, 3),
                "factor_peak":      round(self._factor_peak[nid], 3),
                "factor_nen1010":   NEN1010_SIMULTANEITY,
                "vs_nen1010_pct":   round((learned / NEN1010_SIMULTANEITY - 1) * 100, 1),
                "samples":          self._samples[nid],
                "factor_by_hour":   [round(x, 3) for x in self._factor_hour[nid]],
            }

        return result

    def get_status(self) -> dict:
        """Geef huidige gelijktijdigheidsstatus terug."""
        samples    = sum(self._samples.values()) if self._samples else 0
        all_factors = list(self._factor_ema.values()) if self._factor_ema else []
        avg_factor  = sum(all_factors) / len(all_factors) if all_factors else NEN1010_SIMULTANEITY
        return {
            "simultaneity_factor": round(avg_factor, 3),
            "nen1010_factor":      NEN1010_SIMULTANEITY,
            "nen1010_deviation":   round(avg_factor - NEN1010_SIMULTANEITY, 3),
            "sufficient_data":     samples >= 100,
            "peak_samples":        samples,
        }

    def to_dict(self) -> dict:
        return {
            "factor_ema":  self._factor_ema,
            "factor_peak": self._factor_peak,
            "factor_hour": self._factor_hour,
            "samples":     self._samples,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SimultaneityTracker":
        st = cls()
        st._factor_ema  = d.get("factor_ema",  {})
        st._factor_peak = d.get("factor_peak", {})
        st._factor_hour = d.get("factor_hour", {})
        st._samples     = d.get("samples",     {})
        return st


# ══════════════════════════════════════════════════════════════════════════════
# GROEP-ANOMALIE DETECTIE
# ══════════════════════════════════════════════════════════════════════════════

ANOMALY_SIGMA         = 2.0    # afwijking in standaarddeviaties voor alert
ANOMALY_MIN_SAMPLES   = 20     # minimum samples voor betrouwbare baseline
ANOMALY_MIN_DELTA_W   = 100    # minimale absolute afwijking (W) voor alert
ANOMALY_COOLDOWN_S    = 600    # minimale tijd tussen twee alerts voor zelfde groep


@dataclass
class AnomalyAlert:
    node_id    : str
    node_name  : str
    power_w    : float
    baseline_w : float
    sigma      : float
    delta_w    : float
    likely_cause: str   # "new_device" / "fault" / "leakage" / "unknown"
    ts         : float

    def to_dict(self) -> dict:
        return asdict(self)


class AnomalyDetector:
    """
    Detecteert onverklaard verbruik per groep via statistische baseline.

    Algoritme:
      - Houdt lopend gemiddelde en variantie bij (Welford's online algoritme)
      - Alert als |verbruik - gemiddelde| > ANOMALY_SIGMA × std én > ANOMALY_MIN_DELTA_W
      - Heuristische classificatie op basis van patroon:
          new_device  : stap-sprong die daarna stabiel blijft
          fault       : pulserende of snel wisselende overschrijding
          leakage     : kleine maar constante overschrijding (~5-50W)
          unknown     : overig

    Gebruik:
        detector = AnomalyDetector()
        alerts = detector.tick(readings, panel)
    """

    def __init__(self) -> None:
        self._n    : Dict[str, int]   = {}
        self._mean : Dict[str, float] = {}
        self._m2   : Dict[str, float] = {}   # Welford M2
        self._last_alert: Dict[str, float] = {}
        self._prev_power: Dict[str, float] = {}

    def tick(
        self,
        readings : Dict[str, "GroupMeterReading"],
        panel    : "CircuitBreakerPanel",
        ts       : float,
    ) -> List[AnomalyAlert]:
        alerts: List[AnomalyAlert] = []

        for node_id, reading in readings.items():
            pw = reading.power_w
            self._update_stats(node_id, pw)

            n    = self._n.get(node_id, 0)
            mean = self._mean.get(node_id, 0.0)
            m2   = self._m2.get(node_id, 0.0)

            if n < ANOMALY_MIN_SAMPLES:
                continue

            std   = math.sqrt(m2 / n) if n > 1 else 0.0
            delta = pw - mean
            if std < 1.0:
                continue

            sigma_dist = abs(delta) / std
            if sigma_dist < ANOMALY_SIGMA or abs(delta) < ANOMALY_MIN_DELTA_W:
                continue

            # Cooldown
            last = self._last_alert.get(node_id, 0.0)
            if (ts - last) < ANOMALY_COOLDOWN_S:
                continue

            node  = panel.get_node(node_id)
            cause = self._classify_anomaly(node_id, delta, std, ts)

            self._last_alert[node_id] = ts
            alerts.append(AnomalyAlert(
                node_id     = node_id,
                node_name   = node.name if node else node_id,
                power_w     = round(pw, 1),
                baseline_w  = round(mean, 1),
                sigma       = round(sigma_dist, 2),
                delta_w     = round(delta, 1),
                likely_cause= cause,
                ts          = ts,
            ))

        self._prev_power = {nid: r.power_w for nid, r in readings.items()}
        return alerts

    def _update_stats(self, node_id: str, value: float) -> None:
        """Welford's online variantie-algoritme."""
        n    = self._n.get(node_id, 0) + 1
        mean = self._mean.get(node_id, 0.0)
        m2   = self._m2.get(node_id, 0.0)
        delta  = value - mean
        mean  += delta / n
        delta2 = value - mean
        m2    += delta * delta2
        self._n[node_id]    = n
        self._mean[node_id] = mean
        self._m2[node_id]   = m2

    def _classify_anomaly(
        self,
        node_id: str,
        delta  : float,
        std    : float,
        ts     : float,
    ) -> str:
        prev   = self._prev_power.get(node_id, 0.0)
        mean   = self._mean.get(node_id, 0.0)
        current = mean + delta

        # Lekstroom: klein, positief, constant
        if 5 < delta < 60 and abs(delta - (current - prev)) < 10:
            return "leakage"

        # Nieuw apparaat: grote stap-sprong, daarna stabiel
        if delta > std * 3 and abs(current - prev) < std * 0.5:
            return "new_device"

        # Defect: pulserende overschrijding
        if abs(current - prev) > std * 1.5:
            return "fault"

        return "unknown"

    def to_dict(self) -> dict:
        return {
            "n":          self._n,
            "mean":       self._mean,
            "m2":         self._m2,
            "last_alert": self._last_alert,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnomalyDetector":
        det = cls()
        det._n          = d.get("n",          {})
        det._mean       = d.get("mean",        {})
        det._m2         = d.get("m2",          {})
        det._last_alert = d.get("last_alert",  {})
        return det


# ══════════════════════════════════════════════════════════════════════════════
# NEN1010 RAPPORT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

    def get_stats(self, node_id: str) -> dict:
        """Geef baseline-statistieken terug voor een node (compat met get_status)."""
        return {"baseline_w": 0.0, "variance_w": 0.0, "samples": 0}


class NEN1010ReportGenerator:
    """
    Genereert een HTML-rapport van NEN1010-bevindingen.
    Geschikt om naar een installateur te sturen of als PDF op te slaan.

    Gebruik:
        gen  = NEN1010ReportGenerator()
        html = gen.generate(panel, address="Mijn straat 1", nilm_devices=[...])
        # Sla op als .html of converteer naar PDF via weasyprint/xhtml2pdf
    """

    SEVERITY_LABELS = {
        "red":    ("🔴 Overtreding", "#dc2626", "#fef2f2"),
        "orange": ("🟠 Aanbeveling", "#ea580c", "#fff7ed"),
        "yellow": ("🟡 Advies",      "#ca8a04", "#fefce8"),
        "green":  ("🟢 Conform",     "#16a34a", "#f0fdf4"),
    }

    @classmethod
    def generate_html(cls, panel_status: dict, address: str = "") -> str:
        """HTML rapport vanuit een panel_status dict (output van panel.get_status())."""
        import datetime as _dt
        findings = panel_status.get("nen1010_findings", [])
        nodes    = panel_status.get("nodes", [])
        n_red    = panel_status.get("nen1010_red", 0)
        n_orange = panel_status.get("nen1010_orange", 0)
        n_nodes  = panel_status.get("circuit_count", 0)
        date_str = _dt.datetime.now().strftime("%d-%m-%Y %H:%M")
        by_sev: dict = {"red": [], "orange": [], "yellow": []}
        for f in findings:
            by_sev.setdefault(f["severity"], []).append(f)
        C = {"red": "#ef4444", "orange": "#f97316", "yellow": "#eab308"}
        L = {"red": "🔴 Overtreding", "orange": "🟠 Aanbeveling", "yellow": "🟡 Advies"}
        sections = ""
        for sev in ("red", "orange", "yellow"):
            if not by_sev[sev]:
                continue
            c    = C[sev]
            rows = "".join(
                f"<tr><td style='padding:6px'><b style='color:{c}'>{f['message']}</b>"
                f"<br><small style='color:#6b7280'>{f['detail']}</small></td>"
                f"<td style='padding:6px;color:#9ca3af;font-size:11px'>{f['code']}</td></tr>"
                for f in by_sev[sev]
            )
            sections += (f"<h3 style='color:{c};margin-top:20px'>{L[sev]} ({len(by_sev[sev])})</h3>"
                         f"<table style='width:100%;border-collapse:collapse'>{rows}</table>")
        node_rows = "".join(
            f"<tr><td style='padding:4px 8px'>{n['name']}</td>"
            f"<td style='padding:4px 8px;color:#6b7280'>{n['node_type'].upper()}</td>"
            f"<td style='padding:4px 8px'>{n.get('phase') or '?'}</td>"
            f"<td style='padding:4px 8px'>{', '.join(n.get('linked_rooms') or []) or '—'}</td></tr>"
            for n in nodes if n.get("node_type") not in ("rcd", "main")
        )
        addr_line = f"Adres: {address}<br>" if address else ""
        return (
            f"<!DOCTYPE html><html lang='nl'><head><meta charset='UTF-8'>"
            f"<title>NEN1010 Rapport</title></head>"
            f"<body style='font-family:sans-serif;max-width:900px;margin:0 auto;padding:24px;color:#111827'>"
            f"<h1>⚡ NEN1010 Installatierapport</h1>"
            f"<p style='color:#6b7280'>{addr_line}Datum: {date_str}</p>"
            f"<div style='display:flex;gap:16px;margin:16px 0'>"
            f"<div style='background:#f9fafb;padding:12px 20px;border-radius:8px;text-align:center'>"
            f"<div style='font-size:28px;font-weight:700;color:#ef4444'>{n_red}</div>"
            f"<div style='font-size:12px;color:#6b7280'>Overtredingen</div></div>"
            f"<div style='background:#f9fafb;padding:12px 20px;border-radius:8px;text-align:center'>"
            f"<div style='font-size:28px;font-weight:700;color:#f97316'>{n_orange}</div>"
            f"<div style='font-size:12px;color:#6b7280'>Aanbevelingen</div></div>"
            f"<div style='background:#f9fafb;padding:12px 20px;border-radius:8px;text-align:center'>"
            f"<div style='font-size:28px;font-weight:700;color:#374151'>{n_nodes}</div>"
            f"<div style='font-size:12px;color:#6b7280'>Groepen</div></div></div>"
            f"<h2>Bevindingen</h2>"
            f"{sections if sections else '<p style="color:#22c55e">Geen overtredingen of aanbevelingen.</p>'}"
            f"<h2>Groepenoverzicht</h2>"
            f"<table style='width:100%;border-collapse:collapse'>"
            f"<thead><tr style='background:#f9fafb'>"
            f"<th style='padding:8px;text-align:left'>Naam</th>"
            f"<th style='padding:8px;text-align:left'>Type</th>"
            f"<th style='padding:8px;text-align:left'>Fase</th>"
            f"<th style='padding:8px;text-align:left'>Ruimtes</th></tr></thead>"
            f"<tbody>{node_rows}</tbody></table>"
            f"</body></html>"
        )

    @classmethod
    def to_markdown(cls, panel_status: dict) -> str:
        """Compacte markdown versie van NEN1010 bevindingen."""
        findings = panel_status.get("nen1010_findings", [])
        lines    = ["# NEN1010 Bevindingen\n"]
        for sev in ("red", "orange", "yellow"):
            items = [f for f in findings if f["severity"] == sev]
            if not items:
                continue
            icon = {"red": "🔴", "orange": "🟠", "yellow": "🟡"}[sev]
            lines.append(f"## {icon} {sev.capitalize()}")
            for f in items:
                lines.append(f"- **{f['message']}** ({f['code']})")
                lines.append(f"  {f['detail']}")
        return "\n".join(lines) if len(lines) > 1 else "✅ Geen bevindingen."

    def generate(
        self,
        panel       : "CircuitBreakerPanel",
        address     : str = "",
        nilm_devices: Optional[List[dict]] = None,
        extra_info  : str = "",
    ) -> str:
        import datetime as _dt

        findings  = panel.check_nen1010(nilm_devices)
        red_f     = [f for f in findings if f.severity == "red"]
        orange_f  = [f for f in findings if f.severity == "orange"]
        yellow_f  = [f for f in findings if f.severity == "yellow"]
        status_color = "#dc2626" if red_f else "#ea580c" if orange_f else "#ca8a04" if yellow_f else "#16a34a"
        status_text  = (f"{len(red_f)} overtreding(en)" if red_f
                        else f"{len(orange_f)} aanbeveling(en)" if orange_f
                        else f"{len(yellow_f)} adviespunt(en)" if yellow_f
                        else "Volledig conform")

        date_str = _dt.datetime.now().strftime("%d-%m-%Y %H:%M")
        nodes    = panel.get_all_sorted()

        findings_html = ""
        for sev in ("red", "orange", "yellow", "green"):
            sev_findings = [f for f in findings if f.severity == sev]
            if not sev_findings and sev == "green":
                continue
            label, color, bg = self.SEVERITY_LABELS[sev]
            rows = "".join(
                f"""<tr>
                  <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600">{f.message}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280">{f.detail}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#9ca3af;font-family:monospace;font-size:12px">{f.code}</td>
                </tr>"""
                for f in sev_findings
            ) if sev_findings else f"""<tr><td colspan="3" style="padding:8px 12px;color:#9ca3af">Geen bevindingen</td></tr>"""

            findings_html += f"""
            <div style="margin-bottom:20px">
              <div style="background:{bg};border-left:4px solid {color};padding:8px 14px;
                          font-weight:700;color:{color};margin-bottom:0">
                {label} ({len(sev_findings)})
              </div>
              <table style="width:100%;border-collapse:collapse;background:#fff;font-size:13px">
                <thead><tr style="background:#f9fafb">
                  <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;width:35%">Bevinding</th>
                  <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Toelichting</th>
                  <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;width:15%">Code</th>
                </tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </div>"""

        tree_html = self._render_tree_html(nodes, panel)

        return f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NEN1010 Groepenkast Rapport</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           font-size: 14px; color: #111827; margin: 0; padding: 0; background: #f3f4f6; }}
    .page {{ max-width: 900px; margin: 0 auto; background: #fff; padding: 40px;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    h1 {{ font-size: 22px; margin: 0 0 4px; }}
    h2 {{ font-size: 16px; margin: 24px 0 10px; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
    .meta {{ color: #6b7280; font-size: 12px; margin-bottom: 24px; }}
    .status-box {{ padding: 14px 18px; border-radius: 6px;
                   border-left: 5px solid {status_color}; background: #f9fafb;
                   margin-bottom: 24px; }}
    .status-title {{ font-size: 18px; font-weight: 700; color: {status_color}; }}
    .tree-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .tree-table th {{ background: #f9fafb; padding: 6px 10px; text-align: left;
                      border-bottom: 2px solid #e5e7eb; }}
    .tree-table td {{ padding: 5px 10px; border-bottom: 1px solid #f3f4f6; }}
    .tree-indent {{ display: inline-block; }}
    .badge {{ display: inline-block; padding: 1px 7px; border-radius: 10px;
              font-size: 11px; font-weight: 600; }}
    .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb;
               color: #9ca3af; font-size: 11px; }}
    @media print {{ body {{ background: #fff; }} .page {{ box-shadow: none; }} }}
  </style>
</head>
<body>
<div class="page">
  <h1>⚡ Groepenkast NEN1010 Rapport</h1>
  <div class="meta">
    {f"Adres: <strong>{address}</strong> · " if address else ""}
    Gegenereerd door CloudEMS op {date_str}
    {f" · {extra_info}" if extra_info else ""}
  </div>

  <div class="status-box">
    <div class="status-title">{status_text}</div>
    <div style="color:#6b7280;margin-top:4px">
      {len(findings)} bevinding(en) totaal ·
      {len(red_f)} overtreding(en) ·
      {len(orange_f)} aanbeveling(en) ·
      {len(yellow_f)} adviespunt(en) ·
      {len(nodes)} groepen geanalyseerd
    </div>
  </div>

  <h2>Bevindingen</h2>
  {findings_html}

  <h2>Kastoverzicht</h2>
  <table class="tree-table">
    <thead><tr>
      <th>Naam</th><th>Type</th><th>A</th><th>Fase</th>
      <th>Apparaten</th><th>Ruimtes</th><th>Zekerheid</th>
    </tr></thead>
    <tbody>{tree_html}</tbody>
  </table>

  <div class="footer">
    Dit rapport is gegenereerd door CloudEMS op basis van gemeten en geleerde data.
    Aanbevelingen zijn indicatief. Laat aanpassingen uitvoeren door een erkend installateur.
    NEN1010: Nederlandse norm voor elektrische installaties in gebouwen.
  </div>
</div>
</body>
</html>"""

    def _render_tree_html(self, nodes: list, panel: "CircuitBreakerPanel") -> str:
        def render_node(node, depth: int) -> str:
            indent  = "&nbsp;" * (depth * 4)
            icon    = {"main":"⚡","rcd":"🛡","rcbo":"🔒","mcb":"▶","mcb_3f":"⚡⚡","submeter":"📊"}.get(
                       getattr(node,"node_type","mcb"), "▶")
            ampere  = str(getattr(node,"ampere","")) + "A" if getattr(node,"ampere",None) else "—"
            phase   = getattr(node,"phase","") or "—"
            devices = str(len(node.linked_devices)) if node.linked_devices else "0"
            rooms   = ", ".join(node.linked_rooms) if node.linked_rooms else "—"
            conf    = f"{round(node.confidence*100)}%" if node.confidence > 0 else "—"
            bg      = "#fff" if depth % 2 == 0 else "#f9fafb"
            row = (f'<tr style="background:{bg}">'
                   f'<td><span class="tree-indent">{indent}</span>{icon} {node.name}</td>'
                   f'<td><span class="badge" style="background:#f3f4f6">{getattr(node,"node_type","?").upper()}</span></td>'
                   f'<td>{ampere}</td><td>{phase}</td>'
                   f'<td>{devices}</td><td>{rooms}</td><td>{conf}</td>'
                   f'</tr>')
            children_rows = "".join(
                render_node(c, depth + 1) for c in panel.get_children(node.id)
            )
            return row + children_rows

        roots = panel.get_roots()
        return "".join(render_node(r, 0) for r in roots)


