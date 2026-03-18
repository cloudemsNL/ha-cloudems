# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS — UPS Manager (v1.0.0).

Beheert meerdere UPS-systemen met prioriteitsgebaseerd afschakelen.

Ondersteunde integraties:
  - NUT  (Network UPS Tools — meest universeel)
  - APC  (APC UPS HA integratie)
  - Eaton (Eaton HA integratie)
  - Generiek (elke HA sensor met battery_level)

Werking:
  1. Lees UPS status (online / on_battery / low_battery / bypass)
  2. Bereken resterende runtime per UPS
  3. Schakel apparaten af op basis van prioriteit + runtime drempel
  4. Zodra generator actief → herstel alle apparaten
  5. Notificeer bij statuswijziging

Prioriteiten (1=kritiek, 5=laag):
  1  Netwerk, HA server, security — nooit afschakelen
  2  Koelkast, vriezer, medisch — alleen bij <2 min
  3  NAS, servers — bij <5 min
  4  Entertainment, overig — bij <10 min
  5  Niet-essentieel — direct bij battery
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Runtime drempels per prioriteit (minuten)
PRIORITY_RUNTIME_THRESHOLDS = {
    1: 0,    # nooit afschakelen
    2: 2,    # <2 min
    3: 5,    # <5 min
    4: 10,   # <10 min
    5: 999,  # direct bij op batterij
}

# UPS status normalisatie per merk/integratie
STATUS_ONLINE    = {"online", "on_line", "mains", "normal", "nut_online"}
STATUS_BATTERY   = {"on_battery", "battery", "ob", "nut_on_battery"}
STATUS_LOW_BAT   = {"low_battery", "low", "lb", "nut_low_battery", "battery_low"}
STATUS_BYPASS    = {"bypass", "bp", "eco"}
STATUS_FAULT     = {"fault", "off", "overload", "trim", "boost"}

NOTIFY_COOLDOWN_S = 120   # max 1 melding per 2 min per UPS


@dataclass
class UPSDevice:
    """Één gekoppeld apparaat aan een UPS."""
    entity_id:    str
    label:        str
    priority:     int   = 3    # 1=kritiek, 5=laag
    shed_cmd:     str   = "turn_off"  # HA service om af te schakelen
    restore_cmd:  str   = "turn_on"   # HA service om te herstellen
    is_shed:      bool  = False
    shed_ts:      float = 0.0


@dataclass
class UPSUnit:
    """Één UPS-systeem."""
    ups_id:           str
    label:            str
    brand:            str          = "generic"   # nut/apc/eaton/generic
    # Sensoren
    status_entity:    str          = ""
    battery_entity:   str          = ""
    runtime_entity:   str          = ""   # resterende minuten
    power_entity:     str          = ""   # belasting W
    # Afgeleid
    status:           str          = "unknown"
    battery_pct:      float        = 100.0
    runtime_min:      float        = 999.0
    power_w:          float        = 0.0
    on_battery:       bool         = False
    low_battery:      bool         = False
    fault:            bool         = False
    # Apparaten op deze UPS
    devices:          list[UPSDevice] = field(default_factory=list)
    # Runtime state
    on_battery_since: Optional[float] = None
    last_status:      str          = ""

    def to_dict(self) -> dict:
        return {
            "ups_id":       self.ups_id,
            "label":        self.label,
            "brand":        self.brand,
            "status":       self.status,
            "battery_pct":  round(self.battery_pct, 1),
            "runtime_min":  round(self.runtime_min, 1),
            "power_w":      round(self.power_w, 1),
            "on_battery":   self.on_battery,
            "low_battery":  self.low_battery,
            "fault":        self.fault,
            "devices_total": len(self.devices),
            "devices_shed":  sum(1 for d in self.devices if d.is_shed),
            "on_battery_s":  round(time.time() - self.on_battery_since)
                             if self.on_battery_since else 0,
        }


class UPSManager:
    """Beheert alle UPS-systemen voor CloudEMS."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass         = hass
        self._config       = config
        self._ups_units:   list[UPSUnit] = []
        self._notify_svc   = config.get("notification_service", "")
        self._last_notify: dict[str, float] = {}
        self._enabled      = False

    def configure(self, ups_configs: list[dict]) -> None:
        """Laad UPS configuraties."""
        existing = {u.ups_id: u for u in self._ups_units}
        new_units = []
        for cfg in ups_configs:
            uid = cfg.get("ups_id") or cfg.get("label", "ups1").lower().replace(" ", "_")
            ups = existing.get(uid) or UPSUnit(ups_id=uid, label=cfg.get("label", uid))
            ups.brand          = cfg.get("brand", "generic")
            ups.status_entity  = cfg.get("status_entity", "")
            ups.battery_entity = cfg.get("battery_entity", "")
            ups.runtime_entity = cfg.get("runtime_entity", "")
            ups.power_entity   = cfg.get("power_entity", "")
            # Apparaten
            ups.devices = [
                UPSDevice(
                    entity_id=d.get("entity_id", ""),
                    label    =d.get("label", d.get("entity_id", "")),
                    priority =int(d.get("priority", 3)),
                    shed_cmd =d.get("shed_cmd", "turn_off"),
                    restore_cmd=d.get("restore_cmd", "turn_on"),
                )
                for d in cfg.get("devices", [])
                if d.get("entity_id")
            ]
            new_units.append(ups)
        self._ups_units = new_units
        self._enabled   = bool(new_units)
        _LOGGER.info("UPSManager: %d UPS systemen geconfigureerd", len(new_units))

    def _read_status(self, ups: UPSUnit, hass_states: dict) -> None:
        """Lees UPS status uit HA sensoren."""
        # Status
        if ups.status_entity:
            st = hass_states.get(ups.status_entity)
            if st and st.state not in ("unavailable", "unknown"):
                raw = st.state.lower().replace("-", "_")
                ups.status     = raw
                ups.on_battery = raw in STATUS_BATTERY or raw in STATUS_LOW_BAT
                ups.low_battery= raw in STATUS_LOW_BAT
                ups.fault      = raw in STATUS_FAULT

                # NUT specifiek: parse meerdere flags (b.v. "OL CHRG")
                if ups.brand == "nut":
                    flags = raw.split()
                    ups.on_battery  = any(f in STATUS_BATTERY for f in flags)
                    ups.low_battery = any(f in STATUS_LOW_BAT for f in flags)
                    ups.fault       = any(f in STATUS_FAULT for f in flags)

        # Batterij %
        if ups.battery_entity:
            st = hass_states.get(ups.battery_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    ups.battery_pct = float(st.state)
                except (ValueError, TypeError):
                    pass

        # Runtime (minuten)
        if ups.runtime_entity:
            st = hass_states.get(ups.runtime_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    val = float(st.state)
                    # Sommige sensoren geven seconden
                    uom = (st.attributes or {}).get("unit_of_measurement", "min")
                    ups.runtime_min = val / 60 if uom in ("s", "sec", "seconds") else val
                except (ValueError, TypeError):
                    pass
        elif ups.battery_pct > 0:
            # Schat runtime op basis van batterij %: ruw 1% ≈ 1 min (conservatief)
            ups.runtime_min = ups.battery_pct * 0.8

        # Belasting W
        if ups.power_entity:
            st = hass_states.get(ups.power_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    ups.power_w = float(st.state)
                except (ValueError, TypeError):
                    pass

    async def async_tick(
        self,
        generator_active: bool,
        hass_states: dict,
    ) -> dict:
        """Hoofd-tick: lees UPS status en voer afschakelingen uit."""
        if not self._enabled:
            return {"enabled": False, "ups_units": []}

        now      = time.time()
        actions  = []
        any_on_battery = False

        for ups in self._ups_units:
            prev_status = ups.status

            # Lees huidige status
            self._read_status(ups, hass_states)

            # On-battery timer
            if ups.on_battery:
                any_on_battery = True
                if ups.on_battery_since is None:
                    ups.on_battery_since = now
                    _LOGGER.warning(
                        "UPS '%s' op batterij (%.0f%% · %.0f min)",
                        ups.label, ups.battery_pct, ups.runtime_min
                    )
            else:
                ups.on_battery_since = None

            # Statuswijziging notificatie
            if ups.status != prev_status and ups.status != ups.last_status:
                await self._notify_status_change(ups, now)
                ups.last_status = ups.status

            # Generator actief → herstel alle afgeschakelde apparaten
            if generator_active:
                for dev in ups.devices:
                    if dev.is_shed:
                        await self._restore_device(dev, ups.label, actions)
                continue

            # Afschakelen op basis van prioriteit + runtime
            if ups.on_battery:
                for dev in sorted(ups.devices, key=lambda d: -d.priority):
                    if dev.is_shed:
                        continue
                    threshold = PRIORITY_RUNTIME_THRESHOLDS.get(dev.priority, 10)
                    should_shed = (
                        threshold == 999 or   # prioriteit 5: direct
                        ups.runtime_min <= threshold
                    )
                    if should_shed and dev.priority > 1:
                        await self._shed_device(dev, ups, actions, now)

            # Herstel als UPS terug op net is
            elif not ups.on_battery and not ups.fault:
                for dev in ups.devices:
                    if dev.is_shed:
                        await self._restore_device(dev, ups.label, actions)

        return {
            "enabled":       True,
            "any_on_battery": any_on_battery,
            "generator_active": generator_active,
            "ups_units":     [u.to_dict() for u in self._ups_units],
            "actions":       actions,
        }

    async def _shed_device(self, dev: UPSDevice, ups: UPSUnit,
                            actions: list, now: float) -> None:
        """Schakel een apparaat af."""
        try:
            domain = dev.entity_id.split(".")[0]
            await self._hass.services.async_call(
                domain, dev.shed_cmd,
                {"entity_id": dev.entity_id},
                blocking=False,
            )
            dev.is_shed = True
            dev.shed_ts = now
            _LOGGER.info(
                "UPS '%s': afgeschakeld %s (prioriteit %d, runtime %.0f min)",
                ups.label, dev.label, dev.priority, ups.runtime_min
            )
            actions.append({
                "ups":      ups.label,
                "device":   dev.label,
                "action":   "shed",
                "priority": dev.priority,
                "runtime":  ups.runtime_min,
                "ts":       now,
            })
        except Exception as err:
            _LOGGER.warning("UPS shed fout voor %s: %s", dev.entity_id, err)

    async def _restore_device(self, dev: UPSDevice, ups_label: str,
                               actions: list) -> None:
        """Herstel een afgeschakeld apparaat."""
        try:
            domain = dev.entity_id.split(".")[0]
            await self._hass.services.async_call(
                domain, dev.restore_cmd,
                {"entity_id": dev.entity_id},
                blocking=False,
            )
            dev.is_shed = False
            _LOGGER.info("UPS '%s': hersteld %s", ups_label, dev.label)
            actions.append({
                "ups":    ups_label,
                "device": dev.label,
                "action": "restore",
                "ts":     time.time(),
            })
        except Exception as err:
            _LOGGER.warning("UPS restore fout voor %s: %s", dev.entity_id, err)

    async def _notify_status_change(self, ups: UPSUnit, now: float) -> None:
        """Stuur notificatie bij UPS statuswijziging."""
        key = f"ups_{ups.ups_id}"
        if now - self._last_notify.get(key, 0) < NOTIFY_COOLDOWN_S:
            return
        self._last_notify[key] = now

        if ups.on_battery:
            title = f"🔋 {ups.label} op batterij"
            msg   = (
                f"{ups.label} draait op batterij. "
                f"Batterij: {ups.battery_pct:.0f}% · "
                f"Geschatte runtime: {ups.runtime_min:.0f} min. "
                f"CloudEMS schakelt niet-essentiële apparaten af."
            )
        elif ups.low_battery:
            title = f"⚠️ {ups.label} batterij kritiek laag"
            msg   = (
                f"{ups.label} heeft kritiek lage batterij ({ups.battery_pct:.0f}%). "
                f"Nog ca. {ups.runtime_min:.0f} min. "
                f"Start de generator onmiddellijk."
            )
        elif ups.fault:
            title = f"❌ {ups.label} fout gedetecteerd"
            msg   = f"{ups.label} meldt een fout (status: {ups.status})."
        else:
            title = f"✅ {ups.label} terug op net"
            msg   = f"{ups.label} is terug op netspanning. Apparaten worden hersteld."

        if not self._notify_svc:
            return
        try:
            svc   = self._notify_svc.split(".")
            dom   = svc[0] if len(svc) > 1 else "notify"
            svc_n = svc[1] if len(svc) > 1 else svc[0]
            await self._hass.services.async_call(
                dom, svc_n,
                {"title": title, "message": msg},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("UPS notificatie fout: %s", err)

    def get_status(self) -> dict:
        return {
            "enabled":    self._enabled,
            "ups_count":  len(self._ups_units),
            "on_battery": any(u.on_battery for u in self._ups_units),
            "ups_units":  [u.to_dict() for u in self._ups_units],
        }
