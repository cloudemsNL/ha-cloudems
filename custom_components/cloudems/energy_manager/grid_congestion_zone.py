# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
GridCongestionZone — v1.1.0

Detects whether the household's grid connection is in a congestion zone
and adjusts export/charging behaviour accordingly.

Countries supported:
  NL — capaciteitskaart.netbeheernederland.nl (public, no API key)
  BE — stub (Elia congestion map planned)
  DE — stub (Bundesnetzagentur planned)

NL: The Dutch capacity map uses a public REST API that returns congestion
status per postal code area. When congestion is detected, CloudEMS will:
  - Limit battery export to avoid grid stress
  - Prefer self-consumption over feed-in
  - Log the congestion reason in decisions
"""

from __future__ import annotations

import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

FETCH_INTERVAL_S = 86_400   # check once per day
NL_CAPACITY_MAP  = "https://capaciteitskaart.netbeheernederland.nl/api/postcodes"


class GridCongestionZone:
    """Detects grid congestion in the household's postal code area."""

    def __init__(self, hass, config: dict) -> None:
        self._hass        = hass
        self._session     = None
        self._postal_code = config.get("postal_code", "")
        self._country     = config.get("country", "NL").upper()
        self._last_fetch  = 0.0
        self._fetch_errors: int = 0

        # State
        self._in_congestion_zone: bool  = False
        self._congestion_level:   str   = "none"   # none / low / medium / high
        self._congestion_reason:  str   = ""
        self._grid_operator:      str   = ""
        self._last_checked:       str   = ""

    async def async_setup(self) -> None:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)

    async def async_update(self) -> dict:
        """Check congestion zone status for the configured postal code."""
        now = time.time()
        if now - self._last_fetch > FETCH_INTERVAL_S:
            if self._country == "NL" and self._postal_code:
                await self._check_nl_congestion()
            self._last_fetch = now
        return self._build_state()

    async def _check_nl_congestion(self) -> None:
        """Check Dutch capacity map for congestion in postal code."""
        if not self._session:
            return
        # Extract 4-digit postal code prefix
        pc4 = self._postal_code[:4].strip()
        if not pc4.isdigit():
            return
        try:
            url = f"{NL_CAPACITY_MAP}/{pc4}"
            async with self._session.get(url, timeout=10) as r:
                if r.status == 404:
                    # Not in congestion registry — no congestion
                    self._in_congestion_zone = False
                    self._congestion_level   = "none"
                    self._fetch_errors       = 0
                    return
                if r.status != 200:
                    _LOGGER.warning("GridCongestionZone: NL API returned HTTP %s", r.status)
                    self._fetch_errors += 1
                    return
                data = await r.json()
                # Parse response — schema may vary; use safe fallback
                level  = str(data.get("congestieniveau", data.get("level", "none"))).lower()
                reason = str(data.get("omschrijving", data.get("reason", "")))
                operator = str(data.get("netbeheerder", data.get("operator", "")))
                level_map = {"geen": "none", "laag": "low", "midden": "medium",
                             "hoog": "high", "kritiek": "high"}
                level = level_map.get(level, level if level in ("none", "low", "medium", "high") else "none")
                self._in_congestion_zone = level != "none"
                self._congestion_level   = level
                self._congestion_reason  = reason
                self._grid_operator      = operator
                self._fetch_errors       = 0
                if self._in_congestion_zone:
                    _LOGGER.warning(
                        "GridCongestionZone: postal code %s is in congestion zone (level=%s)",
                        pc4, level
                    )
        except Exception as exc:
            self._fetch_errors += 1
            _LOGGER.warning("GridCongestionZone: check error (%s)", exc)

    def _build_state(self) -> dict:
        return {
            "in_congestion_zone": self._in_congestion_zone,
            "congestion_level":   self._congestion_level,
            "congestion_reason":  self._congestion_reason,
            "grid_operator":      self._grid_operator,
            "postal_code":        self._postal_code,
            "country":            self._country,
            "fetch_errors":       self._fetch_errors,
        }

    @property
    def in_congestion_zone(self) -> bool:
        return self._in_congestion_zone

    @property
    def congestion_level(self) -> str:
        return self._congestion_level

    async def async_maybe_fetch(self) -> None:
        """Fetch if interval has elapsed (alias for async_update)."""
        await self.async_update()

    @property
    def export_restricted(self) -> bool:
        """True when congestion level is medium or high — limit feed-in."""
        return self._congestion_level in ("medium", "high")


    def get_data(self) -> dict:
        """Return current state as dict (coordinator-facing)."""
        return self._build_state()
