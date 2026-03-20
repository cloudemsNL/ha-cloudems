# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
topology_consistency.py — v4.6.535

Uitbreiding op MeterTopologyLearner met drie validators:

1. TopologyConsistencyValidator
   Controleert of upstream ≥ sum(downstream) − tolerantie.
   Detecteert:
   - Tussenmeter meldt meer dan zijn upstream (teken-fout of verkeerde sensor)
   - Upstream nooit groter dan downstream (omgewisseld)
   - Som van downstream structureel hoger dan upstream (dubbeltellingsbron)

2. TopologyAutoFeeder
   Voedt de MeterTopologyLearner automatisch met alle bekende power-sensoren:
   - Smart-plugs via NILM confirmed-devices
   - Geconfigureerde boiler/EV/solar sensoren
   - Fase-sensoren
   - Room-meter sensoren
   Geen handmatige config van extra_meter_entities meer nodig.

3. NILMDoubleCountDetector
   Detecteert als twee sensoren in de NILM-som beiden in de approved topologie
   zitten als upstream/downstream paar → dubbeltellingswaarschuwing.

Alle drie werken samen via MeterTopologyLearner als gedeeld state-object.
Cloud-sync via CloudSyncMixin: anonieme topologie-statistieken.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .cloud_sync_mixin import CloudSyncMixin

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_topology_consistency_v1"
STORAGE_VERSION = 1

# Tolerantie-venster: upstream mag X% lager zijn door meting-timing
UPSTREAM_TOLERANCE_FRAC = 0.15   # 15%
MIN_POWER_W             = 100    # meet alleen boven 100W (ruis-filter)
EMA_ALPHA               = 0.08
MIN_SAMPLES             = 20
SAVE_INTERVAL           = 30

# Drempels voor classificatie
INVERSION_FRAC    = 0.85    # downstream > upstream × 0.85 → verdacht
SWAP_FRAC         = 0.90    # downstream > upstream × 0.90 → waarschijnlijk omgewisseld
OVERCOUNT_FRAC    = 0.20    # som_downstream > upstream × 1.20 → dubbeltelling


# ─────────────────────────────────────────────────────────────────────────────
# 1. TopologyConsistencyValidator
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RelationConsistency:
    """Consistentie-statistiek voor één upstream→downstream paar."""
    upstream_id:    str
    downstream_id:  str
    ema_ratio:      float = 0.5     # downstream / upstream EMA
    sample_count:   int   = 0
    classification: str   = "learning"
    confidence:     float = 0.0
    violations:     int   = 0       # keren dat downstream > upstream

    def to_dict(self) -> dict:
        return {
            "up":      self.upstream_id,
            "down":    self.downstream_id,
            "ratio":   round(self.ema_ratio, 3),
            "samples": self.sample_count,
            "class":   self.classification,
            "conf":    round(self.confidence, 3),
            "viol":    self.violations,
        }

    def from_dict(self, d: dict) -> None:
        self.ema_ratio      = float(d.get("ratio", 0.5))
        self.sample_count   = int(d.get("samples", 0))
        self.classification = d.get("class", "learning")
        self.confidence     = float(d.get("conf", 0.0))
        self.violations     = int(d.get("viol", 0))


class TopologyConsistencyValidator(CloudSyncMixin):
    """
    Valideert of de geleerde/goedgekeurde meter-topologie fysiek klopt.
    Aanroepen elke coordinator-cyclus via validate().
    """

    _cloud_module_name = "topology_consistency"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        # {(upstream_id, downstream_id): RelationConsistency}
        self._stats: Dict[Tuple[str, str], RelationConsistency] = {}
        # som-controle: {upstream_id: [downstream_ids]}
        self._upstream_groups: Dict[str, List[str]] = {}
        self._sum_ema: Dict[str, float] = {}        # upstream → EMA van som-ratio
        self._sum_samples: Dict[str, int] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        data = await self._store.async_load()
        if data:
            for key_str, d in data.get("stats", {}).items():
                try:
                    up, down = key_str.split("|", 1)
                    rc = RelationConsistency(upstream_id=up, downstream_id=down)
                    rc.from_dict(d)
                    self._stats[(up, down)] = rc
                except Exception:
                    pass

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                "stats": {
                    f"{k[0]}|{k[1]}": v.to_dict()
                    for k, v in self._stats.items()
                }
            })
            self._dirty_count = 0

    def validate(
        self,
        topology_learner,         # MeterTopologyLearner instance
        current_powers: Dict[str, float],   # {entity_id: power_w}
    ) -> List[dict]:
        """
        Valideer de huidige topologie met de actuele vermogensmetingen.
        Geeft lijst van gedetecteerde problemen terug.
        """
        if not topology_learner or not current_powers:
            return []

        issues = []

        # Haal approved + hoge-confidence tentative relaties op
        relations = topology_learner.get_all_relations()
        approved = [r for r in relations if r["status"] == "approved"]
        tentative = [r for r in relations if r["status"] == "tentative"
                     and r.get("co_movements", 0) >= 12]
        active = approved + tentative

        if not active:
            return []

        # Bouw upstream-groepen
        self._upstream_groups = defaultdict(list)
        for rel in active:
            self._upstream_groups[rel["upstream_id"]].append(rel["downstream_id"])

        # 1. Paar-validatie: upstream ≥ downstream
        for rel in active:
            up_id   = rel["upstream_id"]
            down_id = rel["downstream_id"]
            up_w    = current_powers.get(up_id)
            down_w  = current_powers.get(down_id)

            if up_w is None or down_w is None:
                continue
            if abs(up_w) < MIN_POWER_W and abs(down_w) < MIN_POWER_W:
                continue

            key = (up_id, down_id)
            if key not in self._stats:
                self._stats[key] = RelationConsistency(
                    upstream_id=up_id, downstream_id=down_id
                )
            rc = self._stats[key]

            ratio = abs(down_w) / max(abs(up_w), 1.0)
            rc.ema_ratio    = EMA_ALPHA * ratio + (1 - EMA_ALPHA) * rc.ema_ratio
            rc.sample_count = min(rc.sample_count + 1, 99999)
            if ratio > 1.0 + UPSTREAM_TOLERANCE_FRAC:
                rc.violations += 1
            self._dirty_count += 1

            if rc.sample_count >= MIN_SAMPLES:
                old_class = rc.classification
                issue = self._classify_pair(rc, up_id, down_id)
                if issue:
                    issues.append(issue)
                if rc.classification != old_class and rc.classification != "ok":
                    self._log_issue(rc, up_id, down_id)
                    self._emit_pair_hint(rc, up_id, down_id)

        # 2. Som-validatie: sum(downstream) ≤ upstream
        for up_id, down_ids in self._upstream_groups.items():
            up_w = current_powers.get(up_id)
            if up_w is None or abs(up_w) < MIN_POWER_W:
                continue

            sum_down = sum(
                abs(current_powers.get(d, 0.0))
                for d in down_ids
                if current_powers.get(d) is not None
            )
            if sum_down < MIN_POWER_W:
                continue

            sum_ratio = sum_down / max(abs(up_w), 1.0)
            self._sum_ema[up_id]     = EMA_ALPHA * sum_ratio + (1 - EMA_ALPHA) * self._sum_ema.get(up_id, 0.5)
            self._sum_samples[up_id] = min(self._sum_samples.get(up_id, 0) + 1, 99999)

            if (self._sum_samples[up_id] >= MIN_SAMPLES
                    and self._sum_ema[up_id] > 1.0 + OVERCOUNT_FRAC):
                issue = {
                    "type":        "sum_exceeds_upstream",
                    "upstream_id": up_id,
                    "downstream_ids": down_ids,
                    "sum_ratio":   round(self._sum_ema[up_id], 3),
                    "message":     (
                        f"Som van tussenmeters onder '{up_id}' "
                        f"({self._sum_ema[up_id]*100:.0f}%) overschrijdt de upstream. "
                        f"Mogelijke oorzaak: dubbeltelling of verkeerde sensorrichting."
                    ),
                }
                issues.append(issue)
                self._emit_sum_hint(up_id, down_ids, self._sum_ema[up_id])
                self._log_issue_dict(issue)

        return issues

    def _classify_pair(
        self, rc: RelationConsistency, up_id: str, down_id: str
    ) -> Optional[dict]:
        viol_frac = rc.violations / max(rc.sample_count, 1)

        if rc.ema_ratio > SWAP_FRAC and viol_frac > 0.40:
            rc.classification = "swapped"
            rc.confidence     = min(0.92, viol_frac * 2)
            return {
                "type":          "swapped",
                "upstream_id":   up_id,
                "downstream_id": down_id,
                "ema_ratio":     round(rc.ema_ratio, 3),
                "message":       (
                    f"'{down_id}' is waarschijnlijk de upstream van '{up_id}', niet andersom. "
                    f"Gemiddeld verhouding downstream/upstream = {rc.ema_ratio:.0%}."
                ),
            }
        elif rc.ema_ratio > INVERSION_FRAC and viol_frac > 0.20:
            rc.classification = "suspicious"
            rc.confidence     = min(0.75, viol_frac * 1.5)
            return {
                "type":          "suspicious",
                "upstream_id":   up_id,
                "downstream_id": down_id,
                "ema_ratio":     round(rc.ema_ratio, 3),
                "message":       (
                    f"'{down_id}' meldt {rc.ema_ratio:.0%} van wat '{up_id}' meldt. "
                    f"Controleer of de relatie correct is."
                ),
            }
        else:
            rc.classification = "ok"
            rc.confidence     = min(0.99, 1.0 - rc.ema_ratio)
            return None

    def _emit_pair_hint(
        self, rc: RelationConsistency, up_id: str, down_id: str
    ) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"topo_pair_{rc.classification}_{up_id[:20]}_{down_id[:20]}".replace(".", "_"),
                title      = f"Tussenmeter topologie: {rc.classification}",
                message    = (
                    f"Meter '{down_id}' gedraagt zich niet als een kind van '{up_id}'. "
                    f"Gemiddelde verhouding: {rc.ema_ratio:.0%}, schendingen: "
                    f"{rc.violations} keer. "
                    f"{'De meters zijn waarschijnlijk omgewisseld.' if rc.classification == 'swapped' else 'Controleer de tussenmeter-configuratie.'}"
                ),
                action     = "Controleer meter-topologie in CloudEMS",
                confidence = rc.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("TopologyConsistency hint fout: %s", _e)

    def _emit_sum_hint(
        self, up_id: str, down_ids: List[str], ratio: float
    ) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"topo_sum_{up_id[:30]}".replace(".", "_"),
                title      = "Tussenmeter som overschrijdt upstream",
                message    = (
                    f"De som van de tussenmeters onder '{up_id}' is "
                    f"{ratio*100:.0f}% van de upstream — meer dan verwacht. "
                    f"Controleer op dubbeltellingen of verkeerde sensorrichting. "
                    f"Betrokken meters: {', '.join(down_ids[:3])}."
                ),
                action     = "Controleer meter-topologie op dubbeltellingen",
                confidence = min(0.85, ratio - 1.0),
            )
        except Exception as _e:
            _LOGGER.debug("TopologyConsistency sum hint fout: %s", _e)

    def _log_issue(self, rc: RelationConsistency, up_id: str, down_id: str) -> None:
        msg = (
            f"TopologyConsistencyValidator: {up_id}→{down_id} "
            f"{rc.classification} (ratio {rc.ema_ratio:.3f}, viol {rc.violations})"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "topology_consistency",
                    action   = rc.classification,
                    reason   = f"{up_id}→{down_id}",
                    message  = msg,
                    extra    = rc.to_dict(),
                )
            except Exception:
                pass

    def _log_issue_dict(self, issue: dict) -> None:
        msg = issue.get("message", "topology issue")
        _LOGGER.warning("TopologyConsistencyValidator: %s", msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "topology_consistency",
                    action   = issue.get("type", "unknown"),
                    reason   = issue.get("upstream_id", ""),
                    message  = msg,
                    extra    = issue,
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            "ok_pairs":         sum(1 for rc in self._stats.values() if rc.classification == "ok"),
            "suspicious_pairs": sum(1 for rc in self._stats.values() if rc.classification in ("suspicious", "swapped")),
            "total_pairs":      len(self._stats),
        }

    def get_diagnostics(self) -> dict:
        return {
            f"{k[0]}|{k[1]}": v.to_dict()
            for k, v in self._stats.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. TopologyAutoFeeder
# ─────────────────────────────────────────────────────────────────────────────

class TopologyAutoFeeder:
    """
    Voedt MeterTopologyLearner automatisch met alle bekende power-sensoren.

    Verzamelt:
    - Geconfigureerde primaire sensoren (grid, solar, battery, boiler, EV)
    - NILM confirmed smart-plug entities
    - Fase-sensoren L1/L2/L3
    - Room-meter sensoren

    Aanroepen elke coordinator-cyclus via feed().
    Geen handmatige configuratie van extra_meter_entities nodig.
    """

    REDISCOVER_INTERVAL_S = 600    # herdicover elke 10 minuten

    def __init__(self, hass, config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._known_eids: Set[str] = set()
        self._last_discover_ts: float = 0.0

    def feed(
        self,
        topology_learner,
        current_powers: Dict[str, float],
        nilm_devices: Optional[list] = None,
        room_meter=None,
    ) -> Dict[str, float]:
        """
        Voeg alle bekende sensoren toe aan de topologie-learner.
        Geeft uitgebreid current_powers dict terug (inclusief nieuw ontdekte sensoren).
        """
        now = time.time()
        if now - self._last_discover_ts > self.REDISCOVER_INTERVAL_S:
            self._last_discover_ts = now
            self._discover_entities(nilm_devices, room_meter)

        # Lees waarden van alle bekende sensors
        result = dict(current_powers)
        for eid in self._known_eids:
            if eid in result:
                continue
            state = self._hass.states.get(eid)
            if not state or state.state in ("unavailable", "unknown"):
                continue
            try:
                val = float(state.state)
                if abs(val) < 50000:    # plausibel vermogensbereik
                    result[eid] = val
            except (ValueError, TypeError):
                pass

        # Feed alle waarden aan de learner
        ts = now
        for eid, power_w in result.items():
            try:
                topology_learner.observe(eid, power_w, ts)
            except Exception:
                pass

        return result

    def _discover_entities(
        self,
        nilm_devices: Optional[list],
        room_meter,
    ) -> None:
        """Herdicover alle bekende power-sensor entity_ids."""
        new_eids: Set[str] = set()

        # 1. Geconfigureerde primaire sensoren
        config_keys = [
            "grid_power_sensor", "pv_power_sensor", "battery_power_sensor",
            "battery_soc_sensor",
        ]
        for k in config_keys:
            v = self._config.get(k, "")
            if v and isinstance(v, str) and v.startswith("sensor."):
                new_eids.add(v)

        # Fase-sensoren
        for phase in ("l1", "l2", "l3"):
            for suffix in ("power_sensor", "current_sensor"):
                k = f"phase_{phase}_{suffix}"
                v = self._config.get(k, "")
                if v and isinstance(v, str):
                    new_eids.add(v)
        # CONF_POWER_L1/L2/L3
        for key in ("CONF_POWER_L1", "CONF_POWER_L2", "CONF_POWER_L3",
                    "CONF_PHASE_SENSORS_L1", "CONF_PHASE_SENSORS_L2",
                    "CONF_PHASE_SENSORS_L3"):
            v = self._config.get(key.lower().replace("conf_", ""), "")
            if v and isinstance(v, str):
                new_eids.add(v)

        # Boiler sensoren
        for boiler_cfg in self._config.get("boiler_configs", []):
            for field in ("energy_sensor", "power_sensor"):
                v = boiler_cfg.get(field, "")
                if v and isinstance(v, str):
                    new_eids.add(v)

        # EV sensoren
        for ev_cfg in self._config.get("ev_chargers", []):
            v = ev_cfg.get("power_sensor", "")
            if v and isinstance(v, str):
                new_eids.add(v)

        # Extra meters uit config
        for eid in self._config.get("extra_meter_entities", []):
            if eid and isinstance(eid, str):
                new_eids.add(eid)

        # 2. NILM confirmed smart-plug entities
        if nilm_devices:
            for dev in nilm_devices:
                try:
                    eid = getattr(dev, "entity_id", None)
                    src = getattr(dev, "source", "")
                    confirmed = getattr(dev, "confirmed", False)
                    if eid and confirmed and src == "smart_plug":
                        new_eids.add(eid)
                except Exception:
                    pass

        # 3. Room-meter sensoren
        if room_meter:
            try:
                for eid in getattr(room_meter, "_last_power", {}).keys():
                    if eid and isinstance(eid, str):
                        new_eids.add(eid)
            except Exception:
                pass

        # Filter CloudEMS eigen sensoren (vermijdt feedback loops)
        new_eids = {e for e in new_eids if e and "cloudems" not in e.lower()}

        added = new_eids - self._known_eids
        if added:
            _LOGGER.debug(
                "TopologyAutoFeeder: %d nieuwe sensoren toegevoegd: %s",
                len(added), list(added)[:5],
            )
        self._known_eids = new_eids

    def get_known_entities(self) -> Set[str]:
        return set(self._known_eids)


# ─────────────────────────────────────────────────────────────────────────────
# 3. NILMDoubleCountDetector
# ─────────────────────────────────────────────────────────────────────────────

class NILMDoubleCountDetector:
    """
    Detecteert dubbeltellingen in de NILM-som door topologie-relaties
    te vergelijken met de actieve NILM-apparaten.

    Als twee NILM-apparaten beide actief zijn én een upstream/downstream
    relatie hebben in de goedgekeurde topologie → mogelijke dubbeltelling.

    Aanroepen elke coordinator-cyclus via check().
    """

    def __init__(self, hint_engine=None) -> None:
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._last_alert_ts: Dict[str, float] = {}
        self._ALERT_INTERVAL_S = 3600    # max 1× per uur per paar

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    def check(
        self,
        topology_learner,
        active_nilm_devices: List[dict],    # [{entity_id, name, power_w, is_on}, ...]
    ) -> List[dict]:
        """
        Controleer actieve NILM-apparaten op dubbeltellingen.
        Geeft lijst van verdachte paren terug.
        """
        if not topology_learner or not active_nilm_devices:
            return []

        # Bouw set van actieve entity_ids
        active_eids = {
            d.get("entity_id", "")
            for d in active_nilm_devices
            if d.get("is_on") and d.get("entity_id")
        }
        if len(active_eids) < 2:
            return []

        # Haal approved relaties op
        relations = [
            r for r in topology_learner.get_all_relations()
            if r["status"] == "approved"
        ]

        issues = []
        now = time.time()

        for rel in relations:
            up_id   = rel["upstream_id"]
            down_id = rel["downstream_id"]

            # Beide actief in NILM?
            if up_id not in active_eids or down_id not in active_eids:
                continue

            pair_key = f"{up_id}|{down_id}"

            # Rate-limit
            if now - self._last_alert_ts.get(pair_key, 0) < self._ALERT_INTERVAL_S:
                continue

            self._last_alert_ts[pair_key] = now

            # Zoek namen
            up_dev   = next((d for d in active_nilm_devices if d.get("entity_id") == up_id), {})
            down_dev = next((d for d in active_nilm_devices if d.get("entity_id") == down_id), {})

            issue = {
                "type":          "nilm_double_count",
                "upstream_id":   up_id,
                "downstream_id": down_id,
                "upstream_name":   up_dev.get("name", up_id),
                "downstream_name": down_dev.get("name", down_id),
                "upstream_w":    up_dev.get("power_w", 0),
                "downstream_w":  down_dev.get("power_w", 0),
            }
            issues.append(issue)
            self._emit_hint(issue)
            self._log(issue)

        return issues

    def _emit_hint(self, issue: dict) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"nilm_double_{issue['upstream_id'][:20]}_{issue['downstream_id'][:20]}".replace(".", "_"),
                title      = "Mogelijke dubbeltelling in NILM-som",
                message    = (
                    f"Apparaat '{issue['upstream_name']}' ({issue['upstream_w']:.0f}W) "
                    f"en '{issue['downstream_name']}' ({issue['downstream_w']:.0f}W) zijn "
                    f"beiden actief, maar '{issue['downstream_name']}' hangt achter "
                    f"'{issue['upstream_name']}' in de meter-topologie. "
                    f"Dit telt het verbruik mogelijk dubbel in de NILM-som. "
                    f"Bevestig of verwerp de topologie-relatie."
                ),
                action     = "Controleer meter-topologie en NILM-apparaat configuratie",
                confidence = 0.80,
            )
        except Exception as _e:
            _LOGGER.debug("NILMDoubleCount hint fout: %s", _e)

    def _log(self, issue: dict) -> None:
        msg = (
            f"NILMDoubleCountDetector: '{issue['upstream_name']}' en "
            f"'{issue['downstream_name']}' zijn beide actief in NILM maar "
            f"hebben een upstream→downstream relatie."
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "nilm_double_count",
                    action   = "double_count_detected",
                    reason   = f"{issue['upstream_id']}→{issue['downstream_id']}",
                    message  = msg,
                    extra    = issue,
                )
            except Exception:
                pass
