# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
supplier_compare.py — CloudEMS v4.0.6
=======================================
Energiecontract vergelijker — berekent hoeveel je had betaald
bij alternatieve tariefstructuren, op basis van je werkelijke verbruiksprofiel.

Vergelijkbare contracttypes:
  1. Dynamisch (EPEX-volgend, zoals je nu hebt) — huidige kosten
  2. Vast tarief — één prijs dag en nacht
  3. Dal/piek — goedkoper 's nachts, duurder overdag
  4. Volledig groen vast — vergelijkbaar met marktaanbod

Invoer: price_hour_history + werkelijk verbruiksprofiel (uurdata)
Uitvoer: kostenvergelijking in €/maand per contracttype

Geen API-aanroepen — puur lokale berekening.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# Nederlandse referentietarieven (begin 2026, indicatief)
REFERENCE_CONTRACTS = {
    "vast_gemiddeld": {
        "label":        "Vast tarief (gemiddeld markt)",
        "type":         "flat",
        "import_eur":   0.285,    # €/kWh
        "export_eur":   0.08,
        "standing":     0.50,     # €/dag
    },
    "vast_hoog": {
        "label":        "Vast tarief (duur contract)",
        "type":         "flat",
        "import_eur":   0.340,
        "export_eur":   0.07,
        "standing":     0.55,
    },
    "dal_piek": {
        "label":        "Dal/piek tarief (typisch NL)",
        "type":         "tou",    # time-of-use
        "import_dal":   0.22,     # 23:00-7:00
        "import_piek":  0.31,
        "export_eur":   0.08,
        "dal_hours":    list(range(0, 7)) + [23],
        "standing":     0.48,
    },
    "groen_vast": {
        "label":        "Groen vast (hernieuwbaar)",
        "type":         "flat",
        "import_eur":   0.295,
        "export_eur":   0.085,
        "standing":     0.52,
    },
}


@dataclass
class ContractComparison:
    label:          str
    contract_type:  str
    monthly_import_eur:  float
    monthly_export_eur:  float
    monthly_standing_eur: float
    monthly_total_eur:   float
    vs_current_eur:      float    # negatief = goedkoper dan huidig
    vs_current_pct:      float


def compare_contracts(
    price_hour_history: list,     # [{ts, price, kwh_net}, ...]
    days: int = 30,
) -> list[ContractComparison]:
    """
    Vergelijk alternatieve contracten met je werkelijke verbruik.

    price_hour_history: van coordinator._price_hour_history
    days: hoeveel dagen meenemen
    """
    from datetime import datetime, timezone, timedelta
    if not price_hour_history:
        return []

    # Filter op de laatste 'days' dagen
    now = __import__("time").time()
    cutoff = now - days * 86400
    recent = [e for e in price_hour_history if e.get("ts", 0) >= cutoff]
    if len(recent) < 24:
        return []

    # Bereken werkelijk verbruik per uur
    total_import_kwh  = 0.0
    total_export_kwh  = 0.0
    hour_import: dict[int, float] = {h: 0.0 for h in range(24)}

    for entry in recent:
        kwh_net = float(entry.get("kwh_net", 0) or 0)
        ts      = entry.get("ts", 0)
        hr      = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        if kwh_net > 0:
            total_import_kwh += kwh_net
            hour_import[hr]  += kwh_net
        elif kwh_net < 0:
            total_export_kwh += abs(kwh_net)

    if total_import_kwh <= 0:
        return []

    actual_days = max(1, len(recent) / 24)

    # Bereken huidige kosten (EPEX-volgend)
    current_total_eur = sum(
        float(e.get("kwh_net", 0) or 0) * float(e.get("price", 0.28) or 0.28)
        for e in recent
        if float(e.get("kwh_net", 0) or 0) > 0
    )
    current_export_eur = sum(
        abs(float(e.get("kwh_net", 0) or 0)) * float(e.get("price", 0.08) or 0.08)
        for e in recent
        if float(e.get("kwh_net", 0) or 0) < 0
    )
    current_monthly_net = (current_total_eur - current_export_eur) / actual_days * 30

    results = []
    for key, contract in REFERENCE_CONTRACTS.items():
        ct = contract["type"]

        if ct == "flat":
            imp_eur  = total_import_kwh * contract["import_eur"]
            exp_eur  = total_export_kwh * contract["export_eur"]
        elif ct == "tou":
            dal_h  = set(contract["dal_hours"])
            imp_dal  = sum(kwh for h, kwh in hour_import.items() if h in dal_h)
            imp_piek = sum(kwh for h, kwh in hour_import.items() if h not in dal_h)
            imp_eur  = imp_dal * contract["import_dal"] + imp_piek * contract["import_piek"]
            exp_eur  = total_export_kwh * contract["export_eur"]
        else:
            continue

        standing_eur = contract.get("standing", 0.50) * actual_days
        total_eur    = imp_eur - exp_eur + standing_eur
        monthly_net  = (imp_eur - exp_eur) / actual_days * 30
        vs_current   = monthly_net - current_monthly_net

        results.append(ContractComparison(
            label                = contract["label"],
            contract_type        = ct,
            monthly_import_eur   = round(imp_eur / actual_days * 30, 2),
            monthly_export_eur   = round(exp_eur / actual_days * 30, 2),
            monthly_standing_eur = round(contract.get("standing", 0.50) * 30, 2),
            monthly_total_eur    = round(total_eur / actual_days * 30, 2),
            vs_current_eur       = round(vs_current, 2),
            vs_current_pct       = round(vs_current / max(0.01, abs(current_monthly_net)) * 100, 1),
        ))

    results.sort(key=lambda x: x.monthly_total_eur)
    return results


def derive_actual_tariff(price_hour_history: list, days: int = 30) -> dict | None:
    """Leid het werkelijke gemiddelde importtarief af uit de price_hour_history.

    Berekent een consumption-gewogen gemiddelde prijs en effectief exporttarief.
    Geeft None als er te weinig data is.

    Gebruikt door compare_contracts() om de vergelijking altijd met actuele
    marktprijzen te doen in plaats van 2026-defaults.
    """
    if not price_hour_history:
        return None

    import time as _t
    now = _t.time()
    cutoff = now - days * 86400
    recent = [e for e in price_hour_history if e.get("ts", 0) >= cutoff]
    if len(recent) < 48:
        return None

    total_import_kwh  = 0.0
    total_export_kwh  = 0.0
    weighted_price    = 0.0
    weighted_export   = 0.0

    for entry in recent:
        kwh  = float(entry.get("kwh_net", 0) or 0)
        price = float(entry.get("price", 0) or 0)
        if kwh > 0:
            total_import_kwh += kwh
            weighted_price   += kwh * price
        elif kwh < 0:
            total_export_kwh += abs(kwh)
            weighted_export  += abs(kwh) * price

    if total_import_kwh <= 0:
        return None

    avg_import = round(weighted_price / total_import_kwh, 4)
    avg_export = round(weighted_export / total_export_kwh, 4) if total_export_kwh > 0 else avg_import * 0.28

    return {
        "avg_import_eur_kwh": avg_import,
        "avg_export_eur_kwh": avg_export,
        "days_measured":      round(len(recent) / 24, 1),
        "total_import_kwh":   round(total_import_kwh, 2),
    }


def to_dict_list(comparisons: list[ContractComparison]) -> list[dict]:
    return [
        {
            "label":               c.label,
            "monthly_import_eur":  c.monthly_import_eur,
            "monthly_export_eur":  c.monthly_export_eur,
            "monthly_total_eur":   c.monthly_total_eur,
            "vs_current_eur":      c.vs_current_eur,
            "vs_current_pct":      c.vs_current_pct,
            "cheaper":             c.vs_current_eur < -2.0,
        }
        for c in comparisons
    ]
