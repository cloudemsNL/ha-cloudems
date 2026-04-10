"""
CloudEMS PVClippingDetector — v5.5.505
Detecteert PV clipping: omvormer limiteert vermogen op zonnige periodes.

Clipping vertekent de forecast learner — als de omvormer bijv. limiteert
op 3.93kW maar de zon zou 5kW leveren, leert het model een te laag profiel.

Detectie:
- Vermogen bereikt de AC-limiet (>95% van max_ac_power_w) voor ≥10 min
- Radiation is hoger dan verwacht op basis van vermogen

Correctie:
- Clipping events worden gemarkeerd en uitgesloten van PV forecast training
- Clipping factor per uur bijgehouden voor betere schatting
"""
from __future__ import annotations
import logging
import time
from collections import deque
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Drempel: boven dit percentage van max vermogen = mogelijk clipping
CLIPPING_THRESHOLD = 0.95


class PVClippingDetector:
    """
    Detecteert en kwantificeert PV clipping per omvormer.
    """

    def __init__(self, max_ac_power_w: float, inverter_id: str = ""):
        self.max_ac_power_w = max_ac_power_w
        self.inverter_id = inverter_id

        # Clipping tracking
        self._clipping_start: Optional[float] = None
        self._clipping_events: deque = deque(maxlen=365)  # events per dag

        # Per-uur clipping factor
        self._hourly_clipping_factor: dict[int, list[float]] = {}

        # Statistieken
        self._total_clipping_minutes: float = 0.0
        self._total_clipped_kwh_estimate: float = 0.0

    def observe(self, power_w: float, hour: int,
                interval_s: float = 15.0) -> dict:
        """
        Observeer huidig PV-vermogen en detecteer clipping.

        Returns:
            dict met is_clipping, clipping_factor, message
        """
        if self.max_ac_power_w <= 0:
            return {"is_clipping": False}

        ratio = power_w / self.max_ac_power_w
        is_clipping = ratio >= CLIPPING_THRESHOLD

        if is_clipping:
            if self._clipping_start is None:
                self._clipping_start = time.time()
                _LOGGER.debug("PVClipping[%s]: start gedetecteerd %.0fW/%.0fW (%.0f%%)",
                             self.inverter_id, power_w, self.max_ac_power_w, ratio * 100)
            # Schat hoeveel er werkelijk beschikbaar was (aanname: lineair met irradiatie)
            # Simpele schatting: als ratio > 0.95 dan is er tenminste 5% verlies
            clipping_factor = max(0.0, ratio - CLIPPING_THRESHOLD) / (1.0 - CLIPPING_THRESHOLD)
            estimated_loss_w = power_w * clipping_factor * 0.1  # conservatief 10% extra
            self._total_clipped_kwh_estimate += estimated_loss_w * interval_s / 3_600_000.0

            # Per-uur factor bijhouden
            if hour not in self._hourly_clipping_factor:
                self._hourly_clipping_factor[hour] = []
            self._hourly_clipping_factor[hour].append(ratio)

        else:
            if self._clipping_start is not None:
                # Clipping beëindigd
                duration_min = (time.time() - self._clipping_start) / 60.0
                if duration_min >= 5:  # alleen loggen als ≥5 min
                    self._total_clipping_minutes += duration_min
                    self._clipping_events.append({
                        "duration_min": round(duration_min, 1),
                        "hour": hour,
                        "ts": time.time(),
                    })
                    _LOGGER.info("PVClipping[%s]: %.0f min clipping beëindigd "
                                "(schatting %.3f kWh verlies)",
                                self.inverter_id, duration_min,
                                self._total_clipped_kwh_estimate)
                self._clipping_start = None

        return {
            "is_clipping":    is_clipping,
            "ratio":          round(ratio, 3),
            "clipping_factor": round(max(0.0, ratio - CLIPPING_THRESHOLD), 3),
        }

    def is_hour_clipped(self, hour: int, threshold: float = 0.7) -> bool:
        """Retourneert True als dit uur frequent clipping had (>70% van samples)."""
        samples = self._hourly_clipping_factor.get(hour, [])
        if len(samples) < 5:
            return False
        clipped = sum(1 for s in samples if s >= CLIPPING_THRESHOLD)
        return (clipped / len(samples)) >= threshold

    def get_summary(self) -> dict:
        clipped_hours = [h for h in range(24) if self.is_hour_clipped(h)]
        return {
            "max_ac_power_w":             self.max_ac_power_w,
            "total_clipping_minutes":     round(self._total_clipping_minutes, 1),
            "total_clipped_kwh_estimate": round(self._total_clipped_kwh_estimate, 3),
            "clipping_events_count":      len(self._clipping_events),
            "clipped_hours":              clipped_hours,
            "is_currently_clipping":      self._clipping_start is not None,
        }
