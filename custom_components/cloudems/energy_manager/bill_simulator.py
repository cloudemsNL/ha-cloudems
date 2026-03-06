# -*- coding: utf-8 -*-
"""
CloudEMS Virtuele Stroomrekening Simulator — v1.0.0

Beantwoordt de vraag: "Hoeveel zou ik betaald hebben met een ander contract?"

CloudEMS registreert elke uur:
  • Verbruik (kWh) — uit de P1/slimme meter
  • EPEX spotprijs (€/kWh) — uit de prijsfetcher

Met die dataset vergelijkt de simulator je werkelijk betaalde rekening
(dynamisch contract) met alternatieve contractvormen:

  1. VAST TARIEF         — één prijs per kWh, heel het jaar
  2. DAG/NACHT TARIEF    — lager tarief 23:00–07:00, hoger overdag
  3. WEEKENDTARIEF       — lager tarief op za/zo

Opbrengsten (teruglevering aan net) worden gesimuleerd met het opgegeven
terugleverpercentage of de actuele spotprijs.

Output (sensor attributes):
  • Werkelijk betaald dit jaar (dynamisch)
  • Gesimuleerd vast tarief
  • Gesimuleerd dag/nacht tarief
  • Verschil t.o.v. vast tarief (€ bespaard / te veel betaald)
  • Maandelijkse breakdown (12 maanden)
  • Beste maand / slechtste maand voor dynamisch contract

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_bill_simulator_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 600   # elke 10 min opslaan

# Maximale opgeslagen uren (2 jaar × 8760 = 17520)
MAX_HOURS = 17520


@dataclass
class HourRecord:
    """Één uurmeting: verbruik + prijs."""
    ts:       int     # Unix timestamp (begin van het uur, UTC)
    kwh_net:  float   # Verbruik uit net (positief = import, negatief = export)
    price:    float   # EPEX spotprijs incl. opslag (€/kWh)

    def to_list(self) -> list:
        return [self.ts, round(self.kwh_net, 4), round(self.price, 5)]

    @classmethod
    def from_list(cls, row: list) -> "HourRecord":
        return cls(ts=int(row[0]), kwh_net=float(row[1]), price=float(row[2]))


@dataclass
class SimScenario:
    """Eén gesimuleerd contract-scenario."""
    name:           str
    cost_eur:       float = 0.0   # totale kosten (import − export)
    import_kwh:     float = 0.0
    export_kwh:     float = 0.0
    monthly:        dict  = field(default_factory=dict)  # "YYYY-MM" → €


@dataclass
class BillSimResult:
    """Output van de simulator voor de HA-sensor."""
    dynamic_cost_eur:    float
    dynamic_import_kwh:  float
    dynamic_export_kwh:  float
    fixed_cost_eur:      float
    fixed_tariff:        float   # geconfigureerd vast tarief
    day_night_cost_eur:  float
    day_tariff:          float
    night_tariff:        float
    saving_vs_fixed_eur: float   # positief = dynamisch goedkoper
    saving_vs_fixed_pct: float
    best_month:          str     # maand waarop dynamisch het meest bespaarde
    worst_month:         str     # maand waarop dynamisch het duurst was
    months_dynamic_won:  int     # hoeveel maanden goedkoper dan vast
    months_data:         int     # hoeveel maanden in de dataset
    hours_recorded:      int
    advice:              str


class BillSimulator:
    """
    Vergelijkt je werkelijk betaalde dynamische stroomrekening
    met alternatieve contractvormen op basis van historische uurdata.

    Gebruik vanuit coordinator:
        sim = BillSimulator(hass, fixed_tariff=0.28, day_tariff=0.30,
                            night_tariff=0.22, return_pct=0.80)
        await sim.async_setup()
        # Elke update-cyclus:
        sim.record(kwh_net, epex_price_eur_kwh)
        result = sim.get_result()
    """

    def __init__(
        self,
        hass:          HomeAssistant,
        fixed_tariff:  float = 0.28,   # €/kWh vast (instelbaar in config flow)
        day_tariff:    float = 0.30,   # €/kWh overdag (07–23 u)
        night_tariff:  float = 0.22,   # €/kWh nacht (23–07 u)
        return_pct:    float = 0.80,   # teruglevering: % van spotprijs
    ) -> None:
        self.hass          = hass
        self._fixed        = fixed_tariff
        self._day          = day_tariff
        self._night        = night_tariff
        self._return_pct   = return_pct
        self._store        = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._hours:    list[HourRecord] = []
        self._dirty     = False
        self._last_save = 0.0
        self._last_ts   = 0     # voor de-duplicatie

        # Accumulatie binnen het lopende uur
        self._hour_kwh_acc:   float = 0.0
        self._hour_price_acc: float = 0.0
        self._hour_ticks:     int   = 0
        self._current_hour_ts: int  = 0

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for row in saved.get("hours", []):
            try:
                self._hours.append(HourRecord.from_list(row))
            except Exception:
                pass
        _LOGGER.info(
            "BillSimulator: %d uur geladen (%d maanden data)",
            len(self._hours),
            len({h.ts // (86400 * 28) for h in self._hours}),
        )

    # ── Data opnemen ─────────────────────────────────────────────────────

    def record(self, kwh_net: float, price_eur_kwh: float) -> None:
        """
        Voeg één 10-seconde meting toe.

        kwh_net > 0 → import; kwh_net < 0 → export (PV/batterij teruglevering).
        Wordt elke 10s aangeroepen vanuit de coordinator; accumuleert per uur.
        """
        now_ts = int(time.time())
        # Bepaal het begin van het huidige uur (afgerond naar beneden)
        hour_ts = now_ts - (now_ts % 3600)

        if hour_ts != self._current_hour_ts:
            # Nieuw uur begonnen → sla vorig uur op
            if self._current_hour_ts > 0 and self._hour_ticks > 0:
                avg_price = self._hour_price_acc / self._hour_ticks
                self._commit_hour(self._current_hour_ts, self._hour_kwh_acc, avg_price)
            self._current_hour_ts = hour_ts
            self._hour_kwh_acc    = 0.0
            self._hour_price_acc  = 0.0
            self._hour_ticks      = 0

        # kWh per tick = vermogen × (10s / 3600s) — maar we krijgen al kWh binnen
        self._hour_kwh_acc   += kwh_net
        self._hour_price_acc += price_eur_kwh
        self._hour_ticks     += 1

    def _commit_hour(self, hour_ts: int, kwh_net: float, avg_price: float) -> None:
        if hour_ts == self._last_ts:
            return   # dedup
        self._last_ts = hour_ts
        rec = HourRecord(ts=hour_ts, kwh_net=kwh_net, price=avg_price)
        self._hours.append(rec)
        if len(self._hours) > MAX_HOURS:
            self._hours = self._hours[-MAX_HOURS:]
        self._dirty = True

    # ── Berekening ───────────────────────────────────────────────────────

    def get_result(self) -> BillSimResult:
        """Bereken en vergelijk alle scenario's over de volledige dataset."""
        if len(self._hours) < 24:
            return self._empty_result()

        dynamic  = SimScenario("dynamic")
        fixed    = SimScenario("fixed")
        day_night = SimScenario("day_night")

        for rec in self._hours:
            dt  = datetime.fromtimestamp(rec.ts, tz=timezone.utc)
            mon = dt.strftime("%Y-%m")
            h   = dt.hour

            kwh_import = max(0.0,  rec.kwh_net)
            kwh_export = max(0.0, -rec.kwh_net)

            # ── Dynamisch (werkelijk) ──────────────────────────────────
            dyn_cost = kwh_import * rec.price - kwh_export * rec.price * self._return_pct
            dynamic.cost_eur    += dyn_cost
            dynamic.import_kwh  += kwh_import
            dynamic.export_kwh  += kwh_export
            dynamic.monthly[mon] = dynamic.monthly.get(mon, 0.0) + dyn_cost

            # ── Vast tarief ───────────────────────────────────────────
            fix_cost = kwh_import * self._fixed - kwh_export * self._fixed * self._return_pct
            fixed.cost_eur    += fix_cost
            fixed.import_kwh  += kwh_import
            fixed.export_kwh  += kwh_export
            fixed.monthly[mon] = fixed.monthly.get(mon, 0.0) + fix_cost

            # ── Dag/nacht tarief ──────────────────────────────────────
            night_hour = h < 7 or h >= 23
            dn_price = self._night if night_hour else self._day
            dn_cost = kwh_import * dn_price - kwh_export * dn_price * self._return_pct
            day_night.cost_eur    += dn_cost
            day_night.import_kwh  += kwh_import
            day_night.export_kwh  += kwh_export
            day_night.monthly[mon] = day_night.monthly.get(mon, 0.0) + dn_cost

        saving_eur = fixed.cost_eur - dynamic.cost_eur
        saving_pct = (saving_eur / fixed.cost_eur * 100) if fixed.cost_eur != 0 else 0.0

        # Beste/slechtste maand voor dynamisch vs vast
        months_dynamic_won = 0
        best_mon  = ""
        worst_mon = ""
        best_val  = float("inf")
        worst_val = float("-inf")
        for mon in dynamic.monthly:
            if mon not in fixed.monthly:
                continue
            diff = fixed.monthly[mon] - dynamic.monthly[mon]   # positief = dynamisch won
            if diff > worst_val:
                worst_val = diff
                worst_mon = mon   # ironisch: "worst" = maand met grootste voordeel?
            # Eigenlijk: worst = maand dat dynamisch het meest DUURDER was
        # Correct: best = max saving, worst = min saving (most expensive dynamic)
        diffs = {
            mon: fixed.monthly[mon] - dynamic.monthly.get(mon, 0)
            for mon in fixed.monthly
            if mon in dynamic.monthly
        }
        if diffs:
            best_mon  = max(diffs, key=lambda m: diffs[m])
            worst_mon = min(diffs, key=lambda m: diffs[m])
            months_dynamic_won = sum(1 for v in diffs.values() if v > 0)

        advice = self._build_advice(saving_eur, saving_pct, months_dynamic_won, len(diffs))

        return BillSimResult(
            dynamic_cost_eur    = round(dynamic.cost_eur, 2),
            dynamic_import_kwh  = round(dynamic.import_kwh, 1),
            dynamic_export_kwh  = round(dynamic.export_kwh, 1),
            fixed_cost_eur      = round(fixed.cost_eur, 2),
            fixed_tariff        = self._fixed,
            day_night_cost_eur  = round(day_night.cost_eur, 2),
            day_tariff          = self._day,
            night_tariff        = self._night,
            saving_vs_fixed_eur = round(saving_eur, 2),
            saving_vs_fixed_pct = round(saving_pct, 1),
            best_month          = best_mon,
            worst_month         = worst_mon,
            months_dynamic_won  = months_dynamic_won,
            months_data         = len(diffs),
            hours_recorded      = len(self._hours),
            advice              = advice,
        )

    def _build_advice(
        self,
        saving_eur: float,
        saving_pct: float,
        months_won: int,
        total_months: int,
    ) -> str:
        if total_months < 2:
            return (
                "Nog te weinig data voor een betrouwbare vergelijking. "
                f"Na {max(0, 2 - total_months)} maand(en) meer is de analyse beschikbaar."
            )
        if saving_eur > 0:
            return (
                f"Jouw dynamische contract bespaart je €{saving_eur:.0f} "
                f"({saving_pct:.0f}%) t.o.v. een vast tarief van €{self._fixed:.2f}/kWh. "
                f"In {months_won} van de {total_months} maanden was dynamisch goedkoper."
            )
        else:
            return (
                f"Met een vast tarief van €{self._fixed:.2f}/kWh zou je "
                f"€{abs(saving_eur):.0f} minder betaald hebben. "
                f"Overweeg of je laadgedrag (EV, boiler) beter op goedkope uren afgestemd kan worden."
            )

    def _empty_result(self) -> BillSimResult:
        return BillSimResult(
            dynamic_cost_eur=0, dynamic_import_kwh=0, dynamic_export_kwh=0,
            fixed_cost_eur=0, fixed_tariff=self._fixed,
            day_night_cost_eur=0, day_tariff=self._day, night_tariff=self._night,
            saving_vs_fixed_eur=0, saving_vs_fixed_pct=0,
            best_month="", worst_month="",
            months_dynamic_won=0, months_data=0,
            hours_recorded=len(self._hours),
            advice="Wacht 24 uur — de simulator heeft minimaal 24 uur data nodig.",
        )

    # ── Opslaan ──────────────────────────────────────────────────────────

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "hours": [h.to_list() for h in self._hours],
            })
            self._dirty     = False
            self._last_save = time.time()

    def update_tariffs(
        self,
        fixed:      Optional[float] = None,
        day:        Optional[float] = None,
        night:      Optional[float] = None,
        return_pct: Optional[float] = None,
    ) -> None:
        """Pas tarieven aan (vanuit options flow of service call)."""
        if fixed      is not None: self._fixed      = fixed
        if day        is not None: self._day        = day
        if night      is not None: self._night      = night
        if return_pct is not None: self._return_pct = return_pct
