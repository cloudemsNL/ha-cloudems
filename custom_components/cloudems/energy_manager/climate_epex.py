# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.
"""
CloudEMS Climate EPEX Compensatie

Geen zone-beheer, geen aanwezigheidsdetectie.
Enkel kleine temperatuur-offsets op basis van EPEX prijs:
  - Goedkoop uur  → WP: +offset (voorverwarmen), Airco: -offset (voorkoelen)
  - Duur uur      → WP: -offset (minder verbruiken), Airco: +offset (minder koelen)

De module leert het gebruikersprofiel: wanneer wil de gebruiker verwarmen/koelen?
Offset wordt alleen toegepast als het device actief is (verwarmt of koelt).
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_climate_epex_v1"
STORAGE_VERSION = 1
SAVE_INTERVAL_S = 120

# Standaard offset in °C
DEFAULT_OFFSET_C  = 0.5   # verschil tussen goedkoop/duur uur
PRICE_CHEAP_PCT   = 0.85  # onder 85% van daggemiddelde = goedkoop
PRICE_DEAR_PCT    = 1.20  # boven 120% van daggemiddelde = duur


@dataclass
class ClimateEpexDevice:
    """Configuratie van één WP of Airco."""
    entity_id:      str
    label:          str
    device_type:    str    # "heat_pump" | "airco" | "hybrid" | "floor_heating"
    power_entity:   str    # vermogensensor
    offset_c:       float  # max offset in °C
    enabled:        bool   = True

    def to_dict(self) -> dict:
        return {
            "entity_id":    self.entity_id,
            "label":        self.label,
            "device_type":  self.device_type,
            "power_entity": self.power_entity,
            "offset_c":     self.offset_c,
            "enabled":      self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClimateEpexDevice":
        return cls(
            entity_id=d["entity_id"],
            label=d.get("label", d["entity_id"]),
            device_type=d.get("device_type", "heat_pump"),
            power_entity=d.get("power_entity", ""),
            offset_c=float(d.get("offset_c", DEFAULT_OFFSET_C)),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class ClimateEpexStatus:
    """Live status per device voor de sensor."""
    entity_id:        str
    label:            str
    device_type:      str
    current_temp:     Optional[float]
    target_temp:      Optional[float]
    base_setpoint:    Optional[float]   # geleerd basissetpoint
    applied_offset:   float             # huidige actieve offset
    power_w:          float
    mode:             str               # "cheap" | "dear" | "neutral" | "off"
    action:           str               # "heating" | "cooling" | "idle" | "off"
    is_on:            bool


class ClimateEpexController:
    """
    Leert gebruikerssetpoints en past EPEX-offsets toe.

    Aanroep vanuit coordinator elke cyclus:
        ctrl.tick(price_info)
        statuses = ctrl.get_status()
    """

    def __init__(self, hass: HomeAssistant, devices: List[ClimateEpexDevice]) -> None:
        self.hass     = hass
        self._devices = devices
        self._store   = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Geleerde basissetpoints per entity_id per uur van de dag
        # { entity_id: { hour: ema_setpoint } }
        self._learned: Dict[str, Dict[int, float]] = {}

        # Huidige actieve offsets { entity_id: offset_c }
        self._active_offsets: Dict[str, float] = {}

        self._dirty     = False
        self._last_save = 0.0
        self._high_log_cb = None

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for eid, hours in saved.get("learned", {}).items():
            self._learned[eid] = {int(h): float(v) for h, v in hours.items()}
        _LOGGER.info("ClimateEpex: %d devices geladen", len(self._devices))

    def set_log_callback(self, cb) -> None:
        self._high_log_cb = cb

    def _high_log(self, category: str, payload: dict) -> None:
        if not self._high_log_cb:
            return
        try:
            import asyncio as _aio
            _aio.ensure_future(self._high_log_cb(category, payload))
        except Exception:
            pass

    def _state(self, entity_id: str):
        return self.hass.states.get(entity_id)

    def _temp(self, entity_id: str, attr: str) -> Optional[float]:
        st = self._state(entity_id)
        if not st:
            return None
        v = st.attributes.get(attr)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _power_w(self, device: ClimateEpexDevice) -> float:
        if not device.power_entity:
            return 0.0
        st = self._state(device.power_entity)
        if not st or st.state in ("unavailable", "unknown", ""):
            return 0.0
        try:
            pw = float(st.state)
            unit = st.attributes.get("unit_of_measurement", "W")
            if unit.lower() == "kw":
                pw *= 1000
            return abs(pw)
        except (ValueError, TypeError):
            return 0.0

    def _learn_setpoint(self, entity_id: str, setpoint: float) -> None:
        """EMA-leren van het gewenste setpoint per uur."""
        hour = datetime.now(timezone.utc).hour
        if entity_id not in self._learned:
            self._learned[entity_id] = {}
        old = self._learned[entity_id].get(hour, setpoint)
        # EMA alpha=0.1 — langzaam leren
        self._learned[entity_id][hour] = round(old * 0.9 + setpoint * 0.1, 2)
        self._dirty = True

    def _base_setpoint(self, entity_id: str) -> Optional[float]:
        """Geleerd basissetpoint voor dit uur."""
        hour = datetime.now(timezone.utc).hour
        return self._learned.get(entity_id, {}).get(hour)

    def tick(self, price_info: dict) -> None:
        """
        Verwerk EPEX prijs en pas offsets toe op alle geconfigureerde devices.
        price_info: coordinator price_info dict met avg_today, current_price
        """
        if not price_info:
            return

        current  = float(price_info.get("current_price") or price_info.get("price_eur_kwh") or 0)
        avg      = float(price_info.get("avg_today") or current or 0.01)

        is_cheap = current < avg * PRICE_CHEAP_PCT
        is_dear  = current > avg * PRICE_DEAR_PCT

        for dev in self._devices:
            if not dev.enabled:
                continue

            st = self._state(dev.entity_id)
            if not st or st.state in ("unavailable", "unknown", "off"):
                self._active_offsets[dev.entity_id] = 0.0
                continue

            target = self._temp(dev.entity_id, "temperature")
            current_temp = self._temp(dev.entity_id, "current_temperature")
            hvac_action = st.attributes.get("hvac_action", "")
            is_heating = hvac_action in ("heating",) or st.state == "heat"
            is_cooling = hvac_action in ("cooling",) or st.state == "cool"

            if target is None:
                continue

            # Leer het basissetpoint (als er geen actieve offset is)
            current_offset = self._active_offsets.get(dev.entity_id, 0.0)
            base = target - current_offset  # terug naar het originele setpoint
            self._learn_setpoint(dev.entity_id, base)

            # Bepaal nieuwe offset
            new_offset = 0.0
            if dev.device_type in ("heat_pump", "hybrid"):
                if is_cheap and is_heating:
                    new_offset = dev.offset_c   # voorverwarmen
                elif is_dear and is_heating:
                    new_offset = -dev.offset_c  # minder verbruiken
            elif dev.device_type == "airco":
                if is_cheap and is_cooling:
                    new_offset = -dev.offset_c  # voorkoelen
                elif is_dear and is_cooling:
                    new_offset = dev.offset_c   # minder koelen
            elif dev.device_type == "floor_heating":
                # v5.5.331: vloerverwarming — zelfde logica als heat_pump
                # Goedkoop: hoger setpoint (thermische opslag in vloer)
                # Duur: lager setpoint (vertraagde afgifte benut opgeslagen warmte)
                if is_cheap and is_heating:
                    new_offset = dev.offset_c
                elif is_dear and is_heating:
                    new_offset = -dev.offset_c

            # Alleen aanpassen als offset veranderd is
            old_offset = self._active_offsets.get(dev.entity_id, 0.0)
            if abs(new_offset - old_offset) > 0.05:
                new_target = round(base + new_offset, 1)
                self._apply_offset(dev, new_target, new_offset, is_cheap, is_dear)

            self._active_offsets[dev.entity_id] = new_offset

    def _apply_offset(self, dev: ClimateEpexDevice, new_target: float,
                      offset: float, is_cheap: bool, is_dear: bool) -> None:
        """Stuur setpoint naar het climate entity."""
        try:
            import asyncio as _aio
            _aio.ensure_future(self._async_set_temp(dev, new_target))
            mode = "cheap" if is_cheap else ("dear" if is_dear else "neutral")
            _LOGGER.info(
                "ClimateEpex: %s → %.1f°C (offset %+.1f, %s)",
                dev.label, new_target, offset, mode
            )
            self._high_log("climate_epex_offset", {
                "device":      dev.label,
                "entity_id":   dev.entity_id,
                "new_target":  new_target,
                "offset_c":    offset,
                "price_mode":  mode,
            })
        except Exception as e:
            _LOGGER.debug("ClimateEpex: offset apply fout: %s", e)

    async def _async_set_temp(self, dev: ClimateEpexDevice, target: float) -> None:
        try:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": dev.entity_id, "temperature": target},
                blocking=False,
            )
            # Watchdog: controleer elke 60s of de temperature klopt
            _wd = getattr(getattr(self, "hass", None), "_cloudems_watchdog", None)
            if _wd is None:
                # Probeer via coordinator
                import homeassistant.core as _ha_core
                for _d in (self.hass.data or {}).values():
                    _coord = getattr(_d, "get", lambda k, d=None: d)("coordinator")
                    if hasattr(_coord, "_actuator_watchdog"):
                        _wd = _coord._actuator_watchdog; break
            if _wd:
                async def _restore_temp(eid=dev.entity_id, t=target):
                    await self.hass.services.async_call("climate", "set_temperature", {"entity_id": eid, "temperature": t}, blocking=False)
                _wd.register(f"climate_epex_{dev.entity_id}", dev.entity_id, str(target), _restore_temp, tolerance=0.5)
        except Exception as e:
            _LOGGER.debug("ClimateEpex: set_temperature fout voor %s: %s", dev.entity_id, e)

    def get_status(self) -> List[dict]:
        """Geef live status voor alle devices."""
        result = []
        for dev in self._devices:
            st = self._state(dev.entity_id)
            if not st:
                continue

            current_temp = self._temp(dev.entity_id, "current_temperature")
            target_temp  = self._temp(dev.entity_id, "temperature")
            offset       = self._active_offsets.get(dev.entity_id, 0.0)
            base         = round(target_temp - offset, 1) if target_temp is not None else None
            power_w      = self._power_w(dev)
            hvac_action  = st.attributes.get("hvac_action", "idle")
            is_on        = st.state not in ("off", "unavailable", "unknown")

            if offset > 0:
                mode = "cheap"
            elif offset < 0:
                mode = "dear"
            elif not is_on:
                mode = "off"
            else:
                mode = "neutral"

            result.append({
                "entity_id":      dev.entity_id,
                "label":          dev.label,
                "device_type":    dev.device_type,
                "current_temp":   current_temp,
                "target_temp":    target_temp,
                "base_setpoint":  base,
                "applied_offset": offset,
                "power_w":        round(power_w, 1),
                "mode":           mode,
                "action":         hvac_action,
                "is_on":          is_on,
                "state":          st.state,
                "learned_today":  list(self._learned.get(dev.entity_id, {}).values()),
            })
        return result

    def get_total_power_w(self) -> float:
        return sum(self._power_w(d) for d in self._devices if d.enabled)

    async def async_save(self) -> None:
        await self._store.async_save({
            "learned": {
                eid: {str(h): v for h, v in hours.items()}
                for eid, hours in self._learned.items()
            }
        })
        self._dirty = False
        self._last_save = time.time()

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()
