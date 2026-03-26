# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Slimme Zwembad Controller — v1.0.0

Beheert automatisch filtration en verwarming van een zwembad op basis van:

FILTRATION (filtreerpomp):
  1. PV-surplus modus  — pomp aan zodra PV-overschot > drempel
  2. EPEX goedkope uren — pomp draait tijdens goedkoopste uren
  3. Minimum dagelijkse filtertijd — bewaakt dat minimum uren gehaald wordt
  4. Temperatuur-afhankelijk — meer filtertijd bij hogere watertemperatuur

VERWARMING (warmtepomp):
  1. Temperatuurbewaking — pomp aan als watertemperatuur < setpoint
  2. PV-surplus prioriteit — warmtepomp krijgt voorrang bij PV-overschot
  3. EPEX goedkope uren — verwarming op goedkoopste momenten
  4. COP-optimalisatie — hoger COP bij hogere buitentemperatuur → sturing op beste moment

DAILY FILTER SCHEDULE:
  watertemperatuur ≤ 15°C  →  2 uur/dag minimum
  watertemperatuur 15–24°C →  4 uur/dag minimum
  watertemperatuur ≥ 24°C  →  6 uur/dag minimum
  (warm zwembad heeft meer filtratie nodig i.v.m. bacteriegroei)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# ── Filtration defaults ────────────────────────────────────────────────────────
MIN_FILTER_HOURS_COLD   = 2.0   # uur/dag bij watertemp ≤ 15°C
MIN_FILTER_HOURS_WARM   = 4.0   # uur/dag bij watertemp 15–24°C
MIN_FILTER_HOURS_HOT    = 6.0   # uur/dag bij watertemp ≥ 24°C
FILTER_PV_SURPLUS_W     = 200   # W — minimaal PV-surplus om pomp aan te zetten
FILTER_MIN_ON_MIN       = 30    # minuten — minimale aaneengesloten looptijd
FILTER_MIN_OFF_MIN      = 15    # minuten — minimale off-tijd voor herstart

# ── Heating defaults ───────────────────────────────────────────────────────────
HEAT_DEFAULT_SETPOINT_C = 28.0  # °C — doel watertemperatuur
HEAT_HYSTERESIS_C       = 0.5   # °C — hysterese (aan bij < setpoint-hysteresis)
HEAT_PV_SURPLUS_W       = 1500  # W — minimaal PV-surplus voor warmtepomp (hogere last)
HEAT_MIN_ON_MIN         = 20    # minuten — minimale aaneengesloten looptijd
HEAT_MIN_OFF_MIN        = 10    # minuten — minimale off-tijd voor herstart
HEAT_TEMP_UNKNOWN_ON    = False # False = niet verwarmen als temp onbekend

# ── Modes ──────────────────────────────────────────────────────────────────────
MODE_PV_SURPLUS   = "pv_surplus"
MODE_CHEAP_HOURS  = "cheap_hours"
MODE_TEMP_DEMAND  = "temp_demand"   # alleen voor verwarming
MODE_SCHEDULE     = "schedule"       # minimum dagelijkse filtertijd


@dataclass
class PoolAction:
    """Beslissing voor één schakelaar."""
    entity_id:   str
    label:       str
    action:      str    # "turn_on" | "turn_off" | "hold_on" | "hold_off"
    reason:      str
    is_on:       bool


@dataclass
class PoolStatus:
    """Volledige status voor dashboard-weergave."""
    filter_action:       PoolAction
    heat_action:         PoolAction
    water_temp_c:        Optional[float]
    heat_setpoint_c:     float
    filter_hours_today:  float
    filter_target_hours: float
    filter_mode:         str   # "pv_surplus" | "cheap_hours" | "schedule" | "off"
    heat_mode:           str   # "pv_surplus" | "cheap_hours" | "temp_demand" | "off"
    advice:              str
    uv_is_on:            bool
    robot_is_on:         bool


class PoolController:
    """
    Slimme controller voor zwembad filtration en verwarming.

    Gebruik vanuit coordinator (elke 10s tick):
        actions = await ctrl.async_evaluate(pv_surplus_w, price_info, sensor_states)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        filter_entity:        str = "",
        heat_entity:          str = "",
        temp_entity:          str = "",
        uv_entity:            str = "",
        robot_entity:         str = "",
        heat_setpoint:        float = HEAT_DEFAULT_SETPOINT_C,
        filter_modes:         Optional[list] = None,
        heat_modes:           Optional[list] = None,
        filter_power_entity:  str = "",
        heat_power_entity:    str = "",
    ) -> None:
        self._hass                = hass
        self._filter_eid          = filter_entity
        self._heat_eid            = heat_entity
        self._temp_eid            = temp_entity
        self._uv_eid              = uv_entity
        self._robot_eid           = robot_entity
        self._heat_setpoint       = heat_setpoint
        self._filter_power_eid    = filter_power_entity
        self._heat_power_eid      = heat_power_entity
        self._filter_modes    = filter_modes or [MODE_PV_SURPLUS, MODE_CHEAP_HOURS, MODE_SCHEDULE]
        self._heat_modes      = heat_modes   or [MODE_PV_SURPLUS, MODE_CHEAP_HOURS, MODE_TEMP_DEMAND]

        # Runtime state
        self._filter_last_on_ts:  float = 0.0
        self._filter_last_off_ts: float = 0.0
        self._heat_last_on_ts:    float = 0.0

        # Zelflerend vermogen — EMA over gemeten waarden (alpha=0.15)
        # Fallback als geen power-sensor geconfigureerd is
        self._learned_filter_w: float = 150.0   # startschatting filtreerpomp
        self._learned_heat_w:   float = 2000.0  # startschatting warmtepomp
        self._power_store = Store(hass, 1, "cloudems_pool_learned_power_v1")
        self._power_dirty = False
        self._power_last_save: float = 0.0
        self._heat_last_off_ts:   float = 0.0

        # Daily tracking (reset at midnight)
        self._filter_today_s:     float = 0.0
        self._last_tick_date:     Optional[str] = None
        self._filter_tick_on:     bool  = False   # was filter on last tick?

    # ── Public API ──────────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        pv_surplus_w: float,
        price_info:   dict,
        water_temp_c: Optional[float] = None,
    ) -> PoolStatus:
        """Evalueer en stuur filter + warmtepomp aan. Geef status terug."""
        now      = time.time()
        today    = datetime.now().strftime("%Y-%m-%d")

        # Dagelijkse reset
        if self._last_tick_date and self._last_tick_date != today:
            self._filter_today_s = 0.0
            self._filter_tick_on = False
        self._last_tick_date = today

        # Tik filter uren bij
        if self._filter_tick_on:
            self._filter_today_s += 10.0

        # Bereken doeluren filter vandaag
        target_h = self._filter_target_hours(water_temp_c)
        filter_h = self._filter_today_s / 3600.0

        # Haal huidige schakelaarstaten op
        filter_is_on = self._get_switch_state(self._filter_eid)
        heat_is_on   = self._get_switch_state(self._heat_eid)
        uv_is_on     = self._get_switch_state(self._uv_eid)
        robot_is_on  = self._get_switch_state(self._robot_eid)

        # Leer vermogen via EMA als apparaat aan is en power-sensor geconfigureerd
        if filter_is_on and self._filter_power_eid:
            self._learn_power(self._filter_power_eid, is_filter=True)
        if heat_is_on and self._heat_power_eid:
            self._learn_power(self._heat_power_eid, is_filter=False)

        # Evalueer filter
        filter_action = await self._eval_filter(
            pv_surplus_w, price_info, filter_is_on, filter_h, target_h, now
        )

        # Evalueer warmtepomp
        heat_action = await self._eval_heat(
            pv_surplus_w, price_info, heat_is_on, water_temp_c, now
        )

        # UV-installatie: meedraaien met filtratie
        if self._uv_eid and filter_action.action == "turn_on" and not uv_is_on:
            await self._switch(self._uv_eid, True)
        elif self._uv_eid and filter_action.action == "turn_off" and uv_is_on:
            await self._switch(self._uv_eid, False)

        self._filter_tick_on = (
            filter_action.action in ("turn_on", "hold_on")
            or (filter_is_on and filter_action.action not in ("turn_off",))
        )

        # Advies
        advice = self._build_advice(
            filter_h, target_h, water_temp_c, heat_is_on,
            filter_action, heat_action, pv_surplus_w
        )

        return PoolStatus(
            filter_action       = filter_action,
            heat_action         = heat_action,
            water_temp_c        = water_temp_c,
            heat_setpoint_c     = self._heat_setpoint,
            filter_hours_today  = round(filter_h, 2),
            filter_target_hours = target_h,
            filter_mode         = self._action_mode(filter_action),
            heat_mode           = self._action_mode(heat_action),
            advice              = advice,
            uv_is_on            = uv_is_on,
            robot_is_on         = robot_is_on,
        )

    def get_status_dict(self, status: PoolStatus) -> dict:
        """Converteer PoolStatus naar dict voor coordinator data."""
        return {
            "filter_is_on":        status.filter_action.is_on,
            "filter_action":       status.filter_action.action,
            "filter_reason":       status.filter_action.reason,
            "filter_mode":         status.filter_mode,
            "filter_hours_today":  status.filter_hours_today,
            "filter_target_hours": status.filter_target_hours,
            "filter_power_w":      self._get_power_w(self._filter_power_eid, self._filter_eid, 150.0),
            "heat_is_on":          status.heat_action.is_on,
            "heat_action":         status.heat_action.action,
            "heat_reason":         status.heat_action.reason,
            "heat_mode":           status.heat_mode,
            "water_temp_c":        status.water_temp_c,
            "heat_setpoint_c":     status.heat_setpoint_c,
            "heat_power_w":        self._get_power_w(self._heat_power_eid, self._heat_eid, 2000.0),
            "uv_is_on":            status.uv_is_on,
            "robot_is_on":         status.robot_is_on,
            "advice":              status.advice,
        }

    def update_config(
        self,
        filter_entity:       str = "",
        heat_entity:         str = "",
        temp_entity:         str = "",
        uv_entity:           str = "",
        robot_entity:        str = "",
        heat_setpoint:       float = HEAT_DEFAULT_SETPOINT_C,
        filter_power_entity: str = "",
        heat_power_entity:   str = "",
    ) -> None:
        self._filter_eid         = filter_entity
        self._heat_eid           = heat_entity
        self._temp_eid           = temp_entity
        self._uv_eid             = uv_entity
        self._robot_eid          = robot_entity
        self._heat_setpoint      = heat_setpoint
        self._filter_power_eid   = filter_power_entity
        self._heat_power_eid     = heat_power_entity

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _filter_target_hours(self, temp_c: Optional[float]) -> float:
        if temp_c is None:
            return MIN_FILTER_HOURS_WARM   # geen data → veilige standaard
        if temp_c >= 24.0:
            return MIN_FILTER_HOURS_HOT
        if temp_c >= 15.0:
            return MIN_FILTER_HOURS_WARM
        return MIN_FILTER_HOURS_COLD

    async def _eval_filter(
        self,
        pv_surplus_w: float,
        price_info:   dict,
        is_on:        bool,
        hours_done:   float,
        target_h:     float,
        now:          float,
    ) -> PoolAction:
        """Bepaal actie voor filtreerpomp."""
        if not self._filter_eid:
            return PoolAction(self._filter_eid, "Filtreerpomp", "hold_off",
                              "Niet geconfigureerd", False)

        min_on_s  = FILTER_MIN_ON_MIN  * 60
        min_off_s = FILTER_MIN_OFF_MIN * 60

        # Minimum looptijd bewaken (niet uitzetten als net aangedraaid)
        if is_on and (now - self._filter_last_on_ts) < min_on_s:
            return PoolAction(self._filter_eid, "Filtreerpomp", "hold_on",
                              f"Minimale looptijd ({FILTER_MIN_ON_MIN} min) actief", True)
        if not is_on and (now - self._filter_last_off_ts) < min_off_s:
            return PoolAction(self._filter_eid, "Filtreerpomp", "hold_off",
                              f"Minimale rusttijd ({FILTER_MIN_OFF_MIN} min) actief", False)

        # Reden om AAN te zetten
        turn_on_reason: Optional[str] = None

        # 1. Dagelijks minimum nog niet gehaald + het is de beste tijd
        if MODE_SCHEDULE in self._filter_modes and hours_done < target_h:
            # Haast: < 4 uur resttijd in de dag → altijd aan
            remaining_day_h = (24.0 - datetime.now().hour)
            remaining_needed = target_h - hours_done
            if remaining_needed > 0 and remaining_day_h <= remaining_needed + 1:
                turn_on_reason = (
                    f"Schema: {hours_done:.1f}/{target_h:.0f}u gefiltreerd, "
                    f"nog {remaining_needed:.1f}u nodig vandaag"
                )

        # 2. PV-surplus
        if MODE_PV_SURPLUS in self._filter_modes and pv_surplus_w >= FILTER_PV_SURPLUS_W:
            turn_on_reason = f"PV-surplus {pv_surplus_w:.0f}W — gratis filtreren"

        # 3. Goedkoopste uren
        if MODE_CHEAP_HOURS in self._filter_modes:
            in_cheap = price_info.get("in_cheapest_3h", False)
            if in_cheap and hours_done < target_h:
                turn_on_reason = f"Goedkoopste uren actief — {hours_done:.1f}/{target_h:.0f}u klaar"

        # Beslissing
        if turn_on_reason:
            if not is_on:
                self._filter_last_on_ts = now
                await self._switch(self._filter_eid, True)
                return PoolAction(self._filter_eid, "Filtreerpomp", "turn_on",
                                  turn_on_reason, True)
            return PoolAction(self._filter_eid, "Filtreerpomp", "hold_on",
                              turn_on_reason, True)

        # Minimum gehaald + geen reden om aan te zijn → uit
        if is_on and hours_done >= target_h:
            self._filter_last_off_ts = now
            await self._switch(self._filter_eid, False)
            return PoolAction(self._filter_eid, "Filtreerpomp", "turn_off",
                              f"Doel {target_h:.0f}u bereikt ({hours_done:.1f}u gefilterd)", False)

        if is_on:
            return PoolAction(self._filter_eid, "Filtreerpomp", "hold_on",
                              f"Doorlopen: {hours_done:.1f}/{target_h:.0f}u", True)

        return PoolAction(self._filter_eid, "Filtreerpomp", "hold_off",
                          f"Geen reden om te starten ({hours_done:.1f}/{target_h:.0f}u)", False)

    async def _eval_heat(
        self,
        pv_surplus_w: float,
        price_info:   dict,
        is_on:        bool,
        water_temp_c: Optional[float],
        now:          float,
    ) -> PoolAction:
        """Bepaal actie voor warmtepomp."""
        if not self._heat_eid:
            return PoolAction(self._heat_eid, "Warmtepomp", "hold_off",
                              "Niet geconfigureerd", False)

        min_on_s  = HEAT_MIN_ON_MIN  * 60
        min_off_s = HEAT_MIN_OFF_MIN * 60

        # Minimum looptijd bewaken
        if is_on and (now - self._heat_last_on_ts) < min_on_s:
            return PoolAction(self._heat_eid, "Warmtepomp", "hold_on",
                              f"Minimale looptijd ({HEAT_MIN_ON_MIN} min) actief", True)
        if not is_on and (now - self._heat_last_off_ts) < min_off_s:
            return PoolAction(self._heat_eid, "Warmtepomp", "hold_off",
                              f"Minimale rusttijd ({HEAT_MIN_OFF_MIN} min) actief", False)

        # Temperatuurbewaking
        temp_demand = False
        if water_temp_c is not None:
            threshold = self._heat_setpoint - HEAT_HYSTERESIS_C
            if is_on:
                # Doorgaan tot setpoint bereikt
                temp_demand = water_temp_c < self._heat_setpoint
            else:
                # Starten pas onder threshold
                temp_demand = water_temp_c < threshold
        elif HEAT_TEMP_UNKNOWN_ON:
            temp_demand = True

        turn_on_reason: Optional[str] = None

        # 1. Temperatuur heeft hoogste prioriteit
        if MODE_TEMP_DEMAND in self._heat_modes and temp_demand:
            # Extra check: PV-surplus of goedkope uren geeft extra punt
            if pv_surplus_w >= HEAT_PV_SURPLUS_W:
                turn_on_reason = (
                    f"Temperatuur {water_temp_c:.1f}°C < {self._heat_setpoint:.0f}°C "
                    f"+ PV-surplus {pv_surplus_w:.0f}W — ideaal moment"
                )
            elif price_info.get("in_cheapest_3h", False):
                turn_on_reason = (
                    f"Temperatuur {water_temp_c:.1f}°C < {self._heat_setpoint:.0f}°C "
                    f"+ goedkoopste uren — slim verwarmen"
                )
            else:
                # Temp vraagt verwarming maar geen goedkoop moment → wacht tenzij urgent
                if water_temp_c is not None and water_temp_c < (self._heat_setpoint - 2.0):
                    turn_on_reason = (
                        f"Temperatuur {water_temp_c:.1f}°C ruim onder setpoint — urgent verwarmen"
                    )
                elif is_on:
                    turn_on_reason = (
                        f"Doorverwarmen tot {self._heat_setpoint:.0f}°C "
                        f"(nu {water_temp_c:.1f}°C)"
                    )

        # 2. PV-surplus zonder temperatuurvraag (pre-heating)
        if not turn_on_reason and MODE_PV_SURPLUS in self._heat_modes:
            if pv_surplus_w >= HEAT_PV_SURPLUS_W:
                # Alleen pre-heaten als we nog niet op max temp
                max_preheat = self._heat_setpoint + 1.0
                if water_temp_c is None or water_temp_c < max_preheat:
                    turn_on_reason = (
                        f"PV-surplus {pv_surplus_w:.0f}W — gratis pre-heaten "
                        f"({water_temp_c:.1f}°C)" if water_temp_c is not None
                        else f"PV-surplus {pv_surplus_w:.0f}W — gratis verwarmen"
                    )

        # Beslissing
        if turn_on_reason:
            if not is_on:
                self._heat_last_on_ts = now
                await self._switch(self._heat_eid, True)
                return PoolAction(self._heat_eid, "Warmtepomp", "turn_on",
                                  turn_on_reason, True)
            return PoolAction(self._heat_eid, "Warmtepomp", "hold_on",
                              turn_on_reason, True)

        # Geen reden → uitzetten
        if is_on:
            reason = (
                f"Setpoint {self._heat_setpoint:.0f}°C bereikt ({water_temp_c:.1f}°C)"
                if water_temp_c is not None else "Geen verwarmingsvraag"
            )
            self._heat_last_off_ts = now
            await self._switch(self._heat_eid, False)
            return PoolAction(self._heat_eid, "Warmtepomp", "turn_off", reason, False)

        return PoolAction(self._heat_eid, "Warmtepomp", "hold_off",
                          "Geen verwarmingsvraag actief", False)

    def _build_advice(
        self,
        hours_done:    float,
        target_h:      float,
        water_temp_c:  Optional[float],
        heat_is_on:    bool,
        filter_action: PoolAction,
        heat_action:   PoolAction,
        pv_surplus_w:  float,
    ) -> str:
        parts = []

        if filter_action.action == "turn_on":
            parts.append(f"🔄 Filtreerpomp gestart: {filter_action.reason}")
        elif filter_action.action == "hold_on":
            parts.append(f"🔄 Filtreerpomp actief: {hours_done:.1f}/{target_h:.0f}u")
        else:
            remaining = max(0.0, target_h - hours_done)
            if remaining > 0:
                parts.append(f"⏳ Nog {remaining:.1f}u filtratie nodig vandaag")
            else:
                parts.append(f"✅ Dagelijkse filtratie compleet ({hours_done:.1f}u)")

        if water_temp_c is not None:
            if heat_action.action in ("turn_on", "hold_on"):
                parts.append(
                    f"🌡️ Verwarming actief — {water_temp_c:.1f}°C → {self._heat_setpoint:.0f}°C"
                )
            else:
                if water_temp_c >= self._heat_setpoint:
                    parts.append(f"✅ Water op temperatuur ({water_temp_c:.1f}°C)")
                else:
                    diff = self._heat_setpoint - water_temp_c
                    parts.append(
                        f"❄️ Water {water_temp_c:.1f}°C, {diff:.1f}°C onder setpoint — "
                        f"wacht op PV-surplus of goedkoop uur"
                    )

        if pv_surplus_w > 100 and filter_action.action not in ("turn_on", "hold_on"):
            parts.append(f"☀️ {pv_surplus_w:.0f}W PV-surplus beschikbaar voor filtratie")

        return " | ".join(parts) if parts else "Zwembad in standby"

    @staticmethod
    def _action_mode(action: PoolAction) -> str:
        if action.action in ("turn_off", "hold_off"):
            return "off"
        r = action.reason.lower()
        if "pv-surplus" in r:
            return "pv_surplus"
        if "goedkoop" in r:
            return "cheap_hours"
        if "temperatuur" in r or "setpoint" in r or "verwarmen" in r:
            return "temp_demand"
        if "schema" in r or "gefilterd" in r:
            return "schedule"
        return "active"

    def _get_switch_state(self, entity_id: str) -> bool:
        if not entity_id:
            return False
        st = self._hass.states.get(entity_id)
        return bool(st and st.state == "on")

    def _get_power_w(self, power_eid: str, switch_eid: str, fallback_w: float) -> float:
        """Lees vermogen uit een power-sensor. Valt terug op geleerde/fallback waarde."""
        if power_eid:
            st = self._hass.states.get(power_eid)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    pass
        # Geen power-sensor geconfigureerd: gebruik geleerde schatting
        is_filter = (switch_eid == self._filter_eid)
        if is_filter:
            return self._learned_filter_w if self._get_switch_state(switch_eid) else 0.0
        return self._learned_heat_w if self._get_switch_state(switch_eid) else 0.0

    def _learn_power(self, power_eid: str, is_filter: bool) -> None:
        """EMA-update van geleerd vermogen zodra een meting beschikbaar is (alpha=0.15)."""
        if not power_eid:
            return
        st = self._hass.states.get(power_eid)
        if not st or st.state in ("unavailable", "unknown"):
            return
        try:
            measured = float(st.state)
        except (ValueError, TypeError):
            return
        if measured < 10:   # negeer nul-metingen (schakelaar net aan)
            return
        alpha = 0.15
        if is_filter:
            self._learned_filter_w = round(
                self._learned_filter_w * (1 - alpha) + measured * alpha, 1)
        else:
            self._learned_heat_w = round(
                self._learned_heat_w * (1 - alpha) + measured * alpha, 1)
        self._power_dirty = True

    async def async_load(self) -> None:
        """Laad geleerde vermogenswaarden van schijf."""
        data = await self._power_store.async_load()
        if data:
            self._learned_filter_w = float(data.get("filter_w", self._learned_filter_w))
            self._learned_heat_w   = float(data.get("heat_w",   self._learned_heat_w))
            _LOGGER.debug("PoolController: geladen — filter=%.0fW, heat=%.0fW",
                          self._learned_filter_w, self._learned_heat_w)

    async def async_save(self) -> None:
        """Sla geleerde vermogenswaarden op (max 1x per 5 min)."""
        if not self._power_dirty:
            return
        if time.time() - self._power_last_save < 300:
            return
        await self._power_store.async_save({
            "filter_w": self._learned_filter_w,
            "heat_w":   self._learned_heat_w,
        })
        self._power_dirty = False
        self._power_last_save = time.time()

    async def _switch(self, entity_id: str, turn_on: bool) -> None:
        if not entity_id:
            return
        domain = entity_id.split(".")[0]
        service = "turn_on" if turn_on else "turn_off"
        try:
            await self._hass.services.async_call(
                domain, service, {"entity_id": entity_id}, blocking=False
            )
            _LOGGER.info("PoolController: %s → %s", entity_id, service)
            # Watchdog registratie
            _wd = getattr(getattr(self, "_coordinator", None), "_actuator_watchdog", None)
            if _wd:
                desired = "on" if turn_on else "off"
                async def _restore(eid=entity_id, ton=turn_on):
                    await self._hass.services.async_call(eid.split(".")[0], "turn_on" if ton else "turn_off", {"entity_id": eid}, blocking=False)
                _wd.register(f"pool_{entity_id}", entity_id, desired, _restore)
        except Exception as exc:
            _LOGGER.warning("PoolController: fout bij %s %s: %s", service, entity_id, exc)
