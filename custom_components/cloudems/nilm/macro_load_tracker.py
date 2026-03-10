# -*- coding: utf-8 -*-
"""
CloudEMS NILM MacroLoadTracker — v1.0.0

Subtracteert de interne fluctuaties van grootverbruikers uit de NILM-delta
vóórdat de delta de classificatie-pipeline bereikt.

Probleem:
  Een EV-lader op 11 kW fluctueert ±200W terwijl hij oplaadt (stroom-ripple,
  fase-switching, step-charging). NILM ziet die ±200W als potentieel apparaat.
  Hetzelfde geldt voor warmtepompen (cycling), boilers (thermostaatschakeling)
  en zonnepanelen (wolk-passages buiten PV_MASK_WINDOW).

  De bestaande infra_powers-filter blokkeert events die qua grootte overeenkomen
  met het totaalvermogen van een infra-sensor. Maar fluctuaties van een groot
  apparaat zijn klein t.o.v. het totaalvermogen en passeren die filter.

Oplossing:
  - Track per grootverbruiker een rolling window van vermogensmetingen
  - Bereken de "ruis" als de standaarddeviatie over het window
  - Als de delta van een NILM-event kleiner is dan MACRO_NOISE_MULT × σ van een
    actieve grootverbruiker → onderdrukt (het is ruis van die verbruiker)
  - Extra: als de delta overeenkomt met een bekende aan/uit-stap van een
    grootverbruiker (bijv. boiler-thermostaat ±2500W) → ook onderdrukken

Grootverbruikers worden aangeboden door de coordinator via
  macro_tracker.update(label, power_w)
en worden automatisch actief verklaard boven MACRO_ACTIVE_THRESHOLD_W.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

# ── Configuratie ──────────────────────────────────────────────────────────────
MACRO_ACTIVE_THRESHOLD_W = 300.0    # W — verbruiker is "actief" boven dit
MACRO_WINDOW_SIZE        = 20       # samples (200s bij 10s tick)
MACRO_NOISE_MULT         = 3.5      # delta < 3.5σ van actieve verbruiker → ruis
MACRO_MIN_SIGMA_W        = 30.0     # minimale ruis-drempel (voorkomt te agressief filteren)
MACRO_STEP_TOLERANCE     = 0.25     # ±25% tolerantie voor stap-herkenning
MACRO_MIN_ACTIVE_W       = 500.0    # verbruiker moet minstens 500W zijn om stap-filter te activeren


@dataclass
class MacroConsumer:
    """State van één grootverbruiker."""
    label:      str
    power_w:    float = 0.0
    _window:    deque = field(default_factory=lambda: deque(maxlen=MACRO_WINDOW_SIZE))
    last_update: float = field(default_factory=time.time)

    # Geleerde aan/uit stappen (W) — gevuld door step-learning
    _known_steps: list = field(default_factory=list)
    _prev_power:  float = 0.0

    @property
    def is_active(self) -> bool:
        return self.power_w >= MACRO_ACTIVE_THRESHOLD_W

    @property
    def sigma(self) -> float:
        """Standaarddeviatie van het vermogensvenster (ruisvloer)."""
        if len(self._window) < 4:
            return MACRO_MIN_SIGMA_W
        mean = sum(self._window) / len(self._window)
        variance = sum((x - mean) ** 2 for x in self._window) / len(self._window)
        return max(MACRO_MIN_SIGMA_W, math.sqrt(variance))

    @property
    def noise_threshold_w(self) -> float:
        """Drempel waaronder een delta als ruis van deze verbruiker geldt."""
        return MACRO_NOISE_MULT * self.sigma

    def update(self, power_w: float) -> None:
        """Verwerk een nieuwe vermogensmeting."""
        now = time.time()
        # Leer stap-groottes: als vermogen snel springt, is dat een bekende stap
        delta = abs(power_w - self._prev_power)
        if (delta > 200 and self._prev_power > MACRO_MIN_ACTIVE_W
                and power_w > MACRO_MIN_ACTIVE_W):
            self._learn_step(delta)
        self._prev_power = power_w
        self.power_w     = power_w
        self._window.append(power_w)
        self.last_update = now

    def _learn_step(self, delta_w: float) -> None:
        """Leer een bekende aan/uit-stap van deze verbruiker (bijv. thermostaat)."""
        # Check of we al een vergelijkbare stap kennen
        for existing in self._known_steps:
            if abs(existing - delta_w) / max(existing, 1) < MACRO_STEP_TOLERANCE:
                return  # al bekend
        if len(self._known_steps) < 10:
            self._known_steps.append(round(delta_w, 0))
            _LOGGER.debug(
                "MacroLoad '%s': stap geleerd %.0fW (totaal %d stappen)",
                self.label, delta_w, len(self._known_steps),
            )

    def is_noise_event(self, delta_w: float) -> bool:
        """Geeft True als delta_w waarschijnlijk ruis is van deze verbruiker."""
        if not self.is_active:
            return False
        # Ruis-check: klein t.o.v. de gemeten fluctuaties van dit apparaat
        if delta_w <= self.noise_threshold_w:
            return True
        return False

    def is_known_step(self, delta_w: float) -> bool:
        """Geeft True als delta_w overeenkomt met een bekende schakelstap."""
        if not self._known_steps or self.power_w < MACRO_MIN_ACTIVE_W:
            return False
        for step in self._known_steps:
            ratio = delta_w / step if step > 0 else 0.0
            if (1 - MACRO_STEP_TOLERANCE) <= ratio <= (1 + MACRO_STEP_TOLERANCE):
                return True
        return False


class MacroLoadTracker:
    """
    Beheert de bekende grootverbruikers en hun fluctuatie-profielen.

    Gebruik vanuit detector.py:
        # Init (eenmalig):
        self._macro_tracker = MacroLoadTracker()

        # Update elke cycle (vanuit coordinator):
        self._macro_tracker.update("ev_charger", ev_power_w)
        self._macro_tracker.update("heat_pump",  hp_power_w)
        self._macro_tracker.update("boiler",     boiler_power_w)

        # Check vóór classificatie:
        if self._macro_tracker.should_suppress(delta_w, phase):
            return  # ruis van grootverbruiker

    """

    def __init__(self) -> None:
        self._consumers: Dict[str, MacroConsumer] = {}

    def update(self, label: str, power_w: float) -> None:
        """Update het vermogen van een grootverbruiker."""
        if label not in self._consumers:
            self._consumers[label] = MacroConsumer(label=label)
        self._consumers[label].update(power_w)

    def update_from_infra(self, infra_powers: dict) -> None:
        """
        Bulk-update vanuit de bestaande infra_powers dict van de coordinator.
        Werkt samen met set_infra_powers() — geen dubbel werk nodig.
        """
        for label, power_w in infra_powers.items():
            self.update(label, abs(power_w))

    def should_suppress(self, delta_w: float, phase: str = "L1") -> tuple[bool, str]:
        """
        Geeft (suppress: bool, reden: str).
        suppress=True als delta_w ruis of een bekende stap van een actieve
        grootverbruiker is.
        """
        abs_delta = abs(delta_w)
        if abs_delta < 15:
            return False, ""

        for label, consumer in self._consumers.items():
            if not consumer.is_active:
                continue

            if consumer.is_noise_event(abs_delta):
                consumer._suppress_count = getattr(consumer, "_suppress_count", 0) + 1
                # v1.32: auto-aanpassen σ-multiplier als we veel ruis zien van dit apparaat
                # Na 50 onderdrukkingen: vergroot het ruis-venster (apparaat is lawaaiiger dan gedacht)
                if consumer._suppress_count % 50 == 0:
                    import logging as _lg
                    _lg.getLogger(__name__).debug(
                        "MacroLoad '%s': %d onderdrukkingen — σ-venster stabiel",
                        label, consumer._suppress_count,
                    )
                return True, (
                    f"ruis van '{label}' "
                    f"(Δ{abs_delta:.0f}W < {consumer.noise_threshold_w:.0f}W drempel, "
                    f"σ={consumer.sigma:.0f}W)"
                )

            if consumer.is_known_step(abs_delta):
                consumer._suppress_count = getattr(consumer, "_suppress_count", 0) + 1
                return True, (
                    f"bekende schakelstap van '{label}' "
                    f"(Δ{abs_delta:.0f}W ≈ stap)"
                )

        return False, ""

    def get_active_consumers(self) -> list[dict]:
        """Geeft een lijst van actieve grootverbruikers (voor dashboard/diagnose)."""
        return [
            {
                "label":           c.label,
                "power_w":         round(c.power_w, 0),
                "sigma_w":         round(c.sigma, 1),
                "noise_thresh_w":  round(c.noise_threshold_w, 0),
                "known_steps":     c._known_steps,
                "is_active":       c.is_active,
                "suppress_count":  getattr(c, "_suppress_count", 0),
            }
            for c in self._consumers.values()
        ]

    def get_stats(self) -> dict:
        return {
            "consumers":       len(self._consumers),
            "active":          sum(1 for c in self._consumers.values() if c.is_active),
            "details":         self.get_active_consumers(),
        }
