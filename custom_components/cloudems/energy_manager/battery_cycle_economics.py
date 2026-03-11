# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Degradatiekosten-bewuste Batterijplanning — v1.0.0

Uitbreiding op BatteryEPEXScheduler (battery_scheduler.py).
Berekent voor elk potentieel laad/ontlaad-uur de netto winst ná aftrek
van de slijtagekosten per kWh, zodat een cyclus van 10 ct winst maar
9 ct degradatie automatisch wordt overgeslagen.

Formule:
  netto_spread = (discharge_price - charge_price) - cycle_cost_eur_per_kwh
  ↳ schedule alleen als netto_spread > MIN_NET_SPREAD_EUR

Degradatiekosten:
  cycle_cost = (battery_price_eur / capacity_kwh) * chemistry_factor_per_kwh
  Voorbeeld: 8000 € / 10 kWh * 0.0045 = 0.0036 €/kWh per cyclus (NMC)

Integratie:
  BatteryCycleEconomics.evaluate_slot_pair(charge_price, discharge_price,
      soc_pct, capacity_kwh)
  → DegradationDecision(worth_it, netto_spread, cycle_cost, reason)

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Minimale netto spread na degradatiekosten om te schedulen (€/kWh)
MIN_NET_SPREAD_EUR    = 0.02

# Defaultwaarden als batterijprijs niet geconfigureerd is
DEFAULT_BATTERY_PRICE_EUR  = 8_000.0    # €
DEFAULT_CAPACITY_KWH       = 10.0
DEFAULT_ROUND_TRIP_EFF     = 0.92       # 92% round-trip efficiency

# Gekopieerd van battery_degradation.py — chemie-factoren
CHEMISTRY_FACTORS = {
    "LFP":  0.0025,
    "NMC":  0.0045,
    "NCA":  0.0050,
    "LTO":  0.0010,
}
DEFAULT_CHEMISTRY = "NMC"

# SoC stress-boete (degradatie neemt toe bij extremen)
SOC_PENALTY_DEEP     = 0.30    # +30% degradatiekosten als SoC < 15% bij ontladen
SOC_PENALTY_HIGH     = 0.20    # +20% degradatiekosten als SoC > 92% bij laden


@dataclass
class DegradationDecision:
    """Resultaat van de winstberekening voor één laad/ontlaad-paar."""
    worth_it:    bool
    netto_spread: float   # €/kWh na aftrek degradatiekosten
    cycle_cost:   float   # €/kWh degradatiekosten
    gross_spread: float   # €/kWh voor aftrek
    reason:       str     = ""


class BatteryCycleEconomics:
    """
    Berekent de netto economische waarde van een batterijcyclus,
    rekening houdend met degradatiekosten en round-trip efficiency.

    Gebruik in BatteryEPEXScheduler._build_schedule():
        eco = BatteryCycleEconomics(config)
        dec = eco.evaluate_slot_pair(charge_price, discharge_price, soc_pct)
        if not dec.worth_it:
            skip_discharge()
    """

    def __init__(self, config: dict) -> None:
        battery_price = float(config.get("battery_price_eur", DEFAULT_BATTERY_PRICE_EUR))
        capacity_kwh  = float(config.get("battery_capacity_kwh", DEFAULT_CAPACITY_KWH))
        chemistry     = config.get("battery_chemistry", DEFAULT_CHEMISTRY)
        rt_eff        = float(config.get("battery_round_trip_efficiency", DEFAULT_ROUND_TRIP_EFF))

        chem_factor = CHEMISTRY_FACTORS.get(chemistry, CHEMISTRY_FACTORS[DEFAULT_CHEMISTRY])

        # Basiskosten per kWh per cyclus (€/kWh)
        self._base_cycle_cost = (battery_price / max(capacity_kwh, 0.1)) * chem_factor
        self._rt_eff          = max(rt_eff, 0.5)
        self._min_spread      = float(config.get("battery_min_net_spread", MIN_NET_SPREAD_EUR))

        _LOGGER.debug(
            "BatteryCycleEconomics: %.4f €/kWh degradatie (%s), min spread %.3f €",
            self._base_cycle_cost, chemistry, self._min_spread,
        )

    def evaluate_slot_pair(
        self,
        charge_price: float,
        discharge_price: float,
        soc_at_discharge: Optional[float] = None,
        soc_at_charge: Optional[float]    = None,
    ) -> DegradationDecision:
        """
        Bereken of een laad/ontlaad-paar economisch rendabel is.

        charge_price:      EPEX prijs bij laden (€/kWh)
        discharge_price:   EPEX prijs bij ontladen (€/kWh)
        soc_at_discharge:  SoC (%) op moment van ontladen (optioneel)
        soc_at_charge:     SoC (%) op moment van laden (optioneel)
        """
        # Bruto spread na round-trip efficiency
        effective_charge = charge_price / self._rt_eff
        gross_spread = discharge_price - effective_charge

        # SoC stress-boete
        stress_factor = 1.0
        if soc_at_discharge is not None and soc_at_discharge < 15.0:
            stress_factor += SOC_PENALTY_DEEP
        if soc_at_charge is not None and soc_at_charge > 92.0:
            stress_factor += SOC_PENALTY_HIGH

        cycle_cost    = self._base_cycle_cost * stress_factor
        netto_spread  = gross_spread - cycle_cost

        if netto_spread >= self._min_spread:
            return DegradationDecision(
                worth_it     = True,
                netto_spread = round(netto_spread, 4),
                cycle_cost   = round(cycle_cost, 4),
                gross_spread = round(gross_spread, 4),
                reason       = (
                    f"Netto spread {netto_spread*100:.1f} ct/kWh "
                    f"(bruto {gross_spread*100:.1f} ct - "
                    f"slijtage {cycle_cost*100:.1f} ct)"
                ),
            )

        # Niet rendabel
        if gross_spread <= 0:
            reason = f"Bruto spread negatief ({gross_spread*100:.1f} ct/kWh)"
        else:
            reason = (
                f"Slijtagekosten ({cycle_cost*100:.1f} ct/kWh) "
                f"eten winst op ({gross_spread*100:.1f} ct/kWh bruto)"
            )

        return DegradationDecision(
            worth_it     = False,
            netto_spread = round(netto_spread, 4),
            cycle_cost   = round(cycle_cost, 4),
            gross_spread = round(gross_spread, 4),
            reason       = reason,
        )

    def evaluate_self_consumption(
        self,
        discharge_price: float,
        soc_at_discharge: Optional[float] = None,
    ) -> DegradationDecision:
        """
        Eigenverbruik (batterij dekt directe huislast, geen export).
        Referentieprijs = actuele inkoopprijs. Altijd rendabel als prijs > slijtage.
        """
        stress_factor = 1.0
        if soc_at_discharge is not None and soc_at_discharge < 15.0:
            stress_factor += SOC_PENALTY_DEEP

        cycle_cost   = self._base_cycle_cost * stress_factor
        netto_spread = discharge_price - cycle_cost   # geen laadprijs: al gevuld via PV

        return DegradationDecision(
            worth_it     = netto_spread > 0,
            netto_spread = round(netto_spread, 4),
            cycle_cost   = round(cycle_cost, 4),
            gross_spread = round(discharge_price, 4),
            reason       = (
                f"Eigenverbruik: {discharge_price*100:.1f} ct/kWh - "
                f"{cycle_cost*100:.1f} ct slijtage = "
                f"{netto_spread*100:.1f} ct netto"
            ),
        )

    @property
    def base_cycle_cost(self) -> float:
        """Basiskosten per kWh (zonder stress) — voor rapportage."""
        return self._base_cycle_cost

    def summary_dict(self) -> dict:
        """Sensor-attributen voor diagnose."""
        return {
            "cycle_cost_eur_per_kwh": round(self._base_cycle_cost, 5),
            "min_net_spread_eur":     self._min_spread,
            "round_trip_eff_pct":     round(self._rt_eff * 100, 1),
        }
