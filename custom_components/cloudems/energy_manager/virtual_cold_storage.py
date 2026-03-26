# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Virtual Cold Storage v1.0.0

Gebruikt vrieskast/vriezer als thermische batterij:
  - Super-cool: bij negatieve prijs of hoog PV-surplus → koel naar min_temp_c
  - Uitschakel-venster: bij avondpiek → schakel uit, laat opwarmen naar max_temp_c
  - Leert opwarm/afkoelsnelheid van de specifieke vriezer

Werkt via slimme stekker (switch entity).
Optioneel: temperatuursensor voor feedback-loop.

Configuratie per apparaat:
  entity_id         str   — switch entity
  label             str   — naam (bijv. "Vriezer garage")
  temp_sensor       str?  — temperatuursensor entity (°C)
  min_temp_c        float — super-cool doel (bijv. -24.0)
  max_temp_c        float — maximale toelaatbare temp (bijv. -16.0)
  nominal_temp_c    float — normale setpoint (bijv. -18.0)
  super_cool_surplus_w  float — PV-surplus (W) waarboven super-cool start (bijv. 500)
  price_off_eur_kwh float — prijs waarboven uitschakelen (bijv. 0.25)
  active            bool  — module in/uitschakelen
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

STORAGE_KEY     = "cloudems_virtual_cold_storage_v1"
STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__)

# Standaard parameters
DEFAULT_MIN_TEMP    = -24.0   # super-cool doel
DEFAULT_MAX_TEMP    = -16.0   # maximale toelaatbare temp
DEFAULT_NOMINAL     = -18.0   # normale temp
DEFAULT_SURPLUS_W   = 800.0   # PV-surplus drempel voor super-cool
DEFAULT_PRICE_OFF   = 0.25    # prijs drempel voor uitschakelen

# Leersnelheid thermisch model (EMA factor)
LEARN_ALPHA = 0.15


@dataclass
class ColdStorageConfig:
    entity_id:           str
    label:               str         = ""
    temp_sensor:         Optional[str] = None
    min_temp_c:          float       = DEFAULT_MIN_TEMP
    max_temp_c:          float       = DEFAULT_MAX_TEMP
    nominal_temp_c:      float       = DEFAULT_NOMINAL
    super_cool_surplus_w: float      = DEFAULT_SURPLUS_W
    price_off_eur_kwh:   float       = DEFAULT_PRICE_OFF
    active:              bool        = True

    @classmethod
    def from_dict(cls, d: dict) -> "ColdStorageConfig":
        return cls(
            entity_id            = d["entity_id"],
            label                = d.get("label", d["entity_id"]),
            temp_sensor          = d.get("temp_sensor"),
            min_temp_c           = float(d.get("min_temp_c", DEFAULT_MIN_TEMP)),
            max_temp_c           = float(d.get("max_temp_c", DEFAULT_MAX_TEMP)),
            nominal_temp_c       = float(d.get("nominal_temp_c", DEFAULT_NOMINAL)),
            super_cool_surplus_w = float(d.get("super_cool_surplus_w", DEFAULT_SURPLUS_W)),
            price_off_eur_kwh    = float(d.get("price_off_eur_kwh", DEFAULT_PRICE_OFF)),
            active               = bool(d.get("active", True)),
        )


@dataclass
class ColdStorageState:
    """Runtime state per vriezer."""
    entity_id:       str
    label:           str
    mode:            str    = "nominal"   # nominal | super_cool | off_peak
    last_temp_c:     Optional[float] = None
    last_switch_ts:  float  = 0.0
    # Geleerd thermisch model
    warmup_rate_c_per_min:   float = 0.03   # °C/min opwarmen zonder stroom
    cooldown_rate_c_per_min: float = 0.08   # °C/min afkoelen met stroom
    model_samples:           int   = 0
    # Tijdstip waarop super-cool gestart is
    super_cool_start_ts:     float = 0.0
    # Tijdstip waarop off-peak gestart is
    off_peak_start_ts:       float = 0.0


class VirtualColdStorageManager:
    """Beheert meerdere vriezers als thermische batterij."""

    def __init__(self, hass: HomeAssistant, configs: list[dict]) -> None:
        self._hass    = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._configs: list[ColdStorageConfig] = [
            ColdStorageConfig.from_dict(c) for c in configs
            if c.get("entity_id")
        ]
        self._states: dict[str, ColdStorageState] = {
            cfg.entity_id: ColdStorageState(
                entity_id = cfg.entity_id,
                label     = cfg.label,
            )
            for cfg in self._configs
        }

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        if saved:
            self.load_persist(saved)
            _LOGGER.debug("VirtualColdStorage: thermisch model hersteld")

    async def async_save(self) -> None:
        await self._store.async_save(self.to_persist())

    def load_persist(self, saved: dict) -> None:
        """Herstel geleerde thermische modellen na herstart."""
        for eid, d in saved.items():
            if eid in self._states:
                st = self._states[eid]
                st.warmup_rate_c_per_min   = float(d.get("warmup_rate", st.warmup_rate_c_per_min))
                st.cooldown_rate_c_per_min = float(d.get("cooldown_rate", st.cooldown_rate_c_per_min))
                st.model_samples           = int(d.get("model_samples", 0))
                st.mode                    = d.get("mode", "nominal")
                _LOGGER.debug("VirtualColdStorage: %s geladen (warmup=%.3f°C/min)", eid, st.warmup_rate_c_per_min)

    def to_persist(self) -> dict:
        """Sla geleerde modellen op."""
        return {
            eid: {
                "warmup_rate":   st.warmup_rate_c_per_min,
                "cooldown_rate": st.cooldown_rate_c_per_min,
                "model_samples": st.model_samples,
                "mode":          st.mode,
            }
            for eid, st in self._states.items()
        }

    def _read_temp(self, cfg: ColdStorageConfig) -> Optional[float]:
        """Lees temperatuursensor als geconfigureerd."""
        if not cfg.temp_sensor:
            return None
        state = self._hass.states.get(cfg.temp_sensor)
        if not state:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _switch_on(self, cfg: ColdStorageConfig) -> None:
        try:
            self._hass.async_create_task(
                self._hass.services.async_call(
                    "switch", "turn_on", {"entity_id": cfg.entity_id}, blocking=False
                )
            )
        except Exception as e:
            _LOGGER.debug("VirtualColdStorage: turn_on %s fout: %s", cfg.entity_id, e)

    def _switch_off(self, cfg: ColdStorageConfig) -> None:
        try:
            self._hass.async_create_task(
                self._hass.services.async_call(
                    "switch", "turn_off", {"entity_id": cfg.entity_id}, blocking=False
                )
            )
        except Exception as e:
            _LOGGER.debug("VirtualColdStorage: turn_off %s fout: %s", cfg.entity_id, e)

    def _is_on(self, cfg: ColdStorageConfig) -> bool:
        state = self._hass.states.get(cfg.entity_id)
        return state is not None and state.state == "on"

    def _update_thermal_model(
        self,
        st: ColdStorageState,
        temp_now: float,
        was_on: bool,
        elapsed_min: float,
    ) -> None:
        """Update geleerde opwarm/afkoelsnelheid via EMA."""
        if elapsed_min < 0.5 or st.last_temp_c is None:
            return
        delta = temp_now - st.last_temp_c
        rate  = abs(delta) / elapsed_min
        if rate < 0.001:
            return

        if not was_on and delta > 0:
            # Opwarmen (geen stroom)
            st.warmup_rate_c_per_min = (
                st.warmup_rate_c_per_min * (1 - LEARN_ALPHA) + rate * LEARN_ALPHA
            )
        elif was_on and delta < 0:
            # Afkoelen (stroom aan)
            st.cooldown_rate_c_per_min = (
                st.cooldown_rate_c_per_min * (1 - LEARN_ALPHA) + rate * LEARN_ALPHA
            )
        st.model_samples += 1

    def estimated_hours_cold(self, cfg: ColdStorageConfig) -> float:
        """Schat hoeveel uur de vriezer koud blijft zonder stroom.

        Gebaseerd op geleerde opwarmsnelheid en huidige temperatuur.
        Returns: uren dat de vriezer onder max_temp_c blijft.
        """
        st = self._states.get(cfg.entity_id)
        if not st or st.last_temp_c is None:
            return 0.0
        temp_margin = cfg.max_temp_c - st.last_temp_c  # negatief = ruimte beschikbaar
        if temp_margin <= 0 or st.warmup_rate_c_per_min < 0.001:
            return 0.0
        return (temp_margin / st.warmup_rate_c_per_min) / 60.0

    def tick(self, data: dict) -> list[dict]:
        """Hoofdlus — aanroepen elke coordinator tick.

        Returns: lijst van acties genomen deze tick.
        """
        solar_surplus_w = float(data.get("solar_surplus_w", 0.0))
        price_now       = float(
            data.get("epex_price_now", data.get("current_price_eur_kwh", 0.25))
        )
        now_ts = time.time()
        actions = []

        for cfg in self._configs:
            if not cfg.active:
                continue

            st = self._states.get(cfg.entity_id)
            if not st:
                continue

            # Cooldown na laatste schakelactie (60s)
            if now_ts - st.last_switch_ts < 60:
                continue

            temp_now = self._read_temp(cfg)
            was_on   = self._is_on(cfg)

            # Update thermisch model als temperatuurdata beschikbaar
            if temp_now is not None and st.last_temp_c is not None:
                elapsed_min = (now_ts - st.last_switch_ts) / 60.0
                self._update_thermal_model(st, temp_now, was_on, elapsed_min)

            if temp_now is not None:
                st.last_temp_c = temp_now

            # ── Beslissingslogica ─────────────────────────────────────────────

            # 1. Temperatuur te hoog → altijd inschakelen (veiligheid)
            if temp_now is not None and temp_now >= cfg.max_temp_c:
                if not was_on:
                    self._switch_on(cfg)
                    st.mode = "nominal"
                    st.last_switch_ts = now_ts
                    actions.append({
                        "entity_id": cfg.entity_id, "label": cfg.label,
                        "action": "turn_on", "reason": f"temp {temp_now:.1f}°C >= max {cfg.max_temp_c:.1f}°C"
                    })
                    _LOGGER.info("VirtualColdStorage: %s AAN — temp te hoog (%.1f°C)", cfg.label, temp_now)
                continue

            # 2. Super-cool: PV-surplus hoog OF prijs negatief
            super_cool_trigger = (
                solar_surplus_w >= cfg.super_cool_surplus_w
                or price_now < 0
            )
            if super_cool_trigger:
                # Super-cool: alleen uitvoeren als temp nog niet op min_temp_c
                if temp_now is None or temp_now > cfg.min_temp_c:
                    if not was_on:
                        self._switch_on(cfg)
                        st.mode = "super_cool"
                        st.super_cool_start_ts = now_ts
                        st.last_switch_ts = now_ts
                        actions.append({
                            "entity_id": cfg.entity_id, "label": cfg.label,
                            "action": "super_cool",
                            "reason": f"surplus {solar_surplus_w:.0f}W / prijs {price_now:.4f}€"
                        })
                        _LOGGER.info(
                            "VirtualColdStorage: %s SUPER-COOL — surplus %.0fW, prijs %.3f€/kWh",
                            cfg.label, solar_surplus_w, price_now
                        )
                else:
                    # Al op min_temp — schakel uit om te sparen
                    if was_on:
                        self._switch_off(cfg)
                        st.mode = "off_peak"
                        st.off_peak_start_ts = now_ts
                        st.last_switch_ts = now_ts
                        actions.append({
                            "entity_id": cfg.entity_id, "label": cfg.label,
                            "action": "turn_off",
                            "reason": f"super-cool doel bereikt ({temp_now:.1f}°C)"
                        })
                continue

            # 3. Off-peak: prijs hoog → uitschakelen als thermische buffer het toelaat
            if price_now >= cfg.price_off_eur_kwh:
                hours_cold = self.estimated_hours_cold(cfg)
                # Alleen uitschakelen als we verwachten dat de vriezer koud genoeg blijft
                # OF als we geen temperatuurdata hebben maar er is genoeg surplus geweest
                safe_to_off = (
                    hours_cold >= 1.0  # minstens 1 uur koud
                    or (temp_now is not None and temp_now <= cfg.nominal_temp_c - 2)  # 2°C buffer
                    or st.mode == "super_cool"  # net super-gekoeld
                )
                if was_on and safe_to_off:
                    self._switch_off(cfg)
                    st.mode = "off_peak"
                    st.off_peak_start_ts = now_ts
                    st.last_switch_ts = now_ts
                    actions.append({
                        "entity_id": cfg.entity_id, "label": cfg.label,
                        "action": "turn_off",
                        "reason": f"prijs {price_now:.3f}€ >= drempel, {hours_cold:.1f}u koud buffer"
                    })
                    _LOGGER.info(
                        "VirtualColdStorage: %s UIT — prijs %.3f€/kWh, buffer %.1fu",
                        cfg.label, price_now, hours_cold
                    )
                continue

            # 4. Nominaal: zorg dat vriezer aan is
            if not was_on and st.mode not in ("super_cool",):
                self._switch_on(cfg)
                st.mode = "nominal"
                st.last_switch_ts = now_ts
                actions.append({
                    "entity_id": cfg.entity_id, "label": cfg.label,
                    "action": "turn_on", "reason": "nominale modus hersteld"
                })

        return actions

    def get_status(self) -> list[dict]:
        """Status voor dashboard sensor."""
        result = []
        for cfg in self._configs:
            st = self._states.get(cfg.entity_id)
            if not st:
                continue
            result.append({
                "entity_id":         cfg.entity_id,
                "label":             cfg.label,
                "mode":              st.mode,
                "temp_c":            round(st.last_temp_c, 1) if st.last_temp_c is not None else None,
                "warmup_rate":       round(st.warmup_rate_c_per_min, 4),
                "cooldown_rate":     round(st.cooldown_rate_c_per_min, 4),
                "model_samples":     st.model_samples,
                "hours_cold_est":    round(self.estimated_hours_cold(cfg), 1),
                "temp_sensor":       cfg.temp_sensor,
                "min_temp_c":        cfg.min_temp_c,
                "max_temp_c":        cfg.max_temp_c,
                "nominal_temp_c":    cfg.nominal_temp_c,
            })
        return result
