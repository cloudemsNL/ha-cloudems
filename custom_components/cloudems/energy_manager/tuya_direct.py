# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Tuya Direct Provider — v1.0.0

Native Tuya OpenAPI v3 client. Geen afhankelijkheid van
'localtuya', 'tuya_v2' of andere HACS-integraties.

Spreekt de officiële Tuya OpenAPI aan:
  https://openapi.tuyaeu.com/v1.0/  (EU)
  https://openapi.tuyaus.com/v1.0/  (US)

Auth: HMAC-SHA256 signing (Tuya standaard).
      Vereist Tuya IoT Platform account (gratis):
        https://iot.tuya.com/

Wat CloudEMS hiermee doet:
  1. Smart plugs/relais → goedkope-uren schakelaars (vervangt Tuya-integratie dep.)
  2. Energiemeters (power sensors) → verbruiksdata voor NILM
  3. Thermostaten/TRV's → klimaatbeheer
  4. Gordijnmotoren/rolluiken → rolluikbeheer

Werkt als EntityProvider (past in entity_provider.py architectuur):
  provider = TuyaDirectProvider(hass, access_id="...", access_secret="...", region="eu")
  await provider.setup()
  state = await provider.get_state("device_abc123:switch_1")
  await provider.call_service("switch", "turn_on", "device_abc123:switch_1")

Stabiel contract voor cloud-variant:
  Zelfde TuyaDirectProvider werkt los van HA in cloud-variant.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY      = "cloudems_tuya_direct_v1"
STORAGE_VERSION  = 1

TUYA_ENDPOINTS = {
    "eu":  "https://openapi.tuyaeu.com",
    "us":  "https://openapi.tuyaus.com",
    "cn":  "https://openapi.tuyacn.com",
    "in":  "https://openapi.tuyain.com",
}

TOKEN_REFRESH_MARGIN_S = 300
DEVICE_CACHE_TTL_S     = 300    # device-lijst 5 min cachen
STATE_CACHE_TTL_S      = 10     # state 10s cachen (Tuya rate-limits agressief)


# ── DataPoint (DP) mappings per device-type ───────────────────────────────────
# Tuya gebruikt numerieke DP-codes; deze zijn gestandaardiseerd voor gangbare types.
# CloudEMS abstraheert dit naar leesbare namen.

TUYA_DP_MAP: Dict[str, Dict[str, str]] = {
    # Slimme stekker / relais
    "switch": {
        "on_off":     "1",
        "countdown":  "2",
    },
    # Slimme stekker met energiemeting (bijv. Nous A1T, Blitzwolf BW-SHP6)
    "plug_meter": {
        "on_off":     "1",
        "countdown":  "2",
        "power_w":    "19",   # W × 0.1
        "current_ma": "18",   # mA
        "voltage_mv": "20",   # mV × 0.1
        "energy_kwh": "17",   # kWh × 0.01
    },
    # Thermostaat / TRV
    "thermostat": {
        "on_off":           "1",
        "mode":             "2",   # "manual" | "auto" | "eco" | "boost"
        "setpoint_tenths":  "16",  # °C × 10
        "current_temp":     "24",  # °C × 10
        "valve_open":       "36",  # %
    },
    # Gordijnmotor / rolluik
    "curtain": {
        "control":   "1",   # "open" | "close" | "stop"
        "percent":   "3",   # 0–100%
        "direction": "5",   # "forward" | "back"
    },
    # Enkelvoudige schakelaar (geen meter)
    "switch_simple": {
        "on_off": "1",
    },
    # Multi-gang schakelaar (2/3/4 kanalen)
    "switch_2gang": {
        "on_off_1": "1",
        "on_off_2": "2",
    },
    "switch_3gang": {
        "on_off_1": "1",
        "on_off_2": "2",
        "on_off_3": "3",
    },
}

# Omgekeerde mapping: DP-code → naam per type
_REVERSE_DP_MAP: Dict[str, Dict[str, str]] = {
    dev_type: {v: k for k, v in dps.items()}
    for dev_type, dps in TUYA_DP_MAP.items()
}


@dataclass
class TuyaToken:
    access_token:  str  = ""
    refresh_token: str  = ""
    expires_at:    float = 0.0
    uid:           str  = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < (self.expires_at - TOKEN_REFRESH_MARGIN_S)

    def to_dict(self) -> dict:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token,
                "expires_at": self.expires_at, "uid": self.uid}

    @classmethod
    def from_dict(cls, d: dict) -> "TuyaToken":
        return cls(**{k: d[k] for k in ("access_token", "refresh_token", "expires_at", "uid") if k in d})


@dataclass
class TuyaDevice:
    device_id:   str
    name:        str
    product_name:str = ""
    category:    str = ""   # sp=plug, cz=socket, kg=switch, wk=thermostat, cl=curtain
    online:      bool = True
    icon:        str  = ""
    room:        str  = ""
    device_type: str  = ""  # "switch" | "plug_meter" | "thermostat" | "curtain"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("device_id", "name", "product_name", "category", "online", "device_type", "room")}

    @classmethod
    def from_dict(cls, d: dict) -> "TuyaDevice":
        obj = cls(device_id=d.get("device_id",""), name=d.get("name",""))
        for k in ("product_name","category","online","icon","room","device_type"):
            if k in d:
                setattr(obj, k, d[k])
        return obj


class TuyaDirectProvider:
    """
    Native Tuya OpenAPI v3 provider voor CloudEMS.

    Gebruik:
        provider = TuyaDirectProvider(hass, access_id="abc", access_secret="xyz", region="eu")
        await provider.setup()

        # Device discovery
        devices = await provider.async_get_devices()

        # State lezen
        state = await provider.async_get_device_state("device123")
        # → {"on_off": True, "power_w": 850.5, "current_ma": 3726, "voltage_mv": 228400}

        # Schakelen
        await provider.async_set_switch("device123", True)
        await provider.async_set_value("device123", dp_code="setpoint_tenths", value=215)

        # Als EntityProvider:
        entity_state = await provider.get_state("device123:on_off")
        await provider.call_service("switch", "turn_on", "device123:on_off")
    """

    platform     = "tuya_direct"
    display_name = "Tuya OpenAPI (CloudEMS native)"
    icon         = "mdi:cloud-check"

    def __init__(
        self,
        hass,
        access_id:     str,
        access_secret: str,
        region:        str = "eu",
    ) -> None:
        self._hass          = hass
        self._access_id     = access_id
        self._access_secret = access_secret
        self._base_url      = TUYA_ENDPOINTS.get(region, TUYA_ENDPOINTS["eu"])
        self._store         = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._token         = TuyaToken()
        self._session:      Optional[aiohttp.ClientSession] = None
        self._lock          = asyncio.Lock()
        self._device_cache: Dict[str, TuyaDevice] = {}
        self._state_cache:  Dict[str, Tuple[dict, float]] = {}   # device_id → (state, ts)
        self._devices_ts:   float = 0.0
        self._api_ok:       bool  = False
        self._last_error:   str   = ""

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def setup(self) -> bool:
        """Initialiseer provider: laad cache, authenticeer, ontdek devices."""
        try:
            data = await self._store.async_load() or {}
            self._token = TuyaToken.from_dict(data.get("token", {}))
            for d in data.get("devices", []):
                dev = TuyaDevice.from_dict(d)
                self._device_cache[dev.device_id] = dev
            _LOGGER.debug("CloudEMS Tuya: cache geladen (%d devices)", len(self._device_cache))
        except Exception:
            pass

        ok = await self._ensure_token()
        if not ok:
            _LOGGER.error("CloudEMS Tuya Direct: authenticatie mislukt — controleer access_id/secret")
            return False

        # Ververs device-lijst
        devices = await self.async_get_devices(force_refresh=True)
        self._api_ok = True
        _LOGGER.info("CloudEMS Tuya Direct: verbonden, %d devices gevonden", len(devices))
        return True

    async def teardown(self) -> None:
        await self._save()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Device discovery ──────────────────────────────────────────────────────

    async def async_get_devices(self, force_refresh: bool = False) -> List[TuyaDevice]:
        """Haal alle devices op, gecached."""
        if not force_refresh and (time.time() - self._devices_ts) < DEVICE_CACHE_TTL_S:
            return list(self._device_cache.values())

        if not await self._ensure_token():
            return list(self._device_cache.values())

        raw_devices = await self._api_get(f"/v1.3/iot-03/devices?uid={self._token.uid}&page_size=100")
        if raw_devices and raw_devices.get("success"):
            items = raw_devices.get("result", {}).get("list", [])
            for item in items:
                dev = self._parse_device(item)
                self._device_cache[dev.device_id] = dev
            self._devices_ts = time.time()
            await self._save()

        return list(self._device_cache.values())

    async def async_get_device_state(self, device_id: str) -> Dict[str, Any]:
        """
        Haal device state op, genormaliseerd naar leesbare namen.

        Returns bijv.:
            {"on_off": True, "power_w": 850.5, "current_ma": 3726}
        """
        # Check cache
        cached = self._state_cache.get(device_id)
        if cached and (time.time() - cached[1]) < STATE_CACHE_TTL_S:
            return cached[0]

        if not await self._ensure_token():
            return {}

        resp = await self._api_get(f"/v1.0/iot-03/devices/{device_id}/status")
        if not resp or not resp.get("success"):
            return {}

        dps = resp.get("result", [])
        dev = self._device_cache.get(device_id)
        dev_type = dev.device_type if dev else ""

        state = self._normalize_dps(dps, dev_type)
        self._state_cache[device_id] = (state, time.time())
        return state

    # ── Schakelaar ────────────────────────────────────────────────────────────

    async def async_set_switch(self, device_id: str, on: bool, channel: int = 1) -> bool:
        """
        Schakel een Tuya switch aan/uit.

        Args:
            device_id: Tuya device ID
            on: True = aan, False = uit
            channel: 1 = kanaal 1, 2 = kanaal 2 (multi-gang)
        """
        dp_code = "1" if channel == 1 else str(channel)
        return await self._send_command(device_id, [{
            "code":  dp_code,
            "value": on,
        }])

    async def async_set_value(self, device_id: str, dp_name: str, value: Any,
                               dev_type: str = "") -> bool:
        """
        Stel een DP-waarde in op naam.

        Voorbeeld: async_set_value("abc", "setpoint_tenths", 215)
        """
        dp_code = self._dp_name_to_code(dp_name, dev_type)
        if dp_code is None:
            dp_code = dp_name  # probeer als directe DP-code
        return await self._send_command(device_id, [{"code": dp_code, "value": value}])

    # ── EntityProvider interface (voor entity_provider.py integratie) ─────────

    async def get_state(self, entity_id: str):
        """
        EntityProvider.get_state() compatibel.
        entity_id formaat: "device123:dp_name" (bijv. "device123:on_off")
        """
        device_id, dp_name = self._parse_entity_id(entity_id)
        state = await self.async_get_device_state(device_id)
        value = state.get(dp_name)
        if value is None:
            return None
        from .entity_provider import EntityState   # lazy import
        return EntityState(
            entity_id  = entity_id,
            state      = str(value),
            attributes = state,
            available  = True,
        )

    async def get_all_of_domain(self, domain: str) -> list:
        """Haal alle Tuya devices terug als EntityState lijst voor een domein."""
        devices = await self.async_get_devices()
        result  = []
        from .entity_provider import EntityState
        for dev in devices:
            if domain == "switch" and dev.device_type in ("switch", "plug_meter", "switch_simple"):
                result.append(EntityState(
                    entity_id  = f"{dev.device_id}:on_off",
                    state      = "on" if dev.online else "off",
                    attributes = dev.to_dict(),
                    available  = dev.online,
                ))
            elif domain == "climate" and dev.device_type == "thermostat":
                state = await self.async_get_device_state(dev.device_id)
                temp  = state.get("current_temp", 0)
                result.append(EntityState(
                    entity_id  = f"{dev.device_id}:climate",
                    state      = str(temp / 10.0) if temp else "unknown",
                    attributes = {**dev.to_dict(), **state},
                    available  = dev.online,
                ))
            elif domain == "cover" and dev.device_type == "curtain":
                state = await self.async_get_device_state(dev.device_id)
                result.append(EntityState(
                    entity_id  = f"{dev.device_id}:cover",
                    state      = state.get("control", "stop"),
                    attributes = {**dev.to_dict(), **state},
                    available  = dev.online,
                ))
        return result

    async def call_service(self, domain: str, service: str, entity_id: str,
                            data: Optional[dict] = None) -> bool:
        device_id, _ = self._parse_entity_id(entity_id)
        if domain == "switch":
            on = service in ("turn_on", "toggle")
            return await self.async_set_switch(device_id, on)
        elif domain == "climate" and service == "set_temperature":
            temp_c  = float((data or {}).get("temperature", 20))
            tenths  = int(temp_c * 10)
            return await self.async_set_value(device_id, "setpoint_tenths", tenths, "thermostat")
        elif domain == "cover":
            ctrl = "open" if service == "open_cover" else ("close" if service == "close_cover" else "stop")
            return await self.async_set_value(device_id, "control", ctrl, "curtain")
        return False

    async def health_check(self) -> Tuple[bool, str]:
        ok = await self._ensure_token()
        return ok, "Tuya Direct OK" if ok else f"Tuya auth mislukt: {self._last_error}"

    def get_status(self) -> dict:
        return {
            "tuya_direct_ok":      self._api_ok,
            "tuya_direct_devices": len(self._device_cache),
            "tuya_direct_region":  self._base_url,
            "tuya_token_valid":    self._token.is_valid,
            "tuya_last_error":     self._last_error,
        }

    # ── Interne API ───────────────────────────────────────────────────────────

    async def _ensure_token(self) -> bool:
        async with self._lock:
            if self._token.is_valid:
                return True
            ok = await self._fetch_token()
            if ok:
                await self._save()
            return ok

    async def _fetch_token(self) -> bool:
        """Haal nieuw access token op (geen refresh in Tuya OpenAPI v1.0)."""
        ts      = str(int(time.time() * 1000))
        sign    = self._sign_token_request(ts)
        headers = {
            "client_id":  self._access_id,
            "sign":       sign,
            "t":          ts,
            "sign_method":"HMAC-SHA256",
            "nonce":      str(uuid.uuid4()),
        }
        try:
            async with self._get_session() as session:
                async with session.get(
                    f"{self._base_url}/v1.0/token?grant_type=1",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data   = await resp.json()
                        result = data.get("result", {})
                        self._token = TuyaToken(
                            access_token  = result.get("access_token", ""),
                            refresh_token = result.get("refresh_token", ""),
                            expires_at    = time.time() + result.get("expire_time", 7200),
                            uid           = result.get("uid", ""),
                        )
                        return bool(self._token.access_token)
                    else:
                        body = await resp.text()
                        self._last_error = f"Token {resp.status}: {body[:200]}"
                        _LOGGER.error("CloudEMS Tuya: token ophalen mislukt %d: %s", resp.status, body[:200])
                        return False
        except Exception as exc:
            self._last_error = str(exc)
            _LOGGER.error("CloudEMS Tuya: token exception: %s", exc)
            return False

    async def _send_command(self, device_id: str, commands: List[dict]) -> bool:
        """Stuur één of meer DP-commando's naar een device."""
        if not await self._ensure_token():
            return False
        resp = await self._api_post(
            f"/v1.0/iot-03/devices/{device_id}/commands",
            {"commands": commands}
        )
        ok = resp and resp.get("success", False) if resp else False
        if ok:
            # Invalideer state cache
            self._state_cache.pop(device_id, None)
        return ok

    async def _api_get(self, path: str) -> Optional[dict]:
        if not self._token.access_token:
            return None
        try:
            ts      = str(int(time.time() * 1000))
            headers = self._make_headers("GET", path, ts, "")
            async with self._get_session() as session:
                async with session.get(
                    f"{self._base_url}{path}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 401:
                        self._token.access_token = ""
                        return None
                    return None
        except Exception as exc:
            _LOGGER.debug("CloudEMS Tuya GET %s: %s", path, exc)
            return None

    async def _api_post(self, path: str, body: dict) -> Optional[dict]:
        if not self._token.access_token:
            return None
        try:
            body_str = json.dumps(body, separators=(",", ":"))
            ts       = str(int(time.time() * 1000))
            headers  = self._make_headers("POST", path, ts, body_str)
            async with self._get_session() as session:
                async with session.post(
                    f"{self._base_url}{path}",
                    headers=headers,
                    data=body_str,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    return None
        except Exception as exc:
            _LOGGER.debug("CloudEMS Tuya POST %s: %s", path, exc)
            return None

    # ── Request signing (Tuya HMAC-SHA256) ────────────────────────────────────

    def _sign_token_request(self, ts: str) -> str:
        """Signing voor token request (zonder access token)."""
        string_to_sign = self._access_id + ts
        return hmac.new(
            self._access_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    def _make_headers(self, method: str, path: str, ts: str, body_str: str) -> dict:
        """Maak gesigneerde headers voor Tuya OpenAPI request."""
        content_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
        # Path zonder query string voor signing
        path_no_query = path.split("?")[0]
        string_to_sign = "\n".join([method, content_hash, "", path_no_query])
        nonce   = str(uuid.uuid4())
        msg     = self._access_id + self._token.access_token + ts + nonce + string_to_sign
        sign    = hmac.new(
            self._access_secret.encode("utf-8"),
            msg.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        return {
            "client_id":   self._access_id,
            "access_token":self._token.access_token,
            "sign":        sign,
            "sign_method": "HMAC-SHA256",
            "t":           ts,
            "nonce":       nonce,
            "Content-Type":"application/json",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_device(self, item: dict) -> TuyaDevice:
        category  = item.get("category", "")
        dev_type  = self._category_to_type(category)
        return TuyaDevice(
            device_id    = item.get("id", ""),
            name         = item.get("name", ""),
            product_name = item.get("product_name", ""),
            category     = category,
            online       = item.get("online", True),
            icon         = item.get("icon", ""),
            room         = item.get("room_name", ""),
            device_type  = dev_type,
        )

    def _category_to_type(self, category: str) -> str:
        """Tuya categorie-code → CloudEMS device type."""
        mapping = {
            "sp":  "plug_meter",    # smart plug met energiemeting
            "cz":  "plug_meter",    # socket
            "kg":  "switch",        # schakelaar
            "pc":  "switch",        # power strip
            "wk":  "thermostat",    # thermostaat
            "wkf": "thermostat",    # WiFi thermostaat
            "cl":  "curtain",       # gordijn/rolluik
            "clkg":"curtain",       # gordijn schakelaar
            "ckmv":"curtain",       # gordijnmotor
            "mcs": "switch_simple", # enkelvoudige schakelaar
        }
        return mapping.get(category, "switch_simple")

    def _normalize_dps(self, dps: List[dict], dev_type: str) -> Dict[str, Any]:
        """Normaliseer Tuya DP-lijst naar leesbaar dict."""
        result    = {}
        rev_map   = _REVERSE_DP_MAP.get(dev_type, {})

        for dp in dps:
            code  = str(dp.get("code", dp.get("dpId", "")))
            value = dp.get("value")

            # Vertaal naar leesbare naam
            name = rev_map.get(code, code)
            result[name] = value

            # Speciale eenheidsconversies
            if name == "power_w" and value is not None:
                result["power_w"] = float(value) / 10.0      # ×0.1
            elif name == "setpoint_tenths" and value is not None:
                result["setpoint_c"] = float(value) / 10.0   # °C
            elif name == "current_temp" and value is not None:
                result["current_temp_c"] = float(value) / 10.0
            elif name == "voltage_mv" and value is not None:
                result["voltage_v"] = float(value) / 10.0

        return result

    def _dp_name_to_code(self, name: str, dev_type: str = "") -> Optional[str]:
        """Leesbare DP-naam → DP-code."""
        if dev_type and dev_type in TUYA_DP_MAP:
            code = TUYA_DP_MAP[dev_type].get(name)
            if code:
                return code
        # Zoek in alle types
        for dps in TUYA_DP_MAP.values():
            if name in dps:
                return dps[name]
        return None

    def _parse_entity_id(self, entity_id: str) -> Tuple[str, str]:
        """Parse "device123:dp_name" → ("device123", "dp_name")."""
        if ":" in entity_id:
            parts = entity_id.split(":", 1)
            return parts[0], parts[1]
        return entity_id, "on_off"

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "token":   self._token.to_dict(),
                "devices": [d.to_dict() for d in self._device_cache.values()],
            })
        except Exception:
            pass
