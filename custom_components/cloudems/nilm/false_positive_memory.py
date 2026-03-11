# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS NILM FalsePositiveMemory — v1.0.0

Leert afgewezen power-signatures en blokkeert ze bij toekomstige detecties.

Wanneer de gebruiker een apparaat als "incorrect" markeert, slaat deze module
de power-signature op als bekende fout-positief. Bij elk volgend on-event wordt
de delta vergeleken met de opgeslagen signatures — bij een match wordt het event
onderdrukt vóórdat het de classificatie-pipeline bereikt.

Kernmechanisme:
  - Elke afgewezen signature = (power_w, phase, time_of_day_bucket, day_of_week_bucket)
  - Match = power binnen FP_TOLERANCE%, optioneel versterkt door tijdcontext
  - Signatures vervallen na FP_MAX_AGE_DAYS als ze geen recente bevestiging krijgen
  - Maximal FP_MAX_SIGNATURES per fase om geheugengebruik te begrenzen
  - Persistent opgeslagen via HA Store

Integratie in detector.py:
  _async_process_event() → vóór classificatie: if fp_memory.is_false_positive(...): return

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY     = "cloudems_nilm_fp_memory_v1"
_STORAGE_VERSION = 1

# ── Configuratie ──────────────────────────────────────────────────────────────
FP_TOLERANCE        = 0.22   # ±22% vermogenstolerantie voor signature-match
FP_MAX_AGE_DAYS     = 90     # signatures ouder dan 90 dagen worden verwijderd
FP_MAX_SIGNATURES   = 120    # max signatures in geheugen (per alle fasen)
FP_MIN_REJECTIONS   = 1      # 1 afwijzing is genoeg om te leren
FP_TIME_BUCKET_H    = 3      # tijdvakken van 3 uur (0-2, 3-5, 6-8, ...)
FP_CONTEXT_BOOST    = 0.15   # extra zekerheid als tijdcontext ook overeenkomt


@dataclass
class FPSignature:
    """Een opgeslagen false-positive power-signature."""
    power_w:         float          # Geleerd nominaal vermogen (W)
    phase:           str            # L1 / L2 / L3
    time_bucket:     int            # uur // FP_TIME_BUCKET_H (0-7)
    day_bucket:      int            # weekdag (0=ma, 6=zo)
    rejection_count: int   = 1      # hoe vaak afgewezen
    first_seen:      float = field(default_factory=time.time)
    last_seen:       float = field(default_factory=time.time)

    def matches(self, power_w: float, phase: str,
                time_bucket: int, day_bucket: int) -> float:
        """
        Geeft een score [0.0, 1.0] als dit event overeenkomt met de signature.
        0.0 = geen match, >0.5 = betrouwbare match.
        """
        if phase != self.phase:
            return 0.0
        ratio = power_w / self.power_w if self.power_w > 0 else 0.0
        if not (1 - FP_TOLERANCE) <= ratio <= (1 + FP_TOLERANCE):
            return 0.0
        # Basis match op vermogen
        power_score = 1.0 - abs(ratio - 1.0) / FP_TOLERANCE
        # Context-boost als tijdvak ook overeenkomt
        context_match = (time_bucket == self.time_bucket)
        return min(1.0, power_score + (FP_CONTEXT_BOOST if context_match else 0.0))

    def to_dict(self) -> dict:
        return {
            "power_w":         self.power_w,
            "phase":           self.phase,
            "time_bucket":     self.time_bucket,
            "day_bucket":      self.day_bucket,
            "rejection_count": self.rejection_count,
            "first_seen":      self.first_seen,
            "last_seen":       self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FPSignature":
        return cls(
            power_w         = float(d.get("power_w", 0)),
            phase           = d.get("phase", "L1"),
            time_bucket     = int(d.get("time_bucket", 0)),
            day_bucket      = int(d.get("day_bucket", 0)),
            rejection_count = int(d.get("rejection_count", 1)),
            first_seen      = float(d.get("first_seen", time.time())),
            last_seen       = float(d.get("last_seen", time.time())),
        )


class FalsePositiveMemory:
    """
    Persistent geheugen voor afgewezen NILM power-signatures.

    Gebruik:
        fp = FalsePositiveMemory(hass)
        await fp.async_load()

        # Bij afwijzing door gebruiker:
        fp.record_rejection(power_w=1800.0, phase="L1")

        # Bij elk nieuw on-event vóór classificatie:
        if fp.is_false_positive(power_w=1820.0, phase="L1"):
            return  # onderdrukt
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass       = hass
        self._store      = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._signatures: list[FPSignature] = []
        self._dirty      = False

    # ── Publieke API ──────────────────────────────────────────────────────────

    def record_rejection(
        self,
        power_w: float,
        phase:   str = "L1",
        ts:      Optional[float] = None,
    ) -> None:
        """
        Sla een afgewezen power-signature op.
        Wordt aangeroepen vanuit NILMDetector.record_feedback() bij 'incorrect'.
        """
        if power_w < 20:
            return  # te kleine delta — niet zinvol opslaan

        now = ts or time.time()
        tb, db = self._time_buckets(now)

        # Check of een bestaande signature al overeenkomt
        for sig in self._signatures:
            score = sig.matches(power_w, phase, tb, db)
            if score >= 0.5:
                sig.rejection_count += 1
                sig.last_seen = now
                # Update gewogen gemiddelde vermogen (online EMA)
                sig.power_w = round(sig.power_w * 0.8 + power_w * 0.2, 1)
                self._dirty = True
                _LOGGER.debug(
                    "FP-geheugen: bestaande signature bijgewerkt "
                    "%.0fW fase=%s (n=%d)",
                    sig.power_w, phase, sig.rejection_count,
                )
                return

        # Nieuwe signature
        if len(self._signatures) >= FP_MAX_SIGNATURES:
            self._evict_oldest()

        self._signatures.append(FPSignature(
            power_w     = round(power_w, 1),
            phase       = phase,
            time_bucket = tb,
            day_bucket  = db,
            first_seen  = now,
            last_seen   = now,
        ))
        self._dirty = True
        _LOGGER.info(
            "FP-geheugen: nieuwe signature opgeslagen %.0fW fase=%s "
            "(tijdvak=%d, totaal=%d signatures)",
            power_w, phase, tb, len(self._signatures),
        )

    def is_false_positive(
        self,
        power_w: float,
        phase:   str = "L1",
        ts:      Optional[float] = None,
        threshold: float = 0.55,
    ) -> bool:
        """
        Geeft True als dit event overeenkomt met een bekende false-positive.
        threshold: minimale match-score (0.55 = veilige standaard).
        """
        if not self._signatures or power_w < 20:
            return False

        now = ts or time.time()
        tb, db = self._time_buckets(now)

        best_score = 0.0
        best_sig   = None
        for sig in self._signatures:
            score = sig.matches(power_w, phase, tb, db)
            if score > best_score:
                best_score = score
                best_sig   = sig

        if best_score >= threshold:
            _LOGGER.debug(
                "FP-geheugen: %.0fW fase=%s geblokkeerd "
                "(score=%.2f, sig=%.0fW n=%d)",
                power_w, phase, best_score,
                best_sig.power_w, best_sig.rejection_count,
            )
            return True
        return False

    def get_stats(self) -> dict:
        """Dashboard/diagnose statistieken."""
        return {
            "total_signatures": len(self._signatures),
            "by_phase": {
                p: sum(1 for s in self._signatures if s.phase == p)
                for p in ("L1", "L2", "L3")
            },
            "most_rejected": sorted(
                [s.to_dict() for s in self._signatures],
                key=lambda x: x["rejection_count"],
                reverse=True,
            )[:5],
        }

    # ── Opslag ────────────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Laad signatures vanuit HA storage."""
        try:
            data = await self._store.async_load()
            if data and isinstance(data.get("signatures"), list):
                now = time.time()
                max_age = FP_MAX_AGE_DAYS * 86400
                loaded = 0
                for d in data["signatures"]:
                    sig = FPSignature.from_dict(d)
                    if now - sig.last_seen < max_age:
                        self._signatures.append(sig)
                        loaded += 1
                _LOGGER.debug(
                    "FP-geheugen: %d signatures geladen (%d verlopen verwijderd)",
                    loaded, len(data["signatures"]) - loaded,
                )
        except Exception as exc:
            _LOGGER.warning("FP-geheugen: kon niet laden: %s", exc)

    async def async_save(self) -> None:
        """Sla signatures op naar HA storage (alleen als dirty)."""
        if not self._dirty:
            return
        try:
            self._prune_expired()
            await self._store.async_save({
                "signatures": [s.to_dict() for s in self._signatures],
            })
            self._dirty = False
            _LOGGER.debug(
                "FP-geheugen: %d signatures opgeslagen", len(self._signatures)
            )
        except Exception as exc:
            _LOGGER.warning("FP-geheugen: kon niet opslaan: %s", exc)

    # ── Intern ────────────────────────────────────────────────────────────────

    @staticmethod
    def _time_buckets(ts: float) -> tuple[int, int]:
        """Zet timestamp om naar (tijdvak, weekdag) buckets."""
        import datetime
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.hour // FP_TIME_BUCKET_H, dt.weekday()

    def _evict_oldest(self) -> None:
        """Verwijder de minst recente signature om ruimte te maken."""
        if not self._signatures:
            return
        oldest = min(self._signatures, key=lambda s: s.last_seen)
        self._signatures.remove(oldest)
        _LOGGER.debug("FP-geheugen: oudste signature verwijderd (%.0fW)", oldest.power_w)

    def _prune_expired(self) -> None:
        """Verwijder signatures ouder dan FP_MAX_AGE_DAYS."""
        cutoff = time.time() - FP_MAX_AGE_DAYS * 86400
        before = len(self._signatures)
        self._signatures = [s for s in self._signatures if s.last_seen >= cutoff]
        removed = before - len(self._signatures)
        if removed:
            _LOGGER.debug("FP-geheugen: %d verlopen signatures verwijderd", removed)
