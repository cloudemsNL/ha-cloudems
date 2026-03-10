# -*- coding: utf-8 -*-
"""
CloudEMS Appliance HMM — v1.0.0

Generieke Hidden Markov Model engine voor het bijhouden van multi-fase
apparaatruns (wasmachine, droger, vaatwasser) als één coherente sessie.

Probleem dat dit oplost:
────────────────────────
Een wasmachine genereert tijdens één wasprogramma meerdere NILM-events:
  +1900 W  (verwarmen)   → NILMDetector maakt "Washing Machine Heat" aan
  -1900 W  (motor over)  → apparaat gaat "uit"
  +400 W   (motor)       → NILMDetector maakt nieuw apparaat aan
  ...

Zonder HMM: 3–5 losse apparaten, energie per sub-event, geen programmaduur.
Met HMM:    1 sessie "Wasmachine run", correcte kWh, programmatype, duur.

Werking:
────────
Elke ApplianceHMM beheert een toestandsmachine per fase per apparaattype.
Bij een on-event op een fase kijkt de HMM:
  1. Loopt er al een sessie op deze fase voor dit type?
     → Ja: is de nieuwe state een geldige transitie? Zo ja: update sessie.
     → Nee: start een nieuwe sessie.
  2. Negatieve delta die terug naar baseline gaat → sluit sessie.
  3. Sessie-timeout (max programma-duur) → automatisch sluiten.

State-transities zijn predefined per apparaattype maar de *duur* van elke
state wordt online geleerd (exponentieel voortschrijdend gemiddelde).
Hierdoor past de HMM zich aan het specifieke apparaat van de gebruiker aan.

Geen sklearn, geen numpy — puur Python voor minimale HA-footprint.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
SESSION_IDLE_TIMEOUT_S  = 300.0   # 5 min zonder activiteit → sessie sluiten
POWER_MATCH_TOLERANCE   = 0.45    # ±45% — ruim voor variabele-snelheid apparaten
EMA_ALPHA               = 0.20    # gewicht voor online duratie-leren (snelheid)
MIN_SESSION_DURATION_S  = 30.0    # minimale sessieduur om op te slaan
MAX_SESSION_DURATION_S  = 36_000  # 10 uur — absolute ceiling


# ── State definitie ───────────────────────────────────────────────────────────

@dataclass
class HMMState:
    """Één toestand in de toestandsmachine van een apparaat."""
    name:           str
    power_min_w:    float           # minimaal vermogen in deze state (0 = idle/transitie)
    power_max_w:    float           # maximaal vermogen
    typical_s:      float           # typische duur (wordt online bijgesteld)
    max_s:          float           # harde bovengrens voor deze state
    is_idle:        bool = False    # True = apparaat is feitelijk uit (wacht op start)
    can_start:      bool = False    # True = dit is een geldige startstate
    transitions_to: List[str] = field(default_factory=list)  # toegestane opvolgers

    def power_matches(self, power_w: float) -> bool:
        """Controleer of een vermogen bij deze state past."""
        if self.is_idle:
            return power_w < 30.0
        if self.power_max_w <= 0:
            return False
        tol = max(self.power_min_w * POWER_MATCH_TOLERANCE, 80.0)
        return (self.power_min_w - tol) <= power_w <= (self.power_max_w + tol)

    def update_typical_s(self, observed_s: float) -> None:
        """Pas typische duur aan op basis van observatie (online EMA)."""
        self.typical_s = round(
            EMA_ALPHA * observed_s + (1 - EMA_ALPHA) * self.typical_s, 1
        )


# ── Sessie ────────────────────────────────────────────────────────────────────

@dataclass
class ApplianceSession:
    """Één run van een multi-fase apparaat."""
    device_type:    str
    phase:          str
    start_ts:       float
    current_state:  str
    state_enter_ts: float

    events:         List[dict] = field(default_factory=list)   # ruwe sub-events
    total_kwh:      float = 0.0
    program_type:   str   = "unknown"   # bijv. "eco", "intensive", "normal"
    end_ts:         float = 0.0
    is_closed:      bool  = False

    # Runtime vermogenstracking
    last_power_w:   float = 0.0
    last_tick_ts:   float = field(default_factory=time.time)

    def tick_energy(self, power_w: float, ts: float) -> None:
        """Verbruik bijhouden terwijl sessie loopt."""
        if self.last_tick_ts > 0 and power_w > 0:
            dt_h = (ts - self.last_tick_ts) / 3600.0
            self.total_kwh = round(self.total_kwh + power_w / 1000.0 * dt_h, 4)
        self.last_power_w = power_w
        self.last_tick_ts = ts

    @property
    def duration_s(self) -> float:
        end = self.end_ts if self.is_closed else time.time()
        return end - self.start_ts

    def to_dict(self) -> dict:
        return {
            "device_type":  self.device_type,
            "phase":        self.phase,
            "start_ts":     self.start_ts,
            "end_ts":       self.end_ts,
            "duration_s":   round(self.duration_s, 0),
            "total_kwh":    self.total_kwh,
            "current_state": self.current_state,
            "program_type": self.program_type,
            "event_count":  len(self.events),
            "is_closed":    self.is_closed,
            "last_power_w": self.last_power_w,
        }


# ── State machine definities ──────────────────────────────────────────────────

def _washing_machine_states() -> Dict[str, HMMState]:
    """
    Wasmachine toestandsmachine.
    Vermogensbereiken gebaseerd op UK-DALE + ECO + REDD datasets.
    """
    return {
        "idle": HMMState(
            name="idle", power_min_w=0, power_max_w=30,
            typical_s=0, max_s=0, is_idle=True,
            transitions_to=["heating", "motor_wash"],
        ),
        "heating": HMMState(
            name="heating", power_min_w=900, power_max_w=2800,
            typical_s=900, max_s=3600, can_start=True,
            transitions_to=["motor_wash", "rinse", "idle"],
        ),
        "motor_wash": HMMState(
            name="motor_wash", power_min_w=200, power_max_w=800,
            typical_s=600, max_s=3000, can_start=True,
            transitions_to=["heating", "rinse", "spin", "idle"],
        ),
        "rinse": HMMState(
            name="rinse", power_min_w=200, power_max_w=700,
            typical_s=480, max_s=1800,
            transitions_to=["motor_wash", "spin", "idle"],
        ),
        "spin": HMMState(
            name="spin", power_min_w=200, power_max_w=600,
            typical_s=360, max_s=900,
            transitions_to=["idle"],
        ),
    }


def _dryer_states() -> Dict[str, HMMState]:
    """
    Droger toestandsmachine.
    Condensatiedroger: 2000–2500 W heatup, dan cycling.
    Warmtepomp-droger: 800–1200 W stabiel.
    """
    return {
        "idle": HMMState(
            name="idle", power_min_w=0, power_max_w=30,
            typical_s=0, max_s=0, is_idle=True,
            transitions_to=["heat_up"],
        ),
        "heat_up": HMMState(
            name="heat_up", power_min_w=600, power_max_w=2800,
            typical_s=600, max_s=3000, can_start=True,
            transitions_to=["drying", "cool_down", "idle"],
        ),
        "drying": HMMState(
            name="drying", power_min_w=400, power_max_w=2600,
            typical_s=2700, max_s=7200,
            transitions_to=["cool_down", "heat_up", "idle"],
        ),
        "cool_down": HMMState(
            name="cool_down", power_min_w=80, power_max_w=600,
            typical_s=480, max_s=1200,
            transitions_to=["idle"],
        ),
    }


def _dishwasher_states() -> Dict[str, HMMState]:
    """
    Vaatwasser toestandsmachine.
    """
    return {
        "idle": HMMState(
            name="idle", power_min_w=0, power_max_w=30,
            typical_s=0, max_s=0, is_idle=True,
            transitions_to=["pre_wash", "wash"],
        ),
        "pre_wash": HMMState(
            name="pre_wash", power_min_w=100, power_max_w=500,
            typical_s=300, max_s=1200, can_start=True,
            transitions_to=["wash", "idle"],
        ),
        "wash": HMMState(
            name="wash", power_min_w=800, power_max_w=2500,
            typical_s=1200, max_s=4500, can_start=True,
            transitions_to=["rinse", "drying", "idle"],
        ),
        "rinse": HMMState(
            name="rinse", power_min_w=800, power_max_w=2200,
            typical_s=600, max_s=2400,
            transitions_to=["drying", "wash", "idle"],
        ),
        "drying": HMMState(
            name="drying", power_min_w=200, power_max_w=1000,
            typical_s=900, max_s=3600,
            transitions_to=["idle"],
        ),
    }


# Registratie van alle bekende apparaattypen
APPLIANCE_STATE_MACHINES: Dict[str, callable] = {
    "washing_machine": _washing_machine_states,
    "dryer":           _dryer_states,
    "dishwasher":      _dishwasher_states,
}

# Mensleesbare state-labels per taal
STATE_LABELS_NL: Dict[str, Dict[str, str]] = {
    "washing_machine": {
        "idle":       "stand-by",
        "heating":    "verwarmen",
        "motor_wash": "wassen",
        "rinse":      "spoelen",
        "spin":       "centrifugeren",
    },
    "dryer": {
        "idle":      "stand-by",
        "heat_up":   "opwarmen",
        "drying":    "drogen",
        "cool_down": "afkoelen",
    },
    "dishwasher": {
        "idle":      "stand-by",
        "pre_wash":  "voorspoelen",
        "wash":      "wassen",
        "rinse":     "naspoelen",
        "drying":    "drogen",
    },
}


# ── Per-fase sessietracker ─────────────────────────────────────────────────────

class ApplianceHMM:
    """
    Generieke HMM voor één apparaattype.

    Eén instantie per apparaattype. Sessies worden per fase bijgehouden,
    zodat een wasmachine op L2 en een droger op L3 onafhankelijk tracked worden.

    Gebruik:
        hmm = ApplianceHMM("washing_machine")
        result = hmm.process_event(phase="L2", power_w=1950, ts=time.time())
        if result:
            print(result)  # {"action": "started"|"updated"|"closed", "session": ...}
    """

    def __init__(self, device_type: str) -> None:
        if device_type not in APPLIANCE_STATE_MACHINES:
            raise ValueError(f"Onbekend apparaattype voor HMM: {device_type}")
        self.device_type = device_type
        # States zijn gedeeld over alle fasen (duurleren is type-breed)
        self._states: Dict[str, HMMState] = APPLIANCE_STATE_MACHINES[device_type]()
        # Lopende sessies per fase
        self._sessions: Dict[str, ApplianceSession] = {}
        # Afgesloten sessies (ring buffer, max 20)
        self._history: List[ApplianceSession] = []
        self._stats = dict(
            sessions_started=0, sessions_closed=0,
            sessions_timeout=0, events_processed=0,
        )

    # ── Publieke API ──────────────────────────────────────────────────────────

    def process_event(
        self,
        phase: str,
        power_w: float,
        delta_w: float,
        ts: float,
    ) -> Optional[dict]:
        """
        Verwerk een NILM-event en retourneer een actie-dict of None.

        Args:
            phase:   "L1", "L2" of "L3"
            power_w: absoluut vermogen van het event (altijd positief)
            delta_w: signed delta (positief = aan, negatief = uit)
            ts:      unix timestamp

        Returns:
            {"action": "started"|"updated"|"closed"|"timeout", "session": dict}
            of None als het event niet relevant is voor dit apparaat.
        """
        self._stats["events_processed"] += 1
        self._expire_timeouts(ts)

        is_on = delta_w > 0

        # ── Off-event: sluit lopende sessie ───────────────────────────────────
        if not is_on:
            session = self._sessions.get(phase)
            if session and not session.is_closed:
                return self._close_session(phase, ts, reason="off_event")
            return None

        # ── On-event ──────────────────────────────────────────────────────────
        session = self._sessions.get(phase)

        if session and not session.is_closed:
            # Probeer transitie binnen lopende sessie
            result = self._try_transition(session, power_w, ts)
            if result:
                return result
            # Geen geldige transitie — sluit lopende sessie en start nieuwe
            self._close_session(phase, ts, reason="state_mismatch")

        # Start nieuwe sessie als vermogen bij een startstate past
        start_state = self._find_start_state(power_w)
        if start_state:
            return self._start_session(phase, power_w, start_state, ts)

        return None

    def tick(self, phase: str, power_w: float, ts: float) -> None:
        """
        Roep elke updatecyclus aan voor energieboekhouding en timeout-detectie.
        Geen actie als er geen lopende sessie is op deze fase.
        """
        session = self._sessions.get(phase)
        if session and not session.is_closed:
            session.tick_energy(power_w, ts)

    def get_active_session(self, phase: str) -> Optional[dict]:
        """Geef de lopende sessie op deze fase terug als dict."""
        s = self._sessions.get(phase)
        if s and not s.is_closed:
            return s.to_dict()
        return None

    def get_all_active_sessions(self) -> List[dict]:
        """Geef alle lopende sessies terug (over alle fasen)."""
        return [
            s.to_dict()
            for s in self._sessions.values()
            if not s.is_closed
        ]

    def get_recent_history(self, n: int = 10) -> List[dict]:
        """Geef de laatste n afgesloten sessies."""
        return [s.to_dict() for s in self._history[-n:]]

    def get_state_label(self, state_name: str, lang: str = "nl") -> str:
        labels = STATE_LABELS_NL.get(self.device_type, {})
        return labels.get(state_name, state_name)

    def get_diagnostics(self) -> dict:
        return {
            "device_type":       self.device_type,
            "active_sessions":   len([s for s in self._sessions.values() if not s.is_closed]),
            "history_count":     len(self._history),
            "states":            {
                name: {
                    "typical_s": st.typical_s,
                    "power_range": f"{st.power_min_w}–{st.power_max_w} W",
                }
                for name, st in self._states.items()
                if not st.is_idle
            },
            "stats": dict(self._stats),
        }

    # ── Interne logica ────────────────────────────────────────────────────────

    def _find_start_state(self, power_w: float) -> Optional[str]:
        """Zoek de beste startstate voor dit vermogen."""
        best: Optional[str] = None
        best_dist = float("inf")
        for name, state in self._states.items():
            if not state.can_start:
                continue
            if state.power_matches(power_w):
                mid = (state.power_min_w + state.power_max_w) / 2
                dist = abs(power_w - mid)
                if dist < best_dist:
                    best_dist = dist
                    best = name
        return best

    def _try_transition(
        self, session: ApplianceSession, power_w: float, ts: float
    ) -> Optional[dict]:
        """
        Probeer de sessie naar een nieuwe state te brengen.
        Geeft actie-dict terug bij succes, None als er geen geldige transitie is.
        """
        current = self._states.get(session.current_state)
        if not current:
            return None

        # Controleer of huidig vermogen nog steeds bij huidige state past
        if current.power_matches(power_w):
            # Zelfde state, gewoon update
            session.events.append({"ts": ts, "power_w": power_w, "state": session.current_state})
            session.last_power_w = power_w
            return {
                "action":  "updated",
                "session": session.to_dict(),
                "state":   session.current_state,
            }

        # Zoek beste opvolger-state
        best_next: Optional[str] = None
        best_dist = float("inf")
        for next_name in current.transitions_to:
            next_state = self._states.get(next_name)
            if next_state and not next_state.is_idle and next_state.power_matches(power_w):
                mid = (next_state.power_min_w + next_state.power_max_w) / 2
                dist = abs(power_w - mid)
                if dist < best_dist:
                    best_dist  = dist
                    best_next  = next_name

        if best_next is None:
            return None  # Geen geldige transitie

        # ── State-transitie uitvoeren ─────────────────────────────────────────
        prev_state = session.current_state
        state_duration = ts - session.state_enter_ts
        # Online duratie-leren voor de vorige state
        if state_duration > 5:
            self._states[prev_state].update_typical_s(state_duration)

        session.current_state  = best_next
        session.state_enter_ts = ts
        session.events.append({"ts": ts, "power_w": power_w, "state": best_next})
        session.last_power_w   = power_w

        _LOGGER.debug(
            "HMM %s fase %s: %s → %s (%.0fW, duur vorige state %.0fs)",
            self.device_type, session.phase,
            prev_state, best_next, power_w, state_duration,
        )
        return {
            "action":     "state_changed",
            "session":    session.to_dict(),
            "prev_state": prev_state,
            "state":      best_next,
        }

    def _start_session(
        self, phase: str, power_w: float, start_state: str, ts: float
    ) -> dict:
        session = ApplianceSession(
            device_type    = self.device_type,
            phase          = phase,
            start_ts       = ts,
            current_state  = start_state,
            state_enter_ts = ts,
            last_power_w   = power_w,
            last_tick_ts   = ts,
        )
        session.events.append({"ts": ts, "power_w": power_w, "state": start_state})
        self._sessions[phase] = session
        self._stats["sessions_started"] += 1
        _LOGGER.info(
            "HMM %s: nieuwe sessie gestart op fase %s (state=%s, %.0fW)",
            self.device_type, phase, start_state, power_w,
        )
        return {"action": "started", "session": session.to_dict(), "state": start_state}

    def _close_session(self, phase: str, ts: float, reason: str = "off_event") -> Optional[dict]:
        session = self._sessions.get(phase)
        if not session or session.is_closed:
            return None

        session.end_ts    = ts
        session.is_closed = True

        # Leer duur van laatste state
        state_duration = ts - session.state_enter_ts
        if state_duration > 5:
            self._states[session.current_state].update_typical_s(state_duration)

        # Bepaal programmatype op basis van totaal vermogen
        session.program_type = self._classify_program(session)

        if session.duration_s >= MIN_SESSION_DURATION_S:
            self._history.append(session)
            if len(self._history) > 20:
                self._history.pop(0)
            self._stats["sessions_closed"] += 1
            if reason == "timeout":
                self._stats["sessions_timeout"] += 1
            _LOGGER.info(
                "HMM %s: sessie gesloten op fase %s — %s, duur=%.0fmin, "
                "kWh=%.3f, reden=%s",
                self.device_type, phase, session.program_type,
                session.duration_s / 60, session.total_kwh, reason,
            )

        del self._sessions[phase]
        return {"action": "closed", "session": session.to_dict(), "reason": reason}

    def _expire_timeouts(self, ts: float) -> None:
        """Sluit sessies die te lang inactief zijn."""
        for phase in list(self._sessions.keys()):
            session = self._sessions[phase]
            if session.is_closed:
                continue
            idle_s = ts - (session.last_tick_ts or session.start_ts)
            total_s = ts - session.start_ts
            if idle_s > SESSION_IDLE_TIMEOUT_S or total_s > MAX_SESSION_DURATION_S:
                _LOGGER.debug(
                    "HMM %s: sessie timeout fase %s (idle=%.0fs, totaal=%.0fs)",
                    self.device_type, phase, idle_s, total_s,
                )
                self._close_session(phase, ts, reason="timeout")

    def _classify_program(self, session: ApplianceSession) -> str:
        """Schat programmatype op basis van verbruik en duur."""
        kwh = session.total_kwh
        dur_min = session.duration_s / 60

        if self.device_type == "washing_machine":
            if kwh < 0.20:   return "eco_koud"
            if kwh < 0.50:   return "eco_30"
            if kwh < 0.90:   return "normaal_40"
            if kwh < 1.50:   return "normaal_60"
            return "intensief_90"

        if self.device_type == "dryer":
            if dur_min < 40:  return "quick_dry"
            if dur_min < 75:  return "normaal"
            return "intensief"

        if self.device_type == "dishwasher":
            if kwh < 0.50:   return "eco"
            if kwh < 1.00:   return "normaal"
            return "intensief"

        return "unknown"


# ── ApplianceHMMManager ───────────────────────────────────────────────────────

class ApplianceHMMManager:
    """
    Beheert alle HMM-instanties en koppelt ze aan de NILMDetector.

    Setup in NILMDetector.__init__():
        self._hmm = ApplianceHMMManager()

    Gebruik in NILMDetector._handle_match():
        result = self._hmm.on_nilm_event(
            device_type=best["device_type"],
            phase=event.phase,
            power_w=abs(event.delta_power),
            delta_w=event.delta_power,
            ts=event.timestamp,
        )

    Tick in NILMDetector.update_power() (elke cyclus):
        self._hmm.tick(phase, power_watt, timestamp)
    """

    def __init__(self) -> None:
        self._hmms: Dict[str, ApplianceHMM] = {
            dt: ApplianceHMM(dt)
            for dt in APPLIANCE_STATE_MACHINES
        }

    def on_nilm_event(
        self,
        device_type: str,
        phase: str,
        power_w: float,
        delta_w: float,
        ts: float,
    ) -> Optional[dict]:
        """
        Stuur een NILM-event naar de juiste HMM.
        Geeft actie-dict terug of None als dit type niet tracked wordt.
        """
        hmm = self._hmms.get(device_type)
        if hmm is None:
            return None
        try:
            return hmm.process_event(phase=phase, power_w=power_w,
                                     delta_w=delta_w, ts=ts)
        except Exception as exc:
            _LOGGER.debug("HMM fout voor %s: %s", device_type, exc)
            return None

    def tick(self, phase: str, power_w: float, ts: float) -> None:
        """Energie bijhouden voor alle actieve sessies op deze fase."""
        for hmm in self._hmms.values():
            try:
                hmm.tick(phase, power_w, ts)
            except Exception:
                pass

    def get_active_sessions(self) -> List[dict]:
        """Alle lopende sessies over alle apparaattypen en fasen."""
        sessions = []
        for hmm in self._hmms.values():
            sessions.extend(hmm.get_all_active_sessions())
        return sessions

    def get_diagnostics(self) -> dict:
        return {dt: hmm.get_diagnostics() for dt, hmm in self._hmms.items()}
