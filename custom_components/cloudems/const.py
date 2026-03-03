"""Constants for CloudEMS integration."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

DOMAIN = "cloudems"
VERSION = "1.3.0"
ATTRIBUTION = "Data provided by CloudEMS"
MANUFACTURER = "CloudEMS"
NAME = "CloudEMS Energy Manager"
WEBSITE = "https://cloudems.eu"
BUY_ME_COFFEE_URL = "https://buymeacoffee.com/cloudems"
CLOUDEMS_WEBSITE = "https://cloudems.eu"

# ── Sensor / entity attributes ────────────────────────────────────────────────
ATTR_PROBABILITY    = "probability"
ATTR_DEVICE_TYPE    = "device_type"
ATTR_CONFIRMED      = "confirmed"
ATTR_MANUFACTURER   = "CloudEMS"
ATTR_MODEL          = f"CloudEMS v{VERSION}"

# ── Icons ─────────────────────────────────────────────────────────────────────
ICON_NILM    = "mdi:home-analytics"
ICON_LIMITER = "mdi:current-ac"
ICON_PRICE   = "mdi:currency-eur"

# ── Core config keys ──────────────────────────────────────────────────────────
CONF_GRID_SENSOR            = "grid_sensor"
CONF_PHASE_SENSORS          = "phase_sensors"
CONF_SOLAR_SENSOR           = "solar_sensor"
CONF_BATTERY_SENSOR         = "battery_sensor"
CONF_EV_CHARGER_ENTITY      = "ev_charger_entity"
CONF_ENERGY_PRICES_COUNTRY  = "energy_prices_country"
CONF_EPEX_COUNTRY           = CONF_ENERGY_PRICES_COUNTRY  # alias
CONF_CLOUD_API_KEY          = "cloud_api_key"
CONF_NILM_MODE              = "nilm_mode"
CONF_MAX_CURRENT_PER_PHASE  = "max_current_per_phase"
CONF_ENABLE_SOLAR_DIMMER    = "enable_solar_dimmer"
CONF_NEGATIVE_PRICE_THRESHOLD = "negative_price_threshold"
CONF_GRID_PHASES            = "grid_phases"

# ── Phase config ──────────────────────────────────────────────────────────────
CONF_PHASE_COUNT            = "phase_count"
CONF_PHASE_PRESET           = "phase_preset"
CONF_MAX_CURRENT_L1         = "max_current_l1"
CONF_MAX_CURRENT_L2         = "max_current_l2"
CONF_MAX_CURRENT_L3         = "max_current_l3"
CONF_MAX_CURRENT_IMPORT     = "max_current_import"
CONF_MAX_CURRENT_EXPORT     = "max_current_export"

CONF_SOLAR_INVERTER_SWITCH  = "solar_inverter_switch"
CONF_EV_CHARGER_SWITCH      = "ev_charger_switch"
CONF_BATTERY_SWITCH         = "battery_switch"

# ── Phase presets ─────────────────────────────────────────────────────────────
PHASE_PRESETS: dict[str, dict] = {
    "1x16A": {"count": 1, "L1": 16,  "L2": None, "L3": None},
    "1x20A": {"count": 1, "L1": 20,  "L2": None, "L3": None},
    "1x25A": {"count": 1, "L1": 25,  "L2": None, "L3": None},
    "1x35A": {"count": 1, "L1": 35,  "L2": None, "L3": None},
    "3x16A": {"count": 3, "L1": 16,  "L2": 16,   "L3": 16},
    "3x20A": {"count": 3, "L1": 20,  "L2": 20,   "L3": 20},
    "3x25A": {"count": 3, "L1": 25,  "L2": 25,   "L3": 25},
    "3x32A": {"count": 3, "L1": 32,  "L2": 32,   "L3": 32},
    "custom": {"count": None, "L1": None, "L2": None, "L3": None},
}

PHASE_PRESET_LABELS: dict[str, str] = {
    "1x16A":  "1 fase — 16 A",
    "1x20A":  "1 fase — 20 A",
    "1x25A":  "1 fase — 25 A",
    "1x35A":  "1 fase — 35 A",
    "3x16A":  "3 fasen — 3×16 A",
    "3x20A":  "3 fasen — 3×20 A",
    "3x25A":  "3 fasen — 3×25 A",
    "3x32A":  "3 fasen — 3×32 A",
    "custom": "Aangepast (handmatig invoeren)",
}

PHASES = ["L1", "L2", "L3"]
PHASE_L1, PHASE_L2, PHASE_L3 = "L1", "L2", "L3"
ALL_PHASES = [PHASE_L1, PHASE_L2, PHASE_L3]

# ── P1 / DSMR ─────────────────────────────────────────────────────────────────
CONF_P1_INTEGRATION         = "p1_integration"
CONF_P1_SENSOR              = "p1_sensor"
P1_INTEGRATION_OPTIONS = {
    "dsmr":       "DSMR / Slimme Meter (HA integratie)",
    "homewizard": "HomeWizard Energy",
    "p1monitor":  "P1 Monitor",
    "manual":     "Handmatig sensoren kiezen",
}
# Substrings used to guess grid/P1 entities in auto-detection
P1_ENTITY_KEYWORDS = [
    "dsmr", "p1", "slimme_meter", "homewizard", "power_delivered",
    "electricity_delivered", "power_usage", "net_consumption",
]

# ── Dynamic EV charging ───────────────────────────────────────────────────────
CONF_DYNAMIC_EV_CHARGING     = "dynamic_ev_charging"
CONF_EV_CHEAP_THRESHOLD      = "ev_cheap_price_threshold"   # EUR/kWh
CONF_EV_ALWAYS_ON_CURRENT    = "ev_always_on_current"       # A floor when expensive
CONF_EV_SOLAR_SURPLUS_PRIO   = "ev_solar_surplus_priority"  # bool
CONF_EV_MIN_SOC_THRESHOLD    = "ev_min_soc_threshold"       # % — always charge below
CONF_EV_SMART_SCHEDULE       = "ev_smart_schedule"          # bool

DEFAULT_EV_CHEAP_THRESHOLD   = 0.10   # EUR/kWh
DEFAULT_EV_ALWAYS_ON_CURRENT = 6      # A
DEFAULT_EV_MIN_SOC_THRESHOLD = 20     # %

# ── Phase balancing ───────────────────────────────────────────────────────────
CONF_ENABLE_PHASE_BALANCING    = "enable_phase_balancing"
DEFAULT_PHASE_BALANCE_THRESHOLD = 4.0                       # A

# ── Cost / tax ────────────────────────────────────────────────────────────────
CONF_ENERGY_TAX              = "energy_tax"        # EUR/kWh surcharge
DEFAULT_ENERGY_TAX_NL        = 0.1228              # 2024 NL tarief incl. ODE

# ── Diagnostics ───────────────────────────────────────────────────────────────
CONF_ENABLE_DIAGNOSTICS      = "enable_diagnostics"
DIAG_REPORT_EVENT            = f"{DOMAIN}_diagnostic_report"

# ── EPEX countries & area codes ───────────────────────────────────────────────
EPEX_COUNTRIES = {
    "NL": "Netherlands", "BE": "Belgium", "DE": "Germany",
    "FR": "France",      "AT": "Austria", "CH": "Switzerland",
    "DK": "Denmark",     "NO": "Norway",  "SE": "Sweden", "FI": "Finland",
}
EPEX_AREAS = {
    "NL": "10YNL----------L",   "BE": "10YBE----------2",
    "DE": "10Y1001A1001A82H",   "FR": "10YFR-RTE------C",
    "AT": "10YAT-APG------L",   "CH": "10YCH-SWISSGRID--D",
    "DK": "10YDK-1--------W",   "NO": "10YNO-0--------C",
    "SE": "10YSE-1--------K",   "FI": "10YFI-1--------U",
}
EPEX_UPDATE_INTERVAL         = 3600
DEFAULT_NEGATIVE_PRICE_THRESHOLD = 0.0
DEFAULT_EPEX_COUNTRY         = "NL"

# ── NILM ──────────────────────────────────────────────────────────────────────
NILM_MODE_DATABASE           = "database"
NILM_MODE_LOCAL_AI           = "local_ai"
NILM_MODE_CLOUD_AI           = "cloud_ai"
NILM_MIN_CONFIDENCE          = 0.65
NILM_HIGH_CONFIDENCE         = 0.85
NILM_LEARNING_WINDOW         = 30

# ── Device types ──────────────────────────────────────────────────────────────
DEVICE_TYPE_REFRIGERATOR     = "refrigerator"
DEVICE_TYPE_WASHING_MACHINE  = "washing_machine"
DEVICE_TYPE_DRYER            = "dryer"
DEVICE_TYPE_DISHWASHER       = "dishwasher"
DEVICE_TYPE_OVEN             = "oven"
DEVICE_TYPE_MICROWAVE        = "microwave"
DEVICE_TYPE_KETTLE           = "kettle"
DEVICE_TYPE_TV               = "television"
DEVICE_TYPE_COMPUTER         = "computer"
DEVICE_TYPE_HEAT_PUMP        = "heat_pump"
DEVICE_TYPE_BOILER           = "boiler"
DEVICE_TYPE_EV_CHARGER       = "ev_charger"
DEVICE_TYPE_SOLAR_INVERTER   = "solar_inverter"
DEVICE_TYPE_LIGHT            = "light"
DEVICE_TYPE_UNKNOWN          = "unknown"

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
}

# ── Timing ────────────────────────────────────────────────────────────────────
DEFAULT_MAX_CURRENT          = 25
DEFAULT_MAX_CURRENT_IMPORT   = 25
DEFAULT_MAX_CURRENT_EXPORT   = 25
LIMITER_UPDATE_INTERVAL      = 10
MIN_EV_CURRENT               = 6
MAX_EV_CURRENT               = 32
UPDATE_INTERVAL_FAST         = 10
UPDATE_INTERVAL_SLOW         = 300

# ── Cloud API ─────────────────────────────────────────────────────────────────
CLOUD_API_BASE               = "https://api.cloudems.eu/v1"
CLOUD_NILM_ENDPOINT          = "/nilm/classify"
CLOUD_PRICES_ENDPOINT        = "/prices/epex"

# ── Storage keys ──────────────────────────────────────────────────────────────
STORAGE_KEY_NILM_DEVICES     = f"{DOMAIN}_nilm_devices"
STORAGE_KEY_LEARNED_PROFILES = f"{DOMAIN}_learned_profiles"
STORAGE_KEY_ENERGY_STATS     = f"{DOMAIN}_energy_stats"
STORAGE_KEY_DIAGNOSTICS      = f"{DOMAIN}_diagnostics"

# ── Platforms ─────────────────────────────────────────────────────────────────
PLATFORM_SENSOR  = "sensor"
PLATFORM_SWITCH  = "switch"
PLATFORM_NUMBER  = "number"
PLATFORM_BUTTON  = "button"

# ── Aliases for config_flow compatibility ──────────────────────────────────────
CONF_EV_PRICE_THRESHOLD      = CONF_EV_CHEAP_THRESHOLD
CONF_ENABLE_PHASE_BALANCER   = CONF_ENABLE_PHASE_BALANCING
CONF_PHASE_IMBALANCE_LIMIT   = CONF_PHASE_BALANCE_THRESHOLD
DEFAULT_EV_PRICE_THRESHOLD   = DEFAULT_EV_CHEAP_THRESHOLD
DEFAULT_PHASE_IMBALANCE_LIMIT = DEFAULT_PHASE_BALANCE_THRESHOLD

# ── Dynamic loader (EPEX-based EV charging) ───────────────────────────────────
CONF_DYNAMIC_LOADING         = "dynamic_loading"
CONF_DYNAMIC_LOAD_THRESHOLD  = "dynamic_load_price_threshold"   # EUR/kWh
CONF_DYNAMIC_LOAD_MIN_SOC    = "dynamic_load_min_soc"            # % battery before allowing
DEFAULT_DYNAMIC_LOAD_THRESHOLD = 0.10                            # charge when price < 10 ct

# ── Phase balancer ────────────────────────────────────────────────────────────
CONF_PHASE_BALANCE           = "phase_balance_enabled"
CONF_PHASE_BALANCE_THRESHOLD = "phase_balance_threshold_a"       # Ampere imbalance trigger
DEFAULT_PHASE_BALANCE_THRESHOLD = 4.0

# ── P1 smart meter ────────────────────────────────────────────────────────────
CONF_P1_ENABLED              = "p1_enabled"
CONF_P1_HOST                 = "p1_host"
CONF_P1_PORT                 = "p1_port"
CONF_P1_SERIAL_PORT          = "p1_serial_port"
DEFAULT_P1_PORT              = 8088
DSMR_TELEGRAM_INTERVAL       = 10   # seconds

# ── Diagnostics ───────────────────────────────────────────────────────────────
STORAGE_KEY_DIAGNOSTICS      = f"{DOMAIN}_diagnostics"

# ── Cost tracking ─────────────────────────────────────────────────────────────
CONF_COST_TRACKING           = "cost_tracking_enabled"
STORAGE_KEY_ENERGY_COST      = f"{DOMAIN}_energy_cost"

# ── v1.3: Multi-inverter & Solar Learner ──────────────────────────────────────
CONF_INVERTER_CONFIGS        = "inverter_configs"
CONF_INVERTER_CONTROL_ENTITY = "inverter_control_entity"
CONF_INVERTER_PRIORITY       = "inverter_priority"
CONF_INVERTER_MIN_POWER_PCT  = "inverter_min_power_pct"
CONF_INVERTER_LABEL          = "inverter_label"
CONF_ENABLE_MULTI_INVERTER   = "enable_multi_inverter"
STORAGE_KEY_SOLAR_PROFILES   = "cloudems_solar_profiles_v2"

# ── Auto sensor detection scoring ─────────────────────────────────────────────
# Keywords that suggest a sensor is a grid power meter
GRID_SENSOR_KEYWORDS = [
    "grid", "net", "import", "export", "p1", "dsmr", "mains",
    "totaal", "verbruik", "levering", "main", "house", "home",
]
PHASE_SENSOR_KEYWORDS_L1 = ["l1", "fase_1", "phase_1", "phase1"]
PHASE_SENSOR_KEYWORDS_L2 = ["l2", "fase_2", "phase_2", "phase2"]
PHASE_SENSOR_KEYWORDS_L3 = ["l3", "fase_3", "phase_3", "phase3"]
