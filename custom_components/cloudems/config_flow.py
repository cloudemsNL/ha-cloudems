"""Config flow for CloudEMS — v1.2.0 with auto sensor detection."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import (
    DOMAIN,
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
    CONF_INVERTER_CONFIGS,
    CONF_ENABLE_MULTI_INVERTER,
    DEFAULT_MAX_CURRENT, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    DEFAULT_DYNAMIC_LOAD_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD,
    DEFAULT_P1_PORT,
    EPEX_COUNTRIES,
    PHASE_PRESETS, PHASE_PRESET_LABELS,
    GRID_SENSOR_KEYWORDS,
    PHASE_SENSOR_KEYWORDS_L1, PHASE_SENSOR_KEYWORDS_L2, PHASE_SENSOR_KEYWORDS_L3,
)

_LOGGER = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _preset_selector() -> selector.SelectSelector:
    options = [
        selector.SelectOptionDict(value=k, label=v)
        for k, v in PHASE_PRESET_LABELS.items()
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, mode="list")
    )


def _score_sensor(entity_id: str, keywords: list[str]) -> int:
    """Return a relevance score for an entity_id against a keyword list."""
    name = entity_id.lower()
    return sum(1 for kw in keywords if kw in name)


def _detect_sensors(hass, phase_count: int) -> dict[str, str | None]:
    """
    Scan all HA sensor entities and return best guesses for:
      - grid_sensor
      - phase_sensors_L1 / _L2 / _L3
      - solar_sensor
      - battery_sensor

    Returns a dict of suggested entity_ids (None if not found).
    """
    all_sensors = [
        s.entity_id
        for s in hass.states.async_all("sensor")
        if s.attributes.get("unit_of_measurement") in ("W", "kW", "A")
    ]

    def best(keywords: list[str]) -> str | None:
        scored = [(s, _score_sensor(s, keywords)) for s in all_sensors]
        scored = [(s, sc) for s, sc in scored if sc > 0]
        if not scored:
            return None
        return max(scored, key=lambda x: x[1])[0]

    grid = best(GRID_SENSOR_KEYWORDS)
    l1   = best(PHASE_SENSOR_KEYWORDS_L1) if phase_count >= 1 else None
    l2   = best(PHASE_SENSOR_KEYWORDS_L2) if phase_count == 3 else None
    l3   = best(PHASE_SENSOR_KEYWORDS_L3) if phase_count == 3 else None
    solar = best(["solar", "pv", "zon", "inverter", "omvormer", "yield"])
    battery = best(["battery", "batterij", "accu", "batt", "storage"])

    return {
        CONF_GRID_SENSOR:              grid,
        CONF_PHASE_SENSORS + "_L1":    l1,
        CONF_PHASE_SENSORS + "_L2":    l2,
        CONF_PHASE_SENSORS + "_L3":    l3,
        CONF_SOLAR_SENSOR:             solar,
        CONF_BATTERY_SENSOR:           battery,
    }


# ── Config flow ────────────────────────────────────────────────────────────────

class CloudEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    CloudEMS onboarding wizard (v1.2.0).

    Steps
    -----
    1. user          — Welcome + country
    2. phase_config  — Phase/ampere preset
    2b. phase_custom — Only for 'custom' preset
    3. grid_sensors  — Auto-detected sensors (editable)
    4. solar_ev      — Solar / battery / EV
    5. features      — New v1.2.0 features toggle
    6. advanced      — P1 settings + API key
    """

    VERSION = 1

    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}
        self._suggestions: dict = {}

    # ── Step 1 ─────────────────────────────────────────────────────────────────
    async def async_step_user(self, user_input=None):
        """Welcome + country selection."""
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_phase_config()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ENERGY_PRICES_COUNTRY, default="NL"): vol.In(EPEX_COUNTRIES),
            }),
            description_placeholders={
                "buy_me_coffee": "https://buymeacoffee.com/cloudems",
                "website": "https://cloudems.eu",
            },
        )

    # ── Step 2 ─────────────────────────────────────────────────────────────────
    async def async_step_phase_config(self, user_input=None):
        """Choose a phase/ampere preset."""
        if user_input is not None:
            key = user_input.get(CONF_PHASE_PRESET, "3x25A")
            self._config[CONF_PHASE_PRESET] = key
            if key == "custom":
                return await self.async_step_phase_custom()
            preset = PHASE_PRESETS[key]
            self._config[CONF_PHASE_COUNT]           = preset["count"]
            self._config[CONF_MAX_CURRENT_L1]        = preset["L1"]
            self._config[CONF_MAX_CURRENT_L2]        = preset["L2"]
            self._config[CONF_MAX_CURRENT_L3]        = preset["L3"]
            self._config[CONF_MAX_CURRENT_PER_PHASE] = preset["L1"]
            return await self.async_step_grid_sensors()

        return self.async_show_form(
            step_id="phase_config",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_PRESET, default="3x25A"): _preset_selector(),
            }),
        )

    # ── Step 2b ────────────────────────────────────────────────────────────────
    async def async_step_phase_custom(self, user_input=None):
        """Manual phase count + per-phase ampere."""
        if user_input is not None:
            count = int(user_input.get(CONF_PHASE_COUNT, 3))
            l1 = float(user_input.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))
            self._config[CONF_PHASE_COUNT]           = count
            self._config[CONF_MAX_CURRENT_L1]        = l1
            self._config[CONF_MAX_CURRENT_PER_PHASE] = l1
            self._config[CONF_MAX_CURRENT_L2] = float(user_input.get(CONF_MAX_CURRENT_L2, l1)) if count == 3 else None
            self._config[CONF_MAX_CURRENT_L3] = float(user_input.get(CONF_MAX_CURRENT_L3, l1)) if count == 3 else None
            return await self.async_step_grid_sensors()

        return self.async_show_form(
            step_id="phase_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_PHASE_COUNT, default=3): vol.In({1: "1 fase", 3: "3 fasen"}),
                vol.Required(CONF_MAX_CURRENT_L1, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L2, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
                vol.Optional(CONF_MAX_CURRENT_L3, default=DEFAULT_MAX_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
            }),
        )

    # ── Step 3 ─────────────────────────────────────────────────────────────────
    async def async_step_grid_sensors(self, user_input=None):
        """
        Grid meter + phase sensors.

        Pre-filled with auto-detected suggestions so most users can
        just click Next without touching anything.
        """
        phase_count = self._config.get(CONF_PHASE_COUNT, 3)

        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_solar_ev()

        # Auto-detect on first visit
        if not self._suggestions:
            self._suggestions = _detect_sensors(self.hass, phase_count)
            detected_count = sum(1 for v in self._suggestions.values() if v)
            _LOGGER.info(
                "CloudEMS auto-detection: %d/%d sensors found",
                detected_count, len(self._suggestions),
            )

        s = self._suggestions

        def _entity_sel(suggested: str | None):
            cfg = selector.EntitySelectorConfig(domain="sensor")
            sel = selector.EntitySelector(cfg)
            return sel

        schema_dict: dict = {
            vol.Required(
                CONF_GRID_SENSOR,
                description={"suggested_value": s.get(CONF_GRID_SENSOR)},
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_PHASE_SENSORS + "_L1",
                description={"suggested_value": s.get(CONF_PHASE_SENSORS + "_L1")},
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        }
        if phase_count == 3:
            schema_dict[vol.Optional(
                CONF_PHASE_SENSORS + "_L2",
                description={"suggested_value": s.get(CONF_PHASE_SENSORS + "_L2")},
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
            schema_dict[vol.Optional(
                CONF_PHASE_SENSORS + "_L3",
                description={"suggested_value": s.get(CONF_PHASE_SENSORS + "_L3")},
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))

        return self.async_show_form(
            step_id="grid_sensors",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "phase_count": str(phase_count),
                "detected": str(sum(1 for v in self._suggestions.values() if v)),
            },
        )

    # ── Step 4 ─────────────────────────────────────────────────────────────────
    async def async_step_solar_ev(self, user_input=None):
        """Solar inverter, battery and EV charger."""
        s = self._suggestions

        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_inverters()

        return self.async_show_form(
            step_id="solar_ev",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SOLAR_SENSOR,
                    description={"suggested_value": s.get(CONF_SOLAR_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_BATTERY_SENSOR,
                    description={"suggested_value": s.get(CONF_BATTERY_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(CONF_EV_CHARGER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["number", "input_number"])
                ),
                vol.Optional(CONF_ENABLE_SOLAR_DIMMER, default=False): bool,
                vol.Optional(
                    CONF_NEGATIVE_PRICE_THRESHOLD,
                    default=DEFAULT_NEGATIVE_PRICE_THRESHOLD,
                ): vol.Coerce(float),
            }),
        )


    # ── Step 4b – Multi-inverter (v1.3.0) ─────────────────────────────────────
    async def async_step_inverters(self, user_input=None):
        """
        Configure one or more solar inverters for auto-learning and PID control.
        The user can add 1–4 inverters. Each needs:
          - A power sensor (what CloudEMS reads to learn peak Wp)
          - A control entity (switch or number 0-100% for dimming)
          - A label and priority
        This step is optional — skip with no input to use legacy solar_dimmer only.
        """
        if user_input is not None:
            # Build inverter_configs list from flat form fields
            inverter_configs = []
            for i in range(1, 5):
                eid = user_input.get(f"inverter_{i}_sensor")
                if not eid:
                    break
                inverter_configs.append({
                    "entity_id":      eid,
                    "control_entity": user_input.get(f"inverter_{i}_control", eid),
                    "label":          user_input.get(f"inverter_{i}_label", f"Omvormer {i}"),
                    "priority":       i,
                    "min_power_pct":  float(user_input.get(f"inverter_{i}_min_pct", 0.0)),
                })
            if inverter_configs:
                self._config[CONF_INVERTER_CONFIGS]      = inverter_configs
                self._config[CONF_ENABLE_MULTI_INVERTER] = True
            return await self.async_step_features()

        return self.async_show_form(
            step_id="inverters",
            data_schema=vol.Schema({
                # Inverter 1 (required to enable multi-inverter)
                vol.Optional("inverter_1_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("inverter_1_control"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "number"])
                ),
                vol.Optional("inverter_1_label",  default="Dak Zuid"): str,
                vol.Optional("inverter_1_min_pct", default=0.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=50)
                ),
                # Inverter 2
                vol.Optional("inverter_2_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("inverter_2_control"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "number"])
                ),
                vol.Optional("inverter_2_label", default="Garage"): str,
            }),
            description_placeholders={
                "docs_url": "https://cloudems.eu/docs/multi-inverter",
            },
        )

    # ── Step 5 – New v1.2.0 features ──────────────────────────────────────────
    async def async_step_features(self, user_input=None):
        """
        Enable/disable the new v1.2.0 features.

        Shown as toggles with clear descriptions so users understand
        what they're turning on.
        """
        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_advanced()

        phase_count = self._config.get(CONF_PHASE_COUNT, 1)

        schema_dict: dict = {
            # Dynamic EPEX loader (needs EV charger)
            vol.Optional(CONF_DYNAMIC_LOADING, default=False): bool,
            vol.Optional(
                CONF_DYNAMIC_LOAD_THRESHOLD,
                default=DEFAULT_DYNAMIC_LOAD_THRESHOLD,
            ): vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=1.0)),
            # Cost tracking
            vol.Optional(CONF_COST_TRACKING, default=True): bool,
        }

        # Phase balancer only relevant for 3-phase
        if phase_count == 3:
            schema_dict[vol.Optional(CONF_PHASE_BALANCE, default=True)] = bool
            schema_dict[vol.Optional(
                CONF_PHASE_BALANCE_THRESHOLD,
                default=DEFAULT_PHASE_BALANCE_THRESHOLD,
            )] = vol.All(vol.Coerce(float), vol.Range(min=1, max=20))

        return self.async_show_form(
            step_id="features",
            data_schema=vol.Schema(schema_dict),
        )

    # ── Step 6 ─────────────────────────────────────────────────────────────────
    async def async_step_advanced(self, user_input=None):
        """P1 smart meter + optional CloudEMS API key."""
        if user_input is not None:
            self._config.update(user_input)
            return self.async_create_entry(
                title=self._build_title(),
                data=self._config,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema({
                vol.Optional(CONF_P1_ENABLED, default=False): bool,
                vol.Optional(CONF_P1_HOST): str,
                vol.Optional(CONF_P1_PORT, default=DEFAULT_P1_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(CONF_CLOUD_API_KEY): str,
            }),
            description_placeholders={"premium_url": "https://cloudems.eu/premium"},
        )

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _build_title(self) -> str:
        preset = self._config.get(CONF_PHASE_PRESET, "")
        if preset and preset != "custom":
            return f"CloudEMS ({preset})"
        count = self._config.get(CONF_PHASE_COUNT, "?")
        l1 = self._config.get(CONF_MAX_CURRENT_L1, "?")
        return f"CloudEMS ({count}×{l1} A)"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CloudEMSOptionsFlow(config_entry)


# ── Options flow ────────────────────────────────────────────────────────────────

class CloudEMSOptionsFlow(config_entries.OptionsFlow):
    """Full settings panel — all features editable after setup."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        data = {**self._config_entry.data, **self._config_entry.options}
        phase_count = int(data.get(CONF_PHASE_COUNT, 3))
        errors: dict = {}

        if user_input is not None:
            if int(user_input.get(CONF_PHASE_COUNT, 3)) == 1:
                user_input[CONF_MAX_CURRENT_L2] = None
                user_input[CONF_MAX_CURRENT_L3] = None
            return self.async_create_entry(title="", data=user_input)

        schema: dict = {
            # Phase limits
            vol.Optional(CONF_PHASE_COUNT, default=int(data.get(CONF_PHASE_COUNT, 3))): vol.In({1: "1 fase", 3: "3 fasen"}),
            vol.Optional(CONF_MAX_CURRENT_L1, default=float(data.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))): vol.All(vol.Coerce(float), vol.Range(min=6, max=63)),
        }
        if phase_count == 3:
            schema[vol.Optional(CONF_MAX_CURRENT_L2, default=float(data.get(CONF_MAX_CURRENT_L2, DEFAULT_MAX_CURRENT)))] = vol.All(vol.Coerce(float), vol.Range(min=6, max=63))
            schema[vol.Optional(CONF_MAX_CURRENT_L3, default=float(data.get(CONF_MAX_CURRENT_L3, DEFAULT_MAX_CURRENT)))] = vol.All(vol.Coerce(float), vol.Range(min=6, max=63))
            schema[vol.Optional(CONF_PHASE_BALANCE, default=bool(data.get(CONF_PHASE_BALANCE, True)))] = bool
            schema[vol.Optional(CONF_PHASE_BALANCE_THRESHOLD, default=float(data.get(CONF_PHASE_BALANCE_THRESHOLD, DEFAULT_PHASE_BALANCE_THRESHOLD)))] = vol.All(vol.Coerce(float), vol.Range(min=1, max=20))

        schema.update({
            # Features
            vol.Optional(CONF_DYNAMIC_LOADING,       default=bool(data.get(CONF_DYNAMIC_LOADING, False))): bool,
            vol.Optional(CONF_DYNAMIC_LOAD_THRESHOLD, default=float(data.get(CONF_DYNAMIC_LOAD_THRESHOLD, DEFAULT_DYNAMIC_LOAD_THRESHOLD))): vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=1.0)),
            vol.Optional(CONF_COST_TRACKING,         default=bool(data.get(CONF_COST_TRACKING, True))): bool,
            vol.Optional(CONF_ENABLE_SOLAR_DIMMER,   default=bool(data.get(CONF_ENABLE_SOLAR_DIMMER, False))): bool,
            vol.Optional(CONF_NEGATIVE_PRICE_THRESHOLD, default=float(data.get(CONF_NEGATIVE_PRICE_THRESHOLD, 0.0))): vol.Coerce(float),
            # P1
            vol.Optional(CONF_P1_ENABLED, default=bool(data.get(CONF_P1_ENABLED, False))): bool,
            vol.Optional(CONF_P1_HOST,    default=str(data.get(CONF_P1_HOST, ""))): str,
            vol.Optional(CONF_P1_PORT,    default=int(data.get(CONF_P1_PORT, DEFAULT_P1_PORT))): vol.All(int, vol.Range(min=1, max=65535)),
            # API
            vol.Optional(CONF_CLOUD_API_KEY, default=str(data.get(CONF_CLOUD_API_KEY, ""))): str,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
