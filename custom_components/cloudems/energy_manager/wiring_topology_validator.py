# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
wiring_topology_validator.py — v4.6.531

Controleert of CT-klemmen op de juiste fasen zitten door NILM-vermogenspulsen
te correleren met fase-vermogenspieken.

Probleem dat dit detecteert:
  Gebruiker heeft CT-klem van L2 op de L1-ingang van de meter aangesloten.
  NILM ziet een apparaat op L2 (via P1-stroom), maar de vermogenspiek
  komt binnen op de L1-kanaal van de fase-sensor.

Werking:
  - Registreer korte vermogenspieken per apparaat (NILM-events)
  - Kijk welke fase-sensor op hetzelfde moment een piek toont
  - Bouw stemmen op: apparaat X "ziet" piek op fase Y (sensor-zijde)
    maar NILM denkt fase Z (P1-stroom-zijde)
  - Als sensor-fase ≠ NILM-fase voor voldoende apparaten → CT omgewisseld

Zelflerend via stemmen-telling per {nilm_fase → sensor_fase}.
Waarschuwing als meerderheid van apparaten op fase X eigenlijk via sensor Y binnenkomt.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_wiring_topology_v1"
STORAGE_VERSION = 1

# Minimum votes voor betrouwbare uitspraak
MIN_VOTES       = 10
# Minimum fractie van apparaten op een fase die verkeerd gaat → waarschuwing
SWAP_THRESHOLD  = 0.65   # 65% van de apparaten op fase X loopt via sensor Y
# Tijdvenster voor correlatie (ms → s)
CORRELATION_WINDOW_S = 3.0
SAVE_INTERVAL   = 30


@dataclass
class TopologyVote:
    """Stem: apparaat op NILM-fase X toonde piek op sensor-fase Y."""
    nilm_phase:   str
    sensor_phase: str
    count:        int = 0


class WiringTopologyValidator:
    """
    Leert of CT-klemmen overeenkomen met NILM fase-toewijzingen.
    """

    PHASES = ["L1", "L2", "L3"]

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._store  = None
        # votes[nilm_phase][sensor_phase] = count
        self._votes: Dict[str, Dict[str, int]] = {
            ph: {s: 0 for s in self.PHASES} for ph in self.PHASES
        }
        # Wacht op pieken: {device_name: (timestamp, nilm_phase, power_w)}
        self._pending_events: dict = {}
        self._dirty_count  = 0
        self._hint_engine  = None
        self._decisions_history = None
        self._last_analysis_ts: float = 0.0

    def set_hint_engine(self, he) -> None:
        self._hint_engine = he

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        data = await self._store.async_load()
        if data:
            for np in self.PHASES:
                for sp in self.PHASES:
                    self._votes[np][sp] = int(
                        data.get(np, {}).get(sp, 0)
                    )

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(self._votes)
            self._dirty_count = 0

    def record_nilm_event(
        self,
        device_name: str,
        nilm_phase: str,
        power_delta_w: float,
    ) -> None:
        """
        Registreer een NILM-event: apparaat op phase nilm_phase is aan/uit gegaan.
        power_delta_w: positief = aangegaan, negatief = uitgegaan.
        """
        if nilm_phase not in self.PHASES or abs(power_delta_w) < 50:
            return
        self._pending_events[device_name] = (time.time(), nilm_phase, power_delta_w)

    def observe_phase_power(
        self,
        l1_w: Optional[float],
        l2_w: Optional[float],
        l3_w: Optional[float],
    ) -> None:
        """
        Elke cyclus aanroepen met actuele fase-vermogens.
        Correleert met pending NILM-events.
        """
        now = time.time()
        phase_vals = {"L1": l1_w, "L2": l2_w, "L3": l3_w}
        expired = []

        for device_name, (event_ts, nilm_phase, delta_w) in self._pending_events.items():
            age = now - event_ts
            if age > CORRELATION_WINDOW_S:
                expired.append(device_name)
                continue

            # Zoek welke fase-sensor de grootste piek toont
            best_phase = None
            best_val   = 0.0
            for ph, val in phase_vals.items():
                if val is None:
                    continue
                if abs(val) > best_val:
                    best_val   = abs(val)
                    best_phase = ph

            if best_phase and best_val > 50:
                self._votes[nilm_phase][best_phase] += 1
                self._dirty_count += 1
                expired.append(device_name)

        for d in expired:
            self._pending_events.pop(d, None)

        # Analyseer elke 5 minuten
        if now - self._last_analysis_ts > 300:
            self._last_analysis_ts = now
            self._analyze()

    def _analyze(self) -> None:
        """Detecteer CT-klem wisselingen op basis van stemmen."""
        for nilm_ph in self.PHASES:
            total_votes = sum(self._votes[nilm_ph].values())
            if total_votes < MIN_VOTES:
                continue

            # Meest-gestemde sensor-fase
            best_sensor_ph = max(self._votes[nilm_ph], key=lambda k: self._votes[nilm_ph][k])
            best_count     = self._votes[nilm_ph][best_sensor_ph]
            best_fraction  = best_count / total_votes

            if best_sensor_ph != nilm_ph and best_fraction >= SWAP_THRESHOLD:
                self._emit_hint(nilm_ph, best_sensor_ph, best_fraction, total_votes)
                self._log_swap(nilm_ph, best_sensor_ph, best_fraction, total_votes)

    def _emit_hint(
        self,
        nilm_phase: str,
        sensor_phase: str,
        fraction: float,
        total_votes: int,
    ) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"wiring_swap_{nilm_phase}_{sensor_phase}",
                title      = f"CT-klem mogelijk omgewisseld: {nilm_phase} ↔ {sensor_phase}",
                message    = (
                    f"{fraction*100:.0f}% van de apparaten die P1 op fase {nilm_phase} "
                    f"plaatst, verschijnt op sensor-fase {sensor_phase} "
                    f"({total_votes} metingen). "
                    f"Waarschijnlijk zijn de CT-klemmen van {nilm_phase} en {sensor_phase} "
                    f"omgewisseld. Controleer de bedrading van je stroommeter."
                ),
                action     = f"Controleer CT-klem bedrading voor fase {nilm_phase} en {sensor_phase}",
                confidence = min(0.90, fraction),
            )
        except Exception as _e:
            _LOGGER.debug("WiringTopology hint fout: %s", _e)

    def _log_swap(
        self,
        nilm_phase: str, sensor_phase: str,
        fraction: float, total_votes: int,
    ) -> None:
        msg = (
            f"WiringTopologyValidator: CT-klem swap {nilm_phase}→{sensor_phase} "
            f"gedetecteerd ({fraction*100:.0f}%, n={total_votes})"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "wiring_topology",
                    action   = f"swap_{nilm_phase}_{sensor_phase}",
                    reason   = f"{fraction*100:.0f}% consensus",
                    message  = msg,
                    extra    = {
                        "nilm_phase":   nilm_phase,
                        "sensor_phase": sensor_phase,
                        "fraction":     round(fraction, 3),
                        "total_votes":  total_votes,
                        "votes":        self._votes[nilm_phase],
                    },
                )
            except Exception:
                pass

    def get_diagnostics(self) -> dict:
        result = {}
        for nilm_ph in self.PHASES:
            total = sum(self._votes[nilm_ph].values())
            result[nilm_ph] = {
                "total_votes": total,
                "votes":       dict(self._votes[nilm_ph]),
                "dominant_sensor": (
                    max(self._votes[nilm_ph], key=lambda k: self._votes[nilm_ph][k])
                    if total > 0 else None
                ),
            }
        return result
