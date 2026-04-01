# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Buurtwaakzaamheid Module (v1.0.0).

Detecteert ongebruikelijke aanwezigheidspatronen en deelt deze
anoniem via AdaptiveHome met geopteerde buren.

TRANSPARANTIE
═════════════
- Volledig opt-in via config flow stap "Data & Privacy"
- Gebruikers weten wat er gedeeld wordt (zie translations)
- Geen camera-beelden of persoonlijke data — alleen afgeleid patroon
- Meldingen gaan naar bewoners die zelf ook opt-in zijn

WAT DETECTEERBAAR IS VIA BESTAANDE SENSOREN
═══════════════════════════════════════════
- Aanwezigheidspatroon afwijking (absence_detector geeft is_home)
- Ongebruikelijk lichtgebruik: lichten aan op slaaptijd + niemand thuis
- Beweging zonder aanwezigheid: alarmsensor via HA
- Deurbel/deurcontact zonder verwachte aankomst
- Stroomverbruik anomalie: apparaten aan terwijl niemand thuis

PRIVACY-GARANTIES
═════════════════
- GPS afgerond op 0.01° (~1km) — niet adres-nauwkeurig
- installation_id = SHA-256 hash
- Geen camerabeelden, geen audio
- Meldingen zijn "verdachte activiteit in jouw buurt" — geen adres

BUURTWAAKZAAMHEID WEBSITE (toekomstig: cloudems.eu/buurtwaakzaamheid)
══════════════════════════════════════════════════════════════════════
- Bewoners melden zich aan voor push-meldingen
- Email/telefoonnummer verificatie
- Koppelen aan postcode-gebied (op basis van GPS-radius)
- CloudEMS stuurt events → AdaptiveHome → push naar geregistreerden
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Drempels
MIN_ANOMALY_CONFIDENCE = 0.50   # minimale confidence voor melding
COOLDOWN_S             = 1800   # max 1 melding per 30 min
MAX_EVENTS_LOCAL       = 50


@dataclass
class WatchEvent:
    """Buurtwaakzaamheid event — cloud-ready schema."""
    timestamp_utc:    str
    installation_id:  str
    lat_rounded:      float
    lon_rounded:      float
    event_type:       str          # "unusual_activity" | "vacancy_anomaly" | "sensor_trigger"
    confidence:       float        # 0.0-1.0
    description:      str          # mensvriendelijk, geen adres
    duration_s:       Optional[float] = None
    uploaded:         bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class NeighbourhoodWatch:
    """Detecteert ongebruikelijke patronen voor buurtwaakzaamheid.

    Gebruik in coordinator (alleen als share_neighbourhood=True):
        watch = NeighbourhoodWatch(lat, lon, entry_id)
        event = watch.observe(
            is_home=False,
            lights_on=True,
            motion_detected=False,
            door_open=False,
            hour=2,
        )
    """

    def __init__(self, lat: float, lon: float, installation_id: str) -> None:
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        self._events:    list[WatchEvent] = []
        self._last_ts:   float = 0.0
        self._total:     int = 0

        # Patroon tracking
        self._vacancy_since:  Optional[float] = None
        self._anomaly_start:  Optional[float] = None

    def observe(
        self,
        is_home:          bool,
        lights_on:        bool,
        motion_detected:  bool,
        door_open:        bool,
        hour:             int,
        alarm_triggered:  bool = False,
        power_anomaly:    bool = False,
    ) -> Optional[WatchEvent]:
        """Verwerk huidige aanwezigheidsstatus. Geeft event bij anomalie."""
        now = time.time()
        if now - self._last_ts < COOLDOWN_S:
            return None

        confidence = 0.0
        reasons    = []
        event_type = "unusual_activity"

        # Track leegstand
        if not is_home:
            if self._vacancy_since is None:
                self._vacancy_since = now
        else:
            self._vacancy_since = None

        vacancy_hours = ((now - self._vacancy_since) / 3600
                         if self._vacancy_since else 0)

        # ── Alarm getriggerd ─────────────────────────────────────────────────
        if alarm_triggered:
            confidence = 0.90
            reasons.append("alarmsysteem geactiveerd")
            event_type = "sensor_trigger"

        # ── Lichten aan, niemand thuis, slaaptijd ────────────────────────────
        elif lights_on and not is_home and 0 <= hour <= 5:
            confidence = max(confidence, 0.60)
            reasons.append("lichten aan om " + str(hour) + ":00 terwijl huis leeg is")
            event_type = "vacancy_anomaly"

        # ── Beweging zonder bewoner + licht aan ─────────────────────────────
        elif motion_detected and not is_home and lights_on:
            confidence = max(confidence, 0.70)
            reasons.append("beweging en licht zonder aanwezige bewoner")
            event_type = "unusual_activity"

        # ── Deur open bij langdurige afwezigheid ─────────────────────────────
        elif door_open and vacancy_hours > 24 and not is_home:
            confidence = max(confidence, 0.55)
            reasons.append(f"deur geopend na {vacancy_hours:.0f}u leegstand")
            event_type = "unusual_activity"

        # ── Stroomverbruik anomalie + leeg huis ──────────────────────────────
        elif power_anomaly and not is_home and vacancy_hours > 2:
            confidence = max(confidence, 0.50)
            reasons.append("ongebruikelijk stroomverbruik bij leeg huis")
            event_type = "vacancy_anomaly"

        if confidence < MIN_ANOMALY_CONFIDENCE or not reasons:
            return None

        description = "; ".join(reasons)
        event = WatchEvent(
            timestamp_utc   = datetime.now(timezone.utc).isoformat(),
            installation_id = self._install_id,
            lat_rounded     = self._lat,
            lon_rounded     = self._lon,
            event_type      = event_type,
            confidence      = round(confidence, 2),
            description     = description,
            duration_s      = round(now - self._vacancy_since, 0)
                              if self._vacancy_since else None,
        )

        self._events.append(event)
        if len(self._events) > MAX_EVENTS_LOCAL:
            self._events = self._events[-MAX_EVENTS_LOCAL:]

        self._last_ts = now
        self._total  += 1

        _LOGGER.info(
            "NeighbourhoodWatch: anomalie gedetecteerd — %s (confidence=%.0f%%)",
            description, confidence * 100,
        )
        return event

    def get_upload_batch(self) -> list[dict]:
        batch = [e for e in self._events if not e.uploaded][:20]
        for e in batch:
            e.uploaded = True
        return [e.to_dict() for e in batch]

    def to_dict(self) -> dict:
        return {
            "installation_id": self._install_id,
            "total_events":    self._total,
            "upload_pending":  sum(1 for e in self._events if not e.uploaded),
            "is_vacant":       self._vacancy_since is not None,
            "vacancy_hours":   round((time.time() - self._vacancy_since) / 3600, 1)
                               if self._vacancy_since else 0,
        }
