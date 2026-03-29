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
import time as _time
import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
MIN_SOC_DISCHARGE   = 15.0   # % — nooit
from ..const import AI_BATTERY_MIN_CONFIDENCE as _AI_MIN_CONFIDENCE_DEFAULT
# AI_MIN_CONFIDENCE is overridden at runtime by ThresholdLearner via set_ai_thresholds()
AI_MIN_CONFIDENCE = _AI_MIN_CONFIDENCE_DEFAULT   # minimum confidence before AI hint influences decisions
AI_PRICE_NUDGE = 0.02  # TODO: make this learnable   # €/kWh threshold adjustment when AI agrees onder dit niveau ontladen
MAX_SOC_CHARGE      = 95.0   # % — nooit boven dit laden (default)
SOC_FULL_THRESHOLD  = 90.0
SOC_LOW_THRESHOLD   = 25.0

from ..const import PRICE_CHEAP_EUR_KWH as _PRICE_CHEAP_DEFAULT, PRICE_EXPENSIVE_EUR_KWH as _PRICE_EXPENSIVE_DEFAULT
# Runtime values — updated from ThresholdLearner via set_ai_thresholds()
PRICE_CHEAP_EUR     = _PRICE_CHEAP_DEFAULT
PRICE_EXPENSIVE_EUR = _PRICE_EXPENSIVE_DEFAULT

PV_SURPLUS_MIN_W    = 500.0
MIN_USEFUL_CAPACITY_KWH = 0.5

# Peak shaving: minimale SOC die we bewaren als reserve voor piek
PEAK_SHAVING_RESERVE_SOC = 20.0


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
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


@dataclass(slots=True)
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
    # v5.4.6: cel-balancering
    cell_balancing_needed:    bool            = False  # True = laad naar 100% deze maand

    # v5.4.5: dispatch planner suggestie
    dispatch_action:          str             = ""     # "charge"/"discharge"/"idle" van planner
    dispatch_target_soc:      Optional[float] = None   # Gewenste SoC dit uur
    # v5.4.13: cost-based optimizer suggestie
    optimizer_action:         str             = ""     # actie van BatteryOptimizer
    optimizer_target_soc:     Optional[float] = None   # target SoC van optimizer
    optimizer_reason:         str             = ""     # uitleg van optimizer

    # v4.6.507: salderingspercentage — bepaalt werkelijke waarde van export vs. self-consumption
    # NL 2026: 0.36, NL 2027+: 0.00, DE/BE/FR: 0.00
    # Beïnvloedt laad/ontlaad drempels: bij 0% saldering is zelf-consumptie veel waardevoller
    net_metering_pct:         float           = 0.0   # 0.0–1.0


# ── Engine ────────────────────────────────────────────────────────────────────

class BatteryDecisionEngine:
    """
    Centrale beslisser voor batterijsturing.

    Gebruik:
        engine = BatteryDecisionEngine()
        engine.set_learner(decision_outcome_learner)   # optioneel
        decision = engine.evaluate(ctx)
        lines    = engine.explain(ctx)
    """

    def __init__(self) -> None:
        self._learner = None   # v4.6.498: DecisionOutcomeLearner — optioneel koppelen
        self._last_action:    str   = "idle"   # laatste batterij actie
        self._last_action_ts: float = 0.0       # timestamp van laatste actiewissel
        self.anti_cycling_min: int  = 10        # minimale minuten tussen actiewissel

    def set_learner(self, learner) -> None:
        """Koppel de DecisionOutcomeLearner voor bias-toepassing op drempels."""

    def set_ai_thresholds(self, threshold_fn) -> None:
        """
        Koppel een threshold-lookup functie (van AIRegistry).
        Daarna gebruikt de engine geleerde drempels i.p.v. vaste defaults.
        threshold_fn('AI_BATTERY_MIN_CONFIDENCE') → float
        """
        global AI_MIN_CONFIDENCE, AI_PRICE_NUDGE, PRICE_CHEAP_EUR, PRICE_EXPENSIVE_EUR
        try:
            AI_MIN_CONFIDENCE   = threshold_fn("AI_BATTERY_MIN_CONFIDENCE")
            AI_PRICE_NUDGE      = threshold_fn("AI_PRICE_NUDGE_EUR_KWH")
            PRICE_CHEAP_EUR     = threshold_fn("PRICE_CHEAP_EUR_KWH")
            PRICE_EXPENSIVE_EUR = threshold_fn("PRICE_EXPENSIVE_EUR_KWH")
        except Exception:
            pass  # keep defaults
        # _learner is de BDEFeedbackTracker — set door coordinator na initialisatie
        # (was eerder undefined 'learner' variabele → silent crash)
        if not hasattr(self, '_learner'):
            self._learner = None

    def _biased_threshold(self, base: float, component: str, bucket: str, action: str) -> float:
        """Pas de geleerde bias toe op een drempelwaarde. Veilig: max ±30%, min 5 samples."""
        if self._learner is None:
            return base
        try:
            return self._learner.apply_bias_to_threshold(base, component, bucket, action)
        except Exception:
            return base

    def evaluate(self, ctx: DecisionContext) -> BatteryDecision:
        decision = self._evaluate_inner(ctx)
        return self._apply_anti_cycling(decision)

    def _evaluate_inner(self, ctx: DecisionContext) -> BatteryDecision:
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

        # Laag 0: anti-cycling — voorkom snelle wissel tussen laden en ontladen
        _now = _time.time()
        _elapsed = _now - self._last_action_ts
        _cooldown_s = self.anti_cycling_min * 60

        # Laag 1: veiligheidsgrenzen
        d = self._check_safety(ctx, soc, ceil, available_kwh, headroom_kwh)
        if d: return d

        # Laag 1a: cel-balancering — maandelijkse volledige lading heeft prioriteit
        if ctx.cell_balancing_needed and headroom_kwh > 0.5:
            # Alleen laden als prijs acceptabel (< 25ct) — niet bij piekprijzen
            if ctx.epex_eur_now is None or ctx.epex_eur_now < 0.25:
                return BatteryDecision(
                    action="charge",
                    reason="Cel-balancering: maandelijkse volledige lading naar 100%",
                    priority=15,
                    confidence=1.0,
                    source="cell_balancing",
                    soc_pct=soc, tariff_group=tg, epex_eur=ctx.epex_eur_now,
                )

        # Laag 1b: peak shaving
        d = self._check_peak_shaving(ctx, soc, available_kwh)
        if d: return d

        # Laag 2: tariefgroep
        d = self._check_tariff_group(ctx, tg, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 2b: Negative Price Dumping
        # Als het volgende uur negatief geprijsd is → ontlaad nu om maximale laadruimte te hebben
        d = self._check_negative_price_dump(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 2.5: Cost-based optimizer — 48-uurs plan weet meer dan losse EPEX-drempel
        d = self._check_optimizer(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3: EPEX (fallback als optimizer geen signaal geeft)
        d = self._check_epex(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3b: off-peak tarief (als geen EPEX signal)
        d = self._check_off_peak(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3.4: Dispatch plan — planner suggestie als zachte nudge
        d = self._check_dispatch_plan(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 3.5: AI hint — nudge thresholds when confident
        d = self._check_ai_hint(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Laag 4: PV forecast
        d = self._check_pv(ctx, soc, available_kwh, headroom_kwh)
        if d: return d

        # Anti-cycling: als actie wisselt en cooldown nog actief, terug naar idle
        # (wordt toegepast na alle lagen via _apply_anti_cycling)

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

    def _apply_anti_cycling(self, decision: "BatteryDecision") -> "BatteryDecision":
        """
        Laag 0: Anti-cycling filter.

        Twee beschermingen:
        1. Micro-cycle prevention: blokkeer actiewissels korter dan MIN_CYCLE_S seconden.
           Voorkomt dat de batterij tientallen keren per uur voor/ontlaadt (slijt chemie).
        2. Anti-cycling cooldown: na een actiewissel, wacht anti_cycling_min minuten
           voor de volgende wissel van richting (laden→ontladen of andersom).
        """
        _now  = _time.time()
        _prev = self._last_action
        _new  = decision.action

        MIN_CYCLE_S = 120  # 2 minuten minimale cyclustijd

        # Altijd safety-acties doorlaten
        if decision.source in ("safety", "cell_balancing", "peak_shaving"):
            self._last_action    = _new
            self._last_action_ts = _now
            return decision

        # Micro-cycle prevention: blokkeer als actie te snel wisselt
        elapsed = _now - self._last_action_ts
        if _prev != "idle" and _new != _prev and _new != "idle" and elapsed < MIN_CYCLE_S:
            return BatteryDecision(
                action   = "idle",
                reason   = (
                    f"Micro-cycle preventie: {_prev}→{_new} geweigerd "
                    f"({elapsed:.0f}s < {MIN_CYCLE_S}s minimum). Batterij beschermd."
                ),
                priority  = 0,
                confidence= 1.0,
                source    = "anti_cycling",
                soc_pct   = decision.soc_pct,
                tariff_group = decision.tariff_group,
                epex_eur  = decision.epex_eur,
            )

        # Anti-cycling cooldown: laden→ontladen of andersom pas na cooldown
        cooldown = self.anti_cycling_min * 60
        is_direction_flip = (
            (_prev == "charge"    and _new == "discharge") or
            (_prev == "discharge" and _new == "charge")
        )
        if is_direction_flip and elapsed < cooldown:
            return BatteryDecision(
                action   = "idle",
                reason   = (
                    f"Anti-cycling: richting {_prev}→{_new} geweigerd "
                    f"({elapsed:.0f}s < {cooldown:.0f}s cooldown). Wacht nog {cooldown-elapsed:.0f}s."
                ),
                priority  = 0,
                confidence= 1.0,
                source    = "anti_cycling",
                soc_pct   = decision.soc_pct,
                tariff_group = decision.tariff_group,
                epex_eur  = decision.epex_eur,
            )

        # Actie geaccepteerd — update state
        if _new != _prev:
            self._last_action_ts = _now
        self._last_action = _new
        return decision

    def _check_optimizer(self, ctx, soc, available_kwh, headroom_kwh):
        """
        Laag 3.3: Cost-based BatteryOptimizer — sterker signaal dan dispatch planner.

        De optimizer heeft 48 uur vooruit gekeken en de goedkoopste combinatie
        van laden/ontladen berekend. Dit is een sterk signaal — hoger dan EPEX-drempel.
        Maar veiligheidsregels (laag 1) hebben altijd prioriteit.
        """
        action = ctx.optimizer_action
        target = ctx.optimizer_target_soc
        reason = ctx.optimizer_reason or "Cost-optimizer"

        if not action or action == "idle":
            return None

        soc_  = soc or 0.0
        tg    = (ctx.tariff_group or "normal").lower()
        price = ctx.epex_eur_now

        if action in ("charge_grid", "charge_pv") and headroom_kwh > 0.2:
            return BatteryDecision(
                action    = "charge",
                reason    = f"Optimizer (48u plan): {reason}",
                priority  = 25,   # boven EPEX drempel (3), onder safety (1)
                confidence= 0.85,
                source    = "cost_optimizer",
                soc_pct   = soc_,
                target_soc_pct = target,
                tariff_group   = tg,
                epex_eur  = price,
            )

        if action == "discharge" and available_kwh > 0.2:
            return BatteryDecision(
                action    = "discharge",
                reason    = f"Optimizer (48u plan): {reason}",
                priority  = 25,
                confidence= 0.85,
                source    = "cost_optimizer",
                soc_pct   = soc_,
                target_soc_pct = target,
                tariff_group   = tg,
                epex_eur  = price,
            )

        return None

    def _check_dispatch_plan(self, ctx, soc, available_kwh, headroom_kwh):
        """Laag 3.4: Gebruik dispatch-plan suggestie als zachte nudge."""
        action = ctx.dispatch_action
        target = ctx.dispatch_target_soc
        if not action or action == "idle":
            return None
        soc = soc or 0.0
        tg  = (ctx.tariff_group or "normal").lower()
        price = ctx.epex_eur_now

        if action == "charge" and headroom_kwh > 0.3:
            # Alleen laden als prijs acceptabel (< 20ct)
            if price is None or price < 0.20:
                return BatteryDecision(
                    action="charge",
                    reason=f"Dispatch plan: laden aanbevolen (target SoC {target:.0f}%)" if target else "Dispatch plan: laden",
                    priority=34, confidence=0.7, source="dispatch_plan",
                    soc_pct=soc, tariff_group=tg, epex_eur=price,
                )

        if action == "discharge" and available_kwh > 0.3:
            # Alleen ontladen als prijs hoog genoeg (> 15ct)
            if price is not None and price > 0.15:
                return BatteryDecision(
                    action="discharge",
                    reason=f"Dispatch plan: ontladen aanbevolen (target SoC {target:.0f}%)" if target else "Dispatch plan: ontladen",
                    priority=34, confidence=0.7, source="dispatch_plan",
                    soc_pct=soc, tariff_group=tg, epex_eur=price,
                )

        if action == "dump_to_boiler":
            # Negatieve prijs: geef hint maar laat boiler controller beslissen
            return None

        return None

    # ── Laag 3.5: AI hint ────────────────────────────────────────────────────────

    def _check_ai_hint(self, ctx, soc, available_kwh, headroom_kwh):
        """
        Apply AI model suggestion as a nudge to battery decisions.

        Only activates when:
        - AI model is ready and confidence >= AI_MIN_CONFIDENCE (65%)
        - Safety rules (layer 1) have already passed
        - The AI suggestion aligns with existing EPEX direction or fills a gap

        The AI does NOT override safety limits or hard rules.
        It lowers/raises the price threshold slightly to act on borderline cases.
        """
        label = ctx.ai_hint_label
        conf  = ctx.ai_hint_confidence or 0.0
        if not label or conf < AI_MIN_CONFIDENCE:
            return None

        soc   = soc or 0.0
        tg    = (ctx.tariff_group or "normal").lower()
        price = ctx.epex_eur_now
        ceil  = self._charge_ceiling(ctx.soh_pct)

        # AI says: charge — act if there is headroom and price is reasonable
        if label == "charge_battery" and headroom_kwh > 0.5:
            # Only if price is not outright expensive (< avg + nudge)
            prices = [p.get("price", 0) for p in (ctx.epex_forecast or []) if p.get("price")]
            avg_price = sum(prices) / len(prices) if prices else 0.20
            threshold = avg_price + AI_PRICE_NUDGE
            if price is None or price <= threshold:
                return BatteryDecision(
                    action="charge",
                    reason=f"AI ({conf:.0%} zekerheid): laden aanbevolen — prijs €{price:.3f}/kWh ≤ drempel €{threshold:.3f}",
                    priority=35,   # between EPEX (3) and PV (4) — lower priority than hard rules
                    confidence=conf * 0.9,
                    source="ai_hint",
                    soc_pct=soc, tariff_group=tg, epex_eur=price,
                )

        # AI says: discharge — act if battery has charge and price is above avg
        if label == "discharge_battery" and available_kwh > 0.5:
            prices = [p.get("price", 0) for p in (ctx.epex_forecast or []) if p.get("price")]
            avg_price = sum(prices) / len(prices) if prices else 0.20
            threshold = avg_price - AI_PRICE_NUDGE
            if price is not None and price >= threshold:
                return BatteryDecision(
                    action="discharge",
                    reason=f"AI ({conf:.0%} zekerheid): ontladen aanbevolen — prijs €{price:.3f}/kWh ≥ drempel €{threshold:.3f}",
                    priority=35,
                    confidence=conf * 0.9,
                    source="ai_hint",
                    soc_pct=soc, tariff_group=tg, epex_eur=price,
                )

        return None

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

        # v4.6.507: pas geleerde bias toe op drempels
        _bucket = ""
        try:
            from .decision_outcome_learner import build_context_bucket
            import datetime as _dt
            _avg = ctx.epex_forecast[0].get("price", PRICE_CHEAP_EUR) if ctx.epex_forecast else PRICE_CHEAP_EUR
            _bucket = build_context_bucket(
                "battery", ctx.soc_pct, price or 0.0,
                float(_avg), ctx.pv_surplus_w,
                month=_dt.datetime.now().month, hour=_dt.datetime.now().hour,
            )
        except Exception:
            pass
        _cheap_thresh     = self._biased_threshold(PRICE_CHEAP_EUR,     "battery", _bucket, "charge")
        _expensive_thresh = self._biased_threshold(PRICE_EXPENSIVE_EUR, "battery", _bucket, "discharge")

        # v4.6.507: saldering corrigeert de werkelijke waarde van export.
        # Bij 36% saldering is export 36% van importprijs waard — ontladen is minder aantrekkelijk.
        # Bij 0% saldering (2027 NL, en alle andere landen) is zelf-consumeren maximaal waardevol
        # → ontlaaddrempel omlaag (eerder ontladen), laaddrempel iets omhoog.
        #
        # Effectieve exportwaarde:  price × net_metering_pct
        # Waarde zelf-consumptie:   all_in_price (≈ price + tax + markup)
        # Spread = zelf-consumptie minus export → groter bij lager saldering → eerder laden
        _nm = max(0.0, min(1.0, ctx.net_metering_pct))
        # Ontlaaddrempel: bij 100% saldering is export evenveel waard als import → minder
        # nuttig om te ontladen. Bij 0% saldering: directe besparing = maximaal.
        # Correctie: drempel × (1 - nm * 0.4) — max 40% lager bij volledige saldering
        _discharge_thresh = _expensive_thresh * (1.0 - _nm * 0.4)
        # Laaddrempel: bij 0% saldering wil je vroeger laden (geen export-fallback)
        # Correctie: drempel iets hoger bij 0% saldering (agressiever laden)
        _charge_thresh = _cheap_thresh * (1.0 + (1.0 - _nm) * 0.15)

        # Sla drempels op voor tooltip in coordinator
        self._last_charge_thr    = round(_charge_thresh, 4)
        self._last_discharge_thr = round(_discharge_thresh, 4)
        self._last_nm_pct        = round(_nm, 3)

        if price <= _charge_thresh and headroom_kwh >= MIN_USEFUL_CAPACITY_KWH:
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
                reason=f"EPEX goedkoop €{price:.3f}/kWh ≤ {_charge_thresh:.2f} (saldering {_nm:.0%}) — laden",
                priority=3, confidence=0.75, source="epex_cheap",
                soc_pct=soc, target_soc_pct=ceil,
                tariff_group=tg, epex_eur=price,
            )

        if price >= _discharge_thresh and available_kwh >= MIN_USEFUL_CAPACITY_KWH:
            return BatteryDecision(
                action="discharge",
                reason=f"EPEX duur €{price:.3f}/kWh ≥ {_discharge_thresh:.2f} (saldering {_nm:.0%}) — ontladen",
                priority=3, confidence=0.70, source="epex_expensive",
                soc_pct=soc, target_soc_pct=MIN_SOC_DISCHARGE + 5,
                tariff_group=tg, epex_eur=price,
            )
        return None

    def _check_negative_price_dump(self, ctx, soc, available_kwh, headroom_kwh):
        """
        Laag 2b: Negative Price Dumping.

        Als er in de komende 1-2 uur een negatief EPEX-uur is:
        1. Ontlaad nu tot minimum (ruimte creëren voor gratis/betaald laden)
        2. Zodat we in het negatieve uur maximaal kunnen laden (je krijgt geld toe)

        Actief als: volgende uur prijs < NEGATIVE_PRICE_THRESHOLD EN huidige SoC > 30%
        """
        if not ctx.epex_forecast:
            return None

        # Zoek negatief uur in de komende 3 uur
        NEGATIVE_THRESHOLD = -0.005  # -0.5 ct/kWh of lager
        LOOKAHEAD_HOURS    = 3
        now_hour = ctx.current_hour

        upcoming_negative = None
        for slot in ctx.epex_forecast:
            h = slot.get("hour", -1)
            p = slot.get("price", 0)
            # Uur is in de komende LOOKAHEAD_HOURS uur
            diff = (h - now_hour) % 24
            if 0 < diff <= LOOKAHEAD_HOURS and p <= NEGATIVE_THRESHOLD:
                upcoming_negative = slot
                break

        if upcoming_negative is None:
            return None

        # Huidig uur moet NIET al negatief zijn (dan laden we al)
        if ctx.epex_eur_now is not None and ctx.epex_eur_now <= NEGATIVE_THRESHOLD:
            return None

        # Ontlaad alleen als er voldoende te ontladen valt
        if available_kwh < 1.0:
            return None

        soc  = soc or 0.0
        tg   = (ctx.tariff_group or "normal").lower()
        neg_h = upcoming_negative.get("hour", "?")
        neg_p = upcoming_negative.get("price", 0)

        return BatteryDecision(
            action   = "discharge",
            reason   = (
                f"Negative Price Dump: uur {neg_h:02d}:00 heeft prijs €{neg_p:.3f}/kWh — "
                f"nu ontladen om maximale laadruimte te hebben bij betaald laden"
            ),
            priority  = 25,   # hoger dan EPEX (3) maar lager dan safety (1)
            confidence= 0.85,
            source    = "negative_price_dump",
            soc_pct   = soc,
            target_soc_pct = MIN_SOC_DISCHARGE + 5,
            tariff_group  = tg,
            epex_eur  = ctx.epex_eur_now,
        )

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
            f"Saldering: {ctx.net_metering_pct:.0%} → laadrempel €{(PRICE_CHEAP_EUR * (1.0 + (1.0 - ctx.net_metering_pct) * 0.15)):.3f}, ontlaadrempel €{(PRICE_EXPENSIVE_EUR * (1.0 - ctx.net_metering_pct * 0.4)):.3f}",
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
