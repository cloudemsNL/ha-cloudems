# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — SMA Batterij Provider v1.0.0

Supports SMA Sunny Boy Storage / Sunny Tripower Storage
via the standaard HA SMA Solar integratie.

Entity patronen:
  sensor.sma_*_battery_charge_total      → SOC (%)
  sensor.sma_*_battery_power             → Vermogen (W, + laden / - ontladen)
  sensor.sma_*_battery_voltage           → Spanning (V)
  number.sma_*_battery_min_soc           → Min SOC limiet
"""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant

from .battery_provider import BatteryProvider, BatteryProviderState, BatteryProviderRegistry, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_SMA_PREFIXES  = ("sma_",)
_SOC_KEYWORDS  = ("battery_charge_total", "battery_soc", "battery_level")
_POWER_KEYWORDS = ("battery_power", "battery_charging_power")


class SMABatteryProvider(BatteryProvider):
    """SMA Sunny Boy/Tripower Storage batterij-provider."""

    PROVIDER_ID    = "sma_battery"
    PROVIDER_LABEL = "SMA Batterij"
    PROVIDER_ICON  = "mdi:battery-charging"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._soc_entity:   Optional[str] = None
        self._power_entity: Optional[str] = None

    async def async_detect(self) -> bool:
        for state in self._hass.states.async_all("sensor"):
            eid = state.entity_id.lower()
            if not any(p in eid for p in _SMA_PREFIXES):
                continue
            if any(k in eid for k in _SOC_KEYWORDS):
                self._soc_entity = state.entity_id
            if any(k in eid for k in _POWER_KEYWORDS):
                self._power_entity = state.entity_id

        detected = self._soc_entity is not None
        if detected:
            _LOGGER.info("SMABatteryProvider: gedetecteerd soc=%s power=%s",
                         self._soc_entity, self._power_entity)
        return detected

    def read_state(self) -> BatteryProviderState:
        soc_pct = power_w = None
        if self._soc_entity:
            s = self._hass.states.get(self._soc_entity)
            if s and s.state not in ("unavailable", "unknown"):
                try: soc_pct = float(s.state)
                except (ValueError, TypeError): pass
        if self._power_entity:
            s = self._hass.states.get(self._power_entity)
            if s and s.state not in ("unavailable", "unknown"):
                try: power_w = float(s.state)
                except (ValueError, TypeError): pass

        return BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc_pct,
            power_w        = power_w,
            is_charging    = (power_w or 0) > 10,
            is_discharging = (power_w or 0) < -10,
            active_mode    = "auto",
            available_modes= ["auto"],
            is_online      = soc_pct is not None,
        )

    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        # SMA biedt geen directe laadsturing via HA — alleen via Modbus (optioneel)
        _LOGGER.info("SMABatteryProvider: directe laadsturing niet beschikbaar via HA integratie")
        return False

    async def async_set_discharge(self, power_w: Optional[float] = None) -> bool:
        return False

    async def async_set_auto(self) -> bool:
        return True  # SMA always manages itself automatically

    def get_wizard_hint(self) -> ProviderWizardHint:
        return ProviderWizardHint(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            detected       = self.is_detected,
            enabled        = self.is_enabled,
            hint           = "SMA Battery detected. CloudEMS leest SOC en vermogen. Directe sturing vereist SMA Modbus configuratie.",
            setup_url      = "https://www.home-assistant.io/integrations/sma/",
        )


BatteryProviderRegistry.register_provider(SMABatteryProvider)
