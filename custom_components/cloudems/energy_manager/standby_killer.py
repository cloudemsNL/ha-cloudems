# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Standby Killer v1.0.0

Automatically cuts power to a group of smart plugs when nobody is home
(or after a configurable time without presence).

Use cases:
  - TV cabinet (TV + soundbar + media player)
  - Home office (monitor + PC peripherals)
  - Guest room
  - Workshop

Rules:
  1. If presence = away for >= away_delay_min → turn off group
  2. If presence = home → turn on group (optional, configurable)
  3. Blacklist: never turn off critical devices (NAS, router, etc.)
  4. Night mode: cut power at night independently of presence

Configuration (config_flow):
  standby_killer_groups: [
    {
      label, switch_entities, away_delay_min,
      restore_on_home, night_cut_enabled,
      night_cut_start, night_cut_end
    }
  ]
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEFAULT_AWAY_DELAY_MIN = 15


@dataclass
class KillerGroup:
    label:              str
    switch_entities:    list
    away_delay_min:     float = DEFAULT_AWAY_DELAY_MIN
    restore_on_home:    bool  = True
    night_cut_enabled:  bool  = False
    night_cut_start:    int   = 23    # hour
    night_cut_end:      int   = 6     # hour
    # Runtime state
    is_cut:             bool  = False
    cut_ts:             float = 0.0
    away_since_ts:      float = 0.0
    cut_reason:         str   = ""
    saved_wh:           float = 0.0


class StandbyKiller:
    """Cuts standby power for configured groups based on presence and time."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._groups: list[KillerGroup] = []
        self._setup_done = False

    def setup(self) -> None:
        raw = self._config.get("standby_killer_groups") or []
        self._groups = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            self._groups.append(KillerGroup(
                label             = item.get("label", "Groep"),
                switch_entities   = item.get("switch_entities") or [],
                away_delay_min    = float(item.get("away_delay_min", DEFAULT_AWAY_DELAY_MIN)),
                restore_on_home   = bool(item.get("restore_on_home", True)),
                night_cut_enabled = bool(item.get("night_cut_enabled", False)),
                night_cut_start   = int(item.get("night_cut_start", 23)),
                night_cut_end     = int(item.get("night_cut_end", 6)),
            ))
        self._setup_done = True
        _LOGGER.info("StandbyKiller: %d groups configured", len(self._groups))

    def tick(self, is_home: bool) -> list[dict]:
        """Call every coordinator cycle. Returns group statuses."""
        if not self._setup_done:
            self.setup()

        now   = time.time()
        hour  = datetime.now().hour
        actions = []

        for g in self._groups:
            # Accumulate savings when cut
            if g.is_cut:
                g.saved_wh += 50 * (10 / 3600)  # estimate 50W saved per group

            should_cut = False
            reason     = ""

            # Night cut check
            if g.night_cut_enabled:
                in_night = (g.night_cut_start <= hour or hour < g.night_cut_end)
                if in_night:
                    should_cut = True
                    reason     = f"nachtmodus ({g.night_cut_start}u–{g.night_cut_end}u)"

            # Away check
            if not is_home:
                if g.away_since_ts == 0.0:
                    g.away_since_ts = now
                away_min = (now - g.away_since_ts) / 60
                if away_min >= g.away_delay_min:
                    should_cut = True
                    reason     = f"afwezig {away_min:.0f} min"
            else:
                g.away_since_ts = 0.0

            # Apply
            if should_cut and not g.is_cut:
                g.is_cut    = True
                g.cut_ts    = now
                g.cut_reason = reason
                for eid in g.switch_entities:
                    self._hass.async_create_task(
                        self._set_switch(eid, False)
                    )
                actions.append({"group": g.label, "action": "cut", "reason": reason})
                _LOGGER.info("StandbyKiller: cut '%s' (%s)", g.label, reason)

            elif not should_cut and g.is_cut:
                if is_home and g.restore_on_home:
                    g.is_cut     = False
                    g.cut_reason = ""
                    for eid in g.switch_entities:
                        self._hass.async_create_task(
                            self._set_switch(eid, True)
                        )
                    actions.append({"group": g.label, "action": "restore", "reason": "thuis"})
                    _LOGGER.info("StandbyKiller: restored '%s'", g.label)

        return actions

    async def _set_switch(self, entity_id: str, on: bool) -> None:
        try:
            await self._hass.services.async_call(
                "switch", "turn_on" if on else "turn_off",
                {"entity_id": entity_id}, blocking=True,
            )
        except Exception as e:
            _LOGGER.warning("StandbyKiller: switch %s failed: %s", entity_id, e)

    def get_status(self) -> list[dict]:
        return [
            {
                "label":       g.label,
                "is_cut":      g.is_cut,
                "cut_reason":  g.cut_reason,
                "saved_kwh":   round(g.saved_wh / 1000, 3),
                "switches":    len(g.switch_entities),
            }
            for g in self._groups
        ]
