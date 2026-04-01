# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Weather Observation Collector (v1.0.0).

Verzamelt microklimaat-metingen van alle sensoren die een gebruiker
al in HA heeft gekoppeld aan CloudEMS. Dit vormt de basis voor:

  1. Betere lokale beslissingen (boiler, EV, rolluiken)
  2. Historisch weerarchief per installatie (verzekeringsmarkt)
  3. Toekomstig netwerk van duizenden stations → unieke NL-dataset

DATAKWALITEIT EN IJKING
═══════════════════════
Elke meting bevat kwaliteitsmetadata zodat afnemers weten
hoe betrouwbaar de waarde is:

  quality: 0–100
    100 = gekalibreerd, professioneel station
     80 = HA-weerstation, betrouwbare positie
     60 = proxy-meting (bijv. PV → bewolking)
     40 = indirect afgeleid (bijv. rolluik → windstoot)
     20 = onbekende sensorpositie/kwaliteit

  calibration_ref: KNMI-stationsnummer of None
    Als set: meting is gecorrigeerd tegen KNMI-referentie
    Factor opgeslagen zodat afnemers de ruwe waarde ook krijgen

SENSOREN DIE AUTOMATISCH WORDEN HERKEND
════════════════════════════════════════
CloudEMS leest uit de geconfigureerde HA-entiteiten:

Direct (als gebruiker heeft geconfigureerd):
  - Buitentemperatuur        → weather entity / temperature sensor
  - Windsnelheid / richting  → weather entity / wind sensor
  - Neerslag                 → rain sensor / precipitation sensor
  - Luchtdruk                → pressure sensor / weather entity
  - Luchtvochtigheid         → humidity sensor / weather entity
  - UV-index                 → UV sensor

Indirect (altijd aanwezig):
  - PV-bewolking proxy       → pv_forecast vs pv_actual
  - Windstoot proxy          → rolluik windbeveiliging activatie
  - Thermische isolatiewaarde → buiten- vs binnentemperatuur delta

CLOUD-READY SCHEMA
══════════════════
Elk ObservationRecord is klaar voor upload naar:
  AdaptiveHome API → POST /api/v1/weather_observations

Toekomstige afnemers:
  - KNMI / meteobedrijven (microklimaat dataset)
  - Verzekeringsmaatschappijen (schade-verificatie per adres)
  - Netbeheerders (wind/zon correlatie voor netbalancering)
  - Klimaatonderzoekers (hyperlocale historische data)

BUSINESS MODEL VOORBEREIDING
═════════════════════════════
Data wordt opgeslagen met:
  - Anonieme installatie_id (SHA-256 hash, geen adres)
  - GPS afgerond op 0.01° (~1km privacy)
  - Sensor metadata: type, hoogte, oriëntatie, ijkingsstatus

Verkoop-tiers (toekomstig):
  - Tier 1: Geaggregeerd per uur per postcode (goedkoop)
  - Tier 2: Per 10 minuten per locatie met kwaliteitsscore
  - Tier 3: Real-time stream + historisch archief + API
  - Tier 4: Maatwerk voor verzekeringsmarkt (per claim verificatie)
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Any

_LOGGER = logging.getLogger(__name__)

# Maximaal lokaal te bewaren observaties (±7 dagen bij 10-min interval)
MAX_OBSERVATIONS = 1008

# Minimale kwaliteitsscore om op te slaan (alles < 20 is te onbetrouwbaar)
MIN_QUALITY_SCORE = 20


@dataclass
class SensorMeta:
    """Metadata over de sensor die een meting levert.

    Essentieel voor ijking en kwaliteitsbeoordeling door afnemers.
    """
    entity_id:      str
    sensor_type:    str             # 'weather', 'temperature', 'wind', 'rain', 'pressure', 'pv_proxy', 'shutter_proxy'
    quality:        int             # 0-100
    height_m:       Optional[float] = None   # hoogte boven maaiveld
    orientation:    Optional[str]   = None   # 'N', 'NE', ... voor buitensensoren
    calibrated:     bool            = False
    calibration_ref: Optional[str] = None   # KNMI-stationsnummer
    calibration_factor: float       = 1.0   # correctiefactor
    calibration_offset: float       = 0.0   # correctie-offset

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObservationRecord:
    """Één tijdstip met alle beschikbare metingen. Cloud-ready schema."""
    timestamp_utc:  str     # ISO 8601
    lat_rounded:    float   # GPS 0.01° (~1km)
    lon_rounded:    float   # GPS 0.01° (~1km)
    installation_id: str    # SHA-256 hash, nooit raw entry_id

    # Atmosferische variabelen
    temp_out_c:         Optional[float] = None   # buitentemperatuur °C
    temp_in_c:          Optional[float] = None   # binnentemperatuur °C
    humidity_pct:       Optional[float] = None   # luchtvochtigheid %
    pressure_hpa:       Optional[float] = None   # luchtdruk hPa
    wind_speed_ms:      Optional[float] = None   # windsnelheid m/s
    wind_dir_deg:       Optional[float] = None   # windrichting °
    wind_gust_ms:       Optional[float] = None   # windstoot m/s
    rain_mm_h:          Optional[float] = None   # neerslag mm/uur
    rain_mm_day:        Optional[float] = None   # neerslag mm/dag totaal
    uv_index:           Optional[float] = None   # UV-index
    visibility_km:      Optional[float] = None   # zicht km

    # PV-afgeleide variabelen (altijd aanwezig)
    cloud_cover_pv_pct: Optional[float] = None   # bewolking via PV proxy
    solar_irr_wm2:      Optional[float] = None   # zonnestraling W/m²
    pv_forecast_w:      Optional[float] = None   # verwachte PV productie
    pv_actual_w:        Optional[float] = None   # werkelijke PV productie

    # Indirecte proxies
    wind_gust_proxy:    Optional[bool]  = None   # rolluik windbeveiliging actief
    thermal_loss_w_k:   Optional[float] = None   # thermisch verlies W/K (isolatiewaarde)

    # Kwaliteit per variabele (gemiddelde kwaliteitsscore van sensors)
    quality_temp:       int = 0
    quality_wind:       int = 0
    quality_rain:       int = 0
    quality_pressure:   int = 0
    quality_cloud:      int = 0

    # Upload tracking
    uploaded:           bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def has_meaningful_data(self) -> bool:
        """True als minimaal één meteorologische waarde aanwezig is."""
        return any([
            self.temp_out_c is not None,
            self.wind_speed_ms is not None,
            self.rain_mm_h is not None,
            self.cloud_cover_pv_pct is not None,
            self.pressure_hpa is not None,
        ])


class WeatherObservationCollector:
    """Verzamelt en bewaard microklimaat-observaties.

    Gebruik in coordinator:
        collector = WeatherObservationCollector(lat, lon, entry_id)
        record = collector.observe(coordinator_data, hass)
        upload_batch = collector.get_upload_batch()
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        installation_id: str,
    ) -> None:
        self._lat = round(lat, 2)
        self._lon = round(lon, 2)
        self._install_id = hashlib.sha256(
            installation_id.encode()
        ).hexdigest()[:16]

        self._observations: list[ObservationRecord] = []
        self._sensor_meta:  dict[str, SensorMeta]  = {}
        self._last_obs_ts:  float = 0.0

        # KNMI-kalibratie referentie (toekomstig: ophalen uit KNMI open data)
        self._knmi_station: Optional[str] = None
        self._knmi_temp_offset: float = 0.0
        self._knmi_last_calibrated: float = 0.0

        # Statistieken voor sensor health monitoring
        self._total_records:   int = 0
        self._records_with_wind: int = 0
        self._records_with_rain: int = 0
        self._records_with_temp: int = 0

    def register_sensor(
        self,
        entity_id: str,
        sensor_type: str,
        quality: int = 60,
        height_m: Optional[float] = None,
        orientation: Optional[str] = None,
    ) -> None:
        """Registreer een sensor met metadata. Aanroepen vanuit config flow."""
        self._sensor_meta[entity_id] = SensorMeta(
            entity_id=entity_id,
            sensor_type=sensor_type,
            quality=quality,
            height_m=height_m,
            orientation=orientation,
        )

    def observe(
        self,
        data: dict,
        hass_states: dict,
        config: dict,
    ) -> Optional[ObservationRecord]:
        """Verzamel huidige observatie uit coordinator data + HA states.

        Aanroepen elke 10 minuten vanuit coordinator.
        Geeft ObservationRecord terug als er zinvolle data is.
        """
        now = time.time()
        # Max 1 observatie per 5 minuten (niet elke 10s)
        if now - self._last_obs_ts < 300:
            return None
        self._last_obs_ts = now

        rec = ObservationRecord(
            timestamp_utc  = datetime.now(timezone.utc).isoformat(),
            lat_rounded    = self._lat,
            lon_rounded    = self._lon,
            installation_id = self._install_id,
        )

        # ── PV-afgeleide data (altijd aanwezig) ──────────────────────────────
        pv_dip = data.get("pv_dip_detector", {})
        pv_dip_risk = data.get("pv_dip_risk", {})
        pv_w = float(data.get("pv_power_w") or 0)
        rec.pv_actual_w = round(pv_w, 0)
        rec.quality_cloud = 60   # proxy kwaliteit

        if pv_dip_risk.get("cloud_pct") is not None:
            rec.cloud_cover_pv_pct = float(pv_dip_risk["cloud_pct"])

        if pv_dip_risk.get("wind_ms") is not None and pv_dip_risk.get("wind_ms", 0) > 0:
            rec.wind_speed_ms = float(pv_dip_risk["wind_ms"])
            rec.wind_dir_deg  = float(pv_dip_risk.get("wind_dir", 0))
            rec.quality_wind  = 70   # Open-Meteo real-time kwaliteit

        # ── Rolluik windstoot proxy ───────────────────────────────────────────
        shutter_data = data.get("shutters", {})
        if isinstance(shutter_data, dict):
            shutters = shutter_data.get("shutters", [])
        else:
            shutters = shutter_data if isinstance(shutter_data, list) else []
        wind_protected = any(s.get("wind_protected") for s in shutters)
        if wind_protected:
            rec.wind_gust_proxy = True
            _LOGGER.debug("WeatherObserver: rolluik windbeveiliging actief → windstoot proxy")

        # ── Weer-entiteit (als geconfigureerd) ───────────────────────────────
        _weather_eid = config.get("weather_entity", "")
        if _weather_eid and _weather_eid in hass_states:
            ws = hass_states[_weather_eid]
            wa = ws.attributes if hasattr(ws, 'attributes') else (ws.get("attributes") or {})
            self._read_weather_entity(rec, wa)

        # ── Directe temperatuursensoren ──────────────────────────────────────
        _temp_eid = config.get("outdoor_temp_sensor", "")
        if _temp_eid and _temp_eid in hass_states:
            ts = hass_states[_temp_eid]
            try:
                v = float(ts.state if hasattr(ts, 'state') else ts.get("state", 0))
                if -40 <= v <= 60:
                    rec.temp_out_c   = round(v + self._knmi_temp_offset, 1)
                    rec.quality_temp = 75
            except (ValueError, TypeError):
                pass

        # ── Binnentemperatuur via thermostaat ────────────────────────────────
        climate_entities = [k for k in hass_states if k.startswith("climate.")]
        if climate_entities:
            temps = []
            for eid in climate_entities[:5]:  # max 5 zones
                st = hass_states[eid]
                try:
                    t = float((st.attributes if hasattr(st, 'attributes')
                               else st.get("attributes", {})).get("current_temperature", 0))
                    if 10 <= t <= 35:
                        temps.append(t)
                except (ValueError, TypeError, AttributeError):
                    pass
            if temps:
                rec.temp_in_c = round(sum(temps) / len(temps), 1)

        # ── Thermisch verlies berekening (isolatiewaarde) ────────────────────
        if (rec.temp_out_c is not None and rec.temp_in_c is not None
                and rec.temp_out_c < rec.temp_in_c - 3):
            # Heel ruwe schatting: huisverbruik voor verwarming / delta T
            house_w = float(data.get("house_power_w") or 0)
            delta_t = rec.temp_in_c - rec.temp_out_c
            if delta_t > 0 and house_w > 200:
                rec.thermal_loss_w_k = round(house_w / delta_t, 1)

        # ── Neerslag ─────────────────────────────────────────────────────────
        _rain_eid = config.get("rain_sensor", "")
        if _rain_eid and _rain_eid in hass_states:
            rs = hass_states[_rain_eid]
            try:
                v = float(rs.state if hasattr(rs, 'state') else rs.get("state", 0))
                rec.rain_mm_h    = round(max(0, v), 2)
                rec.quality_rain = 70
            except (ValueError, TypeError):
                pass

        # ── Sla op als zinvol ────────────────────────────────────────────────
        if not rec.has_meaningful_data:
            return None

        self._observations.append(rec)
        if len(self._observations) > MAX_OBSERVATIONS:
            self._observations = self._observations[-MAX_OBSERVATIONS:]

        self._total_records += 1
        if rec.wind_speed_ms: self._records_with_wind += 1
        if rec.rain_mm_h:     self._records_with_rain += 1
        if rec.temp_out_c:    self._records_with_temp += 1

        return rec

    def _read_weather_entity(self, rec: ObservationRecord, attrs: dict) -> None:
        """Lees data uit een HA weer-entiteit."""
        try:
            t = attrs.get("temperature")
            if t is not None and -40 <= float(t) <= 60:
                rec.temp_out_c   = round(float(t) + self._knmi_temp_offset, 1)
                rec.quality_temp = 70  # weather entity kwaliteit

            ws = attrs.get("wind_speed")
            if ws is not None:
                # HA weather entity geeft km/u, omzetten naar m/s
                rec.wind_speed_ms = round(float(ws) / 3.6, 2)
                rec.quality_wind  = 65

            wd = attrs.get("wind_bearing")
            if wd is not None:
                rec.wind_dir_deg = round(float(wd), 1)

            h = attrs.get("humidity")
            if h is not None and 0 <= float(h) <= 100:
                rec.humidity_pct = round(float(h), 1)

            p = attrs.get("pressure")
            if p is not None and 900 <= float(p) <= 1100:
                rec.pressure_hpa   = round(float(p), 1)
                rec.quality_pressure = 70

            pr = attrs.get("precipitation") or attrs.get("precipitation_unit")
            if pr is not None:
                rec.rain_mm_h    = round(max(0, float(pr)), 2)
                rec.quality_rain = 60

            vis = attrs.get("visibility")
            if vis is not None:
                rec.visibility_km = round(float(vis), 1)

        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.debug("WeatherObserver: weather entity parse fout: %s", e)

    def apply_knmi_calibration(
        self,
        knmi_station: str,
        knmi_temp_c: float,
        our_temp_c: float,
    ) -> None:
        """Kalibreer temperatuursensor tegen KNMI-referentie.

        Aanroepen als KNMI data beschikbaar is (toekomstig).
        De correctie-offset wordt persistent opgeslagen.
        """
        delta = knmi_temp_c - our_temp_c
        # EMA voor stabiele kalibratie (niet te snel bijsturen)
        alpha = 0.1
        self._knmi_temp_offset = (
            alpha * delta + (1 - alpha) * self._knmi_temp_offset
        )
        self._knmi_station = knmi_station
        self._knmi_last_calibrated = time.time()

        for meta in self._sensor_meta.values():
            if meta.sensor_type == "temperature":
                meta.calibrated = True
                meta.calibration_ref = knmi_station
                meta.calibration_offset = round(self._knmi_temp_offset, 2)
                meta.quality = min(90, meta.quality + 15)

        _LOGGER.info(
            "WeatherObserver: KNMI-kalibratie station=%s offset=%.2f°C",
            knmi_station, self._knmi_temp_offset,
        )

    def get_upload_batch(self, max_records: int = 100) -> list[dict]:
        """Geef niet-geüploade observaties terug voor cloud upload."""
        batch = [r for r in self._observations if not r.uploaded][:max_records]
        for r in batch:
            r.uploaded = True
        return [r.to_dict() for r in batch]

    def get_recent(self, n: int = 12) -> list[dict]:
        """Geef laatste N observaties terug."""
        return [r.to_dict() for r in self._observations[-n:]]

    def get_statistics(self) -> dict:
        """Overzicht van verzamelde data voor sensor health dashboard."""
        recent = self._observations[-6:] if self._observations else []
        return {
            "total_records":        self._total_records,
            "records_with_wind":    self._records_with_wind,
            "records_with_rain":    self._records_with_rain,
            "records_with_temp":    self._records_with_temp,
            "wind_coverage_pct":    round(
                self._records_with_wind / max(1, self._total_records) * 100, 0),
            "temp_coverage_pct":    round(
                self._records_with_temp / max(1, self._total_records) * 100, 0),
            "knmi_calibrated":      self._knmi_station is not None,
            "knmi_station":         self._knmi_station,
            "knmi_temp_offset_c":   round(self._knmi_temp_offset, 2),
            "upload_pending":       sum(1 for r in self._observations if not r.uploaded),
            "available_variables":  self._available_variables(recent),
        }

    def _available_variables(self, recent: list[ObservationRecord]) -> list[str]:
        """Welke variabelen zijn de laatste 6 observaties beschikbaar."""
        vars_found = set()
        for r in recent:
            if r.temp_out_c is not None:    vars_found.add("temperature")
            if r.wind_speed_ms is not None: vars_found.add("wind")
            if r.rain_mm_h is not None:     vars_found.add("rain")
            if r.pressure_hpa is not None:  vars_found.add("pressure")
            if r.humidity_pct is not None:  vars_found.add("humidity")
            if r.cloud_cover_pv_pct is not None: vars_found.add("cloud_cover_pv")
            if r.wind_gust_proxy:           vars_found.add("wind_gust_proxy")
            if r.thermal_loss_w_k:          vars_found.add("thermal_insulation")
        return sorted(vars_found)

    def to_dict(self) -> dict:
        return {
            "installation_id": self._install_id,
            "lat_rounded":     self._lat,
            "lon_rounded":     self._lon,
            **self.get_statistics(),
            "recent":          self.get_recent(3),
        }
