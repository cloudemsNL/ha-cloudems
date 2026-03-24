# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — FCR/aFRR Virtual Power Plant Foundation v1.0.0

Foundation for participating in ancillary services markets:
  - FCR  (Frequency Containment Reserve) — automatic, within 30s
  - aFRR (automatic Frequency Restoration Reserve) — within 5 min
  - mFRR (manual FRR) — within 15 min

Currently implements:
  1. Local frequency monitoring and response readiness check
  2. Battery capacity availability reporting
  3. Eligibility assessment (battery size, inverter response time)
  4. Simulated revenue estimation

Full market participation requires:
  - Aggregator contract (e.g. Vandebron, Sympower, Enersis)
  - Certified bidirectional inverter
  - API connection to TSO (TenneT NL) or aggregator

This module provides the local intelligence foundation.
The actual market bidding happens via the aggregator's cloud API
which will be integrated in a future version via AdaptiveHome.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# FCR requirements (TenneT NL, 2024)
FCR_MIN_CAPACITY_KW     = 1.0    # minimum 1 kW symmetric capacity
FCR_RESPONSE_TIME_S     = 30     # must respond within 30 seconds
FCR_HOLDING_TIME_H      = 0.5    # hold for 30 min minimum
FCR_DEADBAND_HZ         = 0.01   # ±10 mHz deadband

# aFRR requirements
AFRR_MIN_CAPACITY_KW    = 1.0
AFRR_RESPONSE_TIME_S    = 300    # 5 minutes
AFRR_ACTIVATION_PROB    = 0.15   # typical activation ~15% of contracted hours

# Revenue estimates (EUR/MW/h — market averages 2024)
FCR_REVENUE_EUR_MW_H    = 12.0   # €12/MW/h for FCR capacity
AFRR_REVENUE_EUR_MW_H   = 8.0    # €8/MW/h for aFRR capacity


@dataclass
class FCRReadiness:
    """Assessment of readiness to participate in FCR/aFRR."""
    eligible_fcr:       bool  = False
    eligible_afrr:      bool  = False
    eligible_mfrr:      bool  = False
    battery_kw:         float = 0.0   # available symmetric power
    battery_kwh:        float = 0.0   # available energy buffer
    soc_ok:             bool  = False  # SOC in valid FCR range (20-80%)
    freq_monitoring:    bool  = False  # frequency sensor available
    issues:             list  = field(default_factory=list)
    monthly_revenue_est: float = 0.0  # estimated monthly revenue (EUR)


@dataclass
class FCRStatus:
    readiness:          FCRReadiness
    current_freq:       Optional[float] = None
    freq_ok:            bool  = True
    activation_needed:  bool  = False   # True if freq deviation > deadband
    activation_direction: str = "none"  # "charge" | "discharge" | "none"
    contracted_kw:      float = 0.0     # kW under contract (0 = not contracted)


class FCRAFRRManager:
    """
    FCR/aFRR readiness assessment and local response manager.

    Does NOT connect to any market API. Provides the local intelligence
    layer that makes battery+inverter ready for aggregator integration.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._enabled = config.get("fcr_enabled", False)
        self._freq_entity = config.get("blackout_freq_entity", "")  # reuse
        self._last_freq: Optional[float] = None
        self._freq_history: list = []

    def assess_readiness(
        self,
        battery_soc_pct: Optional[float],
        battery_max_kw:  float,
        battery_kwh:     float,
    ) -> FCRReadiness:
        """Assess current FCR/aFRR eligibility."""
        issues = []
        soc_ok = False

        # SOC check: FCR requires 20-80% SOC for symmetric response
        if battery_soc_pct is not None:
            if 20 <= battery_soc_pct <= 80:
                soc_ok = True
            else:
                issues.append(f"SOC {battery_soc_pct:.0f}% buiten FCR bereik (20-80%)")
        else:
            issues.append("Batterij SOC niet beschikbaar")

        # Capacity check
        if battery_max_kw < FCR_MIN_CAPACITY_KW:
            issues.append(f"Vermogen {battery_max_kw:.1f} kW < minimum {FCR_MIN_CAPACITY_KW} kW")

        # Frequency monitoring
        freq_ok = bool(self._freq_entity and self._hass.states.get(self._freq_entity))
        if not freq_ok:
            issues.append("Geen frequentiesensor geconfigureerd (aanbevolen voor FCR)")

        eligible_fcr  = (battery_max_kw >= FCR_MIN_CAPACITY_KW and soc_ok and not issues)
        eligible_afrr = (battery_max_kw >= AFRR_MIN_CAPACITY_KW)
        eligible_mfrr = (battery_max_kw >= 0.5)

        # Revenue estimate
        contracted_kw = min(battery_max_kw, 5.0)  # conservative
        monthly_fcr   = contracted_kw / 1000 * FCR_REVENUE_EUR_MW_H * 24 * 30
        monthly_afrr  = contracted_kw / 1000 * AFRR_REVENUE_EUR_MW_H * 24 * 30 * AFRR_ACTIVATION_PROB
        monthly_est   = monthly_fcr + monthly_afrr if eligible_fcr else monthly_afrr

        return FCRReadiness(
            eligible_fcr        = eligible_fcr,
            eligible_afrr       = eligible_afrr,
            eligible_mfrr       = eligible_mfrr,
            battery_kw          = battery_max_kw,
            battery_kwh         = battery_kwh,
            soc_ok              = soc_ok,
            freq_monitoring     = freq_ok,
            issues              = issues,
            monthly_revenue_est = round(monthly_est, 2),
        )

    def tick(
        self,
        battery_soc_pct: Optional[float],
        battery_max_kw:  float = 5.0,
        battery_kwh:     float = 10.0,
    ) -> dict:
        """Main tick — assess readiness and check frequency."""
        readiness = self.assess_readiness(battery_soc_pct, battery_max_kw, battery_kwh)

        # Read current frequency
        current_freq = None
        activation_needed = False
        direction = "none"

        if self._freq_entity:
            s = self._hass.states.get(self._freq_entity)
            if s and s.state not in ("unavailable", "unknown"):
                try:
                    current_freq = float(s.state)
                    deviation = current_freq - 50.0
                    if abs(deviation) > FCR_DEADBAND_HZ and readiness.eligible_fcr:
                        activation_needed = True
                        direction = "charge" if deviation < 0 else "discharge"
                except (ValueError, TypeError):
                    pass

        return {
            "enabled":           self._enabled,
            "eligible_fcr":      readiness.eligible_fcr,
            "eligible_afrr":     readiness.eligible_afrr,
            "eligible_mfrr":     readiness.eligible_mfrr,
            "battery_kw":        readiness.battery_kw,
            "soc_ok":            readiness.soc_ok,
            "freq_monitoring":   readiness.freq_monitoring,
            "issues":            readiness.issues,
            "monthly_revenue_est": readiness.monthly_revenue_est,
            "current_freq":      current_freq,
            "activation_needed": activation_needed,
            "activation_direction": direction,
            "next_step":         (
                "Neem contact op met een aggregator (Vandebron, Sympower) voor contractering"
                if readiness.eligible_fcr else
                "Verbeter SOC-bereik en controleer issues voor FCR-deelname"
            ),
        }
