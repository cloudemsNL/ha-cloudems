# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS NILM Load Shifter — v1.0.0

Detecteert automatisch NILM-apparaten die zijn gestart tijdens dure stroom
en stelt ze uit naar het goedkoopste beschikbare uurblok.

Verschil met SmartDelaySwitch:
  - SmartDelaySwitch: handmatig geconfigureerde schakelaars
  - NILMLoadShifter:  volledig automatisch via NILM-detectie

Werking:
  1. Elke tick: ontvang lijst van actieve NILM-detecties van coordinator
  2. Per detectie: is de prijs nu hoger dan drempel?
  3. Zo ja: schakel het gekoppelde entity_id (indien bekend) UIT
  4. Zoek goedkoopste blok in komende 12 uur binnen allowed window
  5. Plan herstart op dat moment
  6. Herstart wanneer het goedkope blok bereikt wordt
  7. Rapporteer status per apparaat terug aan coordinator

Cloud-gereed:
  - Gebruikt EntityProvider abstractie (geen directe hass calls)
  - Alle state via provider.get_state() / provider.call_service()
  - Cloud-variant kan eigen provider injecteren

Beperkingen v1.0:
  - Alleen apparaten met een bekend schakelbaar entity_id
  - Geen kennis van cyclusduur (wordt in v1.1 toegevoegd via NILM profiel)
  - Geen conflictdetectie met smart_delay (wordt in v1.1 toegevoegd)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Prijs waarboven we uitstellen (€/kWh all-in)
DEFAULT_PRICE_THRESHOLD = 0.25

# Maximum uitstel in uren
MAX_DEFER_HOURS = 8

# Minimale cyclustijd voor een apparaat om in aanmerking te komen (seconden)
MIN_CYCLE_S = 120

# Cooldown na herstart — voorkom direct opnieuw uitstellen (seconden)
RESTART_COOLDOWN_S = 3600


@dataclass
class ShiftedDevice:
    """Staat van één uitgesteld apparaat."""
    device_id: str           # NILM device_id
    entity_id: str           # HA schakelaar entity_id
    label: str               # leesbare naam
    deferred_at: float       # unix timestamp waarop we uitgesteld hebben
    planned_start: float     # unix timestamp van geplande herstart
    planned_hour: int        # uur van geplande herstart (lokale tijd)
    price_at_defer: float    # prijs op moment van uitstellen
    target_price: float      # verwachte prijs op herstelmoment
    avg_duration_min: float = 0.0   # geleerde gemiddelde cyclusduur (minuten)
    deadline_ts: float = 0.0        # uiterste starttijd (0 = geen deadline)
    restarted: bool = False  # al herstart?
    restart_ts: float = 0.0  # wanneer herstart


class NILMLoadShifter:
    """
    Automatische NILM-gebaseerde load shifter.

    Wordt aangeroepen door de coordinator elke tick met:
      - nilm_devices: lijst van actieve NILM detecties (coordinator data)
      - price_info:   verrijkte prijsinfo (coordinator._enrich_price_info)

    Geeft terug:
      - lijst van acties (dict) voor logging in coordinator
      - status dict voor sensor + dashboard
    """

    def __init__(
        self,
        entity_provider,          # EntityProvider instantie (HA of cloud)
        config: dict,
    ) -> None:
        self._provider = entity_provider
        self._threshold: float = float(
            config.get("nilm_shift_price_threshold", DEFAULT_PRICE_THRESHOLD)
        )
        self._max_defer_h: int = int(
            config.get("nilm_shift_max_defer_hours", MAX_DEFER_HOURS)
        )
        self._enabled: bool = bool(config.get("nilm_load_shifting_enabled", True))

        # entity_id overrides: {device_type: entity_id}
        self._entity_overrides: Dict[str, str] = dict(
            config.get("nilm_shift_entity_overrides", {}) or {}
        )

        # Include/exclude lijsten — device_type of device_id strings
        # include: alleen deze apparaten verschuiven (leeg = alles)
        # exclude: deze apparaten nooit verschuiven
        _inc = config.get("nilm_shift_include") or []
        _exc = config.get("nilm_shift_exclude") or []
        self._include: list[str] = [s.lower().strip() for s in _inc if s]
        self._exclude: list[str] = [s.lower().strip() for s in _exc if s]

        # hass referentie voor auto-detectie (optioneel — None in cloud)
        self._hass = config.get("_hass")

        # Deadlines per device_type: {device_type: "HH:MM"} — klaar voor dit tijdstip
        self._deadlines: Dict[str, str] = dict(
            config.get("nilm_shift_deadlines", {}) or {}
        )

        # Actieve uitstelrecords: device_id → ShiftedDevice
        self._deferred: Dict[str, ShiftedDevice] = {}

        # Cooldown na herstart: device_id → timestamp
        self._cooldown: Dict[str, float] = {}

        _LOGGER.info(
            "CloudEMS NILMLoadShifter: gestart — drempel=%.2f €/kWh, max uitstel=%dh",
            self._threshold, self._max_defer_h,
        )

    # ── Publieke interface ────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        nilm_devices: List[Dict[str, Any]],
        price_info: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Hoofdlogica — roep elke coordinator-tick aan.

        Returns lijst van actie-dicts voor coordinator logging.
        """
        if not self._enabled:
            return []

        actions: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc).timestamp()
        current_price = self._current_price(price_info)
        today_all: List[Dict] = price_info.get("today_all") or []
        tomorrow_all: List[Dict] = price_info.get("tomorrow_all") or []
        all_slots = today_all + tomorrow_all

        # 1. Check actieve NILM detecties — stel uit indien nodig
        active_device_ids = {d.get("device_id") or d.get("id", "") for d in nilm_devices}

        for device in nilm_devices:
            dev_id = device.get("device_id") or device.get("id", "")
            if not dev_id:
                continue

            # Include/exclude filter
            dev_type_key = (device.get("device_type") or "").lower().strip()
            dev_name_key = (device.get("name") or "").lower().strip()
            keys = {k for k in (dev_id, dev_type_key, dev_name_key) if k}
            # v5.5.350: apparaattypen die NOOIT uitgesteld mogen worden
            # Koelkast/vriezer → voedselveiligheid
            # Heat_pump → comfortcritisch, grote thermische massa
            NEVER_SHIFT = {"refrigerator", "freezer", "heat_pump", "medical"}
            if dev_type_key in NEVER_SHIFT:
                continue
            if self._include and not keys.intersection(self._include):
                continue  # niet op de include-lijst
            if keys.intersection(self._exclude):
                continue  # op de exclude-lijst

            # Al uitgesteld of in cooldown?
            if dev_id in self._deferred:
                continue
            if dev_id in self._cooldown and now - self._cooldown[dev_id] < RESTART_COOLDOWN_S:
                continue

            # Heeft dit apparaat een schakelbaar entity_id?
            entity_id = self._resolve_entity(device)
            if not entity_id:
                continue

            # Is de prijs hoog genoeg om uit te stellen?
            if current_price is None or current_price <= self._threshold:
                continue

            # Is het apparaat al lang genoeg actief (voorkom te vroeg uitstellen)?
            started = device.get("started_at") or device.get("session_start", 0)
            if started and (now - started) < MIN_CYCLE_S:
                continue

            # Is er een goedkoper blok beschikbaar?
            # Deadline: bereken uiterste starttijd op basis van cyclus + deadline
            _avg_dur = float(device.get("avg_duration_min") or 0.0)
            _deadline_ts = self._calc_deadline_ts(
                (device.get("device_type") or "").lower().strip(), _avg_dur, now
            )
            _max_h = self._max_defer_h
            if _deadline_ts:
                _max_h = min(_max_h, round((_deadline_ts - now) / 3600, 1))

            target = self._find_cheapest_slot(all_slots, now, _max_h)
            if target is None:
                _LOGGER.debug(
                    "NILMLoadShifter: %s — geen goedkoper blok gevonden, niet uitgesteld",
                    dev_id,
                )
                continue

            # Schakel uit via provider
            try:
                await self._provider.call_service(
                    "homeassistant", "turn_off", {"entity_id": entity_id}
                )
            except Exception as exc:
                _LOGGER.warning("NILMLoadShifter: turn_off %s fout: %s", entity_id, exc)
                continue

            avg_dur = float(device.get("avg_duration_min") or 0.0)
            deadline_ts = self._calc_deadline_ts(dev_type_key, avg_dur, now)

            rec = ShiftedDevice(
                device_id=dev_id,
                entity_id=entity_id,
                label=device.get("label") or device.get("device_type", dev_id),
                deferred_at=now,
                planned_start=target["ts"],
                planned_hour=target["hour"],
                price_at_defer=current_price,
                target_price=target["price"],
                avg_duration_min=avg_dur,
                deadline_ts=deadline_ts,
            )
            self._deferred[dev_id] = rec

            actions.append({
                "action": "deferred",
                "device_id": dev_id,
                "entity_id": entity_id,
                "label": rec.label,
                "reason": f"prijs {current_price:.3f} €/kWh > drempel {self._threshold:.2f}",
                "planned_hour": target["hour"],
                "target_price": target["price"],
            })
            _LOGGER.info(
                "NILMLoadShifter: %s (%s) uitgesteld — prijs %.3f > %.2f, gepland %02d:00 @ %.3f €/kWh",
                rec.label, entity_id, current_price, self._threshold,
                target["hour"], target["price"],
            )

        # 2. Check uitgestelde apparaten — herstart indien goedkoop blok bereikt
        for dev_id, rec in list(self._deferred.items()):
            if rec.restarted:
                # Ruim op na 2 uur
                if now - rec.restart_ts > 7200:
                    del self._deferred[dev_id]
                continue

            # Wacht tot gepland moment (of goedkope prijs bereikt)
            if now < rec.planned_start:
                continue
            if current_price is not None and current_price > self._threshold * 1.1:
                # Prijs nog te hoog — wacht extra
                _LOGGER.debug(
                    "NILMLoadShifter: %s herstart uitgesteld, prijs %.3f nog hoog",
                    dev_id, current_price,
                )
                continue

            # Herstart
            try:
                await self._provider.call_service(
                    "homeassistant", "turn_on", {"entity_id": rec.entity_id}
                )
                rec.restarted = True
                rec.restart_ts = now
                self._cooldown[dev_id] = now
            except Exception as exc:
                _LOGGER.warning("NILMLoadShifter: turn_on %s fout: %s", rec.entity_id, exc)
                continue

            actions.append({
                "action": "restarted",
                "device_id": dev_id,
                "entity_id": rec.entity_id,
                "label": rec.label,
                "reason": f"goedkoop blok bereikt — prijs {current_price:.3f} €/kWh",
                "deferred_at": rec.deferred_at,
                "saved_minutes": round((now - rec.deferred_at) / 60),
            })
            _LOGGER.info(
                "NILMLoadShifter: %s (%s) herstart — prijs %.3f €/kWh, %d min uitgesteld",
                rec.label, rec.entity_id, current_price or 0,
                round((now - rec.deferred_at) / 60),
            )

        return actions

    def get_status(self) -> Dict[str, Any]:
        """Retourneer huidige status voor coordinator data dict en sensor."""
        now = datetime.now(timezone.utc).timestamp()
        pending = [
            {
                "device_id":    r.device_id,
                "entity_id":    r.entity_id,
                "label":        r.label,
                "deferred_at":  r.deferred_at,
                "planned_hour": r.planned_hour,
                "price_at_defer": round(r.price_at_defer, 4),
                "target_price": round(r.target_price, 4),
                "wait_minutes":    round((r.planned_start - now) / 60) if not r.restarted else 0,
                "avg_duration_min": r.avg_duration_min,
                "deadline_ts":     r.deadline_ts or None,
                "restarted":       r.restarted,
            }
            for r in self._deferred.values()
        ]
        return {
            "enabled":        self._enabled,
            "pending_count":  sum(1 for r in self._deferred.values() if not r.restarted),
            "threshold_eur":  self._threshold,
            "deferred":       pending,
        }

    # ── Hulpmethoden ──────────────────────────────────────────────────────────

    def _resolve_entity(self, device: Dict) -> Optional[str]:
        """Zoek het schakelbare entity_id voor dit NILM apparaat.

        Volgorde:
          1. Handmatige override in config (entity_overrides)
          2. NILM device heeft zelf een linked_entity
          3. Auto-detectie via naampatronen op device_type / name
        """
        dev_type = (device.get("device_type") or "").lower().strip()
        dev_id   = device.get("device_id") or device.get("id", "")
        dev_name = (device.get("name") or device.get("label") or dev_type).lower()

        # 1. Handmatige override in config
        for key in (dev_type, dev_id, dev_name):
            if key and key in self._entity_overrides:
                return self._entity_overrides[key]

        # 2. NILM device heeft zelf een gekoppeld entity_id
        linked = device.get("linked_entity") or device.get("entity_id")
        if linked and linked.startswith("switch."):
            return linked

        # 3. Auto-detectie — probeer gangbare naampatronen
        if not self._hass:
            return None

        slug = dev_type.replace(" ", "_").replace("-", "_")
        name_slug = dev_name.replace(" ", "_").replace("-", "_")

        candidates = [
            f"switch.{slug}",
            f"switch.{name_slug}",
            f"switch.cloudems_{slug}",
            f"switch.{slug}_schakelaar",
            f"switch.smart_{slug}",
        ]
        for eid in candidates:
            if self._hass.states.get(eid) is not None:
                _LOGGER.debug("NILMLoadShifter: auto-detectie %s → %s", dev_type, eid)
                return eid

        return None

    @staticmethod
    def _current_price(price_info: Dict) -> Optional[float]:
        """Haal huidige all-in prijs op uit price_info."""
        if not price_info:
            return None
        return (
            price_info.get("current_all_in")
            or price_info.get("current")
            or price_info.get("price_incl_tax")
        )

    def _calc_deadline_ts(
        self, dev_type: str, avg_duration_min: float, now_ts: float
    ) -> float:
        """
        Bereken de uiterste starttijd op basis van deadline config en cyclus-duur.

        Voorbeeld: deadline "07:00", cyclus 90 min → uiterste start = 05:30
        Returns 0.0 als geen deadline geconfigureerd.
        """
        deadline_str = self._deadlines.get(dev_type, "")
        if not deadline_str:
            return 0.0

        try:
            from datetime import datetime, timezone, timedelta
            h, m = (int(x) for x in deadline_str.split(":"))
            now_dt = datetime.now(timezone.utc)
            # Zoek eerstvolgende moment dat overeenkomt met deadline
            candidate = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate.timestamp() <= now_ts:
                candidate += timedelta(days=1)
            # Trek cyclus-duur af zodat het apparaat op tijd KLAAR is
            if avg_duration_min > 0:
                candidate -= timedelta(minutes=avg_duration_min)
            return max(now_ts + 600, candidate.timestamp())  # minimaal 10 min in toekomst
        except Exception:
            return 0.0

    @staticmethod
    def _find_cheapest_slot(
        slots: List[Dict],
        now_ts: float,
        max_hours: int,
    ) -> Optional[Dict]:
        """
        Zoek het goedkoopste uurblok in de komende max_hours uur.

        Returns dict met 'ts', 'hour', 'price' of None.
        """
        if not slots:
            return None

        cutoff = now_ts + max_hours * 3600
        future = []

        for slot in slots:
            # Slots kunnen een 'time' (ISO string) of 'hour' (int) hebben
            slot_ts = None
            if "time" in slot:
                try:
                    dt = datetime.fromisoformat(str(slot["time"]))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    slot_ts = dt.timestamp()
                except Exception:
                    pass
            elif "hour" in slot:
                # Gebruik vandaag of morgen afhankelijk van het uur
                from datetime import timedelta
                now_dt = datetime.now(timezone.utc)
                h = int(slot["hour"])
                candidate = now_dt.replace(hour=h, minute=0, second=0, microsecond=0)
                if candidate.timestamp() <= now_ts:
                    candidate += timedelta(days=1)
                slot_ts = candidate.timestamp()

            if slot_ts is None:
                continue
            if slot_ts <= now_ts + 300:  # minimaal 5 min in de toekomst
                continue
            if slot_ts > cutoff:
                continue

            price = slot.get("price_incl_tax") or slot.get("price") or slot.get("all_in")
            if price is None:
                continue

            future.append({
                "ts":    slot_ts,
                "hour":  int(slot.get("hour", datetime.fromtimestamp(slot_ts, tz=timezone.utc).hour)),
                "price": float(price),
            })

        if not future:
            return None

        return min(future, key=lambda x: x["price"])
