# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS StateReader — v4.6.522.

Dunne abstractielaag over hass.states.get() voor gebruik in
energy_manager-modules.

Waarom deze laag
────────────────
34 energy_manager-modules roepen nu rechtstreeks hass.states.get() aan.
Dat koppelt ze hard aan Home Assistant — migratie naar cloud/non-HA vereist
dan aanpassingen in 34 bestanden.

Met StateReader is de wijziging bij een platform-migratie beperkt tot
één bestand: de implementatie van StateReader zelf.

Gebruik
───────
    # In een module:
    from ..energy_manager.state_reader import StateReader

    class MijnModule:
        def __init__(self, hass):
            self._sr = StateReader(hass)

        def evaluate(self):
            temp = self._sr.float("sensor.outside_temp")
            mode = self._sr.str("climate.woonkamer", attr="hvac_mode")
            is_on = self._sr.bool("switch.boiler")

Voordelen t.o.v. directe hass.states.get()
────────────────────────────────────────────
- Één plek voor None-guards, unavailable/unknown filtering en type-casting
- Attribuut-reads net zo eenvoudig als state-reads
- Mockbaar in unit tests (geef een dict mee als mock_states)
- Toekomstig: swap hass-backend voor cloud-backend zonder module-aanpassingen
- SensorIntervalRegistry automatisch gevoed als registry meegegeven wordt

Bestaande code hoeft NIET aangepast te worden — beide patronen coëxisteren.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)

# Type hint zonder circular import
if TYPE_CHECKING:
    from .sensor_interval_registry import SensorIntervalRegistry


class StateReader:
    """Lichtgewicht wrapper voor HA state-reads in energy_manager modules.

    Parameters
    ----------
    hass:
        Home Assistant core object (of None voor unit tests met mock_states).
    mock_states:
        Dict van entity_id → waarde/dict voor unit testing zonder HA.
        Als meegegeven wordt hass genegeerd.
    interval_registry:
        Optionele SensorIntervalRegistry — als meegegeven worden gelezen
        waarden automatisch geregistreerd voor interval-tracking.
    """

    def __init__(
        self,
        hass=None,
        mock_states: Optional[Dict[str, Any]] = None,
        interval_registry: Optional["SensorIntervalRegistry"] = None,
    ) -> None:
        self._hass             = hass
        self._mock             = mock_states
        self._registry         = interval_registry

    # ── Interne helpers ──────────────────────────────────────────────────────

    def _raw_state(self, entity_id: str) -> Optional[Any]:
        """Geef ruwe HA state-string of None bij unavailable/unknown."""
        if not entity_id:
            return None
        if self._mock is not None:
            v = self._mock.get(entity_id)
            return str(v) if v is not None else None
        if self._hass is None:
            return None
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        return state.state

    def _raw_attr(self, entity_id: str, attr: str) -> Optional[Any]:
        """Geef een attribuut-waarde of None."""
        if not entity_id or not attr:
            return None
        if self._mock is not None:
            v = self._mock.get(entity_id)
            if isinstance(v, dict):
                return v.get(attr)
            return None
        if self._hass is None:
            return None
        state = self._hass.states.get(entity_id)
        if state is None:
            return None
        return state.attributes.get(attr)

    def _feed_registry(self, entity_id: str, value: float) -> None:
        """Voer waarde door naar SensorIntervalRegistry als beschikbaar."""
        if self._registry is not None:
            try:
                self._registry.observe(entity_id, value)
            except Exception:
                pass

    # ── Publieke API ─────────────────────────────────────────────────────────

    def float(
        self,
        entity_id: str,
        attr: Optional[str] = None,
        default: Optional[float] = None,
    ) -> Optional[float]:
        """Lees state of attribuut als float. Geeft default bij fout.

        Als entity_id een vermogenssensor is, wordt de waarde automatisch
        doorgegeven aan de SensorIntervalRegistry voor interval-meting.
        """
        raw = self._raw_attr(entity_id, attr) if attr else self._raw_state(entity_id)
        if raw is None:
            return default
        try:
            v = float(raw)
            if attr is None:
                self._feed_registry(entity_id, v)
            return v
        except (ValueError, TypeError):
            return default

    def str(
        self,
        entity_id: str,
        attr: Optional[str] = None,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """Lees state of attribuut als string."""
        raw = self._raw_attr(entity_id, attr) if attr else self._raw_state(entity_id)
        if raw is None:
            return default
        return str(raw)

    def bool(
        self,
        entity_id: str,
        attr: Optional[str] = None,
        default: bool = False,
    ) -> bool:
        """Lees state of attribuut als bool.

        'on', 'true', '1', 'yes', 'home' → True. Alles anders → False.
        """
        raw = self._raw_attr(entity_id, attr) if attr else self._raw_state(entity_id)
        if raw is None:
            return default
        return str(raw).lower() in ("on", "true", "1", "yes", "home", "open", "unlocked")

    def int(
        self,
        entity_id: str,
        attr: Optional[str] = None,
        default: Optional[int] = None,
    ) -> Optional[int]:
        """Lees state of attribuut als int."""
        v = self.float(entity_id, attr, default=None)
        if v is None:
            return default
        return int(v)

    def available(self, entity_id: str) -> bool:
        """True als de entiteit bestaat en niet unavailable/unknown is."""
        if not entity_id:
            return False
        if self._mock is not None:
            return entity_id in self._mock
        if self._hass is None:
            return False
        state = self._hass.states.get(entity_id)
        return state is not None and state.state not in ("unavailable", "unknown", "")

    def all_of_domain(self, domain: str) -> list:
        """Geef alle entity_ids voor een domein (bijv. 'climate', 'switch').

        Returns lege lijst als hass niet beschikbaar is.
        """
        if self._mock is not None:
            return [eid for eid in self._mock if eid.startswith(f"{domain}.")]
        if self._hass is None:
            return []
        return [s.entity_id for s in self._hass.states.async_all(domain)]

    def attributes(self, entity_id: str) -> dict:
        """Geef volledige attributen-dict van een entiteit, of lege dict."""
        if not entity_id:
            return {}
        if self._mock is not None:
            v = self._mock.get(entity_id)
            return v if isinstance(v, dict) else {}
        if self._hass is None:
            return {}
        state = self._hass.states.get(entity_id)
        if state is None:
            return {}
        return dict(state.attributes)

    # ── Factory / configuratie ───────────────────────────────────────────────

    def with_registry(self, registry: "SensorIntervalRegistry") -> "StateReader":
        """Geef een nieuwe StateReader terug met interval_registry gekoppeld."""
        return StateReader(
            hass=self._hass,
            mock_states=self._mock,
            interval_registry=registry,
        )
