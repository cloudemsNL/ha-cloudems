# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — Vehicle-to-Home (V2H) Manager v1.0.0

Maakt gebruik van bidirectionele laadpalen om de auto als thuisbatterij
te gebruiken bij dure EPEX-uren of netuitval.

Supportede hardware via HA:
  - Wallbox Quasar 2        (wallbox integratie)
  - Hyundai/Kia (Ioniq 5/6, EV6) via OCPP bidirectioneel
  - EVCC brug (evcc_provider.py) met V2H modus

How it works:
  1. Detecteer bidirectionele laadpaal
  2. Monitor SOC auto + EPEX prijs
  3. Ontlaad auto → huis bij: hoge EPEX prijs EN voldoende SOC
  4. Stop als: SOC auto onder minimum OF prijs daalt
  5. Log sessie voor financiële rapportage

Configuratie (via config_flow):
  v2h_enabled             bool
  v2h_charger_entity      entity_id van laadpaal
  v2h_car_soc_entity      entity_id van auto SOC sensor
  v2h_min_soc_pct         minimum auto SOC om te bewaren (default 30%)
  v2h_price_threshold     EPEX prijs drempel voor ontladen (€/kWh, default 0.25)
  v2h_max_discharge_w     max ontlaadvermogen W (default 3700 = 1-fase 16A)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Default settings
DEFAULT_MIN_SOC_PCT      = 30.0    # always preserve minimum 30% voor rijden
DEFAULT_PRICE_THRESHOLD  = 0.25    # discharge at > €0.25/kWh
DEFAULT_MAX_DISCHARGE_W  = 3700.0  # 1-fase 16A = 3.7 kW

# Wallbox Quasar entiteit-patronen
_WALLBOX_BIDIRECT_PATTERNS = (
    "wallbox_quasar", "wallbox_bidirectional", "quasar_2",
    "evcc_v2h", "ocpp_v2h",
)
_CAR_SOC_PATTERNS = (
    "car_battery", "vehicle_battery", "ev_battery_level",
    "hyundai_ev_battery", "kia_ev_battery", "ioniq_battery",
    "tesla_battery_level",
)


@dataclass
class V2HSession:
    """Active V2H session data."""
    start_ts:       float = 0.0
    end_ts:         float = 0.0
    energy_kwh:     float = 0.0   # ontladen kWh
    saving_eur:     float = 0.0   # geschatte besparing
    soc_start:      float = 0.0
    soc_end:        float = 0.0
    reason_stop:    str   = ""
    active:         bool  = False


@dataclass
class V2HStatus:
    """V2H system status for dashboard."""
    enabled:         bool  = False
    available:       bool  = False   # charger found + car connected
    active:          bool  = False   # actively discharging
    car_soc_pct:     Optional[float] = None
    discharge_w:     float = 0.0
    price_eur_kwh:   float = 0.0
    session:         Optional[dict]  = None
    reason:          str   = ""
    charger_entity:  str   = ""
    car_soc_entity:  str   = ""


class V2HManager:
    """
    Vehicle-to-Home manager.

    Integreert auto-batterij als virtuele thuisbatterij voor
    EPEX-price-driven discharge.
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._enabled = config.get("v2h_enabled", False)

        # Configuratie
        self._charger_entity  = config.get("v2h_charger_entity", "")
        self._car_soc_entity  = config.get("v2h_car_soc_entity", "")
        self._min_soc_pct     = float(config.get("v2h_min_soc_pct",     DEFAULT_MIN_SOC_PCT))
        self._price_threshold = float(config.get("v2h_price_threshold", DEFAULT_PRICE_THRESHOLD))
        self._max_discharge_w = float(config.get("v2h_max_discharge_w", DEFAULT_MAX_DISCHARGE_W))

        # Internal state
        self._active_session: Optional[V2HSession] = None
        self._last_action_ts: float = 0.0
        self._action_cooldown: float = 60.0  # min 60s between actions

        # Auto-detection if not configured
        self._detected_charger:  Optional[str] = None
        self._detected_car_soc:  Optional[str] = None

    async def async_setup(self) -> None:
        """Setup: detect V2H hardware if not configured."""
        if not self._charger_entity:
            self._detected_charger = self._detect_bidirectional_charger()
        if not self._car_soc_entity:
            self._detected_car_soc = self._detect_car_soc()

        if self._enabled:
            _LOGGER.info(
                "V2HManager: actief — charger=%s soc=%s min_soc=%.0f%% threshold=€%.3f",
                self._effective_charger, self._effective_car_soc,
                self._min_soc_pct, self._price_threshold,
            )

    @property
    def _effective_charger(self) -> Optional[str]:
        return self._charger_entity or self._detected_charger

    @property
    def _effective_car_soc(self) -> Optional[str]:
        return self._car_soc_entity or self._detected_car_soc

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_available(self) -> bool:
        """True if charger + car SOC are available."""
        return bool(self._effective_charger and self._effective_car_soc)

    def tick(self, current_price_eur_kwh: float, grid_power_w: float) -> V2HStatus:
        """
        Main logic — call every coordinator cycle.

        Returns:
            V2HStatus met huidige toestand en aanbeveling.
        """
        if not self._enabled or not self.is_available:
            return V2HStatus(enabled=self._enabled, available=self.is_available)

        car_soc = self._read_car_soc()
        is_connected = self._is_car_connected()

        status = V2HStatus(
            enabled        = True,
            available      = is_connected,
            car_soc_pct    = car_soc,
            price_eur_kwh  = current_price_eur_kwh,
            charger_entity = self._effective_charger or "",
            car_soc_entity = self._effective_car_soc or "",
        )

        if not is_connected:
            status.reason = "Auto niet aangesloten"
            if self._active_session and self._active_session.active:
                self._stop_session("auto_losgekoppeld")
            return status

        if car_soc is None:
            status.reason = "Auto SOC niet beschikbaar"
            return status

        # Cooldown check
        now = time.time()
        if now - self._last_action_ts < self._action_cooldown:
            status.active = self._active_session is not None and self._active_session.active
            status.reason = "Cooldown actief"
            return status

        # Decision logic
        should_discharge = (
            current_price_eur_kwh >= self._price_threshold
            and car_soc > self._min_soc_pct
            and grid_power_w > 100  # house is consuming power
        )

        should_stop = (
            current_price_eur_kwh < self._price_threshold * 0.8  # price 20% below threshold
            or car_soc <= self._min_soc_pct
            or grid_power_w <= 0  # house no longer consuming power
        )

        if self._active_session and self._active_session.active:
            status.active = True
            status.discharge_w = self._max_discharge_w
            if should_stop:
                self._stop_session(
                    "prijs_gedaald" if current_price_eur_kwh < self._price_threshold * 0.8
                    else f"soc_minimum_{car_soc:.0f}pct"
                )
                status.active = False
                status.reason = "Sessie gestopt"
        elif should_discharge:
            self._start_session(car_soc)
            status.active = True
            status.discharge_w = self._max_discharge_w
            status.reason = f"V2H actief — prijs €{current_price_eur_kwh:.3f}/kWh"
            self._last_action_ts = now
        else:
            status.reason = (
                f"Standby — prijs €{current_price_eur_kwh:.3f} "
                f"(drempel €{self._price_threshold:.2f}), SOC {car_soc:.0f}%"
            )

        if self._active_session:
            status.session = {
                "active":     self._active_session.active,
                "energy_kwh": round(self._active_session.energy_kwh, 3),
                "saving_eur": round(self._active_session.saving_eur, 2),
                "soc_start":  self._active_session.soc_start,
                "duration_m": round((now - self._active_session.start_ts) / 60, 1),
            }

        return status

    # ── Session management ─────────────────────────────────────────────────────────

    def _start_session(self, car_soc: float) -> None:
        self._active_session = V2HSession(
            start_ts   = time.time(),
            soc_start  = car_soc,
            active     = True,
        )
        _LOGGER.info("V2H: sessie gestart (SOC=%.0f%%)", car_soc)

    def _stop_session(self, reason: str) -> None:
        if not self._active_session:
            return
        self._active_session.active     = False
        self._active_session.end_ts     = time.time()
        self._active_session.reason_stop = reason
        duration_h = (self._active_session.end_ts - self._active_session.start_ts) / 3600
        self._active_session.energy_kwh = duration_h * self._max_discharge_w / 1000
        self._active_session.saving_eur = (
            self._active_session.energy_kwh * self._price_threshold * 0.5
        )
        _LOGGER.info(
            "V2H: sessie gestopt (%s) — %.2f kWh, €%.2f bespaard",
            reason, self._active_session.energy_kwh, self._active_session.saving_eur,
        )

    # ── Detection helpers ─────────────────────────────────────────────────────

    def _detect_bidirectional_charger(self) -> Optional[str]:
        """Look for bidirectional charger in HA."""
        for state in self._hass.states.async_all():
            eid = state.entity_id.lower()
            if any(p in eid for p in _WALLBOX_BIDIRECT_PATTERNS):
                _LOGGER.info("V2H: bidirectionele laadpaal gevonden: %s", state.entity_id)
                return state.entity_id
        return None

    def _detect_car_soc(self) -> Optional[str]:
        """Look for car SOC sensor in HA."""
        for state in self._hass.states.async_all("sensor"):
            eid = state.entity_id.lower()
            if any(p in eid for p in _CAR_SOC_PATTERNS):
                _LOGGER.info("V2H: auto SOC sensor gevonden: %s", state.entity_id)
                return state.entity_id
        return None

    def _read_car_soc(self) -> Optional[float]:
        eid = self._effective_car_soc
        if not eid:
            return None
        s = self._hass.states.get(eid)
        if not s or s.state in ("unavailable", "unknown"):
            return None
        try:
            return float(s.state)
        except (ValueError, TypeError):
            return None

    def _is_car_connected(self) -> bool:
        """Check if car is connected to charger."""
        eid = self._effective_charger
        if not eid:
            return False
        s = self._hass.states.get(eid)
        if not s:
            return False
        # Typische states: "charging", "connected", "discharging", "ready"
        return s.state.lower() not in ("disconnected", "unavailable", "unknown", "off")

    def get_status_dict(self) -> dict:
        """Status for coordinator data / sensor attributes."""
        status = self.tick(0.0, 0.0)  # read-only tick without price data
        return {
            "enabled":        self._enabled,
            "available":      self.is_available,
            "charger_entity": self._effective_charger or "",
            "car_soc_entity": self._effective_car_soc or "",
            "min_soc_pct":    self._min_soc_pct,
            "price_threshold":self._price_threshold,
            "detected_charger": self._detected_charger,
        }
