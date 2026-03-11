# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Centrale Orphan Pruner (v1.1.0).

Verwijdert automatisch alle verouderde HA-entiteiten die door CloudEMS zijn
aangemaakt maar waarvan de onderliggende bron niet meer bestaat.

Gedekte dynamische entiteitsgroepen
─────────────────────────────────────
  NILM apparaten    {entry_id}_nilm_{device_id}          sensor
  NILM bevestig     {entry_id}_nilm_confirm_{device_id}  button
  NILM afwijzen     {entry_id}_nilm_reject_{device_id}   button
  Omvormer profiel  {entry_id}_inv_profile_{entity_id}   sensor
  Omvormer clipping {entry_id}_inv_clipping_{entity_id}  binary_sensor
  Kamermeters       {entry_id}_room_{room_name}           sensor
  Zoneklimaatsensor {entry_id}_zone_climate_{area_id}    sensor
  Rolluikknoppen    {entry_id}_shutter_{safe_id}_{action} button

Elke groep heeft een eigen absent-teller die pas na PRUNE_THRESHOLD opeenvolgende
cycli zonder actieve bron de entiteit uit het HA entity-registry verwijdert.
Zo worden tijdelijke uitval of HA-herstart niet als reden voor pruning gezien.
"""

from __future__ import annotations

import logging
import time as _time_mod
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger("cloudems.orphan_pruner")
_STORAGE_KEY     = "cloudems_orphan_pruner_v1"
_STORAGE_VERSION = 1

# ── Whitelist: alle vaste (niet-dynamische) {entry_id}_nilm_* suffixen ───────
# Alles wat hier NIET in staat met prefix _nilm_ is een dynamisch apparaat-ID.
_STATIC_NILM_SUFFIXES: frozenset[str] = frozenset({
    # Vaste sensor/switch/button entiteiten in sensor.py / switch.py / button.py
    "db",             # sensor.cloudems_nilm_db
    "stats",          # sensor.cloudems_nilm_stats
    "running",        # sensor.cloudems_nilm_running
    "running_power",  # sensor.cloudems_nilm_running_power
    "diag",           # sensor.cloudems_nilm_diag
    "input",          # sensor.cloudems_nilm_input
    "schedule",       # sensor.cloudems_nilm_schedule
    "overzicht",      # sensor.cloudems_nilm_overzicht
    "review_current", # sensor.cloudems_nilm_review_current
    # Review-queue knoppen (button.py) — vaste entity_id's
    "review_confirm", "review_dismiss", "review_skip", "review_previous",
    # NILM module-schakelaars (switch.py)
    "active",         # switch.cloudems_nilm_actief
    "hmm_active",     # switch.cloudems_nilm_sessietracking_hmm
    "bayes_active",   # switch.cloudems_nilm_bayesian_classifier
})

# Vaste NILM top-device ID's (sensor.cloudems_nilm_top_1..15_device)
# Device-id part = "top_{rank}" → altijd top_
_NILM_PROTECTED_PREFIXES = ("top_", "__")

# Vaste zone_climate entiteiten die NIET dynamisch zijn en nooit gepruned mogen worden
_STATIC_ZONE_CLIMATE_SUFFIXES: frozenset[str] = frozenset({
    "cost_today",   # sensor.cloudems_zone_klimaat_kosten_vandaag
})


def _is_protected_nilm_uid_suffix(device_id_part: str) -> bool:
    """True als dit suffix hoort bij een vaste (niet-dynamische) entiteit."""
    if device_id_part in _STATIC_NILM_SUFFIXES:
        return True
    for prefix in _NILM_PROTECTED_PREFIXES:
        if device_id_part.startswith(prefix):
            return True
    return False


class OrphanPruner:
    """Bewaakt alle dynamische CloudEMS-entiteiten en verwijdert verouderde exemplaren.

    Gebruik:
        pruner = OrphanPruner(hass, entry, coordinator, threshold=60, min_days=1)
        pruner.register()   # na async_add_entities in elke platform setup
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: "ConfigEntry",
        coordinator: "CloudEMSCoordinator",
        threshold: int = 60,
        min_days: float = 1.0,
    ) -> None:
        self._hass        = hass
        self._entry       = entry
        self._coordinator = coordinator
        self._threshold   = threshold
        self._min_days    = min_days

        # absent-tellers per groep: uid → aantal cycli afwezig (persistent across restarts)
        self._absent: dict[str, int] = {}
        self._store  = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._store_loaded = False
        self._dirty = False
        self._pending_updates = 0  # updates gebufferd tot store geladen is

    # ── Publieke interface ────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Laad persistente absent-tellers vanuit opslag."""
        try:
            data = await self._store.async_load()
            if data and isinstance(data.get("absent"), dict):
                self._absent = {k: int(v) for k, v in data["absent"].items()}
                _LOGGER.debug("OrphanPruner: %d absent-tellers hersteld", len(self._absent))
        except Exception as exc:
            _LOGGER.warning("OrphanPruner: kon state niet laden: %s", exc)
        self._store_loaded = True
        if self._pending_updates > 0:
            _LOGGER.debug(
                "OrphanPruner: %d gebufferde updates verwerken na store-load",
                self._pending_updates,
            )
            self._pending_updates = 0
            self._on_update()

    async def _async_save(self) -> None:
        """Sla absent-tellers op naar persistente opslag."""
        try:
            await self._store.async_save({"absent": dict(self._absent)})
        except Exception as exc:
            _LOGGER.warning("OrphanPruner: kon state niet opslaan: %s", exc)

    def register(self) -> None:
        """Registreer de pruner als coordinator-listener."""
        self._coordinator.async_add_listener(self._on_update)
        _LOGGER.debug(
            "OrphanPruner geregistreerd voor entry %s (threshold=%d, min_days=%.1f)",
            self._entry.entry_id, self._threshold, self._min_days,
        )

    # ── Interne update-callback ───────────────────────────────────────────────

    @callback
    def _on_update(self) -> None:
        """Wordt aangeroepen bij elke coordinator-update."""
        if not self._store_loaded:
            self._pending_updates += 1
            return  # Wacht tot de store geladen is
        _er = er.async_get(self._hass)
        entry_id = self._entry.entry_id

        # Verzamel alle CloudEMS-entiteiten in de HA registry voor dit config entry
        all_registered: dict[str, er.RegistryEntry] = {
            reg.unique_id: reg
            for reg in er.async_entries_for_config_entry(_er, entry_id)
        }

        # Bepaal alle actieve (levende) unique_ids
        active_uids = self._collect_active_uids(entry_id)

        # Loop over alle geregistreerde dynamische UIDs
        dynamic_uids = self._filter_dynamic_uids(all_registered, entry_id)

        pruned: list[str] = []

        for uid, reg_entry in dynamic_uids.items():
            if uid in active_uids:
                # Levend → reset teller
                self._absent.pop(uid, None)
                continue

            # Afwezig → verhoog teller
            self._absent[uid] = self._absent.get(uid, 0) + 1
            self._dirty = True

            # Bepaal effectieve threshold voor deze uid
            effective_threshold = self._threshold
            confirm_prefix = f"{entry_id}_nilm_confirm_"
            reject_prefix  = f"{entry_id}_nilm_reject_"
            if uid.startswith(confirm_prefix) or uid.startswith(reject_prefix):
                pfx = confirm_prefix if uid.startswith(confirm_prefix) else reject_prefix
                did = uid[len(pfx):]
                dev = self._coordinator.nilm.get_device(did)
                if dev is None:
                    # Apparaat bestaat helemaal niet meer → direct prunen
                    effective_threshold = 1
                elif getattr(dev, "user_suppressed", False):
                    # Afgewezen door gebruiker → snel prunen (3 cycli)
                    effective_threshold = 3

            if self._absent[uid] < effective_threshold:
                continue  # Nog niet lang genoeg afwezig

            # Optionele minimum-inactiviteit op basis van last_seen (alleen NILM)
            if self._min_days > 0 and effective_threshold == self._threshold \
                    and not self._check_min_days(uid, entry_id):
                continue

            # ─── Verwijder de entiteit ────────────────────────────────────────
            # Nooit verwijderen als de entiteit nog een state heeft in HA (geen echte orphan)
            if self._hass.states.get(reg_entry.entity_id) is not None:
                self._absent.pop(uid, None)
                continue
            try:
                _er.async_remove(reg_entry.entity_id)
                pruned.append(reg_entry.entity_id)
                self._absent.pop(uid, None)
                _LOGGER.info(
                    "CloudEMS OrphanPruner: verwijderd '%s' (uid=%s, %d cycli afwezig)",
                    reg_entry.entity_id, uid, self._threshold,
                )
                self._notify_pruned(uid, reg_entry.entity_id)
            except Exception as exc:
                _LOGGER.warning("OrphanPruner: kon '%s' niet verwijderen: %s", uid, exc)

        # Ruim tellers op van uid's die niet meer in de registry staan
        registered_set = set(all_registered)
        for uid in list(self._absent):
            if uid not in registered_set:
                self._absent.pop(uid, None)

        # Sla bijgewerkte tellers op (alleen als er iets veranderd is)
        if self._dirty:
            self._dirty = False
            self._hass.async_create_task(self._async_save())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _collect_active_uids(self, entry_id: str) -> set[str]:
        """Bouw de set op van alle UID's die momenteel actief zijn.

        Principe: als de *bron* nog bestaat, zijn ALLE geregistreerde entiteiten
        met dat prefix actief — ongeacht welke sub-entiteiten we kennen.
        Zo prunen we nooit actieve entiteiten door een onvolledige hardcoded lijst.
        Alleen echte orphans (bron verdwenen) tellen absent-cycli op.
        """
        active: set[str] = set()
        coord     = self._coordinator
        data      = coord.data or {}
        _er_local = er.async_get(self._hass)

        def _all_with_prefix(prefix: str) -> None:
            """Markeer alle geregistreerde UIDs met dit prefix als actief."""
            for reg in er.async_entries_for_config_entry(_er_local, entry_id):
                if reg.unique_id.startswith(prefix):
                    active.add(reg.unique_id)

        # ── NILM apparaten ────────────────────────────────────────────────────
        # Uitzondering: user_suppressed apparaten → confirm/reject knoppen mogen
        # gepruned worden, maar de sensor zelf blijft voor leerdata.
        nilm_storage_ready = getattr(coord.nilm, "_storage_loaded", False)
        if nilm_storage_ready:
            for dev in coord.nilm.get_devices():
                did = dev.device_id
                _all_with_prefix(f"{entry_id}_nilm_{did}")
                if not getattr(dev, "user_suppressed", False):
                    active.add(f"{entry_id}_nilm_confirm_{did}")
                    active.add(f"{entry_id}_nilm_reject_{did}")

        # ── Omvormer sensoren ─────────────────────────────────────────────────
        for inv in data.get("inverter_data", []):
            eid = inv.get("entity_id", "")
            if eid:
                _all_with_prefix(f"{entry_id}_inv_profile_{eid}")
                _all_with_prefix(f"{entry_id}_inv_clipping_{eid}")

        # ── Kamermeters ───────────────────────────────────────────────────────
        active.add(f"{entry_id}_room_overview")
        for room_name, room_data in data.get("room_meter", {}).get("rooms", {}).items():
            # Lege kamers (device_count=0) mogen orphan worden
            if not isinstance(room_data, dict) or room_data.get("device_count", 1) > 0:
                _all_with_prefix(f"{entry_id}_room_{room_name}")

        # ── Zone klimaat sensoren ─────────────────────────────────────────────
        active.add(f"{entry_id}_zone_climate_cost_today")
        zm = getattr(coord, "_zone_climate", None)
        if zm:
            for zone_attrs in zm.get_zone_attrs():
                area_id = zone_attrs.get("area") or zone_attrs.get("area_id", "")
                if not area_id:
                    continue
                zone_obj = next(
                    (z for z in getattr(zm, "_zones", []) if z._area_id == area_id),
                    None,
                )
                if zone_obj is not None:
                    has_live_entity = any(
                        self._hass.states.get(eid) is not None
                        for eid in getattr(zone_obj, "_entities", {})
                    )
                    if not has_live_entity:
                        continue  # Zone heeft geen levende entities → mag orphan worden
                _all_with_prefix(f"{entry_id}_zone_climate_{area_id}")

        # ── Rolluik entiteiten ────────────────────────────────────────────────
        shutter_cfgs = (
            self._entry.options.get("shutter_configs")
            or self._entry.data.get("shutter_configs", [])
        )
        for sc in shutter_cfgs:
            cover_id = sc.get("entity_id", "") or sc.get("cover_entity_id", "")
            if cover_id:
                safe = cover_id.split(".")[-1].replace("-", "_")
                _all_with_prefix(f"{entry_id}_shutter_{safe}_")
                # v4.3.15: text/number/sensor entities zijn statisch per rolluik —
                # expliciet als actief markeren zodat de pruner ze nooit verwijdert,
                # ook niet bij een race condition tijdens de eerste setup-cyclus.
                for static_suffix in (
                    "night_close", "morning_open", "setpoint",
                    "override_restant",
                ):
                    active.add(f"{entry_id}_shutter_{safe}_{static_suffix}")
                    active.add(f"{entry_id}_shutterv2_{safe}_{static_suffix}")

        return active

    def _filter_dynamic_uids(
        self,
        all_registered: dict[str, er.RegistryEntry],
        entry_id: str,
    ) -> dict[str, er.RegistryEntry]:
        """Filter op UID's die door de pruner bewaakt worden."""
        result: dict[str, er.RegistryEntry] = {}

        # (prefix, verificatiefunctie)
        # _always_dynamic: alles met dit prefix is dynamisch behalve wat in active_uids zit
        # _is_dynamic_nilm: extra check om vaste nilm_* entiteiten te beschermen
        checks = [
            (f"{entry_id}_nilm_",        self._is_dynamic_nilm),
            (f"{entry_id}_nilm_confirm_", self._always_dynamic),
            (f"{entry_id}_nilm_reject_",  self._always_dynamic),
            (f"{entry_id}_inv_profile_",  self._always_dynamic),
            (f"{entry_id}_inv_clipping_", self._always_dynamic),
            (f"{entry_id}_room_",         self._always_dynamic),
            (f"{entry_id}_zone_climate_", self._is_dynamic_zone_climate),
            (f"{entry_id}_shutter_",      self._always_dynamic),
            (f"{entry_id}_shutterv2_",    self._always_dynamic),
        ]

        for uid, reg in all_registered.items():
            for pattern, check_fn in checks:
                if uid.startswith(pattern) and check_fn(uid, pattern, entry_id):
                    result[uid] = reg
                    break

        return result

    @staticmethod
    def _always_dynamic(uid: str, pattern: str, entry_id: str) -> bool:
        return True

    @staticmethod
    def _is_dynamic_nilm(uid: str, pattern: str, entry_id: str) -> bool:
        """Sluit vaste module-sensoren uit die toevallig het nilm_ prefix hebben."""
        device_id_part = uid[len(pattern):]
        return not _is_protected_nilm_uid_suffix(device_id_part)

    @staticmethod
    def _is_dynamic_zone_climate(uid: str, pattern: str, entry_id: str) -> bool:
        """Sluit vaste zone_climate entiteiten uit die altijd aanwezig zijn."""
        suffix = uid[len(pattern):]
        return suffix not in _STATIC_ZONE_CLIMATE_SUFFIXES

    def _check_min_days(self, uid: str, entry_id: str) -> bool:
        """True als het NILM-apparaat lang genoeg inactief is (alleen NILM UID's)."""
        nilm_prefix    = f"{entry_id}_nilm_"
        confirm_prefix = f"{entry_id}_nilm_confirm_"
        reject_prefix  = f"{entry_id}_nilm_reject_"

        if uid.startswith(confirm_prefix):
            device_id = uid[len(confirm_prefix):]
        elif uid.startswith(reject_prefix):
            device_id = uid[len(reject_prefix):]
        elif uid.startswith(nilm_prefix):
            device_id = uid[len(nilm_prefix):]
        else:
            # Niet-NILM entiteiten: geen min-days check
            return True

        dev = self._coordinator.nilm.get_device(device_id)
        if dev is None:
            return True  # Apparaat bestaat niet meer → prunen toegestaan
        age_days = (_time_mod.time() - dev.last_seen) / 86400.0
        return age_days >= self._min_days

    def _notify_pruned(self, uid: str, entity_id: str) -> None:
        """Stuur een melding via de NotificationEngine als die beschikbaar is."""
        try:
            ne = getattr(self._coordinator, "_notification_engine", None)
            if ne:
                ne.ingest({
                    f"orphan_pruned:{uid}": {
                        "priority": "info",
                        "category": "system",
                        "title":    "CloudEMS entiteit opgeruimd",
                        "message":  (
                            f"Entiteit '{entity_id}' is automatisch verwijderd "
                            f"omdat de bijbehorende bron niet meer actief is."
                        ),
                        "active": True,
                    }
                })
        except Exception:
            pass
