"""
CloudEMS Shower Tracker — v1.0.0

Detecteert douche-sessies via boilertemperatuur-daling en berekent:
  - Duur van de sessie (minuten)
  - Verbruikte liters warm water
  - Kosten van de sessie (€)
  - CO₂-uitstoot (gram)
  - Vergelijking met vorige sessie en huishoudgemiddelde
  - Strafpunten / complimenten

Detectielogica:
  Temperatuurdaling > SHOWER_DETECT_DROP_C in < SHOWER_MAX_DURATION_MIN
  → douche gedetecteerd

Berekening verbruikte energie:
  Q = tankvolume × 4186 × ΔT  (J)
  → kWh = Q / 3.600.000
  → liters gebruikt = Q / (4186 × (T_douche - T_koud))
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Detectie-drempels ────────────────────────────────────────────────────────
SHOWER_DETECT_DROP_C    = 3.0    # min temperatuurdaling om sessie te starten
SHOWER_END_STABLE_S     = 300    # 5 min stabiel → sessie voorbij
SHOWER_MIN_DURATION_S   = 60     # kortere sessies negeren (vals positief)
SHOWER_MAX_DURATION_MIN = 60     # max 60 min (anders iets anders dan douchen)

# ── Berekening defaults ──────────────────────────────────────────────────────
SHOWER_TEMP_C       = 38.0   # comfortabele douchetemperatuur
COLD_WATER_TEMP_C   = 10.0   # koud water temperatuur
FLOW_L_MIN          = 8.0    # gemiddelde douchekop L/min
CO2_GRAM_PER_KWH    = 400.0  # gram CO₂ per kWh elektriciteit (NL mix 2026)

# ── Fun facts drempelwaarden ─────────────────────────────────────────────────
LONG_SHOWER_MIN     = 10.0   # > 10 min = lang
VERY_LONG_MIN       = 15.0   # > 15 min = veel te lang
SHORT_SHOWER_MIN    = 5.0    # < 5 min = korte douche, goed!
OLYMPIC_POOL_L      = 2_500_000  # liter in een olympisch zwembad

MAX_HISTORY         = 30     # bewaar max 30 sessies


@dataclass
class ShowerSession:
    """Één douche-sessie."""
    start_ts:       float
    end_ts:         float = 0.0
    temp_start_c:   float = 0.0
    temp_end_c:     float = 0.0
    tank_liters:    float = 80.0
    elec_price_kwh: float = 0.25
    boiler_label:   str   = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_ts or time.time()) - self.start_ts)

    @property
    def duration_min(self) -> float:
        return round(self.duration_s / 60, 1)

    @property
    def temp_drop_c(self) -> float:
        return max(0.0, self.temp_start_c - self.temp_end_c)

    @property
    def energy_kwh(self) -> float:
        """Energie onttrokken aan de boiler (kWh)."""
        return round(self.tank_liters * 4186 * self.temp_drop_c / 3_600_000, 3)

    @property
    def liters_used(self) -> float:
        """Geschat verbruik warm water in liters."""
        denom = 4186 * (SHOWER_TEMP_C - COLD_WATER_TEMP_C)
        if denom <= 0:
            return 0.0
        return round(self.tank_liters * 4186 * self.temp_drop_c / denom, 1)

    @property
    def cost_eur(self) -> float:
        return round(self.energy_kwh * self.elec_price_kwh, 3)

    @property
    def co2_gram(self) -> float:
        return round(self.energy_kwh * CO2_GRAM_PER_KWH, 0)

    @property
    def flow_l_min(self) -> float:
        """Geschatte flow rate op basis van verbruik en duur."""
        if self.duration_min <= 0:
            return FLOW_L_MIN
        return round(self.liters_used / self.duration_min, 1)

    @property
    def completed(self) -> bool:
        return self.end_ts > 0

    def fun_fact(self, history_avg_min: float = 8.0) -> dict:
        """Geeft een fun fact / beoordeling terug."""
        dur = self.duration_min
        liters = self.liters_used
        cost = self.cost_eur

        if dur < SHORT_SHOWER_MIN:
            rating = "⚡ Militaire douche!"
            msg = f"Snel en efficiënt — {liters:.0f}L in {dur:.0f} min"
            score = "top"
        elif dur < LONG_SHOWER_MIN:
            rating = "✅ Prima douche"
            diff = dur - history_avg_min
            if abs(diff) < 1:
                msg = f"Precies gemiddeld — {liters:.0f}L, €{cost:.2f}"
            elif diff < 0:
                msg = f"{abs(diff):.0f} min korter dan gemiddeld 👍"
            else:
                msg = f"{diff:.0f} min langer dan gemiddeld"
            score = "good"
        elif dur < VERY_LONG_MIN:
            extra_l = liters - (history_avg_min * FLOW_L_MIN)
            rating = "⚠️ Lange douche"
            msg = f"{extra_l:.0f}L extra t.o.v. gemiddeld — €{cost:.2f}"
            score = "warning"
        else:
            bathtubs = liters / 150  # gemiddeld bad = 150L
            rating = "🚨 Erg lang!"
            msg = f"{liters:.0f}L = {bathtubs:.1f}× een bad vullen — €{cost:.2f}"
            score = "alert"

        return {
            "rating":  rating,
            "message": msg,
            "score":   score,
        }

    def to_dict(self) -> dict:
        return {
            "start_ts":     round(self.start_ts, 0),
            "end_ts":       round(self.end_ts, 0),
            "duration_min": self.duration_min,
            "temp_drop_c":  round(self.temp_drop_c, 1),
            "liters":       self.liters_used,
            "energy_kwh":   self.energy_kwh,
            "cost_eur":     self.cost_eur,
            "co2_gram":     self.co2_gram,
            "flow_l_min":   self.flow_l_min,
            "boiler":       self.boiler_label,
        }


class ShowerTracker:
    """
    Detecteert en registreert douche-sessies per boiler.

    Gebruik:
        tracker = ShowerTracker()
        tracker.update(boiler_id, temp_c, tank_l, price_kwh)
        status = tracker.get_status(boiler_id)
    """

    def __init__(self) -> None:
        self._active:  dict[str, ShowerSession] = {}   # boiler_id → actieve sessie
        self._history: dict[str, list[ShowerSession]] = {}  # boiler_id → lijst sessies
        self._last_temp: dict[str, float] = {}
        self._stable_since: dict[str, float] = {}

    def update(self,
               boiler_id:      str,
               temp_c:         float,
               tank_liters:    float = 80.0,
               elec_price_kwh: float = 0.25,
               boiler_label:   str   = "") -> None:
        """Verwerk nieuwe temperatuurmeting."""
        now = time.time()
        prev_temp = self._last_temp.get(boiler_id)
        self._last_temp[boiler_id] = temp_c

        if prev_temp is None:
            return

        delta = prev_temp - temp_c  # positief = afkoeling

        # ── Sessie starten ────────────────────────────────────────────────────
        if boiler_id not in self._active:
            if delta >= SHOWER_DETECT_DROP_C / 10:
                # Begin van temperatuurdaling → mogelijk douche
                if boiler_id not in self._stable_since:
                    # Start tracking maar nog niet officieel sessie
                    self._active[boiler_id] = ShowerSession(
                        start_ts       = now,
                        temp_start_c   = prev_temp,
                        temp_end_c     = temp_c,
                        tank_liters    = tank_liters,
                        elec_price_kwh = elec_price_kwh,
                        boiler_label   = boiler_label,
                    )
        else:
            session = self._active[boiler_id]
            session.temp_end_c = temp_c  # update lopende temp

            # ── Sessie beëindigen ─────────────────────────────────────────────
            if delta <= 0.1:  # temp stijgt of stabiel
                if boiler_id not in self._stable_since:
                    self._stable_since[boiler_id] = now
                elif now - self._stable_since[boiler_id] >= SHOWER_END_STABLE_S:
                    # Lang genoeg stabiel → sessie voorbij
                    session.end_ts = now
                    dur_s = session.duration_s
                    if dur_s >= SHOWER_MIN_DURATION_S:
                        if boiler_id not in self._history:
                            self._history[boiler_id] = []
                        self._history[boiler_id].append(session)
                        if len(self._history[boiler_id]) > MAX_HISTORY:
                            self._history[boiler_id].pop(0)
                        _LOGGER.info(
                            "CloudEMS Douche: %.0f min, %.0fL, €%.2f (ΔT=%.1f°C) [%s]",
                            session.duration_min, session.liters_used,
                            session.cost_eur, session.temp_drop_c, boiler_label,
                        )
                    del self._active[boiler_id]
                    if boiler_id in self._stable_since:
                        del self._stable_since[boiler_id]
            else:
                # Temp daalt nog → reset stable timer
                if boiler_id in self._stable_since:
                    del self._stable_since[boiler_id]

    def get_active(self, boiler_id: str) -> Optional[ShowerSession]:
        return self._active.get(boiler_id)

    def get_last(self, boiler_id: str) -> Optional[ShowerSession]:
        hist = self._history.get(boiler_id, [])
        return hist[-1] if hist else None

    def get_history(self, boiler_id: str, n: int = 10) -> list[dict]:
        hist = self._history.get(boiler_id, [])
        return [s.to_dict() for s in hist[-n:]]

    def get_status(self, boiler_id: str,
                   history_n: int = 10) -> dict:
        """Volledig status-dict voor dashboard."""
        active  = self.get_active(boiler_id)
        last    = self.get_last(boiler_id)
        history = self.get_history(boiler_id, history_n)

        # Gemiddelden over geschiedenis
        if history:
            avg_min   = sum(s["duration_min"] for s in history) / len(history)
            avg_liter = sum(s["liters"] for s in history) / len(history)
            avg_cost  = sum(s["cost_eur"] for s in history) / len(history)
            total_l   = sum(s["liters"] for s in history)
        else:
            avg_min = avg_liter = avg_cost = total_l = 0.0

        # Fun facts
        olympic_pct = round(total_l / OLYMPIC_POOL_L * 100, 4) if total_l else 0

        return {
            # Actieve sessie
            "active": {
                "running":       active is not None,
                "duration_min":  round(active.duration_s / 60, 1) if active else None,
                "temp_drop_c":   round(active.temp_drop_c, 1) if active else None,
                "liters_so_far": active.liters_used if active else None,
                "flow_l_min":    active.flow_l_min if active else None,
            },
            # Laatste sessie
            "last": last.to_dict() if last else None,
            "last_fun_fact": last.fun_fact(avg_min) if last else None,

            # Statistieken
            "stats": {
                "sessions_total":  len(history),
                "avg_min":         round(avg_min, 1),
                "avg_liters":      round(avg_liter, 1),
                "avg_cost_eur":    round(avg_cost, 3),
                "total_liters":    round(total_l, 0),
                "olympic_pool_pct": olympic_pct,
            },
            "history": history,
        }

    def get_all_status(self) -> dict:
        """Status voor alle bekende boilers."""
        all_ids = set(list(self._active.keys()) +
                      list(self._history.keys()))
        return {bid: self.get_status(bid) for bid in all_ids}
