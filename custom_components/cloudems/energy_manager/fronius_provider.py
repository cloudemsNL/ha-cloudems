# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
CloudEMS Fronius Provider — v1.0.0

Integreert Fronius omvormer/batterij via de standaard HA Fronius integratie.
Levert solar, grid, battery en SoC data aan CloudEMS coordinator.

Ondersteunde hardware (via Fronius Solar API v1):
  - Fronius Symo / Primo / Eco / Galvo omvormers
  - Fronius Symo GEN24 + BYD/LG/Sony batterij
  - Fronius Smart Meter (grid meting)
  - Fronius Ohmpilot (boiler/EV sturing)

HA integratie: homeassistant.components.fronius (standaard, geen HACS nodig)
Update frequentie: power flow 10s, omvormer detail 1min

Entity patronen (HA genereert device-specifieke namen):
  sensor.*_power_photovoltaics  (W,  solar productie)
  sensor.*_power_grid           (W,  + = import, - = export)
  sensor.*_power_battery        (W,  + = laden, - = ontladen)
  sensor.*_state_of_charge      (%,  batterij SoC)
  sensor.*_power_load           (W,  huisverbruik)
  sensor.*_energy_day           (kWh, dagproductie)
  sensor.*_ohmpilot_power_*     (W,  Ohmpilot verbruik)
"""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant

from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

# Entity-naam patronen (lowercase fragment in entity_id)
_SOLAR_PATTERNS   = ["power_photovoltaics", "ac_power", "pv_power"]
_GRID_PATTERNS    = ["power_grid", "grid_power"]
_BATTERY_PATTERNS = ["power_battery", "battery_power"]
_SOC_PATTERNS     = ["state_of_charge", "battery_soc", "soc"]
_LOAD_PATTERNS    = ["power_load", "load_power", "house_power"]
_ENERGY_PATTERNS  = ["energy_day", "energy_today", "daily_yield"]
_OHMPILOT_PATTERNS= ["ohmpilot_power", "ohmpilot"]


def _find_entity(hass: HomeAssistant, patterns: list[str],
                 domain: str = "sensor") -> Optional[str]:
    """Zoek eerste entity_id die één van de patronen bevat (Fronius domein)."""
    for st in hass.states.async_all(domain):
        sid = st.entity_id.lower()
        # Moet 'fronius' in de naam hebben om andere integraties te vermijden
        if "fronius" not in sid:
            continue
        for pat in patterns:
            if pat in sid:
                return st.entity_id
    return None


def _read_float(hass: HomeAssistant, entity_id: Optional[str]) -> Optional[float]:
    """Lees float waarde van een HA sensor, None bij unavailable."""
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if not st or st.state in ("unavailable", "unknown", ""):
        return None
    try:
        return float(st.state)
    except (ValueError, TypeError):
        return None


class FroniusProvider(BatteryProvider):
    """
    Fronius omvormer + batterij provider voor CloudEMS.

    Levert genormaliseerde solar/grid/battery data.
    Geen actieve sturing (Fronius beheert de batterij zelf via zijn eigen algoritme).
    CloudEMS leest de data en gebruikt die voor beslissingen over andere apparaten.

    Ohmpilot: optionele directe boiler/EV sturing via Fronius — als aanwezig
    wordt het vermogen gerapporteerd zodat NILM en kostenberekening kloppen.
    """

    PROVIDER_ID    = "fronius"
    PROVIDER_LABEL = "Fronius"
    PROVIDER_ICON  = "mdi:solar-power"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)

        # Gecachte entity IDs (gevuld bij async_setup)
        self._solar_eid:    Optional[str] = config.get("fronius_solar_sensor")
        self._grid_eid:     Optional[str] = config.get("fronius_grid_sensor")
        self._battery_eid:  Optional[str] = config.get("fronius_battery_sensor")
        self._soc_eid:      Optional[str] = config.get("fronius_soc_sensor")
        self._load_eid:     Optional[str] = config.get("fronius_load_sensor")
        self._energy_eid:   Optional[str] = config.get("fronius_energy_sensor")
        self._ohmpilot_eid: Optional[str] = config.get("fronius_ohmpilot_sensor")

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID,
            provider_label=self.PROVIDER_LABEL,
        )

    async def async_setup(self) -> None:
        await super().async_setup()
        # Autodetectie: vul ontbrekende entity IDs in
        self._autodiscover()
        _LOGGER.info(
            "FroniusProvider: detected=%s solar=%s grid=%s battery=%s soc=%s ohmpilot=%s",
            self._detected,
            self._solar_eid, self._grid_eid,
            self._battery_eid, self._soc_eid,
            self._ohmpilot_eid or "—",
        )

    def _autodiscover(self) -> None:
        """Detecteer Fronius entities automatisch."""
        if not self._solar_eid:
            self._solar_eid   = _find_entity(self._hass, _SOLAR_PATTERNS)
        if not self._grid_eid:
            self._grid_eid    = _find_entity(self._hass, _GRID_PATTERNS)
        if not self._battery_eid:
            self._battery_eid = _find_entity(self._hass, _BATTERY_PATTERNS)
        if not self._soc_eid:
            self._soc_eid     = _find_entity(self._hass, _SOC_PATTERNS)
        if not self._load_eid:
            self._load_eid    = _find_entity(self._hass, _LOAD_PATTERNS)
        if not self._energy_eid:
            self._energy_eid  = _find_entity(self._hass, _ENERGY_PATTERNS)
        if not self._ohmpilot_eid:
            self._ohmpilot_eid = _find_entity(self._hass, _OHMPILOT_PATTERNS)

    async def async_detect(self) -> bool:
        """Fronius aanwezig als minstens solar OF grid entity gevonden."""
        self._autodiscover()
        return bool(self._solar_eid or self._grid_eid)

    def read_state(self) -> BatteryProviderState:
        """Lees huidige Fronius data en geef genormaliseerde state terug."""
        solar_w   = _read_float(self._hass, self._solar_eid)
        grid_w    = _read_float(self._hass, self._grid_eid)
        battery_w = _read_float(self._hass, self._battery_eid)
        soc_pct   = _read_float(self._hass, self._soc_eid)
        load_w    = _read_float(self._hass, self._load_eid)
        energy_wh = None
        if self._energy_eid:
            ev = _read_float(self._hass, self._energy_eid)
            if ev is not None:
                unit = (self._hass.states.get(self._energy_eid)
                        .attributes.get("unit_of_measurement") or "").lower()
                energy_wh = ev * 1000 if "kwh" in unit else ev

        ohmpilot_w = _read_float(self._hass, self._ohmpilot_eid)

        # Fronius: battery_w positief = laden, negatief = ontladen
        is_charging    = battery_w is not None and battery_w > 10
        is_discharging = battery_w is not None and battery_w < -10

        self._last_state = BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc_pct,
            power_w        = battery_w,
            is_charging    = is_charging,
            is_discharging = is_discharging,
            active_mode    = "auto",   # Fronius beheert zelf
            available_modes= ["auto"],
            is_online      = solar_w is not None or grid_w is not None,
            raw = {
                "solar_w":     solar_w,
                "grid_w":      grid_w,
                "battery_w":   battery_w,
                "load_w":      load_w,
                "energy_wh":   energy_wh,
                "ohmpilot_w":  ohmpilot_w,
                "solar_eid":   self._solar_eid,
                "grid_eid":    self._grid_eid,
                "battery_eid": self._battery_eid,
                "soc_eid":     self._soc_eid,
                "ohmpilot_eid":self._ohmpilot_eid,
            },
        )
        return self._last_state

    # Fronius batterij wordt niet actief gestuurd door CloudEMS
    # (Fronius heeft eigen intelligente batterijsturing)
    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        _LOGGER.debug("FroniusProvider: sturing niet ondersteund (Fronius beheert zelf)")
        return False

    async def async_set_auto(self) -> bool:
        return True  # Fronius staat altijd in auto

    def get_wizard_hint(self) -> ProviderWizardHint:
        has_battery = bool(self._battery_eid)
        return ProviderWizardHint(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            detected       = self._detected,
            configured     = self._enabled,
            title          = "Fronius omvormer gedetecteerd",
            description    = (
                "CloudEMS leest solar, grid en batterijdata van je Fronius omvormer. "
                + ("Batterij met SoC gevonden. " if has_battery else "Geen batterij gevonden. ")
                + ("Ohmpilot gevonden — boiler/EV vermogen wordt meegenomen." if self._ohmpilot_eid else "")
            ),
            icon    = "mdi:solar-power",
            warning = "" if has_battery else "Geen Fronius batterij gevonden",
        )

    def get_solar_w(self) -> Optional[float]:
        """Solar vermogen (W) — voor coordinator solar_power override."""
        return self._last_state.raw.get("solar_w")

    def get_grid_w(self) -> Optional[float]:
        """Grid vermogen (W) — + = import, - = export."""
        return self._last_state.raw.get("grid_w")

    def get_load_w(self) -> Optional[float]:
        """Huisverbruik (W)."""
        return self._last_state.raw.get("load_w")

    def get_ohmpilot_w(self) -> Optional[float]:
        """Ohmpilot vermogen (W) — boiler of EV via Fronius."""
        return self._last_state.raw.get("ohmpilot_w")

    def get_energy_today_wh(self) -> Optional[float]:
        """Dagproductie (Wh) — voor SelfConsumptionTracker seed."""
        return self._last_state.raw.get("energy_wh")


# Registreer bij de BatteryProviderRegistry
from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(FroniusProvider)
