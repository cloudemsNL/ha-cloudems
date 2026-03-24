# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved.

"""
CloudEMS — EV Trip Planner v1.0.0

Combines calendar events with learned driving patterns to plan EV charging.
Charges exactly enough for tomorrow's trip at the cheapest EPEX moment.

How it works:
  1. Reads HA Calendar entities for events that indicate trips (work, meetings, travel)
  2. Learns average km driven per trip type from historical SOC changes
  3. Calculates required charge for next trip
  4. Finds cheapest EPEX window before departure to charge just enough

Unlike simple "charge when cheap" logic, this avoids unnecessary full charges
and prioritises battery longevity (fewer deep cycles).

Entity patterns used:
  calendar.*           — HA calendar entities (auto-discovered)
  sensor.*_battery     — EV battery SOC (linked via ev_charger config)
  sensor.*_range       — EV range (optional, improves accuracy)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Keywords that indicate a trip in calendar event titles
TRIP_KEYWORDS = (
    "work", "werk", "kantoor", "office", "meeting", "vergadering",
    "trip", "reis", "travel", "vakantie", "holiday", "uitje",
    "dokter", "doctor", "hospital", "ziekenhuis", "sport",
    "school", "training", "afspraak", "appointment",
)

# Minimum SOC to always keep available (for unexpected trips)
MIN_RESERVE_SOC_PCT  = 20.0
# kWh per % SOC (default 0.77 kWh/% for 77 kWh battery — learned over time)
DEFAULT_KWH_PER_PCT  = 0.77
# Minimum trip distance in km before we bother planning
MIN_TRIP_KM          = 5.0
# Default assumed km per trip if no history (learned from SOC changes)
DEFAULT_TRIP_KM      = 40.0


@dataclass
class TripEvent:
    """A calendar event that may require EV charging."""
    title:          str
    start_dt:       datetime
    end_dt:         datetime
    estimated_km:   float = DEFAULT_TRIP_KM
    required_kwh:   float = 0.0
    required_soc:   float = 0.0
    source:         str   = "calendar"  # "calendar" | "learned" | "manual"


@dataclass
class ChargeRecommendation:
    """Charging recommendation for an upcoming trip."""
    needed:             bool    = False
    target_soc_pct:     float   = 0.0
    current_soc_pct:    float   = 0.0
    kwh_to_add:         float   = 0.0
    charge_by:          Optional[datetime] = None  # latest time to start charging
    cheapest_window_start: Optional[datetime] = None
    price_at_window:    float   = 0.0
    trip:               Optional[TripEvent] = None
    reason:             str     = ""


class EVTripLearner:
    """
    Learns average km per trip type from historical EV SOC changes.
    Persists learned values via HA Storage.
    """

    def __init__(self) -> None:
        # trip_type → average km (EMA learned)
        self._km_by_type: dict[str, float] = {}
        self._total_trips: int = 0
        self._ema_alpha: float = 0.15

    def record_trip(self, trip_type: str, soc_before: float, soc_after: float,
                    kwh_per_pct: float = DEFAULT_KWH_PER_PCT) -> None:
        """Record a completed trip to improve future estimates."""
        soc_used = soc_before - soc_after
        if soc_used < 2:
            return  # Too small to be meaningful
        km_estimate = soc_used * kwh_per_pct * 6.0  # ~6 km/kWh average EV
        existing = self._km_by_type.get(trip_type, DEFAULT_TRIP_KM)
        self._km_by_type[trip_type] = (
            self._ema_alpha * km_estimate + (1 - self._ema_alpha) * existing
        )
        self._total_trips += 1
        _LOGGER.debug("EVTripLearner: recorded %s trip, %.0f km (EMA: %.0f km)",
                      trip_type, km_estimate, self._km_by_type[trip_type])

    def estimate_km(self, trip_type: str) -> float:
        """Get estimated km for a trip type."""
        return self._km_by_type.get(trip_type, DEFAULT_TRIP_KM)

    def to_dict(self) -> dict:
        return {"km_by_type": self._km_by_type, "total_trips": self._total_trips}

    def from_dict(self, data: dict) -> None:
        self._km_by_type  = data.get("km_by_type", {})
        self._total_trips = data.get("total_trips", 0)


class EVTripPlanner:
    """
    Plans EV charging based on upcoming calendar events and learned trip patterns.
    """

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._learner = EVTripLearner()
        self._calendar_entities: list[str] = []
        self._ev_soc_entity: Optional[str] = config.get("v2h_car_soc_entity") or \
                                              config.get("ev_soc_entity")
        self._kwh_per_pct: float = float(config.get("ev_kwh_per_pct", DEFAULT_KWH_PER_PCT))

    async def async_setup(self) -> None:
        """Auto-discover calendar entities."""
        self._calendar_entities = [
            s.entity_id for s in self._hass.states.async_all("calendar")
        ]
        _LOGGER.info("EVTripPlanner: found %d calendar entities", len(self._calendar_entities))

    def get_upcoming_trips(self, hours_ahead: int = 24) -> list[TripEvent]:
        """Find trip events in the next N hours from HA calendars."""
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        trips = []

        for eid in self._calendar_entities:
            state = self._hass.states.get(eid)
            if not state or state.state == "off":
                continue
            attr = state.attributes
            title = (attr.get("message") or attr.get("summary") or "").lower()

            # Only process events with trip-related keywords
            is_trip = any(kw in title for kw in TRIP_KEYWORDS)
            if not is_trip:
                continue

            # Parse start time
            start_str = attr.get("start_time") or attr.get("start")
            if not start_str:
                continue
            try:
                if isinstance(start_str, str):
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    start_dt = start_dt.replace(tzinfo=None)  # naive
                else:
                    start_dt = start_str
            except (ValueError, TypeError):
                continue

            if start_dt < now or start_dt > cutoff:
                continue

            # Determine trip type from keywords
            trip_type = "work" if any(k in title for k in ("werk", "work", "kantoor", "office")) \
                else "appointment" if any(k in title for k in ("dokter", "doctor", "afspraak")) \
                else "other"

            estimated_km  = self._learner.estimate_km(trip_type)
            required_kwh  = estimated_km / 6.0  # ~6 km/kWh
            required_soc  = (required_kwh / self._kwh_per_pct) + MIN_RESERVE_SOC_PCT

            trips.append(TripEvent(
                title        = attr.get("message") or attr.get("summary") or eid,
                start_dt     = start_dt,
                end_dt       = start_dt + timedelta(hours=1),
                estimated_km = estimated_km,
                required_kwh = round(required_kwh, 1),
                required_soc = min(100.0, round(required_soc, 1)),
                source       = "calendar",
            ))

        return sorted(trips, key=lambda t: t.start_dt)

    def get_recommendation(self, current_soc_pct: float,
                           epex_prices: list[dict]) -> ChargeRecommendation:
        """
        Returns a charging recommendation for the next trip.

        Args:
            current_soc_pct: Current EV battery SOC (0-100)
            epex_prices: List of {"hour": datetime, "price": float} dicts
        """
        trips = self.get_upcoming_trips(hours_ahead=20)
        if not trips:
            # No calendar trips — check if AI pattern learner has a prediction
            # (passed via ai_departure_h / ai_min_soc attributes on self)
            _ai_h   = getattr(self, '_ai_departure_h', None)
            _ai_soc = getattr(self, '_ai_min_soc', None)
            if _ai_h is not None and _ai_soc is not None:
                import datetime as _dt_ai
                _now = _dt_ai.datetime.now()
                _dep_h = int(_ai_h)
                _dep_m = int((_ai_h - _dep_h) * 60)
                _dep_dt = _now.replace(hour=_dep_h, minute=_dep_m, second=0)
                if _dep_dt > _now:
                    # Synthesize a trip from AI prediction
                    fake_trip = TripEvent(
                        title="AI voorspeld vertrek",
                        start_dt=_dep_dt,
                        end_dt=_dep_dt,
                        required_soc=float(_ai_soc),
                        source="learned",
                    )
                    trips = [fake_trip]
            if not trips:
                return ChargeRecommendation(needed=False, reason="No upcoming trips in calendar")

        next_trip = trips[0]

        # Already have enough SOC?
        if current_soc_pct >= next_trip.required_soc:
            return ChargeRecommendation(
                needed          = False,
                target_soc_pct  = next_trip.required_soc,
                current_soc_pct = current_soc_pct,
                trip            = next_trip,
                reason          = f"Sufficient SOC ({current_soc_pct:.0f}% ≥ {next_trip.required_soc:.0f}%)"
            )

        # Calculate how much to add
        kwh_to_add = (next_trip.required_soc - current_soc_pct) * self._kwh_per_pct

        # Find cheapest EPEX window before departure
        now = datetime.now()
        cheapest = None
        cheapest_price = float("inf")
        hours_until_trip = (next_trip.start_dt - now).total_seconds() / 3600

        for entry in epex_prices:
            try:
                hour_dt = entry.get("hour") or entry.get("datetime")
                if isinstance(hour_dt, str):
                    hour_dt = datetime.fromisoformat(hour_dt.replace("Z", ""))
                price = float(entry.get("price", 0))
                if now <= hour_dt < next_trip.start_dt and price < cheapest_price:
                    cheapest_price = price
                    cheapest = hour_dt
            except (ValueError, TypeError, KeyError):
                continue

        return ChargeRecommendation(
            needed                = True,
            target_soc_pct        = next_trip.required_soc,
            current_soc_pct       = current_soc_pct,
            kwh_to_add            = round(kwh_to_add, 1),
            charge_by             = next_trip.start_dt,
            cheapest_window_start = cheapest,
            price_at_window       = round(cheapest_price, 4) if cheapest else 0.0,
            trip                  = next_trip,
            reason                = (
                f"Trip '{next_trip.title}' at {next_trip.start_dt.strftime('%H:%M')}, "
                f"need {next_trip.required_soc:.0f}% SOC for ~{next_trip.estimated_km:.0f} km"
            )
        )

    def get_status(self) -> dict:
        """Status dict for coordinator data / sensor attributes."""
        return {
            "calendar_entities":  self._calendar_entities,
            "learned_trips":      self._learner.to_dict(),
            "ev_soc_entity":      self._ev_soc_entity,
        }
