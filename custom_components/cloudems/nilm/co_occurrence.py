# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS NILM Co-occurrence Detector — v1.0.0

Detecteert apparaten die structureel tegelijk aan/uit gaan en markeert ze als
gekoppeld. Dit lost twee problemen op:

PROBLEEM 1 — Dubbele clusters
  Een wasmachine met een verwarmingselement en een pomp kan twee aparte on-events
  genereren die beiden als "washing_machine" worden herkend. Zonder co-occurrence
  kennis ontstaan er twee clusters voor hetzelfde apparaat.

PROBLEEM 2 — Valse positieven bij cascades
  Een warmtepomp schakelt een boiler in → beide events lijken op boiler. De
  co-occurrence context geeft de HybridNILM een extra signal om te dedupliceren.

MECHANISME
  Per apparaat-paar (A, B) wordt bijgehouden hoe vaak ze:
    - Samen AAN gaan (co_on)  — beide binnen CO_WINDOW_S van elkaar
    - Samen UIT gaan (co_off)
    - Onafhankelijk AAN gaan (solo_on_A, solo_on_B)

  Co-occurrence ratio = co_on / (co_on + solo_on_A + solo_on_B)

  Als de ratio ≥ CO_THRESHOLD gedurende ≥ CO_MIN_EVENTS events:
    → paar wordt als "gekoppeld" gemarkeerd
    → bij een nieuw event van A: confidence van B-types wordt verhoogd (boost)
    → bij een nieuw event van A: als B al confirmed actief is, penalty op B-type
      (voorkomt dubbele registratie van hetzelfde apparaat)

INTEGRATIE
  In NILMDetector._async_process_event() NA enrich_matches():
      if self._co_occurrence:
          matches = self._co_occurrence.adjust_matches(
              matches, event, currently_active_device_ids)

  In NILMDetector._handle_on/off():
      if self._co_occurrence:
          self._co_occurrence.record_event(device_id, "on"|"off", timestamp)

PERSISTENTIE
  Via HA Store — overleeft herstart.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# ── Configuratie ──────────────────────────────────────────────────────────────

# Tijdvenster waarbinnen twee events als "gelijktijdig" tellen (seconden)
CO_WINDOW_S = 30.0

# Minimale co-occurrence ratio om als gekoppeld te beschouwen
CO_THRESHOLD = 0.70

# Minimaal aantal geobserveerde events voordat we een conclusie trekken
CO_MIN_EVENTS = 6

# Boost voor matches van types die vaak samen opduiken met een actief apparaat
CO_BOOST = 1.25

# Penalty als een gekoppeld apparaat al actief is (voorkomt dubbele registratie)
CO_DUPE_PENALTY = 0.20

# Max paren bijhouden (geheugenbeperking)
CO_MAX_PAIRS = 200

# Vervalsnelheid: events ouder dan CO_DECAY_DAYS tellen minder zwaar
CO_DECAY_DAYS = 60

# Minimum events per apparaat voordat we paren analyseren
CO_MIN_DEVICE_EVENTS = 3


# ── Datastructuren ────────────────────────────────────────────────────────────

@dataclass
class CoEvent:
    """Eén on/off-event van een apparaat."""
    device_id:   str
    event_type:  str    # "on" | "off"
    timestamp:   float


@dataclass
class PairStats:
    """Co-occurrence statistieken voor één apparaat-paar (A, B)."""
    device_a:    str
    device_b:    str
    co_on:       int   = 0    # keer samen AAN
    co_off:      int   = 0    # keer samen UIT
    solo_on_a:   int   = 0    # A aan, B niet
    solo_on_b:   int   = 0    # B aan, A niet
    last_updated: float = field(default_factory=time.time)

    @property
    def total_events(self) -> int:
        return self.co_on + self.solo_on_a + self.solo_on_b

    @property
    def co_ratio(self) -> float:
        """Co-occurrence ratio [0.0–1.0]. Hoog = sterk gekoppeld."""
        total = self.total_events
        return (self.co_on / total) if total >= CO_MIN_EVENTS else 0.0

    @property
    def is_coupled(self) -> bool:
        return (
            self.total_events >= CO_MIN_EVENTS
            and self.co_ratio >= CO_THRESHOLD
        )

    def to_dict(self) -> dict:
        return {
            "device_a":    self.device_a,
            "device_b":    self.device_b,
            "co_on":       self.co_on,
            "co_off":      self.co_off,
            "solo_on_a":   self.solo_on_a,
            "solo_on_b":   self.solo_on_b,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairStats":
        return cls(
            device_a     = d["device_a"],
            device_b     = d["device_b"],
            co_on        = int(d.get("co_on", 0)),
            co_off       = int(d.get("co_off", 0)),
            solo_on_a    = int(d.get("solo_on_a", 0)),
            solo_on_b    = int(d.get("solo_on_b", 0)),
            last_updated = float(d.get("last_updated", time.time())),
        )


# ── Hoofdklasse ───────────────────────────────────────────────────────────────

class CoOccurrenceDetector:
    """
    Leert welke NILM-apparaten structureel tegelijk aan/uit gaan.

    Gebruik in detector.py:

        # Setup (in async_setup of __init__):
        self._co_occurrence = CoOccurrenceDetector()
        await self._co_occurrence.async_load(store)

        # Bij elk on/off event (na device is_on update):
        self._co_occurrence.record_event(device_id, "on", event.timestamp)

        # Bij classificatie (na enrich_matches, vóór _handle_match):
        active_ids = [d.device_id for d in self._devices.values() if d.is_on]
        matches = self._co_occurrence.adjust_matches(
            matches, delta_w, event.phase, event.timestamp, active_ids)

        # Periodiek opslaan (bijv. elke 5 min of bij store_devices):
        await self._co_occurrence.async_save()
    """

    def __init__(self) -> None:
        # Recente events per apparaat — sliding window
        self._recent: Dict[str, List[CoEvent]] = {}
        # Paar-statistieken: key = (sorted device_a, device_b)
        self._pairs:  Dict[Tuple[str, str], PairStats] = {}
        self._store   = None
        self._dirty   = False

    # ── Opslag ────────────────────────────────────────────────────────────────

    async def async_load(self, store) -> None:
        """Laad statistieken uit HA storage."""
        self._store = store
        try:
            data = await store.async_load()
            if not data:
                return
            loaded = 0
            for d in data.get("pairs", []):
                try:
                    ps = PairStats.from_dict(d)
                    # Verwijder verouderde paren
                    age_days = (time.time() - ps.last_updated) / 86400.0
                    if age_days > CO_DECAY_DAYS:
                        continue
                    key = (min(ps.device_a, ps.device_b),
                           max(ps.device_a, ps.device_b))
                    self._pairs[key] = ps
                    loaded += 1
                except Exception:
                    pass
            _LOGGER.debug("CoOccurrence: %d paren geladen", loaded)
        except Exception as exc:
            _LOGGER.warning("CoOccurrence: laden mislukt: %s", exc)

    async def async_save(self) -> None:
        """Sla statistieken op naar HA storage (alleen als dirty)."""
        if not self._dirty or self._store is None:
            return
        try:
            await self._store.async_save({
                "pairs": [ps.to_dict() for ps in self._pairs.values()],
            })
            self._dirty = False
            _LOGGER.debug("CoOccurrence: %d paren opgeslagen", len(self._pairs))
        except Exception as exc:
            _LOGGER.warning("CoOccurrence: opslaan mislukt: %s", exc)

    # ── Event registratie ─────────────────────────────────────────────────────

    def record_event(
        self,
        device_id:  str,
        event_type: str,   # "on" | "off"
        timestamp:  float,
        active_device_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Registreer een on/off-event en update paar-statistieken.

        active_device_ids: lijst van device_ids die nu actief zijn
        (exclusief het huidige apparaat). Nodig om co_on vs solo_on te bepalen.
        """
        if not device_id:
            return

        ev = CoEvent(device_id=device_id, event_type=event_type, timestamp=timestamp)

        # Ruim oude events op uit de sliding window
        cutoff = timestamp - CO_WINDOW_S
        self._recent[device_id] = [
            e for e in self._recent.get(device_id, [])
            if e.timestamp >= cutoff
        ]
        self._recent[device_id].append(ev)

        if event_type != "on" or active_device_ids is None:
            return

        # ── Update paar-statistieken ──────────────────────────────────────────
        # Apparaten die binnen CO_WINDOW_S ook AAN zijn gegaan
        co_devices = set()
        now = timestamp
        for other_id, events in self._recent.items():
            if other_id == device_id:
                continue
            for other_ev in events:
                if (other_ev.event_type == "on"
                        and abs(other_ev.timestamp - now) <= CO_WINDOW_S):
                    co_devices.add(other_id)
                    break

        # Apparaten die al actief waren (maar niet net AAN gegaan)
        active_set = set(active_device_ids) - {device_id} - co_devices

        # Update paar-stats voor apparaten die nu samen AAN gingen
        for other_id in co_devices:
            self._update_pair(device_id, other_id, co_on=True)

        # Update paar-stats voor apparaten die onafhankelijk actief zijn
        for other_id in active_set:
            # We zien device_id solo AAN gaan terwijl other_id al actief was
            self._update_pair(device_id, other_id, co_on=False, a_is_first=True)

        # Als dit apparaat solo AAN gaat (geen andere recente on-events)
        if not co_devices and not active_set:
            # Solo event — geen paar te updaten, maar we kunnen bestaande paren
            # bijwerken om solo_on te verhogen
            for key, ps in list(self._pairs.items()):
                if device_id in (ps.device_a, ps.device_b):
                    other = ps.device_b if ps.device_a == device_id else ps.device_a
                    if other not in active_device_ids:
                        # Beide solo → solo teller voor device_id omhoog
                        if ps.device_a == device_id:
                            ps.solo_on_a += 1
                        else:
                            ps.solo_on_b += 1
                        ps.last_updated = now
                        self._dirty = True

    def _update_pair(
        self,
        device_a: str,
        device_b: str,
        co_on:    bool,
        a_is_first: bool = False,
    ) -> None:
        """Update statistieken voor paar (device_a, device_b)."""
        key = (min(device_a, device_b), max(device_a, device_b))

        # Begrens het totaal aantal paren
        if key not in self._pairs and len(self._pairs) >= CO_MAX_PAIRS:
            # Verwijder het minst actieve paar
            oldest_key = min(self._pairs, key=lambda k: self._pairs[k].last_updated)
            del self._pairs[oldest_key]
            _LOGGER.debug("CoOccurrence: paar verwijderd (max bereikt)")

        if key not in self._pairs:
            self._pairs[key] = PairStats(device_a=key[0], device_b=key[1])

        ps = self._pairs[key]
        if co_on:
            ps.co_on += 1
        elif a_is_first:
            if ps.device_a == device_a:
                ps.solo_on_a += 1
            else:
                ps.solo_on_b += 1
        ps.last_updated = time.time()
        self._dirty = True

        if ps.is_coupled:
            _LOGGER.info(
                "CoOccurrence: %s ↔ %s gekoppeld (ratio=%.0f%%, n=%d)",
                ps.device_a, ps.device_b,
                ps.co_ratio * 100, ps.total_events,
            )

    # ── Match-aanpassing ──────────────────────────────────────────────────────

    def adjust_matches(
        self,
        matches:           List[dict],
        active_device_ids: List[str],
        detector_devices:  dict,     # device_id → DetectedDevice
    ) -> List[dict]:
        """
        Pas match-confidences aan op basis van co-occurrence kennis.

        Twee effecten:
        1. BOOST: als een device_type vaak samen voorkomt met een actief apparaat,
           verhoog de confidence voor dat type licht.
        2. DUPE PENALTY: als een gekoppeld apparaat al actief en confirmed is
           op dezelfde fase, verlaag drastisch (voorkomt dubbele cluster).

        Returns: aangepaste matches, gesorteerd op confidence desc.
        """
        if not self._pairs or not active_device_ids:
            return matches

        # Bouw een set van (device_type, phase) van bevestigde actieve apparaten
        confirmed_active: Dict[str, str] = {}  # device_type → phase
        for did in active_device_ids:
            dev = detector_devices.get(did)
            if dev and dev.is_on and (dev.confirmed or getattr(dev, "user_feedback", "") == "correct"):
                confirmed_active[dev.display_type] = getattr(dev, "phase", "L1")

        # Welke device_types zijn co-occurrence-gekoppeld met actieve apparaten?
        coupled_boost:   Dict[str, float] = {}  # device_type → boost factor
        coupled_dupe:    set              = set()  # device_types die al actief zijn

        for key, ps in self._pairs.items():
            if not ps.is_coupled:
                continue
            a_active = ps.device_a in active_device_ids
            b_active = ps.device_b in active_device_ids

            if not (a_active or b_active):
                continue

            # Bepaal het type van het actieve apparaat in dit paar
            active_id   = ps.device_a if a_active else ps.device_b
            inactive_id = ps.device_b if a_active else ps.device_a

            active_dev = detector_devices.get(active_id)
            if not active_dev:
                continue
            active_type = active_dev.display_type

            # Het inactieve apparaat heeft nog geen confirmed type:
            # boost het actieve type (het is gekoppeld)
            inactive_dev = detector_devices.get(inactive_id)
            inactive_type = inactive_dev.display_type if inactive_dev else ""

            # Als het actieve type al confirmed is → sterk gekoppeld event
            # is waarschijnlijk het ZELFDE apparaat → dupe penalty
            if active_type in confirmed_active:
                coupled_dupe.add(active_type)
            else:
                # Nog niet confirmed → lichte boost
                coupled_boost[active_type] = max(
                    coupled_boost.get(active_type, 1.0), CO_BOOST
                )

        if not coupled_boost and not coupled_dupe:
            return matches

        out = []
        for m in matches:
            dt   = m.get("device_type", "")
            conf = m.get("confidence", 0.0)
            note = m.get("hybrid_note", "")

            if dt in coupled_dupe:
                # Dit type is al confirmed actief — waarschijnlijk een duplicaat
                conf = round(conf * CO_DUPE_PENALTY, 4)
                note = (note + ",co_dupe_penalty").lstrip(",")
                _LOGGER.debug(
                    "CoOccurrence: %s dupe-penalty (%.0f%%)", dt, CO_DUPE_PENALTY * 100
                )
            elif dt in coupled_boost:
                # Gekoppeld maar nog niet confirmed → lichte boost
                conf = round(min(1.0, conf * coupled_boost[dt]), 4)
                note = (note + ",co_boost").lstrip(",")

            out.append({**m, "confidence": conf, "hybrid_note": note})

        out.sort(key=lambda x: x["confidence"], reverse=True)
        return out

    # ── Diagnostiek ───────────────────────────────────────────────────────────

    def get_coupled_pairs(self) -> List[dict]:
        """Geeft alle gekoppelde paren terug (voor dashboard/diagnose)."""
        return [
            {
                "device_a":  ps.device_a,
                "device_b":  ps.device_b,
                "co_ratio":  round(ps.co_ratio, 3),
                "co_on":     ps.co_on,
                "total":     ps.total_events,
                "coupled":   ps.is_coupled,
            }
            for ps in sorted(self._pairs.values(),
                             key=lambda p: -p.co_ratio)
            if ps.total_events >= CO_MIN_EVENTS
        ]

    def get_diagnostics(self) -> dict:
        total     = len(self._pairs)
        coupled   = sum(1 for ps in self._pairs.values() if ps.is_coupled)
        candidate = sum(1 for ps in self._pairs.values()
                        if CO_MIN_EVENTS // 2 <= ps.total_events < CO_MIN_EVENTS)
        return {
            "total_pairs":     total,
            "coupled_pairs":   coupled,
            "candidate_pairs": candidate,
            "top_coupled":     self.get_coupled_pairs()[:5],
        }

    def on_device_removed(self, device_id: str) -> None:
        """Verwijder alle paren die dit apparaat bevatten."""
        keys_to_remove = [
            k for k in self._pairs
            if device_id in k
        ]
        for k in keys_to_remove:
            del self._pairs[k]
        self._recent.pop(device_id, None)
        if keys_to_remove:
            self._dirty = True
            _LOGGER.debug(
                "CoOccurrence: %d paren verwijderd voor '%s'",
                len(keys_to_remove), device_id,
            )
