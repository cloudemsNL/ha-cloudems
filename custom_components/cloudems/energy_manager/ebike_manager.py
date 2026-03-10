# -*- coding: utf-8 -*-
"""CloudEMS — E-bike Manager (v2.6).

Multi-merk e-bike integratie via adapter-patroon.

ARCHITECTUUR
════════════
Eén unified datamodel (EBikeData) ongeacht merk.
Elke brand-adapter leest HA-entities en vult het model.

    EBikeManager
    ├── adapter_factory()   auto-detect per HA device
    ├── BoschAdapter        hass-bosch-ebike (HACS)
    ├── SpecializedAdapter  ha-specialized-turbo (Bluetooth, HACS)
    ├── YamahaAdapter       YEC-app of MQTT-bridge
    ├── SmartphixAdapter    Smartphix NL (cloud + MQTT)
    └── GenericAdapter      losse sensors zelf koppelen (vangnet)

EBikeData: unified velden
    soc_pct / range_km / is_charging / is_connected
    health_pct / charge_cycles / battery_wh
    motor_w / speed_kmh / odometer_km / temp_c
    → zelfde dashboard ongeacht merk

SLIM LADEN (gedeelde logica, merk-onafhankelijk)
    1. Solar-overschot > drempel  → direct laden (gratis + max ERE)
    2. EPEX < drempel             → laden in goedkoop uur
    3. Temperatuur buiten bereik  → niet laden
    4. SOC ≥ dagelijkse max       → vol, niets doen

ACCU-DEGRADATIE MODEL
    Bosch:       70% capaciteit na 500 volledige laadcycli
    Specialized: sensor levert health_pct direct
    Yamaha:      70% na 1000 cycli (betere cellen)
    Generiek:    70% na 500 cycli (veilige default)

AUTO-DISCOVERY VOLGORDE
    1. Platform-naam check (bosch_ebike, ha_specialized_turbo, ...)
    2. Device-naam keywords
    3. Entity-ID patronen
    4. Fallback: GenericAdapter als er iets van "bike/soc/range" gevonden wordt

NIEUWE MERKEN TOEVOEGEN
    Maak een subklasse van BrandAdapter, definieer:
      PLATFORM_NAMES: set[str]
      NAME_KEYWORDS:  set[str]
      ENTITY_MAP: dict  (logische naam → entity-id suffix/pattern)
    Registreer in ADAPTERS lijst onderaan dit bestand.

Copyright 2025 CloudEMS
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── Unified data model ────────────────────────────────────────────────────────

@dataclass
class EBikeData:
    """Genormaliseerd e-bike datapunt — merk-onafhankelijk."""
    # Identiteit
    name:        str
    brand:       str        # "bosch" | "specialized" | "yamaha" | "smartphix" | "generic"
    device_id:   str

    # Accu
    soc_pct:         Optional[float] = None
    range_km:        Optional[float] = None
    battery_wh:      int             = 500
    health_pct:      Optional[float] = None
    charge_cycles:   Optional[int]   = None
    temp_c:          Optional[float] = None
    voltage_v:       Optional[float] = None

    # Staat
    is_charging:     bool = False
    is_connected:    bool = False
    remaining_wh:    Optional[float] = None   # Bosch eBike Connect: battery_remaining_energy
    lifetime_energy_kwh: Optional[float] = None  # Bosch eBike Connect: lifetime_energy_delivered

    # Rijden
    motor_w:         Optional[float] = None
    speed_kmh:       Optional[float] = None
    odometer_km:     Optional[float] = None
    cadence_rpm:     Optional[float] = None
    rider_power_w:   Optional[float] = None

    # CloudEMS laad-intelligentie (ingevuld door manager)
    charge_advice:   str  = "onbekend"    # solar|nu_laden|wachten|vol|niet_aanbevolen
    charge_reason:   str  = ""
    target_soc:      float = 80.0
    minutes_to_full: Optional[float] = None

    # Berekend
    def estimated_health_pct(self) -> float:
        if self.health_pct is not None:
            return self.health_pct
        cycles = self.charge_cycles or 0
        if cycles <= 0:
            return 100.0
        eol = self._brand_eol_cycles()
        degradation = (1.0 - 70.0 / 100) * min(1.0, cycles / eol)
        return max(70.0, round((1.0 - degradation) * 100, 1))

    def _brand_eol_cycles(self) -> int:
        return {"yamaha": 1000, "specialized": 800}.get(self.brand, 500)

    def effective_capacity_wh(self) -> float:
        return self.battery_wh * (self.estimated_health_pct() / 100)

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "brand":          self.brand,
            "soc_pct":        round(self.soc_pct, 0)    if self.soc_pct    is not None else None,
            "range_km":       round(self.range_km, 0)   if self.range_km   is not None else None,
            "battery_wh":     self.battery_wh,
            "health_pct":     round(self.estimated_health_pct(), 1),
            "charge_cycles":  self.charge_cycles,
            "temp_c":         self.temp_c,
            "is_charging":    self.is_charging,
            "is_connected":   self.is_connected,
            "motor_w":        self.motor_w,
            "speed_kmh":      self.speed_kmh,
            "odometer_km":    round(self.odometer_km, 0) if self.odometer_km is not None else None,
            "charge_advice":  self.charge_advice,
            "charge_reason":  self.charge_reason,
            "target_soc":     self.target_soc,
            "minutes_to_full":self.minutes_to_full,
        }


# ── Base adapter ──────────────────────────────────────────────────────────────

class BrandAdapter(ABC):
    """Abstracte basis voor alle merk-adapters.

    Elke adapter weet:
      - Welke HA-platforms/namen bij dit merk horen  (voor discovery)
      - Hoe hij de ruwe HA-entities leest en naar EBikeData mapt
    """

    # Override in subklasse
    PLATFORM_NAMES: set[str] = set()
    NAME_KEYWORDS:  set[str] = set()
    BRAND_NAME:     str      = "generic"
    DEFAULT_WH:     int      = 500

    def __init__(self, hass: "HomeAssistant", bike_cfg: dict) -> None:
        self._hass    = hass
        self._cfg     = bike_cfg   # device_id, name, entities dict
        self._did     = bike_cfg["device_id"]
        self._name    = bike_cfg["name"]
        self._ents    = bike_cfg.get("entities", {})

    @classmethod
    def matches_platform(cls, platform: str) -> bool:
        return any(p in platform.lower() for p in cls.PLATFORM_NAMES)

    @classmethod
    def matches_name(cls, name: str) -> bool:
        n = name.lower().replace("-", "_").replace(" ", "_")
        return any(kw in n for kw in cls.NAME_KEYWORDS)

    def _read_float(self, key: str) -> Optional[float]:
        eid = self._ents.get(key)
        if not eid:
            return None
        st = self._hass.states.get(eid)
        if not st or st.state in ("unavailable", "unknown", "none", ""):
            return None
        try:
            return float(st.state)
        except (ValueError, TypeError):
            return None

    def _read_bool(self, key: str) -> bool:
        eid = self._ents.get(key)
        if not eid:
            return False
        st = self._hass.states.get(eid)
        return bool(st and st.state in ("on", "true", "charging", "1", "yes"))

    def read(self) -> EBikeData:
        """Lees alle entities en geef uniform EBikeData terug."""
        d = EBikeData(
            name=self._name,
            brand=self.BRAND_NAME,
            device_id=self._did,
            battery_wh=int(self._cfg.get("battery_wh", self.DEFAULT_WH)),
        )
        self._fill(d)
        return d

    @abstractmethod
    def _fill(self, d: EBikeData) -> None:
        """Vul EBikeData in vanuit brand-specifieke entities."""


# ── Bosch adapter ─────────────────────────────────────────────────────────────

class BoschAdapter(BrandAdapter):
    """Leest van hass-bosch-ebike (HACS).

    Entiteiten (auto-gecategoriseerd door factory):
      battery_level, battery_health, range, motor_power,
      total_distance, charge_cycles, temperature, charging, connected
    """
    PLATFORM_NAMES = {"bosch_ebike", "hass_bosch_ebike", "bosch_smart_ebike",
                       "bosch_ebike_connect", "bosch_ebike_flow", "bosch_flow",
                       "bosch_ebike_connect_cloud"}
    NAME_KEYWORDS  = {"bosch", "powertube", "powerpack", "kiox",
                      "intuvia", "nyon", "purion", "boschebike",
                      # Bosch motor-namen (device = fietsmerk + motor naam)
                      "drive_unit", "performance_line", "active_line",
                      "cargo_line", "smart_system", "cx", "speed_motor"}
    BRAND_NAME     = "bosch"
    DEFAULT_WH     = 500

    def _fill(self, d: EBikeData) -> None:
        d.soc_pct        = self._read_float("battery_level")
        d.health_pct     = self._read_float("battery_health")
        # Bosch eBike Flow: "reachable_range"; hass-bosch-ebike: "range"
        d.range_km       = self._read_float("range")
        d.motor_w        = self._read_float("motor_power")
        d.odometer_km    = self._read_float("total_distance")
        d.charge_cycles  = _to_int(self._read_float("charge_cycles"))
        d.temp_c         = self._read_float("temperature")
        # Bosch eBike Flow: "charging" = binary_sensor charger_connected
        d.is_charging    = self._read_bool("charging")
        d.is_connected   = self._read_bool("connected")
        # Bosch eBike Connect: "battery_capacity" geeft Wh capaciteit
        cap = self._read_float("capacity_wh")
        if cap and cap > 0:
            d.battery_wh = int(cap)
        # Bosch eBike Connect: "battery_remaining_energy" in Wh
        rem = self._read_float("remaining_wh")
        if rem is not None:
            d.remaining_wh = rem
        # Bosch eBike Connect: lifetime_energy_delivered in kWh
        life_kwh = self._read_float("lifetime_energy")
        if life_kwh and life_kwh > 0:
            d.lifetime_energy_kwh = life_kwh
            # Als total_distance ontbreekt: schat odometer op ~25Wh/km
            if d.odometer_km is None:
                d.odometer_km = round(life_kwh * 1000 / 25, 1)


# ── Specialized adapter ───────────────────────────────────────────────────────

class SpecializedAdapter(BrandAdapter):
    """Leest van ha-specialized-turbo (Bluetooth BLE, HACS).

    Bron: github.com/JamieMagee/ha-specialized-turbo
    Entiteiten: charge_pct, capacity_wh, remaining_wh, health_pct,
                temperature, voltage, current, charge_cycles,
                speed, rider_power, motor_power, cadence, odometer, motor_temp
    """
    PLATFORM_NAMES = {"ha_specialized_turbo", "specialized_turbo",
                      "specialized", "turbo_ebike"}
    NAME_KEYWORDS  = {"specialized", "turbo", "levo", "creo", "tero",
                      "vado", "como", "tcu_"}
    BRAND_NAME     = "specialized"
    DEFAULT_WH     = 700

    def _fill(self, d: EBikeData) -> None:
        d.soc_pct        = self._read_float("charge_pct")      or self._read_float("battery_level")
        d.health_pct     = self._read_float("health_pct")      or self._read_float("battery_health")
        d.range_km       = self._read_float("range")
        d.motor_w        = self._read_float("motor_power")
        d.odometer_km    = self._read_float("odometer")        or self._read_float("total_distance")
        d.charge_cycles  = _to_int(self._read_float("charge_cycles"))
        d.temp_c         = self._read_float("temperature")     or self._read_float("motor_temp")
        d.voltage_v      = self._read_float("voltage")
        d.speed_kmh      = self._read_float("speed")
        d.cadence_rpm    = self._read_float("cadence")
        d.rider_power_w  = self._read_float("rider_power")
        d.is_charging    = self._read_bool("charging")
        d.is_connected   = self._read_bool("connected")

        # Specialized levert remaining_wh + capacity_wh → bereken SOC
        if d.soc_pct is None:
            cap  = self._read_float("capacity_wh")
            rem  = self._read_float("remaining_wh")
            if cap and rem and cap > 0:
                d.soc_pct    = round(rem / cap * 100, 1)
                d.battery_wh = int(cap)


# ── Yamaha adapter ────────────────────────────────────────────────────────────

class YamahaAdapter(BrandAdapter):
    """Leest van Yamaha YEC-app bridge of MQTT.

    Yamaha heeft geen officële HA-integratie. Twee routes:
      A) MQTT bridge (custom ESPHome of Node-RED)
         → entities: mqtt_soc, mqtt_range, mqtt_battery_temp
      B) Generieke REST-sensor op de YEC-API
         → dezelfde entity-namen als GenericAdapter

    Platform detectie via naam-keywords (geen vaste platform-naam).
    """
    PLATFORM_NAMES = {"yamaha_ebike", "yec_ebike", "yamaha_yec"}
    NAME_KEYWORDS  = {"yamaha", "yec", "pw_series", "pwseries", "pw_st",
                      "pw_ce", "pw_x", "crosscore"}
    BRAND_NAME     = "yamaha"
    DEFAULT_WH     = 500
    # Yamaha-specifieke EOL: 70% na 1000 cycli (kwalitatief betere cellen)

    def _fill(self, d: EBikeData) -> None:
        # Yamaha-specifiek of generiek — probeer beide
        d.soc_pct       = (self._read_float("battery_level")
                           or self._read_float("soc")
                           or self._read_float("charge"))
        d.range_km      = (self._read_float("range")
                           or self._read_float("remaining_range"))
        d.motor_w       = self._read_float("motor_power")
        d.odometer_km   = (self._read_float("total_distance")
                           or self._read_float("odometer"))
        d.charge_cycles = _to_int(self._read_float("charge_cycles"))
        d.temp_c        = self._read_float("temperature")
        d.speed_kmh     = self._read_float("speed")
        d.is_charging   = self._read_bool("charging")
        d.is_connected  = self._read_bool("connected")


# ── Smartphix adapter ─────────────────────────────────────────────────────────

class SmartphixAdapter(BrandAdapter):
    """Leest van Smartphix NL (populair Nederlands merk).

    Smartphix gebruikt een eigen cloud-app. Twee routes naar HA:
      A) Smartphix MQTT-bridge (community-project)
      B) RESTful sensor op de Smartphix API
      C) Als Smartphix officieel een HA-integratie uitbrengt → platform-naam

    Entity-namen volgen Smartphix MQTT-topic structuur:
      smartphix/{device_id}/battery/soc     → sensor.*_soc
      smartphix/{device_id}/battery/range   → sensor.*_range
      smartphix/{device_id}/battery/temp    → sensor.*_temperature
      smartphix/{device_id}/charging        → binary_sensor.*_charging
    """
    PLATFORM_NAMES = {"smartphix", "smartphix_ebike", "smartphix_mqtt"}
    NAME_KEYWORDS  = {"smartphix", "smphx"}
    BRAND_NAME     = "smartphix"
    DEFAULT_WH     = 500

    def _fill(self, d: EBikeData) -> None:
        # Probeer Smartphix-specifieke suffixen, dan generiek
        d.soc_pct      = (self._read_float("soc")
                          or self._read_float("battery_level")
                          or self._read_float("charge"))
        d.range_km     = self._read_float("range") or self._read_float("remaining_range")
        d.temp_c       = self._read_float("temperature")
        d.motor_w      = self._read_float("motor_power")
        d.odometer_km  = self._read_float("odometer") or self._read_float("total_distance")
        d.is_charging  = self._read_bool("charging")
        d.is_connected = self._read_bool("connected")


# ── Generic adapter ───────────────────────────────────────────────────────────

class GenericAdapter(BrandAdapter):
    """Vangnet voor elk merk via handmatig geconfigureerde sensor-entiteiten.

    Gebruiker configureert in CloudEMS:
      ebikes:
        - name: "Mijn Trek"
          brand: generic
          battery_wh: 500
          entities:
            soc:          sensor.trek_soc
            range:        sensor.trek_range_km
            charging:     binary_sensor.trek_charging
            health_pct:   sensor.trek_battery_health    # optioneel
            charge_cycles:sensor.trek_charge_cycles     # optioneel
            temperature:  sensor.trek_battery_temp      # optioneel
            odometer:     sensor.trek_total_km          # optioneel
            motor_power:  sensor.trek_motor_w           # optioneel

    Werkt met ELKE sensor in HA — MQTT, REST, Modbus, ESPHome, etc.
    """
    PLATFORM_NAMES = set()   # geen auto-discovery — altijd expliciet config
    NAME_KEYWORDS  = set()
    BRAND_NAME     = "generic"
    DEFAULT_WH     = 500

    def _fill(self, d: EBikeData) -> None:
        # Alle mogelijke namen proberen (generiek + aliassen)
        d.soc_pct      = (self._read_float("soc")
                          or self._read_float("battery_level")
                          or self._read_float("battery")
                          or self._read_float("charge"))
        d.range_km     = (self._read_float("range")
                          or self._read_float("remaining_range")
                          or self._read_float("range_km"))
        d.health_pct   = (self._read_float("health_pct")
                          or self._read_float("battery_health")
                          or self._read_float("health"))
        d.charge_cycles= _to_int(
                          self._read_float("charge_cycles")
                          or self._read_float("cycles"))
        d.temp_c       = (self._read_float("temperature")
                          or self._read_float("temp")
                          or self._read_float("battery_temp"))
        d.motor_w      = (self._read_float("motor_power")
                          or self._read_float("motor_w")
                          or self._read_float("motor"))
        d.speed_kmh    = self._read_float("speed") or self._read_float("speed_kmh")
        d.odometer_km  = (self._read_float("odometer")
                          or self._read_float("total_distance")
                          or self._read_float("total_km"))
        d.voltage_v    = self._read_float("voltage")
        d.is_charging  = (self._read_bool("charging")
                          or self._read_bool("is_charging"))
        d.is_connected = (self._read_bool("connected")
                          or self._read_bool("is_connected"))


# ── Adapter registry ──────────────────────────────────────────────────────────
# Volgorde bepaalt prioriteit bij auto-detection

ADAPTERS: list[type[BrandAdapter]] = [
    BoschAdapter,
    SpecializedAdapter,
    YamahaAdapter,
    SmartphixAdapter,
    # GenericAdapter is de fallback — nooit in auto-discovery
]


def _adapter_for(platform: str, name: str) -> type[BrandAdapter]:
    """Kies de juiste adapter op basis van platform-naam en device-naam."""
    for cls in ADAPTERS:
        if cls.matches_platform(platform) or cls.matches_name(name):
            return cls
    return GenericAdapter


# ── Auto-discovery ────────────────────────────────────────────────────────────

# Entity-categorisatie: keyword in entity_id → logische naam
ENTITY_CATEGORIES: list[tuple[set[str], str]] = [
    ({"battery_level", "soc", "charge_pct", "battery_charge"},           "battery_level"),
    ({"battery_health", "health_pct", "health"},                          "battery_health"),
    # Bosch eBike Connect: "reachable_range"; hass-bosch-ebike: "range"
    ({"reachable_range", "remaining_range", "range_km", "range"},         "range"),
    ({"motor_power", "motor_w"},                                          "motor_power"),
    # Bosch eBike Connect: "total_distance"; odometer fallback
    ({"total_distance", "odometer_km", "odometer"},                       "total_distance"),
    # Bosch eBike Connect: "lifetime_energy_delivered" → extra odometer proxy
    ({"lifetime_energy_delivered", "lifetime_energy", "energy_delivered"}, "lifetime_energy"),
    ({"charge_cycles", "charge_cycle", "cycles"},                         "charge_cycles"),
    ({"temperature", "temp_c", "battery_temp", "motor_temp"},             "temperature"),
    ({"voltage"},                                                         "voltage"),
    # Bosch eBike Connect: "battery_capacity" (Wh); anderen: "capacity_wh"
    ({"battery_capacity", "capacity_wh", "capacity_kwh"},                 "capacity_wh"),
    ({"battery_remaining_energy", "remaining_energy", "remaining_wh"},    "remaining_wh"),
    ({"rider_power"},                                                     "rider_power"),
    ({"cadence"},                                                         "cadence"),
    ({"speed"},                                                           "speed"),
    # Bosch eBike Connect: "charger_connected" (binary); anderen: "charging"
    ({"charger_connected", "charger_connect", "charging", "is_charging"}, "charging"),
    ({"connected"},                                                       "connected"),
    ({"alarm_enabled", "alarm"},                                          "alarm"),
    ({"lock_enabled", "lock"},                                            "lock"),
]

def _categorize_entity(entity_id: str) -> Optional[str]:
    ekw = entity_id.lower().replace(".", "_")
    for keywords, cat in ENTITY_CATEGORIES:
        if any(kw in ekw for kw in keywords):
            return cat
    return None


def discover_ebikes(hass: "HomeAssistant") -> list[dict]:
    """Scant HA entity/device registry voor e-bikes van alle merken.

    Geeft lijst van bike-config dicts terug:
      {"device_id", "name", "brand", "platform", "entities": {...}}

    Merkt automatisch het merk via platform-naam of device-naam.
    """
    try:
        from homeassistant.helpers import entity_registry as er, device_registry as dr
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
    except Exception:
        return []

    bikes: dict[str, dict] = {}

    for entry in ent_reg.entities.values():
        if not entry.device_id:
            continue

        platform  = (entry.platform or "").lower()
        dev       = dev_reg.async_get(entry.device_id)
        dev_name  = ((dev.name or dev.name_by_user or "") if dev else "").lower()

        # Config entry title en domain — bijv. "Bosch eBike Flow" / "bosch_ebike_connect"
        cfg_entry  = hass.config_entries.async_get_entry(entry.config_entry_id)                      if entry.config_entry_id else None
        cfg_domain = (cfg_entry.domain if cfg_entry else "").lower()
        cfg_title  = (cfg_entry.title  if cfg_entry else "").lower()

        # Check of dit een bekende e-bike integratie is
        adapter_cls = None
        for cls in ADAPTERS:
            if (cls.matches_platform(platform)
                    or cls.matches_platform(cfg_domain)
                    or cls.matches_name(dev_name)
                    or cls.matches_name(cfg_title)):
                adapter_cls = cls
                break

        if adapter_cls is None:
            continue

        did = entry.device_id
        if did not in bikes:
            name = (dev.name or dev.name_by_user or "e-bike") if dev else "e-bike"
            bikes[did] = {
                "device_id": did,
                "name":      name,
                "brand":     adapter_cls.BRAND_NAME,
                "platform":  platform,
                "entities":  {},
            }

        cat = _categorize_entity(entry.entity_id)
        if cat and cat not in bikes[did]["entities"]:
            bikes[did]["entities"][cat] = entry.entity_id

    result = list(bikes.values())
    if result:
        _LOGGER.info(
            "EBike discovery: %d fiets(en) gevonden — %s",
            len(result),
            ", ".join(f"{b['name']} ({b['brand']})" for b in result)
        )
    return result


# ── Gedeelde laad-intelligentie ───────────────────────────────────────────────

CHARGE_TEMP_MIN   =  0.0
CHARGE_TEMP_MAX   = 40.0
DEFAULT_TARGET_SOC = 80.0
CHARGER_W_DEFAULT  = 85.0    # W — standaard e-bike lader (~4A × 21V)
LOW_BATTERY_PCT    = 25.0


def calc_charge_advice(
    d: EBikeData,
    solar_w: float,
    price_eur: float,
    forecast: list,
    cheap_threshold: float = 0.18,
) -> tuple[str, str]:
    """Bereken laadadvies (advice, reason) — merk-onafhankelijk."""

    soc = d.soc_pct
    if soc is None:
        return "onbekend", "Geen SOC data"

    if soc >= d.target_soc:
        return "vol", f"Accu vol ({soc:.0f}% ≥ {d.target_soc:.0f}%)"

    if d.temp_c is not None:
        if d.temp_c < CHARGE_TEMP_MIN:
            return "niet_aanbevolen", f"Accu te koud ({d.temp_c:.0f}°C)"
        if d.temp_c > CHARGE_TEMP_MAX:
            return "niet_aanbevolen", f"Accu te warm ({d.temp_c:.0f}°C)"

    if solar_w >= CHARGER_W_DEFAULT * 0.8:
        return "solar", f"Solar-overschot {solar_w:.0f}W — gratis laden"

    if price_eur <= cheap_threshold:
        return "nu_laden", f"Goedkoop tarief {price_eur:.3f} EUR/kWh"

    # Zoek goedkoopste komende 12 uur
    if forecast:
        try:
            best = min(forecast[:12], key=lambda x: float(x.get("price", 999)))
            bp   = float(best.get("price", 999))
            bh   = best.get("hour", "?")
            if bp < price_eur * 0.75:
                return "wachten", f"Goedkoper om {bh}:00 ({bp:.3f} EUR/kWh)"
        except (ValueError, TypeError, KeyError):
            pass

    if soc is not None and soc <= LOW_BATTERY_PCT:
        return "nu_laden", f"Accu laag ({soc:.0f}%) — toch laden"

    return "wachten", f"Huidig tarief {price_eur:.3f} EUR/kWh — wacht op solar/goedkoop"


# ── Hoofd EBike Manager ───────────────────────────────────────────────────────

class EBikeManager:
    """Beheert alle e-bikes van alle merken.

    Auto-detecteert via HA entity/device registry.
    Ondersteunt handmatige config als aanvulling of override.

    Coordinator-gebruik:
        mgr = EBikeManager(hass, config)
        await mgr.async_setup()
        result = await mgr.async_update(coordinator_data)
        # result: {"fietsen": [EBikeData.to_dict(), ...]}
    """

    STORAGE_KEY = "cloudems_ebike_v2"

    # Notificatie-drempels
    NOTIFY_LOW_SOC   = LOW_BATTERY_PCT
    NOTIFY_DONE      = True

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass    = hass
        self._config  = config
        self._store   = None
        self._adapters: list[BrandAdapter]   = []
        self._persist:  dict[str, dict]      = {}  # device_id → opgeslagen data

        # Sessie-tracking (merk-onafhankelijk)
        self._charging_start: dict[str, float] = {}
        self._soc_at_start:   dict[str, float] = {}
        self._notif_low:      set[str]         = set()
        self._notif_done:     set[str]         = set()

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store   = Store(self._hass, 1, self.STORAGE_KEY)
        self._persist = await self._store.async_load() or {}

        # Stap 1: auto-discovery
        discovered = discover_ebikes(self._hass)

        # Stap 2: handmatige config (override of aanvulling)
        manual = self._config.get("ebikes", [])
        manual_ids = {b.get("device_id", b.get("name", "")) for b in manual}

        # Merge: handmatige config wint bij overlap
        all_configs = list(manual)
        for disc in discovered:
            if disc["device_id"] not in manual_ids:
                all_configs.append(disc)

        # Stap 3: adapter aanmaken per fiets
        for cfg in all_configs:
            brand    = cfg.get("brand", "")
            platform = cfg.get("platform", "")
            name     = cfg.get("name", "")

            # Kies adapter: expliciete brand > platform-detect > naam-detect
            cls = None
            if brand:
                cls = next((a for a in ADAPTERS if a.BRAND_NAME == brand), None)
            if cls is None:
                cls = _adapter_for(platform, name)

            # Herstel opgeslagen data in config
            saved = self._persist.get(cfg["device_id"], {})
            cfg.setdefault("battery_wh", int(saved.get("battery_wh", cls.DEFAULT_WH)))

            adapter = cls(self._hass, cfg)
            self._adapters.append(adapter)
            _LOGGER.info("EBike: %s gekoppeld via %s adapter", name, cls.BRAND_NAME)

        if not self._adapters:
            _LOGGER.debug(
                "EBike: geen fietsen gevonden. "
                "Installeer hass-bosch-ebike / ha-specialized-turbo via HACS, "
                "of configureer handmatig via 'ebikes' in CloudEMS opties."
            )

    async def async_update(self, data: dict) -> dict:
        solar_w   = float(data.get("solar_surplus_w") or 0)
        price_eur = float((data.get("energy_price") or {}).get("current_eur_kwh") or 0)
        forecast  = (data.get("energy_price") or {}).get("forecast", [])
        threshold = float(self._config.get("ev_cheap_price_threshold", 0.18))

        results = []
        for adapter in self._adapters:
            try:
                ebike = adapter.read()
                ebike.target_soc = DEFAULT_TARGET_SOC

                # Laadadvies
                ebike.charge_advice, ebike.charge_reason = calc_charge_advice(
                    ebike, solar_w, price_eur, forecast, threshold
                )

                # Resterende laadtijd
                if ebike.is_charging and ebike.soc_pct is not None:
                    needed_wh = ebike.effective_capacity_wh() * (
                        (ebike.target_soc - ebike.soc_pct) / 100
                    )
                    if needed_wh > 0:
                        ebike.minutes_to_full = round(needed_wh / CHARGER_W_DEFAULT * 60)

                # Sessie-tracking & notificaties
                await self._handle_session(ebike)

                results.append(ebike.to_dict())

            except Exception as err:
                _LOGGER.error("EBike %s update fout: %s", adapter._name, err)

        # Periodiek persisteren
        await self._maybe_save()

        return {"fietsen": results, "count": len(results)}

    async def _handle_session(self, ebike: EBikeData) -> None:
        did = ebike.device_id

        # Sessie-start
        if ebike.is_charging and did not in self._charging_start:
            self._charging_start[did] = time.time()
            self._soc_at_start[did]   = ebike.soc_pct or 0
            self._notif_done.discard(did)
            _LOGGER.info("EBike %s: laadsessie gestart (SOC %.0f%%)",
                         ebike.name, ebike.soc_pct or 0)

        # Sessie-einde
        if not ebike.is_charging and did in self._charging_start:
            await self._on_charge_done(ebike)

        # Accu laag melding
        if (ebike.soc_pct is not None
                and ebike.soc_pct <= self.NOTIFY_LOW_SOC
                and not ebike.is_charging
                and did not in self._notif_low):
            await self._notify(
                f"🔋 {ebike.name} — accu bijna leeg",
                f"Nog {ebike.soc_pct:.0f}% geladen"
                + (f" (~{ebike.range_km:.0f} km bereik)" if ebike.range_km else "") + ".",
                f"cloudems_ebike_low_{did}",
            )
            self._notif_low.add(did)

        if ebike.is_charging:
            self._notif_low.discard(did)

    async def _on_charge_done(self, ebike: EBikeData) -> None:
        did       = ebike.device_id
        start_ts  = self._charging_start.pop(did)
        start_soc = self._soc_at_start.pop(did, 0)
        dur_min   = (time.time() - start_ts) / 60
        soc_delta = (ebike.soc_pct or DEFAULT_TARGET_SOC) - start_soc
        kwh       = max(0, ebike.effective_capacity_wh() * soc_delta / 100 / 1000)

        # Persisteer nieuw cycle-getal als geen sensor
        p = self._persist.setdefault(did, {})
        if not ebike.charge_cycles:
            p["charge_cycles"] = p.get("charge_cycles", 0) + max(0, round(soc_delta / 100, 1))
        p["battery_wh"] = ebike.battery_wh

        if did not in self._notif_done:
            await self._notify(
                f"✅ {ebike.name} — opladen klaar",
                (f"Laadsessie {dur_min:.0f} min. "
                 f"SOC: {start_soc:.0f}% → {ebike.soc_pct or DEFAULT_TARGET_SOC:.0f}% "
                 f"(+{kwh:.3f} kWh). "
                 f"Accugezondheid: {ebike.estimated_health_pct():.0f}%."),
                f"cloudems_ebike_done_{did}",
            )
            self._notif_done.add(did)

    async def _notify(self, title: str, msg: str, nid: str) -> None:
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": title, "message": msg, "notification_id": nid},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.debug("EBike notificatie mislukt: %s", err)

    async def _maybe_save(self) -> None:
        if not self._store:
            return
        try:
            await self._store.async_save(self._persist)
        except Exception:
            pass


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _to_int(v: Optional[float]) -> Optional[int]:
    return int(v) if v is not None else None
