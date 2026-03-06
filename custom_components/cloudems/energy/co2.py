# -*- coding: utf-8 -*-
"""
CloudEMS CO2 Intensity — v1.9.0

Fetches the current grid carbon intensity (gCO2/kWh) for the configured country.

Sources (in priority order):
  1. Electricity Maps API v3 (free tier, no key needed for basic zones)
  2. CO2 Signal API (free with token)
  3. Static European averages (EEA 2023 data, always works offline)

The CO2 intensity is used to:
  - Show users when the grid is "green" vs "dirty"
  - Optionally delay flexible loads (EV, boiler) to cleaner grid hours
  - Calculate lifecycle CO2 savings from self-consumption

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from typing import Optional

import aiohttp

from ..const import (
    CO2_COUNTRY_DEFAULTS,
    ELECTRICITY_MAP_FREE_URL,
    CO2_SIGNAL_URL,
)

_LOGGER = logging.getLogger(__name__)

# Zone codes for Electricity Maps (country → zone)
_EM_ZONES = {
    "NL": "NL", "DE": "DE", "BE": "BE", "FR": "FR",
    "AT": "AT", "DK": "DK-DK1", "NO": "NO-NO1",
    "SE": "SE-SE3", "FI": "FI", "CH": "CH",
    "GB": "GB", "ES": "ES", "IT": "IT-NO", "PL": "PL",
}

# Update interval: 15 minutes (CO2 intensity changes slowly)
UPDATE_INTERVAL_S = 900


class CO2IntensityFetcher:
    """
    Fetches real-time grid carbon intensity.

    Usage:
        fetcher = CO2IntensityFetcher("NL", session)
        await fetcher.update()
        print(fetcher.current_gco2_kwh)   # e.g. 245
    """

    def __init__(
        self,
        country: str,
        session: aiohttp.ClientSession,
        co2signal_token: Optional[str] = None,
    ) -> None:
        self._country     = country.upper()
        self._session     = session
        self._token       = co2signal_token

        self._current_g: Optional[float] = None
        self._source:    str             = "static_default"
        self._last_update: float         = 0.0

        # Use static default immediately as fallback
        self._static_g = float(CO2_COUNTRY_DEFAULTS.get(self._country, 350))

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def current_gco2_kwh(self) -> float:
        """Current CO2 intensity in gCO2eq/kWh. Falls back to static average."""
        return self._current_g if self._current_g is not None else self._static_g

    @property
    def source(self) -> str:
        return self._source

    @property
    def is_live(self) -> bool:
        return self._source != "static_default"

    def is_green(self, threshold_g: float = 200.0) -> bool:
        """True when grid is cleaner than threshold (default 200g CO2/kWh)."""
        return self.current_gco2_kwh < threshold_g

    def is_dirty(self, threshold_g: float = 400.0) -> bool:
        """True when grid is dirtier than threshold (default 400g CO2/kWh)."""
        return self.current_gco2_kwh > threshold_g

    async def update(self) -> None:
        """Fetch latest CO2 intensity. Skips if recently updated."""
        if time.time() - self._last_update < UPDATE_INTERVAL_S:
            return

        # Try Electricity Maps first (no key required for basic zones)
        if await self._fetch_electricity_maps():
            self._last_update = time.time()
            return

        # Try CO2 Signal (needs free token)
        if self._token and await self._fetch_co2signal():
            self._last_update = time.time()
            return

        # Fall back to static defaults
        self._current_g = self._static_g
        self._source    = "static_default"
        self._last_update = time.time()

    # ── Fetch methods ──────────────────────────────────────────────────────────

    async def _fetch_electricity_maps(self) -> bool:
        """Fetch from Electricity Maps free API."""
        zone = _EM_ZONES.get(self._country)
        if not zone:
            return False
        try:
            url = f"{ELECTRICITY_MAP_FREE_URL}?zone={zone}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    intensity = data.get("carbonIntensity")
                    if intensity is not None:
                        self._current_g = round(float(intensity), 1)
                        self._source    = "electricitymap"
                        _LOGGER.debug(
                            "CO2 intensity (%s): %.0f gCO2/kWh [electricitymap]",
                            self._country, self._current_g,
                        )
                        return True
        except Exception as err:
            _LOGGER.debug("CO2 electricitymap fetch failed: %s", err)
        return False

    async def _fetch_co2signal(self) -> bool:
        """Fetch from CO2 Signal API (requires free token)."""
        try:
            url  = f"{CO2_SIGNAL_URL}?countryCode={self._country}"
            headers = {"auth-token": self._token}
            async with self._session.get(url, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    intensity = data.get("data", {}).get("carbonIntensity")
                    if intensity is not None:
                        self._current_g = round(float(intensity), 1)
                        self._source    = "co2signal"
                        return True
        except Exception as err:
            _LOGGER.debug("CO2 co2signal fetch failed: %s", err)
        return False

    def get_info(self) -> dict:
        """Return full CO2 info dict for coordinator and sensors."""
        g = self.current_gco2_kwh
        return {
            "current_gco2_kwh":  g,
            "source":            self._source,
            "is_live":           self.is_live,
            "is_green":          self.is_green(),
            "is_dirty":          self.is_dirty(),
            "country":           self._country,
            "static_default_g":  self._static_g,
            "label":             (
                "🟢 Groen" if g < 150
                else "🟡 Gemiddeld" if g < 300
                else "🟠 Vuil" if g < 500
                else "🔴 Zeer vuil"
            ),
        }
