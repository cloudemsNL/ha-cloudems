"""
CloudEMS MultidayPlanner — v5.5.512
Plant batterijladen/ontladen over meerdere dagen (vandaag + morgen + overmorgen).

Gebruikt EPEX dag+1 en dag+2 prijzen zodra beschikbaar.
Voordeel: goedkope nachttarieven morgen alvast inplannen, dure uren morgen mijden.

Strategie:
- Kijk 48-72u vooruit op prijzen
- Bereken optimale SOC doelen per dag-einde
- Pas vandaag-plan aan op basis van morgen-verwachting
"""
from __future__ import annotations
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class MultidayPlanner:
    """
    Optimaliseert batterijstrategie over meerdere dagen.
    Geeft aanbevelingen voor SOC-doelen en prioriteiten per dag.
    """

    def __init__(self, capacity_kwh: float = 9.3,
                 min_soc_pct: float = 10.0,
                 max_soc_pct: float = 95.0):
        self.capacity_kwh = capacity_kwh
        self.min_soc_pct = min_soc_pct
        self.max_soc_pct = max_soc_pct

    def analyze(self, today_prices: list[dict],
                tomorrow_prices: list[dict],
                day2_prices: list[dict],
                current_soc_pct: float,
                pv_today_kwh: float = 0.0,
                pv_tomorrow_kwh: float = 0.0) -> dict:
        """
        Analyseer meerdaagse prijzen en geef strategie aanbeveling.

        Args:
            *_prices: lijst van {hour, price_eur_kwh} dicts
            current_soc_pct: huidige SOC
            pv_*_kwh: verwachte PV per dag

        Returns:
            dict met aanbevelingen per dag
        """
        if not today_prices:
            return {}

        today_avg = self._avg_price(today_prices)
        tomorrow_avg = self._avg_price(tomorrow_prices) if tomorrow_prices else None
        day2_avg = self._avg_price(day2_prices) if day2_prices else None

        today_min = self._min_price(today_prices)
        tomorrow_min = self._min_price(tomorrow_prices) if tomorrow_prices else None

        today_max = self._max_price(today_prices)
        tomorrow_max = self._max_price(tomorrow_prices) if tomorrow_prices else None

        result = {
            "today": self._day_strategy(
                today_prices, current_soc_pct, pv_today_kwh,
                next_day_avg=tomorrow_avg, next_day_min=tomorrow_min
            ),
            "horizon_days": 1,
        }

        if tomorrow_prices:
            result["tomorrow"] = self._day_strategy(
                tomorrow_prices, None, pv_tomorrow_kwh,
                next_day_avg=day2_avg, next_day_min=None
            )
            result["horizon_days"] = 2

            # Aanbeveling voor vandaag op basis van morgen
            result["cross_day_advice"] = self._cross_day_advice(
                today_avg, today_min, today_max,
                tomorrow_avg, tomorrow_min, tomorrow_max,
                current_soc_pct, pv_today_kwh
            )

        if day2_prices:
            result["day2"] = {"avg_price": day2_avg}
            result["horizon_days"] = 3

        return result

    def _day_strategy(self, prices: list[dict], current_soc_pct: Optional[float],
                      pv_kwh: float, next_day_avg: Optional[float],
                      next_day_min: Optional[float]) -> dict:
        """Bereken strategie voor één dag."""
        avg = self._avg_price(prices)
        min_p = self._min_price(prices)
        max_p = self._max_price(prices)
        spread = max_p - min_p

        # Laden aantrekkelijk als: goedkope uren beschikbaar en spread > 5ct
        charge_attractive = spread > 0.05 and min_p < avg * 0.8

        # Ontladen aantrekkelijk als: dure uren beschikbaar
        discharge_attractive = max_p > avg * 1.2

        # SOC doel einde dag: hoog als morgen duur, laag als morgen goedkoop
        soc_target_end = 50.0  # default
        if next_day_avg is not None:
            if next_day_avg < avg * 0.8:
                # Morgen goedkoop → vandaag zoveel mogelijk ontladen
                soc_target_end = self.min_soc_pct + 10
            elif next_day_avg > avg * 1.2:
                # Morgen duur → vandaag zo vol mogelijk laden
                soc_target_end = self.max_soc_pct - 5

        # Goedkoopste laaduren
        cheap_hours = sorted(prices, key=lambda x: x.get("price_eur_kwh", 0))[:4]
        cheap_hour_nums = sorted([h["hour"] for h in cheap_hours])

        # Duurste ontlaaduren
        expensive_hours = sorted(prices, key=lambda x: -x.get("price_eur_kwh", 0))[:4]
        expensive_hour_nums = sorted([h["hour"] for h in expensive_hours])

        return {
            "avg_price_ct":         round(avg * 100, 1),
            "min_price_ct":         round(min_p * 100, 1),
            "max_price_ct":         round(max_p * 100, 1),
            "spread_ct":            round(spread * 100, 1),
            "charge_attractive":    charge_attractive,
            "discharge_attractive": discharge_attractive,
            "soc_target_end_pct":   round(soc_target_end, 1),
            "cheap_hours":          cheap_hour_nums,
            "expensive_hours":      expensive_hour_nums,
            "pv_kwh":               pv_kwh,
        }

    def _cross_day_advice(self, today_avg, today_min, today_max,
                           tomorrow_avg, tomorrow_min, tomorrow_max,
                           current_soc_pct, pv_today_kwh) -> dict:
        """Geef concreet advies voor vandaag op basis van morgen."""
        advice = []
        priority = "normal"

        if tomorrow_min is not None and tomorrow_min < today_min * 0.7:
            advice.append(f"⚡ Morgen goedkoper laden ({tomorrow_min*100:.1f}ct) — vandaag minder laden")
            priority = "save_for_tomorrow"

        if tomorrow_max is not None and tomorrow_max > today_max * 1.2:
            advice.append(f"💰 Morgen hogere piekprijs ({tomorrow_max*100:.1f}ct) — volle batterij aanbevolen")
            priority = "charge_now"

        if tomorrow_avg is not None and tomorrow_avg < today_avg * 0.85:
            advice.append(f"📉 Morgen gemiddeld goedkoper — ontlaad vandaag maximaal")

        if not advice:
            advice.append("✅ Geen bijzondere meerdag strategie nodig")

        return {
            "priority": priority,
            "advice":   advice,
            "today_avg_ct":    round(today_avg * 100, 1),
            "tomorrow_avg_ct": round(tomorrow_avg * 100, 1) if tomorrow_avg else None,
        }

    @staticmethod
    def _avg_price(prices: list[dict]) -> float:
        if not prices: return 0.0
        vals = [p.get("price_eur_kwh", p.get("price", 0)) for p in prices]
        return sum(vals) / len(vals)

    @staticmethod
    def _min_price(prices: list[dict]) -> float:
        if not prices: return 0.0
        return min(p.get("price_eur_kwh", p.get("price", 0)) for p in prices)

    @staticmethod
    def _max_price(prices: list[dict]) -> float:
        if not prices: return 0.0
        return max(p.get("price_eur_kwh", p.get("price", 0)) for p in prices)
