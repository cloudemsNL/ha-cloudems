# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
gas_predictor.py — CloudEMS v4.3.4
=====================================
Voorspelt dagelijks gasverbruik op basis van buitentemperatuur.

Model: lineair regressie op (temperatuur → m³/dag)
  - Leert automatisch van historische dagdata (P1-lezer)
  - Buitentemperatuur via HA weather entity of sensor
  - Correctionele factor: setpoint verwarmingstemperatuur

Output:
  - Voorspeld verbruik morgen (m³)
  - Verwachte maandkosten gas
  - Stookgrens (HDD-model: boven welke temp is er geen verwarming nodig?)
  - Vergelijking: dit jaar vs. vorig jaar zelfde periode
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
STORAGE_KEY_GAS_PREDICTOR = "cloudems_gas_predictor_v1"

GAS_PRICE_DEFAULT_EUR_M3 = 1.20     # fallback gasprijs
HEATING_DEGREE_BASE_C    = 18.0     # stookgrens (Heating Degree Day basis)
MIN_DAYS_FOR_MODEL       = 7        # minimale datadagen voor voorspelling


@dataclass
class GasPrediction:
    tomorrow_m3:         float
    month_m3:            float
    month_eur:           float
    annual_m3:           float
    heating_degree_days: float      # HDD afgelopen 7 dagen
    stook_threshold_c:   float      # boven deze temp geen verwarming nodig
    model_r2:            float      # kwaliteit van het model (0–1)
    days_of_data:        int
    tip:                 str = ""

    def to_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


class GasPredictor:
    """
    Lineair regressiemodel voor gasverbruik op basis van temperatuur.

    Gebruik:
        predictor = GasPredictor(store)
        await predictor.async_load()
        predictor.record_day(date_str, gas_m3, temp_c)
        prediction = predictor.predict(temp_tomorrow_c, gas_price_eur_m3)
        await predictor.async_save()
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        # [{date, gas_m3, temp_c}]
        self._days: list[dict] = []
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw:
                self._days = raw.get("days", [])[-365:]
        except Exception as err:
            _LOGGER.warning("GasPredictor: laden mislukt: %s", err)
        self._loaded = True

    async def async_save(self) -> None:
        try:
            await self._store.async_save({"days": self._days[-365:]})
        except Exception as err:
            _LOGGER.warning("GasPredictor: opslaan mislukt: %s", err)

    def record_day(self, date_str: str, gas_m3: float, temp_c: float) -> None:
        if gas_m3 <= 0:
            return
        # Dedupliceer op datum
        self._days = [d for d in self._days if d["date"] != date_str]
        self._days.append({"date": date_str, "gas_m3": gas_m3, "temp_c": temp_c})
        self._days.sort(key=lambda x: x["date"])

    def predict(
        self,
        temp_tomorrow_c: float,
        gas_price_eur_m3: float = GAS_PRICE_DEFAULT_EUR_M3,
        days_ahead: int = 30,
    ) -> GasPrediction:
        n = len(self._days)
        if n < MIN_DAYS_FOR_MODEL:
            # Te weinig data — gebruik HDD-schatting
            hdd = max(0.0, HEATING_DEGREE_BASE_C - temp_tomorrow_c)
            est_m3 = round(hdd * 0.15, 2) if hdd > 0 else 0.1
            return GasPrediction(
                tomorrow_m3         = est_m3,
                month_m3            = round(est_m3 * 30, 1),
                month_eur           = round(est_m3 * 30 * gas_price_eur_m3, 2),
                annual_m3           = round(est_m3 * 365, 0),
                heating_degree_days = 0.0,
                stook_threshold_c   = HEATING_DEGREE_BASE_C,
                model_r2            = 0.0,
                days_of_data        = n,
                tip                 = f"Nog {MIN_DAYS_FOR_MODEL - n} dagen nodig voor nauwkeurig model.",
            )

        # v1.32: Stuksgewijze lineaire regressie per temperatuurzone
        # Zone 1: < 5°C  → koude winterdagen (verwarming + warmwater + koken)
        # Zone 2: 5–12°C → overgangsperiode (verwarming gedeeltelijk)
        # Zone 3: > 12°C → zomerdagen (alleen warm water + koken)
        # Elke zone heeft zijn eigen a/b, zodat niet-lineariteit wordt gevangen.
        ZONES = [
            ("koud",       lambda t: t <  5),
            ("overgang",   lambda t: 5 <= t <= 12),
            ("warm",       lambda t: t >  12),
        ]

        def _linreg(xs, ys):
            """Eenvoudige lineaire regressie, geeft (a, b, r2) terug."""
            n = len(xs)
            if n < 3:
                return 0.0, (sum(ys)/n if n else 0.0), 0.0
            mx = sum(xs) / n
            my = sum(ys) / n
            ssxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            ssxx = sum((x - mx) ** 2 for x in xs)
            a = ssxy / ssxx if ssxx > 0.001 else 0.0
            b = my - a * mx
            ss_res = sum((y - (a*x + b))**2 for x, y in zip(xs, ys))
            ss_tot = sum((y - my)**2 for y in ys)
            r2 = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0.001 else 0.0
            return a, b, r2

        # Bouw zone-modellen
        zone_models = {}
        for zname, zcond in ZONES:
            zdata = [(d["temp_c"], d["gas_m3"]) for d in self._days if zcond(d["temp_c"])]
            if len(zdata) >= 3:
                zxs, zys = zip(*zdata)
                zone_models[zname] = _linreg(list(zxs), list(zys))

        # Kies het model dat hoort bij de voorspelde temperatuur van morgen
        if temp_tomorrow_c < 5 and "koud" in zone_models:
            a, b, r2 = zone_models["koud"]
        elif 5 <= temp_tomorrow_c <= 12 and "overgang" in zone_models:
            a, b, r2 = zone_models["overgang"]
        elif temp_tomorrow_c > 12 and "warm" in zone_models:
            a, b, r2 = zone_models["warm"]
        else:
            # Fallback: globaal model over alle data
            xs_all = [d["temp_c"] for d in self._days]
            ys_all = [d["gas_m3"] for d in self._days]
            a, b, r2 = _linreg(xs_all, ys_all)

        predicted = max(0.0, a * temp_tomorrow_c + b)

        # r2 = gewogen gemiddelde over beschikbare zones (voor info)
        # (al gezet door geselecteerde zone hierboven)

        # Stookgrens: temp waarbij gas_m3 = minimaal basisverbruik (koken, warm water)
        ys_all = [d["gas_m3"] for d in self._days]
        base_use = max(0.1, min(ys_all))
        # Gebruik het warme-zone model voor de stookgrens (meest representatief)
        a_w, b_w, _ = zone_models.get("warm", (a, b, r2))
        stook_thres = ((base_use - b_w) / a_w) if abs(a_w) > 0.001 else HEATING_DEGREE_BASE_C

        # HDD afgelopen 7 dagen
        recent7 = self._days[-7:]
        hdd_7 = sum(max(0.0, HEATING_DEGREE_BASE_C - d["temp_c"]) for d in recent7)

        # Tip
        tip = ""
        if r2 < 0.5 and n >= 14:
            tip = "Groot variatie in gasverbruik — controleer of thermostaatinstelling stabiel is."
        elif predicted > 5.0:
            tip = f"Hoog gasverbruik verwacht ({predicted:.1f} m³) — overweeg thermostaatbesparing."

        return GasPrediction(
            tomorrow_m3         = round(predicted, 2),
            month_m3            = round(predicted * days_ahead, 1),
            month_eur           = round(predicted * days_ahead * gas_price_eur_m3, 2),
            annual_m3           = round(sum(ys_all) / len(ys_all) * 365, 0),
            heating_degree_days = round(hdd_7, 1),
            stook_threshold_c   = round(stook_thres, 1),
            model_r2            = round(r2, 3),
            days_of_data        = n,
            tip                 = tip,
        )
