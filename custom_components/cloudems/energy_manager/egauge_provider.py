# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — eGauge Slimme Meter Provider v1.0.0

eGauge is een nauwkeurige submetering oplossing, nieuw in HA 2026.1.
Populair in zakelijke installaties en grotere woningen.

Detection based on bekende entity-ID patronen:
  sensor.egauge_*_power            → Totaalvermogen (W)
  sensor.egauge_*_grid_l1_power    → Fase L1 vermogen (W)
  sensor.egauge_*_grid_l2_power    → Fase L2 vermogen (W)
  sensor.egauge_*_grid_l3_power    → Fase L3 vermogen (W)
  sensor.egauge_*_solar_power      → PV vermogen (W)
  sensor.egauge_*_usage            → Verbruik (kWh)

Returns P1-achtige grid data terug zodat CloudEMS fase-sturing kan doen
ook zonder P1 kabel of DSMR integratie.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_EGAUGE_PREFIXES = ("egauge_", "egauge.")
_GRID_KEYWORDS   = ("grid_power", "net_power", "total_power", "_power")
_PHASE_MAP       = {
    "L1": ("l1_power", "l1_current", "phase1_power", "phase_a_power"),
    "L2": ("l2_power", "l2_current", "phase2_power", "phase_b_power"),
    "L3": ("l3_power", "l3_current", "phase3_power", "phase_c_power"),
}


@dataclass
class EGaugeData:
    """eGauge measurement data."""
    available:      bool  = False
    net_power_w:    float = 0.0   # + import, - export
    l1_power_w:     Optional[float] = None
    l2_power_w:     Optional[float] = None
    l3_power_w:     Optional[float] = None
    solar_power_w:  Optional[float] = None
    energy_kwh:     Optional[float] = None
    device_name:    str   = "eGauge"


class EGaugeProvider:
    """
    eGauge smart meter provider.

    Leest grid- en fase-data uit eGauge entiteiten en geeft die terug
    in a format compatible with CloudEMS coordinator (grid_power, phases).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass           = hass
        self._detected:      bool = False
        self._net_entity:    Optional[str] = None
        self._phase_entities: dict[str, Optional[str]] = {"L1": None, "L2": None, "L3": None}
        self._solar_entity:  Optional[str] = None
        self._energy_entity: Optional[str] = None
        self._device_name:   str = "eGauge"

    async def async_setup(self) -> bool:
        """Detecteer eGauge entiteiten."""
        all_sensors = self._hass.states.async_all("sensor")

        for state in all_sensors:
            eid = state.entity_id.lower()
            if not any(p in eid for p in _EGAUGE_PREFIXES):
                continue

            # Haal apparaatnaam op
            if "egauge" in eid:
                parts = state.entity_id.split("_")
                if len(parts) > 1:
                    self._device_name = parts[1].title()

            # Grid totaal
            if self._net_entity is None and any(k in eid for k in _GRID_KEYWORDS):
                if "solar" not in eid and "pv" not in eid:
                    self._net_entity = state.entity_id
                    _LOGGER.debug("eGauge: net entity = %s", state.entity_id)

            # Fase-entiteiten
            for phase, keywords in _PHASE_MAP.items():
                if self._phase_entities[phase] is None:
                    if any(k in eid for k in keywords):
                        self._phase_entities[phase] = state.entity_id
                        _LOGGER.debug("eGauge: fase %s entity = %s", phase, state.entity_id)

            # Solar
            if self._solar_entity is None and ("solar" in eid or "pv" in eid) and "power" in eid:
                self._solar_entity = state.entity_id

            # Energie (kWh)
            if self._energy_entity is None and "usage" in eid:
                self._energy_entity = state.entity_id

        self._detected = self._net_entity is not None
        if self._detected:
            _LOGGER.info(
                "eGaugeProvider: gedetecteerd '%s' — net=%s, L1=%s, L2=%s, L3=%s",
                self._device_name, self._net_entity,
                self._phase_entities["L1"],
                self._phase_entities["L2"],
                self._phase_entities["L3"],
            )
        return self._detected

    @property
    def is_detected(self) -> bool:
        return self._detected

    def read(self) -> EGaugeData:
        """Read current eGauge data."""
        if not self._detected:
            return EGaugeData()

        def _float(entity_id: Optional[str]) -> Optional[float]:
            if not entity_id:
                return None
            s = self._hass.states.get(entity_id)
            if not s or s.state in ("unavailable", "unknown"):
                return None
            try:
                return float(s.state)
            except (ValueError, TypeError):
                return None

        net = _float(self._net_entity)
        if net is None:
            return EGaugeData()

        return EGaugeData(
            available     = True,
            net_power_w   = net,
            l1_power_w    = _float(self._phase_entities["L1"]),
            l2_power_w    = _float(self._phase_entities["L2"]),
            l3_power_w    = _float(self._phase_entities["L3"]),
            solar_power_w = _float(self._solar_entity),
            energy_kwh    = _float(self._energy_entity),
            device_name   = self._device_name,
        )

    def get_info(self) -> dict:
        """Info for dashboard / diagnostics."""
        data = self.read()
        return {
            "detected":       self._detected,
            "device_name":    self._device_name,
            "net_entity":     self._net_entity,
            "phase_entities": self._phase_entities,
            "solar_entity":   self._solar_entity,
            "net_power_w":    data.net_power_w if data.available else None,
            "l1_power_w":     data.l1_power_w,
            "l2_power_w":     data.l2_power_w,
            "l3_power_w":     data.l3_power_w,
        }
