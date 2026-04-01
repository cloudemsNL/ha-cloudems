# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Grid Voltage Monitor (v1.0.0).

Bewaakt de netspanning via bestaande P1-meter data en detecteert anomalieën.
Geen extra hardware — P1 DSMR 5.x leest al voltage_l1/l2/l3 elke 10s.

DETECTIE
════════
  Dip  (<207V, EU norm -10%): spanning te laag → apparaatveiligheid
  Piek (>253V, EU norm +10%): spanning te hoog → omvormer uitval risico
  Asymmetrie (>15V verschil tussen fasen): netprobleem of zware 1-fase last
  Flicker (>5 dips in 60s): haspelmotor, las, slecht contact

WAARDE VOOR NETBEHEERDERS
══════════════════════════
Liander/Enexis/Stedin weten pas van spanningsproblemen als ze een klacht
krijgen of hun meetpunt (1 per wijk) het ziet. Met 1000+ P1-meters:
  - Real-time spanningskaart per straat
  - Anomalie 5-30 min eerder gedetecteerd
  - Locatie van probleem via GPS-correlatie
  - Historisch patroon voor structurele problemen

CLOUD SCHEMA
════════════
VoltageEvent:
  installation_id, lat_rounded, lon_rounded, timestamp_utc
  event_type: "dip" | "peak" | "asymmetry" | "flicker"
  voltage_l1, voltage_l2, voltage_l3
  duration_s: float | None
  max_deviation_v: float
  affected_phases: list[str]
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# EU norm: 230V ±10%
VOLT_NOMINAL   = 230.0
VOLT_LOW       = 207.0   # 230 × 0.90
VOLT_HIGH      = 253.0   # 230 × 1.10
VOLT_ASYMMETRY = 15.0    # max verschil tussen fasen
FLICKER_COUNT  = 5       # dips per minuut = flicker
COOLDOWN_S     = 60      # max 1 event per minuut per type


@dataclass
class VoltageEvent:
    """Netspanningsanomalie — cloud-ready schema."""
    timestamp_utc:   str
    installation_id: str
    lat_rounded:     float
    lon_rounded:     float
    event_type:      str          # dip | peak | asymmetry | flicker
    voltage_l1:      Optional[float]
    voltage_l2:      Optional[float]
    voltage_l3:      Optional[float]
    max_deviation_v: float        # max afwijking van 230V
    affected_phases: list[str]    # ["L1", "L2", "L3"]
    duration_s:      Optional[float] = None
    uploaded:        bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class GridVoltageMonitor:
    """Bewaakt netspanning en detecteert anomalieën.

    Gebruik in coordinator:
        monitor = GridVoltageMonitor(lat, lon, entry_id)
        events = monitor.observe(v_l1=228.0, v_l2=231.0, v_l3=229.0)
    """

    def __init__(self, lat: float, lon: float, installation_id: str) -> None:
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        self._events:     list[VoltageEvent] = []
        self._last_ts:    dict[str, float] = {}   # {event_type: last_ts}
        self._dip_times:  deque[float] = deque(maxlen=20)
        self._anomaly_start: dict[str, Optional[float]] = {"dip": None, "peak": None}

        # Statistieken
        self._total_dips:      int = 0
        self._total_peaks:     int = 0
        self._total_asymmetry: int = 0
        self._volt_history:    deque[tuple] = deque(maxlen=360)  # 1 uur bij 10s

    def observe(
        self,
        v_l1: Optional[float],
        v_l2: Optional[float] = None,
        v_l3: Optional[float] = None,
    ) -> list[VoltageEvent]:
        """Verwerk spanning per fase. Geeft lijst van nieuwe events."""
        now = time.time()
        if v_l1 is None:
            return []

        # Filter onrealistische waarden
        for v in [v_l1, v_l2, v_l3]:
            if v is not None and not (150 <= v <= 280):
                return []

        self._volt_history.append((now, v_l1, v_l2, v_l3))
        events: list[VoltageEvent] = []

        volts = {k: v for k, v in [("L1", v_l1), ("L2", v_l2), ("L3", v_l3)] if v is not None}
        if not volts:
            return []

        # ── Dip detectie ──────────────────────────────────────────────────────
        low_phases = [ph for ph, v in volts.items() if v < VOLT_LOW]
        if low_phases:
            self._dip_times.append(now)
            if self._anomaly_start["dip"] is None:
                self._anomaly_start["dip"] = now
            if self._cooldown_ok("dip", now):
                dev = max(VOLT_LOW - volts[ph] for ph in low_phases)
                ev = self._emit("dip", volts, low_phases, dev, now)
                events.append(ev)
                self._total_dips += 1
        else:
            if self._anomaly_start["dip"] is not None:
                self._anomaly_start["dip"] = None

        # ── Piek detectie ─────────────────────────────────────────────────────
        high_phases = [ph for ph, v in volts.items() if v > VOLT_HIGH]
        if high_phases:
            if self._anomaly_start["peak"] is None:
                self._anomaly_start["peak"] = now
            if self._cooldown_ok("peak", now):
                dev = max(volts[ph] - VOLT_HIGH for ph in high_phases)
                ev = self._emit("peak", volts, high_phases, dev, now)
                events.append(ev)
                self._total_peaks += 1
        else:
            self._anomaly_start["peak"] = None

        # ── Asymmetrie (alleen bij 3-fase) ────────────────────────────────────
        if v_l2 is not None and v_l3 is not None:
            spread = max(volts.values()) - min(volts.values())
            if spread > VOLT_ASYMMETRY and self._cooldown_ok("asymmetry", now):
                ev = self._emit("asymmetry", volts,
                                list(volts.keys()), spread, now)
                events.append(ev)
                self._total_asymmetry += 1

        # ── Flicker (>5 dips per 60s) ─────────────────────────────────────────
        recent_dips = sum(1 for t in self._dip_times if now - t <= 60)
        if recent_dips >= FLICKER_COUNT and self._cooldown_ok("flicker", now):
            dev = max(VOLT_LOW - v for v in volts.values() if v < VOLT_LOW) if low_phases else 0
            ev = self._emit("flicker", volts, list(volts.keys()), dev, now)
            events.append(ev)

        return events

    def _cooldown_ok(self, event_type: str, now: float) -> bool:
        last = self._last_ts.get(event_type, 0)
        if now - last < COOLDOWN_S:
            return False
        self._last_ts[event_type] = now
        return True

    def _emit(
        self,
        event_type: str,
        volts: dict,
        phases: list[str],
        deviation: float,
        now: float,
    ) -> VoltageEvent:
        duration = None
        start = self._anomaly_start.get(event_type)
        if start is not None:
            duration = round(now - start, 1)

        ev = VoltageEvent(
            timestamp_utc   = datetime.now(timezone.utc).isoformat(),
            installation_id = self._install_id,
            lat_rounded     = self._lat,
            lon_rounded     = self._lon,
            event_type      = event_type,
            voltage_l1      = volts.get("L1"),
            voltage_l2      = volts.get("L2"),
            voltage_l3      = volts.get("L3"),
            max_deviation_v = round(deviation, 1),
            affected_phases = phases,
            duration_s      = duration,
        )
        self._events.append(ev)
        _LOGGER.info("GridVoltageMonitor: %s gedetecteerd — fasen=%s dev=%.1fV",
                     event_type, phases, deviation)
        return ev

    def get_current_stats(self) -> dict:
        """Huidige spanningsstatistieken voor sensor."""
        if not self._volt_history:
            return {}
        recent = list(self._volt_history)[-6:]  # laatste 60s
        def avg(idx):
            vals = [r[idx] for r in recent if r[idx] is not None]
            return round(sum(vals)/len(vals), 1) if vals else None
        return {
            "voltage_l1_avg": avg(1),
            "voltage_l2_avg": avg(2),
            "voltage_l3_avg": avg(3),
            "total_dips":      self._total_dips,
            "total_peaks":     self._total_peaks,
            "total_asymmetry": self._total_asymmetry,
        }

    def get_upload_batch(self) -> list[dict]:
        batch = [e for e in self._events if not e.uploaded][:100]
        for e in batch: e.uploaded = True
        return [e.to_dict() for e in batch]

    def to_dict(self) -> dict:
        return {
            "installation_id": self._install_id,
            "upload_pending":  sum(1 for e in self._events if not e.uploaded),
            **self.get_current_stats(),
        }
