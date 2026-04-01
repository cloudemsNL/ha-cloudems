# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — AdaptiveHome Data Uploader (v1.0.0).

Uploadt PV-dip events en weerobservaties naar AdaptiveHome cloud
zodra een bridge token beschikbaar is.

Werkt volledig opt-in: upload alleen als:
  1. Gebruiker heeft data-deling ingeschakeld (config: share_observations=True)
  2. Bridge token beschikbaar in coordinator config
  3. Events staan als upload_pending in de detector/collector

Rate limiting: max 1 upload per 10 minuten per type.
Backoff: bij fout, wacht 30/60/300 min voor retry.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

# AdaptiveHome endpoints
AH_BASE_URL      = "https://api.adaptivehome.nl"
DIP_ENDPOINT     = f"{AH_BASE_URL}/api/v1/observations/pv_dip_events"
WEATHER_ENDPOINT    = f"{AH_BASE_URL}/api/v1/observations/weather"
LIGHTNING_ENDPOINT    = f"{AH_BASE_URL}/api/v1/observations/lightning"
VOLTAGE_ENDPOINT      = f"{AH_BASE_URL}/api/v1/observations/voltage"
THERMAL_ENDPOINT      = f"{AH_BASE_URL}/api/v1/observations/thermal_leak"
NEIGHBOURHOOD_ENDPOINT = f"{AH_BASE_URL}/api/v1/observations/neighbourhood"

UPLOAD_INTERVAL_S  = 600   # min 10 min tussen uploads
RETRY_BACKOFF_S    = [1800, 3600, 18000]  # 30min, 1u, 5u


class AdaptiveHomeUploader:
    """Beheert uploads naar AdaptiveHome cloud.

    Gebruik in coordinator:
        uploader = AdaptiveHomeUploader(session, bridge_token)
        await uploader.maybe_upload_dips(pv_dip_detector)
        await uploader.maybe_upload_weather(weather_observer)
    """

    def __init__(
        self,
        session:      aiohttp.ClientSession,
        bridge_token: str,
        enabled:      bool = False,
    ) -> None:
        self._session      = session
        self._token        = bridge_token
        self._enabled      = enabled

        self._last_dip_upload:     float = 0.0
        self._last_weather_upload: float = 0.0
        self._dip_errors:          int   = 0
        self._weather_errors:      int   = 0

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._token)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    async def maybe_upload_dips(self, pv_dip_detector) -> bool:
        """Upload PV-dip events als er pending zijn. Geeft True bij succes."""
        if not self.enabled:
            return False
        if time.time() - self._last_dip_upload < self._backoff(self._dip_errors, UPLOAD_INTERVAL_S):
            return False

        batch = pv_dip_detector.get_upload_batch()
        if not batch:
            return True  # Niets te uploaden — ok

        success = await self._post(DIP_ENDPOINT, batch)
        if success:
            self._last_dip_upload = time.time()
            self._dip_errors = 0
            _LOGGER.info("AdaptiveHome: %d pv_dip_events geüpload", len(batch))
        else:
            self._dip_errors += 1
            # Markeer events als niet geüpload zodat ze opnieuw geprobeerd worden
            for ev in batch:
                ev["uploaded"] = False
            _LOGGER.warning(
                "AdaptiveHome: dip upload mislukt (poging %d)", self._dip_errors)
        return success

    async def maybe_upload_weather(self, weather_observer) -> bool:
        """Upload weerobservaties als er pending zijn."""
        if not self.enabled:
            return False
        if time.time() - self._last_weather_upload < self._backoff(self._weather_errors, UPLOAD_INTERVAL_S):
            return False

        batch = weather_observer.get_upload_batch()
        if not batch:
            return True

        success = await self._post(WEATHER_ENDPOINT, batch)
        if success:
            self._last_weather_upload = time.time()
            self._weather_errors = 0
            _LOGGER.info("AdaptiveHome: %d weather_observations geüpload", len(batch))
        else:
            self._weather_errors += 1
            _LOGGER.warning(
                "AdaptiveHome: weather upload mislukt (poging %d)", self._weather_errors)
        return success

    async def maybe_upload_neighbourhood(self, watch) -> bool:
        if not self.enabled: return False
        batch = watch.get_upload_batch()
        if not batch: return True
        success = await self._post(NEIGHBOURHOOD_ENDPOINT, batch)
        if success: _LOGGER.info("AdaptiveHome: %d neighbourhood_events geüpload", len(batch))
        return success

    async def maybe_upload_voltage(self, voltage_monitor) -> bool:
        if not self.enabled: return False
        batch = voltage_monitor.get_upload_batch()
        if not batch: return True
        success = await self._post(VOLTAGE_ENDPOINT, batch)
        if success: _LOGGER.info("AdaptiveHome: %d voltage_events geüpload", len(batch))
        return success

    async def maybe_upload_thermal_leak(self, thermal_leak) -> bool:
        if not self.enabled: return False
        batch = thermal_leak.get_upload_batch()
        if not batch: return True
        success = await self._post(THERMAL_ENDPOINT, batch)
        if success: _LOGGER.info("AdaptiveHome: %d thermal_leak_events geüpload", len(batch))
        return success

    async def maybe_upload_lightning(self, lightning_detector) -> bool:
        """Upload bliksemdetecties als er pending zijn."""
        if not self.enabled:
            return False
        batch = lightning_detector.get_upload_batch()
        if not batch:
            return True
        success = await self._post(LIGHTNING_ENDPOINT, batch)
        if success:
            _LOGGER.info("AdaptiveHome: %d lightning_events geüpload", len(batch))
        return success

    async def _post(self, url: str, data: list[dict]) -> bool:
        """POST batch naar AdaptiveHome. Geeft True bij HTTP 202."""
        try:
            async with self._session.post(
                url,
                json=data,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type":  "application/json",
                    "User-Agent":    "CloudEMS/5.5 (HA integration)",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 202:
                    return True
                body = await resp.text()
                _LOGGER.warning("AdaptiveHome upload: HTTP %d — %s", resp.status, body[:200])
                return False
        except aiohttp.ClientError as e:
            _LOGGER.warning("AdaptiveHome upload: verbindingsfout — %s", e)
            return False
        except Exception as e:
            _LOGGER.debug("AdaptiveHome upload: onverwachte fout — %s", e)
            return False

    def _backoff(self, errors: int, base_interval: float) -> float:
        """Exponentiële backoff bij fouten."""
        if errors == 0:
            return base_interval
        idx = min(errors - 1, len(RETRY_BACKOFF_S) - 1)
        return RETRY_BACKOFF_S[idx]

    def to_dict(self) -> dict:
        return {
            "enabled":              self.enabled,
            "last_dip_upload":      self._last_dip_upload,
            "last_weather_upload":  self._last_weather_upload,
            "dip_errors":           self._dip_errors,
            "weather_errors":       self._weather_errors,
        }
