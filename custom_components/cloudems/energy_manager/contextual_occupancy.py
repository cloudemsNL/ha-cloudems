# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Contextual Occupancy v1.0.0

Leert gedragssequenties van bewoners via NILM apparaat-activaties.
Herkent patronen zoals:
  slaap:     waterkoker → badkamer → telefoon opladen → 0W woonkamer
  opstaan:   koffiezetter → broodrooster → tv
  vertrek:   vaatwasser start → alle kleine verbruikers uit
  thuiskomst: verlichting → tv → magnetron/koken

Na N herhalingen van een sequentie → herkend als "intentie".
Bij afwijking van een bekende sequentie → notificatie (bijv. oven aan om 02:00).

WERKING
═══════
1. Elke tick: registreer welke apparaten aan/uit gaan (NILM events)
2. Bouw rolling window van laatste N events
3. Match window tegen geleerde patronen (DTW-achtig, maar simpel)
4. Als match → infereer intentie (slaap/opstaan/weg/thuis)
5. Deel mee aan AbsenceDetector als extra signaal
6. Anomalie: event dat niet past bij recent patroon + tijdstip → alert
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_contextual_occupancy_v1"
STORAGE_VERSION = 1

# Sequentie parameters
MAX_SEQUENCE_GAP_S  = 300    # max tijd tussen events in één sequentie (5 min)
MIN_PATTERN_REPEATS = 3      # minimaal herhalingen voor herkenning
MAX_EVENTS_WINDOW   = 8      # aantal events in rolling window
ANOMALY_HOUR_START  = 23     # uren waarbuiten activiteit verdacht is
ANOMALY_HOUR_END    = 6
ANOMALY_MIN_W       = 200    # minimaal vermogen voor anomalie-check

# Bekende intentie-patronen (device_type sequenties)
# CloudEMS leert eigen varianten, maar dit zijn goede defaults
KNOWN_PATTERNS = {
    "slaap": [
        ["kettle", "bathroom_light", "phone_charger"],
        ["kettle", "phone_charger"],
        ["bathroom_light", "phone_charger"],
    ],
    "opstaan": [
        ["coffee_maker", "toaster"],
        ["coffee_maker", "kitchen_light"],
        ["kettle", "toaster"],
    ],
    "vertrek": [
        ["dishwasher", "all_small_off"],
        ["washing_machine", "all_small_off"],
    ],
    "thuiskomst": [
        ["light", "tv"],
        ["light", "microwave"],
        ["light", "kettle"],
    ],
}

# Device type mapping (NILM type → intentie-categorie)
DEVICE_INTENT_MAP = {
    "kettle":          "kettle",
    "coffee_maker":    "coffee_maker",
    "toaster":         "toaster",
    "washing_machine": "washing_machine",
    "washer":          "washing_machine",
    "dishwasher":      "dishwasher",
    "tv":              "tv",
    "television":      "tv",
    "phone_charger":   "phone_charger",
    "light":           "light",
    "microwave":       "microwave",
    "oven":            "oven",
    "computer":        "computer",
    "printer":         "printer",
}


@dataclass
class SequenceEvent:
    ts:          float
    device_type: str
    device_id:   str
    label:       str
    power_w:     float
    transition:  str   # "on" | "off"


@dataclass
class LearnedPattern:
    name:       str
    sequence:   list[str]   # device_type lijst
    count:      int = 0
    last_seen:  float = 0.0
    avg_gap_s:  float = 60.0


class ContextualOccupancyLearner:
    """Leert gedragssequenties en detecteert intenties + anomalieën."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass      = hass
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._events:   deque = deque(maxlen=MAX_EVENTS_WINDOW * 3)
        self._patterns: dict[str, LearnedPattern] = {}
        self._prev_on:  dict[str, bool] = {}
        self._last_intent:   str   = ""
        self._last_intent_ts: float = 0.0
        self._anomaly_count: int   = 0
        self._notify_cb = None

    def set_notify_callback(self, cb) -> None:
        self._notify_cb = cb

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for name, d in saved.get("patterns", {}).items():
            self._patterns[name] = LearnedPattern(
                name     = name,
                sequence = d.get("sequence", []),
                count    = int(d.get("count", 0)),
                last_seen = float(d.get("last_seen", 0)),
                avg_gap_s = float(d.get("avg_gap_s", 60)),
            )
        _LOGGER.info(
            "ContextualOccupancy: %d patronen geladen", len(self._patterns)
        )

    async def async_save(self) -> None:
        await self._store.async_save({
            "patterns": {
                name: {
                    "sequence":  p.sequence,
                    "count":     p.count,
                    "last_seen": p.last_seen,
                    "avg_gap_s": p.avg_gap_s,
                }
                for name, p in self._patterns.items()
            }
        })

    def _get_intent_type(self, device_type: str) -> str:
        return DEVICE_INTENT_MAP.get(device_type.lower(), device_type.lower())

    def _recent_sequence(self, window_s: float = MAX_SEQUENCE_GAP_S * MAX_EVENTS_WINDOW) -> list[str]:
        """Haal recente device_type sequentie op."""
        now = time.time()
        cutoff = now - window_s
        seq = []
        last_ts = 0.0
        for ev in self._events:
            if ev.ts < cutoff:
                continue
            if ev.transition != "on":
                continue
            # Breek sequentie als gat te groot
            if last_ts > 0 and (ev.ts - last_ts) > MAX_SEQUENCE_GAP_S:
                seq = []
            seq.append(self._get_intent_type(ev.device_type))
            last_ts = ev.ts
        return seq[-MAX_EVENTS_WINDOW:]

    def _match_pattern(self, sequence: list[str]) -> Optional[str]:
        """Match sequentie tegen bekende patronen. Returns: intentie naam of None."""
        if len(sequence) < 2:
            return None

        # Check geleerde patronen
        for name, pattern in self._patterns.items():
            pat_seq = pattern.sequence
            if len(pat_seq) < 2:
                continue
            # Subsequence check: pat_seq moet als subsequentie in sequence voorkomen
            pat_idx = 0
            for item in sequence:
                if pat_idx < len(pat_seq) and item == pat_seq[pat_idx]:
                    pat_idx += 1
            if pat_idx >= len(pat_seq):
                return name

        # Check default patronen
        for intent, variants in KNOWN_PATTERNS.items():
            for variant in variants:
                pat_idx = 0
                for item in sequence:
                    if pat_idx < len(variant) and item == variant[pat_idx]:
                        pat_idx += 1
                if pat_idx >= len(variant):
                    return intent

        return None

    def _is_anomaly(self, event: SequenceEvent) -> Optional[str]:
        """Check of dit event een anomalie is."""
        h = datetime.fromtimestamp(event.ts).hour
        is_night = h >= ANOMALY_HOUR_START or h < ANOMALY_HOUR_END

        if not is_night:
            return None
        if event.power_w < ANOMALY_MIN_W:
            return None
        if event.transition != "on":
            return None

        # Gevaarlijke apparaten 's nachts
        dangerous = {"oven", "stove", "cooking", "iron", "hairdryer"}
        if self._get_intent_type(event.device_type) in dangerous:
            return (
                f"{event.label} is om {datetime.fromtimestamp(event.ts).strftime('%H:%M')} "
                f"ingeschakeld ({event.power_w:.0f}W). "
                f"Wil je de nachtmodus uitstellen of dit apparaat uitschakelen?"
            )

        return None

    def tick(self, nilm_devices: list[dict]) -> dict:
        """Aanroepen elke coordinator tick.

        Returns: dict met intent, anomalies, patterns_learned.
        """
        now   = time.time()
        result = {
            "intent":          self._last_intent,
            "intent_ts":       self._last_intent_ts,
            "anomalies":       [],
            "patterns_learned": len(self._patterns),
        }

        # Detecteer on/off transities
        for dev in nilm_devices:
            did   = dev.get("device_id") or dev.get("id") or dev.get("label", "")
            dtype = dev.get("device_type", "")
            pw    = float(dev.get("power_w", dev.get("current_power", 0)) or 0)
            label = dev.get("label") or dev.get("name") or did
            was_on = self._prev_on.get(did, False)
            is_on  = pw > 10

            if is_on != was_on:
                transition = "on" if is_on else "off"
                ev = SequenceEvent(
                    ts=now, device_type=dtype, device_id=did,
                    label=label, power_w=pw, transition=transition
                )
                self._events.append(ev)

                # Anomalie check
                if is_on:
                    anomaly_msg = self._is_anomaly(ev)
                    if anomaly_msg:
                        self._anomaly_count += 1
                        result["anomalies"].append({
                            "device_id": did, "label": label,
                            "message": anomaly_msg, "ts": now,
                        })
                        if self._notify_cb:
                            try:
                                self._notify_cb(
                                    title=f"⚠️ Ongewoon verbruik — {label}",
                                    message=anomaly_msg,
                                    severity="warning",
                                )
                            except Exception:
                                pass

            self._prev_on[did] = is_on

        # Intentie detectie op huidige sequentie
        seq = self._recent_sequence()
        if seq:
            intent = self._match_pattern(seq)
            if intent and intent != self._last_intent:
                self._last_intent    = intent
                self._last_intent_ts = now
                result["intent"]     = intent
                _LOGGER.debug(
                    "ContextualOccupancy: intentie herkend → %s (seq: %s)",
                    intent, seq[-3:]
                )

                # Leer nieuw patroon als het nog niet bekend is
                pat_key = "_".join(seq[-3:])
                if pat_key not in self._patterns:
                    self._patterns[pat_key] = LearnedPattern(
                        name=pat_key, sequence=seq[-3:], count=1, last_seen=now
                    )
                else:
                    self._patterns[pat_key].count    += 1
                    self._patterns[pat_key].last_seen = now
                result["patterns_learned"] = len(self._patterns)

        return result

    def get_status(self) -> dict:
        top_patterns = sorted(
            self._patterns.values(), key=lambda p: p.count, reverse=True
        )[:10]
        return {
            "last_intent":       self._last_intent,
            "last_intent_ts":    self._last_intent_ts,
            "patterns_learned":  len(self._patterns),
            "anomaly_count":     self._anomaly_count,
            "top_patterns": [
                {"name": p.name, "count": p.count, "sequence": p.sequence}
                for p in top_patterns
            ],
        }
