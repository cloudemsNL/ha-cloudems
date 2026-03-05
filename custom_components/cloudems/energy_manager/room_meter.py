"""
CloudEMS Virtuele Stroommeter per Kamer — v1.20.0

Clustert NILM-apparaten en smart plug entiteiten per kamer/zone en berekent
real-time verbruik én dagkWh per ruimte.

Zelf-lerende kamertoewijzing (prioriteitsvolgorde):
  1. HA Area Registry     — entiteit heeft area_id in entity_registry → directe naam
  2. Keyword matching     — entity_id/friendly_name bevat kamernaam (slaapkamer, keuken, ...)
  3. Device-type heuristiek — koelkast→keuken, tv→woonkamer, wasmachine→bijkeuken
  4. Gebruiker-override   — via service cloudems.assign_device_to_room
  5. Fallback             — "Overig"

Doordat de HA area registry wordt gelezen, profiteren gebruikers automatisch
van elke entiteit die zij al aan een ruimte hebben toegewezen in HA.

Sensor-output per kamer:
  State: huidig verbruik (W)
  Attributen:
    - room_name
    - devices: lijst van apparaten + hun verbruik
    - kwh_today
    - kwh_this_month
    - pct_of_total

Master-sensor (overzicht alle kamers):
  State: kamer met hoogste verbruik nu
  Attributen: breakdown per kamer

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_room_meters_v2"
STORAGE_VERSION = 2
SAVE_INTERVAL_S = 300

# ── Standaard kamer-iconen ────────────────────────────────────────────────────
ROOM_ICONS: dict[str, str] = {
    "woonkamer":   "mdi:sofa",
    "keuken":      "mdi:countertop",
    "slaapkamer":  "mdi:bed",
    "badkamer":    "mdi:shower",
    "bijkeuken":   "mdi:washing-machine",
    "garage":      "mdi:garage",
    "kantoor":     "mdi:desk",
    "zolder":      "mdi:home-roof",
    "kelder":      "mdi:stairs-down",
    "tuin":        "mdi:tree",
    "hal":         "mdi:door",
    "overig":      "mdi:home-outline",
}

# ── Device-type → meest waarschijnlijke kamer (heuristiek) ───────────────────
DEVICE_TYPE_ROOM_HINT: dict[str, str] = {
    "refrigerator":   "keuken",
    "oven":           "keuken",
    "microwave":      "keuken",
    "dishwasher":     "keuken",
    "kettle":         "keuken",
    "washing_machine":"bijkeuken",
    "dryer":          "bijkeuken",
    "television":     "woonkamer",
    "entertainment":  "woonkamer",
    "computer":       "kantoor",
    "heat_pump":      "overig",
    "boiler":         "bijkeuken",
    "ev_charger":     "garage",
    "light":          "woonkamer",   # meest voorkomende kamer voor licht
    "unknown":        "overig",
    "socket":         "overig",
}

# ── Kamer-keywords in entity_id / friendly_name ──────────────────────────────
# Tupels: (keyword_nl_en, genormaliseerde_kamernaam)
ROOM_KEYWORDS: list[tuple[str, str]] = [
    # Woonkamer
    ("living",      "woonkamer"),
    ("lounge",      "woonkamer"),
    ("woonkamer",   "woonkamer"),
    ("huiskamer",   "woonkamer"),
    ("salon",       "woonkamer"),
    # Keuken
    ("kitchen",     "keuken"),
    ("keuken",      "keuken"),
    ("kook",        "keuken"),
    # Slaapkamer
    ("bedroom",     "slaapkamer"),
    ("slaapkamer",  "slaapkamer"),
    ("master_bed",  "slaapkamer"),
    ("master bed",  "slaapkamer"),
    ("bed_room",    "slaapkamer"),
    ("slaap",       "slaapkamer"),
    # Badkamer
    ("bathroom",    "badkamer"),
    ("badkamer",    "badkamer"),
    ("toilet",      "badkamer"),
    ("wc",          "badkamer"),
    ("douche",      "badkamer"),
    # Bijkeuken / wasruimte
    ("utility",     "bijkeuken"),
    ("laundry",     "bijkeuken"),
    ("bijkeuken",   "bijkeuken"),
    ("wasruimte",   "bijkeuken"),
    # Garage
    ("garage",      "garage"),
    ("carport",     "garage"),
    # Kantoor
    ("office",      "kantoor"),
    ("kantoor",     "kantoor"),
    ("studeerkamer","kantoor"),
    ("werkplek",    "kantoor"),
    ("study",       "kantoor"),
    # Zolder / kelder
    ("attic",       "zolder"),
    ("zolder",      "zolder"),
    ("loft",        "zolder"),
    ("basement",    "kelder"),
    ("kelder",      "kelder"),
    ("cellar",      "kelder"),
    # Tuin
    ("garden",      "tuin"),
    ("outdoor",     "tuin"),
    ("outside",     "tuin"),
    ("tuin",        "tuin"),
    ("buiten",      "tuin"),
    # Hal / gang
    ("hallway",     "hal"),
    ("hall",        "hal"),
    ("corridor",    "hal"),
    ("gang",        "hal"),
    ("hal",         "hal"),
    ("entree",      "hal"),
]


@dataclass
class RoomDevice:
    """Één apparaat dat bijdraagt aan het kamerverbruik."""
    device_id:    str
    device_type:  str
    display_name: str
    current_power_w: float
    is_on:        bool
    source:       str       # "nilm" | "smart_plug"
    assignment:   str       # hoe kamer bepaald: "area_registry" | "keyword" | "device_hint" | "user"


@dataclass
class RoomMeterState:
    """Real-time + historisch verbruik voor één kamer."""
    room_name:      str
    current_power_w: float = 0.0
    kwh_today:      float = 0.0
    kwh_this_month: float = 0.0
    kwh_all_time:   float = 0.0
    devices:        list  = field(default_factory=list)   # List[RoomDevice]
    last_update_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "room_name":       self.room_name,
            "current_power_w": round(self.current_power_w, 1),
            "kwh_today":       round(self.kwh_today, 3),
            "kwh_this_month":  round(self.kwh_this_month, 3),
            "kwh_all_time":    round(self.kwh_all_time, 3),
            "devices": [
                {
                    "device_id":    d.device_id,
                    "name":         d.display_name,
                    "device_type":  d.device_type,
                    "power_w":      round(d.current_power_w, 1),
                    "is_on":        d.is_on,
                    "assignment":   d.assignment,
                }
                for d in self.devices
            ],
        }


class RoomMeterEngine:
    """
    Verdeelt NILM-apparaten over kamers en houdt verbruik per ruimte bij.

    Gebruik vanuit coordinator:
        engine = RoomMeterEngine(hass)
        await engine.async_setup()
        result = await engine.async_update(nilm_devices, user_overrides)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass   = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._rooms:  dict[str, RoomMeterState] = {}   # room_name → state
        self._user_overrides: dict[str, str]    = {}   # device_id → room_name
        self._area_cache:     dict[str, str]    = {}   # entity_id → room_name
        self._area_cache_ts:  float             = 0.0
        self._last_save:      float             = 0.0
        self._last_reset_day: str               = ""
        self._last_reset_month: str             = ""
        self._dirty: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Load persisted kWh counters from storage."""
        saved = await self._store.async_load() or {}
        self._user_overrides = saved.get("user_overrides", {})

        for room_name, rd in saved.get("rooms", {}).items():
            self._rooms[room_name] = RoomMeterState(
                room_name      = room_name,
                kwh_today      = float(rd.get("kwh_today", 0)),
                kwh_this_month = float(rd.get("kwh_this_month", 0)),
                kwh_all_time   = float(rd.get("kwh_all_time", 0)),
            )
        self._last_reset_day   = saved.get("last_reset_day", "")
        self._last_reset_month = saved.get("last_reset_month", "")
        _LOGGER.info("RoomMeterEngine: setup met %d kamers", len(self._rooms))

    async def async_save(self) -> None:
        """Persist kWh counters."""
        rooms_data = {
            name: {
                "kwh_today":      r.kwh_today,
                "kwh_this_month": r.kwh_this_month,
                "kwh_all_time":   r.kwh_all_time,
            }
            for name, r in self._rooms.items()
        }
        await self._store.async_save({
            "rooms":            rooms_data,
            "user_overrides":   self._user_overrides,
            "last_reset_day":   self._last_reset_day,
            "last_reset_month": self._last_reset_month,
        })
        self._dirty = False

    # ── Main update ────────────────────────────────────────────────────────────

    async def async_update(
        self,
        nilm_devices: list[dict],
        interval_s:   float = 10.0,
    ) -> dict[str, RoomMeterState]:
        """
        Update room meters with current NILM device data.

        Args:
            nilm_devices:  Output of coordinator's nilm_devices list.
            interval_s:    Seconds since last call (for kWh accumulation).

        Returns:
            Dict of room_name → RoomMeterState.
        """
        now = datetime.now(timezone.utc)
        self._maybe_reset_counters(now)

        # Refresh area cache every 5 minutes
        if time.time() - self._area_cache_ts > 300:
            self._area_cache = self._build_area_cache()
            self._area_cache_ts = time.time()

        # Assign each device to a room
        room_devices: dict[str, list[RoomDevice]] = {}

        for dev in nilm_devices:
            device_id  = dev.get("device_id", "")
            device_type= dev.get("device_type", "unknown")
            name       = dev.get("user_name") or dev.get("name", device_type)
            power_w    = float(dev.get("current_power", 0) or dev.get("power_w", 0) or 0)
            is_on      = bool(dev.get("is_on", False))
            source_eid = dev.get("source_entity_id", "")

            room, assignment = self._assign_room(
                device_id   = device_id,
                device_type = device_type,
                display_name= name,
                source_entity_id = source_eid,
            )

            rd = RoomDevice(
                device_id       = device_id,
                device_type     = device_type,
                display_name    = name,
                current_power_w = power_w if is_on else 0.0,
                is_on           = is_on,
                source          = dev.get("source", "nilm"),
                assignment      = assignment,
            )

            room_devices.setdefault(room, []).append(rd)

        # Update RoomMeterState objects
        all_rooms = set(self._rooms.keys()) | set(room_devices.keys())
        for room_name in all_rooms:
            if room_name not in self._rooms:
                self._rooms[room_name] = RoomMeterState(room_name=room_name)

            state    = self._rooms[room_name]
            devices  = room_devices.get(room_name, [])
            total_w  = sum(d.current_power_w for d in devices)

            # Accumulate kWh (trapezoidal: avg power × time)
            kwh_delta = (total_w / 1000.0) * (interval_s / 3600.0)
            state.kwh_today      = round(state.kwh_today + kwh_delta, 4)
            state.kwh_this_month = round(state.kwh_this_month + kwh_delta, 4)
            state.kwh_all_time   = round(state.kwh_all_time + kwh_delta, 4)
            state.current_power_w= round(total_w, 1)
            state.devices        = devices
            state.last_update_ts = time.time()
            self._dirty = True

        # Periodic save
        if self._dirty and time.time() - self._last_save > SAVE_INTERVAL_S:
            await self.async_save()
            self._last_save = time.time()

        return self._rooms

    # ── Room assignment ────────────────────────────────────────────────────────

    def _assign_room(
        self,
        device_id:        str,
        device_type:      str,
        display_name:     str,
        source_entity_id: str,
    ) -> tuple[str, str]:
        """
        Determine room for a device. Returns (room_name, assignment_method).

        Priority:
          1. User override (set via service)
          2. HA area registry (via source_entity_id)
          3. Keyword match on display_name or device_id
          4. Device-type heuristic
          5. Fallback: "overig"
        """
        # 1. User override
        if device_id in self._user_overrides:
            return self._user_overrides[device_id], "user"

        # 2. HA area registry — entity_id → area name
        if source_entity_id and source_entity_id in self._area_cache:
            return self._area_cache[source_entity_id], "area_registry"

        # 3. Keyword match on display_name + device_id
        search_text = f"{display_name} {device_id}".lower().replace("_", " ")
        for keyword, room in ROOM_KEYWORDS:
            if keyword in search_text:
                return room, "keyword"

        # 4. Device-type heuristic
        hint = DEVICE_TYPE_ROOM_HINT.get(device_type)
        if hint:
            return hint, "device_hint"

        return "overig", "fallback"

    def _build_area_cache(self) -> dict[str, str]:
        """
        Build entity_id → normalized_room_name mapping from HA area registry.

        Reads:
          - entity_registry: entity.area_id (direct assignment)
          - device_registry: device.area_id (device-level assignment, fallback)
          - area_registry: area.name (human-readable)
        """
        cache: dict[str, str] = {}
        try:
            from homeassistant.helpers import entity_registry as er, \
                                              device_registry as dr, \
                                              area_registry  as ar

            ent_reg  = er.async_get(self._hass)
            dev_reg  = dr.async_get(self._hass)
            area_reg = ar.async_get(self._hass)

            for entry in ent_reg.entities.values():
                # Prefer entity-level area, fall back to device-level
                area_id = entry.area_id
                if not area_id and entry.device_id:
                    dev = dev_reg.async_get(entry.device_id)
                    if dev:
                        area_id = dev.area_id

                if area_id:
                    area = area_reg.async_get_area(area_id)
                    if area:
                        room = _normalize_room_name(area.name)
                        cache[entry.entity_id] = room

        except Exception as exc:
            _LOGGER.debug("RoomMeterEngine: area cache build failed: %s", exc)

        _LOGGER.debug("RoomMeterEngine: area cache: %d entiteiten met ruimte", len(cache))
        return cache

    # ── Day/month reset ────────────────────────────────────────────────────────

    def _maybe_reset_counters(self, now: datetime) -> None:
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")

        if self._last_reset_day != today_str:
            for room in self._rooms.values():
                room.kwh_today = 0.0
            self._last_reset_day = today_str
            self._dirty = True
            _LOGGER.debug("RoomMeterEngine: dag-reset")

        if self._last_reset_month != month_str:
            for room in self._rooms.values():
                room.kwh_this_month = 0.0
            self._last_reset_month = month_str
            self._dirty = True
            _LOGGER.debug("RoomMeterEngine: maand-reset")

    # ── User override (via service) ────────────────────────────────────────────

    def assign_device_to_room(self, device_id: str, room_name: str) -> None:
        """Manually assign a device to a room. Persisted across restarts."""
        normalized = _normalize_room_name(room_name)
        if room_name:
            self._user_overrides[device_id] = normalized
            _LOGGER.info("RoomMeterEngine: '%s' → '%s' (user override)", device_id, normalized)
        else:
            # Empty name = clear override
            self._user_overrides.pop(device_id, None)
            _LOGGER.info("RoomMeterEngine: user override voor '%s' verwijderd", device_id)
        self._dirty = True

    # ── Output helpers ─────────────────────────────────────────────────────────

    def get_overview(self, total_power_w: float) -> dict:
        """Return aggregated overview for the master sensor."""
        rooms_data = []
        for name, state in sorted(
            self._rooms.items(), key=lambda x: x[1].current_power_w, reverse=True
        ):
            pct = round(state.current_power_w / max(total_power_w, 1) * 100, 1)
            rooms_data.append({
                "room":      name,
                "power_w":   round(state.current_power_w, 1),
                "kwh_today": round(state.kwh_today, 3),
                "pct":       pct,
                "icon":      ROOM_ICONS.get(name, "mdi:home-outline"),
                "devices":   len(state.devices),
            })

        top_room = rooms_data[0]["room"] if rooms_data else "onbekend"
        return {
            "top_room":    top_room,
            "rooms":       rooms_data,
            "room_count":  len(rooms_data),
            "total_power_w": round(total_power_w, 1),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_room_name(name: str) -> str:
    """Normalize a room name for consistent lookups.

    Converts HA area names like 'Woonkamer', 'Living Room', 'Master Bedroom'
    to a consistent lowercase key matching ROOM_KEYWORDS targets.
    Falls back to lowercased original if no keyword match is found.
    """
    if not name:
        return "overig"
    lower = name.lower().replace("-", " ").replace("_", " ").strip()
    # Try ROOM_KEYWORDS mapping
    for keyword, canonical in ROOM_KEYWORDS:
        if keyword in lower:
            return canonical
    # Fall back to slugified original (e.g. "master bedroom" → "master bedroom")
    return lower
