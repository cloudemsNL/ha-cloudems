# -*- coding: utf-8 -*-
"""
CloudEMS EPEX Spot Price Fetcher.

Retrieves day-ahead prices from ENTSO-E Transparency Platform.
Falls back to Tibber API if configured.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import CONF_EPEX_COUNTRY, DEFAULT_EPEX_COUNTRY, EPEX_AREAS

_LOGGER = logging.getLogger(__name__)

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
ENTSOE_TOKEN_ENV = "ENTSOE_TOKEN"


class EPEXPriceFetcher:
    """Fetches EPEX spot prices from ENTSO-E or Tibber."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config = {**entry.data, **entry.options}
        self.prices: list[dict] = []
        self._country = self.config.get(CONF_EPEX_COUNTRY, DEFAULT_EPEX_COUNTRY)

    async def async_setup(self) -> None:
        _LOGGER.info("EPEX price fetcher ready for area: %s", self._country)

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
            async with aiohttp.ClientSession() as session:
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
