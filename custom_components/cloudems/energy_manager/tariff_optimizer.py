# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Negatief Tarief Afvanger + Slim Wassen Verschuiver (v2.6).

Twee gerelateerde functies:

1. NEGATIEF TARIEF AFVANGEN
   Als EPEX < 0 (of onder geconfigureerde drempel):
   • Stel EV-lader in op maximale capaciteit
   • Zet boiler op hoog (als aanwezig)
   • Stuur notificatie

2. SLIM WASSEN/DROGER VERSCHUIVEN
   Als wasmachine/droger aangaat en het huidige tarief hoog is:
   • Detecteer via NILM (device_type: washer / dryer)
   • Bereken wanneer de komende 8 uur het goedkoopste uur is
   • Stuur een suggestie-notificatie: "Wacht X uur, bespaar €Y"
   • Stuur geen notificatie als het toch goedkoop is
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

NEGATIVE_TARIFF_THRESHOLD_DEFAULT = 0.0   # EUR/kWh — onder deze prijs = "negatief"
HIGH_TARIFF_THRESHOLD_DEFAULT     = 0.28  # EUR/kWh — boven dit = "verschuif suggestie"
WASHERS = {"washer", "washing_machine", "dryer", "dishwasher"}
NOTIFICATION_COOLDOWN_H = 2  # Stuur niet vaker dan elke 2 uur


class NegativeTariffCatcher:
    """Detecteert negatieve tarieven en activeert extra verbruik."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._threshold  = float(config.get("negative_tariff_threshold", NEGATIVE_TARIFF_THRESHOLD_DEFAULT))
        self._last_notif: datetime | None = None
        self._was_negative = False

    async def async_check(self, current_price: float, coordinator_data: dict) -> dict:
        """Controleer tarief en activeer apparaten indien nodig."""
        result = {
            "price_is_negative":  current_price < self._threshold,
            "current_price":      current_price,
            "threshold":          self._threshold,
            "actions_taken":      [],
        }

        is_neg = current_price < self._threshold
        if not is_neg:
            self._was_negative = False
            return result

        # Voorkom spam
        now = datetime.now(timezone.utc)
        if self._last_notif and (now - self._last_notif).total_seconds() < NOTIFICATION_COOLDOWN_H * 3600:
            return result

        actions = []

        # EV lader aanzetten / maximeren
        ev_entity = self._config.get("ev_charger_entity")
        if ev_entity:
            state = self._hass.states.get(ev_entity)
            if state and state.state in ("off", "idle", "paused"):
                try:
                    domain = ev_entity.split(".")[0]
                    await self._hass.services.async_call(
                        domain, "turn_on", {"entity_id": ev_entity}, blocking=False
                    )
                    actions.append(f"EV lader ingeschakeld ({ev_entity})")
                except Exception as err:
                    _LOGGER.warning("Negatief tarief: EV lader fout: %s", err)

        # Boiler verhogen
        boiler_entity = self._config.get("boiler_entity")
        if boiler_entity:
            try:
                await self._hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": boiler_entity, "temperature": 65},
                    blocking=False
                )
                actions.append(f"Boiler verhoogd naar 65°C ({boiler_entity})")
            except Exception:
                pass

        # Notificatie
        price_str = f"€{current_price:.3f}/kWh"
        msg = f"⚡ Negatief stroomtarief: {price_str}!\n\n"
        if actions:
            msg += "Automatisch geactiveerd:\n" + "\n".join(f"• {a}" for a in actions)
        else:
            msg += "Overweeg extra verbruikers in te schakelen (EV laden, boiler, vaatwasser)."

        try:
            from homeassistant.components.persistent_notification import async_create
            async_create(
                self._hass, message=msg,
                title="☀️ CloudEMS — Negatief tarief",
                notification_id="cloudems_negative_tariff",
            )
        except Exception:
            pass

        self._last_notif = now
        result["actions_taken"] = actions
        return result


class ApplianceShiftAdvisor:
    """Detecteert wasmachine/droger en adviseert te verschuiven naar goedkoop uur."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass        = hass
        self._config      = config
        self._threshold   = float(config.get("shift_high_tariff_threshold", HIGH_TARIFF_THRESHOLD_DEFAULT))
        self._last_advice: dict[str, datetime] = {}  # device_type → last notification time
        self._devices_on: set = set()

    async def async_check(
        self,
        nilm_devices: list[dict],
        current_price: float,
        price_forecast: list[dict],  # [{hour, price_eur_kwh}, ...]
    ) -> list[dict]:
        """Check of er een wasapparaat is aangegaan en prijs hoog is. Geeft advies-lijst terug."""
        advices = []
        now = datetime.now(timezone.utc)

        for dev in nilm_devices:
            dtype = dev.get("device_type", "")
            name  = dev.get("name") or dtype
            if dtype not in WASHERS:
                continue
            if not dev.get("is_on"):
                self._devices_on.discard(dtype)
                continue

            # Apparaat net aangegaan?
            if dtype in self._devices_on:
                continue  # Al gedetecteerd deze sessie
            self._devices_on.add(dtype)

            # Prijs check — alleen adviseren als hoog
            if current_price < self._threshold:
                continue

            # Cooldown
            last = self._last_advice.get(dtype)
            if last and (now - last).total_seconds() < 4 * 3600:
                continue

            # Vind goedkoopste uur in komende 8 uur
            best = self._find_best_hour(price_forecast, hours_ahead=8)
            if not best:
                continue

            hours_wait  = best.get("hours_from_now", 0)
            best_price  = best.get("price", current_price)
            power_w     = dev.get("power_w", 1000)
            duration_h  = dev.get("avg_duration_h", 1.5)
            saving_eur  = round((current_price - best_price) * (power_w / 1000) * duration_h, 3)

            if saving_eur < 0.01:
                continue

            advice = {
                "device_type":    dtype,
                "device_name":    name,
                "current_price":  current_price,
                "best_price":     best_price,
                "hours_wait":     round(hours_wait, 1),
                "saving_eur":     saving_eur,
                "best_hour_label": best.get("label", ""),
            }
            advices.append(advice)

            # Stuur notificatie
            msg = (
                f"🧺 {name} is gestart bij hoog tarief ({current_price:.2f} €/kWh).\n\n"
                f"Wacht {hours_wait:.0f} uur → tarief daalt naar {best_price:.2f} €/kWh.\n"
                f"Besparing: ~€{saving_eur:.2f} per wasbeurt."
            )
            try:
                from homeassistant.components.persistent_notification import async_create
                async_create(
                    self._hass, message=msg,
                    title=f"💡 CloudEMS — Verschuif {name}?",
                    notification_id=f"cloudems_shift_{dtype}",
                )
            except Exception:
                pass

            self._last_advice[dtype] = now

        return advices

    def _find_best_hour(self, forecast: list[dict], hours_ahead: int = 8) -> dict | None:
        if not forecast:
            return None
        now = datetime.now(timezone.utc)
        window = []
        for entry in forecast:
            h = entry.get("hours_from_now", entry.get("hour", 0))
            if isinstance(h, (int, float)) and 0 < h <= hours_ahead:
                window.append(entry)
        if not window:
            return None
        best = min(window, key=lambda e: e.get("price", e.get("price_eur_kwh", 9999)))
        return {
            "hours_from_now": best.get("hours_from_now", best.get("hour", 0)),
            "price":          best.get("price", best.get("price_eur_kwh", 0)),
            "label":          best.get("label", f"over {best.get('hours_from_now', 0):.0f} uur"),
        }
