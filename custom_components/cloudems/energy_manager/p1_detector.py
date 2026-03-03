"""
CloudEMS P1 / DSMR Auto-Detector.

Scans registered HA entities and suggests the most likely:
  - Grid power sensor  (W or kW, bidirectional)
  - Per-phase current sensors (A)
  - Solar production sensor

Used during config-flow to pre-fill sensor fields, reducing
manual search for the user.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import P1_ENTITY_KEYWORDS

_LOGGER = logging.getLogger(__name__)

# Unit groups accepted per sensor role
UNITS_POWER  = {"W", "kW"}
UNITS_CURRENT = {"A"}

# Name patterns (lower-case) that strongly suggest a sensor role
GRID_PATTERNS = [
    r"power_delivered",
    r"electricity_delivered",
    r"net_consumption",
    r"power_usage",
    r"dsmr.*power",
    r"p1.*power",
    r"homewizard.*power",
    r"slimmelezer.*power",
    r"active_power",
]
SOLAR_PATTERNS = [
    r"solar.*power",
    r"pv.*power",
    r"inverter.*power",
    r"sun2000",
    r"solaredge.*power",
]
PHASE_PATTERNS = {
    "L1": [r"l1.*current", r"phase.*1.*current", r"current.*l1", r"fase.*1"],
    "L2": [r"l2.*current", r"phase.*2.*current", r"current.*l2", r"fase.*2"],
    "L3": [r"l3.*current", r"phase.*3.*current", r"current.*l3", r"fase.*3"],
}


@dataclass
class DetectionResult:
    grid_sensor: str | None = None
    solar_sensor: str | None = None
    phase_l1: str | None = None
    phase_l2: str | None = None
    phase_l3: str | None = None
    confidence: dict[str, float] = field(default_factory=dict)


def _score_entity(entity_id: str, unit: str | None, patterns: list[str]) -> float:
    """Return a match score 0..1 for an entity against a list of regex patterns."""
    name = entity_id.lower().replace(".", "_")
    best = 0.0
    for pat in patterns:
        if re.search(pat, name):
            best = max(best, 0.8)
    # Keyword boost
    for kw in P1_ENTITY_KEYWORDS:
        if kw in name:
            best = min(1.0, best + 0.1)
    # Unit match
    if unit in UNITS_POWER and best > 0:
        best = min(1.0, best + 0.1)
    return best


async def async_detect_sensors(hass: HomeAssistant) -> DetectionResult:
    """
    Scan all sensor entities and return best guesses for each role.

    This is a heuristic — results are used as *suggestions* in the wizard,
    never applied silently.
    """
    result = DetectionResult()
    ent_reg = er.async_get(hass)

    candidates: list[tuple[str, str | None]] = []  # (entity_id, unit)

    for state in hass.states.async_all("sensor"):
        entity_id = state.entity_id
        unit = state.attributes.get("unit_of_measurement")
        candidates.append((entity_id, unit))

    # ── Grid power ────────────────────────────────────────────────────────────
    best_grid, best_grid_score = None, 0.0
    for entity_id, unit in candidates:
        if unit not in UNITS_POWER:
            continue
        score = _score_entity(entity_id, unit, GRID_PATTERNS)
        if score > best_grid_score:
            best_grid, best_grid_score = entity_id, score

    result.grid_sensor = best_grid
    result.confidence["grid_sensor"] = round(best_grid_score, 2)

    # ── Solar ─────────────────────────────────────────────────────────────────
    best_solar, best_solar_score = None, 0.0
    for entity_id, unit in candidates:
        if unit not in UNITS_POWER:
            continue
        score = _score_entity(entity_id, unit, SOLAR_PATTERNS)
        if score > best_solar_score:
            best_solar, best_solar_score = entity_id, score

    result.solar_sensor = best_solar
    result.confidence["solar_sensor"] = round(best_solar_score, 2)

    # ── Per-phase current ─────────────────────────────────────────────────────
    for phase, patterns in PHASE_PATTERNS.items():
        best_phase, best_phase_score = None, 0.0
        for entity_id, unit in candidates:
            if unit not in UNITS_CURRENT:
                continue
            score = _score_entity(entity_id, unit, patterns)
            if score > best_phase_score:
                best_phase, best_phase_score = entity_id, score
        setattr(result, f"phase_{phase.lower()}", best_phase)
        result.confidence[f"phase_{phase}"] = round(best_phase_score, 2)

    _LOGGER.debug("P1 auto-detect result: %s", result)
    return result
