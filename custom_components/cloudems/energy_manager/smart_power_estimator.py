# -*- coding: utf-8 -*-
"""
CloudEMS Smart Power Estimator -- v2.1.0

Nul-configuratie vermogensschatting per HA-entiteit, zelflerend via NILM.

ARCHITECTUUR (lagen, hoge naar lage prioriteit)
================================================
1  NILM-geleerd      -- per-entiteit geleerde waarde via on/off-delta correlatie
2  PowerCalc lokaal  -- entity-registry lookup (platform=powercalc, zelfde device_id)
3  Remote database   -- cloudems.eu community-db (dagelijks sync via HA-sessie)
4  Ingebouwde db     -- ~300 profielen
5  Device-klasse     -- mediaan per domein/device_class
6  Domein-fallback   -- light=8W, switch=50W, ...

NIEUW IN v2.1.0
================

[1] INFRA-FILTERING — grid/PV/omvormer/EV/batterij-sensoren worden NIET getrackt
    Drie filterlagen (gecombineerd):
      a. Config-gebaseerd : alle entity_ids die als infra geconfigureerd zijn
         (import/export/grid/solar/battery/EV/warmtepomp/boiler/fase-sensoren)
      b. Platform-gebaseerd : entiteiten van inverter-platforms (growatt, goodwe,
         solis, solaredge, fronius, huawei_solar, ...) worden overgeslagen
      c. Naam-gebaseerd : PHASE_EXCLUDE_KEYWORDS uit const.py — dezelfde lijst
         die al gebruikt wordt voor de fase/gridpool-filtering

[2] MULTI-DIMENSIONAAL CONFIDENCE MODEL
    combined = source_score*0.30 + confirmation_score*0.45 + consistency_score*0.25
    PowerCalc-meting zonder NILM → direct MEDIUM
    PowerCalc + 1 NILM-bevestiging (< 15% verschil) → direct HIGH

[3] STANDBY-VERBRUIK ZELFLEREND
    Als PowerCalc een waarde rapporteert terwijl de entiteit 'off' is,
    wordt dat via EWMA bijgehouden als standby_w. Die offset gaat ook naar
    NILM als constante last.

[4] POWERCALC-STABILITEITS-BONUS
    Na 10 consistente PC-metingen (spreiding < 5%) groeit confirmation_score
    met een bonus — stabiele apparaten bereiken sneller HIGH zonder NILM.

[5] USER FEEDBACK KOPPELING
    notify_feedback(entity_id, "correct"|"incorrect") → update confidence:
      correct   → consistency_score=1.0, +3 sessies
      incorrect → reset naar UNKNOWN

[6] COMMUNITY UPLOAD
    Als een entiteit HIGH bereikt én merk/model bekend is, wordt een anoniem
    profiel aangeboden aan cloudems.eu via async_contribute_profile().

[7] VERBETERDE SENSOR ATTRS
    confidence_score, source_score, consistency_score, confirmation_score
    zijn nu zichtbaar in extra_state_attributes van de HA-sensor.

Copyright (c) 2025 CloudEMS -- https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .powercalc_engine import PowerCalcEngine, PowerProfile
from .powercalc_profiles import ProfileDatabase

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_smart_power_estimator_v2"
STORAGE_VERSION = 2

DISCOVERY_INTERVAL_S    = 900
REMOTE_SYNC_INTERVAL_S  = 86_400
EWMA_ALPHA              = 0.15
EWMA_ALPHA_FAST         = 0.30
MATCH_TOLERANCE         = 0.35
MATCH_WINDOW_S          = 8.0
DELTA_BUFFER_MAXAGE_S   = 30.0
MIN_DELTA_W             = 5.0
PC_CONSISTENCY_INTERVAL_S = 60.0
PC_HISTORY_SIZE         = 10
PC_STABILITY_MIN_N      = 10      # metingen nodig voor stabilitets-bonus
PC_STABILITY_CV_MAX     = 0.05    # max variatiecoëfficiënt (5%)
STANDBY_EWMA_ALPHA      = 0.10    # langzame EWMA voor standby-leren

W_SOURCE       = 0.30
W_CONFIRMATION = 0.45
W_CONSISTENCY  = 0.25
CONF_THRESHOLD_LOW    = 0.20
CONF_THRESHOLD_MEDIUM = 0.45
CONF_THRESHOLD_HIGH   = 0.72

SOURCE_SCORES: Dict[str, float] = {
    "domain_fallback": 0.10,
    "class_median":    0.20,
    "builtin":         0.35,
    "remote":          0.45,
    "powercalc_local": 0.70,
    "nilm_learned":    0.85,
    "unknown":         0.05,
}

TRACKED_DOMAINS = {
    "light", "switch", "fan", "media_player",
    "climate", "cover", "vacuum", "input_boolean",
}

# Platforms waarvan sensoren per definitie infra zijn (omvormers, meters, ...)
INFRA_PLATFORMS: Set[str] = {
    "growatt_server", "growatt", "goodwe", "solis", "solaredge", "fronius",
    "enphase_envoy", "huawei_solar", "deye", "sunsynk", "sofar", "sma",
    "dsmr", "homewizard", "slimmelezer", "p1_monitor", "iungo", "youless",
    "ecodevices", "tibber", "energyzero", "entsoe",
}

# Config-keys die infra entity_ids bevatten (enkelvoudig of lijst)
_INFRA_CONFIG_KEYS_SINGLE = [
    "import_power_sensor", "export_power_sensor", "grid_sensor",
    "solar_sensor", "battery_sensor", "ev_charger_entity",
    "battery_charge_entity", "battery_discharge_entity", "battery_soc_entity",
    "heat_pump_power_entity", "heat_pump_thermal_entity",
    "cv_boiler_entity", "boiler_power_entity",
    "inverter_control_entity",
]
_INFRA_CONFIG_KEYS_LIST = [
    "phase_sensors",  # list van entity_ids
]
_INFRA_CONFIG_KEYS_DICTLIST = [
    "inverter_configs",  # list van dicts, elk met "power_sensor" o.i.d.
]

# Naam-keywords voor infra-filtering (uitbreiding van PHASE_EXCLUDE_KEYWORDS)
_INFRA_NAME_KEYWORDS: Set[str] = {
    "solar", "pv", "zon", "inverter", "omvormer", "battery", "batterij",
    "accu", "batt", "storage", "ev", "charger", "laadpaal", "yield",
    "feedin", "feed_in", "clipping", "forecast", "predicted", "estimated",
    "on_grid", "goodwe", "growatt", "solis", "solaredge", "fronius",
    "enphase", "huawei_solar", "deye", "sunsynk", "sofar", "sma_",
    "output_power", "ac_power", "grid_power", "meter", "energiemeter",
    "energieverbruik", "electricit", "verbruik_huidig", "cloudems",
    "import", "export", "net_power", "teruglevering",
}

COMMUNITY_UPLOAD_URL = "https://cloudems.eu/powercalc/community-v1"


# ── Hulpfuncties confidence model ────────────────────────────────────────────

class Confidence(str, Enum):
    UNKNOWN = "unknown"
    LOW     = "low"
    MEDIUM  = "medium"
    HIGH    = "high"


def _conf_from_score(score: float) -> Confidence:
    if score >= CONF_THRESHOLD_HIGH:   return Confidence.HIGH
    if score >= CONF_THRESHOLD_MEDIUM: return Confidence.MEDIUM
    if score >= CONF_THRESHOLD_LOW:    return Confidence.LOW
    return Confidence.UNKNOWN


def _confirmation_score(n: int) -> float:
    """Niet-lineaire groeicurve: 1→0.20, 2→0.45, 5→0.80, 10→1.00."""
    return round(min(1.0, 1.0 - math.exp(-0.28 * n)), 3) if n > 0 else 0.0


def _consistency_score(pc_w: Optional[float], ref_w: float) -> float:
    """Overeenkomst PowerCalc-meting vs referentiewaarde (0.50 = neutraal)."""
    if pc_w is None or pc_w <= 0 or ref_w < MIN_DELTA_W:
        return 0.50
    ratio = abs(pc_w - ref_w) / max(ref_w, 1.0)
    if ratio < 0.10: return 1.00
    if ratio < 0.25: return 0.80
    if ratio < 0.50: return 0.55
    return 0.20


# ── EntityPowerState ─────────────────────────────────────────────────────────

@dataclass
class EntityPowerState:
    """Vermogensstatus per HA-entiteit."""
    entity_id:    str
    domain:       str
    manufacturer: str = ""
    model:        str = ""
    device_class: str = ""

    estimated_w:  float = 0.0
    standby_w:    float = 0.0       # geleerd stand-by verbruik

    confidence:          Confidence = Confidence.UNKNOWN
    confidence_score:    float = 0.0
    source_score:        float = 0.05
    confirmation_score:  float = 0.0
    consistency_score:   float = 0.50

    confirmed_sessions:  int   = 0
    last_state:          str   = ""
    last_change_ts:      float = 0.0
    learned_w:           float = 0.0
    source:              str   = "unknown"

    pc_readings:         List[float] = field(default_factory=list)
    pc_last_reading_ts:  float = 0.0
    pc_mean_w:           float = 0.0
    pc_stability_bonus:  float = 0.0    # bonus op basis van meetstabiliteit

    # Community upload tracking
    _contributed:        bool  = field(default=False, repr=False)

    def _recompute_confidence(self) -> None:
        combined = (
            self.source_score       * W_SOURCE
            + self.confirmation_score * W_CONFIRMATION
            + self.consistency_score  * W_CONSISTENCY
        )
        self.confidence_score = round(min(combined + self.pc_stability_bonus, 1.0), 3)
        self.confidence       = _conf_from_score(self.confidence_score)

    def update_source(self, source: str) -> None:
        self.source       = source
        self.source_score = SOURCE_SCORES.get(source, 0.05)
        self._recompute_confidence()

    def update_learned(self, delta_w: float) -> None:
        """Verwerk een NILM-bevestiging."""
        if self.learned_w == 0.0:
            self.learned_w = delta_w
        else:
            alpha = (EWMA_ALPHA_FAST
                     if abs(delta_w - self.learned_w) / max(self.learned_w, 1) > 0.5
                     else EWMA_ALPHA)
            self.learned_w = round(self.learned_w * (1 - alpha) + delta_w * alpha, 1)

        self.confirmed_sessions += 1
        self.estimated_w         = self.learned_w
        self.source_score        = SOURCE_SCORES["nilm_learned"]
        self.source              = "nilm_learned"
        self.confirmation_score  = _confirmation_score(self.confirmed_sessions)

        pc_ref = self.pc_mean_w if self.pc_mean_w > 0 else None
        self.consistency_score = _consistency_score(pc_ref, self.learned_w)
        self._recompute_confidence()

    def record_powercalc_reading(self, pc_w: float, is_off: bool = False) -> None:
        """Verwerk een nieuwe PowerCalc live-meting.

        Als de entiteit UIT is (is_off=True) → bijhouden als standby_w.
        Anders → consistency check + source/confidence update.
        """
        now = time.time()
        if now - self.pc_last_reading_ts < PC_CONSISTENCY_INTERVAL_S:
            return
        self.pc_last_reading_ts = now

        if is_off:
            # [3] Standby-verbruik zelflerend
            if pc_w > 0.1:
                if self.standby_w == 0.0:
                    self.standby_w = round(pc_w, 2)
                else:
                    self.standby_w = round(
                        self.standby_w * (1 - STANDBY_EWMA_ALPHA) + pc_w * STANDBY_EWMA_ALPHA, 2
                    )
            return

        # EWMA van actieve PowerCalc-metingen
        if self.pc_mean_w == 0.0:
            self.pc_mean_w = pc_w
        else:
            self.pc_mean_w = round(self.pc_mean_w * 0.8 + pc_w * 0.2, 1)

        self.pc_readings.append(round(pc_w, 1))
        if len(self.pc_readings) > PC_HISTORY_SIZE:
            self.pc_readings.pop(0)

        # [4] Stabiliteits-bonus als spreiding klein is
        if len(self.pc_readings) >= PC_STABILITY_MIN_N:
            mean = sum(self.pc_readings) / len(self.pc_readings)
            if mean > 0:
                cv = (sum((x - mean) ** 2 for x in self.pc_readings) / len(self.pc_readings)) ** 0.5 / mean
                self.pc_stability_bonus = 0.08 if cv <= PC_STABILITY_CV_MAX else 0.0

        if self.source not in ("nilm_learned",):
            self.source       = "powercalc_local"
            self.source_score = SOURCE_SCORES["powercalc_local"]
            self.estimated_w  = round(pc_w, 1)

        ref_w = self.learned_w if self.learned_w > MIN_DELTA_W else self.estimated_w
        self.consistency_score = _consistency_score(pc_w, ref_w)
        self._recompute_confidence()

    def apply_feedback(self, correct: bool) -> None:
        """[5] Verwerk user feedback van NILMDetector."""
        if correct:
            self.consistency_score  = 1.0
            self.confirmed_sessions += 3
            self.confirmation_score  = _confirmation_score(self.confirmed_sessions)
        else:
            # Reset naar onbekend
            self.learned_w          = 0.0
            self.confirmed_sessions  = 0
            self.confirmation_score  = 0.0
            self.consistency_score   = 0.50
            self.pc_stability_bonus  = 0.0
            self.source              = "unknown"
            self.source_score        = SOURCE_SCORES["unknown"]
        self._recompute_confidence()

    def needs_community_upload(self) -> bool:
        """True als dit profiel klaar is om bij te dragen aan de community."""
        return (
            not self._contributed
            and self.confidence == Confidence.HIGH
            and bool(self.manufacturer)
            and bool(self.model)
            and self.learned_w > MIN_DELTA_W
        )

    def to_dict(self) -> dict:
        return {
            "entity_id":          self.entity_id,
            "domain":             self.domain,
            "manufacturer":       self.manufacturer,
            "model":              self.model,
            "device_class":       self.device_class,
            "estimated_w":        self.estimated_w,
            "standby_w":          self.standby_w,
            "confidence":         self.confidence.value,
            "confidence_score":   self.confidence_score,
            "source_score":       self.source_score,
            "confirmation_score": self.confirmation_score,
            "consistency_score":  self.consistency_score,
            "pc_stability_bonus": self.pc_stability_bonus,
            "confirmed_sessions": self.confirmed_sessions,
            "learned_w":          self.learned_w,
            "source":             self.source,
            "pc_mean_w":          self.pc_mean_w,
            "pc_readings":        self.pc_readings[-4:],
            "contributed":        self._contributed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EntityPowerState":
        s = cls(entity_id=d["entity_id"], domain=d.get("domain", ""))
        s.manufacturer        = d.get("manufacturer", "")
        s.model               = d.get("model", "")
        s.device_class        = d.get("device_class", "")
        s.estimated_w         = float(d.get("estimated_w", 0))
        s.standby_w           = float(d.get("standby_w", 0))
        s.confidence          = Confidence(d.get("confidence", "unknown"))
        s.confidence_score    = float(d.get("confidence_score", 0))
        s.source_score        = float(d.get("source_score", 0.05))
        s.confirmation_score  = float(d.get("confirmation_score", 0))
        s.consistency_score   = float(d.get("consistency_score", 0.50))
        s.pc_stability_bonus  = float(d.get("pc_stability_bonus", 0))
        s.confirmed_sessions  = int(d.get("confirmed_sessions", 0))
        s.learned_w           = float(d.get("learned_w", 0))
        s.source              = d.get("source", "unknown")
        s.pc_mean_w           = float(d.get("pc_mean_w", 0))
        s.pc_readings         = list(d.get("pc_readings", []))
        s._contributed        = bool(d.get("contributed", False))
        return s


# ── SmartPowerEstimator ───────────────────────────────────────────────────────

class SmartPowerEstimator:
    """
    Centrale power-estimator voor CloudEMS.

    Gebruik:
        estimator = SmartPowerEstimator(hass)
        await estimator.async_setup(store, nilm_detector, config)
        estimator.tick()
        nilm.set_infra_powers(estimator.get_infra_powers())
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass    = hass
        self._engine  = PowerCalcEngine()
        self._db      = ProfileDatabase()
        self._states: Dict[str, EntityPowerState] = {}
        self._store:  Optional[Store] = None
        self._nilm    = None
        self._config: Dict[str, Any] = {}

        self._delta_buffer: Deque[Tuple[float, float]] = deque(maxlen=200)

        self._last_discovery:   float = 0.0
        self._last_remote_sync: float = 0.0
        self._last_pc_scan:     float = 0.0

        self._unsub_state:   Optional[Callable] = None
        self._powercalc_available: Optional[bool] = None
        self._powercalc_sensor_cache: Dict[str, Optional[str]] = {}

        # [1] Gecombineerde set van bekende infra entity_ids
        self._infra_entity_ids: Set[str] = set()

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self, store: Store, nilm=None, config: dict = None) -> None:
        self._store  = store
        self._nilm   = nilm
        self._config = config or {}

        # [1] Bouw infra-filter op basis van config
        self._build_infra_filter()

        await self._async_load()
        # Verwijder al geladen infra-entities uit de state
        purged = [e for e in list(self._states) if self._is_infra(e)]
        for eid in purged:
            del self._states[eid]
        if purged:
            _LOGGER.info(
                "SmartPowerEstimator: %d infra-entiteiten uit opgeslagen state verwijderd: %s",
                len(purged), purged[:5],
            )

        await self._async_discover()
        await self._async_sync_remote()

        if nilm is not None and hasattr(nilm, "register_event_hook"):
            nilm.register_event_hook(self._on_nilm_event)
        else:
            _LOGGER.warning(
                "SmartPowerEstimator: NILMDetector heeft geen register_event_hook — "
                "update NILMDetector naar v1.32+."
            )

        self._unsub_state = self._hass.bus.async_listen(
            "state_changed", self._on_state_changed
        )
        _LOGGER.info(
            "SmartPowerEstimator v2.1 klaar — %d profielen, %d entiteiten, "
            "%d infra gefilterd",
            self._db.total_profiles, len(self._states), len(self._infra_entity_ids),
        )

    async def async_stop(self) -> None:
        if self._unsub_state:
            self._unsub_state()
        if self._nilm is not None and hasattr(self._nilm, "unregister_event_hook"):
            self._nilm.unregister_event_hook(self._on_nilm_event)
        await self._async_save()

    # ── [1] Infra-filter ──────────────────────────────────────────────────────

    def _build_infra_filter(self) -> None:
        """Bouw _infra_entity_ids op basis van de CloudEMS config."""
        ids: Set[str] = set()
        cfg = self._config

        # Enkelvoudige entity_id keys
        for key in _INFRA_CONFIG_KEYS_SINGLE:
            val = cfg.get(key)
            if isinstance(val, str) and val:
                ids.add(val)

        # Lijst van entity_ids
        for key in _INFRA_CONFIG_KEYS_LIST:
            val = cfg.get(key, [])
            if isinstance(val, (list, tuple)):
                for v in val:
                    if isinstance(v, str) and v:
                        ids.add(v)

        # Lijst van dicts (inverter_configs)
        for key in _INFRA_CONFIG_KEYS_DICTLIST:
            val = cfg.get(key, [])
            if isinstance(val, (list, tuple)):
                for item in val:
                    if isinstance(item, dict):
                        for sub_key in ("power_sensor", "sensor", "entity_id", "control_entity"):
                            sv = item.get(sub_key)
                            if isinstance(sv, str) and sv:
                                ids.add(sv)

        self._infra_entity_ids = ids
        _LOGGER.debug(
            "SmartPowerEstimator: infra-filter gebouwd — %d config-entiteiten", len(ids)
        )

    def _is_infra(self, entity_id: str) -> bool:
        """Geeft True als deze entiteit infra is en NIET getrackt moet worden."""
        # 1. Directe config-match
        if entity_id in self._infra_entity_ids:
            return True

        # 2. Platform-check via entity registry
        try:
            ent_reg = er.async_get(self._hass)
            entry   = ent_reg.async_get(entity_id)
            if entry and entry.platform and entry.platform.lower() in INFRA_PLATFORMS:
                return True
        except Exception:
            pass

        # 3. Naam-keyword check (entity_id in lowercase)
        eid_lower = entity_id.lower()
        for kw in _INFRA_NAME_KEYWORDS:
            if kw in eid_lower:
                return True

        return False

    def refresh_infra_filter(self, config: dict) -> None:
        """Herlaad de infra-filter na een config-update (options flow)."""
        self._config = config
        self._build_infra_filter()
        # Verwijder nieuw-infra entities uit tracking
        purged = [e for e in list(self._states) if self._is_infra(e)]
        for eid in purged:
            del self._states[eid]
        _LOGGER.info(
            "SmartPowerEstimator: infra-filter herladen — %d entiteiten verwijderd", len(purged)
        )

    # ── Publieke API ──────────────────────────────────────────────────────────

    def tick(self) -> None:
        now = time.time()
        if now - self._last_discovery > DISCOVERY_INTERVAL_S:
            asyncio.ensure_future(self._async_discover())
            self._last_discovery = now
        if now - self._last_remote_sync > REMOTE_SYNC_INTERVAL_S:
            asyncio.ensure_future(self._async_sync_remote())
        if self._powercalc_available and now - self._last_pc_scan > PC_CONSISTENCY_INTERVAL_S:
            self._scan_powercalc_readings()
            self._last_pc_scan = now

    def get_power(self, entity_id: str) -> float:
        s = self._states.get(entity_id)
        if not s:
            return 0.0
        ha_state = self._hass.states.get(entity_id)
        if not ha_state:
            return 0.0
        return self._compute(s, ha_state.state, dict(ha_state.attributes))

    def get_infra_powers(self) -> Dict[str, float]:
        """HIGH-confidence entiteiten als infra-powers dict voor NILMDetector.
        Inclusief geleerd standby-verbruik als constante offset.
        """
        result: Dict[str, float] = {}
        for eid, s in self._states.items():
            if s.confidence != Confidence.HIGH:
                continue
            pw = self.get_power(eid)
            if pw > MIN_DELTA_W:
                result[eid.replace(".", "_")] = pw
            # Standby als separate offset-entry
            if s.standby_w > 0.5:
                result[eid.replace(".", "_") + "_standby"] = s.standby_w
        return result

    def get_all_states(self) -> List[dict]:
        return [s.to_dict() for s in sorted(
            self._states.values(), key=lambda x: x.estimated_w, reverse=True
        )]

    def get_stats(self) -> dict:
        total   = len(self._states)
        by_conf = {c.value: 0 for c in Confidence}
        by_src  = {}
        for s in self._states.values():
            by_conf[s.confidence.value] += 1
            by_src[s.source] = by_src.get(s.source, 0) + 1
        return {
            "total_entities":      total,
            "by_confidence":       by_conf,
            "by_source":           by_src,
            "profiles_builtin":    len(self._db._builtin),
            "profiles_remote":     len(self._db._remote),
            "powercalc_available": self._powercalc_available,
            "delta_buffer_size":   len(self._delta_buffer),
            "infra_filtered":      len(self._infra_entity_ids),
            "remote_sync_age_h":   round(
                (time.time() - self._last_remote_sync) / 3600, 1
            ) if self._last_remote_sync else None,
        }

    # ── [5] User feedback koppeling ───────────────────────────────────────────

    def notify_feedback(self, entity_id: str, correct: bool) -> None:
        """Verwerk user feedback vanuit NILMDetector/coordinator."""
        s = self._states.get(entity_id)
        if not s:
            return
        old = s.confidence
        s.apply_feedback(correct)
        _LOGGER.debug(
            "SmartPowerEstimator: feedback %s voor %s — conf %s → %s",
            "correct" if correct else "incorrect",
            entity_id, old.value, s.confidence.value,
        )
        asyncio.ensure_future(self._async_save())

    # ── NILM event-hook ───────────────────────────────────────────────────────

    def _on_nilm_event(self, delta_w: float, timestamp: float) -> None:
        cutoff = timestamp - DELTA_BUFFER_MAXAGE_S
        while self._delta_buffer and self._delta_buffer[0][0] < cutoff:
            self._delta_buffer.popleft()
        self._delta_buffer.append((timestamp, delta_w))

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def _async_discover(self) -> None:
        self._last_discovery = time.time()

        if self._powercalc_available is None:
            self._powercalc_available = "powercalc" in self._hass.config.components

        ent_reg = er.async_get(self._hass)
        dev_reg = dr.async_get(self._hass)
        new = skipped = 0

        for state in self._hass.states.async_all():
            eid    = state.entity_id
            domain = eid.split(".")[0]
            if domain not in TRACKED_DOMAINS:
                continue
            if eid in self._states:
                continue

            # [1] Infra-filter toepassen
            if self._is_infra(eid):
                skipped += 1
                continue

            mfr, model = "", ""
            entry = ent_reg.async_get(eid)
            if entry and entry.device_id:
                dev = dev_reg.async_get(entry.device_id)
                if dev:
                    mfr   = (dev.manufacturer or "").strip()
                    model = (dev.model or "").strip()

            s = EntityPowerState(
                entity_id=eid, domain=domain,
                manufacturer=mfr, model=model,
                device_class=state.attributes.get("device_class", ""),
            )
            self._bootstrap_profile(s, state.state, dict(state.attributes))
            self._states[eid] = s
            new += 1

        if new or skipped:
            _LOGGER.debug(
                "SmartPowerEstimator discovery: %d nieuw, %d infra overgeslagen",
                new, skipped,
            )
            if new:
                await self._async_save()

    # ── Remote sync ───────────────────────────────────────────────────────────

    async def _async_sync_remote(self) -> None:
        try:
            session = async_get_clientsession(self._hass)
            await self._db.async_sync_remote(session)
            self._last_remote_sync = time.time()
        except Exception as ex:
            _LOGGER.debug("SmartPowerEstimator: remote sync mislukt: %s", ex)

    # ── [6] Community upload ──────────────────────────────────────────────────

    async def async_contribute_profile(self, s: EntityPowerState) -> None:
        """Upload een anoniem verifiëerd profiel naar cloudems.eu."""
        if not s.needs_community_upload():
            return
        try:
            session = async_get_clientsession(self._hass)
            payload = {
                "manufacturer":  s.manufacturer,
                "model":         s.model,
                "device_type":   s.domain,
                "power_on_w":    round(s.learned_w, 1),
                "standby_w":     round(s.standby_w, 2),
                "source":        "cloudems_verified",
                "confidence":    round(s.confidence_score, 3),
                "n_sessions":    s.confirmed_sessions,
            }
            async with session.post(
                COMMUNITY_UPLOAD_URL, json=payload,
                timeout=__import__("aiohttp").ClientTimeout(total=5),
            ) as resp:
                if resp.status in (200, 201, 204):
                    s._contributed = True
                    _LOGGER.info(
                        "SmartPowerEstimator: community-profiel bijgedragen voor %s %s (%.0fW)",
                        s.manufacturer, s.model, s.learned_w,
                    )
        except Exception as ex:
            _LOGGER.debug("SmartPowerEstimator: community upload mislukt: %s", ex)

    # ── PowerCalc entity lookup ───────────────────────────────────────────────

    def _find_powercalc_sensor(self, entity_id: str) -> Optional[str]:
        if entity_id in self._powercalc_sensor_cache:
            return self._powercalc_sensor_cache[entity_id]
        result: Optional[str] = None
        try:
            ent_reg = er.async_get(self._hass)
            source  = ent_reg.async_get(entity_id)
            if source and source.device_id:
                best = None
                first = None
                for entry in ent_reg.entities.values():
                    if (entry.platform != "powercalc" or entry.domain != "sensor"
                            or entry.device_id != source.device_id or entry.disabled):
                        continue
                    if first is None:
                        first = entry.entity_id
                    uid  = (entry.unique_id or "").lower()
                    name = (entry.original_name or "").lower()
                    if "power" in uid or "power" in name or "_power" in entry.entity_id.lower():
                        best = entry.entity_id
                        break
                result = best or first
        except Exception as ex:
            _LOGGER.debug("PowerCalc lookup fout voor %s: %s", entity_id, ex)
        self._powercalc_sensor_cache[entity_id] = result
        return result

    # ── Periodieke PowerCalc scan ─────────────────────────────────────────────

    def _scan_powercalc_readings(self) -> None:
        """Lees live PowerCalc-metingen, update consistency + standby."""
        updated = 0
        for eid, s in self._states.items():
            pc_eid = self._find_powercalc_sensor(eid)
            if not pc_eid:
                continue
            pc_state  = self._hass.states.get(pc_eid)
            ha_state  = self._hass.states.get(eid)
            if not pc_state or pc_state.state in ("unavailable", "unknown", ""):
                continue
            try:
                pc_w   = float(pc_state.state)
                is_off = (ha_state and ha_state.state in
                          ("off", "0", "false", "unavailable", "unknown"))
                old_conf = s.confidence
                s.record_powercalc_reading(pc_w, is_off=bool(is_off))
                if s.confidence != old_conf:
                    _LOGGER.debug(
                        "SmartPowerEstimator: %s conf %s→%s (PC=%.0fW score=%.2f)",
                        eid, old_conf.value, s.confidence.value,
                        pc_w, s.confidence_score,
                    )
                    updated += 1
                    # [6] Check community upload als HIGH bereikt
                    if s.confidence == Confidence.HIGH and s.needs_community_upload():
                        asyncio.ensure_future(self.async_contribute_profile(s))
            except (ValueError, TypeError):
                pass
        if updated:
            asyncio.ensure_future(self._async_save())

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def _bootstrap_profile(self, s: EntityPowerState, state: str, attrs: Dict) -> None:
        if self._powercalc_available:
            pc_eid = self._find_powercalc_sensor(s.entity_id)
            if pc_eid:
                pc_state = self._hass.states.get(pc_eid)
                if pc_state and pc_state.state not in ("unavailable", "unknown", ""):
                    try:
                        pc_w = float(pc_state.state)
                        if pc_w >= 0:
                            s.estimated_w = round(pc_w, 1)
                            s.update_source("powercalc_local")
                            s.record_powercalc_reading(pc_w)
                            return
                    except (ValueError, TypeError):
                        pass

        profile: Optional[PowerProfile] = None
        if s.manufacturer and s.model:
            profile = self._db.get(s.manufacturer, s.model)
        if profile:
            s.estimated_w = self._compute_from_profile(profile, state, attrs)
            s.standby_w   = profile.standby_w
            s.update_source(profile.source)
            return

        fallback = self._db.fallback_watt(s.domain, s.device_class or None)
        if fallback > 0:
            s.estimated_w = fallback
            s.update_source("class_median")
            return

        s.estimated_w = {"light": 8.0, "switch": 50.0, "fan": 40.0,
                         "media_player": 25.0, "climate": 800.0,
                         "cover": 30.0, "vacuum": 20.0}.get(s.domain, 0.0)
        s.update_source("domain_fallback")

    # ── State change handler ──────────────────────────────────────────────────

    @callback
    def _on_state_changed(self, event) -> None:
        eid       = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state or eid not in self._states:
            return

        s      = self._states[eid]
        new_st = new_state.state
        old_st = old_state.state if old_state else ""

        was_on = old_st not in ("off", "0", "false", "unavailable", "unknown")
        is_on  = new_st not in ("off", "0", "false", "unavailable", "unknown")

        if was_on != is_on:
            self._try_correlate(s, is_on, dict(new_state.attributes), time.time())

        s.last_state     = new_st
        s.last_change_ts = time.time()

    # ── NILM-correlatie ───────────────────────────────────────────────────────

    def _try_correlate(self, s: EntityPowerState, turned_on: bool,
                       attrs: dict, change_ts: float) -> None:
        if not self._delta_buffer:
            return
        expected_w = s.estimated_w if s.estimated_w > MIN_DELTA_W else max(s.standby_w, MIN_DELTA_W)
        cutoff     = change_ts - MATCH_WINDOW_S
        best_match: Optional[float] = None
        best_score: float = float("inf")

        for ts, delta_w in reversed(self._delta_buffer):
            if ts < cutoff:
                break
            abs_delta = abs(delta_w)
            if abs_delta < MIN_DELTA_W:
                continue
            if turned_on and delta_w < 0:
                continue
            if not turned_on and delta_w > 0:
                continue
            ratio = abs_delta / max(expected_w, 1.0)
            if (1.0 - MATCH_TOLERANCE) <= ratio <= (1.0 + MATCH_TOLERANCE):
                score = abs(ratio - 1.0)
                if score < best_score:
                    best_score = score
                    best_match = abs_delta

        if best_match is None:
            return

        old_conf = s.confidence
        s.update_learned(best_match)
        _LOGGER.debug(
            "SmartPowerEstimator: %s bevestigd %.0fW (sessies=%d conf=%s→%s score=%.2f)",
            s.entity_id, best_match, s.confirmed_sessions,
            old_conf.value, s.confidence.value, s.confidence_score,
        )
        if s.confidence == Confidence.HIGH and self._nilm is not None:
            self._nilm.set_infra_powers(self.get_infra_powers())
        if s.needs_community_upload():
            asyncio.ensure_future(self.async_contribute_profile(s))
        asyncio.ensure_future(self._async_save())

    # ── Berekening ────────────────────────────────────────────────────────────

    def _compute(self, s: EntityPowerState, state: str, attrs: Dict) -> float:
        if s.learned_w > 0 and s.confidence in (Confidence.MEDIUM, Confidence.HIGH):
            if s.domain == "light" and "brightness" in attrs:
                return round(s.learned_w * float(attrs["brightness"]) / 255.0, 1)
            return s.learned_w
        if self._powercalc_available:
            pc_eid = self._find_powercalc_sensor(s.entity_id)
            if pc_eid:
                pc_state = self._hass.states.get(pc_eid)
                if pc_state and pc_state.state not in ("unavailable", "unknown", ""):
                    try:
                        return round(float(pc_state.state), 1)
                    except (ValueError, TypeError):
                        pass
        if s.manufacturer and s.model:
            profile = self._db.get(s.manufacturer, s.model)
            if profile:
                return self._compute_from_profile(profile, state, attrs)
        return s.estimated_w

    def _compute_from_profile(self, profile: PowerProfile, state: str, attrs: Dict) -> float:
        return self._engine.calculate(profile, state, attrs)

    # ── Persistentie ──────────────────────────────────────────────────────────

    async def _async_load(self) -> None:
        if not self._store:
            return
        data = await self._store.async_load() or {}
        for d in data.get("entities", []):
            try:
                s = EntityPowerState.from_dict(d)
                self._states[s.entity_id] = s
            except Exception:
                pass
        _LOGGER.debug("SmartPowerEstimator: %d entiteiten geladen", len(self._states))

    async def _async_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "entities": [s.to_dict() for s in self._states.values()],
                "saved_at": time.time(),
                "version":  STORAGE_VERSION,
            })
        except Exception as ex:
            _LOGGER.debug("SmartPowerEstimator opslaan mislukt: %s", ex)
