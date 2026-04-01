# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — KNMI Automatische Kalibratie (v1.0.0).

Haalt elke uur de dichtstbijzijnde KNMI-meting op en gebruikt die
om de lokale temperatuursensor te kalibreren via EMA-offset.

API: KNMI Open Data (geen API key nodig voor publieke datasets)
  https://api.knmi.nl/open-data/datasets/actuele10mindataKNMIstations/
  Velden: T (temp °C ×10), FF (wind m/s ×10), RH (neerslag mm ×10), P (druk hPa ×10)

KALIBRATIE
══════════
  delta = knmi_temp - onze_temp
  offset = alpha × delta + (1-alpha) × offset_prev  (EMA, alpha=0.05)
  quality_boost: sensor kwaliteit +15 na 48u kalibratie

GEBRUIK
═══════
  calibrator = KnmiCalibration(lat, lon, session)
  await calibrator.async_refresh()
  offset = calibrator.temp_offset_c
  nearest = calibrator.nearest_station
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

KNMI_STATIONS_URL = (
    "https://api.knmi.nl/open-data/datasets"
    "/actuele10mindataKNMIstations/versions/2/files"
)
# Fallback: buienradar stationmeasurements (geen API key, public)
BUIENRADAR_URL = "https://data.buienradar.nl/2.0/feed/json"

REFRESH_INTERVAL_S = 3600   # 1 uur
ALPHA              = 0.05   # EMA voor kalibratie (traag bijsturen)


class KnmiCalibration:
    """Kalibreert lokale temperatuursensor tegen KNMI-referentie.

    Gebruikt Buienradar JSON als primaire bron (geen API key nodig,
    vrij voor niet-commercieel HA-gebruik). Voor commerciële deployments:
    eigen KNMI Open Data API key instellen.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        session: aiohttp.ClientSession,
    ) -> None:
        self._lat     = lat
        self._lon     = lon
        self._session = session

        self._temp_offset:    float = 0.0
        self._wind_offset:    float = 0.0
        self._nearest_station: Optional[str] = None
        self._nearest_dist_km: Optional[float] = None
        self._last_refresh:   float = 0.0
        self._calibration_hours: int = 0   # uren gekalibreerd
        self._last_knmi_temp: Optional[float] = None
        self._last_knmi_wind: Optional[float] = None

    @property
    def temp_offset_c(self) -> float:
        """Correctie-offset voor lokale temperatuursensor (°C)."""
        return round(self._temp_offset, 2)

    @property
    def quality_boost(self) -> int:
        """Extra kwaliteitspunten na voldoende kalibratie."""
        if self._calibration_hours >= 48:
            return 15
        if self._calibration_hours >= 12:
            return 8
        return 0

    @property
    def nearest_station(self) -> Optional[str]:
        return self._nearest_station

    @property
    def is_calibrated(self) -> bool:
        return self._calibration_hours >= 6

    async def async_refresh(self, our_temp_c: Optional[float] = None) -> bool:
        """Haal KNMI data op en update kalibratie offset.

        Aanroepen max 1x per uur vanuit coordinator.
        Geeft True terug als kalibratie bijgewerkt is.
        """
        now = time.time()
        if now - self._last_refresh < REFRESH_INTERVAL_S:
            return False

        try:
            result = await self._fetch_buienradar()
            if result and our_temp_c is not None:
                knmi_temp = result["temp_c"]
                delta = knmi_temp - our_temp_c
                # EMA — niet te snel bijsturen (ons dak vs KNMI-mast verschil is normaal)
                self._temp_offset = (
                    ALPHA * delta + (1 - ALPHA) * self._temp_offset
                )
                self._last_knmi_temp = knmi_temp
                self._calibration_hours += 1
                _LOGGER.debug(
                    "KNMI kalibratie: station=%s dist=%.1fkm "
                    "knmi=%.1f°C ons=%.1f°C offset=%.2f°C",
                    self._nearest_station, self._nearest_dist_km or 0,
                    knmi_temp, our_temp_c, self._temp_offset,
                )

            if result and result.get("wind_ms") is not None:
                self._last_knmi_wind = result["wind_ms"]

            self._last_refresh = now
            return True

        except Exception as e:
            _LOGGER.debug("KNMI kalibratie fout: %s", e)
            return False

    async def _fetch_buienradar(self) -> Optional[dict]:
        """Haal dichtstbijzijnde KNMI-station op via Buienradar JSON API."""
        async with self._session.get(
            BUIENRADAR_URL,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "CloudEMS/5.5 (HA integration, non-commercial)"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)

        stations = data.get("actual", {}).get("stationmeasurements", [])
        if not stations:
            return None

        # Vind dichtstbijzijnde station met temperatuurdata
        best = None
        best_dist = float("inf")
        for st in stations:
            if st.get("temperature") is None:
                continue
            lat_s = st.get("lat") or st.get("stationlatitude")
            lon_s = st.get("lon") or st.get("stationlongitude")
            if lat_s is None or lon_s is None:
                continue
            dist = _haversine_km(self._lat, self._lon, float(lat_s), float(lon_s))
            if dist < best_dist:
                best_dist = dist
                best = st

        if best is None or best_dist > 75:
            return None   # Geen station binnen 75 km

        self._nearest_station  = best.get("stationname", "onbekend")
        self._nearest_dist_km  = round(best_dist, 1)

        wind_ms = None
        if best.get("windspeed") is not None:
            wind_ms = round(float(best["windspeed"]) / 3.6, 2)  # km/u → m/s

        return {
            "temp_c":   float(best["temperature"]),
            "wind_ms":  wind_ms,
            "station":  self._nearest_station,
            "dist_km":  best_dist,
        }

    def to_dict(self) -> dict:
        return {
            "nearest_station":    self._nearest_station,
            "nearest_dist_km":    self._nearest_dist_km,
            "temp_offset_c":      self.temp_offset_c,
            "calibration_hours":  self._calibration_hours,
            "quality_boost":      self.quality_boost,
            "is_calibrated":      self.is_calibrated,
            "last_knmi_temp_c":   self._last_knmi_temp,
            "last_knmi_wind_ms":  self._last_knmi_wind,
        }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))
