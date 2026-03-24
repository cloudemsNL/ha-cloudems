"""
CloudEMS Shutter Pattern Learner — v1.0.0

Learns when shutters are opened/closed based on:
  - Time of day + day of week
  - Solar radiation / cloud cover
  - Outside temperature
  - Season

Predicts optimal shutter positions without manual rules.
Works alongside the existing ShutterThermalLearner — this one learns
the user's *behavioral* patterns (when do they actually open/close?),
while the thermal learner handles energy optimization.

The AI learns per-shutter because each room behaves differently:
  - Slaapkamer: opened early morning, closed for privacy at night
  - Woonkamer: opened when sunny but not too hot, closed in evening
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_shutter_pattern_v1"
STORAGE_VERSION = 1

MIN_OBSERVATIONS = 10
MAX_OBSERVATIONS = 500


@dataclass
class ShutterObservation:
    """One observed shutter state change."""
    shutter_id:  str
    hour:        float          # time of day
    dow:         int            # day of week
    position:    int            # 0=closed, 100=open
    solar_w:     float          # solar radiation W/m²
    temp_out:    float          # outside temp °C
    cloud_pct:   float          # cloud cover %
    ts:          float


class ShutterPatternLearner:
    """
    Learns per-shutter behavioral patterns.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass   = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._observations: dict[str, list[ShutterObservation]] = {}
        self._last_positions: dict[str, int] = {}
        self._dirty = False

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for shutter_id, obs_list in saved.get("observations", {}).items():
            self._observations[shutter_id] = []
            for o in obs_list:
                try:
                    self._observations[shutter_id].append(ShutterObservation(**o))
                except Exception:
                    pass
        _LOGGER.info(
            "Shutter Pattern Learner: loaded %d shutters",
            len(self._observations)
        )

    def observe(
        self,
        shutter_id: str,
        position:   int,
        solar_w:    float,
        temp_out:   float,
        cloud_pct:  float,
        ts:         Optional[float] = None,
    ) -> None:
        """Record a shutter position observation. Call when position changes."""
        ts = ts or time.time()
        now = datetime.fromtimestamp(ts, tz=timezone.utc)
        hour = now.hour + now.minute / 60.0
        dow  = now.weekday()

        last = self._last_positions.get(shutter_id)
        if last == position:
            return  # no change, skip

        self._last_positions[shutter_id] = position

        obs = ShutterObservation(
            shutter_id=shutter_id, hour=hour, dow=dow,
            position=position, solar_w=solar_w,
            temp_out=temp_out, cloud_pct=cloud_pct, ts=ts,
        )
        if shutter_id not in self._observations:
            self._observations[shutter_id] = []
        self._observations[shutter_id].append(obs)
        if len(self._observations[shutter_id]) > MAX_OBSERVATIONS:
            self._observations[shutter_id] = self._observations[shutter_id][-MAX_OBSERVATIONS:]
        self._dirty = True

    def predict(
        self,
        shutter_id: str,
        hour:       float,
        dow:        int,
        solar_w:    float,
        temp_out:   float,
        cloud_pct:  float,
    ) -> dict:
        """
        Predict recommended position for a shutter.
        Returns {'position': int, 'confidence': float, 'reason': str}
        """
        obs_list = self._observations.get(shutter_id, [])
        if len(obs_list) < MIN_OBSERVATIONS:
            return {"position": None, "confidence": 0.0, "reason": "not enough data"}

        # Find similar past observations (k-NN in feature space)
        def similarity(o: ShutterObservation) -> float:
            hour_diff  = min(abs(o.hour - hour), 24 - abs(o.hour - hour)) / 12.0
            dow_diff   = min(abs(o.dow - dow), 7 - abs(o.dow - dow)) / 3.5
            solar_diff = abs(o.solar_w - solar_w) / max(1.0, max(o.solar_w, solar_w))
            temp_diff  = abs(o.temp_out - temp_out) / max(1.0, abs(o.temp_out) + abs(temp_out) + 1)
            dist = math.sqrt(hour_diff**2 + dow_diff**2 * 0.5 + solar_diff**2 * 0.3 + temp_diff**2 * 0.2)
            return math.exp(-dist * 2)  # Gaussian kernel

        # Weight recent observations higher
        now_ts = time.time()
        weighted = [
            (similarity(o) * math.exp(-(now_ts - o.ts) / (30 * 86400)), o.position)
            for o in obs_list
        ]
        weighted.sort(reverse=True)
        top_k = weighted[:7]

        total_w = sum(w for w, _ in top_k)
        if total_w < 0.01:
            return {"position": None, "confidence": 0.0, "reason": "no similar observations"}

        avg_pos = sum(w * p for w, p in top_k) / total_w

        # Snap to 0, 25, 50, 75, or 100
        snapped = round(avg_pos / 25) * 25
        confidence = min(0.85, total_w * 2.0)

        reason = (
            f"Gebaseerd op {len(top_k)} vergelijkbare momenten. "
            f"Avg positie: {avg_pos:.0f}%"
        )
        return {
            "position":   int(snapped),
            "confidence": round(confidence, 3),
            "reason":     reason,
        }

    async def async_maybe_save(self) -> None:
        if self._dirty:
            await self._save()

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "observations": {
                    sid: [
                        {"shutter_id": o.shutter_id, "hour": o.hour, "dow": o.dow,
                         "position": o.position, "solar_w": o.solar_w,
                         "temp_out": o.temp_out, "cloud_pct": o.cloud_pct, "ts": o.ts}
                        for o in obs
                    ]
                    for sid, obs in self._observations.items()
                }
            })
            self._dirty = False
        except Exception as exc:
            _LOGGER.warning("Shutter Pattern save error: %s", exc)

    @property
    def stats(self) -> dict:
        return {
            "n_shutters":     len(self._observations),
            "total_obs":      sum(len(v) for v in self._observations.values()),
            "shutters_ready": sum(
                1 for v in self._observations.values() if len(v) >= MIN_OBSERVATIONS
            ),
        }
