# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Appliance Done Notifier v1.0.0

Sends a push notification when the washing machine or dryer finishes.
Builds on existing wash_cycle.py phase detection (WasFase.IDLE after RUN).

Works without wash_cycle.py too — uses power-based detection directly:
  1. Power rises above threshold (appliance started)
  2. Power drops below idle threshold for > cooldown period
  3. Send notification

Also supports any other appliance (dishwasher, oven, etc.) via config.

Configuration per appliance:
  done_notifier_appliances: [
    {label, power_entity, start_threshold_w, idle_threshold_w, cooldown_s, notify_service}
  ]
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEFAULT_START_W    = 50.0    # W above this = appliance running
DEFAULT_IDLE_W     = 10.0    # W below this = appliance done
DEFAULT_COOLDOWN_S = 120.0   # must be idle for 2 min before notifying
DEFAULT_MIN_RUN_S  = 60.0    # must have run for at least 1 min


@dataclass
class ApplianceState:
    label:           str
    power_entity:    str
    start_w:         float = DEFAULT_START_W
    idle_w:          float = DEFAULT_IDLE_W
    cooldown_s:      float = DEFAULT_COOLDOWN_S
    min_run_s:       float = DEFAULT_MIN_RUN_S
    # Runtime state
    is_running:      bool  = False
    run_start_ts:    float = 0.0
    idle_since_ts:   float = 0.0
    notified:        bool  = False   # prevent double notification
    last_run_s:      float = 0.0     # duration of last completed run


class ApplianceDoneNotifier:
    """
    Monitors configured appliances and fires push notifications
    when a cycle completes.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass     = hass
        self._config   = config
        self._states:  list[ApplianceState] = []
        self._setup_done = False

    def setup(self) -> None:
        """Build appliance list from config."""
        raw = self._config.get("done_notifier_appliances") or []
        self._states = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            self._states.append(ApplianceState(
                label        = item.get("label", "Apparaat"),
                power_entity = item.get("power_entity", ""),
                start_w      = float(item.get("start_threshold_w", DEFAULT_START_W)),
                idle_w       = float(item.get("idle_threshold_w", DEFAULT_IDLE_W)),
                cooldown_s   = float(item.get("cooldown_s", DEFAULT_COOLDOWN_S)),
            ))
        self._setup_done = True
        _LOGGER.info("ApplianceDoneNotifier: %d appliances configured", len(self._states))

    def tick(self) -> list[dict]:
        """
        Call every coordinator cycle.
        Returns list of appliances that just finished (for coordinator data).
        """
        if not self._setup_done:
            self.setup()

        finished = []
        now = time.time()

        for s in self._states:
            if not s.power_entity:
                continue
            state = self._hass.states.get(s.power_entity)
            if not state or state.state in ("unavailable", "unknown"):
                continue
            try:
                power_w = float(state.state)
            except (ValueError, TypeError):
                continue

            if not s.is_running and power_w >= s.start_w:
                # Appliance started
                s.is_running   = True
                s.run_start_ts = now
                s.idle_since_ts = 0.0
                s.notified     = False
                _LOGGER.debug("ApplianceDoneNotifier: %s started (%.0fW)", s.label, power_w)

            elif s.is_running and power_w < s.idle_w:
                # Appliance dropped to idle
                if s.idle_since_ts == 0.0:
                    s.idle_since_ts = now

                idle_duration = now - s.idle_since_ts
                run_duration  = now - s.run_start_ts

                if (idle_duration >= s.cooldown_s
                        and run_duration >= s.min_run_s
                        and not s.notified):
                    # Cycle complete — notify
                    s.last_run_s = round(run_duration)
                    s.notified   = True
                    s.is_running = False
                    finished.append({
                        "label":      s.label,
                        "run_min":    round(run_duration / 60, 1),
                        "power_entity": s.power_entity,
                    })
                    _LOGGER.info("ApplianceDoneNotifier: %s done after %.0f min",
                                 s.label, run_duration / 60)
                    self._hass.async_create_task(
                        self._send_notification(s.label, round(run_duration / 60))
                    )

            elif s.is_running and power_w >= s.start_w:
                # Still running — reset idle timer
                s.idle_since_ts = 0.0

        return finished

    async def _send_notification(self, label: str, duration_min: int) -> None:
        """Send persistent HA notification."""
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":           f"✅ {label} klaar!",
                    "message":         f"{label} heeft zijn programma afgerond na {duration_min} minuten. "
                                       f"Vergeet niet om de was/vaat te verwijderen.",
                    "notification_id": f"cloudems_done_{label.lower().replace(' ', '_')}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.warning("ApplianceDoneNotifier: notification failed: %s", e)

    def get_status(self) -> list[dict]:
        return [
            {
                "label":       s.label,
                "is_running":  s.is_running,
                "power_entity":s.power_entity,
                "last_run_s":  s.last_run_s,
            }
            for s in self._states
        ]
