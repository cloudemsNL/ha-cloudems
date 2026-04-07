"""
phase_current_fusion.py — v4.6.530

Zelflerend gewogen gemiddelde van fase-stroom schattingen.

Methoden per fase:
  direct_sensor      : geconfigureerde stroomsensor (A)
  p1_current         : DSMR P1 stroom (integer bij DSMR4, actueel bij DSMR5)
  power_div_voltage  : vermogenssensor / gemeten spanning
  power_div_mains    : vermogenssensor / mains_v (230V fallback)
  p1power_div_voltage: P1 per-fase vermogen / gemeten spanning
  p1power_div_mains  : P1 per-fase vermogen / mains_v

Leren (elke 10s cyclus):
  - Bereken alle beschikbare schattingen
  - Vergelijk elk paar: afwijking = |A - B| / max(|A|, |B|, 0.5)
  - EMA van afwijking per methode t.o.v. consensus
  - Gewicht = 1 / (ema_deviation + EPSILON)
  - Gewogen gemiddelde = eindwaarde

Realtime pad (elke P1 telegram):
  - Gebruik gecachede gewichten — geen EMA-updates
  - Alleen berekening, geen I/O

Tekenbepaling (gesigneerde stroom):
  - Positief = import, negatief = export
  - Teken bepaald door: netto vermogen > 5W → sign(power_w)
  - Fallback: positief (import)

Persistentie: HA Storage cloudems_phase_current_fusion_v1
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_phase_current_fusion_v1"
STORAGE_VERSION = 1
EMA_ALPHA       = 0.08    # traag leren — stabiele gewichten
EPSILON         = 0.15    # minimale afwijking (A) — voorkomt deling door nul
MIN_SAMPLES     = 8       # minimum samples voor vertrouwen op geleerd gewicht
SAVE_INTERVAL   = 30      # dirty-updates vóór opslaan
STALE_SECONDS   = 120.0   # max leeftijd van een schatting

METHODS = [
    "direct_sensor",
    "p1_current",
    "power_div_voltage",
    "power_div_mains",
    "p1power_div_voltage",
    "p1power_div_mains",
]

_INITIAL_WEIGHT = 0.5     # neutrale startwaarde


class _MethodState:
    """Toestand per methode per fase."""
    __slots__ = ("ema_deviation", "sample_count", "last_value", "last_ts")

    def __init__(self) -> None:
        self.ema_deviation: float = EPSILON   # start neutraal
        self.sample_count:  int   = 0
        self.last_value:    Optional[float] = None
        self.last_ts:       float = 0.0

    def to_dict(self) -> dict:
        return {
            "ema_dev": round(self.ema_deviation, 6),
            "samples": self.sample_count,
        }

    def from_dict(self, d: dict) -> None:
        self.ema_deviation = float(d.get("ema_dev", EPSILON))
        self.sample_count  = int(d.get("samples", 0))


class PhaseCurrentFusion:
    """Zelflerend gewogen gemiddelde van fase-stroom schattingen."""

    def __init__(self, hass, phases: list[str]) -> None:
        self._hass   = hass
        self._phases = phases
        # state[fase][methode] = _MethodState
        self._state: Dict[str, Dict[str, _MethodState]] = {
            ph: {m: _MethodState() for m in METHODS}
            for ph in phases
        }
        self._dirty_count = 0
        self._store       = None   # geladen in async_setup

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        await self._async_load()

    async def _async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        for ph in self._phases:
            ph_data = data.get(ph, {})
            for m in METHODS:
                if m in ph_data:
                    self._state[ph][m].from_dict(ph_data[m])
        _LOGGER.debug("PhaseCurrentFusion: gewichten geladen uit storage")

    async def _async_save(self) -> None:
        data = {
            ph: {m: self._state[ph][m].to_dict() for m in METHODS}
            for ph in self._phases
        }
        await self._store.async_save(data)
        self._dirty_count = 0

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL:
            await self._async_save()

    # ── Publieke interface ────────────────────────────────────────────────────

    def fuse_and_learn(
        self,
        phase:      str,
        estimates:  Dict[str, Optional[float]],   # {method: abs_ampere or None}
        power_w:    Optional[float] = None,        # netto vermogen voor tekenbepaling
    ) -> float:
        """Volledige fusie met leren. Aanroepen vanuit 10s coordinator-cyclus."""
        now = time.time()
        st = self._state.get(phase, {})
        if not st:
            return 0.0

        # Bewaar laatste waarden
        for m, val in estimates.items():
            if m in st and val is not None:
                st[m].last_value = val
                st[m].last_ts    = now

        valid = {m: v for m, v in estimates.items() if v is not None and m in st}
        if not valid:
            return 0.0

        # Consensus = ongewogen gemiddelde van beschikbare schattingen
        consensus = sum(valid.values()) / len(valid)

        # Update EMA van afwijking per methode
        for m, val in valid.items():
            deviation = abs(val - consensus) / max(abs(consensus), 0.5)
            s = st[m]
            s.ema_deviation = EMA_ALPHA * deviation + (1.0 - EMA_ALPHA) * s.ema_deviation
            s.sample_count  = min(s.sample_count + 1, 9999)
            self._dirty_count += 1

        # Gewogen gemiddelde
        fused_abs = self._weighted_average(phase, valid)

        # Teken bepalen
        sign = self._determine_sign(power_w, estimates)

        return round(fused_abs * sign, 3)

    def fuse_fast(
        self,
        phase:      str,
        estimates:  Dict[str, Optional[float]],
        power_w:    Optional[float] = None,
    ) -> float:
        """Lichtgewicht fusie zonder leren. Aanroepen vanuit realtime P1 callback."""
        valid = {m: v for m, v in estimates.items()
                 if v is not None and m in self._state.get(phase, {})}
        if not valid:
            return 0.0

        fused_abs = self._weighted_average(phase, valid)
        sign      = self._determine_sign(power_w, estimates)
        return round(fused_abs * sign, 3)

    def get_diagnostics(self, phase: str) -> dict:
        """Geef diagnostics terug voor sensor/dashboard."""
        st = self._state.get(phase, {})
        return {
            m: {
                "weight":   round(self._weight(st[m]), 3),
                "ema_dev":  round(st[m].ema_deviation, 4),
                "samples":  st[m].sample_count,
                "trusted":  st[m].sample_count >= MIN_SAMPLES,
            }
            for m in METHODS if m in st
        }

    # ── Interne helpers ───────────────────────────────────────────────────────

    def _weight(self, s: _MethodState) -> float:
        """Gewicht voor een methode. Onervaren methodes krijgen neutraal gewicht."""
        if s.sample_count < MIN_SAMPLES:
            return _INITIAL_WEIGHT
        return 1.0 / (s.ema_deviation + EPSILON)

    # Methodes die betrouwbaar zijn direct na herstart (geen leren nodig)
    _TRUSTED_COLD = frozenset(["p1_current", "p1power_div_voltage", "p1power_div_mains"])

    def _weighted_average(self, phase: str, valid: Dict[str, float]) -> float:
        st = self._state[phase]
        # v5.5.278: na herstart (sample_count < MIN_SAMPLES) alleen P1-gebaseerde
        # methodes gebruiken — andere methodes hebben nog geen betrouwbare gewichten
        # en kunnen extreme uitschieters produceren (bijv. 48A bij 1.4A werkelijk).
        cold_start = any(
            st[m].sample_count < MIN_SAMPLES
            for m in valid if m in st
        )
        if cold_start:
            cold_valid = {m: v for m, v in valid.items() if m in self._TRUSTED_COLD}
            if cold_valid:
                return sum(cold_valid.values()) / len(cold_valid)
        total_w = 0.0
        total_v = 0.0
        for m, val in valid.items():
            w = self._weight(st[m])
            total_w += w
            total_v += w * abs(val)
        if total_w <= 0:
            return sum(valid.values()) / len(valid)
        return total_v / total_w

    @staticmethod
    def _determine_sign(
        power_w:   Optional[float],
        estimates: Dict[str, Optional[float]],
    ) -> float:
        """Bepaal tekens via nettovermogen. Positief = import, negatief = export."""
        if power_w is not None and abs(power_w) > 5.0:
            return 1.0 if power_w >= 0.0 else -1.0
        # Fallback: directe stroomsensor als die al gesigneerd is
        direct = estimates.get("direct_sensor")
        if direct is not None:
            return 1.0 if direct >= 0.0 else -1.0
        return 1.0   # standaard import

    # ── Hulpmethode: bouw estimates dict uit ruwe meetwaarden ─────────────────

    @staticmethod
    def build_estimates(
        raw_sensor_a:      Optional[float],
        p1_current_a:      Optional[float],
        raw_power_w:       Optional[float],
        p1_power_w:        Optional[float],
        voltage_v:         float,
        mains_v:           float,
    ) -> Dict[str, Optional[float]]:
        """Bereken alle beschikbare schattingen vanuit ruwe meetwaarden."""
        estimates: Dict[str, Optional[float]] = {}

        # Directe stroomsensor
        estimates["direct_sensor"] = abs(raw_sensor_a) if raw_sensor_a is not None else None

        # P1 stroom (afgerond bij DSMR4, actueel bij DSMR5)
        estimates["p1_current"] = abs(p1_current_a) if p1_current_a is not None else None

        # I = P_sensor / U_gemeten
        if raw_power_w is not None and voltage_v > 0:
            estimates["power_div_voltage"] = abs(raw_power_w) / voltage_v
        else:
            estimates["power_div_voltage"] = None

        # I = P_sensor / U_mains
        if raw_power_w is not None and mains_v > 0:
            estimates["power_div_mains"] = abs(raw_power_w) / mains_v
        else:
            estimates["power_div_mains"] = None

        # I = P_p1 / U_gemeten
        if p1_power_w is not None and voltage_v > 0:
            estimates["p1power_div_voltage"] = abs(p1_power_w) / voltage_v
        else:
            estimates["p1power_div_voltage"] = None

        # I = P_p1 / U_mains
        if p1_power_w is not None and mains_v > 0:
            estimates["p1power_div_mains"] = abs(p1_power_w) / mains_v
        else:
            estimates["p1power_div_mains"] = None

        return estimates
