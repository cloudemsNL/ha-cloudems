"""CloudEMS HeatPumpCOPLearner — v1.15.0.

Learns the COP (Coefficient of Performance) curve of a heat pump from
live measurements, grouped by outdoor temperature bucket.

Inspired by HeatPumpAutoDetect in CloudEMS v7 / TuyaWizard.

Algorithm
---------
COP = thermal_power_out / electric_power_in

If thermal sensor is available:
    COP direct = thermal_w / electric_w

If only electric power is available (most common in HA):
    Estimate thermal from the thermal house model:
        thermal_w ≈ w_per_k × (indoor_temp – outdoor_temp)
    Fallback formula from Tuya auto_detect:
        COP ≈ 0.001 × T² + 0.05 × T + 3.0  (T = outdoor_temp_c)

Defrost detection
-----------------
Defrost cycles appear as COP dips (COP < 1.0 at temperatures > -5°C).
They are identified and excluded from the learning curve.

Output
------
Per outdoor temp bucket (−20 to +20°C, step 2°C):
  - cop_mean: learned average COP
  - cop_ema: smoothed EMA
  - samples: number of observations

Sensors exposed:
  - cloudems_heat_pump_cop_current: current measured/estimated COP
  - cloudems_heat_pump_cop_7c: learned COP at 7°C reference
  - cloudems_heat_pump_defrost_count_today: defrost cycle count
"""
from __future__ import annotations
import logging
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

BUCKET_SIZE_C   = 2.0       # Group measurements per 2°C bucket
MIN_ELECTRIC_W  = 100       # Ignore readings below 100 W (standby/off)
DEFROST_COP     = 0.8       # COP below this = likely defrost cycle
DEFROST_MAX_C   = 5.0       # Only flag defrost below 5°C outdoor
COP_EMA_ALPHA   = 0.05      # Slow EMA per bucket (seasonal stability)
MIN_SAMPLES_RELIABLE = 20   # Minimum samples per bucket for reliability
SAVE_INTERVAL_S = 300       # Save every 5 minutes


@dataclass
class BucketData:
    cop_ema:    float = 3.0
    cop_mean:   float = 3.0
    samples:    int   = 0
    sum_cop:    float = 0.0
    defrost_n:  int   = 0


@dataclass
class COPReport:
    cop_current:     Optional[float]
    cop_at_7c:       Optional[float]
    cop_at_2c:       Optional[float]
    cop_at_minus5c:  Optional[float]
    defrost_today:   int
    defrost_threshold_c: float
    outdoor_temp_c:  Optional[float]
    reliable:        bool
    method:          str      # "direct" | "thermal_model" | "formula"
    curve:           Dict[float, float]   # temp → cop_ema


class HeatPumpCOPLearner:
    """Learns heat pump COP from live measurements."""

    def __init__(self, hass=None):
        self._hass = hass
        self._buckets: Dict[float, BucketData] = {}   # bucket_key → data
        self._defrost_today  = 0
        self._defrost_day_k  = ""
        self._last_save_ts   = 0.0
        self._last_cop: Optional[float] = None
        self._method = "formula"
        self._store_key = "cloudems_hp_cop"

    # ── Public API ────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        if self._hass:
            from homeassistant.helpers.storage import Store
            self._store = Store(self._hass, 1, self._store_key)
            saved = await self._store.async_load()
            if saved:
                self._load_state(saved)
                _LOGGER.info("CloudEMS HeatPumpCOPLearner: loaded %d buckets",
                             len(self._buckets))

    def update(
        self,
        electric_w:   float,
        outdoor_temp_c: Optional[float],
        thermal_w:    Optional[float] = None,
        w_per_k:      Optional[float] = None,
        indoor_temp_c: Optional[float] = None,
    ) -> COPReport:
        """Feed one measurement and return current COP state."""
        import datetime as _dt
        day_k = _dt.date.today().isoformat()
        if self._defrost_day_k != day_k:
            self._defrost_today = 0
            self._defrost_day_k = day_k

        if electric_w < MIN_ELECTRIC_W:
            return self._make_report(outdoor_temp_c, None)

        # Calculate COP
        cop: Optional[float] = None
        method = "formula"

        if thermal_w and thermal_w > 0 and electric_w > 0:
            cop    = thermal_w / electric_w
            method = "direct"
        elif w_per_k and indoor_temp_c and outdoor_temp_c is not None:
            delta  = indoor_temp_c - outdoor_temp_c
            if delta > 0:
                est_thermal_w = w_per_k * delta
                cop            = est_thermal_w / electric_w
                method         = "thermal_model"
        
        if cop is None and outdoor_temp_c is not None:
            # Fallback formula (from Tuya HeatPumpAutoDetect)
            t = outdoor_temp_c
            cop = max(1.0, 0.001 * t * t + 0.05 * t + 3.0)
            method = "formula"

        if cop is None:
            return self._make_report(outdoor_temp_c, None)

        cop = round(max(0.5, min(8.0, cop)), 2)
        self._last_cop = cop
        self._method   = method

        # Defrost detection
        if (cop < DEFROST_COP and outdoor_temp_c is not None
                and outdoor_temp_c < DEFROST_MAX_C):
            self._defrost_today += 1
            _LOGGER.debug("Defrost cycle detected (COP=%.2f, T=%.1f°C)", cop, outdoor_temp_c)
            # Don't update learning curve during defrost
            return self._make_report(outdoor_temp_c, cop)

        # Update bucket
        if outdoor_temp_c is not None:
            bkey = round(math.floor(outdoor_temp_c / BUCKET_SIZE_C) * BUCKET_SIZE_C, 1)
            bkt  = self._buckets.setdefault(bkey, BucketData())
            bkt.samples  += 1
            bkt.sum_cop  += cop
            bkt.cop_mean  = bkt.sum_cop / bkt.samples
            bkt.cop_ema   = COP_EMA_ALPHA * cop + (1.0 - COP_EMA_ALPHA) * bkt.cop_ema

        return self._make_report(outdoor_temp_c, cop)

    def get_report(self, outdoor_temp_c: Optional[float] = None) -> COPReport:
        return self._make_report(outdoor_temp_c, self._last_cop)

    async def async_maybe_save(self) -> None:
        if time.time() - self._last_save_ts > SAVE_INTERVAL_S:
            if hasattr(self, "_store"):
                await self._store.async_save(self._dump_state())
                self._last_save_ts = time.time()

    # ── Internal ─────────────────────────────────────────────────────────

    def _interpolate_cop(self, target_c: float) -> Optional[float]:
        if not self._buckets:
            return None
        keys = sorted(self._buckets.keys())
        if target_c <= keys[0]:
            return self._buckets[keys[0]].cop_ema
        if target_c >= keys[-1]:
            return self._buckets[keys[-1]].cop_ema
        for i in range(len(keys) - 1):
            if keys[i] <= target_c <= keys[i + 1]:
                t = (target_c - keys[i]) / (keys[i + 1] - keys[i])
                return (self._buckets[keys[i]].cop_ema * (1 - t)
                        + self._buckets[keys[i + 1]].cop_ema * t)
        return None

    def _make_report(self, outdoor_c, cop_now) -> COPReport:
        total_samples = sum(b.samples for b in self._buckets.values())
        reliable = total_samples >= MIN_SAMPLES_RELIABLE * 3

        curve = {
            k: round(v.cop_ema, 2)
            for k, v in sorted(self._buckets.items())
            if v.samples >= 3
        }

        # Detect defrost threshold (lowest temp with good data)
        defrost_thresh = -2.0
        cold_buckets = [k for k in self._buckets if k < 5.0
                        and self._buckets[k].samples >= 5]
        if cold_buckets:
            defrost_thresh = min(cold_buckets)

        return COPReport(
            cop_current     = cop_now,
            cop_at_7c       = self._interpolate_cop(7.0),
            cop_at_2c       = self._interpolate_cop(2.0),
            cop_at_minus5c  = self._interpolate_cop(-5.0),
            defrost_today   = self._defrost_today,
            defrost_threshold_c = defrost_thresh,
            outdoor_temp_c  = outdoor_c,
            reliable        = reliable,
            method          = self._method,
            curve           = curve,
        )

    def _dump_state(self) -> dict:
        return {
            "buckets": {
                str(k): {
                    "cop_ema":  v.cop_ema,
                    "cop_mean": v.cop_mean,
                    "samples":  v.samples,
                    "sum_cop":  v.sum_cop,
                    "defrost_n":v.defrost_n,
                }
                for k, v in self._buckets.items()
            }
        }

    def _load_state(self, data: dict) -> None:
        for k_str, v in data.get("buckets", {}).items():
            bkt = BucketData()
            bkt.cop_ema   = v.get("cop_ema",  3.0)
            bkt.cop_mean  = v.get("cop_mean", 3.0)
            bkt.samples   = v.get("samples",  0)
            bkt.sum_cop   = v.get("sum_cop",  0.0)
            bkt.defrost_n = v.get("defrost_n",0)
            try:
                self._buckets[float(k_str)] = bkt
            except ValueError:
                pass
