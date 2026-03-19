# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Decision Outcome Learner v1.0 (Fase 1: batterij)

Registreert batterijbeslissingen, meet het werkelijke financiële resultaat
1–4 uur later, en leert op basis daarvan een bias per context-bucket.

De bias wordt teruggegeven aan de BatteryDecisionEngine zodat drempels
zich aanpassen aan wat historisch het beste werkte.

Fase 1: batterij (charge / discharge / hold)
Fase 2: boiler + EV (gepland v4.6.50x)
Fase 3: warmtepomp + rolluiken (gepland v4.6.51x)
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY    = "cloudems_decision_outcomes_v1"
STORAGE_VERSION = 1

# EMA learning rate — traag leren (stabiel)
EMA_ALPHA      = 0.15
# Minimaal samples voordat bias toegepast wordt
MIN_SAMPLES    = 5
# Maximale bias-aanpassing op drempel (±30%)
MAX_BIAS_FACTOR = 0.30
# Pending records ouder dan 48u worden verwijderd (niet meer evalueerbaar)
MAX_PENDING_AGE_S = 48 * 3600
# Evalueer batterijbeslissingen na 1 uur (3600s)
BATTERY_EVAL_AFTER_S = 3600


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class DecisionRecord:
    """Één opgenomen beslissing, wacht op evaluatie."""
    id:             str
    ts:             float          # unix timestamp beslismoment
    component:      str            # "battery", "boiler", "ev", ...
    action:         str            # "charge", "discharge", "hold", ...
    alternative:    str            # wat het alternatief was
    context_bucket: str            # zie build_context_bucket()
    price_eur_kwh:  float          # EPEX prijs op beslismoment
    expected_value: float          # verwacht financieel voordeel (€), kan 0 zijn
    energy_kwh:     float          # betrokken energie (voor normalisering)
    eval_after_s:   int            # evalueer na X seconden
    # Ingevuld na evaluatie
    actual_value:   float = 0.0
    counterfactual: float = 0.0
    evaluated:      bool  = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LearnedBias:
    """Geleerde bias per component × context_bucket × action."""
    component:       str
    context_bucket:  str
    action:          str
    bias:            float   # -1.0 tot +1.0, EMA-gewogen
    samples:         int
    last_updated:    float
    total_value_eur: float   # cumulatief financieel resultaat

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "LearnedBias":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Hoofd klasse ──────────────────────────────────────────────────────────────

class DecisionOutcomeLearner:
    """Zelflerend beslissingsysteem — fase 1: batterij counterfactual evaluation.

    Workflow per cyclus:
      1. evaluate_outcomes() — verwerk records die oud genoeg zijn
      2. record_decision()   — registreer nieuwe beslissing
      3. get_bias()          — geef geleerde bias terug aan BDE
    """

    def __init__(self, hass) -> None:
        self.hass    = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._pending:  list[DecisionRecord] = []
        self._biases:   dict[str, LearnedBias] = {}  # key = component:bucket:action
        self._stats: dict = {
            "total_decisions": 0,
            "total_evaluated": 0,
            "total_value_eur": 0.0,
        }
        self._recent_outcomes: list[dict] = []   # laatste 20 uitkomsten voor dashboard
        self._dirty = False

    # ── Persistentie ─────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load() or {}
            for r in data.get("pending", []):
                try:
                    self._pending.append(DecisionRecord.from_dict(r))
                except Exception as e:
                    _LOGGER.debug("DOL: pending record overgeslagen: %s", e)
            for b in data.get("biases", []):
                try:
                    bias = LearnedBias.from_dict(b)
                    self._biases[self._bias_key(bias.component, bias.context_bucket, bias.action)] = bias
                except Exception as e:
                    _LOGGER.debug("DOL: bias record overgeslagen: %s", e)
            self._stats = data.get("stats", self._stats)
            self._recent_outcomes = data.get("recent_outcomes", [])
            _LOGGER.info(
                "DOL: geladen — %d pending, %d biases, €%.2f totaal geleerd",
                len(self._pending), len(self._biases), self._stats.get("total_value_eur", 0)
            )
        except Exception as e:
            _LOGGER.warning("DOL: laden mislukt: %s", e)

    async def async_save(self) -> None:
        if not self._dirty:
            return
        try:
            await self._store.async_save({
                "pending":  [r.to_dict() for r in self._pending],
                "biases":   [b.to_dict() for b in self._biases.values()],
                "stats":    self._stats,
                "recent_outcomes": self._recent_outcomes[-20:],
            })
            self._dirty = False
        except Exception as e:
            _LOGGER.warning("DOL: opslaan mislukt: %s", e)

    # ── Publieke API ──────────────────────────────────────────────────────────

    def record_decision(
        self,
        component: str,
        action: str,
        alternative: str,
        context_bucket: str,
        price_eur_kwh: float,
        energy_kwh: float,
        expected_value: float = 0.0,
        eval_after_s: int = BATTERY_EVAL_AFTER_S,
    ) -> str:
        """Registreer een beslissing voor latere evaluatie. Geeft record-id terug."""
        rec_id = str(uuid.uuid4())[:8]
        rec = DecisionRecord(
            id             = rec_id,
            ts             = time.time(),
            component      = component,
            action         = action,
            alternative    = alternative,
            context_bucket = context_bucket,
            price_eur_kwh  = price_eur_kwh,
            energy_kwh     = energy_kwh,
            expected_value = expected_value,
            eval_after_s   = eval_after_s,
        )
        self._pending.append(rec)
        self._stats["total_decisions"] = self._stats.get("total_decisions", 0) + 1
        self._dirty = True
        _LOGGER.debug(
            "DOL: beslissing geregistreerd [%s] %s:%s vs %s bucket=%s prijs=%.4f€",
            rec_id, component, action, alternative, context_bucket, price_eur_kwh,
        )
        return rec_id

    def evaluate_outcomes(
        self,
        current_price: float,
        p1_data: dict | None = None,
        price_history: list[dict] | None = None,
    ) -> int:
        """Evalueer alle rijpe pending records. Geeft aantal geëvalueerde records terug.

        Wordt elke coordinator-cyclus aangeroepen.
        """
        now = time.time()
        evaluated = 0

        # Verwijder verlopen records (>48u oud)
        self._pending = [r for r in self._pending if (now - r.ts) < MAX_PENDING_AGE_S]

        for rec in self._pending:
            if rec.evaluated:
                continue
            if (now - rec.ts) < rec.eval_after_s:
                continue

            # Evalueer op basis van component
            if rec.component == "battery":
                actual, counterfactual = self._evaluate_battery(
                    rec, current_price, price_history or []
                )
            elif rec.component == "boiler":
                actual, counterfactual = self._evaluate_boiler(
                    rec, current_price, price_history or []
                )
            elif rec.component == "ev":
                actual, counterfactual = self._evaluate_ev(
                    rec, current_price, price_history or []
                )
            elif rec.component == "heatpump":
                actual, counterfactual = self._evaluate_heatpump(
                    rec, current_price, price_history or []
                )
            elif rec.component == "shutter":
                actual, counterfactual = self._evaluate_shutter(
                    rec, current_price, price_history or []
                )
            else:
                actual, counterfactual = 0.0, 0.0

            rec.actual_value    = actual
            rec.counterfactual  = counterfactual
            rec.evaluated       = True

            # decision_value = wat we kozen minus wat alternatief had opgeleverd
            decision_value = actual - counterfactual

            # Update bias voor dit component × bucket × action
            self._update_bias(rec, decision_value)

            # Stats bijwerken
            self._stats["total_evaluated"] = self._stats.get("total_evaluated", 0) + 1
            self._stats["total_value_eur"] = round(
                self._stats.get("total_value_eur", 0.0) + decision_value, 4
            )

            # Opslaan in recente uitkomsten (dashboard)
            self._recent_outcomes.append({
                "ts":             now,
                "component":      rec.component,
                "action":         rec.action,
                "alternative":    rec.alternative,
                "context_bucket": rec.context_bucket,
                "decision_value": round(decision_value, 4),
                "actual_eur":     round(actual, 4),
                "counterfactual_eur": round(counterfactual, 4),
                "price_at_decision": round(rec.price_eur_kwh, 5),
                "energy_kwh":     round(rec.energy_kwh, 3),
            })
            self._recent_outcomes = self._recent_outcomes[-20:]

            _LOGGER.info(
                "DOL: geëvalueerd [%s] %s:%s — waarde=€%.3f (werkelijk €%.3f, "
                "alternatief €%.3f) bucket=%s",
                rec.id, rec.component, rec.action, decision_value,
                actual, counterfactual, rec.context_bucket,
            )
            evaluated += 1
            self._dirty = True

        # Verwijder geëvalueerde records ouder dan 24u (ruimtebesparing)
        self._pending = [
            r for r in self._pending
            if not r.evaluated or (now - r.ts) < 86400
        ]

        return evaluated

    def get_bias(self, component: str, context_bucket: str, action: str) -> float:
        """Geef geleerde bias terug (-1.0 tot +1.0). 0.0 als onvoldoende data.

        Bias > 0 → component doet het goed in deze context → drempel iets agressiever
        Bias < 0 → component doet het slecht → drempel iets conservatiever
        """
        key = self._bias_key(component, context_bucket, action)
        b = self._biases.get(key)
        if b is None or b.samples < MIN_SAMPLES:
            return 0.0
        return b.bias

    def apply_bias_to_threshold(
        self, threshold: float, component: str, context_bucket: str, action: str
    ) -> float:
        """Pas geleerde bias toe op een drempelwaarde. Max ±30% aanpassing."""
        bias = self.get_bias(component, context_bucket, action)
        if bias == 0.0:
            return threshold
        adjusted = threshold * (1.0 + bias * MAX_BIAS_FACTOR)
        _LOGGER.debug(
            "DOL: drempel %s:%s %.4f → %.4f (bias=%.3f)",
            component, action, threshold, adjusted, bias,
        )
        return adjusted

    def get_status(self) -> dict:
        """Status voor sensor-attribuut en dashboard."""
        top_insight = self._generate_top_insight()
        return {
            "pending_evaluations": sum(1 for r in self._pending if not r.evaluated),
            "total_decisions":     self._stats.get("total_decisions", 0),
            "total_evaluated":     self._stats.get("total_evaluated", 0),
            "total_value_eur":     round(self._stats.get("total_value_eur", 0.0), 2),
            "top_insight":         top_insight,
            "biases": [
                {
                    "component":       b.component,
                    "context_bucket":  b.context_bucket,
                    "action":          b.action,
                    "bias":            round(b.bias, 3),
                    "samples":         b.samples,
                    "value_eur":       round(b.total_value_eur, 2),
                    "ready":           b.samples >= MIN_SAMPLES,
                }
                for b in sorted(self._biases.values(), key=lambda x: abs(x.bias), reverse=True)[:20]
            ],
            "recent_outcomes": self._recent_outcomes[-10:],
        }

    # ── Interne evaluatie batterij ────────────────────────────────────────────

    def _evaluate_battery(
        self,
        rec: DecisionRecord,
        current_price: float,
        price_history: list[dict],
    ) -> tuple[float, float]:
        """Bereken werkelijke waarde en counterfactual voor een batterijbeslissing.

        Retourneert (actual_eur, counterfactual_eur).

        Methode:
          charge → werkelijke waarde = (prijs nu − prijs op laadmoment) × kWh
                    counterfactual    = 0 (hold had niets opgeleverd)
          discharge → werkelijke waarde = prijs nu × kWh (vermeden import)
                      counterfactual    = prijs op laadmoment × kWh (had geladen)
          hold → werkelijke waarde = 0
                 counterfactual    = gemiste waarde als charge of discharge beter was
        """
        kwh   = rec.energy_kwh
        p_dec = rec.price_eur_kwh   # prijs op beslismoment
        p_now = current_price       # prijs op evaluatiemoment

        if rec.action == "charge":
            # Geladen bij lage prijs, ontladen bij hogere prijs?
            # Werkelijke waarde: price spread × energie
            spread = p_now - p_dec
            actual = spread * kwh
            # Alternatief (hold): niets geladen = 0 winst
            counterfactual = 0.0

        elif rec.action == "discharge":
            # Ontladen: vermijden van netimport
            actual = p_now * kwh
            # Alternatief (hold): niet ontladen, had later wellicht bij betere prijs gekund
            # Conservatieve schatting: gemiddelde prijs in window
            avg_price = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            counterfactual = (avg_price or p_dec) * kwh

        elif rec.action == "hold":
            actual = 0.0
            # Counterfactual: had laden/ontladen beter geweest?
            if rec.alternative == "charge":
                # Als we geladen hadden, wat was dan de spread?
                spread = p_now - p_dec
                counterfactual = max(0.0, spread * kwh)
            elif rec.alternative == "discharge":
                counterfactual = p_now * kwh
            else:
                counterfactual = 0.0

        else:
            actual = 0.0
            counterfactual = 0.0

        return round(actual, 4), round(counterfactual, 4)


    def _evaluate_boiler(
        self,
        rec: DecisionRecord,
        current_price: float,
        price_history: list[dict],
    ) -> tuple[float, float]:
        """Bereken waarde van een boilerbeslissing.

        Methode:
          hold_on/turn_on/boost → nu stoken bij prijs p_dec
            Werkelijke waarde  = (avg_prijs_komende_2u − p_dec) × kWh
              positief = goed gekozen (goedkoper dan later)
            Counterfactual (hold_off) = 0 (uitgesteld → gemiste besparing)
        """
        kwh   = rec.energy_kwh
        p_dec = rec.price_eur_kwh
        p_now = current_price

        if rec.action in ("hold_on", "turn_on", "boost"):
            # We stookten bij p_dec. Had het uitgesteld beter geweest?
            avg_later = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            p_later   = avg_later if avg_later is not None else p_now
            # Positief = we stookten goedkoper dan het gemiddelde later
            actual         = (p_later - p_dec) * kwh
            counterfactual = 0.0   # alternatief was wachten

        elif rec.action in ("hold_off", "turn_off"):
            # We wachtten. Was dat beter?
            avg_later = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            p_later   = avg_later if avg_later is not None else p_now
            # Counterfactual: als we nu gestookt hadden bij p_dec
            actual         = 0.0
            counterfactual = (p_later - p_dec) * kwh   # hoeveel we gewonnen hadden door NU te stoken
        else:
            actual, counterfactual = 0.0, 0.0

        return round(actual, 4), round(counterfactual, 4)

    def _evaluate_ev(
        self,
        rec: DecisionRecord,
        current_price: float,
        price_history: list[dict],
    ) -> tuple[float, float]:
        """Bereken waarde van een EV-laadsbeslissing.

        Methode:
          solar / cheap → laden op goed moment
            Werkelijke waarde  = (avg_prijs_dag − p_dec) × kWh
              positief = goedkoper geladen dan dag-gemiddelde
            Counterfactual (wait) = 0
          wait → uitgesteld laden
            Counterfactual = verschil met prijs op beslismoment
        """
        kwh   = rec.energy_kwh
        p_dec = rec.price_eur_kwh

        if rec.action in ("solar", "cheap", "charge_now"):
            avg_later = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            p_later   = avg_later if avg_later is not None else current_price
            actual         = (p_later - p_dec) * kwh
            counterfactual = 0.0

        elif rec.action == "wait":
            avg_later = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            p_later   = avg_later if avg_later is not None else current_price
            actual         = 0.0
            counterfactual = (p_later - p_dec) * kwh
        else:
            actual, counterfactual = 0.0, 0.0

        return round(actual, 4), round(counterfactual, 4)


    def _evaluate_heatpump(
        self,
        rec: DecisionRecord,
        current_price: float,
        price_history: list[dict],
    ) -> tuple[float, float]:
        """Bereken waarde van een warmtepomp setpoint-offset beslissing.

        Methode:
          preheat (offset omhoog bij goedkope prijs):
            Werkelijke waarde = (avg_prijs_komende_3u - p_dec) × kWh_thermisch / COP
            Positief = we verwarmden goedkoper dan het alternatief later
          reduce (offset omlaag bij dure prijs):
            Werkelijke waarde = p_dec × kWh_bespaard (we hebben minder verbruikt)
        """
        kwh   = rec.energy_kwh
        p_dec = rec.price_eur_kwh

        if rec.action == "preheat":
            avg_later = self._avg_price_in_window(price_history, rec.ts, rec.eval_after_s)
            p_later   = avg_later if avg_later is not None else current_price
            # Voorverwarmd bij p_dec, anders had het p_later gekost
            actual         = (p_later - p_dec) * kwh
            counterfactual = 0.0
        elif rec.action == "reduce":
            # We verlaagden setpoint bij dure prijs → bespaard p_dec × kWh
            actual         = p_dec * kwh
            counterfactual = 0.0   # alternatief was geen besparing
        else:
            actual, counterfactual = 0.0, 0.0

        return round(actual, 4), round(counterfactual, 4)

    def _evaluate_shutter(
        self,
        rec: DecisionRecord,
        current_price: float,
        price_history: list[dict],
    ) -> tuple[float, float]:
        """Bereken waarde van een rolluikbeslissing.

        Methode:
          close (sluiten voor thermisch comfort — koeling besparen):
            Werkelijke waarde = voorkomen airco-kWh × (COP_airco) × prijs
            Schatting: 0.3 kWh koeling per graad uur × prijs
          open (openen voor passieve zonnewarmte):
            Werkelijke waarde = gewonnen thermische kWh × prijs / COP_WP

        Voorzichtig geschat: gebruik alleen prijs en energie-schatting.
        """
        kwh   = rec.energy_kwh  # geschat thermisch voordeel
        p_dec = rec.price_eur_kwh

        if rec.action in ("close", "position"):
            # Sluiten → koeling bespaard → werkelijke besparing
            actual         = p_dec * kwh
            counterfactual = 0.0
        elif rec.action == "open":
            # Openen → passieve zonnewarmte → minder WP/CV nodig
            actual         = p_dec * kwh
            counterfactual = 0.0
        elif rec.action == "idle":
            actual         = 0.0
            counterfactual = p_dec * kwh * 0.3  # gemiste kans (conservatief)
        else:
            actual, counterfactual = 0.0, 0.0

        return round(actual, 4), round(counterfactual, 4)

    def _avg_price_in_window(
        self,
        price_history: list[dict],
        ts_start: float,
        window_s: int,
    ) -> float | None:
        """Bereken gemiddelde prijs in een tijdvenster uit price_history."""
        ts_end = ts_start + window_s
        relevant = [
            float(p.get("price", 0))
            for p in (price_history or [])
            if ts_start <= float(p.get("ts", 0)) <= ts_end
        ]
        if not relevant:
            return None
        return sum(relevant) / len(relevant)

    # ── Bias update ───────────────────────────────────────────────────────────

    def _update_bias(self, rec: DecisionRecord, decision_value: float) -> None:
        """Update de bias voor component × bucket × action via EMA."""
        key = self._bias_key(rec.component, rec.context_bucket, rec.action)
        b = self._biases.get(key)

        # Normaliseer decision_value op kWh zodat grote en kleine beslissingen vergelijkbaar zijn
        kwh = max(rec.energy_kwh, 0.01)
        normalized_value = decision_value / kwh   # €/kWh

        # Converteer naar bias-signaal: positief = goed, negatief = slecht
        # Schaal: elke 0.10 €/kWh = 1.0 bias-punt (arbitraire schaal)
        raw_signal = normalized_value / 0.10

        if b is None:
            b = LearnedBias(
                component       = rec.component,
                context_bucket  = rec.context_bucket,
                action          = rec.action,
                bias            = max(-1.0, min(1.0, raw_signal)),
                samples         = 1,
                last_updated    = time.time(),
                total_value_eur = decision_value,
            )
        else:
            # EMA update
            new_bias = EMA_ALPHA * max(-1.0, min(1.0, raw_signal)) + (1 - EMA_ALPHA) * b.bias
            b.bias            = round(max(-1.0, min(1.0, new_bias)), 4)
            b.samples        += 1
            b.last_updated    = time.time()
            b.total_value_eur = round(b.total_value_eur + decision_value, 4)

        self._biases[key] = b
        _LOGGER.debug(
            "DOL: bias update %s → %.3f (samples=%d, €/kWh=%.4f)",
            key, b.bias, b.samples, normalized_value,
        )

    # ── Insights ─────────────────────────────────────────────────────────────

    def _generate_top_insight(self) -> str:
        """Genereer de meest waardevolle inzicht-zin op basis van geleerde biases."""
        if not self._biases:
            return "Nog onvoldoende data — evaluaties worden automatisch opgebouwd."

        ready = [b for b in self._biases.values() if b.samples >= MIN_SAMPLES]
        if not ready:
            pending_count = sum(1 for r in self._pending if not r.evaluated)
            return f"Leerproces gestart — {pending_count} beslissingen wachten op evaluatie."

        best = max(ready, key=lambda b: abs(b.bias))
        direction = "vaker" if best.bias > 0 else "minder vaak"

        comp_nl = {
            "battery": "Batterij", "boiler": "Boiler", "ev": "EV",
            "heatpump": "Warmtepomp", "shutter": "Rolluiken",
        }.get(best.component, best.component.capitalize())

        action_nl = {
            "charge": "laden", "discharge": "ontladen", "hold": "niets doen",
            "boost": "BOOST", "green": "GREEN", "hold_on": "aan houden",
            "hold_off": "uit houden", "turn_on": "inschakelen",
            "solar": "zonneladen", "cheap": "goedkoop laden", "wait": "wachten",
            "preheat": "voorverwarmen", "reduce": "verbruik verlagen",
            "close": "sluiten", "open": "openen", "position": "positie aanpassen",
        }.get(best.action, best.action)

        bucket_parts = best.context_bucket.split(":")
        context_hint = ""
        if len(bucket_parts) >= 5:
            daytime_nl = {"night": "'s nachts", "morning": "'s ochtends",
                          "afternoon": "'s middags", "evening": "'s avonds"}
            context_hint = f" {daytime_nl.get(bucket_parts[4], bucket_parts[4])}"
        price_hint = ""
        if len(bucket_parts) >= 2:
            price_nl = {"cheap": "bij lage prijs", "dear": "bij hoge prijs", "normal": ""}
            price_hint = f" {price_nl.get(bucket_parts[1], '')}".rstrip()

        eur = abs(best.total_value_eur)
        return (
            f"{comp_nl} {action_nl}{context_hint}{price_hint} leverde historisch "
            f"{'meer' if best.bias > 0 else 'minder'} op dan verwacht "
            f"(€{eur:.2f} over {best.samples} beslissingen). "
            f"CloudEMS past drempel {direction} aan."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _bias_key(component: str, bucket: str, action: str) -> str:
        return f"{component}:{bucket}:{action}"


# ── Context Bucketing ─────────────────────────────────────────────────────────

def build_context_bucket(
    component: str,
    soc_pct: float | None,
    price_eur_kwh: float,
    avg_price_eur_kwh: float,
    solar_surplus_w: float,
    month: int | None = None,
    hour: int | None = None,
) -> str:
    """Bouw een context-bucket key voor een beslissing.

    Formaat: "component:prijs:soc:seizoen:dagdeel:surplus"
    """
    import datetime as _dt

    # Prijs tier
    if avg_price_eur_kwh > 0:
        ratio = price_eur_kwh / avg_price_eur_kwh
        price_tier = "cheap" if ratio < 0.80 else "dear" if ratio > 1.20 else "normal"
    else:
        price_tier = "normal"

    # SOC tier
    if soc_pct is None:
        soc_tier = "unknown"
    elif soc_pct < 30:
        soc_tier = "low"
    elif soc_pct < 70:
        soc_tier = "mid"
    else:
        soc_tier = "high"

    # Seizoen
    _month = month if month is not None else _dt.datetime.now().month
    season = "winter" if _month in (10, 11, 12, 1, 2, 3) else "summer"

    # Dagdeel
    _hour = hour if hour is not None else _dt.datetime.now().hour
    if _hour < 6:
        daytime = "night"
    elif _hour < 12:
        daytime = "morning"
    elif _hour < 18:
        daytime = "afternoon"
    else:
        daytime = "evening"

    # PV surplus tier
    if solar_surplus_w <= 0:
        surplus_tier = "none"
    elif solar_surplus_w < 500:
        surplus_tier = "low"
    else:
        surplus_tier = "high"

    return f"{component}:{price_tier}:{soc_tier}:{season}:{daytime}:{surplus_tier}"
