# -*- coding: utf-8 -*-
"""
CloudEMS — Energieleverancier Switchadviseur — v1.0.0

Breidt supplier_compare.py uit met een concreet switchadvies:
  • Wanneer is de beste tijd om over te stappen?
  • Wat zijn de administratieve kosten/drempels?
  • Hoeveel bespaar je op jaarbasis?

Logica:
  1. Gebruik ContractComparison-data van SupplierCompare
  2. Bereken maandelijkse besparing vs. huidig contract
  3. Zet drempelcriteria: overstapbonus, opzegkosten, contractduur
  4. Genereer switchadvies als jaarlijkse besparing > overstapdrempel

Output:
  sensor.cloudems_switch_advies
    state:      "switch_aanbevolen" | "blijf" | "evalueer"
    attributen: beste_contract, jaarlijkse_besparing, terugverdientijd_mnd,
                beste_moment_beschrijving, administratieve_drempel

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Drempel: minimale jaarlijkse besparing (€) om switch aan te bevelen
MIN_ANNUAL_SAVING_EUR   = 60.0    # €/jaar
# Typische overstapkosten (eenmalig, als niet geconfigureerd)
DEFAULT_SWITCH_COST_EUR = 40.0    # €  (tijd + administratie)
# Minimale terugverdientijd drempel (maanden)
MAX_PAYBACK_MONTHS      = 3


@dataclass
class SwitchScenario:
    """Eén contractscenario voor de switchanalyse."""
    contract_key:        str
    label:               str
    monthly_saving_eur:  float   # + = goedkoper dan huidig
    annual_saving_eur:   float
    switch_cost_eur:     float
    payback_months:      float   # NaN als besparing negatief
    recommended:         bool
    reason:              str


@dataclass
class SwitchAdvice:
    """Volledig switchadvies."""
    state:              str    # "switch_aanbevolen" | "blijf" | "evalueer" | "onvoldoende_data"
    best_contract:      str
    annual_saving_eur:  float
    payback_months:     float
    beste_moment:       str
    admin_drempel:      str
    scenarios:          list[SwitchScenario] = field(default_factory=list)
    data_days:          int = 0

    def to_dict(self) -> dict:
        return {
            "state":             self.state,
            "best_contract":     self.best_contract,
            "annual_saving_eur": round(self.annual_saving_eur, 2),
            "payback_months":    round(self.payback_months, 1) if self.payback_months == self.payback_months else None,
            "beste_moment":      self.beste_moment,
            "admin_drempel":     self.admin_drempel,
            "data_days":         self.data_days,
            "scenarios": [
                {
                    "contract":     s.contract_key,
                    "label":        s.label,
                    "besparing_mnd": round(s.monthly_saving_eur, 2),
                    "besparing_jr":  round(s.annual_saving_eur, 2),
                    "aanbevolen":    s.recommended,
                    "reden":         s.reason,
                }
                for s in self.scenarios
            ],
        }


def build_switch_advice(
    comparisons: list,                    # list[ContractComparison] van supplier_compare.py
    config: dict,
    data_days: int = 30,
) -> SwitchAdvice:
    """
    Genereer een switchadvies op basis van ContractComparison-resultaten.

    comparisons:   uitvoer van supplier_compare.compare_contracts()
    config:        CloudEMS config dict (optioneel: switch_cost_eur, contract_end_date)
    data_days:     hoeveel dagen meetdata beschikbaar is
    """
    if data_days < 14:
        return SwitchAdvice(
            state          = "onvoldoende_data",
            best_contract  = "",
            annual_saving_eur = 0.0,
            payback_months = float("nan"),
            beste_moment   = "Wacht op meer meetdata (minimaal 14 dagen)",
            admin_drempel  = "",
            data_days      = data_days,
        )

    switch_cost   = float(config.get("switch_cost_eur", DEFAULT_SWITCH_COST_EUR))
    contract_end  = config.get("contract_end_date", "")   # "YYYY-MM-DD"

    scenarios: list[SwitchScenario] = []

    best_saving = 0.0
    best_key    = ""
    best_label  = ""

    for comp in comparisons:
        # comp.vs_current_eur is negatief als het goedkoper is
        monthly_saving = -comp.vs_current_eur   # omdraaien: positief = besparing
        annual_saving  = monthly_saving * 12

        if annual_saving > 0:
            payback = switch_cost / (annual_saving / 12) if annual_saving > 0 else float("nan")
        else:
            payback = float("nan")

        recommended = (
            annual_saving >= MIN_ANNUAL_SAVING_EUR
            and (payback == payback and payback <= MAX_PAYBACK_MONTHS)
        )

        if annual_saving > best_saving:
            best_saving = annual_saving
            best_key    = comp.contract_type
            best_label  = comp.label

        reason = _build_reason(annual_saving, payback, comp.contract_type)

        scenarios.append(SwitchScenario(
            contract_key       = comp.contract_type,
            label              = comp.label,
            monthly_saving_eur = monthly_saving,
            annual_saving_eur  = annual_saving,
            switch_cost_eur    = switch_cost,
            payback_months     = payback,
            recommended        = recommended,
            reason             = reason,
        ))

    # Bepaal overall state
    best_scenario = next((s for s in scenarios if s.recommended), None)

    if best_scenario:
        state       = "switch_aanbevolen"
        best_moment = _best_switch_moment(contract_end)
        admin       = _admin_text(switch_cost, contract_end)
    elif best_saving >= MIN_ANNUAL_SAVING_EUR * 0.5:
        state       = "evalueer"
        best_moment = "Bespar meer data voor een zeker advies"
        admin       = _admin_text(switch_cost, contract_end)
    else:
        state       = "blijf"
        best_moment = "Huidig contract is concurrerend"
        admin       = "Geen actie nodig"

    best_payback = best_scenario.payback_months if best_scenario else float("nan")

    return SwitchAdvice(
        state             = state,
        best_contract     = best_label or best_key,
        annual_saving_eur = best_saving,
        payback_months    = best_payback,
        beste_moment      = best_moment,
        admin_drempel     = admin,
        scenarios         = scenarios,
        data_days         = data_days,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_reason(annual_saving: float, payback: float, contract_type: str) -> str:
    if annual_saving <= 0:
        return f"Duurder dan huidig (€{abs(annual_saving):.0f}/jr meer)"
    if payback != payback:  # nan
        return f"Besparing €{annual_saving:.0f}/jr maar overstapkosten te hoog"
    return (
        f"€{annual_saving:.0f}/jr besparing, "
        f"terugverdientijd {payback:.1f} maanden"
    )


def _best_switch_moment(contract_end: str) -> str:
    if not contract_end:
        return "Zo snel mogelijk overstappen (geen vaste einddatum bekend)"
    try:
        end_dt = datetime.strptime(contract_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now    = datetime.now(timezone.utc)
        days   = (end_dt - now).days
        if days < 0:
            return "Contract al verlopen — direct overstappen mogelijk"
        if days <= 30:
            return f"Contract loopt af over {days} dagen — overstap nu plannen"
        if days <= 90:
            return f"Contract loopt af over ~{days // 30} maanden — overstap nu aanvragen"
        return f"Contract loopt nog {days} dagen — alvast vergelijken en aanvragen"
    except ValueError:
        return "Controleer contracteinddatum in instellingen"


def _admin_text(switch_cost: float, contract_end: str) -> str:
    parts = [f"Eenmalige overstapkosten: ±€{switch_cost:.0f}"]
    if contract_end:
        parts.append(f"Contracteinddatum: {contract_end}")
    parts.append("Stappen: opzeggen → nieuw contract aanvragen → meter overzetten (~2-4 weken)")
    return " | ".join(parts)
