# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — VvE Energy Split v1.0.0

Splits shared solar and EV charging costs fairly across apartments
in a VvE (Vereniging van Eigenaren / homeowners association).

Use cases:
  1. Shared solar installation on apartment building roof
     → Split production credit by floor area or fixed share
  2. Shared EV charging post
     → Split cost by actual kWh charged per session per apartment
  3. Shared battery
     → Track contribution vs. draw per unit

Split methods:
  - equal:       divide evenly across all units
  - area:        proportional to floor area (m²)
  - kwh:         proportional to actual measured kWh per unit
  - fixed_pct:   configured percentage per unit (must sum to 100)

Output per unit per month:
  - solar_credit_eur:   money saved by shared solar
  - ev_cost_eur:        cost of EV charging sessions
  - battery_credit_eur: benefit from shared battery
  - net_balance_eur:    credit minus costs

Configuration:
  vve_enabled          bool
  vve_units: [
    {id, label, area_m2, fixed_pct, ev_meter_entity, submeter_entity}
  ]
  vve_solar_split_method:   "equal" | "area" | "fixed_pct"
  vve_ev_split_method:      "kwh" | "equal"
  vve_total_solar_entity:   entity for total shared solar kWh today
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class VvEUnit:
    """One apartment unit in the VvE."""
    unit_id:        str
    label:          str
    area_m2:        float = 0.0
    fixed_pct:      float = 0.0   # 0-100
    ev_meter_entity: str  = ""    # kWh meter for this unit's EV charging
    submeter_entity: str  = ""    # electricity submeter for this unit
    # Accumulated per-day
    ev_kwh_today:   float = 0.0
    sub_kwh_today:  float = 0.0


@dataclass
class VvEUnitResult:
    unit_id:          str
    label:            str
    solar_share_pct:  float = 0.0
    solar_kwh:        float = 0.0
    solar_credit_eur: float = 0.0
    ev_kwh:           float = 0.0
    ev_cost_eur:      float = 0.0
    net_eur:          float = 0.0   # positive = credit, negative = cost


@dataclass
class VvEReport:
    units:             list = field(default_factory=list)
    total_solar_kwh:   float = 0.0
    total_ev_kwh:      float = 0.0
    price_eur_kwh:     float = 0.0
    split_method:      str   = "equal"


class VvEEnergySplit:
    """
    Calculates fair energy cost and credit distribution across VvE units.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("vve_enabled", False)
        self._units:  list[VvEUnit] = []
        self._setup()

    def _setup(self) -> None:
        raw = self._config.get("vve_units") or []
        self._units = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            self._units.append(VvEUnit(
                unit_id         = item.get("id", f"unit_{len(self._units)+1}"),
                label           = item.get("label", f"Appartement {len(self._units)+1}"),
                area_m2         = float(item.get("area_m2", 0)),
                fixed_pct       = float(item.get("fixed_pct", 0)),
                ev_meter_entity = item.get("ev_meter_entity", ""),
                submeter_entity = item.get("submeter_entity", ""),
            ))
        _LOGGER.info("VvEEnergySplit: %d units configured", len(self._units))

    def update_config(self, config: dict) -> None:
        self._config  = config
        self._enabled = config.get("vve_enabled", False)
        self._setup()

    def calculate(self, price_eur_kwh: float = 0.25) -> VvEReport:
        """Calculate current split based on today's readings."""
        if not self._units:
            return VvEReport(price_eur_kwh=price_eur_kwh)

        # Read shared solar total
        solar_entity = self._config.get("vve_total_solar_entity", "")
        total_solar_kwh = self._read_kwh(solar_entity)

        # Read EV kWh per unit
        for unit in self._units:
            unit.ev_kwh_today  = self._read_kwh(unit.ev_meter_entity)
            unit.sub_kwh_today = self._read_kwh(unit.submeter_entity)

        total_ev_kwh = sum(u.ev_kwh_today for u in self._units)

        # Calculate solar shares
        solar_method = self._config.get("vve_solar_split_method", "equal")
        solar_shares = self._calculate_shares(solar_method)

        # Calculate EV cost per unit
        ev_method = self._config.get("vve_ev_split_method", "kwh")

        results = []
        for i, unit in enumerate(self._units):
            solar_share_pct = solar_shares[i]
            solar_kwh       = total_solar_kwh * solar_share_pct / 100
            solar_credit    = solar_kwh * price_eur_kwh

            # EV cost
            if ev_method == "kwh" and total_ev_kwh > 0:
                ev_kwh  = unit.ev_kwh_today
            else:
                ev_kwh  = total_ev_kwh * solar_share_pct / 100
            ev_cost = ev_kwh * price_eur_kwh

            net = solar_credit - ev_cost

            results.append(VvEUnitResult(
                unit_id          = unit.unit_id,
                label            = unit.label,
                solar_share_pct  = round(solar_share_pct, 1),
                solar_kwh        = round(solar_kwh, 3),
                solar_credit_eur = round(solar_credit, 3),
                ev_kwh           = round(ev_kwh, 3),
                ev_cost_eur      = round(ev_cost, 3),
                net_eur          = round(net, 3),
            ))

        return VvEReport(
            units          = [self._unit_to_dict(r) for r in results],
            total_solar_kwh= round(total_solar_kwh, 3),
            total_ev_kwh   = round(total_ev_kwh, 3),
            price_eur_kwh  = price_eur_kwh,
            split_method   = solar_method,
        )

    def _calculate_shares(self, method: str) -> list[float]:
        """Return list of percentage shares (sum = 100) per unit."""
        n = len(self._units)
        if n == 0:
            return []

        if method == "equal":
            return [100.0 / n] * n

        if method == "area":
            total = sum(u.area_m2 for u in self._units)
            if total <= 0:
                return [100.0 / n] * n
            return [u.area_m2 / total * 100 for u in self._units]

        if method == "fixed_pct":
            total = sum(u.fixed_pct for u in self._units)
            if total <= 0:
                return [100.0 / n] * n
            return [u.fixed_pct / total * 100 for u in self._units]

        return [100.0 / n] * n

    def _read_kwh(self, entity_id: str) -> float:
        if not entity_id:
            return 0.0
        state = self._hass.states.get(entity_id)
        if not state or state.state in ("unavailable", "unknown"):
            return 0.0
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return 0.0

    def _unit_to_dict(self, r: VvEUnitResult) -> dict:
        return {
            "unit_id":          r.unit_id,
            "label":            r.label,
            "solar_share_pct":  r.solar_share_pct,
            "solar_kwh":        r.solar_kwh,
            "solar_credit_eur": r.solar_credit_eur,
            "ev_kwh":           r.ev_kwh,
            "ev_cost_eur":      r.ev_cost_eur,
            "net_eur":          r.net_eur,
        }

    def get_status(self, price_eur_kwh: float = 0.25) -> dict:
        if not self._enabled or not self._units:
            return {"enabled": False, "units": []}
        report = self.calculate(price_eur_kwh)
        return {
            "enabled":          True,
            "units":            report.units,
            "total_solar_kwh":  report.total_solar_kwh,
            "total_ev_kwh":     report.total_ev_kwh,
            "split_method":     report.split_method,
        }
