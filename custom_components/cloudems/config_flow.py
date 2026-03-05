"""Config flow for CloudEMS — v1.5.1."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
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

    VERSION = 3

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
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDAwIDE0MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQwMCIgaGVpZ2h0PSIxNDAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjxjaXJjbGUgY3g9IjQwIiBjeT0iNzAiIHI9IjI4IiBmaWxsPSIjZjk3MzE2MTgiIHN0cm9rZT0iI2Y5NzMxNiIgc3Ryb2tlLXdpZHRoPSIxLjUiLz48dGV4dCB4PSI0MCIgeT0iNjUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMjAiPvCfj608L3RleHQ+PHRleHQgeD0iNDAiIHk9IjgyIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjkiIGZpbGw9IiNmOTczMTYiIGZvbnQtd2VpZ2h0PSI3MDAiPk5ldDwvdGV4dD48bGluZSB4MT0iNjgiIHkxPSI3MCIgeDI9IjExMiIgeTI9IjcwIiBzdHJva2U9IiNmOTczMTYiIHN0cm9rZS13aWR0aD0iMiIgbWFya2VyLWVuZD0idXJsKCNhMSkiLz48Y2lyY2xlIGN4PSIxNDAiIGN5PSI3MCIgcj0iMjgiIGZpbGw9IiM2MzY2ZjExOCIgc3Ryb2tlPSIjNjM2NmYxIiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjE0MCIgeT0iNjUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMjAiPvCfj6A8L3RleHQ+PHRleHQgeD0iMTQwIiB5PSI4MiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjODE4Y2Y4IiBmb250LXdlaWdodD0iNzAwIj5WZXJicnVpazwvdGV4dD48bGluZSB4MT0iMjIwIiB5MT0iNDIiIHgyPSIxNjgiIHkyPSI1NiIgc3Ryb2tlPSIjZmJiZjI0IiBzdHJva2Utd2lkdGg9IjIiIG1hcmtlci1lbmQ9InVybCgjYTIpIi8+PGNpcmNsZSBjeD0iMjQwIiBjeT0iMjgiIHI9IjI0IiBmaWxsPSIjZmJiZjI0MTgiIHN0cm9rZT0iI2ZiYmYyNCIgc3Ryb2tlLXdpZHRoPSIxLjUiLz48dGV4dCB4PSIyNDAiIHk9IjIzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjE3Ij7imIDvuI88L3RleHQ+PHRleHQgeD0iMjQwIiB5PSIzOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjZmJiZjI0IiBmb250LXdlaWdodD0iNzAwIj5ab25uZXN0cm9vbTwvdGV4dD48Y2lyY2xlIGN4PSIyNDAiIGN5PSIxMTAiIHI9IjI0IiBmaWxsPSIjMjJjNTVlMTgiIHN0cm9rZT0iIzIyYzU1ZSIgc3Ryb2tlLXdpZHRoPSIxLjUiLz48dGV4dCB4PSIyNDAiIHk9IjEwNSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxNyI+8J+UizwvdGV4dD48dGV4dCB4PSIyNDAiIHk9IjEyMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjNGFkZTgwIiBmb250LXdlaWdodD0iNzAwIj5CYXR0ZXJpajwvdGV4dD48Y2lyY2xlIGN4PSIzMzAiIGN5PSI3MCIgcj0iMjgiIGZpbGw9IiMyMmM1NWUxOCIgc3Ryb2tlPSIjMjJjNTVlIiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjMzMCIgeT0iNjUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMjAiPvCfmpc8L3RleHQ+PHRleHQgeD0iMzMwIiB5PSI4MiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjNGFkZTgwIiBmb250LXdlaWdodD0iNzAwIj5FViBMYWRlbjwvdGV4dD48dGV4dCB4PSIyMDAiIHk9IjEzNSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4IiBmaWxsPSIjNDc1NTY5Ij5DbG91ZEVNUyBiZWhlZXJ0IGFsbGUgZW5lcmdpZXN0cm9tZW4gYXV0b21hdGlzY2g8L3RleHQ+PGRlZnM+PG1hcmtlciBpZD0iYTEiIG1hcmtlcldpZHRoPSI1IiBtYXJrZXJIZWlnaHQ9IjUiIHJlZlg9IjQiIHJlZlk9IjIuNSIgb3JpZW50PSJhdXRvIj48cGF0aCBkPSJNMCwwIEw1LDIuNSBMMCw1IFoiIGZpbGw9IiNmOTczMTYiLz48L21hcmtlcj48bWFya2VyIGlkPSJhMiIgbWFya2VyV2lkdGg9IjUiIG1hcmtlckhlaWdodD0iNSIgcmVmWD0iNCIgcmVmWT0iMi41IiBvcmllbnQ9ImF1dG8iPjxwYXRoIGQ9Ik0wLDAgTDUsMi41IEwwLDUgWiIgZmlsbD0iI2ZiYmYyNCIvPjwvbWFya2VyPjwvZGVmcz48L3N2Zz4=",
                    
                "support_url": SUPPORT_URL,
                "buy_me_coffee_url": BUY_ME_COFFEE_URL,
                "website": "https://cloudems.eu",
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
            return await self.async_step_grid_sensors()
        return self.async_show_form(
            step_id="grid_connection",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_PRESET, default="3x25A"): _preset_selector(),
            }),
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
            return await self.async_step_grid_sensors()
        return self.async_show_form(
            step_id="phase_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_COUNT, default=3): vol.In({1: "1 phase", 3: "3 phases"}),
                vol.Required(CONF_MAX_CURRENT_L1, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L2, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L3, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
            }),
        )

    # ── 3. Grid sensors ───────────────────────────────────────────────────────
    async def async_step_grid_sensors(self, user_input=None):
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)
        if user_input is not None:
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

        # DSMR5 per-fase teruglevering sensoren (bidirectionele meter).
        # Sommige slimme meters (DSMR5) meten teruglevering per fase apart.
        # Getoond in zowel Basis als Geavanceerd, zodat dit niet ontbreekt in de wizard.
        for exp_key in ("power_sensor_l1_export", "power_sensor_l2_export", "power_sensor_l3_export"):
            sv = self._config.get(exp_key) or s.get(exp_key)
            if sv or phase_count == 3:
                schema[vol.Optional(exp_key, description={"suggested_value": sv})] = _ent()

        return self.async_show_form(
            step_id="grid_sensors",
            data_schema=vol.Schema(schema),
            description_placeholders={
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMjAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPktvcHBlbCBqZSBzbGltbWUgbWV0ZXIgb2YgUDEtbGV6ZXI8L3RleHQ+PHJlY3QgeD0iMTQwIiB5PSIzNSIgd2lkdGg9IjE0MCIgaGVpZ2h0PSI4MCIgcng9IjEwIiBmaWxsPSIjNjM2NmYxMTgiIHN0cm9rZT0iIzYzNjZmMTU1IiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjIxMCIgeT0iNTciIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iOSIgZmlsbD0iIzk0YTNiOCI+U2xpbW1lIG1ldGVyPC90ZXh0PjxyZWN0IHg9IjE2MyIgeT0iNjMiIHdpZHRoPSI5NCIgaGVpZ2h0PSIzMiIgcng9IjYiIGZpbGw9IiMwZjE3MmEiLz48dGV4dCB4PSIyMTAiIHk9Ijc0IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IiM0YWRlODAiPiYjOTY2MDsgMTI0MyBXICBhZm5hbWU8L3RleHQ+PHRleHQgeD0iMjEwIiB5PSI4NiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3IiBmaWxsPSIjZjk3MzE2Ij4mIzk2NTA7IDAgVyAgdGVydWdsZXZlcmluZzwvdGV4dD48dGV4dCB4PSIyMTAiIHk9IjEwNyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjODE4Y2Y4IiBmb250LXdlaWdodD0iNjAwIj5QMS1wb29ydCAoUkoxMSk8L3RleHQ+PGNpcmNsZSBjeD0iNjAiIGN5PSI3NSIgcj0iMjYiIGZpbGw9IiNmOTczMTYxOCIgc3Ryb2tlPSIjZjk3MzE2IiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjYwIiB5PSI3MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxOCI+8J+PrTwvdGV4dD48dGV4dCB4PSI2MCIgeT0iODUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iOCIgZmlsbD0iI2Y5NzMxNiI+RWxla3RyaWNpdGVpdHNuZXQ8L3RleHQ+PGxpbmUgeDE9Ijg2IiB5MT0iNzUiIHgyPSIxNDAiIHkyPSI3NSIgc3Ryb2tlPSIjZjk3MzE2IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1kYXNoYXJyYXk9IjUsMyIvPjxjaXJjbGUgY3g9IjM2MCIgY3k9Ijc1IiByPSIyNiIgZmlsbD0iIzYzNjZmMTE4IiBzdHJva2U9IiM2MzY2ZjEiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iMzYwIiB5PSI3MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxOCI+8J+PoDwvdGV4dD48dGV4dCB4PSIzNjAiIHk9Ijg1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjgiIGZpbGw9IiM4MThjZjgiPkhvbWUgQXNzaXN0YW50PC90ZXh0PjxsaW5lIHgxPSIyODAiIHkxPSI3NSIgeDI9IjMzNCIgeTI9Ijc1IiBzdHJva2U9IiM2MzY2ZjEiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWRhc2hhcnJheT0iNSwzIi8+PC9zdmc+",
                    
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMjIiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPktpZXMgamUgYWFuc2x1aXRpbmc8L3RleHQ+PHJlY3QgeD0iMjAiIHk9IjM1IiB3aWR0aD0iMTYwIiBoZWlnaHQ9IjgwIiByeD0iMTAiIGZpbGw9IiM2MzY2ZjExOCIgc3Ryb2tlPSIjNjM2NmYxNTUiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iMTAwIiB5PSI1OCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI5IiBmaWxsPSIjOTRhM2I4Ij4xLWZhc2UgYWFuc2x1aXRpbmc8L3RleHQ+PHJlY3QgeD0iMzgiIHk9IjY3IiB3aWR0aD0iMzAiIGhlaWdodD0iMzQiIHJ4PSI1IiBmaWxsPSIjNjM2NmYxIiBvcGFjaXR5PSIuOCIvPjx0ZXh0IHg9IjUzIiB5PSI4OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4IiBmaWxsPSJ3aGl0ZSIgZm9udC13ZWlnaHQ9IjcwMCI+TDE8L3RleHQ+PHRleHQgeD0iMTAwIiB5PSIxMDUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTAiIGZpbGw9IiM4MThjZjgiIGZvbnQtd2VpZ2h0PSI3MDAiPjF4MTZBIC8gMXgyNUE8L3RleHQ+PHJlY3QgeD0iMjQwIiB5PSIzNSIgd2lkdGg9IjE2MCIgaGVpZ2h0PSI4MCIgcng9IjEwIiBmaWxsPSIjZmJiZjI0MTgiIHN0cm9rZT0iI2ZiYmYyNDU1IiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjMyMCIgeT0iNTgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iOSIgZmlsbD0iIzk0YTNiOCI+My1mYXNlIGFhbnNsdWl0aW5nPC90ZXh0PjxyZWN0IHg9IjI1NiIgeT0iNjciIHdpZHRoPSIyNCIgaGVpZ2h0PSIzNCIgcng9IjUiIGZpbGw9IiNmOTczMTYiIG9wYWNpdHk9Ii45Ii8+PHRleHQgeD0iMjY4IiB5PSI4OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3IiBmaWxsPSJ3aGl0ZSIgZm9udC13ZWlnaHQ9IjcwMCI+TDE8L3RleHQ+PHJlY3QgeD0iMjg4IiB5PSI2NyIgd2lkdGg9IjI0IiBoZWlnaHQ9IjM0IiByeD0iNSIgZmlsbD0iI2ZiYmYyNCIgb3BhY2l0eT0iLjkiLz48dGV4dCB4PSIzMDAiIHk9Ijg5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IndoaXRlIiBmb250LXdlaWdodD0iNzAwIj5MMjwvdGV4dD48cmVjdCB4PSIzMjAiIHk9IjY3IiB3aWR0aD0iMjQiIGhlaWdodD0iMzQiIHJ4PSI1IiBmaWxsPSIjNGFkZTgwIiBvcGFjaXR5PSIuOSIvPjx0ZXh0IHg9IjMzMiIgeT0iODkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNyIgZmlsbD0id2hpdGUiIGZvbnQtd2VpZ2h0PSI3MDAiPkwzPC90ZXh0Pjx0ZXh0IHg9IjMyMCIgeT0iMTA1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjEwIiBmaWxsPSIjZmJiZjI0IiBmb250LXdlaWdodD0iNzAwIj4zeDE2QSAvIDN4MjVBIC8gM3gzNUE8L3RleHQ+PHRleHQgeD0iMjEwIiB5PSI4MiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzQ3NTU2OSI+dnM8L3RleHQ+PC9zdmc+",
                    
                "phase_count": str(phase_count),
                "detected": str(sum(1 for v in s.values() if v)),
                "mains_voltage": str(DEFAULT_MAINS_VOLTAGE_V),
            },
        )

    # ── 3b. Per-phase sensors (Advanced only) ─────────────────────────────────
    async def async_step_phase_sensors(self, user_input=None):
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)
        if user_input is not None:
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
            description_placeholders={
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMTYiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTAiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPkNULWtsZW1tZW4gb3AgZGUgaW5rb21lbmRlIGthYmVscyAob3B0aW9uZWVsKTwvdGV4dD48bGluZSB4MT0iMzAiIHkxPSI0NSIgeDI9IjM5MCIgeTI9IjQ1IiBzdHJva2U9IiNmOTczMTYiIHN0cm9rZS13aWR0aD0iNSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+PHRleHQgeD0iMTUiIHk9IjQ5IiBmb250LXNpemU9IjkiIGZpbGw9IiNmOTczMTYiIGZvbnQtd2VpZ2h0PSI3MDAiPkwxPC90ZXh0PjxlbGxpcHNlIGN4PSIxNDAiIGN5PSI0NSIgcng9IjE0IiByeT0iOSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTRhM2I4IiBzdHJva2Utd2lkdGg9IjIiLz48bGluZSB4MT0iMTQwIiB5MT0iMzYiIHgyPSIxNDAiIHkyPSIyMCIgc3Ryb2tlPSIjOTRhM2I4IiBzdHJva2Utd2lkdGg9IjEuNSIgc3Ryb2tlLWRhc2hhcnJheT0iMywyIi8+PHJlY3QgeD0iMTEyIiB5PSIxMSIgd2lkdGg9IjU2IiBoZWlnaHQ9IjE0IiByeD0iNCIgZmlsbD0iIzFlMjkzYiIgc3Ryb2tlPSIjNDc1NTY5IiBzdHJva2Utd2lkdGg9IjEiLz48dGV4dCB4PSIxNDAiIHk9IjIxIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjcuNSIgZmlsbD0iIzk0YTNiOCI+c2Vuc29yIEwxIChBKTwvdGV4dD48bGluZSB4MT0iMzAiIHkxPSI3OCIgeDI9IjM5MCIgeTI9Ijc4IiBzdHJva2U9IiNmYmJmMjQiIHN0cm9rZS13aWR0aD0iNSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+PHRleHQgeD0iMTUiIHk9IjgyIiBmb250LXNpemU9IjkiIGZpbGw9IiNmYmJmMjQiIGZvbnQtd2VpZ2h0PSI3MDAiPkwyPC90ZXh0PjxlbGxpcHNlIGN4PSIyMTAiIGN5PSI3OCIgcng9IjE0IiByeT0iOSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTRhM2I4IiBzdHJva2Utd2lkdGg9IjIiLz48bGluZSB4MT0iMjEwIiB5MT0iNjkiIHgyPSIyMTAiIHkyPSI1MyIgc3Ryb2tlPSIjOTRhM2I4IiBzdHJva2Utd2lkdGg9IjEuNSIgc3Ryb2tlLWRhc2hhcnJheT0iMywyIi8+PHJlY3QgeD0iMTgyIiB5PSI0NCIgd2lkdGg9IjU2IiBoZWlnaHQ9IjE0IiByeD0iNCIgZmlsbD0iIzFlMjkzYiIgc3Ryb2tlPSIjNDc1NTY5IiBzdHJva2Utd2lkdGg9IjEiLz48dGV4dCB4PSIyMTAiIHk9IjU0IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjcuNSIgZmlsbD0iIzk0YTNiOCI+c2Vuc29yIEwyIChBKTwvdGV4dD48bGluZSB4MT0iMzAiIHkxPSIxMTEiIHgyPSIzOTAiIHkyPSIxMTEiIHN0cm9rZT0iIzRhZGU4MCIgc3Ryb2tlLXdpZHRoPSI1IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48dGV4dCB4PSIxNSIgeT0iMTE1IiBmb250LXNpemU9IjkiIGZpbGw9IiM0YWRlODAiIGZvbnQtd2VpZ2h0PSI3MDAiPkwzPC90ZXh0PjxlbGxpcHNlIGN4PSIyODAiIGN5PSIxMTEiIHJ4PSIxNCIgcnk9IjkiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzk0YTNiOCIgc3Ryb2tlLXdpZHRoPSIyIi8+PGxpbmUgeDE9IjI4MCIgeTE9IjEwMiIgeDI9IjI4MCIgeTI9Ijg2IiBzdHJva2U9IiM5NGEzYjgiIHN0cm9rZS13aWR0aD0iMS41IiBzdHJva2UtZGFzaGFycmF5PSIzLDIiLz48cmVjdCB4PSIyNTIiIHk9Ijc3IiB3aWR0aD0iNTYiIGhlaWdodD0iMTQiIHJ4PSI0IiBmaWxsPSIjMWUyOTNiIiBzdHJva2U9IiM0NzU1NjkiIHN0cm9rZS13aWR0aD0iMSIvPjx0ZXh0IHg9IjI4MCIgeT0iODciIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNy41IiBmaWxsPSIjOTRhM2I4Ij5zZW5zb3IgTDMgKEEpPC90ZXh0Pjwvc3ZnPg==",
                    "phase_count": str(phase_count)},
        )

    # ── 4. EV Charger ──────────────────────────────────────────────────────────
    async def async_step_solar_ev(self, user_input=None):
        s = self._suggestions
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_inverter_count() if self._advanced() else await self.async_step_features()
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
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMjAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPktvcHBlbCBvbXZvcm1lciwgYmF0dGVyaWogZW4gbGFhZHBhYWwgKG9wdGlvbmVlbCk8L3RleHQ+PHJlY3QgeD0iMjAiIHk9IjQwIiB3aWR0aD0iMTAwIiBoZWlnaHQ9IjcwIiByeD0iOSIgZmlsbD0iI2ZiYmYyNDE4IiBzdHJva2U9IiNmYmJmMjQ1NSIgc3Ryb2tlLXdpZHRoPSIxLjUiLz48dGV4dCB4PSI3MCIgeT0iNjMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTgiPuKYgO+4jzwvdGV4dD48dGV4dCB4PSI3MCIgeT0iNzgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iOC41IiBmaWxsPSIjZmJiZjI0IiBmb250LXdlaWdodD0iNjAwIj5PbXZvcm1lcjwvdGV4dD48dGV4dCB4PSI3MCIgeT0iOTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNyIgZmlsbD0iIzY0NzQ4YiI+dmVybW9nZW5zc2Vuc29yPC90ZXh0Pjx0ZXh0IHg9IjcwIiB5PSIxMDIiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNyIgZmlsbD0iIzY0NzQ4YiI+KFcgb2Yga1cpPC90ZXh0PjxyZWN0IHg9IjE2MCIgeT0iNDAiIHdpZHRoPSIxMDAiIGhlaWdodD0iNzAiIHJ4PSI5IiBmaWxsPSIjMjJjNTVlMTgiIHN0cm9rZT0iIzIyYzU1ZTU1IiBzdHJva2Utd2lkdGg9IjEuNSIvPjx0ZXh0IHg9IjIxMCIgeT0iNjMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTgiPvCflIs8L3RleHQ+PHRleHQgeD0iMjEwIiB5PSI3OCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4LjUiIGZpbGw9IiM0YWRlODAiIGZvbnQtd2VpZ2h0PSI2MDAiPkJhdHRlcmlqPC90ZXh0Pjx0ZXh0IHg9IjIxMCIgeT0iOTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNyIgZmlsbD0iIzY0NzQ4YiI+KyA9IGxhZGVuPC90ZXh0Pjx0ZXh0IHg9IjIxMCIgeT0iMTAyIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IiM2NDc0OGIiPi0gPSBvbnRsYWRlbjwvdGV4dD48cmVjdCB4PSIzMDAiIHk9IjQwIiB3aWR0aD0iMTAwIiBoZWlnaHQ9IjcwIiByeD0iOSIgZmlsbD0iIzgxOGNmODE4IiBzdHJva2U9IiM4MThjZjg1NSIgc3Ryb2tlLXdpZHRoPSIxLjUiLz48dGV4dCB4PSIzNTAiIHk9IjYzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjE4Ij7wn5qXPC90ZXh0Pjx0ZXh0IHg9IjM1MCIgeT0iNzgiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iOC41IiBmaWxsPSIjODE4Y2Y4IiBmb250LXdlaWdodD0iNjAwIj5MYWFkcGFhbDwvdGV4dD48dGV4dCB4PSIzNTAiIHk9IjkwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IiM2NDc0OGIiPnNldHBvaW50IGVudGl0ZWl0PC90ZXh0Pjx0ZXh0IHg9IjM1MCIgeT0iMTAyIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IiM2NDc0OGIiPihudW1iZXIpPC90ZXh0Pjx0ZXh0IHg9IjIxMCIgeT0iMTI0IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjgiIGZpbGw9IiM0NzU1NjkiPkFsbGUgdmVsZGVuIHppam4gb3B0aW9uZWVsPC90ZXh0Pjwvc3ZnPg==",
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
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMjAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPlBlciBvbXZvcm1lcjogdmVybW9nZW4gKyByaWNodGluZyArIGhlbGxpbmc8L3RleHQ+PHJlY3QgeD0iMjAiIHk9IjQwIiB3aWR0aD0iNTAiIGhlaWdodD0iMzUiIHJ4PSI2IiBmaWxsPSIjZmJiZjI0MjAiIHN0cm9rZT0iI2ZiYmYyNDY2IiBzdHJva2Utd2lkdGg9IjEuNSIvPjxyZWN0IHg9IjI4IiB5PSI0NyIgd2lkdGg9IjE1IiBoZWlnaHQ9IjIwIiByeD0iMiIgZmlsbD0iIzFlM2E1ZiIgc3Ryb2tlPSIjM2I4MmY2IiBzdHJva2Utd2lkdGg9IjAuOCIvPjxyZWN0IHg9IjQ3IiB5PSI0NyIgd2lkdGg9IjE1IiBoZWlnaHQ9IjIwIiByeD0iMiIgZmlsbD0iIzFlM2E1ZiIgc3Ryb2tlPSIjM2I4MmY2IiBzdHJva2Utd2lkdGg9IjAuOCIvPjx0ZXh0IHg9IjQ1IiB5PSI4NiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3LjUiIGZpbGw9IiNmYmJmMjQiPlBhbmVsZW48L3RleHQ+PGxpbmUgeDE9IjcyIiB5MT0iNTgiIHgyPSIxMDUiIHkyPSI1OCIgc3Ryb2tlPSIjZmJiZjI0IiBzdHJva2Utd2lkdGg9IjIiIG1hcmtlci1lbmQ9InVybCgjYmkpIi8+PHJlY3QgeD0iMTA4IiB5PSI0MCIgd2lkdGg9IjgwIiBoZWlnaHQ9Ijc2IiByeD0iOSIgZmlsbD0iIzFlMjkzYiIgc3Ryb2tlPSIjNjM2NmYxNTUiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iMTQ4IiB5PSI2MiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxNCI+JiM5ODg5OzwvdGV4dD48dGV4dCB4PSIxNDgiIHk9Ijc2IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjgiIGZpbGw9IiM4MThjZjgiIGZvbnQtd2VpZ2h0PSI2MDAiPk9tdm9ybWVyPC90ZXh0Pjx0ZXh0IHg9IjE0OCIgeT0iOTIiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iNyIgZmlsbD0iIzY0NzQ4YiI+YXppbXV0OiAxODAgWjwvdGV4dD48dGV4dCB4PSIxNDgiIHk9IjEwNiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3IiBmaWxsPSIjNjQ3NDhiIj5oZWxsaW5nOiAzMCBncmFkZW48L3RleHQ+PHJlY3QgeD0iMjEwIiB5PSI0MCIgd2lkdGg9IjE5MCIgaGVpZ2h0PSI3NiIgcng9IjkiIGZpbGw9IiMwZjE3MmEiIHN0cm9rZT0iIzFlMjkzYiIgc3Ryb2tlLXdpZHRoPSIxIi8+PHRleHQgeD0iMzA1IiB5PSI1OCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4IiBmaWxsPSIjOTRhM2I4Ij5Db25maWd1cmF0aWUgcGVyIG9tdm9ybWVyPC90ZXh0Pjx0ZXh0IHg9IjIyMiIgeT0iNzMiIGZvbnQtc2l6ZT0iNy41IiBmaWxsPSIjOTRhM2I4Ij5WZXJtb2dlbnNzZW5zb3IgKFcgb2Yga1cpPC90ZXh0Pjx0ZXh0IHg9IjIyMiIgeT0iODciIGZvbnQtc2l6ZT0iNy41IiBmaWxsPSIjOTRhM2I4Ij5OYWFtIGJpanYuIERhayBadWlkPC90ZXh0Pjx0ZXh0IHg9IjIyMiIgeT0iMTAxIiBmb250LXNpemU9IjcuNSIgZmlsbD0iIzk0YTNiOCI+QXppbXV0OiAwTiA5ME8gMTgwWiAyNzBXPC90ZXh0Pjx0ZXh0IHg9IjIyMiIgeT0iMTE1IiBmb250LXNpemU9IjcuNSIgZmlsbD0iIzk0YTNiOCI+SGVsbGluZzogMD1wbGF0IDkwPXZlcnRpY2FhbDwvdGV4dD48ZGVmcz48bWFya2VyIGlkPSJiaSIgbWFya2VyV2lkdGg9IjUiIG1hcmtlckhlaWdodD0iNSIgcmVmWD0iNCIgcmVmWT0iMi41IiBvcmllbnQ9ImF1dG8iPjxwYXRoIGQ9Ik0wLDAgTDUsMi41IEwwLDUgWiIgZmlsbD0iI2ZiYmYyNCIvPjwvbWFya2VyPjwvZGVmcz48L3N2Zz4=",
                    
                "inverter_num": str(i), "total": str(self._inv_count),
                "azimuth_tip": "0=N 90=E 180=S 270=W — leeg = zelf leren",
                "tilt_tip":    "0=plat 90=verticaal — leeg = zelf leren",
            },
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
        return self.async_show_form(
            step_id="battery_count",
            data_schema=vol.Schema({
                vol.Required(CONF_BATTERY_COUNT, default="0"): _inverter_count_selector(),
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
            return await self.async_step_features()
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

    # ── 5. Features ───────────────────────────────────────────────────────────
    async def async_step_features(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_peak_config() if user_input.get(CONF_PEAK_SHAVING_ENABLED) else await self.async_step_prices()

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
            vol.Optional("nilm_min_confidence", default=0.80):
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
            return await self.async_step_prices()
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
                vol.Optional(CONF_PRICE_INCLUDE_TAX,  default=False): bool,
                vol.Optional(CONF_PRICE_INCLUDE_BTW,  default=False): bool,
                vol.Optional(CONF_SELECTED_SUPPLIER,  default="none"):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=sup_options, mode="dropdown")),
                vol.Optional(CONF_SUPPLIER_MARKUP, default=0.0):
                    vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.5)),
            }),
        )

    # ── 6. AI & NILM provider ─────────────────────────────────────────────────
    async def async_step_ai_config(self, user_input=None):
        if user_input is not None:
            provider = user_input.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
            self._config.update(user_input)
            # Back-compat: set ollama_enabled flag
            self._config[CONF_OLLAMA_ENABLED] = (provider == AI_PROVIDER_OLLAMA)
            if provider == AI_PROVIDER_OLLAMA:
                return await self.async_step_ollama_config()
            return await self.async_step_advanced() if self._advanced() else self._create()

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
            return await self.async_step_advanced() if self._advanced() else self._create()
        return self.async_show_form(
            step_id="ollama_config",
            data_schema=vol.Schema({
                vol.Optional(CONF_OLLAMA_HOST,  default=DEFAULT_OLLAMA_HOST): str,
                vol.Optional(CONF_OLLAMA_PORT,  default=DEFAULT_OLLAMA_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_OLLAMA_MODEL, default=DEFAULT_OLLAMA_MODEL): str,
            }),
        )

    # ── 7. Advanced options (P1) — Advanced only ──────────────────────────────
    async def async_step_advanced(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_p1_config() if user_input.get(CONF_P1_ENABLED) else self._create()
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema({vol.Optional(CONF_P1_ENABLED, default=False): bool}),
        )

    async def async_step_p1_config(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return self._create()
        return self.async_show_form(
            step_id="p1_config",
            data_schema=vol.Schema({
                vol.Optional(CONF_P1_HOST): str,
                vol.Optional(CONF_P1_PORT, default=DEFAULT_P1_PORT): vol.All(int, vol.Range(min=1, max=65535)),
            }),
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
        preset = self._config.get(CONF_PHASE_PRESET, "")
        if preset and preset != "custom":
            return f"CloudEMS ({preset})"
        count = self._config.get(CONF_PHASE_COUNT, "?")
        l1    = self._config.get(CONF_MAX_CURRENT_L1, "?")
        return f"CloudEMS ({count}×{l1} A)"

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

    def _data(self) -> dict:
        # OptionsFlowWithConfigEntry exposes self.config_entry; keep _entry too.
        entry = getattr(self, "config_entry", self._entry)
        return {**entry.data, **entry.options, **self._opts}

    def _entry_options(self) -> dict:
        """Return current entry options — works with both base classes."""
        entry = getattr(self, "config_entry", self._entry)
        return dict(entry.options)

    def _save(self, extra: dict) -> object:
        """Merge extra into options and save; triggers auto-reload via base class."""
        return self.async_create_entry(title="", data={**self._entry_options(), **extra})

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
                        selector.SelectOptionDict(value="batteries_opts", label="🔋 Batteries"),
                        selector.SelectOptionDict(value="prices_opts",    label="💶 Prijzen & Belasting"),
                        selector.SelectOptionDict(value="features_opts",  label="🚀 Features"),
                        selector.SelectOptionDict(value="cheap_switches_opts", label="⚡ Goedkope Uren Schakelaars"),
                        selector.SelectOptionDict(value="ai_opts",        label="🤖 AI & NILM"),
                        selector.SelectOptionDict(value="nilm_devices_opts", label="🏷️ NILM Apparaten beheren"),
                        selector.SelectOptionDict(value="advanced_opts",  label="📡 P1 & Advanced"),
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
        return self.async_show_form(step_id="phase_sensors", data_schema=vol.Schema(schema))

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
                vol.Optional(CONF_ENABLE_SOLAR_DIMMER, default=bool(data.get(CONF_ENABLE_SOLAR_DIMMER, False))): bool,
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
        """Wizard stap: koppel schakelaars aan goedkoopste uren.

        Toont 4 slots. Per slot: entiteit + venstergrootte + vroegste/laatste uur.
        Lege entiteit = slot niet actief.
        """
        import json
        data = self._data()

        if user_input is not None:
            # Bouw cheap_switches lijst uit de slot-velden
            cheap_switches = []
            for i in range(1, 5):
                eid = user_input.get(f"slot{i}_entity", "")
                if not eid:
                    continue
                cheap_switches.append({
                    "entity_id":     eid,
                    "window_hours":  int(user_input.get(f"slot{i}_window", 4)),
                    "earliest_hour": int(user_input.get(f"slot{i}_earliest", 0)),
                    "latest_hour":   int(user_input.get(f"slot{i}_latest", 23)),
                    "active":        True,
                })
            return self._save({"cheap_switches": cheap_switches})

        # Bestaande configuratie terugzetten in slots
        existing = data.get("cheap_switches", []) or []
        defaults: list[dict] = (list(existing) + [{}, {}, {}, {}])[:4]

        def _slot_eid(i):
            return defaults[i].get("entity_id", "") if i < len(defaults) else ""
        def _slot_win(i):
            return int(defaults[i].get("window_hours", 4)) if i < len(defaults) else 4
        def _slot_ear(i):
            return int(defaults[i].get("earliest_hour", 0)) if i < len(defaults) else 0
        def _slot_lat(i):
            return int(defaults[i].get("latest_hour", 23)) if i < len(defaults) else 23

        _window_opts = selector.SelectSelectorConfig(options=[
            selector.SelectOptionDict(value="1", label="Goedkoopste 1 uur"),
            selector.SelectOptionDict(value="2", label="Goedkoopste 2 aaneengesloten uren"),
            selector.SelectOptionDict(value="3", label="Goedkoopste 3 aaneengesloten uren"),
            selector.SelectOptionDict(value="4", label="Goedkoopste 4 aaneengesloten uren"),
        ], mode="list")

        _entity_sel = selector.EntitySelectorConfig(
            domain=["switch", "input_boolean", "light", "script", "automation"],
            multiple=False,
        )

        schema = {}
        for i in range(1, 5):
            schema[vol.Optional(f"slot{i}_entity",   default=_slot_eid(i-1))] = \
                selector.EntitySelector(_entity_sel)
            schema[vol.Optional(f"slot{i}_window",   default=str(_slot_win(i-1)))] = \
                selector.SelectSelector(_window_opts)
            schema[vol.Optional(f"slot{i}_earliest", default=_slot_ear(i-1))] = \
                vol.All(vol.Coerce(int), vol.Range(min=0, max=23))
            schema[vol.Optional(f"slot{i}_latest",   default=_slot_lat(i-1))] = \
                vol.All(vol.Coerce(int), vol.Range(min=0, max=23))

        return self.async_show_form(
            step_id="cheap_switches_opts",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "info": (
                    "Koppel tot 4 schakelaars aan het goedkoopste stroomblok. "
                    "CloudEMS zet de schakelaar automatisch AAN zodra het goedkope blok begint — "
                    "nooit UIT. Laat een slot leeg om het niet te gebruiken."
                )
            },
        )
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
                    "diagram_url": "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNDIwIDEzMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiI+PHJlY3Qgd2lkdGg9IjQyMCIgaGVpZ2h0PSIxMzAiIHJ4PSIxMiIgZmlsbD0iIzFjMWMyZSIvPjx0ZXh0IHg9IjIxMCIgeT0iMjAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiM5NGEzYjgiIGZvbnQtd2VpZ2h0PSI2MDAiPlAxL0RTTVIgZGlyZWN0ZSBUQ1AgdmVyYmluZGluZzwvdGV4dD48cmVjdCB4PSIyMCIgeT0iMzUiIHdpZHRoPSI5MCIgaGVpZ2h0PSI4MCIgcng9IjkiIGZpbGw9IiMyMmM1NWUxOCIgc3Ryb2tlPSIjMjJjNTVlNTUiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iNjUiIHk9IjY1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjIyIj7wn5SMPC90ZXh0Pjx0ZXh0IHg9IjY1IiB5PSI4MiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI4LjUiIGZpbGw9IiM0YWRlODAiIGZvbnQtd2VpZ2h0PSI2MDAiPlNsaW1tZSBtZXRlcjwvdGV4dD48cmVjdCB4PSI0MiIgeT0iOTAiIHdpZHRoPSI0NiIgaGVpZ2h0PSIxNiIgcng9IjQiIGZpbGw9IiMwZjE3MmEiIHN0cm9rZT0iIzIyYzU1ZTU1Ii8+PHRleHQgeD0iNjUiIHk9IjEwMiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3IiBmaWxsPSIjNGFkZTgwIj5QMS1wb29ydDwvdGV4dD48bGluZSB4MT0iMTEwIiB5MT0iNzUiIHgyPSIxNjAiIHkyPSI3NSIgc3Ryb2tlPSIjMjJjNTVlIiBzdHJva2Utd2lkdGg9IjIuNSIgc3Ryb2tlLWRhc2hhcnJheT0iNiwzIi8+PHJlY3QgeD0iMTYzIiB5PSI1MCIgd2lkdGg9IjgwIiBoZWlnaHQ9IjUwIiByeD0iOCIgZmlsbD0iIzFlMjkzYiIgc3Ryb2tlPSIjNjM2NmYxNTUiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iMjAzIiB5PSI3MyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxNCI+8J+ToTwvdGV4dD48dGV4dCB4PSIyMDMiIHk9Ijg2IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjgiIGZpbGw9IiM4MThjZjgiIGZvbnQtd2VpZ2h0PSI2MDAiPlAxLWxlemVyIChUQ1ApPC90ZXh0PjxsaW5lIHgxPSIyNDMiIHkxPSI3NSIgeDI9IjI5NSIgeTI9Ijc1IiBzdHJva2U9IiM2MzY2ZjEiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWRhc2hhcnJheT0iNSwzIi8+PHJlY3QgeD0iMjk4IiB5PSI1MCIgd2lkdGg9IjEwMCIgaGVpZ2h0PSI1MCIgcng9IjgiIGZpbGw9IiM2MzY2ZjExOCIgc3Ryb2tlPSIjNjM2NmYxNTUiIHN0cm9rZS13aWR0aD0iMS41Ii8+PHRleHQgeD0iMzQ4IiB5PSI3MyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxNCI+8J+PoDwvdGV4dD48dGV4dCB4PSIzNDgiIHk9Ijg2IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjgiIGZpbGw9IiM4MThjZjgiIGZvbnQtd2VpZ2h0PSI2MDAiPkNsb3VkRU1TIEhBPC90ZXh0Pjx0ZXh0IHg9IjEzNSIgeT0iMTE4IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjciIGZpbGw9IiM0NzU1NjkiPlJKMTEgYmVkcmFhZDwvdGV4dD48dGV4dCB4PSIyNzAiIHk9IjExOCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSI3IiBmaWxsPSIjNDc1NTY5Ij5UQ1AgMTkyLjE2OC54Lng6cG9vcnQ8L3RleHQ+PC9zdmc+",
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
        """💶 Prijzen & Belasting — incl. contracttype (dynamisch / vast tarief)."""
        from .const import (CONF_CONTRACT_TYPE, CONTRACT_TYPE_DYNAMIC, CONTRACT_TYPE_FIXED,
                            DEFAULT_CONTRACT_TYPE, CONF_FIXED_IMPORT_PRICE, CONF_FIXED_EXPORT_PRICE)
        data = self._data()
        country = data.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        suppliers = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"])
        sup_options = [
            selector.SelectOptionDict(value=k, label=v[0])
            for k, v in suppliers.items()
        ]
        contract_type = data.get(CONF_CONTRACT_TYPE, DEFAULT_CONTRACT_TYPE)
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(
            step_id="prices_opts",
            data_schema=vol.Schema({
                # v1.15.0: contract type — dynamisch (EPEX) of vast tarief
                vol.Optional(CONF_CONTRACT_TYPE, default=contract_type): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=CONTRACT_TYPE_DYNAMIC, label="⚡ Dynamisch (EPEX dag-vooruit)"),
                        selector.SelectOptionDict(value=CONTRACT_TYPE_FIXED,   label="📋 Vast tarief"),
                    ], mode="list")
                ),
                vol.Optional(CONF_FIXED_IMPORT_PRICE, default=float(data.get(CONF_FIXED_IMPORT_PRICE, 0.25))): vol.All(vol.Coerce(float), vol.Range(min=0, max=2.0)),
                vol.Optional(CONF_FIXED_EXPORT_PRICE, default=float(data.get(CONF_FIXED_EXPORT_PRICE, 0.09))): vol.All(vol.Coerce(float), vol.Range(min=0, max=2.0)),
                # Existing fields
                vol.Optional(CONF_PRICE_INCLUDE_TAX, default=bool(data.get(CONF_PRICE_INCLUDE_TAX, False))): bool,
                vol.Optional(CONF_PRICE_INCLUDE_BTW, default=bool(data.get(CONF_PRICE_INCLUDE_BTW, False))): bool,
                vol.Optional(CONF_SELECTED_SUPPLIER, default=str(data.get(CONF_SELECTED_SUPPLIER, "none"))):
                    selector.SelectSelector(selector.SelectSelectorConfig(options=sup_options, mode="dropdown")),
                vol.Optional(CONF_SUPPLIER_MARKUP, default=float(data.get(CONF_SUPPLIER_MARKUP, 0.0))):
                    vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.5)),
            }),
        )


    async def async_step_batteries_opts(self, user_input=None):
        """How many batteries do you have?"""
        data = self._data()
        existing_cfgs = data.get(CONF_BATTERY_CONFIGS, [])

        # Legacy: user may have a single battery via CONF_BATTERY_SENSOR (not multi-config).
        # Synthesise a minimal config entry so the wizard shows 1 (not 0) as default.
        legacy_sensor = data.get(CONF_BATTERY_SENSOR)
        if not existing_cfgs and legacy_sensor:
            existing_cfgs = [{"power_sensor": legacy_sensor, "label": "Batterij 1"}]

        current_count = len(existing_cfgs)
        if user_input is not None:
            self._inv_count = int(user_input.get(CONF_BATTERY_COUNT, 0))
            self._opts[CONF_BATTERY_COUNT]   = self._inv_count
            self._opts[CONF_BATTERY_CONFIGS] = []
            # Keep synthesised configs for pre-fill in detail steps
            self._existing_bat_cfgs = existing_cfgs
            self._inv_step = 0
            if self._inv_count > 0:
                return await self.async_step_battery_detail_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = False
            self._opts[CONF_BATTERY_SENSOR] = ""   # clear legacy sensor if removing all
            return self._save(self._opts)

        bat_names = ", ".join(
            c.get("label", f"Batterij {i+1}") for i, c in enumerate(existing_cfgs)
        ) or "—"
        return self.async_show_form(
            step_id="batteries_opts",
            data_schema=vol.Schema({
                vol.Required(CONF_BATTERY_COUNT, default=current_count): _inverter_count_selector(),
            }),
            description_placeholders={
                "current_count": str(current_count),
                "battery_names": bat_names,
            },
        )

    async def async_step_battery_detail_opts(self, user_input=None):
        """Configure one battery at a time."""
        data = self._data()
        i = self._inv_step + 1
        # Use the synthesised/existing configs stored during batteries_opts
        existing_cfgs = getattr(self, "_existing_bat_cfgs", data.get(CONF_BATTERY_CONFIGS, []))
        existing = existing_cfgs[self._inv_step] if self._inv_step < len(existing_cfgs) else {}

        if user_input is not None:
            self._opts[CONF_BATTERY_CONFIGS].append({
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
                return await self.async_step_battery_detail_opts()
            self._opts[CONF_ENABLE_MULTI_BATTERY] = len(self._opts[CONF_BATTERY_CONFIGS]) > 0
            return self._save(self._opts)

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

    async def async_step_advanced_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(
            step_id="advanced_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_P1_ENABLED, default=bool(data.get(CONF_P1_ENABLED, False))): bool,
                vol.Optional(CONF_P1_HOST,    default=str(data.get(CONF_P1_HOST, ""))): str,
                vol.Optional(CONF_P1_PORT,    default=int(data.get(CONF_P1_PORT, DEFAULT_P1_PORT))): vol.All(int, vol.Range(min=1, max=65535)),
            }),
        )
