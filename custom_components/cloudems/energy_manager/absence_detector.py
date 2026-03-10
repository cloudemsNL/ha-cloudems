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
from homeassistant.helpers.storage import Store
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

    _STORE_KEY     = "cloudems_absence_detector_v1"
    _STORE_VERSION = 1
    _SAVE_INTERVAL = 300   # seconden tussen saves

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
        # Persistence
        self._store      = Store(hass, self._STORE_VERSION, self._STORE_KEY) if hass else None
        self._dirty      = False
        self._last_save  = 0.0
        # SleepDetector koppeling — confidence-gewogen blend
        self._sleep_active     = False
        self._sleep_confidence = 0.0

    async def async_setup(self) -> None:
        """Laad opgeslagen weekpatroon en standby-baseline."""
        if not self._store:
            return
        try:
            data = await self._store.async_load() or {}
            self._weekly    = data.get("weekly",   [None] * WEEK_SLOTS)
            self._weekly_n  = data.get("weekly_n", [0]    * WEEK_SLOTS)
            self._standby_ema = data.get("standby_ema")
            self._samples     = int(data.get("samples", 0))
            if len(self._weekly)   != WEEK_SLOTS:
                self._weekly   = [None] * WEEK_SLOTS
            if len(self._weekly_n) != WEEK_SLOTS:
                self._weekly_n = [0]    * WEEK_SLOTS
            import logging as _l
            _l.getLogger(__name__).debug(
                "AbsenceDetector: %d weekslots geladen, standby=%.0fW, %d samples",
                sum(1 for v in self._weekly if v is not None),
                self._standby_ema or 0, self._samples,
            )
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("AbsenceDetector: laden mislukt: %s", exc)

    async def _async_save(self) -> None:
        """Sla weekpatroon op (dirty-flag + rate-limit)."""
        if not self._store or not self._dirty:
            return
        now = time.time()
        if now - self._last_save < self._SAVE_INTERVAL:
            return
        try:
            await self._store.async_save({
                "weekly":      self._weekly,
                "weekly_n":    self._weekly_n,
                "standby_ema": self._standby_ema,
                "samples":     self._samples,
            })
            self._dirty     = False
            self._last_save = now
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("AbsenceDetector: opslaan mislukt: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def set_sleep_mode(self, is_sleeping: bool, confidence: float = 0.8) -> None:
        """Koppel SleepDetector-signaal aan de aanwezigheidsdetectie.

        Als iemand slaapt is dat geen 'afwezigheid' maar de EMA-drempel
        moet anders zijn. We bewaren het signaal en blenden het in update().
        """
        self._sleep_active     = is_sleeping
        self._sleep_confidence = max(0.0, min(1.0, confidence))

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
        self._dirty = True

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

        # SleepDetector blend: als slaap actief is, verlaag away_score (het is geen afwezigheid)
        if self._sleep_active and self._sleep_confidence > 0:
            # Blend richting 0.35 (slaap = thuis, maar laag verbruik is normaal)
            sleep_target = 0.35
            blend_w = self._sleep_confidence * 0.5   # maximaal 50% invloed
            away_score = (1 - blend_w) * away_score + blend_w * sleep_target

        confidence = min(1.0, abs(away_score - 0.5) * 2 + 0.2)

        if is_night and recent_avg < standby * 3:
            state = "sleeping"
        elif self._sleep_active and self._sleep_confidence >= 0.6:
            # SleepDetector bevestigt slaap — overschrijf staat direct
            state = "sleeping"
            self._away_since = None
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
