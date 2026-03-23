# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
NationalGridMonitor — v1.1.0

Monitors national renewable energy production to derive a grid surplus signal
and CO2 intensity. Used to improve battery/EV charging decisions.

Countries supported:
  NL — NED API (api.ned.nl), free account required, 10-min resolution
  DE — stub (SMARD API planned)
  BE — stub (Elia API planned)
  Other — static fallback values

NL NED API:
  Endpoint: https://api.ned.nl/v1/utilizations
  Auth:     X-AUTH-TOKEN header (free registration at ned.nl)
  Rate:     200 requests / 5 minutes
  Fields:   capacity (kW), validfrom, type (2=solar, 4=wind onshore, 5=wind offshore)

Surplus signal:
  If >60% of NL electricity comes from solar + wind, EPEX tends toward
  zero or negative. Battery/EV charging is favoured in this condition.

CO2 intensity estimate:
  Based on renewable fraction: high renewables → low CO2/kWh.
  Average NL grid: ~230 g CO2/kWh (2025). Pure renewable: ~5 g CO2/kWh.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

FETCH_INTERVAL_S   = 600    # every 10 minutes
SURPLUS_THRESHOLD  = 0.60   # renewable fraction above which surplus signal fires
NED_API_URL        = "https://api.ned.nl/v1/utilizations"

# NL total installed capacity estimates (GW) — update annually
NL_CAPACITY_GW = {
    "solar":          23.0,
    "wind_onshore":   7.0,
    "wind_offshore":  4.5,
    "total":          45.0,   # approximate total dispatchable + renewable
}

# NED API energy type IDs
NED_TYPE_SOLAR        = 2
NED_TYPE_WIND_ONSHORE = 4
NED_TYPE_WIND_OFFSHORE = 5

# Average grid CO2 intensity (g/kWh) per country
AVG_CO2_INTENSITY: dict[str, float] = {
    "NL": 230.0,
    "DE": 350.0,
    "BE": 170.0,
    "FR": 65.0,
    "GB": 180.0,
}
# Minimum CO2 at 100% renewable (lifecycle emissions)
MIN_CO2_G_KWH = 5.0


class NationalGridMonitor:
    """Monitors national grid renewable fraction and CO2 intensity."""

    def __init__(self, hass, config: dict) -> None:
        self._hass        = hass
        self._session     = None
        self._api_key     = config.get("ned_api_key", "")
        self._country     = config.get("country", "NL").upper()
        self._enabled     = bool(self._api_key) or self._country != "NL"
        self._last_fetch  = 0.0
        self._fetch_errors: int = 0

        # State
        self._solar_mw:      float = 0.0
        self._wind_mw:       float = 0.0
        self._renewable_pct: float = 0.0
        self._surplus:       bool  = False
        self._co2_g_kwh:     float = AVG_CO2_INTENSITY.get(self._country, 250.0)
        self._ts:            str   = ""

    async def async_setup(self) -> None:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)

    async def async_update(self) -> dict:
        """Fetch latest grid data and return current state."""
        now = time.time()
        if now - self._last_fetch > FETCH_INTERVAL_S:
            if self._country == "NL" and self._api_key:
                await self._fetch_nl_ned()
            # Other countries: future implementations
            self._last_fetch = now
        return self._build_state()

    async def _fetch_nl_ned(self) -> None:
        """Fetch Dutch grid data from NED API."""
        if not self._session:
            return
        try:
            # Request last 30 minutes of data to get the most recent values
            now_utc    = datetime.now(timezone.utc)
            since      = (now_utc - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
            params     = {
                "itemsPerPage": "10",
                "validfrom[after]": since,
                "type[]": [str(NED_TYPE_SOLAR), str(NED_TYPE_WIND_ONSHORE), str(NED_TYPE_WIND_OFFSHORE)],
                "granularity": "15",
                "granularitytimezone": "UTC",
                "classification": "1",  # actual
                "activity": "1",        # production
            }
            headers = {"X-AUTH-TOKEN": self._api_key}
            async with self._session.get(NED_API_URL, params=params, headers=headers, timeout=10) as r:
                if r.status == 401:
                    _LOGGER.warning("NationalGridMonitor: invalid NED API key")
                    return
                if r.status != 200:
                    _LOGGER.warning("NationalGridMonitor: NED API returned HTTP %s", r.status)
                    return
                data   = await r.json()
                rows   = data.get("hydra:member", [])
                if not rows:
                    return

                solar_mw = wind_mw = 0.0
                for row in rows:
                    cap_w  = float(row.get("capacity", 0))
                    cap_mw = cap_w / 1_000_000
                    t      = row.get("type", {}).get("id", 0)
                    if t == NED_TYPE_SOLAR:
                        solar_mw = max(solar_mw, cap_mw)
                    elif t in (NED_TYPE_WIND_ONSHORE, NED_TYPE_WIND_OFFSHORE):
                        wind_mw += cap_mw

                self._solar_mw = solar_mw
                self._wind_mw  = wind_mw
                total_cap_mw   = NL_CAPACITY_GW["total"] * 1000
                self._renewable_pct = min(1.0, (solar_mw + wind_mw) / max(total_cap_mw, 1))
                self._surplus       = self._renewable_pct >= SURPLUS_THRESHOLD
                self._ts            = now_utc.strftime("%H:%M")
                self._fetch_errors  = 0

                # Estimate CO2 intensity
                avg   = AVG_CO2_INTENSITY.get(self._country, 250.0)
                self._co2_g_kwh = round(
                    MIN_CO2_G_KWH + avg * (1.0 - self._renewable_pct), 1
                )
                _LOGGER.debug(
                    "NationalGridMonitor NL: solar=%.0fMW wind=%.0fMW ren=%.0f%% co2=%.0fg/kWh",
                    solar_mw, wind_mw, self._renewable_pct * 100, self._co2_g_kwh
                )
        except Exception as exc:
            self._fetch_errors += 1
            _LOGGER.warning("NationalGridMonitor: fetch error (%s)", exc)

    def _build_state(self) -> dict:
        return {
            "solar_mw":       round(self._solar_mw, 1),
            "wind_mw":        round(self._wind_mw, 1),
            "renewable_pct":  round(self._renewable_pct * 100, 1),
            "surplus":        self._surplus,
            "co2_g_kwh":      self._co2_g_kwh,
            "timestamp":      self._ts,
            "country":        self._country,
            "fetch_errors":   self._fetch_errors,
            "api_configured": bool(self._api_key),
        }

    @property
    def surplus(self) -> bool:
        return self._surplus

    @property
    def co2_g_kwh(self) -> float:
        return self._co2_g_kwh

    @property
    def co2_intensity(self) -> float:
        """Alias for co2_g_kwh — used by coordinator."""
        return self._co2_g_kwh

    @property
    def renewable_pct(self) -> float:
        return self._renewable_pct

    @property
    def is_fresh(self) -> bool:
        """True if data was fetched successfully at least once."""
        return self._ts != "" and self._fetch_errors < 3

    @property
    def surplus_signal(self) -> bool:
        """True when renewable fraction exceeds surplus threshold."""
        return self._surplus

    async def async_maybe_fetch(self) -> None:
        """Fetch if interval has elapsed (alias for async_update)."""
        await self.async_update()



    def get_data(self) -> dict:
        """Return current state as dict (coordinator-facing)."""
        return self._build_state()

# Backwards-compatible alias
NedNationalGrid = NationalGridMonitor
