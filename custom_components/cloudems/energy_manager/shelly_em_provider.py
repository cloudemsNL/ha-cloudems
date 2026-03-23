# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS — All rights reserved.
"""CloudEMS Shelly EM / 3EM Provider — v1.0.0

Shelly EM en 3EM worden veelgebruikt als:
  - P1/grid meter alternatief (CT-clamp op hoofdaansluiting)
  - Per-fase meting (Shelly 3EM)
  - Submeter per groep (zonnepanelen, EV-lader, boiler)

Entity patronen (Shelly EM):
  sensor.shelly_em_*_power           (W, kanaal A of B)
  sensor.shelly_em_*_reactive_power  (VAR)
  sensor.shelly_em_*_energy          (kWh)
  sensor.shelly_em_*_returned_energy (kWh, teruglevering)

Entity patronen (Shelly 3EM):
  sensor.shellyem3_*_a_power / b_power / c_power   (W per fase)
  sensor.shellyem3_*_a_current / b_current / c_current (A)
  sensor.shellyem3_*_total_power                   (W, som)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
from homeassistant.core import HomeAssistant
from .battery_provider import BatteryProvider, BatteryProviderState, ProviderWizardHint

_LOGGER = logging.getLogger(__name__)


@dataclass
class ShellyChannel:
    name:       str
    power_eid:  Optional[str] = None
    energy_eid: Optional[str] = None
    current_eid:Optional[str] = None
    power_w:    float          = 0.0
    energy_kwh: Optional[float]= None


def _find_shelly(hass, keyword, domain="sensor"):
    results = []
    for st in hass.states.async_all(domain):
        s = st.entity_id.lower()
        if ("shelly" in s or "shellyem" in s) and keyword in s:
            results.append(st.entity_id)
    return results


def _rf(hass, eid):
    if not eid: return None
    st = hass.states.get(eid)
    if not st or st.state in ("unavailable","unknown",""): return None
    try: return float(st.state)
    except: return None


class ShellyEMProvider(BatteryProvider):
    """Shelly EM / 3EM provider — grid meting en per-fase data.

    Gebruik als P1-alternatief of voor submeters (EV-lader, boiler, PV).
    CloudEMS gebruikt de Shelly als grid_sensor als er geen P1 is.
    """

    PROVIDER_ID    = "shelly_em"
    PROVIDER_LABEL = "Shelly EM / 3EM"
    PROVIDER_ICON  = "mdi:meter-electric"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._channels: list[ShellyChannel] = []
        self._is_3em:   bool = False
        self._total_power_eid: Optional[str] = None
        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL)

    async def async_setup(self):
        await super().async_setup()
        self._discover_channels()
        _LOGGER.info("ShellyEMProvider: detected=%s 3em=%s channels=%d",
                     self._detected, self._is_3em, len(self._channels))

    def _discover_channels(self):
        self._channels = []
        # Detecteer Shelly 3EM (3-fase)
        total_eids = _find_shelly(self._hass, "total_power")
        if total_eids:
            self._total_power_eid = total_eids[0]
            self._is_3em = True
            for phase in ("a", "b", "c"):
                power_eids   = _find_shelly(self._hass, f"_{phase}_power")
                current_eids = _find_shelly(self._hass, f"_{phase}_current")
                ch = ShellyChannel(
                    name       = f"Fase {phase.upper()}",
                    power_eid  = power_eids[0]   if power_eids   else None,
                    current_eid= current_eids[0] if current_eids else None,
                )
                self._channels.append(ch)
            return

        # Detecteer Shelly EM (2-kanaals)
        power_eids = _find_shelly(self._hass, "_power")
        for i, eid in enumerate(power_eids[:2]):
            energy_eids = _find_shelly(self._hass, f"_energy")
            ch = ShellyChannel(
                name      = f"Kanaal {chr(65+i)}",
                power_eid = eid,
                energy_eid= energy_eids[i] if i < len(energy_eids) else None,
            )
            self._channels.append(ch)

    async def async_detect(self):
        self._discover_channels()
        return len(self._channels) > 0

    def read_state(self):
        for ch in self._channels:
            ch.power_w   = _rf(self._hass, ch.power_eid)  or 0.0
            ch.energy_kwh= _rf(self._hass, ch.energy_eid)
            if ch.current_eid:
                ch.current_a = _rf(self._hass, ch.current_eid)

        total_w = (_rf(self._hass, self._total_power_eid)
                   if self._total_power_eid
                   else sum(ch.power_w for ch in self._channels))

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            is_online=len(self._channels) > 0,
            raw={
                "total_power_w": total_w,
                "is_3em":        self._is_3em,
                "channels": [
                    {"name": ch.name, "power_w": ch.power_w,
                     "energy_kwh": ch.energy_kwh}
                    for ch in self._channels
                ],
                "grid_w": total_w,  # alias voor coordinator gebruik als grid sensor
            },
        )
        return self._last_state

    async def async_set_charge(self, power_w=None): return False
    async def async_set_auto(self): return True

    def get_wizard_hint(self):
        return ProviderWizardHint(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL,
            detected=self._detected, configured=self._enabled,
            title=f"Shelly {'3EM (3-fase)' if self._is_3em else 'EM'} gedetecteerd",
            description=(
                f"{len(self._channels)} kanalen gevonden. "
                "Kan gebruikt worden als P1-alternatief of per-fase meting."
            ),
            icon="mdi:meter-electric",
        )

    def get_total_power_w(self) -> float:
        return self._last_state.raw.get("total_power_w", 0.0)

    def get_grid_w(self) -> float:
        return self.get_total_power_w()

    def get_channels(self) -> list[dict]:
        return self._last_state.raw.get("channels", [])


from .battery_provider import BatteryProviderRegistry
BatteryProviderRegistry.register_provider(ShellyEMProvider)
