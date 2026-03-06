# -*- coding: utf-8 -*-
"""
CloudEMS Apparaatvervangings-ROI — v1.0.0

Berekent per NILM-apparaat of vervanging door een energiezuiniger model
financieel aantrekkelijk is.

Methode:
  1. NILM meet het werkelijke jaarverbruik per apparaat (kWh/jaar).
  2. De EPA-benchmarktabel bevat het verbruik van een modern A+++ model.
  3. Besparing = (huidig_verbruik − nieuw_verbruik) × stroomprijs
  4. Terugverdientijd = nieuwprijs / jaarlijkse_besparing

Invoer:
  - NILM devices (device_type, energy.year_kwh)
  - Actuele stroomprijs (€/kWh)
  - Optioneel: gebruikersinput over bouwjaar apparaat

Uitvoer:
  - Per apparaat: jaarverbruik, benchmarkverbruik, besparing, terugverdientijd
  - Totale besparing als alle 'rijpe' apparaten vervangen worden
  - Advies per apparaat

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── EPA-benchmark tabel ───────────────────────────────────────────────────────
# Verbruik modern A+++ model (kWh/jaar) per apparaattype.
# Bron: Energie.nl, EPREL-database, Consumentenbond 2023.
BENCHMARK_KWH: dict[str, float] = {
    "refrigerator":    110,   # A+++ koelkast 250L
    "washing_machine": 170,   # A+++ wasmachine 8kg
    "dryer":           200,   # A+++ warmtepompdroger 8kg
    "dishwasher":      230,   # A+++ vaatwasser 14 couv.
    "oven":            100,   # A+++ oven (inbouw, 65L)
}

# Gemiddeld verbruik oud model (voor apparaten zonder NILM-meting)
# Bron: CBS energiecijfers huishoudens + Milieucentraal
OLD_AVG_KWH: dict[str, float] = {
    "refrigerator":    380,
    "washing_machine": 350,
    "dryer":           500,
    "dishwasher":      400,
    "oven":            220,
}

# Prijs nieuw A+++ model (€, gemiddeld NL 2024)
REPLACEMENT_COST_EUR: dict[str, int] = {
    "refrigerator":    600,
    "washing_machine": 550,
    "dryer":           700,
    "dishwasher":      500,
    "oven":            400,
}

# Minimale meetduur voordat een NILM-meting als betrouwbaar wordt beschouwd
MIN_YEAR_KWH_MEASURED = 20    # minstens 20 kWh gemeten → vertrouwen we de meting
# Apparaten waarvoor ROI zinvol is
ROI_DEVICE_TYPES = set(BENCHMARK_KWH.keys())
# Terugverdientijd onder deze grens → 'aanbeveling'
GOOD_PAYBACK_YEARS = 8.0


@dataclass
class ApplianceROI:
    """ROI-analyse voor één apparaat."""
    device_id:          str
    device_type:        str
    label:              str
    measured_kwh_year:  float     # NILM-gemeten jaarverbruik
    benchmark_kwh_year: float     # A+++ referentieverbruik
    saving_kwh_year:    float
    saving_eur_year:    float
    replacement_cost_eur: int
    payback_years:      Optional[float]
    is_measured:        bool      # False = geschat via OLD_AVG
    advice:             str
    recommend:          bool


@dataclass
class ApplianceROIResult:
    """Totaalresultaat voor de HA-sensor."""
    devices:                list[ApplianceROI] = field(default_factory=list)
    total_saving_eur_year:  float = 0.0
    devices_to_replace:     int = 0
    top_candidate:          Optional[str] = None
    top_candidate_payback:  Optional[float] = None
    advice:                 str = ""
    price_eur_kwh:          float = 0.0


class ApplianceROICalculator:
    """
    Berekent vervangings-ROI voor huishoudapparaten op basis van NILM-data.

    Gebruik:
        calc = ApplianceROICalculator()
        result = calc.calculate(nilm_devices, price_eur_kwh=0.28)
    """

    def calculate(
        self,
        nilm_devices: list[dict],
        price_eur_kwh: float = 0.28,
    ) -> ApplianceROIResult:
        """
        nilm_devices  — get_devices_for_ha() uitvoer (inclusief energy dict)
        price_eur_kwh — huidige gemiddelde stroomprijs
        """
        if price_eur_kwh <= 0:
            price_eur_kwh = 0.28

        results: list[ApplianceROI] = []
        seen_types: set[str] = set()

        for dev in nilm_devices:
            dtype = dev.get("device_type", "")
            if dtype not in ROI_DEVICE_TYPES:
                continue
            # Toon elk type maar één keer (neem het apparaat met meeste gebruik)
            if dtype in seen_types:
                existing = next((r for r in results if r.device_type == dtype), None)
                current_kwh = float((dev.get("energy") or {}).get("year_kwh", 0) or 0)
                if existing and current_kwh <= existing.measured_kwh_year:
                    continue

            did   = dev.get("device_id", "")
            label = dev.get("name") or dev.get("label") or dtype.replace("_", " ").title()
            energy = dev.get("energy") or {}
            year_kwh = float(energy.get("year_kwh", 0) or 0)

            is_measured = year_kwh >= MIN_YEAR_KWH_MEASURED
            measured    = year_kwh if is_measured else OLD_AVG_KWH.get(dtype, 0)

            benchmark = BENCHMARK_KWH.get(dtype, 0)
            if benchmark <= 0 or measured <= benchmark:
                continue   # al zo zuinig als benchmark of onbekend

            saving_kwh  = measured - benchmark
            saving_eur  = round(saving_kwh * price_eur_kwh, 2)
            replace_eur = REPLACEMENT_COST_EUR.get(dtype, 500)
            payback     = round(replace_eur / saving_eur, 1) if saving_eur > 0 else None
            recommend   = payback is not None and payback <= GOOD_PAYBACK_YEARS

            if is_measured:
                kwh_label = f"{measured:.0f} kWh/jaar (gemeten)"
            else:
                kwh_label = f"~{measured:.0f} kWh/jaar (schatting, geen meting)"

            if recommend:
                advice = (
                    f"{label} verbruikt {kwh_label}, "
                    f"een nieuw A+++ model verbruikt ~{benchmark:.0f} kWh/jaar. "
                    f"Besparing: €{saving_eur:.0f}/jaar. "
                    f"Terugverdientijd bij vervangingskosten ~€{replace_eur}: "
                    f"~{payback} jaar. ✅ Aanbevolen."
                )
            else:
                advice = (
                    f"{label} verbruikt {kwh_label}. "
                    f"Terugverdientijd: {payback if payback else '?'} jaar "
                    f"(drempel: {GOOD_PAYBACK_YEARS:.0f} jaar)."
                )

            roi = ApplianceROI(
                device_id           = did,
                device_type         = dtype,
                label               = label,
                measured_kwh_year   = round(measured, 1),
                benchmark_kwh_year  = benchmark,
                saving_kwh_year     = round(saving_kwh, 1),
                saving_eur_year     = saving_eur,
                replacement_cost_eur = replace_eur,
                payback_years       = payback,
                is_measured         = is_measured,
                advice              = advice,
                recommend           = recommend,
            )
            # Replace existing entry for same type if this one is measured
            seen_types.add(dtype)
            existing_idx = next(
                (i for i, r in enumerate(results) if r.device_type == dtype), None
            )
            if existing_idx is not None:
                results[existing_idx] = roi
            else:
                results.append(roi)

        results.sort(key=lambda r: (not r.recommend, r.payback_years or 99))
        recommended = [r for r in results if r.recommend]
        total_saving = round(sum(r.saving_eur_year for r in recommended), 2)
        top = recommended[0] if recommended else (results[0] if results else None)

        if not results:
            advice = "Nog geen NILM-apparaten met voldoende meetdata voor ROI-analyse."
        elif recommended:
            advice = (
                f"{len(recommended)} apparaat/apparaten aanbevolen ter vervanging. "
                f"Totale besparing bij vervanging: €{total_saving:.0f}/jaar. "
                f"Grootste kans: {top.label} ({top.payback_years} jaar terugverdientijd)."
            )
        else:
            advice = "Geen apparaten met terugverdientijd onder 8 jaar gevonden."

        return ApplianceROIResult(
            devices               = results,
            total_saving_eur_year = total_saving,
            devices_to_replace    = len(recommended),
            top_candidate         = top.label if top else None,
            top_candidate_payback = top.payback_years if top else None,
            advice                = advice,
            price_eur_kwh         = price_eur_kwh,
        )

    def to_sensor_dict(self, result: ApplianceROIResult) -> dict:
        return {
            "total_saving_eur_year":  result.total_saving_eur_year,
            "devices_to_replace":     result.devices_to_replace,
            "top_candidate":          result.top_candidate,
            "top_candidate_payback":  result.top_candidate_payback,
            "price_eur_kwh":          result.price_eur_kwh,
            "advice":                 result.advice,
            "devices": [
                {
                    "label":                r.label,
                    "device_type":          r.device_type,
                    "current_kwh_year":     r.measured_kwh_year,
                    "benchmark_kwh_year":   r.benchmark_kwh_year,
                    "saving_eur_year":      r.saving_eur_year,
                    "payback_years":        r.payback_years,
                    "is_measured":          r.is_measured,
                    "recommend":            r.recommend,
                    "advice":               r.advice,
                }
                for r in result.devices[:8]
            ],
        }
