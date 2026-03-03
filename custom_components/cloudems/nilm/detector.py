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

POWER_CHANGE_THRESHOLD = 25   # W — minimum change to detect an event
WINDOW_SIZE            = 10
DEBOUNCE_TIME          = 2.0  # seconds


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
    ):
        from ..const import AI_PROVIDER_OLLAMA
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

        _LOGGER.info("CloudEMS NILM Detector v1.4 initialized")

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

    def update_power(self, phase: str, power_watt: float, timestamp: float = None):
        if timestamp is None:
            timestamp = time.time()
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

        if abs(delta) >= POWER_CHANGE_THRESHOLD:
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
                import asyncio
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
        matches: List[Dict] = self._db.classify(event)
        if self._local_ai.is_available:
            matches = self._merge_matches(matches, self._local_ai.classify(event))

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
        """Query local Ollama instance for device classification."""
        try:
            import aiohttp
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
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json={"model": model, "prompt": prompt, "stream": False},
                                  timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        import json, re
                        text = data.get("response","")
                        m    = re.search(r'\{.*\}', text, re.DOTALL)
                        if m:
                            parsed = json.loads(m.group())
                            return [{
                                "device_type": parsed.get("device_type","unknown"),
                                "confidence":  float(parsed.get("confidence", 0.5)),
                                "name":        parsed.get("device_type","unknown").replace("_"," ").title(),
                                "source":      NILM_MODE_OLLAMA,
                            }]
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("CloudEMS NILM Ollama: %s", exc)
        return []

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
                name           = best.get("name", best["device_type"].replace("_"," ").title()),
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

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_devices(self) -> List[DetectedDevice]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[DetectedDevice]:
        return self._devices.get(device_id)

    def get_devices_for_ha(self) -> List[dict]:
        """Return all devices as dicts suitable for HA attributes."""
        return [d.to_dict() for d in self._devices.values()]

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
