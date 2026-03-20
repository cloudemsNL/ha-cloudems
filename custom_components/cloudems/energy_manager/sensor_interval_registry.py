# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS SensorIntervalRegistry — v4.6.522.

Centraal register dat voor élke vermogenssensor het werkelijke update-interval
meet, persistent opslaat en beschikbaar stelt aan andere modules.

Waarom dit nuttig is
────────────────────
Elke sensor heeft een andere updatesnelheid:
  - P1/DSMR5         →  ~1 s   (bijna realtime)
  - P1/DSMR4         →  ~10 s
  - Lokale smart plug →  2-5 s
  - Shelly EM        →  1-5 s
  - Growatt/Solarman →  30-300 s (cloud API)
  - Zonneplan Nexus  →  30-120 s (cloud API)
  - HomeWizard P1    →  ~1 s

Modules die hier profijt van hebben:
  - NILM: edge-detectie confidence aanpassen aan sensor snelheid.
    Trage sensor (30s) → rise_time_reliable=False, grotere deadband.
    Snelle sensor (1s) → rise_time_reliable=True, nauwkeurige detectie.
  - EnergyBalancer: stale-drempel per sensor instellenin plaats van vaste 90s.
  - PhaseLimiter: reageer sneller op fase-overschrijding als CT-sensor snel is.
  - Sturing algemeen: weet welke sensoren je kunt vertrouwen op 1s vs 30s.

Werking
───────
1. `observe(entity_id, new_value, ts)` — aanroepen bij elke verse sensorlezing.
   Meet het interval tussen significante waarde-wijzigingen (>1W verschil).
   Slaat EMA op (alpha=0.15, traag lerend = stabiel).

2. `get_interval(entity_id)` → float | None
   Geeft geleerd gemiddeld interval in seconden, of None als nog onvoldoende data.

3. `get_all()` → dict  — voor diagnostics sensor / dashboard.

4. `classify(entity_id)` → SensorSpeed
   Classificeert sensor als REALTIME (<2s), FAST (<8s), MEDIUM (<30s),
   SLOW (<120s) of CLOUD (≥120s).

5. Persistentie via HA Storage — overleeft herstart.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
_STORAGE_KEY      = "cloudems_sensor_interval_registry_v1"
_SAVE_INTERVAL_S  = 300         # sla max 1× per 5 min op
_EMA_ALPHA        = 0.15        # traag lerend — stabiel
_MIN_CHANGE_W     = 1.0         # minimale waarde-wijziging om interval te tellen (W)
_MIN_SAMPLES      = 3           # minimaal samples voor betrouwbaar interval
_MAX_INTERVAL_S   = 600.0       # maximale geloofwaardige interval (10 min)
_INITIAL_EMA_S    = 30.0        # startwaarde vóór eerste meting

# Classificatie-drempels (seconden)
REALTIME_THRESHOLD_S = 2.0
FAST_THRESHOLD_S     = 8.0
MEDIUM_THRESHOLD_S   = 30.0
SLOW_THRESHOLD_S     = 120.0


class SensorSpeed(str, Enum):
    """Snelheidsklasse van een sensor op basis van geleerd update-interval."""
    REALTIME = "realtime"   # < 2s   — P1 DSMR5, ESPHome 1kHz
    FAST     = "fast"       # < 8s   — DSMR4, Shelly, smart plug
    MEDIUM   = "medium"     # < 30s  — HomeWizard P1, lokale omvormer API
    SLOW     = "slow"       # < 120s — Solarman, SolarEdge cloud
    CLOUD    = "cloud"      # ≥ 120s — Growatt, Zonneplan, trage cloud APIs
    UNKNOWN  = "unknown"    # nog onvoldoende data


def _speed_from_interval(interval_s: Optional[float]) -> SensorSpeed:
    if interval_s is None:
        return SensorSpeed.UNKNOWN
    if interval_s < REALTIME_THRESHOLD_S:
        return SensorSpeed.REALTIME
    if interval_s < FAST_THRESHOLD_S:
        return SensorSpeed.FAST
    if interval_s < MEDIUM_THRESHOLD_S:
        return SensorSpeed.MEDIUM
    if interval_s < SLOW_THRESHOLD_S:
        return SensorSpeed.SLOW
    return SensorSpeed.CLOUD


# ── Per-sensor state ──────────────────────────────────────────────────────────

@dataclass
class _SensorRecord:
    entity_id:    str
    interval_ema: float       = _INITIAL_EMA_S
    prev_value:   float       = 0.0
    prev_ts:      float       = field(default_factory=time.time)
    sample_count: int         = 0
    last_update:  float       = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "interval_ema": round(self.interval_ema, 3),
            "prev_value":   round(self.prev_value, 2),
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, entity_id: str, d: dict) -> "_SensorRecord":
        r = cls(entity_id=entity_id)
        r.interval_ema = float(d.get("interval_ema", _INITIAL_EMA_S))
        r.prev_value   = float(d.get("prev_value",   0.0))
        r.sample_count = int(d.get("sample_count",   0))
        return r


# ── Hoofdklasse ───────────────────────────────────────────────────────────────

class SensorIntervalRegistry:
    """Centraal register voor update-interval per vermogenssensor.

    Thread-safe genoeg voor async HA-context (single-threaded event loop).
    Werkt zonder HA import — kan ook in unit tests gebruikt worden.
    """

    def __init__(self) -> None:
        self._records: Dict[str, _SensorRecord] = {}
        self._store          = None
        self._dirty          = False
        self._last_save_ts   = 0.0

    # ── Setup / persistentie ─────────────────────────────────────────────────

    async def async_setup(self, hass) -> None:
        """Laad opgeslagen intervallen vanuit HA Storage."""
        try:
            from homeassistant.helpers.storage import Store
            self._store = Store(hass, 1, _STORAGE_KEY)
            data = await self._store.async_load() or {}
            for eid, d in data.items():
                self._records[eid] = _SensorRecord.from_dict(eid, d)
            _LOGGER.debug(
                "SensorIntervalRegistry: %d sensor-records geladen", len(self._records)
            )
        except Exception as exc:
            _LOGGER.warning("SensorIntervalRegistry: laden mislukt: %s", exc)

    async def async_maybe_save(self) -> None:
        """Sla op als dirty + rate-limit niet overschreden."""
        if not self._store or not self._dirty:
            return
        now = time.time()
        if now - self._last_save_ts < _SAVE_INTERVAL_S:
            return
        try:
            payload = {eid: r.to_dict() for eid, r in self._records.items()}
            await self._store.async_save(payload)
            self._dirty      = False
            self._last_save_ts = now
        except Exception as exc:
            _LOGGER.warning("SensorIntervalRegistry: opslaan mislukt: %s", exc)

    # ── Publieke API ─────────────────────────────────────────────────────────

    def observe(self, entity_id: str, value: float, ts: Optional[float] = None) -> None:
        """Verwerk een nieuwe sensorlezing en update het interval-model.

        Args:
            entity_id: HA entity id van de sensor.
            value:     Actuele waarde in W (of kW — maakt niet uit voor interval-meting).
            ts:        Unix timestamp; default = now.
        """
        if not entity_id:
            return
        now = ts if ts is not None else time.time()

        if entity_id not in self._records:
            self._records[entity_id] = _SensorRecord(
                entity_id=entity_id,
                prev_value=value,
                prev_ts=now,
                last_update=now,
            )
            return

        r = self._records[entity_id]
        r.last_update = now

        # Meet interval alleen bij significante waarde-wijziging
        if abs(value - r.prev_value) >= _MIN_CHANGE_W:
            elapsed = now - r.prev_ts
            if 0.2 < elapsed < _MAX_INTERVAL_S:
                # EMA update — traag lerend voor stabiliteit
                r.interval_ema = (
                    _EMA_ALPHA * elapsed + (1.0 - _EMA_ALPHA) * r.interval_ema
                )
                r.sample_count += 1
                self._dirty = True
            r.prev_value = value
            r.prev_ts    = now

    def get_interval(self, entity_id: str) -> Optional[float]:
        """Geef geleerd update-interval in seconden, of None als onvoldoende data."""
        r = self._records.get(entity_id)
        if r is None or r.sample_count < _MIN_SAMPLES:
            return None
        return round(r.interval_ema, 2)

    def classify(self, entity_id: str) -> SensorSpeed:
        """Classificeer sensor als REALTIME / FAST / MEDIUM / SLOW / CLOUD / UNKNOWN."""
        return _speed_from_interval(self.get_interval(entity_id))

    def is_fast_enough_for_nilm(self, entity_id: str) -> bool:
        """True als de sensor snel genoeg is voor nauwkeurige NILM edge-detectie.

        NILM heeft baat bij sensoren die minstens elke 8 seconden updaten.
        Bij tragere sensoren wordt rise_time_reliable=False doorgegeven.
        """
        spd = self.classify(entity_id)
        return spd in (SensorSpeed.REALTIME, SensorSpeed.FAST, SensorSpeed.UNKNOWN)

    def rise_time_reliable(self, entity_id: str) -> bool:
        """Geeft aan of de rise_time van een edge betrouwbaar is voor classificatie.

        Een snelle sensor (<8s) geeft een echte rise_time.
        Een trage cloud-sensor (30-300s) geeft altijd een stap van 1 polling-interval
        — die rise_time is nutteloos voor apparaat-classificatie.
        """
        return self.is_fast_enough_for_nilm(entity_id)

    def nilm_deadband_factor(self, entity_id: str) -> float:
        """Schaalfactor voor NILM-drempel op basis van sensorsnelheid.

        Trage sensoren → grotere deadband (meer ruis/onzekerheid per stap).
        Snelle sensoren → normale (1.0) deadband.

        Returns:
            1.0 voor snelle sensoren.
            1.5-3.0 voor trage cloud-sensoren.
        """
        interval = self.get_interval(entity_id)
        if interval is None or interval <= FAST_THRESHOLD_S:
            return 1.0
        if interval <= MEDIUM_THRESHOLD_S:
            return 1.5
        if interval <= SLOW_THRESHOLD_S:
            return 2.0
        return 3.0  # cloud: zeer grote onzekerheid

    def stale_threshold(self, entity_id: str) -> float:
        """Bereken een sensor-specifieke stale-drempel (seconden).

        Gebaseerd op geleerd interval: als een sensor normaal elke 30s update,
        is het pas echt stale na 3× dat interval (90s), niet na de vaste 120s.
        Snelle sensoren zijn al stale na 3× hun interval (bijv. 3s voor DSMR5).

        Returns:
            Stale-drempel in seconden. Minimum 15s, maximum 600s.
        """
        interval = self.get_interval(entity_id)
        if interval is None:
            return 120.0  # standaard fallback
        return max(15.0, min(600.0, interval * 3.0))

    def get_all(self) -> dict:
        """Geef alle bekende sensors met interval en classificatie — voor diagnostics."""
        result = {}
        for eid, r in self._records.items():
            interval = r.interval_ema if r.sample_count >= _MIN_SAMPLES else None
            result[eid] = {
                "interval_s":   round(interval, 2) if interval is not None else None,
                "speed":        _speed_from_interval(interval).value,
                "sample_count": r.sample_count,
                "stale_after_s": self.stale_threshold(eid),
                "last_update_age_s": round(time.time() - r.last_update, 1),
            }
        return result

    def get_diagnostics(self) -> dict:
        """Samenvatting voor diagnose-dashboard."""
        all_s = self.get_all()
        by_speed: Dict[str, list] = {s.value: [] for s in SensorSpeed}
        for eid, info in all_s.items():
            by_speed[info["speed"]].append(eid)
        return {
            "total_sensors":   len(all_s),
            "by_speed":        {k: len(v) for k, v in by_speed.items()},
            "sensors":         all_s,
            "realtime_count":  len(by_speed[SensorSpeed.REALTIME.value]),
            "fast_count":      len(by_speed[SensorSpeed.FAST.value]),
            "cloud_count":     len(by_speed[SensorSpeed.CLOUD.value]),
        }
