"""
CloudEMS EPEX Spot Price Fetcher — v1.4.1

BUG FIXES vs v1.4.0:
  - Added get_price_info() method (coordinator called it but it didn't exist)
  - get_next_hours(): hour field is now int (was "HH:MM" string, caused cheap-hour mismatch)
  - Added cheapest_hour_1/2/3 and window calculations inside get_price_info()

Copyright © 2025 CloudEMS — https://cloudems.eu
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

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"


class EnergyPriceFetcher:
    """
    EPEX spot-price fetcher for CloudEMSCoordinator.

    Interface:
        await .update()
        .current_price               -> float
        .min_price_today             -> float
        .max_price_today             -> float
        .avg_price_today             -> float
        .is_negative_price(threshold) -> bool
        .get_next_hours(n)           -> list[dict]  (hour is int)
        .get_price_info()            -> dict        ← NEW in v1.4.1
    """

    def __init__(self, country=DEFAULT_EPEX_COUNTRY, session=None, api_key=None):
        self._country = country
        self._session = session
        self._api_key = api_key
        self._prices: list = []
        self._area   = EPEX_AREAS.get(country, "10YNL----------L")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_price(self) -> float:
        return self._get_current_price() or 0.0

    @property
    def min_price_today(self) -> float:
        p = [s["price"] for s in self._today_slots()]
        return min(p, default=0.0)

    @property
    def max_price_today(self) -> float:
        p = [s["price"] for s in self._today_slots()]
        return max(p, default=0.0)

    @property
    def avg_price_today(self) -> float:
        p = [s["price"] for s in self._today_slots()]
        return mean(p) if p else 0.0

    def is_negative_price(self, threshold: float = 0.0) -> bool:
        price = self._get_current_price()
        return price is not None and price <= threshold

    # ── get_next_hours ────────────────────────────────────────────────────────

    def get_next_hours(self, count: int = 24) -> list[dict]:
        """
        Returns upcoming hourly prices.
        'hour' is an int (0-23) — FIX: was "HH:MM" string in v1.4.0
        """
        now    = datetime.now(timezone.utc)
        result = []
        for s in self._prices:
            if self._aware(s["end"]) > now:
                start = self._aware(s["start"])
                result.append({
                    "hour":  start.hour,           # ← FIX: int not string
                    "price": round(float(s["price"]), 5),
                    "start": start.isoformat(),
                    "label": start.strftime("%H:%M"),
                })
        return result[:count]

    # ── get_price_info ────────────────────────────────────────────────────────

    def get_price_info(self) -> dict:
        """
        Returns complete price dict for coordinator.
        FIX: This method was called by coordinator but didn't exist in v1.4.0.
        """
        current      = self._get_current_price()
        next_hours   = self.get_next_hours(24)
        today_slots  = self._today_slots()
        prices_today = [s["price"] for s in today_slots]

        # Cheapest individual hours
        sorted_by_price = sorted(next_hours, key=lambda h: h["price"])
        cheapest_hours  = [h["hour"] for h in sorted_by_price]

        # Cheapest contiguous 2h and 3h windows
        cheapest_2h = _find_cheapest_window(next_hours, 2)
        cheapest_3h = _find_cheapest_window(next_hours, 3)

        # Is current hour in cheapest N?
        now_hour = datetime.now(timezone.utc).hour

        return {
            "current":          round(current, 5) if current is not None else None,
            "is_negative":      self.is_negative_price(),
            "min_today":        round(min(prices_today), 5) if prices_today else None,
            "max_today":        round(max(prices_today), 5) if prices_today else None,
            "avg_today":        round(mean(prices_today), 5) if prices_today else None,
            "next_hours":       next_hours,
            # Cheapest individual hours (rank 1, 2, 3)
            "cheapest_hour_1":  cheapest_hours[0] if len(cheapest_hours) > 0 else None,
            "cheapest_hour_2":  cheapest_hours[1] if len(cheapest_hours) > 1 else None,
            "cheapest_hour_3":  cheapest_hours[2] if len(cheapest_hours) > 2 else None,
            # Cheapest windows
            "cheapest_2h_start": cheapest_2h,
            "cheapest_3h_start": cheapest_3h,
            # Is now in cheapest N hours?
            "in_cheapest_1h":   now_hour in cheapest_hours[:1],
            "in_cheapest_2h":   now_hour in cheapest_hours[:2],
            "in_cheapest_3h":   now_hour in cheapest_hours[:3],
            "cheapest_1h_hours": cheapest_hours[:1],
            "cheapest_2h_hours": cheapest_hours[:2],
            "cheapest_3h_hours": cheapest_hours[:3],
        }

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(self) -> None:
        if not self._session:
            return
        try:
            prices = await self._fetch_entsoe()
            if prices:
                self._prices = prices
                _LOGGER.debug("CloudEMS: %d EPEX slots for %s", len(prices), self._country)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("EnergyPriceFetcher.update failed: %s", err)

    # ── Internal helpers ──────────────────────────────────────────────────────

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

    @staticmethod
    def _aware(dt) -> datetime:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if isinstance(dt, datetime) and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

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
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ENTSO-E fetch failed: %s", err)
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
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ENTSO-E XML parse error: %s", err)
        return sorted(prices, key=lambda x: x["start"])


def _find_cheapest_window(hours: list, window: int) -> Optional[int]:
    """Find start hour (int) of cheapest contiguous window of given size."""
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
