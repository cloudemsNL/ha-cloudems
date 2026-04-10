"""
CloudEMS MeasurementTracker — v5.5.520

Vergelijkt gemeten (sensor) vs berekende (W×t) kWh per stroom.
Leert lokaal de correctiefactor zodat de fallback berekening steeds nauwkeuriger wordt.

Principe:
    sensor_kwh    = directe meting (primair, betrouwbaar)
    calc_kwh      = W × tijd (fallback)
    factor        = sensor / calc  (1.0 = perfect)

Als sensor wegvalt → gecorrigeerde W×t als fallback:
    corrected_kwh = calc_kwh × learned_factor

Geen cloud correctie — dat is voor later met statistische validatie.
"""
from __future__ import annotations
import logging
import time
from collections import deque
from typing import Optional

_LOGGER = logging.getLogger(__name__)

DEVIATION_WARN_PCT = 20.0   # log WARNING als afwijking > 20%
MIN_SAMPLES        = 5      # minimale samples voor betrouwbare factor
WINDOW             = 30     # rolling window (dagen)


class StreamTracker:
    """Bijhoudt sensor vs berekening voor één stroom."""

    def __init__(self, name: str):
        self.name             = name
        self._sensor_days:    deque = deque(maxlen=WINDOW)
        self._calc_days:      deque = deque(maxlen=WINDOW)
        self._factor_samples: deque = deque(maxlen=WINDOW)
        self._last_warn_ts:   float = 0.0
        self._sensor_ok:      bool  = False  # sensor actief in laatste cyclus

    def observe_day(self, sensor_kwh: float, calc_kwh: float) -> None:
        """Voeg één dagmeting toe (aanroepen bij dagovergang)."""
        if calc_kwh < 0.1 or sensor_kwh < 0:
            return
        factor = sensor_kwh / calc_kwh
        self._sensor_days.append(sensor_kwh)
        self._calc_days.append(calc_kwh)
        self._factor_samples.append(factor)

        dev_pct = abs(factor - 1.0) * 100
        if dev_pct > DEVIATION_WARN_PCT and time.time() - self._last_warn_ts > 3600:
            _LOGGER.warning(
                "MeasurementTracker[%s]: structurele afwijking %.1f%% "
                "(sensor=%.3f kWh berekend=%.3f kWh factor=%.3f) — "
                "fallback wordt bijgestuurd",
                self.name, dev_pct, sensor_kwh, calc_kwh, factor
            )
            self._last_warn_ts = time.time()
        else:
            _LOGGER.debug(
                "MeasurementTracker[%s]: sensor=%.3f kWh calc=%.3f kWh "
                "factor=%.3f (afwijking %.1f%%)",
                self.name, sensor_kwh, calc_kwh, factor, dev_pct
            )

    def apply(self, calc_kwh: float, sensor_kwh: Optional[float] = None) -> tuple[float, str]:
        """
        Geef beste kWh schatting terug.
        Returns: (kwh, bron) waarbij bron = 'sensor' | 'corrected_calc' | 'raw_calc'
        """
        if sensor_kwh is not None and sensor_kwh >= 0:
            self._sensor_ok = True
            return sensor_kwh, "sensor"

        self._sensor_ok = False
        factor = self.learned_factor
        if factor is not None:
            corrected = round(calc_kwh * factor, 4)
            return corrected, "corrected_calc"

        return calc_kwh, "raw_calc"

    @property
    def learned_factor(self) -> Optional[float]:
        """Geleerde correctiefactor (mediaan over window)."""
        if len(self._factor_samples) < MIN_SAMPLES:
            return None
        sorted_f = sorted(self._factor_samples)
        mid = len(sorted_f) // 2
        return round(sorted_f[mid], 4)  # mediaan — robuust tegen uitschieters

    @property
    def deviation_pct(self) -> Optional[float]:
        f = self.learned_factor
        return round(abs(f - 1.0) * 100, 1) if f is not None else None

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "learned_factor":  self.learned_factor,
            "deviation_pct":   self.deviation_pct,
            "samples":         len(self._factor_samples),
            "sensor_active":   self._sensor_ok,
        }

    def to_persist(self) -> dict:
        return {
            "sensor_days":    list(self._sensor_days),
            "calc_days":      list(self._calc_days),
            "factor_samples": list(self._factor_samples),
        }

    @classmethod
    def from_persist(cls, name: str, data: dict) -> "StreamTracker":
        t = cls(name)
        t._sensor_days    = deque(data.get("sensor_days", []),    maxlen=WINDOW)
        t._calc_days      = deque(data.get("calc_days", []),      maxlen=WINDOW)
        t._factor_samples = deque(data.get("factor_samples", []), maxlen=WINDOW)
        return t


class MeasurementTracker:
    """
    Beheert StreamTrackers voor alle energiestromen.
    Publiceert correctiefactoren naar data["measurement_factors"].
    """

    STREAMS = ["pv", "grid_import", "grid_export",
               "bat_charge", "bat_discharge"]

    def __init__(self):
        self._trackers: dict[str, StreamTracker] = {
            s: StreamTracker(s) for s in self.STREAMS
        }

    def get(self, stream: str) -> StreamTracker:
        if stream not in self._trackers:
            self._trackers[stream] = StreamTracker(stream)
        return self._trackers[stream]

    def apply_pv(self, calc_kwh: float,
                 sensor_kwh: Optional[float] = None) -> tuple[float, str]:
        return self.get("pv").apply(calc_kwh, sensor_kwh)

    def apply_grid_import(self, calc_kwh: float,
                          sensor_kwh: Optional[float] = None) -> tuple[float, str]:
        return self.get("grid_import").apply(calc_kwh, sensor_kwh)

    def apply_grid_export(self, calc_kwh: float,
                          sensor_kwh: Optional[float] = None) -> tuple[float, str]:
        return self.get("grid_export").apply(calc_kwh, sensor_kwh)

    def apply_battery(self, calc_charge: float, calc_discharge: float,
                      sensor_charge: Optional[float] = None,
                      sensor_discharge: Optional[float] = None) -> dict:
        chg, chg_src = self.get("bat_charge").apply(calc_charge, sensor_charge)
        dis, dis_src = self.get("bat_discharge").apply(calc_discharge, sensor_discharge)
        return {
            "charge_kwh": chg, "charge_src": chg_src,
            "discharge_kwh": dis, "discharge_src": dis_src,
        }

    def commit_day(self, stream: str,
                   sensor_kwh: float, calc_kwh: float) -> None:
        """Dagovergang — sla meting op voor leren."""
        self.get(stream).observe_day(sensor_kwh, calc_kwh)

    def to_data_dict(self) -> dict:
        """Publiceert alle factoren naar data dict."""
        return {
            s: t.to_dict() for s, t in self._trackers.items()
        }

    def to_persist(self) -> dict:
        return {s: t.to_persist() for s, t in self._trackers.items()}

    @classmethod
    def from_persist(cls, data: dict) -> "MeasurementTracker":
        mt = cls()
        for stream, sdata in data.items():
            if stream in mt._trackers:
                mt._trackers[stream] = StreamTracker.from_persist(stream, sdata)
        return mt
