# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
BatteryTemperatureEfficiencyLearner — v1.0.0

Learns the round-trip efficiency of the home battery per temperature range.
Li-ion batteries perform significantly worse at low temperatures:
  < 5°C:   ~75% efficiency (recommend: avoid charging)
  5-10°C:  ~82% efficiency
  10-15°C: ~87% efficiency
  15-20°C: ~91% efficiency
  20-25°C: ~93% efficiency (optimal)
  25-30°C: ~92% efficiency
  > 30°C:  ~90% efficiency (heat = accelerated wear)

Usage:
  - User configures sensor.battery_room_temp (thermometer in battery room)
  - Each cycle: observe temp + charge_w + discharge_w
  - Per hour: commit average efficiency per temperature bin
  - Advice: "is heating cheaper than the efficiency loss?"
  - Optional auto-control: turn climate entity on/off if battery_room_auto_heat=true

Configuration:
  battery_room_temp_sensor:    sensor.battery_room_temperature  (entity_id)
  battery_room_climate_entity: climate.battery_room             (entity_id, optional)
  battery_room_heater_w:       1500   (heater power in W, default 1500W)
  battery_room_auto_heat:      false  (true = CloudEMS controls the heater automatically)
"""
from __future__ import annotations
import logging, time, math
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

TEMP_BIN_SIZE = 5
TEMP_MIN      = -5
TEMP_MAX      = 45

# Li-ion baseline efficiency per bin (literature values)
BASELINE_EFF = {
    -5: 0.70, 0: 0.75, 5: 0.82, 10: 0.87,
    15: 0.91, 20: 0.93, 25: 0.92, 30: 0.90,
    35: 0.87, 40: 0.83,
}

MIN_SAMPLES = 3


@dataclass
class TempBin:
    ema_eff: float = 0.0
    samples: int   = 0
    last_ts: float = 0.0


@dataclass
class TempAdvice:
    current_temp_c:       float
    current_eff_pct:      float
    optimal_temp_c:       float
    optimal_eff_pct:      float
    eff_gain_pct:         float
    loss_kwh_per_hour:    float
    heat_kwh_to_optimal:  float
    heat_cost_eur:        float
    saving_eur:           float
    advice:               str
    worth_heating:        bool


class BatteryTemperatureEfficiencyLearner:
    """Learns efficiency per temperature bin and provides heating advice."""

    def __init__(self, hass, config: dict) -> None:
        self._hass           = hass
        self._temp_sensor    = config.get("battery_room_temp_sensor", "")
        self._heater_w       = float(config.get("battery_room_heater_w", 1500))
        self._climate_entity = config.get("battery_room_climate_entity", "")
        self._auto_heat      = bool(config.get("battery_room_auto_heat", False))
        self._bins: dict[int, TempBin] = {}
        self._hour_charge_wh:    float = 0.0
        self._hour_discharge_wh: float = 0.0
        self._hour_temp_sum:     float = 0.0
        self._hour_samples:      int   = 0
        self._last_hour:         int   = -1
        self._store = None

    async def async_setup(self) -> None:
        if self._temp_sensor:
            from homeassistant.helpers.storage import Store
            self._store = Store(self._hass, 1, "cloudems_battery_temp_efficiency_v1")
            await self._load()
            _LOGGER.info("BatteryTempLearner: active with sensor %s", self._temp_sensor)

    async def _load(self) -> None:
        if not self._store:
            return
        try:
            saved = await self._store.async_load()
            if saved and "bins" in saved:
                for k, v in saved["bins"].items():
                    self._bins[int(k)] = TempBin(
                        ema_eff = float(v.get("ema_eff", 0)),
                        samples = int(v.get("samples", 0)),
                        last_ts = float(v.get("last_ts", 0)),
                    )
        except Exception as e:
            _LOGGER.debug("BatteryTempLearner load error: %s", e)

    async def async_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "bins": {
                    str(k): {"ema_eff": b.ema_eff, "samples": b.samples, "last_ts": b.last_ts}
                    for k, b in self._bins.items()
                }
            })
        except Exception as e:
            _LOGGER.debug("BatteryTempLearner save error: %s", e)

    def _temp_to_bin(self, temp_c: float) -> int:
        return int(math.floor(temp_c / TEMP_BIN_SIZE) * TEMP_BIN_SIZE)

    def get_current_temp(self) -> Optional[float]:
        if not self._temp_sensor:
            return None
        try:
            state = self._hass.states.get(self._temp_sensor)
            if state and state.state not in ("unavailable", "unknown"):
                return float(state.state)
        except Exception:
            pass
        return None

    def observe(self, charge_w: float, discharge_w: float) -> None:
        """Record one measurement for hourly accumulation."""
        import datetime
        h = datetime.datetime.now().hour
        if h != self._last_hour and self._last_hour >= 0:
            self._commit_hour()
            self._hour_charge_wh = self._hour_discharge_wh = 0.0
            self._hour_temp_sum  = 0.0
            self._hour_samples   = 0
        self._last_hour = h

        temp = self.get_current_temp()
        if temp is not None:
            self._hour_temp_sum  += temp
            self._hour_samples   += 1
        tick_h = 15 / 3600
        self._hour_charge_wh    += charge_w    * tick_h
        self._hour_discharge_wh += discharge_w * tick_h

    def _commit_hour(self) -> None:
        """Commit hourly average efficiency to temperature bin."""
        if self._hour_samples < 4 or self._hour_charge_wh < 0.05:
            return
        avg_temp = self._hour_temp_sum / self._hour_samples
        eff      = min(1.0, self._hour_discharge_wh / self._hour_charge_wh)
        if eff < 0.5 or eff > 1.0:
            return

        bin_k = self._temp_to_bin(avg_temp)
        if bin_k not in self._bins:
            self._bins[bin_k] = TempBin()
        b     = self._bins[bin_k]
        alpha = 0.2 if b.samples < 10 else 0.05
        b.ema_eff = eff if b.samples == 0 else b.ema_eff * (1 - alpha) + eff * alpha
        b.samples = min(b.samples + 1, 9999)
        b.last_ts = time.time()

    def get_efficiency(self, temp_c: float) -> float:
        """Return expected efficiency at given temperature (0-1)."""
        bin_k = self._temp_to_bin(temp_c)
        if bin_k in self._bins and self._bins[bin_k].samples >= MIN_SAMPLES:
            return self._bins[bin_k].ema_eff
        return self._baseline_eff(temp_c)

    def _baseline_eff(self, temp_c: float) -> float:
        keys = sorted(BASELINE_EFF.keys())
        if temp_c <= keys[0]:  return BASELINE_EFF[keys[0]]
        if temp_c >= keys[-1]: return BASELINE_EFF[keys[-1]]
        for i in range(len(keys) - 1):
            if keys[i] <= temp_c < keys[i+1]:
                t = (temp_c - keys[i]) / (keys[i+1] - keys[i])
                return BASELINE_EFF[keys[i]] * (1-t) + BASELINE_EFF[keys[i+1]] * t
        return 0.90

    def get_advice(self, current_temp_c: float, charge_power_w: float,
                   price_eur_kwh: float, battery_capacity_kwh: float) -> TempAdvice:
        """
        Calculate whether heating the battery room is financially worthwhile.

        Logic:
          - Current temp → current eff → current loss per hour
          - Optimal temp (20°C) → optimal eff → reduced loss
          - Heating costs energy (heater_w × time_to_warm)
          - If savings > heating_cost → recommend heating
        """
        optimal_temp = 20.0
        current_eff  = self.get_efficiency(current_temp_c)
        optimal_eff  = self.get_efficiency(optimal_temp)
        eff_gain     = optimal_eff - current_eff

        charge_kwh_h   = charge_power_w / 1000
        loss_current_h = charge_kwh_h * (1 - current_eff)
        loss_optimal_h = charge_kwh_h * (1 - optimal_eff)
        saving_kwh_h   = loss_current_h - loss_optimal_h
        saving_eur_h   = saving_kwh_h * price_eur_kwh

        delta_temp    = max(0, optimal_temp - current_temp_c)
        heat_hours    = delta_temp / 6   # 6°C/hour at 1500W in typical battery room
        heat_kwh      = self._heater_w / 1000 * heat_hours
        heat_cost_eur = heat_kwh * price_eur_kwh

        benefit_hours = 4.0
        total_saving  = saving_eur_h * benefit_hours
        worth_heating = (total_saving > heat_cost_eur * 1.5
                         and current_temp_c < 18
                         and delta_temp > 2)

        if current_temp_c < 5:
            advice = (f"Warning: battery room is {current_temp_c:.0f}°C — very cold! "
                      f"Efficiency only {current_eff*100:.0f}%. Avoid charging until warmer.")
        elif worth_heating:
            advice = (f"Heat battery room from {current_temp_c:.0f}°C to {optimal_temp:.0f}°C. "
                      f"Heating cost: €{heat_cost_eur:.2f}, "
                      f"savings (4h): €{total_saving:.2f} → net €{total_saving-heat_cost_eur:.2f} benefit.")
        elif eff_gain > 0.02:
            advice = (f"Room {current_temp_c:.0f}°C → efficiency {current_eff*100:.0f}%. "
                      f"Heating saves €{total_saving:.2f} but costs €{heat_cost_eur:.2f}.")
        else:
            advice = f"Battery room {current_temp_c:.0f}°C — efficiency {current_eff*100:.0f}%, good."

        return TempAdvice(
            current_temp_c      = current_temp_c,
            current_eff_pct     = round(current_eff * 100, 1),
            optimal_temp_c      = optimal_temp,
            optimal_eff_pct     = round(optimal_eff * 100, 1),
            eff_gain_pct        = round(eff_gain * 100, 1),
            loss_kwh_per_hour   = round(loss_current_h, 3),
            heat_kwh_to_optimal = round(heat_kwh, 2),
            heat_cost_eur       = round(heat_cost_eur, 3),
            saving_eur          = round(total_saving, 3),
            advice              = advice,
            worth_heating       = worth_heating,
        )

    async def async_control_climate(self, advice: TempAdvice, auto_heat: bool,
                                    price_eur_kwh: float) -> dict:
        """
        Control climate entity when heating is worthwhile.

        Always: generate advice.
        If auto_heat=True AND worth_heating: turn heater on.
        If temperature is optimal: reset to off.
        """
        if not self._climate_entity:
            return {"action": "none", "reason": "No climate entity configured"}

        result = {"advice": advice.advice, "worth_heating": advice.worth_heating}

        if not auto_heat:
            result["action"] = "advise_only"
            result["reason"] = "Auto-heating disabled — advice only"
            return result

        if advice.worth_heating and advice.current_temp_c < 18:
            target_temp = min(advice.optimal_temp_c, 22.0)
            try:
                domain = self._climate_entity.split(".")[0]
                if domain == "climate":
                    await self._hass.services.async_call(
                        "climate", "set_temperature",
                        {"entity_id": self._climate_entity, "temperature": target_temp},
                        blocking=False,
                    )
                    await self._hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": self._climate_entity, "hvac_mode": "heat"},
                        blocking=False,
                    )
                elif domain in ("switch", "input_boolean"):
                    await self._hass.services.async_call(
                        domain, "turn_on",
                        {"entity_id": self._climate_entity},
                        blocking=False,
                    )
                result["action"]      = "heating_on"
                result["target_temp"] = target_temp
                result["reason"]      = (
                    f"Heater on → {target_temp:.0f}°C. "
                    f"Saving €{advice.saving_eur:.2f} > cost €{advice.heat_cost_eur:.2f}"
                )
                _LOGGER.info("BatteryTempLearner: heater on (%s → %.0f°C)",
                             self._climate_entity, target_temp)
            except Exception as e:
                result["action"] = "error"
                result["reason"] = f"Climate service error: {e}"

        elif advice.current_temp_c >= 20 or not advice.worth_heating:
            try:
                domain = self._climate_entity.split(".")[0]
                if domain == "climate":
                    await self._hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": self._climate_entity, "hvac_mode": "off"},
                        blocking=False,
                    )
                elif domain in ("switch", "input_boolean"):
                    await self._hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": self._climate_entity},
                        blocking=False,
                    )
                result["action"] = "heating_off"
                result["reason"] = f"Temp {advice.current_temp_c:.0f}°C OK, heater off"
            except Exception as e:
                result["action"] = "error"
                result["reason"] = f"Climate service error: {e}"
        else:
            result["action"] = "holding"
            result["reason"] = f"Temp {advice.current_temp_c:.0f}°C — waiting"

        return result

    def to_dict(self) -> dict:
        temp = self.get_current_temp()
        if temp is None:
            return {"configured": False, "reason": "No temperature sensor configured"}
        eff = self.get_efficiency(temp)
        return {
            "configured":      True,
            "temp_sensor":     self._temp_sensor,
            "current_temp_c":  round(temp, 1),
            "current_eff_pct": round(eff * 100, 1),
            "bins_learned":    len([b for b in self._bins.values() if b.samples >= MIN_SAMPLES]),
            "total_bins":      len(self._bins),
        }
