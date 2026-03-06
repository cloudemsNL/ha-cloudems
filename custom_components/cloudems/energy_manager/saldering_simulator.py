# -*- coding: utf-8 -*-
"""
CloudEMS Salderingsafbouw Simulator — v1.0.0

De Nederlandse salderingsregeling (net metering) wordt stapsgewijs afgebouwd:
  2023 — 100% (huidige situatie)
  2025 —  64%
  2026 —  36%
  2027 —   0%  (volledig afgeschaft)

Bron: Wet Elektriciteitsproductie Kleinschalig (WEK), Staatsblad 2023

Dit module gebruikt de bestaande historische uurdata van BillSimulator
om te berekenen hoeveel de stroomrekening stijgt per fase van de afbouw,
en welke batterijgrootte de schade het beste beperkt.

Output:
  • Rekening per jaar onder elk salderingsscenario (€)
  • Extra jaarkosten tov huidige situatie per fase (€)
  • Optimale batterijgrootte om netto-kostenstijging te minimaliseren
  • Advies in gewone taal

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Salderingspercentages per jaar (NL WEK)
SALDERING_PHASES: list[tuple[int, float]] = [
    (2023, 1.00),
    (2024, 1.00),
    (2025, 0.64),
    (2026, 0.36),
    (2027, 0.00),
]

# Batterijgroottes om te simuleren (kWh)
BATTERY_SIZES_KWH = [0, 5, 10, 15]

# Aanname: gemiddelde zelf-consumptie toename per kWh batterij
# Gebaseerd op NL gemiddelde (ECN/RVO 2022): 0.07 per kWh
SELF_CONSUMPTION_GAIN_PER_KWH_BATTERY = 0.07


@dataclass
class SalderingScenario:
    """Resultaat voor één salderingspercentage."""
    year:           int
    pct:            float    # 0.0 – 1.0
    annual_cost_eur: float
    export_revenue_eur: float
    import_cost_eur: float
    delta_vs_now_eur: float   # verschil t.o.v. huidig (positief = duurder)


@dataclass
class BatterySavingScenario:
    """Besparing bij een bepaalde batterijgrootte bij 0% saldering."""
    battery_kwh:        int
    self_consumption_pct: float   # geschatte zelfconsumptie na batterij
    annual_cost_eur:    float
    saving_vs_no_battery: float   # besparing t.o.v. 0% saldering zonder batterij
    payback_years:      Optional[float]   # terugverdientijd (bij €800/kWh)


@dataclass
class SalderingResult:
    """Volledig resultaat voor de HA-sensor."""
    current_annual_cost_eur:   float
    current_export_kwh:        float
    scenarios:                 list[SalderingScenario] = field(default_factory=list)
    battery_scenarios:         list[BatterySavingScenario] = field(default_factory=list)
    cost_at_zero_saldering:    float = 0.0
    extra_cost_at_zero_eur:    float = 0.0
    recommended_battery_kwh:   int = 0
    advice:                    str = ""
    hours_data:                int = 0


class SalderingSimulator:
    """
    Simuleert de financiële impact van de salderingsafbouw op basis van
    historische uurdata (BillSimulator._hours).

    Gebruik:
        sim = SalderingSimulator()
        result = sim.calculate(hour_records, fixed_tariff=0.28)
    """

    def calculate(
        self,
        hour_records: list,      # list[HourRecord]
        fixed_tariff: float = 0.28,
        current_return_pct: float = 1.00,
    ) -> SalderingResult:
        """
        Bereken rekening per salderingsfase en batterij-ROI.

        hour_records        — BillSimulator._hours (elk uur: ts, kwh_net, price)
        fixed_tariff        — vast tarief voor import-kosten (€/kWh)
        current_return_pct  — huidig terugleverings-% (standaard 1.00 = 100%)
        """
        if len(hour_records) < 168:   # min 1 week
            return SalderingResult(
                current_annual_cost_eur=0,
                current_export_kwh=0,
                advice="Nog te weinig data — beschikbaar na 1 week.",
                hours_data=len(hour_records),
            )

        # Annualiseer: schaal dataset naar 12 maanden
        days_in_data = len(hour_records) / 24
        scale = 365.0 / max(days_in_data, 1)

        total_import_kwh = 0.0
        total_export_kwh = 0.0
        total_import_cost = 0.0
        total_export_value = 0.0   # bij 100% saldering

        for rec in hour_records:
            kwh_import = max(0.0,  rec.kwh_net)
            kwh_export = max(0.0, -rec.kwh_net)
            total_import_kwh   += kwh_import
            total_export_kwh   += kwh_export
            total_import_cost  += kwh_import * fixed_tariff
            total_export_value += kwh_export * fixed_tariff   # @ 100%

        # Annualiseer
        ann_import_kwh   = total_import_kwh   * scale
        ann_export_kwh   = total_export_kwh   * scale
        ann_import_cost  = total_import_cost  * scale
        ann_export_value = total_export_value * scale

        # Scenario per salderingsfase
        scenarios: list[SalderingScenario] = []
        current_cost = ann_import_cost - ann_export_value * current_return_pct

        for year, pct in SALDERING_PHASES:
            export_rev = ann_export_value * pct
            cost = ann_import_cost - export_rev
            delta = cost - current_cost
            scenarios.append(SalderingScenario(
                year             = year,
                pct              = pct,
                annual_cost_eur  = round(cost, 2),
                export_revenue_eur = round(export_rev, 2),
                import_cost_eur  = round(ann_import_cost, 2),
                delta_vs_now_eur = round(delta, 2),
            ))

        cost_zero = ann_import_cost   # bij 0% saldering: geen teruglevering
        extra_zero = cost_zero - current_cost

        # Batterij-ROI bij 0% saldering
        battery_scenarios: list[BatterySavingScenario] = []
        for bkwh in BATTERY_SIZES_KWH:
            sc_gain = min(
                SELF_CONSUMPTION_GAIN_PER_KWH_BATTERY * bkwh,
                0.60,   # max 60% zelfconsumptie (fysieke limiet)
            )
            # Meer zelfconsumptie → minder export, meer import van eigen PV
            new_export_kwh = ann_export_kwh * (1 - sc_gain)
            new_import_kwh = ann_import_kwh - (ann_export_kwh - new_export_kwh)
            new_import_kwh = max(0, new_import_kwh)
            # Bij 0% saldering: export levert niets op
            batt_cost = new_import_kwh * fixed_tariff
            saving = cost_zero - batt_cost
            # Terugverdientijd: €800/kWh installatieprijs (NL gemiddelde 2024)
            invest = bkwh * 800
            payback = round(invest / saving, 1) if saving > 10 and bkwh > 0 else None

            battery_scenarios.append(BatterySavingScenario(
                battery_kwh           = bkwh,
                self_consumption_pct  = round(sc_gain * 100, 0),
                annual_cost_eur       = round(batt_cost, 2),
                saving_vs_no_battery  = round(saving, 2),
                payback_years         = payback,
            ))

        # Beste batterijgrootte: laagste payback die ≤ 10 jaar is
        valid = [b for b in battery_scenarios if b.payback_years and b.payback_years <= 10 and b.battery_kwh > 0]
        best_batt = min(valid, key=lambda b: b.payback_years) if valid else None
        recommended_kwh = best_batt.battery_kwh if best_batt else 0

        advice = self._build_advice(
            extra_zero, ann_export_kwh, recommended_kwh, best_batt
        )

        return SalderingResult(
            current_annual_cost_eur = round(current_cost, 2),
            current_export_kwh      = round(ann_export_kwh, 1),
            scenarios               = scenarios,
            battery_scenarios       = battery_scenarios,
            cost_at_zero_saldering  = round(cost_zero, 2),
            extra_cost_at_zero_eur  = round(extra_zero, 2),
            recommended_battery_kwh = recommended_kwh,
            advice                  = advice,
            hours_data              = len(hour_records),
        )

    def _build_advice(
        self,
        extra_zero: float,
        export_kwh: float,
        recommended_kwh: int,
        best_batt: Optional[BatterySavingScenario],
    ) -> str:
        if export_kwh < 100:
            return (
                "Je levert weinig terug aan het net. "
                "De salderingsafbouw heeft beperkte invloed op jouw rekening."
            )
        lines = [
            f"Bij volledige afbouw van saldering (2027) stijgt jouw jaarrekening "
            f"met ca. €{extra_zero:.0f}."
        ]
        if best_batt:
            lines.append(
                f"Een batterij van {recommended_kwh} kWh beperkt dit met "
                f"€{best_batt.saving_vs_no_battery:.0f}/jaar "
                f"(terugverdientijd ~{best_batt.payback_years} jaar)."
            )
        else:
            lines.append(
                "Een thuisbatterij is op basis van huidige data financieel "
                "niet rendabel binnen 10 jaar."
            )
        return " ".join(lines)

    def to_sensor_dict(self, result: SalderingResult) -> dict:
        """Flatten to HA sensor attributes."""
        return {
            "current_annual_cost_eur":   result.current_annual_cost_eur,
            "current_export_kwh":        result.current_export_kwh,
            "cost_at_zero_saldering_eur": result.cost_at_zero_saldering,
            "extra_cost_at_zero_eur":    result.extra_cost_at_zero_eur,
            "recommended_battery_kwh":   result.recommended_battery_kwh,
            "advice":                    result.advice,
            "hours_data":                result.hours_data,
            "phases": [
                {
                    "year":             s.year,
                    "saldering_pct":    round(s.pct * 100),
                    "annual_cost_eur":  s.annual_cost_eur,
                    "delta_vs_now_eur": s.delta_vs_now_eur,
                }
                for s in result.scenarios
            ],
            "battery_roi": [
                {
                    "battery_kwh":          b.battery_kwh,
                    "annual_cost_eur":      b.annual_cost_eur,
                    "saving_eur_year":      b.saving_vs_no_battery,
                    "payback_years":        b.payback_years,
                    "self_consumption_pct": b.self_consumption_pct,
                }
                for b in result.battery_scenarios
            ],
        }
