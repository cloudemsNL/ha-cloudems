# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
NilmGroupTracker — v4.6.584

Groepeert NILM-apparaten in categorieën (zoals Regelneef/Greenchoice),
berekent vermogen + dagkosten per groep, houdt maandhistorie bij en
genereert onboarding-hints als verwachte categorieën ontbreken.

Groepen:
  verlichting    — light, led, lamp
  koken          — oven, dishwasher, coffee, microwave, kettle
  wasgoed        — washer, dryer, washing_machine
  koeling        — refrigerator, fridge, freezer
  entertainment  — entertainment, tv, computer, gaming, audio
  verwarming     — heat, heat_pump, electric_heater, boiler, cv_boiler, floor_heat
  transport      — ev_charger, ebike, charger
  gereedschap    — power_tool
  overig         — socket, unknown, en alles wat niet past

Cloud-ready: geen directe HA-afhankelijkheden buiten async_setup().
"""

from __future__ import annotations
import logging
import time
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "cloudems_nilm_groups_v1"

# ── Groep-mapping: device_type → groep-id ────────────────────────────────────
_TYPE_TO_GROUP: dict[str, str] = {
    # Verlichting
    "light":              "verlichting",
    "led":                "verlichting",
    "lamp":               "verlichting",
    # Koken
    "oven":               "koken",
    "dishwasher":         "koken",
    "coffee":             "koken",
    "microwave":          "koken",
    "kettle":             "koken",
    # Wasgoed
    "washer":             "wasgoed",
    "dryer":              "wasgoed",
    "washing_machine":    "wasgoed",
    # Koeling
    "refrigerator":       "koeling",
    "fridge":             "koeling",
    "freezer":            "koeling",
    # Entertainment & computers
    "entertainment":      "entertainment",
    "tv":                 "entertainment",
    "computer":           "entertainment",
    "gaming":             "entertainment",
    "audio":              "entertainment",
    # Verwarming
    "heat":               "verwarming",
    "heat_pump":          "verwarming",
    "air_source_heat_pump": "verwarming",
    "electric_heater":    "verwarming",
    "boiler":             "verwarming",
    "cv_boiler":          "verwarming",
    "floor_heat":         "verwarming",
    "underfloor":         "verwarming",
    # Transport
    "ev_charger":         "transport",
    "ev":                 "transport",
    "ebike":              "transport",
    "charger":            "transport",
    # Gereedschap
    "power_tool":         "gereedschap",
    # Overig / standby
    "socket":             "overig",
    "unknown":            "overig",
}

# Groepen met hun label, icoon en verwacht of ze aanwezig zijn in een gemiddeld huishouden
_GROUP_META: dict[str, dict] = {
    "verlichting":   {"label": "Verlichting",   "icon": "💡", "expected": True},
    "koken":         {"label": "Koken",          "icon": "🍳", "expected": True},
    "wasgoed":       {"label": "Wasgoed",        "icon": "👕", "expected": True},
    "koeling":       {"label": "Koeling",        "icon": "🧊", "expected": True},
    "entertainment": {"label": "Entertainment",  "icon": "📺", "expected": True},
    "verwarming":    {"label": "Verwarming",     "icon": "🔥", "expected": False},
    "transport":     {"label": "Transport",      "icon": "🚗", "expected": False},
    "gereedschap":   {"label": "Gereedschap",    "icon": "🔧", "expected": False},
    "overig":        {"label": "Overig / standby", "icon": "🔌", "expected": False},
}

# Vragen voor onboarding-hints (groep → vraag als die groep ontbreekt)
_ONBOARDING_HINTS: dict[str, str] = {
    "wasgoed":       "We zien nog geen wasmachine of droger. Heb je die? Bevestig het apparaat in de NILM-lijst.",
    "koeling":       "We zien nog geen koelkast of vriezer. Heb je die? Ze draaien 24/7 en zijn goed zichtbaar.",
    "koken":         "We zien nog geen vaatwasser of oven. Heb je die? Bevestig het apparaat om groepskosten te zien.",
    "verlichting":   "We zien nog geen verlichting. Heb je slimme lampen of spotjes? Koppel ze als smart plug.",
    "entertainment": "We zien nog geen tv of computer. Heb je die? Bevestig het apparaat in de NILM-lijst.",
}


def _device_group(device_type: str) -> str:
    """Vertaal device_type naar groep-id."""
    return _TYPE_TO_GROUP.get((device_type or "").lower(), "overig")


class NilmGroupTracker:
    """
    Groepeert NILM-apparaten, berekent kosten per groep,
    houdt maandhistorie bij en genereert onboarding-hints.

    Gebruik:
        tracker = NilmGroupTracker(hass)
        await tracker.async_setup()
        result = tracker.update(devices, price_eur_kwh)
        # result = {groups, onboarding_hints, month_history}
    """

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store = None
        self._month_history: dict[str, dict[str, float]] = {}
        # {YYYY-MM: {groep_id: kwh}}
        self._current_month_kwh: dict[str, float] = {}
        self._last_month_key: str = ""
        self._last_save: float = 0.0

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
        try:
            saved = await self._store.async_load() or {}
            self._month_history   = saved.get("month_history", {})
            self._current_month_kwh = saved.get("current_month_kwh", {})
            self._last_month_key  = saved.get("last_month_key", "")
        except Exception as exc:
            _LOGGER.warning("NilmGroupTracker: kon opgeslagen data niet laden: %s", exc)

    def update(self, devices: list[dict], price_eur_kwh: float) -> dict:
        """
        Verwerk apparatenlijst → groepsoverzicht.

        Args:
            devices:        lijst van NILM-device dicts (uit coordinator.data["nilm_devices"])
            price_eur_kwh:  huidige energieprijs voor kostenschatting

        Returns dict met:
            groups          — lijst van groep-dicts
            onboarding_hints — lijst van hints voor ontbrekende categorieën
            month_history   — {YYYY-MM: {groep: kwh}} (laatste 3 maanden)
        """
        now = time.time()
        month_key = date.today().strftime("%Y-%m")

        # Rollover bij maandwisseling
        if self._last_month_key and self._last_month_key != month_key:
            self._month_history[self._last_month_key] = dict(self._current_month_kwh)
            # Bewaar max 12 maanden
            if len(self._month_history) > 12:
                oldest = sorted(self._month_history.keys())[0]
                del self._month_history[oldest]
            self._current_month_kwh = {}
        self._last_month_key = month_key

        # ── Per groep aggregeren ──────────────────────────────────────────────
        group_power:   dict[str, float] = {g: 0.0 for g in _GROUP_META}
        group_active:  dict[str, int]   = {g: 0   for g in _GROUP_META}
        group_devices: dict[str, list]  = {g: []  for g in _GROUP_META}
        group_kwh_today: dict[str, float] = {g: 0.0 for g in _GROUP_META}

        for d in devices:
            dt    = (d.get("device_type") or "unknown").lower()
            grp   = _device_group(dt)
            pw    = float(d.get("power_w") or d.get("current_power") or 0)
            is_on = bool(d.get("is_on"))
            kwh   = float(d.get("today_kwh") or d.get("energy_kwh_today") or 0)

            group_devices[grp].append({
                "name":        d.get("name") or d.get("device_type") or "Apparaat",
                "device_type": dt,
                "power_w":     round(pw, 1),
                "is_on":       is_on,
                "confirmed":   bool(d.get("confirmed")),
                "source_type": d.get("source_type", "nilm"),
                "today_kwh":   round(kwh, 3),
            })

            if is_on:
                group_power[grp]  += pw
                group_active[grp] += 1
            group_kwh_today[grp]  += kwh

        # kWh per groep bijhouden in lopende maand (EMA-achtig: dagkwh sommeren)
        for grp, kwh in group_kwh_today.items():
            if kwh > 0:
                self._current_month_kwh[grp] = round(
                    self._current_month_kwh.get(grp, 0.0) + kwh, 3
                )

        # ── Groepen samenstellen ──────────────────────────────────────────────
        price = max(price_eur_kwh or 0.0, 0.0)
        groups = []
        for grp_id, meta in _GROUP_META.items():
            devices_in_group = group_devices[grp_id]
            if not devices_in_group:
                continue
            pw    = group_power[grp_id]
            kwh_d = group_kwh_today[grp_id]
            cost_today = round(kwh_d * price, 3)
            groups.append({
                "id":           grp_id,
                "label":        meta["label"],
                "icon":         meta["icon"],
                "power_w":      round(pw, 1),
                "active_count": group_active[grp_id],
                "device_count": len(devices_in_group),
                "today_kwh":    round(kwh_d, 3),
                "cost_today_eur": cost_today,
                "devices":      devices_in_group,
                "month_kwh":    round(self._current_month_kwh.get(grp_id, 0.0), 3),
                "month_cost_eur": round(
                    self._current_month_kwh.get(grp_id, 0.0) * price, 2
                ),
            })

        # Sorteer: meeste vermogen bovenaan
        groups.sort(key=lambda g: g["power_w"], reverse=True)

        # ── Onboarding-hints ─────────────────────────────────────────────────
        present_groups = {g["id"] for g in groups}
        hints = []
        for grp_id, hint_text in _ONBOARDING_HINTS.items():
            if grp_id not in present_groups:
                meta = _GROUP_META[grp_id]
                hints.append({
                    "group_id": grp_id,
                    "label":    meta["label"],
                    "icon":     meta["icon"],
                    "hint":     hint_text,
                })

        # ── Maandhistorie (laatste 3 maanden voor dashboard) ─────────────────
        recent_months = sorted(self._month_history.keys())[-3:]
        month_history = {m: self._month_history[m] for m in recent_months}
        # Voeg lopende maand toe
        if self._current_month_kwh:
            month_history[month_key] = dict(self._current_month_kwh)

        # Sla op elke 60s
        if now - self._last_save > 60:
            self.hass.async_create_task(self._async_save())
            self._last_save = now

        return {
            "groups":           groups,
            "onboarding_hints": hints,
            "month_history":    month_history,
            "total_groups":     len(groups),
            "groups_with_power": sum(1 for g in groups if g["power_w"] > 0),
        }

    async def _async_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save({
                "month_history":    self._month_history,
                "current_month_kwh": self._current_month_kwh,
                "last_month_key":   self._last_month_key,
            })
        except Exception as exc:
            _LOGGER.debug("NilmGroupTracker: opslaan mislukt: %s", exc)
