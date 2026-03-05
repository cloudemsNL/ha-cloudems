"""
CloudEMS Smart Sensor Discovery — v1.1.0

Scant automatisch alle Home Assistant entiteiten en herkent:
  1. Smart plug vermogenssensoren  → NILM-ankers (bekend apparaat, bekende fase)
  2. Weersensoren                  → temperatuur, zonnestraling voor contextpriors
  3. Apparaatnamen in entiteit-ID  → koppel aan NILM device_type
  4. Generieke stekkers (fallback) → platform-match zonder naamkeyword → device_type "socket"

Wijzigingen v1.1.0:
  - Alle vermogenssensoren van bekende smart-plug platforms worden gevonden,
    ook als ze geen apparaatspecifieke naam hebben (bijv. sensor.shelly_pm_1_power).
    Deze worden als device_type "socket" aangemeld.
  - Hiermee worden ALLE stopcontacten met energiemeting zichtbaar als NILM-anker,
    niet alleen degenen met een herkenbare apparaatnaam.

Geen configuratie nodig: de discovery draait bij opstart en elke 5 minuten.
Nieuwe sensoren worden automatisch opgepikt zodra ze in HA verschijnen.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from homeassistant.helpers import entity_registry as er

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
    ("quooker",           "boiler",           0.88),   # Quooker kokendwaterkraan
    ("bosch_therm",       "boiler",           0.80),
    ("cv_ketel",          "boiler",           0.90),
    ("geiser",            "boiler",           0.88),

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

    # Generieke stopcontacten / onbekend apparaat
    ("socket",            "socket",           0.65),
    ("stopcontact",       "socket",           0.70),
    ("stekker",           "socket",           0.70),
    ("plug",              "socket",           0.60),
    ("outlet",            "socket",           0.60),
    ("wcd",               "socket",           0.80),   # Wandcontactdoos (NL)
    ("wandcontactdoos",   "socket",           0.90),
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

    def _get_platform(self, entity_id: str) -> str:
        """
        Zoek het integratie-platform van een entity via de HA entity registry.
        Geeft de platform-string terug (bijv. 'shelly', 'zha') of '' als onbekend.
        Dit is de correcte methode: entity_id's bevatten de platformnaam niet altijd.
        """
        try:
            entity_reg = er.async_get(self._hass)
            entry = entity_reg.async_get(entity_id)
            if entry and entry.platform:
                return entry.platform.lower()
        except Exception:
            pass
        # Fallback: doorzoek entity_id-string als registry niet beschikbaar is
        eid_low = entity_id.lower()
        for plat in SMART_PLUG_PLATFORMS:
            if plat in eid_low:
                return plat
        return ""

    # Patronen die bij een bekende vermogenssensor horen die GEEN stopcontact is.
    # Gebruikt scheidingstekens i.p.v. \b zodat 'solar_power' ook gematcht wordt.
    _EXCLUDE_PATTERNS = re.compile(
        r'(^|[_\s\.])('
        r'grid|solar|pv|fase|phase|net(?=_)|l[123](?=_)|totaal|total|'
        r'cloudems|import|export|teruglevering|afname|mains|house_total|'
        r'verbruik_totaal|zon(?=_)|omvorm'
        r')([_\s\.]|$)',
        re.IGNORECASE,
    )

    def _classify_plug(self, entity_id: str, attrs: dict) -> Optional[DiscoveredPlug]:
        """
        Koppel een vermogenssensor aan een apparaattype.

        Beslisboom:
          1. Expliciete uitsluiting: bekende niet-stekker patronen → None
          2. Keyword-match op entity_id + friendly_name → specifiek type
          3. Platform via entity registry → 'socket' als het een smartplug-platform is
          4. Platform via device registry (config_entry domain) → 'socket'
          5. Switch-sibling: als hetzelfde HA-device ook een switch-entiteit heeft
             is het vrijwel zeker een smart plug → 'socket' met conf 0.80
          6. Attribuut-fallback: device_class=power + state_class=measurement
             + 'vermogen'/'power'/'watt' in naam → 'socket' conf 0.42
          7. Geen match → None
        """
        friendly = str(attrs.get("friendly_name", entity_id)).lower()
        eid_low  = entity_id.lower()
        search   = f"{eid_low} {friendly}"

        # ── Stap 1: uitsluitfilter ─────────────────────────────────────────
        if self._EXCLUDE_PATTERNS.search(search):
            return None

        best_type = None
        best_conf = 0.0

        # ── Stap 2: keyword-match ──────────────────────────────────────────
        for keyword, device_type, conf in DEVICE_KEYWORDS:
            pattern = r'(^|[_\s\-\.])' + re.escape(keyword) + r'($|[_\s\-\.\d])'
            if re.search(pattern, search):
                if conf > best_conf:
                    best_conf = conf
                    best_type = device_type

        # ── Stap 3: platform via entity registry ───────────────────────────
        platform = self._get_platform(entity_id)
        if best_type is None and platform in SMART_PLUG_PLATFORMS:
            best_type = "socket"
            best_conf = 0.60

        # ── Stap 4 + 5: device registry ────────────────────────────────────
        if best_type is None:
            plat, has_switch = self._check_device_registry(entity_id)
            if plat:
                platform = plat
            if has_switch:
                # Switch-sibling = vrijwel zeker smart plug (aan/uit + vermogen)
                best_type = "socket"
                best_conf = 0.82
            elif plat in SMART_PLUG_PLATFORMS:
                best_type = "socket"
                best_conf = 0.58

        # ── Stap 6: attribuut-fallback ─────────────────────────────────────
        # v1.17.3: elke sensor met device_class=power + state_class=measurement
        # die niet is uitgesloten, wordt als meetapparaat opgenomen.
        if best_type is None:
            dc = attrs.get("device_class", "")
            sc = attrs.get("state_class", "")
            if dc == "power" and sc == "measurement":
                # Naam-hint geeft iets hogere conf
                if re.search(r'(^|[_\s\.])(vermogen|power|watt|energie|verbruik|meting|usage)([_\s\.]|$)',
                              search, re.IGNORECASE):
                    best_type = "socket"
                    best_conf = 0.50
                else:
                    # Geen naam-hint maar wél juiste device_class/state_class
                    best_type = "socket"
                    best_conf = 0.40

        if best_type is None:
            return None

        area = str(attrs.get("area", "") or "")

        return DiscoveredPlug(
            entity_id    = entity_id,
            friendly_name= attrs.get("friendly_name", entity_id),
            device_type  = best_type,
            confidence   = best_conf,
            area         = area,
            platform     = platform or "",
        )

    def _check_device_registry(self, entity_id: str) -> tuple:
        """
        Controleer het HA-device via de device registry.

        Geeft terug: (platform_str, has_switch_sibling)
          - platform_str: integratie-domein als het in SMART_PLUG_PLATFORMS zit, anders ''
          - has_switch_sibling: True als het device ook een switch.* entiteit heeft
            (sterke indicator voor smart plug: schakelaar + vermogensmeting)
        """
        platform   = ""
        has_switch = False
        try:
            from homeassistant.helpers import device_registry as dr
            entity_reg = er.async_get(self._hass)
            entry = entity_reg.async_get(entity_id)
            if not entry or not entry.device_id:
                return platform, has_switch

            dev_reg = dr.async_get(self._hass)
            device  = dev_reg.async_get(entry.device_id)
            if not device:
                return platform, has_switch

            # Platform via config_entries
            for config_entry_id in device.config_entries:
                ce = self._hass.config_entries.async_get_entry(config_entry_id)
                if ce and ce.domain.lower() in SMART_PLUG_PLATFORMS:
                    platform = ce.domain.lower()
                    break

            # Fabrikant/model fallback als config_entry geen hit gaf
            if not platform:
                mfr   = (device.manufacturer or "").lower()
                model = (device.model or "").lower()
                known = {
                    "shelly": "shelly", "sonoff": "sonoff", "tuya": "tuya",
                    "ikea": "zha", "xiaomi": "zha", "philips": "zha",
                    "tp-link": "tplink_smartlife", "kasa": "tplink_smartlife",
                    "aqara": "zha", "zemismart": "zha", "nous": "tasmota",
                    "blitzwolf": "tasmota", "athom": "tasmota",
                    "frient": "zha", "innr": "zha", "osram": "zha",
                    "legrand": "zha", "schneider": "zha", "niko": "zha",
                }
                for brand, plat in known.items():
                    if brand in mfr or brand in model:
                        platform = plat
                        break

            # Switch-sibling: zoek switch.* entiteiten op hetzelfde device
            siblings = entity_reg.entities.get_entries_for_device_id(device.id)
            has_switch = any(
                s.entity_id.startswith("switch.") for s in siblings
                if s.entity_id != entity_id
            )

        except Exception as exc:
            _LOGGER.debug("Device registry check fout voor %s: %s", entity_id, exc)

        return platform, has_switch

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
