"""
CloudEMS EPEX Spot Price Fetcher — v1.6.0

Changelog vs v1.5.0:
  - Free price sources added (no API key needed):
      NL -> EnergyZero public API  (api.energyzero.nl)
      DE -> Awattar DE API         (api.awattar.de)
      AT -> Awattar AT API         (api.awattar.at)
  - ENTSO-E Transparency API kept as optional upgrade for all countries
    (free registration at transparency.entsoe.eu)
  - get_price_info() now includes 'source', 'today_all' fields
  - today_slots() is now public
  - _fetch chain: free source first -> ENTSO-E fallback if key available

Copyright (c) 2025 CloudEMS - https://cloudems.eu
"""
from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Optional

import aiohttp

from ..const import CONF_ENERGY_PRICES_COUNTRY, DEFAULT_EPEX_COUNTRY, EPEX_AREAS

_LOGGER = logging.getLogger(__name__)

ENTSOE_BASE     = "https://web-api.tp.entsoe.eu/api"
ENERGYZERO_BASE = "https://api.energyzero.nl/v1/energyprices"
AWATTAR_DE_BASE = "https://api.awattar.de/v1/marketdata"
AWATTAR_AT_BASE = "https://api.awattar.at/v1/marketdata"


class EnergyPriceFetcher:
    """
    EPEX spot-price fetcher for CloudEMSCoordinator.

    Fetch priority (first success wins):
      1. Free country-specific API  - NL (EnergyZero) / DE+AT (Awattar)
      2. ENTSO-E Transparency API   - all EU countries, free key required
    """

    def __init__(self, country=DEFAULT_EPEX_COUNTRY, session=None, api_key=None):
        self._country = country
        self._session = session
        self._api_key = api_key
        self._prices: list = []
        self._area   = EPEX_AREAS.get(country, "10YNL----------L")
        self._source  = "none"

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def data_source(self) -> str:
        return self._source

    @property
    def current_price(self) -> float:
        return self._get_current_price() or 0.0

    @property
    def min_price_today(self) -> float:
        p = [s["price"] for s in self.today_slots()]
        return min(p, default=0.0)

    @property
    def max_price_today(self) -> float:
        p = [s["price"] for s in self.today_slots()]
        return max(p, default=0.0)

    @property
    def avg_price_today(self) -> float:
        p = [s["price"] for s in self.today_slots()]
        return mean(p) if p else 0.0

    def is_negative_price(self, threshold: float = 0.0) -> bool:
        price = self._get_current_price()
        return price is not None and price <= threshold

    # ── Public API ────────────────────────────────────────────────────────────

    def today_slots(self) -> list:
        return self._today_slots()

    def get_next_hours(self, count: int = 24) -> list[dict]:
        now    = datetime.now(timezone.utc)
        result = []
        for s in self._prices:
            if self._aware(s["end"]) > now:
                start = self._aware(s["start"])
                result.append({
                    "hour":  start.hour,
                    "price": round(float(s["price"]), 5),
                    "start": start.isoformat(),
                    "label": start.strftime("%H:%M"),
                })
        return result[:count]

    def get_price_info(self) -> dict:
        """Returns complete price dict for coordinator and sensors."""
        current        = self._get_current_price()
        next_hours     = self.get_next_hours(24)
        today_slots    = self._today_slots()
        tomorrow_slots = self._tomorrow_slots()
        prices_today   = [s["price"] for s in today_slots]

        sorted_by_price = sorted(next_hours, key=lambda h: h["price"])
        cheapest_hours  = [h["hour"] for h in sorted_by_price]
        cheapest_2h     = _find_cheapest_window(next_hours, 2)
        cheapest_3h     = _find_cheapest_window(next_hours, 3)
        cheapest_4h     = _find_cheapest_window(next_hours, 4)
        now_hour        = datetime.now(timezone.utc).hour

        today_all = []
        for s in today_slots:
            start = self._aware(s["start"])
            today_all.append({
                "hour":  start.hour,
                "price": round(float(s["price"]), 5),
                "label": start.strftime("%H:%M"),
            })

        tomorrow_all = []
        for s in tomorrow_slots:
            start = self._aware(s["start"])
            tomorrow_all.append({
                "hour":  start.hour,
                "price": round(float(s["price"]), 5),
                "label": start.strftime("%H:%M"),
            })

        return {
            "current":            round(current, 5) if current is not None else None,
            "is_negative":        self.is_negative_price(),
            "min_today":          round(min(prices_today), 5) if prices_today else None,
            "max_today":          round(max(prices_today), 5) if prices_today else None,
            "avg_today":          round(mean(prices_today), 5) if prices_today else None,
            "next_hours":         next_hours,
            "today_all":          today_all,
            "tomorrow_all":       tomorrow_all,
            "tomorrow_available": len(tomorrow_all) > 0,
            "cheapest_hour_1":    cheapest_hours[0] if len(cheapest_hours) > 0 else None,
            "cheapest_hour_2":    cheapest_hours[1] if len(cheapest_hours) > 1 else None,
            "cheapest_hour_3":    cheapest_hours[2] if len(cheapest_hours) > 2 else None,
            "cheapest_2h_start":  cheapest_2h,
            "cheapest_3h_start":  cheapest_3h,
            "cheapest_4h_start":  cheapest_4h,
            "in_cheapest_1h":     now_hour in cheapest_hours[:1],
            "in_cheapest_2h":     now_hour in cheapest_hours[:2],
            "in_cheapest_3h":     now_hour in cheapest_hours[:3],
            "in_cheapest_4h":     now_hour in cheapest_hours[:4],
            "cheapest_1h_hours":  cheapest_hours[:1],
            "cheapest_2h_hours":  cheapest_hours[:2],
            "cheapest_3h_hours":  cheapest_hours[:3],
            "cheapest_4h_hours":  cheapest_hours[:4],
            "source":             self._source,
            "country":            self._country,
            "slot_count":         len(self._prices),
        }

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(self) -> None:
        if not self._session:
            return
        prices = []

        # 1. Free country-specific source
        if self._country == "NL":
            prices = await self._fetch_energyzero()
            if prices:
                self._source = "energyzero.nl"
        elif self._country == "DE":
            prices = await self._fetch_awattar(AWATTAR_DE_BASE)
            if prices:
                self._source = "awattar.de"
        elif self._country == "AT":
            prices = await self._fetch_awattar(AWATTAR_AT_BASE)
            if prices:
                self._source = "awattar.at"

        # 2. ENTSO-E fallback if free source failed or country not supported
        if not prices and self._api_key:
            prices = await self._fetch_entsoe()
            if prices:
                self._source = "ENTSO-E"

        if prices:
            self._prices = prices
            _LOGGER.debug(
                "CloudEMS prices: %d slots voor %s via %s",
                len(prices), self._country, self._source,
            )
        elif not self._prices:
            _LOGGER.warning(
                "CloudEMS: geen EPEX-prijzen geladen voor %s. "
                "NL/DE/AT werken gratis en zonder sleutel. "
                "Voor andere landen: voer een gratis ENTSO-E API-sleutel "
                "in via transparency.entsoe.eu",
                self._country,
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_current_price(self) -> Optional[float]:
        now = datetime.now(timezone.utc)
        for slot in self._prices:
            if self._aware(slot["start"]) <= now < self._aware(slot["end"]):
                return float(slot["price"])
        return None

    def _today_slots(self) -> list:
        now = datetime.now(timezone.utc)
        ts  = now.replace(hour=0, minute=0, second=0, microsecond=0)
        te  = ts + timedelta(days=1)
        return [s for s in self._prices if ts <= self._aware(s["start"]) < te]

    def _tomorrow_slots(self) -> list:
        now = datetime.now(timezone.utc)
        ts  = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        te  = ts + timedelta(days=1)
        return [s for s in self._prices if ts <= self._aware(s["start"]) < te]

    @staticmethod
    def _aware(dt) -> datetime:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if isinstance(dt, datetime) and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    # ── EnergyZero (NL, gratis) ───────────────────────────────────────────────

    async def _fetch_energyzero(self) -> list:
        try:
            now       = datetime.now(timezone.utc)
            from_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            till_date = from_date + timedelta(days=2)
            params = {
                "fromDate":  from_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "tillDate":  till_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "interval":  "4",
                "usageType": "1",
                "inclBtw":   "false",
            }
            async with self._session.get(
                ENERGYZERO_BASE, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("EnergyZero HTTP %d", resp.status)
                    return []
                data = await resp.json()
            prices = []
            for item in data.get("Prices", []):
                try:
                    start = datetime.fromisoformat(
                        item["readingDate"].replace("Z", "+00:00")
                    )
                    # EnergyZero returns EUR/kWh directly
                    prices.append({
                        "start": start,
                        "end":   start + timedelta(hours=1),
                        "price": float(item["price"]),
                    })
                except (KeyError, ValueError):
                    continue
            return sorted(prices, key=lambda x: x["start"])
        except Exception as err:
            _LOGGER.debug("EnergyZero fetch mislukt: %s", err)
            return []

    # ── Awattar (DE / AT, gratis) ─────────────────────────────────────────────

    async def _fetch_awattar(self, base_url: str) -> list:
        try:
            now      = datetime.now(timezone.utc)
            start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ms   = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)).timestamp() * 1000)
            async with self._session.get(
                base_url, params={"start": start_ms, "end": end_ms},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Awattar HTTP %d (%s)", resp.status, base_url)
                    return []
                data = await resp.json()
            prices = []
            for item in data.get("data", []):
                try:
                    start = datetime.fromtimestamp(
                        item["start_timestamp"] / 1000, tz=timezone.utc
                    )
                    # Awattar returns EUR/MWh -> convert to EUR/kWh
                    prices.append({
                        "start": start,
                        "end":   start + timedelta(hours=1),
                        "price": float(item["marketprice"]) / 1000.0,
                    })
                except (KeyError, ValueError):
                    continue
            return sorted(prices, key=lambda x: x["start"])
        except Exception as err:
            _LOGGER.debug("Awattar fetch mislukt (%s): %s", base_url, err)
            return []

    # ── ENTSO-E Transparency (alle landen, gratis key vereist) ────────────────

    async def _fetch_entsoe(self) -> list:
        if not self._api_key or not self._session:
            return []
        now    = datetime.now(timezone.utc)
        params = {
            "securityToken": self._api_key,
            "documentType":  "A44",
            "in_Domain":     self._area,
            "out_Domain":    self._area,
            "periodStart":   now.strftime("%Y%m%d0000"),
            "periodEnd":     (now + timedelta(days=1)).strftime("%Y%m%d2300"),
        }
        try:
            async with self._session.get(
                ENTSOE_BASE, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return self._parse_xml(await resp.text())
                _LOGGER.debug("ENTSO-E HTTP %d", resp.status)
        except Exception as err:
            _LOGGER.debug("ENTSO-E fetch mislukt: %s", err)
        return []

    def _parse_xml(self, xml_text: str) -> list:
        prices = []
        try:
            root = ET.fromstring(xml_text)
            ns   = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0"}
            for ts in root.findall(".//ns:TimeSeries", ns):
                period = ts.find(".//ns:Period", ns)
                if period is None:
                    continue
                se = period.find("ns:timeInterval/ns:start", ns)
                if se is None:
                    continue
                base = datetime.fromisoformat(se.text.replace("Z", "+00:00"))
                for pt in period.findall("ns:Point", ns):
                    pos       = int(pt.find("ns:position", ns).text)
                    price_mwh = float(pt.find("ns:price.amount", ns).text)
                    s         = base + timedelta(hours=pos - 1)
                    prices.append({
                        "start": s,
                        "end":   s + timedelta(hours=1),
                        "price": price_mwh / 1000.0,
                    })
        except Exception as err:
            _LOGGER.warning("ENTSO-E XML parse fout: %s", err)
        return sorted(prices, key=lambda x: x["start"])


def _find_cheapest_window(hours: list, window: int) -> Optional[int]:
    if len(hours) < window:
        return None
    h_sorted   = sorted(hours, key=lambda h: h.get("hour", 0))
    best_cost  = float("inf")
    best_start = None
    for i in range(len(h_sorted) - window + 1):
        cost = sum(h_sorted[j].get("price", 0) for j in range(i, i + window))
        if cost < best_cost:
            best_cost  = cost
            best_start = h_sorted[i].get("hour")
    return best_start


# Backwards compatibility alias
EPEXPriceFetcher = EnergyPriceFetcher
