# -*- coding: utf-8 -*-
"""CloudEMS — Thermische massa leerder (v1.0)

Leert hoe lang het huis warm blijft nadat de verwarming uitschakelt.
Gebruikt dit om de warmtepomp slim voor te verwarmen op goedkope uren.

Werkt puur additief — geen invloed op bestaande logica.
"""
from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class ThermalObservation:
    """Één waarneming: temp na uitschakelen verwarming."""
    ts_off:      float   # unix timestamp uitschakelen
    temp_start:  float   # binnentemperatuur bij uitschakelen (°C)
    temp_out:    float   # buitentemperatuur (°C)
    temp_after_h: float  # binnentemp na 1 uur (°C)
    drop_per_h:  float   # kelvin daling per uur


class ThermalMassLearner:
    """Leert thermische massa van het huis via temperatuurmetingen.

    Schat hoe snel het huis afkoelt na het uitschakelen van verwarming.
    Verfijnt de schatting elke keer dat er nieuwe data binnenkomt.

    Gebruik:
        learner.observe(temp_in, temp_out, heating_on)  # elke coordinator tick
        hours = learner.hours_above(setpoint=20.0)       # hoeveel uur boven setpoint
    """

    STORE_KEY = "cloudems_thermal_mass_v1"
    MIN_OBS   = 5    # minimaal observaties voor betrouwbare schatting
    EMA_ALPHA = 0.15 # hoe snel het gemiddelde bijstelt

    def __init__(self) -> None:
        self._obs: list[ThermalObservation] = []
        self._drop_ema: float = 0.5        # K/uur daling (initieel conservatief)
        self._n_learned: int  = 0
        self._last_temp:  Optional[float] = None
        self._last_ts:    float = 0.0
        self._heating_was_on: bool = False
        self._off_ts:   float = 0.0
        self._off_temp: float = 20.0
        self._off_temp_out: float = 10.0
        self._ready: bool = False

    def observe(self, temp_in: float, temp_out: float, heating_on: bool) -> None:
        """Registreer één meting. Aanroepen elke coordinator tick (~10s)."""
        now = time.time()

        # Detecteer uitschakelmoment
        if self._heating_was_on and not heating_on:
            self._off_ts       = now
            self._off_temp     = temp_in
            self._off_temp_out = temp_out
            _LOGGER.debug("ThermalMass: verwarming uit op %.1f°C", temp_in)

        # Na 1 uur meten hoe ver temp gedaald is
        if (not heating_on and self._off_ts > 0
                and now - self._off_ts >= 3600
                and now - self._off_ts < 3700):
            drop = self._off_temp - temp_in
            if 0.05 < drop < 5.0:  # sanity check
                obs = ThermalObservation(
                    ts_off=self._off_ts,
                    temp_start=self._off_temp,
                    temp_out=self._off_temp_out,
                    temp_after_h=temp_in,
                    drop_per_h=drop,
                )
                self._obs.append(obs)
                self._obs = self._obs[-100:]  # bewaar laatste 100
                self._drop_ema = (
                    self.EMA_ALPHA * drop
                    + (1 - self.EMA_ALPHA) * self._drop_ema
                )
                self._n_learned += 1
                self._ready = self._n_learned >= self.MIN_OBS
                _LOGGER.info(
                    "ThermalMass: daling %.2f K/uur geleerd (EMA=%.2f, n=%d)",
                    drop, self._drop_ema, self._n_learned,
                )
                self._off_ts = 0.0  # reset voor volgende cyclus

        self._heating_was_on = heating_on
        self._last_temp = temp_in
        self._last_ts   = now

    def hours_above(self, setpoint: float = 20.0,
                    temp_now: Optional[float] = None) -> float:
        """Hoeveel uur blijft de temp boven setpoint zonder verwarming?"""
        t = temp_now if temp_now is not None else self._last_temp
        if t is None or self._drop_ema <= 0:
            return 0.0
        margin = t - setpoint
        if margin <= 0:
            return 0.0
        return round(margin / self._drop_ema, 1)

    def preheat_start_hour(self, target_hour: int, setpoint: float = 20.0,
                           temp_now: Optional[float] = None) -> Optional[int]:
        """Welk uur moet verwarming starten om op target_hour warm genoeg te zijn?

        Returns: uur om te starten (0-23), of None als al warm genoeg
        """
        buffer = self.hours_above(setpoint, temp_now)
        start = target_hour - int(math.ceil(buffer))
        if start < 0: start += 24
        return start if start != target_hour else None

    @property
    def stats(self) -> dict:
        return {
            "ready":        self._ready,
            "n_learned":    self._n_learned,
            "drop_k_per_h": round(self._drop_ema, 3),
            "hours_above_20": self.hours_above(20.0),
        }

    def to_dict(self) -> dict:
        return {
            "drop_ema":  self._drop_ema,
            "n_learned": self._n_learned,
            "obs":       [(o.ts_off, o.temp_start, o.temp_out,
                           o.temp_after_h, o.drop_per_h) for o in self._obs[-50:]],
        }

    def from_dict(self, d: dict) -> None:
        self._drop_ema  = float(d.get("drop_ema",  0.5))
        self._n_learned = int(d.get("n_learned", 0))
        self._ready     = self._n_learned >= self.MIN_OBS
        for row in d.get("obs", []):
            if len(row) == 5:
                self._obs.append(ThermalObservation(*row))
