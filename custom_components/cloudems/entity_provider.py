# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — EntityProvider Abstractie
======================================

Dit is de centrale abstractielaag die de CloudEMS engine
ontkoppelt van Home Assistant.

De coordinator gebruikt ALLEEN deze interface voor data ophalen
en commando's sturen. Het maakt niet uit of de data van HA,
Tuya, Google Nest, Tesla, Enphase of welk platform dan ook komt.

Nieuwe provider bouwen = 4 methoden implementeren:
    get_state()       — actuele waarde van een entiteit
    get_attribute()   — attribuut van een entiteit
    get_all_of_type() — alle entiteiten van een type (bijv. "climate")
    call_service()    — commando sturen (schakelaar, setpoint, etc.)

Beschikbare providers:
    HAEntityProvider        ← Home Assistant (productie nu)
    TuyaEntityProvider      ← Tuya / Smart Life
    HomeyEntityProvider     ← Homey Pro + Cloud
    P1EntityProvider        ← HomeWizard / CloudEMS dongle
    GoogleNestProvider      ← Google Nest thermostaat / Protect
    TeslaEntityProvider     ← Tesla Powerwall + Model S/3/X/Y
    VictronEntityProvider   ← Victron Energy (MQTT/Modbus)
    EnphaseEntityProvider   ← Enphase Envoy
    SolarEdgeEntityProvider ← SolarEdge cloud API
    OctopusEntityProvider   ← Octopus Energy (UK/EU)
    GoodWeEntityProvider    ← GoodWe omvormer cloud
    ShellyEntityProvider    ← Shelly slimme relais (lokaal REST)
    ZwaveEntityProvider     ← Z-Wave via MQTT
    ZigbeeEntityProvider    ← Zigbee2MQTT
    ModbusEntityProvider    ← Generieke Modbus (omvormers, meters)
    MqttEntityProvider      ← Generieke MQTT topics
    MockEntityProvider      ← Testing / ontwikkeling
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cloudems.entity_provider")


# ── State representatie ───────────────────────────────────────────────────────

@dataclass
class EntityState:
    """
    Universele state representatie — platform onafhankelijk.
    Vervangt HA's State object in de engine.
    """
    entity_id:  str
    state:      str                          # altijd string, net als HA
    attributes: Dict[str, Any] = field(default_factory=dict)
    unit:       Optional[str]  = None        # "W", "kWh", "°C", "%", etc.
    available:  bool           = True

    # ── Handige conversie properties ────────────────────────────────────────

    @property
    def as_float(self) -> Optional[float]:
        """State als float. None als niet beschikbaar of niet numeriek."""
        if not self.available or self.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(self.state)
        except (ValueError, TypeError):
            return None

    @property
    def as_bool(self) -> Optional[bool]:
        """State als bool. None als niet beschikbaar."""
        if not self.available:
            return None
        return self.state.lower() in ("on", "true", "1", "yes", "open", "active")

    def attr(self, key: str, default: Any = None) -> Any:
        """Haal attribuut op met fallback."""
        return self.attributes.get(key, default)

    def __repr__(self) -> str:
        return f"<EntityState {self.entity_id}={self.state} ({self.unit or '?'})>"


# ── Abstracte provider ────────────────────────────────────────────────────────

class EntityProvider(ABC):
    """
    Abstracte basisklasse voor alle CloudEMS entity providers.

    Elke provider is verantwoordelijk voor:
    1. Data ophalen van het externe platform
    2. Normaliseren naar EntityState
    3. Commando's doorsturen naar het platform

    De engine (coordinator) weet nooit welk platform er achter zit.
    """

    # Platform naam — overschrijf in subklasse
    platform: str = "abstract"

    # Beschrijving voor de UI
    display_name: str = "Onbekend platform"
    icon: str = "mdi:help-circle"

    def __init__(self) -> None:
        self._cache: Dict[str, EntityState] = {}

    # ── Verplichte methoden ───────────────────────────────────────────────────

    @abstractmethod
    async def get_state(self, entity_id: str) -> Optional[EntityState]:
        """
        Haal actuele state op voor één entity.

        Args:
            entity_id: Platform-specifieke identifier.
                       In HA: "sensor.solar_power"
                       In Tuya: "device_abc123:power"
                       In MQTT: "cloudems/p1/power"

        Returns:
            EntityState of None als niet gevonden/beschikbaar.
        """
        ...

    @abstractmethod
    async def get_all_of_domain(self, domain: str) -> List[EntityState]:
        """
        Haal alle entities op van een bepaald type/domein.

        Args:
            domain: bijv. "climate", "light", "switch", "sensor"

        Returns:
            Lijst van EntityState objecten.
        """
        ...

    @abstractmethod
    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Stuur een commando naar het platform.

        Voorbeelden:
            call_service("switch", "turn_on", "switch.boiler")
            call_service("climate", "set_temperature", "climate.woonkamer", {"temperature": 20.5})
            call_service("number", "set_value", "number.charge_power", {"value": 2500})

        Returns:
            True bij succes, False bij fout.
        """
        ...

    # ── Optionele methoden (hebben defaults) ──────────────────────────────────

    async def get_attribute(
        self,
        entity_id: str,
        attribute: str,
        default: Any = None,
    ) -> Any:
        """Haal één attribuut op van een entity."""
        state = await self.get_state(entity_id)
        if state is None:
            return default
        return state.attr(attribute, default)

    async def get_float(self, entity_id: str) -> Optional[float]:
        """Shorthand: state als float."""
        state = await self.get_state(entity_id)
        return state.as_float if state else None

    async def get_bool(self, entity_id: str) -> Optional[bool]:
        """Shorthand: state als bool."""
        state = await self.get_state(entity_id)
        return state.as_bool if state else None

    async def is_available(self, entity_id: str) -> bool:
        """Check of een entity beschikbaar is."""
        state = await self.get_state(entity_id)
        return state is not None and state.available

    async def setup(self) -> bool:
        """
        Initialiseer de provider (authenticatie, verbinding, etc.).
        Wordt aangeroepen bij coordinator setup.
        Geeft True bij succes.
        """
        return True

    async def teardown(self) -> None:
        """Cleanup bij afsluiten."""
        pass

    async def health_check(self) -> Tuple[bool, str]:
        """
        Health check voor monitoring.
        Returns: (ok: bool, message: str)
        """
        return True, f"{self.platform} OK"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.platform}>"


# ── Provider registry ─────────────────────────────────────────────────────────

_PROVIDER_REGISTRY: Dict[str, type] = {}


def register_provider(platform: str):
    """
    Decorator om een provider te registreren.

    Gebruik:
        @register_provider("google_nest")
        class GoogleNestProvider(EntityProvider):
            ...
    """
    def decorator(cls: type) -> type:
        _PROVIDER_REGISTRY[platform] = cls
        logger.debug("Provider geregistreerd: %s → %s", platform, cls.__name__)
        return cls
    return decorator


def get_provider_class(platform: str) -> Optional[type]:
    """Haal provider klasse op via platform naam."""
    return _PROVIDER_REGISTRY.get(platform)


def list_providers() -> List[str]:
    """Alle geregistreerde provider platforms."""
    return sorted(_PROVIDER_REGISTRY.keys())


def create_provider(platform: str, **kwargs) -> Optional[EntityProvider]:
    """
    Factory: maak een provider aan via platform naam.

    Gebruik:
        provider = create_provider("tuya", access_id="...", access_secret="...")
        provider = create_provider("ha")     # automatisch gevuld door HA integratie
        provider = create_provider("mock")   # voor tests
    """
    cls = _PROVIDER_REGISTRY.get(platform)
    if cls is None:
        logger.error("Onbekend provider platform: '%s'. Beschikbaar: %s", platform, list_providers())
        return None
    try:
        return cls(**kwargs)
    except Exception as exc:
        logger.error("Provider aanmaken mislukt (%s): %s", platform, exc)
        return None
