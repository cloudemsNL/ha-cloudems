"""CloudEMS DataUpdateCoordinator — v1.15.5."""
# Copyright (c) 2025 CloudEMS - https://cloudems.eu
# BUG FIXES in v1.4.1:
#   - Added confirm_nilm_device(), dismiss_nilm_device(), async_shutdown() methods
#   - _process_power_data: passes current_a correctly to limiter.update_phase()
#   - _calc_cheap_hours removed (logic now inside prices.get_price_info())
#   - _find_cheapest_window removed (lives in prices.py)
#   - solar_learner.get_profile() None check added
#   - Binary sensor platform registration (in __init__.py)
#   - Insights/advice text generation
#   - Decision log for dimming / switching events
#   - Boiler controller integration
#   - Inverter peak power + clipping detection exposed in data

from __future__ import annotations
import logging
import asyncio
import os
import time
from datetime import timedelta, datetime, timezone
from typing import Dict, List, Optional, Any
from collections import deque

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import (
    CONF_AI_PROVIDER, AI_PROVIDER_NONE, AI_PROVIDER_OLLAMA, AI_PROVIDERS_NEEDING_KEY,
    CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE,
    DOMAIN, UPDATE_INTERVAL_FAST, DEFAULT_MAX_CURRENT, DEFAULT_MAINS_VOLTAGE_V,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_NILM_ENERGY,
    CONF_GRID_SENSOR, CONF_PHASE_SENSORS, CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY,
    CONF_ENERGY_PRICES_COUNTRY, CONF_CLOUD_API_KEY,
    CONF_MAX_CURRENT_PER_PHASE, CONF_ENABLE_SOLAR_DIMMER,
    CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    CONF_PHASE_COUNT, CONF_ENERGY_TAX,
    CONF_DYNAMIC_LOADING, CONF_PHASE_BALANCE, CONF_P1_ENABLED,
    CONF_MAX_CURRENT_L1,
    CONF_INVERTER_CONFIGS, CONF_ENABLE_MULTI_INVERTER,
    CONF_USE_SEPARATE_IE, CONF_IMPORT_SENSOR, CONF_EXPORT_SENSOR,
    CONF_VOLTAGE_L1, CONF_VOLTAGE_L2, CONF_VOLTAGE_L3,
    CONF_POWER_L1, CONF_POWER_L2, CONF_POWER_L3,
    CONF_MAINS_VOLTAGE,
    CONF_OLLAMA_ENABLED, CONF_OLLAMA_HOST, CONF_OLLAMA_PORT, CONF_OLLAMA_MODEL,
    CONF_PEAK_SHAVING_ENABLED, CONF_PEAK_SHAVING_LIMIT_W, CONF_PEAK_SHAVING_ASSETS,
    EPEX_UPDATE_INTERVAL, ALL_PHASES,
    CONF_GAS_SENSOR,
    CONF_BATTERY_CONFIGS, CONF_ENABLE_MULTI_BATTERY,
    CONF_PRICE_INCLUDE_TAX, CONF_PRICE_INCLUDE_BTW, CONF_SUPPLIER_MARKUP, CONF_SELECTED_SUPPLIER,
    ENERGY_TAX_PER_COUNTRY, VAT_RATE_PER_COUNTRY, SUPPLIER_MARKUPS,
    CONF_ENERGY_PRICES_COUNTRY,
)
from .nilm.detector import NILMDetector, DetectedDevice
from .energy_manager.home_baseline import HomeBaselineLearner
from .energy_manager.ev_session_learner import EVSessionLearner
from .energy_manager.nilm_schedule import NILMScheduleLearner
from .energy.prices import EnergyPriceFetcher
from .energy.limiter import CurrentLimiter
from .energy_manager.power_calculator import PowerCalculator
from .energy_manager.notification_engine import NotificationEngine
from .energy_manager.sensor_ema import SensorEMALayer
from .energy_manager.sensor_sanity import SensorSanityGuard
from .energy_manager.absence_detector import AbsenceDetector
from .energy_manager.climate_preheat import ClimatePreHeatAdvisor
from .energy_manager.pv_accuracy import PVForecastAccuracyTracker
from .energy_manager.heat_pump_cop import HeatPumpCOPLearner

_LOGGER = logging.getLogger(__name__)

# Max decision log entries kept in memory
MAX_DECISION_LOG = 50
# Clipping detection: plateau-based (flat top in power curve)
# A rolling window of recent readings per inverter; if stddev < adaptive threshold
# AND power ≈ learned ceiling → clipping detected.
# The ceiling is learned from ClippingLossCalculator.get_learned_ceiling() which
# accumulates actual plateau events — no hardcoded fraction of nominal power.
PLATEAU_WINDOW_SIZE    = 6      # number of readings (~60s at 10s interval)
PLATEAU_STABILITY_PCT  = 0.015  # max stddev/mean allowed when no baseline known (1.5%)
PLATEAU_MIN_FRACTION   = 0.80   # must be at least 80% of seen peak to count
DEFAULT_FEEDIN_EUR_KWH = 0.08   # fallback feed-in tarief als EPEX niet beschikbaar
# How close to the learned ceiling before we call it clipping (when ceiling is known)
CLIPPING_CEILING_FRAC  = 0.985  # within 1.5% of learned ceiling = clipping


class CloudEMSCoordinator(DataUpdateCoordinator):
    """Main coordinator for CloudEMS v1.4.1."""

    def __init__(self, hass: HomeAssistant, config: Dict):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_FAST),
        )
        self._config  = config
        self._session: Optional[aiohttp.ClientSession] = None

        self._store_devices = Store(hass, 1, STORAGE_KEY_NILM_DEVICES)
        self._store_energy  = Store(hass, 1, STORAGE_KEY_NILM_ENERGY)

        model_path = hass.config.path(".storage", "cloudems_models")
        os.makedirs(model_path, exist_ok=True)

        # v1.5: resolve AI provider (new field, with backward-compat fallback)
        ai_provider = config.get(CONF_AI_PROVIDER, AI_PROVIDER_NONE)
        if ai_provider == AI_PROVIDER_NONE and config.get(CONF_OLLAMA_ENABLED, False):
            ai_provider = AI_PROVIDER_OLLAMA  # back-compat upgrade

        ollama_cfg = {
            "enabled": (ai_provider == AI_PROVIDER_OLLAMA),
            "host":    config.get(CONF_OLLAMA_HOST, "localhost"),
            "port":    config.get(CONF_OLLAMA_PORT, 11434),
            "model":   config.get(CONF_OLLAMA_MODEL, "llama3"),
        }

        self._ai_provider = ai_provider
        self._nilm_min_confidence = float(config.get(CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE))

        self._nilm = NILMDetector(
            model_path=model_path,
            api_key=config.get(CONF_CLOUD_API_KEY),
            session=None,
            on_device_found=self._on_nilm_device_found,
            on_device_update=self._on_nilm_device_update,
            ollama_config=ollama_cfg,
            ai_provider=ai_provider,
            hass=hass,
        )
        self._nilm.set_stores(self._store_devices, self._store_energy)

        self._prices: Optional[EnergyPriceFetcher] = None
        self._limiter = CurrentLimiter(
            max_current_per_phase=config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT),
            ev_charger_callback=self._set_ev_current,
            solar_inverter_callback=self._set_solar_curtailment,
        )
        self._calc = PowerCalculator(
            default_voltage=float(config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
        )

        self._prices_last_update: float = 0.0
        self._data: Dict = {}

        # Sub-modules
        self._dynamic_loader    = None
        self._phase_balancer    = None
        self._p1_reader         = None
        self._solar_learner     = None
        self._multi_inv_manager = None
        self._pv_forecast       = None
        self._peak_shaving      = None
        self._boiler_ctrl       = None

        # v1.9: new sub-modules
        self._co2_fetcher:       Optional[object] = None
        self._battery_scheduler:    Optional[object] = None
        self._congestion_detector:  Optional[object] = None
        self._battery_degradation:  Optional[object] = None
        self._sensor_hints:         Optional[object] = None
        self._cost_forecaster:   Optional[object] = None
        # v1.10.3: self-learning intelligence modules
        self._home_baseline:     Optional[object] = None
        self._ev_session:        Optional[object] = None
        self._nilm_schedule:     Optional[object] = None

        # v1.11.0: 8 new intelligence features
        self._thermal_model:     Optional[object] = None
        self._self_consumption:  Optional[object] = None
        self._day_classifier:    Optional[object] = None
        self._device_drift:      Optional[object] = None
        self._pv_health:         Optional[object] = None
        self._micro_mobility:    Optional[object] = None
        self._notification_engine: Optional[object] = None
        self._clipping_loss:     Optional[object] = None
        self._categories:        Optional[object] = None

        # v1.8: EV PID controller
        self._ev_pid: Optional[object] = None
        # v1.8: PID auto-tuner state per controller
        self._phase_pid_tuners: dict = {}
        self._cost_today_eur  = 0.0
        self._cost_month_eur  = 0.0
        self._cost_day_key    = ""
        self._cost_month_key  = ""

        # Decision log (ring buffer)
        self._decision_log: deque = deque(maxlen=MAX_DECISION_LOG)
        # Insights text
        self._insights: str = ""
        # Per-inverter rolling power window for plateau/clipping detection
        self._plateau_windows: dict = {}  # entity_id → deque of float
        # Per-inverter noise baseline: measured stddev/mean when NOT near ceiling.
        # Adapted over time — allows stricter clipping detection on smooth inverters.
        self._noise_baselines: dict = {}  # entity_id → EMA of stability ratio
        # Per-battery learned stats: {sensor_id: {max_charge_w, max_discharge_w, energy_accum_wh}}
        self._battery_learned: dict = {}

        # v1.15.0: new intelligence modules
        self._hp_cop:         Optional[object] = None
        self._sensor_ema:     Optional[object] = None
        self._sensor_sanity:  Optional[object] = None
        self._absence:        Optional[object] = None
        self._preheat:        Optional[object] = None
        self._pv_accuracy:    Optional[object] = None

    # ── Public helpers ────────────────────────────────────────────────────────

    @property
    def nilm(self) -> NILMDetector:
        return self._nilm

    @property
    def phase_currents(self) -> dict[str, float]:
        return self._limiter.phase_currents

    # ── v1.5: Helpers ─────────────────────────────────────────────────────────

    def _enrich_price_info(self, price_info: dict) -> dict:
        """Add prev_hour_price, rank_today and is_cheap_hour to price_info dict."""
        if not price_info or not self._prices:
            return price_info
        # Use today_all from prices.py (already has hour int) if available
        # Fallback: use raw _today_slots() and extract hour via _aware()
        today_all = price_info.get("today_all", [])
        cur = price_info.get("current")

        # Previous hour price — find slot whose hour == (now - 1)
        prev = None
        try:
            from datetime import datetime, timezone
            now    = datetime.now(timezone.utc)
            prev_h = (now.hour - 1) % 24
            if today_all:
                # today_all has "hour" int key (from prices.py v1.6+)
                prev_slot = next((s for s in today_all if s.get("hour") == prev_h), None)
                if prev_slot:
                    prev = prev_slot.get("price")
            else:
                # Fallback to raw slots from _today_slots() using datetime
                for s in self._prices._today_slots():
                    slot_hour = self._prices._aware(s["start"]).hour
                    if slot_hour == prev_h:
                        prev = float(s["price"])
                        break
        except Exception:
            pass

        # Rank of current price among today's hours (1 = cheapest)
        rank = None
        prices_today = [s["price"] for s in today_all] if today_all else []
        if not prices_today:
            prices_today = [float(s["price"]) for s in self._prices._today_slots()]
        if cur is not None and prices_today:
            sorted_prices = sorted(prices_today)
            rank = next((i + 1 for i, p in enumerate(sorted_prices) if p >= cur - 0.0001), None)

        # Is this a cheap hour? (below avg)
        is_cheap = False
        if cur is not None and price_info.get("avg_today") is not None:
            is_cheap = cur < price_info["avg_today"]

        return {
            **price_info,
            "prev_hour_price": prev,
            "rank_today":      rank,
            "is_cheap_hour":   is_cheap,
        }

    def _apply_price_components(self, price_info: dict) -> dict:
        """Add tax/BTW/supplier markup fields to price_info without changing the base EPEX price."""
        cfg     = self._config
        country = cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL")

        include_tax  = bool(cfg.get(CONF_PRICE_INCLUDE_TAX, False))
        include_btw  = bool(cfg.get(CONF_PRICE_INCLUDE_BTW, False))
        supplier_key = cfg.get(CONF_SELECTED_SUPPLIER, "none")
        custom_markup = float(cfg.get(CONF_SUPPLIER_MARKUP, 0.0))

        tax  = ENERGY_TAX_PER_COUNTRY.get(country, 0.0)
        vat  = VAT_RATE_PER_COUNTRY.get(country, 0.21)
        suppliers  = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS["default"])
        sup_markup = suppliers.get(supplier_key, ("", 0.0))[1]
        if supplier_key == "custom":
            sup_markup = custom_markup

        def _enrich(base):
            tax_c   = tax if include_tax else 0.0
            sub     = base + tax_c + sup_markup
            btw_c   = sub * vat if include_btw else 0.0
            all_in  = sub + btw_c
            return round(all_in, 5)

        cur = price_info.get("current")
        today_display = []
        for slot in price_info.get("today_all", []):
            today_display.append({**slot,
                "price_display": _enrich(slot["price"]),
                "price_all_in":  _enrich(slot["price"])})

        return {
            **price_info,
            "tax_per_kwh":         round(tax, 5),
            "vat_rate":            round(vat, 4),
            "supplier_markup_kwh": round(sup_markup, 5),
            "price_include_tax":   include_tax,
            "price_include_btw":   include_btw,
            "country":             country,
            "current_all_in":      _enrich(cur) if cur is not None else None,
            "current_display":     _enrich(cur) if cur is not None else cur,
            "today_all_display":   today_display,
        }


    def _build_ai_status(self) -> dict:
        """Build AI/NILM status dict for the AI Status sensor."""
        devices   = self._nilm.get_devices()
        confirmed = sum(1 for d in devices if getattr(d, "confirmed", False))
        solar_peak_w = 0.0
        solar_profiles = 0
        if self._solar_learner:
            profiles = self._solar_learner.get_all_profiles()
            solar_profiles = len(profiles)
            solar_peak_w   = sum(p.peak_power_w for p in profiles)
        cloud_ai = getattr(self._nilm, "_cloud_ai", None)
        return {
            "call_count":      getattr(cloud_ai, "call_count", 0) if cloud_ai else 0,
            "available":       getattr(cloud_ai, "is_available", True) if cloud_ai else True,
            "min_confidence":  self._nilm_min_confidence,
            "confirmed_count": confirmed,
            "total_devices":   len(devices),
            "solar_profiles":  solar_profiles,
            "solar_peak_w":    round(solar_peak_w, 0),
        }

    def confirm_nilm_device(self, device_id: str, device_type: str, name: str) -> None:
        from .const import NILM_FEEDBACK_CORRECT
        self._nilm.set_feedback(device_id, NILM_FEEDBACK_CORRECT,
                                corrected_name=name, corrected_type=device_type)

    def dismiss_nilm_device(self, device_id: str) -> None:
        self._nilm.dismiss_device(device_id)

    def set_nilm_feedback(self, device_id: str, feedback: str,
                          corrected_name: str = "", corrected_type: str = "") -> None:
        self._nilm.set_feedback(device_id, feedback, corrected_name, corrected_type)

    async def async_shutdown(self) -> None:
        """FIX: Called by __init__.py on unload. Was missing in v1.4.0."""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._p1_reader:
            try:
                await self._p1_reader.async_stop()
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.info("CloudEMS coordinator shut down")

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self):
        self._session = aiohttp.ClientSession()
        self._nilm._cloud_ai._session = self._session
        await self._nilm.async_load()

        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        self._prices = EnergyPriceFetcher(
            country=country,
            session=self._session,
            api_key=self._config.get(CONF_CLOUD_API_KEY),
        )
        await self._prices.update()

        cfg = self._config

        # v1.9: CO2 intensity (always active — uses static defaults without key)
        from .energy.co2 import CO2IntensityFetcher
        self._co2_fetcher = CO2IntensityFetcher(
            country = cfg.get("co2_country", cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL")),
            session = self._session,
        )
        await self._co2_fetcher.update()

        # v1.9: Cost forecaster (always active — self-trains over time)
        from .energy_manager.cost_forecaster import EnergyCostForecaster
        self._cost_forecaster = EnergyCostForecaster(self.hass)
        await self._cost_forecaster.async_setup()

        # v1.10.3: always-on self-learning modules (zero config)
        self._home_baseline = HomeBaselineLearner(self.hass)
        await self._home_baseline.async_setup()

        self._ev_session = EVSessionLearner(self.hass)
        await self._ev_session.async_setup()

        self._nilm_schedule = NILMScheduleLearner(self.hass)
        await self._nilm_schedule.async_setup()

        # v1.11.0: Thermal house model (always active — needs outside_temp + heating power)
        from .energy_manager.thermal_model import ThermalHouseModel
        self._thermal_model = ThermalHouseModel(self.hass)
        await self._thermal_model.async_setup()

        # v1.11.0: Self-consumption ratio tracker
        from .energy_manager.self_consumption import SelfConsumptionTracker
        self._self_consumption = SelfConsumptionTracker(self.hass)
        await self._self_consumption.async_setup()

        # v1.11.0: Day-type classifier
        from .energy_manager.day_classifier import DayTypeClassifier
        self._day_classifier = DayTypeClassifier(self.hass)
        await self._day_classifier.async_setup()

        # v1.11.0: Device efficiency drift tracker
        from .energy_manager.device_drift import DeviceDriftTracker
        self._device_drift = DeviceDriftTracker(self.hass)
        await self._device_drift.async_setup()

        # v1.11.0: PV health monitor (soiling/degradation detection)
        from .energy_manager.pv_health import PVHealthMonitor
        self._pv_health = PVHealthMonitor(self.hass)
        await self._pv_health.async_setup()

        # v1.11.0: Micro-mobility tracker (e-bikes, scooters)
        from .energy_manager.micro_mobility import MicroMobilityTracker
        self._micro_mobility = MicroMobilityTracker(self.hass)
        await self._micro_mobility.async_setup()

        # v1.12.0: Notification engine
        self._notification_engine = NotificationEngine(self.hass, cfg)
        await self._notification_engine.async_setup()

        # v1.12.0: Clipping verlies calculator
        from .energy_manager.clipping_loss import ClippingLossCalculator
        self._clipping_loss = ClippingLossCalculator(self.hass)
        await self._clipping_loss.async_setup()

        # v1.12.0: Verbruik categorieën tracker
        from .energy_manager.consumption_categories import ConsumptionCategoryTracker
        self._categories = ConsumptionCategoryTracker(self.hass)
        await self._categories.async_setup()

        # v1.9: Battery EPEX scheduler (only when battery entities configured)
        if cfg.get("battery_scheduler_enabled", False) or cfg.get("battery_soc_entity"):
            from .energy_manager.battery_scheduler import BatteryEPEXScheduler
            self._battery_scheduler = BatteryEPEXScheduler(self.hass, cfg)
            await self._battery_scheduler.async_setup()

        # v1.10: Grid congestion detector (always active if threshold configured)
        if cfg.get("congestion_threshold_w") or cfg.get("congestion_enabled", True):
            from .energy_manager.grid_congestion import GridCongestionDetector
            self._congestion_detector = GridCongestionDetector(self.hass, cfg)
            await self._congestion_detector.async_setup()

        # v1.10: Battery degradation tracker (active if SoC entity configured)
        if cfg.get("battery_soc_entity"):
            from .energy_manager.battery_degradation import BatteryDegradationTracker
            self._battery_degradation = BatteryDegradationTracker(self.hass, cfg)
            await self._battery_degradation.async_setup()

        # v1.10: NILM remote feed (non-blocking background refresh)
        await self._nilm._db.async_setup(self.hass)
        _LOGGER.info("CloudEMS: BatteryEPEXScheduler actief")

        # v1.10.2: Sensor hint engine (passive pattern observer)
        from .energy_manager.sensor_hint import SensorHintEngine
        self._sensor_hints = SensorHintEngine(self.hass, cfg)
        await self._sensor_hints.async_setup()

        # v1.8: EV PID controller (runs alongside DynamicLoader)
        from .energy_manager.dynamic_ev_charger import EVChargingPIDController
        from .const import (DEFAULT_PID_EV_KP, DEFAULT_PID_EV_KI, DEFAULT_PID_EV_KD,
                            CONF_PID_EV_KP, CONF_PID_EV_KI, CONF_PID_EV_KD,
                            MIN_EV_CURRENT, MAX_EV_CURRENT)
        self._ev_pid = EVChargingPIDController(
            min_a  = MIN_EV_CURRENT,
            max_a  = MAX_EV_CURRENT,
            kp     = float(cfg.get(CONF_PID_EV_KP, DEFAULT_PID_EV_KP)),
            ki     = float(cfg.get(CONF_PID_EV_KI, DEFAULT_PID_EV_KI)),
            kd     = float(cfg.get(CONF_PID_EV_KD, DEFAULT_PID_EV_KD)),
        )
        if cfg.get(CONF_DYNAMIC_LOADING, False):
            self._ev_pid.enable(True)

        if cfg.get(CONF_PHASE_BALANCE, False):
            from .energy_manager.phase_balancer import PhaseBalancer
            self._phase_balancer = PhaseBalancer(self.hass, cfg)

        if cfg.get(CONF_P1_ENABLED, False):
            from .energy_manager.p1_reader import P1Reader
            self._p1_reader = P1Reader(cfg)
            await self._p1_reader.async_start()

        if cfg.get(CONF_PEAK_SHAVING_ENABLED, False):
            from .energy_manager.peak_shaving import PeakShaving
            self._peak_shaving = PeakShaving(self.hass, cfg)
            await self._peak_shaving.async_setup()

        # Boiler controller
        boiler_configs = cfg.get("boiler_configs", [])
        if boiler_configs:
            from .energy_manager.boiler_controller import BoilerController
            self._boiler_ctrl = BoilerController(self.hass, boiler_configs)
            await self._boiler_ctrl.async_setup()
            _LOGGER.info("CloudEMS: BoilerController actief (%d boilers)", len(boiler_configs))

        # Solar Learner + Multi-Inverter + PV Forecast
        inverter_configs = cfg.get(CONF_INVERTER_CONFIGS, [])
        if inverter_configs:
            from .energy_manager.solar_learner import SolarPowerLearner
            self._solar_learner = SolarPowerLearner(self.hass, inverter_configs)
            await self._solar_learner.async_setup()

            if cfg.get(CONF_ENABLE_MULTI_INVERTER, False):
                from .energy_manager.multi_inverter_manager import MultiInverterManager, InverterControl
                controls = [
                    InverterControl(
                        entity_id    =inv["entity_id"],
                        control_entity=inv.get("control_entity", inv["entity_id"]),
                        label        =inv.get("label",""),
                        priority     =int(inv.get("priority",1)),
                        min_power_pct=float(inv.get("min_power_pct",0.0)),
                    ) for inv in inverter_configs
                ]
                max_phase_a = {
                    phase: float(cfg.get(f"max_current_{phase.lower()}", DEFAULT_MAX_CURRENT))
                    for phase in ALL_PHASES
                }
                self._multi_inv_manager = MultiInverterManager(
                    hass=self.hass, entry=None,
                    inverter_controls=controls,
                    learner=self._solar_learner,
                    max_phase_currents=max_phase_a,
                    negative_price_threshold=float(cfg.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)),
                )
                await self._multi_inv_manager.async_setup()

            from .energy_manager.pv_forecast import PVForecast
            self._pv_forecast = PVForecast(
                hass=self.hass,
                inverter_configs=inverter_configs,
                latitude =self.hass.config.latitude  or 52.1,
                longitude=self.hass.config.longitude or 5.3,
                session  =self._session,
            )
            await self._pv_forecast.async_setup()

        # v1.15.0: EMA smoothing + sanity guard (always active)
        self._sensor_ema    = SensorEMALayer()
        self._sensor_sanity = SensorSanityGuard(self._config)
        # v1.15.0: Absence detector + climate preheat advisor
        self._absence = AbsenceDetector(self.hass)
        self._preheat = ClimatePreHeatAdvisor()
        # v1.15.0: PV forecast accuracy tracker
        self._pv_accuracy = PVForecastAccuracyTracker(self.hass)
        await self._pv_accuracy.async_setup()
        # v1.15.0: Heat pump COP learner
        self._hp_cop = HeatPumpCOPLearner(self.hass)
        await self._hp_cop.async_setup()

    # ── Update loop ───────────────────────────────────────────────────────────

    async def _async_update_data(self) -> Dict:
        try:
            data = await self._gather_power_data()
            await self._process_power_data(data)
            await self._limiter.evaluate_and_act()

            if time.time() - self._prices_last_update > EPEX_UPDATE_INTERVAL:
                await self._prices.update()
                self._prices_last_update = time.time()

            if self._config.get(CONF_ENABLE_SOLAR_DIMMER, False):
                threshold = float(self._config.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD))
                is_neg    = self._prices.is_negative_price(threshold) if self._prices else False
                self._limiter.set_negative_price_mode(is_neg)

            current_price = self._prices.current_price if self._prices else 0.0

            # v1.15.0: contract type — dynamic (EPEX) or fixed tariff
            from .const import (CONF_CONTRACT_TYPE, CONTRACT_TYPE_FIXED,
                                DEFAULT_CONTRACT_TYPE, CONF_FIXED_IMPORT_PRICE, CONF_FIXED_EXPORT_PRICE)
            contract_type = self._config.get(CONF_CONTRACT_TYPE, DEFAULT_CONTRACT_TYPE)

            if contract_type == CONTRACT_TYPE_FIXED:
                # Fixed tariff: build synthetic price_info without EPEX
                fixed_import = float(self._config.get(CONF_FIXED_IMPORT_PRICE, 0.25))
                fixed_export = float(self._config.get(CONF_FIXED_EXPORT_PRICE, 0.09))
                import datetime as _dt
                now_h = _dt.datetime.now().hour
                # Flat 24-hour schedule at fixed price
                today_all = [
                    {"hour": h, "price": fixed_import, "is_cheap": True} for h in range(24)
                ]
                price_info = {
                    "current":        fixed_import,
                    "feed_in":        fixed_export,
                    "avg_today":      fixed_import,
                    "today_all":      today_all,
                    "contract_type":  CONTRACT_TYPE_FIXED,
                    "is_cheap_hour":  True,
                }
            else:
                # EPEX price info (FIX: get_price_info() now exists)
                price_info: dict = self._prices.get_price_info() if self._prices else {}
                price_info["contract_type"] = CONTRACT_TYPE_FIXED if contract_type == CONTRACT_TYPE_FIXED else "dynamic"

            # v1.13.0: apply tax/BTW/markup to produce all-in price fields
            price_info = self._apply_price_components(price_info)

            # Dynamic loader (threshold-based, keeps running for price logic)
            ev_decision = {}
            if self._dynamic_loader:
                ev_decision = await self._dynamic_loader.async_evaluate(
                    price_eur_kwh  =current_price,
                    solar_surplus_w=data.get("solar_power", 0.0),
                    max_current_a  =float(self._config.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT)),
                )

            # v1.8: EV PID controller — smooth solar surplus tracking
            ev_pid_state = {}
            if self._ev_pid and self._ev_pid._enabled:
                grid_w  = data.get("grid_power", 0.0)
                new_a   = self._ev_pid.compute(grid_w)
                if new_a is not None:
                    await self._set_ev_current(new_a)
                    self._log_decision("ev_pid",
                        f"🔋 EV PID: {new_a:.1f}A (netto {grid_w:.0f}W)")
                ev_pid_state = self._ev_pid.pid_state

            # Phase balancer
            balance_data = {}
            if self._phase_balancer:
                status = await self._phase_balancer.async_check(self._limiter.phase_currents)
                balance_data = {
                    "imbalance_a":      status.imbalance_a,
                    "balanced":         status.balanced,
                    "overloaded_phase": status.overloaded_phase,
                    "recommendation":   status.recommendation,
                    "phase_currents":   status.phase_currents,
                }

            # P1 reader
            p1_data = {}
            if self._p1_reader and self._p1_reader.available:
                t = self._p1_reader.latest
                p1_data = {
                    "net_power_w":    t.net_power_w,
                    "power_import_w": t.power_import_w,
                    "power_export_w": t.power_export_w,
                    "current_l1": t.current_l1,
                    "current_l2": t.current_l2,
                    "current_l3": t.current_l3,
                    # Tariff-split energy totals (kWh meter readings)
                    "energy_import_kwh":    t.energy_import_kwh,
                    "energy_import_t1_kwh": t.energy_import_t1_kwh,
                    "energy_import_t2_kwh": t.energy_import_t2_kwh,
                    "energy_export_kwh":    t.energy_export_kwh,
                    "energy_export_t1_kwh": t.energy_export_t1_kwh,
                    "energy_export_t2_kwh": t.energy_export_t2_kwh,
                    "tariff": t.tariff,
                    # Per-phase import power (W, DSMR5)
                    "power_l1_import_w": t.power_l1_w,
                    "power_l2_import_w": t.power_l2_w,
                    "power_l3_import_w": t.power_l3_w,
                    # Per-phase export power (W, DSMR5)
                    "power_l1_export_w": t.power_l1_export_w,
                    "power_l2_export_w": t.power_l2_export_w,
                    "power_l3_export_w": t.power_l3_export_w,
                }
                # v1.9: P1 per-phase power → NILM (highest quality input)
                # DSMR5 telegrams include per-phase import power in kW
                # P1Telegram fields: power_l1_import_w, power_l2_import_w, power_l3_import_w
                for ph, attr in (("L1","power_l1_import_w"),("L2","power_l2_import_w"),("L3","power_l3_import_w")):
                    pw = getattr(t, attr, None)
                    if pw is not None and pw >= 0:
                        self._nilm.update_power(ph, pw, source="p1_direct")
                # Also feed per-phase from current × voltage if power not in telegram (DSMR4)
                mains_v = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
                if getattr(t, "current_l1", None) is not None and not getattr(t, "power_l1_import_w", None):
                    for ph, amp in (("L1", t.current_l1),("L2", t.current_l2),("L3", t.current_l3)):
                        if amp is not None:
                            self._nilm.update_power(ph, amp * mains_v, source="p1_i*u")

            # v1.15.1: inject battery directly into NILM (prevents false edge detection)
            batt_configs = self._config.get("battery_configs", [])
            total_battery_w = 0.0
            for bc in batt_configs:
                b_eid = bc.get("power_sensor", "")
                b_raw = self._read_state(b_eid) if b_eid else None
                if b_raw is not None:
                    bw = self._calc.to_watts(b_eid, b_raw)
                    total_battery_w += (bw or 0.0)
            if abs(total_battery_w) > 50:
                self._nilm.inject_battery(total_battery_w, "Thuisbatterij")

            # Solar learner + PV forecast
            inverter_data      = []
            pv_forecast_kwh         = None
            pv_forecast_tomorrow_kwh = None
            pv_forecast_hourly: list = []
            pv_forecast_hourly_tomorrow: list = []
            inverter_profiles:  list = []

            if self._solar_learner:
                await self._solar_learner.async_update(phase_currents=self._limiter.phase_currents)

                # Build inverter data: peak, clipping, utilisation — for sensors/diagnostics
                # Merge pv_forecast orientation data
                forecast_profiles: dict = {}
                if self._pv_forecast:
                    for fp in self._pv_forecast.get_all_profiles():
                        forecast_profiles[fp["inverter_id"]] = fp

                def _azimuth_compass(az):
                    if az is None:
                        return "onbekend"
                    dirs = ["N","NNO","NO","ONO","O","OZO","ZO","ZZO",
                            "Z","ZZW","ZW","WZW","W","WNW","NW","NNW"]
                    return dirs[round(az / 22.5) % 16]

                for eid, profile in {p.inverter_id: p for p in self._solar_learner.get_all_profiles()}.items():
                    raw = self._read_state(eid)
                    cur_w = self._calc.to_watts(eid, raw) if raw is not None else 0.0
                    peak_w = profile.peak_power_w
                    util   = round(cur_w / peak_w * 100, 1) if peak_w > 0 else 0.0

                    # ── Plateau-based clipping detection ─────────────────────
                    # Clipping = inverter output is FLAT at its hardware limit.
                    # Strategy (in priority order):
                    #  1. Use self-learned ceiling from ClippingLossCalculator
                    #     (most accurate: actual observed plateau, not a fraction)
                    #  2. Fall back to rated_power_w from config (if set)
                    #  3. Fall back to peak_power_w_7d (only after 50+ samples,
                    #     conservative fraction to avoid false positives)
                    inv_cfg = next(
                        (c for c in self._config.get(CONF_INVERTER_CONFIGS, []) if c.get("entity_id") == eid),
                        {}
                    )
                    rated_w = inv_cfg.get("rated_power_w") or None

                    # Try to get self-learned ceiling first
                    learned_ceiling_w: Optional[float] = None
                    if self._clipping_loss:
                        learned_ceiling_w = self._clipping_loss.get_learned_ceiling(eid)

                    if learned_ceiling_w:
                        # Best case: use self-learned ceiling
                        clipping_ceiling = learned_ceiling_w
                        clip_frac = CLIPPING_CEILING_FRAC   # within 1.5% of learned ceiling
                        min_samples = 0
                    elif rated_w:
                        # Configured rated power: reliable, allow 5% headroom
                        clipping_ceiling = rated_w
                        clip_frac = 0.95
                        min_samples = 0
                    else:
                        # Learned all-time peak — only use after enough samples
                        clipping_ceiling = profile.peak_power_w_7d
                        clip_frac = 0.98
                        min_samples = 50

                    win = self._plateau_windows.setdefault(eid, deque(maxlen=PLATEAU_WINDOW_SIZE))
                    if cur_w > 0:
                        win.append(cur_w)
                    clipping = False
                    if len(win) >= PLATEAU_WINDOW_SIZE and clipping_ceiling > 100:
                        mean_w = sum(win) / len(win)
                        variance = sum((x - mean_w) ** 2 for x in win) / len(win)
                        stddev_w = variance ** 0.5
                        stability = stddev_w / mean_w if mean_w > 0 else 1.0

                        # Adaptive stability threshold: use per-inverter learned noise
                        # baseline when not near ceiling. Smoother inverters get tighter.
                        baseline_stability = self._noise_baselines.get(eid, PLATEAU_STABILITY_PCT)
                        adaptive_threshold = max(PLATEAU_STABILITY_PCT, baseline_stability * 1.5)

                        if mean_w < clipping_ceiling * 0.70:
                            # Well below ceiling: update noise baseline (EMA)
                            prev = self._noise_baselines.get(eid, stability)
                            self._noise_baselines[eid] = prev * 0.95 + stability * 0.05

                        if (stability < adaptive_threshold
                                and mean_w >= clipping_ceiling * clip_frac
                                and profile.samples >= min_samples):
                            clipping = True

                    if clipping:
                        msg = (f"\u26a0\ufe0f Clipping: {profile.label} produceert {cur_w:.0f}W "
                               f"= {util:.0f}% van max {peak_w:.0f}W \u2014 "
                               f"panelen leveren meer dan omvormer aankan")
                        self._log_decision("clipping", msg)

                    fp = forecast_profiles.get(eid, {})
                    azimuth   = fp.get("azimuth_deg")
                    tilt      = fp.get("tilt_deg")
                    az_learned  = fp.get("learned_azimuth")
                    ti_learned  = fp.get("learned_tilt")
                    or_confident = fp.get("orientation_confident", False)
                    clear_sky_samples = fp.get("clear_sky_samples", 0)
                    samples_needed = fp.get("samples_needed", 30)
                    hourly_yield = fp.get("hourly_yield_fraction", {})
                    learn_pct = round(min(100, clear_sky_samples / 30 * 100), 0)
                    peak_hour = int(max(hourly_yield, key=lambda h: hourly_yield[h])) if hourly_yield else None
                    votes = profile.phase_votes or {}
                    total_votes = sum(votes.values()) if isinstance(votes, dict) else 0

                    inverter_data.append({
                        "entity_id":         eid,
                        "label":             profile.label,
                        "current_w":         round(cur_w, 1),
                        "peak_w":            round(peak_w, 1),
                        "peak_w_7d":         round(profile.peak_power_w_7d, 1),
                        "estimated_wp":      round(profile.estimated_wp, 1),
                        "rated_power_w":     round(rated_w, 0) if rated_w else None,
                        "clipping_ceiling_w":round(clipping_ceiling, 0) if clipping_ceiling else None,
                        "utilisation_pct":   util,
                        "clipping":          clipping,
                        "phase":             profile.detected_phase or "unknown",
                        "phase_certain":     profile.phase_certain,
                        "phase_votes":       profile.phase_votes,
                        "phase_total_votes": total_votes,
                        "samples":           profile.samples,
                        "confident":         profile.confident,
                        "azimuth_deg":       azimuth,
                        "azimuth_learned":   az_learned,
                        "azimuth_compass":   _azimuth_compass(azimuth),
                        "tilt_deg":          tilt,
                        "tilt_learned":      ti_learned,
                        "orientation_confident":      or_confident,
                        "clear_sky_samples":          clear_sky_samples,
                        "orientation_samples_needed": samples_needed,
                        "orientation_learning_pct":   learn_pct,
                        "peak_production_hour":       peak_hour,
                        "hourly_yield_fraction":      hourly_yield,
                    })
            if self._pv_forecast:
                await self._pv_forecast.async_refresh_weather()
                pv_forecast_kwh          = self._pv_forecast.get_total_forecast_today_kwh()
                pv_forecast_tomorrow_kwh = self._pv_forecast.get_total_forecast_tomorrow_kwh()
                inverter_profiles        = self._pv_forecast.get_all_profiles()
                for inv_id in [p["inverter_id"] for p in inverter_profiles]:
                    for hf in self._pv_forecast.get_forecast(inv_id):
                        pv_forecast_hourly.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                        })
                    for hf in self._pv_forecast.get_forecast_tomorrow(inv_id):
                        pv_forecast_hourly_tomorrow.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                        })
                # Feed learner
                for inv in self._config.get(CONF_INVERTER_CONFIGS, []):
                    eid  = inv.get("entity_id","")
                    raw  = self._read_state(eid)
                    if raw is not None:
                        pw = self._calc.to_watts(eid, raw)
                        # FIX: None check on get_profile
                        profile = self._solar_learner.get_profile(eid) if self._solar_learner else None
                        pk = profile.peak_power_w if profile else pw
                        await self._pv_forecast.async_update(eid, pw, pk)

            # Multi-inverter manager
            inv_decisions: list = []
            if self._multi_inv_manager:
                inv_decisions = await self._multi_inv_manager.async_evaluate(
                    phase_currents    =self._limiter.phase_currents,
                    current_epex_price=current_price,
                )
                for d in inv_decisions:
                    if d.action in ("dim_pid","negative_price","dim_full"):
                        self._log_decision("solar_dim",
                            f"🔆 Omvormer {d.label}: {d.action} → {d.target_pct:.0f}% — {d.reason}")

            # Peak shaving
            peak_data = {}
            if self._peak_shaving:
                grid_import_w = max(0.0, data.get("grid_power", 0.0))
                peak_data = await self._peak_shaving.async_evaluate(
                    grid_import_w        =grid_import_w,
                    ev_current_a         =self._limiter.ev_charging_current,
                    solar_curtailment_pct=self._limiter.solar_curtailment_percent,
                )
                if peak_data.get("active"):
                    self._log_decision("peak_shaving",
                        f"📊 Piekafschaving actief: {grid_import_w:.0f}W > {peak_data.get('limit_w',0):.0f}W — {peak_data.get('action','')}")

            # Boiler controller
            boiler_decisions: list = []
            solar_surplus = max(0.0, data.get("solar_power",0) - abs(data.get("grid_power",0)))
            if self._boiler_ctrl:
                boiler_decisions = await self._boiler_ctrl.async_evaluate(
                    price_info         =price_info,
                    solar_surplus_w    =solar_surplus,
                    phase_currents     =self._limiter.phase_currents,
                    phase_max_currents ={
                        ph: self._limiter._phases[ph].max_ampere
                        for ph in self._limiter._phases
                    },
                )
                for bd in boiler_decisions:
                    if bd.action in ("turn_on","turn_off"):
                        self._log_decision("boiler",
                            f"🔌 {bd.label}: {bd.action} — {bd.reason}")

            # Cost tracking
            energy_tax   = float(self._config.get(CONF_ENERGY_TAX, 0.0))
            grid_power_w = p1_data.get("net_power_w") or data.get("grid_power", 0.0)
            cost_ph      = (grid_power_w / 1000.0) * (current_price + energy_tax)

            now_dt   = datetime.now(timezone.utc)
            day_k    = now_dt.strftime("%Y-%m-%d")
            month_k  = now_dt.strftime("%Y-%m")
            if self._cost_day_key   != day_k:   self._cost_today_eur = 0.0;  self._cost_day_key   = day_k
            if self._cost_month_key != month_k: self._cost_month_eur = 0.0;  self._cost_month_key = month_k
            self._cost_today_eur  = round(self._cost_today_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)
            self._cost_month_eur  = round(self._cost_month_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)

            # v1.9: CO2 intensity update (rate-limited internally to 15 min)
            await self._co2_fetcher.update()
            co2_info = self._co2_fetcher.get_info()

            # v1.9: Cost forecaster tick
            await self._cost_forecaster.async_tick(
                power_w       = max(0.0, data.get("grid_power", 0.0)),
                price_eur_kwh = current_price or 0.0,
            )
            cost_forecast = self._cost_forecaster.get_forecast(price_info)
            seasonal_summary = self._cost_forecaster.get_seasonal_summary()

            # v1.10.3: Home baseline anomaly + standby + occupancy (always-on)
            grid_w = data.get("grid_power", 0.0)
            baseline_data = self._home_baseline.update(grid_w) if self._home_baseline else {}

            # v1.10.3: EV session learner (auto-detects sessions from charger current)
            ev_session_data: dict = {}
            if self._ev_session:
                ev_current_a = 0.0
                ev_eid = self._config.get("ev_charger_entity", "")
                if ev_eid:
                    ev_st = self.hass.states.get(ev_eid)
                    if ev_st and ev_st.state not in ("unavailable", "unknown"):
                        try:
                            ev_current_a = float(ev_st.state)
                        except (ValueError, TypeError):
                            ev_current_a = 0.0
                ev_session_data = self._ev_session.update(ev_current_a, current_price or 0.0)

            # v1.10.3: NILM schedule learner (enriches device list with schedule metadata)
            nilm_devices_raw = self._nilm.get_devices_for_ha()
            if self._nilm_schedule:
                nilm_devices_enriched = self._nilm_schedule.update(nilm_devices_raw)
                nilm_schedule_summary = self._nilm_schedule.get_schedule_summary()
            else:
                nilm_devices_enriched = nilm_devices_raw
                nilm_schedule_summary = []

            # v1.10.3: Weather calibration for PV forecast
            weather_calib: dict = {}
            if self._pv_forecast:
                for inv in self._config.get("inverter_configs", []):
                    eid = inv.get("entity_id", "")
                    raw = self._read_state(eid)
                    if raw is not None:
                        pw = self._calc.to_watts(eid, raw)
                        self._pv_forecast.update_weather_calibration(eid, pw)
                weather_calib = self._pv_forecast.get_calibration_summary()

            # ── v1.11.0: NEW INTELLIGENCE FEATURES ──────────────────────────

            # Feature 1: Thermal house model
            thermal_data: dict = {}
            if self._thermal_model:
                outside_temp_eid = self._config.get("outside_temp_entity", "")
                outside_temp_c   = self._read_state(outside_temp_eid) if outside_temp_eid else None
                if outside_temp_c is not None:
                    # Use NILM heating devices or total power as heating proxy
                    heating_w = 0.0
                    for dev in nilm_devices_raw:
                        if dev.get("device_type") in ("heat_pump", "boiler", "cv_boiler", "heat") and dev.get("is_on"):
                            heating_w += float(dev.get("current_power") or 0)
                    if heating_w == 0:
                        # Fallback: use total grid import as rough proxy
                        heating_w = max(0.0, data.get("grid_power", 0.0))
                    self._thermal_model.update(heating_w=heating_w, outside_temp_c=outside_temp_c)
                therm_obj  = self._thermal_model.get_data()
                thermal_data = {
                    "w_per_k":             therm_obj.w_per_k,
                    "samples":             therm_obj.samples,
                    "reliable":            therm_obj.reliable,
                    "rating":              therm_obj.rating,
                    "advice":              therm_obj.advice,
                    "heating_days":        therm_obj.heating_days,
                    "last_heating_w":      therm_obj.last_heating_w,
                    "last_outside_temp_c": therm_obj.last_outside_temp_c,
                }
                await self._thermal_model.async_maybe_save()

            # v1.15.0: Outdoor temp fallback via Open-Meteo when no sensor configured
            outside_temp_eid = self._config.get("outside_temp_entity", "")
            outside_temp_c_val = self._read_state(outside_temp_eid) if outside_temp_eid else None
            if outside_temp_c_val is None and self._thermal_model:
                outside_temp_c_val = await self._thermal_model.async_fetch_outdoor_temp(
                    session=self._session
                )

            # v1.15.0: Heat pump COP update
            hp_cop_data: dict = {}
            if self._hp_cop:
                hp_eid = self._config.get("heat_pump_power_entity", "")
                hp_th_eid = self._config.get("heat_pump_thermal_entity", "")
                hp_electric_w = 0.0
                hp_thermal_w = None
                if hp_eid:
                    raw = self._read_state(hp_eid)
                    if raw is not None:
                        hp_electric_w = self._calc.to_watts(hp_eid, raw)
                else:
                    # Derive from NILM heat pump detections
                    for dev in nilm_devices_raw:
                        if dev.get("device_type") in ("heat_pump", "air_source_heat_pump") and dev.get("running"):
                            hp_electric_w += float(dev.get("current_power") or dev.get("power_w") or 0)
                if hp_th_eid:
                    raw_th = self._read_state(hp_th_eid)
                    if raw_th is not None:
                        hp_thermal_w = self._calc.to_watts(hp_th_eid, raw_th)
                # Get w_per_k from thermal model
                wk_val = thermal_data.get("w_per_k") if thermal_data else None
                indoor_t = self._config.get("indoor_temp_entity", "")
                indoor_c = self._read_state(indoor_t) if indoor_t else None
                cop_result = self._hp_cop.update(
                    electric_w    = hp_electric_w,
                    outdoor_temp_c= outside_temp_c_val,
                    thermal_w     = hp_thermal_w,
                    w_per_k       = wk_val,
                    indoor_temp_c = indoor_c,
                )
                hp_cop_data = {
                    "cop_current":    cop_result.cop_current,
                    "cop_at_7c":      cop_result.cop_at_7c,
                    "cop_at_2c":      cop_result.cop_at_2c,
                    "cop_at_minus5c": cop_result.cop_at_minus5c,
                    "defrost_today":  cop_result.defrost_today,
                    "outdoor_temp_c": cop_result.outdoor_temp_c,
                    "reliable":       cop_result.reliable,
                    "method":         cop_result.method,
                    "curve":          cop_result.curve,
                    "defrost_threshold_c": cop_result.defrost_threshold_c,
                }
                await self._hp_cop.async_maybe_save()

            # Feature 2: Flexible power score
            from .energy_manager.flex_score import calculate_flex_score
            ev_connected      = bool(self._config.get("ev_charger_entity") and data.get("ev_decision"))
            batt_soc          = self._read_state(self._config.get("battery_soc_entity", ""))
            batt_capacity     = float(self._config.get("battery_capacity_kwh", 0) or 0)
            batt_max_kw       = float(self._config.get("battery_max_charge_kw", 0) or 0)
            flex_result       = calculate_flex_score(
                battery_soc_pct      = batt_soc,
                battery_capacity_kwh = batt_capacity or None,
                battery_max_charge_kw= batt_max_kw or None,
                ev_connected         = ev_connected,
                ev_max_charge_kw     = float(self._config.get("ev_max_charge_kw", 7.4) or 7.4),
                ev_session_hours_remaining = float(ev_session_data.get("predicted_duration_h") or 2.0),
                boiler_status        = self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                nilm_devices         = nilm_devices_enriched,
            )
            flex_data = {
                "total_kw":   flex_result.total_kw,
                "battery_kw": flex_result.battery_kw,
                "ev_kw":      flex_result.ev_kw,
                "boiler_kw":  flex_result.boiler_kw,
                "nilm_kw":    flex_result.nilm_kw,
                "breakdown":  flex_result.breakdown,
                "components": [
                    {"source": c.source, "label": c.label, "flex_kw": c.flex_kw, "reason": c.reason}
                    for c in flex_result.components
                ],
            }

            # Feature 3: PV panel health (soiling/degradation)
            pv_health_data: dict = {}
            if self._pv_health and self._solar_learner:
                profiles   = self._solar_learner.get_all_profiles()
                pv_health  = self._pv_health.assess(profiles)
                pv_health_data = {
                    "any_alert": pv_health.any_alert,
                    "summary":   pv_health.summary,
                    "inverters": [
                        {
                            "inverter_id":    s.inverter_id,
                            "label":          s.label,
                            "peak_all_time_w":s.peak_all_time_w,
                            "peak_recent_w":  s.peak_recent_w,
                            "ratio":          s.ratio,
                            "alert":          s.alert,
                            "alert_type":     s.alert_type,
                            "message":        s.message,
                        }
                        for s in pv_health.inverters
                    ],
                }
                await self._pv_health.async_maybe_save()

            # Feature 5: Self-consumption ratio
            self_cons_data: dict = {}
            if self._self_consumption:
                self._self_consumption.tick(
                    pv_w     = max(0.0, data.get("solar_power", 0.0)),
                    import_w = max(0.0, data.get("import_power", data.get("grid_power", 0.0))),
                    export_w = max(0.0, data.get("export_power", 0.0)),
                )
                sc = self._self_consumption.get_data()
                self_cons_data = {
                    "ratio_pct":          sc.ratio_pct,
                    "export_pct":         sc.export_pct,
                    "pv_today_kwh":       sc.pv_today_kwh,
                    "self_consumed_kwh":  sc.self_consumed_kwh,
                    "exported_kwh":       sc.exported_kwh,
                    "best_solar_hour":    sc.best_solar_hour,
                    "best_solar_label":   sc.best_solar_hour_label,
                    "advice":             sc.advice,
                    "monthly_saving_eur": sc.monthly_saving_eur,
                }
                await self._self_consumption.async_maybe_save()

            # Feature 6: Day-type classification
            day_type_data: dict = {}
            if self._day_classifier:
                self._day_classifier.observe_power(max(0.0, data.get("grid_power", 0.0)))
                dt = self._day_classifier.get_data()
                day_type_data = {
                    "today_type":         dt.today_type,
                    "today_label":        dt.today_label,
                    "confidence":         dt.confidence,
                    "expected_kwh":       dt.expected_kwh,
                    "total_days_learned": dt.total_days_learned,
                    "advice":             dt.advice,
                }
                await self._day_classifier.async_maybe_save()

            # Feature 7: Device efficiency drift
            drift_data: dict = {}
            if self._device_drift:
                # Feed current NILM detections
                for dev in nilm_devices_enriched:
                    if dev.get("is_on") and dev.get("current_power"):
                        self._device_drift.record_detection(
                            device_id   = dev.get("device_id", ""),
                            device_type = dev.get("device_type", ""),
                            label       = dev.get("name") or dev.get("label") or dev.get("device_type", ""),
                            power_w     = float(dev.get("current_power", 0)),
                        )
                drift_report = self._device_drift.get_report()
                drift_data = {
                    "any_alert":   drift_report.any_alert,
                    "any_warning": drift_report.any_warning,
                    "summary":     drift_report.summary,
                    "devices": [
                        {
                            "device_id": s.device_id, "label": s.label,
                            "baseline_w": s.baseline_w, "current_w": s.current_w,
                            "drift_pct": s.drift_pct, "level": s.level,
                            "message": s.message,
                        }
                        for s in drift_report.devices
                    ],
                }
                await self._device_drift.async_maybe_save()

            # Feature 8: Phase migration advice
            phase_migration_data: dict = {}
            try:
                from .energy_manager.phase_advisor import generate_migration_advice
                ph_currents = {}
                if self._limiter:
                    ph_summary = self._limiter.get_phase_summary()
                    ph_currents = {
                        ph: info.get("current_a", 0.0)
                        for ph, info in ph_summary.items()
                        if isinstance(info, dict)
                    }
                inv_phases = {}
                if self._solar_learner:
                    for prof in self._solar_learner.get_all_profiles():
                        if prof.phase_certain and prof.detected_phase:
                            inv_phases[prof.inverter_id] = prof.detected_phase
                mig_report = generate_migration_advice(
                    phase_currents  = ph_currents,
                    inverter_phases = inv_phases,
                    nilm_devices    = nilm_devices_enriched,
                )
                phase_migration_data = {
                    "has_advice":      mig_report.has_advice,
                    "summary":         mig_report.summary,
                    "overloaded_phase":mig_report.overloaded_phase,
                    "lightest_phase":  mig_report.lightest_phase,
                    "imbalance_a":     mig_report.imbalance_a,
                    "advices": [
                        {
                            "device_label":     a.device_label,
                            "from_phase":       a.from_phase,
                            "to_phase":         a.to_phase,
                            "current_load_w":   a.current_load_w,
                            "balance_gain_pct": a.balance_gain_pct,
                            "explanation":      a.explanation,
                        }
                        for a in mig_report.advices
                    ],
                }
            except Exception as _pm_err:
                _LOGGER.debug("Phase migration advisor error: %s", _pm_err)
                phase_migration_data = {}

            # ── End v1.11.0 features ─────────────────────────────────────────

            # v1.11.0: Micro-mobility (e-bike/scooter) tracking
            micro_mobility_data: dict = {}
            if self._micro_mobility:
                self._micro_mobility.update(
                    nilm_devices    = nilm_devices_enriched,
                    price_eur_kwh   = current_price or 0.0,
                )
                mm = self._micro_mobility.get_data()
                micro_mobility_data = {
                    "vehicles_today":   mm.vehicles_today,
                    "kwh_today":        mm.kwh_today,
                    "cost_today_eur":   mm.cost_today_eur,
                    "sessions_today":   mm.sessions_today,
                    "active_sessions":  mm.active_sessions,
                    "vehicle_profiles": mm.vehicle_profiles,
                    "best_charge_hour": mm.best_charge_hour,
                    "advice":           mm.advice,
                    "total_sessions":   mm.total_sessions,
                    "total_kwh":        mm.total_kwh,
                    "weekly_kwh_avg":   mm.weekly_kwh_avg,
                }
                await self._micro_mobility.async_maybe_save()

            # v1.12.0: Clipping verlies per omvormer
            clipping_loss_data: dict = {}
            if self._clipping_loss and self._solar_learner:
                try:
                    # Haal PV-forecast op voor estimated_peak (per uur)
                    pv_hourly: dict[str, float] = {}
                    if self._pv_forecast:
                        for hf in getattr(self._pv_forecast, "_hourly_cache", {}).values():
                            pass  # forecast_w beschikbaar via inverter_data
                    feedin_price = float(data.get("energy_price_current_hour", DEFAULT_FEEDIN_EUR_KWH)
                                        if "energy_price_current_hour" in (data or {}) else 0.08)
                    for inv in inverter_data:
                        eid  = inv["entity_id"]
                        # estimated_peak: use learned scale factor if available,
                        # otherwise forecast hourly yield, otherwise all-time peak × factor
                        learned_scale = self._clipping_loss.get_learned_scale_factor(eid)
                        # Prefer forecast-derived estimate if we have hourly yield data
                        fc_est = inv.get("forecast_peak_w", 0.0)
                        if fc_est and fc_est > 0:
                            est_peak = fc_est
                        else:
                            est_peak = inv.get("peak_w", 0.0) * learned_scale
                        self._clipping_loss.tick(
                            inverter_id      = eid,
                            label            = inv.get("label", eid),
                            power_w          = inv.get("current_w", 0.0),
                            estimated_peak_w = est_peak,
                            is_clipping      = bool(inv.get("clipping", False)),
                        )
                    clipping_obj      = self._clipping_loss.get_data(feedin_price_eur_kwh=feedin_price)
                    clipping_loss_data = {
                        "total_kwh_lost_30d":   clipping_obj.total_kwh_lost_30d,
                        "total_eur_lost_year":  clipping_obj.total_eur_lost_year,
                        "inverters":            clipping_obj.inverters,
                        "worst_inverter":       clipping_obj.worst_inverter,
                        "advice":               clipping_obj.advice,
                        "any_curtailment":      clipping_obj.any_curtailment,
                        "expansion_roi_years":  clipping_obj.expansion_roi_years,
                    }
                    await self._clipping_loss.async_maybe_save()
                except Exception as _cl_err:
                    _LOGGER.debug("ClippingLoss error: %s", _cl_err)

            # v1.12.0: Verbruik categorieën
            categories_data: dict = {}
            if self._categories:
                try:
                    standby_w = float((data or {}).get("standby_w", 0.0))
                    self._categories.tick(
                        nilm_devices  = nilm_devices_enriched,
                        standby_w     = standby_w,
                        grid_import_w = float((data or {}).get("grid_import_power", 0.0)),
                    )
                    cat_obj = self._categories.get_data()
                    categories_data = {
                        "top_category":      cat_obj.top_category,
                        "top_category_pct":  cat_obj.top_category_pct,
                        "breakdown_pct":     cat_obj.breakdown_pct,
                        "breakdown_kwh":     cat_obj.breakdown_kwh,
                        "breakdown_w_now":   cat_obj.breakdown_w_now,
                        "total_kwh_today":   cat_obj.total_kwh_today,
                        "total_w_now":       cat_obj.total_w_now,
                        "pie_data":          cat_obj.pie_data,
                        "dominant_insight":  cat_obj.dominant_insight,
                        "avg_breakdown_pct": cat_obj.avg_breakdown_pct,
                    }
                    await self._categories.async_maybe_save()
                except Exception as _cat_err:
                    _LOGGER.debug("ConsumptionCategories error: %s", _cat_err)

            # v1.9: Battery EPEX scheduler
            battery_schedule = {}
            if self._battery_scheduler:
                battery_schedule = await self._battery_scheduler.async_evaluate(
                    price_info      = price_info,
                    solar_surplus_w = solar_surplus,
                )

            # v1.10: Grid congestion detection
            congestion_data: dict = {}
            if self._congestion_detector:
                grid_import_w   = max(0.0, data.get("grid_power", 0.0))
                current_price   = price_info.get("current", 0.0) if price_info else 0.0
                cong_result     = await self._congestion_detector.async_evaluate(
                    grid_import_w  = grid_import_w,
                    price_eur_kwh  = current_price,
                )
                congestion_data = {
                    "active":          cong_result.congestion_active,
                    "import_w":        cong_result.import_w,
                    "threshold_w":     cong_result.threshold_w,
                    "utilisation_pct": cong_result.utilisation_pct,
                    "actions":         cong_result.actions,
                    "today_events":    cong_result.today_events,
                    "month_events":    cong_result.month_events,
                    "peak_today_w":    cong_result.peak_today_w,
                    "monthly_summary": self._congestion_detector.get_monthly_summary(),
                }
                # Propagate congestion state to boiler controller
                if self._boiler_ctrl:
                    self._boiler_ctrl.update_congestion_state(cong_result.congestion_active)
                if cong_result.congestion_active and cong_result.actions:
                    self._log_decision(
                        "congestion",
                        f"⚡ Netcongestie: {cong_result.utilisation_pct:.0f}% benutting "
                        f"— {len(cong_result.actions)} aanbevolen acties"
                    )

            # v1.10: Battery degradation tracking
            degradation_data: dict = {}
            if self._battery_degradation:
                soc_eid  = self._config.get("battery_soc_entity", "")
                soc_val  = self._read_state(soc_eid) if soc_eid else None
                deg_result = self._battery_degradation.update(soc_val)
                degradation_data = {
                    "soh_pct":        deg_result.soh_pct,
                    "capacity_kwh":   deg_result.capacity_kwh,
                    "total_cycles":   deg_result.total_cycles,
                    "cycles_per_day": deg_result.cycles_per_day,
                    "alert_level":    deg_result.alert_level,
                    "alert_message":  deg_result.alert_message,
                    "soc_low_events": deg_result.soc_low_events,
                    "days_tracked":   deg_result.days_tracked,
                }
                await self._battery_degradation.async_save()
                if deg_result.alert_level in ("warn", "critical"):
                    self._log_decision(
                        "battery_health",
                        f"🔋 {deg_result.alert_message}"
                    )

            # v1.10: Update outside temperature for heat demand mode
            outside_temp_eid = self._config.get("outside_temp_entity", "")
            if self._boiler_ctrl and outside_temp_eid:
                outside_temp = self._read_state(outside_temp_eid)
                self._boiler_ctrl.update_outside_temp(outside_temp)

            # v1.10.2: Sensor hint engine — detect unconfigured PV/battery from grid patterns
            sensor_hints: list = []
            if self._sensor_hints:
                cfg = self._config
                has_solar   = bool(cfg.get("solar_sensor", ""))
                has_battery = bool(cfg.get("battery_sensor", ""))
                has_curr_l1 = bool(cfg.get("phase_sensors_L1", ""))
                has_volt_l1 = bool(cfg.get("voltage_sensor_l1", ""))
                has_pwr_l1  = bool(cfg.get("power_sensor_l1", ""))
                hints = self._sensor_hints.update(
                    grid_power_w        = data.get("grid_power", 0.0),
                    has_solar_sensor    = has_solar,
                    has_battery_sensor  = has_battery,
                    has_current_l1      = has_curr_l1,
                    has_voltage_l1      = has_volt_l1,
                    has_power_l1        = has_pwr_l1,
                )
                sensor_hints = self._sensor_hints.get_all_hints()
                for h in hints:
                    self._log_decision(
                        "sensor_hint",
                        f"💡 {h.title}: {h.message[:80]}…"
                    )
                await self._sensor_hints.async_save()

            # v1.15.0: Sanity guard
            sanity_data: dict = {}
            battery_total_w: Optional[float] = None
            if self._config.get(CONF_BATTERY_SENSOR, ""):
                batt_raw = self._read_state(self._config.get(CONF_BATTERY_SENSOR, ""))
                battery_total_w = self._calc.to_watts(
                    self._config.get(CONF_BATTERY_SENSOR, ""), batt_raw
                ) if batt_raw is not None else None
            if self._sensor_sanity:
                phase_c = {}
                if self._limiter:
                    phase_c = {ph: info.get("current_a", 0.0)
                               for ph, info in self._limiter.get_phase_summary().items()
                               if isinstance(info, dict)}
                sanity_result = self._sensor_sanity.update(
                    grid_w    = data.get("grid_power", 0.0),
                    solar_w   = data.get("solar_power", 0.0),
                    battery_w = battery_total_w,
                    phase_currents = phase_c,
                    max_current_a  = float(self._config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT)),
                    phases         = int(self._config.get(CONF_PHASE_COUNT, 1)),
                    mains_v        = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V)),
                )
                sanity_data = {
                    "has_critical": sanity_result.has_critical,
                    "has_warning":  sanity_result.has_warning,
                    "summary":      sanity_result.summary,
                    "issues": [
                        {
                            "code":        getattr(i, "code", ""),
                            "level":       getattr(i, "level", "warning"),
                            "sensor_type": getattr(i, "sensor_type", ""),
                            "entity_id":   getattr(i, "entity_id", ""),
                            "description": getattr(i, "description", ""),
                            "advice":      getattr(i, "advice", ""),
                            "value":       round(getattr(i, "value", 0.0), 2),
                            "expected":    getattr(i, "expected", ""),
                        }
                        for i in sanity_result.issues
                    ],
                }

            # v1.15.0: EMA diagnostics
            ema_diag: dict = {}
            if self._sensor_ema:
                ema_diag = self._sensor_ema.get_diagnostics()

            # v1.15.0: Absence / occupancy detection
            occupancy_data: dict = {}
            if self._absence:
                occ = self._absence.update(data.get("grid_power", 0.0))
                occupancy_data = {
                    "state":         occ.state,
                    "confidence":    occ.confidence,
                    "vacation_hours": occ.vacation_hours,
                    "standby_w":     occ.standby_w,
                    "advice":        occ.advice,
                }

            # v1.15.0: Climate pre-heat advisor
            preheat_data: dict = {}
            if self._preheat:
                avg_p = price_info.get("avg_today") if price_info else None
                cur_p = price_info.get("current")   if price_info else None
                wk    = thermal_data.get("w_per_k") if thermal_data else None
                th_rel = thermal_data.get("reliable", False) if thermal_data else False
                adv = self._preheat.update(
                    current_price    = cur_p,
                    avg_price_today  = avg_p,
                    w_per_k          = wk,
                    thermal_reliable = th_rel,
                )
                preheat_data = {
                    "mode":               adv.mode,
                    "setpoint_offset_c":  adv.setpoint_offset_c,
                    "reason":             adv.reason,
                    "price_ratio":        adv.price_ratio,
                    "w_per_k":            adv.w_per_k,
                    "reliable":           adv.reliable,
                }

            # v1.15.0: PV forecast accuracy tracker
            pv_accuracy_data: dict = {}
            if self._pv_accuracy:
                try:
                    solar_w_now = max(0.0, data.get("solar_power", 0.0))
                    fc_now = sum(h.get("forecast_w", 0) for h in pv_forecast_hourly
                                 if h.get("hour") == __import__("datetime").datetime.now().hour)
                    # Support both tick() and tick_production() across versions
                    if hasattr(self._pv_accuracy, 'tick_production'):
                        self._pv_accuracy.tick_production(pv_w=solar_w_now)
                    else:
                        self._pv_accuracy.tick(actual_w=solar_w_now, forecast_w=fc_now)
                    _acc = self._pv_accuracy.get_data()
                    pv_accuracy_data = {
                        "mape_14d_pct":       _acc.mape_14d,
                        "mape_30d_pct":       _acc.mape_30d,
                        "bias_factor":        _acc.bias_factor,
                        "samples":            _acc.days_with_data,
                        "last_day_mape":      _acc.last_day_error_pct,
                        "quality_label":      _acc.quality_label,
                        "advice":             _acc.advice,
                        "days_tracked":       _acc.days_tracked,
                        "calibration_month":  _acc.calibration_month,
                        "consecutive_over":   _acc.consecutive_over,
                        "consecutive_under":  _acc.consecutive_under,
                        "monthly_bias":       _acc.monthly_bias,
                    }
                    await self._pv_accuracy.async_maybe_save()
                except Exception as _pvacc_err:
                    _LOGGER.warning("CloudEMS: pv_accuracy skipped: %s", _pvacc_err)

            # Generate insights
            self._insights = self._generate_insights(
                data, price_info, inverter_data, peak_data, balance_data,
                self._limiter.phase_currents, solar_surplus, boiler_decisions
            )

            # Save NILM
            await self._nilm.async_save()

            self._data = {
                "grid_power_w":         grid_power_w,
                "power_w":              grid_power_w,
                "solar_power_w":        data.get("solar_power", 0.0),
                "import_power_w":       data.get("import_power", 0.0),
                "export_power_w":       data.get("export_power", 0.0),
                "solar_surplus_w":      solar_surplus,
                "phases":               self._limiter.get_phase_summary(),
                "phase_balance":        balance_data,
                "nilm_devices":         nilm_devices_enriched,
                "nilm_mode":            self._nilm.active_mode,
                "energy_price":         self._enrich_price_info(price_info),
                "ai_status":            self._build_ai_status(),
                "cost_per_hour":        round(cost_ph, 4),
                "cost_today_eur":       self._cost_today_eur,
                "cost_month_eur":       self._cost_month_eur,
                "config_price_alert_high": float(self._config.get("price_alert_high_eur_kwh", 0.30)),
                "config_nilm_confidence":  float(self._config.get("nilm_min_confidence", 0.65)),
                "ev_decision":          ev_decision,
                "p1_data":              p1_data,
                "inverter_data":        inverter_data,          # ← NEW: peak + clipping
                "pv_forecast_today_kwh":     pv_forecast_kwh,
                "pv_forecast_tomorrow_kwh":  pv_forecast_tomorrow_kwh,
                "pv_forecast_hourly":        pv_forecast_hourly,
                "pv_forecast_hourly_tomorrow": pv_forecast_hourly_tomorrow,
                "inverter_profiles":    inverter_profiles,
                "peak_shaving":         peak_data,
                "boiler_status":        self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                "decision_log":         list(self._decision_log),
                "insights":             self._insights,
                "nilm_diagnostics":     self._nilm.get_diagnostics(),  # ← v1.7
                "ev_pid_state":         ev_pid_state,                   # ← v1.8
                "phase_pid_states":     self._get_phase_pid_states(),   # ← v1.8
                "co2_info":             co2_info,                       # ← v1.9
                "cost_forecast":        cost_forecast,                  # ← v1.9
                "battery_schedule":     battery_schedule,               # ← v1.9
                "congestion":           congestion_data,                # ← v1.10
                "battery_degradation":  degradation_data,              # ← v1.10
                "nilm_db_stats":        self._nilm._db.get_stats(),    # ← v1.10
                "sensor_hints":         sensor_hints,                   # ← v1.10.2
                "scale_info":           {eid: self._calc.get_scale_info(eid)
                                         for eid in [
                                             self._config.get("grid_sensor",""),
                                             self._config.get("solar_sensor",""),
                                             self._config.get("battery_sensor",""),
                                         ] if eid},                        # ← v1.10.2
                # v1.10.3: self-learning intelligence
                "baseline":             baseline_data,
                "ev_session":           ev_session_data,
                "nilm_schedule":        nilm_schedule_summary,
                "weather_calibration":  weather_calib,
                "seasonal_summary":     seasonal_summary,
                # v1.11.0: 8 new intelligence features
                "thermal_model":        thermal_data,
                "flex_score":           flex_data,
                "pv_health":            pv_health_data,
                "self_consumption":     self_cons_data,
                "day_type":             day_type_data,
                "device_drift":         drift_data,
                "phase_migration":      phase_migration_data,
                "gas_data":             {
                    "gas_m3":  (self._p1_reader.latest.gas_m3  if self._p1_reader and self._p1_reader.latest else self._read_gas_sensor()),
                    "gas_kwh": (self._p1_reader.latest.gas_kwh if self._p1_reader and self._p1_reader.latest else round((self._read_gas_sensor() or 0.0) * 9.769, 3)),
                },
                "batteries":            self._collect_multi_battery_data(),
                "micro_mobility":       micro_mobility_data,
                "clipping_loss":        clipping_loss_data,
                "consumption_categories": categories_data,
                # v1.15.0: new intelligence
                "heat_pump_cop":    hp_cop_data,
                "sensor_sanity":    sanity_data,
                "ema_diagnostics":  ema_diag,
                "occupancy":        occupancy_data,
                "climate_preheat":  preheat_data,
                "pv_accuracy":      pv_accuracy_data,
                "notifications":        {},  # gevuld na dispatch hieronder
            }

            # v1.12.0: Notification engine — ingest alle alerts en verstuur
            if self._notification_engine:
                try:
                    alert_dict = NotificationEngine.build_alerts_from_coordinator_data(self._data)
                    self._notification_engine.ingest(alert_dict)
                    await self._notification_engine.async_dispatch()
                    self._data["notifications"] = self._notification_engine.get_data()
                    await self._notification_engine.async_maybe_save()
                except Exception as _ne_err:
                    _LOGGER.debug("NotificationEngine error: %s", _ne_err)
            return self._data

        except Exception as exc:
            _LOGGER.exception("CloudEMS coordinator update failed: %s", exc)
            raise UpdateFailed(str(exc)) from exc

    # ── Data gathering ────────────────────────────────────────────────────────

    def _read_state(self, entity_id: str) -> Optional[float]:
        """Read HA state as float. Also feeds unit_of_measurement to the power calculator."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        # Feed UOM to power calculator so kW/W is determined from metadata first
        self._calc.observe_state(entity_id, state)
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _read_gas_sensor(self) -> Optional[float]:
        """Read standalone gas sensor (m³) when P1 reader is not active."""
        entity_id = self._config.get(CONF_GAS_SENSOR, "")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _collect_multi_battery_data(self) -> list:
        """Collect and self-learn stats for all configured batteries."""
        configs = self._config.get(CONF_BATTERY_CONFIGS, [])
        results = []
        for cfg in configs:
            eid = cfg.get("power_sensor", "")
            soc_eid = cfg.get("soc_sensor", "")
            label = cfg.get("label", "Batterij")

            raw_power = self._read_state(eid) if eid else None
            power_w = self._calc.to_watts(eid, raw_power) if raw_power is not None else None
            soc_pct = self._read_state(soc_eid) if soc_eid else None

            # Self-learn max charge/discharge power
            learned = self._battery_learned.setdefault(eid, {
                "max_charge_w": 0.0, "max_discharge_w": 0.0,
                "energy_wh": 0.0, "soc_samples": [],
            })
            if power_w is not None:
                if power_w > 0:
                    learned["max_charge_w"] = max(learned["max_charge_w"], power_w)
                elif power_w < 0:
                    learned["max_discharge_w"] = max(learned["max_discharge_w"], abs(power_w))

            # Use configured values with learned fallbacks
            max_charge_w    = float(cfg.get("max_charge_w", 0)) or learned["max_charge_w"]
            max_discharge_w = float(cfg.get("max_discharge_w", 0)) or learned["max_discharge_w"]
            capacity_kwh    = float(cfg.get("capacity_kwh", 0))

            # Estimate capacity from SoC swing if not configured
            if soc_pct is not None:
                learned["soc_samples"].append(soc_pct)
                if len(learned["soc_samples"]) > 1000:
                    learned["soc_samples"] = learned["soc_samples"][-1000:]
                if not capacity_kwh and len(learned["soc_samples"]) >= 20:
                    soc_range = max(learned["soc_samples"]) - min(learned["soc_samples"])
                    if soc_range > 10 and max_charge_w > 0:
                        # Very rough: assume 1h at half power ≈ half of soc_range % capacity
                        pass  # Better estimation needs energy integration — leave as 0 for now

            results.append({
                "label":            label,
                "entity_id":        eid,
                "power_w":          round(power_w, 1) if power_w is not None else None,
                "soc_pct":          round(soc_pct, 1) if soc_pct is not None else None,
                "capacity_kwh":     capacity_kwh,
                "max_charge_w":     round(max_charge_w, 0),
                "max_discharge_w":  round(max_discharge_w, 0),
                "learned_max_charge_w":    round(learned["max_charge_w"], 0),
                "learned_max_discharge_w": round(learned["max_discharge_w"], 0),
                "charging":         power_w is not None and power_w > 50,
                "discharging":      power_w is not None and power_w < -50,
                "priority":         cfg.get("priority", 1),
            })
        return results

    async def _gather_power_data(self) -> Dict:
        cfg      = self._config
        use_sep  = cfg.get(CONF_USE_SEPARATE_IE, False)

        import_w = export_w = grid_power = None

        if use_sep:
            raw_imp = self._read_state(cfg.get(CONF_IMPORT_SENSOR,""))
            raw_exp = self._read_state(cfg.get(CONF_EXPORT_SENSOR,""))
            if raw_imp is not None:
                import_w = self._calc.to_watts(cfg.get(CONF_IMPORT_SENSOR,""), raw_imp)
            if raw_exp is not None:
                export_w = self._calc.to_watts(cfg.get(CONF_EXPORT_SENSOR,""), raw_exp)
            if import_w is not None and export_w is not None:
                grid_power = import_w - export_w
        else:
            raw_grid = self._read_state(cfg.get(CONF_GRID_SENSOR,""))
            if raw_grid is not None:
                grid_power = self._calc.to_watts(cfg.get(CONF_GRID_SENSOR,""), raw_grid)
            import_w = max(0.0, grid_power or 0.0)
            export_w = max(0.0, -(grid_power or 0.0))

        raw_solar = self._read_state(cfg.get(CONF_SOLAR_SENSOR,""))
        solar_w   = self._calc.to_watts(cfg.get(CONF_SOLAR_SENSOR,""), raw_solar) if raw_solar is not None else 0.0

        # v1.15.0: apply EMA smoothing to delay-prone cloud sensors
        if self._sensor_ema:
            grid_eid  = cfg.get(CONF_GRID_SENSOR, "")
            solar_eid = cfg.get(CONF_SOLAR_SENSOR, "")
            if grid_eid and grid_power is not None:
                grid_power = self._sensor_ema.update(grid_eid, grid_power)
                import_w   = max(0.0, grid_power or 0.0)
                export_w   = max(0.0, -(grid_power or 0.0))
            if solar_eid and solar_w is not None:
                solar_w = self._sensor_ema.update(solar_eid, solar_w) or 0.0

        return {
            "grid_power":   grid_power or 0.0,
            "import_power": import_w   or 0.0,
            "export_power": export_w   or 0.0,
            "solar_power":  solar_w,
        }

    async def _process_power_data(self, data: Dict) -> None:
        """Update per-phase readings; uses P=U*I fallback via PowerCalculator."""
        cfg      = self._config
        mains_v  = float(cfg.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
        phase_count = int(cfg.get(CONF_PHASE_COUNT, 1))
        phases   = ["L1","L2","L3"] if phase_count == 3 else ["L1"]

        phase_conf = {
            "L1": (CONF_PHASE_SENSORS+"_L1", CONF_VOLTAGE_L1, CONF_POWER_L1),
            "L2": (CONF_PHASE_SENSORS+"_L2", CONF_VOLTAGE_L2, CONF_POWER_L2),
            "L3": (CONF_PHASE_SENSORS+"_L3", CONF_VOLTAGE_L3, CONF_POWER_L3),
        }
        # v1.15.0: DSMR5 per-phase export sensors
        # Bidirectionele meters meten teruglevering per fase apart.
        # Netto fase vermogen = import_W − export_W
        from .const import CONF_POWER_L1_EXPORT, CONF_POWER_L2_EXPORT, CONF_POWER_L3_EXPORT
        phase_export_keys = {"L1": CONF_POWER_L1_EXPORT, "L2": CONF_POWER_L2_EXPORT, "L3": CONF_POWER_L3_EXPORT}

        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            raw_a = self._read_state(cfg.get(amp_key,""))
            raw_v = self._read_state(cfg.get(volt_key,""))
            raw_p = self._read_state(cfg.get(pwr_key,""))
            # DSMR5 netto: subtract export if configured
            exp_eid = cfg.get(phase_export_keys.get(ph,""), "")
            if exp_eid and raw_p is not None:
                raw_exp = self._read_state(exp_eid)
                if raw_exp is not None:
                    try:
                        exp_w = self._calc.to_watts(exp_eid, raw_exp)
                        imp_w = self._calc.to_watts(pwr_key, raw_p)
                        raw_p = imp_w - exp_w   # netto (negative = export)
                    except Exception:
                        pass

            resolved = self._calc.resolve_phase(
                ph,
                power_entity=cfg.get(pwr_key,""),
                raw_power   =raw_p,
                raw_current =raw_a,
                raw_voltage =raw_v,
            )

            # FIX: pass current_a and voltage_v separately — don't let limiter recalculate
            self._limiter.update_phase(
                phase       = ph,
                current_a   = resolved.get("current_a") or 0.0,
                power_w     = resolved.get("power_w")   or 0.0,
                voltage_v   = resolved.get("voltage_v") or mains_v,
                derived_from= resolved.get("derived_from","direct"),
            )

            # Feed NILM — v1.8: smart fallback cascade
            #
            # Priority:
            #   1. Per-phase power sensor configured & valid  → best accuracy
            #   2. No phase sensor but total grid available   → split equally per phase
            #   3. Single-phase install                       → total on L1
            #
            # This ensures NILM always gets a meaningful signal even when
            # no per-phase sensors are installed.
            phase_pw = resolved.get("power_w")
            if phase_pw is not None:
                self._nilm.update_power(ph, phase_pw, source="per_phase")
            # (fallback handled below after all phases are processed)

        # v1.8: NILM fallback — if no per-phase power sensors, use total grid
        # Detect how many phases had real data
        phases_with_data = []
        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            if self._read_state(cfg.get(amp_key,"")) is not None or \
               self._read_state(cfg.get(pwr_key,"")) is not None:
                phases_with_data.append(ph)

        if not phases_with_data:
            # No per-phase sensors at all → distribute total grid power
            total_w = data.get("grid_power", 0.0)
            n       = len(phases)
            if n > 1:
                # Equal split — better than nothing; at least the total signature is preserved
                per_phase_w = total_w / n
                for ph in phases:
                    self._nilm.update_power(ph, per_phase_w, source="total_split")
            else:
                # Single phase — send total directly to L1
                self._nilm.update_power("L1", total_w, source="total_l1")

    def _get_phase_pid_states(self) -> dict:
        """Return PID state for all phase controllers (from multi-inverter manager)."""
        if self._multi_inv_manager:
            status = self._multi_inv_manager.get_status()
            return status.get("phase_pids", {})
        return {}

    def _generate_insights(
        self,
        data:           dict,
        price_info:     dict,
        inverter_data:  list,
        peak_data:      dict,
        balance_data:   dict,
        phase_currents: dict,
        solar_surplus:  float,
        boiler_decs:    list,
    ) -> str:
        """
        Generate a human-readable insights/advice string.
        Shown as a text sensor in HA.
        """
        tips: list[str] = []

        price = price_info.get("current")
        if price is not None:
            if price < 0:
                tips.append(f"⚡ Negatieve prijs ({price:.4f} €/kWh): overweeg zware lasten in te schakelen of PV te begrenzen.")
            elif price_info.get("in_cheapest_3h"):
                tips.append(f"💰 Je bent nu in de goedkoopste 3 uur (prijs {price:.4f} €/kWh). Goed moment voor vaatwasser/boiler.")
            elif price > price_info.get("avg_today", 0) * 1.5:
                tips.append(f"💸 Dure stroom: prijs {price:.4f} €/kWh is {((price/max(price_info.get('avg_today',0.001),0.001)-1)*100):.0f}% boven daaggemiddelde.")

        if solar_surplus > 500:
            tips.append(f"☀️ PV-surplus {solar_surplus:.0f}W: zet boiler/EV aan om exportverlies te minimaliseren.")

        for inv in inverter_data:
            if inv.get("clipping"):
                tips.append(f"⚠️ Clipping bij {inv['label']}: {inv['current_w']:.0f}W ≈ max. Panelen leveren meer dan omvormer aankan.")
            elif inv.get("utilisation_pct",0) < 10 and inv.get("confident"):
                pass  # Don't warn about low yield at night

        if peak_data.get("active"):
            tips.append(f"📊 Piekafschaving actief: verbruik {data.get('import_power_w',0):.0f}W > limiet {peak_data.get('limit_w',0):.0f}W.")

        if balance_data.get("imbalance_a", 0) > 5:
            tips.append(f"⚖️ Fase-onbalans: {balance_data.get('imbalance_a',0):.1f}A verschil. Overweeg lasten te herverdelingen.")

        # Startup / learning phase: geen EPEX-data of te weinig data
        if not tips:
            if price_info and price_info.get("current") is not None:
                tips.append("✅ Alles in orde — geen bijzonderheden op dit moment.")
            else:
                tips.append("⏳ CloudEMS leert je installatie kennen. Tips verschijnen zodra EPEX-prijzen beschikbaar zijn.")

        return " | ".join(tips)

    # ── Decision log ──────────────────────────────────────────────────────────

    def _log_decision(self, category: str, message: str) -> None:
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "category": category,
            "message":  message,
        }
        self._decision_log.appendleft(entry)
        _LOGGER.debug("CloudEMS decision [%s]: %s", category, message)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_nilm_device_found(self, device: DetectedDevice, all_matches: list):
        _LOGGER.info("CloudEMS NILM: device found → %s (%.0f%%)", device.name, device.confidence*100)
        self.async_update_listeners()

    def _on_nilm_device_update(self, device: DetectedDevice):
        self.async_update_listeners()

    async def _set_ev_current(self, ampere: float):
        entity_id = self._config.get("ev_charger_entity","")
        if not entity_id:
            return
        await self.hass.services.async_call(
            "number","set_value",{"entity_id": entity_id, "value": ampere}, blocking=False,
        )

    async def _set_solar_curtailment(self, pct: float):
        pass  # Handled by multi_inverter_manager
