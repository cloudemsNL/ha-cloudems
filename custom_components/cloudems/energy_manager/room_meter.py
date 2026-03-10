# -*- coding: utf-8 -*-
"""
CloudEMS Virtuele Stroommeter per Kamer — v1.21.0

Kamertoewijzing (prioriteit):
  1. User override  → via service cloudems.assign_device_to_room
  2. HA Area Registry → entiteit/device heeft area_id
  3. Keyword match  → naam of entity_id bevat kamernaam
  4. Device-type heuristiek → koelkast→keuken, wasmachine→bijkeutem, ...
  5. Auto-exclude   → ALLEEN als stap 2-4 niets opleverde EN het apparaat
                      lijkt op een meter/omvormer/batterij/laadpaal
                      → "CloudEMS Exclude" virtuele ruimte
  6. Fallback       → "overig"

Labels (categorie, los van ruimte):
  Via service cloudems.label_nilm_device — sleutel uit AVAILABLE_LABELS.
  Zichtbaar in sensor-attributen voor dashboard/filter gebruik.

User controls:
  - assign_device_to_room  → handmatige ruimtetoewijzing (stap 1, ook naar Exclude)
  - include_nilm_device    → auto-exclude opheffen, apparaat → overig
  - exclude_nilm_device    → apparaat altijd naar CloudEMS Exclude
  - label_nilm_device      → categorie-label instellen

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_room_meters_v3"
STORAGE_VERSION = 3
SAVE_INTERVAL_S = 300

# ── CloudEMS Exclude (virtuele ruimte) ───────────────────────────────────────
EXCLUDE_ROOM      = "CloudEMS Exclude"
EXCLUDE_ROOM_ICON = "mdi:filter-remove-outline"

# ── Auto-exclude drempelwaarden ──────────────────────────────────────────────
# Alleen toegepast als het apparaat GEEN ruimte heeft via stap 2-4
MAX_HOUSEHOLD_W = 6_000.0   # boven dit = geen normaal woonapparaat
MIN_CONFIDENCE  = 0.20      # onder dit = NILM te onzeker

# ── Device-types die altijd auto-excluded worden (indien geen ruimte) ────────
AUTO_EXCLUDE_TYPES: frozenset[str] = frozenset({
    "grid_meter", "energy_meter", "smart_meter", "p1_meter",
    "solar_inverter", "pv_inverter", "battery_system", "home_battery",
    "ev_charger", "wallbox", "heat_meter", "gas_meter", "water_meter",
    "ct_clamp", "power_monitor", "subpanel",
})

# ── Naam/entity_id patronen die wijzen op een meter of installatie ───────────
_METER_RE: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\bp1\b", r"slimme.?meter", r"smart.?meter", r"grid.?meter",
    r"energy.?meter", r"main.?meter", r"hoofdmeter",
    r"zonneplan", r"solar.?edge", r"solarman", r"fronius",
    r"enphase", r"goodwe", r"omvormer", r"inverter",
    r"battery.?system", r"powerwall", r"huawei.?luna", r"byd.?battery",
    r"zappi", r"alfen", r"easee", r"laadpaal", r"wallbox",
    r"ct.?clamp", r"stroommeter", r"power.?meter",
    r"connectie.?meter", r"aansluitmeter", r"\bems\b",
]]

# ── Beschikbare labels / categorieën ────────────────────────────────────────
AVAILABLE_LABELS: dict[str, dict] = {
    "meter":     {"icon": "mdi:meter-electric",      "color": "#ff5252", "label": "Energiemeter"},
    "solar":     {"icon": "mdi:solar-power",         "color": "#ffab00", "label": "Zonnepanelen"},
    "battery":   {"icon": "mdi:battery-charging",    "color": "#40c4ff", "label": "Thuisbatterij"},
    "ev":        {"icon": "mdi:ev-station",          "color": "#ce93d8", "label": "Laadpaal"},
    "heating":   {"icon": "mdi:radiator",            "color": "#ff7043", "label": "Verwarming"},
    "cooling":   {"icon": "mdi:air-conditioner",     "color": "#26c6da", "label": "Koeling"},
    "appliance": {"icon": "mdi:washing-machine",     "color": "#a5d6a7", "label": "Huishoudelijk"},
    "lighting":  {"icon": "mdi:lightbulb",           "color": "#fff176", "label": "Verlichting"},
    "network":   {"icon": "mdi:router-wireless",     "color": "#90caf9", "label": "Netwerk/IT"},
    "unknown":   {"icon": "mdi:help-circle-outline", "color": "#78909c", "label": "Onbekend"},
}

# ── Kamer iconen ─────────────────────────────────────────────────────────────
ROOM_ICONS: dict[str, str] = {
    "woonkamer": "mdi:sofa",        "keuken":    "mdi:countertop",
    "slaapkamer":"mdi:bed",         "badkamer":  "mdi:shower",
    "bijkeuken": "mdi:washing-machine", "garage":"mdi:garage",
    "kantoor":   "mdi:desk",        "zolder":    "mdi:home-roof",
    "kelder":    "mdi:stairs-down", "tuin":      "mdi:tree",
    "hal":       "mdi:door",        "overig":    "mdi:home-outline",
    EXCLUDE_ROOM: EXCLUDE_ROOM_ICON,
}

# ── Device-type → kamer heuristiek ───────────────────────────────────────────
DEVICE_TYPE_ROOM_HINT: dict[str, str] = {
    "refrigerator":    "keuken",    "oven":          "keuken",
    "microwave":       "keuken",    "dishwasher":    "keuken",
    "kettle":          "keuken",    "washing_machine":"bijkeuken",
    "dryer":           "bijkeuken", "television":    "woonkamer",
    "entertainment":   "woonkamer", "computer":      "kantoor",
    "heat_pump":       "overig",    "boiler":        "bijkeuken",
    "light":           "woonkamer", "unknown":       "overig",
    "socket":          "overig",
}

# ── Kamer keywords ───────────────────────────────────────────────────────────
ROOM_KEYWORDS: list[tuple[str, str]] = [
    ("living","woonkamer"),("lounge","woonkamer"),("woonkamer","woonkamer"),
    ("huiskamer","woonkamer"),("salon","woonkamer"),
    ("kitchen","keuken"),("keuken","keuken"),("kook","keuken"),
    ("bedroom","slaapkamer"),("slaapkamer","slaapkamer"),("slaap","slaapkamer"),
    ("master_bed","slaapkamer"),("master bed","slaapkamer"),("bed_room","slaapkamer"),
    ("bathroom","badkamer"),("badkamer","badkamer"),("toilet","badkamer"),
    ("wc","badkamer"),("douche","badkamer"),
    ("utility","bijkeuken"),("laundry","bijkeuken"),
    ("bijkeuken","bijkeuken"),("wasruimte","bijkeuken"),
    ("garage","garage"),("carport","garage"),
    ("office","kantoor"),("kantoor","kantoor"),("studeerkamer","kantoor"),
    ("werkplek","kantoor"),("study","kantoor"),
    ("attic","zolder"),("zolder","zolder"),("loft","zolder"),
    ("basement","kelder"),("kelder","kelder"),("cellar","kelder"),
    ("garden","tuin"),("outdoor","tuin"),("outside","tuin"),
    ("tuin","tuin"),("buiten","tuin"),("afdak","tuin"),
    ("schuur","tuin"),("blokhut","tuin"),("shed","tuin"),
    ("hallway","hal"),("hall","hal"),("corridor","hal"),
    ("gang","hal"),("hal","hal"),("entree","hal"),
]


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RoomDevice:
    device_id:       str
    device_type:     str
    display_name:    str
    current_power_w: float
    is_on:           bool
    source:          str          # "nilm" | "smart_plug"
    assignment:      str          # hoe ruimte bepaald
    label:           Optional[str] = None   # sleutel uit AVAILABLE_LABELS
    auto_excluded:   bool = False
    confidence:      float = 1.0


@dataclass
class RoomMeterState:
    room_name:       str
    current_power_w: float = 0.0
    kwh_today:       float = 0.0
    kwh_this_month:  float = 0.0
    kwh_all_time:    float = 0.0
    devices:         list  = field(default_factory=list)
    last_update_ts:  float = field(default_factory=time.time)
    is_virtual:      bool  = False

    def to_dict(self) -> dict:
        return {
            "room_name":       self.room_name,
            "current_power_w": round(self.current_power_w, 1),
            "kwh_today":       round(self.kwh_today, 3),
            "kwh_this_month":  round(self.kwh_this_month, 3),
            "kwh_all_time":    round(self.kwh_all_time, 3),
            "is_virtual":      self.is_virtual,
            "icon":            ROOM_ICONS.get(self.room_name, "mdi:home-outline"),
            "devices": [
                {
                    "device_id":    d.device_id,
                    "name":         d.display_name,
                    "device_type":  d.device_type,
                    "power_w":      round(d.current_power_w, 1),
                    "is_on":        d.is_on,
                    "assignment":   d.assignment,
                    "label":        d.label,
                    "label_info":   AVAILABLE_LABELS.get(d.label) if d.label else None,
                    "auto_excluded":d.auto_excluded,
                    "confidence":   round(d.confidence, 2),
                }
                for d in self.devices
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
class RoomMeterEngine:
    """Verdeelt NILM-apparaten over kamers. Zie module-docstring voor logica."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass   = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._rooms:           dict[str, RoomMeterState] = {}
        self._user_overrides:  dict[str, str]  = {}   # device_id → room (stap 1)
        self._user_labels:     dict[str, str]  = {}   # device_id → label key
        self._user_excluded:   set[str]        = set()  # altijd → Exclude
        self._user_included:   set[str]        = set()  # nooit auto-exclude
        self._area_cache:      dict[str, str]  = {}
        self._area_cache_ts:   float           = 0.0
        self._last_save:       float           = 0.0
        self._last_reset_day:  str             = ""
        self._last_reset_month:str             = ""
        self._dirty: bool = False
        # device_ids die al in de HA-ruimte "CloudEMS Exclude" geplaatst zijn
        # zodat we dat niet elke cyclus opnieuw doen (rate-limit HA registry writes)
        self._ha_exclude_placed: set[str] = set()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        self._user_overrides = saved.get("user_overrides", {})
        self._user_labels    = saved.get("user_labels", {})
        self._user_excluded  = set(saved.get("user_excluded", []))
        self._user_included  = set(saved.get("user_included", []))

        for room_name, rd in saved.get("rooms", {}).items():
            self._rooms[room_name] = RoomMeterState(
                room_name      = room_name,
                kwh_today      = float(rd.get("kwh_today", 0)),
                kwh_this_month = float(rd.get("kwh_this_month", 0)),
                kwh_all_time   = float(rd.get("kwh_all_time", 0)),
                is_virtual     = rd.get("is_virtual", room_name == EXCLUDE_ROOM),
            )
        self._last_reset_day   = saved.get("last_reset_day", "")
        self._last_reset_month = saved.get("last_reset_month", "")

        # Virtuele Exclude-ruimte altijd aanwezig
        if EXCLUDE_ROOM not in self._rooms:
            self._rooms[EXCLUDE_ROOM] = RoomMeterState(
                room_name=EXCLUDE_ROOM, is_virtual=True
            )

        _LOGGER.info(
            "RoomMeterEngine v1.21: %d kamers, %d overrides, %d labels, "
            "%d excluded, %d included",
            len(self._rooms), len(self._user_overrides), len(self._user_labels),
            len(self._user_excluded), len(self._user_included),
        )

    async def async_save(self) -> None:
        await self._store.async_save({
            "rooms": {
                name: {
                    "kwh_today": r.kwh_today,
                    "kwh_this_month": r.kwh_this_month,
                    "kwh_all_time": r.kwh_all_time,
                    "is_virtual": r.is_virtual,
                }
                for name, r in self._rooms.items()
            },
            "user_overrides":  self._user_overrides,
            "user_labels":     self._user_labels,
            "user_excluded":   list(self._user_excluded),
            "user_included":   list(self._user_included),
            "last_reset_day":  self._last_reset_day,
            "last_reset_month":self._last_reset_month,
        })
        self._dirty = False

    # ── Main update ────────────────────────────────────────────────────────────

    async def async_update(
        self,
        nilm_devices: list[dict],
        interval_s:   float = 10.0,
    ) -> dict[str, RoomMeterState]:
        now = datetime.now(timezone.utc)
        self._maybe_reset_counters(now)

        if time.time() - self._area_cache_ts > 300:
            self._area_cache    = self._build_area_cache()
            self._area_cache_ts = time.time()

        room_devices: dict[str, list[RoomDevice]] = {}

        for dev in nilm_devices:
            device_id   = dev.get("device_id", "")
            device_type = dev.get("device_type", "unknown")
            name        = dev.get("user_name") or dev.get("name", device_type)
            power_w     = float(dev.get("current_power", 0) or dev.get("power_w", 0) or 0)
            is_on       = bool(dev.get("is_on", False))
            source_eid  = dev.get("source_entity_id", "")
            confidence  = float(dev.get("confidence", 1.0))

            room, assignment, auto_exc = self._assign_room(
                device_id=device_id, device_type=device_type,
                display_name=name, source_entity_id=source_eid,
                power_w=power_w, confidence=confidence,
            )

            # v3.9: plaatst apparaat in HA-ruimte "CloudEMS Exclude" als het
            # uitgesloten is én nog geen bestaande HA-ruimte heeft.
            if room == EXCLUDE_ROOM and source_eid:
                await self._place_in_ha_exclude_area(source_eid, device_id)

            room_devices.setdefault(room, []).append(RoomDevice(
                device_id=device_id, device_type=device_type,
                display_name=name,
                current_power_w=power_w if is_on else 0.0,
                is_on=is_on, source=dev.get("source", "nilm"),
                assignment=assignment, label=self._user_labels.get(device_id),
                auto_excluded=auto_exc, confidence=confidence,
            ))

        # Update alle kamers (incl. Exclude)
        for room_name in set(self._rooms) | set(room_devices) | {EXCLUDE_ROOM}:
            if room_name not in self._rooms:
                self._rooms[room_name] = RoomMeterState(
                    room_name=room_name,
                    is_virtual=room_name == EXCLUDE_ROOM,
                )
            state   = self._rooms[room_name]
            devices = room_devices.get(room_name, [])
            total_w = sum(d.current_power_w for d in devices)
            kwh_d   = (total_w / 1000.0) * (interval_s / 3600.0)
            state.kwh_today      = round(state.kwh_today + kwh_d, 4)
            state.kwh_this_month = round(state.kwh_this_month + kwh_d, 4)
            state.kwh_all_time   = round(state.kwh_all_time + kwh_d, 4)
            state.current_power_w = round(total_w, 1)
            state.devices         = devices
            state.last_update_ts  = time.time()
            self._dirty = True

        if self._dirty and time.time() - self._last_save > SAVE_INTERVAL_S:
            await self.async_save()
            self._last_save = time.time()

        return self._rooms

    # ── Room assignment ────────────────────────────────────────────────────────

    def _assign_room(
        self,
        device_id: str, device_type: str, display_name: str,
        source_entity_id: str, power_w: float, confidence: float,
    ) -> tuple[str, str, bool]:
        """
        Returns (room_name, assignment_method, auto_excluded).

        Stap 1: user override     → altijd gevolgd (ook naar Exclude)
        Stap 2: user_excluded     → altijd Exclude
        Stap 3: area registry     → echte HA-ruimte → geen auto-exclude
        Stap 4: keyword match     → echte ruimte → geen auto-exclude
        Stap 5: device-type hint  → echte ruimte → geen auto-exclude
        --- apparaat heeft GEEN bekende ruimte ---
        Stap 6: user_included     → overig (auto-exclude overgeslagen)
        Stap 7: auto-exclude?     → CloudEMS Exclude (alleen naam/type/drempels)
        Stap 8: fallback          → overig
        """
        # Stap 1 — user override (hoogste prioriteit)
        if device_id in self._user_overrides:
            return self._user_overrides[device_id], "user", False

        # Stap 2 — user altijd excluded
        if device_id in self._user_excluded:
            return EXCLUDE_ROOM, "user_excluded", False

        # Stap 3 — HA area registry (apparaat heeft al een echte ruimte)
        if source_entity_id and source_entity_id in self._area_cache:
            return self._area_cache[source_entity_id], "area_registry", False

        # Stap 4 — keyword match op naam/entity_id
        search = f"{display_name} {device_id}".lower().replace("_", " ")
        for kw, room in ROOM_KEYWORDS:
            if kw in search:
                return room, "keyword", False

        # Stap 5 — device-type heuristiek
        hint = DEVICE_TYPE_ROOM_HINT.get(device_type)
        if hint:
            return hint, "device_hint", False

        # ── Geen ruimte gevonden via stap 3-5 ────────────────────────────────

        # Stap 6 — user heeft expliciet included → skip auto-exclude
        if device_id in self._user_included:
            return "overig", "user_included", False

        # Stap 7 — auto-exclude? (alleen hier, nooit eerder)
        reason = self._should_auto_exclude(device_id, device_type, display_name, power_w, confidence)
        if reason:
            _LOGGER.debug("auto-exclude '%s' reden=%s", display_name, reason)
            return EXCLUDE_ROOM, f"auto:{reason}", True

        # Stap 8 — fallback
        return "overig", "fallback", False

    def _should_auto_exclude(
        self, device_id: str, device_type: str, display_name: str,
        power_w: float, confidence: float,
    ) -> Optional[str]:
        """Geeft reden-string als auto-exclude van toepassing, anders None."""
        if device_type in AUTO_EXCLUDE_TYPES:
            return f"type={device_type}"
        check = f"{display_name} {device_id}".lower()
        for pat in _METER_RE:
            if pat.search(check):
                return f"naam"
        if power_w > MAX_HOUSEHOLD_W:
            return f"vermogen={power_w:.0f}W"
        if confidence < MIN_CONFIDENCE:
            return f"confidence={confidence:.0%}"
        return None

    # ── User controls ──────────────────────────────────────────────────────────

    def assign_device_to_room(self, device_id: str, room_name: str) -> None:
        """Stap 1 override. Leeg = wissen. Werkt ook naar EXCLUDE_ROOM."""
        if room_name:
            norm = _normalize_room_name(room_name)
            self._user_overrides[device_id] = norm
            # Wis conflicterende flags als naar echte ruimte
            if norm != _normalize_room_name(EXCLUDE_ROOM):
                self._user_excluded.discard(device_id)
                self._user_included.discard(device_id)
        else:
            self._user_overrides.pop(device_id, None)
        self._dirty = True
        _LOGGER.info("assign_device_to_room: '%s' → '%s'", device_id, room_name or "(verwijderd)")

    def exclude_device(self, device_id: str) -> None:
        """Forceer apparaat altijd naar CloudEMS Exclude (stap 2)."""
        self._user_excluded.add(device_id)
        self._user_included.discard(device_id)
        self._user_overrides.pop(device_id, None)
        # Reset HA-placement cache zodat volgende cyclus de entiteit plaatst
        self._ha_exclude_placed.discard(device_id)
        self._dirty = True
        _LOGGER.info("exclude_device: '%s'", device_id)

    def include_device(self, device_id: str) -> None:
        """Hef auto-exclude op: apparaat gaat naar 'overig' (stap 6)."""
        self._user_included.add(device_id)
        self._user_excluded.discard(device_id)
        self._user_overrides.pop(device_id, None)
        # Verwijder uit HA placement cache — HA-ruimte wordt NIET teruggedraaid
        # (de gebruiker moet dat zelf doen in HA als gewenst)
        self._ha_exclude_placed.discard(device_id)
        self._dirty = True
        _LOGGER.info("include_device: '%s'", device_id)

    def label_device(self, device_id: str, label_key: str) -> bool:
        """Sla categorie-label op. Leeg = wissen. Returns False bij onbekend label."""
        if not label_key:
            self._user_labels.pop(device_id, None)
            self._dirty = True
            return True
        if label_key not in AVAILABLE_LABELS:
            _LOGGER.warning("label_device: onbekend label '%s'", label_key)
            return False
        self._user_labels[device_id] = label_key
        self._dirty = True
        _LOGGER.info("label_device: '%s' → '%s'", device_id, label_key)
        return True

    # ── Output ─────────────────────────────────────────────────────────────────

    def get_overview(self, total_power_w: float) -> dict:
        real_rooms = [
            (n, s) for n, s in self._rooms.items() if n != EXCLUDE_ROOM
        ]
        excl = self._rooms.get(EXCLUDE_ROOM)
        rooms_data = []
        for name, state in sorted(real_rooms, key=lambda x: x[1].current_power_w, reverse=True):
            pct = round(state.current_power_w / max(total_power_w, 1) * 100, 1)
            rooms_data.append({
                "room":      name,
                "power_w":   round(state.current_power_w, 1),
                "kwh_today": round(state.kwh_today, 3),
                "pct":       pct,
                "icon":      ROOM_ICONS.get(name, "mdi:home-outline"),
                "devices":   len(state.devices),
            })
        return {
            "top_room":         rooms_data[0]["room"] if rooms_data else "onbekend",
            "rooms":            rooms_data,
            "room_count":       len(rooms_data),
            "total_power_w":    round(total_power_w, 1),
            "excluded_count":   len(excl.devices) if excl else 0,
            "excluded_power_w": round(excl.current_power_w, 1) if excl else 0,
            "available_labels": [{"key": k, **v} for k, v in AVAILABLE_LABELS.items()],
        }

    def get_excluded_devices(self) -> list[dict]:
        """Alle apparaten in CloudEMS Exclude, met metadata voor UI."""
        excl = self._rooms.get(EXCLUDE_ROOM)
        if not excl:
            return []
        return [
            {
                "device_id":    d.device_id,
                "name":         d.display_name,
                "device_type":  d.device_type,
                "power_w":      round(d.current_power_w, 1),
                "is_on":        d.is_on,
                "auto_excluded":d.auto_excluded,
                "assignment":   d.assignment,
                "label":        d.label,
                "label_info":   AVAILABLE_LABELS.get(d.label) if d.label else None,
                "can_include":  d.auto_excluded and d.device_id not in self._user_excluded,
            }
            for d in excl.devices
        ]

    def get_available_labels(self) -> list[dict]:
        return [{"key": k, **v} for k, v in AVAILABLE_LABELS.items()]

    # ── Area cache ─────────────────────────────────────────────────────────────

    async def _place_in_ha_exclude_area(
        self, source_entity_id: str, device_id: str
    ) -> None:
        """Zet entiteit in HA-ruimte 'CloudEMS Exclude', maar ALLEEN als die
        entiteit nog geen ruimte heeft. Entiteiten met een bestaande ruimte
        worden nooit verplaatst.

        Wordt aangeroepen bij auto-exclude en user_excluded — maar niet vaker
        dan nodig (bijgehouden via _ha_exclude_placed).
        """
        if device_id in self._ha_exclude_placed:
            return
        if not source_entity_id:
            return
        try:
            from homeassistant.helpers import (
                entity_registry as er, device_registry as dr, area_registry as ar,
            )
            ent_reg  = er.async_get(self._hass)
            dev_reg  = dr.async_get(self._hass)
            area_reg = ar.async_get(self._hass)

            entry = ent_reg.async_get(source_entity_id)
            if entry is None:
                return

            # Controleer of entiteit of bijbehorend device al een ruimte heeft
            has_area = bool(entry.area_id)
            if not has_area and entry.device_id:
                dev = dev_reg.async_get(entry.device_id)
                has_area = bool(dev and dev.area_id)

            if has_area:
                # Bestaande ruimte → nooit aanraken
                self._ha_exclude_placed.add(device_id)   # skip volgende check
                return

            # Zoek de "CloudEMS Exclude" area
            exclude_area = next(
                (a for a in area_reg.areas.values()
                 if a.name.lower() == EXCLUDE_ROOM.lower()),
                None,
            )
            if exclude_area is None:
                # Aanmaken als hij nog niet bestaat
                exclude_area = area_reg.async_create(
                    EXCLUDE_ROOM, icon=EXCLUDE_ROOM_ICON
                )
                _LOGGER.info("CloudEMS: HA-ruimte '%s' aangemaakt", EXCLUDE_ROOM)

            # Plaats entiteit in de ruimte
            ent_reg.async_update_entity(source_entity_id, area_id=exclude_area.id)
            self._ha_exclude_placed.add(device_id)
            _LOGGER.info(
                "CloudEMS: '%s' geplaatst in HA-ruimte '%s'",
                source_entity_id, EXCLUDE_ROOM,
            )
        except Exception as exc:
            _LOGGER.debug("_place_in_ha_exclude_area mislukt: %s", exc)

    def _build_area_cache(self) -> dict[str, str]:
        cache: dict[str, str] = {}
        try:
            from homeassistant.helpers import (
                entity_registry as er, device_registry as dr, area_registry as ar,
            )
            ent_reg  = er.async_get(self._hass)
            dev_reg  = dr.async_get(self._hass)
            area_reg = ar.async_get(self._hass)
            for entry in ent_reg.entities.values():
                area_id = entry.area_id
                if not area_id and entry.device_id:
                    dev = dev_reg.async_get(entry.device_id)
                    if dev:
                        area_id = dev.area_id
                if area_id:
                    area = area_reg.async_get_area(area_id)
                    if area:
                        cache[entry.entity_id] = _normalize_room_name(area.name)
        except Exception as exc:
            _LOGGER.debug("area cache mislukt: %s", exc)
        return cache

    # ── Day/month reset ────────────────────────────────────────────────────────

    def _maybe_reset_counters(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        if self._last_reset_day != today:
            for r in self._rooms.values():
                r.kwh_today = 0.0
            self._last_reset_day = today
            self._dirty = True
        if self._last_reset_month != month:
            for r in self._rooms.values():
                r.kwh_this_month = 0.0
            self._last_reset_month = month
            self._dirty = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_room_name(name: str) -> str:
    if not name:
        return "overig"
    if name.lower() == EXCLUDE_ROOM.lower():
        return EXCLUDE_ROOM
    lower = name.lower().replace("-", " ").replace("_", " ").strip()
    for kw, canonical in ROOM_KEYWORDS:
        if kw in lower:
            return canonical
    return lower
