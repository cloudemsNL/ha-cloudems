# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS NILM Other Bucket Tracker — v1.0.0

Berekent continu de "Other" (onbekend) energiebucket:

  Other_W = Grid_Import_W
            − Σ(bevestigde NILM-apparaten die AAN zijn)
            − Σ(SmartPowerEstimator HIGH-confidence entiteiten)
            − Standby_baseline_W

Dit getal toont hoeveel verbruik nog NIET door CloudEMS wordt verklaard.
Hoog getal = goede reden om smart plugs te plaatsen of meer te leren.

Geïnspireerd door Sense's "Other" bubble — maar beter omdat CloudEMS
ook HA-entiteiten kent als extra ankerpunten.

Sensor: sensor.cloudems_onbekend_verbruik_w
Attribuut breakdown toont de afzonderlijke aftrekposten.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Minimum grid import voordat "other" berekend wordt (vermijdt ruis bij 0W)
MIN_GRID_W = 10.0
# EMA alpha voor de other-W output (dempt ruis)
OTHER_EMA_ALPHA = 0.20
# Geschiedenis voor trend-analyse
HISTORY_SIZE = 120   # ~2 minuten bij 1s updates


@dataclass
class OtherBucketState:
    """Actuele decompostie van het totale huisverbruik."""
    grid_import_w:      float = 0.0   # bruto grid import
    nilm_known_w:       float = 0.0   # bevestigde NILM-apparaten
    estimator_known_w:  float = 0.0   # HIGH-conf SmartPowerEstimator totaal
    powercalc_w:        float = 0.0   # deel via PowerCalc-profielen
    learned_w:          float = 0.0   # deel via eigen leerproces
    standby_w:          float = 0.0   # baseline standby
    other_w:            float = 0.0   # onverklaard verbruik (EMA)
    other_raw_w:        float = 0.0   # onverklaard verbruik (rauw)
    coverage_pct:       float = 0.0   # percentage dat verklaard is
    timestamp:          float = 0.0


class NilmOtherTracker:
    """
    Bijhouder van de "Other" energiebucket.

    Gebruik:
        tracker = NilmOtherTracker()
        state = tracker.update(
            grid_import_w   = 3200.0,
            nilm_devices    = coordinator.data["nilm_devices"],
            estimator       = coordinator._power_estimator,
            standby_w       = coordinator._home_baseline.get_standby_w(),
        )
    """

    def __init__(self) -> None:
        self._state = OtherBucketState()
        self._history: List[float] = []     # ring-buffer van raw other_w
        self._ema_w: float = 0.0

    def update(
        self,
        grid_import_w:   float,
        nilm_devices:    List[dict],
        estimator        = None,    # SmartPowerEstimator | None
        standby_w:       float = 0.0,
    ) -> OtherBucketState:
        """Herbereken de bucket op basis van actuele data."""
        now = time.time()

        # 1. Vertrouwde NILM apparaten die AAN zijn
        # Caller geeft nilm_devices_trusted door — geen extra confirmed-filter nodig,
        # die selectie is al gedaan door het geïntegreerde vertrouwensmodel.
        nilm_on_w = sum(
            float(d.get("current_power") or d.get("power_w") or 0)
            for d in nilm_devices
            if d.get("is_on")
            and float(d.get("current_power") or d.get("power_w") or 0) > 1.0
        )

        # 2. SmartPowerEstimator — splits PowerCalc vs geleerde entiteiten
        estimator_w   = 0.0   # alle HIGH-confidence (totaal voor aftrek)
        powercalc_w   = 0.0   # alleen entiteiten met PowerCalc-profiel
        learned_w     = 0.0   # alleen via eigen leerproces herkend
        if estimator is not None:
            try:
                for s in estimator.get_all_states():
                    if s.get("confidence") == "high" and s.get("estimated_w", 0) > 1.0:
                        ew = float(s["estimated_w"])
                        estimator_w += ew
                        src = s.get("source", "")
                        if "powercalc" in src:
                            powercalc_w += ew
                        else:
                            learned_w += ew
            except Exception:
                pass

        # 3. Bereken raw other
        raw = grid_import_w - nilm_on_w - estimator_w - standby_w
        raw = max(0.0, round(raw, 1))

        # 4. EMA smoothing
        if self._ema_w == 0.0:
            self._ema_w = raw
        else:
            self._ema_w = round(self._ema_w * (1 - OTHER_EMA_ALPHA) + raw * OTHER_EMA_ALPHA, 1)

        # 5. Coverage percentage
        total = grid_import_w if grid_import_w > MIN_GRID_W else 1.0
        explained = nilm_on_w + estimator_w + standby_w
        coverage = round(min(100.0, explained / total * 100), 1)

        # 6. Historiek bijhouden
        self._history.append(raw)
        if len(self._history) > HISTORY_SIZE:
            self._history.pop(0)

        self._state = OtherBucketState(
            grid_import_w      = round(grid_import_w, 1),
            nilm_known_w       = round(nilm_on_w, 1),
            estimator_known_w  = round(estimator_w, 1),
            powercalc_w        = round(powercalc_w, 1),
            learned_w          = round(learned_w, 1),
            standby_w          = round(standby_w, 1),
            other_w            = self._ema_w,
            other_raw_w        = raw,
            coverage_pct       = coverage,
            timestamp          = now,
        )
        return self._state

    def get_state(self) -> OtherBucketState:
        return self._state

    def get_trend(self) -> str:
        """Geeft "stijgend", "dalend" of "stabiel" op basis van recente history."""
        if len(self._history) < 20:
            return "onbekend"
        recent = self._history[-10:]
        older  = self._history[-20:-10]
        avg_r  = sum(recent) / len(recent)
        avg_o  = sum(older)  / len(older)
        diff   = avg_r - avg_o
        if diff > 100:   return "stijgend"
        if diff < -100:  return "dalend"
        return "stabiel"

    def to_sensor_dict(self) -> dict:
        s = self._state
        return {
            "other_w":          s.other_w,
            "coverage_pct":     s.coverage_pct,
            "trend":            self.get_trend(),
            "breakdown": {
                "grid_import_w":     s.grid_import_w,
                "nilm_known_w":      s.nilm_known_w,
                "powercalc_w":       s.powercalc_w,
                "learned_w":         s.learned_w,
                "estimator_known_w": s.estimator_known_w,
                "standby_w":         s.standby_w,
                "other_w":           s.other_w,
            },
        }
