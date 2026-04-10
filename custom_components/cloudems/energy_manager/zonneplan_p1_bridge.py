"""
CloudEMS ZonneplanP1Bridge — v5.5.514
Gebruikt Zonneplan integratie sensoren als databron voor CloudEMS.

Beschikbare data van Zonneplan integratie:
- P1/Grid: vermogen import/export (W), kWh vandaag import/export
- PV: vermogen (W), kWh vandaag, kWh totaal
- Batterij: vermogen (W), SOC (%), geladen/ontladen kWh vandaag
- Prijzen: huidig tarief, volgende uren

Entity_id patronen (sensor.zonneplan_{sensor_key}):
- sensor.zonneplan_electricity_consumption    → grid import W
- sensor.zonneplan_electricity_production     → grid export W  
- sensor.zonneplan_electricity_total_today    → import kWh vandaag
- sensor.zonneplan_electricity_total_today_returned → export kWh vandaag
- sensor.zonneplan_last_measured_value        → PV vermogen W
- sensor.zonneplan_yield_today                → PV kWh vandaag
- sensor.zonneplan_yield_total                → PV kWh lifetime
- sensor.zonneplan_power                      → batterij W (pos=laden, neg=leveren)
- sensor.zonneplan_state_of_charge            → batterij SOC %
- sensor.zonneplan_delivery_day               → batterij ontladen kWh vandaag
- sensor.zonneplan_production_day             → batterij geladen kWh vandaag
- sensor.zonneplan_current_electricity_tariff → huidig tarief €/kWh
"""
from __future__ import annotations
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Mapping: CloudEMS data key → Zonneplan entity_id kandidaten (op volgorde van voorkeur)
ZONNEPLAN_SENSOR_MAP = {
    # Grid vermogen
    "grid_import_w":   ["sensor.zonneplan_electricity_consumption",
                        "sensor.zonneplan_electricity_average"],
    "grid_export_w":   ["sensor.zonneplan_electricity_production"],
    # Grid kWh vandaag
    "grid_import_kwh": ["sensor.zonneplan_electricity_total_today",
                        "sensor.zonneplan_electricity_consumption_today"],
    "grid_export_kwh": ["sensor.zonneplan_electricity_total_today_returned",
                        "sensor.zonneplan_electricity_returned_today"],
    # PV vermogen en energie
    "pv_w":            ["sensor.zonneplan_last_measured_value"],
    "pv_kwh_today":    ["sensor.zonneplan_yield_today"],
    "pv_kwh_total":    ["sensor.zonneplan_yield_total"],
    # Batterij
    "bat_w":           ["sensor.zonneplan_power"],
    "bat_soc_pct":     ["sensor.zonneplan_state_of_charge"],
    "bat_charged_kwh": ["sensor.zonneplan_production_day",
                        "sensor.zonneplan_productie_vandaag"],
    "bat_discharged_kwh": ["sensor.zonneplan_delivery_day",
                           "sensor.zonneplan_levering_vandaag"],
    # Prijs
    "price_eur_kwh":   ["sensor.zonneplan_current_electricity_tariff"],
}


class ZonneplanP1Bridge:
    """
    Leest CloudEMS-relevante data uit de Zonneplan HA integratie.
    
    Werkt als fallback als geen eigen P1/DSMR sensor geconfigureerd is,
    of als aanvulling voor ontbrekende sensoren.
    """

    def __init__(self, hass: "HomeAssistant"):
        self.hass = hass
        self._available_sensors: dict[str, str] = {}  # cloudems_key → entity_id
        self._detected = False

    def detect(self) -> dict[str, str]:
        # Detecteer Zonneplan sensoren in twee groepen:
        # Groep 1: P1/electricity sensoren → bevatten "zonneplan" in entity_id
        # Groep 2: battery sensoren → entity_id = sensor.{device_naam}_*, geen "zonneplan"
        found = {}

        # Groep 1: sensoren MET "zonneplan" in entity_id (P1, prijzen, PV)
        zp_states = [s for s in self.hass.states.async_all("sensor")
                     if "zonneplan" in s.entity_id.lower()
                     and s.state not in ("unavailable", "unknown", "")]

        def _find_zp(patterns):
            for s in zp_states:
                eid = s.entity_id.lower()
                for pat in patterns:
                    if eid.endswith(pat):
                        return s.entity_id
            return None

        found["grid_import_w"]   = _find_zp(["_electricity_consumption", "_electricity_average"])
        found["grid_export_w"]   = _find_zp(["_electricity_production"])
        found["grid_import_kwh"] = _find_zp(["_electricity_total_today", "_electricity_consumption_today"])
        found["grid_export_kwh"] = _find_zp(["_electricity_total_today_returned", "_electricity_returned_today"])
        found["pv_w"]            = _find_zp(["_last_measured_value"])
        found["pv_kwh_today"]    = _find_zp(["_yield_today"])
        found["price_eur_kwh"]   = _find_zp(["_current_electricity_tariff", "_current_tariff"])

        # Groep 2: battery sensoren — device naam als prefix, geen "zonneplan" in entity_id
        # Zoek via entity registry op platform="zonneplan_one"
        try:
            from homeassistant.helpers import entity_registry as _er
            _reg = _er.async_get(self.hass)
            zp_bat_entries = [
                e for e in _reg.entities.values()
                if e.domain == "sensor" and e.platform == "zonneplan_one"
            ]
            all_bat_states = [
                self.hass.states.get(e.entity_id)
                for e in zp_bat_entries
            ]
            bat_states = [s for s in all_bat_states
                          if s and s.state not in ("unavailable", "unknown", "")]

            def _find_bat(patterns):
                for s in bat_states:
                    eid = s.entity_id.lower()
                    for pat in patterns:
                        if eid.endswith(pat):
                            return s.entity_id
                return None

            found["bat_w"]              = _find_bat(["_power"])
            found["bat_soc_pct"]        = _find_bat(["_percentage", "_state_of_charge"])
            found["bat_charged_kwh"]    = _find_bat(["_production_today", "_production_day",
                                                      "_productie_vandaag"])
            found["bat_discharged_kwh"] = _find_bat(["_delivery_today", "_delivery_day",
                                                      "_levering_vandaag"])

        except Exception as _be:
            _LOGGER.debug("ZonneplanP1Bridge battery detectie fout: %s", _be)

        found = {k: v for k, v in found.items() if v}
        self._available_sensors = found
        self._detected = True

        if found:
            _LOGGER.info("ZonneplanP1Bridge: %d sensoren — %s",
                         len(found), list(found.keys()))
            if found.get("bat_charged_kwh"):
                _LOGGER.info("ZonneplanP1Bridge: batterij kWh gevonden: "
                             "geladen=%s ontladen=%s",
                             found.get("bat_charged_kwh"),
                             found.get("bat_discharged_kwh"))
        else:
            _LOGGER.warning("ZonneplanP1Bridge: geen Zonneplan sensoren gevonden — "
                            "check of zonneplan_one integratie actief is")
        return found
    def _read(self, cloudems_key: str, factor: float = 1.0) -> Optional[float]:
        """Lees een waarde uit de gevonden Zonneplan sensor."""
        eid = self._available_sensors.get(cloudems_key)
        if not eid:
            return None
        try:
            state = self.hass.states.get(eid)
            if not state or state.state in ("unavailable", "unknown", ""):
                return None
            return round(float(state.state) * factor, 3)
        except (ValueError, TypeError):
            return None

    def get_grid_power_w(self) -> Optional[float]:
        """
        Nettovermogen in W.
        Positief = import (verbruik), negatief = export (teruglevering).
        """
        imp = self._read("grid_import_w")
        exp = self._read("grid_export_w")
        if imp is not None and exp is not None:
            return round(imp - exp, 1)
        if imp is not None:
            return imp
        return None

    def get_pv_power_w(self) -> Optional[float]:
        """PV vermogen in W."""
        return self._read("pv_w")

    def get_battery_power_w(self) -> Optional[float]:
        """
        Batterij vermogen in W.
        Positief = laden, negatief = ontladen (Nexus conventie).
        """
        return self._read("bat_w")

    def get_battery_soc_pct(self) -> Optional[float]:
        """Batterij SOC in %."""
        return self._read("bat_soc_pct")

    def get_current_price_eur_kwh(self) -> Optional[float]:
        """Huidig elektriciteitstarief in €/kWh."""
        return self._read("price_eur_kwh")

    def get_all(self) -> dict:
        """Lees alle beschikbare Zonneplan data."""
        if not self._detected:
            self.detect()

        result = {}

        grid_w = self.get_grid_power_w()
        if grid_w is not None:
            result["zp_grid_power_w"]   = grid_w
            result["zp_grid_import_w"]  = max(0.0, grid_w)
            result["zp_grid_export_w"]  = max(0.0, -grid_w)

        pv_w = self.get_pv_power_w()
        if pv_w is not None:
            result["zp_solar_power_w"] = pv_w

        bat_w = self.get_battery_power_w()
        if bat_w is not None:
            result["zp_battery_power_w"] = bat_w

        soc = self.get_battery_soc_pct()
        if soc is not None:
            result["zp_battery_soc_pct"] = soc

        price = self.get_current_price_eur_kwh()
        if price is not None:
            result["zp_price_eur_kwh"] = price

        # kWh dagwaarden
        for key, zp_key in [
            ("grid_import_kwh", "zp_grid_import_kwh_today"),
            ("grid_export_kwh", "zp_grid_export_kwh_today"),
            ("pv_kwh_today",    "zp_pv_kwh_today"),
            ("bat_charged_kwh", "zp_bat_charged_kwh_today"),
            ("bat_discharged_kwh", "zp_bat_discharged_kwh_today"),
        ]:
            val = self._read(key)
            if val is not None:
                result[zp_key] = val

        return result

    def fill_missing(self, data: dict) -> dict:
        """
        Vul ontbrekende CloudEMS data aan met Zonneplan waarden.
        Overschrijft bestaande waarden NIET — alleen fallback.
        """
        if not self._detected:
            self.detect()

        zp = self.get_all()

        # Grid: gebruik Zonneplan als fallback voor ontbrekende P1
        if not data.get("grid_power") and zp.get("zp_grid_power_w") is not None:
            data["grid_power"]  = zp["zp_grid_power_w"]
            data["grid_power_source"] = "zonneplan_fallback"
            _LOGGER.debug("ZonneplanP1Bridge: grid_power fallback %.0fW", data["grid_power"])

        # PV: gebruik Zonneplan als fallback
        if not data.get("solar_power") and zp.get("zp_solar_power_w") is not None:
            data["solar_power"] = zp["zp_solar_power_w"]
            data["solar_power_source"] = "zonneplan_fallback"

        # Prijs: gebruik Zonneplan als primaire bron als geen andere beschikbaar
        if not data.get("current_price_eur_kwh") and zp.get("zp_price_eur_kwh"):
            data["current_price_eur_kwh"] = zp["zp_price_eur_kwh"]

        # kWh dag totalen: altijd opslaan (ook als andere bron er al is)
        for zp_key, data_key in [
            ("zp_grid_import_kwh_today",   "zp_grid_import_kwh_today"),
            ("zp_grid_export_kwh_today",    "zp_grid_export_kwh_today"),
            ("zp_pv_kwh_today",             "zp_pv_kwh_today"),
            ("zp_bat_charged_kwh_today",    "zp_bat_charged_kwh_today"),
            ("zp_bat_discharged_kwh_today", "zp_bat_discharged_kwh_today"),
        ]:
            if zp.get(zp_key) is not None:
                data[data_key] = zp[zp_key]

        return data

    @property
    def is_available(self) -> bool:
        """True als Zonneplan integratie aanwezig en bruikbaar is."""
        if not self._detected:
            self.detect()
        return len(self._available_sensors) > 0

    @property
    def available_sensors(self) -> dict[str, str]:
        return self._available_sensors

    def get_summary(self) -> dict:
        """Geef samenvatting van beschikbare Zonneplan sensoren."""
        return {
            "available":      self.is_available,
            "sensor_count":   len(self._available_sensors),
            "sensors":        self._available_sensors,
            "has_grid":       "grid_import_w" in self._available_sensors,
            "has_pv":         "pv_w" in self._available_sensors,
            "has_battery":    "bat_w" in self._available_sensors,
            "has_price":      "price_eur_kwh" in self._available_sensors,
            "has_kwh":        "grid_import_kwh" in self._available_sensors,
        }
