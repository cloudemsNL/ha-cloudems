# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS BatterySavingsTracker — v1.0.0

Houdt bij hoeveel de thuisbatterij de gebruiker heeft bespaard, uitgesplitst naar:
  1. Eigenverbruik-besparing: batterij voorkomt import (bespaart volle importprijs)
  2. Arbitrage-besparing: goedkoop laden, duur ontladen (gecorrigeerd voor saldering)
  3. PV-zelfconsumptie: PV surplus opgeslagen i.p.v. teruggeleverd (saldering-bewust)

Saldering-correctie (NL WEK):
  2026 — 36%: exportwaarde = 36% × importprijs → eigenverbruik loont veel meer dan export
  2027 —  0%: export levert niets → alleen eigenverbruik en arbitrage tellen

Data-acquisitie: coordinator geeft elk update-interval door:
  - battery_power_w:    ontlaadvermogen (positief = ontladen, negatief = laden)
  - solar_power_w:      huidig PV-vermogen
  - grid_power_w:       netimport (positief = import, negatief = export)
  - house_load_w:       huisverbruik (berekend of direct)
  - current_price:      huidige importprijs (€/kWh, all-in)
  - charge_price:       prijs waartegen de huidige lading geladen is (€/kWh)
  - interval_s:         meetinterval in seconden (default 10s)

Output (HA sensor-attributen):
  - total_savings_eur           — totale besparing (lopend jaar)
  - eigenverbruik_savings_eur   — via directe huisdekking
  - arbitrage_savings_eur       — via prijs-arbitrage (gecorrigeerd voor saldering)
  - pv_selfconsumption_eur      — PV die opgeslagen werd i.p.v. teruggeleverd
  - saldering_loss_eur          — gederfde waarde door salderingsafbouw (informatief)
  - sessions_today              — aantal laad+ontlaadcycli vandaag
  - kwh_charged_today           — geladen kWh vandaag
  - kwh_discharged_today        — ontladen kWh vandaag
  - year / saldering_pct        — huidig jaar en salderingsniveau

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .saldering_context import SalderingContext, BATTERY_ROUNDTRIP_EFFICIENCY

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_battery_savings_v1"
STORAGE_VERSION = 1

# Minimaal ontlaadvermogen om te tellen als actief ontladen (W)
MIN_DISCHARGE_W = 100.0
MIN_CHARGE_W    = 100.0


@dataclass
class DailySavings:
    """Besparingen voor één kalenderdag."""
    date_str:               str
    eigenverbruik_eur:      float = 0.0   # batterij dekte huislast direct
    arbitrage_eur:          float = 0.0   # laad goedkoop – ontlaad duur (na saldering)
    pv_selfconsumption_eur: float = 0.0   # PV opgeslagen i.p.v. teruggeleverd
    saldering_loss_eur:     float = 0.0   # gederfde exportwaarde door salderingsafbouw
    kwh_charged:            float = 0.0
    kwh_discharged:         float = 0.0
    sessions:               int   = 0     # voltooide laad+ontlaadcycli
    # Lopende laadsessie
    _session_charge_price:  float = 0.0   # gewogen gem. laadprijs lopende sessie
    _session_charge_kwh:    float = 0.0


@dataclass
class YearlySavings:
    """Gecumuleerde besparingen per kalenderjaar."""
    year:                   int
    eigenverbruik_eur:      float = 0.0
    arbitrage_eur:          float = 0.0
    pv_selfconsumption_eur: float = 0.0
    saldering_loss_eur:     float = 0.0
    kwh_charged:            float = 0.0
    kwh_discharged:         float = 0.0
    sessions:               int   = 0


class BatterySavingsTracker:
    """
    Registreert financiële besparingen van de thuisbatterij.

    Aangemaakt door de coordinator:
        tracker = BatterySavingsTracker(hass, config)
        await tracker.async_setup()

    Elke coordinator-cyclus:
        await tracker.async_update(
            battery_power_w = data["battery_power"],
            solar_power_w   = data["solar_power"],
            grid_power_w    = data["grid_power"],
            house_load_w    = house_load,
            current_price   = price_info["current"],
            interval_s      = 10,
        )

    Sensor-output:
        attrs = tracker.get_sensor_attributes()
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self._today:  DailySavings  = DailySavings(date_str=str(date.today()))
        self._yearly: dict[int, YearlySavings] = {}

        # Saldering-context: automatisch correct voor huidig jaar
        self._sal_ctx = SalderingContext.for_current_year(
            cycle_cost=float(config.get("battery_cycle_cost_eur_kwh", 0.044))
        )

        # State tracking
        self._prev_soc:     Optional[float] = None
        self._is_charging:  bool = False
        self._is_discharging: bool = False
        self._last_date:    str  = str(date.today())

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        self._load_state(saved)
        _LOGGER.info(
            "BatterySavingsTracker: setup (jaar %d, saldering %d%%)",
            self._sal_ctx.year, round(self._sal_ctx.saldering_pct * 100)
        )

    async def async_save(self) -> None:
        await self._store.async_save(self._build_save_data())

    # ── Hoofd update methode ───────────────────────────────────────────────────

    async def async_update(
        self,
        battery_power_w:  float,
        solar_power_w:    float,
        grid_power_w:     float,
        house_load_w:     float,
        current_price:    float,
        charge_price:     Optional[float] = None,
        interval_s:       float = 10.0,
    ) -> None:
        """
        Verwerk één meetinterval en accumuleer besparingen.

        Args:
            battery_power_w:  positief = ontladen, negatief = laden (W)
            solar_power_w:    PV-vermogen (W, altijd ≥ 0)
            grid_power_w:     netimport (positief = import, negatief = export)
            house_load_w:     huisverbruik (W, altijd ≥ 0)
            current_price:    all-in importprijs (€/kWh)
            charge_price:     prijs waartegen geladen is (€/kWh); None = current_price
            interval_s:       meetinterval (seconden)
        """
        today_str = str(date.today())

        # v4.5.7: negatieve prijs betekent geen besparing voor batterij-arbitrage.
        # Clamp naar 0 zodat besparingen niet negatief worden. Powerplay-logica
        # (zelf profiteren van negatieve prijs) zit elders in tariff_optimizer.
        current_price = max(0.0, current_price)
        if charge_price is not None:
            charge_price = max(0.0, charge_price)

        # Dagwissel: zet dagdata over naar yearly en reset
        if today_str != self._last_date:
            self._rollover_day()
            self._last_date = today_str
            # Herinitialiseer saldering-context (kan jaarwisseling zijn)
            self._sal_ctx = SalderingContext.for_current_year(
                cycle_cost=float(self._config.get("battery_cycle_cost_eur_kwh", 0.044))
            )

        # kWh voor dit interval
        interval_h  = interval_s / 3600.0
        discharge_w = max(0.0, battery_power_w)
        charge_w    = max(0.0, -battery_power_w)
        kwh_out     = discharge_w * interval_h / 1000.0
        kwh_in      = charge_w   * interval_h / 1000.0

        # ── 1. EIGENVERBRUIK-BESPARING ─────────────────────────────────────────
        # Fractie van ontladen die direct het huis dekt (niet naar net).
        # Dit bespaart altijd de volle importprijs, ongeacht saldering.
        if discharge_w >= MIN_DISCHARGE_W and house_load_w > 0:
            house_covered_w = min(discharge_w, house_load_w)
            house_fraction  = house_covered_w / discharge_w
            # Alleen het eigenverbruikdeel
            ev_saving = kwh_out * house_fraction * current_price
            self._today.eigenverbruik_eur += ev_saving

        # ── 2. ARBITRAGE-BESPARING ─────────────────────────────────────────────
        # Besparing door prijsverschil laden vs. ontladen, gecorrigeerd voor saldering.
        # Het exportdeel (niet eigenverbruik) krijgt alleen saldering% van importprijs.
        if discharge_w >= MIN_DISCHARGE_W:
            cp = charge_price if charge_price is not None else current_price * 0.7
            if house_load_w > 0 and discharge_w > 0:
                export_fraction = max(0.0, 1.0 - min(1.0, house_load_w / discharge_w))
            else:
                export_fraction = 1.0

            # Eigenverbruikdeel spaart volle prijs; exportdeel krijgt saldering%
            effective_sell = (
                (1.0 - export_fraction) * current_price
                + export_fraction * current_price * self._sal_ctx.saldering_pct
            )
            # Netto arbitrage na laadkosten en cyclusverlies
            net_arb = (effective_sell * BATTERY_ROUNDTRIP_EFFICIENCY
                       - cp - self._sal_ctx.cycle_cost_eur_kwh)
            if net_arb > 0:
                self._today.arbitrage_eur += kwh_out * net_arb

            # Informatief: gederfde exportwaarde door salderingsafbouw
            # (wat we hadden verdiend bij 100% saldering, minus wat we nu verdienen)
            if self._sal_ctx.saldering_pct < 1.0 and export_fraction > 0:
                full_export_value   = kwh_out * export_fraction * current_price
                actual_export_value = kwh_out * export_fraction * current_price * self._sal_ctx.saldering_pct
                self._today.saldering_loss_eur += max(0.0, full_export_value - actual_export_value)

        # ── 3. PV-ZELFCONSUMPTIE BESPARING ────────────────────────────────────
        # Als de batterij geladen wordt terwijl er PV is, wordt PV opgeslagen
        # i.p.v. teruggeleverd. Waarde = wat we zouden missen = saldering% × prijs.
        # (Bij 0% saldering is PV opslaan alleen waardevol als we het later zelf gebruiken)
        if charge_w >= MIN_CHARGE_W and solar_power_w > MIN_CHARGE_W:
            pv_charged_w = min(charge_w, solar_power_w)
            pv_kwh       = pv_charged_w * interval_h / 1000.0
            # Waarde van opgeslagen PV = voorkomen import later (vol roundtrip voordeel)
            # minus wat de export zou hebben opgebracht (saldering%)
            pv_save = pv_kwh * current_price * BATTERY_ROUNDTRIP_EFFICIENCY
            pv_lost_export = pv_kwh * current_price * self._sal_ctx.saldering_pct
            self._today.pv_selfconsumption_eur += max(0.0, pv_save - pv_lost_export)

        # ── Accumuleer kWh ─────────────────────────────────────────────────────
        if charge_w >= MIN_CHARGE_W:
            self._today.kwh_charged += kwh_in
            # Track gemiddelde laadprijs voor deze sessie
            total_charged = self._today._session_charge_kwh + kwh_in
            if total_charged > 0:
                self._today._session_charge_price = (
                    (self._today._session_charge_price * self._today._session_charge_kwh
                     + (charge_price or current_price) * kwh_in)
                    / total_charged
                )
                self._today._session_charge_kwh = total_charged
            self._is_charging = True
            if self._is_discharging:
                # Overgang ontladen→laden = nieuwe sessie
                self._today.sessions += 1
                self._is_discharging = False

        elif discharge_w >= MIN_DISCHARGE_W:
            self._today.kwh_discharged += kwh_out
            self._is_discharging = True
            if self._is_charging:
                self._is_charging = False
                # Reset sessie laadprijs voor de volgende cyclus
                self._today._session_charge_kwh   = 0.0
                self._today._session_charge_price  = 0.0
        else:
            if self._is_charging or self._is_discharging:
                if self._is_discharging:
                    self._today.sessions += 1
                self._is_charging    = False
                self._is_discharging = False

    # ── Sensor output ──────────────────────────────────────────────────────────

    def get_sensor_attributes(self) -> dict:
        """HA sensor-attributen — state = totale besparing vandaag (€)."""
        year = self._sal_ctx.year
        yearly = self._yearly.get(year, YearlySavings(year=year))

        today_total = (
            self._today.eigenverbruik_eur
            + self._today.arbitrage_eur
            + self._today.pv_selfconsumption_eur
        )
        year_total = (
            yearly.eigenverbruik_eur + self._today.eigenverbruik_eur
            + yearly.arbitrage_eur + self._today.arbitrage_eur
            + yearly.pv_selfconsumption_eur + self._today.pv_selfconsumption_eur
        )

        return {
            # Vandaag
            "savings_today_eur":             round(today_total, 3),
            "eigenverbruik_today_eur":       round(self._today.eigenverbruik_eur, 3),
            "arbitrage_today_eur":           round(self._today.arbitrage_eur, 3),
            "pv_selfconsumption_today_eur":  round(self._today.pv_selfconsumption_eur, 3),
            "saldering_loss_today_eur":      round(self._today.saldering_loss_eur, 3),
            "kwh_charged_today":             round(self._today.kwh_charged, 2),
            "kwh_discharged_today":          round(self._today.kwh_discharged, 2),
            "sessions_today":                self._today.sessions,
            # Huidig jaar (inclusief vandaag)
            "savings_year_eur":              round(year_total, 2),
            "eigenverbruik_year_eur":        round(yearly.eigenverbruik_eur + self._today.eigenverbruik_eur, 2),
            "arbitrage_year_eur":            round(yearly.arbitrage_eur + self._today.arbitrage_eur, 2),
            "pv_selfconsumption_year_eur":   round(yearly.pv_selfconsumption_eur + self._today.pv_selfconsumption_eur, 2),
            "saldering_loss_year_eur":       round(yearly.saldering_loss_eur + self._today.saldering_loss_eur, 2),
            "kwh_charged_year":              round(yearly.kwh_charged + self._today.kwh_charged, 1),
            "kwh_discharged_year":           round(yearly.kwh_discharged + self._today.kwh_discharged, 1),
            "sessions_year":                 yearly.sessions + self._today.sessions,
            # Saldering context
            "year":                          year,
            "saldering_pct":                 round(self._sal_ctx.saldering_pct * 100, 0),
            "saldering_fully_abolished":     self._sal_ctx.saldering_pct == 0.0,
            # Historische jaren
            "history_years": [
                {
                    "year":                  y.year,
                    "total_eur":             round(y.eigenverbruik_eur + y.arbitrage_eur + y.pv_selfconsumption_eur, 2),
                    "eigenverbruik_eur":     round(y.eigenverbruik_eur, 2),
                    "arbitrage_eur":         round(y.arbitrage_eur, 2),
                    "pv_selfconsumption_eur":round(y.pv_selfconsumption_eur, 2),
                    "saldering_loss_eur":    round(y.saldering_loss_eur, 2),
                    "kwh_charged":           round(y.kwh_charged, 1),
                    "kwh_discharged":        round(y.kwh_discharged, 1),
                    "sessions":              y.sessions,
                }
                for y in sorted(self._yearly.values(), key=lambda x: x.year, reverse=True)
            ],
        }

    def get_state_value(self) -> float:
        """State van de HA-sensor: totale besparing lopend jaar (€)."""
        year   = self._sal_ctx.year
        yearly = self._yearly.get(year, YearlySavings(year=year))
        return round(
            yearly.eigenverbruik_eur + self._today.eigenverbruik_eur
            + yearly.arbitrage_eur   + self._today.arbitrage_eur
            + yearly.pv_selfconsumption_eur + self._today.pv_selfconsumption_eur,
            2
        )

    # ── Interne helpers ────────────────────────────────────────────────────────

    def _rollover_day(self) -> None:
        """Dagwissel: voeg dagdata toe aan jaardata en reset dag."""
        year = self._sal_ctx.year
        if year not in self._yearly:
            self._yearly[year] = YearlySavings(year=year)
        y = self._yearly[year]
        y.eigenverbruik_eur      += self._today.eigenverbruik_eur
        y.arbitrage_eur          += self._today.arbitrage_eur
        y.pv_selfconsumption_eur += self._today.pv_selfconsumption_eur
        y.saldering_loss_eur     += self._today.saldering_loss_eur
        y.kwh_charged            += self._today.kwh_charged
        y.kwh_discharged         += self._today.kwh_discharged
        y.sessions               += self._today.sessions
        self._today = DailySavings(date_str=str(date.today()))

    def _build_save_data(self) -> dict:
        return {
            "today": {
                "date_str":              self._today.date_str,
                "eigenverbruik_eur":     self._today.eigenverbruik_eur,
                "arbitrage_eur":         self._today.arbitrage_eur,
                "pv_selfconsumption_eur":self._today.pv_selfconsumption_eur,
                "saldering_loss_eur":    self._today.saldering_loss_eur,
                "kwh_charged":           self._today.kwh_charged,
                "kwh_discharged":        self._today.kwh_discharged,
                "sessions":              self._today.sessions,
            },
            "yearly": {
                str(year): {
                    "year":                  y.year,
                    "eigenverbruik_eur":     y.eigenverbruik_eur,
                    "arbitrage_eur":         y.arbitrage_eur,
                    "pv_selfconsumption_eur":y.pv_selfconsumption_eur,
                    "saldering_loss_eur":    y.saldering_loss_eur,
                    "kwh_charged":           y.kwh_charged,
                    "kwh_discharged":        y.kwh_discharged,
                    "sessions":              y.sessions,
                }
                for year, y in self._yearly.items()
            },
        }

    def _load_state(self, saved: dict) -> None:
        today_str = str(date.today())
        raw_today = saved.get("today", {})
        if raw_today.get("date_str") == today_str:
            self._today = DailySavings(
                date_str               = today_str,
                eigenverbruik_eur      = float(raw_today.get("eigenverbruik_eur", 0)),
                arbitrage_eur          = float(raw_today.get("arbitrage_eur", 0)),
                pv_selfconsumption_eur = float(raw_today.get("pv_selfconsumption_eur", 0)),
                saldering_loss_eur     = float(raw_today.get("saldering_loss_eur", 0)),
                kwh_charged            = float(raw_today.get("kwh_charged", 0)),
                kwh_discharged         = float(raw_today.get("kwh_discharged", 0)),
                sessions               = int(raw_today.get("sessions", 0)),
            )
        for year_str, raw_y in saved.get("yearly", {}).items():
            try:
                year = int(year_str)
                self._yearly[year] = YearlySavings(
                    year                 = year,
                    eigenverbruik_eur    = float(raw_y.get("eigenverbruik_eur", 0)),
                    arbitrage_eur        = float(raw_y.get("arbitrage_eur", 0)),
                    pv_selfconsumption_eur=float(raw_y.get("pv_selfconsumption_eur", 0)),
                    saldering_loss_eur   = float(raw_y.get("saldering_loss_eur", 0)),
                    kwh_charged          = float(raw_y.get("kwh_charged", 0)),
                    kwh_discharged       = float(raw_y.get("kwh_discharged", 0)),
                    sessions             = int(raw_y.get("sessions", 0)),
                )
            except (ValueError, KeyError):
                pass
