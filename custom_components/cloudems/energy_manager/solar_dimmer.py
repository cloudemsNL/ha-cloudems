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
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.config = {**entry.data, **entry.options}
        self.is_active = False
        self._threshold = float(
            self.config.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)
        )

    async def async_setup(self) -> None:
        _LOGGER.info(
            "SolarDimmer ready — threshold: %.4f €/kWh", self._threshold
        )

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
