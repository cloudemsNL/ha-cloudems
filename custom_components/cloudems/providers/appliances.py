# -*- coding: utf-8 -*-
"""
CloudEMS Appliance Providers  v1.0.0
======================================
Slimme huishoudapparaten: wasmachines, drogers, vaatwassers,
warmtepompen en boilers — allemaal via cloud API.

Providers:
  HomeConnectProvider  — BSH (Bosch, Siemens, Neff, Gaggenau, Thermador)
  AristonProvider      — Ariston boilers & warmtepompen (NET remotethermo v3)
  MieleProvider        — Miele@home cloud API
  ElectroluxProvider   — Electrolux, AEG, Frigidaire (Electrolux Group API)
  CandyHaierProvider   — Candy Simply-Fi / Haier cloud

Genormaliseerde data per poll():
  state, program, remaining_minutes, power_w, door_open,
  remote_start_enabled, cycle_count

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base import CloudEMSProvider, OAuth2Mixin, ProviderDevice, register_provider

_LOGGER = logging.getLogger(__name__)


def _app_dev(pid, did, name, dtype, attrs) -> ProviderDevice:
    return ProviderDevice(pid, did, name, dtype, True, attrs)

def _f(v, factor=1.0, dec=1) -> Optional[float]:
    try:
        return round(float(v) * factor, dec)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════
# HomeConnect (BSH: Bosch, Siemens, Neff, Gaggenau, Thermador)
# ═══════════════════════════════════════════════════════════════════
@register_provider("homeconnect")
class HomeConnectProvider(CloudEMSProvider, OAuth2Mixin):
    """
    BSH Home Connect API — officieel en gedocumenteerd.
    Werkt voor: Bosch, Siemens, Neff, Gaggenau, Thermador.
    Apparaten: wasmachine, droger, vaatwasser, oven, koelkast.
    """
    PROVIDER_ID  = "homeconnect"
    DISPLAY_NAME = "BSH Home Connect (Bosch/Siemens)"
    CATEGORY     = "appliance"
    ICON         = "mdi:washing-machine"
    BASE         = "https://api.home-connect.com/api"
    TOKEN_URL    = "https://api.home-connect.com/security/oauth/token"

    UPDATE_HINTS = {
        "docs":     "https://api-docs.home-connect.com/",
        "ha_repo":  "https://github.com/home-assistant/core/tree/dev/homeassistant/components/home_connect",
        "sdk":      "https://api-docs.home-connect.com/#sdk-home-connect-python-sdk",
        "scopes":   "IdentifyAppliance Monitor Control Settings",
        "endpoints":{
            "appliances":  "GET /api/homeappliances",
            "status":      "GET /api/homeappliances/{ha_id}/status",
            "programs":    "GET /api/homeappliances/{ha_id}/programs/active",
            "start":       "PUT /api/homeappliances/{ha_id}/programs/active",
            "settings":    "GET /api/homeappliances/{ha_id}/settings",
            "events_sse":  "GET /api/homeappliances/{ha_id}/events  (SSE stream)",
        },
        "note": "Officiële API. Developer-sandbox beschikbaar op api-docs.home-connect.com",
    }

    # Mapping HomeConnect device types → CloudEMS types
    _TYPE_MAP = {
        "Washer": "washer", "Dryer": "dryer", "Dishwasher": "dishwasher",
        "WasherDryer": "washer_dryer", "Oven": "oven", "Refrigerator": "refrigerator",
        "FreezerCombination": "fridge_freezer", "CoffeeMaker": "coffee",
    }

    async def async_setup(self) -> bool:
        self.CLIENT_ID     = self._credentials.get("client_id", "")
        self.CLIENT_SECRET = self._credentials.get("client_secret", "")
        self._init_store("homeconnect")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/homeappliances",
                                headers=self._auth_header())
        if data is None:
            return False
        self._cache["appliances"] = data.get("data", {}).get("homeappliances", [])
        await self._save({"tokens": self._tokens})
        self._api_ok = True
        _LOGGER.info("HomeConnect: %d apparaat/apparaten", len(self._cache["appliances"]))
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        devices = []
        for a in self._cache.get("appliances", []):
            ha_id = a.get("haId", "")
            dtype = self._TYPE_MAP.get(a.get("type",""), "appliance")
            devices.append(_app_dev(
                self.PROVIDER_ID, ha_id,
                f"{a.get('brand','')} {a.get('name',a.get('type',''))}",
                dtype,
                {"ha_id": ha_id, "brand": a.get("brand",""),
                 "type": a.get("type",""), "e_number": a.get("enumber",""),
                 "connected": a.get("connected", True)},
            ))
        return devices

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for a in self._cache.get("appliances", []):
            ha_id = a.get("haId","")
            if not a.get("connected", True):
                out[ha_id] = {"state": "offline"}
                continue

            status = await self._get(f"{self.BASE}/homeappliances/{ha_id}/status",
                                     headers=self._auth_header())
            program= await self._get(f"{self.BASE}/homeappliances/{ha_id}/programs/active",
                                     headers=self._auth_header())

            status_items = {}
            if status and status.get("data"):
                for item in status["data"].get("status", []):
                    key = item.get("key","").split(".")[-1]   # bijv. BSH.Common.Status.DoorState → DoorState
                    status_items[key] = item.get("value")

            prog_data  = (program or {}).get("data", {}).get("program", {}) if program else {}
            prog_opts  = {o.get("key","").split(".")[-1]: o.get("value")
                          for o in prog_data.get("options", [])}

            out[ha_id] = {
                "state":             status_items.get("OperationState","unknown"),
                "door_open":         status_items.get("DoorState") == "BSH.Common.EnumType.DoorState.Open",
                "remote_start_enabled": status_items.get("RemoteControlStartAllowed", False),
                "program":           prog_data.get("key","").split(".")[-1],
                "remaining_minutes": _f(prog_opts.get("RemainingProgramTime"), 1/60, 0),
                "progress_pct":      _f(prog_opts.get("ProgramProgress")),
            }
        return out

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        """
        Commando's: "remote_start", "stop", "set_option"
        """
        p = params or {}
        if command == "stop":
            r = await self._delete(f"{self.BASE}/homeappliances/{device_id}/programs/active")
            return bool(r)
        elif command == "remote_start":
            program_key = p.get("program_key", "")
            options     = p.get("options", [])
            body = {"data": {"key": program_key, "options": options}}
            r = await self._put(f"{self.BASE}/homeappliances/{device_id}/programs/active",
                                json_=body)
            return bool(r)
        return False

    async def _put(self, url: str, json_: dict) -> Optional[Any]:
        self._tick()
        try:
            async with self._sess().put(url, json=json_, headers=self._auth_header(),
                                         timeout=__import__("aiohttp").ClientTimeout(total=15)) as r:
                return {"ok": True} if r.status in (200,204) else None
        except Exception as e:
            self._last_error = str(e)
            return None

    async def _delete(self, url: str) -> Optional[Any]:
        self._tick()
        try:
            async with self._sess().delete(url, headers=self._auth_header(),
                                            timeout=__import__("aiohttp").ClientTimeout(total=15)) as r:
                return {"ok": True} if r.status in (200,204) else None
        except Exception as e:
            self._last_error = str(e)
            return None


# ═══════════════════════════════════════════════════════════════════
# Ariston NET remotethermo v3
# ═══════════════════════════════════════════════════════════════════
@register_provider("ariston")
class AristonProvider(CloudEMSProvider, OAuth2Mixin):
    """
    Ariston NET remotethermo API v3.
    Gebaseerd op: fustom/ariston-remotethermo-home-assistant-v3
    Werkt voor: Ariston boilers, Genus One, Alteas One, warmtepompen.
    """
    PROVIDER_ID  = "ariston"
    DISPLAY_NAME = "Ariston NET remotethermo"
    CATEGORY     = "heating"
    ICON         = "mdi:water-boiler"
    BASE         = "https://www.ariston-net.remotethermo.com/api/v2"
    TOKEN_URL    = "https://www.ariston-net.remotethermo.com/api/v2/accounts/login"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/fustom/ariston-remotethermo-home-assistant-v3",
        "pypi":     "https://pypi.org/project/aristonremotethermo/",
        "api_ref":  "https://www.ariston-net.remotethermo.com/api/v2",
        "endpoints":{
            "login":       "POST /api/v2/accounts/login",
            "plants":      "GET  /api/v2/remote/plants",
            "plant_data":  "GET  /api/v2/remote/plants/{gw}/reports",
            "ch_data":     "GET  /api/v2/remote/plants/{gw}/measurements",
            "set_mode":    "POST /api/v2/remote/plants/{gw}/mode",
            "set_temp":    "POST /api/v2/remote/plants/{gw}/dhw/temperature",
            "dhw":         "POST /api/v2/remote/plants/{gw}/dhw/switch",
        },
        "note": "Ariston gebruikt eigen token (geen OAuth2). Zie ha_repo voor details.",
    }

    async def async_setup(self) -> bool:
        self._init_store("ariston")
        saved = await self._load()
        self._ariston_token = saved.get("token", "")

        if not self._ariston_token:
            ok = await self._ariston_login()
            if not ok:
                return False
        plants = await self._get_plants()
        if plants is None:
            # Token verlopen → opnieuw inloggen
            ok = await self._ariston_login()
            if not ok:
                return False
            plants = await self._get_plants()
        if plants is None:
            self._last_error = "Ariston: geen installaties gevonden"
            return False
        self._cache["plants"] = plants
        await self._save({"token": self._ariston_token})
        self._api_ok = True
        _LOGGER.info("Ariston: %d installatie(s)", len(plants))
        return True

    async def _ariston_login(self) -> bool:
        resp = await self._post(
            self.TOKEN_URL,
            json_={"usr": self._credentials.get("username",""),
                   "pwd": self._credentials.get("password",""),
                   "imp": False, "notTrack": True},
        )
        if resp and resp.get("token"):
            self._ariston_token = resp["token"]
            return True
        self._last_error = "Ariston login mislukt"
        return False

    def _ah(self) -> dict:
        return {"ar.authToken": self._ariston_token}

    async def _get_plants(self) -> Optional[list]:
        data = await self._get(f"{self.BASE}/remote/plants", headers=self._ah())
        return data if isinstance(data, list) else None

    async def async_get_devices(self) -> List[ProviderDevice]:
        devices = []
        for p in self._cache.get("plants", []):
            gw   = p.get("gw","")
            name = p.get("name", f"Ariston {gw}")
            devices.append(_app_dev(
                self.PROVIDER_ID, gw, name, "boiler",
                {"gateway": gw, "plant_type": p.get("plantType",""),
                 "has_dhw": p.get("hasDhw", False),
                 "has_ch": p.get("hasCh", False)},
            ))
        return devices

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for p in self._cache.get("plants", []):
            gw = p.get("gw","")

            # Metingen ophalen
            meas = await self._get(f"{self.BASE}/remote/plants/{gw}/measurements",
                                   headers=self._ah())
            # Rapport (modus, temp instelling etc.)
            report = await self._get(f"{self.BASE}/remote/plants/{gw}/reports",
                                     headers=self._ah())
            # Flame / status
            data_items = {}
            if meas:
                for item in (meas if isinstance(meas, list) else []):
                    data_items[item.get("id","")] = item.get("value")

            r = report or {}
            out[gw] = {
                # CV / verwarming
                "ch_temp_c":          _f(data_items.get("ChOutTemperature") or r.get("chOutTemperature")),
                "ch_setpoint_c":      _f(r.get("chSetTemperature")),
                "ch_mode":            r.get("chMode",""),
                "ch_active":          bool(r.get("chOn", False)),
                # Warm water (DHW)
                "dhw_temp_c":         _f(data_items.get("DhwTemperature") or r.get("dhwTemperature")),
                "dhw_setpoint_c":     _f(r.get("dhwSetTemperature")),
                "dhw_comfort_active": bool(r.get("dhwComfortActive", False)),
                "dhw_active":         bool(r.get("dhwOn", False)),
                # Algemeen
                "flame_on":           bool(r.get("flameOn", False)),
                "outside_temp_c":     _f(data_items.get("OutdoorTemperature") or r.get("outsideTemperature")),
                "mode":               r.get("mode",""),
                "plant_mode":         r.get("plantMode",""),
                "online":             True,
            }
        return out

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        p = params or {}
        gw = device_id

        if command == "set_ch_setpoint":
            r = await self._post(f"{self.BASE}/remote/plants/{gw}/comfort/ch",
                                 json_={"new": {"comfortTemp": p.get("temperature", 20.0)}},
                                 headers=self._ah())
            return bool(r)

        elif command == "set_dhw_setpoint":
            r = await self._post(f"{self.BASE}/remote/plants/{gw}/comfort/dhw",
                                 json_={"new": {"comfortTemp": p.get("temperature", 55.0)}},
                                 headers=self._ah())
            return bool(r)

        elif command == "set_mode":
            # mode: "heating_only" | "cooling" | "summer" | "winter" | "off"
            r = await self._post(f"{self.BASE}/remote/plants/{gw}/mode",
                                 json_={"new": p.get("mode","heating_only")},
                                 headers=self._ah())
            return bool(r)

        elif command == "dhw_switch":
            r = await self._post(f"{self.BASE}/remote/plants/{gw}/dhw/switch",
                                 json_={"new": p.get("on", True)},
                                 headers=self._ah())
            return bool(r)

        elif command == "set_plant_mode":
            r = await self._post(f"{self.BASE}/remote/plants/{gw}/plantMode",
                                 json_={"new": p.get("plant_mode", "manual")},
                                 headers=self._ah())
            return bool(r)

        return False


# ═══════════════════════════════════════════════════════════════════
# Miele@home cloud API
# ═══════════════════════════════════════════════════════════════════
@register_provider("miele")
class MieleProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "miele"
    DISPLAY_NAME = "Miele@home"
    CATEGORY     = "appliance"
    ICON         = "mdi:washing-machine"
    BASE         = "https://api.mcs3.miele.com/v1"
    TOKEN_URL    = "https://api.mcs3.miele.com/thirdparty/login"
    CLIENT_ID    = ""  # Vereist Miele developer account

    UPDATE_HINTS = {
        "docs":    "https://www.miele.com/developer/",
        "ha_repo": "https://github.com/astrandb/miele",
        "scopes":  "details actions events",
        "note":    "Vereist Miele developer account op www.miele.com/developer",
        "endpoints":{
            "devices":   "GET /v1/devices",
            "state":     "GET /v1/devices/{id}/state",
            "actions":   "GET /v1/devices/{id}/actions",
            "start":     "PUT /v1/devices/{id}/programs",
        },
    }

    _STATUS_MAP = {1:"off", 2:"on", 3:"programmed", 4:"waiting_to_start", 5:"running",
                   6:"pause", 7:"end", 9:"error", 12:"rinse_hold"}

    async def async_setup(self) -> bool:
        self.CLIENT_ID     = self._credentials.get("client_id","")
        self.CLIENT_SECRET = self._credentials.get("client_secret","")
        self._init_store("miele")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/devices", headers=self._auth_header())
        if data is None:
            return False
        self._cache["devices"] = data
        self._api_ok = True
        _LOGGER.info("Miele: %d apparaat/apparaten", len(data))
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        devices = []
        for did, dev in (self._cache.get("devices") or {}).items():
            ident = dev.get("ident",{})
            dtype = ident.get("type",{}).get("value_raw",0)
            dtype_map = {1:"washer",2:"dryer",7:"dishwasher",12:"oven",18:"fridge"}
            devices.append(_app_dev(
                self.PROVIDER_ID, did,
                ident.get("deviceName", f"Miele {did}"),
                dtype_map.get(dtype, "appliance"),
                {"model": ident.get("type",{}).get("value_localized",""),
                 "device_type_raw": dtype}
            ))
        return devices

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for did in (self._cache.get("devices") or {}):
            data = await self._get(f"{self.BASE}/devices/{did}/state",
                                   headers=self._auth_header())
            if data:
                status = data.get("status",{}).get("value_raw",0)
                prog   = data.get("ProgramID",{})
                remain = data.get("remainingTime",[0,0])
                out[did] = {
                    "state":              self._STATUS_MAP.get(status, f"raw:{status}"),
                    "program":            prog.get("value_localized",""),
                    "remaining_minutes":  remain[0] * 60 + remain[1] if remain else None,
                    "door_open":          data.get("doorState",{}).get("value_raw") == 1,
                    "temperature_target": _f(data.get("targetTemperature",[{}])[0].get("value_raw") if data.get("targetTemperature") else None, 0.01),
                }
        return out

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        p = params or {}
        if command == "start":
            r = await self._post(f"{self.BASE}/devices/{device_id}/actions",
                                 json_={"processAction": 1},
                                 headers=self._auth_header())
            return bool(r)
        elif command == "stop":
            r = await self._post(f"{self.BASE}/devices/{device_id}/actions",
                                 json_={"processAction": 2},
                                 headers=self._auth_header())
            return bool(r)
        return False


# ═══════════════════════════════════════════════════════════════════
# Electrolux / AEG / Frigidaire — Electrolux Group API
# ═══════════════════════════════════════════════════════════════════
@register_provider("electrolux")
@register_provider("aeg")
class ElectroluxAEGProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "electrolux"
    DISPLAY_NAME = "Electrolux / AEG"
    CATEGORY     = "appliance"
    ICON         = "mdi:washing-machine"
    BASE         = "https://api.developer.electrolux.one/api/v1"
    TOKEN_URL    = "https://api.developer.electrolux.one/api/v1/token"

    UPDATE_HINTS = {
        "docs":    "https://developer.electrolux.one/",
        "ha_repo": "https://github.com/albinmedoc/ha-cleanmate",  # zelfde API patroon
        "note":    "Electrolux Group API — zelfde voor AEG, Frigidaire. Vereist developer account.",
        "endpoints":{
            "appliances": "GET /api/v1/appliances",
            "state":      "GET /api/v1/appliances/{id}/state",
            "command":    "PUT /api/v1/appliances/{id}/command",
        },
    }

    async def async_setup(self) -> bool:
        self.CLIENT_ID     = self._credentials.get("client_id","")
        self.CLIENT_SECRET = self._credentials.get("client_secret","")
        self._api_key      = self._credentials.get("api_key","")
        self._init_store("electrolux")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/appliances",
                                headers={**self._auth_header(), "x-api-key": self._api_key})
        if data is None:
            return False
        self._cache["appliances"] = data if isinstance(data, list) else data.get("appliances", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        dtype_map = {"WM":"washer","TD":"dryer","DW":"dishwasher","OV":"oven","AC":"air_conditioner"}
        return [_app_dev(
            self.PROVIDER_ID, a.get("applianceId",""),
            a.get("applianceName", a.get("modelName","Electrolux")),
            dtype_map.get(a.get("applianceType","")[:2],"appliance"),
            {"model": a.get("modelName",""), "type": a.get("applianceType","")})
            for a in self._cache.get("appliances",[])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for a in self._cache.get("appliances",[]):
            aid  = a.get("applianceId","")
            data = await self._get(f"{self.BASE}/appliances/{aid}/state",
                                   headers={**self._auth_header(), "x-api-key": self._api_key})
            if data:
                props = data.get("properties", data.get("reported",{}))
                out[aid] = {
                    "state":             props.get("ApplianceState","unknown"),
                    "program":           props.get("CyclePhase", props.get("DisplayProgram","")),
                    "remaining_minutes": _f(props.get("TimeToEnd")),
                    "door_open":         props.get("DoorState") == "Open",
                    "remote_start_enabled": props.get("RemoteControl", False),
                }
        return out

    async def async_send_command(self, device_id: str, command: str,
                                  params: Optional[Dict[str, Any]] = None) -> bool:
        if command in ("start","stop","pause"):
            cmd_map = {"start": "START","stop":"STOP","pause":"PAUSE"}
            r = await self._put_cmd(device_id, {"ApplianceState": cmd_map[command]})
            return bool(r)
        return False

    async def _put_cmd(self, device_id: str, body: dict) -> Optional[Any]:
        self._tick()
        import aiohttp
        try:
            async with self._sess().put(
                f"{self.BASE}/appliances/{device_id}/command",
                json=body,
                headers={**self._auth_header(), "x-api-key": self._api_key},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                return {"ok": True} if r.status in (200,204) else None
        except Exception as e:
            self._last_error = str(e)
            return None


# ═══════════════════════════════════════════════════════════════════
# Candy Simply-Fi / Haier hOn
# ═══════════════════════════════════════════════════════════════════
@register_provider("candy")
@register_provider("haier")
class CandyHaierProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "candy"
    DISPLAY_NAME = "Candy Simply-Fi / Haier hOn"
    CATEGORY     = "appliance"
    ICON         = "mdi:washing-machine"
    BASE_CANDY   = "https://Simply-Fi-prod.haiereurope.com/api"
    BASE_HAIER   = "https://account.haier.com"
    TOKEN_URL    = "https://Simply-Fi-prod.haiereurope.com/api/accounts/login"

    UPDATE_HINTS = {
        "ha_repo":  "https://github.com/Andre0512/hon",
        "pypi":     "https://pypi.org/project/pyhon/",
        "note":     "pyhon library reverse-engineered Haier hOn. Candy gebruikt zelfde API.",
        "brand_map":"Candy, Hoover, Haier, Rosieres, Kelvinator, Simpson",
    }

    async def async_setup(self) -> bool:
        self._init_store("candy_haier")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        is_haier = self._credentials.get("brand","candy").lower() == "haier"
        if is_haier:
            # Haier hOn authenticatie (complexer)
            ok = await self._haier_login()
        else:
            # Candy Simply-Fi
            ok = await self._pw_grant(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE_CANDY}/appliances",
                                headers=self._auth_header())
        if data is None:
            return False
        self._cache["appliances"] = (data.get("payload",{}).get("appliances",{})
                                         .get("content",[]) if data else [])
        self._api_ok = True
        return True

    async def _haier_login(self) -> bool:
        # Haier gebruikt een custom login flow — vereenvoudigd
        resp = await self._post(
            f"{self.BASE_HAIER}/oauth/oauth/token",
            data={"username": self._credentials.get("username",""),
                  "password": self._credentials.get("password",""),
                  "grant_type": "password",
                  "client_id": "haier_eu_mobile"},
        )
        if resp and resp.get("access_token"):
            self._store_tokens(resp)
            return True
        return False

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_app_dev(
            self.PROVIDER_ID, a.get("applId",""),
            a.get("nickName", a.get("modelName","Candy/Haier")),
            "appliance",
            {"model": a.get("modelName",""), "type": a.get("applianceTypeDescription","")})
            for a in self._cache.get("appliances",[])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for a in self._cache.get("appliances",[]):
            aid  = a.get("applId","")
            data = await self._get(f"{self.BASE_CANDY}/appliances/{aid}/context",
                                   headers=self._auth_header())
            if data:
                ctx  = data.get("payload",{}).get("appliance",{})
                pars = {p.get("parName",""):p.get("parValue") for p in ctx.get("parameters",[])}
                out[aid] = {
                    "state":             pars.get("MachMd","unknown"),
                    "program":           pars.get("PrCode",""),
                    "remaining_minutes": _f(pars.get("RemTime")),
                    "door_open":         pars.get("DoorState","0") == "1",
                    "spin_speed":        _f(pars.get("SpinSp")),
                    "temperature":       _f(pars.get("TempSel")),
                }
        return out
