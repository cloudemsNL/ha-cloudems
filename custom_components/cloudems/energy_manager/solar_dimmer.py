# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

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
        # Bij herstart: altijd restore uitvoeren zodat een eerder gedimde inverter
        # niet permanent op 0% blijft staan (is_active staat na herstart op False
        # maar de fysieke inverter kan nog steeds gedimd zijn)
        try:
            await self._restore()
            _LOGGER.info("SolarDimmer: inverter hersteld naar 100%% bij opstarten")
        except Exception as _e:
            _LOGGER.debug("SolarDimmer: restore bij opstarten mislukt: %s", _e)

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
        """Evaluate current price and dim/restore accordingly.

        v4.6.507: de drempel wordt gecorrigeerd voor saldering.
        Bij 36% saldering (NL 2026) is de werkelijke export-opbrengst:
          effective_export = current_price × net_metering_pct
        De dimmer activeert pas als effective_export <= threshold,
        zodat hij niet te vroeg ingrijpt terwijl export nog waarde heeft.
        Bij 0% saldering (2027+, DE, BE) is effective_export = current_price (geen correctie).
        """
        if current_price is None:
            return

        # Haal actueel salderingspercentage op via coordinator
        _nm_pct = 0.0
        try:
            from ..const import get_net_metering_pct, CONF_ENERGY_PRICES_COUNTRY
            _country = self.config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
            _nm_pct  = get_net_metering_pct(_country)
        except Exception:
            pass

        # Effectieve export-waarde: bij saldering is een lage prijs minder erg
        # want je ontvangt ook teruglevering-credit. Dus: pas drempel aan.
        # Bij nm=0.36: prijs van -5ct voelt als -5 + 0.36×all_in_price ≈ effectief hoger
        # Vereenvoudigd: drempel verschuift met -nm_pct × all_in_estimate
        # Schatting all_in: current_price + 0.12 (energie belasting + BTW)
        _tax_estimate = 0.12  # conservatieve schatting belasting + BTW (€/kWh)
        _effective_price = current_price + _nm_pct * _tax_estimate

        should_dim = _effective_price <= self._threshold

        if should_dim and not self.is_active:
            _LOGGER.info(
                "⚡ Prijs te laag (%.4f€ effectief, %.4f€ nominaal, saldering %.0f%%) "
                "≤ %.4f — dimmen",
                _effective_price, current_price, _nm_pct * 100, self._threshold,
            )
            await self._dim()
            self.is_active = True
            self._curtail_sessions += 1

        elif not should_dim and self.is_active:
            _LOGGER.info(
                "✅ Prijs genormaliseerd (%.4f€ effectief) — herstellen",
                _effective_price,
            )
            await self._restore()
            self.is_active = False

        # Registreer gewenste staat in ActuatorWatchdog
        self._register_watchdog()

    def _register_watchdog(self) -> None:
        """Registreer gewenste staat van schakelaar(s) in de ActuatorWatchdog.
        Zo wordt elke 60s gecontroleerd of de feitelijke staat klopt.
        """
        watchdog = getattr(getattr(self, "_coordinator", None), "_actuator_watchdog", None)
        if not watchdog:
            return
        desired = "off" if self.is_active else "on"
        for key_conf in (CONF_SOLAR_INVERTER_SWITCH, CONF_EV_CHARGER_SWITCH):
            eid = self.config.get(key_conf)
            if eid:
                restore = self._restore if desired == "on" else self._dim
                watchdog.register(f"solar_dimmer_{key_conf}", eid, desired, restore)

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
            from .command_verify import send_and_verify
            # Bepaal verify op basis van domain/service
            if domain == "number" and service == "set_value":
                target_val = float(extra.get("value", 0)) if extra else 0.0
                await send_and_verify(
                    self.hass, domain, service, data, entity_id=entity_id,
                    verify_fn=lambda s, v=target_val: abs(float(s.state or 0) - v) <= 2.0,
                    description=f"dimmer {entity_id} → {target_val}",
                    max_attempts=3, verify_delay=3.0,
                )
            elif domain == "switch":
                target_state = "on" if service == "turn_on" else "off"
                await send_and_verify(
                    self.hass, domain, service, data, entity_id=entity_id,
                    verify_fn=lambda s, t=target_state: s.state == t,
                    description=f"dimmer switch {entity_id} → {target_state}",
                    max_attempts=3, verify_delay=3.0,
                )
            else:
                await self.hass.services.async_call(domain, service, data, blocking=False)
        except Exception as err:
            _LOGGER.warning("SolarDimmer service call failed: %s", err)
