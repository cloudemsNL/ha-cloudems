# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""Config flow for CloudEMS — v1.5.1."""
from __future__ import annotations
import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN, SUPPORT_URL, BUY_ME_COFFEE_URL,
    CONF_GRID_SENSOR, CONF_PHASE_SENSORS, CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY, CONF_EV_CHARGER_COUNT, CONF_EV_CHARGER_CONFIGS, CONF_ENERGY_PRICES_COUNTRY,
    CONF_CLOUD_API_KEY, CONF_MAX_CURRENT_PER_PHASE, CONF_ENABLE_SOLAR_DIMMER,
    CONF_NEGATIVE_PRICE_THRESHOLD,
    CONF_PHASE_COUNT, CONF_PHASE_PRESET,
    CONF_MAX_CURRENT_L1, CONF_MAX_CURRENT_L2, CONF_MAX_CURRENT_L3,
    CONF_DYNAMIC_LOADING, CONF_DYNAMIC_LOAD_THRESHOLD,
    CONF_PHASE_BALANCE, CONF_PHASE_BALANCE_THRESHOLD,
    CONF_P1_ENABLED, CONF_P1_HOST, CONF_P1_PORT,
    CONF_DSMR_SOURCE, DSMR_SOURCE_INTEGRATION, DSMR_SOURCE_HA_ENTITIES,
    DSMR_SOURCE_DIRECT, DSMR_SOURCE_ESPHOME, DSMR_SOURCE_LABELS, DSMR_HA_PLATFORMS,
    CONF_DSMR_TYPE, DSMR_TYPE_4, DSMR_TYPE_5, DSMR_TYPE_UNIVERSAL, DSMR_TYPE_LABELS,
    CONF_ESPHOME_POWER_L1, CONF_ESPHOME_POWER_L2, CONF_ESPHOME_POWER_L3,
    CONF_ESPHOME_POWER_FACTOR_L1, CONF_ESPHOME_POWER_FACTOR_L2, CONF_ESPHOME_POWER_FACTOR_L3,
    CONF_ESPHOME_INRUSH_L1, CONF_ESPHOME_INRUSH_L2, CONF_ESPHOME_INRUSH_L3,
    CONF_ESPHOME_RISE_TIME_L1, CONF_ESPHOME_RISE_TIME_L2, CONF_ESPHOME_RISE_TIME_L3,
    CONF_COST_TRACKING,
    CONF_INVERTER_CONFIGS, CONF_ENABLE_MULTI_INVERTER, CONF_INVERTER_COUNT,
    CONF_USE_SEPARATE_IE, CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR,
    CONF_VOLTAGE_L1, CONF_VOLTAGE_L2, CONF_VOLTAGE_L3,
    CONF_POWER_L1, CONF_POWER_L2, CONF_POWER_L3,
    CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V,
    CONF_OLLAMA_ENABLED, CONF_OLLAMA_HOST, CONF_OLLAMA_PORT, CONF_OLLAMA_MODEL,
    DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_PORT, DEFAULT_OLLAMA_MODEL,
    CONF_PEAK_SHAVING_ENABLED, CONF_PEAK_SHAVING_LIMIT_W, CONF_PEAK_SHAVING_ASSETS,
    CONF_PRESENCE_ENTITIES, CONF_PRESENCE_CALENDAR,
    DEFAULT_PEAK_SHAVING_LIMIT_W,
    DEFAULT_MAX_CURRENT, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    DEFAULT_DYNAMIC_LOAD_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD,
    DEFAULT_P1_PORT, EPEX_COUNTRIES,
    PHASE_PRESETS, PHASE_PRESET_LABELS,
    GRID_SENSOR_KEYWORDS,
    PHASE_SENSOR_KEYWORDS_L1, PHASE_SENSOR_KEYWORDS_L2, PHASE_SENSOR_KEYWORDS_L3,
    GRID_EXCLUDE_KEYWORDS, PHASE_EXCLUDE_KEYWORDS, CURRENT_EXCLUDE_KEYWORDS, VOLTAGE_EXCLUDE_KEYWORDS,
    CONF_WIZARD_MODE, WIZARD_MODE_BASIC, WIZARD_MODE_ADVANCED, WIZARD_MODE_ONBOARDING, WIZARD_MODE_DEMO,
    CONF_AI_PROVIDER, AI_PROVIDER_NONE, AI_PROVIDER_CLOUDEMS,
    AI_PROVIDER_OPENAI, AI_PROVIDER_ANTHROPIC, AI_PROVIDER_OLLAMA,
    AI_PROVIDER_LABELS, AI_PROVIDERS_NEEDING_KEY,
    CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE,
    CONF_GAS_SENSOR,
    CONF_BATTERY_CONFIGS, CONF_ENABLE_MULTI_BATTERY, CONF_BATTERY_COUNT,
    CONF_BATTERY_SCHEDULER_ENABLED, CONF_CONGESTION_ENABLED, CONF_BATTERY_DEGRADATION_ENABLED,
    CONF_GAS_PRICE_SENSOR, CONF_GAS_PRICE_FIXED, CONF_BOILER_EFFICIENCY, CONF_HEAT_PUMP_COP,
    DEFAULT_GAS_PRICE_EUR_M3, DEFAULT_BOILER_EFFICIENCY, DEFAULT_HEAT_PUMP_COP,
    CONF_PRICE_INCLUDE_TAX, CONF_PRICE_INCLUDE_BTW, CONF_SUPPLIER_MARKUP, CONF_SELECTED_SUPPLIER,
    SUPPLIER_MARKUPS, CONF_ENERGY_PRICES_COUNTRY,
    CONF_HIDDEN_TABS, CLOUDEMS_TABS, CLOUDEMS_TABS_HIDDEN_DEFAULT,
    CONF_MAIL_ENABLED, CONF_MAIL_HOST, CONF_MAIL_PORT, CONF_MAIL_USERNAME,
    CONF_MAIL_PASSWORD, CONF_MAIL_FROM, CONF_MAIL_TO, CONF_MAIL_USE_TLS,
    CONF_MAIL_MONTHLY, CONF_MAIL_WEEKLY,
    DEFAULT_MAIL_PORT, DEFAULT_MAIL_USE_TLS,
    # v2.6 klimaat
    CONF_CLIMATE_ENABLED, CONF_CLIMATE_ZONES_ENABLED, CONF_CV_BOILER_ENTITY,
    CONF_CV_MIN_ZONES, CONF_CV_MIN_ON_MIN, CONF_CV_MIN_OFF_MIN, CONF_CV_SUMMER_CUTOFF_C,
    DEFAULT_CV_MIN_ZONES, DEFAULT_CV_MIN_ON_MIN, DEFAULT_CV_MIN_OFF_MIN, DEFAULT_CV_SUMMER_CUTOFF_C,
    CONF_CLIMATE_EPEX_ENABLED, CONF_CLIMATE_EPEX_DEVICES,
    # v2.0 warm water cascade
    CONF_BOILER_GROUPS, CONF_BOILER_GROUPS_ENABLED,
    BOILER_MODE_LABELS, BOILER_MODE_AUTO, BOILER_MODE_SEQUENTIAL,
    BOILER_MODE_PARALLEL, BOILER_MODE_PRIORITY,
    DEFAULT_BOILER_SETPOINT_C, DEFAULT_BOILER_MIN_TEMP_C, DEFAULT_BOILER_COMFORT_C,
    DEFAULT_BOILER_POWER_W, DEFAULT_BOILER_MIN_ON_MIN, DEFAULT_BOILER_MIN_OFF_MIN,
    CONF_SHUTTER_COUNT, CONF_SHUTTER_CONFIGS, CONF_SHUTTER_GROUPS,
    DEFAULT_SHUTTER_COUNT, DEFAULT_SHUTTER_OVERRIDE_H,
    CONF_PROVIDERS,
    CONF_PRICE_PROVIDER, DEFAULT_PRICE_PROVIDER,
    PRICE_PROVIDER_CREDENTIALS, PRICE_PROVIDER_LABELS, EPEX_BASED_PROVIDERS,
)

_LOGGER = logging.getLogger(__name__)


# ── Helper selectors ──────────────────────────────────────────────────────────

def _preset_selector():
    opts = [selector.SelectOptionDict(value=k, label=v) for k, v in PHASE_PRESET_LABELS.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _inverter_count_selector():
    opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(100)]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="dropdown"))

def _country_selector():
    opts = [selector.SelectOptionDict(value=k, label=f"{v} ({k})") for k, v in EPEX_COUNTRIES.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="dropdown"))

def _ai_provider_selector():
    opts = [selector.SelectOptionDict(value=k, label=v) for k, v in AI_PROVIDER_LABELS.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _wizard_mode_selector():
    opts = [
        selector.SelectOptionDict(value=WIZARD_MODE_BASIC,      label="🟢 Basic — quick setup, essential sensors only"),
        selector.SelectOptionDict(value=WIZARD_MODE_ADVANCED,   label="🔧 Advanced — full control over all sensors & features"),
        selector.SelectOptionDict(value=WIZARD_MODE_ONBOARDING, label="🚀 Interactieve wizard — sensoren kiezen via browser"),
        selector.SelectOptionDict(value=WIZARD_MODE_DEMO,       label="🎮 Demo — virtuele installatie, geen echte sensoren nodig"),
    ]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _dsmr_source_selector():
    opts = [selector.SelectOptionDict(value=k, label=v) for k, v in DSMR_SOURCE_LABELS.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _ent(domains=None):
    cfg = selector.EntitySelectorConfig(domain=domains or "sensor")
    return selector.EntitySelector(cfg)


# ── Merk-presets voor boiler wizard ──────────────────────────────────────────
# Elke entry bevat de volledige backend-config die automatisch wordt ingevuld.
# "_label" is alleen UI. De gebruiker kan alles daarna nog aanpassen.
BOILER_BRAND_PRESETS: dict[str, dict] = {
    # ── Generiek (bovenaan — meest gekozen startpunt) ─────────────────────────
    "unknown": {
        "_label":               "❓ Merk onbekend — handmatig instellen",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       0.0,
        "setpoint_c":           60.0,
        "min_temp_c":           40.0,
    },
    "generic_resistive": {
        "_label":               "⚡ Generiek elektrisch (switch / setpoint)",
        "boiler_type":          "resistive",
        "control_mode":         "switch",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       0.0,
        "setpoint_c":           60.0,
        "min_temp_c":           40.0,
    },
    "generic_heatpump": {
        "_label":               "♻️ Generiek warmtepomp boiler",
        "boiler_type":          "heat_pump",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 60.0,
        "surplus_setpoint_c":   60.0,
        "hardware_max_c":       60.0,
        "setpoint_c":           55.0,
        "min_temp_c":           40.0,
        "hardware_deadband_c":  2.0,
    },
    # ── Ariston ──────────────────────────────────────────────────────────────
    "ariston_lydos_hybrid": {
        "_label":               "🔥 Ariston Lydos Hybrid (warmtepomp + weerstand)",
        "boiler_type":          "hybrid",
        "control_mode":         "preset",
        "preset_on":            "BOOST",
        "preset_off":           "GREEN",
        "max_setpoint_boost_c": 75.0,
        "max_setpoint_green_c": 53.0,
        "hardware_max_c":       75.0,
        "surplus_setpoint_c":   75.0,
        "setpoint_c":           53.0,
        "min_temp_c":           35.0,
        "hardware_deadband_c":  2.0,
        "stall_timeout_s":      300.0,
        "stall_boost_c":        5.0,
    },
    "ariston_velis_evo": {
        "_label":               "⚡ Ariston Velis Evo (elektrisch)",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "MANUAL",
        "preset_off":           "MANUAL",
        "max_setpoint_boost_c": 80.0,
        "surplus_setpoint_c":   80.0,
        "hardware_max_c":       80.0,
        "setpoint_c":           60.0,
        "min_temp_c":           35.0,
    },
    "ariston_andris": {
        "_label":               "⚡ Ariston Andris Lux (elektrisch)",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "MANUAL",
        "preset_off":           "MANUAL",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       75.0,
        "setpoint_c":           60.0,
        "min_temp_c":           35.0,
    },
    # ── Midea / Comfee (midea_ac_lan integratie) ─────────────────────────────
    "midea_e2": {
        "_label":               "💧 Midea / Comfee elektrisch boiler (E2)",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       75.0,
        "setpoint_c":           60.0,
        "min_temp_c":           30.0,
    },
    "midea_e3": {
        "_label":               "🔥 Midea / Comfee gas boiler (E3)",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 65.0,
        "surplus_setpoint_c":   65.0,
        "hardware_max_c":       65.0,
        "setpoint_c":           55.0,
        "min_temp_c":           35.0,
    },
    # ── Daikin ───────────────────────────────────────────────────────────────
    "daikin_altherma_dhw": {
        "_label":               "♻️ Daikin Altherma DHW (warmtepomp boiler)",
        "boiler_type":          "heat_pump",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 60.0,
        "surplus_setpoint_c":   60.0,
        "hardware_max_c":       60.0,
        "setpoint_c":           55.0,
        "min_temp_c":           40.0,
        "hardware_deadband_c":  3.0,
    },
    # ── Vaillant ─────────────────────────────────────────────────────────────
    "vaillant_unistor": {
        "_label":               "♻️ Vaillant uniSTOR / aroSTOR (warmtepomp boiler)",
        "boiler_type":          "heat_pump",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 65.0,
        "surplus_setpoint_c":   65.0,
        "hardware_max_c":       65.0,
        "setpoint_c":           55.0,
        "min_temp_c":           40.0,
        "hardware_deadband_c":  3.0,
    },
    # ── Stiebel Eltron ───────────────────────────────────────────────────────
    "stiebel_wwk": {
        "_label":               "♻️ Stiebel Eltron WWK / SHW (warmtepomp boiler)",
        "boiler_type":          "heat_pump",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 65.0,
        "surplus_setpoint_c":   65.0,
        "hardware_max_c":       65.0,
        "setpoint_c":           55.0,
        "min_temp_c":           40.0,
        "hardware_deadband_c":  2.0,
    },
    # ── A.O. Smith / State / American Water Heater ───────────────────────────
    "aosmith_electric": {
        "_label":               "⚡ A.O. Smith / State elektrisch",
        "boiler_type":          "resistive",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 60.0,
        "surplus_setpoint_c":   60.0,
        "hardware_max_c":       60.0,
        "setpoint_c":           55.0,
        "min_temp_c":           35.0,
    },
    # ── Itho Daalderop ───────────────────────────────────────────────────────
    "itho_heatpump": {
        "_label":               "♻️ Itho Daalderop warmtepomp boiler",
        "boiler_type":          "heat_pump",
        "control_mode":         "setpoint",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 60.0,
        "surplus_setpoint_c":   60.0,
        "hardware_max_c":       60.0,
        "setpoint_c":           55.0,
        "min_temp_c":           40.0,
        "hardware_deadband_c":  3.0,
    },
    # ── Dimmer / vermogensregeling ────────────────────────────────────────────
    "dimmerlink": {
        "_label":               "💡 DimmerLink / RBDimmer (vermogensregeling via dimmer)",
        "boiler_type":          "resistive",
        "control_mode":         "dimmer",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       75.0,
        "setpoint_c":           60.0,
        "min_temp_c":           40.0,
        "dimmer_on_pct":        100.0,
        "dimmer_off_pct":       0.0,
    },
    "acrouter": {
        "_label":               "🔌 ACRouter (RobotDyn DimmerLink via IP)",
        "boiler_type":          "resistive",
        "control_mode":         "acrouter",
        "preset_on":            "on",
        "preset_off":           "off",
        "max_setpoint_boost_c": 75.0,
        "surplus_setpoint_c":   75.0,
        "hardware_max_c":       75.0,
        "setpoint_c":           60.0,
        "min_temp_c":           40.0,
    },
}

def _boiler_brand_selector() -> selector.SelectSelector:
    opts = [
        selector.SelectOptionDict(value=k, label=v["_label"])
        for k, v in BOILER_BRAND_PRESETS.items()
    ]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="dropdown"))


def _brand_category(brand_key: str) -> str:
    """Bepaal welke velden getoond worden op basis van het gekozen merk.

    known_brand  — preset bevat alle sturingsinstellingen, alleen setpoint + sensoren tonen
    generic_switch — aan/uit of setpoint, geen dimmer
    generic_heatpump — setpoint only, geen dimmer
    dimmer       — dimmer% velden tonen, geen preset/control_mode keuze
    manual       — alle velden zichtbaar (volledig handmatig)
    """
    if brand_key == "unknown":
        return "manual"
    if brand_key == "generic_resistive":
        return "generic_switch"
    if brand_key == "generic_heatpump":
        return "generic_heatpump"
    if brand_key in ("dimmerlink", "acrouter"):
        return "dimmer"
    # Alle andere bekende merken (Ariston, Daikin, Vaillant, etc.)
    return "known_brand"


# ── Auto-detection ────────────────────────────────────────────────────────────

def _score(entity_id: str, keywords: list[str]) -> int:
    n = entity_id.lower()
    return sum(1 for kw in keywords if kw in n)

def _best(pool, keywords):
    """Return the best matching entity_id from pool.

    Tiebreaker: longer keyword match wins; then shorter entity_id (more specific name).
    This prevents non-deterministic picks when multiple sensors score equally.
    """
    scored = [(s, _score(s, keywords)) for s in pool]
    scored = [(s, sc) for s, sc in scored if sc > 0]
    if not scored:
        return None
    # Sort: highest score first, then shortest entity_id as tiebreaker
    scored.sort(key=lambda x: (-x[1], len(x[0]), x[0]))
    return scored[0][0]

def _exclude(pool: list, exclude_kws: list) -> list:
    """Remove entities whose id contains any exclusion keyword."""
    ex = [kw.lower() for kw in exclude_kws]
    return [e for e in pool if not any(kw in e.lower() for kw in ex)]


def _validate_power_sensor(hass, entity_id: str) -> str | None:
    """Controleer of een entity_id een vermogenssensor is (W/kW), niet een energieteller (kWh).

    Geeft None terug als de sensor geldig is, anders een foutsleutel.
    Sensoren met device_class='energy' of unit='kWh'/'Wh' zijn kWh-tellers
    en worden niet geaccepteerd als vermogenssensor voor CloudEMS.
    """
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None  # niet geladen, laat door — runtime zal het merken
    attrs = state.attributes
    dc    = attrs.get("device_class", "")
    unit  = (attrs.get("unit_of_measurement") or "").lower().strip()
    sc    = attrs.get("state_class", "")

    # Blokkeer alleen als unit ZEKER een energieteller is (kWh/Wh/MWh)
    # device_class energy + kWh-unit = onmiskenbare energieteller
    if unit in ("kwh", "wh", "mwh"):
        return "sensor_is_energy_not_power"
    # state_class NIET gebruiken als blokkade:
    # een kW-vermogensmeter (netto) kan ook state_class total/total_increasing hebben
    return None


def _detect_sensors(hass, phase_count: int) -> dict:
    """Auto-detect HA sensors by unit + keyword scoring.

    Scoring priority:
      1. Exact DSMR / HomeWizard entity patterns (highest weight: +5)
      2. Keyword match in entity_id
      3. Tiebreaker: shortest entity_id (more specific name)
    """
    all_power   = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") in ("W","kW")]
    all_current = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") == "A"]
    all_voltage = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") == "V"]

    # Filtered pools — exclude obvious false-positives for each role
    grid_power    = _exclude(all_power,   GRID_EXCLUDE_KEYWORDS)
    phase_power   = _exclude(all_power,   PHASE_EXCLUDE_KEYWORDS)
    phase_current = _exclude(all_current, CURRENT_EXCLUDE_KEYWORDS)
    phase_voltage = _exclude(all_voltage, VOLTAGE_EXCLUDE_KEYWORDS)

    # PV / battery use full pool so we still find them even if exclusions are broad
    pv_power   = all_power
    batt_power = all_power

    # DSMR5 / HomeWizard per-phase export pool  (bidirectional meters)
    dsmr_export_l1 = _best(all_power, ["power_returned_l1","power_l1_neg","l1_export","l1_return","fase_1_return"])
    dsmr_export_l2 = _best(all_power, ["power_returned_l2","power_l2_neg","l2_export","l2_return","fase_2_return"])
    dsmr_export_l3 = _best(all_power, ["power_returned_l3","power_l3_neg","l3_export","l3_return","fase_3_return"])

    # Better import/export detection: DSMR 'power_delivered' = import, 'power_returned' = export
    import_kws = ["power_delivered","net_power_import","import_power","energy_import","power_import",
                  "levering","consume","afname","meting_levering"]
    export_kws = ["power_returned","net_power_export","export_power","energy_export","power_export",
                  "teruglevering","feed","return","terugmeting"]

    p3 = phase_count == 3
    return {
        CONF_GRID_SENSOR:            _best(grid_power,    GRID_SENSOR_KEYWORDS),
        CONF_IMPORT_SENSOR:          _best(grid_power,    import_kws),
        CONF_EXPORT_SENSOR:          _best(grid_power,    export_kws),
        CONF_SOLAR_SENSOR:           _best(pv_power,      ["solar","pv","zon","zonne","inverter","omvormer","yield","opwek"]),
        CONF_BATTERY_SENSOR:         _best(batt_power,    ["battery","batterij","accu","batt","storage","opslag"]),
        CONF_PHASE_SENSORS+"_L1":    _best(phase_current, PHASE_SENSOR_KEYWORDS_L1),
        CONF_PHASE_SENSORS+"_L2":    _best(phase_current, PHASE_SENSOR_KEYWORDS_L2) if p3 else None,
        CONF_PHASE_SENSORS+"_L3":    _best(phase_current, PHASE_SENSOR_KEYWORDS_L3) if p3 else None,
        CONF_VOLTAGE_L1:             _best(phase_voltage, ["l1","phase1","phase_1","fase_1","voltage_l1"]),
        CONF_VOLTAGE_L2:             _best(phase_voltage, ["l2","phase2","phase_2","fase_2","voltage_l2"]) if p3 else None,
        CONF_VOLTAGE_L3:             _best(phase_voltage, ["l3","phase3","phase_3","fase_3","voltage_l3"]) if p3 else None,
        CONF_POWER_L1:               _best(phase_power,   PHASE_SENSOR_KEYWORDS_L1),
        CONF_POWER_L2:               _best(phase_power,   PHASE_SENSOR_KEYWORDS_L2) if p3 else None,
        CONF_POWER_L3:               _best(phase_power,   PHASE_SENSOR_KEYWORDS_L3) if p3 else None,
        # DSMR5 per-phase export (bidirectionele meter)
        "power_sensor_l1_export":    dsmr_export_l1,
        "power_sensor_l2_export":    dsmr_export_l2 if p3 else None,
        "power_sensor_l3_export":    dsmr_export_l3 if p3 else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Config flow
# ══════════════════════════════════════════════════════════════════════════════

class CloudEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    CloudEMS wizard.

    Basic mode:
      welcome → grid_connection → [phase_custom] → dsmr_source → grid_sensors
      → phase_sensors (altijd bij 3-fase)
      → solar_ev (overslaan mogelijk)
      → managed_battery (overslaan mogelijk)
      → price_provider → [prices / credentials]
      → _create()

    Advanced voegt toe:
      Na grid_sensors/phase_sensors → generator
      Na solar_ev → inverter_count → inverter_detail
      Na managed_battery → battery_count → battery_detail → shutter_count → shutter_detail
      Na price_provider/prices → features → [peak_config] → ai_config → [ollama_config]
        → advanced → [p1_config] → climate → [boiler/epex] → mail → diagnostics
      → _create()
    """

    VERSION = 6

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._suggestions: dict = {}
        self._inv_count = 0
        self._inv_step  = 0
        self._bat_count = 0
        self._bat_step  = 0
        self._ce_count  = 0
        self._ce_step   = 0

    def _advanced(self) -> bool:
        return self._config.get(CONF_WIZARD_MODE) == WIZARD_MODE_ADVANCED

    # ── 1. Welcome ────────────────────────────────────────────────────────────
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_grid_connection()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ENERGY_PRICES_COUNTRY, default="NL"): _country_selector(),
                vol.Required(CONF_WIZARD_MODE, default=WIZARD_MODE_BASIC): _wizard_mode_selector(),
            }),
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/welcome.svg",
                    
                "support_url": SUPPORT_URL,
                "buy_me_coffee_url": BUY_ME_COFFEE_URL,
                "website": "https://cloudems.eu",
            },
        )

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            # Onboarding wizard modus: minimale setup + HA-notificatie met URL
            if user_input.get(CONF_WIZARD_MODE) == WIZARD_MODE_ONBOARDING:
                return await self.async_step_onboarding_redirect()
            # Demo modus: geen sensoren nodig, direct afronden met demo-config
            if user_input.get(CONF_WIZARD_MODE) == WIZARD_MODE_DEMO:
                return await self.async_step_demo_finish()
            # Auto-discover vanuit HA Energy dashboard
            from .energy_autodiscover import async_discover_from_energy_dashboard
            disc = await async_discover_from_energy_dashboard(self.hass)
            if disc.confidence != "none":
                # Pre-fill config met gevonden sensoren (gebruiker bevestigt nog)
                prefill = disc.to_config_prefill()
                self._config.update({k: v for k, v in prefill.items() if k not in self._config or not self._config[k]})
                self._energy_discovery = disc
                return await self.async_step_ha_energy_import()
            self._energy_discovery = disc
            return await self.async_step_grid_connection()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ENERGY_PRICES_COUNTRY, default="NL"): _country_selector(),
                vol.Required(CONF_WIZARD_MODE, default=WIZARD_MODE_BASIC): _wizard_mode_selector(),
            }),
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/welcome.svg",
                    
                "support_url": SUPPORT_URL,
                "buy_me_coffee_url": BUY_ME_COFFEE_URL,
                "website": "https://cloudems.eu",
            },
        )

    async def async_step_demo_finish(self, user_input=None):
        """Demo modus: sla minimale config op en activeer demo engine direct.
        Geen echte sensoren nodig — virtuele installatie met tijdversnelling."""
        from .const import CONF_DEMO_ENABLED, CONF_DEMO_SPEED

        # Demo config: minimale waarden, geen echte sensoren
        self._config.update({
            CONF_DEMO_ENABLED:    True,
            CONF_DEMO_SPEED:      48,    # 48× tijdversnelling — dag in 30 min
            CONF_WIZARD_MODE:     WIZARD_MODE_DEMO,
            # Lege sensor-velden zodat coordinator niet crasht
            "grid_sensor":        "",
            "solar_sensor":       "",
            "battery_sensor":     "",
            "battery_soc_entity": "",
        })

        # Stuur HA-notificatie
        try:
            await self.hass.services.async_call(
                "persistent_notification", "create", {
                    "title": "CloudEMS Demo actief 🎮",
                    "message": (
                        "CloudEMS draait in demo modus.\n\n"
                        "Een volledige dag wordt gesimuleerd in ~30 minuten (48× versnelling).\n"
                        "Geen echte sensoren of apparaten worden aangestuurd.\n\n"
                        "Activeer/deactiveer via: CloudEMS → Configureren → Systeem → Demo modus"
                    ),
                    "notification_id": "cloudems_demo_active",
                }
            )
        except Exception:
            pass

        return self.async_create_entry(
            title="CloudEMS Demo",
            data=self._config,
        )

    async def async_step_onboarding_redirect(self, user_input=None):
        """Toon de wizard-URL en voltooi de setup met basisdefaults."""
        _ONBOARDING_URL = "http://homeassistant.local:8123/local/cloudems/onboarding.html"
        if user_input is not None:
            # Zet wizard mode terug op basic voor de daadwerkelijke flow
            self._config[CONF_WIZARD_MODE] = WIZARD_MODE_BASIC
            # Stuur HA-notificatie met URL
            try:
                await self.hass.services.async_call(
                    "persistent_notification", "create", {
                        "title": "CloudEMS — Interactieve wizard",
                        "message": (
                            f"Open de interactieve setup wizard in je browser:\n\n"
                            f"**[{_ONBOARDING_URL}]({_ONBOARDING_URL})**\n\n"
                            f"De wizard helpt je sensoren en apparaten koppelen "
                            f"zonder handmatig typen."
                        ),
                        "notification_id": "cloudems_onboarding_url",
                    }
                )
            except Exception:
                pass
            return await self.async_step_grid_connection()
        return self.async_show_form(
            step_id="onboarding_redirect",
            description_placeholders={"onboarding_url": _ONBOARDING_URL},
        )

    async def async_step_ha_energy_import(self, user_input=None):
        """Toon wat auto-discover gevonden heeft en laat gebruiker bevestigen of aanpassen."""
        disc = getattr(self, "_energy_discovery", None)

        if user_input is not None:
            # Overschrijf alleen met expliciete gebruikersinput (lege waarden negeren)
            for k, v in user_input.items():
                if v:
                    self._config[k] = v
            # skip_import → overgeslagen, direct naar grid_connection
            return await self.async_step_grid_connection()

        if disc is None:
            return await self.async_step_grid_connection()

        # Build bevestigingsformulier op basis van wat gevonden is
        existing = self._config
        schema_dict = {}

        if disc.grid_power_sensor or disc.import_power_sensor:
            if disc.import_power_sensor and disc.export_power_sensor:
                schema_dict[vol.Optional("import_power_sensor",
                    description={"suggested_value": disc.import_power_sensor or ""})] = str
                schema_dict[vol.Optional("export_power_sensor",
                    description={"suggested_value": disc.export_power_sensor or ""})] = str
            else:
                schema_dict[vol.Optional("grid_sensor",
                    description={"suggested_value": disc.grid_power_sensor or ""})] = str

        if disc.solar_sensors:
            schema_dict[vol.Optional("solar_sensor",
                description={"suggested_value": disc.solar_sensors[0]})] = str

        if disc.battery_power_in or disc.battery_power_out:
            schema_dict[vol.Optional("battery_sensor",
                description={"suggested_value": disc.battery_power_in or disc.battery_power_out or ""})] = str

        # Build samenvatting voor description
        found_lines = []
        if disc.grid_power_sensor:     found_lines.append(f"⚡ Net-sensor: `{disc.grid_power_sensor}`")
        if disc.import_power_sensor:   found_lines.append(f"⬇️ Import: `{disc.import_power_sensor}`")
        if disc.export_power_sensor:   found_lines.append(f"⬆️ Export: `{disc.export_power_sensor}`")
        for s in disc.solar_sensors:   found_lines.append(f"☀️ PV-sensor: `{s}`")
        if disc.battery_power_in:      found_lines.append(f"🔋 Batterij laden: `{disc.battery_power_in}`")
        if disc.battery_power_out:     found_lines.append(f"🔋 Batterij ontladen: `{disc.battery_power_out}`")
        found_text = "\n".join(found_lines)

        return self.async_show_form(
            step_id="ha_energy_import",
            data_schema=vol.Schema(schema_dict) if schema_dict else vol.Schema({}),
            description_placeholders={
                "found": found_text,
                "count": str(len(found_lines)),
            },
        )

    # ── 2. Grid connection preset ─────────────────────────────────────────────
    async def async_step_grid_connection(self, user_input=None):
        if user_input is not None:
            key = user_input.get(CONF_PHASE_PRESET, "3x25A")
            self._config[CONF_PHASE_PRESET] = key
            if key == "custom":
                return await self.async_step_phase_custom()
            preset = PHASE_PRESETS[key]
            self._config.update({
                CONF_PHASE_COUNT:           preset["count"],
                CONF_MAX_CURRENT_L1:        preset["L1"],
                CONF_MAX_CURRENT_L2:        preset["L2"],
                CONF_MAX_CURRENT_L3:        preset["L3"],
                CONF_MAX_CURRENT_PER_PHASE: preset["L1"],
            })
            return await self.async_step_dsmr_source()
        return self.async_show_form(
            step_id="grid_connection",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_PRESET, default="3x25A"): _preset_selector(),
            }),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/grid_connection.svg",
            },
        )

    # ── 2b. Custom limits ─────────────────────────────────────────────────────
    async def async_step_phase_custom(self, user_input=None):
        if user_input is not None:
            count   = int(user_input.get(CONF_PHASE_COUNT, 3))
            l1      = float(user_input.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))
            dsmr_t  = user_input.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL)
            self._config.update({
                CONF_PHASE_COUNT:           count,
                CONF_MAX_CURRENT_L1:        l1,
                CONF_MAX_CURRENT_PER_PHASE: l1,
                # L2 en L3 altijd gelijk aan L1 — gebruiker hoeft maar 1 waarde in te vullen
                CONF_MAX_CURRENT_L2: l1 if count == 3 else None,
                CONF_MAX_CURRENT_L3: l1 if count == 3 else None,
                CONF_DSMR_TYPE:             dsmr_t,
            })
            return await self.async_step_dsmr_source()

        dsmr_type_opts = [
            selector.SelectOptionDict(value=k, label=v)
            for k, v in DSMR_TYPE_LABELS.items()
        ]
        return self.async_show_form(
            step_id="phase_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_COUNT, default=3): vol.In({1: "1 phase", 3: "3 phases"}),
                vol.Required(CONF_MAX_CURRENT_L1, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Required(CONF_DSMR_TYPE, default=DSMR_TYPE_UNIVERSAL): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=dsmr_type_opts, mode=selector.SelectSelectorMode.LIST)
                ),
            }),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/phase_custom.svg",
            },
        )

    # ── 3. DSMR / Meter bron keuze ───────────────────────────────────────────
    async def async_step_dsmr_source(self, user_input=None):
        """Laat de gebruiker kiezen hoe CloudEMS de slimme-meterdata leest.

        Keuzes:
          • DSMR / HomeWizard integratie — auto-detecteer entiteiten uit HA
          • Handmatig HA-sensoren selecteren — vrije sensorpicker
          • Directe P1-verbinding (IP/serieel) — directe TCP/serieel koppeling
        """
        if user_input is not None:
            source = user_input.get(CONF_DSMR_SOURCE, DSMR_SOURCE_HA_ENTITIES)
            self._config[CONF_DSMR_SOURCE] = source

            if source == DSMR_SOURCE_INTEGRATION:
                # Auto-detecteer DSMR/HomeWizard entiteiten en pre-fill grid sensors
                await self._prefill_from_dsmr_integration()
                return await self.async_step_grid_sensors()

            elif source == DSMR_SOURCE_DIRECT:
                # Directe P1-verbinding — ga naar P1 config, daarna naar grid_sensors
                self._config["_p1_direct_from_wizard"] = True
                return await self.async_step_p1_config()

            elif source == DSMR_SOURCE_ESPHOME:
                # DIY ESPHome meter — ga naar ESPHome sensor picker
                return await self.async_step_esphome_sensors()

            else:  # DSMR_SOURCE_HA_ENTITIES
                return await self.async_step_grid_sensors()

        # Auto-detecteer welke opties beschikbaar zijn als hint
        detected_integration = await self._detect_dsmr_integration()
        default_source = DSMR_SOURCE_INTEGRATION if detected_integration else DSMR_SOURCE_HA_ENTITIES
        # Herstel bestaande keuze bij reconfigure
        default_source = self._config.get(CONF_DSMR_SOURCE, default_source)

        if detected_integration:
            detected_msg = f"✅ Gevonden: **{detected_integration}** — sensoren worden automatisch ingelezen."
        else:
            detected_msg = "ℹ️ Geen bekende DSMR/P1-integratie gevonden. Selecteer HA-sensoren handmatig of stel een directe verbinding in."

        return self.async_show_form(
            step_id="dsmr_source",
            data_schema=vol.Schema({
                vol.Required(CONF_DSMR_SOURCE, default=default_source): _dsmr_source_selector(),
            }),
            description_placeholders={
                "detected": detected_msg,
                "diagram_url": "/local/cloudems/diagrams/grid_sensors.svg",
            },
        )

    async def _detect_dsmr_integration(self) -> str:
        """Detecteer of een bekende DSMR/P1 HA-integratie aanwezig is.

        Geeft de naam van de integratie terug als die gevonden wordt, anders ''.
        Detectie op basis van platform van aanwezige sensor-entiteiten.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)
            for entry in ent_reg.entities.values():
                if entry.domain != "sensor":
                    continue
                if entry.platform in DSMR_HA_PLATFORMS:
                    platform_labels = {
                        "dsmr": "DSMR integratie",
                        "homewizard": "HomeWizard Energy",
                        "slimmelezer": "SLIMMELEZER+",
                        "p1_monitor": "P1 Monitor",
                        "iungo": "Iungo",
                        "youless": "YouLess",
                        "ecodevices": "ecoDevices",
                    }
                    return platform_labels.get(entry.platform, entry.platform)
        except Exception:
            pass
        # Fallback: zoek op bekende entity-id patronen
        probe_ids = [
            "sensor.dsmr_reading_electricity_currently_delivered",
            "sensor.homewizard_p1_active_power_w",
            "sensor.p1_active_power",
            "sensor.slimmelezer_power_delivered",
            "sensor.electricity_power_usage",
        ]
        for eid in probe_ids:
            state = self.hass.states.get(eid)
            if state and state.state not in ("unavailable", "unknown", ""):
                if "dsmr" in eid:
                    return "DSMR integratie"
                if "homewizard" in eid:
                    return "HomeWizard Energy"
                if "slimmelezer" in eid:
                    return "SLIMMELEZER+"
                return "P1 integratie"
        return ""


    async def async_step_esphome_sensors(self, user_input=None):
        """Wizard stap: koppel de ESPHome NILM-meter sensoren (L1/L2/L3)."""
        errors: dict = {}
        if user_input is not None:
            power_l1 = user_input.get(CONF_ESPHOME_POWER_L1, "")
            if not power_l1:
                errors[CONF_ESPHOME_POWER_L1] = "esphome_power_required"
            else:
                self._config[CONF_ESPHOME_POWER_L1]        = power_l1
                self._config[CONF_ESPHOME_POWER_L2]        = user_input.get(CONF_ESPHOME_POWER_L2, "")
                self._config[CONF_ESPHOME_POWER_L3]        = user_input.get(CONF_ESPHOME_POWER_L3, "")
                self._config[CONF_ESPHOME_POWER_FACTOR_L1] = user_input.get(CONF_ESPHOME_POWER_FACTOR_L1, "")
                self._config[CONF_ESPHOME_POWER_FACTOR_L2] = user_input.get(CONF_ESPHOME_POWER_FACTOR_L2, "")
                self._config[CONF_ESPHOME_POWER_FACTOR_L3] = user_input.get(CONF_ESPHOME_POWER_FACTOR_L3, "")
                self._config[CONF_ESPHOME_INRUSH_L1]       = user_input.get(CONF_ESPHOME_INRUSH_L1, "")
                self._config[CONF_ESPHOME_INRUSH_L2]       = user_input.get(CONF_ESPHOME_INRUSH_L2, "")
                self._config[CONF_ESPHOME_INRUSH_L3]       = user_input.get(CONF_ESPHOME_INRUSH_L3, "")
                self._config[CONF_ESPHOME_RISE_TIME_L1]    = user_input.get(CONF_ESPHOME_RISE_TIME_L1, "")
                self._config[CONF_ESPHOME_RISE_TIME_L2]    = user_input.get(CONF_ESPHOME_RISE_TIME_L2, "")
                self._config[CONF_ESPHOME_RISE_TIME_L3]    = user_input.get(CONF_ESPHOME_RISE_TIME_L3, "")
                self._config["import_power_sensor"]         = power_l1
                return await self.async_step_grid_sensors()

        # Auto-detecteer ESPHome sensoren — sorteer alfabetisch zodat L1/L2/L3 op volgorde staan
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg  = er.async_get(self.hass)
            esp_all  = sorted([e.entity_id for e in ent_reg.entities.values()
                        if e.platform == "esphome"])
            esp_power  = [e for e in esp_all if "power" in e.lower() and "factor" not in e.lower()]
            esp_pf     = [e for e in esp_all if "power_factor" in e.lower()]
            esp_inrush = [e for e in esp_all if "inrush" in e.lower()]
            esp_rise   = [e for e in esp_all if "rise_time" in e.lower()]
        except Exception:
            esp_power = esp_pf = esp_inrush = esp_rise = []

        _ent_sel = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))

        return self.async_show_form(
            step_id="esphome_sensors",
            data_schema=vol.Schema({
                # ── Vermogen per fase (L1 verplicht, L2+L3 optioneel) ─────────
                vol.Required(CONF_ESPHOME_POWER_L1,
                    default=self._config.get(CONF_ESPHOME_POWER_L1,
                        esp_power[0] if len(esp_power) > 0 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_POWER_L2,
                    default=self._config.get(CONF_ESPHOME_POWER_L2,
                        esp_power[1] if len(esp_power) > 1 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_POWER_L3,
                    default=self._config.get(CONF_ESPHOME_POWER_L3,
                        esp_power[2] if len(esp_power) > 2 else "")): _ent_sel,
                # ── Power factor per fase ─────────────────────────────────────
                vol.Optional(CONF_ESPHOME_POWER_FACTOR_L1,
                    default=self._config.get(CONF_ESPHOME_POWER_FACTOR_L1,
                        esp_pf[0] if len(esp_pf) > 0 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_POWER_FACTOR_L2,
                    default=self._config.get(CONF_ESPHOME_POWER_FACTOR_L2,
                        esp_pf[1] if len(esp_pf) > 1 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_POWER_FACTOR_L3,
                    default=self._config.get(CONF_ESPHOME_POWER_FACTOR_L3,
                        esp_pf[2] if len(esp_pf) > 2 else "")): _ent_sel,
                # ── Inrush per fase ───────────────────────────────────────────
                vol.Optional(CONF_ESPHOME_INRUSH_L1,
                    default=self._config.get(CONF_ESPHOME_INRUSH_L1,
                        esp_inrush[0] if len(esp_inrush) > 0 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_INRUSH_L2,
                    default=self._config.get(CONF_ESPHOME_INRUSH_L2,
                        esp_inrush[1] if len(esp_inrush) > 1 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_INRUSH_L3,
                    default=self._config.get(CONF_ESPHOME_INRUSH_L3,
                        esp_inrush[2] if len(esp_inrush) > 2 else "")): _ent_sel,
                # ── Rise time per fase ────────────────────────────────────────
                vol.Optional(CONF_ESPHOME_RISE_TIME_L1,
                    default=self._config.get(CONF_ESPHOME_RISE_TIME_L1,
                        esp_rise[0] if len(esp_rise) > 0 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_RISE_TIME_L2,
                    default=self._config.get(CONF_ESPHOME_RISE_TIME_L2,
                        esp_rise[1] if len(esp_rise) > 1 else "")): _ent_sel,
                vol.Optional(CONF_ESPHOME_RISE_TIME_L3,
                    default=self._config.get(CONF_ESPHOME_RISE_TIME_L3,
                        esp_rise[2] if len(esp_rise) > 2 else "")): _ent_sel,
            }),
            errors=errors,
            description_placeholders={
                "tip": ("Installeer eerst de CloudEMS NILM Meter op uw ESP32-S3. "
                        "Zie esphome/README.md voor schema en YAML. "
                        "L1 is verplicht; L2 en L3 zijn optioneel voor 3-fase aansluitingen."),
            },
        )

    async def _prefill_from_dsmr_integration(self):
        """Pre-fill grid sensor config vanuit de HA DSMR/P1-integratie.

        Zoekt de beste import/export/netto sensor van het gedetecteerde platform
        en slaat die op als suggestie zodat de gebruiker ze kan bevestigen.
        """
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)
        if not self._suggestions:
            self._suggestions = _detect_sensors(self.hass, phase_count)

        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)

            # Verzamel alle sensor-entiteiten van bekende DSMR-platforms
            dsmr_sensors: list[str] = []
            for entry in ent_reg.entities.values():
                if entry.domain == "sensor" and entry.platform in DSMR_HA_PLATFORMS:
                    dsmr_sensors.append(entry.entity_id)

            if not dsmr_sensors:
                return  # No platform-sensors — suggestions blijven als ze zijn

            # Import/export keywords voor DSMR
            import_kws = ["power_delivered", "net_power_import", "power_import", "levering",
                          "consume", "afname", "currently_delivered", "active_power_positive"]
            export_kws = ["power_returned", "net_power_export", "power_export", "teruglevering",
                          "feed", "return", "currently_returned", "active_power_negative"]

            best_import = _best(dsmr_sensors, import_kws)
            best_export = _best(dsmr_sensors, export_kws)

            # Netto sensor: als geen aparte import/export, zoek gecombineerde sensor
            net_kws = ["active_power_w", "net_power", "power_usage", "current_power",
                       "electricity_power", "p1_active_power"]
            best_net = _best(dsmr_sensors, net_kws)

            if best_import and best_export:
                self._config[CONF_USE_SEPARATE_IE] = True
                self._config.setdefault(CONF_IMPORT_SENSOR, best_import)
                self._config.setdefault(CONF_EXPORT_SENSOR, best_export)
                self._suggestions[CONF_IMPORT_SENSOR] = best_import
                self._suggestions[CONF_EXPORT_SENSOR] = best_export
            elif best_net:
                self._config[CONF_USE_SEPARATE_IE] = False
                self._config.setdefault(CONF_GRID_SENSOR, best_net)
                self._suggestions[CONF_GRID_SENSOR] = best_net
            elif best_import:
                # Alleen import gevonden — gebruik als netto sensor
                self._config.setdefault(CONF_GRID_SENSOR, best_import)
                self._suggestions[CONF_GRID_SENSOR] = best_import

            _LOGGER.info(
                "CloudEMS DSMR auto-prefill: import=%s export=%s net=%s",
                best_import, best_export, best_net,
            )
        except Exception as exc:
            _LOGGER.warning("CloudEMS DSMR prefill mislukt: %s", exc)

    # ── 4. Grid sensors ───────────────────────────────────────────────────────
    async def async_step_grid_sensors(self, user_input=None):
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)
        errors: dict = {}
        if user_input is not None:
            # Validatie is nooit blokkerend — gebruiker weet zelf welke sensor correct is
            for _sensor_key in (CONF_GRID_SENSOR, CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR):
                _eid = user_input.get(_sensor_key)
                _warn = _validate_power_sensor(self.hass, _eid) if _eid else None
                if _warn:
                    _LOGGER.warning("CloudEMS netsensor '%s' mogelijk geen W/kW — doorgaan op verzoek gebruiker", _eid)
            # Altijd doorgaan — geen harde blokkade op sensor-type
            self._config.update(user_input)
            if phase_count == 3:
                return await self.async_step_phase_sensors()
            return await self.async_step_generator() if self._advanced() else await self.async_step_solar_ev()

        if not self._suggestions:
            self._suggestions = _detect_sensors(self.hass, phase_count)
        s = self._suggestions
        use_sep = self._config.get(CONF_USE_SEPARATE_IE, False)

        schema: dict = {vol.Optional(CONF_USE_SEPARATE_IE, default=use_sep): bool}
        if not use_sep:
            schema[vol.Optional(CONF_GRID_SENSOR,   description={"suggested_value": self._config.get(CONF_GRID_SENSOR)   or s.get(CONF_GRID_SENSOR)})]   = _ent()
        else:
            schema[vol.Optional(CONF_IMPORT_SENSOR, description={"suggested_value": self._config.get(CONF_IMPORT_SENSOR) or s.get(CONF_IMPORT_SENSOR)})] = _ent()
            schema[vol.Optional(CONF_EXPORT_SENSOR, description={"suggested_value": self._config.get(CONF_EXPORT_SENSOR) or s.get(CONF_EXPORT_SENSOR)})] = _ent()
        schema[vol.Optional(CONF_MAINS_VOLTAGE, default=DEFAULT_MAINS_VOLTAGE_V)] = \
            vol.All(vol.Coerce(float), vol.Range(min=100, max=480))

        # Note: DSMR5 per-fase teruglevering sensoren worden geconfigureerd in de
        # fase-sensoren stap (phase_sensors), niet hier. Zo vermijden we duplicaten.

        return self.async_show_form(
            step_id="grid_sensors",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/grid_sensors.svg",
                "phase_count": str(phase_count),
                "detected": str(sum(1 for v in s.values() if v)),
                "mains_voltage": str(DEFAULT_MAINS_VOLTAGE_V),
            },
        )

    # ── 3b. Per-phase sensors (Advanced only) ─────────────────────────────────
    async def async_step_phase_sensors(self, user_input=None):
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)
        errors: dict = {}

        if user_input is not None:
            # Validate UOM van fase-power sensoren: alleen W of kW toegestaan
            power_keys = [CONF_POWER_L1, CONF_POWER_L2, CONF_POWER_L3,
                          "power_sensor_l1_export", "power_sensor_l2_export", "power_sensor_l3_export"]
            for pk in power_keys:
                eid = user_input.get(pk, "")
                if not eid:
                    continue
                try:
                    state = self.hass.states.get(eid)
                    if state:
                        uom = state.attributes.get("unit_of_measurement", "")
                        if uom and uom.upper() not in ("W", "KW", "WATT", "KILOWATT"):
                            errors[pk] = "invalid_power_unit"
                except Exception:
                    pass

            if not errors:
                self._config.update(user_input)
                return await self.async_step_generator() if self._advanced() else await self.async_step_solar_ev()

        s = self._suggestions
        def _sv(key):
            """Return existing config value, falling back to auto-detected suggestion."""
            return self._config.get(key) or s.get(key)

        schema: dict = {
            vol.Optional(CONF_PHASE_SENSORS+"_L1", description={"suggested_value": _sv(CONF_PHASE_SENSORS+"_L1")}): _ent(),
            vol.Optional(CONF_VOLTAGE_L1,          description={"suggested_value": _sv(CONF_VOLTAGE_L1)}):          _ent(),
            vol.Optional(CONF_POWER_L1,            description={"suggested_value": _sv(CONF_POWER_L1)}):            _ent(),
        }
        if phase_count == 3:
            for k in [
                CONF_PHASE_SENSORS+"_L2", CONF_VOLTAGE_L2, CONF_POWER_L2,
                CONF_PHASE_SENSORS+"_L3", CONF_VOLTAGE_L3, CONF_POWER_L3,
            ]:
                schema[vol.Optional(k, description={"suggested_value": _sv(k)})] = _ent()
        # DSMR5: add per-phase export sensors (bidirectional meters)
        for exp_key in ("power_sensor_l1_export", "power_sensor_l2_export", "power_sensor_l3_export"):
            sv = self._config.get(exp_key) or s.get(exp_key)
            schema[vol.Optional(exp_key, description={"suggested_value": sv})] = _ent()

        return self.async_show_form(
            step_id="phase_sensors",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/phase_sensors.svg",
                    "phase_count": str(phase_count)},
        )

    # ── 4. EV Charger ──────────────────────────────────────────────────────────
    async def async_step_solar_ev(self, user_input=None):
        s = self._suggestions
        if user_input is not None:
            self._config.update(user_input)
            if self._advanced():
                return await self.async_step_inverter_count()
            return await self.async_step_managed_battery()
        # In advanced mode the solar sensor is configured per-inverter in the
        # inverter_detail loop that follows, so we skip it here to avoid confusion.
        # Similarly, the battery sensor is configured per-battery in the battery loop.
        schema: dict = {}
        if not self._advanced():
            schema[vol.Optional(CONF_SOLAR_SENSOR,   description={"suggested_value": self._config.get(CONF_SOLAR_SENSOR)   or s.get(CONF_SOLAR_SENSOR)})]   = _ent()
            schema[vol.Optional(CONF_BATTERY_SENSOR, description={"suggested_value": self._config.get(CONF_BATTERY_SENSOR) or s.get(CONF_BATTERY_SENSOR)})] = _ent()
        return self.async_show_form(
            step_id="solar_ev",
            data_schema=vol.Schema({
                **schema,
                vol.Optional(CONF_EV_CHARGER_ENTITY, description={"suggested_value": self._config.get(CONF_EV_CHARGER_ENTITY)}): _ent(["number","input_number"]),
            }),
        )

    # ── 4b. Inverter count (Advanced) ─────────────────────────────────────────
    async def async_step_inverter_count(self, user_input=None):
        if user_input is not None:
            self._inv_count = int(user_input.get(CONF_INVERTER_COUNT, 0))
            # Save existing configs for pre-fill BEFORE clearing the list
            self._existing_inv_cfgs = list(self._config.get(CONF_INVERTER_CONFIGS, []))
            self._config[CONF_INVERTER_COUNT]   = self._inv_count
            self._config[CONF_INVERTER_CONFIGS] = []
            self._inv_step = 0
            return await self.async_step_inverter_detail() if self._inv_count > 0 else await self.async_step_managed_battery()
        existing_inv_count = str(len(self._config.get(CONF_INVERTER_CONFIGS, [])))
        return self.async_show_form(
            step_id="inverter_count",
            data_schema=vol.Schema({vol.Required(CONF_INVERTER_COUNT, default=existing_inv_count): _inverter_count_selector()}),
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/solar_ev.svg",
                    "docs_url": SUPPORT_URL},
        )

    # ── 4c. Inverter detail loop (Advanced) ───────────────────────────────────
    async def async_step_inverter_detail(self, user_input=None):
        i = self._inv_step + 1
        # Pre-fill from saved existing configs (before the list was cleared in inverter_count)
        existing_cfgs = getattr(self, "_existing_inv_cfgs", []) or self._config.get(CONF_INVERTER_CONFIGS, [])
        existing = existing_cfgs[self._inv_step] if self._inv_step < len(existing_cfgs) else {}
        if user_input is not None:
            self._config[CONF_INVERTER_CONFIGS].append({
                "entity_id":      user_input.get("inv_sensor"),
                "control_entity": user_input.get("inv_control", ""),
                "label":          user_input.get("inv_label", f"Inverter {i}"),
                "priority":       i,
                "min_power_pct":  float(user_input.get("inv_min_pct", 0.0)),
                "azimuth_deg":    user_input.get("inv_azimuth") or None,
                "tilt_deg":       user_input.get("inv_tilt") or None,
                "rated_power_w":  float(user_input.get("inv_rated_power", 0)) or None,

            })
            self._inv_step += 1
            if self._inv_step < self._inv_count:
                return await self.async_step_inverter_detail()
            if self._config[CONF_INVERTER_CONFIGS]:
                self._config[CONF_ENABLE_MULTI_INVERTER] = True
            self._came_from_advanced_battery = True
            return await self.async_step_managed_battery()
        return self.async_show_form(
            step_id="inverter_detail",
            data_schema=vol.Schema({
                # ── Verplicht ─────────────────────────────────────────────────
                vol.Required("inv_sensor", description={"suggested_value": existing.get("entity_id") or None}): _ent(),
                # ── Identificatie ─────────────────────────────────────────────
                vol.Optional("inv_label",       default=existing.get("label", f"Omvormer {i}")): str,
                vol.Optional("inv_rated_power", default=float(existing.get("rated_power_w") or 0)): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                # ── Oriëntatie (leeg laten = zelf leren) ──────────────────────
                vol.Optional("inv_azimuth", description={"suggested_value": existing.get("azimuth_deg")}): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=360))),
                vol.Optional("inv_tilt",    description={"suggested_value": existing.get("tilt_deg")}):    vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=90))),
                # ── Begrenzing ────────────────────────────────────────────────
                vol.Optional("inv_min_pct", default=float(existing.get("min_power_pct", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
                vol.Optional("inv_control", default=existing.get("control_entity") or vol.UNDEFINED): _ent(["switch","number"]),
            }),
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/inverter_detail.svg",
                    
                "inverter_num": str(i), "total": str(self._inv_count),
                "azimuth_tip": "0=N 90=E 180=S 270=W — leeg = zelf leren",
                "tilt_tip":    "0=plat 90=verticaal — leeg = zelf leren",
            },
        )

    # ── 4c-bis. Managed battery provider detection ───────────────────────────
    async def async_step_managed_battery(self, user_input=None):
        """
        Wizard-stap: geeft melding als een leverancier-gebonden batterij-
        integratie gedetecteerd is maar nog niet geconfigureerd in CloudEMS.
        Biedt opt-in setup per provider.
        Wordt getoond vóór battery_count / battery_detail als ≥1 provider gevonden.
        Wordt ook getoond als er 0 handmatige batterijen zijn.
        """
        from .energy_manager.battery_provider import BatteryProviderRegistry
        import importlib
        # Zorg dat providers geregistreerd zijn
        try:
            importlib.import_module(".energy_manager.zonneplan_bridge", package=__name__.rsplit(".", 1)[0])
        except Exception:
            pass

        # Detecteer providers (tijdelijk, zonder config — alleen detectie)
        tmp_registry = BatteryProviderRegistry(self.hass, self._config)
        await tmp_registry.async_setup()
        hints = tmp_registry.get_wizard_hints()
        unconfigured = [h for h in hints if h.detected and not h.configured]

        if user_input is not None:
            # Savet-in keuzes op
            for h in hints:
                key_en = f"{h.provider_id}_enabled"
                if key_en in user_input:
                    self._config[key_en] = user_input[key_en]
                # Provider-specifieke opties (restore, soc-grenzen, etc.)
                for field_def in h.config_fields:
                    k = field_def["key"]
                    if k in user_input:
                        self._config[k] = user_input[k]

            # Ga door naar handmatige batterij-setup of features
            if self._advanced():
                return await self.async_step_battery_count()
            return await self.async_step_price_provider()

        # No providers → stap overslaan
        if not unconfigured:
            if self._advanced():
                return await self.async_step_battery_count()
            return await self.async_step_price_provider()

        # Build schema op basis van wat er gedetecteerd is
        schema: dict = {}
        placeholders: dict = {}

        for h in unconfigured:
            # Hoofd opt-in toggle per provider
            schema[vol.Optional(f"{h.provider_id}_enabled", default=False)] = bool
            # Provider-specifieke velden (restore_mode, soc-grenzen, etc.)
            for field_def in h.config_fields:
                k = field_def["key"]
                if k == f"{h.provider_id}_enabled":
                    continue  # al hierboven
                t = field_def.get("type", "bool")
                default = field_def.get("default")
                if t == "bool":
                    schema[vol.Optional(k, default=bool(default))] = bool
                elif t in ("int", "float"):
                    mn = field_def.get("min", 0)
                    mx = field_def.get("max", 9999)
                    coerce = int if t == "int" else float
                    schema[vol.Optional(k, default=coerce(default))] = vol.All(
                        vol.Coerce(coerce), vol.Range(min=mn, max=mx)
                    )

            # Zet detectie-info in placeholders
            placeholders[f"{h.provider_id}_label"]      = h.provider_label
            placeholders[f"{h.provider_id}_warning"]    = h.warning
            placeholders[f"{h.provider_id}_suggestion"] = h.suggestion
            placeholders[f"{h.provider_id}_description"]= h.description

        # Generieke placeholders voor de template
        provider_names = ", ".join(h.provider_label for h in unconfigured)
        placeholders["detected_providers"] = provider_names
        placeholders["provider_count"]     = str(len(unconfigured))

        return self.async_show_form(
            step_id="managed_battery",
            data_schema=vol.Schema(schema),
            description_placeholders=placeholders,
        )

    # ── 4d. Battery count (Advanced) ─────────────────────────────────────────
    async def async_step_battery_count(self, user_input=None):
        if user_input is not None:
            self._bat_count = int(user_input.get(CONF_BATTERY_COUNT, 0))
            # Save existing configs for pre-fill BEFORE clearing the list
            self._existing_bat_cfgs = list(self._config.get(CONF_BATTERY_CONFIGS, []))
            self._config[CONF_BATTERY_COUNT]   = self._bat_count
            self._config[CONF_BATTERY_CONFIGS] = []
            self._bat_step = 0
            if self._bat_count > 0:
                return await self.async_step_battery_detail()
            self._config[CONF_ENABLE_MULTI_BATTERY] = False
            # features was already completed earlier in the wizard — go forward to climate
            return await self.async_step_climate()
        existing_bat_count = str(len(self._config.get(CONF_BATTERY_CONFIGS, [])) or int(self._config.get(CONF_BATTERY_COUNT, 0)))
        return self.async_show_form(
            step_id="battery_count",
            data_schema=vol.Schema({
                vol.Required(CONF_BATTERY_COUNT, default=existing_bat_count): _inverter_count_selector(),
            }),
            description_placeholders={"docs_url": SUPPORT_URL},
        )

    # ── 4e. Battery detail loop (Advanced) ───────────────────────────────────
    async def async_step_battery_detail(self, user_input=None):
        i = self._bat_step + 1
        existing_bat_cfgs = getattr(self, "_existing_bat_cfgs", []) or self._config.get(CONF_BATTERY_CONFIGS, [])
        if user_input is not None:
            self._config[CONF_BATTERY_CONFIGS].append({
                "power_sensor":     user_input.get("bat_power_sensor"),
                "soc_sensor":       user_input.get("bat_soc_sensor"),
                "capacity_kwh":     float(user_input.get("bat_capacity_kwh", 0.0)),
                "max_charge_w":     float(user_input.get("bat_max_charge_w", 0.0)),
                "max_discharge_w":  float(user_input.get("bat_max_discharge_w", 0.0)),
                "charge_entity":    user_input.get("bat_charge_entity", ""),
                "discharge_entity": user_input.get("bat_discharge_entity", ""),
                "label":            user_input.get("bat_label", f"Batterij {i}"),
                "priority":         i,
            })
            self._bat_step += 1
            if self._bat_step < self._bat_count:
                return await self.async_step_battery_detail()
            if self._config[CONF_BATTERY_CONFIGS]:
                self._config[CONF_ENABLE_MULTI_BATTERY] = True
            return await self.async_step_shutter_count()
        existing_bat = existing_bat_cfgs[self._bat_step] if self._bat_step < len(existing_bat_cfgs) else {}
        return self.async_show_form(
            step_id="battery_detail",
            data_schema=vol.Schema({
                vol.Required("bat_power_sensor", description={"suggested_value": existing_bat.get("power_sensor")}): _ent(),
                vol.Optional("bat_soc_sensor",   default=existing_bat.get("soc_sensor") or vol.UNDEFINED):   _ent(),
                vol.Optional("bat_capacity_kwh",    default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional("bat_max_charge_w",    default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_max_discharge_w", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_charge_entity"):    _ent(["number", "input_number"]),
                vol.Optional("bat_discharge_entity"): _ent(["number", "input_number"]),
                vol.Optional("bat_label", default=f"Batterij {i}"): str,
            }),
            description_placeholders={
                "battery_num": str(i),
                "total":       str(self._bat_count),
                "diagram_url": "/local/cloudems/diagrams/battery_detail.svg",
            },
        )

    # ── 4f. Shutter count ─────────────────────────────────────────────────────
    async def async_step_shutter_count(self, user_input=None):
        # Overkiz auto-detect
        overkiz_covers = await self._detect_overkiz_covers()

        if user_input is not None:
            self._shutter_count = int(user_input.get(CONF_SHUTTER_COUNT, 0))
            self._existing_shutter_cfgs = list(self._config.get(CONF_SHUTTER_CONFIGS, []))
            self._config[CONF_SHUTTER_COUNT]   = self._shutter_count
            self._config[CONF_SHUTTER_CONFIGS] = []
            self._config["shutter_global_smoke_sensor"] = user_input.get("shutter_global_smoke_sensor") or ""
            self._shutter_step = 0
            self._overkiz_prefill = overkiz_covers
            if self._shutter_count == 0 and overkiz_covers:
                self._shutter_count = len(overkiz_covers)
                self._config[CONF_SHUTTER_COUNT] = self._shutter_count
            if self._shutter_count > 0:
                return await self.async_step_shutter_detail()
            return await self.async_step_climate()

        existing_count = str(self._config.get(CONF_SHUTTER_COUNT, DEFAULT_SHUTTER_COUNT))
        if existing_count == "0" and overkiz_covers:
            existing_count = str(len(overkiz_covers))
        opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(21)]
        if overkiz_covers:
            names = ", ".join(c["label"] for c in overkiz_covers[:4])
            overkiz_msg = f"Overkiz/Somfy gevonden: {len(overkiz_covers)} rolluik(en) — {names}"
        else:
            overkiz_msg = "Geen Overkiz/Somfy integratie gevonden. Voeg deze toe voor automatische detectie."
        return self.async_show_form(
            step_id="shutter_count",
            data_schema=vol.Schema({
                vol.Required(CONF_SHUTTER_COUNT, default=existing_count): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opts, mode="dropdown")
                ),
                vol.Optional(
                    "shutter_global_smoke_sensor",
                    default=self._config.get("shutter_global_smoke_sensor", "") or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="smoke", multiple=False)
                ),
            }),
            description_placeholders={"overkiz_found": overkiz_msg},
        )

    async def _detect_overkiz_covers(self) -> list:
        """Detecteer Overkiz/Somfy cover entiteiten via HA entity registry."""
        try:
            from homeassistant.helpers import entity_registry as er, area_registry as ar
            ent_reg  = er.async_get(self.hass)
            area_reg = ar.async_get(self.hass)
            covers = []
            for entry in ent_reg.entities.values():
                if entry.domain != "cover":
                    continue
                if entry.platform not in ("overkiz", "somfy", "somfy_mylink", "tahoma"):
                    continue
                if entry.disabled:
                    continue
                area_id   = entry.area_id or ""
                area_name = ""
                if area_id:
                    area = area_reg.areas.get(area_id)
                    if area:
                        area_name = area.name
                label = entry.original_name or entry.entity_id.split(".")[-1].replace("_", " ").title()
                covers.append({"entity_id": entry.entity_id, "label": label,
                                "area_id": area_id, "area_name": area_name})
            return covers
        except Exception:
            return []

    def _get_area_for_entity(self, entity_id: str) -> tuple:
        """Geef (area_id, area_name) terug voor een entity."""
        try:
            from homeassistant.helpers import entity_registry as er, area_registry as ar
            ent_reg  = er.async_get(self.hass)
            area_reg = ar.async_get(self.hass)
            entry = ent_reg.async_get(entity_id)
            if entry and entry.area_id:
                area = area_reg.areas.get(entry.area_id)
                return entry.area_id, (area.name if area else "")
        except Exception:
            pass
        return "", ""

    def _suggest_temp_sensor_for_cover(self, cover_entity_id: str) -> str:
        """Geef de beste temperatuursensor in dezelfde ruimte als het rolluik.

        Voorkeursvolgorde:
        1. sensor.* met device_class=temperature in dezelfde ruimte
        2. climate.* in dezelfde ruimte (via current_temperature attribuut)
        Buitensensoren (outdoor / buiten / extern) worden overgeslagen.
        Geeft '' terug als niets gevonden.
        """
        if not cover_entity_id:
            return ""
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg  = er.async_get(self.hass)
            cover_entry = ent_reg.async_get(cover_entity_id)
            if cover_entry is None or not cover_entry.area_id:
                return ""
            area_id = cover_entry.area_id
            candidates: list[str] = []
            climate_fallback: list[str] = []
            for entry in ent_reg.entities.values():
                if entry.area_id != area_id or entry.disabled:
                    continue
                eid   = entry.entity_id.lower()
                label = (entry.original_name or entry.entity_id).lower()
                skip_words = ("outdoor", "buiten", "outside", "extern", "external")
                if any(w in eid or w in label for w in skip_words):
                    continue
                if entry.domain == "sensor":
                    dc = entry.device_class or entry.original_device_class or ""
                    if dc == "temperature":
                        candidates.append(entry.entity_id)
                elif entry.domain == "climate":
                    # Klimaatregelaar als fallback — coordinator leest current_temperature
                    climate_fallback.append(entry.entity_id)
            if candidates:
                return candidates[0]
            if climate_fallback:
                return climate_fallback[0]
        except Exception:
            pass
        return ""

    # ── 4g. Shutter detail loop ───────────────────────────────────────────────
    async def async_step_shutter_detail(self, user_input=None):
        i = self._shutter_step + 1
        existing_cfgs   = getattr(self, "_existing_shutter_cfgs", []) or self._config.get(CONF_SHUTTER_CONFIGS, [])
        overkiz_prefill = getattr(self, "_overkiz_prefill", [])

        if user_input is not None:
            cover_eid = user_input.get("shutter_entity", "")
            area_id, area_name = self._get_area_for_entity(cover_eid)
            self._config[CONF_SHUTTER_CONFIGS].append({
                "entity_id":       cover_eid,
                "label":           user_input.get("shutter_label", f"Rolluik {i}"),
                "area_id":         area_id,
                "area_name":       area_name,
                "group":           user_input.get("shutter_group", ""),
                "temp_sensor":     user_input.get("shutter_temp_sensor") or "",
                "auto_thermal":    user_input.get("shutter_auto_thermal", True),
                "auto_solar_gain": user_input.get("shutter_auto_solar_gain", True),
                "auto_overheat":   user_input.get("shutter_auto_overheat", True),
                "night_close_time":  user_input.get("shutter_night_close", "23:00"),
                "morning_open_time": user_input.get("shutter_morning_open", "07:30"),
                "default_setpoint":  float(user_input.get("shutter_default_setpoint", 20.0)),
                "smoke_sensor":    user_input.get("shutter_smoke_sensor") or "",
            })
            self._shutter_step += 1
            if self._shutter_step < self._shutter_count:
                return await self.async_step_shutter_detail()
            return await self.async_step_climate()

        existing = {}
        if self._shutter_step < len(existing_cfgs):
            existing = existing_cfgs[self._shutter_step]
        elif self._shutter_step < len(overkiz_prefill):
            existing = overkiz_prefill[self._shutter_step]

        # Stel temperatuursensor voor op basis van de ruimte van de cover entity
        cover_eid_hint = existing.get("entity_id", "")
        suggested_temp = existing.get("temp_sensor") or self._suggest_temp_sensor_for_cover(cover_eid_hint)
        area_hint = existing.get("area_name", "")

        temp_sensor_schema = (
            vol.Optional(
                "shutter_temp_sensor",
                description={"suggested_value": suggested_temp},
            )
            if suggested_temp
            else vol.Optional("shutter_temp_sensor")
        )

        return self.async_show_form(
            step_id="shutter_detail",
            data_schema=vol.Schema({
                vol.Required("shutter_entity", description={"suggested_value": cover_eid_hint}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
                vol.Optional("shutter_label", default=existing.get("label", f"Rolluik {i}")): str,
                vol.Optional("shutter_group", default=existing.get("group", "")): str,
                temp_sensor_schema: selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "climate"],
                        device_class="temperature",
                        multiple=False,
                    )
                ),
                vol.Optional("shutter_auto_thermal",    default=existing.get("auto_thermal", True)):    bool,
                vol.Optional("shutter_auto_solar_gain", default=existing.get("auto_solar_gain", True)): bool,
                vol.Optional("shutter_auto_overheat",   default=existing.get("auto_overheat", True)):   bool,
                vol.Optional("shutter_night_close",    default=existing.get("night_close_time", "23:00")):  str,
                vol.Optional("shutter_morning_open",   default=existing.get("morning_open_time", "07:30")): str,
                vol.Optional("shutter_default_setpoint", default=existing.get("default_setpoint", 20.0)):   vol.Coerce(float),
                vol.Optional("shutter_smoke_sensor", default=existing.get("smoke_sensor", "") or vol.UNDEFINED): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor", device_class="smoke", multiple=False)),
            }),
            description_placeholders={
                "shutter_num":  str(i),
                "total":        str(self._shutter_count),
                "area_hint":    f" (kamer: {area_hint})" if area_hint else "",
                "sensor_hint":  f" • gevonden sensor: {suggested_temp}" if suggested_temp else "",
            },
        )

    # ── 5. Features ───────────────────────────────────────────────────────────
    async def async_step_features(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_peak_config() if user_input.get(CONF_PEAK_SHAVING_ENABLED) else await self.async_step_price_provider()

        phase_count = self._config.get(CONF_PHASE_COUNT, 1)
        schema: dict = {
            vol.Optional(CONF_DYNAMIC_LOADING, default=False): bool,
            vol.Optional(CONF_DYNAMIC_LOAD_THRESHOLD, default=DEFAULT_DYNAMIC_LOAD_THRESHOLD):
                vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=1.0)),
            vol.Optional(CONF_COST_TRACKING, default=True): bool,
            vol.Optional(CONF_PEAK_SHAVING_ENABLED, default=False): bool,
            vol.Optional(CONF_BATTERY_SCHEDULER_ENABLED, default=False): bool,
            vol.Optional(CONF_CONGESTION_ENABLED, default=False): bool,
            vol.Optional(CONF_BATTERY_DEGRADATION_ENABLED, default=False): bool,
            vol.Optional("price_alert_high_eur_kwh", default=0.30):
                vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
            vol.Optional("nilm_min_confidence", default=0.65):
                vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        }
        if phase_count == 3:
            schema[vol.Optional(CONF_PHASE_BALANCE, default=True)] = bool
            schema[vol.Optional(CONF_PHASE_BALANCE_THRESHOLD, default=DEFAULT_PHASE_BALANCE_THRESHOLD)] = \
                vol.All(vol.Coerce(float), vol.Range(min=1, max=20))
        return self.async_show_form(step_id="features", data_schema=vol.Schema(schema))

    # ── 5b. Peak shaving config ────────────────────────────────────────────────
    async def async_step_peak_config(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_price_provider()
        return self.async_show_form(
            step_id="peak_config",
            data_schema=vol.Schema({
                vol.Optional(CONF_PEAK_SHAVING_LIMIT_W, default=DEFAULT_PEAK_SHAVING_LIMIT_W):
                    vol.All(vol.Coerce(float), vol.Range(min=500, max=50000)),
                vol.Optional(CONF_PEAK_SHAVING_ASSETS, default=[]):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch","number","input_boolean","light","climate"], multiple=True)),
            }),
        )

    # ── 5c. Prices & tax ─────────────────────────────────────────────────────
    async def async_step_prices(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            # Herlaad leverancier-opties als land gewijzigd is
            new_country = user_input.get(CONF_ENERGY_PRICES_COUNTRY)
            if new_country:
                self._config[CONF_ENERGY_PRICES_COUNTRY] = new_country
            return await self.async_step_gas_prices()
        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        suppliers = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"])
        sup_options = [
            selector.SelectOptionDict(value=k, label=v[0])
            for k, v in suppliers.items()
        ]
        return self.async_show_form(
            step_id="prices",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENERGY_PRICES_COUNTRY, default=country): _country_selector(),
                vol.Optional(CONF_PRICE_INCLUDE_TAX,  default=False): bool,
                vol.Optional(CONF_PRICE_INCLUDE_BTW,  default=False): bool,
                vol.Optional(CONF_SELECTED_SUPPLIER,  default="none"):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=sup_options, mode="dropdown")),
                vol.Optional(CONF_SUPPLIER_MARKUP, default=0.0):
                    vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.5)),
            }),
        )

    async def async_step_gas_prices(self, user_input=None):
        """🔥 Gas — optionele gasprijs configuratie (wizard stap)."""
        if user_input is not None:
            self._config.update({k: v for k, v in user_input.items() if v not in (None, vol.UNDEFINED, "")})
            return await self.async_step_ai_config() if self._advanced() else self._create()

        from .const import (
            CONF_GAS_SENSOR, CONF_GAS_PRICE_SENSOR, CONF_GAS_TTF_SENSOR,
            CONF_GAS_PRICE_FIXED, CONF_GAS_USE_TTF,
            CONF_GAS_SUPPLIER, CONF_GAS_NETBEHEERDER,
            DEFAULT_GAS_PRICE_EUR_M3, GAS_SUPPLIER_MARKUPS, GAS_NETBEHEERDERS,
            CONF_ENERGY_PRICES_COUNTRY,
        )
        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        data = self._config

        gas_suppliers = GAS_SUPPLIER_MARKUPS.get(country, GAS_SUPPLIER_MARKUPS["NL"])
        supplier_options = [
            selector.SelectOptionDict(value=k, label=v[0])
            for k, v in gas_suppliers.items()
        ]
        netbeheerders = GAS_NETBEHEERDERS.get(country, GAS_NETBEHEERDERS["NL"])
        netbeheerder_options = [
            selector.SelectOptionDict(value=k, label=f"{v[0]} ({v[1]:.4f} €/m³)")
            for k, v in netbeheerders.items()
        ]

        return self.async_show_form(
            step_id="gas_prices",
            data_schema=vol.Schema({
                vol.Optional(CONF_GAS_SENSOR,
                    default=data.get(CONF_GAS_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_GAS_PRICE_SENSOR,
                    default=data.get(CONF_GAS_PRICE_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_GAS_USE_TTF,
                    default=bool(data.get(CONF_GAS_USE_TTF, True))): selector.BooleanSelector(),
                vol.Optional(CONF_GAS_TTF_SENSOR,
                    default=data.get(CONF_GAS_TTF_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_GAS_PRICE_FIXED,
                    default=float(data.get(CONF_GAS_PRICE_FIXED, DEFAULT_GAS_PRICE_EUR_M3))):
                    vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
                vol.Optional(CONF_GAS_SUPPLIER,
                    default=data.get(CONF_GAS_SUPPLIER, "none")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=supplier_options, mode="dropdown"
                    )),
                vol.Optional(CONF_GAS_NETBEHEERDER,
                    default=data.get(CONF_GAS_NETBEHEERDER, "default")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=netbeheerder_options, mode="dropdown"
                    )),
            }),
            description_placeholders={
                "info": (
                    "Alle velden zijn optioneel — sla over als je geen gas hebt.\n\n"
                    "Gasprijs volgorde: (1) Prijssensor → (2) TTF Day-Ahead spotmarkt → (3) Vaste prijs.\n"
                    "CloudEMS rekent TTF automatisch om naar all-in consumentenprijs."
                )
            },
        )

    # ── 5b. Prijsleverancier koppeling (v4.5.2) ───────────────────────────────
    async def async_step_price_provider(self, user_input=None):
        """Optionele directe koppeling met energieleverancier voor realtime prijzen."""
        if user_input is not None:
            chosen = user_input.get(CONF_PRICE_PROVIDER, DEFAULT_PRICE_PROVIDER)
            self._config[CONF_PRICE_PROVIDER] = chosen
            # Credentials-stap als de gekozen provider dat vereist
            needed = PRICE_PROVIDER_CREDENTIALS.get(chosen, [])
            if needed:
                self._config["_price_provider_pending"] = chosen
                return await self.async_step_price_provider_credentials()
            # No credentials nodig → provider meteen registreren
            self._register_price_provider(chosen, {})
            # EPEX-gebaseerde providers → toon prijzen-stap (belasting, leverancier markup)
            if chosen in EPEX_BASED_PROVIDERS:
                return await self.async_step_prices()
            # Echte leverancier → prijs komt rechtstreeks van API, sla prijzen-stap over
            return await self.async_step_ai_config() if self._advanced() else self._create()

        provider_options = [
            selector.SelectOptionDict(value=k, label=v)
            for k, v in PRICE_PROVIDER_LABELS.items()
        ]
        return self.async_show_form(
            step_id="price_provider",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRICE_PROVIDER, default=DEFAULT_PRICE_PROVIDER):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=provider_options, mode="list"
                    )),
            }),
            description_placeholders={
                "info": (
                    "CloudEMS haalt standaard gratis EPEX dag-vooruit prijzen op. "
                    "Als je een dynamisch contract hebt bij een van onderstaande leveranciers, "
                    "kun je jouw persoonlijke tarieven (inclusief alle toeslagen) rechtstreeks koppelen."
                )
            },
        )

    async def async_step_price_provider_credentials(self, user_input=None):
        """Voer credentials in voor de gekozen prijsleverancier."""
        pending = self._config.get("_price_provider_pending", "")
        needed  = PRICE_PROVIDER_CREDENTIALS.get(pending, [])

        if user_input is not None:
            creds = {k: user_input.get(k, "") for k in needed}
            self._config.pop("_price_provider_pending", None)
            self._register_price_provider(pending, creds)
            # EPEX-gebaseerde providers → toon prijzen-stap
            if pending in EPEX_BASED_PROVIDERS:
                return await self.async_step_prices()
            # Echte leverancier → prijs komt van API, sla prijzen-stap over
            return await self.async_step_ai_config() if self._advanced() else self._create()

        label = PRICE_PROVIDER_LABELS.get(pending, pending)
        schema_fields = {}
        for field in needed:
            field_label = {
                "access_token": "API Token / Access Token",
                "api_key":      "API-sleutel",
                "username":     "E-mailadres / gebruikersnaam",
                "password":     "Wachtwoord",
            }.get(field, field)
            schema_fields[vol.Optional(field)] = str

        return self.async_show_form(
            step_id="price_provider_credentials",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={"provider_label": label},
        )

    def _register_price_provider(self, provider_type: str, credentials: dict) -> None:
        """Voeg de prijsleverancier toe aan external_providers config."""
        if provider_type in ("none", "", None):
            return
        existing: list = list(self._config.get(CONF_PROVIDERS, []))
        # Verwijder eventuele vorige prijs-provider registratie
        existing = [
            p for p in existing
            if p.get("_price_provider") is not True
        ]
        existing.append({
            "type":           provider_type,
            "label":          PRICE_PROVIDER_LABELS.get(provider_type, provider_type),
            "credentials":    credentials,
            "_price_provider": True,  # markering zodat we hem later kunnen herkennen
        })
        self._config[CONF_PROVIDERS] = existing

    # ── 6. AI & NILM provider ─────────────────────────────────────────────────
    async def async_step_ai_config(self, user_input=None):
        if user_input is not None:
            provider = user_input.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
            self._config.update(user_input)
            # Back-compat: set ollama_enabled flag
            self._config[CONF_OLLAMA_ENABLED] = (provider == AI_PROVIDER_OLLAMA)
            if provider == AI_PROVIDER_OLLAMA:
                return await self.async_step_ollama_config()
            return await self.async_step_advanced() if self._advanced() else await self.async_step_climate()

        return self.async_show_form(
            step_id="ai_config",
            data_schema=vol.Schema({
                vol.Required(CONF_AI_PROVIDER, default=AI_PROVIDER_NONE): _ai_provider_selector(),
                vol.Optional(CONF_CLOUD_API_KEY): str,
                vol.Optional(CONF_NILM_CONFIDENCE, default=DEFAULT_NILM_CONFIDENCE):
                    vol.All(vol.Coerce(float), vol.Range(min=0.3, max=0.99)),
            }),
            description_placeholders={"premium_url": "https://cloudems.eu/premium"},
        )

    # ── 6b. Ollama settings ───────────────────────────────────────────────────
    async def async_step_ollama_config(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_advanced() if self._advanced() else await self.async_step_climate()
        return self.async_show_form(
            step_id="ollama_config",
            data_schema=vol.Schema({
                vol.Optional(CONF_OLLAMA_HOST,  default=DEFAULT_OLLAMA_HOST): str,
                vol.Optional(CONF_OLLAMA_PORT,  default=DEFAULT_OLLAMA_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_OLLAMA_MODEL, default=DEFAULT_OLLAMA_MODEL): str,
            }),
        )

    # ── 7. Advanced options (P1) — gaat nu via slimme auto-detectie ───────────
    async def async_step_advanced(self, user_input=None):
        """Detecteer P1-bron automatisch; sla toggle-stap over.

        Als grid_sensors al gedaan is (CONF_GRID_SENSOR of CONF_IMPORT_SENSOR gezet),
        sla dan P1-config over om te voorkomen dat de wizard teruglust naar eerder
        geconfigureerde stappen.
        """
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_p1_config() if user_input.get(CONF_P1_ENABLED) else await self.async_step_climate()
        # Skip P1 config if grid sensors were already configured earlier in this wizard run
        _grid_done = bool(
            self._config.get(CONF_GRID_SENSOR)
            or self._config.get(CONF_IMPORT_SENSOR)
            or self._config.get(CONF_DSMR_SOURCE)
        )
        if _grid_done:
            return await self.async_step_climate()
        # First time through: go to P1 config
        return await self.async_step_p1_config()

    async def async_step_p1_config(self, user_input=None):
        """
        Slimme P1-configuratiestap.

        Prioriteitsvolgorde (volledig automatisch):
          1. Detecteer bestaande DSMR / HomeWizard / P1-monitor entities
             → gevonden: sla IP-invoer over, gebruik ze direct
          2. Detecteer HomeWizard P1 via mDNS/Zeroconf (LAN-scan)
             → gevonden: IP al ingevuld als suggestie
          3. Toon optioneel IP-veld (leeg laten = geen directe verbinding)
             → gebruiker hoeft NIETS in te vullen als stap 1 of 2 werkte

        In alle gevallen geldt: als niets gevonden EN geen IP ingevuld,
        werkt CloudEMS gewoon door zonder directe P1 (geen foutmelding).
        """
        if user_input is not None:
            self._config.update(user_input)
            # Sla P1 als enabled op als er een host is of auto-bron gevonden
            host = (user_input.get(CONF_P1_HOST) or "").strip()
            auto = self._config.get("_p1_auto_source", "")
            self._config[CONF_P1_ENABLED] = bool(host or auto)
            self._config.pop("_p1_auto_source", None)
            # If we vanuit de wizard DSMR-bron "direct" kwamen, terug naar grid_sensors
            if self._config.pop("_p1_direct_from_wizard", False):
                return await self.async_step_grid_sensors()
            return await self.async_step_climate()

        # ── Auto-detectie ───────────────────────────────────────────────────
        auto_source  = ""
        auto_host    = ""
        auto_info    = ""

        # 1. Bekende P1 HA-entiteiten aanwezig?
        _P1_PROBE_ENTITIES = [
            "sensor.dsmr_reading_electricity_currently_delivered",
            "sensor.homewizard_p1_active_power_w",
            "sensor.p1_active_power",
            "sensor.slimmelezer_power_delivered",
            "sensor.electricity_power_usage",
        ]
        for eid in _P1_PROBE_ENTITIES:
            state = self.hass.states.get(eid)
            if state and state.state not in ("unavailable", "unknown", ""):
                integration = eid.split("_")[0].replace("sensor.", "")
                auto_source = eid
                auto_info   = f"✅ P1-data gevonden via bestaande integratie ({eid})"
                _LOGGER.info("P1 auto-detect: %s", eid)
                break

        # 2. HomeWizard P1 via mDNS (alleen als nog geen bron)
        if not auto_source:
            try:
                from homeassistant.components import zeroconf as _zc
                aiozc = await _zc.async_get_async_instance(self.hass)
                records = aiozc.async_get_service_info("_hwenergy._tcp.local.", timeout=2.0) \
                    if hasattr(aiozc, "async_get_service_info") else None
                if records and records.addresses:
                    import socket
                    auto_host = socket.inet_ntoa(records.addresses[0])
                    auto_info = f"✅ HomeWizard P1 gevonden op {auto_host} (via mDNS)"
                    _LOGGER.info("P1 mDNS: HomeWizard op %s", auto_host)
            except Exception:
                pass   # mDNS niet beschikbaar of timeout -- geen probleem

        # Bewaar auto-bron voor de next step
        if auto_source:
            self._config["_p1_auto_source"] = auto_source

        # ── Schema: alleen IP vragen; poort standaard verborgen ─────────────
        schema_dict: dict = {}
        if not auto_source:
            # No auto-bron → optioneel IP tonen (leeg = overslaan)
            schema_dict[vol.Optional(
                CONF_P1_HOST,
                description={"suggested_value": auto_host},
            )] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )

        schema = vol.Schema(schema_dict) if schema_dict else vol.Schema({
            vol.Optional("_skip"): bool   # dummy schema zodat form werkt
        })

        # Beschrijving aanpassen op basis van wat gevonden is
        if auto_source:
            description = (
                f"{auto_info}\n\n"
                "CloudEMS leest P1-data automatisch. "
                "Geen verdere configuratie nodig."
            )
        elif auto_host:
            description = (
                f"{auto_info}\n\n"
                "IP-adres al ingevuld. Klik op Volgende om te bevestigen.\n"
                "Of vul handmatig een ander IP in."
            )
        else:
            description = (
                "Vul het IP-adres in van je P1-gateway "
                "(HomeWizard Energy, SLIMMELEZER, P1ib, ...).\n\n"
                "**Geen P1-gateway?** Laat leeg — CloudEMS werkt ook zonder."
            )

        return self.async_show_form(
            step_id="p1_config",
            data_schema=schema,
            description_placeholders={
                "auto_info":   auto_info or "Geen P1-bron automatisch gevonden.",
                "diagram_url": "/local/cloudems/diagrams/p1_config.svg",
                "description": description,
            },
        )

    # ── 8. E-mail / SMTP ──────────────────────────────────────────────────────
    # ── Klimaat wizard ────────────────────────────────────────────────────────
    async def async_step_climate(self, user_input=None):
        """Klimaat keuzemenu: Zone Control (TRV/thermostaat) of Airco/WP EPEX."""
        if user_input is not None:
            mode = user_input.get("climate_mode", "none")
            self._config["climate_mode"] = mode
            if mode == "zones":
                return await self.async_step_climate_boiler()
            if mode == "epex":
                return await self.async_step_climate_epex_count()
            # none: beide uit
            self._config[CONF_CLIMATE_ENABLED] = False
            self._config[CONF_CLIMATE_EPEX_ENABLED] = False
            return await self.async_step_boiler_groups()

        # Bepaal huidige modus op basis van bestaande config
        ex = self._config
        if ex.get(CONF_CLIMATE_EPEX_ENABLED):
            current_mode = "epex"
        elif ex.get(CONF_CLIMATE_ENABLED):
            current_mode = "zones"
        else:
            current_mode = "none"

        return self.async_show_form(
            step_id="climate",
            data_schema=vol.Schema({
                vol.Required("climate_mode", default=current_mode): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="none",  label="🚫 Klimaat uitgeschakeld"),
                        selector.SelectOptionDict(value="zones", label="🏠 Zone Control (TRV / thermostaat per kamer)"),
                        selector.SelectOptionDict(value="epex",  label="❄️ Airco / Warmtepomp EPEX-sturing"),
                    ], mode="list")
                ),
            }),
            description_placeholders={
                "info": (
                    "**Zone Control** past virtuele thermostaten toe per kamer via HA area-indeling.\n\n"
                    "**Airco / WP EPEX** past kleine temperatuuroffsets toe op basis van de EPEX-spotprijs "
                    "— voorverwarmen in goedkope uren, zuiniger in dure uren. Ondersteunt meerdere apparaten."
                )
            },
        )

    async def async_step_climate_boiler(self, user_input=None):
        """Zone Control stap 1: CV-ketel entiteit + minimale zones."""
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_climate_zones()

        ex = self._config
        return self.async_show_form(
            step_id="climate_boiler",
            data_schema=vol.Schema({
                vol.Optional(CONF_CV_BOILER_ENTITY,
                             description={"suggested_value": ex.get(CONF_CV_BOILER_ENTITY, "")}):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch", "climate", "input_boolean"])),
                vol.Optional(CONF_CV_MIN_ZONES, default=ex.get(CONF_CV_MIN_ZONES, DEFAULT_CV_MIN_ZONES)):
                    vol.All(int, vol.Range(min=1, max=20)),
                vol.Optional(CONF_CV_MIN_ON_MIN, default=ex.get(CONF_CV_MIN_ON_MIN, DEFAULT_CV_MIN_ON_MIN)):
                    vol.All(int, vol.Range(min=1, max=60)),
                vol.Optional(CONF_CV_MIN_OFF_MIN, default=ex.get(CONF_CV_MIN_OFF_MIN, DEFAULT_CV_MIN_OFF_MIN)):
                    vol.All(int, vol.Range(min=1, max=60)),
                vol.Optional(CONF_CV_SUMMER_CUTOFF_C,
                             default=ex.get(CONF_CV_SUMMER_CUTOFF_C, DEFAULT_CV_SUMMER_CUTOFF_C)):
                    vol.All(vol.Coerce(float), vol.Range(min=10, max=30)),
            }),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/climate_zones.svg",
            },
        )

    async def async_step_climate_zones(self, user_input=None):
        """Zone Control stap 2: Zone-ontdekking — kies per kamer."""
        errors: dict = {}

        try:
            from .climate_discovery import async_suggest_zones
            suggested = await async_suggest_zones(self.hass)
        except Exception as exc:
            _LOGGER.warning("ClimateDiscovery mislukt: %s", exc)
            suggested = []

        if user_input is not None:
            enabled_ids = user_input.get(CONF_CLIMATE_ZONES_ENABLED, [])
            self._config[CONF_CLIMATE_ZONES_ENABLED] = enabled_ids
            self._config[CONF_CLIMATE_ENABLED] = bool(enabled_ids)
            self._config[CONF_CLIMATE_EPEX_ENABLED] = False
            if suggested and "climate_zones" not in self._config:
                self._config["climate_zones"] = suggested
            return await self.async_step_cv_boiler_config()

        if suggested and "climate_zones" not in self._config:
            self._config["climate_zones"] = suggested

        zone_options = [
            selector.SelectOptionDict(
                value=z["zone_name"],
                label=f"{z['zone_display_name']} "
                      f"({'CV' if z['zone_heating_type']=='cv' else 'Airco' if z['zone_heating_type']=='airco' else 'CV+Airco'})",
            )
            for z in suggested
        ]
        default_zones = [z["zone_name"] for z in suggested]

        if not zone_options:
            return self.async_show_form(
                step_id="climate_zones",
                data_schema=vol.Schema({}),
                description_placeholders={"discovery": (
                    "*Geen fysieke climate-entiteiten gevonden. "
                    "Wijs climate-apparaten toe aan een HA-ruimte (Instellingen → Gebieden & zones) "
                    "voor automatische zone-indeling.*"
                )},
                errors=errors,
            )

        return self.async_show_form(
            step_id="climate_zones",
            data_schema=vol.Schema({
                vol.Optional(CONF_CLIMATE_ZONES_ENABLED, default=default_zones):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=zone_options, multiple=True, mode="list",
                    )),
            }),
            description_placeholders={
                "discovery": "Selecteer de kamers waarvoor CloudEMS een virtueel klimaatapparaat "
                             "aanmaakt. Alleen kamers met een fysieke thermostaat of TRV worden getoond.",
            },
        )


    async def async_step_cv_boiler_config(self, user_input=None):
        """CV-ketel configuratie: entity, type en stooklijn."""
        if user_input is not None:
            if user_input.get("cv_boiler_entity"):
                self._config["cv_boiler_entity"]   = user_input["cv_boiler_entity"]
                self._config["cv_control_type"]    = user_input.get("cv_control_type", "switch")
                self._config["cv_curve_slope"]     = float(user_input.get("cv_curve_slope", 1.5))
                self._config["cv_min_supply_c"]    = float(user_input.get("cv_min_supply_c", 25.0))
                self._config["cv_max_supply_c"]    = float(user_input.get("cv_max_supply_c", 55.0))
                self._config["cv_min_zones_calling"] = int(user_input.get("cv_min_zones_calling", 1))
                self._config["cv_summer_cutoff_c"] = float(user_input.get("cv_summer_cutoff_c", 18.0))
            return await self.async_step_boiler_groups()

        return self.async_show_form(
            step_id="cv_boiler_config",
            data_schema=vol.Schema({
                vol.Optional("cv_boiler_entity", default=self._config.get("cv_boiler_entity", "")): str,
                vol.Optional("cv_control_type", default=self._config.get("cv_control_type", "switch")):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="switch",     label="Switch / input_boolean (aan/uit)"),
                        selector.SelectOptionDict(value="climate",    label="Climate (aan/uit via hvac_mode)"),
                        selector.SelectOptionDict(value="opentherm",  label="OpenTherm (aanvoertemperatuur via stooklijn)"),
                    ], mode="list")),
                vol.Optional("cv_curve_slope", default=self._config.get("cv_curve_slope", 1.5)):
                    selector.NumberSelector(selector.NumberSelectorConfig(min=0.5, max=3.0, step=0.1)),
                vol.Optional("cv_min_supply_c", default=self._config.get("cv_min_supply_c", 25.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(min=20.0, max=40.0, step=1.0)),
                vol.Optional("cv_max_supply_c", default=self._config.get("cv_max_supply_c", 55.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(min=40.0, max=80.0, step=1.0)),
                vol.Optional("cv_min_zones_calling", default=self._config.get("cv_min_zones_calling", 1)):
                    selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=10, step=1)),
                vol.Optional("cv_summer_cutoff_c", default=self._config.get("cv_summer_cutoff_c", 18.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(min=12.0, max=25.0, step=0.5)),
            }),
            description_placeholders={
                "info": (
                    "**CV-ketel aansturing**\n\n"
                    "- **Switch/climate**: aan/uit sturing\n"
                    "- **OpenTherm**: berekent aanvoertemperatuur via stooklijn\n"
                    "  *Beter dan VTherm vaste hoog/laag: CloudEMS berekent de optimale "
                    "aanvoertemperatuur op basis van buitentemperatuur en warmtevraag. "
                    "Max 55°C zodat condensatieketel altijd in condensatiemodus blijft.*\n\n"
                    "Laat leeg om CV-ketel niet via CloudEMS aan te sturen."
                ),
            },
        )


    async def async_step_climate_epex_count(self, user_input=None):
        """Airco/WP EPEX stap 1: hoeveel apparaten?"""
        ex = self._config
        existing_devices = ex.get(CONF_CLIMATE_EPEX_DEVICES, [])

        if user_input is not None:
            self._ce_count = int(user_input.get("ce_count", 1))
            self._config[CONF_CLIMATE_EPEX_ENABLED] = True
            self._config[CONF_CLIMATE_ENABLED] = False
            self._config[CONF_CLIMATE_EPEX_DEVICES] = []
            self._ce_step = 0
            self._existing_ce_cfgs = list(existing_devices)
            return await self.async_step_climate_epex_device()

        opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(1, 9)]
        return self.async_show_form(
            step_id="climate_epex_count",
            data_schema=vol.Schema({
                vol.Required("ce_count", default=str(max(1, len(existing_devices)))): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opts, mode="list")
                ),
            }),
            description_placeholders={
                "current": ", ".join(d.get("label", d.get("entity_id", "")) for d in existing_devices) or "—",
            },
        )

    async def async_step_climate_epex_device(self, user_input=None):
        """Airco/WP EPEX: configureer apparaat N."""
        i = self._ce_step + 1
        existing_cfgs = getattr(self, "_existing_ce_cfgs", [])
        existing = existing_cfgs[self._ce_step] if self._ce_step < len(existing_cfgs) else {}

        if user_input is not None:
            self._config[CONF_CLIMATE_EPEX_DEVICES].append({
                "entity_id":    user_input["ce_entity"],
                "label":        user_input.get("ce_label", f"Apparaat {i}"),
                "device_type":  user_input.get("ce_type", "heat_pump"),
                "power_entity": user_input.get("ce_power", ""),
                "offset_c":     float(user_input.get("ce_offset", 0.5)),
                "enabled":      True,
            })
            self._ce_step += 1
            if self._ce_step < self._ce_count:
                return await self.async_step_climate_epex_device()
            return await self.async_step_boiler_groups()

        type_opts = [
            selector.SelectOptionDict(value="heat_pump", label="🔥 Warmtepomp"),
            selector.SelectOptionDict(value="airco",     label="❄️ Airco / koeling"),
            selector.SelectOptionDict(value="hybrid",    label="🔄 Hybride (WP + ketel)"),
        ]
        return self.async_show_form(
            step_id="climate_epex_device",
            data_schema=vol.Schema({
                vol.Required("ce_entity", default=existing.get("entity_id") or vol.UNDEFINED):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["climate"])),
                vol.Optional("ce_label", description={"suggested_value": existing.get("label", f"Apparaat {i}")}): str,
                vol.Required("ce_type", default=existing.get("device_type", "heat_pump")):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=type_opts, mode="list")),
                vol.Optional("ce_power", default=existing.get("power_entity") or vol.UNDEFINED):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
                vol.Optional("ce_offset", default=float(existing.get("offset_c", 0.5))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
            }),
            description_placeholders={
                "device_num": str(i),
                "total":      str(self._ce_count),
                "tip":        "Offset = maximale temperatuurverschuiving in °C (aanbevolen: 0.5°C).",
            },
        )

    async def async_step_boiler_groups(self, user_input=None):
        """Warm Water Cascade wizard-stap.

        Vraagt of de gebruiker boiler-cascade-groepen wil configureren.
        Zo ja: stap 1 van N (groep aanmaken), anders door naar mail.

        Opgeslagen als boiler_groups: list[dict] in de config.
        Elke dict = { id, name, mode, units: [...] }
        """
        data = getattr(self, "_config", {})
        existing_groups: list = data.get(CONF_BOILER_GROUPS, [])

        if user_input is not None:
            # v4.6.271: Als gebruiker geen boiler heeft, direct door naar mail (issue #28 feedback)
            if not user_input.get(CONF_BOILER_GROUPS_ENABLED, False):
                self._config[CONF_BOILER_GROUPS_ENABLED] = False
                return await self.async_step_presence()
            self._config[CONF_BOILER_GROUPS_ENABLED] = True
            self._boiler_group_index = 0
            self._boiler_groups_tmp  = list(existing_groups)
            self._boiler_unit_count  = int(user_input.get("unit_count", 1) or 1)
            self._boiler_group_name  = user_input.get("group_name", "Tapwater")
            self._boiler_group_mode  = user_input.get("group_mode", BOILER_MODE_AUTO)
            self._boiler_unit_index  = 0
            self._boiler_units_tmp   = []
            return await self.async_step_boiler_brand()

        return self.async_show_form(
            step_id="boiler_groups",
            description_placeholders={
                "info": (
                    "**Heb je een warmwaterboiler, elektrische geyser of accumulatortank?**\n"
                    "Schakel deze stap in om CloudEMS automatisch te laten sturen op basis van "
                    "PV-surplus, goedkope EPEX-uren en netcongestie.\n\n"
                    "**Geen boiler?** Laat de schakelaar UIT staan en klik op Volgende — "
                    "je slaat deze configuratie volledig over.\n\n"
                    "Je koppelt gewoon bestaande HA-entiteiten (switch, climate of water_heater). "
                    "Meerdere boilers in groepen zijn mogelijk."
                ),
            },
            data_schema=vol.Schema({
                vol.Optional(CONF_BOILER_GROUPS_ENABLED,
                             default=data.get(CONF_BOILER_GROUPS_ENABLED, False)): bool,
                vol.Optional("group_name",
                             description={"suggested_value": "Tapwater"}): str,
                vol.Optional("group_mode",
                             default=BOILER_MODE_AUTO): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=k, label=v)
                                 for k, v in BOILER_MODE_LABELS.items()],
                        mode="list",
                    )
                ),
                vol.Optional("unit_count", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=12, step=1, mode="box")
                ),
            }),
        )

    async def async_step_boiler_brand(self, user_input=None):
        """Wizard-stap: kies het merk/type van de boiler. Vult automatisch de juiste instellingen."""
        idx   = getattr(self, "_boiler_unit_index", 0)
        total = int(getattr(self, "_boiler_unit_count", 1))

        if user_input is not None:
            brand = user_input.get("brand", "unknown")
            self._boiler_brand_tmp = BOILER_BRAND_PRESETS.get(brand, BOILER_BRAND_PRESETS["unknown"]).copy()
            self._boiler_brand_tmp["_brand_key"] = brand
            return await self.async_step_boiler_unit()

        return self.async_show_form(
            step_id="boiler_brand",
            description_placeholders={
                "idx":         str(idx + 1),
                "total":       str(total),
                "group":       getattr(self, "_boiler_group_name", "?"),
                "diagram_url": "/local/cloudems/diagrams/boiler_brand.svg",
            },
            data_schema=vol.Schema({
                vol.Required("brand", default="unknown"): _boiler_brand_selector(),
            }),
        )

    async def async_step_boiler_unit(self, user_input=None):
        """Wizard-stap: configureer één boiler-unit in de huidige groep."""
        idx   = getattr(self, "_boiler_unit_index", 0)
        total = int(getattr(self, "_boiler_unit_count", 1))
        # Merk-preset van vorige stap (async_step_boiler_brand)
        bp    = getattr(self, "_boiler_brand_tmp", BOILER_BRAND_PRESETS["unknown"])

        if user_input is not None:
            control_mode = user_input.get("control_mode", bp.get("control_mode", "switch"))
            unit = {
                "entity_id":            user_input["entity_id"],
                "label":                user_input.get("label", f"Boiler {idx + 1}"),
                "temp_sensor":          user_input.get("temp_sensor", ""),
                "energy_sensor":        user_input.get("energy_sensor", ""),
                "power_w":              DEFAULT_BOILER_POWER_W,
                "setpoint_c":           float(user_input.get("setpoint_c",           bp.get("setpoint_c",           DEFAULT_BOILER_SETPOINT_C))),
                "min_temp_c":           float(user_input.get("min_temp_c",           bp.get("min_temp_c",           DEFAULT_BOILER_MIN_TEMP_C))),
                "comfort_floor_c":      float(user_input.get("comfort_floor_c",      DEFAULT_BOILER_COMFORT_C)),
                "surplus_setpoint_c":   float(user_input.get("surplus_setpoint_c",   bp.get("surplus_setpoint_c",   75.0))),
                "max_setpoint_boost_c": float(user_input.get("max_setpoint_boost_c", bp.get("max_setpoint_boost_c", 75.0))),
                "max_setpoint_green_c": float(user_input.get("max_setpoint_green_c", bp.get("max_setpoint_green_c", 53.0))),
                "hardware_max_c":       float(user_input.get("hardware_max_c",       bp.get("hardware_max_c",       0.0))),
                "hardware_deadband_c":  float(bp.get("hardware_deadband_c",  0.0)),
                "stall_timeout_s":      float(bp.get("stall_timeout_s",      300.0)),
                "stall_boost_c":        float(bp.get("stall_boost_c",        5.0)),
                "priority":             int(user_input.get("priority", idx)),
                "min_on_minutes":       int(user_input.get("min_on_minutes",  DEFAULT_BOILER_MIN_ON_MIN)),
                "min_off_minutes":      int(user_input.get("min_off_minutes", DEFAULT_BOILER_MIN_OFF_MIN)),
                "control_mode":         control_mode,
                "boiler_type":          user_input.get("boiler_type", bp.get("boiler_type", "resistive")),
                "preset_on":            user_input.get("preset_on",  bp.get("preset_on",  "on")),
                "preset_off":           user_input.get("preset_off", bp.get("preset_off", "off")),
                "dimmer_on_pct":        float(user_input.get("dimmer_on_pct",  100)),
                "dimmer_off_pct":       float(user_input.get("dimmer_off_pct", 0)),
                "max_setpoint_entity":  user_input.get("max_setpoint_entity", ""),
                "brand":                bp.get("_brand_key", "unknown"),
                "modes":                ["cheap_hours", "negative_price", "pv_surplus", "export_reduce"],
                # v4.6.561: tankvolume en ramp-max opslaan uit wizard
                "tank_liters":          int(user_input.get("tank_liters",       bp.get("tank_liters",       0))),
                "cheap_ramp_max_c":     int(user_input.get("cheap_ramp_max_c",  bp.get("cheap_ramp_max_c",  65))),
            }
            getattr(self, "_boiler_units_tmp", []).append(unit)
            self._boiler_unit_index = idx + 1
            self._boiler_brand_tmp  = BOILER_BRAND_PRESETS["unknown"]  # reset voor volgende boiler

            if self._boiler_unit_index < total:
                return await self.async_step_boiler_brand()

            # Alle units van deze groep zijn klaar — sla groep op
            group = {
                "group":  True,
                "id":     getattr(self, "_boiler_group_name", "tapwater").lower().replace(" ", "_"),
                "name":   getattr(self, "_boiler_group_name", "Tapwater"),
                "mode":   getattr(self, "_boiler_group_mode",  BOILER_MODE_AUTO),
                "units":  list(self._boiler_units_tmp),
            }
            groups = getattr(self, "_boiler_groups_tmp", [])
            groups.append(group)
            self._config[CONF_BOILER_GROUPS] = groups
            return await self.async_step_mail()

        # Detecteer water_heater / climate / switch entiteiten als suggestie
        all_states   = self.hass.states.async_all()
        boiler_hints = sorted(set(
            s.entity_id for s in all_states
            if s.domain in ("switch", "climate", "water_heater", "number")
            and any(kw in s.entity_id.lower()
                    for kw in ("boiler", "boil", "water", "heater", "geyser",
                               "warmwater", "hw", "dhw", "cv"))
        ))

        _default_sp   = bp.get("setpoint_c",          DEFAULT_BOILER_SETPOINT_C)
        _default_min  = bp.get("min_temp_c",           DEFAULT_BOILER_MIN_TEMP_C)
        _default_mxsp = bp.get("max_setpoint_boost_c", 75.0)
        _brand_label  = bp.get("_label",               "❓ Onbekend")
        _brand_key    = bp.get("_brand_key",            "unknown")
        _is_known_brand = _brand_key not in ("unknown", "generic_resistive", "generic_heatpump")

        # Basis schema — altijd getoond
        schema_dict = {
            vol.Required("entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "climate", "water_heater", "input_boolean"]
                )
            ),
            vol.Optional("label",
                         description={"suggested_value": f"Boiler {idx + 1}"}): str,
            vol.Optional("temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("energy_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor",
                    device_class=["power", "energy"])
            ),
            vol.Optional("setpoint_c", default=_default_sp): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=85, step=1,
                                              mode="slider", unit_of_measurement="°C")
            ),
            # v4.6.25: max_setpoint_entity — number-entity die de hardware-limiet bestuurt
            # (bijv. number.ariston_max_setpoint_temperature). CloudEMS zet deze entity
            # vóór set_temperature zodat de boiler echt 75°C kan bereiken in BOOST-modus.
            vol.Optional("max_setpoint_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
        }

        # v4.6.562: categorie-gebaseerde velden — toon alleen wat relevant is
        _cat = _brand_category(_brand_key)
        _default_cm   = bp.get("control_mode", "switch")
        _default_type = bp.get("boiler_type",  "resistive")
        _default_pon  = bp.get("preset_on",    "on")
        _default_poff = bp.get("preset_off",   "off")

        # manual + generic_switch: sturingmodus zonder dimmer-opties
        if _cat in ("manual",):
            schema_dict.update({
                vol.Optional("min_temp_c", default=_default_min): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=60, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
                vol.Optional("max_setpoint_boost_c", default=_default_mxsp): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=85, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
                vol.Optional("boiler_type", default=_default_type): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "resistive", "label": "⚡ Elektrisch weerstand"},
                        {"value": "heat_pump", "label": "♻️ Warmtepomp boiler"},
                        {"value": "hybrid",    "label": "🔥 Hybride (WP + weerstand)"},
                    ], mode="list")),
                vol.Optional("control_mode", default=_default_cm): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",         "label": "🔌 Aan/uit schakelaar"},
                        {"value": "setpoint",       "label": "🌡️ Setpoint instellen"},
                        {"value": "setpoint_boost", "label": "🌡️⚡ Setpoint + Boost bij PV-surplus"},
                        {"value": "preset",         "label": "🎛️ Preset modus (bijv. GREEN/BOOST)"},
                    ], mode="list")),
                vol.Optional("preset_on",  default=_default_pon):  selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
                vol.Optional("preset_off", default=_default_poff): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
            })

        elif _cat == "generic_switch":
            # Generiek elektrisch: switch of setpoint, geen dimmer, geen preset
            schema_dict.update({
                vol.Optional("min_temp_c", default=_default_min): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=60, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
                vol.Optional("control_mode", default=_default_cm): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",   "label": "🔌 Aan/uit schakelaar (switch)"},
                        {"value": "setpoint", "label": "🌡️ Setpoint instellen (climate / water_heater)"},
                    ], mode="list")),
            })

        elif _cat == "dimmer":
            # DimmerLink / ACRouter: dimmer% velden, geen preset/control_mode keuze
            schema_dict.update({
                vol.Optional("dimmer_on_pct",  default=int(bp.get("dimmer_on_pct", 100))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
                vol.Optional("dimmer_off_pct", default=int(bp.get("dimmer_off_pct", 0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
            })
        # known_brand + generic_heatpump: geen extra velden — preset bevat alles

        # Tankvolume en ramp-max: altijd instelbaar
        _default_tank    = int(bp.get("tank_liters", 0))
        _default_rampmax = int(bp.get("cheap_ramp_max_c", 65))
        schema_dict.update({
            vol.Optional("tank_liters", default=_default_tank): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=5,
                                              mode="slider", unit_of_measurement="L")),
            vol.Optional("cheap_ramp_max_c", default=_default_rampmax): selector.NumberSelector(
                selector.NumberSelectorConfig(min=40, max=85, step=1,
                                              mode="slider", unit_of_measurement="°C")),
        })

        return self.async_show_form(
            step_id="boiler_unit",
            description_placeholders={
                "idx":         str(idx + 1),
                "total":       str(total),
                "group":       getattr(self, "_boiler_group_name", "?"),
                "brand_label": _brand_label,
            },
            data_schema=vol.Schema(schema_dict),
        )



    async def async_step_presence(self, user_input=None):
        """Aanwezigheidsdetectie — extra bewegings-/aanwezigheidssensoren toevoegen.

        CloudEMS detecteert automatisch:
          - person.* en device_tracker.* entiteiten
          - binary_sensor met device_class presence/occupancy/motion
        Hier kun je extra sensoren opgeven die niet auto-gedetecteerd worden.
        """
        if user_input is not None:
            entities = user_input.get(CONF_PRESENCE_ENTITIES, [])
            self._config[CONF_PRESENCE_ENTITIES] = entities
            return await self.async_step_mail()

        # Auto-detecteer aanwezige presence sensoren als hint
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(self.hass)
        auto_found = []
        for state in self.hass.states.async_all("binary_sensor"):
            dc = state.attributes.get("device_class", "")
            if dc in ("presence", "occupancy", "motion"):
                auto_found.append(state.entity_id)
        for state in self.hass.states.async_all("person"):
            auto_found.append(state.entity_id)

        existing = self._config.get(CONF_PRESENCE_ENTITIES, [])
        auto_str = "\n".join(f"• {e}" for e in auto_found[:10]) if auto_found else "Geen gevonden"

        return self.async_show_form(
            step_id="presence",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRESENCE_ENTITIES, default=existing):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["binary_sensor", "person", "device_tracker", "input_boolean"],
                        multiple=True,
                    )),
            }),
            description_placeholders={
                "auto_found": auto_str,
                "info": (
                    "CloudEMS combineert meerdere signalen voor aanwezigheidsdetectie.\n\n"
                    "**Auto-gedetecteerd:**\n"
                    f"{auto_str}\n\n"
                    "**Extra sensoren** (optioneel): voeg hier Hue, Zigbee2MQTT of andere "
                    "bewegings- of aanwezigheidssensoren toe die niet in de lijst staan. "
                    "CloudEMS gebruikt ze als extra signaal naast de auto-detectie."
                ),
            },
        )

    async def async_step_mail(self, user_input=None):
        errors: dict = {}
        if user_input is not None:
            enabled = user_input.get(CONF_MAIL_ENABLED, False)
            if enabled:
                # Validate minimale verplichte velden
                if not user_input.get(CONF_MAIL_HOST, "").strip():
                    errors[CONF_MAIL_HOST] = "mail_host_required"
                if not user_input.get(CONF_MAIL_TO, "").strip():
                    errors[CONF_MAIL_TO] = "mail_to_required"
                # SMTP connection test is skipped in wizard to prevent blocking
                # User can validate via options flow after setup
            if not errors:
                self._config.update(user_input)
                return await self.async_step_diagnostics()

        existing = self._config
        return self.async_show_form(
            step_id="mail",
            errors=errors,
            data_schema=vol.Schema({
                vol.Optional(CONF_MAIL_ENABLED,  default=existing.get(CONF_MAIL_ENABLED, False)): bool,
                vol.Optional(CONF_MAIL_HOST,     description={"suggested_value": existing.get(CONF_MAIL_HOST, "")}): str,
                vol.Optional(CONF_MAIL_PORT,     default=existing.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)):
                    vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_MAIL_USE_TLS,  default=existing.get(CONF_MAIL_USE_TLS, DEFAULT_MAIL_USE_TLS)): bool,
                vol.Optional(CONF_MAIL_USERNAME, description={"suggested_value": existing.get(CONF_MAIL_USERNAME, "")}): str,
                vol.Optional(CONF_MAIL_PASSWORD, description={"suggested_value": existing.get(CONF_MAIL_PASSWORD, "")}): str,
                vol.Optional(CONF_MAIL_FROM,     description={"suggested_value": existing.get(CONF_MAIL_FROM, "")}): str,
                vol.Optional(CONF_MAIL_TO,       description={"suggested_value": existing.get(CONF_MAIL_TO, "")}): str,
                vol.Optional(CONF_MAIL_MONTHLY,  default=existing.get(CONF_MAIL_MONTHLY, True)): bool,
                vol.Optional(CONF_MAIL_WEEKLY,   default=existing.get(CONF_MAIL_WEEKLY, False)): bool,
            }),
        )

    async def async_step_generator(self, user_input=None):
        """Optionele stap: Generator / ATS configureren."""
        if user_input is not None:
            self._config.update({k: v for k, v in user_input.items() if v not in (None, "", False) or k == "generator_enabled"})
            return await self.async_step_solar_ev()

        existing = self._config
        _gen_enabled = existing.get("generator_enabled", False)

        schema_dict = {
            vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
            vol.Optional("generator_enabled", default=_gen_enabled): bool,
        }

        if _gen_enabled or True:  # altijd tonen voor duidelijkheid
            schema_dict.update({
                vol.Optional("generator_power_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class=["power"])
                ),
                vol.Optional("generator_status_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig()  # binary_sensor, sensor of input_boolean
                ),
                vol.Optional("generator_autostart_switch"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "button", "script"])
                ),
                vol.Optional("generator_max_power_w", default=int(existing.get("generator_max_power_w", 5000))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=500, max=30000, step=500, mode="slider", unit_of_measurement="W")
                ),
                vol.Optional("generator_type", default=existing.get("generator_type", "diesel")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "diesel",   "label": "🛢️ Diesel"},
                        {"value": "benzine",  "label": "⛽ Benzine"},
                        {"value": "propaan",  "label": "🔵 Propaan/LPG"},
                        {"value": "aardgas",  "label": "🔥 Aardgas"},
                        {"value": "overig",   "label": "⚡ Overig"},
                    ], mode="list")
                ),
                vol.Optional("generator_fuel_cost_eur_kwh", default=float(existing.get("generator_fuel_cost_eur_kwh", 0.35))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.05, max=2.0, step=0.01, mode="box", unit_of_measurement="€/kWh")
                ),
                vol.Optional("ats_type", default=existing.get("ats_type", "auto")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "auto",     "label": "🔄 Automatische ATS — CloudEMS leest status"},
                        {"value": "manual",   "label": "🔧 Handmatige MTS — CloudEMS geeft melding"},
                        {"value": "none",     "label": "➖ Geen ATS/MTS"},
                    ], mode="list")
                ),
            })

        return self.async_show_form(
            step_id="generator",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/generator.svg",
            },
        )

    async def async_step_diagnostics(self, user_input=None):
        """Optionele stap: GitHub log reporting instellen."""
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_data_consent()

        existing = self._config
        return self.async_show_form(
            step_id="diagnostics",
            data_schema=vol.Schema({
                vol.Optional(
                    "github_log_token",
                    description={"suggested_value": existing.get("github_log_token", "")},
                ): str,
                vol.Optional(
                    "notification_service",
                    description={"suggested_value": existing.get("notification_service", "")},
                ): str,
            }),
            description_placeholders={
                "info": (
                    "Optioneel: voer een GitHub Personal Access Token in om diagnostische "
                    "rapporten automatisch te uploaden bij kritieke fouten. "
                    "Maak een token aan op github.com/settings/tokens met 'public_repo' scope. "
                    "Alle data wordt geanonimiseerd voor verzending.\n\n"
                    "Voer ook de naam van je HA mobiele app notify service in voor push-meldingen, "
                    "bijv. 'mobile_app_mijn_telefoon'."
                ),
            },
        )

    async def async_step_data_consent(self, user_input=None):
        """Opt-in voor data-deling en buurtwaakzaamheid.

        Volledig vrijwillig — geen impact op CloudEMS functionaliteit.
        Transparant: gebruiker weet precies wat er gedeeld wordt.
        """
        if user_input is not None:
            self._config["share_observations"]      = user_input.get("share_observations", False)
            self._config["share_neighbourhood"]     = user_input.get("share_neighbourhood", False)
            self._config["adaptivehome_token"]      = user_input.get("adaptivehome_token", "").strip()
            self._config["partner_slug"]            = user_input.get("partner_slug", "").strip().lower()
            return self._create()

        existing = self._config
        return self.async_show_form(
            step_id="data_consent",
            data_schema=vol.Schema({
                vol.Optional(
                    "share_observations",
                    default=existing.get("share_observations", False),
                ): bool,
                vol.Optional(
                    "share_neighbourhood",
                    default=existing.get("share_neighbourhood", False),
                ): bool,
                vol.Optional(
                    "adaptivehome_token",
                    default=existing.get("adaptivehome_token", ""),
                ): str,
                vol.Optional(
                    "partner_slug",
                    default=existing.get("partner_slug", ""),
                ): str,
            }),
            description_placeholders={
                "privacy_url":        "https://cloudems.eu/privacy",
                "neighbourhood_url":  "https://cloudems.eu/buurtwaakzaamheid",
            },
        )

    def _create(self):

        # When re-running via Reconfigure, update the existing entry instead of creating new
        if self.source == config_entries.SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=self._config,
                reason="reconfigure_successful",
            )
        return self.async_create_entry(title=self._build_title(), data=self._config)

    def _build_title(self) -> str:
        if self._config.get(CONF_WIZARD_MODE) == WIZARD_MODE_DEMO:
            return "CloudEMS Demo"
        return "CloudEMS"

    # ── Reconfigure: re-run the full wizard on an existing entry ─────────────
    async def async_step_reconfigure(self, user_input=None):
        """Re-run the full setup wizard from the Integrations page (⋮ → Reconfigure).
        Seeds all current values so users only change what they need.
        """
        existing = self._get_reconfigure_entry()
        self._config = {**existing.data, **existing.options}
        self._inv_count = len(self._config.get(CONF_INVERTER_CONFIGS, []))
        self._inv_step  = 0
        self._bat_count = len(self._config.get(CONF_BATTERY_CONFIGS, []))
        self._bat_step  = 0
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CloudEMSOptionsFlow(config_entry)


# ══════════════════════════════════════════════════════════════════════════════
# Options flow — multi-step grouped by category
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Options flow — multi-step grouped by category
# ══════════════════════════════════════════════════════════════════════════════

# HA 2023.3+ exposes OptionsFlowWithConfigEntry which auto-triggers a
# config-entry reload after async_create_entry — no manual update_listener
# needed and no "restart required" dialog shown to the user.
# Fall back to the plain OptionsFlow on older HA builds.
try:
    _OptionsBase = config_entries.OptionsFlowWithConfigEntry
except AttributeError:
    _OptionsBase = config_entries.OptionsFlow  # type: ignore[assignment]


class CloudEMSOptionsFlow(_OptionsBase):

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None,
                        description_placeholders=None, last_step=None, **kwargs):
        """Overschreven: voeg automatisch terug-knop toe aan elk formulier.

        Submenus (step_id start met 'menu_') en de init-stap krijgen geen knop
        want die hebben al een eigen navigatiemechanisme.
        """
        import voluptuous as _vol
        from homeassistant.helpers import selector as _sel_mod
        _BoolSel = _sel_mod.BooleanSelector
        _skip = step_id.startswith("menu_") or step_id == "init"
        if not _skip and data_schema is not None:
            _back_field = {
                _vol.Optional("back_to_menu", default=False,
                              description={"suggested_value": False}): _BoolSel(),
            }
            # Voeg terug-veld toe aan het begin van het schema
            try:
                _existing = dict(data_schema.schema)
                data_schema = _vol.Schema({**_back_field, **_existing})
            except Exception:
                pass  # Schema niet aanpasbaar — sla over

        return super().async_show_form(
            step_id=step_id,
            data_schema=data_schema,
            errors=errors or {},
            description_placeholders=description_placeholders or {},
            last_step=last_step,
            **kwargs,
        )

    def __init__(self, config_entry) -> None:
        # OptionsFlowWithConfigEntry stores config_entry as self.config_entry;
        # plain OptionsFlow does not call super().__init__() with the entry.
        try:
            super().__init__(config_entry)
        except TypeError:
            super().__init__()
        self._entry = config_entry  # always available as shorthand
        self._opts: dict = {}
        self._inv_count = 0
        self._inv_step  = 0
        # Cheap-hours switches wizard
        self._cheap_count = 0
        self._cheap_step  = 0
        # Climate EPEX wizard
        self._ce_count = 0
        self._ce_step  = 0
        self._existing_cheap_cfgs: list[dict] = []

    def _data(self) -> dict:
        # OptionsFlowWithConfigEntry exposes self.config_entry; keep _entry too.
        entry = getattr(self, "config_entry", self._entry)
        return {**entry.data, **entry.options, **self._opts}

    def _entry_options(self) -> dict:
        """Return current entry options — works with both base classes."""
        entry = getattr(self, "config_entry", self._entry)
        return dict(entry.options)

    async def async_step_lamp_auto_opts(self, user_input=None):
        """Backwards compat — verwijst door naar lamp_automation_opts."""
        return await self.async_step_lamp_automation_opts(user_input)

    async def async_step_lamp_automation_opts(self, user_input=None):
        """Lamp Automatisering — stap 1: aan/uit + vergeten-timer.

        De engine kent 3 modi per lamp:
          👤 Handmatig  — CloudEMS leert alleen, doet niets automatisch
          🔔 Semi-auto  — CloudEMS stuurt een notificatie, jij bevestigt
          🤖 Automatisch — CloudEMS schakelt direct op basis van aanwezigheid

        Standaarden op basis van ruimtenaam:
          slaapkamer / badkamer → Handmatig
          woonkamer / keuken   → Semi-auto
          hal / gang / buiten  → Automatisch
        """
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            la_cfg = data.get("lamp_automation", {}) or {}
            new_la = {
                **la_cfg,
                "enabled":           user_input.get("la_enabled", False),
                "forgotten_minutes": int(user_input.get("la_forgotten_minutes", 30)),
            }
            # Save en ga door naar per-lamp stap
            # We updaten intern zodat detail-stap de nieuwe waarden ziet
            if hasattr(self, "_options"):
                self._options = {**self._options, "lamp_automation": new_la}
            self._la_area_filter = ""
            return await self.async_step_lamp_automation_detail_opts()

        la_cfg = data.get("lamp_automation", {}) or {}
        return self.async_show_form(
            step_id="lamp_automation_opts",
            description_placeholders={
                "uitleg": (
                    "Modi:\n"
                    "👤 Handmatig — alleen leren, nooit schakelen\n"
                    "🔔 Semi-auto — notificatie sturen, jij bevestigt\n"
                    "🤖 Automatisch — direct schakelen op basis van aanwezigheid\n\n"
                    "Standaard per ruimte: slaapkamer→Handmatig, woonkamer→Semi, hal→Automatisch"
                )
            },
            data_schema=vol.Schema({
                vol.Optional("back_to_menu",         default=False): selector.BooleanSelector(),
                vol.Optional("la_enabled",           default=la_cfg.get("enabled", False)): selector.BooleanSelector(),
                vol.Optional("la_forgotten_minutes", default=int(la_cfg.get("forgotten_minutes", 30))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=120, step=5, mode="slider",
                                                  unit_of_measurement="min")
                ),
            }),
        )

    async def async_step_lamp_automation_detail_opts(self, user_input=None):
        """Lamp Automatisering — stap 2: stel per lamp de modus in."""
        data      = self._data()
        la_cfg    = data.get("lamp_automation", {}) or {}
        lamp_list = list(la_cfg.get("lamps", []))
        area      = getattr(self, "_la_area_filter", "")

        # Auto-discover lampen via HA als lijst leeg is
        if not lamp_list:
            try:
                from .energy_manager.lamp_automation import ROOM_DEFAULT_MODE
                from homeassistant.helpers import area_registry as ar, entity_registry as er
                area_reg = ar.async_get(self.hass)
                ent_reg  = er.async_get(self.hass)
                for entry in ent_reg.entities.values():
                    if entry.domain != "light" or entry.disabled:
                        continue
                    a = area_reg.async_get_area(entry.area_id) if entry.area_id else None
                    area_name = a.name if a else ""
                    mode = "manual"
                    for kw, (m, _) in ROOM_DEFAULT_MODE.items():
                        if kw in area_name.lower():
                            mode = m
                            break
                    lamp_list.append({
                        "entity_id": entry.entity_id,
                        "label":     entry.name or entry.original_name or entry.entity_id,
                        "area_name": area_name,
                        "mode":      mode,
                        "excluded":  False,
                    })
                la_cfg = {**la_cfg, "lamps": lamp_list}
            except Exception:
                pass

        filtered = [l for l in lamp_list if not area or l.get("area_name", "") == area]

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            if user_input.get("terug_naar_stap1"):
                return await self.async_step_lamp_automation_opts()
            for lamp in lamp_list:
                slug = lamp["entity_id"].replace(".", "_").replace("-", "_")
                if f"mode_{slug}" in user_input:
                    lamp["mode"]     = user_input[f"mode_{slug}"]
                if f"excl_{slug}" in user_input:
                    lamp["excluded"] = user_input[f"excl_{slug}"]
            new_la = {**la_cfg, "lamps": lamp_list}
            return self._save({"lamp_automation": new_la})

        schema_dict = {
            vol.Optional("back_to_menu",     default=False): selector.BooleanSelector(),
            vol.Optional("terug_naar_stap1", default=False): selector.BooleanSelector(),
        }
        for lamp in filtered[:15]:
            slug = lamp["entity_id"].replace(".", "_").replace("-", "_")
            lbl      = lamp.get("label", lamp["entity_id"])
            area_lbl = f" [{lamp.get('area_name','')}]" if lamp.get("area_name") else ""
            schema_dict[vol.Optional(f"mode_{slug}", default=lamp.get("mode", "manual"))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    {"value": "manual", "label": f"{lbl}{area_lbl} — 👤 Handmatig (alleen leren, nooit schakelen)"},
                    {"value": "semi",   "label": f"{lbl}{area_lbl} — 🔔 Semi-auto (notificatie, jij bevestigt)"},
                    {"value": "auto",   "label": f"{lbl}{area_lbl} — 🤖 Automatisch (direct schakelen)"},
                ], mode="list")
            )
            schema_dict[vol.Optional(f"excl_{slug}", default=lamp.get("excluded", False))] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="lamp_automation_detail_opts",
            description_placeholders={
                "uitleg": (
                    f"Gevonden: {len(filtered)} lamp(en).\n"
                    "👤 Handmatig = CloudEMS leert alleen, doet nooit iets automatisch.\n"
                    "🔔 Semi-auto = CloudEMS stuurt een notificatie, jij bevestigt.\n"
                    "🤖 Automatisch = CloudEMS schakelt direct op basis van aanwezigheid.\n"
                    "Zet 'Uitsluiten' aan om een lamp volledig te negeren.\n"
                    "Zet 'Terug naar stap 1' aan om de globale instellingen te wijzigen."
                )
            },
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_ups_count_opts(self, user_input=None):
        """Hoeveel UPS systemen wil je configureren?"""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            count = int(user_input.get("ups_count", 0))
            if count == 0:
                return self._save({"ups_systems": []})
            self._ups_count = count
            self._ups_index = 0
            self._ups_configs = list(data.get("ups_systems", []))
            # Vul aan tot gewenst aantal
            while len(self._ups_configs) < count:
                self._ups_configs.append({})
            return await self.async_step_ups_detail_opts()

        existing = data.get("ups_systems", [])
        return self.async_show_form(
            step_id="ups_count_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("ups_count", default=len(existing)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=8, step=1, mode="slider")
                ),
            }),
            description_placeholders={"info":
                f"Huidige UPS: {len(existing)}. Stel 0 in om UPS-beheer uit te schakelen."
            },
        )

    async def async_step_ups_detail_opts(self, user_input=None):
        """Configureer één UPS systeem."""
        data  = self._data()
        idx   = getattr(self, "_ups_index", 0)
        total = getattr(self, "_ups_count", 1)
        cfgs  = getattr(self, "_ups_configs", [{}] * total)
        existing = cfgs[idx] if idx < len(cfgs) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Sla deze UPS op
            cfgs[idx] = {
                "ups_id":         f"ups_{idx+1}",
                "label":          user_input.get("ups_label", f"UPS {idx+1}"),
                "brand":          user_input.get("ups_brand", "generic"),
                "status_entity":  user_input.get("ups_status_entity", ""),
                "battery_entity": user_input.get("ups_battery_entity", ""),
                "runtime_entity": user_input.get("ups_runtime_entity", ""),
                "power_entity":   user_input.get("ups_power_entity", ""),
                "devices":        existing.get("devices", []),
            }
            self._ups_configs = cfgs
            self._ups_index   = idx + 1
            if self._ups_index < total:
                return await self.async_step_ups_detail_opts()
            # Alle UPS geconfigureerd
            return self._save({"ups_systems": cfgs[:total]})

        return self.async_show_form(
            step_id="ups_detail_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Optional("ups_label", default=existing.get("label", f"UPS {idx+1}")): str,
                vol.Optional("ups_brand", default=existing.get("brand", "generic")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "nut",     "label": "🔌 NUT (universeel — APC/Eaton/CyberPower/...)"},
                        {"value": "apc",     "label": "🔵 APC (HA integratie)"},
                        {"value": "eaton",   "label": "🟡 Eaton (HA integratie)"},
                        {"value": "generic", "label": "⚡ Generiek (elke HA sensor)"},
                    ], mode="list")
                ),
                vol.Optional("ups_status_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Optional("ups_battery_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class=["battery"])
                ),
                vol.Optional("ups_runtime_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("ups_power_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class=["power"])
                ),
            }),
            description_placeholders={
                "info": f"UPS {idx+1} van {total}. Koppel minimaal de status-entiteit."
            },
        )

    async def async_step_generator_opts(self, user_input=None):
        """Generator / ATS opties voor bestaande installaties."""
        data = self._data()
        if hasattr(self, '_opts'):
            data = {**data, **self._opts}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save({**data, **user_input})

        _gen_enabled = data.get("generator_enabled", False)
        schema_dict = {
            vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
            vol.Optional("generator_enabled", default=_gen_enabled): bool,
            vol.Optional("generator_power_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=["power"])
            ),
            vol.Optional("generator_status_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
            vol.Optional("generator_autostart_switch"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "button", "script"])
            ),
            vol.Optional("generator_max_power_w", default=int(data.get("generator_max_power_w", 5000))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=500, max=30000, step=500, mode="slider", unit_of_measurement="W")
            ),
            vol.Optional("generator_type", default=data.get("generator_type", "diesel")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    {"value": "diesel",  "label": "🛢️ Diesel"},
                    {"value": "benzine", "label": "⛽ Benzine"},
                    {"value": "propaan", "label": "🔵 Propaan/LPG"},
                    {"value": "aardgas", "label": "🔥 Aardgas"},
                    {"value": "overig",  "label": "⚡ Overig"},
                ], mode="list")
            ),
            vol.Optional("generator_fuel_cost_eur_kwh", default=float(data.get("generator_fuel_cost_eur_kwh", 0.35))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.05, max=2.0, step=0.01, mode="box", unit_of_measurement="€/kWh")
            ),
            vol.Optional("ats_type", default=data.get("ats_type", "none")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    {"value": "auto",   "label": "🔄 Automatische ATS"},
                    {"value": "manual", "label": "🔧 Handmatige MTS"},
                    {"value": "none",   "label": "➖ Geen ATS/MTS"},
                ], mode="list")
            ),
        }
        return self.async_show_form(
            step_id="generator_opts",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_menu_back(self, user_input=None):
        """Terug naar het hoofdmenu."""
        return await self.async_step_init()

    def _check_back(self, user_input: dict):
        """Terug naar menu als gebruiker op terug drukt."""
        return user_input.get("back_to_menu", False)

    def _back_schema(self, schema_dict: dict) -> dict:
        """Voeg terug-knop toe aan een schema dict."""
        return {
            vol.Optional("back_to_menu", default=False,
                         description={"suggested_value": False}): selector.BooleanSelector(),
            **schema_dict,
        }

    def _save(self, extra: dict) -> object:
        """Merge extra into options and save; triggers auto-reload via base class.

        Strategie: options = volledig gecombineerde config (data + bestaande options
        + nieuw extra). Zo gaan nooit waarden verloren bij de eerste options-save
        of bij stappen die slechts een subset van velden tonen.
        """
        entry = getattr(self, "config_entry", self._entry)
        # Build altijd op vanuit data + options zodat ook keys die nog nooit in
        # options stonden (alleen in entry.data) correct worden meegenomen.
        # v4.6.136: Filter lege strings uit extra — een leeg veld in een stap
        # mag een bestaande geconfigureerde waarde NIET overschrijven.
        extra_clean = {k: v for k, v in extra.items() if v not in (None, "")}
        merged = {**entry.data, **entry.options, **extra_clean}
        # v4.6.175: als _opts boiler_groups heeft, altijd die gebruiken —
        # voorkomt dat een andere wizard-stap de boiler config terugzet naar entry.data
        if CONF_BOILER_GROUPS in self._opts and CONF_BOILER_GROUPS not in extra_clean:
            merged[CONF_BOILER_GROUPS] = self._opts[CONF_BOILER_GROUPS]

        # ── Afgeleide velden ───────────────────────────────────────────────────
        # CONF_MAX_CURRENT_PER_PHASE = L1 (gebruikt door piekbeperking + solar learner)
        if CONF_MAX_CURRENT_L1 in merged:
            merged[CONF_MAX_CURRENT_PER_PHASE] = float(merged[CONF_MAX_CURRENT_L1])

        # phase_count altijd als int opslaan
        if CONF_PHASE_COUNT in merged:
            merged[CONF_PHASE_COUNT] = int(merged[CONF_PHASE_COUNT])

        return self.async_create_entry(title="", data=merged)


    async def _maybe_back(self, user_input):
        """Universele back-check: als back_to_menu=True → terug naar init."""
        if user_input and user_input.get("back_to_menu"):
            return await self.async_step_init()
        return None

    async def async_step_init(self, user_input=None):
        """Main menu — with auto-detection summary above."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            cat = user_input.get("category", "energie")
            if cat == "auto_detect":
                return await self.async_step_auto_detect()
            return await getattr(self, f"async_step_menu_{cat}")()

        # Build detection summary for description_placeholders
        summary_lines = []
        missing_lines = []
        data = self._data()

        # Grid sensor
        if data.get("grid_sensor") or data.get("import_power_sensor"):
            summary_lines.append("✅ Net-sensor geconfigureerd")
        else:
            missing_lines.append("⚠️ Geen net-sensor — stel in via Energie & Grid")

        # PV
        inv_cfgs = data.get("inverter_configs", [])
        if inv_cfgs:
            summary_lines.append(f"✅ {len(inv_cfgs)} omvormer(s) geconfigureerd")
        else:
            missing_lines.append("💡 Geen omvormers — stel in via Opwekking & Opslag")

        # Battery
        bat_cfgs = data.get("battery_configs", [])
        if bat_cfgs:
            summary_lines.append(f"✅ {len(bat_cfgs)} batterij(en) geconfigureerd")

        # P1 / DSMR — auto detect
        try:
            from homeassistant.helpers import entity_registry as er
            _ent_reg = er.async_get(self.hass)
            dsmr_found = any(
                e.platform in ("dsmr", "homewizard", "p1_monitor")
                for e in _ent_reg.entities.values()
            )
            if dsmr_found:
                summary_lines.append("✅ P1/DSMR integratie gedetecteerd")
            elif not data.get("p1_enabled"):
                missing_lines.append("💡 P1/DSMR niet geconfigureerd — stel in via Energie & Grid")
        except Exception:
            pass

        # EV
        ev_cfgs = data.get("ev_charger_configs", [])
        if ev_cfgs:
            summary_lines.append(f"✅ {len(ev_cfgs)} EV laadpaal(en) geconfigureerd")

        # Boiler
        boiler_cfgs = data.get("boiler_configs", [])
        if boiler_cfgs:
            summary_lines.append(f"✅ {len(boiler_cfgs)} boiler(s) geconfigureerd")

        found_text  = "\n".join(summary_lines) if summary_lines else "Nog niets geconfigureerd"
        todo_text   = "\n".join(missing_lines) if missing_lines else "✅ Alles ingesteld"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("category", default="energie"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="auto_detect",   label="🔍 Automatisch detecteren & toepassen"),
                        selector.SelectOptionDict(value="energie",      label="⚡ Energie & Grid"),
                        selector.SelectOptionDict(value="opwekking",    label="☀️ Opwekking & Opslag"),
                        selector.SelectOptionDict(value="verbruik",     label="🏠 Verbruik & Comfort"),
                        selector.SelectOptionDict(value="automatisering", label="🤖 Automatisering & NILM"),
                        selector.SelectOptionDict(value="mobiliteit",   label="🚗 Mobiliteit & Laden"),
                        selector.SelectOptionDict(value="systeem",      label="🔧 Systeem & Communicatie"),
                        selector.SelectOptionDict(value="dashboard",    label="🏠 Dashboard & Weergave"),
                    ], mode="list"))
            }),
            description_placeholders={
                "found": found_text,
                "todo":  todo_text,
            },
        )

    async def async_step_auto_detect(self, user_input=None):
        """
        Scan HA for all detectable sensors and integrations.
        Only fills empty fields — never overwrites existing configuration.
        """
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # User confirmed — apply all detected values to empty fields only
            applied = getattr(self, "_auto_detect_results", {})
            data = self._data()
            changed = 0
            for key, value in applied.items():
                if value and not data.get(key):
                    self._opts[key] = value
                    changed += 1
            _LOGGER.info("CloudEMS auto-detect: %d fields applied", changed)
            return self._save(self._opts)

        # Run full detection
        data = self._data()
        phase_count = int(data.get("phase_count", 3) or 3)
        applied: dict = {}
        skipped: dict = {}

        # 1. Grid sensors via _detect_sensors
        suggestions = _detect_sensors(self.hass, phase_count)
        sensor_map = {
            CONF_GRID_SENSOR:   ("grid_sensor",   "Net vermogen sensor"),
            CONF_IMPORT_SENSOR: ("import_sensor",  "Import sensor"),
            CONF_EXPORT_SENSOR: ("export_sensor",  "Export sensor"),
            CONF_SOLAR_SENSOR:  ("solar_sensor",   "PV sensor"),
            CONF_BATTERY_SENSOR:("battery_sensor", "Batterij sensor"),
        }
        for conf_key, (data_key, label) in sensor_map.items():
            found = suggestions.get(conf_key)
            if found:
                if data.get(data_key):
                    skipped[label] = f"{data.get(data_key)} (behouden)"
                else:
                    applied[data_key] = found

        # 2. DSMR / HomeWizard via _prefill_from_dsmr_integration
        await self._prefill_from_dsmr_integration()
        for key in (CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR, CONF_GRID_SENSOR):
            val = self._suggestions.get(key)
            if val and not data.get(key) and key not in applied:
                applied[key] = val

        # 3. Energy dashboard scan
        try:
            from .energy_autodiscover import async_discover_from_energy_dashboard
            disc = await async_discover_from_energy_dashboard(self.hass)
            if disc.confidence != "none":
                prefill = disc.to_config_prefill()
                for k, v in prefill.items():
                    if v and not data.get(k) and k not in applied:
                        applied[k] = v
        except Exception as exc:
            _LOGGER.debug("Energy dashboard scan failed: %s", exc)

        # 4. Battery providers
        try:
            from .energy_manager.battery_provider import BatteryProviderRegistry
            from .energy_manager.victron_provider import VictronProvider    # noqa: F401
            from .energy_manager.sma_battery_provider import SMABatteryProvider  # noqa: F401
            from .energy_manager.huawei_luna_provider import HuaweiLunaProvider  # noqa: F401
            tmp_reg = BatteryProviderRegistry(self.hass, data)
            await tmp_reg.async_setup()
            for hint in tmp_reg.get_wizard_hints():
                applied[f"_detected_{hint.provider_id}"] = hint.provider_label
        except Exception as exc:
            _LOGGER.debug("Battery provider scan failed: %s", exc)

        self._auto_detect_results = applied

        # Build summary lines
        applied_lines  = [f"✅ {label}: `{val}`" for label, val in applied.items()
                          if not label.startswith("_detected_")]
        provider_lines = [f"🔋 {val} gedetecteerd" for key, val in applied.items()
                          if key.startswith("_detected_")]
        skipped_lines  = [f"⏭️ {label}: {val}" for label, val in skipped.items()]

        applied_text  = "\n".join(applied_lines + provider_lines) or "Niets nieuws gevonden"
        skipped_text  = "\n".join(skipped_lines) or "—"

        return self.async_show_form(
            step_id="auto_detect",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
            }),
            description_placeholders={
                "applied":  applied_text,
                "skipped":  skipped_text,
                "count":    str(len(applied_lines) + len(provider_lines)),
            },
        )


    async def async_step_menu_energie(self, user_input=None):
        """Submenu: Energie & Grid."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_energie",
            data_schema=vol.Schema({
                vol.Required("section", default="sensors"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="sensors",      label="🔌 Grid Sensoren"),
                        selector.SelectOptionDict(value="phase_sensors", label="⚡ Fase Sensoren"),
                        selector.SelectOptionDict(value="prices_opts",  label="💶 Prijzen & Belasting"),
                        selector.SelectOptionDict(value="budget_opts",  label="📊 Energiebudget"),
                        selector.SelectOptionDict(value="advanced_opts", label="📡 P1 & Geavanceerd"),
                        selector.SelectOptionDict(value="egauge_opts",      label="📊 eGauge Submeter"),
                        selector.SelectOptionDict(value="neighbourhood_opts", label="🏘️ Buurtenergie (P2P)"),
                        selector.SelectOptionDict(value="blackout_guard_opts",label="⚡ Blackout Guard"),
                        selector.SelectOptionDict(value="fcr_opts",           label="📈 FCR/aFRR Virtuele Powerplant"),
                        selector.SelectOptionDict(value="noodstroom",   label="⚡ Noodstroom & Backup"),
                        selector.SelectOptionDict(value="__terug__",    label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_noodstroom(self, user_input=None):
        """Submenu: Noodstroom & Backup."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_menu_energie()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="noodstroom",
            data_schema=vol.Schema({
                vol.Required("section", default="generator_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="generator_opts", label="🔧 Generator / Aggregaat"),
                        selector.SelectOptionDict(value="ups_count_opts", label="🔋 UPS Systemen"),
                        selector.SelectOptionDict(value="__terug__",      label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_menu_opwekking(self, user_input=None):
        """Submenu: Opwekking & Opslag."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_opwekking",
            data_schema=vol.Schema({
                vol.Required("section", default="inverters_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="inverters_opts", label="🔆 PV Omvormers & Zonnebegrenzing"),
                        selector.SelectOptionDict(value="batteries_opts", label="🔋 Batterijen & Providers"),
                        selector.SelectOptionDict(value="__terug__",      label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_menu_verbruik(self, user_input=None):
        """Submenu: Verbruik & Comfort."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_verbruik",
            data_schema=vol.Schema({
                vol.Required("section", default="boiler_groups_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="boiler_groups_opts", label="🚿 Boiler Controller"),
                        selector.SelectOptionDict(value="multisplit_count_opts", label="❄️ Airco / Multisplit"),
                        selector.SelectOptionDict(value="climate_opts",       label="🌡️ Klimaatbeheer"),
                        selector.SelectOptionDict(value="shutter_count_opts", label="🪟 Rolluiken"),
                        selector.SelectOptionDict(value="pool_opts",          label="🏊 Zwembad Controller"),
                        selector.SelectOptionDict(value="lamp_circ_opts",      label="💡 Lampcirculatie & Beveiliging"),
                        selector.SelectOptionDict(value="lamp_automation_opts", label="🏠 Lamp Automatisering (aan/uit per ruimte)"),
                        selector.SelectOptionDict(value="gas_opts",           label="🔥 Gas & Warmte"),
                        selector.SelectOptionDict(value="__terug__",          label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_menu_automatisering(self, user_input=None):
        """Submenu: Automatisering & NILM."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_automatisering",
            data_schema=vol.Schema({
                vol.Required("section", default="ai_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="ai_opts",              label="🤖 AI & NILM"),
                        selector.SelectOptionDict(value="nilm_shift_opts",      label="🔀 NILM Lastverschuiving"),
                        selector.SelectOptionDict(value="nilm_devices_opts",    label="🏷️ NILM Apparaten beheren"),
                        selector.SelectOptionDict(value="cheap_switches_opts",  label="⚡ Goedkope Uren Schakelaars"),
                        selector.SelectOptionDict(value="features_opts",        label="🚀 Features"),
                        selector.SelectOptionDict(value="__terug__",            label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_menu_mobiliteit(self, user_input=None):
        """Submenu: Mobiliteit & Laden."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_mobiliteit",
            data_schema=vol.Schema({
                vol.Required("section", default="solar_ev_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="ev_opts",        label="🚗 EV Laadpalen"),
                        selector.SelectOptionDict(value="ebike_count",    label="🚲 E-bike & Micro-mobiliteit"),
                        selector.SelectOptionDict(value="v2h_opts",       label="🔄 Vehicle-to-Home (V2H)"),
                        selector.SelectOptionDict(value="ev_trip_opts",    label="🗓️ EV Ritplanning (kalender)"),
                        selector.SelectOptionDict(value="__terug__",      label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_menu_dashboard(self, user_input=None):
        """Dashboard & Weergave instellingen."""
        from .const import CONF_LICENSE_KEY
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._opts["iso_house_type"]      = user_input.get("iso_house_type", "modern")
            self._opts["iso_custom_image_url"] = user_input.get("iso_custom_image_url", "")
            return self._save(self._opts)

        data = self._data()
        return self.async_show_form(
            step_id="menu_dashboard",
            data_schema=vol.Schema({
                vol.Optional("iso_house_type", default=data.get("iso_house_type", "modern")):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="modern",    label="Modern (glas/flat dak)"),
                        selector.SelectOptionDict(value="villa",     label="Villa"),
                        selector.SelectOptionDict(value="terraced",  label="Rijtjeshuis"),
                        selector.SelectOptionDict(value="apartment", label="Appartement"),
                        selector.SelectOptionDict(value="farmhouse", label="Boerderij"),
                        selector.SelectOptionDict(value="custom",    label="Eigen foto (URL invullen)"),
                    ], mode="list")),
                vol.Optional("iso_custom_image_url", default=data.get("iso_custom_image_url", "")):
                    selector.TextSelector(selector.TextSelectorConfig(type="url")),
            }),
            description_placeholders={
                "info": "Kies een huistype voor de isometrische energiekaart. Bij 'Eigen foto' vult CloudEMS AI automatisch de elementposities in.",
            },
        )

    async def async_step_menu_systeem(self, user_input=None):
        """Submenu: Systeem & Communicatie."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section")
            if section == "__terug__":
                return await self.async_step_init()
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="menu_systeem",
            data_schema=vol.Schema({
                vol.Required("section", default="mail_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="mail_opts",     label="📧 E-mail rapporten"),
                        selector.SelectOptionDict(value="demo_opts",     label="🎮 Demo modus"),
                        selector.SelectOptionDict(value="__terug__",     label="← Terug"),
                    ], mode="list"))
            }),
        )

    async def async_step_demo_opts(self, user_input=None):
        """Demo modus — virtuele installatie met tijdversnelling."""
        from .const import CONF_DEMO_ENABLED, CONF_DEMO_SPEED
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Zet demo aan/uit via coordinator
            enabled = bool(user_input.get(CONF_DEMO_ENABLED, False))
            speed   = int(user_input.get(CONF_DEMO_SPEED, 48))
            coord   = self.hass.data.get("cloudems", {})
            if hasattr(coord, "set_demo_mode"):
                await coord.set_demo_mode(enabled, speed)
            return self._save(user_input)
        enabled = bool(data.get(CONF_DEMO_ENABLED, False))
        speed   = int(data.get(CONF_DEMO_SPEED, 48))
        return self.async_show_form(
            step_id="demo_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEMO_ENABLED, default=enabled): bool,
                vol.Optional(CONF_DEMO_SPEED, default=speed): vol.In({
                    1: "1x — realtime",
                    10: "10x — dag in 2.4 uur",
                    48: "48x — dag in 30 min",
                    96: "96x — dag in 15 min",
                }),
            }),
            description_placeholders={
                "info": "Demo modus simuleert een volledige energie-installatie. "
                        "Echte sensoren en geleerde data blijven onaangetast."
            },
        )

    async def async_step_sensors(self, user_input=None):
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # L1 is leidend — L2 en L3 automatisch gelijk stellen als 3-fase
            _l1 = float(user_input.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))
            if phase_count == 3:
                user_input[CONF_MAX_CURRENT_L2] = _l1
                user_input[CONF_MAX_CURRENT_L3] = _l1
            user_input[CONF_MAX_CURRENT_PER_PHASE] = _l1
            return self._save(user_input)

        dsmr_type_opts = [
            selector.SelectOptionDict(value=k, label=v)
            for k, v in DSMR_TYPE_LABELS.items()
        ]
        use_sep = bool(data.get(CONF_USE_SEPARATE_IE, False))
        schema: dict = {
            vol.Optional(CONF_USE_SEPARATE_IE, default=use_sep): bool,
            vol.Optional(CONF_MAINS_VOLTAGE, default=float(data.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))):
                vol.All(vol.Coerce(float), vol.Range(min=100, max=480)),
            vol.Optional(CONF_PHASE_COUNT, default=phase_count): vol.In({1: "1 phase", 3: "3 phases"}),
            vol.Optional(CONF_MAX_CURRENT_L1, default=float(data.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))):
                vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
            vol.Optional(CONF_DSMR_TYPE, default=data.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL)):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=dsmr_type_opts, mode=selector.SelectSelectorMode.LIST)
                ),
        }
        if not use_sep:
            schema[vol.Optional(CONF_GRID_SENSOR, default=data.get(CONF_GRID_SENSOR) or vol.UNDEFINED)] = _ent()
        else:
            schema[vol.Optional(CONF_IMPORT_SENSOR, default=data.get(CONF_IMPORT_SENSOR) or vol.UNDEFINED)] = _ent()
            schema[vol.Optional(CONF_EXPORT_SENSOR, default=data.get(CONF_EXPORT_SENSOR) or vol.UNDEFINED)] = _ent()
        return self.async_show_form(step_id="sensors", data_schema=vol.Schema(schema))

    async def async_step_phase_sensors(self, user_input=None):
        """Redirect naar L1 — entry point blijft werken vanuit het menu."""
        return await self.async_step_phase_sensors_l1(user_input)

    async def async_step_phase_sensors_l1(self, user_input=None):
        """⚡ Fase L1 — stroom, spanning, vermogen."""
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._pending = {**self._pending, **user_input} if hasattr(self, "_pending") else dict(user_input)
            if phase_count == 3:
                return await self.async_step_phase_sensors_l2()
            # 1-fase: sla direct op
            return self._save(self._pending)

        schema: dict = {}
        for k in [CONF_PHASE_SENSORS+"_L1", CONF_VOLTAGE_L1, CONF_POWER_L1,
                  "power_sensor_l1_export"]:
            schema[vol.Optional(k, default=data.get(k) or vol.UNDEFINED)] = _ent()
        return self.async_show_form(
            step_id="phase_sensors_l1",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/phase_sensor_l1.svg",
                "phase_count": str(phase_count),
            },
        )

    async def async_step_phase_sensors_l2(self, user_input=None):
        """⚡ Fase L2 — stroom, spanning, vermogen."""
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._pending = {**getattr(self, "_pending", {}), **user_input}
            return await self.async_step_phase_sensors_l3()

        schema: dict = {}
        for k in [CONF_PHASE_SENSORS+"_L2", CONF_VOLTAGE_L2, CONF_POWER_L2,
                  "power_sensor_l2_export"]:
            schema[vol.Optional(k, default=data.get(k) or vol.UNDEFINED)] = _ent()
        return self.async_show_form(
            step_id="phase_sensors_l2",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/phase_sensor_l2.svg",
                "phase_count": str(phase_count),
            },
        )

    async def async_step_phase_sensors_l3(self, user_input=None):
        """⚡ Fase L3 — stroom, spanning, vermogen."""
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            merged = {**getattr(self, "_pending", {}), **user_input}
            self._pending = {}
            return self._save(merged)

        schema: dict = {}
        for k in [CONF_PHASE_SENSORS+"_L3", CONF_VOLTAGE_L3, CONF_POWER_L3,
                  "power_sensor_l3_export"]:
            schema[vol.Optional(k, default=data.get(k) or vol.UNDEFINED)] = _ent()
        return self.async_show_form(
            step_id="phase_sensors_l3",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "diagram_url": "/local/cloudems/diagrams/phase_sensor_l3.svg",
                "phase_count": str(phase_count),
            },
        )

    async def async_step_multisplit_count_opts(self, user_input=None):
        """❄️ Airco / Multisplit — eerst het aantal buitenunits kiezen."""
        from .const import CONF_MULTISPLIT_GROUPS
        data = self._data()
        current_groups = data.get(CONF_MULTISPLIT_GROUPS, [])
        current_count = len(current_groups)

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            count = int(user_input.get("multisplit_count", current_count))
            if count == 0:
                # Verwijder alle groepen
                self._config[CONF_MULTISPLIT_GROUPS] = []
                return self._save(user_input)
            # Sla gewenst aantal op als hint voor multisplit_opts
            self._multisplit_target_count = count
            return await self.async_step_multisplit_opts()

        count_opts = [
            selector.SelectOptionDict(value=str(i), label=str(i) if i > 0 else "0 — Airco uitschakelen")
            for i in range(6)
        ]
        return self.async_show_form(
            step_id="multisplit_count_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("multisplit_count", default=str(current_count) if current_count else "1"): _inverter_count_selector(),
            }),
            description_placeholders={
                "info": (
                    f"Huidig geconfigureerd: {current_count} buitenunit(s). "
                    "Kies het gewenste aantal."
                )
            },
        )

    async def async_step_multisplit_opts(self, user_input=None):
        """❄️ Airco / Multisplit — buitenunits en binnenunits configureren."""
        from .const import CONF_MULTISPLIT_GROUPS, MULTISPLIT_BRANDS
        data = self._data()
        errors: dict = {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back

            # Build groepsconfig op vanuit user_input
            groups = data.get(CONF_MULTISPLIT_GROUPS, [])

            action = user_input.get("action", "save")
            if action == "add_group":
                # Voeg nieuwe lege groep toe
                new_group = {
                    "id":           f"airco_{len(groups)+1}",
                    "label":        user_input.get("new_label", f"Airco {len(groups)+1}"),
                    "power_sensor": user_input.get("new_power_sensor", ""),
                    "freq_sensor":  user_input.get("new_freq_sensor", ""),
                    "brand":        user_input.get("new_brand", "generic"),
                    "indoor_units": [],
                }
                groups = list(groups) + [new_group]
                data[CONF_MULTISPLIT_GROUPS] = groups
                self._config[CONF_MULTISPLIT_GROUPS] = groups
                self._multisplit_indoor_group_idx = len(groups) - 1
                return await self.async_step_multisplit_indoor_count_opts()
            elif action == "edit_group":
                idx = int(user_input.get("edit_idx", 0))
                self._multisplit_indoor_group_idx = idx
                return await self.async_step_multisplit_indoor_count_opts()
            elif action == "delete_group":
                idx = int(user_input.get("delete_idx", 0))
                groups = [g for i, g in enumerate(groups) if i != idx]
                self._config[CONF_MULTISPLIT_GROUPS] = groups
                return await self.async_step_multisplit_opts()
            else:
                return self._save(user_input)

        groups = data.get(CONF_MULTISPLIT_GROUPS, [])

        # Toon overzicht + formulier voor nieuwe groep
        brand_options = [
            selector.SelectOptionDict(value=k, label=v)
            for k, v in MULTISPLIT_BRANDS.items()
        ]
        # Build action opties
        action_options = [
            selector.SelectOptionDict(value="add_group", label="➕ Nieuwe buitenunit toevoegen"),
            selector.SelectOptionDict(value="save",      label="✅ Opslaan"),
        ]
        for i, g in enumerate(groups):
            action_options.insert(i, selector.SelectOptionDict(
                value=f"edit_{i}", label=f"✏️ {g.get('label','Airco')} bewerken"
            ))

        return self.async_show_form(
            step_id="multisplit_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                # Nieuwe buitenunit
                vol.Optional("new_label",        default=""): str,
                vol.Optional("new_brand",        default="generic"):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=brand_options, mode="dropdown"
                    )),
                vol.Optional("new_power_sensor", default=vol.UNDEFINED): _ent(),
                vol.Optional("new_freq_sensor",  default=vol.UNDEFINED): _ent(),
                vol.Optional("action",           default="add_group"):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=action_options, mode="list"
                    )),
            }),
            description_placeholders={
                "info": (
                    f"Geconfigureerde buitenunits: {len(groups)}\n"
                    + "\n".join(
                        f"• {g.get('label','?')} — {len(g.get('indoor_units',[]))} binnenunits, "
                        f"vermogenssensor: {g.get('power_sensor','—')}"
                        for g in groups
                    )
                    if groups else
                    "Nog geen airco/multisplit geconfigureerd. "
                    "Voeg een buitenunit toe met de vermogenssensor en de bijbehorende binnenunits."
                )
            },
            errors=errors,
        )

    async def async_step_multisplit_indoor_count_opts(self, user_input=None):
        """❄️ Hoeveel binnenunits heeft deze buitenunit?"""
        from .const import CONF_MULTISPLIT_GROUPS
        data = self._data()
        groups = list(data.get(CONF_MULTISPLIT_GROUPS, []))
        group_idx = getattr(self, "_multisplit_indoor_group_idx", 0)
        group = groups[group_idx] if group_idx < len(groups) else {}
        current_units = len(group.get("indoor_units", []))

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            count = int(user_input.get("indoor_count", 1))
            self._multisplit_indoor_target = count
            # Ga naar indoor_opts om de units te configureren
            return await self.async_step_multisplit_indoor_opts(group_idx=group_idx)

        count_opts = [
            selector.SelectOptionDict(value=str(i), label=str(i) if i > 0 else "0 — Geen binnenunits")
            for i in range(9)
        ]
        group_label = group.get("label", f"Buitenunit {group_idx + 1}")
        return self.async_show_form(
            step_id="multisplit_indoor_count_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("indoor_count", default=str(max(current_units, 1))):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=count_opts, mode="list"
                    )),
            }),
            description_placeholders={
                "info": (
                    f"Buitenunit: {group_label}\n"
                    f"Huidig geconfigureerd: {current_units} binnenunit(s).\n"
                    "Een binnenunit is één ruimte/zone die door deze buitenunit bediend wordt."
                )
            },
        )

    async def async_step_multisplit_indoor_opts(self, user_input=None, group_idx: int = 0):
        """Binnenunits configureren voor één buitenunit."""
        from .const import CONF_MULTISPLIT_GROUPS
        data = self._data()
        groups = list(data.get(CONF_MULTISPLIT_GROUPS, []))
        if group_idx >= len(groups):
            return await self.async_step_multisplit_opts()

        group = groups[group_idx]

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back

            action = user_input.get("action", "save")
            if action == "add_unit":
                eid   = user_input.get("unit_entity", "")
                label = user_input.get("unit_label", eid.split(".")[-1] if eid else "")
                area  = user_input.get("unit_area", "")
                freq  = user_input.get("unit_freq_sensor", "")
                if eid:
                    units = list(group.get("indoor_units", []))
                    # Autodetectie energiesensoren op basis van merk + entity basis-naam
                    brand = group.get("brand", "generic")
                    unit_dict = {
                        "entity_id":  eid,
                        "label":      label,
                        "area":       area,
                        "freq_sensor":freq,
                    }
                    if brand == "daikin":
                        # Daikin: zoek cool/heat/total energy sensoren
                        # entity = climate.daikin_abc → basis = daikin_abc
                        base = eid.split(".", 1)[-1]
                        all_states = self.hass.states.async_all("sensor")
                        for st in all_states:
                            sid = st.entity_id.lower()
                            if base.lower() in sid:
                                if "cool_energy" in sid:
                                    unit_dict["energy_cool_sensor"] = st.entity_id
                                elif "heat_energy" in sid:
                                    unit_dict["energy_heat_sensor"] = st.entity_id
                                elif "total_energy" in sid:
                                    unit_dict["energy_total_sensor"] = st.entity_id
                    units.append(unit_dict)
                    group["indoor_units"] = units
                    groups[group_idx] = group
                    self._config[CONF_MULTISPLIT_GROUPS] = groups
            elif action.startswith("del_"):
                unit_idx = int(action[4:])
                units = [u for i, u in enumerate(group.get("indoor_units", []))
                         if i != unit_idx]
                group["indoor_units"] = units
                groups[group_idx] = group
                self._config[CONF_MULTISPLIT_GROUPS] = groups
            else:
                return await self.async_step_multisplit_opts()
            return await self.async_step_multisplit_indoor_opts(group_idx=group_idx)

        units = group.get("indoor_units", [])
        unit_action_opts = [
            selector.SelectOptionDict(value="add_unit", label="➕ Binnenunit toevoegen"),
            selector.SelectOptionDict(value="save",     label="✅ Klaar"),
        ]
        for i, u in enumerate(units):
            unit_action_opts.insert(i, selector.SelectOptionDict(
                value=f"del_{i}",
                label=f"🗑️ {u.get('label','Unit')} verwijderen"
            ))

        return self.async_show_form(
            step_id="multisplit_indoor_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Optional("unit_entity",      default=vol.UNDEFINED):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["climate"])),
                vol.Optional("unit_label",       default=""): str,
                vol.Optional("unit_area",        default=""): str,
                vol.Optional("unit_freq_sensor", default=vol.UNDEFINED): _ent(),
                vol.Optional("action",           default="add_unit"):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=unit_action_opts, mode="list"
                    )),
            }),
            description_placeholders={
                "group_label": group.get("label", "Airco"),
                "info": (
                    f"Buitenunit: {group.get('label','?')} | "
                    f"Vermogen: {group.get('power_sensor','—')}\n\n"
                    + ("Geconfigureerde binnenunits:\n" +
                       "\n".join(f"• {u.get('label','?')} ({u.get('entity_id','?')}) "
                                  f"— ruimte: {u.get('area','—')}"
                                  for u in units)
                       if units else "Nog geen binnenunits.")
                )
            },
        )


    async def async_step_geofencing_opts(self, user_input=None):
        """Geofencing actions configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="geofencing_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("geofencing_enabled", default=bool(data.get("geofencing_enabled", False))): bool,
                vol.Optional("geofencing_arrival_switches",   default=data.get("geofencing_arrival_switches") or []): selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch","light"], multiple=True)),
                vol.Optional("geofencing_departure_switches", default=data.get("geofencing_departure_switches") or []): selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch","light"], multiple=True)),
                vol.Optional("geofencing_arrival_thermostat", default=data.get("geofencing_arrival_thermostat") or vol.UNDEFINED): _ent(["climate"]),
                vol.Optional("geofencing_arrival_temp",   default=float(data.get("geofencing_arrival_temp",   20.0))): vol.Coerce(float),
                vol.Optional("geofencing_departure_temp", default=float(data.get("geofencing_departure_temp", 17.0))): vol.Coerce(float),
                vol.Required("geofencing_notify", default=bool(data.get("geofencing_notify", False))): bool,
            }),
        )

    async def async_step_sleep_switch_opts(self, user_input=None):
        """Sleep group switch configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="sleep_switch_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("sleep_switch_enabled", default=bool(data.get("sleep_switch_enabled", False))): bool,
                vol.Optional("sleep_switch_entities", default=data.get("sleep_switch_entities") or []): selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch","light"], multiple=True)),
                vol.Optional("sleep_thermostat_entity", default=data.get("sleep_thermostat_entity") or vol.UNDEFINED): _ent(["climate"]),
                vol.Optional("sleep_thermostat_setpoint", default=float(data.get("sleep_thermostat_setpoint", 17.0))): vol.Coerce(float),
                vol.Required("sleep_restore_on_wake", default=bool(data.get("sleep_restore_on_wake", True))): bool,
            }),
        )

    async def async_step_fcr_opts(self, user_input=None):
        """FCR/aFRR virtual power plant configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="fcr_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("fcr_enabled", default=bool(data.get("fcr_enabled", False))): bool,
            }),
        )


    async def async_step_neighbourhood_opts(self, user_input=None):
        """Neighbourhood P2P energy sharing configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="neighbourhood_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("neighbourhood_enabled", default=bool(data.get("neighbourhood_enabled", False))): bool,
                vol.Optional("neighbourhood_mqtt_broker", default=data.get("neighbourhood_mqtt_broker", "") or vol.UNDEFINED): str,
                vol.Optional("neighbourhood_mqtt_port",   default=int(data.get("neighbourhood_mqtt_port", 1883))): vol.Coerce(int),
                vol.Optional("neighbourhood_max_share_w", default=float(data.get("neighbourhood_max_share_w", 1000.0))): vol.Coerce(float),
            }),
        )

    async def async_step_blackout_guard_opts(self, user_input=None):
        """Blackout guard configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="blackout_guard_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("blackout_guard_enabled", default=bool(data.get("blackout_guard_enabled", True))): bool,
                vol.Optional("blackout_freq_entity",    default=data.get("blackout_freq_entity")    or vol.UNDEFINED): _ent(["sensor"]),
                vol.Optional("blackout_voltage_entity", default=data.get("blackout_voltage_entity") or vol.UNDEFINED): _ent(["sensor"]),
            }),
        )


    async def async_step_auto_apply(self, user_input=None):
        """Auto-detect and apply all discoverable settings."""
        data = self._data()
        applied = []
        skipped = []

        # 1. HA Energy dashboard scan
        try:
            from .energy_autodiscover import async_discover_from_energy_dashboard
            disc = await async_discover_from_energy_dashboard(self.hass)
            if disc.confidence != "none":
                prefill = disc.to_config_prefill()
                for k, v in prefill.items():
                    if v and not data.get(k):
                        data[k] = v
                        applied.append(f"✅ {k}: {str(v)[:40]}")
                    elif data.get(k):
                        skipped.append(f"⏭ {k}: al geconfigureerd")
        except Exception as e:
            skipped.append(f"⚠️ Energy dashboard: {e}")

        # 2. P1/DSMR integration
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)
            dsmr_found = any(
                e.platform in ("dsmr", "homewizard", "p1_monitor")
                for e in ent_reg.entities.values()
            )
            if dsmr_found and not data.get("p1_enabled"):
                data["p1_enabled"] = True
                applied.append("✅ P1/DSMR: automatisch geactiveerd")
        except Exception:
            pass

        # 3. Battery providers
        try:
            from .energy_manager.battery_provider import BatteryProviderRegistry
            from .energy_manager.victron_provider import VictronProvider      # noqa
            from .energy_manager.sma_battery_provider import SMABatteryProvider  # noqa
            from .energy_manager.huawei_luna_provider import HuaweiLunaProvider  # noqa
            registry = BatteryProviderRegistry(self.hass, data)
            await registry.async_setup()
            for p in registry.detected_providers:
                key = f"{p.PROVIDER_ID}_enabled"
                if not data.get(key):
                    data[key] = True
                    applied.append(f"✅ Batterij provider: {p.PROVIDER_LABEL}")
        except Exception as e:
            skipped.append(f"⚠️ Battery providers: {e}")

        # Save applied config
        if applied:
            self._opts.update(data)

        if user_input is not None:
            return self._save(self._opts)

        applied_text = "\n".join(applied) if applied else "Niets nieuws gevonden"
        skipped_text = "\n".join(skipped[:5]) if skipped else "—"

        return self.async_show_form(
            step_id="auto_apply",
            data_schema=vol.Schema({}),
            description_placeholders={
                "applied": applied_text,
                "skipped": skipped_text,
                "count":   str(len(applied)),
            },
        )


    async def async_step_vacation_opts(self, user_input=None):
        """Vacation mode configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="vacation_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("vacation_enabled", default=bool(data.get("vacation_enabled", False))): bool,
                vol.Optional("vacation_switch_entities", default=data.get("vacation_switch_entities") or []): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch", multiple=True)),
                vol.Optional("vacation_boiler_setpoint", default=float(data.get("vacation_boiler_setpoint", 45.0))): vol.Coerce(float),
                vol.Required("vacation_notify", default=bool(data.get("vacation_notify", True))): bool,
            }),
        )

    async def async_step_appliance_done_opts(self, user_input=None):
        """Appliance done notifier configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="appliance_done_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
            }),
            description_placeholders={
                "tip": "Configureer apparaten via de CloudEMS YAML configuratie: done_notifier_appliances lijst met label, power_entity, start_threshold_w, idle_threshold_w.",
            },
        )

    async def async_step_standby_killer_opts(self, user_input=None):
        """Standby killer configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="standby_killer_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
            }),
            description_placeholders={
                "tip": "Configureer groepen via de CloudEMS YAML configuratie: standby_killer_groups lijst met label, switch_entities, away_delay_min, restore_on_home.",
            },
        )

    async def async_step_circadian_nudge_opts(self, user_input=None):
        """Circadian nudge lighting configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="circadian_nudge_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("circadian_nudge_enabled", default=bool(data.get("circadian_nudge_enabled", False))): bool,
                vol.Required("circadian_nudge_mode", default=data.get("circadian_nudge_mode", "nudge")): selector.SelectSelector(selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value="nudge",     label="💡 Nudge — subtiele aanpassing (5-8%)"),
                    selector.SelectOptionDict(value="circadian", label="🌅 Circadian — volledige HCL op hernieuwbare energie"),
                    selector.SelectOptionDict(value="both",      label="✨ Beide — gecombineerd"),
                ], mode="list")),
                vol.Optional("circadian_nudge_entities", default=data.get("circadian_nudge_entities") or []): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional("circadian_nudge_max_shift", default=int(data.get("circadian_nudge_max_shift", 8))): vol.All(vol.Coerce(int), vol.Range(min=2, max=25)),
                vol.Optional("circadian_nudge_transition", default=int(data.get("circadian_nudge_transition", 30))): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
            }),
        )


    async def async_step_ev_trip_opts(self, user_input=None):
        """EV Trip Planner — calendar-based charging configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="ev_trip_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("ev_trip_enabled", default=bool(data.get("ev_trip_enabled", False))): bool,
                vol.Optional("ev_kwh_per_pct", default=float(data.get("ev_kwh_per_pct", 0.77))): vol.Coerce(float),
                vol.Optional("ev_soc_entity", default=data.get("ev_soc_entity", "") or vol.UNDEFINED): _ent(["sensor"]),
            }),
        )


    async def async_step_v2h_opts(self, user_input=None):
        """Vehicle-to-Home (V2H) configuration."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="v2h_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("v2h_enabled", default=bool(data.get("v2h_enabled", False))): bool,
                vol.Optional("v2h_charger_entity", default=data.get("v2h_charger_entity", "") or vol.UNDEFINED): _ent(["select","sensor","switch","number"]),
                vol.Optional("v2h_car_soc_entity",  default=data.get("v2h_car_soc_entity",  "") or vol.UNDEFINED): _ent(["sensor"]),
                vol.Optional("v2h_min_soc_pct",     default=float(data.get("v2h_min_soc_pct",     30.0))): vol.Coerce(float),
                vol.Optional("v2h_price_threshold", default=float(data.get("v2h_price_threshold", 0.25))): vol.Coerce(float),
                vol.Optional("v2h_max_discharge_w", default=float(data.get("v2h_max_discharge_w", 3700.0))): vol.Coerce(float),
            }),
        )


    async def async_step_egauge_opts(self, user_input=None):
        """eGauge smart meter configuration — auto-detects entities."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)

        # Auto-detect eGauge entities and pre-fill
        from .energy_manager.egauge_provider import EGaugeProvider
        _eg = EGaugeProvider(self.hass)
        await _eg.async_setup()
        _info = _eg.get_info()

        def _pre(key):
            """Return saved value, then auto-detected, then UNDEFINED."""
            saved = data.get(key, "")
            if saved:
                return saved
            auto = _info.get(key.replace("egauge_", "").replace("_entity", "_entity"), "")
            # Map info keys to config keys
            key_map = {
                "egauge_net_entity":   _info.get("net_entity", ""),
                "egauge_l1_entity":    (_info.get("phase_entities") or {}).get("L1", ""),
                "egauge_l2_entity":    (_info.get("phase_entities") or {}).get("L2", ""),
                "egauge_l3_entity":    (_info.get("phase_entities") or {}).get("L3", ""),
                "egauge_solar_entity": _info.get("solar_entity", ""),
            }
            v = key_map.get(key, "")
            return v or vol.UNDEFINED

        detected = _eg.is_detected
        return self.async_show_form(
            step_id="egauge_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("egauge_enabled", default=bool(data.get("egauge_enabled", detected))): bool,
                vol.Optional("egauge_net_entity",    default=_pre("egauge_net_entity")   ): _ent(["sensor"]),
                vol.Optional("egauge_l1_entity",     default=_pre("egauge_l1_entity")    ): _ent(["sensor"]),
                vol.Optional("egauge_l2_entity",     default=_pre("egauge_l2_entity")    ): _ent(["sensor"]),
                vol.Optional("egauge_l3_entity",     default=_pre("egauge_l3_entity")    ): _ent(["sensor"]),
                vol.Optional("egauge_solar_entity",  default=_pre("egauge_solar_entity") ): _ent(["sensor"]),
            }),
            description_placeholders={
                "detected": "✅ eGauge gedetecteerd — entiteiten vooringevuld" if detected
                            else "⚠️ Geen eGauge gevonden — vul handmatig in als je een eGauge hebt",
            },
        )


    async def async_step_ebike_count(self, user_input=None):
        """🚲 E-bike & Micro-mobiliteit — aantal voertuigen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._ebike_count = int(user_input.get("ebike_count_sel", 0))
            self._existing_ebike_cfgs = [
                {"entity_id": data.get(f"ebike_entity_{i+1}", ""), "label": data.get(f"ebike_label_{i+1}", f"E-bike {i+1}")}
                for i in range(10) if data.get(f"ebike_entity_{i+1}")
            ]
            self._config["ebike_configs"] = []
            self._ebike_step = 0
            if self._ebike_count > 0:
                return await self.async_step_ebike_detail()
            return self._save({})
        existing_count = str(len([i for i in range(10) if data.get(f"ebike_entity_{i+1}")]))
        return self.async_show_form(
            step_id="ebike_count",
            data_schema=vol.Schema({
                vol.Required("ebike_count_sel", default=existing_count): _inverter_count_selector(),
            }),
        )

    async def async_step_ebike_detail(self, user_input=None):
        """🚲 E-bike detail (herhaalt per voertuig)."""
        i = self._ebike_step + 1
        existing_cfgs = getattr(self, "_existing_ebike_cfgs", [])
        existing = existing_cfgs[self._ebike_step] if self._ebike_step < len(existing_cfgs) else {}
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            cfg = {
                "entity_id": user_input.get("ebike_entity", ""),
                "label":     user_input.get("ebike_label", f"E-bike {i}"),
            }
            self._config["ebike_configs"].append(cfg)
            # Backwards compat: ook als ebike_entity_1/label_1 etc opslaan
            self._config[f"ebike_entity_{self._ebike_step+1}"] = cfg["entity_id"]
            self._config[f"ebike_label_{self._ebike_step+1}"] = cfg["label"]
            self._ebike_step += 1
            if self._ebike_step < self._ebike_count:
                return await self.async_step_ebike_detail()
            return self._save({})
        return self.async_show_form(
            step_id="ebike_detail",
            data_schema=vol.Schema({
                vol.Optional("ebike_entity", default=existing.get("entity_id", "") or vol.UNDEFINED): _ent(["sensor"]),
                vol.Optional("ebike_label", default=existing.get("label", f"E-bike {i}")): str,
            }),
            description_placeholders={"ebike_num": str(i), "total": str(self._ebike_count)},
        )


    async def async_step_ebike_opts(self, user_input=None):
        """🚲 E-bike & Micro-mobiliteit instellingen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)

        existing = data
        return self.async_show_form(
            step_id="ebike_opts",
            data_schema=vol.Schema({
                vol.Optional("ebike_entity_1", default=existing.get("ebike_entity_1", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"])
                ),
                vol.Optional("ebike_label_1", default=existing.get("ebike_label_1", "")): str,
                vol.Optional("ebike_entity_2", default=existing.get("ebike_entity_2", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"])
                ),
                vol.Optional("ebike_label_2", default=existing.get("ebike_label_2", "")): str,
            }),
            description_placeholders={
                "info": (
                    "🚲 E-bikes en scooters worden automatisch gedetecteerd via NILM (40–700W laadpatroon). "
                    "Optioneel: koppel een vermogenssensor per voertuig voor nauwkeuriger sessietracking. "
                    "Labels worden getoond op het dashboard."
                )
            },
        )

    async def async_step_solar_opts(self, user_input=None):
        """☀️ PV Zonnepanelen — sensor en instellingen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="solar_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SOLAR_SENSOR, default=data.get(CONF_SOLAR_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_BATTERY_SENSOR, default=data.get(CONF_BATTERY_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=float(data.get(CONF_NEGATIVE_PRICE_THRESHOLD, 0.0))): vol.Coerce(float),
            }),
        )

    async def async_step_ev_opts(self, user_input=None):
        """🚗 EV Laadpalen — aantal en details."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            ev_count = int(user_input.get("ev_charger_count_sel", 0))
            self._ev_charger_count = ev_count
            self._existing_ev_cfgs = list(data.get(CONF_EV_CHARGER_CONFIGS, []))
            if not self._existing_ev_cfgs and data.get(CONF_EV_CHARGER_ENTITY):
                self._existing_ev_cfgs = [{"entity_id": data.get(CONF_EV_CHARGER_ENTITY), "label": "EV Laadpaal 1"}]
            self._config[CONF_EV_CHARGER_COUNT] = ev_count
            self._config[CONF_EV_CHARGER_CONFIGS] = []
            self._ev_charger_step = 0
            if ev_count > 0:
                return await self.async_step_ev_charger_detail()
            return self._save({})
        existing_count = str(len(data.get(CONF_EV_CHARGER_CONFIGS, [])) or (1 if data.get(CONF_EV_CHARGER_ENTITY) else 0))
        return self.async_show_form(
            step_id="ev_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("ev_charger_count_sel", default=existing_count): _inverter_count_selector(),
            }),
        )


    async def async_step_ev_charger_detail(self, user_input=None):
        """🚗 EV Laadpaal detail (herhaalt per laadpaal)."""
        i = self._ev_charger_step + 1
        existing_cfgs = getattr(self, "_existing_ev_cfgs", [])
        existing = existing_cfgs[self._ev_charger_step] if self._ev_charger_step < len(existing_cfgs) else {}
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._config[CONF_EV_CHARGER_CONFIGS].append({
                "entity_id": user_input.get("ev_charger_entity", ""),
                "label":     user_input.get("ev_charger_label", f"EV Laadpaal {i}"),
                "switch":    user_input.get("ev_charger_switch", ""),
            })
            # Backwards compat: zet eerste als CONF_EV_CHARGER_ENTITY
            if self._ev_charger_step == 0:
                self._config[CONF_EV_CHARGER_ENTITY] = user_input.get("ev_charger_entity", "")
            self._ev_charger_step += 1
            if self._ev_charger_step < self._ev_charger_count:
                return await self.async_step_ev_charger_detail()
            return self._save({})
        return self.async_show_form(
            step_id="ev_charger_detail",
            data_schema=vol.Schema({
                vol.Required("ev_charger_entity", description={"suggested_value": existing.get("entity_id")}): _ent(["number", "input_number", "sensor"]),
                vol.Optional("ev_charger_label", default=existing.get("label", f"EV Laadpaal {i}")): str,
                vol.Optional("ev_charger_switch", default=existing.get("switch", "") or vol.UNDEFINED): _ent(["switch", "input_boolean"]),
            }),
            description_placeholders={"ev_num": str(i), "total": str(self._ev_charger_count)},
        )


    async def async_step_solar_opts(self, user_input=None):
        """☀️ PV Zonnepanelen — sensor en instellingen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="solar_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SOLAR_SENSOR, default=data.get(CONF_SOLAR_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_BATTERY_SENSOR, default=data.get(CONF_BATTERY_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=float(data.get(CONF_NEGATIVE_PRICE_THRESHOLD, 0.0))): vol.Coerce(float),
            }),
        )

    async def async_step_gas_opts(self, user_input=None):
        """🔥 Gas & Warmte — submenu om te kiezen."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            section = user_input.get("section", "")
            if section == "gas_meter_opts":
                return await self.async_step_gas_meter_opts()
            if section == "warmtepomp_opts":
                return await self.async_step_warmtepomp_opts()
            return await self.async_step_menu_verbruik()
        return self.async_show_form(
            step_id="gas_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Required("section", default="gas_meter_opts"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="gas_meter_opts",   label="🔥 Gasverbruik & Gasprijs"),
                        selector.SelectOptionDict(value="warmtepomp_opts",  label="♨️ Warmtepomp"),
                    ], mode="list")
                ),
            }),
        )

    async def async_step_gas_meter_opts(self, user_input=None):
        """🔥 Gasverbruik & Gasprijs."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)

        from .const import (
            CONF_GAS_SENSOR, CONF_GAS_PRICE_SENSOR, CONF_GAS_TTF_SENSOR,
            CONF_GAS_PRICE_FIXED, CONF_GAS_USE_TTF,
            CONF_GAS_SUPPLIER, CONF_GAS_NETBEHEERDER,
            CONF_BOILER_EFFICIENCY,
            DEFAULT_GAS_PRICE_EUR_M3, DEFAULT_BOILER_EFFICIENCY,
            GAS_SUPPLIER_MARKUPS, GAS_NETBEHEERDERS,
            CONF_ENERGY_PRICES_COUNTRY,
        )

        country = data.get(CONF_ENERGY_PRICES_COUNTRY, "NL")

        # Leveranciers voor gas opslag
        gas_suppliers = GAS_SUPPLIER_MARKUPS.get(country, GAS_SUPPLIER_MARKUPS["NL"])
        supplier_options = [
            selector.SelectOptionDict(value=k, label=v[0])
            for k, v in gas_suppliers.items()
        ]

        # Netbeheerders
        netbeheerders = GAS_NETBEHEERDERS.get(country, GAS_NETBEHEERDERS["NL"])
        netbeheerder_options = [
            selector.SelectOptionDict(value=k, label=f"{v[0]} ({v[1]:.4f} €/m³)")
            for k, v in netbeheerders.items()
        ]

        return self.async_show_form(
            step_id="gas_meter_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                # ── Gasmeter sensor ──────────────────────────────────────────
                vol.Optional(CONF_GAS_SENSOR,
                    default=data.get(CONF_GAS_SENSOR) or vol.UNDEFINED): _ent(),
                # ── Gasprijs — volgorde: sensor → TTF → vast ────────────────
                vol.Optional(CONF_GAS_PRICE_SENSOR,
                    default=data.get(CONF_GAS_PRICE_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_GAS_USE_TTF,
                    default=bool(data.get(CONF_GAS_USE_TTF, True))): selector.BooleanSelector(),
                vol.Optional(CONF_GAS_TTF_SENSOR,
                    default=data.get(CONF_GAS_TTF_SENSOR) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_GAS_PRICE_FIXED,
                    default=float(data.get(CONF_GAS_PRICE_FIXED, DEFAULT_GAS_PRICE_EUR_M3))):
                    vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
                # ── Leverancier & netbeheerder voor opslag berekening ────────
                vol.Optional(CONF_GAS_SUPPLIER,
                    default=data.get(CONF_GAS_SUPPLIER, "none")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=supplier_options, mode="dropdown"
                    )),
                vol.Optional(CONF_GAS_NETBEHEERDER,
                    default=data.get(CONF_GAS_NETBEHEERDER, "default")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=netbeheerder_options, mode="dropdown"
                    )),
                # ── Ketelrendement ───────────────────────────────────────────
                vol.Optional(CONF_BOILER_EFFICIENCY,
                    default=float(data.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
            }),
            description_placeholders={
                "info": (
                    "Gasprijs volgorde: (1) Sensor met all-in prijs → "
                    "(2) TTF Day-Ahead spotmarkt + omrekening naar all-in → "
                    "(3) Vaste handmatige prijs.\n\n"
                    "Gasmeter sensor en prijssensor zijn beide optioneel. "
                    "Zonder sensor gebruikt CloudEMS TTF Day-Ahead (NL) of de vaste prijs als fallback."
                )
            },
        )

    async def async_step_warmtepomp_opts(self, user_input=None):
        """♨️ Warmtepomp instellingen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        try:
            from .const import CONF_HEAT_PUMP_COP, CONF_HEAT_PUMP_ENTITY, CONF_HEAT_PUMP_THERMAL_ENTITY
            from .const import DEFAULT_HEAT_PUMP_COP
        except ImportError:
            CONF_HEAT_PUMP_COP = "heat_pump_cop"; DEFAULT_HEAT_PUMP_COP = 3.5
            CONF_HEAT_PUMP_ENTITY = "heat_pump_power_entity"
            CONF_HEAT_PUMP_THERMAL_ENTITY = "heat_pump_thermal_entity"
        return self.async_show_form(
            step_id="warmtepomp_opts",
            data_schema=vol.Schema({
                vol.Optional("back_to_menu", default=False): selector.BooleanSelector(),
                vol.Optional(CONF_HEAT_PUMP_COP,            default=float(data.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))):
                    vol.All(vol.Coerce(float), vol.Range(min=1.0, max=8.0)),
                vol.Optional(CONF_HEAT_PUMP_ENTITY,         default=data.get(CONF_HEAT_PUMP_ENTITY) or vol.UNDEFINED): _ent(),
                vol.Optional(CONF_HEAT_PUMP_THERMAL_ENTITY, default=data.get(CONF_HEAT_PUMP_THERMAL_ENTITY) or vol.UNDEFINED): _ent(),
            }),
        )

    async def async_step_features_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        phase_count = int(data.get(CONF_PHASE_COUNT, 1))
        schema: dict = {
            vol.Optional(CONF_DYNAMIC_LOADING, default=bool(data.get(CONF_DYNAMIC_LOADING, False))): bool,
            vol.Optional(CONF_DYNAMIC_LOAD_THRESHOLD, default=float(data.get(CONF_DYNAMIC_LOAD_THRESHOLD, DEFAULT_DYNAMIC_LOAD_THRESHOLD))):
                vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=1.0)),
            vol.Optional(CONF_COST_TRACKING, default=bool(data.get(CONF_COST_TRACKING, True))): bool,
            vol.Optional(CONF_PEAK_SHAVING_ENABLED, default=bool(data.get(CONF_PEAK_SHAVING_ENABLED, False))): bool,
            vol.Optional(CONF_PEAK_SHAVING_LIMIT_W, default=float(data.get(CONF_PEAK_SHAVING_LIMIT_W, DEFAULT_PEAK_SHAVING_LIMIT_W))):
                vol.All(vol.Coerce(float), vol.Range(min=500, max=50000)),
            vol.Optional(CONF_PEAK_SHAVING_ASSETS, default=data.get(CONF_PEAK_SHAVING_ASSETS, [])):
                selector.EntitySelector(selector.EntitySelectorConfig(
                    domain=["switch","number","input_boolean","light","climate","media_player"], multiple=True)),
            vol.Optional(CONF_BATTERY_SCHEDULER_ENABLED, default=bool(data.get(CONF_BATTERY_SCHEDULER_ENABLED, False))): bool,
            vol.Optional(CONF_CONGESTION_ENABLED,         default=bool(data.get(CONF_CONGESTION_ENABLED, False))): bool,
            vol.Optional(CONF_BATTERY_DEGRADATION_ENABLED, default=bool(data.get(CONF_BATTERY_DEGRADATION_ENABLED, False))): bool,
            # v1.20: Batterij seizoensstrategie override
            vol.Optional("battery_season_override", default=str(data.get("battery_season_override", "auto"))): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value="auto",       label="🔄 Automatisch detecteren (aanbevolen)"),
                    selector.SelectOptionDict(value="summer",     label="☀️ Zomer (minder nachtladen, meer ontladen avond)"),
                    selector.SelectOptionDict(value="winter",     label="❄️ Winter (meer goedkoop laden, vroeg ontladen)"),
                    selector.SelectOptionDict(value="transition", label="🍂 Overgang (standaard balans)"),
                ], mode="list"),
            ),
        }
        if phase_count == 3:
            schema[vol.Optional(CONF_PHASE_BALANCE, default=bool(data.get(CONF_PHASE_BALANCE, True)))] = bool
            schema[vol.Optional(CONF_PHASE_BALANCE_THRESHOLD, default=float(data.get(CONF_PHASE_BALANCE_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD)))] = \
                vol.All(vol.Coerce(float), vol.Range(min=1, max=20))
        return self.async_show_form(step_id="features_opts", data_schema=vol.Schema(schema))

    async def async_step_cheap_switches_opts(self, user_input=None):
        """Stap 1: Hoeveel goedkope-uren schakelaars wil je koppelen?"""
        data = self._data()
        existing = data.get("cheap_switches", []) or []

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._cheap_count = int(user_input.get("cheap_switch_count", 0))
            # Bewaar huidige configs voor pre-fill in detail-stap
            self._existing_cheap_cfgs = list(existing)
            # Reset de opslag voor de nieuwe configuratie
            self._opts["cheap_switches"] = []
            self._cheap_step = 0
            if self._cheap_count > 0:
                return await self.async_step_cheap_switch_detail_opts()
            self._opts["cheap_switches"] = []
            return await self.async_step_smart_delay_opts()

        current_count = len(existing)
        switch_names = ", ".join(
            c.get("label", c.get("entity_id", f"Schakelaar {i+1}"))
            for i, c in enumerate(existing)
        ) or "—"

        count_opts = [
            selector.SelectOptionDict(value="0", label="Geen (uitschakelen)")
        ] + [
            selector.SelectOptionDict(value=str(i), label=str(i))
            for i in range(1, 10)
        ]

        return self.async_show_form(
            step_id="cheap_switches_opts",
            data_schema=vol.Schema({
                vol.Required("cheap_switch_count", default=str(current_count)):
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(options=count_opts, mode="dropdown")
                    ),
            }),
            description_placeholders={
                "current_count": str(current_count),
                "switch_names":  switch_names,
                "diagram_url":   "/local/cloudems/diagrams/cheap_switches.svg",
            },
        )

    async def async_step_cheap_switch_detail_opts(self, user_input=None):
        """Configureer één schakelaar incl. optionele Slimme Uitstelmodus."""
        i = self._cheap_step + 1
        existing = (
            self._existing_cheap_cfgs[self._cheap_step]
            if self._cheap_step < len(self._existing_cheap_cfgs)
            else {}
        )
        # Bestaande smart_delay config voor deze schakelaar (zit embedded in cheap_switch entry)
        ex_sd = existing.get("smart_delay") or {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            sd_enabled = bool(user_input.get("sd_enabled", False))
            switch_cfg = {
                "entity_id":     user_input.get("switch_entity", ""),
                "label":         user_input.get("switch_label",
                                                existing.get("label", f"Schakelaar {i}")),
                "window_hours":  int(user_input.get("window_hours", 2)),
                "earliest_hour": int(user_input.get("earliest_hour", 0)),
                "latest_hour":   int(user_input.get("latest_hour", 23)),
                "active":        True,
            }
            if sd_enabled:
                switch_cfg["smart_delay"] = {
                    "entity_id":           user_input.get("switch_entity", ""),
                    "label":               user_input.get("switch_label",
                                                          existing.get("label", f"Schakelaar {i}")),
                    "power_sensor":        user_input.get("sd_power_sensor") or None,
                    "power_threshold_w":   float(user_input.get("sd_power_threshold_w", 10.0)),
                    "price_threshold_eur": float(user_input.get("sd_price_threshold_eur", 0.25)),
                    "window_hours":        int(user_input.get("window_hours", 2)),
                    "earliest_hour":       int(user_input.get("earliest_hour", 0)),
                    "latest_hour":         int(user_input.get("latest_hour", 23)),
                    "grace_s":             int(user_input.get("sd_grace_s", 30)),
                    "notify":              bool(user_input.get("sd_notify", True)),
                    "wait_mode":           user_input.get("sd_wait_mode", "price"),
                    "max_wait_h":          int(user_input.get("sd_max_wait_h", 0)),
                    "surplus_threshold_w": float(user_input.get("sd_surplus_threshold_w", 0.0)),
                    "active":              True,
                }
            self._opts.setdefault("cheap_switches", []).append(switch_cfg)
            self._cheap_step += 1
            if self._cheap_step < self._cheap_count:
                return await self.async_step_cheap_switch_detail_opts()
            # Sla smart_delay_switches ook apart op voor de scheduler (backwards compat)
            self._opts["smart_delay_switches"] = [
                sw["smart_delay"] for sw in self._opts.get("cheap_switches", [])
                if sw.get("smart_delay")
            ]
            return self._save(self._opts)

        _window_opts = [
            selector.SelectOptionDict(value="1", label="Goedkoopste 1 uur"),
            selector.SelectOptionDict(value="2", label="Goedkoopste 2 aaneengesloten uren"),
            selector.SelectOptionDict(value="3", label="Goedkoopste 3 aaneengesloten uren"),
            selector.SelectOptionDict(value="4", label="Goedkoopste 4 aaneengesloten uren"),
            selector.SelectOptionDict(value="6", label="Goedkoopste 6 aaneengesloten uren"),
            selector.SelectOptionDict(value="8", label="Goedkoopste 8 aaneengesloten uren"),
        ]
        _entity_sel = selector.EntitySelectorConfig(
            domain=["switch", "input_boolean", "light", "script", "automation"],
            multiple=False,
        )
        _power_sel = selector.EntitySelectorConfig(
            domain=["sensor"], device_class=["power"], multiple=False,
        )

        return self.async_show_form(
            step_id="cheap_switch_detail_opts",
            data_schema=vol.Schema({
                # ── Goedkope uren ────────────────────────────────────────────
                vol.Required("switch_entity",
                             default=existing.get("entity_id") or vol.UNDEFINED):
                    selector.EntitySelector(_entity_sel),
                vol.Optional("switch_label",
                             default=existing.get("label", f"Schakelaar {i}")):
                    selector.TextSelector(),
                vol.Optional("window_hours",
                             default=str(existing.get("window_hours", 2))):
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(options=_window_opts, mode="list")
                    ),
                vol.Optional("earliest_hour",
                             default=int(existing.get("earliest_hour", 0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=23, step=1, mode="slider")
                    ),
                vol.Optional("latest_hour",
                             default=int(existing.get("latest_hour", 23))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=23, step=1, mode="slider")
                    ),
                # ── Slimme Uitstelmodus ──────────────────────────────────────
                vol.Optional("sd_enabled",
                             default=bool(ex_sd)):
                    selector.BooleanSelector(),
                vol.Optional("sd_power_sensor",
                             default=ex_sd.get("power_sensor") or vol.UNDEFINED):
                    selector.EntitySelector(_power_sel),
                vol.Optional("sd_power_threshold_w",
                             default=float(ex_sd.get("power_threshold_w", 10.0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=5000, step=1,
                                                      unit_of_measurement="W", mode="box")),
                vol.Optional("sd_price_threshold_eur",
                             default=float(ex_sd.get("price_threshold_eur", 0.25))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.01,
                                                      unit_of_measurement="€/kWh", mode="box")),
                vol.Optional("sd_grace_s",
                             default=int(ex_sd.get("grace_s", 30))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=300, step=5,
                                                      unit_of_measurement="s", mode="slider")),
                vol.Optional("sd_notify",
                             default=bool(ex_sd.get("notify", True))):
                    selector.BooleanSelector(),
                vol.Optional("sd_wait_mode",
                             default=ex_sd.get("wait_mode", "price")):
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value="price",
                                    label="Wacht tot prijs ≤ drempel (€/kWh)"
                                ),
                                selector.SelectOptionDict(
                                    value="cheapest_block",
                                    label="Wacht op goedkoopste prijsblok (aanbevolen)"
                                ),
                            ],
                            mode="list",
                        )
                    ),
                vol.Optional("sd_max_wait_h",
                             default=int(ex_sd.get("max_wait_h", 0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=24, step=1,
                            unit_of_measurement="uur", mode="slider"
                        )
                    ),
                vol.Optional("sd_surplus_threshold_w",
                             default=float(ex_sd.get("surplus_threshold_w", 0.0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=5000, step=50,
                            unit_of_measurement="W", mode="slider"
                        )
                    ),
            }),
            description_placeholders={
                "switch_num":   str(i),
                "total":        str(self._cheap_count),
                "diagram_url":  "/local/cloudems/diagrams/cheap_switches.svg",
            },
        )

    # ── Slimme Uitstelmodus (deprecated standalone stap — logic now inline in cheap_switch_detail) ──

    async def async_step_smart_delay_opts(self, user_input=None):
        """Niet meer als zelfstandige stap — save direct."""
        return self._save(self._opts)

    async def async_step_smart_delay_detail_opts(self, user_input=None):
        """Stap 2: Configureer één slimme uitstelmodus-schakelaar (legacy — niet meer in gebruik)."""
        i = self._smart_delay_step + 1
        existing = (
            self._existing_smart_delay_cfgs[self._smart_delay_step]
            if self._smart_delay_step < len(self._existing_smart_delay_cfgs)
            else {}
        )

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._opts.setdefault("smart_delay_switches", []).append({
                "entity_id":           user_input.get("switch_entity", ""),
                "label":               user_input.get("switch_label",
                                                       existing.get("label", f"Schakelaar {i}")),
                "power_sensor":        user_input.get("power_sensor") or None,
                "power_threshold_w":   float(user_input.get("power_threshold_w", 10.0)),
                "price_threshold_eur": float(user_input.get("price_threshold_eur", 0.25)),
                "window_hours":        int(user_input.get("window_hours", 2)),
                "earliest_hour":       int(user_input.get("earliest_hour", 0)),
                "latest_hour":         int(user_input.get("latest_hour", 23)),
                "grace_s":             int(user_input.get("grace_s", 30)),
                "notify":              bool(user_input.get("notify", True)),
                "wait_mode":           user_input.get("wait_mode", "price"),
                "active":              True,
            })
            self._smart_delay_step += 1
            if self._smart_delay_step < self._smart_delay_count:
                return await self.async_step_smart_delay_detail_opts()
            return self._save({
                "cheap_switches":       self._opts.get("cheap_switches", []),
                "smart_delay_switches": self._opts.get("smart_delay_switches", []),
            })

        _entity_sel = selector.EntitySelectorConfig(
            domain=["switch", "input_boolean", "light", "script", "automation"],
            multiple=False,
        )
        _power_sel = selector.EntitySelectorConfig(
            domain=["sensor"], device_class=["power"], multiple=False,
        )
        _window_opts = [
            selector.SelectOptionDict(value="1", label="Goedkoopste 1 uur"),
            selector.SelectOptionDict(value="2", label="Goedkoopste 2 aaneengesloten uren"),
            selector.SelectOptionDict(value="3", label="Goedkoopste 3 aaneengesloten uren"),
            selector.SelectOptionDict(value="4", label="Goedkoopste 4 aaneengesloten uren"),
            selector.SelectOptionDict(value="6", label="Goedkoopste 6 aaneengesloten uren"),
        ]

        return self.async_show_form(
            step_id="smart_delay_detail_opts",
            data_schema=vol.Schema({
                vol.Required("switch_entity",
                             default=existing.get("entity_id") or vol.UNDEFINED):
                    selector.EntitySelector(_entity_sel),
                vol.Optional("switch_label",
                             default=existing.get("label", f"Apparaat {i}")):
                    selector.TextSelector(),
                vol.Optional("power_sensor",
                             default=existing.get("power_sensor") or vol.UNDEFINED):
                    selector.EntitySelector(_power_sel),
                vol.Optional("power_threshold_w",
                             default=float(existing.get("power_threshold_w", 10.0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=5000, step=1,
                                                      unit_of_measurement="W", mode="box")),
                vol.Optional("price_threshold_eur",
                             default=float(existing.get("price_threshold_eur", 0.25))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.01,
                                                      unit_of_measurement="€/kWh", mode="box")),
                vol.Optional("window_hours",
                             default=str(existing.get("window_hours", 2))):
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(options=_window_opts, mode="list")),
                vol.Optional("earliest_hour",
                             default=int(existing.get("earliest_hour", 0))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=23, step=1, mode="slider")),
                vol.Optional("latest_hour",
                             default=int(existing.get("latest_hour", 23))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=23, step=1, mode="slider")),
                vol.Optional("grace_s",
                             default=int(existing.get("grace_s", 30))):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=300, step=5,
                                                      unit_of_measurement="s", mode="slider")),
                vol.Optional("notify", default=bool(existing.get("notify", True))):
                    selector.BooleanSelector(),
            }),
            description_placeholders={
                "switch_num":       str(i),
                "total":            str(self._smart_delay_count),
                "grace_tip":        "Seconden na detectie wachten vóór uitschakelen — 0 = direct.",
                "power_tip":        "Optioneel: koppel een vermogenssensor voor betrouwbaarder detectie.",
                "price_tip":        "Prijs waarboven CloudEMS het apparaat uitschakelt en wacht.",
            },
        )

    # ── PV Inverter management (Options) ──────────────────────────────────────


    async def async_step_ai_opts(self, user_input=None):
        """🤖 AI & NILM instellingen."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            provider = user_input.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
            user_input[CONF_OLLAMA_ENABLED] = (provider == AI_PROVIDER_OLLAMA)
            return self._save(user_input)
        return self.async_show_form(
            step_id="ai_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_AI_PROVIDER, default=str(data.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE))): _ai_provider_selector(),
                vol.Optional(CONF_CLOUD_API_KEY,  default=str(data.get(CONF_CLOUD_API_KEY, ""))): str,
                vol.Optional(CONF_OLLAMA_HOST,    default=str(data.get(CONF_OLLAMA_HOST, DEFAULT_OLLAMA_HOST))): str,
                vol.Optional(CONF_OLLAMA_PORT,    default=int(data.get(CONF_OLLAMA_PORT, DEFAULT_OLLAMA_PORT))): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_OLLAMA_MODEL,   default=str(data.get(CONF_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL))): str,
                vol.Optional(CONF_NILM_CONFIDENCE, default=float(data.get(CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.3, max=0.99)),
            }),
            description_placeholders={
                    "diagram_url": "/local/cloudems/diagrams/p1_config.svg",
                    "premium_url": "https://cloudems.eu/premium"},
        )


    # ── PV Inverter management (Options) ──────────────────────────────────────


    async def async_step_budget_opts(self, user_input=None):
        """💶 Energiebudget — stel maandbudget in of schakel uit."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._opts["budget_enabled"]          = user_input.get("budget_enabled", True)
            self._opts["budget_elec_eur_month"]   = float(user_input.get("budget_elec_eur_month", 120.0))
            self._opts["budget_elec_kwh_month"]   = float(user_input.get("budget_elec_kwh_month", 300.0))
            self._opts["budget_gas_m3_month"]     = float(user_input.get("budget_gas_m3_month", 150.0))
            return await self.async_step_init()

        existing = self._opts
        return self.async_show_form(
            step_id="budget_opts",
            data_schema=vol.Schema({
                vol.Required("budget_enabled",
                    default=existing.get("budget_enabled", True)):
                    selector.BooleanSelector(),
                vol.Required("budget_elec_eur_month",
                    default=existing.get("budget_elec_eur_month", 120.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=10, max=2000, step=5, unit_of_measurement="€/maand", mode="box"
                    )),
                vol.Required("budget_elec_kwh_month",
                    default=existing.get("budget_elec_kwh_month", 300.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=50, max=5000, step=10, unit_of_measurement="kWh/maand", mode="box"
                    )),
                vol.Required("budget_gas_m3_month",
                    default=existing.get("budget_gas_m3_month", 150.0)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=0, max=1000, step=5, unit_of_measurement="m³/maand", mode="box"
                    )),
            }),
        )

    async def async_step_nilm_shift_opts(self, user_input=None):
        """🔀 NILM Lastverschuiving — configureer include/exclude en drempel."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Parse include/exclude uit komma-gescheiden tekst
            def _parse_list(val: str) -> list:
                return [s.strip() for s in (val or "").split(",") if s.strip()]

            self._opts["nilm_load_shifting_enabled"] = user_input.get("nilm_load_shifting_enabled", True)
            self._opts["nilm_shift_price_threshold"]  = float(user_input.get("nilm_shift_price_threshold", 0.25))
            self._opts["nilm_shift_max_defer_hours"]  = int(user_input.get("nilm_shift_max_defer_hours", 8))
            self._opts["nilm_shift_include"]          = _parse_list(user_input.get("nilm_shift_include", ""))
            self._opts["nilm_shift_exclude"]          = _parse_list(user_input.get("nilm_shift_exclude", ""))
            # Parse deadlines: "wasmachine=07:00, vaatwasser=08:30"
            raw = user_input.get("nilm_shift_deadlines_raw", "")
            deadlines = {}
            for part in raw.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    deadlines[k.strip().lower()] = v.strip()
            self._opts["nilm_shift_deadlines"]      = deadlines
            self._opts["nilm_shift_deadlines_raw"]  = raw
            return await self.async_step_init()

        existing = self._opts
        inc_str = ", ".join(existing.get("nilm_shift_include") or [])
        exc_str = ", ".join(existing.get("nilm_shift_exclude") or [])

        return self.async_show_form(
            step_id="nilm_shift_opts",
            data_schema=vol.Schema({
                vol.Required("nilm_load_shifting_enabled",
                    default=existing.get("nilm_load_shifting_enabled", True)):
                    selector.BooleanSelector(),
                vol.Required("nilm_shift_price_threshold",
                    default=existing.get("nilm_shift_price_threshold", 0.25)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=0.05, max=1.00, step=0.01, unit_of_measurement="€/kWh", mode="box"
                    )),
                vol.Required("nilm_shift_max_defer_hours",
                    default=existing.get("nilm_shift_max_defer_hours", 8)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=1, max=12, step=1, unit_of_measurement="uur", mode="slider"
                    )),
                vol.Optional("nilm_shift_include", default=inc_str):
                    selector.TextSelector(selector.TextSelectorConfig(
                        multiline=False
                    )),
                vol.Optional("nilm_shift_exclude", default=exc_str):
                    selector.TextSelector(selector.TextSelectorConfig(
                        multiline=False
                    )),
                vol.Optional("nilm_shift_deadlines_raw",
                    default=existing.get("nilm_shift_deadlines_raw", "")):
                    selector.TextSelector(selector.TextSelectorConfig(
                        multiline=True
                    )),
            }),
            description_placeholders={
                "include_hint": "Komma-gescheiden apparaatnamen die WEL verschoven mogen worden. Leeg = alles.",
                "exclude_hint": "Komma-gescheiden apparaatnamen die NOOIT verschoven mogen worden.",
            },
        )

    async def async_step_nilm_devices_opts(self, user_input=None):
        """🏷️ NILM Apparaten beheren — hernoem of verberg gedetecteerde apparaten.

        v1.20: This step shows a summary of currently known NILM devices and
        provides instructions for renaming/hiding via HA developer tools.
        Direct per-device editing is not possible in the HA options flow UI
        (no dynamic forms), so we guide the user to the service calls.
        """
        from homeassistant.loader import async_get_integration
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Nothing to save — this is an informational step
            return self.async_abort(reason="nilm_manage_via_services")

        # Build a human-readable overview of current devices
        entry = getattr(self, "config_entry", self._entry)
        hass  = self.hass  # available on OptionsFlow

        # Try to get live device list from coordinator
        device_lines = []
        try:
            from homeassistant.helpers import entity_registry as er
            from . import DOMAIN
            coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator and hasattr(coordinator, "_nilm"):
                devices = coordinator._nilm.get_devices_for_ha()
                # Also include hidden devices so user can un-hide them
                all_devs = [d.to_dict() for d in coordinator._nilm._devices.values()]
                for dev in all_devs:
                    uid  = dev.get("device_id", "?")
                    name = dev.get("user_name") or dev.get("name", dev.get("device_type", "?"))
                    hidden = "🙈 verborgen" if dev.get("user_hidden") else "✅ zichtbaar"
                    device_lines.append(f"{name}  [{uid}]  {hidden}")
        except Exception:
            pass

        devices_text = "\n".join(device_lines) if device_lines else "(nog geen apparaten gedetecteerd)"

        return self.async_show_form(
            step_id="nilm_devices_opts",
            data_schema=vol.Schema({}),
            description_placeholders={
                "devices_overview": devices_text,
                "rename_service":   "cloudems.rename_nilm_device",
                "hide_service":     "cloudems.hide_nilm_device",
                "devtools_url":     "/developer-tools/service",
            },
        )

    def _inv_d(self) -> dict:
        """Shorthand for combined entry data."""
        return self._data()

    async def async_step_inverters_opts(self, user_input=None):
        """Choose how many PV inverters to configure."""
        data = self._inv_d()
        current_cfgs = data.get(CONF_INVERTER_CONFIGS, [])
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._inv_count = int(user_input.get(CONF_INVERTER_COUNT, 0))
            # Save existing configs BEFORE clearing, same as battery pattern
            self._existing_inv_cfgs = list(current_cfgs)
            self._opts[CONF_INVERTER_COUNT]   = self._inv_count
            self._opts[CONF_INVERTER_CONFIGS] = []
            self._inv_step = 0
            if self._inv_count > 0:
                return await self.async_step_inverter_detail_opts()
            # Zero inverters: clear config and finish
            self._opts[CONF_ENABLE_MULTI_INVERTER] = False
            return self._save(self._opts)

        current_count = str(len(current_cfgs))
        return self.async_show_form(
            step_id="inverters_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_INVERTER_COUNT, default=current_count): _inverter_count_selector(),
            }),
            description_placeholders={
                "current_count": str(len(current_cfgs)),
                "inverter_names": ", ".join(c.get("label", f"Inverter {i+1}") for i, c in enumerate(current_cfgs)) or "—",
            },
        )

    async def async_step_inverter_detail_opts(self, user_input=None):
        """Configure each inverter one by one (Options flow)."""
        i = self._inv_step + 1
        # Use the snapshot saved in inverters_opts (before the list was cleared)
        # so entity selectors are pre-filled with the current configuration.
        existing_cfgs = getattr(self, "_existing_inv_cfgs", None)
        if existing_cfgs is None:
            existing_cfgs = self._inv_d().get(CONF_INVERTER_CONFIGS, [])
        # Pre-fill from existing config for this slot if it exists
        existing = existing_cfgs[self._inv_step] if self._inv_step < len(existing_cfgs) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            _inv_keep = lambda k_ui, k_ex: user_input.get(k_ui) or existing.get(k_ex, "")
            self._opts[CONF_INVERTER_CONFIGS].append({
                "entity_id":      user_input.get("inv_sensor"),
                "control_entity": _inv_keep("inv_control", "control_entity"),
                "label":          user_input.get("inv_label", f"Inverter {i}"),
                "priority":       i,
                "min_power_pct":  float(user_input.get("inv_min_pct", 0.0)),
                "azimuth_deg":    user_input.get("inv_azimuth") or None,
                "tilt_deg":       user_input.get("inv_tilt") or None,
                "rated_power_w":  float(user_input.get("inv_rated_power", 0)) or None,
            })
            self._inv_step += 1
            if self._inv_step < self._inv_count:
                return await self.async_step_inverter_detail_opts()
            self._opts[CONF_ENABLE_MULTI_INVERTER] = len(self._opts[CONF_INVERTER_CONFIGS]) > 0
            return self._save(self._opts)

        return self.async_show_form(
            step_id="inverter_detail_opts",
            data_schema=vol.Schema({
                vol.Required("inv_sensor", default=existing.get("entity_id", vol.UNDEFINED)): _ent(),
                vol.Optional("inv_control", default=existing.get("control_entity") or vol.UNDEFINED): _ent(["switch", "number"]),
                vol.Optional("inv_label",   default=existing.get("label", f"Inverter {i}")): str,
                vol.Optional("inv_min_pct", default=float(existing.get("min_power_pct", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
                vol.Optional("inv_azimuth", description={"suggested_value": existing.get("azimuth_deg")}): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=360))),
                vol.Optional("inv_tilt",    description={"suggested_value": existing.get("tilt_deg")}): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=90))),
                vol.Optional("inv_rated_power", default=float(existing.get("rated_power_w") or 0)): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
            }),
            description_placeholders={
                "inverter_num": str(i),
                "total":        str(self._inv_count),
                "azimuth_tip":  "0=N 90=E 180=S 270=W — leeg = zelf leren",
                "tilt_tip":     "0=plat 90=verticaal — leeg = zelf leren",
            },
        )


    # ── 🔋 Batteries (multi-battery, like multi-inverter) ──────────────────────

    async def async_step_prices_opts(self, user_input=None):
        """Stap 1/3: Land kiezen."""
        data = self._data()
        country = data.get(CONF_ENERGY_PRICES_COUNTRY, "NL")

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._opts_country = user_input.get(CONF_ENERGY_PRICES_COUNTRY, country)
            self._save({CONF_ENERGY_PRICES_COUNTRY: self._opts_country})
            return await self.async_step_prices_provider_opts()

        return self.async_show_form(
            step_id="prices_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_ENERGY_PRICES_COUNTRY, default=country): _country_selector(),
            }),

        )

    async def async_step_prices_provider_opts(self, user_input=None):
        """Stap 2/3: Leverancier kiezen (gefilterd op gekozen land)."""
        from .const import (CONF_CONTRACT_TYPE, CONTRACT_TYPE_DYNAMIC, CONTRACT_TYPE_FIXED,
                            DEFAULT_CONTRACT_TYPE, CONF_FIXED_IMPORT_PRICE, CONF_FIXED_EXPORT_PRICE)
        data = self._data()
        country = getattr(self, "_opts_country", data.get(CONF_ENERGY_PRICES_COUNTRY, "NL"))

        # Huidig geconfigureerde prijsleverancier
        current_price_provider = data.get(CONF_PRICE_PROVIDER, DEFAULT_PRICE_PROVIDER)
        existing_providers: list = list(data.get(CONF_PROVIDERS, []))
        registered_pp = next((p["type"] for p in existing_providers if p.get("_price_provider")), None)
        if registered_pp:
            current_price_provider = registered_pp

        # Build leverancier-opties gefilterd op land:
        # PRICE_PROVIDER_LABELS bevat alle directe API-leveranciers.
        # SUPPLIER_MARKUPS bevat per-land de relevante leveranciers voor EPEX-opslag.
        # We tonen alle API-providers + de EPEX optie altijd, maar filteren de
        # SUPPLIER_MARKUPS leveranciers op land zodat de lijst relevant is.
        country_suppliers = set(SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"]).keys())
        provider_options = []
        for k, v in PRICE_PROVIDER_LABELS.items():
            # "none" (EPEX) en frank_energie altijd tonen
            # Echte leveranciers alleen tonen als ze voor dit land beschikbaar zijn
            if k in EPEX_BASED_PROVIDERS:
                provider_options.append(selector.SelectOptionDict(value=k, label=v))
            else:
                # Toon als er credentials voor zijn (directe API) OF als ze in het land zitten
                has_direct_api = bool(PRICE_PROVIDER_CREDENTIALS.get(k))
                in_country = any(k in SUPPLIER_MARKUPS.get(c, {}) for c in [country])
                if has_direct_api or in_country:
                    provider_options.append(selector.SelectOptionDict(value=k, label=v))

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            chosen_pp = user_input.get(CONF_PRICE_PROVIDER, current_price_provider)

            # Credentials nodig?
            needed = PRICE_PROVIDER_CREDENTIALS.get(chosen_pp, [])
            if needed and chosen_pp != current_price_provider:
                self._pending_price_provider = chosen_pp
                return await self.async_step_price_provider_creds_opts()

            # No credentials nodig: provider registreren
            if chosen_pp != current_price_provider:
                self._apply_price_provider_opts(chosen_pp, {})
            else:
                self._apply_price_provider_opts(chosen_pp, {})

            # EPEX → ga naar belasting/markup stap
            if chosen_pp in EPEX_BASED_PROVIDERS:
                self._pending_price_provider = chosen_pp
                return await self.async_step_prices_epex_opts()

            # Echte leverancier → klaar
            return self._save({CONF_PRICE_PROVIDER: chosen_pp})

        return self.async_show_form(
            step_id="prices_provider_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_PRICE_PROVIDER, default=current_price_provider):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=provider_options, mode="list"
                    )),
            }),
            description_placeholders={
                "info": f"Kies je energieleverancier voor {country}. Bij EPEX-providers stel je daarna belasting en opslag in.",
            },
        )

    async def async_step_prices_epex_opts(self, user_input=None):
        """Stap 3/3: EPEX belasting & leverancier-markup (alleen bij EPEX-provider)."""
        from .const import (CONF_CONTRACT_TYPE, CONTRACT_TYPE_DYNAMIC, CONTRACT_TYPE_FIXED,
                            DEFAULT_CONTRACT_TYPE, CONF_FIXED_IMPORT_PRICE, CONF_FIXED_EXPORT_PRICE)
        data = self._data()
        country = getattr(self, "_opts_country", data.get(CONF_ENERGY_PRICES_COUNTRY, "NL"))
        contract_type = data.get(CONF_CONTRACT_TYPE, DEFAULT_CONTRACT_TYPE)

        suppliers = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"])
        sup_options = [
            selector.SelectOptionDict(value=k, label=v[0])
            for k, v in suppliers.items()
        ]

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)

        return self.async_show_form(
            step_id="prices_epex_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_CONTRACT_TYPE, default=contract_type): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=CONTRACT_TYPE_DYNAMIC, label="⚡ Dynamisch (EPEX dag-vooruit)"),
                        selector.SelectOptionDict(value=CONTRACT_TYPE_FIXED,   label="📋 Vast tarief"),
                    ], mode="list")
                ),
                vol.Optional(CONF_FIXED_IMPORT_PRICE, default=float(data.get(CONF_FIXED_IMPORT_PRICE, 0.25))): vol.All(vol.Coerce(float), vol.Range(min=0, max=2.0)),
                vol.Optional(CONF_FIXED_EXPORT_PRICE, default=float(data.get(CONF_FIXED_EXPORT_PRICE, 0.09))): vol.All(vol.Coerce(float), vol.Range(min=0, max=2.0)),
                vol.Optional(CONF_PRICE_INCLUDE_TAX, default=bool(data.get(CONF_PRICE_INCLUDE_TAX, False))): bool,
                vol.Optional(CONF_PRICE_INCLUDE_BTW, default=bool(data.get(CONF_PRICE_INCLUDE_BTW, False))): bool,
                vol.Optional(CONF_SELECTED_SUPPLIER, default=str(data.get(CONF_SELECTED_SUPPLIER, "none"))):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=sup_options, mode="dropdown")),
                vol.Optional(CONF_SUPPLIER_MARKUP, default=float(data.get(CONF_SUPPLIER_MARKUP, 0.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.5)),
            }),
            description_placeholders={
                "info": "Stel energiebelasting, BTW en leverancier-opslag in voor nauwkeurige kostberekeningen.",
            },
        )

    async def async_step_price_provider_creds_opts(self, user_input=None):
        """Options flow: credentials invullen voor gekozen prijsleverancier."""
        pending = getattr(self, "_pending_price_provider", "")
        needed  = PRICE_PROVIDER_CREDENTIALS.get(pending, [])
        label   = PRICE_PROVIDER_LABELS.get(pending, pending)

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            creds = {k: user_input.get(k, "") for k in needed}
            self._apply_price_provider_opts(pending, creds)
            self._pending_price_provider = None
            return self._save({})

        schema_fields = {}
        for field in needed:
            schema_fields[vol.Optional(field)] = str

        return self.async_show_form(
            step_id="price_provider_creds_opts",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={"provider_label": label},
        )

    def _apply_price_provider_opts(self, provider_type: str, credentials: dict) -> None:
        """Registreer of wis de prijsleverancier in external_providers (options flow)."""
        data = self._data()
        existing: list = list(data.get(CONF_PROVIDERS, []))
        # Verwijder eventuele vorige prijs-provider registratie
        existing = [p for p in existing if not p.get("_price_provider")]
        if provider_type not in ("none", "", None):
            existing.append({
                "type":           provider_type,
                "label":          PRICE_PROVIDER_LABELS.get(provider_type, provider_type),
                "credentials":    credentials,
                "_price_provider": True,
            })
        # Sla gecombineerd op via config entry update
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, CONF_PROVIDERS: existing, CONF_PRICE_PROVIDER: provider_type},
        )


    async def async_step_managed_battery_opts(self, user_input=None):
        """
        Options flow: toon gedetecteerde leverancier-gebonden batterijen en
        laat de gebruiker opt-in configuratie aanpassen.
        Wordt getoond aan het begin van de batteries_opts flow als er providers gevonden zijn.
        """
        from .energy_manager.battery_provider import BatteryProviderRegistry
        import importlib
        try:
            importlib.import_module(".energy_manager.zonneplan_bridge",
                                    package=__name__.rsplit(".", 1)[0])
        except Exception:
            pass

        data = self._data()
        tmp_registry = BatteryProviderRegistry(self.hass, data)
        await tmp_registry.async_setup()
        hints = tmp_registry.get_wizard_hints()

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Sla Zonneplan provider-instellingen op
            for h in hints:
                key_en = f"{h.provider_id}_enabled"
                if key_en in user_input:
                    self._opts[key_en] = user_input[key_en]
                for field_def in h.config_fields:
                    k = field_def["key"]
                    if k in user_input:
                        self._opts[k] = user_input[k]
            # Sla ook op als battery_config entry (zodat het dashboard weet dat dit een Zonneplan batterij is)
            i = getattr(self, "_inv_step", 0) + 1
            if not hasattr(self, "_opts") or CONF_BATTERY_CONFIGS not in self._opts:
                self._opts[CONF_BATTERY_CONFIGS] = []
            self._opts[CONF_BATTERY_CONFIGS].append({
                "battery_type": "zonneplan",
                "label":        f"Zonneplan Nexus",
                "priority":     i,
            })
            self._inv_step = getattr(self, "_inv_step", 0) + 1
            # Zijn er nog meer batterijen te configureren?
            inv_count = getattr(self, "_inv_count", 0)
            if self._inv_step < inv_count:
                return await self.async_step_battery_type_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = len(self._opts[CONF_BATTERY_CONFIGS]) > 0
            return self._save(self._opts)

        schema: dict = {}
        placeholders: dict = {}

        for h in hints:
            key_en = f"{h.provider_id}_enabled"
            current = data.get(key_en, False)
            schema[vol.Optional(key_en, default=current)] = bool

            for field_def in h.config_fields:
                k = field_def["key"]
                if k == key_en:
                    continue
                t       = field_def.get("type", "bool")
                default = data.get(k, field_def.get("default"))
                if t == "bool":
                    schema[vol.Optional(k, default=bool(default))] = bool
                elif t in ("int", "float"):
                    mn     = field_def.get("min", 0)
                    mx     = field_def.get("max", 9999)
                    coerce = int if t == "int" else float
                    schema[vol.Optional(k, default=coerce(default))] = vol.All(
                        vol.Coerce(coerce), vol.Range(min=mn, max=mx)
                    )

            placeholders[f"{h.provider_id}_label"]       = h.provider_label
            placeholders[f"{h.provider_id}_warning"]     = h.warning or ""
            placeholders[f"{h.provider_id}_description"] = h.description

        provider_names = ", ".join(h.provider_label for h in hints)
        placeholders["detected_providers"] = provider_names
        placeholders["provider_count"]     = str(len(hints))

        return self.async_show_form(
            step_id="managed_battery_opts",
            data_schema=vol.Schema(schema),
            description_placeholders=placeholders,
        )

    async def async_step_batteries_opts(self, user_input=None):
        """Stap 1: Hoeveel batterijen heb je?"""
        data = self._data()
        existing_cfgs = data.get(CONF_BATTERY_CONFIGS, [])

        # Legacy: single battery via CONF_BATTERY_SENSOR
        legacy_sensor = data.get(CONF_BATTERY_SENSOR)
        if not existing_cfgs and legacy_sensor:
            existing_cfgs = [{"power_sensor": legacy_sensor, "label": "Batterij 1"}]

        current_count = len(existing_cfgs)
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._inv_count = int(user_input.get(CONF_BATTERY_COUNT, 0))
            self._opts[CONF_BATTERY_COUNT]   = self._inv_count
            self._opts[CONF_BATTERY_CONFIGS] = []
            self._existing_bat_cfgs = existing_cfgs
            self._inv_step = 0
            if self._inv_count > 0:
                return await self.async_step_battery_type_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = False
            self._opts[CONF_BATTERY_SENSOR] = ""
            return self._save(self._opts)

        bat_names = ", ".join(
            c.get("label", f"Batterij {i+1}") for i, c in enumerate(existing_cfgs)
        ) or "—"
        return self.async_show_form(
            step_id="batteries_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_BATTERY_COUNT, default=str(current_count)): _inverter_count_selector(),
            }),
            description_placeholders={
                "current_count": str(current_count),
                "battery_names": bat_names,
            },
        )

    async def async_step_battery_type_opts(self, user_input=None):
        """Stap 2: Kies het type voor elke batterij (Zonneplan / Handmatig / ander merk)."""
        from .energy_manager.battery_provider import BatteryProviderRegistry
        import importlib
        try:
            importlib.import_module(".energy_manager.zonneplan_bridge",
                                    package=__name__.rsplit(".", 1)[0])
        except Exception:
            pass

        data = self._data()
        i = self._inv_step + 1
        existing_cfgs = getattr(self, "_existing_bat_cfgs", data.get(CONF_BATTERY_CONFIGS, []))
        existing = existing_cfgs[self._inv_step] if self._inv_step < len(existing_cfgs) else {}

        # Detecteer beschikbare providers voor hint in de selector
        tmp_registry = BatteryProviderRegistry(self.hass, data)
        await tmp_registry.async_setup()
        hints = tmp_registry.get_wizard_hints()
        provider_options = [
            selector.SelectOptionDict(value="manual", label="🔧 Handmatig (SOC-sensor + schakelaar)"),
        ]
        for h in hints:
            provider_options.insert(0, selector.SelectOptionDict(
                value=h.provider_id,
                label=f"⚡ {h.provider_label} (gevonden — {h.description[:40]}…)" if len(h.description) > 40 else f"⚡ {h.provider_label} — {h.description}",
            ))

        # Default: herstel vorige keuze als die er is
        existing_type = existing.get("battery_type", "zonneplan" if hints else "manual")

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            bat_type = user_input.get("bat_type", "manual")
            # Sla type op bij de battery config (wordt later aangevuld)
            if not hasattr(self, "_battery_types"):
                self._battery_types = {}
            self._battery_types[self._inv_step] = bat_type

            if bat_type == "zonneplan":
                return await self.async_step_managed_battery_opts()
            else:
                return await self.async_step_battery_detail_opts()

        return self.async_show_form(
            step_id="battery_type_opts",
            data_schema=vol.Schema({
                vol.Required("bat_type", default=existing_type): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=provider_options, mode="list")
                ),
            }),
            description_placeholders={
                "battery_num": str(i),
                "total":       str(self._inv_count),
                "detected_providers": ", ".join(h.provider_label for h in hints) if hints else "geen",
            },
        )

    async def async_step_battery_detail_opts(self, user_input=None):
        """Configureer hardware-sensoren voor één batterij."""
        data = self._data()
        i = self._inv_step + 1
        existing_cfgs = getattr(self, "_existing_bat_cfgs", data.get(CONF_BATTERY_CONFIGS, []))
        existing = existing_cfgs[self._inv_step] if self._inv_step < len(existing_cfgs) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            _bat_keep = lambda k_ui, k_ex: user_input.get(k_ui) or existing.get(k_ex, "")
            self._opts[CONF_BATTERY_CONFIGS].append({
                "battery_type":     "manual",
                "power_sensor":     user_input.get("bat_power_sensor") or existing.get("power_sensor"),
                "soc_sensor":       user_input.get("bat_soc_sensor")   or existing.get("soc_sensor"),
                "capacity_kwh":     float(user_input.get("bat_capacity_kwh", 0.0)),
                "max_charge_w":     float(user_input.get("bat_max_charge_w", 0.0)),
                "max_discharge_w":  float(user_input.get("bat_max_discharge_w", 0.0)),
                "charge_entity":    _bat_keep("bat_charge_entity",    "charge_entity"),
                "discharge_entity": _bat_keep("bat_discharge_entity", "discharge_entity"),
                "label":            user_input.get("bat_label", f"Batterij {i}"),
                "priority":         i,
            })
            self._inv_step += 1
            if self._inv_step < self._inv_count:
                return await self.async_step_battery_type_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = len(self._opts[CONF_BATTERY_CONFIGS]) > 0
            return await self.async_step_shutter_count_opts()

        return self.async_show_form(
            step_id="battery_detail_opts",
            data_schema=vol.Schema({
                vol.Required("bat_power_sensor", default=existing.get("power_sensor", vol.UNDEFINED)): _ent(),
                vol.Optional("bat_soc_sensor", default=existing.get("soc_sensor") or vol.UNDEFINED): _ent(),
                vol.Optional("bat_capacity_kwh", default=float(existing.get("capacity_kwh", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional("bat_max_charge_w", default=float(existing.get("max_charge_w", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_max_discharge_w", default=float(existing.get("max_discharge_w", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_charge_entity", default=existing.get("charge_entity") or vol.UNDEFINED): _ent(["number", "input_number"]),
                vol.Optional("bat_discharge_entity", default=existing.get("discharge_entity") or vol.UNDEFINED): _ent(["number", "input_number"]),
                vol.Optional("bat_label", default=existing.get("label", f"Batterij {i}")): str,
            }),
            description_placeholders={
                "battery_num": str(i),
                "total":       str(self._inv_count),
            },
        )

    # ── Rolluiken opties ──────────────────────────────────────────────────────
    async def async_step_climate_opts(self, user_input=None):
        """Klimaatbeheer — keuze Zone Control of Airco/WP EPEX."""
        data = self._data()

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            mode = user_input.get("climate_mode", "none")
            if mode == "zones":
                return await self.async_step_climate_zones_opts()
            if mode == "epex":
                return await self.async_step_climate_epex_count_opts()
            # none
            self._opts[CONF_CLIMATE_ENABLED] = False
            self._opts[CONF_CLIMATE_EPEX_ENABLED] = False
            return self._save(self._opts)

        if data.get(CONF_CLIMATE_EPEX_ENABLED):
            current_mode = "epex"
        elif data.get(CONF_CLIMATE_ENABLED):
            current_mode = "zones"
        else:
            current_mode = "none"

        return self.async_show_form(
            step_id="climate_opts",
            data_schema=vol.Schema({
                vol.Required("climate_mode", default=current_mode): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="none",  label="🚫 Klimaat uitgeschakeld"),
                        selector.SelectOptionDict(value="zones", label="🏠 Zone Control (TRV / thermostaat per kamer)"),
                        selector.SelectOptionDict(value="epex",  label="❄️ Airco / Warmtepomp EPEX-sturing"),
                    ], mode="list")
                ),
            }),
            description_placeholders={
                "info": (
                    "**Zone Control** beheert virtuele thermostaten per HA-ruimte.\n\n"
                    "**Airco / WP EPEX** past temperatuuroffsets toe op basis van spotprijzen. "
                    "Meerdere apparaten (WP's en airco's) worden ondersteund."
                )
            },
        )

    async def async_step_climate_zones_opts(self, user_input=None):
        """Zone Control options: kies actieve kamers."""
        data = self._data()
        try:
            from .climate_discovery import async_suggest_zones
            suggested = await async_suggest_zones(self.hass)
        except Exception:
            suggested = []

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            enabled_ids = user_input.get(CONF_CLIMATE_ZONES_ENABLED, [])
            self._opts[CONF_CLIMATE_ZONES_ENABLED] = enabled_ids
            self._opts[CONF_CLIMATE_ENABLED] = bool(enabled_ids)
            self._opts[CONF_CLIMATE_EPEX_ENABLED] = False
            if suggested:
                self._opts["climate_zones"] = suggested
            return self._save(self._opts)

        zone_options = []
        zone_device_info = []
        for z in suggested:
            ht = "CV" if z["zone_heating_type"] == "cv" else "Airco" if z["zone_heating_type"] == "airco" else "CV+Airco"
            zone_options.append(selector.SelectOptionDict(
                value=z["zone_name"], label=f"{z['zone_display_name']} ({ht})",
            ))
            devices = z.get("zone_climate_entities", [])
            if devices:
                zone_device_info.append(f"**{z['zone_display_name']}** ({ht}): {', '.join(f'`{e}`' for e in devices)}")

        current_enabled = list(data.get(CONF_CLIMATE_ZONES_ENABLED, [z["zone_name"] for z in suggested]))
        device_info_text = ("\n\n**Gekoppelde apparaten per ruimte:**\n" + "\n".join(f"- {l}" for l in zone_device_info)) if zone_device_info else ""

        if not zone_options:
            return self.async_show_form(
                step_id="climate_zones_opts",
                data_schema=vol.Schema({}),
                description_placeholders={"discovery": "*Geen klimaatentiteiten gevonden. Wijs thermostaten/TRV's toe aan een HA-ruimte.*"},
            )

        return self.async_show_form(
            step_id="climate_zones_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_CLIMATE_ZONES_ENABLED, default=current_enabled):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=zone_options, multiple=True, mode="list",
                    )),
            }),
            description_placeholders={
                "discovery": (
                    "Selecteer de ruimten waarvoor CloudEMS een virtuele thermostaat aanmaakt."
                    + device_info_text
                ),
            },
        )

    async def async_step_climate_epex_count_opts(self, user_input=None):
        """Airco/WP EPEX options stap 1: hoeveel apparaten?"""
        data = self._data()
        existing_devices = data.get(CONF_CLIMATE_EPEX_DEVICES, [])

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._ce_count = int(user_input.get("ce_count", 1))
            self._opts[CONF_CLIMATE_EPEX_ENABLED] = True
            self._opts[CONF_CLIMATE_ENABLED] = False
            self._opts[CONF_CLIMATE_EPEX_DEVICES] = []
            self._ce_step = 0
            self._existing_ce_cfgs = list(existing_devices)
            return await self.async_step_climate_epex_device_opts()

        opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(1, 9)]
        return self.async_show_form(
            step_id="climate_epex_count_opts",
            data_schema=vol.Schema({
                vol.Required("ce_count", default=str(max(1, len(existing_devices)))): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opts, mode="list")
                ),
            }),
            description_placeholders={
                "current": ", ".join(d.get("label", d.get("entity_id", "")) for d in existing_devices) or "—",
            },
        )

    async def async_step_climate_epex_device_opts(self, user_input=None):
        """Airco/WP EPEX options: configureer apparaat N."""
        i = self._ce_step + 1
        existing_cfgs = getattr(self, "_existing_ce_cfgs", [])
        existing = existing_cfgs[self._ce_step] if self._ce_step < len(existing_cfgs) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._opts[CONF_CLIMATE_EPEX_DEVICES].append({
                "entity_id":    user_input["ce_entity"],
                "label":        user_input.get("ce_label", f"Apparaat {i}"),
                "device_type":  user_input.get("ce_type", "heat_pump"),
                "power_entity": user_input.get("ce_power", ""),
                "offset_c":     float(user_input.get("ce_offset", 0.5)),
                "enabled":      True,
            })
            self._ce_step += 1
            if self._ce_step < self._ce_count:
                return await self.async_step_climate_epex_device_opts()
            return self._save(self._opts)

        type_opts = [
            selector.SelectOptionDict(value="heat_pump", label="🔥 Warmtepomp"),
            selector.SelectOptionDict(value="airco",     label="❄️ Airco / koeling"),
            selector.SelectOptionDict(value="hybrid",    label="🔄 Hybride (WP + ketel)"),
        ]
        return self.async_show_form(
            step_id="climate_epex_device_opts",
            data_schema=vol.Schema({
                vol.Required("ce_entity", default=existing.get("entity_id") or vol.UNDEFINED):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["climate"])),
                vol.Optional("ce_label", description={"suggested_value": existing.get("label", f"Apparaat {i}")}): str,
                vol.Required("ce_type", default=existing.get("device_type", "heat_pump")):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=type_opts, mode="list")),
                vol.Optional("ce_power", default=existing.get("power_entity") or vol.UNDEFINED):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
                vol.Optional("ce_offset", default=float(existing.get("offset_c", 0.5))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
            }),
            description_placeholders={
                "device_num": str(i),
                "total":      str(self._ce_count),
                "tip":        "Offset = maximale temperatuurverschuiving in °C (aanbevolen: 0.5°C).",
            },
        )


    async def async_step_shutter_count_opts(self, user_input=None):
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            self._shutter_count = int(user_input.get(CONF_SHUTTER_COUNT, 0))
            self._existing_shutter_cfgs = list(self._data().get(CONF_SHUTTER_CONFIGS, []))
            self._opts[CONF_SHUTTER_COUNT]   = self._shutter_count
            self._opts[CONF_SHUTTER_CONFIGS] = []
            self._shutter_step = 0
            if self._shutter_count > 0:
                return await self.async_step_shutter_detail_opts()
            return self._save(self._opts)
        existing_count = str(self._data().get(CONF_SHUTTER_COUNT, DEFAULT_SHUTTER_COUNT))
        opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(21)]
        return self.async_show_form(
            step_id="shutter_count_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_SHUTTER_COUNT, default=existing_count): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=opts, mode="dropdown")
                ),
            }),
            description_placeholders={"overkiz_found": ""},
        )

    def _get_area_for_entity(self, entity_id: str) -> tuple:
        """Geef (area_id, area_name) terug voor een entity."""
        try:
            from homeassistant.helpers import entity_registry as er, area_registry as ar
            ent_reg  = er.async_get(self.hass)
            area_reg = ar.async_get(self.hass)
            entry = ent_reg.async_get(entity_id)
            if entry and entry.area_id:
                area = area_reg.areas.get(entry.area_id)
                return entry.area_id, (area.name if area else "")
        except Exception:
            pass
        return "", ""

    def _suggest_temp_sensor_for_cover(self, cover_entity_id: str) -> str:
        """Geef de beste temperatuursensor in dezelfde ruimte als het rolluik."""
        if not cover_entity_id:
            return ""
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)
            cover_entry = ent_reg.async_get(cover_entity_id)
            if cover_entry is None or not cover_entry.area_id:
                return ""
            area_id = cover_entry.area_id
            candidates: list = []
            climate_fallback: list = []
            for entry in ent_reg.entities.values():
                if entry.area_id != area_id or entry.disabled:
                    continue
                eid   = entry.entity_id.lower()
                label = (entry.original_name or entry.entity_id).lower()
                skip_words = ("outdoor", "buiten", "outside", "extern", "external")
                if any(w in eid or w in label for w in skip_words):
                    continue
                if entry.domain == "sensor":
                    dc = entry.device_class or entry.original_device_class or ""
                    if dc == "temperature":
                        candidates.append(entry.entity_id)
                elif entry.domain == "climate":
                    climate_fallback.append(entry.entity_id)
            if candidates:
                return candidates[0]
            if climate_fallback:
                return climate_fallback[0]
        except Exception:
            pass
        return ""

    async def async_step_shutter_detail_opts(self, user_input=None):
        i = self._shutter_step + 1
        existing_cfgs = getattr(self, "_existing_shutter_cfgs", None)
        if existing_cfgs is None:
            existing_cfgs = self._data().get(CONF_SHUTTER_CONFIGS, [])
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            cover_eid = user_input.get("shutter_entity", "")
            area_id, area_name = self._get_area_for_entity(cover_eid)
            self._opts[CONF_SHUTTER_CONFIGS].append({
                "entity_id":       cover_eid,
                "label":           user_input.get("shutter_label", f"Rolluik {i}"),
                "area_id":         area_id,
                "area_name":       area_name,
                "group":           user_input.get("shutter_group", ""),
                "temp_sensor":     user_input.get("shutter_temp_sensor") or "",
                "auto_thermal":    user_input.get("shutter_auto_thermal", True),
                "auto_solar_gain": user_input.get("shutter_auto_solar_gain", True),
                "auto_overheat":   user_input.get("shutter_auto_overheat", True),
                "night_close_time":  user_input.get("shutter_night_close", "23:00"),
                "morning_open_time": user_input.get("shutter_morning_open", "07:30"),
                "default_setpoint":  float(user_input.get("shutter_default_setpoint", 20.0)),
                "smoke_sensor":    user_input.get("shutter_smoke_sensor") or "",
                "schedule_learning": user_input.get("shutter_schedule_learning", True),
            })
            self._shutter_step += 1
            if self._shutter_step < self._shutter_count:
                return await self.async_step_shutter_detail_opts()
            return self._save(self._opts)

        existing = existing_cfgs[self._shutter_step] if self._shutter_step < len(existing_cfgs) else {}

        # Stel temperatuursensor voor op basis van de ruimte van de cover entity
        cover_eid_hint = existing.get("entity_id", "")
        suggested_temp = existing.get("temp_sensor") or self._suggest_temp_sensor_for_cover(cover_eid_hint)
        area_hint = existing.get("area_name", "")

        temp_sensor_schema = (
            vol.Optional(
                "shutter_temp_sensor",
                description={"suggested_value": suggested_temp},
            )
            if suggested_temp
            else vol.Optional("shutter_temp_sensor")
        )

        return self.async_show_form(
            step_id="shutter_detail_opts",
            data_schema=vol.Schema({
                vol.Required("shutter_entity", description={"suggested_value": cover_eid_hint}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
                vol.Optional("shutter_label", default=existing.get("label", f"Rolluik {i}")): str,
                vol.Optional("shutter_group", default=existing.get("group", "")): str,
                temp_sensor_schema: selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "climate"],
                        device_class="temperature",
                        multiple=False,
                    )
                ),
                vol.Optional("shutter_auto_thermal",    default=existing.get("auto_thermal", True)):    bool,
                vol.Optional("shutter_auto_solar_gain", default=existing.get("auto_solar_gain", True)): bool,
                vol.Optional("shutter_auto_overheat",   default=existing.get("auto_overheat", True)):   bool,
                vol.Optional("shutter_night_close",    default=existing.get("night_close_time", "23:00")):  str,
                vol.Optional("shutter_morning_open",   default=existing.get("morning_open_time", "07:30")): str,
                vol.Optional("shutter_default_setpoint", default=existing.get("default_setpoint", 20.0)):   vol.Coerce(float),
                vol.Optional(
                    "shutter_smoke_sensor",
                    default=existing.get("smoke_sensor", "") or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="smoke", multiple=False)
                ),
                vol.Optional("shutter_schedule_learning", default=existing.get("schedule_learning", True)): bool,
            }),
            description_placeholders={
                "shutter_num":  str(i),
                "total":        str(self._shutter_count),
                "area_hint":    f" (kamer: {area_hint})" if area_hint else "",
                "sensor_hint":  f" • gevonden sensor: {suggested_temp}" if suggested_temp else "",
            },
        )

    async def async_step_advanced_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="advanced_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_DSMR_SOURCE, default=str(data.get(CONF_DSMR_SOURCE, DSMR_SOURCE_HA_ENTITIES))): _dsmr_source_selector(),
                vol.Optional(CONF_P1_ENABLED, default=bool(data.get(CONF_P1_ENABLED, False))): bool,
                vol.Optional(CONF_P1_HOST,    default=str(data.get(CONF_P1_HOST, ""))): str,
                vol.Optional(CONF_P1_PORT,    default=int(data.get(CONF_P1_PORT, DEFAULT_P1_PORT))): vol.All(int, vol.Range(min=1, max=65535)),

            }),
        )


    async def async_step_battery_advanced_opts(self, user_input=None):
        """Options flow: geavanceerde batterij-instellingen (ruimte, terugverdientijd, Mijnbatterij)."""
        data = self._data()
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            return self._save(user_input)
        return self.async_show_form(
            step_id="battery_advanced_opts",
            data_schema=vol.Schema({
                # Mijnbatterij.nl
                vol.Optional("mijnbatterij_api_key",
                    default=str(data.get("mijnbatterij_api_key", ""))): str,
                # Accu-ruimte temperatuur
                vol.Optional("battery_room_temp_sensor",
                    default=str(data.get("battery_room_temp_sensor", ""))): str,
                vol.Optional("battery_room_heater_w",
                    default=float(data.get("battery_room_heater_w", 1500.0))): vol.All(
                        float, vol.Range(min=100, max=10000)),
                vol.Optional("battery_room_climate_entity",
                    default=str(data.get("battery_room_climate_entity", ""))): str,
                vol.Optional("battery_room_auto_heat",
                    default=bool(data.get("battery_room_auto_heat", False))): bool,
                # Terugverdientijd
                vol.Optional("battery_purchase_price_eur",
                    default=float(data.get("battery_purchase_price_eur") or 0)): vol.All(
                        float, vol.Range(min=0, max=50000)),
                vol.Optional("battery_purchase_date",
                    default=str(data.get("battery_purchase_date", ""))): str,
            }),
        )

    # ── Zwembad Controller wizard stap ────────────────────────────────────────
    async def async_step_pool_opts(self, user_input=None):
        """Wizard stap: zwembad filter + warmtepomp configuratie."""
        data = self._data()
        pool_cfg = data.get("pool", {}) or {}

        def _find_power_sensor(switch_eid: str) -> str:
            """Zoek automatisch een vermogensensor bij een schakelaar-entiteit.

            Strategie: neem de naam van de schakelaar (bijv. 'zwembad_pomp'),
            zoek dan sensoren met W/kW unit die die naam bevatten.
            """
            if not switch_eid:
                return ""
            # naam zonder domein, bijv. 'zwembad_pomp'
            base = switch_eid.split(".", 1)[-1].lower()
            keywords = [p for p in base.replace("_", " ").split() if len(p) > 2]
            candidates = [
                s.entity_id for s in self.hass.states.async_all("sensor")
                if s.attributes.get("unit_of_measurement") in ("W", "kW")
            ]
            # score op overlappende keywords
            scored = []
            for eid in candidates:
                eid_lower = eid.lower()
                score = sum(1 for kw in keywords if kw in eid_lower)
                if score > 0:
                    scored.append((eid, score))
            if not scored:
                return ""
            scored.sort(key=lambda x: (-x[1], len(x[0])))
            return scored[0][0]

        # Auto-fill power sensoren als ze nog niet geconfigureerd zijn
        filter_eid        = pool_cfg.get("filter_entity", "")
        heat_eid          = pool_cfg.get("heat_entity", "")
        filter_power_def  = pool_cfg.get("filter_power_entity") or _find_power_sensor(filter_eid)
        heat_power_def    = pool_cfg.get("heat_power_entity")   or _find_power_sensor(heat_eid)

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            new_pool = {
                "filter_entity":       user_input.get("pool_filter_entity", ""),
                "heat_entity":         user_input.get("pool_heat_entity", ""),
                "temp_entity":         user_input.get("pool_temp_entity", ""),
                "uv_entity":           user_input.get("pool_uv_entity", ""),
                "robot_entity":        user_input.get("pool_robot_entity", ""),
                "heat_setpoint":       float(user_input.get("pool_heat_setpoint", 28.0)),
                "filter_power_entity": user_input.get("pool_filter_power_entity", ""),
                "heat_power_entity":   user_input.get("pool_heat_power_entity", ""),
            }
            return self._save({"pool": new_pool})
        return self.async_show_form(
            step_id="pool_opts",
            data_schema=vol.Schema({
                vol.Optional("pool_filter_entity", default=pool_cfg.get("filter_entity", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean"])),
                vol.Optional("pool_filter_power_entity", default=filter_power_def):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["sensor"])),
                vol.Optional("pool_heat_entity", default=pool_cfg.get("heat_entity", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "climate"])),
                vol.Optional("pool_heat_power_entity", default=heat_power_def):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["sensor"])),
                vol.Optional("pool_temp_entity", default=pool_cfg.get("temp_entity", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["sensor"])),
                vol.Optional("pool_uv_entity", default=pool_cfg.get("uv_entity", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean"])),
                vol.Optional("pool_robot_entity", default=pool_cfg.get("robot_entity", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "vacuum"])),
                vol.Optional("pool_heat_setpoint", default=float(pool_cfg.get("heat_setpoint", 28.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=10, max=40)),
            }),
        )

    # ── Virtual Cold Storage wizard stap ─────────────────────────────────────
    async def async_step_virtual_cold_storage(self, user_input=None):
        """Wizard stap: vriezer als thermische batterij (Virtual Cold Storage)."""
        data = self._data()
        vcs_list = data.get("virtual_cold_storage", [])
        vcs = vcs_list[0] if vcs_list else {}
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            entity = user_input.get("vcs_entity_id", "")
            if entity:
                new_vcs = [{
                    "entity_id":             entity,
                    "label":                 user_input.get("vcs_label", "Vriezer"),
                    "temp_sensor":           user_input.get("vcs_temp_sensor", ""),
                    "min_temp_c":            float(user_input.get("vcs_min_temp_c", -24.0)),
                    "max_temp_c":            float(user_input.get("vcs_max_temp_c", -16.0)),
                    "nominal_temp_c":        float(user_input.get("vcs_nominal_temp_c", -18.0)),
                    "super_cool_surplus_w":  float(user_input.get("vcs_surplus_w", 800.0)),
                    "price_off_eur_kwh":     float(user_input.get("vcs_price_off", 0.25)),
                    "active":                bool(user_input.get("vcs_active", True)),
                }]
            else:
                new_vcs = []
            return self._save({"virtual_cold_storage": new_vcs})
        return self.async_show_form(
            step_id="virtual_cold_storage",
            data_schema=vol.Schema({
                vol.Optional("vcs_entity_id",
                             default=vcs.get("entity_id", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch"])),
                vol.Optional("vcs_label",
                             default=vcs.get("label", "Vriezer")): str,
                vol.Optional("vcs_temp_sensor",
                             default=vcs.get("temp_sensor", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
                vol.Optional("vcs_min_temp_c",
                             default=float(vcs.get("min_temp_c", -24.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=-30.0, max=-20.0)),
                vol.Optional("vcs_max_temp_c",
                             default=float(vcs.get("max_temp_c", -16.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=-20.0, max=-10.0)),
                vol.Optional("vcs_nominal_temp_c",
                             default=float(vcs.get("nominal_temp_c", -18.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=-22.0, max=-14.0)),
                vol.Optional("vcs_surplus_w",
                             default=float(vcs.get("super_cool_surplus_w", 800.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=200.0, max=5000.0)),
                vol.Optional("vcs_price_off",
                             default=float(vcs.get("price_off_eur_kwh", 0.25))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.60)),
                vol.Optional("vcs_active",
                             default=bool(vcs.get("active", True))): bool,
            }),
            description_placeholders={
                "info": "Stel een lege switch in om Virtual Cold Storage uit te schakelen."
            }
        )

    # ── Lamp Circulatie wizard stap ───────────────────────────────────────────
    async def async_step_lamp_circ_opts(self, user_input=None):
        """Wizard stap: lampcirculatie configuratie (beveiliging + energiebesparing)."""
        data = self._data()
        lc_cfg = data.get("lamp_circulation", {}) or {}
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # TV simulator config
            tv_sim_entity = user_input.get("lc_tv_sim_entity", "")
            tv_sim_cfg = {}
            if tv_sim_entity:
                tv_sim_cfg = {
                    "entity_id": tv_sim_entity,
                    "active":    bool(user_input.get("lc_tv_sim_active", True)),
                }
            new_lc = {
                "light_entities":  [],  # auto-discovery: alle light.* entiteiten
                "excluded_ids":    user_input.get("lc_excluded_ids", []),
                "enabled":         bool(user_input.get("lc_enabled", False)),
                "min_confidence":  float(user_input.get("lc_min_confidence", 0.55)),
                "night_start_h":   int(user_input.get("lc_night_start_h", 22)),
                "night_end_h":     int(user_input.get("lc_night_end_h", 7)),
                "use_sun_entity":  bool(user_input.get("lc_use_sun_entity", True)),
                "tv_simulator":    tv_sim_cfg,
            }
            return self._save({"lamp_circulation": new_lc})
        return self.async_show_form(
            step_id="lamp_circ_opts",
            data_schema=vol.Schema({
                vol.Optional("lc_excluded_ids",
                             default=lc_cfg.get("excluded_ids", [])):
                    selector.EntitySelector(selector.EntitySelectorConfig(
                        domain=["light", "switch", "input_boolean"], multiple=True)),
                vol.Optional("lc_enabled",
                             default=bool(lc_cfg.get("enabled", False))): bool,
                vol.Optional("lc_use_sun_entity",
                             default=bool(lc_cfg.get("use_sun_entity", True))): bool,
                vol.Optional("lc_min_confidence",
                             default=float(lc_cfg.get("min_confidence", 0.55))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.3, max=0.95)),
                vol.Optional("lc_night_start_h",
                             default=int(lc_cfg.get("night_start_h", 22))):
                    vol.All(vol.Coerce(int), vol.Range(min=18, max=23)),
                vol.Optional("lc_night_end_h",
                             default=int(lc_cfg.get("night_end_h", 7))):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=10)),
                # Ghost 2.0 TV Simulator
                vol.Optional("lc_tv_sim_entity",
                             default=lc_cfg.get("tv_simulator", {}).get("entity_id", "")):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain=["light"])),
                vol.Optional("lc_tv_sim_active",
                             default=bool(lc_cfg.get("tv_simulator", {}).get("active", True))): bool,
            }),
        )

    async def async_step_tab_visibility_opts(self, user_input=None):
        """Wizard stap: stel in welke dashboard-tabbladen zichtbaar zijn in de navigatiebalk.

        Verborgen tabs zijn nog steeds bereikbaar via directe URL
        (bijv. /lovelace/cloudems-zwembad) maar verschijnen niet als tabblad.
        CloudEMS past automatisch 'subview: true/false' aan in het Lovelace dashboard.
        """
        data = self._data()
        current_hidden: list = data.get(CONF_HIDDEN_TABS, list(CLOUDEMS_TABS_HIDDEN_DEFAULT))

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            hidden = user_input.get("hidden_tabs", [])
            result = self._save({CONF_HIDDEN_TABS: hidden})
            # Apply immediately via HA's lovelace storage if available
            try:
                from . import _async_apply_tab_visibility
                self.hass.async_create_task(
                    _async_apply_tab_visibility(self.hass, hidden)
                )
            except Exception:
                pass
            return result

        all_tab_options = [
            selector.SelectOptionDict(value=path, label=label)
            for path, label in CLOUDEMS_TABS
            if path != "cloudems-overzicht"  # Overzicht altijd zichtbaar
        ]

        return self.async_show_form(
            step_id="tab_visibility_opts",
            description_placeholders={
                "info": "Selecteer de tabbladen die je WIL VERBERGEN. "
                        "Verborgen tabs verschijnen niet in de navigatiebalk maar zijn "
                        "nog bereikbaar via directe URL. "
                        "Overzicht is altijd zichtbaar.",
            },
            data_schema=vol.Schema({
                vol.Optional(
                    "hidden_tabs",
                    default=current_hidden,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=all_tab_options,
                        multiple=True,
                        mode="list",
                    )
                ),
            }),
        )

    async def async_step_boiler_groups_opts(self, user_input=None):
        """Options flow: Warm Water Cascade — overzicht + aan/uit + groepen beheren."""
        data = self._data()
        current_groups: list = list(data.get(CONF_BOILER_GROUPS, []))
        enabled = data.get(CONF_BOILER_GROUPS_ENABLED, False)

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            action = user_input.get("bg_action", "add_group")

            if action == "add_group":
                self._opts[CONF_BOILER_GROUPS] = current_groups
                return await self.async_step_boiler_group_add()

            if action.startswith("edit_"):
                idx = int(action.split("_")[1])
                self._opts[CONF_BOILER_GROUPS] = current_groups
                self._opts["_bg_edit_idx"] = idx
                return await self.async_step_boiler_group_edit()

            if action.startswith("delete_"):
                idx = int(action.split("_")[1])
                current_groups.pop(idx)
                return self._save({
                    CONF_BOILER_GROUPS: current_groups,
                })

            # Onbekende actie of terugval → gewoon opslaan en terug
            return self._save({
                CONF_BOILER_GROUPS: current_groups,
            })

        # Build actie-opties (geen "Opslaan" als actie — navigatie-only)
        action_options = [selector.SelectOptionDict(value="add_group", label="➕ Nieuwe groep toevoegen")]
        for i, g in enumerate(current_groups):
            name = g.get("name", f"Groep {i+1}")
            action_options.append(selector.SelectOptionDict(value=f"edit_{i}", label=f"✏️ Bewerk: {name}"))
            action_options.append(selector.SelectOptionDict(value=f"delete_{i}", label=f"🗑️ Verwijder: {name}"))

        # Build groepen-overzicht tekst
        groups_info = ""
        for g in current_groups:
            units = g.get("units", [])
            mode = BOILER_MODE_LABELS.get(g.get("mode", "auto"), g.get("mode", "auto"))
            unit_lines = "\n".join(
                f"  • {u.get('label', u.get('entity_id', '?'))} "
                f"({u.get('setpoint_c', 60):.0f}°C, {u.get('power_w', 2500):.0f}W)"
                for u in units
            ) or "  (geen units)"
            groups_info += f"**{g.get('name', '?')}** — {mode}\n{unit_lines}\n\n"

        return self.async_show_form(
            step_id="boiler_groups_opts",
            description_placeholders={
                "groups_info": groups_info if groups_info else "Nog geen groepen geconfigureerd.",
                "count": str(len(current_groups)),
                "units": str(sum(len(g.get("units", [])) for g in current_groups)),
                "tip": "Gebruik 'Nieuwe groep toevoegen' om boilers te koppelen.",
            },
            data_schema=vol.Schema({
                vol.Required("bg_action", default="add_group"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=action_options, mode="list")
                ),
            }),
        )

    async def async_step_boiler_group_add(self, user_input=None):
        """Voeg een nieuwe cascade-groep toe."""
        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            groups = list(self._opts.get(CONF_BOILER_GROUPS, []))
            unit_count = int(user_input.get("bg_unit_count", 1))
            new_group = {
                "id":    f"group_{len(groups)+1}",
                "name":  user_input.get("bg_name", f"Groep {len(groups)+1}"),
                "mode":  user_input.get("bg_mode", "auto"),
                "units": [],
            }
            groups.append(new_group)
            self._opts[CONF_BOILER_GROUPS] = groups
            self._opts["_bg_edit_idx"] = len(groups) - 1
            self._opts["_bg_unit_count"] = unit_count
            self._opts["_bg_unit_step"] = 0
            return await self.async_step_boiler_group_brand()

        return self.async_show_form(
            step_id="boiler_group_add",
            data_schema=vol.Schema({
                vol.Required("bg_name", default="Groep 1"): str,
                vol.Required("bg_mode", default="auto"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=k, label=v)
                        for k, v in BOILER_MODE_LABELS.items()
                    ], mode="list")
                ),
                vol.Required("bg_unit_count", default="1"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=str(i), label=f"{i} boiler{'s' if i>1 else ''}")
                        for i in range(1, 9)
                    ], mode="list")
                ),
            }),
        )

    async def async_step_boiler_group_edit(self, user_input=None):
        """Bewerk een bestaande cascade-groep: naam, modus en units beheren."""
        # v4.6.174: laad altijd uit _data() zodat bestaande config niet verloren gaat
        # als _opts nog niet gevuld is met boiler_groups (bijv. bij directe edit-navigatie)
        if CONF_BOILER_GROUPS not in self._opts:
            self._opts[CONF_BOILER_GROUPS] = list(self._data().get(CONF_BOILER_GROUPS, []))
        groups = list(self._opts.get(CONF_BOILER_GROUPS, []))
        idx    = int(self._opts.get("_bg_edit_idx", 0))
        group  = groups[idx] if idx < len(groups) else {}
        units  = group.get("units", [])

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            action = user_input.get("bge_action", "save")

            if action == "add_unit":
                # Sla naam+modus al op, ga dan unit toevoegen
                groups[idx]["name"] = user_input.get("bg_name", group.get("name", "Groep"))
                groups[idx]["mode"] = user_input.get("bg_mode", group.get("mode", "auto"))
                self._opts[CONF_BOILER_GROUPS] = groups
                self._opts["_bg_unit_count"] = len(units) + 1
                self._opts["_bg_unit_step"]  = len(units)
                # Tijdelijk: voeg lege placeholder toe die in boiler_group_unit wordt ingevuld
                return await self.async_step_boiler_group_brand()

            if action.startswith("edit_unit_"):
                u_idx = int(action.split("_")[-1])
                groups[idx]["name"] = user_input.get("bg_name", group.get("name", "Groep"))
                groups[idx]["mode"] = user_input.get("bg_mode", group.get("mode", "auto"))
                self._opts[CONF_BOILER_GROUPS] = groups
                self._opts["_bg_unit_edit_idx"] = u_idx
                return await self.async_step_boiler_unit_edit()

            if action.startswith("remove_unit_"):
                u_idx = int(action.split("_")[-1])
                new_units = [u for i, u in enumerate(units) if i != u_idx]
                groups[idx]["units"] = new_units
                # Herberekende prioriteiten
                for i, u in enumerate(new_units):
                    u["priority"] = i + 1
                groups[idx]["name"] = user_input.get("bg_name", group.get("name", "Groep"))
                groups[idx]["mode"] = user_input.get("bg_mode", group.get("mode", "auto"))
                self._opts[CONF_BOILER_GROUPS] = groups
                return self._save(self._opts)

            # save
            groups[idx]["name"] = user_input.get("bg_name", group.get("name", "Groep"))
            groups[idx]["mode"] = user_input.get("bg_mode", group.get("mode", "auto"))
            self._opts[CONF_BOILER_GROUPS] = groups
            return self._save(self._opts)

        # Build unit-overzicht
        units_summary = ""
        for i, u in enumerate(units):
            units_summary += f"**{i+1}.** {u.get('label', u.get('entity_id', '?'))} — {u.get('setpoint_c', 60):.0f}°C\n"

        # Build actie-opties
        edit_actions = [
            selector.SelectOptionDict(value="save",     label="💾 Opslaan en terug"),
            selector.SelectOptionDict(value="add_unit", label="➕ Extra boiler toevoegen"),
        ]
        for i, u in enumerate(units):
            lbl = u.get("label", u.get("entity_id", f"Boiler {i+1}"))
            edit_actions.append(selector.SelectOptionDict(
                value=f"edit_unit_{i}", label=f"✏️ Bewerk boiler: {lbl}"
            ))
        for i, u in enumerate(units):
            lbl = u.get("label", u.get("entity_id", f"Boiler {i+1}"))
            edit_actions.append(selector.SelectOptionDict(
                value=f"remove_unit_{i}", label=f"🗑️ Verwijder boiler: {lbl}"
            ))

        return self.async_show_form(
            step_id="boiler_group_edit",
            description_placeholders={
                "group_name":    group.get("name", "?"),
                "units_summary": units_summary if units_summary else "*(geen boilers)*",
                "unit_count":    str(len(units)),
            },
            data_schema=vol.Schema({
                vol.Required("bg_name", default=group.get("name", "Groep")): str,
                vol.Required("bg_mode", default=group.get("mode", "auto")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=k, label=v)
                        for k, v in BOILER_MODE_LABELS.items()
                    ], mode="list")
                ),
                vol.Required("bge_action", default="save"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=edit_actions, mode="list")
                ),
            }),
        )

    async def async_step_boiler_group_brand(self, user_input=None):
        """Options flow: kies merk/type boiler — vult instellingen automatisch voor."""
        u_step = int(self._opts.get("_bg_unit_step", 0))
        u_total = int(self._opts.get("_bg_unit_count", 1))
        groups = list(self._opts.get(CONF_BOILER_GROUPS, []))
        g_idx  = int(self._opts.get("_bg_edit_idx", 0))
        group  = groups[g_idx] if g_idx < len(groups) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            brand = user_input.get("brand", "unknown")
            self._opts["_bg_brand_preset"] = brand
            return await self.async_step_boiler_group_unit()

        return self.async_show_form(
            step_id="boiler_group_brand",
            description_placeholders={
                "unit_num":   str(u_step + 1),
                "total":      str(u_total),
                "group_name": group.get("name", "?"),
            },
            data_schema=vol.Schema({
                vol.Required("brand", default="unknown"): _boiler_brand_selector(),
            }),
        )

    async def async_step_boiler_group_unit(self, user_input=None):
        """Configureer één boiler-unit binnen een groep."""
        groups  = list(self._opts.get(CONF_BOILER_GROUPS, []))
        g_idx   = int(self._opts.get("_bg_edit_idx", 0))
        u_step  = int(self._opts.get("_bg_unit_step", 0))
        u_total = int(self._opts.get("_bg_unit_count", 1))
        group   = groups[g_idx] if g_idx < len(groups) else {}
        units   = list(group.get("units", []))
        # Merk-preset van vorige stap
        brand_key = self._opts.pop("_bg_brand_preset", "unknown")
        bp = BOILER_BRAND_PRESETS.get(brand_key, BOILER_BRAND_PRESETS["unknown"])

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            units.append({
                "entity_id":            user_input.get("bu_entity", ""),
                "temp_sensor":          user_input.get("bu_temp_sensor", ""),
                "energy_sensor":        user_input.get("bu_energy_sensor", ""),
                "label":                user_input.get("bu_label", f"Boiler {u_step+1}"),
                "setpoint_c":           float(user_input.get("bu_setpoint",           bp.get("setpoint_c",           DEFAULT_BOILER_SETPOINT_C))),
                "surplus_setpoint_c":   float(user_input.get("bu_surplus_setpoint",   bp.get("surplus_setpoint_c",   75.0))),
                "max_setpoint_boost_c": float(user_input.get("bu_max_setpoint_boost", bp.get("max_setpoint_boost_c", 75.0))),
                "max_setpoint_green_c": float(bp.get("max_setpoint_green_c", 53.0)),
                "hardware_max_c":       float(bp.get("hardware_max_c",       0.0)),
                "hardware_deadband_c":  float(bp.get("hardware_deadband_c",  0.0)),
                "stall_timeout_s":      float(bp.get("stall_timeout_s",      300.0)),
                "stall_boost_c":        float(bp.get("stall_boost_c",        5.0)),
                "power_w":              DEFAULT_BOILER_POWER_W,
                "priority":             u_step + 1,
                "boiler_type":          user_input.get("bu_boiler_type",  bp.get("boiler_type",  "resistive")),
                "control_mode":         user_input.get("bu_control_mode", bp.get("control_mode", "setpoint")),
                "preset_on":            user_input.get("bu_preset_on",    bp.get("preset_on",    "on")),
                "preset_off":           user_input.get("bu_preset_off",   bp.get("preset_off",   "off")),
                "dimmer_on_pct":        float(user_input.get("bu_dimmer_on_pct",  100)),
                "dimmer_off_pct":       float(user_input.get("bu_dimmer_off_pct", 0)),
                "brand":                brand_key,
            })
            groups[g_idx]["units"] = units
            self._opts[CONF_BOILER_GROUPS] = groups
            self._opts["_bg_unit_step"] = u_step + 1
            if u_step + 1 < u_total:
                return await self.async_step_boiler_group_brand()
            if len(groups[g_idx].get("units", [])) > 1 or self._opts.get("_bg_edit_idx", -1) >= 0:
                return await self.async_step_boiler_group_edit()
            return self._save(self._opts)

        _default_sp   = bp.get("setpoint_c",            DEFAULT_BOILER_SETPOINT_C)
        _brand_label  = bp.get("_label",                "❓ Onbekend")
        _cat_gu       = _brand_category(brand_key)

        # Basis schema — altijd getoond
        gu_schema: dict = {
            vol.Required("bu_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "climate", "water_heater", "input_boolean"]
                )
            ),
            vol.Optional("bu_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("bu_energy_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor",
                    device_class=["power", "energy"])
            ),
            vol.Optional("bu_label", default=f"Boiler {u_step+1}"): str,
            vol.Optional("bu_setpoint", default=_default_sp): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=85, step=1,
                                              mode="slider", unit_of_measurement="°C")
            ),
        }

        # Categorie-gebaseerde extra velden
        if _cat_gu == "manual":
            gu_schema.update({
                vol.Optional("bu_boiler_type", default=bp.get("boiler_type", "resistive")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "resistive", "label": "⚡ Elektrisch weerstand"},
                        {"value": "heat_pump", "label": "♻️ Warmtepomp boiler"},
                        {"value": "hybrid",    "label": "🔥 Hybride (WP + weerstand)"},
                    ], mode="list")),
                vol.Optional("bu_control_mode", default=bp.get("control_mode", "setpoint")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",         "label": "🔌 Aan/uit schakelaar"},
                        {"value": "setpoint",       "label": "🌡️ Setpoint instellen"},
                        {"value": "setpoint_boost", "label": "🌡️⚡ Setpoint + Boost bij PV-surplus"},
                        {"value": "preset",         "label": "🎛️ Preset modus (bijv. GREEN/BOOST)"},
                    ], mode="list")),
                vol.Optional("bu_preset_on",  default=bp.get("preset_on",  "on")):  selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
                vol.Optional("bu_preset_off", default=bp.get("preset_off", "off")): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
                vol.Optional("bu_max_setpoint_boost", default=bp.get("max_setpoint_boost_c", 75.0)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=85, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
            })
        elif _cat_gu == "generic_switch":
            gu_schema.update({
                vol.Optional("bu_control_mode", default=bp.get("control_mode", "switch")): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",   "label": "🔌 Aan/uit schakelaar"},
                        {"value": "setpoint", "label": "🌡️ Setpoint instellen"},
                    ], mode="list")),
            })
        elif _cat_gu == "dimmer":
            gu_schema.update({
                vol.Optional("bu_dimmer_on_pct",  default=int(bp.get("dimmer_on_pct",  100))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
                vol.Optional("bu_dimmer_off_pct", default=int(bp.get("dimmer_off_pct", 0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
            })
        # known_brand + generic_heatpump: geen extra velden

        # Tankvolume altijd instelbaar
        gu_schema.update({
            vol.Optional("bu_tank_liters", default=int(bp.get("tank_liters", 0))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=5,
                                              mode="slider", unit_of_measurement="L")),
        })

        return self.async_show_form(
            step_id="boiler_group_unit",
            description_placeholders={
                "unit_num":    str(u_step + 1),
                "total":       str(u_total),
                "group_name":  group.get("name", "?"),
                "brand_label": _brand_label,
            },
            data_schema=vol.Schema(gu_schema),
        )


    async def async_step_boiler_unit_edit(self, user_input=None):
        """Bewerk een bestaande boiler-unit — pre-filled met huidige waarden."""
        # v4.6.174: zorg dat boiler_groups altijd aanwezig zijn in _opts
        if CONF_BOILER_GROUPS not in self._opts:
            self._opts[CONF_BOILER_GROUPS] = list(self._data().get(CONF_BOILER_GROUPS, []))
        groups  = list(self._opts.get(CONF_BOILER_GROUPS, []))
        g_idx   = int(self._opts.get("_bg_edit_idx", 0))
        u_idx   = int(self._opts.get("_bg_unit_edit_idx", 0))
        group   = groups[g_idx] if g_idx < len(groups) else {}
        units   = list(group.get("units", []))
        unit    = units[u_idx] if u_idx < len(units) else {}

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            # Haal merk-preset op als gebruiker een ander merk kiest
            brand_key = user_input.get("bu_brand", unit.get("brand", "unknown"))
            bp = BOILER_BRAND_PRESETS.get(brand_key, BOILER_BRAND_PRESETS["unknown"])
            _brand_changed = brand_key != unit.get("brand", "unknown")
            _is_known = brand_key not in ("unknown", "generic_resistive", "generic_heatpump")

            updated = dict(unit)
            # v4.6.136: entity-selector velden zijn Optional met suggested_value.
            # HA stuurt ze als lege string als de gebruiker ze wist. Filter deze
            # leeg-overschrijvingen zodat bestaande sensor-config behouden blijft.
            def _keep(key_ui: str, key_unit: str, fallback: str = "") -> str:
                v = user_input.get(key_ui, "")
                return v if v else unit.get(key_unit, fallback)
            updated.update({
                "entity_id":            user_input.get("bu_entity",           unit.get("entity_id", "")),
                "temp_sensor":          _keep("bu_temp_sensor",    "temp_sensor"),
                "energy_sensor":        _keep("bu_energy_sensor",  "energy_sensor"),
                "label":                user_input.get("bu_label",            unit.get("label", f"Boiler {u_idx+1}")),
                # boiler_type/control_mode/preset: bij known brand altijd uit preset overnemen
                # (velden niet getoond), tenzij generic → dan uit user_input
                "boiler_type":          bp.get("boiler_type", "resistive") if _is_known
                                        else user_input.get("bu_boiler_type", unit.get("boiler_type", "resistive")),
                "setpoint_c":           float(user_input.get("bu_setpoint",           unit.get("setpoint_c",           DEFAULT_BOILER_SETPOINT_C))),
                "max_setpoint_entity":   user_input.get("bu_max_setpoint_entity", unit.get("max_setpoint_entity", "")),
                # surplus_setpoint en max_setpoint_boost: bij known brand uit preset,
                # bij generiek uit user_input (velden zichtbaar)
                "surplus_setpoint_c":   float(bp.get("surplus_setpoint_c", unit.get("surplus_setpoint_c", 75.0)) if _is_known
                                              else user_input.get("bu_surplus_setpoint", unit.get("surplus_setpoint_c", bp.get("surplus_setpoint_c", 75.0)))),
                "max_setpoint_boost_c": float(bp.get("max_setpoint_boost_c", unit.get("max_setpoint_boost_c", 75.0)) if _is_known
                                              else user_input.get("bu_max_setpoint_boost", unit.get("max_setpoint_boost_c", bp.get("max_setpoint_boost_c", 75.0)))),
                "max_setpoint_green_c": float(bp.get("max_setpoint_green_c", unit.get("max_setpoint_green_c", 53.0)) if _brand_changed else unit.get("max_setpoint_green_c", bp.get("max_setpoint_green_c", 53.0))),
                "hardware_max_c":       float(bp.get("hardware_max_c", unit.get("hardware_max_c", 0.0)) if _brand_changed else unit.get("hardware_max_c", bp.get("hardware_max_c", 0.0))),
                "hardware_deadband_c":  float(bp.get("hardware_deadband_c", unit.get("hardware_deadband_c", 0.0)) if _brand_changed else unit.get("hardware_deadband_c", 0.0)),
                "stall_timeout_s":      float(bp.get("stall_timeout_s", unit.get("stall_timeout_s", 300.0)) if _brand_changed else unit.get("stall_timeout_s", 300.0)),
                "stall_boost_c":        float(bp.get("stall_boost_c", unit.get("stall_boost_c", 5.0)) if _brand_changed else unit.get("stall_boost_c", 5.0)),
                "control_mode":         bp.get("control_mode", "setpoint") if _is_known
                                        else user_input.get("bu_control_mode", unit.get("control_mode", "setpoint")),
                "preset_on":            bp.get("preset_on", "on") if _is_known
                                        else user_input.get("bu_preset_on", unit.get("preset_on", "on")),
                "preset_off":           bp.get("preset_off", "off") if _is_known
                                        else user_input.get("bu_preset_off", unit.get("preset_off", "off")),
                "dimmer_on_pct":        float(user_input.get("bu_dimmer_on_pct",  unit.get("dimmer_on_pct",  100))),
                "dimmer_off_pct":       float(user_input.get("bu_dimmer_off_pct", unit.get("dimmer_off_pct", 0))),
                "brand":                brand_key,
                # v4.6.561: tankvolume en ramp-max opslaan
                "tank_liters":          int(user_input.get("bu_tank_liters",    unit.get("tank_liters",       0))),
                "cheap_ramp_max_c":     int(user_input.get("bu_cheap_ramp_max", unit.get("cheap_ramp_max_c", 65))),
            })
            units[u_idx] = updated
            groups[g_idx]["units"] = units
            self._opts[CONF_BOILER_GROUPS] = groups
            return await self.async_step_boiler_group_edit()

        # Haal huidige merk-preset op voor pre-fill
        cur_brand = unit.get("brand", "unknown")
        # v4.6.26: Auto-detectie voor oude configs zonder brand-sleutel.
        # Vergelijk opgeslagen control_mode + preset_on/off met bekende presets.
        if cur_brand in ("unknown", "") and unit.get("control_mode"):
            _saved_cm   = unit.get("control_mode", "")
            _saved_pon  = unit.get("preset_on",    "").upper()
            _saved_poff = unit.get("preset_off",   "").upper()
            _saved_type = unit.get("boiler_type",  "")
            for _bk, _bpreset in BOILER_BRAND_PRESETS.items():
                if _bk in ("unknown", "generic_resistive", "generic_heatpump"):
                    continue
                # Match op control_mode + preset_on/off (case-insensitief)
                _cm_match  = _bpreset.get("control_mode") == _saved_cm
                _pon_match = _bpreset.get("preset_on",  "").upper() == _saved_pon
                _poff_match= _bpreset.get("preset_off", "").upper() == _saved_poff
                # Extra: match ook op boiler_type als presets gelijk zijn
                _type_match= _bpreset.get("boiler_type", "") == _saved_type
                if _cm_match and (_pon_match and _poff_match or _type_match):
                    cur_brand = _bk
                    break
        # Laatste fallback: boiler_type=hybrid + control_mode=preset → ariston_lydos_hybrid
        if cur_brand in ("unknown", "") and unit.get("boiler_type") == "hybrid" and unit.get("control_mode") == "preset":
            cur_brand = "ariston_lydos_hybrid"
        bp = BOILER_BRAND_PRESETS.get(cur_brand, BOILER_BRAND_PRESETS["unknown"])
        _is_known_brand = cur_brand not in ("unknown", "generic_resistive", "generic_heatpump")

        # Basis schema — altijd getoond
        edit_schema = {
            vol.Required("bu_entity", default=unit.get("entity_id", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "climate", "water_heater", "input_boolean"]
                )
            ),
            vol.Optional("bu_temp_sensor",
                         default=unit.get("temp_sensor", "") or vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("bu_energy_sensor",
                         default=unit.get("energy_sensor", "") or vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=["power", "energy"])
            ),
            vol.Optional("bu_label", default=unit.get("label", f"Boiler {u_idx+1}")): str,
            vol.Optional("bu_brand", default=cur_brand): _boiler_brand_selector(),
            vol.Optional("bu_setpoint",
                         default=unit.get("setpoint_c", DEFAULT_BOILER_SETPOINT_C)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=85, step=1,
                                              mode="slider", unit_of_measurement="°C")
            ),
            # v4.6.25: max_setpoint_entity — number-entity die de hardware-limiet bestuurt
            # (bijv. number.ariston_max_setpoint_temperature). Altijd zichtbaar zodat ook
            # gebruikers van bekende merken dit veld kunnen invullen.
            vol.Optional("bu_max_setpoint_entity",
                         default=unit.get("max_setpoint_entity") or vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
        }

        # v4.6.562: categorie-gebaseerde velden in edit-wizard
        _cat_edit = _brand_category(cur_brand)
        _def_cm   = unit.get("control_mode", bp.get("control_mode", "setpoint"))
        _def_type = unit.get("boiler_type",  bp.get("boiler_type",  "resistive"))
        _def_pon  = unit.get("preset_on",    bp.get("preset_on",    "on"))
        _def_poff = unit.get("preset_off",   bp.get("preset_off",   "off"))

        if _cat_edit == "manual":
            edit_schema.update({
                vol.Optional("bu_surplus_setpoint",
                             default=unit.get("surplus_setpoint_c", bp.get("surplus_setpoint_c", 75.0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=85, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
                vol.Optional("bu_max_setpoint_boost",
                             default=unit.get("max_setpoint_boost_c", bp.get("max_setpoint_boost_c", 75.0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=85, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
                vol.Optional("bu_boiler_type", default=_def_type): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "resistive", "label": "⚡ Elektrisch weerstand"},
                        {"value": "heat_pump", "label": "♻️ Warmtepomp boiler"},
                        {"value": "hybrid",    "label": "🔥 Hybride (WP + weerstand)"},
                    ], mode="list")),
                vol.Optional("bu_control_mode", default=_def_cm): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",         "label": "🔌 Aan/uit schakelaar"},
                        {"value": "setpoint",       "label": "🌡️ Setpoint instellen"},
                        {"value": "setpoint_boost", "label": "🌡️⚡ Setpoint + Boost bij PV-surplus"},
                        {"value": "preset",         "label": "🎛️ Preset modus (bijv. GREEN/BOOST)"},
                    ], mode="list")),
                vol.Optional("bu_preset_on",  default=_def_pon):  selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
                vol.Optional("bu_preset_off", default=_def_poff): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")),
            })

        elif _cat_edit == "generic_switch":
            edit_schema.update({
                vol.Optional("bu_control_mode", default=_def_cm): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": "switch",   "label": "🔌 Aan/uit schakelaar"},
                        {"value": "setpoint", "label": "🌡️ Setpoint instellen"},
                    ], mode="list")),
            })

        elif _cat_edit == "dimmer":
            edit_schema.update({
                vol.Optional("bu_dimmer_on_pct",
                             default=unit.get("dimmer_on_pct", bp.get("dimmer_on_pct", 100))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
                vol.Optional("bu_dimmer_off_pct",
                             default=unit.get("dimmer_off_pct", bp.get("dimmer_off_pct", 0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")),
            })
        # known_brand + generic_heatpump: geen extra velden

        return self.async_show_form(
            step_id="boiler_unit_edit",
            description_placeholders={
                "unit_label": unit.get("label", unit.get("entity_id", f"Boiler {u_idx+1}")),
                "group_name": group.get("name", "?"),
            },
            data_schema=vol.Schema({
                **edit_schema,
                vol.Optional("bu_tank_liters",
                             default=int(unit.get("tank_liters", 0))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=500, step=5,
                                                  mode="slider", unit_of_measurement="L")),
                vol.Optional("bu_cheap_ramp_max",
                             default=int(unit.get("cheap_ramp_max_c", 65))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=85, step=1,
                                                  mode="slider", unit_of_measurement="°C")),
            }),
        )


    async def async_step_mail_opts(self, user_input=None):
        """E-mail / SMTP opties — ook bereikbaar vanuit het Configureren-menu."""
        errors: dict = {}
        data = self._data()

        if user_input is not None:
            _back = await self._maybe_back(user_input)
            if _back is not None: return _back
            enabled = user_input.get(CONF_MAIL_ENABLED, False)
            if enabled:
                if not user_input.get(CONF_MAIL_HOST, "").strip():
                    errors[CONF_MAIL_HOST] = "mail_host_required"
                if not user_input.get(CONF_MAIL_TO, "").strip():
                    errors[CONF_MAIL_TO] = "mail_to_required"
                if not errors:
                    try:
                        import smtplib, ssl as _ssl
                        host     = user_input[CONF_MAIL_HOST].strip()
                        port     = user_input.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)
                        use_tls  = user_input.get(CONF_MAIL_USE_TLS, True)
                        ctx      = _ssl.create_default_context() if use_tls else None
                        with smtplib.SMTP(host, port, timeout=5) as smtp:
                            if use_tls:
                                smtp.starttls(context=ctx)
                            u = user_input.get(CONF_MAIL_USERNAME, "").strip()
                            p = user_input.get(CONF_MAIL_PASSWORD, "").strip()
                            if u and p:
                                smtp.login(u, p)
                    except Exception as _err:
                        errors["base"] = "mail_connection_failed"
                        _LOGGER.warning("CloudEMS mail test mislukt: %s", _err)
            if not errors:
                # v4.6.432: eerst generator opties
                self._opts = {**self._data(), **user_input}
                return await self.async_step_generator_opts()

        return self.async_show_form(
            step_id="mail_opts",
            errors=errors,
            description_placeholders={
                "info": (
                    "💡 Gebruik voor Gmail een App-wachtwoord "
                    "(myaccount.google.com → Beveiliging → App-wachtwoorden). "
                    "Office 365: smtp.office365.com, poort 587."
                )
            },
            data_schema=vol.Schema({
                vol.Optional(CONF_MAIL_ENABLED,  default=data.get(CONF_MAIL_ENABLED, False)): bool,
                vol.Optional(CONF_MAIL_HOST,     description={"suggested_value": data.get(CONF_MAIL_HOST, "")}): str,
                vol.Optional(CONF_MAIL_PORT,     default=data.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)):
                    vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_MAIL_USE_TLS,  default=data.get(CONF_MAIL_USE_TLS, DEFAULT_MAIL_USE_TLS)): bool,
                vol.Optional(CONF_MAIL_USERNAME, description={"suggested_value": data.get(CONF_MAIL_USERNAME, "")}): str,
                vol.Optional(CONF_MAIL_PASSWORD, description={"suggested_value": data.get(CONF_MAIL_PASSWORD, "")}): str,
                vol.Optional(CONF_MAIL_FROM,     description={"suggested_value": data.get(CONF_MAIL_FROM, "")}): str,
                vol.Optional(CONF_MAIL_TO,       description={"suggested_value": data.get(CONF_MAIL_TO, "")}): str,
                vol.Optional(CONF_MAIL_MONTHLY,  default=data.get(CONF_MAIL_MONTHLY, True)): bool,
                vol.Optional(CONF_MAIL_WEEKLY,   default=data.get(CONF_MAIL_WEEKLY, False)): bool,
            }),
        )
