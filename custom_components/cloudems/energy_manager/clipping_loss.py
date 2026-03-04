"""
CloudEMS Clipping Verlies Calculator — v1.0.0

Clipping-detectie bestaat al in coordinator.py (CLIPPING_RATIO = 0.97).
Deze module gaat verder: hoe VEEL verlies leidt het tot en loont uitbreiding?

Wat is clipping?
  Panelen produceren meer dan de omvormer aankan (omvormergrens bereikt).
  De omvormer "knipt" de bovenkant af → verloren energie.
  Typisch bij: te veel panelen t.o.v. omvormer, middagzon, kleine oostwest-string.

Wat dit module berekent:
  1. kWh verlies per dag per omvormer (geschat via piekverlengingsmethode)
  2. Geaccumuleerd verlies: week / maand / jaar
  3. Financiële waarde: verlies × actuele EPEX-verkoopprijs
  4. Terugverdientijd uitbreiding: "Grotere omvormer kost €500, terugverdient in 3.4 jaar"
  5. Detecteert ook netbeheerder feed-in curtailment (anders patroon dan hardware clipping)

Methode voor verlies-schatting:
  Per clipping-event: surplus_w = current_w - peak_w
  Maar current_w IS al geclipped... dus we meten via duurextensie:
  "Hoe lang duurt de plateau-fase?" × "Wat zou de piekwaarde zijn zonder begrenzing?"
  
  Praktische benadering:
  • Detecteer plateau: power_w stabiel binnen 2% voor > N minuten tijdens zonnige uren
  • Schat verwacht piekvermogen via forecast of seizoensprofiel
  • Verschil = geclipte waarde per uur

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

STORAGE_KEY     = "cloudems_clipping_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 600

# Minimale duur plateau voor clipping-registratie (minuten)
MIN_PLATEAU_MIN  = 15
# Stabiliteitsmarge plateau (% variatie)
PLATEAU_MARGIN   = 0.03
# Minimaal vermogen om clipping te kunnen detecteren (W)
MIN_POWER_CLIPPING = 500
# Gemiddelde feed-in prijs NL (als fallback)
DEFAULT_FEEDIN_EUR_KWH = 0.08


@dataclass
class ClippingEvent:
    inverter_id:  str
    start_ts:     float
    end_ts:       float
    plateau_w:    float    # stabiel gemeten vermogen (omvormergrens)
    estimated_peak_w: float  # verwacht vermogen zonder begrenzing
    lost_kwh:     float    # geschat verlies

    def to_dict(self) -> dict:
        return {
            "inverter_id": self.inverter_id,
            "start_ts": round(self.start_ts), "end_ts": round(self.end_ts),
            "plateau_w": round(self.plateau_w, 1),
            "estimated_peak_w": round(self.estimated_peak_w, 1),
            "lost_kwh": round(self.lost_kwh, 4),
        }


@dataclass
class InverterClippingStats:
    inverter_id:  str
    label:        str
    events_7d:    int
    events_30d:   int
    kwh_lost_7d:  float
    kwh_lost_30d: float
    kwh_lost_year_est: float
    eur_lost_year_est: float
    plateau_w:    float      # geleerde omvormergrens (W)
    max_observed_w: float    # maximaal gezien boven plateau (toont mogelijke uitbreiding)
    curtailment_suspected: bool   # feed-in curtailment door netbeheerder?
    payback_years: Optional[float]  # terugverdientijd uitbreiding omvormer


@dataclass
class ClippingLossData:
    """Output voor de HA-sensor."""
    total_kwh_lost_30d:   float
    total_eur_lost_year:  float
    inverters:            list[dict]
    worst_inverter:       str
    advice:               str
    any_curtailment:      bool
    expansion_roi_years:  Optional[float]  # snelste ROI over alle omvormers


class ClippingLossCalculator:
    """
    Berekent hoeveel energie en geld er verloren gaat door clipping.

    Gebruik vanuit coordinator:
        calc.tick(inverter_id, label, power_w, estimated_peak_w, is_clipping)
        data = calc.get_data(feedin_price_eur_kwh, expansion_cost_eur)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._events: list[ClippingEvent] = []

        # Per-omvormer plateau-tracker (lopend event)
        self._active: dict[str, dict] = {}   # inverter_id → {start_ts, readings}

        self._dirty    = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for d in saved.get("events", []):
            try:
                self._events.append(ClippingEvent(**d))
            except Exception:
                pass
        self._events = self._events[-2000:]  # max 2000 events
        _LOGGER.info("ClippingCalculator: %d events geladen", len(self._events))

    def tick(
        self,
        inverter_id:      str,
        label:            str,
        power_w:          float,
        estimated_peak_w: float,
        is_clipping:      bool,
    ) -> None:
        """
        Registreer huidige status per omvormer (elke 10s).

        estimated_peak_w: wat de PV-forecast zegt dat de omvormer zou moeten produceren
                          (of het seizoenprofiel). Als onbekend: gebruik 0 (event wordt
                          dan zonder verlies-schatting opgeslagen).
        """
        if power_w < MIN_POWER_CLIPPING:
            self._close_active(inverter_id)
            return

        if is_clipping:
            if inverter_id not in self._active:
                self._active[inverter_id] = {
                    "label":    label,
                    "start_ts": time.time(),
                    "readings": [power_w],
                    "peak_estimates": [estimated_peak_w] if estimated_peak_w > 0 else [],
                }
            else:
                self._active[inverter_id]["readings"].append(power_w)
                if estimated_peak_w > 0:
                    self._active[inverter_id]["peak_estimates"].append(estimated_peak_w)
        else:
            self._close_active(inverter_id)

    def _close_active(self, inverter_id: str) -> None:
        if inverter_id not in self._active:
            return
        act = self._active.pop(inverter_id)
        duration_min = (time.time() - act["start_ts"]) / 60

        if duration_min < MIN_PLATEAU_MIN:
            return  # te kort voor een registreerbaar event

        readings         = act["readings"]
        plateau_w        = sum(readings) / len(readings)
        peak_estimates   = act["peak_estimates"]
        estimated_peak_w = sum(peak_estimates) / len(peak_estimates) if peak_estimates else plateau_w * 1.15

        # Lost kWh = (estimated_peak - plateau) × duration_h
        duration_h = duration_min / 60.0
        surplus_w  = max(0.0, estimated_peak_w - plateau_w)
        lost_kwh   = round(surplus_w * duration_h / 1000.0, 4)

        event = ClippingEvent(
            inverter_id      = inverter_id,
            start_ts         = act["start_ts"],
            end_ts           = time.time(),
            plateau_w        = round(plateau_w, 1),
            estimated_peak_w = round(estimated_peak_w, 1),
            lost_kwh         = lost_kwh,
        )
        self._events.append(event)
        self._dirty = True

        if lost_kwh > 0.01:
            _LOGGER.debug(
                "Clipping event afgesloten: %s | %.0f min | %.0fW plateau | "
                "%.0fW geschat piek | %.3f kWh verlies",
                inverter_id, duration_min, plateau_w, estimated_peak_w, lost_kwh,
            )

    def get_data(
        self,
        feedin_price_eur_kwh: float = DEFAULT_FEEDIN_EUR_KWH,
        expansion_cost_eur: float = 500.0,
    ) -> ClippingLossData:
        now   = time.time()
        d7    = now - 7  * 86400
        d30   = now - 30 * 86400

        # Groepeer per omvormer
        inv_stats: dict[str, dict] = {}
        for ev in self._events:
            if ev.inverter_id not in inv_stats:
                inv_stats[ev.inverter_id] = {
                    "events_7d": 0, "events_30d": 0,
                    "kwh_7d": 0.0, "kwh_30d": 0.0,
                    "plateaus": [], "peaks": [],
                }
            s = inv_stats[ev.inverter_id]
            if ev.start_ts > d7:
                s["events_7d"] += 1
                s["kwh_7d"]    += ev.lost_kwh
            if ev.start_ts > d30:
                s["events_30d"] += 1
                s["kwh_30d"]    += ev.lost_kwh
            s["plateaus"].append(ev.plateau_w)
            s["peaks"].append(ev.estimated_peak_w)

        # Kijk in het active dict ook mee voor het label
        active_labels = {inv_id: v["label"] for inv_id, v in self._active.items()}

        # Bouw stats per omvormer
        stats_list: list[InverterClippingStats] = []
        for inv_id, s in inv_stats.items():
            plateau_w  = max(s["plateaus"]) if s["plateaus"] else 0.0
            max_peak   = max(s["peaks"])    if s["peaks"]    else plateau_w

            # Jaar-schatting: schaal 30-daags verlies op naar jaar
            kwh_year   = round(s["kwh_30d"] / 30 * 365, 1) if s["kwh_30d"] > 0 else 0.0
            eur_year   = round(kwh_year * feedin_price_eur_kwh, 2)

            # Curtailment-vermoeden: plateau exact op round number (netbeheerder limiet?)
            curtailment = plateau_w > 0 and abs(plateau_w % 1000) < 50

            # Terugverdientijd uitbreiding
            payback = round(expansion_cost_eur / eur_year, 1) if eur_year > 5 else None

            stats_list.append(InverterClippingStats(
                inverter_id     = inv_id,
                label           = active_labels.get(inv_id, inv_id[-8:]),
                events_7d       = s["events_7d"],
                events_30d      = s["events_30d"],
                kwh_lost_7d     = round(s["kwh_7d"], 2),
                kwh_lost_30d    = round(s["kwh_30d"], 2),
                kwh_lost_year_est = kwh_year,
                eur_lost_year_est = eur_year,
                plateau_w       = plateau_w,
                max_observed_w  = max_peak,
                curtailment_suspected = curtailment,
                payback_years   = payback,
            ))

        total_30d  = round(sum(s.kwh_lost_30d  for s in stats_list), 2)
        total_year = round(sum(s.eur_lost_year_est for s in stats_list), 2)
        any_curtailment = any(s.curtailment_suspected for s in stats_list)

        # Ergste omvormer
        worst = max(stats_list, key=lambda s: s.eur_lost_year_est, default=None)
        worst_label = worst.label if worst else "—"

        # Beste ROI uitbreiding
        paybacks = [s.payback_years for s in stats_list if s.payback_years is not None]
        best_roi = min(paybacks) if paybacks else None

        # Advies
        if not stats_list or total_30d < 0.5:
            advice = "Geen significant clipping-verlies gedetecteerd. Panelen en omvormer zijn goed op elkaar afgestemd."
        elif best_roi and best_roi < 5:
            advice = (
                f"Clipping kost ~€{total_year:.0f}/jaar. "
                f"Uitbreiding omvormer {worst_label} verdient zich terug in {best_roi:.1f} jaar."
            )
        elif any_curtailment:
            advice = (
                f"Mogelijk feed-in curtailment door netbeheerder gedetecteerd (plateau op round getal). "
                f"Verlies: ~{total_30d:.1f} kWh/30 dagen."
            )
        else:
            advice = (
                f"Clipping-verlies: ~{total_30d:.1f} kWh/30 dagen (~€{total_year:.0f}/jaar). "
                "Overwegen: omvormer uitbreiden of panelen herdistribueren over meer fases."
            )

        return ClippingLossData(
            total_kwh_lost_30d  = total_30d,
            total_eur_lost_year = total_year,
            inverters = [
                {
                    "label":            s.label,
                    "inverter_id":      s.inverter_id,
                    "kwh_lost_7d":      s.kwh_lost_7d,
                    "kwh_lost_30d":     s.kwh_lost_30d,
                    "kwh_lost_year_est":s.kwh_lost_year_est,
                    "eur_lost_year_est":s.eur_lost_year_est,
                    "plateau_w":        s.plateau_w,
                    "payback_years":    s.payback_years,
                    "curtailment_suspected": s.curtailment_suspected,
                }
                for s in stats_list
            ],
            worst_inverter      = worst_label,
            advice              = advice,
            any_curtailment     = any_curtailment,
            expansion_roi_years = best_roi,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "events": [e.to_dict() for e in self._events[-2000:]],
            })
            self._dirty     = False
            self._last_save = time.time()
