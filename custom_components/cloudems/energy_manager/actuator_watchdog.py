"""
CloudEMS — actuator_watchdog.py

Periodieke controle: is de feitelijke staat van actuatoren gelijk aan de gewenste staat?
Als er een afwijking is → stuur het commando opnieuw.

Principe:
  - Elk actuator-module registreert zijn gewenste staat via register()
  - De watchdog controleert elke CHECK_INTERVAL seconden
  - Bij mismatch: herstel-callback aanroepen + loggen

Dit is essentieel voor cloud-integratie: de cloud weet wat gewenst is,
de bridge controleert of HA de juiste staat heeft.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL_S = 60   # elke minuut checken
MAX_DRIFT_BEFORE_CORRECT = 2  # pas corrigeren na 2 opeenvolgende afwijkingen


@dataclass
class ActuatorEntry:
    """Registratie van één te bewaken actuator."""
    key:            str                          # unieke sleutel bijv. "boiler_preset"
    entity_id:      str                          # HA entity_id om te lezen
    desired_state:  Any                          # gewenste staat (string, float, etc.)
    restore_cb:     Callable[[], Awaitable[None]]  # async callback om te herstellen
    tolerance:      float = 0.0                  # voor numerieke states: toegestane afwijking
    drift_count:    int   = 0                    # hoeveel opeenvolgende afwijkingen
    last_checked:   float = field(default_factory=time.time)
    last_corrected: float = 0.0


class ActuatorWatchdog:
    """
    Bewaakt of actuatoren de gewenste staat hebben en corrigeert bij afwijking.
    
    Gebruik:
        watchdog = ActuatorWatchdog(hass)
        watchdog.register("solar_switch", "switch.growatt_oost", "on", restore_fn)
        
        # In coordinator tick:
        await watchdog.async_tick()
    """

    def __init__(self, hass) -> None:
        self._hass = hass
        self._entries: dict[str, ActuatorEntry] = {}
        self._last_full_check = 0.0

    def register(
        self,
        key: str,
        entity_id: str,
        desired_state: Any,
        restore_cb: Callable[[], Awaitable[None]],
        tolerance: float = 0.0,
    ) -> None:
        """Registreer of update een actuator om te bewaken."""
        if key in self._entries:
            self._entries[key].desired_state = desired_state
            self._entries[key].entity_id = entity_id
        else:
            self._entries[key] = ActuatorEntry(
                key=key,
                entity_id=entity_id,
                desired_state=desired_state,
                restore_cb=restore_cb,
                tolerance=tolerance,
            )

    def unregister(self, key: str) -> None:
        """Verwijder een actuator uit bewaking."""
        self._entries.pop(key, None)

    async def async_tick(self) -> None:
        """Aanroepen elke coordinator slow-tick. Checkt alleen als CHECK_INTERVAL verstreken."""
        now = time.time()
        if now - self._last_full_check < CHECK_INTERVAL_S:
            return
        self._last_full_check = now

        for entry in list(self._entries.values()):
            try:
                await self._check_entry(entry)
            except Exception as err:
                _LOGGER.debug("ActuatorWatchdog fout bij %s: %s", entry.key, err)

    async def _check_entry(self, entry: ActuatorEntry) -> None:
        """Controleer één actuator. Corrigeer bij hardnekkige afwijking."""
        state = self._hass.states.get(entry.entity_id)
        if not state or state.state in ("unavailable", "unknown"):
            return

        actual = state.state
        desired = str(entry.desired_state)

        # Numerieke tolerantie
        if entry.tolerance > 0:
            try:
                diff = abs(float(actual) - float(desired))
                matches = diff <= entry.tolerance
            except (ValueError, TypeError):
                matches = actual == desired
        else:
            matches = actual.lower() == desired.lower()

        if matches:
            if entry.drift_count > 0:
                _LOGGER.debug("ActuatorWatchdog: %s hersteld naar %s", entry.key, desired)
            entry.drift_count = 0
            return

        entry.drift_count += 1
        _LOGGER.warning(
            "ActuatorWatchdog: %s afwijking #%d — gewenst=%s, feitelijk=%s",
            entry.key, entry.drift_count, desired, actual
        )

        if entry.drift_count >= MAX_DRIFT_BEFORE_CORRECT:
            _LOGGER.warning(
                "ActuatorWatchdog: %s corrigeren (entity=%s, gewenst=%s)",
                entry.key, entry.entity_id, desired
            )
            try:
                await entry.restore_cb()
                entry.drift_count = 0
                entry.last_corrected = time.time()
            except Exception as err:
                _LOGGER.error("ActuatorWatchdog: correctie %s mislukt: %s", entry.key, err)

    @property
    def summary(self) -> dict:
        """Status overzicht voor sensor/diagnostics."""
        return {
            k: {
                "entity_id":      e.entity_id,
                "desired":        e.desired_state,
                "drift_count":    e.drift_count,
                "last_corrected": e.last_corrected,
            }
            for k, e in self._entries.items()
        }
