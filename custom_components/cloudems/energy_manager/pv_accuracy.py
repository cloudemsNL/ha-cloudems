# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS PV Forecast Nauwkeurigheid Tracker — v1.0.0

Sluit de feedback-loop die in pv_forecast.py ontbreekt:
  elke avond → vergelijk voorspelde dagopbrengst met werkelijke dagopbrengst
  → pas het leermodel bij → betere voorspellingen morgen

Wat dit oplost:
  pv_forecast.py voorspelt al, maar vergelijkt nooit achteraf.
  Na een paar weken weet dit module:
    • Systematische over/onderschatting per seizoen of bewolkingstype
    • Per omvormer: is Open-Meteo betrouwbaar voor deze locatie?
    • "Bij een bewolkte dag zijn jouw panelen beter dan het model dacht"

Berekende metrics:
  • MAPE (Mean Absolute Percentage Error) laatste 14 en 30 dagen
  • Bias-factor: structurele over/onderschatting (> 1.0 = model overschat)
  • Per-maand kalibratiefactor (seizoensgebonden correctie)
  • Streakdetectie: "5 opeenvolgende overschatting-dagen → model bijgesteld"

Sensor output:
  • Nauwkeurigheid: 94.2% (14-daags MAPE)
  • Kalibratiefactor: 0.91 (model overschat 9%)
  • Advies: "Model presteert goed in zomer, maar overschat lentedagen met 15%"

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

STORAGE_KEY     = "cloudems_pv_accuracy_v1"
STORAGE_VERSION = 1

SAVE_INTERVAL_S = 600
MIN_DAYS_MAPE   = 3     # minimum zonnige dagen voor eerste MAPE-schatting
MIN_KWH_DAY     = 0.5   # minimale dagproductie om mee te tellen (bewolkte dag)


@dataclass
class DayAccuracy:
    date:         str
    forecast_kwh: float
    actual_kwh:   float
    error_pct:    float   # (actual - forecast) / forecast × 100 (negatief = overschatting)
    month:        int

    @property
    def abs_error_pct(self) -> float:
        return abs(self.error_pct)

    def to_dict(self) -> dict:
        return {
            "date":         self.date,
            "forecast_kwh": round(self.forecast_kwh, 3),
            "actual_kwh":   round(self.actual_kwh, 3),
            "error_pct":    round(self.error_pct, 1),
            "month":        self.month,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DayAccuracy":
        return cls(**{k: v for k, v in d.items()
                      if k in ("date", "forecast_kwh", "actual_kwh", "error_pct", "month")})


@dataclass
class PVAccuracyData:
    """Output voor de sensor."""
    mape_14d:          Optional[float]   # % fout laatste 14 dagen
    mape_30d:          Optional[float]   # % fout laatste 30 dagen
    bias_factor:       float             # gemiddeld actual/forecast ratio
    calibration_month: Optional[float]   # kalibratiefactor huidige maand
    days_tracked:      int
    days_with_data:    int
    last_day_error_pct:Optional[float]
    consecutive_over:  int               # opeenvolgende overschattingen
    consecutive_under: int               # opeenvolgende onderschattingen
    quality_label:     str               # "uitstekend" | "goed" | "matig" | "slecht"
    advice:            str
    monthly_bias:      dict[str, float]  # {maand: bias_factor}


def _quality_label(mape: Optional[float]) -> str:
    if mape is None:
        return "onbekend"
    if mape < 8:
        return "uitstekend"
    if mape < 15:
        return "goed"
    if mape < 25:
        return "matig"
    return "slecht"


class PVForecastAccuracyTracker:
    """
    Vergelijkt dagelijks de PV-voorspelling met de werkelijke productie
    en leert een kalibratiefactor per maand.

    Aanroep vanuit coordinator:
        # elke tick: rapporteer huidige productie
        tracker.tick_production(pv_w)
        # dagelijks (bij dag-rollover of expliciet):
        tracker.finalize_day(forecast_kwh)
        # kalibratiefactor opvragen voor forecast-correctie:
        factor = tracker.get_calibration_factor()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._history: list[DayAccuracy] = []
        self._today_date  = ""
        self._today_kwh   = 0.0   # accumuleer productie vandaag
        self._last_save   = 0.0
        self._dirty       = False
        self._tick_s      = 10.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for d in saved.get("history", []):
            try:
                self._history.append(DayAccuracy.from_dict(d))
            except Exception:
                pass
        self._today_kwh  = float(saved.get("today_kwh", 0.0))
        self._today_date = saved.get("today_date", "")
        _LOGGER.info(
            "PVAccuracyTracker: %d dagen historiek geladen, %.2f kWh vandaag",
            len(self._history), self._today_kwh,
        )

    def tick(self, actual_w: float = 0.0, forecast_w: float = 0.0, pv_w: float = 0.0) -> None:
        """Compatibility alias — accepts both old .tick(actual_w=) and new .tick_production(pv_w=) signatures."""
        self.tick_production(pv_w=actual_w or pv_w)

    def tick_production(self, pv_w: float) -> None:
        """Registreer huidige PV-productie (elke 10s)."""
        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if today != self._today_date:
            self._today_date = today
            self._today_kwh  = 0.0
        self._today_kwh += max(0.0, pv_w * (self._tick_s / 3600.0) / 1000.0)
        self._dirty = True

    def finalize_day(self, forecast_kwh: float) -> None:
        """
        Sluit de dag af: vergelijk voorspelling met werkelijkheid.

        Wordt aangeroepen bij dag-rollover vanuit coordinator.
        """
        if self._today_kwh < MIN_KWH_DAY:
            _LOGGER.debug("PVAccuracy: dag overgeslagen (te weinig productie: %.2f kWh)", self._today_kwh)
            return
        if forecast_kwh <= 0:
            return

        error_pct = (self._today_kwh - forecast_kwh) / forecast_kwh * 100.0
        now = datetime.now(timezone.utc)

        entry = DayAccuracy(
            date         = self._today_date or now.strftime("%Y-%m-%d"),
            forecast_kwh = round(forecast_kwh, 3),
            actual_kwh   = round(self._today_kwh, 3),
            error_pct    = round(error_pct, 2),
            month        = now.month,
        )
        self._history.append(entry)
        # Bewaar max 365 dagen
        self._history = self._history[-365:]
        self._dirty   = True

        n_days = len(self._history)
        bar = '#' * min(n_days, MIN_DAYS_MAPE) + '.' * max(0, MIN_DAYS_MAPE - n_days)
        _LOGGER.info(
            "PVAccuracy: dag %d/%d [%s] | %s | voorspeld %.2f kWh | werkelijk %.2f kWh | fout %.1f%%",
            n_days, MIN_DAYS_MAPE, bar, entry.date, forecast_kwh, self._today_kwh, error_pct,
        )
        if n_days == MIN_DAYS_MAPE:
            _LOGGER.info("PVAccuracy: ✅ voldoende data — MAPE-kalibratie actief")

    def get_calibration_factor(self, month: Optional[int] = None) -> float:
        """
        Geeft de kalibratiefactor terug voor de huidige (of opgegeven) maand.
        Gebruik dit om de ruwe forecast × factor te corrigeren.
        Factor > 1.0 = model onderschat → schaal omhoog.
        Factor < 1.0 = model overschat  → schaal omlaag.
        """
        if month is None:
            month = datetime.now(timezone.utc).month
        monthly = [d for d in self._history if d.month == month and d.forecast_kwh > 0]
        if len(monthly) < 3:
            return 1.0
        ratios = [d.actual_kwh / d.forecast_kwh for d in monthly]
        return round(sum(ratios) / len(ratios), 3)

    def get_data(self) -> PVAccuracyData:
        recent_14 = [d for d in self._history[-14:] if d.forecast_kwh > 0]
        recent_30 = [d for d in self._history[-30:] if d.forecast_kwh > 0]

        mape_14 = round(
            sum(d.abs_error_pct for d in recent_14) / len(recent_14), 1
        ) if len(recent_14) >= MIN_DAYS_MAPE else None

        mape_30 = round(
            sum(d.abs_error_pct for d in recent_30) / len(recent_30), 1
        ) if len(recent_30) >= MIN_DAYS_MAPE else None

        # Bias: structurele over/onderschatting
        ratios = [d.actual_kwh / d.forecast_kwh for d in recent_30 if d.forecast_kwh > 0]
        bias   = round(sum(ratios) / len(ratios), 3) if ratios else 1.0

        # Per-maand kalibratie
        monthly_bias: dict[str, float] = {}
        MONTHS = {1:"Jan",2:"Feb",3:"Mrt",4:"Apr",5:"Mei",6:"Jun",
                  7:"Jul",8:"Aug",9:"Sep",10:"Okt",11:"Nov",12:"Dec"}
        for m in range(1, 13):
            f = self.get_calibration_factor(m)
            if f != 1.0:
                monthly_bias[MONTHS[m]] = f

        # Streak detectie
        streak_over = streak_under = 0
        for d in reversed(self._history[-10:]):
            if d.error_pct < -5:
                if streak_under == 0:
                    streak_over += 1
                else:
                    break
            elif d.error_pct > 5:
                if streak_over == 0:
                    streak_under += 1
                else:
                    break
            else:
                break

        last_err = self._history[-1].error_pct if self._history else None
        quality  = _quality_label(mape_14)

        # Advies
        if mape_14 is None:
            advice = f"Nog {MIN_DAYS_MAPE - len(recent_14)} zonnige dagen nodig voor betrouwbare nauwkeurigheidsanalyse."
        elif bias < 0.85:
            advice = (
                f"Model overschat {(1-bias)*100:.0f}% structureel. "
                f"Kalibratiefactor {bias:.2f} — CloudEMS corrigeert automatisch."
            )
        elif bias > 1.15:
            advice = (
                f"Model onderschat {(bias-1)*100:.0f}% structureel. "
                f"Kalibratiefactor {bias:.2f} — CloudEMS corrigeert automatisch."
            )
        elif mape_14 < 10:
            advice = (
                f"Uitstekende voorspelnauwkeurigheid: {mape_14:.1f}% MAPE. "
                "Forecast is goed gekalibreerd voor deze locatie."
            )
        else:
            advice = (
                f"Voorspelnauwkeurigheid: {mape_14:.1f}% MAPE. "
                "Model verbetert automatisch met meer data."
            )

        return PVAccuracyData(
            mape_14d           = mape_14,
            mape_30d           = mape_30,
            bias_factor        = bias,
            calibration_month  = self.get_calibration_factor(),
            days_tracked       = len(self._history),
            days_with_data     = len(recent_30),
            last_day_error_pct = last_err,
            consecutive_over   = streak_over,
            consecutive_under  = streak_under,
            quality_label      = quality,
            advice             = advice,
            monthly_bias       = monthly_bias,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "history":    [d.to_dict() for d in self._history],
                "today_kwh":  round(self._today_kwh, 4),
                "today_date": self._today_date,
            })
            self._dirty     = False
            self._last_save = time.time()


# ── v4.6.531: Per-uur correctie ───────────────────────────────────────────────

class HourlyBiasLearner:
    """
    Leert per-uur systematische bias van PV-voorspelling.
    Bijv. ochtend altijd te optimistisch (bewolking), middag goed, avond te pessimistisch.

    Gebruik:
        learner = HourlyBiasLearner()
        learner.observe(hour=10, forecast_w=800, actual_w=650)
        factor = learner.get_correction(hour=10)  # 0.81
    """
    EMA_ALPHA   = 0.10
    MIN_SAMPLES = 5

    def __init__(self) -> None:
        # {hour: {"ema_ratio": float, "samples": int}}
        self._hourly: dict[int, dict] = {
            h: {"ema_ratio": 1.0, "samples": 0} for h in range(24)
        }

    def observe(self, hour: int, forecast_w: float, actual_w: float) -> None:
        """Verwerk één uur-observatie."""
        if forecast_w < 10:
            return   # te weinig productie om betrouwbaar te meten
        ratio = actual_w / forecast_w
        ratio = max(0.1, min(3.0, ratio))   # clamp outliers
        h = self._hourly[hour % 24]
        h["ema_ratio"] = self.EMA_ALPHA * ratio + (1 - self.EMA_ALPHA) * h["ema_ratio"]
        h["samples"]   = min(h["samples"] + 1, 9999)

    def get_correction(self, hour: int) -> float:
        """Geef correctiefactor voor dit uur. 1.0 als onvoldoende data."""
        h = self._hourly[hour % 24]
        if h["samples"] < self.MIN_SAMPLES:
            return 1.0
        return round(h["ema_ratio"], 3)

    def apply_to_forecast(self, hour: int, forecast_w: float) -> float:
        """Pas correctiefactor toe op forecast."""
        return forecast_w * self.get_correction(hour)

    def to_dict(self) -> dict:
        return {str(h): v for h, v in self._hourly.items()}

    def from_dict(self, d: dict) -> None:
        for h_str, v in d.items():
            try:
                h = int(h_str)
                if 0 <= h < 24:
                    self._hourly[h] = v
            except (ValueError, TypeError):
                pass

    def get_diagnostics(self) -> dict:
        return {
            h: {
                "correction": round(v["ema_ratio"], 3),
                "samples":    v["samples"],
                "trusted":    v["samples"] >= self.MIN_SAMPLES,
            }
            for h, v in self._hourly.items()
            if v["samples"] > 0
        }
