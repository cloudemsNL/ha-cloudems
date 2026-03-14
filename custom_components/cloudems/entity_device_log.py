# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Entity & Device Log (v1.0.0)

Houdt bij welke entiteiten en devices CloudEMS heeft aangemaakt.
Elke aanmaak wordt gelogd met timestamp, platform, unique_id en bron.
Bij elke coordinator-update wordt de live HA entity registry vergeleken
met het log — ontbrekende entries worden als orphan gemarkeerd en na
een configureerbare grace-periode automatisch opgeruimd.

Opgeslagen in:  .storage/cloudems_entity_device_log_v1
Dashboard via:  coordinator.data["entity_log"]

Structuur per entry:
  {
    "unique_id":   "abc123_vboiler_water_heater.ariston",
    "entity_id":   "climate.cloudems_boiler_ariston",
    "platform":    "climate",
    "source":      "virtual_boiler",
    "created_at":  1712345678.0,
    "last_seen":   1712345678.0,   # laatste coordinator-tick dat de entity bestond
    "absent_ticks": 0,             # opeenvolgende ticks dat de entity ontbrak
    "pruned":      false,          # True zodra opgeruimd
    "pruned_at":   null,
  }

Copyright 2025-2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger("cloudems.entity_device_log")

_STORAGE_KEY     = "cloudems_entity_device_log_v1"
_STORAGE_VERSION = 1

# Grace-periode: na hoeveel opeenvolgende afwezige ticks ruimen we op
PRUNE_ABSENT_TICKS  = 48      # ~24u bij 30min coordinator interval
# Minimale leeftijd voordat een entity als orphan mag worden beschouwd
PRUNE_MIN_AGE_S     = 86400   # 24 uur


def get_entity_device_log(hass: HomeAssistant, entry: "ConfigEntry") -> "EntityDeviceLog | None":
    """Haal bestaande EntityDeviceLog op voor deze config entry, of None.

    Geeft None terug als de coordinator nog niet klaar is met async_setup
    (wat kan voorkomen bij de eerste platform-setup na HA start).
    """
    from .const import DOMAIN
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coord is None:
        return None
    log = getattr(coord, "_entity_device_log", None)
    return log  # kan None zijn als async_setup nog niet klaar is


class EntityDeviceLog:
    """
    Persistent logboek van alle door CloudEMS aangemakte entiteiten.

    Gebruik:
        log = EntityDeviceLog(hass, entry)
        await log.async_load()
        log.register("climate", "climate.cloudems_boiler_ariston",
                     "abc_vboiler_water_heater.ariston", "virtual_boiler")
        await log.async_tick()   # elke coordinator-update
    """

    def __init__(self, hass: HomeAssistant, entry: "ConfigEntry") -> None:
        self._hass    = hass
        self._entry   = entry
        self._store   = Store(hass, _STORAGE_VERSION, f"{_STORAGE_KEY}_{entry.entry_id}")
        self._entries: dict[str, dict] = {}   # unique_id → entry dict
        self._dirty   = False

    async def async_load(self) -> None:
        """Laad opgeslagen log uit HA storage."""
        raw = await self._store.async_load()
        if raw and isinstance(raw, dict):
            self._entries = raw.get("entries", {})
            _LOGGER.debug(
                "EntityDeviceLog: %d entries geladen uit storage",
                len(self._entries),
            )

    async def async_save(self) -> None:
        if self._dirty:
            await self._store.async_save({"entries": self._entries})
            self._dirty = False

    def register(
        self,
        platform:  str,
        entity_id: str,
        unique_id: str,
        source:    str,
    ) -> None:
        """Registreer een nieuwe of bestaande entity in het log."""
        now = time.time()
        if unique_id in self._entries:
            # Update entity_id bij eventuele hernoeming
            entry = self._entries[unique_id]
            if entry.get("entity_id") != entity_id:
                _LOGGER.info(
                    "EntityDeviceLog: entity hernoemd %s → %s",
                    entry["entity_id"], entity_id,
                )
                entry["entity_id"] = entity_id
                self._dirty = True
            entry["last_seen"]    = now
            entry["absent_ticks"] = 0
            return

        self._entries[unique_id] = {
            "unique_id":    unique_id,
            "entity_id":    entity_id,
            "platform":     platform,
            "source":       source,
            "created_at":   now,
            "last_seen":    now,
            "absent_ticks": 0,
            "pruned":       False,
            "pruned_at":    None,
        }
        self._dirty = True
        _LOGGER.info(
            "EntityDeviceLog: nieuwe entity geregistreerd — %s (source=%s, uid=%s)",
            entity_id, source, unique_id,
        )

    async def async_tick(self) -> dict:
        """
        Voer één controlecyclus uit:
          1. Vergelijk gelogde entities met live HA entity registry
          2. Verhoog absent_ticks voor ontbrekende entries
          3. Ruim entities op die te lang ontbreken (orphan pruning)
          4. Sla op als dirty
          5. Geef samenvattingsdict terug voor coordinator.data

        Geeft dict terug:
          {
            "total":    int,   # totaal geregistreerde (niet-gepruned) entries
            "active":   int,   # momenteel aanwezig in HA registry
            "orphaned": int,   # afwezig ≥ 1 tick
            "pruned":   int,   # totaal ooit opgeruimd (historisch)
            "entries":  list,  # alle entries (voor diagnose/dashboard)
          }
        """
        now      = time.time()
        ent_reg  = er.async_get(self._hass)
        active_uids: set[str] = set()

        # Bouw set van alle actieve unique_ids in HA registry
        for reg_entry in ent_reg.entities.values():
            if reg_entry.config_entry_id == self._entry.entry_id:
                if reg_entry.unique_id:
                    active_uids.add(reg_entry.unique_id)

        pruned_this_tick: list[str] = []

        for uid, entry in list(self._entries.items()):
            if entry.get("pruned"):
                continue

            if uid in active_uids:
                # Entity bestaat — reset teller
                entry["last_seen"]    = now
                entry["absent_ticks"] = 0
                self._dirty = True
            else:
                # Entity ontbreekt in registry
                entry["absent_ticks"] = entry.get("absent_ticks", 0) + 1
                self._dirty = True

                age_s = now - entry.get("created_at", now)
                if (
                    entry["absent_ticks"] >= PRUNE_ABSENT_TICKS
                    and age_s >= PRUNE_MIN_AGE_S
                ):
                    # Orphan — ruim op
                    await self._prune(uid, entry, ent_reg)
                    pruned_this_tick.append(entry["entity_id"])

        if pruned_this_tick:
            _LOGGER.warning(
                "EntityDeviceLog: %d orphan entit%s opgeruimd: %s",
                len(pruned_this_tick),
                "eit" if len(pruned_this_tick) == 1 else "eiten",
                pruned_this_tick,
            )

        await self.async_save()

        # Samenvattingsstatistiek
        all_entries     = [e for e in self._entries.values() if not e.get("pruned")]
        active_entries  = [e for e in all_entries if e["absent_ticks"] == 0]
        orphan_entries  = [e for e in all_entries if e["absent_ticks"] > 0]
        pruned_total    = sum(1 for e in self._entries.values() if e.get("pruned"))

        return {
            "total":    len(all_entries),
            "active":   len(active_entries),
            "orphaned": len(orphan_entries),
            "pruned":   pruned_total,
            "entries":  sorted(
                all_entries,
                key=lambda e: (e["absent_ticks"] > 0, -e.get("created_at", 0)),
            ),
        }

    async def _prune(self, uid: str, entry: dict, ent_reg: Any) -> None:
        """Verwijder een orphan entity uit HA registry en markeer als gepruned."""
        entity_id = entry.get("entity_id", "")
        try:
            reg_entry = ent_reg.async_get_entity_id(
                entry.get("platform", "sensor"), "cloudems", uid
            )
            if reg_entry:
                ent_reg.async_remove(reg_entry)
                _LOGGER.info(
                    "EntityDeviceLog: orphan '%s' verwijderd uit HA registry "
                    "(absent %d ticks, aangemaakt %s)",
                    entity_id,
                    entry["absent_ticks"],
                    _fmt_ts(entry.get("created_at", 0)),
                )
            else:
                _LOGGER.debug(
                    "EntityDeviceLog: orphan '%s' was al niet meer in registry",
                    entity_id,
                )
        except Exception as exc:
            _LOGGER.warning(
                "EntityDeviceLog: kon orphan '%s' niet verwijderen: %s",
                entity_id, exc,
            )
        finally:
            entry["pruned"]    = True
            entry["pruned_at"] = time.time()
            self._dirty = True

    def get_summary(self) -> dict:
        """Synchrone samenvatting zonder tick-logica (voor diagnostics)."""
        all_entries    = [e for e in self._entries.values() if not e.get("pruned")]
        active_entries = [e for e in all_entries if e["absent_ticks"] == 0]
        orphan_entries = [e for e in all_entries if e["absent_ticks"] > 0]
        pruned_total   = sum(1 for e in self._entries.values() if e.get("pruned"))
        return {
            "total":    len(all_entries),
            "active":   len(active_entries),
            "orphaned": len(orphan_entries),
            "pruned":   pruned_total,
            "entries":  sorted(
                all_entries,
                key=lambda e: (e["absent_ticks"] > 0, -e.get("created_at", 0)),
            ),
        }

    def get_all_by_source(self) -> dict[str, list[dict]]:
        """Groepeer entries op source (voor logging per module)."""
        result: dict[str, list[dict]] = {}
        for e in self._entries.values():
            src = e.get("source", "unknown")
            result.setdefault(src, []).append(e)
        return result

    def log_summary_to_logger(self) -> None:
        """Schrijf een overzicht naar het HA logboek (INFO niveau)."""
        by_source = self.get_all_by_source()
        _LOGGER.info("─── CloudEMS Entity Device Log ─────────────────────────")
        for source, entries in sorted(by_source.items()):
            active  = [e for e in entries if not e.get("pruned") and e["absent_ticks"] == 0]
            orphans = [e for e in entries if not e.get("pruned") and e["absent_ticks"] > 0]
            pruned  = [e for e in entries if e.get("pruned")]
            _LOGGER.info(
                "  %-30s  ✅ actief: %2d  ⚠ orphan: %2d  🗑 gepruned: %2d",
                source, len(active), len(orphans), len(pruned),
            )
            for e in orphans:
                _LOGGER.warning(
                    "    ORPHAN: %-50s  absent %d ticks  (aangemaakt %s)",
                    e["entity_id"], e["absent_ticks"], _fmt_ts(e.get("created_at", 0)),
                )
        _LOGGER.info("────────────────────────────────────────────────────────")


def _fmt_ts(ts: float) -> str:
    """Format unix timestamp naar leesbare string."""
    if not ts:
        return "onbekend"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
