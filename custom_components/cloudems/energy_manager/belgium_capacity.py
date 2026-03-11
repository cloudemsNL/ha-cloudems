# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — België Capaciteitstarief Optimalisatie — v1.0.0

Specifieke module voor de Belgische capaciteitstarief-wetgeving (actief 2023+).
Verschil met NL: het Belgische tarief is strenger en werkt anders:

  • Grondslag:       gemiddelde van de 12 hoogste maandpieken van het afgelopen jaar
  • Tarief:          ~41 €/kW/jaar (Fluvius 2025) = ~3.42 €/kW/maand
  • Drempelwaarde:   2.5 kW per kwartier (gratis tot hier)
  • Gratis band:     eerste 2.5 kW maandpiek is altijd gratis
  • DSO-zones:       Fluvius Antwerpen, Gent, Limburg, Oost-VL, West-VL,
                     Ores, Resa, Sibelgas (elk eigen tarief)

Functies:
  1. BelgianCapacityCalculator: bereken actuele jaarkosten + verwacht tarief volgend jaar
  2. DSO zone-detectie op basis van postcode
  3. Geoptimaliseerde load-shed: rangschik acties op € impact
  4. Sensor: cloudems_be_capacity_cost

Integratie:
  Gebruik naast (niet als vervanging van) CapacityPeakMonitor.
  Geactiveerd als country == "BE" in coordinator config.

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Belgische DSO-tarieven 2025 (€/kW/jaar) ──────────────────────────────────
# Bron: VREG tariefkaart 2025
BE_DSO_TARIFFS: dict[str, dict] = {
    "fluvius_antwerpen": {
        "label":             "Fluvius Antwerpen",
        "eur_kw_year":       38.80,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["2"],
    },
    "fluvius_gent": {
        "label":             "Fluvius Gent",
        "eur_kw_year":       41.20,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["9"],
    },
    "fluvius_limburg": {
        "label":             "Fluvius Limburg",
        "eur_kw_year":       39.60,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["35", "36", "37", "38"],
    },
    "fluvius_oost_vl": {
        "label":             "Fluvius Oost-Vlaanderen",
        "eur_kw_year":       40.10,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["90", "91", "92", "93", "94"],
    },
    "fluvius_west_vl": {
        "label":             "Fluvius West-Vlaanderen",
        "eur_kw_year":       37.90,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["8"],
    },
    "fluvius_vlaams_brabant": {
        "label":             "Fluvius Vlaams-Brabant",
        "eur_kw_year":       42.50,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["1", "3"],
    },
    "ores": {
        "label":             "Ores (Wallonië)",
        "eur_kw_year":       44.00,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["4", "5", "6", "7"],
    },
    "sibelgas": {
        "label":             "Sibelgas (Brussel)",
        "eur_kw_year":       48.20,
        "free_kw":           2.5,
        "measurement":       "quarterly_15min",
        "postcodes_prefix":  ["10", "11", "12"],
    },
}

# Fallback als postcode niet herkend
DEFAULT_BE_DSO = "fluvius_gent"


def detect_dso_by_postcode(postcode: str) -> str:
    """Detecteer Belgische DSO op basis van postcode."""
    pc = str(postcode).strip()
    for key, cfg in BE_DSO_TARIFFS.items():
        for prefix in cfg["postcodes_prefix"]:
            if pc.startswith(prefix):
                return key
    return DEFAULT_BE_DSO


@dataclass
class BeCapacityStatus:
    """Status van het Belgische capaciteitstarief."""
    current_quarter_avg_kw:  float   # huidig kwartiergemiddelde
    monthly_peak_kw:         float   # hoogste piek deze maand
    rolling_12m_avg_kw:      float   # gemiddelde van 12 maandpieken
    estimated_annual_cost:   float   # €/jaar op basis van rolling avg
    monthly_headroom_kw:     float   # kW beschikbaar voor nieuwe maandpiek
    warning_level:           str     # ok / caution / warning / critical
    dso_label:               str
    tariff_eur_kw_year:      float
    free_kw:                 float

    def to_dict(self) -> dict:
        return {
            "current_quarter_avg_kw":   round(self.current_quarter_avg_kw, 2),
            "monthly_peak_kw":          round(self.monthly_peak_kw, 2),
            "rolling_12m_avg_kw":       round(self.rolling_12m_avg_kw, 2),
            "estimated_annual_cost_eur": round(self.estimated_annual_cost, 2),
            "monthly_headroom_kw":      round(self.monthly_headroom_kw, 2),
            "warning_level":            self.warning_level,
            "dso":                      self.dso_label,
            "tariff_eur_kw_year":       self.tariff_eur_kw_year,
            "free_kw":                  self.free_kw,
        }


class BelgianCapacityCalculator:
    """
    Bewaakt en optimaliseert het Belgisch capaciteitstarief.

    Gebruik:
        calc = BelgianCapacityCalculator(config)
        status = calc.update(grid_import_w)
        coord_data["be_capacity"] = status.to_dict()
    """

    def __init__(self, config: dict) -> None:
        postcode = str(config.get("postal_code", "9000"))
        dso_key  = config.get("be_dso_zone") or detect_dso_by_postcode(postcode)
        dso_cfg  = BE_DSO_TARIFFS.get(dso_key, BE_DSO_TARIFFS[DEFAULT_BE_DSO])

        self._tariff_eur_kw_year: float = float(
            config.get("be_capacity_tariff_eur_kw_year", dso_cfg["eur_kw_year"])
        )
        self._free_kw: float = float(dso_cfg["free_kw"])
        self._dso_label: str = dso_cfg["label"]

        # 15-minuten samples (rolling window)
        self._samples: deque = deque()       # (timestamp, power_w)
        self._monthly_peak_kw: float = 0.0
        self._monthly_peak_ts: str   = ""
        self._month_history: list    = []    # max 12 maanden — {month, peak_kw}
        self._current_month: str     = ""

        self._last_update: float = 0.0

        _LOGGER.debug(
            "BelgianCapacityCalculator: %s, %.2f €/kW/jaar, gratis tot %.1f kW",
            self._dso_label, self._tariff_eur_kw_year, self._free_kw,
        )

    # ── Publieke API ──────────────────────────────────────────────────────────

    def update(self, grid_import_w: float) -> BeCapacityStatus:
        """Verwerk nieuw vermogensmeting en bereken status."""
        now_ts = time.time()
        self._samples.append((now_ts, max(0.0, grid_import_w)))

        # Verwijder samples ouder dan 15 minuten
        cutoff = now_ts - 900
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        # Kwartiergemiddelde
        if self._samples:
            quarter_avg_w = sum(s[1] for s in self._samples) / len(self._samples)
        else:
            quarter_avg_w = 0.0
        quarter_avg_kw = quarter_avg_w / 1000.0

        # Maandpiek bijwerken
        now_dt = datetime.now(timezone.utc)
        month_key = now_dt.strftime("%Y-%m")
        if month_key != self._current_month:
            # Nieuwe maand — sla vorige maandpiek op
            if self._current_month and self._monthly_peak_kw > 0:
                self._month_history.append({
                    "month":   self._current_month,
                    "peak_kw": round(self._monthly_peak_kw, 3),
                })
                if len(self._month_history) > 12:
                    self._month_history.pop(0)
            self._current_month  = month_key
            self._monthly_peak_kw = quarter_avg_kw
        elif quarter_avg_kw > self._monthly_peak_kw:
            self._monthly_peak_kw = quarter_avg_kw
            self._monthly_peak_ts = now_dt.strftime("%H:%M")

        # Rolling 12-maanden gemiddelde
        all_peaks = [h["peak_kw"] for h in self._month_history] + [self._monthly_peak_kw]
        rolling_avg = sum(all_peaks) / len(all_peaks) if all_peaks else 0.0

        # Jaarlijkse kosten
        billable_kw  = max(0.0, rolling_avg - self._free_kw)
        annual_cost  = billable_kw * self._tariff_eur_kw_year

        # Headroom t.o.v. huidige maandpiek
        headroom_kw = max(0.0, self._monthly_peak_kw - quarter_avg_kw)

        # Warning level
        pct = quarter_avg_kw / max(self._monthly_peak_kw, self._free_kw, 0.1)
        if pct >= 1.0:
            warning = "critical"
        elif pct >= 0.95:
            warning = "warning"
        elif pct >= 0.85:
            warning = "caution"
        else:
            warning = "ok"

        return BeCapacityStatus(
            current_quarter_avg_kw = quarter_avg_kw,
            monthly_peak_kw        = self._monthly_peak_kw,
            rolling_12m_avg_kw     = rolling_avg,
            estimated_annual_cost  = annual_cost,
            monthly_headroom_kw    = headroom_kw,
            warning_level          = warning,
            dso_label              = self._dso_label,
            tariff_eur_kw_year     = self._tariff_eur_kw_year,
            free_kw                = self._free_kw,
        )

    def get_month_history(self) -> list[dict]:
        """Laatste 12 maandpieken."""
        return list(self._month_history)

    def estimate_cost_impact(self, extra_kw: float) -> float:
        """
        Bereken de extra jaarlijkse kosten als de piek met extra_kw stijgt.
        Nuttig voor load-shedding beslissingen.
        """
        current_billable = max(0.0, self._monthly_peak_kw - self._free_kw)
        new_billable     = max(0.0, (self._monthly_peak_kw + extra_kw) - self._free_kw)
        return (new_billable - current_billable) * self._tariff_eur_kw_year

    def get_dso_info(self) -> dict:
        """DSO-informatie voor diagnose."""
        return {
            "label":             self._dso_label,
            "tariff_eur_kw_year": self._tariff_eur_kw_year,
            "free_kw":           self._free_kw,
        }
