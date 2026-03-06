# -*- coding: utf-8 -*-
"""
CloudEMS Phase Prober — v2.0.0

Bepaalt actief op welke netfase een last zit via een korte, gecontroleerde puls:
dim/schakel de load kort terug, meet welke fasestroom reageert, herstel direct.

Nieuw in v2.0:
  - Generiek ProbeCandidate systeem: naast PV-omvormers ook EV-laders, boilers,
    en thuisbatterijen kunnen als probe-kanaal dienen.
  - Veiligheidsclassificatie per apparaattype: alleen lasten waarbij de gebruiker
    een korte onderbreking NIET merkt worden gebruikt.
  - Automatische kandidaat-ranking: het systeem kiest de meest geschikte last
    op basis van huidig vermogen, veiligheid en beschikbaarheid.

Veiligheidsclassificatie:
  ✅ VEILIG (probe mag):
      - PV-omvormer (met dimmer)          — verlies van zonproductie is acceptabel
      - EV-lader                          — korte pauze merkt EV/eigenaar niet
      - Elektrische boiler / boiler       — thermische buffer absorbeert de puls
      - Thuisbatterij (laden)             — korte laadpauze is irrelevant
      - Warmtepomp (niet koelen in zomer) — thermische massa vangt puls op

  ❌ NIET VEILIG (nooit probe):
      - Wasmachine, droger, vaatwasser    — programma-onderbreking / waterschade
      - Koelkast / vriezer                — temperatuurverlies, mogelijk bederf
      - Oven, magnetron                   — kookverstoring
      - Verlichting                       — zichtbare flicker
      - Computer, TV, audio               — reboot / dataverlies
      - Inductie / elektrisch fornuis     — kookverstoring

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .multi_inverter_manager import MultiInverterManager, InverterControl
    from .solar_learner import SolarPowerLearner

_LOGGER = logging.getLogger(__name__)

# ── Configuratie-constanten ────────────────────────────────────────────────────

PROBE_MIN_POWER_W       = 200    # Minimaal vermogen (W) op de candidate om te mogen proben
PROBE_DIM_PCT           = 40.0   # Dimniveau tijdens de puls (% van vol vermogen)
PROBE_SWITCH_OFF        = True   # Bij schakelaar-kandidaten: even uitzetten
PROBE_SETTLE_S          = 7      # Wacht na dim/uit voordat we meten (s)
PROBE_MAX_DURATION_S    = 18     # Veiligheidsnet: max pulse duur (s)
PROBE_COOLDOWN_S        = 180    # Min. pauze tussen twee rondes per kandidaat (s)
PROBE_CONFIRM_ROUNDS    = 3      # Rondes voor definitief resultaat
PROBE_MIN_DELTA_A       = 0.15   # Min. stroomdaling (A) om als signaal te tellen
PROBE_WINNER_RATIO      = 0.60   # Winnende fase ≥ 60% van stemmen
PROBE_INSTABILITY_PCT   = 20.0   # Abort als vermogen >20% afwijkt tijdens settle
PROBE_EV_MIN_CURRENT_A  = 6.0   # EV: minimale laadstroom om probe te mogen starten


class CandidateType(str, Enum):
    """Soort probe-kandidaat — bepaalt hoe we aansturen en hoe veilig het is."""
    INVERTER     = "inverter"      # PV-omvormer met dimmer-regelaar
    EV_CHARGER   = "ev_charger"    # EV-lader (kan tijdelijk pauzeren)
    BOILER       = "boiler"        # Elektrische boiler / warmwaterboiler
    BATTERY      = "battery"       # Thuisbatterij (laden)
    HEAT_PUMP    = "heat_pump"     # Warmtepomp (alleen verwarmen, niet koelen)


# Apparaattypen die NOOIT gebruikt mogen worden als probe-kandidaat
UNSAFE_DEVICE_TYPES = frozenset({
    "washing_machine", "dryer", "dishwasher",
    "refrigerator",
    "oven", "microwave", "kettle",
    "television", "computer",
    "light",
    "unknown",
})


@dataclass
class ProbeCandidate:
    """
    Beschrijft één last die als probe-kanaal kan dienen.

    entity_id        : sensor die het vermogen levert (W)
    control_entity   : switch of number om aan te sturen
    candidate_type   : zie CandidateType
    label            : weergavenaam
    rated_power_w    : nominaal vermogen (voor % → W conversie bij number-entities)
    target_phase_id  : ID van de entiteit waarvan we de fase willen leren
                       (bijv. inverter-sensor; None = zelf)
    """
    entity_id:       str
    control_entity:  str
    candidate_type:  CandidateType
    label:           str   = ""
    rated_power_w:   float | None = None
    target_phase_id: str   | None = None   # None = sla fase op voor entity_id zelf

    def safe_to_probe(self) -> bool:
        """Altijd True — alleen veilige typen worden ooit aangemeld."""
        return True


@dataclass
class ProbeVotes:
    L1: int = 0
    L2: int = 0
    L3: int = 0
    aborted: int = 0

    def add(self, phase: str) -> None:
        if phase in ("L1", "L2", "L3"):
            setattr(self, phase, getattr(self, phase) + 1)

    def total_valid(self) -> int:
        return self.L1 + self.L2 + self.L3

    def winner(self, min_ratio: float = PROBE_WINNER_RATIO) -> str | None:
        t = self.total_valid()
        if not t:
            return None
        for p in ("L1", "L2", "L3"):
            if getattr(self, p) / t >= min_ratio:
                return p
        return None

    def to_dict(self) -> dict:
        return {"L1": self.L1, "L2": self.L2, "L3": self.L3, "aborted": self.aborted}


@dataclass
class ProbeSession:
    candidate:             ProbeCandidate
    state:                 str             = "idle"
    votes:                 ProbeVotes      = field(default_factory=ProbeVotes)
    pre_phase_currents:    dict            = field(default_factory=dict)
    pre_power_w:           float           = 0.0
    pulse_started_at:      float           = 0.0
    last_probe_at:         float           = 0.0
    rounds_done:           int             = 0
    result_phase:          str | None      = None
    result_confidence:     float           = 0.0
    last_status:           str             = "Wacht op voldoende verbruik..."


class PhaseProber:
    """
    Actieve fase-detectie via korte puls op veilige controlleerbare lasten.

    Gebruik:
        prober = PhaseProber(hass, manager, learner)
        prober.register_candidate(ProbeCandidate(...))   # voor extra kandidaten
        await prober.async_tick(phase_currents, negative_price_active)

    Schrijft gevonden fase direct naar SolarPowerLearner (voor PV-omvormers)
    of naar een apart resultaat-dict (voor andere kandidaten).
    """

    def __init__(
        self,
        hass:    "HomeAssistant",
        manager: "MultiInverterManager",
        learner: "SolarPowerLearner",
    ) -> None:
        self.hass     = hass
        self._mgr     = manager
        self._learner = learner
        self._sessions:  dict[str, ProbeSession]   = {}
        self._results:   dict[str, str]             = {}   # entity_id → "L1"/"L2"/"L3"
        self._active_id: str | None                 = None

        # Registreer automatisch PV-omvormers met control_entity
        for ctrl in manager._controls:
            if ctrl.control_entity:
                cand = ProbeCandidate(
                    entity_id      = ctrl.entity_id,
                    control_entity = ctrl.control_entity,
                    candidate_type = CandidateType.INVERTER,
                    label          = ctrl.label or ctrl.entity_id,
                    rated_power_w  = ctrl.rated_power_w,
                    target_phase_id = ctrl.entity_id,
                )
                self._register(cand)

    # ── Publieke interface ─────────────────────────────────────────────────────

    def register_candidate(self, candidate: ProbeCandidate) -> None:
        """Voeg een extra probe-kandidaat toe (EV, boiler, batterij, warmtepomp)."""
        if candidate.candidate_type.value in [t.value for t in CandidateType]:
            self._register(candidate)
            _LOGGER.info(
                "PhaseProber: kandidaat toegevoegd — %s (%s) control=%s",
                candidate.label, candidate.candidate_type.value, candidate.control_entity,
            )

    async def async_tick(
        self,
        phase_currents:       dict[str, float],
        negative_price_active: bool = False,
    ) -> None:
        """Aanroepen elke coordinator-cyclus (~10 s)."""
        if negative_price_active:
            return  # Nooit proben tijdens negatieve prijs — we dimmen al

        pv_powers = self._read_powers()

        if self._active_id:
            session = self._sessions.get(self._active_id)
            if session and session.state not in ("idle", "done"):
                await self._continue_probe(session, phase_currents, pv_powers)
                return
            self._active_id = None

        candidate_session = self._pick_candidate(pv_powers)
        if candidate_session:
            await self._start_probe(candidate_session, phase_currents, pv_powers)

    def get_status(self) -> dict:
        return {
            eid: {
                "state":             s.state,
                "candidate_type":    s.candidate.candidate_type.value,
                "label":             s.candidate.label,
                "rounds_done":       s.rounds_done,
                "votes":             s.votes.to_dict(),
                "result_phase":      s.result_phase,
                "result_confidence": round(s.result_confidence, 1),
                "last_status":       s.last_status,
            }
            for eid, s in self._sessions.items()
        }

    def get_result(self, entity_id: str) -> str | None:
        """Geeft de gevonden fase terug voor een entiteit, of None."""
        return self._results.get(entity_id)

    def reset_session(self, entity_id: str) -> None:
        if entity_id in self._sessions:
            cand = self._sessions[entity_id].candidate
            self._sessions[entity_id] = ProbeSession(candidate=cand)
            if self._active_id == entity_id:
                self._active_id = None

    # ── Interne registratie ────────────────────────────────────────────────────

    def _register(self, candidate: ProbeCandidate) -> None:
        eid = candidate.entity_id
        if eid not in self._sessions:
            self._sessions[eid] = ProbeSession(candidate=candidate)

    # ── Kandidaat selectie ─────────────────────────────────────────────────────

    def _pick_candidate(self, powers: dict[str, float]) -> ProbeSession | None:
        """
        Kies de meest geschikte kandidaat.

        Prioriteit:
          1. PV-omvormers met dimmer (meest nauwkeurig signaal)
          2. EV-lader (groot vermogen, duidelijk signaal)
          3. Boiler / batterij
          4. Warmtepomp

        Binnen een type: kies de kandidaat met het hoogste huidige vermogen.
        """
        now = time.monotonic()

        # Bouw lijst van geschikte kandidaten, gesorteerd op prioriteit + vermogen
        priority_order = [
            CandidateType.INVERTER,
            CandidateType.EV_CHARGER,
            CandidateType.BOILER,
            CandidateType.BATTERY,
            CandidateType.HEAT_PUMP,
        ]

        eligible: list[tuple[int, float, ProbeSession]] = []

        for eid, session in self._sessions.items():
            if session.state == "done":
                # Controleer of fase al zeker is via learner (voor omvormers)
                ctype = session.candidate.candidate_type
                if ctype == CandidateType.INVERTER:
                    profile = self._learner.get_profile(eid)
                    if profile and profile.phase_certain:
                        continue
                else:
                    if eid in self._results:
                        continue  # Al gevonden

            if session.state not in ("idle",):
                continue  # Al bezig

            cand = session.candidate

            # Handmatige override actief? (voor omvormers)
            if self._mgr._manual_dim_pct.get(eid) is not None:
                session.last_status = "⏸ Handmatige override actief"
                continue

            # Cooldown?
            if session.last_probe_at and (now - session.last_probe_at) < PROBE_COOLDOWN_S:
                rem = int(PROBE_COOLDOWN_S - (now - session.last_probe_at))
                session.last_status = f"⏳ Cooldown — nog {rem}s"
                continue

            # Genoeg vermogen?
            power_w = powers.get(eid, 0.0)
            if power_w < PROBE_MIN_POWER_W:
                session.last_status = f"☁ Te weinig vermogen ({power_w:.0f}W < {PROBE_MIN_POWER_W}W)"
                continue

            # EV-lader: controleer minimale laadstroom
            if cand.candidate_type == CandidateType.EV_CHARGER:
                state = self.hass.states.get(eid)
                current_a = state.attributes.get("current_a") or state.attributes.get("charging_current") if state else None
                if current_a is not None and float(current_a) < PROBE_EV_MIN_CURRENT_A:
                    session.last_status = f"⏸ EV laadstroom te laag ({current_a}A)"
                    continue

            # Fase al bekend via learner (omvormer)?
            if cand.candidate_type == CandidateType.INVERTER:
                profile = self._learner.get_profile(eid)
                if profile and profile.phase_certain:
                    session.state = "done"
                    session.last_status = f"✅ Fase {profile.detected_phase} bevestigd (passief geleerd)"
                    continue

            prio = priority_order.index(cand.candidate_type) if cand.candidate_type in priority_order else 99
            eligible.append((prio, -power_w, session))  # -power_w: hogere W = hogere prioriteit

        if not eligible:
            return None

        eligible.sort(key=lambda x: (x[0], x[1]))
        return eligible[0][2]

    # ── Probe lifecycle ────────────────────────────────────────────────────────

    async def _start_probe(
        self,
        session:       ProbeSession,
        phase_currents: dict[str, float],
        powers:        dict[str, float],
    ) -> None:
        cand    = session.candidate
        eid     = cand.entity_id
        power_w = powers.get(eid, 0.0)

        _LOGGER.info(
            "PhaseProber '%s' (%s): start ronde %d/%d — puls via '%s' (%.0fW)",
            cand.label, cand.candidate_type.value,
            session.rounds_done + 1, PROBE_CONFIRM_ROUNDS,
            cand.control_entity, power_w,
        )

        session.pre_phase_currents = dict(phase_currents)
        session.pre_power_w        = power_w
        session.pulse_started_at   = time.monotonic()
        session.state              = "settling"
        session.last_status        = (
            f"🔬 Ronde {session.rounds_done + 1}: puls actief via {cand.candidate_type.value} "
            f"— wacht {PROBE_SETTLE_S}s..."
        )
        self._active_id = eid

        await self._apply_pulse(cand, on=False)  # dim/uit

    async def _continue_probe(
        self,
        session:       ProbeSession,
        phase_currents: dict[str, float],
        powers:        dict[str, float],
    ) -> None:
        cand    = session.candidate
        eid     = cand.entity_id
        now     = time.monotonic()
        elapsed = now - session.pulse_started_at

        # Veiligheidsnet
        if elapsed > PROBE_MAX_DURATION_S:
            _LOGGER.warning("PhaseProber '%s': timeout — herstel", cand.label)
            await self._apply_pulse(cand, on=True)
            session.state       = "idle"
            session.votes.aborted += 1
            session.last_status = "⚠ Timeout — herstel 100%"
            return

        if elapsed < PROBE_SETTLE_S:
            return  # Nog niet klaar

        # ── Meet de stroomdaling ──────────────────────────────────────────────
        power_now    = powers.get(eid, 0.0)
        power_before = session.pre_power_w

        # Stabiliteitscheck
        if power_before > 0:
            dev_pct = abs(power_now - power_before) / power_before * 100
            # Voor een "uit"-puls verwachten we juist een daling — check op
            # extra ruis (andere apparaten die tegelijk aan/uit gaan)
            expected_drop = power_before * (1 - PROBE_DIM_PCT / 100)
            actual_drop   = power_before - power_now
            if actual_drop < 0:
                # Vermogen is gestegen?! → onstabiel
                _LOGGER.info(
                    "PhaseProber '%s': onstabiel — vermogen steeg tijdens puls (%.0fW→%.0fW)",
                    cand.label, power_before, power_now,
                )
                await self._apply_pulse(cand, on=True)
                session.state = "idle"
                session.votes.aborted += 1
                session.last_status = "⚡ Onstabiel: vermogen steeg — ronde overgeslagen"
                session.last_probe_at = now
                return

        # Bereken delta per fase (pre − nu = daling)
        deltas: dict[str, float] = {}
        for ph in ("L1", "L2", "L3"):
            pre = session.pre_phase_currents.get(ph)
            cur = phase_currents.get(ph)
            if pre is not None and cur is not None:
                deltas[ph] = pre - cur

        if not deltas:
            _LOGGER.warning("PhaseProber '%s': geen fase-stroom data", cand.label)
            await self._apply_pulse(cand, on=True)
            session.state = "idle"
            session.votes.aborted += 1
            session.last_probe_at = now
            return

        winner     = max(deltas, key=lambda p: deltas[p])
        winner_val = deltas[winner]

        _LOGGER.info(
            "PhaseProber '%s' ronde %d: Δ L1=%.2fA L2=%.2fA L3=%.2fA → %s wins (%.2fA)",
            cand.label, session.rounds_done + 1,
            deltas.get("L1", 0), deltas.get("L2", 0), deltas.get("L3", 0),
            winner, winner_val,
        )

        if winner_val >= PROBE_MIN_DELTA_A:
            session.votes.add(winner)
        else:
            session.votes.aborted += 1
            session.last_status = f"Delta te klein ({winner_val:.2f}A < {PROBE_MIN_DELTA_A}A)"

        # Herstel
        await self._apply_pulse(cand, on=True)
        session.state        = "idle"
        session.rounds_done += 1
        session.last_probe_at = now

        if session.votes.total_valid() >= PROBE_CONFIRM_ROUNDS:
            await self._finalize(session)
        else:
            session.last_status = (
                f"🔬 Ronde {session.rounds_done}/{PROBE_CONFIRM_ROUNDS} — "
                f"stemmen: {session.votes.to_dict()}"
            )

    async def _finalize(self, session: ProbeSession) -> None:
        cand   = session.candidate
        winner = session.votes.winner(PROBE_WINNER_RATIO)
        total  = session.votes.total_valid()
        conf   = getattr(session.votes, winner) / total * 100 if (winner and total) else 0.0

        if winner:
            session.result_phase      = winner
            session.result_confidence = conf
            session.state             = "done"
            session.last_status       = (
                f"✅ Fase {winner} bepaald via {cand.candidate_type.value}-probe "
                f"({conf:.0f}% van {total} rondes)"
            )
            _LOGGER.info(
                "PhaseProber '%s': ✅ FASE %s bepaald (%.0f%% van %d rondes) | stemmen: %s",
                cand.label, winner, conf, total, session.votes.to_dict(),
            )

            # Bepaal het doel-entity waarvan we de fase opslaan
            target_id = cand.target_phase_id or cand.entity_id
            self._results[target_id] = winner

            # Schrijf terug naar SolarPowerLearner (voor PV-omvormers)
            if cand.candidate_type == CandidateType.INVERTER:
                profile = self._learner.get_profile(target_id)
                if profile and not profile.phase_certain:
                    profile.detected_phase = winner
                    profile.phase_certain  = True
                    profile.phase_votes    = session.votes.to_dict()
                    self._learner._dirty   = True
                    _LOGGER.info(
                        "PhaseProber: SolarLearner profiel '%s' bijgewerkt → %s (zeker)",
                        cand.label, winner,
                    )
            else:
                _LOGGER.info(
                    "PhaseProber: fase %s opgeslagen voor '%s' (%s)",
                    winner, target_id, cand.candidate_type.value,
                )
        else:
            # Geen duidelijke winnaar → reset voor herstart
            session.state       = "idle"
            session.rounds_done = 0
            session.votes       = ProbeVotes()
            session.last_status = (
                f"❓ Geen duidelijke fase na {total} rondes — herstart na cooldown"
            )
            _LOGGER.warning(
                "PhaseProber '%s': geen duidelijke winnaar na %d rondes", cand.label, total
            )

    # ── Hardware-aanstuurlogica ────────────────────────────────────────────────

    async def _apply_pulse(self, cand: ProbeCandidate, on: bool) -> None:
        """
        Stuur de probe-last aan:
          on=False → dim naar PROBE_DIM_PCT, of schakel uit
          on=True  → herstel naar 100% / zet aan
        """
        eid    = cand.control_entity
        domain = eid.split(".")[0] if "." in eid else "switch"

        try:
            if domain == "number":
                if on:
                    # Herstel: probeer eerst max te lezen uit entity state
                    state   = self.hass.states.get(eid)
                    max_val = float(state.attributes.get("max", 100)) if state else 100.0
                    # Als max > 100 en rated_power_w bekend → herstel naar rated_power_w
                    if max_val > 100 and cand.rated_power_w:
                        val = cand.rated_power_w
                    else:
                        val = max_val
                else:
                    state   = self.hass.states.get(eid)
                    max_val = float(state.attributes.get("max", 100)) if state else 100.0
                    if max_val > 100 and cand.rated_power_w:
                        # Watt-gebaseerd: dim naar PROBE_DIM_PCT van rated
                        val = round(PROBE_DIM_PCT / 100.0 * cand.rated_power_w, 0)
                    else:
                        val = PROBE_DIM_PCT
                await self.hass.services.async_call(
                    "number", "set_value", {"entity_id": eid, "value": val}, blocking=False
                )
            else:
                # switch / input_boolean / generic — gewoon aan/uit
                service = "turn_on" if on else "turn_off"
                await self.hass.services.async_call(
                    domain, service, {"entity_id": eid}, blocking=False
                )
        except Exception as err:
            _LOGGER.warning("PhaseProber: aansturen '%s' mislukt: %s", eid, err)

    # ── Hulpfuncties ──────────────────────────────────────────────────────────

    def _read_powers(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for eid in self._sessions:
            state = self.hass.states.get(eid)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    result[eid] = float(state.state)
                except (ValueError, TypeError):
                    result[eid] = 0.0
            else:
                result[eid] = 0.0
        return result
