# -*- coding: utf-8 -*-
"""
CloudEMS Battery Provider — v1.0.0

Generieke abstractie voor leverancier-gebonden batterij-integraties.
Elke leverancier implementeert BatteryProvider. De registry detecteert
welke providers aanwezig zijn en biedt wizard-hints en waarschuwingen.

Architectuur:
  BatteryProvider (abstract)
    └── ZonneplanProvider      (zonneplan_one integratie)
    └── TibberVoltProvider     (tibber integratie, toekomstig)
    └── EnecoProvider          (eneco, toekomstig)
    └── HomeWizardProvider     (generieke local API, toekomstig)
    └── ...

BatteryProviderRegistry
    └── detecteert alle providers
    └── geeft wizard_hints (voor config_flow)
    └── geeft waarschuwingen voor dashboard/notificaties

Gebruik in coordinator:
    registry = BatteryProviderRegistry(hass, config)
    await registry.async_setup()
    primary = registry.primary_provider   # eerste beschikbare
    if primary and primary.is_available:
        await primary.async_set_charge(power_w=2000)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Generieke batterijstatus — provider-onafhankelijk
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BatteryProviderState:
    """Genormaliseerde batterijstatus voor gebruik door CloudEMS coordinator."""
    provider_id:       str            # bijv. "zonneplan", "tibber_volt"
    provider_label:    str            # bijv. "Zonneplan Nexus"
    soc_pct:           Optional[float] = None   # 0-100
    power_w:           Optional[float] = None   # + laden, - ontladen
    is_charging:       bool           = False
    is_discharging:    bool           = False
    active_mode:       Optional[str]  = None   # provider-specifieke modusnaam
    available_modes:   list[str]      = field(default_factory=list)
    is_online:         bool           = True
    raw:               dict           = field(default_factory=dict)  # provider-specifiek

    def to_dict(self) -> dict:
        d = {
            "provider_id":    self.provider_id,
            "provider_label": self.provider_label,
            "soc_pct":        self.soc_pct,
            "power_w":        self.power_w,
            "is_charging":    self.is_charging,
            "is_discharging": self.is_discharging,
            "active_mode":    self.active_mode,
            "available_modes":self.available_modes,
            "is_online":      self.is_online,
        }
        # Voeg provider-specifieke velden toe vanuit raw{} die dashboard nodig heeft
        if self.raw:
            d["tariff_group"]          = self.raw.get("tariff_group")
            d["electricity_tariff_eur"]= self.raw.get("electricity_tariff_eur")
            d["forecast_tariff_groups"]= self.raw.get("forecast_tariff_groups", [])
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Wizard hint — wat moet de wizard aan de gebruiker vertonen?
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ProviderWizardHint:
    """Informatie die de config_flow wizard gebruikt om de gebruiker te begeleiden."""
    provider_id:    str
    provider_label: str
    detected:       bool     # integratie gevonden in HA
    configured:     bool     # CloudEMS heeft deze provider al ingesteld
    # Wat te tonen in de wizard
    title:          str      = ""
    description:    str      = ""
    icon:           str      = "mdi:battery"
    warning:        str      = ""   # bijv. "Batterij gevonden maar niet geconfigureerd"
    suggestion:     str      = ""   # bijv. "Wil je dit nu instellen?"
    # Configureerbare opties voor de wizard-stap
    config_fields:  list[dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Abstracte base class
# ─────────────────────────────────────────────────────────────────────────────
class BatteryProvider(ABC):
    """
    Abstracte basis voor alle leverancier-specifieke batterij-providers.

    Elke concrete subklasse implementeert:
      - PROVIDER_ID    (class constante, bijv. "zonneplan")
      - PROVIDER_LABEL (bijv. "Zonneplan Nexus")
      - async_detect() → bool
      - read_state()   → BatteryProviderState
      - async_set_charge(power_w)
      - async_set_discharge(power_w)
      - async_set_auto()
      - get_wizard_hint() → ProviderWizardHint
    """

    PROVIDER_ID:    str = "unknown"
    PROVIDER_LABEL: str = "Onbekend"
    PROVIDER_ICON:  str = "mdi:battery"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._detected:  Optional[bool] = None
        self._enabled:   bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Setup: detecteer provider en laad eventuele persistente state."""
        self._enabled = self._config.get(f"{self.PROVIDER_ID}_enabled", False)
        self._detected = await self.async_detect()

    async def async_maybe_restore(self) -> None:
        """Aanroepen elke update-cyclus voor automatisch herstel van overrides."""
        pass  # override indien relevant

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_detected(self) -> bool:
        """True als de integratie in HA aanwezig is."""
        return bool(self._detected)

    @property
    def is_available(self) -> bool:
        """True als gevonden EN door gebruiker ingeschakeld."""
        return bool(self._detected and self._enabled)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def update_config(self, config: dict) -> None:
        self._config  = config
        self._enabled = config.get(f"{self.PROVIDER_ID}_enabled", self._enabled)

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def async_detect(self) -> bool:
        """Detecteer of deze provider aanwezig is in HA."""
        ...

    @abstractmethod
    def read_state(self) -> BatteryProviderState:
        """Lees actuele batterijstatus (poll, geen await)."""
        ...

    @abstractmethod
    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        """Laat batterij laden."""
        ...

    @abstractmethod
    async def async_set_discharge(self, power_w: Optional[float] = None) -> bool:
        """Laat batterij ontladen."""
        ...

    @abstractmethod
    async def async_set_auto(self) -> bool:
        """Herstel automatisch (leverancier) beheer."""
        ...

    @abstractmethod
    def get_wizard_hint(self) -> ProviderWizardHint:
        """Geeft wizard-informatie voor config_flow."""
        ...

    # ── Optionele methoden (override indien beschikbaar) ─────────────────────

    async def async_set_mode(self, mode: str, **kwargs) -> bool:
        """Stel een provider-specifieke modus in (optioneel)."""
        _LOGGER.debug("%s: set_mode niet geïmplementeerd (mode=%s)", self.PROVIDER_ID, mode)
        return False

    def get_available_modes(self) -> list[dict]:
        """Geeft beschikbare modi terug voor de UI (optioneel)."""
        return []

    def get_info(self) -> dict:
        """Uitgebreide info voor sensor-attributen en dashboard."""
        return {
            "provider_id":    self.PROVIDER_ID,
            "provider_label": self.PROVIDER_LABEL,
            "detected":       self.is_detected,
            "enabled":        self.is_enabled,
            "available":      self.is_available,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Registry — detecteert en beheert alle providers
# ─────────────────────────────────────────────────────────────────────────────
class BatteryProviderRegistry:
    """
    Detecteert leverancier-specifieke batterij-integraties en biedt:
      - providers         : alle geregistreerde providers
      - detected_providers: alleen gevonden providers
      - primary_provider  : eerste beschikbare (enabled) provider
      - wizard_hints      : hints voor config_flow wizard
      - notifications     : waarschuwingen voor dashboard

    Wizard-detectie logica:
      1. Scan entity registry voor bekende integratie-domeinen
      2. Als gevonden maar niet geconfigureerd → waarschuwing + setup-suggestie
      3. Als geconfigureerd → toon status in dashboard
    """

    # Geregistreerde provider-klassen (uitbreidbaar)
    _PROVIDER_CLASSES: list[type[BatteryProvider]] = []

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass      = hass
        self._config    = config
        self._providers: list[BatteryProvider] = []

    @classmethod
    def register_provider(cls, provider_class: type[BatteryProvider]) -> None:
        """Registreer een nieuwe provider-klasse (aanroepen bij module import)."""
        if provider_class not in cls._PROVIDER_CLASSES:
            cls._PROVIDER_CLASSES.append(provider_class)

    async def async_setup(self) -> None:
        """Initialiseer alle geregistreerde providers."""
        self._providers = []
        for cls in self._PROVIDER_CLASSES:
            try:
                provider = cls(self._hass, self._config)
                await provider.async_setup()
                self._providers.append(provider)
                _LOGGER.info(
                    "BatteryProviderRegistry: %s detected=%s enabled=%s",
                    cls.PROVIDER_ID, provider.is_detected, provider.is_enabled,
                )
            except Exception as exc:
                _LOGGER.error("BatteryProviderRegistry: fout bij %s: %s", cls.PROVIDER_ID, exc)

    def update_config(self, config: dict) -> None:
        self._config = config
        for p in self._providers:
            p.update_config(config)

    async def async_maybe_restore(self) -> None:
        for p in self._providers:
            await p.async_maybe_restore()

    # ── Provider toegang ──────────────────────────────────────────────────────

    @property
    def providers(self) -> list[BatteryProvider]:
        return list(self._providers)

    @property
    def detected_providers(self) -> list[BatteryProvider]:
        return [p for p in self._providers if p.is_detected]

    @property
    def available_providers(self) -> list[BatteryProvider]:
        return [p for p in self._providers if p.is_available]

    @property
    def primary_provider(self) -> Optional[BatteryProvider]:
        """Eerste beschikbare (enabled) provider."""
        avail = self.available_providers
        return avail[0] if avail else None

    def get_provider(self, provider_id: str) -> Optional[BatteryProvider]:
        for p in self._providers:
            if p.PROVIDER_ID == provider_id:
                return p
        return None

    # ── Wizard hints & notificaties ───────────────────────────────────────────

    def get_wizard_hints(self) -> list[ProviderWizardHint]:
        """
        Geeft wizard-hints voor alle GEDETECTEERDE providers.
        Alleen providers die aanwezig zijn in HA maar nog niet geconfigureerd
        worden als actieve hint (waarschuwing) teruggegeven.
        """
        return [p.get_wizard_hint() for p in self.detected_providers]

    def get_setup_warnings(self) -> list[dict]:
        """
        Waarschuwingen voor het dashboard:
        - Provider gevonden maar niet geconfigureerd
        - Provider geconfigureerd maar offline
        - Provider-specifieke waarschuwingen (bv. disabled entity, ontbrekende tarief-sensor)
        """
        warnings = []
        for p in self.detected_providers:
            if not p.is_enabled:
                warnings.append({
                    "type":     "provider_not_configured",
                    "severity": "warning",
                    "provider": p.PROVIDER_ID,
                    "message":  f"{p.PROVIDER_LABEL} gedetecteerd maar niet geconfigureerd",
                    "action":   "open_options",
                })
            elif p.is_available:
                state = p.read_state()
                if not state.is_online:
                    warnings.append({
                        "type":     "provider_offline",
                        "severity": "error",
                        "provider": p.PROVIDER_ID,
                        "message":  f"{p.PROVIDER_LABEL} geconfigureerd maar offline",
                        "action":   "check_integration",
                    })
            # Provider-specifieke extra waarschuwingen (override in subklasse)
            if hasattr(p, "get_setup_warnings"):
                try:
                    warnings.extend(p.get_setup_warnings())
                except Exception:
                    pass
        return warnings

    def get_info(self) -> dict:
        """Overzicht voor sensor-attributen en dashboard."""
        return {
            "providers":          [p.get_info() for p in self._providers],
            "detected_count":     len(self.detected_providers),
            "available_count":    len(self.available_providers),
            "primary":            self.primary_provider.PROVIDER_ID if self.primary_provider else None,
            "setup_warnings":     self.get_setup_warnings(),
        }
