# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS PV Forecasting — v1.5.0

Three-layer forecast engine:
  Layer 1: Statistical model using historically learned hourly yield curves
           per inverter. No internet required.
  Layer 2: Open-Meteo weather API (free, no key) for irradiance forecast.
           Used when available to weight the statistical model.
  Layer 3: Forecast.Solar API (free, no key, rate-limited to 12 req/hour).
           Direct watt-per-hour forecast based on exact panel config.
           When available, overrides layers 1+2 with high confidence.
           Cache: 2 hours. Falls back to layers 1+2 on error or rate limit.

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

# v1.5.0: Forecast.Solar API — gratis, geen API key, rate limit ~12 req/uur
# URL: /estimate/:lat/:lon/:dec/:az/:kwp
# dec = tilt (0-90), az = azimuth Forecast.Solar conventie (-180…+180, 0=S)
FORECAST_SOLAR_URL = "https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}"
FORECAST_SOLAR_CACHE_S = 7200  # 2 uur cache (rate limit: ~12 req/uur)

# Minimum samples before orientation is "confident".
# Each sample = one clear-sky *minute* (sampled once per minute).
# 60 hours × 60 min = 3600 samples → confirmed after ~10 sunny days.
# Verhoogd van 1800 naar 3600: mistige/bewolkte dagen verstoren het leren doordat
# diffuus licht geen duidelijke azimut-informatie geeft. Meer samples = robuuster.
MIN_ORIENTATION_SAMPLES = 3600

# Oriëntatie-drift detectie
# Als de geleerde azimuth consistent >DRIFT_AZ_THRESHOLD° afwijkt van
# de lopende schatting (over DRIFT_WINDOW_SAMPLES samples), neem dan aan
# dat de panelen zijn verplaatst/gedraaid en reset het profiel.
DRIFT_AZ_THRESHOLD   = 25.0   # graden — gevoelig genoeg voor 1 dakvlak verschil
DRIFT_TILT_THRESHOLD = 15.0   # graden
DRIFT_WINDOW_SAMPLES = 10     # aantal opeenvolgende afwijkende samples

# Als de azimuth-schatting sterk afwijkt van het huidige profiel,
# pas dan een hogere decay toe op het hourly_yield_fraction profiel
# zodat verkeerde historische data sneller weg-EWMA't.
FAST_CORRECT_AZ_THRESHOLD = 20.0  # graden — begin versneld corrigeren
FAST_CORRECT_ALPHA_BOOST  = 3.0   # multiplier op alpha bij grote afwijking

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
    # Drift-detectie: tel samples waarbij nieuwe schatting sterk afwijkt van geleerde waarde
    _drift_az_votes:   int = field(default=0, repr=False)
    _drift_tilt_votes: int = field(default=0, repr=False)

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
        # Cloud cover correctie (Ecowitt / weather entity)
        self._live_cloud_cover_pct:  float | None = None
        self._live_cloud_cover_hour: int | None   = None
        # v1.5.0: Forecast.Solar cache — dict[hour_key] = watts
        self._fcsolar_cache:    dict = {}   # "YYYY-MM-DDTHH:00" → W
        self._fcsolar_ts:       float = 0.0  # timestamp laatste fetch

    # Save interval: write to HA Store at most every 2 minutes when data changed.
    _SAVE_INTERVAL_S: int = 30   # v2.6: verlaagd van 120s — minder kans op verlies bij harde restart
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
                label=(
                    cfg.get("label")
                    or (
                        (lambda st: st.attributes.get("friendly_name"))(self._hass.states.get(eid))
                        if self._hass.states.get(eid) else None
                    )
                    or eid.split(".")[-1].replace("_", " ").title()
                ),
                azimuth_deg=cfg.get("azimuth_deg"),
                tilt_deg=cfg.get("tilt_deg"),
            ))
            stored = saved.get(eid, {})
            stored_tilt = stored.get("learned_tilt")
            # Migration: old formula (peak_frac * 90) produced unrealistically
            # steep angles. Reset any learned_tilt >= 70° back to the safe
            # default so the correct curve-width algorithm can retrain quickly.
            # Manual tilt_deg overrides (set by the user) are never touched.
            if stored_tilt is not None and p.tilt_deg is None and float(stored_tilt) >= 70.0:
                _LOGGER.warning(
                    "CloudEMS PVForecast [%s]: geleerde helling %.0f° onrealistisch hoog "                    "(oud algoritme) — gereset naar %.0f° voor hertraining.",
                    cfg.get("label", eid), float(stored_tilt), _DEFAULT_TILT,
                )
                stored_tilt = _DEFAULT_TILT
                # Also clear confidence so learning restarts cleanly
                stored["orientation_confident"] = False

            p.learned_azimuth          = stored.get("learned_azimuth")
            p.learned_tilt             = stored_tilt
            p.orientation_confident    = bool(stored.get("orientation_confident", False))
            p.clear_sky_samples        = int(stored.get("clear_sky_samples", 0))
            p.hourly_yield_fraction    = dict(stored.get("hourly_yield_fraction", {}))
            p._peak_wp                 = float(stored.get("peak_wp", 0.0))
            p._calib_factor            = stored.get("calib_factor")  # None if absent
            p._calib_samples           = int(stored.get("calib_samples", 0))
            p._drift_az_votes          = int(stored.get("drift_az_votes", 0))
            p._drift_tilt_votes        = int(stored.get("drift_tilt_votes", 0))
            p._prev_learned_az         = stored.get("prev_learned_az", p.learned_azimuth)
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
                "drift_az_votes":        getattr(p, "_drift_az_votes",   0),
                "drift_tilt_votes":      getattr(p, "_drift_tilt_votes", 0),
                "prev_learned_az":       getattr(p, "_prev_learned_az", p.learned_azimuth),
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
            # Snelle alpha bij weinig data; langzamer naarmate profiel stabiliseert.
            # Minimumwaarde 0.08 (was 0.05) zodat geleidelijke wijzigingen (boomgroei,
            # tijdelijk schaduwobject) binnen enkele weken merkbaar zijn in het profiel.
            n_hours = len(p.hourly_yield_fraction)
            # When orientation is not yet confident, keep alpha higher so bad early
            # data (e.g. first cloudy day only covering 2-3 hours) is overwritten
            # within days rather than weeks.
            if not p.orientation_confident:
                alpha = 0.30 if n_hours < 8 else 0.20
            else:
                alpha = 0.30 if n_hours < 8 else (0.15 if n_hours < 16 else 0.08)
            prev = float(p.hourly_yield_fraction.get(hour_key, frac))

            # ── Adaptive alpha: versneld corrigeren bij grote afwijking ──────
            # Als de meting sterk afwijkt van het opgeslagen profiel (bijv. door
            # corrupte testdata), verhoog alpha zodat nieuwe data sneller domineert.
            deviation = abs(frac - prev)
            if deviation > 0.25 and n_hours >= 8:
                # Grote afwijking → boost alpha (max 0.45)
                alpha = min(0.45, alpha * FAST_CORRECT_ALPHA_BOOST)

            new_frac = round(prev * (1.0 - alpha) + frac * alpha, 4)

            # v4.6.453: smoothing — voorkom outliers door per uur te begrenzen
            # op max 1.5x het gemiddelde van de buururen (prevents 0.93 spike bij uur 11)
            if n_hours >= 8:
                hour_int = int(hour_key)
                neighbors = []
                for dh in (-2, -1, 1, 2):
                    nk = str((hour_int + dh) % 24)
                    if nk in p.hourly_yield_fraction and p.hourly_yield_fraction[nk] > 0:
                        neighbors.append(p.hourly_yield_fraction[nk])
                if neighbors:
                    avg_neighbor = sum(neighbors) / len(neighbors)
                    max_allowed  = min(1.0, avg_neighbor * 2.5)  # max 2.5x buurgemiddelde
                    new_frac     = round(min(new_frac, max_allowed), 4)

            p.hourly_yield_fraction[hour_key] = new_frac

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

            # ── Vroege consistentiecheck: profiel-zwaartepunt vs geleerd azimuth ──
            # Als er ≥6 uren in het profiel zitten en het gewogen zwaartepunt >60°
            # afwijkt van het geleerde azimuth, is de leerdata corrupt → directe reset.
            if len(hf) >= 6 and p.learned_azimuth is not None:
                total_w = sum(hf.values())
                if total_w > 0:
                    centroid_h  = sum(int(h) * v for h, v in hf.items()) / total_w
                    centroid_az = max(0.0, min(360.0, 180.0 + (centroid_h - 12) * 15.0))
                    az_err      = abs(centroid_az - p.learned_azimuth)
                    az_err      = min(az_err, 360.0 - az_err)  # wrap-around
                    if az_err > 60.0:
                        _LOGGER.warning(
                            "CloudEMS PVForecast [%s]: uurprofiel-zwaartepunt (%.0f°) wijkt "
                            "%.0f° af van geleerd azimuth (%.0f°) — leerdata corrupt, reset.",
                            p.label, centroid_az, az_err, p.learned_azimuth,
                        )
                        p.hourly_yield_fraction = {}
                        p.orientation_confident = False
                        p.clear_sky_samples     = 0
                        p._drift_az_votes       = 0
                        p._drift_tilt_votes     = 0
                        p.learned_azimuth       = None
                        p.learned_tilt          = None
                        self._dirty             = True
                        return

            # Solar noon = hour of maximum yield fraction seen so far.
            # Even with a single hour of data we can make a provisional estimate —
            # it will refine itself as more hours accumulate.
            # Azimuth: use weighted centroid (not argmax) to estimate solar noon.
            # Argmax is fragile: one cloud-free hour early in the season biases the
            # whole profile. Centroid weighs ALL hours proportionally so it corrects
            # itself as soon as the true peak hours accumulate data.
            # Also require a minimum time-spread of ≥5 hours so that an incomplete
            # daily profile (e.g. only 09:00-12:00 captured) cannot lock in a wrong
            # south-facing estimate for both east and west inverters.
            n_hours      = len(hf)
            hf_values    = list(hf.values())
            peak_frac    = max(hf_values)
            hour_keys    = [int(h) for h in hf]
            hour_spread  = max(hour_keys) - min(hour_keys) if hour_keys else 0

            if n_hours >= 4 and hour_spread >= 5:
                # Weighted centroid of hourly yield fractions → robust solar noon
                total_w    = sum(hf.values())
                centroid_h = sum(int(h) * v for h, v in hf.items()) / total_w
                noon_offset = centroid_h - 12
                learned_az = max(0.0, min(360.0, 180.0 + noon_offset * 15.0))
            else:
                # Insufficient spread — keep previous value or default to geographic south
                learned_az = p.learned_azimuth if p.learned_azimuth is not None else 180.0

            # Tilt: derived from yield-curve *width*, NOT peak fraction.
            #
            # Physical reasoning: a flat panel captures diffuse light over many
            # hours; a steep panel has a narrow peaked window.
            # Count hours with yield_fraction >= 30% of peak hour as productive.
            #
            # Netherlands calibration (lat ~52°, summer clear-sky day):
            #   >= 9 productive hours  -> very flat  ~10-20 deg
            #      7-8 hours           -> typical    ~25-35 deg
            #      5-6 hours           -> steeper    ~40-50 deg
            #   <= 4 hours             -> steep      ~52-60 deg
            #
            # Formula: tilt = 75 - productive_hours * 7, clamped 15-60 deg.
            # Hard cap at 60: vertical/wall panels need manual override.
            # With <6 distinct hours the curve shape is not meaningful yet.
            if n_hours >= 6:
                productive_hours = sum(1 for v in hf_values if v >= 0.30 * peak_frac)
                learned_tilt = round(max(15.0, min(60.0, 75.0 - productive_hours * 7.0)), 1)
            else:
                # Insufficient hourly diversity — keep previous or use safe default
                learned_tilt = p.learned_tilt if p.learned_tilt is not None else _DEFAULT_TILT

            new_az   = round(learned_az, 1)
            new_tilt = learned_tilt

            # ── Oriëntatie-drift detectie ──────────────────────────────────
            # Als de nieuwe schatting structureel afwijkt van wat geleerd is,
            # neem dan aan dat de panelen verplaatst zijn en reset het profiel.
            if p.learned_azimuth is not None and p.orientation_confident:
                az_dev   = abs(new_az - p.learned_azimuth)
                tilt_dev = abs(new_tilt - (p.learned_tilt or _DEFAULT_TILT))

                az_drifting   = az_dev   > DRIFT_AZ_THRESHOLD
                tilt_drifting = tilt_dev > DRIFT_TILT_THRESHOLD

                if az_drifting or tilt_drifting:
                    p._drift_az_votes   = getattr(p, "_drift_az_votes",   0) + (1 if az_drifting   else 0)
                    p._drift_tilt_votes = getattr(p, "_drift_tilt_votes", 0) + (1 if tilt_drifting else 0)
                else:
                    # Consistent opnieuw — reset tellers
                    p._drift_az_votes   = max(0, getattr(p, "_drift_az_votes",   0) - 1)
                    p._drift_tilt_votes = max(0, getattr(p, "_drift_tilt_votes", 0) - 1)

                drift_confirmed = (
                    getattr(p, "_drift_az_votes",   0) >= DRIFT_WINDOW_SAMPLES or
                    getattr(p, "_drift_tilt_votes", 0) >= DRIFT_WINDOW_SAMPLES
                )
                if drift_confirmed:
                    _LOGGER.warning(
                        "CloudEMS PVForecast [%s]: oriëntatie-drift gedetecteerd! "
                        "Azimuth %.0f°→%.0f° (Δ%.0f°), tilt %.0f°→%.0f° (Δ%.0f°). "
                        "Profiel gereset — hertraining gestart.",
                        p.label,
                        p.learned_azimuth, new_az, az_dev,
                        p.learned_tilt or _DEFAULT_TILT, new_tilt, tilt_dev,
                    )
                    # Reset profiel: wis hourly yield shape en oriëntatiezekerheid
                    # zodat het algoritme snel herleert met de nieuwe positie.
                    p.hourly_yield_fraction = {}
                    p.orientation_confident = False
                    p.clear_sky_samples     = 0
                    p._drift_az_votes       = 0
                    p._drift_tilt_votes     = 0
                    # Bewaar nieuwe waarden direct als startpunt
                    p.learned_azimuth = new_az
                    p.learned_tilt    = new_tilt
                    self._dirty = True
                    return  # Sla rest van deze sample over

            p.learned_azimuth = new_az
            p.learned_tilt    = new_tilt
            p.clear_sky_samples += 1
            self._dirty = True

            # ── Fast-track azimuth correctie (ook vóór orientation_confident) ──
            # Als de dagvorm-schatting sterk afwijkt van het huidige geleerde azimuth
            # (bijv. door te veel testdata), verminder dan het gewicht van het hele
            # hourly profiel zodat nieuwe zonnedata sneller domineert.
            # EXTRA: when still learning (not confident) the threshold is halved so
            # that bad-early-data profiles correct within days instead of weeks.
            prev_az = getattr(p, "_prev_learned_az", None)
            fast_correct_threshold = (
                FAST_CORRECT_AZ_THRESHOLD / 2.0
                if not p.orientation_confident
                else FAST_CORRECT_AZ_THRESHOLD
            )
            if (
                prev_az is not None
                and abs(new_az - prev_az) > fast_correct_threshold
                and n_hours >= 8
            ):
                # Vertraag het profiel: schaal alle waarden met 0.5
                # → nieuwe dagmetingen hebben 2× zo veel gewicht → snellere correctie
                scale = 0.3 if not p.orientation_confident else 0.5
                p.hourly_yield_fraction = {
                    k: round(v * scale, 4)
                    for k, v in p.hourly_yield_fraction.items()
                }
                _LOGGER.info(
                    "CloudEMS PVForecast [%s]: azimuth-correctie versneld "
                    "(was %.0f°, schatting %.0f°, Δ%.0f°) — profiel gewicht × %.1f.",
                    p.label, prev_az, new_az, abs(new_az - prev_az), scale,
                )
            p._prev_learned_az = new_az  # type: ignore[attr-defined]

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

    async def async_refresh_forecast_solar(self) -> None:
        """Fetch Forecast.Solar watt-per-hour forecast for all inverters combined.

        Gratis API, geen key vereist. Rate limit: ~12 req/uur (1 req per 12 min).
        Cache: FORECAST_SOLAR_CACHE_S (2u). Valt stil bij fouten — layers 1+2 nemen over.

        Forecast.Solar azimuth-conventie: 0=S, -90=O (East), +90=W.
        HA-conventie: 0=N, 90=O, 180=Z, 270=W.
        Conversie: fs_az = ha_az - 180 (dan clampen naar -180…+180).
        """
        if not self._session:
            return
        if time.time() - self._fcsolar_ts < FORECAST_SOLAR_CACHE_S:
            return  # Cache nog geldig

        profiles_with_data = [
            p for p in self._profiles.values()
            if p.effective_tilt is not None and p.effective_azimuth is not None
            and p._peak_wp and p._peak_wp > 10
        ]
        if not profiles_with_data:
            return

        # Combineer alle omvormers: gewogen gemiddeld tilt/azimuth, totaal kWp
        total_kwp = sum(p._peak_wp for p in profiles_with_data) / 1000.0
        if total_kwp < 0.1:
            return

        tilts = [p.effective_tilt or 35.0 for p in profiles_with_data]
        azims = [p.effective_azimuth or 180.0 for p in profiles_with_data]
        avg_tilt = round(sum(tilts) / len(tilts), 0)
        avg_az_ha = sum(azims) / len(azims)
        # HA (0=N,90=E,180=S,270=W) → Forecast.Solar (0=S,-90=E,+90=W)
        fs_az = avg_az_ha - 180.0
        fs_az = max(-180.0, min(180.0, fs_az))

        url = FORECAST_SOLAR_URL.format(
            lat=round(self._lat, 4),
            lon=round(self._lon, 4),
            dec=int(avg_tilt),
            az=int(fs_az),
            kwp=round(total_kwp, 2),
        )

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data   = await r.json()
                    watts  = data.get("result", {}).get("watts", {})
                    # watts dict: {"2025-03-18 08:00:00": 123, ...}
                    # Normaliseer keys naar ISO format "YYYY-MM-DDTHH:00"
                    cache = {}
                    for ts_str, w in watts.items():
                        try:
                            # Forecast.Solar levert "YYYY-MM-DD HH:MM:SS"
                            dt_obj = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                            key = dt_obj.strftime("%Y-%m-%dT%H:00")
                            cache[key] = float(w)
                        except Exception:
                            pass
                    self._fcsolar_cache = cache
                    self._fcsolar_ts    = time.time()
                    _LOGGER.info(
                        "CloudEMS PVForecast: Forecast.Solar bijgewerkt — %d uur, %.1f kWp, "
                        "tilt=%.0f° az=%.0f° (HA-conventie)",
                        len(cache), total_kwp, avg_tilt, avg_az_ha,
                    )
                elif r.status == 429:
                    _LOGGER.debug("CloudEMS PVForecast: Forecast.Solar rate limit (429) — gebruik cache")
                else:
                    _LOGGER.debug("CloudEMS PVForecast: Forecast.Solar HTTP %d", r.status)
        except Exception as exc:
            _LOGGER.debug("CloudEMS PVForecast: Forecast.Solar fetch mislukt: %s", exc)

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

        # v1.5.0: Layer 3 — Forecast.Solar (na Open-Meteo, zelfde aanroep-cadans)
        await self.async_refresh_forecast_solar()

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

    def update_cloud_cover(self, cloud_cover_pct: float | None, hour: int | None = None) -> None:
        """Update live cloud cover voor huidige uur (0-100%).
        Bronnen: HA weather entity, Ecowitt, KNMI, etc.
        Reduceer forecast proportioneel: 0% bewolkt = 100% zon, 100% bewolkt = 15% zon (diffuus licht)
        """
        if cloud_cover_pct is None:
            return
        self._live_cloud_cover_pct = float(max(0.0, min(100.0, cloud_cover_pct)))
        self._live_cloud_cover_hour = hour if hour is not None else __import__("datetime").datetime.now().hour

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

            # v4.6.453: pas calib_factor toe — zonder calib is forecast ~1.6x te hoog
            _calib = p._calib_factor if (p._calib_factor and 0.2 <= p._calib_factor <= 1.5) else 1.0
            forecast_w = round(max(0.0, p._peak_wp * blended * _calib), 1)

            # v1.5.0: Layer 3 — Forecast.Solar overschrijft layers 1+2 als beschikbaar
            # Forecast.Solar geeft totaal voor alle omvormers; verdeel proportioneel over
            # omvormers op basis van hun peak_wp aandeel.
            weather_key_fs = target.strftime("%Y-%m-%dT%H:00")
            fs_total_w = self._fcsolar_cache.get(weather_key_fs)
            if fs_total_w is not None and fs_total_w >= 0:
                # Bereken aandeel van deze omvormer in totaal kWp
                total_peak_wp = sum(
                    pp._peak_wp for pp in self._profiles.values() if pp._peak_wp and pp._peak_wp > 10
                )
                share = (p._peak_wp / total_peak_wp) if total_peak_wp > 10 else 1.0
                # v4.6.595: calib_factor OOK toepassen op Forecast.Solar layer 3.
                # Forecast.Solar kent geen schaduw/horizon/systeemverliezen — de calib_factor
                # corrigeert daarvoor op basis van historische werkelijke productie.
                # Zonder deze correctie geeft morgen ~2.5x te hoge waarde (calib ~0.40).
                forecast_w = round(max(0.0, fs_total_w * share * _calib), 1)
                conf = 0.93  # Forecast.Solar: hoge betrouwbaarheid

            # Cloud cover correctie voor het huidige uur (live data van weather sensor/Ecowitt)
            # Alleen toepassen als de cloud cover data vers is (huidig uur)
            _cc = self._live_cloud_cover_pct
            _cc_hour = self._live_cloud_cover_hour
            if _cc is not None and _cc_hour == target.hour:
                # 0% bewolkt = factor 1.0, 100% bewolkt = factor 0.15 (diffuus licht)
                # Lineaire interpolatie: factor = 1.0 - 0.85 * (cc/100)
                _cc_factor = max(0.15, 1.0 - 0.85 * (_cc / 100.0))
                forecast_w = round(forecast_w * _cc_factor, 1)
                conf = max(0.4, conf * (1.0 - _cc / 200.0))  # confidence daalt bij bewolking

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

    def finalize_hour(
        self,
        inverter_id: str,
        hour: int,
        actual_kwh: float,
    ) -> None:
        """v4.6.506: Sterke per-uur correctie bij uurwisseling.

        Vergelijkt de werkelijke kWh van het afgesloten uur met de forecast-kWh
        voor dat uur, en past hourly_yield_fraction aan via een sterkere alpha
        dan de 10-seconden EMA (0.08-0.15).

        Dit zorgt dat een uur dat structureel te hoog/laag is (bijv. door schaduw
        of oriëntatie-afwijking) binnen enkele dagen gecorrigeerd wordt.

        Logica:
          actual_kwh → actual_frac = actual_kwh / peak_wp
          forecast_frac → huidig opgeslagen profiel
          verschil → pas hourly_yield_fraction aan met alpha=0.25 (sterk)

        Veiligheidslimieten:
          - Alleen als actual_kwh >= 0 en uur een zonne-uur is (6-21)
          - Correctie max factor 2.0x of 0.1x (voorkomt wilde uitschieters)
          - Alleen als peak_wp bekend is
        """
        if hour < 6 or hour > 21:
            return  # nacht — geen correctie
        p = self._profiles.get(inverter_id)
        if p is None or p._peak_wp < 10:
            return
        if actual_kwh < 0:
            return

        hour_key = str(hour)
        # Werkelijke fractie: kWh → W gemiddeld over het uur
        actual_w    = actual_kwh * 1000.0  # kWh → Wh → gem. W (1 uur)
        actual_frac = actual_w / p._peak_wp

        # Begrens op plausibele waarden
        actual_frac = max(0.0, min(1.0, actual_frac))

        prev_frac = float(p.hourly_yield_fraction.get(hour_key, actual_frac))

        # Gebruik sterkere alpha dan de 10s-EMA zodat uurwisseling meer gewicht heeft
        alpha = 0.25

        new_frac = round(prev_frac * (1.0 - alpha) + actual_frac * alpha, 4)

        # Veiligheidscheck: max 2x of min 0.1x van vorige waarde
        if prev_frac > 0.01:
            new_frac = min(new_frac, prev_frac * 2.0)
            new_frac = max(new_frac, prev_frac * 0.1)

        old_frac = p.hourly_yield_fraction.get(hour_key, 0.0)
        p.hourly_yield_fraction[hour_key] = round(new_frac, 4)
        self._dirty = True

        _LOGGER.info(
            "PVForecast finalize_hour [%s] uur=%d: werkelijk=%.3f kWh "
            "frac %.4f → %.4f (Δ%+.4f, alpha=%.2f)",
            inverter_id, hour, actual_kwh,
            old_frac, new_frac, new_frac - old_frac, alpha,
        )

    def get_forecast_tomorrow(self, inverter_id: str) -> list[HourForecast]:
        """Return 24-hour forecast for tomorrow for one inverter."""
        tomorrow = (
            dt_util.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        return self._build_forecast(inverter_id, tomorrow, confidence_no_weather=0.6)

    def get_total_forecast_today_kwh(self, produced_kwh: float = 0.0) -> float:
        """Sum forecast for all inverters for today in kWh.

        v4.6.493: dagtotaal = geproduceerde uren (0 t/m nowH-1) + forecast resterende uren
        (nowH t/m 23). get_forecast() start al bij het huidige uur, maar geeft 24 uur terug
        die na middernacht morgen in lopen — alleen de uren t/m 23 meenemen.
        """
        from homeassistant.util import dt as _dt_util
        _now = _dt_util.now()
        _now_h = _now.hour
        _now_min = _now.minute
        # Aantal resterende uren vandaag (inclusief huidig uur)
        hours_left_today = 24 - _now_h
        remaining = 0.0
        for eid in self._profiles:
            for i, hf in enumerate(self.get_forecast(eid)):
                if i >= hours_left_today:
                    break
                remaining += hf.forecast_w / 1000.0
        # Huidig uur al deels geproduceerd — trek overlap af om dubbeltelling te voorkomen
        current_hour_forecast = 0.0
        for eid in self._profiles:
            fc_list = self.get_forecast(eid)
            if fc_list:
                current_hour_forecast += fc_list[0].forecast_w / 1000.0
        _hour_frac_done = _now_min / 60.0
        overlap = min(produced_kwh, current_hour_forecast * _hour_frac_done)
        return round(max(0.0, produced_kwh - overlap) + remaining, 2)

    def get_total_forecast_tomorrow_kwh(self) -> float:
        """Sum forecast for all inverters for tomorrow in kWh."""
        total = 0.0
        for eid in self._profiles:
            for hf in self.get_forecast_tomorrow(eid):
                total += hf.forecast_w / 1000.0
        return round(total, 2)

    def get_forecast_solar_status(self) -> dict:
        """Return Forecast.Solar layer 3 status voor dashboard."""
        return {
            "active":       bool(self._fcsolar_cache),
            "cached_hours": len(self._fcsolar_cache),
            "last_update":  datetime.fromtimestamp(self._fcsolar_ts, tz=timezone.utc).isoformat()
                            if self._fcsolar_ts > 0 else None,
            "cache_age_min": round((time.time() - self._fcsolar_ts) / 60, 0)
                            if self._fcsolar_ts > 0 else None,
        }

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

    def seed_from_learner(
        self,
        inverter_id: str,
        hourly_peak_w: dict,
        peak_wp: float,
    ) -> None:
        """
        Vul *ontbrekende* uren in hourly_yield_fraction vanuit solar_learner data.

        Wordt aangeroepen na elke solar_learner update, zodat de pv_forecast niet
        leeg blijft na een herstart wanneer het systeem nog niet alle uren van
        vandaag heeft kunnen leren.

        Regels:
        - Overschrijft NOOIT reeds geleerde fracties (die zijn nauwkeuriger).
        - Gebruikt hourly_peak_w uit solar_learner als zwak prior.
        - Normaliseert op peak_wp zodat de fractie consistent is.
        - Slaat alleen fracties op als ze plausibel zijn (> 0 en peak_wp > 10).
        """
        p = self._profiles.get(inverter_id)
        if p is None or peak_wp < 10 or not hourly_peak_w:
            return

        seeded = 0
        for hour_str, peak_w in hourly_peak_w.items():
            hk = str(int(hour_str))          # normaliseer key (geen leading zero's)
            if hk in p.hourly_yield_fraction:
                continue                     # al geleerd — niet overschrijven
            frac = max(0.0, float(peak_w) / peak_wp)
            if frac <= 0.0:
                continue
            # Zwak prior: lagere alpha dan leerroute (0.15) — wordt snel vervangen
            p.hourly_yield_fraction[hk] = round(min(frac, 1.0), 4)
            seeded += 1

        if seeded:
            import logging as _log
            _log.getLogger(__name__).debug(
                "CloudEMS PVForecast: seed_from_learner %s — %d uren gevuld als prior",
                inverter_id, seeded,
            )



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
