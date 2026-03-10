# -*- coding: utf-8 -*-
"""CloudEMS HeatPumpCOPLearner — v1.16.0.

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
MIN_SAMPLES_RELIABLE = 8    # Minimum samples per bucket for reliability
COP_EMA_ALPHA_FAST = 0.25   # Fast EMA when bucket has few samples
COP_EMA_ALPHA_MID  = 0.10   # Mid EMA
COP_EMA_ALPHA_SLOW = 0.05   # Slow EMA once bucket is reliable (seasonal stability)
SAVE_INTERVAL_S = 300       # Save every 5 minutes


@dataclass
class BucketData:
    cop_ema:    float = 3.0
    cop_mean:   float = 3.0
    samples:    int   = 0
    sum_cop:    float = 0.0
    defrost_n:  int   = 0
    # Tijdreeks voor kortetermijn-degradatiedetectie (max 60 metingen)
    recent_cops: list = None
    # Jaar-op-jaar seizoenstabel: {"2024-winter": avg_cop, "2025-winter": avg_cop, ...}
    # Slaat per seizoen het gemiddelde op zodat jaar-op-jaar achteruitgang zichtbaar wordt.
    seasonal_avgs: dict = None

    def __post_init__(self):
        if self.recent_cops  is None: self.recent_cops  = []
        if self.seasonal_avgs is None: self.seasonal_avgs = {}

    def add_cop(self, cop: float, season_key: str) -> None:
        self.recent_cops.append(cop)
        if len(self.recent_cops) > 60:
            self.recent_cops = self.recent_cops[-60:]
        # Bijhouden seizoensgemiddelde via EMA per seizoenssleutel
        if season_key not in self.seasonal_avgs:
            self.seasonal_avgs[season_key] = cop
        else:
            # Trage EMA zodat het seizoensgemiddelde stabiel is
            self.seasonal_avgs[season_key] = (
                0.05 * cop + 0.95 * self.seasonal_avgs[season_key]
            )


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
    degradation_detected: bool = False   # COP structureel gedaald vs baseline
    degradation_pct: float = 0.0        # hoeveel % gedaald (positief = slechter)
    degradation_advice: str = ""        # adviestekst


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

        # Seizoen bepalen (voor jaar-op-jaar tracking)
        import datetime as _dt_s
        _m = _dt_s.date.today().month
        season = (
            "winter" if _m in (12, 1, 2) else
            "spring" if _m in (3, 4, 5)  else
            "summer" if _m in (6, 7, 8)  else
            "autumn"
        )

        # Update bucket
        if outdoor_temp_c is not None:
            bkey = round(math.floor(outdoor_temp_c / BUCKET_SIZE_C) * BUCKET_SIZE_C, 1)
            bkt  = self._buckets.setdefault(bkey, BucketData())
            bkt.samples  += 1
            bkt.sum_cop  += cop
            bkt.cop_mean  = bkt.sum_cop / bkt.samples
            cop_alpha = COP_EMA_ALPHA_FAST if bkt.samples < 5 else (COP_EMA_ALPHA_MID if bkt.samples < 15 else COP_EMA_ALPHA_SLOW)
            bkt.cop_ema   = cop_alpha * cop + (1.0 - cop_alpha) * bkt.cop_ema
            season_key = f"{_dt.date.today().year}-{season}"
            bkt.add_cop(cop, season_key)
            total_samples = sum(b.samples for b in self._buckets.values())
            reliable_buckets = sum(1 for b in self._buckets.values() if b.samples >= MIN_SAMPLES_RELIABLE)
            _LOGGER.info(
                "HeatPumpCOP: %d°C-bucket sample %d — COP=%.2f (EMA=%.2f) | "
                "%d buckets betrouwbaar, %d metingen totaal",
                int(bkey), bkt.samples, cop, bkt.cop_ema, reliable_buckets, total_samples,
            )

        return self._make_report(outdoor_temp_c, cop)

    def get_report(self, outdoor_temp_c: Optional[float] = None) -> COPReport:
        return self._make_report(outdoor_temp_c, self._last_cop)

    def get_heating_rate_estimate(self, outdoor_temp_c: Optional[float] = None) -> Optional[float]:
        """Schat verwarmingssnelheid (K/min) op basis van de geleerde COP-curve.

        Een hogere COP bij mildere temperaturen impliceert hogere thermische capaciteit
        en dus een hogere verwarmingssnelheid. Geeft None terug als er te weinig data is.

        Gebruik als prior seed voor PredictiveStartScheduler.rate_ema.
        """
        total_samples = sum(b.samples for b in self._buckets.values())
        if total_samples < MIN_SAMPLES_RELIABLE:
            return None

        ref_temp = outdoor_temp_c if outdoor_temp_c is not None else 7.0
        cop = self._interpolate_cop(ref_temp)
        if cop is None:
            return None

        # Empirische schaling: COP 3.0 ≈ 0.20 K/min (HA-default prior)
        # COP 4.0 ≈ 0.27 K/min, COP 2.0 ≈ 0.13 K/min
        rate = 0.20 * (cop / 3.0)
        return round(max(0.05, min(1.0, rate)), 3)

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

        # Degradatiedetectie: vergelijk recente COP met vroegere baseline
        degradation_detected = False
        degradation_pct = 0.0
        degradation_advice = ""
        if reliable and outdoor_c is not None:
            bkey = round(math.floor(outdoor_c / BUCKET_SIZE_C) * BUCKET_SIZE_C, 1)
            bkt = self._buckets.get(bkey)
            if bkt and len(bkt.recent_cops) >= 20:
                recent_10  = bkt.recent_cops[-10:]
                baseline_10 = bkt.recent_cops[-30:-20] if len(bkt.recent_cops) >= 30 else bkt.recent_cops[:10]
                avg_recent   = sum(recent_10) / len(recent_10)
                avg_baseline = sum(baseline_10) / len(baseline_10)
                if avg_baseline > 0:
                    drop_pct = (avg_baseline - avg_recent) / avg_baseline * 100
                    if drop_pct > 15:
                        degradation_detected = True
                        degradation_pct = round(drop_pct, 1)
                        degradation_advice = (
                            f"Warmtepomp COP is {degradation_pct:.0f}% lager dan eerder "
                            f"bij {outdoor_c:.0f}°C (van {avg_baseline:.2f} naar {avg_recent:.2f}). "
                            "Mogelijke oorzaken: ijsvorming op buitenunit, filter vervuild, "
                            "koudemiddel verlaagd. Overweeg onderhoud."
                        )

        # ── Jaar-op-jaar seizoensdegradatie ──────────────────────────────────
        # Vergelijk het COP-gemiddelde van hetzelfde seizoen dit jaar vs. vorig jaar.
        # Bv: winter 2025 vs. winter 2024 bij dezelfde buitentemperatuur.
        yoy_detected    = False
        yoy_drop_pct    = 0.0
        yoy_advice      = ""
        if outdoor_c is not None:
            bkey_ref = round(math.floor(outdoor_c / BUCKET_SIZE_C) * BUCKET_SIZE_C, 1)
            bkt_ref = self._buckets.get(bkey_ref)
            if bkt_ref and bkt_ref.seasonal_avgs:
                import datetime as _dt_yoy
                m = _dt_yoy.date.today().month
                cur_season = (
                    "winter" if m in (12, 1, 2) else
                    "spring" if m in (3, 4, 5)  else
                    "summer" if m in (6, 7, 8)  else
                    "autumn"
                )
                cur_year  = _dt_yoy.date.today().year
                prev_year = cur_year - 1
                cur_key   = f"{cur_year}-{cur_season}"
                prev_key  = f"{prev_year}-{cur_season}"
                cop_cur  = bkt_ref.seasonal_avgs.get(cur_key)
                cop_prev = bkt_ref.seasonal_avgs.get(prev_key)
                if cop_cur and cop_prev and cop_prev > 0:
                    yoy_drop = (cop_prev - cop_cur) / cop_prev * 100
                    if yoy_drop > 8:    # > 8% jaar-op-jaar terugval is significant
                        yoy_detected = True
                        yoy_drop_pct = round(yoy_drop, 1)
                        yoy_advice = (
                            f"Warmtepomp COP in {cur_season} {cur_year} is "
                            f"{yoy_drop_pct:.0f}% lager dan {cur_season} {prev_year} "
                            f"({cop_cur:.2f} vs {cop_prev:.2f}) bij {outdoor_c:.0f}°C. "
                            "Dit kan duiden op koudemiddelverlies of fouling van de "
                            "warmtewisselaar. Overweeg een onderhoudsinspectie."
                        )
                        _LOGGER.warning(
                            "HeatPumpCOP: jaar-op-jaar degradatie gedetecteerd — "
                            "%s %.0f°C: %.2f→%.2f (%.1f%% daling)",
                            cur_season, outdoor_c, cop_prev, cop_cur, yoy_drop,
                        )
        # Combineer korte- en langetermijn-degradatieadvies
        if yoy_detected and not degradation_detected:
            degradation_detected = True
            degradation_pct      = yoy_drop_pct
            degradation_advice   = yoy_advice
        elif yoy_detected and degradation_detected:
            degradation_advice += " | " + yoy_advice

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
            degradation_detected = degradation_detected,
            degradation_pct      = degradation_pct,
            degradation_advice   = degradation_advice,
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
                    "recent_cops": v.recent_cops[-30:] if v.recent_cops else [],
                    "seasonal_avgs": v.seasonal_avgs if v.seasonal_avgs else {},
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
            bkt.recent_cops    = v.get("recent_cops", [])
            bkt.seasonal_avgs  = v.get("seasonal_avgs", {})
            try:
                self._buckets[float(k_str)] = bkt
            except ValueError:
                pass
