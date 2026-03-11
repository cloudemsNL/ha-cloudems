# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Energy Supplier Providers  v1.0.0
===========================================
Directe koppelingen met energieleveranciers voor realtime
prijzen, verbruiksdata en sturing.

Providers:
  TibberProvider      — Tibber (GraphQL, officieel gedocumenteerd)
  OctopusProvider     — Octopus Energy (NL/UK)
  EnecoProvider       — Eneco MijnEneco API
  VattenfallProvider  — Vattenfall MyVattenfall
  EssentProvider      — Essent Mijn Essent
  FrankEnergieProvider — Frank Energie realtime prijzen
  ANWBEnergyProvider  — ANWB Energie
  NieuweStroomProvider — NieuweStroom

Genormaliseerde data:
  current_price_eur_kwh, today_prices[], tomorrow_prices[],
  monthly_usage_kwh, contract_type

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import CloudEMSProvider, OAuth2Mixin, ProviderDevice, register_provider

_LOGGER = logging.getLogger(__name__)

PRICE_DEVICE_ID = "prices"   # vaste device_id voor prijssensor

def _f(v, factor=1.0, dec=5) -> Optional[float]:
    try:
        return round(float(v) * factor, dec)
    except (TypeError, ValueError):
        return None

def _price_dev(pid, name) -> ProviderDevice:
    return ProviderDevice(pid, PRICE_DEVICE_ID, name, "energy_prices", True, {})


# ═══════════════════════════════════════════════════════════════════
# Tibber — officieel GraphQL API
# ═══════════════════════════════════════════════════════════════════
@register_provider("tibber")
class TibberProvider(CloudEMSProvider):
    PROVIDER_ID  = "tibber"
    DISPLAY_NAME = "Tibber"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://api.tibber.com/v1-beta/gql"

    UPDATE_HINTS = {
        "docs":    "https://developer.tibber.com/docs/overview",
        "ha_repo": "https://github.com/Danielhiversen/home_assistant_tibber_custom",
        "note":    "Officieel GraphQL API. Personal Access Token vereist.",
    }

    async def async_setup(self) -> bool:
        self._token = self._credentials.get("access_token","")
        if not self._token:
            self._last_error = "Geen Tibber access token"
            return False
        q = '{ viewer { homes { id address { address1 } } } }'
        data = await self._gql(q)
        if not data:
            return False
        self._cache["homes"] = data.get("data",{}).get("viewer",{}).get("homes",[])
        self._api_ok = True
        _LOGGER.info("Tibber: %d home(s)", len(self._cache["homes"]))
        return True

    async def _gql(self, query: str) -> Optional[dict]:
        return await self._post(self.BASE, json_={"query": query},
                                headers={"Authorization": f"Bearer {self._token}"})

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Tibber prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        q = '''{ viewer { homes { currentSubscription {
            priceInfo {
                current { total startsAt }
                today { total startsAt }
                tomorrow { total startsAt }
            }
        } } } }'''
        data = await self._gql(q)
        if not data:
            return {}
        homes = data.get("data",{}).get("viewer",{}).get("homes",[])
        if not homes:
            return {}
        pi = homes[0].get("currentSubscription",{}).get("priceInfo",{})
        return {PRICE_DEVICE_ID: {
            "current_price": _f(pi.get("current",{}).get("total")),
            "today_prices":  [{"hour": datetime.fromisoformat(p["startsAt"]).hour,
                               "price": _f(p["total"])} for p in pi.get("today",[])],
            "tomorrow_prices":[{"hour": datetime.fromisoformat(p["startsAt"]).hour,
                                "price": _f(p["total"])} for p in pi.get("tomorrow",[])],
            "source": "tibber",
        }}


# ═══════════════════════════════════════════════════════════════════
# Octopus Energy (NL/UK)
# ═══════════════════════════════════════════════════════════════════
@register_provider("octopus")
class OctopusProvider(CloudEMSProvider):
    PROVIDER_ID  = "octopus"
    DISPLAY_NAME = "Octopus Energy"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE_EU      = "https://api.octer.octopusenergy.nl/graphql"
    BASE_UK      = "https://api.octopus.energy/v1"

    UPDATE_HINTS = {
        "docs":    "https://developer.octopus.energy/docs/api/",
        "ha_repo": "https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy",
        "note":    "UK: REST API met api_key. NL: GraphQL met account_number.",
    }

    async def async_setup(self) -> bool:
        self._region  = self._credentials.get("region","nl").lower()
        self._api_key = self._credentials.get("api_key","")
        self._account = self._credentials.get("account_number","")
        if not (self._api_key or self._account):
            self._last_error = "Geen Octopus API key of account_number"
            return False
        self._api_ok = True
        _LOGGER.info("Octopus Energy: regio %s", self._region)
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Octopus prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        if self._region == "nl":
            return await self._poll_nl()
        return await self._poll_uk()

    async def _poll_nl(self) -> Dict[str, Any]:
        q = '''{ electricityTariff { todayRates { from to unitRateExclTax } } }'''
        data = await self._post(self.BASE_EU, json_={"query": q})
        if not data:
            return {}
        rates = (data.get("data",{}).get("electricityTariff",{}).get("todayRates",[]))
        now_h = datetime.now().hour
        current = next((r for r in rates
                        if datetime.fromisoformat(r["from"]).hour == now_h), {})
        return {PRICE_DEVICE_ID: {
            "current_price": _f(current.get("unitRateExclTax")),
            "today_prices":  [{"hour": datetime.fromisoformat(r["from"]).hour,
                               "price": _f(r.get("unitRateExclTax"))} for r in rates],
            "source": "octopus_nl",
        }}

    async def _poll_uk(self) -> Dict[str, Any]:
        import base64
        b64key = base64.b64encode(f"{self._api_key}:".encode()).decode()
        data = await self._get(
            f"{self.BASE_UK}/accounts/{self._account}/",
            headers={"Authorization": f"Basic {b64key}"},
        )
        return {PRICE_DEVICE_ID: {"source": "octopus_uk", "account_data": bool(data)}}


# ═══════════════════════════════════════════════════════════════════
# Frank Energie — realtime EPEX prijzen (NL)
# ═══════════════════════════════════════════════════════════════════
@register_provider("frank_energie")
class FrankEnergieProvider(CloudEMSProvider):
    PROVIDER_ID  = "frank_energie"
    DISPLAY_NAME = "Frank Energie"
    CATEGORY     = "energy"
    ICON         = "mdi:flash"
    BASE         = "https://frank-graphql-prod.graphcdn.app/"

    UPDATE_HINTS = {
        "ha_repo": "https://github.com/DCSBL/ha-frank-energie",
        "note":    "GraphQL API. Geen authenticatie nodig voor marktprijzen.",
        "endpoints":{
            "prices": "POST / query { marketPrices(date:DATE) { from till priceIncl } }",
        },
    }

    async def async_setup(self) -> bool:
        # Frank Energie vereist geen authenticatie voor marktprijzen
        test = await self._gql('{ marketPrices(date:"' + datetime.now().strftime("%Y-%m-%d") + '") { from } }')
        if test is None:
            self._last_error = "Frank Energie API niet bereikbaar"
            return False
        self._api_ok = True
        # Optioneel: inloggen voor persoonlijk verbruik
        if self._credentials.get("username"):
            await self._frank_login()
        return True

    async def _gql(self, query: str) -> Optional[dict]:
        return await self._post(self.BASE, json_={"query": query})

    async def _frank_login(self) -> bool:
        q = '''mutation Login($email:String!,$password:String!){
            login(email:$email,password:$password){authToken refreshToken}
        }'''
        resp = await self._gql(q.replace("$email", f'"{self._credentials.get("username","")}"')
                                 .replace("$password", f'"{self._credentials.get("password","")}"'))
        if resp and resp.get("data",{}).get("login",{}).get("authToken"):
            self._frank_token = resp["data"]["login"]["authToken"]
            return True
        return False

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Frank Energie prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        q = f'''{{ marketPrices(date:"{today}") {{
            from till priceIncl priceExcl
        }} }}'''
        data = await self._gql(q)
        if not data:
            return {}
        prices_raw = data.get("data",{}).get("marketPrices",[])
        now_h = datetime.now().hour
        today_prices = []
        current = None
        for p in prices_raw:
            try:
                h = datetime.fromisoformat(p["from"].replace("Z","+00:00")).astimezone().hour
                price_incl = _f(p.get("priceIncl"))
                today_prices.append({"hour": h, "price": price_incl})
                if h == now_h:
                    current = price_incl
            except Exception:
                continue
        return {PRICE_DEVICE_ID: {
            "current_price": current,
            "today_prices":  today_prices,
            "source": "frank_energie",
        }}


# ═══════════════════════════════════════════════════════════════════
# Eneco — Mijn Eneco API
# ═══════════════════════════════════════════════════════════════════
@register_provider("eneco")
class EnecoProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "eneco"
    DISPLAY_NAME = "Eneco"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://api.eneco.nl/api/v1"
    TOKEN_URL    = "https://api.eneco.nl/api/v1/oauth/token"
    CLIENT_ID    = "eneco-app"

    UPDATE_HINTS = {
        "ha_repo": "https://github.com/home-assistant/core/tree/dev/homeassistant/components/eneco",
        "note":    "Eneco API is reverse-engineered. Controleer ha_repo bij updates.",
    }

    async def async_setup(self) -> bool:
        self._init_store("eneco")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Eneco prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        data = await self._get(f"{self.BASE}/energy/usage",
                                headers=self._auth_header())
        if not data:
            return {}
        return {PRICE_DEVICE_ID: {
            "monthly_usage_kwh": _f(data.get("electricity",{}).get("usage")),
            "source": "eneco",
        }}


# ═══════════════════════════════════════════════════════════════════
# Vattenfall
# ═══════════════════════════════════════════════════════════════════
@register_provider("vattenfall")
class VattenfallProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "vattenfall"
    DISPLAY_NAME = "Vattenfall"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://api.vattenfall.nl/api/v1"
    TOKEN_URL    = "https://login.vattenfall.nl/api/token"

    UPDATE_HINTS = {
        "note": "Vattenfall NL API is reverse-engineered. Controleer bij updates via browser devtools.",
    }

    async def async_setup(self) -> bool:
        self._init_store("vattenfall")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        self._api_ok = ok
        return ok

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Vattenfall prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        data = await self._get(f"{self.BASE}/contracts", headers=self._auth_header())
        if not data:
            return {}
        return {PRICE_DEVICE_ID: {"contract_data": bool(data), "source": "vattenfall"}}


# ═══════════════════════════════════════════════════════════════════
# Essent
# ═══════════════════════════════════════════════════════════════════
@register_provider("essent")
class EssentProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "essent"
    DISPLAY_NAME = "Essent"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://api.essent.nl/api/v2"
    TOKEN_URL    = "https://api.essent.nl/api/v2/auth/token"

    UPDATE_HINTS = {
        "note": "Essent API is reverse-engineered via de Mijn Essent app.",
    }

    async def async_setup(self) -> bool:
        self._init_store("essent")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        self._api_ok = ok
        return ok

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Essent verbruik")]

    async def async_poll(self) -> Dict[str, Any]:
        data = await self._get(f"{self.BASE}/usage/electricity",
                                headers=self._auth_header())
        if not data:
            return {}
        return {PRICE_DEVICE_ID: {
            "monthly_usage_kwh": _f(data.get("totalKwh")),
            "source": "essent",
        }}


# ═══════════════════════════════════════════════════════════════════
# ANWB Energie
# ═══════════════════════════════════════════════════════════════════
@register_provider("anwb_energie")
class ANWBEnergieProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "anwb_energie"
    DISPLAY_NAME = "ANWB Energie"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://api.anwb.nl/energie/v1"
    TOKEN_URL    = "https://api.anwb.nl/energie/v1/auth/token"

    UPDATE_HINTS = {
        "note": "ANWB Energie is een Vattenfall white-label product. Dezelfde API als Vattenfall.",
    }

    async def async_setup(self) -> bool:
        self._init_store("anwb_energie")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        self._api_ok = ok
        return ok

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "ANWB Energie")]

    async def async_poll(self) -> Dict[str, Any]:
        return {PRICE_DEVICE_ID: {"source": "anwb_energie"}}


# ═══════════════════════════════════════════════════════════════════
# NieuweStroom
# ═══════════════════════════════════════════════════════════════════
@register_provider("nieuwestroom")
class NieuweStroomProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "nieuwestroom"
    DISPLAY_NAME = "NieuweStroom"
    CATEGORY     = "energy"
    ICON         = "mdi:lightning-bolt"
    BASE         = "https://mijnnieuwstroom.nl/api/v1"
    TOKEN_URL    = "https://mijnnieuwstroom.nl/api/v1/auth/login"

    UPDATE_HINTS = {
        "note": "NieuweStroom API — reverse-engineered via Mijn NieuweStroom portal.",
    }

    async def async_setup(self) -> bool:
        self._init_store("nieuwestroom")
        resp = await self._post(self.TOKEN_URL, json_={
            "email": self._credentials.get("username",""),
            "password": self._credentials.get("password",""),
        })
        if resp and resp.get("token"):
            self._ns_token = resp["token"]
            self._api_ok   = True
            return True
        self._last_error = "NieuweStroom login mislukt"
        return False

    def _nsh(self) -> dict:
        return {"Authorization": f"Token {getattr(self,'_ns_token','')}"}

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "NieuweStroom")]

    async def async_poll(self) -> Dict[str, Any]:
        data = await self._get(f"{self.BASE}/usage", headers=self._nsh())
        return {PRICE_DEVICE_ID: {
            "monthly_usage_kwh": _f((data or {}).get("electricity",{}).get("kwh")),
            "source": "nieuwestroom",
        }}


# ═══════════════════════════════════════════════════════════════════
# Zonneplan — directe API koppeling voor persoonlijke tarieven
# ═══════════════════════════════════════════════════════════════════
@register_provider("zonneplan")
class ZonneplanProvider(CloudEMSProvider):
    PROVIDER_ID  = "zonneplan"
    DISPLAY_NAME = "Zonneplan"
    CATEGORY     = "energy"
    ICON         = "mdi:solar-power"
    API_BASE     = "https://app-api.zonneplan.nl"
    TOKEN_URL    = "https://app-api.zonneplan.nl/oauth/token"
    CLIENT_ID    = "zonneplan_one"

    UPDATE_HINTS = {
        "note": "Zonneplan persoonlijke energieprijzen via directe API koppeling.",
        "auth": "OAuth2 met access_token. Token wordt automatisch vernieuwd.",
    }

    async def async_setup(self) -> bool:
        """Valideer access_token door een test-aanroep te doen."""
        token = self._credentials.get("access_token", "")
        if not token:
            self._last_error = "Geen access_token opgegeven"
            return False
        self._zp_token = token
        # Test de verbinding
        data = await self._get(
            f"{self.API_BASE}/energy-contracts",
            headers={"Authorization": f"Bearer {self._zp_token}"},
        )
        if data is None:
            self._last_error = "Zonneplan API niet bereikbaar of token ongeldig"
            return False
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_price_dev(self.PROVIDER_ID, "Zonneplan prijzen")]

    async def async_poll(self) -> Dict[str, Any]:
        """Haal huidige en dagprijzen op van Zonneplan."""
        token = getattr(self, "_zp_token", self._credentials.get("access_token", ""))
        headers = {"Authorization": f"Bearer {token}"}
        today = datetime.now().strftime("%Y-%m-%d")

        # Probeer tarieven endpoint
        data = await self._get(
            f"{self.API_BASE}/energy-contracts/prices?date={today}",
            headers=headers,
        )
        if not data:
            return {}

        prices_raw = data.get("data", []) or []
        now_h = datetime.now().hour
        today_prices = []
        current = None

        for p in prices_raw:
            try:
                hour_str = p.get("datetime") or p.get("from", "")
                h = datetime.fromisoformat(hour_str.replace("Z", "+00:00")).astimezone().hour
                price = _f(p.get("price") or p.get("priceIncl") or p.get("electricity_price"))
                if price is not None:
                    today_prices.append({"hour": h, "price": price})
                    if h == now_h:
                        current = price
            except Exception:
                continue

        return {PRICE_DEVICE_ID: {
            "current_price": current,
            "today_prices":  today_prices,
            "source":        "zonneplan",
        }}
