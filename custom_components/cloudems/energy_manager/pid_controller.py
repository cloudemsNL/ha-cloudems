# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

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


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — PID Auto-Tuner (Relay Feedback / Ziegler-Nichols)
# ═══════════════════════════════════════════════════════════════════════════════

class PIDAutoTuner:
    """
    Automatic PID parameter tuner using the relay feedback (Åström-Hägglund) method.

    How it works:
      1. Temporarily replaces PID output with a relay (bang-bang: high/low)
      2. Measures the resulting oscillation (period Tu, amplitude Ku)
      3. Calculates Kp, Ki, Kd using Ziegler-Nichols PID tuning rules
      4. Writes results back to the PIDController
      5. Caller can then accept or reject the new parameters

    Usage:
        tuner = PIDAutoTuner(pid_controller, relay_amplitude=5.0)
        # call tuner.step(measurement) every sample_time instead of pid.compute()
        if tuner.done:
            kp, ki, kd = tuner.get_tuned_params()
            pid.kp = kp; pid.ki = ki; pid.kd = kd

    Safety: relay amplitude should be a small fraction of the output range.
    Auto-tuning should only run during stable, representative operating conditions.
    """

    def __init__(
        self,
        pid: PIDController,
        relay_amplitude: float = 5.0,   # half-amplitude of relay output swing
        min_cycles: int = 4,             # number of full oscillation cycles needed
        timeout_steps: int = 300,        # give up after N steps (~50 min at 10s)
        label: str = "auto_tune",
    ) -> None:
        self._pid            = pid
        self._relay_amp      = relay_amplitude
        self._min_cycles     = min_cycles
        self._timeout        = timeout_steps

        self._relay_output   = pid.output_max   # start HIGH
        self._last_crossing: float | None = None
        self._crossings: list[float] = []       # half-period durations between zero-crossings
        self._amplitudes: list[float] = []      # measured process variable amplitudes per half-cycle
        self._meas_max: float = float("-inf")   # track measurement extremes per half-cycle
        self._meas_min: float = float("inf")
        self._step           = 0
        self._done           = False
        self._failed         = False
        self._tuned_kp: float | None = None
        self._tuned_ki: float | None = None
        self._tuned_kd: float | None = None
        self._label          = label

        _LOGGER.info("PID AutoTuner [%s] gestart (relay_amplitude=%.1f)", label, relay_amplitude)

    @property
    def done(self) -> bool:
        return self._done

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def active(self) -> bool:
        return not self._done and not self._failed

    def step(self, measurement: float) -> float:
        """
        Run one relay-feedback step.
        Returns the relay output (use this instead of pid.compute()).
        """
        if self._done or self._failed:
            return self._pid.compute(measurement) or self._pid._prev_output

        self._step += 1
        if self._step > self._timeout:
            _LOGGER.warning("PID AutoTuner [%s]: timeout na %d stappen", self._label, self._step)
            self._failed = True
            return self._pid._prev_output

        error = self._pid.setpoint - measurement

        # Track measurement extremes within each half-cycle (for amplitude estimation)
        self._meas_max = max(self._meas_max, measurement)
        self._meas_min = min(self._meas_min, measurement)

        # Relay logic: flip output when error crosses zero
        if self._last_crossing is None:
            self._last_crossing = time.time()

        prev_relay = self._relay_output
        if error > 0:
            self._relay_output = self._pid.output_max
        else:
            self._relay_output = self._pid.output_min

        # Detect sign change (zero crossing)
        if (prev_relay != self._relay_output) and self._last_crossing is not None:
            now = time.time()
            period_half = now - self._last_crossing
            self._crossings.append(period_half)
            self._last_crossing = now

            # Record half-cycle amplitude and reset extremes
            half_amp = (self._meas_max - self._meas_min) / 2.0
            if half_amp > 0:
                self._amplitudes.append(half_amp)
            self._meas_max = float("-inf")
            self._meas_min = float("inf")

            cycles = len(self._crossings) // 2
            if cycles >= self._min_cycles:
                self._calculate_params()

        return self._relay_output

    def _calculate_params(self) -> None:
        """Apply Ziegler-Nichols tuning from measured oscillation."""
        if len(self._crossings) < 4:
            self._failed = True
            return

        # Estimate ultimate period Tu (average of full oscillation periods)
        full_periods = [self._crossings[i] + self._crossings[i+1]
                        for i in range(0, len(self._crossings)-1, 2)]
        Tu = sum(full_periods) / len(full_periods) if full_periods else 0

        # Ultimate gain Ku from relay: Ku = 4d / (π * A)
        # d = relay amplitude (half-swing of relay output)
        # A = measured amplitude of process variable oscillation
        d = self._relay_amp
        # Use average of measured amplitudes; fall back to relay amplitude if no data yet
        A = (sum(self._amplitudes) / len(self._amplitudes)) if self._amplitudes else d
        if Tu <= 0 or A <= 0:
            self._failed = True
            return

        Ku = (4 * d) / (3.14159 * A)

        # Ziegler-Nichols PID rules
        kp = 0.60 * Ku
        ki = 1.20 * Ku / Tu
        kd = 0.075 * Ku * Tu

        # Clamp to reasonable ranges
        kp = max(0.1, min(20.0, kp))
        ki = max(0.01, min(5.0, ki))
        kd = max(0.0,  min(5.0, kd))

        self._tuned_kp = round(kp, 3)
        self._tuned_ki = round(ki, 3)
        self._tuned_kd = round(kd, 3)
        self._done     = True

        _LOGGER.info(
            "PID AutoTuner [%s] klaar: Ku=%.2f Tu=%.1fs → Kp=%.3f Ki=%.3f Kd=%.3f",
            self._label, Ku, Tu, kp, ki, kd,
        )

    def get_tuned_params(self) -> tuple[float, float, float] | None:
        """Returns (Kp, Ki, Kd) if tuning completed, else None."""
        if self._done and self._tuned_kp is not None:
            return self._tuned_kp, self._tuned_ki, self._tuned_kd
        return None

    def apply_to_pid(self) -> bool:
        """Write tuned parameters back to the PIDController. Returns True on success."""
        params = self.get_tuned_params()
        if params is None:
            return False
        self._pid.kp, self._pid.ki, self._pid.kd = params
        self._pid.reset()
        _LOGGER.info(
            "PID AutoTuner [%s]: parameters toegepast op PID → Kp=%.3f Ki=%.3f Kd=%.3f",
            self._label, *params,
        )
        return True

    def to_dict(self) -> dict:
        return {
            "active":         self.active,
            "done":           self._done,
            "failed":         self._failed,
            "step":           self._step,
            "crossings":      len(self._crossings),
            "relay_amplitude":self._relay_amp,
            "tuned_kp":       self._tuned_kp,
            "tuned_ki":       self._tuned_ki,
            "tuned_kd":       self._tuned_kd,
        }
