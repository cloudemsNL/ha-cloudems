# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Victron Energy Battery Provider v1.0.0

Supports Victron Cerbo GX / Venus OS via the HA Victron Energy integratie
(HACS: victronenergy/hacs-victron of standaard via MQTT/Modbus GX).

Detection based on bekende entity-ID patronen:
  sensor.victron_*_soc            → State of Charge
  sensor.victron_*_battery_power  → Laad/ontlaadvermogen (W)
  sensor.ve_bus_*                 → VE.Bus inverter/charger
  number.victron_*_max_charge_*   → Laadlimiet (optioneel)

Control via HA services (indien beschikbaar) of via number/select entiteiten.
"""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant

from .battery_provider import BatteryProvider, BatteryProviderState, BatteryProviderRegistry, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

# Known entity-ID fragmenten voor detectie
_SOC_PATTERNS     = ("victron_", "ve_bus_", "vebus_", "multiplus_", "quattro_")
_SOC_KEYWORDS     = ("_soc", "_state_of_charge", "_battery_soc")
_POWER_KEYWORDS   = ("_battery_power", "_battery_current_power", "_dc_power")
_CHARGE_SWITCH    = ("switch.victron_", "switch.ve_bus_", "switch.multiplus_")


class VictronProvider(BatteryProvider):
    """Victron Energy Cerbo GX / Venus OS batterij-provider."""

    PROVIDER_ID    = "victron"
    PROVIDER_LABEL = "Victron Energy"
    PROVIDER_ICON  = "mdi:battery-charging"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._soc_entity:   Optional[str] = None
        self._power_entity: Optional[str] = None

    async def async_detect(self) -> bool:
        """Detecteer Victron entiteiten in HA."""
        all_states = self._hass.states.async_all()
        soc_found   = False
        power_found = False

        for state in all_states:
            eid = state.entity_id.lower()
            # Controleer op bekende Victron patronen
            has_prefix = any(p in eid for p in _SOC_PATTERNS)
            if not has_prefix:
                continue
            if any(k in eid for k in _SOC_KEYWORDS):
                self._soc_entity = state.entity_id
                soc_found = True
                _LOGGER.debug("Victron: SOC entity gevonden: %s", state.entity_id)
            if any(k in eid for k in _POWER_KEYWORDS):
                self._power_entity = state.entity_id
                power_found = True
                _LOGGER.debug("Victron: Power entity gevonden: %s", state.entity_id)

        detected = soc_found
        if detected:
            _LOGGER.info("VictronProvider: gedetecteerd (soc=%s, power=%s)",
                         self._soc_entity, self._power_entity)
        return detected

    def read_state(self) -> BatteryProviderState:
        """Read current Victron battery status."""
        soc_state   = self._hass.states.get(self._soc_entity)   if self._soc_entity   else None
        power_state = self._hass.states.get(self._power_entity) if self._power_entity else None

        soc_pct = None
        if soc_state and soc_state.state not in ("unavailable", "unknown"):
            try:
                soc_pct = float(soc_state.state)
            except (ValueError, TypeError):
                pass

        power_w = None
        if power_state and power_state.state not in ("unavailable", "unknown"):
            try:
                power_w = float(power_state.state)
            except (ValueError, TypeError):
                pass

        is_charging    = (power_w or 0) > 10
        is_discharging = (power_w or 0) < -10
        is_online      = soc_pct is not None

        return BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc_pct,
            power_w        = power_w,
            is_charging    = is_charging,
            is_discharging = is_discharging,
            active_mode    = "charging" if is_charging else "discharging" if is_discharging else "idle",
            available_modes= ["auto", "charge", "discharge", "idle"],
            is_online      = is_online,
        )

    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        """Victron charging — via HA number entity or service."""
        # Victron Cerbo GX: set ESS mode via select entity if available
        select_eid = self._find_entity("select", ("ess_mode", "charger_mode", "mode"))
        if select_eid:
            try:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": select_eid, "option": "Optimized (with BatteryLife)"},
                    blocking=True,
                )
                _LOGGER.info("Victron: laden geactiveerd via %s", select_eid)
                return True
            except Exception as e:
                _LOGGER.warning("Victron: laden mislukt: %s", e)

        # Fallback: set max charge via number entiteit
        number_eid = self._find_entity("number", ("max_charge_current", "charge_current"))
        if number_eid and power_w:
            # Convert W to A (48V system default, maar check voltage)
            voltage = self._get_battery_voltage() or 48.0
            current_a = round(power_w / voltage, 1)
            try:
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": number_eid, "value": current_a},
                    blocking=True,
                )
                return True
            except Exception as e:
                _LOGGER.warning("Victron: laadstroom instellen mislukt: %s", e)
        return False

    async def async_set_discharge(self, power_w: Optional[float] = None) -> bool:
        """Victron ontladen."""
        select_eid = self._find_entity("select", ("ess_mode", "charger_mode", "mode"))
        if select_eid:
            try:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": select_eid, "option": "External control"},
                    blocking=True,
                )
                return True
            except Exception as e:
                _LOGGER.warning("Victron: ontladen mislukt: %s", e)
        return False

    async def async_set_auto(self) -> bool:
        """Restore Victron automatic management (ESS)."""
        select_eid = self._find_entity("select", ("ess_mode", "charger_mode", "mode"))
        if select_eid:
            try:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": select_eid, "option": "Optimized (with BatteryLife)"},
                    blocking=True,
                )
                return True
            except Exception as e:
                _LOGGER.warning("Victron: auto herstellen mislukt: %s", e)
        return False

    def get_wizard_hint(self) -> ProviderWizardHint:
        return ProviderWizardHint(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            detected       = self.is_detected,
            enabled        = self.is_enabled,
            hint           = "Victron Cerbo GX / Venus OS gedetecteerd. Installeer de Victron Energy HA integratie voor volledige sturing.",
            setup_url      = "https://github.com/sfstar/hass-victron",
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_entity(self, domain: str, keywords: tuple) -> Optional[str]:
        """Find first entity in given domain with one of the keywords."""
        for state in self._hass.states.async_all(domain):
            eid = state.entity_id.lower()
            if any(p in eid for p in _SOC_PATTERNS):
                if any(k in eid for k in keywords):
                    return state.entity_id
        return None

    def _get_battery_voltage(self) -> Optional[float]:
        """Get battery voltage (for W→A calculation)."""
        for state in self._hass.states.async_all("sensor"):
            eid = state.entity_id.lower()
            if any(p in eid for p in _SOC_PATTERNS) and "battery_voltage" in eid:
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return None


# Register on import
BatteryProviderRegistry.register_provider(VictronProvider)
