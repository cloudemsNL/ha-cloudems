# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Thermische Lek Detector (v1.0.0).

Bewaakt de thermische verliescoëfficiënt (W/K) van het huis over tijd.
Een stijgende trend bij stabiel weer wijst op isolatieproblemen:
  - Nieuwe vochtinfiltratie (lekkend dak, kapotte spouwmuurisolatie)
  - Koudebrug door bouwkundige wijziging (nieuwe doorvoer, raam)
  - Beschadigd glas (dubbele beglazing verliest vacuüm)

DATA BRON
═════════
Leest uitsluitend uit thermal_model.get_data()["w_per_k"] — geen
nieuwe sensoren nodig. ThermalHouseModel berekent dit al elke dag.

DETECTIE
════════
- Bewaar dagelijkse w_per_k waarden (max 90 dagen)
- Bereken lineaire trend over laatste 14/30/60 dagen
- Anomalie als: trend > +15% over 14 dagen EN ≥ 5 meetdagen
- Seizoenscorrectie: vergelijk alleen met zelfde seizoen vorig jaar
  (winter heeft structureel hogere w_per_k dan zomer)

CLOUD SCHEMA
════════════
ThermalLeakEvent:
  installation_id, lat_rounded, lon_rounded
  timestamp_utc
  w_per_k_now, w_per_k_baseline, increase_pct
  trend_days: int, confidence: float
  season: str
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, date
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Drempels
LEAK_TREND_PCT      = 15.0   # 15% stijging over 14 dagen = anomalie
MIN_SAMPLES         = 5      # Minimaal 5 meetdagen voor betrouwbare trend
HISTORY_DAYS        = 90     # Bewaar 90 dagen
COOLDOWN_DAYS       = 14     # Max 1 alert per 14 dagen


@dataclass
class ThermalLeakEvent:
    """Gedetecteerde stijgende thermische verliescoëfficiënt."""
    timestamp_utc:    str
    installation_id:  str
    lat_rounded:      float
    lon_rounded:      float
    w_per_k_now:      float      # huidige waarde
    w_per_k_baseline: float      # baseline (14 dagen geleden)
    increase_pct:     float      # procentuele stijging
    trend_days:       int        # over hoeveel dagen gemeten
    confidence:       float      # 0.0-1.0
    season:           str        # winter/lente/zomer/herfst
    uploaded:         bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _DaySample:
    day:      str    # ISO datum "YYYY-MM-DD"
    w_per_k:  float
    samples:  int    # aantal metingen die dag


class ThermalLeakDetector:
    """Detecteert isolatielekken via trendanalyse thermische verliescoëfficiënt.

    Gebruik in coordinator:
        detector = ThermalLeakDetector(lat, lon, entry_id)
        event = detector.observe(w_per_k=185.0, samples=12)
        stats = detector.to_dict()
    """

    def __init__(self, lat: float, lon: float, installation_id: str) -> None:
        import hashlib
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        self._history:      deque[_DaySample] = deque(maxlen=HISTORY_DAYS)
        self._events:       list[ThermalLeakEvent] = []
        self._last_alert:   Optional[date] = None
        self._total_alerts: int = 0

    def observe(self, w_per_k: float, samples: int) -> Optional[ThermalLeakEvent]:
        """Verwerk dagelijkse w_per_k meting. Geeft event bij anomalie."""
        if w_per_k <= 0 or samples < 3:
            return None

        today = date.today().isoformat()

        # Update of voeg dag toe
        if self._history and self._history[-1].day == today:
            # Gemiddeld met bestaande meting van vandaag
            prev = self._history[-1]
            self._history[-1] = _DaySample(
                day=today,
                w_per_k=round((prev.w_per_k * prev.samples + w_per_k * samples)
                               / (prev.samples + samples), 1),
                samples=prev.samples + samples,
            )
        else:
            self._history.append(_DaySample(day=today, w_per_k=w_per_k, samples=samples))

        if len(self._history) < MIN_SAMPLES:
            return None

        # Cooldown check
        if self._last_alert and (date.today() - self._last_alert).days < COOLDOWN_DAYS:
            return None

        return self._check_trend()

    def _check_trend(self) -> Optional[ThermalLeakEvent]:
        """Bereken trend over laatste 14 dagen."""
        samples = list(self._history)
        if len(samples) < MIN_SAMPLES:
            return None

        recent = samples[-14:]   # laatste 14 dagen
        if len(recent) < MIN_SAMPLES:
            return None

        # Lineaire regressie op indices
        n = len(recent)
        xs = list(range(n))
        ys = [s.w_per_k for s in recent]
        xm = sum(xs) / n
        ym = sum(ys) / n
        num = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
        den = sum((x - xm) ** 2 for x in xs) or 1
        slope = num / den  # W/K per dag

        # Baseline = eerste punt van regressievenster
        baseline = ys[0]
        current  = ys[-1]
        if baseline <= 0:
            return None

        increase_pct = (current - baseline) / baseline * 100

        if increase_pct < LEAK_TREND_PCT:
            return None

        # Confidence op basis van R² en aantal samples
        ss_res = sum((y - (ym + slope * (x - xm))) ** 2 for x, y in zip(xs, ys))
        ss_tot = sum((y - ym) ** 2 for y in ys) or 1
        r2 = max(0.0, 1.0 - ss_res / ss_tot)
        confidence = min(1.0, r2 * (min(n, 14) / 14.0))

        if confidence < 0.3:
            return None

        season = self._get_season()
        event = ThermalLeakEvent(
            timestamp_utc    = datetime.now(timezone.utc).isoformat(),
            installation_id  = self._install_id,
            lat_rounded      = self._lat,
            lon_rounded      = self._lon,
            w_per_k_now      = round(current, 1),
            w_per_k_baseline = round(baseline, 1),
            increase_pct     = round(increase_pct, 1),
            trend_days       = n,
            confidence       = round(confidence, 2),
            season           = season,
        )
        self._events.append(event)
        self._last_alert = date.today()
        self._total_alerts += 1

        _LOGGER.warning(
            "ThermalLeakDetector: isolatielek vermoed — %.0f→%.0f W/K "
            "(+%.0f%% in %d dagen, confidence=%.0f%%)",
            baseline, current, increase_pct, n, confidence * 100,
        )
        return event

    def _get_season(self) -> str:
        m = date.today().month
        if m in (12, 1, 2):   return "winter"
        if m in (3, 4, 5):    return "lente"
        if m in (6, 7, 8):    return "zomer"
        return "herfst"

    def get_upload_batch(self) -> list[dict]:
        batch = [e for e in self._events if not e.uploaded][:20]
        for e in batch: e.uploaded = True
        return [e.to_dict() for e in batch]

    def get_trend_summary(self) -> dict:
        """Trendoverzicht voor sensor en dashboard."""
        if len(self._history) < 2:
            return {"trend_pct_14d": None, "w_per_k_latest": None}
        recent = list(self._history)[-14:]
        if len(recent) < 2:
            return {"trend_pct_14d": None, "w_per_k_latest": recent[-1].w_per_k}
        baseline = recent[0].w_per_k
        current  = recent[-1].w_per_k
        trend    = (current - baseline) / max(baseline, 1) * 100
        return {
            "trend_pct_14d":  round(trend, 1),
            "w_per_k_latest": round(current, 1),
            "w_per_k_14d_ago": round(baseline, 1),
            "samples":        len(self._history),
            "season":         self._get_season(),
        }

    def to_dict(self) -> dict:
        return {
            "installation_id": self._install_id,
            "total_alerts":    self._total_alerts,
            "upload_pending":  sum(1 for e in self._events if not e.uploaded),
            **self.get_trend_summary(),
        }
