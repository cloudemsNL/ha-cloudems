# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Lightning Detector (v1.0.0).

Detecteert mogelijke blikseminslagen via bestaande HA-sensoren.
Geen extra hardware nodig — gebruikt PV-omvormer data, P1-meter
en optionele omvormer-faultcodes.

DETECTIEMETHODEN (gestapeld, elk voegt betrouwbaarheid toe)
═══════════════════════════════════════════════════════════

Methode A — PV plotselinge totale drop (confidence: 40%)
  PV zakt van >500W naar <10W in één 10s-cyclus
  én Open-Meteo cloud_cover < 50% (geen wolkverklaring)
  én herstel binnen 3 cycli (30s) naar >70% van vorige waarde
  Werkt omdat: overspanningsbeveiliging klapt bij EM-puls, omvormer herstart

Methode B — Omvormer faultcode (confidence: 70%)
  Growatt: fault_code attribuut bevat "lightning" of code 119/121
  Goodwe: fault_code bevat "SPD" (Surge Protection Device)
  SMA: operating_status = "Fault" gecombineerd met snelle recovery
  Huawei: alarm_code bevat "SVG" of "Overvoltage"

Methode C — P1 spanningspiek (confidence: 30%)
  Netsanningsensor (als gekoppeld) toont piek >253V of dip <207V
  Gecombineerd met snel herstel (<3 cycli)

Methode D — Multi-omvormer correlatie (confidence: 80%)
  Meerdere omvormers op zelfde installatie tonen gelijktijdige drop
  Sluit uit: selectieve schaduw van één omvormer

Gecombineerde confidence:
  A+B: 85%     A+C: 60%     B+D: 92%     A+B+C+D: 97%

WAAROM BETER DAN BLITZORTUNG
═════════════════════════════
Blitzortung meet radiofequente emissie (VLF 3-30kHz) — detecteert
de bliksem ZELF maar niet de IMPACT op infrastructuur.

CloudEMS meet de impact: welke installaties zijn geraakt,
welk vermogenverlies, hoe lang uitval, exact tijdstip.

Dat is wat verzekeraars, netbeheerders en schadefondsen willen:
niet "er was bliksem bij gemeente X" maar "installatie Y op adres Z
heeft om 14:23:07 een vermogenspiek gehad van 0→8.2kW in 2s".

Met duizenden installaties: triangulatie van inslagelocatie
via aankomsttijden en correlatie tussen installaties.

CLOUD SCHEMA (upload naar AdaptiveHome)
════════════════════════════════════════
LightningEvent:
  timestamp_utc, lat_rounded, lon_rounded, installation_id
  detection_methods: ["pv_drop", "fault_code", "voltage_spike"]
  confidence: 0.0-1.0
  pv_before_w, pv_after_w, pv_recovery_s
  fault_code: str | None
  voltage_peak_v: float | None
  inverter_count: int  (hoeveel omvormers beïnvloed)
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Detectiedrempels
PV_DROP_THRESHOLD_PCT  = 0.97   # 97% daling van vorige waarde = totale drop
PV_MIN_BEFORE_W        = 500    # Minimale PV voor drop-detectie (dag-uur)
PV_RECOVERY_CYCLES     = 4      # Max cycli (40s) voor herstel-check
CLOUD_EXCLUDE_PCT      = 60     # cloud_cover < 60% = geen wolkverklaring
VOLTAGE_HIGH_V         = 253.0  # EU norm + 10%
VOLTAGE_LOW_V          = 207.0  # EU norm - 10%
COOLDOWN_S             = 120    # Min 2 min tussen events

# Omvormer fault codes die wijzen op overspanning/bliksem
LIGHTNING_FAULT_KEYWORDS = [
    "lightning", "spd", "surge", "overvoltage", "overspanning",
    "bliksem", "119", "121", "spd_fault", "arc",
]


@dataclass
class LightningEvent:
    """Gedetecteerde mogelijke blikseminslag. Cloud-ready schema."""
    timestamp_utc:      str
    lat_rounded:        float
    lon_rounded:        float
    installation_id:    str
    detection_methods:  list[str]
    confidence:         float          # 0.0-1.0
    pv_before_w:        float          # PV vermogen vlak voor event
    pv_after_w:         float          # PV vermogen vlak na event
    pv_recovery_s:      Optional[float] = None   # seconden tot herstel
    fault_code:         Optional[str]  = None
    voltage_peak_v:     Optional[float] = None
    inverter_count:     int            = 1
    cloud_cover_pct:    Optional[float] = None
    uploaded:           bool           = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _PvSample:
    """Intern: één PV-meting voor drop-detectie."""
    ts:       float
    pv_w:     float
    cloud_pct: Optional[float]


class LightningDetector:
    """Detecteert mogelijke blikseminslagen via bestaande sensoren.

    Gebruik in coordinator:
        detector = LightningDetector(lat, lon, entry_id)
        event = detector.observe(
            pv_w=1200, pv_per_inverter=[800,400],
            cloud_pct=20, fault_codes=["SPD_fault"],
            voltage_v=None,
        )
        if event:
            # log, notify, upload
    """

    def __init__(self, lat: float, lon: float, installation_id: str) -> None:
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        # Ringbuffer van laatste 8 metingen (80s)
        self._history: deque[_PvSample] = deque(maxlen=8)
        self._events:  deque[LightningEvent] = deque(maxlen=100)
        self._last_event_ts: float = 0.0

        # Herstel tracking
        self._drop_detected_at: Optional[float] = None
        self._pv_before_drop:   float = 0.0
        self._pending_methods:  list[str] = []
        self._pending_confidence: float = 0.0

        self._total_detected: int = 0

    def observe(
        self,
        pv_w:             float,
        pv_per_inverter:  list[float],
        cloud_pct:        float,
        fault_codes:      list[str],
        voltage_l1:       Optional[float] = None,
        voltage_l2:       Optional[float] = None,
        voltage_l3:       Optional[float] = None,
    ) -> Optional[LightningEvent]:
        """Verwerk nieuwe meting. Geeft LightningEvent terug bij detectie."""
        now = time.time()
        sample = _PvSample(ts=now, pv_w=pv_w, cloud_pct=cloud_pct)

        # Cooldown check
        if now - self._last_event_ts < COOLDOWN_S:
            self._history.append(sample)
            return None

        # Controleer herstel van eerder gedetecteerde drop
        if self._drop_detected_at is not None:
            event = self._check_recovery(sample, pv_per_inverter)
            if event:
                self._history.append(sample)
                return event

        methods: list[str] = []
        confidence = 0.0

        # ── Methode B: Omvormer faultcode ────────────────────────────────────
        fault_match = self._check_fault_codes(fault_codes)
        if fault_match:
            methods.append("fault_code")
            confidence = max(confidence, 0.70)
            _LOGGER.debug("LightningDetector: faultcode match: %s", fault_match)

        # ── Methode C: Spanningspiek — alle beschikbare fasen ────────────────
        # Bliksem treft alle fasen tegelijk → multi-fase = hogere confidence
        # Enkelfase buiten norm = lokaal probleem, niet per se bliksem
        _volts = {k: v for k, v in [
            ("L1", voltage_l1), ("L2", voltage_l2), ("L3", voltage_l3)
        ] if v is not None and 150 <= v <= 280}
        if _volts:
            _affected = [ph for ph, v in _volts.items()
                         if v > VOLTAGE_HIGH_V or v < VOLTAGE_LOW_V]
            if _affected:
                methods.append("voltage_spike")
                # Confidence schaalt met aantal getroffen fasen
                # 1 fase: 0.30  — kan lokaal faseverschijnsel zijn
                # 2 fasen: 0.45 — waarschijnlijk netprobleem of bliksem
                # 3 fasen: 0.65 — sterk bliksemindicator
                _phase_conf = {1: 0.30, 2: 0.45, 3: 0.65}
                _c = _phase_conf.get(len(_affected), 0.30)
                confidence = max(confidence, _c)
                _LOGGER.debug(
                    "LightningDetector: voltage_spike %s fasen=%s conf=%.0f%%",
                    _affected, {ph: _volts[ph] for ph in _affected}, _c * 100
                )

        # ── Methode A: PV plotselinge drop ────────────────────────────────────
        pv_drop = self._check_pv_drop(sample, cloud_pct, pv_per_inverter)
        if pv_drop:
            methods.append("pv_drop")
            confidence = max(confidence, 0.40)
            # Start herstel-tracking
            self._drop_detected_at  = now
            self._pv_before_drop    = pv_drop
            self._pending_methods   = methods.copy()
            self._pending_confidence = confidence

        # Gecombineerde confidence
        if len(methods) > 1:
            confidence = self._combine_confidence(methods, confidence)

        # Minimale drempel: alleen bij faultcode of combinatie
        if confidence < 0.40 or not methods:
            self._history.append(sample)
            return None

        # Direct event als confidence hoog genoeg zonder drop-tracking
        if "fault_code" in methods and "pv_drop" not in methods:
            event = LightningEvent(
                timestamp_utc   = datetime.now(timezone.utc).isoformat(),
                lat_rounded     = self._lat,
                lon_rounded     = self._lon,
                installation_id = self._install_id,
                detection_methods = methods,
                confidence      = round(confidence, 2),
                pv_before_w     = pv_w,
                pv_after_w      = pv_w,
                fault_code      = fault_match,
                voltage_peak_v  = max(_volts.values()) if _volts else None,
                inverter_count  = len(pv_per_inverter) or 1,
                cloud_cover_pct = cloud_pct,
            )
            return self._emit(event)

        self._history.append(sample)
        return None

    def _check_pv_drop(
        self,
        sample: _PvSample,
        cloud_pct: float,
        pv_per_inverter: list[float],
    ) -> Optional[float]:
        """Check voor plotselinge totale PV-drop. Geeft pv_before terug."""
        if len(self._history) < 2:
            return None

        prev = self._history[-1]
        if prev.pv_w < PV_MIN_BEFORE_W:
            return None  # Niet genoeg PV voor betrouwbare meting

        # Drop: huidige PV < 3% van vorige waarde
        drop_ratio = sample.pv_w / max(prev.pv_w, 1)
        if drop_ratio > (1 - PV_DROP_THRESHOLD_PCT):
            return None

        # Wolkencheck: als bewolkt, is dit gewoon een wolkdip
        if cloud_pct >= CLOUD_EXCLUDE_PCT:
            return None

        # Multi-omvormer: alle omvormers tegelijk? (niet selectieve schaduw)
        if len(pv_per_inverter) > 1:
            all_dropped = all(w < 50 for w in pv_per_inverter)
            if not all_dropped:
                return None  # Maar één omvormer → waarschijnlijk schaduw

        _LOGGER.info(
            "LightningDetector: PV-drop gedetecteerd %.0fW → %.0fW (cloud=%.0f%%)",
            prev.pv_w, sample.pv_w, cloud_pct,
        )
        return prev.pv_w

    def _check_recovery(
        self,
        sample: _PvSample,
        pv_per_inverter: list[float],
    ) -> Optional[LightningEvent]:
        """Check of PV hersteld na drop — bevestigt bliksem-hypothese."""
        elapsed = sample.ts - self._drop_detected_at
        if elapsed > PV_RECOVERY_CYCLES * 10 + 5:
            # Te lang: geen herstel → reset, was waarschijnlijk iets anders
            self._drop_detected_at = None
            return None

        # Herstel check: >70% van voor de drop
        if sample.pv_w < self._pv_before_drop * 0.70:
            return None  # Nog niet hersteld

        # Herstel bevestigd!
        self._drop_detected_at = None
        methods = self._pending_methods.copy()
        if "pv_drop" not in methods:
            methods.insert(0, "pv_drop")
        confidence = self._combine_confidence(methods, self._pending_confidence)
        # Herstel binnen korte tijd verhoogt confidence
        if elapsed < 30:
            confidence = min(1.0, confidence + 0.15)

        event = LightningEvent(
            timestamp_utc    = datetime.now(timezone.utc).isoformat(),
            lat_rounded      = self._lat,
            lon_rounded      = self._lon,
            installation_id  = self._install_id,
            detection_methods = methods,
            confidence       = round(confidence, 2),
            pv_before_w      = self._pv_before_drop,
            pv_after_w       = sample.pv_w,
            pv_recovery_s    = round(elapsed, 1),
            inverter_count   = len(pv_per_inverter) or 1,
            cloud_cover_pct  = sample.cloud_pct,
        )
        return self._emit(event)

    def _check_fault_codes(self, fault_codes: list[str]) -> Optional[str]:
        """Check of omvormer faultcodes wijzen op bliksem/overspanning."""
        for code in fault_codes:
            code_lower = str(code).lower()
            for kw in LIGHTNING_FAULT_KEYWORDS:
                if kw in code_lower:
                    return code
        return None

    def _combine_confidence(self, methods: list[str], base: float) -> float:
        """Combineer confidence van meerdere onafhankelijke methoden."""
        # Elke extra methode voegt toe: 1 - (1-p1)(1-p2)...
        # Approximatie: base + 0.15 per extra methode
        extra = max(0, len(methods) - 1) * 0.15
        return min(1.0, base + extra)

    def _emit(self, event: LightningEvent) -> LightningEvent:
        self._events.append(event)
        self._last_event_ts = time.time()
        self._total_detected += 1
        _LOGGER.info(
            "LightningDetector: event gedetecteerd — methods=%s confidence=%.0f%%",
            event.detection_methods, event.confidence * 100,
        )
        return event

    def get_recent_events(self, n: int = 10) -> list[dict]:
        return [e.to_dict() for e in list(self._events)[-n:]]

    def get_upload_batch(self) -> list[dict]:
        batch = [e for e in self._events if not e.uploaded][:50]
        for e in batch:
            e.uploaded = True
        return [e.to_dict() for e in batch]

    def to_dict(self) -> dict:
        return {
            "installation_id": self._install_id,
            "total_detected":  self._total_detected,
            "recent_events":   self.get_recent_events(5),
            "upload_pending":  sum(1 for e in self._events if not e.uploaded),
        }
