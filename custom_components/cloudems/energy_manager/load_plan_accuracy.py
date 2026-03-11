# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS LoadPlanAccuracyTracker — v1.0.0.

Vergelijkt elke dag of het gisteren gegenereerde LoadPlanner-schema
(estimated_savings_eur) overeenkomt met de werkelijk gerealiseerde besparing.

Methode:
  - Plan van gisteren heeft estimated_savings_eur X en per-uur prijzen.
  - Vandaag zijn de werkelijke EPEX-prijzen en verbruiksdata beschikbaar
    via price_hour_history.
  - Werkelijke besparing = Σ (verplaatste kWh × (gemiddelde prijs − plan-uur-prijs))
  - Vergelijk X met werkelijk → leer correctiefactoren voor:
      * pv_factor:  was de PV-forecast te optimistisch/pessimistisch?
      * ev_factor:  week de EV-aankomst af?
      * price_factor: waren de EPEX-prijzen voorspelbaar?

Output: sensor.cloudems_load_plan_accuracy

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

STORE_KEY     = "cloudems_load_plan_accuracy_v1"
STORE_VERSION = 1
SAVE_INTERVAL = 3600   # max 1× per uur opslaan
MAX_HISTORY   = 30     # bewaar 30 dag-vergelijkingen


@dataclass
class PlanEvaluation:
    """Vergelijking van plan vs. werkelijkheid voor één dag."""
    date:               str
    estimated_eur:      float   # wat het plan beloofde
    actual_eur:         float   # werkelijke besparing
    accuracy_pct:       float   # 100 × actual / estimated (100 = perfect)
    pv_error_pct:       float   # afwijking PV-forecast (pos = te optimistisch)
    price_error_pct:    float   # afwijking prijsforecast
    notes:              str = ""


@dataclass
class AccuracyReport:
    """Samenvatting over de laatste MAX_HISTORY dagen."""
    days_evaluated:      int
    avg_accuracy_pct:    float   # gemiddelde nauwkeurigheid (100 = perfect)
    pv_bias:             float   # gem. PV-forecast afwijking (pos = te optimistisch)
    price_bias:          float   # gem. prijsforecast afwijking
    correction_factors:  dict    # toe te passen correcties
    history:             list[dict]
    advice:              str


class LoadPlanAccuracyTracker:
    """Vergelijkt LoadPlanner schattingen met werkelijkheid en leert correctiefactoren."""

    def __init__(self, hass=None) -> None:
        self._hass    = hass
        self._store   = None
        self._history: list[PlanEvaluation] = []
        # Correctiefactoren (1.0 = geen correctie nodig)
        self._pv_factor:    float = 1.0
        self._price_factor: float = 1.0
        self._dirty       = False
        self._last_save   = 0.0
        # Gisteren-plan bewaard voor vergelijking vandaag
        self._pending_plan: dict = {}   # {date, estimated_eur, flex_hours: [{hour, price}]}

    async def async_setup(self) -> None:
        """Laad opgeslagen vergelijkingen na herstart."""
        if not self._hass:
            return
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORE_VERSION, STORE_KEY)
        try:
            data = await self._store.async_load() or {}
            raw_hist = data.get("history", [])
            self._history = [PlanEvaluation(**e) for e in raw_hist]
            self._pv_factor    = float(data.get("pv_factor",    1.0))
            self._price_factor = float(data.get("price_factor", 1.0))
            self._pending_plan = data.get("pending_plan", {})
            _LOGGER.info(
                "LoadPlanAccuracyTracker: %d evaluaties geladen, pv_factor=%.2f",
                len(self._history), self._pv_factor,
            )
        except Exception as exc:
            _LOGGER.warning("LoadPlanAccuracyTracker: laden mislukt: %s", exc)

    async def async_maybe_save(self) -> None:
        """Sla op (dirty + rate-limit)."""
        if not self._store or not self._dirty:
            return
        if time.time() - self._last_save < SAVE_INTERVAL:
            return
        try:
            await self._store.async_save({
                "history": [
                    {k: getattr(e, k) for k in e.__dataclass_fields__}
                    for e in self._history[-MAX_HISTORY:]
                ],
                "pv_factor":    self._pv_factor,
                "price_factor": self._price_factor,
                "pending_plan": self._pending_plan,
            })
            self._dirty     = False
            self._last_save = time.time()
        except Exception as exc:
            _LOGGER.warning("LoadPlanAccuracyTracker: opslaan mislukt: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def store_plan(self, plan_dict: dict) -> None:
        """Sla het plan van vandaag op voor vergelijking morgen.

        plan_dict: output van plan_to_dict() uit load_planner.py
        """
        import datetime as _dt
        today = _dt.date.today().isoformat()
        self._pending_plan = {
            "date":          today,
            "estimated_eur": float(plan_dict.get("estimated_savings_eur", 0)),
            "flex_hours":    plan_dict.get("slots", []),   # [{hour, price, actions}]
            "pv_forecast":   plan_dict.get("pv_utilisation_pct", 0),
        }
        self._dirty = True
        _LOGGER.debug(
            "LoadPlanAccuracyTracker: plan %s opgeslagen (est. €%.2f)",
            today, self._pending_plan["estimated_eur"],
        )

    def evaluate_yesterday(self, price_hour_history: list) -> Optional[PlanEvaluation]:
        """Vergelijk gisteren-plan met werkelijkheid.

        Aanroepen elke ochtend (bv. na 06:00) vanuit coordinator.
        Geeft None als er geen plan was of te weinig data.
        """
        import datetime as _dt
        if not self._pending_plan:
            return None

        yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        plan_date = self._pending_plan.get("date", "")

        if plan_date != yesterday:
            # Plan is ouder dan gisteren — niet meer te vergelijken
            if plan_date < yesterday:
                self._pending_plan = {}
                self._dirty = True
            return None

        est_eur = self._pending_plan.get("estimated_eur", 0.0)
        if est_eur <= 0:
            return None

        # Filter price_hour_history op gisteren
        import datetime as _dt2
        yday_start = _dt2.datetime.combine(
            _dt2.date.fromisoformat(yesterday),
            _dt2.time.min,
        ).timestamp()
        yday_end = yday_start + 86400

        yday_entries = [
            e for e in price_hour_history
            if yday_start <= e.get("ts", 0) < yday_end
        ]
        if len(yday_entries) < 12:
            return None   # Te weinig data

        # Bereken gemiddelde prijs gisteren (consumption-weighted)
        total_kwh = sum(float(e.get("kwh_net", 0) or 0) for e in yday_entries if float(e.get("kwh_net", 0) or 0) > 0)
        avg_price = 0.0
        if total_kwh > 0:
            avg_price = sum(
                float(e.get("kwh_net", 0) or 0) * float(e.get("price", 0) or 0)
                for e in yday_entries
                if float(e.get("kwh_net", 0) or 0) > 0
            ) / total_kwh

        # Werkelijke besparing: verschil t.o.v. ongestuurd laden op piekprijs
        peak_price = max((float(e.get("price", 0) or 0) for e in yday_entries), default=avg_price)
        actual_eur = total_kwh * max(0, peak_price - avg_price)

        # Nauwkeurigheid
        accuracy_pct = round(actual_eur / est_eur * 100, 1) if est_eur > 0 else 0.0

        # PV-forecast afwijking: gebruik pv_utilisation uit plan vs. werkelijk
        plan_pv_pct = float(self._pending_plan.get("pv_forecast", 0))
        actual_pv_pct = 0.0
        pv_entries_kwh = sum(abs(float(e.get("kwh_net", 0) or 0)) for e in yday_entries if float(e.get("kwh_net", 0) or 0) < 0)
        if total_kwh + pv_entries_kwh > 0:
            actual_pv_pct = round(pv_entries_kwh / (total_kwh + pv_entries_kwh) * 100, 1)
        pv_error = round(plan_pv_pct - actual_pv_pct, 1)   # pos = plan was te optimistisch

        # Prijsforecast afwijking (plan vs. werkelijk gemiddelde)
        plan_slots = self._pending_plan.get("flex_hours", [])
        plan_avg_price = 0.0
        if plan_slots:
            prices = [float(s.get("price", 0) or 0) for s in plan_slots if s.get("price")]
            if prices:
                plan_avg_price = sum(prices) / len(prices)
        price_error = round((plan_avg_price - avg_price) / max(0.01, avg_price) * 100, 1) if plan_avg_price > 0 else 0.0

        eval_result = PlanEvaluation(
            date           = yesterday,
            estimated_eur  = round(est_eur, 3),
            actual_eur     = round(actual_eur, 3),
            accuracy_pct   = accuracy_pct,
            pv_error_pct   = pv_error,
            price_error_pct = price_error,
            notes          = f"avg_price={avg_price:.3f}, actual_savings={actual_eur:.3f}",
        )

        self._history.append(eval_result)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

        # Update correctiefactoren (trage EMA)
        if accuracy_pct > 0:
            ideal_factor = min(2.0, max(0.5, 100.0 / accuracy_pct))
            self._pv_factor    = 0.85 * self._pv_factor    + 0.15 * (1.0 - pv_error / 100)
            self._price_factor = 0.85 * self._price_factor + 0.15 * ideal_factor
            self._pv_factor    = max(0.5, min(2.0, self._pv_factor))
            self._price_factor = max(0.5, min(2.0, self._price_factor))

        self._pending_plan = {}
        self._dirty = True

        _LOGGER.info(
            "LoadPlanAccuracyTracker: %s — est €%.2f, actual €%.2f, accuracy %.0f%%, "
            "pv_error %.1f%%, pv_factor=%.2f",
            yesterday, est_eur, actual_eur, accuracy_pct,
            pv_error, self._pv_factor,
        )
        return eval_result

    def get_report(self) -> AccuracyReport:
        """Geef samenvatting voor de sensor."""
        if not self._history:
            return AccuracyReport(
                days_evaluated=0,
                avg_accuracy_pct=0.0,
                pv_bias=0.0,
                price_bias=0.0,
                correction_factors={"pv": 1.0, "price": 1.0},
                history=[],
                advice="Nog geen evaluaties beschikbaar (wacht tot morgen na het eerste plan).",
            )

        recent = self._history[-14:]
        avg_acc   = round(sum(e.accuracy_pct for e in recent) / len(recent), 1)
        avg_pv    = round(sum(e.pv_error_pct for e in recent) / len(recent), 1)
        avg_price = round(sum(e.price_error_pct for e in recent) / len(recent), 1)

        if avg_acc >= 80:
            advice = f"LoadPlanner nauwkeurigheid: {avg_acc:.0f}% — plannen zijn betrouwbaar."
        elif avg_acc >= 50:
            advice = (
                f"LoadPlanner nauwkeurigheid: {avg_acc:.0f}% — "
                f"PV-afwijking {avg_pv:+.1f}%, prijs-afwijking {avg_price:+.1f}%."
            )
        else:
            advice = (
                f"LoadPlanner nauwkeurigheid laag ({avg_acc:.0f}%) — "
                "PV-forecast of verbruikspatroon wijkt sterk af van plan. "
                "Controleer PV-forecast bron en EV-aankomsttijden."
            )

        return AccuracyReport(
            days_evaluated      = len(self._history),
            avg_accuracy_pct    = avg_acc,
            pv_bias             = avg_pv,
            price_bias          = avg_price,
            correction_factors  = {
                "pv":    round(self._pv_factor, 3),
                "price": round(self._price_factor, 3),
            },
            history = [
                {
                    "date":       e.date,
                    "est_eur":    e.estimated_eur,
                    "actual_eur": e.actual_eur,
                    "accuracy_pct": e.accuracy_pct,
                    "pv_error_pct": e.pv_error_pct,
                }
                for e in reversed(recent)
            ],
            advice = advice,
        )

    @property
    def pv_correction_factor(self) -> float:
        """Correctiefactor voor PV-forecast (toepassen in LoadPlanner)."""
        return self._pv_factor

    @property
    def price_correction_factor(self) -> float:
        """Correctiefactor voor prijsforecast."""
        return self._price_factor
