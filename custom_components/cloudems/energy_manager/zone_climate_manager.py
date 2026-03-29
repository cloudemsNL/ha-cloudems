# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Zelflerend Multi-Zone Klimaatbeheer (v2.6).

FILOSOFIE
════════════════════════════════════════════════════════════════════════════════
Geen configuratie nodig — CloudEMS ontdekt alles automatisch:

  1. Leest HA Area Registry → maakt een VirtualZone per ruimte
  2. Koppelt alle climate.* entiteiten via area_id aan de juiste zone
  3. Classificeert elk apparaat: TRV / airco / thermostaat / convector
  4. Leert verwarmingssnelheid per zone (graden/min bij actieve verwarming)
  5. Vergelijkt gas vs elektriciteit per uur → kiest goedkoopste warmtebron
  6. Berekent kosten per zone per dag/maand
  7. Adviseert houtkachel als dat goedkoper/duurzamer is
  8. Stuurt CV-ketel op basis van geaggregeerde TRV-vraag
  9. Stuurt airco/warmtepomp op basis van prijs+COP+zonne-overschot

ENERGIE-BRON KEUZE (per zone, per uur)
════════════════════════════════════════
  gas_eur_kwh_th   = gas_prijs_m3 / (9.769 * eta_cv)     # typisch ~0.14 euro/kWh_th
  elec_eur_kwh_th  = epex_prijs_kwh / COP_warmtepomp      # typisch 0.08-0.30 euro/kWh_th

  Keuze:
    COP * prijs_el < gas_prijs_th  ->  airco/warmtepomp
    anders                          ->  CV (gas) of convector als geen CV

HOUTKACHEL ADVIES
══════════════════
  Kachel aan = zinvol als:
    - Buiten < 10 graden
    - Warmtebehoefte > 1 kWh komend uur
    - Gas > 1.50 euro/m3 OF elektriciteit > 0.28 euro/kWh
  Besparing berekend op basis van gemiddeld vermogen en tarief

Copyright 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .pid_controller import PIDController

_LOGGER = logging.getLogger(__name__)

# ── Constanten ─────────────────────────────────────────────────────────────────
GAS_KWH_PER_M3      = 9.769
GAS_BOILER_EFF      = 0.90
DEFAULT_GAS_EUR_M3  = 1.25
DEFAULT_COP         = 3.5
CONVECTOR_EFF       = 1.00

WOOD_STOVE_KW       = 6.0
WOOD_STOVE_MIN_NEED = 1.0
WOOD_STOVE_MIN_SAVE = 0.25
WOOD_STOVE_MAX_OUT  = 10.0

CV_DEADBAND_K       = 0.5
PRICE_HIGH_RATIO    = 1.40
PRICE_PREHEAT_RATIO = 0.65
SOLAR_SURPLUS_W     = 800
PREHEAT_MAX_MIN     = 120
OVERRIDE_TIMEOUT_H  = 4

SAVE_KEY            = "cloudems_zone_climate_v1"
SAVE_VERSION        = 1
SAVE_INTERVAL_S     = 300


# ── Presets ────────────────────────────────────────────────────────────────────
class Preset(str, Enum):
    COMFORT    = "comfort"
    ECO        = "eco"
    BOOST      = "boost"
    SLEEP      = "sleep"
    AWAY       = "away"
    SOLAR      = "solar"
    HOUTFIRE   = "houtfire"
    ECO_WINDOW = "eco_window"

DEFAULT_TEMPS = {
    Preset.COMFORT:    20.0,
    Preset.ECO:        17.5,
    Preset.BOOST:      22.0,
    Preset.SLEEP:      15.5,
    Preset.AWAY:       14.0,
    Preset.SOLAR:      21.0,
    Preset.HOUTFIRE:   15.0,
    Preset.ECO_WINDOW: 14.0,
}

PRESET_NL = {
    Preset.COMFORT:    "Comfort",
    Preset.ECO:        "Eco",
    Preset.BOOST:      "Boost",
    Preset.SLEEP:      "Slaap",
    Preset.AWAY:       "Afwezig",
    Preset.SOLAR:      "Zon",
    Preset.HOUTFIRE:   "Houtkachel",
    Preset.ECO_WINDOW: "Raam open",
}


# ── Apparaat-classificatie ──────────────────────────────────────────────────────
class DeviceRole(str, Enum):
    TRV        = "trv"
    AIRCO      = "airco"
    THERMOSTAT = "thermostat"
    CONVECTOR  = "convector"
    UNKNOWN    = "unknown"

PLATFORM_ROLE = {
    "zha": DeviceRole.TRV, "z2m": DeviceRole.TRV, "zigbee2mqtt": DeviceRole.TRV,
    "zwave_js": DeviceRole.TRV, "eq3btsmart": DeviceRole.TRV, "tuya": DeviceRole.TRV,
    "daikin": DeviceRole.AIRCO, "mitsubishi": DeviceRole.AIRCO,
    "sensibo": DeviceRole.AIRCO, "midea_ac": DeviceRole.AIRCO,
    "panasonic_cc": DeviceRole.AIRCO, "toshiba_ac": DeviceRole.AIRCO,
    "hisense_ac": DeviceRole.AIRCO, "intesishome": DeviceRole.AIRCO,
    "broadlink": DeviceRole.AIRCO,
    "nest": DeviceRole.THERMOSTAT, "tado": DeviceRole.THERMOSTAT,
    "honeywell_home": DeviceRole.THERMOSTAT, "netatmo": DeviceRole.THERMOSTAT,
    "opentherm_gw": DeviceRole.THERMOSTAT, "otgw": DeviceRole.THERMOSTAT,
    "evohome": DeviceRole.THERMOSTAT, "ecobee": DeviceRole.THERMOSTAT,
}

NAME_ROLE = [
    ("trv", DeviceRole.TRV), ("radiator", DeviceRole.TRV),
    ("klep", DeviceRole.TRV), ("valve", DeviceRole.TRV),
    ("kraan", DeviceRole.TRV), ("thermkop", DeviceRole.TRV),
    ("airco", DeviceRole.AIRCO), ("split", DeviceRole.AIRCO),
    ("warmtepomp", DeviceRole.AIRCO), ("heatpump", DeviceRole.AIRCO),
    ("daikin", DeviceRole.AIRCO), ("mitsubishi", DeviceRole.AIRCO),
    ("convector", DeviceRole.CONVECTOR), ("kachel", DeviceRole.CONVECTOR),
    ("heater", DeviceRole.CONVECTOR),
    ("nest", DeviceRole.THERMOSTAT), ("tado", DeviceRole.THERMOSTAT),
    ("honeywell", DeviceRole.THERMOSTAT), ("opentherm", DeviceRole.THERMOSTAT),
    ("otgw", DeviceRole.THERMOSTAT), ("ketel", DeviceRole.THERMOSTAT),
]


def classify_entity(entity_id: str, state, platform: str = "") -> DeviceRole:
    name = (state.attributes.get("friendly_name") or entity_id).lower()
    for plat, role in PLATFORM_ROLE.items():
        if plat in platform.lower():
            return role
    for kw, role in NAME_ROLE:
        if kw in name or kw in entity_id.lower():
            return role
    hvac_modes = state.attributes.get("hvac_modes", [])
    if "cool" in hvac_modes or "dry" in hvac_modes:
        return DeviceRole.AIRCO
    if state.attributes.get("supported_features", 0) & 8:
        return DeviceRole.AIRCO
    if hvac_modes in [["heat"], ["heat", "off"]]:
        if state.attributes.get("target_temp_step", 1.0) <= 0.5:
            return DeviceRole.TRV
    return DeviceRole.UNKNOWN


# ── Energie-bron optimizer ──────────────────────────────────────────────────────
@dataclass
class SourceComparison:
    gas_eur_kwh_th:       float
    elec_eur_kwh_th:      float
    convector_eur_kwh_th: float
    cop_used:             float
    best_source:          str
    reason:               str
    saving_eur_kwh:       float


def compare_sources(
    gas_eur_m3: float,
    elec_eur_kwh: float,
    cop: float,
    solar_surplus_w: float = 0.0,
    has_cv: bool = True,
    has_heatpump: bool = False,
    has_airco: bool = False,
    has_convector: bool = False,
) -> SourceComparison:
    gas_th  = gas_eur_m3 / (GAS_KWH_PER_M3 * GAS_BOILER_EFF)
    elec_th = elec_eur_kwh / max(cop, 1.0)
    conv_th = elec_eur_kwh / CONVECTOR_EFF

    if solar_surplus_w > SOLAR_SURPLUS_W and (has_heatpump or has_airco or has_convector):
        return SourceComparison(gas_th, elec_th, conv_th, cop, "free_solar",
            f"Zonne-overschot {solar_surplus_w:.0f}W — gratis elektrisch", gas_th)

    if elec_eur_kwh < 0 and (has_heatpump or has_airco or has_convector):
        return SourceComparison(gas_th, elec_th, conv_th, cop, "free_negative",
            f"Negatief tarief {elec_eur_kwh*100:.1f}ct — elektrisch verwarmen",
            round(gas_th - elec_th, 4))

    if (has_heatpump or has_airco) and elec_th < gas_th:
        return SourceComparison(gas_th, elec_th, conv_th, cop, "electric",
            f"Warmtepomp goedkoper: {elec_th*100:.1f}ct vs gas {gas_th*100:.1f}ct/kWh (COP={cop:.1f})",
            round(gas_th - elec_th, 4))

    if has_cv:
        if has_convector and conv_th < gas_th:
            return SourceComparison(gas_th, elec_th, conv_th, cop, "convector",
                f"Convector goedkoper: {conv_th*100:.1f}ct vs gas {gas_th*100:.1f}ct/kWh",
                round(gas_th - conv_th, 4))
        return SourceComparison(gas_th, elec_th, conv_th, cop, "gas",
            f"Gas goedkoper: {gas_th*100:.1f}ct vs stroom {elec_th*100:.1f}ct/kWh_th",
            round(elec_th - gas_th, 4))

    best = "electric" if (has_heatpump or has_airco) and elec_th < conv_th else "convector"
    return SourceComparison(gas_th, elec_th, conv_th, cop, best, "Geen CV — elektrisch", 0.0)


# ── Houtkachel adviseur ─────────────────────────────────────────────────────────
@dataclass
class WoodStoveAdvice:
    should_light:   bool
    reason:         str
    saving_eur_h:   float
    saving_eur_day: float


def advise_wood_stove(
    outside_temp_c: float,
    heat_need_w: float,
    gas_eur_m3: float,
    elec_eur_kwh: float,
    cop: float,
    stove_available: bool = True,
) -> WoodStoveAdvice:
    if not stove_available or outside_temp_c > WOOD_STOVE_MAX_OUT:
        return WoodStoveAdvice(False, f"Buiten {outside_temp_c:.0f}C — kachel niet nodig", 0.0, 0.0)
    need_kwh_h = heat_need_w / 1000
    if need_kwh_h < WOOD_STOVE_MIN_NEED:
        return WoodStoveAdvice(False, f"Warmtebehoefte laag ({heat_need_w:.0f}W)", 0.0, 0.0)
    gas_th      = gas_eur_m3 / (GAS_KWH_PER_M3 * GAS_BOILER_EFF)
    elec_th     = elec_eur_kwh / max(cop, 1.0)
    current_th  = min(gas_th, elec_th)
    stove_kwh_h = min(WOOD_STOVE_KW, need_kwh_h)
    saving_h    = stove_kwh_h * current_th
    if saving_h < WOOD_STOVE_MIN_SAVE:
        return WoodStoveAdvice(False, f"Besparing {saving_h*100:.0f}ct/uur — niet de moeite", 0.0, 0.0)
    return WoodStoveAdvice(
        True,
        f"Steek de houtkachel aan! Bespaart {saving_h*100:.0f}ct/uur "
        f"(stroom {elec_eur_kwh*100:.0f}ct, gas {gas_eur_m3:.2f} euro/m3)",
        round(saving_h, 3),
        round(saving_h * 8, 2),
    )


# ── Weekschema ──────────────────────────────────────────────────────────────────
@dataclass
class ScheduleBlock:
    weekdays: list
    time_on:  str
    preset:   Preset
    temp:     Optional[float] = None

    def is_active_now(self, now: datetime) -> bool:
        if now.weekday() not in self.weekdays:
            return False
        h, m = map(int, self.time_on.split(":"))
        return (now.hour, now.minute) >= (h, m)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            weekdays=d.get("weekdays", list(range(7))),
            time_on=d.get("time", "00:00"),
            preset=Preset(d.get("preset", "comfort")),
            temp=d.get("temp"),
        )


# ── Lerende verwarmingssnelheid ─────────────────────────────────────────────────
class HeatingRateLearner:
    def __init__(self):
        self._samples: deque = deque(maxlen=60)
        self._rates:   deque = deque(maxlen=40)

    def record(self, temp: float, heating_active: bool) -> None:
        now_ts = time.time()
        self._samples.append((now_ts, temp, heating_active))
        if heating_active and len(self._samples) >= 6:
            recent = [s for s in self._samples if now_ts - s[0] < 600 and s[2]]
            if len(recent) >= 4:
                dt = recent[-1][0] - recent[0][0]
                dT = recent[-1][1] - recent[0][1]
                if dt > 60 and 0 < dT < 10:
                    rate = dT / (dt / 60)
                    if 0.01 < rate < 3.0:
                        self._rates.append(rate)

    def avg_rate(self) -> float:
        return sum(self._rates) / len(self._rates) if self._rates else 0.20

    def preheat_minutes(self, delta_k: float) -> int:
        if delta_k <= 0:
            return 0
        return max(5, min(PREHEAT_MAX_MIN, int(delta_k / self.avg_rate())))

    def to_dict(self) -> dict:
        return {
            "rate_k_min":    round(self.avg_rate(), 3),
            "samples":       len(self._rates),
            "preheat_1k_m":  self.preheat_minutes(1.0),
            "preheat_3k_m":  self.preheat_minutes(3.0),
        }


# ── Kosten-tracker ─────────────────────────────────────────────────────────────
class ZoneCostTracker:
    def __init__(self):
        self._today_eur  = 0.0
        self._month_eur  = 0.0
        self._today_kwh  = 0.0
        self._month_kwh  = 0.0
        self._last_day   = ""
        self._last_month = ""
        self._history: dict = {}
        self._sources: dict = {}

    def record(self, power_w: float, duration_s: float, eur_kwh_th: float, source: str):
        kwh = power_w / 1000 * duration_s / 3600
        eur = kwh * eur_kwh_th
        now  = datetime.now(timezone.utc)
        day  = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        if day != self._last_day:
            if self._last_day:
                self._history[self._last_day] = round(self._today_eur, 4)
            self._today_eur = 0.0
            self._today_kwh = 0.0
            self._sources   = {}
            self._last_day  = day
        if month != self._last_month:
            self._month_eur = 0.0
            self._month_kwh = 0.0
            self._last_month = month
        self._today_eur += eur
        self._today_kwh += kwh
        self._month_eur += eur
        self._month_kwh += kwh
        self._sources[source] = self._sources.get(source, 0.0) + eur

    def to_dict(self) -> dict:
        return {
            "today_eur":  round(self._today_eur, 2),
            "today_kwh":  round(self._today_kwh, 3),
            "month_eur":  round(self._month_eur, 2),
            "month_kwh":  round(self._month_kwh, 3),
            "sources":    {k: round(v, 2) for k, v in self._sources.items()},
            "history":    dict(list(self._history.items())[-30:]),
        }

    def load(self, d: dict):
        self._today_eur = d.get("today_eur", 0.0)
        self._today_kwh = d.get("today_kwh", 0.0)
        self._month_eur = d.get("month_eur", 0.0)
        self._month_kwh = d.get("month_kwh", 0.0)
        self._history   = d.get("history", {})


# ── VirtualZone ────────────────────────────────────────────────────────────────
@dataclass
class ZoneSnapshot:
    area_id:        str
    area_name:      str
    preset:         Preset
    target_temp:    float
    current_temp:   Optional[float]
    heat_demand:    bool
    cool_demand:    bool
    reason:         str
    best_source:    str
    source_reason:  str
    cost_today:     float
    cost_month:     float
    stove_advice:   Optional[WoodStoveAdvice]
    preheat_min:    int
    window_open:    bool
    entities:       list
    pid_info:       dict
    learning:       dict


class VirtualZone:
    """Een zelflerend klimaatzone voor een HA area."""

    def __init__(self, hass, area_id: str, area_name: str):
        self._hass       = hass
        self._area_id    = area_id
        self._area_name  = area_name
        self._entities: dict = {}    # entity_id -> DeviceRole
        self._temps      = dict(DEFAULT_TEMPS)
        self._schedule: list = []
        self._pid = PIDController(
            kp=1.2, ki=0.08, kd=0.3,
            setpoint=self._temps[Preset.COMFORT],
            output_min=self._temps[Preset.AWAY],
            output_max=self._temps[Preset.BOOST],
            deadband=0.2, sample_time=120,
            label=f"zone_{area_id}",
        )
        self._learner    = HeatingRateLearner()
        self._costs      = ZoneCostTracker()
        self._preset     = Preset.COMFORT
        self._override_preset: Optional[Preset] = None
        self._override_until:  Optional[datetime] = None
        self._last_temp: Optional[float] = None
        self._last_snap: Optional[ZoneSnapshot] = None
        self._update_ts  = 0.0
        self._stove_samples: deque = deque(maxlen=20)

    # Entiteit-beheer
    def add_entity(self, eid: str, role: DeviceRole):
        self._entities[eid] = role

    def set_temp(self, preset: Preset, temp: float):
        self._temps[preset] = temp
        if preset == Preset.COMFORT:
            self._pid.update_setpoint(temp)

    def set_schedule(self, blocks: list):
        self._schedule = [ScheduleBlock.from_dict(b) for b in blocks]

    def set_override(self, preset: Preset, hours: float = OVERRIDE_TIMEOUT_H):
        self._override_preset = preset
        self._override_until  = datetime.now(timezone.utc) + timedelta(hours=hours)

    # ── Hoofd update ───────────────────────────────────────────────────────────
    async def async_update(self, data: dict) -> ZoneSnapshot:
        now   = datetime.now(timezone.utc)
        dt_s  = time.time() - self._update_ts if self._update_ts else 60.0
        self._update_ts = time.time()

        # Override verlopen?
        if self._override_until and now > self._override_until:
            self._override_preset = None
            self._override_until  = None

        # Prijzen & parameters
        price_info   = data.get("energy_price") or {}
        elec_kwh     = float(price_info.get("current_eur_kwh", 0.25) or 0.25)
        avg_elec     = float(price_info.get("avg_today_eur_kwh", 0.25) or 0.25)
        gas_m3       = float(data.get("gas_price_eur_m3", DEFAULT_GAS_EUR_M3) or DEFAULT_GAS_EUR_M3)
        surplus_w    = float(data.get("solar_surplus_w", 0) or 0)
        outside_t    = data.get("outside_temp_c")
        _cop_raw     = data.get("heat_pump_cop", DEFAULT_COP)
        cop          = float(
            (_cop_raw.get("cop_current") or DEFAULT_COP) if isinstance(_cop_raw, dict)
            else (_cop_raw or DEFAULT_COP)
        )

        has_cv       = bool(data.get("cv_available", False))
        has_hp       = any(r == DeviceRole.AIRCO for r in self._entities.values())
        has_conv     = any(r == DeviceRole.CONVECTOR for r in self._entities.values())

        # Temperatuur lezen
        current_t = self._read_temp()

        # Verwarmingsactiviteit + leren
        heating = self._is_heating()
        if current_t is not None:
            self._learner.record(current_t, heating)

        # Houtkachel detectie
        stove = self._detect_stove(current_t, heating, data)

        # Energiebron vergelijking
        src = compare_sources(gas_m3, elec_kwh, cop, surplus_w, has_cv, has_hp, has_hp, has_conv)

        # Houtkachel advies
        stove_adv = None
        if outside_t is not None and data.get("stove_available"):
            need_w = max(0, (self._temps[Preset.COMFORT] - (current_t or 18.0))) * 200
            stove_adv = advise_wood_stove(outside_t, need_w, gas_m3, elec_kwh, cop)

        # Preset beslissen
        ratio  = elec_kwh / avg_elec if avg_elec > 0 else 1.0
        preset, reason = self._decide(now, current_t, data, stove, src, ratio)
        self._preset   = preset
        target_t       = self._temps[preset]

        # PID
        pid_info = {}
        if preset in (Preset.COMFORT, Preset.ECO, Preset.BOOST, Preset.SOLAR) \
                and current_t is not None:
            self._pid.update_setpoint(target_t)
            out = self._pid.compute(current_t)
            if out is not None:
                target_t = round(max(self._temps[Preset.AWAY],
                                     min(self._temps[Preset.BOOST], out)), 1)
            pid_info = self._pid.to_dict()

        heat_demand = self._needs_heat(current_t, target_t, src.best_source)
        cool_demand = self._needs_cool(current_t, target_t, preset)

        # Pre-heat
        preheat_min = 0
        nc = self._next_comfort(now)
        if nc and current_t is not None:
            preheat_min = self._learner.preheat_minutes(
                max(0.0, self._temps[Preset.COMFORT] - current_t)
            )

        # Entiteiten aansturen
        await self._drive(target_t, heat_demand, cool_demand, preset, src.best_source)

        # Kosten
        if heat_demand or cool_demand:
            # Gebruik gewogen daggemiddelde voor stabiele kostenscnatting.
            # Actuele prijs alleen bij extreme tarieven (negatief / gratis zonnestroom).
            if "free" in src.best_source:
                eur_kwh_th = 0.0
            elif src.best_source == "gas":
                eur_kwh_th = src.gas_eur_kwh_th
            else:
                # Elektrisch: gewogen gemiddelde geeft stabieler dagtotaal dan momentprijs
                _avg_elec = float(price_info.get("avg_today_eur_kwh", elec_kwh) or elec_kwh)
                _elec_for_cost = (_avg_elec + elec_kwh) / 2.0  # mix van gemiddelde en actueel
                eur_kwh_th = _elec_for_cost / max(cop, 1.0)
            self._costs.record(1000.0, dt_s, eur_kwh_th, src.best_source)

        snap = ZoneSnapshot(
            area_id=self._area_id, area_name=self._area_name,
            preset=preset, target_temp=target_t, current_temp=current_t,
            heat_demand=heat_demand, cool_demand=cool_demand, reason=reason,
            best_source=src.best_source, source_reason=src.reason,
            cost_today=self._costs.to_dict()["today_eur"],
            cost_month=self._costs.to_dict()["month_eur"],
            stove_advice=stove_adv, preheat_min=preheat_min,
            window_open=self._window_open(data),
            entities=self._entity_states(),
            pid_info=pid_info, learning=self._learner.to_dict(),
        )
        self._last_snap = snap
        return snap

    # ── Preset-beslissing ──────────────────────────────────────────────────────
    def _decide(self, now, current_t, data, stove, src, ratio):
        if self._override_preset:
            return self._override_preset, f"Handmatig: {PRESET_NL[self._override_preset]}"
        if self._window_open(data):
            return Preset.ECO_WINDOW, "Raam open — vorstbeveiliging"
        if stove:
            return Preset.HOUTFIRE, "Houtkachel actief — TRV minimaal"
        if data.get("absence_active"):
            return Preset.AWAY, "Niemand aanwezig"
        if (data.get("sleep_detector") or {}).get("sleep_active"):
            return Preset.SLEEP, "Slaapstand actief"
        p, r = self._sched_preset(now) or (Preset.COMFORT, "Standaard comfort")
        if (data.get("capacity_peak") or {}).get("warning_active"):
            return Preset.ECO, "Kwartier-piek — eco"
        elec = float((data.get("energy_price") or {}).get("current_eur_kwh", 0.25))
        if elec < 0 and src.best_source in ("electric", "free_negative"):
            return Preset.BOOST, f"Negatief tarief {elec*100:.1f}ct"
        if src.best_source in ("free_solar",):
            return Preset.SOLAR, "Gratis zonne-energie"
        if ratio > PRICE_HIGH_RATIO and src.best_source == "gas":
            return Preset.ECO, f"Hoge stroomprijs ({ratio:.1f}x) — eco"
        return p, r

    def _sched_preset(self, now):
        active = [b for b in self._schedule if b.is_active_now(now)]
        if not active:
            return None
        b = max(active, key=lambda x: x.time_on)
        return b.preset, f"Schema {b.time_on}"

    def _next_comfort(self, now):
        for b in sorted(self._schedule, key=lambda x: x.time_on):
            if b.preset in (Preset.COMFORT, Preset.BOOST):
                h, m = map(int, b.time_on.split(":"))
                t = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if t > now and now.weekday() in b.weekdays:
                    return t
        return None

    # ── Sensoren ───────────────────────────────────────────────────────────────
    def _read_temp(self):
        temps = []
        for eid in self._entities:
            st = self._hass.states.get(eid)
            if st:
                t = st.attributes.get("current_temperature")
                if t is not None:
                    try:
                        temps.append(float(t))
                    except (ValueError, TypeError):
                        pass
        if temps:
            avg = sum(temps) / len(temps)
            self._last_temp = round(avg, 1)
            return self._last_temp
        return self._last_temp

    def _is_heating(self):
        for eid in self._entities:
            st = self._hass.states.get(eid)
            if st and st.attributes.get("hvac_action") in ("heating", "heat"):
                return True
        return False

    def _window_open(self, data):
        for eid, val in (data.get("window_sensors") or {}).items():
            if self._area_id in eid or self._area_name.lower() in eid.lower():
                if val:
                    return True
        return False

    def _detect_stove(self, current_t, heating, data):
        if current_t is None:
            return False
        ts = time.time()
        self._stove_samples.append((ts, current_t))
        sensor = (data.get("stove_sensors") or {}).get(self._area_id)
        if sensor == "on":
            return True
        if not heating and len(self._stove_samples) >= 6:
            old = self._stove_samples[0]
            dt_m = (ts - old[0]) / 60
            if dt_m > 4:
                rise = (current_t - old[1]) / dt_m
                sp = self._temps[self._preset]
                if rise > 0.12 or (current_t > sp + 2.5 and rise > 0):
                    return True
        return False

    def _needs_heat(self, current_t, target_t, source):
        if current_t is None:
            return False
        return current_t < (target_t - CV_DEADBAND_K)

    def _needs_cool(self, current_t, target_t, preset):
        if current_t is None or preset in (Preset.BOOST, Preset.HOUTFIRE):
            return False
        has_ac = any(r == DeviceRole.AIRCO for r in self._entities.values())
        return has_ac and current_t > (target_t + 1.0)

    def _entity_states(self):
        out = []
        for eid, role in self._entities.items():
            st = self._hass.states.get(eid)
            if st:
                out.append({
                    "entity_id":    eid,
                    "role":         role.value,
                    "current_temp": st.attributes.get("current_temperature"),
                    "target_temp":  st.attributes.get("temperature"),
                    "hvac_action":  st.attributes.get("hvac_action"),
                    "hvac_mode":    st.state,
                })
        return out

    # ── Entiteiten aansturen ───────────────────────────────────────────────────
    async def _drive(self, target_t, heat, cool, preset, source):
        for eid, role in self._entities.items():
            st = self._hass.states.get(eid)
            if not st:
                continue
            try:
                if role == DeviceRole.TRV:
                    await self._drive_trv(eid, st, target_t, preset)
                elif role == DeviceRole.AIRCO:
                    await self._drive_airco(eid, st, target_t, heat, cool, source)
                elif role == DeviceRole.CONVECTOR:
                    await self._drive_convector(eid, st, target_t, heat, source)
                else:
                    await self._drive_generic(eid, st, target_t, heat, cool, preset)
            except Exception as err:
                _LOGGER.warning("Zone %s: fout %s: %s", self._area_name, eid, err)

    async def _svc(self, domain, service, data):
        await self._hass.services.async_call(domain, service, data, blocking=False)

    async def _set_temp(self, eid, temp, current):
        if current is None or abs(float(current) - temp) > 0.2:
            await self._svc("climate", "set_temperature", {"entity_id": eid, "temperature": temp})

    async def _set_mode(self, eid, mode, current_mode):
        if current_mode != mode:
            await self._svc("climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": mode})

    async def _drive_trv(self, eid, st, target_t, preset):
        modes = st.attributes.get("hvac_modes", [])
        mode  = "heat" if "heat" in modes else "auto"
        t     = self._temps[preset] if preset in (Preset.AWAY, Preset.ECO_WINDOW) else target_t
        await self._set_mode(eid, mode, st.state)
        await self._set_temp(eid, t, st.attributes.get("temperature"))

    async def _drive_airco(self, eid, st, target_t, heat, cool, source):
        modes = st.attributes.get("hvac_modes", [])
        elec_ok = source in ("electric", "free_solar", "free_negative")
        if cool and "cool" in modes:
            mode = "cool"
        elif heat and elec_ok and "heat" in modes:
            mode = "heat"
        elif heat and elec_ok and "heat_cool" in modes:
            mode = "heat_cool"
        elif not heat and not cool:
            mode = "off"
        else:
            mode = st.state
        await self._set_mode(eid, mode, st.state)
        await self._set_temp(eid, target_t, st.attributes.get("temperature"))

    async def _drive_convector(self, eid, st, target_t, heat, source):
        modes = st.attributes.get("hvac_modes", [])
        use   = heat and source in ("convector", "electric", "free_solar", "free_negative")
        mode  = "heat" if use and "heat" in modes else "off"
        await self._set_mode(eid, mode, st.state)
        if use:
            await self._set_temp(eid, target_t, st.attributes.get("temperature"))

    async def _drive_generic(self, eid, st, target_t, heat, cool, preset):
        modes = st.attributes.get("hvac_modes", [])
        if cool and "cool" in modes:
            mode = "cool"
        elif heat:
            mode = "heat" if "heat" in modes else "auto"
        else:
            mode = "heat"
        t = self._temps[Preset.AWAY] if preset == Preset.AWAY else target_t
        await self._set_mode(eid, mode, st.state)
        await self._set_temp(eid, t, st.attributes.get("temperature"))

    async def async_release_devices(self) -> None:
        """
        v4.2.1: Zet alle gekoppelde climate-apparaten terug op 'auto' of 'heat'
        wanneer CloudEMS klimaatbeheer uitgeschakeld wordt.
        Voorkomt dat airco's/TRV's blijven piepen of in een ongewenste mode hangen.
        """
        for eid, role in list(self._entities.items()):
            st = self._hass.states.get(eid)
            if st is None:
                continue
            modes = st.attributes.get("hvac_modes", [])
            # Kies de meest neutrale beschikbare mode
            if "auto" in modes:
                release_mode = "auto"
            elif "heat_cool" in modes:
                release_mode = "heat_cool"
            elif "heat" in modes:
                release_mode = "heat"
            else:
                continue  # Geen known mode — niet aanraken
            if st.state != release_mode:
                try:
                    await self._svc("climate", "set_hvac_mode",
                                    {"entity_id": eid, "hvac_mode": release_mode})
                    _LOGGER.info("CloudEMS release: %s → %s (module uitgeschakeld)", eid, release_mode)
                except Exception as err:
                    _LOGGER.warning("CloudEMS release: fout bij %s: %s", eid, err)

    # ── Persistentie & attributen ──────────────────────────────────────────────
    def to_save(self):
        return {
            "temps":    {p.value: t for p, t in self._temps.items()},
            "schedule": [{"weekdays": b.weekdays, "time": b.time_on,
                          "preset": b.preset.value, "temp": b.temp}
                         for b in self._schedule],
            "cost":     self._costs.to_dict(),
        }

    def load(self, d: dict):
        for k, v in d.get("temps", {}).items():
            try:
                self._temps[Preset(k)] = float(v)
            except (ValueError, KeyError):
                pass
        self._schedule = [ScheduleBlock.from_dict(b) for b in d.get("schedule", [])]
        self._costs.load(d.get("cost", {}))

    def get_attrs(self) -> dict:
        s = self._last_snap
        cost = self._costs.to_dict()
        out = {
            "area":            self._area_name,
            "preset":          s.preset.value if s else "comfort",
            "preset_nl":       PRESET_NL.get(s.preset, "") if s else "",
            "doeltemperatuur": s.target_temp if s else None,
            "huidige_temp":    s.current_temp if s else None,
            "warmtevraag":     s.heat_demand if s else False,
            "koelingsvraag":   s.cool_demand if s else False,
            "reden":           s.reason if s else "",
            "beste_bron":      s.best_source if s else "",
            "bron_uitleg":     s.source_reason if s else "",
            "kosten_vandaag":  cost["today_eur"],
            "kosten_maand":    cost["month_eur"],
            "kosten_per_bron": cost["sources"],
            "kosten_historie": cost["history"],
            "voorstook_min":   s.preheat_min if s else 0,
            "raam_open":       s.window_open if s else False,
            "leerdata":        s.learning if s else {},
            "entiteiten":      s.entities if s else [],
        }
        if s and s.stove_advice and s.stove_advice.should_light:
            out["kachel_advies"]       = s.stove_advice.reason
            out["kachel_besparing_dag"] = s.stove_advice.saving_eur_day
        return out


# ── CV-Ketel Coördinator ────────────────────────────────────────────────────────
class CVBoilerCoordinator:
    """Schakelt CV-ketel (switch.* / climate.* / input_boolean.*) op basis van zones."""

    def __init__(self, hass, config: dict):
        self._hass      = hass
        self._entity    = config.get("cv_boiler_entity", "")
        self._min_zones = int(config.get("cv_min_zones_calling", 1))
        self._min_on_s  = float(config.get("cv_min_on_minutes", 5)) * 60
        self._min_off_s = float(config.get("cv_min_off_minutes", 3)) * 60
        self._summer_c  = float(config.get("cv_summer_cutoff_c", 18.0))
        self._last_on   = 0.0
        self._last_off  = 0.0
        self._is_on     = False
        self._reason    = ""

    async def async_update(self, zones: list, outside_t) -> dict:
        if not self._entity:
            return {"boiler_on": False, "reason": "Niet geconfigureerd", "zones_calling": 0}

        now    = time.time()
        domain = self._entity.split(".")[0]

        if outside_t is not None and outside_t > self._summer_c:
            await self._switch(False, domain)
            return {"boiler_on": False,
                    "reason": f"Zomermodus ({outside_t:.0f}C > {self._summer_c:.0f}C)",
                    "zones_calling": 0}

        calling  = [z for z in zones if z.heat_demand and z.best_source in ("gas", "convector")]
        n        = len(calling)
        names    = ", ".join(z.area_name for z in calling)
        want_on  = n >= self._min_zones

        if want_on and not self._is_on and now - self._last_off < self._min_off_s:
            want_on = False
        if not want_on and self._is_on and now - self._last_on < self._min_on_s:
            want_on = True

        if want_on != self._is_on:
            await self._switch(want_on, domain)
            self._is_on = want_on
            if want_on:
                self._last_on  = now
                self._reason   = f"Aan: {n} zone(s) — {names}"
            else:
                self._last_off = now
                self._reason   = "Uit: geen warmtevraag"

        return {"boiler_on": self._is_on, "reason": self._reason, "zones_calling": n, "zones": names}

    async def _switch(self, on: bool, domain: str):
        try:
            if domain in ("switch", "input_boolean"):
                svc = "turn_on" if on else "turn_off"
                await self._hass.services.async_call(domain, svc, {"entity_id": self._entity}, blocking=False)
            elif domain == "climate":
                await self._hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": self._entity, "hvac_mode": "heat" if on else "off"},
                    blocking=False,
                )
        except Exception as err:
            _LOGGER.error("CVBoiler: fout bij schakelen %s: %s", self._entity, err)


# ── Auto-Discovery ──────────────────────────────────────────────────────────────
async def async_discover_zones(hass) -> list:
    """Maak automatisch VirtualZone-objecten op basis van HA Area Registry."""
    try:
        from homeassistant.helpers import (
            area_registry as ar_mod,
            entity_registry as er_mod,
            device_registry as dr_mod,
        )
        area_reg   = ar_mod.async_get(hass)
        entity_reg = er_mod.async_get(hass)
        dev_reg    = dr_mod.async_get(hass)
    except Exception as err:
        _LOGGER.warning("Zone discovery: registries niet beschikbaar: %s", err)
        return []

    areas = {a.id: a.name for a in area_reg.async_list_areas()}
    zones: dict = {}

    # Platforms die virtuele/scheduling climate entities maken — never opnemen als fysiek apparaat
    _VIRTUAL_PLATFORMS = frozenset({
        "cloudems",           # eigen entities — voorkomt discovery-loop
        "climate_scheduler",  # Climate Scheduler integratie
        "scheduler",          # Scheduler card
        "generic_thermostat", # HA generieke thermostaat (virtueel)
        "climate_template",   # Template climate (virtueel)
    })
    # Entity_id patronen die op virtuele/scheduling entities wijzen
    _VIRTUAL_PATTERNS = ("climate_schedule", "climate_scheduler", "_schedule_", "_scheduler_")

    for entry in entity_reg.entities.values():
        if entry.domain != "climate" or entry.disabled:
            continue
        # Save virtuele platforms over
        if (entry.platform or "") in _VIRTUAL_PLATFORMS:
            continue
        # Save entities over waarvan de entity_id op een scheduler/schedule wijst
        eid_lower = entry.entity_id.lower()
        if any(pat in eid_lower for pat in _VIRTUAL_PATTERNS):
            _LOGGER.debug("Zone discovery: sla virtual/scheduler entity over: %s", entry.entity_id)
            continue

        area_id = entry.area_id
        if not area_id and entry.device_id:
            dev = dev_reg.async_get(entry.device_id)
            if dev:
                area_id = dev.area_id

        if not area_id or area_id not in areas:
            continue

        if area_id not in zones:
            # Store de volledige area entry voor floor_id toegang in climate.py
            area_entry = area_reg.async_get_area(area_id)
            zone = VirtualZone(hass, area_id, areas[area_id])
            zone._area_entry = area_entry  # v4.2.1: voor floor_id in entity slug
            zones[area_id] = zone

        st       = hass.states.get(entry.entity_id)
        platform = entry.platform or ""
        role     = classify_entity(entry.entity_id, st, platform) if st else DeviceRole.UNKNOWN
        zones[area_id].add_entity(entry.entity_id, role)
        _LOGGER.info("Zone '%s': %s -> %s", areas[area_id], entry.entity_id, role.value)

    _LOGGER.info("Zone discovery: %d zones, %d entiteiten totaal",
                 len(zones), sum(len(z._entities) for z in zones.values()))
    return list(zones.values())


# ── Top-level manager ───────────────────────────────────────────────────────────
class ZoneClimateManager:
    """Coördineert alle zones en de CV-ketel. Aanroepen vanuit coordinator."""

    def __init__(self, hass, config: dict):
        self._hass   = hass
        self._config = config
        self._zones: list  = []
        self._boiler       = None
        self._store        = None
        self._ready        = False
        self._save_ts      = 0.0

    async def async_setup(self):
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, SAVE_VERSION, SAVE_KEY)

        # Auto-discover via HA areas
        self._zones = await async_discover_zones(self._hass)

        # Handmatig geconfigureerde zones aanvullen/toevoegen
        for zcfg in self._config.get("climate_zones", []):
            aid  = zcfg.get("area_id") or zcfg.get("zone_name", "manual").lower().replace(" ", "_")
            zone = self._find(aid)
            if not zone:
                zone = VirtualZone(self._hass, aid, zcfg.get("zone_name", aid))
                self._zones.append(zone)
            for eid in zcfg.get("zone_climate_entities", []):
                st   = self._hass.states.get(eid)
                role = classify_entity(eid, st, "") if st else DeviceRole.UNKNOWN
                zone.add_entity(eid, role)
            for p in Preset:
                key = f"temp_{p.value}"
                if key in zcfg:
                    zone.set_temp(p, float(zcfg[key]))
            if "schedule" in zcfg:
                zone.set_schedule(zcfg["schedule"])

        # CV-ketel
        if self._config.get("cv_boiler_entity"):
            self._boiler = CVBoilerCoordinator(self._hass, self._config)

        # Load persistente data
        saved = await self._store.async_load() or {}
        for z in self._zones:
            if z._area_id in saved:
                z.load(saved[z._area_id])

        self._ready = True
        _LOGGER.info("ZoneClimateManager gereed: %d zones", len(self._zones))

    async def async_update(self, data: dict) -> dict:
        if not self._ready:
            return {}

        snaps = []
        for z in self._zones:
            try:
                snaps.append(await z.async_update(data))
            except Exception as err:
                _LOGGER.error("Zone %s update fout: %s", z._area_name, err)

        boiler = {}
        if self._boiler:
            boiler = await self._boiler.async_update(snaps, data.get("outside_temp_c"))

        now = time.time()
        if now - self._save_ts > SAVE_INTERVAL_S:
            await self._store.async_save({z._area_id: z.to_save() for z in self._zones})
            self._save_ts = now

        return {
            "zones":       {s.area_id: s for s in snaps},   # v4.0.8: dict voor climate.py
            "zones_list":  [s.__dict__ for s in snaps],     # backwards compat
            "boiler":      boiler,
            "total_today": round(sum(z._costs.to_dict()["today_eur"] for z in self._zones), 2),
            "total_month": round(sum(z._costs.to_dict()["month_eur"] for z in self._zones), 2),
        }

    def _find(self, area_id_or_name: str):
        for z in self._zones:
            if z._area_id == area_id_or_name or z._area_name.lower() == area_id_or_name.lower():
                return z
        return None

    def get_zone_attrs(self) -> list:
        return [z.get_attrs() for z in self._zones]

    def set_override(self, area_id: str, preset: str, hours: float = 4.0) -> bool:
        z = self._find(area_id)
        if not z:
            return False
        try:
            z.set_override(Preset(preset), hours)
            return True
        except ValueError:
            return False

    def set_schedule(self, area_id: str, blocks: list) -> bool:
        z = self._find(area_id)
        if z:
            z.set_schedule(blocks)
            return True
        return False

    def set_temp(self, area_id: str, preset: str, temp: float) -> bool:
        z = self._find(area_id)
        if not z:
            return False
        try:
            z.set_temp(Preset(preset), temp)
            return True
        except ValueError:
            return False
