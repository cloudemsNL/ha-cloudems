# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CloudEMS Shutter PID Gain Learner — v1.0.0

Leert de effectieve gain (ΔT/Δpositie) per rolluik per uur en seizoen.

Principe:
  1. Na elke PID-beweging sla op: {pos_voor, temp_voor, timestamp, uur, seizoen}
  2. 10 minuten later: meet temp_na
  3. Bereken effectieve gain = ΔT / |Δpos|  (°C per % positiewijziging)
     - Negatieve gain = sluiten (lager %) koelt de kamer → correct gedrag
     - Positieve gain = sluiten warmt de kamer op → onverwacht
  4. Update EMA per (entity_id, uur, seizoen) met α=0.15
  5. Gebruik geleerde gain om pid_kp bij te stellen:
     - Hoge gain (veel effect) → lagere kp nodig
     - Lage gain (weinig effect) → hogere kp nodig

Seizoenen (op basis van maand):
  winter:  dec, jan, feb
  spring:  mrt, apr, mei
  summer:  jun, jul, aug
  autumn:  sep, okt, nov

Opslag: HA Store "cloudems_shutter_pid_learner_v1"
Elke entry: {"gain_ema": float, "samples": int, "last_updated": iso_str}

Copyright © 2025-2026 CloudEMS — https://cloudems.eu
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

STORAGE_KEY     = "cloudems_shutter_pid_learner_v1"
STORAGE_VERSION = 1

# EMA smoothing factor — α=0.15 zodat uitschieters weinig invloed hebben
EMA_ALPHA = 0.15

# Minimum positiewijziging om gain te kunnen meten (%)
MIN_DELTA_POS = 5

# Tijd na beweging om temperatuureffect te meten (seconden)
MEASURE_DELAY_S = 600  # 10 minuten

# Minimum temperatuurverschil om als meting te tellen (°C)
MIN_DELTA_TEMP = 0.05

# Standaard pid_kp als nog geen data (zelfde als ShutterConfig default)
DEFAULT_KP = 15.0

# Referentie gain: bij deze gain is de standaard kp optimaal
# Calibratie: gain ≈ 0.05 °C/% → kp=15 geeft ~0.75°C correctie per tick
REFERENCE_GAIN = 0.05

# Grenzen voor gecalibreerde kp
MIN_KP = 3.0
MAX_KP = 50.0

# Seizoenen
SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3:  "spring", 4: "spring", 5: "spring",
    6:  "summer", 7: "summer", 8: "summer",
    9:  "autumn", 10: "autumn", 11: "autumn",
}

# Auto-save interval
SAVE_INTERVAL_S = 120


@dataclass
class PendingMeasurement:
    """Een PID-beweging die wacht op de temperatuurmeting na 10 minuten."""
    entity_id:    str
    pos_before:   int
    pos_after:    int
    temp_before:  float
    timestamp:    float   # time.time() van de beweging
    hour:         int
    season:       str


@dataclass
class GainEntry:
    """Geleerde gain voor één (entity_id, hour, season) combinatie."""
    gain_ema:     float = 0.0
    samples:      int   = 0
    last_updated: str   = ""


class ShutterPIDLearner:
    """
    Leert de effectieve thermische gain per rolluik per uur en seizoen.

    Gebruik:
        learner = ShutterPIDLearner(hass)
        await learner.async_setup()

        # Na elke PID-beweging:
        learner.record_movement(entity_id, pos_before, pos_after, temp_before)

        # Elke coordinator-tick (10s):
        await learner.async_tick(entity_id, current_temp)

        # Gecalibreerde kp opvragen:
        kp = learner.get_calibrated_kp(entity_id, hour, season)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass    = hass
        self._store   = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # Geleerde gains: {entity_id: {season: {hour: GainEntry}}}
        self._gains:   dict[str, dict[str, dict[int, GainEntry]]] = {}
        # Wachtende metingen: {entity_id: PendingMeasurement}
        self._pending: dict[str, PendingMeasurement] = {}
        self._dirty   = False
        self._last_save = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Laad opgeslagen gains van HA Storage."""
        saved = await self._store.async_load() or {}
        for eid, seasons in saved.items():
            self._gains[eid] = {}
            for season, hours in seasons.items():
                self._gains[eid][season] = {}
                for hour_str, entry in hours.items():
                    self._gains[eid][season][int(hour_str)] = GainEntry(
                        gain_ema     = float(entry.get("gain_ema", 0.0)),
                        samples      = int(entry.get("samples", 0)),
                        last_updated = entry.get("last_updated", ""),
                    )
        _LOGGER.info(
            "CloudEMS ShutterPIDLearner: geladen — %d rolluiken, %d gain-entries",
            len(self._gains),
            sum(len(h) for s in self._gains.values() for h in s.values()),
        )

    async def async_save(self) -> None:
        """Sla gains op naar HA Storage."""
        data = {}
        for eid, seasons in self._gains.items():
            data[eid] = {}
            for season, hours in seasons.items():
                data[eid][season] = {}
                for hour, entry in hours.items():
                    data[eid][season][str(hour)] = {
                        "gain_ema":     round(entry.gain_ema, 6),
                        "samples":      entry.samples,
                        "last_updated": entry.last_updated,
                    }
        await self._store.async_save(data)
        self._dirty     = False
        self._last_save = time.time()

    async def async_flush_if_dirty(self) -> None:
        """Sla op als er nieuwe data is en het interval verstreken is."""
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()

    # ── Publieke API ───────────────────────────────────────────────────────────

    def record_movement(
        self,
        entity_id:   str,
        pos_before:  int,
        pos_after:   int,
        temp_before: float,
    ) -> None:
        """
        Registreer een PID-beweging. Na MEASURE_DELAY_S seconden wordt de
        temperatuur opnieuw gemeten via async_tick().
        """
        delta_pos = abs(pos_after - pos_before)
        if delta_pos < MIN_DELTA_POS:
            return  # Beweging te klein om te meten

        now       = time.time()
        now_dt    = datetime.fromtimestamp(now, tz=timezone.utc)
        hour      = now_dt.hour
        season    = SEASONS.get(now_dt.month, "spring")

        self._pending[entity_id] = PendingMeasurement(
            entity_id   = entity_id,
            pos_before  = pos_before,
            pos_after   = pos_after,
            temp_before = temp_before,
            timestamp   = now,
            hour        = hour,
            season      = season,
        )
        _LOGGER.debug(
            "PIDLearner[%s]: beweging %d→%d% geregistreerd (temp_voor=%.1f°C, uur=%d, seizoen=%s)",
            entity_id, pos_before, pos_after, temp_before, hour, season,
        )

    async def async_tick(self, entity_id: str, current_temp: float | None) -> None:
        """
        Aanroepen elke coordinator-tick. Als er een pending meting is voor
        dit rolluik en MEASURE_DELAY_S verstreken is, verwerk de meting.
        """
        pm = self._pending.get(entity_id)
        if pm is None or current_temp is None:
            return

        elapsed = time.time() - pm.timestamp
        if elapsed < MEASURE_DELAY_S:
            return  # Nog niet genoeg tijd verstreken

        # Meting uitvoeren
        delta_temp = current_temp - pm.temp_before
        delta_pos  = pm.pos_after - pm.pos_before  # negatief = sluiten

        # Gain = ΔT / Δpos
        # Bij sluiten (delta_pos < 0) verwachten we delta_temp < 0 (koeler)
        # Gain positief = koeling werkt, negatief = onverwacht
        if abs(delta_pos) < MIN_DELTA_POS:
            del self._pending[entity_id]
            return

        gain = delta_temp / delta_pos  # °C per %

        # Alleen meten als temperatuurverandering meetbaar is
        if abs(delta_temp) < MIN_DELTA_TEMP:
            _LOGGER.debug(
                "PIDLearner[%s]: ΔT=%.2f°C te klein — meting overgeslagen",
                entity_id, delta_temp,
            )
            del self._pending[entity_id]
            return

        # EMA update
        self._update_gain(entity_id, pm.hour, pm.season, gain)
        del self._pending[entity_id]

        _LOGGER.info(
            "PIDLearner[%s]: ΔT=%.2f°C Δpos=%d%% → gain=%.4f °C/%% "
            "(uur=%d, %s, %d samples)",
            entity_id, delta_temp, delta_pos, gain,
            pm.hour, pm.season,
            self._gains.get(entity_id, {}).get(pm.season, {}).get(pm.hour, GainEntry()).samples,
        )

    def get_calibrated_kp(
        self,
        entity_id: str,
        hour:      int,
        season:    str,
        default_kp: float = DEFAULT_KP,
    ) -> float:
        """
        Geeft gecalibreerde pid_kp terug op basis van geleerde gain.

        Formule: kp_cal = kp_default × (REFERENCE_GAIN / gain_ema)

        Interpretatie:
          - Hoge gain (raam heeft groot effect) → kp omlaag (anders oscillatie)
          - Lage gain (raam heeft weinig effect) → kp omhoog (anders te traag)

        Returns default_kp als nog geen data beschikbaar.
        """
        entry = self._get_entry(entity_id, hour, season)
        if entry is None or entry.samples < 3 or abs(entry.gain_ema) < 0.001:
            return default_kp  # Nog niet genoeg data

        kp_cal = default_kp * (REFERENCE_GAIN / abs(entry.gain_ema))
        kp_cal = max(MIN_KP, min(MAX_KP, kp_cal))
        return round(kp_cal, 2)

    def get_status(self) -> dict:
        """Geef status dict voor dashboard/sensor."""
        result = {}
        for eid, seasons in self._gains.items():
            result[eid] = {}
            for season, hours in seasons.items():
                entries = []
                for hour, entry in sorted(hours.items()):
                    entries.append({
                        "hour":         hour,
                        "gain_ema":     round(entry.gain_ema, 4),
                        "samples":      entry.samples,
                        "last_updated": entry.last_updated,
                        "kp_cal":       round(
                            DEFAULT_KP * (REFERENCE_GAIN / abs(entry.gain_ema))
                            if abs(entry.gain_ema) > 0.001 else DEFAULT_KP,
                            2
                        ),
                    })
                result[eid][season] = entries
        return result

    def get_summary(self, entity_id: str) -> dict:
        """Compacte samenvatting per rolluik voor shutter-card dashboard."""
        seasons_data = self._gains.get(entity_id, {})
        total_samples = sum(
            e.samples
            for s in seasons_data.values()
            for e in s.values()
        )
        # Huidige gain
        now_dt   = datetime.now(tz=timezone.utc)
        hour     = now_dt.hour
        season   = SEASONS.get(now_dt.month, "spring")
        entry    = self._get_entry(entity_id, hour, season)
        cur_gain = round(entry.gain_ema, 4) if entry else None
        cur_kp   = self.get_calibrated_kp(entity_id, hour, season)
        confident = total_samples >= 10

        return {
            "total_samples": total_samples,
            "current_gain":  cur_gain,
            "current_kp":    cur_kp,
            "confident":     confident,
            "season":        season,
            "hour":          hour,
        }

    # ── Intern ────────────────────────────────────────────────────────────────

    def _get_entry(
        self, entity_id: str, hour: int, season: str
    ) -> GainEntry | None:
        return self._gains.get(entity_id, {}).get(season, {}).get(hour)

    def _update_gain(
        self, entity_id: str, hour: int, season: str, new_gain: float
    ) -> None:
        """EMA update van gain voor (entity_id, hour, season)."""
        if entity_id not in self._gains:
            self._gains[entity_id] = {}
        if season not in self._gains[entity_id]:
            self._gains[entity_id][season] = {}

        existing = self._gains[entity_id][season].get(hour)
        if existing is None or existing.samples == 0:
            # Eerste meting — gebruik direct
            ema = new_gain
            samples = 1
        else:
            ema = EMA_ALPHA * new_gain + (1 - EMA_ALPHA) * existing.gain_ema
            samples = existing.samples + 1

        self._gains[entity_id][season][hour] = GainEntry(
            gain_ema     = ema,
            samples      = samples,
            last_updated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._dirty = True
