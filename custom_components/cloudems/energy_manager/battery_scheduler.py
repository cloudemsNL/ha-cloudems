# -*- coding: utf-8 -*-
"""
CloudEMS Battery EPEX Scheduler — v1.20.0

Automatically plans the optimal battery charge/discharge schedule based on
EPEX day-ahead electricity prices.

Strategy (self-learning):
  1. Rank all hours of today (and tomorrow when available) by price
  2. Schedule CHARGE during the N cheapest hours (fill battery when cheap)
  3. Schedule DISCHARGE during the N most expensive hours (sell/use when dear)
  4. Respect battery capacity, max charge/discharge power and current SoC
  5. Avoid scheduling when solar surplus is expected to charge anyway

v1.20: Seasonal strategy integration
  - SeasonalParameters from seasonal_strategy.py now drive charge_hours,
    discharge_hours, discharge_window and skip_pv_hours
  - Summer: fewer charge hours (PV charges battery), more discharge hours,
    evening discharge window; net-charging skipped when PV forecast is high
  - Winter: more charge hours, earlier discharge window
  - Transition: balanced defaults

The schedule is recalculated:
  - Every hour
  - Whenever new day-ahead prices become available (after ~13:00 CET)
  - When SoC changes significantly (± 10%)
  - When the season changes

Self-learning:
  - Tracks how often the battery actually charges/discharges during planned hours
  - If solar always charges the battery during "cheap" hours, shifts focus to
    peak discharge (evening expensive hours)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .seasonal_strategy import (
    SeasonalParameters, build_seasonal_parameters,
    SEASON_TRANSITION, SEASON_SUMMER, SEASON_WINTER,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_battery_schedule_v1"
STORAGE_VERSION = 1

# Default charge hours: 3 cheapest hours per day
DEFAULT_CHARGE_HOURS   = 3
DEFAULT_DISCHARGE_HOURS = 3

# Minimum SoC before scheduling discharge (don't discharge too low)
MIN_SOC_DISCHARGE = 20.0   # %
# SoC considered "full" — skip charging if above this
FULL_SOC          = 90.0   # %


@dataclass
class ScheduleSlot:
    """One hour in the battery schedule."""
    hour:       int            # 0–23
    action:     str            # "charge" | "discharge" | "idle"
    price:      float          # EUR/kWh
    reason:     str            = ""
    executed:   bool           = False   # did the battery actually do this?
    soc_start:  Optional[float]= None


@dataclass
class BatterySchedule:
    """Full daily schedule."""
    date:       str            # YYYY-MM-DD
    slots:      list           = field(default_factory=list)   # List[ScheduleSlot]
    generated_at: str          = ""
    capacity_kwh: float        = 10.0
    charge_hours: int          = DEFAULT_CHARGE_HOURS
    discharge_hours: int       = DEFAULT_DISCHARGE_HOURS


class BatteryEPEXScheduler:
    """
    Plans and executes battery charge/discharge based on EPEX prices.

    Usage in coordinator:
        sched = BatteryEPEXScheduler(hass, config)
        await sched.async_setup()
        # Every 10s:
        action = await sched.async_evaluate(price_info, soc_pct, solar_surplus_w)
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._store   = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._schedule: Optional[BatterySchedule] = None
        self._last_plan_ts: float = 0.0
        self._last_soc: float     = -1.0

        self._capacity_kwh = float(config.get("battery_capacity_kwh", 10.0))
        self._max_charge_w = float(config.get("battery_max_charge_w", 3000.0))
        self._max_disch_w  = float(config.get("battery_max_discharge_w", 3000.0))
        self._charge_eid   = config.get("battery_charge_entity", "")
        self._discharge_eid= config.get("battery_discharge_entity", "")
        self._soc_eid      = config.get("battery_soc_entity", "")

        # Learning: track plan accuracy
        self._plan_hits = 0
        self._plan_total = 0

        # v1.20: seasonal strategy
        self._seasonal_params: Optional[SeasonalParameters] = None
        self._last_season: str = ""

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        self._plan_hits  = int(saved.get("plan_hits", 0))
        self._plan_total = int(saved.get("plan_total", 0))
        _LOGGER.info("CloudEMS BatteryScheduler: setup (capacity=%.1f kWh)", self._capacity_kwh)

    async def async_maybe_save(self) -> None:
        """Persist learning counters — called from coordinator on shutdown."""
        await self._store.async_save({
            "plan_hits":  self._plan_hits,
            "plan_total": self._plan_total,
        })

    # ── Main evaluate loop ─────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_info: dict,
        soc_pct: Optional[float] = None,
        solar_surplus_w: float   = 0.0,
        soh_pct: Optional[float] = None,
        pv_forecast_hourly: list = None,
        seasonal_params: Optional[SeasonalParameters] = None,
    ) -> dict:
        """
        Evaluate current hour and execute battery action if needed.
        Returns status dict.

        v1.18.1: soh_pct — als SoH < 80% wordt het laadplafond automatisch
        verlaagd naar 80% SoC om verdere slijtage te beperken.
        pv_forecast_hourly — als PV-forecast beschikbaar is, worden uren
        met hoge PV-verwachting niet ingepland voor netwerk-laden.

        v1.20: seasonal_params — SeasonalParameters from seasonal_strategy.py.
        When provided, overrides charge_hours, discharge_hours and the list of
        PV-skip hours used during schedule building.
        """
        now         = datetime.now(timezone.utc)
        current_hour= now.hour
        soc         = soc_pct if soc_pct is not None else self._get_soc()

        # Store seasonal params for use in _build_schedule
        if seasonal_params is not None:
            season_changed = (seasonal_params.season != self._last_season)
            self._seasonal_params = seasonal_params
            self._last_season     = seasonal_params.season
        else:
            season_changed = False

        # Re-plan if: no plan, new day, new prices available, SoC changed a lot,
        # or season changed
        should_replan = (
            self._schedule is None
            or self._schedule.date != now.strftime("%Y-%m-%d")
            or time.time() - self._last_plan_ts > 3600
            or (soc is not None and abs(soc - self._last_soc) > 10)
            or season_changed
        )
        if should_replan:
            await self._build_schedule(price_info, soc, solar_surplus_w)

        # Find current hour action
        current_slot = self._get_slot(current_hour)
        action       = "idle"
        reason       = "geen gepland actie dit uur"

        if current_slot:
            action = current_slot.action
            reason = current_slot.reason

        # Safety guards
        if action == "discharge" and soc is not None and soc < MIN_SOC_DISCHARGE:
            action = "idle"
            reason = f"Ontladen gestopt: SoC {soc:.0f}% < minimum {MIN_SOC_DISCHARGE:.0f}%"

        # v1.18.1: slijtage-bewust laden — laadplafond verlagen bij lage SoH
        charge_ceiling = FULL_SOC
        if soh_pct is not None and soh_pct < 80.0:
            charge_ceiling = 80.0
            _LOGGER.debug(
                "BatteryScheduler: SoH %.1f%% < 80%% → laadplafond verlaagd naar 80%% SoC",
                soh_pct,
            )
        elif soh_pct is not None and soh_pct < 90.0:
            charge_ceiling = 85.0

        if action == "charge" and soc is not None and soc > charge_ceiling:
            action = "idle"
            reason = f"Laden gestopt: SoC {soc:.0f}% boven plafond {charge_ceiling:.0f}% (SoH-bewust)" 

        # During solar surplus — don't force charge (solar will do it)
        if action == "charge" and solar_surplus_w > self._max_charge_w * 0.8:
            action = "idle"
            reason = f"Laden overgeslagen: PV surplus {solar_surplus_w:.0f}W doet het al"

        # v1.18.1: skip net-laden als PV-forecast dit uur hoog is
        if action == "charge" and pv_forecast_hourly:
            now_h = datetime.now(timezone.utc).hour
            hour_fc = next((h for h in pv_forecast_hourly if h.get("hour") == now_h), None)
            if hour_fc:
                total_inv = len(set(h.get("inverter_id") for h in pv_forecast_hourly))
                # sum forecast for this hour across all inverters
                total_fc_w = sum(
                    h.get("forecast_w", 0) for h in pv_forecast_hourly if h.get("hour") == now_h
                )
                if total_fc_w > self._max_charge_w * 0.6:
                    action = "idle"
                    reason = f"Laden overgeslagen: PV-prognose {total_fc_w:.0f}W dit uur laadt batterij zelf" 

        # Execute
        await self._execute_action(action)
        if soc is not None:
            self._last_soc = soc

        return {
            "action":           action,
            "reason":           reason,
            "current_hour":     current_hour,
            "soc_pct":          soc,
            "schedule_date":    self._schedule.date if self._schedule else None,
            "schedule":         self._get_schedule_list(),
            "plan_accuracy_pct":round(self._plan_hits/self._plan_total*100, 1)
                                if self._plan_total > 0 else None,
            "charge_hours":     self._seasonal_params.charge_hours if self._seasonal_params else DEFAULT_CHARGE_HOURS,
            "discharge_hours":  self._seasonal_params.discharge_hours if self._seasonal_params else DEFAULT_DISCHARGE_HOURS,
            # v1.20 seasonal
            "season":           self._seasonal_params.season if self._seasonal_params else SEASON_TRANSITION,
            "season_reason":    self._seasonal_params.reason if self._seasonal_params else "",
            "season_auto":      self._seasonal_params.auto_detected if self._seasonal_params else True,
            "discharge_window": list(self._seasonal_params.discharge_window) if self._seasonal_params else [17, 21],
        }

    # ── Schedule building ──────────────────────────────────────────────────────

    async def _build_schedule(
        self,
        price_info: dict,
        soc: Optional[float],
        solar_surplus_w: float,
    ) -> None:
        """Build optimal charge/discharge schedule for today.

        v1.20: Uses SeasonalParameters when available:
          - charge_hours from seasonal strategy
          - discharge_hours from seasonal strategy
          - discharge_window: prefer evening hours in that window for discharge
          - skip_pv_hours: exclude from charge scheduling (PV will charge)
        """
        now      = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        sp = self._seasonal_params  # may be None (first run before coordinator sets it)
        charge_hours_n   = sp.charge_hours   if sp else DEFAULT_CHARGE_HOURS
        discharge_hours_n= sp.discharge_hours if sp else DEFAULT_DISCHARGE_HOURS
        disch_window     = sp.discharge_window if sp else (17, 21)
        skip_pv_hours    = set(sp.skip_pv_hours) if sp else set()

        # Collect all available price slots (today + tomorrow if available)
        today_all    = price_info.get("today_all", [])
        tomorrow_all = price_info.get("tomorrow_all", [])

        if not today_all:
            _LOGGER.warning("BatteryScheduler: geen prijsdata beschikbaar")
            return

        # Sort by price for ranking
        sorted_asc  = sorted(today_all, key=lambda x: x["price"])
        sorted_desc = sorted(today_all, key=lambda x: x["price"], reverse=True)

        # ── Charge hours: cheapest N, but skip hours where PV covers charging ──
        # v2.1.7: skip charge planning volledig als batterij al vol (of bijna vol) is
        charge_ceiling_plan = FULL_SOC
        if soc is not None and soc >= charge_ceiling_plan:
            charge_hour_set = set()
            _LOGGER.debug(
                "BatteryScheduler: SoC %.0f%% >= %.0f%% — geen laaduren ingepland",
                soc, charge_ceiling_plan,
            )
        else:
            charge_candidates = [s for s in sorted_asc if s["hour"] not in skip_pv_hours]
            # If PV skips removed too many, fall back to include them to still charge
            if len(charge_candidates) < charge_hours_n:
                charge_candidates = sorted_asc
            charge_hour_set = {s["hour"] for s in charge_candidates[:charge_hours_n]}

        # ── Discharge hours: most expensive N, prefer discharge_window ─────────
        # First try to pick from the preferred evening window
        in_window   = [s for s in sorted_desc
                       if disch_window[0] <= s["hour"] <= disch_window[1]]
        out_window  = [s for s in sorted_desc
                       if not (disch_window[0] <= s["hour"] <= disch_window[1])]
        # Take as many from window as available, fill remainder from outside
        disch_from_window = in_window[:discharge_hours_n]
        remaining = discharge_hours_n - len(disch_from_window)
        disch_extra = out_window[:remaining] if remaining > 0 else []
        disch_hour_set = {s["hour"] for s in disch_from_window + disch_extra}

        # ── Build schedule slots ──────────────────────────────────────────────
        slots = []
        for s in sorted(today_all, key=lambda x: x["hour"]):
            h = s["hour"]
            p = s["price"]
            if h in charge_hour_set and h in disch_hour_set:
                action = "discharge" if (soc or 50) > 60 else "charge"
                r      = f"Conflict opgelost op basis van SoC ({soc:.0f}%)"
            elif h in charge_hour_set:
                pv_note = " (PV skip overruled)" if h in skip_pv_hours else ""
                action = "charge"
                r = f"Laaduur (seizoen: {sp.season if sp else 'transition'}{pv_note}, {p:.4f} €/kWh)"
            elif h in disch_hour_set:
                win_note = " (voorkeur venster)" if disch_window[0] <= h <= disch_window[1] else ""
                action = "discharge"
                r = f"Ontlaaduur{win_note} ({p:.4f} €/kWh)"
            else:
                action = "idle"
                r      = f"Gemiddeld uur ({p:.4f} €/kWh)"
            slots.append(ScheduleSlot(hour=h, action=action, price=p, reason=r))

        season_label = sp.season if sp else "transition"
        self._schedule = BatterySchedule(
            date           = date_str,
            slots          = slots,
            generated_at   = now.isoformat(),
            capacity_kwh   = self._capacity_kwh,
            charge_hours   = charge_hours_n,
            discharge_hours= discharge_hours_n,
        )
        self._last_plan_ts = time.time()

        charge_hrs = [s.hour for s in slots if s.action == "charge"]
        disch_hrs  = [s.hour for s in slots if s.action == "discharge"]
        _LOGGER.info(
            "BatteryScheduler [%s]: nieuw schema — laden: %s, ontladen: %s (venster %02d-%02d)",
            season_label, charge_hrs, disch_hrs, disch_window[0], disch_window[1],
        )

    # ── Execution ──────────────────────────────────────────────────────────────

    async def _execute_action(self, action: str) -> None:
        """Send charge/discharge command to battery entities."""
        if action == "charge" and self._charge_eid:
            await self._call_service(self._charge_eid, self._max_charge_w)
        elif action == "discharge" and self._discharge_eid:
            await self._call_service(self._discharge_eid, self._max_disch_w)
        elif action == "idle":
            # Set both to 0 (idle)
            if self._charge_eid:
                await self._call_service(self._charge_eid, 0.0)
            if self._discharge_eid:
                await self._call_service(self._discharge_eid, 0.0)

    async def _call_service(self, entity_id: str, value: float) -> None:
        domain = entity_id.split(".")[0]
        try:
            if domain == "number":
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": value},
                    blocking=False,
                )
            elif domain == "switch":
                svc = "turn_on" if value > 0 else "turn_off"
                await self._hass.services.async_call(
                    "switch", svc, {"entity_id": entity_id}, blocking=False,
                )
        except Exception as err:
            _LOGGER.warning("BatteryScheduler service call failed: %s", err)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_soc(self) -> Optional[float]:
        if not self._soc_eid:
            return None
        state = self._hass.states.get(self._soc_eid)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None

    def _get_slot(self, hour: int) -> Optional[ScheduleSlot]:
        if not self._schedule:
            return None
        return next((s for s in self._schedule.slots if s.hour == hour), None)

    def _get_schedule_list(self) -> list:
        if not self._schedule:
            return []
        return [
            {
                "hour":   s.hour,
                "action": s.action,
                "price":  s.price,
                "reason": s.reason,
            }
            for s in self._schedule.slots
        ]
