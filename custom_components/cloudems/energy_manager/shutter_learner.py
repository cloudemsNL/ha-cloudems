"""
CloudEMS Shutter Schedule Learner — v4.6.154

Features:
- Per-weekday learning with cross-day seeding (weekday/weekend groups)
- Seasonal deadband: summer 45min, shoulder 30min, winter 15min
- Holiday detection: Dutch public holidays treated as Sunday
- Persistence via coordinator storage
- Reset per shutter/action/day via service call

Defaults: open 08:00, close 20:00 until confidence reached.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from datetime import time, date
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_SAMPLES        = 5
MAX_SAMPLES        = 30
CONFIDENCE_HIGH    = 0.80
STDDEV_MAX_MIN     = 45

EVENT_CLOSE = "close"
EVENT_OPEN  = "open"

CROSS_DAY_WEIGHT = 0.5
WEEKDAYS  = (0, 1, 2, 3, 4)
WEEKEND   = (5, 6)

# Seasonal deadband (minutes)
DEADBAND_SUMMER_CLOSE  = 45   # April–September: earlier close (bright evenings)
DEADBAND_SUMMER_OPEN   = 45   # Later open
DEADBAND_WINTER_CLOSE  = 15   # October–March: shorter deadband
DEADBAND_WINTER_OPEN   = 15
DEADBAND_DEFAULT_CLOSE = 30   # Fallback
DEADBAND_DEFAULT_OPEN  = 30

# Dutch public holidays (MM-DD, year-independent)
NL_HOLIDAYS = {
    "01-01",  # Nieuwjaarsdag
    "04-27",  # Koningsdag
    "05-05",  # Bevrijdingsdag
    "12-25",  # 1e Kerstdag
    "12-26",  # 2e Kerstdag
    "12-31",  # Oudejaarsavond (optional)
}
# Easter-based holidays are computed dynamically


def _is_nl_holiday(d: date) -> bool:
    """Returns True if date is a Dutch public holiday."""
    mmdd = d.strftime("%m-%d")
    if mmdd in NL_HOLIDAYS:
        return True
    # Easter-based: Good Friday (-2), Easter Sunday (0), Easter Monday (+1),
    # Ascension (+39), Whit Sunday (+49), Whit Monday (+50)
    try:
        from datetime import timedelta
        # Compute Easter (Meeus/Jones/Butcher algorithm)
        y = d.year
        a = y % 19
        b, c = divmod(y, 100)
        dd, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - dd - g + 15) % 30
        i, k = divmod(c, 4)
        ll = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * ll) // 451
        month = (h + ll - 7 * m + 114) // 31
        day   = ((h + ll - 7 * m + 114) % 31) + 1
        easter = date(y, month, day)
        offsets = (-2, 0, 1, 39, 49, 50)
        for off in offsets:
            if d == easter + timedelta(days=off):
                return True
    except Exception:
        pass
    return False


def _seasonal_deadband(action: str, month: int) -> int:
    """Returns deadband in minutes based on current season."""
    summer = month in (4, 5, 6, 7, 8, 9)
    if summer:
        return DEADBAND_SUMMER_CLOSE if action == EVENT_CLOSE else DEADBAND_SUMMER_OPEN
    else:
        return DEADBAND_WINTER_CLOSE if action == EVENT_CLOSE else DEADBAND_WINTER_OPEN


def _effective_weekday(dt) -> int:
    """Returns weekday, treating public holidays as Sunday (6)."""
    d = dt.date() if hasattr(dt, 'date') else dt
    if _is_nl_holiday(d):
        return 6  # treat as Sunday
    return d.weekday()


@dataclass
class TimeObservation:
    weekday: int
    minutes: int
    source:  str
    weight:  float
    ts:      float


@dataclass
class LearnedSchedule:
    weekday: int
    action:  str
    observations: list[TimeObservation] = field(default_factory=list)

    @property
    def effective_samples(self) -> float:
        return sum(o.weight for o in self.observations)

    @property
    def mean_minutes(self) -> Optional[float]:
        obs = self.observations[-MAX_SAMPLES:]
        if not obs or self.effective_samples < MIN_SAMPLES:
            return None
        total_w = sum(o.weight for o in obs)
        return sum(o.minutes * o.weight for o in obs) / total_w

    @property
    def stddev_minutes(self) -> float:
        obs = self.observations[-MAX_SAMPLES:]
        if len(obs) < 2:
            return 999.0
        mean = self.mean_minutes
        if mean is None:
            return 999.0
        total_w = sum(o.weight for o in obs)
        return math.sqrt(sum(o.weight * (o.minutes - mean) ** 2 for o in obs) / total_w)

    @property
    def confidence(self) -> float:
        if self.effective_samples < MIN_SAMPLES:
            return 0.0
        stddev = self.stddev_minutes
        if stddev > STDDEV_MAX_MIN:
            return 0.0
        consistency   = max(0.0, 1.0 - stddev / STDDEV_MAX_MIN)
        sample_factor = min(1.0, self.effective_samples / MAX_SAMPLES)
        return round(consistency * 0.7 + sample_factor * 0.3, 2)

    def applied_time(self, month: int) -> Optional[time]:
        if self.confidence < CONFIDENCE_HIGH:
            return None
        mean = self.mean_minutes
        if mean is None:
            return None
        deadband = _seasonal_deadband(self.action, month)
        if self.action == EVENT_CLOSE:
            applied = max(0, int(mean) - deadband)
        else:
            applied = min(23 * 60 + 59, int(mean) + deadband)
        h, m = divmod(applied, 60)
        return time(h, m)

    def add_observation(self, minutes: int, source: str, weight: float = 1.0) -> None:
        import time as _t
        self.observations.append(TimeObservation(
            weekday=self.weekday, minutes=minutes,
            source=source, weight=weight, ts=_t.time(),
        ))
        if len(self.observations) > MAX_SAMPLES:
            self.observations = self.observations[-MAX_SAMPLES:]

    def to_dict(self) -> dict:
        return {
            "weekday": self.weekday, "action": self.action,
            "observations": [
                {"weekday": o.weekday, "minutes": o.minutes,
                 "source": o.source, "weight": o.weight, "ts": o.ts}
                for o in self.observations
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LearnedSchedule":
        obj = cls(weekday=d["weekday"], action=d["action"])
        for o in d.get("observations", []):
            obj.observations.append(TimeObservation(
                weekday=o["weekday"], minutes=o["minutes"],
                source=o.get("source", "unknown"),
                weight=o.get("weight", 1.0),
                ts=o.get("ts", 0.0),
            ))
        return obj


class ShutterScheduleLearner:
    def __init__(self) -> None:
        self._schedules: dict[tuple, LearnedSchedule] = {}
        self._dirty: bool = False

    def observe(self, entity_id: str, action: str, dt, source: str = "manual") -> None:
        weekday = _effective_weekday(dt)
        minutes = dt.hour * 60 + dt.minute
        self._add(entity_id, action, weekday, minutes, source, weight=1.0)
        group = WEEKDAYS if weekday in WEEKDAYS else WEEKEND
        for sibling in group:
            if sibling != weekday:
                self._add(entity_id, action, sibling, minutes, source, weight=CROSS_DAY_WEIGHT)
        self._dirty = True
        _LOGGER.debug(
            "ShutterLearner: %s %s wd=%d %02d:%02d src=%s conf=%.0f%%",
            entity_id, action, weekday, dt.hour, dt.minute, source,
            self.get_confidence(entity_id, action, weekday) * 100,
        )

    def _add(self, entity_id: str, action: str, weekday: int,
             minutes: int, source: str, weight: float) -> None:
        key = (entity_id, action, weekday)
        if key not in self._schedules:
            self._schedules[key] = LearnedSchedule(weekday=weekday, action=action)
        self._schedules[key].add_observation(minutes, source, weight)

    def get_learned_time(self, entity_id: str, action: str, weekday: int,
                         month: int = 6) -> Optional[time]:
        key = (entity_id, action, weekday)
        s = self._schedules.get(key)
        return s.applied_time(month) if s else None

    def get_confidence(self, entity_id: str, action: str, weekday: int) -> float:
        key = (entity_id, action, weekday)
        s = self._schedules.get(key)
        return s.confidence if s else 0.0

    def reset(self, entity_id: str, action: Optional[str] = None,
              weekday: Optional[int] = None) -> int:
        """Reset learned data. Returns number of schedules cleared."""
        keys_to_delete = [
            k for k in list(self._schedules.keys())
            if k[0] == entity_id
            and (action is None or k[1] == action)
            and (weekday is None or k[2] == weekday)
        ]
        for k in keys_to_delete:
            del self._schedules[k]
        if keys_to_delete:
            self._dirty = True
        return len(keys_to_delete)

    def needs_more_data(self, entity_id: str) -> int:
        """Returns how many more direct observations are needed (0 = enough)."""
        total = sum(
            1 for (eid, _, _), s in self._schedules.items()
            if eid == entity_id and s.effective_samples >= 1.0
        )
        needed = max(0, MIN_SAMPLES - total)
        return needed

    def get_status(self, entity_id: str) -> dict:
        from datetime import datetime
        month = datetime.now().month
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        result = {}
        for action in (EVENT_OPEN, EVENT_CLOSE):
            result[action] = {}
            for wd in range(7):
                key = (entity_id, action, wd)
                s = self._schedules.get(key)
                if s is None:
                    result[action][days[wd]] = {
                        "samples": 0, "effective_samples": 0.0,
                        "confidence": 0.0, "learned": None, "applied": None,
                        "stddev_min": 0.0,
                    }
                    continue
                mean = s.mean_minutes
                applied = s.applied_time(month)
                result[action][days[wd]] = {
                    "samples":           len(s.observations),
                    "effective_samples": round(s.effective_samples, 1),
                    "confidence":        s.confidence,
                    "learned":           f"{int(mean)//60:02d}:{int(mean)%60:02d}" if mean is not None else None,
                    "applied":           applied.strftime("%H:%M") if applied else None,
                    "stddev_min":        round(s.stddev_minutes, 1),
                }
        return result

    @property
    def dirty(self) -> bool:
        return self._dirty

    def to_dict(self) -> dict:
        self._dirty = False
        return {
            f"{eid}|{action}|{wd}": sched.to_dict()
            for (eid, action, wd), sched in self._schedules.items()
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ShutterScheduleLearner":
        obj = cls()
        for key_str, sched_dict in d.items():
            try:
                eid, action, wd_str = key_str.split("|")
                wd = int(wd_str)
                obj._schedules[(eid, action, wd)] = LearnedSchedule.from_dict(sched_dict)
            except Exception as e:
                _LOGGER.warning("ShutterLearner: could not load %s: %s", key_str, e)
        return obj
