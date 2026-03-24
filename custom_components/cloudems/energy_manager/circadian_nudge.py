# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Circadian Energy Nudge v1.0.0

Subtly adjusts light brightness and color temperature based on:
  1. EPEX price (expensive = cooler/dimmer, cheap/negative = warmer/brighter)
  2. Grid renewable ratio (high wind/solar = warmer tones to encourage usage)
  3. Time of day (standard circadian curve as base)

Two modes:
  A. NUDGE — psychological: 5-8% unnoticed adjustments to steer behaviour
     - Expensive grid: slightly cooler, slightly dimmer → less activity impulse
     - Cheap/surplus: slightly warmer, slightly brighter → encourage usage
  B. CIRCADIAN — full HCL (Human Centric Lighting) driven by grid composition
     - High renewables available: active/blue-white (6000K)
     - Normal: neutral (4000K)
     - Evening/expensive: warm (2700K)

Only adjusts lights that are already ON. Never turns lights on or off.
Respects manual overrides — if user changed brightness manually, skip that light
for override_cooldown_s seconds.

Configuration:
  circadian_nudge_enabled     bool
  circadian_nudge_mode        "nudge" | "circadian" | "both"
  circadian_nudge_entities    list[str]  — light entity IDs to control
  circadian_nudge_max_shift   int        — max brightness shift % (default 8)
  circadian_nudge_transition  int        — transition seconds (default 30)
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

# Color temperature range (Kelvin)
CT_WARM      = 2700   # evening, expensive grid, encourage rest
CT_NEUTRAL   = 4000   # normal daytime
CT_COOL      = 5500   # active work, surplus renewables
CT_DAYLIGHT  = 6500   # max renewable surplus

# Brightness range (0-255 HA scale)
BRIGHTNESS_MIN = 20
BRIGHTNESS_MAX = 255

# How long to respect manual override before resuming nudge
OVERRIDE_COOLDOWN_S = 1800  # 30 min


@dataclass
class LightState:
    """Tracked state for one light entity."""
    entity_id:          str
    last_nudge_ts:      float = 0.0
    last_nudge_bri:     int   = 0
    last_nudge_ct:      int   = 0
    manual_override_ts: float = 0.0  # when user last changed it


@dataclass
class NudgeTarget:
    """Computed nudge target for one light."""
    entity_id:    str
    brightness:   int    # 0-255
    color_temp_k: int    # Kelvin
    transition_s: int
    reason:       str


class CircadianNudge:
    """
    Applies subtle brightness and color temperature adjustments
    to guide energy behaviour without explicit notifications.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("circadian_nudge_enabled", False)
        self._mode    = config.get("circadian_nudge_mode", "nudge")
        self._entities: list[str]  = config.get("circadian_nudge_entities") or []
        self._max_shift = int(config.get("circadian_nudge_max_shift", 8))
        self._transition = int(config.get("circadian_nudge_transition", 30))
        self._states:  dict[str, LightState] = {}
        self._last_applied: float = 0.0
        self._apply_interval_s = 300  # apply at most every 5 min

    def update_config(self, config: dict) -> None:
        self._config    = config
        self._enabled   = config.get("circadian_nudge_enabled", False)
        self._mode      = config.get("circadian_nudge_mode", "nudge")
        self._entities  = config.get("circadian_nudge_entities") or []
        self._max_shift = int(config.get("circadian_nudge_max_shift", 8))

    async def async_tick(
        self,
        price_eur_kwh:       float,
        price_avg_eur_kwh:   float,
        renewable_pct:       float = 50.0,
        is_negative_price:   bool  = False,
    ) -> list[dict]:
        """
        Main tick — computes and applies nudge targets.

        Args:
            price_eur_kwh:      current all-in price
            price_avg_eur_kwh:  today's average price
            renewable_pct:      % renewables on grid (0-100, from CO2 module)
            is_negative_price:  True if price < 0

        Returns list of applied actions for coordinator data.
        """
        if not self._enabled or not self._entities:
            return []

        now = time.time()
        if now - self._last_applied < self._apply_interval_s:
            return []

        hour = datetime.now().hour
        targets = self._compute_targets(
            price_eur_kwh, price_avg_eur_kwh, renewable_pct, is_negative_price, hour
        )

        applied = []
        for target in targets:
            state = self._hass.states.get(target.entity_id)
            if not state or state.state != "on":
                continue  # only adjust lights that are already on

            # Check manual override
            ls = self._states.get(target.entity_id, LightState(entity_id=target.entity_id))
            if now - ls.manual_override_ts < OVERRIDE_COOLDOWN_S:
                continue

            # Check if light supports color_temp
            supports_ct  = state.attributes.get("supported_color_modes") and \
                           any(m in (state.attributes.get("supported_color_modes") or [])
                               for m in ("color_temp", "hs", "xy", "rgbw"))
            current_bri  = state.attributes.get("brightness") or 128

            service_data: dict = {
                "entity_id":  target.entity_id,
                "transition": target.transition_s,
                "brightness": target.brightness,
            }
            if supports_ct:
                # Convert K to mireds (HA uses mireds: 1000000/K)
                mireds = max(153, min(500, int(1_000_000 / target.color_temp_k)))
                service_data["color_temp"] = mireds

            try:
                await self._hass.services.async_call(
                    "light", "turn_on", service_data, blocking=False
                )
                ls.last_nudge_ts  = now
                ls.last_nudge_bri = target.brightness
                ls.last_nudge_ct  = target.color_temp_k
                self._states[target.entity_id] = ls
                applied.append({
                    "entity_id":    target.entity_id,
                    "brightness":   target.brightness,
                    "color_temp_k": target.color_temp_k,
                    "reason":       target.reason,
                })
                _LOGGER.debug(
                    "CircadianNudge: %s → %d bri, %dK (%s)",
                    target.entity_id, target.brightness, target.color_temp_k, target.reason
                )
            except Exception as e:
                _LOGGER.warning("CircadianNudge: failed for %s: %s", target.entity_id, e)

        if applied:
            self._last_applied = now

        return applied

    def _compute_targets(
        self,
        price:       float,
        price_avg:   float,
        renewable:   float,
        negative:    bool,
        hour:        int,
    ) -> list[NudgeTarget]:
        """Compute target brightness and color_temp for each entity."""
        # Base circadian curve (independent of price)
        base_ct, base_bri = self._circadian_base(hour)

        # Price signal: how expensive vs average? (-1.0 = very cheap, +1.0 = very expensive)
        if price_avg > 0:
            price_ratio = (price - price_avg) / max(0.05, price_avg)
            price_signal = max(-1.0, min(1.0, price_ratio))
        else:
            price_signal = 0.0

        if negative:
            price_signal = -1.0  # maximum cheapness signal

        # Renewable signal: 0 = fossil, 1 = full renewable
        renewable_signal = (renewable - 50) / 50  # -1 to +1

        targets = []
        for eid in self._entities:
            if self._mode == "nudge":
                # Subtle: only shift by max_shift%
                shift_pct = -price_signal * self._max_shift  # expensive → dim
                bri_shift = int(BRIGHTNESS_MAX * shift_pct / 100)
                ct_shift  = int(-price_signal * 300)  # expensive → cooler
                target_bri = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, base_bri + bri_shift))
                target_ct  = max(CT_WARM, min(CT_DAYLIGHT, base_ct + ct_shift))
                reason = (
                    f"duur ({price:.3f}€)" if price_signal > 0.3
                    else f"goedkoop ({price:.3f}€)" if price_signal < -0.3
                    else "normaal tarief"
                )

            elif self._mode == "circadian":
                # Full HCL driven by renewables + time
                renewable_ct  = int(base_ct + renewable_signal * 500)
                target_ct     = max(CT_WARM, min(CT_DAYLIGHT, renewable_ct))
                target_bri    = base_bri
                reason = f"{renewable:.0f}% hernieuwbaar"

            else:  # both
                shift_pct = -price_signal * self._max_shift
                bri_shift = int(BRIGHTNESS_MAX * shift_pct / 100)
                renewable_ct_shift = int(renewable_signal * 300)
                target_bri = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, base_bri + bri_shift))
                target_ct  = max(CT_WARM, min(CT_DAYLIGHT,
                                              base_ct - int(price_signal * 200) + renewable_ct_shift))
                reason = f"prijs {price:.3f}€, {renewable:.0f}% hernieuwbaar"

            targets.append(NudgeTarget(
                entity_id    = eid,
                brightness   = target_bri,
                color_temp_k = target_ct,
                transition_s = self._transition,
                reason       = reason,
            ))

        return targets

    def _circadian_base(self, hour: int) -> tuple[int, int]:
        """Base color temp and brightness by time of day."""
        if 6 <= hour < 9:    return CT_COOL,    180  # morning: energetic
        if 9 <= hour < 12:   return CT_DAYLIGHT, 230  # work: max focus
        if 12 <= hour < 14:  return CT_COOL,    200  # lunch
        if 14 <= hour < 17:  return CT_DAYLIGHT, 220  # afternoon work
        if 17 <= hour < 20:  return CT_NEUTRAL,  180  # evening starts
        if 20 <= hour < 22:  return CT_WARM,    140  # winding down
        return CT_WARM, 80  # night: very warm and dim

    def notify_manual_override(self, entity_id: str) -> None:
        """Call when user manually changes a light — pauses nudge for cooldown."""
        ls = self._states.get(entity_id, LightState(entity_id=entity_id))
        ls.manual_override_ts = time.time()
        self._states[entity_id] = ls

    def get_status(self) -> dict:
        return {
            "enabled":      self._enabled,
            "mode":         self._mode,
            "entities":     len(self._entities),
            "max_shift_pct":self._max_shift,
            "last_applied": self._last_applied,
            "active_states": [
                {
                    "entity_id":   ls.entity_id,
                    "last_ct_k":   ls.last_nudge_ct,
                    "last_bri":    ls.last_nudge_bri,
                }
                for ls in self._states.values()
                if ls.last_nudge_ts > 0
            ],
        }
