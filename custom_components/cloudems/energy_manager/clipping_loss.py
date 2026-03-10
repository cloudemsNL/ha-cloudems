# -*- coding: utf-8 -*-
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

# Bekende netbeheerder feed-in curtailment limieten (W)
# Gebaseerd op gangbare netten-aansluitingen in NL/BE/DE
GRID_CURTAILMENT_LIMITS_W = [
    1000, 1500, 2000, 2500, 3000, 3450, 3500, 3680,   # kleinverbruik limieten
    4000, 4600, 5000, 5520, 5750, 6000, 6900,           # 3×16A / 3×20A / 3×25A
    8000, 10000, 11040, 13800, 15000, 17250, 20000,     # zakelijk / teruglevering
]
# Tolerantie rondom een curtailment-limiet (% van limiet)
CURTAILMENT_TOLERANCE_PCT = 0.025   # 2.5% = ±250 W op 10 kW


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

        # Per-inverter learned scale factors: plateau→peak ratio history
        self._scale_factors: dict[str, list[float]] = {}

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
        # Restore per-inverter scale factors
        self._scale_factors: dict[str, list[float]] = saved.get("scale_factors", {})
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

        if peak_estimates:
            # Use provided forecast estimate
            estimated_peak_w = sum(peak_estimates) / len(peak_estimates)
            # Learn the scale factor from this observation (only if estimate > plateau)
            if estimated_peak_w > plateau_w:
                scale = estimated_peak_w / plateau_w
                # Only store plausible scale factors (1.0–2.5× = realistic clipping)
                if 1.01 < scale < 2.5:
                    factors = self._scale_factors.setdefault(inverter_id, [])
                    factors.append(round(scale, 3))
                    # Keep last 50 observations
                    self._scale_factors[inverter_id] = factors[-50:]
                    self._dirty = True
        else:
            # No forecast: use learned scale factor if available, else 1.15
            factors = self._scale_factors.get(inverter_id, [])
            if len(factors) >= 3:
                # Use median of learned scale factors — robust to outliers
                sorted_f = sorted(factors)
                learned_scale = sorted_f[len(sorted_f) // 2]
            else:
                learned_scale = 1.15   # conservative default until we have data
            estimated_peak_w = plateau_w * learned_scale

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

    def get_learned_ceiling(self, inverter_id: str) -> Optional[float]:
        """
        Return the self-learned clipping ceiling (W) for an inverter.

        Uses the median of the most recent plateau observations (last 30 days).
        Returns None if fewer than 3 events have been observed (not yet reliable).

        This ceiling represents the *actual* hardware limit as measured in the field —
        it may be lower than the rated power if the inverter is derated, or lower
        than peak_power_w_7d if clipping was happening while that peak was recorded.

        Use this in the coordinator instead of `rated_power_w * 0.95` or
        `peak_power_w_7d * 0.98` to avoid false positives and circular references.
        """
        now = time.time()
        d30 = now - 30 * 86400
        recent_plateaus = [
            ev.plateau_w
            for ev in self._events
            if ev.inverter_id == inverter_id and ev.start_ts > d30
        ]
        # Also include any active observation
        if inverter_id in self._active:
            readings = self._active[inverter_id].get("readings", [])
            if readings:
                recent_plateaus.append(sum(readings) / len(readings))

        if len(recent_plateaus) < 3:
            return None  # not enough data yet

        # Use the 90th-percentile plateau as the learned ceiling.
        # The median would underestimate the true hardware limit because cloudy clipping
        # events tend to produce lower plateaus. The highest confirmed plateaus are the
        # best approximation of the actual inverter ceiling.
        sorted_p = sorted(recent_plateaus)
        idx = max(0, int(len(sorted_p) * 0.90) - 1)
        return round(sorted_p[idx], 1)

    def get_learned_scale_factor(self, inverter_id: str) -> float:
        """
        Return the self-learned peak/plateau ratio for an inverter.
        Used to estimate what the inverter *would* produce without clipping.
        Falls back to 1.15 (conservative default) if fewer than 3 observations.
        """
        factors = self._scale_factors.get(inverter_id, [])
        if len(factors) >= 3:
            sorted_f = sorted(factors)
            return sorted_f[len(sorted_f) // 2]
        return 1.15

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

            # Curtailment-vermoeden: plateau valt binnen 2.5% van een bekende
            # netbeheerder feed-in limiet (bijv. 3680 W, 5000 W, 10000 W).
            # Dit is betrouwbaarder dan `plateau % 1000 < 50` wat ook normale
            # omvormergrenzens kan raken (bijv. 5000 W omvormer → plateau 5000 W).
            curtailment = False
            if plateau_w > 0:
                for limit_w in GRID_CURTAILMENT_LIMITS_W:
                    tol = limit_w * CURTAILMENT_TOLERANCE_PCT
                    if abs(plateau_w - limit_w) <= tol:
                        curtailment = True
                        break

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
        # Zorg dat worst_label nooit een ruwe entity_id is
        if worst:
            lbl = worst.label or ""
            # Als het label eruit ziet als een entity_id (bevat punt, geen spaties), maak er een nette naam van
            if "." in lbl and " " not in lbl:
                lbl = lbl.split(".")[-1].replace("_", " ").title()
            worst_label = lbl or "—"
        else:
            worst_label = "—"

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

    def get_clipping_forecast(
        self,
        inverter_id: str,
        forecast_hourly_w: list[float],   # 24 waarden: verwacht vermogen per uur (vandaag of morgen)
        label: str = "",
    ) -> dict:
        """
        Voorspel hoeveel kWh er geclipped wordt op basis van de PV-forecast
        en de geleerde clipping-grens (ceiling) van deze omvormer.

        Args:
            inverter_id:       HA entity_id van de omvormer
            forecast_hourly_w: lijst van 24 floats (uur 0-23), verwacht vermogen in W
            label:             leesbare naam voor het advies

        Returns dict met:
            ceiling_w:         geleerde clipping-grens (W), None als onbekend
            predicted_clip_kwh: verwacht geclipped energie (kWh)
            clipped_hours:     lijst van uren (0-23) met verwachte clipping
            advice:            tekstadvies
        """
        ceiling_w = self.get_learned_ceiling(inverter_id)
        if ceiling_w is None or ceiling_w < 100:
            return {
                "ceiling_w":          None,
                "predicted_clip_kwh": 0.0,
                "clipped_hours":      [],
                "advice":             "Onvoldoende data om clipping te voorspellen (nog geen geleerde grens).",
            }

        clipped_hours: list[int] = []
        total_clip_kwh = 0.0

        for hour, forecast_w in enumerate(forecast_hourly_w[:24]):
            if forecast_w > ceiling_w:
                clip_w       = forecast_w - ceiling_w
                clip_kwh     = clip_w / 1000.0   # 1 uur = 1 kWh per kW
                total_clip_kwh += clip_kwh
                clipped_hours.append(hour)

        total_clip_kwh = round(total_clip_kwh, 2)
        lbl = label or inverter_id[-8:]

        if total_clip_kwh < 0.05:
            advice = f"{lbl}: geen significante clipping verwacht (grens {ceiling_w:.0f} W)."
        else:
            uren_str = ", ".join(f"{h}:00" for h in clipped_hours)
            advice = (
                f"{lbl}: ~{total_clip_kwh:.1f} kWh clipping verwacht op uren {uren_str}. "
                f"Omvormergrens: {ceiling_w:.0f} W. "
                f"Tip: laad de batterij vóór {min(clipped_hours):02d}:00 om de geclipte energie op te vangen."
                if clipped_hours else
                f"{lbl}: ~{total_clip_kwh:.1f} kWh clipping verwacht (grens {ceiling_w:.0f} W)."
            )

        return {
            "ceiling_w":          round(ceiling_w, 0),
            "predicted_clip_kwh": total_clip_kwh,
            "clipped_hours":      clipped_hours,
            "advice":             advice,
        }

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "events": [e.to_dict() for e in self._events[-2000:]],
                "scale_factors": self._scale_factors,
            })
            self._dirty     = False
            self._last_save = time.time()
