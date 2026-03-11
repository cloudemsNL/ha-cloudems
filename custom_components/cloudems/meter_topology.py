"""
CloudEMS — Meter Topology Learning
===================================
Leert automatisch welke meetpunten "achter" andere meetpunten hangen via
correlatie van vermogensmetingen. Ondersteunt een volledige boom:

  root_meter  (P1 / netsensor)
  └── meter_A  (bijv. laadpaal groep)
      └── device_B  (EV lader)
      └── device_C  (wandcontactdoos)
  └── meter_D  (zonnepanelen groep)

Upstream learning:
  Als meter_X en meter_Y tegelijkertijd op- en afschalen, is de kans groot
  dat één van hen achter de ander hangt. Na voldoende co-bewegingen (LEARN_MIN)
  wordt een upstream-relatie gesuggereerd met status 'tentative'.

Status per relatie:
  tentative  — door CloudEMS geleerd, nog niet bevestigd
  approved   — door gebruiker bevestigd
  declined   — door gebruiker afgewezen (nooit opnieuw suggereren)

v4.5.51 — initiële implementatie
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# Minimaal aantal co-bewegingen voor een tentative suggestie
LEARN_MIN_CORRELATIONS = 8

# Correlatie-venster in seconden (maximale tijd tussen 2 gelijktijdige events)
CORR_WINDOW_S = 5.0

# Minimale vermogensverandering om als "beweging" te tellen (W)
MIN_DELTA_W = 50.0

# Factor: upstream moet GROTERE uitschieters hebben dan downstream
# (root meter bevat altijd de som van alle kinderen)
UPSTREAM_RATIO_MIN = 1.05

# Maximale boomdiepte
MAX_DEPTH = 6


@dataclass
class MeterRelation:
    """Een geleerde of bevestigde upstream → downstream relatie."""
    upstream_id: str      # entity_id van de bovenliggende meter
    downstream_id: str    # entity_id van de onderliggende meter

    status: str = "tentative"   # tentative | approved | declined

    # Leer-statistieken (alleen intern gebruikt)
    co_movements: int  = 0      # aantal keren dat beide bewogen
    confirmed_at:  Optional[float] = None
    declined_at:   Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "upstream_id":   self.upstream_id,
            "downstream_id": self.downstream_id,
            "status":        self.status,
            "co_movements":  self.co_movements,
        }

    @staticmethod
    def from_dict(d: dict) -> "MeterRelation":
        rel = MeterRelation(
            upstream_id=d["upstream_id"],
            downstream_id=d["downstream_id"],
            status=d.get("status", "tentative"),
            co_movements=d.get("co_movements", 0),
        )
        return rel


@dataclass
class MeterNode:
    """Een knoop in de meters-boom."""
    entity_id: str
    name: str = ""
    power_w: float = 0.0
    depth: int = 0
    children: List["MeterNode"] = field(default_factory=list)
    status: str = "tentative"   # status van de relatie met z'n parent

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name":      self.name,
            "power_w":   round(self.power_w, 1),
            "depth":     self.depth,
            "status":    self.status,
            "children":  [c.to_dict() for c in self.children],
        }


class MeterTopologyLearner:
    """
    Leert en beheert de topologie van energiemeters.

    Gebruik:
        learner = MeterTopologyLearner()
        learner.load(saved_data)            # bij opstarten

        # elke coördinatorcyclus:
        learner.observe(entity_id, power_w, ts)

        # dashboard:
        tree = learner.get_tree(hass)
        suggestions = learner.get_tentative_relations()

        # gebruikersacties:
        learner.approve(upstream_id, downstream_id)
        learner.decline(upstream_id, downstream_id)
    """

    def __init__(self) -> None:
        # entity_id → laatste (power_w, ts)
        self._last_power: Dict[str, Tuple[float, float]] = {}

        # (upstream_id, downstream_id) → MeterRelation
        self._relations: Dict[Tuple[str, str], MeterRelation] = {}

        # entity_id → lijst van recente grote deltas (delta_w, ts)
        self._recent_deltas: Dict[str, List[Tuple[float, float]]] = {}

        # Expliciete root meters (ingesteld via config of handmatig)
        self._root_meters: List[str] = []

        self._lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Persistentie
    # ─────────────────────────────────────────────────────────────────────────

    def dump(self) -> dict:
        """Sla de geleerde topologie op als JSON-serialiseerbaar dict."""
        return {
            "relations": [r.to_dict() for r in self._relations.values()],
            "root_meters": self._root_meters,
        }

    def load(self, data: dict) -> None:
        """Herstel de topologie uit opgeslagen data."""
        if not data:
            return
        for rd in data.get("relations", []):
            try:
                rel = MeterRelation.from_dict(rd)
                self._relations[(rel.upstream_id, rel.downstream_id)] = rel
            except Exception as exc:
                _LOGGER.warning("MeterTopology: ongeldige relatie: %s — %s", rd, exc)
        self._root_meters = data.get("root_meters", [])
        _LOGGER.debug(
            "MeterTopology geladen: %d relaties, root meters: %s",
            len(self._relations), self._root_meters
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Observaties (aanroepen elke coordinator-cyclus)
    # ─────────────────────────────────────────────────────────────────────────

    def observe(self, entity_id: str, power_w: float, ts: float) -> None:
        """
        Registreer een vermogensmeting. Vergelijk met vorige meting om
        grote veranderingen op te sporen en cross-meter correlaties te leren.
        """
        prev = self._last_power.get(entity_id)
        self._last_power[entity_id] = (power_w, ts)

        if prev is None:
            return

        prev_w, prev_ts = prev
        delta = abs(power_w - prev_w)

        if delta < MIN_DELTA_W:
            return  # te klein om interessant te zijn

        # Registreer delta voor correlatie
        deltas = self._recent_deltas.setdefault(entity_id, [])
        deltas.append((delta, ts))

        # Verwijder verouderde deltas
        cutoff = ts - CORR_WINDOW_S * 4
        self._recent_deltas[entity_id] = [
            (d, t) for d, t in deltas if t >= cutoff
        ]

        # Zoek correlaties met alle andere meters
        self._find_correlations(entity_id, delta, ts)

    def _find_correlations(self, source_id: str, source_delta: float, ts: float) -> None:
        """
        Vergelijk de huidige delta van source_id met recente deltas van
        alle andere bekende meters. Als beide bijna gelijktijdig bewegen,
        registreer een co-beweging.
        """
        for other_id, other_deltas in self._recent_deltas.items():
            if other_id == source_id:
                continue

            # Check of andere meter ook recent bewogen is
            recent = [
                (d, t) for d, t in other_deltas
                if abs(t - ts) <= CORR_WINDOW_S
            ]
            if not recent:
                continue

            # Bepaal richting: wie is upstream (grotere beweging)?
            other_delta = max(d for d, _ in recent)

            # Upstream moet altijd >= downstream zijn (netstroom = som van alles)
            if source_delta > other_delta * UPSTREAM_RATIO_MIN:
                # source is waarschijnlijk upstream van other
                self._register_co_movement(source_id, other_id)
            elif other_delta > source_delta * UPSTREAM_RATIO_MIN:
                # other is waarschijnlijk upstream van source
                self._register_co_movement(other_id, source_id)

    def _register_co_movement(self, upstream_id: str, downstream_id: str) -> None:
        """Registreer een co-beweging en creëer/update de relatie."""
        key = (upstream_id, downstream_id)

        # Sla declined relaties volledig over
        existing = self._relations.get(key)
        if existing and existing.status == "declined":
            return
        if existing and existing.status == "approved":
            # Al goedgekeurd — alleen co_movements ophogen
            existing.co_movements += 1
            return

        if existing is None:
            self._relations[key] = MeterRelation(
                upstream_id=upstream_id,
                downstream_id=downstream_id,
                co_movements=1,
            )
        else:
            existing.co_movements += 1

        # Log als we de drempel bereiken
        new_count = self._relations[key].co_movements
        if new_count == LEARN_MIN_CORRELATIONS:
            _LOGGER.info(
                "MeterTopology: nieuwe suggestie — %s is waarschijnlijk upstream van %s (%d co-bewegingen)",
                upstream_id, downstream_id, new_count
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Gebruikersacties
    # ─────────────────────────────────────────────────────────────────────────

    def approve(self, upstream_id: str, downstream_id: str) -> None:
        """Bevestig een upstream-relatie."""
        key = (upstream_id, downstream_id)
        if key not in self._relations:
            self._relations[key] = MeterRelation(
                upstream_id=upstream_id,
                downstream_id=downstream_id,
                co_movements=0,
            )
        rel = self._relations[key]
        rel.status = "approved"
        rel.confirmed_at = time.time()
        _LOGGER.info("MeterTopology: relatie goedgekeurd — %s → %s", upstream_id, downstream_id)

    def decline(self, upstream_id: str, downstream_id: str) -> None:
        """Wijs een upstream-relatie af."""
        key = (upstream_id, downstream_id)
        if key not in self._relations:
            self._relations[key] = MeterRelation(
                upstream_id=upstream_id,
                downstream_id=downstream_id,
                co_movements=0,
            )
        rel = self._relations[key]
        rel.status = "declined"
        rel.declined_at = time.time()
        _LOGGER.info("MeterTopology: relatie afgewezen — %s → %s", upstream_id, downstream_id)

    def set_root_meter(self, entity_id: str) -> None:
        """Markeer een entity als root meter (bijv. P1 sensor)."""
        if entity_id not in self._root_meters:
            self._root_meters.append(entity_id)

    def remove_root_meter(self, entity_id: str) -> None:
        """Verwijder een entity als root meter."""
        self._root_meters = [x for x in self._root_meters if x != entity_id]

    # ─────────────────────────────────────────────────────────────────────────
    # Dashboard data
    # ─────────────────────────────────────────────────────────────────────────

    def get_tentative_relations(self) -> List[dict]:
        """Geef alle tentative relaties terug die boven de leer-drempel zitten."""
        result = []
        for rel in self._relations.values():
            if rel.status == "tentative" and rel.co_movements >= LEARN_MIN_CORRELATIONS:
                result.append(rel.to_dict())
        return sorted(result, key=lambda r: r["co_movements"], reverse=True)

    def get_all_relations(self) -> List[dict]:
        """Geef alle niet-declined relaties terug."""
        return [
            r.to_dict() for r in self._relations.values()
            if r.status != "declined"
        ]

    def get_tree(self, name_resolver=None) -> List[dict]:
        """
        Bouw een boom van alle goedgekeurde én tentative relaties.

        name_resolver: optioneel callable(entity_id) → str
                       bijv. lambda eid: hass.states[eid].attributes.get('friendly_name', eid)

        Geeft een lijst van root-knopen terug (elk als dict met 'children').
        """
        # Verzamel approved + tentative relaties
        active = {
            key: rel for key, rel in self._relations.items()
            if rel.status in ("approved", "tentative")
            and rel.co_movements >= LEARN_MIN_CORRELATIONS
        }

        if not active:
            return []

        # Bouw downstream-set: welke entity_ids hebben een upstream?
        all_downstream = {rel.downstream_id for rel in active.values()}

        # Bepaal root_ids: upstream die zelf geen downstream zijn
        all_upstream = {rel.upstream_id for rel in active.values()}
        root_ids = all_upstream - all_downstream

        # Voeg expliciete root meters toe
        for r in self._root_meters:
            root_ids.add(r)

        def _resolve_name(eid: str) -> str:
            if name_resolver:
                try:
                    return name_resolver(eid)
                except Exception:
                    pass
            return eid.split(".")[-1].replace("_", " ").title()

        def _build_node(eid: str, depth: int, visited: set) -> Optional[MeterNode]:
            if depth > MAX_DEPTH:
                return None
            if eid in visited:
                return None  # vermijd cirkels
            visited = visited | {eid}

            node = MeterNode(
                entity_id=eid,
                name=_resolve_name(eid),
                power_w=self._last_power.get(eid, (0.0, 0))[0],
                depth=depth,
            )

            # Zoek kinderen (alle meters waarvoor eid upstream is)
            for (up, down), rel in active.items():
                if up == eid:
                    child = _build_node(down, depth + 1, visited)
                    if child:
                        child.status = rel.status
                        node.children.append(child)

            return node

        visited_global: set = set()
        roots = []
        for root_id in sorted(root_ids):
            node = _build_node(root_id, 0, visited_global)
            if node:
                visited_global.add(root_id)
                roots.append(node.to_dict())

        return roots

    def get_stats(self) -> dict:
        """Dashboard statistieken."""
        approved  = sum(1 for r in self._relations.values() if r.status == "approved")
        tentative = sum(
            1 for r in self._relations.values()
            if r.status == "tentative" and r.co_movements >= LEARN_MIN_CORRELATIONS
        )
        learning  = sum(
            1 for r in self._relations.values()
            if r.status == "tentative" and r.co_movements < LEARN_MIN_CORRELATIONS
        )
        declined  = sum(1 for r in self._relations.values() if r.status == "declined")
        return {
            "approved":  approved,
            "tentative": tentative,
            "learning":  learning,
            "declined":  declined,
            "root_meters": self._root_meters,
        }
