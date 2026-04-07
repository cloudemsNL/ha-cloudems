# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
CloudEMSAlpha — v1.0.0

Measures the added value of CloudEMS vs the naive Zonneplan strategy.

Definition of Alpha:
  CloudEMS alpha = actual result - naive baseline result

Naive baseline = what Zonneplan does by default without CloudEMS:
  - LOW tariff: do nothing (Zonneplan charges from solar only)
  - NORMAL tariff: do nothing
  - HIGH tariff: discharge at fixed 2500W
  - No anticipation of future prices
  - No PV forecast integration
  - No export limit awareness

CloudEMS additionally:
  - Charges at cheap tariff when HIGH is expected
  - Scales charge urgency based on forecast
  - Considers battery wear (SoH)
  - Considers temperature efficiency
  - Pre-positions for imbalance market
  - Respects export limits

Daily measurement:
  Actual arbitrage spread (CloudEMS) vs naive spread
  Delta in €/day = CloudEMS alpha

Commercial value:
  - To users: "CloudEMS earns €X/month extra"
  - To energy companies: proof of flexibility value
  - For VPP aggregation: proof of collective value
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class AlphaSession:
    """Single-day alpha measurement."""
    date:               str   = ""
    cloudems_eur:       float = 0.0
    naive_eur:          float = 0.0
    alpha_eur:          float = 0.0
    charge_kwh:         float = 0.0
    discharge_kwh:      float = 0.0
    avg_charge_ct:      float = 0.0
    avg_discharge_ct:   float = 0.0
    naive_charge_ct:    float = 0.0
    naive_discharge_ct: float = 0.0


class CloudEMSAlpha:
    """
    Measures and reports the alpha (added value) of CloudEMS
    compared to the naive Zonneplan baseline strategy.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass    = hass
        self._store   = None
        self._history: list[AlphaSession] = []

        # Current day accumulation
        self._today_charge_wh           = 0.0
        self._today_discharge_wh        = 0.0
        self._today_charge_cost         = 0.0
        self._today_discharge_rev       = 0.0
        self._today_naive_charge_cost   = 0.0
        self._today_naive_discharge_rev = 0.0

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, 1, "cloudems_alpha_v1")
        try:
            saved = await self._store.async_load()
            if saved:
                self._history = [AlphaSession(**s) for s in saved.get("history", [])]
        except Exception as e:
            _LOGGER.debug("CloudEMSAlpha load error: %s", e)

    def observe(self,
                battery_w:     float,
                price_eur_kwh: float,
                tariff_group:  str,
                pv_surplus_w:  float) -> None:
        """
        Observe one tick (15s):
          - CloudEMS action: actual battery_w + price
          - Naive action: what Zonneplan would do without CloudEMS
        """
        tick_kwh = abs(battery_w) / 1000 * (15 / 3600)

        # CloudEMS actual
        if battery_w > 50:
            self._today_charge_wh     += tick_kwh * 1000
            self._today_charge_cost   += price_eur_kwh * tick_kwh
        elif battery_w < -50:
            self._today_discharge_wh  += tick_kwh * 1000
            self._today_discharge_rev += price_eur_kwh * tick_kwh

        # Naive baseline: charge from PV surplus only, discharge at HIGH only
        naive_charge_w    = min(pv_surplus_w, 3000) if pv_surplus_w > 100 else 0.0
        naive_discharge_w = 2500.0 if tariff_group == "high" else 0.0

        self._today_naive_charge_cost   += price_eur_kwh * naive_charge_w    / 1000 * (15/3600)
        self._today_naive_discharge_rev += price_eur_kwh * naive_discharge_w / 1000 * (15/3600)

    def commit_day(self) -> Optional[AlphaSession]:
        """Close current day and persist."""
        charge_kwh    = self._today_charge_wh    / 1000
        discharge_kwh = self._today_discharge_wh / 1000

        cloudems_spread = self._today_discharge_rev  - self._today_charge_cost
        naive_spread    = self._today_naive_discharge_rev - self._today_naive_charge_cost
        alpha           = cloudems_spread - naive_spread

        avg_chg_ct = (self._today_charge_cost   / charge_kwh    * 100) if charge_kwh    > 0.01 else 0
        avg_dis_ct = (self._today_discharge_rev / discharge_kwh * 100) if discharge_kwh > 0.01 else 0

        session = AlphaSession(
            date               = date.today().isoformat(),
            cloudems_eur       = round(cloudems_spread, 4),
            naive_eur          = round(naive_spread, 4),
            alpha_eur          = round(alpha, 4),
            charge_kwh         = round(charge_kwh, 3),
            discharge_kwh      = round(discharge_kwh, 3),
            avg_charge_ct      = round(avg_chg_ct, 2),
            avg_discharge_ct   = round(avg_dis_ct, 2),
        )
        self._history.append(session)
        self._history = self._history[-90:]

        # Reset accumulators
        self._today_charge_wh = self._today_discharge_wh = 0.0
        self._today_charge_cost = self._today_discharge_rev = 0.0
        self._today_naive_charge_cost = self._today_naive_discharge_rev = 0.0

        return session

    async def async_save(self) -> None:
        if not self._store:
            return
        try:
            import dataclasses
            await self._store.async_save({
                "history": [dataclasses.asdict(s) for s in self._history]
            })
        except Exception as e:
            _LOGGER.debug("CloudEMSAlpha save error: %s", e)

    def to_dict(self) -> dict:
        # Intraday totals
        charge_kwh    = self._today_charge_wh / 1000
        discharge_kwh = self._today_discharge_wh / 1000
        today_cloudems = self._today_discharge_rev  - self._today_charge_cost
        today_naive    = self._today_naive_discharge_rev - self._today_naive_charge_cost
        today_alpha    = today_cloudems - today_naive

        last_30   = self._history[-30:]
        avg_alpha = sum(s.alpha_eur for s in last_30) / len(last_30) if last_30 else 0
        cum_alpha = sum(s.alpha_eur for s in self._history)

        return {
            "tracking":             True,
            "cloudems_eur_today":   round(today_cloudems, 3),
            "naive_eur_today":      round(today_naive, 3),
            "alpha_eur_today":      round(today_alpha, 3),
            "avg_alpha_eur_day":    round(avg_alpha, 3),
            "avg_alpha_eur_month":  round(avg_alpha * 30.44, 2),
            "cumulative_alpha_eur": round(cum_alpha, 2),
            "history_30d": [
                {
                    "date":     s.date,
                    "cloudems": round(s.cloudems_eur, 3),
                    "naive":    round(s.naive_eur, 3),
                    "alpha":    round(s.alpha_eur, 3),
                }
                for s in last_30
            ],
        }
