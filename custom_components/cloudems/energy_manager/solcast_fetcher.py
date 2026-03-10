# -*- coding: utf-8 -*-
"""
CloudEMS Solcast Fetcher — v1.0.0

Native Solcast Hobby API client. Geen afhankelijkheid van BJReplay/ha-solcast-solar.
Werkt als optionele Tier-3 laag bovenop het eigen statistische model in pv_forecast.py.

API limieten Hobby account:
  - 10 calls/dag
  - 2 rooftop sites max
  - Forecast: 7 dagen vooruit, 30 min resolutie → geaggregeerd naar uur

Integratie met pv_forecast.py:
  - PVForecast.set_solcast_fetcher(fetcher) → activeer Tier 3
  - PVForecast._build_forecast() → blend solcast_w met statistisch model
  - Coordinator roept async_refresh() aan: max 2x/dag (06:00 + 13:00 lokale tijd)

Sensor output (sensor.cloudems_pv_forecast_today attributes):
    hourly: [
      {hour: 6, forecast_w: 850, low_w: 600, high_w: 1100, confidence: 0.85, solcast_w: 920},
      ...
    ]
    source: "solcast+statistical"
    solcast_last_update: "2026-03-10T13:00:00+01:00"
    solcast_calls_today: 2
    solcast_api_ok: true

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_solcast_cache_v1"
STORAGE_VERSION = 1

SOLCAST_API_BASE = "https://api.solcast.com.au"
MAX_CALLS_PER_DAY = 10
PREFERRED_REFRESH_HOURS = (6, 13)   # lokale tijd — 2 calls/dag = ruim binnen limiet
MIN_REFRESH_INTERVAL_S  = 3 * 3600  # minimaal 3 uur tussen calls


@dataclass
class SolcastHourly:
    """Eén uur PV-voorspelling van Solcast."""
    dt_utc:     datetime
    hour_local: int          # 0–23 lokale tijd
    p50_w:      float        # mediaan (pv_estimate)
    p10_w:      float        # pessimistisch (pv_estimate10)
    p90_w:      float        # optimistisch (pv_estimate90)

    def to_dict(self) -> dict:
        return {
            "dt_utc":     self.dt_utc.isoformat(),
            "hour_local": self.hour_local,
            "p50_w":      round(self.p50_w, 1),
            "p10_w":      round(self.p10_w, 1),
            "p90_w":      round(self.p90_w, 1),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SolcastHourly":
        return cls(
            dt_utc     = datetime.fromisoformat(d["dt_utc"]),
            hour_local = d["hour_local"],
            p50_w      = d["p50_w"],
            p10_w      = d["p10_w"],
            p90_w      = d["p90_w"],
        )


@dataclass
class SolcastSiteCache:
    """Cache voor één Solcast rooftop site."""
    site_id:      str
    today:        List[SolcastHourly]   = field(default_factory=list)
    tomorrow:     List[SolcastHourly]   = field(default_factory=list)
    last_fetch_ts: float                = 0.0
    calls_today:  int                   = 0
    last_call_date: str                 = ""   # "2026-03-10"
    api_ok:       bool                  = True
    last_error:   str                   = ""

    def to_dict(self) -> dict:
        return {
            "site_id":       self.site_id,
            "today":         [h.to_dict() for h in self.today],
            "tomorrow":      [h.to_dict() for h in self.tomorrow],
            "last_fetch_ts": self.last_fetch_ts,
            "calls_today":   self.calls_today,
            "last_call_date":self.last_call_date,
            "api_ok":        self.api_ok,
            "last_error":    self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SolcastSiteCache":
        obj = cls(site_id=d.get("site_id", ""))
        obj.today          = [SolcastHourly.from_dict(h) for h in d.get("today", [])]
        obj.tomorrow       = [SolcastHourly.from_dict(h) for h in d.get("tomorrow", [])]
        obj.last_fetch_ts  = d.get("last_fetch_ts", 0.0)
        obj.calls_today    = d.get("calls_today", 0)
        obj.last_call_date = d.get("last_call_date", "")
        obj.api_ok         = d.get("api_ok", True)
        obj.last_error     = d.get("last_error", "")
        return obj


class SolcastFetcher:
    """
    Native Solcast Hobby API client voor CloudEMS.

    Gebruik vanuit pv_forecast.py:
        fetcher = SolcastFetcher(hass, api_key="abc123", site_ids=["rooftop-id"])
        await fetcher.async_setup()
        pv_forecast.set_solcast_fetcher(fetcher)

    Daarna roept coordinator periodiek aan:
        await fetcher.async_refresh_if_needed()

    Data ophalen:
        hourly_today    = fetcher.get_hourly_today(site_id)
        hourly_tomorrow = fetcher.get_hourly_tomorrow(site_id)
        merged_today    = fetcher.get_merged_today()   # alle sites opgeteld
    """

    def __init__(
        self,
        hass,
        api_key: str,
        site_ids: Optional[List[str]] = None,  # None = auto-discover
        dampening: float = 1.0,                # correctiefactor 0.5–1.5
    ) -> None:
        self._hass      = hass
        self._api_key   = api_key
        self._site_ids  = site_ids or []
        self._dampening = max(0.1, min(2.0, dampening))
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._cache:    Dict[str, SolcastSiteCache] = {}
        self._lock      = asyncio.Lock()
        self._session:  Optional[aiohttp.ClientSession] = None

    # ── Setup & teardown ──────────────────────────────────────────────────────

    async def async_setup(self) -> bool:
        """Laad cache uit storage, discover sites als nodig."""
        try:
            data = await self._store.async_load() or {}
            for site_id, site_data in data.get("sites", {}).items():
                self._cache[site_id] = SolcastSiteCache.from_dict(site_data)
            _LOGGER.info("CloudEMS Solcast: cache geladen (%d sites)", len(self._cache))
        except Exception as exc:
            _LOGGER.warning("CloudEMS Solcast: cache laden mislukt: %s", exc)

        if not self._api_key:
            _LOGGER.warning("CloudEMS Solcast: geen API key — schakel uit")
            return False

        # Auto-discover sites als niet geconfigureerd
        if not self._site_ids:
            sites = await self._discover_sites()
            self._site_ids = [s["resource_id"] for s in sites]
            _LOGGER.info("CloudEMS Solcast: %d sites gevonden: %s", len(self._site_ids), self._site_ids)

        # Initialiseer cache entries
        for site_id in self._site_ids:
            if site_id not in self._cache:
                self._cache[site_id] = SolcastSiteCache(site_id=site_id)

        return bool(self._site_ids)

    async def async_shutdown(self) -> None:
        await self._save()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Publieke interface ────────────────────────────────────────────────────

    async def async_refresh_if_needed(self) -> bool:
        """
        Ververs forecast als het tijd is.
        Roep aan vanuit coordinator update loop.
        Respecteert daglimieten en refresh-uren.
        Returns True als data ververst is.
        """
        now_local = dt_util.now()
        today_str = now_local.date().isoformat()
        hour_now  = now_local.hour

        refreshed = False
        for site_id in self._site_ids:
            cache = self._cache.get(site_id)
            if cache is None:
                continue

            # Reset dagtelller
            if cache.last_call_date != today_str:
                cache.calls_today   = 0
                cache.last_call_date = today_str

            # Limiet check
            if cache.calls_today >= MAX_CALLS_PER_DAY:
                continue

            # Minimale interval
            if time.time() - cache.last_fetch_ts < MIN_REFRESH_INTERVAL_S:
                continue

            # Alleen op de gewenste uren verversen
            should_refresh = any(
                abs(hour_now - preferred) <= 1
                for preferred in PREFERRED_REFRESH_HOURS
            )
            if not should_refresh:
                continue

            ok = await self._fetch_site(site_id)
            if ok:
                refreshed = True

        if refreshed:
            await self._save()

        return refreshed

    def get_hourly_today(self, site_id: Optional[str] = None) -> List[SolcastHourly]:
        """Uurlijkse forecast vandaag voor één of alle sites opgeteld."""
        return self._get_hourly("today", site_id)

    def get_hourly_tomorrow(self, site_id: Optional[str] = None) -> List[SolcastHourly]:
        """Uurlijkse forecast morgen voor één of alle sites opgeteld."""
        return self._get_hourly("tomorrow", site_id)

    def get_merged_today(self) -> List[dict]:
        """
        Alle sites opgeteld → geeft [{hour, p50_w, p10_w, p90_w}] terug
        met dampening toegepast.
        """
        return self._merge_hourly("today")

    def get_merged_tomorrow(self) -> List[dict]:
        """Alle sites opgeteld voor morgen."""
        return self._merge_hourly("tomorrow")

    def get_status(self) -> dict:
        """Status voor sensor attributen."""
        total_calls = sum(c.calls_today for c in self._cache.values())
        last_update = max(
            (c.last_fetch_ts for c in self._cache.values() if c.last_fetch_ts > 0),
            default=0.0
        )
        all_ok = all(c.api_ok for c in self._cache.values())
        errors = [c.last_error for c in self._cache.values() if c.last_error]
        return {
            "solcast_api_ok":       all_ok,
            "solcast_calls_today":  total_calls,
            "solcast_calls_max":    MAX_CALLS_PER_DAY,
            "solcast_last_update":  datetime.fromtimestamp(last_update, tz=timezone.utc).isoformat() if last_update else None,
            "solcast_sites":        len(self._site_ids),
            "solcast_last_error":   errors[0] if errors else None,
            "solcast_dampening":    self._dampening,
        }

    # ── API calls ─────────────────────────────────────────────────────────────

    async def _discover_sites(self) -> List[dict]:
        """Haal alle rooftop sites op via GET /rooftop_sites."""
        try:
            async with self._get_session() as session:
                url = f"{SOLCAST_API_BASE}/rooftop_sites"
                async with session.get(url, params={"api_key": self._api_key}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("rooftop_sites", [])
                    elif resp.status == 401:
                        _LOGGER.error("CloudEMS Solcast: ongeldige API key (401)")
                    elif resp.status == 429:
                        _LOGGER.warning("CloudEMS Solcast: rate limit bereikt (429)")
                    else:
                        _LOGGER.warning("CloudEMS Solcast: sites discovery mislukt: %d", resp.status)
        except Exception as exc:
            _LOGGER.warning("CloudEMS Solcast: discovery fout: %s", exc)
        return []

    async def _fetch_site(self, site_id: str) -> bool:
        """
        Haal forecasts op voor één site.
        Gebruikt één API call voor beide dagen (estimated_actuals + forecasts).
        """
        async with self._lock:
            cache = self._cache[site_id]
            try:
                data = await self._api_get_forecast(site_id)
                if data is None:
                    cache.api_ok     = False
                    cache.last_error = "API call mislukt"
                    return False

                now_local    = dt_util.now()
                today_date   = now_local.date()
                tomorrow_date= today_date + timedelta(days=1)

                today_hourly    = self._aggregate_to_hours(data, today_date)
                tomorrow_hourly = self._aggregate_to_hours(data, tomorrow_date)

                cache.today        = today_hourly
                cache.tomorrow     = tomorrow_hourly
                cache.last_fetch_ts= time.time()
                cache.calls_today += 1
                cache.last_call_date = today_date.isoformat()
                cache.api_ok       = True
                cache.last_error   = ""

                _LOGGER.info(
                    "CloudEMS Solcast: site %s ververst — vandaag %.1f kWh, morgen %.1f kWh (call %d/%d)",
                    site_id,
                    sum(h.p50_w for h in today_hourly) / 1000,
                    sum(h.p50_w for h in tomorrow_hourly) / 1000,
                    cache.calls_today, MAX_CALLS_PER_DAY,
                )
                return True

            except Exception as exc:
                cache.api_ok     = False
                cache.last_error = str(exc)
                _LOGGER.error("CloudEMS Solcast: fetch %s mislukt: %s", site_id, exc)
                return False

    async def _api_get_forecast(self, site_id: str) -> Optional[List[dict]]:
        """
        GET /rooftop_sites/{site_id}/forecasts
        Geeft lijst van 30-minuut periodes terug.
        """
        url = f"{SOLCAST_API_BASE}/rooftop_sites/{site_id}/forecasts"
        params = {
            "api_key": self._api_key,
            "hours":   48,
            "format":  "json",
        }
        try:
            async with self._get_session() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("forecasts", [])
                    elif resp.status == 401:
                        _LOGGER.error("CloudEMS Solcast: API key ongeldig (401) — schakel Solcast uit")
                        return None
                    elif resp.status == 429:
                        _LOGGER.warning("CloudEMS Solcast: dagelijks limiet bereikt (429)")
                        return None
                    elif resp.status == 404:
                        _LOGGER.warning("CloudEMS Solcast: site %s niet gevonden (404)", site_id)
                        return None
                    else:
                        body = await resp.text()
                        _LOGGER.warning("CloudEMS Solcast: onverwachte respons %d: %s", resp.status, body[:200])
                        return None
        except asyncio.TimeoutError:
            _LOGGER.warning("CloudEMS Solcast: API timeout voor site %s", site_id)
            return None
        except aiohttp.ClientError as exc:
            _LOGGER.warning("CloudEMS Solcast: verbindingsfout: %s", exc)
            return None

    def _aggregate_to_hours(self, forecasts: List[dict], target_date: date) -> List[SolcastHourly]:
        """
        Aggregeer 30-minuut Solcast data naar volledige uren.
        Solcast geeft periodes: period_end + pv_estimate (W gemiddeld over periode).
        → Uurwaarde = gemiddelde van de twee 30-minuut periodes van dat uur.
        """
        # Groepeer per uur (lokale tijd)
        hour_buckets: Dict[int, List[dict]] = {}
        local_tz = dt_util.now().tzinfo

        for entry in forecasts:
            try:
                # Solcast period_end is in UTC, formaat: "2026-03-10T07:30:00.0000000Z"
                period_end_str = entry.get("period_end", "")
                if not period_end_str:
                    continue
                # Normaliseer: verwijder sub-seconde precisie
                period_end_str = period_end_str.split(".")[0].rstrip("Z") + "+00:00"
                dt_utc = datetime.fromisoformat(period_end_str)
                # Omrekenen naar lokale tijd
                dt_local = dt_utc.astimezone(local_tz)

                if dt_local.date() != target_date:
                    continue

                # 30-min bucket hoort bij het uur van period_end - 30min
                effective_dt  = dt_local - timedelta(minutes=30)
                hour_local    = effective_dt.hour

                if hour_local not in hour_buckets:
                    hour_buckets[hour_local] = []
                hour_buckets[hour_local].append(entry)

            except (ValueError, KeyError):
                continue

        # Aggregeer per uur
        result: List[SolcastHourly] = []
        for hour_local, entries in sorted(hour_buckets.items()):
            p50_vals = [float(e.get("pv_estimate",   0)) * 1000 for e in entries]  # kW→W
            p10_vals = [float(e.get("pv_estimate10", 0)) * 1000 for e in entries]
            p90_vals = [float(e.get("pv_estimate90", 0)) * 1000 for e in entries]

            # Som (Wh/periode × 2 periodes ≈ uurwaarde in Wh, maar we willen W gemiddeld)
            n = len(entries)
            p50_w = sum(p50_vals) / n if n else 0.0
            p10_w = sum(p10_vals) / n if n else 0.0
            p90_w = sum(p90_vals) / n if n else 0.0

            # Pas dampening toe
            p50_w *= self._dampening
            p10_w *= self._dampening
            p90_w *= self._dampening

            # Reconstructie van de UTC datetime voor dit uur
            dt_utc_hour = datetime(
                target_date.year, target_date.month, target_date.day,
                hour_local, 0, 0, tzinfo=local_tz
            ).astimezone(timezone.utc)

            result.append(SolcastHourly(
                dt_utc     = dt_utc_hour,
                hour_local = hour_local,
                p50_w      = round(max(0.0, p50_w), 1),
                p10_w      = round(max(0.0, p10_w), 1),
                p90_w      = round(max(0.0, p90_w), 1),
            ))

        return result

    def _get_hourly(self, day: str, site_id: Optional[str]) -> List[SolcastHourly]:
        if site_id:
            cache = self._cache.get(site_id)
            return getattr(cache, day, []) if cache else []
        # Alle sites optellen
        merged: Dict[int, SolcastHourly] = {}
        for cache in self._cache.values():
            for h in getattr(cache, day, []):
                if h.hour_local in merged:
                    existing = merged[h.hour_local]
                    merged[h.hour_local] = SolcastHourly(
                        dt_utc     = existing.dt_utc,
                        hour_local = existing.hour_local,
                        p50_w      = existing.p50_w + h.p50_w,
                        p10_w      = existing.p10_w + h.p10_w,
                        p90_w      = existing.p90_w + h.p90_w,
                    )
                else:
                    merged[h.hour_local] = SolcastHourly(
                        dt_utc=h.dt_utc, hour_local=h.hour_local,
                        p50_w=h.p50_w, p10_w=h.p10_w, p90_w=h.p90_w
                    )
        return [merged[h] for h in sorted(merged.keys())]

    def _merge_hourly(self, day: str) -> List[dict]:
        hourly = self._get_hourly(day, None)
        return [
            {
                "hour":      h.hour_local,
                "solcast_w": h.p50_w,
                "solcast_low_w":  h.p10_w,
                "solcast_high_w": h.p90_w,
            }
            for h in hourly
        ]

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )
        return self._session

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "sites": {sid: cache.to_dict() for sid, cache in self._cache.items()}
            })
        except Exception as exc:
            _LOGGER.debug("CloudEMS Solcast: cache opslaan mislukt: %s", exc)


# ── Integratie-hook voor pv_forecast.py ──────────────────────────────────────

def blend_solcast_with_statistical(
    statistical_hourly: List[dict],
    solcast_merged:     List[dict],
    solcast_weight:     float = 0.6,
) -> List[dict]:
    """
    Blend Solcast forecast met statistisch model.

    Args:
        statistical_hourly: [{hour, forecast_w, low_w, high_w, confidence}]
        solcast_merged:     [{hour, solcast_w, solcast_low_w, solcast_high_w}]
        solcast_weight:     gewicht Solcast (0.0–1.0), default 0.6

    Returns:
        Gemengde lijst, zelfde formaat als statistical_hourly + solcast_w veld.
    """
    solcast_by_hour = {s["hour"]: s for s in solcast_merged}
    stat_weight     = 1.0 - solcast_weight
    result          = []

    for stat in statistical_hourly:
        h   = stat["hour"]
        sc  = solcast_by_hour.get(h)
        if sc and sc["solcast_w"] > 0:
            blended_w   = stat["forecast_w"] * stat_weight + sc["solcast_w"] * solcast_weight
            blended_low = stat["low_w"]      * stat_weight + sc["solcast_low_w"]  * solcast_weight
            blended_high= stat["high_w"]     * stat_weight + sc["solcast_high_w"] * solcast_weight
            result.append({
                **stat,
                "forecast_w": round(blended_w, 1),
                "low_w":      round(blended_low, 1),
                "high_w":     round(blended_high, 1),
                "solcast_w":  sc["solcast_w"],
                "solcast_low_w":  sc["solcast_low_w"],
                "solcast_high_w": sc["solcast_high_w"],
                "confidence": min(1.0, stat["confidence"] * 1.1),  # solcast boost
            })
        else:
            result.append({**stat, "solcast_w": None})

    return result
