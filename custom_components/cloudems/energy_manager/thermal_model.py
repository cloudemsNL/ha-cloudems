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
ALPHA_EMA               = 0.05    # EMA smoothing (traag leren = stabiele schatting)
MIN_SAMPLES_RELIABLE    = 50      # Metingen voor betrouwbare schatting
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

        if self._samples == 0:
            self._w_per_k = measured_w_per_k
        else:
            self._w_per_k = ALPHA_EMA * measured_w_per_k + (1 - ALPHA_EMA) * self._w_per_k

        self._samples += 1
        self._dirty = True

        # Bijhouden verwarmingsdagen
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._heating_days_seen.add(today)

        if self._samples % 100 == 0:
            _LOGGER.info(
                "ThermalModel: schatting %.0f W/°C na %d samples (%d verwarmingsdagen)",
                self._w_per_k, self._samples, len(self._heating_days_seen),
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
