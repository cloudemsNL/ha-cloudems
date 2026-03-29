"""
CloudEMS Pro License Manager — v1.0.0

Verantwoordelijk voor:
- Validatie van licentiesleutel via cloudems.eu
- 24u caching in HA Storage
- Geen enkele feature wordt hier vergrendeld — dat komt later

Gebruik:
    mgr = ProLicenseManager(hass, key)
    await mgr.async_setup()
    status = mgr.status   # dict: tier, valid, expires, ...
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import PRO_TIER_FREE, PRO_TIER_PRO, PRO_TIER_LIFETIME, PRO_VALIDATE_URL, PRO_CACHE_TTL_H

_LOGGER = logging.getLogger(__name__)

STORE_KEY = "cloudems_pro_license_v1"


class ProLicenseManager:
    """Beheert Pro-licentiestatus voor één CloudEMS installatie."""

    def __init__(self, hass: HomeAssistant, license_key: str | None) -> None:
        self._hass        = hass
        self._key         = (license_key or "").strip()
        self._store       = Store(hass, 1, STORE_KEY)
        self._status: dict[str, Any] = {
            "tier":        PRO_TIER_FREE,
            "valid":       False,
            "expires":     None,
            "last_check":  None,
            "error":       None,
            "key_prefix":  self._key_prefix(),
        }

    def _key_prefix(self) -> str:
        if not self._key:
            return ""
        return self._key[:8] + "…"

    def _key_hash(self) -> str:
        return hashlib.sha256(self._key.encode()).hexdigest() if self._key else ""

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    @property
    def tier(self) -> str:
        return self._status["tier"]

    @property
    def is_pro(self) -> bool:
        return self._status["valid"] and self._status["tier"] in (PRO_TIER_PRO, PRO_TIER_LIFETIME)

    async def async_setup(self) -> None:
        """Laad gecachte status, valideer opnieuw als cache verlopen."""
        if not self._key:
            return

        cached = await self._store.async_load()
        if cached and self._cache_fresh(cached):
            self._status.update(cached)
            _LOGGER.debug("CloudEMS Pro: cache geladen (tier=%s)", self._status["tier"])
            return

        await self._validate()

    async def async_revalidate(self) -> dict[str, Any]:
        """Forceer een nieuwe validatie (bijv. na configuratiewijziging)."""
        await self._validate()
        return self.status

    async def _validate(self) -> None:
        if not self._key:
            self._status.update({"tier": PRO_TIER_FREE, "valid": False, "error": None})
            return

        try:
            session  = async_get_clientsession(self._hass)
            payload  = {"key_hash": self._key_hash()}
            async with session.post(
                PRO_VALIDATE_URL,
                json=payload,
                timeout=10,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._status.update({
                        "tier":       data.get("tier", PRO_TIER_FREE),
                        "valid":      bool(data.get("valid", False)),
                        "expires":    data.get("expires"),
                        "last_check": time.time(),
                        "error":      None,
                        "key_prefix": self._key_prefix(),
                    })
                    await self._store.async_save(self._status)
                    _LOGGER.info(
                        "CloudEMS Pro: validatie OK — tier=%s, expires=%s",
                        self._status["tier"], self._status["expires"],
                    )
                else:
                    self._status["error"] = f"HTTP {resp.status}"
                    _LOGGER.warning("CloudEMS Pro: validatie mislukt — HTTP %s", resp.status)
        except Exception as exc:
            self._status["error"] = str(exc)
            _LOGGER.debug("CloudEMS Pro: validatie fout — %s", exc)

    def _cache_fresh(self, cached: dict) -> bool:
        ts = cached.get("last_check") or 0
        return (time.time() - ts) < PRO_CACHE_TTL_H * 3600
