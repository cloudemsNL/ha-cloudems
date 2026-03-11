# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS EPEX Spot Price Fetcher — v1.6.1

Changelog vs v1.6.0:
  - Tijdzone-fix: alle "lokale uur"-berekeningen (cheapest_Nh_start,
    in_cheapest_Nh, today_all, tomorrow_all) gebruiken nu de lokale
    tijdzone van de HA-instantie.
  - Zomer-/wintertijd (DST) wordt automatisch correct afgehandeld
    via Python's zoneinfo / dateutil.
  - time_zone parameter toegevoegd aan constructor (optioneel, default UTC).
  - _today_slots / _tomorrow_slots gebruiken lokale daggrens.

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


def _get_tz(time_zone: str | None):
    """Return a tzinfo object for the given timezone name.

    Tries zoneinfo (Python 3.9+) first, falls back to dateutil, then UTC.
    """
    if not time_zone:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(time_zone)
    except Exception:
        pass
    try:
        from dateutil import tz as _tz
        result = _tz.gettz(time_zone)
        if result is not None:
            return result
    except Exception:
        pass
    _LOGGER.warning("CloudEMS: kon tijdzone '%s' niet laden, UTC wordt gebruikt", time_zone)
    return timezone.utc


class EnergyPriceFetcher:
    """
    EPEX spot-price fetcher for CloudEMSCoordinator.

    Fetch priority (first success wins):
      1. Free country-specific API  - NL (EnergyZero) / DE+AT (Awattar)
      2. ENTSO-E Transparency API   - all EU countries, free key required

    Args:
        time_zone: HA timezone string, e.g. "Europe/Amsterdam".
                   Used for local-hour calculations (cheapest blocks,
                   today/tomorrow boundaries). Handles DST automatically.
    """

    def __init__(self, country=DEFAULT_EPEX_COUNTRY, session=None, api_key=None,
                 time_zone: str | None = None):
        self._country   = country
        self._session   = session
        self._api_key   = api_key
        self._prices: list = []
        self._area      = EPEX_AREAS.get(country, "10YNL----------L")
        self._source    = "none"
        self._local_tz  = _get_tz(time_zone)
        # Rolling 30-daags daggemiddelden voor ROI-berekening
        # Formaat: list van floats (kale EPEX daggemiddelde), max 30 entries
        self._daily_avg_history: list[float] = []

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def data_source(self) -> str:
        return self._source

    @property
    def current_price(self) -> Optional[float]:
        """Huidige spotprijs, of None als geen slot beschikbaar (API fout / overgang)."""
        return self._get_current_price()

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
        """Return upcoming price slots with LOCAL hour numbers."""
        now    = datetime.now(timezone.utc)
        result = []
        for s in self._prices:
            if self._aware(s["end"]) > now:
                start_local = self._aware(s["start"]).astimezone(self._local_tz)
                result.append({
                    "hour":  start_local.hour,
                    "price": round(float(s["price"]), 5),
                    "start": self._aware(s["start"]).isoformat(),
                    "label": start_local.strftime("%H:%M"),
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
        cheapest_4h_block = _cheapest_window_detail(next_hours, 4)  # v1.20: rich detail

        # in_cheapest_Nh: zit het HUIDIGE uur in het goedkoopste aaneengesloten N-uur blok?
        # next_hours[0] is het huidige (lopende) uur — index 0 = "nu".
        # _find_cheapest_window_indices geeft de set van indices in het goedkoopste blok.
        # Als index 0 in die set zit, zijn we nu in het goedkoopste blok.
        _in_1h = 0 in _find_cheapest_window_indices(next_hours, 1)
        _in_2h = 0 in _find_cheapest_window_indices(next_hours, 2)
        _in_3h = 0 in _find_cheapest_window_indices(next_hours, 3)
        _in_4h = 0 in _find_cheapest_window_indices(next_hours, 4)

        today_all = []
        for s in today_slots:
            start_local = self._aware(s["start"]).astimezone(self._local_tz)
            today_all.append({
                "hour":  start_local.hour,
                "price": round(float(s["price"]), 5),
                "label": start_local.strftime("%H:%M"),
            })

        tomorrow_all = []
        for s in tomorrow_slots:
            start_local = self._aware(s["start"]).astimezone(self._local_tz)
            tomorrow_all.append({
                "hour":  start_local.hour,
                "price": round(float(s["price"]), 5),
                "label": start_local.strftime("%H:%M"),
            })

        return {
            "current":            round(current, 5) if current is not None else None,
            "is_negative":        self.is_negative_price(),
            "min_today":          round(min(prices_today), 5) if prices_today else None,
            "max_today":          round(max(prices_today), 5) if prices_today else None,
            "avg_today":          round(mean(prices_today), 5) if prices_today else None,
            "rolling_avg_30d":    round(mean(self._daily_avg_history), 5) if self._daily_avg_history else None,
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
            "cheapest_4h_block":  cheapest_4h_block,       # v1.20: volledige blok-info
            # Blok-gebaseerde check: zit het huidige uur in het goedkoopste N-uur blok?
            # Correct ook als morgen-uren goedkoper zijn: we kijken naar blok-lidmaatschap,
            # niet naar prijs-drempel.
            "in_cheapest_1h":     _in_1h,
            "in_cheapest_2h":     _in_2h,
            "in_cheapest_3h":     _in_3h,
            "in_cheapest_4h":     _in_4h,
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
            # Rolling 30-daags daggemiddelde bijhouden voor ROI-berekening
            today_p = [s["price"] for s in self._today_slots()]
            if today_p:
                from statistics import mean as _mean
                day_avg = _mean(today_p)
                # Voeg toe als het afwijkt van vorige (vermijd duplicaten bij meerdere fetches/dag)
                if not self._daily_avg_history or abs(self._daily_avg_history[-1] - day_avg) > 0.001:
                    self._daily_avg_history.append(day_avg)
                    if len(self._daily_avg_history) > 30:
                        self._daily_avg_history = self._daily_avg_history[-30:]
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
        """Prijsslots voor de lokale kalenderdag van vandaag."""
        now_local = datetime.now(timezone.utc).astimezone(self._local_tz)
        ts_local  = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        te_local  = ts_local + timedelta(days=1)
        # Vergelijk in UTC om DST-overgangen correct te verwerken
        ts_utc = ts_local.astimezone(timezone.utc)
        te_utc = te_local.astimezone(timezone.utc)
        return [s for s in self._prices if ts_utc <= self._aware(s["start"]) < te_utc]

    def _tomorrow_slots(self) -> list:
        """Prijsslots voor de lokale kalenderdag van morgen."""
        now_local = datetime.now(timezone.utc).astimezone(self._local_tz)
        ts_local  = now_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        te_local  = ts_local + timedelta(days=1)
        ts_utc = ts_local.astimezone(timezone.utc)
        te_utc = te_local.astimezone(timezone.utc)
        return [s for s in self._prices if ts_utc <= self._aware(s["start"]) < te_utc]

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
    """Vind het goedkoopste aaneengesloten blok van `window` uren.

    De `hours`-lijst is in CHRONOLOGISCHE volgorde (zoals get_next_hours() levert).
    We sorteren NIET op uur-nummer want 01:00 morgen komt chronologisch NA 23:00 vandaag
    maar heeft een lager uur-nummer — sorteren op uur zou de volgorde breken.

    Retourneert: het start-uur (0-23) van het goedkoopste blok, of None.
    """
    if len(hours) < window:
        return None
    # hours is al in chronologische volgorde — niet opnieuw sorteren
    best_cost  = float("inf")
    best_start = None
    for i in range(len(hours) - window + 1):
        cost = sum(hours[j].get("price", 0) for j in range(i, i + window))
        if cost < best_cost:
            best_cost  = cost
            best_start = hours[i].get("hour")
    return best_start


def _find_cheapest_window_indices(hours: list, window: int) -> set:
    """Geef de INDEX-set van het goedkoopste blok — voor in_cheapest_Nh check."""
    if len(hours) < window:
        return set()
    best_cost = float("inf")
    best_idx  = 0
    for i in range(len(hours) - window + 1):
        cost = sum(hours[j].get("price", 0) for j in range(i, i + window))
        if cost < best_cost:
            best_cost = cost
            best_idx  = i
    return set(range(best_idx, best_idx + window))


def _cheapest_window_detail(hours: list, window: int) -> Optional[dict]:
    """Like _find_cheapest_window but returns a rich detail dict.

    Returns:
        {
          "start_hour":  14,           # first hour of block (0-23)
          "end_hour":    18,           # exclusive end (start + window)
          "hours":       [14,15,16,17],
          "prices":      [0.08, 0.07, 0.09, 0.08],   # EUR/kWh per hour
          "avg_price":   0.080,        # average over block
          "total_cost":  0.320,        # sum (useful for full-charge cost estimate)
          "label":       "14:00–18:00",
        }
        or None if not enough data.
    """
    if len(hours) < window:
        return None
    # Bewaar chronologische volgorde — niet sorteren op hour-nummer
    best_cost  = float("inf")
    best_idx   = 0
    for i in range(len(hours) - window + 1):
        cost = sum(hours[j].get("price", 0) for j in range(i, i + window))
        if cost < best_cost:
            best_cost = cost
            best_idx  = i

    slot_hours  = [hours[best_idx + k].get("hour") for k in range(window)]
    slot_prices = [round(hours[best_idx + k].get("price", 0), 5) for k in range(window)]
    start_h     = slot_hours[0]
    end_h       = start_h + window
    avg_p       = round(best_cost / window, 5)

    return {
        "start_hour": start_h,
        "end_hour":   end_h,
        "hours":      slot_hours,
        "prices":     slot_prices,
        "avg_price":  avg_p,
        "total_cost": round(best_cost, 5),
        "label":      f"{start_h:02d}:00–{end_h:02d}:00",
    }


# Backwards compatibility alias
EPEXPriceFetcher = EnergyPriceFetcher
