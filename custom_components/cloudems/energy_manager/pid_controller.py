"""
CloudEMS PID Controller — v1.3.0

Generieke PID-regelaar voor gebruik bij:
  - Fase-stroom regeling (dimmen van omvormers)
  - EV laadstroom bijsturen op zonne-overschot
  - Batterij laad/ontlaad vermogen sturen

Werking:
  output = Kp * e(t) + Ki * ∫e(t)dt + Kd * de(t)/dt

Anti-windup: integrator wordt geclamped op [output_min, output_max]
Anti-pendel : output wordt alleen toegepast als |Δoutput| > deadband

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class PIDState:
    """Interne toestand van de PID — handig voor logging/diagnostics."""
    setpoint: float       = 0.0
    measurement: float    = 0.0
    error: float          = 0.0
    p_term: float         = 0.0
    i_term: float         = 0.0
    d_term: float         = 0.0
    output: float         = 0.0
    output_clamped: float = 0.0
    dt: float             = 0.0
    timestamp: float      = field(default_factory=time.time)


class PIDController:
    """
    PID-regelaar met anti-windup, deadband en output-clamping.

    Parameters
    ----------
    kp : float
        Proportionele versterking.  Hogere waarde = snellere reactie maar meer overshoot.
    ki : float
        Integratieve versterking.   Compenseert blijvende afwijking.
    kd : float
        Differentiële versterking.  Dempt snelle veranderingen (anti-pendel).
    setpoint : float
        Gewenste waarde (bijv. 90% van max fase-stroom in Ampere).
    output_min / output_max : float
        Minimale en maximale uitgangswaarde (bijv. 0–100% dimmen, of 6–32A EV).
    deadband : float
        Minimale outputwijziging om door te sturen. Voorkomt continu kleine aanpassingen.
    sample_time : float
        Minimale tijd (s) tussen twee berekeningen. Negeert aanroepen die te snel komen.

    Typische instellingen voor fase-stroom dimmen:
        kp=2.0, ki=0.3, kd=0.5, setpoint=max_A*0.9, output_min=0, output_max=100
    """

    def __init__(
        self,
        kp: float = 2.0,
        ki: float = 0.3,
        kd: float = 0.5,
        setpoint: float = 0.0,
        output_min: float = 0.0,
        output_max: float = 100.0,
        deadband: float = 1.0,
        sample_time: float = 5.0,    # seconden
        label: str = "pid",
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.output_min = output_min
        self.output_max = output_max
        self.deadband = deadband
        self.sample_time = sample_time
        self.label = label

        self._integral: float = 0.0
        self._prev_error: float = 0.0
        self._prev_output: float = output_max   # Begin op max (omvormer aan)
        self._last_time: float = 0.0
        self._last_state: PIDState | None = None

    # ── Hoofd-berekening ───────────────────────────────────────────────────────

    def compute(self, measurement: float) -> float | None:
        """
        Bereken een nieuwe uitgangswaarde op basis van de meting.

        Geeft None terug als sample_time nog niet verstreken is.
        Output is een positieve waarde tussen output_min en output_max.

        In de context van omvormer-dimmen:
            setpoint   = bijv. 22A (= 90% van 25A fase-max)
            measurement = huidige fase-stroom in A
            output     = gewenst vermogen omvormer in % (100 = vol, 0 = uit)

        Als de stroom te hoog is (measurement > setpoint):
            → error < 0 → output daalt → omvormer dimmt
        Als de stroom te laag is:
            → error > 0 → output stijgt → omvormer produceert meer
        """
        now = time.time()
        dt = now - self._last_time

        if self._last_time > 0 and dt < self.sample_time:
            return None   # Te vroeg voor nieuwe berekening

        error = self.setpoint - measurement

        # ── P ─────────────────────────────────────────────────────────────────
        p_term = self.kp * error

        # ── I (met anti-windup) ───────────────────────────────────────────────
        self._integral += error * dt
        i_term = self.ki * self._integral

        # Anti-windup: clamp de integrator als output al geclamped is
        raw_i_term_clamped = max(
            self.output_min - p_term,
            min(self.output_max - p_term, i_term)
        )
        if raw_i_term_clamped != i_term:
            self._integral = raw_i_term_clamped / self.ki if self.ki != 0 else 0.0
            i_term = raw_i_term_clamped

        # ── D ─────────────────────────────────────────────────────────────────
        d_term = 0.0
        if dt > 0 and self._last_time > 0:
            d_term = self.kd * (error - self._prev_error) / dt

        # ── Output ────────────────────────────────────────────────────────────
        output_raw = p_term + i_term + d_term
        output_clamped = max(self.output_min, min(self.output_max, output_raw))

        # Deadband: stuur alleen door als de wijziging groot genoeg is
        if abs(output_clamped - self._prev_output) < self.deadband:
            output_clamped = self._prev_output

        # State opslaan
        self._last_state = PIDState(
            setpoint=self.setpoint,
            measurement=measurement,
            error=error,
            p_term=p_term,
            i_term=i_term,
            d_term=d_term,
            output=output_raw,
            output_clamped=output_clamped,
            dt=round(dt, 2),
            timestamp=now,
        )

        self._prev_error  = error
        self._prev_output = output_clamped
        self._last_time   = now

        _LOGGER.debug(
            "PID[%s] setpoint=%.2f meas=%.2f err=%.2f "
            "P=%.2f I=%.2f D=%.2f out=%.2f",
            self.label, self.setpoint, measurement, error,
            p_term, i_term, d_term, output_clamped,
        )
        return output_clamped

    # ── Hulpfuncties ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset de integrator en vorige error. Gebruik bij grote setpoint-sprongen."""
        self._integral    = 0.0
        self._prev_error  = 0.0
        self._prev_output = self.output_max
        self._last_time   = 0.0
        _LOGGER.debug("PID[%s] gereset", self.label)

    def update_setpoint(self, new_setpoint: float) -> None:
        """Pas setpoint aan; reset integrator als verschil > 20% om windup te voorkomen."""
        if abs(new_setpoint - self.setpoint) > 0.2 * max(abs(self.setpoint), 1):
            self.reset()
        self.setpoint = new_setpoint

    @property
    def state(self) -> PIDState | None:
        return self._last_state

    def to_dict(self) -> dict[str, Any]:
        """Diagnostics dict voor sensor attributes / HA developer tools."""
        s = self._last_state
        return {
            "label":        self.label,
            "kp": self.kp, "ki": self.ki, "kd": self.kd,
            "setpoint":     self.setpoint,
            "output_min":   self.output_min,
            "output_max":   self.output_max,
            "deadband":     self.deadband,
            "integral":     round(self._integral, 4),
            "last_error":   round(self._prev_error, 4),
            "last_output":  round(self._prev_output, 4),
            **({"last_state": {
                "measurement":    round(s.measurement, 3),
                "error":          round(s.error, 3),
                "p_term":         round(s.p_term, 3),
                "i_term":         round(s.i_term, 3),
                "d_term":         round(s.d_term, 3),
                "output_clamped": round(s.output_clamped, 3),
                "dt_s":           s.dt,
            }} if s else {}),
        }
