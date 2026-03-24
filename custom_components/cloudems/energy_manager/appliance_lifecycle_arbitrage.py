# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Appliance Lifecycle Arbitrage v1.0.0

Calculates whether switching on an appliance is financially worthwhile
after accounting for wear and degradation costs.

Decision logic:
  net_value = energy_saving_eur - wear_cost_eur
  If net_value <= 0: do not activate (not worth the wear)
  If net_value > min_profit: activate

Supported appliances:
  - Heat pump (compressor wear per start/stop cycle)
  - Battery (cycle degradation cost per kWh charged/discharged)
  - Washing machine (drum bearing wear per cycle)
  - Dishwasher (pump wear per cycle)
  - Any custom appliance via config

Wear cost models:
  - Cycle-based: cost_per_cycle / cycles_per_lifetime
  - kWh-based:   replacement_cost_eur / lifetime_kwh  (battery)
  - Hour-based:  replacement_cost_eur / lifetime_hours (pumps, compressors)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Default appliance wear parameters (researched typical values)
APPLIANCE_DEFAULTS = {
    "heat_pump": {
        "label":             "Warmtepomp",
        "wear_model":        "cycle",
        "replacement_eur":   8000.0,  # typical ASHP replacement
        "lifetime_cycles":   20000,   # compressor start/stop cycles
        "min_on_minutes":    20,       # minimum run time to amortize start cost
    },
    "battery": {
        "label":             "Thuisbatterij",
        "wear_model":        "kwh",
        "replacement_eur":   5000.0,  # per 10kWh usable capacity
        "lifetime_kwh":      50000,   # total usable kWh over lifetime (2000 cycles × 25kWh)
    },
    "washing_machine": {
        "label":             "Wasmachine",
        "wear_model":        "cycle",
        "replacement_eur":   600.0,
        "lifetime_cycles":   2000,
    },
    "dishwasher": {
        "label":             "Vaatwasser",
        "wear_model":        "cycle",
        "replacement_eur":   500.0,
        "lifetime_cycles":   5000,
    },
    "heat_pump_boiler": {
        "label":             "Warmtepompboiler",
        "wear_model":        "hour",
        "replacement_eur":   1200.0,
        "lifetime_hours":    15000,
    },
}


@dataclass
class ArbitrageDecision:
    """Result of one arbitrage calculation."""
    appliance_id:    str
    appliance_label: str
    should_activate: bool
    energy_value_eur:float    # value of running (savings or revenue)
    wear_cost_eur:   float    # degradation cost of one activation
    net_value_eur:   float    # energy_value - wear_cost
    reason:          str
    price_needed:    float    # minimum price needed to break even


class ApplianceLifecycleArbitrage:
    """
    Evaluates whether activating appliances is worthwhile
    after accounting for wear costs.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        # Build appliance registry from config + defaults
        self._appliances: dict = {}
        self._setup()

    def _setup(self) -> None:
        """Build appliance registry."""
        # Start with defaults
        for app_id, defaults in APPLIANCE_DEFAULTS.items():
            cfg_key = f"lifecycle_{app_id}"
            override = self._config.get(cfg_key, {})
            self._appliances[app_id] = {**defaults, **override}

        # Add custom appliances from config
        custom = self._config.get("lifecycle_custom_appliances") or []
        for item in custom:
            if isinstance(item, dict) and item.get("id"):
                self._appliances[item["id"]] = item

    def calculate(
        self,
        appliance_id:     str,
        price_eur_kwh:    float,
        duration_h:       float = 1.0,
        power_w:          float = 1000.0,
        energy_saving_eur: Optional[float] = None,
        min_profit_eur:   float = 0.005,  # minimum 0.5 ct net benefit
    ) -> ArbitrageDecision:
        """
        Calculate if activating the appliance is worthwhile.

        Args:
            appliance_id:      key from APPLIANCE_DEFAULTS or custom
            price_eur_kwh:     current electricity price
            duration_h:        expected run duration in hours
            power_w:           appliance power draw in W
            energy_saving_eur: override — manual energy value (e.g. for battery arbitrage)
            min_profit_eur:    minimum net profit to trigger activation
        """
        app = self._appliances.get(appliance_id)
        if not app:
            return ArbitrageDecision(
                appliance_id    = appliance_id,
                appliance_label = appliance_id,
                should_activate = True,  # unknown = no objection
                energy_value_eur= 0,
                wear_cost_eur   = 0,
                net_value_eur   = 0,
                reason          = "Onbekend apparaat — geen bezwaar",
                price_needed    = 0,
            )

        # Calculate wear cost
        model = app.get("wear_model", "cycle")
        replacement = float(app.get("replacement_eur", 1000))

        if model == "cycle":
            lifetime = float(app.get("lifetime_cycles", 2000))
            wear_eur = replacement / lifetime

        elif model == "kwh":
            lifetime = float(app.get("lifetime_kwh", 50000))
            energy_kwh = power_w / 1000 * duration_h
            wear_eur = (replacement / lifetime) * energy_kwh

        elif model == "hour":
            lifetime = float(app.get("lifetime_hours", 10000))
            wear_eur = (replacement / lifetime) * duration_h

        else:
            wear_eur = 0.0

        # Calculate energy value
        if energy_saving_eur is not None:
            ev_eur = energy_saving_eur
        else:
            energy_kwh = power_w / 1000 * duration_h
            ev_eur = energy_kwh * price_eur_kwh

        net = ev_eur - wear_eur
        should_activate = net >= min_profit_eur

        # Minimum price needed to break even
        energy_kwh = power_w / 1000 * duration_h
        price_needed = (wear_eur + min_profit_eur) / max(0.001, energy_kwh)

        if should_activate:
            reason = (
                f"Rendabel: €{ev_eur:.4f} opbrengst − €{wear_eur:.4f} slijtage = €{net:.4f} winst"
            )
        else:
            reason = (
                f"Niet rendabel: opbrengst €{ev_eur:.4f} < slijtage €{wear_eur:.4f}. "
                f"Prijs moet ≥ €{price_needed:.3f}/kWh zijn."
            )

        _LOGGER.debug(
            "Arbitrage %s: price=%.3f ev=%.4f wear=%.4f net=%.4f → %s",
            appliance_id, price_eur_kwh, ev_eur, wear_eur, net,
            "ACTIVATE" if should_activate else "SKIP"
        )

        return ArbitrageDecision(
            appliance_id     = appliance_id,
            appliance_label  = app.get("label", appliance_id),
            should_activate  = should_activate,
            energy_value_eur = round(ev_eur, 5),
            wear_cost_eur    = round(wear_eur, 5),
            net_value_eur    = round(net, 5),
            reason           = reason,
            price_needed     = round(price_needed, 4),
        )

    def evaluate_all(self, price_eur_kwh: float) -> list[dict]:
        """Quick evaluation of all known appliances at current price."""
        results = []
        power_map = {
            "heat_pump": 1500, "battery": 5000, "washing_machine": 1800,
            "dishwasher": 1200, "heat_pump_boiler": 800,
        }
        for app_id in self._appliances:
            dec = self.calculate(
                app_id, price_eur_kwh,
                duration_h=1.0,
                power_w=power_map.get(app_id, 1000),
            )
            results.append({
                "id":              dec.appliance_id,
                "label":           dec.appliance_label,
                "should_activate": dec.should_activate,
                "net_eur":         dec.net_value_eur,
                "wear_eur":        dec.wear_cost_eur,
                "price_needed":    dec.price_needed,
                "reason":          dec.reason,
            })
        return results
