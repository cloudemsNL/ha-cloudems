# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
ImbalanceRevenueTracker — v1.0.0

Tracks battery charge/discharge during Tennet imbalance events and calculates
the theoretical imbalance market revenue vs what Zonneplan actually pays.

The difference reveals Zonneplan's margin on imbalance market participation.

How it works:
  1. Each coordinator tick: record battery_w + current EPEX price + Tennet signal
  2. When Tennet settlement prices are available (per PTU):
       - UP regulation PTU: battery discharged → theoretical_revenue += kWh × tennet_up_price
       - DOWN regulation PTU: battery charged  → theoretical_revenue += kWh × tennet_down_price
  3. Actual revenue: EPEX spread × our kWh (what Zonneplan credits/charges us)
  4. Margin = theoretical_revenue - actual_revenue = Zonneplan's cut

Tennet imbalance settlement prices (Dutch):
  - "opregelen" (up-regulation):   generators/batteries get paid opregel_prijs (€/MWh)
  - "afregelen" (down-regulation): batteries get paid to absorb afregel_prijs (€/MWh)
  - Both published per PTU (15-min block) via Tennet API

Typical margin:
  Tennet opregel price during scarcity: 200-1000 €/MWh
  EPEX spot price: 50-150 €/MWh
  Zonneplan credits Nexus owners at EPEX rate
  → margin can be 4-10x during activation events

Commercial insight:
  This data demonstrates the VPP value proposition:
  Direct market access would eliminate the intermediary margin.
  Data can be shared with energy companies to prove flexibility value.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

PTU_SECONDS    = 900   # 15-minute PTU blocks
STORE_KEY      = "cloudems_imbalance_revenue_v1"
CO2_KG_PER_KWH = 0.4  # NL grid average CO2 intensity


@dataclass
class PTURecord:
    """One PTU (15-min block) of battery activity and imbalance market data."""
    ts:                   float  = 0.0    # PTU start timestamp
    ptu_start:            str    = ""     # ISO datetime
    direction:            str    = "neutral"  # "up" | "down" | "neutral"
    battery_charge_kwh:   float  = 0.0   # kWh charged this PTU
    battery_discharge_kwh: float = 0.0   # kWh discharged this PTU
    epex_price_eur_mwh:   float  = 0.0   # EPEX spot price (€/MWh)
    tennet_up_price:      float  = 0.0   # Tennet up-regulation price (€/MWh), 0 if unknown
    tennet_down_price:    float  = 0.0   # Tennet down-regulation price (€/MWh), 0 if unknown
    # Calculated fields
    actual_revenue_eur:   float  = 0.0   # what Zonneplan credits at EPEX rate
    theoretical_revenue_eur: float = 0.0 # what we'd earn at Tennet imbalance price
    margin_eur:           float  = 0.0   # theoretical - actual = Zonneplan's cut


class ImbalanceRevenueTracker:
    """
    Tracks battery revenue during imbalance events and estimates Zonneplan's margin.

    Accumulates data per PTU, then calculates revenue metrics.
    Persists daily/monthly aggregates in HA Store.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass    = hass
        self._store   = None

        # Current PTU accumulation
        self._ptu_start_ts:       float = 0.0
        self._ptu_charge_wh:      float = 0.0
        self._ptu_discharge_wh:   float = 0.0
        self._ptu_epex_sum:       float = 0.0  # price × tick_kwh for weighted avg
        self._ptu_ticks:          int   = 0

        # Imbalance prices (updated from Tennet API)
        self._last_up_price:   float = 0.0   # €/MWh
        self._last_down_price: float = 0.0   # €/MWh
        self._last_direction:  str   = "neutral"

        # History
        self._ptu_history:     list[PTURecord]  = []   # last 96 PTUs (24h)
        self._daily_summary:   list[dict]        = []   # last 90 days
        self._today:           dict              = self._empty_day()

    def _empty_day(self) -> dict:
        return {
            "date":                    "",
            "actual_revenue_eur":      0.0,
            "theoretical_revenue_eur": 0.0,
            "margin_eur":              0.0,
            "margin_pct":              0.0,
            "up_events":               0,
            "down_events":             0,
            "charge_kwh":              0.0,
            "discharge_kwh":           0.0,
        }

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, 1, STORE_KEY)
        await self._load()

    async def _load(self) -> None:
        try:
            saved = await self._store.async_load()
            if saved:
                self._daily_summary = saved.get("daily_summary", [])
                self._today         = saved.get("today", self._empty_day())
        except Exception as e:
            _LOGGER.debug("ImbalanceRevenueTracker load error: %s", e)

    async def _save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "daily_summary": self._daily_summary[-90:],
                "today":         self._today,
            })
        except Exception as e:
            _LOGGER.debug("ImbalanceRevenueTracker save error: %s", e)

    def update_tennet_prices(self, up_price: float, down_price: float,
                              direction: str) -> None:
        """Update current Tennet settlement prices from signal module."""
        self._last_up_price   = up_price
        self._last_down_price = down_price
        self._last_direction  = direction

    def observe(self, battery_w: float, epex_price_eur_kwh: float) -> None:
        """
        Record one coordinator tick (15s).
        Commits PTU when 15-minute boundary is crossed.
        """
        now     = time.time()
        tick_kwh = abs(battery_w) / 1000 * (15 / 3600)

        # Initialize PTU on first tick
        if self._ptu_start_ts == 0.0:
            self._ptu_start_ts = now - (now % PTU_SECONDS)

        # Accumulate within PTU
        if battery_w > 50:
            self._ptu_charge_wh    += battery_w * (15 / 3600)
        elif battery_w < -50:
            self._ptu_discharge_wh += abs(battery_w) * (15 / 3600)

        self._ptu_epex_sum += epex_price_eur_kwh * tick_kwh
        self._ptu_ticks    += 1

        # Commit when PTU boundary is crossed
        if now >= self._ptu_start_ts + PTU_SECONDS:
            self._commit_ptu()
            self._ptu_start_ts    = now - (now % PTU_SECONDS)
            self._ptu_charge_wh   = 0.0
            self._ptu_discharge_wh = 0.0
            self._ptu_epex_sum    = 0.0
            self._ptu_ticks       = 0

    def _commit_ptu(self) -> None:
        """Close current PTU and calculate revenue."""
        charge_kwh    = self._ptu_charge_wh    / 1000
        discharge_kwh = self._ptu_discharge_wh / 1000

        if charge_kwh < 0.001 and discharge_kwh < 0.001:
            return   # nothing happened this PTU

        # Weighted average EPEX price this PTU
        total_kwh    = charge_kwh + discharge_kwh
        avg_epex_kwh = (self._ptu_epex_sum / total_kwh) if total_kwh > 0 else 0
        epex_mwh     = avg_epex_kwh * 1000  # → €/MWh

        direction = self._last_direction

        # Actual revenue at EPEX rate (Zonneplan billing)
        # Discharging = selling at EPEX, charging = buying at EPEX
        actual_rev = (discharge_kwh * avg_epex_kwh) - (charge_kwh * avg_epex_kwh)

        # Theoretical revenue at Tennet imbalance prices
        theoretical_rev = 0.0
        if direction == "up" and self._last_up_price > 0:
            # Up-regulation: grid pays us opregel_prijs to discharge
            up_kwh_price     = self._last_up_price / 1000   # €/MWh → €/kWh
            theoretical_rev  = discharge_kwh * up_kwh_price
        elif direction == "down" and self._last_down_price > 0:
            # Down-regulation: grid pays us afregel_prijs to charge
            down_kwh_price   = self._last_down_price / 1000
            theoretical_rev  = charge_kwh * down_kwh_price
        else:
            # No imbalance event: theoretical = actual (EPEX rate)
            theoretical_rev = actual_rev

        margin = theoretical_rev - actual_rev

        ptu_start_dt = datetime.fromtimestamp(self._ptu_start_ts, tz=timezone.utc)
        rec = PTURecord(
            ts                      = self._ptu_start_ts,
            ptu_start               = ptu_start_dt.strftime("%H:%M"),
            direction               = direction,
            battery_charge_kwh      = round(charge_kwh, 4),
            battery_discharge_kwh   = round(discharge_kwh, 4),
            epex_price_eur_mwh      = round(epex_mwh, 2),
            tennet_up_price         = round(self._last_up_price, 2),
            tennet_down_price       = round(self._last_down_price, 2),
            actual_revenue_eur      = round(actual_rev, 5),
            theoretical_revenue_eur = round(theoretical_rev, 5),
            margin_eur              = round(margin, 5),
        )
        self._ptu_history.append(rec)
        self._ptu_history = self._ptu_history[-96:]   # 24h

        # Accumulate daily totals
        import dataclasses
        self._today["actual_revenue_eur"]      += actual_rev
        self._today["theoretical_revenue_eur"] += theoretical_rev
        self._today["margin_eur"]              += margin
        self._today["charge_kwh"]              += charge_kwh
        self._today["discharge_kwh"]           += discharge_kwh
        if direction == "up":   self._today["up_events"]   += 1
        if direction == "down": self._today["down_events"] += 1

        theo = self._today["theoretical_revenue_eur"]
        act  = self._today["actual_revenue_eur"]
        self._today["margin_pct"] = (
            round((theo - act) / theo * 100, 1) if theo > 0.001 else 0.0
        )

        _LOGGER.debug(
            "PTU %s: dir=%s charge=%.3f dis=%.3f EPEX=%.0f €/MWh "
            "actual=€%.4f theoretical=€%.4f margin=€%.4f",
            rec.ptu_start, direction, charge_kwh, discharge_kwh,
            epex_mwh, actual_rev, theoretical_rev, margin
        )

    def commit_day(self) -> None:
        """Day rollover: archive today's summary."""
        from datetime import date
        self._today["date"] = date.today().isoformat()
        self._daily_summary.append(dict(self._today))
        self._daily_summary = self._daily_summary[-90:]
        self._today = self._empty_day()

    def to_dict(self) -> dict:
        today = self._today

        # Aggregate PTU history for display
        up_ptus   = [r for r in self._ptu_history if r.direction == "up"   and r.tennet_up_price > 0]
        down_ptus = [r for r in self._ptu_history if r.direction == "down" and r.tennet_down_price > 0]

        avg_up_price   = (sum(r.tennet_up_price   for r in up_ptus)   / len(up_ptus))   if up_ptus   else 0
        avg_down_price = (sum(r.tennet_down_price for r in down_ptus) / len(down_ptus)) if down_ptus else 0

        # Last 10 PTUs for display
        recent_ptus = [
            {
                "time":        r.ptu_start,
                "direction":   r.direction,
                "charge_kwh":  r.battery_charge_kwh,
                "dis_kwh":     r.battery_discharge_kwh,
                "epex_mwh":    r.epex_price_eur_mwh,
                "tennet_up":   r.tennet_up_price,
                "tennet_down": r.tennet_down_price,
                "actual_eur":  r.actual_revenue_eur,
                "theor_eur":   r.theoretical_revenue_eur,
                "margin_eur":  r.margin_eur,
            }
            for r in self._ptu_history[-10:]
        ]

        return {
            # Today
            "today_actual_eur":       round(today["actual_revenue_eur"],      4),
            "today_theoretical_eur":  round(today["theoretical_revenue_eur"], 4),
            "today_margin_eur":       round(today["margin_eur"],              4),
            "today_margin_pct":       today["margin_pct"],
            "today_up_events":        today["up_events"],
            "today_down_events":      today["down_events"],
            "today_charge_kwh":       round(today["charge_kwh"],    3),
            "today_discharge_kwh":    round(today["discharge_kwh"], 3),
            # Market prices
            "avg_tennet_up_price_mwh":   round(avg_up_price,   2),
            "avg_tennet_down_price_mwh": round(avg_down_price, 2),
            # History
            "daily_summary": self._daily_summary[-30:],
            "recent_ptus":   recent_ptus,
        }
