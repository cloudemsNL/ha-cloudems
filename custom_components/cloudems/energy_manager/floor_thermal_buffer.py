# -*- coding: utf-8 -*-
"""
CloudEMS Vloer Thermische Buffer — v1.0.0

Modelleert vloerverwarming als thermische batterij, geïnspireerd op het
physics-informed model van Langer & Volling (2020) zoals geïmplementeerd in EMHASS.

Kernidee
--------
Een vloer met vloerverwarming heeft een aanzienlijke thermische massa (C_floor).
Die massa kan "opgeladen" worden met goedkope stroom en "ontladen" worden
(warmteafgifte) tijdens dure uren — zonder comfort te verliezen.

Vloer-thermisch model (discretisatie per tijdstap dt):
    T_floor(t+1) = T_floor(t) + dt/C_floor × (P_floor(t) - UA_floor × (T_floor(t) - T_room(t)))

Waarbij:
    T_floor   : vloertemperatuur (°C)
    T_room    : kamertemperatuur (°C)
    C_floor   : thermische capaciteit vloer (Wh/°C)
    P_floor   : ingangsvermogen vloerverwarming (W)
    UA_floor  : warmteoverdrachtcoëfficiënt vloer→kamer (W/°C)

Leren
-----
CloudEMS leert C_floor en UA_floor automatisch als een vloertemperatuursensor
beschikbaar is. Zonder sensor worden standaardwaarden gebruikt op basis van
vloeroppervlak:
    C_floor  ≈ 60 Wh/°C per m² (beton) of 30 Wh/°C per m² (licht)
    UA_floor ≈ 8 W/°C per m²

Planningsfunctie
----------------
plan_charge_windows() berekent voor een 24-uurs EPEX-prijsprofiel de optimale
aan/uit-vensters voor de vloer, rekening houdend met:
  - Comfort band: T_floor ∈ [T_floor_min, T_floor_max]
  - Kamertemperatuur setpoint
  - COP van de warmtepomp per buitentemperatuur
  - Huidige vloertemperatuur als beginconditie

Output
------
Sensor: cloudems_floor_buffer_status
  state: "opladen" | "afgifte" | "normaal" | "onbekend"
  attributes:
    t_floor_c         : huidige/geschatte vloertemperatuur (°C)
    c_floor_wh_k      : geleerde thermische capaciteit
    ua_floor_w_k      : geleerde warmteoverdracht
    charge_windows    : [{start, end, price_ct, action}]
    savings_today_eur : geschatte besparing vandaag
    confidence        : modelbetrouwbaarheid 0–1

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_floor_buffer_v1"
STORAGE_VERSION = 1

# Fysische standaardwaarden (worden overschreven door geleerde waarden)
DEFAULT_C_FLOOR_WH_K     = 50.0    # Wh/°C per m² (gemiddeld beton/screed)
DEFAULT_UA_FLOOR_W_K     = 9.0     # W/°C per m² (standaard vloer→kamer)
DEFAULT_FLOOR_AREA_M2    = 30.0    # m² als geen oppervlak geconfigureerd is

# Comfortgrenzen vloertemperatuur
T_FLOOR_MIN_C   = 18.0   # Ondergrens comfortzone (°C)
T_FLOOR_MAX_C   = 29.0   # Bovengrens (NEN-EN 1264: max 29°C bij woonruimte)
T_FLOOR_TARGET  = 24.0   # Standaard streeftemperatuur
T_ROOM_DEFAULT  = 20.0   # Kamertemp als geen sensor beschikbaar

# Leerconstanten
ALPHA_FAST  = 0.20
ALPHA_SLOW  = 0.05
MIN_SAMPLES = 15          # Metingen voor betrouwbare parameterscatting

# Planningshorizon
HORIZON_H   = 24          # Uren vooruitkijken
DT_MIN      = 30          # Tijdstap in minuten


@dataclass
class FloorWindow:
    """Eén gepland aan/uit-venster voor de vloerverwarming."""
    start_hour:   int
    end_hour:     int
    action:       str    # "laden" | "afgifte" | "normaal"
    price_ct_kwh: float
    t_floor_start: float
    t_floor_end:   float


@dataclass
class FloorBufferStatus:
    state:            str
    t_floor_c:        float
    c_floor_wh_k:     float
    ua_floor_w_k:     float
    charge_windows:   list
    savings_today_eur: float
    confidence:       float
    advice:           str


class FloorThermalBuffer:
    """
    Vloerverwarmingsbuffer als thermische batterij.

    Gebruik vanuit coordinator:
        buffer.update(p_floor_w, t_floor_c, t_room_c, t_outside_c)
        plan = buffer.plan_charge_windows(epex_prices_24h, cop_curve)
        status = buffer.get_status()
    """

    def __init__(
        self,
        hass: HomeAssistant,
        floor_area_m2: float = DEFAULT_FLOOR_AREA_M2,
        floor_type: str = "beton",     # "beton" | "licht" | "hout"
    ) -> None:
        self.hass       = hass
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._area      = max(5.0, floor_area_m2)
        self._floor_type = floor_type

        # Thermische parameters (geleerd of standaard)
        _factor = {"beton": 60.0, "licht": 35.0, "hout": 25.0}.get(floor_type, 50.0)
        self._c_floor   = _factor * self._area        # Wh/°C
        self._ua_floor  = DEFAULT_UA_FLOOR_W_K * self._area  # W/°C
        self._samples   = 0

        # Toestandsvariabelen
        self._t_floor: Optional[float]   = None   # Geschatte/gemeten vloertemperatuur
        self._t_room:  float = T_ROOM_DEFAULT
        self._t_outside: float = 5.0
        self._p_floor: float = 0.0                 # Actueel vermogen (W)

        # Dagboekhouding
        self._savings_today_eur: float  = 0.0
        self._last_plan_date: str       = ""
        self._plan_windows: list        = []

        self._dirty     = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        """Laad opgeslagen parameters."""
        saved: dict = await self._store.async_load() or {}
        if saved.get("c_floor"):
            self._c_floor   = float(saved["c_floor"])
        if saved.get("ua_floor"):
            self._ua_floor  = float(saved["ua_floor"])
        self._samples       = int(saved.get("samples", 0))
        self._t_floor       = saved.get("t_floor_last")
        self._savings_today_eur = float(saved.get("savings_today_eur", 0.0))
        _LOGGER.info(
            "FloorBuffer: geladen — C=%.0f Wh/K  UA=%.1f W/K  samples=%d",
            self._c_floor, self._ua_floor, self._samples,
        )

    # ──────────────────────────────────────────────────────────────────
    # Update — wordt aangeroepen per coordinator-tick (~10s)
    # ──────────────────────────────────────────────────────────────────

    def update(
        self,
        p_floor_w:  float,
        t_floor_c:  Optional[float],
        t_room_c:   float,
        t_outside_c: float,
    ) -> None:
        """
        Verwerk nieuwe meting en actualiseer het thermische model.

        Parameters
        ----------
        p_floor_w   : Actueel ingangsvermogen vloerverwarming (W).
                      0 als de vloerverwarming uit staat.
        t_floor_c   : Gemeten vloertemperatuur (°C). None als geen sensor.
        t_room_c    : Kamertemperatuur (°C).
        t_outside_c : Buitentemperatuur (°C).
        """
        self._p_floor   = p_floor_w
        self._t_room    = t_room_c
        self._t_outside = t_outside_c

        dt_h = 10 / 3600  # 10-seconden coordinator-tick → uren

        if t_floor_c is not None:
            # Sensor beschikbaar: gebruik hem én leer de parameters bij
            if self._t_floor is not None and p_floor_w > 50:
                self._learn_parameters(p_floor_w, t_floor_c, t_room_c, dt_h)
            self._t_floor = t_floor_c
        else:
            # Geen sensor: simuleer vloertemperatuur via model
            if self._t_floor is None:
                self._t_floor = T_FLOOR_TARGET  # Koud starten met streefwaarde
            self._t_floor = self._simulate_step(p_floor_w, self._t_floor, t_room_c, dt_h)

        self._dirty = True

    def _simulate_step(
        self, p_w: float, t_floor: float, t_room: float, dt_h: float
    ) -> float:
        """
        Discretiseer de vloer-warmtebalans over één tijdstap.
            T_floor(t+dt) = T_floor(t) + dt/C × (P - UA × (T_floor - T_room))
        """
        c_wh = self._c_floor          # Wh/°C
        ua   = self._ua_floor         # W/°C
        delta_t = (p_w - ua * (t_floor - t_room)) * dt_h / c_wh
        return min(T_FLOOR_MAX_C + 2, max(T_FLOOR_MIN_C - 2, t_floor + delta_t))

    def _learn_parameters(
        self, p_w: float, t_floor_new: float, t_room: float, dt_h: float
    ) -> None:
        """
        Schat C_floor en UA_floor bij via gradient-vrije EMA-aanpassing.

        Principe: de gemeten temperatuurverandering per tijdstap (dT/dt_meas)
        moet overeenkomen met het model (dT/dt_model = (P - UA×ΔT) / C).
        We corrigeren C en UA elk iets in de goede richting.
        """
        if self._t_floor is None:
            return
        dt_floor_meas = t_floor_new - self._t_floor
        delta_tf_room = self._t_floor - t_room

        if abs(dt_floor_meas) < 0.05 or abs(delta_tf_room) < 1.0:
            return  # Te weinig signaal

        # Wat voorspelt het model?
        dt_model = (p_w - self._ua_floor * delta_tf_room) * dt_h / self._c_floor

        error = dt_floor_meas - dt_model

        alpha = ALPHA_FAST if self._samples < MIN_SAMPLES else ALPHA_SLOW

        # Correctie C_floor: als model te snel opwarmt → C te klein → vergroot C
        if abs(dt_model) > 1e-4:
            c_adj = self._c_floor * (1 + alpha * error / (dt_model + 1e-6))
            self._c_floor = max(50.0, min(50000.0, c_adj))

        # Correctie UA: als vloer te snel afkoelt → UA te groot → verklein UA
        if abs(delta_tf_room) > 2.0 and p_w < 50:
            ua_adj = self._ua_floor * (1 - alpha * 0.1 * (dt_floor_meas / (delta_tf_room * dt_h + 1e-6) + self._ua_floor / self._c_floor))
            self._ua_floor = max(0.5 * DEFAULT_UA_FLOOR_W_K * self._area,
                                 min(5.0 * DEFAULT_UA_FLOOR_W_K * self._area, ua_adj))

        self._samples += 1

    # ──────────────────────────────────────────────────────────────────
    # Planning — wordt eenmaal per dag aangeroepen
    # ──────────────────────────────────────────────────────────────────

    def plan_charge_windows(
        self,
        epex_prices_24h: list[dict],   # [{hour: 0, price_eur_kwh: 0.12}, ...]
        cop_by_temp: Optional[dict] = None,  # {outdoor_temp_bucket: cop_value}
        t_floor_now: Optional[float] = None,
        t_outside_now: float = 5.0,
    ) -> list[FloorWindow]:
        """
        Bereken optimale laadvensters voor de komende 24 uur.

        Algoritme
        ---------
        1. Simuleer vloertemperatuur uur-voor-uur voor elke mogelijke
           aan/uit-combinatie (vereenvoudigd: greedy op prijs + comfort).
        2. Selecteer goedkope uren waarbij vloer nog niet op max zit.
        3. Markeer dure uren als "afgifte" als de vloer voldoende warm is.

        Parameters
        ----------
        epex_prices_24h : Lijst met {hour, price_eur_kwh} voor de komende 24 uur.
        cop_by_temp     : Geleerde COP-curve van de warmtepomp (optioneel).
                          Wordt gebruikt om elektriciteitskosten per kWh warmte te berekenen.
        t_floor_now     : Huidige vloertemperatuur (overschrijft interne schatting).
        t_outside_now   : Huidige buitentemperatuur.
        """
        if len(epex_prices_24h) < 12:
            return []

        t_floor = t_floor_now if t_floor_now is not None else (
            self._t_floor if self._t_floor is not None else T_FLOOR_TARGET
        )
        t_room  = self._t_room

        # Gemiddelde prijs en goedkoop/duur drempels
        prices   = [p["price_eur_kwh"] for p in epex_prices_24h]
        avg_price = sum(prices) / len(prices)
        cheap_threshold = avg_price * 0.75
        expensive_threshold = avg_price * 1.30

        # Typisch vermogen vloerverwarming: UA_floor × (T_floor_target - T_room)
        p_typical_w = self._ua_floor * (T_FLOOR_TARGET - t_room)
        p_typical_w = max(500, min(5000, p_typical_w))

        # COP op huidige buitentemperatuur
        cop = self._get_cop(cop_by_temp, t_outside_now)

        windows: list[FloorWindow] = []
        t_sim = t_floor

        for entry in sorted(epex_prices_24h, key=lambda x: x["hour"]):
            hour  = entry["hour"]
            price = entry["price_eur_kwh"]
            dt_h  = 1.0  # uur-stapje in planning

            if price <= cheap_threshold and t_sim < T_FLOOR_MAX_C - 1.0:
                # Goedkoop uur + vloer heeft ruimte → laden
                action  = "laden"
                p_used  = p_typical_w * 1.2   # iets meer vermogen bij laden
                t_end   = self._simulate_step(p_used, t_sim, t_room, dt_h)
                t_end   = min(T_FLOOR_MAX_C, t_end)
                cost    = (p_used / 1000) * (price / cop)
            elif price >= expensive_threshold and t_sim > T_FLOOR_MIN_C + 1.5:
                # Duur uur + vloer is warm genoeg → laat de vloer afgeven zonder bij te verwarmen
                action  = "afgifte"
                p_used  = 0.0
                t_end   = self._simulate_step(0.0, t_sim, t_room, dt_h)
                t_end   = max(T_FLOOR_MIN_C, t_end)
                cost    = 0.0
            else:
                action  = "normaal"
                p_used  = p_typical_w * 0.8
                t_end   = self._simulate_step(p_used, t_sim, t_room, dt_h)
                cost    = (p_used / 1000) * (price / cop)

            windows.append(FloorWindow(
                start_hour    = hour,
                end_hour      = hour + 1,
                action        = action,
                price_ct_kwh  = round(price * 100, 2),
                t_floor_start = round(t_sim, 1),
                t_floor_end   = round(t_end, 1),
            ))
            t_sim = t_end

        self._plan_windows = windows

        # Schat besparing: afgifte-uren × typisch vermogen × (duur_prijs − gem_prijs) / COP
        savings = 0.0
        for w in windows:
            if w.action == "afgifte":
                price_diff = (w.price_ct_kwh / 100) - avg_price
                if price_diff > 0:
                    savings += (p_typical_w / 1000) * price_diff / cop
        self._savings_today_eur = round(savings, 3)

        return windows

    def _get_cop(self, cop_by_temp: Optional[dict], t_outside: float) -> float:
        """Geeft de COP op de huidige buitentemperatuur."""
        if not cop_by_temp:
            # Eenvoudige vaste formule als fallback (Langer & Volling aanpak)
            return max(1.5, 0.001 * t_outside**2 + 0.05 * t_outside + 3.0)
        # Zoek de dichtstbijzijnde bucket
        bucket = round(t_outside / 2) * 2
        for offset in [0, 2, -2, 4, -4, 6, -6]:
            cop = cop_by_temp.get(bucket + offset)
            if cop and cop > 1.0:
                return float(cop)
        return 3.0  # Fallback

    # ──────────────────────────────────────────────────────────────────
    # Status & output
    # ──────────────────────────────────────────────────────────────────

    def get_status(self) -> FloorBufferStatus:
        """Geeft huidige bufferstatus terug voor sensor-output."""
        t_floor = self._t_floor or T_FLOOR_TARGET
        confidence = min(1.0, self._samples / MIN_SAMPLES)

        # Huidige staat op basis van vermogen en vloertemperatuur
        if self._p_floor > 200 and t_floor < T_FLOOR_MAX_C - 0.5:
            state = "opladen"
            advice = f"Vloer wordt opgeladen: {t_floor:.1f}°C → streef {T_FLOOR_TARGET:.0f}°C"
        elif self._p_floor < 50 and t_floor > T_FLOOR_MIN_C + 1.0:
            state = "afgifte"
            advice = f"Vloer geeft warmte af: {t_floor:.1f}°C (min comfort: {T_FLOOR_MIN_C:.0f}°C)"
        elif t_floor is not None:
            state = "normaal"
            advice = f"Vloer op {t_floor:.1f}°C"
        else:
            state = "onbekend"
            advice = "Geen vloertemperatuursensor geconfigureerd — model schat."

        return FloorBufferStatus(
            state             = state,
            t_floor_c         = round(t_floor, 1),
            c_floor_wh_k      = round(self._c_floor, 0),
            ua_floor_w_k      = round(self._ua_floor, 1),
            charge_windows    = [
                {
                    "uur":    w.start_hour,
                    "actie":  w.action,
                    "prijs":  w.price_ct_kwh,
                    "t_start": w.t_floor_start,
                    "t_eind":  w.t_floor_end,
                }
                for w in self._plan_windows
            ],
            savings_today_eur = self._savings_today_eur,
            confidence        = round(confidence, 2),
            advice            = advice,
        )

    def get_state(self) -> str:
        """Sensorwaarde."""
        return self.get_status().state

    def get_t_floor(self) -> float:
        """Actuele (of geschatte) vloertemperatuur."""
        return round(self._t_floor or T_FLOOR_TARGET, 1)

    async def async_maybe_save(self) -> None:
        """Sla geleerde parameters op (max 1x per 5 min)."""
        if self._dirty and (time.time() - self._last_save) >= 300:
            await self._store.async_save({
                "c_floor":           round(self._c_floor, 2),
                "ua_floor":          round(self._ua_floor, 3),
                "samples":           self._samples,
                "t_floor_last":      self._t_floor,
                "savings_today_eur": self._savings_today_eur,
            })
            self._dirty     = False
            self._last_save = time.time()
