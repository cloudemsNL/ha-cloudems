# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
DemandResponseManager — v1.1.0

Responds to grid congestion signals and adjusts energy consumption automatically.

Signal sources:
  1. GOPACS BRP-pooling signal (NL imbalance market)
     → when the grid is short, discharging can earn extra revenue
  2. TenneT Transparency Platform (ENTSO-E) — day-ahead congestion
  3. Automatic EPEX-based demand response (no API key required)
     → when EPEX > threshold: defer flexible consumption

Actions:
  SHED    — reduce consumption (defer boiler, slow EV charging)
  SHIFT   — defer to another hour (washing machine, dishwasher)
  BOOST   — charge battery at maximum rate (during surplus)
  EXPORT  — discharge battery to grid (during shortage + high price)

Configuration:
  dr_enabled           — enable/disable
  dr_epex_shed_eur     — EPEX threshold for SHED (e.g. 0.50 €/kWh)
  dr_epex_boost_eur    — EPEX threshold for BOOST charging (e.g. 0.05 €/kWh)
  dr_notify            — send notification on action

No API key required for EPEX-based DR.
TenneT transparency API is free but requires registration.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Default EPEX thresholds (all-in EUR/kWh)
DEFAULT_SHED_THRESHOLD   = 0.50   # above this: reduce consumption
DEFAULT_BOOST_THRESHOLD  = 0.08   # below this: charge at maximum rate
DEFAULT_EXPORT_THRESHOLD = 0.65   # above this: discharge to grid


class DRAction(Enum):
    NONE   = "none"
    SHED   = "shed"      # reduce consumption
    SHIFT  = "shift"     # defer to later hour
    BOOST  = "boost"     # charge at maximum rate
    EXPORT = "export"    # discharge to grid


@dataclass
class DRSignal:
    action:     DRAction
    reason:     str
    epex_kwh:   float
    priority:   int       # 1=low, 5=critical
    expires_at: float     # monotonic timestamp
    shed_w:     float = 0.0    # power to reduce (W)
    boost_w:    float = 0.0    # extra charge power (W)


class DemandResponseManager:
    """Processes demand response signals and provides action instructions."""

    def __init__(self, config: dict) -> None:
        self._config           = config
        self._enabled          = False
        self._shed_threshold   = DEFAULT_SHED_THRESHOLD
        self._boost_threshold  = DEFAULT_BOOST_THRESHOLD
        self._export_threshold = DEFAULT_EXPORT_THRESHOLD
        self._current_signal: Optional[DRSignal] = None
        self._action_count    = 0
        self._last_action_ts  = 0.0
        self.update_config(config)

    def update_config(self, config: dict) -> None:
        self._config           = config
        self._enabled          = config.get("dr_enabled", False)
        self._shed_threshold   = float(config.get("dr_epex_shed_eur",   DEFAULT_SHED_THRESHOLD))
        self._boost_threshold  = float(config.get("dr_epex_boost_eur",  DEFAULT_BOOST_THRESHOLD))
        self._export_threshold = float(config.get("dr_epex_export_eur", DEFAULT_EXPORT_THRESHOLD))

    def evaluate(
        self,
        epex_all_in_eur_kwh:  float,
        soc_pct:              float,
        battery_capacity_kwh: float,
        solar_surplus_w:      float,
        ned_surplus:          bool = False,
    ) -> DRSignal:
        """
        Evaluate the current situation and return a DR signal.

        Priorities:
          5 (critical) — EXPORT at extreme price + battery charged
          4 (high)     — SHED at high price
          3 (normal)   — SHIFT at moderate price
          2 (low)      — BOOST at negative/low price + NED surplus
          1 (idle)     — NONE
        """
        if not self._enabled:
            return DRSignal(DRAction.NONE, "DR disabled", epex_all_in_eur_kwh, 1,
                            time.monotonic() + 600)

        now = time.monotonic()

        # EXPORT: high price + battery > 30% → discharging is profitable
        if (epex_all_in_eur_kwh >= self._export_threshold
                and soc_pct >= 30
                and battery_capacity_kwh > 0):
            return DRSignal(
                action    = DRAction.EXPORT,
                reason    = (f"EPEX €{epex_all_in_eur_kwh:.3f}/kWh ≥ threshold "
                             f"€{self._export_threshold:.2f} — discharge to grid"),
                epex_kwh  = epex_all_in_eur_kwh,
                priority  = 5,
                expires_at = now + 3600,
                shed_w    = 0,
                boost_w   = 0,
            )

        # SHED: high price → defer flexible consumption
        if epex_all_in_eur_kwh >= self._shed_threshold:
            return DRSignal(
                action    = DRAction.SHED,
                reason    = (f"EPEX €{epex_all_in_eur_kwh:.3f}/kWh ≥ "
                             f"€{self._shed_threshold:.2f} — defer boiler/EV charging"),
                epex_kwh  = epex_all_in_eur_kwh,
                priority  = 4,
                expires_at = now + 3600,
                shed_w    = 2000,   # defer up to 2kW of flexible consumption
                boost_w   = 0,
            )

        # BOOST: low price or NED surplus → charge at maximum rate
        if epex_all_in_eur_kwh <= self._boost_threshold or ned_surplus:
            reason_parts = []
            if epex_all_in_eur_kwh <= self._boost_threshold:
                reason_parts.append(f"EPEX €{epex_all_in_eur_kwh:.3f}/kWh ≤ €{self._boost_threshold:.2f}")
            if ned_surplus:
                reason_parts.append("national solar/wind surplus")
            return DRSignal(
                action    = DRAction.BOOST,
                reason    = " + ".join(reason_parts) + " — charge at maximum rate",
                epex_kwh  = epex_all_in_eur_kwh,
                priority  = 2,
                expires_at = now + 1800,
                shed_w    = 0,
                boost_w   = battery_capacity_kwh * 200,   # ~C/5 charge rate in W
            )

        return DRSignal(DRAction.NONE, "Normal operation", epex_all_in_eur_kwh, 1,
                        now + 600)

    def apply(self, signal: DRSignal) -> None:
        """Register an active DR signal."""
        if signal.action != DRAction.NONE:
            if (not self._current_signal or
                    self._current_signal.action != signal.action):
                _LOGGER.info(
                    "DemandResponse: %s (priority %d) — %s",
                    signal.action.value, signal.priority, signal.reason,
                )
                self._action_count   += 1
                self._last_action_ts  = time.monotonic()
        self._current_signal = signal

    @property
    def current_action(self) -> DRAction:
        if not self._current_signal:
            return DRAction.NONE
        if time.monotonic() > self._current_signal.expires_at:
            return DRAction.NONE
        return self._current_signal.action

    @property
    def should_shed(self) -> bool:
        return self.current_action in (DRAction.SHED, DRAction.EXPORT)

    @property
    def should_boost_charge(self) -> bool:
        return self.current_action == DRAction.BOOST

    @property
    def should_export(self) -> bool:
        return self.current_action == DRAction.EXPORT

    def get_data(self) -> dict:
        sig = self._current_signal
        return {
            "enabled":        self._enabled,
            "action":         self.current_action.value,
            "reason":         sig.reason if sig else "",
            "priority":       sig.priority if sig else 0,
            "shed_w":         sig.shed_w if sig else 0,
            "boost_w":        sig.boost_w if sig else 0,
            "action_count":   self._action_count,
            "shed_threshold":  self._shed_threshold,
            "boost_threshold": self._boost_threshold,
        }
