# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS EV Vehicle Providers  v1.0.0
=======================================
Cloud-API koppelingen voor elektrische auto's.
Alle providers werken via officiële of community-geverifieerde REST APIs.
Geen lokale verbinding nodig — werkt ook in de hosted cloud-variant.

Providers:
  Tesla          — Tesla Fleet API (OAuth2, owners.api.com fallback)
  BMW / Mini     — BMW ConnectedDrive API
  Volkswagen     — WeConnect API (ook Audi, SEAT, Škoda, Cupra)
  Hyundai / Kia  — Bluelink / UVO Connect API
  Renault        — My Renault API
  Nissan         — Nissan Connect EV API
  Polestar       — Polestar API
  Ford           — Ford Pass / FordConnect API
  Rivian         — Rivian GraphQL API
  Mercedes-Benz  — Mercedes me connect API
  Volvo          — Volvo Cars API

Genormaliseerde data per poll():
  soc_pct, range_km, charging, charge_power_w,
  charge_limit_pct, plugged_in, location (lat/lon)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from .base import CloudEMSProvider, OAuth2Mixin, ProviderDevice, register_provider

_LOGGER = logging.getLogger(__name__)


def _ev_dev(pid, did, name, attrs) -> ProviderDevice:
    return ProviderDevice(pid, did, name, "ev", True, attrs)

def _f(v, factor=1.0, dec=1) -> Optional[float]:
    try:
        return round(float(v) * factor, dec)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════
# Tesla
# ═══════════════════════════════════════════════════════════════════
@register_provider("tesla")
class TeslaProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "tesla"
    DISPLAY_NAME = "Tesla"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1"
    TOKEN_URL    = "https://auth.tesla.com/oauth2/v3/token"
    CLIENT_ID    = "ownerapi"

    UPDATE_HINTS = {
        "docs":    "https://developer.tesla.com/docs/fleet-api",
        "ha_repo": "https://github.com/alandtse/tesla",
        "note":    "Fleet API vereist app-registratie. owners.api fallback voor persoonlijk gebruik.",
        "endpoints": {
            "vehicles":  "GET /vehicles",
            "data":      "GET /vehicles/{id}/vehicle_data",
            "wake":      "POST /vehicles/{id}/wake_up",
            "charge_cmd":"POST /vehicles/{id}/command/charge_start",
        },
    }

    async def async_setup(self) -> bool:
        self._init_store("tesla")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            # Probeer refresh_token direct als het in credentials zit
            rt = self._credentials.get("refresh_token","")
            if rt:
                self._tokens["refresh_token"] = rt
                ok = await self._refresh()
        if not ok:
            self._last_error = "Tesla authenticatie mislukt — controleer token"
            return False
        vehs = await self._get(f"{self.BASE}/vehicles", headers=self._auth_header())
        if vehs is None:
            return False
        self._cache["vehicles"] = vehs.get("response", [])
        await self._save({"tokens": self._tokens})
        self._api_ok = True
        _LOGGER.info("Tesla: %d voertuig(en)", len(self._cache["vehicles"]))
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, str(v.get("id","")),
                        v.get("display_name", f"Tesla {v.get('vin','')}"),
                        {"vin": v.get("vin",""), "model": v.get("model","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vid   = str(v.get("id",""))
            state = v.get("state","")
            # Tesla slaapt als de auto niet in gebruik is — wake alleen als nodig
            if state == "asleep":
                out[vid] = {"soc_pct": None, "charging": False, "asleep": True}
                continue
            data = await self._get(f"{self.BASE}/vehicles/{vid}/vehicle_data",
                                   headers=self._auth_header())
            if not data:
                continue
            r   = data.get("response", {})
            cs  = r.get("charge_state", {})
            ds  = r.get("drive_state", {})
            out[vid] = {
                "soc_pct":          _f(cs.get("battery_level")),
                "range_km":         _f(cs.get("battery_range"), 1.60934),  # miles→km
                "charging":         cs.get("charging_state") == "Charging",
                "charge_power_w":   _f(cs.get("charger_power"), 1000),
                "charge_limit_pct": _f(cs.get("charge_limit_soc")),
                "plugged_in":       cs.get("charging_state") != "Disconnected",
                "latitude":         _f(ds.get("latitude"), 1.0, 6),
                "longitude":        _f(ds.get("longitude"), 1.0, 6),
                "odometer_km":      _f(r.get("vehicle_state",{}).get("odometer"), 1.60934, 0),
            }
        return out

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        cmd_map = {
            "charge_start":  "charge_start",
            "charge_stop":   "charge_stop",
            "wake_up":       None,  # special
            "set_charge_limit": "set_charge_limit",
            "set_charging_amps":"set_charging_amps",
        }
        if command == "wake_up":
            r = await self._post(f"{self.BASE}/vehicles/{device_id}/wake_up",
                                 json_={}, headers=self._auth_header())
            return bool(r)
        ep = cmd_map.get(command)
        if not ep:
            return False
        r = await self._post(f"{self.BASE}/vehicles/{device_id}/command/{ep}",
                             json_=params or {}, headers=self._auth_header())
        return bool(r and r.get("response",{}).get("result"))


# ═══════════════════════════════════════════════════════════════════
# BMW / Mini
# ═══════════════════════════════════════════════════════════════════
@register_provider("bmw")
@register_provider("mini")
class BMWProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "bmw"
    DISPLAY_NAME = "BMW ConnectedDrive"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://cocoapi.bmwgroup.com/eadrax-vcs/v4/vehicles"
    TOKEN_URL    = "https://customer.bmwgroup.com/gcdm/oauth/authenticate"
    CLIENT_ID    = "dbf0a542-ebd1-4ff0-a9a7-55172fbfce35"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/bimmerconnected/bimmer_connected",
        "pypi":     "https://pypi.org/project/bimmer-connected/",
        "note":     "Gebruik bimmer_connected library als referentie. Authenticatie wijzigt regelmatig.",
        "endpoints":{
            "vehicles":   "GET /eadrax-vcs/v4/vehicles",
            "state":      "GET /eadrax-vcs/v4/vehicles/{vin}/state",
            "charge_now": "POST /eadrax-ccs/v1/vehicles/{vin}/charging/start",
        },
    }

    async def async_setup(self) -> bool:
        self._init_store("bmw")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(self.BASE, headers={**self._auth_header(),
                                                    "bmw-vin": "",
                                                    "x-user-agent": "android(v1.7.0);bmw;1.7.0;row"})
        if data is None:
            return False
        self._cache["vehicles"] = data if isinstance(data, list) else data.get("vehicles", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        f"{v.get('attributes',{}).get('brand','')} {v.get('attributes',{}).get('model','')}",
                        {"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("vin","")
            data = await self._get(
                f"https://cocoapi.bmwgroup.com/eadrax-vcs/v4/vehicles/{vin}/state",
                headers={**self._auth_header(), "x-user-agent": "android(v1.7.0);bmw;1.7.0;row"})
            if data:
                es = data.get("electricChargingState", {})
                out[vin] = {
                    "soc_pct":        _f(es.get("chargingLevelHv")),
                    "range_km":       _f(es.get("range")),
                    "charging":       es.get("chargingStatus") == "CHARGING",
                    "charge_power_w": _f(es.get("chargingRateKmPerHour"), 250),  # rough conv
                    "plugged_in":     es.get("isChargerConnected", False),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Volkswagen / Audi / SEAT / Škoda / Cupra — WeConnect
# ═══════════════════════════════════════════════════════════════════
@register_provider("volkswagen")
@register_provider("audi")
@register_provider("skoda")
@register_provider("seat")
class VolkswagenWeConnectProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "volkswagen"
    DISPLAY_NAME = "Volkswagen WeConnect"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://emea.bff.cariad.digital/vehicle/v1/vehicles"
    TOKEN_URL    = "https://identity.vwgroup.io/oidc/v1/token"
    CLIENT_ID    = "09b6cbec-cd19-4589-82fd-363dfa8c24da@apps_vw-dilab_com"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/robinostlund/homeassistant-volkswagencarnet",
        "pypi":     "https://pypi.org/project/volkswagencarnet/",
        "note":     "WeConnect werkt voor VW, Audi (e-tron), SEAT, Škoda, Cupra.",
        "endpoints":{
            "vehicles":   "GET /vehicle/v1/vehicles",
            "status":     "GET /vehicle/v1/vehicles/{vin}/selectivestatus",
            "charge_start":"POST /vehicle/v1/vehicles/{vin}/charging/start",
        },
    }

    async def async_setup(self) -> bool:
        self._init_store("vw_weconnect")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(self.BASE, headers=self._auth_header())
        if data is None:
            return False
        self._cache["vehicles"] = data.get("data", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        v.get("nickname", v.get("model","VW")),
                        {"vin": v.get("vin",""), "brand": v.get("brand","VW")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("vin","")
            data = await self._get(
                f"https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/selectivestatus",
                headers=self._auth_header(),
                params={"jobs": "charging"})
            if data:
                cs = data.get("charging",{}).get("chargingStatus",{}).get("value",{})
                bs = data.get("charging",{}).get("batteryStatus",{}).get("value",{})
                out[vin] = {
                    "soc_pct":        _f(bs.get("currentSOC_pct")),
                    "range_km":       _f(bs.get("cruisingRangeElectric_km")),
                    "charging":       cs.get("chargingState") == "charging",
                    "charge_power_w": _f(cs.get("chargePower_kW"), 1000),
                    "plugged_in":     cs.get("chargingState") not in ("notReadyForCharging","",None),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Hyundai / Kia
# ═══════════════════════════════════════════════════════════════════
@register_provider("hyundai")
@register_provider("kia")
class HyundaiKiaProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "hyundai"
    DISPLAY_NAME = "Hyundai Bluelink / Kia UVO"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE_EU      = "https://prd.eu-ccapi.hyundai.com:8080/api/v1"
    TOKEN_URL    = "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api",
        "pypi":     "https://pypi.org/project/hyundai-kia-connect-api/",
        "note":     "Zelfde API voor Hyundai Bluelink en Kia UVO in EU.",
    }

    async def async_setup(self) -> bool:
        self._init_store("hyundai_kia")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        brand = "kia" if self._credentials.get("brand","").lower() == "kia" else "hyundai"
        self.BASE_EU = (f"https://prd.eu-ccapi.{brand}.com:8080/api/v1"
                        if brand == "kia" else self.BASE_EU)
        self.TOKEN_URL = f"{self.BASE_EU}/user/oauth2/token"
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE_EU}/spa/vehicles",
                                headers={**self._auth_header(),
                                         "ccsp-service-id": "6d477c38-3ca4-4cf3-9557-2a1929a94654"})
        if data is None:
            return False
        self._cache["vehicles"] = data.get("resMsg",{}).get("vehicles",[])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vehicleId",""),
                        v.get("nickname", v.get("vehicleName","Hyundai/Kia")),
                        {"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vid  = v.get("vehicleId","")
            data = await self._get(
                f"{self.BASE_EU}/spa/vehicles/{vid}/status",
                headers={**self._auth_header(),
                         "ccsp-service-id": "6d477c38-3ca4-4cf3-9557-2a1929a94654"})
            if data:
                ev = data.get("resMsg",{}).get("evStatus",{})
                out[vid] = {
                    "soc_pct":    _f(ev.get("batteryStatus")),
                    "range_km":   _f(ev.get("drvDistance",[{}])[0].get("rangeByFuel",{}).get("totalAvailableRange",{}).get("value")),
                    "charging":   ev.get("batteryCharge", False),
                    "plugged_in": ev.get("batteryPlugin", 0) > 0,
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Renault
# ═══════════════════════════════════════════════════════════════════
@register_provider("renault")
class RenaultProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "renault"
    DISPLAY_NAME = "My Renault"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://api-wired-prod-1-euw1.wrd-aws.com"
    TOKEN_URL    = "https://accounts.eu1.gigya.com/accounts.login"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/hacf-fr/renault-api",
        "pypi":     "https://pypi.org/project/renault-api/",
        "note":     "Gigya authenticatie. Zie renault-api pypi voor volledige implementatie.",
    }

    async def async_setup(self) -> bool:
        self._init_store("renault")
        # Renault gebruikt Gigya sessie-tokens — complexe flow
        # Stap 1: Gigya login
        resp = await self._post(
            "https://accounts.eu1.gigya.com/accounts.login",
            data={"loginID": self._credentials.get("username",""),
                  "password": self._credentials.get("password",""),
                  "apiKey": "3_7PLksOyBRkHv126x5WhHb-5pqC1qFR2pCpKHDDRyeE8bGMGxMzvrbwaeDsLSp2Ae"})
        if not (resp and resp.get("statusCode") == 200):
            self._last_error = "Renault Gigya login mislukt"
            return False
        self._gigya_token = resp.get("sessionInfo",{}).get("sessionToken","")
        # Stap 2: Renault JWT
        resp2 = await self._get(
            "https://accounts.eu1.gigya.com/accounts.getJWT",
            params={"login_token": self._gigya_token,
                    "apiKey": "3_7PLksOyBRkHv126x5WhHb-5pqC1qFR2pCpKHDDRyeE8bGMGxMzvrbwaeDsLSp2Ae",
                    "fields": "data.personId,data.gigyaDataCenter",
                    "expiration": "900"})
        if not resp2:
            return False
        self._tokens = {"access_token": resp2.get("id_token",""), "token_type": "Bearer",
                        "expires_at": time.time() + 900}
        # Stap 3: persoon-ID
        person = await self._get(
            f"{self.BASE}/commerce/v1/persons/", headers=self._auth_header())
        if not person:
            return False
        self._person_id = person.get("id","")
        # Stap 4: voertuigen
        vehs = await self._get(
            f"{self.BASE}/commerce/v1/persons/{self._person_id}/vehicles",
            headers=self._auth_header())
        self._cache["vehicles"] = (vehs or {}).get("vehicleLinks",[])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        v.get("vehicleDetails",{}).get("registrationNumber", v.get("vin","")),
                        {"vin": v.get("vin",""), "brand": v.get("brand","Renault")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("vin","")
            ak   = v.get("accountId","")
            data = await self._get(
                f"{self.BASE}/commerce/v1/accounts/{ak}/kamereon/kca/car-adapter/v2/cars/{vin}/charges/lastcharge",
                headers=self._auth_header())
            battery = await self._get(
                f"{self.BASE}/commerce/v1/accounts/{ak}/kamereon/kca/car-adapter/v2/cars/{vin}/battery-status",
                headers=self._auth_header())
            bat = (battery or {}).get("data",{}).get("attributes",{})
            out[vin] = {
                "soc_pct":    _f(bat.get("batteryLevel")),
                "range_km":   _f(bat.get("batteryAutonomy")),
                "charging":   bat.get("chargingStatus",0) > 0,
                "plugged_in": bat.get("plugStatus",0) > 0,
                "charge_power_w": _f(bat.get("chargingInstantaneousPower"), 1000),
            }
        return out


# ═══════════════════════════════════════════════════════════════════
# Nissan Leaf — NissanConnect EV
# ═══════════════════════════════════════════════════════════════════
@register_provider("nissan")
class NissanProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "nissan"
    DISPLAY_NAME = "Nissan Connect EV"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://application.api.carwings.com"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/filcole/pycarwings2",
        "pypi":     "https://pypi.org/project/pycarwings2/",
        "note":     "NissanConnect voor Leaf/Ariya. Zie pycarwings2 voor implementatie.",
    }

    async def async_setup(self) -> bool:
        self._init_store("nissan")
        resp = await self._post(f"{self.BASE}/en/BatteryStatusCheckRequest.php",
                                data={"initial_app_strings": "geORNtsZe5I4lRGjqC9mNEHfQmG3GeYFpLi47Vs2qD9dYMG",
                                      "RegionCode": "NE",
                                      "lg": "nl",
                                      "UserId": self._credentials.get("username",""),
                                      "Password": self._credentials.get("password","")})
        if resp and resp.get("status") == 200:
            self._session_id = resp.get("VehicleInfoList",{}).get("vehicleInfo",[{}])[0].get("custom_sessionid","")
            self._vin = resp.get("VehicleInfoList",{}).get("vehicleInfo",[{}])[0].get("vin","")
            self._cache["vehicles"] = [{"vin": self._vin}]
            self._api_ok = True
            return True
        self._last_error = "Nissan Connect login mislukt"
        return False

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        f"Nissan Leaf {v.get('vin','')}",{"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        resp = await self._post(f"{self.BASE}/en/BatteryStatusRecordsRequest.php",
                                data={"custom_sessionid": self._session_id,
                                      "RegionCode": "NE", "lg": "nl",
                                      "VIN": getattr(self,"_vin","")})
        if resp and resp.get("status") == 200:
            bs = resp.get("BatteryStatusRecords",{})
            return {self._vin: {
                "soc_pct":    _f(bs.get("BatteryStatus",{}).get("BatteryRemainingAmountWH"), 0.01),
                "range_km":   _f(bs.get("CruisingRangeAcOn"), 0.001),  # m→km
                "charging":   bs.get("BatteryStatus",{}).get("BatteryChargingStatus") != "NOT_CHARGING",
                "plugged_in": bs.get("PluginState") != "NOT_CONNECTED",
            }}
        return {}


# ═══════════════════════════════════════════════════════════════════
# Polestar
# ═══════════════════════════════════════════════════════════════════
@register_provider("polestar")
class PolestarProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "polestar"
    DISPLAY_NAME = "Polestar"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://pc-api.polestar.com/eu-north-1/my-star"
    TOKEN_URL    = "https://polestarid.eu.polestar.com/as/token.oauth2"
    CLIENT_ID    = "l3oopkc_10"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/pypolestar/pypolestar",
        "pypi":     "https://pypi.org/project/pypolestar/",
        "note":     "GraphQL API. Controleer pypolestar voor mutatienamen.",
    }

    async def async_setup(self) -> bool:
        self._init_store("polestar")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._gql('{ getConsumerCarsV2 { vin internalVehicleIdentifier } }')
        if not data:
            return False
        self._cache["vehicles"] = data.get("data",{}).get("getConsumerCarsV2",[])
        self._api_ok = True
        return True

    async def _gql(self, query: str) -> Optional[dict]:
        return await self._post(f"{self.BASE}/graphql",
                                json_={"query": query},
                                headers=self._auth_header())

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        f"Polestar {v.get('vin','')}",{"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin = v.get("vin","")
            iid = v.get("internalVehicleIdentifier","")
            q   = f'''{{ getBatteryV2(input:{{vins:["{vin}"]}}) {{
                          vin batteryChargeLevelPercentage
                          estimatedDistanceToEmptyKm chargingConnectionStatus
                          chargingSystemStatus chargerPowerKW }} }}'''
            data = await self._gql(q)
            if data:
                b = (data.get("data",{}).get("getBatteryV2") or [{}])[0]
                out[vin] = {
                    "soc_pct":        _f(b.get("batteryChargeLevelPercentage")),
                    "range_km":       _f(b.get("estimatedDistanceToEmptyKm")),
                    "charging":       b.get("chargingSystemStatus") == "CHARGING_STATUS_CHARGING",
                    "charge_power_w": _f(b.get("chargerPowerKW"), 1000),
                    "plugged_in":     b.get("chargingConnectionStatus") != "CHARGER_CONNECTION_STATUS_DISCONNECTED",
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Ford / FordConnect
# ═══════════════════════════════════════════════════════════════════
@register_provider("ford")
class FordProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "ford"
    DISPLAY_NAME = "Ford Pass"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://api.mps.ford.com/api"
    TOKEN_URL    = "https://dah2vb2cprod.b2clogin.com/914d88b1-3523-4bf6-9be4-1b96b4f6f919/oauth2/v2.0/token"
    CLIENT_ID    = "9fb503e0-715b-47e8-adfd-ad4b7770f73b"

    UPDATE_HINTS = {
        "ha_repo": "https://github.com/itchannel/fordpass-ha",
        "note":    "B2C login. Zie fordpass-ha voor token-flow details.",
    }

    async def async_setup(self) -> bool:
        self._init_store("ford")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/expdashboard/v1/details/",
                                headers={**self._auth_header(), "Application-Id": "71A3AD0A-CF46-4CCF-B473-FC7FE5BC4592"})
        if data:
            self._cache["vehicles"] = data.get("userVehicles",{}).get("vehicleDetails",[])
            self._api_ok = True
        return self._api_ok

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("VIN",""),
                        v.get("nickName", v.get("modelName","Ford")),
                        {"vin": v.get("VIN","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("VIN","")
            data = await self._get(
                f"{self.BASE}/vehicles/v4/{vin}/status",
                headers={**self._auth_header(), "Application-Id": "71A3AD0A-CF46-4CCF-B473-FC7FE5BC4592"})
            if data:
                cs = data.get("vehiclestatus",{}).get("chargingStatus",{})
                ev = data.get("vehiclestatus",{}).get("elVehDTE",{})
                bat= data.get("vehiclestatus",{}).get("batteryFillLevel",{})
                out[vin] = {
                    "soc_pct":    _f(bat.get("value")),
                    "range_km":   _f(ev.get("value"), 1.60934),
                    "charging":   cs.get("value") == "ChargingAC",
                    "plugged_in": cs.get("value") not in ("EvseNotDetected","",None),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Mercedes-Benz me connect
# ═══════════════════════════════════════════════════════════════════
@register_provider("mercedes")
class MercedesProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "mercedes"
    DISPLAY_NAME = "Mercedes me connect"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://api.mercedes-benz.com/vehicledata/v2"
    TOKEN_URL    = "https://id.mercedes-benz.com/as/token.oauth2"
    CLIENT_ID    = "01398c1c-dc45-4b42-882b-9f5ba9f175f1"

    UPDATE_HINTS = {
        "docs":    "https://developer.mercedes-benz.com/apis/vehicle_status_api/apiref",
        "ha_repo": "https://github.com/ReneNulschDE/mbapi2020",
        "note":    "Officiële Mercedes Vehicle Status API. Vereist developer account.",
    }

    async def async_setup(self) -> bool:
        self._init_store("mercedes")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/vehicles", headers=self._auth_header())
        if data is None:
            return False
        self._cache["vehicles"] = data if isinstance(data, list) else []
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("id",""),
                        f"Mercedes {v.get('id','')}",{"vin": v.get("id","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("id","")
            data = await self._get(f"{self.BASE}/vehicles/{vin}/resources/soc/value",
                                   headers=self._auth_header())
            rng  = await self._get(f"{self.BASE}/vehicles/{vin}/resources/rangeelectric/value",
                                   headers=self._auth_header())
            if data:
                out[vin] = {
                    "soc_pct":  _f(data.get("soc",{}).get("value")),
                    "range_km": _f((rng or {}).get("rangeelectric",{}).get("value")),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Volvo Cars API
# ═══════════════════════════════════════════════════════════════════
@register_provider("volvo")
class VolvoProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "volvo"
    DISPLAY_NAME = "Volvo Cars"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://api.volvocars.com/connected-vehicle/v2"
    TOKEN_URL    = "https://volvoid.eu.volvocars.com/as/token.oauth2"
    CLIENT_ID    = "h4Yf0bos360FFPin2dna5270VlkUm7yd"

    UPDATE_HINTS = {
        "docs":    "https://developer.volvocars.com/apis/connected-vehicle/v2/overview/",
        "ha_repo": "https://github.com/thomasddn/ha-volvo-cars",
        "note":    "Officiële Volvo Connected Vehicle API. Gratis developer account.",
    }

    async def async_setup(self) -> bool:
        self._init_store("volvo")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/vehicles",
                                headers={**self._auth_header(),
                                         "vcc-api-key": self._credentials.get("vcc_api_key","")})
        if data is None:
            return False
        self._cache["vehicles"] = data.get("data",[])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("vin",""),
                        f"Volvo {v.get('descriptions',{}).get('model',v.get('vin',''))}",
                        {"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vin  = v.get("vin","")
            vcc  = self._credentials.get("vcc_api_key","")
            h    = {**self._auth_header(), "vcc-api-key": vcc}
            bat  = await self._get(f"{self.BASE}/vehicles/{vin}/recharge-status", headers=h)
            if bat:
                d = bat.get("data",{})
                out[vin] = {
                    "soc_pct":        _f(d.get("batteryChargeLevel",{}).get("value")),
                    "range_km":       _f(d.get("electricRange",{}).get("value")),
                    "charging":       d.get("chargingSystemStatus",{}).get("value") == "CHARGING",
                    "charge_power_w": _f(d.get("chargingCurrentAmps",{}).get("value"), 230),
                    "plugged_in":     d.get("chargingConnectionStatus",{}).get("value") == "CONNECTED",
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Rivian — GraphQL API
# ═══════════════════════════════════════════════════════════════════
@register_provider("rivian")
class RivianProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "rivian"
    DISPLAY_NAME = "Rivian"
    CATEGORY     = "ev"
    ICON         = "mdi:car-electric"
    BASE         = "https://rivian.com/api/gql/gateway/graphql"
    TOKEN_URL    = "https://rivian.com/api/gql/gateway/graphql"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/bretterer/rivian-python-client",
        "community":"https://github.com/the-rccg/rivian_api",
        "note":     "GraphQL. Authenticatie via mutation loginWithOTP.",
    }

    async def async_setup(self) -> bool:
        self._init_store("rivian")
        # Stap 1: login
        q = '''mutation Login($email:String!,$password:String!){
            login(email:$email,password:$password){accessToken refreshToken}
        }'''
        resp = await self._post(self.BASE, json_={
            "query": q,
            "variables": {"email": self._credentials.get("username",""),
                          "password": self._credentials.get("password","")}
        })
        if not resp:
            return False
        tokens = resp.get("data",{}).get("login",{})
        if not tokens.get("accessToken"):
            self._last_error = "Rivian login mislukt"
            return False
        self._tokens = {"access_token": tokens["accessToken"],
                        "refresh_token": tokens.get("refreshToken",""),
                        "token_type": "Bearer",
                        "expires_at": time.time() + 3600}
        # Stap 2: vehicles
        vq = '''query GetUserInfo{currentUser{vehicles{id name vin}}}'''
        vdata = await self._post(self.BASE, json_={"query": vq},
                                 headers=self._auth_header())
        if vdata:
            self._cache["vehicles"] = (vdata.get("data",{})
                                            .get("currentUser",{})
                                            .get("vehicles",[]))
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_ev_dev(self.PROVIDER_ID, v.get("id",""),
                        v.get("name", f"Rivian {v.get('vin','')}"),{"vin": v.get("vin","")})
                for v in self._cache.get("vehicles", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for v in self._cache.get("vehicles", []):
            vid = v.get("id","")
            q   = f'''query GetVehicleState($vehicleID:String!){{
                getVehicleState(id:$vehicleID){{
                    batteryLevel chargerStatus chargerDerate rangeThreshold
                }}
            }}'''
            data = await self._post(self.BASE,
                                    json_={"query": q, "variables": {"vehicleID": vid}},
                                    headers=self._auth_header())
            if data:
                vs = data.get("data",{}).get("getVehicleState",{})
                out[vid] = {
                    "soc_pct":    _f(vs.get("batteryLevel")),
                    "charging":   vs.get("chargerStatus") in ("charging_active","chrgr_sts_charging"),
                    "plugged_in": vs.get("chargerStatus") not in ("chrgr_sts_not_connected","",None),
                }
        return out
