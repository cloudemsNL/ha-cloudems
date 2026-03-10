# -*- coding: utf-8 -*-
"""
CloudEMS NILM Device Power Profile — v1.0.0

Per-device learned power profile, built up from real observations.
Used for:
  1. Off-edge matching: match negative delta to known active device power
  2. Auto-confirm: after N consistent sessions, confirm automatically
  3. Session fingerprint dedup: recognize repeat cycling (refrigerator etc.)
  4. Energy anomaly detection: flag unexpected kWh divergence

Algorithm:
  - Each completed session (on→off with known duration + avg power) is recorded
  - Running EWMA of observed power values → learned_power_w
  - Running standard deviation → power_std_w  (for soft matching window)
  - Duty cycle estimation → learned_duty_cycle
  - Auto-confirm when: N sessions seen, power std/mean < 0.15 (consistent),
    no user-reject in last K sessions

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
EWMA_ALPHA              = 0.20      # learning rate voor vermogensupdates
EWMA_ALPHA_SLOW         = 0.05      # trage update voor stabiele apparaten
AUTOCONFIRM_SESSIONS    = 8         # na 8 sessies auto-bevestigen
AUTOCONFIRM_CV_MAX      = 0.18      # max variatie-coefficient voor auto-confirm
AUTOCONFIRM_MIN_POWER_W = 20.0      # minvermogen om auto-confirm te activeren
CYCLE_DETECT_WINDOW_S   = 3600      # venster om cyclus-patronen te detecteren
CYCLE_CONFIRM_MIN       = 3         # min aantal cycli voor cycling-classificatie
ENERGY_ANOMALY_SIGMA    = 3.5       # z-score drempel voor energie-anomalie melding
MIN_SESSION_DURATION_S  = 5.0       # sessies korter dan 5s negeren
POWER_MATCH_TOLERANCE   = 0.35      # 35% tolerantie bij off-edge matching op profiel

# Apparaattypen die per definitie cycling zijn (compressor-gedreven)
CYCLING_TYPES = frozenset({
    "refrigerator", "heat_pump", "dehumidifier", "air_conditioner",
    "heat_pump_dryer", "pool_pump",
})


@dataclass
class SessionRecord:
    """Enkelvoudige sessie: AAN → UIT."""
    start_ts:       float
    end_ts:         float
    avg_power_w:    float
    peak_power_w:   float
    energy_kwh:     float
    phase:          str = "L1"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)

    def to_dict(self) -> dict:
        return {
            "start_ts":    round(self.start_ts, 1),
            "end_ts":      round(self.end_ts, 1),
            "duration_s":  round(self.duration_s, 1),
            "avg_power_w": round(self.avg_power_w, 1),
            "peak_power_w": round(self.peak_power_w, 1),
            "energy_kwh":  round(self.energy_kwh, 4),
            "phase":       self.phase,
        }


class DevicePowerProfile:
    """
    Geleerd vermogensprofiel voor één apparaat.

    Bijgehouden per apparaat (device_id) in NILMDetector._profiles.
    Persistentie: serialiseerbaar via to_dict() / from_dict().
    """

    def __init__(self, device_id: str, device_type: str) -> None:
        self.device_id   = device_id
        self.device_type = device_type

        # Geleerd vermogen (EWMA over sessies)
        self.learned_power_w: float  = 0.0
        self.power_std_w: float      = 0.0       # running std dev
        self._power_m2: float        = 0.0       # Welford M2 voor online std
        self._power_count: int       = 0

        # Sessie-statistieken
        self.session_count: int      = 0
        self.total_sessions: int     = 0         # incl. onbevestigde
        self._recent_sessions: list  = []        # laatste 20 sessies (SessionRecord)
        self._recent_reject_count: int = 0       # user-rejects in recente sessies

        # Duty cycle / cyclus-patroon
        self.is_cycling: bool        = False     # koelkast-type cyclus herkend
        self.learned_duty_cycle: float = 0.0     # geschatte aan-tijd fractie
        self._cycle_on_times: list   = []        # lijst van (start_ts,) voor cyclus-detectie

        # Auto-confirm status
        self.auto_confirmed: bool    = False
        self.auto_confirm_ts: float  = 0.0

        # Energie-anomalie tracking
        self._monthly_kwh: list      = []        # lijst van 12 maandwaarden
        self._current_month_key: str = ""
        self._current_month_kwh: float = 0.0
        self.anomaly_flag: bool      = False
        self.anomaly_reason: str     = ""

        # Diagnose
        self.created_at: float       = time.time()
        self.last_session_ts: float  = 0.0

    # ── Hoofd-API ─────────────────────────────────────────────────────────────

    def record_session(self, start_ts: float, end_ts: float,
                       avg_power_w: float, peak_power_w: float,
                       energy_kwh: float, phase: str = "L1",
                       user_rejected: bool = False) -> None:
        """Verwerk een voltooide sessie in het profiel."""
        duration_s = end_ts - start_ts
        if duration_s < MIN_SESSION_DURATION_S or avg_power_w < 1.0:
            return

        session = SessionRecord(
            start_ts     = start_ts,
            end_ts       = end_ts,
            avg_power_w  = avg_power_w,
            peak_power_w = peak_power_w,
            energy_kwh   = energy_kwh,
            phase        = phase,
        )

        self._recent_sessions.append(session)
        if len(self._recent_sessions) > 20:
            self._recent_sessions.pop(0)

        self.session_count     += 1
        self.total_sessions    += 1
        self.last_session_ts    = end_ts

        if user_rejected:
            self._recent_reject_count += 1
        else:
            # Welford online mean + variance voor vermogen
            self._power_count += 1
            delta = avg_power_w - self.learned_power_w
            if self._power_count == 1:
                self.learned_power_w = avg_power_w
            else:
                alpha = EWMA_ALPHA_SLOW if self.auto_confirmed else EWMA_ALPHA
                self.learned_power_w = (1 - alpha) * self.learned_power_w + alpha * avg_power_w
            delta2 = avg_power_w - self.learned_power_w
            self._power_m2 += delta * delta2
            if self._power_count >= 2:
                self.power_std_w = math.sqrt(self._power_m2 / (self._power_count - 1))

            # Duty cycle
            self._update_duty_cycle(start_ts, duration_s)

            # Energie anomalie
            self._update_energy_anomaly(energy_kwh, end_ts)

            # Auto-confirm check
            if not self.auto_confirmed:
                self._check_auto_confirm()

        _LOGGER.debug(
            "DeviceProfile %s: sessie %.0fs avg=%.0fW → learned=%.0fW±%.0fW (n=%d)",
            self.device_id, duration_s, avg_power_w,
            self.learned_power_w, self.power_std_w, self._power_count,
        )

    def matches_off_event(self, delta_w: float) -> float:
        """
        Geeft een match-score (0.0–1.0) terug voor een off-event delta.

        Off-events hebben negatieve delta. We vergelijken abs(delta) met
        learned_power_w ± (power_std_w + POWER_MATCH_TOLERANCE × learned_power_w).

        Returns:
            0.0  → geen match
            >0.0 → match score (hoger = betere match)
        """
        if self.learned_power_w < AUTOCONFIRM_MIN_POWER_W:
            return 0.0
        abs_delta = abs(delta_w)
        ref = self.learned_power_w
        # Tolerantievenster: max van std of 35% van ref vermogen
        tol = max(self.power_std_w * 2.0, ref * POWER_MATCH_TOLERANCE)
        if abs(abs_delta - ref) <= tol:
            # Score: 1.0 bij perfecte match, aflopend naar 0 bij rand venster
            dist_frac = abs(abs_delta - ref) / max(tol, 1.0)
            return round(max(0.0, 1.0 - dist_frac), 3)
        return 0.0

    def coefficient_of_variation(self) -> float:
        """CV = std / mean — maat voor consistentie van het vermogen."""
        if self.learned_power_w <= 0:
            return 1.0
        return round(self.power_std_w / self.learned_power_w, 3)

    # ── Interne helpers ───────────────────────────────────────────────────────

    def _update_duty_cycle(self, start_ts: float, duration_s: float) -> None:
        """Schat duty cycle op basis van recente sessie-timing."""
        self._cycle_on_times.append((start_ts, duration_s))
        # Houd alleen cycli in CYCLE_DETECT_WINDOW_S
        cutoff = start_ts - CYCLE_DETECT_WINDOW_S
        self._cycle_on_times = [(t, d) for t, d in self._cycle_on_times if t > cutoff]

        if len(self._cycle_on_times) >= CYCLE_CONFIRM_MIN:
            total_on  = sum(d for _, d in self._cycle_on_times)
            dc = min(1.0, total_on / CYCLE_DETECT_WINDOW_S)
            self.learned_duty_cycle = round(dc, 3)
            if self.device_type in CYCLING_TYPES or dc < 0.60:
                self.is_cycling = True

    def _update_energy_anomaly(self, energy_kwh: float, ts: float) -> None:
        """Bijhouden energie per maand en detecteren van anomalieën."""
        from datetime import datetime, timezone
        month_key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
        if self._current_month_key != month_key:
            if self._current_month_key:
                self._monthly_kwh.append(self._current_month_kwh)
                if len(self._monthly_kwh) > 12:
                    self._monthly_kwh = self._monthly_kwh[-12:]
            self._current_month_key = month_key
            self._current_month_kwh = 0.0
        self._current_month_kwh += energy_kwh

        # Anomalie-detectie: z-score over maandhistorie
        if len(self._monthly_kwh) >= 3:
            mean = sum(self._monthly_kwh) / len(self._monthly_kwh)
            std  = math.sqrt(sum((v - mean) ** 2 for v in self._monthly_kwh)
                             / len(self._monthly_kwh))
            if std > 0 and self._current_month_kwh > 0:
                z = (self._current_month_kwh - mean) / std
                if z > ENERGY_ANOMALY_SIGMA:
                    self.anomaly_flag   = True
                    self.anomaly_reason = (
                        f"Maandverbruik {self._current_month_kwh:.1f} kWh "
                        f"({z:.1f}σ boven gemiddeld {mean:.1f} kWh)"
                    )
                    _LOGGER.warning(
                        "NILM energie-anomalie %s: %s", self.device_id, self.anomaly_reason
                    )
                else:
                    self.anomaly_flag   = False
                    self.anomaly_reason = ""

    def _check_auto_confirm(self) -> None:
        """Auto-bevestig als het profiel consistent genoeg is."""
        if self._power_count < AUTOCONFIRM_SESSIONS:
            return
        if self.learned_power_w < AUTOCONFIRM_MIN_POWER_W:
            return
        if self.coefficient_of_variation() > AUTOCONFIRM_CV_MAX:
            return
        # Niet auto-confirmen als gebruiker recent heeft afgewezen
        if self._recent_reject_count > 0:
            return
        self.auto_confirmed  = True
        self.auto_confirm_ts = time.time()
        _LOGGER.info(
            "NILM auto-confirm: %s (%.0fW±%.0fW na %d sessies, CV=%.2f)",
            self.device_id,
            self.learned_power_w, self.power_std_w,
            self._power_count, self.coefficient_of_variation(),
        )

    # ── Serialisatie ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "device_id":           self.device_id,
            "device_type":         self.device_type,
            "learned_power_w":     round(self.learned_power_w, 2),
            "power_std_w":         round(self.power_std_w, 2),
            "_power_m2":           round(self._power_m2, 4),
            "_power_count":        self._power_count,
            "session_count":       self.session_count,
            "total_sessions":      self.total_sessions,
            "recent_sessions":     [s.to_dict() for s in self._recent_sessions[-5:]],
            "_recent_reject_count": self._recent_reject_count,
            "is_cycling":          self.is_cycling,
            "learned_duty_cycle":  self.learned_duty_cycle,
            "auto_confirmed":      self.auto_confirmed,
            "auto_confirm_ts":     self.auto_confirm_ts,
            "anomaly_flag":        self.anomaly_flag,
            "anomaly_reason":      self.anomaly_reason,
            "_monthly_kwh":        self._monthly_kwh,
            "_current_month_key":  self._current_month_key,
            "_current_month_kwh":  round(self._current_month_kwh, 4),
            "created_at":          self.created_at,
            "last_session_ts":     self.last_session_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DevicePowerProfile":
        p = cls(data["device_id"], data.get("device_type", "unknown"))
        p.learned_power_w       = data.get("learned_power_w", 0.0)
        p.power_std_w           = data.get("power_std_w", 0.0)
        p._power_m2             = data.get("_power_m2", 0.0)
        p._power_count          = data.get("_power_count", 0)
        p.session_count         = data.get("session_count", 0)
        p.total_sessions        = data.get("total_sessions", 0)
        p._recent_reject_count  = data.get("_recent_reject_count", 0)
        p.is_cycling            = data.get("is_cycling", False)
        p.learned_duty_cycle    = data.get("learned_duty_cycle", 0.0)
        p.auto_confirmed        = data.get("auto_confirmed", False)
        p.auto_confirm_ts       = data.get("auto_confirm_ts", 0.0)
        p.anomaly_flag          = data.get("anomaly_flag", False)
        p.anomaly_reason        = data.get("anomaly_reason", "")
        p._monthly_kwh          = data.get("_monthly_kwh", [])
        p._current_month_key    = data.get("_current_month_key", "")
        p._current_month_kwh    = data.get("_current_month_kwh", 0.0)
        p.created_at            = data.get("created_at", time.time())
        p.last_session_ts       = data.get("last_session_ts", 0.0)
        # Reconstructeer recente sessies
        for sd in data.get("recent_sessions", []):
            try:
                p._recent_sessions.append(SessionRecord(**{
                    k: sd[k] for k in (
                        "start_ts","end_ts","avg_power_w","peak_power_w","energy_kwh","phase"
                    ) if k in sd
                }))
            except Exception:
                pass
        return p
