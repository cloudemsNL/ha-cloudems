"""NILM Event Detector and Device Manager for CloudEMS."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any

from .database import NILMDatabase
from .local_ai import LocalAIClassifier, PowerEvent
from .cloud_ai import CloudAIClassifier
from ..const import (
    NILM_MIN_CONFIDENCE, NILM_HIGH_CONFIDENCE,
    NILM_MODE_DATABASE, NILM_MODE_LOCAL_AI, NILM_MODE_CLOUD_AI,
)

_LOGGER = logging.getLogger(__name__)

POWER_CHANGE_THRESHOLD = 25  # Watt - minimum change to detect an event
WINDOW_SIZE = 10              # samples in sliding window
DEBOUNCE_TIME = 2.0           # seconds between events on same phase


@dataclass
class DetectedDevice:
    """A device detected via NILM."""
    device_id: str
    device_type: str
    name: str
    confidence: float
    current_power: float
    is_on: bool
    source: str                     # database / local_ai / cloud_ai
    confirmed: bool = False         # user-confirmed
    detection_count: int = 1
    last_seen: float = field(default_factory=time.time)
    phase: str = "L1"
    energy_today: float = 0.0      # kWh
    energy_total: float = 0.0      # kWh
    on_events: int = 0
    pending_confirmation: bool = False


class NILMDetector:
    """
    Main NILM detector engine.
    Pipeline: raw power → edge detection → db classify → local AI → cloud AI
    """

    def __init__(
        self,
        model_path: str,
        api_key: Optional[str],
        session: Any,
        on_device_found: Optional[Callable] = None,
        on_device_update: Optional[Callable] = None,
    ):
        self._db = NILMDatabase()
        self._local_ai = LocalAIClassifier(model_path)
        self._cloud_ai = CloudAIClassifier(api_key, session)

        self._on_device_found = on_device_found
        self._on_device_update = on_device_update

        # Per-phase power buffers
        self._power_buffers: Dict[str, deque] = {
            "L1": deque(maxlen=WINDOW_SIZE),
            "L2": deque(maxlen=WINDOW_SIZE),
            "L3": deque(maxlen=WINDOW_SIZE),
        }
        self._last_event_time: Dict[str, float] = {}
        self._baseline_power: Dict[str, float] = {"L1": 0, "L2": 0, "L3": 0}

        # Known devices
        self._devices: Dict[str, DetectedDevice] = {}
        self._active_events: Dict[str, str] = {}  # phase -> device_id

        _LOGGER.info("CloudEMS NILM Detector initialized")

    def update_power(self, phase: str, power_watt: float, timestamp: float = None):
        """Feed a new power reading for a phase."""
        if timestamp is None:
            timestamp = time.time()

        buf = self._power_buffers.get(phase)
        if buf is None:
            return

        buf.append((timestamp, power_watt))

        if len(buf) < 3:
            return

        # Calculate moving average to reduce noise
        recent = list(buf)[-3:]
        avg_power = sum(p for _, p in recent) / len(recent)

        baseline = self._baseline_power[phase]
        delta = avg_power - baseline

        # Detect significant edge
        if abs(delta) >= POWER_CHANGE_THRESHOLD:
            last_event = self._last_event_time.get(phase, 0)
            if timestamp - last_event > DEBOUNCE_TIME:
                self._last_event_time[phase] = timestamp
                rise_time = recent[-1][0] - recent[0][0]

                event = PowerEvent(
                    timestamp=timestamp,
                    delta_power=delta,
                    rise_time=rise_time,
                    duration=0.0,
                    peak_power=max(p for _, p in recent),
                    rms_power=avg_power,
                    phase=phase,
                )
                self._process_event(event)

            # Update baseline for stable states
            if abs(delta) > 200:
                self._baseline_power[phase] = avg_power

    def _process_event(self, event: PowerEvent):
        """Process a detected power event through the classification pipeline."""
        _LOGGER.debug("NILM event: phase=%s delta=%.1fW", event.phase, event.delta_power)

        # 1. Try built-in database first
        matches = self._db.classify(event.delta_power, event.rise_time)

        # 2. Enhance/override with local AI if trained
        if self._local_ai.is_available:
            ai_matches = self._local_ai.classify(event)
            matches = self._merge_matches(matches, ai_matches)

        if not matches:
            _LOGGER.debug("No NILM match found for delta=%.1fW", event.delta_power)
            return

        best = matches[0]

        if best["confidence"] >= NILM_MIN_CONFIDENCE:
            self._handle_match(event, best, matches)

    async def process_event_with_cloud(self, event: PowerEvent):
        """Process event including cloud AI (async)."""
        matches = self._db.classify(event.delta_power, event.rise_time)

        if self._local_ai.is_available:
            ai_matches = self._local_ai.classify(event)
            matches = self._merge_matches(matches, ai_matches)

        # Fallback to cloud if confidence is low or no match
        best_confidence = matches[0]["confidence"] if matches else 0
        if best_confidence < NILM_HIGH_CONFIDENCE and self._cloud_ai.is_available:
            cloud_matches = await self._cloud_ai.classify(
                event.delta_power, event.rise_time,
                {"phase": event.phase, "timestamp": event.timestamp}
            )
            matches = self._merge_matches(matches, cloud_matches)

        if matches and matches[0]["confidence"] >= NILM_MIN_CONFIDENCE:
            self._handle_match(event, matches[0], matches)

    def _merge_matches(self, base: List[Dict], new: List[Dict]) -> List[Dict]:
        """Merge match lists, boosting confidence when multiple sources agree."""
        merged = {m["device_type"]: m.copy() for m in base}
        for m in new:
            dt = m["device_type"]
            if dt in merged:
                # Both sources agree - boost confidence
                merged[dt]["confidence"] = min(
                    merged[dt]["confidence"] + m["confidence"] * 0.3, 1.0
                )
            else:
                merged[dt] = m.copy()
        result = list(merged.values())
        result.sort(key=lambda x: x["confidence"], reverse=True)
        return result

    def _handle_match(self, event: PowerEvent, best: Dict, all_matches: List[Dict]):
        """Create or update a detected device."""
        is_turn_on = event.delta_power > 0

        # Check for existing device of this type on this phase
        existing_id = None
        for dev_id, dev in self._devices.items():
            if dev.device_type == best["device_type"] and dev.phase == event.phase:
                existing_id = dev_id
                break

        if existing_id and existing_id in self._devices:
            dev = self._devices[existing_id]
            dev.is_on = is_turn_on
            dev.confidence = max(dev.confidence, best["confidence"])
            dev.current_power = abs(event.delta_power) if is_turn_on else 0.0
            dev.last_seen = event.timestamp
            dev.detection_count += 1
            if is_turn_on:
                dev.on_events += 1
            if self._on_device_update:
                self._on_device_update(dev)
        else:
            # New device!
            dev_id = str(uuid.uuid4())[:8]
            dev = DetectedDevice(
                device_id=dev_id,
                device_type=best["device_type"],
                name=best.get("name", best["device_type"].replace("_", " ").title()),
                confidence=best["confidence"],
                current_power=abs(event.delta_power) if is_turn_on else 0.0,
                is_on=is_turn_on,
                source=best.get("source", "database"),
                phase=event.phase,
                pending_confirmation=best["confidence"] < NILM_HIGH_CONFIDENCE,
            )
            self._devices[dev_id] = dev
            _LOGGER.info(
                "CloudEMS NILM: New device detected! %s (%.1f%% confidence) on phase %s",
                dev.name, dev.confidence * 100, dev.phase
            )
            if self._on_device_found:
                self._on_device_found(dev, all_matches)

    def confirm_device(self, device_id: str, device_type: str, name: str):
        """User confirms a detected device."""
        if device_id in self._devices:
            dev = self._devices[device_id]
            old_type = dev.device_type
            dev.device_type = device_type
            dev.name = name
            dev.confirmed = True
            dev.pending_confirmation = False
            dev.confidence = 1.0
            _LOGGER.info("CloudEMS NILM: Device %s confirmed as %s", device_id, name)

            # Train local AI with confirmed data
            # (reconstruct a synthetic event for training)
            if self._local_ai and dev.current_power > 0:
                synthetic_event = PowerEvent(
                    timestamp=time.time(),
                    delta_power=dev.current_power,
                    rise_time=2.0,
                    duration=0.0,
                    peak_power=dev.current_power,
                    rms_power=dev.current_power,
                    phase=dev.phase,
                )
                self._local_ai.add_training_sample(synthetic_event, device_type)

    def dismiss_device(self, device_id: str):
        """User dismisses a detected device."""
        if device_id in self._devices:
            del self._devices[device_id]

    def get_devices(self) -> List[DetectedDevice]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[DetectedDevice]:
        return self._devices.get(device_id)

    @property
    def active_mode(self) -> str:
        """Current active classification mode."""
        if self._cloud_ai.is_available:
            return NILM_MODE_CLOUD_AI
        if self._local_ai.is_available:
            return NILM_MODE_LOCAL_AI
        return NILM_MODE_DATABASE
