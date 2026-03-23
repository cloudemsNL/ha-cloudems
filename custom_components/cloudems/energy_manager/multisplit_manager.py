# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS Multisplit Manager — v1.0.0

Verdeelt het gemeten vermogen van een buitenunit proportioneel over binnenunits.

Verdeling prioriteit:
  1. Compressor frequentie per unit  (sensor.daikin_*_compressor_frequency)
  2. Setpoint-delta                  (|setpoint − huidige temp|)
  3. Gelijk verdeeld

Merk-onafhankelijk — werkt met elke HA climate.* entity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

MIN_DELTA_T = 0.3
MIN_FREQ_HZ = 1.0


@dataclass
class IndoorUnitState:
    entity_id:       str
    label:           str
    area:            str   = ""
    freq_sensor:     str   = ""
    hvac_mode:       str   = "off"
    hvac_action:     str   = "idle"
    current_temp_c:  Optional[float] = None
    setpoint_c:      Optional[float] = None
    freq_hz:         Optional[float] = None
    power_w:         float = 0.0
    share_pct:       float = 0.0
    method:          str   = "off"


@dataclass
class OutdoorUnitState:
    id:            str
    label:         str
    power_sensor:  str
    freq_sensor:   str                    = ""
    indoor_units:  list[IndoorUnitState]  = field(default_factory=list)
    total_power_w: float = 0.0
    active_count:  int   = 0
    method_used:   str   = "none"


class MultisplitManager:
    """
    Beheert alle geconfigureerde multisplit/airco groepen.

    Configuratie via config_entry.options["multisplit_groups"]:
      [{
        "id":           "airco_1",
        "label":        "Airco Woonvleugel",
        "power_sensor": "sensor.airco_buitenunit_vermogen",   # W
        "freq_sensor":  "sensor.daikin_freq",                 # Hz optioneel
        "indoor_units": [
          {"entity_id": "climate.daikin_woonkamer",
           "label": "Woonkamer", "area": "Woonkamer",
           "freq_sensor": "sensor.daikin_woonkamer_freq"},    # optioneel
          ...
        ]
      }]
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._groups: list[OutdoorUnitState] = []
        self._build_groups()

    def _build_groups(self) -> None:
        self._groups = []
        for g in self._config.get("multisplit_groups", []):
            units = [
                IndoorUnitState(
                    entity_id  = u["entity_id"],
                    label      = u.get("label", u["entity_id"].split(".")[-1]),
                    area       = u.get("area", ""),
                    freq_sensor= u.get("freq_sensor", ""),
                )
                for u in g.get("indoor_units", [])
            ]
            self._groups.append(OutdoorUnitState(
                id           = g.get("id", f"group_{len(self._groups)}"),
                label        = g.get("label", f"Airco {len(self._groups)+1}"),
                power_sensor = g.get("power_sensor", ""),
                freq_sensor  = g.get("freq_sensor", ""),
                indoor_units = units,
            ))

    def update(self) -> None:
        for g in self._groups:
            self._update_group(g)

    def _update_group(self, g: OutdoorUnitState) -> None:
        # Buitenunit vermogen
        total_w = 0.0
        if g.power_sensor:
            st = self._hass.states.get(g.power_sensor)
            if st and st.state not in ("unavailable", "unknown", ""):
                try:
                    total_w = float(st.state)
                except (ValueError, TypeError):
                    pass
        g.total_power_w = total_w

        for u in g.indoor_units:
            self._read_unit(u)

        active = [u for u in g.indoor_units
                  if u.hvac_mode not in ("off", "unavailable", "unknown", "")]
        g.active_count = len(active)

        if total_w <= 0 or not active:
            for u in g.indoor_units:
                u.power_w = 0.0; u.share_pct = 0.0; u.method = "off"
            g.method_used = "off"
            return

        # Methode 1: compressorfrequentie
        freq_ok = [u for u in active
                   if u.freq_hz is not None and u.freq_hz >= MIN_FREQ_HZ]
        if len(freq_ok) == len(active) and freq_ok:
            total_freq = sum(u.freq_hz for u in freq_ok) or 1.0
            for u in active:
                u.share_pct = round(u.freq_hz / total_freq * 100, 1)
                u.power_w   = round(total_w * u.freq_hz / total_freq, 1)
                u.method    = "freq"
            for u in g.indoor_units:
                if u not in active:
                    u.power_w = 0.0; u.share_pct = 0.0; u.method = "off"
            g.method_used = "freq"
            return

        # Methode 2: setpoint-delta
        delta_ok = [u for u in active
                    if u.current_temp_c is not None and u.setpoint_c is not None]
        if len(delta_ok) == len(active) and delta_ok:
            deltas = [max(MIN_DELTA_T, abs(u.setpoint_c - u.current_temp_c))
                      for u in delta_ok]
            total_d = sum(deltas) or 1.0
            for u, d in zip(delta_ok, deltas):
                u.share_pct = round(d / total_d * 100, 1)
                u.power_w   = round(total_w * d / total_d, 1)
                u.method    = "delta"
            for u in g.indoor_units:
                if u not in active:
                    u.power_w = 0.0; u.share_pct = 0.0; u.method = "off"
            g.method_used = "delta"
            return

        # Methode 3: gelijk
        eq_w   = round(total_w / len(active), 1)
        eq_pct = round(100 / len(active), 1)
        for u in active:
            u.power_w = eq_w; u.share_pct = eq_pct; u.method = "equal"
        for u in g.indoor_units:
            if u not in active:
                u.power_w = 0.0; u.share_pct = 0.0; u.method = "off"
        g.method_used = "equal"

    def _read_unit(self, u: IndoorUnitState) -> None:
        st = self._hass.states.get(u.entity_id)
        if not st or st.state in ("unavailable", "unknown"):
            u.hvac_mode = "unavailable"; u.hvac_action = "unavailable"
            u.current_temp_c = None; u.setpoint_c = None; u.freq_hz = None
            return
        u.hvac_mode   = st.state
        u.hvac_action = st.attributes.get("hvac_action", "")
        for attr, dest in (("current_temperature", "current_temp_c"),
                           ("temperature", "setpoint_c")):
            try:
                setattr(u, dest, float(st.attributes[attr]))
            except (KeyError, TypeError, ValueError):
                setattr(u, dest, None)
        u.freq_hz = None
        if u.freq_sensor:
            fs = self._hass.states.get(u.freq_sensor)
            if fs and fs.state not in ("unavailable", "unknown", ""):
                try:
                    u.freq_hz = float(fs.state)
                except (ValueError, TypeError):
                    pass

        # Energiesensoren uitlezen (uurlijks bijgewerkt, bijv. Daikin)
        for sensor_attr, dest in (
            ("energy_cool_sensor",  "energy_cool_wh"),
            ("energy_heat_sensor",  "energy_heat_wh"),
            ("energy_total_sensor", "energy_total_wh"),
        ):
            sensor_id = getattr(u, sensor_attr, "")
            if sensor_id:
                es = self._hass.states.get(sensor_id)
                if es and es.state not in ("unavailable", "unknown", ""):
                    try:
                        # Daikin rapporteert in kWh → omzetten naar Wh
                        val = float(es.state)
                        unit = (es.attributes.get("unit_of_measurement") or "").lower()
                        setattr(u, dest, val * 1000 if "kwh" in unit else val)
                    except (ValueError, TypeError):
                        pass

    # ── Publieke interface ─────────────────────────────────────────────────────

    def get_data(self) -> dict:
        return {
            "groups": [
                {
                    "id":            g.id,
                    "label":         g.label,
                    "total_power_w": g.total_power_w,
                    "active_count":  g.active_count,
                    "method":        g.method_used,
                    "indoor_units": [
                        {
                            "entity_id":   u.entity_id,
                            "label":       u.label,
                            "area":        u.area,
                            "hvac_mode":   u.hvac_mode,
                            "hvac_action": u.hvac_action,
                            "current_temp":u.current_temp_c,
                            "setpoint":    u.setpoint_c,
                            "freq_hz":     u.freq_hz,
                            "power_w":     u.power_w,
                            "share_pct":   u.share_pct,
                            "method":      u.method,
                            "energy_cool_wh":  u.energy_cool_wh,
                            "energy_heat_wh":  u.energy_heat_wh,
                            "energy_total_wh": u.energy_total_wh,
                        }
                        for u in g.indoor_units
                    ],
                }
                for g in self._groups
            ],
            "total_groups":  len(self._groups),
            "total_power_w": sum(g.total_power_w for g in self._groups),
        }

    def get_nilm_devices(self) -> list[dict]:
        """NILM-injectie: per binnenunit een device met berekend vermogen."""
        devices = []
        for g in self._groups:
            for u in g.indoor_units:
                devices.append({
                    "id":        f"multisplit_{u.entity_id.replace('.','_')}",
                    "name":      u.label,
                    "type":      "heat_pump",
                    "area":      u.area,
                    "phase":     "?",
                    "power_w":   u.power_w,
                    "confidence":100.0,
                    "on_events": 0,
                    "confirmed": True,
                    "source":    "multisplit",
                    "group":     g.label,
                    "method":    u.method,
                })
        return devices

    def get_total_power_w(self) -> float:
        return sum(g.total_power_w for g in self._groups)

    def is_configured(self) -> bool:
        return bool(self._groups)

    def reload_config(self, config: dict) -> None:
        self._config = config
        self._build_groups()
