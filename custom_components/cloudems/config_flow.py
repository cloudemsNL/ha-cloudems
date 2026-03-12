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
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY, CONF_ENERGY_PRICES_COUNTRY,
    CONF_CLOUD_API_KEY, CONF_MAX_CURRENT_PER_PHASE, CONF_ENABLE_SOLAR_DIMMER,
    CONF_NEGATIVE_PRICE_THRESHOLD,
    CONF_PHASE_COUNT, CONF_PHASE_PRESET,
    CONF_MAX_CURRENT_L1, CONF_MAX_CURRENT_L2, CONF_MAX_CURRENT_L3,
    CONF_DYNAMIC_LOADING, CONF_DYNAMIC_LOAD_THRESHOLD,
    CONF_PHASE_BALANCE, CONF_PHASE_BALANCE_THRESHOLD,
    CONF_P1_ENABLED, CONF_P1_HOST, CONF_P1_PORT,
    CONF_DSMR_SOURCE, DSMR_SOURCE_INTEGRATION, DSMR_SOURCE_HA_ENTITIES,
    DSMR_SOURCE_DIRECT, DSMR_SOURCE_ESPHOME, DSMR_SOURCE_LABELS, DSMR_HA_PLATFORMS,
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
    DEFAULT_PEAK_SHAVING_LIMIT_W,
    DEFAULT_MAX_CURRENT, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    DEFAULT_DYNAMIC_LOAD_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD,
    DEFAULT_P1_PORT, EPEX_COUNTRIES,
    PHASE_PRESETS, PHASE_PRESET_LABELS,
    GRID_SENSOR_KEYWORDS,
    PHASE_SENSOR_KEYWORDS_L1, PHASE_SENSOR_KEYWORDS_L2, PHASE_SENSOR_KEYWORDS_L3,
    GRID_EXCLUDE_KEYWORDS, PHASE_EXCLUDE_KEYWORDS, CURRENT_EXCLUDE_KEYWORDS, VOLTAGE_EXCLUDE_KEYWORDS,
    CONF_WIZARD_MODE, WIZARD_MODE_BASIC, WIZARD_MODE_ADVANCED,
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
    opts = [selector.SelectOptionDict(value=str(i), label=str(i)) for i in range(10)]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _country_selector():
    opts = [selector.SelectOptionDict(value=k, label=f"{v} ({k})") for k, v in EPEX_COUNTRIES.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="dropdown"))

def _ai_provider_selector():
    opts = [selector.SelectOptionDict(value=k, label=v) for k, v in AI_PROVIDER_LABELS.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _wizard_mode_selector():
    opts = [
        selector.SelectOptionDict(value=WIZARD_MODE_BASIC,    label="🟢 Basic — quick setup, essential sensors only"),
        selector.SelectOptionDict(value=WIZARD_MODE_ADVANCED, label="🔧 Advanced — full control over all sensors & features"),
    ]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _dsmr_source_selector():
    opts = [selector.SelectOptionDict(value=k, label=v) for k, v in DSMR_SOURCE_LABELS.items()]
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, mode="list"))

def _ent(domains=None):
    cfg = selector.EntitySelectorConfig(domain=domains or "sensor")
    return selector.EntitySelector(cfg)


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
    CloudEMS v1.5.0 wizard.

    Basic mode  (7 steps):
      1. welcome        — country + wizard mode
      2. grid_connection — phase preset (→ phase_custom if custom)
      3. grid_sensors   — net/import/export sensor + mains voltage
      4. solar_ev       — solar / battery / EV
      5. features       — enable features (→ peak_config if peak shaving)
      6. ai_config      — AI provider + key (→ ollama_config if Ollama)
      7. → finish

    Advanced adds:
      After grid_sensors → phase_sensors (current / voltage / power per phase)
      After solar_ev     → inverter_count (→ inverter_detail loop)
      After ai_config    → advanced (P1 toggle → p1_config)
    """

    VERSION = 5

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._suggestions: dict = {}
        self._inv_count = 0
        self._inv_step  = 0
        self._bat_count = 0
        self._bat_step  = 0

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

        # Bouw bevestigingsformulier op basis van wat gevonden is
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

        # Bouw samenvatting voor description
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
            count = int(user_input.get(CONF_PHASE_COUNT, 3))
            l1    = float(user_input.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))
            self._config.update({
                CONF_PHASE_COUNT:           count,
                CONF_MAX_CURRENT_L1:        l1,
                CONF_MAX_CURRENT_PER_PHASE: l1,
                CONF_MAX_CURRENT_L2: float(user_input.get(CONF_MAX_CURRENT_L2, l1)) if count == 3 else None,
                CONF_MAX_CURRENT_L3: float(user_input.get(CONF_MAX_CURRENT_L3, l1)) if count == 3 else None,
            })
            return await self.async_step_dsmr_source()
        return self.async_show_form(
            step_id="phase_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_COUNT, default=3): vol.In({1: "1 phase", 3: "3 phases"}),
                vol.Required(CONF_MAX_CURRENT_L1, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L2, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L3, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
            }),
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
                return  # Geen platform-sensors — suggestions blijven als ze zijn

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
            return await self.async_step_phase_sensors() if self._advanced() else await self.async_step_solar_ev()

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
            # Valideer UOM van fase-power sensoren: alleen W of kW toegestaan
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
                return await self.async_step_solar_ev()

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
            return await self.async_step_inverter_detail() if self._inv_count > 0 else await self.async_step_battery_count()
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
            return await self.async_step_battery_count()
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
                vol.Optional("inv_control", description={"suggested_value": existing.get("control_entity") or None}): _ent(["switch","number"]),
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
            # Sla opt-in keuzes op
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
            if self._advanced() and not getattr(self, "_came_from_advanced_battery", False):
                return await self.async_step_battery_count()
            return await self.async_step_features()

        # Geen providers → stap overslaan
        if not unconfigured:
            if self._advanced():
                return await self.async_step_battery_count()
            return await self.async_step_features()

        # Bouw schema op basis van wat er gedetecteerd is
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
            return await self.async_step_features()
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
                vol.Optional("bat_soc_sensor",   description={"suggested_value": existing_bat.get("soc_sensor")}):   _ent(),
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
            self._shutter_step = 0
            self._overkiz_prefill = overkiz_covers
            if self._shutter_count == 0 and overkiz_covers:
                self._shutter_count = len(overkiz_covers)
                self._config[CONF_SHUTTER_COUNT] = self._shutter_count
            if self._shutter_count > 0:
                return await self.async_step_shutter_detail()
            return await self.async_step_features()

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
            })
            self._shutter_step += 1
            if self._shutter_step < self._shutter_count:
                return await self.async_step_shutter_detail()
            return await self.async_step_features()

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
            return await self.async_step_ai_config()
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
            # Geen credentials nodig → provider meteen registreren
            self._register_price_provider(chosen, {})
            # EPEX-gebaseerde providers → toon prijzen-stap (belasting, leverancier markup)
            if chosen in EPEX_BASED_PROVIDERS:
                return await self.async_step_prices()
            # Echte leverancier → prijs komt rechtstreeks van API, sla prijzen-stap over
            return await self.async_step_ai_config()

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
            return await self.async_step_ai_config()

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
        """Detecteer P1-bron automatisch; sla toggle-stap over."""
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_p1_config() if user_input.get(CONF_P1_ENABLED) else await self.async_step_mail()
        # Direct naar slimme P1-detectie, geen losse toggle nodig
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
            # Als we vanuit de wizard DSMR-bron "direct" kwamen, terug naar grid_sensors
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
            # Geen auto-bron → optioneel IP tonen (leeg = overslaan)
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
        """Stap 1 van klimaatwizard: inschakelen + CV-ketel entiteit opgeven."""
        if user_input is not None:
            self._config.update(user_input)
            if user_input.get(CONF_CLIMATE_ENABLED) or self._config.get(CONF_CLIMATE_ZONES_ENABLED):
                return await self.async_step_climate_boiler()
            return await self.async_step_boiler_groups()

        ex = self._config
        return self.async_show_form(
            step_id="climate",
            data_schema=vol.Schema({
                vol.Optional(CONF_CLIMATE_ENABLED, default=ex.get(CONF_CLIMATE_ENABLED, False)): bool,
            }),
            description_placeholders={
                "info": (
                    "CloudEMS ontdekt automatisch alle verwarmings- en "
                    "koelapparaten per ruimte via de HA area-indeling. "
                    "Je hoeft alleen de CV-ketel en eventuele extra instellingen op te geven."
                )
            },
        )

    async def async_step_climate_boiler(self, user_input=None):
        """Stap 2: CV-ketel entiteit + minimale zones."""
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
        )

    async def async_step_climate_zones(self, user_input=None):
        """Stap 3: Zone-ontdekking — kies per kamer of een virtual climate device gewenst is."""
        errors: dict = {}

        # Discovery uitvoeren
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
            if suggested and "climate_zones" not in self._config:
                self._config["climate_zones"] = suggested
            return await self.async_step_boiler_groups()

        # Sla suggesties op in config
        if suggested and "climate_zones" not in self._config:
            self._config["climate_zones"] = suggested

        # Bouw zone-opties voor multi-select
        zone_options = [
            selector.SelectOptionDict(
                value=z["zone_name"],
                label=f"{z['zone_display_name']} "
                      f"({'CV' if z['zone_heating_type']=='cv' else 'Airco' if z['zone_heating_type']=='airco' else 'CV+Airco'})",
            )
            for z in suggested
        ]

        # Standaard alle zones aan
        default_zones = [z["zone_name"] for z in suggested]

        if not zone_options:
            description = (
                "*Geen fysieke climate-entiteiten gevonden. "
                "Wijs climate-apparaten toe aan een HA-ruimte (Instellingen → Gebieden & zones) "
                "voor automatische zone-indeling.*"
            )
            return self.async_show_form(
                step_id="climate_zones",
                data_schema=vol.Schema({}),
                description_placeholders={"discovery": description},
                errors=errors,
            )

        return self.async_show_form(
            step_id="climate_zones",
            data_schema=vol.Schema({
                vol.Optional(CONF_CLIMATE_ZONES_ENABLED, default=default_zones):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=zone_options,
                        multiple=True,
                        mode="list",
                    )),
            }),
            description_placeholders={
                "discovery": "Selecteer de kamers waarvoor CloudEMS een virtueel klimaatapparaat "
                             "aanmaakt. Alleen kamers met een fysieke thermostaat of TRV worden getoond.",
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
            # Altijd activeren — enabled-toggle verwijderd uit wizard (Fix 22)
            self._config[CONF_BOILER_GROUPS_ENABLED] = True
            self._boiler_group_index = 0
            self._boiler_groups_tmp  = list(existing_groups)
            self._boiler_unit_count  = int(user_input.get("unit_count", 1) or 1)
            self._boiler_group_name  = user_input.get("group_name", "Tapwater")
            self._boiler_group_mode  = user_input.get("group_mode", BOILER_MODE_AUTO)
            self._boiler_unit_index  = 0
            self._boiler_units_tmp   = []
            return await self.async_step_boiler_unit()

        return self.async_show_form(
            step_id="boiler_groups",
            description_placeholders={
                "info": (
                    "Koppel warmwaterboilers, elektrische geysers of accumulatortanks. "
                    "CloudEMS stuurt ze automatisch op basis van PV-surplus, "
                    "goedkope EPEX-uren en netcongestie.\n\n"
                    "Elke groep kan sequentieel (1 per keer) of parallel (allemaal tegelijk) "
                    "werken. Je koppelt gewoon bestaande HA-entiteiten — "
                    "switch, climate of water_heater."
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

    async def async_step_boiler_unit(self, user_input=None):
        """Wizard-stap: configureer één boiler-unit in de huidige groep."""
        idx   = getattr(self, "_boiler_unit_index", 0)
        total = int(getattr(self, "_boiler_unit_count", 1))

        if user_input is not None:
            control_mode = user_input.get("control_mode", "switch")
            unit = {
                "entity_id":      user_input["entity_id"],
                "label":          user_input.get("label", f"Boiler {idx + 1}"),
                "temp_sensor":    user_input.get("temp_sensor", ""),
                "energy_sensor":  user_input.get("energy_sensor", ""),
                "power_w":        DEFAULT_BOILER_POWER_W,  # wordt geleerd via energy_sensor
                "setpoint_c":     float(user_input.get("setpoint_c", DEFAULT_BOILER_SETPOINT_C)),
                "min_temp_c":     float(user_input.get("min_temp_c", DEFAULT_BOILER_MIN_TEMP_C)),
                "comfort_floor_c":float(user_input.get("comfort_floor_c", DEFAULT_BOILER_COMFORT_C)),
                "priority":       int(user_input.get("priority", idx)),
                "min_on_minutes": int(user_input.get("min_on_minutes", DEFAULT_BOILER_MIN_ON_MIN)),
                "min_off_minutes":int(user_input.get("min_off_minutes", DEFAULT_BOILER_MIN_OFF_MIN)),
                "control_mode":   control_mode,
                "preset_on":      user_input.get("preset_on",  "boost"),
                "preset_off":     user_input.get("preset_off", "green"),
                "dimmer_on_pct":  float(user_input.get("dimmer_on_pct",  100)),
                "dimmer_off_pct": float(user_input.get("dimmer_off_pct", 0)),
                # Stel modus vast op basis van entiteitstype
                "modes": ["cheap_hours", "negative_price", "pv_surplus", "export_reduce"],
            }
            getattr(self, "_boiler_units_tmp", []).append(unit)
            self._boiler_unit_index = idx + 1

            if self._boiler_unit_index < total:
                return await self.async_step_boiler_unit()

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

        # Detecteer switch/climate/water_heater entiteiten als suggestie
        all_states   = self.hass.states.async_all()
        boiler_hints = sorted(set(
            s.entity_id for s in all_states
            if s.domain in ("switch", "climate", "water_heater", "number")
            and any(kw in s.entity_id.lower()
                    for kw in ("boiler", "boil", "water", "heater", "geyser",
                               "warmwater", "hw", "dhw", "cv"))
        ))

        return self.async_show_form(
            step_id="boiler_unit",
            description_placeholders={
                "idx":   str(idx + 1),
                "total": str(total),
                "group": getattr(self, "_boiler_group_name", "?"),
            },
            data_schema=vol.Schema({
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
                vol.Optional("setpoint_c",
                             default=DEFAULT_BOILER_SETPOINT_C): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=80, step=1,
                                                  mode="slider", unit_of_measurement="°C")
                ),
                vol.Optional("min_temp_c",
                             default=DEFAULT_BOILER_MIN_TEMP_C): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=60, step=1,
                                                  mode="slider", unit_of_measurement="°C")
                ),
                vol.Optional("comfort_floor_c",
                             default=DEFAULT_BOILER_COMFORT_C): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=35, max=70, step=1,
                                                  mode="slider", unit_of_measurement="°C")
                ),
                vol.Optional("control_mode", default="switch"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "switch",   "label": "🔌 Aan/uit schakelaar (switch / input_boolean)"},
                            {"value": "setpoint", "label": "🌡️ Setpoint instellen (climate / water_heater) — aanbevolen"},
                            {"value": "preset",   "label": "🎛️ Preset modus (bijv. Ariston green/boost)"},
                            {"value": "dimmer",   "label": "💡 Dimmer / vermogensregeling (RBDimmer, number)"},
                        ],
                        mode="list",
                    )
                ),
                vol.Optional("preset_on",  default="boost"): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("preset_off", default="green"): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("dimmer_on_pct", default=100): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
                vol.Optional("dimmer_off_pct", default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
            }),
        )


    async def async_step_mail(self, user_input=None):
        errors: dict = {}
        if user_input is not None:
            enabled = user_input.get(CONF_MAIL_ENABLED, False)
            if enabled:
                # Valideer minimale verplichte velden
                if not user_input.get(CONF_MAIL_HOST, "").strip():
                    errors[CONF_MAIL_HOST] = "mail_host_required"
                if not user_input.get(CONF_MAIL_TO, "").strip():
                    errors[CONF_MAIL_TO] = "mail_to_required"
                if not errors:
                    # Doe een snelle verbindingstest
                    try:
                        import smtplib, ssl as _ssl
                        host = user_input[CONF_MAIL_HOST].strip()
                        port = user_input.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)
                        use_tls = user_input.get(CONF_MAIL_USE_TLS, True)
                        ctx = _ssl.create_default_context() if use_tls else None
                        with smtplib.SMTP(host, port, timeout=5) as smtp:
                            if use_tls:
                                smtp.starttls(context=ctx)
                            user = user_input.get(CONF_MAIL_USERNAME, "").strip()
                            pwd  = user_input.get(CONF_MAIL_PASSWORD, "").strip()
                            if user and pwd:
                                smtp.login(user, pwd)
                    except Exception as _smtp_err:
                        errors["base"] = "mail_connection_failed"
                        _LOGGER.warning("CloudEMS mail test mislukt: %s", _smtp_err)
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

    async def async_step_diagnostics(self, user_input=None):
        """Optionele stap: GitHub log reporting instellen."""
        if user_input is not None:
            self._config.update(user_input)
            return self._create()

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
        # v4.2.1: altijd "CloudEMS" — fasepresets in de titel zijn verwarrend
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
        self._existing_cheap_cfgs: list[dict] = []

    def _data(self) -> dict:
        # OptionsFlowWithConfigEntry exposes self.config_entry; keep _entry too.
        entry = getattr(self, "config_entry", self._entry)
        return {**entry.data, **entry.options, **self._opts}

    def _entry_options(self) -> dict:
        """Return current entry options — works with both base classes."""
        entry = getattr(self, "config_entry", self._entry)
        return dict(entry.options)

    def _save(self, extra: dict) -> object:
        """Merge extra into options and save; triggers auto-reload via base class.

        Strategie: options = volledig gecombineerde config (data + bestaande options
        + nieuw extra). Zo gaan nooit waarden verloren bij de eerste options-save
        of bij stappen die slechts een subset van velden tonen.
        """
        entry = getattr(self, "config_entry", self._entry)
        # Bouw altijd op vanuit data + options zodat ook keys die nog nooit in
        # options stonden (alleen in entry.data) correct worden meegenomen.
        merged = {**entry.data, **entry.options, **extra}

        # ── Afgeleide velden ───────────────────────────────────────────────────
        # CONF_MAX_CURRENT_PER_PHASE = L1 (gebruikt door piekbeperking + solar learner)
        if CONF_MAX_CURRENT_L1 in merged:
            merged[CONF_MAX_CURRENT_PER_PHASE] = float(merged[CONF_MAX_CURRENT_L1])

        # phase_count altijd als int opslaan
        if CONF_PHASE_COUNT in merged:
            merged[CONF_PHASE_COUNT] = int(merged[CONF_PHASE_COUNT])

        return self.async_create_entry(title="", data=merged)

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            section = user_input.get("section", "sensors")
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("section", default="sensors"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="sensors",        label="🔌 Grid Sensors"),
                        selector.SelectOptionDict(value="phase_sensors",  label="⚡ Phase Sensors"),
                        selector.SelectOptionDict(value="solar_ev_opts",  label="🔌 EV Laadpaal"),
                        selector.SelectOptionDict(value="gas_opts",        label="🔥 Gas & Warmte"),
                        selector.SelectOptionDict(value="inverters_opts", label="🔆 PV Omvormers & Zonnebegrenzing"),
                        selector.SelectOptionDict(value="batteries_opts", label="🔋 Batterijen & Providers"),
                        selector.SelectOptionDict(value="prices_opts",    label="💶 Prijzen & Belasting"),
                        selector.SelectOptionDict(value="features_opts",  label="🚀 Features"),
                        selector.SelectOptionDict(value="cheap_switches_opts", label="⚡ Goedkope Uren Schakelaars & Slimme Uitstel"),
                        selector.SelectOptionDict(value="ai_opts",        label="🤖 AI & NILM"),
                        selector.SelectOptionDict(value="nilm_devices_opts", label="🏷️ NILM Apparaten beheren"),
                        selector.SelectOptionDict(value="advanced_opts",  label="📡 P1 & Advanced"),
                        selector.SelectOptionDict(value="pool_opts",      label="🏊 Zwembad Controller"),
                        selector.SelectOptionDict(value="lamp_circ_opts", label="💡 Lampcirculatie & Beveiliging"),
                        selector.SelectOptionDict(value="climate_opts",       label="🌡️ Klimaatbeheer"),
                        selector.SelectOptionDict(value="shutter_count_opts", label="🪟 Rolluiken"),
                        selector.SelectOptionDict(value="boiler_groups_opts", label="🚿 Boiler Controller"),
                        selector.SelectOptionDict(value="mail_opts",          label="📧 E-mail rapporten"),
                    ], mode="list"))
            }),
        )

    async def async_step_sensors(self, user_input=None):
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            return self._save(user_input)

        use_sep = bool(data.get(CONF_USE_SEPARATE_IE, False))
        schema: dict = {
            vol.Optional(CONF_USE_SEPARATE_IE, default=use_sep): bool,
            vol.Optional(CONF_MAINS_VOLTAGE, default=float(data.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))):
                vol.All(vol.Coerce(float), vol.Range(min=100, max=480)),
            vol.Optional(CONF_PHASE_COUNT, default=phase_count): vol.In({1: "1 phase", 3: "3 phases"}),
            vol.Optional(CONF_MAX_CURRENT_L1, default=float(data.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))):
                vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
        }
        if not use_sep:
            schema[vol.Optional(CONF_GRID_SENSOR, description={"suggested_value": data.get(CONF_GRID_SENSOR) or None})] = _ent()
        else:
            schema[vol.Optional(CONF_IMPORT_SENSOR, description={"suggested_value": data.get(CONF_IMPORT_SENSOR) or None})] = _ent()
            schema[vol.Optional(CONF_EXPORT_SENSOR, description={"suggested_value": data.get(CONF_EXPORT_SENSOR) or None})] = _ent()
        if phase_count == 3:
            for k in (CONF_MAX_CURRENT_L2, CONF_MAX_CURRENT_L3):
                schema[vol.Optional(k, default=float(data.get(k, DEFAULT_MAX_CURRENT)))] = \
                    vol.All(vol.Coerce(float), vol.Range(min=6, max=63))
        return self.async_show_form(step_id="sensors", data_schema=vol.Schema(schema))

    async def async_step_phase_sensors(self, user_input=None):
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            return self._save(user_input)

        schema: dict = {}
        for k in [CONF_PHASE_SENSORS+"_L1", CONF_VOLTAGE_L1, CONF_POWER_L1]:
            schema[vol.Optional(k, description={"suggested_value": data.get(k) or None})] = _ent()
        if phase_count == 3:
            for k in [
                CONF_PHASE_SENSORS+"_L2", CONF_VOLTAGE_L2, CONF_POWER_L2,
                CONF_PHASE_SENSORS+"_L3", CONF_VOLTAGE_L3, CONF_POWER_L3,
            ]:
                schema[vol.Optional(k, description={"suggested_value": data.get(k) or None})] = _ent()
        # v1.15.0: DSMR5 per-phase export sensors (bidirectional meters)
        # Sommige slimme meters (DSMR5) meten teruglevering per fase apart.
        # Als geconfigureerd: netto_fase = import_fase − export_fase.
        for exp_key in ("power_sensor_l1_export", "power_sensor_l2_export", "power_sensor_l3_export"):
            schema[vol.Optional(exp_key, description={"suggested_value": data.get(exp_key) or None})] = _ent()
        return self.async_show_form(
            step_id="phase_sensors",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "diagram_url":  "/local/cloudems/diagrams/phase_sensors.svg",
                "phase_count":  str(self.config_entry.data.get("phase_count", 3)),
            },
        )

    async def async_step_solar_ev_opts(self, user_input=None):
        """☀️ PV & EV Laden — opties voor PV sensor, laadpaal en zonnebegrenzing."""
        data = self._data()
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(
            step_id="solar_ev_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_SOLAR_SENSOR, description={"suggested_value": data.get(CONF_SOLAR_SENSOR) or None}): _ent(),
                vol.Optional(CONF_BATTERY_SENSOR, description={"suggested_value": data.get(CONF_BATTERY_SENSOR) or None}): _ent(),
                vol.Optional(CONF_EV_CHARGER_ENTITY, description={"suggested_value": data.get(CONF_EV_CHARGER_ENTITY) or None}): _ent(["number","input_number"]),
                # Note: zonnebegrenzing (solar dimmer) wordt per omvormer ingesteld in de
                # 🔆 Omvormers sectie — niet meer als globale schakelaar hier.
                vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=float(data.get(CONF_NEGATIVE_PRICE_THRESHOLD, 0.0))): vol.Coerce(float),
                # Note: gas & warmtepomp instellingen → 🔥 Gas & Warmte sectie
            }),
        )

    async def async_step_gas_opts(self, user_input=None):
        """🔥 Gas & Warmte — aparte sectie voor gas/boiler/warmtepomp."""
        data = self._data()
        if user_input is not None:
            return self._save(user_input)
        # Import needed constants with safe fallback
        try:
            from .const import CONF_GAS_SENSOR, CONF_GAS_PRICE_SENSOR, CONF_GAS_PRICE_FIXED
            from .const import CONF_BOILER_EFFICIENCY, CONF_HEAT_PUMP_COP
            from .const import DEFAULT_GAS_PRICE_EUR_M3, DEFAULT_BOILER_EFFICIENCY, DEFAULT_HEAT_PUMP_COP
            from .const import CONF_HEAT_PUMP_ENTITY, CONF_HEAT_PUMP_THERMAL_ENTITY
        except ImportError:
            CONF_GAS_SENSOR = "gas_sensor"; CONF_GAS_PRICE_SENSOR = "gas_price_sensor"
            CONF_GAS_PRICE_FIXED = "gas_price_fixed"; CONF_BOILER_EFFICIENCY = "boiler_efficiency"
            CONF_HEAT_PUMP_COP = "heat_pump_cop"; DEFAULT_GAS_PRICE_EUR_M3 = 1.05
            DEFAULT_BOILER_EFFICIENCY = 0.90; DEFAULT_HEAT_PUMP_COP = 3.5
            CONF_HEAT_PUMP_ENTITY = "heat_pump_power_entity"
            CONF_HEAT_PUMP_THERMAL_ENTITY = "heat_pump_thermal_entity"
        return self.async_show_form(
            step_id="gas_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_GAS_SENSOR, description={"suggested_value": data.get(CONF_GAS_SENSOR) or None}): _ent(),
                vol.Optional(CONF_GAS_PRICE_SENSOR, description={"suggested_value": data.get(CONF_GAS_PRICE_SENSOR) or None}): _ent(),
                vol.Optional(CONF_GAS_PRICE_FIXED, default=float(data.get(CONF_GAS_PRICE_FIXED, DEFAULT_GAS_PRICE_EUR_M3))): vol.All(vol.Coerce(float), vol.Range(min=0, max=10)),
                vol.Optional(CONF_BOILER_EFFICIENCY, default=float(data.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
                vol.Optional(CONF_HEAT_PUMP_COP, default=float(data.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=8.0)),
                vol.Optional(CONF_HEAT_PUMP_ENTITY, description={"suggested_value": data.get(CONF_HEAT_PUMP_ENTITY) or None}): _ent(),
                vol.Optional(CONF_HEAT_PUMP_THERMAL_ENTITY, description={"suggested_value": data.get(CONF_HEAT_PUMP_THERMAL_ENTITY) or None}): _ent(),
            }),
        )

    async def async_step_features_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
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

    async def async_step_nilm_devices_opts(self, user_input=None):
        """🏷️ NILM Apparaten beheren — hernoem of verberg gedetecteerde apparaten.

        v1.20: This step shows a summary of currently known NILM devices and
        provides instructions for renaming/hiding via HA developer tools.
        Direct per-device editing is not possible in the HA options flow UI
        (no dynamic forms), so we guide the user to the service calls.
        """
        from homeassistant.loader import async_get_integration
        if user_input is not None:
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
            self._opts[CONF_INVERTER_CONFIGS].append({
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
                return await self.async_step_inverter_detail_opts()
            self._opts[CONF_ENABLE_MULTI_INVERTER] = len(self._opts[CONF_INVERTER_CONFIGS]) > 0
            return self._save(self._opts)

        return self.async_show_form(
            step_id="inverter_detail_opts",
            data_schema=vol.Schema({
                vol.Required("inv_sensor", default=existing.get("entity_id", vol.UNDEFINED)): _ent(),
                vol.Optional("inv_control", description={"suggested_value": existing.get("control_entity") or None}): _ent(["switch", "number"]),
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

        # Bouw leverancier-opties gefilterd op land:
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
            chosen_pp = user_input.get(CONF_PRICE_PROVIDER, current_price_provider)

            # Credentials nodig?
            needed = PRICE_PROVIDER_CREDENTIALS.get(chosen_pp, [])
            if needed and chosen_pp != current_price_provider:
                self._pending_price_provider = chosen_pp
                return await self.async_step_price_provider_creds_opts()

            # Geen credentials nodig: provider registreren
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
            self._opts[CONF_BATTERY_CONFIGS].append({
                "battery_type":     "manual",
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
            self._inv_step += 1
            if self._inv_step < self._inv_count:
                return await self.async_step_battery_type_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = len(self._opts[CONF_BATTERY_CONFIGS]) > 0
            return await self.async_step_shutter_count_opts()

        return self.async_show_form(
            step_id="battery_detail_opts",
            data_schema=vol.Schema({
                vol.Required("bat_power_sensor", default=existing.get("power_sensor", vol.UNDEFINED)): _ent(),
                vol.Optional("bat_soc_sensor", description={"suggested_value": existing.get("soc_sensor")}): _ent(),
                vol.Optional("bat_capacity_kwh", default=float(existing.get("capacity_kwh", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
                vol.Optional("bat_max_charge_w", default=float(existing.get("max_charge_w", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_max_discharge_w", default=float(existing.get("max_discharge_w", 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
                vol.Optional("bat_charge_entity", description={"suggested_value": existing.get("charge_entity") or None}): _ent(["number", "input_number"]),
                vol.Optional("bat_discharge_entity", description={"suggested_value": existing.get("discharge_entity") or None}): _ent(["number", "input_number"]),
                vol.Optional("bat_label", default=existing.get("label", f"Batterij {i}")): str,
            }),
            description_placeholders={
                "battery_num": str(i),
                "total":       str(self._inv_count),
            },
        )

    # ── Rolluiken opties ──────────────────────────────────────────────────────
    async def async_step_climate_opts(self, user_input=None):
        """Klimaatbeheer — in/uitschakelen en per kamer virtual climate device kiezen."""
        data = self._data()

        # Discovery
        try:
            from .climate_discovery import async_suggest_zones
            suggested = await async_suggest_zones(self.hass)
        except Exception:  # noqa: BLE001
            suggested = []

        if user_input is not None:
            enabled_ids = user_input.get(CONF_CLIMATE_ZONES_ENABLED, [])
            self._opts[CONF_CLIMATE_ZONES_ENABLED] = enabled_ids
            # climate_mgr_enabled wordt afgeleid: actief als er minstens 1 zone geselecteerd is
            self._opts[CONF_CLIMATE_ENABLED] = bool(enabled_ids)
            if suggested:
                self._opts["climate_zones"] = suggested
            return self._save(self._opts)

        # Bouw zone-opties voor multi-select, met gekoppelde apparaten per zone
        zone_options = []
        zone_device_info = []
        for z in suggested:
            ht = "CV" if z["zone_heating_type"] == "cv" else "Airco" if z["zone_heating_type"] == "airco" else "CV+Airco"
            zone_options.append(selector.SelectOptionDict(
                value=z["zone_name"],
                label=f"{z['zone_display_name']} ({ht})",
            ))
            devices = z.get("zone_climate_entities", [])
            if devices:
                device_list = ", ".join(f"`{e}`" for e in devices)
                zone_device_info.append(f"**{z['zone_display_name']}** ({ht}): {device_list}")

        current_enabled = list(data.get(CONF_CLIMATE_ZONES_ENABLED, [z["zone_name"] for z in suggested]))
        device_info_text = ("\n\n**Gekoppelde apparaten per ruimte:**\n" + "\n".join(f"- {l}" for l in zone_device_info)) if zone_device_info else ""

        if not zone_options:
            return self.async_show_form(
                step_id="climate_opts",
                data_schema=vol.Schema({}),
                description_placeholders={"discovery": "*Geen klimaatentiteiten gevonden in HA-ruimten. Wijs thermostaten/TRV\'s toe aan een HA-ruimte (Instellingen → Gebieden & zones).*"},
            )

        return self.async_show_form(
            step_id="climate_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_CLIMATE_ZONES_ENABLED, default=current_enabled):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=zone_options,
                        multiple=True,
                        mode="list",
                    )),
            }),
            description_placeholders={
                "discovery": (
                    "Selecteer de ruimten waarvoor CloudEMS een virtuele thermostaat aanmaakt. "
                    "Per ruimte worden alle klimaatapparaten in die HA-ruimte aangestuurd. "
                    "Vink een ruimte uit om het virtuele device te verwijderen."
                    + device_info_text
                ),
            },
        )

    async def async_step_shutter_count_opts(self, user_input=None):
        if user_input is not None:
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

    # ── Lamp Circulatie wizard stap ───────────────────────────────────────────
    async def async_step_lamp_circ_opts(self, user_input=None):
        """Wizard stap: lampcirculatie configuratie (beveiliging + energiebesparing)."""
        data = self._data()
        lc_cfg = data.get("lamp_circulation", {}) or {}
        if user_input is not None:
            new_lc = {
                "light_entities":  [],  # auto-discovery: alle light.* entiteiten
                "excluded_ids":    user_input.get("lc_excluded_ids", []),
                "enabled":         bool(user_input.get("lc_enabled", False)),
                "min_confidence":  float(user_input.get("lc_min_confidence", 0.55)),
                "night_start_h":   int(user_input.get("lc_night_start_h", 22)),
                "night_end_h":     int(user_input.get("lc_night_end_h", 7)),
                "use_sun_entity":  bool(user_input.get("lc_use_sun_entity", True)),
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

        # Bouw actie-opties (geen "Opslaan" als actie — navigatie-only)
        action_options = [selector.SelectOptionDict(value="add_group", label="➕ Nieuwe groep toevoegen")]
        for i, g in enumerate(current_groups):
            name = g.get("name", f"Groep {i+1}")
            action_options.append(selector.SelectOptionDict(value=f"edit_{i}", label=f"✏️ Bewerk: {name}"))
            action_options.append(selector.SelectOptionDict(value=f"delete_{i}", label=f"🗑️ Verwijder: {name}"))

        # Bouw groepen-overzicht tekst
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
            return await self.async_step_boiler_group_unit()

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
        groups = list(self._opts.get(CONF_BOILER_GROUPS, []))
        idx    = int(self._opts.get("_bg_edit_idx", 0))
        group  = groups[idx] if idx < len(groups) else {}
        units  = group.get("units", [])

        if user_input is not None:
            action = user_input.get("bge_action", "save")

            if action == "add_unit":
                # Sla naam+modus al op, ga dan unit toevoegen
                groups[idx]["name"] = user_input.get("bg_name", group.get("name", "Groep"))
                groups[idx]["mode"] = user_input.get("bg_mode", group.get("mode", "auto"))
                self._opts[CONF_BOILER_GROUPS] = groups
                self._opts["_bg_unit_count"] = len(units) + 1
                self._opts["_bg_unit_step"]  = len(units)
                # Tijdelijk: voeg lege placeholder toe die in boiler_group_unit wordt ingevuld
                return await self.async_step_boiler_group_unit()

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

        # Bouw unit-overzicht
        units_summary = ""
        for i, u in enumerate(units):
            units_summary += f"**{i+1}.** {u.get('label', u.get('entity_id', '?'))} — {u.get('setpoint_c', 60):.0f}°C\n"

        # Bouw actie-opties
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

    async def async_step_boiler_group_unit(self, user_input=None):
        """Configureer één boiler-unit binnen een groep."""
        groups = list(self._opts.get(CONF_BOILER_GROUPS, []))
        g_idx = int(self._opts.get("_bg_edit_idx", 0))
        u_step = int(self._opts.get("_bg_unit_step", 0))
        u_total = int(self._opts.get("_bg_unit_count", 1))
        group = groups[g_idx] if g_idx < len(groups) else {}
        units = list(group.get("units", []))

        if user_input is not None:
            units.append({
                "entity_id":       user_input.get("bu_entity", ""),
                "temp_sensor":     user_input.get("bu_temp_sensor", ""),
                "energy_sensor":   user_input.get("bu_energy_sensor", ""),
                "label":           user_input.get("bu_label", f"Boiler {u_step+1}"),
                "setpoint_c":      float(user_input.get("bu_setpoint", DEFAULT_BOILER_SETPOINT_C)),
                "surplus_setpoint_c": float(user_input.get("bu_surplus_setpoint", 75.0)),
                "power_w":         DEFAULT_BOILER_POWER_W,
                "priority":        u_step + 1,
                "control_mode":    user_input.get("bu_control_mode", "setpoint"),
                "preset_on":       user_input.get("bu_preset_on",  "boost"),
                "preset_off":      user_input.get("bu_preset_off", "green"),
                "dimmer_on_pct":   float(user_input.get("bu_dimmer_on_pct",  100)),
                "dimmer_off_pct":  float(user_input.get("bu_dimmer_off_pct", 0)),
            })
            groups[g_idx]["units"] = units
            self._opts[CONF_BOILER_GROUPS] = groups
            self._opts["_bg_unit_step"] = u_step + 1
            if u_step + 1 < u_total:
                return await self.async_step_boiler_group_unit()
            # Als we vanuit edit kwamen (group al bestaat), terug naar edit
            if len(groups[g_idx].get("units", [])) > 1 or self._opts.get("_bg_edit_idx", -1) >= 0:
                return await self.async_step_boiler_group_edit()
            return self._save(self._opts)

        return self.async_show_form(
            step_id="boiler_group_unit",
            description_placeholders={
                "unit_num":    str(u_step + 1),
                "total":       str(u_total),
                "group_name":  group.get("name", "?"),
            },
            data_schema=vol.Schema({
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
                vol.Optional("bu_setpoint", default=DEFAULT_BOILER_SETPOINT_C):
                    vol.All(vol.Coerce(float), vol.Range(min=30, max=90)),
                vol.Optional("bu_control_mode", default="setpoint"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "switch",             "label": "🔌 Aan/uit schakelaar (switch / input_boolean)"},
                            {"value": "setpoint",           "label": "🌡️ Setpoint instellen (climate / water_heater) — aanbevolen"},
                            {"value": "setpoint_boost",     "label": "🌡️⚡ Setpoint + Boost bij PV-surplus / accu vol (aanbevolen voor Ariston)"},
                            {"value": "preset",             "label": "🎛️ Preset modus (bijv. Ariston green/boost)"},
                            {"value": "dimmer",             "label": "💡 Dimmer / vermogensregeling (RBDimmer, number)"},
                        ],
                        mode="list",
                    )
                ),
                vol.Optional("bu_surplus_setpoint", default=75.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=90, step=1,
                                                  mode="slider", unit_of_measurement="°C")
                ),
                vol.Optional("bu_preset_on",  default="boost"): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("bu_preset_off", default="green"): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("bu_dimmer_on_pct", default=100): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
                vol.Optional("bu_dimmer_off_pct", default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
            }),
        )


    async def async_step_boiler_unit_edit(self, user_input=None):
        """Bewerk een bestaande boiler-unit — pre-filled met huidige waarden."""
        groups  = list(self._opts.get(CONF_BOILER_GROUPS, []))
        g_idx   = int(self._opts.get("_bg_edit_idx", 0))
        u_idx   = int(self._opts.get("_bg_unit_edit_idx", 0))
        group   = groups[g_idx] if g_idx < len(groups) else {}
        units   = list(group.get("units", []))
        unit    = units[u_idx] if u_idx < len(units) else {}

        if user_input is not None:
            updated = dict(unit)  # behoud alle bestaande keys (power_w, priority, etc.)
            updated.update({
                "entity_id":          user_input.get("bu_entity", unit.get("entity_id", "")),
                "temp_sensor":        user_input.get("bu_temp_sensor", unit.get("temp_sensor", "")),
                "energy_sensor":      user_input.get("bu_energy_sensor", unit.get("energy_sensor", "")),
                "label":              user_input.get("bu_label", unit.get("label", f"Boiler {u_idx+1}")),
                "setpoint_c":         float(user_input.get("bu_setpoint", unit.get("setpoint_c", DEFAULT_BOILER_SETPOINT_C))),
                "surplus_setpoint_c": float(user_input.get("bu_surplus_setpoint", unit.get("surplus_setpoint_c", 75.0))),
                "control_mode":       user_input.get("bu_control_mode", unit.get("control_mode", "setpoint")),
                "preset_on":          user_input.get("bu_preset_on",  unit.get("preset_on",  "boost")),
                "preset_off":         user_input.get("bu_preset_off", unit.get("preset_off", "green")),
                "dimmer_on_pct":      float(user_input.get("bu_dimmer_on_pct",  unit.get("dimmer_on_pct",  100))),
                "dimmer_off_pct":     float(user_input.get("bu_dimmer_off_pct", unit.get("dimmer_off_pct", 0))),
            })
            units[u_idx] = updated
            groups[g_idx]["units"] = units
            self._opts[CONF_BOILER_GROUPS] = groups
            return await self.async_step_boiler_group_edit()

        return self.async_show_form(
            step_id="boiler_unit_edit",
            description_placeholders={
                "unit_label": unit.get("label", unit.get("entity_id", f"Boiler {u_idx+1}")),
                "group_name": group.get("name", "?"),
            },
            data_schema=vol.Schema({
                vol.Required("bu_entity", default=unit.get("entity_id", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch", "climate", "water_heater", "input_boolean"]
                    )
                ),
                vol.Optional("bu_temp_sensor", description={"suggested_value": unit.get("temp_sensor", "")}): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional("bu_energy_sensor", description={"suggested_value": unit.get("energy_sensor", "")}): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class=["power", "energy"])
                ),
                vol.Optional("bu_label", default=unit.get("label", f"Boiler {u_idx+1}")): str,
                vol.Optional("bu_setpoint", default=unit.get("setpoint_c", DEFAULT_BOILER_SETPOINT_C)):
                    vol.All(vol.Coerce(float), vol.Range(min=30, max=90)),
                vol.Optional("bu_control_mode", default=unit.get("control_mode", "setpoint")): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "switch",         "label": "🔌 Aan/uit schakelaar (switch / input_boolean)"},
                            {"value": "setpoint",       "label": "🌡️ Setpoint instellen (climate / water_heater) — aanbevolen"},
                            {"value": "setpoint_boost", "label": "🌡️⚡ Setpoint + Boost bij PV-surplus / accu vol (aanbevolen voor Ariston)"},
                            {"value": "preset",         "label": "🎛️ Preset modus (bijv. Ariston green/boost)"},
                            {"value": "dimmer",         "label": "💡 Dimmer / vermogensregeling (RBDimmer, number)"},
                        ],
                        mode="list",
                    )
                ),
                vol.Optional("bu_surplus_setpoint", default=unit.get("surplus_setpoint_c", 75.0)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=90, step=1,
                                                  mode="slider", unit_of_measurement="°C")
                ),
                vol.Optional("bu_preset_on",  default=unit.get("preset_on",  "boost")): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("bu_preset_off", default=unit.get("preset_off", "green")): selector.TextSelector(
                    selector.TextSelectorConfig(type="text")
                ),
                vol.Optional("bu_dimmer_on_pct", default=unit.get("dimmer_on_pct", 100)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
                vol.Optional("bu_dimmer_off_pct", default=unit.get("dimmer_off_pct", 0)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5,
                                                  mode="slider", unit_of_measurement="%")
                ),
            }),
        )


    async def async_step_mail_opts(self, user_input=None):
        """E-mail / SMTP opties — ook bereikbaar vanuit het Configureren-menu."""
        errors: dict = {}
        data = self._data()

        if user_input is not None:
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
                return self._save(user_input)

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
