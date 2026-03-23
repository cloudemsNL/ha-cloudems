# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Enphase Envoy Provider — v1.0.0

HA integratie: homeassistant.components.enphase_envoy (standaard)
Update: 60s systeem, 5-15min per micro-omvormer

Uniek: per micro-omvormer data → verbetering PV health / schaduwdetectie.

Entity patronen:
  sensor.envoy_*_current_power_production   (W, totaal)
  sensor.envoy_*_current_power_consumption  (W, huisverbruik)
  sensor.envoy_*_energy_production_today    (kWh)
  sensor.inverter_*_<serienr>               (W, per micro-omvormer)
"""
from __future__ import annotations
import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)

_SOLAR_P   = ["current_power_production", "envoy_production"]
_LOAD_P    = ["current_power_consumption", "envoy_consumption"]
_GRID_P    = ["current_power_net_consumption", "envoy_grid"]
_ENERGY_P  = ["energy_production_today", "envoy_today"]
_MICRO_P   = ["inverter_"]  # micro-omvormer entities


def _find_envoy(hass, patterns):
    for st in hass.states.async_all("sensor"):
        s = st.entity_id.lower()
        if "envoy" not in s: continue
        for p in patterns:
            if p in s: return st.entity_id
    return None


def _find_micro_inverters(hass) -> list[str]:
    """Vind alle micro-omvormer entities (per paneel)."""
    result = []
    for st in hass.states.async_all("sensor"):
        s = st.entity_id.lower()
        # Micro-omvormers: sensor.inverter_<serienr> of sensor.envoy_inverter_*
        if ("inverter" in s) and ("envoy" in s or s.startswith("sensor.inverter_")):
            try:
                val = float(st.state)
                if 0 <= val <= 1000:  # sanity: max 1kW per paneel
                    result.append(st.entity_id)
            except (ValueError, TypeError):
                pass
    return result


def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None


class EnphaseProvider(BatteryProvider):
    """Enphase Envoy provider — solar, verbruik, grid en per-paneel data."""

    PROVIDER_ID    = "enphase"
    PROVIDER_LABEL = "Enphase Envoy"
    PROVIDER_ICON  = "mdi:solar-panel"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._solar_eid  = config.get("enphase_solar_sensor")
        self._load_eid   = config.get("enphase_load_sensor")
        self._grid_eid   = config.get("enphase_grid_sensor")
        self._energy_eid = config.get("enphase_energy_sensor")
        self._micro_eids: list[str] = []
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        if not self._solar_eid:  self._solar_eid  = _find_envoy(self._hass, _SOLAR_P)
        if not self._load_eid:   self._load_eid   = _find_envoy(self._hass, _LOAD_P)
        if not self._grid_eid:   self._grid_eid   = _find_envoy(self._hass, _GRID_P)
        if not self._energy_eid: self._energy_eid = _find_envoy(self._hass, _ENERGY_P)
        self._micro_eids = _find_micro_inverters(self._hass)
        _LOGGER.info("EnphaseProvider: detected=%s solar=%s micro_inverters=%d",
                     self._detected, self._solar_eid, len(self._micro_eids))

    async def async_detect(self):
        if not self._solar_eid: self._solar_eid = _find_envoy(self._hass, _SOLAR_P)
        return bool(self._solar_eid)

    def read_state(self):
        solar_w  = _rf(self._hass, self._solar_eid)
        load_w   = _rf(self._hass, self._load_eid)
        grid_w   = _rf(self._hass, self._grid_eid)
        energy_wh = None
        if self._energy_eid:
            ev = _rf(self._hass, self._energy_eid)
            if ev is not None:
                st = self._hass.states.get(self._energy_eid)
                unit = (st.attributes.get("unit_of_measurement") or "").lower() if st else ""
                energy_wh = ev * 1000 if "kwh" in unit else ev

        # Per micro-omvormer vermogen
        micro_data = {}
        for eid in self._micro_eids:
            pw = _rf(self._hass, eid)
            if pw is not None:
                micro_data[eid] = pw

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=solar_w is not None,
            raw={
                "solar_w":    solar_w,
                "load_w":     load_w,
                "grid_w":     grid_w,
                "energy_wh":  energy_wh,
                "micro":      micro_data,
                "micro_count":len(micro_data),
            },
        )
        return self._last_state

    async def async_set_charge(self, power_w=None): return False
    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        n = len(self._micro_eids)
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title=f"Enphase Envoy gedetecteerd ({n} micro-omvormers)",
            description=(
                f"CloudEMS leest solar/grid/verbruik van Enphase Envoy. "
                + (f"{n} micro-omvormer sensoren gevonden voor per-paneel schaduwanalyse." if n else "")
            ),
            icon="mdi:solar-panel",
        )

    def get_solar_w(self): return self._last_state.raw.get("solar_w")
    def get_grid_w(self):  return self._last_state.raw.get("grid_w")
    def get_load_w(self):  return self._last_state.raw.get("load_w")
    def get_energy_today_wh(self): return self._last_state.raw.get("energy_wh")

    def get_micro_inverters(self) -> dict[str, float]:
        """Per-paneel vermogen: {entity_id: watt}."""
        return self._last_state.raw.get("micro", {})


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(EnphaseProvider)
