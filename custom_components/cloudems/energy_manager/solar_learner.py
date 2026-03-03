"""
CloudEMS Solar Power Learner — v1.3.0

Leert automatisch per omvormer:
  1. Piekvermogen (Wp) — voor sturing en rapportage
  2. Op welke fase een 1-fase omvormer is aangesloten — voor gerichte dimming
     bij fase-overbelasting

Fase-detectie werkt door correlatie:
  - Bij elke meting: welke fase-stroom steeg het meest toen de PV-output steeg?
  - Na MIN_PHASE_DETECTIONS consistente waarnemingen → fase wordt "zeker" gelabeld
  - Zolang onzeker: alle fasen in aanmerking nemen (veilig gedrag)

Opslag: HA Store (persistent over HA restarts).

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY          = "cloudems_solar_profiles_v2"
STORAGE_VERSION      = 2

# Leer-parameters
IRRADIANCE_MIN_W          = 100    # Metingen onder dit niveau worden genegeerd
MIN_POWER_DELTA_W         = 50     # Minimale stijging om fase-correlatie te meten
MIN_PHASE_DETECTIONS      = 8      # Aantal consistente waarnemingen voor "zeker"
PHASE_CONFIRM_RATIO       = 0.70   # Fase moet in >=70% van waarnemingen de winnaar zijn
LEARNING_SAVE_INTERVAL_S  = 120    # Elke 2 min opslaan als er iets veranderd is


@dataclass
class PhaseVotes:
    """Telt hoe vaak iedere fase de meeste stijging vertoonde tegelijk met PV-stijging."""
    L1: int = 0
    L2: int = 0
    L3: int = 0

    def add(self, phase: str) -> None:
        if phase in ("L1", "L2", "L3"):
            setattr(self, phase, getattr(self, phase) + 1)

    def total(self) -> int:
        return self.L1 + self.L2 + self.L3

    def winner(self, min_ratio: float) -> str | None:
        total = self.total()
        if total == 0:
            return None
        for phase in ("L1", "L2", "L3"):
            if getattr(self, phase) / total >= min_ratio:
                return phase
        return None

    def to_dict(self) -> dict:
        return {"L1": self.L1, "L2": self.L2, "L3": self.L3}


@dataclass
class InverterProfile:
    """Volledig geleerd profiel voor één omvormer / string."""
    inverter_id: str
    label: str
    peak_power_w: float      = 0.0
    peak_power_w_7d: float   = 0.0
    estimated_wp: float      = 0.0
    samples: int             = 0
    last_updated: str        = ""
    confident: bool          = False
    detected_phase: str | None  = None
    phase_certain: bool         = False
    phase_votes: dict           = field(default_factory=dict)
    hourly_peak_w: dict         = field(default_factory=dict)
    # Runtime state (niet persistent)
    _prev_power_w: float        = field(default=0.0, repr=False, compare=False)
    _prev_phase_currents: dict  = field(default_factory=dict, repr=False, compare=False)
    _votes_obj: Any             = field(default=None, repr=False, compare=False)


class SolarPowerLearner:
    """
    Leert het piekvermogen en de fase-aansluiting van meerdere PV-omvormers.

    Gebruik vanuit coordinator:
        await learner.async_setup()
        # elke 10s:
        await learner.async_update(phase_currents={"L1": 8.2, "L2": 3.1, "L3": 4.5})
    """

    def __init__(
        self,
        hass: HomeAssistant,
        inverter_configs: list[dict],
    ) -> None:
        self.hass = hass
        self._configs = inverter_configs
        self._profiles: dict[str, InverterProfile] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._dirty = False
        self._last_save = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}

        for cfg in self._configs:
            eid   = cfg["entity_id"]
            label = cfg.get("label", eid)

            if eid in saved:
                d = saved[eid]
                votes_d = d.get("phase_votes", {})
                votes = PhaseVotes(
                    L1=votes_d.get("L1", 0),
                    L2=votes_d.get("L2", 0),
                    L3=votes_d.get("L3", 0),
                )
                profile = InverterProfile(
                    inverter_id=eid,
                    label=d.get("label", label),
                    peak_power_w=float(d.get("peak_power_w", 0)),
                    peak_power_w_7d=float(d.get("peak_power_w_7d", 0)),
                    estimated_wp=float(d.get("estimated_wp", 0)),
                    samples=int(d.get("samples", 0)),
                    last_updated=d.get("last_updated", ""),
                    confident=bool(d.get("confident", False)),
                    detected_phase=d.get("detected_phase"),
                    phase_certain=bool(d.get("phase_certain", False)),
                    phase_votes=votes_d,
                    hourly_peak_w=d.get("hourly_peak_w", {}),
                    _votes_obj=votes,
                )
                self._profiles[eid] = profile
                _LOGGER.info(
                    "SolarLearner: '%s' geladen — piek %.0fW | fase: %s%s",
                    label, profile.peak_power_w,
                    profile.detected_phase or "onbekend",
                    " (zeker)" if profile.phase_certain else "",
                )
            else:
                profile = InverterProfile(
                    inverter_id=eid, label=label, _votes_obj=PhaseVotes()
                )
                self._profiles[eid] = profile
                _LOGGER.info("SolarLearner: nieuw profiel '%s'", label)

    async def async_update(self, phase_currents: dict[str, float] | None = None) -> None:
        """Hoofdlus — aanroepen vanuit coordinator elke ~10s."""
        now = datetime.now(timezone.utc)
        hour_key = str(now.hour)

        for eid, profile in self._profiles.items():
            state = self.hass.states.get(eid)
            if state is None or state.state in ("unavailable", "unknown"):
                continue
            try:
                power_w = float(state.state)
            except (ValueError, TypeError):
                continue

            # ── Piekvermogen leren ─────────────────────────────────────────────
            if power_w >= IRRADIANCE_MIN_W:
                changed = False

                if power_w > profile.peak_power_w:
                    _LOGGER.info(
                        "SolarLearner '%s': nieuw piek %.0fW (was %.0fW)",
                        profile.label, power_w, profile.peak_power_w,
                    )
                    profile.peak_power_w = round(power_w, 1)
                    changed = True

                if power_w > profile.peak_power_w_7d:
                    profile.peak_power_w_7d = round(power_w, 1)
                    changed = True

                if power_w > profile.hourly_peak_w.get(hour_key, 0.0):
                    profile.hourly_peak_w[hour_key] = round(power_w, 1)
                    changed = True

                profile.samples      += 1
                profile.last_updated  = now.isoformat()
                profile.confident     = profile.samples >= 5
                profile.estimated_wp  = round(profile.peak_power_w / 0.87)

                if changed:
                    self._dirty = True

            # ── Fase-detectie ─────────────────────────────────────────────────
            if not profile.phase_certain and phase_currents and len(phase_currents) >= 2:
                await self._detect_phase(profile, power_w, phase_currents)

            profile._prev_power_w        = power_w
            profile._prev_phase_currents = dict(phase_currents or {})

        # Periodiek opslaan
        if self._dirty and (time.time() - self._last_save) >= LEARNING_SAVE_INTERVAL_S:
            await self._async_save()

    # ── Fase-detectie ──────────────────────────────────────────────────────────

    async def _detect_phase(
        self,
        profile: InverterProfile,
        current_power_w: float,
        phase_currents: dict[str, float],
    ) -> None:
        """
        Stem voor de fase die het meest correleerde met de PV-vermogenstoename.

        Principe:
          Als het PV-vermogen stijgt met >MIN_POWER_DELTA_W, kijk dan welke
          fase-stroom het meest steeg. Dat is hoogstwaarschijnlijk de fase
          waarop de omvormer is aangesloten.
        """
        prev_power  = profile._prev_power_w
        prev_phases = profile._prev_phase_currents

        if not prev_phases or current_power_w < IRRADIANCE_MIN_W:
            return

        power_delta = current_power_w - prev_power
        if power_delta < MIN_POWER_DELTA_W:
            return

        # Fase-stroom-deltas berekenen
        phase_deltas: dict[str, float] = {
            phase: (current_a - prev_phases.get(phase, current_a))
            for phase, current_a in phase_currents.items()
        }

        winner = max(phase_deltas, key=lambda p: phase_deltas[p])
        # Drempel: minimale fase-stijging in relatie tot PV-stijging
        threshold_a = max(0.3, power_delta / 250.0)
        if phase_deltas[winner] < threshold_a:
            return

        votes: PhaseVotes = profile._votes_obj or PhaseVotes()
        votes.add(winner)
        profile.phase_votes = votes.to_dict()
        profile._votes_obj  = votes

        _LOGGER.debug(
            "SolarLearner '%s': fase-stem %s (ΔPV=+%.0fW Δ%s=+%.2fA) | %s",
            profile.label, winner, power_delta, winner,
            phase_deltas[winner], votes.to_dict(),
        )

        # Controleer drempel voor bevestiging
        if votes.total() >= MIN_PHASE_DETECTIONS:
            candidate = votes.winner(PHASE_CONFIRM_RATIO)
            if candidate and candidate != profile.detected_phase:
                _LOGGER.info(
                    "SolarLearner '%s': fase BEVESTIGD → %s  "
                    "(na %d metingen, %.0f%% stemmen)",
                    profile.label, candidate, votes.total(),
                    getattr(votes, candidate) / votes.total() * 100,
                )
                profile.detected_phase = candidate
                profile.phase_certain  = True
                self._dirty = True

            elif not candidate and votes.total() >= MIN_PHASE_DETECTIONS * 2:
                # Onduidelijk → waarschijnlijk 3-fase of noisy sensor
                _LOGGER.warning(
                    "SolarLearner '%s': fase-detectie onduidelijk na %d metingen",
                    profile.label, votes.total(),
                )
                profile.detected_phase = None
                profile.phase_certain  = True
                self._dirty = True

    # ── Queries ────────────────────────────────────────────────────────────────

    def get_profile(self, inverter_id: str) -> InverterProfile | None:
        return self._profiles.get(inverter_id)

    def get_all_profiles(self) -> list[InverterProfile]:
        return list(self._profiles.values())

    def get_inverters_on_phase(self, phase: str) -> list[InverterProfile]:
        """Geeft alle omvormers die zeker op de opgegeven fase zitten."""
        return [
            p for p in self._profiles.values()
            if p.phase_certain and p.detected_phase == phase
        ]

    def get_total_peak_w(self) -> float:
        return sum(p.peak_power_w for p in self._profiles.values())

    def get_total_estimated_wp(self) -> float:
        return sum(p.estimated_wp for p in self._profiles.values())

    def get_current_total_w(self) -> float:
        total = 0.0
        for eid in self._profiles:
            s = self.hass.states.get(eid)
            if s and s.state not in ("unavailable", "unknown"):
                try:
                    total += float(s.state)
                except (ValueError, TypeError):
                    pass
        return total

    def get_utilization_pct(self, inverter_id: str) -> float | None:
        p = self._profiles.get(inverter_id)
        if not p or p.peak_power_w <= 0:
            return None
        s = self.hass.states.get(inverter_id)
        if not s or s.state in ("unavailable", "unknown"):
            return None
        try:
            return round(min(100.0, float(s.state) / p.peak_power_w * 100), 1)
        except (ValueError, TypeError):
            return None

    async def async_reset_profile(self, inverter_id: str) -> None:
        """Reset leermodel voor één omvormer (bijv. na nieuwe panelen)."""
        if inverter_id in self._profiles:
            label = self._profiles[inverter_id].label
            self._profiles[inverter_id] = InverterProfile(
                inverter_id=inverter_id, label=label, _votes_obj=PhaseVotes()
            )
            await self._async_save()
            _LOGGER.info("SolarLearner: profiel '%s' gereset", label)

    def to_dict(self) -> dict[str, Any]:
        return {
            eid: {
                "label":          p.label,
                "peak_power_w":   p.peak_power_w,
                "estimated_wp":   p.estimated_wp,
                "samples":        p.samples,
                "confident":      p.confident,
                "detected_phase": p.detected_phase,
                "phase_certain":  p.phase_certain,
                "phase_votes":    p.phase_votes,
                "last_updated":   p.last_updated,
            }
            for eid, p in self._profiles.items()
        }

    # ── Opslag ────────────────────────────────────────────────────────────────

    async def _async_save(self) -> None:
        data = {
            eid: {
                "label":           p.label,
                "peak_power_w":    p.peak_power_w,
                "peak_power_w_7d": p.peak_power_w_7d,
                "estimated_wp":    p.estimated_wp,
                "samples":         p.samples,
                "last_updated":    p.last_updated,
                "confident":       p.confident,
                "detected_phase":  p.detected_phase,
                "phase_certain":   p.phase_certain,
                "phase_votes":     p.phase_votes,
                "hourly_peak_w":   p.hourly_peak_w,
            }
            for eid, p in self._profiles.items()
        }
        await self._store.async_save(data)
        self._dirty    = False
        self._last_save = time.time()
        _LOGGER.debug("SolarLearner: %d profielen opgeslagen", len(data))
