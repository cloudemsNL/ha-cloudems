# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
HybridEVAdvisor — v1.1.0

Determines whether it is cheaper to charge a hybrid electric vehicle or
to drive on combustion fuel, based on current electricity and fuel prices.

Break-even formula:
  electric_cost_per_km  = (EPEX_price_eur_kwh × all_in_factor) / electric_km_per_kwh
  fuel_cost_per_km      = fuel_price_eur_l / fuel_km_per_l
  if fuel_cost_per_km < electric_cost_per_km → advise fuel mode

Typical break-even (NL, 2026):
  Electric: €0.25 all-in / 7 km/kWh = €0.036/km
  Petrol:   €2.05 / 13 km/L = €0.158/km
  → charging is almost always better
  → petrol wins when EPEX > ~€1.00/kWh all-in (occurs ~20–30× per year)
"""

from __future__ import annotations

import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# All-in electricity price multiplier (EPEX raw → consumer price)
# Includes network fees, taxes and VAT (NL typical: ×3.5–4×)
DEFAULT_ALLIN_FACTOR = 3.8


class HybridEVAdvisor:
    """Advises hybrid EV users on whether to charge or drive on fuel."""

    def __init__(self, config: dict) -> None:
        self._enabled            = config.get("hybrid_ev_enabled", False)
        self._electric_km_kwh    = float(config.get("hybrid_ev_electric_km_kwh", 7.0))
        self._fuel_km_l          = float(config.get("hybrid_ev_fuel_km_l", 13.0))
        self._fuel_type          = config.get("hybrid_ev_fuel_type", "petrol")
        self._allin_factor       = float(config.get("hybrid_ev_allin_factor", DEFAULT_ALLIN_FACTOR))
        self._last_result: Optional[dict] = None

    def advise(
        self,
        epex_price_eur_kwh: float,
        fuel_price_eur_l:   float,
    ) -> dict:
        """
        Calculate whether to charge or drive on fuel.

        epex_price_eur_kwh — current EPEX spot price (EUR/kWh, raw)
        fuel_price_eur_l   — current pump price for vehicle fuel (EUR/litre)
        """
        if not self._enabled:
            return {"enabled": False}

        allin_eur_kwh     = epex_price_eur_kwh * self._allin_factor
        electric_cost_km  = allin_eur_kwh / max(self._electric_km_kwh, 0.1)
        fuel_cost_km      = fuel_price_eur_l / max(self._fuel_km_l, 0.1)

        use_fuel          = fuel_cost_km < electric_cost_km
        saving_eur_100km  = (electric_cost_km - fuel_cost_km) * 100 if use_fuel else 0.0

        # Break-even EPEX price (raw)
        if self._electric_km_kwh > 0 and self._fuel_km_l > 0:
            breakeven_allin  = fuel_price_eur_l / self._fuel_km_l * self._electric_km_kwh
            breakeven_epex   = breakeven_allin / max(self._allin_factor, 0.1)
        else:
            breakeven_epex = 9999.0

        result = {
            "enabled":           True,
            "use_fuel":          use_fuel,
            "electric_cost_km":  round(electric_cost_km, 4),
            "fuel_cost_km":      round(fuel_cost_km, 4),
            "saving_eur_100km":  round(saving_eur_100km, 2),
            "breakeven_epex":    round(breakeven_epex, 4),
            "allin_eur_kwh":     round(allin_eur_kwh, 4),
            "fuel_type":         self._fuel_type,
        }
        self._last_result = result
        return result

    def get_cached(self) -> Optional[dict]:
        return self._last_result

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def has_hybrid_vehicles(self) -> bool:
        """Return True if hybrid EV module is enabled and configured."""
        return self._enabled

    def get_all_advice(
        self,
        epex_all_in_eur_kwh: float,
        benzine_eur_l: Optional[float] = None,
        diesel_eur_l: Optional[float] = None,
        soc_by_vehicle: dict = None,
    ) -> dict:
        """Coordinator-facing wrapper — maps flat kwargs to advise()."""
        fuel_price = benzine_eur_l if self._fuel_type == "petrol" else diesel_eur_l
        if fuel_price is None:
            fuel_price = 1.85  # fallback if no live price yet
        result = self.advise(
            epex_price_eur_kwh=epex_all_in_eur_kwh,
            fuel_price_eur_l=fuel_price,
        )
        return {"vehicles": [result]} if result else {}
