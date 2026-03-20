# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
financial_quality.py — v4.6.533

Twee modules voor financiële kwaliteitsmonitoring:

1. SavingsAttributionTracker
   Meet werkelijke besparingen per CloudEMS-subsysteem.
   Vergelijkt wat het kostte MET CloudEMS vs ZONDER (counterfactual).

2. TariffArbitrageQuality
   Meet hoe goed CloudEMS de prijsspreiding benut op dynamische tarieven.
   Score 0-100%: 0 = willekeurig, 100 = perfect timing.

Beide hebben cloud-sync voor anonieme benchmarking tussen installaties.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cloud_sync_mixin import CloudSyncMixin

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_SAVINGS   = "cloudems_savings_attribution_v1"
STORAGE_KEY_ARBITRAGE = "cloudems_tariff_arbitrage_v1"
STORAGE_VERSION       = 1
EMA_ALPHA   = 0.08
SAVE_INTERVAL = 30


# ─────────────────────────────────────────────────────────────────────────────
# 1. SavingsAttributionTracker
# ─────────────────────────────────────────────────────────────────────────────

SUBSYSTEMS = ["battery", "shutter", "boiler", "ev", "solar_dimmer"]


@dataclass
class SubsystemSavings:
    """Besparingsstatistiek per subsysteem."""
    subsystem:       str
    total_saved_eur: float = 0.0    # cumulatief
    ema_saved_eur_h: float = 0.0    # per uur (EMA)
    events:          int   = 0
    last_event_ts:   float = 0.0

    def to_dict(self) -> dict:
        return {
            "sub":    self.subsystem,
            "total":  round(self.total_saved_eur, 4),
            "ema_h":  round(self.ema_saved_eur_h, 6),
            "events": self.events,
        }

    def from_dict(self, d: dict) -> None:
        self.total_saved_eur = float(d.get("total", 0.0))
        self.ema_saved_eur_h = float(d.get("ema_h", 0.0))
        self.events          = int(d.get("events", 0))


class SavingsAttributionTracker(CloudSyncMixin):
    """
    Meet werkelijke besparingen per subsysteem via counterfactual-analyse.

    Voor elke CloudEMS-actie wordt berekend:
    - Wat het kost MET de actie (werkelijk)
    - Wat het gekost zou hebben ZONDER de actie (counterfactual)
    - Verschil = werkelijke besparing

    Counterfactual-aannames:
    - Batterij: zonder laden/ontladen zou stroom van/naar het net gegaan zijn
    - Boiler: zonder EPEX-sturing zou op duurste uur gestookt zijn
    - EV: zonder smart charging op huidige prijs geladen
    - Rolluiken: zonder sluiting zou koeling meer werk gehad hebben
    """

    _cloud_module_name = "savings_attribution"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._subsystems: Dict[str, SubsystemSavings] = {
            s: SubsystemSavings(subsystem=s) for s in SUBSYSTEMS
        }
        self._store = None
        self._dirty_count = 0
        # Dagelijkse totalen voor trendanalyse
        self._daily_totals: deque = deque(maxlen=90)   # 3 maanden
        self._current_day: Optional[str] = None
        self._day_total: float = 0.0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_SAVINGS)
        data = await self._store.async_load()
        if data:
            for s in SUBSYSTEMS:
                if s in data:
                    self._subsystems[s].from_dict(data[s])
            self._daily_totals = deque(data.get("daily", []), maxlen=90)

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                **{s: self._subsystems[s].to_dict() for s in SUBSYSTEMS},
                "daily": list(self._daily_totals),
            })
            self._dirty_count = 0

    def record_saving(
        self,
        subsystem: str,
        saved_eur: float,
        duration_h: float = 0.0,
    ) -> None:
        """
        Registreer een bewezen besparing voor een subsysteem.
        saved_eur: werkelijke besparing in euro (mag negatief zijn als het duurder was)
        duration_h: duur van de actie in uren
        """
        if subsystem not in self._subsystems:
            return
        s = self._subsystems[subsystem]
        s.total_saved_eur += saved_eur
        if duration_h > 0:
            hourly = saved_eur / duration_h
            s.ema_saved_eur_h = EMA_ALPHA * hourly + (1 - EMA_ALPHA) * s.ema_saved_eur_h
        s.events += 1
        s.last_event_ts = time.time()
        self._dirty_count += 1

        # Dagcumulatief
        import datetime
        today = datetime.date.today().isoformat()
        if today != self._current_day:
            if self._current_day:
                self._daily_totals.append({
                    "date":  self._current_day,
                    "total": round(self._day_total, 4),
                })
            self._current_day = today
            self._day_total   = 0.0
        self._day_total += saved_eur

        if abs(saved_eur) > 0.01:
            _LOGGER.debug(
                "SavingsAttribution: %s +€%.4f (totaal €%.2f)",
                subsystem, saved_eur, s.total_saved_eur,
            )

    def record_battery_cycle(
        self,
        charge_price_eur_kwh: float,
        discharge_price_eur_kwh: float,
        energy_kwh: float,
        efficiency: float = 0.90,
    ) -> float:
        """
        Bereken en registreer besparing van één batterijcyclus.
        Counterfactual: zonder batterij zou alles via grid gegaan zijn.
        Geeft besparing in euro terug.
        """
        # Kosten zonder batterij: laad_energie × ontlaad_prijs (had van grid moeten komen)
        without_cost = energy_kwh * discharge_price_eur_kwh
        # Kosten met batterij: laad_energie × laad_prijs / rendement
        with_cost    = energy_kwh * charge_price_eur_kwh / max(efficiency, 0.5)
        saved        = without_cost - with_cost
        self.record_saving("battery", saved, duration_h=0.5)
        return saved

    def get_total(self) -> float:
        return sum(s.total_saved_eur for s in self._subsystems.values())

    def get_summary(self) -> dict:
        total = self.get_total()
        days_running = (time.time() - self._start_ts) / 86400
        return {
            "total_eur":      round(total, 2),
            "per_subsystem":  {s: round(v.total_saved_eur, 2) for s, v in self._subsystems.items()},
            "eur_per_day":    round(total / max(days_running, 1), 3),
            "days_running":   round(days_running, 1),
            "recent_daily":   list(self._daily_totals)[-7:],   # laatste 7 dagen
        }

    def _get_learned_data(self) -> dict:
        return {
            s: {
                "ema_saved_eur_h": self._round_for_cloud(v.ema_saved_eur_h, 2),
                "events":          v.events,
            }
            for s, v in self._subsystems.items()
            if v.events >= 5
        }

    def _apply_prior(self, data: dict) -> None:
        for s, v in self._subsystems.items():
            if v.events < 5 and s in data:
                prior = float(data[s].get("ema_saved_eur_h", 0.0))
                if prior > 0:
                    v.ema_saved_eur_h = prior * CLOUD_PRIOR_WEIGHT
                    _LOGGER.debug("SavingsAttribution: cloud prior voor %s = €%.6f/h", s, prior)

    def get_diagnostics(self) -> dict:
        return self.get_summary()


# import constant vanuit mixin
try:
    from .cloud_sync_mixin import CLOUD_PRIOR_WEIGHT
except ImportError:
    CLOUD_PRIOR_WEIGHT = 0.2


# ─────────────────────────────────────────────────────────────────────────────
# 2. TariffArbitrageQuality
# ─────────────────────────────────────────────────────────────────────────────

STORAGE_KEY_ARB = "cloudems_arbitrage_quality_v1"
ARB_MIN_SAMPLES = 20
# Venster voor dag-optimum berekening
DAY_PRICES_WINDOW = 24   # 24 uur


@dataclass
class DayArbitrageRecord:
    """Arbitrage-kwaliteit voor één dag."""
    date:           str
    cloudems_score: float   # gemiddeld laadprijs / ontlaadprijs ratio
    optimal_score:  float   # wat perfect zou zijn geweest
    efficiency_pct: float   # cloudems / optimal × 100

    def to_dict(self) -> dict:
        return {
            "d": self.date,
            "cs": round(self.cloudems_score, 4),
            "os": round(self.optimal_score, 4),
            "eff": round(self.efficiency_pct, 1),
        }


class TariffArbitrageQuality(CloudSyncMixin):
    """
    Meet hoe goed CloudEMS de prijsspreiding benut.
    Vergelijkt werkelijke laad/ontlaad-tijden met het theoretisch optimum.
    """

    _cloud_module_name = "tariff_arbitrage_quality"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._ema_efficiency: float = 0.5   # prior: 50%
        self._sample_count:   int   = 0
        self._store = None
        self._dirty_count = 0

        # Dagelijkse prijshistorie voor optimum-berekening
        self._day_prices:  list = []   # [(hour, price)]
        self._day_actions: list = []   # [(hour, action, price)]
        self._current_day: Optional[str] = None
        self._daily_records: deque = deque(maxlen=90)

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_ARB)
        data = await self._store.async_load()
        if data:
            self._ema_efficiency = float(data.get("ema_eff", 0.5))
            self._sample_count   = int(data.get("samples", 0))
            self._daily_records  = deque(
                [d for d in data.get("records", [])],
                maxlen=90,
            )

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save({
                "ema_eff": round(self._ema_efficiency, 4),
                "samples": self._sample_count,
                "records": [r.to_dict() for r in self._daily_records][-30:],
            })
            self._dirty_count = 0

    def tick(
        self,
        hour: int,
        price_eur_kwh: float,
        bde_action: Optional[str] = None,
    ) -> None:
        """
        Aanroepen elke cyclus met huidig uur, prijs en BDE-actie.
        """
        import datetime
        today = datetime.date.today().isoformat()

        if today != self._current_day:
            if self._current_day and self._day_prices and self._day_actions:
                self._finalize_day(self._current_day)
            self._current_day = today
            self._day_prices  = []
            self._day_actions = []

        # Voeg prijs toe (deduplicated per uur)
        if not self._day_prices or self._day_prices[-1][0] != hour:
            self._day_prices.append((hour, price_eur_kwh))

        if bde_action in ("charge", "discharge"):
            self._day_actions.append((hour, bde_action, price_eur_kwh))

    def _finalize_day(self, date: str) -> None:
        """Bereken arbitrage-efficiëntie voor voltooide dag."""
        if len(self._day_prices) < 6 or not self._day_actions:
            return

        prices  = [p for _, p in self._day_prices]
        p_min   = min(prices)
        p_max   = max(prices)
        spread  = p_max - p_min
        if spread < 0.02:
            return   # te kleine spread voor zinvolle meting

        # Optimal score: laad op p_min, ontlaad op p_max
        optimal_score = p_max / max(p_min, 0.001)

        # CloudEMS score: gemiddelde van werkelijke acties
        charge_prices    = [p for _, a, p in self._day_actions if a == "charge"]
        discharge_prices = [p for _, a, p in self._day_actions if a == "discharge"]

        if not charge_prices or not discharge_prices:
            return

        avg_charge    = sum(charge_prices)    / len(charge_prices)
        avg_discharge = sum(discharge_prices) / len(discharge_prices)
        cloudems_score = avg_discharge / max(avg_charge, 0.001)

        efficiency_pct = min(100.0, cloudems_score / optimal_score * 100)

        rec = DayArbitrageRecord(
            date           = date,
            cloudems_score = cloudems_score,
            optimal_score  = optimal_score,
            efficiency_pct = efficiency_pct,
        )
        self._daily_records.append(rec)
        self._ema_efficiency = EMA_ALPHA * (efficiency_pct / 100) + (1 - EMA_ALPHA) * self._ema_efficiency
        self._sample_count  += 1
        self._dirty_count   += 1

        _LOGGER.info(
            "TariffArbitrageQuality: dag %s efficiëntie %.0f%% "
            "(laad %.3f€/kWh → ontlaad %.3f€/kWh, optimaal ratio %.2f)",
            date, efficiency_pct, avg_charge, avg_discharge, optimal_score,
        )

        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "arbitrage_quality",
                    action   = "day_finalized",
                    reason   = date,
                    message  = f"Dag {date}: arbitrage efficiëntie {efficiency_pct:.0f}%",
                    extra    = rec.to_dict(),
                )
            except Exception:
                pass

        # Waarschuw als structureel laag
        if self._sample_count >= ARB_MIN_SAMPLES and self._ema_efficiency < 0.40:
            self._emit_hint()

    def _emit_hint(self) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = "arbitrage_quality_low",
                title      = "Arbitrage-efficiëntie laag",
                message    = (
                    f"CloudEMS benut gemiddeld {self._ema_efficiency*100:.0f}% van de "
                    f"beschikbare prijsspreiding voor batterij-arbitrage. "
                    f"Mogelijke verbeteringen: pas laad/ontlaad-drempels aan, "
                    f"vergroot het gehanteerde prijsverschil (MIN_NET_SPREAD), "
                    f"of controleer de prijsdata-kwaliteit."
                ),
                action     = "Controleer BDE-instellingen en prijsdata",
                confidence = min(0.80, 1.0 - self._ema_efficiency),
            )
        except Exception as _e:
            _LOGGER.debug("ArbitrageQuality hint fout: %s", _e)

    def _get_learned_data(self) -> dict:
        return {
            "ema_efficiency": round(self._ema_efficiency, 3),
            "sample_count":   self._sample_count,
        }

    def _apply_prior(self, data: dict) -> None:
        if self._sample_count < ARB_MIN_SAMPLES:
            prior = float(data.get("ema_efficiency", 0.5))
            self._ema_efficiency = 0.7 * self._ema_efficiency + 0.3 * prior

    def get_diagnostics(self) -> dict:
        return {
            "ema_efficiency_pct": round(self._ema_efficiency * 100, 1),
            "sample_count":       self._sample_count,
            "recent_days":        [r.to_dict() for r in list(self._daily_records)[-7:]],
        }
