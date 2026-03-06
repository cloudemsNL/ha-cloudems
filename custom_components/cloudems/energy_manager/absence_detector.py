# -*- coding: utf-8 -*-
"""CloudEMS AbsenceDetector — v1.15.0.

Detects home occupancy state purely from energy consumption patterns.
No PIR sensors, no calendar, no login events — just the meter.

States
------
* home    — normal consumption pattern detected
* away    — power consistently near standby level
* sleeping — night-time pattern (low, smooth)
* vacation — away for > VACATION_H consecutive hours

Algorithm
---------
The detector maintains two rolling signals:
  1. Standby deviation: how far is current consumption from learned night-time baseline.
  2. Weekly pattern deviation: how far is current from the same hour last week.

Both signals are normalised 0–1 and blended with a configured weight.
"""
from __future__ import annotations
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

VACATION_H    = 8       # hours of continuous away → vacation
WINDOW_MIN    = 30      # minutes of data needed before trusting state
STANDBY_ALPHA_FAST = 0.15   # eerste 10 nacht-metingen
STANDBY_ALPHA_MID  = 0.03   # metingen 10-40
STANDBY_ALPHA_SLOW = 0.005  # daarna (seizoensrobuust)
WEEK_SLOTS    = 24 * 7  # hourly slots per week
AWAY_RATIO    = 0.25    # consumption at or below 25% of normal → away
NIGHT_HOURS   = (22, 7) # inclusive range for sleeping check


@dataclass
class OccupancyState:
    state: str          # "home" | "away" | "sleeping" | "vacation"
    confidence: float   # 0.0–1.0
    away_since: Optional[float]   # epoch seconds
    vacation_hours: int           # continuous away hours
    standby_w: float              # learned standby consumption
    advice: str


class AbsenceDetector:
    """Presence/absence detection from energy consumption patterns."""

    def __init__(self, hass=None):
        self._hass = hass
        # Hourly slot learning (7 days × 24 h)
        self._weekly: list[float | None] = [None] * WEEK_SLOTS
        self._weekly_n: list[int] = [0] * WEEK_SLOTS
        # Night-time standby baseline
        self._standby_ema: Optional[float] = None
        # Rolling recent samples (10-second ticks)
        self._recent: deque = deque(maxlen=WINDOW_MIN * 6)
        # Away tracking
        self._away_since: Optional[float] = None
        self._samples = 0

    # ── Public API ────────────────────────────────────────────────────────

    def update(self, grid_w: float) -> OccupancyState:
        """Feed one power reading and return current occupancy state."""
        now = time.time()
        import datetime as _dt
        hour  = _dt.datetime.now().hour
        dow   = _dt.datetime.now().weekday()   # 0=Mon … 6=Sun
        slot  = dow * 24 + hour

        # Learn standby during quiet night hours (22–07)
        is_night = (hour >= NIGHT_HOURS[0] or hour < NIGHT_HOURS[1])
        if is_night and grid_w > 0:
            if self._standby_ema is None:
                self._standby_ema = grid_w
                self._standby_n = 1
            else:
                sn = getattr(self, '_standby_n', 0)
                sa = STANDBY_ALPHA_FAST if sn < 10 else (STANDBY_ALPHA_MID if sn < 40 else STANDBY_ALPHA_SLOW)
                self._standby_ema = sa * grid_w + (1.0 - sa) * self._standby_ema
                self._standby_n = sn + 1
                if self._standby_n <= 20 or self._standby_n % 10 == 0:
                    import logging as _log
                    _log.getLogger(__name__).info(
                        "AbsenceDetector: standby nacht #%d — %.0f W gemeten, EMA → %.0f W",
                        self._standby_n, grid_w, self._standby_ema,
                    )

        # Update weekly slot (slow EMA per slot)
        if self._weekly[slot] is None:
            self._weekly[slot] = grid_w
        else:
            wn = self._weekly_n[slot]
            wa = 0.20 if wn < 5 else (0.07 if wn < 20 else 0.02)
            self._weekly[slot] = wa * grid_w + (1.0 - wa) * self._weekly[slot]
        self._weekly_n[slot] += 1

        self._recent.append(grid_w)
        self._samples += 1

        # Need minimum samples
        if self._samples < WINDOW_MIN * 2:
            return OccupancyState(
                state="home", confidence=0.3, away_since=None,
                vacation_hours=0, standby_w=self._standby_ema or 0.0,
                advice="Aan het leren…",
            )

        standby = self._standby_ema or 50.0
        recent_avg = sum(self._recent) / len(self._recent)
        weekly_ref = self._weekly[slot]

        # Score 0=home, 1=away
        # Signal 1: vs standby
        ratio_standby = min(1.0, recent_avg / max(standby * 2, 10))
        sig1 = 1.0 - ratio_standby   # close to standby → away

        # Signal 2: vs weekly pattern
        if weekly_ref and weekly_ref > 10:
            ratio_weekly = min(2.0, recent_avg / weekly_ref)
            sig2 = 1.0 - min(1.0, ratio_weekly)
        else:
            sig2 = sig1

        away_score = 0.6 * sig1 + 0.4 * sig2
        confidence = min(1.0, abs(away_score - 0.5) * 2 + 0.2)

        if is_night and recent_avg < standby * 3:
            state = "sleeping"
        elif away_score > 0.65:
            if self._away_since is None:
                self._away_since = now
            away_h = (now - self._away_since) / 3600
            state = "vacation" if away_h >= VACATION_H else "away"
        else:
            self._away_since = None
            state = "home"

        away_since = self._away_since
        vac_hours = int((now - away_since) / 3600) if away_since else 0

        advice = {
            "home":     "Normaal verbruikspatroon gedetecteerd.",
            "sleeping": "Nachtmodus — laag verbruik.",
            "away":     f"Afwezigheid gedetecteerd ({recent_avg:.0f} W gemiddeld).",
            "vacation": f"Vakantiestand: {vac_hours} uur afwezig.",
        }.get(state, "")

        return OccupancyState(
            state=state,
            confidence=round(confidence, 2),
            away_since=away_since,
            vacation_hours=vac_hours,
            standby_w=round(standby, 1),
            advice=advice,
        )
