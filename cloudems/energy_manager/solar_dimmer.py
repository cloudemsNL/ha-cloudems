# -*- coding: utf-8 -*-
"""
CloudEMS Solar Dimmer — throttles solar inverter / EV charger / battery
charging when EPEX spot prices go negative.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_SOLAR_INVERTER_SWITCH,
    CONF_EV_CHARGER_SWITCH,
    CONF_BATTERY_SWITCH,
    CONF_NEGATIVE_PRICE_THRESHOLD,
    DEFAULT_NEGATIVE_PRICE_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)


class SolarDimmer:
    """
    Automatically throttles/enables solar production and EV charging
    based on EPEX spot price threshold.

    At negative prices: solar is throttled to avoid paying grid fees.
    At positive prices: loads are restored to maximise self-consumption.

    v2.6: curtailment tracking — accumulateert verloren kWh en euro's
    per dag/maand/jaar terwijl dimmen actief is.
    """

    def __init__(self, hass: HomeAssistant, config_or_entry, coordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        # Accept either a ConfigEntry or a plain config dict (v2.2.5+)
        if hasattr(config_or_entry, "data"):
            self.config = {**config_or_entry.data, **config_or_entry.options}
        else:
            self.config = dict(config_or_entry) if config_or_entry else {}
        self.is_active = False
        self._threshold = float(
            self.config.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)
        )
        # v2.6: curtailment tracking
        import time as _t
        self._dim_start_ts: float = 0.0
        self._curtail_today_kwh:  float = 0.0
        self._curtail_month_kwh:  float = 0.0
        self._curtail_year_kwh:   float = 0.0
        self._curtail_today_eur:  float = 0.0
        self._curtail_month_eur:  float = 0.0
        self._curtail_year_eur:   float = 0.0
        self._curtail_sessions:   int   = 0
        self._last_reset_day:     str   = ""
        self._last_reset_month:   str   = ""
        self._last_reset_year:    str   = ""
        self._last_solar_w:       float = 0.0   # huidig PV-vermogen (voor kWh-schatting)

    async def async_setup(self) -> None:
        _LOGGER.info(
            "SolarDimmer ready — threshold: %.4f €/kWh", self._threshold
        )

    def update_solar_power(self, solar_w: float) -> None:
        """Bijwerken PV-vermogen voor curtailment-schatting. Elke coordinator-cyclus."""
        self._last_solar_w = max(0.0, solar_w)

    def tick_curtailment(self, interval_s: float = 10.0) -> None:
        """
        Accumuleer verloren energie terwijl dimmen actief is.
        Aanroepen elke 10s vanuit coordinator.
        Gebruikt huidig PV-vermogen als benadering voor wat er afgeknepen wordt.
        """
        if not self.is_active or self._last_solar_w <= 0:
            return
        import time as _t
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        day_k   = now.strftime("%Y-%m-%d")
        month_k = now.strftime("%Y-%m")
        year_k  = now.strftime("%Y")
        if self._last_reset_day   != day_k:   self._curtail_today_kwh  = 0.0; self._curtail_today_eur  = 0.0; self._last_reset_day   = day_k
        if self._last_reset_month != month_k: self._curtail_month_kwh  = 0.0; self._curtail_month_eur  = 0.0; self._last_reset_month = month_k
        if self._last_reset_year  != year_k:  self._curtail_year_kwh   = 0.0; self._curtail_year_eur   = 0.0; self._last_reset_year  = year_k
        # kWh = W × uren; uren = interval_s / 3600
        kwh_lost = self._last_solar_w * (interval_s / 3600.0) / 1000.0
        # Euro-waarde bij positief nultarief (teruglevering verdiend als niet gecurtaild)
        # Gebruik 0.01 €/kWh als minimumwaarde (negatieve prijs = kostenvermijding)
        eur_avoided = kwh_lost * 0.01
        self._curtail_today_kwh  += kwh_lost
        self._curtail_month_kwh  += kwh_lost
        self._curtail_year_kwh   += kwh_lost
        self._curtail_today_eur  += eur_avoided
        self._curtail_month_eur  += eur_avoided
        self._curtail_year_eur   += eur_avoided

    def get_curtailment_stats(self) -> dict:
        """Geef curtailment-statistieken terug voor HA-sensor attributen."""
        return {
            "is_dimming":          self.is_active,
            "today_kwh":           round(self._curtail_today_kwh,  3),
            "month_kwh":           round(self._curtail_month_kwh,  2),
            "year_kwh":            round(self._curtail_year_kwh,   2),
            "today_eur_avoided":   round(self._curtail_today_eur,  3),
            "month_eur_avoided":   round(self._curtail_month_eur,  2),
            "year_eur_avoided":    round(self._curtail_year_eur,   2),
            "sessions_total":      self._curtail_sessions,
            "current_solar_w":     round(self._last_solar_w, 0),
        }

    async def async_evaluate(self, current_price: float | None) -> None:
        """Evaluate current price and dim/restore accordingly."""
        if current_price is None:
            return

        should_dim = current_price <= self._threshold

        if should_dim and not self.is_active:
            _LOGGER.info(
                "⚡ Negative price detected (%.4f €/kWh ≤ %.4f) — dimming solar/EV",
                current_price, self._threshold,
            )
            await self._dim()
            self.is_active = True
            self._curtail_sessions += 1

        elif not should_dim and self.is_active:
            _LOGGER.info(
                "✅ Price normalised (%.4f €/kWh) — restoring solar/EV",
                current_price,
            )
            await self._restore()
            self.is_active = False

    async def _dim(self) -> None:
        """Reduce solar export and stop EV charging to avoid negative price penalties."""
        for key in (CONF_SOLAR_INVERTER_SWITCH, CONF_EV_CHARGER_SWITCH):
            entity_id = self.config.get(key)
            if entity_id:
                await self._call(entity_id, "turn_off")

        # Battery: stop export but allow charging (buy cheap!)
        battery = self.config.get(CONF_BATTERY_SWITCH)
        if battery:
            # If it's a number entity (charge power), set to max charge
            if battery.startswith("number.") or battery.startswith("input_number."):
                await self._call(battery, "set_value", {"value": 100})
            else:
                await self._call(battery, "turn_on")  # enable charging

    async def _restore(self) -> None:
        """Restore normal operation."""
        for key in (CONF_SOLAR_INVERTER_SWITCH, CONF_EV_CHARGER_SWITCH, CONF_BATTERY_SWITCH):
            entity_id = self.config.get(key)
            if entity_id:
                await self._call(entity_id, "turn_on")

    async def _call(self, entity_id: str, service: str, extra: dict | None = None) -> None:
        domain = entity_id.split(".")[0]
        data = {"entity_id": entity_id, **(extra or {})}
        try:
            await self.hass.services.async_call(domain, service, data, blocking=False)
        except Exception as err:
            _LOGGER.warning("SolarDimmer service call failed: %s", err)
