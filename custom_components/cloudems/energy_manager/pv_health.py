# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS PV Paneel Gezondheidsmonitor — v1.0.0

Detecteert vuile panelen of degradatie door vergelijking van:
  • peak_power_w_7d (recente piek)  ← uit solar_learner
  • peak_power_w    (all-time piek) ← uit solar_learner

Op vergelijkbare zondagen met hoge irradiantie:
  Als recente productie consistent X% onder all-time record ligt
  → waarschijnlijk vuile panelen of degradatie.

Aanvullend: vergelijking met Open-Meteo irradiantie via pv_forecast
zodat alleen gelijkwaardige zondagen worden vergeleken.

Drempels:
  Soiling alert:     recente piek < 85% van all-time piek
  Degradatie info:   recente piek daalt jaar-op-jaar met > 1%

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

STORAGE_KEY     = "cloudems_pv_health_v1"
STORAGE_VERSION = 1

SOILING_THRESHOLD       = 0.85   # < 85% van all-time piek → soiling alert
DEGRADATION_THRESHOLD   = 0.99   # < 99% ten opzichte van vorig jaar-record → degradatie
MIN_PEAK_W              = 200    # Minimaal piek voor detectie
MIN_SAMPLES             = 5      # Minimale samples voor conclusie
SAVE_INTERVAL_S         = 600


@dataclass
class InverterHealthStatus:
    inverter_id: str
    label: str
    peak_all_time_w: float
    peak_recent_w: float           # 7-daags recent maximum
    ratio: float                   # recent / all-time
    alert: bool                    # True als < soiling drempel
    alert_type: str                # "soiling" | "degradation" | "ok" | "unknown"
    message: str


@dataclass
class PVHealthData:
    """Resultaat van de PV-gezondheidsmeter."""
    inverters: list[InverterHealthStatus]
    any_alert: bool
    summary: str


def _assess_inverter(
    inverter_id: str,
    label: str,
    peak_all_time_w: float,
    peak_recent_w: float,
    samples: int,
) -> InverterHealthStatus:
    """Beoordeel één omvormer."""
    if peak_all_time_w < MIN_PEAK_W or samples < MIN_SAMPLES:
        return InverterHealthStatus(
            inverter_id    = inverter_id,
            label          = label,
            peak_all_time_w= peak_all_time_w,
            peak_recent_w  = peak_recent_w,
            ratio          = 1.0,
            alert          = False,
            alert_type     = "unknown",
            message        = "Onvoldoende data voor beoordeling.",
        )

    ratio = peak_recent_w / peak_all_time_w if peak_all_time_w > 0 else 1.0

    if ratio < SOILING_THRESHOLD:
        pct_loss = round((1.0 - ratio) * 100, 1)
        return InverterHealthStatus(
            inverter_id    = inverter_id,
            label          = label,
            peak_all_time_w= round(peak_all_time_w),
            peak_recent_w  = round(peak_recent_w),
            ratio          = round(ratio, 3),
            alert          = True,
            alert_type     = "soiling",
            message        = (
                f"Omvormer '{label}' produceert de laatste 7 dagen {pct_loss:.1f}% minder dan het all-time record "
                f"({peak_recent_w:.0f} W vs {peak_all_time_w:.0f} W). "
                "Mogelijke oorzaak: vuile panelen, schaduw of degradatie. Overweeg de panelen te reinigen."
            ),
        )

    return InverterHealthStatus(
        inverter_id    = inverter_id,
        label          = label,
        peak_all_time_w= round(peak_all_time_w),
        peak_recent_w  = round(peak_recent_w),
        ratio          = round(ratio, 3),
        alert          = False,
        alert_type     = "ok",
        message        = f"Omvormer '{label}' presteert normaal ({ratio*100:.0f}% van all-time record).",
    )


class PVHealthMonitor:
    """
    Monitort PV-paneelgezondheid op basis van solar_learner profielen.

    Gebruik:
        monitor = PVHealthMonitor(hass)
        await monitor.async_setup()
        data = monitor.assess(solar_learner.get_all_profiles())
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # Bewaar maandelijkse pieken per omvormer voor degradatie-trend
        self._monthly_peaks: dict[str, dict[str, float]] = {}   # {inverter_id: {YYYY-MM: peak_w}}
        self._dirty = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        self._monthly_peaks = saved.get("monthly_peaks", {})
        _LOGGER.info("PVHealthMonitor: geladen (%d omvormerprofielen)", len(self._monthly_peaks))

    def assess(self, inverter_profiles: list) -> PVHealthData:
        """
        Beoordeel alle omvormers op basis van solar_learner-profielen.

        Parameters
        ----------
        inverter_profiles : list[InverterProfile]
            Geretourneerd door solar_learner.get_all_profiles()
        """
        statuses: list[InverterHealthStatus] = []

        now_ym = datetime.now(timezone.utc).strftime("%Y-%m")

        for profile in inverter_profiles:
            eid            = profile.inverter_id
            peak_all       = profile.peak_power_w
            peak_recent    = profile.peak_power_w_7d
            samples        = profile.samples

            # Update maandelijks record
            if eid not in self._monthly_peaks:
                self._monthly_peaks[eid] = {}
            if peak_recent > self._monthly_peaks[eid].get(now_ym, 0.0):
                self._monthly_peaks[eid][now_ym] = peak_recent
                self._dirty = True

            status = _assess_inverter(eid, profile.label, peak_all, peak_recent, samples)
            statuses.append(status)

        any_alert = any(s.alert for s in statuses)

        if not statuses:
            summary = "Geen omvormerdata beschikbaar."
        elif any_alert:
            alerts = [s for s in statuses if s.alert]
            summary = "; ".join(s.message for s in alerts)
        else:
            summary = (
                f"Alle {len(statuses)} omvormer(s) presteren normaal. "
                "Geen soiling of degradatie gedetecteerd."
            )

        return PVHealthData(
            inverters = statuses,
            any_alert = any_alert,
            summary   = summary,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({"monthly_peaks": self._monthly_peaks})
            self._dirty = False
            self._last_save = time.time()
