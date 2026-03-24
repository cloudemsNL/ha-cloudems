# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Atmospheric Heat Pump Optimizer v1.0.0

Uses outdoor temperature, air pressure and humidity to:
  1. Predict optimal defrost cycle timing
  2. Estimate current COP degradation from icing conditions
  3. Recommend best time to run intensive heating cycles

Icing conditions on outdoor unit:
  - Temperature between -5°C and +7°C (frost zone)
  - Humidity > 75%
  - Low wind speed (< 2 m/s) accelerates ice buildup

Optimal defrost window:
  - When outdoor temp rises above +3°C (natural thaw)
  - Low electricity price
  - Not during peak demand hours

Data sources:
  - HA weather entity (temperature, humidity, wind_speed, pressure)
  - EPEX price from coordinator
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Icing risk thresholds
FROST_TEMP_MIN = -8.0   # °C — below this: mostly dry frost, lower risk
FROST_TEMP_MAX = +7.0   # °C — above this: no icing
FROST_HUMIDITY = 75.0   # % — below this: lower icing risk
FROST_WIND_MAX = 3.0    # m/s — above this: wind prevents icing

# COP degradation model: icing reduces COP by ~15% at max icing conditions
COP_DEGRADE_MAX = 0.20  # 20% max degradation from icing


@dataclass
class AtmosphericConditions:
    temp_c:       float = 10.0
    humidity_pct: float = 60.0
    pressure_hpa: float = 1013.0
    wind_ms:      float = 3.0
    condition:    str   = "cloudy"


@dataclass
class HeatPumpAtmosphericAdvice:
    icing_risk:          str    # "none" | "low" | "medium" | "high"
    icing_pct:           float  # 0-100
    cop_degradation_pct: float  # estimated COP reduction
    defrost_recommended: bool
    defrost_reason:      str
    optimal_run_now:     bool
    optimal_run_reason:  str
    conditions:          dict


class AtmosphericHeatPumpOptimizer:
    """
    Optimises heat pump operation based on atmospheric conditions.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._weather_entity = config.get("weather_entity", "weather.home")

    def _read_conditions(self) -> AtmosphericConditions:
        """Read current conditions from HA weather entity."""
        state = self._hass.states.get(self._weather_entity)
        if not state:
            return AtmosphericConditions()
        attr = state.attributes
        try:
            return AtmosphericConditions(
                temp_c       = float(attr.get("temperature", 10)),
                humidity_pct = float(attr.get("humidity", 60)),
                pressure_hpa = float(attr.get("pressure", 1013)),
                wind_ms      = float(attr.get("wind_speed", 3)),
                condition    = str(state.state),
            )
        except (ValueError, TypeError):
            return AtmosphericConditions()

    def analyse(self, price_eur_kwh: float = 0.25) -> HeatPumpAtmosphericAdvice:
        """
        Analyse current atmospheric conditions for heat pump optimisation.
        """
        cond = self._read_conditions()
        hour = datetime.now().hour

        # ── Icing risk calculation ───────────────────────────────────────────
        icing_score = 0.0

        # Temperature factor (max risk at 0-3°C)
        if FROST_TEMP_MIN <= cond.temp_c <= FROST_TEMP_MAX:
            t_factor = 1.0 - abs(cond.temp_c - 2.0) / 10.0  # peak at 2°C
            icing_score += max(0, t_factor) * 40

        # Humidity factor
        if cond.humidity_pct > FROST_HUMIDITY:
            h_factor = (cond.humidity_pct - FROST_HUMIDITY) / (100 - FROST_HUMIDITY)
            icing_score += h_factor * 35

        # Wind factor (low wind = more icing)
        if cond.wind_ms < FROST_WIND_MAX:
            w_factor = 1.0 - cond.wind_ms / FROST_WIND_MAX
            icing_score += w_factor * 25

        icing_score = min(100, icing_score)

        if icing_score < 20:   icing_risk = "none"
        elif icing_score < 45: icing_risk = "low"
        elif icing_score < 70: icing_risk = "medium"
        else:                  icing_risk = "high"

        # COP degradation estimate
        cop_degrade = COP_DEGRADE_MAX * (icing_score / 100)

        # ── Defrost recommendation ───────────────────────────────────────────
        # Best defrost: temp rising above +3°C (natural assist), low price
        defrost_recommended = False
        defrost_reason      = ""

        if icing_risk in ("medium", "high"):
            if cond.temp_c >= 2.0:  # temperature allows natural assist
                if price_eur_kwh < 0.25:
                    defrost_recommended = True
                    defrost_reason = (
                        f"Ijsvorming risico {icing_score:.0f}%, "
                        f"temp {cond.temp_c:.1f}°C gunstig voor ontdooien, "
                        f"prijs laag (€{price_eur_kwh:.3f}/kWh)"
                    )
                else:
                    defrost_reason = (
                        f"Ontdooien aanbevolen maar prijs hoog (€{price_eur_kwh:.3f}). "
                        f"Wacht op goedkoper moment."
                    )
            else:
                defrost_reason = (
                    f"IJsvorming risico {icing_score:.0f}% — "
                    f"temp te laag ({cond.temp_c:.1f}°C) voor efficiënt ontdooien."
                )

        # ── Optimal run window ───────────────────────────────────────────────
        # Best to run heat pump when: high pressure (stable), temp above -3°C, cheap price
        optimal_run_now = False
        optimal_run_reason = ""

        if (cond.pressure_hpa >= 1010
                and cond.temp_c >= -3.0
                and icing_risk in ("none", "low")
                and price_eur_kwh < 0.22):
            optimal_run_now = True
            optimal_run_reason = (
                f"Gunstige omstandigheden: luchtdruk {cond.pressure_hpa:.0f} hPa, "
                f"temp {cond.temp_c:.1f}°C, prijs €{price_eur_kwh:.3f}/kWh"
            )
        elif icing_risk == "high":
            optimal_run_reason = (
                f"Hoog ijsrisico ({icing_score:.0f}%). "
                f"COP geschat {cop_degrade*100:.0f}% lager dan normaal."
            )
        else:
            optimal_run_reason = "Normale omstandigheden"

        advice = HeatPumpAtmosphericAdvice(
            icing_risk          = icing_risk,
            icing_pct           = round(icing_score, 1),
            cop_degradation_pct = round(cop_degrade * 100, 1),
            defrost_recommended = defrost_recommended,
            defrost_reason      = defrost_reason,
            optimal_run_now     = optimal_run_now,
            optimal_run_reason  = optimal_run_reason,
            conditions={
                "temp_c":       cond.temp_c,
                "humidity_pct": cond.humidity_pct,
                "pressure_hpa": cond.pressure_hpa,
                "wind_ms":      cond.wind_ms,
                "condition":    cond.condition,
            },
        )

        if icing_risk in ("medium", "high"):
            _LOGGER.info(
                "AtmosphericHP: icing risk=%s (%.0f%%), COP degrade %.0f%%",
                icing_risk, icing_score, cop_degrade * 100
            )

        return advice

    def to_dict(self, advice: HeatPumpAtmosphericAdvice) -> dict:
        return {
            "icing_risk":          advice.icing_risk,
            "icing_pct":           advice.icing_pct,
            "cop_degradation_pct": advice.cop_degradation_pct,
            "defrost_recommended": advice.defrost_recommended,
            "defrost_reason":      advice.defrost_reason,
            "optimal_run_now":     advice.optimal_run_now,
            "optimal_run_reason":  advice.optimal_run_reason,
            "conditions":          advice.conditions,
        }
