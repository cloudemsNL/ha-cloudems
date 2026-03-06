# -*- coding: utf-8 -*-
"""
CloudEMS NILM Detector — v1.21.0

Changes vs v1.3:
  - User feedback: correct / incorrect / maybe  per device
  - Energy tracking: kWh per day / week / month / year per detected device
  - Devices visible as HA sensor entities (via coordinator → sensor.py)
  - Persistent storage of all device data
  - Confidence shown on each device

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
from .local_ai import LocalAIClassifier, PowerEvent
from .cloud_ai import CloudAIClassifier
from ..const import (
    NILM_MIN_CONFIDENCE, NILM_HIGH_CONFIDENCE,
    NILM_MODE_DATABASE, NILM_MODE_LOCAL_AI, NILM_MODE_CLOUD_AI, NILM_MODE_OLLAMA,
    NILM_FEEDBACK_CORRECT, NILM_FEEDBACK_INCORRECT, NILM_FEEDBACK_MAYBE,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_NILM_ENERGY,
)

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

    def to_dict(self) -> dict:
        return {
            "threshold_w":  self._threshold,
            "adapted":      self._adapted,
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
        return self.confidence

    def to_dict(self) -> dict:
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
            "energy":         self.energy.to_dict(),
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

        # v1.22: HMM sessietracking callback (wordt gezet door coordinator)
        # Signature: hmm_callback(device_type, phase, power_w, delta_w, ts) → None
        self._hmm_callback: Optional[Any] = None

        # v1.23: Bayesian posterior classifier (BayesianNILMClassifier instantie)
        self._bayes_callback: Optional[Any] = None

        _LOGGER.info("CloudEMS NILM Detector v1.24 initialized")

    # ── Storage setup ─────────────────────────────────────────────────────────

    def set_stores(self, store_devices: Store, store_energy: Store) -> None:
        self._store_devices = store_devices
        self._store_energy  = store_energy

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
        """Register entity_ids of CloudEMS-configured sensors (grid, PV, P1, gas, etc.).

        v1.20: These are definitively NOT household appliances — filter them from
        get_devices_for_ha() even if the NILM algorithm accidentally learned them.
        Also removes any already-stored devices whose device_id matches these eids.
        """
        self._config_sensor_eids = {e for e in entity_ids if e}
        # Purge any devices already learned from these sensors
        to_remove = [
            did for did, dev in self._devices.items()
            if getattr(dev, "source_entity_id", "") in self._config_sensor_eids
        ]
        for did in to_remove:
            _LOGGER.info("NILM: verwijder config-sensor apparaat '%s' uit _devices", did)
            self._devices.pop(did, None)

    def set_infra_powers(self, powers: dict) -> None:
        """Update known infrastructure sensor power values.

        Called every coordinator cycle. powers = {label: abs_power_w}, e.g.:
          {"pv": 1840.0, "grid": -230.0, "ev_charger": 3700.0}
        Used in _async_process_event to discard events whose delta exactly matches
        a configured infrastructure component — those are environmental changes,
        not appliance on/off events.
        """
        self._infra_powers = {k: abs(v) for k, v in powers.items() if abs(v) > 20}

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

        _LOGGER.info("CloudEMS NILM: loaded %d devices", len(self._devices))

    async def async_save(self) -> None:
        if self._store_devices:
            await self._store_devices.async_save({
                "devices": [d.to_dict() for d in self._devices.values()]
            })
        if self._store_energy and time.time() - self._last_energy_save > 60:
            edata = {d.device_id: d.energy.to_dict() for d in self._devices.values()}
            await self._store_energy.async_save(edata)
            self._last_energy_save = time.time()

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

        if abs(delta) >= threshold:
            last_ev = self._last_event_time.get(phase, 0)
            if timestamp - last_ev > DEBOUNCE_TIME:
                self._last_event_time[phase] = timestamp
                event = PowerEvent(
                    timestamp   = timestamp,
                    delta_power = delta,
                    # rise_time from polling is always ~20 s — passed as-is but
                    # flagged unreliable so database.classify() ignores it.
                    rise_time   = recent[-1][0] - recent[0][0],
                    duration    = 0.0,
                    peak_power  = max(p for _, p in recent),
                    rms_power   = avg,
                    phase       = phase,
                )
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._async_process_event(event))
                except RuntimeError:
                    asyncio.ensure_future(self._async_process_event(event))

        # Update baseline slowly
        self._baseline_power[phase] = baseline * 0.998 + avg * 0.002

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

        # FIX v1.7: pass scalar args — database.classify(float, float), NOT the PowerEvent object
        # v1.21: rise_time_reliable=False — polling-based detectors always produce ~20 s
        lang = getattr(getattr(self._hass, "config", None), "language", "en")
        lang = lang[:2].lower() if lang else "en"
        matches: List[Dict] = self._db.classify(event.delta_power, event.rise_time,
                                                 language=lang, rise_time_reliable=False)
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
            async with aiohttp.ClientSession() as s:
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
                # Registreer voor steady-state validatie
                self._pending_validations.append({
                    "device_id":      existing_id,
                    "phase":          event.phase,
                    "expected_power": abs_delta,
                    "baseline_before": self._baseline_power.get(event.phase, 0.0),
                    "check_at":       event.timestamp + STEADY_STATE_DELAY_S,
                })
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
        if corrected_name:
            dev.user_name = corrected_name
        if corrected_type:
            dev.user_type = corrected_type

        if feedback == NILM_FEEDBACK_CORRECT:
            dev.confirmed = True
            dev.pending_confirmation = False
            dev.confidence = 1.0
            _LOGGER.info("CloudEMS NILM: %s confirmed as %s", device_id, dev.display_type)
        elif feedback == NILM_FEEDBACK_INCORRECT:
            dev.confirmed = False
            dev.confidence = 0.0
            _LOGGER.info("CloudEMS NILM: %s marked incorrect", device_id)

        # Train local AI with confirmed data
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
            self._local_ai.add_training_sample(synth, dev.display_type)

        # v1.23: Bayesian prior update op basis van feedback
        if self._bayes_callback is not None:
            try:
                if feedback == NILM_FEEDBACK_CORRECT:
                    self._bayes_callback.on_confirmed(dev.display_type, dev.current_power)
                elif feedback == NILM_FEEDBACK_INCORRECT:
                    self._bayes_callback.on_rejected(dev.display_type)
            except Exception:
                pass

    def dismiss_device(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

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
            _LOGGER.info("NILM cleanup FULL: %d apparaten verwijderd, reset compleet", removed)

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
        }

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_devices(self) -> List[DetectedDevice]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[DetectedDevice]:
        return self._devices.get(device_id)

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

        raw = [d.to_dict() for d in self._devices.values()]

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

        # Filter: skip devices that have too low confidence or too few on-events,
        # unless they come from a smart plug anchor (those are always reliable).
        def _min_events(dtype: str) -> int:
            return RARE_TYPES_MIN_EVENTS.get(dtype, MIN_ON_EVENTS_DEFAULT)

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
