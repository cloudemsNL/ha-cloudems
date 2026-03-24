"""
CloudEMS EV Pattern Learner — v1.0.0

Learns driving patterns without needing a calendar.
Observes when the EV is connected/disconnected and correlates with:
  - Time of day, day of week
  - SOC at connection time
  - How much was charged (= how far they drove)
  - How much time before next departure

From this, it predicts:
  - Expected departure time for today
  - Minimum SOC needed (based on historical trip length)
  - Optimal charging window (EPEX-aware)

Works alongside the existing EV Trip Planner.
The AI learner improves over time without any user configuration.
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

STORAGE_KEY     = "cloudems_ev_pattern_v1"
STORAGE_VERSION = 1

# Minimum observations before predictions are made
MIN_TRIPS = 5
# Max trips to keep in memory
MAX_TRIPS = 200


@dataclass
class TripRecord:
    """One observed EV trip."""
    connected_at_h:    float   # hour of day when connected (returned home)
    connected_dow:     int     # day of week (0=mon)
    soc_on_arrival:    float   # SOC% when plugged in
    soc_on_departure:  float   # SOC% when unplugged
    departed_at_h:     float   # hour of day when unplugged
    charged_kwh:       float   # energy delivered during session
    ts:                float   # unix timestamp


class EVPatternLearner:
    """
    Learns EV usage patterns and feeds predictions to the AI registry.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass   = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self._trips: list[TripRecord] = []
        self._session_start_ts:  Optional[float] = None
        self._session_start_soc: Optional[float] = None
        self._session_start_h:   Optional[float] = None
        self._was_connected      = False
        self._dirty = False

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        raw_trips = saved.get("trips", [])
        for t in raw_trips:
            try:
                self._trips.append(TripRecord(**t))
            except Exception:
                pass
        _LOGGER.info("EV Pattern Learner: loaded %d trips", len(self._trips))

    def tick(self, is_connected: bool, soc_pct: float, ts: Optional[float] = None) -> None:
        """Call every coordinator tick with current EV state."""
        ts = ts or time.time()
        now_h = datetime.fromtimestamp(ts, tz=timezone.utc).hour + \
                datetime.fromtimestamp(ts, tz=timezone.utc).minute / 60.0
        dow = datetime.fromtimestamp(ts, tz=timezone.utc).weekday()

        if is_connected and not self._was_connected:
            # Just connected — start session
            self._session_start_ts  = ts
            self._session_start_soc = soc_pct
            self._session_start_h   = now_h
            _LOGGER.debug("EV Pattern: session started, SOC=%.0f%%", soc_pct)

        elif not is_connected and self._was_connected:
            # Just disconnected — record completed session
            if (self._session_start_ts and self._session_start_soc is not None
                    and self._session_start_h is not None):
                duration_h = (ts - self._session_start_ts) / 3600.0
                if duration_h > 0.25:  # at least 15 min — filter out brief disconnects
                    charged_kwh = max(0.0, (soc_pct - self._session_start_soc) / 100.0 * 75.0)
                    # Assume 75 kWh battery — will be overridden by config later
                    trip = TripRecord(
                        connected_at_h   = self._session_start_h,
                        connected_dow    = dow,
                        soc_on_arrival   = self._session_start_soc,
                        soc_on_departure = soc_pct,
                        departed_at_h    = now_h,
                        charged_kwh      = charged_kwh,
                        ts               = ts,
                    )
                    self._trips.append(trip)
                    if len(self._trips) > MAX_TRIPS:
                        self._trips = self._trips[-MAX_TRIPS:]
                    self._dirty = True
                    _LOGGER.debug(
                        "EV Pattern: trip recorded, charged=%.1f kWh, depart=%.1f:00",
                        charged_kwh, now_h
                    )
            self._session_start_ts = None

        self._was_connected = is_connected

    def predict_departure(self, dow: int, current_hour: float) -> dict:
        """
        Predict likely departure time and required SOC for today.
        Returns {'departure_hour': float, 'min_soc': float, 'confidence': float}
        """
        if len(self._trips) < MIN_TRIPS:
            return {"departure_hour": None, "min_soc": 80.0, "confidence": 0.0}

        # Filter trips for same day-of-week (or adjacent days)
        same_day = [t for t in self._trips if t.connected_dow == dow]
        if len(same_day) < 2:
            same_day = self._trips  # fall back to all trips

        # Find trips where departure was AFTER current_hour
        future_trips = [t for t in same_day if t.departed_at_h > current_hour + 0.5]
        if not future_trips:
            return {"departure_hour": None, "min_soc": 80.0, "confidence": 0.0}

        # Weighted average departure hour (recent trips weighted higher)
        now_ts = time.time()
        weights = [math.exp(-(now_ts - t.ts) / (30 * 86400)) for t in future_trips]  # 30-day decay
        total_w = sum(weights)
        avg_departure = sum(t.departed_at_h * w for t, w in zip(future_trips, weights)) / total_w

        # Min SOC: 90th percentile of departure SOC (be conservative)
        sorted_soc = sorted(t.soc_on_departure for t in future_trips)
        p90_soc    = sorted_soc[int(len(sorted_soc) * 0.9)]

        confidence = min(0.85, len(future_trips) / 10.0)

        return {
            "departure_hour": round(avg_departure, 1),
            "min_soc":        round(p90_soc, 0),
            "confidence":     round(confidence, 3),
            "based_on_trips": len(future_trips),
        }

    async def async_maybe_save(self) -> None:
        if self._dirty:
            await self._save()

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "trips": [
                    {"connected_at_h": t.connected_at_h, "connected_dow": t.connected_dow,
                     "soc_on_arrival": t.soc_on_arrival, "soc_on_departure": t.soc_on_departure,
                     "departed_at_h": t.departed_at_h, "charged_kwh": t.charged_kwh, "ts": t.ts}
                    for t in self._trips
                ]
            })
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("EV Pattern save error: %s", exc)

    @property
    def stats(self) -> dict:
        return {
            "n_trips":   len(self._trips),
            "ready":     len(self._trips) >= MIN_TRIPS,
            "connected": self._was_connected,
        }
