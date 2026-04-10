"""
CloudEMS SensorFingerprinter — v5.5.505
Herkent automatisch welk merk/type apparaat een sensor behoort.

Gebruikt entity_id patronen, integratie-naam en statistieken om:
- Omvormertype te identificeren (SolarEdge, Huawei, Growatt, etc.)
- Batterijmerk te identificeren (Nexus, Growatt, Sofar, etc.)
- Grid meter type te identificeren (P1, HomeWizard, DSMR, etc.)
- Automatisch correcte kWh-sensoren voor te stellen
"""
from __future__ import annotations
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Fingerprint database: {patroon: (merk, type, kwh_sensor_suffix)}
INVERTER_FINGERPRINTS = [
    # SolarEdge
    (["solaredge", "solar_edge"],
     "SolarEdge", "inverter",
     ["energy_production_today", "lifetime_production"]),
    # Huawei SUN2000
    (["sun2000", "huawei_solar", "huawei"],
     "Huawei SUN2000", "inverter",
     ["day_active_power_peak", "accumulated_energy_yield"]),
    # Growatt
    (["growatt"],
     "Growatt", "inverter",
     ["today_s_power_generation", "total_power_generation"]),
    # GoodWe
    (["goodwe", "good_we"],
     "GoodWe", "inverter",
     ["today_generation", "total_generation"]),
    # SMA
    (["sma_"],
     "SMA", "inverter",
     ["pv_gen_meter_day", "pv_gen_meter"]),
    # Fronius
    (["fronius"],
     "Fronius", "inverter",
     ["energy_day", "energy_total"]),
    # Enphase
    (["enphase"],
     "Enphase", "micro-inverter",
     ["energy_today", "lifetime_energy"]),
    # Solarman/Deye
    (["solarman", "deye"],
     "Solarman/Deye", "inverter",
     ["daily_production", "total_production"]),
    # Omnik
    (["omnik"],
     "Omnik", "inverter",
     ["today_energy", "total_energy"]),
]

BATTERY_FINGERPRINTS = [
    # Zonneplan Nexus (via Zonneplan integratie)
    (["zonneplan", "nexus"],
     "Zonneplan Nexus", "home-battery",
     ["battery_energy_charged", "battery_energy_discharged"]),
    # Growatt battery
    (["growatt_battery", "growatt.*bat"],
     "Growatt Battery", "home-battery",
     ["today_s_charging_energy", "today_s_discharging_energy"]),
    # Sofar
    (["sofar"],
     "Sofar Solar", "home-battery",
     ["daily_battery_charge", "daily_battery_discharge"]),
    # Huawei LUNA
    (["luna", "huawei.*bat"],
     "Huawei LUNA2000", "home-battery",
     ["charge_capacity_day", "discharge_capacity_day"]),
    # SMA Sunny Boy Storage
    (["sunnyboysto", "sbs"],
     "SMA SBS", "home-battery",
     ["bat_chrg_sum", "bat_dischrg_sum"]),
    # Tesla Powerwall
    (["powerwall", "tesla.*battery"],
     "Tesla Powerwall", "home-battery",
     ["energy_charged", "energy_discharged"]),
    # Victron
    (["victron"],
     "Victron", "home-battery",
     ["battery_charged_energy", "battery_discharged_energy"]),
]

GRID_FINGERPRINTS = [
    (["dsmr", "p1_monitor", "electricity_meter_energie"],
     "DSMR/P1", "grid-meter",
     ["energieverbruik_tarief", "energieproductie_tarief"]),
    (["homewizard"],
     "HomeWizard", "grid-meter",
     ["total_power_import_kwh", "total_power_export_kwh"]),
    (["ams_han", "tibber_pulse", "pulse"],
     "Tibber Pulse/AMS", "grid-meter",
     ["accumulated_consumption", "accumulated_production"]),
    (["slimmemeter", "smart_meter"],
     "Slimme Meter", "grid-meter",
     ["electricity_import_today", "electricity_export_today"]),
]


class SensorFingerprinter:
    """Herkent apparaattype en stelt kWh-sensoren voor."""

    def __init__(self, hass):
        self.hass = hass

    def fingerprint_entity(self, entity_id: str) -> Optional[dict]:
        """
        Probeer entity_id te matchen met bekende apparaten.
        Retourneert {brand, type, suggested_kwh_sensors} of None.
        """
        eid = entity_id.lower()

        # Check omvormers
        for patterns, brand, device_type, kwh_suffixes in INVERTER_FINGERPRINTS:
            for pat in patterns:
                if pat in eid:
                    return {
                        "brand": brand,
                        "type": device_type,
                        "category": "inverter",
                        "suggested_kwh_sensors": self._find_sensors(kwh_suffixes),
                    }

        # Check batterijen
        for patterns, brand, device_type, kwh_suffixes in BATTERY_FINGERPRINTS:
            for pat in patterns:
                if pat in eid:
                    return {
                        "brand": brand,
                        "type": device_type,
                        "category": "battery",
                        "suggested_kwh_sensors": self._find_sensors(kwh_suffixes),
                    }

        # Check grid meters
        for patterns, brand, device_type, kwh_suffixes in GRID_FINGERPRINTS:
            for pat in patterns:
                if pat in eid:
                    return {
                        "brand": brand,
                        "type": device_type,
                        "category": "grid",
                        "suggested_kwh_sensors": self._find_sensors(kwh_suffixes),
                    }
        return None

    def _find_sensors(self, suffixes: list[str]) -> list[str]:
        """Zoek sensoren in HA die overeenkomen met gegeven suffixes."""
        found = []
        for state in self.hass.states.async_all("sensor"):
            eid = state.entity_id.lower()
            for suffix in suffixes:
                if suffix in eid:
                    found.append(state.entity_id)
                    break
        return found[:3]  # max 3 suggesties

    def fingerprint_all_config(self, config: dict) -> dict:
        """Fingerprint alle geconfigureerde sensoren."""
        results = {}

        for i, inv in enumerate(config.get("inverter_configs", [])):
            eid = inv.get("entity_id", "")
            if eid:
                fp = self.fingerprint_entity(eid)
                if fp:
                    results[f"inverter_{i}"] = fp

        for i, bat in enumerate(config.get("battery_configs", [])):
            eid = bat.get("power_sensor", "")
            if eid:
                fp = self.fingerprint_entity(eid)
                if fp:
                    results[f"battery_{i}"] = fp

        grid_eid = config.get("grid_sensor") or config.get("import_power_sensor", "")
        if grid_eid:
            fp = self.fingerprint_entity(grid_eid)
            if fp:
                results["grid"] = fp

        return results

    async def async_suggest_kwh_sensors(self, config: dict) -> dict:
        """
        Combineer fingerprinting met EnergySourceManager auto-detect
        voor maximale dekkingsgraad.
        """
        from .energy_source_manager import EnergySourceManager
        suggestions = {}

        fingerprints = self.fingerprint_all_config(config)
        for key, fp in fingerprints.items():
            kwh_sensors = fp.get("suggested_kwh_sensors", [])
            if kwh_sensors:
                suggestions[f"{key}_kwh_suggestion"] = {
                    "brand": fp["brand"],
                    "sensors": kwh_sensors,
                }

        # Aanvullen met auto-detect
        auto = EnergySourceManager.auto_detect_all(self.hass, config)
        suggestions["auto_detect"] = auto

        return suggestions
