"""
CloudEMS Unified Load Planner — v1.0.0

De kroonjuweel van CloudEMS-planning: combineert ALLE flexibele lasten
en energiebronnen in één geoptimaliseerd schema voor morgen.

Inputs:
  • EPEX-prijzen morgen (beschikbaar na ~13:00)
  • PV forecast morgen (per uur, uit pv_forecast)
  • EV sessie leermodel (verwacht laden morgen?)
  • Micro-mobiliteit (e-bike, scooter — wanneer typisch thuis?)
  • Boiler configuratie (min/max-tijden)
  • Batterij (capaciteit, SoC, max laad/ontlaadstroom)
  • Dag-type classificatie (is morgen een werkdag of weekend?)

Output: één compleet uurschema voor morgen:
  00:00  batterij laden   (goedkoopste uur, 3ct/kWh)
  01:00  batterij laden
  02:00  EV laden         (2e goedkoopste uur, 4ct/kWh)
  ...
  11:00  boiler aan       (PV-surplus verwacht)
  12:00  wasmachine aan   (PV-piek, maximale zelfconsumptie)
  13:00  e-bike laden     (PV-surplus)
  ...
  19:00  batterij ontladen(duurste uur, 28ct/kWh)
  20:00  batterij ontladen

Optimalisatieprincipes (in volgorde van prioriteit):
  1. Veiligheid: EV klaar voor vertrek, batterij niet diep ontladen
  2. PV-surplus eerst: laad zo veel mogelijk met eigen zonnestroom
  3. Goedkoopste EPEX-uren voor resterende laadvraag
  4. Duurste uren: ontlaad batterij of vermijd verbruik
  5. Comfort: boiler niet te vroeg, EV klaar op typisch vertrektijdstip

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Minimale PV-surplus om apparaten op te draaien (W)
PV_SURPLUS_MIN_W = 300
# Aandeel PV dat als "surplus" beschouwd wordt als EV ook laadt
PV_SURPLUS_SHARE = 0.8
# Prioriteit-volgorde voor flexibele lasten
LOAD_PRIORITY = ["battery_charge", "ev_charge", "boiler", "ebike", "washing_machine", "dishwasher"]


@dataclass
class PlannedSlot:
    """Eén uur in het schema."""
    hour:       int
    actions:    list[str]   = field(default_factory=list)
    reasons:    list[str]   = field(default_factory=list)
    pv_w:       float       = 0.0
    price:      float       = 0.0
    net_import_w: float     = 0.0   # geschatte nettoimport dit uur


@dataclass
class LoadPlan:
    """Volledig uurschema voor morgen."""
    date:           str
    generated_at:   str
    slots:          list[PlannedSlot]
    ev_charge_hours:    list[int]
    boiler_hours:       list[int]
    battery_charge_hours:  list[int]
    battery_discharge_hours: list[int]
    ebike_hours:        list[int]
    total_flex_kwh:     float        # totaal geplande flexibele kWh
    pv_utilisation_pct: float        # % van PV dat benut wordt door flexibele lasten
    estimated_savings_eur: float     # schatting besparing t.o.v. ongeoptimaliseerd
    advice:             str
    warnings:           list[str]


def plan_tomorrow(
    *,
    # EPEX prijzen morgen: [{hour: 0, price: 0.05}, ...]
    tomorrow_prices:       list[dict],
    # PV forecast per uur morgen (W): {0: 0, 1: 0, ..., 11: 2400, ...}
    pv_forecast_hourly_w:  dict[int, float],
    # EV
    ev_expected:           bool  = False,
    ev_kwh_needed:         float = 0.0,
    ev_max_kw:             float = 7.4,
    ev_departure_hour:     int   = 8,
    # Micro-mobiliteit
    ebike_sessions:        int   = 0,     # aantal te laden fietsen morgen
    ebike_kwh_per_session: float = 0.5,
    # Boiler
    boiler_power_w:        float = 0.0,
    boiler_min_hour:       int   = 6,
    boiler_max_hour:       int   = 22,
    # Batterij
    battery_soc_pct:       float = 50.0,
    battery_capacity_kwh:  float = 0.0,
    battery_max_charge_kw: float = 0.0,
    battery_min_soc:       float = 20.0,
    # Dag-type
    day_type:              str   = "unknown",
    # Gemiddelde prijs (voor savings berekening)
    avg_price_eur_kwh:     float = 0.15,
) -> LoadPlan:
    """
    Genereer geoptimaliseerd uurschema voor morgen.

    Alle parameters zijn optioneel — de planner werkt met wat beschikbaar is.
    """
    now      = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if not tomorrow_prices:
        return LoadPlan(
            date=tomorrow, generated_at=now.isoformat(),
            slots=[], ev_charge_hours=[], boiler_hours=[],
            battery_charge_hours=[], battery_discharge_hours=[],
            ebike_hours=[], total_flex_kwh=0.0, pv_utilisation_pct=0.0,
            estimated_savings_eur=0.0,
            advice="Geen EPEX-prijzen beschikbaar voor morgen. Probeer na 13:00 CET.",
            warnings=[],
        )

    # Sorteer prijzen
    prices_by_hour = {p["hour"]: p["price"] for p in tomorrow_prices}
    sorted_cheap   = sorted(tomorrow_prices, key=lambda x: x["price"])
    sorted_dear    = sorted(tomorrow_prices, key=lambda x: x["price"], reverse=True)
    min_price      = sorted_cheap[0]["price"]  if sorted_cheap  else 0.0
    max_price      = sorted_dear[0]["price"]   if sorted_dear   else 0.0

    # Initialiseer slots
    slots = {h: PlannedSlot(hour=h, price=prices_by_hour.get(h, avg_price_eur_kwh),
                             pv_w=pv_forecast_hourly_w.get(h, 0.0))
             for h in range(24)}

    planned:      dict[str, set] = {k: set() for k in LOAD_PRIORITY}
    warnings:     list[str]      = []
    total_pv_w    = sum(pv_forecast_hourly_w.values())
    total_pv_kwh  = total_pv_w / 1000.0   # ruwe schatting

    # ── Stap 1: Batterij laden (goedkoopste uren, vóór zonsopgang) ───────────
    if battery_capacity_kwh > 0 and battery_max_charge_kw > 0:
        free_kwh     = max(0.0, (100 - battery_soc_pct) / 100 * battery_capacity_kwh)
        hours_needed = min(6, int(free_kwh / battery_max_charge_kw) + 1)
        night_hours  = [h for h in sorted_cheap if h["hour"] < 8 or h["hour"] > 21]
        for slot_d in night_hours[:hours_needed]:
            h = slot_d["hour"]
            planned["battery_charge"].add(h)
            slots[h].actions.append("⚡ Batterij laden")
            slots[h].reasons.append(f"Goedkoopste nachtuur ({slot_d['price']:.3f} €/kWh)")

    # ── Stap 2: Batterij ontladen (duurste avonduren) ────────────────────────
    if battery_capacity_kwh > 0 and battery_soc_pct > battery_min_soc + 10:
        evening_hours = [h for h in sorted_dear if 17 <= h["hour"] <= 22]
        for slot_d in evening_hours[:3]:
            h = slot_d["hour"]
            planned["battery_charge"].discard(h)
            slots[h].actions.append("🔋 Batterij ontladen")
            slots[h].reasons.append(f"Duurste avonduur ({slot_d['price']:.3f} €/kWh)")

    # ── Stap 3: EV laden (goedkoop + vóór vertrekuur) ───────────────────────
    if ev_expected and ev_kwh_needed > 0 and ev_max_kw > 0:
        ev_hours_needed = int(ev_kwh_needed / ev_max_kw) + 1
        # Prioriteer PV-uren overdag, dan goedkoopste uren 's nachts
        pv_hours   = sorted(
            [h for h, w in pv_forecast_hourly_w.items() if w > PV_SURPLUS_MIN_W and h < ev_departure_hour],
            key=lambda h: -pv_forecast_hourly_w[h]
        )
        night_cheap = [h["hour"] for h in sorted_cheap
                       if h["hour"] < ev_departure_hour and h["hour"] not in planned["battery_charge"]]
        ev_candidate_hours = (pv_hours + night_cheap)[:ev_hours_needed]

        for h in ev_candidate_hours:
            planned["ev_charge"].add(h)
            p = prices_by_hour.get(h, 0.0)
            pv_w = pv_forecast_hourly_w.get(h, 0.0)
            source = f"PV-surplus ({pv_w:.0f}W)" if pv_w > PV_SURPLUS_MIN_W else f"goedkoop uur ({p:.3f} €/kWh)"
            slots[h].actions.append("🚗 EV laden")
            slots[h].reasons.append(source)

        if len(ev_candidate_hours) < ev_hours_needed:
            warnings.append(f"EV: slechts {len(ev_candidate_hours)} goedkope uren beschikbaar voor {ev_departure_hour}:00")

    # ── Stap 4: Boiler (PV-surplus uren) ────────────────────────────────────
    if boiler_power_w > 0:
        pv_surplus_hours = sorted(
            [h for h, w in pv_forecast_hourly_w.items()
             if w > PV_SURPLUS_MIN_W and boiler_min_hour <= h <= boiler_max_hour],
            key=lambda h: -pv_forecast_hourly_w[h]
        )[:4]
        for h in pv_surplus_hours:
            planned["boiler"].add(h)
            slots[h].actions.append("🌡️ Boiler aan")
            slots[h].reasons.append(f"PV-surplus {pv_forecast_hourly_w[h]:.0f}W")

        # Fallback: als geen PV-uren, dan goedkoopste uur overdag
        if not pv_surplus_hours:
            daytime_cheap = [p for p in sorted_cheap if boiler_min_hour <= p["hour"] <= boiler_max_hour]
            if daytime_cheap:
                h = daytime_cheap[0]["hour"]
                planned["boiler"].add(h)
                slots[h].actions.append("🌡️ Boiler aan")
                slots[h].reasons.append(f"Goedkoopste daguur ({daytime_cheap[0]['price']:.3f} €/kWh)")

    # ── Stap 5: E-bike laden (PV-piek uren) ─────────────────────────────────
    if ebike_sessions > 0:
        peak_pv_hours = sorted(
            pv_forecast_hourly_w.items(), key=lambda x: -x[1]
        )
        ebike_hours_planned = 0
        for h, w in peak_pv_hours:
            if ebike_hours_planned >= ebike_sessions:
                break
            if w > 200:  # e-bike lader past ook op kleine surplus
                planned["ebike"].add(h)
                slots[h].actions.append("🚲 E-bike laden")
                slots[h].reasons.append(f"PV-piek {w:.0f}W")
                ebike_hours_planned += 1

    # ── Stap 6: Wasmachine / vaatwasser (PV-piek, dag-type afhankelijk) ─────
    best_solar_window = sorted(
        [(h, w) for h, w in pv_forecast_hourly_w.items() if w > 1000],
        key=lambda x: -x[1]
    )
    if best_solar_window:
        best_h = best_solar_window[0][0]
        slots[best_h].actions.append("🫧 Wasmachine / vaatwasser")
        slots[best_h].reasons.append(f"Optimale PV-piek {best_solar_window[0][1]:.0f}W")

    # ── Berekening totalen ───────────────────────────────────────────────────
    all_flex_hours  = (
        planned["battery_charge"] | planned["ev_charge"] |
        planned["boiler"] | planned["ebike"]
    )
    total_flex_kwh = sum(
        battery_max_charge_kw * (h in planned["battery_charge"]) +
        ev_max_kw             * (h in planned["ev_charge"]) +
        boiler_power_w / 1000 * (h in planned["boiler"]) +
        ebike_kwh_per_session  * (h in planned["ebike"])
        for h in range(24)
    )

    # PV benutting
    pv_used_kwh = sum(
        min(pv_forecast_hourly_w.get(h, 0) / 1000,
            battery_max_charge_kw + ev_max_kw + boiler_power_w / 1000)
        for h in all_flex_hours
    )
    pv_utilisation = min(100.0, pv_used_kwh / max(total_pv_kwh, 0.1) * 100)

    # Geschatte besparing
    savings = sum(
        (avg_price_eur_kwh - prices_by_hour.get(h, avg_price_eur_kwh)) *
        (battery_max_charge_kw + ev_max_kw * (h in planned["ev_charge"]))
        for h in planned["battery_charge"]
    )
    savings = max(0.0, round(savings, 2))

    # Advies
    actions_count = sum(len(s.actions) for s in slots.values())
    if actions_count == 0:
        advice = "Geen flexibele lasten geconfigureerd. Voeg EV, batterij of boiler toe."
    elif total_pv_kwh < 1:
        advice = f"Morgen weinig zon. Schema gebaseerd op {len(sorted_cheap[:3])} goedkoopste uren (min. {min_price:.3f} €/kWh)."
    else:
        advice = (
            f"Morgen ~{total_pv_kwh:.1f} kWh PV verwacht. "
            f"{len(all_flex_hours)} flexibele uren gepland. "
            f"Geschatte besparing: €{savings:.2f} t.o.v. ongeoptimaliseerd."
        )

    return LoadPlan(
        date                     = tomorrow,
        generated_at             = now.isoformat(),
        slots                    = list(slots.values()),
        ev_charge_hours          = sorted(planned["ev_charge"]),
        boiler_hours             = sorted(planned["boiler"]),
        battery_charge_hours     = sorted(planned["battery_charge"]),
        battery_discharge_hours  = sorted(
            h for h, s in slots.items() if any("ontladen" in a for a in s.actions)
        ),
        ebike_hours              = sorted(planned["ebike"]),
        total_flex_kwh           = round(total_flex_kwh, 2),
        pv_utilisation_pct       = round(pv_utilisation, 1),
        estimated_savings_eur    = savings,
        advice                   = advice,
        warnings                 = warnings,
    )


def plan_to_dict(plan: LoadPlan) -> dict:
    """Converteer plan naar dict voor HA-sensor opslag."""
    return {
        "date":                    plan.date,
        "generated_at":            plan.generated_at,
        "ev_charge_hours":         plan.ev_charge_hours,
        "boiler_hours":            plan.boiler_hours,
        "battery_charge_hours":    plan.battery_charge_hours,
        "battery_discharge_hours": plan.battery_discharge_hours,
        "ebike_hours":             plan.ebike_hours,
        "total_flex_kwh":          plan.total_flex_kwh,
        "pv_utilisation_pct":      plan.pv_utilisation_pct,
        "estimated_savings_eur":   plan.estimated_savings_eur,
        "advice":                  plan.advice,
        "warnings":                plan.warnings,
        "slots": [
            {
                "hour":    s.hour,
                "actions": s.actions,
                "reasons": s.reasons,
                "price":   round(s.price, 4),
                "pv_w":    round(s.pv_w, 0),
            }
            for s in plan.slots if s.actions   # alleen uren met geplande acties
        ],
    }
