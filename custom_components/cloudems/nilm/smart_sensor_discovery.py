# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Smart Sensor Discovery — v1.2.0

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
# v1.20: socket-keywords op 1.0 — als naam/platform expliciet op smart plug wijst
# is er geen twijfel. Andere apparaten houden hun bestaande confidence-waarden.
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

    # Generieke stopcontacten / slimme stekkers — altijd 1.0 (v1.20)
    # Als naam of entity_id expliciet op stopcontact wijst, is het zeker een smart plug.
    ("socket",            "socket",           1.0),
    ("stopcontact",       "socket",           1.0),
    ("stekker",           "socket",           1.0),
    ("plug",              "socket",           1.0),
    ("outlet",            "socket",           1.0),
    ("wcd",               "socket",           1.0),   # Wandcontactdoos (NL)
    ("wandcontactdoos",   "socket",           1.0),
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
    phase:        str = "?"    # "?" = onbekend totdat DSMR5-correlatie bewijs levert
    area:         str = ""     # HA-ruimte indien beschikbaar
    platform:     str = ""     # integratieplatform
    # Nieuwe velden v4.5.86
    manufacturer: str = ""     # apparaatfabrikant (uit device registry)
    model:        str = ""     # apparaatmodel (uit device registry)
    device_name:  str = ""     # echte HA device naam (bijv. "Koelkast Keuken")
    source:       str = ""     # "powercalc" | "device_registry" | "keyword" | "platform" | "switch_sibling"
    source_entity_id: str = "" # powercalc: de originele source entity (bijv. "switch.koelkast")
    is_topology_meter: bool = False  # True als dit een submeter is, geen eindapparaat
    pending_identity: bool = False   # True als device_type=socket maar naam onbekend → review nodig


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
        self._excluded_entity_ids: set = set()  # explicit exclusions from CloudEMS config
        # v2.2.2: change-detection — set van entity_id's uit vorige scan
        self._prev_plug_eids: set = set()
        self._on_change_callback = None  # callback(added: set, removed: set) bij wijziging

    def set_on_change_callback(self, callback) -> None:
        """Registreer een callback die aangeroepen wordt als de plug-set wijzigt.
        callback(added: set[str], removed: set[str])
        """
        self._on_change_callback = callback

    def set_excluded_entity_ids(self, entity_ids: set) -> None:
        """Stel expliciete uitsluitingslijst in vanuit CloudEMS config (grid, solar, battery, P1, enz.)."""
        self._excluded_entity_ids = {eid for eid in entity_ids if eid}

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

        # v2.2.2: change-detection — vergelijk met vorige scan
        current_plug_eids = {p.entity_id for p in plugs}
        added   = current_plug_eids - self._prev_plug_eids
        removed = self._prev_plug_eids - current_plug_eids
        if (added or removed) and self._prev_plug_eids:  # geen callback op eerste scan
            if added:
                _LOGGER.info(
                    "CloudEMS discovery: %d nieuwe vermogenssensor(en): %s",
                    len(added), ", ".join(sorted(added)[:5]),
                )
            if removed:
                _LOGGER.info(
                    "CloudEMS discovery: %d verdwenen vermogenssensor(en): %s",
                    len(removed), ", ".join(sorted(removed)[:5]),
                )
            if self._on_change_callback:
                try:
                    self._on_change_callback(added, removed)
                except Exception as exc:
                    _LOGGER.debug("Discovery change callback fout: %s", exc)
        self._prev_plug_eids = current_plug_eids

        _LOGGER.info(
            "CloudEMS HybridNILM discovery: %d vermogenssensoren, %d weersensoren gevonden",
            len(plugs), len(weather),
        )
        if plugs:
            for p in plugs[:10]:
                _LOGGER.debug("  → %s: %s (%.0f%%)", p.entity_id, p.device_type, p.confidence * 100)

        # Samenvatting per bron voor nilm log (indien backup beschikbaar)
        _src_counts: dict = {}
        _pending_count = 0
        for p in plugs:
            _src_counts[p.source] = _src_counts.get(p.source, 0) + 1
            if p.pending_identity:
                _pending_count += 1
        _LOGGER.info(
            "[nilm_discovery] scan klaar: %d plugs (%s), %d pending review",
            len(plugs),
            ", ".join(f"{k}:{v}" for k, v in sorted(_src_counts.items())),
            _pending_count,
        )

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
    #
    # Categorieën:
    #   • Grid / P1 / DSMR   — net, grid, import, export, p1, dsmr, slimme_meter, gas
    #   • PV / omvormer       — solar, pv, zon, omvorm, inverter, string, opbrengst, yield
    #   • Thuisbatterij       — battery, batterij, accu, opslag, soc, bms, laad, ontlaad
    #   • Aggregaat/totaal    — totaal, total, mains, house_total, verbruik_totaal
    #   • CloudEMS intern     — cloudems, fase, phase, l1/l2/l3, afname, teruglevering
    _EXCLUDE_PATTERNS = re.compile(
        r'(^|[_\s\.])('
        # Grid / P1 / DSMR
        r'grid|net(?=_)|import|export|teruglevering|afname|mains|'
        r'p1(?=_|$)|dsmr|slimme_meter|gas_meter|stroom_meter|'
        # PV / omvormer
        r'solar|pv(?=_|\d|$)|zon(?=_)|omvorm|inverter|omvormer|'
        r'string(?=_|\d)|opbrengst|pv_power|solar_power|'
        # Thuisbatterij / accu
        r'battery(?=_|$)|batterij|accu(?=_|$)|opslag(?=_|$)|'
        r'thuisbatterij|bms(?=_|$)|soc(?=_|$)|'
        r'laadvermogen|ontlaadvermogen|'
        r'charge_power|discharge_power|'
        # Aggregaat / totaal
        r'totaal|total|house_total|verbruik_totaal|home_power|'
        r'house_consumption|woningverbruik|'
        # CloudEMS intern / metingen
        r'cloudems|fase|phase|l[123](?=_)'
        r')([_\s\.]|$)',
        re.IGNORECASE,
    )

    # v4.4: aanvullende uitsluitpatronen die NIET in bovenstaande word-boundary
    # regex passen omdat ze meerdere woorden of vrije substrings zijn.
    # Matcht op entity_id + friendly_name gecombineerd (lowercase).
    _EXCLUDE_SUBSTRINGS = (
        "energiemeter", "energy meter", "energy_meter",
        "uurprijs", "stroom_tegen", "stroom tegen",
        "connect energi", "connect_energi",
        "elektriciteitsgemiddelde", "elektriciteitsverbruik",
        "elektriciteitsproductie", "electriciteitsverbruik",
        "huidig verbruik", "huidig_verbruik",
        "net_power", "net power", "grid_power",
        "kwh_meter", "kwh meter",
        # v4.5.12: PV / zonne-productie sensors — nooit als verbruiker registreren
        "energieproductie", "energie productie",
        "geschatte energieproductie", "geschatte productie",
        "pv productie", "pv-productie", "pv_productie",
        "solar productie", "solar production",
        "estimated production", "geschatte opbrengst",
        "ac output", "dc output", "ac_output", "dc_input",
        "vermogen omvormer", "omvormer vermogen",
        "solar yield", "pv yield", "pv opbrengst",
    )

    def _classify_plug(self, entity_id: str, attrs: dict) -> Optional[DiscoveredPlug]:
        """
        Koppel een vermogenssensor aan een apparaattype.

        Prioriteitsketen (hoogste prioriteit eerst):
          1. Expliciete uitsluiting → None
          2. Powercalc path: parse source_entity + device registry voor echte naam/model
          3. Device registry: echte device naam voor keyword-match
          4. Keyword-match op entity_id + friendly_name + device naam
          5. Platform via entity registry → 'socket' als smart-plug platform
          6. Switch-sibling: schakelaar op zelfde device → 'socket'
          7. Attribuut-fallback: device_class=power + state_class=measurement

        Fase-toewijzing: altijd "?" bij ontdekking; verfijnd later via DSMR5-correlatie.
        Socket zonder naamherkenning → pending_identity=True voor review dashboard.
        """
        friendly = str(attrs.get("friendly_name", entity_id)).lower()
        eid_low  = entity_id.lower()
        search   = f"{eid_low} {friendly}"

        # ── Stap 1: uitsluitfilter ─────────────────────────────────────────
        if entity_id in self._excluded_entity_ids:
            return None
        if self._EXCLUDE_PATTERNS.search(search):
            return None
        if any(sub in search for sub in self._EXCLUDE_SUBSTRINGS):
            return None

        best_type   = None
        best_conf   = 0.0
        source      = ""
        device_name = ""
        manufacturer= ""
        model       = ""
        source_entity_id = ""
        area        = str(attrs.get("area", "") or "")

        # ── Stap 2: Powercalc path (hoogste prioriteit) ────────────────────
        # Powercalc sensoren zijn gekoppeld aan een echt HA device via de
        # device registry: device.name / manufacturer / model / area staan daar.
        pc_info = self._get_powercalc_info(entity_id)
        if pc_info:
            device_name      = pc_info.get("device_name", "")
            manufacturer     = pc_info.get("manufacturer", "")
            model_str        = pc_info.get("model", "")
            model            = model_str
            source_entity_id = pc_info.get("source_entity_id", "")
            area             = pc_info.get("area", area)
            # Keyword-match op echte device naam + fabrikant + model
            pc_search = f"{device_name} {manufacturer} {model_str} {eid_low} {friendly}".lower()
            for keyword, device_type, conf in DEVICE_KEYWORDS:
                pattern = r'(^|[_\s\-\.])' + re.escape(keyword) + r'($|[_\s\-\.\d])'
                if re.search(pattern, pc_search):
                    if conf > best_conf:
                        best_conf = conf
                        best_type = device_type
                        source    = "powercalc"
            if best_type is None:
                # Powercalc sensor maar geen keyword match → socket met hoge conf
                # (het is zeker een meting, maar type onbekend)
                best_type = "socket"
                best_conf = 0.70
                source    = "powercalc"
            _LOGGER.debug(
                "[nilm_discovery] powercalc: %s → type=%s conf=%.2f device='%s' model='%s'",
                entity_id, best_type, best_conf, device_name, model_str,
            )

        # ── Stap 3 + 4: Device registry + keyword match ────────────────────
        if best_type is None:
            dev_info = self._get_device_info(entity_id)
            if dev_info:
                device_name  = dev_info.get("device_name", "")
                manufacturer = dev_info.get("manufacturer", "")
                model        = dev_info.get("model", "")
                area         = dev_info.get("area", area)
                dev_search   = f"{device_name} {manufacturer} {model} {eid_low} {friendly}".lower()
                for keyword, device_type, conf in DEVICE_KEYWORDS:
                    pattern = r'(^|[_\s\-\.])' + re.escape(keyword) + r'($|[_\s\-\.\d])'
                    if re.search(pattern, dev_search):
                        if conf > best_conf:
                            best_conf = conf
                            best_type = device_type
                            source    = "device_registry"

        # ── Stap 4b: Keyword match op entity_id + friendly name alleen ─────
        if best_type is None:
            for keyword, device_type, conf in DEVICE_KEYWORDS:
                pattern = r'(^|[_\s\-\.])' + re.escape(keyword) + r'($|[_\s\-\.\d])'
                if re.search(pattern, search):
                    if conf > best_conf:
                        best_conf = conf
                        best_type = device_type
                        source    = "keyword"

        # ── Stap 5: Platform via entity registry ───────────────────────────
        platform = self._get_platform(entity_id)
        if best_type is None and platform in SMART_PLUG_PLATFORMS:
            best_type = "socket"
            best_conf = 0.85
            source    = "platform"
            _LOGGER.debug(
                "[nilm_discovery] platform match: %s → socket via platform '%s'",
                entity_id, platform,
            )

        # ── Stap 6: Device registry — platform + switch-sibling ───────────
        if best_type is None:
            plat, has_switch = self._check_device_registry(entity_id)
            if plat:
                platform = plat
            if has_switch:
                best_type = "socket"
                best_conf = 0.90
                source    = "switch_sibling"
            elif plat in SMART_PLUG_PLATFORMS:
                best_type = "socket"
                best_conf = 0.85
                source    = "platform"

        # ── Stap 7: Attribuut-fallback ─────────────────────────────────────
        if best_type is None:
            dc = attrs.get("device_class", "")
            sc = attrs.get("state_class", "")
            if dc == "power" and sc == "measurement":
                if re.search(r'(^|[_\s\.])(vermogen|power|watt|energie|verbruik|meting|usage)([_\s\.]|$)',
                              search, re.IGNORECASE):
                    best_type = "socket"
                    best_conf = 0.50
                    source    = "attr_fallback"
                else:
                    best_type = "socket"
                    best_conf = 0.40
                    source    = "attr_fallback"

        if best_type is None:
            return None

        # Gebruik echte device naam als friendly_name als die beschikbaar is
        display_name = device_name if device_name else attrs.get("friendly_name", entity_id)

        # Socket zonder duidelijke identiteit → review nodig op dashboard
        pending = (best_type == "socket" and source not in ("powercalc", "keyword", "device_registry")
                   and not device_name)

        _LOGGER.debug(
            "[nilm_discovery] %s → type=%s conf=%.2f bron=%s area=%s pending=%s",
            entity_id, best_type, best_conf, source, area or "?", pending,
        )

        return DiscoveredPlug(
            entity_id        = entity_id,
            friendly_name    = display_name,
            device_type      = best_type,
            confidence       = best_conf,
            phase            = "?",   # altijd onbekend bij ontdekking
            area             = area,
            platform         = platform or "",
            manufacturer     = manufacturer,
            model            = model,
            device_name      = device_name,
            source           = source,
            source_entity_id = source_entity_id,
            pending_identity = pending,
        )

    def _get_powercalc_info(self, entity_id: str) -> Optional[dict]:
        """
        Controleer of dit een powercalc sensor is en lees device informatie uit.

        Powercalc koppelt zijn sensor aan het echte HA device via de device registry.
        Zo staat de echte naam (bijv. "Koelkast Keuken"), fabrikant en model al klaar.

        Geeft dict terug met: device_name, manufacturer, model, area, source_entity_id
        of None als dit geen powercalc sensor is.
        """
        try:
            entity_reg = er.async_get(self._hass)
            entry = entity_reg.async_get(entity_id)
            if not entry:
                return None
            # Controleer of platform powercalc is
            if not entry.platform or "powercalc" not in entry.platform.lower():
                return None

            result: dict = {"source_entity_id": ""}

            # Parse source entity uit powercalc unique_id (formaat: "powercalc_xxx_<source_entity>")
            if entry.unique_id:
                # Powercalc unique_ids bevatten vaak de source entity_id
                uid = entry.unique_id
                for prefix in ("powercalc_", "pc_"):
                    if uid.startswith(prefix):
                        candidate = uid[len(prefix):]
                        if "." in candidate:
                            result["source_entity_id"] = candidate
                            break

            # Device registry voor echte naam/fabrikant/model/area
            if entry.device_id:
                from homeassistant.helpers import device_registry as dr
                dev_reg = dr.async_get(self._hass)
                device  = dev_reg.async_get(entry.device_id)
                if device:
                    result["device_name"]  = device.name_by_user or device.name or ""
                    result["manufacturer"] = device.manufacturer or ""
                    result["model"]        = device.model or ""
                    # Area via device of entity
                    area_id = device.area_id or entry.area_id
                    if area_id:
                        from homeassistant.helpers import area_registry as ar
                        area_reg = ar.async_get(self._hass)
                        area_entry = area_reg.async_get_area(area_id)
                        result["area"] = area_entry.name if area_entry else ""
                    else:
                        result["area"] = ""

            return result if result.get("device_name") or result.get("source_entity_id") else None

        except Exception as exc:
            _LOGGER.debug("Powercalc info fout voor %s: %s", entity_id, exc)
            return None

    def _get_device_info(self, entity_id: str) -> Optional[dict]:
        """
        Lees device naam, fabrikant, model en area uit de HA device registry.

        Geeft dict terug met: device_name, manufacturer, model, area
        of None als geen device gevonden.
        """
        try:
            from homeassistant.helpers import device_registry as dr, area_registry as ar
            entity_reg = er.async_get(self._hass)
            entry = entity_reg.async_get(entity_id)
            if not entry or not entry.device_id:
                return None

            dev_reg = dr.async_get(self._hass)
            device  = dev_reg.async_get(entry.device_id)
            if not device:
                return None

            area_name = ""
            area_id   = device.area_id or entry.area_id
            if area_id:
                area_reg   = ar.async_get(self._hass)
                area_entry = area_reg.async_get_area(area_id)
                area_name  = area_entry.name if area_entry else ""

            return {
                "device_name":  device.name_by_user or device.name or "",
                "manufacturer": device.manufacturer or "",
                "model":        device.model or "",
                "area":         area_name,
            }
        except Exception as exc:
            _LOGGER.debug("Device info fout voor %s: %s", entity_id, exc)
            return None

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
