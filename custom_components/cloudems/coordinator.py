"""CloudEMS DataUpdateCoordinator — v1.16.1."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
# BUG FIXES in v1.4.1:
#   - Added confirm_nilm_device(), dismiss_nilm_device(), async_shutdown() methods
#   - _process_power_data: passes current_a correctly to limiter.update_phase()
#   - _calc_cheap_hours removed (logic now inside prices.get_price_info())
#   - _find_cheapest_window removed (lives in prices.py)
#   - solar_learner.get_profile() None check added
#   - Binary sensor platform registration (in __init__.py)
#   - Insights/advice text generation
#   - Decision log for dimming / switching events
#   - Boiler controller integration
#   - Inverter peak power + clipping detection exposed in data

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IDEEËNLIJST — toekomstige features (backlog, niet geïmplementeerd)         │
# ├─────────────────────────────────────────────────────────────────────────────┤
# │                                                                             │
# │  3. NETCONGESTIE VOORSPELLING                                               │
# │     Koppeling Tennet/Enexis congestiekaart. Nieuwe module:                 │
# │     energy_manager/grid_forecast.py                                        │
# │     - Bronnen: Tennet Transparantie API, Enexis GeoJSON, ENTSO-E           │
# │     - ZIP-code → regio mapping voor lokale congestie                       │
# │     - Sensoren: grid_congestion_forecast (none/low/medium/high/critical)   │
# │       grid_congestion_region_active, flex_minutes, next_event              │
# │     - HA-blueprint: EV terugschalen + boiler uit bij congestie             │
# │                                                                             │
# │  4. MAANDRAPPORTAGE PER E-MAIL                                              │
# │     Automatische overzichtsmail via HA notify.                             │
# │     energy_manager/monthly_report.py                                       │
# │     - Data uit HA long-term statistics (netverbruik, kosten, PV, CO2,      │
# │       EV, gas, top-3 apparaten, trend vs vorige maand)                     │
# │     - Service: cloudems.send_monthly_report(month, notify_service)         │
# │     - Talen: NL/EN/DE, optioneel PDF via WeasyPrint                        │
# │     - Weekdigest variant (compacter, elke maandag)                         │
# │                                                                             │
# │  5. ONBOARDING KWALITEITS-SCORE                                             │
# │     Installatiekwaliteit 0-100 voor gebruikersbegeleiding.                 │
# │     energy_manager/installation_score.py                                   │
# │     - Criteria: P1-lezer, fase-sensoren, PV, EV, batterij, gas,            │
# │       EPEX-land, AI-provider, tarieven                                     │
# │     - Sensor: cloudems_installatiescore (0-100, grade A/B/C/D)            │
# │     - Dashboard: cirkel met score, tips, sparkline 30d                    │
# │     - Persistent notification bij score <50                                │
# │                                                                             │
# │  6. TIBBER INTEGRATIE                                                       │
# │     GraphQL API koppeling voor directe prijzen + Pulse meterdata.          │
# │     energy/tibber.py                                                        │
# │     - Bearer token auth, vandaag + morgen prijzen, 7 landen                │
# │     - WebSocket subscription voor Pulse real-time data (1 Hz)              │
# │     - Fetch chain: Tibber → EnergyZero → Awattar → ENTSO-E                │
# │     - Verbruikshistorie 30d voor CostForecaster initialisatie              │
# │                                                                             │
# │  7. BE/FR/NO/SE/DK GRATIS PRIJSBRON                                         │
# │     Gratis EPEX zonder API-sleutel voor meer landen.                       │
# │     Uitbreiding energy/prices.py FREE_SOURCES dict:                        │
# │     - BE: Elia griddata.elia.be (JSON dag-ahead, update 12:30 CET)        │
# │     - FR: RTE digital.iservices.rte-france.com (publiek, geen auth)       │
# │     - NO: Hvakoster.no, SE: Elpriset Just Nu, DK: Energidataservice       │
# │     - Fallback: ENTSO-E voor alle andere landen                            │
# │                                                                             │
# │  8. NILM TIJDPATROON LEREN                                                  │
# │     Detecteer vaste gebruikspatronen per apparaat (bijv. wasmachine        │
# │     altijd di/do/za 10:00). Basis voor slimmere planning en anomalie-      │
# │     detectie ("wasmachine draait midden in de nacht — wie doet dat?").     │
# │     Opslaan als uurhistogram per weekdag in nilm storage.                  │
# │                                                                             │
# │  9. MULTI-TARIEF NACHTLADEN BEWUSTZIJN                                      │
# │     Detecteer automatisch of gebruiker dalttarief heeft (bijv. 23:00-7:00) │
# │     op basis van prijspatronen of handmatige invoer.                       │
# │     Koppelen aan battery_scheduler en EV charger planning.                 │
# │                                                                             │
# └─────────────────────────────────────────────────────────────────────────────┘

from __future__ import annotations
import logging
import asyncio
import math
import os
import threading
import time
from datetime import timedelta, datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import IntEnum

# v1.21.0: optional libs — HA loads fine without them, engine degrades gracefully
try:
    import numpy as _np
    from scipy.signal import find_peaks as _find_peaks, savgol_filter as _savgol_filter
    from sklearn.cluster import MiniBatchKMeans as _KMeans
    _NILM_LIBS = True
except ImportError:
    _np = _find_peaks = _savgol_filter = _KMeans = None  # type: ignore
    _NILM_LIBS = False

try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    _psutil = None  # type: ignore
    _PSUTIL_OK = False

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import (
    CONF_AI_PROVIDER, AI_PROVIDER_NONE, AI_PROVIDER_OLLAMA, AI_PROVIDERS_NEEDING_KEY,
    CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE,
    DOMAIN, UPDATE_INTERVAL_FAST, DEFAULT_MAX_CURRENT, DEFAULT_MAINS_VOLTAGE_V,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_NILM_ENERGY,
    CONF_GRID_SENSOR, CONF_PHASE_SENSORS, CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY,
    CONF_ENERGY_PRICES_COUNTRY, CONF_CLOUD_API_KEY,
    CONF_MAX_CURRENT_PER_PHASE, CONF_ENABLE_SOLAR_DIMMER,
    CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    CONF_PHASE_COUNT, CONF_ENERGY_TAX,
    CONF_DYNAMIC_LOADING, CONF_PHASE_BALANCE, CONF_P1_ENABLED,
    CONF_MAX_CURRENT_L1,
    CONF_INVERTER_CONFIGS, CONF_ENABLE_MULTI_INVERTER,
    CONF_USE_SEPARATE_IE, CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR,
    CONF_VOLTAGE_L1, CONF_VOLTAGE_L2, CONF_VOLTAGE_L3,
    CONF_POWER_L1, CONF_POWER_L2, CONF_POWER_L3,
    CONF_MAINS_VOLTAGE,
    CONF_OLLAMA_ENABLED, CONF_OLLAMA_HOST, CONF_OLLAMA_PORT, CONF_OLLAMA_MODEL,
    CONF_PEAK_SHAVING_ENABLED, CONF_PEAK_SHAVING_LIMIT_W, CONF_PEAK_SHAVING_ASSETS,
    EPEX_UPDATE_INTERVAL, ALL_PHASES,
    CONF_GAS_SENSOR,
    CONF_BATTERY_CONFIGS, CONF_ENABLE_MULTI_BATTERY,
    CONF_PRICE_INCLUDE_TAX, CONF_PRICE_INCLUDE_BTW, CONF_SUPPLIER_MARKUP, CONF_SELECTED_SUPPLIER,
    ENERGY_TAX_PER_COUNTRY, VAT_RATE_PER_COUNTRY, SUPPLIER_MARKUPS,
    CONF_ENERGY_PRICES_COUNTRY,
)
from .nilm.detector import NILMDetector, DetectedDevice
from .nilm.hybrid_nilm import HybridNILM
from .energy_manager.home_baseline import HomeBaselineLearner
from .energy_manager.ev_session_learner import EVSessionLearner
from .energy_manager.nilm_schedule import NILMScheduleLearner
from .energy.prices import EnergyPriceFetcher
from .energy.limiter import CurrentLimiter
from .energy_manager.power_calculator import PowerCalculator
from .energy_manager.notification_engine import NotificationEngine
from .energy_manager.sensor_ema import SensorEMALayer
from .energy_manager.sensor_sanity import SensorSanityGuard
from .energy_manager.absence_detector import AbsenceDetector
from .energy_manager.climate_preheat import ClimatePreHeatAdvisor
from .energy_manager.pv_accuracy import PVForecastAccuracyTracker
from .energy_manager.heat_pump_cop import HeatPumpCOPLearner

_LOGGER = logging.getLogger(__name__)

# Max decision log entries kept in memory
MAX_DECISION_LOG = 50
# Clipping detection: plateau-based (flat top of the power parabola).
#
# Two-layer detection:
#   Layer 1 — Plateau: last PLATEAU_WINDOW_SIZE readings (≈5 min) are flat.
#             stddev/mean < adaptive threshold AND mean ≥ ceiling × CLIPPING_CEILING_FRAC.
#   Layer 2 — Rising slope: the PLATEAU_PRE_SIZE readings BEFORE the plateau were
#             still rising (pre-window mean < plateau mean × PLATEAU_RISE_MAX_RATIO).
#             This confirms the parabola was cut off, not merely a cloudy plateau.
#
# Ceiling priority:
#   1. rated_power_w from config (most reliable — set by user)
#   2. Self-learned ceiling from ClippingLossCalculator (accumulated real plateaus)
#   3. NO fallback to peak_power_w_7d — that is the already-clipped observed peak,
#      using it as ceiling causes false positives on every clear day.
PLATEAU_WINDOW_SIZE    = 30     # readings in plateau window  (~5 min at 10 s interval)
PLATEAU_PRE_SIZE       = 18     # readings before plateau for slope check (~3 min)
PLATEAU_RISE_MAX_RATIO = 0.97   # pre-window mean must be < plateau_mean * this to confirm rise
PLATEAU_STABILITY_PCT  = 0.015  # max stddev/mean for plateau (1.5 %)
PLATEAU_MIN_FRACTION   = 0.80   # must be at least 80% of seen peak to count
DEFAULT_FEEDIN_EUR_KWH = 0.08   # fallback feed-in tarief als EPEX niet beschikbaar
# How close to the configured/learned ceiling before we call it clipping
CLIPPING_CEILING_FRAC  = 0.95   # within 5% of ceiling — avoids false positives


# ═══════════════════════════════════════════════════════════════════════════════
# v1.21.0 — NilmCpuGuard + NilmEnhancer (CPU-adaptive NILM engine)
# ═══════════════════════════════════════════════════════════════════════════════

_NILM_CORES         = os.cpu_count() or 1
_NILM_MAX_CPU       = _NILM_CORES * 100.0
_NILM_EWA_ALPHA     = 0.3
_NILM_MONITOR_INT   = 0.5

# CPU thresholds (% of total process cpu_percent across all cores)
_THRESH_EASY    = _NILM_MAX_CPU * 0.40
_THRESH_NORMAL  = _NILM_MAX_CPU * 0.60
_THRESH_BUSY    = _NILM_MAX_CPU * 0.75
_THRESH_HEAVY   = _NILM_MAX_CPU * 0.88
_THRESH_CRIT    = _NILM_MAX_CPU * 0.95

# Kalman
_KAL_Q = 1e-4; _KAL_R = 5.0; _BASELINE_WIN = 300

# Scipy event detection
_SAVGOL_WIN = 11; _SAVGOL_POLY = 3; _PEAK_MIN_H = 25; _PEAK_MIN_DIST = 3

# Bayesian
_WATT_SIG_REL = 0.15; _WATT_SIG_ABS = 30.0; _TIME_SIG_H = 2.0
_CONFIRM_BOOST = 0.25; _EV_MAX = 0.95

# FSM
_FSM_TYPES = {"washing_machine","dishwasher","dryer","oven","ev_charger","heat_pump","cv_boiler"}
_FSM_IDLE_TO = 120; _FSM_MIN_DELTA = 40

# Evidence accumulation
_EV_DECAY = 0.85; _EV_TRIGGER = 0.55

# Clustering
_CL_K = 12; _CL_MIN_TRAIN = 30; _CL_RETRAIN_N = 100

# Seq2Point
_SEQ2P_WIN = 599
_ONNX_DIR  = os.path.join(os.path.dirname(__file__), "nilm_models")

# Overlap resolver
_OVERLAP_MARGIN = 0.12; _SIG_BUF_LEN = 3600; _RECENT_EV = 20

_NILM_LOGGER = logging.getLogger(__name__ + ".nilm")


class _CpuMode(IntEnum):
    FULL = 5; NORMAL = 4; LITE = 3; MINIMAL = 2; PAUSE = 1


@dataclass
class _KalmanState:
    estimate: float = 0.0
    error_cov: float = 1.0
    initialised: bool = False
    residuals: deque = field(default_factory=lambda: deque(maxlen=_BASELINE_WIN))

    def update(self, meas: float) -> float:
        if not self.initialised:
            self.estimate = meas; self.initialised = True; return self.estimate
        p = self.error_cov + _KAL_Q
        k = p / (p + _KAL_R)
        self.estimate = self.estimate + k * (meas - self.estimate)
        self.error_cov = (1.0 - k) * p
        self.residuals.append(abs(meas - self.estimate))
        return self.estimate

    @property
    def noise_p80(self) -> float:
        if len(self.residuals) < 10: return 25.0
        s = sorted(self.residuals)
        return max(10.0, s[int(0.80 * len(s))])


@dataclass
class _FsmDevice:
    device_id: str; device_type: str
    states: List[float] = field(default_factory=list)
    current_state_idx: int = 0
    last_transition: float = field(default_factory=time.monotonic)
    active: bool = False

    @property
    def current_power(self) -> float:
        return self.states[min(self.current_state_idx, len(self.states)-1)] if self.active and self.states else 0.0

    def transition(self, delta_w: float) -> bool:
        if not self.states: return False
        now = time.monotonic()
        if now - self.last_transition > _FSM_IDLE_TO and self.active:
            self.current_state_idx = 0; self.active = False; self.last_transition = now; return True
        new_pw = self.current_power + delta_w
        best_i, best_d = 0, float("inf")
        for i, s in enumerate(self.states):
            if abs(s - new_pw) < best_d: best_d, best_i = abs(s - new_pw), i
        if best_d < _FSM_MIN_DELTA:
            self.current_state_idx = best_i; self.active = best_i > 0; self.last_transition = now; return True
        return False

    def add_state(self, power_w: float) -> None:
        if any(abs(s - power_w) < _FSM_MIN_DELTA for s in self.states): return
        self.states.append(power_w); self.states.sort()
        if 0.0 not in self.states: self.states.insert(0, 0.0)


@dataclass
class _EvidenceAcc:
    device_id: str; score: float = 0.0; last_seen: float = 0.0

    def accumulate(self, likelihood: float) -> float:
        self.score = min(_EV_MAX, self.score * _EV_DECAY + likelihood)
        if likelihood > 0.1: self.last_seen = time.monotonic()
        return self.score

    @property
    def is_on(self) -> bool: return self.score >= _EV_TRIGGER


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)

def _watt_lh(measured: float, nominal: float) -> float:
    if nominal <= 0: return 0.0
    return _gauss(measured, nominal, max(_WATT_SIG_ABS, _WATT_SIG_REL * nominal))

def _time_prior(hour: int, sched: Optional[dict]) -> float:
    if not sched or not sched.get("ready"): return 1.0
    ph = sched.get("peak_hour")
    if ph is None: return 1.0
    diff = min(abs(hour - ph), 24 - abs(hour - ph))
    return _gauss(diff, 0.0, _TIME_SIG_H)

def _user_factor(dev: dict) -> float:
    if dev.get("user_suppressed"): return 0.0
    if dev.get("confirmed"): return 1.0 + _CONFIRM_BOOST
    if dev.get("user_feedback") == "wrong": return 0.3
    return 1.0

def _anchor_factor(device_id: str, anchors: List[dict]) -> float:
    for a in anchors:
        if a.get("device_id") == device_id: return 1.5 if a.get("is_on") else 0.1
    return 1.0


class _NilmCpuGuard:
    """CPU monitor daemon thread — adapts NILM workload to available CPU."""

    def __init__(self) -> None:
        self._ewa: float = 0.0
        self._mode: _CpuMode = _CpuMode.NORMAL
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stats: dict = {
            "mode_changes": 0, "pauses": 0,
            "mode_full_pct": 0.0, "mode_normal_pct": 0.0, "mode_lite_pct": 0.0,
            "peak_cpu_pct": 0.0, "samples": 0,
        }
        if _PSUTIL_OK:
            try: _psutil.Process().cpu_percent()
            except Exception: pass

    def start(self) -> None:
        if self._running or not _PSUTIL_OK: return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="cloudems-cpu-guard", daemon=True)
        self._thread.start()

    @property
    def current_mode(self) -> _CpuMode:
        with self._lock: return self._mode

    def allow(self, mode: _CpuMode) -> bool:
        return self.current_mode >= mode

    def stats(self) -> dict:
        with self._lock:
            s = dict(self._stats)
            s["current_mode"] = self._mode.name
            s["cpu_ewa_pct"] = round(self._ewa, 1)
            s["cpu_normalized_pct"] = round(self._ewa / _NILM_MAX_CPU * 100, 1)
            s["cores"] = _NILM_CORES
            s["nilm_budget_pct"] = 35
            return s

    def _loop(self) -> None:
        while self._running:
            try: self._tick()
            except Exception: pass
            time.sleep(_NILM_MONITOR_INT)

    def _tick(self) -> None:
        try:
            pct = _psutil.Process().cpu_percent()
        except Exception: return
        if self._ewa == 0.0 and pct == 0.0: return
        self._ewa = self._ewa * (1 - _NILM_EWA_ALPHA) + pct * _NILM_EWA_ALPHA
        new_mode = self._compute(self._ewa)
        old_mode = self._mode
        with self._lock:
            self._mode = new_mode
            self._stats["samples"] += 1
            if pct > self._stats["peak_cpu_pct"]: self._stats["peak_cpu_pct"] = round(pct, 1)
            n = self._stats["samples"]
            for attr, m in [("mode_full_pct", _CpuMode.FULL), ("mode_normal_pct", _CpuMode.NORMAL), ("mode_lite_pct", _CpuMode.LITE)]:
                old_v = self._stats[attr]
                self._stats[attr] = round(old_v + ((1.0 if new_mode == m else 0.0) - old_v) / n, 3)
            if new_mode != old_mode:
                self._stats["mode_changes"] += 1
                if new_mode == _CpuMode.PAUSE: self._stats["pauses"] += 1

    def _compute(self, ewa: float) -> _CpuMode:
        cur = self._mode
        if ewa >= _THRESH_CRIT: return _CpuMode.PAUSE
        if ewa >= _THRESH_HEAVY: return _CpuMode.MINIMAL
        if ewa >= _THRESH_BUSY: return _CpuMode.LITE
        hysteresis = _NILM_MAX_CPU * 0.10
        if cur <= _CpuMode.LITE and ewa < _THRESH_BUSY - hysteresis: return _CpuMode.NORMAL
        if cur <= _CpuMode.NORMAL and ewa < _THRESH_NORMAL - hysteresis: return _CpuMode.FULL
        if cur >= _CpuMode.NORMAL and ewa >= _THRESH_NORMAL: return _CpuMode.NORMAL
        return cur


_nilm_guard_instance: Optional[_NilmCpuGuard] = None

def _get_nilm_guard() -> _NilmCpuGuard:
    global _nilm_guard_instance
    if _nilm_guard_instance is None:
        _nilm_guard_instance = _NilmCpuGuard()
        _nilm_guard_instance.start()
    return _nilm_guard_instance


class _NilmEnhancer:
    """CPU-adaptive NILM enhancement layer — runs after the existing NILM stack."""

    def __init__(self) -> None:
        self._guard = _get_nilm_guard()
        self._kalman: Dict[str, _KalmanState] = {}
        self._fsm: Dict[str, _FsmDevice] = {}
        self._evidence: Dict[str, _EvidenceAcc] = {}
        self._signal_buf: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_SIG_BUF_LEN))
        self._baseline_buf: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_SIG_BUF_LEN))
        self._recent_events: deque = deque(maxlen=_RECENT_EV)
        self._stats: dict = defaultdict(int)
        # Clustering (only if sklearn available)
        self._cl_buf: deque = deque(maxlen=500)
        self._cl_km = None
        self._cl_trained = 0
        self._cl_events = 0
        # Seq2Point ONNX (optional)
        self._seq2p_sessions: dict = {}
        self._seq2p_tried: set = set()
        self._seq2p_ok: bool = self._check_onnx()

    def _check_onnx(self) -> bool:
        try:
            import onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    def enhance(self, devices, phase_powers_w, hybrid_nilm, nilm_diag, nilm_schedule, hour_of_day) -> dict:
        mode = self._guard.current_mode
        self._stats["calls"] += 1

        if mode == _CpuMode.PAUSE:
            return {"devices": devices, "diagnostics": {"engine_version": "1.21.0", "engine_paused": True}, "stats": dict(self._stats)}

        anchors = hybrid_nilm.get("anchors", [])
        schedules = {s["device_id"]: s for s in nilm_schedule if "device_id" in s}

        # Step 1: Kalman baseline (always)
        baselines = self._kalman_update(phase_powers_w)

        if mode == _CpuMode.MINIMAL:
            return {"devices": devices, "diagnostics": self._diag(devices, [], mode), "stats": dict(self._stats)}

        # Step 2: Event detection (scipy if available, else simple diff)
        events = self._detect_events(phase_powers_w, baselines, hour_of_day)

        # Step 3: Bayesian confidence refinement
        enhanced = self._refine(devices, anchors, schedules, hour_of_day, events)

        if mode == _CpuMode.LITE:
            return {"devices": enhanced, "diagnostics": self._diag(enhanced, events, mode), "stats": dict(self._stats)}

        # Steps 4-5: FSM + evidence (NORMAL+)
        enhanced = self._apply_fsm(enhanced, events)
        enhanced = self._accumulate_ev(enhanced)
        enhanced = self._resolve_overlaps(enhanced, phase_powers_w)

        if mode == _CpuMode.NORMAL:
            return {"devices": enhanced, "diagnostics": self._diag(enhanced, events, mode), "stats": dict(self._stats)}

        # Step 6: Clustering (FULL, sklearn optional)
        if _NILM_LIBS:
            self._cluster_train(hour_of_day, events)

        # Step 7: Seq2Point ONNX (FULL, optional)
        enhanced = self._seq2point(enhanced, phase_powers_w)

        return {"devices": enhanced, "diagnostics": self._diag(enhanced, events, mode), "stats": dict(self._stats)}

    def reset_device(self, device_id: str) -> None:
        self._fsm.pop(device_id, None)
        self._evidence.pop(device_id, None)

    def _kalman_update(self, phase_powers_w: dict) -> dict:
        baselines = {}
        for phase, power in phase_powers_w.items():
            if not isinstance(power, (int, float)): continue
            if phase not in self._kalman: self._kalman[phase] = _KalmanState()
            baselines[phase] = self._kalman[phase].update(float(power))
            self._signal_buf[phase].append(float(power))
            self._baseline_buf[phase].append(baselines[phase])
        return baselines

    def _detect_events(self, phase_powers_w: dict, baselines: dict, hour: int) -> list:
        events = []
        ts = time.monotonic()
        for phase, buf in self._signal_buf.items():
            if len(buf) < _SAVGOL_WIN + 2: continue
            kal = self._kalman.get(phase)
            sigma = kal.noise_p80 if kal else 25.0
            min_h = max(_PEAK_MIN_H, sigma * 1.5)
            if _NILM_LIBS:
                sig = _np.array(buf, dtype=_np.float32)
                bl  = _np.array(self._baseline_buf[phase], dtype=_np.float32)
                residual = sig - bl
                if len(residual) < _SAVGOL_WIN + 2: continue
                diff = _np.diff(residual)
                if len(diff) < _SAVGOL_WIN: continue
                smooth = _savgol_filter(diff, _SAVGOL_WIN, _SAVGOL_POLY)
                ups, _   = _find_peaks( smooth, height=min_h, distance=_PEAK_MIN_DIST)
                downs, _ = _find_peaks(-smooth, height=min_h, distance=_PEAK_MIN_DIST)
                for idx in ups:
                    ev = {"phase": phase, "delta_w": float(smooth[idx]), "ts": ts}
                    events.append(ev); self._recent_events.appendleft(ev)
                    self._stats["scipy_events_up"] += 1
                for idx in downs:
                    ev = {"phase": phase, "delta_w": -float(smooth[idx]), "ts": ts}
                    events.append(ev); self._recent_events.appendleft(ev)
                    self._stats["scipy_events_down"] += 1
            else:
                # Simple fallback: compare last two samples
                buf_list = list(buf)
                if len(buf_list) >= 2:
                    delta = buf_list[-1] - buf_list[-2]
                    if abs(delta) >= min_h:
                        ev = {"phase": phase, "delta_w": delta, "ts": ts}
                        events.append(ev); self._recent_events.appendleft(ev)
        return events

    def _cluster_prior(self, delta_w: float, hour: int) -> float:
        if not _NILM_LIBS or self._cl_km is None or len(self._cl_buf) < _CL_MIN_TRAIN: return 0.5
        feat = _np.array([[delta_w, math.log(abs(delta_w)+1)*math.copysign(1,delta_w), 0.0, hour]], dtype=_np.float32)
        dists = _np.linalg.norm(self._cl_km.cluster_centers_ - feat, axis=1)
        return float(_np.exp(-float(dists.min()) / 100.0))

    def _cluster_train(self, hour: int, events: list) -> None:
        if not _NILM_LIBS: return
        for ev in events:
            delta = ev["delta_w"]
            if abs(delta) < _PEAK_MIN_H: continue
            feat = _np.array([delta, math.log(abs(delta)+1)*math.copysign(1,delta), 0.0, hour], dtype=_np.float32)
            self._cl_buf.append(feat); self._cl_events += 1
        if len(self._cl_buf) >= _CL_MIN_TRAIN and (self._cl_events - self._cl_trained) >= _CL_RETRAIN_N:
            X = _np.array(list(self._cl_buf), dtype=_np.float32)
            if self._cl_km is None:
                self._cl_km = _KMeans(n_clusters=_CL_K, n_init=1, random_state=42, batch_size=64)
            self._cl_km.partial_fit(X)
            self._cl_trained = self._cl_events
            self._stats["cluster_retrains"] += 1

    def _refine(self, devices, anchors, schedules, hour, events) -> list:
        result = []
        for dev in devices:
            dev = dict(dev)
            if dev.get("source") in ("smart_plug", "injected"):
                result.append(dev); continue
            did   = dev.get("device_id") or dev.get("name", "")
            cur_w = dev.get("current_power", 0.0) or 0.0
            nom_w = dev.get("typical_power_w") or dev.get("peak_power_w") or cur_w
            orig  = float(dev.get("confidence", 0.5) or 0.5)
            p_w   = _watt_lh(cur_w, nom_w) if dev.get("is_on") else 1.0
            p_t   = _time_prior(hour, schedules.get(did))
            p_u   = _user_factor(dev)
            p_a   = _anchor_factor(did, anchors)
            phase = dev.get("phase", "L1")
            ev_delta = next((e["delta_w"] for e in events if e.get("phase") == phase), 0.0)
            p_c   = self._cluster_prior(ev_delta, hour)
            if p_u == 0.0:
                posterior = 0.0
            else:
                eps = 1e-9
                log_odds = math.log(orig / (1 - orig + eps) + eps)
                log_upd  = (0.4*math.log(p_w+eps) + 0.3*math.log(p_t+eps) + 0.2*math.log(p_a+eps) + 0.1*math.log(p_c+eps))
                posterior = 1.0 / (1.0 + math.exp(-(log_odds + 0.5*log_upd)))
                posterior = min(_EV_MAX, posterior * p_u)
            new_conf = min(_EV_MAX, posterior) if dev.get("confirmed") else (min(orig, posterior) if posterior < orig else min(_EV_MAX, posterior*0.8))
            if abs(new_conf - orig) > 0.01: self._stats["conf_adjustments"] += 1
            dev["confidence"] = round(new_conf, 4)
            result.append(dev)
        return result

    def _apply_fsm(self, devices, events) -> list:
        if not events: return devices
        result = []
        for dev in devices:
            dev = dict(dev)
            dtype = dev.get("device_type", "")
            if dtype not in _FSM_TYPES: result.append(dev); continue
            did = dev.get("device_id") or dev.get("name", "")
            if did not in self._fsm: self._fsm[did] = _FsmDevice(device_id=did, device_type=dtype)
            fsm = self._fsm[did]
            cur_w = dev.get("current_power", 0.0) or 0.0
            if dev.get("is_on") and cur_w > 10: fsm.add_state(cur_w)
            for ev in events:
                if ev.get("phase") == dev.get("phase", "L1"):
                    if fsm.transition(ev["delta_w"]): self._stats["fsm_transitions"] += 1
            if fsm.states:
                dev["fsm_states_w"] = [round(s, 0) for s in fsm.states]
                dev["fsm_active"] = fsm.active
            result.append(dev)
        return result

    def _accumulate_ev(self, devices) -> list:
        result = []
        for dev in devices:
            dev = dict(dev)
            if dev.get("source") in ("smart_plug", "injected"): result.append(dev); continue
            did = dev.get("device_id") or dev.get("name", "")
            if did not in self._evidence: self._evidence[did] = _EvidenceAcc(device_id=did)
            acc = self._evidence[did]
            conf = float(dev.get("confidence", 0.0) or 0.0)
            score = acc.accumulate(conf if dev.get("is_on") else 0.0)
            dev["evidence_score"] = round(score, 3)
            if acc.is_on and not dev.get("is_on") and score > _EV_TRIGGER + 0.1:
                dev["engine_hint_on"] = True; self._stats["evidence_hints"] += 1
            result.append(dev)
        return result

    def _resolve_overlaps(self, devices, phase_powers_w) -> list:
        by_phase: Dict[str, list] = defaultdict(list)
        for dev in devices:
            if dev.get("is_on") and (dev.get("current_power") or 0) > 0:
                by_phase[dev.get("phase", "L1")].append(dev)
        for phase, pdevs in by_phase.items():
            measured = phase_powers_w.get(phase, 0.0)
            if measured <= 0: continue
            plug_w = sum(d.get("current_power", 0) for d in pdevs if d.get("source") in ("smart_plug","injected"))
            nilm   = [d for d in pdevs if d.get("source") not in ("smart_plug","injected")]
            nilm_w = sum(d.get("current_power", 0) for d in nilm)
            budget = measured * (1 + _OVERLAP_MARGIN) - plug_w
            if budget <= 0 or nilm_w <= 0 or nilm_w <= budget: continue
            scale = budget / nilm_w
            for dev in nilm:
                conf = float(dev.get("confidence", 0.5) or 0.5)
                dev["current_power"] = round((dev.get("current_power", 0) or 0) * (scale + (1.0-scale)*conf), 1)
            self._stats["overlap_rescales"] += 1
        return devices

    def _seq2point(self, devices, phase_powers_w) -> list:
        if not self._seq2p_ok or not os.path.isdir(_ONNX_DIR): return devices
        result = []
        for dev in devices:
            dev = dict(dev)
            dtype = dev.get("device_type", "")
            phase = dev.get("phase", "L1")
            if dev.get("source") in ("smart_plug","injected") or not dev.get("is_on"):
                result.append(dev); continue
            buf = self._signal_buf.get(phase)
            if not _NILM_LIBS or buf is None or len(buf) < _SEQ2P_WIN:
                result.append(dev); continue
            sess = self._seq2p_load(dtype)
            if sess is None: result.append(dev); continue
            try:
                window = _np.array(list(buf)[-_SEQ2P_WIN:], dtype=_np.float32)
                mu = window.mean(); sigma = window.std() + 1e-6
                x  = ((window - mu) / sigma).reshape(1, -1).astype(_np.float32)
                out = sess.run(None, {sess.get_inputs()[0].name: x})
                pred = float(out[0][0][0]) * sigma + mu
                if pred > 5.0:
                    dev["engine_seq2point_w"] = round(pred, 1)
                    self._stats["seq2point_inferences"] += 1
                    cur_w = dev.get("current_power", 0.0) or 0.0
                    if cur_w > 0 and abs(pred - cur_w) / (cur_w + 1e-6) > 0.3:
                        dev["current_power"] = round(0.7*cur_w + 0.3*pred, 1)
                        self._stats["seq2point_corrections"] += 1
            except Exception as exc:
                _NILM_LOGGER.debug("Seq2Point fout (%s): %s", dtype, exc)
            result.append(dev)
        return result

    def _seq2p_load(self, device_type: str):
        if device_type in self._seq2p_tried: return self._seq2p_sessions.get(device_type)
        self._seq2p_tried.add(device_type)
        model_path = os.path.join(_ONNX_DIR, f"{device_type}.onnx")
        if not os.path.exists(model_path): return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, (_NILM_CORES) // 2)
            sess = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
            self._seq2p_sessions[device_type] = sess
            return sess
        except Exception as exc:
            _NILM_LOGGER.warning("Seq2Point laad-fout (%s): %s", device_type, exc)
            return None

    def _diag(self, devices, events, mode) -> dict:
        recent = [{"ts": round(e["ts"],1), "phase": e["phase"], "delta_w": e["delta_w"]} for e in list(self._recent_events)[:10]]
        baselines = {ph: round(k.estimate, 1) for ph, k in self._kalman.items()}
        noise     = {ph: round(k.noise_p80, 1) for ph, k in self._kalman.items()}
        confs = [float(d.get("confidence",0) or 0) for d in devices if d.get("source") not in ("smart_plug","injected")]
        avg_conf = round(sum(confs)/len(confs), 3) if confs else 0.0
        low_conf = sum(1 for c in confs if c < 0.4)
        g = self._guard.stats()
        return {
            "engine_version":            "1.21.0",
            "engine_mode":               mode.name,
            "engine_avg_confidence":     avg_conf,
            "engine_low_conf_devices":   low_conf,
            "engine_kalman_baselines_w": baselines,
            "engine_noise_p80_w":        noise,
            "engine_recent_events":      recent,
            "engine_scipy_events":       self._stats.get("scipy_events_up",0) + self._stats.get("scipy_events_down",0),
            "engine_fsm_transitions":    self._stats.get("fsm_transitions", 0),
            "engine_evidence_hints":     self._stats.get("evidence_hints", 0),
            "engine_overlap_rescales":   self._stats.get("overlap_rescales", 0),
            "engine_conf_adjustments":   self._stats.get("conf_adjustments", 0),
            "engine_cluster_retrains":   self._stats.get("cluster_retrains", 0),
            "engine_seq2point_infer":    self._stats.get("seq2point_inferences", 0),
            "engine_seq2point_models":   list(self._seq2p_sessions.keys()),
            "engine_cpu_mode":           g.get("current_mode", "?"),
            "engine_cpu_ewa_pct":        g.get("cpu_ewa_pct", 0.0),
            "engine_cpu_normalized_pct": g.get("cpu_normalized_pct", 0.0),
            "engine_cpu_peak_pct":       g.get("peak_cpu_pct", 0.0),
        }


class CloudEMSCoordinator(DataUpdateCoordinator):
    """Main coordinator for CloudEMS v1.4.1."""

    def __init__(self, hass: HomeAssistant, config: Dict):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_FAST),
        )
        self._config  = config
        self._session: Optional[aiohttp.ClientSession] = None

        self._store_devices = Store(hass, 1, STORAGE_KEY_NILM_DEVICES)
        self._store_energy  = Store(hass, 1, STORAGE_KEY_NILM_ENERGY)

        model_path = hass.config.path(".storage", "cloudems_models")
        os.makedirs(model_path, exist_ok=True)

        # v1.5: resolve AI provider (new field, with backward-compat fallback)
        ai_provider = config.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
        if ai_provider == AI_PROVIDER_NONE and config.get(CONF_OLLAMA_ENABLED, False):
            ai_provider = AI_PROVIDER_OLLAMA  # back-compat upgrade

        ollama_cfg = {
            "enabled": (ai_provider == AI_PROVIDER_OLLAMA),
            "host":    config.get(CONF_OLLAMA_HOST, "localhost"),
            "port":    config.get(CONF_OLLAMA_PORT, 11434),
            "model":   config.get(CONF_OLLAMA_MODEL, "llama3"),
        }

        self._ai_provider = ai_provider
        self._nilm_min_confidence = float(config.get(CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE))

        # v1.16: Ollama health-check state
        self._ollama_cfg = ollama_cfg
        self._ollama_health: dict = {
            "status": "unknown",
            "models_available": [],
            "active_model_found": False,
            "last_check_ts": None,
            "last_error": None,
        }
        self._ollama_health_last_check: float = 0.0

        self._nilm = NILMDetector(
            model_path=model_path,
            api_key=config.get(CONF_CLOUD_API_KEY),
            session=None,
            on_device_found=self._on_nilm_device_found,
            on_device_update=self._on_nilm_device_update,
            ollama_config=ollama_cfg,
            ai_provider=ai_provider,
            hass=hass,
        )
        self._nilm.set_stores(self._store_devices, self._store_energy)

        # v1.20: vertel NILM welke entity_ids geconfigureerde infrastructure-sensoren zijn
        # zodat die nooit als huishoudapparaat worden geclassificeerd.
        _config_eids: set = set()
        for _key in (
            "grid_sensor", "solar_sensor", "battery_sensor", "battery_soc_entity",
            "import_power_sensor", "export_power_sensor",
            "power_sensor_l1", "power_sensor_l2", "power_sensor_l3",
            "voltage_sensor_l1", "voltage_sensor_l2", "voltage_sensor_l3",
            "phase_sensors_L1", "phase_sensors_L2", "phase_sensors_L3",
            "gas_sensor", "gas_price_sensor",
            "heat_pump_power_entity", "heat_pump_thermal_entity",
            "ev_charger_entity",
        ):
            _v = config.get(_key, "")
            if _v:
                _config_eids.add(_v)
        for _inv in config.get("inverter_configs", []):
            if _inv.get("entity_id"):
                _config_eids.add(_inv["entity_id"])
        for _bc in config.get("battery_configs", []):
            for _bk in ("power_sensor", "soc_sensor", "charge_sensor", "discharge_sensor"):
                if _bc.get(_bk):
                    _config_eids.add(_bc[_bk])
        self._nilm.set_config_sensor_eids(_config_eids)

        self._prices: Optional[EnergyPriceFetcher] = None
        self._limiter = CurrentLimiter(
            max_current_per_phase=config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT),
            ev_charger_callback=self._set_ev_current,
            solar_inverter_callback=self._set_solar_curtailment,
        )
        self._calc = PowerCalculator(
            default_voltage=float(config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
        )

        self._prices_last_update: float = 0.0
        self._data: Dict = {}
        self._last_battery_w: float = 0.0  # v1.16: for consumption category correction
        self._last_p1_data: Dict = {}       # v1.17 fix: ensure always initialized
        self._acc_date: str = ""  # tracks date for pv_accuracy day rollover

        # Sub-modules
        self._dynamic_loader    = None
        self._phase_balancer    = None
        self._p1_reader         = None
        self._solar_learner     = None
        self._multi_inv_manager = None
        self._pv_forecast       = None
        self._peak_shaving      = None
        self._boiler_ctrl       = None
        self._learning_backup   = None  # v1.18.0: backup schrijfpad voor alle leerdata

        # v1.9: new sub-modules
        self._co2_fetcher:       Optional[object] = None
        self._battery_scheduler:    Optional[object] = None
        self._congestion_detector:  Optional[object] = None
        self._battery_degradation:  Optional[object] = None
        self._sensor_hints:         Optional[object] = None
        self._cost_forecaster:   Optional[object] = None
        # v1.10.3: self-learning intelligence modules
        self._home_baseline:     Optional[object] = None
        self._ev_session:        Optional[object] = None
        self._nilm_schedule:     Optional[object] = None

        # v1.11.0: 8 new intelligence features
        self._thermal_model:     Optional[object] = None
        self._self_consumption:  Optional[object] = None
        self._day_classifier:    Optional[object] = None
        self._device_drift:      Optional[object] = None
        self._pv_health:         Optional[object] = None
        self._micro_mobility:    Optional[object] = None
        self._notification_engine: Optional[object] = None
        self._clipping_loss:     Optional[object] = None
        self._categories:        Optional[object] = None
        self._shadow_detector:   Optional[object] = None

        # v1.8: EV PID controller
        self._ev_pid: Optional[object] = None
        # v1.8: PID auto-tuner state per controller
        self._phase_pid_tuners: dict = {}
        self._cost_today_eur  = 0.0
        self._cost_month_eur  = 0.0
        self._cost_day_key    = ""
        self._cost_month_key  = ""

        # Decision log (ring buffer)
        self._decision_log: deque = deque(maxlen=MAX_DECISION_LOG)
        # Insights text
        self._insights: str = ""
        # Per-inverter rolling power window for plateau/clipping detection
        self._plateau_windows: dict = {}  # entity_id → deque of float (plateau window)
        self._pre_windows: dict = {}      # entity_id → deque of float (pre-plateau slope window)
        # Per-inverter noise baseline: measured stddev/mean when NOT near ceiling.
        # Adapted over time — allows stricter clipping detection on smooth inverters.
        self._noise_baselines: dict = {}  # entity_id → EMA of stability ratio
        # Per-battery learned stats: {sensor_id: {max_charge_w, max_discharge_w, energy_accum_wh}}
        self._battery_learned: dict = {}

        # v1.15.0: new intelligence modules
        self._hp_cop:         Optional[object] = None
        self._sensor_ema:     Optional[object] = None
        self._sensor_sanity:  Optional[object] = None
        self._absence:        Optional[object] = None
        self._preheat:        Optional[object] = None
        self._pv_accuracy:    Optional[object] = None

        # v1.17: Hybride NILM
        self._hybrid: Optional[HybridNILM] = None

        # v1.21.0: CPU-adaptive NILM enhancer
        self._nilm_enhancer = _NilmEnhancer()

    # ── Public helpers ────────────────────────────────────────────────────────

    @property
    def nilm(self) -> NILMDetector:
        return self._nilm

    @property
    def phase_currents(self) -> dict[str, float]:
        return self._limiter.phase_currents

    # ── v1.5: Helpers ─────────────────────────────────────────────────────────

    def _enrich_price_info(self, price_info: dict) -> dict:
        """Add prev_hour_price, rank_today and is_cheap_hour to price_info dict."""
        if not price_info or not self._prices:
            return price_info
        # Use today_all from prices.py (already has hour int) if available
        # Fallback: use raw _today_slots() and extract hour via _aware()
        today_all = price_info.get("today_all", [])
        cur = price_info.get("current")

        # Previous hour price — find slot whose hour == (now - 1)
        prev = None
        try:
            from datetime import datetime, timezone
            now    = datetime.now(timezone.utc)
            prev_h = (now.hour - 1) % 24
            if today_all:
                # today_all has "hour" int key (from prices.py v1.6+)
                prev_slot = next((s for s in today_all if s.get("hour") == prev_h), None)
                if prev_slot:
                    prev = prev_slot.get("price")
            else:
                # Fallback to raw slots from _today_slots() using datetime
                for s in self._prices._today_slots():
                    slot_hour = self._prices._aware(s["start"]).hour
                    if slot_hour == prev_h:
                        prev = float(s["price"])
                        break
        except Exception:
            pass

        # Rank of current price among today's hours (1 = cheapest)
        rank = None
        prices_today = [s["price"] for s in today_all] if today_all else []
        if not prices_today:
            prices_today = [float(s["price"]) for s in self._prices._today_slots()]
        if cur is not None and prices_today:
            sorted_prices = sorted(prices_today)
            rank = next((i + 1 for i, p in enumerate(sorted_prices) if p >= cur - 0.0001), None)

        # Is this a cheap hour? (below avg)
        is_cheap = False
        if cur is not None and price_info.get("avg_today") is not None:
            is_cheap = cur < price_info["avg_today"]

        return {
            **price_info,
            "prev_hour_price": prev,
            "rank_today":      rank,
            "is_cheap_hour":   is_cheap,
        }

    def _apply_price_components(self, price_info: dict) -> dict:
        """Add tax/BTW/supplier markup fields to price_info without changing the base EPEX price."""
        cfg     = self._config
        country = cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL")

        include_tax  = bool(cfg.get(CONF_PRICE_INCLUDE_TAX, False))
        include_btw  = bool(cfg.get(CONF_PRICE_INCLUDE_BTW, False))
        supplier_key = cfg.get(CONF_SELECTED_SUPPLIER, "none")
        custom_markup = float(cfg.get(CONF_SUPPLIER_MARKUP, 0.0))

        tax  = ENERGY_TAX_PER_COUNTRY.get(country, 0.0)
        vat  = VAT_RATE_PER_COUNTRY.get(country, 0.21)
        suppliers  = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"])
        sup_markup = suppliers.get(supplier_key, ("", 0.0))[1]
        if supplier_key == "custom":
            sup_markup = custom_markup

        def _enrich(base):
            tax_c   = tax if include_tax else 0.0
            sub     = base + tax_c + sup_markup
            btw_c   = sub * vat if include_btw else 0.0
            all_in  = sub + btw_c
            return round(all_in, 5)

        cur = price_info.get("current")
        today_display = []
        for slot in price_info.get("today_all", []):
            today_display.append({**slot,
                "price_display": _enrich(slot["price"]),
                "price_all_in":  _enrich(slot["price"])})

        return {
            **price_info,
            "tax_per_kwh":         round(tax, 5),
            "vat_rate":            round(vat, 4),
            "supplier_markup_kwh": round(sup_markup, 5),
            "price_include_tax":   include_tax,
            "price_include_btw":   include_btw,
            "country":             country,
            "current_all_in":      _enrich(cur) if cur is not None else None,
            "current_display":     _enrich(cur) if cur is not None else cur,
            "today_all_display":   today_display,
        }


    def _build_ai_status(self) -> dict:
        """Build AI/NILM status dict for the AI Status sensor."""
        devices   = self._nilm.get_devices()
        confirmed = sum(1 for d in devices if getattr(d, "confirmed", False))
        solar_peak_w = 0.0
        solar_profiles = 0
        if self._solar_learner:
            profiles = self._solar_learner.get_all_profiles()
            solar_profiles = len(profiles)
            solar_peak_w   = sum(p.peak_power_w for p in profiles)
        cloud_ai = getattr(self._nilm, "_cloud_ai", None)
        return {
            "call_count":      getattr(cloud_ai, "call_count", 0) if cloud_ai else 0,
            "available":       getattr(cloud_ai, "is_available", True) if cloud_ai else True,
            "min_confidence":  self._nilm_min_confidence,
            "confirmed_count": confirmed,
            "total_devices":   len(devices),
            "solar_profiles":  solar_profiles,
            "solar_peak_w":    round(solar_peak_w, 0),
        }

    async def async_check_ollama_health(self) -> None:
        """Ping Ollama /api/tags to verify connectivity and model availability. v1.16"""
        import time as _t, aiohttp as _aio
        from datetime import datetime, timezone

        cfg   = self._ollama_cfg
        host  = cfg.get("host", "localhost")
        port  = cfg.get("port", 11434)
        model = cfg.get("model", "llama3")
        url   = f"http://{host}:{port}/api/tags"

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        try:
            async with _aio.ClientSession() as s:
                async with s.get(url, timeout=_aio.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data   = await r.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        found  = any(model in m for m in models)
                        self._ollama_health = {
                            "status":              "online",
                            "models_available":    models,
                            "active_model":        model,
                            "active_model_found":  found,
                            "last_check_ts":       now_iso,
                            "last_error":          None,
                        }
                        _LOGGER.debug("Ollama health OK — modellen: %s", models)
                    else:
                        self._ollama_health.update({
                            "status":       "error",
                            "last_check_ts": now_iso,
                            "last_error":   f"HTTP {r.status}",
                        })
        except _aio.ClientConnectorError:
            self._ollama_health.update({
                "status":       "offline",
                "last_check_ts": now_iso,
                "last_error":   f"Kan niet verbinden met {host}:{port}",
            })
        except Exception as exc:  # noqa: BLE001
            self._ollama_health.update({
                "status":       "error",
                "last_check_ts": now_iso,
                "last_error":   str(exc),
            })
        self._ollama_health_last_check = _t.time()

    def confirm_nilm_device(self, device_id: str, name: str = "", device_type: str = "") -> None:
        """Confirm a NILM-detected device with optional corrected name/type."""
        from .const import NILM_FEEDBACK_CORRECT
        self._nilm.set_feedback(device_id, NILM_FEEDBACK_CORRECT,
                                corrected_name=name, corrected_type=device_type)

    def dismiss_nilm_device(self, device_id: str) -> None:
        self._nilm.dismiss_device(device_id)

    def set_nilm_feedback(self, device_id: str, feedback: str,
                          corrected_name: str = "", corrected_type: str = "") -> None:
        self._nilm.set_feedback(device_id, feedback, corrected_name, corrected_type)

    def rename_nilm_device(self, device_id: str, name: str, device_type: str = "") -> None:
        """Rename a NILM-detected device. Optionally correct the device type too.

        v1.20: dedicated rename method — does not change feedback/confidence,
        only updates the display name (and optionally type) the user sees.
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS rename_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_name = name.strip()[:60]  # max 60 chars
        if device_type:
            dev.user_type = device_type.strip()
        _LOGGER.info("CloudEMS NILM: renamed '%s' → '%s'", device_id, dev.user_name)

    def hide_nilm_device(self, device_id: str, hidden: bool = True) -> None:
        """Hide or unhide a NILM device from the dashboard and sensors.

        v1.20: hidden devices are excluded from get_devices_for_ha() but
        remain in storage so they can be un-hidden later.
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS hide_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_hidden = hidden
        _LOGGER.info("CloudEMS NILM: device '%s' hidden=%s", device_id, hidden)

    def assign_device_to_room(self, device_id: str, room_name: str) -> None:
        """Manually assign a NILM device to a room for the virtual room meter.

        v1.20: Overrides auto-detected room. Use empty room_name to clear override.
        """
        if hasattr(self, "_room_meter") and self._room_meter:
            self._room_meter.assign_device_to_room(device_id, room_name)

    def suppress_nilm_device(self, device_id: str) -> None:
        """Decline/suppress a NILM device — never show again.

        v1.20: User-visible 'Decline' button. Keeps the record in storage so the
        NILM algorithm knows not to resurface this detection, but hides it from all
        dashboards and sensors. Sets user_feedback='incorrect' so it also improves
        future NILM training (negative example).
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS suppress_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_suppressed = True
        dev.user_feedback   = "incorrect"
        dev.confirmed       = False
        _LOGGER.info("CloudEMS NILM: device '%s' declined/suppressed by user", device_id)

    async def async_shutdown(self) -> None:
        """Called by __init__.py on unload. Flush all dirty learning data before exit."""
        # Flush every learning module that tracks dirty state
        flush_targets = [
            self._solar_learner,
            self._pv_forecast,
            self._clipping_loss,
            self._shadow_detector,
            self._pv_health,
            self._device_drift,
            self._micro_mobility,
            self._notification_engine,
            self._categories,
            self._cost_forecaster,
            self._thermal_model,
            self._self_consumption,
            self._day_classifier,
            self._pv_accuracy,
            getattr(self, "_home_baseline", None),
            getattr(self, "_ev_session", None),
            getattr(self, "_nilm_schedule", None),
            getattr(self, "_gas_analysis", None),
            getattr(self, "_battery_degradation", None),
            getattr(self, "_sensor_hints", None),
            getattr(self, "_room_meter", None),          # v1.20
        ]
        for module in flush_targets:
            if module is None:
                continue
            for method_name in ("async_maybe_save", "async_save", "_async_save"):
                method = getattr(module, method_name, None)
                if callable(method):
                    try:
                        await method()
                    except Exception:  # noqa: BLE001
                        pass
                    break  # only call the first available save method

        if self._session and not self._session.closed:
            await self._session.close()
        if self._p1_reader:
            try:
                await self._p1_reader.async_stop()
            except Exception:  # noqa: BLE001
                pass

        # Geforceerde backup-flush bij nette afsluiting
        backup = getattr(self, "_learning_backup", None)
        if backup is not None:
            modules_data = {}
            if self._solar_learner:
                modules_data["solar_learner"] = self._solar_learner._build_save_data()
            if self._pv_forecast:
                pv_data = {}
                for eid, p in self._pv_forecast._profiles.items():
                    pv_data[eid] = {
                        "learned_azimuth":       p.learned_azimuth,
                        "learned_tilt":          p.learned_tilt,
                        "orientation_confident": p.orientation_confident,
                        "clear_sky_samples":     p.clear_sky_samples,
                        "hourly_yield_fraction": p.hourly_yield_fraction,
                        "peak_wp":               p._peak_wp,
                        "calib_factor":          p._calib_factor,
                        "calib_samples":         p._calib_samples,
                    }
                modules_data["pv_forecast"] = pv_data
            if modules_data:
                await backup.async_flush_all(modules_data)

        _LOGGER.info("CloudEMS coordinator shut down")

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self):
        self._session = aiohttp.ClientSession()
        self._nilm._cloud_ai._session = self._session
        await self._nilm.async_load()

        # ── LearningBackup: tweede schrijfpad voor alle leerdata ──────────────
        from .energy_manager.learning_backup import LearningBackup
        self._learning_backup = LearningBackup(self.hass)
        await self._learning_backup.async_setup()

        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        self._prices = EnergyPriceFetcher(
            country=country,
            session=self._session,
            api_key=self._config.get(CONF_CLOUD_API_KEY),
        )
        await self._prices.update()

        cfg = self._config

        # v1.9: CO2 intensity (always active — uses static defaults without key)
        from .energy.co2 import CO2IntensityFetcher
        self._co2_fetcher = CO2IntensityFetcher(
            country = cfg.get("co2_country", cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL")),
            session = self._session,
        )
        await self._co2_fetcher.update()

        # v1.9: Cost forecaster (always active — self-trains over time)
        from .energy_manager.cost_forecaster import EnergyCostForecaster
        self._cost_forecaster = EnergyCostForecaster(self.hass)
        await self._cost_forecaster.async_setup()

        # v1.10.3: always-on self-learning modules (zero config)
        self._home_baseline = HomeBaselineLearner(self.hass)
        await self._home_baseline.async_setup()

        self._ev_session = EVSessionLearner(self.hass)
        await self._ev_session.async_setup()

        self._nilm_schedule = NILMScheduleLearner(self.hass)
        await self._nilm_schedule.async_setup()

        # v1.11.0: Thermal house model (always active — needs outside_temp + heating power)
        from .energy_manager.thermal_model import ThermalHouseModel
        self._thermal_model = ThermalHouseModel(self.hass)
        await self._thermal_model.async_setup()

        # v1.11.0: Self-consumption ratio tracker
        from .energy_manager.self_consumption import SelfConsumptionTracker
        self._self_consumption = SelfConsumptionTracker(self.hass)
        await self._self_consumption.async_setup()

        # v1.11.0: Day-type classifier
        from .energy_manager.day_classifier import DayTypeClassifier
        self._day_classifier = DayTypeClassifier(self.hass)
        await self._day_classifier.async_setup()

        # v1.11.0: Device efficiency drift tracker
        from .energy_manager.device_drift import DeviceDriftTracker
        self._device_drift = DeviceDriftTracker(self.hass)
        await self._device_drift.async_setup()

        # v1.11.0: PV health monitor (soiling/degradation detection)
        from .energy_manager.pv_health import PVHealthMonitor
        self._pv_health = PVHealthMonitor(self.hass)
        await self._pv_health.async_setup()

        # v1.11.0: Micro-mobility tracker (e-bikes, scooters)
        from .energy_manager.micro_mobility import MicroMobilityTracker
        self._micro_mobility = MicroMobilityTracker(self.hass)
        await self._micro_mobility.async_setup()

        # v1.12.0: Notification engine
        self._notification_engine = NotificationEngine(self.hass, cfg)
        await self._notification_engine.async_setup()

        # v1.12.0: Clipping verlies calculator
        from .energy_manager.clipping_loss import ClippingLossCalculator
        self._clipping_loss = ClippingLossCalculator(self.hass)
        await self._clipping_loss.async_setup()

        # v1.16.0: Structurele schaduwdetector
        from .energy_manager.shadow_detector import ShadowDetector
        self._shadow_detector = ShadowDetector(self.hass)
        await self._shadow_detector.async_setup()

        # v1.12.0: Verbruik categorieën tracker
        from .energy_manager.consumption_categories import ConsumptionCategoryTracker
        self._categories = ConsumptionCategoryTracker(self.hass)
        await self._categories.async_setup()

        # v1.20: Virtuele stroommeter per kamer
        from .energy_manager.room_meter import RoomMeterEngine
        self._room_meter = RoomMeterEngine(self.hass)
        await self._room_meter.async_setup()

        # v1.20: Goedkope uren schakelaar planner
        from .energy_manager.cheap_switch_scheduler import CheapSwitchScheduler
        _cheap_switch_cfgs = cfg.get("cheap_switches", []) or []
        self._cheap_switch_scheduler = CheapSwitchScheduler(self.hass, _cheap_switch_cfgs)

        # v1.9: Battery EPEX scheduler (only when battery entities configured)
        if cfg.get("battery_scheduler_enabled", False) or cfg.get("battery_soc_entity"):
            from .energy_manager.battery_scheduler import BatteryEPEXScheduler
            self._battery_scheduler = BatteryEPEXScheduler(self.hass, cfg)
            await self._battery_scheduler.async_setup()

        # v1.10: Grid congestion detector (always active if threshold configured)
        if cfg.get("congestion_threshold_w") or cfg.get("congestion_enabled", True):
            from .energy_manager.grid_congestion import GridCongestionDetector
            self._congestion_detector = GridCongestionDetector(self.hass, cfg)
            await self._congestion_detector.async_setup()

        # v1.10: Battery degradation tracker (active if SoC entity configured)
        if cfg.get("battery_soc_entity"):
            from .energy_manager.battery_degradation import BatteryDegradationTracker
            self._battery_degradation = BatteryDegradationTracker(self.hass, cfg)
            await self._battery_degradation.async_setup()

        # v1.10: NILM remote feed (non-blocking background refresh)
        await self._nilm._db.async_setup(self.hass)
        _LOGGER.info("CloudEMS: BatteryEPEXScheduler actief")

        # v1.10.2: Sensor hint engine (passive pattern observer)
        from .energy_manager.sensor_hint import SensorHintEngine
        self._sensor_hints = SensorHintEngine(self.hass, cfg)
        await self._sensor_hints.async_setup()

        # v1.8: EV PID controller (runs alongside DynamicLoader)
        from .energy_manager.dynamic_ev_charger import EVChargingPIDController
        from .const import (DEFAULT_PID_EV_KP, DEFAULT_PID_EV_KI, DEFAULT_PID_EV_KD,
                            CONF_PID_EV_KP, CONF_PID_EV_KI, CONF_PID_EV_KD,
                            MIN_EV_CURRENT, MAX_EV_CURRENT)
        self._ev_pid = EVChargingPIDController(
            min_a  = MIN_EV_CURRENT,
            max_a  = MAX_EV_CURRENT,
            kp     = float(cfg.get(CONF_PID_EV_KP, DEFAULT_PID_EV_KP)),
            ki     = float(cfg.get(CONF_PID_EV_KI, DEFAULT_PID_EV_KI)),
            kd     = float(cfg.get(CONF_PID_EV_KD, DEFAULT_PID_EV_KD)),
        )
        if cfg.get(CONF_DYNAMIC_LOADING, False):
            self._ev_pid.enable(True)

        if cfg.get(CONF_PHASE_BALANCE, False):
            from .energy_manager.phase_balancer import PhaseBalancer
            self._phase_balancer = PhaseBalancer(self.hass, cfg)

        if cfg.get(CONF_P1_ENABLED, False):
            from .energy_manager.p1_reader import P1Reader
            self._p1_reader = P1Reader(cfg)
            await self._p1_reader.async_start()

        if cfg.get(CONF_PEAK_SHAVING_ENABLED, False):
            from .energy_manager.peak_shaving import PeakShaving
            self._peak_shaving = PeakShaving(self.hass, cfg)
            await self._peak_shaving.async_setup()

        # Boiler controller
        boiler_configs = cfg.get("boiler_configs", [])
        if boiler_configs:
            from .energy_manager.boiler_controller import BoilerController
            self._boiler_ctrl = BoilerController(self.hass, boiler_configs)
            await self._boiler_ctrl.async_setup()
            _LOGGER.info("CloudEMS: BoilerController actief (%d boilers)", len(boiler_configs))

        # Solar Learner + Multi-Inverter + PV Forecast
        inverter_configs = cfg.get(CONF_INVERTER_CONFIGS, [])
        if inverter_configs:
            from .energy_manager.solar_learner import SolarPowerLearner
            self._solar_learner = SolarPowerLearner(self.hass, inverter_configs)
            await self._solar_learner.async_setup(backup=getattr(self, "_learning_backup", None))

            if cfg.get(CONF_ENABLE_MULTI_INVERTER, False):
                from .energy_manager.multi_inverter_manager import MultiInverterManager, InverterControl
                controls = [
                    InverterControl(
                        entity_id    =inv["entity_id"],
                        control_entity=inv.get("control_entity", inv["entity_id"]),
                        label        =inv.get("label",""),
                        priority     =int(inv.get("priority",1)),
                        min_power_pct=float(inv.get("min_power_pct",0.0)),
                    ) for inv in inverter_configs
                ]
                max_phase_a = {
                    phase: float(cfg.get(f"max_current_{phase.lower()}", DEFAULT_MAX_CURRENT))
                    for phase in ALL_PHASES
                }
                self._multi_inv_manager = MultiInverterManager(
                    hass=self.hass, entry=None,
                    inverter_controls=controls,
                    learner=self._solar_learner,
                    max_phase_currents=max_phase_a,
                    negative_price_threshold=float(cfg.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)),
                )
                await self._multi_inv_manager.async_setup()

            from .energy_manager.pv_forecast import PVForecast
            self._pv_forecast = PVForecast(
                hass=self.hass,
                inverter_configs=inverter_configs,
                latitude =self.hass.config.latitude  or 52.1,
                longitude=self.hass.config.longitude or 5.3,
                session  =self._session,
            )
            await self._pv_forecast.async_setup(backup=getattr(self, "_learning_backup", None))

        # v1.15.0: EMA smoothing + sanity guard (always active)
        self._sensor_ema    = SensorEMALayer()
        self._sensor_sanity = SensorSanityGuard(self._config)
        # v1.15.0: Absence detector + climate preheat advisor
        self._absence = AbsenceDetector(self.hass)
        self._preheat = ClimatePreHeatAdvisor()
        # v1.15.0: PV forecast accuracy tracker
        self._pv_accuracy = PVForecastAccuracyTracker(self.hass)
        await self._pv_accuracy.async_setup()
        # v1.15.0: Heat pump COP learner
        self._hp_cop = HeatPumpCOPLearner(self.hass)
        await self._hp_cop.async_setup()

        # v1.17: Hybride NILM — auto-discovery + contextpriors + 3-fase balans
        self._hybrid = HybridNILM(self.hass, self._config)
        await self._hybrid.async_setup()
        # Koppel hybride laag aan de NILM-detector
        self._nilm._hybrid = self._hybrid
        _LOGGER.info("CloudEMS HybridNILM geïntegreerd")

    # ── Update loop ───────────────────────────────────────────────────────────

    async def _async_update_data(self) -> Dict:
        try:
            data = await self._gather_power_data()
            await self._process_power_data(data)
            await self._limiter.evaluate_and_act()

            if time.time() - self._prices_last_update > EPEX_UPDATE_INTERVAL:
                await self._prices.update()
                self._prices_last_update = time.time()

            # v1.16: Ollama health-check every 60 s (only when Ollama is configured)
            if self._ollama_cfg.get("enabled") and time.time() - self._ollama_health_last_check > 60:
                await self.async_check_ollama_health()

            if self._config.get(CONF_ENABLE_SOLAR_DIMMER, False):
                threshold = float(self._config.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD))
                is_neg    = self._prices.is_negative_price(threshold) if self._prices else False
                self._limiter.set_negative_price_mode(is_neg)

            current_price = self._prices.current_price if self._prices else 0.0

            # v1.15.0: contract type — dynamic (EPEX) or fixed tariff
            from .const import (CONF_CONTRACT_TYPE, CONTRACT_TYPE_FIXED,
                                DEFAULT_CONTRACT_TYPE, CONF_FIXED_IMPORT_PRICE, CONF_FIXED_EXPORT_PRICE)
            contract_type = self._config.get(CONF_CONTRACT_TYPE, DEFAULT_CONTRACT_TYPE)

            if contract_type == CONTRACT_TYPE_FIXED:
                # Fixed tariff: build synthetic price_info without EPEX
                fixed_import = float(self._config.get(CONF_FIXED_IMPORT_PRICE, 0.25))
                fixed_export = float(self._config.get(CONF_FIXED_EXPORT_PRICE, 0.09))
                import datetime as _dt
                now_h = _dt.datetime.now().hour
                # Flat 24-hour schedule at fixed price
                today_all = [
                    {"hour": h, "price": fixed_import, "is_cheap": True} for h in range(24)
                ]
                price_info = {
                    "current":        fixed_import,
                    "feed_in":        fixed_export,
                    "avg_today":      fixed_import,
                    "today_all":      today_all,
                    "contract_type":  CONTRACT_TYPE_FIXED,
                    "is_cheap_hour":  True,
                }
            else:
                # EPEX price info (FIX: get_price_info() now exists)
                price_info: dict = self._prices.get_price_info() if self._prices else {}
                price_info["contract_type"] = CONTRACT_TYPE_FIXED if contract_type == CONTRACT_TYPE_FIXED else "dynamic"

            # v1.13.0: apply tax/BTW/markup to produce all-in price fields
            price_info = self._apply_price_components(price_info)

            # Dynamic loader (threshold-based, keeps running for price logic)
            ev_decision = {}
            if self._dynamic_loader:
                ev_decision = await self._dynamic_loader.async_evaluate(
                    price_eur_kwh  =current_price,
                    solar_surplus_w=data.get("solar_power", 0.0),
                    max_current_a  =float(self._config.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT)),
                )

            # v1.18.1: EV zonnepiek-planning — plan laden op verwacht PV-piek
            ev_solar_plan: dict = {}
            _ev_fc = locals().get('pv_forecast_hourly') or []  # may not be set yet
            if self._ev_pid and _ev_fc:
                try:
                    now_h = datetime.now(timezone.utc).hour
                    # Zoek het uur met de hoogste verwachte PV-opbrengst vandaag
                    future_hours = [h for h in _ev_fc if h.get("hour", 0) >= now_h]
                    if future_hours:
                        # Aggregeer per uur over alle omvormers
                        by_hour: dict[int, float] = {}
                        for h in future_hours:
                            hr = h.get("hour", 0)
                            by_hour[hr] = by_hour.get(hr, 0.0) + h.get("forecast_w", 0.0)
                        best_hour = max(by_hour, key=lambda k: by_hour[k])
                        best_w    = by_hour[best_hour]
                        ev_solar_plan = {
                            "best_hour":    best_hour,
                            "best_w":       round(best_w, 0),
                            "hours_until":  best_hour - now_h,
                            "advice": (
                                f"Optimaal EV-laadmoment vandaag: {best_hour}:00 "
                                f"(verwacht {best_w:.0f}W PV)"
                            ) if best_w > 500 else "",
                        }
                        # Log als advies
                        if best_w > 1000 and best_hour != now_h:
                            self._log_decision(
                                "ev_solar_plan",
                                f"☀️ EV zonneplanning: optimum om {best_hour}:00 "
                                f"({best_w:.0f}W verwacht)"
                            )
                except Exception:
                    pass

            # v1.8: EV PID controller — smooth solar surplus tracking
            ev_pid_state = {}
            if self._ev_pid and self._ev_pid._enabled:
                grid_w  = data.get("grid_power", 0.0)
                new_a   = self._ev_pid.compute(grid_w)
                if new_a is not None:
                    await self._set_ev_current(new_a)
                    self._log_decision("ev_pid",
                        f"🔋 EV PID: {new_a:.1f}A (netto {grid_w:.0f}W)")
                ev_pid_state = self._ev_pid.pid_state

            # Phase balancer
            balance_data = {}
            if self._phase_balancer:
                status = await self._phase_balancer.async_check(self._limiter.phase_currents)
                balance_data = {
                    "imbalance_a":      status.imbalance_a,
                    "balanced":         status.balanced,
                    "overloaded_phase": status.overloaded_phase,
                    "recommendation":   status.recommendation,
                    "phase_currents":   status.phase_currents,
                }

            # P1 reader
            p1_data = {}
            if self._p1_reader and self._p1_reader.available:
                t = self._p1_reader.latest
                p1_data = {
                    "net_power_w":    t.net_power_w,
                    "power_import_w": t.power_import_w,
                    "power_export_w": t.power_export_w,
                    "current_l1": t.current_l1,
                    "current_l2": t.current_l2,
                    "current_l3": t.current_l3,
                    # Tariff-split energy totals (kWh meter readings)
                    "energy_import_kwh":    t.energy_import_kwh,
                    "energy_import_t1_kwh": t.energy_import_t1_kwh,
                    "energy_import_t2_kwh": t.energy_import_t2_kwh,
                    "energy_export_kwh":    t.energy_export_kwh,
                    "energy_export_t1_kwh": t.energy_export_t1_kwh,
                    "energy_export_t2_kwh": t.energy_export_t2_kwh,
                    "tariff": t.tariff,
                    # Per-phase import power (W, DSMR5)
                    "power_l1_import_w": t.power_l1_w,
                    "power_l2_import_w": t.power_l2_w,
                    "power_l3_import_w": t.power_l3_w,
                    # Per-phase export power (W, DSMR5)
                    "power_l1_export_w": t.power_l1_export_w,
                    "power_l2_export_w": t.power_l2_export_w,
                    "power_l3_export_w": t.power_l3_export_w,
                }
                # v1.9: P1 per-phase power → NILM (highest quality input)
                # DSMR5 telegrams include per-phase import power in kW
                # P1Telegram fields: power_l1_import_w, power_l2_import_w, power_l3_import_w
                for ph, attr in (("L1","power_l1_import_w"),("L2","power_l2_import_w"),("L3","power_l3_import_w")):
                    pw = getattr(t, attr, None)
                    if pw is not None and pw >= 0:
                        self._nilm.update_power(ph, pw, source="p1_direct")
                # Also feed per-phase from current × voltage if power not in telegram (DSMR4)
                mains_v = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
                if getattr(t, "current_l1", None) is not None and not getattr(t, "power_l1_import_w", None):
                    for ph, amp in (("L1", t.current_l1),("L2", t.current_l2),("L3", t.current_l3)):
                        if amp is not None:
                            self._nilm.update_power(ph, amp * mains_v, source="p1_i*u")

            # Store latest P1 data so _process_power_data can use it as fallback
            # for phase voltage derivation (U = P/I) when no dedicated sensors configured.
            self._last_p1_data = p1_data

            # v1.15.1: inject battery directly into NILM (prevents false edge detection)
            batt_configs = self._config.get("battery_configs", [])
            total_battery_w = 0.0
            for bc in batt_configs:
                b_eid = bc.get("power_sensor", "")
                b_raw = self._read_state(b_eid) if b_eid else None
                if b_raw is not None:
                    bw = self._calc.to_watts(b_eid, b_raw)
                    total_battery_w += (bw or 0.0)
            if abs(total_battery_w) > 50:
                self._nilm.inject_battery(total_battery_w, "Thuisbatterij")
            # v1.16: persist so consumption categories can subtract battery from totals
            self._last_battery_w = total_battery_w

            # Solar learner + PV forecast
            inverter_data      = []
            pv_forecast_kwh         = None
            pv_forecast_tomorrow_kwh = None
            pv_forecast_hourly: list = []
            pv_forecast_hourly_tomorrow: list = []

            # v1.18.1: stroomuitval-detectie
            _outage_detected = False
            _outage_message  = ""
            if not hasattr(self, '_outage_streak'):
                self._outage_streak = 0
                self._outage_active = False
            inverter_profiles:  list = []

            if self._solar_learner:
                await self._solar_learner.async_update(phase_currents=self._limiter.phase_currents)

                # Build inverter data: peak, clipping, utilisation — for sensors/diagnostics
                # Merge pv_forecast orientation data
                forecast_profiles: dict = {}
                if self._pv_forecast:
                    for fp in self._pv_forecast.get_all_profiles():
                        forecast_profiles[fp["inverter_id"]] = fp

                def _azimuth_compass(az):
                    if az is None:
                        return "onbekend"
                    dirs = ["N","NNO","NO","ONO","O","OZO","ZO","ZZO",
                            "Z","ZZW","ZW","WZW","W","WNW","NW","NNW"]
                    return dirs[round(az / 22.5) % 16]

                for eid, profile in {p.inverter_id: p for p in self._solar_learner.get_all_profiles()}.items():
                    raw = self._read_state(eid)
                    cur_w = self._calc.to_watts(eid, raw) if raw is not None else 0.0
                    peak_w = profile.peak_power_w
                    util   = round(cur_w / peak_w * 100, 1) if peak_w > 0 else 0.0

                    # ── Plateau-based clipping detection ─────────────────────
                    # Clipping = inverter output is FLAT at its hardware limit.
                    # Strategy (in priority order):
                    #  1. Use self-learned ceiling from ClippingLossCalculator
                    #     (most accurate: actual observed plateau, not a fraction)
                    #  2. Fall back to rated_power_w from config (if set)
                    #  3. Fall back to peak_power_w_7d (only after 50+ samples,
                    #     conservative fraction to avoid false positives)
                    inv_cfg = next(
                        (c for c in self._config.get(CONF_INVERTER_CONFIGS, []) if c.get("entity_id") == eid),
                        {}
                    )
                    rated_w = inv_cfg.get("rated_power_w") or None

                    # Try to get self-learned ceiling first
                    learned_ceiling_w: Optional[float] = None
                    if self._clipping_loss:
                        learned_ceiling_w = self._clipping_loss.get_learned_ceiling(eid)

                    # Ceiling priority:
                    #   1. rated_power_w from config (user-configured, most reliable)
                    #   2. Self-learned ceiling (accumulated from confirmed plateau events)
                    #   3. No fallback to peak_power_w_7d — that is already the clipped
                    #      observed peak, using it as ceiling causes circular false positives.
                    if rated_w:
                        clipping_ceiling = rated_w
                    elif learned_ceiling_w:
                        clipping_ceiling = learned_ceiling_w
                    else:
                        clipping_ceiling = None  # not enough info — skip detection

                    # Maintain a combined window: pre-plateau (slope) + plateau readings.
                    # Total size = PLATEAU_PRE_SIZE + PLATEAU_WINDOW_SIZE so the oldest
                    # PLATEAU_PRE_SIZE values form the "was it rising?" reference.
                    total_win_size = PLATEAU_WINDOW_SIZE + PLATEAU_PRE_SIZE
                    win = self._plateau_windows.setdefault(
                        eid, deque(maxlen=total_win_size)
                    )
                    if cur_w > 0:
                        win.append(cur_w)

                    clipping = False
                    if clipping_ceiling and len(win) >= total_win_size:
                        pre_win     = list(win)[:PLATEAU_PRE_SIZE]   # older readings (slope)
                        plateau_win = list(win)[PLATEAU_PRE_SIZE:]   # recent readings (flat?)

                        plateau_mean = sum(plateau_win) / len(plateau_win)
                        variance     = sum((x - plateau_mean) ** 2 for x in plateau_win) / len(plateau_win)
                        stddev_w     = variance ** 0.5
                        stability    = stddev_w / plateau_mean if plateau_mean > 0 else 1.0

                        pre_mean = sum(pre_win) / len(pre_win)

                        # Adaptive stability threshold per inverter noise floor
                        baseline_stability = self._noise_baselines.get(eid, PLATEAU_STABILITY_PCT)
                        adaptive_threshold = max(PLATEAU_STABILITY_PCT, baseline_stability * 1.5)

                        # Update noise baseline when well below ceiling (not in clipping zone)
                        if plateau_mean < clipping_ceiling * 0.70:
                            prev = self._noise_baselines.get(eid, stability)
                            self._noise_baselines[eid] = prev * 0.95 + stability * 0.05

                        # Three conditions must all be true:
                        #   A. Recent window is flat (parabola top is cut off)
                        #   B. Flat level is close to the configured/learned ceiling
                        #   C. The readings BEFORE the plateau were still rising
                        #      (pre_mean < plateau_mean * ratio) — confirms it is a
                        #      parabola cut, not just a cloud or stable low production
                        rising_before = pre_mean < plateau_mean * PLATEAU_RISE_MAX_RATIO
                        if (stability < adaptive_threshold
                                and plateau_mean >= clipping_ceiling * CLIPPING_CEILING_FRAC
                                and rising_before):
                            clipping = True

                    if clipping:
                        msg = (f"\u26a0\ufe0f Clipping: {profile.label} produceert {cur_w:.0f}W "
                               f"= {util:.0f}% van max {peak_w:.0f}W \u2014 "
                               f"panelen leveren meer dan omvormer aankan")
                        self._log_decision("clipping", msg)

                    fp = forecast_profiles.get(eid, {})
                    azimuth   = fp.get("azimuth_deg")
                    tilt      = fp.get("tilt_deg")
                    az_learned  = fp.get("learned_azimuth")
                    ti_learned  = fp.get("learned_tilt")
                    or_confident = fp.get("orientation_confident", False)
                    clear_sky_samples = fp.get("clear_sky_samples", 0)
                    from .energy_manager.pv_forecast import MIN_ORIENTATION_SAMPLES as _ORI_NEEDED
                    samples_needed = _ORI_NEEDED
                    hourly_yield = fp.get("hourly_yield_fraction", {})
                    learn_pct = round(min(100, clear_sky_samples / _ORI_NEEDED * 100), 0)
                    peak_hour = int(max(hourly_yield, key=lambda h: hourly_yield[h])) if hourly_yield else None

                    # Use provisional learned values immediately (even before confident)
                    # so the dashboard shows a rough estimate rather than "onbekend"
                    azimuth_eff = azimuth if azimuth is not None else az_learned
                    tilt_eff    = tilt    if tilt    is not None else ti_learned

                    votes = profile.phase_votes or {}
                    total_votes = sum(votes.values()) if isinstance(votes, dict) else 0

                    # Phase best-guess: show provisional L1/L2/L3 with confidence
                    # even before phase_certain is reached
                    _sl_prof = self._solar_learner.get_profile(eid) if self._solar_learner else None
                    if _sl_prof:
                        _pdf = self._solar_learner._phase_display_fields(_sl_prof)
                        _phase_display = _pdf["phase_display"]
                        _phase_conf    = _pdf["phase_confidence"]
                        _phase_prov    = _pdf["phase_provisional"]
                    else:
                        _phase_display = None
                        _phase_conf    = 0.0
                        _phase_prov    = True

                    inverter_data.append({
                        "entity_id":         eid,
                        "label":             profile.label,
                        "current_w":         round(cur_w, 1),
                        "peak_w":            round(peak_w, 1),
                        "peak_w_7d":         round(profile.peak_power_w_7d, 1),
                        "estimated_wp":      round(profile.estimated_wp, 1),
                        "rated_power_w":     round(rated_w, 0) if rated_w else None,
                        "clipping_ceiling_w":round(clipping_ceiling, 0) if clipping_ceiling else None,
                        "utilisation_pct":   util,
                        "clipping":          clipping,
                        "phase":             profile.detected_phase or "unknown",
                        "phase_certain":     profile.phase_certain,
                        "phase_votes":       profile.phase_votes,
                        "phase_total_votes": total_votes,
                        "phase_display":     _phase_display,
                        "phase_confidence":  _phase_conf,
                        "phase_provisional": _phase_prov,
                        "samples":           profile.samples,
                        "confident":         profile.confident,
                        "azimuth_deg":       azimuth_eff,
                        "azimuth_learned":   az_learned,
                        "azimuth_compass":   _azimuth_compass(azimuth_eff),
                        "tilt_deg":          tilt_eff,
                        "tilt_learned":      ti_learned,
                        "orientation_confident":      or_confident,
                        "clear_sky_samples":          clear_sky_samples,
                        "orientation_samples_needed": samples_needed,
                        "orientation_learning_pct":   learn_pct,
                        "peak_production_hour":       peak_hour,
                        "hourly_yield_fraction":      hourly_yield,
                    })
            if self._pv_forecast:
                await self._pv_forecast.async_refresh_weather()
                pv_forecast_kwh          = self._pv_forecast.get_total_forecast_today_kwh()
                pv_forecast_tomorrow_kwh = self._pv_forecast.get_total_forecast_tomorrow_kwh()
                inverter_profiles        = self._pv_forecast.get_all_profiles()
                for inv_id in [p["inverter_id"] for p in inverter_profiles]:
                    for hf in self._pv_forecast.get_forecast(inv_id):
                        pv_forecast_hourly.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                            "low_w":       hf.low_w,
                            "high_w":      hf.high_w,
                        })
                    for hf in self._pv_forecast.get_forecast_tomorrow(inv_id):
                        pv_forecast_hourly_tomorrow.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                            "low_w":       hf.low_w,
                            "high_w":      hf.high_w,
                        })
                # Feed learner
                for inv in self._config.get(CONF_INVERTER_CONFIGS, []):
                    eid  = inv.get("entity_id","")
                    raw  = self._read_state(eid)
                    if raw is not None:
                        pw = self._calc.to_watts(eid, raw)
                        # FIX: None check on get_profile
                        profile = self._solar_learner.get_profile(eid) if self._solar_learner else None
                        learned_pk = profile.peak_power_w if profile else 0.0
                        rated_pk   = (next(
                            (c.get("rated_power_w", 0) for c in self._config.get(CONF_INVERTER_CONFIGS, [])
                             if c.get("entity_id") == eid), 0
                        ) or 0)
                        # Bootstrap: use max of learned peak, rated power, or current reading.
                        # Without this, peak_wp=0 → frac=0 → learning never triggers (circular).
                        pk = float(max(learned_pk, rated_pk, pw))
                        await self._pv_forecast.async_update(eid, pw, pk)

            # Multi-inverter manager
            inv_decisions: list = []
            if self._multi_inv_manager:
                inv_decisions = await self._multi_inv_manager.async_evaluate(
                    phase_currents    =self._limiter.phase_currents,
                    current_epex_price=current_price,
                )
                for d in inv_decisions:
                    if d.action in ("dim_pid","negative_price","dim_full"):
                        self._log_decision("solar_dim",
                            f"🔆 Omvormer {d.label}: {d.action} → {d.target_pct:.0f}% — {d.reason}")

            # Peak shaving
            peak_data = {}
            if self._peak_shaving:
                grid_import_w = max(0.0, data.get("grid_power", 0.0))
                peak_data = await self._peak_shaving.async_evaluate(
                    grid_import_w        =grid_import_w,
                    ev_current_a         =self._limiter.ev_charging_current,
                    solar_curtailment_pct=self._limiter.solar_curtailment_percent,
                )
                if peak_data.get("active"):
                    self._log_decision("peak_shaving",
                        f"📊 Piekafschaving actief: {grid_import_w:.0f}W > {peak_data.get('limit_w',0):.0f}W — {peak_data.get('action','')}")

            # Boiler controller
            boiler_decisions: list = []
            solar_surplus = max(0.0, data.get("solar_power",0) - abs(data.get("grid_power",0)))

            # v1.18.1: stroomuitval — alle PV + netspanning = 0 overdag
            _solar_w = data.get("solar_power", 0.0) or 0.0
            _grid_w  = abs(data.get("grid_power", 0.0) or 0.0)
            _hour    = datetime.now(timezone.utc).hour
            if 7 <= _hour <= 20 and _solar_w < 10 and _grid_w < 5:
                self._outage_streak = getattr(self, '_outage_streak', 0) + 1
                if self._outage_streak >= 3 and not getattr(self, '_outage_active', False):
                    self._outage_active = True
                    _outage_detected = True
                    _outage_message = (
                        f"Mogelijke stroomstoring gedetecteerd: PV {_solar_w:.0f}W en "
                        f"netimport {_grid_w:.0f}W gedurende 3+ meting-cycli overdag ({_hour}:xx)."
                    )
                    _LOGGER.warning("CloudEMS: %s", _outage_message)
            else:
                self._outage_streak = 0
                self._outage_active = False
            _outage_detected = getattr(self, '_outage_active', False)
            if self._boiler_ctrl:
                boiler_decisions = await self._boiler_ctrl.async_evaluate(
                    price_info         =price_info,
                    solar_surplus_w    =solar_surplus,
                    phase_currents     =self._limiter.phase_currents,
                    phase_max_currents ={
                        ph: self._limiter._phases[ph].max_ampere
                        for ph in self._limiter._phases
                    },
                )
                for bd in boiler_decisions:
                    if bd.action in ("turn_on","turn_off"):
                        self._log_decision("boiler",
                            f"🔌 {bd.label}: {bd.action} — {bd.reason}")

            # Cost tracking
            energy_tax   = float(self._config.get(CONF_ENERGY_TAX, 0.0))
            grid_power_w = p1_data.get("net_power_w") or data.get("grid_power", 0.0)
            cost_ph      = (grid_power_w / 1000.0) * (current_price + energy_tax)

            now_dt   = datetime.now(timezone.utc)
            day_k    = now_dt.strftime("%Y-%m-%d")
            month_k  = now_dt.strftime("%Y-%m")
            if self._cost_day_key   != day_k:   self._cost_today_eur = 0.0;  self._cost_day_key   = day_k
            if self._cost_month_key != month_k: self._cost_month_eur = 0.0;  self._cost_month_key = month_k
            self._cost_today_eur  = round(self._cost_today_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)
            self._cost_month_eur  = round(self._cost_month_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)

            # v1.9: CO2 intensity update (rate-limited internally to 15 min)
            await self._co2_fetcher.update()
            co2_info = self._co2_fetcher.get_info()

            # v1.9: Cost forecaster tick
            await self._cost_forecaster.async_tick(
                power_w       = max(0.0, data.get("grid_power", 0.0)),
                price_eur_kwh = current_price or 0.0,
            )
            cost_forecast = self._cost_forecaster.get_forecast(price_info)
            seasonal_summary = self._cost_forecaster.get_seasonal_summary()

            # v1.10.3: Home baseline anomaly + standby + occupancy (always-on)
            grid_w = data.get("grid_power", 0.0)
            baseline_data = self._home_baseline.update(grid_w) if self._home_baseline else {}

            # v1.10.3: EV session learner (auto-detects sessions from charger current)
            ev_session_data: dict = {}
            if self._ev_session:
                ev_current_a = 0.0
                ev_eid = self._config.get("ev_charger_entity", "")
                if ev_eid:
                    ev_st = self.hass.states.get(ev_eid)
                    if ev_st and ev_st.state not in ("unavailable", "unknown"):
                        try:
                            ev_current_a = float(ev_st.state)
                        except (ValueError, TypeError):
                            ev_current_a = 0.0
                ev_session_data = self._ev_session.update(ev_current_a, current_price or 0.0)

            # v1.10.3: NILM schedule learner (enriches device list with schedule metadata)
            nilm_devices_raw = self._nilm.get_devices_for_ha()

            # v1.17: Hybride NILM tick + anker-apparaten samenvoegen
            if self._hybrid:
                await self._hybrid.async_tick()
                anchored = self._hybrid.get_anchored_devices()
                # Verwijder NILM-dubbelingen op basis van entity_id (v1.17.1 fix:
                # niet op device_type+phase — alle stopcontacten hebben device_type='socket'
                # en dat zou alle maar 1 weggooien).
                anchored_eids = {a["entity_id"] for a in anchored if "entity_id" in a}
                # Verwijder ook NILM-apparaten die hetzelfde NAMED apparaat zijn als een anker
                # (bijv. als NILM ook een "washing_machine" detecteert die al via stekker gemeten wordt)
                anchored_named = {
                    (a["device_type"], a["phase"])
                    for a in anchored
                    if a.get("device_type") not in ("socket", "unknown", None)
                }
                nilm_devices_raw = [
                    d for d in nilm_devices_raw
                    if d.get("entity_id") not in anchored_eids
                    and (d.get("device_type"), d.get("phase")) not in anchored_named
                ] + anchored

            if self._nilm_schedule:
                nilm_devices_enriched = self._nilm_schedule.update(nilm_devices_raw)
                nilm_schedule_summary = self._nilm_schedule.get_schedule_summary()
            else:
                nilm_devices_enriched = nilm_devices_raw
                nilm_schedule_summary = []

            # v1.10.3: Weather calibration for PV forecast
            weather_calib: dict = {}
            if self._pv_forecast:
                for inv in self._config.get("inverter_configs", []):
                    eid = inv.get("entity_id", "")
                    raw = self._read_state(eid)
                    if raw is not None:
                        pw = self._calc.to_watts(eid, raw)
                        self._pv_forecast.update_weather_calibration(eid, pw)
                weather_calib = self._pv_forecast.get_calibration_summary()

            # ── v1.11.0: NEW INTELLIGENCE FEATURES ──────────────────────────

            # Feature 1: Thermal house model
            thermal_data: dict = {}
            if self._thermal_model:
                outside_temp_eid = self._config.get("outside_temp_entity", "")
                outside_temp_c   = self._read_state(outside_temp_eid) if outside_temp_eid else None
                if outside_temp_c is not None:
                    # Use NILM heating devices or total power as heating proxy
                    heating_w = 0.0
                    for dev in nilm_devices_raw:
                        if dev.get("device_type") in ("heat_pump", "boiler", "cv_boiler", "heat") and dev.get("is_on"):
                            heating_w += float(dev.get("current_power") or 0)
                    if heating_w == 0:
                        # Fallback: use total grid import as rough proxy
                        heating_w = max(0.0, data.get("grid_power", 0.0))
                    self._thermal_model.update(heating_w=heating_w, outside_temp_c=outside_temp_c)
                therm_obj  = self._thermal_model.get_data()
                from .energy_manager.thermal_model import MIN_SAMPLES_RELIABLE as _TH_NEEDED
                thermal_data = {
                    "w_per_k":             therm_obj.w_per_k,
                    "samples":             therm_obj.samples,
                    "samples_needed":      _TH_NEEDED,
                    "progress_pct":        round(min(100, therm_obj.samples / _TH_NEEDED * 100)),
                    "reliable":            therm_obj.reliable,
                    "rating":              therm_obj.rating,
                    "advice":              therm_obj.advice,
                    "heating_days":        therm_obj.heating_days,
                    "last_heating_w":      therm_obj.last_heating_w,
                    "last_outside_temp_c": therm_obj.last_outside_temp_c,
                }
                await self._thermal_model.async_maybe_save()

            # v1.15.0: Outdoor temp fallback via Open-Meteo when no sensor configured
            outside_temp_eid = self._config.get("outside_temp_entity", "")
            outside_temp_c_val = self._read_state(outside_temp_eid) if outside_temp_eid else None
            if outside_temp_c_val is None and self._thermal_model:
                outside_temp_c_val = await self._thermal_model.async_fetch_outdoor_temp(
                    session=self._session
                )

            # v1.15.0: Heat pump COP update
            hp_cop_data: dict = {}
            if self._hp_cop:
                hp_eid = self._config.get("heat_pump_power_entity", "")
                hp_th_eid = self._config.get("heat_pump_thermal_entity", "")
                hp_electric_w = 0.0
                hp_thermal_w = None
                if hp_eid:
                    raw = self._read_state(hp_eid)
                    if raw is not None:
                        hp_electric_w = self._calc.to_watts(hp_eid, raw)
                else:
                    # Derive from NILM heat pump detections
                    for dev in nilm_devices_raw:
                        if dev.get("device_type") in ("heat_pump", "air_source_heat_pump") and dev.get("running"):
                            hp_electric_w += float(dev.get("current_power") or dev.get("power_w") or 0)
                if hp_th_eid:
                    raw_th = self._read_state(hp_th_eid)
                    if raw_th is not None:
                        hp_thermal_w = self._calc.to_watts(hp_th_eid, raw_th)
                # Get w_per_k from thermal model
                wk_val = thermal_data.get("w_per_k") if thermal_data else None
                indoor_t = self._config.get("indoor_temp_entity", "")
                indoor_c = self._read_state(indoor_t) if indoor_t else None
                cop_result = self._hp_cop.update(
                    electric_w    = hp_electric_w,
                    outdoor_temp_c= outside_temp_c_val,
                    thermal_w     = hp_thermal_w,
                    w_per_k       = wk_val,
                    indoor_temp_c = indoor_c,
                )
                from .energy_manager.heat_pump_cop import MIN_SAMPLES_RELIABLE as _COP_NEEDED
                _cop_buckets = getattr(self._hp_cop, "_buckets", {})
                _cop_total   = sum(b.samples for b in _cop_buckets.values())
                _cop_rel_bkt = sum(1 for b in _cop_buckets.values() if b.samples >= _COP_NEEDED)
                hp_cop_data = {
                    "cop_current":       cop_result.cop_current,
                    "cop_at_7c":         cop_result.cop_at_7c,
                    "cop_at_2c":         cop_result.cop_at_2c,
                    "cop_at_minus5c":    cop_result.cop_at_minus5c,
                    "defrost_today":     cop_result.defrost_today,
                    "outdoor_temp_c":    cop_result.outdoor_temp_c,
                    "reliable":          cop_result.reliable,
                    "method":            cop_result.method,
                    "curve":             cop_result.curve,
                    "defrost_threshold_c": cop_result.defrost_threshold_c,
                    "total_samples":     _cop_total,
                    "reliable_buckets":  _cop_rel_bkt,
                    "progress_pct":      round(min(100, _cop_rel_bkt / max(1, len(_cop_buckets)) * 100)) if _cop_buckets else 0,
                }
                await self._hp_cop.async_maybe_save()

            # Feature 2: Flexible power score
            from .energy_manager.flex_score import calculate_flex_score
            ev_connected      = bool(self._config.get("ev_charger_entity") and data.get("ev_decision"))
            batt_soc          = self._read_state(self._config.get("battery_soc_entity", ""))
            batt_capacity     = float(self._config.get("battery_capacity_kwh", 0) or 0)
            batt_max_kw       = float(self._config.get("battery_max_charge_kw", 0) or 0)
            flex_result       = calculate_flex_score(
                battery_soc_pct      = batt_soc,
                battery_capacity_kwh = batt_capacity or None,
                battery_max_charge_kw= batt_max_kw or None,
                ev_connected         = ev_connected,
                ev_max_charge_kw     = float(self._config.get("ev_max_charge_kw", 7.4) or 7.4),
                ev_session_hours_remaining = float(ev_session_data.get("predicted_duration_h") or 2.0),
                boiler_status        = self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                nilm_devices         = nilm_devices_enriched,
            )
            flex_data = {
                "total_kw":   flex_result.total_kw,
                "battery_kw": flex_result.battery_kw,
                "ev_kw":      flex_result.ev_kw,
                "boiler_kw":  flex_result.boiler_kw,
                "nilm_kw":    flex_result.nilm_kw,
                "breakdown":  flex_result.breakdown,
                "components": [
                    {"source": c.source, "label": c.label, "flex_kw": c.flex_kw, "reason": c.reason}
                    for c in flex_result.components
                ],
            }

            # Feature 3: PV panel health (soiling/degradation)
            pv_health_data: dict = {}
            if self._pv_health and self._solar_learner:
                profiles   = self._solar_learner.get_all_profiles()
                pv_health  = self._pv_health.assess(profiles)
                pv_health_data = {
                    "any_alert": pv_health.any_alert,
                    "summary":   pv_health.summary,
                    "inverters": [
                        {
                            "inverter_id":    s.inverter_id,
                            "label":          s.label,
                            "peak_all_time_w":s.peak_all_time_w,
                            "peak_recent_w":  s.peak_recent_w,
                            "ratio":          s.ratio,
                            "alert":          s.alert,
                            "alert_type":     s.alert_type,
                            "message":        s.message,
                        }
                        for s in pv_health.inverters
                    ],
                }
                await self._pv_health.async_maybe_save()

            # Feature 5: Self-consumption ratio
            self_cons_data: dict = {}
            if self._self_consumption:
                self._self_consumption.tick(
                    pv_w     = max(0.0, data.get("solar_power", 0.0)),
                    import_w = max(0.0, data.get("import_power", data.get("grid_power", 0.0))),
                    export_w = max(0.0, data.get("export_power", 0.0)),
                )
                sc = self._self_consumption.get_data()
                self_cons_data = {
                    "ratio_pct":          sc.ratio_pct,
                    "export_pct":         sc.export_pct,
                    "pv_today_kwh":       sc.pv_today_kwh,
                    "self_consumed_kwh":  sc.self_consumed_kwh,
                    "exported_kwh":       sc.exported_kwh,
                    "best_solar_hour":    sc.best_solar_hour,
                    "best_solar_label":   sc.best_solar_hour_label,
                    "advice":             sc.advice,
                    "monthly_saving_eur": sc.monthly_saving_eur,
                }
                await self._self_consumption.async_maybe_save()

            # Feature 6: Day-type classification
            day_type_data: dict = {}
            if self._day_classifier:
                self._day_classifier.observe_power(max(0.0, data.get("grid_power", 0.0)))
                dt = self._day_classifier.get_data()
                day_type_data = {
                    "today_type":         dt.today_type,
                    "today_label":        dt.today_label,
                    "confidence":         dt.confidence,
                    "expected_kwh":       dt.expected_kwh,
                    "total_days_learned": dt.total_days_learned,
                    "advice":             dt.advice,
                }
                await self._day_classifier.async_maybe_save()

            # Feature 7: Device efficiency drift
            drift_data: dict = {}
            if self._device_drift:
                # Feed current NILM detections — v1.20: alleen bevestigde apparaten
                # (user_feedback="correct" of confidence=1.0) krijgen drift-tracking.
                # Onbevestigde detecties hebben een onzekere baseline en geven anders
                # valse drift-waarschuwingen voor dingen die de NILM zelf nog niet
                # goed heeft geleerd.
                for dev in nilm_devices_enriched:
                    if not (dev.get("is_on") and dev.get("current_power")):
                        continue
                    _confirmed   = bool(dev.get("confirmed", False))
                    _confidence  = float(dev.get("confidence", 0))
                    _feedback_ok = dev.get("user_feedback", "") == "correct"
                    _is_anchor   = dev.get("source", "") == "smart_plug"
                    # Drift alleen tracken als: bevestigd door gebruiker, OF 100% confidence
                    # (smart plug anchor), OF eerder handmatig gecorrigeerd
                    if not (_confirmed or _confidence >= 1.0 or _feedback_ok or _is_anchor):
                        continue
                    self._device_drift.record_detection(
                            device_id   = dev.get("device_id", ""),
                            device_type = dev.get("device_type", ""),
                            label       = dev.get("name") or dev.get("label") or dev.get("device_type", ""),
                            power_w     = float(dev.get("current_power", 0)),
                        )
                drift_report = self._device_drift.get_report()
                _drift_profiles = getattr(self._device_drift, "_profiles", {})
                from .energy_manager.device_drift import MIN_BASELINE_SAMPLES as _DR_NEEDED
                _drift_trained  = sum(1 for p in _drift_profiles.values() if p.baseline_frozen)
                drift_data = {
                    "any_alert":     drift_report.any_alert,
                    "any_warning":   drift_report.any_warning,
                    "summary":       drift_report.summary,
                    "trained_count": _drift_trained,
                    "total_count":   len(_drift_profiles),
                    "devices": [
                        {
                            "device_id":      s.device_id,
                            "label":          s.label,
                            "baseline_w":     s.baseline_w,
                            "current_w":      s.current_w,
                            "drift_pct":      s.drift_pct,
                            "level":          s.level,
                            "message":        s.message,
                            "baseline_frozen":_drift_profiles[s.device_id].baseline_frozen if s.device_id in _drift_profiles else True,
                            "samples_total":  _drift_profiles[s.device_id].samples_total if s.device_id in _drift_profiles else 0,
                            "samples_needed": _DR_NEEDED,
                        }
                        for s in drift_report.devices
                    ],
                }
                await self._device_drift.async_maybe_save()

            # Feature 8: Phase migration advice
            phase_migration_data: dict = {}
            try:
                from .energy_manager.phase_advisor import generate_migration_advice
                ph_currents = {}
                if self._limiter:
                    ph_summary = self._limiter.get_phase_summary()
                    ph_currents = {
                        ph: info.get("current_a", 0.0)
                        for ph, info in ph_summary.items()
                        if isinstance(info, dict)
                    }
                inv_phases = {}
                if self._solar_learner:
                    for prof in self._solar_learner.get_all_profiles():
                        if prof.phase_certain and prof.detected_phase:
                            inv_phases[prof.inverter_id] = prof.detected_phase
                mig_report = generate_migration_advice(
                    phase_currents  = ph_currents,
                    inverter_phases = inv_phases,
                    nilm_devices    = nilm_devices_enriched,
                )
                phase_migration_data = {
                    "has_advice":      mig_report.has_advice,
                    "summary":         mig_report.summary,
                    "overloaded_phase":mig_report.overloaded_phase,
                    "lightest_phase":  mig_report.lightest_phase,
                    "imbalance_a":     mig_report.imbalance_a,
                    "advices": [
                        {
                            "device_label":     a.device_label,
                            "from_phase":       a.from_phase,
                            "to_phase":         a.to_phase,
                            "current_load_w":   a.current_load_w,
                            "balance_gain_pct": a.balance_gain_pct,
                            "explanation":      a.explanation,
                        }
                        for a in mig_report.advices
                    ],
                }
            except Exception as _pm_err:
                _LOGGER.debug("Phase migration advisor error: %s", _pm_err)
                phase_migration_data = {}

            # ── End v1.11.0 features ─────────────────────────────────────────

            # v1.11.0: Micro-mobility (e-bike/scooter) tracking
            micro_mobility_data: dict = {}
            if self._micro_mobility:
                self._micro_mobility.update(
                    nilm_devices    = nilm_devices_enriched,
                    price_eur_kwh   = current_price or 0.0,
                )
                mm = self._micro_mobility.get_data()
                micro_mobility_data = {
                    "vehicles_today":   mm.vehicles_today,
                    "kwh_today":        mm.kwh_today,
                    "cost_today_eur":   mm.cost_today_eur,
                    "sessions_today":   mm.sessions_today,
                    "active_sessions":  mm.active_sessions,
                    "vehicle_profiles": mm.vehicle_profiles,
                    "best_charge_hour": mm.best_charge_hour,
                    "advice":           mm.advice,
                    "total_sessions":   mm.total_sessions,
                    "total_kwh":        mm.total_kwh,
                    "weekly_kwh_avg":   mm.weekly_kwh_avg,
                }
                await self._micro_mobility.async_maybe_save()

            # v1.12.0: Clipping verlies per omvormer
            clipping_loss_data: dict = {}
            if self._clipping_loss and self._solar_learner:
                try:
                    # Haal PV-forecast op voor estimated_peak (per uur)
                    pv_hourly: dict[str, float] = {}
                    if self._pv_forecast:
                        for hf in getattr(self._pv_forecast, "_hourly_cache", {}).values():
                            pass  # forecast_w beschikbaar via inverter_data
                    feedin_price = float(data.get("energy_price_current_hour", DEFAULT_FEEDIN_EUR_KWH)
                                        if "energy_price_current_hour" in (data or {}) else 0.08)
                    for inv in inverter_data:
                        eid  = inv["entity_id"]
                        # estimated_peak: use learned scale factor if available,
                        # otherwise forecast hourly yield, otherwise all-time peak × factor
                        learned_scale = self._clipping_loss.get_learned_scale_factor(eid)
                        # Prefer forecast-derived estimate if we have hourly yield data
                        fc_est = inv.get("forecast_peak_w", 0.0)
                        if fc_est and fc_est > 0:
                            est_peak = fc_est
                        else:
                            est_peak = inv.get("peak_w", 0.0) * learned_scale
                        self._clipping_loss.tick(
                            inverter_id      = eid,
                            label            = inv.get("label", eid),
                            power_w          = inv.get("current_w", 0.0),
                            estimated_peak_w = est_peak,
                            is_clipping      = bool(inv.get("clipping", False)),
                        )
                    clipping_obj      = self._clipping_loss.get_data(feedin_price_eur_kwh=feedin_price)
                    clipping_loss_data = {
                        "total_kwh_lost_30d":   clipping_obj.total_kwh_lost_30d,
                        "total_eur_lost_year":  clipping_obj.total_eur_lost_year,
                        "inverters":            clipping_obj.inverters,
                        "worst_inverter":       clipping_obj.worst_inverter,
                        "advice":               clipping_obj.advice,
                        "any_curtailment":      clipping_obj.any_curtailment,
                        "expansion_roi_years":  clipping_obj.expansion_roi_years,
                    }
                    # v1.16.0: Clipping forecast voor morgen
                    clipping_forecast_list = []
                    if self._pv_forecast:
                        for inv in inverter_data:
                            eid  = inv["entity_id"]
                            lbl  = inv.get("label", eid)
                            # Haal het uurlijkse forecast op voor morgen (24 waarden)
                            tomorrow_fc = self._pv_forecast.get_forecast_tomorrow(eid)
                            fc_w_list   = [hf.forecast_w for hf in tomorrow_fc] if tomorrow_fc else []
                            if fc_w_list:
                                cf = self._clipping_loss.get_clipping_forecast(
                                    inverter_id       = eid,
                                    forecast_hourly_w = fc_w_list,
                                    label             = lbl,
                                )
                                clipping_forecast_list.append(cf)
                    clipping_loss_data["clipping_forecast_tomorrow"] = clipping_forecast_list
                    await self._clipping_loss.async_maybe_save()
                except Exception as _cl_err:
                    _LOGGER.debug("ClippingLoss error: %s", _cl_err)

            # v1.16.0: Schaduwdetectie
            shadow_data: dict = {}
            if self._shadow_detector and self._solar_learner and self._pv_forecast:
                try:
                    hour_utc = datetime.now(timezone.utc).hour
                    for inv in inverter_data:
                        eid    = inv["entity_id"]
                        fp     = {}
                        for p in self._pv_forecast.get_all_profiles():
                            if p["inverter_id"] == eid:
                                fp = p
                                break
                        # Verwacht fractie uit het geleerde uurprofiel van pv_forecast
                        hyf          = fp.get("hourly_yield_fraction", {})
                        expected_frac = float(hyf.get(str(hour_utc), 0.0))
                        peak_wp      = inv.get("estimated_wp") or inv.get("peak_w", 0.0)
                        self._shadow_detector.tick(
                            inverter_id   = eid,
                            label         = inv.get("label", eid),
                            current_w     = inv.get("current_w", 0.0),
                            peak_wp       = float(peak_wp),
                            expected_frac = expected_frac,
                            hour_utc      = hour_utc,
                        )
                    shadow_obj = self._shadow_detector.get_result()
                    _shad_profiles = getattr(self._shadow_detector, "_profiles", {})
                    from .energy_manager.shadow_detector import MIN_SHADOW_DAYS as _SH_NEEDED
                    _shad_trained  = sum(
                        sum(1 for p in hours.values() if p.samples >= _SH_NEEDED)
                        for hours in _shad_profiles.values()
                    )
                    _shad_total    = sum(len(hours) for hours in _shad_profiles.values())
                    shadow_data = {
                        "any_shadow":         shadow_obj.any_shadow,
                        "total_lost_kwh_day": shadow_obj.total_lost_kwh_day,
                        "summary":            shadow_obj.summary,
                        "trained_hours":      _shad_trained,
                        "total_hours":        _shad_total,
                        "progress_pct":       round(min(100, _shad_trained / max(1, _shad_total) * 100)) if _shad_total else 0,
                        "inverters": [
                            {
                                "inverter_id":     r.inverter_id,
                                "label":           r.label,
                                "shadowed_hours":  r.shadowed_hours,
                                "partial_hours":   r.partial_hours,
                                "direction":       r.direction,
                                "severity":        r.severity,
                                "lost_kwh_day_est":r.lost_kwh_day_est,
                                "advice":          r.advice,
                            }
                            for r in shadow_obj.inverters
                        ],
                    }
                    await self._shadow_detector.async_maybe_save()
                except Exception as _sd_err:
                    _LOGGER.debug("ShadowDetector error: %s", _sd_err)

            # v1.12.0: Verbruik categorieën
            categories_data: dict = {}
            if self._categories:
                try:
                    standby_w = float((data or {}).get("standby_w", 0.0))
                    self._categories.tick(
                        nilm_devices  = nilm_devices_enriched,
                        standby_w     = standby_w,
                        grid_import_w = float((data or {}).get("grid_import_power", 0.0)),
                        battery_w     = self._last_battery_w,
                    )
                    cat_obj = self._categories.get_data()
                    categories_data = {
                        "top_category":      cat_obj.top_category,
                        "top_category_pct":  cat_obj.top_category_pct,
                        "breakdown_pct":     cat_obj.breakdown_pct,
                        "breakdown_kwh":     cat_obj.breakdown_kwh,
                        "breakdown_w_now":   cat_obj.breakdown_w_now,
                        "total_kwh_today":   cat_obj.total_kwh_today,
                        "total_w_now":       cat_obj.total_w_now,
                        "pie_data":          cat_obj.pie_data,
                        "dominant_insight":  cat_obj.dominant_insight,
                        "avg_breakdown_pct": cat_obj.avg_breakdown_pct,
                    }
                    await self._categories.async_maybe_save()
                except Exception as _cat_err:
                    _LOGGER.debug("ConsumptionCategories error: %s", _cat_err)

            # v1.20: Virtuele stroommeter per kamer
            room_meter_data: dict = {}
            try:
                if hasattr(self, "_room_meter") and self._room_meter:
                    _rooms = await self._room_meter.async_update(
                        nilm_devices = nilm_devices_enriched,
                        interval_s   = 10.0,
                    )
                    _total_w = data.get("grid_power", 0) or 0
                    room_meter_data = {
                        "overview": self._room_meter.get_overview(abs(_total_w)),
                        "rooms":    {name: r.to_dict() for name, r in _rooms.items()},
                    }
            except Exception as _room_err:
                _LOGGER.debug("RoomMeter error: %s", _room_err)

            # v1.20: Goedkope uren schakelaar planner
            cheap_switch_data: dict = {}
            try:
                if hasattr(self, "_cheap_switch_scheduler") and self._cheap_switch_scheduler:
                    _cs_price = self._enrich_price_info(price_info) if price_info else {}
                    _cs_actions = await self._cheap_switch_scheduler.async_evaluate(_cs_price)
                    _cs_status  = self._cheap_switch_scheduler.get_status(_cs_price)
                    cheap_switch_data = {
                        "switches": _cs_status,
                        "actions":  _cs_actions,
                        "count":    len(_cs_status),
                    }
            except Exception as _cs_err:
                _LOGGER.debug("CheapSwitch error: %s", _cs_err)
            battery_schedule = {}
            if self._battery_scheduler:
                # v1.18.1: pass soh_pct voor slijtage-bewust laden
                _soh = (
                    self._battery_degradation.update.__self__.state.soh_pct
                    if self._battery_degradation and hasattr(self._battery_degradation, '_state')
                    else None
                )
                _soh = getattr(getattr(self, '_battery_degradation', None), '_state', None)
                _soh_pct = getattr(_soh, 'soh_pct', None)

                # v1.20: build seasonal parameters
                from .energy_manager.seasonal_strategy import build_seasonal_parameters
                _pv_avg_14d_w = None
                _pv_peak_w    = None
                if self._solar_learner:
                    _all_profiles = self._solar_learner.get_all_profiles()
                    if _all_profiles:
                        _pv_peak_w    = sum(p.peak_power_w for p in _all_profiles if p.peak_power_w)
                        _pv_peak_7d   = sum(p.peak_power_w_7d for p in _all_profiles if p.peak_power_w_7d)
                        _pv_avg_14d_w = _pv_peak_7d  # best proxy without 14d rolling average

                _season_override = cfg.get("battery_season_override", None)
                _seasonal_params = build_seasonal_parameters(
                    latitude_deg          = self.hass.config.latitude or 52.1,
                    pv_avg_14d_w          = _pv_avg_14d_w,
                    pv_peak_w             = _pv_peak_w,
                    pv_forecast_today_kwh = pv_forecast_kwh,
                    battery_capacity_kwh  = float(cfg.get("battery_capacity_kwh", 10.0)),
                    battery_max_charge_w  = float(cfg.get("battery_max_charge_w", 3000.0)),
                    pv_forecast_hourly    = pv_forecast_hourly,
                    override              = _season_override,
                )

                battery_schedule = await self._battery_scheduler.async_evaluate(
                    price_info         = price_info,
                    solar_surplus_w    = solar_surplus,
                    soh_pct            = _soh_pct,
                    pv_forecast_hourly = pv_forecast_hourly,
                    seasonal_params    = _seasonal_params,
                )

            # v1.10: Grid congestion detection
            congestion_data: dict = {}
            if self._congestion_detector:
                grid_import_w   = max(0.0, data.get("grid_power", 0.0))
                congestion_price = price_info.get("current", 0.0) if price_info else 0.0
                cong_result     = await self._congestion_detector.async_evaluate(
                    grid_import_w  = grid_import_w,
                    price_eur_kwh  = congestion_price,
                )
                congestion_data = {
                    "active":          cong_result.congestion_active,
                    "import_w":        cong_result.import_w,
                    "threshold_w":     cong_result.threshold_w,
                    "utilisation_pct": cong_result.utilisation_pct,
                    "actions":         cong_result.actions,
                    "today_events":    cong_result.today_events,
                    "month_events":    cong_result.month_events,
                    "peak_today_w":    cong_result.peak_today_w,
                    "monthly_summary": self._congestion_detector.get_monthly_summary(),
                }
                # Propagate congestion state to boiler controller
                if self._boiler_ctrl:
                    self._boiler_ctrl.update_congestion_state(cong_result.congestion_active)
                if cong_result.congestion_active and cong_result.actions:
                    self._log_decision(
                        "congestion",
                        f"⚡ Netcongestie: {cong_result.utilisation_pct:.0f}% benutting "
                        f"— {len(cong_result.actions)} aanbevolen acties"
                    )

            # v1.10: Battery degradation tracking
            degradation_data: dict = {}
            if self._battery_degradation:
                soc_eid  = self._config.get("battery_soc_entity", "")
                soc_val  = self._read_state(soc_eid) if soc_eid else None
                deg_result = self._battery_degradation.update(soc_val)
                degradation_data = {
                    "soh_pct":        deg_result.soh_pct,
                    "capacity_kwh":   deg_result.capacity_kwh,
                    "total_cycles":   deg_result.total_cycles,
                    "cycles_per_day": deg_result.cycles_per_day,
                    "alert_level":    deg_result.alert_level,
                    "alert_message":  deg_result.alert_message,
                    "soc_low_events": deg_result.soc_low_events,
                    "days_tracked":   deg_result.days_tracked,
                }
                await self._battery_degradation.async_save()
                if deg_result.alert_level in ("warn", "critical"):
                    self._log_decision(
                        "battery_health",
                        f"🔋 {deg_result.alert_message}"
                    )

            # v1.10: Update outside temperature for heat demand mode
            outside_temp_eid = self._config.get("outside_temp_entity", "")
            if self._boiler_ctrl and outside_temp_eid:
                outside_temp = self._read_state(outside_temp_eid)
                self._boiler_ctrl.update_outside_temp(outside_temp)

            # v1.10.2: Sensor hint engine — detect unconfigured PV/battery from grid patterns
            sensor_hints: list = []
            if self._sensor_hints:
                cfg = self._config
                has_solar   = bool(cfg.get("solar_sensor", ""))
                has_battery = bool(cfg.get("battery_sensor", ""))
                has_curr_l1 = bool(cfg.get("phase_sensors_L1", ""))
                has_volt_l1 = bool(cfg.get("voltage_sensor_l1", ""))
                has_pwr_l1  = bool(cfg.get("power_sensor_l1", ""))
                hints = self._sensor_hints.update(
                    grid_power_w        = data.get("grid_power", 0.0),
                    has_solar_sensor    = has_solar,
                    has_battery_sensor  = has_battery,
                    has_current_l1      = has_curr_l1,
                    has_voltage_l1      = has_volt_l1,
                    has_power_l1        = has_pwr_l1,
                )
                sensor_hints = self._sensor_hints.get_all_hints()
                for h in hints:
                    self._log_decision(
                        "sensor_hint",
                        f"💡 {h.title}: {h.message[:80]}…"
                    )
                await self._sensor_hints.async_save()

            # v1.15.0: Sanity guard
            sanity_data: dict = {}
            battery_total_w: Optional[float] = None
            if self._config.get(CONF_BATTERY_SENSOR, ""):
                batt_raw = self._read_state(self._config.get(CONF_BATTERY_SENSOR, ""))
                battery_total_w = self._calc.to_watts(
                    self._config.get(CONF_BATTERY_SENSOR, ""), batt_raw
                ) if batt_raw is not None else None
            if self._sensor_sanity:
                phase_c = {}
                if self._limiter:
                    phase_c = {ph: info.get("current_a", 0.0)
                               for ph, info in self._limiter.get_phase_summary().items()
                               if isinstance(info, dict)}
                sanity_result = self._sensor_sanity.update(
                    grid_w    = data.get("grid_power", 0.0),
                    solar_w   = data.get("solar_power", 0.0),
                    battery_w = battery_total_w,
                    phase_currents = phase_c,
                    max_current_a  = float(self._config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT)),
                    phases         = int(self._config.get(CONF_PHASE_COUNT, 1)),
                    mains_v        = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V)),
                )
                sanity_data = {
                    "has_critical": sanity_result.has_critical,
                    "has_warning":  sanity_result.has_warning,
                    "summary":      sanity_result.summary,
                    "issues": [
                        {
                            "code":        getattr(i, "code", ""),
                            "level":       getattr(i, "level", "warning"),
                            "sensor_type": getattr(i, "sensor_type", ""),
                            "entity_id":   getattr(i, "entity_id", ""),
                            "description": getattr(i, "description", ""),
                            "advice":      getattr(i, "advice", ""),
                            "value":       round(getattr(i, "value", 0.0), 2),
                            "expected":    getattr(i, "expected", ""),
                        }
                        for i in sanity_result.issues
                    ],
                }

            # v1.15.0: EMA diagnostics
            ema_diag: dict = {}
            if self._sensor_ema:
                ema_diag = self._sensor_ema.get_diagnostics()

            # v1.15.0: Absence / occupancy detection
            occupancy_data: dict = {}
            if self._absence:
                occ = self._absence.update(data.get("grid_power", 0.0))
                occupancy_data = {
                    "state":         occ.state,
                    "confidence":    occ.confidence,
                    "vacation_hours": occ.vacation_hours,
                    "standby_w":     occ.standby_w,
                    "advice":        occ.advice,
                }

            # v1.15.0: Climate pre-heat advisor
            preheat_data: dict = {}
            if self._preheat:
                avg_p = price_info.get("avg_today") if price_info else None
                cur_p = price_info.get("current")   if price_info else None
                wk    = thermal_data.get("w_per_k") if thermal_data else None
                th_rel = thermal_data.get("reliable", False) if thermal_data else False
                adv = self._preheat.update(
                    current_price    = cur_p,
                    avg_price_today  = avg_p,
                    w_per_k          = wk,
                    thermal_reliable = th_rel,
                )
                preheat_data = {
                    "mode":               adv.mode,
                    "setpoint_offset_c":  adv.setpoint_offset_c,
                    "reason":             adv.reason,
                    "price_ratio":        adv.price_ratio,
                    "w_per_k":            adv.w_per_k,
                    "reliable":           adv.reliable,
                }

            # v1.15.0: PV forecast accuracy tracker
            pv_accuracy_data: dict = {}
            if self._pv_accuracy:
                try:
                    solar_w_now = max(0.0, data.get("solar_power", 0.0))
                    # Support both tick() and tick_production() across versions
                    if hasattr(self._pv_accuracy, 'tick_production'):
                        self._pv_accuracy.tick_production(pv_w=solar_w_now)
                    else:
                        self._pv_accuracy.tick(actual_w=solar_w_now)
                    # Day rollover: finalize yesterday and record MAPE
                    from datetime import datetime as _dt_acc
                    today_str = _dt_acc.now().strftime("%Y-%m-%d")
                    if self._acc_date and self._acc_date != today_str and pv_forecast_kwh:
                        try:
                            self._pv_accuracy.finalize_day(forecast_kwh=pv_forecast_kwh)
                        except Exception as _fe:
                            _LOGGER.debug("CloudEMS: pv_accuracy finalize_day failed: %s", _fe)
                    self._acc_date = today_str
                    _acc = self._pv_accuracy.get_data()
                    pv_accuracy_data = {
                        "mape_14d_pct":       _acc.mape_14d,
                        "mape_30d_pct":       _acc.mape_30d,
                        "bias_factor":        _acc.bias_factor,
                        "samples":            _acc.days_with_data,
                        "last_day_mape":      _acc.last_day_error_pct,
                        "quality_label":      _acc.quality_label,
                        "advice":             _acc.advice,
                        "days_tracked":       _acc.days_tracked,
                        "calibration_month":  _acc.calibration_month,
                        "consecutive_over":   _acc.consecutive_over,
                        "consecutive_under":  _acc.consecutive_under,
                        "monthly_bias":       _acc.monthly_bias,
                    }
                    await self._pv_accuracy.async_maybe_save()
                except Exception as _pvacc_err:
                    _LOGGER.warning("CloudEMS: pv_accuracy skipped: %s", _pvacc_err)

            # v1.18.1: Dagelijks leerrapport om 20:00
            _now_h = datetime.now(timezone.utc).hour
            if _now_h == 20 and self._notification_engine:
                try:
                    _report = {"orientation_progress": [], "phase_progress": [], "samples_today": 0}
                    if self._solar_learner:
                        for _p in self._solar_learner.get_all_profiles():
                            if self._pv_forecast:
                                _prof = self._pv_forecast._profiles.get(_p.inverter_id)
                                if _prof:
                                    _have = _prof.clear_sky_samples or 0
                                    _need = _prof.orientation_samples_needed or 1800
                                    _ori_pct = min(100, round(_have / _need * 100)) if _need else 0
                                    _report["orientation_progress"].append({
                                        "label": _p.label, "pct": _ori_pct,
                                        "samples": _have, "needed": _need,
                                        "confident": _prof.orientation_confident,
                                    })
                            _report["phase_progress"].append({
                                "label": _p.label, "phase": _p.detected_phase,
                                "certain": _p.phase_certain, "confidence": 100.0 if _p.phase_certain else 0.0,
                            })
                    await self._notification_engine.send_daily_learning_report(_report)
                except Exception as _rep_err:
                    _LOGGER.debug("Leerrapport fout: %s", _rep_err)

            # Generate insights
            self._insights = self._generate_insights(
                data, price_info, inverter_data, peak_data, balance_data,
                self._limiter.phase_currents, solar_surplus, boiler_decisions
            )

            # Save NILM
            await self._nilm.async_save()

            # ── Periodiek opslaan: alle zelflerende modules ───────────────────
            # Modules die hun eigen dirty/interval-logica hebben maar geen
            # expliciete save-aanroep in de update-loop — max elke 2-10 min.
            for _mod, _method in (
                (getattr(self, "_solar_learner",       None), "_async_save"),
                (getattr(self, "_pv_forecast",         None), "async_save"),
                (getattr(self, "_battery_degradation", None), "async_save"),
                (getattr(self, "_sensor_hints",        None), "async_save"),
                (getattr(self, "_cost_forecaster",     None), "async_save"),
                (getattr(self, "_congestion_detector", None), "async_maybe_save"),
                (getattr(self, "_battery_scheduler",   None), "async_maybe_save"),
                (getattr(self, "_home_baseline",       None), "_async_save"),
                (getattr(self, "_ev_session",          None), "_async_save"),
                (getattr(self, "_nilm_schedule",       None), "_async_save"),
                (getattr(self, "_gas_analysis",        None), "async_maybe_save"),
                (getattr(self, "_energy_budget",       None), "async_maybe_save"),
                (getattr(self, "_notification_engine", None), "async_maybe_save"),
            ):
                if _mod is None:
                    continue
                _fn = getattr(_mod, _method, None)
                if callable(_fn):
                    try:
                        await _fn()
                    except Exception:  # noqa: BLE001
                        pass

            self._data = {
                "grid_power_w":         grid_power_w,
                "power_w":              grid_power_w,
                "solar_power_w":        data.get("solar_power", 0.0),
                "import_power_w":       data.get("import_power", 0.0),
                "export_power_w":       data.get("export_power", 0.0),
                "solar_surplus_w":      solar_surplus,
                "phases":               self._limiter.get_phase_summary(),
                "phase_balance":        balance_data,
                "nilm_devices":         nilm_devices_enriched,
                "nilm_mode":            self._nilm.active_mode,
                "energy_price":         self._enrich_price_info(price_info),
                "ai_status":            self._build_ai_status(),
                "cost_per_hour":        round(cost_ph, 4),
                "cost_today_eur":       self._cost_today_eur,
                "cost_month_eur":       self._cost_month_eur,
                "config_price_alert_high": float(self._config.get("price_alert_high_eur_kwh", 0.30)),
                "config_nilm_confidence":  float(self._config.get("nilm_min_confidence", 0.65)),
                "ev_decision":          ev_decision,
                "ev_solar_plan":        ev_solar_plan,
                "p1_data":              p1_data,
                "inverter_data":        inverter_data,          # ← NEW: peak + clipping
                "pv_forecast_today_kwh":     pv_forecast_kwh,
                "pv_payback":           self._calc_pv_payback(
                    pv_forecast_kwh,
                    price_info,
                    current_price,
                ),
                "pv_forecast_tomorrow_kwh":  pv_forecast_tomorrow_kwh,
                "pv_forecast_hourly":        pv_forecast_hourly,
                "pv_forecast_hourly_tomorrow": pv_forecast_hourly_tomorrow,
                "inverter_profiles":    inverter_profiles,
                "peak_shaving":         peak_data,
                "boiler_status":        self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                "decision_log":         list(self._decision_log),
                "insights":             self._insights,
                "nilm_diagnostics":     self._nilm.get_diagnostics(),  # ← v1.7
                "ollama_health":        self._ollama_health,            # ← v1.16
                "ollama_diagnostics":   self._nilm.get_ollama_diagnostics(),  # ← v1.16
                "hybrid_nilm":          self._hybrid.get_diagnostics() if self._hybrid else {},  # ← v1.17
                "ev_pid_state":         ev_pid_state,                   # ← v1.8
                "phase_pid_states":     self._get_phase_pid_states(),   # ← v1.8
                "co2_info":             co2_info,                       # ← v1.9
                "cost_forecast":        cost_forecast,                  # ← v1.9
                "battery_schedule":     battery_schedule,               # ← v1.9
                "congestion":           congestion_data,                # ← v1.10
                "battery_degradation":  degradation_data,              # ← v1.10
                "nilm_db_stats":        self._nilm._db.get_stats(),    # ← v1.10
                "sensor_hints":         sensor_hints,                   # ← v1.10.2
                "scale_info":           {eid: self._calc.get_scale_info(eid)
                                         for eid in [
                                             self._config.get("grid_sensor",""),
                                             self._config.get("solar_sensor",""),
                                             self._config.get("battery_sensor",""),
                                         ] if eid},                        # ← v1.10.2
                # v1.10.3: self-learning intelligence
                "baseline":             baseline_data,
                "ev_session":           ev_session_data,
                "nilm_schedule":        nilm_schedule_summary,
                "weather_calibration":  weather_calib,
                "seasonal_summary":     seasonal_summary,
                # v1.11.0: 8 new intelligence features
                "thermal_model":        thermal_data,
                "flex_score":           flex_data,
                "pv_health":            pv_health_data,
                "self_consumption":     self_cons_data,
                "day_type":             day_type_data,
                "device_drift":         drift_data,
                "phase_migration":      phase_migration_data,
                "gas_data":             {
                    "gas_m3":  (self._p1_reader.latest.gas_m3  if self._p1_reader and self._p1_reader.latest else self._read_gas_sensor()),
                    "gas_kwh": (self._p1_reader.latest.gas_kwh if self._p1_reader and self._p1_reader.latest else round((self._read_gas_sensor() or 0.0) * 9.769, 3)),
                },
                "batteries":            self._collect_multi_battery_data(),
                "micro_mobility":       micro_mobility_data,
                "clipping_loss":        clipping_loss_data,
                "shadow_detection":     shadow_data,
                "consumption_categories": categories_data,
                "room_meter":       room_meter_data,         # ← v1.20
                "cheap_switches":   cheap_switch_data,        # ← v1.20
                # v1.15.0: new intelligence
                "heat_pump_cop":    hp_cop_data,
                "sensor_sanity":    sanity_data,
                "ema_diagnostics":  ema_diag,
                "occupancy":        occupancy_data,
                "climate_preheat":  preheat_data,
                "pv_accuracy":      pv_accuracy_data,
                "outage_detected":  _outage_detected,
                "outage_message":   _outage_message if _outage_detected else "",
                "notifications":        {},  # gevuld na dispatch hieronder
                # v1.18.0: cross-validatie alerts voor notification engine
                "phase_conflict_alerts": (
                    self._solar_learner.get_phase_conflict_alerts()
                    if self._solar_learner else []
                ),
                "new_panel_resets": [
                    {
                        "inverter_id":  p.inverter_id,
                        "label":        p.label,
                        "reset_count":  p.new_panel_resets,
                    }
                    for p in (self._solar_learner.get_all_profiles() if self._solar_learner else [])
                    if p.new_panel_resets > 0
                ],
            }

            # v1.12.0: Notification engine — ingest alle alerts en verstuur
            if self._notification_engine:
                try:
                    alert_dict = NotificationEngine.build_alerts_from_coordinator_data(self._data)
                    self._notification_engine.ingest(alert_dict)
                    await self._notification_engine.async_dispatch()
                    self._data["notifications"] = self._notification_engine.get_data()
                    await self._notification_engine.async_maybe_save()
                except Exception as _ne_err:
                    _LOGGER.debug("NotificationEngine error: %s", _ne_err)

            # v1.21.0: CPU-adaptive NILM enhancer — runs after base NILM
            if self._data.get("nilm_devices") is not None:
                try:
                    phase_powers = {
                        "L1": self._data.get("phase_power_l1_w") or 0.0,
                        "L2": self._data.get("phase_power_l2_w") or 0.0,
                        "L3": self._data.get("phase_power_l3_w") or 0.0,
                    }
                    enhanced = await self.hass.async_add_executor_job(
                        self._nilm_enhancer.enhance,
                        self._data["nilm_devices"],
                        phase_powers,
                        self._data.get("hybrid_nilm", {}),
                        self._data.get("nilm_diagnostics", {}),
                        self._data.get("nilm_schedule", []),
                        datetime.now().hour,
                    )
                    self._data["nilm_devices"]      = enhanced["devices"]
                    self._data["nilm_diagnostics"]  = {**self._data.get("nilm_diagnostics", {}), **enhanced["diagnostics"]}
                    self._data["nilm_engine_stats"] = enhanced["stats"]
                except Exception as _enh_err:
                    _LOGGER.warning("NilmEnhancer fout (niet-kritisch): %s", _enh_err)

            return self._data

        except Exception as exc:
            _LOGGER.exception("CloudEMS coordinator update failed: %s", exc)
            raise UpdateFailed(str(exc)) from exc

    # ── Data gathering ────────────────────────────────────────────────────────

    def _read_state(self, entity_id: str) -> Optional[float]:
        """Read HA state as float. Also feeds unit_of_measurement to the power calculator."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        # Feed UOM to power calculator so kW/W is determined from metadata first
        self._calc.observe_state(entity_id, state)
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _read_gas_sensor(self) -> Optional[float]:
        """Read standalone gas sensor (m³) when P1 reader is not active."""
        entity_id = self._config.get(CONF_GAS_SENSOR, "")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _collect_multi_battery_data(self) -> list:
        """Collect and self-learn stats for all configured batteries."""
        configs = self._config.get(CONF_BATTERY_CONFIGS, [])
        results = []
        for cfg in configs:
            eid = cfg.get("power_sensor", "")
            soc_eid = cfg.get("soc_sensor", "")
            label = cfg.get("label", "Batterij")

            raw_power = self._read_state(eid) if eid else None
            power_w = self._calc.to_watts(eid, raw_power) if raw_power is not None else None
            soc_pct = self._read_state(soc_eid) if soc_eid else None

            # Self-learn max charge/discharge power
            learned = self._battery_learned.setdefault(eid, {
                "max_charge_w": 0.0, "max_discharge_w": 0.0,
                "energy_wh": 0.0, "soc_samples": [],
            })
            if power_w is not None:
                if power_w > 0:
                    learned["max_charge_w"] = max(learned["max_charge_w"], power_w)
                elif power_w < 0:
                    learned["max_discharge_w"] = max(learned["max_discharge_w"], abs(power_w))

            # Use configured values with learned fallbacks
            max_charge_w    = float(cfg.get("max_charge_w", 0)) or learned["max_charge_w"]
            max_discharge_w = float(cfg.get("max_discharge_w", 0)) or learned["max_discharge_w"]
            capacity_kwh    = float(cfg.get("capacity_kwh", 0))

            # Estimate capacity from SoC swing if not configured
            if soc_pct is not None:
                learned["soc_samples"].append(soc_pct)
                if len(learned["soc_samples"]) > 1000:
                    learned["soc_samples"] = learned["soc_samples"][-1000:]
                if not capacity_kwh and len(learned["soc_samples"]) >= 20:
                    soc_range = max(learned["soc_samples"]) - min(learned["soc_samples"])
                    if soc_range > 10 and max_charge_w > 0:
                        # Very rough: assume 1h at half power ≈ half of soc_range % capacity
                        pass  # Better estimation needs energy integration — leave as 0 for now

            results.append({
                "label":            label,
                "entity_id":        eid,
                "power_w":          round(power_w, 1) if power_w is not None else None,
                "soc_pct":          round(soc_pct, 1) if soc_pct is not None else None,
                "capacity_kwh":     capacity_kwh,
                "max_charge_w":     round(max_charge_w, 0),
                "max_discharge_w":  round(max_discharge_w, 0),
                "learned_max_charge_w":    round(learned["max_charge_w"], 0),
                "learned_max_discharge_w": round(learned["max_discharge_w"], 0),
                "charging":         power_w is not None and power_w > 50,
                "discharging":      power_w is not None and power_w < -50,
                "priority":         cfg.get("priority", 1),
            })
        return results

    async def _gather_power_data(self) -> Dict:
        cfg      = self._config
        use_sep  = cfg.get(CONF_USE_SEPARATE_IE, False)

        import_w = export_w = grid_power = None

        if use_sep:
            raw_imp = self._read_state(cfg.get(CONF_IMPORT_SENSOR,""))
            raw_exp = self._read_state(cfg.get(CONF_EXPORT_SENSOR,""))
            if raw_imp is not None:
                import_w = self._calc.to_watts(cfg.get(CONF_IMPORT_SENSOR,""), raw_imp)
            if raw_exp is not None:
                export_w = self._calc.to_watts(cfg.get(CONF_EXPORT_SENSOR,""), raw_exp)
            if import_w is not None and export_w is not None:
                grid_power = import_w - export_w
        else:
            raw_grid = self._read_state(cfg.get(CONF_GRID_SENSOR,""))
            if raw_grid is not None:
                grid_power = self._calc.to_watts(cfg.get(CONF_GRID_SENSOR,""), raw_grid)
            import_w = max(0.0, grid_power or 0.0)
            export_w = max(0.0, -(grid_power or 0.0))

        raw_solar = self._read_state(cfg.get(CONF_SOLAR_SENSOR,""))
        solar_w   = self._calc.to_watts(cfg.get(CONF_SOLAR_SENSOR,""), raw_solar) if raw_solar is not None else 0.0

        # v1.15.0: apply EMA smoothing to delay-prone cloud sensors
        if self._sensor_ema:
            grid_eid  = cfg.get(CONF_GRID_SENSOR, "")
            solar_eid = cfg.get(CONF_SOLAR_SENSOR, "")
            if grid_eid and grid_power is not None:
                grid_power = self._sensor_ema.update(grid_eid, grid_power)
                import_w   = max(0.0, grid_power or 0.0)
                export_w   = max(0.0, -(grid_power or 0.0))
            if solar_eid and solar_w is not None:
                solar_w = self._sensor_ema.update(solar_eid, solar_w) or 0.0

        return {
            "grid_power":   grid_power or 0.0,
            "import_power": import_w   or 0.0,
            "export_power": export_w   or 0.0,
            "solar_power":  solar_w,
        }

    async def _process_power_data(self, data: Dict) -> None:
        """Update per-phase readings; uses P=U*I fallback via PowerCalculator."""
        cfg      = self._config
        mains_v  = float(cfg.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
        phase_count = int(cfg.get(CONF_PHASE_COUNT, 1))
        phases   = ["L1","L2","L3"] if phase_count == 3 else ["L1"]

        phase_conf = {
            "L1": (CONF_PHASE_SENSORS+"_L1", CONF_VOLTAGE_L1, CONF_POWER_L1),
            "L2": (CONF_PHASE_SENSORS+"_L2", CONF_VOLTAGE_L2, CONF_POWER_L2),
            "L3": (CONF_PHASE_SENSORS+"_L3", CONF_VOLTAGE_L3, CONF_POWER_L3),
        }
        # v1.15.0: DSMR5 per-phase export sensors
        # Bidirectionele meters meten teruglevering per fase apart.
        # Netto fase vermogen = import_W − export_W
        from .const import CONF_POWER_L1_EXPORT, CONF_POWER_L2_EXPORT, CONF_POWER_L3_EXPORT
        # P1 per-phase data — used as fallback when no dedicated phase sensors configured.
        # p1_data is populated earlier in _gather_power_data if P1 reader is active.
        p1_data = getattr(self, "_last_p1_data", {})
        p1_phase_power  = {"L1": "power_l1_import_w", "L2": "power_l2_import_w", "L3": "power_l3_import_w"}
        p1_phase_export = {"L1": "power_l1_export_w",  "L2": "power_l2_export_w",  "L3": "power_l3_export_w"}
        p1_phase_current= {"L1": "current_l1",          "L2": "current_l2",          "L3": "current_l3"}

        phase_export_keys = {"L1": CONF_POWER_L1_EXPORT, "L2": CONF_POWER_L2_EXPORT, "L3": CONF_POWER_L3_EXPORT}

        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            raw_a = self._read_state(cfg.get(amp_key,""))
            raw_v = self._read_state(cfg.get(volt_key,""))
            raw_p = self._read_state(cfg.get(pwr_key,""))

            # Fallback 1: use P1 per-phase current when no dedicated current sensor
            if raw_a is None and p1_data:
                p1_a = p1_data.get(p1_phase_current[ph])
                if p1_a and p1_a > 0:
                    raw_a = float(p1_a)

            # Fallback 2: use P1 per-phase net power when no dedicated power sensor.
            # This enables U = P/I derivation when both P1 power and current are available.
            if raw_p is None and p1_data:
                p1_imp = p1_data.get(p1_phase_power[ph])
                p1_exp = p1_data.get(p1_phase_export[ph], 0.0) or 0.0
                if p1_imp is not None:
                    raw_p = float(p1_imp) - float(p1_exp)   # netto

            # DSMR5 netto: subtract export if dedicated export sensor configured
            exp_eid = cfg.get(phase_export_keys.get(ph,""), "")
            if exp_eid and raw_p is not None:
                raw_exp = self._read_state(exp_eid)
                if raw_exp is not None:
                    try:
                        exp_w = self._calc.to_watts(exp_eid, raw_exp)
                        imp_w = self._calc.to_watts(pwr_key, raw_p)
                        raw_p = imp_w - exp_w   # netto (negative = export)
                    except Exception:
                        pass

            resolved = self._calc.resolve_phase(
                ph,
                power_entity=cfg.get(pwr_key,""),
                raw_power   =raw_p,
                raw_current =raw_a,
                raw_voltage =raw_v,
            )

            # FIX: pass current_a and voltage_v separately — don't let limiter recalculate
            self._limiter.update_phase(
                phase       = ph,
                current_a   = resolved.get("current_a") or 0.0,
                power_w     = resolved.get("power_w")   or 0.0,
                voltage_v   = resolved.get("voltage_v") or mains_v,
                derived_from= resolved.get("derived_from","direct"),
            )

            # Feed NILM — v1.8: smart fallback cascade
            #
            # Priority:
            #   1. Per-phase power sensor configured & valid  → best accuracy
            #   2. No phase sensor but total grid available   → split equally per phase
            #   3. Single-phase install                       → total on L1
            #
            # This ensures NILM always gets a meaningful signal even when
            # no per-phase sensors are installed.
            phase_pw = resolved.get("power_w")
            if phase_pw is not None:
                # v1.17.1 — Aftrekken van bekende stopcontact-vermogens per fase
                # zodat NILM alleen op het restsignaal hoeft te werken.
                # Apparaten die al exact gemeten worden via een smart plug hoeven
                # niet opnieuw door NILM gedetecteerd te worden.
                if self._hybrid:
                    anchored_by_phase = self._hybrid.get_anchored_power_per_phase()
                    socket_w = anchored_by_phase.get(ph, 0.0)
                    nilm_input_w = max(0.0, phase_pw - socket_w)
                    if socket_w > 10.0:
                        _LOGGER.debug(
                            "NILM %s: fase=%.0fW − stopcontact=%.0fW = restsignaal=%.0fW",
                            ph, phase_pw, socket_w, nilm_input_w,
                        )
                else:
                    nilm_input_w = phase_pw
                self._nilm.update_power(ph, nilm_input_w, source="per_phase")
            # (fallback handled below after all phases are processed)

        # v1.8: NILM fallback — if no per-phase power sensors, use total grid
        # Detect how many phases had real data
        phases_with_data = []
        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            if self._read_state(cfg.get(amp_key,"")) is not None or \
               self._read_state(cfg.get(pwr_key,"")) is not None:
                phases_with_data.append(ph)

        if not phases_with_data:
            # No per-phase sensors at all → distribute total grid power
            total_w = data.get("grid_power", 0.0)
            n       = len(phases)
            if n > 1:
                # Equal split — better than nothing; at least the total signature is preserved
                per_phase_w = total_w / n
                for ph in phases:
                    self._nilm.update_power(ph, per_phase_w, source="total_split")
            else:
                # Single phase — send total directly to L1
                self._nilm.update_power("L1", total_w, source="total_l1")

    def _get_phase_pid_states(self) -> dict:
        """Return PID state for all phase controllers (from multi-inverter manager)."""
        if self._multi_inv_manager:
            status = self._multi_inv_manager.get_status()
            return status.get("phase_pids", {})
        return {}

    def _calc_pv_payback(
        self,
        pv_forecast_today_kwh: float | None,
        price_info: dict | None,
        current_price: float,
    ) -> dict:
        """
        Bereken de terugverdientijd op basis van:
          - Geleerde jaarproductie (geëxtrapoleerd uit pv_forecast)
          - Huidige EPEX-prijs + net-terugleverprijs
          - Geconfigureerde investeringskosten (pv_investment_eur in config)
        Geeft {} terug als onvoldoende data.
        """
        investment_eur = float(self._config.get("pv_investment_eur", 0))
        if investment_eur <= 0 or not self._solar_learner:
            return {}

        # Geschatte jaarproductie in kWh
        total_wp = self._solar_learner.get_total_estimated_wp()
        if total_wp <= 0:
            return {}

        # Gebruik PV-forecast om correctiefactor te berekenen t.o.v. piekwaarden
        # Aanname: NL gemiddeld ~900 vollasturen per jaar per Wp (conservatief)
        vollasturen = float(self._config.get("pv_vollasturen", 900))
        annual_kwh_est = round(total_wp / 1000.0 * vollasturen, 0)

        # Opbrengst per jaar: mix van eigen gebruik (bespaarde inkoop) + terugleving
        # Gebruik actuele prijs als proxy; terugleverprijs typisch 30% van inkoop
        if not price_info:
            return {}
        avg_price = price_info.get("average_today") or current_price or 0.25
        avg_price = max(0.05, float(avg_price))

        # Config: percentage eigen gebruik (default 60%)
        eigenverbruik_pct = float(self._config.get("pv_eigenverbruik_pct", 60)) / 100.0
        eigenverbruik_pct = max(0.1, min(1.0, eigenverbruik_pct))

        # Eigen gebruik bespaart volle inkoopprijs; overschot levert terugleverprijs op
        feed_in_price = float(self._config.get("pv_feed_in_price_eur_kwh", avg_price * 0.30))
        revenue_per_kwh = (
            eigenverbruik_pct * avg_price
            + (1.0 - eigenverbruik_pct) * feed_in_price
        )
        annual_revenue_eur = round(annual_kwh_est * revenue_per_kwh, 2)

        if annual_revenue_eur <= 0:
            return {}

        payback_years = round(investment_eur / annual_revenue_eur, 1)
        roi_10y = round((annual_revenue_eur * 10 - investment_eur) / investment_eur * 100, 1)

        return {
            "investment_eur":     investment_eur,
            "total_wp_est":       total_wp,
            "annual_kwh_est":     annual_kwh_est,
            "annual_revenue_eur": annual_revenue_eur,
            "payback_years":      payback_years,
            "roi_10y_pct":        roi_10y,
            "avg_price_used":     round(avg_price, 4),
            "eigenverbruik_pct":  round(eigenverbruik_pct * 100, 1),
        }

    def _generate_insights(
        self,
        data:           dict,
        price_info:     dict,
        inverter_data:  list,
        peak_data:      dict,
        balance_data:   dict,
        phase_currents: dict,
        solar_surplus:  float,
        boiler_decs:    list,
    ) -> str:
        """
        Generate a human-readable insights/advice string.
        Shown as a text sensor in HA.
        """
        tips: list[str] = []

        price = price_info.get("current")
        if price is not None:
            if price < 0:
                tips.append(f"⚡ Negatieve prijs ({price:.4f} €/kWh): overweeg zware lasten in te schakelen of PV te begrenzen.")
            elif price_info.get("in_cheapest_3h"):
                tips.append(f"💰 Je bent nu in de goedkoopste 3 uur (prijs {price:.4f} €/kWh). Goed moment voor vaatwasser/boiler.")
            elif price > price_info.get("avg_today", 0) * 1.5:
                tips.append(f"💸 Dure stroom: prijs {price:.4f} €/kWh is {((price/max(price_info.get('avg_today',0.001),0.001)-1)*100):.0f}% boven daaggemiddelde.")

        if solar_surplus > 500:
            tips.append(f"☀️ PV-surplus {solar_surplus:.0f}W: zet boiler/EV aan om exportverlies te minimaliseren.")

        for inv in inverter_data:
            if inv.get("clipping"):
                tips.append(f"⚠️ Clipping bij {inv['label']}: {inv['current_w']:.0f}W ≈ max. Panelen leveren meer dan omvormer aankan.")
            elif inv.get("utilisation_pct",0) < 10 and inv.get("confident"):
                pass  # Don't warn about low yield at night

        if peak_data.get("active"):
            tips.append(f"📊 Piekafschaving actief: verbruik {data.get('import_power_w',0):.0f}W > limiet {peak_data.get('limit_w',0):.0f}W.")

        if balance_data.get("imbalance_a", 0) > 5:
            tips.append(f"⚖️ Fase-onbalans: {balance_data.get('imbalance_a',0):.1f}A verschil. Overweeg lasten te herverdelingen.")

        # Startup / learning phase: geen EPEX-data of te weinig data
        if not tips:
            if price_info and price_info.get("current") is not None:
                tips.append("✅ Alles in orde — geen bijzonderheden op dit moment.")
            else:
                tips.append("⏳ CloudEMS leert je installatie kennen. Tips verschijnen zodra EPEX-prijzen beschikbaar zijn.")

        return " | ".join(tips)

    # ── Decision log ──────────────────────────────────────────────────────────

    def _log_decision(self, category: str, message: str) -> None:
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "category": category,
            "message":  message,
        }
        self._decision_log.appendleft(entry)
        _LOGGER.debug("CloudEMS decision [%s]: %s", category, message)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_nilm_device_found(self, device: DetectedDevice, all_matches: list):
        _LOGGER.info("CloudEMS NILM: device found → %s (%.0f%%)", device.name, device.confidence*100)
        self.async_update_listeners()

    def _on_nilm_device_update(self, device: DetectedDevice):
        self.async_update_listeners()

    async def _set_ev_current(self, ampere: float):
        entity_id = self._config.get("ev_charger_entity","")
        if not entity_id:
            return
        await self.hass.services.async_call(
            "number","set_value",{"entity_id": entity_id, "value": ampere}, blocking=False,
        )

    async def _set_solar_curtailment(self, pct: float):
        pass  # Handled by multi_inverter_manager
