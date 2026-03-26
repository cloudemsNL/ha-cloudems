"""
CloudEMS — energy_dispatch_planner.py  v1.0.0

Berekent een optimaal energiedispatch-plan voor de komende N uur.
Uitvoer: per uur de aanbevolen actie (laden/ontladen/idle) en doelwaarde.

Principe (energie-cascadering):
  Prioriteit 1: Direct PV-verbruik (nul-actie nodig)
  Prioriteit 2: Batterij laden van PV-surplus
  Prioriteit 3: Grote verbruikers aansturen (boiler, EV) bij surplus of goedkoop uur
  Prioriteit 4: Netlevering alleen bij extreem gunstige prijs

De planner berekent GEEN commando's — dat doet de BDE per tick.
De planner geeft een trajectory mee als context zodat de BDE vooruit kan kijken.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class HourSlot:
    """Één uur in het dispatch-plan."""
    hour:          int
    epex_eur:      float          # EPEX prijs €/kWh
    pv_kwh:        float          # Verwachte PV opwekking dit uur
    load_kwh:      float          # Verwacht verbruik dit uur
    net_kwh:       float          # pv_kwh - load_kwh (positief = surplus)
    action:        str            # "charge", "discharge", "idle", "dump_to_boiler"
    target_soc:    float          # Gewenste SoC aan het einde van dit uur (%)
    reason:        str = ""


@dataclass
class DispatchPlan:
    """Het volledige dispatch-plan voor de komende N uur."""
    slots:         list[HourSlot] = field(default_factory=list)
    horizon_hours: int = 12

    def get_slot(self, hour: int) -> Optional[HourSlot]:
        for s in self.slots:
            if s.hour == hour:
                return s
        return None

    def target_soc_now(self, current_hour: int) -> Optional[float]:
        """Gewenste SoC dit uur."""
        s = self.get_slot(current_hour)
        return s.target_soc if s else None

    def summary(self) -> list[dict]:
        return [
            {"hour": s.hour, "action": s.action,
             "epex": round(s.epex_eur, 4), "pv": round(s.pv_kwh, 2),
             "target_soc": round(s.target_soc, 1), "reason": s.reason}
            for s in self.slots
        ]


class EnergyDispatchPlanner:
    """
    Berekent een optimaal energiedispatch-plan voor de komende N uur.

    Invoer:
        epex_forecast:     [{hour, price}]    — EPEX prijzen per uur
        pv_forecast:       [{hour, kwh}]      — PV opwekking per uur
        load_forecast:     [{hour, kwh}]      — Verwacht verbruik per uur
        current_soc:       float              — Huidige SoC %
        battery_kwh:       float              — Batterij capaciteit kWh
        charge_rate_kw:    float              — Max laadvermogen kW
        discharge_rate_kw: float              — Max ontlaadvermogen kW
        min_soc:           float              — Minimale SoC %
        max_soc:           float              — Maximale SoC %
        net_metering_pct:  float              — Salderingspercentage 0-1

    Strategie:
        1. Bereken per uur het energie-overschot/tekort
        2. Rangschik uren op EPEX prijs
        3. Wijs ladingsuren toe aan goedkoopste uren met surplus
        4. Wijs ontladingsuren toe aan duurste uren met tekort
        5. Bereken het SoC-traject dat hieruit volgt
    """

    def __init__(
        self,
        battery_kwh:       float = 10.0,
        charge_rate_kw:    float = 3.0,
        discharge_rate_kw: float = 3.0,
        min_soc:           float = 10.0,
        max_soc:           float = 90.0,
        net_metering_pct:  float = 0.36,
    ) -> None:
        self._battery_kwh       = battery_kwh
        self._charge_rate_kw    = charge_rate_kw
        self._discharge_rate_kw = discharge_rate_kw
        self._min_soc           = min_soc
        self._max_soc           = max_soc
        self._net_metering_pct  = net_metering_pct

    def plan(
        self,
        current_hour:  int,
        current_soc:   float,
        epex_forecast: list[dict],   # [{hour, price}]
        pv_forecast:   list[dict],   # [{hour, kwh}]
        load_forecast: list[dict],   # [{hour, kwh}]
        horizon:       int = 12,
    ) -> DispatchPlan:
        """Bereken het optimale dispatch-plan voor de komende `horizon` uren."""
        # Normaliseer input naar dict per uur
        epex = {e["hour"] % 24: e["price"] for e in epex_forecast if "hour" in e and "price" in e}
        pv   = {p["hour"] % 24: p.get("kwh", p.get("wh", 0) / 1000) for p in pv_forecast if "hour" in p}
        load = {l["hour"] % 24: l.get("kwh", 0) for l in load_forecast if "hour" in l}

        slots: list[HourSlot] = []
        soc = current_soc

        for i in range(horizon):
            h = (current_hour + i) % 24
            price = epex.get(h, 0.15)
            pv_kwh   = pv.get(h, 0.0)
            load_kwh = load.get(h, 0.3)  # default 300Wh/h als geen forecast
            net_kwh  = pv_kwh - load_kwh

            # Bepaal actie op basis van prioriteit
            action, new_soc, reason = self._decide(h, soc, price, net_kwh)

            slots.append(HourSlot(
                hour=h, epex_eur=price, pv_kwh=pv_kwh,
                load_kwh=load_kwh, net_kwh=net_kwh,
                action=action, target_soc=new_soc, reason=reason
            ))
            soc = new_soc

        return DispatchPlan(slots=slots, horizon_hours=horizon)

    def _decide(
        self, hour: int, soc: float, price: float, net_kwh: float
    ) -> tuple[str, float, str]:
        """Beslis de actie voor één uur. Returnt (action, new_soc, reason)."""
        cap = self._battery_kwh
        max_charge_kwh    = self._charge_rate_kw     # 1 uur = rate kW × 1u = kWh
        max_discharge_kwh = self._discharge_rate_kw

        headroom = (self._max_soc - soc) / 100 * cap
        available = (soc - self._min_soc) / 100 * cap

        # Prioriteit 1: PV-surplus → batterij laden
        if net_kwh > 0.1 and headroom > 0.1:
            charge_kwh = min(net_kwh, max_charge_kwh, headroom)
            new_soc = soc + (charge_kwh / cap * 100)
            return "charge", min(new_soc, self._max_soc), f"PV-surplus {net_kwh:.1f}kWh → laden"

        # Prioriteit 2: Goedkoop uur → laden van net (< 8ct of < 50% van daggemiddelde)
        if price < 0.08 and headroom > 0.5:
            charge_kwh = min(max_charge_kwh, headroom)
            new_soc = soc + (charge_kwh / cap * 100)
            return "charge", min(new_soc, self._max_soc), f"Goedkoop uur ({price*100:.1f}ct) → laden"

        # Prioriteit 3: Negatieve prijs → dump naar boiler/EV (batterij pas als die vol zijn)
        if price < 0 and headroom > 0.1:
            charge_kwh = min(max_charge_kwh, headroom)
            new_soc = soc + (charge_kwh / cap * 100)
            return "dump_to_boiler", min(new_soc, self._max_soc), f"Negatieve prijs ({price*100:.1f}ct) → boiler/EV eerst"

        # Prioriteit 4: Duur uur → ontladen (> 25ct)
        if price > 0.25 and available > 0.5:
            discharge_kwh = min(max_discharge_kwh, available, abs(net_kwh) + 0.3)
            new_soc = soc - (discharge_kwh / cap * 100)
            return "discharge", max(new_soc, self._min_soc), f"Duur uur ({price*100:.1f}ct) → ontladen"

        # Prioriteit 5: Tekort maar prijs redelijk → licht ontladen
        if net_kwh < -0.5 and available > 1.0 and price < 0.20:
            discharge_kwh = min(abs(net_kwh), max_discharge_kwh * 0.5, available)
            new_soc = soc - (discharge_kwh / cap * 100)
            return "discharge", max(new_soc, self._min_soc), f"Tekort dekken ({net_kwh:.1f}kWh)"

        return "idle", soc, "Geen actie nodig"

    def load_forecast_from_history(self, history_kwh_per_hour: dict[int, float]) -> list[dict]:
        """Maak een load forecast van historisch verbruik per uur."""
        return [{"hour": h, "kwh": kwh} for h, kwh in history_kwh_per_hour.items()]
