"""
CloudEMS Solar Power Learner — v1.5.0

Leert automatisch per omvormer:
  1. Piekvermogen (Wp) — voor sturing en rapportage
  2. Op welke fase een 1-fase omvormer is aangesloten
  3. Of een omvormer 3-fasig is (nieuw in v1.5.0)

Nieuw in v1.5.0:
  - 3-fase detectie: wanneer alle drie fasen tegelijk en proportioneel stijgen
    bij een vermogenssprong wordt de omvormer als "3F" gelabeld.
  - THREE_PHASE_BALANCE_RATIO: de drie deltawaarden moeten binnen deze
    verhouding van elkaar liggen om als "3-fasig" te worden herkend.
  - THREE_PHASE_MIN_DETECTIONS: aantal bevestigingen vóór definitief "3F".
  - detected_phase kan nu ook "3F" zijn naast "L1"/"L2"/"L3".
  - Opslag en sensor-output uitgebreid met is_three_phase vlag.
  - Cross-validatie werkt ook voor 3F: verwacht dat alle fasen gelijkmatig
    blijven meebewegen; anders herstart leerproces.

Nieuw in v1.4.0:
  - Cross-validatie na bevestiging: passieve monitoring na phase_certain=True.
    Als de bevestigde fase structureel verliest (< CROSSVAL_MIN_RATIO) →
    automatische herstart van het leerproces.
  - Nieuwe-panelen-detectie: vermogen >120% van piek voor 3 metingen op rij
    → automatische reset van het piekvermogenprofiel.
  - Backup-integratie: schrijft ook naar LearningBackup (15 min).
    Bij lege Store → automatisch terugvallen op backup.
  - phase_conflict_pct in sensor-output zodat dashboard conflict kan tonen.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY          = "cloudems_solar_profiles_v2"
STORAGE_VERSION      = 2
BACKUP_KEY           = "solar_learner"

IRRADIANCE_MIN_W         = 100
MIN_POWER_DELTA_W        = 50
MIN_PHASE_DETECTIONS     = 5
PHASE_CONFIRM_RATIO      = 0.70
LEARNING_SAVE_INTERVAL_S = 120

# Cross-validatie
CROSSVAL_MIN_VOTES = 20
CROSSVAL_MIN_RATIO = 0.50

# Nieuwe-panelen-detectie
NEW_PANEL_RATIO         = 1.20
NEW_PANEL_CONFIRM_COUNT = 3

# 3-fase detectie (v1.5.0)
# Alle drie fasen moeten stijgen bij een PV-sprong. De kleinste delta mag niet
# minder dan dit aandeel van de grootste delta zijn (symmetriecheck).
THREE_PHASE_BALANCE_RATIO  = 0.35   # kleinste / grootste ≥ 0.35 → 3-fasig
THREE_PHASE_MIN_DETECTIONS = 4      # aantal bevestigingen voor definitief "3F"
THREE_PHASE_LABEL          = "3F"   # label dat in sensor/dashboard verschijnt


@dataclass
class PhaseVotes:
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

    def best_guess(self) -> tuple[str | None, float]:
        total = self.total()
        if total == 0:
            return None, 0.0
        best = max(("L1", "L2", "L3"), key=lambda p: getattr(self, p))
        return best, round(getattr(self, best) / total * 100, 1)

    def to_dict(self) -> dict:
        return {"L1": self.L1, "L2": self.L2, "L3": self.L3}


@dataclass
class InverterProfile:
    inverter_id: str
    label: str
    peak_power_w: float      = 0.0
    peak_power_w_7d: float   = 0.0
    peak_power_w_7d_ts: str  = ""
    estimated_wp: float      = 0.0
    samples: int             = 0
    last_updated: str        = ""
    confident: bool          = False
    detected_phase: str | None  = None   # "L1" / "L2" / "L3" / "3F" / None
    phase_certain: bool         = False
    phase_votes: dict           = field(default_factory=dict)
    is_three_phase: bool        = False  # True wanneer 3F bevestigd (v1.5.0)
    three_phase_votes: int      = 0      # teller 3F-stemmen (v1.5.0)
    hourly_peak_w: dict         = field(default_factory=dict)
    # Cross-validatie — persistent
    phase_post_votes: dict      = field(default_factory=dict)
    phase_relearn_events: int   = 0
    phase_conflict_pct: float   = 0.0
    # Nieuwe panelen — persistent
    new_panel_resets: int       = 0
    # Runtime
    _prev_power_w: float        = field(default=0.0, repr=False, compare=False)
    _prev_phase_currents: dict  = field(default_factory=dict, repr=False, compare=False)
    _votes_obj: Any             = field(default=None, repr=False, compare=False)
    _post_votes_obj: Any        = field(default=None, repr=False, compare=False)
    _new_panel_streak: int      = field(default=0, repr=False, compare=False)


class SolarPowerLearner:

    def __init__(self, hass: HomeAssistant, inverter_configs: list[dict]) -> None:
        self.hass = hass
        self._configs = inverter_configs
        self._profiles: dict[str, InverterProfile] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._dirty = False
        self._last_save = 0.0
        self._backup: Optional[Any] = None

    async def async_setup(self, backup: Optional[Any] = None) -> None:
        self._backup = backup
        saved: dict = await self._store.async_load() or {}

        if not saved and backup is not None:
            fallback = await backup.async_read(BACKUP_KEY)
            if fallback:
                saved = fallback
                _LOGGER.warning(
                    "SolarLearner: HA Store leeg — data hersteld uit backup (%d omvormers)",
                    len(saved),
                )

        for cfg in self._configs:
            eid   = cfg["entity_id"]
            label = cfg.get("label", eid)
            d     = saved.get(eid, {})

            votes_d = d.get("phase_votes", {})
            post_d  = d.get("phase_post_votes", {})

            profile = InverterProfile(
                inverter_id=eid,
                label=d.get("label", label),
                peak_power_w=float(d.get("peak_power_w", 0)),
                peak_power_w_7d=float(d.get("peak_power_w_7d", 0)),
                peak_power_w_7d_ts=d.get("peak_power_w_7d_ts", ""),
                estimated_wp=float(d.get("estimated_wp", 0)),
                samples=int(d.get("samples", 0)),
                last_updated=d.get("last_updated", ""),
                confident=bool(d.get("confident", False)),
                detected_phase=d.get("detected_phase"),
                phase_certain=bool(d.get("phase_certain", False)),
                phase_votes=votes_d,
                is_three_phase=bool(d.get("is_three_phase", False)),
                three_phase_votes=int(d.get("three_phase_votes", 0)),
                hourly_peak_w=d.get("hourly_peak_w", {}),
                phase_post_votes=post_d,
                phase_relearn_events=int(d.get("phase_relearn_events", 0)),
                phase_conflict_pct=float(d.get("phase_conflict_pct", 0.0)),
                new_panel_resets=int(d.get("new_panel_resets", 0)),
                _votes_obj=PhaseVotes(
                    L1=votes_d.get("L1", 0), L2=votes_d.get("L2", 0), L3=votes_d.get("L3", 0)
                ),
                _post_votes_obj=PhaseVotes(
                    L1=post_d.get("L1", 0), L2=post_d.get("L2", 0), L3=post_d.get("L3", 0)
                ),
            )
            self._profiles[eid] = profile

            if d:
                _LOGGER.info(
                    "SolarLearner: '%s' geladen — piek %.0fW | fase: %s%s | "
                    "fase-herstarts: %d | piek-resets: %d | conflict: %.0f%%",
                    label, profile.peak_power_w,
                    profile.detected_phase or "onbekend",
                    " (zeker)" if profile.phase_certain else "",
                    profile.phase_relearn_events,
                    profile.new_panel_resets,
                    profile.phase_conflict_pct,
                )
            else:
                _LOGGER.info("SolarLearner: nieuw profiel '%s'", label)

    async def async_update(self, phase_currents: dict[str, float] | None = None) -> None:
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

            if power_w >= IRRADIANCE_MIN_W:
                changed = False

                # ── Nieuwe-panelen-detectie ────────────────────────────────
                if profile.peak_power_w > 0 and power_w > profile.peak_power_w * NEW_PANEL_RATIO:
                    profile._new_panel_streak += 1
                    if profile._new_panel_streak >= NEW_PANEL_CONFIRM_COUNT:
                        _LOGGER.warning(
                            "SolarLearner '%s': 🔄 NIEUWE PANELEN GEDETECTEERD — "
                            "%.0fW is %.0f%% boven geleerd piek %.0fW. "
                            "Piekvermogen gereset. Reset #%d.",
                            profile.label, power_w,
                            (power_w / profile.peak_power_w - 1) * 100,
                            profile.peak_power_w,
                            profile.new_panel_resets + 1,
                        )
                        profile.peak_power_w      = 0.0
                        profile.peak_power_w_7d   = 0.0
                        profile.hourly_peak_w     = {}
                        profile.samples           = 0
                        profile.confident         = False
                        profile.new_panel_resets += 1
                        profile._new_panel_streak = 0
                        changed = True
                else:
                    profile._new_panel_streak = 0

                if power_w > profile.peak_power_w:
                    _LOGGER.info(
                        "SolarLearner '%s': nieuw piek %.0fW (was %.0fW)",
                        profile.label, power_w, profile.peak_power_w,
                    )
                    profile.peak_power_w = round(power_w, 1)
                    changed = True

                if power_w > profile.peak_power_w_7d:
                    profile.peak_power_w_7d    = round(power_w, 1)
                    profile.peak_power_w_7d_ts = now.isoformat()
                    changed = True
                else:
                    if profile.peak_power_w_7d_ts:
                        try:
                            ts = datetime.fromisoformat(profile.peak_power_w_7d_ts)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if (now - ts) > timedelta(days=7):
                                profile.peak_power_w_7d    = round(power_w, 1)
                                profile.peak_power_w_7d_ts = now.isoformat()
                                changed = True
                        except (ValueError, TypeError):
                            profile.peak_power_w_7d_ts = now.isoformat()

                if power_w > profile.hourly_peak_w.get(hour_key, 0.0):
                    profile.hourly_peak_w[hour_key] = round(power_w, 1)
                    changed = True

                profile.samples      += 1
                profile.last_updated  = now.isoformat()
                profile.confident     = profile.samples >= 5
                profile.estimated_wp  = round(profile.peak_power_w / 0.87)

                if changed:
                    self._dirty = True

            # ── Fase-detectie of cross-validatie ──────────────────────────
            if phase_currents and len(phase_currents) >= 2:
                if not profile.phase_certain:
                    await self._detect_phase(profile, power_w, phase_currents)
                else:
                    await self._crossval_phase(profile, power_w, phase_currents)

            profile._prev_power_w        = power_w
            profile._prev_phase_currents = dict(phase_currents or {})

        if self._dirty and (time.time() - self._last_save) >= LEARNING_SAVE_INTERVAL_S:
            await self._async_save()

    # ── Fase-detectie ─────────────────────────────────────────────────────────

    @staticmethod
    def _calc_deltas(phase_currents: dict, prev: dict) -> dict:
        return {ph: cur - prev.get(ph, cur) for ph, cur in phase_currents.items()}

    async def _detect_phase(self, profile: InverterProfile, power_w: float, phase_currents: dict) -> None:
        prev_power  = profile._prev_power_w
        prev_phases = profile._prev_phase_currents
        if not prev_phases or power_w < IRRADIANCE_MIN_W:
            return
        power_delta = power_w - prev_power
        if power_delta < MIN_POWER_DELTA_W:
            return

        deltas  = self._calc_deltas(phase_currents, prev_phases)
        phases_available = [p for p in ("L1", "L2", "L3") if p in deltas]

        # ── 3-fase check (v1.5.0) ─────────────────────────────────────────────
        # Alle drie fasen moeten positief en relatief symmetrisch stijgen.
        if len(phases_available) == 3:
            pos_deltas = {p: deltas[p] for p in phases_available if deltas[p] > 0}
            if len(pos_deltas) == 3:
                max_d = max(pos_deltas.values())
                min_d = min(pos_deltas.values())
                min_abs_threshold = max(0.2, power_delta / 350.0)
                if min_d >= min_abs_threshold and (min_d / max_d) >= THREE_PHASE_BALANCE_RATIO:
                    profile.three_phase_votes += 1
                    self._dirty = True
                    _LOGGER.info(
                        "SolarLearner '%s': 3F-stem %d/%d — deltas L1=%.2f L2=%.2f L3=%.2f "
                        "(sym=%.0f%%) ΔPV=+%.0fW",
                        profile.label,
                        profile.three_phase_votes, THREE_PHASE_MIN_DETECTIONS,
                        deltas["L1"], deltas["L2"], deltas["L3"],
                        (min_d / max_d) * 100, power_delta,
                    )
                    if profile.three_phase_votes >= THREE_PHASE_MIN_DETECTIONS:
                        _LOGGER.info(
                            "SolarLearner '%s': ✅ 3-FASIG BEVESTIGD na %d metingen",
                            profile.label, profile.three_phase_votes,
                        )
                        profile.detected_phase  = THREE_PHASE_LABEL
                        profile.phase_certain   = True
                        profile.is_three_phase  = True
                        profile._post_votes_obj = PhaseVotes()
                        profile.phase_post_votes = {}
                        profile.phase_conflict_pct = 0.0
                        self._dirty = True
                    return  # sowieso niet verder als single-fase stem

        # ── Enkelfase check (bestaande logica) ────────────────────────────────
        winner  = max(deltas, key=lambda p: deltas[p])
        if deltas[winner] < max(0.3, power_delta / 250.0):
            return

        votes: PhaseVotes = profile._votes_obj or PhaseVotes()
        votes.add(winner)
        profile.phase_votes = votes.to_dict()
        profile._votes_obj  = votes

        bar = '#' * votes.total() + '.' * max(0, MIN_PHASE_DETECTIONS - votes.total())
        _LOGGER.info(
            "SolarLearner '%s': fase-stem %d/%d [%s] — %s wint ΔPV=+%.0fW | stemmen: %s",
            profile.label, votes.total(), MIN_PHASE_DETECTIONS, bar,
            winner, power_delta, votes.to_dict(),
        )

        if votes.total() >= MIN_PHASE_DETECTIONS:
            candidate = votes.winner(PHASE_CONFIRM_RATIO)
            if candidate and candidate != profile.detected_phase:
                _LOGGER.info(
                    "SolarLearner '%s': ✅ fase BEVESTIGD → %s (na %d metingen, %.0f%%)",
                    profile.label, candidate, votes.total(),
                    getattr(votes, candidate) / votes.total() * 100,
                )
                profile.detected_phase   = candidate
                profile.phase_certain    = True
                profile.is_three_phase   = False
                profile._post_votes_obj  = PhaseVotes()
                profile.phase_post_votes = {}
                profile.phase_conflict_pct = 0.0
                self._dirty = True
            elif not candidate and votes.total() >= MIN_PHASE_DETECTIONS * 2:
                _LOGGER.warning(
                    "SolarLearner '%s': fase onduidelijk na %d metingen (noisy sensor?)",
                    profile.label, votes.total(),
                )
                profile.detected_phase = None
                profile.phase_certain  = True
                self._dirty = True

    # ── Cross-validatie ───────────────────────────────────────────────────────

    async def _crossval_phase(self, profile: InverterProfile, power_w: float, phase_currents: dict) -> None:
        if profile.detected_phase is None:
            return
        prev_power  = profile._prev_power_w
        prev_phases = profile._prev_phase_currents
        if not prev_phases or power_w < IRRADIANCE_MIN_W:
            return
        power_delta = power_w - prev_power
        if power_delta < MIN_POWER_DELTA_W:
            return

        deltas = self._calc_deltas(phase_currents, prev_phases)

        # ── 3F cross-validatie: blijven alle drie fasen symmetrisch? ──────────
        if profile.is_three_phase:
            phases_available = [p for p in ("L1", "L2", "L3") if p in deltas]
            if len(phases_available) == 3:
                pos_deltas = {p: deltas[p] for p in phases_available if deltas[p] > 0}
                min_abs_threshold = max(0.2, power_delta / 350.0)
                if len(pos_deltas) == 3:
                    max_d = max(pos_deltas.values())
                    min_d = min(pos_deltas.values())
                    sym_ok = min_d >= min_abs_threshold and (min_d / max_d) >= THREE_PHASE_BALANCE_RATIO
                else:
                    sym_ok = False
                post: PhaseVotes = profile._post_votes_obj or PhaseVotes()
                # Misbruik post-votes als symmetrie-teller: L1=ok, L2=conflict
                if sym_ok:
                    post.add("L1")
                else:
                    post.add("L2")
                profile.phase_post_votes = post.to_dict()
                profile._post_votes_obj  = post
                total = post.total()
                ok_votes = post.L1
                conflict_votes = post.L2
                conflict_pct = round(conflict_votes / total * 100, 1) if total > 0 else 0.0
                profile.phase_conflict_pct = conflict_pct
                if total >= CROSSVAL_MIN_VOTES and (ok_votes / total) < CROSSVAL_MIN_RATIO:
                    _LOGGER.warning(
                        "SolarLearner '%s': ⚠️ 3F CONFLICT → herstart. "
                        "Slechts %.0f%% symmetrische metingen (min %.0f%%). Herstart #%d.",
                        profile.label,
                        ok_votes / total * 100, CROSSVAL_MIN_RATIO * 100,
                        profile.phase_relearn_events + 1,
                    )
                    profile.detected_phase       = None
                    profile.phase_certain        = False
                    profile.is_three_phase       = False
                    profile.three_phase_votes    = 0
                    profile.phase_votes          = {}
                    profile.phase_post_votes     = {}
                    profile.phase_conflict_pct   = 0.0
                    profile.phase_relearn_events += 1
                    profile._votes_obj           = PhaseVotes()
                    profile._post_votes_obj      = PhaseVotes()
                    self._dirty = True
            return

        # ── Enkelfase cross-validatie (bestaande logica) ──────────────────────
        winner  = max(deltas, key=lambda p: deltas[p])
        if deltas[winner] < max(0.3, power_delta / 250.0):
            return

        post: PhaseVotes = profile._post_votes_obj or PhaseVotes()
        post.add(winner)
        profile.phase_post_votes = post.to_dict()
        profile._post_votes_obj  = post
        self._dirty = True

        total           = post.total()
        confirmed_votes = getattr(post, profile.detected_phase)
        conflict_pct    = round((1.0 - confirmed_votes / total) * 100, 1) if total > 0 else 0.0
        profile.phase_conflict_pct = conflict_pct

        if total % 10 == 0 and total > 0:
            _LOGGER.info(
                "SolarLearner '%s': cross-validatie — fase %s: %d/%d stemmen "
                "(%.0f%% correct, conflict %.0f%%)",
                profile.label, profile.detected_phase,
                confirmed_votes, total,
                confirmed_votes / total * 100 if total else 0,
                conflict_pct,
            )

        if total < CROSSVAL_MIN_VOTES:
            return

        ratio = confirmed_votes / total
        if ratio < CROSSVAL_MIN_RATIO:
            new_phase, new_conf = post.best_guess()
            _LOGGER.warning(
                "SolarLearner '%s': ⚠️ FASE-CONFLICT → automatische herstart. "
                "Fase %s krijgt slechts %.0f%% (minimum %.0f%%). "
                "Waarschijnlijk echte fase: %s (%.0f%%). Herstart #%d.",
                profile.label,
                profile.detected_phase, ratio * 100, CROSSVAL_MIN_RATIO * 100,
                new_phase or "onbekend", new_conf,
                profile.phase_relearn_events + 1,
            )
            profile.detected_phase       = None
            profile.phase_certain        = False
            profile.phase_votes          = {}
            profile.phase_post_votes     = {}
            profile.phase_conflict_pct   = 0.0
            profile.phase_relearn_events += 1
            profile._votes_obj           = PhaseVotes()
            profile._post_votes_obj      = PhaseVotes()
            self._dirty = True

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_profile(self, inverter_id: str) -> InverterProfile | None:
        return self._profiles.get(inverter_id)

    def get_all_profiles(self) -> list[InverterProfile]:
        return list(self._profiles.values())

    def get_inverters_on_phase(self, phase: str) -> list[InverterProfile]:
        """Geeft omvormers op een bepaalde fase terug.
        Phase kan "L1"/"L2"/"L3" zijn voor enkelfase, of "3F" voor 3-fasige omvormers.
        """
        return [p for p in self._profiles.values() if p.phase_certain and p.detected_phase == phase]

    def get_three_phase_inverters(self) -> list[InverterProfile]:
        """Geeft alle bevestigde 3-fasige omvormers terug (v1.5.0)."""
        return [p for p in self._profiles.values() if p.phase_certain and p.is_three_phase]

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

    def get_phase_conflict_alerts(self) -> list[dict]:
        """Voor de notification engine: omvormers met actief fase-conflict."""
        return [
            {
                "inverter_id":    p.inverter_id,
                "label":          p.label,
                "detected_phase": p.detected_phase,
                "conflict_pct":   p.phase_conflict_pct,
                "post_votes":     p.phase_post_votes,
                "relearn_events": p.phase_relearn_events,
            }
            for p in self._profiles.values()
            if p.phase_certain and p.detected_phase and p.phase_conflict_pct > 30
        ]

    async def async_reset_profile(self, inverter_id: str) -> None:
        if inverter_id in self._profiles:
            label = self._profiles[inverter_id].label
            self._profiles[inverter_id] = InverterProfile(
                inverter_id=inverter_id, label=label,
                _votes_obj=PhaseVotes(), _post_votes_obj=PhaseVotes(),
                is_three_phase=False, three_phase_votes=0,
            )
            await self._async_save()
            _LOGGER.info("SolarLearner: profiel '%s' gereset (incl. 3F-status)", label)

    def to_dict(self) -> dict[str, Any]:
        return {
            eid: {
                "label":               p.label,
                "peak_power_w":        p.peak_power_w,
                "estimated_wp":        p.estimated_wp,
                "samples":             p.samples,
                "confident":           p.confident,
                "detected_phase":      p.detected_phase,
                "phase_certain":       p.phase_certain,
                "phase_votes":         p.phase_votes,
                "phase_post_votes":    p.phase_post_votes,
                "phase_relearn_events": p.phase_relearn_events,
                "phase_conflict_pct":  p.phase_conflict_pct,
                "new_panel_resets":    p.new_panel_resets,
                "is_three_phase":      p.is_three_phase,
                "three_phase_votes":   p.three_phase_votes,
                "last_updated":        p.last_updated,
                **self._phase_display_fields(p),
            }
            for eid, p in self._profiles.items()
        }

    @staticmethod
    def _phase_display_fields(p: "InverterProfile") -> dict:
        votes: PhaseVotes = p._votes_obj or PhaseVotes()
        if p.phase_certain and p.detected_phase:
            conf = max(0.0, round(100.0 - p.phase_conflict_pct, 1))
            return {
                "phase_display":      p.detected_phase,   # "L1"/"L2"/"L3" of "3F"
                "phase_confidence":   conf,
                "phase_provisional":  False,
                "phase_conflict_pct": p.phase_conflict_pct,
                "is_three_phase":     p.is_three_phase,
            }
        # Provisorisch: 3F-stemmen bijhouden voor voorlopige weergave
        if p.three_phase_votes >= 2:
            conf_3f = round(p.three_phase_votes / THREE_PHASE_MIN_DETECTIONS * 100, 1)
            return {
                "phase_display":      "3F",
                "phase_confidence":   min(conf_3f, 99.0),
                "phase_provisional":  True,
                "phase_conflict_pct": 0.0,
                "is_three_phase":     False,  # nog niet bevestigd
            }
        best, conf = votes.best_guess()
        if best and votes.total() >= 2:
            return {
                "phase_display":      best,
                "phase_confidence":   conf,
                "phase_provisional":  True,
                "phase_conflict_pct": 0.0,
                "is_three_phase":     False,
            }
        return {
            "phase_display":      None,
            "phase_confidence":   0.0,
            "phase_provisional":  True,
            "phase_conflict_pct": 0.0,
            "is_three_phase":     False,
        }

    # ── Opslag ────────────────────────────────────────────────────────────────

    def _build_save_data(self) -> dict:
        return {
            eid: {
                "label":               p.label,
                "peak_power_w":        p.peak_power_w,
                "peak_power_w_7d":     p.peak_power_w_7d,
                "peak_power_w_7d_ts":  p.peak_power_w_7d_ts,
                "estimated_wp":        p.estimated_wp,
                "samples":             p.samples,
                "last_updated":        p.last_updated,
                "confident":           p.confident,
                "detected_phase":      p.detected_phase,
                "phase_certain":       p.phase_certain,
                "phase_votes":         p.phase_votes,
                "phase_post_votes":    p.phase_post_votes,
                "phase_relearn_events": p.phase_relearn_events,
                "phase_conflict_pct":  p.phase_conflict_pct,
                "new_panel_resets":    p.new_panel_resets,
                "is_three_phase":      p.is_three_phase,
                "three_phase_votes":   p.three_phase_votes,
                "hourly_peak_w":       p.hourly_peak_w,
            }
            for eid, p in self._profiles.items()
        }

    async def _async_save(self) -> None:
        data = self._build_save_data()
        await self._store.async_save(data)
        self._dirty     = False
        self._last_save = time.time()
        _LOGGER.debug("SolarLearner: %d profielen opgeslagen", len(data))
        if self._backup is not None:
            await self._backup.async_write(BACKUP_KEY, data)
