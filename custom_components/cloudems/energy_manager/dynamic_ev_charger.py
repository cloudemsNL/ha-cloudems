"""
CloudEMS Dynamic EV Charger.

Adjusts EV charging current in real-time based on:
  1. Current EPEX spot price vs configured threshold
  2. Solar surplus (optional)
  3. Grid phase headroom (from PhaseLimiter)
  4. EV minimum SoC override (if battery sensor configured)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_EV_CHARGER_ENTITY,
    CONF_DYNAMIC_EV_CHARGING,
    CONF_EV_CHEAP_THRESHOLD,
    CONF_EV_ALWAYS_ON_CURRENT,
    CONF_EV_SOLAR_SURPLUS_PRIO,
    CONF_EV_MIN_SOC_THRESHOLD,
    CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR,
    DEFAULT_EV_CHEAP_THRESHOLD,
    DEFAULT_EV_ALWAYS_ON_CURRENT,
    DEFAULT_EV_MIN_SOC_THRESHOLD,
    MIN_EV_CURRENT,
    MAX_EV_CURRENT,
)

_LOGGER = logging.getLogger(__name__)

# Voltage assumed for W→A conversion (single/three-phase 230 V)
GRID_VOLTAGE = 230.0
# Minimum seconds between current changes (avoid relay chatter)
CHANGE_DEBOUNCE_S = 30


@dataclass
class EVChargingState:
    active: bool = False
    current_a: float = 0.0
    last_change_ts: float = 0.0
    reason: str = "initialising"


class DynamicEVCharger:
    """Controls EV charging current dynamically based on price + solar."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.config = {**entry.data, **entry.options}
        self.state = EVChargingState()
        self._enabled = bool(self.config.get(CONF_DYNAMIC_EV_CHARGING, False))
        self._cheap_threshold = float(
            self.config.get(CONF_EV_CHEAP_THRESHOLD, DEFAULT_EV_CHEAP_THRESHOLD)
        )
        self._always_on_current = float(
            self.config.get(CONF_EV_ALWAYS_ON_CURRENT, DEFAULT_EV_ALWAYS_ON_CURRENT)
        )
        self._solar_prio = bool(self.config.get(CONF_EV_SOLAR_SURPLUS_PRIO, True))
        self._min_soc = float(
            self.config.get(CONF_EV_MIN_SOC_THRESHOLD, DEFAULT_EV_MIN_SOC_THRESHOLD)
        )

    # ── Main update called by coordinator ─────────────────────────────────────

    async def async_update(self) -> None:
        """Compute desired EV current and apply it."""
        if not self._enabled:
            return

        charger_entity = self.config.get(CONF_EV_CHARGER_ENTITY)
        if not charger_entity:
            return

        desired_a, reason = self._compute_desired_current()

        # Debounce: don't change more than once per CHANGE_DEBOUNCE_S
        now = time.time()
        if (
            abs(desired_a - self.state.current_a) < 0.5
            and (now - self.state.last_change_ts) < CHANGE_DEBOUNCE_S
        ):
            return

        await self._set_ev_current(charger_entity, desired_a)
        self.state.current_a = desired_a
        self.state.reason = reason
        self.state.last_change_ts = now
        _LOGGER.info("EV charger → %.1f A (%s)", desired_a, reason)

    # ── Decision logic ────────────────────────────────────────────────────────

    def _compute_desired_current(self) -> tuple[float, str]:
        """Return (ampere, reason) for the desired charging current."""

        # 1. Always charge at minimum if SoC below threshold
        battery_soc = self._get_battery_soc()
        if battery_soc is not None and battery_soc < self._min_soc:
            return (
                self._clamp(MAX_EV_CURRENT),
                f"SoC {battery_soc:.0f}% < minimum {self._min_soc:.0f}%",
            )

        current_price = self._get_current_price()

        # 2. Solar surplus mode
        if self._solar_prio:
            surplus_w = self._get_solar_surplus_w()
            if surplus_w > 200:
                solar_a = self._clamp(surplus_w / GRID_VOLTAGE)
                if current_price is not None and current_price <= self._cheap_threshold:
                    # Cheap + solar: max charge
                    return (
                        self._clamp(MAX_EV_CURRENT),
                        f"Goedkope stroom {current_price:.3f} EUR/kWh + zonnestroom",
                    )
                return solar_a, f"Zonnestroom surplus {surplus_w:.0f} W → {solar_a:.1f} A"

        # 3. Price-based
        if current_price is None:
            return self._always_on_current, "Geen prijsdata — minimum stroom"

        if current_price <= self._cheap_threshold:
            return (
                self._clamp(MAX_EV_CURRENT),
                f"Goedkope stroom {current_price:.3f} EUR/kWh ≤ {self._cheap_threshold:.3f}",
            )

        # Expensive: scale linearly between min and max based on price headroom
        # Price > threshold → only always_on_current
        return (
            self._always_on_current,
            f"Dure stroom {current_price:.3f} EUR/kWh > {self._cheap_threshold:.3f}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clamp(self, amps: float) -> float:
        return round(max(MIN_EV_CURRENT, min(MAX_EV_CURRENT, amps)), 1)

    def _get_current_price(self) -> float | None:
        """Get current EPEX price from coordinator."""
        try:
            return float(self.coordinator.current_epex_price)
        except (AttributeError, TypeError, ValueError):
            return None

    def _get_battery_soc(self) -> float | None:
        """Get battery state-of-charge from HA sensor."""
        entity_id = self.config.get(CONF_BATTERY_SENSOR)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None

    def _get_solar_surplus_w(self) -> float:
        """Return solar production minus current grid consumption (W)."""
        solar_entity = self.config.get(CONF_SOLAR_SENSOR)
        if not solar_entity:
            return 0.0
        state = self.hass.states.get(solar_entity)
        if not state or state.state in ("unknown", "unavailable"):
            return 0.0
        try:
            solar_w = float(state.state)
            # Convert kW → W if unit is kW
            if state.attributes.get("unit_of_measurement", "W") == "kW":
                solar_w *= 1000
            grid_w = getattr(self.coordinator, "current_power_w", 0.0) or 0.0
            return max(0.0, solar_w - grid_w)
        except (ValueError, TypeError):
            return 0.0

    async def _set_ev_current(self, entity_id: str, amps: float) -> None:
        """Write the current setpoint to the EV charger number entity."""
        domain = entity_id.split(".")[0]
        try:
            await self.hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": amps},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("DynamicEVCharger: set_value failed for %s: %s", entity_id, err)

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "current_a": self.state.current_a,
            "reason": self.state.reason,
            "cheap_threshold_eur": self._cheap_threshold,
            "always_on_current_a": self._always_on_current,
            "solar_priority": self._solar_prio,
        }
