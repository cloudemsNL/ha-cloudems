# -*- coding: utf-8 -*-
"""CloudEMS — KirchhoffBalancer v4.5.6.

Houdt per sensor bij hoe vers de meting is en berekent een ontbrekende
waarde uit de andere drie als die sensor te oud is.

Kirchhoff energiebalans:
    huis = solar + grid - battery
    → battery = solar + grid - huis
    → grid    = huis + battery - solar
    → solar   = huis + battery - grid

Begrippen:
    grid_w    : positief = import, negatief = export
    battery_w : positief = laden, negatief = ontladen
    solar_w   : altijd >= 0
    house_w   : altijd >= 0

Bij elke coordinator-cyclus:
1. Registreer de verse sensorwaarden met hun timestamp.
2. Controleer welke sensoren verouderd zijn (> max_age_s).
3. Als precies één sensor verouderd is: bereken hem uit de andere drie.
4. Als meerdere sensoren verouderd zijn: gebruik de EMA-gebaseerde schatting
   als zachte correctie (blend) — niet als harde vervanging.
5. Geef altijd een consistent viertal terug.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Sensor als verouderd beschouwen na:
_MAX_AGE_GRID_S    =  15.0   # P1 update elke 1-10s — na 15s is er iets mis
_MAX_AGE_SOLAR_S   =  30.0   # Omvormer telemetrie
_MAX_AGE_BATTERY_S = 120.0   # Cloud-batterij (Zonneplan) kan 60-300s traag zijn
_MAX_AGE_HOUSE_S   =  15.0   # Afgeleid, altijd vers als grid+solar vers zijn

# EMA alpha voor zachte schatting
_EMA_ALPHA = 0.15

# Minimale absolute waarde om te vertrouwen als "echt signaal"
_MIN_SIGNAL_W = 10.0


@dataclass
class BalancedReading:
    """Gecorrigeerde energiebalans met herkomst per sensor."""
    grid_w:    float
    solar_w:   float
    battery_w: float
    house_w:   float

    # Herkomst per waarde: "measured" / "kirchhoff" / "ema" / "held"
    grid_src:    str = "measured"
    solar_src:   str = "measured"
    battery_src: str = "measured"
    house_src:   str = "kirchhoff"  # house is altijd afgeleid

    # Balansresidu na correctie (ideaal 0)
    residual_w: float = 0.0
    corrected:  bool  = False


@dataclass
class _SensorState:
    """EMA + timestamp voor één sensor."""
    ema:      float = 0.0
    last_ts:  float = field(default_factory=time.time)
    last_val: float = 0.0
    n:        int   = 0

    def update(self, val: float) -> None:
        now = time.time()
        if self.n == 0:
            self.ema = val
        else:
            self.ema = _EMA_ALPHA * val + (1 - _EMA_ALPHA) * self.ema
        self.last_val = val
        self.last_ts  = now
        self.n       += 1

    def age_s(self) -> float:
        return time.time() - self.last_ts

    def is_fresh(self, max_age: float) -> bool:
        return self.age_s() <= max_age and self.n > 0


class KirchhoffBalancer:
    """Korrekt alle energiewaarden via Kirchhoff als een sensor traag is.

    Gebruik:
        balancer = KirchhoffBalancer()
        result = balancer.balance(grid_w, solar_w, battery_w, house_w_measured)
    """

    def __init__(self) -> None:
        self._grid    = _SensorState()
        self._solar   = _SensorState()
        self._battery = _SensorState()
        self._house   = _SensorState()   # huis = afgeleid uit vorige cyclus

    def balance(
        self,
        grid_w:    Optional[float],
        solar_w:   Optional[float],
        battery_w: Optional[float],
        *,
        grid_fresh:    bool = True,
        solar_fresh:   bool = True,
        battery_fresh: bool = True,
    ) -> BalancedReading:
        """Geef een consistente energiebalans.

        Parameters
        ----------
        grid_w       : netflow W (pos=import, neg=export). None als onbekend.
        solar_w      : PV vermogen W (>= 0). None als onbekend.
        battery_w    : batterijflow W (pos=laden, neg=ontladen). None als onbekend.
        grid_fresh   : is de grid-meting vers?
        solar_fresh  : is de solar-meting vers?
        battery_fresh: is de battery-meting vers?
        """
        # Normaliseer None naar EMA-schatting
        g = grid_w    if grid_w    is not None else self._grid.ema
        s = solar_w   if solar_w   is not None else self._solar.ema
        b = battery_w if battery_w is not None else self._battery.ema

        # Update EMA alleen met verse waarden
        if grid_w    is not None and grid_fresh:    self._grid.update(g)
        if solar_w   is not None and solar_fresh:   self._solar.update(s)
        if battery_w is not None and battery_fresh: self._battery.update(b)

        g_src = "measured" if grid_fresh    else "held"
        s_src = "measured" if solar_fresh   else "held"
        b_src = "measured" if battery_fresh else "held"
        corrected = False

        # Tel hoeveel sensoren stale zijn
        stale = (not grid_fresh) + (not solar_fresh) + (not battery_fresh)

        if stale == 0:
            # Alle sensoren vers — kleine Kirchhoff-correctie als residu > drempel
            house_raw = s + g - b
            residual  = house_raw - self._house.ema if self._house.n > 0 else 0.0

        elif stale == 1:
            # Precies één stale sensor — bereken hem exact uit de andere twee + huis EMA
            corrected = True
            if not battery_fresh:
                # Bereken battery uit grid + solar - huis_EMA
                house_est = self._house.ema if self._house.n >= 3 else max(0.0, s + g - b)
                b = s + g - house_est
                b_src = "kirchhoff"
                _LOGGER.debug(
                    "KirchhoffBalancer: battery stale → berekend %.0fW "
                    "(solar=%.0f grid=%.0f huis_ema=%.0f)",
                    b, s, g, house_est,
                )
            elif not grid_fresh:
                # Bereken grid uit huis_EMA + battery - solar
                house_est = self._house.ema if self._house.n >= 3 else max(0.0, s + g - b)
                g = house_est + b - s
                g_src = "kirchhoff"
                _LOGGER.debug(
                    "KirchhoffBalancer: grid stale → berekend %.0fW "
                    "(solar=%.0f battery=%.0f huis_ema=%.0f)",
                    g, s, b, house_est,
                )
            elif not solar_fresh:
                # Bereken solar uit huis_EMA + battery - grid (zelden nodig)
                house_est = self._house.ema if self._house.n >= 3 else max(0.0, s + g - b)
                s = max(0.0, house_est + b - g)  # solar kan nooit negatief
                s_src = "kirchhoff"
                _LOGGER.debug(
                    "KirchhoffBalancer: solar stale → berekend %.0fW "
                    "(grid=%.0f battery=%.0f huis_ema=%.0f)",
                    s, g, b, house_est,
                )

        else:
            # Meerdere stale sensoren — gebruik EMA-schattingen als zachte blend
            # Geen harde Kirchhoff-correctie want we hebben te weinig ankers
            _LOGGER.debug(
                "KirchhoffBalancer: %d stale sensoren — EMA blend (grid_ema=%.0f "
                "solar_ema=%.0f batt_ema=%.0f)",
                stale, self._grid.ema, self._solar.ema, self._battery.ema,
            )

        # Bereken huisverbruik (altijd Kirchhoff, nooit negatief)
        house_w  = max(0.0, s + g - b)
        residual = abs(house_w - self._house.ema) if self._house.n >= 3 else 0.0
        self._house.update(house_w)

        return BalancedReading(
            grid_w    = round(g, 1),
            solar_w   = round(max(0.0, s), 1),
            battery_w = round(b, 1),
            house_w   = round(house_w, 1),
            grid_src    = g_src,
            solar_src   = s_src,
            battery_src = b_src,
            house_src   = "kirchhoff",
            residual_w  = round(residual, 1),
            corrected   = corrected,
        )

    def get_diagnostics(self) -> dict:
        return {
            "grid_ema_w":    round(self._grid.ema, 1),
            "solar_ema_w":   round(self._solar.ema, 1),
            "battery_ema_w": round(self._battery.ema, 1),
            "house_ema_w":   round(self._house.ema, 1),
            "grid_age_s":    round(self._grid.age_s(), 1),
            "solar_age_s":   round(self._solar.age_s(), 1),
            "battery_age_s": round(self._battery.age_s(), 1),
        }
