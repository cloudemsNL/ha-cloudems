# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS ClimatePreHeatAdvisor — v1.15.0.

Advises when to pre-heat the home (before expensive price windows) or reduce
heating (during high-priced hours) using the learned thermal house model.

Algorithm
---------
The advisor computes a setpoint offset in °C based on:
  1. EPEX price ratio: current / daily-average.  High ratio → reduce.
                                                  Low ratio  → pre-heat.
  2. Thermal inertia from ThermalHouseModel.w_per_k: heavier house → larger
     feasible offset (the house retains heat longer).
  3. A short prediction horizon — if a cheap hour ends in < 2h, pre-heat now.

Output
------
* mode:           "pre_heat" | "reduce" | "normal"
* setpoint_offset_c: float (+ = warmer, − = cooler)
* reason:         Dutch explanation string
* price_ratio:    current / avg (for dashboard display)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Tuning parameters
PREHEAT_RATIO    = 0.65   # trigger pre-heat if price < 65% of daily average
REDUCE_RATIO     = 1.35   # trigger reduce if price > 135% of daily average
MAX_OFFSET_C     = 3.0    # never advise more than ±3 °C
MIN_W_PER_K      = 50     # W/K below this → house has no significant thermal mass
HEAVY_W_PER_K    = 400    # W/K above this → house is very heavy, allow full offset


@dataclass
class PreHeatAdvice:
    mode:               str     # "pre_heat" | "reduce" | "normal"
    setpoint_offset_c:  float
    reason:             str
    price_ratio:        float
    w_per_k:            float
    reliable:           bool


class ClimatePreHeatAdvisor:
    """Compute pre-heat / reduce advice each coordinator tick."""

    def __init__(self):
        self._last_advice: Optional[PreHeatAdvice] = None

    def update(
        self,
        current_price:  Optional[float],
        avg_price_today: Optional[float],
        w_per_k:        Optional[float],
        thermal_reliable: bool = False,
    ) -> PreHeatAdvice:
        """Return heating advice based on current price and thermal model."""

        # Cannot advise without price data
        if current_price is None or avg_price_today is None or avg_price_today == 0:
            return PreHeatAdvice(
                mode="normal", setpoint_offset_c=0.0,
                reason="Geen prijsdata beschikbaar.",
                price_ratio=1.0, w_per_k=w_per_k or 0.0, reliable=False,
            )

        ratio = current_price / avg_price_today

        # Thermal inertia factor (0–1)
        wk = w_per_k or MIN_W_PER_K
        inertia = min(1.0, max(0.0,
            (wk - MIN_W_PER_K) / max(1, HEAVY_W_PER_K - MIN_W_PER_K)
        ))
        max_off = MAX_OFFSET_C * (0.3 + 0.7 * inertia)

        if ratio < PREHEAT_RATIO:
            offset = round(max_off * (1.0 - ratio / PREHEAT_RATIO), 1)
            offset = min(offset, max_off)
            mode   = "pre_heat"
            reason = (
                f"Goedkoop uur: prijs {current_price*100:.1f} ct/kWh "
                f"({ratio:.2f}× gemiddelde). "
                f"Verwarm {offset:.1f}°C extra voor het dure uur."
            )
        elif ratio > REDUCE_RATIO:
            offset = -round(max_off * min(1.0, (ratio - REDUCE_RATIO) / 0.5), 1)
            offset = max(offset, -max_off)
            mode   = "reduce"
            reason = (
                f"Duur uur: prijs {current_price*100:.1f} ct/kWh "
                f"({ratio:.2f}× gemiddelde). "
                f"Verlaag setpoint {abs(offset):.1f}°C om kosten te besparen."
            )
        else:
            offset = 0.0
            mode   = "normal"
            reason = f"Prijs {current_price*100:.1f} ct/kWh is normaal ({ratio:.2f}× gem.)."

        advice = PreHeatAdvice(
            mode=mode,
            setpoint_offset_c=offset,
            reason=reason,
            price_ratio=round(ratio, 3),
            w_per_k=round(wk, 1),
            reliable=thermal_reliable,
        )
        self._last_advice = advice
        return advice

    def update_cooling(
        self,
        current_price:    Optional[float],
        avg_price_today:  Optional[float],
        outdoor_temp_c:   Optional[float],
        indoor_temp_c:    Optional[float],
        cooling_setpoint: float = 24.0,
        w_per_k:          Optional[float] = None,
    ) -> PreHeatAdvice:
        """
        Pre-Cooling strategie: koel het huis extra in de ochtend met goedkope/zonneenergie
        zodat je de warmste uren doorkomt zonder dure stroom.

        Logica:
        - Als buitentemperatuur > 25°C verwacht (warm dag) EN
          prijs nu goedkoop (< 65% van daggemiddelde) EN
          kamertemperatuur nog niet te koud (<= setpoint - 1°C):
          → adviseer 1-2°C lager setpoint nu (pre-koelen)

        - Als prijs duur EN buitentemperatuur hoog:
          → adviseer setpoint verhogen (koeling beperken, huis buffert de koude)
        """
        if current_price is None or avg_price_today is None or avg_price_today == 0:
            return PreHeatAdvice(
                mode="normal", setpoint_offset_c=0.0,
                reason="Geen prijsdata beschikbaar voor pre-cooling.",
                price_ratio=1.0, w_per_k=w_per_k or 0.0, reliable=False,
            )

        ratio  = current_price / avg_price_today
        wk     = w_per_k or MIN_W_PER_K
        inertia = min(1.0, max(0.0, (wk - MIN_W_PER_K) / max(1, HEAVY_W_PER_K - MIN_W_PER_K)))
        max_off = MAX_OFFSET_C * (0.3 + 0.7 * inertia)

        is_warm_day  = outdoor_temp_c is not None and outdoor_temp_c > 22.0
        room_ok      = indoor_temp_c is None or indoor_temp_c > (cooling_setpoint - 2.0)

        if ratio < PREHEAT_RATIO and is_warm_day and room_ok:
            # Goedkoop uur + warme dag → pre-koelen
            offset = -round(min(max_off, 2.0) * (1.0 - ratio / PREHEAT_RATIO), 1)
            return PreHeatAdvice(
                mode="pre_cool",
                setpoint_offset_c=offset,
                reason=(
                    f"Pre-koelen: prijs {current_price*100:.1f}ct ({ratio:.2f}× gem.), "
                    f"buiten {outdoor_temp_c:.1f}°C. "
                    f"Setpoint {abs(offset):.1f}°C lager nu voor koele buffer later."
                ),
                price_ratio=round(ratio, 3),
                w_per_k=round(wk, 1),
                reliable=True,
            )

        if ratio > REDUCE_RATIO and is_warm_day:
            # Duur uur + warm → koeling beperken, vertrouw op thermische buffer
            offset = round(min(1.5, max_off * 0.5), 1)
            return PreHeatAdvice(
                mode="reduce_cooling",
                setpoint_offset_c=offset,
                reason=(
                    f"Duur uur ({current_price*100:.1f}ct): koeling terugschroeven "
                    f"{offset:.1f}°C. Huis buffert de opgeslagen koude."
                ),
                price_ratio=round(ratio, 3),
                w_per_k=round(wk, 1),
                reliable=True,
            )

        return PreHeatAdvice(
            mode="normal", setpoint_offset_c=0.0,
            reason=f"Geen pre-cooling actie nodig (prijs {current_price*100:.1f}ct, buiten {outdoor_temp_c or 0:.1f}°C).",
            price_ratio=round(ratio, 3),
            w_per_k=round(wk, 1),
            reliable=False,
        )

    @property
    def last_advice(self) -> Optional[PreHeatAdvice]:
        return self._last_advice
