# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
BatteryBenchmarkReporter — v1.2.0

Posts battery performance data to external benchmark services.
Currently supports Mijnbatterij.nl (Netherlands).

The reporter is designed to be extended with additional benchmark platforms
(e.g. SolarEdge Community, pvoutput.org, battery vendor cloud APIs).

Mijnbatterij.nl API:
  POST endpoint: https://api.mijnbatterij.nl/api/live
  Method:        POST (JSON)
  Fields:        batteryResult, batteryCharge, batteryPower,
                 chargedToday, dischargedToday, solarResult, totalBatteryCycles
  Auth:          api_key in payload
  Rate:          at most once per 5 minutes

  GET endpoint:  https://api.mijnbatterij.nl/api/user/stats
  Auth:          X-API-Key header
  Returns:       rank, score, totalUsers, percentile, todayResult, monthResult, profileUrl
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

POST_INTERVAL_S  = 300   # maximum once every 5 minutes
MIJNBATTERIJ_URL = "https://api.mijnbatterij.nl/api/live"


class BatteryBenchmarkReporter:
    """Posts battery metrics to external benchmark services."""

    def __init__(self, hass, config: dict) -> None:
        self._hass       = hass
        self._session    = None
        self._api_key    = config.get("mijnbatterij_api_key", "")
        self._enabled    = bool(self._api_key)
        self._last_post  = 0.0
        self._post_errors: int = 0
        self._total_posts: int = 0

    async def async_setup(self) -> None:
        if not self._enabled:
            return
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)
        _LOGGER.debug("BatteryBenchmarkReporter: enabled, api_key configured")

    async def async_report(
        self,
        battery_soc_pct:      float,
        battery_power_w:      float,
        charged_today_kwh:    float,
        discharged_today_kwh: float,
        solar_today_kwh:      float,
        battery_result_eur:   float = 0.0,
        total_cycles:         int   = 0,
    ) -> None:
        """Post battery data to all configured benchmark services."""
        if not self._enabled:
            return
        now = time.time()
        if now - self._last_post < POST_INTERVAL_S:
            return
        await self._post_mijnbatterij(
            battery_soc_pct, battery_power_w,
            charged_today_kwh, discharged_today_kwh,
            solar_today_kwh, battery_result_eur, total_cycles,
        )
        self._last_post = now

    async def _post_mijnbatterij(
        self,
        soc_pct:    float,
        power_w:    float,
        charged:    float,
        discharged: float,
        solar:      float,
        result_eur: float,
        cycles:     int,
    ) -> None:
        if not self._session:
            return
        payload = {
            "api_key":            self._api_key,
            "batteryResult":      round(result_eur, 2),
            "batteryCharge":      round(soc_pct, 1),
            "batteryPower":       round(power_w, 0),
            "chargedToday":       round(charged, 3),
            "dischargedToday":    round(discharged, 3),
            "solarResult":        round(solar, 3),
            "totalBatteryCycles": cycles,
        }
        try:
            async with self._session.post(MIJNBATTERIJ_URL, json=payload, timeout=10) as r:
                if r.status in (200, 201):
                    self._total_posts += 1
                    self._post_errors  = 0
                else:
                    self._post_errors += 1
                    _LOGGER.warning("BatteryBenchmarkReporter: HTTP %s from Mijnbatterij", r.status)
        except Exception as exc:
            self._post_errors += 1
            _LOGGER.warning("BatteryBenchmarkReporter: post error (%s)", exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> dict:
        return {
            "enabled":     self._enabled,
            "total_posts": self._total_posts,
            "post_errors": self._post_errors,
        }

    def get_status(self) -> dict:
        return self.status

    async def async_maybe_post(
        self,
        soc_pct:         float = 0.0,
        battery_w:       float = 0.0,
        charged_kwh:     float = 0.0,
        discharged_kwh:  float = 0.0,
        pv_today_kwh:    float = 0.0,
    ) -> None:
        """Coordinator-facing wrapper — maps flat kwargs to async_report."""
        await self.async_report(
            battery_soc_pct      = soc_pct,
            battery_power_w      = battery_w,
            charged_today_kwh    = charged_kwh,
            discharged_today_kwh = discharged_kwh,
            solar_today_kwh      = pv_today_kwh,
        )


# Backwards-compatible alias
MijnbatterijReporter = BatteryBenchmarkReporter


class MijnbatterijScoreFetcher:
    """Fetches user ranking and score from Mijnbatterij.nl."""

    SCORE_URL      = "https://api.mijnbatterij.nl/api/user/stats"
    FETCH_INTERVAL = 3600  # once per hour

    def __init__(self, hass, api_key: str) -> None:
        self._hass       = hass
        self._api_key    = api_key
        self._session    = None
        self._last_fetch = 0.0
        self._cached:    dict = {}

    async def async_setup(self) -> None:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)

    async def async_fetch(self) -> dict:
        """Fetch score and ranking from Mijnbatterij.nl."""
        now = time.time()
        if now - self._last_fetch < self.FETCH_INTERVAL:
            return self._cached
        if not self._session:
            return {}
        try:
            async with self._session.get(
                self.SCORE_URL,
                headers={"X-API-Key": self._api_key, "Accept": "application/json"},
                timeout=10,
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    self._cached = {
                        "rank":         data.get("rank"),
                        "score":        data.get("score"),
                        "total_users":  data.get("totalUsers"),
                        "percentile":   data.get("percentile"),
                        "today_result": data.get("todayResult"),
                        "month_result": data.get("monthResult"),
                        "profile_url":  data.get("profileUrl"),
                    }
                    self._last_fetch = now
        except Exception as e:
            _LOGGER.debug("Mijnbatterij score fetch error: %s", e)
        return self._cached
