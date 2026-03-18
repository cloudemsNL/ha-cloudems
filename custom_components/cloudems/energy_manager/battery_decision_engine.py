# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
battery_decision_engine.py — CloudEMS v4.0.2
=============================================
Centrale beslisser voor batterijsturing.

Prioriteitsvolgorde (hoog → laag):
  1. Veiligheidsgrenzen (SOC min/max, SoH-plafond, PV surplus)
  1b. Peak shaving (capaciteitstarief bescherming)
  2. Tariefgroep HIGH → ontladen / LOW → laden
  3. EPEX goedkoopste/duurste uren
  4. PV forecast morgen hoog → avond ontladen (ruimte maken)
  5. Default idle

v4.0.2:
  - Laag 1b: peak shaving — batterij ontladen als grid > limiet
  - target_soc_pct op elke beslissing
  - DecisionContext uitgebreid: peak_shaving_active, grid_import_w, grid_peak_limit_w
  - explain() toont nu ook peak shaving status
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
MIN_SOC_DISCHARGE   = 15.0   # % — nooit onder dit niveau ontladen
MAX_SOC_CHARGE      = 95.0   # % — nooit boven dit laden (default)
SOC_FULL_THRESHOLD  = 90.0
SOC_LOW_THRESHOLD   = 25.0

PRICE_CHEAP_EUR     = 0.10
PRICE_EXPENSIVE_EUR = 0.25

PV_SURPLUS_MIN_W    = 500.0
MIN_USEFUL_CAPACITY_KWH = 0.5

# Peak shaving: minimale SOC die we bewaren als reserve voor piek
PEAK_SHAVING_RESERVE_SOC = 20.0


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class BatteryDecision:
    action:        str             # "charge" | "discharge" | "idle"
    reason:        str
    priority:      int             # 1=veiligheid, 1b=peak, 2=tariefgroep, 3=EPEX, 4=PV, 5=default
    confidence:    float           # 0.0–1.0
    source:        str
    soc_pct:       Optional[float] = None
    target_soc_pct:Optional[float] = None  # doelwaarde (bijv. 80% voor nachtlading)
    tariff_group:  str             = "normal"
    epex_eur:      Optional[float] = None
    extras:        dict            = field(default_factory=dict)

    @property
    def is_charging(self) -> bool:
        return self.action == "charge"

    @property
    def is_discharging(self) -> bool:
        return self.action == "discharge"

    @property
    def should_execute(self) -> bool:
        """True als confidence hoog genoeg is om daadwerkelijk uit te voeren."""
        return self.confidence >= 0.75 and self.action != "idle"


@dataclass
class DecisionContext:
    soc_pct:                  Optional[float] = None
    soh_pct:                  Optional[float] = None
    epex_eur_now:             Optional[float] = None
    epex_forecast:            list            = field(default_factory=list)
    tariff_group:             str             = "normal"
    tariff_forecast:          list            = field(default_factory=list)
    pv_surplus_w:             float           = 0.0
    pv_forecast_today_kwh:    float           = 0.0
    pv_forecast_tomorrow_kwh: float           = 0.0
    pv_forecast_hourly:       list            = field(default_factory=list)
    concurrent_load_w:        float           = 0.0
    battery_capacity_kwh:     float           = 10.0
    max_charge_w:             float           = 3000.0
    max_discharge_w:          float           = 3000.0
    current_hour:             int             = 12
    season:                   str             = "transition"
    # v4.0.2: peak shaving
    peak_shaving_active:      bool            = False
    # v4.0.4: off-peak tarief
    off_peak_active:          bool            = False
    grid_import_w:            float           = 0.0
    grid_peak_limit_w:        float           = 0.0   # 0 = geen limiet geconfigureerd
    # v4.6.416: verwacht resterend verbruik vandaag (uit energy_demand module)
    # Gebruikt om te bepalen of accu genoeg heeft voor rest van de dag
    expected_remaining_kwh:   float           = 0.0   # device + systeem vraag rest dag
    system_demand_kwh:        float           = 0.0   # boiler + zones + EV (doel-gebaseerd)


# ── Engine ────────────────────────────────────────────────────────────────────

class BatteryDecisionEngine:
    """
    Centrale beslisser voor batterijsturing.

    Gebruik:
        engine = BatteryDecisionEngine()
        decision = engine.evaluate(ctx)
        lines    = engine.explain(ctx)
    """

    def evaluate(self, ctx: DecisionContext) -> BatteryDecision:
        soc = ctx.soc_pct
        tg  = (ctx.tariff_group or "normal").lower().strip()
        ceil = self._charge_ceiling(ctx.soh_pct)

        # v4.5.12: log waarschuwing als SoC niet beschikbaar is — batterijsturing is dan blind.
        if soc is None:
            _LOGGER.warning(
                "BatteryDecisionEngine: soc_pct is None — "
                "koppel een SoC-sensor (entity_id) aan de batterijconfiguratie in CloudEMS. "
                "Optimalisatie op basis van laadtoestand is uitgeschakeld."
            )

        available_kwh = (
            max(0.0, (soc - MIN_SOC_DISCHARGE) / 100.0 * ctx.battery_capacity_kwh)
            if soc is not None else 0.0
        )
        headroom_kwh = (
            max(0.0, (ceil - soc) / 100.0 * ctx.battery_capacity_kwh)
            if soc is not None else ctx.battery_capacity_kwh
        )
        # v4.6.416: demand-bewuste beschikbaarheid
        # Als verwacht verbruik > beschikbare kWh → reserveer marge voor laden
        _total_demand = ctx.expected_remaining_kwh + ctx.system_demand_kwh
        _demand_gap   = max(0.0, _total_demand - available_kwh)
        _needs_charge = _demand_gap > 0.5  # meer dan 500Wh tekort

        # Laag 1: veiligheidsgrenzen
        d = self._check_safety(ctx, soc, ceil, available_kwh, headroom_kwh)
        if d: return d

        # Laag 1b: peak shaving
        d = self._check_peak_shaving(ctx, soc, available_kwh)
        if d: return d

        # Laag 2: tariefgroep
        d = self._check_tariff_group(ctx, tg, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3: EPEX
        d = self._check_epex(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3b: off-peak tarief (als geen EPEX signal)
        d = self._check_off_peak(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 4: PV forecast
        d = self._check_pv(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 5: default idle
        return BatteryDecision(
            action="idle",
            reason="Geen actief signaal — wachten op goedkopere/duurdere uren",
            priority=5,
            confidence=0.5,
            source="default",
            soc_pct=soc,
            tariff_group=tg,
            epex_eur=ctx.epex_eur_now,
        )

    # ── Laag 1: Veiligheid ────────────────────────────────────────────────────

    def _check_safety(self, ctx, soc, ceil, available_kwh, headroom_kwh):
        tg = (ctx.tariff_group or "normal").lower()

        if soc is not None and soc <= MIN_SOC_DISCHARGE:
            return BatteryDecision(
                action="idle",
                reason=f"Veiligheidsgrens: SOC {soc:.0f}% ≤ minimum {MIN_SOC_DISCHARGE:.0f}%",
                priority=1, confidence=1.0, source="safety_soc_min",
                soc_pct=soc, tariff_group=tg,
            )
        if soc is not None and soc >= ceil:
            return BatteryDecision(
                action="idle",
                reason=f"Vol: SOC {soc:.0f}% ≥ plafond {ceil:.0f}%",
                priority=1, confidence=1.0, source="safety_soc_max",
                soc_pct=soc, tariff_group=tg,
            )
        if ctx.pv_surplus_w > ctx.max_charge_w * 0.8:
            return BatteryDecision(
                action="idle",
                reason=f"PV surplus {ctx.pv_surplus_w:.0f}W laadt batterij al via zelfverbruik",
                priority=1, confidence=0.9, source="safety_pv_surplus",
                soc_pct=soc, tariff_group=tg,
            )
        return None

    # ── Laag 1b: Peak shaving ─────────────────────────────────────────────────

    def _check_peak_shaving(self, ctx, soc, available_kwh):
        """
        Als grid-import boven de piek-limiet uitkomt EN de batterij genoeg
        heeft (boven reserve), dan ontladen om de piek te dempen.
        """
        if not ctx.peak_shaving_active:
            return None
        if ctx.grid_peak_limit_w <= 0:
            return None
        if ctx.grid_import_w <= ctx.grid_peak_limit_w:
            return None

        tg = (ctx.tariff_group or "normal").lower()
        excess_w = ctx.grid_import_w - ctx.grid_peak_limit_w

        # Genoeg reserve? SOC moet boven PEAK_SHAVING_RESERVE_SOC zitten
        if soc is not None and soc <= PEAK_SHAVING_RESERVE_SOC:
            return BatteryDecision(
                action="idle",
                reason=f"Piek {ctx.grid_import_w:.0f}W > limiet {ctx.grid_peak_limit_w:.0f}W "
                       f"maar SOC {soc:.0f}% ≤ reserve {PEAK_SHAVING_RESERVE_SOC:.0f}%",
                priority=2,   # zelfde prio als tariefgroep — komt na veiligheid
                confidence=0.85,
                source="peak_shaving_reserve",
                soc_pct=soc,
                tariff_group=tg,
                extras={"grid_import_w": ctx.grid_import_w, "peak_limit_w": ctx.grid_peak_limit_w},
            )

        if available_kwh < MIN_USEFUL_CAPACITY_KWH:
            return None

        return BatteryDecision(
            action="discharge",
            reason=f"Peak shaving: {ctx.grid_import_w:.0f}W > limiet {ctx.grid_peak_limit_w:.0f}W "
                   f"(+{excess_w:.0f}W) — batterij ontladen",
            priority=2,
            confidence=0.92,
            source="peak_shaving",
            soc_pct=soc,
            target_soc_pct=PEAK_SHAVING_RESERVE_SOC,
            tariff_group=tg,
            extras={
                "grid_import_w": ctx.grid_import_w,
                "peak_limit_w":  ctx.grid_peak_limit_w,
                "excess_w":      excess_w,
            },
        )

    # ── Laag 2: Tariefgroep ───────────────────────────────────────────────────

    def _check_tariff_group(self, ctx, tg, soc, available_kwh, headroom_kwh):
        if tg == "high":
            if available_kwh >= MIN_USEFUL_CAPACITY_KWH:
                upcoming_low = "low" in ctx.tariff_forecast[:3]
                if upcoming_low and soc is not None and soc < 60:
                    return BatteryDecision(
                        action="idle",
                        reason="HIGH tariefgroep maar LOW verwacht komende uren — lading bewaren",
                        priority=2, confidence=0.7, source="tariff_high_hold",
                        soc_pct=soc, tariff_group=tg, epex_eur=ctx.epex_eur_now,
                    )
                return BatteryDecision(
                    action="discharge",
                    reason=f"HIGH tariefgroep — ontladen ({available_kwh:.1f} kWh beschikbaar)",
                    priority=2, confidence=0.85, source="tariff_high",
                    soc_pct=soc, target_soc_pct=MIN_SOC_DISCHARGE + 5,
                    tariff_group=tg, epex_eur=ctx.epex_eur_now,
                )
            return BatteryDecision(
                action="idle",
                reason=f"HIGH tariefgroep maar te weinig lading ({available_kwh:.1f} kWh)",
                priority=2, confidence=0.8, source="tariff_high_empty",
                soc_pct=soc, tariff_group=tg,
            )

        if tg == "low":
            if headroom_kwh >= MIN_USEFUL_CAPACITY_KWH:
                return BatteryDecision(
                    action="charge",
                    reason=f"LOW tariefgroep — laden ({headroom_kwh:.1f} kWh ruimte)",
                    priority=2, confidence=0.85, source="tariff_low",
                    soc_pct=soc, target_soc_pct=self._charge_ceiling(ctx.soh_pct),
                    tariff_group=tg, epex_eur=ctx.epex_eur_now,
                )
        return None

    # ── Laag 3: EPEX ─────────────────────────────────────────────────────────

    def _check_epex(self, ctx, soc, available_kwh, headroom_kwh):
        price = ctx.epex_eur_now
        tg    = (ctx.tariff_group or "normal").lower()
        if price is None:
            return None

        if price <= PRICE_CHEAP_EUR and headroom_kwh >= MIN_USEFUL_CAPACITY_KWH:
            if ctx.pv_forecast_tomorrow_kwh > ctx.battery_capacity_kwh * 0.7:
                if soc is not None and soc > 50:
                    return BatteryDecision(
                        action="idle",
                        reason=f"Goedkoop (€{price:.3f}) maar morgen veel zon "
                               f"({ctx.pv_forecast_tomorrow_kwh:.1f} kWh) — niet volladen",
                        priority=3, confidence=0.65, source="epex_cheap_pv_tomorrow",
                        soc_pct=soc, tariff_group=tg, epex_eur=price,
                    )
            ceil = self._charge_ceiling(ctx.soh_pct)
            return BatteryDecision(
                action="charge",
                reason=f"EPEX goedkoop €{price:.3f}/kWh ≤ {PRICE_CHEAP_EUR:.2f} — laden",
                priority=3, confidence=0.75, source="epex_cheap",
                soc_pct=soc, target_soc_pct=ceil,
                tariff_group=tg, epex_eur=price,
            )

        if price >= PRICE_EXPENSIVE_EUR and available_kwh >= MIN_USEFUL_CAPACITY_KWH:
            return BatteryDecision(
                action="discharge",
                reason=f"EPEX duur €{price:.3f}/kWh ≥ {PRICE_EXPENSIVE_EUR:.2f} — ontladen",
                priority=3, confidence=0.70, source="epex_expensive",
                soc_pct=soc, target_soc_pct=MIN_SOC_DISCHARGE + 5,
                tariff_group=tg, epex_eur=price,
            )
        return None

    # ── Laag 3b: Off-peak tarief ─────────────────────────────────────────────

    def _check_off_peak(self, ctx, soc, available_kwh, headroom_kwh):
        """
        Als een dal-tarief gedetecteerd is en we in een dal-uur zitten,
        laden — tenzij EPEX al een signal gaf (priority 3 is al afgehandeld).
        """
        if not ctx.off_peak_active:
            return None
        # Alleen als er nog ruimte is én EPEX gaf geen goedkoop-signaal
        # (EPEX-laag is al voorbij, dus hier zitten we > PRICE_CHEAP_EUR)
        tg = (ctx.tariff_group or "normal").lower()
        if headroom_kwh >= MIN_USEFUL_CAPACITY_KWH:
            ceil = self._charge_ceiling(ctx.soh_pct)
            return BatteryDecision(
                action="charge",
                reason="Dal-tariefuur gedetecteerd — laden voor piek",
                priority=3,
                confidence=0.70,
                source="off_peak_tariff",
                soc_pct=soc,
                target_soc_pct=ceil,
                tariff_group=tg,
            )
        return None

    # ── Laag 4: PV forecast ───────────────────────────────────────────────────

    def _check_pv(self, ctx, soc, available_kwh, headroom_kwh):
        tg = (ctx.tariff_group or "normal").lower()
        if (
            ctx.current_hour >= 19
            and ctx.pv_forecast_tomorrow_kwh > ctx.battery_capacity_kwh * 0.8
            and soc is not None and soc > 60
            and available_kwh >= MIN_USEFUL_CAPACITY_KWH
        ):
            return BatteryDecision(
                action="discharge",
                reason=f"Morgen {ctx.pv_forecast_tomorrow_kwh:.1f} kWh PV — "
                       f"avond ontladen voor ruimte",
                priority=4, confidence=0.60, source="pv_tomorrow_makeroom",
                soc_pct=soc, target_soc_pct=30.0,
                tariff_group=tg,
                extras={"pv_tomorrow_kwh": ctx.pv_forecast_tomorrow_kwh},
            )
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _charge_ceiling(soh_pct: Optional[float]) -> float:
        if soh_pct is None:
            return MAX_SOC_CHARGE
        if soh_pct < 70.0: return 75.0
        if soh_pct < 80.0: return 80.0
        if soh_pct < 90.0: return 85.0
        return MAX_SOC_CHARGE

    def explain(self, ctx: DecisionContext) -> list[str]:
        """Volledige uitleg van alle lagen voor het dashboard."""
        soc   = ctx.soc_pct
        tg    = (ctx.tariff_group or "normal").lower()
        price = ctx.epex_eur_now
        ceil  = self._charge_ceiling(ctx.soh_pct)
        avail = max(0.0, (soc - MIN_SOC_DISCHARGE) / 100.0 * ctx.battery_capacity_kwh) if soc is not None else 0
        head  = max(0.0, (ceil - soc) / 100.0 * ctx.battery_capacity_kwh) if soc is not None else 0

        # v4.6.416: demand-info in uitleg
        _td   = ctx.expected_remaining_kwh + ctx.system_demand_kwh
        _gap  = max(0.0, _td - avail)
        lines = [
            f"SOC: {soc:.0f}%{' ✅' if soc is not None and soc > SOC_LOW_THRESHOLD else ' ⚠️'}" if soc is not None else "SOC: onbekend",
            f"Laadplafond: {ceil:.0f}% (SoH: {ctx.soh_pct:.0f}%)" if ctx.soh_pct else f"Laadplafond: {ceil:.0f}%",
            f"Beschikbaar: {avail:.1f} kWh | Ruimte: {head:.1f} kWh",
            *([ f"⚡ Verwacht verbruik: {_td:.1f} kWh (devices {ctx.expected_remaining_kwh:.1f} + systemen {ctx.system_demand_kwh:.1f}) — {'tekort {:.1f} kWh'.format(_gap) if _gap > 0.2 else 'voldoende ✅'}" ] if _td > 0.05 else []),
            f"Tariefgroep: {tg.upper()}",
            f"EPEX nu: €{price:.3f}/kWh {'🟢' if price is not None and price <= PRICE_CHEAP_EUR else ('🔴' if price is not None and price >= PRICE_EXPENSIVE_EUR else '🟡')}" if price is not None else "EPEX: onbekend",
            f"PV surplus: {ctx.pv_surplus_w:.0f}W",
            f"PV morgen: {ctx.pv_forecast_tomorrow_kwh:.1f} kWh",
            f"Concurrent load: {ctx.concurrent_load_w:.0f}W",
        ]
        if ctx.off_peak_active:
            lines.append("Dal-tarief: 🌙 Actief — laden aanbevolen")
        elif hasattr(ctx, 'off_peak_active'):
            lines.append("Dal-tarief: niet actief / niet gedetecteerd")
        if ctx.peak_shaving_active:
            over = ctx.grid_import_w - ctx.grid_peak_limit_w
            lines.append(
                f"Peak shaving: {ctx.grid_import_w:.0f}W / {ctx.grid_peak_limit_w:.0f}W "
                f"({'🔴 OVER +' + str(round(over)) + 'W' if over > 0 else '🟢 OK'})"
            )
        return lines
