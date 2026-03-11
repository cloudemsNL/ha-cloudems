# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Capaciteitstarief Piekbewaker (v3.0).

Bewaakt de 15-minuten gemiddelde vermogenspiek (kW) en vergelijkt deze
met de hoogste piek van de lopende maand. Stuurt een waarschuwing als
de huidige kwartier-piek dreigt de maandpiek te overtreffen.

Nieuw in v3.0:
  • Automatische maandreset (geen handmatig resetten meer nodig)
  • Projectie eindpiek op basis van huidig kwartierverloop
  • Gerangschikte load-shedding acties met urgentieniveau
  • 12-maanden piekhistoriek met kostenindicatie
  • Headroom: hoeveel W is er nog beschikbaar zonder nieuwe piek

Relevant voor:
  • België (capaciteitstarief al actief)
  • Nederland (Liander/Enexis capaciteitstarief actief per 2025)
  • Iedereen met een slimme meter en piekgevoeligheid

Output:
  sensor.cloudems_kwartier_piek  →  huidig kwartier-gemiddelde (W)
  Attributen:
    month_peak_w:       hoogste kwartier-piek deze maand (W)
    threshold_w:        geconfigureerde drempel (default: month_peak_w)
    warning_active:     bool — dreigt piek te worden overschreden
    warning_level:      'ok' | 'caution' | 'warning' | 'critical'
    minutes_remaining:  minuten resterend in huidig kwartier
    projected_end_w:    geschatte eindpiek kwartier bij huidig verloop (W)
    headroom_w:         W beschikbaar zonder nieuwe maandpiek te zetten
    shed_actions:       gerangschikte acties om piek te verlagen
    cost_impact_eur:    geschatte kostenstijging als piek overschreden wordt
    month_history:      laatste 12 maanden [{month, peak_kw, cost_eur_month}]
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

_SAVE_INTERVAL = 600   # seconden tussen saves

WINDOW_SECONDS  = 900   # 15 minuten
WARN_MARGIN_W   = 200   # Waarschuw als we binnen 200 W van de piek zitten
SAMPLE_INTERVAL = 30    # seconden tussen metingen

# Fallback NL waarden (worden overschreven door CAPACITY_TARIFF_CONFIG per land)
CAPACITY_TARIFF_EUR_PER_KW_MONTH = 4.37


def _get_tariff_config(country: str) -> dict:
    """Haal capaciteitstarief config op voor het opgegeven land."""
    try:
        from ..const import CAPACITY_TARIFF_CONFIG
        return CAPACITY_TARIFF_CONFIG.get(country, CAPACITY_TARIFF_CONFIG.get("NL", {}))
    except ImportError:
        return {"enabled": True, "threshold_kw": 2.5, "cost_per_kw_month": 4.37, "currency": "EUR"}


class CapacityPeakMonitor:
    """
    Bewaakt 15-minuten vermogenspiek en vergelijkt met maandpiek.

    Gebruik in coordinator:
        cpm = CapacityPeakMonitor(config)
        status = cpm.update(grid_import_w, sheddable_loads_w=ev_w + boiler_w)
    """

    def __init__(self, config: dict) -> None:
        self._config           = config
        self._samples: deque   = deque()  # (timestamp, power_w)
        self._month_peak_w     = 0.0
        self._month_peak_date  = ""
        self._warn_margin      = float(config.get("capacity_warn_margin_w", WARN_MARGIN_W))
        self._custom_threshold = config.get("capacity_threshold_w")
        self._month_history: dict = {}   # "YYYY-MM" → peak_w
        self._current_month   = ""
        # Land-specifieke tarief configuratie
        country = config.get("energy_prices_country", "NL")
        self._tariff_cfg = _get_tariff_config(country)
        # Drempel uit land-config als geen aangepaste drempel
        if not self._custom_threshold and self._tariff_cfg.get("threshold_kw"):
            self._capacity_threshold_kw = float(self._tariff_cfg["threshold_kw"])
        else:
            self._capacity_threshold_kw = 2.5  # fallback
        self._cost_per_kw = float(self._tariff_cfg.get("cost_per_kw_month") or CAPACITY_TARIFF_EUR_PER_KW_MONTH)
        self._currency    = self._tariff_cfg.get("currency", "EUR")
        self._tariff_enabled = bool(self._tariff_cfg.get("enabled", True))
        # Persistence
        self._hass       = config.get("_hass")   # geïnjecteerd door coordinator
        self._store      = None
        self._dirty      = False
        self._last_save  = 0.0

    async def async_setup(self, hass=None) -> None:
        """Laad opgeslagen piekhistorie en maandpiek na herstart."""
        from homeassistant.helpers.storage import Store
        _hass = hass or self._hass
        if not _hass:
            return
        self._store = Store(_hass, 1, "cloudems_capacity_peak_v1")
        try:
            data = await self._store.async_load() or {}
            self._month_history  = data.get("month_history", {})
            self._month_peak_w   = float(data.get("month_peak_w", 0.0))
            self._month_peak_date = data.get("month_peak_date", "")
            self._current_month  = data.get("current_month", "")
            _LOGGER.info(
                "CapacityPeakMonitor: geladen — %d maanden, piek=%.0f W",
                len(self._month_history), self._month_peak_w,
            )
        except Exception as exc:
            _LOGGER.warning("CapacityPeakMonitor: laden mislukt: %s", exc)

    async def async_maybe_save(self) -> None:
        """Sla piekhistorie op (dirty-flag + rate-limit)."""
        if not self._store or not self._dirty:
            return
        now = time.time()
        if now - self._last_save < _SAVE_INTERVAL:
            return
        try:
            await self._store.async_save({
                "month_history":  self._month_history,
                "month_peak_w":   self._month_peak_w,
                "month_peak_date": self._month_peak_date,
                "current_month":  self._current_month,
            })
            self._dirty     = False
            self._last_save = now
        except Exception as exc:
            _LOGGER.warning("CapacityPeakMonitor: opslaan mislukt: %s", exc)

    def update(self, power_w: float, sheddable_loads_w: float = 0.0) -> dict:
        """
        Voeg een vermogensmeting toe en bereken de piekstatus.

        Args:
            power_w:           Huidig net-verbruik (W), positief = import.
            sheddable_loads_w: Totaal vermogen van uitschakelbare lasten (W),
                               bijv. EV-lader + boiler. Gebruikt voor advies.

        Returns:
            dict met alle piekstatus-velden (zie module-docstring).
        """
        now       = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")

        # ── Automatische maandreset ──────────────────────────────────────────
        if month_key != self._current_month:
            if self._current_month and self._month_peak_w > 0:
                self._month_history[self._current_month] = round(self._month_peak_w, 0)
                if len(self._month_history) > 12:
                    del self._month_history[min(self._month_history)]
                self._dirty = True
            self._month_peak_w    = 0.0
            self._month_peak_date = ""
            self._current_month   = month_key
            _LOGGER.info("CapacityPeakMonitor: nieuwe maand %s — piek gereset", month_key)

        # ── Samples bijhouden ────────────────────────────────────────────────
        self._samples.append((now.timestamp(), power_w))
        cutoff = now.timestamp() - WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if not self._samples:
            return self._status(0.0, 0.0, sheddable_loads_w, now)

        # ── Kwartier-gemiddelde ──────────────────────────────────────────────
        avg_w = sum(s[1] for s in self._samples) / len(self._samples)

        # ── Projectie eindpiek ───────────────────────────────────────────────
        # Gewogen combinatie: gemiddelde tot nu (verstreken fractie)
        # + huidig vermogen (resterende fractie)
        elapsed_s     = now.minute % 15 * 60 + now.second
        fraction_done = min(1.0, elapsed_s / WINDOW_SECONDS)
        if fraction_done > 0.05:
            projected_w = avg_w * fraction_done + power_w * (1.0 - fraction_done)
        else:
            projected_w = power_w  # Eerste samples — nog niet betrouwbaar

        # ── Maandpiek bijwerken ──────────────────────────────────────────────
        if avg_w > self._month_peak_w:
            self._month_peak_w    = avg_w
            self._month_peak_date = now.strftime("%Y-%m-%d %H:%M")
            self._dirty = True

        return self._status(avg_w, projected_w, sheddable_loads_w, now)

    def reset_month_peak(self) -> None:
        """Reset de maandpiek handmatig (bijv. bij een foutieve meting)."""
        _LOGGER.info(
            "CapacityPeakMonitor: maandpiek handmatig gereset (was %.0f W)",
            self._month_peak_w,
        )
        self._month_peak_w    = 0.0
        self._month_peak_date = ""

    # ── Interne helpers ───────────────────────────────────────────────────────

    def _status(self, avg_w: float, projected_w: float,
                sheddable_w: float, now: datetime) -> dict:
        threshold = float(self._custom_threshold or self._month_peak_w or 0)

        # Resterend in kwartier
        elapsed_s       = now.minute % 15 * 60 + now.second
        remaining_s     = WINDOW_SECONDS - elapsed_s
        remaining_min   = round(remaining_s / 60, 1)

        # Headroom
        headroom_w = max(0.0, threshold - avg_w) if threshold > 0 else 9999.0

        # Waarschuwingsniveau
        if threshold <= 0:
            warn_level, warn_active = "ok", False
        elif avg_w >= threshold:
            warn_level, warn_active = "critical", True
        elif avg_w >= threshold - self._warn_margin / 2:
            warn_level, warn_active = "warning", True
        elif avg_w >= threshold - self._warn_margin:
            warn_level, warn_active = "caution", True
        else:
            warn_level, warn_active = "ok", False

        # Kostenwaarschuwing: extra kosten als eindpiek boven drempel
        cost_impact = 0.0
        if threshold > 0 and projected_w > threshold:
            overshoot_kw = (projected_w - threshold) / 1000.0
            cost_impact  = round(overshoot_kw * self._cost_per_kw, 2)

        return {
            "current_avg_w":     round(avg_w, 0),
            "projected_end_w":   round(projected_w, 0),
            "month_peak_w":      round(self._month_peak_w, 0),
            "month_peak_date":   self._month_peak_date,
            "threshold_w":       round(threshold, 0),
            "warn_margin_w":     self._warn_margin,
            "warning_active":    warn_active,
            "warning_level":     warn_level,
            "minutes_remaining": remaining_min,
            "headroom_w":        round(headroom_w, 0),
            "shed_actions":      self._shed_actions(avg_w, threshold, remaining_min, sheddable_w),
            "cost_impact_eur":   cost_impact,
            "cost_currency":     self._currency,
            "capacity_tariff_enabled": self._tariff_enabled,
            "sample_count":      len(self._samples),
            "month_history":     self._month_history,
        }

    def _shed_actions(self, current_w: float, threshold_w: float,
                      remaining_min: float, sheddable_w: float) -> list:
        """
        Gerangschikte load-shedding acties, meest comfortabel eerst.

        Urgentieniveaus:
          advisory — meer dan 8 minuten, preventief advies
          soon     — 3–8 minuten, actie gewenst
          now      — minder dan 3 minuten, direct handelen
        """
        if threshold_w <= 0 or current_w < threshold_w - self._warn_margin:
            return []

        urgency = "now" if remaining_min < 3 else ("soon" if remaining_min < 8 else "advisory")
        needed  = max(0.0, current_w - (threshold_w - self._warn_margin / 2))
        actions = []

        if sheddable_w > 0:
            actions.append({
                "action":   "reduce_flexible_loads",
                "label":    f"Schakelbare lasten verlagen (~{sheddable_w:.0f} W beschikbaar)",
                "priority": 1,
                "saves_w":  round(sheddable_w, 0),
                "urgency":  urgency,
            })
        actions.append({
            "action":   "pause_ev_charging",
            "label":    "EV-lader pauzeren (tot 7400 W, 1-fase 32 A)",
            "priority": 2,
            "saves_w":  7400,
            "urgency":  urgency,
        })
        if sheddable_w > 0:
            actions.append({
                "action":   "defer_boiler",
                "label":    f"Boiler uitstellen (~{sheddable_w:.0f} W)",
                "priority": 3,
                "saves_w":  round(sheddable_w, 0),
                "urgency":  urgency,
            })
        if remaining_min < 5 and current_w > threshold_w:
            actions.append({
                "action":   "emergency_shed",
                "label":    "Noodshedding: schakel alle niet-kritieke lasten uit",
                "priority": 4,
                "saves_w":  round(sheddable_w + 7400, 0),
                "urgency":  "now",
            })

        return actions

    def get_monthly_summary(self) -> list:
        """Geeft piekhistoriek van de laatste 12 maanden inclusief lopende maand."""
        result = []
        if self._current_month and self._month_peak_w > 0:
            result.append({
                "month":            self._current_month + " ▶",
                "peak_w":           round(self._month_peak_w, 0),
                "peak_kw":          round(self._month_peak_w / 1000.0, 2),
                "cost_eur_month":   round(
                    (self._month_peak_w / 1000.0) * self._cost_per_kw, 2),
            })
        for month, peak_w in sorted(self._month_history.items(), reverse=True):
            result.append({
                "month":          month,
                "peak_w":         peak_w,
                "peak_kw":        round(peak_w / 1000.0, 2),
                "cost_eur_month": round(
                    (peak_w / 1000.0) * self._cost_per_kw, 2),
            })
        return result
