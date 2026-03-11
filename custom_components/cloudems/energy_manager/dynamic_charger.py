# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Dynamic EV Charger.

Adjusts EV charging current based on:
  1. Current EPEX spot price vs configured cheap threshold
  2. Solar surplus availability
  3. Phase current limits

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_EV_CHARGER_ENTITY,
    CONF_EV_CHEAP_THRESHOLD,
    CONF_EV_ALWAYS_ON_CURRENT,
    CONF_EV_SOLAR_SURPLUS_PRIO,
    CONF_PHASE_COUNT,
    CONF_MAX_CURRENT_L1,
    DEFAULT_EV_CHEAP_THRESHOLD,
    DEFAULT_EV_ALWAYS_ON_CURRENT,
    MIN_EV_CURRENT,
    MAX_EV_CURRENT,
)

_LOGGER = logging.getLogger(__name__)

# Voltage assumed for power→current conversion
GRID_VOLTAGE = 230.0  # V


@dataclass
class ChargeDecision:
    target_current_a: float
    reason: str
    price_eur_kwh: float | None
    solar_surplus_w: float


class DynamicEVCharger:
    """
    Smart EV charge controller.

    Strategy (priority order):
      1. Phase over-limit protection always wins (handled by PhaseLimiter).
      2. If solar surplus ≥ min EV current × voltage  → charge on surplus.
      3. If EPEX price ≤ cheap threshold              → charge at max allowed.
      4. Otherwise                                    → charge at floor current.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config = {**entry.data, **entry.options}
        self._last_decision: ChargeDecision | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        current_price: float | None,
        solar_surplus_w: float,
        phase_headroom_a: float,       # min headroom across active phases
    ) -> ChargeDecision:
        """Compute target EV current and apply it."""
        cheap_threshold  = float(self.config.get(CONF_EV_CHEAP_THRESHOLD, DEFAULT_EV_CHEAP_THRESHOLD))
        floor_current    = float(self.config.get(CONF_EV_ALWAYS_ON_CURRENT, DEFAULT_EV_ALWAYS_ON_CURRENT))
        solar_priority   = bool(self.config.get(CONF_EV_SOLAR_SURPLUS_PRIO, True))

        # Max current we can use without tripping the phase limiter
        phase_count      = int(self.config.get(CONF_PHASE_COUNT, 1))
        max_phase_a      = float(self.config.get(CONF_MAX_CURRENT_L1, 25))
        safe_max_a       = min(MAX_EV_CURRENT, max_phase_a, phase_headroom_a + floor_current)

        target_a: float
        reason: str

        # 1 — Solar surplus charging
        if solar_priority and solar_surplus_w > 0:
            surplus_per_phase_a = solar_surplus_w / (GRID_VOLTAGE * phase_count)
            solar_current = max(MIN_EV_CURRENT, min(safe_max_a, surplus_per_phase_a))
            target_a = round(solar_current, 1)
            reason = f"zonne-energie surplus ({solar_surplus_w:.0f} W → {target_a:.1f} A)"

        # 2 — Cheap EPEX price
        elif current_price is not None and current_price <= cheap_threshold:
            target_a = safe_max_a
            reason = (
                f"goedkope stroom ({current_price:.4f} EUR/kWh "
                f"≤ drempel {cheap_threshold:.4f} EUR/kWh)"
            )

        # 3 — Default floor
        else:
            target_a = floor_current
            price_str = f"{current_price:.4f} EUR/kWh" if current_price is not None else "onbekend"
            reason = f"dure stroom ({price_str}) — minimale laadstroom"

        target_a = max(MIN_EV_CURRENT, min(MAX_EV_CURRENT, target_a))

        decision = ChargeDecision(
            target_current_a=target_a,
            reason=reason,
            price_eur_kwh=current_price,
            solar_surplus_w=solar_surplus_w,
        )

        # Apply only if changed by ≥ 0.5 A to reduce noise
        if (
            self._last_decision is None
            or abs(decision.target_current_a - self._last_decision.target_current_a) >= 0.5
        ):
            await self._apply_current(target_a)
            _LOGGER.info("DynamicEVCharger: %s → %.1f A", reason, target_a)

        self._last_decision = decision
        return decision

    async def _apply_current(self, ampere: float) -> None:
        """Write target current to EV charger entity."""
        entity_id = self.config.get(CONF_EV_CHARGER_ENTITY)
        if not entity_id:
            return
        try:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": entity_id, "value": round(ampere, 1)},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("DynamicEVCharger: kon stroom niet instellen: %s", err)

    @property
    def last_decision(self) -> ChargeDecision | None:
        return self._last_decision
