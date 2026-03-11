# -*- coding: utf-8 -*-
"""
CloudEMS NILM Detector — v1.30.0

Changes vs v1.3:
  - User feedback: correct / incorrect / maybe  per device
  - Energy tracking: kWh per day / week / month / year per detected device
  - Devices visible as HA sensor entities (via coordinator → sensor.py)
  - Persistent storage of all device data
  - Confidence shown on each device

Changes v1.30 (NILM intelligence overhaul):
  - DevicePowerProfile: per-device learned power profile (EWMA, std dev, duty cycle)
  - Off-edge suppression: negative deltas match directly to active device profiles,
    no re-classification through the database (eliminates off-event false positives)
  - Simultaneous device stack: running power stack per phase; delta computed against
    the sum of known active devices, not just the baseline (wasmachine+magnetron fix)
  - Energy anomaly integration: confidence penalty when monthly kWh diverges >3.5σ
  - Auto-confirm after N consistent sessions (configurable, default 8)
  - Session fingerprint dedup: cycling devices (refrigerator etc.) recognized across
    sessions via DevicePowerProfile, not as new detections each cycle
  - nilm_device_profile service: full per-device stats accessible from HA
  - Profile persistence: DevicePowerProfile stored in separate HA storage key

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional, Callable, Any

from homeassistant.helpers.storage import Store
from homeassistant.core import HomeAssistant

from .database import NILMDatabase
from .false_positive_memory import FalsePositiveMemory
from .co_occurrence import CoOccurrenceDetector
from .macro_load_tracker import MacroLoadTracker
from .battery_uncertainty import BatteryUncertaintyTracker
from .local_ai import LocalAIClassifier, PowerEvent
from .cloud_ai import CloudAIClassifier
from .power_learner import PowerLearner
from .unsupervised_cluster import NILMEventClusterer
from ..const import (
    NILM_MIN_CONFIDENCE, NILM_HIGH_CONFIDENCE,
    NILM_MODE_DATABASE, NILM_MODE_LOCAL_AI, NILM_MODE_CLOUD_AI, NILM_MODE_OLLAMA,
    NILM_FEEDBACK_CORRECT, NILM_FEEDBACK_INCORRECT, NILM_FEEDBACK_MAYBE,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_NILM_ENERGY,
)

STORAGE_KEY_NILM_LEARNER = "cloudems_nilm_learner_v1"

_LOGGER = logging.getLogger(__name__)

# These defaults are overridden at runtime by AdaptiveNILMThreshold
POWER_CHANGE_THRESHOLD = 25.0  # W — starting value; adapts based on signal noise
WINDOW_SIZE            = 10
DEBOUNCE_TIME          = 2.0   # seconds

# ── Auto-off timeouts per apparaattype ────────────────────────────────────────
# Als een apparaat langer AAN is dan zijn type-maximum, wordt het automatisch
# op UIT gezet (beschermt tegen gemiste off-edges of sensor-dropouts).
# Waarden zijn ruim gekozen: NILM mag geen vals-uit triggeren bij normaal gebruik.
DEVICE_MAX_ON_TIMES: dict = {
    "kettle":          420,    #  7 min  — ketel kookt nooit langer
    "microwave":       2400,   # 40 min  — magnetron
    "washing_machine": 9000,   # 2.5 h   — inclusief eco-programma
    "dryer":           9000,   # 2.5 h
    "dishwasher":      9000,   # 2.5 h   — intensief programma
    "oven":            18000,  #  5 h    — langzame braadstukken
    "boiler":          4500,   # 75 min  — boiler cycli
    "refrigerator":    1200,   # 20 min  — compressor-cyclus
    "ev_charger":      57600,  # 16 h    — nachtladen
    "heat_pump":       21600,  #  6 h
    "entertainment":   28800,  #  8 h
    "computer":        50400,  # 14 h
    "light":           86400,  # 24 h    — lichten worden niet auto-uit gezet
}

# ── Power-stack: meerdere instanties ─────────────────────────────────────────
# Apparaattypen die in meerdere exemplaren kunnen voorkomen (bijv. 2 koelkasten).
# Voor deze types wordt bij een nieuw on-event altijd een nieuw apparaat aangemaakt
# als het vermogensniveau >30% afwijkt van bestaande instanties.
MULTI_INSTANCE_TYPES: frozenset = frozenset({
    "refrigerator", "light", "entertainment", "socket", "power_tool",
})

# ── Steady-state validatie ────────────────────────────────────────────────────
STEADY_STATE_DELAY_S   = 20.0   # seconden na on-event → validatiemoment (was 35s, sneller false positive removal)
STEADY_STATE_MIN_RATIO = 0.40   # baseline moet minstens 40% van verwacht vermogen gestegen zijn (was 50%)



# ── PV-delta maskering ────────────────────────────────────────────────────────
# Zonnepanelen veranderen van output bij wolken/zon-overgangen. Die delta is
# zichtbaar in het netsignaal maar is GEEN huishoudapparaat. Als de PV-output
# snel verandert, negeren we NILM-events op alle fasen gedurende PV_MASK_WINDOW_S.
# Drempel: 80W verandering in één 10s-tick = zeker een wolk of ochtend/avond ramp.
PV_DELTA_MASK_THRESHOLD_W = 80.0   # W/tick (10s) → maskeer NILM
PV_MASK_WINDOW_S          = 25.0   # seconden na PV-sprong maskeren

# ── Batterij-ramp maskering ───────────────────────────────────────────────────
# Batterij-omvormers rampen op in stappen. Die stappen zijn echte power-edges
# die NILM als "zware boiler" of "warmtepomp" leest. Als de batterij in de
# laatste BATT_RAMP_WINDOW_S seconden meer dan BATT_RAMP_TOTAL_W veranderd is,
# blokkeren we nieuwe NILM-events.
BATT_RAMP_WINDOW_S    = 30.0   # seconden waarbinnen we naar ramp zoeken
BATT_RAMP_TOTAL_W     = 300.0  # W totale verandering = ramp gedetecteerd
BATT_RAMP_MASK_S      = 20.0   # extra maskeervenster na ramp-detectie

class AdaptiveNILMThreshold:
    """
    Automatically adjusts the power-change detection threshold based on
    the measured noise floor of the grid signal.

    Algorithm:
      - Track a rolling window of per-sample |Δpower| values
      - Estimate noise as the 80th-percentile of those deltas
      - Set threshold = max(MIN, min(MAX, noise * 3.0))
        (3σ rule: events 3× above noise floor are real events)
      - Persist learned threshold across HA restarts

    This means:
      - Quiet installations (good P1 meters) → threshold drops to ~10W
      - Noisy installations (cheap clamp meters) → threshold stays high
    """
    def __init__(self, initial: float = 25.0,
                 min_w: float = 8.0, max_w: float = 100.0,
                 window: int = 120):
        from ..const import NILM_MIN_THRESHOLD_W, NILM_MAX_THRESHOLD_W, NILM_NOISE_WINDOW
        self._threshold   = initial
        self._min_w       = min_w
        self._max_w       = max_w
        self._window      = window
        self._deltas: list = []   # rolling |Δpower| values
        self._prev_power: dict = {}
        self._adapted     = False

    @property
    def threshold(self) -> float:
        return self._threshold

    def update(self, phase: str, power_w: float) -> None:
        """Feed a new power reading; adapt threshold from noise."""
        prev = self._prev_power.get(phase)
        if prev is not None:
            delta = abs(power_w - prev)
            self._deltas.append(delta)
            if len(self._deltas) > self._window:
                self._deltas.pop(0)
            if len(self._deltas) >= 30:
                self._recalculate()
        self._prev_power[phase] = power_w

    def _recalculate(self) -> None:
        import statistics
        sorted_d = sorted(self._deltas)
        # 80th percentile of idle deltas → noise floor
        idx       = int(len(sorted_d) * 0.80)
        noise_p80 = sorted_d[idx]
        # threshold = 3× noise floor, clamped
        new_t = max(self._min_w, min(self._max_w, noise_p80 * 3.0))
        if abs(new_t - self._threshold) > 2.0:
            _LOGGER.debug(
                "NILM adaptive threshold: %.1fW → %.1fW (noise p80=%.1fW)",
                self._threshold, new_t, noise_p80,
            )
            self._threshold  = round(new_t, 1)
            self._adapted    = True

    def set_away_mode(self, away: bool) -> None:
        """
        v1.32: Verhoog drempel bij afwezigheid zodat koelkast/router-fluctuaties
        niet als nieuwe NILM-apparaten worden geregistreerd.
        Threshold × 2 bij afwezigheid, terug naar geleerde waarde bij thuiskomst.
        """
        if away and not getattr(self, "_away_mode", False):
            self._away_mode       = True
            self._threshold_home  = self._threshold
            self._threshold       = min(self._max_w, self._threshold * 2.0)
            _LOGGER.debug(
                "NILM: afwezigheidsmodus — drempel %.0fW → %.0fW",
                self._threshold_home, self._threshold,
            )
        elif not away and getattr(self, "_away_mode", False):
            self._away_mode  = False
            self._threshold  = getattr(self, "_threshold_home", self._threshold)
            _LOGGER.debug("NILM: thuismodus — drempel terug naar %.0fW", self._threshold)

    def to_dict(self) -> dict:
        return {
            "threshold_w":  self._threshold,
            "adapted":      self._adapted,
            "away_mode":    getattr(self, "_away_mode", False),
            "samples":      len(self._deltas),
            "noise_p80_w":  round(sorted(self._deltas)[int(len(self._deltas)*0.8)], 1)
                            if len(self._deltas) >= 10 else None,
        }


@dataclass
class DeviceEnergy:
    """Per-device cumulative energy tracking."""
    device_id:    str
    today_kwh:    float = 0.0
    week_kwh:     float = 0.0
    month_kwh:    float = 0.0
    year_kwh:     float = 0.0
    total_kwh:    float = 0.0
    last_reset_day:   str = ""
    last_reset_week:  str = ""
    last_reset_month: str = ""
    last_reset_year:  str = ""

    # v2.2.2: sessie-statistieken
    session_count:      int   = 0      # totaal aantal voltooide sessies (aan→uit)
    total_on_seconds:   float = 0.0    # totale brandtijd in seconden
    last_12_months_kwh: list  = field(default_factory=list)  # [kwh_maand-11, ..., kwh_deze_maand]
    _last_month_key:    str   = field(default="", repr=False, compare=False)

    @property
    def avg_duration_min(self) -> float:
        """Gemiddelde sessieduur in minuten. 0.0 als geen sessies."""
        if self.session_count <= 0:
            return 0.0
        return round(self.total_on_seconds / self.session_count / 60.0, 1)

    def record_session(self, duration_seconds: float) -> None:
        """Registreer een voltooide sessie (apparaat ging uit)."""
        if duration_seconds > 5:  # negeer flicker < 5 s
            self.session_count     += 1
            self.total_on_seconds  += duration_seconds

    def add_kwh(self, kwh: float, ts: float) -> None:
        now     = datetime.fromtimestamp(ts, tz=timezone.utc)
        day_k   = now.strftime("%Y-%m-%d")
        week_k  = now.strftime("%Y-W%W")
        month_k = now.strftime("%Y-%m")
        year_k  = now.strftime("%Y")

        if self.last_reset_day   != day_k:   self.today_kwh  = 0.0; self.last_reset_day   = day_k
        if self.last_reset_week  != week_k:  self.week_kwh   = 0.0; self.last_reset_week  = week_k
        if self.last_reset_month != month_k: self.month_kwh  = 0.0; self.last_reset_month = month_k
        if self.last_reset_year  != year_k:  self.year_kwh   = 0.0; self.last_reset_year  = year_k

        self.today_kwh  = round(self.today_kwh  + kwh, 4)
        self.week_kwh   = round(self.week_kwh   + kwh, 4)
        self.month_kwh  = round(self.month_kwh  + kwh, 4)
        self.year_kwh   = round(self.year_kwh   + kwh, 4)
        self.total_kwh  = round(self.total_kwh  + kwh, 4)

        # v2.2.2: rol maand-geschiedenis bij (last_12_months_kwh)
        if self._last_month_key != month_k:
            if self._last_month_key:
                # Vorige maand afsluiten — voeg toe aan history
                self.last_12_months_kwh.append(round(self.month_kwh, 3))
                if len(self.last_12_months_kwh) > 12:
                    self.last_12_months_kwh = self.last_12_months_kwh[-12:]
            self._last_month_key = month_k

    def to_dict(self) -> dict:
        return {
            "today_kwh":    self.today_kwh,
            "week_kwh":     self.week_kwh,
            "month_kwh":    self.month_kwh,
            "year_kwh":     self.year_kwh,
            "total_kwh":    self.total_kwh,
            "last_reset_day":   self.last_reset_day,
            "last_reset_week":  self.last_reset_week,
            "last_reset_month": self.last_reset_month,
            "last_reset_year":  self.last_reset_year,
            # v2.2.2: sessie-statistieken
            "session_count":      self.session_count,
            "total_on_seconds":   self.total_on_seconds,
            "last_12_months_kwh": self.last_12_months_kwh,
        }


@dataclass
class DetectedDevice:
    """A device detected via NILM."""
    device_id:      str
    device_type:    str
    name:           str
    confidence:     float
    current_power:  float
    is_on:          bool
    source:         str             # database / local_ai / cloud_ai / ollama
    confirmed:      bool = False
    detection_count:int  = 1
    last_seen:      float = field(default_factory=time.time)
    phase:          str   = "L1"
    on_events:      int   = 0
    pending_confirmation: bool = False

    # v1.4 — user feedback
    user_feedback:  str   = ""      # correct / incorrect / maybe / ""
    user_name:      str   = ""      # user-corrected name
    user_type:      str   = ""      # user-corrected device type

    # v1.20 — user label management
    user_hidden:    bool  = False   # user explicitly hid this device from dashboard
    user_suppressed: bool = False   # user declined/suppressed this detection — never show again

    # v1.20 — room meter: originating HA entity for area registry lookup
    source_entity_id: str = ""      # entity_id of smart plug / power sensor that anchored this device

    # v2.2.5 — LLM naam-suggestie voor generic apparaten
    suggested_name: str = ""        # door LLM voorgestelde naam (nog niet door gebruiker bevestigd)

    # v2.4.18 — dag/nacht profiel: bijhouden in welke tijdvakken het apparaat actief is
    # Slaat on_events op per tijdvak: {"day": n, "evening": n, "night": n}
    # dag=06-18u, avond=18-23u, nacht=23-06u
    time_profile: dict = field(default_factory=dict)

    # v1.4 — energy tracking (runtime; persisted separately)
    energy: DeviceEnergy = field(default_factory=lambda: DeviceEnergy(device_id=""))
    _on_start_ts: float  = field(default=0.0, repr=False, compare=False)

    def tick_energy(self, ts: float) -> None:
        """Called every 10 s while device is on. Accumulates kWh."""
        if self.is_on and self.current_power > 0:
            kwh = (self.current_power / 1000.0) * (10.0 / 3600.0)
            self.energy.add_kwh(kwh, ts)

    @property
    def display_name(self) -> str:
        return self.user_name or self.name

    @property
    def display_type(self) -> str:
        return self.user_type or self.device_type

    @property
    def effective_confidence(self) -> float:
        if self.user_feedback == NILM_FEEDBACK_CORRECT:
            return 1.0
        if self.user_feedback == NILM_FEEDBACK_INCORRECT:
            return 0.0
        # Tijdsgebaseerde confidence decay: elk apparaat dat langer dan 7 dagen
        # niet gezien is, verliest geleidelijk vertrouwen (max -30% na 30 dagen).
        # Beschermt bevestigde apparaten: confirmed devices decayen niet.
        if not self.confirmed:
            age_days = (time.time() - self.last_seen) / 86400.0
            if age_days > 7:
                decay = min(0.30, (age_days - 7) / 23.0 * 0.30)  # 0→30% over 7-30 dagen
                return max(0.0, round(self.confidence - decay, 3))
        return self.confidence

    def to_dict(self) -> dict:
        # current_on_duration_s: seconden dat het apparaat nu al AAN is (0 als UIT)
        _now = time.time()
        current_on_s = (_now - self._on_start_ts) if (self.is_on and self._on_start_ts > 0) else 0.0
        return {
            "device_id":      self.device_id,
            "device_type":    self.device_type,
            "name":           self.name,
            "confidence":     round(self.confidence, 3),
            "current_power":  self.current_power,
            "is_on":          self.is_on,
            "source":         self.source,
            "confirmed":      self.confirmed,
            "detection_count":self.detection_count,
            "last_seen":      self.last_seen,
            "phase":          self.phase,
            "on_events":      self.on_events,
            "pending":        self.pending_confirmation,
            "user_feedback":  self.user_feedback,
            "user_name":      self.user_name,
            "user_type":      self.user_type,
            "user_hidden":    self.user_hidden,
            "user_suppressed": self.user_suppressed,
            "source_entity_id": self.source_entity_id,
            "suggested_name": self.suggested_name,
            "time_profile":   self.time_profile,
            "energy":         self.energy.to_dict(),
            # v4.1: ondersteuning voor overduration detectie
            "current_on_duration_s": round(current_on_s, 1),
            "avg_duration_min":      self.energy.avg_duration_min,
            "session_count":         self.energy.session_count,
        }


class NILMDetector:
    """
    Main NILM detector — raw power → edge detection → classify → track.
    """

    def __init__(
        self,
        model_path: str,
        api_key: Optional[str],
        session: Any,
        on_device_found:  Optional[Callable] = None,
        on_device_update: Optional[Callable] = None,
        ollama_config:    Optional[dict]     = None,
        ai_provider:      str                = "none",
        hass:             Any                = None,
    ):
        from ..const import AI_PROVIDER_OLLAMA
        self._hass     = hass
        self._db       = NILMDatabase()
        self._local_ai = LocalAIClassifier(model_path)
        self._cloud_ai = CloudAIClassifier(api_key, session, provider=ai_provider)
        self._ollama_config = ollama_config or {}

        # Wire Ollama settings into CloudAIClassifier
        if ollama_config:
            self._cloud_ai.ollama_host  = ollama_config.get("host", "localhost")
            self._cloud_ai.ollama_port  = ollama_config.get("port", 11434)
            self._cloud_ai.ollama_model = ollama_config.get("model", "llama3")

        self._ai_provider = ai_provider

        self._on_device_found  = on_device_found
        self._on_device_update = on_device_update

        # v2.4.17: warmup periode — hogere drempel in eerste 24 uur na start
        self._started_at: float = time.time()

        # v2.4.17: adaptieve drempels per device_type vanuit coordinator feedback
        self._adaptive_overrides: dict = {}  # {device_type: {min_events: int}}

        # v2.4.19: friendly names van geblokkeerde entiteiten voor naam-gebaseerde filter
        self._blocked_friendly_names: set = set()

        self._power_buffers: Dict[str, deque] = {
            "L1": deque(maxlen=WINDOW_SIZE),
            "L2": deque(maxlen=WINDOW_SIZE),
            "L3": deque(maxlen=WINDOW_SIZE),
        }
        self._last_event_time: Dict[str, float] = {}
        self._baseline_power: Dict[str, float]  = {"L1":0,"L2":0,"L3":0}
        self._devices: Dict[str, DetectedDevice] = {}
        self._active_events: Dict[str, str] = {}
        self._store_devices: Optional[Store] = None
        self._store_energy:  Optional[Store] = None
        self._last_energy_save = 0.0
        self._storage_loaded: bool = False   # True after async_load() completes

        # v1.8: adaptive threshold
        self._adaptive = AdaptiveNILMThreshold()

        # v1.8: track which sensor inputs are feeding NILM
        self._sensor_input_log: Dict[str, str] = {}   # phase → source description

        # v1.7: diagnostics
        self._diag_events_total: int = 0
        self._diag_events_classified: int = 0
        self._diag_events_missed: int = 0
        self._diag_last_event_ts: float = 0.0
        self._diag_last_event_delta: float = 0.0
        self._diag_last_match: str = ""
        self._diag_log: list = []     # ring buffer, last 20 events

        # Formele event-hooks — geregistreerd via register_event_hook()
        # Callback-signatuur: cb(delta_w: float, timestamp: float) -> None
        self._event_hooks: list = []

        # v1.16: Ollama-specific diagnostics
        self._ollama_calls_total: int = 0
        self._ollama_calls_success: int = 0
        self._ollama_calls_failed: int = 0
        self._ollama_last_success_ts: float = 0.0
        self._ollama_last_error: str = ""
        self._ollama_last_response_ms: float = 0.0
        self._ollama_avg_response_ms: float = 0.0
        self._ollama_log: list = []   # ring buffer, last 20 Ollama decisions

        # v1.16: known battery power — used to skip false NILM edges
        self._battery_power_w: float = 0.0

        # v1.24: known infrastructure sensor power values (W).
        # Updated every cycle from coordinator. Used to suppress NILM events whose
        # delta closely matches a configured sensor (grid, PV, EV charger, heat pump).
        # key = sensor label, value = abs power in W
        self._infra_powers: dict = {}

        # v1.24: battery transition cooldown — timestamp and delta of last large
        # battery power change. NILM events similar in magnitude are suppressed
        # for BATTERY_COOLDOWN_S seconds after a battery ramp.
        self._battery_last_delta_w: float = 0.0
        self._battery_last_delta_ts: float = 0.0
        self._battery_prev_power_w: float = 0.0

        # v1.24: PV-delta maskering
        # _pv_power_prev: PV-vermogen vorige tick (om delta te berekenen)
        # _pv_mask_until: timestamp tot wanneer NILM-events geblokkeerd zijn door PV-sprong
        self._pv_power_prev: float = 0.0
        self._pv_mask_until: float = 0.0

        # v1.24: Batterij-ramp buffer
        # Sla de laatste N batterijmetingen op (ts, power_w) zodat we de
        # totale vermogensverandering over BATT_RAMP_WINDOW_S kunnen berekenen.
        self._batt_ramp_buffer: list = []   # [(ts, power_w), ...]
        self._batt_ramp_mask_until: float = 0.0

        # v1.17: Hybride NILM verrijkingslaag (optioneel — wordt gezet door coordinator)
        self._hybrid: Optional[Any] = None

        # v1.20: entity_ids van door de gebruiker geconfigureerde sensoren (grid, PV, P1,
        # gas, warmtepomp) — worden altijd gefilterd uit NILM-detecties.
        self._config_sensor_eids: set = set()

        # v1.21: steady-state validatie — wachtrij van on-events die na 35 s gecheckt
        # worden om te verifiëren dat de baseline daadwerkelijk gestegen is.
        self._pending_validations: list = []

        # v1.31: FalsePositiveMemory — leert afgewezen power-signatures
        self._fp_memory = FalsePositiveMemory(hass)
        # v4.5: co-occurrence detector
        self._co_occurrence: Optional[CoOccurrenceDetector] = CoOccurrenceDetector()

        # v1.31: MacroLoadTracker — ruis van grootverbruikers onderdrukken
        self._macro_tracker = MacroLoadTracker()

        # v1.31: BatteryUncertaintyTracker — traag/stale gemeten batterijen (Nexus etc.)
        self._batt_uncertainty = BatteryUncertaintyTracker()

        # v1.22: HMM sessietracking callback (wordt gezet door coordinator)
        # Signature: hmm_callback(device_type, phase, power_w, delta_w, ts) → None
        self._hmm_callback: Optional[Any] = None

        # v1.23: Bayesian posterior classifier (BayesianNILMClassifier instantie)
        self._bayes_callback: Optional[Any] = None

        # v1.25: PowerLearner — zelflerend vermogensprofiel + slimme off-edge matching
        self._power_learner: PowerLearner = PowerLearner(auto_confirm_enabled=True)
        self._store_learner: Optional[Any] = None
        self._energy_anomaly_ids: set = set()

        # v4.0.5: Time pattern learner (wordt gezet via set_stores)
        self._time_pattern_learner: Optional[Any] = None
        self._store_time_patterns:  Optional[Any] = None
        self._store_co_occurrence:  Optional[Any] = None  # v4.5

        # v4.4: Unsupervised clustering — groepeert onbekende events automatisch
        # en vraagt gebruiker om bevestiging als cluster >= CLUSTER_MIN_EVENTS bereikt.
        self._clusterer: NILMEventClusterer = NILMEventClusterer(hass)

        _LOGGER.info("CloudEMS NILM Detector v1.25 initialized")

    @property
    def time_pattern_learner(self) -> "Optional[Any]":
        """Publieke alias voor _time_pattern_learner (backwards compat)."""
        return self._time_pattern_learner

    # ── Storage setup ─────────────────────────────────────────────────────────

    def set_stores(self, store_devices: Store, store_energy: Store,
                   store_learner=None, store_time_patterns=None,
                   store_co_occurrence=None) -> None:
        self._store_devices       = store_devices
        self._store_energy        = store_energy
        self._store_learner       = store_learner
        self._store_time_patterns = store_time_patterns
        self._store_co_occurrence = store_co_occurrence
        # Instantieer TimePatternLearner zodra store beschikbaar is
        if store_time_patterns is not None and self._time_pattern_learner is None:
            try:
                from .time_pattern_learner import TimePatternLearner
                self._time_pattern_learner = TimePatternLearner(store_time_patterns)
                _LOGGER.debug("CloudEMS NILM: TimePatternLearner geïnitialiseerd")
            except Exception as _tpl_err:
                _LOGGER.warning("TimePatternLearner init mislukt: %s", _tpl_err)

    def set_pv_power(self, pv_w: float, timestamp: float | None = None) -> None:
        """Informeer NILM over het huidige PV-vermogen (W).

        v1.24: Als de PV-output in één 10s-tick met meer dan PV_DELTA_MASK_THRESHOLD_W
        verandert (wolk, ochtend/avond-ramp), worden alle NILM-events voor
        PV_MASK_WINDOW_S geblokkeerd. PV-veranderingen zijn zichtbaar in het
        netsignaal maar zijn GEEN huishoudapparaten.

        Aanroepen vanuit de coordinator elke 10s, vóór update_power().
        """
        import time as _t
        ts = timestamp if timestamp is not None else _t.time()
        delta = abs(pv_w - self._pv_power_prev)
        if delta >= PV_DELTA_MASK_THRESHOLD_W:
            self._pv_mask_until = ts + PV_MASK_WINDOW_S
            _LOGGER.debug(
                "NILM PV-mask actief: ΔPV=%.0fW → NILM geblokkeerd tot +%.0fs",
                delta, PV_MASK_WINDOW_S,
            )
        self._pv_power_prev = pv_w

    def set_config_sensor_eids(self, entity_ids: set) -> None:
        """Register entity_ids of CloudEMS-configured sensors (grid, PV, P1, gas, etc.)."""
        self._config_sensor_eids = {e for e in entity_ids if e}
        # Purge any devices already learned from these sensors
        to_remove = [
            did for did, dev in self._devices.items()
            if getattr(dev, "source_entity_id", "") in self._config_sensor_eids
        ]
        for did in to_remove:
            _LOGGER.info("NILM: verwijder config-sensor apparaat '%s' uit _devices", did)
            self._devices.pop(did, None)

        # v2.4.18: reset baselijnen die buiten fysiek bereik liggen (bijv. door
        # eerdere export-bug waarbij negatieve waarden de EWMA vertekenden).
        for phase, val in self._baseline_power.items():
            if val < 0 or val > 6000:
                _LOGGER.warning(
                    "NILM: basislijn %s (%.0fW) buiten bereik — gereset naar 0",
                    phase, val,
                )
                self._baseline_power[phase] = 0.0

    def set_adaptive_overrides(self, overrides: dict) -> None:
        """Ontvang adaptieve drempelwaarden per device_type vanuit coordinator.

        overrides: {device_type: {min_events: int, ...}}
        """
        self._adaptive_overrides = overrides or {}

    def set_blocked_friendly_names(self, names: set) -> None:
        """Registreer friendly names van geblokkeerde infra-entiteiten.

        Apparaten waarvan de naam overeenkomt worden gefilterd uit get_devices_for_ha(),
        ook als ze geen source_entity_id hebben.
        """
        self._blocked_friendly_names = {n.lower().strip() for n in names if n}

    def set_esphome_features(
        self,
        power_factor_l1:    float | None = None,
        power_factor_l2:    float | None = None,
        power_factor_l3:    float | None = None,
        inrush_peak_l1:     float | None = None,
        inrush_peak_l2:     float | None = None,
        inrush_peak_l3:     float | None = None,
        rise_time_l1:       float | None = None,
        rise_time_l2:       float | None = None,
        rise_time_l3:       float | None = None,
        reactive_power_l1:  float | None = None,
        reactive_power_l2:  float | None = None,
        reactive_power_l3:  float | None = None,
        thd_l1:             float | None = None,
        thd_l2:             float | None = None,
        thd_l3:             float | None = None,
        # Backwards-compat aliassen (oude coordinator-versies)
        inrush_peak_a:      float | None = None,
        rise_time_ms:       float | None = None,
    ) -> None:
        """Sla ESPHome NILM-meter features op voor gebruik bij de volgende event-classificatie.

        Aangeroepen elke coordinator-cyclus als een DIY ESPHome-meter geconfigureerd is.
        Alle parameters zijn optioneel — ontbrekende features (None) worden volledig
        overgeslagen in classify() zodat gebruikers zonder ESP32 geen enkel effect merken.

        Graceful degradation: elk feature-blok in classify() controleert zelfstandig
        op None. Alleen aanwezige features beïnvloeden de confidence-scores.

        Ondersteunt zowel 1-fase als 3-fase ESPHome meters.
        """
        self._esp_power_factor: dict[str, float | None] = {
            "L1": power_factor_l1,
            "L2": power_factor_l2,
            "L3": power_factor_l3,
        }
        # Per-fase inrush en rise time — backwards compat: oude velden als fallback voor L1
        self._esp_inrush_peak: dict[str, float | None] = {
            "L1": inrush_peak_l1 if inrush_peak_l1 is not None else inrush_peak_a,
            "L2": inrush_peak_l2,
            "L3": inrush_peak_l3,
        }
        # Rise time in seconden per fase
        def _ms_to_s(v: float | None) -> float | None:
            return (v / 1000.0) if v is not None else None
        self._esp_rise_time_s: dict[str, float | None] = {
            "L1": _ms_to_s(rise_time_l1) if rise_time_l1 is not None else _ms_to_s(rise_time_ms),
            "L2": _ms_to_s(rise_time_l2),
            "L3": _ms_to_s(rise_time_l3),
        }
        # Reactief vermogen in VAR per fase (None = niet beschikbaar)
        self._esp_reactive_power: dict[str, float | None] = {
            "L1": reactive_power_l1,
            "L2": reactive_power_l2,
            "L3": reactive_power_l3,
        }
        # THD% per fase (None = niet beschikbaar — ESP32 zonder FFT-firmware)
        self._esp_thd: dict[str, float | None] = {
            "L1": thd_l1,
            "L2": thd_l2,
            "L3": thd_l3,
        }

    def set_infra_powers(self, powers: dict) -> None:
        """Update known infrastructure sensor power values.

        Called every coordinator cycle. powers = {label: abs_power_w}, e.g.:
          {"pv": 1840.0, "grid": -230.0, "ev_charger": 3700.0}

        Twee effecten:
        1. Toekomstige events worden geblokkeerd in _async_process_event als
           de delta overeenkomt met een bekende infra-sensor.
        2. Bestaande GELEERDE apparaten worden ge-purged als hun geleerde
           nominaal vermogen nauwkeurig overeenkomt (+-20%) met een infra-sensor.
           Dit ruimt EV/warmtepomp apparaten op die voor de configuratie werden
           geleerd. Smart-plug ankerapparaten worden nooit ge-purged.
        """
        self._infra_powers = {k: abs(v) for k, v in powers.items() if abs(v) > 20}

        # v1.31: grootverbruikers doorgeven aan MacroLoadTracker
        self._macro_tracker.update_from_infra(self._infra_powers)

        # Purge bestaande geleerde apparaten die matchen met een infra-sensor
        to_remove = []
        for did, dev in self._devices.items():
            if getattr(dev, "source", None) == "smart_plug":
                continue   # nooit stekker-apparaten verwijderen
            nom_w = getattr(dev, "nominal_power_w", None) or getattr(dev, "power_w", None) or 0
            if nom_w < 100:
                continue
            for label, infra_w in self._infra_powers.items():
                if infra_w < 100:
                    continue
                ratio = nom_w / infra_w
                if 0.80 <= ratio <= 1.20:
                    _LOGGER.info(
                        "NILM: verwijder geleerd apparaat '%s' (nominaal %.0fW) — "
                        "overeenkomst met infra-sensor '%s' (%.0fW)",
                        getattr(dev, "name", did), nom_w, label, infra_w,
                    )
                    to_remove.append(did)
                    break
        for did in to_remove:
            self._devices.pop(did, None)

    def register_event_hook(self, callback) -> None:
        """Registreer een callback die aangeroepen wordt bij elke NILM-powergebeurtenis.

        Formele interface zodat externe modules (zoals SmartPowerEstimator) niet
        afhankelijk zijn van interne attributen zoals _diag_log of _recent_events.

        Callback-signatuur:
            cb(delta_w: float, timestamp: float) -> None

        Meerdere callbacks zijn toegestaan. Elk wordt aangeroepen direct nadat
        _async_process_event klaar is — ook als er geen classificatie-match was.
        Dit stelt de SmartPowerEstimator in staat om de NILM-delta te correleren
        met aan/uit-overgangen van bekende HA-entiteiten.
        """
        if callback not in self._event_hooks:
            self._event_hooks.append(callback)

    def unregister_event_hook(self, callback) -> None:
        """Verwijder een eerder geregistreerde callback."""
        try:
            self._event_hooks.remove(callback)
        except ValueError:
            pass

    def update_battery_power(self, power_w: float) -> None:
        """Track battery power changes for cooldown suppression.

        Called every coordinator cycle alongside inject_battery().
        Records the magnitude of sudden battery ramps so that NILM events
        of similar size in the next BATTERY_COOLDOWN_S seconds are suppressed.
        """
        import time as _t
        delta = abs(power_w - self._battery_prev_power_w)
        if delta > 400:   # battery ramp of > 400W → record cooldown
            self._battery_last_delta_w  = delta
            self._battery_last_delta_ts = _t.time()
            _LOGGER.debug(
                "NILM: batterij ramp %.0fW→%.0fW (Δ%.0fW) — cooldown gestart",
                self._battery_prev_power_w, power_w, delta,
            )
        self._battery_prev_power_w = power_w
        self._battery_power_w = abs(power_w)

    async def async_load(self) -> None:
        await self._fp_memory.async_load()
        # v4.5: co-occurrence
        if self._co_occurrence and getattr(self, '_store_co_occurrence', None):
            await self._co_occurrence.async_load(self._store_co_occurrence)
        if self._store_devices:
            data = await self._store_devices.async_load() or {}
            for dev_data in data.get("devices", []):
                dev = DetectedDevice(
                    device_id      = dev_data["device_id"],
                    device_type    = dev_data.get("device_type","unknown"),
                    name           = dev_data.get("name",""),
                    confidence     = dev_data.get("confidence", 0.5),
                    current_power  = dev_data.get("current_power", 0.0),
                    is_on          = dev_data.get("is_on", False),
                    source         = dev_data.get("source","database"),
                    confirmed      = dev_data.get("confirmed", False),
                    detection_count= dev_data.get("detection_count", 1),
                    last_seen      = dev_data.get("last_seen", time.time()),
                    phase          = dev_data.get("phase","L1"),
                    on_events      = dev_data.get("on_events", 0),
                    pending_confirmation = dev_data.get("pending", False),
                    user_feedback  = dev_data.get("user_feedback",""),
                    user_name      = dev_data.get("user_name",""),
                    user_type      = dev_data.get("user_type",""),
                    user_hidden    = dev_data.get("user_hidden", False),
                    user_suppressed = dev_data.get("user_suppressed", False),
                    source_entity_id = dev_data.get("source_entity_id", ""),
                    suggested_name   = dev_data.get("suggested_name", ""),
                    time_profile     = dev_data.get("time_profile", {}),
                )
                dev.energy.device_id = dev.device_id
                self._devices[dev.device_id] = dev

        if self._store_energy:
            edata = await self._store_energy.async_load() or {}
            for dev_id, edict in edata.items():
                if dev_id in self._devices:
                    e = self._devices[dev_id].energy
                    e.today_kwh   = edict.get("today_kwh",   0.0)
                    e.week_kwh    = edict.get("week_kwh",    0.0)
                    e.month_kwh   = edict.get("month_kwh",   0.0)
                    e.year_kwh    = edict.get("year_kwh",    0.0)
                    e.total_kwh   = edict.get("total_kwh",   0.0)
                    e.last_reset_day   = edict.get("last_reset_day",   "")
                    e.last_reset_week  = edict.get("last_reset_week",  "")
                    e.last_reset_month = edict.get("last_reset_month", "")
                    e.last_reset_year  = edict.get("last_reset_year",  "")
                    # v2.2.2: sessie-statistieken
                    e.session_count      = edict.get("session_count",      0)
                    e.total_on_seconds   = edict.get("total_on_seconds",   0.0)
                    e.last_12_months_kwh = edict.get("last_12_months_kwh", [])

        # v1.25: PowerLearner laden
        if self._store_learner:
            ldata = await self._store_learner.async_load() or {}
            self._power_learner.load(ldata)

        # v4.4: Unsupervised clusterer laden
        await self._clusterer.async_setup()

        _LOGGER.info("CloudEMS NILM: loaded %d devices", len(self._devices))
        self._storage_loaded = True

    async def async_save(self) -> None:
        if self._store_devices:
            await self._fp_memory.async_save()
            # v4.5: co-occurrence
            if self._co_occurrence and getattr(self, "_store_co_occurrence", None):
                await self._co_occurrence.async_save()
            await self._store_devices.async_save({
                "devices": [d.to_dict() for d in self._devices.values()]
            })
        if self._store_energy and time.time() - self._last_energy_save > 60:
            edata = {d.device_id: d.energy.to_dict() for d in self._devices.values()}
            await self._store_energy.async_save(edata)
            self._last_energy_save = time.time()
        # v1.25: PowerLearner state opslaan (elke 5 min)
        if self._store_learner and time.time() - self._last_energy_save > 300:
            await self._store_learner.async_save(self._power_learner.to_dict())
        # v4.4: Unsupervised clusterer opslaan
        await self._clusterer.async_save()

    # ── Power update ──────────────────────────────────────────────────────────

    def update_power(self, phase: str, power_watt: float, timestamp: float = None,
                     source: str = "per_phase"):
        """Feed a new power reading for NILM edge detection.
        
        Args:
            phase:      'L1', 'L2' or 'L3'
            power_watt: power in Watts (positive = consumption)
            timestamp:  unix timestamp (defaults to now)
            source:     human label for diagnostics ('per_phase', 'total_split', 'total_l1')

        v1.21 changes:
          - rise_time_reliable=False is passed to database.classify() — polling-based
            detectors always produce rise_time ≈ 20 s which is meaningless for
            sub-second appliances; skipping it allows the power-weight to dominate.
          - Auto-off timeout: devices that have been 'on' beyond their type maximum
            are automatically flipped to off (protects against missed off-edges).
          - Steady-state validation: pending on-events are verified 35 s after
            detection; if the baseline has not risen as expected, confidence is halved.
        """
        if timestamp is None:
            timestamp = time.time()
        # v1.8: record sensor source for diagnostics
        self._sensor_input_log[phase] = source

        # v1.8: feed adaptive threshold
        self._adaptive.update(phase, power_watt)
        threshold = self._adaptive.threshold

        buf = self._power_buffers.get(phase)
        if buf is None:
            return
        buf.append((timestamp, power_watt))
        if len(buf) < 3:
            return

        recent   = list(buf)[-3:]
        avg      = sum(p for _, p in recent) / len(recent)
        baseline = self._baseline_power[phase]
        delta    = avg - baseline

        # Bij export (gemiddeld negatief) geen edges detecteren: de vermogenssprong
        # is dan veroorzaakt door zon, niet door een huishoudapparaat.
        if avg < 0 or baseline < 0:
            # Baseline wel zachtjes terugbrengen naar 0 als we lang in export zitten
            if avg < 0:
                self._baseline_power[phase] = max(0.0, baseline * 0.999)
            return

        if abs(delta) >= threshold:
            last_ev = self._last_event_time.get(phase, 0)
            if timestamp - last_ev > DEBOUNCE_TIME:
                self._last_event_time[phase] = timestamp
                # v4.5: ESP-features direct meegeven aan PowerEvent zodat local_ai.classify()
                # ze ook ontvangt. Voorheen werden ze alleen doorgegeven aan db.classify(),
                # waardoor de local AI kNN nooit kon leren op power_factor, reactive_power of THD.
                _pf     = getattr(self, "_esp_power_factor",   {}).get(phase)
                _inrush = getattr(self, "_esp_inrush_peak",    {}).get(phase)
                _rt_map = getattr(self, "_esp_rise_time_s",    {})
                _rt_esp = _rt_map.get(phase) if isinstance(_rt_map, dict) else None
                _q      = getattr(self, "_esp_reactive_power", {}).get(phase)
                _thd    = getattr(self, "_esp_thd",            {}).get(phase)
                # Gebruik ESPHome rise_time als beschikbaar (<1s = betrouwbaar), anders polling
                _rise   = _rt_esp if (_rt_esp is not None and _rt_esp < 1.0) \
                          else recent[-1][0] - recent[0][0]
                event = PowerEvent(
                    timestamp          = timestamp,
                    delta_power        = delta,
                    # rise_time from polling is always ~20 s — passed as-is but
                    # flagged unreliable so database.classify() ignores it.
                    rise_time          = _rise,
                    duration           = 0.0,
                    peak_power         = max(p for _, p in recent),
                    rms_power          = avg,
                    phase              = phase,
                    # v4.5: ESP-features voor V-I trajectory benadering
                    power_factor       = _pf,
                    inrush_peak_a      = _inrush,
                    reactive_power_var = _q,
                    thd_pct            = _thd,
                )
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._async_process_event(event))
                except RuntimeError:
                    asyncio.ensure_future(self._async_process_event(event))

        # Update baseline slowly — alleen bij import (positief vermogen).
        # Bij export (negatief) niet updaten: zonnepanelen drukken het fasevermogen
        # negatief maar de altijd-aan last is ongewijzigd.
        if avg >= 0:
            new_baseline = baseline * 0.998 + avg * 0.002
            # Sanity cap: basislijn per fase max 6000W (een volledig belaste 25A fase)
            self._baseline_power[phase] = min(new_baseline, 6000.0)

        # ── v1.21: Auto-off timeout ───────────────────────────────────────────
        # Apparaten die te lang 'aan' zijn, worden stilgezet. Dit vangt gemiste
        # off-edges op (bijv. als de vermogensdelta net onder de drempel viel).
        for dev in self._devices.values():
            if not dev.is_on or dev.phase not in (phase, "ALL"):
                continue
            if dev._on_start_ts <= 0:
                continue
            max_on = DEVICE_MAX_ON_TIMES.get(dev.device_type)
            if max_on and (timestamp - dev._on_start_ts) > max_on:
                _LOGGER.debug(
                    "NILM auto-off: %s na %.0f min (max %.0f min)",
                    dev.name,
                    (timestamp - dev._on_start_ts) / 60,
                    max_on / 60,
                )
                # v2.2.2: registreer sessieduur bij auto-off
                dev.energy.record_session(timestamp - dev._on_start_ts)
                dev.is_on         = False
                dev.current_power = 0.0
                dev._on_start_ts  = 0.0

        # ── v1.21: Steady-state validatie ────────────────────────────────────
        # Controleer on-events die 35 s geleden gedetecteerd zijn. Als de baseline
        # niet met minstens 50% van het verwachte vermogen gestegen is, was het
        # waarschijnlijk een vals positief → halveer de confidence.
        current_baseline = self._baseline_power[phase]
        still_pending = []
        for val in self._pending_validations:
            if val["phase"] != phase:
                still_pending.append(val)
                continue
            if timestamp < val["check_at"]:
                still_pending.append(val)
                continue
            # Validatiemoment bereikt
            dev = self._devices.get(val["device_id"])
            if dev and dev.is_on:
                actual_rise  = current_baseline - val["baseline_before"]
                expected     = val["expected_power"]
                if expected > 50 and actual_rise < expected * STEADY_STATE_MIN_RATIO:
                    # False positive: verwijder onbevestigde apparaten direct,
                    # bevestigde apparaten krijgen confidence-knip maar blijven staan.
                    if not dev.confirmed:
                        _LOGGER.info(
                            "NILM steady-state FALSE POSITIVE verwijderd: %s "
                            "(verwacht +%.0fW, gemeten +%.0fW)",
                            dev.name, expected, actual_rise,
                        )
                        # v1.32: auto-leer: sla de afgewezen signature op
                        # zodat hetzelfde vermogen de volgende keer geblokkeerd wordt.
                        self._fp_memory.record_rejection(
                            power_w = expected,
                            phase   = val["phase"],
                        )
                        if val["device_id"] in self._devices:
                            del self._devices[val["device_id"]]
                        continue  # niet terug in still_pending
                    old_conf = dev.confidence
                    dev.confidence = round(dev.confidence * 0.65, 3)
                    _LOGGER.debug(
                        "NILM steady-state FAIL %s: verwacht +%.0fW baseline, "
                        "gemeten +%.0fW → confidence %.0f%%→%.0f%%",
                        dev.name, expected, actual_rise,
                        old_conf * 100, dev.confidence * 100,
                    )
                else:
                    _LOGGER.debug(
                        "NILM steady-state OK %s: baseline +%.0fW (verwacht +%.0fW)",
                        dev.name, actual_rise, expected,
                    )
        self._pending_validations = still_pending

        # ── Laag C: bijhouden actieve concurrent last per fase ────────────────
        # PowerLearner._active_loads bijwerken op basis van actieve apparaten.
        # Dit zorgt dat adjust_delta_for_concurrent_load() juiste data heeft.
        phase_loads: dict = {}
        for dev in self._devices.values():
            if dev.is_on and dev.current_power >= 50 and dev.phase in (phase, "ALL"):
                phase_loads[dev.device_id] = dev.current_power
        self._power_learner._active_loads[phase] = phase_loads

        # Tick energy on active devices
        ts = timestamp
        for dev in self._devices.values():
            if dev.phase == phase:
                dev.tick_energy(ts)

    # ── Classification ────────────────────────────────────────────────────────

    # Battery cooldown window: suppress NILM events for this many seconds after
    # a large battery ramp of similar magnitude.
    BATTERY_COOLDOWN_S = 90

    async def _async_process_event(self, event: PowerEvent) -> None:
        import time as _t
        abs_delta = abs(event.delta_power)
        now = _t.time()

        # ── v1.24: batterij-ramp masker — EERST checken ───────────────────────
        # inject_battery() zet _batt_ramp_mask_until als de batterij snel van
        # vermogen wisselt. Tijdens het maskervenster worden ALLE NILM-events
        # geblokkeerd — de batterij domineert het signaal toch.
        if now < self._batt_ramp_mask_until:
            _LOGGER.debug(
                "NILM: event %.0fW geblokkeerd — batterij-ramp masker actief "
                "(nog %.0fs)",
                event.delta_power,
                self._batt_ramp_mask_until - now,
            )
            return

        # ── v1.31: BatteryUncertaintyTracker — stale/traag gemeten batterijen ───
        if event.delta_power > 0:
            _suppress_batt, _batt_reason = self._batt_uncertainty.should_suppress_nilm(
                delta_w=abs_delta,
                phase=event.phase,
            )
            if _suppress_batt:
                _LOGGER.debug(
                    "NILM: event %.0fW fase=%s onderdrukt — %s",
                    event.delta_power, event.phase, _batt_reason,
                )
                self._diag_events_total += 1
                return

        # ── v1.31: FalsePositiveMemory — bekende afgewezen signatures blokkeren ─
        if event.delta_power > 0:
            if self._fp_memory.is_false_positive(
                power_w = abs_delta,
                phase   = event.phase,
                ts      = now,
            ):
                _LOGGER.debug(
                    "NILM: event %.0fW fase=%s onderdrukt — bekende false-positive",
                    event.delta_power, event.phase,
                )
                self._diag_events_total += 1
                return

        # ── v1.31: MacroLoadTracker — ruis van grootverbruikers onderdrukken ──
        if event.delta_power > 0:
            suppress, reason = self._macro_tracker.should_suppress(
                abs_delta, event.phase
            )
            if suppress:
                _LOGGER.debug(
                    "NILM: event %.0fW fase=%s onderdrukt — %s",
                    event.delta_power, event.phase, reason,
                )
                self._diag_events_total += 1
                return

        # ── v1.24: skip events that match a configured infrastructure sensor ──
        # If the delta closely matches (±25%) a known infrastructure power reading
        # (PV, grid, EV charger) it is an environmental change, not an appliance.
        for label, infra_w in self._infra_powers.items():
            if infra_w < 50:
                continue
            ratio = abs_delta / infra_w
            if 0.75 <= ratio <= 1.25:
                _LOGGER.debug(
                    "NILM: event %.0fW overgeslagen — komt overeen met infra-sensor '%s' (%.0fW)",
                    event.delta_power, label, infra_w,
                )
                return

        # ── v1.24: battery cooldown suppression ──────────────────────────────
        # After a large battery ramp, suppress NILM events of similar magnitude
        # for BATTERY_COOLDOWN_S seconds (prevents boiler/heat_pump false positives
        # when battery switches from idle to charging at 2–3 kW).
        if (self._battery_last_delta_w > 300
                and (now - self._battery_last_delta_ts) < self.BATTERY_COOLDOWN_S):
            ratio_cooldown = abs_delta / self._battery_last_delta_w
            if 0.55 <= ratio_cooldown <= 1.55:
                _LOGGER.debug(
                    "NILM: event %.0fW overgeslagen — batterij-cooldown actief "
                    "(Δbatterij %.0fW, %.0fs geleden)",
                    event.delta_power, self._battery_last_delta_w,
                    now - self._battery_last_delta_ts,
                )
                return

        # ── v1.16: skip events during active battery charge/discharge ─────────
        # Ratio-based check: event delta ≈ battery power → battery-caused edge
        if self._battery_power_w > 300:
            ratio = abs_delta / self._battery_power_w
            if 0.55 <= ratio <= 1.55:
                _LOGGER.debug(
                    "NILM: event %.0fW overgeslagen — lijkt op batterijovergang (batterij %.0fW)",
                    event.delta_power, self._battery_power_w,
                )
                return

        # ── v1.25: Laag B — off-event short-circuit via power-stack ─────────────
        # Bij negatieve deltas (off-events) zoeken we EERST in de power-stack naar
        # een actief apparaat dat qua vermogen overeenkomt. Als we een match vinden,
        # verwerken we het off-event direct zonder database-reclassificatie.
        # Dit voorkomt dat off-events nep-detecties aanmaken.
        if event.delta_power < 0:
            off_match_id = self._power_learner.find_off_match(
                event.phase, abs_delta, event.timestamp
            )
            if off_match_id and off_match_id in self._devices:
                dev = self._devices[off_match_id]
                was_on = dev.is_on
                dev.is_on         = False
                dev.current_power = 0.0
                dev.last_seen     = event.timestamp
                dev.detection_count += 1
                if was_on and dev._on_start_ts > 0:
                    duration = event.timestamp - dev._on_start_ts
                    dev.energy.record_session(duration)
                    # v1.32: te korte sessie (<8s) = ruis → auto-leer als false-positive
                    # Niet voor bevestigde apparaten of smart-plug ankering
                    if (duration < 8.0
                            and not dev.confirmed
                            and dev.source != "smart_plug"
                            and dev.device_id not in ("__battery_injected__",)
                    ):
                        _fp_w = dev.current_power if dev.current_power > 20 else abs_delta
                        self._fp_memory.record_rejection(
                            power_w = _fp_w,
                            phase   = dev.phase,
                            ts      = event.timestamp,
                        )
                        _LOGGER.debug(
                            "NILM: korte sessie %.1fs → auto-FP %.0fW fase=%s",
                            duration, _fp_w, dev.phase,
                        )
                    # v1.30: cycling/session-fingerprint tracking
                    try:
                        self._power_learner.record_session_timing(
                            device_id  = off_match_id,
                            device_type= dev.device_type,
                            start_ts   = dev._on_start_ts,
                            duration_s = duration,
                            power_w    = dev.current_power if dev.current_power > 0
                                         else abs_delta,
                        )
                    except Exception as _cle:
                        _LOGGER.debug("PowerLearner cycling tracking fout: %s", _cle)
                    dev._on_start_ts = 0.0
                self._power_learner.record_off_event(off_match_id, event.phase, event.timestamp)
                if self._on_device_update:
                    self._on_device_update(dev)
                _LOGGER.debug(
                    "NILM Laag-B off-match: %s ← %.0fW (overgeslagen database)",
                    dev.name, abs_delta,
                )
                # Diagnostics loggen (behandeld als classified off-event)
                self._diag_events_total += 1
                self._diag_events_classified += 1
                return  # geen verdere verwerking nodig

        # ── v4.0.3: Laag C — concurrent load context bij on-event ────────────
        # adjust_delta_for_concurrent_load() geeft de gelijktijdige actieve last
        # terug zodat we in de log kunnen zien hoeveel er al draait.
        # De delta zelf wordt NIET aangepast — de EMA-baseline verdisconteert al
        # lopende lasten. We loggen het wel voor diagnose en sturen het mee naar
        # de classify-aanroep als extra context.
        _concurrent_context_w = 0.0
        if event.delta_power > 0:
            try:
                _, _concurrent_context_w = self._power_learner.adjust_delta_for_concurrent_load(
                    event.phase, event.delta_power
                )
                if _concurrent_context_w > 100:
                    _LOGGER.debug(
                        "NILM Laag-C: on-event %.0fW met %.0fW concurrent last op fase %s",
                        event.delta_power, _concurrent_context_w, event.phase,
                    )
            except Exception as _lc_err:
                _LOGGER.debug("PowerLearner Laag-C fout: %s", _lc_err)

        # FIX v1.7: pass scalar args — database.classify(float, float), NOT the PowerEvent object
        # v1.21: rise_time_reliable=False — polling-based detectors always produce ~20 s
        # v2.2: power_factor vanuit ESPHome-meter als extra discriminerende feature
        # v1.23: reactive_power + THD toegevoegd — None als ESP32 die sensor niet heeft
        # v4.5: ESP-features komen nu rechtstreeks uit het PowerEvent-object (set in update_power),
        # zodat db.classify() en local_ai.classify() exact dezelfde features zien.
        # Graceful degradation: elk None-argument wordt in classify() volledig overgeslagen.
        lang = getattr(getattr(self._hass, "config", None), "language", "en")
        lang = lang[:2].lower() if lang else "en"
        _rt_reliable = event.power_factor is not None or (
            event.rise_time < 1.0 and event.rise_time > 0
        )  # ESPHome rise_time is < 1s; polling levert ~20s
        matches: List[Dict] = self._db.classify(
            event.delta_power,
            event.rise_time,
            language=lang,
            rise_time_reliable=_rt_reliable,
            power_factor=event.power_factor,
            inrush_peak_a=event.inrush_peak_a,
            reactive_power_var=event.reactive_power_var,
            thd_pct=event.thd_pct,
        )
        self._diag_log_event(event, matches)
        if self._local_ai.is_available:
            matches = self._merge_matches(matches, self._local_ai.classify(event))

        # v1.23: Bayesian posterior classifier — prior × likelihood → posterior
        # Veiligheidsregel: nooit lagere confidence dan origineel (verbetert alleen)
        if self._bayes_callback is not None:
            try:
                temp_c = getattr(self._bayes_callback, "_last_temp_c", 15.0)
                matches = self._bayes_callback.update_confidences(
                    matches       = matches,
                    delta_w       = event.delta_power,
                    timestamp     = event.timestamp,
                    temperature_c = temp_c,
                )
            except Exception as _be:
                _LOGGER.debug("BayesianNILM fout: %s", _be)

        # v1.17: Hybride verrijking — ankering + contextpriors + 3-fase balans
        if self._hybrid is not None:
            try:
                # v1.20: geef bevestigde apparaten mee zodat duplicaat-detectie werkt
                _confirmed = [
                    d.to_dict() for d in self._devices.values()
                    if d.confirmed and d.is_on and d.phase == event.phase
                ]
                matches = self._hybrid.enrich_matches(
                    matches            = matches,
                    delta_w            = event.delta_power,
                    phase              = event.phase,
                    timestamp          = event.timestamp,
                    confirmed_devices  = _confirmed,
                )
            except Exception as _he:
                _LOGGER.debug("HybridNILM enrich fout: %s", _he)

        # ── v4.5: Co-occurrence aanpassing ─────────────────────────────────────
        # Pas matches aan op basis van co-occurrence kennis:
        # - BOOST  als een type structureel samen met een actief apparaat voorkomt
        # - PENALTY als een gekoppeld confirmed apparaat al actief is op zelfde fase
        if self._co_occurrence and matches:
            try:
                _active_ids = [
                    d.device_id for d in self._devices.values()
                    if d.is_on and d.device_id
                ]
                matches = self._co_occurrence.adjust_matches(
                    matches            = matches,
                    active_device_ids  = _active_ids,
                    detector_devices   = self._devices,
                )
            except Exception as _coe:
                _LOGGER.debug("CoOccurrence adjust fout: %s", _coe)

        # ── v1.25: Laag A — per-apparaat vermogensprofiel boost ─────────────────
        # Apparaten met een geleerd profiel (n≥3 observaties) krijgen een confidence-
        # boost als het huidige vermogen goed overeenkomt met het geleerde profiel.
        # Apparaten zonder profiel worden niet beïnvloed.
        if matches:
            try:
                matches = self._power_learner.apply_profile_boost(
                    matches   = matches,
                    devices   = self._devices,
                    power_w   = abs_delta,
                )
            except Exception as _ple:
                _LOGGER.debug("PowerLearner profile boost fout: %s", _ple)

        best_conf = matches[0]["confidence"] if matches else 0.0

        # Try Ollama if enabled
        if best_conf < NILM_HIGH_CONFIDENCE and self._ollama_config.get("enabled"):
            ollama_matches = await self._classify_ollama(event)
            matches = self._merge_matches(matches, ollama_matches)

        # Try Cloud AI
        if best_conf < NILM_HIGH_CONFIDENCE and self._cloud_ai.is_available:
            cloud = await self._cloud_ai.classify(
                event.delta_power, event.rise_time,
                {"phase": event.phase, "timestamp": event.timestamp}
            )
            matches = self._merge_matches(matches, cloud)

        if matches and matches[0]["confidence"] >= NILM_MIN_CONFIDENCE:
            self._handle_match(event, matches[0], matches)
        elif event.delta_power > 0:
            # v4.4: geen classificatie-match → voeg event toe aan unsupervised clusterer.
            # De clusterer groepeert vergelijkbare onbekende events en vraagt
            # de gebruiker om bevestiging zodra een cluster voldoende groot is.
            # Alleen positieve deltas (on-events) — off-events zijn geen nieuwe apparaten.
            try:
                # v4.5: reactive_fraction (sin phi) meegeven voor V-I-gebaseerde clustering
                _rfrac: float | None = None
                if event.reactive_power_var is not None:
                    import math as _m
                    _p = abs(event.delta_power)
                    _q = abs(event.reactive_power_var)
                    _s = _m.sqrt(_p ** 2 + _q ** 2)
                    _rfrac = _q / max(_s, 1.0)
                self._clusterer.add_unknown_event(
                    power_w    = abs(event.delta_power),
                    duration_s = 0.0,   # duur onbekend op dit punt
                    reactive_frac = _rfrac,
                )
            except Exception as _ce:
                _LOGGER.debug("NILM clusterer fout: %s", _ce)

        # Formele event-hooks — altijd aanroepen, ook bij geen match
        # Zo kunnen externe modules (SmartPowerEstimator) delta correleren zonder
        # afhankelijk te zijn van interne attributen.
        if self._event_hooks:
            for _hook in self._event_hooks:
                try:
                    _hook(event.delta_power, event.timestamp)
                except Exception as _he:
                    _LOGGER.debug("NILM event_hook fout: %s", _he)

    async def _classify_ollama(self, event: PowerEvent) -> List[Dict]:
        """Query local Ollama instance for device classification — with full diagnostic tracking."""
        import time as _t, json as _json, re as _re, aiohttp
        from datetime import datetime, timezone

        host  = self._ollama_config.get("host", "localhost")
        port  = self._ollama_config.get("port", 11434)
        model = self._ollama_config.get("model", "llama3")
        prompt = (
            f"You are a home energy expert. A power event was detected:\n"
            f"Delta power: {event.delta_power:.0f}W, Rise time: {event.rise_time:.1f}s, "
            f"Peak: {event.peak_power:.0f}W\n"
            f"Reply ONLY with JSON: {{\"device_type\": \"<type>\", \"confidence\": <0.0-1.0>}}\n"
            f"Valid types: refrigerator, washing_machine, dryer, dishwasher, oven, microwave, "
            f"kettle, television, computer, heat_pump, boiler, ev_charger, light, unknown"
        )
        url = f"http://{host}:{port}/api/generate"
        self._ollama_calls_total += 1
        t_start = _t.monotonic()
        log_entry = {
            "ts":       datetime.now(tz=timezone.utc).strftime("%H:%M:%S"),
            "delta_w":  round(event.delta_power, 1),
            "phase":    event.phase,
            "result":   "❌ geen antwoord",
            "device":   None,
            "conf_pct": None,
            "ms":       None,
            "fallback": True,
        }
        try:
            s = async_get_clientsession(self.hass)
            async with s.post(url, json={"model": model, "prompt": prompt, "stream": False},
                                  timeout=aiohttp.ClientTimeout(total=8)) as r:
                    elapsed_ms = round((_t.monotonic() - t_start) * 1000, 1)
                    log_entry["ms"] = elapsed_ms
                    if r.status == 200:
                        data = await r.json()
                        text = data.get("response", "")
                        m = _re.search(r'\{.*\}', text, _re.DOTALL)
                        if m:
                            parsed = _json.loads(m.group())
                            device_type = parsed.get("device_type", "unknown")
                            confidence  = float(parsed.get("confidence", 0.5))
                            self._ollama_calls_success += 1
                            self._ollama_last_success_ts = _t.time()
                            self._ollama_last_response_ms = elapsed_ms
                            # Running average response time
                            n = self._ollama_calls_success
                            self._ollama_avg_response_ms = round(
                                ((self._ollama_avg_response_ms * (n - 1)) + elapsed_ms) / n, 1
                            )
                            log_entry.update({
                                "result":   f"✅ {device_type} ({confidence*100:.0f}%)",
                                "device":   device_type,
                                "conf_pct": round(confidence * 100, 0),
                                "fallback": False,
                            })
                            self._ollama_log.insert(0, log_entry)
                            if len(self._ollama_log) > 20:
                                self._ollama_log.pop()
                            return [{
                                "device_type": device_type,
                                "confidence":  confidence,
                                "name":        device_type.replace("_", " ").title(),
                                "source":      NILM_MODE_OLLAMA,
                            }]
                    # Non-200
                    elapsed_ms = round((_t.monotonic() - t_start) * 1000, 1)
                    log_entry["ms"] = elapsed_ms
                    self._ollama_calls_failed += 1
                    self._ollama_last_error = f"HTTP {r.status}"
                    log_entry["result"] = f"❌ HTTP {r.status}"
        except asyncio.TimeoutError:
            elapsed_ms = round((_t.monotonic() - t_start) * 1000, 1)
            self._ollama_calls_failed += 1
            self._ollama_last_error = "timeout"
            log_entry.update({"result": "⏱️ timeout", "ms": elapsed_ms})
            _LOGGER.debug("CloudEMS NILM Ollama: timeout na %.0fms", elapsed_ms)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = round((_t.monotonic() - t_start) * 1000, 1)
            self._ollama_calls_failed += 1
            self._ollama_last_error = str(exc)
            log_entry.update({"result": f"❌ {exc}", "ms": elapsed_ms})
            _LOGGER.debug("CloudEMS NILM Ollama: %s", exc)

        self._ollama_log.insert(0, log_entry)
        if len(self._ollama_log) > 20:
            self._ollama_log.pop()
        return []

    def get_ollama_diagnostics(self) -> dict:
        """Return Ollama-specific diagnostics for the dedicated sensor."""
        import time as _t
        from datetime import datetime, timezone

        total   = self._ollama_calls_total
        success = self._ollama_calls_success
        failed  = self._ollama_calls_failed
        rate    = round(success / total * 100, 1) if total > 0 else 0.0

        last_ok = None
        if self._ollama_last_success_ts:
            last_ok = datetime.fromtimestamp(
                self._ollama_last_success_ts, tz=timezone.utc
            ).isoformat()

        host  = self._ollama_config.get("host", "localhost")
        port  = self._ollama_config.get("port", 11434)
        model = self._ollama_config.get("model", "llama3")
        enabled = bool(self._ollama_config.get("enabled", False))

        return {
            "enabled":              enabled,
            "host":                 host,
            "port":                 port,
            "model":                model,
            "calls_total":          total,
            "calls_success":        success,
            "calls_failed":         failed,
            "success_rate_pct":     rate,
            "last_success_ts":      last_ok,
            "last_error":           self._ollama_last_error or None,
            "last_response_ms":     self._ollama_last_response_ms,
            "avg_response_ms":      self._ollama_avg_response_ms,
            "recent_calls":         self._ollama_log[:20],
        }

    def _merge_matches(self, base: List[Dict], new: List[Dict]) -> List[Dict]:
        merged = {m["device_type"]: m.copy() for m in base}
        for m in new:
            dt = m["device_type"]
            if dt in merged:
                merged[dt]["confidence"] = min(merged[dt]["confidence"] + m["confidence"] * 0.3, 1.0)
            else:
                merged[dt] = m.copy()
        result = list(merged.values())
        result.sort(key=lambda x: x["confidence"], reverse=True)
        return result

    def _handle_match(self, event: PowerEvent, best: Dict, all_matches: List[Dict]):
        """Verwerk een geclassificeerde power-event.

        v1.21 verbeteringen:
        ─────────────────────
        1. Off-event power-stack matching
           Bij een negatieve delta zoeken we het apparaat op fase met het
           vermogen dat het best overeenkomt met de delta (±40%), in plaats van
           alleen te zoeken op device_type. Dit lost het probleem op waarbij
           bijv. twee boilers van 2000 W op L1 dezelfde off-event claimen.

        2. Meerdere instanties per type + fase
           Voor MULTI_INSTANCE_TYPES (koelkast, lamp, entertainment, socket) én
           voor elk ander type waarvan het vermogen >30% afwijkt van bestaande
           instanties op dezelfde fase, wordt een nieuw apparaat aangemaakt.

        3. Steady-state validatie registratie
           Elk nieuw on-event wordt als 'pending validation' opgeslagen.
           update_power() controleert dit 35 s later en verlaagt de confidence
           als de baseline niet voldoende gestegen is.
        """
        is_on      = event.delta_power > 0
        abs_delta  = abs(event.delta_power)

        existing_id: Optional[str] = None

        # ── OFF-event: match op vermogen, niet op type ────────────────────────
        # Zoek het actieve apparaat op dezelfde fase wiens huidig vermogen het
        # dichtstbij abs_delta ligt (relatieve afwijking ≤ 40%).
        if not is_on:
            best_diff = float("inf")
            for dev_id, dev in self._devices.items():
                if dev.phase not in (event.phase, "ALL") or not dev.is_on:
                    continue
                pw = dev.current_power
                if pw <= 0:
                    continue
                rel_diff = abs(pw - abs_delta) / max(pw, 1.0)
                if rel_diff <= 0.40 and rel_diff < best_diff:
                    best_diff   = rel_diff
                    existing_id = dev_id

            # Fallback: als geen power-match gevonden, val terug op type+fase
            if existing_id is None:
                for dev_id, dev in self._devices.items():
                    if dev.device_type == best["device_type"] and dev.phase == event.phase:
                        existing_id = dev_id
                        break

        # ── ON-event: zoek bestaande instantie op type + fase + vergelijkbaar vermogen ──
        else:
            dt = best["device_type"]
            allow_multi = dt in MULTI_INSTANCE_TYPES

            for dev_id, dev in self._devices.items():
                if dev.device_type != dt or dev.phase != event.phase:
                    continue

                if allow_multi:
                    # Multi-instance type: match alleen als huidig vermogen vergelijkbaar
                    ref_pw = dev.current_power if dev.current_power > 0 else abs_delta
                    rel_diff = abs(ref_pw - abs_delta) / max(ref_pw, 1.0)
                    if rel_diff > 0.30:
                        continue  # Ander vermogen → aparte instantie

                existing_id = dev_id
                break

        # ── Update of nieuw apparaat aanmaken ────────────────────────────────
        if existing_id:
            dev = self._devices[existing_id]
            prev_is_on        = dev.is_on
            dev.is_on         = is_on
            dev.confidence    = max(dev.confidence, best["confidence"])
            dev.current_power = abs_delta if is_on else 0.0
            dev.last_seen     = event.timestamp
            dev.detection_count += 1
            if is_on:
                dev.on_events    += 1
                dev._on_start_ts  = event.timestamp
                # v2.4.18: dag/nacht profiel bijhouden
                _hour = int((event.timestamp % 86400) / 3600)  # UTC uur, goed genoeg voor profiel
                _slot = "night" if _hour < 6 or _hour >= 23 else ("day" if _hour < 18 else "evening")
                dev.time_profile[_slot] = dev.time_profile.get(_slot, 0) + 1
                # Registreer voor steady-state validatie
                self._pending_validations.append({
                    "device_id":      existing_id,
                    "phase":          event.phase,
                    "expected_power": abs_delta,
                    "baseline_before": self._baseline_power.get(event.phase, 0.0),
                    "check_at":       event.timestamp + STEADY_STATE_DELAY_S,
                })
            elif prev_is_on and dev._on_start_ts > 0:
                # v2.2.2: off-event — registreer sessieduur
                duration = event.timestamp - dev._on_start_ts
                dev.energy.record_session(duration)
                # v1.30: cycling/session-fingerprint tracking
                try:
                    self._power_learner.record_session_timing(
                        device_id  = existing_id,
                        device_type= dev.device_type,
                        start_ts   = dev._on_start_ts,
                        duration_s = duration,
                        power_w    = abs_delta,
                    )
                except Exception as _cle:
                    _LOGGER.debug("PowerLearner cycling tracking fout: %s", _cle)
                dev._on_start_ts = 0.0
            if self._on_device_update:
                self._on_device_update(dev)
            # v1.22: HMM sessietracking
            if self._hmm_callback:
                try:
                    self._hmm_callback(dev.device_type, event.phase,
                                       abs_delta, event.delta_power, event.timestamp)
                except Exception:
                    pass
        else:
            dev_id = str(uuid.uuid4())[:8]
            dev = DetectedDevice(
                device_id      = dev_id,
                device_type    = best["device_type"],
                name           = best.get("name", (best.get("device_type") or "unknown").replace("_"," ").title()),
                confidence     = best["confidence"],
                current_power  = abs_delta if is_on else 0.0,
                is_on          = is_on,
                source         = best.get("source","database"),
                phase          = event.phase,
                pending_confirmation = best["confidence"] < NILM_HIGH_CONFIDENCE,
            )
            dev.energy = DeviceEnergy(device_id=dev_id)
            if is_on:
                dev.on_events    = 1
                dev._on_start_ts = event.timestamp
                # v2.4.18: dag/nacht profiel initialiseren
                _hour = int((event.timestamp % 86400) / 3600)
                _slot = "night" if _hour < 6 or _hour >= 23 else ("day" if _hour < 18 else "evening")
                dev.time_profile = {_slot: 1}
                # Registreer voor steady-state validatie
                self._pending_validations.append({
                    "device_id":      dev_id,
                    "phase":          event.phase,
                    "expected_power": abs_delta,
                    "baseline_before": self._baseline_power.get(event.phase, 0.0),
                    "check_at":       event.timestamp + STEADY_STATE_DELAY_S,
                })
            self._devices[dev_id] = dev
            _LOGGER.info(
                "CloudEMS NILM: NEW device %s (%.0f%% confidence) on %s",
                dev.name, dev.confidence * 100, dev.phase
            )
            if self._on_device_found:
                self._on_device_found(dev, all_matches)
            # v1.22: HMM sessietracking voor nieuw apparaat
            if self._hmm_callback and is_on:
                try:
                    self._hmm_callback(dev.device_type, event.phase,
                                       abs_delta, event.delta_power, event.timestamp)
                except Exception:
                    pass

        # ── v4.5: Co-occurrence event registratie ─────────────────────────────
        if self._co_occurrence:
            try:
                _active_now = [
                    d.device_id for d in self._devices.values()
                    if d.is_on and d.device_id != dev.device_id
                ]
                self._co_occurrence.record_event(
                    device_id          = dev.device_id,
                    event_type         = "on" if is_on else "off",
                    timestamp          = event.timestamp,
                    active_device_ids  = _active_now,
                )
            except Exception as _coe_err:
                _LOGGER.debug("CoOccurrence record fout: %s", _coe_err)

        # ── v1.25: PowerLearner — record event, check auto-confirm ───────────
        # Wordt uitgevoerd voor zowel bestaande als nieuwe apparaten.
        try:
            if is_on:
                _dev_id   = dev.device_id
                _dev_type = dev.display_type
                _confirmed = dev.confirmed or dev.user_feedback == "correct"
                self._power_learner.record_on_event(
                    device_id  = _dev_id,
                    device_type= _dev_type,
                    power_w    = abs_delta,
                    phase      = event.phase,
                    ts         = event.timestamp,
                    confirmed  = _confirmed,
                )
                # v4.0.4: tijdpatroon
                if self._time_pattern_learner:
                    try:
                        self._time_pattern_learner.record_on(_dev_id, event.timestamp)
                    except Exception: pass
                # Laag E: auto-confirm check
                if not dev.confirmed:
                    energy_ok = _dev_id not in self._energy_anomaly_ids
                    if self._power_learner.check_auto_confirm(
                        device_id  = _dev_id,
                        confidence = dev.confidence,
                        energy_ok  = energy_ok,
                    ):
                        dev.confirmed = True
                        dev.pending_confirmation = False
                        _LOGGER.info(
                            "NILM AUTO-CONFIRM: %s (type=%s, conf=%.0f%%)",
                            _dev_id, _dev_type, dev.confidence * 100,
                        )
                        if self._on_device_update:
                            self._on_device_update(dev)
            else:
                self._power_learner.record_off_event(
                    device_id = dev.device_id,
                    phase     = event.phase,
                    ts        = event.timestamp,
                )

            # Laag D: wekelijkse energie-validatie (async-safe via HA loop)
            if self._power_learner.should_validate_energy(event.timestamp):
                anomalies = self._power_learner.validate_energy(
                    self._devices, event.timestamp
                )
                for anomaly in anomalies:
                    self._energy_anomaly_ids.add(anomaly.device_id)
                    dev_anom = self._devices.get(anomaly.device_id)
                    if dev_anom and not dev_anom.confirmed:
                        dev_anom.confidence = round(
                            dev_anom.confidence * anomaly.confidence_adj, 3
                        )
                    _LOGGER.warning(
                        "NILM energie-anomalie: %s", anomaly.suggestion
                    )
        except Exception as _ple:
            _LOGGER.debug("PowerLearner _handle_match fout: %s", _ple)

    # ── User feedback ─────────────────────────────────────────────────────────

    def set_feedback(self, device_id: str, feedback: str,
                     corrected_name: str = "", corrected_type: str = "") -> None:
        """
        feedback: 'correct' | 'incorrect' | 'maybe'
        When 'correct' or corrected type given, trains local AI.
        """
        dev = self._devices.get(device_id)
        if not dev:
            return
        dev.user_feedback = feedback
        # Sla old_type op vóór we user_type aanpassen — nodig voor relabeling
        _old_device_type = dev.device_type

        if corrected_name:
            dev.user_name = corrected_name
        if corrected_type:
            dev.user_type = corrected_type
            # v4.5: update device_type ook zodat display_type consistent is
            # en toekomstige relabeling het juiste oude type kent
            dev.device_type = corrected_type

        if feedback == NILM_FEEDBACK_CORRECT:
            dev.confirmed = True
            dev.pending_confirmation = False
            dev.confidence = 1.0
            _LOGGER.info("CloudEMS NILM: %s confirmed as %s", device_id, dev.display_type)
        elif feedback == NILM_FEEDBACK_INCORRECT:
            dev.confirmed = False
            dev.confidence = 0.0
            _LOGGER.info("CloudEMS NILM: %s marked incorrect", device_id)
            # v1.31: sla de afgewezen signature op in FalsePositiveMemory
            if dev.current_power > 20:
                self._fp_memory.record_rejection(
                    power_w = dev.current_power,
                    phase   = dev.phase,
                )
            elif getattr(dev, "nominal_power_w", 0) > 20:
                self._fp_memory.record_rejection(
                    power_w = dev.nominal_power_w,
                    phase   = dev.phase,
                )

        # ── Train local AI with confirmed/corrected data ────────────────
        # v4.5 fix: als het type gecorrigeerd is (corrected_type opgegeven),
        # hernoem eerst alle bestaande trainingssamples voor dit apparaat zodat
        # de kNN geen conflicterende labels krijgt voor dezelfde feature-vector.
        if corrected_type and hasattr(self._local_ai, "relabel_device"):
            old_type = _old_device_type  # type vóór de correctie (bewaard hierboven)
            if old_type and old_type != dev.display_type:
                relabeled = self._local_ai.relabel_device(
                    device_id = device_id,
                    old_type  = old_type,
                    new_type  = dev.display_type,
                )
                _LOGGER.info(
                    "CloudEMS NILM: %s type gecorrigeerd %s→%s, "
                    "%d trainingssamples herschreven",
                    device_id, old_type, dev.display_type, relabeled,
                )

        if feedback in (NILM_FEEDBACK_CORRECT,) and dev.current_power > 0:
            synth = PowerEvent(
                timestamp  = time.time(),
                delta_power= dev.current_power,
                rise_time  = 2.0,
                duration   = 0.0,
                peak_power = dev.current_power,
                rms_power  = dev.current_power,
                phase      = dev.phase,
            )
            # v4.5: geef device_id mee zodat relabeling in de toekomst werkt
            self._local_ai.add_training_sample(synth, dev.display_type, device_id=device_id)

        # v1.23: Bayesian prior update op basis van feedback
        if self._bayes_callback is not None:
            try:
                if feedback == NILM_FEEDBACK_CORRECT:
                    self._bayes_callback.on_confirmed(dev.display_type, dev.current_power)
                elif feedback == NILM_FEEDBACK_INCORRECT:
                    self._bayes_callback.on_rejected(dev.display_type)
            except Exception:
                pass

        # v1.25: PowerLearner feedback
        try:
            if feedback == NILM_FEEDBACK_CORRECT and dev.current_power > 0:
                # Bevestigd → profiel versneld updaten met huidig vermogen
                self._power_learner.record_on_event(
                    device_id  = device_id,
                    device_type= dev.display_type,
                    power_w    = dev.current_power,
                    phase      = dev.phase,
                    ts         = time.time(),
                    confirmed  = True,
                )
                # Verwijder uit anomalie-set zodat auto-confirm weer mogelijk is
                self._energy_anomaly_ids.discard(device_id)
            elif feedback == NILM_FEEDBACK_INCORRECT:
                # Fout-positief → reset confirm-streak
                self._power_learner.reset_confirm_streak(device_id)
                self._energy_anomaly_ids.discard(device_id)
        except Exception as _ple:
            _LOGGER.debug("PowerLearner feedback fout: %s", _ple)

    def dismiss_device(self, device_id: str) -> None:
        """Wijs een NILM-apparaat permanent af.

        v4.5.3: in plaats van het apparaat direct te verwijderen uit _devices,
        zetten we user_suppressed=True. Zo wordt het bij de volgende async_save()
        opgeslagen in de store en na herstart NIET opnieuw getoond.

        Het apparaat verdwijnt uit get_devices_for_ha() (die filtert op user_suppressed),
        maar blijft in _devices zodat de store het persistent bijhoudt.
        """
        dev = self._devices.get(device_id)
        if dev is not None:
            dev.user_suppressed = True
            dev.is_on = False        # zet uit zodat het stroomverbruik niet mee-telt
            dev.current_power = 0.0
            _LOGGER.info(
                "NILM: apparaat '%s' (id=%s, type=%s) afgewezen door gebruiker — "
                "user_suppressed=True, wordt niet meer getoond",
                dev.user_name or dev.name or dev.device_type, device_id, dev.device_type,
            )
        else:
            _LOGGER.debug("NILM dismiss: device_id '%s' niet gevonden in _devices", device_id)

        # v4.5: cleanup co-occurrence paren voor afgewezen apparaat
        if self._co_occurrence:
            self._co_occurrence.on_device_removed(device_id)

    def cleanup(self, scope: str, days: int = 0) -> dict:
        """
        Verwijder NILM-apparaten en/of reset energietellers op basis van scope.

        scope opties:
          "full"        — verwijder ALLE apparaten en reset alle energietellers.
                          Reset ook de adaptive threshold en pending validaties.
                          Gebruik dit voor een schone start.

          "devices"     — verwijder alleen apparaten die langer dan `days` dagen
                          niet gezien zijn. Behoudt actieve apparaten.

          "energy"      — reset alleen de energietellers (kWh) van alle apparaten.
                          Apparaten zelf blijven intact.

          "last_x_days" — verwijder apparaten die de laatste `days` dagen zijn
                          aangemaakt maar nog niet bevestigd zijn (confidence < 1.0).
                          Nuttig om rommelige leersessies ongedaan te maken.

          "week"        — reset de week_kwh teller van alle apparaten.
          "month"       — reset de month_kwh teller van alle apparaten.
          "year"        — reset de year_kwh teller van alle apparaten.

        Returns:
            {"removed_devices": int, "reset_energy": int, "scope": str, "days": int}
        """
        import time as _t
        now = _t.time()
        removed = 0
        reset   = 0

        if scope == "full":
            removed = len(self._devices)
            self._devices.clear()
            self._active_events.clear()
            self._pending_validations.clear()
            self._baseline_power = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
            self._adaptive = AdaptiveNILMThreshold()
            # v1.25: PowerLearner volledig resetten
            self._power_learner = PowerLearner(auto_confirm_enabled=True)
            self._energy_anomaly_ids.clear()
            _LOGGER.info("NILM cleanup FULL: %d apparaten verwijderd, reset compleet (incl. PowerLearner)", removed)

        elif scope == "devices":
            cutoff = now - (days * 86_400)
            to_remove = [
                did for did, dev in self._devices.items()
                if dev.last_seen < cutoff and not dev.is_on
            ]
            for did in to_remove:
                del self._devices[did]
                removed += 1
            _LOGGER.info(
                "NILM cleanup DEVICES (>%d dagen): %d apparaten verwijderd", days, removed
            )

        elif scope == "energy":
            for dev in self._devices.values():
                dev.energy.today_kwh  = 0.0
                dev.energy.week_kwh   = 0.0
                dev.energy.month_kwh  = 0.0
                dev.energy.year_kwh   = 0.0
                dev.energy.total_kwh  = 0.0
                reset += 1
            _LOGGER.info("NILM cleanup ENERGY: %d tellers gereset", reset)

        elif scope == "last_x_days":
            cutoff = now - (days * 86_400)
            to_remove = [
                did for did, dev in self._devices.items()
                if dev.last_seen >= cutoff
                and dev.confidence < 1.0
                and not dev.confirmed
                and dev.source != "smart_plug"
            ]
            for did in to_remove:
                del self._devices[did]
                removed += 1
            _LOGGER.info(
                "NILM cleanup LAST_%d_DAYS: %d onbevestigde apparaten verwijderd",
                days, removed,
            )

        elif scope == "week":
            for dev in self._devices.values():
                dev.energy.week_kwh = 0.0
                reset += 1
            _LOGGER.info("NILM cleanup WEEK: %d week-tellers gereset", reset)

        elif scope == "month":
            for dev in self._devices.values():
                dev.energy.month_kwh = 0.0
                reset += 1
            _LOGGER.info("NILM cleanup MONTH: %d maand-tellers gereset", reset)

        elif scope == "year":
            for dev in self._devices.values():
                dev.energy.year_kwh = 0.0
                reset += 1
            _LOGGER.info("NILM cleanup YEAR: %d jaar-tellers gereset", reset)

        else:
            _LOGGER.warning("NILM cleanup: onbekende scope '%s'", scope)

        return {
            "scope":            scope,
            "days":             days,
            "removed_devices":  removed,
            "reset_energy":     reset,
            "devices_remaining": len(self._devices),
        }

    def _diag_log_event(self, event: "PowerEvent", matches: list) -> None:
        """Record event in diagnostics ring buffer."""
        from datetime import datetime, timezone
        self._diag_events_total += 1
        self._diag_last_event_ts    = event.timestamp
        self._diag_last_event_delta = event.delta_power
        direction = "↑ AAN" if event.delta_power > 0 else "↓ UIT"
        best = matches[0] if matches else None

        if best and best["confidence"] >= NILM_MIN_CONFIDENCE:
            self._diag_events_classified += 1
            self._diag_last_match = best["device_type"]
            result = f"✅ {best['device_type']} ({best['confidence']*100:.0f}%)"
        elif best:
            self._diag_events_missed += 1
            self._diag_last_match = f"laag vertrouwen ({best['confidence']*100:.0f}%)"
            result = f"⚠️ laag: {best['device_type']} ({best['confidence']*100:.0f}%)"
        else:
            self._diag_events_missed += 1
            self._diag_last_match = "geen match"
            result = "❌ geen match in database"

        entry = {
            "ts":        datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime("%H:%M:%S"),
            "phase":     event.phase,
            "delta_w":   round(event.delta_power, 1),
            "peak_w":    round(event.peak_power, 1),
            "rise_s":    round(event.rise_time, 2),
            "direction": direction,
            "result":    result,
            "top_matches": [
                {"type": m["device_type"], "conf_pct": round(m["confidence"]*100, 0)}
                for m in (matches[:3] if matches else [])
            ],
        }
        self._diag_log.insert(0, entry)
        if len(self._diag_log) > 30:
            self._diag_log.pop()
        _LOGGER.debug("NILM event %s %+.0fW → %s", event.phase, event.delta_power, result)

    def get_diagnostics(self) -> dict:
        """Return full diagnostics dict for the NILM Diagnostics sensor."""
        from datetime import datetime, timezone
        last_ts = None
        if self._diag_last_event_ts:
            last_ts = datetime.fromtimestamp(
                self._diag_last_event_ts, tz=timezone.utc
            ).isoformat()

        # Classification rate
        total = self._diag_events_total
        rate  = round(self._diag_events_classified / total * 100, 1) if total > 0 else 0.0

        return {
            "events_total":        total,
            "events_classified":   self._diag_events_classified,
            "fp_memory":           self._fp_memory.get_stats(),
            "macro_load":          self._macro_tracker.get_stats(),
            "battery_uncertainty": self._batt_uncertainty.get_stats(),
            "events_missed":       self._diag_events_missed,
            "classification_rate_pct": rate,
            "last_event_ts":       last_ts,
            "last_event_delta_w":  self._diag_last_event_delta,
            "last_match":          self._diag_last_match,
            "baselines_w": {
                ph: round(v, 1) for ph, v in self._baseline_power.items()
            },
            "devices_known":       len(self._devices),
            "devices_confirmed":   sum(1 for d in self._devices.values() if d.confirmed),
            "ai_mode":             self.active_mode,
            # v1.8: adaptive threshold info
            "adaptive_threshold":  self._adaptive.to_dict(),
            # v1.8: which sensors feed NILM per phase
            "sensor_inputs":       dict(self._sensor_input_log),
            "power_threshold_w":   self._adaptive.threshold,
            "debounce_s":          DEBOUNCE_TIME,
            # v1.24: mask status
            "pv_mask_active":      self._pv_mask_until > __import__("time").time(),
            "pv_mask_remaining_s": max(0.0, round(self._pv_mask_until - __import__("time").time(), 1)),
            "batt_ramp_mask_active":  self._batt_ramp_mask_until > __import__("time").time(),
            "batt_ramp_mask_remaining_s": max(0.0, round(self._batt_ramp_mask_until - __import__("time").time(), 1)),
            "recent_events":       self._diag_log[:20],
            # v1.25: PowerLearner diagnostics
            "power_learner":       self._power_learner.get_diagnostics(),
            "energy_anomaly_ids":  list(self._energy_anomaly_ids),
            "time_patterns":       self._time_pattern_learner.get_diagnostics() if self._time_pattern_learner else {},
            # v4.4: Unsupervised clusterer diagnostics
            "unknown_clusters":    self._clusterer.get_all_clusters(),
            "cluster_suggestions": len(self._clusterer.get_pending_suggestions()),
            # v4.0.3: Laag C — actieve concurrent last per fase
            "concurrent_loads": {
                phase: {
                    "total_w": round(sum(loads.values()), 1),
                    "devices": {did: round(w, 1) for did, w in loads.items()},
                    "count":   len(loads),
                }
                for phase, loads in self._power_learner._active_loads.items()
                if loads
            },
        }

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_devices(self) -> List[DetectedDevice]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[DetectedDevice]:
        return self._devices.get(device_id)

    def get_device_profile(self, device_id: str) -> Optional[dict]:
        """
        v1.30: Geeft het geleerde vermogensprofiel terug voor één apparaat.
        Combineert DevicePowerProfile-data met het DetectedDevice voor een
        volledig overzicht. Gebruikt voor de nilm_device_profile HA-service.
        """
        dev = self._devices.get(device_id)
        profile = self._power_learner.get_device_profile(device_id)
        if dev is None and profile is None:
            return None
        base = dev.to_dict() if dev else {"device_id": device_id}
        if profile:
            base["power_profile"] = profile
        return base

    def get_all_device_profiles(self) -> dict:
        """v1.30: Alle geleerde profielen als {device_id: dict}."""
        return self._power_learner.get_all_profiles()

    # ── v4.4: Unsupervised clusterer publieke API ─────────────────────────────

    def get_cluster_suggestions(self) -> list[dict]:
        """
        Geeft alle clusters terug waarvoor een gebruikersvraag klaar staat.
        Gebruikt door coordinator voor sensor.cloudems_nilm_unknown_devices
        en voor de NILM Beheer tab.
        """
        return self._clusterer.get_pending_suggestions()

    def get_all_clusters(self) -> list[dict]:
        """Alle actieve clusters (voor dashboard-weergave)."""
        return self._clusterer.get_all_clusters()

    def confirm_cluster_as_device(
        self,
        cluster_id: str,
        device_name: str,
        device_type: str,
    ) -> Optional[dict]:
        """
        Bevestig een cluster als apparaat. Geeft de clusterparameters terug
        zodat de coordinator een nieuw NILM-apparaat kan aanmaken.

        Aanroepen vanuit coordinator.confirm_nilm_cluster_device() service.
        """
        result = self._clusterer.confirm_cluster(cluster_id, device_name, device_type)
        if result:
            # Maak direct een DetectedDevice aan zodat toekomstige events herkend worden
            import uuid as _uuid
            dev_id = str(_uuid.uuid4())[:8]
            dev = DetectedDevice(
                device_id    = dev_id,
                device_type  = device_type,
                name         = device_name,
                confidence   = 0.90,
                current_power = 0.0,
                is_on        = False,
                source       = "cluster",
                confirmed    = True,
                detection_count = result.get("event_count", 1),
                phase        = "L1",
            )
            dev.energy = DeviceEnergy(device_id=dev_id)
            self._devices[dev_id] = dev
            _LOGGER.info(
                "NILM cluster bevestigd: '%s' (%s) — %d events, %.0fW",
                device_name, device_type,
                result.get("event_count", 0), result.get("power_w", 0),
            )
            if self._on_device_found:
                self._on_device_found(dev, [])
        return result

    def dismiss_cluster(self, cluster_id: str) -> None:
        """Verwijder een cluster permanent (gebruiker zegt: niet interessant)."""
        self._clusterer.dismiss_cluster(cluster_id)

    def register_battery_provider(self, label: str, provider: str = "default") -> None:
        """Registreer een batterij-provider bij BatteryUncertaintyTracker (setup-tijd)."""
        self._batt_uncertainty.register(label, provider)

    def update_battery_uncertainty(self, label: str, power_w: float) -> list[str]:
        """
        Update BatteryUncertaintyTracker met een nieuwe meting.
        Geeft lijst van device_ids die als burst-FP verwijderd moeten worden.
        Roep aan vóór inject_battery() zodat burst-masker klaar is.
        """
        burst, delta = self._batt_uncertainty.update(label, power_w)
        removed: list[str] = []
        if burst and delta > 0:
            removed = self._batt_uncertainty.cleanup_burst_false_positives(
                self._devices, delta, label
            )
            for did in removed:
                self._devices.pop(did, None)
            if removed:
                _LOGGER.info(
                    "BatteryUncertainty: %d burst-FP apparaten verwijderd na Δ%.0fW van '%s'",
                    len(removed), delta, label,
                )
        return removed

    def inject_battery(self, power_w: float, label: str = "Thuisbatterij") -> None:
        """Directly inject battery as a NILM device (not via edge detection).
        
        This avoids battery charge/discharge transitions triggering false NILM events.
        Battery is shown with 100% confidence and a dynamic power range.
        v1.16: also removes any heat_pump/boiler device that was caused by battery edges.
        v1.24: ramp-buffer bijhouden zodat geleidelijke rampen ook worden gefilterd.
        """
        import time as _t
        device_id = "__battery_injected__"
        ts = _t.time()

        # v1.24: ramp-buffer bijwerken
        self._batt_ramp_buffer.append((ts, abs(power_w)))
        # Houd buffer schoon: alleen metingen binnen BATT_RAMP_WINDOW_S bewaren
        cutoff = ts - BATT_RAMP_WINDOW_S
        self._batt_ramp_buffer = [e for e in self._batt_ramp_buffer if e[0] >= cutoff]

        # Ramp-detectie: wat is de totale vermogensverandering in het venster?
        if len(self._batt_ramp_buffer) >= 2:
            powers_in_window = [e[1] for e in self._batt_ramp_buffer]
            ramp_total = max(powers_in_window) - min(powers_in_window)
            if ramp_total >= BATT_RAMP_TOTAL_W:
                self._batt_ramp_mask_until = ts + BATT_RAMP_MASK_S
                _LOGGER.debug(
                    "NILM batterij-ramp gedetecteerd: %.0fW verandering in %.0fs "
                    "→ NILM geblokkeerd %.0fs",
                    ramp_total, BATT_RAMP_WINDOW_S, BATT_RAMP_MASK_S,
                )

        # v1.16: store battery power so _async_process_event can ignore matching edges
        self._battery_power_w = abs(power_w)

        # v1.16: if battery is significantly active, remove any heating/boiler NILM device
        # whose power is within 30% of the battery power — those were false positives from
        # battery charge/discharge transitions hitting the NILM edge detector.
        if abs(power_w) > 300:
            false_pos_types = {
                "heat_pump", "boiler", "electric_heater", "heat",
                "air_source_heat_pump", "ground_source_heat_pump",
                "cv_boiler", "resistive",
            }
            to_remove = []
            for did, dev in self._devices.items():
                if did == device_id:
                    continue
                if dev.device_type not in false_pos_types:
                    continue
                # Alleen verwijderen als:
                # (a) het apparaat niet bevestigd is door de gebruiker, en
                # (b) het vermogen plausibel door de batterij veroorzaakt is
                if dev.confirmed or dev.user_feedback == "correct":
                    continue
                batt_w = abs(power_w)
                dev_w  = dev.current_power if dev.current_power > 0 else dev.confidence * batt_w
                ratio  = dev_w / batt_w if batt_w > 0 else 0
                # Breeder raam: 30–170% van batterijvermogen — vangt ook deelstappen op
                if 0.3 <= ratio <= 1.7:
                    to_remove.append(did)
                    _LOGGER.debug(
                        "NILM: verwijder vals positief '%s' (%.0fW) — batterij (%.0fW, ratio=%.2f)",
                        dev.name, dev_w, batt_w, ratio,
                    )
            for did in to_remove:
                del self._devices[did]

        if device_id not in self._devices:
            dev = DetectedDevice(
                device_id     = device_id,
                device_type   = "battery",
                name          = label,
                confidence    = 1.0,
                current_power = abs(power_w),
                is_on         = abs(power_w) > 50,
                phase         = "ALL",
                source        = "injected",
            )
            self._devices[device_id] = dev

        dev = self._devices[device_id]
        dev.current_power = round(abs(power_w), 1)
        dev.is_on         = abs(power_w) > 50
        dev.confidence    = 1.0
        dev.name          = f"{label} ({'laden' if power_w > 0 else 'ontladen'})"
        dev.last_seen     = _t.time()

    # ── v1.32: Autonome dagelijkse zelfverbetering ───────────────────────────────

    async def auto_prune_ghosts(self) -> dict:
        """
        Dagelijkse automatische FP-leercyclus — geen gebruikersinteractie nodig.

        Drie automatische bronnen:
        1. Confidence bodemplank (<0.15): nooit bevestigd + zelden gezien →
           signature leren + apparaat verwijderen.
        2. Duplicate watt-klasse: twee niet-bevestigde apparaten met overlappend
           vermogen op dezelfde fase → de minst-geziene is een ghost.
        3. Lange ghost-sessies: apparaat staat al >6u aan zonder off-edge en
           heeft geen bekende duty-cycle → waarschijnlijk stranded detection.

        Geeft diagnose-dict terug.
        """
        import time as _t
        now = _t.time()
        pruned_conf  = []  # verwijderd via confidence-vloer
        pruned_dupl  = []  # verwijderd als duplicate
        pruned_ghost = []  # verwijderd als lange ghost-sessie

        # ── 1. Confidence-vloer sweep ─────────────────────────────────────────
        CONF_FLOOR    = 0.15   # effective_confidence onder dit → leer + verwijder
        MIN_AGE_DAYS  = 3.0    # ten minste 3 dagen oud (geen nieuwe apparaten weggooien)

        to_remove = []
        for did, dev in self._devices.items():
            if did.startswith("__"):
                continue
            if dev.confirmed or dev.user_feedback == "correct":
                continue
            if dev.source == "smart_plug":
                continue
            age_days = (now - dev.last_seen) / 86400.0
            if age_days < MIN_AGE_DAYS:
                continue
            if dev.effective_confidence < CONF_FLOOR:
                fp_w = dev.current_power if dev.current_power > 20                        else getattr(dev, "nominal_power_w", 0)
                if fp_w > 20:
                    self._fp_memory.record_rejection(
                        power_w = fp_w,
                        phase   = dev.phase,
                    )
                to_remove.append(did)
                pruned_conf.append({
                    "id": did, "name": dev.name,
                    "power_w": fp_w,
                    "eff_conf": dev.effective_confidence,
                    "age_days": round(age_days, 1),
                })
        for did in to_remove:
            self._devices.pop(did, None)

        # ── 2. Duplicate watt-klasse detectie ────────────────────────────────
        # Groepeer niet-bevestigde apparaten per (fase, watt-klasse).
        # Watt-klasse = power afgerond op 200W-stappen.
        WATT_BUCKET = 200.0
        from collections import defaultdict
        buckets: dict = defaultdict(list)
        for did, dev in self._devices.items():
            if did.startswith("__") or dev.confirmed or dev.source == "smart_plug":
                continue
            fp_w = dev.current_power if dev.current_power > 20                    else getattr(dev, "nominal_power_w", 0)
            if fp_w < 50:
                continue
            bucket = round(fp_w / WATT_BUCKET) * WATT_BUCKET
            buckets[(dev.phase, bucket)].append((did, dev, fp_w))

        for (phase, bucket), group in buckets.items():
            if len(group) < 2:
                continue
            # Sorteer op detection_count desc — de meest-geziene is "echt"
            group.sort(key=lambda x: x[1].detection_count, reverse=True)
            # Alles behalve de top-1 is een ghost
            for did, dev, fp_w in group[1:]:
                self._fp_memory.record_rejection(
                    power_w = fp_w,
                    phase   = phase,
                )
                self._devices.pop(did, None)
                pruned_dupl.append({
                    "id": did, "name": dev.name,
                    "power_w": fp_w, "phase": phase, "bucket": bucket,
                    "detections": dev.detection_count,
                })

        # ── 3. Lange ghost-sessie detectie ───────────────────────────────────
        # Apparaat staat al >6u aan maar heeft nooit een off-edge gehad en is
        # niet een cycling-type → stranded detection.
        MAX_SESSION_H     = 6.0
        CYCLING_TYPES = {
            "fridge", "refrigerator", "freezer", "heat_pump",
            "air_source_heat_pump", "boiler", "cv_boiler",
        }
        for did, dev in list(self._devices.items()):
            if did.startswith("__") or dev.confirmed or not dev.is_on:
                continue
            if dev.device_type in CYCLING_TYPES:
                continue
            if dev._on_start_ts <= 0:
                continue
            session_h = (now - dev._on_start_ts) / 3600.0
            if session_h > MAX_SESSION_H:
                fp_w = dev.current_power if dev.current_power > 20                        else getattr(dev, "nominal_power_w", 0)
                if fp_w > 20:
                    self._fp_memory.record_rejection(
                        power_w = fp_w,
                        phase   = dev.phase,
                    )
                self._devices.pop(did, None)
                pruned_ghost.append({
                    "id": did, "name": dev.name,
                    "power_w": fp_w, "session_h": round(session_h, 1),
                })

        # Opslaan als er iets veranderd is
        await self._fp_memory.async_save()

        total = len(pruned_conf) + len(pruned_dupl) + len(pruned_ghost)
        if total:
            _LOGGER.info(
                "NILM auto-prune: %d ghost(s) verwijderd en geleerd "
                "(conf=%d, dupl=%d, sessie=%d)",
                total, len(pruned_conf), len(pruned_dupl), len(pruned_ghost),
            )
        return {
            "pruned_total":   total,
            "pruned_conf":    pruned_conf,
            "pruned_dupl":    pruned_dupl,
            "pruned_ghost":   pruned_ghost,
            "fp_signatures":  len(self._fp_memory._signatures),
        }

    def get_devices_for_ha(self) -> List[dict]:
        """Return all devices as dicts suitable for HA attributes.
        
        v1.15.1: deduplicates variable-speed heat pump entries — merges
        all heat_pump/heat type entries on the same phase into one entry
        showing the power range instead of separate per-step entries.

        v1.17.5: filters out low-confidence and barely-seen devices.
        A device must have been detected at least MIN_ON_EVENTS times
        AND have confidence ≥ NILM_MIN_CONFIDENCE to appear.
        Smart plug anchors (source="smart_plug") are always shown.
        """
        # Zeldzame apparaattypes vereisen meer herhaalde detecties voor ze worden
        # getoond — dit voorkomt dat een eenmalige vermogenstap al een "cirkelzaag"
        # op het dashboard plaatst.
        RARE_TYPES_MIN_EVENTS = {
            "power_tool":  5,   # moet 5× gezien zijn vóór zichtbaar
            "garden":      4,
            "medical":     4,
            "kitchen":     3,
        }
        MIN_ON_EVENTS_DEFAULT = 2   # voor alle andere types

        # v2.4.17: warmup periode — eerste 24 uur na start zijn drempels 2× hoger
        # zodat vroege false positives niet direct op het dashboard verschijnen.
        _uptime_h = (time.time() - self._started_at) / 3600
        _warmup_factor = 2 if _uptime_h < 24 else 1

        raw = [d.to_dict() for d in self._devices.values()]

        # v4.4: naam-gebaseerde keyword-filter — verwijder infrastructure-sensoren
        # die via de naam herkenbaar zijn maar niet via source_entity_id gefilterd werden.
        # Dit pakt apparaten die al geleerd waren vóór de coordinator-filter ze kon blokkeren.
        _INFRA_NAME_KEYWORDS_EARLY = (
            "energiemeter", "energy meter", "stroomprijs", "uurprijs",
            "stroom tegen", "elektriciteitsgemiddelde",
            "elektriciteitsverbruik", "elektriciteitsproductie",
            "connect energi", "slimme meter", "p1 meter",
            "net import", "net export", "grid import", "grid export",
            "solar production", "pv productie",
            # v4.5.3: extra termen
            "energieproductie", "energieverbruik", "electricity meter",
            # v4.5.6: standalone "electricity meter" zonder suffix ook blokkeren
            "electricity meter",
        )
        def _is_infra_name(dev_dict: dict) -> bool:
            if dev_dict.get("source") == "smart_plug":
                return False
            name = (dev_dict.get("name") or "").lower().strip()
            if any(kw in name for kw in _INFRA_NAME_KEYWORDS_EARLY):
                return True
            # Extra patroon: "meter" + energie-term
            if "meter" in name and any(w in name for w in ("verbruik", "productie", "energy", "elektric")):
                return True
            # v4.5.6: device_type uitsluitingen — hoofdmeter is nooit een NILM apparaat
            _INFRA_TYPES = {
                "electricity_meter", "energy_meter", "main_meter", "grid_meter",
                "smart_meter", "p1_meter", "dsmr", "net_meter",
            }
            if dev_dict.get("device_type", "").lower() in _INFRA_TYPES:
                return True
            # v4.5.6: naam is exact "electricity meter" (DSMR/P1 hoofdmeter)
            if name in ("electricity meter", "energiemeter", "energy meter", "slimme meter"):
                return True
            return False
        raw = [d for d in raw if not _is_infra_name(d)]

        # Filter: verwijder altijd device-types die nooit huishoudapparaten zijn.
        # solar_inverter → PV-omvormer (coordinator geeft dit zelf al door)
        # battery        → thuisbatterij (al apart gemeten)
        # solar_inverter kan ook door AI worden geclassificeerd op grote negatieve delta
        # Apparaattypen die NOOIT huishoudapparaten zijn — altijd uitsluiten.
        # solar_inverter / pv_inverter → door coordinator apart gemeten
        # battery / opslag → inject_battery() regelt dit
        # net_meter / smart_meter / p1_meter → de meetinfrastructuur zelf
        # grid / grid_export / grid_import → netsensor
        ALWAYS_EXCLUDE_TYPES = {
            "solar_inverter", "pv_inverter", "pv", "inverter",
            "battery", "opslag", "home_battery",
            "net_meter", "smart_meter", "p1_meter", "dsmr",
            "grid", "grid_export", "grid_import", "net_power",
        }
        raw = [d for d in raw if d.get("device_type", "") not in ALWAYS_EXCLUDE_TYPES]

        # Filter: verwijder apparaten waarvan het source_entity_id een geconfigureerde
        # CloudEMS-sensor is (grid, import, export, solar, P1, gas, warmtepomp, enz.)
        if self._config_sensor_eids:
            raw = [
                d for d in raw
                if d.get("source_entity_id", "") not in self._config_sensor_eids
            ]
            # v2.4.19: ook filteren op naam — voor devices zonder source_entity_id
            # die zijn geleerd via de ruwe vermogensstroom van een infra-sensor.
            if self._blocked_friendly_names:
                raw = [
                    d for d in raw
                    if d.get("source") == "smart_plug"
                    or (d.get("name") or "").lower().strip() not in self._blocked_friendly_names
                ]

        # v4.4.1: keyword-filter — vang infrastructuur-sensoren die via naam niet
        # exact matchen maar duidelijk geen huishoudapparaat zijn.
        # Patronen gebaseerd op observaties: "energiemeter", "uurprijzen", "verbruik",
        # "productie", "electricity meter", "connect energiemeter" etc.
        # Smart-plug ankerapparaten worden nooit gefilterd.
        _INFRA_NAME_KEYWORDS = {
            # Nederlands
            "energiemeter", "uurprijzen", "elektriciteitsmeter",
            "elektriciteitsverbruik", "elektriciteitsproductie",
            "elektriciteitsgemiddelde", "stroomverbruik", "stroomproductie",
            "nettometing", "netmeting", "slimme meter", "p1 meter",
            "zonnepanelen productie", "zonnepanelen verbruik",
            "teruglevering", "netlevering", "netafname",
            "huidig verbruik", "huidig gebruik",
            # v4.5.3: extra NL termen die in de praktijk voorkomen
            "energieproductie", "energieverbruik", "stroomlevering",
            "netto verbruik", "netto levering",
            # Engels
            "electricity meter", "energy meter", "smart meter",
            "grid power", "grid import", "grid export",
            "solar production", "solar power", "pv production",
            "net metering", "feed-in", "feedin",
            "current consumption", "current production",
            # v4.5.3: combo-namen die DSMR/P1 meters soms produceren
            # bijv. "Electricity Meter Energieproductie", "Meter Energieverbruik"
            "electricity meter energieproductie", "electricity meter energieverbruik",
            "meter energieproductie", "meter energieverbruik",
            # Merknamen die typisch infra zijn
            "connect energiemeter", "stroom tegen uurprijzen",
            "p1 telegram",
        }
        def _has_infra_keyword(name: str) -> bool:
            n = (name or "").lower().strip()
            # Exacte substring match op alle keywords
            if any(kw in n for kw in _INFRA_NAME_KEYWORDS):
                return True
            # v4.5.3: extra patroon — naam bevat "meter" + (verbruik|productie|levering|import|export)
            if "meter" in n and any(w in n for w in ("verbruik", "productie", "levering", "import", "export", "energy", "elektric")):
                return True
            # v4.5.3: naam begint met bekende infra-prefix
            _INFRA_PREFIXES = ("electricity ", "electric meter", "dsmr ", "p1 ", "slimme ")
            if any(n.startswith(pfx) for pfx in _INFRA_PREFIXES):
                return True
            # v4.5.6: exacte naam-match voor veelvoorkomende hoofdmeter-labels
            if n in ("electricity meter", "energiemeter", "energy meter", "slimme meter", "main meter"):
                return True
            return False

        raw = [
            d for d in raw
            if d.get("source") == "smart_plug"
            or (
                not _has_infra_keyword(d.get("name", ""))
                and d.get("device_type", "").lower() not in {
                    "electricity_meter", "energy_meter", "main_meter", "grid_meter",
                    "smart_meter", "p1_meter", "dsmr", "net_meter",
                }
            )
        ]

        # v2.5: runtime vermogensfilter op basis van _infra_powers.
        #
        # Probleem: NILM leert apparaten via de fasesensor (source_entity_id = slimme meter).
        # Als een EV-lader of warmtepomp aanspringt, detecteert NILM een apparaat met dat
        # vermogen, maar de source_entity_id is de meter — niet de EV/HP sensor — dus het
        # bovenstaande source-filter pakt het NIET.
        #
        # Oplossing: als een apparaat *nu actief is* (is_on=True) en het vermogen ervan
        # nauwkeurig overeenkomt (+-30%) met een bekende infra-sensor, sluit het uit.
        # Smart-plug ankerapparaten worden nooit gefilterd.
        # Apparaten met is_on=False worden ook nooit gefilterd: het actieve vermogen
        # is dan 0W en ze vormen geen dubbeltellingrisico.
        if self._infra_powers:
            def _matches_infra(dev_dict: dict) -> bool:
                if dev_dict.get("source") == "smart_plug":
                    return False   # expliciet gemeten via stekker — nooit filteren
                if not dev_dict.get("is_on"):
                    return False   # slapend apparaat — geen risico
                pw = float(dev_dict.get("current_power") or 0)
                if pw < 100:
                    return False   # te laag om betrouwbaar te matchen
                for label, infra_w in self._infra_powers.items():
                    if infra_w < 100:
                        continue
                    ratio = pw / infra_w
                    if 0.70 <= ratio <= 1.30:
                        _LOGGER.debug(
                            "NILM get_devices_for_ha: '%s' (%.0fW) gefilterd "
                            "omdat het overeenkomt met infra-sensor '%s' (%.0fW)",
                            dev_dict.get("name", "?"), pw, label, infra_w,
                        )
                        return True
                return False
            raw = [d for d in raw if not _matches_infra(d)]

        # Filter: skip devices that have too low confidence or too few on-events,
        # unless they come from a smart plug anchor (those are always reliable).
        def _min_events(dtype: str) -> int:
            base = RARE_TYPES_MIN_EVENTS.get(dtype, MIN_ON_EVENTS_DEFAULT)
            # Adaptieve override: als dit type meer fp's had, verhoog drempel
            override = self._adaptive_overrides.get(dtype, {})
            base = max(base, override.get("min_events", base))
            return base * _warmup_factor

        raw = [
            d for d in raw
            if d.get("source") == "smart_plug"
            or (
                d.get("confidence", 0) >= NILM_MIN_CONFIDENCE
                and d.get("on_events", 0) >= _min_events(d.get("device_type", ""))
            )
        ]

        # Filter: skip devices hidden by the user (via rename_nilm_device service)
        raw = [d for d in raw if not d.get("user_hidden", False)]

        # Filter: skip devices suppressed/declined by the user — never show again
        raw = [d for d in raw if not d.get("user_suppressed", False)]

        # v2.4.18: dag/nacht profiel — bereken primair tijdvak en pas confidence aan
        # op basis van of het huidige tijdstip overeenkomt met het profiel.
        # Een apparaat dat vrijwel alleen 's nachts actief is maar nu overdag als "on"
        # wordt gemeld, krijgt een lichte confidence-penalty.
        _now_hour = int((time.time() % 86400) / 3600)
        _current_slot = ("night" if _now_hour < 6 or _now_hour >= 23
                         else ("day" if _now_hour < 18 else "evening"))
        for d in raw:
            profile = d.get("time_profile") or {}
            if not profile or d.get("source") == "smart_plug":
                d["primary_slot"] = "unknown"
                continue
            total = sum(profile.values())
            primary = max(profile, key=profile.get)
            primary_pct = profile[primary] / total if total > 0 else 0
            d["primary_slot"] = primary
            d["primary_slot_pct"] = round(primary_pct * 100)
            # Confidence aanpassen: als apparaat sterk gebonden is aan één tijdvak
            # (>70%) maar nu in een ander tijdvak actief lijkt, penalty van 10%.
            if primary_pct > 0.70 and primary != _current_slot and d.get("is_on"):
                d["confidence"] = round(max(0.0, d.get("confidence", 0.5) - 0.10), 3)
                d["time_mismatch"] = True
            else:
                d["time_mismatch"] = False

        # Deduplicate heat pump entries per phase
        hp_by_phase: dict = {}
        others = []
        for dev in raw:
            dtype = dev.get("device_type", "")
            if dtype in ("heat_pump", "air_source_heat_pump", "ground_source_heat_pump"):
                phase = dev.get("phase", "ALL")
                if phase not in hp_by_phase:
                    hp_by_phase[phase] = []
                hp_by_phase[phase].append(dev)
            else:
                others.append(dev)

        merged_hps = []
        for phase, devs in hp_by_phase.items():
            if len(devs) == 1:
                merged_hps.append(devs[0])
                continue
            powers = [d.get("power_w") or d.get("power_min") or 0 for d in devs]
            base   = max(devs, key=lambda d: d.get("confidence", 0))
            merged = dict(base)
            merged["name"]      = "Warmtepomp"
            merged["power_min"] = round(min(powers), 1)
            merged["power_max"] = round(max(powers), 1)
            merged["power_w"]   = round(sum(powers) / len(powers), 1)
            merged["confidence"] = max(d.get("confidence", 0) for d in devs)
            merged["is_on"]     = any(d.get("is_on") or d.get("running") for d in devs)
            merged["running"]   = merged["is_on"]
            merged_hps.append(merged)

        return others + merged_hps

    @property
    def active_mode(self) -> str:
        """Return the active NILM mode label, based on configured provider."""
        from ..const import (AI_PROVIDER_OLLAMA, AI_PROVIDER_NONE,
                             NILM_MODE_CLOUD_AI, NILM_MODE_OLLAMA,
                             NILM_MODE_LOCAL_AI, NILM_MODE_DATABASE)
        p = getattr(self, "_ai_provider", "none")
        if p == AI_PROVIDER_OLLAMA:
            return NILM_MODE_OLLAMA
        if p not in (AI_PROVIDER_NONE, "none", "") and self._cloud_ai.is_available:
            return NILM_MODE_CLOUD_AI
        if self._local_ai.is_available:
            return NILM_MODE_LOCAL_AI
        return NILM_MODE_DATABASE
