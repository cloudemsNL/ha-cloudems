# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Provider Base  v1.0.0
================================
Gemeenschappelijke basisklassen voor alle externe CloudEMS providers.

Elk provider-bestand:
  1. Implementeert CloudEMSProvider
  2. Registreert zichzelf via @register_provider("id")
  3. Bevat UPDATE_HINTS met links naar de officiële API-docs + HA community repos
     zodat je bij API-wijzigingen precies weet waar je moet kijken

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# ── Centrale update-hints registry ───────────────────────────────────────────
ALL_UPDATE_HINTS: Dict[str, dict] = {}


def register_update_hints(provider_id: str, hints: dict) -> None:
    ALL_UPDATE_HINTS[provider_id] = hints


# ── Gestandaardiseerde data klassen ──────────────────────────────────────────

@dataclass
class ProviderDevice:
    provider_id:  str
    device_id:    str
    name:         str
    device_type:  str        # "inverter"|"ev"|"appliance"|"meter"|"battery"|"boiler"
    available:    bool       = True
    attributes:   Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "device_id":   self.device_id,
            "name":        self.name,
            "device_type": self.device_type,
            "available":   self.available,
            **self.attributes,
        }


@dataclass
class ProviderStatus:
    provider_id:    str
    ok:             bool
    message:        str = ""
    last_update_ts: float = 0.0
    devices_found:  int   = 0
    api_calls_today:int   = 0
    extra:          Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider_id":    self.provider_id,
            "ok":             self.ok,
            "message":        self.message,
            "last_update_ts": self.last_update_ts,
            "devices_found":  self.devices_found,
            "api_calls_today":self.api_calls_today,
            **self.extra,
        }


# ── Abstract base ─────────────────────────────────────────────────────────────

class CloudEMSProvider(ABC):
    """
    Abstract base voor alle CloudEMS externe providers.

    Minimale implementatie:
        async_setup()       → authenticeer + ontdek devices → bool
        async_get_devices() → List[ProviderDevice]
        async_poll()        → Dict[str, Any]  (device_id → data)

    Optioneel:
        async_send_command(device_id, command, params) → bool
    """
    PROVIDER_ID:  str  = "abstract"
    DISPLAY_NAME: str  = "Onbekende provider"
    CATEGORY:     str  = "generic"   # "inverter"|"ev"|"appliance"|"energy"|"heating"
    ICON:         str  = "mdi:help-circle"
    UPDATE_HINTS: dict = {}

    def __init__(self, hass, credentials: dict) -> None:
        self._hass        = hass
        self._credentials = credentials
        self._session:    Optional[aiohttp.ClientSession] = None
        self._lock        = asyncio.Lock()
        self._api_ok      = False
        self._last_error  = ""
        self._call_count  = 0
        self._call_date   = ""
        self._store:      Optional[Store] = None
        self._cache:      Dict[str, Any]  = {}
        if self.UPDATE_HINTS:
            register_update_hints(self.PROVIDER_ID, self.UPDATE_HINTS)

    @abstractmethod
    async def async_setup(self) -> bool: ...

    @abstractmethod
    async def async_get_devices(self) -> List[ProviderDevice]: ...

    @abstractmethod
    async def async_poll(self) -> Dict[str, Any]: ...

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        return False

    async def async_teardown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def async_health_check(self) -> Tuple[bool, str]:
        return self._api_ok, self._last_error or f"{self.PROVIDER_ID} OK"

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id    = self.PROVIDER_ID,
            ok             = self._api_ok,
            message        = self._last_error if not self._api_ok else "OK",
            last_update_ts = self._cache.get("_last_ts", 0.0),
            devices_found  = len(self._cache.get("_devices", [])),
            api_calls_today= self._call_count,
        )

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _sess(self, extra_headers: Optional[dict] = None) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            h = {"Content-Type": "application/json", "Accept": "application/json"}
            if extra_headers:
                h.update(extra_headers)
            self._session = aiohttp.ClientSession(headers=h)
        return self._session

    async def _get(self, url: str, headers: Optional[dict] = None,
                   params: Optional[dict] = None, timeout: int = 15) -> Optional[Any]:
        self._tick()
        try:
            async with self._sess().get(url, headers=headers, params=params,
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
                self._last_error = f"GET {r.status}"
                if r.status == 401:
                    self._api_ok = False
                return None
        except asyncio.TimeoutError:
            self._last_error = "Timeout"
        except aiohttp.ClientError as e:
            self._last_error = str(e)
        return None

    async def _post(self, url: str, data: Optional[dict] = None,
                    json_: Optional[dict] = None, headers: Optional[dict] = None,
                    timeout: int = 15) -> Optional[Any]:
        self._tick()
        try:
            kw: dict = {"timeout": aiohttp.ClientTimeout(total=timeout)}
            if headers:
                kw["headers"] = headers
            if json_ is not None:
                kw["json"] = json_
            elif data is not None:
                kw["data"] = data
            async with self._sess().post(url, **kw) as r:
                if r.status in (200, 201, 204):
                    try:
                        return await r.json(content_type=None)
                    except Exception:
                        return {"ok": True}
                self._last_error = f"POST {r.status}"
                if r.status == 401:
                    self._api_ok = False
                return None
        except asyncio.TimeoutError:
            self._last_error = "POST Timeout"
        except aiohttp.ClientError as e:
            self._last_error = str(e)
        return None

    def _tick(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._call_date:
            self._call_count = 0
            self._call_date  = today
        self._call_count += 1

    def _init_store(self, key: str) -> None:
        self._store = Store(self._hass, 1, f"cloudems_{key}_v1")

    async def _load(self) -> dict:
        if not self._store:
            return {}
        try:
            return await self._store.async_load() or {}
        except Exception:
            return {}

    async def _save(self, data: dict) -> None:
        if self._store:
            try:
                await self._store.async_save(data)
            except Exception:
                pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.PROVIDER_ID} ok={self._api_ok}>"


# ── OAuth2 mixin ──────────────────────────────────────────────────────────────

class OAuth2Mixin:
    """
    Herbruikbaar OAuth2 password/refresh flow.
    Gebruik: class MyProvider(CloudEMSProvider, OAuth2Mixin)
    """
    TOKEN_URL:      str = ""
    CLIENT_ID:      str = ""
    CLIENT_SECRET:  str = ""
    TOKEN_MARGIN_S: int = 300
    _tokens:        dict = {}

    def _token_valid(self) -> bool:
        return (bool(self._tokens.get("access_token")) and
                time.time() < self._tokens.get("expires_at", 0) - self.TOKEN_MARGIN_S)

    def _store_tokens(self, data: dict) -> None:
        self._tokens = {
            "access_token":  data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
            "expires_at":    time.time() + data.get("expires_in", 3600),
            "token_type":    data.get("token_type", "Bearer"),
        }

    def _auth_header(self) -> dict:
        tt = self._tokens.get("token_type", "Bearer")
        return {"Authorization": f"{tt} {self._tokens.get('access_token','')}"}

    async def _pw_grant(self, username: str, password: str) -> bool:
        resp = await self._post(self.TOKEN_URL, data={   # type: ignore[attr-defined]
            "grant_type": "password", "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "username": username, "password": password,
        })
        if resp and resp.get("access_token"):
            self._store_tokens(resp)
            self._api_ok = True   # type: ignore[attr-defined]
            return True
        self._api_ok    = False   # type: ignore[attr-defined]
        self._last_error = f"Auth mislukt"  # type: ignore[attr-defined]
        return False

    async def _refresh(self) -> bool:
        rt = self._tokens.get("refresh_token", "")
        if not rt:
            return False
        resp = await self._post(self.TOKEN_URL, data={  # type: ignore[attr-defined]
            "grant_type": "refresh_token", "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET, "refresh_token": rt,
        })
        if resp and resp.get("access_token"):
            self._store_tokens(resp)
            return True
        self._tokens.pop("refresh_token", None)
        return False

    async def _ensure_token(self, username: str = "", password: str = "") -> bool:
        if self._token_valid():
            return True
        if await self._refresh():
            return True
        if username and password:
            return await self._pw_grant(username, password)
        self._api_ok    = False  # type: ignore[attr-defined]
        self._last_error = "Token verlopen"  # type: ignore[attr-defined]
        return False


# ── Provider Registry ─────────────────────────────────────────────────────────

_REGISTRY: Dict[str, type] = {}


def register_provider(provider_id: str):
    """Decorator: registreer een provider klasse."""
    def decorator(cls: type) -> type:
        _REGISTRY[provider_id] = cls
        return cls
    return decorator


def get_all_providers() -> Dict[str, type]:
    return dict(_REGISTRY)


def create_provider(provider_id: str, hass, credentials: dict) -> Optional[CloudEMSProvider]:
    cls = _REGISTRY.get(provider_id)
    if not cls:
        _LOGGER.error("Onbekende provider: %s. Beschikbaar: %s", provider_id, list(_REGISTRY))
        return None
    try:
        return cls(hass, credentials)
    except Exception as exc:
        _LOGGER.error("Provider aanmaken mislukt (%s): %s", provider_id, exc)
        return None


def list_providers_by_category(category: str) -> List[str]:
    return [pid for pid, cls in _REGISTRY.items() if getattr(cls, "CATEGORY", "") == category]
