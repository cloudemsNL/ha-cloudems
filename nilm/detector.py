"""
CloudEMS NILM Detector — v1.4.0

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

        # v1.17: Hybride NILM verrijkingslaag (optioneel — wordt gezet door coordinator)
        self._hybrid: Optional[Any] = None

        _LOGGER.info("CloudEMS NILM Detector v1.8 initialized")

    # ── Storage setup ─────────────────────────────────────────────────────────

    def set_stores(self, store_devices: Store, store_energy: Store) -> None:
        self._store_devices = store_devices
        self._store_energy  = store_energy

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
                    rise_time   = recent[-1][0] - recent[0][0],
                    duration    = 0.0,
                    peak_power  = max(p for _, p in recent),
                    rms_power   = avg,
                    phase       = phase,
                )
                # Use get_running_loop (Python 3.10+, always available in HA context)
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._async_process_event(event))
                except RuntimeError:
                    asyncio.ensure_future(self._async_process_event(event))

        # Update baseline slowly
        self._baseline_power[phase] = baseline * 0.998 + avg * 0.002

        # Tick energy on active devices
        ts = timestamp
        for dev in self._devices.values():
            if dev.phase == phase:
                dev.tick_energy(ts)

    # ── Classification ────────────────────────────────────────────────────────

    async def _async_process_event(self, event: PowerEvent) -> None:
        # v1.16: skip events that are caused by battery charge/discharge transitions
        if self._battery_power_w > 500:
            ratio = abs(event.delta_power) / self._battery_power_w
            if 0.6 <= ratio <= 1.4:
                _LOGGER.debug(
                    "NILM: event %.0fW overgeslagen — lijkt op batterijovergang (batterij %.0fW)",
                    event.delta_power, self._battery_power_w,
                )
                return

        # FIX v1.7: pass scalar args — database.classify(float, float), NOT the PowerEvent object
        lang = getattr(getattr(self._hass, "config", None), "language", "en")
        lang = lang[:2].lower() if lang else "en"
        matches: List[Dict] = self._db.classify(event.delta_power, event.rise_time, language=lang)
        self._diag_log_event(event, matches)
        if self._local_ai.is_available:
            matches = self._merge_matches(matches, self._local_ai.classify(event))

        # v1.17: Hybride verrijking — ankering + contextpriors + 3-fase balans
        if self._hybrid is not None:
            try:
                matches = self._hybrid.enrich_matches(
                    matches   = matches,
                    delta_w   = event.delta_power,
                    phase     = event.phase,
                    timestamp = event.timestamp,
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
        is_on = event.delta_power > 0
        existing_id = None
        for dev_id, dev in self._devices.items():
            if dev.device_type == best["device_type"] and dev.phase == event.phase:
                existing_id = dev_id
                break

        if existing_id:
            dev = self._devices[existing_id]
            dev.is_on          = is_on
            dev.confidence     = max(dev.confidence, best["confidence"])
            dev.current_power  = abs(event.delta_power) if is_on else 0.0
            dev.last_seen      = event.timestamp
            dev.detection_count += 1
            if is_on:
                dev.on_events += 1
                dev._on_start_ts = event.timestamp
            if self._on_device_update:
                self._on_device_update(dev)
        else:
            dev_id = str(uuid.uuid4())[:8]
            dev = DetectedDevice(
                device_id      = dev_id,
                device_type    = best["device_type"],
                name           = best.get("name", (best.get("device_type") or "unknown").replace("_"," ").title()),
                confidence     = best["confidence"],
                current_power  = abs(event.delta_power) if is_on else 0.0,
                is_on          = is_on,
                source         = best.get("source","database"),
                phase          = event.phase,
                pending_confirmation = best["confidence"] < NILM_HIGH_CONFIDENCE,
            )
            dev.energy = DeviceEnergy(device_id=dev_id)
            self._devices[dev_id] = dev
            _LOGGER.info(
                "CloudEMS NILM: NEW device %s (%.0f%% confidence) on %s",
                dev.name, dev.confidence * 100, dev.phase
            )
            if self._on_device_found:
                self._on_device_found(dev, all_matches)

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

    def dismiss_device(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

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
        """
        import time as _t
        device_id = "__battery_injected__"

        # v1.16: store battery power so _async_process_event can ignore matching edges
        self._battery_power_w = abs(power_w)

        # v1.16: if battery is significantly active, remove any heating/boiler NILM device
        # whose power is within 30% of the battery power — those were false positives from
        # battery charge/discharge transitions hitting the NILM edge detector.
        if abs(power_w) > 500:
            false_pos_types = {"heat_pump", "boiler", "electric_heater", "heat",
                               "air_source_heat_pump", "ground_source_heat_pump"}
            to_remove = []
            for did, dev in self._devices.items():
                if did == device_id:
                    continue
                if dev.device_type not in false_pos_types:
                    continue
                # Only purge if the device power is plausibly battery-caused
                ratio = dev.current_power / abs(power_w) if abs(power_w) > 0 else 0
                if 0.5 <= ratio <= 1.5:
                    to_remove.append(did)
                    _LOGGER.debug(
                        "NILM: verwijder vals positief '%s' (%.0fW) — veroorzaakt door batterij (%.0fW)",
                        dev.name, dev.current_power, abs(power_w),
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
        MIN_ON_EVENTS_REQUIRED = 2   # seen at least twice before showing

        raw = [d.to_dict() for d in self._devices.values()]

        # Filter: skip devices that have too low confidence or too few on-events,
        # unless they come from a smart plug anchor (those are always reliable).
        raw = [
            d for d in raw
            if d.get("source") == "smart_plug"
            or (
                d.get("confidence", 0) >= NILM_MIN_CONFIDENCE
                and d.get("on_events", 0) >= MIN_ON_EVENTS_REQUIRED
            )
        ]

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
