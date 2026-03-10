# -*- coding: utf-8 -*-
"""
CloudEMS NILM — Unsupervised Event Clustering — v1.0.0

Groepeert onbekende vermogensevents automatisch via incrementele clustering
(DBSCAN-geïnspireerd, zonder scikit-learn afhankelijkheid) en stelt de gebruiker
vragen als een cluster groot genoeg is om een apparaat te benoemen.

Werking:
  1. Elk onbekend power-event (delta_w, duration_s) wordt als punt opgeslagen.
  2. Na elk nieuw punt wordt gecontroleerd of bestaande clusters uitgebreid worden.
  3. Als een cluster ≥ CLUSTER_MIN_EVENTS events bevat én recent actief is,
     wordt een review-suggestie aangemaakt voor de gebruiker:
     "Er is een onbekend apparaat ~1800 W, ~45 min — wat is dit?"
  4. Na gebruikersbevestiging wordt het cluster omgezet naar een NILM-apparaat
     en worden toekomstige events direct herkend.

Parameters per cluster:
  • centroid_w       — gemiddeld vermogen (W)
  • centroid_dur_s   — gemiddelde duur (s)
  • std_w            — standaarddeviatie vermogen
  • event_count      — aantal events in cluster
  • last_seen_ts     — laatste event timestamp
  • suggested_type   — meest waarschijnlijke apparaattype op basis van centroid

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_nilm_clusters_v1"
STORAGE_VERSION = 1

# Clustering parameters
CLUSTER_EPS_W        = 150.0   # W — max verschil om bij cluster te voegen
CLUSTER_EPS_DUR_S    = 180.0   # s — max verschil in duur
CLUSTER_MIN_EVENTS   = 5       # minimum events voor suggestie
CLUSTER_MAX_AGE_DAYS = 90      # verwijder clusters ouder dan dit
MAX_CLUSTERS         = 50      # maximaal aantal clusters bijhouden


# ── Type-suggestie op basis van vermogen + duur ───────────────────────────────

def _suggest_type(power_w: float, duration_s: float) -> str:
    """Schat het meest waarschijnlijke apparaattype op basis van centroid."""
    p = power_w
    d = duration_s / 60.0  # minuten

    if 1500 <= p <= 3000 and d < 5:
        return "kettle"
    if 800 <= p <= 1800 and 3 <= d <= 20:
        return "microwave"
    if 1800 <= p <= 3500 and 30 <= d <= 180:
        return "washing_machine"
    if 1500 <= p <= 3000 and 40 <= d <= 180:
        return "dryer"
    if 1000 <= p <= 2500 and 60 <= d <= 180:
        return "dishwasher"
    if 1000 <= p <= 4000 and 20 <= d <= 90:
        return "oven"
    if 1000 <= p <= 3000 and 30 <= d <= 120:
        return "boiler"
    if 3000 <= p <= 22000 and d > 60:
        return "ev_charger"
    if 500 <= p <= 3000 and d > 60:
        return "heat_pump"
    if 100 <= p <= 400 and d > 5:
        return "refrigerator"
    if p < 100:
        return "light"
    return "unknown"


# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class EventCluster:
    cluster_id:    str
    centroid_w:    float
    centroid_dur_s: float
    std_w:         float = 0.0
    event_count:   int   = 0
    last_seen_ts:  float = field(default_factory=time.time)
    suggested:     bool  = False   # al een suggestie aangemaakt?
    confirmed:     bool  = False   # door gebruiker bevestigd als apparaat?
    suggested_type: str  = "unknown"
    # v4.5: V-I trajectory approximation — gemiddelde reactive fraction sin(phi)
    # 0.0 = puur resistief (ketel/oven), 1.0 = puur reactief (inductiemotor)
    # Discrimineert motor-apparaten van resistieve lasten bij zelfde wattage.
    centroid_reactive_frac: float = 0.0   # gemiddelde sin(phi) over cluster-events

    def distance(self, power_w: float, duration_s: float,
                 reactive_frac: float | None = None) -> float:
        """Genormaliseerde afstand tot centroid — nu ook op V-I dimensie."""
        dw = abs(self.centroid_w - power_w) / max(self.centroid_w, 1.0)
        dd = abs(self.centroid_dur_s - duration_s) / max(self.centroid_dur_s, 1.0)
        dist = math.sqrt(dw ** 2 + dd ** 2)
        # v4.5: als reactive_fraction beschikbaar is, voeg V-I dimensie toe
        # Gewicht 0.5× want dit feature is minder betrouwbaar dan vermogen
        if reactive_frac is not None and self.centroid_reactive_frac > 0:
            dr = abs(self.centroid_reactive_frac - reactive_frac)
            dist = math.sqrt(dist ** 2 + (dr * 0.5) ** 2)
        return dist

    def update(self, power_w: float, duration_s: float,
               reactive_frac: float | None = None) -> None:
        """Voeg een nieuw event toe en herbereken centroid (incrementeel)."""
        n = self.event_count
        self.centroid_w    = (self.centroid_w * n + power_w)    / (n + 1)
        self.centroid_dur_s = (self.centroid_dur_s * n + duration_s) / (n + 1)
        # Welford online std dev (vereenvoudigd — geen M2 tracking voor lichtgewicht impl.)
        self.std_w = abs(power_w - self.centroid_w)
        # v4.5: incrementeel gemiddelde voor reactive_fraction
        if reactive_frac is not None:
            self.centroid_reactive_frac = (
                self.centroid_reactive_frac * n + reactive_frac
            ) / (n + 1)
        self.event_count  += 1
        self.last_seen_ts  = time.time()
        self.suggested_type = _suggest_type(self.centroid_w, self.centroid_dur_s)

    def to_dict(self) -> dict:
        return {
            "cluster_id":     self.cluster_id,
            "centroid_w":     round(self.centroid_w, 1),
            "centroid_dur_s": round(self.centroid_dur_s, 1),
            "std_w":          round(self.std_w, 1),
            "event_count":    self.event_count,
            "last_seen_ts":   self.last_seen_ts,
            "suggested":      self.suggested,
            "confirmed":      self.confirmed,
            "suggested_type": self.suggested_type,
            "centroid_reactive_frac": round(self.centroid_reactive_frac, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EventCluster":
        return cls(
            cluster_id     = d.get("cluster_id", ""),
            centroid_w     = d.get("centroid_w", 0.0),
            centroid_dur_s = d.get("centroid_dur_s", 0.0),
            std_w          = d.get("std_w", 0.0),
            event_count    = d.get("event_count", 0),
            last_seen_ts   = d.get("last_seen_ts", time.time()),
            suggested      = d.get("suggested", False),
            confirmed      = d.get("confirmed", False),
            suggested_type = d.get("suggested_type", "unknown"),
            centroid_reactive_frac = d.get("centroid_reactive_frac", 0.0),
        )


# ── Hoofd-klasse ──────────────────────────────────────────────────────────────

class NILMEventClusterer:
    """
    Incrementele DBSCAN-achtige clustering van onbekende NILM-events.

    Gebruik in NILMDetector:
        clusterer.add_unknown_event(delta_w, duration_s)
        suggestions = clusterer.get_pending_suggestions()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass: HomeAssistant   = hass
        self._store: Optional[Store] = None
        self._clusters: list[EventCluster] = []
        self._pending_suggestions: list[dict] = []

    # ── Setup & persistentie ──────────────────────────────────────────────────

    async def async_setup(self) -> None:
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        try:
            data = await self._store.async_load() or {}
            self._clusters = [
                EventCluster.from_dict(c)
                for c in data.get("clusters", [])
            ]
            _LOGGER.debug("NILMEventClusterer: %d clusters geladen", len(self._clusters))
        except Exception as err:
            _LOGGER.warning("NILMEventClusterer load fout: %s", err)
            self._clusters = []

    async def async_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "clusters": [c.to_dict() for c in self._clusters],
            })
        except Exception as err:
            _LOGGER.debug("NILMEventClusterer save fout: %s", err)

    # ── Publieke API ──────────────────────────────────────────────────────────

    def add_unknown_event(self, power_w: float, duration_s: float,
                          reactive_frac: float | None = None) -> None:
        """
        Voeg een onbekend event toe aan het dichtstbijzijnde cluster,
        of maak een nieuw cluster aan.

        v4.5: reactive_frac (optioneel) = sin(phi) = Q/S uit PowerEvent.
        Verbetert clustering: een 2000W wasmachine (hoog Q) en een 2000W
        elektrische oven (Q≈0) worden nu in aparte clusters geplaatst.
        """
        if power_w < 30:
            return  # te klein om te clusteren

        best_cluster: Optional[EventCluster] = None
        best_dist = float("inf")

        for cl in self._clusters:
            if cl.confirmed:
                continue  # bevestigde clusters niet meer uitbreiden
            d = cl.distance(power_w, duration_s, reactive_frac)
            if d < best_dist:
                best_dist = d
                best_cluster = cl

        # Bepaal of event bij bestaand cluster hoort
        power_thresh = CLUSTER_EPS_W / max(power_w, 1.0)
        dur_thresh   = CLUSTER_EPS_DUR_S / max(duration_s, 1.0)
        threshold    = math.sqrt(power_thresh**2 + dur_thresh**2)

        if best_cluster and best_dist < threshold:
            best_cluster.update(power_w, duration_s, reactive_frac)
        else:
            if len(self._clusters) >= MAX_CLUSTERS:
                self._prune_old_clusters()
            new_id = f"cluster_{int(time.time() * 1000) % 100000}"
            cl = EventCluster(
                cluster_id    = new_id,
                centroid_w    = power_w,
                centroid_dur_s = duration_s,
                event_count   = 1,
                suggested_type = _suggest_type(power_w, duration_s),
                centroid_reactive_frac = reactive_frac or 0.0,
            )
            self._clusters.append(cl)

        self._check_for_suggestions()

    def get_pending_suggestions(self) -> list[dict]:
        """Geef alle clusters die een gebruikersvraag waard zijn."""
        return list(self._pending_suggestions)

    def confirm_cluster(self, cluster_id: str, device_name: str, device_type: str) -> Optional[dict]:
        """
        Markeer een cluster als bevestigd apparaat.
        Geeft de cluster-parameters terug zodat de NILMDetector
        een nieuw DeviceProfile kan aanmaken.
        """
        for cl in self._clusters:
            if cl.cluster_id == cluster_id:
                cl.confirmed = True
                cl.suggested_type = device_type
                self._pending_suggestions = [
                    s for s in self._pending_suggestions
                    if s.get("cluster_id") != cluster_id
                ]
                return {
                    "cluster_id":  cl.cluster_id,
                    "power_w":     cl.centroid_w,
                    "duration_s":  cl.centroid_dur_s,
                    "device_name": device_name,
                    "device_type": device_type,
                    "event_count": cl.event_count,
                }
        return None

    def dismiss_cluster(self, cluster_id: str) -> None:
        """Verwijder cluster permanent (gebruiker zegt: niet interessant)."""
        self._clusters = [c for c in self._clusters if c.cluster_id != cluster_id]
        self._pending_suggestions = [
            s for s in self._pending_suggestions
            if s.get("cluster_id") != cluster_id
        ]

    def get_all_clusters(self) -> list[dict]:
        """Alle clusters als dict-lijst, voor sensor-attributen."""
        return [c.to_dict() for c in self._clusters if not c.confirmed]

    # ── Interne helpers ───────────────────────────────────────────────────────

    def _check_for_suggestions(self) -> None:
        """Maak suggesties voor clusters die groot genoeg zijn."""
        for cl in self._clusters:
            if cl.confirmed or cl.suggested:
                continue
            if cl.event_count >= CLUSTER_MIN_EVENTS:
                cl.suggested = True
                dur_min = round(cl.centroid_dur_s / 60)
                self._pending_suggestions.append({
                    "cluster_id":    cl.cluster_id,
                    "centroid_w":    round(cl.centroid_w),
                    "duration_min":  dur_min,
                    "event_count":   cl.event_count,
                    "suggested_type": cl.suggested_type,
                    "title": (
                        f"Onbekend apparaat ~{round(cl.centroid_w)} W gedetecteerd"
                    ),
                    "message": (
                        f"CloudEMS heeft {cl.event_count}× een onbekend apparaat "
                        f"van ~{round(cl.centroid_w)} W gezien "
                        f"(gemiddeld {dur_min} min). "
                        f"Waarschijnlijk: {cl.suggested_type}. Wat is dit?"
                    ),
                })
                _LOGGER.info(
                    "NILM cluster suggestie: ~%dW, ~%dmin, %d events → %s",
                    cl.centroid_w, dur_min, cl.event_count, cl.suggested_type,
                )

    def _prune_old_clusters(self) -> None:
        """Verwijder de oudste niet-bevestigde clusters."""
        cutoff = time.time() - CLUSTER_MAX_AGE_DAYS * 86400
        before = len(self._clusters)
        self._clusters = [
            c for c in self._clusters
            if c.confirmed or c.last_seen_ts > cutoff
        ]
        # Als nog steeds te veel, verwijder kleinste clusters
        if len(self._clusters) >= MAX_CLUSTERS:
            unconfirmed = sorted(
                [c for c in self._clusters if not c.confirmed],
                key=lambda c: c.event_count,
            )
            to_remove = {c.cluster_id for c in unconfirmed[:5]}
            self._clusters = [c for c in self._clusters if c.cluster_id not in to_remove]
        _LOGGER.debug(
            "NILMEventClusterer: %d → %d clusters na pruning",
            before, len(self._clusters),
        )
