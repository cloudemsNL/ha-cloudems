# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS
"""
TennetImbalanceSignal — v1.0.0

Fetches Dutch imbalance market data from the Tennet open data API.
Used for pre-positioning the battery before FCR/aFRR activation is needed.

Tennet Open Data API: https://api.tennet.org/open/
Endpoints:
  /settledimbalances       — settled imbalance per PTU (15-min block)
  /actualsystemimbalance   — current system imbalance (MW)

Strategy:
  - Positive imbalance (grid shortage) → grid needs power → discharge battery
  - Negative imbalance (grid surplus)  → grid has excess → charge battery
  - Use trending over last 4 PTUs to predict direction

SOC pre-positioning targets:
  - Expected UP-regulation (positive): raise SOC target (more energy to deliver)
  - Expected DOWN-regulation (negative): lower SOC target (more headroom to absorb)

Fallback:
  If Tennet API is unavailable, falls back to EPEX price as proxy.
  Strong correlation for NL: negative EPEX = grid surplus = down-regulation expected.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

_LOGGER = logging.getLogger(__name__)

TENNET_API     = "https://api.tennet.org/open"
FETCH_INTERVAL = 900   # every PTU (15 minutes)
TREND_WINDOW   = 4     # look back 4 PTUs for trend


@dataclass
class ImbalanceSignal:
    """Current imbalance signal and recommended SOC adjustment."""
    timestamp:          float = 0.0
    current_mw:         float = 0.0   # positive = shortage, negative = surplus
    trend_mw:           float = 0.0   # average over last 4 PTUs
    direction:          str   = "neutral"  # "up" | "down" | "neutral"
    soc_adjustment_pct: float = 0.0   # how much to shift SOC target
    confidence:         float = 0.0   # 0-1
    reason:             str   = ""
    source:             str   = "epex_proxy"  # "tennet" | "epex_proxy"


class TennetImbalanceSignal:
    """
    Fetches imbalance data and calculates pre-positioning advice.

    Falls back to EPEX price proxy if Tennet API is unavailable.
    """

    def __init__(self, hass, config: dict) -> None:
        self._hass           = hass
        self._session        = None
        self._enabled        = True
        self._last_fetch     = 0.0
        self._history:       list[dict] = []
        self._last_signal:   Optional[ImbalanceSignal] = None
        self._api_available  = True
        self._last_up_price:  float = 0.0   # latest Tennet up-regulation price (€/MWh)
        self._last_down_price: float = 0.0  # latest Tennet down-regulation price (€/MWh)

    async def async_setup(self) -> None:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        self._session = async_get_clientsession(self._hass)

    async def async_update(self, epex_price_eur_kwh: float = 0.0) -> ImbalanceSignal:
        """Fetch current imbalance and calculate pre-positioning signal."""
        now = time.time()

        if self._api_available and now - self._last_fetch > FETCH_INTERVAL:
            _LOGGER.debug("TennetImbalance: fetching from API (api_available=%s)", self._api_available)
            await self._fetch_tennet()
            self._last_fetch = now

        if not self._history or not self._api_available:
            signal = self._epex_proxy(epex_price_eur_kwh)
            _LOGGER.debug(
                "TennetImbalance: using EPEX proxy — price=%.3f €/kWh, "
                "direction=%s, adj=%.1f%%, conf=%.0f%%",
                epex_price_eur_kwh, signal.direction,
                signal.soc_adjustment_pct, signal.confidence * 100,
            )
            return signal

        signal = self._calculate_signal()
        _LOGGER.debug(
            "TennetImbalance: Tennet data — mw=%.0f, trend=%.0f, "
            "direction=%s, adj=%.1f%%, up_price=%.0f €/MWh",
            signal.current_mw, signal.trend_mw,
            signal.direction, signal.soc_adjustment_pct,
            self._last_up_price,
        )
        return signal

    async def _fetch_tennet(self) -> None:
        """Fetch current system imbalance from Tennet."""
        if not self._session:
            return
        try:
            url     = f"{TENNET_API}/actualsystemimbalance"
            headers = {"Accept": "application/json", "User-Agent": "CloudEMS/5.5"}
            async with self._session.get(url, headers=headers, timeout=10) as r:
                if r.status == 200:
                    data    = await r.json()
                    records = data.get("records", data.get("data", [data]))
                    for rec in (records if isinstance(records, list) else [records]):
                        mw       = float(rec.get("systemImbalance", rec.get("imbalance", 0)) or 0)
                        up_price = float(rec.get("upwardDispatchPrice",
                                         rec.get("priceUpward",
                                         rec.get("upPrice", 0))) or 0)
                        dn_price = float(rec.get("downwardDispatchPrice",
                                         rec.get("priceDownward",
                                         rec.get("downPrice", 0))) or 0)
                        self._history.append({
                            "ts":       time.time(),
                            "mw":       mw,
                            "up_price": up_price,   # €/MWh
                            "dn_price": dn_price,   # €/MWh
                        })
                    self._history = self._history[-8:]
                    _LOGGER.debug("TennetImbalance: %d records loaded", len(self._history))
                elif r.status == 404:
                    await self._fetch_tennet_settled()
                else:
                    _LOGGER.debug("TennetImbalance: HTTP %s", r.status)
                    self._api_available = False
        except Exception as exc:
            _LOGGER.info(
                "TennetImbalance: API unreachable (%s) — falling back to EPEX proxy. "
                "URL attempted: %s/actualsystemimbalance",
                exc, TENNET_API,
            )
            self._api_available = False

    async def _fetch_tennet_settled(self) -> None:
        """Alternative: fetch settled imbalance prices."""
        try:
            now     = datetime.now(timezone.utc)
            from_dt = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            to_dt   = now.strftime("%Y-%m-%dT%H:%M:%S")
            url     = f"{TENNET_API}/settledimbalances?fromDateTime={from_dt}&toDateTime={to_dt}"
            headers = {"Accept": "application/json", "User-Agent": "CloudEMS/5.5"}
            async with self._session.get(url, headers=headers, timeout=10) as r:
                if r.status == 200:
                    data    = await r.json()
                    records = data.get("records", data.get("data", []))
                    for rec in records:
                        mw       = float(rec.get("systemImbalanceVolume",
                                                  rec.get("imbalanceVolume", 0)) or 0)
                        up_price = float(rec.get("upwardDispatchPrice",
                                         rec.get("priceUpward", 0)) or 0)
                        dn_price = float(rec.get("downwardDispatchPrice",
                                         rec.get("priceDownward", 0)) or 0)
                        self._history.append({
                            "ts":       time.time(),
                            "mw":       mw,
                            "up_price": up_price,
                            "dn_price": dn_price,
                        })
                    self._history    = self._history[-8:]
                    self._api_available = True
        except Exception as exc:
            _LOGGER.debug("TennetImbalance settled error: %s", exc)
            self._api_available = False

    def _calculate_signal(self) -> ImbalanceSignal:
        """Calculate pre-positioning signal from imbalance trend."""
        if not self._history:
            return ImbalanceSignal(source="tennet", reason="No data")

        recent     = self._history[-TREND_WINDOW:]
        current_mw = recent[-1]["mw"]
        trend_mw   = sum(r["mw"] for r in recent) / len(recent)

        if trend_mw > 200:      # grid shortage → up-regulation expected → pre-charge
            direction = "up"
            soc_adj   = min(10.0, trend_mw / 500 * 10)
            confidence = min(1.0, abs(trend_mw) / 500)
            reason = (f"Tennet shortage {trend_mw:.0f}MW → pre-charge battery "
                      f"(+{soc_adj:.0f}% SOC target)")
        elif trend_mw < -200:   # grid surplus → down-regulation expected → free up headroom
            direction = "down"
            soc_adj   = max(-10.0, trend_mw / 500 * 10)
            confidence = min(1.0, abs(trend_mw) / 500)
            reason = (f"Tennet surplus {abs(trend_mw):.0f}MW → free up headroom "
                      f"({soc_adj:.0f}% SOC target)")
        else:
            direction  = "neutral"
            soc_adj    = 0.0
            confidence = 0.3
            reason     = f"Tennet neutral ({trend_mw:.0f}MW)"

        # Extract latest settlement prices
        last_up   = recent[-1].get("up_price", 0.0)
        last_down = recent[-1].get("dn_price",  0.0)

        signal = ImbalanceSignal(
            timestamp          = time.time(),
            current_mw         = current_mw,
            trend_mw           = round(trend_mw, 1),
            direction          = direction,
            soc_adjustment_pct = round(soc_adj, 1),
            confidence         = round(confidence, 2),
            reason             = reason,
            source             = "tennet",
        )
        self._last_signal    = signal
        self._last_up_price  = last_up
        self._last_down_price = last_down
        return signal

    def _epex_proxy(self, epex_price: float) -> ImbalanceSignal:
        """
        EPEX price as proxy for imbalance signal.

        Strong NL correlation:
        - EPEX < 0 ct/kWh  → grid surplus → down-regulation → charge extra
        - EPEX > 35 ct/kWh → grid shortage → up-regulation → keep headroom
        """
        p = epex_price * 100  # → ct/kWh

        if p < -5:
            direction  = "down"
            soc_adj    = max(-8.0, p / 10)
            confidence = min(1.0, abs(p) / 20)
            reason     = f"EPEX {p:.1f}ct (negative) → surplus expected, free up headroom"
        elif p < 5:
            direction  = "down"
            soc_adj    = -3.0
            confidence = 0.4
            reason     = f"EPEX {p:.1f}ct (very low) → light surplus signal"
        elif p > 40:
            direction  = "up"
            soc_adj    = min(8.0, (p - 30) / 10)
            confidence = min(1.0, (p - 30) / 30)
            reason     = f"EPEX {p:.1f}ct (high) → shortage signal, charge priority"
        else:
            direction  = "neutral"
            soc_adj    = 0.0
            confidence = 0.2
            reason     = f"EPEX {p:.1f}ct — neutral"

        signal = ImbalanceSignal(
            timestamp          = time.time(),
            current_mw         = 0.0,
            trend_mw           = 0.0,
            direction          = direction,
            soc_adjustment_pct = round(soc_adj, 1),
            confidence         = round(confidence, 2),
            reason             = reason,
            source             = "epex_proxy",
        )
        self._last_signal = signal
        return signal

    def to_dict(self) -> dict:
        s = self._last_signal
        if not s:
            return {}
        return {
            "direction":            s.direction,
            "current_mw":           s.current_mw,
            "trend_mw":             s.trend_mw,
            "soc_adjustment_pct":   s.soc_adjustment_pct,
            "confidence":           s.confidence,
            "reason":               s.reason,
            "source":               s.source,
            "ts":                   s.timestamp,
            "up_price_eur_mwh":     round(self._last_up_price, 2),
            "down_price_eur_mwh":   round(self._last_down_price, 2),
        }

    @property
    def last_up_price(self) -> float:
        return self._last_up_price

    @property
    def last_down_price(self) -> float:
        return self._last_down_price
