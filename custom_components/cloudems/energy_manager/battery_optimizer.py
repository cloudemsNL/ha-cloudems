"""
CloudEMS — battery_optimizer.py  v1.0.0

Cost-based battery optimizer — 48-uurs vooruitkijkende optimalisatie.

Werking:
  Voor elk 30-minuut slot in de komende 48 uur berekenen we de optimale actie
  (laden van net, laden van PV, ontladen, idle) op basis van minimale kosten.

  Kosten per slot:
    laden van net  = import_prijs × laad_kwh × (1 + laad_verlies)
    ontladen       = -(export_prijs × ontlaad_kwh × (1 - ontlaad_verlies))
                     want ontladen vermindert import later
    batterij slijtage = cycle_cost × kwh_gebruikt

  Algoritme:
    1. Bouw 48 × 2 slots (30 min) met PV, verbruik en prijzen
    2. Greedy optimalisatie: sorteer slots op prijs
       - Goedkoopste slots → laden (als er later duurdere slots zijn)
       - Duurste slots → ontladen (als er voldoende lading is)
    3. Simuleer SoC-traject en pas aan voor PV-surplus
    4. Output: per slot de actie + target SoC

  Beter dan heuristische BDE omdat:
    - Kijkt 48 uur vooruit (niet 12)
    - Optimaliseert over de hele horizon (niet slot-voor-slot)
    - Houdt rekening met inverter/batterij-efficiëntie
    - Probabilistische PV: 10%/50%/90% scenario's
    - Historisch verbruiksprofiel per halfuur
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Standaard efficiënties (configureerbaar)
DEFAULT_CHARGE_EFFICIENCY   = 0.95   # 95% round-trip laden
DEFAULT_DISCHARGE_EFFICIENCY = 0.95  # 95% round-trip ontladen
DEFAULT_CYCLE_COST_EUR_KWH  = 0.005  # €0.005/kWh batterij slijtage
DEFAULT_MIN_SOC_PCT         = 10.0
DEFAULT_MAX_SOC_PCT         = 95.0
DEFAULT_BATTERY_KWH         = 10.0
DEFAULT_MAX_CHARGE_KW       = 3.0
DEFAULT_MAX_DISCHARGE_KW    = 3.0
SLOT_DURATION_H             = 0.5   # 30 minuten


@dataclass
class OptSlot:
    """Één 30-minuut slot in het optimalisatieplan."""
    slot_idx:       int         # 0 = nu, 1 = +30min, etc.
    hour:           float       # decimale uren (bijv. 14.5 = 14:30)
    epex_eur:       float       # importprijs €/kWh
    export_eur:     float       # exportprijs €/kWh (vaak lager of 0)
    pv_kwh:         float       # verwachte PV opwekking dit slot (kWh)
    load_kwh:       float       # verwacht verbruik dit slot (kWh)
    action:         str  = "idle"   # "charge_grid","charge_pv","discharge","idle"
    charge_kwh:     float = 0.0     # kWh laden dit slot
    discharge_kwh:  float = 0.0     # kWh ontladen dit slot
    soc_start:      float = 50.0    # SoC % aan begin slot
    soc_end:        float = 50.0    # SoC % aan einde slot
    cost_eur:       float = 0.0     # netto kosten dit slot (negatief = winst)
    reason:         str  = ""


@dataclass
class OptimizationResult:
    """Resultaat van de 48-uurs optimalisatie."""
    slots:              list[OptSlot] = field(default_factory=list)
    total_cost_eur:     float = 0.0
    savings_vs_idle_eur: float = 0.0
    charge_slots:       int   = 0
    discharge_slots:    int   = 0
    pv_used_kwh:        float = 0.0

    def get_current_slot(self, current_hour: float) -> Optional[OptSlot]:
        """Geeft het slot dat nu actief is."""
        for s in self.slots:
            if abs(s.hour - current_hour) < 0.26:
                return s
        return self.slots[0] if self.slots else None

    def get_next_hours(self, n: int = 4) -> list[OptSlot]:
        return self.slots[:n*2]

    def summary(self) -> list[dict]:
        return [
            {"slot": s.slot_idx, "hour": s.hour, "action": s.action,
             "epex": round(s.epex_eur, 4), "pv": round(s.pv_kwh, 3),
             "load": round(s.load_kwh, 3), "soc_end": round(s.soc_end, 1),
             "cost": round(s.cost_eur, 4), "reason": s.reason}
            for s in self.slots[:24]  # eerste 12 uur
        ]


class BatteryOptimizer:
    """
    Cost-based 48-uurs batterij-optimizer.

    Vergelijkbaar met PredBat maar geïntegreerd in CloudEMS architectuur.
    Gebruikt greedy optimalisatie (goedkoper en sneller dan LP voor 96 slots).

    Gebruik:
        optimizer = BatteryOptimizer(battery_kwh=10, charge_kw=3, ...)
        result = optimizer.optimize(
            current_soc=74,
            epex_slots=[{"hour": 14.0, "price": 0.32}, ...],
            pv_slots=[{"hour": 14.0, "kwh_p50": 0.8, "kwh_p10": 0.3}],
            load_profile={14: 0.4, 15: 0.6, ...},
        )
    """

    def __init__(
        self,
        battery_kwh:          float = DEFAULT_BATTERY_KWH,
        charge_kw:            float = DEFAULT_MAX_CHARGE_KW,
        discharge_kw:         float = DEFAULT_MAX_DISCHARGE_KW,
        charge_efficiency:    float = DEFAULT_CHARGE_EFFICIENCY,
        discharge_efficiency: float = DEFAULT_DISCHARGE_EFFICIENCY,
        cycle_cost_eur_kwh:   float = DEFAULT_CYCLE_COST_EUR_KWH,
        min_soc_pct:          float = DEFAULT_MIN_SOC_PCT,
        max_soc_pct:          float = DEFAULT_MAX_SOC_PCT,
        net_metering_pct:     float = 0.36,
        export_price_factor:  float = 0.36,  # exportprijs = importprijs × factor
    ) -> None:
        self._cap_kwh   = battery_kwh
        self._chg_kw    = charge_kw
        self._dis_kw    = discharge_kw
        self._chg_eff   = charge_efficiency
        self._dis_eff   = discharge_efficiency
        self._cyc_cost  = cycle_cost_eur_kwh
        self._min_soc   = min_soc_pct
        self._max_soc   = max_soc_pct
        self._nm_pct    = net_metering_pct
        self._exp_factor = export_price_factor
        self._last_result: Optional[OptimizationResult] = None

    def optimize(
        self,
        current_soc:    float,
        current_hour:   float,
        epex_slots:     list[dict],   # [{hour, price}] — 48 uur vooruit
        pv_slots:       list[dict],   # [{hour, kwh_p50, kwh_p10, kwh_p90}]
        load_profile:   dict[int, float],  # {hour_of_day: kwh_per_30min}
        soh_pct:        float = 100.0,
        pv_scenario:    str   = "p50",  # "p10", "p50", "p90"
    ) -> OptimizationResult:
        """
        Bereken optimaal laad/ontlaad plan voor komende 48 uur.
        """
        # Bouw slot-lijst
        slots = self._build_slots(
            current_soc, current_hour, epex_slots, pv_slots, load_profile,
            soh_pct, pv_scenario
        )

        # Stap 1: verwerk PV-surplus direct (gratis laden)
        slots = self._apply_pv_charging(slots)

        # Stap 2: greedy arbitrage — laad goedkoop, ontlaad duur
        slots = self._apply_arbitrage(slots)

        # Stap 3: simuleer SoC-traject
        slots = self._simulate_soc(slots, current_soc, soh_pct)

        # Stap 4: bereken kosten
        result = self._calculate_costs(slots)
        self._last_result = result

        _LOGGER.debug(
            "BatteryOptimizer: plan berekend — %.2f€ kosten, %.2f€ besparing, "
            "%d laadslots, %d ontlaadslots",
            result.total_cost_eur, result.savings_vs_idle_eur,
            result.charge_slots, result.discharge_slots,
        )
        return result

    def _build_slots(
        self, current_soc, current_hour, epex_slots, pv_slots, load_profile,
        soh_pct, pv_scenario
    ) -> list[OptSlot]:
        """Bouw lijst van 96 slots (48 uur × 2 per uur)."""
        # Normaliseer input naar dict per halfuur
        epex_by_h = {}
        for e in epex_slots:
            h = e.get("hour", 0)
            epex_by_h[round(h * 2) / 2] = float(e.get("price", 0.15))

        pv_by_h = {}
        for p in pv_slots:
            h = p.get("hour", 0)
            kwh = float(p.get(f"kwh_{pv_scenario}", p.get("kwh_p50", p.get("kwh", 0))) or 0)
            pv_by_h[round(h * 2) / 2] = kwh / 2  # per uur → per halfuur

        slots = []
        for i in range(96):  # 48 uur × 2
            h = (current_hour + i * 0.5) % 24
            h_rounded = round(h * 2) / 2
            h_int = int(h)

            price = epex_by_h.get(h_rounded, epex_by_h.get(float(h_int), 0.15))
            pv    = pv_by_h.get(h_rounded, pv_by_h.get(float(h_int), 0.0))
            load  = float(load_profile.get(h_int, 0.3)) / 2  # uur→halfuur

            export_price = price * self._exp_factor * self._nm_pct

            slots.append(OptSlot(
                slot_idx   = i,
                hour       = h_rounded,
                epex_eur   = max(price, -0.5),
                export_eur = export_price,
                pv_kwh     = max(0.0, pv),
                load_kwh   = max(0.0, load),
            ))
        return slots

    def _apply_pv_charging(self, slots: list[OptSlot]) -> list[OptSlot]:
        """PV-surplus gaat altijd eerst naar batterij — gratis laden."""
        for s in slots:
            surplus = s.pv_kwh - s.load_kwh
            if surplus > 0.01:
                max_chg = self._chg_kw * SLOT_DURATION_H
                chg = min(surplus, max_chg)
                s.charge_kwh = chg
                s.action = "charge_pv"
                s.reason = f"PV-surplus {surplus:.2f}kWh → laden"
        return slots

    def _apply_arbitrage(self, slots: list[OptSlot]) -> list[OptSlot]:
        """
        Greedy arbitrage:
        1. Sorteer slots op prijs
        2. Goedkoopste slots zonder PV-surplus → laden van net
           (alleen als er duurdere slots later zijn om te ontladen)
        3. Duurste slots → ontladen
        """
        n = len(slots)

        # Bereken beschikbare capaciteit per slot na PV
        pv_charge = [s.charge_kwh for s in slots]

        # Identificeer potentiële laad- en ontlaadslots
        # Laaddrempel: prijs < gemiddelde - 20%
        prices = [s.epex_eur for s in slots if s.epex_eur > 0]
        if not prices:
            return slots
        avg_price = sum(prices) / len(prices)
        charge_threshold   = avg_price * 0.75   # laden onder 75% van gemiddelde
        discharge_threshold = avg_price * 1.20  # ontladen boven 120% van gemiddelde

        # Markeer slots
        charge_candidates   = [(i, slots[i].epex_eur) for i in range(n)
                                if slots[i].epex_eur <= charge_threshold
                                and slots[i].action == "idle"
                                and slots[i].epex_eur > -0.01]  # niet bij negatieve prijs laden van net
        discharge_candidates = [(i, slots[i].epex_eur) for i in range(n)
                                 if slots[i].epex_eur >= discharge_threshold
                                 and slots[i].action == "idle"]

        # Negatieve prijs: dump nu (gratis stroom)
        for i, s in enumerate(slots):
            if s.epex_eur < 0 and s.action == "idle":
                max_chg = self._chg_kw * SLOT_DURATION_H
                s.charge_kwh = max_chg
                s.action = "charge_grid"
                s.reason = f"Negatieve prijs {s.epex_eur:.3f}€ — gratis laden"

        # Sorteer laden op goedkoopste eerst
        charge_candidates.sort(key=lambda x: x[1])
        # Sorteer ontladen op duurste eerst
        discharge_candidates.sort(key=lambda x: -x[1])

        # Greedy koppeling: voor elk ontlaadslot, zoek goedkoopste laadslot ervóór
        assigned_charge = set()
        for dis_i, dis_price in discharge_candidates:
            # Zoek het goedkoopste beschikbare laadslot vóór dit ontlaadslot
            best_chg_i = None
            best_chg_price = float('inf')
            for chg_i, chg_price in charge_candidates:
                if chg_i < dis_i and chg_i not in assigned_charge:
                    # Winstgevend? Spread moet groter zijn dan slijtagekosten
                    spread = dis_price * self._dis_eff - chg_price / self._chg_eff - self._cyc_cost * 2
                    if spread > 0.01 and chg_price < best_chg_price:
                        best_chg_price = chg_price
                        best_chg_i = chg_i

            if best_chg_i is not None:
                assigned_charge.add(best_chg_i)
                # Laadslot
                s_c = slots[best_chg_i]
                if s_c.action == "idle":
                    s_c.charge_kwh = self._chg_kw * SLOT_DURATION_H
                    s_c.action = "charge_grid"
                    s_c.reason = (f"Laden voor arbitrage — prijs {s_c.epex_eur:.3f}€, "
                                  f"ontladen om {slots[dis_i].hour:.1f}u @ {dis_price:.3f}€")
                # Ontlaadslot
                s_d = slots[dis_i]
                if s_d.action == "idle":
                    s_d.discharge_kwh = self._dis_kw * SLOT_DURATION_H
                    s_d.action = "discharge"
                    s_d.reason = (f"Arbitrage ontladen @ {dis_price:.3f}€ — "
                                  f"geladen @ {s_c.epex_eur:.3f}€ spread {dis_price-s_c.epex_eur:.3f}€")

        return slots

    def _simulate_soc(
        self, slots: list[OptSlot], initial_soc: float, soh_pct: float
    ) -> list[OptSlot]:
        """Simuleer SoC-traject en knip acties bij limietoverschrijding."""
        usable_cap = self._cap_kwh * (soh_pct / 100.0)
        soc = initial_soc

        for s in slots:
            s.soc_start = soc
            cap_kwh = usable_cap * soc / 100.0
            headroom = usable_cap * (self._max_soc - soc) / 100.0
            available = usable_cap * (soc - self._min_soc) / 100.0

            net_kwh = 0.0

            if s.charge_kwh > 0:
                # Begrens laden door beschikbare ruimte
                actual_chg = min(s.charge_kwh, headroom / self._chg_eff)
                actual_chg = max(0.0, actual_chg)
                s.charge_kwh = round(actual_chg, 4)
                net_kwh += actual_chg * self._chg_eff
                if actual_chg < 0.001:
                    s.action = "idle"
                    s.charge_kwh = 0.0
                    s.reason = "Batterij vol — laden overgeslagen"

            if s.discharge_kwh > 0:
                # Begrens ontladen door beschikbare energie
                actual_dis = min(s.discharge_kwh, available * self._dis_eff)
                actual_dis = max(0.0, actual_dis)
                s.discharge_kwh = round(actual_dis, 4)
                net_kwh -= actual_dis / self._dis_eff
                if actual_dis < 0.001:
                    s.action = "idle"
                    s.discharge_kwh = 0.0
                    s.reason = "Batterij leeg — ontladen overgeslagen"

            # Update SoC
            delta_pct = (net_kwh / usable_cap) * 100.0 if usable_cap > 0 else 0
            soc = max(self._min_soc, min(self._max_soc, soc + delta_pct))
            s.soc_end = round(soc, 1)

        return slots

    def _calculate_costs(self, slots: list[OptSlot]) -> OptimizationResult:
        """Bereken kosten per slot en totaalresultaat."""
        total_cost   = 0.0
        idle_cost    = 0.0
        charge_slots = 0
        dis_slots    = 0
        pv_used      = 0.0

        for s in slots:
            # Netto verbruik van net dit slot
            net_import = s.load_kwh - s.pv_kwh + s.charge_kwh - s.discharge_kwh * self._dis_eff
            net_export = max(0.0, -net_import)
            net_import = max(0.0, net_import)

            # Kosten
            cost = (net_import * s.epex_eur
                    - net_export * s.export_eur
                    + (s.charge_kwh + s.discharge_kwh) * self._cyc_cost)
            s.cost_eur = round(cost, 5)
            total_cost += cost

            # Idle benchmark (geen sturing)
            idle_import = max(0.0, s.load_kwh - s.pv_kwh)
            idle_cost  += idle_import * s.epex_eur

            if s.action in ("charge_grid", "charge_pv"):
                charge_slots += 1
            elif s.action == "discharge":
                dis_slots += 1
            if s.action == "charge_pv":
                pv_used += s.charge_kwh

        return OptimizationResult(
            slots               = slots,
            total_cost_eur      = round(total_cost, 4),
            savings_vs_idle_eur = round(idle_cost - total_cost, 4),
            charge_slots        = charge_slots,
            discharge_slots     = dis_slots,
            pv_used_kwh         = round(pv_used, 3),
        )

    @property
    def last_result(self) -> Optional[OptimizationResult]:
        return self._last_result
