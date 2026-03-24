"""
CloudEMS AI Learning Log — v1.0.0

Structured log of what happened, what the AI decided, and what the
correct action would have been. This is the training data for future
Seq2Point models and for debugging AI decisions.

Every entry contains:
  - Full feature vector at decision time
  - What action was taken (and by which module)
  - What outcome was measured N minutes later
  - What the "correct" action would have been (hindsight label)
  - Which thresholds were active at the time

This log is:
  1. Stored locally (HA Storage, rolling 7 days)
  2. Uploaded to AdaptiveHome cloud (anonymized, opt-in) for community model
  3. Used by seq2point_nilm.py for supervised NILM learning

Privacy: no personal data, only power measurements and decisions.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_ai_learning_log_v1"
STORAGE_VERSION = 1
MAX_ENTRIES     = 2016   # 7 days × 288 entries/day (5-min intervals)
SAVE_INTERVAL   = 300    # save every 5 minutes


@dataclass
class LearningEntry:
    """One complete learning episode."""
    ts:              float           # unix timestamp
    hour:            int             # hour of day
    dow:             int             # day of week
    season:          str             # spring/summer/autumn/winter

    # State snapshot
    solar_w:         float
    grid_w:          float
    battery_soc:     float
    battery_w:       float
    house_w:         float
    epex_eur_kwh:    float
    epex_avg_today:  float
    temp_out:        float
    cloud_pct:       float

    # Phase currents
    l1_a:            float
    l2_a:            float
    l3_a:            float

    # AI decision
    ai_label:        str             # what AI suggested
    ai_confidence:   float
    ai_source:       str             # "knn" | "bootstrap" | "rule"
    action_taken:    str             # what actually happened
    action_source:   str             # "bde" | "scheduler" | "manual" | "ai_hint"

    # Outcome (filled in later)
    outcome_reward:  Optional[float] = None
    hindsight_label: Optional[str]   = None  # what should have happened
    outcome_ts:      Optional[float] = None

    # Active thresholds at decision time
    thresholds:      dict = field(default_factory=dict)

    # NILM active devices
    active_devices:  list = field(default_factory=list)


class AILearningLog:
    """
    Structured learning log for AI training and debugging.

    Usage:
        log.record(entry)          # record a decision episode
        log.update_outcome(ts, reward, hindsight)  # fill in outcome
        log.get_recent(n=100)      # get recent entries
        log.export_training_data() # get entries suitable for model training
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass    = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entries: deque = deque(maxlen=MAX_ENTRIES)
        self._last_save_ts   = 0.0
        self._dirty          = False
        self._n_total        = 0   # total entries ever recorded

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for e in saved.get("entries", []):
            try:
                self._entries.append(LearningEntry(**e))
            except Exception:
                pass
        self._n_total = saved.get("n_total", len(self._entries))
        _LOGGER.info(
            "AI Learning Log: loaded %d entries (total ever: %d)",
            len(self._entries), self._n_total
        )

    def record(self, entry: LearningEntry) -> None:
        """Record a new decision episode."""
        self._entries.append(entry)
        self._n_total += 1
        self._dirty    = True

    def record_from_data(
        self,
        data:         dict,
        ai_label:     str,
        ai_conf:      float,
        ai_source:    str,
        action_taken: str,
        action_source: str,
        thresholds:   dict,
    ) -> LearningEntry:
        """Convenience method: build entry from coordinator data dict."""
        now     = datetime.now(timezone.utc)
        phases  = data.get("phases", {})
        season  = data.get("season", "transition")

        entry = LearningEntry(
            ts             = time.time(),
            hour           = now.hour,
            dow            = now.weekday(),
            season         = season,
            solar_w        = float(data.get("solar_power",  0) or 0),
            grid_w         = float(data.get("grid_power",   0) or 0),
            battery_soc    = float(data.get("battery_soc",  0) or 0),
            battery_w      = float(data.get("battery_power",0) or 0),
            house_w        = float(data.get("house_power",  0) or 0),
            epex_eur_kwh   = float(data.get("current_price",0) or 0),
            epex_avg_today = float(data.get("avg_price_today",0) or 0),
            temp_out       = float(data.get("outdoor_temp_c", data.get("temp_outside",0)) or 0),
            cloud_pct      = float(data.get("cloud_cover_pct",50) or 50),
            l1_a           = float((phases.get("L1") or {}).get("current_a", 0)),
            l2_a           = float((phases.get("L2") or {}).get("current_a", 0)),
            l3_a           = float((phases.get("L3") or {}).get("current_a", 0)),
            ai_label       = ai_label,
            ai_confidence  = ai_conf,
            ai_source      = ai_source,
            action_taken   = action_taken,
            action_source  = action_source,
            thresholds     = thresholds,
            active_devices = [
                d.get("label","") for d in data.get("nilm_running_devices", [])
                if d.get("label")
            ],
        )
        self.record(entry)
        return entry

    def update_outcome(
        self,
        decision_ts:      float,
        reward:           float,
        hindsight_label:  Optional[str] = None,
        window_s:         float = 900,
    ) -> bool:
        """
        Find the entry nearest to decision_ts and fill in the outcome.
        Returns True if found and updated.
        """
        best   = None
        best_d = window_s

        for entry in self._entries:
            d = abs(entry.ts - decision_ts)
            if d < best_d:
                best_d = d
                best   = entry

        if best is None:
            return False

        best.outcome_reward  = round(reward, 3)
        best.hindsight_label = hindsight_label
        best.outcome_ts      = time.time()
        self._dirty = True
        return True

    def get_recent(self, n: int = 50) -> list[LearningEntry]:
        entries = list(self._entries)
        return entries[-n:]

    def export_training_data(self, min_reward: float = -2.0) -> list[dict]:
        """
        Export entries with outcomes for model training.
        Filters to entries where outcome was measured.
        """
        return [
            {
                "features": [
                    e.hour / 23.0,
                    e.dow / 6.0,
                    e.solar_w / 10000.0,
                    e.grid_w / 10000.0,
                    e.battery_soc / 100.0,
                    e.battery_w / 5000.0,
                    e.house_w / 10000.0,
                    e.epex_eur_kwh / 1.0,
                    e.epex_avg_today / 1.0,
                    e.temp_out / 40.0,
                    e.cloud_pct / 100.0,
                    e.l1_a / 25.0,
                    e.l2_a / 25.0,
                    e.l3_a / 25.0,
                ],
                "label":          e.hindsight_label or e.ai_label,
                "action_taken":   e.action_taken,
                "reward":         e.outcome_reward,
                "weight":         max(0.1, 0.5 + (e.outcome_reward or 0)),
            }
            for e in self._entries
            if e.outcome_reward is not None and (e.outcome_reward or 0) >= min_reward
        ]

    @property
    def stats(self) -> dict:
        entries = list(self._entries)
        with_outcome = [e for e in entries if e.outcome_reward is not None]
        avg_reward   = (
            sum(e.outcome_reward for e in with_outcome) / len(with_outcome)
            if with_outcome else 0.0
        )
        # Label distribution
        label_counts: dict[str, int] = {}
        for e in entries:
            label_counts[e.ai_label] = label_counts.get(e.ai_label, 0) + 1

        return {
            "n_entries":      len(entries),
            "n_with_outcome": len(with_outcome),
            "n_total_ever":   self._n_total,
            "avg_reward":     round(avg_reward, 3),
            "label_counts":   label_counts,
            "training_ready": len(with_outcome) >= 50,
        }

    async def async_maybe_save(self) -> None:
        now = time.time()
        if self._dirty and (now - self._last_save_ts) >= SAVE_INTERVAL:
            await self._save()

    async def async_save(self) -> None:
        await self._save()

    async def _save(self) -> None:
        try:
            entries = list(self._entries)
            await self._store.async_save({
                "n_total": self._n_total,
                "entries": [asdict(e) for e in entries[-MAX_ENTRIES:]],
            })
            self._last_save_ts = time.time()
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("AI Learning Log save error: %s", exc)
