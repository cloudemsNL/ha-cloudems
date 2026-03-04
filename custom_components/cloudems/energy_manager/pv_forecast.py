"""
CloudEMS PV Forecasting — v1.4.0

Two-layer forecast engine:
  Layer 1: Statistical model using historically learned hourly yield curves
           per inverter. No internet required.
  Layer 2: Open-Meteo weather API (free, no key) for irradiance forecast.
           Used when available to weight the statistical model.

Self-learning orientation / azimuth / tilt:
  - CloudEMS measures actual peak irradiance times throughout the day.
  - The hour with the highest yield → solar noon → azimuth is derived.
  - Morning-heavy vs afternoon-heavy yield → east vs west bias.
  - After ~30 clear days the orientation estimate becomes "confident".
  - Users can fill in values manually; tooltip says "leave blank to self-learn".

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_pv_forecast_v1"
STORAGE_VERSION = 1

# v1.15.0: Use global_tilted_irradiance (panel-angle-corrected) as primary source
# Fallback cascade: global_tilted → direct_radiation → shortwave_radiation
OPEN_METEO_URL_BASE = (
    "https://api.open-meteo.com/v1/forecast"
    "?forecast_days=2&timezone=auto"
)
OPEN_METEO_URL = OPEN_METEO_URL_BASE  # legacy, unused — URL built dynamically now

# Minimum samples before orientation is "confident"
MIN_ORIENTATION_SAMPLES = 30

# Hours considered "morning" and "afternoon" for azimuth heuristic
MORNING_HOURS   = list(range(6, 11))
AFTERNOON_HOURS = list(range(14, 19))


@dataclass
class InverterOrientation:
    """Learned or manually set orientation for one inverter."""
    inverter_id: str
    label:        str         = ""

    # Manual (overrides learning when set)
    azimuth_deg:  Optional[float] = None   # 0=N 90=E 180=S 270=W
    tilt_deg:     Optional[float] = None   # 0=horizontal 90=vertical

    # Learned
    learned_azimuth:  Optional[float] = None
    learned_tilt:     Optional[float] = None
    orientation_confident: bool       = False
    clear_sky_samples:     int        = 0

    # Per-hour average yield fraction (0-1 relative to peak Wp)
    hourly_yield_fraction: dict = field(default_factory=dict)  # {"8": 0.12, ...}

    # Runtime — not persisted
    _prev_power_w: float = field(default=0.0, repr=False, compare=False)
    _peak_wp:      float = field(default=0.0, repr=False, compare=False)

    @property
    def effective_azimuth(self) -> Optional[float]:
        if self.azimuth_deg is not None:
            return self.azimuth_deg
        return self.learned_azimuth

    @property
    def effective_tilt(self) -> Optional[float]:
        if self.tilt_deg is not None:
            return self.tilt_deg
        return self.learned_tilt


@dataclass
class HourForecast:
    hour: int           # 0-23
    forecast_w: float
    confidence: float   # 0-1


class PVForecast:
    """
    Manages PV forecasting and orientation learning for all inverters.

    Usage in coordinator:
        fc = PVForecast(hass, inverter_configs, lat, lon)
        await fc.async_setup()
        await fc.async_update(inverter_id, power_w, peak_wp)
        forecast = fc.get_forecast(inverter_id)
        total_forecast = fc.get_total_forecast_today_kwh()
    """

    def __init__(
        self,
        hass: HomeAssistant,
        inverter_configs: list[dict],
        latitude:  float = 52.1,
        longitude: float = 5.3,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._hass     = hass
        self._lat      = latitude
        self._lon      = longitude
        self._session  = session
        self._store    = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._profiles: dict[str, InverterOrientation] = {}
        self._configs  = inverter_configs
        self._weather_cache: dict = {}
        self._weather_ts:   float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for cfg in self._configs:
            eid = cfg["entity_id"]
            p   = self._profiles.setdefault(eid, InverterOrientation(
                inverter_id=eid,
                label=cfg.get("label", eid),
                azimuth_deg=cfg.get("azimuth_deg"),
                tilt_deg=cfg.get("tilt_deg"),
            ))
            stored = saved.get(eid, {})
            p.learned_azimuth          = stored.get("learned_azimuth")
            p.learned_tilt             = stored.get("learned_tilt")
            p.orientation_confident    = stored.get("orientation_confident", False)
            p.clear_sky_samples        = stored.get("clear_sky_samples", 0)
            p.hourly_yield_fraction    = stored.get("hourly_yield_fraction", {})
            p._peak_wp                 = stored.get("peak_wp", 0.0)
        _LOGGER.info("CloudEMS PVForecast: setup for %d inverters", len(self._profiles))

    async def async_save(self) -> None:
        data = {}
        for eid, p in self._profiles.items():
            data[eid] = {
                "learned_azimuth":       p.learned_azimuth,
                "learned_tilt":          p.learned_tilt,
                "orientation_confident": p.orientation_confident,
                "clear_sky_samples":     p.clear_sky_samples,
                "hourly_yield_fraction": p.hourly_yield_fraction,
                "peak_wp":               p._peak_wp,
            }
        await self._store.async_save(data)

    # ── Update (called every 10 s from coordinator) ───────────────────────────

    async def async_update(self, inverter_id: str, power_w: float, peak_wp: float) -> None:
        p = self._profiles.get(inverter_id)
        if p is None:
            return

        if peak_wp > p._peak_wp:
            p._peak_wp = peak_wp

        hour_key = str(datetime.now(timezone.utc).hour)
        frac     = (power_w / peak_wp) if peak_wp > 10 else 0.0

        # Exponential moving average per hour
        prev = float(p.hourly_yield_fraction.get(hour_key, frac))
        p.hourly_yield_fraction[hour_key] = round(prev * 0.95 + frac * 0.05, 4)

        # Orientation learning — run once per hour when power > 5% of peak
        if frac > 0.05:
            await self._learn_orientation(p, power_w, peak_wp)

        p._prev_power_w = power_w

    # ── Orientation learning ──────────────────────────────────────────────────

    async def _learn_orientation(
        self, p: InverterOrientation, power_w: float, peak_wp: float
    ) -> None:
        """Infer azimuth and tilt from daily yield shape."""
        if peak_wp < 100:
            return

        hour = datetime.now(timezone.utc).hour
        hf   = p.hourly_yield_fraction

        if len(hf) < 8:
            return  # Not enough data yet

        # Solar noon = hour of maximum yield
        best_hour = max(hf, key=lambda h: hf[h], default=None)
        if best_hour is None:
            return
        solar_noon = int(best_hour)

        # Azimuth: noon at 12 UTC ≈ south (180°), each hour offset shifts 15°
        # This is a rough heuristic; good enough without a full ephemeris lib
        noon_offset  = solar_noon - 12          # -4 → east, +4 → west
        learned_az   = 180.0 + noon_offset * 15.0
        learned_az   = max(0.0, min(360.0, learned_az))

        # Tilt: estimated from peak yield fraction relative to horizontal
        # A flat roof (0°) would show broader, lower peak; steep (90°) narrow+high
        peak_frac = max(hf.values()) if hf else 0.0
        learned_tilt = round(min(90.0, max(0.0, peak_frac * 90.0)), 1)

        p.learned_azimuth = round(learned_az, 1)
        p.learned_tilt    = learned_tilt
        p.clear_sky_samples += 1

        if p.clear_sky_samples >= MIN_ORIENTATION_SAMPLES:
            p.orientation_confident = True

        if p.clear_sky_samples % 10 == 0:
            _LOGGER.info(
                "CloudEMS PVForecast [%s]: azimuth=%.0f° tilt=%.0f° (samples=%d confident=%s)",
                p.label, learned_az, learned_tilt, p.clear_sky_samples, p.orientation_confident
            )

    # ── Forecast ──────────────────────────────────────────────────────────────

    async def async_refresh_weather(self) -> None:
        """Fetch Open-Meteo irradiance forecast (hourly, 2 days). No API key needed."""
        if not self._session:
            return
        if time.time() - self._weather_ts < 3600:
            return   # Cache for 1 hour
        # v1.15.0: prefer global_tilted_irradiance with learned orientation
        # Average tilt/azimuth across all configured inverters
        avg_tilt = 35.0
        avg_az   = 180.0
        profiles_with_data = [
            p for p in self._profiles.values()
            if p.effective_tilt is not None and p.effective_azimuth is not None
        ]
        if profiles_with_data:
            avg_tilt = sum(p.effective_tilt or 35.0 for p in profiles_with_data) / len(profiles_with_data)
            avg_az   = sum(p.effective_azimuth or 180.0 for p in profiles_with_data) / len(profiles_with_data)
            # Convert HA azimuth (0=N,90=E,180=S,270=W) to Open-Meteo (-180…180, 0=S)
            avg_az_om = avg_az - 180.0  # 0=S, -90=E, +90=W

        url = (
            f"{OPEN_METEO_URL_BASE}"
            f"&latitude={self._lat}&longitude={self._lon}"
            f"&hourly=global_tilted_irradiance,direct_radiation,shortwave_radiation"
            f"&tilt={avg_tilt:.0f}&azimuth={avg_az_om:.0f}"
        )
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data  = await r.json()
                    hours = data.get("hourly", {}).get("time", [])
                    # Cascade: global_tilted → direct → shortwave
                    rad_gti   = data.get("hourly", {}).get("global_tilted_irradiance", [])
                    rad_dir   = data.get("hourly", {}).get("direct_radiation", [])
                    rad_sw    = data.get("hourly", {}).get("shortwave_radiation", [])
                    irradiances = []
                    for i in range(len(hours)):
                        gti = rad_gti[i] if i < len(rad_gti) else None
                        dr  = rad_dir[i] if i < len(rad_dir) else None
                        sw  = rad_sw[i]  if i < len(rad_sw)  else None
                        # Use best available, non-null value
                        irradiances.append(gti if gti is not None else (dr if dr is not None else (sw or 0)))
                    self._weather_cache = dict(zip(hours, irradiances))
                    self._weather_ts    = time.time()
                    _LOGGER.debug(
                        "CloudEMS PVForecast: weather updated (%d hours, tilt=%.0f° az=%.0f°)",
                        len(hours), avg_tilt, avg_az
                    )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("CloudEMS PVForecast: weather fetch failed: %s", exc)

    def get_forecast(self, inverter_id: str) -> list[HourForecast]:
        """Return 24-hour forecast for one inverter."""
        p = self._profiles.get(inverter_id)
        if p is None or p._peak_wp < 10:
            return []

        now      = datetime.now(timezone.utc)
        forecasts: list[HourForecast] = []

        for h in range(24):
            target  = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h)
            hk      = str(target.hour)
            stat_frac = float(p.hourly_yield_fraction.get(hk, 0.0))

            # Weather weighting
            weather_key   = target.strftime("%Y-%m-%dT%H:00")
            irradiance    = self._weather_cache.get(weather_key)
            confidence    = 0.7 if irradiance is None else 0.9

            if irradiance is not None:
                # Blend statistical shape with weather irradiance
                max_irr = 1000.0   # W/m² clear sky reference
                irr_frac = min(irradiance / max_irr, 1.0) if max_irr else 0.0
                blended  = stat_frac * 0.4 + irr_frac * 0.6
            else:
                blended = stat_frac

            forecast_w = round(p._peak_wp * blended, 1)
            forecasts.append(HourForecast(hour=target.hour, forecast_w=forecast_w, confidence=confidence))

        return forecasts

    def get_forecast_tomorrow(self, inverter_id: str) -> list[HourForecast]:
        """Return 24-hour forecast for tomorrow for one inverter."""
        p = self._profiles.get(inverter_id)
        if p is None or p._peak_wp < 10:
            return []

        tomorrow = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        forecasts: list[HourForecast] = []

        for h in range(24):
            target   = tomorrow + timedelta(hours=h)
            hk       = str(target.hour)
            stat_frac = float(p.hourly_yield_fraction.get(hk, 0.0))

            weather_key = target.strftime("%Y-%m-%dT%H:00")
            irradiance  = self._weather_cache.get(weather_key)
            confidence  = 0.6 if irradiance is None else 0.85

            if irradiance is not None:
                max_irr  = 1000.0
                irr_frac = min(irradiance / max_irr, 1.0) if max_irr else 0.0
                blended  = stat_frac * 0.4 + irr_frac * 0.6
            else:
                blended = stat_frac

            forecast_w = round(p._peak_wp * blended, 1)
            forecasts.append(HourForecast(hour=target.hour, forecast_w=forecast_w, confidence=confidence))

        return forecasts

    def get_total_forecast_today_kwh(self) -> float:
        """Sum forecast for all inverters for today in kWh."""
        total = 0.0
        for eid in self._profiles:
            for hf in self.get_forecast(eid):
                total += hf.forecast_w / 1000.0
        return round(total, 2)

    def get_total_forecast_tomorrow_kwh(self) -> float:
        """Sum forecast for all inverters for tomorrow in kWh."""
        total = 0.0
        for eid in self._profiles:
            for hf in self.get_forecast_tomorrow(eid):
                total += hf.forecast_w / 1000.0
        return round(total, 2)

    def get_profile_summary(self, inverter_id: str) -> dict:
        p = self._profiles.get(inverter_id)
        if p is None:
            return {}
        return {
            "inverter_id":             p.inverter_id,
            "label":                   p.label,
            "azimuth_deg":             p.effective_azimuth,
            "tilt_deg":                p.effective_tilt,
            "azimuth_manual":          p.azimuth_deg,
            "tilt_manual":             p.tilt_deg,
            "learned_azimuth":         p.learned_azimuth,
            "learned_tilt":            p.learned_tilt,
            "orientation_confident":   p.orientation_confident,
            "clear_sky_samples":       p.clear_sky_samples,
            "peak_wp":                 p._peak_wp,
            "samples_needed":          max(0, MIN_ORIENTATION_SAMPLES - p.clear_sky_samples),
        }

    def get_all_profiles(self) -> list[dict]:
        return [self.get_profile_summary(eid) for eid in self._profiles]

    # ── Weather calibration ───────────────────────────────────────────────────
    # Learns the ratio actual_output / open_meteo_expected for each irradiance
    # bucket. After 30+ sunny days this self-calibrates the forecast model to the
    # specific installation (panel angle, local shading, panel type).

    def update_weather_calibration(self, inverter_id: str, actual_w: float) -> None:
        """
        Call each coordinator tick when irradiance data is available.
        Compares actual inverter output to what the irradiance model predicts
        and adjusts a per-installation calibration factor.
        """
        p = self._profiles.get(inverter_id)
        if p is None:
            return
        if p._peak_wp < 10:
            return
        now = datetime.now(timezone.utc)
        weather_key = now.strftime("%Y-%m-%d %H:00")
        irradiance  = self._weather_cache.get(weather_key)
        if irradiance is None or irradiance < 50:
            return
        # Maximum possible irradiance (1000 W/m² on a perfect clear day)
        max_irr = 1000.0
        expected_frac = min(irradiance / max_irr, 1.0)
        expected_w    = expected_frac * p._peak_wp
        if expected_w < 10:
            return
        ratio = actual_w / expected_w
        # Clamp to plausible range (avoid dust/shadow outliers)
        if not (0.05 <= ratio <= 1.5):
            return
        # EMA into per-profile calibration factor
        cur_factor = getattr(p, "_calib_factor", None)
        if cur_factor is None:
            p._calib_factor = ratio
        else:
            p._calib_factor = 0.9 * cur_factor + 0.1 * ratio
        p._calib_samples = getattr(p, "_calib_samples", 0) + 1

    def get_calibration_summary(self) -> dict:
        """Return calibration info for all inverters."""
        invs = []
        for eid, p in self._profiles.items():
            factor  = getattr(p, "_calib_factor", None)
            samples = getattr(p, "_calib_samples", 0)
            invs.append({
                "inverter_id":   eid,
                "label":         p.label,
                "calib_factor":  round(factor, 3) if factor else None,
                "calib_samples": samples,
                "calib_confident": samples >= 30,
                "calib_pct":     round(min(100, samples / 30 * 100), 0),
            })
        global_samples = sum(getattr(p, "_calib_samples", 0) for p in self._profiles.values())
        return {
            "inverters": invs,
            "global_confident": global_samples >= 30,
            "global_samples":   global_samples,
        }
