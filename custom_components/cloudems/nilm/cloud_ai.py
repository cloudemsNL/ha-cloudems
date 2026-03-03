"""Cloud AI NILM classifier for CloudEMS - calls cloudems.eu API."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
import asyncio
from typing import List, Dict, Optional
import aiohttp

from ..const import CLOUD_API_BASE, CLOUD_NILM_ENDPOINT

_LOGGER = logging.getLogger(__name__)


class CloudAIClassifier:
    """Classifies power events via CloudEMS cloud API."""

    def __init__(self, api_key: Optional[str], session: aiohttp.ClientSession):
        self._api_key = api_key
        self._session = session
        self._available = bool(api_key)
        self._last_error: Optional[str] = None
        self._call_count = 0

    async def classify(self, delta_power: float, rise_time: float,
                        context: Dict) -> List[Dict]:
        """Classify event via cloud API. Returns list of matches."""
        if not self._api_key:
            return []

        try:
            payload = {
                "delta_power": delta_power,
                "rise_time": rise_time,
                "context": context,
                "source": "ha_cloudems_light",
            }
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "X-CloudEMS-Version": "1.0",
            }
            url = f"{CLOUD_API_BASE}{CLOUD_NILM_ENDPOINT}"
            async with self._session.post(url, json=payload, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._call_count += 1
                    self._available = True
                    return [
                        {**m, "source": "cloud_ai"}
                        for m in data.get("matches", [])
                    ]
                elif resp.status == 402:
                    _LOGGER.warning("CloudEMS API: Upgrade to premium at cloudems.eu")
                    self._available = False
                    return []
                else:
                    _LOGGER.warning("CloudEMS API error: %d", resp.status)
                    return []
        except asyncio.TimeoutError:
            _LOGGER.debug("CloudEMS API timeout, using local fallback")
            return []
        except Exception as e:
            self._last_error = str(e)
            _LOGGER.debug("CloudEMS API error: %s", e)
            return []

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def call_count(self) -> int:
        return self._call_count
