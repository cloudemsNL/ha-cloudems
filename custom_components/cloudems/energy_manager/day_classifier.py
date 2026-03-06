# -*- coding: utf-8 -*-
"""
CloudEMS Dag-Type Classificatie — v1.0.0

Leert automatisch onderscheid te maken tussen dag-types op basis van het
uurlijkse verbruiksprofiel, zonder handmatige configuratie.

Dag-types:
  • work_away     : Kantoordag — laag verbruik overdag, piek 's avonds
  • work_home     : Thuiswerk  — hoog verbruik overdag + avondpiek
  • weekend       : Weekend    — andere piek-tijden (later begin)
  • holiday       : Vakantie   — alleen standby / extreem laag
  • unknown       : Nog niet genoeg data

Methode:
  1. Bouw een 24-dimensionaal verbruiksprofiel per dag
  2. Normaliseer per totaalverbruik (patroon, niet absoluut niveau)
  3. Vergelijk met geleerde prototype-profielen via cosinusgelijkenis
  4. Na 60 dagen: zelflerend met k-means-achtige aanpak

Gebruik:
  classifier.observe_hour(hour, power_w)     # elke 10s → aggregeer per uur
  day_type = classifier.classify_today()
  forecast_kwh = classifier.expected_kwh(day_type)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_day_classifier_v1"
STORAGE_VERSION = 1

MIN_DAYS_BEFORE_LEARNING = 14     # Wachten tot er genoeg data is
SAVE_INTERVAL_S           = 600
ALPHA_PROTOTYPE           = 0.10  # Prototype-update snelheid

# Initiële prototype-profielen (genormaliseerd 0-1 per uur)
# Index = uur van de dag (0-23)
_INITIAL_PROTOTYPES: dict[str, list[float]] = {
    "work_away": [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.3,   # 00-05
        0.5, 0.6, 0.4, 0.3, 0.3, 0.3,   # 06-11
        0.3, 0.3, 0.3, 0.3, 0.4, 0.6,   # 12-17
        0.9, 1.0, 0.9, 0.7, 0.5, 0.4,   # 18-23
    ],
    "work_home": [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.3,   # 00-05
        0.5, 0.7, 0.8, 0.8, 0.8, 0.7,   # 06-11
        0.7, 0.7, 0.7, 0.7, 0.8, 0.8,   # 12-17
        0.9, 1.0, 0.9, 0.7, 0.5, 0.4,   # 18-23
    ],
    "weekend": [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.2,   # 00-05
        0.3, 0.4, 0.6, 0.7, 0.8, 0.9,   # 06-11
        0.8, 0.8, 0.7, 0.7, 0.7, 0.8,   # 12-17
        0.9, 1.0, 0.9, 0.7, 0.5, 0.4,   # 18-23
    ],
    "holiday": [
        0.2, 0.2, 0.2, 0.2, 0.2, 0.2,   # 00-05
        0.3, 0.3, 0.3, 0.3, 0.3, 0.3,   # 06-11
        0.3, 0.3, 0.3, 0.3, 0.3, 0.3,   # 12-17
        0.4, 0.4, 0.3, 0.3, 0.2, 0.2,   # 18-23
    ],
}

DAY_TYPE_LABELS = {
    "work_away": "Kantoordag",
    "work_home": "Thuiswerkdag",
    "weekend":   "Weekend/vrijdag",
    "holiday":   "Vakantie/standby",
    "unknown":   "Onbekend",
}

DAY_TYPE_EXPECTED_KWH = {
    "work_away": 11.0,
    "work_home": 18.0,
    "weekend":   15.0,
    "holiday":   6.0,
    "unknown":   13.0,
}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosinusgelijkenis tussen twee vectoren."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _normalize(profile: list[float]) -> list[float]:
    """Normaliseer naar maximum = 1.0."""
    mx = max(profile) if profile else 1.0
    if mx == 0:
        return profile
    return [v / mx for v in profile]


@dataclass
class DayRecord:
    date: str
    profile: list[float]          # 24 uur, Wh per uur
    total_kwh: float
    day_type: str


@dataclass
class DayTypeData:
    """Output van de dag-classificatie."""
    today_type: str
    today_label: str
    confidence: float             # 0.0–1.0
    expected_kwh: float
    total_days_learned: int
    prototype_similarity: dict[str, float]  # type → similarity score
    advice: str


class DayTypeClassifier:
    """
    Zelflerend dag-type classificatiesysteem.

    Gebruik vanuit coordinator:
        classifier.observe_power(power_w)     # elke 10s
        data = classifier.get_data()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Huidige dag accumulatie (Wh per uur)
        self._today_profile: list[float] = [0.0] * 24
        self._today_date    = ""
        self._tick_s        = 10.0

        # Geleerde prototypen (gemiddeld verbruiksprofiel per dag-type)
        self._prototypes: dict[str, list[float]] = {
            k: list(v) for k, v in _INITIAL_PROTOTYPES.items()
        }

        # Geschiedenis van geclassificeerde dagen
        self._day_history: list[DayRecord] = []
        self._total_days  = 0

        # Verwachte kWh per dag-type (geleerd)
        self._expected_kwh: dict[str, float] = dict(DAY_TYPE_EXPECTED_KWH)

        self._dirty      = False
        self._last_save  = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        self._prototypes = saved.get("prototypes", self._prototypes)
        self._expected_kwh = saved.get("expected_kwh", self._expected_kwh)
        self._total_days = saved.get("total_days", 0)
        _LOGGER.info("DayTypeClassifier: geladen (%d geleerde dagen)", self._total_days)

    def observe_power(self, power_w: float) -> None:
        """Registreer huidig vermogen (elke 10s)."""
        now   = datetime.now(timezone.utc)
        hour  = now.hour
        today = now.strftime("%Y-%m-%d")

        # Dag-reset: sla vorige dag op
        if today != self._today_date:
            if self._today_date:
                self._finalize_day(self._today_date, self._today_profile)
            self._today_date    = today
            self._today_profile = [0.0] * 24

        # Accumuleer Wh
        self._today_profile[hour] += power_w * (self._tick_s / 3600.0)

    def _finalize_day(self, date: str, profile_wh: list[float]) -> None:
        """Sla dag op en update prototype."""
        total_kwh = sum(profile_wh) / 1000.0
        if total_kwh < 0.5:
            return   # Te weinig data (dag niet begonnen?)

        day_type, _ = self._classify_profile(profile_wh)

        # Update prototype (exponentieel voortschrijdend gemiddelde)
        if self._total_days >= MIN_DAYS_BEFORE_LEARNING:
            norm = _normalize(profile_wh)
            proto = self._prototypes[day_type]
            self._prototypes[day_type] = [
                ALPHA_PROTOTYPE * n + (1 - ALPHA_PROTOTYPE) * p
                for n, p in zip(norm, proto)
            ]
            # Update verwacht kWh
            old_kwh = self._expected_kwh.get(day_type, total_kwh)
            self._expected_kwh[day_type] = 0.1 * total_kwh + 0.9 * old_kwh

        self._total_days += 1
        self._dirty = True

        _LOGGER.debug("DayTypeClassifier: %s geclassificeerd als '%s' (%.1f kWh)", date, day_type, total_kwh)

    def _classify_profile(self, profile_wh: list[float]) -> tuple[str, float]:
        """Classificeer een profiel → (dag_type, confidence)."""
        norm = _normalize(profile_wh)
        similarities = {
            dt: _cosine_similarity(norm, proto)
            for dt, proto in self._prototypes.items()
        }
        best_type = max(similarities, key=lambda k: similarities[k])
        best_sim  = similarities[best_type]

        # Lage confidence als het gat met de tweede te klein is
        sorted_sims = sorted(similarities.values(), reverse=True)
        gap = sorted_sims[0] - sorted_sims[1] if len(sorted_sims) > 1 else 1.0
        confidence = min(1.0, gap * 5)   # schaal gap naar 0-1

        return best_type, round(confidence, 2)

    def classify_today(self) -> tuple[str, float]:
        """Geef dag-type en confidence voor vandaag (op basis van data tot nu)."""
        if max(self._today_profile) < 10:   # < 10 Wh → te vroeg
            return "unknown", 0.0
        return self._classify_profile(self._today_profile)

    def get_data(self) -> DayTypeData:
        """Geef dag-type data terug voor de sensor."""
        day_type, confidence = self.classify_today()
        norm = _normalize(self._today_profile)

        similarities = {
            dt: round(_cosine_similarity(norm, proto), 3)
            for dt, proto in self._prototypes.items()
        } if max(self._today_profile) > 10 else {}

        expected_kwh = self._expected_kwh.get(day_type, DAY_TYPE_EXPECTED_KWH.get(day_type, 13.0))
        label        = DAY_TYPE_LABELS.get(day_type, "Onbekend")

        if self._total_days < MIN_DAYS_BEFORE_LEARNING:
            advice = f"Nog {MIN_DAYS_BEFORE_LEARNING - self._total_days} dag(en) nodig voor betrouwbare classificatie."
        elif day_type == "unknown":
            advice = "Dag-type nog niet bepaalbaar (te vroeg op de dag)."
        elif confidence > 0.6:
            advice = f"Hoog vertrouwen: dit is een {label.lower()}. Verwacht verbruik: ~{expected_kwh:.0f} kWh."
        else:
            advice = f"Waarschijnlijk een {label.lower()} (laag vertrouwen). Verwacht verbruik: ~{expected_kwh:.0f} kWh."

        return DayTypeData(
            today_type            = day_type,
            today_label           = label,
            confidence            = confidence,
            expected_kwh          = round(expected_kwh, 1),
            total_days_learned    = self._total_days,
            prototype_similarity  = similarities,
            advice                = advice,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "prototypes":   self._prototypes,
                "expected_kwh": self._expected_kwh,
                "total_days":   self._total_days,
            })
            self._dirty     = False
            self._last_save = time.time()
