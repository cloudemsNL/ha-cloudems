"""
CloudEMS Smart Sensor Discovery — v1.0.0

Scant automatisch alle Home Assistant entiteiten en herkent:
  1. Smart plug vermogenssensoren  → NILM-ankers (bekend apparaat, bekende fase)
  2. Weersensoren                  → temperatuur, zonnestraling voor contextpriors
  3. Apparaatnamen in entiteit-ID  → koppel aan NILM device_type

Geen configuratie nodig: de discovery draait bij opstart en elke 5 minuten.
Nieuwe sensoren worden automatisch opgepikt zodra ze in HA verschijnen.

Hoe werkt de koppeling:
  - Entiteit-ID of friendly_name wordt vergeleken met een keywdord-tabel
  - Apparaten met een `device_class: power` en bekende naam → anker
  - Weersensoren met `device_class: temperature / irradiance` → context

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# ── Herkennings-tabellen ──────────────────────────────────────────────────────

# keyword → (device_type, confidence_boost)
# Termen worden vergeleken tegen entity_id en friendly_name (lowercase)
DEVICE_KEYWORDS: List[Tuple[str, str, float]] = [
    # Wasmachine
    ("washing_machine",   "washing_machine",  0.90),
    ("wasmachine",        "washing_machine",  0.95),
    ("washer",            "washing_machine",  0.88),

    # Droger
    ("dryer",             "dryer",            0.90),
    ("droger",            "dryer",            0.95),
    ("tumble",            "dryer",            0.85),

    # Vaatwasser
    ("dishwasher",        "dishwasher",       0.90),
    ("vaatwasser",        "dishwasher",       0.95),
    ("afwasmachine",      "dishwasher",       0.95),

    # Boiler / waterverwarmer
    ("boiler",            "boiler",           0.90),
    ("water_heater",      "boiler",           0.85),
    ("elektrische_boiler","boiler",           0.95),
    ("immersion",         "boiler",           0.80),
    ("thermex",           "boiler",           0.85),

    # Warmtepomp
    ("heat_pump",         "heat_pump",        0.90),
    ("warmtepomp",        "heat_pump",        0.95),
    ("heatpump",          "heat_pump",        0.90),
    ("mitsubishi",        "heat_pump",        0.75),
    ("daikin",            "heat_pump",        0.75),
    ("vaillant",          "heat_pump",        0.75),
    ("nibe",              "heat_pump",        0.75),
    ("viessmann",         "heat_pump",        0.75),

    # EV lader
    ("ev_charger",        "ev_charger",       0.95),
    ("ev_lader",          "ev_charger",       0.95),
    ("charger",           "ev_charger",       0.80),
    ("wallbox",           "ev_charger",       0.90),
    ("easee",             "ev_charger",       0.90),
    ("alfen",             "ev_charger",       0.90),
    ("zappi",             "ev_charger",       0.90),
    ("ocpp",              "ev_charger",       0.80),

    # Koelkast / vriezer
    ("refrigerator",      "refrigerator",     0.90),
    ("koelkast",          "refrigerator",     0.95),
    ("freezer",           "refrigerator",     0.85),
    ("vriezer",           "refrigerator",     0.95),
    ("fridge",            "refrigerator",     0.88),

    # Oven / inductie
    ("oven",              "oven",             0.88),
    ("induction",         "oven",             0.85),
    ("inductie",          "oven",             0.90),
    ("hob",               "oven",             0.80),
    ("cooker",            "oven",             0.80),

    # Magnetron
    ("microwave",         "microwave",        0.92),
    ("magnetron",         "microwave",        0.95),

    # Verlichting
    ("light",             "light",            0.70),
    ("lamp",              "light",            0.75),
    ("verlichting",       "light",            0.80),

    # Televisie / entertainment
    ("tv",                "entertainment",    0.80),
    ("television",        "entertainment",    0.85),
    ("televisie",         "entertainment",    0.90),

    # Computer
    ("computer",          "entertainment",    0.80),
    ("desktop",           "entertainment",    0.80),
    ("gaming",            "entertainment",    0.75),
    ("server",            "entertainment",    0.75),
    ("nas",               "entertainment",    0.80),

    # Airco
    ("airco",             "heat_pump",        0.85),
    ("air_conditioner",   "heat_pump",        0.85),
    ("ac_unit",           "heat_pump",        0.85),
    ("klimaat",           "heat_pump",        0.70),
]

# Weersensor herkenning
WEATHER_KEYWORDS = {
    "temperature":     ["temperature", "temp", "temperatuur", "outside_temp", "buitentemperatuur"],
    "irradiance":      ["irradiance", "solar_radiation", "ghi", "straling", "solaredge_radiation"],
    "humidity":        ["humidity", "vochtigheid", "humid"],
    "cloud_cover":     ["cloud", "bewolking", "cloudiness"],
}

# Bekende smart plug / power meter integraties (platform of entity_id prefix)
SMART_PLUG_PLATFORMS = {
    "shelly",
    "tasmota",
    "tplink_smartlife",
    "esphome",
    "zwave_js",
    "zha",
    "deconz",
    "zigbee2mqtt",
    "tuya",
    "sonoff",
    "wemo",
    "kasa",
    "emporia",
    "iotawatt",
    "sense",
}

# Unit-of-measurement die wijzen op vermogenssensoren
POWER_UNITS = {"W", "kW", "watt"}


# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class DiscoveredPlug:
    """Een ontdekte smart-plug of vermogenssensor."""
    entity_id:    str
    friendly_name: str
    device_type:  str          # NILM device_type
    confidence:   float        # match-betrouwbaarheid
    phase:        str = "L1"   # Fase nog onbekend bij ontdekking; verfijnd later
    area:         str = ""     # HA-ruimte indien beschikbaar
    platform:     str = ""     # integratieplatform


@dataclass
class DiscoveredWeather:
    """Een ontdekte weersensor."""
    entity_id:    str
    friendly_name: str
    sensor_type:  str          # temperature / irradiance / humidity / cloud_cover
    unit:         str = ""


@dataclass
class DiscoveryResult:
    """Resultaat van één discovery-ronde."""
    plugs:   List[DiscoveredPlug]   = field(default_factory=list)
    weather: List[DiscoveredWeather] = field(default_factory=list)
    ts:      float = field(default_factory=time.time)

    @property
    def plug_count(self) -> int:
        return len(self.plugs)

    @property
    def weather_count(self) -> int:
        return len(self.weather)


# ── Discovery-engine ─────────────────────────────────────────────────────────

class SmartSensorDiscovery:
    """
    Scant HA-states op vermogenssensoren en weersensoren.

    Gebruik:
        disc = SmartSensorDiscovery(hass)
        result = disc.run()
        # result.plugs  → lijst van DiscoveredPlug
        # result.weather → lijst van DiscoveredWeather
    """

    REFRESH_INTERVAL_S = 300   # herscanning elke 5 minuten

    def __init__(self, hass) -> None:
        self._hass = hass
        self._last_result: Optional[DiscoveryResult] = None
        self._last_run: float = 0.0

    # ── Publieke API ──────────────────────────────────────────────────────────

    def run(self, force: bool = False) -> DiscoveryResult:
        """
        Voer discovery uit. Resultaat gecached gedurende REFRESH_INTERVAL_S.
        Geeft altijd een DiscoveryResult terug (nooit None).
        """
        if not force and self._last_result and (time.time() - self._last_run) < self.REFRESH_INTERVAL_S:
            return self._last_result

        plugs:   List[DiscoveredPlug]    = []
        weather: List[DiscoveredWeather] = []

        try:
            states = self._hass.states.async_all()
        except Exception:
            states = []

        for state in states:
            try:
                entity_id = state.entity_id
                attrs     = state.attributes or {}

                # ── Weersensoren ───────────────────────────────────────────
                ws = self._classify_weather(entity_id, attrs)
                if ws:
                    weather.append(ws)
                    continue

                # ── Vermogenssensoren ──────────────────────────────────────
                if not self._is_power_sensor(entity_id, attrs):
                    continue

                plug = self._classify_plug(entity_id, attrs)
                if plug:
                    plugs.append(plug)

            except Exception as exc:
                _LOGGER.debug("Discovery fout voor %s: %s", getattr(state, "entity_id", "?"), exc)

        # Sorteren op betrouwbaarheid
        plugs.sort(key=lambda p: p.confidence, reverse=True)

        result = DiscoveryResult(plugs=plugs, weather=weather)
        self._last_result = result
        self._last_run    = time.time()

        _LOGGER.info(
            "CloudEMS HybridNILM discovery: %d vermogenssensoren, %d weersensoren gevonden",
            len(plugs), len(weather),
        )
        if plugs:
            for p in plugs[:10]:
                _LOGGER.debug("  → %s: %s (%.0f%%)", p.entity_id, p.device_type, p.confidence * 100)

        return result

    def get_weather_value(self, sensor_type: str) -> Optional[float]:
        """
        Lees de huidige waarde van de beste weersensor van het gevraagde type.
        Geeft None terug als geen sensor beschikbaar is.
        """
        if not self._last_result:
            return None
        candidates = [w for w in self._last_result.weather if w.sensor_type == sensor_type]
        if not candidates:
            return None
        # Neem de eerste (hoogste prioriteit na sortering)
        eid = candidates[0].entity_id
        state = self._hass.states.get(eid)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def get_plug_power(self, entity_id: str) -> Optional[float]:
        """Lees het actuele vermogen van een ontdekte plug-sensor (Watt)."""
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            val = float(state.state)
            uom = (state.attributes or {}).get("unit_of_measurement", "W")
            if uom == "kW":
                val *= 1000.0
            return val
        except (ValueError, TypeError):
            return None

    # ── Interne classificatie ─────────────────────────────────────────────────

    def _is_power_sensor(self, entity_id: str, attrs: dict) -> bool:
        """Is dit een sensor die vermogen meet?"""
        # Alleen sensor.* entiteiten
        if not entity_id.startswith("sensor."):
            return False

        uom = attrs.get("unit_of_measurement", "")
        dc  = attrs.get("device_class", "")

        # Directe match op eenheid of device_class
        if uom in POWER_UNITS or dc == "power":
            return True

        # kWh is energie, niet vermogen — overslaan
        if uom in ("kWh", "Wh", "MWh"):
            return False

        return False

    def _classify_plug(self, entity_id: str, attrs: dict) -> Optional[DiscoveredPlug]:
        """
        Probeer de sensor te koppelen aan een bekend apparaattype.
        Geeft None terug als geen match gevonden.
        """
        friendly = str(attrs.get("friendly_name", entity_id)).lower()
        eid_low  = entity_id.lower()
        search   = f"{eid_low} {friendly}"

        best_type = None
        best_conf = 0.0

        for keyword, device_type, conf in DEVICE_KEYWORDS:
            # Gebruik regex-woordgrens om bijv. "nas" niet te matchen in "dynasolar"
            pattern = r'(^|[_\s\-\.])' + re.escape(keyword) + r'($|[_\s\-\.\d])'
            if re.search(pattern, search):
                if conf > best_conf:
                    best_conf = conf
                    best_type = device_type

        if best_type is None:
            return None

        # Detecteer platform uit entity_id (bijv. "sensor.shelly_wasmachine_power")
        platform = ""
        for plat in SMART_PLUG_PLATFORMS:
            if plat in eid_low:
                platform = plat
                break

        # Ruimte / area
        area = str(attrs.get("area", "") or "")

        return DiscoveredPlug(
            entity_id    = entity_id,
            friendly_name= attrs.get("friendly_name", entity_id),
            device_type  = best_type,
            confidence   = best_conf,
            area         = area,
            platform     = platform,
        )

    def _classify_weather(self, entity_id: str, attrs: dict) -> Optional[DiscoveredWeather]:
        """Herken weersensoren."""
        if not entity_id.startswith("sensor."):
            return None

        dc  = attrs.get("device_class", "")
        uom = attrs.get("unit_of_measurement", "")
        friendly = str(attrs.get("friendly_name", entity_id)).lower()
        eid_low  = entity_id.lower()
        search   = f"{eid_low} {friendly}"

        # Temperatuursensor (buitentemperatuur prioriteit)
        if dc == "temperature" or uom in ("°C", "°F", "K"):
            # Prioriteer buitensensoren
            for kw in WEATHER_KEYWORDS["temperature"]:
                if kw in search:
                    return DiscoveredWeather(
                        entity_id    = entity_id,
                        friendly_name= attrs.get("friendly_name", entity_id),
                        sensor_type  = "temperature",
                        unit         = uom,
                    )

        # Zonnestraling / irradiantie
        if dc in ("irradiance",) or uom in ("W/m²", "W/m2", "lx", "lux"):
            for kw in WEATHER_KEYWORDS["irradiance"]:
                if kw in search:
                    return DiscoveredWeather(
                        entity_id    = entity_id,
                        friendly_name= attrs.get("friendly_name", entity_id),
                        sensor_type  = "irradiance",
                        unit         = uom,
                    )

        # Luchtvochtigheid
        if dc == "humidity" or uom == "%":
            for kw in WEATHER_KEYWORDS["humidity"]:
                if kw in search:
                    return DiscoveredWeather(
                        entity_id    = entity_id,
                        friendly_name= attrs.get("friendly_name", entity_id),
                        sensor_type  = "humidity",
                        unit         = uom,
                    )

        return None
