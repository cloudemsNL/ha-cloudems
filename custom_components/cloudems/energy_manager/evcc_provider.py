# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS EVCC Bridge Provider — v1.0.0

EVCC (evcc.io) is een open-source EV laadbeheer systeem dat 50+ lader-merken
ondersteunt via één uniforme interface. De HA EVCC integratie (HACS) biedt
real-time laad- en voertuigdata.

Ondersteunde laders (via EVCC): Wallbox, ABL, Alfen, Easee, go-e, Heidelberg,
  Keba, Mennekes, NRGkick, OpenWB, Webasto, Zappi, en 40+ andere.

Entity patronen:
  sensor.evcc_*_charge_power         (W, laadvermogen per loadpoint)
  sensor.evcc_*_charge_energy        (kWh, geladen deze sessie)
  sensor.evcc_*_vehicle_soc          (%, voertuig SoC)
  sensor.evcc_*_vehicle_range        (km, resterende range)
  sensor.evcc_*_charging_duration    (s, sessieduur)
  binary_sensor.evcc_*_vehicle_connected (aan/uit)
  binary_sensor.evcc_*_charging      (aan/uit)
  select.evcc_*_mode                 (off/now/minpv/pv)
  number.evcc_*_min_current          (A, minimaal laadstroom)
  number.evcc_*_max_current          (A, maximaal laadstroom)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)


@dataclass
class EVCCLoadpoint:
    """Eén EVCC laadpunt met bijbehorende entities."""
    name:             str
    power_eid:        Optional[str] = None
    energy_eid:       Optional[str] = None
    soc_eid:          Optional[str] = None
    range_eid:        Optional[str] = None
    connected_eid:    Optional[str] = None
    charging_eid:     Optional[str] = None
    mode_eid:         Optional[str] = None
    min_current_eid:  Optional[str] = None
    max_current_eid:  Optional[str] = None
    # Live data
    power_w:          float         = 0.0
    vehicle_soc:      Optional[float] = None
    vehicle_range_km: Optional[float] = None
    is_connected:     bool           = False
    is_charging:      bool           = False
    mode:             str            = "off"


def _read_float(hass, eid):
    if not eid:
        return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable", "unknown", ""):
        return None
    try:
        return float(st.state)
    except (ValueError, TypeError):
        return None


def _read_bool(hass, eid) -> bool:
    if not eid:
        return False
    st = hass.states.get(eid)
    return st is not None and st.state in ("on", "true", "1", "charging")


class EVCCProvider(BatteryProvider):
    """EVCC EV laadbrug — leest alle loadpoints en biedt laadmodus sturing.

    CloudEMS kan via EVCC de laadbeslissingen sturen:
      - mode "off"   → laden uitgeschakeld
      - mode "now"   → laden zo snel mogelijk
      - mode "minpv" → laden met minimum stroom + PV-surplus
      - mode "pv"    → alleen laden op PV-surplus

    Dit vervangt directe lader-specifieke integraties voor EV-laden.
    """

    PROVIDER_ID    = "evcc"
    PROVIDER_LABEL = "EVCC"
    PROVIDER_ICON  = "mdi:ev-station"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._loadpoints: list[EVCCLoadpoint] = []
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self) -> None:
        await super().async_setup()
        self._discover_loadpoints()
        _LOGGER.info("EVCCProvider v1.0: detected=%s loadpoints=%d",
                     self._detected, len(self._loadpoints))

    def _discover_loadpoints(self) -> None:
        """Detecteer alle EVCC loadpoints via entity_id patronen."""
        # Zoek alle unieke loadpoint namen via charge_power sensors
        seen = set()
        for st in self._hass.states.async_all():
            sid = st.entity_id.lower()
            if "evcc" not in sid or "charge_power" not in sid:
                continue
            # Extraheer loadpoint naam: evcc_<name>_charge_power
            parts = sid.replace("sensor.evcc_", "").replace("_charge_power", "")
            if parts in seen:
                continue
            seen.add(parts)
            lp_name = parts
            # Bouw loadpoint met alle bijbehorende entities
            lp = EVCCLoadpoint(name=lp_name)
            prefix = f"evcc_{lp_name}"
            for st2 in self._hass.states.async_all():
                s2 = st2.entity_id.lower()
                if prefix not in s2:
                    continue
                if "charge_power" in s2:
                    lp.power_eid = st2.entity_id
                elif "charge_energy" in s2:
                    lp.energy_eid = st2.entity_id
                elif "vehicle_soc" in s2:
                    lp.soc_eid = st2.entity_id
                elif "vehicle_range" in s2:
                    lp.range_eid = st2.entity_id
                elif "vehicle_connected" in s2:
                    lp.connected_eid = st2.entity_id
                elif "charging" in s2 and st2.domain == "binary_sensor":
                    lp.charging_eid = st2.entity_id
                elif s2.startswith("select.") and "mode" in s2:
                    lp.mode_eid = st2.entity_id
                elif "min_current" in s2:
                    lp.min_current_eid = st2.entity_id
                elif "max_current" in s2:
                    lp.max_current_eid = st2.entity_id
            self._loadpoints.append(lp)

    async def async_detect(self) -> bool:
        self._discover_loadpoints()
        return len(self._loadpoints) > 0

    def read_state(self) -> BatteryProviderState:
        total_power_w = 0.0
        for lp in self._loadpoints:
            pw = _read_float(self._hass, lp.power_eid) or 0.0
            lp.power_w        = pw
            lp.vehicle_soc    = _read_float(self._hass, lp.soc_eid)
            lp.vehicle_range_km = _read_float(self._hass, lp.range_eid)
            lp.is_connected   = _read_bool(self._hass, lp.connected_eid)
            lp.is_charging    = _read_bool(self._hass, lp.charging_eid)
            if lp.mode_eid:
                st = self._hass.states.get(lp.mode_eid)
                lp.mode = st.state if st and st.state not in ("unavailable", "unknown") else "off"
            total_power_w += pw

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=len(self._loadpoints) > 0,
            raw={
                "total_power_w": total_power_w,
                "loadpoints": [
                    {
                        "name":        lp.name,
                        "power_w":     lp.power_w,
                        "vehicle_soc": lp.vehicle_soc,
                        "range_km":    lp.vehicle_range_km,
                        "connected":   lp.is_connected,
                        "charging":    lp.is_charging,
                        "mode":        lp.mode,
                        "power_eid":   lp.power_eid,
                        "mode_eid":    lp.mode_eid,
                    }
                    for lp in self._loadpoints
                ],
            },
        )
        return self._last_state

    async def async_set_charge(self, power_w=None) -> bool:
        """Schakel eerste loadpoint naar 'now' (laden) of 'off'."""
        if not self._loadpoints:
            return False
        lp = self._loadpoints[0]
        if not lp.mode_eid:
            return False
        mode = "now" if (power_w is None or power_w > 0) else "off"
        await self._hass.services.async_call(
            "select", "select_option",
            {"entity_id": lp.mode_eid, "option": mode},
            blocking=False,
        )
        _LOGGER.info("EVCCProvider: loadpoint %s → mode %s", lp.name, mode)
        return True

    async def async_set_mode(self, mode: str, loadpoint_name: Optional[str] = None) -> bool:
        """Stel EVCC laadmodus in: off / now / minpv / pv."""
        lps = self._loadpoints
        if loadpoint_name:
            lps = [lp for lp in lps if lp.name == loadpoint_name]
        for lp in lps:
            if lp.mode_eid:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": lp.mode_eid, "option": mode},
                    blocking=False,
                )
        return True

    async def async_set_auto(self) -> bool:
        return await self.async_set_mode("minpv")

    def get_wizard_hint(self) -> ProviderWizardHint:
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title=f"EVCC gedetecteerd ({len(self._loadpoints)} laadpunten)",
            description=(
                f"CloudEMS kan via EVCC {len(self._loadpoints)} EV-laadpunten sturen. "
                "Laadmodi: off / now / minpv (PV+minimum) / pv (alleen PV)."
            ),
            icon="mdi:ev-station",
        )

    def get_total_power_w(self) -> float:
        return self._last_state.raw.get("total_power_w", 0.0)

    def get_loadpoints(self) -> list[dict]:
        return self._last_state.raw.get("loadpoints", [])


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(EVCCProvider)
