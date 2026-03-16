# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CloudEMS — AdaptiveHome Bridge
================================

Koppellaag tussen CloudEMS en AdaptiveHome (SelfLearningHomeAssistantCard).
Werkt zowel met de lokale HA-variant als de toekomstige hosted variant.

Architectuur:
    CloudEMS ──► HA event bus ──► AdaptiveHome      (lokale koppeling)
    CloudEMS ──► REST/WebSocket ──► AdaptiveHome     (hosted koppeling, toekomst)

Events die CloudEMS vuurt (luister ernaar in AdaptiveHome):
    cloudems_state_update       — energiestatus elke 10s
    cloudems_nilm_update        — NILM apparaten gewijzigd
    cloudems_price_update       — EPEX prijzen bijgewerkt
    cloudems_presence_update    — aanwezigheid gewijzigd

Events die AdaptiveHome kan sturen (CloudEMS luistert):
    adaptivehome_occupancy      — bezetting per kamer
    adaptivehome_mode           — huismodus (home/away/sleep/vacation)
    adaptivehome_scene          — scène geactiveerd (morning/evening/etc.)

Sensors die CloudEMS deelt via HA state:
    sensor.cloudems_ah_status   — koppelstatus (enkel zichtbaar als AH actief)

v4.6.276: Eerste versie — alleen infrastructuur, geen zichtbare UI voor bestaande gebruikers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_LOGGER = logging.getLogger("cloudems.adaptivehome")

# ── Event namen ───────────────────────────────────────────────────────────────

# CloudEMS → AdaptiveHome
EVENT_CLOUDEMS_STATE     = "cloudems_state_update"
EVENT_CLOUDEMS_NILM      = "cloudems_nilm_update"
EVENT_CLOUDEMS_PRICE     = "cloudems_price_update"
EVENT_CLOUDEMS_PRESENCE  = "cloudems_presence_update"

# AdaptiveHome → CloudEMS
EVENT_AH_OCCUPANCY = "adaptivehome_occupancy"
EVENT_AH_MODE      = "adaptivehome_mode"
EVENT_AH_SCENE     = "adaptivehome_scene"

# ── Huismodus waarden (gedeeld vocabulaire) ───────────────────────────────────

class HouseMode:
    HOME     = "home"
    AWAY     = "away"
    SLEEP    = "sleep"
    VACATION = "vacation"
    MORNING  = "morning"
    EVENING  = "evening"


@dataclass
class AdaptiveHomeState:
    """Huidige staat van de AdaptiveHome koppeling."""
    connected:         bool = False
    last_seen:         float = 0.0
    house_mode:        str = HouseMode.HOME
    occupied_rooms:    List[str] = field(default_factory=list)
    active_scene:      str = ""
    ah_version:        str = ""
    # Toekomst: hosted variant
    hosted_url:        str = ""
    hosted_token:      str = ""
    hosted_enabled:    bool = False


class AdaptiveHomeBridge:
    """
    Brug tussen CloudEMS coordinator en AdaptiveHome.

    Gebruik:
        bridge = AdaptiveHomeBridge(hass, coordinator)
        await bridge.async_setup()
        # bridge.async_shutdown() bij unload
    """

    def __init__(self, hass, coordinator) -> None:
        self._hass        = hass
        self._coord       = coordinator
        self._state       = AdaptiveHomeState()
        self._unsubs:     List[Callable] = []
        self._last_fire:  Dict[str, float] = {}
        self._setup_done: bool = False

        # Callbacks die AdaptiveHome kan registreren via CloudEMS services
        self._occupancy_cb: Optional[Callable] = None
        self._mode_cb:      Optional[Callable] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Registreer event listeners voor AdaptiveHome events."""
        if self._setup_done:
            return

        # Luister naar events van AdaptiveHome
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_OCCUPANCY, self._on_ah_occupancy)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_MODE, self._on_ah_mode)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_SCENE, self._on_ah_scene)
        )

        self._setup_done = True
        _LOGGER.debug("CloudEMS AdaptiveHome bridge: klaar voor koppeling")

    async def async_shutdown(self) -> None:
        """Ruim listeners op bij unload."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        self._setup_done = False

    # ── Events → AdaptiveHome ─────────────────────────────────────────────────

    def fire_state_update(self, data: dict) -> None:
        """
        Stuur energiestatus naar AdaptiveHome elke coordinator-cyclus.
        Throttled op 10s (gelijk aan coordinator interval).
        """
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_STATE, 0) < 9.5:
            return
        self._last_fire[EVENT_CLOUDEMS_STATE] = now

        payload = {
            "solar_w":       data.get("solar_power", 0.0),
            "grid_w":        data.get("grid_power", 0.0),
            "battery_w":     data.get("battery_power", 0.0),
            "house_w":       data.get("house_power", 0.0),
            "battery_soc":   data.get("battery_soc_pct"),
            "pv_surplus_w":  data.get("solar_surplus_w", 0.0),
            "presence":      data.get("presence_detected", False),
            "house_mode":    self._state.house_mode,
            "price_eur_kwh": data.get("current_price_eur_kwh"),
            "ts":            now,
            "_source":       "cloudems",
            "_version":      data.get("_version", ""),
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_STATE, payload)

    def fire_nilm_update(self, devices: list) -> None:
        """Stuur NILM apparatenlijst naar AdaptiveHome als die wijzigt."""
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_NILM, 0) < 30:
            return
        self._last_fire[EVENT_CLOUDEMS_NILM] = now

        payload = {
            "devices": [
                {
                    "name":       d.get("name", ""),
                    "type":       d.get("device_type", ""),
                    "phase":      d.get("phase", ""),
                    "power_w":    d.get("current_power", d.get("power_w", 0)),
                    "is_on":      d.get("is_on", False),
                    "confirmed":  d.get("confirmed", False),
                    "room":       d.get("room", ""),
                }
                for d in devices
                if not d.get("user_hidden") and not d.get("user_suppressed")
            ],
            "ts":      now,
            "_source": "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_NILM, payload)

    def fire_price_update(self, price_info: dict) -> None:
        """Stuur EPEX prijsinfo naar AdaptiveHome als die wijzigt."""
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_PRICE, 0) < 300:
            return
        self._last_fire[EVENT_CLOUDEMS_PRICE] = now

        payload = {
            "current_eur_kwh":  price_info.get("current_price_eur_kwh"),
            "all_in_eur_kwh":   price_info.get("all_in_price_eur_kwh"),
            "tariff_group":     price_info.get("tariff_group", "unknown"),
            "today_prices":     price_info.get("today_prices", []),
            "in_cheapest_2h":   price_info.get("in_cheapest_2h", False),
            "in_cheapest_4h":   price_info.get("in_cheapest_4h", False),
            "ts":               now,
            "_source":          "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_PRICE, payload)

    def fire_presence_update(self, present: bool, method: str = "power") -> None:
        """Stuur aanwezigheidswijziging naar AdaptiveHome."""
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_PRESENCE, 0) < 30:
            return
        self._last_fire[EVENT_CLOUDEMS_PRESENCE] = now

        payload = {
            "present":     present,
            "method":      method,   # "power" | "phone" | "sensor" | "ah"
            "house_mode":  self._state.house_mode,
            "ts":          now,
            "_source":     "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_PRESENCE, payload)

    # ── Events ← AdaptiveHome ─────────────────────────────────────────────────

    async def _on_ah_occupancy(self, event) -> None:
        """AdaptiveHome meldt bezetting per kamer."""
        data = event.data or {}
        rooms = data.get("occupied_rooms", [])
        self._state.occupied_rooms = rooms
        self._state.last_seen = time.time()
        self._state.connected = True

        _LOGGER.debug(
            "CloudEMS AdaptiveHome: bezetting ontvangen — kamers: %s",
            ", ".join(rooms) if rooms else "geen",
        )

        # Propageer naar coordinator zodat boiler/EV sturing dit kan gebruiken
        if hasattr(self._coord, "_ah_occupied_rooms"):
            self._coord._ah_occupied_rooms = rooms

    async def _on_ah_mode(self, event) -> None:
        """AdaptiveHome meldt huismodus (home/away/sleep/vacation)."""
        data = event.data or {}
        mode = data.get("mode", HouseMode.HOME)
        prev = self._state.house_mode
        self._state.house_mode = mode
        self._state.last_seen  = time.time()
        self._state.connected  = True

        _LOGGER.info(
            "CloudEMS AdaptiveHome: huismodus %s → %s",
            prev, mode,
        )

        # Propageer naar coordinator
        if hasattr(self._coord, "_ah_house_mode"):
            self._coord._ah_house_mode = mode

        # Hint aan coordinator dat er iets veranderd is
        if hasattr(self._coord, "_valuesChanged"):
            pass  # coordinator pikt het op via _ah_house_mode

    async def _on_ah_scene(self, event) -> None:
        """AdaptiveHome meldt actieve scène (morning/evening/dinner/etc.)."""
        data = event.data or {}
        scene = data.get("scene", "")
        self._state.active_scene = scene
        self._state.last_seen    = time.time()
        self._state.connected    = True

        _LOGGER.debug("CloudEMS AdaptiveHome: scène → %s", scene)

        if hasattr(self._coord, "_ah_active_scene"):
            self._coord._ah_active_scene = scene

    # ── Status API ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Koppelstatus voor sensor/diagnostiek."""
        age = time.time() - self._state.last_seen if self._state.last_seen else None
        return {
            "connected":        self._state.connected and (age is not None and age < 120),
            "last_seen_s":      round(age) if age is not None else None,
            "house_mode":       self._state.house_mode,
            "occupied_rooms":   self._state.occupied_rooms,
            "active_scene":     self._state.active_scene,
            "hosted_enabled":   self._state.hosted_enabled,
            "ah_version":       self._state.ah_version,
            "events_fired":     {k: round(v) for k, v in self._last_fire.items()},
        }

    @property
    def house_mode(self) -> str:
        return self._state.house_mode

    @property
    def occupied_rooms(self) -> List[str]:
        return self._state.occupied_rooms

    @property
    def is_connected(self) -> bool:
        age = time.time() - self._state.last_seen if self._state.last_seen else None
        return self._state.connected and age is not None and age < 120

    # ── Toekomst: hosted variant ──────────────────────────────────────────────

    async def async_push_to_hosted(self, payload: dict) -> None:
        """
        Toekomst: push data naar de hosted AdaptiveHome variant.
        Nog niet geïmplementeerd — placeholder voor cloud migratie.
        """
        if not self._state.hosted_enabled or not self._state.hosted_url:
            return
        # TODO: aiohttp POST naar self._state.hosted_url met Bearer token
        _LOGGER.debug("AdaptiveHome hosted push: nog niet geïmplementeerd")
