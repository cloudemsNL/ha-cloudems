# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
FuelPriceFetcher — v1.1.0

Retrieves current pump prices for motor fuels.
Supports multiple countries with country-specific data sources.

Countries supported:
  NL — CBS OData API (table 80416ned), no API key, CC-BY 4.0, weekly updates
  DE — BAFA / MWE (stub, extend as needed)
  BE — CREG (stub)
  Other — uses configurable fallback price

Generator break-even analysis:
  Given the fuel price and generator efficiency (kWh/L), the module calculates
  the cost per kWh of self-generating. This is compared with the current EPEX
  price to decide whether running the generator is economically worthwhile.

  Typical values:
    Diesel:  ~3.2 kWh/L (small generator <5kW) to 4.0 kWh/L (large diesel)
    Petrol:  ~2.5 kWh/L
    LPG:     ~2.8 kWh/L

  If EPEX_price > generator_cost_per_kwh × margin → advise: self-generate
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# NL: CBS OData endpoint
CBS_NL_URL       = "https://opendata.cbs.nl/ODataApi/OData/80416ned/TypedDataSet"
FETCH_INTERVAL_S = 86_400   # fetch once per day (CBS publishes weekly)
BREAKEVEN_MARGIN = 1.05     # generator may be 5% more expensive than grid

# CBS table codes
CBS_DIESEL  = "A047219"
CBS_PETROL  = "A047220"  # Euro95
CBS_LPG     = "A047221"

# Typical generator efficiencies in kWh per litre of fuel
DEFAULT_EFFICIENCY = {
    "diesel":    3.5,
    "petrol":    2.5,
    "lpg":       2.8,
    "natural_gas": 3.0,  # kWh/m³
}

# Fallback prices per country (EUR/litre) when API is unavailable
FALLBACK_PRICES: dict[str, dict] = {
    "NL": {"diesel": 1.85, "petrol": 2.05, "lpg": 1.00},
    "DE": {"diesel": 1.75, "petrol": 1.95, "lpg": 0.95},
    "BE": {"diesel": 1.80, "petrol": 2.00, "lpg": 0.98},
    "FR": {"diesel": 1.78, "petrol": 1.90, "lpg": 0.95},
    "GB": {"diesel": 1.65, "petrol": 1.58, "lpg": 0.75},
}


class FuelPriceFetcher:
    """Fetches fuel prices and calculates generator break-even cost."""

    def __init__(self, hass, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._session = None

        # Cached prices (EUR/litre)
        self._diesel_eur_l_val:  Optional[float] = None
        self._petrol_eur_l:  Optional[float] = None
        self._lpg_eur_l:     Optional[float] = None
        self._price_date:    str = ""
        self._last_fetch:    float = 0.0
        self._fetch_errors:  int = 0

        # Generator configuration
        self._gen_fuel_type:   str   = "diesel"
        self._gen_efficiency:  float = 3.5   # kWh/litre
        self._gen_enabled:     bool  = False
        self._country:         str   = "NL"

    async def async_setup(self) -> None:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)
        self._gen_enabled    = self._config.get("generator_enabled", False)
        self._gen_fuel_type  = self._config.get("generator_fuel_type", "diesel")
        self._gen_efficiency = float(self._config.get("generator_efficiency_kwh_l", 3.5))
        self._country        = self._config.get("country", "NL").upper()
        # Seed with fallback prices immediately
        fb = FALLBACK_PRICES.get(self._country, FALLBACK_PRICES["NL"])
        self._diesel_eur_l_val = fb["diesel"]
        self._petrol_eur_l = fb["petrol"]
        self._lpg_eur_l    = fb["lpg"]

    async def async_update(self, epex_price_eur_kwh: float) -> dict:
        """Fetch latest prices and return generator break-even analysis."""
        now = time.time()
        if now - self._last_fetch > FETCH_INTERVAL_S:
            await self._fetch_prices()
            self._last_fetch = now
        return self._build_result(epex_price_eur_kwh)

    async def _fetch_prices(self) -> None:
        if self._country == "NL":
            await self._fetch_nl_cbs()
        else:
            # For other countries, use fallback until specific APIs are added
            _LOGGER.debug("FuelPriceFetcher: no live API for country=%s, using fallback", self._country)

    async def _fetch_nl_cbs(self) -> None:
        """Fetch Dutch fuel prices from CBS OData API."""
        if not self._session:
            return
        try:
            params = {
                "$select": f"Perioden,{CBS_DIESEL},{CBS_PETROL},{CBS_LPG}",
                "$orderby": "Perioden desc",
                "$top": "1",
                "$format": "json",
            }
            async with self._session.get(CBS_NL_URL, params=params, timeout=10) as r:
                if r.status != 200:
                    _LOGGER.warning("FuelPriceFetcher: CBS returned HTTP %s", r.status)
                    return
                data = await r.json()
                rows = data.get("value", [])
                if not rows:
                    return
                row = rows[0]
                def _to_float(v):
                    try:
                        return float(str(v).replace(",", "."))
                    except (TypeError, ValueError):
                        return None
                d = _to_float(row.get(CBS_DIESEL))
                p = _to_float(row.get(CBS_PETROL))
                l = _to_float(row.get(CBS_LPG))
                if d:
                    self._diesel_eur_l_val = d
                if p:
                    self._petrol_eur_l = p
                if l:
                    self._lpg_eur_l = l
                self._price_date   = str(row.get("Perioden", ""))
                self._fetch_errors = 0
                _LOGGER.debug("FuelPriceFetcher NL: diesel=%.3f petrol=%.3f lpg=%.3f",
                              self._diesel_eur_l_val or 0, self._petrol_eur_l or 0, self._lpg_eur_l or 0)
        except Exception as exc:
            self._fetch_errors += 1
            _LOGGER.warning("FuelPriceFetcher: fetch error (%s)", exc)

    def _build_result(self, epex_price_eur_kwh: float) -> dict:
        """Build break-even analysis result."""
        # Select active fuel price
        fuel_price = {
            "diesel": self._diesel_eur_l_val,
            "petrol": self._petrol_eur_l,
            "lpg":    self._lpg_eur_l,
        }.get(self._gen_fuel_type, self._diesel_eur_l) or 1.90

        efficiency = DEFAULT_EFFICIENCY.get(self._gen_fuel_type, self._gen_efficiency)
        gen_cost_per_kwh = fuel_price / efficiency

        grid_price_with_margin = epex_price_eur_kwh * BREAKEVEN_MARGIN
        run_generator = self._gen_enabled and gen_cost_per_kwh < grid_price_with_margin

        saving_eur_kwh = epex_price_eur_kwh - gen_cost_per_kwh

        return {
            "diesel_eur_l":      self._diesel_eur_l_val,
            "petrol_eur_l":      self._petrol_eur_l,
            "lpg_eur_l":         self._lpg_eur_l,
            "price_date":        self._price_date,
            "gen_cost_per_kwh":  round(gen_cost_per_kwh, 4),
            "gen_fuel_type":     self._gen_fuel_type,
            "run_generator":     run_generator,
            "saving_eur_kwh":    round(saving_eur_kwh, 4) if run_generator else 0.0,
            "country":           self._country,
            "fetch_errors":      self._fetch_errors,
        }

    @property
    def diesel_eur_l(self) -> Optional[float]:
        return self._diesel_eur_l_val

    @property
    def petrol_eur_l(self) -> Optional[float]:
        return self._petrol_eur_l

    @property
    def _benzine_eur_l(self) -> Optional[float]:
        # Backwards-compatible alias used by coordinator (NL name)
        return self._petrol_eur_l

    @property
    def _diesel_eur_l(self) -> Optional[float]:
        # Backwards-compatible alias used by coordinator
        return self._diesel_eur_l_val if hasattr(self, "_diesel_eur_l_val") else self.diesel_eur_l

    async def async_maybe_fetch(self) -> None:
        """Fetch fuel prices if cache is stale (called each coordinator cycle)."""
        now = time.monotonic()
        if now - self._last_fetch > FETCH_INTERVAL_S:
            self._last_fetch = now
            await self._hass.async_add_executor_job(self._fetch_prices)

    def get_data(self) -> dict:
        """Return current fuel price data (empty dict if not yet fetched)."""
        return self._build_result(0.0) if self._price_date else {}
