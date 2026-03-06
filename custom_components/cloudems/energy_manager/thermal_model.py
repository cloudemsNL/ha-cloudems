# -*- coding: utf-8 -*-
"""
CloudEMS Thermisch Huismodel — v1.0.0

Leert automatisch de thermische verliescoëfficiënt van het huis:
  warmteverlies_W / temperatuurverschil_K = W/°C

Data:
  - Verwarmingsvermogen (W): NILM herkende warmte-apparaten (warmtepomp, CV)
                             of totaalverbruik als fallback
  - Buitentemperatuur (°C): sensor uit HA config

Methode:
  - Elke meting: verwarmingsvermogen ÷ (binnentemp_setpoint − buiten_temp)
  - Exponentieel voortschrijdend gemiddelde van W/°C
  - Na 30 verwarmingsdagen: score + vergelijking met benchmarks
  - Opslaan in HA Store voor persistentie

Benchmarks (NL):
  Slecht (jaren 70 woning):       > 350 W/°C
  Gemiddeld (spouwmuur):       200–350 W/°C
  Goed (na-isolatie / 1990s):  100–200 W/°C
  Uitstekend (passiefhuis):     < 100 W/°C

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import aiohttp
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_thermal_model_v1"
STORAGE_VERSION = 1

# Drempelwaarden
MIN_HEATING_W           = 500     # Minimaal verwarmingsvermogen om meting te doen
MIN_DELTA_TEMP_K        = 3.0     # Minimaal temperatuurverschil voor betrouwbare meting
INDOOR_SETPOINT_C       = 20.0    # Aangenomen binnentemperatuur setpoint
ALPHA_EMA_FAST          = 0.25    # Snel leren bij weinig data
ALPHA_EMA_MID           = 0.10    # Middel tempo
ALPHA_EMA_SLOW          = 0.05    # Traag leren zodra model stabiel is
MIN_SAMPLES_RELIABLE    = 20      # Metingen voor betrouwbare schatting
SAVE_INTERVAL_S         = 300

# Benchmarks W/°C
BENCH_EXCELLENT = 100
BENCH_GOOD      = 200
BENCH_AVERAGE   = 350


@dataclass
class ThermalModelData:
    """Output van het thermisch model."""
    w_per_k: float                    # Geschatte verliescoëfficiënt
    samples: int                      # Aantal metingen
    reliable: bool                    # Voldoende metingen?
    rating: str                       # "uitstekend" | "goed" | "gemiddeld" | "slecht"
    benchmark_pct: float              # % slechter dan passiefhuis-grens
    advice: str                       # Mensleesbare aanbeveling
    last_heating_w: float             # Laatste verwarmingsvermogen
    last_outside_temp_c: float        # Laatste buitentemperatuur
    heating_days: int                 # Dagen met actieve verwarming


def _rating(w_per_k: float) -> tuple[str, str]:
    """Geeft rating en advies op basis van W/°C."""
    if w_per_k < BENCH_EXCELLENT:
        return "uitstekend", "Jouw huis heeft een uitstekende isolatie (passiefhuis-niveau)."
    elif w_per_k < BENCH_GOOD:
        return "goed", f"Jouw huis is goed geïsoleerd. Een gemiddeld huis verliest {BENCH_AVERAGE} W/°C."
    elif w_per_k < BENCH_AVERAGE:
        return "gemiddeld", (
            f"Jouw huis verliest {w_per_k:.0f} W/°C — gemiddeld. "
            f"Extra isolatie kan dit naar <{BENCH_GOOD} W/°C brengen en de verwarmingskosten flink verlagen."
        )
    else:
        return "slecht", (
            f"Jouw huis verliest {w_per_k:.0f} W/°C — relatief slecht. "
            f"Een goed geïsoleerd huis zit op {BENCH_GOOD} W/°C. "
            "Overweeg na-isolatie (spouwmuur, vloer, dak) of HR++ glas."
        )


class ThermalHouseModel:
    """
    Leert de thermische verliescoëfficiënt van het huis.

    Aanroep vanuit coordinator:
        model.update(heating_w=2400, outside_temp_c=5.0)
        data = model.get_data()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._w_per_k: float = 0.0
        self._samples: int   = 0
        self._heating_days_seen: set[str] = set()
        self._dirty = False
        self._last_save = 0.0
        self._last_outside_temp = 0.0
        self._last_heating_w    = 0.0

    async def async_setup(self) -> None:
        """Laad persistente data."""
        saved: dict = await self._store.async_load() or {}
        self._w_per_k     = float(saved.get("w_per_k", 0.0))
        self._samples     = int(saved.get("samples", 0))
        self._heating_days_seen = set(saved.get("heating_days", []))
        _LOGGER.info(
            "ThermalModel: geladen — %.0f W/°C (%d samples, %d verwarmingsdagen)",
            self._w_per_k, self._samples, len(self._heating_days_seen),
        )
        # v1.15.0: Open-Meteo temperature fallback
        self._openmeteo_temp: float | None = None
        self._openmeteo_ts:   float = 0.0
        self._openmeteo_lat:  float | None = None
        self._openmeteo_lon:  float | None = None
        try:
            self._openmeteo_lat = self._hass.config.latitude
            self._openmeteo_lon = self._hass.config.longitude
        except Exception:
            pass

    def update(self, heating_w: float, outside_temp_c: float) -> None:
        """
        Voeg een nieuwe meting toe.

        Parameters
        ----------
        heating_w       : actueel verwarmingsvermogen in Watt
        outside_temp_c  : buitentemperatuur in °C
        """
        self._last_outside_temp = outside_temp_c
        self._last_heating_w    = heating_w

        delta_k = INDOOR_SETPOINT_C - outside_temp_c

        if heating_w < MIN_HEATING_W or delta_k < MIN_DELTA_TEMP_K:
            return  # Te weinig signaal

        measured_w_per_k = heating_w / delta_k

        alpha = ALPHA_EMA_FAST if self._samples < 5 else (ALPHA_EMA_MID if self._samples < 20 else ALPHA_EMA_SLOW)
        if self._samples == 0:
            self._w_per_k = measured_w_per_k
        else:
            self._w_per_k = alpha * measured_w_per_k + (1 - alpha) * self._w_per_k

        self._samples += 1
        self._dirty = True

        # Bijhouden verwarmingsdagen
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._heating_days_seen.add(today)

        reliable = self._samples >= MIN_SAMPLES_RELIABLE
        bar = '#' * min(self._samples, MIN_SAMPLES_RELIABLE) + '.' * max(0, MIN_SAMPLES_RELIABLE - self._samples)
        if self._samples <= MIN_SAMPLES_RELIABLE or self._samples % 10 == 0:
            _LOGGER.info(
                "ThermalModel: leren %d/%d [%s] — %.0f W/°C%s (%d verwarmingsdagen)",
                min(self._samples, MIN_SAMPLES_RELIABLE), MIN_SAMPLES_RELIABLE, bar,
                self._w_per_k,
                " ✅ betrouwbaar" if reliable and self._samples == MIN_SAMPLES_RELIABLE else "",
                len(self._heating_days_seen),
            )

    def get_data(self) -> ThermalModelData:
        """Geeft het huidige thermische model terug."""
        w_per_k   = round(self._w_per_k, 1) if self._w_per_k > 0 else 0.0
        reliable  = self._samples >= MIN_SAMPLES_RELIABLE
        rating, advice = _rating(w_per_k) if w_per_k > 0 else ("onbekend", "Nog te weinig verwarmingsdata.")
        bench_pct = round((w_per_k / BENCH_EXCELLENT - 1) * 100, 1) if w_per_k > 0 else 0.0

        return ThermalModelData(
            w_per_k            = w_per_k,
            samples            = self._samples,
            reliable           = reliable,
            rating             = rating,
            benchmark_pct      = bench_pct,
            advice             = advice,
            last_heating_w     = round(self._last_heating_w, 0),
            last_outside_temp_c= round(self._last_outside_temp, 1),
            heating_days       = len(self._heating_days_seen),
        )

    def get_state(self) -> float:
        """Sensorwaarde: W/°C (0 als onbekend)."""
        return round(self._w_per_k, 1) if self._w_per_k > 0 else 0.0


    async def async_fetch_outdoor_temp(self, session=None) -> float | None:
        """Fetch current outdoor temperature from Open-Meteo when no HA sensor is configured.
        
        Inspired by the boiler project's Open-Meteo integration.
        Returns cached value if last fetch was < 15 minutes ago.
        """
        import time as _t
        if _t.time() - self._openmeteo_ts < 900:
            return self._openmeteo_temp  # 15-min cache
        if not self._openmeteo_lat or not self._openmeteo_lon:
            return None
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._openmeteo_lat:.4f}&longitude={self._openmeteo_lon:.4f}"
            f"&current=temperature_2m&timezone=auto"
        )
        try:
            sess = session
            own_sess = False
            if not sess:
                sess = aiohttp.ClientSession()
                own_sess = True
            try:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        t = data.get("current", {}).get("temperature_2m")
                        if t is not None:
                            self._openmeteo_temp = float(t)
                            self._openmeteo_ts   = _t.time()
                            _LOGGER.debug("ThermalModel: Open-Meteo outdoor temp %.1f°C", t)
                            return self._openmeteo_temp
            finally:
                if own_sess:
                    await sess.close()
        except Exception as exc:
            _LOGGER.debug("ThermalModel: Open-Meteo fetch failed: %s", exc)
        return self._openmeteo_temp  # Return cached even if stale on failure

    async def async_maybe_save(self) -> None:
        """Sla op als er wijzigingen zijn en het interval verstreken is."""
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "w_per_k":     round(self._w_per_k, 3),
                "samples":     self._samples,
                "heating_days": list(self._heating_days_seen)[-365:],  # max 1 jaar
            })
            self._dirty     = False
            self._last_save = time.time()
