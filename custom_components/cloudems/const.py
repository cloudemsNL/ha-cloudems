# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""Constants for CloudEMS integration — v1.5.0."""

DOMAIN = "cloudems"
# Versie wordt centraal gelezen uit manifest.json — nooit handmatig aanpassen
import json as _json
import os as _os
_MANIFEST_PATH = _os.path.join(_os.path.dirname(__file__), "manifest.json")
try:
    with open(_MANIFEST_PATH, encoding="utf-8") as _f:
        VERSION: str = _json.load(_f)["version"]
except FileNotFoundError:
    VERSION = "4.6.454"  # manifest.json niet gevonden (unit tests / dev omgeving)
except (KeyError, ValueError) as _e:
    VERSION = "4.6.454"  # manifest.json ongeldig
MANUFACTURER = "CloudEMS"
NAME = "CloudEMS Energy Manager"
WEBSITE = "https://cloudems.eu"
SUPPORT_URL = "https://github.com/cloudemsNL/ha-cloudems"
BUY_ME_COFFEE_URL = "https://buymeacoffee.com/cloudems"
ATTRIBUTION = "Data provided by CloudEMS — cloudems.eu"

ATTR_PROBABILITY = "probability"
ATTR_DEVICE_TYPE = "device_type"
ATTR_CONFIRMED   = "confirmed"
ATTR_MANUFACTURER= "CloudEMS"
ATTR_MODEL       = f"CloudEMS v{VERSION}"

ICON_NILM     = "mdi:home-analytics"
ICON_LIMITER  = "mdi:current-ac"
ICON_PRICE    = "mdi:currency-eur"
ICON_SOLAR    = "mdi:solar-power"
ICON_VOLTAGE  = "mdi:sine-wave"
ICON_POWER    = "mdi:flash"
ICON_FORECAST = "mdi:weather-sunny-alert"
ICON_ENERGY   = "mdi:lightning-bolt-circle"
ICON_PEAK     = "mdi:chart-bell-curve-cumulative"

# ── Core config keys ──────────────────────────────────────────────────────────
CONF_GRID_SENSOR             = "grid_sensor"
CONF_PHASE_SENSORS           = "phase_sensors"
CONF_SOLAR_SENSOR            = "solar_sensor"
CONF_BATTERY_SENSOR          = "battery_sensor"
CONF_EV_CHARGER_ENTITY       = "ev_charger_entity"
CONF_ENERGY_PRICES_COUNTRY   = "energy_prices_country"
CONF_EPEX_COUNTRY            = CONF_ENERGY_PRICES_COUNTRY
CONF_CLOUD_API_KEY           = "cloud_api_key"
CONF_NILM_MODE               = "nilm_mode"
CONF_MAX_CURRENT_PER_PHASE   = "max_current_per_phase"
CONF_ENABLE_SOLAR_DIMMER     = "enable_solar_dimmer"
CONF_NEGATIVE_PRICE_THRESHOLD= "negative_price_threshold"
CONF_GRID_PHASES             = "grid_phases"
CONF_MAINS_VOLTAGE           = "mains_voltage"
DEFAULT_MAINS_VOLTAGE_V      = 230.0

# ── v1.5: Wizard mode ─────────────────────────────────────────────────────────
CONF_WIZARD_MODE      = "wizard_mode"
WIZARD_MODE_BASIC     = "basic"
WIZARD_MODE_ADVANCED  = "advanced"

# ── v1.5: AI Provider ─────────────────────────────────────────────────────────
CONF_AI_PROVIDER      = "ai_provider"
AI_PROVIDER_NONE      = "none"
AI_PROVIDER_CLOUDEMS  = "cloudems"
AI_PROVIDER_OPENAI    = "openai"
AI_PROVIDER_ANTHROPIC = "anthropic"
AI_PROVIDER_OLLAMA    = "ollama"

AI_PROVIDER_LABELS = {
    AI_PROVIDER_NONE:      "None — built-in pattern matching only",
    AI_PROVIDER_OLLAMA:    "Ollama — local LLM (privacy-first, no cloud)",
    AI_PROVIDER_CLOUDEMS:  "CloudEMS Cloud — highest accuracy",
    AI_PROVIDER_OPENAI:    "OpenAI (GPT-4o)",
    AI_PROVIDER_ANTHROPIC: "Anthropic (Claude)",
}

# Which providers need an external API key
AI_PROVIDERS_NEEDING_KEY = {AI_PROVIDER_CLOUDEMS, AI_PROVIDER_OPENAI, AI_PROVIDER_ANTHROPIC}

# ── v1.5: NILM confidence threshold ──────────────────────────────────────────
CONF_NILM_CONFIDENCE      = "nilm_min_confidence"
DEFAULT_NILM_CONFIDENCE   = 0.65

# ── v1.4: Separate import / export sensors ────────────────────────────────────
CONF_USE_SEPARATE_IE = "use_separate_import_export"
CONF_IMPORT_SENSOR   = "import_power_sensor"
CONF_EXPORT_SENSOR   = "export_power_sensor"

# ── v1.4: Per-phase voltage + power sensors ───────────────────────────────────
CONF_VOLTAGE_L1 = "voltage_sensor_l1"
CONF_VOLTAGE_L2 = "voltage_sensor_l2"
CONF_VOLTAGE_L3 = "voltage_sensor_l3"
CONF_POWER_L1   = "power_sensor_l1"
CONF_POWER_L2   = "power_sensor_l2"
CONF_POWER_L3   = "power_sensor_l3"

# ── v1.4: Ollama local AI ─────────────────────────────────────────────────────
CONF_OLLAMA_ENABLED  = "ollama_enabled"
CONF_OLLAMA_HOST     = "ollama_host"
CONF_OLLAMA_PORT     = "ollama_port"
CONF_OLLAMA_MODEL    = "ollama_model"
DEFAULT_OLLAMA_HOST  = "localhost"
DEFAULT_OLLAMA_PORT  = 11434
DEFAULT_OLLAMA_MODEL = "llama3"

# ── v1.4: Inverter config ─────────────────────────────────────────────────────
CONF_INVERTER_COUNT          = "inverter_count"
CONF_INVERTER_CONFIGS        = "inverter_configs"
CONF_INVERTER_CONTROL_ENTITY = "inverter_control_entity"
CONF_INVERTER_PRIORITY       = "inverter_priority"
CONF_INVERTER_MIN_POWER_PCT  = "inverter_min_power_pct"
CONF_INVERTER_LABEL          = "inverter_label"
CONF_ENABLE_MULTI_INVERTER   = "enable_multi_inverter"
STORAGE_KEY_SOLAR_PROFILES   = "cloudems_solar_profiles_v2"

# ── v1.4: Peak shaving ────────────────────────────────────────────────────────
CONF_PEAK_SHAVING_ENABLED    = "peak_shaving_enabled"
CONF_PEAK_SHAVING_LIMIT_W    = "peak_shaving_limit_w"
CONF_PEAK_SHAVING_ASSETS     = "peak_shaving_assets"
DEFAULT_PEAK_SHAVING_LIMIT_W = 5000

# ── EPEX cheap-hour ───────────────────────────────────────────────────────────
CONF_CHEAP_HOURS_COUNT    = "cheap_hours_count"
DEFAULT_CHEAP_HOURS_COUNT = 3

# ── Phase config ──────────────────────────────────────────────────────────────
CONF_PHASE_COUNT         = "phase_count"
CONF_PHASE_PRESET        = "phase_preset"
CONF_MAX_CURRENT_L1      = "max_current_l1"
CONF_MAX_CURRENT_L2      = "max_current_l2"
CONF_MAX_CURRENT_L3      = "max_current_l3"
CONF_MAX_CURRENT_IMPORT  = "max_current_import"
CONF_MAX_CURRENT_EXPORT  = "max_current_export"
CONF_SOLAR_INVERTER_SWITCH= "solar_inverter_switch"
CONF_EV_CHARGER_SWITCH   = "ev_charger_switch"
CONF_BATTERY_SWITCH      = "battery_switch"

PHASE_PRESETS: dict = {
    "1x16A": {"count":1,"L1":16, "L2":None,"L3":None},
    "1x20A": {"count":1,"L1":20, "L2":None,"L3":None},
    "1x25A": {"count":1,"L1":25, "L2":None,"L3":None},
    "1x35A": {"count":1,"L1":35, "L2":None,"L3":None},
    "3x16A": {"count":3,"L1":16, "L2":16,  "L3":16},
    "3x20A": {"count":3,"L1":20, "L2":20,  "L3":20},
    "3x25A": {"count":3,"L1":25, "L2":25,  "L3":25},
    "3x32A": {"count":3,"L1":32, "L2":32,  "L3":32},
    "custom":{"count":None,"L1":None,"L2":None,"L3":None},
}
PHASE_PRESET_LABELS: dict = {
    "1x16A": "1 phase — 16 A",
    "1x20A": "1 phase — 20 A",
    "1x25A": "1 phase — 25 A",
    "1x35A": "1 phase — 35 A",
    "3x16A": "3 phases — 3×16 A",
    "3x20A": "3 phases — 3×20 A",
    "3x25A": "3 phases — 3×25 A",
    "3x32A": "3 phases — 3×32 A",
    "custom":"Custom (manual entry)",
}
PHASES     = ["L1","L2","L3"]
PHASE_L1, PHASE_L2, PHASE_L3 = "L1","L2","L3"
ALL_PHASES = [PHASE_L1, PHASE_L2, PHASE_L3]

# ── P1 / DSMR ─────────────────────────────────────────────────────────────────
CONF_P1_INTEGRATION = "p1_integration"
CONF_P1_SENSOR      = "p1_sensor"
P1_ENTITY_KEYWORDS  = [
    "dsmr","p1","slimme_meter","homewizard",
    "power_delivered","electricity_delivered","power_usage","net_consumption",
]

# ── EV charging ───────────────────────────────────────────────────────────────
CONF_DYNAMIC_EV_CHARGING    = "dynamic_ev_charging"
CONF_EV_CHEAP_THRESHOLD     = "ev_cheap_price_threshold"
CONF_EV_ALWAYS_ON_CURRENT   = "ev_always_on_current"
CONF_EV_SOLAR_SURPLUS_PRIO  = "ev_solar_surplus_priority"
CONF_EV_MIN_SOC_THRESHOLD   = "ev_min_soc_threshold"
CONF_EV_SMART_SCHEDULE      = "ev_smart_schedule"
DEFAULT_EV_CHEAP_THRESHOLD   = 0.10
DEFAULT_EV_ALWAYS_ON_CURRENT = 6
DEFAULT_EV_MIN_SOC_THRESHOLD = 20

# ── Phase balancing ───────────────────────────────────────────────────────────
CONF_ENABLE_PHASE_BALANCING     = "enable_phase_balancing"
DEFAULT_PHASE_BALANCE_THRESHOLD = 4.0
CONF_ENERGY_TAX                 = "energy_tax"
DEFAULT_ENERGY_TAX_NL           = 0.11281
CONF_ENABLE_DIAGNOSTICS         = "enable_diagnostics"
DIAG_REPORT_EVENT               = f"{DOMAIN}_diagnostic_report"

# ── EPEX ──────────────────────────────────────────────────────────────────────
EPEX_COUNTRIES = {
    "NL":"Netherlands","BE":"Belgium","DE":"Germany",
    "FR":"France","AT":"Austria","CH":"Switzerland",
    "DK":"Denmark","NO":"Norway","SE":"Sweden","FI":"Finland",
}
EPEX_AREAS = {
    "NL":"10YNL----------L","BE":"10YBE----------2",
    "DE":"10Y1001A1001A82H","FR":"10YFR-RTE------C",
    "AT":"10YAT-APG------L","CH":"10YCH-SWISSGRID--D",
    "DK":"10YDK-1--------W","NO":"10YNO-0--------C",
    "SE":"10YSE-1--------K","FI":"10YFI-1--------U",
}
EPEX_UPDATE_INTERVAL             = 3600
DEFAULT_NEGATIVE_PRICE_THRESHOLD = 0.0
DEFAULT_EPEX_COUNTRY             = "NL"

# Countries that have a free (no-API-key) price source built in
EPEX_FREE_COUNTRIES = {"NL", "DE", "AT"}

# Optional separate ENTSO-E transparency platform key (free registration)
CONF_ENTSOE_API_KEY = "entsoe_api_key"

# ── NILM ──────────────────────────────────────────────────────────────────────
NILM_MODE_DATABASE   = "database"
NILM_MODE_LOCAL_AI   = "local_ai"
NILM_MODE_CLOUD_AI   = "cloud_ai"
NILM_MODE_OLLAMA     = "ollama"
NILM_MIN_CONFIDENCE  = 0.75   # v4.5.12: bij twijfel niet detecteren — liever minder maar zeker
NILM_HIGH_CONFIDENCE = 0.92   # v4.5.12: nieuw apparaat alleen direct zichtbaar bij hoge zekerheid
NILM_LEARNING_WINDOW = 30
NILM_FEEDBACK_CORRECT   = "correct"
NILM_FEEDBACK_INCORRECT = "incorrect"
NILM_FEEDBACK_MAYBE     = "maybe"

# ── Device types ──────────────────────────────────────────────────────────────
DEVICE_TYPE_REFRIGERATOR    = "refrigerator"
DEVICE_TYPE_WASHING_MACHINE = "washing_machine"
DEVICE_TYPE_DRYER           = "dryer"
DEVICE_TYPE_DISHWASHER      = "dishwasher"
DEVICE_TYPE_OVEN            = "oven"
DEVICE_TYPE_MICROWAVE       = "microwave"
DEVICE_TYPE_KETTLE          = "kettle"
DEVICE_TYPE_TV              = "television"
DEVICE_TYPE_COMPUTER        = "computer"
DEVICE_TYPE_HEAT_PUMP       = "heat_pump"
DEVICE_TYPE_BOILER          = "boiler"
DEVICE_TYPE_EV_CHARGER      = "ev_charger"
DEVICE_TYPE_SOLAR_INVERTER  = "solar_inverter"
DEVICE_TYPE_LIGHT           = "light"
DEVICE_TYPE_UNKNOWN         = "unknown"

DEVICE_ICONS = {
    DEVICE_TYPE_REFRIGERATOR:   "mdi:fridge",
    DEVICE_TYPE_WASHING_MACHINE:"mdi:washing-machine",
    DEVICE_TYPE_DRYER:          "mdi:tumble-dryer",
    DEVICE_TYPE_DISHWASHER:     "mdi:dishwasher",
    DEVICE_TYPE_OVEN:           "mdi:stove",
    DEVICE_TYPE_MICROWAVE:      "mdi:microwave",
    DEVICE_TYPE_KETTLE:         "mdi:kettle",
    DEVICE_TYPE_TV:             "mdi:television",
    DEVICE_TYPE_COMPUTER:       "mdi:desktop-classic",
    DEVICE_TYPE_HEAT_PUMP:      "mdi:heat-pump",
    DEVICE_TYPE_BOILER:         "mdi:water-boiler",
    DEVICE_TYPE_EV_CHARGER:     "mdi:ev-station",
    DEVICE_TYPE_SOLAR_INVERTER: "mdi:solar-power",
    DEVICE_TYPE_LIGHT:          "mdi:lightbulb",
    DEVICE_TYPE_UNKNOWN:        "mdi:help-circle",
    # v1.1.0: generiek stopcontact
    "socket":                   "mdi:power-socket-eu",
}

# ── Timing ────────────────────────────────────────────────────────────────────
DEFAULT_MAX_CURRENT        = 25
DEFAULT_MAX_CURRENT_IMPORT = 25
DEFAULT_MAX_CURRENT_EXPORT = 25
LIMITER_UPDATE_INTERVAL    = 10
MIN_EV_CURRENT             = 6
MAX_EV_CURRENT             = 32
UPDATE_INTERVAL_FAST       = 10
UPDATE_INTERVAL_SLOW       = 300

# ── Cloud ─────────────────────────────────────────────────────────────────────
CLOUD_API_BASE        = "https://api.cloudems.eu/v1"
CLOUD_NILM_ENDPOINT   = "/nilm/classify"
CLOUD_PRICES_ENDPOINT = "/prices/epex"

# ── Storage keys ──────────────────────────────────────────────────────────────
STORAGE_KEY_NILM_DEVICES     = f"{DOMAIN}_nilm_devices"
STORAGE_KEY_LEARNED_PROFILES = f"{DOMAIN}_learned_profiles"
STORAGE_KEY_ENERGY_STATS     = f"{DOMAIN}_energy_stats_v2"
STORAGE_KEY_DIAGNOSTICS      = f"{DOMAIN}_diagnostics"
STORAGE_KEY_NILM_ENERGY      = f"{DOMAIN}_nilm_energy_v1"
STORAGE_KEY_ENERGY_COST      = f"{DOMAIN}_energy_cost"
STORAGE_KEY_PEAK_HISTORY     = f"{DOMAIN}_peak_history_v1"
STORAGE_KEY_NILM_TOGGLES     = f"{DOMAIN}_nilm_toggles_v1"   # v1.22: NILM schakelaars

# ── v1.22: NILM toggle defaults ───────────────────────────────────────────────
# Standaard UIT — zodat gebruikers bewust NILM aanzetten en testresultaten
# stap voor stap kunnen evalueren (NILM → HybridNILM → HMM).
DEFAULT_NILM_ACTIVE        = True
DEFAULT_HYBRID_NILM_ACTIVE = True
DEFAULT_NILM_HMM_ACTIVE    = True
DEFAULT_NILM_BAYES_ACTIVE  = True    # v1.23: Bayesian posterior classifier

# ── Platforms ─────────────────────────────────────────────────────────────────
PLATFORM_SENSOR = "sensor"
PLATFORM_SWITCH = "switch"
PLATFORM_NUMBER = "number"
PLATFORM_BUTTON = "button"
PLATFORM_SELECT = "select"

# ── v1.8.0 — PID tuning entities ─────────────────────────────────────────────
CONF_PID_PHASE_KP             = "pid_phase_kp"
CONF_PID_PHASE_KI             = "pid_phase_ki"
CONF_PID_PHASE_KD             = "pid_phase_kd"
CONF_PID_EV_KP                = "pid_ev_kp"
CONF_PID_EV_KI                = "pid_ev_ki"
CONF_PID_EV_KD                = "pid_ev_kd"
CONF_PRICE_THRESHOLD_CHEAP    = "price_threshold_cheap"   # configurable cheap price
CONF_NILM_THRESHOLD_W         = "nilm_threshold_w"        # adaptive NILM sensitivity

# v1.8.0 — NILM input mode
NILM_INPUT_PER_PHASE          = "per_phase"      # per-phase power (best)
NILM_INPUT_TOTAL_SPLIT        = "total_split"    # total grid / phase_count (fallback)
NILM_INPUT_TOTAL_L1           = "total_l1"       # total grid on L1 only (last resort)

# v1.8.0 — Adaptive NILM defaults
DEFAULT_NILM_THRESHOLD_W      = 25.0     # start value; adapts down to ~8W
NILM_MIN_THRESHOLD_W          = 8.0      # never go below 8W (avoids noise triggers)
NILM_MAX_THRESHOLD_W          = 100.0    # never above 100W (would miss most devices)
NILM_NOISE_WINDOW             = 60       # samples for noise estimation

# v1.8.0 — PID defaults
DEFAULT_PID_PHASE_KP          = 3.0
DEFAULT_PID_PHASE_KI          = 0.4
DEFAULT_PID_PHASE_KD          = 0.8
DEFAULT_PID_EV_KP             = 0.05    # EV PID: setpoint=0W surplus, output=amps
DEFAULT_PID_EV_KI             = 0.008
DEFAULT_PID_EV_KD             = 0.02
DEFAULT_PRICE_THRESHOLD_CHEAP = 0.10    # EUR/kWh

# Storage key for PID state persistence
STORAGE_KEY_PID_STATE         = f"{DOMAIN}_pid_state_v1"
STORAGE_KEY_NILM_THRESHOLD    = f"{DOMAIN}_nilm_threshold_v1"
STORAGE_KEY_NILM_REVIEW       = f"{DOMAIN}_nilm_review_v1"      # review skip history
STORAGE_KEY_NILM_ADAPTIVE     = f"{DOMAIN}_nilm_adaptive_v1"    # adaptive thresholds per device_type

# ── Compat aliases from v1.3 / v1.4 ──────────────────────────────────────────
CONF_EV_PRICE_THRESHOLD       = CONF_EV_CHEAP_THRESHOLD
CONF_ENABLE_PHASE_BALANCER    = CONF_ENABLE_PHASE_BALANCING
CONF_PHASE_IMBALANCE_LIMIT    = "phase_balance_threshold_a"
DEFAULT_EV_PRICE_THRESHOLD    = DEFAULT_EV_CHEAP_THRESHOLD
DEFAULT_PHASE_IMBALANCE_LIMIT = DEFAULT_PHASE_BALANCE_THRESHOLD
CONF_DYNAMIC_LOADING          = "dynamic_loading"
CONF_DYNAMIC_LOAD_THRESHOLD   = "dynamic_load_price_threshold"
CONF_DYNAMIC_LOAD_MIN_SOC     = "dynamic_load_min_soc"
DEFAULT_DYNAMIC_LOAD_THRESHOLD= 0.10
CONF_PHASE_BALANCE            = "phase_balance_enabled"
CONF_PHASE_BALANCE_THRESHOLD  = "phase_balance_threshold_a"
CONF_P1_ENABLED               = "p1_enabled"
CONF_P1_HOST                  = "p1_host"
CONF_P1_PORT                  = "p1_port"

# ── DSMR / meter-bron keuze ───────────────────────────────────────────────────
CONF_DSMR_SOURCE              = "dsmr_source"
DSMR_SOURCE_INTEGRATION       = "integration"   # Gebruik HA DSMR / HomeWizard integratie
DSMR_SOURCE_HA_ENTITIES       = "ha_entities"   # Selecteer HA-sensoren handmatig
DSMR_SOURCE_DIRECT            = "direct"        # Directe P1 TCP/serieel verbinding
DSMR_SOURCE_ESPHOME           = "esphome"       # DIY ESPHome 1kHz NILM-meter
DSMR_SOURCE_LABELS = {
    DSMR_SOURCE_INTEGRATION: "🔌 DSMR / HomeWizard integratie (aanbevolen)",
    DSMR_SOURCE_HA_ENTITIES:  "⚡ Handmatig HA-sensoren selecteren",
    DSMR_SOURCE_DIRECT:       "📡 Directe P1-verbinding (IP/serieel)",
    DSMR_SOURCE_ESPHOME:      "🔬 DIY ESPHome 1kHz NILM-meter (geavanceerd)",
}

# Config keys voor ESPHome-bron
CONF_ESPHOME_POWER_L1         = "esphome_power_l1"
CONF_ESPHOME_POWER_L2         = "esphome_power_l2"
CONF_ESPHOME_POWER_L3         = "esphome_power_l3"
CONF_ESPHOME_POWER_FACTOR_L1  = "esphome_power_factor_l1"
CONF_ESPHOME_POWER_FACTOR_L2  = "esphome_power_factor_l2"
CONF_ESPHOME_POWER_FACTOR_L3  = "esphome_power_factor_l3"
CONF_ESPHOME_INRUSH_L1        = "esphome_inrush_l1"
CONF_ESPHOME_INRUSH_L2        = "esphome_inrush_l2"
CONF_ESPHOME_INRUSH_L3        = "esphome_inrush_l3"
CONF_ESPHOME_RISE_TIME_L1     = "esphome_rise_time_l1"
CONF_ESPHOME_RISE_TIME_L2     = "esphome_rise_time_l2"
CONF_ESPHOME_RISE_TIME_L3     = "esphome_rise_time_l3"
# v4.4.1 — reactief vermogen (VAR) en THD per fase
# Optioneel: alleen ESP32-firmware met FFT/Q-berekening levert deze waarden.
# Afwezig = None → geen effect op NILM classificatie (graceful degradation).
CONF_ESPHOME_REACTIVE_L1      = "esphome_reactive_l1"
CONF_ESPHOME_REACTIVE_L2      = "esphome_reactive_l2"
CONF_ESPHOME_REACTIVE_L3      = "esphome_reactive_l3"
CONF_ESPHOME_THD_L1           = "esphome_thd_l1"
CONF_ESPHOME_THD_L2           = "esphome_thd_l2"
CONF_ESPHOME_THD_L3           = "esphome_thd_l3"
# Bekende DSMR/P1 HA-integratie platforms voor auto-detectie
DSMR_HA_PLATFORMS = [
    "dsmr",           # officiële DSMR integratie
    "homewizard",     # HomeWizard Energy
    "slimmelezer",    # SLIMMELEZER+
    "p1_monitor",     # P1 Monitor
    "iungo",          # Iungo
    "youless",        # YouLess
    "ecodevices",     # ecoDevices
]
CONF_P1_SERIAL_PORT           = "p1_serial_port"
DEFAULT_P1_PORT               = 8088
DSMR_TELEGRAM_INTERVAL        = 10
CONF_COST_TRACKING            = "cost_tracking_enabled"

GRID_SENSOR_KEYWORDS     = ["grid","net","import","export","p1","dsmr","mains","totaal","verbruik","levering","main","house","home"]
PHASE_SENSOR_KEYWORDS_L1 = ["l1","fase_1","phase_1","phase1","stroom_l1","current_l1"]
PHASE_SENSOR_KEYWORDS_L2 = ["l2","fase_2","phase_2","phase2","stroom_l2","current_l2"]
PHASE_SENSOR_KEYWORDS_L3 = ["l3","fase_3","phase_3","phase3","stroom_l3","current_l3"]

# Auto-detect exclusion keywords — entity_ids containing these are EXCLUDED
# from grid/phase pools to avoid false-positive matches on PV/battery/EV sensors
GRID_EXCLUDE_KEYWORDS    = ["solar","pv","zon","inverter","omvormer","battery","batterij","accu",
                             "batt","storage","ev","charger","laadpaal","yield","feedin","feed_in",
                             "clipping","forecast","predicted","estimated",
                             "cloudems"]          # exclude own CloudEMS derived sensors
PHASE_EXCLUDE_KEYWORDS   = ["solar","pv","zon","inverter","omvormer","battery","batterij","accu",
                             "batt","storage","ev","charger","laadpaal",
                             # PV inverter brand prefixes — their AC-side current/power sensors
                             # measure inverter output, NOT the grid meter phase current
                             "on_grid","goodwe","growatt","solis","solaredge","fronius",
                             "enphase","huawei_solar","deye","sunsynk","sofar","sma_",
                             "output_current","output_power","ac_current","ac_power",
                             "cloudems"]          # exclude own CloudEMS derived sensors
CURRENT_EXCLUDE_KEYWORDS = ["solar","pv","zon","inverter","battery","batt","storage","ev","charger",
                             # Same brand exclusions — inverter AC-side current ≠ grid CT current
                             "on_grid","goodwe","growatt","solis","solaredge","fronius",
                             "enphase","huawei_solar","deye","sunsynk","sofar","sma_",
                             "output_current","ac_current",
                             "cloudems"]          # exclude own CloudEMS derived sensors
# Voltage-specific exclusions: extends PHASE_EXCLUDE_KEYWORDS with PV inverter
# voltage sensor patterns. "on_grid" is used by GoodWe/Solis for the AC-side
# voltage measured by the inverter — not a standalone grid meter.
# "cloudems" is already inherited via PHASE_EXCLUDE_KEYWORDS above.
VOLTAGE_EXCLUDE_KEYWORDS = PHASE_EXCLUDE_KEYWORDS + [
    "output_voltage",   # Generic inverter AC output label
    "ac_voltage",       # Generic inverter AC output label
]

# ── v1.9.0 — CO2, battery scheduler, cost forecast, boiler learning ───────────
CONF_CO2_COUNTRY              = "co2_country"       # ISO2 country for CO2 API
CONF_BATTERY_CAPACITY_KWH     = "battery_capacity_kwh"
CONF_BATTERY_CHARGE_ENTITY    = "battery_charge_entity"
CONF_BATTERY_DISCHARGE_ENTITY = "battery_discharge_entity"
CONF_BATTERY_SOC_ENTITY       = "battery_soc_entity"
CONF_BATTERY_MAX_CHARGE_W     = "battery_max_charge_w"
CONF_BATTERY_MAX_DISCHARGE_W  = "battery_max_discharge_w"
CONF_BATTERY_SCHEDULER_ENABLED= "battery_scheduler_enabled"

DEFAULT_BATTERY_CAPACITY_KWH  = 10.0
DEFAULT_BATTERY_MAX_CHARGE_W  = 3000.0
DEFAULT_CO2_COUNTRY           = "NL"

# Storage keys
STORAGE_KEY_BATTERY_SCHEDULE  = f"{DOMAIN}_battery_schedule_v1"
STORAGE_KEY_BOILER_PATTERN    = f"{DOMAIN}_boiler_pattern_v1"
STORAGE_KEY_COST_HISTORY      = f"{DOMAIN}_cost_history_v1"

# CO2 API
CO2_SIGNAL_URL  = "https://api.co2signal.com/v1/latest"   # needs free token
ELECTRICITY_MAP_FREE_URL = "https://api.electricitymap.org/v3/carbon-intensity/latest"
# Fallback: static European averages g CO2/kWh (source: EEA 2023)
CO2_COUNTRY_DEFAULTS = {
    "NL": 283, "DE": 385, "BE": 167, "FR": 56, "AT": 135,
    "DK": 180, "NO": 28, "SE": 41, "FI": 126, "CH": 31,
    "GB": 239, "ES": 206, "IT": 372, "PL": 750,
}

# ── v1.10.0 — Grid congestion, battery degradation, heat demand ───────────────
CONF_CONGESTION_ENABLED        = "congestion_enabled"
CONF_CONGESTION_THRESHOLD_W    = "congestion_threshold_w"
CONF_CONGESTION_PRICE_THR      = "congestion_price_threshold"
CONF_BATTERY_CHEMISTRY         = "battery_chemistry"
CONF_OUTSIDE_TEMP_ENTITY       = "outside_temp_entity"
CONF_BATTERY_DEGRADATION_ENABLED = "battery_degradation_enabled"

# v1.20: Goedkope uren schakelaar planner
CONF_CHEAP_SWITCHES              = "cheap_switches"   # list of dicts

DEFAULT_CONGESTION_THRESHOLD_W = 5000
DEFAULT_OUTSIDE_TEMP_ENTITY    = ""

BATTERY_CHEMISTRIES = ["LFP", "NMC", "NCA", "LTO"]

# ── v1.13.0 — Standalone gas sensor ──────────────────────────────────────────
CONF_GAS_SENSOR = "gas_sensor"

# ── v1.13.0 — Multi-battery support (like multi-inverter) ────────────────────
CONF_BATTERY_CONFIGS           = "battery_configs"
CONF_ENABLE_MULTI_BATTERY      = "enable_multi_battery"
CONF_BATTERY_COUNT             = "battery_count"

# ── v1.13.0 — Energy source comparison (electricity vs gas) ──────────────────
CONF_GAS_PRICE_SENSOR          = "gas_price_sensor"       # HA sensor reporting €/m³
CONF_GAS_PRICE_FIXED           = "gas_price_fixed"        # fixed €/m³ fallback
CONF_HAS_GAS_HEATING           = "has_gas_heating"        # CV-ketel voor warm water: null=niet geconfigureerd, "yes"=ja, "no"=nee
CONF_BOILER_EFFICIENCY         = "boiler_efficiency"       # electric boiler COP (default 0.95)
CONF_HEAT_PUMP_COP             = "heat_pump_cop"           # heat pump COP (default 3.5)
GAS_KWH_PER_M3                 = 9.769                    # calorific value (Groningen gas)
GAS_BOILER_EFFICIENCY          = 0.90                     # conventional gas boiler efficiency
DEFAULT_BOILER_EFFICIENCY      = 0.95                     # electric boiler/immersion heater
DEFAULT_HEAT_PUMP_COP          = 3.5
DEFAULT_GAS_PRICE_EUR_M3       = 1.25                     # fallback if no sensor configured

# ── v1.13.0 — Electricity price display: tax + BTW + supplier markup ─────────
CONF_PRICE_INCLUDE_TAX     = "price_include_tax"     # bool: add energy tax
CONF_PRICE_INCLUDE_BTW     = "price_include_btw"     # bool: add VAT
CONF_SUPPLIER_MARKUP       = "supplier_markup"        # float: €/kWh markup
CONF_SELECTED_SUPPLIER     = "selected_supplier"      # str: supplier key

# ── Net metering (saldering) afbouw per land ──────────────────────────────────
# Format: { country: [ (jaar, pct), ... ] }  — pct = fractie van export die
# verrekend mag worden met import (1.0 = 100% saldering, 0.0 = afgeschaft).
# Sortering: oplopend op jaar. Laatste rij geldt voor alle latere jaren.
#
# NL: Wet Elektriciteitsproductie Kleinschalig (WEK), Staatsblad 2023
#     2023-2024: 100%, 2025: 64%, 2026: 36%, 2027+: 0%
# BE: Geen wettelijke saldering — feedin-compensatie via nettarief (≈0%)
# DE: Einspeisevergütung (EEG) — geen saldering, vaste terugleverprijs
# FR: Geen saldering — contrat de vente (surplus verkoop)
# Overige landen: standaard 0% (geen saldering — puur feedin)
NET_METERING_PHASES: dict[str, list[tuple[int, float]]] = {
    "NL": [
        (2023, 1.00),
        (2024, 1.00),
        (2025, 0.64),
        (2026, 0.36),
        (2027, 0.00),
    ],
    "BE": [(2020, 0.00)],   # geen saldering
    "DE": [(2020, 0.00)],   # EEG: vaste terugleverprijs, geen saldering
    "FR": [(2020, 0.00)],
    "AT": [(2020, 0.00)],
    "CH": [(2020, 0.00)],
    "DK": [(2020, 0.00)],
    "NO": [(2020, 0.00)],
    "SE": [(2020, 0.00)],
    "FI": [(2020, 0.00)],
}


def get_net_metering_pct(country: str, year: int | None = None) -> float:
    """
    Geeft het actieve salderings-percentage (0.0–1.0) voor een land en jaar.

    Voorbeeld:
        get_net_metering_pct("NL", 2026)  →  0.36
        get_net_metering_pct("NL", 2027)  →  0.00
        get_net_metering_pct("DE", 2026)  →  0.00

    Onbekend land → 0.0 (veilige standaard: geen saldering aannemen).
    """
    import datetime as _dt
    if year is None:
        year = _dt.date.today().year
    phases = NET_METERING_PHASES.get(str(country).upper(), [])
    if not phases:
        return 0.0
    # Laatste fase waarvan jaar <= gevraagd jaar
    pct = phases[0][1]
    for phase_year, phase_pct in phases:
        if year >= phase_year:
            pct = phase_pct
    return pct


# Energy tax (energiebelasting) per country in €/kWh (2025 values, excl. BTW)
ENERGY_TAX_PER_COUNTRY = {
    "NL": 0.09157,   # €/kWh excl. BTW (2026: 0,1108 incl. BTW ÷ 1,21 — eerste schijf t/m 2900 kWh)
    "BE": 0.0445,
    "DE": 0.02050,   # reduced since 2023
    "FR": 0.0225,
    "AT": 0.0150,
    "CH": 0.0,       # no federal energy tax
    "DK": 0.0836,
    "NO": 0.1591,
    "SE": 0.0431,
    "FI": 0.02372,
}

# VAT rates per country
VAT_RATE_PER_COUNTRY = {
    "NL": 0.21,
    "BE": 0.21,
    "DE": 0.19,
    "FR": 0.20,
    "AT": 0.20,
    "CH": 0.081,
    "DK": 0.25,
    "NO": 0.25,
    "SE": 0.25,
    "FI": 0.255,
}

# Supplier markups per country: { "supplier_key": ("Label", markup_eur_per_kwh) }
SUPPLIER_MARKUPS = {
    "NL": {
        "none":       ("Geen leverancier markup", 0.0),
        "vattenfall": ("Vattenfall", 0.0215),
        "eneco":      ("Eneco", 0.0189),
        "essent":     ("Essent", 0.0201),
        "greenchoice":("Greenchoice", 0.0175),
        "budget":     ("Budget Energie", 0.0165),
        "vandebron":  ("Vandebron", 0.0182),
        "tibber":     ("Tibber", 0.0149),
        "zonneplan":  ("Zonneplan", 0.0169),
        "custom":     ("Aangepaste markup (zie opslag)", 0.0),
    },
    "BE": {
        "none":       ("Geen leverancier markup", 0.0),
        "engie":      ("Engie", 0.0220),
        "luminus":    ("Luminus", 0.0210),
        "fluvius":    ("Fluvius (netbeheerder)", 0.0180),
        "octa":       ("Octa+", 0.0195),
        "bolt":       ("Bolt", 0.0168),
        "custom":     ("Aangepaste markup", 0.0),
    },
    "DE": {
        "none":       ("Kein Aufschlag", 0.0),
        "eon":        ("E.ON", 0.0250),
        "rwe":        ("RWE / innogy", 0.0230),
        "ewe":        ("EWE", 0.0220),
        "vattenfall": ("Vattenfall DE", 0.0215),
        "tibber":     ("Tibber", 0.0160),
        "ostrom":     ("Ostrom", 0.0145),
        "awattar":    ("aWATTar (EPEX direkt)", 0.0050),
        "custom":     ("Eigener Aufschlag", 0.0),
    },
    "FR": {
        "none":       ("Pas de majoration", 0.0),
        "edf":        ("EDF / EDF OA", 0.0200),
        "total":      ("TotalEnergies", 0.0210),
        "engie_fr":   ("Engie France", 0.0195),
        "octopus_fr": ("Octopus Energy FR", 0.0155),
        "custom":     ("Majoration personnalisée", 0.0),
    },
    "AT": {
        "none":       ("Kein Aufschlag", 0.0),
        "wien_energie": ("Wien Energie", 0.0210),
        "verbund":    ("Verbund", 0.0190),
        "oekostrom":  ("Oekostrom", 0.0175),
        "tibber":     ("Tibber AT", 0.0155),
        "custom":     ("Eigener Aufschlag", 0.0),
    },
    "NO": {
        "none":       ("Ingen leverandørtillegg", 0.0),
        "tibber":     ("Tibber NO", 0.0099),
        "fjordkraft": ("Fjordkraft", 0.0149),
        "fortum":     ("Fortum NO", 0.0139),
        "hafslund":   ("Hafslund Strøm", 0.0129),
        "custom":     ("Egendefinert tillegg", 0.0),
    },
    "DK": {
        "none":       ("Ingen leverandørtillæg", 0.0),
        "tibber":     ("Tibber DK", 0.0099),
        "andel":      ("Andel Energi", 0.0135),
        "norlys":     ("Norlys", 0.0140),
        "ewii":       ("EWII Energi", 0.0128),
        "custom":     ("Brugerdefineret tillæg", 0.0),
    },
    "SE": {
        "none":       ("Inget leverantörstillägg", 0.0),
        "tibber":     ("Tibber SE", 0.0099),
        "vattenfall": ("Vattenfall SE", 0.0165),
        "fortum":     ("Fortum SE", 0.0149),
        "bixia":      ("Bixia", 0.0138),
        "custom":     ("Anpassat tillägg", 0.0),
    },
    "FI": {
        "none":       ("Ei toimittajalisää", 0.0),
        "tibber":     ("Tibber FI", 0.0099),
        "helen":      ("Helen", 0.0155),
        "fortum":     ("Fortum FI", 0.0145),
        "vattenfall": ("Vattenfall FI", 0.0150),
        "custom":     ("Oma lisä", 0.0),
    },
    "CH": {
        "none":       ("Kein Aufschlag", 0.0),
        "ewz":        ("EWZ Zürich", 0.0200),
        "bkw":        ("BKW", 0.0190),
        "alpiq":      ("Alpiq", 0.0185),
        "custom":     ("Eigener Aufschlag", 0.0),
    },
    "default": {
        "none":       ("No supplier markup", 0.0),
        "custom":     ("Custom markup", 0.0),
    },
}

# ── Nord Pool landen (gebruiken Nord Pool API ipv ENTSO-E) ────────────────────
NORDPOOL_COUNTRIES = {"NO", "DK", "SE", "FI"}

# ── Capaciteitstarief configuratie per land ────────────────────────────────────
CAPACITY_TARIFF_CONFIG = {
    "NL": {"enabled": True,  "threshold_kw": 2.5,  "cost_per_kw_month": 4.37, "currency": "EUR",
           "note": "Liander/Enexis: capaciteitstarief boven 2,5 kW piek per kwartier"},
    "BE": {"enabled": True,  "threshold_kw": 2.5,  "cost_per_kw_month": 4.00, "currency": "EUR",
           "note": "Fluvius: capaciteitstarief actief sinds jan 2023"},
    "DE": {"enabled": False, "threshold_kw": None, "cost_per_kw_month": None, "currency": "EUR",
           "note": "Kein Kapazitätstarif für Haushalte"},
    "FR": {"enabled": False, "threshold_kw": None, "cost_per_kw_month": None, "currency": "EUR",
           "note": "Pas de tarif de capacité pour les particuliers"},
    "NO": {"enabled": True,  "threshold_kw": 5.0,  "cost_per_kw_month": 5.50, "currency": "NOK",
           "note": "Effekttariff (Steg): gemiddelde top-3 uur per dag per maand"},
    "DK": {"enabled": True,  "threshold_kw": 4.0,  "cost_per_kw_month": 38.0, "currency": "DKK",
           "note": "Netselskab effekttarif (Radius, N1, etc.)"},
    "SE": {"enabled": True,  "threshold_kw": None, "cost_per_kw_month": None, "currency": "SEK",
           "note": "Kapacitetsavgift (varierar per elnätsbolag)"},
    "AT": {"enabled": False, "threshold_kw": None, "cost_per_kw_month": None, "currency": "EUR", "note": ""},
    "CH": {"enabled": False, "threshold_kw": None, "cost_per_kw_month": None, "currency": "CHF", "note": ""},
    "FI": {"enabled": False, "threshold_kw": None, "cost_per_kw_month": None, "currency": "EUR", "note": ""},
}

# ── v1.13.1 additions ────────────────────────────────────────────────────────
CONF_PRICE_ALERT_HIGH      = "price_alert_high_eur_kwh"   # float: alert when EPEX > this
DEFAULT_PRICE_ALERT_HIGH   = 0.30                          # €/kWh

CONF_INVERTER_RATED_POWER  = "inverter_rated_power_w"      # per-inverter rated capacity (W)

CONF_NILM_MIN_CONFIDENCE_UI= "nilm_confidence_ui"          # alias for wizard display

# ── v1.15.x additions ────────────────────────────────────────────────────────

# Contract type: dynamic (EPEX day-ahead) or fixed (user-entered price)
CONF_CONTRACT_TYPE          = "contract_type"
CONTRACT_TYPE_DYNAMIC       = "dynamic"
CONTRACT_TYPE_FIXED         = "fixed"
DEFAULT_CONTRACT_TYPE       = CONTRACT_TYPE_DYNAMIC
CONF_FIXED_IMPORT_PRICE     = "fixed_import_price"     # €/kWh, used when contract=fixed
CONF_FIXED_EXPORT_PRICE     = "fixed_export_price"     # €/kWh, feed-in tariff when fixed

# DSMR5 per-phase export sensors (separate from import on meters with bidirectional phases)
CONF_POWER_L1_EXPORT        = "power_sensor_l1_export"
CONF_POWER_L2_EXPORT        = "power_sensor_l2_export"
CONF_POWER_L3_EXPORT        = "power_sensor_l3_export"

# NILM config hash (for soft reset on sensor config change)
CONF_NILM_CONFIG_HASH       = "nilm_config_hash"

# Heat pump COP learning
CONF_HEAT_PUMP_ENTITY       = "heat_pump_power_entity"    # entity measuring HP electric power
CONF_HEAT_PUMP_THERMAL_ENTITY = "heat_pump_thermal_entity"  # optional: measured thermal output

# ── v1.25.9: Lamp Circulation (intelligente lampenbeveiliging) ────────────────
CONF_LAMP_CIRCULATION_ENABLED       = "lamp_circulation_enabled"
CONF_LAMP_CIRCULATION_ENTITIES      = "lamp_circulation_light_entities"
CONF_LAMP_CIRCULATION_STEP_S        = "lamp_circulation_step_seconds"
CONF_LAMP_CIRCULATION_MIN_CONF      = "lamp_circulation_min_confidence"
CONF_LAMP_CIRCULATION_NIGHT_START   = "lamp_circulation_night_start_h"
CONF_LAMP_CIRCULATION_NIGHT_END     = "lamp_circulation_night_end_h"

DEFAULT_LAMP_CIRCULATION_STEP_S     = 300    # 5 minuten per lamp
DEFAULT_LAMP_CIRCULATION_MIN_CONF   = 0.55
DEFAULT_LAMP_CIRCULATION_NIGHT_START = 22
DEFAULT_LAMP_CIRCULATION_NIGHT_END   = 7

ICON_LAMP_CIRCULATION = "mdi:lightbulb-group"

# ── v2.0.1: Tab zichtbaarheid ────────────────────────────────────────────────
# Lijst van dashboard-paths die als subview (verborgen tabblad) worden ingesteld.
# Subviews zijn bereikbaar via URL maar verschijnen niet in de navigatiebalk.
CONF_HIDDEN_TABS = "hidden_tabs"

# Alle beschikbare CloudEMS tabs: (path, label)
CLOUDEMS_TABS = [
    ("cloudems-overzicht",    "🏠 Overzicht"),
    ("cloudems-huis",         "🧠 Huis Intelligentie"),
    ("cloudems-prijzen",      "💶 Prijzen & Kosten"),
    ("cloudems-zon",          "☀️ Solar & PV"),
    ("cloudems-lampen",       "💡 Lampen"),
    ("cloudems-nilm",         "📡 NILM Apparaten"),
    ("cloudems-nilm-beheer",  "🏷️ NILM Beheer"),
    ("cloudems-fasen",        "⚡ Fasen"),
    ("cloudems-batterij",     "🔋 Batterij"),
    ("cloudems-boiler",       "🚿 Warm Water"),
    ("cloudems-mobiliteit",   "🚗 EV & Mobiliteit"),
    ("cloudems-micromobiliteit", "🚲 E-bike & Scooter"),
    ("cloudems-zwembad",      "🏊 Zwembad"),
    ("cloudems-klimaat",      "🌡️ Klimaatbeheer"),
    ("cloudems-klimaat-epex", "📈 Klimaat EPEX"),
    ("cloudems-meldingen",    "🔔 Meldingen"),
    ("cloudems-intelligence", "🤖 Zelflerend"),
    ("cloudems-diagnose",     "🩺 Diagnose"),
]

# Tabs die standaard verborgen zijn (optionele features zonder basisconfig)
CLOUDEMS_TABS_HIDDEN_DEFAULT = [
    "cloudems-zwembad",
    "cloudems-micromobiliteit",
    "cloudems-nilm-beheer",
    "cloudems-diagnose",
    "cloudems-intelligence",
    "cloudems-fasen",
    "cloudems-klimaat-epex",
]


# v2.2.2: NILM pruning configuratie
CONF_NILM_PRUNE_THRESHOLD   = "nilm_prune_threshold"   # int: coordinator-cycli voor pruning
DEFAULT_NILM_PRUNE_THRESHOLD = 60                        # 60 cycli ≈ ~10 minuten
CONF_NILM_PRUNE_MIN_DAYS    = "nilm_prune_min_days"     # int: minimale inactiviteit in dagen (0=uit)
DEFAULT_NILM_PRUNE_MIN_DAYS  = 1                         # 1 dag minimum — beschermt tegen herstart-pruning


# v2.4.19: E-mail / SMTP instellingen voor PDF-rapporten
CONF_MAIL_ENABLED    = "mail_enabled"
CONF_MAIL_HOST       = "mail_host"
CONF_MAIL_PORT       = "mail_port"
CONF_MAIL_USERNAME   = "mail_username"
CONF_MAIL_PASSWORD   = "mail_password"
CONF_MAIL_FROM       = "mail_from"
CONF_MAIL_TO         = "mail_to"
CONF_MAIL_USE_TLS    = "mail_use_tls"
CONF_MAIL_MONTHLY    = "mail_monthly_report"    # stuur maandelijks PDF-rapport
CONF_MAIL_WEEKLY     = "mail_weekly_report"     # stuur wekelijks samenvatting
DEFAULT_MAIL_PORT    = 587
DEFAULT_MAIL_USE_TLS = True

# v2.6: Multi-zone klimaatbeheer
CONF_CLIMATE_ENABLED         = "climate_mgr_enabled"
CONF_CLIMATE_ZONES           = "climate_zones"           # list[dict] — per zone
CONF_CLIMATE_ZONES_ENABLED   = "climate_zones_enabled"   # list[str] — area_ids die actief zijn
CONF_CV_BOILER_ENTITY        = "cv_boiler_entity"        # switch.* of climate.*
CONF_CV_MIN_ZONES            = "cv_min_zones_calling"    # int — min zones voor ketel aan
CONF_CV_DEADBAND_K           = "cv_deadband_k"           # float — °C onder setpoint = warmtevraag
CONF_CV_MIN_ON_MIN           = "cv_min_on_minutes"
CONF_CV_MIN_OFF_MIN          = "cv_min_off_minutes"
CONF_CV_SUMMER_CUTOFF_C      = "cv_summer_cutoff_c"      # buiten > X°C → zomermodus

# Zone-veld keys (binnen elk zone-dict)
ZONE_NAME                    = "zone_name"
ZONE_CLIMATE_ENTITIES        = "zone_climate_entities"   # list[str]
ZONE_WINDOW_SENSOR           = "zone_window_sensor"
ZONE_PRESENCE_SENSOR         = "zone_presence_sensor"
ZONE_TEMP_COMFORT            = "zone_temp_comfort"
ZONE_TEMP_ECO                = "zone_temp_eco"
ZONE_TEMP_SLEEP              = "zone_temp_sleep"
ZONE_TEMP_AWAY               = "zone_temp_away"
ZONE_TEMP_BOOST              = "zone_temp_boost"
ZONE_HEATING_TYPE            = "zone_heating_type"       # "cv" | "airco" | "both"

DEFAULT_CV_MIN_ZONES         = 1
DEFAULT_CV_DEADBAND_K        = 0.5
DEFAULT_CV_MIN_ON_MIN        = 5
DEFAULT_CV_MIN_OFF_MIN       = 3
DEFAULT_CV_SUMMER_CUTOFF_C   = 18.0

# Preset-temperaturen (defaults)
DEFAULT_TEMP_COMFORT         = 20.0
DEFAULT_TEMP_ECO             = 17.5
DEFAULT_TEMP_SLEEP           = 15.5
DEFAULT_TEMP_AWAY            = 14.0
DEFAULT_TEMP_BOOST           = 22.0

# ── Warm Water / Boiler Cascade (v2.0) ────────────────────────────────────────
CONF_BOILER_GROUPS           = "boiler_groups"         # list[dict] — cascade groepen
CONF_BOILER_GROUPS_ENABLED   = "boiler_groups_enabled" # bool — module aan/uit

# Cascade modi (gespiegeld aan boiler_controller.py)
BOILER_MODE_SEQUENTIAL       = "sequential"
BOILER_MODE_PARALLEL         = "parallel"
BOILER_MODE_PRIORITY         = "priority"
BOILER_MODE_AUTO             = "auto"

BOILER_MODE_LABELS = {
    BOILER_MODE_AUTO:       "🔄 Auto (aanbevolen)",
    BOILER_MODE_SEQUENTIAL: "🔁 Sequentieel — één boiler per keer",
    BOILER_MODE_PARALLEL:   "⚡ Parallel — alles tegelijk (PV-absorptie)",
    BOILER_MODE_PRIORITY:   "🎯 Prioriteit — op volgorde van belang",
}

# Entiteitstypen die als boiler-actuator gebruikt kunnen worden
BOILER_ENTITY_TYPE_SWITCH        = "switch"
BOILER_ENTITY_TYPE_CLIMATE       = "climate"
BOILER_ENTITY_TYPE_WATER_HEATER  = "water_heater"
BOILER_ENTITY_TYPE_NUMBER        = "number"

DEFAULT_BOILER_SETPOINT_C    = 60.0
DEFAULT_BOILER_MIN_TEMP_C    = 40.0
DEFAULT_BOILER_COMFORT_C     = 50.0
DEFAULT_BOILER_POWER_W       = 2500.0
DEFAULT_BOILER_MIN_ON_MIN    = 10
DEFAULT_BOILER_MIN_OFF_MIN   = 5

# ── Rolluiken ─────────────────────────────────────────────────────────────────
CONF_SHUTTER_COUNT             = "shutter_count"
CONF_SHUTTER_CONFIGS           = "shutter_configs"
CONF_SHUTTER_GROUPS            = "shutter_groups"

DEFAULT_SHUTTER_COUNT          = 0
DEFAULT_SHUTTER_OVERRIDE_H     = 2        # uur handmatige override

SHUTTER_ACTION_OPEN            = "open"
SHUTTER_ACTION_CLOSE           = "close"
SHUTTER_ACTION_POSITION        = "position"
SHUTTER_ACTION_STOP            = "stop"
SHUTTER_ACTION_IDLE            = "idle"

SHUTTER_REASON_MANUAL          = "manual_override"
SHUTTER_REASON_THERMAL         = "thermal_comfort"
SHUTTER_REASON_SOLAR_GAIN      = "solar_gain"
SHUTTER_REASON_OVERHEAT        = "overheat_prevention"
SHUTTER_REASON_SCHEDULE        = "schedule"
SHUTTER_REASON_PV              = "pv_surplus"

SHUTTER_ORIENTATION_NORTH      = "north"
SHUTTER_ORIENTATION_EAST       = "east"
SHUTTER_ORIENTATION_SOUTH      = "south"
SHUTTER_ORIENTATION_WEST       = "west"
SHUTTER_ORIENTATION_UNKNOWN    = "unknown"

SHUTTER_STORAGE_KEY            = "cloudems_shutters_v1"
SHUTTER_REASON_NIGHT           = "night_schedule"
SHUTTER_REASON_MORNING         = "morning_blocked"
SHUTTER_REASON_PID             = "pid_position"
SHUTTER_REASON_WIND            = "wind_protection"
SHUTTER_REASON_PV_SURPLUS      = "pv_surplus"
DEFAULT_SHUTTER_NIGHT_CLOSE    = "20:00"
DEFAULT_SHUTTER_MORNING_OPEN   = "08:00"
DEFAULT_SHUTTER_SETPOINT       = 20.0
CONF_SHUTTER_ENABLED           = "shutter_enabled"
DEFAULT_SHUTTER_ENABLED        = False

# Rolluik — nieuwe features v4.3.7
SHUTTER_REASON_STORM           = "storm_protection"
SHUTTER_REASON_AWAY            = "absence_mode"
SHUTTER_REASON_SUNRISE         = "sunrise_tracking"
SHUTTER_REASON_SEASON          = "seasonal_profile"

DEFAULT_SHUTTER_SUNRISE_OFFSET  = 15       # minuten na zonsopgang
DEFAULT_SHUTTER_AWAY_POSITION   = 50       # % bij afwezig (zomer: gedeeltelijk dicht)
DEFAULT_SHUTTER_SUMMER_OFFSET   = 1.0      # setpoint °C lager in zomer (koeler houden)
DEFAULT_SHUTTER_WINTER_OFFSET   = 0.5      # setpoint °C hoger in winter (warmer houden)
SHUTTER_SUMMER_MONTHS           = (4, 5, 6, 7, 8, 9)   # april t/m september
CONF_SHUTTER_TEMP_SENSOR       = "shutter_temp_sensor"   # optionele kamertemperatuursensor per rolluik

# ── Externe providers (v4.5.0) ────────────────────────────────────────────────
CONF_PROVIDERS                   = "external_providers"
CONF_PROVIDER_TYPE               = "provider_type"
CONF_PROVIDER_LABEL              = "provider_label"
CONF_PROVIDER_CREDENTIALS        = "provider_credentials"

# ── Prijsleverancier koppeling (v4.5.2) ───────────────────────────────────────
# Slaat op welke energieleverancier als directe prijsbron wordt gebruikt.
# Waarden: "none" | "frank_energie" | "tibber" | "octopus" | "zonneplan" |
#          "eneco" | "vattenfall" | "essent" | "anwb_energie" | "nieuwestroom"
CONF_PRICE_PROVIDER              = "price_provider"
DEFAULT_PRICE_PROVIDER           = "none"

# Providers die EPEX-marktprijzen gebruiken (geen eigen leveranciersprijs)
EPEX_BASED_PROVIDERS = {"none", "frank_energie"}

# Leverancier → benodigde credentials-velden
# none/frank_energie (no auth needed for market prices) → geen credentials
PRICE_PROVIDER_CREDENTIALS: dict = {
    "none":         [],
    "frank_energie": [],          # marktprijzen = gratis, geen login
    "tibber":       ["access_token"],
    "octopus":      ["api_key"],
    "zonneplan":    ["access_token"],
    "eneco":        ["username", "password"],
    "vattenfall":   ["username", "password"],
    "essent":       ["username", "password"],
    "anwb_energie": ["username", "password"],
    "nieuwestroom": ["username", "password"],
}

PRICE_PROVIDER_LABELS: dict = {
    "none":          "⚡ EPEX dag-vooruit (automatisch, gratis)",
    "frank_energie": "⚡ Frank Energie (realtime EPEX, gratis)",
    "tibber":        "💡 Tibber (persoonlijk tarief, token vereist)",
    "octopus":       "🐙 Octopus Energy (API-sleutel vereist)",
    "zonneplan":     "☀️ Zonneplan (API-token vereist)",
    "eneco":         "🔵 Eneco (login vereist)",
    "vattenfall":    "🌊 Vattenfall (login vereist)",
    "essent":        "🔴 Essent (login vereist)",
    "anwb_energie":  "🚗 ANWB Energie (login vereist)",
    "nieuwestroom":  "🌿 NieuweStroom (login vereist)",
}

# Categorie constanten
PROVIDER_CATEGORY_INVERTER       = "inverter"
PROVIDER_CATEGORY_EV             = "ev"
PROVIDER_CATEGORY_APPLIANCE      = "appliance"
PROVIDER_CATEGORY_ENERGY         = "energy"
PROVIDER_CATEGORY_HEATING        = "heating"

# Bekende provider IDs
PROVIDER_SOLAREDGE     = "solaredge"
PROVIDER_ENPHASE       = "enphase"
PROVIDER_SMA           = "sma"
PROVIDER_FRONIUS       = "fronius"
PROVIDER_HUAWEI_SOLAR  = "huawei_solar"
PROVIDER_GOODWE        = "goodwe"
PROVIDER_GROWATT       = "growatt"
PROVIDER_SOLIS         = "solis"
PROVIDER_DEYE          = "deye"
PROVIDER_SUNSYNK       = "sunsynk"
PROVIDER_TESLA         = "tesla"
PROVIDER_BMW           = "bmw"
PROVIDER_MINI          = "mini"
PROVIDER_VW            = "volkswagen"
PROVIDER_AUDI          = "audi"
PROVIDER_SKODA         = "skoda"
PROVIDER_SEAT          = "seat"
PROVIDER_HYUNDAI       = "hyundai"
PROVIDER_KIA           = "kia"
PROVIDER_RENAULT       = "renault"
PROVIDER_NISSAN        = "nissan"
PROVIDER_POLESTAR      = "polestar"
PROVIDER_FORD          = "ford"
PROVIDER_MERCEDES      = "mercedes"
PROVIDER_VOLVO         = "volvo"
PROVIDER_RIVIAN        = "rivian"
PROVIDER_HOMECONNECT   = "homeconnect"
PROVIDER_ARISTON       = "ariston"
PROVIDER_MIELE         = "miele"
PROVIDER_ELECTROLUX    = "electrolux"
PROVIDER_AEG           = "aeg"
PROVIDER_CANDY         = "candy"
PROVIDER_HAIER         = "haier"
PROVIDER_TIBBER        = "tibber"
PROVIDER_OCTOPUS       = "octopus"
PROVIDER_FRANK_ENERGIE = "frank_energie"
PROVIDER_ENECO         = "eneco"
PROVIDER_VATTENFALL    = "vattenfall"
PROVIDER_ESSENT        = "essent"
PROVIDER_ANWB_ENERGIE  = "anwb_energie"
PROVIDER_NIEUWESTROOM  = "nieuwestroom"

CONF_TELEMETRY_ENABLED = "telemetry_enabled"

# ── Climate EPEX Compensatie ──────────────────────────────────────────────────
CONF_CLIMATE_EPEX_ENABLED  = "climate_epex_enabled"
CONF_CLIMATE_EPEX_DEVICES  = "climate_epex_devices"   # list[dict]
