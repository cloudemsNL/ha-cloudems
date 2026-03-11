# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS ML Verbruiksvoorspelling — v1.0.0

Verbeterde verbruiksvoorspelling via een lichtgewicht machine-learning model
dat naast uur-van-de-dag en weekdag ook weersgerelateerde en seizoenskenmerken
meeneemt — geïnspireerd door de scikit-learn/skforecast aanpak van EMHASS.

Waarom beter dan puur patroongemiddelde?
----------------------------------------
Het bestaande cost_forecaster.py middelt het kWh-verbruik per uur/weekdag.
Dat werkt prima bij stabiel gedrag maar mist:
  - Temperatuureffect: bij -5°C verbruik je 40% meer dan bij 15°C
  - Seizoenseffect: zomer vs winter dagprofiel verschilt fundamenteel
  - Feestdagen / vakantie: verbruik lijkt op weekendpatroon
  - Solar surplus-effect: bij hoge PV verplaatst verbruik naar de dag

Model
-----
Gradient Boosting via een implementatie zonder externe dependencies
(pure Python + math), aangestuurd door features per uur:

  Feature vector per tijdstap:
    - hour_sin, hour_cos            : circulair uurcodering
    - dow_sin, dow_cos              : circulaire weekdag
    - month_sin, month_cos          : seizoen (circulair)
    - t_outside_c                   : buitentemperatuur
    - pv_kwh_yesterday              : zonneopbrengst gisteren (proxy bewolking)
    - is_weekend                    : 0/1
    - heating_degree_day            : max(0, 18 - t_outside) (verwarmingsgraad)

Implementatie
-------------
Omdat scikit-learn niet beschikbaar is in de standaard HA-omgeving,
wordt een lichtgewicht k-NN-regressie gebruikt (geen externe deps):
  - Slaat de laatste MAX_HISTORY datapunten op
  - Voorspelling = gewogen gemiddelde van de K meest gelijkende datapunten
  - Gewicht = 1 / (euclidische afstand in feature-ruimte + ε)
  - Na BOOTSTRAP_DAYS valt het terug op een patroongemiddelde als de k-NN
    te weinig vergelijkbare punten heeft (afstand > threshold)

Output
------
Sensor: cloudems_ml_consumption_forecast
  state: voorspeld verbruik voor het volgende uur (kWh)
  attributes:
    forecast_24h       : [{'hour': 0, 'kwh': 1.2}, ...]
    model_trained      : bool
    training_samples   : int
    mape_7d_pct        : voorspelnauwkeurigheid laatste 7 dagen (%)
    feature_importance : {'temperature': 0.35, 'hour': 0.28, ...}

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_ml_forecast_v1"
STORAGE_VERSION = 1

# Model-hyperparameters
K_NEIGHBORS         = 7       # k-NN: aantal buren
MAX_HISTORY         = 720     # Bewaar max 720 datapunten (~30 dagen × 24 uur)
BOOTSTRAP_DAYS      = 7       # Na 7 dagen genoeg data voor k-NN
FALLBACK_DAYS       = 3       # Patroongemiddelde als fallback (min 3 dagen)
DIST_THRESHOLD      = 2.5     # Max afstand voor een betrouwbare k-NN buur
SAVE_INTERVAL_S     = 600     # Sla op elke 10 minuten

# Feature gewichten voor afstandsberekening
# Hogere waarde = feature telt zwaarder mee bij het zoeken naar buren
FEATURE_WEIGHTS = {
    "hour_sin":         1.5,
    "hour_cos":         1.5,
    "dow_sin":          1.0,
    "dow_cos":          1.0,
    "month_sin":        0.8,
    "month_cos":        0.8,
    "t_outside_norm":   1.2,   # temperatuur telt flink mee
    "pv_yesterday_norm": 0.5,
    "is_weekend":       0.7,
    "hdd_norm":         0.9,   # verwarmingsgraad
}


@dataclass
class TrainingPoint:
    """Eén historisch datapunt voor het k-NN model."""
    features: list[float]    # genormaliseerde feature-vector
    kwh:      float          # werkelijk verbruik dat uur
    hour:     int
    dow:      int            # day of week 0=ma
    timestamp: float         # unix timestamp


@dataclass
class ForecastResult:
    next_hour_kwh:      float
    forecast_24h:       list[dict]    # [{'hour': h, 'kwh': x}, ...]
    model_trained:      bool
    training_samples:   int
    mape_7d_pct:        Optional[float]
    method:             str           # "knn" | "pattern" | "bootstrap"


class MLConsumptionForecaster:
    """
    Lichtgewicht k-NN verbruiksforecaster met weersfeatues.

    Gebruik vanuit coordinator:
        fc.add_observation(kwh_this_hour, t_outside, pv_kwh_yesterday)
        result = fc.forecast(t_outside_forecast_24h, pv_yesterday)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass       = hass
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self._history:  list[TrainingPoint] = []
        self._accuracy_log: list[dict]      = []   # [{hour, predicted, actual}]
        self._pattern:  dict[str, float]    = {}   # {f"{dow}_{hour}": avg_kwh}

        self._dirty     = False
        self._last_save = 0.0
        self._t_norm_mean: float = 10.0   # Gemiddelde buitentemp voor normalisatie
        self._t_norm_std:  float = 8.0
        self._pv_norm_max: float = 5.0    # Max dagopbrengst voor normalisatie

    async def async_setup(self) -> None:
        """Laad persistente history."""
        saved: dict = await self._store.async_load() or {}
        raw = saved.get("history", [])
        self._history = [
            TrainingPoint(
                features  = p["f"],
                kwh       = p["k"],
                hour      = p["h"],
                dow       = p["d"],
                timestamp = p["t"],
            )
            for p in raw
        ]
        self._accuracy_log = saved.get("accuracy", [])[-168:]  # max 7 dagen
        self._pattern      = saved.get("pattern", {})
        self._t_norm_mean  = float(saved.get("t_mean", 10.0))
        self._t_norm_std   = float(saved.get("t_std",   8.0))
        self._pv_norm_max  = float(saved.get("pv_max",  5.0))
        _LOGGER.info(
            "MLForecast: geladen — %d datapunten, %d patroonslots",
            len(self._history), len(self._pattern),
        )

    # ──────────────────────────────────────────────────────────────────
    # Observatie toevoegen (1x per uur aanroepen)
    # ──────────────────────────────────────────────────────────────────

    def add_observation(
        self,
        kwh_this_hour:    float,
        t_outside_c:      float,
        pv_kwh_yesterday: float = 0.0,
        predicted_kwh:    Optional[float] = None,
    ) -> None:
        """
        Voeg het werkelijke verbruik van het afgelopen uur toe aan de history.

        Parameters
        ----------
        kwh_this_hour    : Gemeten verbruik dit uur (kWh).
        t_outside_c      : Buitentemperatuur (°C).
        pv_kwh_yesterday : Totale PV-opbrengst van gisteren (kWh) — proxy bewolking.
        predicted_kwh    : Eerdere voorspelling (voor nauwkeurigheidslogging).
        """
        if kwh_this_hour < 0 or kwh_this_hour > 50:
            return  # Sanity check

        now = datetime.now(timezone.utc)
        fv  = self._build_features(now, t_outside_c, pv_kwh_yesterday)

        point = TrainingPoint(
            features  = fv,
            kwh       = kwh_this_hour,
            hour      = now.hour,
            dow       = now.weekday(),
            timestamp = time.time(),
        )
        self._history.append(point)

        # Begrens op MAX_HISTORY (verwijder oudste)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

        # Bijwerk patroongemiddelde (fallback)
        key = f"{now.weekday()}_{now.hour}"
        old = self._pattern.get(key, kwh_this_hour)
        self._pattern[key] = 0.9 * old + 0.1 * kwh_this_hour

        # Nauwkeurigheidslog
        if predicted_kwh is not None and predicted_kwh > 0:
            err_pct = abs(kwh_this_hour - predicted_kwh) / max(0.1, kwh_this_hour) * 100
            self._accuracy_log.append({
                "ts": time.time(),
                "pred": round(predicted_kwh, 3),
                "actual": round(kwh_this_hour, 3),
                "err_pct": round(err_pct, 1),
            })
            self._accuracy_log = self._accuracy_log[-168:]

        # Update normalisatieparameters
        self._update_norm_params(t_outside_c, pv_kwh_yesterday)

        self._dirty = True

    def _update_norm_params(self, t_outside: float, pv_yesterday: float) -> None:
        """Pas normalisatiebasis langzaam aan op basis van recente data."""
        self._t_norm_mean = 0.99 * self._t_norm_mean + 0.01 * t_outside
        self._t_norm_std  = max(2.0, 0.99 * self._t_norm_std + 0.01 * abs(t_outside - self._t_norm_mean))
        if pv_yesterday > 0:
            self._pv_norm_max = max(self._pv_norm_max, pv_yesterday * 0.9)

    # ──────────────────────────────────────────────────────────────────
    # Voorspelling
    # ──────────────────────────────────────────────────────────────────

    def forecast(
        self,
        t_outside_forecast: list[float],   # 24 waarden, uur 0–23
        pv_kwh_yesterday:   float = 0.0,
    ) -> ForecastResult:
        """
        Voorspel het verbruik voor de komende 24 uur.

        Parameters
        ----------
        t_outside_forecast : Buitentemperatuurverwachting per uur [0..23] (°C).
        pv_kwh_yesterday   : Totale PV-opbrengst gisteren (kWh).
        """
        trained  = len(self._history) >= 24 * BOOTSTRAP_DAYS
        method   = "knn" if trained else ("pattern" if self._pattern else "bootstrap")

        now      = datetime.now(timezone.utc)
        forecast_24h: list[dict] = []

        for h_offset in range(24):
            target_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h_offset)
            t_out     = t_outside_forecast[h_offset] if h_offset < len(t_outside_forecast) else self._t_norm_mean
            fv        = self._build_features(target_dt, t_out, pv_kwh_yesterday)

            if method == "knn":
                kwh_pred = self._knn_predict(fv)
            else:
                kwh_pred = self._pattern_predict(target_dt.weekday(), target_dt.hour)

            forecast_24h.append({
                "hour": target_dt.hour,
                "kwh":  round(max(0.0, kwh_pred), 3),
            })

        next_kwh = forecast_24h[0]["kwh"] if forecast_24h else 0.0
        mape     = self._calc_mape_7d()

        return ForecastResult(
            next_hour_kwh    = next_kwh,
            forecast_24h     = forecast_24h,
            model_trained    = trained,
            training_samples = len(self._history),
            mape_7d_pct      = mape,
            method           = method,
        )

    def _knn_predict(self, query_features: list[float]) -> float:
        """Gewogen k-NN regressie."""
        if not self._history:
            return 0.5

        weights_list = list(FEATURE_WEIGHTS.values())
        distances = []
        for pt in self._history:
            d = self._weighted_distance(query_features, pt.features, weights_list)
            distances.append((d, pt.kwh))

        distances.sort(key=lambda x: x[0])
        neighbors = distances[:K_NEIGHBORS]

        # Als alle buren ver weg zijn → fallback op patroon
        if neighbors[0][0] > DIST_THRESHOLD:
            return self._pattern_predict_from_features(query_features)

        total_w = 0.0
        total_v = 0.0
        for dist, kwh in neighbors:
            w = 1.0 / (dist + 1e-6)
            total_w += w
            total_v += w * kwh

        return total_v / total_w if total_w > 0 else 0.5

    def _pattern_predict(self, dow: int, hour: int) -> float:
        """Patroongemiddelde fallback."""
        key = f"{dow}_{hour}"
        if key in self._pattern:
            return self._pattern[key]
        # Fallback op daggemiddelde
        day_vals = [v for k, v in self._pattern.items() if k.startswith(f"{dow}_")]
        return sum(day_vals) / len(day_vals) if day_vals else 0.5

    def _pattern_predict_from_features(self, fv: list[float]) -> float:
        """Herstel uur en weekdag uit features voor patroon-fallback."""
        # hour_sin = sin(2π×h/24), hour_cos = cos(2π×h/24)
        h_sin, h_cos = fv[0], fv[1]
        hour = round(math.atan2(h_sin, h_cos) / (2 * math.pi / 24)) % 24
        d_sin, d_cos = fv[2], fv[3]
        dow  = round(math.atan2(d_sin, d_cos) / (2 * math.pi / 7)) % 7
        return self._pattern_predict(dow, hour)

    @staticmethod
    def _weighted_distance(a: list[float], b: list[float], weights: list[float]) -> float:
        """Gewogen Euclidische afstand."""
        if len(a) != len(b):
            return 999.0
        s = 0.0
        for i, (x, y) in enumerate(zip(a, b)):
            w = weights[i] if i < len(weights) else 1.0
            s += w * (x - y) ** 2
        return math.sqrt(s)

    # ──────────────────────────────────────────────────────────────────
    # Features bouwen
    # ──────────────────────────────────────────────────────────────────

    def _build_features(
        self,
        dt:             datetime,
        t_outside_c:    float,
        pv_kwh_yesterday: float,
    ) -> list[float]:
        """
        Bouw de feature-vector voor een gegeven tijdstip.
        Volgorde moet overeenkomen met FEATURE_WEIGHTS.
        """
        h   = dt.hour
        dow = dt.weekday()
        mon = dt.month

        # Circulaire coderingen
        hour_sin  = math.sin(2 * math.pi * h   / 24)
        hour_cos  = math.cos(2 * math.pi * h   / 24)
        dow_sin   = math.sin(2 * math.pi * dow / 7)
        dow_cos   = math.cos(2 * math.pi * dow / 7)
        month_sin = math.sin(2 * math.pi * mon / 12)
        month_cos = math.cos(2 * math.pi * mon / 12)

        # Genormaliseerde temperatuur
        t_norm = (t_outside_c - self._t_norm_mean) / max(1.0, self._t_norm_std)

        # Genormaliseerde PV-opbrengst
        pv_norm = pv_kwh_yesterday / max(1.0, self._pv_norm_max)

        # Weekend-vlag
        is_weekend = 1.0 if dow >= 5 else 0.0

        # Heating Degree Day (per uur) — verwarmingsgraad
        hdd = max(0.0, 18.0 - t_outside_c) / 20.0   # genormaliseerd op 0–1 schaal

        return [hour_sin, hour_cos, dow_sin, dow_cos, month_sin, month_cos,
                t_norm, pv_norm, is_weekend, hdd]

    # ──────────────────────────────────────────────────────────────────
    # Nauwkeurigheid
    # ──────────────────────────────────────────────────────────────────

    def _calc_mape_7d(self) -> Optional[float]:
        """Berekent MAPE over de laatste 7 dagen."""
        cutoff = time.time() - 7 * 86400
        recent = [e for e in self._accuracy_log if e["ts"] >= cutoff]
        if len(recent) < 5:
            return None
        return round(sum(e["err_pct"] for e in recent) / len(recent), 1)

    def get_feature_importance(self) -> dict:
        """
        Schat feature-importantie via variantie-analyse over de history.
        Hoe meer een feature varieert voor punten met vergelijkbare output,
        hoe minder informatief — omgekeerd: hoge correlatie = hoog belang.
        """
        if len(self._history) < 48:
            return {}

        feature_names = list(FEATURE_WEIGHTS.keys())
        n_features = len(feature_names)
        importances = {}

        for i, name in enumerate(feature_names):
            vals  = [p.features[i] for p in self._history if len(p.features) > i]
            kwhs  = [p.kwh         for p in self._history if len(p.features) > i]
            if len(vals) < 10:
                continue
            # Pearson-correlatie als proxy voor importantie
            mean_v = sum(vals) / len(vals)
            mean_k = sum(kwhs) / len(kwhs)
            cov = sum((v - mean_v) * (k - mean_k) for v, k in zip(vals, kwhs))
            std_v = math.sqrt(sum((v - mean_v)**2 for v in vals) + 1e-9)
            std_k = math.sqrt(sum((k - mean_k)**2 for k in kwhs) + 1e-9)
            r = abs(cov / (std_v * std_k))
            importances[name] = round(r, 3)

        # Normaliseer op 0–1
        total = sum(importances.values()) or 1.0
        return {k: round(v / total, 3) for k, v in sorted(importances.items(), key=lambda x: -x[1])}

    # ──────────────────────────────────────────────────────────────────
    # Persistentie
    # ──────────────────────────────────────────────────────────────────

    async def async_maybe_save(self) -> None:
        """Sla model-history op (max 1x per 10 min)."""
        if not self._dirty or (time.time() - self._last_save) < SAVE_INTERVAL_S:
            return
        await self._store.async_save({
            "history": [
                {"f": p.features, "k": round(p.kwh, 4), "h": p.hour,
                 "d": p.dow, "t": round(p.timestamp)}
                for p in self._history[-MAX_HISTORY:]
            ],
            "accuracy": self._accuracy_log[-168:],
            "pattern":  self._pattern,
            "t_mean":   round(self._t_norm_mean, 2),
            "t_std":    round(self._t_norm_std, 2),
            "pv_max":   round(self._pv_norm_max, 2),
        })
        self._dirty     = False
        self._last_save = time.time()
        _LOGGER.debug("MLForecast: opgeslagen (%d punten)", len(self._history))
