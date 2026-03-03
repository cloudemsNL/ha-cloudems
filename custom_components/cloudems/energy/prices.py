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


class EnergyPriceFetcher:
    """
    Adapter used by CloudEMSCoordinator.

    Wraps ENTSO-E / HA integration price sources and exposes the
    simple interface the coordinator expects:
      - EnergyPriceFetcher(country, session, api_key)
      - await .update()
      - .current_price  (float, EUR/kWh)
      - .is_negative_price(threshold) -> bool
      - .get_cheapest_slots(n) -> list[dict]
    """

    def __init__(
        self,
        country: str = DEFAULT_EPEX_COUNTRY,
        session: Any | None = None,
        api_key: str | None = None,
    ) -> None:
        self._country = country
        self._session = session
        self._api_key = api_key
        self._prices: list[dict] = []
        self._area = EPEX_AREAS.get(country, "10YNL----------L")

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def current_price(self) -> float:
        """Return current EUR/kWh price, 0.0 if unknown."""
        return self._get_current_price() or 0.0

    def is_negative_price(self, threshold: float = 0.0) -> bool:
        """Return True when current price is at or below *threshold*."""
        price = self._get_current_price()
        if price is None:
            return False
        return price <= threshold

    def get_cheapest_slots(self, count: int = 3) -> list[dict]:
        """Return the cheapest *count* upcoming hourly slots."""
        now = datetime.now(timezone.utc)
        upcoming = [s for s in self._prices if s["end"] > now]
        return sorted(upcoming, key=lambda x: x["price"])[:count]

    async def update(self) -> None:
        """Fetch / refresh prices from ENTSO-E or skip gracefully."""
        if not self._session:
            return
        try:
            prices = await self._fetch_entsoe()
            if prices:
                self._prices = prices
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("EnergyPriceFetcher.update failed: %s", err)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_current_price(self) -> float | None:
        now = datetime.now(timezone.utc)
        for slot in self._prices:
            start = slot["start"]
            end = slot["end"]
            # Ensure both are offset-aware for comparison
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if start <= now < end:
                return float(slot["price"])
        return None

    async def _fetch_entsoe(self) -> list[dict]:
        if not self._session:
            return []
        token = self._api_key
        if not token:
            return []

        now = datetime.now(timezone.utc)
        period_start = now.strftime("%Y%m%d0000")
        period_end = (now + timedelta(days=1)).strftime("%Y%m%d2300")

        params = {
            "securityToken": token,
            "documentType": "A44",
            "in_Domain": self._area,
            "out_Domain": self._area,
            "periodStart": period_start,
            "periodEnd": period_end,
        }

        try:
            async with self._session.get(
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
                    slot_start = start + timedelta(hours=pos - 1)
                    prices.append({
                        "start": slot_start,
                        "end": slot_start + timedelta(hours=1),
                        "price": price_mwh / 1000.0,
                    })
        except Exception as err:
            _LOGGER.warning("ENTSO-E XML parse error: %s", err)

        return sorted(prices, key=lambda x: x["start"])

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
