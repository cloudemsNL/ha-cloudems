"""CloudEMS DataUpdateCoordinator — v1.4.1."""
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
)
from .nilm.detector import NILMDetector, DetectedDevice
from .energy.prices import EnergyPriceFetcher
from .energy.limiter import CurrentLimiter
from .energy_manager.power_calculator import PowerCalculator

_LOGGER = logging.getLogger(__name__)

# Max decision log entries kept in memory
MAX_DECISION_LOG = 50
# Clipping detection: if power > peak * this ratio → clipping
CLIPPING_RATIO   = 0.97


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

            # EPEX price info (FIX: get_price_info() now exists)
            price_info: dict = self._prices.get_price_info() if self._prices else {}

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
                for eid, profile in {p.inverter_id: p for p in self._solar_learner.get_all_profiles()}.items():
                    raw = self._read_state(eid)
                    cur_w = self._calc.to_watts(eid, raw) if raw is not None else 0.0
                    peak_w = profile.peak_power_w
                    util   = round(cur_w / peak_w * 100, 1) if peak_w > 0 else 0.0
                    clipping = peak_w > 0 and cur_w >= peak_w * CLIPPING_RATIO

                    if clipping:
                        msg = (f"⚠️ Clipping: {profile.label} produceert {cur_w:.0f}W "
                               f"= {util:.0f}% van max {peak_w:.0f}W — "
                               f"panelen leveren meer dan omvormer aankan")
                        self._log_decision("clipping", msg)

                    inverter_data.append({
                        "entity_id":      eid,
                        "label":          profile.label,
                        "current_w":      round(cur_w, 1),
                        "peak_w":         round(peak_w, 1),
                        "estimated_wp":   round(profile.estimated_wp, 1),
                        "utilisation_pct":util,
                        "clipping":       clipping,
                        "phase":          profile.detected_phase or "unknown",
                        "phase_certain":  profile.phase_certain,
                        "samples":        profile.samples,
                        "confident":      profile.confident,
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
                "nilm_devices":         self._nilm.get_devices_for_ha(),
                "nilm_mode":            self._nilm.active_mode,
                "energy_price":         self._enrich_price_info(price_info),
                "ai_status":            self._build_ai_status(),
                "cost_per_hour":        round(cost_ph, 4),
                "cost_today_eur":       self._cost_today_eur,
                "cost_month_eur":       self._cost_month_eur,
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
            }
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

        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            raw_a = self._read_state(cfg.get(amp_key,""))
            raw_v = self._read_state(cfg.get(volt_key,""))
            raw_p = self._read_state(cfg.get(pwr_key,""))

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

        if not tips:
            tips.append("✅ Alles in orde. Geen bijzonderheden.")

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
