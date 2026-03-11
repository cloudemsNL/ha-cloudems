# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS PV Inverter Providers  v1.0.0
=======================================
Cloud-API omvormer integraties. Geen lokale Modbus nodig.
Werkt ook in de hosted cloud-variant.

Providers: SolarEdge · Enphase · SMA · Fronius · Huawei FusionSolar
           GoodWe SEMS · Growatt · Solis · Deye/Sunsynk (SolarmanPV)

UPDATE-HINTS per klasse → UPDATE_HINTS dict bevat alle links die je
nodig hebt om bij API-wijzigingen de juiste repo/docs te raadplegen.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import CloudEMSProvider, OAuth2Mixin, ProviderDevice, register_provider

_LOGGER = logging.getLogger(__name__)


def _dev(pid, did, name, attrs) -> ProviderDevice:
    return ProviderDevice(pid, did, name, "inverter",
                          attrs.get("status", "ok") != "offline", attrs)

def _f(v, factor=1.0, dec=2) -> Optional[float]:
    try:
        return round(float(v) * factor, dec)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════
# SolarEdge
# ═══════════════════════════════════════════════════════════════════
@register_provider("solaredge")
class SolarEdgeProvider(CloudEMSProvider):
    PROVIDER_ID  = "solaredge"
    DISPLAY_NAME = "SolarEdge"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://monitoringapi.solaredge.com"

    UPDATE_HINTS = {
        "docs":      "https://developers.solaredge.com/",
        "ha_repo":   "https://github.com/WillCodeForCats/solaredge-modbus-multi",
        "rate_limit":"300 calls/dag per API-key",
        "endpoints": {
            "sites":   "GET /sites/list?api_key=KEY",
            "power":   "GET /site/{id}/currentPowerFlow?api_key=KEY",
            "energy":  "GET /site/{id}/energy?api_key=KEY",
        },
    }

    async def async_setup(self) -> bool:
        self._key = self._credentials.get("api_key", "")
        if not self._key:
            self._last_error = "Geen SolarEdge API key"
            return False
        self._init_store("solaredge")
        self._cache = await self._load()
        sites = await self._get(f"{self.BASE}/sites/list",
                                params={"api_key": self._key, "size": 100})
        if not sites:
            return False
        self._cache["sites"] = sites.get("sites", {}).get("site", [])
        self._api_ok = True
        _LOGGER.info("SolarEdge: %d site(s)", len(self._cache["sites"]))
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(s.get("id","")),
                     s.get("name","SolarEdge"),
                     {"peak_kwp": _f(s.get("peakPower"))})
                for s in self._cache.get("sites", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("sites", []):
            sid  = str(s.get("id",""))
            data = await self._get(f"{self.BASE}/site/{sid}/currentPowerFlow",
                                   params={"api_key": self._key})
            if not data:
                continue
            flow = data.get("siteCurrentPowerFlow", {})
            out[sid] = {
                "power_w":   _f(flow.get("PV",{}).get("currentPower"), 1000),
                "grid_w":    _f(flow.get("GRID",{}).get("currentPower"), 1000),
                "load_w":    _f(flow.get("LOAD",{}).get("currentPower"), 1000),
                "battery_w": _f(flow.get("STORAGE",{}).get("currentPower"), 1000),
            }
        self._cache["_last_ts"] = time.time()
        return out


# ═══════════════════════════════════════════════════════════════════
# Enphase
# ═══════════════════════════════════════════════════════════════════
@register_provider("enphase")
class EnphaseProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "enphase"
    DISPLAY_NAME = "Enphase Enlighten"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-panel"
    BASE         = "https://api.enphaseenergy.com/api/v4"
    TOKEN_URL    = "https://api.enphaseenergy.com/oauth/token"

    UPDATE_HINTS = {
        "docs":    "https://developer-v4.enphase.com/docs.html",
        "ha_repo": "https://github.com/vincentwolsink/home_assistant_enphase_envoy",
        "note":    "v4 vereist app-registratie op developer-v4.enphase.com",
    }

    async def async_setup(self) -> bool:
        self.CLIENT_ID     = self._credentials.get("client_id", "")
        self.CLIENT_SECRET = self._credentials.get("client_secret", "")
        self._init_store("enphase")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/systems",
                                headers=self._auth_header(),
                                params={"key": self._credentials.get("api_key","")})
        if data is None:
            return False
        self._cache["systems"] = data.get("systems", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(s.get("system_id","")),
                     s.get("name","Enphase"), {"modules": s.get("modules",0)})
                for s in self._cache.get("systems", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("systems", []):
            sid  = str(s.get("system_id",""))
            data = await self._get(f"{self.BASE}/systems/{sid}/summary",
                                   headers=self._auth_header(),
                                   params={"key": self._credentials.get("api_key","")})
            if data:
                out[sid] = {"power_w": _f(data.get("current_power")),
                            "energy_today_wh": _f(data.get("energy_today")),
                            "status": data.get("status","normal")}
        return out


# ═══════════════════════════════════════════════════════════════════
# SMA Sunny Portal / ennexOS
# ═══════════════════════════════════════════════════════════════════
@register_provider("sma")
class SMAProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "sma"
    DISPLAY_NAME = "SMA Sunny Portal"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power-variant"
    BASE         = "https://ennexos.sunnyportal.com/api"
    TOKEN_URL    = "https://ennexos.sunnyportal.com/api/v1/token"
    CLIENT_ID    = "iOS-v1.0.5"

    UPDATE_HINTS = {
        "docs":    "https://developer.sma.de/",
        "ha_repo": "https://github.com/austinmroczek/home-assistant-sunny-home-manager",
        "note":    "API is reverse-engineered. Controleer ha_repo bij updates.",
        "endpoints": {
            "token":  "POST /api/v1/token",
            "plants": "GET  /api/v1/plants",
            "live":   "GET  /api/v1/plants/{id}/livedata/overview",
        },
    }

    async def async_setup(self) -> bool:
        self._init_store("sma")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        ok = await self._ensure_token(self._credentials.get("username",""),
                                       self._credentials.get("password",""))
        if not ok:
            return False
        data = await self._get(f"{self.BASE}/v1/plants", headers=self._auth_header())
        if data is None:
            return False
        self._cache["plants"] = data.get("plants", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(p.get("plantId","")),
                     p.get("name","SMA omvormer"), {})
                for p in self._cache.get("plants", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for p in self._cache.get("plants", []):
            pid  = str(p.get("plantId",""))
            data = await self._get(f"{self.BASE}/v1/plants/{pid}/livedata/overview",
                                   headers=self._auth_header())
            if data:
                vals = {v.get("channelId"): v.get("value") for v in data.get("values",[])}
                out[pid] = {
                    "power_w":      _f(vals.get("PvGen:Power")),
                    "battery_soc":  _f(vals.get("Bat:SoC")),
                    "grid_feed_w":  _f(vals.get("GridMs:TotWOut")),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Fronius Solar.web
# ═══════════════════════════════════════════════════════════════════
@register_provider("fronius")
class FroniusProvider(CloudEMSProvider):
    PROVIDER_ID  = "fronius"
    DISPLAY_NAME = "Fronius Solar.web"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-panel-large"
    BASE         = "https://api.solarweb.com/swqapi"

    UPDATE_HINTS = {
        "docs":    "https://api.solarweb.com/swqapi",
        "ha_repo": "https://github.com/farmio/ha-fronius",
        "pypi":    "https://pypi.org/project/pyfronius/",
        "note":    "Gebruikt accessKeyId + accessKeyValue headers, geen OAuth.",
    }

    async def async_setup(self) -> bool:
        self._kid = self._credentials.get("access_key_id","")
        self._kv  = self._credentials.get("access_key_value","")
        if not self._kid:
            self._last_error = "Geen Fronius accessKeyId"
            return False
        data = await self._get(f"{self.BASE}/pvsystems",
                                headers={"AccessKeyId": self._kid, "AccessKeyValue": self._kv})
        if data is None:
            return False
        self._cache["systems"] = data.get("pvSystems", [])
        self._api_ok = True
        return True

    def _h(self) -> dict:
        return {"AccessKeyId": self._kid, "AccessKeyValue": self._kv}

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, s.get("pvSystemId",""),
                     s.get("name","Fronius"), {"peak_kwp": _f(s.get("peakPower"))})
                for s in self._cache.get("systems", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("systems", []):
            sid  = s.get("pvSystemId","")
            data = await self._get(f"{self.BASE}/pvsystems/{sid}/flowdata", headers=self._h())
            if data:
                ch = {c.get("channelName"): c.get("value")
                      for c in data.get("channels",[])}
                out[sid] = {
                    "power_w":    _f(ch.get("PowerProductionTotal"), 1000),
                    "grid_w":     _f(ch.get("PowerGrid"), 1000),
                    "battery_soc":_f(ch.get("StateOfCharge_Rel")),
                }
        return out


# ═══════════════════════════════════════════════════════════════════
# Huawei FusionSolar
# ═══════════════════════════════════════════════════════════════════
@register_provider("huawei_solar")
class HuaweiSolarProvider(CloudEMSProvider):
    PROVIDER_ID  = "huawei_solar"
    DISPLAY_NAME = "Huawei FusionSolar"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://eu5.fusionsolar.huawei.com/thirdData"

    UPDATE_HINTS = {
        "docs":    "https://intl.fusionsolar.huawei.com/pvmswebsite/nologin/assets/config/openApiDoc.html",
        "ha_repo": "https://github.com/wlcrs/huawei_solar",
        "note":    "Vereist xsrf-token na login. Zie ha_repo voor details.",
    }

    async def async_setup(self) -> bool:
        self._init_store("huawei_solar")
        resp = await self._post(f"{self.BASE}/login",
                                json_={"userName": self._credentials.get("username",""),
                                       "systemCode": self._credentials.get("password","")})
        if not (resp and resp.get("success")):
            self._last_error = "Huawei login mislukt"
            return False
        data = await self._post(f"{self.BASE}/getStationList", json_={})
        if not (data and data.get("success")):
            return False
        self._cache["stations"] = data.get("data", [])
        self._api_ok = True
        _LOGGER.info("Huawei FusionSolar: %d station(s)", len(self._cache["stations"]))
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(s.get("stationCode","")),
                     s.get("stationName","Huawei"),
                     {"capacity_kwp": _f(s.get("capacity"))})
                for s in self._cache.get("stations", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("stations", []):
            code = str(s.get("stationCode",""))
            data = await self._post(f"{self.BASE}/getKpiInfo",
                                    json_={"stationCodes": code,
                                           "kpiCodes": "inverter_power,radiation_intensity"})
            if data and data.get("success"):
                items = data.get("data", [])
                kpi   = items[0].get("dataItemMap", {}) if items else {}
                out[code] = {"power_w": _f(kpi.get("inverter_power"), 1000)}
        return out


# ═══════════════════════════════════════════════════════════════════
# GoodWe SEMS
# ═══════════════════════════════════════════════════════════════════
@register_provider("goodwe")
class GoodWeProvider(CloudEMSProvider):
    PROVIDER_ID  = "goodwe"
    DISPLAY_NAME = "GoodWe SEMS"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://www.semsportal.com/api"

    UPDATE_HINTS = {
        "ha_repo": "https://github.com/yarafie/goodwe",
        "pypi":    "https://pypi.org/project/goodwe/",
        "note":    "Reverse-engineered. Controleer ha_repo bij updates.",
    }

    async def async_setup(self) -> bool:
        self._init_store("goodwe")
        resp = await self._post(
            "https://www.semsportal.com/api/v2/Common/CrossLogin",
            json_={"account": self._credentials.get("username",""),
                   "pwd": self._credentials.get("password",""), "is_local": False})
        if not (resp and resp.get("code") == 0):
            self._last_error = "GoodWe login mislukt"
            return False
        d = resp.get("data", {})
        self._uid  = d.get("uid","")
        self._tok  = d.get("token","")
        self._ts   = d.get("timestamp","")
        stations = await self._post(
            f"{self.BASE}/v2/PowerStation/GetPowerStationByUser",
            json_={}, headers=self._gh())
        self._cache["stations"] = (stations or {}).get("data",{}).get("list",[]) if stations else []
        self._api_ok = True
        return True

    def _gh(self) -> dict:
        import json as _json
        return {"token": _json.dumps({"uid": self._uid, "timestamp": self._ts,
                                      "token": self._tok, "client": "web", "version": ""})}

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, s.get("id",""),
                     s.get("stationname","GoodWe"), {})
                for s in self._cache.get("stations", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("stations", []):
            sid  = s.get("id","")
            data = await self._post(
                f"{self.BASE}/v2/PowerStation/GetMonitorDetailByPowerstationId",
                json_={"powerStationId": sid}, headers=self._gh())
            if data and data.get("code") == 0:
                inv = (data.get("data",{}).get("inverter") or [{}])[0]
                d   = inv.get("d", {})
                out[sid] = {"power_w": _f(d.get("pac")),
                            "battery_soc": _f(d.get("soc")),
                            "temperature_c": _f(d.get("tempperature"), 0.1)}
        return out


# ═══════════════════════════════════════════════════════════════════
# Growatt
# ═══════════════════════════════════════════════════════════════════
@register_provider("growatt")
class GrowattProvider(CloudEMSProvider):
    PROVIDER_ID  = "growatt"
    DISPLAY_NAME = "Growatt Server"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://server.growatt.com"

    UPDATE_HINTS = {
        "ha_repo": "https://github.com/muppet3000/homeassistant-growatt_server_api",
        "pypi":    "https://pypi.org/project/growattServer/",
        "note":    "MD5-hash van wachtwoord. Controleer pypi bij updates.",
    }

    async def async_setup(self) -> bool:
        self._init_store("growatt")
        pw = hashlib.md5(self._credentials.get("password","").encode()).hexdigest()
        resp = await self._post(f"{self.BASE}/login",
                                data={"userName": self._credentials.get("username",""),
                                      "password": pw})
        if not (resp and resp.get("result") == 1):
            self._last_error = "Growatt login mislukt"
            return False
        data = await self._post(f"{self.BASE}/index/getPlantListTitle", data={})
        self._cache["plants"] = data if isinstance(data, list) else []
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(p.get("id","")),
                     p.get("plantName","Growatt"), {})
                for p in self._cache.get("plants", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for p in self._cache.get("plants", []):
            pid  = str(p.get("id",""))
            data = await self._post(f"{self.BASE}/panel/getDevicesByPlantList",
                                    data={"plantId": pid, "currPage": "1"})
            if data and data.get("result") == 1:
                devs = data.get("obj",{}).get("datas",[])
                if devs:
                    out[pid] = {"power_w": _f(devs[0].get("pac")),
                                "energy_today_kwh": _f(devs[0].get("eToday"))}
        return out


# ═══════════════════════════════════════════════════════════════════
# Solis Cloud (Ginlong) — HMAC-MD5 signing
# ═══════════════════════════════════════════════════════════════════
@register_provider("solis")
class SolisProvider(CloudEMSProvider):
    PROVIDER_ID  = "solis"
    DISPLAY_NAME = "Solis Cloud"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://www.soliscloud.com:13333"

    UPDATE_HINTS = {
        "docs":    "https://oss.soliscloud.com/templete/SolisCloud%20Platform%20API%20Document%20V2.0.pdf",
        "ha_repo": "https://github.com/hultenvp/solis-sensor",
        "note":    "HMAC-MD5 content-MD5 signing per request.",
    }

    async def async_setup(self) -> bool:
        self._kid = self._credentials.get("key_id","")
        self._ks  = self._credentials.get("key_secret","")
        if not self._kid:
            self._last_error = "Geen Solis key_id"
            return False
        data = await self._solis_post("/v1/api/userStationList",
                                      {"pageNo": 1, "pageSize": 100})
        if not (data and data.get("code") == "0"):
            self._last_error = "Solis API fout"
            return False
        self._cache["stations"] = data.get("data",{}).get("page",{}).get("records",[])
        self._api_ok = True
        return True

    def _solis_headers(self, body: str, path: str) -> dict:
        import base64
        md5 = base64.b64encode(hashlib.md5(body.encode()).digest()).decode()
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        ct   = "application/json"
        sign = base64.b64encode(
            hmac.new(self._ks.encode(), f"POST\n{md5}\n{ct}\n{date}\n{path}".encode(),
                     hashlib.sha1).digest()
        ).decode()
        return {"Content-MD5": md5, "Content-Type": ct, "Date": date,
                "Authorization": f"API {self._kid}:{sign}"}

    async def _solis_post(self, path: str, body: dict) -> Optional[Any]:
        bs = json.dumps(body)
        return await self._post(f"{self.BASE}{path}", json_=body,
                                headers=self._solis_headers(bs, path))

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(s.get("id","")),
                     s.get("stationName","Solis"), {})
                for s in self._cache.get("stations", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for s in self._cache.get("stations", []):
            sid  = str(s.get("id",""))
            data = await self._solis_post("/v1/api/stationDetail", {"id": sid})
            if data and data.get("code") == "0":
                d = data.get("data", {})
                out[sid] = {"power_w": _f(d.get("pac"), 1000),
                            "battery_soc": _f(d.get("batteryCapacitySoc")),
                            "grid_w": _f(d.get("pGrid"), 1000)}
        return out


# ═══════════════════════════════════════════════════════════════════
# Deye / Sunsynk via SolarmanPV
# ═══════════════════════════════════════════════════════════════════
@register_provider("deye")
@register_provider("sunsynk")
class DeyeSolarmanProvider(CloudEMSProvider, OAuth2Mixin):
    PROVIDER_ID  = "deye"
    DISPLAY_NAME = "Deye / SolarmanPV"
    CATEGORY     = "inverter"
    ICON         = "mdi:solar-power"
    BASE         = "https://api.solarmanpv.com"
    TOKEN_URL    = "https://api.solarmanpv.com/account/v1.0/token"

    UPDATE_HINTS = {
        "docs":    "https://api.solarmanpv.com/",
        "ha_repo": "https://github.com/StephanJoubert/home_assistant_solarman",
        "note":    "Ook voor Afore, Kstar, OMNIK. appId + appSecret vereist.",
    }

    async def async_setup(self) -> bool:
        self._init_store("deye_solarman")
        saved = await self._load()
        self._tokens = saved.get("tokens", {})
        body = {
            "appId": self._credentials.get("app_id",""),
            "appSecret": hashlib.md5(self._credentials.get("app_secret","").encode()).hexdigest(),
            "email": self._credentials.get("username",""),
            "password": hashlib.md5(self._credentials.get("password","").encode()).hexdigest(),
        }
        resp = await self._post(f"{self.BASE}/account/v1.0/token?language=en", json_=body)
        if not (resp and resp.get("access_token")):
            self._last_error = "SolarmanPV login mislukt"
            return False
        self._store_tokens(resp)
        data = await self._post(f"{self.BASE}/station/v1.0/list?language=en",
                                json_={"page": 1, "size": 100},
                                headers=self._auth_header())
        if not (data and data.get("code") == "0"):
            return False
        self._cache["plants"] = data.get("stationList", [])
        self._api_ok = True
        return True

    async def async_get_devices(self) -> List[ProviderDevice]:
        return [_dev(self.PROVIDER_ID, str(p.get("id","")), p.get("name","Deye"), {})
                for p in self._cache.get("plants", [])]

    async def async_poll(self) -> Dict[str, Any]:
        out = {}
        for p in self._cache.get("plants", []):
            pid  = str(p.get("id",""))
            data = await self._post(f"{self.BASE}/station/v1.0/realTime?language=en",
                                    json_={"stationId": pid},
                                    headers=self._auth_header())
            if data and data.get("code") == "0":
                out[pid] = {
                    "power_w":         _f(data.get("generationPower"), 1000),
                    "battery_soc":     _f(data.get("batterySoc")),
                    "grid_w":          _f(data.get("purchasePower"), 1000),
                    "energy_today_kwh":_f(data.get("generationValue")),
                }
        return out
