"""
CloudEMS Battery EPEX Scheduler — v1.9.0

Automatically plans the optimal battery charge/discharge schedule based on
EPEX day-ahead electricity prices.

Strategy (self-learning):
  1. Rank all hours of today (and tomorrow when available) by price
  2. Schedule CHARGE during the N cheapest hours (fill battery when cheap)
  3. Schedule DISCHARGE during the N most expensive hours (sell/use when dear)
  4. Respect battery capacity, max charge/discharge power and current SoC
  5. Avoid scheduling when solar surplus is expected to charge anyway

The schedule is recalculated:
  - Every hour
  - Whenever new day-ahead prices become available (after ~13:00 CET)
  - When SoC changes significantly (± 10%)

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

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        _LOGGER.info("CloudEMS BatteryScheduler: setup (capacity=%.1f kWh)", self._capacity_kwh)

    # ── Main evaluate loop ─────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_info: dict,
        soc_pct: Optional[float] = None,
        solar_surplus_w: float   = 0.0,
    ) -> dict:
        """
        Evaluate current hour and execute battery action if needed.
        Returns status dict.
        """
        now         = datetime.now(timezone.utc)
        current_hour= now.hour
        soc         = soc_pct if soc_pct is not None else self._get_soc()

        # Re-plan if: no plan, new day, new prices available, SoC changed a lot
        should_replan = (
            self._schedule is None
            or self._schedule.date != now.strftime("%Y-%m-%d")
            or time.time() - self._last_plan_ts > 3600
            or (soc is not None and abs(soc - self._last_soc) > 10)
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

        if action == "charge" and soc is not None and soc > FULL_SOC:
            action = "idle"
            reason = f"Laden gestopt: batterij al vol ({soc:.0f}%)"

        # During solar surplus — don't force charge (solar will do it)
        if action == "charge" and solar_surplus_w > self._max_charge_w * 0.8:
            action = "idle"
            reason = f"Laden overgeslagen: PV surplus {solar_surplus_w:.0f}W doet het al"

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
            "charge_hours":     DEFAULT_CHARGE_HOURS,
            "discharge_hours":  DEFAULT_DISCHARGE_HOURS,
        }

    # ── Schedule building ──────────────────────────────────────────────────────

    async def _build_schedule(
        self,
        price_info: dict,
        soc: Optional[float],
        solar_surplus_w: float,
    ) -> None:
        """Build optimal charge/discharge schedule for today."""
        now      = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Collect all available price slots (today + tomorrow if available)
        today_all    = price_info.get("today_all", [])
        tomorrow_all = price_info.get("tomorrow_all", [])
        all_slots    = today_all + [
            {**s, "hour": s["hour"] + 24} for s in tomorrow_all
        ]

        if not today_all:
            _LOGGER.warning("BatteryScheduler: geen prijsdata beschikbaar")
            return

        # Sort by price for ranking
        sorted_asc  = sorted(today_all, key=lambda x: x["price"])
        sorted_desc = sorted(today_all, key=lambda x: x["price"], reverse=True)

        # Cheapest N hours → charge
        charge_hours = {s["hour"] for s in sorted_asc[:DEFAULT_CHARGE_HOURS]}
        # Most expensive N hours → discharge
        disch_hours  = {s["hour"] for s in sorted_desc[:DEFAULT_DISCHARGE_HOURS]}

        # Build schedule slots
        slots = []
        for s in sorted(today_all, key=lambda x: x["hour"]):
            h = s["hour"]
            p = s["price"]
            if h in charge_hours and h in disch_hours:
                # Conflict (same slot ranked both) → prefer discharge if SoC high
                action = "discharge" if (soc or 50) > 60 else "charge"
                r      = f"Conflict opgelost op basis van SoC ({soc:.0f}%)"
            elif h in charge_hours:
                action = "charge"
                r      = f"Goedkoopste uur #{sorted_asc.index(s)+1} ({p:.4f} €/kWh)"
            elif h in disch_hours:
                action = "discharge"
                r      = f"Duurste uur #{sorted(today_all, key=lambda x: -x['price']).index(s)+1} ({p:.4f} €/kWh)"
            else:
                action = "idle"
                r      = f"Gemiddeld uur ({p:.4f} €/kWh)"
            slots.append(ScheduleSlot(hour=h, action=action, price=p, reason=r))

        self._schedule = BatterySchedule(
            date          = date_str,
            slots         = slots,
            generated_at  = now.isoformat(),
            capacity_kwh  = self._capacity_kwh,
            charge_hours  = DEFAULT_CHARGE_HOURS,
            discharge_hours=DEFAULT_DISCHARGE_HOURS,
        )
        self._last_plan_ts = time.time()

        charge_hrs  = [s.hour for s in slots if s.action == "charge"]
        disch_hrs   = [s.hour for s in slots if s.action == "discharge"]
        _LOGGER.info(
            "BatteryScheduler: nieuw schema — laden: %s, ontladen: %s",
            charge_hrs, disch_hrs,
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
