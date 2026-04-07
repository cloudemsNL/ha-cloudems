# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS / AdaptiveHome (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CloudEMS — AdaptiveHome Bridge
================================

Koppellaag tussen CloudEMS (lokale agent) en AdaptiveHome (cloud platform).

Architectuur:
    CloudEMS ──► HA event bus ──► AdaptiveHome      (lokale HA-koppeling)
    CloudEMS ──► REST/WebSocket ──► AdaptiveHome     (cloud koppeling)

De bridge werkt in drie lagen:

  1. LOKAAL (altijd actief):
     CloudEMS vuurt HA events → AdaptiveHome local listener pikt ze op.
     Werkt zonder internet, zonder licentie.

  2. CLOUD (actief als hosted_enabled=True + geldig token):
     CloudEMS pusht data naar AdaptiveHome REST API elke cyclus.
     AdaptiveHome stuurt cloud-beslissingen terug via webhook of polling.
     Beslissingen overschrijven lokale logica per evaluate-methode.

  3. FALLBACK (bij cloud-uitval):
     Bridge buffert uitgaande data lokaal (SQLite-lite via HA Store).
     CloudEMS draait volledig lokaal met laatste bekende cloud-beslissingen.
     Zodra cloud bereikbaar is: buffer wordt alsnog gestuurd (backfill).

Beslissings-override mechanisme:
    AdaptiveHome kan per evaluate-methode een beslissing sturen:
      { "method": "_evaluate_solar", "result": {...}, "expires": <ts> }
    De coordinator checkt self._cloud_decisions vóór lokale logica.
    Verlopen beslissingen (>300s) worden genegeerd → lokale fallback.

Events die CloudEMS vuurt (luister ernaar in AdaptiveHome):
    cloudems_state_update       — energiestatus elke 10s
    cloudems_nilm_update        — NILM apparaten gewijzigd
    cloudems_price_update       — EPEX prijzen bijgewerkt
    cloudems_presence_update    — aanwezigheid gewijzigd

Events die AdaptiveHome kan sturen (CloudEMS luistert):
    adaptivehome_occupancy      — bezetting per kamer
    adaptivehome_mode           — huismodus (home/away/sleep/vacation)
    adaptivehome_scene          — scène geactiveerd (morning/evening/etc.)
    adaptivehome_decision       — cloud-beslissing voor een evaluate-methode

Sensors:
    sensor.cloudems_ah_status   — koppelstatus + licentieniveau
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_LOGGER = logging.getLogger("cloudems.adaptivehome")

# ── Event namen ───────────────────────────────────────────────────────────────

EVENT_CLOUDEMS_STATE     = "cloudems_state_update"
EVENT_CLOUDEMS_NILM      = "cloudems_nilm_update"
EVENT_CLOUDEMS_PRICE     = "cloudems_price_update"
EVENT_CLOUDEMS_PRESENCE  = "cloudems_presence_update"

EVENT_AH_OCCUPANCY  = "adaptivehome_occupancy"
EVENT_AH_MODE       = "adaptivehome_mode"
EVENT_AH_SCENE      = "adaptivehome_scene"
EVENT_AH_DECISION   = "adaptivehome_decision"   # nieuw: cloud-beslissing override

# ── Licentieniveaus ───────────────────────────────────────────────────────────

class LicenseLevel:
    NONE       = "none"        # CloudEMS zonder AdaptiveHome
    CLOUDEMS   = "cloudems"    # CloudEMS standalone
    AH_BASIC   = "ah_basic"    # AdaptiveHome zonder CloudEMS
    BUNDLE     = "bundle"      # Beide + korting — volledige functionaliteit
    ENTERPRISE = "enterprise"  # Installateur / VvE / woningcorporatie

# ── Huismodus waarden ─────────────────────────────────────────────────────────

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
    license_level:     str = LicenseLevel.CLOUDEMS
    license_valid:     bool = True
    license_expires:   Optional[float] = None
    # Cloud koppeling
    hosted_url:        str = ""
    hosted_token:      str = ""
    hosted_enabled:    bool = False
    # Offline buffer status
    buffer_size:       int = 0
    last_backfill_ts:  float = 0.0


@dataclass
class CloudDecision:
    """Een beslissing ontvangen van de AdaptiveHome cloud."""
    method:    str          # bijv. "_evaluate_solar"
    result:    dict         # de beslissing zelf
    received:  float        # timestamp ontvangst
    expires:   float        # timestamp vervaldatum (default: +300s)
    source:    str = "cloud"

    def is_valid(self) -> bool:
        return time.time() < self.expires


class AdaptiveHomeBridge:
    """
    Brug tussen CloudEMS coordinator en AdaptiveHome cloud platform.

    Gebruik:
        bridge = AdaptiveHomeBridge(hass, coordinator)
        await bridge.async_setup()
        bridge.async_shutdown()  # bij unload
    """

    # Maximale buffer: 7 dagen × 6 metingen/min × 60min × 24h × ~300 bytes ≈ 18MB
    _BUFFER_MAX_SIZE = 50_000  # metingen
    _DECISION_TTL    = 300     # seconden — hoe lang een cloud-beslissing geldig is
    _PUSH_INTERVAL   = 10      # seconden — hoe vaak data naar cloud gestuurd wordt

    def __init__(self, hass, coordinator) -> None:
        self._hass        = hass
        self._coord       = coordinator
        self._state       = AdaptiveHomeState()
        self._unsubs:     List[Callable] = []
        self._last_fire:  Dict[str, float] = {}
        self._setup_done: bool = False

        # Cloud-beslissingen per evaluate-methode
        # coordinator checkt deze vóór lokale logica
        self._cloud_decisions: Dict[str, CloudDecision] = {}

        # Offline buffer: lijst van (timestamp, payload_dict)
        self._outbox:     List[tuple] = []

        self._occupancy_cb: Optional[Callable] = None
        self._mode_cb:      Optional[Callable] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Registreer event listeners."""
        if self._setup_done:
            return

        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_OCCUPANCY, self._on_ah_occupancy)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_MODE, self._on_ah_mode)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_SCENE, self._on_ah_scene)
        )
        self._unsubs.append(
            self._hass.bus.async_listen(EVENT_AH_DECISION, self._on_ah_decision)
        )

        self._setup_done = True
        _LOGGER.debug("AdaptiveHome bridge: klaar")

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()
        self._setup_done = False

    # ── Cloud-beslissing API (gebruikt door coordinator) ──────────────────────

    def get_cloud_decision(self, method: str) -> Optional[dict]:
        """
        Geef cloud-beslissing terug als die geldig is, anders None.

        Gebruik in elke _evaluate_* methode:
            override = self._ah_bridge.get_cloud_decision("_evaluate_solar")
            if override is not None:
                return override  # sla lokale logica over
        """
        decision = self._cloud_decisions.get(method)
        if decision is None:
            return None
        if not decision.is_valid():
            del self._cloud_decisions[method]
            _LOGGER.debug("Cloud-beslissing %s verlopen — lokale fallback", method)
            return None
        return decision.result

    def has_active_cloud_decisions(self) -> bool:
        """True als er geldige cloud-beslissingen zijn voor minstens één methode."""
        return any(d.is_valid() for d in self._cloud_decisions.values())

    def clear_cloud_decisions(self) -> None:
        """Wis alle cloud-beslissingen (bijv. bij cloud-uitval of herstart)."""
        self._cloud_decisions.clear()

    # ── Events → AdaptiveHome ─────────────────────────────────────────────────

    def fire_state_update(self, data: dict) -> None:
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
            "nilm_devices":  len(data.get("nilm_devices", [])),
            "ts":            now,
            "_source":       "cloudems",
            "_version":      data.get("_version", ""),
            "_license":      self._state.license_level,
        }

        # Stuur lokaal via HA event bus
        self._hass.bus.async_fire(EVENT_CLOUDEMS_STATE, payload)

        # Voeg toe aan outbox voor cloud push
        self._enqueue(payload)

    def fire_nilm_update(self, devices: list) -> None:
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_NILM, 0) < 30:
            return
        self._last_fire[EVENT_CLOUDEMS_NILM] = now

        payload = {
            "devices": [
                {
                    "name":      d.get("name", ""),
                    "type":      d.get("device_type", ""),
                    "phase":     d.get("phase", ""),
                    "power_w":   d.get("current_power", d.get("power_w", 0)),
                    "is_on":     d.get("is_on", False),
                    "confirmed": d.get("confirmed", False),
                    "room":      d.get("room", ""),
                }
                for d in devices
                if not d.get("user_hidden") and not d.get("user_suppressed")
            ],
            "ts":      now,
            "_source": "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_NILM, payload)

    def fire_price_update(self, price_info: dict) -> None:
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_PRICE, 0) < 300:
            return
        self._last_fire[EVENT_CLOUDEMS_PRICE] = now

        payload = {
            "current_eur_kwh": price_info.get("current_price_eur_kwh"),
            "all_in_eur_kwh":  price_info.get("all_in_price_eur_kwh"),
            "tariff_group":    price_info.get("tariff_group", "unknown"),
            "today_prices":    price_info.get("today_prices", []),
            "in_cheapest_2h":  price_info.get("in_cheapest_2h", False),
            "in_cheapest_4h":  price_info.get("in_cheapest_4h", False),
            "ts":              now,
            "_source":         "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_PRICE, payload)

    def fire_presence_update(self, present: bool, method: str = "power") -> None:
        now = time.time()
        if now - self._last_fire.get(EVENT_CLOUDEMS_PRESENCE, 0) < 30:
            return
        self._last_fire[EVENT_CLOUDEMS_PRESENCE] = now

        payload = {
            "present":    present,
            "method":     method,
            "house_mode": self._state.house_mode,
            "ts":         now,
            "_source":    "cloudems",
        }
        self._hass.bus.async_fire(EVENT_CLOUDEMS_PRESENCE, payload)

    # ── Events ← AdaptiveHome ─────────────────────────────────────────────────

    async def _on_ah_occupancy(self, event) -> None:
        data  = event.data or {}
        rooms = data.get("occupied_rooms", [])
        self._state.occupied_rooms = rooms
        self._state.last_seen      = time.time()
        self._state.connected      = True
        if hasattr(self._coord, "_ah_occupied_rooms"):
            self._coord._ah_occupied_rooms = rooms

    async def _on_ah_mode(self, event) -> None:
        data = event.data or {}
        mode = data.get("mode", HouseMode.HOME)
        self._state.house_mode = mode
        self._state.last_seen  = time.time()
        self._state.connected  = True
        _LOGGER.info("AdaptiveHome huismodus → %s", mode)
        if hasattr(self._coord, "_ah_house_mode"):
            self._coord._ah_house_mode = mode

    async def _on_ah_scene(self, event) -> None:
        data  = event.data or {}
        scene = data.get("scene", "")
        self._state.active_scene = scene
        self._state.last_seen    = time.time()
        self._state.connected    = True
        if hasattr(self._coord, "_ah_active_scene"):
            self._coord._ah_active_scene = scene

    async def _on_ah_decision(self, event) -> None:
        """
        AdaptiveHome stuurt een cloud-beslissing voor een evaluate-methode.

        Payload: {
            "method":  "_evaluate_solar",   # welke methode
            "result":  {...},                # de beslissing
            "ttl":     300,                  # geldigheid in seconden
        }
        """
        data   = event.data or {}
        method = data.get("method", "")
        result = data.get("result")
        ttl    = float(data.get("ttl", self._DECISION_TTL))

        if not method or result is None:
            _LOGGER.warning("AdaptiveHome beslissing ontvangen zonder methode/result — genegeerd")
            return

        now = time.time()
        self._cloud_decisions[method] = CloudDecision(
            method   = method,
            result   = result,
            received = now,
            expires  = now + ttl,
        )
        self._state.last_seen = now
        self._state.connected = True

        _LOGGER.debug("Cloud-beslissing ontvangen voor %s (TTL %ds)", method, int(ttl))

    # ── Cloud push + offline buffer ───────────────────────────────────────────

    def _enqueue(self, payload: dict) -> None:
        """Voeg payload toe aan outbox voor cloud-push."""
        if not self._state.hosted_enabled:
            return
        self._outbox.append((time.time(), payload))
        # Houd buffer binnen limiet — gooi oudste weg
        if len(self._outbox) > self._BUFFER_MAX_SIZE:
            self._outbox = self._outbox[-self._BUFFER_MAX_SIZE:]
        self._state.buffer_size = len(self._outbox)

    async def async_push_to_cloud(self) -> None:
        """
        Push gebufferde data naar AdaptiveHome cloud.
        Wordt periodiek aangeroepen vanuit de coordinator.

        Bij succes: buffer leeggemaakt.
        Bij fout: buffer bewaard voor volgende poging (backfill).
        """
        if not self._state.hosted_enabled or not self._state.hosted_url:
            return
        if not self._outbox:
            return

        try:
            import aiohttp
        except ImportError:
            _LOGGER.warning("aiohttp niet beschikbaar — cloud push overgeslagen")
            return

        batch  = list(self._outbox)  # snapshot
        url    = self._state.hosted_url.rstrip("/") + "/api/v1/ingest"
        token  = self._state.hosted_token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json  = {"batch": batch, "source": "cloudems"},
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type":  "application/json",
                    },
                    timeout = aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 201, 202):
                        self._outbox.clear()
                        self._state.buffer_size     = 0
                        self._state.last_backfill_ts = time.time()
                        _LOGGER.debug("Cloud push: %d metingen gestuurd", len(batch))
                    elif resp.status == 401:
                        _LOGGER.warning("Cloud push: ongeldige token — push gestopt")
                        self._state.hosted_enabled = False
                    else:
                        _LOGGER.debug("Cloud push fout %d — bewaard voor backfill", resp.status)
        except Exception as err:
            _LOGGER.debug("Cloud push fout: %s — bewaard voor backfill", err)

    def configure_cloud(
        self,
        url:     str,
        token:   str,
        enabled: bool = True,
        license_level: str = LicenseLevel.CLOUDEMS,
    ) -> None:
        """
        Configureer de cloud-koppeling vanuit coordinator/config_flow.
        Wordt aangeroepen bij setup en bij config-wijziging.
        """
        self._state.hosted_url     = url
        self._state.hosted_token   = token
        self._state.hosted_enabled = enabled and bool(url) and bool(token)
        self._state.license_level  = license_level
        _LOGGER.info(
            "AdaptiveHome cloud: %s (licentie: %s)",
            "actief" if self._state.hosted_enabled else "uitgeschakeld",
            license_level,
        )

    # ── Status API ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        age = time.time() - self._state.last_seen if self._state.last_seen else None
        active_decisions = [
            {"method": k, "expires_in": round(d.expires - time.time())}
            for k, d in self._cloud_decisions.items()
            if d.is_valid()
        ]
        return {
            "connected":          self._state.connected and (age is not None and age < 120),
            "last_seen_s":        round(age) if age is not None else None,
            "house_mode":         self._state.house_mode,
            "occupied_rooms":     self._state.occupied_rooms,
            "active_scene":       self._state.active_scene,
            "hosted_enabled":     self._state.hosted_enabled,
            "license_level":      self._state.license_level,
            "license_valid":      self._state.license_valid,
            "buffer_size":        self._state.buffer_size,
            "last_backfill_ts":   self._state.last_backfill_ts or None,
            "active_decisions":   active_decisions,
            "ah_version":         self._state.ah_version,
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

    @property
    def license_level(self) -> str:
        return self._state.license_level

    @property
    def cloud_enabled(self) -> bool:
        return self._state.hosted_enabled
