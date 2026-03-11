# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Gas Graaddagen Analyse — v1.0.0

Nu gas_m3 beschikbaar is via de P1-reader, kunnen we eindelijk:
  1. Gasverbruik correleren met buitentemperatuur (graaddagen)
  2. CV-efficiëntie benchmarken: m³/graaddag vs NL-norm
  3. Seizoenskosten voorspellen voor de winter
  4. Plotselinge verbruiksstijging detecteren (lek, slecht brandende brander)

Graaddagen (Heating Degree Days = HDD):
  HDD = max(0, SETPOINT - gemiddelde_buitentemp)
  Typisch SETPOINT: 18°C (NL norm voor gebouwenergie)

Benchmark NL:
  HR-ketel modern:     0.04–0.07 m³/HDD
  Gemiddeld (NL):      0.08–0.12 m³/HDD  
  Slecht (oud huis):   0.15–0.25 m³/HDD

Formule: gas_efficiency = gas_m3_today / hdd_today  (m³ per graaddag)

Seizoen kosten prognose:
  Verwacht wintergas = gemiddelde m³/HDD × verwachte HDD resterend seizoen
  Omrekenen naar €: × gas_prijs_per_m3

Copyright © 2025 CloudEMS — https://cloudems.eu
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

STORAGE_KEY     = "cloudems_gas_analysis_v1"
STORAGE_VERSION = 1

HDD_SETPOINT_C   = 18.0    # NL-norm stookgrens
GAS_PRICE_DEFAULT= 1.25    # €/m³ — indicatief als geen sensor beschikbaar
SAVE_INTERVAL_S  = 600

# Benchmarks m³/HDD
BENCH_EXCELLENT = 0.06
BENCH_GOOD      = 0.09
BENCH_AVERAGE   = 0.13
BENCH_BAD       = 0.20

# Seizoen HDD-normen NL (gemiddeld per maand)
NL_MONTHLY_HDD = {
    1: 310, 2: 265, 3: 195, 4: 90, 5: 30, 6: 5,
    7: 0,   8: 0,   9: 20, 10: 95, 11: 185, 12: 275,
}


@dataclass
class GasDayRecord:
    """Eén dagrecord voor gas + graaddagen."""
    date:          str
    gas_m3_delta:  float    # verbruikte m³ deze dag
    hdd:           float    # graaddagen deze dag
    efficiency:    float    # m³/HDD (0 als geen verwarming)
    outside_temp:  float    # gemiddelde buitentemp

    def to_dict(self) -> dict:
        return {
            "date": self.date, "gas_m3_delta": round(self.gas_m3_delta, 3),
            "hdd": round(self.hdd, 2), "efficiency": round(self.efficiency, 4),
            "outside_temp": round(self.outside_temp, 1),
        }


@dataclass
class GasAnalysisData:
    """Output voor de HA-sensor."""
    gas_m3_today:        float
    gas_m3_month:        float
    gas_cost_month_eur:  float
    efficiency_m3_hdd:   float         # gemiddeld m³/HDD (30-dag)
    efficiency_rating:   str           # "uitstekend" | "goed" | "gemiddeld" | "slecht"
    hdd_today:           float
    hdd_month:           float
    seasonal_forecast_m3:float         # verwacht gas rest van het stookseizoen
    seasonal_forecast_eur:float
    anomaly:             bool          # plotseling 25%+ meer verbruik?
    anomaly_message:     str
    advice:              str
    records_count:       int
    isolation_advice:    str = ""
    isolation_saving_pct: float = 0.0
    # Periode verbruik (m³) en kosten (€) — v2.6.0
    gas_m3_week:         float = 0.0
    gas_m3_year:         float = 0.0
    gas_cost_today_eur:  float = 0.0
    gas_cost_week_eur:   float = 0.0
    gas_cost_year_eur:   float = 0.0


def _efficiency_rating(m3_per_hdd: float) -> str:
    if m3_per_hdd <= 0:
        return "onbekend"
    if m3_per_hdd < BENCH_EXCELLENT:
        return "uitstekend"
    if m3_per_hdd < BENCH_GOOD:
        return "goed"
    if m3_per_hdd < BENCH_AVERAGE:
        return "gemiddeld"
    return "slecht"


class GasAnalyzer:
    """
    Analyseert gasverbruik via graaddagen en detecteert inefficiënties.

    Aanroep vanuit coordinator:
        analyzer.tick(gas_m3_cumulative, outside_temp_c)
        data = analyzer.get_data(gas_price_eur_m3)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._records: list[GasDayRecord] = []

        # Dag-accumulatoren
        self._today_date         = ""
        self._today_gas_start_m3 = None   # gasstand aan het begin van de dag
        self._today_temps:  list[float] = []   # temperatuurmetingen vandaag
        self._last_gas_m3        = 0.0

        self._month_gas_start_m3 = None   # gasstand begin van de maand
        self._month_key          = ""

        # v2.6.0: week en jaar accumulatoren
        self._week_gas_start_m3  = None   # gasstand begin van de week (ma 00:00)
        self._week_key           = ""     # ISO week "2026-W10"
        self._year_gas_start_m3  = None   # gasstand begin van het jaar (1 jan 00:00)
        self._year_key           = ""     # "2026"

        self._dirty    = False
        self._last_save = 0.0
        # v1.18.1: isolatie-investering tracking
        self._isolation_date: str = ""      # datum van geregistreerde isolatie-investering
        self._pre_isolation_eff: float = 0.0  # gemiddelde m³/HDD vóór de ingreep

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for d in saved.get("records", []):
            try:
                self._records.append(GasDayRecord(**d))
            except Exception:
                pass
        self._last_gas_m3      = float(saved.get("last_gas_m3", 0.0))
        self._isolation_date   = saved.get("isolation_date", "")
        self._pre_isolation_eff = float(saved.get("pre_isolation_eff", 0.0))
        # v4.5.11: herstel periode-startpunten uit opslag zodat periodes na herstart correct zijn
        self._today_date         = saved.get("today_date", "")
        self._month_key          = saved.get("month_key", "")
        self._week_key           = saved.get("week_key", "")
        self._year_key           = saved.get("year_key", "")
        _today_start = saved.get("today_gas_start_m3")
        _month_start = saved.get("month_gas_start_m3")
        _week_start  = saved.get("week_gas_start_m3")
        _year_start  = saved.get("year_gas_start_m3")
        self._today_gas_start_m3 = float(_today_start) if _today_start is not None else None
        self._month_gas_start_m3 = float(_month_start) if _month_start is not None else None
        self._week_gas_start_m3  = float(_week_start)  if _week_start  is not None else None
        self._year_gas_start_m3  = float(_year_start)  if _year_start  is not None else None
        _LOGGER.info("GasAnalyzer: %d dagrecords geladen (isolatiedatum: %s)",
                     len(self._records), self._isolation_date or "geen")

    def register_isolation_investment(self, date_str: str = "") -> None:
        """
        Registreer een isolatie-investering. Sla de huidige efficiëntie op als baseline.
        date_str: datum in YYYY-MM-DD formaat (default: vandaag)
        """
        from datetime import datetime, timezone
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        heating_records = [r for r in self._records[-30:] if r.hdd > 1.0 and r.efficiency > 0]
        if heating_records:
            self._pre_isolation_eff = sum(r.efficiency for r in heating_records) / len(heating_records)
        self._isolation_date = date_str
        self._dirty = True
        _LOGGER.info(
            "GasAnalyzer: isolatie-investering geregistreerd op %s "
            "(baseline efficiëntie: %.4f m³/HDD)",
            date_str, self._pre_isolation_eff,
        )

    def tick(self, gas_m3_cumulative: float, outside_temp_c: float) -> None:
        """
        Registreer huidige gasstand en buitentemperatuur (elke 10s).

        Parameters
        ----------
        gas_m3_cumulative : actuele cumulatieve gasstand (m³) van P1
        outside_temp_c    : buitentemperatuur (°C)
        """
        if gas_m3_cumulative <= 0:
            return

        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        # Dag-reset
        if today != self._today_date:
            if self._today_date and self._last_gas_m3 > 0:
                self._finalize_day()
            self._today_date     = today
            self._today_gas_start_m3 = gas_m3_cumulative
            self._today_temps    = []

        # Maand-reset
        if month != self._month_key:
            self._month_key          = month
            self._month_gas_start_m3 = gas_m3_cumulative

        # Week-reset (ISO weeknummer, begint maandag)
        from datetime import datetime, timezone
        _now_local = datetime.now()
        week_key = f"{_now_local.year}-W{_now_local.isocalendar()[1]:02d}"
        if week_key != self._week_key:
            self._week_key          = week_key
            self._week_gas_start_m3 = gas_m3_cumulative

        # Jaar-reset
        year_key = str(_now_local.year)
        if year_key != self._year_key:
            self._year_key          = year_key
            self._year_gas_start_m3 = gas_m3_cumulative

        self._last_gas_m3 = gas_m3_cumulative
        self._today_temps.append(outside_temp_c)
        self._dirty = True

    def _finalize_day(self) -> None:
        """Sluit dag af en voeg record toe."""
        if not self._today_temps or self._today_gas_start_m3 is None:
            return

        avg_temp    = sum(self._today_temps) / len(self._today_temps)
        hdd         = max(0.0, HDD_SETPOINT_C - avg_temp)
        gas_delta   = max(0.0, self._last_gas_m3 - self._today_gas_start_m3)
        efficiency  = gas_delta / hdd if hdd > 0.5 else 0.0   # geen efficiëntie bij warm weer

        record = GasDayRecord(
            date         = self._today_date,
            gas_m3_delta = gas_delta,
            hdd          = hdd,
            efficiency   = efficiency,
            outside_temp = avg_temp,
        )
        self._records.append(record)
        self._records = self._records[-365:]
        self._dirty   = True

        _LOGGER.info(
            "GasAnalyzer: %s | %.2f m³ | %.1f HDD | %.4f m³/HDD | %.1f°C gem.",
            self._today_date, gas_delta, hdd, efficiency, avg_temp,
        )

    def get_data(self, gas_price_eur_m3: float = GAS_PRICE_DEFAULT) -> GasAnalysisData:
        """Geef gas-analyse data voor sensor."""
        now   = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")

        # Vandaag
        gas_today = max(0.0, self._last_gas_m3 - (self._today_gas_start_m3 or self._last_gas_m3))
        avg_temp_today = (sum(self._today_temps) / len(self._today_temps)) if self._today_temps else 15.0
        hdd_today = max(0.0, HDD_SETPOINT_C - avg_temp_today)

        # Deze week
        gas_week = max(0.0, self._last_gas_m3 - (self._week_gas_start_m3 or self._last_gas_m3))
        cost_week = round(gas_week * gas_price_eur_m3, 2)

        # Dit jaar
        gas_year = max(0.0, self._last_gas_m3 - (self._year_gas_start_m3 or self._last_gas_m3))
        cost_year = round(gas_year * gas_price_eur_m3, 2)

        # Vandaag kosten
        cost_today = round(gas_today * gas_price_eur_m3, 2)

        # Deze maand
        gas_month = max(0.0, self._last_gas_m3 - (self._month_gas_start_m3 or self._last_gas_m3))
        cost_month   = round(gas_month * gas_price_eur_m3, 2)
        month_records= [r for r in self._records if r.date.startswith(month)]
        hdd_month    = sum(r.hdd for r in month_records)

        # Efficiëntie (30 dagen)
        heating_records = [r for r in self._records[-30:] if r.hdd > 1.0 and r.efficiency > 0]
        if heating_records:
            eff = sum(r.efficiency for r in heating_records) / len(heating_records)
        else:
            eff = 0.0
        rating = _efficiency_rating(eff)

        # Seizoensprognose
        remaining_hdd = sum(
            NL_MONTHLY_HDD.get(m, 0)
            for m in range(now.month, 13)
        )
        seasonal_m3  = round(eff * remaining_hdd, 0) if eff > 0 else 0.0
        seasonal_eur = round(seasonal_m3 * gas_price_eur_m3, 2)

        # Anomalie detectie: vergelijk laatste 7 dagen met 14-30 dagen eerder
        anomaly = False
        anomaly_msg = ""
        recent_7  = [r for r in self._records[-7:]  if r.hdd > 1.0 and r.efficiency > 0]
        baseline  = [r for r in self._records[-30:-7] if r.hdd > 1.0 and r.efficiency > 0]
        if len(recent_7) >= 3 and len(baseline) >= 5:
            eff_recent   = sum(r.efficiency for r in recent_7) / len(recent_7)
            eff_baseline = sum(r.efficiency for r in baseline) / len(baseline)
            if eff_baseline > 0 and (eff_recent / eff_baseline) > 1.25:
                anomaly = True
                pct_more = round((eff_recent / eff_baseline - 1) * 100)
                anomaly_msg = (
                    f"Gasverbruik laatste 7 dagen is {pct_more}% hoger dan normaal "
                    f"({eff_recent:.4f} vs {eff_baseline:.4f} m³/HDD). "
                    "Mogelijke oorzaak: CV-storing, tochtige woning of hogere comfortinstellingen."
                )

        # Advies
        if eff <= 0:
            advice = "Onvoldoende data. Wacht op kouder weer (min. 5 stookdagen) voor een efficiëntie-analyse."
        elif rating == "uitstekend":
            advice = f"Uitstekend! Jouw CV-installatie verbruikt slechts {eff:.4f} m³/HDD — nagenoeg HR-ketel optimaal."
        elif rating == "goed":
            advice = f"Goed! Verbruik van {eff:.4f} m³/HDD is beter dan gemiddeld."
        elif rating == "gemiddeld":
            advice = (
                f"Gemiddeld verbruik: {eff:.4f} m³/HDD. "
                f"Een moderne HR-ketel haalt {BENCH_GOOD:.4f}. "
                "Overweeg onderhoud of betere isolatie."
            )
        else:
            advice = (
                f"Hoog gasverbruik: {eff:.4f} m³/HDD — {(eff/BENCH_GOOD-1)*100:.0f}% boven HR-norm. "
                "Laat CV onderhouden en controleer isolatie van vloer/dak/glas."
            )

        if anomaly:
            advice = "⚠️ ANOMALIE GEDETECTEERD: " + anomaly_msg

        # v1.18.1: isolatie-investering terugverdiencheck
        isolation_advice = ""
        isolation_saving_pct = 0.0
        if self._isolation_date and self._pre_isolation_eff > 0 and eff > 0:
            post_records = [
                r for r in self._records
                if r.date >= self._isolation_date and r.hdd > 1.0 and r.efficiency > 0
            ]
            if len(post_records) >= 5:
                post_eff = sum(r.efficiency for r in post_records) / len(post_records)
                saving_pct = (self._pre_isolation_eff - post_eff) / self._pre_isolation_eff * 100
                isolation_saving_pct = round(saving_pct, 1)
                if saving_pct > 5:
                    isolation_advice = (
                        f"✅ Na isolatie-ingreep ({self._isolation_date}): "
                        f"{saving_pct:.0f}% minder gas/graaddag "
                        f"({self._pre_isolation_eff:.4f} → {post_eff:.4f} m³/HDD)."
                    )
                elif saving_pct > -5:
                    isolation_advice = (
                        f"⚠️ Isolatie ({self._isolation_date}): nog geen significant "
                        f"verbruiksverschil meetbaar ({len(post_records)} meetdagen). "
                        "Meer stookdagen nodig voor betrouwbare analyse."
                    )
                else:
                    isolation_advice = (
                        f"⚠️ Isolatie ({self._isolation_date}): verbruik is {abs(saving_pct):.0f}% "
                        f"GESTEGEN na ingreep. Controleer of de meting klopt."
                    )

        return GasAnalysisData(
            gas_m3_today         = round(gas_today, 3),
            gas_m3_month         = round(gas_month, 1),
            gas_cost_month_eur   = cost_month,
            efficiency_m3_hdd    = round(eff, 4),
            efficiency_rating    = rating,
            hdd_today            = round(hdd_today, 2),
            hdd_month            = round(hdd_month, 1),
            seasonal_forecast_m3 = seasonal_m3,
            seasonal_forecast_eur= seasonal_eur,
            anomaly              = anomaly,
            anomaly_message      = anomaly_msg,
            advice               = advice,
            records_count        = len(self._records),
            isolation_advice     = isolation_advice,
            isolation_saving_pct = isolation_saving_pct,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "records":           [r.to_dict() for r in self._records],
                "last_gas_m3":       round(self._last_gas_m3, 3),
                "isolation_date":    self._isolation_date,
                "pre_isolation_eff": round(self._pre_isolation_eff, 6),
                # v4.5.11: bewaar periode-startpunten zodat verbruik na herstart correct is
                "today_date":          self._today_date,
                "month_key":           self._month_key,
                "week_key":            self._week_key,
                "year_key":            self._year_key,
                "today_gas_start_m3":  round(self._today_gas_start_m3, 3) if self._today_gas_start_m3 is not None else None,
                "month_gas_start_m3":  round(self._month_gas_start_m3, 3) if self._month_gas_start_m3 is not None else None,
                "week_gas_start_m3":   round(self._week_gas_start_m3, 3)  if self._week_gas_start_m3  is not None else None,
                "year_gas_start_m3":   round(self._year_gas_start_m3, 3)  if self._year_gas_start_m3  is not None else None,
            })
            self._dirty     = False
            self._last_save = time.time()
