# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
tariff_change_detector.py — CloudEMS v4.0.5
=============================================
Detecteert automatisch als het energietarief veranderd is.

Algoritme:
  1. Bereken wekelijks de gemiddelde opslag (markup) boven EPEX
     (werkelijke kosten - EPEX_prijs = leveranciersopslag + belasting)
  2. Als de opslag significant verschilt van de geconfigureerde opslag
     → waarschuw: "Uw contract lijkt gewijzigd"
  3. Detecteert ook BTW/energiebelasting-wijzigingen

Gebruik:
  - Voedt zich met price_info.current (rekening) en price_info.epex_raw
  - Vergelijkt met config.supplier_markup + config.energy_tax
  - Persistent via HA Store (rolling 12 weken)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
STORAGE_KEY_TARIFF_DETECTOR = "cloudems_tariff_detector_v1"

# Significante afwijking: > 3 cent/kWh verschil over 7 dagen
CHANGE_THRESHOLD_EUR = 0.03
MIN_SAMPLES_PER_WEEK = 24        # minimaal 24u data per week


@dataclass
class TariffChangeStatus:
    change_detected:   bool
    current_markup:    float      # gemeten opslag (€/kWh)
    configured_markup: float      # geconfigureerde opslag
    deviation:         float      # verschil (positief = duurder dan verwacht)
    weeks_of_data:     int
    last_changed_week: Optional[str]
    tip:               str = ""

    def to_dict(self) -> dict:
        return {
            "change_detected":   self.change_detected,
            "current_markup":    round(self.current_markup, 4),
            "configured_markup": round(self.configured_markup, 4),
            "deviation":         round(self.deviation, 4),
            "weeks_of_data":     self.weeks_of_data,
            "last_changed_week": self.last_changed_week,
            "tip":               self.tip,
        }


class TariffChangeDetector:
    """
    Detecteert tariefwijzigingen door werkelijke opslag te vergelijken
    met geconfigureerde opslag.
    """

    def __init__(self, store: "Store", config: dict) -> None:
        self._store  = store
        self._config = config
        # {week_str: [markup_sample, ...]}
        self._weekly: dict[str, list[float]] = {}
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw:
                self._weekly = raw.get("weekly", {})
                # Houd laatste 13 weken
                if len(self._weekly) > 13:
                    keys = sorted(self._weekly.keys())[-13:]
                    self._weekly = {k: self._weekly[k] for k in keys}
        except Exception as err:
            _LOGGER.warning("TariffChangeDetector: laden mislukt: %s", err)
        self._loaded = True

    async def async_save(self) -> None:
        try:
            await self._store.async_save({"weekly": self._weekly})
        except Exception as err:
            _LOGGER.warning("TariffChangeDetector: opslaan mislukt: %s", err)

    def observe(
        self,
        actual_price_eur_kwh: float,
        epex_price_eur_kwh:   float,
    ) -> None:
        """Observeer één meting (elke update-cyclus)."""
        if actual_price_eur_kwh <= 0 or epex_price_eur_kwh <= 0:
            return
        markup = actual_price_eur_kwh - epex_price_eur_kwh
        if markup < -0.05:  # negatief is onwaarschijnlijk
            return
        from datetime import date
        week_str = date.today().strftime("%Y-W%W")
        self._weekly.setdefault(week_str, []).append(markup)
        # Cap per week
        if len(self._weekly[week_str]) > 200:
            self._weekly[week_str] = self._weekly[week_str][-200:]

    def analyze(self) -> TariffChangeStatus:
        """Analyseer op tariefwijziging."""
        configured = float(
            self._config.get("supplier_markup", 0) or
            self._config.get("energy_markup_eur_kwh", 0) or
            0.12  # redelijk NL gemiddeld als niet geconfigureerd
        )

        weeks = sorted(self._weekly.keys())
        if len(weeks) < 2:
            return TariffChangeStatus(
                change_detected   = False,
                current_markup    = configured,
                configured_markup = configured,
                deviation         = 0.0,
                weeks_of_data     = len(weeks),
                last_changed_week = None,
            )

        # Gemiddelde opslag van de laatste 4 weken
        recent_weeks = weeks[-4:]
        samples = []
        for w in recent_weeks:
            if len(self._weekly[w]) >= MIN_SAMPLES_PER_WEEK:
                wk_data = self._weekly[w]
                samples.extend(wk_data)

        if not samples:
            return TariffChangeStatus(
                change_detected   = False,
                current_markup    = configured,
                configured_markup = configured,
                deviation         = 0.0,
                weeks_of_data     = len(weeks),
                last_changed_week = None,
            )

        current_markup = sum(samples) / len(samples)
        deviation = current_markup - configured
        change = abs(deviation) >= CHANGE_THRESHOLD_EUR

        # Zoek wanneer de wijziging begon
        changed_week = None
        if change and len(weeks) >= 3:
            for i, w in enumerate(weeks[:-1]):
                if len(self._weekly[w]) >= MIN_SAMPLES_PER_WEEK:
                    prev = sum(self._weekly[w]) / len(self._weekly[w])
                    if abs(prev - current_markup) >= CHANGE_THRESHOLD_EUR:
                        changed_week = weeks[i + 1]
                        break

        tip = ""
        if change:
            direction = "gestegen" if deviation > 0 else "gedaald"
            tip = (
                f"Uw werkelijke opslag ({current_markup:.3f} €/kWh) is {direction} t.o.v. "
                f"geconfigureerd ({configured:.3f} €/kWh). "
                f"Controleer uw energiecontract of pas de instelling aan."
            )

        return TariffChangeStatus(
            change_detected   = change,
            current_markup    = current_markup,
            configured_markup = configured,
            deviation         = deviation,
            weeks_of_data     = len(weeks),
            last_changed_week = changed_week,
            tip               = tip,
        )
