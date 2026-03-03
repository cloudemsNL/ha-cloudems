"""Config flow for CloudEMS — v1.5.0."""
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
    CONF_WIZARD_MODE, WIZARD_MODE_BASIC, WIZARD_MODE_ADVANCED,
    CONF_AI_PROVIDER, AI_PROVIDER_NONE, AI_PROVIDER_CLOUDEMS,
    AI_PROVIDER_OPENAI, AI_PROVIDER_ANTHROPIC, AI_PROVIDER_OLLAMA,
    AI_PROVIDER_LABELS, AI_PROVIDERS_NEEDING_KEY,
    CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE,
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
    scored = [(s, _score(s, keywords)) for s in pool]
    scored = [(s, sc) for s, sc in scored if sc > 0]
    return max(scored, key=lambda x: x[1])[0] if scored else None

def _detect_sensors(hass, phase_count: int) -> dict:
    power   = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") in ("W","kW")]
    current = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") == "A"]
    voltage = [s.entity_id for s in hass.states.async_all("sensor") if s.attributes.get("unit_of_measurement") == "V"]
    p3 = phase_count == 3
    return {
        CONF_GRID_SENSOR:            _best(power,   GRID_SENSOR_KEYWORDS),
        CONF_IMPORT_SENSOR:          _best(power,   ["import","levering","power_delivered","consume"]),
        CONF_EXPORT_SENSOR:          _best(power,   ["export","teruglevering","power_returned","feed"]),
        CONF_SOLAR_SENSOR:           _best(power,   ["solar","pv","zon","inverter","omvormer","yield"]),
        CONF_BATTERY_SENSOR:         _best(power,   ["battery","batterij","accu","batt","storage"]),
        CONF_PHASE_SENSORS+"_L1":    _best(current, PHASE_SENSOR_KEYWORDS_L1),
        CONF_PHASE_SENSORS+"_L2":    _best(current, PHASE_SENSOR_KEYWORDS_L2) if p3 else None,
        CONF_PHASE_SENSORS+"_L3":    _best(current, PHASE_SENSOR_KEYWORDS_L3) if p3 else None,
        CONF_VOLTAGE_L1:             _best(voltage, ["l1","phase1","phase_1","fase_1"]),
        CONF_VOLTAGE_L2:             _best(voltage, ["l2","phase2","phase_2","fase_2"]) if p3 else None,
        CONF_VOLTAGE_L3:             _best(voltage, ["l3","phase3","phase_3","fase_3"]) if p3 else None,
        CONF_POWER_L1:               _best(power,   PHASE_SENSOR_KEYWORDS_L1),
        CONF_POWER_L2:               _best(power,   PHASE_SENSOR_KEYWORDS_L2) if p3 else None,
        CONF_POWER_L3:               _best(power,   PHASE_SENSOR_KEYWORDS_L3) if p3 else None,
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

    VERSION = 1

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._suggestions: dict = {}
        self._inv_count = 0
        self._inv_step  = 0

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

        schema: dict = {vol.Optional(CONF_USE_SEPARATE_IE, default=False): bool}
        if not use_sep:
            schema[vol.Optional(CONF_GRID_SENSOR, description={"suggested_value": s.get(CONF_GRID_SENSOR)})] = _ent()
        else:
            schema[vol.Optional(CONF_IMPORT_SENSOR, description={"suggested_value": s.get(CONF_IMPORT_SENSOR)})] = _ent()
            schema[vol.Optional(CONF_EXPORT_SENSOR, description={"suggested_value": s.get(CONF_EXPORT_SENSOR)})] = _ent()
        schema[vol.Optional(CONF_MAINS_VOLTAGE, default=DEFAULT_MAINS_VOLTAGE_V)] = \
            vol.All(vol.Coerce(float), vol.Range(min=100, max=480))

        return self.async_show_form(
            step_id="grid_sensors",
            data_schema=vol.Schema(schema),
            description_placeholders={
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
        schema: dict = {
            vol.Optional(CONF_PHASE_SENSORS+"_L1", description={"suggested_value": s.get(CONF_PHASE_SENSORS+"_L1")}): _ent(),
            vol.Optional(CONF_VOLTAGE_L1,          description={"suggested_value": s.get(CONF_VOLTAGE_L1)}):          _ent(),
            vol.Optional(CONF_POWER_L1,            description={"suggested_value": s.get(CONF_POWER_L1)}):            _ent(),
        }
        if phase_count == 3:
            for k, sk in [(CONF_PHASE_SENSORS+"_L2", CONF_PHASE_SENSORS+"_L2"),
                          (CONF_PHASE_SENSORS+"_L3", CONF_PHASE_SENSORS+"_L3"),
                          (CONF_VOLTAGE_L2, CONF_VOLTAGE_L2), (CONF_VOLTAGE_L3, CONF_VOLTAGE_L3),
                          (CONF_POWER_L2,   CONF_POWER_L2),   (CONF_POWER_L3,   CONF_POWER_L3)]:
                schema[vol.Optional(k, description={"suggested_value": s.get(sk)})] = _ent()
        return self.async_show_form(
            step_id="phase_sensors",
            data_schema=vol.Schema(schema),
            description_placeholders={"phase_count": str(phase_count)},
        )

    # ── 4. Solar & EV ─────────────────────────────────────────────────────────
    async def async_step_solar_ev(self, user_input=None):
        s = self._suggestions
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_inverter_count() if self._advanced() else await self.async_step_features()
        return self.async_show_form(
            step_id="solar_ev",
            data_schema=vol.Schema({
                vol.Optional(CONF_SOLAR_SENSOR,   description={"suggested_value": s.get(CONF_SOLAR_SENSOR)}):   _ent(),
                vol.Optional(CONF_BATTERY_SENSOR, description={"suggested_value": s.get(CONF_BATTERY_SENSOR)}): _ent(),
                vol.Optional(CONF_EV_CHARGER_ENTITY):  _ent(["number","input_number"]),
                vol.Optional(CONF_ENABLE_SOLAR_DIMMER, default=False): bool,
                vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=DEFAULT_NEGATIVE_PRICE_THRESHOLD): vol.Coerce(float),
            }),
        )

    # ── 4b. Inverter count (Advanced) ─────────────────────────────────────────
    async def async_step_inverter_count(self, user_input=None):
        if user_input is not None:
            self._inv_count = int(user_input.get(CONF_INVERTER_COUNT, 0))
            self._config[CONF_INVERTER_COUNT]   = self._inv_count
            self._config[CONF_INVERTER_CONFIGS] = []
            self._inv_step = 0
            return await self.async_step_inverter_detail() if self._inv_count > 0 else await self.async_step_features()
        return self.async_show_form(
            step_id="inverter_count",
            data_schema=vol.Schema({vol.Required(CONF_INVERTER_COUNT, default="0"): _inverter_count_selector()}),
            description_placeholders={"docs_url": SUPPORT_URL},
        )

    # ── 4c. Inverter detail loop (Advanced) ───────────────────────────────────
    async def async_step_inverter_detail(self, user_input=None):
        i = self._inv_step + 1
        if user_input is not None:
            self._config[CONF_INVERTER_CONFIGS].append({
                "entity_id":      user_input.get("inv_sensor"),
                "control_entity": user_input.get("inv_control", ""),
                "label":          user_input.get("inv_label", f"Inverter {i}"),
                "priority":       i,
                "min_power_pct":  float(user_input.get("inv_min_pct", 0.0)),
                "azimuth_deg":    user_input.get("inv_azimuth") or None,
                "tilt_deg":       user_input.get("inv_tilt") or None,
            })
            self._inv_step += 1
            if self._inv_step < self._inv_count:
                return await self.async_step_inverter_detail()
            if self._config[CONF_INVERTER_CONFIGS]:
                self._config[CONF_ENABLE_MULTI_INVERTER] = True
            return await self.async_step_features()
        return self.async_show_form(
            step_id="inverter_detail",
            data_schema=vol.Schema({
                vol.Required("inv_sensor"):      _ent(),
                vol.Optional("inv_control"):     _ent(["switch","number"]),
                vol.Optional("inv_label", default=f"Inverter {i}"): str,
                vol.Optional("inv_min_pct", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
                vol.Optional("inv_azimuth"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=360))),
                vol.Optional("inv_tilt"):    vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=90))),
            }),
            description_placeholders={
                "inverter_num": str(i), "total": str(self._inv_count),
                "azimuth_tip": "0=N 90=E 180=S 270=W — leave blank to self-learn",
                "tilt_tip":    "0=flat 90=vertical — leave blank to self-learn",
            },
        )

    # ── 5. Features ───────────────────────────────────────────────────────────
    async def async_step_features(self, user_input=None):
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_peak_config() if user_input.get(CONF_PEAK_SHAVING_ENABLED) else await self.async_step_ai_config()

        phase_count = self._config.get(CONF_PHASE_COUNT, 1)
        schema: dict = {
            vol.Optional(CONF_DYNAMIC_LOADING, default=False): bool,
            vol.Optional(CONF_DYNAMIC_LOAD_THRESHOLD, default=DEFAULT_DYNAMIC_LOAD_THRESHOLD):
                vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=1.0)),
            vol.Optional(CONF_COST_TRACKING, default=True): bool,
            vol.Optional(CONF_PEAK_SHAVING_ENABLED, default=False): bool,
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
            return await self.async_step_ai_config()
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
        return self.async_create_entry(title=self._build_title(), data=self._config)

    def _build_title(self) -> str:
        preset = self._config.get(CONF_PHASE_PRESET, "")
        if preset and preset != "custom":
            return f"CloudEMS ({preset})"
        count = self._config.get(CONF_PHASE_COUNT, "?")
        l1    = self._config.get(CONF_MAX_CURRENT_L1, "?")
        return f"CloudEMS ({count}×{l1} A)"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CloudEMSOptionsFlow(config_entry)


# ══════════════════════════════════════════════════════════════════════════════
# Options flow — multi-step grouped by category
# ══════════════════════════════════════════════════════════════════════════════

class CloudEMSOptionsFlow(config_entries.OptionsFlow):

    def __init__(self, config_entry) -> None:
        self._entry = config_entry
        self._opts: dict = {}

    def _data(self) -> dict:
        return {**self._entry.data, **self._entry.options, **self._opts}

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            section = user_input.get("section", "sensors")
            return await getattr(self, f"async_step_{section}")()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("section", default="sensors"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value="sensors",       label="🔌 Grid Sensors"),
                        selector.SelectOptionDict(value="phase_sensors", label="⚡ Phase Sensors"),
                        selector.SelectOptionDict(value="solar_ev_opts", label="☀️ Solar & EV"),
                        selector.SelectOptionDict(value="features_opts", label="🚀 Features"),
                        selector.SelectOptionDict(value="ai_opts",       label="🤖 AI & NILM"),
                        selector.SelectOptionDict(value="advanced_opts", label="📡 P1 & Advanced"),
                    ], mode="list"))
            }),
        )

    async def async_step_sensors(self, user_input=None):
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})

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
            schema[vol.Optional(CONF_GRID_SENSOR, default=data.get(CONF_GRID_SENSOR, ""))] = _ent()
        else:
            schema[vol.Optional(CONF_IMPORT_SENSOR, default=data.get(CONF_IMPORT_SENSOR, ""))] = _ent()
            schema[vol.Optional(CONF_EXPORT_SENSOR, default=data.get(CONF_EXPORT_SENSOR, ""))] = _ent()
        if phase_count == 3:
            for k in (CONF_MAX_CURRENT_L2, CONF_MAX_CURRENT_L3):
                schema[vol.Optional(k, default=float(data.get(k, DEFAULT_MAX_CURRENT)))] = \
                    vol.All(vol.Coerce(float), vol.Range(min=6, max=63))
        return self.async_show_form(step_id="sensors", data_schema=vol.Schema(schema))

    async def async_step_phase_sensors(self, user_input=None):
        data = self._data()
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})

        schema: dict = {}
        for k in [CONF_PHASE_SENSORS+"_L1", CONF_VOLTAGE_L1, CONF_POWER_L1]:
            schema[vol.Optional(k, default=data.get(k, ""))] = _ent()
        if phase_count == 3:
            for k in [CONF_PHASE_SENSORS+"_L2", CONF_PHASE_SENSORS+"_L3",
                      CONF_VOLTAGE_L2, CONF_VOLTAGE_L3, CONF_POWER_L2, CONF_POWER_L3]:
                schema[vol.Optional(k, default=data.get(k, ""))] = _ent()
        return self.async_show_form(step_id="phase_sensors", data_schema=vol.Schema(schema))

    async def async_step_solar_ev_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
        return self.async_show_form(
            step_id="solar_ev_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_SOLAR_SENSOR,   default=data.get(CONF_SOLAR_SENSOR, "")): _ent(),
                vol.Optional(CONF_BATTERY_SENSOR, default=data.get(CONF_BATTERY_SENSOR, "")): _ent(),
                vol.Optional(CONF_EV_CHARGER_ENTITY, default=data.get(CONF_EV_CHARGER_ENTITY, "")): _ent(["number","input_number"]),
                vol.Optional(CONF_ENABLE_SOLAR_DIMMER, default=bool(data.get(CONF_ENABLE_SOLAR_DIMMER, False))): bool,
                vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=float(data.get(CONF_NEGATIVE_PRICE_THRESHOLD, 0.0))): vol.Coerce(float),
            }),
        )

    async def async_step_features_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
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
        }
        if phase_count == 3:
            schema[vol.Optional(CONF_PHASE_BALANCE, default=bool(data.get(CONF_PHASE_BALANCE, True)))] = bool
            schema[vol.Optional(CONF_PHASE_BALANCE_THRESHOLD, default=float(data.get(CONF_PHASE_BALANCE_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD)))] = \
                vol.All(vol.Coerce(float), vol.Range(min=1, max=20))
        return self.async_show_form(step_id="features_opts", data_schema=vol.Schema(schema))

    async def async_step_ai_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            provider = user_input.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
            user_input[CONF_OLLAMA_ENABLED] = (provider == AI_PROVIDER_OLLAMA)
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
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
            description_placeholders={"premium_url": "https://cloudems.eu/premium"},
        )

    async def async_step_advanced_opts(self, user_input=None):
        data = self._data()
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
        return self.async_show_form(
            step_id="advanced_opts",
            data_schema=vol.Schema({
                vol.Optional(CONF_P1_ENABLED, default=bool(data.get(CONF_P1_ENABLED, False))): bool,
                vol.Optional(CONF_P1_HOST,    default=str(data.get(CONF_P1_HOST, ""))): str,
                vol.Optional(CONF_P1_PORT,    default=int(data.get(CONF_P1_PORT, DEFAULT_P1_PORT))): vol.All(int, vol.Range(min=1, max=65535)),
            }),
        )
