# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Home Assistant EntityProvider
==========================================

De HA implementatie van de EntityProvider abstractie.
Werkt exact zoals de coordinator nu al werkt — geen gedragsverandering.

Dit is provider #1 van vele. De coordinator weet niet dat dit HA is.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .entity_provider import EntityProvider, EntityState, register_provider

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

logger = logging.getLogger("cloudems.provider.ha")


@register_provider("ha")
class HAEntityProvider(EntityProvider):
    """
    Home Assistant entity provider.

    Wikkelt hass.states.get() en hass.services.async_call()
    in de universele EntityProvider interface.

    De coordinator gebruikt alleen self._provider.get_state(entity_id)
    — nooit meer hass.states.get() direct.
    """

    platform     = "ha"
    display_name = "Home Assistant"
    icon         = "mdi:home-assistant"

    def __init__(self, hass: "HomeAssistant") -> None:
        super().__init__()
        self._hass = hass

    # ── Implementatie ─────────────────────────────────────────────────────────

    async def get_state(self, entity_id: str) -> Optional[EntityState]:
        """Haal HA state op en converteer naar EntityState."""
        if not entity_id:
            return None

        ha_state = self._hass.states.get(entity_id)
        if ha_state is None:
            return None

        unavailable = ha_state.state in ("unavailable", "unknown", "")

        return EntityState(
            entity_id  = entity_id,
            state      = ha_state.state,
            attributes = dict(ha_state.attributes),
            unit       = ha_state.attributes.get("unit_of_measurement"),
            available  = not unavailable,
        )

    async def get_all_of_domain(self, domain: str) -> List[EntityState]:
        """Haal alle HA entities op van een bepaald domein."""
        results = []
        for ha_state in self._hass.states.async_all(domain):
            results.append(EntityState(
                entity_id  = ha_state.entity_id,
                state      = ha_state.state,
                attributes = dict(ha_state.attributes),
                unit       = ha_state.attributes.get("unit_of_measurement"),
                available  = ha_state.state not in ("unavailable", "unknown"),
            ))
        return results

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Roep een HA service aan.

        Gebruikt target= voor entity_id zodat HA 2024.x+ geen validatiefout
        gooit ('Entity ID entity_id is an invalid entity ID').
        Vóór HA 2021.x bestond target nog niet — de except vangt dat op en
        valt terug op de oude service_data stijl.
        """
        service_data = dict(data) if data else {}
        target = {"entity_id": entity_id}
        try:
            await self._hass.services.async_call(
                domain, service, service_data, target=target, blocking=False
            )
            return True
        except TypeError:
            # HA < 2021.x: target parameter bestaat niet — fallback op oude stijl
            try:
                legacy_data = {"entity_id": entity_id}
                if data:
                    legacy_data.update(data)
                await self._hass.services.async_call(
                    domain, service, legacy_data, blocking=False
                )
                return True
            except Exception as exc2:
                logger.error("HA service call mislukt (%s.%s → %s): %s", domain, service, entity_id, exc2)
                return False
        except Exception as exc:
            logger.error("HA service call mislukt (%s.%s → %s): %s", domain, service, entity_id, exc)
            return False

    async def health_check(self) -> Tuple[bool, str]:
        """HA is altijd beschikbaar als de coordinator draait."""
        state_count = len(self._hass.states.async_all())
        return True, f"HA OK — {state_count} entities beschikbaar"

    # ── HA-specifieke helpers (alleen beschikbaar voor HA provider) ────────────

    @property
    def latitude(self) -> float:
        return self._hass.config.latitude or 52.78

    @property
    def longitude(self) -> float:
        return self._hass.config.longitude or 6.89   # Emmen als default 😄

    @property
    def time_zone(self) -> str:
        return self._hass.config.time_zone

    def get_config_entries(self):
        return self._hass.config_entries

    def get_hass_data(self, key: str) -> Any:
        return self._hass.data.get(key, {})
