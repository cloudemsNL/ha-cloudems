"""
CloudEMS — house_load_optimizer.py  v1.0.0

Coördineert energieverdeling over ALLE flexibele verbruikers:
  batterij, boiler, EV, warmtepomp, zwembad

Principe:
  Gegeven een beperkt vermogen (PV-surplus + netcapaciteit) per slot,
  wie mag laden en hoeveel? Volgorde op basis van:
    1. Urgentie (deadline, temperatuurdrempel)
    2. Efficiëntie (COP warmtepomp vs weerstand)
    3. Prijs (goedkoop uur benutten)

  Beter dan los aansturen omdat:
    - Voorkomt dat boiler + EV + batterij tegelijk laden op duur uur
    - Benut goedkope uren voor ALLE verbruikers tegelijk
    - Houdt rekening met hoofdzekering (max fase-stroom)

Output per slot:
    - Welke verbruikers mogen laden
    - Hoeveel vermogen elk krijgt
    - Reden
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

SLOT_DURATION_H = 0.5   # 30 minuten
DEFAULT_GRID_CAPACITY_KW = 11.0  # 3×25A × 230V ÷ 1000 × 0.95


@dataclass
class FlexLoad:
    """Één flexibele verbruiker in het optimalisatieplan."""
    name:           str
    kwh_needed:     float          # hoeveel energie nog nodig
    max_kw:         float          # max vermogen dit apparaat
    priority:       int            # lager = hogere prioriteit
    urgency:        float          # 0-1, hoe urgent (1 = moet nu)
    efficiency:     float = 1.0    # rendement (WP COP = 3.0, weerstand = 1.0)
    deadline_slots: int   = 99     # over hoeveel slots moet het klaar zijn
    min_kw:         float = 0.0    # minimaal vermogen als ingeschakeld
    label:          str   = ""
    source:         str   = ""     # "boiler", "ev", "battery", "heatpump", "pool"


@dataclass
class SlotAllocation:
    """Toewijzing voor één 30-minuut slot."""
    slot_idx:       int
    hour:           float
    epex_eur:       float
    available_kw:   float          # beschikbaar vermogen dit slot
    allocations:    list[dict] = field(default_factory=list)  # [{name, kw, reason}]
    total_kw:       float = 0.0
    pv_kwh:         float = 0.0

    def get(self, name: str) -> float:
        """Geef toegewezen kW voor een verbruiker."""
        for a in self.allocations:
            if a["name"] == name:
                return a["kw"]
        return 0.0


@dataclass
class HouseLoadPlan:
    """Volledig 48-uurs plan voor alle verbruikers."""
    slots:              list[SlotAllocation] = field(default_factory=list)
    total_cost_eur:     float = 0.0
    savings_vs_now_eur: float = 0.0

    def get_current(self, current_hour: float) -> Optional[SlotAllocation]:
        for s in self.slots:
            if abs(s.hour - current_hour) < 0.26:
                return s
        return self.slots[0] if self.slots else None

    def allocation_for(self, source: str, current_hour: float) -> float:
        """Geef toegewezen kW voor een verbruiker op het huidige moment."""
        slot = self.get_current(current_hour)
        return slot.get(source) if slot else 0.0

    def summary(self) -> list[dict]:
        return [
            {"slot": s.slot_idx, "hour": s.hour, "epex": round(s.epex_eur, 4),
             "total_kw": round(s.total_kw, 2),
             "allocs": [{k: v for k, v in a.items()} for a in s.allocations]}
            for s in self.slots[:24] if s.allocations
        ]


class HouseLoadOptimizer:
    """
    Coördineert energieverdeling over alle flexibele verbruikers.

    Gebruik:
        opt = HouseLoadOptimizer(grid_capacity_kw=11.0)
        opt.add_load(FlexLoad("boiler", kwh_needed=2.5, max_kw=1.5, priority=2, urgency=0.6))
        opt.add_load(FlexLoad("ev",     kwh_needed=15,  max_kw=7.4, priority=3, urgency=0.4))
        opt.add_load(FlexLoad("battery",kwh_needed=5,   max_kw=3.7, priority=1, urgency=0.8))
        plan = opt.optimize(epex_slots, pv_slots, current_hour)
    """

    def __init__(self, grid_capacity_kw: float = DEFAULT_GRID_CAPACITY_KW) -> None:
        self._grid_kw   = grid_capacity_kw
        self._loads:    list[FlexLoad] = []
        self._last_plan: Optional[HouseLoadPlan] = None

    def clear_loads(self) -> None:
        self._loads = []

    def add_load(self, load: FlexLoad) -> None:
        # Vervang bestaande load met zelfde naam
        self._loads = [l for l in self._loads if l.name != load.name]
        if load.kwh_needed > 0.01:
            self._loads.append(load)

    def optimize(
        self,
        epex_slots:   list[dict],   # [{hour, price}]
        pv_slots:     list[dict],   # [{hour, kwh_p50}]
        current_hour: float,
        horizon:      int = 48,
    ) -> HouseLoadPlan:
        """Bereken optimale verdeling over de komende horizon uur."""
        if not self._loads:
            self._last_plan = HouseLoadPlan()
            return self._last_plan

        # Bouw slot-lijst
        slots = self._build_slots(epex_slots, pv_slots, current_hour, horizon)

        # Rangschik verbruikers: urgentie + prioriteit
        sorted_loads = sorted(
            self._loads,
            key=lambda l: (-l.urgency * (1 / max(l.deadline_slots, 1)), l.priority)
        )

        # Kopieer demand-tracking
        remaining = {l.name: l.kwh_needed for l in sorted_loads}

        # Per slot: verdeel beschikbaar vermogen
        for slot in slots:
            available = slot.available_kw
            if available <= 0.1:
                continue

            for load in sorted_loads:
                if remaining.get(load.name, 0) <= 0.01:
                    continue

                # Beslis of dit een goed slot is voor deze verbruiker
                score = self._slot_score(slot, load)
                if score < 0.1:
                    continue

                # Hoeveel vermogen toewijzen?
                kwh_left = remaining[load.name]
                max_kwh  = load.max_kw * SLOT_DURATION_H
                wanted_kwh = min(kwh_left, max_kwh)
                wanted_kw  = wanted_kwh / SLOT_DURATION_H

                # Begrens door beschikbaar netcapaciteit
                alloc_kw = min(wanted_kw, available)
                alloc_kw = max(alloc_kw, 0.0)

                if alloc_kw < 0.05:
                    continue

                alloc_kwh = alloc_kw * SLOT_DURATION_H
                slot.allocations.append({
                    "name":   load.name,
                    "label":  load.label or load.name,
                    "kw":     round(alloc_kw, 3),
                    "kwh":    round(alloc_kwh, 3),
                    "score":  round(score, 2),
                    "reason": self._reason(slot, load, score),
                })
                slot.total_kw += alloc_kw
                available     -= alloc_kw
                remaining[load.name] = max(0.0, remaining[load.name] - alloc_kwh)

        plan = HouseLoadPlan(slots=slots)
        plan.total_cost_eur     = self._calc_cost(slots)
        plan.savings_vs_now_eur = self._calc_savings(slots)
        self._last_plan = plan

        _LOGGER.debug(
            "HouseLoadOptimizer: plan berekend voor %d verbruikers, €%.3f kosten",
            len(self._loads), plan.total_cost_eur,
        )
        return plan

    def _build_slots(
        self, epex_slots, pv_slots, current_hour, horizon
    ) -> list[SlotAllocation]:
        epex_by_h = {}
        for e in epex_slots:
            h = round(float(e.get("hour", 0)) * 2) / 2
            epex_by_h[h] = float(e.get("price", 0.15))

        pv_by_h = {}
        for p in pv_slots:
            h = round(float(p.get("hour", 0)) * 2) / 2
            kwh = float(p.get("kwh_p50", p.get("kwh", 0)) or 0)
            pv_by_h[h] = kwh / 2  # uur → halfuur

        slots = []
        for i in range(horizon * 2):
            h = (current_hour + i * 0.5) % 24
            h_r = round(h * 2) / 2
            price = epex_by_h.get(h_r, epex_by_h.get(float(int(h)), 0.15))
            pv_kwh = pv_by_h.get(h_r, pv_by_h.get(float(int(h)), 0.0))

            # Beschikbaar: PV + grid, begrensd door hoofdzekering
            pv_kw = pv_kwh / SLOT_DURATION_H
            available_kw = min(self._grid_kw, pv_kw + self._grid_kw * 0.3)

            slots.append(SlotAllocation(
                slot_idx    = i,
                hour        = h_r,
                epex_eur    = price,
                available_kw = max(0.0, available_kw),
                pv_kwh      = pv_kwh,
            ))
        return slots

    def _slot_score(self, slot: SlotAllocation, load: FlexLoad) -> float:
        """
        Score 0-1 voor hoe goed dit slot is voor deze verbruiker.
        Hoog = goed slot (laden), laag = slechte slot (wachten).

        Safety-mechanisme: als de deadline nadert en er onvoldoende
        slots meer zijn om de kwh_needed te laden → forceer laden,
        ongeacht de prijs. Dit garandeert dat de boiler op tijd warm
        is en de EV op tijd geladen is.
        """
        price = slot.epex_eur

        # ── Safety: deadline-check ─────────────────────────────────────────
        # Hoeveel kWh kan er nog geladen worden in de resterende slots?
        remaining_slots = max(1, load.deadline_slots - slot.slot_idx)
        max_possible_kwh = remaining_slots * load.max_kw * SLOT_DURATION_H
        # Als we niet genoeg slots meer hebben: forceer laden nu
        safety_margin = 1.3  # 30% buffer voor onzekerheden
        if max_possible_kwh < load.kwh_needed * safety_margin:
            _LOGGER.debug(
                "HouseLoadOptimizer: %s deadline safety — %.1f kWh nodig, "
                "%.1f kWh mogelijk in %d slots — forceer laden",
                load.name, load.kwh_needed, max_possible_kwh, remaining_slots
            )
            return 1.0  # forceer laden ongeacht prijs

        # ── Basisregel: goedkoop uur = goede score ─────────────────────────
        if price < 0:
            return 1.0      # gratis stroom: altijd laden
        if price > 0.35:
            # Duur uur: alleen laden bij hoge urgentie of deadline
            return max(0.0, load.urgency - 0.5)

        # Schaal prijs naar score (0.30 → 0, 0.05 → 1.0)
        price_score = max(0.0, 1.0 - (price / 0.30))

        # PV-bonus: bij PV-surplus altijd verhogen
        pv_bonus = min(0.3, slot.pv_kwh * 0.2)

        # Urgentie: hoge urgentie ook bij hogere prijs laden
        urgency_override = load.urgency * 0.4

        return min(1.0, price_score + pv_bonus + urgency_override)

    def _reason(self, slot: SlotAllocation, load: FlexLoad, score: float) -> str:
        p = slot.epex_eur
        # Deadline safety check
        remaining_slots = max(1, load.deadline_slots - slot.slot_idx)
        max_possible_kwh = remaining_slots * load.max_kw * SLOT_DURATION_H
        if max_possible_kwh < load.kwh_needed * 1.3:
            slots_h = remaining_slots * 0.5
            return (f"⚠️ Deadline safety: nog {slots_h:.0f}u, "
                    f"{load.kwh_needed:.1f}kWh nodig — forceer laden @ {p:.3f}€")
        if p < 0:
            return f"Negatieve prijs {p:.3f}€ — gratis laden"
        if slot.pv_kwh > 0.1:
            return f"PV-surplus {slot.pv_kwh:.2f}kWh — gratis laden"
        if p < 0.10:
            return f"Goedkoop uur {p:.3f}€ — laden"
        if load.urgency > 0.7:
            return f"Urgentie {load.urgency:.0%} — laden ondanks prijs {p:.3f}€"
        return f"Optimaal slot score={score:.2f} prijs={p:.3f}€"

    def _calc_cost(self, slots: list[SlotAllocation]) -> float:
        total = 0.0
        for s in slots:
            for a in s.allocations:
                total += a["kwh"] * s.epex_eur
        return round(total, 4)

    def _calc_savings(self, slots: list[SlotAllocation]) -> float:
        """Besparing vs alles op huidige prijs laden."""
        if not slots:
            return 0.0
        now_price = slots[0].epex_eur
        savings = 0.0
        for s in slots:
            for a in s.allocations:
                savings += a["kwh"] * (now_price - s.epex_eur)
        return round(savings, 4)

    @property
    def last_plan(self) -> Optional[HouseLoadPlan]:
        return self._last_plan
