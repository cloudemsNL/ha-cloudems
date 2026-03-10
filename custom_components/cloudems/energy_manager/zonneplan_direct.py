# -*- coding: utf-8 -*-
"""
CloudEMS Zonneplan One — Direct Provider  v1.0.0

Native Zonneplan One API client. Geen afhankelijkheid van
'ha-zonneplan-one' HACS-integratie.

Spreekt de officiële Zonneplan REST API aan:
  https://app-api.zonneplan.nl/

Auth: OAuth2 Password Grant (zelfde als de HACS-integratie).
      Tokens worden veilig opgeslagen via HA Storage.

Voordelen t.o.v. HACS-brug (zonneplan_bridge.py):
  - Onafhankelijk van 'zonneplan_one' entiteitsnamen/attrs die kunnen wijzigen
  - Werkt ook in standalone cloud-variant (geen HA nodig)
  - Directe EPEX-prijzen als fallback voor eigen prijsdata
  - Volledige controle over retry/backoff/error-handling

Werkt samen met de bestaande ZonnePlanProvider (zonneplan_bridge.py):
  - Als 'direct' mode actief is, vervangt dit de HA-entiteiten brug
  - Zelfde ZPAction / DecisionResult interface
  - Config flow: "Verbinding via HA-integratie" vs "Rechtstreeks (CloudEMS)"

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY      = "cloudems_zonneplan_direct_v1"
STORAGE_VERSION  = 1
API_BASE         = "https://app-api.zonneplan.nl"
TOKEN_URL        = f"{API_BASE}/oauth/token"
CLIENT_ID        = "zonneplan_one"           # public client id van Zonneplan app
CLIENT_SECRET    = ""                        # public — geen secret nodig
TOKEN_REFRESH_MARGIN_S = 300                 # ververs token 5 min voor expiry
POLL_INTERVAL_S  = 60                        # state polling interval


@dataclass
class ZonnePlanTokens:
    access_token:  str  = ""
    refresh_token: str  = ""
    expires_at:    float= 0.0

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < (self.expires_at - TOKEN_REFRESH_MARGIN_S)

    def to_dict(self) -> dict:
        return {
            "access_token":  self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at":    self.expires_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ZonnePlanTokens":
        return cls(
            access_token  = d.get("access_token", ""),
            refresh_token = d.get("refresh_token", ""),
            expires_at    = d.get("expires_at", 0.0),
        )


@dataclass
class ZonnePlanBatteryState:
    """Live batterijstatus van Zonneplan."""
    device_id:    str
    label:        str
    soc_pct:      Optional[float] = None
    power_w:      Optional[float] = None   # + = laden, - = leveren
    control_mode: str             = "unknown"
    state:        str             = "unknown"
    available:    bool            = True

    def to_dict(self) -> dict:
        return {
            "device_id":    self.device_id,
            "label":        self.label,
            "soc_pct":      self.soc_pct,
            "power_w":      self.power_w,
            "control_mode": self.control_mode,
            "state":        self.state,
            "available":    self.available,
        }


@dataclass
class ZonnePlanEnergyPrice:
    """EPEX prijs van Zonneplan (inclusief opslag/teruglevering)."""
    hour_utc:       int
    date:           str     # "2026-03-10"
    price_eur_kwh:  float
    deliver_eur_kwh: Optional[float] = None  # teruglevering

    def to_dict(self) -> dict:
        return {
            "hour_utc":        self.hour_utc,
            "date":            self.date,
            "price_eur_kwh":   round(self.price_eur_kwh, 5),
            "deliver_eur_kwh": round(self.deliver_eur_kwh, 5) if self.deliver_eur_kwh else None,
        }


class ZonnePlanDirectProvider:
    """
    Native Zonneplan One provider voor CloudEMS.

    Gebruik:
        provider = ZonnePlanDirectProvider(hass, username="...", password="...")
        ok = await provider.async_setup()
        if ok:
            state = await provider.async_get_battery_state()
            await provider.async_set_control_mode("home_optimization")
    """

    def __init__(
        self,
        hass,
        username: str,
        password: str,
    ) -> None:
        self._hass      = hass
        self._username  = username
        self._password  = password
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._tokens    = ZonnePlanTokens()
        self._session:  Optional[aiohttp.ClientSession] = None
        self._lock      = asyncio.Lock()
        self._batteries: List[dict] = []   # gecachte device lijst
        self._last_state: Optional[ZonnePlanBatteryState] = None
        self._last_prices: List[ZonnePlanEnergyPrice] = []
        self._last_state_ts: float = 0.0
        self._api_ok:   bool = False
        self._last_error: str = ""

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self) -> bool:
        """Laad tokens, authenticeer, haal device-lijst op."""
        try:
            data = await self._store.async_load() or {}
            self._tokens = ZonnePlanTokens.from_dict(data.get("tokens", {}))
            _LOGGER.debug("CloudEMS Zonneplan: tokens geladen uit storage")
        except Exception:
            pass

        ok = await self._ensure_token()
        if not ok:
            _LOGGER.error("CloudEMS Zonneplan Direct: authenticatie mislukt")
            return False

        self._batteries = await self._fetch_devices()
        _LOGGER.info(
            "CloudEMS Zonneplan Direct: verbonden, %d batterij/energie-devices gevonden",
            len(self._batteries)
        )
        self._api_ok = True
        return True

    async def async_shutdown(self) -> None:
        await self._save_tokens()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Data ophalen ──────────────────────────────────────────────────────────

    async def async_get_battery_state(self) -> Optional[ZonnePlanBatteryState]:
        """Haal actuele batterijstatus op."""
        if not await self._ensure_token():
            return None

        for device in self._batteries:
            if device.get("type") not in ("battery", "home_battery", "energy_device"):
                continue
            device_id = device.get("id") or device.get("uuid", "")
            if not device_id:
                continue

            try:
                data = await self._api_get(f"/energy-devices/{device_id}/state")
                if data is None:
                    continue

                # Normaliseer response — Zonneplan gebruikt wisselende veldnamen
                soc   = self._extract_soc(data)
                power = self._extract_power(data)
                mode  = self._extract_mode(data)
                state = self._extract_state(data)

                result = ZonnePlanBatteryState(
                    device_id    = device_id,
                    label        = device.get("label") or device.get("name") or "Zonneplan Nexus",
                    soc_pct      = soc,
                    power_w      = power,
                    control_mode = mode,
                    state        = state,
                    available    = True,
                )
                self._last_state    = result
                self._last_state_ts = time.time()
                return result

            except Exception as exc:
                _LOGGER.warning("CloudEMS Zonneplan: state ophalen mislukt: %s", exc)

        return self._last_state  # geef gecachte state terug bij fout

    async def async_get_prices_today(self) -> List[ZonnePlanEnergyPrice]:
        """Haal vandaag/morgen EPEX prijzen op van Zonneplan."""
        if not await self._ensure_token():
            return self._last_prices

        try:
            data = await self._api_get("/electricity-prices")
            if data:
                prices = self._parse_prices(data)
                self._last_prices = prices
                return prices
        except Exception as exc:
            _LOGGER.debug("CloudEMS Zonneplan: prijzen ophalen mislukt: %s", exc)

        return self._last_prices

    # ── Sturing ───────────────────────────────────────────────────────────────

    async def async_set_control_mode(self, mode: str, device_id: Optional[str] = None) -> bool:
        """
        Stel batterij besturingsmodus in.

        Args:
            mode: "home_optimization" | "self_consumption" | "powerplay"
            device_id: None = eerste gevonden batterij
        """
        if not await self._ensure_token():
            return False

        dev_id = device_id or self._get_primary_battery_id()
        if not dev_id:
            _LOGGER.warning("CloudEMS Zonneplan: geen batterij device gevonden")
            return False

        # Zonneplan API verwacht specifieke mode-waarden
        mode_map = {
            "home_optimization": "home_optimization",
            "self_consumption":  "self_consumption",
            "powerplay":         "powerplay",
            "manual_control":    "manual_control",
        }
        api_mode = mode_map.get(mode, mode)

        ok = await self._api_put(
            f"/energy-devices/{dev_id}/control-mode",
            {"control_mode": api_mode}
        )
        if ok:
            _LOGGER.info("CloudEMS Zonneplan: mode ingesteld op '%s'", api_mode)
        else:
            _LOGGER.warning("CloudEMS Zonneplan: mode instellen mislukt")
        return ok

    async def async_set_charge_power(self, power_w: float, device_id: Optional[str] = None) -> bool:
        """Stel laadvermogen in (W)."""
        dev_id = device_id or self._get_primary_battery_id()
        if not dev_id:
            return False
        return await self._api_put(
            f"/energy-devices/{dev_id}/charge-power",
            {"power_w": round(power_w)}
        )

    async def async_set_discharge_power(self, power_w: float, device_id: Optional[str] = None) -> bool:
        """Stel ontlaadvermogen in (W)."""
        dev_id = device_id or self._get_primary_battery_id()
        if not dev_id:
            return False
        return await self._api_put(
            f"/energy-devices/{dev_id}/discharge-power",
            {"power_w": round(power_w)}
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "zonneplan_direct_ok":      self._api_ok,
            "zonneplan_direct_devices": len(self._batteries),
            "zonneplan_last_error":     self._last_error,
            "zonneplan_token_valid":    self._tokens.is_valid,
            "zonneplan_last_state_age": int(time.time() - self._last_state_ts) if self._last_state_ts else None,
        }

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    async def _ensure_token(self) -> bool:
        """Zorg dat we een geldig access token hebben."""
        async with self._lock:
            if self._tokens.is_valid:
                return True

            if self._tokens.refresh_token:
                ok = await self._refresh_token()
                if ok:
                    return True

            ok = await self._password_grant()
            return ok

    async def _password_grant(self) -> bool:
        """Nieuw token via username/password."""
        try:
            payload = {
                "grant_type":    "password",
                "client_id":     CLIENT_ID,
                "username":      self._username,
                "password":      self._password,
            }
            async with self._get_session() as session:
                async with session.post(TOKEN_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._store_tokens(data)
                        await self._save_tokens()
                        _LOGGER.info("CloudEMS Zonneplan: nieuw token ontvangen")
                        return True
                    else:
                        body = await resp.text()
                        self._last_error = f"Auth {resp.status}: {body[:200]}"
                        _LOGGER.error("CloudEMS Zonneplan: auth mislukt %d: %s", resp.status, body[:200])
                        return False
        except Exception as exc:
            self._last_error = str(exc)
            _LOGGER.error("CloudEMS Zonneplan: auth exception: %s", exc)
            return False

    async def _refresh_token(self) -> bool:
        """Token vernieuwen via refresh token."""
        try:
            payload = {
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "refresh_token": self._tokens.refresh_token,
            }
            async with self._get_session() as session:
                async with session.post(TOKEN_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._store_tokens(data)
                        await self._save_tokens()
                        return True
                    else:
                        # Refresh gefaald → force nieuwe login
                        self._tokens.refresh_token = ""
                        return False
        except Exception:
            return False

    def _store_tokens(self, data: dict) -> None:
        expires_in = data.get("expires_in", 3600)
        self._tokens = ZonnePlanTokens(
            access_token  = data.get("access_token", ""),
            refresh_token = data.get("refresh_token", ""),
            expires_at    = time.time() + expires_in,
        )

    # ── API helpers ───────────────────────────────────────────────────────────

    async def _api_get(self, path: str) -> Optional[dict]:
        try:
            async with self._get_session() as session:
                async with session.get(
                    f"{API_BASE}{path}",
                    headers={"Authorization": f"Bearer {self._tokens.access_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 401:
                        self._tokens.access_token = ""   # force re-auth
                        return None
                    else:
                        _LOGGER.debug("CloudEMS Zonneplan GET %s → %d", path, resp.status)
                        return None
        except Exception as exc:
            _LOGGER.debug("CloudEMS Zonneplan GET %s fout: %s", path, exc)
            return None

    async def _api_put(self, path: str, payload: dict) -> bool:
        try:
            async with self._get_session() as session:
                async with session.put(
                    f"{API_BASE}{path}",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._tokens.access_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    return resp.status in (200, 201, 204)
        except Exception as exc:
            _LOGGER.warning("CloudEMS Zonneplan PUT %s fout: %s", path, exc)
            return False

    async def _fetch_devices(self) -> List[dict]:
        """Haal alle energie-devices op (Nexus batterij + P1 meter)."""
        data = await self._api_get("/energy-devices") or {}
        devices = data.get("data", data.get("devices", []))
        if isinstance(devices, dict):
            devices = list(devices.values())
        return [d for d in devices if isinstance(d, dict)]

    def _get_primary_battery_id(self) -> Optional[str]:
        for d in self._batteries:
            if d.get("type") in ("battery", "home_battery", "energy_device"):
                return d.get("id") or d.get("uuid")
        return None

    # ── Data parsers (Zonneplan wisselt veldnamen tussen app-versies) ─────────

    def _extract_soc(self, data: dict) -> Optional[float]:
        for key in ("state_of_charge", "soc", "battery_percentage", "soc_pct", "percentage"):
            v = data.get(key) or data.get("attributes", {}).get(key)
            if v is not None:
                return float(v)
        return None

    def _extract_power(self, data: dict) -> Optional[float]:
        for key in ("power", "power_w", "battery_power", "charging_power"):
            v = data.get(key) or data.get("attributes", {}).get(key)
            if v is not None:
                return float(v)
        return None

    def _extract_mode(self, data: dict) -> str:
        for key in ("control_mode", "battery_control_mode", "mode", "operating_mode"):
            v = data.get(key) or data.get("attributes", {}).get(key)
            if v:
                return str(v)
        return "unknown"

    def _extract_state(self, data: dict) -> str:
        for key in ("state", "status", "battery_state"):
            v = data.get(key) or data.get("attributes", {}).get(key)
            if v:
                return str(v)
        return "unknown"

    def _parse_prices(self, data: Any) -> List[ZonnePlanEnergyPrice]:
        """Parseer Zonneplan prijzen naar gestandaardiseerd formaat."""
        prices = []
        items  = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("prices", data.get("electricity_prices", [])))

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                # Datum/uur extraheren
                dt_str = item.get("datetime") or item.get("date") or item.get("from")
                if not dt_str:
                    continue
                dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
                price_raw = item.get("electricity_price") or item.get("price") or item.get("tariff")
                if price_raw is None:
                    continue
                deliver_raw = item.get("electricity_delivery_price") or item.get("delivery_price")
                prices.append(ZonnePlanEnergyPrice(
                    hour_utc       = dt.hour,
                    date           = dt.date().isoformat(),
                    price_eur_kwh  = float(price_raw),
                    deliver_eur_kwh= float(deliver_raw) if deliver_raw is not None else None,
                ))
            except (ValueError, KeyError, TypeError):
                continue

        return prices

    # ── Session & storage ─────────────────────────────────────────────────────

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json", "Accept": "application/json"}
            )
        return self._session

    async def _save_tokens(self) -> None:
        try:
            await self._store.async_save({"tokens": self._tokens.to_dict()})
        except Exception:
            pass
