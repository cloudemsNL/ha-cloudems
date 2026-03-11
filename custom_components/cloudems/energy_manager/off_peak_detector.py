# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
off_peak_detector.py — CloudEMS v4.0.4
=======================================
Detecteert automatisch of de gebruiker een dal/piek tarief heeft,
op basis van prijspatronen — zonder handmatige invoer.

Algoritme:
  1. Verzamel 30 dagen uurprijzen (uit price_hour_history)
  2. Bereken gemiddelde prijs per uur van de dag
  3. Als het verschil nacht vs. dag > THRESHOLD → dal-tarief gedetecteerd
  4. Leer de typische dal-uren (bijv. 23:00-7:00) automatisch

Output voor BDE:
  - is_off_peak_now: bool
  - off_peak_hours:  set van uur-nummers (bijv. {23, 0, 1, 2, 3, 4, 5, 6})
  - price_ratio:     nacht/dag prijsratio (< 0.7 = duidelijk dal-tarief)

Wordt door de BatteryDecisionEngine gebruikt als extra laag:
  - Dal-uur + accu niet vol → laden
  - Piek-uur + accu vol → ontladen
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

# Drempel: nacht/dag ratio < dit → dal-tarief gedetecteerd
OFFPEAK_RATIO_THRESHOLD = 0.75
# Minimum uurprijzen nodig voor detectie (7 dagen × 24 uur)
MIN_PRICE_SAMPLES = 168
# Nacht-uren voor eerste-pass detectie
DEFAULT_NIGHT_HOURS = frozenset(range(0, 7)) | frozenset(range(23, 24))


@dataclass
class OffPeakStatus:
    detected:        bool         # dal-tarief gedetecteerd
    is_off_peak_now: bool         # huidig uur = dal-uur
    off_peak_hours:  set          # set van dal-uur nummers
    price_ratio:     float        # nacht/dag ratio (lager = groter verschil)
    avg_day_eur:     float        # gemiddelde dagprijs
    avg_night_eur:   float        # gemiddelde nachtprijs
    confidence:      float        # 0.0–1.0


class OffPeakDetector:
    """
    Detecteert dal/piek tarief op basis van prijshistorie.

    Gebruik in coordinator:
        detector = OffPeakDetector()
        status = detector.analyze(price_hour_history)
    """

    def analyze(
        self,
        price_hour_history: list,   # [{ts, price, kwh_net}, ...]
        current_hour: int | None = None,
    ) -> OffPeakStatus:
        """
        Analyseer de prijshistorie op dal-tarief patroon.
        price_hour_history: lijst van dicts met 'ts' en 'price'.
        """
        if len(price_hour_history) < MIN_PRICE_SAMPLES:
            # Nog te weinig data — gebruik standaard nachturen als fallback
            now_h = current_hour if current_hour is not None else datetime.now(timezone.utc).hour
            return OffPeakStatus(
                detected=False,
                is_off_peak_now=now_h in DEFAULT_NIGHT_HOURS,
                off_peak_hours=set(DEFAULT_NIGHT_HOURS),
                price_ratio=1.0,
                avg_day_eur=0.0,
                avg_night_eur=0.0,
                confidence=0.0,
            )

        # Bouw uurgemiddelden op
        hour_prices: dict[int, list[float]] = {h: [] for h in range(24)}
        for entry in price_hour_history:
            try:
                ts    = entry.get("ts", 0)
                price = float(entry.get("price", 0) or 0)
                if price <= 0:
                    continue
                hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
                hour_prices[hour].append(price)
            except Exception:
                continue

        # Gemiddelde per uur
        hour_avg: dict[int, float] = {}
        for h, prices in hour_prices.items():
            if prices:
                hour_avg[h] = sum(prices) / len(prices)

        if len(hour_avg) < 12:
            now_h = current_hour if current_hour is not None else datetime.now(timezone.utc).hour
            return OffPeakStatus(
                detected=False,
                is_off_peak_now=now_h in DEFAULT_NIGHT_HOURS,
                off_peak_hours=set(DEFAULT_NIGHT_HOURS),
                price_ratio=1.0, avg_day_eur=0.0, avg_night_eur=0.0,
                confidence=0.0,
            )

        # Splits in nacht (22:00–7:00) en dag (8:00–21:00) voor eerste schatting
        night_h = {h for h in range(24) if h <= 6 or h >= 22}
        day_h   = set(range(24)) - night_h

        night_prices = [hour_avg[h] for h in night_h if h in hour_avg]
        day_prices   = [hour_avg[h] for h in day_h   if h in hour_avg]

        avg_night = sum(night_prices) / len(night_prices) if night_prices else 0
        avg_day   = sum(day_prices)   / len(day_prices)   if day_prices   else 0

        if avg_day <= 0:
            ratio = 1.0
        else:
            ratio = round(avg_night / avg_day, 4)

        detected = ratio < OFFPEAK_RATIO_THRESHOLD

        # Confidence: hoeveel data hebben we?
        total_samples = sum(len(v) for v in hour_prices.values())
        confidence = round(min(1.0, total_samples / (30 * 24)), 2)

        if detected:
            # Verfijn: welke uren zijn écht goedkoop (< gemiddelde dag × 0.85)?
            threshold = avg_day * 0.85
            off_peak_hours = {h for h, p in hour_avg.items() if p <= threshold}
            # Zorg dat het aaneengesloten blok is (vermijd losse uren)
            if len(off_peak_hours) < 3:
                off_peak_hours = set(DEFAULT_NIGHT_HOURS)
        else:
            off_peak_hours = set()

        now_h = current_hour if current_hour is not None else datetime.now(timezone.utc).hour
        is_off_peak_now = now_h in off_peak_hours if detected else False

        _LOGGER.debug(
            "OffPeakDetector: ratio=%.2f detected=%s uren=%s conf=%.0f%%",
            ratio, detected,
            sorted(off_peak_hours) if off_peak_hours else "—",
            confidence * 100,
        )

        return OffPeakStatus(
            detected        = detected,
            is_off_peak_now = is_off_peak_now,
            off_peak_hours  = off_peak_hours,
            price_ratio     = ratio,
            avg_day_eur     = round(avg_day, 4),
            avg_night_eur   = round(avg_night, 4),
            confidence      = confidence,
        )

    def to_dict(self, status: OffPeakStatus) -> dict:
        return {
            "detected":        status.detected,
            "is_off_peak_now": status.is_off_peak_now,
            "off_peak_hours":  sorted(status.off_peak_hours),
            "price_ratio":     status.price_ratio,
            "avg_day_eur":     status.avg_day_eur,
            "avg_night_eur":   status.avg_night_eur,
            "confidence":      status.confidence,
        }
