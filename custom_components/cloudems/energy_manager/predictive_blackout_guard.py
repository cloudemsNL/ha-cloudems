# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Predictive Blackout Guard v1.0.0

Detects early warning signs of grid instability and prepares the home:
  1. Monitors grid frequency (if available via P1 or ESPHome)
  2. Detects voltage dips and frequency deviations
  3. When risk is detected: charges battery to 100%, disables non-critical loads
  4. Sends urgent notification

Grid instability indicators:
  - Frequency deviations: normal = 50.0 Hz, deviation ±0.2 Hz = warning
  - Rapid voltage drops: >5V in <10s
  - Multiple short interruptions in sequence

Also monitors external signals:
  - HA sensor for grid status (e.g. from netbeheerder API)
  - P1 telegram power spikes (sudden >90% capacity usage)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Thresholds
FREQ_NOMINAL_HZ     = 50.0
FREQ_WARNING_HZ     = 0.15  # ±0.15 Hz = warning
FREQ_CRITICAL_HZ    = 0.30  # ±0.30 Hz = critical
VOLTAGE_DIP_V       = 8.0   # drop of 8V = warning
CAPACITY_WARNING    = 0.88  # 88% of max capacity = warning
HISTORY_SECONDS     = 300   # keep 5 min of history

# Cooldown after alert to prevent spam
ALERT_COOLDOWN_S    = 900   # 15 min


@dataclass
class GridSample:
    ts:       float
    freq_hz:  Optional[float]
    voltage:  Optional[float]  # L1 voltage
    power_w:  float


@dataclass
class BlackoutRiskStatus:
    risk_level:      str    # "none" | "low" | "medium" | "high" | "critical"
    risk_score:      float  # 0-100
    freq_hz:         Optional[float]
    freq_deviation:  float
    voltage_v:       Optional[float]
    power_pct:       float  # % of max capacity
    actions_taken:   list
    advice:          str
    battery_charge_requested: bool


class PredictiveBlackoutGuard:
    """
    Monitors grid stability and prepares the home when instability is detected.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("blackout_guard_enabled", True)
        self._history: deque = deque(maxlen=60)  # 60 × 10s = 10 min
        self._last_alert_ts   = 0.0
        self._last_risk_level = "none"
        self._charge_requested = False

        # Config
        self._freq_entity    = config.get("blackout_freq_entity", "")
        self._voltage_entity = config.get("blackout_voltage_entity", "")
        self._max_power_w    = float(config.get("max_power_w") or
                                     config.get("conf_max_current_l1", 25) * 230 * 3)

    def tick(
        self,
        grid_power_w: float,
        battery_soc:  Optional[float] = None,
    ) -> BlackoutRiskStatus:
        """Call every coordinator cycle."""
        if not self._enabled:
            return BlackoutRiskStatus(
                risk_level="none", risk_score=0, freq_hz=None,
                freq_deviation=0, voltage_v=None, power_pct=0,
                actions_taken=[], advice="Blackout guard uitgeschakeld",
                battery_charge_requested=False,
            )

        now = time.time()

        # Read sensors
        freq_hz = self._read_float(self._freq_entity)
        volt_v  = self._read_float(self._voltage_entity)

        # Store sample
        self._history.append(GridSample(
            ts=now, freq_hz=freq_hz, voltage=volt_v, power_w=grid_power_w
        ))

        # Calculate risk
        risk_score = 0.0
        freq_deviation = 0.0
        actions = []

        # Frequency analysis
        if freq_hz is not None:
            freq_deviation = abs(freq_hz - FREQ_NOMINAL_HZ)
            if freq_deviation >= FREQ_CRITICAL_HZ:
                risk_score += 50
            elif freq_deviation >= FREQ_WARNING_HZ:
                risk_score += 25

        # Voltage dip analysis (compare with recent history)
        if volt_v is not None and len(self._history) >= 3:
            recent_voltages = [s.voltage for s in list(self._history)[-6:]
                               if s.voltage is not None]
            if len(recent_voltages) >= 2:
                volt_drop = max(recent_voltages) - volt_v
                if volt_drop >= VOLTAGE_DIP_V:
                    risk_score += 30

        # Capacity usage
        power_pct = (grid_power_w / self._max_power_w * 100) if self._max_power_w > 0 else 0
        if power_pct >= CAPACITY_WARNING * 100:
            risk_score += 20

        # Frequency oscillation (many deviations in last minute)
        if len(self._history) >= 6:
            freq_samples = [s.freq_hz for s in self._history if s.freq_hz is not None]
            if len(freq_samples) >= 4:
                deviations = sum(1 for f in freq_samples if abs(f - FREQ_NOMINAL_HZ) > 0.1)
                if deviations >= 3:
                    risk_score += 15

        risk_score = min(100, risk_score)

        if risk_score < 15:   risk_level = "none"
        elif risk_score < 35: risk_level = "low"
        elif risk_score < 60: risk_level = "medium"
        elif risk_score < 80: risk_level = "high"
        else:                 risk_level = "critical"

        # Actions when risk is elevated
        charge_requested = False
        if risk_level in ("high", "critical") and now - self._last_alert_ts > ALERT_COOLDOWN_S:
            self._last_alert_ts = now
            charge_requested = True
            actions.append("battery_charge_100pct")

            # Send notification
            self._hass.async_create_task(self._send_alert(risk_level, risk_score, freq_hz))

            _LOGGER.warning(
                "BlackoutGuard: %s risk detected (score=%.0f, freq=%s Hz)",
                risk_level, risk_score, f"{freq_hz:.3f}" if freq_hz else "n/a"
            )

        self._charge_requested = charge_requested
        self._last_risk_level  = risk_level

        advice = self._build_advice(risk_level, risk_score, freq_deviation, power_pct)

        return BlackoutRiskStatus(
            risk_level      = risk_level,
            risk_score      = round(risk_score, 1),
            freq_hz         = round(freq_hz, 3) if freq_hz else None,
            freq_deviation  = round(freq_deviation, 3),
            voltage_v       = round(volt_v, 1) if volt_v else None,
            power_pct       = round(power_pct, 1),
            actions_taken   = actions,
            advice          = advice,
            battery_charge_requested = charge_requested,
        )

    def _build_advice(self, risk: str, score: float, freq_dev: float, power_pct: float) -> str:
        if risk == "none":
            return "Netspanning stabiel — geen acties vereist."
        if risk == "low":
            return f"Licht instabiel net (score {score:.0f}). Monitoring actief."
        if risk == "medium":
            return f"Matige netinstabiliteit. Frequentieafwijking {freq_dev:.3f} Hz. Extra monitoring."
        if risk == "high":
            return f"Hoog risico! Batterij wordt opgeladen naar 100%. Niet-kritische lasten vermijden."
        return f"KRITIEK: Ernstige netinstabiliteit! Noodmodus actief. Batterij laadt naar max."

    async def _send_alert(self, risk_level: str, score: float, freq: Optional[float]) -> None:
        msg = (
            f"⚡ CloudEMS Netinstabiliteit Alert\n\n"
            f"Risiconiveau: **{risk_level.upper()}** (score: {score:.0f}/100)\n"
        )
        if freq:
            msg += f"Netfrequentie: {freq:.3f} Hz (normaal: 50.000 Hz)\n"
        msg += "\nActies: batterij wordt opgeladen naar 100% ter voorbereiding op eventuele uitval."

        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":           "⚡ Netinstabiliteit gedetecteerd",
                    "message":         msg,
                    "notification_id": "cloudems_blackout_guard",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.warning("BlackoutGuard: notification failed: %s", e)

    def _read_float(self, entity_id: str) -> Optional[float]:
        if not entity_id:
            return None
        s = self._hass.states.get(entity_id)
        if not s or s.state in ("unavailable", "unknown"):
            return None
        try:
            return float(s.state)
        except (ValueError, TypeError):
            return None

    def get_status(self) -> dict:
        if not self._history:
            return {"enabled": self._enabled, "risk_level": "none", "risk_score": 0}
        last = list(self._history)[-1]
        return {
            "enabled":          self._enabled,
            "risk_level":       self._last_risk_level,
            "freq_entity":      self._freq_entity,
            "voltage_entity":   self._voltage_entity,
            "samples":          len(self._history),
            "last_power_w":     last.power_w,
        }
