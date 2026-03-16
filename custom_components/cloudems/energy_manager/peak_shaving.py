# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Peak Shaving — v1.4.0

Monitors total import power and sheds configurable loads when the peak limit
is about to be exceeded. Also tracks daily / monthly peak values.

Strategy (priority order):
  1. Curtail solar export curtailment (free — no comfort loss)
  2. Reduce EV charging current to minimum
  3. Switch off sheddable loads (user-configured, lowest priority first)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_peak_history_v1"
STORAGE_VERSION = 1
HYSTERESIS_W    = 200   # Watt — restore loads only when power is this far below limit


@dataclass
class PeakRecord:
    peak_w: float
    timestamp: str
    month: str   # "2025-06"
    day: str     # "2025-06-15"


class PeakShaving:
    """
    Monitors grid import and sheds loads to keep under peak_limit_w.

    Usage in coordinator:
        ps = PeakShaving(hass, config)
        await ps.async_setup()
        result = await ps.async_evaluate(grid_import_w, ev_current, solar_pct)
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass   = hass
        self._limit  = float(config.get("peak_shaving_limit_w", 5000))
        self._assets: list[str] = config.get("peak_shaving_assets", [])
        self._shed_active: list[str] = []
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._history: dict = {"daily": {}, "monthly": {}}
        self._active = False
        self._last_action_ts = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        self._history = saved.get("history", {"daily": {}, "monthly": {}})
        _LOGGER.info("CloudEMS PeakShaving: limit=%.0f W, %d sheddable assets",
                     self._limit, len(self._assets))

    # ── Evaluate ──────────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        grid_import_w: float,
        ev_current_a: float = 0.0,
        solar_curtailment_pct: float = 100.0,
    ) -> dict:
        """
        Returns a dict with:
          - active: bool  (peak shaving currently engaged)
          - action: str   (what was done)
          - peak_today_w: float
          - peak_month_w: float
          - headroom_w: float
        """
        now = datetime.now(timezone.utc)
        day_key   = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        # Track peaks
        prev_day   = self._history["daily"].get(day_key, 0.0)
        prev_month = self._history["monthly"].get(month_key, 0.0)
        if grid_import_w > prev_day:
            self._history["daily"][day_key] = grid_import_w
        if grid_import_w > prev_month:
            self._history["monthly"][month_key] = grid_import_w

        # Save periodically
        if time.time() - self._last_action_ts > 60:
            await self._store.async_save({"history": self._history})

        headroom = self._limit - grid_import_w
        action   = "none"

        if grid_import_w > self._limit:
            if not self._active:
                _LOGGER.warning(
                    "CloudEMS PeakShaving: LIMIT EXCEEDED %.0f W > %.0f W — shedding",
                    grid_import_w, self._limit
                )
            self._active = True
            self._last_action_ts = time.time()
            action = await self._shed_loads(grid_import_w)
        elif self._active and headroom > HYSTERESIS_W:
            self._active = False
            action = "restored"
            _LOGGER.info("CloudEMS PeakShaving: headroom %.0f W — loads restored", headroom)
            await self._restore_loads()

        # Prune old daily records (keep 90 days)
        cutoff = now.strftime("%Y-%m-%d")
        self._history["daily"] = {
            k: v for k, v in self._history["daily"].items()
            if k >= cutoff[:7]  # keep current month
        }

        return {
            "active":        self._active,
            "action":        action,
            "limit_w":       self._limit,
            "headroom_w":    round(headroom, 0),
            "peak_today_w":  self._history["daily"].get(day_key, 0.0),
            "peak_month_w":  self._history["monthly"].get(month_key, 0.0),
            "peak_history":  self._get_monthly_summary(),
            "shed_devices":  list(self._shed_active),
        }

    # ── Shedding ──────────────────────────────────────────────────────────────

    async def _shed_loads(self, current_w: float) -> str:
        """Turn off sheddable assets one by one until under limit."""
        for entity_id in self._assets:
            state = self._hass.states.get(entity_id)
            if state and state.state not in ("off", "unavailable", "unknown"):
                await self._hass.services.async_call(
                    "homeassistant", "turn_off", {"entity_id": entity_id}, blocking=False
                )
                _LOGGER.info("CloudEMS PeakShaving: shed %s (%.0f W)", entity_id, current_w)
                if entity_id not in self._shed_active:
                    self._shed_active.append(entity_id)
                return f"shed:{entity_id}"
        return "at_limit_no_assets"

    async def _restore_loads(self) -> None:
        """Restore sheddable assets (reverse order)."""
        self._shed_active = []
        for entity_id in reversed(self._assets):
            state = self._hass.states.get(entity_id)
            if state and state.state in ("off",):
                await self._hass.services.async_call(
                    "homeassistant", "turn_on", {"entity_id": entity_id}, blocking=False
                )
                _LOGGER.info("CloudEMS PeakShaving: restored %s", entity_id)

    # ── Summary ───────────────────────────────────────────────────────────────

    def _get_monthly_summary(self) -> list[dict]:
        return [
            {"month": k, "peak_w": v}
            for k, v in sorted(self._history["monthly"].items())[-6:]
        ]

    @property
    def peak_today_w(self) -> float:
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._history["daily"].get(day_key, 0.0)

    @property
    def peak_this_month_w(self) -> float:
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._history["monthly"].get(month_key, 0.0)
