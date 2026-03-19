# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CloudEMS Shutter Thermal Learner — v1.0.0

Leert de thermische gain per rolluik: hoeveel graden koelt de kamer per %
positiewijziging van het rolluik, uitgesplitst per uur-van-dag en seizoen.

Werking:
  1. Na elke PID-beweging: sla op (ts, pos_voor, pos_na, temp_voor).
  2. Na MEASURE_DELAY_S (15 min): meet temp_na, bereken:
       gain = ΔT / Δpos  [°C per % dichter]
     Verwacht negatief: dichter = koeler.
  3. Update EMA(alpha=0.15) voor dit uur + seizoen.
  4. Na MIN_SAMPLES_CONFIDENT metingen: "confident" → gebruik geleerde gain
     om pid_kp dynamisch te berekenen.
  5. Persisteer via HA Store (zelfde patroon als solar_learner).

Gebruik vanuit shutter_controller:
    learner.record_move(entity_id, pos_before, pos_after, temp_now)
    learner.update_temp(entity_id, temp_now)   # elke tick (10s)
    kp = learner.get_effective_kp(entity_id, hour, is_summer, fallback_kp)

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

STORAGE_KEY     = "cloudems_shutter_thermal_v1"
STORAGE_VERSION = 1

EMA_ALPHA           = 0.15    # smoothing factor voor gain-updates
MIN_SAMPLES_CONFIDENT = 5     # minimaal 5 metingen voor "confident"
MEASURE_DELAY_S     = 900     # 15 minuten wachten na PID-beweging voor meting
MIN_POS_CHANGE      = 8       # minimale positieverandering om te meten (%)
MIN_TEMP_RESOLUTION = 0.05    # sensorresolutie — onder dit is meting ruis (°C)
MAX_GAIN            = -0.005  # maximale (zwakste) gain: -0.005°C per %
MIN_GAIN            = -0.30   # minimale (sterkste) gain: -0.30°C per %

# Referentie gain als er nog geen metingen zijn
DEFAULT_GAIN        = -0.05   # -0.05°C per % (conservatief startpunt)

# Target ΔT en Δpos voor kp-berekening
TARGET_DT           = 0.5     # we willen 0.5°C correctie
TARGET_DPOS         = 15      # bij 15% positiewijziging

# Seizoen
def _is_summer(month: int) -> bool:
    return 4 <= month <= 9


def _season(month: int) -> str:
    return "summer" if _is_summer(month) else "winter"


def _hour_slot(hour: int) -> int:
    """Groepeer uren in slots van 2 uur voor robuustere statistieken."""
    return (hour // 2) * 2   # 0,2,4,...,22


@dataclass
class GainSample:
    """Één gain-meting."""
    ts:          float
    hour_slot:   int
    season:      str
    pos_change:  float   # % dichter (positief = dichter)
    delta_temp:  float   # °C verandering na MEASURE_DELAY_S
    gain:        float   # delta_temp / pos_change


@dataclass
class ShutterGainProfile:
    """Geleerde thermische gain per rolluik."""
    entity_id:   str
    label:       str = ""

    # gain[season][hour_slot] = EMA waarde
    gain: dict = field(default_factory=dict)   # {"summer": {0: -0.08, 2: -0.12, ...}}
    samples: dict = field(default_factory=dict) # {"summer": {0: 5, 2: 3, ...}}
    last_updated: float = 0.0

    def get_gain(self, hour: int, is_summer: bool) -> float:
        """Geef geleerde gain terug, of DEFAULT_GAIN als nog onbekend."""
        s = "summer" if is_summer else "winter"
        slot = _hour_slot(hour)
        return (self.gain.get(s) or {}).get(slot, DEFAULT_GAIN)

    def get_samples(self, hour: int, is_summer: bool) -> int:
        s = "summer" if is_summer else "winter"
        slot = _hour_slot(hour)
        return (self.samples.get(s) or {}).get(slot, 0)

    def is_confident(self, hour: int, is_summer: bool) -> bool:
        return self.get_samples(hour, is_summer) >= MIN_SAMPLES_CONFIDENT

    def update(self, hour: int, is_summer: bool, gain: float) -> None:
        """Update EMA voor dit uur + seizoen."""
        s = "summer" if is_summer else "winter"
        slot = _hour_slot(hour)
        self.gain.setdefault(s, {})
        self.samples.setdefault(s, {})
        prev = self.gain[s].get(slot, gain)  # eerste keer: start met de meting zelf
        self.gain[s][slot] = round(prev * (1 - EMA_ALPHA) + gain * EMA_ALPHA, 5)
        self.samples[s][slot] = self.samples[s].get(slot, 0) + 1
        self.last_updated = time.time()

    def get_effective_kp(self, hour: int, is_summer: bool, fallback_kp: float) -> float:
        """
        Bereken een dynamische pid_kp op basis van de geleerde gain.

        Formule: kp = TARGET_DT / (|gain| × TARGET_DPOS)
        Voorbeeld: gain = -0.08°C/% → kp = 0.5 / (0.08 × 15) = 0.417
        Maar de PID gebruikt error × kp → raw_output → positie.
        We willen dat bij error=+1°C, de positie ~TARGET_DPOS% daalt.
        Dus: kp_effectief = TARGET_DPOS / (TARGET_DT / |gain|) ... vereenvoudigd:
             kp_effectief = TARGET_DPOS × |gain| / TARGET_DT

        Clampen tussen 5.0 (zwak) en 50.0 (sterk).
        """
        if not self.is_confident(hour, is_summer):
            return fallback_kp
        g = abs(self.get_gain(hour, is_summer))
        if g < 0.001:
            return fallback_kp
        kp = TARGET_DPOS * g / TARGET_DT
        return round(max(5.0, min(50.0, kp)), 2)

    def to_dict(self) -> dict:
        return {
            "entity_id":    self.entity_id,
            "label":        self.label,
            "gain":         self.gain,
            "samples":      self.samples,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ShutterGainProfile":
        p = cls(entity_id=d.get("entity_id", ""), label=d.get("label", ""))
        p.gain         = d.get("gain", {})
        p.samples      = d.get("samples", {})
        p.last_updated = float(d.get("last_updated", 0.0))
        return p


@dataclass
class PendingMeasurement:
    """Een lopende meting na een PID-beweging."""
    entity_id:   str
    ts_move:     float   # timestamp van de beweging
    pos_before:  float
    pos_after:   float
    temp_before: float
    hour:        int
    is_summer:   bool
    measured:    bool = False


class ShutterThermalLearner:
    """
    Leert de thermische gain per rolluik en levert dynamische PID kp-waarden.

    Aanroepen vanuit ShutterController:
        learner.record_move(entity_id, label, pos_before, pos_after, temp_now, hour, is_summer)
        learner.tick(entity_id, temp_now)   # elke coordinator-tick
        kp = learner.get_effective_kp(entity_id, hour, is_summer, fallback_kp)
    """

    _SAVE_INTERVAL_S = 300  # sla op elke 5 minuten als dirty

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass     = hass
        self._store    = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._profiles: dict[str, ShutterGainProfile] = {}
        self._pending:  dict[str, PendingMeasurement] = {}   # entity_id → meting
        self._dirty    = False
        self._last_save: float = 0.0

    async def async_setup(self) -> None:
        """Laad opgeslagen profielen."""
        saved = await self._store.async_load() or {}
        for eid, d in saved.items():
            self._profiles[eid] = ShutterGainProfile.from_dict(d)
        _LOGGER.info(
            "CloudEMS ShutterThermalLearner: %d profielen geladen", len(self._profiles)
        )

    async def async_save(self) -> None:
        """Sla profielen op."""
        data = {eid: p.to_dict() for eid, p in self._profiles.items()}
        await self._store.async_save(data)
        self._dirty     = False
        self._last_save = time.time()

    async def async_flush_if_dirty(self) -> None:
        """Sla op als er wijzigingen zijn en de save-interval verstreken is."""
        if self._dirty and (time.time() - self._last_save) >= self._SAVE_INTERVAL_S:
            await self.async_save()

    def _profile(self, entity_id: str, label: str = "") -> ShutterGainProfile:
        if entity_id not in self._profiles:
            self._profiles[entity_id] = ShutterGainProfile(
                entity_id=entity_id, label=label
            )
        return self._profiles[entity_id]

    def record_move(
        self,
        entity_id:   str,
        label:       str,
        pos_before:  float,
        pos_after:   float,
        temp_before: float,
        hour:        int,
        is_summer:   bool,
    ) -> None:
        """
        Registreer een PID-positiewijziging voor latere temperatuurmeting.
        Alleen opslaan als de positieverandering groot genoeg is.
        """
        delta_pos = pos_before - pos_after  # positief = dichter
        if abs(delta_pos) < MIN_POS_CHANGE:
            return

        # Zorg voor profiel
        self._profile(entity_id, label)

        # Overschrijf eventuele eerdere pending meting (meest recente move telt)
        self._pending[entity_id] = PendingMeasurement(
            entity_id   = entity_id,
            ts_move     = time.time(),
            pos_before  = pos_before,
            pos_after   = pos_after,
            temp_before = temp_before,
            hour        = hour,
            is_summer   = is_summer,
        )
        _LOGGER.debug(
            "ShutterThermalLearner [%s]: move %.0f→%.0f%% geregistreerd (temp=%.1f°C)",
            label or entity_id, pos_before, pos_after, temp_before,
        )

    def tick(self, entity_id: str, temp_now: float) -> None:
        """
        Elke coordinator-tick aanroepen met huidige kamertemperatuur.
        Na MEASURE_DELAY_S: bereken gain en update profiel.
        """
        pm = self._pending.get(entity_id)
        if pm is None or pm.measured:
            return

        elapsed = time.time() - pm.ts_move
        if elapsed < MEASURE_DELAY_S:
            return

        # Genoeg tijd verstreken — verwerk de meting
        delta_temp = temp_now - pm.temp_before
        delta_pos  = pm.pos_before - pm.pos_after  # positief = dichter

        if abs(delta_pos) < MIN_POS_CHANGE:
            pm.measured = True
            return

        if abs(delta_temp) < MIN_TEMP_RESOLUTION:
            # Geen meetbaar effect — skip (kan ruis zijn)
            _LOGGER.debug(
                "ShutterThermalLearner [%s]: ΔT=%.2f°C te klein voor meting — skip",
                entity_id, delta_temp,
            )
            pm.measured = True
            return

        gain = delta_temp / delta_pos   # °C per % dichter (verwacht negatief)

        # Plausibiliteitscheck — extreme waarden negeren
        if gain > MAX_GAIN or gain < MIN_GAIN:
            _LOGGER.debug(
                "ShutterThermalLearner [%s]: gain=%.4f buiten bereik [%.3f, %.3f] — skip",
                entity_id, gain, MIN_GAIN, MAX_GAIN,
            )
            pm.measured = True
            return

        profile = self._profile(entity_id)
        profile.update(pm.hour, pm.is_summer, gain)
        pm.measured = True
        self._dirty  = True

        _LOGGER.info(
            "ShutterThermalLearner [%s]: gain %.4f°C/%% geleerd "
            "(uur=%d, %s, pos %.0f→%.0f%%, ΔT=%.2f°C, elapsed=%.0fs)",
            entity_id, gain, pm.hour,
            "zomer" if pm.is_summer else "winter",
            pm.pos_before, pm.pos_after, delta_temp, elapsed,
        )

    def get_effective_kp(
        self,
        entity_id:   str,
        hour:        int,
        is_summer:   bool,
        fallback_kp: float,
    ) -> float:
        """Geef dynamische kp terug op basis van geleerde gain."""
        p = self._profiles.get(entity_id)
        if p is None:
            return fallback_kp
        return p.get_effective_kp(hour, is_summer, fallback_kp)

    def get_status(self) -> list[dict]:
        """Statusoverzicht voor dashboard/sensor."""
        now = datetime.now(tz=timezone.utc)
        result = []
        for eid, p in self._profiles.items():
            # Huidig uur + seizoen
            hour      = now.hour
            is_summer = _is_summer(now.month)
            gain_now  = p.get_gain(hour, is_summer)
            samples_now = p.get_samples(hour, is_summer)
            confident_now = p.is_confident(hour, is_summer)
            kp_now    = p.get_effective_kp(hour, is_summer, fallback_kp=15.0)

            # Alle geleerde slots samenvatten
            total_samples = sum(
                n for season in p.samples.values()
                for n in season.values()
            )
            result.append({
                "entity_id":       eid,
                "label":           p.label,
                "gain_now":        round(gain_now, 5),
                "samples_now":     samples_now,
                "confident_now":   confident_now,
                "kp_now":          kp_now,
                "total_samples":   total_samples,
                "season":          "zomer" if is_summer else "winter",
                "hour_slot":       _hour_slot(hour),
                "gain_all":        {
                    s: {str(h): round(g, 5) for h, g in slots.items()}
                    for s, slots in p.gain.items()
                },
            })
        return result
