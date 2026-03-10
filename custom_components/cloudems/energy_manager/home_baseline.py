# -*- coding: utf-8 -*-
"""
CloudEMS Home Baseline Learner — v1.0.0

Learns three related things from the grid power signal alone:

1. BASELINE MODEL  (HourlyPattern per weekday×hour, 7×24 = 168 buckets)
   Tracks mean + σ of consumption for every slot.
   After ~14 days the model becomes reliable.

2. ANOMALY DETECTION
   If the current consumption deviates more than N×σ from the learned
   average for this slot → anomaly sensor fires.
   "It's Tuesday 3 AM and you're using 900W more than normal."

3. STANDBY + OCCUPANCY
   Nightly minimum (midnight-4h) converges to the true standby load.
   If consumption is significantly above standby → someone is probably home.
   The standby baseline itself surfaces "always-on" appliance load.

4. STANDBY HUNTERS
   Devices that appear always-on across several nights are flagged as
   potential energy wasters (e.g. old set-top-box, forgotten electric heater).

All learning is zero-config: nothing for the user to set.

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

STORAGE_KEY     = "cloudems_home_baseline_v1"
STORAGE_VERSION = 1

# Anomaly: flag if current > mean + sigma_threshold × σ
# De drempel past zich automatisch aan op het huishouden (zie AdaptiveSigma).
# Hoog-variabele huishoudens (gezin, wisselende diensten) krijgen een hogere
# drempel zodat echte afwijkingen niet verdrinken in dagelijkse ruis.
# Laag-variabele huishoudens (alleenwonend, vaste routines) krijgen een lagere
# drempel voor meer gevoeligheid.
SIGMA_THRESHOLD_DEFAULT = 2.5   # startwaarde; wordt adaptief bijgesteld
SIGMA_THRESHOLD_MIN     = 1.8   # nooit lager (te veel valse alarmen)
SIGMA_THRESHOLD_MAX     = 4.0   # nooit hoger (te weinig detectie)
# Minimum samples before anomaly detection activates for a slot
MIN_SAMPLES_FOR_ANOMALY = 7
# Standby learning: hours considered "deep night" (no intentional activity)
NIGHT_HOURS = {0, 1, 2, 3, 4}
# Standby: occupancy is probable if consumption > standby × OCCUPANCY_RATIO
OCCUPANCY_RATIO = 2.2
# Standby hunter: flag if night-average > STANDBY_HUNTER_W watts
STANDBY_HUNTER_W = 50.0
# Adaptive EMA alpha for standby model
STANDBY_ALPHA_FAST = 0.20   # eerste 5 nachten
STANDBY_ALPHA_MID  = 0.10   # nachten 5-15
STANDBY_ALPHA_SLOW = 0.05   # daarna (stabiel)
# Save interval
SAVE_INTERVAL_S = 300


@dataclass
class SlotStats:
    """Running mean + variance for one weekday×hour slot (Welford's algorithm)."""
    count: int   = 0
    mean:  float = 0.0
    m2:    float = 0.0     # sum of squared deviations from mean

    def update(self, value: float) -> None:
        self.count += 1
        delta  = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def std(self) -> float:
        if self.count < 2:
            return max(50.0, self.mean * 0.2)   # prior: 20% or 50W min
        return math.sqrt(self.m2 / (self.count - 1))

    def to_dict(self) -> dict:
        return {"count": self.count, "mean": round(self.mean, 1), "m2": round(self.m2, 1)}

    @classmethod
    def from_dict(cls, d: dict) -> "SlotStats":
        s = cls()
        s.count = d.get("count", 0)
        s.mean  = d.get("mean", 0.0)
        s.m2    = d.get("m2", 0.0)
        return s


class AdaptiveSigmaThreshold:
    """Berekent een per-huishouden adaptieve anomalie-drempel.

    Hoe het werkt:
    - Na MIN_TRAINED_SLOTS getrainde slots berekent de methode de gemiddelde
      coëfficiënt van variatie (CV = σ/μ) over alle goed-getrainde slots.
    - Hoog-CV huishoudens (veel variatie → grote σ/μ) krijgen een hogere
      drempel om valse alarmen te vermijden.
    - Laag-CV huishoudens (strakke routine) krijgen een lagere drempel.
    - De drempel wordt maximaal één keer per dag herberekend.
    """
    MIN_TRAINED_SLOTS = 48   # minstens 2 weekdagen volledig getraind

    def __init__(self) -> None:
        self._threshold: float = SIGMA_THRESHOLD_DEFAULT
        self._last_update_ts: float = 0.0
        self._cv_mean: float = 0.0

    def compute(self, slots: dict) -> float:
        """Herbereken de drempel op basis van alle getrainde slots."""
        import time as _t
        now = _t.time()
        if now - self._last_update_ts < 86400:     # max 1× per dag
            return self._threshold

        trained = [
            s for s in slots.values()
            if s.count >= MIN_SAMPLES_FOR_ANOMALY and s.mean > 20.0
        ]
        if len(trained) < self.MIN_TRAINED_SLOTS:
            return self._threshold

        cvs = [s.std / s.mean for s in trained if s.mean > 0]
        if not cvs:
            return self._threshold

        cv_mean = sum(cvs) / len(cvs)
        self._cv_mean = round(cv_mean, 3)

        # Lineaire mapping: CV 0.2 (strak) → drempel 1.8 | CV 0.8 (variabel) → drempel 4.0
        cv_lo, cv_hi = 0.20, 0.80
        thr_lo, thr_hi = SIGMA_THRESHOLD_MIN, SIGMA_THRESHOLD_MAX
        t = max(0.0, min(1.0, (cv_mean - cv_lo) / (cv_hi - cv_lo)))
        new_thr = round(thr_lo + t * (thr_hi - thr_lo), 2)

        if abs(new_thr - self._threshold) >= 0.05:
            import logging as _log
            _log.getLogger(__name__).info(
                "HomeBaseline: adaptieve σ-drempel bijgesteld van %.2f → %.2f "
                "(gem. CV over %d slots = %.3f)",
                self._threshold, new_thr, len(trained), cv_mean,
            )
        self._threshold = new_thr
        self._last_update_ts = now
        return self._threshold

    @property
    def value(self) -> float:
        return self._threshold

    @property
    def cv_mean(self) -> float:
        return self._cv_mean


class HomeBaselineLearner:
    """
    Learns household baseline consumption and detects anomalies.

    Usage in coordinator:
        bl = HomeBaselineLearner(hass)
        await bl.async_setup()
        # Every 10s:
        result = bl.update(power_w)
        # result keys: anomaly, deviation_w, expected_w, sigma,
        #              standby_w, is_home, standby_hunters
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass  = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # 7 weekdays × 24 hours
        self._slots: dict[tuple, SlotStats] = {
            (wd, h): SlotStats() for wd in range(7) for h in range(24)
        }
        self._standby_w: float = 80.0          # initial prior: 80W
        self._standby_samples: int = 0
        self._night_buffer: list[float] = []   # power readings this night hour
        self._current_night_hour: Optional[int] = None
        self._last_save: float = 0.0
        self._dirty: bool = False

        # Adaptieve sigma-drempel
        self._adaptive_sigma = AdaptiveSigmaThreshold()

        # Anomaly state
        self._anomaly: bool = False
        self._deviation_w: float = 0.0
        self._expected_w: float = 0.0
        self._sigma: float = 0.0

        # Slot accumulator (for hourly update, not every 10s)
        self._slot_buffer: list[float] = []
        self._slot_key: Optional[tuple] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for key_str, d in saved.get("slots", {}).items():
            wd, h = map(int, key_str.split("_"))
            self._slots[(wd, h)] = SlotStats.from_dict(d)
        self._standby_w       = float(saved.get("standby_w", 80.0))
        self._standby_samples = int(saved.get("standby_samples", 0))
        trained = sum(1 for s in self._slots.values() if s.count >= MIN_SAMPLES_FOR_ANOMALY)
        _LOGGER.info(
            "CloudEMS HomeBaseline: geladen — %d/%d slots getraind, standby %.0fW",
            trained, len(self._slots), self._standby_w,
        )

    def get_standby_w(self) -> float:
        """Geef geleerde standby-basislast terug (W)."""
        return self._standby_w

    def adjust_standby(self, confirmed_device_w: float) -> None:
        """
        v1.32: Verwerk bevestigde NILM standby-apparaten in de baseline.
        Verhoogt de standby-drempel zodat afwezigheidsdetectie klopt wanneer
        bekende always-on apparaten (koelkast, router) in de baseline zitten.
        """
        if confirmed_device_w > 0 and confirmed_device_w < 500:
            new_standby = min(
                self._standby_w + confirmed_device_w * 0.5,
                500.0,
            )
            if abs(new_standby - self._standby_w) > 5:
                import logging as _l
                _l.getLogger(__name__).debug(
                    "HomeBaseline: standby bijgesteld %.0fW → %.0fW "
                    "(NILM bevestigde apparaten +%.0fW)",
                    self._standby_w, new_standby, confirmed_device_w,
                )
                self._standby_w = new_standby
                self._dirty = True

    async def _async_save(self) -> None:
        await self._store.async_save({
            "slots": {
                f"{wd}_{h}": s.to_dict()
                for (wd, h), s in self._slots.items()
            },
            "standby_w":       round(self._standby_w, 1),
            "standby_samples": self._standby_samples,
        })
        self._dirty = False
        self._last_save = time.time()

    # ── Main update (call every ~10s from coordinator) ────────────────────────

    def update(self, power_w: float) -> dict:
        now  = datetime.now(timezone.utc)
        wd   = now.weekday()   # 0=Monday … 6=Sunday
        h    = now.hour
        slot = (wd, h)
        slot_key_changed = slot != self._slot_key

        # ── Slot accumulator: collect readings, learn at end of each hour ──
        if slot_key_changed:
            if self._slot_key is not None and self._slot_buffer:
                avg = sum(self._slot_buffer) / len(self._slot_buffer)
                s_prev = self._slots[self._slot_key].count
                self._slots[self._slot_key].update(avg)
                self._dirty = True
                trained_now = sum(1 for s in self._slots.values() if s.count >= MIN_SAMPLES_FOR_ANOMALY)
                total_slots = len(self._slots)
                if self._slots[self._slot_key].count == MIN_SAMPLES_FOR_ANOMALY and s_prev < MIN_SAMPLES_FOR_ANOMALY:
                    _LOGGER.info(
                        "HomeBaseline: slot %s bereikt drempel — %d/%d slots klaar voor anomaliedetectie",
                        self._slot_key, trained_now, total_slots,
                    )
            self._slot_buffer = []
            self._slot_key = slot
        self._slot_buffer.append(max(0.0, power_w))

        # ── Anomaly detection ──────────────────────────────────────────────
        s = self._slots[slot]
        self._expected_w = s.mean
        self._sigma      = s.std
        # Herbereken adaptieve drempel (max 1× per dag, goedkoop)
        sigma_thr = self._adaptive_sigma.compute(self._slots)
        if s.count >= MIN_SAMPLES_FOR_ANOMALY and s.mean > 5.0:
            dev = power_w - s.mean
            self._deviation_w = round(dev, 1)
            self._anomaly = dev > sigma_thr * s.std
        else:
            self._anomaly     = False
            self._deviation_w = 0.0

        # ── Standby learning: use deep-night readings ──────────────────────
        if h in NIGHT_HOURS and power_w > 0:
            if h != self._current_night_hour:
                if self._night_buffer:
                    night_avg = sum(self._night_buffer) / len(self._night_buffer)
                    # Only use if plausible standby range (< 500W, > 5W)
                    if 5.0 < night_avg < 500.0:
                        n = self._standby_samples
                        sa = STANDBY_ALPHA_FAST if n < 5 else (STANDBY_ALPHA_MID if n < 15 else STANDBY_ALPHA_SLOW)
                        self._standby_w = (
                            (1 - sa) * self._standby_w
                            + sa * night_avg
                        )
                        self._standby_samples += 1
                        self._dirty = True
                        _LOGGER.info(
                            "HomeBaseline: standby nacht #%d — %.0f W gemeten, EMA → %.0f W",
                            self._standby_samples, night_avg, self._standby_w,
                        )
                self._night_buffer = [power_w]
                self._current_night_hour = h
            else:
                self._night_buffer.append(power_w)

        # ── Occupancy: consumption significantly above standby? ────────────
        is_home = power_w > self._standby_w * OCCUPANCY_RATIO

        # ── Standby hunters: slots that are always above hunter threshold ──
        # Report night slots whose mean is > STANDBY_HUNTER_W
        hunters = [
            {"weekday": wd2, "hour": h2, "avg_w": round(s2.mean, 0)}
            for (wd2, h2), s2 in self._slots.items()
            if h2 in NIGHT_HOURS
            and s2.count >= MIN_SAMPLES_FOR_ANOMALY
            and s2.mean > STANDBY_HUNTER_W + self._standby_w
        ]

        # ── Periodic save ──────────────────────────────────────────────────
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            self.hass.async_create_task(self._async_save())

        trained_slots = sum(1 for s in self._slots.values() if s.count >= MIN_SAMPLES_FOR_ANOMALY)

        return {
            "anomaly":          self._anomaly,
            "deviation_w":      self._deviation_w,
            "expected_w":       round(self._expected_w, 1),
            "current_w":        round(power_w, 1),
            "sigma_w":          round(self._sigma, 1),
            "sigma_threshold":  self._adaptive_sigma.value,
            "sigma_cv_mean":    self._adaptive_sigma.cv_mean,
            "standby_w":        round(self._standby_w, 1),
            "standby_samples":  self._standby_samples,
            "is_home":          is_home,
            "trained_slots":    trained_slots,
            "total_slots":      168,
            "model_ready":      trained_slots >= 96,   # at least 4 weekday-days fully trained
            "standby_hunters":  hunters,
        }
