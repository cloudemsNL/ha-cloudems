# -*- coding: utf-8 -*-
"""
CloudEMS Price Fetcher — v2.1.

Day-ahead + intraday prijzen via:
  1. Bestaande HA-integraties (Tibber, ENTSO-E, Nordpool HA-integratie)
  2. Nord Pool REST API v2 — gratis, geen token, voor NO/DK/SE/FI
  3. ENTSO-E Transparency Platform (day-ahead A44 + intraday A63)
  4. EPEX SPOT publieke API (intraday NL/DE/FR/BE)

Nord Pool landen (NO/DK/SE/FI) gebruiken primair de Nord Pool API.
EPEX landen (NL/BE/DE/FR/AT/CH) gebruiken ENTSO-E + EPEX publiek.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import CONF_EPEX_COUNTRY, DEFAULT_EPEX_COUNTRY, EPEX_AREAS, NORDPOOL_COUNTRIES

_LOGGER = logging.getLogger(__name__)

ENTSOE_BASE          = "https://web-api.tp.entsoe.eu/api"
ENTSOE_TOKEN_ENV     = "ENTSOE_TOKEN"

# ── Nord Pool REST API v2 (geen token, gratis) ────────────────────────────────
# Documentatie: https://data.nordpoolgroup.com/api/v2/
NORDPOOL_API_BASE    = "https://data.nordpoolgroup.com/api/v2"

# Marktzone per land (Nord Pool biedzone codes)
NORDPOOL_AREAS = {
    "NO": "NO1",   # Oslo / Sørøst-Norge (meest representatief)
    "DK": "DK1",   # West-Denemarken (DK1 = Jutland/Funen)
    "SE": "SE3",   # Stockholm / Midden-Zweden
    "FI": "FI",    # Finland (één zone)
}

# EPEX SPOT publieke intraday data (geen token nodig voor NL/DE/FR/BE)
EPEX_INTRADAY_BASE   = "https://api.epexspot.com/api/marketdata/tradingresult"
EPEX_INTRADAY_AREAS  = {
    "NL": "NL",
    "DE": "DE-LU",
    "BE": "BE",
    "FR": "FR",
    "AT": "AT",
}

# ENTSO-E intraday document type
ENTSOE_INTRADAY_TYPE = "A63"   # Intraday Aggregated Net Position
ENTSOE_XBID_TYPE     = "A63"   # Cross-Border Intraday

# Max uren vooruit voor intraday override
INTRADAY_MAX_HOURS   = 6


class EPEXPriceFetcher:
    """Fetches EPEX day-ahead + intraday spot prices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass          = hass
        self.config        = {**entry.data, **entry.options}
        self.prices:       list[dict] = []   # day-ahead, eventueel patched met intraday
        self._da_prices:   list[dict] = []   # ruwe day-ahead
        self._id_prices:   list[dict] = []   # ruwe intraday
        self._country      = self.config.get(CONF_EPEX_COUNTRY, DEFAULT_EPEX_COUNTRY)
        self._last_intraday_fetch: float = 0.0

    async def async_setup(self) -> None:
        source = "Nord Pool" if self._country in NORDPOOL_COUNTRIES else "EPEX/ENTSO-E"
        _LOGGER.info("CloudEMS price fetcher v2.1 — land=%s, bron=%s", self._country, source)

    async def async_fetch_prices(self) -> None:
        """Fetch day-ahead prijzen + intraday. Routeert naar Nord Pool of EPEX op basis van land."""
        import time

        # Stap 1: probeer bestaande HA-integraties (Tibber, ENTSO-E HA, Nordpool HA)
        da = await self._try_existing_ha_prices()

        if not da:
            if self._country in NORDPOOL_COUNTRIES:
                # Nord Pool landen: gebruik Nord Pool REST API (gratis, geen token)
                da = await self._fetch_nordpool_dayahead()
                if not da:
                    # Fallback: ENTSO-E (vereist token maar werkt ook voor Nord Pool zones)
                    da = await self._fetch_entsoe(document_type="A44")
            else:
                # EPEX landen (NL/BE/DE/FR/AT/CH): ENTSO-E
                da = await self._fetch_entsoe(document_type="A44")

        self._da_prices = da

        # Stap 2: intraday (elke 15 minuten vernieuwen)
        if time.time() - self._last_intraday_fetch > 900:
            if self._country in NORDPOOL_COUNTRIES:
                id_prices = await self._fetch_nordpool_intraday()
            else:
                id_prices = await self._fetch_intraday()
            if id_prices:
                self._id_prices = id_prices
                self._last_intraday_fetch = time.time()
                _LOGGER.debug("Intraday: %d slots geladen (%s)", len(id_prices), self._country)

        # Stap 3: merge
        self.prices = self._merge_prices(self._da_prices, self._id_prices)

        if not self.prices:
            _LOGGER.warning("Geen prijzen beschikbaar voor land=%s", self._country)

    # ── Nord Pool REST API v2 ─────────────────────────────────────────────────

    async def _fetch_nordpool_dayahead(self) -> list[dict]:
        """
        Haal day-ahead prijzen op via Nord Pool REST API v2 (gratis, geen token).
        Endpoint: GET /api/v2/marketdata/areas/{area}?currency=EUR&date=YYYY-MM-DD
        Retourneert prijzen in €/MWh per uur voor de opgegeven dag.
        """
        area = NORDPOOL_AREAS.get(self._country)
        if not area:
            return []

        now = datetime.now(timezone.utc)
        prices = []

        # Haal vandaag en morgen op (morgen beschikbaar na ~13:00 CET)
        for delta in (0, 1):
            date = (now + timedelta(days=delta)).strftime("%Y-%m-%d")
            url  = f"{NORDPOOL_API_BASE}/marketdata/areas/{area}"
            params = {"currency": "EUR", "date": date}

            try:
                session = async_get_clientsession(self.hass)
                async with session.get(
                        url, params=params,
                        headers={"Accept": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=12),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            parsed = self._parse_nordpool_v2(data)
                            prices.extend(parsed)
                            _LOGGER.debug(
                                "Nord Pool %s %s: %d uur", area, date, len(parsed)
                            )
                        elif resp.status == 204:
                            pass  # Geen data voor deze dag (morgen nog niet beschikbaar)
                        else:
                            _LOGGER.debug("Nord Pool API HTTP %d voor %s %s", resp.status, area, date)
            except aiohttp.ClientError as err:
                _LOGGER.debug("Nord Pool API fout (%s %s): %s", area, date, err)
            except Exception as err:
                _LOGGER.warning("Nord Pool onverwachte fout: %s", err)

        return sorted(prices, key=lambda x: x["start"])

    async def _fetch_nordpool_intraday(self) -> list[dict]:
        """
        Nord Pool intraday via de HA Nordpool-integratie als die aanwezig is,
        anders de Nord Pool continuous trading API (beperkte data).
        """
        # Eerst proberen via bestaande HA Nordpool-integratie
        for state in self.hass.states.async_all():
            eid = state.entity_id.lower()
            if "nordpool" not in eid:
                continue
            for attr in ("raw_today", "raw_tomorrow", "prices"):
                raw = state.attributes.get(attr)
                if raw and isinstance(raw, list):
                    parsed = self._parse_generic_prices(raw)
                    if parsed:
                        now = datetime.now(timezone.utc)
                        upcoming = [p for p in parsed if (
                            p.get("end") and p["end"] > now
                        )]
                        if upcoming:
                            _LOGGER.debug(
                                "Nord Pool intraday via HA-integratie: %s (%d slots)",
                                state.entity_id, len(upcoming),
                            )
                            return upcoming

        # Geen HA-integratie beschikbaar — geen Nord Pool intraday zonder token
        return []

    def _parse_nordpool_v2(self, data: Any) -> list[dict]:
        """
        Parse Nord Pool REST API v2 JSON respons naar prijs-slots.

        Verwachte structuur:
        {
          "deliveryDateCET": "2026-03-07",
          "version": 1,
          "updatedAt": "...",
          "deliveryAreas": ["NO1"],
          "market": "DayAhead",
          "multiAreaEntries": [
            {
              "deliveryStart": "2026-03-07T00:00:00Z",
              "deliveryEnd":   "2026-03-07T01:00:00Z",
              "entryPerArea":  {"NO1": 45.23}
            }, ...
          ]
        }
        """
        prices = []
        area   = NORDPOOL_AREAS.get(self._country, "")
        try:
            entries = data.get("multiAreaEntries") or data.get("data", {}).get("Rows", [])
            if not entries:
                # Alternatieve structuur (v1 API)
                return self._parse_nordpool_legacy(data)

            for entry in entries:
                start_str = entry.get("deliveryStart") or entry.get("DeliveryStart")
                end_str   = entry.get("deliveryEnd")   or entry.get("DeliveryEnd")
                per_area  = entry.get("entryPerArea")  or entry.get("EntryPerArea") or {}

                price_val = per_area.get(area) or per_area.get(self._country)
                if price_val is None:
                    # Probeer eerste beschikbare waarde
                    if per_area:
                        price_val = next(iter(per_area.values()))

                if start_str is None or price_val is None:
                    continue

                try:
                    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end   = (datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                             if end_str else start + timedelta(hours=1))
                except ValueError:
                    continue

                prices.append({
                    "start":  start,
                    "end":    end,
                    "price":  float(price_val) / 1000.0,  # €/MWh → €/kWh
                    "source": "nordpool",
                })

        except Exception as err:
            _LOGGER.debug("Nord Pool v2 parse fout: %s", err)

        return prices

    def _parse_nordpool_legacy(self, data: Any) -> list[dict]:
        """Fallback parser voor oudere Nord Pool API response structuur."""
        prices = []
        try:
            rows = data.get("data", {}).get("Rows") or data.get("Rows", [])
            date_str = data.get("data", {}).get("DataStartdate") or ""
            if not date_str:
                return []

            base_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            area      = NORDPOOL_AREAS.get(self._country, "")

            for i, row in enumerate(rows[:24]):  # max 24 uren
                cols = row.get("Columns") or []
                for col in cols:
                    if col.get("Name") == area or col.get("Index") == 0:
                        val = col.get("Value", "").replace(",", ".").replace(" ", "")
                        try:
                            price_mwh = float(val)
                            start = base_date + timedelta(hours=i)
                            prices.append({
                                "start":  start,
                                "end":    start + timedelta(hours=1),
                                "price":  price_mwh / 1000.0,
                                "source": "nordpool_legacy",
                            })
                        except ValueError:
                            pass
                        break
        except Exception as err:
            _LOGGER.debug("Nord Pool legacy parse fout: %s", err)
        return prices

    async def _fetch_intraday(self) -> list[dict]:
        """
        Haal intraday EPEX-prijzen op.
        Probeert achtereenvolgens:
          1. ENTSO-E intraday (A63) — vereist token
          2. EPEX SPOT publieke marktdata API — geen token nodig
        """
        prices = await self._fetch_entsoe_intraday()
        if prices:
            return prices
        prices = await self._fetch_epex_public_intraday()
        return prices

    async def _fetch_entsoe_intraday(self) -> list[dict]:
        """ENTSO-E intraday via A63 document type."""
        area  = EPEX_AREAS.get(self._country)
        token = self.hass.data.get("cloudems_entsoe_token")
        if not area or not token:
            return []

        now          = datetime.now(timezone.utc)
        period_start = now.strftime("%Y%m%d%H%M")
        period_end   = (now + timedelta(hours=INTRADAY_MAX_HOURS)).strftime("%Y%m%d%H%M")

        params = {
            "securityToken": token,
            "documentType": ENTSOE_INTRADAY_TYPE,
            "in_Domain":    area,
            "out_Domain":   area,
            "periodStart":  period_start,
            "periodEnd":    period_end,
        }
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                    ENTSOE_BASE, params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        xml = await resp.text()
                        parsed = self._parse_entsoe_xml(xml)
                        if parsed:
                            _LOGGER.debug("ENTSO-E intraday: %d slots", len(parsed))
                        return parsed
        except Exception as err:
            _LOGGER.debug("ENTSO-E intraday mislukt: %s", err)
        return []

    async def _fetch_epex_public_intraday(self) -> list[dict]:
        """
        EPEX SPOT publieke marktdata — last-traded prijs per kwartier/uur.
        Endpoint geeft de meest recente handelsprijs terug voor de komende uren.
        Geen API-sleutel nodig voor NL/DE/FR/BE day-of data.
        """
        epex_area = EPEX_INTRADAY_AREAS.get(self._country)
        if not epex_area:
            return []

        now      = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # EPEX SPOT publieke REST-endpoint (rate-limited maar gratis)
        url = f"{EPEX_INTRADAY_BASE}"
        params = {
            "market_area":  epex_area,
            "auction":      "MRC",
            "trading_date": date_str,
            "delivery_date": date_str,
            "modality":     "Auction",
            "sub_modality": "HourlyAuction",
            "product":      "60",    # 60-minuut producten
            "data_mode":    "table",
        }

        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                    url, params=params,
                    headers={"Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        return self._parse_epex_public(data, now)
                    _LOGGER.debug("EPEX publiek: HTTP %d", resp.status)
        except Exception as err:
            _LOGGER.debug("EPEX publiek intraday mislukt: %s", err)

        # Fallback: Entsoe-E publiek endpunt zonder token (beperkte data)
        return await self._fetch_entsoe_public_fallback()

    async def _fetch_entsoe_public_fallback(self) -> list[dict]:
        """
        Publieke ENTSO-E data zonder token via entsoe-py compatible endpoint.
        Geeft beperkte intraday data maar werkt zonder registratie.
        """
        area = EPEX_AREAS.get(self._country)
        if not area:
            return []

        now   = datetime.now(timezone.utc)
        start = now.strftime("%Y%m%d%H00")
        end   = (now + timedelta(hours=INTRADAY_MAX_HOURS)).strftime("%Y%m%d%H00")

        url = (
            f"https://transparency.entsoe.eu/api"
            f"?documentType=A44&in_Domain={area}&out_Domain={area}"
            f"&periodStart={start}&periodEnd={end}"
        )
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        xml = await resp.text()
                        return self._parse_entsoe_xml(xml)
        except Exception:
            pass
        return []

    def _parse_epex_public(self, data: Any, now: datetime) -> list[dict]:
        """Parse EPEX SPOT publieke API JSON respons."""
        prices = []
        try:
            rows = data.get("data", {}).get("rows", [])
            for row in rows:
                hour     = row.get("hour")
                price    = row.get("price") or row.get("last") or row.get("close")
                if hour is None or price is None:
                    continue
                # hour is "08:00 - 09:00" of integer
                if isinstance(hour, str) and " - " in hour:
                    h = int(hour.split(":")[0])
                elif isinstance(hour, (int, float)):
                    h = int(hour)
                else:
                    continue
                slot_start = now.replace(hour=h, minute=0, second=0, microsecond=0)
                if slot_start < now - timedelta(hours=1):
                    slot_start += timedelta(days=1)
                prices.append({
                    "start":    slot_start,
                    "end":      slot_start + timedelta(hours=1),
                    "price":    float(price) / 1000.0,  # €/MWh → €/kWh
                    "intraday": True,
                })
        except Exception as err:
            _LOGGER.debug("EPEX public parse error: %s", err)
        return sorted(prices, key=lambda x: x["start"])

    def _merge_prices(self, da: list[dict], intraday: list[dict]) -> list[dict]:
        """
        Combineer day-ahead en intraday prijzen.
        Voor uren waarvoor een intraday-prijs beschikbaar is en die
        binnen INTRADAY_MAX_HOURS liggen, vervangt de intraday-prijs
        de day-ahead prijs. Dit geeft accuratere beslissingen voor de
        eerstvolgende uren.
        """
        if not intraday:
            return da

        now      = datetime.now(timezone.utc)
        horizon  = now + timedelta(hours=INTRADAY_MAX_HOURS)

        # Index intraday op uurstart
        id_index: dict[datetime, float] = {}
        for slot in intraday:
            start = slot["start"]
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except ValueError:
                    continue
            # Normaliseer naar UTC
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            id_index[start.replace(minute=0, second=0, microsecond=0)] = slot["price"]

        merged = []
        overridden = 0
        for slot in da:
            start = slot["start"]
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except ValueError:
                    merged.append(slot)
                    continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)

            key = start.replace(minute=0, second=0, microsecond=0)
            if key in id_index and start <= horizon:
                da_price = slot["price"]
                id_price = id_index[key]
                merged.append({**slot, "price": id_price,
                               "price_da": da_price, "intraday": True})
                overridden += 1
            else:
                merged.append(slot)

        if overridden:
            _LOGGER.info(
                "EPEX intraday: %d van de %d uren overschreven (max %dh vooruit)",
                overridden, len(da), INTRADAY_MAX_HOURS,
            )

        # Voeg intraday-only slots toe (uren zonder day-ahead dekking)
        existing_starts = {
            (s["start"].replace(minute=0, second=0, microsecond=0)
             if not isinstance(s["start"], str) else s["start"])
            for s in merged
        }
        for slot in intraday:
            start = slot["start"]
            if isinstance(start, str):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            key = start.replace(minute=0, second=0, microsecond=0)
            if key not in existing_starts:
                merged.append(slot)

        return sorted(merged, key=lambda x: (
            x["start"] if not isinstance(x["start"], str) else datetime.fromisoformat(x["start"])
        ))

    # ── Bestaande methodes (ongewijzigd + uitgebreid) ─────────────────────────

    async def _try_existing_ha_prices(self) -> list[dict]:
        """Lees prijzen uit bestaande HA-energie-integraties."""
        for s in self.hass.states.async_all():
            eid = s.entity_id.lower()
            if any(kw in eid for kw in ("tibber", "entsoe", "nordpool", "epex", "energyzero")):
                for attr in ("prices", "raw_today", "raw_tomorrow", "data"):
                    raw = s.attributes.get(attr)
                    if raw and isinstance(raw, list):
                        parsed = self._parse_generic_prices(raw)
                        if parsed:
                            _LOGGER.debug("Prijzen uit HA-integratie: %s (%d slots)",
                                          s.entity_id, len(parsed))
                            return parsed
        return []

    def _parse_generic_prices(self, raw: list) -> list[dict]:
        parsed = []
        for item in raw:
            if isinstance(item, dict):
                parsed.append({
                    "start": item.get("start") or item.get("time"),
                    "end":   item.get("end"),
                    "price": float(item.get("price") or item.get("value") or 0),
                })
        return [p for p in parsed if p["start"] and p["price"] is not None]

    async def _fetch_entsoe(self, document_type: str = "A44") -> list[dict]:
        """Fetch van ENTSO-E transparency platform."""
        area  = EPEX_AREAS.get(self._country)
        token = self.hass.data.get("cloudems_entsoe_token")
        if not area or not token:
            return []

        now          = datetime.now(timezone.utc)
        period_start = now.strftime("%Y%m%d0000")
        period_end   = (now + timedelta(days=1)).strftime("%Y%m%d2300")

        params = {
            "securityToken": token,
            "documentType":  document_type,
            "in_Domain":     area,
            "out_Domain":    area,
            "periodStart":   period_start,
            "periodEnd":     period_end,
        }
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                    ENTSOE_BASE, params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return self._parse_entsoe_xml(await resp.text())
        except Exception as err:
            _LOGGER.debug("ENTSO-E fetch mislukt: %s", err)
        return []

    def _parse_entsoe_xml(self, xml: str) -> list[dict]:
        import xml.etree.ElementTree as ET
        prices = []
        try:
            root = ET.fromstring(xml)
            ns = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0"}
            for ts in root.findall(".//ns:TimeSeries", ns):
                period = ts.find(".//ns:Period", ns)
                if period is None:
                    continue
                start_el = period.find("ns:timeInterval/ns:start", ns)
                if start_el is None:
                    continue
                start = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
                for point in period.findall("ns:Point", ns):
                    pos       = int(point.find("ns:position", ns).text)
                    price_mwh = float(point.find("ns:price.amount", ns).text)
                    slot_start = start + timedelta(hours=pos - 1)
                    prices.append({
                        "start": slot_start,
                        "end":   slot_start + timedelta(hours=1),
                        "price": price_mwh / 1000.0,
                    })
        except Exception as err:
            _LOGGER.warning("ENTSO-E XML parse fout: %s", err)
        return sorted(prices, key=lambda x: x["start"])

    # ── Query methodes ────────────────────────────────────────────────────────

    def get_current_price(self) -> float | None:
        now = datetime.now(timezone.utc)
        for slot in self.prices:
            start = slot["start"]
            end   = slot["end"]
            if isinstance(start, str):
                try: start = datetime.fromisoformat(start)
                except ValueError: continue
            if isinstance(end, str):
                try: end = datetime.fromisoformat(end)
                except ValueError: continue
            if start.tzinfo is None: start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:   end   = end.replace(tzinfo=timezone.utc)
            if start <= now < end:
                return slot["price"]
        return None

    def get_current_slot(self) -> dict | None:
        """Geeft het volledige huidige prijsslot inclusief intraday-flag."""
        now = datetime.now(timezone.utc)
        for slot in self.prices:
            start, end = slot["start"], slot["end"]
            if isinstance(start, str):
                try: start = datetime.fromisoformat(start)
                except ValueError: continue
            if isinstance(end, str):
                try: end = datetime.fromisoformat(end)
                except ValueError: continue
            if start.tzinfo is None: start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:   end   = end.replace(tzinfo=timezone.utc)
            if start <= now < end:
                return {**slot, "start": start, "end": end}
        return None

    def get_cheapest_slots(self, count: int = 3) -> list[dict]:
        now = datetime.now(timezone.utc)
        upcoming = [s for s in self.prices if (
            (s["end"] if not isinstance(s["end"], str) else
             datetime.fromisoformat(s["end"])) > now
        )]
        return sorted(upcoming, key=lambda x: x["price"])[:count]

    def get_most_expensive_slots(self, count: int = 3) -> list[dict]:
        now = datetime.now(timezone.utc)
        upcoming = [s for s in self.prices if (
            (s["end"] if not isinstance(s["end"], str) else
             datetime.fromisoformat(s["end"])) > now
        )]
        return sorted(upcoming, key=lambda x: x["price"], reverse=True)[:count]

    def get_intraday_count(self) -> int:
        """Aantal uren momenteel met intraday-prijs."""
        return sum(1 for s in self.prices if s.get("intraday"))

    def get_price_summary(self) -> dict:
        """Samenvattende statistieken voor dashboard/sensor."""
        now    = datetime.now(timezone.utc)
        future = [s for s in self.prices if not isinstance(s["end"], str) and s["end"] > now]
        if not future:
            return {}
        prices = [s["price"] for s in future]
        return {
            "current":        self.get_current_price(),
            "min_today":      min(prices),
            "max_today":      max(prices),
            "avg_today":      round(sum(prices) / len(prices), 4),
            "intraday_slots": self.get_intraday_count(),
            "total_slots":    len(future),
            "has_intraday":   self.get_intraday_count() > 0,
        }


    async def async_fetch_prices(self) -> None:
        """Fetch prices and populate self.prices list."""
        # Try existing energy integrations first (Tibber, ENTSO-E, Nordpool)
        prices = await self._try_existing_ha_prices()
        if prices:
            self.prices = prices
            _LOGGER.debug("EPEX prices from HA integration: %d slots", len(prices))
            return

        # Direct ENTSO-E fetch
        prices = await self._fetch_entsoe()
        if prices:
            self.prices = prices
            return

        _LOGGER.warning("No EPEX price source available — solar dimmer uses no prices")

    async def _try_existing_ha_prices(self) -> list[dict]:
        """Try to read prices from existing HA energy price integrations."""
        # Check for Tibber integration
        tibber_states = [
            s for s in self.hass.states.async_all()
            if "tibber" in s.entity_id.lower() and "price" in s.entity_id.lower()
        ]
        if tibber_states:
            _LOGGER.debug("Found Tibber price entity: %s", tibber_states[0].entity_id)

        # Check for ENTSO-E integration (sensor with prices attribute)
        entsoe_states = [
            s for s in self.hass.states.async_all()
            if "entsoe" in s.entity_id.lower() or "nordpool" in s.entity_id.lower()
        ]
        for state in entsoe_states:
            raw_prices = state.attributes.get("prices") or state.attributes.get("raw_today")
            if raw_prices:
                return self._parse_generic_prices(raw_prices)

        return []

    def _parse_generic_prices(self, raw: list) -> list[dict]:
        """Parse various price formats from HA integrations."""
        parsed = []
        for item in raw:
            if isinstance(item, dict):
                parsed.append({
                    "start": item.get("start") or item.get("time"),
                    "end": item.get("end"),
                    "price": float(item.get("price") or item.get("value") or 0),
                })
        return [p for p in parsed if p["start"] and p["price"] is not None]

    async def _fetch_entsoe(self) -> list[dict]:
        """Fetch directly from ENTSO-E transparency platform."""
        area = EPEX_AREAS.get(self._country)
        if not area:
            return []

        token = self.hass.data.get("cloudems_entsoe_token")
        if not token:
            return []

        now = datetime.now(timezone.utc)
        period_start = now.strftime("%Y%m%d0000")
        period_end = (now + timedelta(days=1)).strftime("%Y%m%d2300")

        params = {
            "securityToken": token,
            "documentType": "A44",
            "in_Domain": area,
            "out_Domain": area,
            "periodStart": period_start,
            "periodEnd": period_end,
        }

        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                    ENTSOE_BASE,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        xml = await resp.text()
                        return self._parse_entsoe_xml(xml)
        except Exception as err:
            _LOGGER.debug("ENTSO-E fetch failed: %s", err)

        return []

    def _parse_entsoe_xml(self, xml: str) -> list[dict]:
        """Parse ENTSO-E XML response into price slots."""
        import xml.etree.ElementTree as ET

        prices = []
        try:
            root = ET.fromstring(xml)
            ns = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0"}

            for ts in root.findall(".//ns:TimeSeries", ns):
                period = ts.find(".//ns:Period", ns)
                if period is None:
                    continue

                start_str = period.find("ns:timeInterval/ns:start", ns)
                if start_str is None:
                    continue
                start = datetime.fromisoformat(start_str.text.replace("Z", "+00:00"))

                for point in period.findall("ns:Point", ns):
                    pos = int(point.find("ns:position", ns).text)
                    price_mwh = float(point.find("ns:price.amount", ns).text)
                    price_kwh = price_mwh / 1000.0  # Convert MWh → kWh

                    slot_start = start + timedelta(hours=pos - 1)
                    slot_end = slot_start + timedelta(hours=1)

                    prices.append({
                        "start": slot_start,
                        "end": slot_end,
                        "price": price_kwh,
                    })
        except Exception as err:
            _LOGGER.warning("ENTSO-E XML parse error: %s", err)

        return sorted(prices, key=lambda x: x["start"])

    def get_current_price(self) -> float | None:
        now = datetime.now(timezone.utc)
        for slot in self.prices:
            if slot["start"] <= now < slot["end"]:
                return slot["price"]
        return None

    def get_cheapest_slots(self, count: int = 3) -> list[dict]:
        """Return the cheapest n upcoming price slots."""
        now = datetime.now(timezone.utc)
        upcoming = [s for s in self.prices if s["end"] > now]
        return sorted(upcoming, key=lambda x: x["price"])[:count]

    def get_most_expensive_slots(self, count: int = 3) -> list[dict]:
        now = datetime.now(timezone.utc)
        upcoming = [s for s in self.prices if s["end"] > now]
        return sorted(upcoming, key=lambda x: x["price"], reverse=True)[:count]
