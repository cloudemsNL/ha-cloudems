"""CloudEMS — Shutter Thermal Learner v1.0
Leert per kamer welke raamoriëntatie de rolluiken hebben via correlatie
tussen temperatuurstijging en zonpositie (azimuth + elevatie).
Koppelt geleerde oriëntatie terug aan ShutterController.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.util import dt as dt_util

from ..const import (
    SHUTTER_ORIENTATION_NORTH,
    SHUTTER_ORIENTATION_EAST,
    SHUTTER_ORIENTATION_SOUTH,
    SHUTTER_ORIENTATION_WEST,
    SHUTTER_ORIENTATION_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)

# Minimaal aantal samples voordat oriëntatie als betrouwbaar geldt
MIN_SAMPLES_CONFIDENT = 20
# Minimale temperatuurstijging om als significante solar gain te tellen (°C)
MIN_TEMP_RISE_C = 0.3
# Minimale zon-elevatie om solar gain te meten (°C)
MIN_SOLAR_ELEVATION = 10.0
# Azimuth-bereiken per oriëntatie
ORIENTATION_RANGES = {
    SHUTTER_ORIENTATION_NORTH: [(315, 360), (0, 45)],
    SHUTTER_ORIENTATION_EAST:  [(45, 135)],
    SHUTTER_ORIENTATION_SOUTH: [(135, 225)],
    SHUTTER_ORIENTATION_WEST:  [(225, 315)],
}


@dataclass
class AzimuthBucket:
    """Accumuleert temperatuurstijging per azimuth-sector (45° buckets)."""
    total_rise: float = 0.0
    samples: int = 0

    def add(self, rise: float) -> None:
        self.total_rise += rise
        self.samples += 1

    @property
    def avg_rise(self) -> float:
        return self.total_rise / self.samples if self.samples > 0 else 0.0


@dataclass
class RoomLearnerState:
    """Leerdata voor één kamer."""
    area_id: str
    area_name: str = ""
    # azimuth bucket index (0-7, elk 45°) → AzimuthBucket
    buckets: dict[int, AzimuthBucket] = field(default_factory=dict)
    learned_orientation: str = SHUTTER_ORIENTATION_UNKNOWN
    orientation_confident: bool = False
    total_samples: int = 0
    last_temp_c: Optional[float] = None
    last_sample_at: Optional[str] = None  # ISO timestamp

    def to_dict(self) -> dict:
        return {
            "area_id":              self.area_id,
            "area_name":            self.area_name,
            "buckets":              {
                str(k): {"total_rise": v.total_rise, "samples": v.samples}
                for k, v in self.buckets.items()
            },
            "learned_orientation":  self.learned_orientation,
            "orientation_confident": self.orientation_confident,
            "total_samples":        self.total_samples,
            "last_sample_at":       self.last_sample_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RoomLearnerState":
        obj = cls(area_id=d.get("area_id", ""), area_name=d.get("area_name", ""))
        obj.learned_orientation  = d.get("learned_orientation", SHUTTER_ORIENTATION_UNKNOWN)
        obj.orientation_confident = d.get("orientation_confident", False)
        obj.total_samples        = d.get("total_samples", 0)
        obj.last_sample_at       = d.get("last_sample_at")
        for k_str, bdata in d.get("buckets", {}).items():
            bucket = AzimuthBucket()
            bucket.total_rise = bdata.get("total_rise", 0.0)
            bucket.samples    = bdata.get("samples", 0)
            obj.buckets[int(k_str)] = bucket
        return obj


def _azimuth_to_bucket(azimuth: float) -> int:
    """Zet azimuth (0-360°) om naar bucket index (0-7, elk 45°)."""
    return int((azimuth % 360) / 45)


def _bucket_to_orientation(bucket_idx: int) -> str:
    """Geef oriëntatie terug voor een bucket index."""
    # Buckets: 0=N(0-45), 1=NE(45-90), 2=E(90-135), 3=SE(135-180),
    #          4=S(180-225), 5=SW(225-270), 6=W(270-315), 7=NW(315-360)
    mapping = {
        0: SHUTTER_ORIENTATION_NORTH,
        1: SHUTTER_ORIENTATION_EAST,
        2: SHUTTER_ORIENTATION_EAST,
        3: SHUTTER_ORIENTATION_SOUTH,
        4: SHUTTER_ORIENTATION_SOUTH,
        5: SHUTTER_ORIENTATION_WEST,
        6: SHUTTER_ORIENTATION_WEST,
        7: SHUTTER_ORIENTATION_NORTH,
    }
    return mapping.get(bucket_idx, SHUTTER_ORIENTATION_UNKNOWN)


class ShutterThermalLearner:
    """Leert raamoriëntatie per kamer via temperatuur-zon correlatie.

    Werking:
    - Elke update: meet temperatuurstijging t.o.v. vorige meting
    - Als zon >10° elevatie en stijging >0.3°C: voeg toe aan azimuth bucket
    - Na MIN_SAMPLES_CONFIDENT samples: bepaal dominante bucket → oriëntatie
    - Oriëntatie wordt teruggekoppeld aan ShutterController
    """

    _STORE_KEY     = "cloudems_shutter_thermal_v1"
    _STORE_VERSION = 1

    def __init__(self, hass=None) -> None:
        self._hass   = hass
        self._rooms: dict[str, RoomLearnerState] = {}
        self._store  = None
        self._dirty  = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        """Laad geleerde kamerorientaties vanuit opslag."""
        if not self._hass:
            return
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, self._STORE_VERSION, self._STORE_KEY)
        try:
            data = await self._store.async_load() or {}
            for area_id, rd in data.get("rooms", {}).items():
                room = self._get_room(area_id, rd.get("name", area_id))
                room.total_samples = int(rd.get("total_samples", 0))
                room.learned_orientation = rd.get("learned_orientation")
                room.orientation_confident = bool(rd.get("orientation_confident", False))
                room.last_sample_at = rd.get("last_sample_at")
                for bi, bdata in rd.get("buckets", {}).items():
                    from .shutter_thermal_learner import AzimuthBucket
                    bucket = room.buckets.setdefault(int(bi), AzimuthBucket())
                    bucket.count = int(bdata.get("count", 0))
                    bucket.total_rise = float(bdata.get("total_rise", 0.0))
            import logging as _l
            _l.getLogger(__name__).debug(
                "ShutterThermalLearner: %d kamers geladen", len(data.get("rooms", {}))
            )
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("ShutterThermalLearner: laden mislukt: %s", exc)

    async def _async_save(self) -> None:
        """Sla kamerorientaties op als dirty."""
        import time as _t
        if not self._store or not self._dirty:
            return
        if _t.time() - self._last_save < 600:
            return
        rooms_data = {}
        for area_id, room in self._rooms.items():
            rooms_data[area_id] = {
                "name":                room.name,
                "total_samples":       room.total_samples,
                "learned_orientation": room.learned_orientation,
                "orientation_confident": room.orientation_confident,
                "last_sample_at":      room.last_sample_at,
                "buckets": {
                    str(bi): {"count": b.count, "total_rise": b.total_rise}
                    for bi, b in room.buckets.items()
                },
            }
        try:
            await self._store.async_save({"rooms": rooms_data})
            self._dirty = False
            self._last_save = _t.time()
        except Exception as exc:
            import logging as _l
            _l.getLogger(__name__).warning("ShutterThermalLearner: opslaan mislukt: %s", exc)

    # ── Publieke API ─────────────────────────────────────────────────────────

    def update(
        self,
        area_id: str,
        area_name: str,
        room_temp_c: float,
        solar_azimuth: float,
        solar_elevation: float,
    ) -> Optional[str]:
        """Voeg een meting toe. Geeft geleerde oriëntatie terug (of None)."""
        if solar_elevation < MIN_SOLAR_ELEVATION:
            # Geen zon — sla temperatuur op als referentie
            room = self._get_room(area_id, area_name)
            room.last_temp_c = room_temp_c
            return room.learned_orientation if room.orientation_confident else None

        room = self._get_room(area_id, area_name)

        # Bereken temperatuurstijging t.o.v. vorige meting
        if room.last_temp_c is not None:
            rise = room_temp_c - room.last_temp_c
            if rise >= MIN_TEMP_RISE_C:
                bucket_idx = _azimuth_to_bucket(solar_azimuth)
                bucket = room.buckets.setdefault(bucket_idx, AzimuthBucket())
                bucket.add(rise)
                room.total_samples += 1
                room.last_sample_at = dt_util.now().isoformat()
                self._dirty = True

                # Herbereken oriëntatie als genoeg samples
                if room.total_samples >= MIN_SAMPLES_CONFIDENT:
                    self._recalculate_orientation(room)

        room.last_temp_c = room_temp_c
        return room.learned_orientation if room.orientation_confident else None

    def get_orientation(self, area_id: str) -> str:
        """Geef geleerde oriëntatie voor een kamer."""
        room = self._rooms.get(area_id)
        if room and room.orientation_confident:
            return room.learned_orientation
        return SHUTTER_ORIENTATION_UNKNOWN

    def get_status(self) -> list[dict]:
        """Geef leerdata terug voor alle kamers."""
        result = []
        for room in self._rooms.values():
            dominant_bucket = self._dominant_bucket(room)
            result.append({
                "area_id":             room.area_id,
                "area_name":           room.area_name,
                "orientation":         room.learned_orientation,
                "confident":           room.orientation_confident,
                "total_samples":       room.total_samples,
                "dominant_azimuth":    dominant_bucket * 45 + 22.5 if dominant_bucket is not None else None,
                "last_sample_at":      room.last_sample_at,
                "bucket_summary":      {
                    str(k * 45) + "°": round(v.avg_rise, 2)
                    for k, v in sorted(room.buckets.items()) if v.samples > 0
                },
            })
        return result

    def reset_room(self, area_id: str) -> None:
        """Reset leerdata voor één kamer."""
        if area_id in self._rooms:
            name = self._rooms[area_id].area_name
            self._rooms[area_id] = RoomLearnerState(area_id=area_id, area_name=name)
            _LOGGER.info("CloudEMS ShutterLearner: reset kamer %s", area_id)

    # ── Persistentie ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {aid: r.to_dict() for aid, r in self._rooms.items()}

    def from_dict(self, data: dict) -> None:
        for aid, rdata in data.items():
            self._rooms[aid] = RoomLearnerState.from_dict(rdata)

    # ── Intern ───────────────────────────────────────────────────────────────

    def _get_room(self, area_id: str, area_name: str) -> RoomLearnerState:
        if area_id not in self._rooms:
            self._rooms[area_id] = RoomLearnerState(
                area_id=area_id, area_name=area_name
            )
        return self._rooms[area_id]

    def _recalculate_orientation(self, room: RoomLearnerState) -> None:
        """Bereken dominante oriëntatie op basis van azimuth buckets."""
        dominant = self._dominant_bucket(room)
        if dominant is None:
            return

        new_orientation = _bucket_to_orientation(dominant)
        if new_orientation != room.learned_orientation:
            _LOGGER.info(
                "CloudEMS ShutterLearner: kamer %s → oriëntatie %s (was %s, %d samples)",
                room.area_name or room.area_id,
                new_orientation,
                room.learned_orientation,
                room.total_samples,
            )
        room.learned_orientation = new_orientation
        room.orientation_confident = True

    @staticmethod
    def _dominant_bucket(room: RoomLearnerState) -> Optional[int]:
        """Geef bucket index met hoogste gemiddelde temperatuurstijging."""
        if not room.buckets:
            return None
        return max(room.buckets.items(), key=lambda kv: kv[1].avg_rise)[0]
