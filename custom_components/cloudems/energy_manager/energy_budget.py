# -*- coding: utf-8 -*-
"""
CloudEMS Energie Budget Tracker — v1.0.0

Gebruiker stelt een maandbudget in (kWh of €).
CloudEMS berekent dagelijks:
  • Ben je op schema? (verwacht vs werkelijk tot nu toe)
  • Hoeveel ruimte heb je nog voor de rest van de maand?
  • Prognose einde maand (lineair + gewogen voor verwachte PV)

Werkt voor zowel elektriciteit als gas afzonderlijk.
Geen externe API nodig — gebruikt uitsluitend lokale data.

Budget-types:
  • euro_month    : maandbudget in Euro (elektriciteit)
  • kwh_month     : maandbudget in kWh (elektriciteit)
  • gas_m3_month  : maandbudget in m³ gas

Alertniveaus:
  • op_schema  : ≤ 90% van budget gebruikt naar evenredigheid
  • attentie   : 90–105% van budget op schema
  • overschrijding : > 105% op schema

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import calendar

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_budget_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 600

# Default budgetten (NL gemiddeld huishouden)
DEFAULT_ELEC_EUR_MONTH = 120.0    # €/maand elektriciteit
DEFAULT_ELEC_KWH_MONTH = 300.0    # kWh/maand
DEFAULT_GAS_M3_MONTH   = 150.0    # m³/maand (stookseizoen)


@dataclass
class BudgetStatus:
    """Status van één budget-dimensie."""
    budget_type:      str       # "euro" | "kwh" | "gas_m3"
    budget_value:     float     # ingesteld maandbudget
    actual_so_far:    float     # werkelijk verbruikt/uitgegeven tot nu
    expected_so_far:  float     # wat je zou verwachten op dag X van de maand
    remaining:        float     # budget - actual_so_far
    forecast_end_month: float   # prognose einde maand
    pct_used:         float     # % van budget verbruikt
    pct_of_month_elapsed: float # % van maand verstreken
    status:           str       # "op_schema" | "attentie" | "overschrijding"
    unit:             str       # "€" | "kWh" | "m³"
    advice:           str


@dataclass
class BudgetData:
    """Gecombineerde output voor de sensor."""
    electricity_eur:  BudgetStatus
    electricity_kwh:  Optional[BudgetStatus]
    gas_m3:           Optional[BudgetStatus]
    overall_status:   str      # meest kritieke status
    days_remaining:   int
    days_elapsed:     int
    month_label:      str
    summary:          str


def _pace_status(pct_used: float, pct_elapsed: float) -> str:
    """Bepaal status op basis van verbruikssnelheid vs tijdsverloop."""
    ratio = pct_used / max(pct_elapsed, 1.0)
    if ratio <= 0.90:
        return "op_schema"
    if ratio <= 1.05:
        return "attentie"
    return "overschrijding"


def _build_status(
    budget_type: str,
    budget_value: float,
    actual: float,
    day_of_month: int,
    days_in_month: int,
    unit: str,
) -> BudgetStatus:
    pct_elapsed = day_of_month / days_in_month * 100
    expected    = budget_value * pct_elapsed / 100
    pct_used    = actual / budget_value * 100 if budget_value > 0 else 0.0
    remaining   = max(0.0, budget_value - actual)
    forecast    = actual / max(day_of_month, 1) * days_in_month

    status = _pace_status(pct_used, pct_elapsed)
    over_pct = round(pct_used - pct_elapsed, 1)

    if status == "op_schema":
        advice = (
            f"Op schema. Verbruikt {actual:.1f} {unit} van {budget_value:.0f} {unit} "
            f"({pct_used:.0f}% in {pct_elapsed:.0f}% van de maand)."
        )
    elif status == "attentie":
        advice = (
            f"Let op: {over_pct:.1f}% voor op schema. Prognose einde maand: "
            f"{forecast:.1f} {unit} (budget: {budget_value:.0f} {unit})."
        )
    else:
        over = round(forecast - budget_value, 1)
        advice = (
            f"⚠️ Budget overschrijding dreigt! Prognose {forecast:.1f} {unit} — "
            f"{over:.1f} {unit} boven budget ({budget_value:.0f}). "
            "Overweeg verbruik te beperken."
        )

    return BudgetStatus(
        budget_type           = budget_type,
        budget_value          = round(budget_value, 2),
        actual_so_far         = round(actual, 2),
        expected_so_far       = round(expected, 2),
        remaining             = round(remaining, 2),
        forecast_end_month    = round(forecast, 2),
        pct_used              = round(pct_used, 1),
        pct_of_month_elapsed  = round(pct_elapsed, 1),
        status                = status,
        unit                  = unit,
        advice                = advice,
    )


class EnergyBudgetTracker:
    """
    Volgt energie-/gasverbruik vs. maandbudgetten.

    Aanroep vanuit coordinator:
        tracker.tick(cost_eur, kwh, gas_m3)
        data = tracker.get_data()
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._config = config

        # Budgetten uit configuratie (vallen terug op defaults)
        self._budget_eur   = float(config.get("budget_elec_eur_month",  DEFAULT_ELEC_EUR_MONTH))
        self._budget_kwh   = float(config.get("budget_elec_kwh_month",  DEFAULT_ELEC_KWH_MONTH))
        self._budget_gas   = float(config.get("budget_gas_m3_month",    DEFAULT_GAS_M3_MONTH))

        # Maand-accumulatoren
        self._month_key    = ""
        self._month_eur    = 0.0
        self._month_kwh    = 0.0
        self._month_gas    = 0.0

        self._tick_s      = 10.0
        self._dirty       = False
        self._last_save   = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        mk = saved.get("month_key", "")
        now_mk = datetime.now(timezone.utc).strftime("%Y-%m")
        if mk == now_mk:
            self._month_key = mk
            self._month_eur = float(saved.get("month_eur", 0.0))
            self._month_kwh = float(saved.get("month_kwh", 0.0))
            self._month_gas = float(saved.get("month_gas", 0.0))
        else:
            self._month_key = now_mk
        _LOGGER.info(
            "EnergyBudget: budget €%.0f/maand | %.0f kWh | %.0f m³ gas",
            self._budget_eur, self._budget_kwh, self._budget_gas,
        )

    def tick(
        self,
        cost_eur_delta: float,
        kwh_delta:      float,
        gas_m3_delta:   float = 0.0,
    ) -> None:
        """
        Voeg incrementele verbruiksdata toe (elke 10s).

        Parameters
        ----------
        cost_eur_delta : kosten dit tijdstap (€)
        kwh_delta      : verbruik dit tijdstap (kWh)
        gas_m3_delta   : gasverbruik dit tijdstap (m³)
        """
        now = datetime.now(timezone.utc)
        mk  = now.strftime("%Y-%m")

        if mk != self._month_key:
            _LOGGER.info("EnergyBudget: nieuwe maand %s — accumulatoren gereset", mk)
            self._month_key = mk
            self._month_eur = 0.0
            self._month_kwh = 0.0
            self._month_gas = 0.0

        self._month_eur += max(0.0, cost_eur_delta)
        self._month_kwh += max(0.0, kwh_delta)
        self._month_gas += max(0.0, gas_m3_delta)
        self._dirty = True

    def get_data(self) -> BudgetData:
        now           = datetime.now(timezone.utc)
        day_of_month  = now.day
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        days_remaining= days_in_month - day_of_month

        MONTHS_NL = {1:"Januari",2:"Februari",3:"Maart",4:"April",5:"Mei",
                     6:"Juni",7:"Juli",8:"Augustus",9:"September",10:"Oktober",
                     11:"November",12:"December"}
        month_label = f"{MONTHS_NL[now.month]} {now.year}"

        elec_eur = _build_status(
            "euro", self._budget_eur, self._month_eur,
            day_of_month, days_in_month, "€",
        )
        elec_kwh = _build_status(
            "kwh", self._budget_kwh, self._month_kwh,
            day_of_month, days_in_month, "kWh",
        )
        gas = _build_status(
            "gas_m3", self._budget_gas, self._month_gas,
            day_of_month, days_in_month, "m³",
        ) if self._budget_gas > 0 else None

        # Overall: meest kritieke status
        statuses = [elec_eur.status, elec_kwh.status]
        if gas:
            statuses.append(gas.status)
        if "overschrijding" in statuses:
            overall = "overschrijding"
        elif "attentie" in statuses:
            overall = "attentie"
        else:
            overall = "op_schema"

        # Samenvatting
        if overall == "op_schema":
            summary = (
                f"✅ {month_label}: op schema. "
                f"€{self._month_eur:.2f} van €{self._budget_eur:.0f} budget. "
                f"{days_remaining} dagen resterend."
            )
        elif overall == "attentie":
            summary = (
                f"⚡ {month_label}: licht voor op schema. "
                f"€{self._month_eur:.2f} van €{self._budget_eur:.0f} budget. "
                f"Prognose einde maand: €{elec_eur.forecast_end_month:.2f}."
            )
        else:
            summary = (
                f"⚠️ {month_label}: budget dreigt overschreden! "
                f"Prognose €{elec_eur.forecast_end_month:.2f} vs budget €{self._budget_eur:.0f}."
            )

        return BudgetData(
            electricity_eur  = elec_eur,
            electricity_kwh  = elec_kwh,
            gas_m3           = gas,
            overall_status   = overall,
            days_remaining   = days_remaining,
            days_elapsed     = day_of_month,
            month_label      = month_label,
            summary          = summary,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "month_key": self._month_key,
                "month_eur": round(self._month_eur, 4),
                "month_kwh": round(self._month_kwh, 4),
                "month_gas": round(self._month_gas, 4),
            })
            self._dirty     = False
            self._last_save = time.time()
