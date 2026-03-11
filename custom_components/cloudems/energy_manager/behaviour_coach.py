# -*- coding: utf-8 -*-
"""
CloudEMS Gedragscoach — v1.0.0

Koppelt NILM-schema-data aan historische EPEX-prijzen om per apparaat
te berekenen hoeveel de gebruiker had kunnen besparen door op een ander
uur te draaien.

Algoritme:
  1. NILMSchedule geeft het gemiddeld piek-uur per apparaat per weekdag.
  2. De historische uurprijsdata (uit BillSimulator._hours) geeft de
     werkelijke prijs op het moment dat het apparaat draaide.
  3. Per apparaat berekent de coach: "als je dit apparaat had verschoven
     naar het goedkoopste uur van die dag, hoeveel had je bespaard?"
  4. Besparing = (werkelijke_prijs - goedkoopste_uur_prijs) × kWh_per_sessie
  5. Resultaat per apparaat per maand, plus totaal.

Output:
  • Totale maandelijkse verschuivingsbesparing (€)
  • Per apparaat: typisch uur, goedkoopste uur, verschil (€/maand)
  • Beste verschuiving (meeste besparing in absolute euro's)
  • Advies in gewone taal

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Welke apparaattypes zijn zinvol om te verschuiven?
SHIFTABLE_TYPES = {
    "washing_machine", "dishwasher", "dryer",
    "ev_charger", "boiler", "heat_pump",
}

# Typisch kWh-verbruik per sessie als NILM geen meting heeft
TYPICAL_KWH: dict[str, float] = {
    "washing_machine": 1.2,
    "dishwasher":      1.0,
    "dryer":           2.5,
    "ev_charger":      8.0,
    "boiler":          1.8,
    "heat_pump":       5.0,
}

# Minimum prijs-spread om een aanbeveling te tonen (€/kWh)
MIN_SPREAD_EUR = 0.03
# Minimum maandelijkse besparing om een apparaat te tonen (€)
MIN_SAVING_EUR = 0.50
# Kijkvenster voor prijsdata (uren)
HOURS_LOOKBACK = 30 * 24   # 30 dagen


@dataclass
class DeviceCoachResult:
    """Besparingsanalyse voor één apparaat."""
    device_id:    str
    device_type:  str
    label:        str
    typical_hour: Optional[int]    # gemiddeld uur dat het draait
    cheapest_hour: Optional[int]   # goedkoopste uur op typische draaidagen
    avg_price_at_run: float        # gemiddelde prijs op het moment van draaien
    avg_cheapest_price: float      # gemiddelde goedkoopste uur-prijs
    kwh_per_session:    float
    sessions_per_month: float
    saving_eur_month:   float      # potentiële besparing per maand
    advice:             str


@dataclass
class CoachSummary:
    """Totaalresultaat van de gedragscoach."""
    total_saving_eur_month: float
    devices: list[DeviceCoachResult] = field(default_factory=list)
    best_device:  Optional[str] = None   # label van het apparaat met meeste besparing
    best_saving_eur_month: float = 0.0
    hours_data:   int = 0
    advice:       str = ""


class BehaviourCoach:
    """
    Koppelt NILM-schemapatronen aan EPEX-prijsgeschiedenis om concrete
    verschuivingsbesparingen per apparaat te berekenen.

    Gebruik vanuit coordinator:
        coach = BehaviourCoach()
        summary = coach.analyse(nilm_schedule_summary, hour_records)
    """

    def analyse(
        self,
        schedule_summary: list[dict],
        hour_records: list,          # list[HourRecord] van BillSimulator
        device_energy: list[dict],   # NILM-devices met energy.today_kwh etc.
    ) -> CoachSummary:
        """
        Berekent potentiële besparingen per verschuifbaar apparaat.

        schedule_summary  — uitvoer van NILMScheduleLearner.get_schedule_summary()
        hour_records      — uitvoer van BillSimulator._hours (laatste 30 dagen)
        device_energy     — get_devices_for_ha() uitvoer (voor kWh-metingen)
        """
        if len(hour_records) < 48:
            return CoachSummary(
                total_saving_eur_month=0,
                advice="Nog te weinig prijsdata — beschikbaar na 48 uur.",
                hours_data=len(hour_records),
            )

        # Bouw een prijs-lookup: hour_ts → prijs
        price_by_hour: dict[int, float] = {}
        for rec in hour_records[-HOURS_LOOKBACK:]:
            price_by_hour[rec.ts] = rec.price

        # Bouw een kWh-lookup per apparaat vanuit NILM-energy data
        kwh_lookup: dict[str, float] = {}
        sessions_lookup: dict[str, float] = {}
        for dev in device_energy:
            did    = dev.get("device_id", "")
            energy = dev.get("energy", {})
            month_kwh = float(energy.get("month_kwh", 0) or 0)
            on_events = int(dev.get("on_events", 0) or 0)
            if on_events > 0 and month_kwh > 0:
                kwh_lookup[did]      = month_kwh / max(on_events, 1)
                sessions_lookup[did] = on_events / max(1, (len(hour_records) / 24 / 30))

        # Bouw een dag → [prijs per uur] mapping
        day_prices: dict[str, list[tuple[int, float]]] = {}
        for rec in hour_records[-HOURS_LOOKBACK:]:
            dt  = datetime.fromtimestamp(rec.ts, tz=timezone.utc)
            day = dt.strftime("%Y-%m-%d")
            h   = dt.hour
            day_prices.setdefault(day, []).append((h, rec.price))

        results: list[DeviceCoachResult] = []

        for sched in schedule_summary:
            dtype     = sched.get("device_type", "")
            did       = sched.get("device_id", "")
            label     = sched.get("label") or dtype
            peak_hour = sched.get("peak_hour")
            ready     = sched.get("ready", False)

            if dtype not in SHIFTABLE_TYPES:
                continue
            if not ready or peak_hour is None:
                continue

            # kWh per sessie
            kwh = kwh_lookup.get(did) or TYPICAL_KWH.get(dtype, 1.0)
            sessions_month = sessions_lookup.get(did, 4.0)

            # Bereken voor elke dag in de dataset:
            # - prijs op het typische uur
            # - goedkoopste uur van die dag
            typical_prices: list[float] = []
            cheapest_prices: list[float] = []
            cheapest_hours_list: list[int] = []

            for day, hour_price_list in day_prices.items():
                if len(hour_price_list) < 12:
                    continue   # onvolledige dag, overslaan
                # Prijs op het typische uur
                hp_dict = dict(hour_price_list)
                typ_price = hp_dict.get(peak_hour)
                if typ_price is None:
                    continue
                # Goedkoopste uur van die dag (alleen daguren voor verschuifbare loads)
                candidates = [(h, p) for h, p in hour_price_list if 0 <= h <= 23]
                if not candidates:
                    continue
                cheapest_h, cheapest_p = min(candidates, key=lambda x: x[1])
                typical_prices.append(typ_price)
                cheapest_prices.append(cheapest_p)
                cheapest_hours_list.append(cheapest_h)

            if len(typical_prices) < 7:
                continue   # te weinig data voor betrouwbare schatting

            avg_typical  = sum(typical_prices)  / len(typical_prices)
            avg_cheapest = sum(cheapest_prices) / len(cheapest_prices)
            spread       = avg_typical - avg_cheapest

            if spread < MIN_SPREAD_EUR:
                continue

            saving_per_session = spread * kwh
            saving_month       = round(saving_per_session * sessions_month, 2)

            if saving_month < MIN_SAVING_EUR:
                continue

            # Meest voorkomende goedkoopste uur
            from collections import Counter
            _most_common = Counter(cheapest_hours_list).most_common(1)
            if not _most_common:
                continue
            best_hour = _most_common[0][0]

            advice = (
                f"{label} draait gemiddeld om {peak_hour:02d}:00 "
                f"(€{avg_typical:.3f}/kWh). "
                f"Verschuiven naar {best_hour:02d}:00 (€{avg_cheapest:.3f}/kWh) "
                f"bespaart ca. €{saving_month:.2f}/maand."
            )

            results.append(DeviceCoachResult(
                device_id          = did,
                device_type        = dtype,
                label              = label,
                typical_hour       = peak_hour,
                cheapest_hour      = best_hour,
                avg_price_at_run   = round(avg_typical, 4),
                avg_cheapest_price = round(avg_cheapest, 4),
                kwh_per_session    = round(kwh, 2),
                sessions_per_month = round(sessions_month, 1),
                saving_eur_month   = saving_month,
                advice             = advice,
            ))

        results.sort(key=lambda r: r.saving_eur_month, reverse=True)
        total = round(sum(r.saving_eur_month for r in results), 2)
        best  = results[0] if results else None

        if not results:
            summary_advice = (
                "Geen significante verschuivingsbesparingen gevonden. "
                "Je apparaten draaien al grotendeels op goedkope uren, "
                "of er is nog te weinig data."
            )
        elif total >= 5:
            summary_advice = (
                f"Je kunt tot €{total:.2f}/maand besparen door {len(results)} "
                f"apparaat/apparaten op goedkopere uren in te plannen. "
                f"Grootste kans: {best.label} (€{best.saving_eur_month:.2f}/maand)."
            )
        else:
            summary_advice = (
                f"Potentiële besparing door verschuiving: €{total:.2f}/maand. "
                f"Meeste winst bij {best.label}."
            )

        return CoachSummary(
            total_saving_eur_month = total,
            devices                = results,
            best_device            = best.label if best else None,
            best_saving_eur_month  = best.saving_eur_month if best else 0.0,
            hours_data             = len(hour_records),
            advice                 = summary_advice,
        )

    def to_sensor_dict(self, summary: CoachSummary) -> dict:
        """Flatten to HA sensor attributes dict."""
        return {
            "total_saving_eur_month": summary.total_saving_eur_month,
            "best_device":            summary.best_device,
            "best_saving_eur_month":  summary.best_saving_eur_month,
            "devices": [
                {
                    "label":               r.label,
                    "device_type":         r.device_type,
                    "typical_hour":        r.typical_hour,
                    "cheapest_hour":       r.cheapest_hour,
                    "saving_eur_month":    r.saving_eur_month,
                    "kwh_per_session":     r.kwh_per_session,
                    "sessions_per_month":  r.sessions_per_month,
                    "avg_run_price":       r.avg_price_at_run,
                    "avg_cheap_price":     r.avg_cheapest_price,
                    "advice":              r.advice,
                }
                for r in summary.devices[:8]   # max 8 in attributes
            ],
            "hours_data":             summary.hours_data,
            "advice":                 summary.advice,
        }
