"""
bde_feedback.py — CloudEMS v4.3.4
===================================
BatteryDecisionEngine feedback loop.

Vergelijkt na elk uur of de genomen beslissing voordelig was:
  - "charge" om 02:00 → was dat daadwerkelijk een goedkoop uur? (vs. daggemiddelde)
  - "discharge" om 18:00 → was dat een duur uur? (vs. daggemiddelde)
  - "idle" → gemiste kans of terechte rust?

Resultaat: confidence-gewicht per source-type wordt bijgesteld.
Persistent via HA Store.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_BDE_FEEDBACK = "cloudems_bde_feedback_v1"

# Minimale prijsverschil om als "goede beslissing" te tellen
GOOD_DECISION_MARGIN_EUR = 0.02    # 2 cent voordeel
# Leertempo: hoeveel % we het gewicht aanpassen per feedback
LEARNING_RATE = 0.05
# Gewichten per source-type: 1.0 = neutraal, > 1.0 = meer vertrouwen
DEFAULT_WEIGHTS = {
    "tariff_high":            1.0,
    "tariff_low":             1.0,
    "tariff_high_hold":       1.0,
    "epex_cheap":             1.0,
    "epex_expensive":         1.0,
    "epex_cheap_pv_tomorrow": 1.0,
    "peak_shaving":           1.0,
    "off_peak_tariff":        1.0,
    "pv_tomorrow_makeroom":   1.0,
    "default":                1.0,
    "safety_soc_min":         1.0,
    "safety_soc_max":         1.0,
}


@dataclass
class DecisionRecord:
    """Eén uitgevoerde beslissing voor feedback-tracking."""
    timestamp:    float
    action:       str     # charge / discharge / idle
    source:       str
    confidence:   float
    epex_at_time: Optional[float]


@dataclass
class FeedbackResult:
    source:        str
    was_good:      bool
    price_margin:  float  # positief = voordeel, negatief = nadeel
    new_weight:    float


class BDEFeedbackTracker:
    """
    Bijhoudt beslissingen en geeft achteraf feedback.

    Gebruik:
        tracker = BDEFeedbackTracker(store)
        await tracker.async_load()

        # Direct na beslissing:
        tracker.record(decision, epex_price)

        # Elk uur (na uurwisseling):
        results = tracker.evaluate_last_hour(avg_price_today)

        # BDE leest gewichten:
        weight = tracker.get_weight("epex_cheap")
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        self._weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        # v1.32: per-uur gewichten — [bron][uur] = float
        # Sommige beslissingstypes zijn op bepaalde uren historisch beter dan anderen.
        # Bijv. "epex_cheap" om 03:00 is betrouwbaarder dan om 14:00.
        self._hour_weights: dict[str, list[float]] = {}
        self._pending: list[DecisionRecord] = []
        self._history: list[dict] = []
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw:
                self._weights = {**DEFAULT_WEIGHTS, **raw.get("weights", {})}
                self._history = raw.get("history", [])[-168:]
                # Herstel uur-gewichten
                for src, hw in raw.get("hour_weights", {}).items():
                    if isinstance(hw, list) and len(hw) == 24:
                        self._hour_weights[src] = [float(v) for v in hw]
                _LOGGER.debug(
                    "BDEFeedbackTracker: %d gewichten, %d history-items, %d uur-profielen geladen",
                    len(self._weights), len(self._history), len(self._hour_weights),
                )
        except Exception as err:
            _LOGGER.warning("BDEFeedbackTracker: laden mislukt: %s", err)
        self._loaded = True

    async def async_save(self) -> None:
        try:
            await self._store.async_save({
                "weights":      self._weights,
                "hour_weights": self._hour_weights,
                "history":      self._history[-168:],
            })
        except Exception as err:
            _LOGGER.warning("BDEFeedbackTracker: opslaan mislukt: %s", err)

    def record(
        self,
        action: str,
        source: str,
        confidence: float,
        timestamp: float,
        epex_price: Optional[float],
    ) -> None:
        """Sla beslissing op voor latere evaluatie."""
        self._pending.append(DecisionRecord(
            timestamp    = timestamp,
            action       = action,
            source       = source,
            confidence   = confidence,
            epex_at_time = epex_price,
        ))
        # Houd max 48 pending (2 dagen)
        if len(self._pending) > 48:
            self._pending = self._pending[-48:]

    def evaluate_and_learn(
        self,
        avg_price_today: float,
    ) -> list[FeedbackResult]:
        """
        Evalueer pending beslissingen die al minstens 1 uur oud zijn.
        Past gewichten aan op basis van of de beslissing voordelig was.
        """
        if avg_price_today <= 0 or not self._pending:
            return []

        import time as _t
        now = _t.time()
        results = []
        still_pending = []

        for rec in self._pending:
            age_h = (now - rec.timestamp) / 3600.0
            if age_h < 1.0:
                still_pending.append(rec)
                continue

            # Beoordeel: was de beslissing goed?
            epex = rec.epex_at_time
            was_good = False
            margin   = 0.0

            if epex is not None:
                if rec.action == "charge":
                    # Goed als we goedkoop laadden (< gemiddelde - marge)
                    margin   = avg_price_today - epex
                    was_good = margin >= GOOD_DECISION_MARGIN_EUR
                elif rec.action == "discharge":
                    # Goed als we duur ontlaadden (> gemiddelde + marge)
                    margin   = epex - avg_price_today
                    was_good = margin >= GOOD_DECISION_MARGIN_EUR
                else:  # idle
                    # Idle is "neutraal" — geen aanpassing
                    still_pending.append(rec)
                    continue

            # Gewicht aanpassen — globaal
            current_w = self._weights.get(rec.source, 1.0)
            if was_good:
                new_w = min(1.5, current_w + LEARNING_RATE)
            else:
                new_w = max(0.5, current_w - LEARNING_RATE * 0.5)
            self._weights[rec.source] = round(new_w, 3)

            # v1.32: uur-gewichten aanpassen
            hour = int((rec.timestamp % 86400) // 3600)
            if rec.source not in self._hour_weights:
                self._hour_weights[rec.source] = [1.0] * 24
            hw = self._hour_weights[rec.source]
            if was_good:
                hw[hour] = round(min(1.8, hw[hour] + LEARNING_RATE * 0.5), 3)
            else:
                hw[hour] = round(max(0.3, hw[hour] - LEARNING_RATE * 0.25), 3)

            result = FeedbackResult(
                source       = rec.source,
                was_good     = was_good,
                price_margin = round(margin, 4),
                new_weight   = new_w,
            )
            results.append(result)
            self._history.append({
                "ts":       rec.timestamp,
                "action":   rec.action,
                "source":   rec.source,
                "was_good": was_good,
                "margin":   round(margin, 4),
                "weight":   new_w,
            })

            _LOGGER.debug(
                "BDE feedback: %s/%s %s (marge €%.3f) → gewicht %.2f",
                rec.action, rec.source,
                "✅" if was_good else "❌",
                margin, new_w,
            )

        self._pending = still_pending
        return results

    def get_weight(self, source: str) -> float:
        """Geeft het geleerde gewicht voor een source-type terug (globaal)."""
        return self._weights.get(source, 1.0)

    def get_weight_for_hour(self, source: str, hour: int) -> float:
        """
        v1.32: Gecombineerd gewicht = globaal_gewicht × uur_gewicht.
        BDE kan dit gebruiken voor confidence-aanpassing voor het huidige uur.
        """
        global_w = self._weights.get(source, 1.0)
        hour_w   = self._hour_weights.get(source, [1.0] * 24)[hour % 24]
        return round(global_w * hour_w, 3)

    def get_hour_profile(self, source: str) -> list[float]:
        """Geeft het 24-uurs gewichtsprofiel voor een source-type."""
        return self._hour_weights.get(source, [1.0] * 24)

    def get_diagnostics(self) -> dict:
        # Beste uur per source (uur met hoogste hour_weight)
        best_hours = {}
        for src, hw in self._hour_weights.items():
            best_h = hw.index(max(hw))
            best_hours[src] = best_h
        return {
            "weights":        self._weights,
            "hour_profiles":  len(self._hour_weights),
            "best_hours":     best_hours,
            "pending_count":  len(self._pending),
            "history_count":  len(self._history),
            "recent": self._history[-5:],
        }
