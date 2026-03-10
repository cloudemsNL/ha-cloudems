# -*- coding: utf-8 -*-
"""
CloudEMS Dynamic EV Loader.

Automatically adjusts EV charging speed based on EPEX spot price,
solar surplus and configurable price thresholds.

Strategy
--------
* price < cheap_threshold  → charge at max configured current
* cheap_threshold ≤ price < normal → charge at solar-surplus speed (min 6A)
* price ≥ normal → stop charging unless solar surplus is sufficient
* price is negative → charge at maximum always (free energy!)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from ..const import (
    CONF_DYNAMIC_LOAD_THRESHOLD,
    DEFAULT_DYNAMIC_LOAD_THRESHOLD,
    MIN_EV_CURRENT,
    MAX_EV_CURRENT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class LoadDecision:
    target_current_a: float
    reason: str
    price_eur_kwh: float
    solar_surplus_w: float


class DynamicLoader:
    """EPEX-price-aware EV charge current controller."""

    def __init__(
        self,
        config: dict,
        set_ev_current_cb: Callable[[float], Awaitable[None]],
    ) -> None:
        self._config = config
        self._set_ev_current = set_ev_current_cb
        self._last_target: float | None = None

        self._cheap_threshold: float = float(
            config.get(CONF_DYNAMIC_LOAD_THRESHOLD, DEFAULT_DYNAMIC_LOAD_THRESHOLD)
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_eur_kwh: float,
        solar_surplus_w: float,
        max_current_a: float,
    ) -> LoadDecision:
        """Decide EV charging current and apply it."""
        decision = self._decide(price_eur_kwh, solar_surplus_w, max_current_a)

        if decision.target_current_a != self._last_target:
            _LOGGER.info(
                "DynamicLoader: %.1fA  [price=%.4f €/kWh | solar=%.0fW | %s]",
                decision.target_current_a,
                price_eur_kwh,
                solar_surplus_w,
                decision.reason,
            )
            await self._set_ev_current(decision.target_current_a)
            self._last_target = decision.target_current_a

        return decision

    def update_threshold(self, threshold_eur_kwh: float) -> None:
        self._cheap_threshold = threshold_eur_kwh

    # ── Decision logic ─────────────────────────────────────────────────────────

    def _decide(
        self,
        price: float,
        solar_surplus_w: float,
        max_current_a: float,
    ) -> LoadDecision:
        # Negative price → full blast
        if price < 0:
            return LoadDecision(
                target_current_a=max_current_a,
                reason="negative price — max charge",
                price_eur_kwh=price,
                solar_surplus_w=solar_surplus_w,
            )

        # Cheap hour → full blast
        if price <= self._cheap_threshold:
            return LoadDecision(
                target_current_a=max_current_a,
                reason=f"cheap hour (≤{self._cheap_threshold:.2f} €/kWh)",
                price_eur_kwh=price,
                solar_surplus_w=solar_surplus_w,
            )

        # Solar surplus available → charge on solar only
        solar_current = self._watts_to_amps(solar_surplus_w)
        if solar_current >= MIN_EV_CURRENT:
            capped = min(solar_current, max_current_a)
            return LoadDecision(
                target_current_a=round(capped, 1),
                reason=f"solar surplus {solar_surplus_w:.0f}W",
                price_eur_kwh=price,
                solar_surplus_w=solar_surplus_w,
            )

        # Expensive + no surplus → pause charging
        return LoadDecision(
            target_current_a=0.0,
            reason=f"expensive ({price:.4f} €/kWh), no solar",
            price_eur_kwh=price,
            solar_surplus_w=solar_surplus_w,
        )

    @staticmethod
    def _watts_to_amps(watts: float, voltage: float = 230.0) -> float:
        return watts / voltage if watts > 0 else 0.0
