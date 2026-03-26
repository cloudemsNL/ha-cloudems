# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Slim Multi-Zone Klimaatbeheer (v2.6).

Architectuur
============
  ZoneController  (één per kamer/zone)
  ├── PID              verfijnt setpoint op basis van temperatuurafwijking
  ├── PredictiveStart  berekent start via geleerde verwarmingssnelheid
  ├── Schedule         tijdgebaseerde presets
  ├── WindowDetect     halt bij raam open
  ├── PresenceDetect   eco bij afwezigheid
  └── WoodStoveDetect  VOLLEDIG ZELF-LEREND
                       Leert: baseline koud, branddrempel, afkoelcurve
                       PID:   voorspelt bijegtijdstip

  CVBoilerCoordinator
  ├── Aggregeert warmtevraag van alle CV-zones
  ├── Schakelt boiler-entiteit (switch.* of climate.* — auto-detect)
  ├── Min aan/uit tijden
  └── Zomermodus

Preset prioriteit (hoog naar laag):
  1. Handmatige override
  2. Raam open     -> eco_window
  3. Houtkachel    -> houtfire
  4. Afwezig       -> away
  5. Slaapstand    -> sleep
  6. Weekschema    -> tijdblok-preset
  7. Piekbewaker   -> eco
  8. Negatief tarief -> boost
  9. Zonne-overschot -> solar
 10. Hoge prijs    -> eco
 11. Pre-heat      -> comfort
 12. Standaard     -> comfort

Copyright 2025 CloudEMS
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
from .zone_presence import ZonePresenceManager, Aanwezigheid
from .zone_driver import ZoneEntityDriver
from .vtherm_bridge import VThermBridge, VThermStateReader

_LOGGER = logging.getLogger(__name__)

# Presets
class Preset(str, Enum):
    COMFORT    = "comfort"
    ECO        = "eco"
    BOOST      = "boost"
    SLEEP      = "sleep"
    AWAY       = "away"
    SOLAR      = "solar"
    HOUTFIRE   = "houtfire"
    ECO_WINDOW = "eco_window"
    FROST      = "frost"      # VTherm vorstbeveiliging (strenger dan away)
    ACTIVITY   = "activity"   # VTherm bewegingsdetectie preset

DEFAULT_TEMPS = {
    Preset.COMFORT:    20.0,
    Preset.ECO:        17.5,
    Preset.BOOST:      22.0,
    Preset.SLEEP:      15.5,
    Preset.AWAY:       14.0,
    Preset.SOLAR:      21.0,
    Preset.HOUTFIRE:   16.0,
    Preset.ECO_WINDOW: 14.0,
    Preset.FROST:      8.0,
    Preset.ACTIVITY:   20.5,
}

PRESET_NL = {
    Preset.COMFORT:    "Comfort",
    Preset.ECO:        "Eco",
    Preset.BOOST:      "Boost",
    Preset.SLEEP:      "Slaap",
    Preset.AWAY:       "Afwezig",
    Preset.SOLAR:      "Zonne",
    Preset.HOUTFIRE:   "Houtkachel",
    Preset.ECO_WINDOW: "Raam open",
    Preset.FROST:      "Vorstbeveiliging",
    Preset.ACTIVITY:   "Beweging",
}

OVERRIDE_TIMEOUT_H  = 4
PRICE_HIGH_RATIO    = 1.40
PRICE_PREHEAT_RATIO = 0.65
SOLAR_SURPLUS_W     = 800


class WoodStoveDetector:
    """Houtkachel detectie + hout-bijleg adviseur, volledig zelf-lerend.

    De gebruiker geeft aan dat er een houtkachel is (zone_has_wood_stove=True).
    Optioneel: koppel een temperatuursensor naast de kachel (rookpijp of
    kachelmantal, bv. Xiaomi LYWSD03, Shelly BLU HT, DS18B20 via ESPHome).

    Geen vaste drempelwaarden. Alles wordt geleerd:

      idle_ema   - EMA van lage kacheltemperaturen (= koud baseline)
                   alpha=0.02 (traag, koudtoestand verandert nauwelijks)

      delta_ema  - EMA van (peak - baseline) per brandcyclus
                   Branddrempel = baseline + 0.6 * delta
                   alpha=0.20

      decay_ema  - EMA van gemeten afkoelsnelheid K/min
                   Wordt nauwkeuriger na elke cyclus
                   alpha=0.15

      PID        - setpoint = geleerde branddrempel
                   meting   = huidige kacheltemperatuur
                   output   = gekalibreerde minuten tot hout nodig
                   output_max wordt bijgesteld op basis van decay_ema

    Statusmachine: idle / opstoken / brandend / dalend / kritiek
    """

    _ALPHA_BASELINE = 0.02
    _ALPHA_DECAY    = 0.15
    _ALPHA_DELTA    = 0.20
    _MIN_CYCLES_RELIABLE = 5

    def __init__(self, sensor_entity: Optional[str]) -> None:
        self._sensor = sensor_entity

        # Geleerde waarden
        self._idle_ema:  Optional[float] = None
        self._delta_ema: Optional[float] = None
        self._decay_ema: Optional[float] = None
        self._cycles: int = 0

        # State
        self._state       = "idle"
        self._peak_temp: Optional[float] = None
        self._prev_temp: Optional[float] = None
        self._prev_ts: float = 0.0
        self._minutes_to_refill: float = 0.0

        self._pid = PIDController(
            kp=4.0, ki=0.3, kd=0.8,
            setpoint=80.0,
            output_min=0.0,
            output_max=90.0,
            deadband=1.5,
            sample_time=60.0,
            label="houtkachel_pid",
        )

    @property
    def is_burning(self) -> bool:
        return self._state in ("opstoken", "brandend", "dalend", "kritiek")

    @property
    def is_reliable(self) -> bool:
        return self._cycles >= self._MIN_CYCLES_RELIABLE

    @property
    def minutes_to_refill(self) -> float:
        return round(self._minutes_to_refill, 0)

    def _burn_threshold(self) -> Optional[float]:
        if self._idle_ema is None:
            return None
        delta = self._delta_ema if self._delta_ema is not None else 20.0
        return self._idle_ema + max(10.0, delta * 0.6)

    def update(self, hass: "HomeAssistant") -> dict:
        temp = self._read_sensor(hass)
        if temp is None:
            return self.get_status()

        now_ts    = time.time()
        threshold = self._burn_threshold()

        # Baseline leren (alleen in idle)
        if self._state == "idle":
            if self._idle_ema is None:
                self._idle_ema = temp
            elif temp <= (self._idle_ema + 8.0):
                self._idle_ema = (
                    self._ALPHA_BASELINE * temp
                    + (1 - self._ALPHA_BASELINE) * self._idle_ema
                )

        if self._state == "idle":
            if threshold is not None and temp > threshold:
                self._state     = "opstoken"
                self._peak_temp = temp

        elif self._state == "opstoken":
            if temp > (self._peak_temp or 0):
                self._peak_temp = temp
            if threshold is not None and temp > threshold:
                observed_delta = (self._peak_temp or temp) - (self._idle_ema or temp)
                if self._delta_ema is None:
                    self._delta_ema = observed_delta
                else:
                    self._delta_ema = (
                        self._ALPHA_DELTA * observed_delta
                        + (1 - self._ALPHA_DELTA) * self._delta_ema
                    )
                new_thr = self._burn_threshold()
                if new_thr:
                    self._pid.update_setpoint(new_thr)
                self._state = "brandend"

        elif self._state == "brandend":
            if threshold is not None and temp < threshold:
                self._state = "dalend"

        elif self._state in ("dalend", "kritiek"):
            # Leer afkoelsnelheid
            if self._prev_temp is not None and self._prev_ts > 0:
                dt_min = (now_ts - self._prev_ts) / 60.0
                if dt_min >= 0.5:
                    rate = (self._prev_temp - temp) / dt_min
                    if 0.02 < rate < 10.0:
                        if self._decay_ema is None:
                            self._decay_ema = rate
                        else:
                            self._decay_ema = (
                                self._ALPHA_DECAY * rate
                                + (1 - self._ALPHA_DECAY) * self._decay_ema
                            )
                        if threshold is not None and self._decay_ema > 0:
                            gap_above = max(1.0, temp - (self._idle_ema or 0))
                            self._pid.output_max = min(180.0, gap_above / self._decay_ema)

            pid_out = self._pid.compute(temp)
            if pid_out is not None:
                decay = self._decay_ema or 0.3
                gap   = max(0.0, (threshold or temp) - temp)
                phys  = gap / max(0.01, decay)
                self._minutes_to_refill = 0.5 * phys + 0.5 * pid_out

            self._state = "kritiek" if self._minutes_to_refill < 10.0 else "dalend"

            # Uitgedoofd
            if temp < (self._idle_ema or 0) + 8.0:
                self._cycles += 1
                self._state             = "idle"
                self._peak_temp         = None
                self._minutes_to_refill = 0.0
                self._pid.reset()
                _LOGGER.info(
                    "Houtkachel [%s]: cyclus %d klaar, decay %.3f K/min, drempel %.1f",
                    self._sensor, self._cycles,
                    self._decay_ema or 0.0, self._burn_threshold() or 0.0,
                )

        self._prev_temp = temp
        self._prev_ts   = now_ts
        return self.get_status()

    def _read_sensor(self, hass: "HomeAssistant") -> Optional[float]:
        if not self._sensor:
            return None
        st = hass.states.get(self._sensor)
        if not st:
            return None
        try:
            return float(st.state)
        except (ValueError, TypeError):
            return None

    def get_status(self) -> dict:
        thr = self._burn_threshold()
        return {
            "state":            self._state,
            "is_burning":       self.is_burning,
            "is_reliable":      self.is_reliable,
            "cycles_learned":   self._cycles,
            "sensor":           self._sensor,
            "idle_baseline_c":  round(self._idle_ema, 1)  if self._idle_ema  else None,
            "burn_threshold_c": round(thr, 1)              if thr             else None,
            "burn_delta_k":     round(self._delta_ema, 1)  if self._delta_ema else None,
            "decay_k_per_min":  round(self._decay_ema, 3)  if self._decay_ema else None,
            "minutes_to_refill":self.minutes_to_refill      if self.is_burning else None,
            "pid":              self._pid.to_dict(),
        }


@dataclass
class ScheduleBlock:
    weekdays: list
    time_on: str
    preset: Preset
    temp_override: Optional[float] = None

    def is_active(self, now: datetime) -> bool:
        if now.weekday() not in self.weekdays:
            return False
        h, m = map(int, self.time_on.split(":"))
        return now.hour > h or (now.hour == h and now.minute >= m)

    @staticmethod
    def from_dict(d: dict) -> "ScheduleBlock":
        return ScheduleBlock(
            weekdays=d.get("weekdays", list(range(7))),
            time_on=d.get("time", "00:00"),
            preset=Preset(d.get("preset", "comfort")),
            temp_override=d.get("temp"),
        )


class PredictiveStartScheduler:
    """Leert verwarmingssnelheid per zone en berekent pre-heat offset."""

    _ALPHA = 0.20

    def __init__(self, store=None) -> None:
        self._rate_ema: dict = {}
        self._samples:  dict = {}
        self._offsets:  dict = {}
        self._store  = store  # geïnjecteerd door SmartClimateManager
        self._dirty  = False
        self._last_save = 0.0

    def record_rate(self, zone: str, rate_k_per_min: float) -> None:
        if not (0.01 < rate_k_per_min < 5.0):
            return
        if zone not in self._rate_ema:
            self._rate_ema[zone] = rate_k_per_min
            self._samples[zone]  = 1
        else:
            self._rate_ema[zone] = (
                self._ALPHA * rate_k_per_min
                + (1 - self._ALPHA) * self._rate_ema[zone]
            )
            self._samples[zone] += 1
        self._dirty = True

    def seed_from_cop_estimate(self, zone: str, rate_k_per_min: float) -> None:
        """Zaai de COP-gebaseerde prior voor zones zonder meetdata.

        Wordt alleen toegepast als de zone nog geen echte metingen heeft,
        zodat geleerde waarden nooit worden overschreven.
        """
        if zone not in self._rate_ema or self._samples.get(zone, 0) == 0:
            if 0.01 < rate_k_per_min < 5.0:
                self._rate_ema[zone] = rate_k_per_min
                self._samples[zone]  = 0   # 0 = seed, nog geen echte metingen
                _LOGGER.debug(
                    "PredictiveStart: COP-seed voor zone '%s' → %.3f K/min",
                    zone, rate_k_per_min,
                )

    def calc_offset_min(self, zone: str, current_temp: float, target_temp: float) -> int:
        delta = target_temp - current_temp
        if delta <= 0:
            return 0
        rate   = self._rate_ema.get(zone, 0.20)
        offset = int(delta / max(0.01, rate))
        offset = max(5, min(120, offset))
        self._offsets[zone] = offset
        return offset

    def should_start_now(
        self, zone: str, target_dt: datetime, current_temp: float, target_temp: float
    ) -> bool:
        offset = self.calc_offset_min(zone, current_temp, target_temp)
        return datetime.now(timezone.utc) >= (target_dt - timedelta(minutes=offset))

    def get_status(self) -> dict:
        return {
            z: {
                "rate_k_min": round(r, 3),
                "samples":    self._samples.get(z, 0),
                "offset_min": self._offsets.get(z, 0),
            }
            for z, r in self._rate_ema.items()
        }

    def load_from_dict(self, data: dict) -> None:
        """Herstel geleerde opwarmsnelheden na herstart."""
        self._rate_ema = {k: float(v) for k, v in data.get("rate_ema", {}).items()}
        self._samples  = {k: int(v)   for k, v in data.get("samples",  {}).items()}

    def to_dict(self) -> dict:
        return {"rate_ema": self._rate_ema, "samples": self._samples}

    async def async_maybe_save(self) -> None:
        import time as _t
        if not self._store or not self._dirty:
            return
        if _t.time() - self._last_save < 600:
            return
        try:
            await self._store.async_save(self.to_dict())
            self._dirty = False
            self._last_save = _t.time()
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("PredictiveStartScheduler: opslaan mislukt: %s", exc)


@dataclass
class ZoneStatus:
    name:          str
    preset:        Preset
    target_temp:   float
    current_temp:  Optional[float]
    heat_demand:   bool
    cool_demand:   bool
    reason:        str
    window_open:   bool      = False
    stove_active:  bool      = False
    override_active: bool    = False
    pid_output:    float     = 0.0
    entities:      list      = field(default_factory=list)
    heating_type:  str       = "cv"


class ZoneController:
    """Beheert één klimaatzone — virtuele thermostaat.

    Stuurt TRV's, Versatile Thermostat, airco en schakelaars aan via
    ZoneEntityDriver (auto-detectie per entiteit).

    Aanwezigheid via ZonePresenceManager (3 lagen):
      1. Person/device trackers  (real-time)
      2. HA/Google Kalender      (gepland)
      3. Zelf-lerend patroon     (historisch)
    """

    def __init__(self, hass: "HomeAssistant", cfg: dict) -> None:
        self._hass = hass
        self._name = cfg.get("zone_name", "onbekend")

        entity_ids           = cfg.get("zone_climate_entities", [])
        # Externe temperatuursensoren — één string of lijst
        _ts = cfg.get("zone_temp_sensor") or cfg.get("zone_temp_sensors")
        if isinstance(_ts, str) and _ts:
            self._temp_sensors: list[str] = [_ts]
        elif isinstance(_ts, list):
            self._temp_sensors = [s for s in _ts if s]
        else:
            self._temp_sensors = []
        # backwards compat
        self._temp_sensor = self._temp_sensors[0] if self._temp_sensors else None
        self._window_sensor  = cfg.get("zone_window_sensor")
        self._heating_type   = cfg.get("zone_heating_type", "cv")
        self._has_stove      = bool(cfg.get("zone_has_wood_stove", False))

        # Preset-temperaturen
        self._temps = {
            p: float(cfg.get(f"temp_{p.value}", DEFAULT_TEMPS[p]))
            for p in Preset
        }

        # Schedule
        self._schedule = [ScheduleBlock.from_dict(b) for b in cfg.get("schedule", [])]

        # Houtkachel
        stove_sensor = cfg.get("zone_stove_sensor") if self._has_stove else None
        self._stove  = WoodStoveDetector(stove_sensor) if self._has_stove else None

        # Aanwezigheid (3 lagen)
        self._presence = ZonePresenceManager(hass, cfg)

        # Entiteit driver (auto-detectie VT / TRV / airco / switch)
        self._driver = ZoneEntityDriver(
            zone_name=self._name,
            entity_ids=entity_ids,
            vt_preset_map=cfg.get("zone_vt_preset_map"),
            entity_type_overrides=cfg.get("zone_entity_types"),
        )

        # VTherm bridge reference (wordt ingesteld door SmartClimateManager)
        self._vtherm_bridge: Optional["VThermBridge"] = None
        # Alle climate-entiteiten (voor _read_temp fallback)
        self._climate_entities = [e for e in entity_ids if e.startswith("climate.")]

        # PID — setpoint in °C
        self._pid = PIDController(
            kp=1.2, ki=0.08, kd=0.3,
            setpoint=self._temps[Preset.COMFORT],
            output_min=self._temps[Preset.AWAY],
            output_max=self._temps[Preset.BOOST],
            deadband=0.2,
            sample_time=120.0,
            label=f"zone_{self._name}",
        )

        # State
        self._current_preset:  Preset              = Preset.COMFORT
        self._override_preset: Optional[Preset]    = None
        self._override_until:  Optional[datetime]  = None
        self._last_temp:       Optional[float]     = None
        self._last_temp_ts:    float               = 0.0
        self._temp_source:     str                 = "onbekend"

    @property
    def name(self) -> str:
        return self._name

    @property
    def heating_type(self) -> str:
        return self._heating_type

    def set_override(self, preset: Preset, hours: float = OVERRIDE_TIMEOUT_H) -> None:
        self._override_preset = preset
        self._override_until  = datetime.now(timezone.utc) + timedelta(hours=hours)

    def clear_override(self) -> None:
        self._override_preset = None
        self._override_until  = None

    async def async_update(
        self,
        data: dict,
        predictive: PredictiveStartScheduler,
        global_hint: Optional[Preset] = None,
    ) -> ZoneStatus:
        now = datetime.now(timezone.utc)

        if self._override_until and now > self._override_until:
            self.clear_override()

        # ── VTherm bridge update (lees alle rijke VTherm-attributen) ──────────
        entity_ids = self._driver._entity_ids
        if self._vtherm_bridge:
            self._vtherm_bridge.update_zone(self._name, entity_ids)

        current_temp  = self._read_temp()
        outside_temp  = data.get("outside_temp_c")

        # Aanwezigheid evalueren (alle 3 lagen)
        aanwezigheid = self._presence.evaluate(self._hass)

        # Houtkachel
        stove_active = False
        if self._stove:
            st = self._stove.update(self._hass)
            stove_active = st.get("is_burning", False)

        # Verwarmingsrate leren:
        # Gebruik VTherm slope als die beschikbaar is (nauwkeuriger dan eigen berekening)
        vtherm_slope = None
        if self._vtherm_bridge:
            vtherm_slope = self._vtherm_bridge.get_zone_slope(self._name)

        if vtherm_slope is not None:
            # VTherm levert slope in °C/uur → omzetten naar °C/min voor predictive
            rate_per_min = vtherm_slope / 60.0
            if abs(rate_per_min) > 0.001:
                predictive.record_rate(self._name, rate_per_min)
        elif (current_temp and self._last_temp and self._last_temp_ts > 0
                and self._any_entity_heating()):
            dt_min = (time.time() - self._last_temp_ts) / 60.0
            if dt_min > 0.5:
                rate = (current_temp - self._last_temp) / dt_min
                predictive.record_rate(self._name, rate)

        preset, reason = self._decide_preset(
            now, current_temp, data, stove_active,
            aanwezigheid, global_hint, predictive
        )
        self._current_preset = preset
        target_temp = self._temps.get(preset, self._temps[Preset.COMFORT])

        # Kalender boost-hint → tijdelijk naar boost preset
        if self._presence.calendar_boost_hint and preset == Preset.COMFORT:
            preset     = Preset.BOOST
            target_temp= self._temps[Preset.BOOST]
            reason    += " + gasten (kalender)"

        # v4.5.118: Preheat/reduce offset op basis van stroomprijs
        _preheat_off = float(data.get("preheat_offset_c", 0.0))
        _preheat_mode= data.get("preheat_mode", "normal")
        if _preheat_off != 0.0 and preset in (Preset.COMFORT, Preset.BOOST, Preset.SOLAR, Preset.ACTIVITY):
            _boost_max = self._temps.get(Preset.BOOST, 22.0)
            _away_min  = self._temps.get(Preset.AWAY, 14.0)
            target_temp = round(max(_away_min, min(_boost_max, target_temp + _preheat_off)), 1)
            reason += f" + {'voorverwarmen' if _preheat_off > 0 else 'besparen'} {_preheat_off:+.1f}°C (prijs)"

        # PID verfijning bij bewoonbare presets
        pid_output = 0.0
        if (preset in (Preset.COMFORT, Preset.ECO, Preset.BOOST,
                       Preset.SOLAR, Preset.ACTIVITY)
                and current_temp is not None):
            self._pid.update_setpoint(target_temp)
            result = self._pid.compute(current_temp)
            if result is not None:
                pid_output  = result
                target_temp = round(
                    max(self._temps.get(Preset.AWAY, 14.0),
                        min(self._temps.get(Preset.BOOST, 22.0), result)), 1
                )

        heat_demand = self._calc_heat_demand(current_temp, target_temp)
        cool_demand = self._calc_cool_demand(current_temp, target_temp, preset)

        # Stuur alle entiteiten aan via driver
        entities = await self._driver.async_apply(
            self._hass, preset.value, target_temp,
            heat_demand, cool_demand, outside_temp
        )

        return ZoneStatus(
            name=self._name, preset=preset, target_temp=target_temp,
            current_temp=current_temp, heat_demand=heat_demand,
            cool_demand=cool_demand, reason=reason,
            window_open=self._is_window_open(), stove_active=stove_active,
            override_active=self._override_preset is not None,
            pid_output=pid_output, entities=entities,
            heating_type=self._heating_type,
        )

    def _decide_preset(self, now, current_temp, data, stove_active,
                       aanwezigheid, global_hint, predictive):
        if self._override_preset:
            return self._override_preset, f"Override ({PRESET_NL.get(self._override_preset, self._override_preset)})"

        # VTherm window state heeft prioriteit boven eigen sensor
        if self._is_window_open():
            return Preset.ECO_WINDOW, "Raam open"

        if stove_active:
            msg = "Houtkachel actief — TRV minimaal"
            if self._stove and self._stove.minutes_to_refill is not None and self._stove.minutes_to_refill < 15:
                msg += f" (hout bijleggen over ~{self._stove.minutes_to_refill:.0f} min)"
            return Preset.HOUTFIRE, msg

        # Aanwezigheid (alle 3 lagen gecombineerd)
        if aanwezigheid.status == Aanwezigheid.WEG:
            return Preset.AWAY, f"Afwezig ({aanwezigheid.bron}: {aanwezigheid.detail})"

        if data.get("sleep_detector", {}).get("sleep_active"):
            return Preset.SLEEP, "Slaapstand actief"

        schema_result = self._active_schedule_preset(now)

        if data.get("capacity_peak", {}).get("warning_active"):
            return Preset.ECO, "Kwartier-piek — eco"

        price_info    = data.get("energy_price") or {}
        current_price = float(price_info.get("current_eur_kwh") or 0)
        avg_price     = float(price_info.get("avg_today_eur_kwh") or 0.20)
        ratio = current_price / avg_price if avg_price > 0 else 1.0

        if current_price < 0:
            return Preset.BOOST, f"Negatief tarief ({current_price:.3f} EUR/kWh)"

        solar = float(data.get("solar_surplus_w") or 0)
        if solar > SOLAR_SURPLUS_W:
            return Preset.SOLAR, f"Zonne-overschot {solar:.0f} W"

        if ratio > PRICE_HIGH_RATIO:
            return Preset.ECO, f"Hoge prijs ({ratio:.1f}x gem.)"

        # VTherm motion state → activity preset
        if self._vtherm_bridge:
            summary = self._vtherm_bridge._zone_cache.get(self._name)
            if summary:
                if any(e.motion_state == "on" for e in summary.entities):
                    return Preset.ACTIVITY, "Beweging gedetecteerd (VTherm)"

        # Pre-heat via predictieve planner
        if schema_result and current_temp is not None:
            next_preset, next_time_str = schema_result
            try:
                h, m = map(int, next_time_str.split(":"))
                tgt_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if tgt_dt < now:
                    tgt_dt += timedelta(days=1)
                tgt_t = self._temps.get(next_preset, 20.0)
                if predictive.should_start_now(self._name, tgt_dt, current_temp, tgt_t):
                    off = predictive.calc_offset_min(self._name, current_temp, tgt_t)
                    return Preset.COMFORT, f"Pre-heat: schema {next_time_str} over {off} min"
            except (ValueError, AttributeError):
                pass

        if schema_result:
            p, _ = schema_result
            return p, "Schema actief"

        # Geleerd aanwezigheidspatroon als terugval
        if aanwezigheid.status == Aanwezigheid.THUIS:
            return global_hint or Preset.COMFORT, f"Comfort ({aanwezigheid.bron})"

        return global_hint or Preset.COMFORT, "Standaard comfort"

    def _active_schedule_preset(self, now: datetime):
        active = [b for b in self._schedule if b.is_active(now)]
        if not active:
            return None
        latest = max(active, key=lambda b: b.time_on)
        return latest.preset, latest.time_on

    def _read_temp(self) -> Optional[float]:
        """Lees ruimtetemperatuur — prioriteit:
        1. Externe sensor(en) via zone_temp_sensor / zone_temp_sensors
           → meerdere sensoren: gemiddelde van beschikbare waarden
        1b. VTherm EMA-temperatuur (gefilterd, nauwkeuriger dan raw TRV)
        2. current_temperature attribuut van de climate-entiteiten zelf
           → gemiddelde van alle beschikbare TRV/thermostaat readings
        3. Laatste bekende waarde (fallback bij tijdelijke uitval)
        """
        # Stap 1: externe sensoren
        ext_temps = []
        for sensor_id in self._temp_sensors:
            st = self._hass.states.get(sensor_id)
            if st and st.state not in ("unavailable", "unknown", "none", ""):
                try:
                    ext_temps.append(float(st.state))
                except (ValueError, TypeError):
                    pass
        if ext_temps:
            t = round(sum(ext_temps) / len(ext_temps), 1)
            self._last_temp    = t
            self._last_temp_ts = time.time()
            self._temp_source  = "extern"
            return t

        # Stap 1b: VTherm EMA-temperatuur (nauwkeuriger dan raw)
        if self._vtherm_bridge:
            ema = self._vtherm_bridge.get_zone_ema_temp(self._name)
            if ema is not None:
                self._last_temp    = ema
                self._last_temp_ts = time.time()
                self._temp_source  = "vtherm_ema"
                return ema

        # Stap 2: current_temperature van de climate-entiteiten
        trv_temps = []
        for eid in self._climate_entities:
            st = self._hass.states.get(eid)
            if st:
                t = st.attributes.get("current_temperature")
                if t is not None:
                    try:
                        trv_temps.append(float(t))
                    except (ValueError, TypeError):
                        pass
        if trv_temps:
            avg = round(sum(trv_temps) / len(trv_temps), 1)
            self._last_temp    = avg
            self._last_temp_ts = time.time()
            self._temp_source  = "thermostat"
            return avg

        # Stap 3: fallback naar laatste bekende waarde
        self._temp_source = "cache"
        return self._last_temp

    def _is_window_open(self) -> bool:
        """
        Detecteert raam open via 3 methodes:
        1. Eigen window sensor (binary_sensor)
        2. VTherm window detectie
        3. Automatische temperatuurval detectie (geen sensor nodig):
           als de kamertemperatuur in 5 minuten meer dan 1.5°C daalt → raam open
        """
        # Methode 1: Eigen sensor
        if self._window_sensor:
            st = self._hass.states.get(self._window_sensor)
            if st and st.state == "on":
                return True

        # Methode 2: VTherm window detectie
        if self._vtherm_bridge:
            summary = self._vtherm_bridge._zone_cache.get(self._name)
            if summary and summary.any_window_open:
                return True

        # Methode 3: Automatische temperatuurval detectie
        # Vereist geen sensor — detecteert snelle daling van kamertemperatuur
        try:
            import time as _t
            now = _t.time()
            # Haal huidige kamertemperatuur op
            cur_temp = None
            for eid in self._climate_entities:
                st = self._hass.states.get(eid)
                if st and st.attributes.get("current_temperature"):
                    cur_temp = float(st.attributes["current_temperature"])
                    break
            if cur_temp is not None:
                # Init temp history als die er niet is
                if not hasattr(self, "_temp_hist"):
                    self._temp_hist = []
                self._temp_hist.append((now, cur_temp))
                # Bewaar alleen laatste 10 minuten
                self._temp_hist = [(t, v) for t, v in self._temp_hist if now - t < 600]
                # Check: daling > 1.5°C in 5 minuten
                if len(self._temp_hist) >= 2:
                    old_samples = [(t, v) for t, v in self._temp_hist if now - t > 240]
                    if old_samples:
                        oldest_temp = old_samples[-1][1]
                        drop = oldest_temp - cur_temp
                        if drop > 1.5:
                            if not getattr(self, "_window_auto_logged", False):
                                import logging
                                logging.getLogger(__name__).info(
                                    "SmartClimate [%s]: raam open gedetecteerd via temperatuurval (%.1f°C in 5min)",
                                    self._name, drop
                                )
                                self._window_auto_logged = True
                            return True
                        else:
                            self._window_auto_logged = False
        except Exception:
            pass

        return False

    def _any_entity_heating(self) -> bool:
        # VTherm on_percent is nauwkeuriger dan hvac_action
        if self._vtherm_bridge:
            summary = self._vtherm_bridge._zone_cache.get(self._name)
            if summary:
                return summary.heat_demand

        for eid in self._climate_entities:
            st = self._hass.states.get(eid)
            if not st:
                continue
            if st.attributes.get("hvac_action") in ("heating", "heat"):
                return True
            # on_percent direct lezen als VTherm-attribuut
            on_pct = st.attributes.get("on_percent")
            if on_pct is not None and float(on_pct) > 0:
                return True
            if st.state == "heat":
                try:
                    if float(st.attributes.get("current_temperature", 99)) < \
                       float(st.attributes.get("temperature", 0)) - 0.3:
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    def _calc_heat_demand(self, current_temp, target_temp) -> bool:
        if self._heating_type not in ("cv", "both"):
            return False
        if current_temp is None:
            return False
        return current_temp < (target_temp - 0.5)

    def _calc_cool_demand(self, current_temp, target_temp, preset) -> bool:
        if self._heating_type not in ("airco", "both"):
            return False
        if current_temp is None or preset in (Preset.BOOST, Preset.HOUTFIRE):
            return False
        return current_temp > (target_temp + 0.8)

    def get_status(self) -> dict:
        vtherm_data = {}
        if self._vtherm_bridge:
            summary = self._vtherm_bridge._zone_cache.get(self._name)
            if summary:
                vtherm_data = {
                    "on_percent":         summary.mean_on_percent,
                    "slope":              summary.mean_slope,
                    "ema_temp":           summary.ema_temp,
                    "any_window_open":    summary.any_window_open,
                    "any_overpowering":   summary.any_overpowering,
                    "any_safety":         summary.any_safety,
                    "heat_demand":        summary.heat_demand,
                    "total_power_w":      summary.total_mean_cycle_power_w,
                    "entity_count":       len(summary.entities),
                }

        return {
            "name":             self._name,
            "preset":           self._current_preset.value,
            "override":         self._override_preset.value if self._override_preset else None,
            "temp":             self._last_temp,
            "temp_source":      self._temp_source,
            "temp_sensors":     self._temp_sensors,
            "stove":            self._stove.get_status() if self._stove else None,
            "presence":         self._presence.get_status(),
            "presence_heatmap": self._presence.get_heatmap(),
            "entity_types":     self._driver.get_entity_types(self._hass),
            "pid":              self._pid.to_dict(),
            "vtherm":           vtherm_data,
        }

    def set_schedule(self, blocks: list[dict]) -> None:
        self._schedule = [ScheduleBlock.from_dict(b) for b in blocks]


class CVBoilerCoordinator:
    """Schakelaar voor de CV-ketel.

    Boiler-entiteit: switch.*, input_boolean.*, of climate.*
    Type wordt automatisch gedetecteerd.
    """

    def __init__(self, hass: "HomeAssistant", cfg: dict) -> None:
        self._hass       = hass
        self._entity     = cfg.get("cv_boiler_entity", "")
        self._min_zones  = int(cfg.get("cv_min_zones_calling", 1))
        self._min_on_s   = float(cfg.get("cv_min_on_minutes", 5)) * 60
        self._min_off_s  = float(cfg.get("cv_min_off_minutes", 3)) * 60
        self._summer_c   = float(cfg.get("cv_summer_cutoff_c", 18.0))
        self._is_on      = False
        self._last_on_ts = 0.0
        self._last_off_ts= 0.0
        self._domain     = ""

    def _get_domain(self) -> str:
        if not self._domain and self._entity:
            self._domain = self._entity.split(".")[0]
        return self._domain

    async def async_update(self, zones: list, outside_temp, data: dict) -> dict:
        if not self._entity:
            return {"boiler_on": False, "reason": "Geen CV-entiteit geconfigureerd"}

        now    = time.time()
        domain = self._get_domain()

        if outside_temp is not None and outside_temp > self._summer_c:
            if self._is_on:
                await self._set_boiler(False, domain)
            return {
                "boiler_on": False,
                "reason": f"Zomermodus (buiten {outside_temp:.1f}C)",
                "zones_calling": 0,
            }

        cv_zones  = [z for z in zones if z.heating_type in ("cv", "both")]
        calling   = [z for z in cv_zones if z.heat_demand]
        n_calling = len(calling)
        want_on   = n_calling >= self._min_zones

        if want_on and not self._is_on:
            if (now - self._last_off_ts) < self._min_off_s:
                want_on = False
        if not want_on and self._is_on:
            if (now - self._last_on_ts) < self._min_on_s:
                want_on = True

        if want_on != self._is_on:
            await self._set_boiler(want_on, domain)

        names = [z.name for z in calling]
        return {
            "boiler_on":     self._is_on,
            "zones_calling": n_calling,
            "calling_zones": names,
            "reason": (
                f"{n_calling} zone(s): {', '.join(names)}"
                if n_calling else "Geen warmtevraag"
            ),
        }

    async def _set_boiler(self, on: bool, domain: str) -> None:
        try:
            if domain == "climate":
                await self._hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": self._entity, "hvac_mode": "heat" if on else "off"},
                    blocking=False,
                )
            else:
                await self._hass.services.async_call(
                    "homeassistant", "turn_on" if on else "turn_off",
                    {"entity_id": self._entity},
                    blocking=False,
                )
            self._is_on = on
            if on:
                self._last_on_ts = time.time()
            else:
                self._last_off_ts = time.time()
            _LOGGER.info("CVBoiler [%s]: %s", self._entity, "AAN" if on else "UIT")
        except Exception as err:
            _LOGGER.warning("CVBoiler: %s", err)


class SmartClimateManager:
    """Hoofdklasse — zones + CV-coördinator + VTherm Bridge.

    Gebruik vanuit coordinator:
        manager = SmartClimateManager(hass, config)
        await manager.async_setup()
        result = await manager.async_update(coordinator_data)
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass       = hass
        self._enabled    = bool(config.get("climate_mgr_enabled", False))
        self._zones: list[ZoneController]     = []
        self._boiler: Optional[CVBoilerCoordinator] = None
        self._predictive = PredictiveStartScheduler()
        self._config     = config
        # VTherm Bridge — één per manager, gedeeld door alle zones
        self._vtherm_bridge = VThermBridge(hass, config)
        # Preheat offset vanuit ClimatePreHeatAdvisor (°C, + = warmer, - = koeler)
        self._preheat_offset_c: float = 0.0
        self._preheat_mode:     str   = "normal"

    def apply_preheat_advice(self, offset_c: float, mode: str) -> None:
        """Ontvang preheat-advies vanuit ClimatePreHeatAdvisor.

        Wordt opgepakt bij de eerstvolgende async_update() zodat zones
        hun setpoints aanpassen op basis van de huidige stroomprijs.
        """
        self._preheat_offset_c = max(-3.0, min(3.0, offset_c))
        self._preheat_mode     = mode

    async def async_setup(self) -> None:
        self._vtherm_bridge.setup()
        for zc in self._config.get("climate_zones", []):
            zone = ZoneController(self._hass, zc)
            zone._vtherm_bridge = self._vtherm_bridge
            self._zones.append(zone)
        _LOGGER.info("SmartClimateManager: %d zones geladen (VTherm bridge actief)",
                     len(self._zones))
        if self._config.get("cv_boiler_entity"):
            self._boiler = CVBoilerCoordinator(self._hass, self._config)
        # v1.32: laad geleerde opwarmsnelheden na herstart
        from homeassistant.helpers.storage import Store
        _sched_store = Store(self._hass, 1, "cloudems_predictive_scheduler_v1")
        self._predictive._store = _sched_store
        try:
            _saved = await _sched_store.async_load() or {}
            if _saved:
                self._predictive.load_from_dict(_saved)
                _LOGGER.debug(
                    "PredictiveStartScheduler: %d zone-snelheden geladen",
                    len(_saved.get("rate_ema", {}))
                )
        except Exception as _exc:
            _LOGGER.warning("PredictiveStartScheduler: laden mislukt: %s", _exc)

    def teardown(self) -> None:
        self._vtherm_bridge.teardown()

    async def async_update(self, data: dict) -> dict:
        if not self._enabled or not self._zones:
            return {"enabled": False}

        # Injecteer preheat-offset in data zodat zones het kunnen gebruiken
        if self._preheat_offset_c != 0.0:
            data = dict(data)
            data["preheat_offset_c"] = self._preheat_offset_c
            data["preheat_mode"]     = self._preheat_mode

        outside_temp = data.get("outside_temp_c")
        zone_statuses = []
        for zone in self._zones:
            try:
                status = await zone.async_update(data, self._predictive)
                zone_statuses.append(status)
            except Exception as err:
                _LOGGER.error("Zone %s fout: %s", zone.name, err)

        boiler_result = {}
        # VTherm Central Boiler heeft prioriteit als beschikbaar
        vtherm_boiler = self._vtherm_bridge.read_central_boiler()
        if vtherm_boiler.get("available"):
            boiler_result = {
                "boiler_on":     vtherm_boiler["boiler_active"],
                "zones_calling": vtherm_boiler["nb_devices"],
                "total_power_w": vtherm_boiler["total_power_w"],
                "threshold_w":   vtherm_boiler["threshold_w"],
                "source":        "vtherm_central_boiler",
                "reason": (
                    f"VTherm Central Boiler — {vtherm_boiler['nb_devices']} apparaten actief"
                    if vtherm_boiler["boiler_active"] else "Geen warmtevraag (VTherm)"
                ),
            }
        elif self._boiler:
            try:
                boiler_result = await self._boiler.async_update(
                    zone_statuses, outside_temp, data
                )
                boiler_result["source"] = "cloudems_cv"
            except Exception as err:
                _LOGGER.error("CVBoiler fout: %s", err)

        return {
            "enabled":   True,
            "zones": [
                {
                    "name":        z.name,
                    "preset":      z.preset.value,
                    "target_temp": z.target_temp,
                    "current_temp":z.current_temp,
                    "heat_demand": z.heat_demand,
                    "cool_demand": z.cool_demand,
                    "stove_active":z.stove_active,
                    "window_open": z.window_open,
                    "reason":      z.reason,
                }
                for z in zone_statuses
            ],
            "boiler":     boiler_result,
            "predictive": self._predictive.get_status(),
            "vtherm":     self._vtherm_bridge.get_status(),
        }

    def get_zone(self, name: str) -> Optional[ZoneController]:
        return next((z for z in self._zones if z.name == name), None)

    def get_all_zone_status(self) -> list:
        return [z.get_status() for z in self._zones]
