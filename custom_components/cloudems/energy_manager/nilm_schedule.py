# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS NILM Schedule Learner — v1.0.0

Learns WHEN each detected appliance typically runs.

For each device × weekday × hour slot it counts how often the device
was active. After enough observations it can:
  - Show a typical weekly schedule per device
  - Detect if a device runs at an unusual time → alert
  - Feed into cost optimisation ("wasmachine usually runs Sat 10h, move to Sat 6h")

Zero config: data comes from the existing NILM device `is_on` state.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_nilm_schedule_v1"
STORAGE_VERSION = 1

MIN_OBSERVATIONS    = 14    # observations before schedule is reliable
UNUSUAL_THRESHOLD   = 0.10  # slot fraction below which a run is "unusual"
SAVE_INTERVAL_S     = 600


@dataclass
class DeviceSchedule:
    device_id:   str
    device_type: str
    label:       str
    # slot_counts[weekday][hour] = times device was on during that slot
    slot_counts: list[list[int]] = field(default_factory=lambda: [[0]*24 for _ in range(7)])
    total_obs:   int = 0
    # Derived after enough data
    peak_weekday: Optional[int] = None
    peak_hour:    Optional[int] = None
    # v1.32: BehaviourCoach feedback — aanbevolen verschuivingsuur
    coach_suggested_hour: Optional[int] = None
    coach_saving_eur_month: float = 0.0

    def observe(self, weekday: int, hour: int, is_on: bool) -> None:
        if is_on:
            self.slot_counts[weekday][hour] += 1
        self.total_obs += 1

    def fraction(self, weekday: int, hour: int) -> float:
        """Fraction of time device was on in this slot."""
        if self.total_obs == 0:
            return 0.0
        return self.slot_counts[weekday][hour] / max(1, self.total_obs // (7 * 24))

    def is_unusual(self, weekday: int, hour: int) -> bool:
        """True if device running in this slot is historically rare."""
        if self.total_obs < MIN_OBSERVATIONS * 7 * 24:
            return False
        return self.fraction(weekday, hour) < UNUSUAL_THRESHOLD

    def peak_slot(self) -> tuple[Optional[int], Optional[int]]:
        """Weekday + hour with highest observed frequency."""
        best_wd, best_h, best_cnt = None, None, 0
        for wd in range(7):
            for h in range(24):
                c = self.slot_counts[wd][h]
                if c > best_cnt:
                    best_cnt = c
                    best_wd, best_h = wd, h
        return best_wd, best_h

    def to_dict(self) -> dict:
        return {
            "device_id":              self.device_id,
            "device_type":            self.device_type,
            "label":                  self.label,
            "slot_counts":            self.slot_counts,
            "total_obs":              self.total_obs,
            "coach_suggested_hour":   self.coach_suggested_hour,
            "coach_saving_eur_month": self.coach_saving_eur_month,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceSchedule":
        s = cls(
            device_id              = d.get("device_id", ""),
            device_type            = d.get("device_type", "unknown"),
            label                  = d.get("label", ""),
            slot_counts            = d.get("slot_counts", [[0]*24 for _ in range(7)]),
            total_obs              = d.get("total_obs", 0),
            coach_suggested_hour   = d.get("coach_suggested_hour"),
            coach_saving_eur_month = float(d.get("coach_saving_eur_month", 0.0)),
        )
        return s


class NILMScheduleLearner:
    """
    Learns weekly schedule patterns per NILM device.

    Usage:
        sl = NILMScheduleLearner(hass)
        await sl.async_setup()
        # Every 10s:
        sl.update(devices)   # list of dicts from nilm.get_devices_for_ha()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass     = hass
        self._store   = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._devices: dict[str, DeviceSchedule] = {}
        self._last_save: float = 0.0
        self._dirty: bool = False

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for d in saved.get("devices", []):
            dev = DeviceSchedule.from_dict(d)
            self._devices[dev.device_id] = dev
        _LOGGER.info("CloudEMS NILMSchedule: %d apparaten geladen", len(self._devices))

    def update(self, nilm_devices: list[dict]) -> list[dict]:
        """
        Observe current device states and return enriched device list
        with schedule metadata appended.
        """
        now = datetime.now(timezone.utc)
        wd  = now.weekday()
        h   = now.hour
        DAYS = ["Maandag","Dinsdag","Woensdag","Donderdag","Vrijdag","Zaterdag","Zondag"]

        enriched = []
        for dev in nilm_devices:
            did   = dev.get("device_id", "")
            is_on = dev.get("is_on", False)
            dtype = dev.get("device_type", "unknown")
            label = dev.get("name") or dev.get("label") or dtype

            # Ensure schedule exists
            if did not in self._devices:
                self._devices[did] = DeviceSchedule(
                    device_id=did, device_type=dtype, label=label
                )
                self._dirty = True

            sched = self._devices[did]
            sched.label       = label
            sched.device_type = dtype
            sched.observe(wd, h, is_on)
            if sched.total_obs % 360 == 1:   # every ~1h
                self._dirty = True

            # Derive peak slot
            peak_wd, peak_h = sched.peak_slot()
            unusual = sched.is_unusual(wd, h) and is_on

            enriched.append({
                **dev,
                "schedule_unusual": unusual,
                "schedule_peak_weekday": DAYS[peak_wd] if peak_wd is not None else None,
                "schedule_peak_hour":    peak_h,
                "schedule_observations": sched.total_obs,
                "schedule_ready":        sched.total_obs >= MIN_OBSERVATIONS * 7 * 24,
            })

        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            self.hass.async_create_task(self._async_save())

        return enriched

    async def _async_save(self) -> None:
        await self._store.async_save({
            "devices": [d.to_dict() for d in self._devices.values()]
        })
        self._dirty = False
        self._last_save = time.time()

    def get_unusual_devices(self) -> list[dict]:
        """Return devices that ran at an unusual time this observation."""
        return []   # real-time via update() return value

    def apply_coach_feedback(self, coach_results: list[dict]) -> None:
        """
        v1.32: Verwerk BehaviourCoach-aanbevelingen terug in DeviceSchedule.

        coach_results: list van dicts uit BehaviourCoach.to_sensor_dict()["devices"]
          [{device_id, cheapest_hour, saving_eur_month, ...}, ...]

        Het aanbevolen uur wordt opgeslagen en zichtbaar in sensor-attributen,
        zodat het dashboard de badge "verschuif naar 03:00 → €4.20/mnd" kan tonen.
        """
        for result in coach_results:
            did          = result.get("device_id", "")
            sug_hour     = result.get("cheapest_hour")
            saving       = float(result.get("saving_eur_month", 0.0))
            if did in self._devices and sug_hour is not None:
                sched = self._devices[did]
                sched.coach_suggested_hour    = int(sug_hour)
                sched.coach_saving_eur_month  = round(saving, 2)
                self._dirty = True

    def get_schedule_summary(self) -> list[dict]:
        """Return one summary per device for sensor attributes."""
        DAYS = ["Ma","Di","Wo","Do","Vr","Za","Zo"]
        out = []
        for sched in self._devices.values():
            peak_wd, peak_h = sched.peak_slot()
            out.append({
                "device_id":              sched.device_id,
                "device_type":            sched.device_type,
                "label":                  sched.label,
                "peak_weekday":           DAYS[peak_wd] if peak_wd is not None else None,
                "peak_hour":              peak_h,
                "observations":           sched.total_obs,
                "ready":                  sched.total_obs >= MIN_OBSERVATIONS * 7 * 24,
                "coach_suggested_hour":   sched.coach_suggested_hour,
                "coach_saving_eur_month": sched.coach_saving_eur_month,
            })
        return out
