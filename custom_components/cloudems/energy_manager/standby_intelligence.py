# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Standby Intelligence v1.0.0

Bundles home_baseline, device_drift, appliance_health and nilm_other_tracker
into one coherent inefficiency report with cost translation and ranked list.

Surfaces:
  - Always-on devices (on day and night, never off)
  - Standby creep (devices using more than their learned baseline)
  - Unaccounted power (nilm_other — power nobody can explain)
  - Total standby cost (€/month)
  - Ranked savings opportunities
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Thresholds
ALWAYS_ON_MIN_HOURS_DAY  = 20    # device on >= 20h/day = always-on candidate
ALWAYS_ON_MIN_DAYS       = 5     # must be true for >= 5 consecutive days
STANDBY_CREEP_THRESHOLD  = 0.25  # 25% above learned baseline = creep alert
HOURS_PER_MONTH          = 730.0


@dataclass
class StandbyDevice:
    """One device with standby/inefficiency data."""
    entity_id:      str
    name:           str
    category:       str           # "always_on" | "creep" | "unaccounted" | "ok"
    current_w:      float = 0.0
    baseline_w:     float = 0.0
    excess_w:       float = 0.0   # current - baseline
    cost_month_eur: float = 0.0
    hours_on_today: float = 0.0
    tip:            str   = ""


@dataclass
class StandbyReport:
    """Full inefficiency report."""
    total_standby_w:    float = 0.0
    total_cost_month:   float = 0.0
    unaccounted_w:      float = 0.0
    always_on_count:    int   = 0
    creep_count:        int   = 0
    devices:            list  = field(default_factory=list)
    top_savings:        list  = field(default_factory=list)   # top 5 by cost
    score:              int   = 100   # 0-100, higher = less waste
    advice:             str   = ""


class StandbyIntelligence:
    """
    Aggregates all inefficiency signals into one ranked report.
    Reads from coordinator data — no direct HA access needed.
    """

    def __init__(self, price_eur_kwh: float = 0.25) -> None:
        self._price = price_eur_kwh
        self._last_report: Optional[StandbyReport] = None

    def update_price(self, price_eur_kwh: float) -> None:
        self._price = max(0.05, price_eur_kwh)

    def analyse(
        self,
        nilm_devices:   list[dict],
        drift_data:     dict,
        baseline_w:     float,
        other_w:        float,
        home_power_w:   float,
    ) -> StandbyReport:
        """
        Build full standby report from coordinator data.

        Args:
            nilm_devices:  coordinator.data["nilm_devices"]
            drift_data:    coordinator.data["device_drift"]
            baseline_w:    coordinator.data["standby_w"] from home_baseline
            other_w:       coordinator.data["other_w"] from nilm_other_tracker
            home_power_w:  total house consumption right now
        """
        devices: list[StandbyDevice] = []
        price = self._price

        # ── 1. Always-on detection from NILM ──────────────────────────────────
        for dev in (nilm_devices or []):
            if not isinstance(dev, dict):
                continue
            name     = dev.get("label") or dev.get("name") or dev.get("entity_id", "?")
            eid      = dev.get("entity_id", "")
            power_w  = float(dev.get("power_w") or 0)
            on_pct   = float(dev.get("on_pct_7d") or dev.get("duty_cycle_pct") or 0)
            base_w   = float(dev.get("standby_w") or dev.get("baseline_w") or 0)

            if on_pct >= 90 and power_w > 5:
                # Likely always-on
                cost = power_w / 1000 * HOURS_PER_MONTH * price
                devices.append(StandbyDevice(
                    entity_id      = eid,
                    name           = name,
                    category       = "always_on",
                    current_w      = power_w,
                    baseline_w     = base_w,
                    excess_w       = power_w,
                    cost_month_eur = round(cost, 2),
                    hours_on_today = round(on_pct / 100 * 24, 1),
                    tip            = f"Staat {on_pct:.0f}% van de tijd aan. Overweeg een timer of schakelaar.",
                ))

        # ── 2. Standby creep from device_drift ────────────────────────────────
        drift_profiles = drift_data.get("profiles", []) if isinstance(drift_data, dict) else []
        for prof in drift_profiles:
            if not isinstance(prof, dict):
                continue
            if not prof.get("has_alert") and not prof.get("has_warning"):
                continue
            name    = prof.get("label") or prof.get("entity_id", "?")
            eid     = prof.get("entity_id", "")
            cur_w   = float(prof.get("current_w") or 0)
            base_w  = float(prof.get("baseline_w") or 0)
            excess  = max(0.0, cur_w - base_w)
            if excess < 5:
                continue
            cost = excess / 1000 * HOURS_PER_MONTH * price
            devices.append(StandbyDevice(
                entity_id      = eid,
                name           = name,
                category       = "creep",
                current_w      = cur_w,
                baseline_w     = base_w,
                excess_w       = round(excess, 1),
                cost_month_eur = round(cost, 2),
                tip            = f"Gebruikt {excess:.0f}W meer dan normaal. Controleer op defect of sluimerverbruik.",
            ))

        # ── 3. Unaccounted power ──────────────────────────────────────────────
        if other_w > 30:
            cost = other_w / 1000 * HOURS_PER_MONTH * price
            devices.append(StandbyDevice(
                entity_id      = "cloudems_unaccounted",
                name           = "Onverklaard verbruik",
                category       = "unaccounted",
                current_w      = round(other_w, 1),
                baseline_w     = 0,
                excess_w       = round(other_w, 1),
                cost_month_eur = round(cost, 2),
                tip            = "Vermogen dat NILM niet kan toewijzen. Mogelijk niet-gemeten apparaten.",
            ))

        # ── 4. Summary ────────────────────────────────────────────────────────
        always_on = [d for d in devices if d.category == "always_on"]
        creep     = [d for d in devices if d.category == "creep"]
        total_w   = sum(d.excess_w for d in devices)
        total_eur = sum(d.cost_month_eur for d in devices)

        top5 = sorted(devices, key=lambda d: d.cost_month_eur, reverse=True)[:5]

        # Score: 100 = perfect, subtract points per issue
        score = 100
        score -= min(40, len(always_on) * 8)
        score -= min(30, len(creep) * 5)
        score -= min(20, int(other_w / 50) * 5)
        score = max(0, score)

        if total_eur < 2:
            advice = "Uitstekend! Nauwelijks sluimerverbruik gedetecteerd."
        elif total_eur < 8:
            advice = f"Goed. €{total_eur:.0f}/maand aan sluimerverbruik — kleine verbeteringen mogelijk."
        elif total_eur < 20:
            advice = f"Let op: €{total_eur:.0f}/maand aan vermijdbaar verbruik. Bekijk de top-besparingen."
        else:
            advice = f"Actie vereist: €{total_eur:.0f}/maand aan sluimerverbruik. Dat is €{total_eur*12:.0f}/jaar."

        report = StandbyReport(
            total_standby_w  = round(total_w, 1),
            total_cost_month = round(total_eur, 2),
            unaccounted_w    = round(other_w, 1),
            always_on_count  = len(always_on),
            creep_count      = len(creep),
            devices          = [self._dev_to_dict(d) for d in devices],
            top_savings      = [self._dev_to_dict(d) for d in top5],
            score            = score,
            advice           = advice,
        )
        self._last_report = report
        return report

    def _dev_to_dict(self, d: StandbyDevice) -> dict:
        return {
            "entity_id":      d.entity_id,
            "name":           d.name,
            "category":       d.category,
            "current_w":      d.current_w,
            "baseline_w":     d.baseline_w,
            "excess_w":       d.excess_w,
            "cost_month_eur": d.cost_month_eur,
            "hours_on_today": d.hours_on_today,
            "tip":            d.tip,
        }

    def get_last(self) -> Optional[StandbyReport]:
        return self._last_report
