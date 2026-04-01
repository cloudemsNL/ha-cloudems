# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — PV Dip Detector (v1.0.0).

Detecteert onverwachte dalingen in PV-productie en slaat events op
inclusief winddata. Dit vormt de basis voor het gedistribueerde
wolkradar-netwerk zodra meerdere installaties online zijn.

PRINCIPE
════════
Een wolk beweegt met de wind. Als installatie A om 12:03 een dip ziet,
en de wind waait van A naar B (40 km, 25 km/u), dan verwacht B de dip
om 12:03 + 96 min = 13:39.

Met genoeg installaties en real-time wind: 10-15 min voorspelling van
PV-dalingen, zodat batterij/boiler/EV alvast reageert.

DATA SCHEMA (cloud-ready)
══════════════════════════
Elk dip event bevat:
  - timestamp (UTC)
  - locatie (GPS afgerond op 0.01° = ~1km, privacy-veilig)
  - dip_pct: hoe groot de daling tov forecast (%)
  - pv_forecast_w: wat werd verwacht
  - pv_actual_w: wat er werkelijk was
  - wind_speed_ms: windsnelheid op dat moment
  - wind_dir_deg: windrichting (0=N, 90=O, 180=Z, 270=W)
  - cloud_shadow_w: geschatte omvang van de schaduw (W)
  - installation_id: anonieme hash van entry_id (geen PII)

CLOUD VOORBEREIDING
═══════════════════
events zijn klaar voor upload naar AdaptiveHome API:
  POST /api/v1/pv_dip_events  [{...event...}, ...]

Ontvangen events van andere installaties worden gebruikt voor
PV-dip voorspelling: als nabije installatie een dip meldde
en wind waait onze kant op, toon dan een waarschuwing.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Drempel: 20% onverwachte daling tov forecast = betekenisvolle dip
DIP_THRESHOLD_PCT  = 0.20   # 20%
# Minimale forecast om te vergelijken (nacht uitsluiten)
DIP_MIN_FORECAST_W = 200    # W
# Cooldown: niet elke 10s een event, maar max 1 per 5 min
DIP_COOLDOWN_S     = 300
# Max events bewaren (lokaal + voor cloud upload)
MAX_EVENTS_LOCAL   = 200
# Max cloud-upload batch
MAX_UPLOAD_BATCH   = 50


@dataclass
class PvDipEvent:
    """Één gedetecteerde PV-dip, cloud-ready."""
    timestamp_utc:   str    # ISO 8601
    lat_rounded:     float  # GPS 0.01° afgerond
    lon_rounded:     float  # GPS 0.01° afgerond
    dip_pct:         float  # bijv. 0.35 = 35% daling
    pv_forecast_w:   float  # verwacht vermogen (W)
    pv_actual_w:     float  # werkelijk vermogen (W)
    wind_speed_ms:   float  # m/s
    wind_dir_deg:    float  # graden (0=N, 90=O, 180=Z, 270=W)
    cloud_shadow_w:  float  # pv_forecast_w - pv_actual_w
    installation_id: str    # anonieme hash
    uploaded:        bool = False  # False = nog niet naar cloud gestuurd

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PvDipEvent":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PvDipPrediction:
    """Voorspelling van een naderende dip (van andere installaties, toekomstig)."""
    source_lat:      float
    source_lon:      float
    dip_pct:         float
    source_ts_utc:   str
    predicted_ts_utc: str   # wanneer de dip hier verwacht wordt
    travel_time_min: float  # reistijd wolk in minuten
    confidence:      float  # 0.0 - 1.0


class PvDipDetector:
    """Detecteert PV-dalingen en bereidt cloud-events voor.

    Gebruik:
        detector = PvDipDetector(lat, lon, installation_id)
        detector.observe(pv_forecast_w, pv_actual_w, wind_speed_ms, wind_dir_deg)
        events = detector.get_recent_events()
        upload_batch = detector.get_upload_batch()
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        installation_id: str,
    ) -> None:
        # Privacy: afronden op 0.01° (~1km)
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        # Anonieme hash van installation_id (nooit raw entry_id naar cloud)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        self._events: deque[PvDipEvent] = deque(maxlen=MAX_EVENTS_LOCAL)
        self._last_dip_ts: float = 0.0
        self._consecutive_dips: int = 0
        self._last_pv_w: float = 0.0

        # Statistieken
        self._total_detected: int = 0
        self._total_uploaded:  int = 0

        # Voorspellingen van andere installaties (toekomstig)
        self._incoming_predictions: list[PvDipPrediction] = []

    def observe(
        self,
        pv_forecast_w: float,
        pv_actual_w:   float,
        wind_speed_ms: float,
        wind_dir_deg:  float,
    ) -> Optional[PvDipEvent]:
        """Verwerk nieuwe meting. Geeft PvDipEvent terug als dip gedetecteerd."""
        if pv_forecast_w < DIP_MIN_FORECAST_W:
            return None   # nacht of bewolkt — geen referentie

        now = time.time()
        if now - self._last_dip_ts < DIP_COOLDOWN_S:
            return None   # cooldown actief

        dip_pct = (pv_forecast_w - pv_actual_w) / pv_forecast_w
        if dip_pct < DIP_THRESHOLD_PCT:
            self._consecutive_dips = 0
            self._last_pv_w = pv_actual_w
            return None   # geen significante dip

        # Dip gedetecteerd
        self._consecutive_dips += 1
        self._last_dip_ts = now
        self._total_detected += 1

        event = PvDipEvent(
            timestamp_utc   = datetime.now(timezone.utc).isoformat(),
            lat_rounded     = self._lat,
            lon_rounded     = self._lon,
            dip_pct         = round(dip_pct, 3),
            pv_forecast_w   = round(pv_forecast_w, 0),
            pv_actual_w     = round(pv_actual_w, 0),
            wind_speed_ms   = round(wind_speed_ms, 1),
            wind_dir_deg    = round(wind_dir_deg, 1),
            cloud_shadow_w  = round(pv_forecast_w - pv_actual_w, 0),
            installation_id = self._install_id,
            uploaded        = False,
        )
        self._events.append(event)

        _LOGGER.info(
            "PvDipDetector: dip gedetecteerd — %.0f%% daling "
            "(forecast=%.0fW actual=%.0fW wind=%.1fm/s uit %.0f°)",
            dip_pct * 100, pv_forecast_w, pv_actual_w,
            wind_speed_ms, wind_dir_deg,
        )
        return event

    def predict_travel_time(
        self,
        source_lat: float,
        source_lon: float,
        wind_speed_ms: float,
        wind_dir_deg: float,
    ) -> Optional[float]:
        """Bereken reistijd wolk van source naar deze installatie (minuten).

        Alleen zinvol als wind recht van source naar ons waait.
        Geeft None als de wind de verkeerde kant op waait.
        """
        if wind_speed_ms < 1.0:
            return None   # windstil — wolk beweegt niet voorspelbaar

        # Haversine afstand
        dist_km = _haversine_km(source_lat, source_lon, self._lat, self._lon)

        # Richting van source naar ons
        bearing = _bearing_deg(source_lat, source_lon, self._lat, self._lon)

        # Controleer of wind onze kant op waait
        # Wind_dir_deg = richting vanwaar de wind waait (meteorologisch)
        # Wind waait VAN wind_dir_deg, NAAR wind_dir_deg + 180
        wind_toward = (wind_dir_deg + 180) % 360
        angle_diff  = abs((bearing - wind_toward + 180) % 360 - 180)

        if angle_diff > 45:
            return None   # wind waait niet onze kant op

        # Effectieve snelheid in richting van source naar ons
        effective_speed = wind_speed_ms * math.cos(math.radians(angle_diff))
        if effective_speed < 0.5:
            return None

        # Reistijd in minuten
        travel_min = (dist_km * 1000 / effective_speed) / 60
        return round(travel_min, 1)

    def receive_cloud_event(
        self,
        event: dict,
        current_wind_ms: float,
        current_wind_dir: float,
    ) -> Optional[PvDipPrediction]:
        """Verwerk een dip event van een andere installatie (toekomstig).

        Berekent wanneer dezelfde wolk hier verwacht wordt.
        """
        try:
            src_lat = event["lat_rounded"]
            src_lon = event["lon_rounded"]
            travel  = self.predict_travel_time(
                src_lat, src_lon, current_wind_ms, current_wind_dir
            )
            if travel is None or travel > 60:
                return None   # te ver of verkeerde windrichting

            from datetime import timedelta
            src_ts = datetime.fromisoformat(event["timestamp_utc"])
            pred_ts = src_ts + timedelta(minutes=travel)

            # Confidence: hoe recht de wind, hoe betrouwbaar
            dist_km = _haversine_km(src_lat, src_lon, self._lat, self._lon)
            confidence = max(0.1, min(0.9, 1.0 - travel / 60.0))

            pred = PvDipPrediction(
                source_lat       = src_lat,
                source_lon       = src_lon,
                dip_pct          = event.get("dip_pct", 0),
                source_ts_utc    = event["timestamp_utc"],
                predicted_ts_utc = pred_ts.isoformat(),
                travel_time_min  = travel,
                confidence       = round(confidence, 2),
            )
            self._incoming_predictions.append(pred)
            # Bewaar max 20 voorspellingen
            self._incoming_predictions = self._incoming_predictions[-20:]
            return pred
        except Exception as exc:
            _LOGGER.debug("PvDipDetector: cloud event verwerking fout: %s", exc)
            return None


    def assess_dip_risk(
        self,
        cloud_pct: float,
        wind_speed_ms: float,
        wind_dir_deg: float,
        pv_forecast_w: float,
    ) -> dict:
        """Berekent actueel dip-risico op basis van bewolking + windrichting.

        Standalone bruikbaar zonder cloud-netwerk:
        - cloud_pct > 60% + wind > 3 m/s → wolk beweegt snel → hogere kans op dip
        - Geeft risico-score terug (0.0 - 1.0) + geschatte minuten tot impact

        Toekomst: als cloud-events van andere installaties beschikbaar zijn,
        gebruikt receive_cloud_event() een nauwkeuriger voorspelling.
        """
        if pv_forecast_w < DIP_MIN_FORECAST_W:
            return {"risk": 0.0, "reason": "nacht/laag", "minutes": None, "act": False}

        # Wolkdekking als primaire indicator
        # >80% = hoge kans, >60% = matige kans, <40% = laag risico
        cloud_risk = max(0.0, (cloud_pct - 40.0) / 60.0)  # 0→0, 100→1

        # Wind versterkt het risico: snel bewegende wolken → abrupte dips
        # >8 m/s = snel, <2 m/s = windstil (wolk staat bijna stil)
        wind_factor = min(1.0, max(0.0, (wind_speed_ms - 2.0) / 8.0))

        # Combineer: bewolking dominant, wind als versterker
        risk = min(1.0, cloud_risk * (0.7 + 0.3 * wind_factor))

        # Schat minuten tot mogelijke impact (hoe sneller de wind, hoe korter)
        # Aanname: wolk van 5 km afstand bij huidige windsnelheid
        minutes = None
        if wind_speed_ms > 1.0 and risk > 0.3:
            km_upstream = 5.0  # conservatieve schatting
            minutes = round((km_upstream * 1000 / wind_speed_ms) / 60, 0)
            minutes = max(5.0, min(30.0, minutes))  # realistisch bereik

        act = risk >= 0.5  # > 50% risico = actie ondernemen

        reason = (
            f"bewolking {cloud_pct:.0f}% wind {wind_speed_ms:.1f}m/s"
            if act else f"laag risico ({cloud_pct:.0f}% bewolkt)"
        )

        return {
            "risk":    round(risk, 2),
            "reason":  reason,
            "minutes": minutes,
            "act":     act,
            "cloud_pct": round(cloud_pct, 0),
            "wind_ms": round(wind_speed_ms, 1),
            "wind_dir": round(wind_dir_deg, 0),
        }

    def get_recent_events(self, n: int = 10) -> list[dict]:
        """Geef laatste N events als dict."""
        return [e.to_dict() for e in list(self._events)[-n:]]

    def get_upload_batch(self) -> list[dict]:
        """Geef events die nog niet naar cloud gestuurd zijn."""
        batch = [e for e in self._events if not e.uploaded][:MAX_UPLOAD_BATCH]
        for e in batch:
            e.uploaded = True
        return [e.to_dict() for e in batch]

    def get_active_prediction(self) -> Optional[dict]:
        """Geef de meest recente actieve voorspelling die nog in de toekomst ligt."""
        now = datetime.now(timezone.utc)
        for pred in reversed(self._incoming_predictions):
            try:
                pred_ts = datetime.fromisoformat(pred.predicted_ts_utc)
                if pred_ts > now:
                    return {
                        "predicted_ts":    pred.predicted_ts_utc,
                        "dip_pct":         pred.dip_pct,
                        "travel_time_min": pred.travel_time_min,
                        "confidence":      pred.confidence,
                        "minutes_away":    round((pred_ts - now).total_seconds() / 60, 1),
                    }
            except Exception:
                pass
        return None

    def to_dict(self) -> dict:
        return {
            "lat_rounded":      self._lat,
            "lon_rounded":      self._lon,
            "installation_id":  self._install_id,
            "total_detected":   self._total_detected,
            "total_uploaded":   self._total_uploaded,
            "recent_events":    self.get_recent_events(5),
            "active_prediction": self.get_active_prediction(),
        }


# ── Geodesische hulpfuncties ─────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Afstand in km tussen twee GPS-coördinaten (Haversine)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Kompasrichting van punt 1 naar punt 2 (graden, 0=N)."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) -
         math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon))
    return (math.degrees(math.atan2(y, x)) + 360) % 360
