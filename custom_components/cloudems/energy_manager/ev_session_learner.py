# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS EV Session Learner — v1.0.0

Learns EV charging behaviour from observed sessions — zero config needed.

What it tracks per session:
  - Plug-in time (weekday + hour)
  - Unplug time
  - Total kWh delivered
  - Session duration

What it learns (after ~10 sessions):
  - Typical plug-in hour per weekday
  - Typical kWh need per session
  - Typical session duration
  - Whether the pattern is "commuter" (Mon-Fri evening) or "weekend" or mixed

What it exposes:
  - Predicted kWh for the next session (so the scheduler can plan optimally)
  - Recommended charge window start (cheapest block that fits predicted kWh)
  - Session history summary
  - Current session state (active / idle)

Zero config: plug-in detection works by watching the EV charger current entity
cross 0 → >0 (session start) and >0 → 0 (session end). The coordinator feeds
this via `update(current_a, price_eur_kwh)`.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_ev_sessions_v1"
STORAGE_VERSION = 1

MIN_SESSION_KWH     = 0.5      # ignore micro-sessions (cable test etc.)
MIN_SESSION_S       = 300      # minimum 5 minutes to count as real session
MAX_SESSIONS_STORED = 60       # keep last 60 sessions
MIN_SESSIONS_MODEL  = 5        # need this many before predictions are made
EMA_ALPHA           = 0.25     # learning rate for rolling averages


@dataclass
class EVSession:
    start_ts:   float
    end_ts:     float   = 0.0
    kwh:        float   = 0.0
    weekday:    int     = 0
    start_hour: int     = 0
    duration_h: float   = 0.0
    cost_eur:   float   = 0.0

    def to_dict(self) -> dict:
        return {
            "start_ts":   self.start_ts,
            "end_ts":     self.end_ts,
            "kwh":        round(self.kwh, 3),
            "weekday":    self.weekday,
            "start_hour": self.start_hour,
            "duration_h": round(self.duration_h, 2),
            "cost_eur":   round(self.cost_eur, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EVSession":
        return cls(
            start_ts   = d.get("start_ts", 0.0),
            end_ts     = d.get("end_ts", 0.0),
            kwh        = d.get("kwh", 0.0),
            weekday    = d.get("weekday", 0),
            start_hour = d.get("start_hour", 0),
            duration_h = d.get("duration_h", 0.0),
            cost_eur   = d.get("cost_eur", 0.0),
        )


class EVSessionLearner:
    """
    Zero-config EV session tracker and predictor.

    Call update(current_a, price_eur_kwh) every 10s from coordinator.
    """

    def __init__(self, hass: HomeAssistant, grid_voltage: float = 230.0) -> None:
        self.hass          = hass
        self._store        = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._voltage      = grid_voltage
        self._sessions:    list[EVSession] = []
        self._active:      Optional[EVSession] = None
        self._last_current: float = 0.0

        # Learned model
        self._avg_kwh:        float = 15.0  # prior
        self._avg_duration_h: float = 4.0
        self._avg_start_hour: float = 18.0
        self._typical_weekdays: list[int] = []   # weekdays most sessions occur

        self._dirty = False
        self._last_save: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        self._sessions = [EVSession.from_dict(d) for d in saved.get("sessions", [])]
        self._avg_kwh        = float(saved.get("avg_kwh",        15.0))
        self._avg_duration_h = float(saved.get("avg_duration_h", 4.0))
        self._avg_start_hour = float(saved.get("avg_start_hour", 18.0))
        self._typical_weekdays = saved.get("typical_weekdays", [])
        _LOGGER.info(
            "CloudEMS EVSessionLearner: %d sessies geladen, gem. %.1f kWh",
            len(self._sessions), self._avg_kwh,
        )
        self._recompute_model()

    async def _async_save(self) -> None:
        await self._store.async_save({
            "sessions":        [s.to_dict() for s in self._sessions[-MAX_SESSIONS_STORED:]],
            "avg_kwh":         round(self._avg_kwh, 3),
            "avg_duration_h":  round(self._avg_duration_h, 3),
            "avg_start_hour":  round(self._avg_start_hour, 2),
            "typical_weekdays": self._typical_weekdays,
        })
        self._dirty = False
        self._last_save = time.time()

    # ── Main update ───────────────────────────────────────────────────────────

    def update(self, current_a: float, price_eur_kwh: float) -> dict:
        """
        Feed current EV charger output (A) and current price.
        Returns session state + learned model output.
        """
        now  = datetime.now(timezone.utc)
        interval_h = 10.0 / 3600.0   # 10s in hours

        # Session start
        if current_a > 0.5 and self._last_current <= 0.5:
            self._active = EVSession(
                start_ts   = time.time(),
                weekday    = now.weekday(),
                start_hour = now.hour,
            )
            _LOGGER.info("CloudEMS EV: sessie gestart om %02d:%02d", now.hour, now.minute)

        # Accumulate active session
        if self._active is not None and current_a > 0.5:
            power_w = current_a * self._voltage
            self._active.kwh      += power_w / 1000.0 * interval_h
            self._active.cost_eur += (power_w / 1000.0 * interval_h) * price_eur_kwh

        # Session end
        if current_a <= 0.5 and self._last_current > 0.5 and self._active is not None:
            sess = self._active
            sess.end_ts     = time.time()
            sess.duration_h = (sess.end_ts - sess.start_ts) / 3600.0
            if sess.kwh >= MIN_SESSION_KWH and sess.duration_h * 3600 >= MIN_SESSION_S:
                self._sessions.append(sess)
                self._recompute_model()
                self._dirty = True
                _LOGGER.info(
                    "CloudEMS EV: sessie afgerond — %.2f kWh, %.1fh, €%.2f",
                    sess.kwh, sess.duration_h, sess.cost_eur,
                )
            self._active = None

        self._last_current = current_a

        # Save periodically
        if self._dirty and (time.time() - self._last_save) >= 300:
            self.hass.async_create_task(self._async_save())

        return self._build_state(current_a)

    # ── Model ─────────────────────────────────────────────────────────────────

    def _recompute_model(self) -> None:
        sess = [s for s in self._sessions if s.kwh >= MIN_SESSION_KWH]
        if len(sess) < MIN_SESSIONS_MODEL:
            return
        kwhs        = [s.kwh for s in sess]
        durations   = [s.duration_h for s in sess]
        start_hours = [s.start_hour for s in sess]
        self._avg_kwh        = sum(kwhs) / len(kwhs)
        self._avg_duration_h = sum(durations) / len(durations)
        self._avg_start_hour = sum(start_hours) / len(start_hours)
        # Weekdays with ≥20% of sessions
        from collections import Counter
        wd_counts = Counter(s.weekday for s in sess)
        total = len(sess)
        self._typical_weekdays = sorted(wd for wd, cnt in wd_counts.items() if cnt / total >= 0.15)

    def _build_state(self, current_a: float) -> dict:
        sess = [s for s in self._sessions if s.kwh >= MIN_SESSION_KWH]
        model_ready = len(sess) >= MIN_SESSIONS_MODEL
        DAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        typical_days_labels = [DAYS[wd] for wd in self._typical_weekdays if wd < 7]

        active_kwh = round(self._active.kwh, 3) if self._active else None
        active_cost = round(self._active.cost_eur, 3) if self._active else None

        return {
            "session_active":      self._active is not None,
            "session_current_a":   round(current_a, 1),
            "session_kwh_so_far":  active_kwh,
            "session_cost_so_far": active_cost,
            "sessions_total":      len(sess),
            "model_ready":         model_ready,
            # Learned predictions
            "predicted_kwh":        round(self._avg_kwh, 1) if model_ready else None,
            "predicted_duration_h": round(self._avg_duration_h, 1) if model_ready else None,
            "typical_start_hour":   round(self._avg_start_hour, 0) if model_ready else None,
            "typical_weekdays":     typical_days_labels,
            # Last 3 sessions summary
            "recent_sessions": [
                {
                    "kwh":        round(s.kwh, 2),
                    "duration_h": round(s.duration_h, 1),
                    "cost_eur":   round(s.cost_eur, 2),
                    "weekday":    DAYS[s.weekday] if s.weekday < 7 else "?",
                    "start_hour": s.start_hour,
                }
                for s in sess[-3:]
            ],
            "avg_cost_per_session": round(
                sum(s.cost_eur for s in sess[-10:]) / min(len(sess), 10), 2
            ) if sess else None,
            "avg_kwh_per_session": round(self._avg_kwh, 2) if model_ready else None,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EVDeparturePredictor — v1.0.0 (toegevoegd in v2.6)
# Leert vertrekkijden per weekdag en activeert deadline-modus als de auto
# niet op tijd volladen kan via alleen goedkope uren.
# ══════════════════════════════════════════════════════════════════════════════

DEADLINE_MIN_MARGIN_H = 0.5   # minimaal 30 min voor vertrek klaar
DEADLINE_SOC_TARGET   = 0.80  # streef naar 80% SoC bij vertrek


class EVDeparturePredictor:
    """
    Leert de typische vertrekkijden per weekdag op basis van historische
    sessies (einde van de laadsessie ≈ vertrek).

    Geeft de DynamicEVCharger een 'deadline' zodat deze bij onvoldoende
    goedkope uren automatisch alsnog oplaadt — ook op duurder stroom —
    om de gewenste SoC te halen.

    Gebruik:
        pred = EVDeparturePredictor()
        pred.learn_from_sessions(sessions)   # lijst van EVSession
        deadline = pred.get_deadline(weekday, current_hour)
        must_charge = pred.must_charge_now(
            deadline_h, current_hour, remaining_kwh, charger_kw, cheap_hours_left
        )
    """

    def __init__(self) -> None:
        # avg_departure_hour[weekday] = gemiddeld vertrekuur (float)
        self.avg_departure_hour: dict[int, float] = {}
        self._raw: dict[int, list[float]] = {i: [] for i in range(7)}

    def learn_from_sessions(self, sessions: list) -> None:
        """Herbereken vertrekmodellen uit historische sessies."""
        from collections import defaultdict
        raw: dict[int, list[float]] = defaultdict(list)
        for s in sessions:
            if s.end_ts <= 0 or s.kwh < 0.5:
                continue
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(s.end_ts, tz=timezone.utc)
            raw[dt.weekday()].append(dt.hour + dt.minute / 60.0)
        for wd, hours in raw.items():
            if len(hours) >= 3:
                self.avg_departure_hour[wd] = sum(hours) / len(hours)

    def get_deadline(self, weekday: int) -> float | None:
        """Geeft het verwachte vertrekuur vandaag, of None als onbekend."""
        return self.avg_departure_hour.get(weekday)

    def must_charge_now(
        self,
        deadline_h: float,
        current_h: float,
        remaining_kwh: float,
        charger_kw: float,
        cheap_hours_left: float,
    ) -> tuple[bool, str]:
        """
        Bepaal of de auto NU geladen moet worden ook al is de prijs hoog.

        Geeft (True, reden) als deadline-laden nodig is.

        remaining_kwh   — nog te laden kWh voor SoC-doel
        charger_kw      — beschikbaar laadvermogen (kW)
        cheap_hours_left — goedkope uren die nog over zijn vóór deadline
        """
        if deadline_h is None or charger_kw <= 0:
            return False, ""

        hours_to_deadline = deadline_h - current_h - DEADLINE_MIN_MARGIN_H
        if hours_to_deadline <= 0:
            return False, "Deadline al voorbij"

        kwh_in_cheap = cheap_hours_left * charger_kw
        if kwh_in_cheap >= remaining_kwh:
            return False, "Voldoende goedkope uren beschikbaar"

        shortfall = remaining_kwh - kwh_in_cheap
        reason = (
            f"Deadline-laden actief: nog {remaining_kwh:.1f} kWh nodig, "
            f"slechts {kwh_in_cheap:.1f} kWh in goedkope uren — "
            f"laad nu {shortfall:.1f} kWh extra om {deadline_h:.0f}:00 te halen."
        )
        return True, reason

    def to_dict(self) -> dict:
        from datetime import datetime, timezone
        DAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        departure_schedule = {
            DAYS[wd]: f"{int(h):02d}:{int((h % 1) * 60):02d}"
            for wd, h in self.avg_departure_hour.items()
        }
        return {
            "departure_schedule": departure_schedule,
            "weekdays_learned":   len(self.avg_departure_hour),
        }
