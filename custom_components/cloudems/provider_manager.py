# -*- coding: utf-8 -*-
"""
CloudEMS Provider Manager  v1.0.0
===================================
Centraliseert alle externe provider-instanties.
Wordt aangemaakt door de coordinator en biedt één uniforme interface.

Gebruik in coordinator:
    mgr = ProviderManager(hass, config)
    await mgr.async_setup()
    data = await mgr.async_poll_all()   # roep aan in coordinator update loop
    devices = mgr.get_all_devices()

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .providers import create_provider, get_all_providers
from .providers.base import CloudEMSProvider, ProviderDevice, ProviderStatus

_LOGGER = logging.getLogger(__name__)

# Config-keys voor het opslaan van provider-credentials
CONF_PROVIDERS = "external_providers"   # lijst van {"type": "tesla", "credentials": {...}}


class ProviderManager:
    """
    Beheert alle externe provider-instanties voor CloudEMS.

    Laadt providers op basis van de gebruikersconfiguratie,
    houdt de poll-resultaten bij en biedt een uniforme interface
    voor de rest van de coordinator.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass       = hass
        self._config     = config
        self._providers: Dict[str, CloudEMSProvider] = {}   # key = "type:index"
        self._last_data: Dict[str, Any] = {}
        self._ok        = False

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self) -> bool:
        """Initialiseer alle geconfigureerde providers."""
        provider_configs = self._config.get(CONF_PROVIDERS, [])
        if not provider_configs:
            _LOGGER.debug("ProviderManager: geen externe providers geconfigureerd")
            return True

        for i, pc in enumerate(provider_configs):
            ptype = pc.get("type","").lower()
            creds = pc.get("credentials", {})
            label = pc.get("label", ptype)

            if not ptype:
                continue

            key = f"{ptype}:{i}"
            try:
                provider = create_provider(ptype, self._hass, creds)
                if provider is None:
                    _LOGGER.warning("ProviderManager: onbekend provider type '%s'", ptype)
                    continue

                ok = await provider.async_setup()
                if ok:
                    self._providers[key] = provider
                    _LOGGER.info("ProviderManager: provider '%s' (%s) actief", label, ptype)
                else:
                    _LOGGER.warning("ProviderManager: provider '%s' setup mislukt: %s",
                                    label, provider._last_error)
            except Exception as exc:
                _LOGGER.error("ProviderManager: provider '%s' exception: %s", ptype, exc)

        self._ok = True
        _LOGGER.info("ProviderManager: %d van %d providers actief",
                     len(self._providers), len(provider_configs))
        return True

    # ── Poll ──────────────────────────────────────────────────────────────────

    async def async_poll_all(self) -> Dict[str, Any]:
        """
        Prik alle actieve providers. Roep aan vanuit coordinator update loop.
        Returns gecombineerde data dict gegroepeerd per categorie.
        """
        result: Dict[str, Any] = {
            "inverters":   {},
            "ev":          {},
            "appliances":  {},
            "energy":      {},
            "heating":     {},
        }

        for key, provider in list(self._providers.items()):
            try:
                data = await provider.async_poll()
                category = getattr(provider, "CATEGORY", "generic")
                bucket   = result.get(category, {})
                # Prefix device-ids met provider key om botsingen te voorkomen
                for device_id, device_data in data.items():
                    bucket[f"{key}:{device_id}"] = {
                        **device_data,
                        "_provider": provider.PROVIDER_ID,
                        "_provider_key": key,
                    }
                result[category] = bucket
            except Exception as exc:
                _LOGGER.warning("ProviderManager: poll '%s' mislukt: %s", key, exc)

        self._last_data = result
        return result

    # ── Devices ───────────────────────────────────────────────────────────────

    def get_all_devices(self) -> List[ProviderDevice]:
        """Alle gevonden devices van alle actieve providers."""
        devices = []
        for provider in self._providers.values():
            # Gebruik gecachede device-lijst als beschikbaar
            for dev in provider._cache.get("_devices", []):
                if isinstance(dev, ProviderDevice):
                    devices.append(dev)
        return devices

    # ── Commands ──────────────────────────────────────────────────────────────

    async def async_send_command(
        self,
        provider_key: str,
        device_id: str,
        command: str,
        params: Optional[dict] = None,
    ) -> bool:
        """Stuur een commando naar een specifieke provider."""
        provider = self._providers.get(provider_key)
        if not provider:
            _LOGGER.warning("ProviderManager: provider '%s' niet gevonden", provider_key)
            return False
        try:
            return await provider.async_send_command(device_id, command, params)
        except Exception as exc:
            _LOGGER.error("ProviderManager: commando '%s' mislukt: %s", command, exc)
            return False

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> List[dict]:
        """Status van alle providers — voor dashboard en diagnostics."""
        return [
            {**provider.get_status().to_dict(), "_key": key}
            for key, provider in self._providers.items()
        ]

    def get_providers_by_category(self, category: str) -> List[CloudEMSProvider]:
        return [p for p in self._providers.values()
                if getattr(p, "CATEGORY", "") == category]

    @property
    def active_count(self) -> int:
        return len(self._providers)

    # ── Teardown ──────────────────────────────────────────────────────────────

    async def async_teardown(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.async_teardown()
            except Exception:
                pass
        self._providers.clear()

    def __repr__(self) -> str:
        return f"<ProviderManager providers={list(self._providers.keys())}>"


# ── Sensor data extractors ────────────────────────────────────────────────────
# Hulpfuncties die de coordinator gebruikt om provider-data om te zetten
# naar sensor-attributen

def extract_ev_summary(poll_data: dict) -> dict:
    """
    Geef een samenvatting van alle EV-data voor de coordinator.
    Gebruikt door: sensor.cloudems_ev_status (toekomstige sensor)
    """
    ev_data = poll_data.get("ev", {})
    vehicles = []
    total_charging_w = 0.0
    any_plugged = False

    for key, data in ev_data.items():
        if data.get("soc_pct") is not None:
            vehicles.append({
                "key":          key,
                "provider":     data.get("_provider",""),
                "soc_pct":      data.get("soc_pct"),
                "range_km":     data.get("range_km"),
                "charging":     data.get("charging", False),
                "plugged_in":   data.get("plugged_in", False),
                "charge_power_w": data.get("charge_power_w"),
            })
            if data.get("charging"):
                total_charging_w += data.get("charge_power_w") or 0
            if data.get("plugged_in"):
                any_plugged = True

    return {
        "vehicles":          vehicles,
        "total_charging_w":  round(total_charging_w, 0),
        "any_plugged":       any_plugged,
        "count":             len(vehicles),
    }


def extract_appliance_summary(poll_data: dict) -> dict:
    """Samenvatting van actieve huishoudapparaten."""
    appl_data = poll_data.get("appliances", {})
    active = []
    total_remaining = 0

    for key, data in appl_data.items():
        state = data.get("state","")
        if state in ("running","5","programmed","3"):
            rem = data.get("remaining_minutes")
            active.append({
                "key":       key,
                "provider":  data.get("_provider",""),
                "state":     state,
                "program":   data.get("program",""),
                "remaining": rem,
            })
            if rem:
                total_remaining = max(total_remaining, rem)

    return {
        "active_appliances": active,
        "count_active":      len(active),
        "max_remaining_min": total_remaining,
    }


def extract_inverter_summary(poll_data: dict) -> dict:
    """Samenvatting van alle omvormer-data."""
    inv_data = poll_data.get("inverters", {})
    total_w  = 0.0
    sources  = []

    for key, data in inv_data.items():
        pw = data.get("power_w")
        if pw is not None:
            total_w += float(pw)
            sources.append({"key": key, "power_w": pw,
                            "provider": data.get("_provider","")})

    return {
        "total_power_w": round(total_w, 0),
        "sources":       sources,
        "count":         len(sources),
    }


def extract_energy_prices(poll_data: dict) -> dict:
    """Haal prijsdata op van energieleverancier providers."""
    energy_data = poll_data.get("energy", {})
    for key, data in energy_data.items():
        if data.get("current_price") is not None:
            return {
                "current_price":  data.get("current_price"),
                "today_prices":   data.get("today_prices", []),
                "tomorrow_prices":data.get("tomorrow_prices", []),
                "source":         data.get("source","provider"),
                "provider_key":   key,
            }
    return {}
