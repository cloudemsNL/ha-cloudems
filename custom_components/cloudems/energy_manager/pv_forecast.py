"""
CloudEMS PV Forecasting — v1.4.2

Two-layer forecast engine:
  Layer 1: Statistical model using historically learned hourly yield curves
           per inverter. No internet required.
  Layer 2: Open-Meteo weather API (free, no key) for irradiance forecast.
           Used when available to weight the statistical model.

Self-learning orientation / azimuth / tilt:
  - CloudEMS measures actual peak irradiance times throughout the day.
  - The hour with the highest yield → solar noon → azimuth is derived.
  - Morning-heavy vs afternoon-heavy yield → east vs west bias.
  - After ~30 clear days (1800 minutes) the orientation estimate becomes "confident".
  - Users can fill in values manually; tooltip says "leave blank to self-learn".

Changelog (v1.4.3):
  - FIX: clear_sky_samples reset to 0 after every HA restart because PVForecast
         had no periodic auto-save — only saved at async_shutdown (clean stop only).
         Added dirty-flag + _SAVE_INTERVAL_S=120s auto-save inside async_update,
         identical to the pattern used in solar_learner.py. Data now survives crashes.
         for a much more reliable azimuth/tilt estimate before "confident" is set.
  - CHG: Log progress bar capped at 30 chars (was unbounded, causing 1800-char lines).
  - CHG: Log frequency changed from every 10 to every 30 samples.

Changelog (v1.4.1):
  - FIX: avg_az_om / _azom UnboundLocalError (was only assigned inside if-block)
  - FIX: weather cache key mismatch — get_forecast used "%Y-%m-%dT%H:00" but
         update_weather_calibration used "%Y-%m-%d %H:00" → unified to ISO format
  - FIX: division-by-zero guards in blending logic (max_irr, peak_wp, len checks)
  - FIX: _learn_orientation could raise on empty hf dict passed to max()
  - FIX: _calib_factor / _calib_samples used fragile getattr pattern on dataclass
  - ADD: try/except wrapper around async_refresh_weather body
  - ADD: try/except wrapper around async_update body
  - ADD: try/except wrapper around _learn_orientation body
  - ADD: None-safety on all effective_tilt / effective_azimuth accesses
  - ADD: guard against self._profiles being empty in get_total_forecast_* methods

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

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

# Minimum samples before orientation is "confident".
# Each sample = one clear-sky *minute* (sampled once per minute).
# 30 hours × 60 min = 1800 samples → confirmed after ~5 sunny days (conservative).
# This ensures the learned azimuth/tilt is based on enough diverse sun positions.
MIN_ORIENTATION_SAMPLES = 1800

# Minimum yield fraction (power/peak) to count as a learning sample.
# 0.10 = 10% of peak — filters night/standby but includes overcast mornings.
CLEAR_SKY_MIN_FRAC = 0.10

# Hours considered "morning" and "afternoon" for azimuth heuristic
MORNING_HOURS   = list(range(6, 11))
AFTERNOON_HOURS = list(range(14, 19))

# Unified weather-cache key format (ISO 8601) — used everywhere in this file
_WEATHER_KEY_FMT = "%Y-%m-%dT%H:00"

# Safe defaults for tilt/azimuth when no profile data is available yet
_DEFAULT_TILT: float = 35.0   # degrees — typical Dutch roof
_DEFAULT_AZOM: float = 0.0    # Open-Meteo: 0 = south, -90 = east, +90 = west


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
    _prev_power_w:   float = field(default=0.0, repr=False, compare=False)
    _peak_wp:        float = field(default=0.0, repr=False, compare=False)

    # Calibration — stored as proper fields (no getattr hacks)
    _calib_factor:   Optional[float] = field(default=None, repr=False, compare=False)
    _calib_samples:  int             = field(default=0,    repr=False, compare=False)

    @property
    def effective_azimuth(self) -> Optional[float]:
        if self.azimuth_deg is not None:
            return float(self.azimuth_deg)
        if self.learned_azimuth is not None:
            return float(self.learned_azimuth)
        return None

    @property
    def effective_tilt(self) -> Optional[float]:
        if self.tilt_deg is not None:
            return float(self.tilt_deg)
        if self.learned_tilt is not None:
            return float(self.learned_tilt)
        return None


@dataclass
@dataclass
class HourForecast:
    hour: int           # 0-23
    forecast_w: float
    confidence: float   # 0-1
    low_w: float = 0.0   # pessimistisch (p25)
    high_w: float = 0.0  # optimistisch (p75)


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
        self._lat      = float(latitude)
        self._lon      = float(longitude)
        self._session  = session
        self._store    = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._profiles: dict[str, InverterOrientation] = {}
        self._configs  = inverter_configs or []
        self._weather_cache: dict = {}
        self._weather_ts:   float = 0.0
        self._dirty:        bool  = False
        self._last_save:    float = 0.0
        self._backup             = None  # LearningBackup — injected via async_setup

    # Save interval: write to HA Store at most every 2 minutes when data changed.
    _SAVE_INTERVAL_S: int = 120
    _BACKUP_KEY: str      = "pv_forecast"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self, backup=None) -> None:
        self._backup = backup
        saved: dict = await self._store.async_load() or {}

        # Fallback naar backup als Store leeg is
        if not saved and backup is not None:
            fallback = await backup.async_read(self._BACKUP_KEY)
            if fallback:
                saved = fallback
                _LOGGER.warning(
                    "CloudEMS PVForecast: HA Store leeg — data hersteld uit backup (%d profielen)",
                    len(saved),
                )
        for cfg in self._configs:
            eid = cfg.get("entity_id", "")
            if not eid:
                continue
            p = self._profiles.setdefault(eid, InverterOrientation(
                inverter_id=eid,
                label=cfg.get("label", eid),
                azimuth_deg=cfg.get("azimuth_deg"),
                tilt_deg=cfg.get("tilt_deg"),
            ))
            stored = saved.get(eid, {})
            p.learned_azimuth          = stored.get("learned_azimuth")
            p.learned_tilt             = stored.get("learned_tilt")
            p.orientation_confident    = bool(stored.get("orientation_confident", False))
            p.clear_sky_samples        = int(stored.get("clear_sky_samples", 0))
            p.hourly_yield_fraction    = dict(stored.get("hourly_yield_fraction", {}))
            p._peak_wp                 = float(stored.get("peak_wp", 0.0))
            p._calib_factor            = stored.get("calib_factor")  # None if absent
            p._calib_samples           = int(stored.get("calib_samples", 0))
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
                "calib_factor":          p._calib_factor,
                "calib_samples":         p._calib_samples,
            }
        await self._store.async_save(data)
        self._dirty     = False
        self._last_save = time.time()
        _LOGGER.debug("CloudEMS PVForecast: %d profielen opgeslagen", len(data))
        if self._backup is not None:
            await self._backup.async_write(self._BACKUP_KEY, data)

    # ── Update (called every 10 s from coordinator) ───────────────────────────

    async def async_update(self, inverter_id: str, power_w: float, peak_wp: float) -> None:
        try:
            p = self._profiles.get(inverter_id)
            if p is None:
                return

            peak_wp = float(peak_wp)
            power_w = float(power_w)

            if peak_wp > p._peak_wp:
                p._peak_wp = peak_wp

            now      = dt_util.now()
            hour_key = str(now.hour)
            frac     = (power_w / peak_wp) if peak_wp > 10 else 0.0

            # Exponential moving average per hour.
            # Use a faster alpha while we have little data so the first clear days
            # are learned quickly; slow down once the profile has stabilised.
            n_hours = len(p.hourly_yield_fraction)
            alpha   = 0.30 if n_hours < 8 else (0.15 if n_hours < 16 else 0.05)
            prev = float(p.hourly_yield_fraction.get(hour_key, frac))
            p.hourly_yield_fraction[hour_key] = round(prev * (1.0 - alpha) + frac * alpha, 4)

            # Orientation learning — at most ONCE per minute, only when sun is up.
            # CLEAR_SKY_MIN_FRAC filters out night/standby readings.
            # Per-minute sampling means 1 sunny hour = 60 samples, visible progress
            # every minute in the dashboard (1800 samples = 30 hours = confident).
            cur_min = now.hour * 60 + now.minute
            last_learn_min = getattr(p, "_last_learn_min", -1)
            if frac > CLEAR_SKY_MIN_FRAC and cur_min != last_learn_min:
                p._last_learn_min = cur_min  # type: ignore[attr-defined]
                await self._learn_orientation(p, power_w, peak_wp)

            p._prev_power_w = power_w
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS PVForecast: async_update failed for %s: %s", inverter_id, exc)

        # Periodiek opslaan zodra er iets veranderd is (max elke 2 min)
        if self._dirty and (time.time() - self._last_save) >= self._SAVE_INTERVAL_S:
            await self.async_save()

    # ── Orientation learning ──────────────────────────────────────────────────

    async def _learn_orientation(
        self, p: InverterOrientation, power_w: float, peak_wp: float
    ) -> None:
        """Infer azimuth and tilt from daily yield shape on clear-sky hours."""
        try:
            if peak_wp < 10:
                return

            hf = p.hourly_yield_fraction
            if not hf:
                return

            # Solar noon = hour of maximum yield fraction seen so far.
            # Even with a single hour of data we can make a provisional estimate —
            # it will refine itself as more hours accumulate.
            best_hour = max(hf, key=lambda h: hf[h])
            solar_noon = int(best_hour)

            # Azimuth: noon at 12 UTC ≈ south (180°), each hour shifts 15°
            noon_offset = solar_noon - 12
            learned_az  = max(0.0, min(360.0, 180.0 + noon_offset * 15.0))

            # Tilt: peak yield fraction → tilt angle (rough linear mapping)
            hf_values    = list(hf.values())
            peak_frac    = max(hf_values)
            learned_tilt = round(min(90.0, max(0.0, peak_frac * 90.0)), 1)

            p.learned_azimuth = round(learned_az, 1)
            p.learned_tilt    = learned_tilt
            p.clear_sky_samples += 1
            self._dirty = True

            just_confident = False
            if p.clear_sky_samples >= MIN_ORIENTATION_SAMPLES and not p.orientation_confident:
                p.orientation_confident = True
                just_confident = True

            # Log on first sample, every 30 after that, and at confirmation
            # Progress bar is capped at 30 chars for readability
            BAR_LEN = 30
            filled = min(round(p.clear_sky_samples / MIN_ORIENTATION_SAMPLES * BAR_LEN), BAR_LEN)
            bar = '#' * filled + '.' * (BAR_LEN - filled)
            n_hours = len(hf)
            if just_confident:
                _LOGGER.info(
                    "CloudEMS PVForecast [%s]: ✅ oriëntatie BEVESTIGD — "
                    "azimuth=%.0f° tilt=%.0f° (na %d minuten zon)",
                    p.label, learned_az, learned_tilt, p.clear_sky_samples,
                )
            elif p.clear_sky_samples == 1 or p.clear_sky_samples % 30 == 0:
                provisional = " (voorlopig)" if n_hours < 4 else ""
                _LOGGER.info(
                    "CloudEMS PVForecast [%s]: leren %d/%d (%.0f%%) [%s] — "
                    "azimuth=%.0f°%s tilt=%.0f° (%d uur data)",
                    p.label, p.clear_sky_samples, MIN_ORIENTATION_SAMPLES,
                    p.clear_sky_samples / MIN_ORIENTATION_SAMPLES * 100,
                    bar, learned_az, provisional, learned_tilt, n_hours,
                )

        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS PVForecast: _learn_orientation failed for %s: %s", p.label, exc)

    # ── Forecast ──────────────────────────────────────────────────────────────

    async def async_refresh_weather(self) -> None:
        """Fetch Open-Meteo irradiance forecast (hourly, 2 days). No API key needed."""
        if not self._session:
            return
        if time.time() - self._weather_ts < 3600:
            return   # Cache for 1 hour

        try:
            # Safe defaults — always set BEFORE any conditional so they are
            # never unbound regardless of which code paths are taken.
            _tilt: float = _DEFAULT_TILT
            _azom: float = _DEFAULT_AZOM

            profiles_with_data = [
                p for p in self._profiles.values()
                if p.effective_tilt is not None and p.effective_azimuth is not None
            ]
            if profiles_with_data:
                tilts = [p.effective_tilt or _DEFAULT_TILT for p in profiles_with_data]
                azims = [p.effective_azimuth or 180.0     for p in profiles_with_data]
                _tilt = sum(tilts) / len(tilts)
                _az   = sum(azims) / len(azims)
                # Convert HA azimuth (0=N, 90=E, 180=S, 270=W)
                # to Open-Meteo convention (-180…+180, 0=S, -90=E, +90=W)
                _azom = _az - 180.0

            # Clamp to valid Open-Meteo ranges
            _tilt = max(0.0, min(90.0,  _tilt))
            _azom = max(-180.0, min(180.0, _azom))

            url = (
                f"{OPEN_METEO_URL_BASE}"
                f"&latitude={self._lat}&longitude={self._lon}"
                f"&hourly=global_tilted_irradiance,direct_radiation,shortwave_radiation"
                f"&tilt={_tilt:.0f}&azimuth={_azom:.0f}"
            )

            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data  = await r.json()
                    hours = data.get("hourly", {}).get("time", [])
                    # Cascade: global_tilted → direct → shortwave
                    rad_gti = data.get("hourly", {}).get("global_tilted_irradiance", [])
                    rad_dir = data.get("hourly", {}).get("direct_radiation", [])
                    rad_sw  = data.get("hourly", {}).get("shortwave_radiation", [])
                    irradiances = []
                    for i in range(len(hours)):
                        gti = rad_gti[i] if i < len(rad_gti) else None
                        dr  = rad_dir[i] if i < len(rad_dir) else None
                        sw  = rad_sw[i]  if i < len(rad_sw)  else None
                        # Use best available non-null value
                        irradiances.append(
                            gti if gti is not None else (dr if dr is not None else (sw or 0))
                        )
                    self._weather_cache = dict(zip(hours, irradiances))
                    self._weather_ts    = time.time()
                    _LOGGER.debug(
                        "CloudEMS PVForecast: weather updated (%d hours, tilt=%.0f° az=%.0f°)",
                        len(hours), _tilt, _azom + 180.0
                    )
                else:
                    _LOGGER.debug(
                        "CloudEMS PVForecast: weather fetch returned HTTP %d", r.status
                    )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("CloudEMS PVForecast: weather fetch failed: %s", exc)

    # ── Internal forecast helper ───────────────────────────────────────────────

    @staticmethod
    def _blend(stat_frac: float, irradiance: Optional[float]) -> tuple[float, float]:
        """
        Blend statistical fraction with weather irradiance.
        Returns (blended_fraction, confidence).
        """
        if irradiance is None:
            return stat_frac, 0.7

        max_irr  = 1000.0
        irr_frac = min(irradiance / max_irr, 1.0) if max_irr > 0 else 0.0
        blended  = stat_frac * 0.4 + irr_frac * 0.6
        return blended, 0.9

    def _build_forecast(
        self, inverter_id: str, start: datetime, confidence_no_weather: float
    ) -> list[HourForecast]:
        """Generic forecast builder for any 24-hour window starting at `start`."""
        p = self._profiles.get(inverter_id)
        if p is None or p._peak_wp < 10:
            return []

        forecasts: list[HourForecast] = []
        for h in range(24):
            target    = start + timedelta(hours=h)
            hk        = str(target.hour)
            stat_frac = float(p.hourly_yield_fraction.get(hk, 0.0))

            weather_key = target.strftime(_WEATHER_KEY_FMT)
            irradiance  = self._weather_cache.get(weather_key)

            blended, conf = self._blend(stat_frac, irradiance)
            if irradiance is None:
                conf = confidence_no_weather

            forecast_w = round(max(0.0, p._peak_wp * blended), 1)
            # Confidence interval: spread gebaseerd op confidence en historische spread
            # Lage confidence → bredere band; hoge confidence → smalle band
            spread_factor = max(0.15, 1.0 - conf) * 0.8  # 8-80% spread
            low_w  = round(max(0.0, forecast_w * (1.0 - spread_factor)), 1)
            high_w = round(forecast_w * (1.0 + spread_factor * 0.6), 1)  # upside kleiner dan downside
            forecasts.append(HourForecast(
                hour=target.hour,
                forecast_w=forecast_w,
                confidence=conf,
                low_w=low_w,
                high_w=high_w,
            ))

        return forecasts

    def get_forecast(self, inverter_id: str) -> list[HourForecast]:
        """Return 24-hour forecast for one inverter starting from the current hour."""
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        return self._build_forecast(inverter_id, now, confidence_no_weather=0.7)

    def get_forecast_tomorrow(self, inverter_id: str) -> list[HourForecast]:
        """Return 24-hour forecast for tomorrow for one inverter."""
        tomorrow = (
            dt_util.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        return self._build_forecast(inverter_id, tomorrow, confidence_no_weather=0.6)

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
            "samples_needed":          MIN_ORIENTATION_SAMPLES,
        }

    def get_all_profiles(self) -> list[dict]:
        return [self.get_profile_summary(eid) for eid in self._profiles]

    # ── Weather calibration ───────────────────────────────────────────────────

    def update_weather_calibration(self, inverter_id: str, actual_w: float) -> None:
        """
        Call each coordinator tick when irradiance data is available.
        Compares actual inverter output to what the irradiance model predicts
        and adjusts a per-installation calibration factor.
        """
        try:
            p = self._profiles.get(inverter_id)
            if p is None or p._peak_wp < 10:
                return

            now         = dt_util.now()
            weather_key = now.strftime(_WEATHER_KEY_FMT)  # unified key format
            irradiance  = self._weather_cache.get(weather_key)
            if irradiance is None or irradiance < 50:
                return

            max_irr      = 1000.0
            expected_frac = min(irradiance / max_irr, 1.0) if max_irr > 0 else 0.0
            expected_w    = expected_frac * p._peak_wp
            if expected_w < 10:
                return

            ratio = actual_w / expected_w
            # Clamp to plausible range (avoid dust/shadow outliers)
            if not (0.05 <= ratio <= 1.5):
                return

            # EMA into per-profile calibration factor
            if p._calib_factor is None:
                p._calib_factor = ratio
            else:
                p._calib_factor = 0.9 * p._calib_factor + 0.1 * ratio
            p._calib_samples += 1
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CloudEMS PVForecast: update_weather_calibration failed for %s: %s",
                inverter_id, exc
            )

    def get_calibration_summary(self) -> dict:
        """Return calibration info for all inverters."""
        invs = []
        for eid, p in self._profiles.items():
            factor  = p._calib_factor
            samples = p._calib_samples
            invs.append({
                "inverter_id":     eid,
                "label":           p.label,
                "calib_factor":    round(factor, 3) if factor is not None else None,
                "calib_samples":   samples,
                "calib_confident": samples >= 30,
                "calib_pct":       round(min(100.0, samples / 30 * 100), 0),
            })
        global_samples = sum(p._calib_samples for p in self._profiles.values())
        return {
            "inverters":        invs,
            "global_confident": global_samples >= 30,
            "global_samples":   global_samples,
        }
