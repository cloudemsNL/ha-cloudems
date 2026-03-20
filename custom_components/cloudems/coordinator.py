# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS DataUpdateCoordinator — v1.16.1."""
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

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IDEEËNLIJST — toekomstige features (backlog, niet geïmplementeerd)         │
# ├─────────────────────────────────────────────────────────────────────────────┤
# │                                                                             │
# │  3. NETCONGESTIE VOORSPELLING                                               │
# │     Koppeling Tennet/Enexis congestiekaart. Nieuwe module:                 │
# │     energy_manager/grid_forecast.py                                        │
# │     - Bronnen: Tennet Transparantie API, Enexis GeoJSON, ENTSO-E           │
# │     - ZIP-code → regio mapping voor lokale congestie                       │
# │     - Sensoren: grid_congestion_forecast (none/low/medium/high/critical)   │
# │       grid_congestion_region_active, flex_minutes, next_event              │
# │     - HA-blueprint: EV terugschalen + boiler uit bij congestie             │
# │                                                                             │
# │  4. MAANDRAPPORTAGE PER E-MAIL                                              │
# │     Automatische overzichtsmail via HA notify.                             │
# │     energy_manager/monthly_report.py                                       │
# │     - Data uit HA long-term statistics (netverbruik, kosten, PV, CO2,      │
# │       EV, gas, top-3 apparaten, trend vs vorige maand)                     │
# │     - Service: cloudems.send_monthly_report(month, notify_service)         │
# │     - Talen: NL/EN/DE, optioneel PDF via WeasyPrint                        │
# │     - Weekdigest variant (compacter, elke maandag)                         │
# │                                                                             │
# │  5. ONBOARDING KWALITEITS-SCORE                                             │
# │     Installatiekwaliteit 0-100 voor gebruikersbegeleiding.                 │
# │     energy_manager/installation_score.py                                   │
# │     - Criteria: P1-lezer, fase-sensoren, PV, EV, batterij, gas,            │
# │       EPEX-land, AI-provider, tarieven                                     │
# │     - Sensor: cloudems_installatiescore (0-100, grade A/B/C/D)            │
# │     - Dashboard: cirkel met score, tips, sparkline 30d                    │
# │     - Persistent notification bij score <50                                │
# │                                                                             │
# │  6. TIBBER INTEGRATIE                                                       │
# │     GraphQL API koppeling voor directe prijzen + Pulse meterdata.          │
# │     energy/tibber.py                                                        │
# │     - Bearer token auth, vandaag + morgen prijzen, 7 landen                │
# │     - WebSocket subscription voor Pulse real-time data (1 Hz)              │
# │     - Fetch chain: Tibber → EnergyZero → Awattar → ENTSO-E                │
# │     - Verbruikshistorie 30d voor CostForecaster initialisatie              │
# │                                                                             │
# │  7. BE/FR/NO/SE/DK GRATIS PRIJSBRON                                         │
# │     Gratis EPEX zonder API-sleutel voor meer landen.                       │
# │     Uitbreiding energy/prices.py FREE_SOURCES dict:                        │
# │     - BE: Elia griddata.elia.be (JSON dag-ahead, update 12:30 CET)        │
# │     - FR: RTE digital.iservices.rte-france.com (publiek, geen auth)       │
# │     - NO: Hvakoster.no, SE: Elpriset Just Nu, DK: Energidataservice       │
# │     - Fallback: ENTSO-E voor alle andere landen                            │
# │                                                                             │
# │  8. NILM TIJDPATROON LEREN                                                  │
# │     Detecteer vaste gebruikspatronen per apparaat (bijv. wasmachine        │
# │     altijd di/do/za 10:00). Basis voor slimmere planning en anomalie-      │
# │     detectie ("wasmachine draait midden in de nacht — wie doet dat?").     │
# │     Opslaan als uurhistogram per weekdag in nilm storage.                  │
# │                                                                             │
# │  9. MULTI-TARIEF NACHTLADEN BEWUSTZIJN                                      │
# │     Detecteer automatisch of gebruiker dalttarief heeft (bijv. 23:00-7:00) │
# │     op basis van prijspatronen of handmatige invoer.                       │
# │     Koppelen aan battery_scheduler en EV charger planning.                 │
# │                                                                             │
# └─────────────────────────────────────────────────────────────────────────────┘

from __future__ import annotations
import logging
import asyncio
import os
import time
from datetime import timedelta, datetime, timezone
from typing import Dict, List, Optional, Any
from collections import deque

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .entity_provider import EntityState
from .adaptivehome_bridge import AdaptiveHomeBridge, HouseMode
from .ha_provider import HAEntityProvider
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .watchdog import CloudEMSWatchdog
from .const import (
    CONF_AI_PROVIDER, AI_PROVIDER_NONE, AI_PROVIDER_OLLAMA, AI_PROVIDERS_NEEDING_KEY,
    CONF_NILM_CONFIDENCE, DEFAULT_NILM_CONFIDENCE,
    DOMAIN, UPDATE_INTERVAL_FAST, DEFAULT_MAX_CURRENT, DEFAULT_MAINS_VOLTAGE_V,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_NILM_ENERGY,
    STORAGE_KEY_NILM_TOGGLES, STORAGE_KEY_NILM_REVIEW, STORAGE_KEY_NILM_ADAPTIVE,
    DEFAULT_NILM_ACTIVE, DEFAULT_HYBRID_NILM_ACTIVE, DEFAULT_NILM_HMM_ACTIVE,
    DEFAULT_NILM_BAYES_ACTIVE,
    CONF_GRID_SENSOR, CONF_PHASE_SENSORS, CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY,
    CONF_ENERGY_PRICES_COUNTRY, CONF_CLOUD_API_KEY,
    CONF_MAX_CURRENT_PER_PHASE,
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
    get_net_metering_pct,
    CONF_SHUTTER_COUNT, CONF_SHUTTER_CONFIGS, CONF_SHUTTER_GROUPS,
    CONF_SHUTTER_TEMP_SENSOR, SHUTTER_STORAGE_KEY,
    DSMR_SOURCE_ESPHOME, CONF_DSMR_SOURCE,
    CONF_DSMR_TYPE, DSMR_TYPE_4, DSMR_TYPE_5, DSMR_TYPE_UNIVERSAL,
    DSMR_TYPE_EXPECTED_INTERVAL, DSMR_TYPE_LABELS,
    DSMR_AUTODETECT_FAST_THRESHOLD_S, DSMR_AUTODETECT_SLOW_THRESHOLD_S, DSMR_AUTODETECT_MIN_SAMPLES,
    CONF_ESPHOME_POWER_L1, CONF_ESPHOME_POWER_L2, CONF_ESPHOME_POWER_L3,
    CONF_ESPHOME_POWER_FACTOR_L1, CONF_ESPHOME_POWER_FACTOR_L2, CONF_ESPHOME_POWER_FACTOR_L3,
    CONF_ESPHOME_INRUSH_L1, CONF_ESPHOME_INRUSH_L2, CONF_ESPHOME_INRUSH_L3,
    CONF_ESPHOME_RISE_TIME_L1, CONF_ESPHOME_RISE_TIME_L2, CONF_ESPHOME_RISE_TIME_L3,
    CONF_ESPHOME_REACTIVE_L1, CONF_ESPHOME_REACTIVE_L2, CONF_ESPHOME_REACTIVE_L3,
    CONF_ESPHOME_THD_L1, CONF_ESPHOME_THD_L2, CONF_ESPHOME_THD_L3,
)
from .nilm.detector import NILMDetector, DetectedDevice, STORAGE_KEY_NILM_LEARNER
from .nilm.hybrid_nilm import HybridNILM
from .nilm.appliance_hmm import ApplianceHMMManager
from .nilm.bayesian_classifier import BayesianNILMClassifier
from .energy_manager.home_baseline import HomeBaselineLearner
from .energy_manager.nilm_other_tracker import NilmOtherTracker
from .energy_manager.fault_notifier import FaultNotifier
from .energy_manager.component_merge_advisor import ComponentMergeAdvisor
from .energy_manager.smart_power_estimator import SmartPowerEstimator, STORAGE_KEY as STORAGE_KEY_POWER_ESTIMATOR
from .energy_manager.ev_session_learner import EVSessionLearner
from .energy_manager.nilm_schedule import NILMScheduleLearner
from .energy.prices import EnergyPriceFetcher
from .energy.limiter import CurrentLimiter
from .energy_manager.power_calculator import PowerCalculator
from .energy_manager.notification_engine import NotificationEngine
from .energy_manager.monthly_report import MonthlyReportGenerator
from .energy_manager.installation_score import InstallationScoreCalculator
from .energy_manager.behaviour_coach import BehaviourCoach
from .energy_manager.load_planner import plan_tomorrow, plan_to_dict
from .energy_manager.load_plan_accuracy import LoadPlanAccuracyTracker
from .energy_manager.supplier_compare import derive_actual_tariff
from .energy_manager.energy_label import EnergyLabelSimulator
from .energy_manager.saldering_simulator import SalderingSimulator
from .energy_manager.saldering_context  import SalderingCalibrator
from .energy_manager.battery_savings_tracker import BatterySavingsTracker
from .tariff_fetcher import TariffFetcher
from .energy_manager.sensor_sanity import SensorSanityGuard
from .energy_manager.energy_balancer import EnergyBalancer
from .energy_manager.sensor_interval_registry import SensorIntervalRegistry, SensorSpeed
from .energy_manager.phase_current_fusion import PhaseCurrentFusion
from .energy_manager.kirchhoff_drift_monitor import KirchhoffDriftMonitor
from .energy_manager.phase_power_consistency import PhasePowerConsistencyMonitor
from .energy_manager.inverter_efficiency import InverterEfficiencyTracker
from .energy_manager.tariff_consistency import TariffConsistencyMonitor
from .energy_manager.wiring_topology_validator import WiringTopologyValidator
from .energy_manager.signal_integrity import GridFeedbackLoopDetector, SignConsistencyLearner
from .energy_manager.appliance_health import ApplianceDegradationMonitor, StandbyDriftTracker
from .energy_manager.system_quality import (
    BDEDecisionQualityTracker, ShutterComfortLearner,
    IntegrationLatencyMonitor, P1TelegramQualityMonitor,
)
from .energy_manager.financial_quality import SavingsAttributionTracker, TariffArbitrageQuality
from .energy_manager.topology_consistency import (
    TopologyConsistencyValidator, TopologyAutoFeeder, NILMDoubleCountDetector,
)
from .energy_manager.state_reader import StateReader
from .data_quality_monitor import DataQualityMonitor
from .nilm_group_tracker import NilmGroupTracker
from .energy_manager.absence_detector import AbsenceDetector
from .energy_manager.zone_presence import ZonePresenceManager
from .energy_manager.climate_preheat import ClimatePreHeatAdvisor
from .energy_manager.pv_accuracy import PVForecastAccuracyTracker
from .energy_manager.heat_pump_cop import HeatPumpCOPLearner, COPReport
# v2.6: nieuwe features
from .energy_manager.sleep_detector import SleepDetector
from .energy_manager.device_lifespan import enrich_devices_with_wear
from .energy_manager.capacity_peak import CapacityPeakMonitor
from .energy_manager.tariff_optimizer import NegativeTariffCatcher, ApplianceShiftAdvisor
try:
    from .energy_manager.influxdb_writer import InfluxDBWriter as _InfluxDBWriter
except Exception:
    _InfluxDBWriter = None
from .energy_manager.weekly_insights import WeeklyComparison, BlueprintGenerator
from .energy_manager.wash_cycle import ApplianceCycleManager
from .energy_manager.generator_manager import GeneratorManager
from .energy_manager.lamp_automation import LampAutomationEngine, ROOM_DEFAULT_MODE
from .energy_manager.circuit_monitor import CircuitMonitor
from .energy_manager.ups_manager import UPSManager
from .energy_manager.lamp_automation import LampAutomationEngine
from .energy_manager.smart_climate import SmartClimateManager
from .energy_manager.ebike_manager import EBikeManager
from .energy_manager.ere_manager import EREManager
from .energy_manager.simulator import CloudEMSSimulator

_LOGGER = logging.getLogger(__name__)

# Max decision log entries kept in memory
MAX_DECISION_LOG = 50
# Clipping detection: plateau-based (flat top of the power parabola).
#
# Two-layer detection:
#   Layer 1 — Plateau: last PLATEAU_WINDOW_SIZE readings (≈5 min) are flat.
#             stddev/mean < adaptive threshold AND mean ≥ ceiling × CLIPPING_CEILING_FRAC.
#   Layer 2 — Rising slope: the PLATEAU_PRE_SIZE readings BEFORE the plateau were
#             still rising (pre-window mean < plateau mean × PLATEAU_RISE_MAX_RATIO).
#             This confirms the parabola was cut off, not merely a cloudy plateau.
#
# Ceiling priority:
#   1. rated_power_w from config (most reliable — set by user)
#   2. Self-learned ceiling from ClippingLossCalculator (accumulated real plateaus)
#   3. NO fallback to peak_power_w_7d — that is the already-clipped observed peak,
#      using it as ceiling causes false positives on every clear day.
PLATEAU_WINDOW_SIZE    = 30     # readings in plateau window  (~5 min at 10 s interval)
PLATEAU_PRE_SIZE       = 18     # readings before plateau for slope check (~3 min)
PLATEAU_RISE_MAX_RATIO = 0.97   # pre-window mean must be < plateau_mean * this to confirm rise
PLATEAU_STABILITY_PCT  = 0.015  # max stddev/mean for plateau (1.5 %)
PLATEAU_MIN_FRACTION   = 0.80   # must be at least 80% of seen peak to count
DEFAULT_FEEDIN_EUR_KWH = 0.08   # fallback feed-in tarief als EPEX niet beschikbaar
# How close to the configured/learned ceiling before we call it clipping
CLIPPING_CEILING_FRAC  = 0.95   # within 5% of ceiling — avoids false positives


# ── Climate entity auto-discovery (v2.6) ────────────────────────────────────

# Entiteiten die CloudEMS al zelf aanmaakt — niet in de scan opnemen
_CLOUDEMS_OWN_PREFIXES = ("sensor.cloudems_", "binary_sensor.cloudems_", "climate.cloudems_")

def _detect_climate_type(state) -> str:
    """Herken entiteitstype: vt | trv | airco | switch | unknown."""
    if state is None:
        return "unknown"
    attrs    = state.attributes
    platform = attrs.get("platform", "")
    modes    = set(attrs.get("hvac_modes", []))
    pid      = attrs.get("pid_mode") or attrs.get("preset_mode")
    name     = state.entity_id.lower()

    if "versatile" in platform or "versatile" in name:
        return "vt"
    if modes and modes <= {"heat", "cool", "heat_cool", "off", "auto", "dry", "fan_only"}:
        if "cool" in modes or "dry" in modes or "fan_only" in modes:
            return "airco"
    if attrs.get("min_temp", 5) >= 5 and attrs.get("max_temp", 30) <= 35 and "cool" not in modes:
        t = attrs.get("target_temp_step", 1)
        if t and float(t) <= 0.5:
            return "trv"
    if "heat" in modes and len(modes) <= 3:
        return "trv"
    return "unknown"


def _scan_all_climate_entities(hass) -> dict:
    """Scan alle climate.* entiteiten in HA.

    Groepeert per area (ruimte/verdieping uit HA area registry).
    Geeft voor elke entiteit: naam, type, temps, modus, area — maar GEEN controle.

    Retourneert:
      {
        "by_area": {
          "Woonkamer": [{"entity_id": ..., "name": ..., "type": ..., ...}],
          "Slaapkamer": [...],
          "Onbekend": [...]
        },
        "all": [...],
        "count": n,
      }
    """
    try:
        from homeassistant.helpers import entity_registry as er, area_registry as ar
        ent_reg  = er.async_get(hass)
        area_reg = ar.async_get(hass)
    except Exception:
        ent_reg  = None
        area_reg = None

    by_area: dict[str, list] = {}
    all_entities: list[dict] = {}

    for state in hass.states.async_all("climate"):
        eid = state.entity_id

        # CloudEMS eigen sensoren overslaan
        if any(eid.startswith(p) for p in _CLOUDEMS_OWN_PREFIXES):
            continue

        attrs    = state.attributes
        cur_temp = attrs.get("current_temperature")
        tgt_temp = attrs.get("temperature")
        mode     = state.state   # heat/cool/off/auto etc.
        name     = attrs.get("friendly_name") or eid.split(".")[-1].replace("_", " ").title()

        # Area opzoeken via entity registry
        area_name = "Onbekend"
        if ent_reg and area_reg:
            entry = ent_reg.async_get(eid)
            if entry:
                area_id = entry.area_id
                if not area_id and entry.device_id:
                    # fallback: area van het device
                    from homeassistant.helpers import device_registry as dr
                    dev_reg = dr.async_get(hass)
                    dev = dev_reg.async_get(entry.device_id)
                    if dev:
                        area_id = dev.area_id
                if area_id:
                    area = area_reg.async_get_area(area_id)
                    if area:
                        area_name = area.name

        entity_type = _detect_climate_type(state)

        rec = {
            "entity_id":   eid,
            "name":        name,
            "area":        area_name,
            "type":        entity_type,
            "current_temp":cur_temp,
            "target_temp": tgt_temp,
            "hvac_mode":   mode,
            "hvac_modes":  attrs.get("hvac_modes", []),
            "preset_mode": attrs.get("preset_mode"),
            "preset_modes":attrs.get("preset_modes", []),
        }

        by_area.setdefault(area_name, []).append(rec)
        all_entities[eid] = rec

    # Sorteren: areas alfabetisch, entiteiten per area op naam
    sorted_areas = {k: sorted(v, key=lambda x: x["name"]) for k, v in sorted(by_area.items())}

    return {
        "by_area": sorted_areas,
        "all":     list(all_entities.values()),
        "count":   len(all_entities),
    }



class CloudEMSCoordinator(DataUpdateCoordinator):
    """Main coordinator for CloudEMS v1.4.1."""

    def __init__(self, hass: HomeAssistant, config: Dict):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_FAST),
        )
        self._config      = config
        self._init_mono   = time.monotonic()  # v4.6.587: startup grace period voor health check
        self._session = None  # v4.0.9: HA aiohttp_client sessie
        # v4.0.9: EntityProvider abstractielaag
        self._provider: HAEntityProvider = HAEntityProvider(hass)

        # v4.6.276: AdaptiveHome koppeling — staat onzichtbaar klaar voor koppeling
        self._ah_bridge:        AdaptiveHomeBridge = AdaptiveHomeBridge(hass, self)
        self._ah_house_mode:    str  = HouseMode.HOME
        self._ah_occupied_rooms: list = []
        self._ah_active_scene:  str  = ""
        self._ah_enabled:       bool = False  # wordt True zodra AH een event stuurt

        # v4.6.152: Adaptive performance monitor
        from .performance_monitor import PerformanceMonitor
        self._perf = PerformanceMonitor()

        # Vroeg initialiseren zodat async_shutdown nooit AttributeError geeft
        # ook als __init__ later crasht voordat deze attrs normaal gezet worden
        self._solar_learner      = None
        self._pv_forecast        = None
        self._clipping_loss      = None
        self._shadow_detector    = None
        self._pv_health          = None
        self._device_drift       = None
        self._micro_mobility     = None
        self._notification_engine = None
        self._categories         = None
        # v4.5.0: externe provider manager
        self._provider_manager   = None
        self._cost_forecaster    = None
        self._thermal_model      = None
        self._floor_buffer       = None
        self._ml_forecaster      = None
        self._self_consumption   = None
        self._day_classifier     = None
        self._pv_accuracy        = None
        self._simulator          = None  # v4.2.1: vroeg init — voorkomt AttributeError als async_setup halverwege crasht

        # Watchdog — bewaakt crashes en herstart automatisch
        # entry_id wordt ingevuld via async_setup() zodra de config entry bekend is
        self._watchdog: Optional[CloudEMSWatchdog] = None

        # v4.6.445: Lamp Automation Engine
        self._lamp_auto: Optional[LampAutomationEngine] = None

        # v4.6.432: Generator / ATS state
        self._generator_active:   bool  = False   # True = draait op generator
        self._generator_power_w:  float = 0.0
        self._ats_last_notified:  float = 0.0     # timestamp laatste MTS-melding
        self._gen_autostart_sent: bool  = False   # auto-start commando verstuurd

        self._store_devices = Store(hass, 1, STORAGE_KEY_NILM_DEVICES)
        self._store_energy  = Store(hass, 1, STORAGE_KEY_NILM_ENERGY)
        self._store_learner = Store(hass, 1, STORAGE_KEY_NILM_LEARNER)
        # v4.5.51: Meter topologie (upstream leren)
        self._store_topo    = Store(hass, 1, "cloudems_meter_topology_v1")
        # v4.5.7: EnergyBalancer lag-leren persistentie
        self._store_balancer = Store(hass, 1, "cloudems_energy_balancer_v1")
        # v4.3.26: SmartPowerEstimator (ingebouwde PowerCalc)
        self._power_estimator: Optional[SmartPowerEstimator] = None
        self._store_power_estimator = Store(hass, 1, STORAGE_KEY_POWER_ESTIMATOR)
        # v1.22: persistente NILM-schakelaar staat
        self._store_toggles = Store(hass, 1, STORAGE_KEY_NILM_TOGGLES)
        # v2.4.17: persistente review-history en adaptieve drempels
        self._store_review   = Store(hass, 1, STORAGE_KEY_NILM_REVIEW)
        self._store_adaptive = Store(hass, 1, STORAGE_KEY_NILM_ADAPTIVE)
        # v4.0.4: tijdpatroon store
        from .nilm.time_pattern_learner import STORAGE_KEY_TIME_PATTERNS as _SKEY_TP
        self._store_time_patterns = Store(hass, 1, _SKEY_TP)
        # v4.5: co-occurrence store
        self._store_co_occurrence = Store(hass, 1, "cloudems_nilm_co_occurrence_v1")
        # v4.6.484: realtime kWh tellers voor altijd-aan apparaten (smart_plug/anchor)
        self._store_anchor_kwh   = Store(hass, 1, "cloudems_anchor_kwh_v1")
        self._store_pv_hourly    = Store(hass, 1, "cloudems_pv_hourly_v1")  # v4.6.493
        self._anchor_kwh_today:     dict[str, float] = {}   # device_id → kWh vandaag
        self._anchor_kwh_yesterday: dict[str, float] = {}   # device_id → kWh gisteren
        self._anchor_kwh_day:       str = ""                # YYYY-MM-DD van huidige dag
        self._anchor_kwh_last_save: float = 0.0
        # v4.6.492: per-uur solar kWh accumulatie (persistent over page-reload)
        self._pv_today_hourly_kwh:  list = [0.0] * 24  # index = uur (0-23)
        self._pv_hourly_day:        str = ""            # YYYY-MM-DD voor dag-reset
        self._pv_hourly_last_hour:  int = -1            # vorig uur voor afsluiting
        # v4.0.1: ExportDailyTracker — persistente dagelijkse export-kWh history
        from .energy_manager.export_limit_monitor import (
            ExportDailyTracker, ExportLimitMonitor,
            STORAGE_KEY_EXPORT_HISTORY,
        )
        self._export_tracker  = ExportDailyTracker(
            Store(hass, 1, STORAGE_KEY_EXPORT_HISTORY)
        )
        self._export_monitor  = ExportLimitMonitor()
        # v4.0.5: Gas predictor
        from .energy_manager.gas_predictor import GasPredictor as _GP, STORAGE_KEY_GAS_PREDICTOR as _SKEY_GP
        self._gas_predictor = _GP(Store(hass, 1, _SKEY_GP))
        self._gas_prediction: dict = {}
        # v4.6.387: Gas meterstand ringbuffer — persists op HA server (cross-device)
        self._store_gas_ring = Store(hass, 1, "cloudems_gas_ring_v1")
        self._gas_ring: list = []   # [{ts: int (ms), val: float (m3)}, ...]
        self._GAS_RING_MAX  = 3000  # max punten (~25u @ 30s interval)
        self._GAS_RING_TTL  = 25 * 3600 * 1000  # 25 uur in ms
        self._gas_dhw_hint_sent: str = ""  # datum van laatste DHW-hint notificatie (YYYY-MM-DD)
        # v4.6.574: geleerde maximale gasflow — EMA, seed wordt direct overschreven door metingen
        # Seed: 3.0 m³/u — typisch max voor combi-ketel, vervangen door echte piekwaarden
        _GAS_RATE_MAX_SEED_M3H = 3.0
        self._gas_rate_max_m3h: float = _GAS_RATE_MAX_SEED_M3H
        self._GAS_RATE_EMA_ALPHA: float = 0.05  # traag leren — pieken zijn zeldzaam
        # v4.0.5: Tariefwijziging detector
        from .energy_manager.tariff_change_detector import TariffChangeDetector as _TCD, STORAGE_KEY_TARIFF_DETECTOR as _SKEY_TC
        self._tariff_detector = _TCD(Store(hass, 1, _SKEY_TC), config)
        self._tariff_change: dict = {}
        # v4.0.5: Batterij efficiëntie tracker
        from .energy_manager.battery_efficiency import BatteryEfficiencyTracker as _BET, STORAGE_KEY_BATTERY_EFF as _SKEY_BE
        self._battery_eff = _BET(Store(hass, 1, _SKEY_BE))
        self._battery_eff_status: dict = {}
        # v4.0.4: BDE Feedback loop
        from .energy_manager.bde_feedback import BDEFeedbackTracker as _BDEF, STORAGE_KEY_BDE_FEEDBACK as _SKEY_BDF
        self._bde_feedback = _BDEF(Store(hass, 1, _SKEY_BDF))
        # v4.5.66: BatterySocLearner — zelflerend SOC / capaciteit / vermogen
        from .energy_manager.battery_soc_learner import BatterySocLearner as _BSL, STORAGE_KEY_SOC_LEARNER as _SKEY_BSL
        self._battery_soc_learner = _BSL(Store(hass, 1, _SKEY_BSL))
        # v4.0.4: OffPeakDetector — dal/piek tarief detectie
        from .energy_manager.off_peak_detector import OffPeakDetector as _OPD
        self._off_peak_detector = _OPD()
        self._off_peak_status:  dict = {}
        # v4.0.2: BatteryDecisionEngine — één instantie
        from .energy_manager.battery_decision_engine import BatteryDecisionEngine as _BDE
        self._battery_decision_engine = _BDE()
        # v4.6.498: Decision Outcome Learner — na BDE aanmaken zodat set_learner() werkt
        from .energy_manager.decision_outcome_learner import DecisionOutcomeLearner as _DOL
        self._decision_learner = _DOL(self.hass)
        self._battery_decision_engine.set_learner(self._decision_learner)
        # adaptive thresholds per device_type: {type: {min_events, confidence, fp_count, tp_count}}
        self._adaptive_thresholds: dict = {}
        self._nilm_active:        bool = DEFAULT_NILM_ACTIVE
        self._hybrid_nilm_active: bool = DEFAULT_HYBRID_NILM_ACTIVE
        self._nilm_hmm_active:    bool = DEFAULT_NILM_HMM_ACTIVE
        self._nilm_bayes_active:  bool = DEFAULT_NILM_BAYES_ACTIVE
        # v3.9: slaapstand persistentie — wordt overschreven door _load_nilm_toggles()
        self._sleep_detector_enabled: bool = config.get("sleep_detector_enabled", False)
        self._hmm:   Optional[ApplianceHMMManager]    = None
        self._bayes: Optional[BayesianNILMClassifier] = None

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

        # v1.16: Ollama health-check state
        self._ollama_cfg = ollama_cfg
        self._ollama_health: dict = {
            "status": "unknown",
            "models_available": [],
            "active_model_found": False,
            "last_check_ts": None,
            "last_error": None,
        }
        self._ollama_health_last_check: float = 0.0

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
        self._nilm.set_stores(self._store_devices, self._store_energy, self._store_learner, self._store_time_patterns, store_co_occurrence=self._store_co_occurrence)

        # v1.20: vertel NILM welke entity_ids geconfigureerde infrastructure-sensoren zijn
        # zodat die nooit als huishoudapparaat worden geclassificeerd.
        _config_eids: set = set()
        for _key in (
            "grid_sensor", "solar_sensor", "battery_sensor", "battery_soc_entity",
            "import_power_sensor", "export_power_sensor",
            "power_sensor_l1", "power_sensor_l2", "power_sensor_l3",
            "voltage_sensor_l1", "voltage_sensor_l2", "voltage_sensor_l3",
            "phase_sensors_L1", "phase_sensors_L2", "phase_sensors_L3",
            "gas_sensor", "gas_price_sensor",
            "heat_pump_power_entity", "heat_pump_thermal_entity",
            "ev_charger_entity",
        ):
            _v = config.get(_key, "")
            if _v:
                _config_eids.add(_v)
        for _inv in config.get("inverter_configs", []):
            if _inv.get("entity_id"):
                _config_eids.add(_inv["entity_id"])
        for _bc in config.get("battery_configs", []):
            for _bk in ("power_sensor", "soc_sensor", "charge_sensor", "discharge_sensor"):
                if _bc.get(_bk):
                    _config_eids.add(_bc[_bk])

        # v2.4.15: Robuuste uitbreiding van _config_sensor_eids — drie lagen:
        #
        # Laag 1 — HA-device siblings: alle entiteiten van hetzelfde HA-device als
        #   een geconfigureerde sensor worden automatisch uitgesloten. Dit pakt alle
        #   afgeleide sensoren van bijv. Zonneplan/DSMR taalongafhankelijk.
        #
        # Laag 2 — Energie-integraties: entiteiten waarvan de config_entry domain
        #   een bekende energiemeter- of energieleverancier-integratie is worden
        #   nooit gescand als apparaat (ongeacht naam of eenheid).
        #
        # Laag 3 — kWh-sensoren: state_class=total_increasing of device_class=energy
        #   zijn nooit bruikbaar als NILM-vermogenssignaal.
        #
        # Bekende energiemeter/leverancier-integraties (taalongafhankelijk):
        _ENERGY_METER_DOMAINS = frozenset({
            # DSMR / P1
            "dsmr", "dsmr_reader", "p1_monitor", "dsmr_parser",
            # Slimme meters / energiemeters
            "homewizard", "homewizard_energy",
            "enelogic", "youless", "volksthuis", "easyenergy",
            "zonneplan", "tibber", "eneco", "vattenfall", "oxxio",
            "n2g_ems", "itho_daalderop",
            # Groene stroom / leveranciers met eigen integratie
            "essent", "greenchoice", "budget_energie",
            # Omvormers / PV (mochten ze toch in de NILM belanden)
            "growatt_local", "goodwe", "solaredge", "fronius",
            "enphase_envoy", "sma", "huawei_solar",
            # Generieke energie-aggregatoren
            "energy_dashboard", "powerwall",
        })

        try:
            from homeassistant.helpers import entity_registry as _er_mod
            _er = _er_mod.async_get(self.hass)

            # Laag 1: siblings van geconfigureerde HA-devices
            _device_ids: set = set()
            for _eid in set(_config_eids):
                _entry = _er.async_get(_eid)
                if _entry and _entry.device_id:
                    _device_ids.add(_entry.device_id)
            for _e in _er.entities.values():
                if _e.device_id and _e.device_id in _device_ids:
                    _config_eids.add(_e.entity_id)

            # Laag 2 + 3: energie-integraties en kWh-sensoren
            for _e in _er.entities.values():
                if _e.domain != "sensor":
                    continue
                # Laag 2: bekende energie-integratie domain
                if _e.platform in _ENERGY_METER_DOMAINS:
                    _config_eids.add(_e.entity_id)
                    continue
                # Laag 3: kWh / energietellers
                _state = self._safe_state(_e.entity_id)
                if _state is None:
                    continue
                _sc = _state.attributes.get("state_class", "")
                _dc = _state.attributes.get("device_class", "")
                _unit = (_state.attributes.get("unit_of_measurement") or "").lower()
                _fname = (_state.attributes.get("friendly_name") or _e.entity_id).lower()
                if (
                    # kWh/energie-tellers
                    _sc in ("total_increasing", "total")
                    or _dc == "energy"
                    or _unit in ("kwh", "wh", "mwh", "gj", "m³", "m3")
                    # v4.4: vermogenssensoren (W) zijn ook geen NILM-verbruikers
                    or (_dc == "power" and _unit == "w")
                    # v4.4: naam-gebaseerde keyword-filter als laatste vangnet
                    # Pakt "Stroom tegen uurprijzen", "Connect energiemeter", enz.
                    or any(kw in _fname for kw in (
                        "energiemeter", "energy meter", "stroomprijs", "uurprijs",
                        "stroom tegen", "elektriciteitsgemiddelde",
                        "elektriciteitsverbruik", "elektriciteitsproductie",
                        "connect energi", "slimme meter", "p1 meter",
                        "net import", "net export", "grid import", "grid export",
                        "solar production", "pv productie",
                    ))
                ):
                    _config_eids.add(_e.entity_id)

            # Laag 4: HA-area "CloudEMS Exclude" — verplaats device naar deze
            #   kamer in HA om het uit te sluiten van NILM en device-tracking.
            #   Werkt direct, geen herstart nodig.
            try:
                from homeassistant.helpers import area_registry as _ar_mod, device_registry as _dr_mod
                _ar = _ar_mod.async_get(self.hass)
                _dr = _dr_mod.async_get(self.hass)
                _EXCLUDE_AREA = "cloudems exclude"
                _excl_area = next(
                    (a for a in _ar.async_list_areas()
                     if a.name.lower().strip() == _EXCLUDE_AREA),
                    None,
                )
                if _excl_area:
                    _excl_device_ids: set = {
                        d.id for d in _dr.devices.values()
                        if d.area_id == _excl_area.id
                    }
                    _excl_count_before = len(_config_eids)
                    for _e in _er.entities.values():
                        if _e.device_id and _e.device_id in _excl_device_ids:
                            _config_eids.add(_e.entity_id)
                        elif _e.area_id == _excl_area.id:
                            _config_eids.add(_e.entity_id)
                    _excl_added = len(_config_eids) - _excl_count_before
                    if _excl_added:
                        _LOGGER.info(
                            "CloudEMS NILM: %d entiteit(en) uitgesloten via "
                            "HA-area 'CloudEMS Exclude'",
                            _excl_added,
                        )
            except Exception as _excl_err:
                _LOGGER.debug("CloudEMS: area-exclude ophalen mislukt: %s", _excl_err)

            _LOGGER.debug(
                "CloudEMS NILM: %d entiteiten uitgesloten als infra/energie-sensor",
                len(_config_eids),
            )
        except Exception as _ex:
            _LOGGER.warning("CloudEMS: uitbreiding config_sensor_eids mislukt: %s", _ex)

        self._nilm.set_config_sensor_eids(_config_eids)

        # v2.4.19: geef ook de friendly names door zodat naam-gebaseerde filter werkt
        try:
            _blocked_names: set = set()
            for _eid in _config_eids:
                _st = self._safe_state(_eid)
                if _st:
                    _fname = _st.attributes.get("friendly_name") or ""
                    if _fname:
                        _blocked_names.add(_fname)
            if _blocked_names:
                self._nilm.set_blocked_friendly_names(_blocked_names)
        except Exception as _bn_err:
            _LOGGER.debug("CloudEMS: blocked_friendly_names ophalen mislukt: %s", _bn_err)

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
        self._last_battery_w: float = 0.0  # v1.16: for consumption category correction
        self._battery_w_ema: Optional[float] = None   # v4.5.15: EMA voor spike-filtering
        # v4.5.15: rollend venster van house_w metingen voor dynamische anomaly-drempel.
        # We bewaren de laatste 1440 samples (~24u bij 60s interval) en gebruiken P95
        # zodat de drempel per huis automatisch kalibreert.
        self._house_w_window: list = []   # circulair venster, max 1440 samples
        self._HOUSE_W_WINDOW_MAX = 1440
        # v4.5.64: onverklaard vermogen — wat house_w over heeft na NILM-som
        # Gebruiker kan dit een naam geven via service cloudems.name_undefined_power
        self._undefined_power_name: str = ""      # lege string = geen naam gezet
        self._undefined_power_min_w: float = 50.0  # toon pas boven 50W
        self._last_p1_data: Dict = {}       # v1.17 fix: ensure always initialized
        self._last_p1_update: float = 0.0   # timestamp van laatste P1 telegram (voor staleness)
        self._last_diag_log:  float = 0.0   # v4.5.11: timestamp van laatste diag-log schrijven
        self._last_price_log: float = 0.0   # v4.5.11: timestamp van laatste prijs-log schrijven
        self._acc_date: str = ""  # tracks date for pv_accuracy day rollover

        # Sub-modules
        self._dynamic_loader    = None
        self._phase_balancer    = None
        self._p1_reader         = None
        self._solar_learner     = None
        self._multi_inv_manager = None
        self._pv_forecast       = None
        self._peak_shaving      = None
        self._boiler_ctrl       = None

        # v4.6.522: DSMR-type auto-detectie state
        self._dsmr_type_last_check_ts: float = 0.0   # unix timestamp laatste check
        self._dsmr_type_notified:      bool  = False  # al een notificatie gestuurd?
        self._dsmr_type_auto_corrected: bool = False  # al automatisch gecorrigeerd?

        # v4.6.522: Sensor interval registry — meet update-snelheid per vermogenssensor
        self._sensor_interval_registry: Optional[SensorIntervalRegistry] = None

        # v4.6.522: gedeelde StateReader voor energy_manager modules
        self._state_reader: Optional[StateReader] = None

        # v4.6.530: zelflerend fase-stroom fusie model
        self._phase_fusion: Optional[PhaseCurrentFusion] = None

        # v4.6.531: zelflerend Kirchhoff-consistentie monitor
        self._kirchhoff_monitor: Optional[KirchhoffDriftMonitor] = None

        # v4.6.533: sensor-fusie en kwaliteitsmonitoring modules
        self._phase_consistency:     Optional[PhasePowerConsistencyMonitor] = None
        self._inverter_efficiency:   Optional[InverterEfficiencyTracker]    = None
        self._tariff_consistency:    Optional[TariffConsistencyMonitor]     = None
        self._wiring_topology:       Optional[WiringTopologyValidator]      = None
        self._feedback_loop:         Optional[GridFeedbackLoopDetector]     = None
        self._sign_consistency:      Optional[SignConsistencyLearner]       = None
        self._appliance_degradation: Optional[ApplianceDegradationMonitor]  = None
        self._standby_drift:         Optional[StandbyDriftTracker]          = None
        self._bde_quality:           Optional[BDEDecisionQualityTracker]    = None
        self._shutter_comfort:       Optional[ShutterComfortLearner]        = None
        self._integration_latency:   Optional[IntegrationLatencyMonitor]    = None
        self._p1_quality:            Optional[P1TelegramQualityMonitor]     = None
        self._savings_attribution:   Optional[SavingsAttributionTracker]    = None
        self._arbitrage_quality:     Optional[TariffArbitrageQuality]       = None

        # v4.6.535: tussenmeter topologie-validatie
        self._topology_validator:    Optional[TopologyConsistencyValidator]  = None
        self._topology_feeder:       Optional[TopologyAutoFeeder]            = None
        self._nilm_double_count:     Optional[NILMDoubleCountDetector]       = None
        self._decisions_history = None
        self._energy_demand_calc = None
        self._storage_backend   = None
        self._telemetry         = None
        self._pool_ctrl         = None
        self._lamp_circulation  = None  # v1.25.9: intelligente lampenbeveiliging
        self._shutter_ctrl      = None  # v3.9.0: rolluiken controller
        self._shutter_learner   = None  # v3.9.0: thermisch leermodel
        self._entity_device_log = None  # v4.6.13: entity/device tracking + orphan cleanup

        # ── Module toggle attrs — geïnitialiseerd op safe defaults ────────────
        # Primaire modules: standaard AAN
        self._peak_shaving_enabled:     bool = True
        self._phase_balancing_enabled:  bool = True
        self._cheap_switch_enabled:     bool = True
        self._nilm_load_shifting_enabled: bool = True
        self._budget_enabled:             bool = True
        self._pv_forecast_enabled:      bool = True
        self._shadow_detector_enabled:  bool = True
        self._solar_learner_enabled:    bool = True
        self._weekly_insights_enabled:  bool = True
        self._notifications_enabled:    bool = True
        # Conditionele modules: standaard UIT (aan na configuratie-check)
        self._lamp_circulation_enabled: bool = False
        self._ebike_enabled:            bool = False
        self._pool_enabled:             bool = False
        self._shutter_enabled:          bool = False
        self._boiler_enabled:           bool = False
        self._ev_charger_enabled:       bool = False
        self._battery_sched_enabled:    bool = False
        self._ere_enabled:              bool = False
        self._climate_mgr_override:     bool = False
        self._learning_backup   = None  # v1.18.0: backup schrijfpad voor alle leerdata

        # v1.9: new sub-modules
        self._co2_fetcher:       Optional[object] = None
        self._battery_scheduler:    Optional[object] = None
        self._congestion_detector:  Optional[object] = None
        self._battery_degradation:  Optional[object] = None
        self._sensor_hints:         Optional[object] = None
        self._cost_forecaster:   Optional[object] = None
        # v2.2.2: maandrapportage + installatie-score
        self._monthly_report:    Optional[object] = None
        self._daily_summary:     Optional[object] = None
        self._install_score:     Optional[InstallationScoreCalculator] = None
        # v2.2.3: gedragscoach + load planner + energy label + saldering
        self._behaviour_coach:   Optional[object] = None
        self._load_planner_data: dict = {}   # resultaat van laatste plan_tomorrow()
        self._load_plan_accuracy: Optional[LoadPlanAccuracyTracker] = None
        self._energy_label:      Optional[object] = None
        self._data_quality_monitor: DataQualityMonitor = DataQualityMonitor()
        self._nilm_group_tracker: Optional[NilmGroupTracker] = None
        self._saldering_sim:     Optional[object] = None
        self._battery_savings:   Optional[BatterySavingsTracker] = None
        # v2.2.3: lichte EPEX-prijshistorie voor BehaviourCoach (max 30 dagen × 24 = 720 uur)
        self._price_hour_history: list = []   # [{"ts": int, "price": float, "kwh_net": float}]
        self._price_history_last_hour: int = 0
        self._store_price_history = Store(hass, 1, "cloudems_price_hour_history_v1")
        # v2.4.0: gas analyse, budget, appliance ROI, solar dimmer
        self._gas_analysis:      Optional[object] = None
        self._energy_budget:     Optional[object] = None
        self._appliance_roi:     Optional[object] = None
        self._solar_dimmer:      Optional[object] = None
        # v1.10.3: self-learning intelligence modules
        self._home_baseline:     Optional[object] = None
        self._nilm_other_tracker: NilmOtherTracker = NilmOtherTracker()
        self._fault_notifier:    Optional[FaultNotifier] = None
        self._merge_advisor:     Optional[ComponentMergeAdvisor] = None
        # ESPHome NILM-meter features per fase (None = niet geconfigureerd/beschikbaar)
        self._esp_power_factor_l1: Optional[float] = None
        self._esp_power_factor_l2: Optional[float] = None
        self._esp_power_factor_l3: Optional[float] = None
        self._esp_inrush_peak_l1:  Optional[float] = None
        self._esp_inrush_peak_l2:  Optional[float] = None
        self._esp_inrush_peak_l3:  Optional[float] = None
        self._esp_rise_time_l1:    Optional[float] = None
        self._esp_rise_time_l2:    Optional[float] = None
        self._esp_rise_time_l3:    Optional[float] = None
        # v4.4.1 — optionele ESP32 features: None als sensor niet geconfigureerd
        self._esp_reactive_l1:     Optional[float] = None
        self._esp_reactive_l2:     Optional[float] = None
        self._esp_reactive_l3:     Optional[float] = None
        self._esp_thd_l1:          Optional[float] = None
        self._esp_thd_l2:          Optional[float] = None
        self._esp_thd_l3:          Optional[float] = None
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
        self._overduration_guard: Optional[object] = None   # v4.1: apparaat te lang aan
        self._clipping_loss:     Optional[object] = None
        self._categories:        Optional[object] = None
        self._shadow_detector:   Optional[object] = None

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
        self._plateau_windows: dict = {}  # entity_id → deque of float (plateau window)
        self._pre_windows: dict = {}      # entity_id → deque of float (pre-plateau slope window)
        # Per-inverter noise baseline: measured stddev/mean when NOT near ceiling.
        # Adapted over time — allows stricter clipping detection on smooth inverters.
        self._noise_baselines: dict = {}  # entity_id → EMA of stability ratio
        # Per-battery learned stats: {sensor_id: {max_charge_w, max_discharge_w, energy_accum_wh}}
        self._battery_learned: dict = {}
        # v4.5.6: Kirchhoff-consistente energiebalancer
        self._energy_balancer: Optional[object] = None
        # v4.5.9: zelflerende totale opslag (EB + BTW + markup als één getal)
        # Leert van de werkelijk betaalde HA-sensor prijs — werkt voor alle leveranciers
        self._total_opslag_learned: dict = {
            "samples":   [],    # opslag-waarden in €/kWh (all_in - epex)
            "estimated": None,  # mediaan opslag
            "n":         0,
            "source":    None,  # welke HA-sensor geleerd heeft
        }
        # Backwards-compat shims voor code die _markup_learned/_tax_learned nog leest
        self._markup_learned: dict = {"samples": [], "estimated_markup": None, "n": 0}
        self._tax_learned: dict = {"eb_samples": [], "btw_samples": [], "estimated_eb": None, "estimated_btw": None}

        # v1.15.0: new intelligence modules
        self._hp_cop:         Optional[object] = None
        self._climate_epex:   Optional[object] = None
        self._sensor_sanity:  Optional[object] = None
        self._absence:        Optional[object] = None
        self._zone_presence:  Optional[ZonePresenceManager] = None
        self._preheat:        Optional[object] = None
        self._pv_accuracy:    Optional[object] = None

        # v1.17: Hybride NILM
        self._hybrid: Optional[HybridNILM] = None

        # v2.4.14: NILM review queue — houdt bij welk apparaat de gebruiker nu beoordeelt
        # _review_skip_set: device_ids die de gebruiker tijdelijk heeft overgeslagen
        self._review_skip_set: set = set()
        self._review_skip_history: list = []  # geordend — voor "Vorige" knop

    # ── Public helpers ────────────────────────────────────────────────────────

    @property
    def nilm(self) -> NILMDetector:
        return self._nilm

    # ── v1.22: NILM toggle properties ────────────────────────────────────────

    @property
    def nilm_active(self) -> bool:
        return self._nilm_active

    @property
    def hybrid_nilm_active(self) -> bool:
        return self._hybrid_nilm_active

    @property
    def nilm_hmm_active(self) -> bool:
        return self._nilm_hmm_active

    async def set_nilm_active(self, enabled: bool) -> None:
        """Zet de NILM-motor aan of uit. Toestand wordt gepersisteerd."""
        self._nilm_active = enabled
        if not enabled:
            # Koppel HybridNILM ook los als NILM uitstaat
            self._nilm._hybrid = None
        else:
            # Koppel HybridNILM opnieuw als die ook actief is
            if self._hybrid_nilm_active and self._hybrid:
                self._nilm._hybrid = self._hybrid
        await self._save_nilm_toggles()
        if enabled:
            _LOGGER.info("CloudEMS NILM: motor AAN")
        else:
            _LOGGER.debug("CloudEMS NILM: motor UIT")

    async def set_hybrid_nilm_active(self, enabled: bool) -> None:
        """Zet de HybridNILM-laag aan of uit. Toestand wordt gepersisteerd."""
        self._hybrid_nilm_active = enabled
        if self._nilm_active:
            self._nilm._hybrid = self._hybrid if (enabled and self._hybrid) else None
        await self._save_nilm_toggles()
        if enabled:
            _LOGGER.info("CloudEMS HybridNILM: AAN")
        else:
            _LOGGER.debug("CloudEMS HybridNILM: UIT")

    @property
    def nilm_bayes_active(self) -> bool:
        return self._nilm_bayes_active

    async def set_nilm_bayes_active(self, enabled: bool) -> None:
        """Zet de Bayesian posterior classifier aan of uit."""
        self._nilm_bayes_active = enabled
        if enabled and self._bayes is None:
            self._bayes = BayesianNILMClassifier()
        self._nilm._bayes_callback = self._bayes if (enabled and self._bayes) else None
        await self._save_nilm_toggles()
        if enabled:
            _LOGGER.info("CloudEMS NILM Bayesian: AAN")
        else:
            _LOGGER.debug("CloudEMS NILM Bayesian: UIT")

    async def set_nilm_hmm_active(self, enabled: bool) -> None:
        """Zet HMM-sessietracking aan of uit. Toestand wordt gepersisteerd."""
        self._nilm_hmm_active = enabled
        if enabled and self._hmm is None:
            self._hmm = ApplianceHMMManager()
        self._nilm._hmm_callback = self._hmm.on_nilm_event if (enabled and self._hmm) else None
        await self._save_nilm_toggles()
        if enabled:
            _LOGGER.info("CloudEMS NILM HMM: AAN")
        else:
            _LOGGER.debug("CloudEMS NILM HMM: UIT")

    async def _save_nilm_toggles(self) -> None:
        """Persisteer de huidige toggle-staat naar HA storage."""
        try:
            await self._store_toggles.async_save({
                "nilm_active":              self._nilm_active,
                "hybrid_nilm_active":       self._hybrid_nilm_active,
                "nilm_hmm_active":          self._nilm_hmm_active,
                "nilm_bayes_active":        self._nilm_bayes_active,
                "sleep_detector_enabled":   self._sleep_detector_enabled,
                "battery_sched_enabled":    self._battery_sched_enabled,
                # v3.9.0: alle module toggles persistent
                "peak_shaving_enabled":     getattr(self, "_peak_shaving_enabled",     True),
                "phase_balancing_enabled":  getattr(self, "_phase_balancing_enabled",  True),
                "cheap_switch_enabled":     getattr(self, "_cheap_switch_enabled",     True),
                "pv_forecast_enabled":      getattr(self, "_pv_forecast_enabled",      True),
                "shadow_detector_enabled":  getattr(self, "_shadow_detector_enabled",  True),
                "solar_learner_enabled":    getattr(self, "_solar_learner_enabled",    True),
                "climate_mgr_override":     getattr(self, "_climate_mgr_override",     False),
                "boiler_enabled":           getattr(self, "_boiler_enabled",           False),
                "ev_charger_enabled":       getattr(self, "_ev_charger_enabled",       False),
                "ere_enabled":              getattr(self, "_ere_enabled",              False),
                "weekly_insights_enabled":  getattr(self, "_weekly_insights_enabled",  True),
                "notifications_enabled":    getattr(self, "_notifications_enabled",    True),
                "lamp_circulation_enabled": getattr(self, "_lamp_circulation_enabled", False),
                "ebike_enabled":            getattr(self, "_ebike_enabled",            False),
                "pool_enabled":             getattr(self, "_pool_enabled",             False),
                "zonneplan_auto_forecast":  getattr(self, "_zonneplan_auto_forecast",  False),
                "shutter_enabled":          getattr(self, "_shutter_enabled",          False),
            })
        except Exception as exc:
            _LOGGER.debug("NILM toggle opslaan mislukt: %s", exc)

    async def _load_nilm_toggles(self) -> None:
        """Laad eerder opgeslagen toggle-staat vanuit HA storage."""
        try:
            data = await self._store_toggles.async_load() or {}
            self._nilm_active        = data.get("nilm_active",        DEFAULT_NILM_ACTIVE)
            self._hybrid_nilm_active = data.get("hybrid_nilm_active", DEFAULT_HYBRID_NILM_ACTIVE)
            self._nilm_hmm_active    = data.get("nilm_hmm_active",    DEFAULT_NILM_HMM_ACTIVE)
            self._nilm_bayes_active  = data.get("nilm_bayes_active",  DEFAULT_NILM_BAYES_ACTIVE)
            if "sleep_detector_enabled" in data:
                self._sleep_detector_enabled = data["sleep_detector_enabled"]
            if "battery_sched_enabled" in data:
                self._battery_sched_enabled = data["battery_sched_enabled"]
            # v3.9.0: alle module toggles herstellen
            if "peak_shaving_enabled" in data:
                self._peak_shaving_enabled    = data["peak_shaving_enabled"]
            if "phase_balancing_enabled" in data:
                self._phase_balancing_enabled = data["phase_balancing_enabled"]
            if "cheap_switch_enabled" in data:
                self._cheap_switch_enabled    = data["cheap_switch_enabled"]
            if "pv_forecast_enabled" in data:
                self._pv_forecast_enabled     = data["pv_forecast_enabled"]
            if "shadow_detector_enabled" in data:
                self._shadow_detector_enabled = data["shadow_detector_enabled"]
            if "solar_learner_enabled" in data:
                self._solar_learner_enabled   = data["solar_learner_enabled"]
            if "climate_mgr_override" in data:
                was_active = getattr(self, "_climate_mgr_override", True)
                self._climate_mgr_override    = data["climate_mgr_override"]
                # v4.2.1: module net uitgeschakeld → release alle apparaten naar auto
                if was_active and not self._climate_mgr_override:
                    zone_mgr = getattr(self, "_zone_climate", None)
                    if zone_mgr:
                        for zone in getattr(zone_mgr, "_zones", []):
                            try:
                                import asyncio
                                asyncio.ensure_future(zone.async_release_devices())
                            except Exception as _exc_ignored:
                                _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)
                    _LOGGER.info("CloudEMS: klimaatbeheer uitgeschakeld — apparaten vrijgegeven")
            if "boiler_enabled" in data:
                self._boiler_enabled          = data["boiler_enabled"]
            if "ev_charger_enabled" in data:
                self._ev_charger_enabled      = data["ev_charger_enabled"]
            if "ere_enabled" in data:
                self._ere_enabled             = data["ere_enabled"]
            if "weekly_insights_enabled" in data:
                self._weekly_insights_enabled = data["weekly_insights_enabled"]
            if "notifications_enabled" in data:
                self._notifications_enabled   = data["notifications_enabled"]
            if "lamp_circulation_enabled" in data:
                self._lamp_circulation_enabled = data["lamp_circulation_enabled"]
            if "ebike_enabled" in data:
                self._ebike_enabled           = data["ebike_enabled"]
            if "pool_enabled" in data:
                self._pool_enabled            = data["pool_enabled"]
            if "shutter_enabled" in data:
                self._shutter_enabled         = data["shutter_enabled"]
            if "zonneplan_auto_forecast" in data:
                self._zonneplan_auto_forecast = data["zonneplan_auto_forecast"]
                # Koppel ook door naar bridge als die al bestaat
                zb = getattr(self, "_zonneplan_bridge", None)
                if zb and hasattr(zb, "_auto_forecast_enabled"):
                    zb._auto_forecast_enabled = self._zonneplan_auto_forecast
            _LOGGER.debug(
                "CloudEMS toggles geladen: nilm=%s hybrid=%s hmm=%s sleep=%s zp_auto=%s",
                self._nilm_active, self._hybrid_nilm_active,
                self._nilm_hmm_active, self._sleep_detector_enabled,
                getattr(self, "_zonneplan_auto_forecast", False),
            )
        except Exception as exc:
            _LOGGER.debug("NILM toggle laden mislukt: %s", exc)

    @property
    def phase_currents(self) -> dict[str, float]:
        return self._limiter.phase_currents

    @property
    def learning_frozen(self) -> bool:
        """True if simulator active OR performance monitor says learning should pause."""
        if getattr(self, "_simulator", None) is not None and self._simulator.active:
            return True
        # v4.6.152: pause learning when performance is degraded
        perf = getattr(self, "_perf", None)
        if perf is not None and not perf.nilm_learning_enabled:
            return True
        return False

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
        # v4.5.66 fix: gebruik today_all_display (all-in prijs) indien beschikbaar,
        # consistent met hoe today_prices in de sensor genormaliseerd wordt.
        prev = None
        try:
            from datetime import datetime, timezone
            now    = datetime.now(timezone.utc)
            prev_h = (now.hour - 1) % 24
            today_display = price_info.get("today_all_display", [])
            slots_to_search = today_display if today_display else today_all
            if slots_to_search:
                prev_slot = next((s for s in slots_to_search if s.get("hour") == prev_h), None)
                if prev_slot:
                    display = prev_slot.get("price_display") or prev_slot.get("price_all_in")
                    prev = display if display is not None else prev_slot.get("price")
            else:
                # Fallback to raw slots from _today_slots() using datetime
                for s in self._prices._today_slots():
                    slot_hour = self._prices._aware(s["start"]).hour
                    if slot_hour == prev_h:
                        prev = float(s["price"])
                        break
        except Exception as _exc_ignored:
            _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

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

        # v4.6.437: voeg uurprijzen toe zodat boiler_controller legionella kan plannen
        # prices_today is een lijst van 24 prijzen (index = uur), gesorteerd op uur
        _hourly_list = []
        if prices_today:
            # today_all is [{hour, price, ...}] — zet om naar lijst van 24
            _by_hour = {int(s.get("hour", 0)): float(s.get("price", 0)) for s in (today_all or [])}
            if not _by_hour:
                _by_hour = {i: prices_today[i] for i in range(len(prices_today))}
            _hourly_list = [_by_hour.get(h, 0.0) for h in range(24)]

        # Morgen prijzen
        _tomorrow_list = []
        try:
            _tom_slots = self._prices._tomorrow_slots() if hasattr(self._prices, "_tomorrow_slots") else []
            if _tom_slots:
                _tom_by_hour = {int(s.get("hour", 0)): float(s.get("price", 0)) for s in _tom_slots}
                _tomorrow_list = [_tom_by_hour.get(h, 0.0) for h in range(24)]
        except Exception:
            pass

        _all_in = price_info.get("current_all_in") or price_info.get("result_all_in_eur_kwh") or cur
        return {
            **price_info,
            "prev_hour_price":        prev,
            "rank_today":             rank,
            "is_cheap_hour":          is_cheap,
            "hourly_prices":          _hourly_list,
            "hourly_prices_tomorrow": _tomorrow_list if _tomorrow_list else None,
            "current_all_in":         round(_all_in, 5) if _all_in is not None else cur,
            "is_negative_all_in":     (_all_in is not None and _all_in < 0),
        }

    def _get_yesterday_prices(self) -> list:
        """Haal gisterprijzen uit _price_hour_history als [{hour, price}] lijst."""
        try:
            from datetime import datetime as _dt, timedelta as _td
            yesterday = (_dt.now() - _td(days=1)).date()
            ts_start = int(_dt(yesterday.year, yesterday.month, yesterday.day, 0).timestamp())
            ts_end   = int(_dt(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59).timestamp())
            slots = [
                {"hour": _dt.fromtimestamp(h["ts"]).hour, "price": round(float(h["price"]), 5)}
                for h in self._price_hour_history
                if ts_start <= h.get("ts", 0) <= ts_end and h.get("price") is not None
            ]
            # Sorteer op uur, dedup (bewaar laatste per uur)
            by_hour = {}
            for s in slots:
                by_hour[s["hour"]] = s
            return [by_hour[h] for h in sorted(by_hour)]
        except Exception:
            return []

    def _apply_price_components(self, price_info: dict) -> dict:
        """Verrijk price_info met all-in prijs (EB + BTW + leveranciersopslag).

        v4.5.9: Zelflerende totale opslag — leert automatisch van HA-sensoren
        die de werkelijk betaalde prijs rapporteren (Zonneplan, DSMR, Tibber, ...).
        Geen hardcoded EB/BTW/markup meer; die zijn slechts initiële fallback.

        Architectuur:
          • _total_opslag_learned  = all_in_paid - epex_base (€/kWh, incl. EB+BTW+markup)
          • Geldig zodra ≥ 6 samples beschikbaar zijn (mediaan, robuust tegen uitschieters)
          • Als EB+BTW toggles AAN zijn maar geen sensor gevonden: gebruik NL 2025 fallback
          • Als EB+BTW toggles UIT zijn: toon kale EPEX (ongewijzigd gedrag)

        Provider-prijzen (prices_from_provider=True): altijd ongewijzigd doorgeven.
        """
        cfg          = self._config
        from_provider = price_info.get("prices_from_provider", False)
        country      = cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL")

        include_tax  = bool(cfg.get(CONF_PRICE_INCLUDE_TAX, False))
        include_btw  = bool(cfg.get(CONF_PRICE_INCLUDE_BTW, False))
        wants_all_in = include_tax or include_btw

        # ── Provider-prijzen zijn al all-in: ongewijzigd teruggeven ──────────
        if from_provider:
            cur = price_info.get("current")
            _vat_rate = VAT_RATE_PER_COUNTRY.get(country, 0.21)
            _eb       = ENERGY_TAX_PER_COUNTRY.get(country, 0.0)
            supplier_key = cfg.get(CONF_SELECTED_SUPPLIER, "none")
            _sup = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS.get("default", {}))
            _markup = _sup.get(supplier_key, ("", 0.0))[1]

            def _strip_tax(p_all_in):
                """Bereken excl-tax prijs uit all-in provider prijs.
                all_in = (epex + eb + markup) * (1 + vat)
                → epex_net = all_in / (1+vat) - eb - markup
                """
                if p_all_in is None:
                    return None
                return round(p_all_in / (1 + _vat_rate) - _eb - _markup, 5)

            cur_excl = _strip_tax(cur)
            today_display = []
            for slot in price_info.get("today_all", []):
                p = slot.get("price")
                today_display.append({**slot,
                    "price_display":   round(p, 5) if p is not None else None,
                    "price_all_in":    round(p, 5) if p is not None else None,
                    "price_excl_tax":  _strip_tax(p),
                    "price_incl_tax":  round(p, 5) if p is not None else None,
                })
            tomorrow_display = []
            for slot in price_info.get("tomorrow_all", []):
                p = slot.get("price")
                tomorrow_display.append({**slot,
                    "price_display":   round(p, 5) if p is not None else None,
                    "price_all_in":    round(p, 5) if p is not None else None,
                    "price_excl_tax":  _strip_tax(p),
                    "price_incl_tax":  round(p, 5) if p is not None else None,
                })
            min_today = price_info.get("min_today")
            max_today = price_info.get("max_today")
            avg_today = price_info.get("avg_today") or price_info.get("rolling_avg_30d")
            return {
                **price_info,
                "tax_per_kwh":            round(_eb, 5),
                "vat_rate":               _vat_rate,
                "supplier_markup_kwh":    round(_markup, 5),
                "price_include_tax":      True,   # provider prijzen zijn altijd all-in
                "price_include_btw":      True,
                "prices_from_provider":   True,
                # all-in (incl. EB + BTW + markup)
                "current_all_in":         round(cur, 5) if cur is not None else None,
                "current_display":        round(cur, 5) if cur is not None else cur,
                # zonder belasting (kale EPEX + markup, excl. EB + BTW)
                "current_excl_tax":       cur_excl,
                # min/max/gem ook in beide varianten
                "min_today_incl_tax":     round(min_today, 5) if min_today is not None else None,
                "max_today_incl_tax":     round(max_today, 5) if max_today is not None else None,
                "avg_today_incl_tax":     round(avg_today, 5) if avg_today is not None else None,
                "min_today_excl_tax":     _strip_tax(min_today),
                "max_today_excl_tax":     _strip_tax(max_today),
                "avg_today_excl_tax":     _strip_tax(avg_today),
                # label voor dashboard
                "price_label":            "all-in (incl. belasting)",
                "price_label_excl":       "excl. belasting",
                "today_all_display":      today_display,
                "tomorrow_all_display":   tomorrow_display,
                "rolling_avg_30d_all_in": price_info.get("rolling_avg_30d"),
                "learned_opslag_kwh":     None,
                "learned_opslag_samples": 0,
                "learned_markup_kwh":     None,
                "learned_markup_samples": 0,
                "learned_eb_kwh":         round(_eb, 5),
                "learned_btw_rate":       _vat_rate,
                # v4.5.87: gasprijs meegeven voor gas-vs-stroom vergelijking
                "gas_price_eur_m3":       self._read_gas_price(),
            }

        epex_base = price_info.get("current")
        supplier_key  = cfg.get(CONF_SELECTED_SUPPLIER, "none")
        custom_markup = float(cfg.get(CONF_SUPPLIER_MARKUP, 0.0))

        # ── Bepaal effectieve opslag op basis van gebruikersinstellingen ─────
        # Alles uit config — geen HA-sensors, geen externe API's.
        # Werkt identiek in HA en in de toekomstige cloud/Proxmox variant.
        if not wants_all_in:
            # Gebruiker wil geen belasting zien: toon kale EPEX
            effective_opslag = 0.0
        else:
            tax = ENERGY_TAX_PER_COUNTRY.get(country, 0.0) if include_tax else 0.0
            vat = VAT_RATE_PER_COUNTRY.get(country, 0.21)  if include_btw else 0.0

            # Leveranciersopslag uit config
            if supplier_key == "custom":
                markup = custom_markup
            else:
                suppliers = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS.get("default", {}))
                markup = suppliers.get(supplier_key, ("", 0.0))[1]

            # Formule: (EPEX + EB + markup) × (1 + BTW)
            # effective_opslag = wat er bij EPEX opgeteld moet worden
            # = (tax + markup) × (1 + vat) + EPEX × vat
            # Maar we werken per slot dus: all_in = (base + tax + markup) × (1 + vat)
            # → opslag = (tax + markup) × (1 + vat) + base × vat
            # Dit kan niet als constante opslag — we gebruiken _enrich() hieronder.
            effective_opslag = None  # signaal voor _enrich: gebruik formule

        # Backwards-compat: tol niet meer gebruikt maar veld moet bestaan
        tol = getattr(self, "_total_opslag_learned", {"samples": [], "estimated": None, "n": 0, "source": None})
        learned_opslag = None  # niet meer geleerd via sensors

        # ── Bereken all-in prijs ─────────────────────────────────────────────
        if wants_all_in:
            _tax    = ENERGY_TAX_PER_COUNTRY.get(country, 0.0) if include_tax else 0.0
            _vat    = VAT_RATE_PER_COUNTRY.get(country, 0.21)  if include_btw else 0.0
            if supplier_key == "custom":
                _markup = custom_markup
            else:
                _sup = SUPPLIER_MARKUPS.get(country, SUPPLIER_MARKUPS.get("default", {}))
                _markup = _sup.get(supplier_key, ("", 0.0))[1]
        else:
            _tax = _vat = _markup = 0.0

        def _enrich(base: float | None) -> float | None:
            if base is None:
                return None
            if not wants_all_in:
                return round(base, 5)
            sub = base + _tax + _markup
            return round(sub * (1 + _vat), 5)

        cur = price_info.get("current")
        today_display = []
        for slot in price_info.get("today_all", []):
            p = slot.get("price")
            today_display.append({**slot,
                "price_display": _enrich(p),
                "price_all_in":  _enrich(p),
            })

        tomorrow_display = []
        for slot in price_info.get("tomorrow_all", []):
            p = slot.get("price")
            tomorrow_display.append({**slot,
                "price_display": _enrich(p),
                "price_all_in":  _enrich(p),
            })

        diag_vat = VAT_RATE_PER_COUNTRY.get(country, 0.21)
        # Totale opslag voor diagnostics: (tax + markup) * (1 + vat)
        diag_opslag = round((_tax + _markup) * (1 + _vat), 5) if wants_all_in else 0.0

        cur_all_in = _enrich(cur)
        _LOGGER.info(
            "CloudEMS prijs [%s/%s]: EPEX=%.5f + EB=%.5f + markup=%.5f x (1+BTW %.0f%%) = all-in %.5f eurokWh (%.2f ct/kWh) | wants_all_in=%s",
            country, supplier_key,
            cur if cur is not None else 0.0,
            _tax, _markup, _vat * 100,
            cur_all_in if cur_all_in is not None else 0.0,
            (cur_all_in * 100) if cur_all_in is not None else 0.0,
            wants_all_in,
        )

        return {
            **price_info,
            "tax_per_kwh":            round(_tax, 5),
            "vat_rate":               round(_vat if _vat > 0 else diag_vat, 4),
            "supplier_markup_kwh":    round(_markup, 5),
            "total_opslag_kwh":       diag_opslag,
            "price_include_tax":      wants_all_in and include_tax,
            "price_include_btw":      wants_all_in and include_btw,
            "country":                country,
            # all-in (incl. EB + BTW + markup)
            "current_all_in":         cur_all_in,
            "current_display":        cur_all_in if wants_all_in else cur,
            # zonder belasting (kale EPEX, excl. EB + BTW + markup)
            "current_excl_tax":       round(cur, 5) if cur is not None else None,
            # min/max/gem in beide varianten
            "min_today_incl_tax":     _enrich(price_info.get("min_today")),
            "max_today_incl_tax":     _enrich(price_info.get("max_today")),
            "avg_today_incl_tax":     _enrich(price_info.get("avg_today")),
            "min_today_excl_tax":     round(price_info["min_today"], 5) if price_info.get("min_today") is not None else None,
            "max_today_excl_tax":     round(price_info["max_today"], 5) if price_info.get("max_today") is not None else None,
            "avg_today_excl_tax":     round(price_info["avg_today"], 5) if price_info.get("avg_today") is not None else None,
            # label voor dashboard
            "price_label":            "all-in (incl. belasting)" if wants_all_in else "EPEX (excl. belasting)",
            "price_label_excl":       "EPEX (excl. belasting)",
            "today_all_display":      today_display,
            "tomorrow_all_display":   tomorrow_display,
            "rolling_avg_30d_all_in": _enrich(price_info.get("rolling_avg_30d")),
            # Legacy/diagnostics
            "learned_opslag_kwh":     None,
            "learned_opslag_samples": 0,
            "learned_markup_kwh":     None,
            "learned_markup_samples": 0,
            "learned_eb_kwh":         round(_tax, 5),
            "learned_btw_rate":       round(diag_vat, 4),
            # v4.5.87: gasprijs meegeven zodat boiler_controller gas-vs-stroom kan vergelijken
            "gas_price_eur_m3":       self._read_gas_price(),
        }


    async def _async_suggest_device_names(self) -> None:
        """v2.4.0: Vraag LLM om naam-suggesties voor pending generic NILM-apparaten."""
        if not self._ollama_cfg.get("enabled"):
            return
        if self._ollama_health.get("status") != "online":
            return

        cfg   = self._ollama_cfg
        host  = cfg.get("host", "localhost")
        port  = cfg.get("port", 11434)
        model = cfg.get("model", "llama3")
        url   = f"http://{host}:{port}/api/generate"

        for dev in self._nilm.get_devices():
            if not dev.pending_confirmation:
                continue
            if dev.suggested_name:
                continue  # al een suggestie
            if dev.user_name:
                continue  # gebruiker heeft al een naam gegeven
            # Alleen voor generic types
            if dev.device_type not in ("unknown", "generic_appliance", "generic", ""):
                continue

            prompt = (
                f"A home energy monitor detected a new electrical device. "
                f"Based on the following profile, suggest a short Dutch household appliance name (max 3 words). "
                f"Device type hint: {dev.device_type or 'unknown'}. "
                f"Power: {dev.current_power:.0f}W. "
                f"Phase: {dev.phase}. "
                f"Detected at hour: {datetime.fromtimestamp(dev.last_seen, tz=timezone.utc).hour}. "
                f"Respond ONLY with the device name, nothing else. Example: 'Magnetron' or 'Elektrische boiler'."
            )

            try:
                async with self._session.post(
                    url,
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        name = (result.get("response") or "").strip().strip('"\'')
                        if name and len(name) < 50:
                            dev.suggested_name = name
                            _LOGGER.info(
                                "NILM LLM naam-suggestie voor '%s': '%s'",
                                dev.device_id, name,
                            )
            except Exception as _llm_err:
                _LOGGER.debug("LLM naam-suggestie fout voor %s: %s", dev.device_id, _llm_err)

    def _calc_tariff_check(self, p1_data: dict | None, price_info: dict | None) -> dict:
        """v2.4.0: Vergelijk berekende kosten met geconfigureerd tarief × gemeten import."""
        try:
            import_kwh = float((p1_data or {}).get("electricity_import_today_kwh") or 0)
            if import_kwh < 1.0:
                return {"status": "insufficient_data"}

            configured_tariff = float(self._config.get("energy_tariff_import_eur_kwh") or 0)
            avg_epex = float((price_info or {}).get("avg_today") or 0)

            if configured_tariff <= 0 and avg_epex <= 0:
                return {"status": "no_tariff_configured"}

            # Geschatte kosten op basis van geconfigureerd vaste tarief
            expected_eur = import_kwh * configured_tariff if configured_tariff > 0 else None
            # Kosten op basis van EPEX gemiddelde
            epex_eur = import_kwh * avg_epex if avg_epex > 0 else None

            actual_eur = self._cost_today_eur

            result = {
                "status":              "ok",
                "import_kwh":          round(import_kwh, 2),
                "calculated_cost_eur": round(actual_eur, 3),
                "configured_tariff":   configured_tariff,
                "avg_epex_price":      round(avg_epex, 4),
            }

            if expected_eur and expected_eur > 0.5:
                deviation_pct = abs(actual_eur - expected_eur) / expected_eur * 100
                result["tariff_deviation_pct"] = round(deviation_pct, 1)
                if deviation_pct > 20:
                    result["status"] = "tariff_mismatch"
                    result["advice"] = (
                        f"Berekende kosten (€{actual_eur:.2f}) wijken {deviation_pct:.0f}% af van "
                        f"tarief × import (€{expected_eur:.2f}). "
                        "Controleer het geconfigureerde importtarief in de CloudEMS instellingen."
                    )
            return result
        except Exception as _tc_err:
            _LOGGER.debug("TariffCheck fout: %s", _tc_err)
            return {"status": "error"}

    def _build_system_health(self, price_info: dict | None) -> dict:
        """v2.2.3: Bouw een systeemgezondheid-overzicht voor de health sensor."""
        import time as _t
        now = _t.time()

        # Tel actieve sub-modules
        modules = {
            "nilm":           self._nilm_active,
            "hybrid_nilm":    self._hybrid_nilm_active and self._hybrid is not None,
            "p1":             self._p1_reader is not None,
            "solar_learner":  self._solar_learner is not None,
            "pv_forecast":    self._pv_forecast is not None,
            "battery_sched":  self._battery_scheduler is not None,
            "ev_charger":     self._dynamic_loader is not None or bool(self._config.get("ev_charger_entity")),
            "prices":         self._prices is not None,
            "notification":   self._notification_engine is not None,
            "behaviour_coach": self._behaviour_coach is not None,
        }
        active_count = sum(1 for v in modules.values() if v)

        # EPEX prijs-versheid
        price_age_min = None
        if self._prices_last_update > 0:
            price_age_min = round((now - self._prices_last_update) / 60, 1)
        prices_fresh = price_age_min is not None and price_age_min < 90

        # NILM devices — gebruik get_devices_for_ha() zodat infra/geblokkeerde
        # sensoren niet meegeteld worden (fix v2.4.17)
        nilm_devices_ha  = self._nilm.get_devices_for_ha()
        nilm_devices_raw = self._nilm.get_devices()
        confirmed_dev = sum(1 for d in nilm_devices_ha if d.get("confirmed", False))
        detected_dev  = len(nilm_devices_ha)

        # Algehele status
        if active_count >= 7 and prices_fresh:
            status = "ok"
        elif active_count >= 4:
            status = "degraded"
        else:
            status = "limited"

        # v4.0.6: numerieke health score 0-10
        _score = 0
        _score += 3 if active_count >= 7 else (2 if active_count >= 5 else 1 if active_count >= 3 else 0)
        _score += 2 if prices_fresh else 0
        _score += 2 if confirmed_dev >= 3 else (1 if confirmed_dev >= 1 else 0)
        _score += 1 if self._watchdog and self._watchdog._consecutive_failures == 0 else 0
        _score += 1 if not (getattr(self, "_battery_eff", None) and self._battery_eff_status.get("warn")) else 0
        _score += 1 if getattr(self, "_off_peak_status", {}) else 0
        health_score = min(10, _score)

        return {
            "status":           status,
            "score":            health_score,           # v4.0.6: 0-10
            "active_modules":   active_count,
            "total_modules":    len(modules),
            "modules":          modules,
            "prices_fresh":     prices_fresh,
            "price_age_min":    price_age_min,
            "nilm_devices":     detected_dev,
            "confirmed_devices": confirmed_dev,
            "uptime_cycles":    getattr(self, "_health_cycle_count", 0),
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

    async def async_check_ollama_health(self) -> None:
        """Ping Ollama /api/tags to verify connectivity and model availability. v1.16"""
        import time as _t, aiohttp as _aio
        from datetime import datetime, timezone

        cfg   = self._ollama_cfg
        host  = cfg.get("host", "localhost")
        port  = cfg.get("port", 11434)
        model = cfg.get("model", "llama3")
        url   = f"http://{host}:{port}/api/tags"

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        try:
            async with async_get_clientsession(self.hass) as s:
                async with s.get(url, timeout=_aio.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data   = await r.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        found  = any(model in m for m in models)
                        self._ollama_health = {
                            "status":              "online",
                            "models_available":    models,
                            "active_model":        model,
                            "active_model_found":  found,
                            "last_check_ts":       now_iso,
                            "last_error":          None,
                        }
                        _LOGGER.debug("Ollama health OK — modellen: %s", models)
                    else:
                        self._ollama_health.update({
                            "status":       "error",
                            "last_check_ts": now_iso,
                            "last_error":   f"HTTP {r.status}",
                        })
        except _aio.ClientConnectorError:
            self._ollama_health.update({
                "status":       "offline",
                "last_check_ts": now_iso,
                "last_error":   f"Kan niet verbinden met {host}:{port}",
            })
        except Exception as exc:  # noqa: BLE001
            self._ollama_health.update({
                "status":       "error",
                "last_check_ts": now_iso,
                "last_error":   str(exc),
            })
        self._ollama_health_last_check = _t.time()

    def confirm_nilm_device(self, device_id: str, name: str = "", device_type: str = "") -> None:
        """Confirm a NILM-detected device with optional corrected name/type."""
        from .const import NILM_FEEDBACK_CORRECT
        self._nilm.set_feedback(device_id, NILM_FEEDBACK_CORRECT,
                                corrected_name=name, corrected_type=device_type)
        # Sync: haal ook uit skip-set en history zodat de review-queue consistent is
        self._review_skip_set.discard(device_id)
        if device_id in self._review_skip_history:
            self._review_skip_history.remove(device_id)
        # v2.4.17: registreer als true positive voor adaptieve drempels
        dev = self._nilm._devices.get(device_id)
        if dev:
            dtype = getattr(dev, "device_type", "unknown") or "unknown"
            rec = self._adaptive_thresholds.setdefault(dtype, {"tp": 0, "fp": 0})
            rec["tp"] = rec.get("tp", 0) + 1

    def dismiss_nilm_device(self, device_id: str) -> None:
        # v4.5.3: dismiss zet user_suppressed=True (persistent) i.p.v. delete
        dev = self._nilm._devices.get(device_id)
        self._nilm.dismiss_device(device_id)
        self._review_skip_set.discard(device_id)
        if device_id in self._review_skip_history:
            self._review_skip_history.remove(device_id)
        # v2.4.17: registreer als false positive voor adaptieve drempels
        if dev:
            dtype = getattr(dev, "device_type", "unknown") or "unknown"
            rec = self._adaptive_thresholds.setdefault(dtype, {"tp": 0, "fp": 0})
            rec["fp"] = rec.get("fp", 0) + 1
            # Pas on_events drempel aan: als fp > tp, verhoog minimale on_events voor dit type
            if rec["fp"] > rec.get("tp", 0):
                rec["min_events"] = min(rec.get("min_events", 3) + 1, 20)
            # Direct doorgeven aan detector
            self._nilm.set_adaptive_overrides(self._adaptive_thresholds)

        # v4.5.3: onmiddellijk opslaan zodat dismissal persistent is na herstart
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._nilm.async_save())
        except Exception as _exc_ignored:
            _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

    # ── v2.4.14: NILM review queue ────────────────────────────────────────────

    def get_review_current(self) -> Optional[object]:
        """Geeft het eerste onbevestigde, niet-overgeslagen NILM-apparaat terug.

        Volgorde: langst aanwezig (meeste on_events) eerst, zodat de meest
        stabiele detecties als eerste worden beoordeeld.
        """
        pending = [
            dev for dev in self._nilm.get_devices()
            if not dev.confirmed
            and not getattr(dev, "user_suppressed", False)
            and dev.device_id not in self._review_skip_set
        ]
        if not pending:
            return None
        return max(pending, key=lambda d: d.on_events)

    def get_review_pending_count(self) -> int:
        """Aantal onbevestigde apparaten (inclusief overgeslagen)."""
        return sum(
            1 for dev in self._nilm.get_devices()
            if not dev.confirmed and not getattr(dev, "user_suppressed", False)
        )

    def review_confirm_current(self) -> Optional[str]:
        """Bevestig het huidige review-apparaat. Geeft device_id terug of None."""
        dev = self.get_review_current()
        if not dev:
            return None
        self.confirm_nilm_device(dev.device_id)
        self._review_skip_set.discard(dev.device_id)
        return dev.device_id

    def review_dismiss_current(self) -> Optional[str]:
        """Wijs het huidige review-apparaat af. Geeft device_id terug of None."""
        dev = self.get_review_current()
        if not dev:
            return None
        self.dismiss_nilm_device(dev.device_id)
        return dev.device_id

    def review_maybe_current(self) -> Optional[str]:
        """Markeer het huidige review-apparaat als 'weet ik niet' (maybe).
        Het apparaat blijft zichtbaar maar krijgt user_feedback='maybe'.
        Wordt overgeslagen in de review-queue zodat de gebruiker verder kan.
        Geeft device_id terug of None.
        """
        dev = self.get_review_current()
        if not dev:
            return None
        self.set_nilm_feedback(dev.device_id, "maybe")
        # Zet ook in skip-set zodat het niet steeds opnieuw bovenaan staat
        self._review_skip_set.add(dev.device_id)
        self._review_skip_history.append(dev.device_id)
        return dev.device_id

    def review_skip_current(self) -> Optional[str]:
        """Sla het huidige review-apparaat over (tijdelijk, reset bij herstart).
        Geeft device_id terug of None.
        """
        dev = self.get_review_current()
        if not dev:
            return None
        self._review_skip_set.add(dev.device_id)
        self._review_skip_history.append(dev.device_id)
        return dev.device_id

    def review_previous(self) -> Optional[str]:
        """Ga terug naar het vorige overgeslagen apparaat.
        Haalt de laatste entry uit de skip-history en zet hem terug in de queue.
        """
        if not self._review_skip_history:
            return None
        prev_id = self._review_skip_history.pop()
        self._review_skip_set.discard(prev_id)
        return prev_id

    def set_nilm_feedback(self, device_id: str, feedback: str,
                          corrected_name: str = "", corrected_type: str = "") -> None:
        self._nilm.set_feedback(device_id, feedback, corrected_name, corrected_type)
        # [v2.1] Koppel feedback door naar SmartPowerEstimator als entity_id bekend is
        if self._power_estimator:
            try:
                dev = self._nilm._devices.get(device_id)
                source_eid = getattr(dev, "source_entity_id", None) if dev else None
                if source_eid:
                    is_correct = feedback in ("correct",)
                    is_incorrect = feedback in ("incorrect",)
                    if is_correct or is_incorrect:
                        self._power_estimator.notify_feedback(source_eid, is_correct)
            except Exception as _fe:
                pass

    def rename_nilm_device(self, device_id: str, name: str, device_type: str = "") -> None:
        """Rename a NILM-detected device. Optionally correct the device type too.

        v1.20: dedicated rename method — does not change feedback/confidence,
        only updates the display name (and optionally type) the user sees.
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS rename_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_name = name.strip()[:60]  # max 60 chars
        if device_type:
            dev.user_type = device_type.strip()
        _LOGGER.info("CloudEMS NILM: renamed '%s' → '%s'", device_id, dev.user_name)

    def hide_nilm_device(self, device_id: str, hidden: bool = True) -> None:
        """Hide or unhide a NILM device from the dashboard and sensors.

        v1.20: hidden devices are excluded from get_devices_for_ha() but
        remain in storage so they can be un-hidden later.
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS hide_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_hidden = hidden
        _LOGGER.info("CloudEMS NILM: device '%s' hidden=%s", device_id, hidden)

    def assign_device_to_room(self, device_id: str, room_name: str) -> None:
        """Manually assign a NILM device to a room for the virtual room meter.

        v1.20: Overrides auto-detected room. Use empty room_name to clear override.
        """
        if hasattr(self, "_room_meter") and self._room_meter:
            self._room_meter.assign_device_to_room(device_id, room_name)

    def suppress_nilm_device(self, device_id: str) -> None:
        """Decline/suppress a NILM device — never show again.

        v1.20: User-visible 'Decline' button. Keeps the record in storage so the
        NILM algorithm knows not to resurface this detection, but hides it from all
        dashboards and sensors. Sets user_feedback='incorrect' so it also improves
        future NILM training (negative example).
        """
        dev = self._nilm._devices.get(device_id)
        if not dev:
            _LOGGER.warning("CloudEMS suppress_nilm_device: unknown device_id '%s'", device_id)
            return
        dev.user_suppressed = True
        dev.user_feedback   = "incorrect"
        dev.confirmed       = False
        _LOGGER.info("CloudEMS NILM: device '%s' declined/suppressed by user", device_id)

    async def async_shutdown(self) -> None:
        """Called by __init__.py on unload. Flush all dirty learning data before exit."""
        # Flush every learning module that tracks dirty state
        flush_targets = [
            self._solar_learner,
            self._pv_forecast,
            self._clipping_loss,
            self._shadow_detector,
            self._pv_health,
            self._device_drift,
            self._micro_mobility,
            self._notification_engine,
            self._categories,
            self._cost_forecaster,
            self._thermal_model,
            self._self_consumption,
            self._day_classifier,
            self._pv_accuracy,
            getattr(self, "_home_baseline", None),
            getattr(self, "_ev_session", None),
            getattr(self, "_nilm_schedule", None),
            getattr(self, "_gas_analysis", None),
            getattr(self, "_energy_budget", None),
            getattr(self, "_battery_degradation", None),
            getattr(self, "_sensor_hints", None),
            getattr(self, "_room_meter", None),          # v1.20
            getattr(self, "_nilm", None),                    # v4.6.246: NILM devices persistent
        ]
        for module in flush_targets:
            if module is None:
                continue
            for method_name in ("async_maybe_save", "async_save", "_async_save"):
                method = getattr(module, method_name, None)
                if callable(method):
                    try:
                        await method()
                    except Exception:  # noqa: BLE001
                        pass
                    break  # only call the first available save method

        # Shutter externe detectie listener stoppen
        if getattr(self, "_shutter_ctrl", None):
            await self._shutter_ctrl.async_shutdown()

        # v4.6.514: opruimen realtime solar/batterij listeners
        if getattr(self, "_rt_unsub_solar", None):
            self._rt_unsub_solar()
            self._rt_unsub_solar = None
        if getattr(self, "_rt_unsub_battery", None):
            self._rt_unsub_battery()
            self._rt_unsub_battery = None

        # v4.6.276: AdaptiveHome bridge opruimen
        if getattr(self, "_ah_bridge", None):
            await self._ah_bridge.async_shutdown()

        # v4.0.9: HA-sessie — niet zelf sluiten
        if self._p1_reader:
            try:
                await self._p1_reader.async_stop()
            except Exception:  # noqa: BLE001
                pass

        # Geforceerde backup-flush bij nette afsluiting — v2.0: alle modules
        backup = getattr(self, "_learning_backup", None)
        if backup is not None:
            modules_data = {}
            # solar_learner
            if self._solar_learner:
                try:
                    modules_data["solar_learner"] = self._solar_learner._build_save_data()
                except Exception as _e:
                    _LOGGER.debug("Backup solar_learner mislukt: %s", _e)
            # pv_forecast
            if self._pv_forecast:
                try:
                    pv_data = {}
                    for eid, p in self._pv_forecast._profiles.items():
                        pv_data[eid] = {
                            "learned_azimuth":       p.learned_azimuth,
                            "learned_tilt":          p.learned_tilt,
                            "orientation_confident": p.orientation_confident,
                            "clear_sky_samples":     p.clear_sky_samples,
                            "hourly_yield_fraction": p.hourly_yield_fraction,
                            "peak_wp":               p._peak_wp,
                            "calib_factor":          p._calib_factor,
                            "calib_samples":         p._calib_samples,
                        }
                    modules_data["pv_forecast"] = pv_data
                except Exception as _e:
                    _LOGGER.debug("Backup pv_forecast mislukt: %s", _e)
            # grid_congestion
            try:
                _gc = getattr(self, "_grid_congestion", None)
                if _gc and hasattr(_gc, "_history"):
                    modules_data["grid_congestion"] = _gc._history
            except Exception as _e:
                _LOGGER.debug("Backup grid_congestion mislukt: %s", _e)
            # sensor_hints
            try:
                _sh = getattr(self, "_sensor_hints", None)
                if _sh and hasattr(_sh, "_hints"):
                    modules_data["sensor_hints"] = {
                        "hints": [
                            {
                                "hint_id":    h.hint_id,
                                "entity_id":  h.entity_id,
                                "category":   h.category,
                                "message":    h.message,
                                "score":      h.score,
                                "dismissed":  h.dismissed,
                                "created_ts": h.created_ts,
                            }
                            for h in _sh._hints.values()
                        ]
                    }
            except Exception as _e:
                _LOGGER.debug("Backup sensor_hints mislukt: %s", _e)
            # cost_forecaster
            try:
                _cf = getattr(self, "_cost_forecaster", None)
                if _cf and hasattr(_cf, "_patterns"):
                    modules_data["cost_forecaster"] = {
                        "patterns": {
                            str(h): p.to_dict()
                            for h, p in _cf._patterns.items()
                        }
                    }
            except Exception as _e:
                _LOGGER.debug("Backup cost_forecaster mislukt: %s", _e)
            # nilm_devices — compacte snapshot voor diagnostiek
            try:
                if self._nilm:
                    _nilm_devs = self._nilm.get_devices()
                    modules_data["nilm_devices"] = [
                        {
                            "id":         d.device_id,
                            "name":       d.display_name,
                            "type":       d.device_type,
                            "phase":      d.phase,
                            "power_w":    round(d.current_power, 1),
                            "confidence": round(d.confidence * 100, 0),
                            "on_events":  d.on_events,
                            "confirmed":  d.confirmed,
                            "source":     d.source,
                        }
                        for d in _nilm_devs
                    ]
            except Exception as _e:
                _LOGGER.debug("Backup nilm_devices mislukt: %s", _e)

            if modules_data:
                await backup.async_flush_all(modules_data)

        # v4.5.64: NILM HA Store expliciet flushen bij shutdown
        # (backup hierboven is alleen diagnostiek — de HA Store is de echte persistentie)
        if getattr(self, "_nilm", None):
            try:
                await self._nilm.async_save()
                _LOGGER.info("CloudEMS NILM: %d apparaten opgeslagen bij afsluiting",
                             len(self._nilm.get_devices()))
            except Exception as _nilm_save_err:
                _LOGGER.warning("CloudEMS NILM: opslaan mislukt bij afsluiting: %s", _nilm_save_err)
        # v4.5.66: BatterySocLearner opslaan bij afsluiting
        if getattr(self, "_battery_soc_learner", None):
            try:
                await self._battery_soc_learner.async_save()
            except Exception as _bsl_save_err:
                _LOGGER.debug("BatterySocLearner: opslaan mislukt bij afsluiting: %s", _bsl_save_err)

        _LOGGER.info("CloudEMS coordinator shut down")

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self):
        self._session = async_get_clientsession(self.hass)
        self._nilm._cloud_ai._session = self._session
        await self._nilm.async_load()
        # v4.0.1: ExportDailyTracker laden
        await self._export_tracker.async_load()
        # v4.0.5: Gas predictor + tariefdetector laden
        await self._gas_predictor.async_load()
        await self._tariff_detector.async_load()
        # v4.0.5: Battery efficiency laden
        await self._battery_eff.async_load()
        # v4.6.387: Gas ringbuffer laden
        _ring_saved = await self._store_gas_ring.async_load()
        if isinstance(_ring_saved, list):
            _now_ms = int(time.time() * 1000)
            self._gas_ring = [p for p in _ring_saved if isinstance(p, dict) and _now_ms - p.get("ts", 0) < self._GAS_RING_TTL]
        # Backfill vanuit HA statistieken als ring leeg of te weinig punten
        if len(self._gas_ring) < 5:
            await self._backfill_gas_ring_from_recorder()
        # v4.5.9: TariffFetcher — actuele EB + markup (CBS API + leren)
        self._tariff_fetcher = TariffFetcher(
            self.hass,
            lambda: async_get_clientsession(self.hass),
            self._config,
        )
        await self._tariff_fetcher.async_setup()
        # v4.1: Prijshistorie laden (overleeft HA-herstart)
        _ph_saved = await self._store_price_history.async_load() or {}
        if isinstance(_ph_saved.get("hours"), list):
            self._price_hour_history = _ph_saved["hours"][-720:]
            self._price_history_last_hour = int(_ph_saved.get("last_hour", 0))
            _LOGGER.info(
                "CloudEMS: %d uur prijshistorie geladen uit opslag",
                len(self._price_hour_history),
            )
        # v4.0.4: BDE Feedback laden
        await self._bde_feedback.async_load()
        # v4.6.498: laad decision outcome learner
        try:
            await self._decision_learner.async_load()
        except Exception as _dol_err:
            _LOGGER.warning("CloudEMS: Decision Learner laden mislukt: %s", _dol_err)
        # v4.5.66: BatterySocLearner laden
        await self._battery_soc_learner.async_load()

        # v4.6.276: AdaptiveHome bridge opstarten (luistert naar AH events)
        await self._ah_bridge.async_setup()
        # v4.5.7: EnergyBalancer geleerde lags laden
        if self._energy_balancer:
            _bal_saved = await self._store_balancer.async_load()
            if isinstance(_bal_saved, dict):
                self._energy_balancer.from_dict(_bal_saved)

        # v2.4.17 Fix 8: Verwijder opgeslagen NILM-devices waarvan source_entity_id
        # nu in de geblokkeerde infra-set zit. Dit treedt op wanneer de gebruiker
        # een P1/DSMR-integratie wijzigt — de oude geleerde devices blijven anders
        # voor altijd in storage staan.
        try:
            _blocked_eids = getattr(self._nilm, "_config_sensor_eids", set())
            if _blocked_eids:
                # Bouw een set van friendly names van geblokkeerde entiteiten
                # zodat we ook kunnen matchen op apparaatnaam (voor devices zonder source_entity_id)
                _blocked_names: set = set()
                for _eid in _blocked_eids:
                    _st = self._safe_state(_eid)
                    if _st:
                        _fname = _st.attributes.get("friendly_name") or _st.name or ""
                        if _fname:
                            _blocked_names.add(_fname.lower().strip())

                _stale_ids = []
                for did, dev in self._nilm._devices.items():
                    if getattr(dev, "source", "") == "smart_plug":
                        continue
                    # Check 1: source_entity_id is geblokkeerd
                    if getattr(dev, "source_entity_id", "") in _blocked_eids:
                        _stale_ids.append(did)
                        continue
                    # Check 2: device naam komt overeen met friendly name van geblokkeerde entity
                    _dev_name = (getattr(dev, "name", "") or "").lower().strip()
                    if _dev_name and _dev_name in _blocked_names:
                        _stale_ids.append(did)

                for did in _stale_ids:
                    _LOGGER.info(
                        "CloudEMS NILM: verwijder stale infra-device '%s' (geblokkeerde naam/entity)",
                        self._nilm._devices[did].name,
                    )
                    del self._nilm._devices[did]
                if _stale_ids:
                    await self._nilm.async_save()

                # v4.4.1: eenmalige cleanup — verwijder devices waarvan de naam
                # overeenkomt met infra-keywords (energiemeter, uurprijzen, enz.).
                # Draait slechts één keer; vlag opgeslagen in review-store.
                try:
                    _review_done = await self._store_review.async_load() or {}
                    if not _review_done.get("infra_keyword_cleanup_v441"):
                        from .nilm.smart_sensor_discovery import SmartSensorDiscovery
                        _kw_stale = []
                        for did, dev in list(self._nilm._devices.items()):
                            if getattr(dev, "source", "") == "smart_plug":
                                continue
                            _dname = (getattr(dev, "name", "") or "").lower()
                            _eid   = (getattr(dev, "source_entity_id", "") or "").lower()
                            _search = f"{_eid} {_dname}"
                            if (SmartSensorDiscovery._EXCLUDE_PATTERNS.search(_search)
                                    or any(sub in _search
                                           for sub in SmartSensorDiscovery._EXCLUDE_SUBSTRINGS)):
                                _kw_stale.append(did)
                        for did in _kw_stale:
                            _LOGGER.info(
                                "CloudEMS NILM: verwijder infra-ghost '%s' (v4.4.1 eenmalig)",
                                self._nilm._devices[did].name,
                            )
                            del self._nilm._devices[did]
                        if _kw_stale:
                            await self._nilm.async_save()
                            _LOGGER.info(
                                "CloudEMS NILM: %d infra-ghost(s) eenmalig opgeruimd",
                                len(_kw_stale),
                            )
                        # Markeer als gedaan — nooit meer uitvoeren
                        _review_done["infra_keyword_cleanup_v441"] = True
                        await self._store_review.async_save(_review_done)

                    # v4.5.6b: aanvullende cleanup — verwijder "Electricity Meter" en andere
                    # hoofdmeter-namen die door eerdere versies in de database zijn opgeslagen.
                    # Gebruikt v456b vlag zodat verbeterde logica opnieuw draait na update.
                    if not _review_done.get("infra_meter_cleanup_v456b"):
                        _INFRA_EXACT_NAMES = {
                            "electricity meter", "energiemeter", "energy meter",
                            "slimme meter", "main meter", "hoofdmeter",
                        }
                        _INFRA_DEVICE_TYPES = {
                            "electricity_meter", "energy_meter", "main_meter", "grid_meter",
                            "smart_meter", "p1_meter", "dsmr", "net_meter",
                        }
                        _INFRA_NAME_SUBSTRINGS = (
                            "electricity meter", "energieverbruik", "energieproductie",
                        )
                        _meter_stale = []
                        for did, dev in list(self._nilm._devices.items()):
                            if getattr(dev, "source", "") == "smart_plug":
                                continue
                            _dname = (getattr(dev, "name", "") or "").lower().strip()
                            _uname = (getattr(dev, "user_name", "") or "").lower().strip()
                            _dtype = (getattr(dev, "device_type", "") or "").lower()
                            # Check op name, user_name én device_type
                            if (
                                _dname in _INFRA_EXACT_NAMES
                                or _uname in _INFRA_EXACT_NAMES
                                or _dtype in _INFRA_DEVICE_TYPES
                                or any(sub in _dname for sub in _INFRA_NAME_SUBSTRINGS)
                                or any(sub in _uname for sub in _INFRA_NAME_SUBSTRINGS)
                                or _dname.startswith("electricity")
                                or _uname.startswith("electricity")
                            ):
                                _meter_stale.append(did)
                        for did in _meter_stale:
                            _LOGGER.info(
                                "CloudEMS NILM: verwijder hoofdmeter-ghost '%s' (v4.5.6b)",
                                self._nilm._devices[did].name,
                            )
                            del self._nilm._devices[did]
                        if _meter_stale:
                            await self._nilm.async_save()
                            _LOGGER.info(
                                "CloudEMS NILM: %d hoofdmeter-ghost(s) opgeruimd (v4.5.6b)",
                                len(_meter_stale),
                            )
                        _review_done["infra_meter_cleanup_v456b"] = True
                        await self._store_review.async_save(_review_done)
                except Exception as _kw_err:
                    _LOGGER.debug("CloudEMS: keyword cleanup mislukt: %s", _kw_err)
        except Exception as _cl_err:
            _LOGGER.warning("CloudEMS: post-load cleanup mislukt: %s", _cl_err)

        # v2.4.17: laad persistente review-history en adaptieve drempels
        try:
            _review_data = await self._store_review.async_load() or {}
            self._review_skip_set  = set(_review_data.get("skip_set", []))
            self._review_skip_history = list(_review_data.get("skip_history", []))
        except Exception as _re:
            _LOGGER.warning("CloudEMS: review-history laden mislukt: %s", _re)
        try:
            self._adaptive_thresholds = await self._store_adaptive.async_load() or {}
            # Stuur direct door naar detector zodat get_devices_for_ha ze direct gebruikt
            if self._adaptive_thresholds:
                self._nilm.set_adaptive_overrides(self._adaptive_thresholds)
        except Exception as _ae:
            _LOGGER.warning("CloudEMS: adaptieve drempels laden mislukt: %s", _ae)

        # ── Watchdog ──────────────────────────────────────────────────────────
        # Haal entry_id op via de config entries — coordinator is gekoppeld aan één entry
        entry_id = None
        for eid, coord in self.hass.data.get("cloudems", {}).items():
            if coord is self:
                entry_id = eid
                break
        if entry_id is None:
            # Fallback: zoek via config entries op domein
            entries = self.hass.config_entries.async_entries("cloudems")
            if entries:
                entry_id = entries[0].entry_id
        if entry_id:
            self._watchdog = CloudEMSWatchdog(self.hass, entry_id)
            await self._watchdog.async_setup()
            _LOGGER.info("CloudEMS Watchdog actief voor entry %s", entry_id)

            # v4.6.13: EntityDeviceLog — bijhouden van alle aangemakte entities + orphan cleanup
            try:
                from .entity_device_log import EntityDeviceLog
                entry_obj = self.hass.config_entries.async_get_entry(entry_id)
                if entry_obj:
                    self._entity_device_log = EntityDeviceLog(self.hass, entry_obj)
                    await self._entity_device_log.async_load()
                    _LOGGER.info("CloudEMS EntityDeviceLog actief voor entry %s", entry_id)
            except Exception as _edl_err:
                _LOGGER.warning("CloudEMS EntityDeviceLog kon niet starten: %s", _edl_err)
        else:
            _LOGGER.warning("CloudEMS Watchdog: kon entry_id niet bepalen, watchdog uitgeschakeld")

        # ── LearningBackup: tweede schrijfpad voor alle leerdata ──────────────
        from .energy_manager.learning_backup import LearningBackup
        self._learning_backup = LearningBackup(self.hass)
        await self._learning_backup.async_setup()

        # v4.5.11: injecteer high-log callback in NILM detector zodat bijzondere
        # events (nieuwe apparaten, fase-wijzigingen, false positives, auto-prune)
        # naar cloudems_high.log gaan zonder directe afhankelijkheid op LearningBackup.
        if hasattr(self._nilm, "set_high_log_callback"):
            self._nilm.set_high_log_callback(self._learning_backup.async_log_high)

        # v4.5.11: log infra-apparaten die bij het laden verwijderd zijn (kon niet
        # eerder omdat LearningBackup nog niet beschikbaar was bij async_load()).
        _infra_removed = getattr(self._nilm, "_infra_removed_on_load", [])
        if _infra_removed:
            import asyncio as _aio_ir
            _aio_ir.ensure_future(self._learning_backup.async_log_high(
                "nilm_infra_removed_on_load",
                {"count": len(_infra_removed), "device_ids": _infra_removed},
            ))
            self._nilm._infra_removed_on_load = []

        # ── Externe providers (v4.5.0) ────────────────────────────────────────
        try:
            from .provider_manager import ProviderManager
            self._provider_manager = ProviderManager(self.hass, self._config)
            await self._provider_manager.async_setup()
            _LOGGER.info("CloudEMS ProviderManager: %d provider(s) actief",
                         self._provider_manager.active_count)
        except Exception as _pm_exc:
            _LOGGER.warning("CloudEMS ProviderManager setup mislukt: %s", _pm_exc)
            self._provider_manager = None

        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        self._prices = EnergyPriceFetcher(
            country=country,
            session=self._session,
            api_key=self._config.get(CONF_CLOUD_API_KEY),
            time_zone=self.hass.config.time_zone,
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
        self._fault_notifier  = FaultNotifier(self.hass)
        self._merge_advisor   = ComponentMergeAdvisor(self.hass)

        # v4.3.26: SmartPowerEstimator — ingebouwde PowerCalc, nul configuratie
        self._power_estimator = SmartPowerEstimator(self.hass)
        await self._power_estimator.async_setup(
            self._store_power_estimator,
            self._nilm,
            config=self._config,
        )

        self._ev_session = EVSessionLearner(self.hass)
        await self._ev_session.async_setup()
        # InfluxDB writer (optioneel)
        self._influxdb = _InfluxDBWriter(self.hass, self._config) if _InfluxDBWriter else None
        if self._influxdb and self._influxdb.enabled:
            _LOGGER.info("CloudEMS InfluxDB: actief → %s/%s", self._config.get("influxdb_url",""), self._config.get("influxdb_bucket","cloudems"))

        self._nilm_schedule = NILMScheduleLearner(self.hass)
        await self._nilm_schedule.async_setup()

        # v1.11.0: Thermal house model (always active — needs outside_temp + heating power)
        from .energy_manager.thermal_model import ThermalHouseModel
        self._thermal_model = ThermalHouseModel(self.hass)
        await self._thermal_model.async_setup()

        # v4.4.5: Vloer thermische buffer (EMHASS-geïnspireerd physics model)
        from .energy_manager.floor_thermal_buffer import FloorThermalBuffer
        _floor_area = float(self._config.get("floor_area_m2", 30.0))
        _floor_type = self._config.get("floor_type", "beton")
        self._floor_buffer = FloorThermalBuffer(self.hass, floor_area_m2=_floor_area, floor_type=_floor_type)
        await self._floor_buffer.async_setup()

        # v4.4.5: ML verbruiksforecaster (k-NN met temperatuur + seizoensfeatures)
        from .energy_manager.consumption_ml_forecast import MLConsumptionForecaster
        self._ml_forecaster = MLConsumptionForecaster(self.hass)
        await self._ml_forecaster.async_setup()

        # v1.11.0: Self-consumption ratio tracker
        from .energy_manager.self_consumption import SelfConsumptionTracker
        self._self_consumption = SelfConsumptionTracker(self.hass)
        await self._self_consumption.async_setup()

        # v4.6.584: NILM apparaatgroepen tracker
        self._nilm_group_tracker = NilmGroupTracker(self.hass)
        await self._nilm_group_tracker.async_setup()

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

        # v4.1: Overduration guard — apparaten die te lang aanstaan
        from .energy_manager.appliance_overduration import ApplianceOverdurationGuard
        self._overduration_guard = ApplianceOverdurationGuard()
        _LOGGER.debug("ApplianceOverdurationGuard geïnitialiseerd")

        # v2.2.2: maandrapportage
        notify_svc = cfg.get("notification_service", "")
        self._monthly_report = MonthlyReportGenerator(self.hass, notify_service=notify_svc)
        # v2.4.0: dagelijkse samenvatting
        from .energy_manager.daily_summary import DailySummaryGenerator
        self._daily_summary = DailySummaryGenerator(self.hass, notify_service=notify_svc)
        # v2.2.2: installatie-score (stateless, berekening on-demand)
        self._install_score = InstallationScoreCalculator(self._config)
        # v2.2.3: gedragscoach (stateless), energy label, saldering simulator
        self._behaviour_coach = BehaviourCoach()
        self._energy_label    = EnergyLabelSimulator()
        self._saldering_sim   = SalderingSimulator()
        self._saldering_cal   = SalderingCalibrator(hass=self.hass)
        await self._saldering_cal.async_setup()
        # v3.9: BatterySavingsTracker — saldering-bewuste besparingssensor
        if cfg.get("battery_soc_entity") or cfg.get("battery_scheduler_enabled"):
            self._battery_savings = BatterySavingsTracker(self.hass, cfg)
            await self._battery_savings.async_setup()
        # v2.4.0: nieuwe modules
        from .energy_manager.gas_analysis import GasAnalyzer
        from .energy_manager.climate_epex import ClimateEpexController, ClimateEpexDevice
        from .energy_manager.energy_budget import EnergyBudgetTracker
        from .energy_manager.appliance_roi import ApplianceROICalculator
        from .energy_manager.solar_dimmer import SolarDimmer
        _gas_eid = self._config.get("gas_sensor", "") or ""
        self._gas_analysis = GasAnalyzer(self.hass, gas_entity_id=_gas_eid)
        await self._gas_analysis.async_setup()
        if hasattr(self._gas_analysis, "set_log_callback"):
            self._gas_analysis.set_log_callback(self._learning_backup.async_log_high)

        # Climate EPEX compensatie
        _ce_devices_cfg = self._config.get("climate_epex_devices", [])
        if self._config.get("climate_epex_enabled") and _ce_devices_cfg:
            _ce_devices = [ClimateEpexDevice.from_dict(d) for d in _ce_devices_cfg]
            self._climate_epex = ClimateEpexController(self.hass, _ce_devices)
            await self._climate_epex.async_setup()
            self._climate_epex.set_log_callback(self._learning_backup.async_log_high)
            _LOGGER.info("ClimateEpex: %d devices geladen", len(_ce_devices))
        # Haal periode-starts op uit HA history zodra HA volledig geladen is
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        import homeassistant.core as _ha_core
        async def _gas_bootstrap(_event=None):
            if hasattr(self._gas_analysis, "_ensure_period_starts"):
                await self._gas_analysis._ensure_period_starts()
        if self.hass.state == _ha_core.CoreState.running:
            self.hass.async_create_task(_gas_bootstrap())
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _gas_bootstrap)
        self._energy_budget = EnergyBudgetTracker(self.hass, self._config)
        await self._energy_budget.async_setup()
        self._appliance_roi = ApplianceROICalculator(hass=self.hass)
        await self._appliance_roi.async_setup()
        self._solar_dimmer  = SolarDimmer(self.hass, self._config, self)

        # v3.0: Setup health check — controleert alle geconfigureerde entiteiten
        from .energy_manager.health_check import SetupHealthCheck
        self._health_checker = SetupHealthCheck(self.hass, cfg,
                                                startup_time=getattr(self, "_init_mono", time.monotonic()))
        self._health_report  = await self._health_checker.async_run()
        self._data["health_check"] = self._health_report.to_dict()

        # v3.0: System Guardian — autonome bewakingsrobot
        from .guardian import SystemGuardian
        self._guardian = SystemGuardian(self.hass, cfg, self)
        await self._guardian.async_setup()

        # v1.12.0: Clipping verlies calculator
        from .energy_manager.clipping_loss import ClippingLossCalculator
        self._clipping_loss = ClippingLossCalculator(self.hass)
        await self._clipping_loss.async_setup()

        # v1.16.0: Structurele schaduwdetector
        from .energy_manager.shadow_detector import ShadowDetector
        self._shadow_detector = ShadowDetector(self.hass)
        await self._shadow_detector.async_setup()

        # v1.12.0: Verbruik categorieën tracker
        from .energy_manager.consumption_categories import ConsumptionCategoryTracker
        self._categories = ConsumptionCategoryTracker(self.hass)
        await self._categories.async_setup()

        # v1.20: Virtuele stroommeter per kamer
        from .energy_manager.room_meter import RoomMeterEngine
        self._room_meter = RoomMeterEngine(self.hass)
        await self._room_meter.async_setup()

        # v4.5.51: Meter topologie leren (root→meter→meter→device boom)
        from .meter_topology import MeterTopologyLearner
        self._meter_topology = MeterTopologyLearner()
        _topo_saved = await self._store_topo.async_load()
        if _topo_saved:
            self._meter_topology.load(_topo_saved)
            _LOGGER.debug("CloudEMS: meter topologie geladen (%d relaties)", len(_topo_saved.get("relations", [])))

        # v1.21: Battery Provider Registry (Zonneplan Nexus + toekomstige leveranciers)
        # Importeer providers zodat ze zichzelf registreren
        from .energy_manager import zonneplan_bridge as _zp_bridge_mod  # noqa: F401
        from .energy_manager.battery_provider import BatteryProviderRegistry
        self._battery_providers = BatteryProviderRegistry(self.hass, cfg)
        await self._battery_providers.async_setup()
        # Backwards-compat alias voor services die nog _zonneplan_bridge verwachten
        self._zonneplan_bridge = self._battery_providers.get_provider("zonneplan")

        # v1.20: Goedkope uren schakelaar planner
        from .energy_manager.cheap_switch_scheduler import CheapSwitchScheduler
        _cheap_switch_cfgs = cfg.get("cheap_switches", []) or []
        self._cheap_switch_scheduler = CheapSwitchScheduler(self.hass, _cheap_switch_cfgs)

        # v4.2: Slimme uitstelmodus — detecteer & herstel bij dure stroom
        from .energy_manager.smart_delay_switch import SmartDelayScheduler
        _smart_delay_cfgs = cfg.get("smart_delay_switches", []) or []
        self._smart_delay_scheduler = SmartDelayScheduler(self.hass, _smart_delay_cfgs)

        # v4.6.217: NILM Load Shifter — automatisch uitstellen via NILM detectie
        from .energy_manager.nilm_load_shifter import NILMLoadShifter
        if cfg.get("nilm_load_shifting_enabled", True):
            self._nilm_load_shifter = NILMLoadShifter(self._provider, {**cfg, '_hass': self.hass})
        else:
            self._nilm_load_shifter = None

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

        # v1.22: laad persistente NILM toggle-staat vóór HybridNILM setup
        await self._load_nilm_toggles()
        # v4.6.484: laad anchor kWh tellers
        try:
            import datetime as _dt_akwh
            _akwh_data = await self._store_anchor_kwh.async_load() or {}
            _today_key = _dt_akwh.date.today().isoformat()
            if _akwh_data.get("day") == _today_key:
                self._anchor_kwh_today     = _akwh_data.get("today", {})
                self._anchor_kwh_yesterday = _akwh_data.get("yesterday", {})
                self._anchor_kwh_day       = _today_key
        except Exception as _akwh_err:
            _LOGGER.debug("CloudEMS: anchor kWh laden mislukt: %s", _akwh_err)
        # v4.6.493: laad per-uur solar kWh (persistent over herstart)
        try:
            import datetime as _dt_pvh_load
            _pvh_data = await self._store_pv_hourly.async_load() or {}
            _pvh_today_key = _dt_pvh_load.date.today().isoformat()
            _pvh_yesterday_key = (_dt_pvh_load.date.today() - _dt_pvh_load.timedelta(days=1)).isoformat()

            if _pvh_data.get("day") == _pvh_today_key:
                _restored_today = _pvh_data.get("today", [0.0] * 24)
                # v4.6.554: sanity check — max realistisch ~200 kWh/dag
                _restored_sum = sum(_restored_today)
                if _restored_sum > 200.0:
                    _LOGGER.warning(
                        "CloudEMS: pv_today_hourly_kwh in storage bevat onrealistische waarde %.1f kWh "
                        "(max 200 kWh/dag) — data gereset om corrupt accumulate te voorkomen",
                        _restored_sum,
                    )
                    _restored_today = [0.0] * 24
                self._pv_today_hourly_kwh     = _restored_today
                self._pv_yesterday_hourly_kwh = _pvh_data.get("yesterday", [0.0] * 24)
                self._pv_hourly_day           = _pvh_today_key
                _LOGGER.info(
                    "CloudEMS: per-uur solar kWh hersteld voor %s (vandaag=%.3f kWh, gisteren=%.3f kWh)",
                    _pvh_today_key,
                    sum(self._pv_today_hourly_kwh),
                    sum(self._pv_yesterday_hourly_kwh),
                )
            elif _pvh_data.get("day") == _pvh_yesterday_key:
                # v4.6.560: HA was offline gedurende dagwisseling — storage heeft gisteren's data
                # Herstel die als yesterday zodat de solar grafiek gisteren correct toont
                _yst_restored = _pvh_data.get("today", [0.0] * 24)
                _yst_sum = sum(_yst_restored)
                if _yst_sum > 200.0:
                    _yst_restored = [0.0] * 24
                self._pv_yesterday_hourly_kwh = _yst_restored
                self._pv_today_hourly_kwh     = [0.0] * 24
                self._pv_hourly_day           = ""  # triggers rollover bij eerste cyclus
                _LOGGER.info(
                    "CloudEMS: HA was offline bij dagwisseling — gisteren (%.3f kWh) hersteld uit storage",
                    sum(self._pv_yesterday_hourly_kwh),
                )
        except Exception as _pvh_load_err:
            _LOGGER.debug("CloudEMS: pv_hourly laden mislukt: %s", _pvh_load_err)
        _LOGGER.info("CloudEMS: BatteryEPEXScheduler actief")

        # v1.10.2: Sensor hint engine (passive pattern observer)
        from .energy_manager.sensor_hint import SensorHintEngine
        self._sensor_hints = SensorHintEngine(self.hass, cfg)
        await self._sensor_hints.async_setup()
        # v4.6.531: koppel hint-engine aan Kirchhoff monitor
        if self._kirchhoff_monitor:
            self._kirchhoff_monitor.set_hint_engine(self._sensor_hints)
        # v4.6.533: koppel hint-engine aan alle nieuwe modules
        for _mod in (
            self._phase_consistency, self._inverter_efficiency,
            self._tariff_consistency, self._wiring_topology,
            self._feedback_loop, self._sign_consistency,
            self._appliance_degradation, self._standby_drift,
            self._bde_quality, self._shutter_comfort,
            self._integration_latency, self._p1_quality,
            self._savings_attribution, self._arbitrage_quality,
            self._topology_validator, self._nilm_double_count,
        ):
            if _mod and hasattr(_mod, "set_hint_engine"):
                try:
                    _mod.set_hint_engine(self._sensor_hints)
                except Exception:
                    pass

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
            # v4.6.512: realtime fase-stroom updates via P1 callback
            def _on_p1_telegram(t) -> None:
                try:
                    import asyncio as _aio
                    _aio.ensure_future(self._process_p1_realtime(t))
                except Exception:
                    pass
            self._p1_reader.set_telegram_callback(_on_p1_telegram)

        if cfg.get(CONF_PEAK_SHAVING_ENABLED, False):
            from .energy_manager.peak_shaving import PeakShaving
            self._peak_shaving = PeakShaving(self.hass, cfg)
            await self._peak_shaving.async_setup()

        # Boiler controller (v2.0: cascade-groepen + v1.x enkelvoudige configs)
        boiler_configs = cfg.get("boiler_configs", [])
        boiler_groups  = cfg.get("boiler_groups",  [])
        # boiler_groups_enabled: als groepen geconfigureerd zijn, altijd actief
        # (de enabled-toggle is verwijderd uit de wizard; als je groepen hebt, zijn ze aan)
        boiler_enabled = cfg.get("boiler_groups_enabled", True) or bool(boiler_groups)
        # Combineer: cascade-groepen (v2.0) + enkelvoudige configs (v1.x backwards-compat)
        combined_configs = (boiler_groups if boiler_enabled else []) + boiler_configs
        if combined_configs:
            from .energy_manager.boiler_controller import BoilerController
            self._boiler_ctrl = BoilerController(self.hass, combined_configs)
            await self._boiler_ctrl.async_setup()
            n_groups = len([c for c in combined_configs if c.get("group")])
            n_single = len(combined_configs) - n_groups
            _LOGGER.info(
                "CloudEMS: BoilerController actief (%d groepen, %d enkelvoudig)",
                n_groups, n_single,
            )

        # Pool controller (zwembad filter + warmtepomp)
        pool_cfg = cfg.get("pool", {}) or {}
        _pool_filter_eid = pool_cfg.get("filter_entity", "")
        _pool_heat_eid   = pool_cfg.get("heat_entity",   "")
        if _pool_filter_eid or _pool_heat_eid:
            from .energy_manager.pool_controller import PoolController
            self._pool_ctrl = PoolController(
                hass                 = self.hass,
                filter_entity        = _pool_filter_eid,
                heat_entity          = _pool_heat_eid,
                temp_entity          = pool_cfg.get("temp_entity",          ""),
                uv_entity            = pool_cfg.get("uv_entity",            ""),
                robot_entity         = pool_cfg.get("robot_entity",         ""),
                heat_setpoint        = float(pool_cfg.get("heat_setpoint",  28.0)),
                filter_power_entity  = pool_cfg.get("filter_power_entity",  ""),
                heat_power_entity    = pool_cfg.get("heat_power_entity",    ""),
            )
            await self._pool_ctrl.async_load()
            _LOGGER.info("CloudEMS: PoolController actief (filter=%s, heat=%s)",
                         _pool_filter_eid, _pool_heat_eid)
        else:
            self._pool_ctrl = None

        # Lamp Circulation — intelligente lampenbeveiliging + energiebesparing (v1.25.9)
        lamp_cfg = cfg.get("lamp_circulation", {}) or {}
        _lamp_entities = lamp_cfg.get("light_entities", []) or []
        # Auto-discovery: als geen lampen handmatig geconfigureerd zijn, alle light.* entities
        # uit Home Assistant ophalen zodat de pagina meteen werkt zonder extra configuratie.
        if not _lamp_entities:
            _lamp_entities = [
                s.entity_id
                for s in self.hass.states.async_all("light")
            ]
            if _lamp_entities:
                _LOGGER.info(
                    "LampCirculation: geen lampen geconfigureerd — auto-discovery: %d lampen gevonden",
                    len(_lamp_entities),
                )
        # Altijd een LampCirculationController aanmaken — ook als er nu 0 lampen zijn.
        # De lazy re-discovery in de update-loop vult de lampenlijst zodra HA volledig geladen is.
        from .energy_manager.lamp_circulation import LampCirculationController
        self._lamp_circulation = LampCirculationController(self.hass)

        # v4.6.445: Lamp Automation Engine — los van circulatie
        self._lamp_auto = LampAutomationEngine(self.hass, self._config)
        _la_cfg = self._config.get("lamp_auto_lamps", [])
        if _la_cfg:
            self._lamp_auto.configure(_la_cfg)
        if _lamp_entities:
            self._lamp_circulation.configure(
                light_entities = _lamp_entities,
                excluded_ids   = lamp_cfg.get("excluded_ids", []),
                enabled        = lamp_cfg.get("enabled", True),
                min_confidence = float(lamp_cfg.get("min_confidence", 0.55)),
                night_start_h  = int(lamp_cfg.get("night_start_h", 22)),
                night_end_h    = int(lamp_cfg.get("night_end_h", 7)),
            )
            _LOGGER.info(
                "CloudEMS: LampCirculation v3 actief (%d lampen, %d uitgesloten, sun=%s)",
                len(_lamp_entities),
                len(lamp_cfg.get("excluded_ids", [])),
                lamp_cfg.get("use_sun_entity", True),
            )
        else:
            _LOGGER.info(
                "CloudEMS: LampCirculation aangemaakt — wacht op lazy-discovery van light.* entiteiten"
            )
        # ── Rolluiken (v3.9.0) ────────────────────────────────────────────────
        shutter_configs = cfg.get(CONF_SHUTTER_CONFIGS, [])
        shutter_count   = int(cfg.get(CONF_SHUTTER_COUNT, 0))
        # Controller altijd aanmaken als er configs zijn — _shutter_enabled bepaalt
        # alleen of beslissingen uitgevoerd worden, niet of de controller bestaat.
        # Zonder controller worden text/number/sensor entities nooit gevuld.
        if shutter_configs:
            from .energy_manager.shutter_controller import ShutterController
            from .energy_manager.shutter_thermal_learner import ShutterThermalLearner
            self._shutter_learner = ShutterThermalLearner(self.hass)
            await self._shutter_learner.async_setup()
            self._shutter_ctrl    = ShutterController(
                self.hass,
                configs=shutter_configs,
                groups=cfg.get(CONF_SHUTTER_GROUPS, []),
            )
            self._shutter_ctrl.set_learner(self._shutter_learner)
            self._shutter_ctrl._coordinator = self   # voor refresh na ext. detectie
            # Externe bediening detectie opstarten
            await self._shutter_ctrl.async_setup()
            await self._shutter_ctrl.async_load_timers()
            # v4.6.502: koppel DOL aan shutter controller voor bias-toepassing
            if getattr(self, "_decision_learner", None):
                self._shutter_ctrl._decision_learner = self._decision_learner

            # v4.6.465: Thermal gain learner — leert pid_kp per rolluik
            try:
                from .energy_manager.shutter_thermal_learner import ShutterThermalLearner as _ThermalLearner
                self._shutter_thermal_learner = _ThermalLearner(self.hass)
                await self._shutter_thermal_learner.async_setup()
                self._shutter_ctrl._thermal_learner = self._shutter_thermal_learner
                _LOGGER.info("CloudEMS: ShutterThermalLearner actief")
            except Exception as _tl_err:
                _LOGGER.warning("CloudEMS: ShutterThermalLearner kon niet starten: %s", _tl_err)
                self._shutter_thermal_learner = None

            # v4.6.464: ShutterPIDLearner — gain learning per rolluik per uur + seizoen
            try:
                from .energy_manager.shutter_pid_learner import ShutterPIDLearner as _PIDLearner
                self._shutter_pid_learner = _PIDLearner(self.hass)
                await self._shutter_pid_learner.async_setup()
                self._shutter_ctrl.set_pid_learner(self._shutter_pid_learner)
                _LOGGER.info("CloudEMS: ShutterPIDLearner actief")
            except Exception as _pl_err:
                _LOGGER.warning("CloudEMS: ShutterPIDLearner kon niet starten: %s", _pl_err)
                self._shutter_pid_learner = None

            # v4.3.7: weather entity + presence entities koppelen
            _weather_eid = cfg.get("shutter_weather_entity") or ""
            if _weather_eid:
                self._shutter_ctrl.set_weather_entity(_weather_eid)
            _presence = cfg.get("shutter_presence_entities") or []
            if _presence:
                self._shutter_ctrl.set_presence_entities(_presence)
            _global_smoke = cfg.get("shutter_global_smoke_sensor") or ""
            if _global_smoke:
                self._shutter_ctrl.set_global_smoke_sensor(_global_smoke)
            # Input helpers aanmaken (tijden/setpoint/seizoen/aanwezigheid per rolluik)
            try:
                await self._async_ensure_shutter_helpers(shutter_configs)
            except Exception as _helpers_exc:
                _LOGGER.warning(
                    "CloudEMS: shutter helpers aanmaken mislukt (niet kritiek): %s", _helpers_exc
                )
            _LOGGER.info(
                "CloudEMS: ShutterController actief — %d rolluiken", shutter_count
            )
            # Runtime discovery: luister naar entity registry wijzigingen voor nieuwe temp sensoren
            self._shutter_unsubscribe_registry = self.hass.bus.async_listen(
                "entity_registry_updated",
                self._async_on_entity_registry_updated,
            )
            # Direct check: zijn er al temp sensoren in de zelfde ruimte die nog niet geconfigureerd zijn?
            try:
                await self._async_discover_shutter_temp_sensors()
            except Exception as _disc_exc:
                _LOGGER.warning("CloudEMS: temp sensor discovery mislukt (niet kritiek): %s", _disc_exc)
        inverter_configs = cfg.get(CONF_INVERTER_CONFIGS, [])
        if inverter_configs:
            from .energy_manager.solar_learner import SolarPowerLearner
            _fuse_a = float(self._config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT))
            self._solar_learner = SolarPowerLearner(self.hass, inverter_configs, fuse_a=_fuse_a)
            await self._solar_learner.async_setup(backup=getattr(self, "_learning_backup", None))

            if cfg.get(CONF_ENABLE_MULTI_INVERTER, False):
                from .energy_manager.multi_inverter_manager import MultiInverterManager, InverterControl
                controls = [
                    InverterControl(
                        entity_id    =inv["entity_id"],
                        control_entity=inv.get("control_entity", inv["entity_id"]),
                        label        =inv.get("label",""),
                        priority     =int(inv.get("priority",1)),
                        min_power_pct=float(inv.get("min_power_pct",0.0)),
                        rated_power_w=float(inv["rated_power_w"]) if inv.get("rated_power_w") else None,
                    ) for inv in inverter_configs
                ]
                max_phase_a = {
                    phase: float(cfg.get(f"max_current_{phase.lower()}") or DEFAULT_MAX_CURRENT)  # v4.6.271: or-fallback voorkomt float(None) crash bij None-waarde in config (issue #28)
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

                # ── v1.25: Registreer extra probe-kandidaten bij PhaseProber ──
                # Alleen als de prober beschikbaar is (omvormers met dimmer gevonden).
                # Veilige lasten: EV-lader, boiler, batterij (laden) — de gebruiker
                # merkt een korte puls nooit bij deze apparaten.
                _prober = self._multi_inv_manager._phase_prober
                if _prober:
                    from .energy_manager.phase_prober import ProbeCandidate, CandidateType

                    # EV-lader
                    ev_eid    = cfg.get("ev_charger_entity", "")
                    ev_switch = cfg.get("ev_charger_switch", "")
                    if ev_eid and ev_switch:
                        _prober.register_candidate(ProbeCandidate(
                            entity_id      = ev_eid,
                            control_entity = ev_switch,
                            candidate_type = CandidateType.EV_CHARGER,
                            label          = "EV-lader",
                        ))

                    # Boilers — elk met een schakelaar
                    for _bc in cfg.get("boiler_configs", []):
                        _beid = _bc.get("entity_id", "")
                        if _beid:
                            _prober.register_candidate(ProbeCandidate(
                                entity_id      = _beid,
                                control_entity = _beid,  # boiler entity is zelf schakelbaar
                                candidate_type = CandidateType.BOILER,
                                label          = _bc.get("label", "Boiler"),
                            ))

                    # Batterij (laad-entity)
                    for _bat in cfg.get("battery_configs", []):
                        _bat_charge = _bat.get("charge_entity", "")
                        _bat_sensor = _bat.get("sensor_entity", "")
                        if _bat_charge and _bat_sensor:
                            _prober.register_candidate(ProbeCandidate(
                                entity_id      = _bat_sensor,
                                control_entity = _bat_charge,
                                candidate_type = CandidateType.BATTERY,
                                label          = _bat.get("label", "Batterij"),
                                rated_power_w  = float(_bat.get("max_charge_w", 0)) or None,
                            ))

            from .energy_manager.pv_forecast import PVForecast
            self._pv_forecast = PVForecast(
                hass=self.hass,
                inverter_configs=inverter_configs,
                latitude =self.hass.config.latitude  or 52.1,
                longitude=self.hass.config.longitude or 5.3,
                session  =self._session,
            )
            await self._pv_forecast.async_setup(backup=getattr(self, "_learning_backup", None))

        # v4.5.7: sanity guard + Kirchhoff-balancer (vervangt SensorEMALayer volledig)
        self._sensor_sanity = SensorSanityGuard(self._config, hass=self.hass)
        self._energy_balancer = EnergyBalancer()
        # v4.6.522: initialiseer grid-interval EMA op basis van geconfigureerd DSMR-type
        # zodat de staleness-detectie direct correct werkt (niet pas na 20+ cycli)
        _dsmr_t = cfg.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL)
        if _dsmr_t == DSMR_TYPE_5:
            self._energy_balancer._grid.interval_ema = 1.0
        elif _dsmr_t == DSMR_TYPE_4:
            self._energy_balancer._grid.interval_ema = 10.0
        # DSMR_TYPE_UNIVERSAL: standaard 10.0 blijft staan

        # v4.6.522: Sensor interval registry
        self._sensor_interval_registry = SensorIntervalRegistry()
        await self._sensor_interval_registry.async_setup(self.hass)

        # v4.6.522: gedeelde StateReader — nieuwe modules gebruiken deze
        # i.p.v. rechtstreeks hass.states.get() aan te roepen.
        # Koppelt interval-registry automatisch aan alle reads.
        self._state_reader = StateReader(
            hass=self.hass,
            interval_registry=self._sensor_interval_registry,
        )
        # v4.6.530: zelflerend fase-stroom fusie model
        _phase_count = int(cfg.get(CONF_PHASE_COUNT, 1))
        _phases = ["L1", "L2", "L3"] if _phase_count == 3 else ["L1"]
        self._phase_fusion = PhaseCurrentFusion(self.hass, _phases)
        await self._phase_fusion.async_setup()

        # v4.6.531: Kirchhoff drift monitor
        self._kirchhoff_monitor = KirchhoffDriftMonitor(self.hass)
        await self._kirchhoff_monitor.async_setup()

        # v4.6.533: alle kwaliteits- en consistentie-modules
        self._phase_consistency = PhasePowerConsistencyMonitor(self.hass)
        await self._phase_consistency.async_setup()

        self._inverter_efficiency = InverterEfficiencyTracker(self.hass)
        await self._inverter_efficiency.async_setup()

        self._tariff_consistency = TariffConsistencyMonitor(self.hass)
        await self._tariff_consistency.async_setup()

        self._wiring_topology = WiringTopologyValidator(self.hass)
        await self._wiring_topology.async_setup()

        self._feedback_loop = GridFeedbackLoopDetector(self.hass, cfg)
        self._sign_consistency = SignConsistencyLearner(self.hass)
        await self._sign_consistency.async_setup()

        self._appliance_degradation = ApplianceDegradationMonitor(self.hass)
        await self._appliance_degradation.async_setup()

        self._standby_drift = StandbyDriftTracker(self.hass)
        await self._standby_drift.async_setup()

        self._bde_quality = BDEDecisionQualityTracker(self.hass)
        await self._bde_quality.async_setup()

        self._shutter_comfort = ShutterComfortLearner(self.hass)
        await self._shutter_comfort.async_setup()

        self._integration_latency = IntegrationLatencyMonitor(self.hass)
        await self._integration_latency.async_setup()

        self._p1_quality = P1TelegramQualityMonitor(self.hass)
        await self._p1_quality.async_setup()

        self._savings_attribution = SavingsAttributionTracker(self.hass)
        await self._savings_attribution.async_setup()

        self._arbitrage_quality = TariffArbitrageQuality(self.hass)
        await self._arbitrage_quality.async_setup()

        # v4.6.535: tussenmeter topologie-validatie
        self._topology_validator = TopologyConsistencyValidator(self.hass)
        await self._topology_validator.async_setup()
        self._topology_feeder    = TopologyAutoFeeder(self.hass, cfg)
        self._nilm_double_count  = NILMDoubleCountDetector()
        _LOGGER.info("CloudEMS EnergyBalancer geïnitialiseerd (v4.5.7)")
        await self._sensor_sanity.async_setup()
        # v1.15.0: Absence detector + climate preheat advisor
        self._absence = AbsenceDetector(self.hass)
        await self._absence.async_setup()
        self._preheat = ClimatePreHeatAdvisor()
        # v3.0: ZonePresenceManager — volledig zelflerend, zero-config
        # Vindt automatisch alle person.*, device_tracker.*, BLE/WiFi, PIR en kalenders
        # Alleen optionele overrides via config nodig
        self._zone_presence = ZonePresenceManager(self.hass, {
            "presence_calendar_entities": self._config.get("presence_calendar_entities", []),
            "ble_wifi_overrides": self._config.get("ble_wifi_overrides", []),
        })
        await self._zone_presence.async_setup()
        # v1.15.0: PV forecast accuracy tracker
        self._pv_accuracy = PVForecastAccuracyTracker(self.hass)
        await self._pv_accuracy.async_setup()
        # v1.15.0: Heat pump COP learner
        self._hp_cop = HeatPumpCOPLearner(self.hass)
        await self._hp_cop.async_setup()

        # v2.6: slaapstand detector (standaard uit)
        # v3.9: gebruik de al geladen _sleep_detector_enabled waarde (uit _load_nilm_toggles)
        #        zodat de staat na herstart bewaard blijft.
        self._sleep_detector = SleepDetector(self.hass, self._config)
        self._sleep_detector.set_enabled(self._sleep_detector_enabled)
        # v2.6: capaciteits-piekbewaker (met persistentie)
        self._capacity_peak  = CapacityPeakMonitor(self._config)
        await self._capacity_peak.async_setup(self.hass)
        # LoadPlanAccuracyTracker — vergelijkt plan met werkelijkheid
        self._load_plan_accuracy = LoadPlanAccuracyTracker(self.hass)
        await self._load_plan_accuracy.async_setup()
        # InstallationScore trending setup
        if self._install_score:
            await self._install_score.async_setup(self.hass)
        # v2.6: negatief tarief + wassen-verschuiver
        self._neg_tariff     = NegativeTariffCatcher(self.hass, self._config)
        self._shift_advisor  = ApplianceShiftAdvisor(self.hass, self._config)
        # v2.6: wekelijkse vergelijking + blueprint generator
        self._weekly_cmp     = WeeklyComparison(self.hass)
        self._blueprint_gen  = BlueprintGenerator(self.hass, self._config)

        # v2.6: multi-zone klimaatbeheer (auto-discovery via HA areas)
        from .energy_manager.zone_climate_manager import ZoneClimateManager
        self._zone_climate = ZoneClimateManager(self.hass, self._config)
        if bool(self._config.get("climate_zones_enabled") or self._config.get("climate_mgr_enabled")):
            await self._zone_climate.async_setup()

        # v2.6: smart climate manager (VT/TRV/airco/switch + aanwezigheid)
        self._smart_climate = SmartClimateManager(self.hass, self._config)
        if bool(self._config.get("climate_zones_enabled") or self._config.get("climate_mgr_enabled")):
            await self._smart_climate.async_setup()

        # v2.6: wasbeurt cyclus detector
        self._appliance_cycles = ApplianceCycleManager(self.hass, self._config)
        await self._appliance_cycles.async_setup()

        # v4.6.432: Generator / ATS manager
        self._generator_mgr = GeneratorManager(self.hass, self._config)
        self._generator_mgr_enabled = bool(self._config.get("generator_enabled"))

        # v4.6.445: Lamp automation engine
        self._lamp_auto = LampAutomationEngine(self.hass, self._config)
        await self._async_configure_lamp_automation()

        # v4.6.447: Circuit monitor
        self._circuit_monitor = CircuitMonitor(self.hass, self._config)
        self._async_configure_circuit_monitor()

        # v4.6.450: UPS manager
        self._ups_manager = UPSManager(self.hass, self._config)
        self._async_configure_ups()

        # v2.6: E-bike integratie (Bosch / Specialized / Yamaha / Smartphix / Generiek)
        self._ebike = EBikeManager(self.hass, self._config)
        await self._ebike.async_setup()

        # v2.6: ERE certificaten module
        self._ere = EREManager(self.hass, self._config)
        await self._ere.async_setup()

        # v3.5.3: Test-mode simulator
        self._simulator = CloudEMSSimulator(self.hass)
        # v3.5.6: Registreer zones in simulator (na init, want _simulator moet bestaan)
        if bool(self._config.get("climate_zones_enabled") or self._config.get("climate_mgr_enabled")):
            self._simulator.register_zones(self._smart_climate)

        # v1.17: Hybride NILM — auto-discovery + contextpriors + 3-fase balans
        # v1.22: altijd instantiëren (discovery draait op achtergrond) maar
        #        alleen koppelen aan NILM-detector als beide schakelaars AAN zijn.
        self._hybrid = HybridNILM(self.hass, self._config)
        await self._hybrid.async_setup()
        if self._nilm_active and self._hybrid_nilm_active:
            self._nilm._hybrid = self._hybrid
            _LOGGER.info("CloudEMS HybridNILM geïntegreerd (schakelaar AAN)")
        else:
            _LOGGER.debug(
                "CloudEMS HybridNILM beschikbaar maar niet actief "
                "(nilm=%s hybrid=%s)", self._nilm_active, self._hybrid_nilm_active,
            )

        # v1.22: HMM sessietracking — alleen aanmaken als schakelaar AAN is
        if self._nilm_hmm_active:
            self._hmm = ApplianceHMMManager()
            self._nilm._hmm_callback = self._hmm.on_nilm_event
            _LOGGER.info("CloudEMS NILM HMM sessietracking actief")

        # v1.23: Bayesian posterior classifier — alleen aanmaken als schakelaar AAN is
        if self._nilm_bayes_active:
            self._bayes = BayesianNILMClassifier()
            self._nilm._bayes_callback = self._bayes
            _LOGGER.info("CloudEMS NILM Bayesian classifier actief")

        # v4.6.514: Realtime solar + batterij via state-change listeners.
        # P1/grid heeft al een callback (1s). Solar en batterij worden normaal elke
        # 10s gepolled — dat is te traag voor NILM huis-verbruik berekening.
        # State-change listeners geven updates zodra de omvormer/batterij-sensor wijzigt.
        self._rt_unsub_solar   = None
        self._rt_unsub_battery = None
        try:
            from homeassistant.helpers.event import async_track_state_change_event
            from homeassistant.core import callback as _ha_callback

            _solar_eid   = cfg.get(CONF_SOLAR_SENSOR, "")
            _battery_eid = cfg.get(CONF_BATTERY_SENSOR, "")
            _use_sep     = cfg.get(CONF_USE_SEPARATE_IE, False)
            _import_eid  = cfg.get(CONF_IMPORT_SENSOR, "") if _use_sep else ""
            _export_eid  = cfg.get(CONF_EXPORT_SENSOR, "") if _use_sep else ""

            @_ha_callback
            def _on_solar_state_change(event) -> None:
                """Ontvang solar-vermogen update direct bij state-change."""
                new_state = event.data.get("new_state")
                if new_state is None or new_state.state in ("unavailable", "unknown", ""):
                    return
                try:
                    _w = self._calc.to_watts(_solar_eid, float(new_state.state))
                    if _w is not None:
                        self._last_solar_w = round(float(_w), 1)
                        # NILM direct voeden met nieuw huis-vermogen
                        if self._nilm and not self.learning_frozen:
                            _grid_w = getattr(self, "_last_p1_realtime_grid_w", 0.0) or 0.0
                            _house  = max(0.0, _grid_w + self._last_solar_w)
                            self._nilm.update_power("L1", _house, source="solar_realtime")
                except Exception:
                    pass

            @_ha_callback
            def _on_battery_state_change(event) -> None:
                """Ontvang batterij-vermogen update direct bij state-change."""
                new_state = event.data.get("new_state")
                if new_state is None or new_state.state in ("unavailable", "unknown", ""):
                    return
                try:
                    _w = self._calc.to_watts(_battery_eid, float(new_state.state))
                    if _w is not None:
                        self._last_battery_w = round(float(_w), 1)
                        # v4.6.533: registreer battery update voor latency monitor
                        try:
                            if self._integration_latency:
                                self._integration_latency.record_update("battery")
                        except Exception:
                            pass
                except Exception:
                    pass

            _solar_listen_ids = [e for e in [_solar_eid] if e]
            _batt_listen_ids  = [e for e in [_battery_eid] if e]

            if _solar_listen_ids:
                self._rt_unsub_solar = async_track_state_change_event(
                    self.hass, _solar_listen_ids, _on_solar_state_change
                )
                _LOGGER.debug("CloudEMS: realtime solar state-listener actief voor %s", _solar_eid)

            if _batt_listen_ids:
                self._rt_unsub_battery = async_track_state_change_event(
                    self.hass, _batt_listen_ids, _on_battery_state_change
                )
                _LOGGER.debug("CloudEMS: realtime batterij state-listener actief voor %s", _battery_eid)
        except Exception as _rt_listen_err:
            _LOGGER.warning("CloudEMS: realtime solar/batterij listeners niet beschikbaar: %s", _rt_listen_err)

        # v4.6.170: gebruik VERSION uit const.py — voorkomt blocking I/O in event loop
        from .const import VERSION as _mf_version
        _active_modules = []
        if getattr(self, "_nilm_active", False):             _active_modules.append("NILM")
        if getattr(self, "_hybrid_nilm_active", False):      _active_modules.append("HybridNILM")
        if getattr(self, "_nilm_bayes_active", False):       _active_modules.append("NILM-Bayesian")
        if getattr(self, "_nilm_hmm_active", False):         _active_modules.append("NILM-HMM")
        if getattr(self, "_boiler_ctrl", None):              _active_modules.append("Boiler")
        if getattr(self, "_phase_balancer", None):           _active_modules.append("PhaseBalancer")
        if getattr(self, "_p1_reader", None):                _active_modules.append("P1")
        if getattr(self, "_peak_shaving", None):             _active_modules.append("PeakShaving")
        if getattr(self, "_gas_analysis", None):             _active_modules.append("GasAnalysis")
        if getattr(self, "_climate_epex", None):             _active_modules.append("ClimateEpex")
        if getattr(self, "_pool_ctrl", None):                _active_modules.append("Pool")
        if getattr(self, "_provider_manager", None):         _active_modules.append("ProviderManager")
        if getattr(self, "_solar_learner", None):            _active_modules.append("SolarLearner")
        if getattr(self, "_pv_forecast", None):              _active_modules.append("PVForecast")
        if getattr(self, "_solar_dimmer", None):             _active_modules.append("SolarDimmer")
        _LOGGER.info(
            "CloudEMS v%s gestart — actieve modules: %s",
            _mf_version, ", ".join(_active_modules) if _active_modules else "geen"
        )
        if hasattr(self, "_learning_backup") and self._learning_backup:
            import asyncio as _aio_su
            _boiler_config_log = []
            if self._boiler_ctrl:
                for _bg in getattr(self._boiler_ctrl, "_groups", []):
                    for _bu in getattr(_bg, "boilers", []):
                        _boiler_config_log.append({
                            "label": _bu.label,
                            "entity_id": _bu.entity_id,
                            "energy_sensor": _bu.energy_sensor or "(leeg)",
                            "temp_sensor": _bu.temp_sensor or "(leeg)",
                            "control_mode": _bu.control_mode,
                        })
                for _bu in getattr(self._boiler_ctrl, "_boilers", []):
                    _boiler_config_log.append({
                        "label": _bu.label,
                        "entity_id": _bu.entity_id,
                        "energy_sensor": _bu.energy_sensor or "(leeg)",
                        "temp_sensor": _bu.temp_sensor or "(leeg)",
                        "control_mode": _bu.control_mode,
                    })
            # v4.6.471: log shutter_config incl. temp_sensor voor debugging
            _shutter_config_log = [
                {
                    "entity_id":   sc.get("entity_id", ""),
                    "label":       sc.get("label", ""),
                    "temp_sensor": sc.get("temp_sensor") or "(leeg)",
                    "area_id":     sc.get("area_id") or "(leeg)",
                }
                for sc in (self._config.get("shutter_configs") or [])
            ]
            _aio_su.ensure_future(self._learning_backup.async_log_high("coordinator_startup", {
                "version":         _mf_version,
                "active_modules":  _active_modules,
                "ha_version":      str(getattr(getattr(self.hass, "data", {}), "get", lambda k, d="": d)("homeassistant", "")),
                "boiler_config":   _boiler_config_log,
                "shutter_config":  _shutter_config_log,
            }))

    # ── Update loop ───────────────────────────────────────────────────────────

    def _read_feature_toggles(self) -> None:
        """Lees input_boolean.cloudems_* entities en pas module-flags aan.

        Hierdoor werken de schakelaars op het configuratie-tabblad direct,
        zonder wizard of herstart.
        """
        # v2.6: Module toggles zijn nu echte switch.* entities (aangemaakt door CloudEMS).
        # De coördinator leest zijn eigen module-attrs direct — de switch entities
        # schrijven via setattr terug. Geen polling meer nodig hier.
        # Deze methode is nog aanwezig als noodval voor externe input_boolean overrides.
        # Bepaal default voor conditionele modules op basis van configuratie
        def _is_configured(*keys) -> bool:
            """Geeft True als minstens één config-key een niet-lege waarde heeft."""
            cfg = self._config
            return any(bool(cfg.get(k)) for k in keys)

        # Primaire modules: altijd aan bij nieuwe installatie
        # Conditionele modules: alleen aan als de gebruiker ze geconfigureerd heeft
        TOGGLES = {
            # Primair — altijd True
            "switch.cloudems_module_nilm":          ("_nilm_active",             True),
            "switch.cloudems_module_piekbeperking": ("_peak_shaving_enabled",    True),
            "switch.cloudems_module_faseverdeling": ("_phase_balancing_enabled", True),
            "switch.cloudems_module_pv_forecast":   ("_pv_forecast_enabled",     True),
            "switch.cloudems_module_schaduw":       ("_shadow_detector_enabled", True),
            "switch.cloudems_module_solar_learner": ("_solar_learner_enabled",   True),
            "switch.cloudems_module_goedkope_uren": ("_cheap_switch_enabled",    True),
            "switch.cloudems_module_inzichten":     ("_weekly_insights_enabled", True),
            "switch.cloudems_module_notificaties":  ("_notifications_enabled",   True),
            # Conditioneel — standaard aan alleen als geconfigureerd
            "switch.cloudems_module_klimaat":       ("_climate_mgr_override",
                _is_configured("climate_zones_enabled") or _is_configured("climate_mgr_enabled", "climate_zones")),
            "switch.cloudems_module_ketel":         ("_boiler_enabled",
                _is_configured("cv_boiler_entity", "boiler_entity")),
            "switch.cloudems_module_ev_lader":      ("_ev_charger_enabled",
                _is_configured("ev_charger_entity", "ev_charger_switch")),
            "switch.cloudems_module_batterij":      ("_battery_sched_enabled",
                _is_configured("battery_soc_entity", "battery_scheduler_enabled",
                               "battery_configs", "zonneplan_enabled")),
            "switch.cloudems_module_ere":           ("_ere_enabled",
                _is_configured("ere_enabled", "ere_meter_entity")),
            "switch.cloudems_module_lampcirculatie":("_lamp_circulation_enabled",
                _is_configured("lamp_circulation_enabled", "lamp_circulation_light_entities")),
            "switch.cloudems_module_ebike":         ("_ebike_enabled",
                _is_configured("ebikes", "ebike_entities")),
            "switch.cloudems_module_zwembad":       ("_pool_enabled",
                _is_configured("pool", "pool_filter_entity")),
            "switch.cloudems_module_rolluiken":     ("_shutter_enabled", False),
        }
        for entity_id, (attr, default) in TOGGLES.items():
            st = self._safe_state(entity_id)
            if st is None:
                # Eerste keer — zet default op basis van configuratie
                if not hasattr(self, attr):
                    setattr(self, attr, bool(default))
                continue
            # v4.5.103: negeer unavailable/unknown — voorkomt dat crashes alle
            # module-toggles op False zetten doordat HA switches tijdelijk
            # unavailable zijn tijdens een coordinator crash-cyclus.
            if st.state not in ("on", "off"):
                continue
            val = st.state == "on"
            if not hasattr(self, attr):
                setattr(self, attr, bool(default))
            current = getattr(self, attr, None)
            if current != val:
                setattr(self, attr, val)
                _LOGGER.info("CloudEMS feature toggle: %s → %s", attr, "AAN" if val else "UIT")

    async def _async_update_data(self) -> Dict:
        try:
            self._coordinator_tick = getattr(self, "_coordinator_tick", 0) + 1
            # v4.6.152: start cycle timer
            self._perf.start_cycle()
            # Lazy init decisions_history
            if self._decisions_history is None:
                from .decisions_history import DecisionsHistory
                self._decisions_history = DecisionsHistory(self.hass.config.config_dir)
            if self._energy_demand_calc is None:
                from .energy_manager.energy_demand import EnergyDemandCalculator
                self._energy_demand_calc = EnergyDemandCalculator(self.hass)
            if self._storage_backend is None:
                from .storage_backend import init_storage_backend
                self._storage_backend = init_storage_backend(self.hass.config.config_dir)
            if self._telemetry is None:
                from .telemetry import CloudEMSTelemetry
                _manifest = {}
                try:
                    import json as _j, os as _os
                    _mp = _os.path.join(_os.path.dirname(__file__), "manifest.json")
                    import asyncio as _aio_m
                    def _read_manifest():
                        with open(_mp) as _f:
                            return _j.load(_f)
                    _manifest = await _aio_m.get_event_loop().run_in_executor(None, _read_manifest)
                except Exception:
                    pass
                self._telemetry = CloudEMSTelemetry(
                    self.hass,
                    self.hass.config.config_dir,
                    version=_manifest.get("version", "4.6"),
                    firebase_project_id=self._config.get("telemetry_firebase_project", ""),
                    firebase_api_key=self._config.get("telemetry_firebase_key", ""),
                )
                self._telemetry.set_enabled(bool(self._config.get("telemetry_enabled", False)))
            # v4.0.5: Watchdog update gestart
            if hasattr(self, "_watchdog") and self._watchdog:
                self._watchdog.report_update_started()
            # Feature toggles uit input_boolean dashboard-schakelaars
            self._read_feature_toggles()

            # ── Lazy re-detect ZonneplanProvider (race condition bij HA start) ──
            # Als _entities leeg is (entity registry nog niet klaar bij setup),
            # probeer elke 5 minuten opnieuw te detecteren.
            _zp = getattr(self, "_zonneplan_bridge", None)
            if _zp is not None and not _zp._entities:
                _now = time.time()
                _last = getattr(self, "_last_zp_redetect", 0)
                # v4.6.310: 30s ipv 5min — zodat na herstart binnen halve minuut sturing start
                _redetect_interval = 30 if getattr(self, "_health_cycle_count", 0) < 20 else 300
                if _now - _last > _redetect_interval:
                    self._last_zp_redetect = _now
                    try:
                        if await _zp.async_detect():
                            _LOGGER.info(
                                "CloudEMS: ZonneplanProvider re-detect geslaagd — %d entiteiten: %s",
                                len(_zp._entities), sorted(_zp._entities.keys()),
                            )
                        else:
                            _LOGGER.debug("CloudEMS: ZonneplanProvider re-detect nog niet geslaagd.")
                    except Exception as _redet_err:
                        _LOGGER.debug("CloudEMS: ZonneplanProvider re-detect fout: %s", _redet_err)

            data = await self._gather_power_data()

            # v2.1.6: als geen CONF_SOLAR_SENSOR geconfigureerd is maar er wél
            # omvormer-entities zijn (multi-inverter), sommeer hun live vermogen.
            # Dit zorgt dat ALLE modules (self_consumption, pv_accuracy, shadow_detector,
            # clipping_loss, solar_learner) van de correcte solar_power profiteren.
            if not data.get("solar_power") and not self._config.get(CONF_SOLAR_SENSOR, ""):
                inv_total = 0.0
                for inv in self._config.get(CONF_INVERTER_CONFIGS, []):
                    eid = inv.get("entity_id", "")
                    if eid:
                        raw = self._read_state(eid)
                        inv_total += float(self._calc.to_watts(eid, raw) or 0.0) if raw is not None else 0.0
                if inv_total > 0:
                    data["solar_power"] = inv_total

            # v4.5.6: Kirchhoff-balancer — garandeert consistente energiebalans
            # ook als cloud-sensoren (batterij, omvormer) traag of stale zijn.
            # house_w = solar + grid - battery  is altijd consistent.
            #
            # v4.5.11 fix: lees de ruwe batterijmeting VOOR reconcile() zodat de
            # balancer de waarde van DEZE cyclus heeft en niet die van de vorige.
            # Vroeger stond _last_battery_w pas na _process_power_data() — dat gaf
            # een cyclus vertraging (±10s) wat bij snelle battery-sprongen leidde
            # tot vals huis-verbruik van soms >9 kW.
            if self._energy_balancer is not None:
                # Lees ruwe batterijwaarde(s) alvast — dezelfde logica als verderop
                # in _process_power_data(), maar puur voor de balancer input.
                _batt_pre_w: Optional[float] = None
                try:
                    _batt_pre_total = 0.0
                    _batt_pre_found = False
                    # Lees multi-battery configs
                    for _bpc in self._config.get("battery_configs", []):
                        _bpc_eid = _bpc.get("power_sensor", "")
                        if _bpc_eid:
                            _bpc_raw = self._read_state(_bpc_eid)
                            if _bpc_raw is not None:
                                _bpc_w = self._calc.to_watts(_bpc_eid, _bpc_raw)
                                if _bpc_w is not None:
                                    _batt_pre_total += _bpc_w
                                    _batt_pre_found = True
                    # v4.5.11: ook legacy CONF_BATTERY_SENSOR meenemen als battery_configs leeg is
                    # Zonder dit krijgt reconcile() battery_w=None op de eerste cyclus → tracker
                    # nooit geüpdatet → battery stale → Kirchhoff berekent +1kW → anomaly-spam.
                    if not _batt_pre_found:
                        _legacy_batt_eid = self._config.get(CONF_BATTERY_SENSOR, "")
                        if _legacy_batt_eid:
                            _legacy_raw = self._read_state(_legacy_batt_eid)
                            if _legacy_raw is not None:
                                _legacy_w = self._calc.to_watts(_legacy_batt_eid, _legacy_raw)
                                if _legacy_w is not None:
                                    _batt_pre_total += _legacy_w
                                    _batt_pre_found = True
                    if _batt_pre_found:
                        _batt_pre_w = _batt_pre_total
                except Exception as _exc_ignored:
                    _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

                # v4.5.15: spike-filter op ruwe batterijmeting.
                # Zonneplan Nexus en andere cloud-batterijen kunnen incidenteel een
                # uitschietende waarde sturen (bijv. +2252W terwijl normaal -590W).
                # Wanneer de nieuwe meting >3× afwijkt van het voortschrijdend gemiddelde
                # (EMA, alpha=0.3) én groter is dan 1500W afwijking, gebruiken we de EMA
                # als proxy en loggen we het als debug. Dit voorkomt absurde house_w.
                if _batt_pre_w is not None:
                    _ema = getattr(self, "_battery_w_ema", None)
                    # v4.6.543: EMA niet initialiseren als grid nog 0 is (koude start)
                    _grid_now = data.get("grid_power") or 0
                    if _ema is None and abs(_grid_now) < 50 and abs(_batt_pre_w) > 500:
                        # P1 nog niet online — sla EMA initialisatie over
                        _batt_pre_w = None  # behandel als ontbrekend
                    elif _ema is None:
                        self._battery_w_ema = _batt_pre_w
                    else:
                        _diff = abs(_batt_pre_w - _ema)
                        _spike = _diff > 1500 and (_ema == 0 or abs(_batt_pre_w / _ema) > 3.0)
                        if _spike:
                            _LOGGER.debug(
                                "EnergyBalancer: battery spike gefilterd %.0fW → EMA %.0fW",
                                _batt_pre_w, _ema,
                            )
                            _batt_pre_w = _ema
                        else:
                            self._battery_w_ema = round(_ema * 0.7 + _batt_pre_w * 0.3, 1)

                # Fallback: gebruik vorige cyclus als sensor niet leesbaar is
                _battery_w_for_reconcile = _batt_pre_w if _batt_pre_w is not None \
                    else getattr(self, "_last_battery_w", None)
                # Bepaal versheid van de batterijsensor
                _batt_age_s = 0.0
                try:
                    from homeassistant.util import dt as _dt_util
                    _b_eid = ""
                    _batt_cfgs = self._config.get("battery_configs", [])
                    if _batt_cfgs:
                        _b_eid = _batt_cfgs[0].get("power_sensor", "")
                    if not _b_eid:
                        _b_eid = self._config.get("battery_sensor", "")
                    if _b_eid:
                        _b_st2 = self.hass.states.get(_b_eid)
                        if _b_st2 and hasattr(_b_st2, "last_changed") and _b_st2.last_changed:
                            _batt_age_s = (_dt_util.utcnow() - _b_st2.last_changed).total_seconds()
                except Exception as _exc_ignored:
                    _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)
                _batt_is_stale = _batt_age_s > 90

                _bal = self._energy_balancer.reconcile(
                    grid_w    = data.get("grid_power"),
                    solar_w   = data.get("solar_power"),
                    battery_w = _battery_w_for_reconcile,
                )

                # Schrijf geschatte waarden terug — ook batterij als die stale is
                if _bal.solar_estimated:
                    data["solar_power"] = _bal.solar_w
                if _bal.grid_estimated:
                    data["grid_power"]   = _bal.grid_w
                    data["import_power"] = max(0.0, _bal.grid_w)
                    data["export_power"] = max(0.0, -_bal.grid_w)

                # v4.6.522 fix: schrijf gecorrigeerde battery terug als:
                #   (a) sensor echt stale is (>90s geen update), OF
                #   (b) balancer heeft lag-compensatie of fast-ramp inferentie toegepast
                #       (cloud sensor stuurt updates maar met vertraagde waarde — niet stale
                #        maar wel onnauwkeurig; dit was de oorzaak van vals huis-verbruik)
                # v4.6.543: alleen terugschrijven als grid actief is (P1 online)
                # Als grid=0 maar battery>0 is de P1 nog niet opgestart —
                # de Kirchhoff-schatting is dan onbetrouwbaar.
                _grid_active = abs(data.get("grid_power") or 0) > 50
                if _bal.battery_estimated and (_batt_is_stale or _bal.lag_compensated) and _grid_active:
                    self._last_battery_w = _bal.battery_w
                    _LOGGER.debug(
                        "EnergyBalancer: battery gecorrigeerd (stale=%s, lag_comp=%s, age=%.0fs) → %.0fW",
                        _batt_is_stale, _bal.lag_compensated, _batt_age_s, _bal.battery_w,
                    )

                # House_w altijd via Kirchhoff (nooit via sensor)
                data["house_power"]  = _bal.house_w
                data["_balancer"]    = _bal

                # v4.5.15: house_w opslaan in rollend venster voor dynamische drempel
                if _bal.house_w > 0:
                    self._house_w_window.append(_bal.house_w)
                    if len(self._house_w_window) > self._HOUSE_W_WINDOW_MAX:
                        self._house_w_window.pop(0)

                # v4.6.531: Kirchhoff drift monitor — observe met ruwe waarden vóór correctie
                # Geeft ook gecorrigeerde waarden terug voor latere verwerking
                if self._kirchhoff_monitor:
                    try:
                        # Koppel decisions_history lazy (pas beschikbaar na eerste cyclus)
                        if self._decisions_history and not getattr(
                                self._kirchhoff_monitor, "_decisions_history", None):
                            self._kirchhoff_monitor.set_decisions_history(
                                self._decisions_history)
                        self._kirchhoff_monitor.observe(
                            grid_w    = data.get("grid_power"),
                            solar_w   = data.get("solar_power"),
                            battery_w = self._last_battery_w,
                            house_w   = _bal.house_w,
                        )
                        # Pas correcties toe op data-dict
                        _cg, _cs, _cb, _ch = self._kirchhoff_monitor.apply_corrections(
                            grid_w    = data.get("grid_power"),
                            solar_w   = data.get("solar_power"),
                            battery_w = self._last_battery_w,
                            house_w   = _bal.house_w,
                        )
                        if _cg is not None: data["grid_power"]   = _cg
                        if _cs is not None: data["solar_power"]  = _cs
                        if _ch is not None: data["house_power"]  = _ch
                        # battery via _last_battery_w niet overschrijven — balancer beheert dat
                    except Exception as _km_err:
                        _LOGGER.debug("KirchhoffDriftMonitor fout (genegeerd): %s", _km_err)

                # v4.6.533: sign consistency — controleer teken per sensor
                try:
                    if self._sign_consistency:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._sign_consistency.set_decisions_history(_dh)
                        for _stype, _sval in (
                            ("solar",   data.get("solar_power")),
                            ("grid",    data.get("grid_power")),
                            ("battery", self._last_battery_w),
                            ("house",   data.get("house_power")),
                        ):
                            if _sval is not None:
                                self._sign_consistency.observe(_stype, _sval)
                except Exception as _sc_err:
                    _LOGGER.debug("SignConsistency fout: %s", _sc_err)

                # v4.6.533: feedback loop detector
                try:
                    if self._feedback_loop:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._feedback_loop.set_decisions_history(_dh)
                        _sensor_readings = {}
                        for _sk, _cfg_key in (
                            ("grid_sensor",    "grid_power_sensor"),
                            ("solar_sensor",   "pv_power_sensor"),
                            ("battery_sensor", "battery_power_sensor"),
                        ):
                            _eid = self._config.get(_cfg_key, "")
                            if _eid:
                                _sv = self._read_state(_eid)
                                if _sv is not None:
                                    _sensor_readings[_sk] = _sv
                        self._feedback_loop.observe(
                            cloudems_house_w = data.get("house_power"),
                            cloudems_grid_w  = data.get("grid_power"),
                            sensor_readings  = _sensor_readings,
                        )
                except Exception as _fl_err:
                    _LOGGER.debug("FeedbackLoop fout: %s", _fl_err)

                # v4.6.533: fase-vermogen consistentie
                try:
                    if self._phase_consistency:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._phase_consistency.set_decisions_history(_dh)
                        _p1d = getattr(self, "_last_p1_data", {})
                        _pc = self._phase_consistency.observe(
                            grid_total_w = data.get("grid_power"),
                            l1_w = _p1d.get("power_l1_import_w"),
                            l2_w = _p1d.get("power_l2_import_w"),
                            l3_w = _p1d.get("power_l3_import_w"),
                        )
                except Exception as _pc_err:
                    _LOGGER.debug("PhaseConsistency fout: %s", _pc_err)

                # v4.6.533: wiring topology observe (correleert fase-sensor met P1-stroom)
                try:
                    if self._wiring_topology:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._wiring_topology.set_decisions_history(_dh)
                        _p1d = getattr(self, "_last_p1_data", {})
                        self._wiring_topology.observe_phase_power(
                            l1_w = _p1d.get("power_l1_import_w"),
                            l2_w = _p1d.get("power_l2_import_w"),
                            l3_w = _p1d.get("power_l3_import_w"),
                        )
                except Exception as _wt_err:
                    _LOGGER.debug("WiringTopology fout: %s", _wt_err)

                # v4.6.533: integration latency check_stale (elke cyclus)
                try:
                    if self._integration_latency:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._integration_latency.set_decisions_history(_dh)
                        _lat_issues = self._integration_latency.check_stale()
                        if _lat_issues:
                            _LOGGER.debug("IntegrationLatency: %d trage integraties", len(_lat_issues))
                except Exception as _il_err:
                    _LOGGER.debug("IntegrationLatency fout: %s", _il_err)

                # v4.6.533: battery capaciteit drift check (1× per uur)
                try:
                    _bsl_ref = getattr(self, "_battery_soc_learner", None)
                    if _bsl_ref and self._sensor_hints:
                        _bat_cfgs = self._config.get("battery_configs") or []
                        _bsl_eid  = (_bat_cfgs[0].get("power_sensor") or "") if _bat_cfgs else ""
                        if _bsl_eid:
                            _bsl_diag = _bsl_ref.get_diagnostics(_bsl_eid)
                            _learned_kwh = _bsl_diag.get("est_capacity_kwh")
                            _config_kwh  = float(self._config.get("battery_capacity_kwh", 0) or 0)
                            if _learned_kwh and _config_kwh > 0:
                                from .energy_manager.battery_soc_learner import check_capacity_drift
                                check_capacity_drift(
                                    learned_kwh    = _learned_kwh,
                                    configured_kwh = _config_kwh,
                                    hint_engine    = self._sensor_hints,
                                    decisions_history = getattr(self, "_decisions_history", None),
                                )
                except Exception as _cd_err:
                    _LOGGER.debug("CapacityDrift fout: %s", _cd_err)
                # of imbalans > 500W (Kirchhoff klopt niet)
                _bk_bal = getattr(self, "_learning_backup", None)
                if _bk_bal is not None:
                    # v4.5.15: dynamische anomaly-drempel op basis van P95 van de gemeten
                    # house_w in de laatste 24u — ieder huis is anders.
                    # Minimum 6000W als fallback (eerste uren na herstart of weinig data).
                    # Drempel = max(6000, P95 * 1.5) zodat echte pieken (~centrifuge +
                    # vloerverwarming) de drempel niet zelf omhoog trekken.
                    _hw_window = self._house_w_window
                    if len(_hw_window) >= 30:
                        _sorted = sorted(_hw_window)
                        _p95_idx = int(len(_sorted) * 0.95)
                        _p95_w = _sorted[min(_p95_idx, len(_sorted) - 1)]
                        _dynamic_threshold = max(6000.0, _p95_w * 1.5)
                    else:
                        _dynamic_threshold = 9000.0  # safe fallback bij te weinig data
                    _house_anomaly = _bal.house_w > _dynamic_threshold
                    _big_imbalance = _bal.imbalance_w > 500
                    if _house_anomaly or _big_imbalance:
                        import asyncio as _aio_bal
                        _aio_bal.ensure_future(_bk_bal.async_log_high(
                            "balancer_anomaly", {
                                "house_w":        round(_bal.house_w, 1),
                                "grid_w":         round(_bal.grid_w, 1),
                                "solar_w":        round(_bal.solar_w, 1),
                                "battery_w":      round(_bal.battery_w, 1),
                                "battery_raw_w":  round(_battery_w_for_reconcile or 0, 1),
                                "battery_prev_w": round(getattr(self, "_last_battery_w", 0), 1),
                                "battery_age_s":  round(_batt_age_s, 1),
                                "battery_stale":  _batt_is_stale,
                                "imbalance_w":    round(_bal.imbalance_w, 1),
                                "stale_sensors":  _bal.stale_sensors,
                                "lag_comp":       _bal.lag_compensated,
                                "anomaly_threshold_w": round(_dynamic_threshold, 1),
                                "house_w_samples": len(self._house_w_window),
                                "reason":         "high_house_w" if _house_anomaly else "high_imbalance",
                            }
                        ))

                if _bal.stale_sensors:
                    _LOGGER.debug(
                        "EnergyBalancer: stale=%s → house=%.0fW "
                        "(grid=%.0f solar=%.0f battery=%.0f)",
                        _bal.stale_sensors, _bal.house_w,
                        _bal.grid_w, _bal.solar_w, _bal.battery_w,
                    )

            await self._process_power_data(data)
            await self._limiter.evaluate_and_act()

            if time.time() - self._prices_last_update > EPEX_UPDATE_INTERVAL:
                await self._prices.update()
                self._prices_last_update = time.time()

            # v1.16: Ollama health-check every 60 s (only when Ollama is configured)
            if self._ollama_cfg.get("enabled") and time.time() - self._ollama_health_last_check > 60:
                await self.async_check_ollama_health()

            # ── v4.5.1: Poll provider prices EARLY so they are available for price_info ──
            # Provider prices (Tibber, Frank Energie, Octopus, etc.) zijn already
            # all-in prijzen rechtstreeks van de leverancier — dit is de meest
            # correcte bron. We cachen het resultaat en hergebruiken het later in de
            # cycle voor ext_inverters / ext_ev / ext_appliances.
            _provider_poll_cache: dict = {}
            _provider_prices: dict = {}
            if self._provider_manager and self._provider_manager.active_count > 0:
                try:
                    from .provider_manager import (
                        extract_inverter_summary, extract_ev_summary,
                        extract_appliance_summary, extract_energy_prices,
                    )
                    _provider_poll_cache = await self._provider_manager.async_poll_all()
                    _provider_prices = extract_energy_prices(_provider_poll_cache)
                except Exception as _pp_err:
                    _LOGGER.debug("ProviderManager vroegtijdige poll fout: %s", _pp_err)

            _raw_price = self._prices.current_price if self._prices else None
            if _raw_price is not None:
                current_price = _raw_price
                self._last_known_price = _raw_price  # v4.5.7: persist for fallback
            else:
                # API-fout of slot-overgang: gebruik vorige bekende prijs om €0-berekeningen te voorkomen
                current_price = getattr(self, "_last_known_price", None)
                if current_price is None:
                    current_price = 0.0  # absolute fallback bij eerste opstart zonder data
                    _LOGGER.debug("Stroomprijs onbekend (geen slot) en geen vorige waarde beschikbaar")
                else:
                    _LOGGER.debug("Stroomprijs tijdelijk onbekend — gebruik vorige prijs: %.5f", current_price)

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
            elif _provider_prices.get("current_price") is not None:
                # ── v4.5.1: Leverancier-prijzen als primaire bron ──────────────
                # Providers als Tibber, Frank Energie en Octopus leveren all-in
                # prijzen inclusief alle toeslagen. Deze zijn nauwkeuriger dan
                # EPEX + vaste markup. We bouwen price_info direct van provider data.
                _pp = _provider_prices
                _today_slots_raw = _pp.get("today_prices", [])
                _tomorrow_slots_raw = _pp.get("tomorrow_prices", [])
                _today_prices = [s["price"] for s in _today_slots_raw if s.get("price") is not None]
                from statistics import mean as _mean
                _avg_today = round(_mean(_today_prices), 5) if _today_prices else None
                _cur = float(_pp["current_price"])

                # Goedkoopste uren bepalen op basis van provider-prijzen
                _next_hours_provider = []
                import datetime as _dt
                _now_h = _dt.datetime.now().hour
                for _slot in _today_slots_raw:
                    if _slot.get("hour") is not None and _slot.get("price") is not None:
                        _next_hours_provider.append({
                            "hour":  _slot["hour"],
                            "price": float(_slot["price"]),
                            "label": f"{_slot['hour']:02d}:00",
                        })
                for _slot in _tomorrow_slots_raw:
                    if _slot.get("hour") is not None and _slot.get("price") is not None:
                        _next_hours_provider.append({
                            "hour":  _slot["hour"],
                            "price": float(_slot["price"]),
                            "label": f"{_slot['hour']:02d}:00",
                        })

                from .energy.prices import (
                    _find_cheapest_window, _find_cheapest_window_indices, _cheapest_window_detail,
                )
                _sorted_prov = sorted(_next_hours_provider, key=lambda h: h["price"])
                _cheapest_hours_prov = [h["hour"] for h in _sorted_prov]

                price_info = {
                    "current":             _cur,
                    "is_negative":         _cur <= 0.0,  # EPEX-basis — boiler gebruikt dit intern
                    "is_negative_all_in":  False,  # wordt hieronder ingevuld na _enrich_price_info
                    "min_today":           round(min(_today_prices), 5) if _today_prices else None,
                    "max_today":           round(max(_today_prices), 5) if _today_prices else None,
                    "avg_today":           _avg_today,
                    "rolling_avg_30d":     _avg_today,  # beste benadering zonder 30d history
                    "next_hours":          _next_hours_provider,
                    "today_all":           _today_slots_raw,
                    "tomorrow_all":        _tomorrow_slots_raw,
                    "tomorrow_available":  len(_tomorrow_slots_raw) > 0,
                    "cheapest_2h_start":   _find_cheapest_window(_next_hours_provider, 2),
                    "cheapest_3h_start":   _find_cheapest_window(_next_hours_provider, 3),
                    "cheapest_4h_start":   _find_cheapest_window(_next_hours_provider, 4),
                    "cheapest_4h_block":   _cheapest_window_detail(_next_hours_provider, 4),
                    "in_cheapest_1h":      0 in _find_cheapest_window_indices(_next_hours_provider, 1),
                    "in_cheapest_2h":      0 in _find_cheapest_window_indices(_next_hours_provider, 2),
                    "in_cheapest_3h":      0 in _find_cheapest_window_indices(_next_hours_provider, 3),
                    "in_cheapest_4h":      0 in _find_cheapest_window_indices(_next_hours_provider, 4),
                    "cheapest_1h_hours":   _cheapest_hours_prov[:1],
                    "cheapest_2h_hours":   _cheapest_hours_prov[:2],
                    "cheapest_3h_hours":   _cheapest_hours_prov[:3],
                    "cheapest_4h_hours":   _cheapest_hours_prov[:4],
                    "source":              _pp.get("source", "provider"),
                    "provider_key":        _pp.get("provider_key", ""),
                    "prices_from_provider": True,  # markeer als all-in, geen markup meer toepassen
                    "contract_type":       "dynamic",
                    "slot_count":          len(_today_slots_raw),
                    "yesterday_prices":    self._get_yesterday_prices(),
                }
                # current_price ook updaten voor modules die rechtstreeks _prices.current_price lezen
                current_price = _cur
                _LOGGER.debug(
                    "CloudEMS prijzen: %.4f €/kWh via provider '%s' (%d slots vandaag)",
                    _cur, _pp.get("source", "?"), len(_today_slots_raw),
                )
            else:
                # EPEX price info (standaard: geen provider geconfigureerd)
                price_info: dict = self._prices.get_price_info() if self._prices else {}
                price_info["contract_type"] = CONTRACT_TYPE_FIXED if contract_type == CONTRACT_TYPE_FIXED else "dynamic"
                price_info["yesterday_prices"] = self._get_yesterday_prices()

            # v1.13.0: apply tax/BTW/markup to produce all-in price fields
            # v4.5.1: bij provider-prijzen wordt in _apply_price_components geen markup opgestapeld
            price_info = self._apply_price_components(price_info)
            self._last_price_info = price_info  # v4.5.11: voor _log_decision context

            # Dynamic loader (threshold-based, keeps running for price logic)
            ev_decision = {}
            if self._dynamic_loader:
                _dyn_batt_w = getattr(self, "_last_battery_w", 0.0)
                _ev_surplus = self._calc_pv_surplus(
                    float(data.get("solar_power", 0.0) or 0.0),
                    float(data.get("grid_power",  0.0) or 0.0),
                    _dyn_batt_w,
                )
                ev_decision = await self._dynamic_loader.async_evaluate(
                    price_eur_kwh  =current_price,
                    solar_surplus_w=_ev_surplus,
                    max_current_a  =float(self._config.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT)),
                )
                # v4.5.11: log EV laadbeslissing
                if ev_decision:
                    self._log_decision(
                        "ev_charger",
                        f"🚗 EV: {ev_decision.get('mode','?')} @ {ev_decision.get('current_a','?')}A — {ev_decision.get('reason','')}",
                        payload={
                            "mode":              ev_decision.get("mode"),
                            "current_a":         ev_decision.get("current_a"),
                            "reason":            ev_decision.get("reason"),
                            "active":            ev_decision.get("active"),
                            "solar_surplus_w":   round(_ev_surplus, 1),
                            "price_eur_kwh":     round(current_price or 0, 5),
                            "max_current_a":     float(self._config.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT)),
                            "ev_soc_pct":        ev_decision.get("ev_soc_pct"),
                            "target_soc_pct":    ev_decision.get("target_soc_pct"),
                        }
                    )
                    # v4.6.498: Fase 2 — registreer EV-beslissing in DOL
                    try:
                        if ev_decision.get("active"):
                            from .energy_manager.decision_outcome_learner import build_context_bucket
                            import datetime as _dt_ev
                            _ev_bucket = build_context_bucket(
                                "ev", None, current_price or 0.0,
                                float((price_info or {}).get("avg_today") or 0),
                                _ev_surplus,
                                month=_dt_ev.datetime.now().month,
                                hour=_dt_ev.datetime.now().hour,
                            )
                            _ev_mode = ev_decision.get("mode", "solar")
                            _ev_kwh  = float(ev_decision.get("current_a", 6)) * 230 / 1000  # ~Wh per cyclus
                            _ev_alt  = "wait" if _ev_mode in ("solar", "cheap") else "charge_now"
                            self._decision_learner.record_decision(
                                component      = "ev",
                                action         = _ev_mode,
                                alternative    = _ev_alt,
                                context_bucket = _ev_bucket,
                                price_eur_kwh  = current_price or 0.0,
                                energy_kwh     = _ev_kwh,
                                eval_after_s   = 3600,
                            )
                    except Exception as _dol_ev_err:
                        _LOGGER.debug("DOL EV record fout: %s", _dol_ev_err)

            # v4.0.6: EV gecombineerde EPEX+PV laadplanning (vervangt v1.18.1 PV-only)
            ev_solar_plan: dict = {}
            _ev_fc = locals().get('pv_forecast_hourly') or []
            if self._ev_pid and (_ev_fc or self._price_hour_history):
                try:
                    now_h = datetime.now(timezone.utc).hour
                    # Bouw score per uur: hogere PV = beter, lagere prijs = beter
                    # Normaliseer beide dimensies naar 0-1 en combineer
                    future_hours_pv: dict[int, float] = {}
                    for h in _ev_fc:
                        hr = h.get("hour", 0)
                        if hr >= now_h:
                            future_hours_pv[hr] = future_hours_pv.get(hr, 0.0) + h.get("forecast_w", 0.0)

                    # EPEX uurtarieven voor vandaag
                    future_hours_price: dict[int, float] = {}
                    for entry in (self._price_hour_history or [])[-48:]:
                        try:
                            _h = datetime.fromtimestamp(entry["ts"], tz=timezone.utc).hour
                            if _h >= now_h:
                                future_hours_price[_h] = float(entry.get("price", 0) or 0)
                        except Exception as _exc_ignored:
                            _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

                    all_hours = set(future_hours_pv.keys()) | set(future_hours_price.keys())
                    if all_hours:
                        max_pv    = max(future_hours_pv.values(),    default=1) or 1
                        min_price = min(future_hours_price.values(), default=0.01) if future_hours_price else 0.01
                        max_price = max(future_hours_price.values(), default=0.40) if future_hours_price else 0.40
                        price_range = max(0.001, max_price - min_price)

                        scored = {}
                        for hr in all_hours:
                            pv_norm     = future_hours_pv.get(hr, 0.0) / max_pv
                            price_norm  = 1.0 - (future_hours_price.get(hr, max_price) - min_price) / price_range
                            # Gewichten: PV gratis > goedkoop EPEX
                            pv_w = future_hours_pv.get(hr, 0.0)
                            if pv_w > 1000:
                                score = 0.7 * pv_norm + 0.3 * price_norm   # zonnig: PV domineert
                            else:
                                score = 0.3 * pv_norm + 0.7 * price_norm   # bewolkt: prijs domineert
                            scored[hr] = round(score, 4)

                        best_hour = max(scored, key=lambda k: scored[k])
                        best_pv   = round(future_hours_pv.get(best_hour, 0.0), 0)
                        best_price = future_hours_price.get(best_hour, current_price)
                        mode = "pv" if future_hours_pv.get(best_hour, 0) > 1000 else "epex"

                        ev_solar_plan = {
                            "best_hour":    best_hour,
                            "best_w":       best_pv,
                            "best_price":   round(best_price, 4),
                            "score":        scored.get(best_hour, 0),
                            "mode":         mode,
                            "hours_until":  best_hour - now_h,
                            "scored_hours": [
                                {"hour": h, "score": s, "pv_w": round(future_hours_pv.get(h, 0), 0),
                                 "price": round(future_hours_price.get(h, 0), 4)}
                                for h, s in sorted(scored.items(), key=lambda x: -x[1])[:5]
                            ],
                            "advice": (
                                f"Optimaal EV-laadmoment: {best_hour}:00 "
                                f"({'☀️ ' + str(int(best_pv)) + 'W PV' if mode == 'pv' else '💰 €' + str(round(best_price, 3)) + '/kWh EPEX'})"
                            ),
                        }
                        if scored.get(best_hour, 0) > 0.5 and best_hour != now_h:
                            self._log_decision(
                                "ev_solar_plan",
                                f"{'☀️' if mode == 'pv' else '💰'} EV planning: "
                                f"optimum {best_hour}:00 (score {scored[best_hour]:.2f})"
                            )
                except Exception as _ev_plan_err:
                    _LOGGER.debug("EV EPEX+PV plan fout: %s", _ev_plan_err)

            # v1.8: EV PID controller — smooth solar surplus tracking
            ev_pid_state = {}
            if self._ev_pid and self._ev_pid._enabled:
                grid_w  = data.get("grid_power", 0.0)
                # v4.5.118: Stop EV-laden bij netcongestie
                _ev_cong = locals().get("congestion_data", {}) or {}
                if _ev_cong.get("active"):
                    await self._set_ev_current(0)
                    self._log_decision("ev_pid",
                        f"🚫 EV PID gestopt: netcongestie actief ({_ev_cong.get('utilisation_pct', 0):.0f}% benutting)")
                else:
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
                    # v4.0.6: spanning + stroomstoringen
                    "voltage_l1":         getattr(t, "voltage_l1", 0.0),
                    "voltage_l2":         getattr(t, "voltage_l2", 0.0),
                    "voltage_l3":         getattr(t, "voltage_l3", 0.0),
                    "power_failures":     getattr(t, "power_failures", 0),
                    "long_power_failures":getattr(t, "long_power_failures", 0),
                    "voltage_sags_l1":    getattr(t, "voltage_sags_l1", 0),
                    "voltage_sags_l2":    getattr(t, "voltage_sags_l2", 0),
                    "voltage_sags_l3":    getattr(t, "voltage_sags_l3", 0),
                    # Per-phase import power (W, DSMR5)
                    "power_l1_import_w": t.power_l1_w,
                    "power_l2_import_w": t.power_l2_w,
                    "power_l3_import_w": t.power_l3_w,
                    # Per-phase export power (W, DSMR5)
                    "power_l1_export_w": t.power_l1_export_w,
                    "power_l2_export_w": t.power_l2_export_w,
                    "power_l3_export_w": t.power_l3_export_w,
                }
                # P1 directe boiler sturing: push net_power_w naar boiler controller
                if self._boiler_ctrl and hasattr(t, "net_power_w") and t.net_power_w is not None:
                    self._boiler_ctrl.async_p1_update(float(t.net_power_w))
                # v1.9: P1 per-phase power → NILM (highest quality input)
                # DSMR5 telegrams include per-phase import power in kW
                # P1Telegram fields: power_l1_import_w, power_l2_import_w, power_l3_import_w
                # v4.6.516: P1Telegram heeft power_l1_w (niet power_l1_import_w)
                for ph, attr in (("L1","power_l1_w"),("L2","power_l2_w"),("L3","power_l3_w")):
                    pw = getattr(t, attr, None)
                    if pw is not None and pw >= 0 and not self.learning_frozen:
                        self._nilm.update_power(ph, pw, source="p1_direct")
                # Also feed per-phase from current × voltage if power not in telegram (DSMR4)
                mains_v = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
                if getattr(t, "current_l1", None) is not None and not getattr(t, "power_l1_import_w", None):
                    for ph, amp in (("L1", t.current_l1),("L2", t.current_l2),("L3", t.current_l3)):
                        if amp is not None and not self.learning_frozen:
                            self._nilm.update_power(ph, amp * mains_v, source="p1_i*u")

            # Store latest P1 data so _process_power_data can use it as fallback
            # for phase voltage derivation (U = P/I) when no dedicated sensors configured.
            # Voeg diagnostics toe: spike-teller voor dashboard en health check
            if self._p1_reader:
                p1_data["spike_count"] = getattr(self._p1_reader, "spike_count", 0)
            self._last_p1_data = p1_data
            self._last_p1_update = time.time()

            # v4.6.533: P1 telegram kwaliteit + integratie latency
            try:
                if self._p1_quality:
                    _dh = getattr(self, "_decisions_history", None)
                    if _dh:
                        self._p1_quality.set_decisions_history(_dh)
                    self._p1_quality.record_telegram(
                        net_power_w = p1_data.get("net_power_w", 0.0),
                        fields      = {
                            "power_l1": p1_data.get("power_l1_import_w"),
                            "power_l2": p1_data.get("power_l2_import_w"),
                            "power_l3": p1_data.get("power_l3_import_w"),
                            "current_l1": p1_data.get("current_l1"),
                            "current_l2": p1_data.get("current_l2"),
                            "current_l3": p1_data.get("current_l3"),
                        },
                    )
                if self._integration_latency:
                    self._integration_latency.record_update("p1_meter")
            except Exception as _pq_err:
                _LOGGER.debug("P1Quality fout: %s", _pq_err)

            # v4.6.522: DSMR-type auto-detectie en waarschuwing / auto-correctie
            try:
                import time as _t_mod
                _now_ts = _t_mod.time()
                # Controleer max 1× per 60 seconden om spam te voorkomen
                if self._p1_reader and (_now_ts - self._dsmr_type_last_check_ts) > 60:
                    self._dsmr_type_last_check_ts = _now_ts
                    _measured = getattr(self._p1_reader, "measured_interval_s", None)
                    _samples  = getattr(self._p1_reader, "telegram_sample_count", 0)
                    _cfg_type = self._config.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL)

                    if (
                        _measured is not None
                        and _samples >= DSMR_AUTODETECT_MIN_SAMPLES
                        and _cfg_type != DSMR_TYPE_UNIVERSAL
                    ):
                        # Bepaal wat we meten
                        if _measured < DSMR_AUTODETECT_FAST_THRESHOLD_S:
                            _detected = DSMR_TYPE_5
                        elif _measured > DSMR_AUTODETECT_SLOW_THRESHOLD_S:
                            _detected = DSMR_TYPE_4
                        else:
                            _detected = None  # twijfelgebied, niets doen

                        if _detected and _detected != _cfg_type:
                            # Stuur één keer een persistent notification
                            if not self._dsmr_type_notified:
                                self._dsmr_type_notified = True
                                _cfg_label  = DSMR_TYPE_LABELS.get(_cfg_type, _cfg_type)
                                _det_label  = DSMR_TYPE_LABELS.get(_detected, _detected)
                                _exp_int    = DSMR_TYPE_EXPECTED_INTERVAL.get(_cfg_type, "?")
                                self.hass.components.persistent_notification.async_create(
                                    title="⚡ CloudEMS — Verkeerd DSMR-type gedetecteerd",
                                    message=(
                                        f"Het ingestelde DSMR-type **{_cfg_label}** klopt niet met de gemeten snelheid.\n\n"
                                        f"- Ingesteld: {_cfg_label} (verwacht ~{_exp_int}s per telegram)\n"
                                        f"- Gemeten: **{_measured:.1f}s** per telegram (n={_samples})\n"
                                        f"- Gedetecteerd: **{_det_label}**\n\n"
                                        f"CloudEMS heeft het DSMR-type automatisch bijgesteld naar **{_det_label}** "
                                        f"voor betere sturing. Pas de instelling handmatig aan via "
                                        f"Instellingen → CloudEMS → Netsensoren om deze melding te voorkomen."
                                    ),
                                    notification_id="cloudems_dsmr_type_mismatch",
                                )
                                _LOGGER.warning(
                                    "CloudEMS DSMR-type mismatch: ingesteld=%s, gemeten=%.1fs (n=%d), "
                                    "gedetecteerd=%s — auto-correctie toegepast",
                                    _cfg_type, _measured, _samples, _detected,
                                )

                            # Auto-correctie: sla het gedetecteerde type op in running config
                            if not self._dsmr_type_auto_corrected:
                                self._dsmr_type_auto_corrected = True
                                self._config[CONF_DSMR_TYPE] = _detected

                        elif _detected == _cfg_type:
                            # Type klopt — reset notificatie-vlag zodat een nieuwe mismatch
                            # later opnieuw gemeld kan worden
                            self._dsmr_type_notified = False
                            self._dsmr_type_auto_corrected = False

            except Exception as _dsmr_detect_err:
                _LOGGER.debug("DSMR-type auto-detectie fout: %s", _dsmr_detect_err)

            # v1.15.1: inject battery directly into NILM (prevents false edge detection)
            # v4.5.7: batterij-meting via EnergyBalancer
            # De balancer meet de echte update-interval per sensor en berekent
            # Kirchhoff-schattingen bij stale waarden. Hier alleen de ruwe meting
            # ophalen en doorgeven — staleness-logica zit volledig in de balancer.
            batt_configs = self._config.get("battery_configs", [])
            total_battery_w = 0.0
            for bc in batt_configs:
                b_eid      = bc.get("power_sensor", "")
                b_label    = bc.get("name", "Thuisbatterij")
                b_provider = bc.get("battery_type", "local")
                if b_provider in ("zonneplan", "nexus"):
                    _bu_provider = "nexus"
                elif b_provider in ("cloud", "api"):
                    _bu_provider = "cloud"
                else:
                    _bu_provider = "local"

                self._nilm.register_battery_provider(b_label, _bu_provider)

                b_raw  = self._read_state(b_eid) if b_eid else None
                b_real = self._calc.to_watts(b_eid, b_raw) if b_raw is not None and b_eid else None

                # Zonneplan-specifiek: ook Nexus bridge entity proberen
                if b_real is None and bc.get("battery_type") == "zonneplan":
                    _zp_pw_eid = getattr(
                        getattr(self, "_zonneplan_bridge", None), "_entities", {}
                    ).get("power")
                    if _zp_pw_eid:
                        _zp_raw = self._read_state(_zp_pw_eid)
                        if _zp_raw is not None:
                            b_real = self._calc.to_watts(_zp_pw_eid, _zp_raw)

                # BatteryUncertaintyTracker: verse meting of balancer-schatting
                _bal = data.get("_balancer")
                if b_real is not None:
                    self._nilm.update_battery_uncertainty(b_label, b_real)
                    bw = b_real
                else:
                    # Geen verse meting — gebruik balancer Kirchhoff-schatting
                    bw = _bal.battery_w if _bal is not None else getattr(self, "_last_battery_w", 0.0)
                    self._nilm._batt_uncertainty.update_estimate(
                        b_label,
                        grid_w     = abs(data.get("grid_power", 0.0) or 0.0),
                        solar_w    = abs(data.get("solar_power", 0.0) or 0.0),
                        baseline_w = (
                            self._home_baseline.get_standby_w()
                            if self._home_baseline and hasattr(self._home_baseline, "get_standby_w")
                            else getattr(self, "_house_baseline_w", 500.0)
                        ),
                    )

                total_battery_w += (bw or 0.0)


            if abs(total_battery_w) > 50:
                self._nilm.inject_battery(total_battery_w, "Thuisbatterij")
            else:
                self._nilm.update_battery_power(total_battery_w)

            # v4.6.413: FIX kWh tellers — smart_plug en injected devices gaan niet
            # via update_power() en missen daardoor tick_energy(). Hier expliciet
            # tick_energy aanroepen voor alle devices die niet via een fase-match getickt worden.
            _now_ts = __import__("time").time()
            for _sp_dev in self._nilm._devices.values():
                if getattr(_sp_dev, "source", "") in ("smart_plug", "injected") and _sp_dev.is_on and _sp_dev.current_power > 0:
                    _sp_dev.tick_energy(_now_ts)
            # v1.16: persist so consumption categories can subtract battery from totals
            self._last_battery_w = total_battery_w

            # v4.5.11: persisteer energie-context voor _log_decision()
            # Zodat elk beslissingsmoment altijd weet wat solar/grid/house/prijs was.
            self._last_solar_w   = round(float(data.get("solar_power", 0) or 0), 1)
            self._last_grid_w    = round(float(data.get("grid_power",  0) or 0), 1)
            self._last_house_w   = round(float(data.get("house_power", 0) or 0), 1)

            # v4.6.492: per-uur solar kWh accumulatie
            try:
                import datetime as _dt_pvh
                _pvh_today = _dt_pvh.date.today().isoformat()
                _pvh_hour  = _dt_pvh.datetime.now().hour
                if self._pv_hourly_day != _pvh_today:
                    # Nieuwe dag: sla vandaag op als gisteren, reset vandaag
                    self._pv_yesterday_hourly_kwh = list(self._pv_today_hourly_kwh)  # v4.6.493
                    self._pv_today_hourly_kwh = [0.0] * 24
                    self._pv_hourly_day       = _pvh_today
                    self._pv_hourly_last_hour = _pvh_hour
                # v4.6.506: bij uurwisseling — finalize vorig uur naar pv_forecast
                if (self._pv_hourly_last_hour >= 0
                        and _pvh_hour != self._pv_hourly_last_hour
                        and self._pv_forecast):
                    _prev_h   = self._pv_hourly_last_hour
                    _prev_kwh = self._pv_today_hourly_kwh[_prev_h]
                    if _prev_kwh > 0:
                        for _inv in self._config.get(CONF_INVERTER_CONFIGS, []):
                            _inv_eid = _inv.get("entity_id", "")
                            if _inv_eid:
                                try:
                                    self._pv_forecast.finalize_hour(
                                        _inv_eid, _prev_h, _prev_kwh
                                    )
                                except Exception as _fh_err:
                                    _LOGGER.debug("finalize_hour fout: %s", _fh_err)
                        _LOGGER.info(
                            "PVForecast: uur %d afgesloten — %.3f kWh werkelijk → fractie bijgesteld",
                            _prev_h, _prev_kwh,
                        )
                # Accumuleer huidig uur: W * interval_s / 3600 / 1000 = kWh
                _pvh_interval = UPDATE_INTERVAL_FAST  # v4.6.493: was getattr met nonexistent attr
                _pvh_inc = self._last_solar_w * _pvh_interval / 3_600_000.0
                if _pvh_inc > 0:
                    _new_val = self._pv_today_hourly_kwh[_pvh_hour] + _pvh_inc
                    # v4.6.554: sanity cap per uur — max 50 kWh/u is absoluut onmogelijk
                    if _new_val > 50.0:
                        _LOGGER.warning(
                            "CloudEMS: pv_today_hourly_kwh[%d] cap getriggerd: %.3f > 50 kWh — gereset",
                            _pvh_hour, _new_val,
                        )
                        _new_val = _pvh_inc  # reset dit uur, begin opnieuw
                    self._pv_today_hourly_kwh[_pvh_hour] = round(_new_val, 4)
                self._pv_hourly_last_hour = _pvh_hour
            except Exception as _pvh_err:
                _LOGGER.debug("CloudEMS: pv hourly accumulatie fout: %s", _pvh_err)
            # InfluxDB realtime
            if self._influxdb and self._influxdb.enabled:
                self._influxdb.write_realtime(data)
                self.hass.async_create_task(self._influxdb.async_flush())

            # v4.5.7: geleerde battery-vertraging vanuit EnergyBalancer doorgeven
            # aan BatteryUncertaintyTracker zodat het burst-masker automatisch
            # klopt voor deze specifieke integratie (Nexus=60s, lokaal=5s, etc.)
            if self._energy_balancer is not None:
                _learned_lag = self._energy_balancer.get_learned_battery_lag_s()
                if _learned_lag is not None and hasattr(self._nilm, "_batt_uncertainty"):
                    for _b_state in self._nilm._batt_uncertainty._batteries.values():
                        # Overschrijf het provider-profiel met de gemeten waarde
                        # alleen als de geleerde lag significant afwijkt (>20%)
                        _profile_stale = _b_state.profile.get("stale_s", 60)
                        if abs(_learned_lag - _profile_stale) / max(1, _profile_stale) > 0.2:
                            _b_state.profile["stale_s"]     = round(_learned_lag * 1.2)
                            _b_state.profile["burst_mask_s"] = round(_learned_lag * 2.5)
                            _LOGGER.debug(
                                "BatteryUncertainty '%s': lag bijgewerkt naar %.1fs "
                                "(stale_s=%d burst_mask_s=%d)",
                                _b_state.label, _learned_lag,
                                _b_state.profile["stale_s"],
                                _b_state.profile["burst_mask_s"],
                            )

            # v1.24: geef alle infra-sensor vermogens door zodat NILM events die
            # overeenkomen met infra-componenten (PV, grid, EV-lader, warmtepomp) 
            # automatisch worden gefilterd.
            _solar_w   = abs(data.get("solar_power",      0.0) or 0.0)
            _grid_w    = abs(data.get("grid_power",       0.0) or 0.0)
            _ev_w      = abs(data.get("ev_power",         0.0) or 0.0)
            _hp_w      = abs(data.get("heat_pump_power",  0.0) or 0.0)
            _boiler_w  = abs(data.get("boiler_power",     0.0) or 0.0)
            _batt_w    = abs(total_battery_w)
            _infra_pw: dict = {}
            if _solar_w  > 50:  _infra_pw["pv"]          = _solar_w
            if _grid_w   > 50:  _infra_pw["grid"]         = _grid_w
            if _ev_w     > 50:  _infra_pw["ev_charger"]   = _ev_w
            if _hp_w     > 50:  _infra_pw["heat_pump"]    = _hp_w
            if _boiler_w > 200: _infra_pw["boiler"]       = _boiler_w
            if _batt_w   > 200: _infra_pw["battery"]      = _batt_w
            # v4.3.26: voeg HIGH-confidence PowerCalc-entiteiten toe als bekende lasten
            if self._power_estimator:
                self._power_estimator.tick()
                _infra_pw.update(self._power_estimator.get_infra_powers())
            self._nilm.set_infra_powers(_infra_pw)

            # v2.2: ESPHome meter features doorgeven aan NILM-detector (alle fasen)
            if (self._config.get(CONF_DSMR_SOURCE) == DSMR_SOURCE_ESPHOME
                    and hasattr(self._nilm, "set_esphome_features")):
                self._nilm.set_esphome_features(
                    power_factor_l1   = self._esp_power_factor_l1,
                    power_factor_l2   = self._esp_power_factor_l2,
                    power_factor_l3   = self._esp_power_factor_l3,
                    inrush_peak_l1    = self._esp_inrush_peak_l1,
                    inrush_peak_l2    = self._esp_inrush_peak_l2,
                    inrush_peak_l3    = self._esp_inrush_peak_l3,
                    rise_time_l1      = self._esp_rise_time_l1,
                    rise_time_l2      = self._esp_rise_time_l2,
                    rise_time_l3      = self._esp_rise_time_l3,
                    reactive_power_l1 = getattr(self, "_esp_reactive_l1", None),
                    reactive_power_l2 = getattr(self, "_esp_reactive_l2", None),
                    reactive_power_l3 = getattr(self, "_esp_reactive_l3", None),
                    thd_l1            = getattr(self, "_esp_thd_l1", None),
                    thd_l2            = getattr(self, "_esp_thd_l2", None),
                    thd_l3            = getattr(self, "_esp_thd_l3", None),
                )

            # Solar learner + PV forecast
            inverter_data      = []
            pv_forecast_kwh         = None
            pv_forecast_tomorrow_kwh = None
            pv_forecast_hourly: list = []
            pv_forecast_hourly_tomorrow: list = []

            # v1.18.1: stroomuitval-detectie
            _outage_detected = False
            _outage_message  = ""
            if not hasattr(self, '_outage_streak'):
                self._outage_streak = 0
                self._outage_active = False
            inverter_profiles:  list = []

            if self._solar_learner and getattr(self, "_solar_learner_enabled", True):
                await self._solar_learner.async_update(phase_currents=self._limiter.phase_currents)

                # Vul ontbrekende pv_forecast uren aan vanuit solar_learner data
                # (lost het probleem op waarbij forecast leeg is na herstart)
                if self._pv_forecast:
                    for sl_prof in self._solar_learner.get_all_profiles():
                        _sl_eid = sl_prof.inverter_id if hasattr(sl_prof, "inverter_id") else None
                        if _sl_eid and hasattr(sl_prof, "hourly_peak_w") and sl_prof.peak_power_w:
                            self._pv_forecast.seed_from_learner(
                                inverter_id   = _sl_eid,
                                hourly_peak_w = sl_prof.hourly_peak_w,
                                peak_wp       = sl_prof.peak_power_w,
                            )

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

                    # Ceiling priority:
                    #   1. rated_power_w from config (user-configured, most reliable)
                    #   2. Self-learned ceiling (accumulated from confirmed plateau events)
                    #   3. No fallback to peak_power_w_7d — that is already the clipped
                    #      observed peak, using it as ceiling causes circular false positives.
                    if rated_w:
                        clipping_ceiling = rated_w
                    elif learned_ceiling_w:
                        clipping_ceiling = learned_ceiling_w
                    else:
                        clipping_ceiling = None  # not enough info — skip detection

                    # Maintain a combined window: pre-plateau (slope) + plateau readings.
                    # Total size = PLATEAU_PRE_SIZE + PLATEAU_WINDOW_SIZE so the oldest
                    # PLATEAU_PRE_SIZE values form the "was it rising?" reference.
                    total_win_size = PLATEAU_WINDOW_SIZE + PLATEAU_PRE_SIZE
                    win = self._plateau_windows.setdefault(
                        eid, deque(maxlen=total_win_size)
                    )
                    if cur_w > 0:
                        win.append(cur_w)

                    clipping = False
                    if clipping_ceiling and len(win) >= total_win_size:
                        pre_win     = list(win)[:PLATEAU_PRE_SIZE]   # older readings (slope)
                        plateau_win = list(win)[PLATEAU_PRE_SIZE:]   # recent readings (flat?)

                        if not plateau_win:  # safety guard
                            continue
                        plateau_mean = sum(plateau_win) / len(plateau_win)
                        variance     = sum((x - plateau_mean) ** 2 for x in plateau_win) / len(plateau_win)
                        stddev_w     = variance ** 0.5
                        stability    = stddev_w / plateau_mean if plateau_mean > 0 else 1.0

                        pre_mean = sum(pre_win) / len(pre_win)

                        # Adaptive stability threshold per inverter noise floor
                        baseline_stability = self._noise_baselines.get(eid, PLATEAU_STABILITY_PCT)
                        adaptive_threshold = max(PLATEAU_STABILITY_PCT, baseline_stability * 1.5)

                        # Update noise baseline when well below ceiling (not in clipping zone)
                        if plateau_mean < clipping_ceiling * 0.70:
                            prev = self._noise_baselines.get(eid, stability)
                            self._noise_baselines[eid] = prev * 0.95 + stability * 0.05

                        # Three conditions must all be true:
                        #   A. Recent window is flat (parabola top is cut off)
                        #   B. Flat level is close to the configured/learned ceiling
                        #   C. The readings BEFORE the plateau were still rising
                        #      (pre_mean < plateau_mean * ratio) — confirms it is a
                        #      parabola cut, not just a cloud or stable low production
                        rising_before = pre_mean < plateau_mean * PLATEAU_RISE_MAX_RATIO
                        if (stability < adaptive_threshold
                                and plateau_mean >= clipping_ceiling * CLIPPING_CEILING_FRAC
                                and rising_before):
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
                    from .energy_manager.pv_forecast import MIN_ORIENTATION_SAMPLES as _ORI_NEEDED
                    samples_needed = _ORI_NEEDED
                    hourly_yield = fp.get("hourly_yield_fraction", {})
                    learn_pct = round(min(100, clear_sky_samples / _ORI_NEEDED * 100), 0)
                    peak_hour = int(max(hourly_yield, key=lambda h: hourly_yield[h])) if hourly_yield else None

                    # Use provisional learned values immediately (even before confident)
                    # so the dashboard shows a rough estimate rather than "onbekend"
                    azimuth_eff = azimuth if azimuth is not None else az_learned
                    tilt_eff    = tilt    if tilt    is not None else ti_learned

                    votes = profile.phase_votes or {}
                    total_votes = sum(votes.values()) if isinstance(votes, dict) else 0

                    # Phase best-guess: show provisional L1/L2/L3 with confidence
                    # even before phase_certain is reached
                    _sl_prof = self._solar_learner.get_profile(eid) if self._solar_learner else None
                    if _sl_prof:
                        _pdf = self._solar_learner._phase_display_fields(_sl_prof)
                        _phase_display = _pdf["phase_display"]
                        _phase_conf    = _pdf["phase_confidence"]
                        _phase_prov    = _pdf["phase_provisional"]
                    else:
                        _phase_display = None
                        _phase_conf    = 0.0
                        _phase_prov    = True

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
                        "phase_display":     _phase_display,
                        "phase_confidence":  _phase_conf,
                        "phase_provisional": _phase_prov,
                        "samples":           profile.samples,
                        "confident":         profile.confident,
                        "azimuth_deg":       azimuth_eff,
                        "azimuth_learned":   az_learned,
                        "azimuth_compass":   _azimuth_compass(azimuth_eff),
                        "tilt_deg":          tilt_eff,
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
                pv_forecast_kwh          = self._pv_forecast.get_total_forecast_today_kwh(
                    produced_kwh=round(sum(self._pv_today_hourly_kwh), 2)
                )  # v4.6.492: dagtotaal = reeds geproduceerd + resterende forecast
                # v4.6.462: Forecast.Solar layer 3 status
                _fcsolar_status = {}
                if hasattr(self._pv_forecast, "get_forecast_solar_status"):
                    _fcsolar_status = self._pv_forecast.get_forecast_solar_status()
                pv_forecast_tomorrow_kwh = self._pv_forecast.get_total_forecast_tomorrow_kwh()
                # Cloud cover correctie: lees van weather entity of aparte sensor
                _cloud_eid = self._config.get("cloud_cover_sensor", "")
                _weather_eid = self._config.get("weather_entity", "")
                _cloud_pct = None
                if _cloud_eid:
                    _cs = self._safe_state(_cloud_eid)
                    if _cs and _cs.state not in ("unavailable", "unknown"):
                        try: _cloud_pct = float(_cs.state)
                        except: pass
                elif _weather_eid:
                    _ws = self._safe_state(_weather_eid)
                    if _ws:
                        # HA weather entity + Ecowitt attributes
                        _cloud_pct = (
                            _ws.attributes.get("cloud_coverage")
                            or _ws.attributes.get("cloudiness")
                            or _ws.attributes.get("cloud_cover")
                        )
                # Ecowitt specifieke sensoren (betere granulariteit dan HA weather)
                if _cloud_pct is None:
                    for _ecowitt_key in ["sensor.ecowitt_solar_and_uvi_solar_radiation",
                                         "sensor.ecowitt_cloud_ceiling"]:
                        _ec = self._safe_state(_ecowitt_key)
                        if _ec and _ec.state not in ("unavailable", "unknown"):
                            break
                if _cloud_pct is not None and hasattr(self._pv_forecast, "update_cloud_cover"):
                    self._pv_forecast.update_cloud_cover(_cloud_pct)

                inverter_profiles        = self._pv_forecast.get_all_profiles()
                for inv_id in [p["inverter_id"] for p in inverter_profiles]:
                    for hf in self._pv_forecast.get_forecast(inv_id):
                        pv_forecast_hourly.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                            "low_w":       hf.low_w,
                            "high_w":      hf.high_w,
                        })
                    for hf in self._pv_forecast.get_forecast_tomorrow(inv_id):
                        pv_forecast_hourly_tomorrow.append({
                            "inverter_id": inv_id,
                            "hour":        hf.hour,
                            "forecast_w":  hf.forecast_w,
                            "confidence":  hf.confidence,
                            "low_w":       hf.low_w,
                            "high_w":      hf.high_w,
                        })
                # Feed learner
                for inv in self._config.get(CONF_INVERTER_CONFIGS, []):
                    eid  = inv.get("entity_id","")
                    raw  = self._read_state(eid)
                    if raw is not None:
                        pw = self._calc.to_watts(eid, raw)
                        # FIX: None check on get_profile
                        profile = self._solar_learner.get_profile(eid) if self._solar_learner else None
                        learned_pk = profile.peak_power_w if profile else 0.0
                        rated_pk   = (next(
                            (c.get("rated_power_w", 0) for c in self._config.get(CONF_INVERTER_CONFIGS, [])
                             if c.get("entity_id") == eid), 0
                        ) or 0)
                        # Bootstrap: use max of learned peak, rated power, or current reading.
                        # Without this, peak_wp=0 → frac=0 → learning never triggers (circular).
                        pk = float(max(learned_pk, rated_pk, pw))
                        await self._pv_forecast.async_update(eid, pw, pk)

            # Multi-inverter manager
            # v4.5.105: gebruik all-in prijs (incl. EB+BTW) voor negatieve-prijs check —
            # ruwe EPEX kan negatief zijn terwijl all-in (incl. energiebelasting) nog positief is.
            _inv_price = (price_info.get("current_all_in")
                          if price_info.get("current_all_in") is not None
                          else current_price)
            inv_decisions: list = []
            if self._multi_inv_manager:
                inv_decisions = await self._multi_inv_manager.async_evaluate(
                    phase_currents    =self._limiter.phase_currents,
                    current_epex_price=_inv_price,
                )
                for d in inv_decisions:
                    if d.action in ("dim_pid","negative_price","dim_full"):
                        self._log_decision("solar_dim",
                            f"🔆 Omvormer {d.label}: {d.action} → {d.target_pct:.0f}% — {d.reason}")
                # v4.5.108: sla dimmer-status op voor alerts/banner
                _mgr_status = self._multi_inv_manager.get_status()
                _dimmer_states = {}
                for _ctrl in self._multi_inv_manager._controls:
                    _st = self._multi_inv_manager.get_dimmer_state(_ctrl.entity_id)
                    _st["label"] = _ctrl.label or _ctrl.entity_id
                    _dimmer_states[_ctrl.entity_id] = _st
                self._data["inverter_dimmer"] = {
                    "active":           any(d.action in ("dim_pid","negative_price","dim_full") for d in inv_decisions),
                    "negative_price":   any(d.action == "negative_price" for d in inv_decisions),
                    "decisions":        [{"label": d.label, "action": d.action, "pct": d.target_pct, "reason": d.reason} for d in inv_decisions],
                    "dimmer_enabled":   _mgr_status.get("dimmer_enabled", {}),
                    "controls":         [c.entity_id for c in self._multi_inv_manager._controls],
                    "dimmer_states":    _dimmer_states,
                }

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
                    self._log_decision(
                        "peak_shaving",
                        f"📊 Piekafschaving actief: {grid_import_w:.0f}W > {peak_data.get('limit_w',0):.0f}W — {peak_data.get('action','')}",
                        payload={
                            "grid_import_w":         round(grid_import_w, 1),
                            "limit_w":               peak_data.get("limit_w"),
                            "action":                peak_data.get("action"),
                            "ev_current_reduced_a":  peak_data.get("ev_current_a"),
                            "solar_curtailment_pct": peak_data.get("solar_curtailment_pct"),
                            "peak_margin_w":         round(peak_data.get("limit_w", 0) - grid_import_w, 1),
                        }
                    )

            # Boiler controller
            boiler_decisions: list = []

            # PV-surplus via centrale helper — batterij-ontlading telt NIET mee als surplus.
            _batt_w_now   = getattr(self, "_last_battery_w", 0.0)
            _solar_w_now  = float(data.get("solar_power", 0.0) or 0.0)
            _grid_w_now   = float(data.get("grid_power",  0.0) or 0.0)
            solar_surplus = self._calc_pv_surplus(_solar_w_now, _grid_w_now, _batt_w_now)

            # v1.18.1: stroomuitval — alle PV + netspanning = 0 overdag
            # v4.5.4: Verbeterde check — ook accu en huisverbruik meenemen.
            # Bij NOM (Nul Op Meter) en zelfvoorzienende huizen kan solar=0 EN grid=0
            # tegelijkertijd voorkomen terwijl de accu het huis volledig voedt.
            # In dat geval is er GEEN stroomstoring.
            _solar_w = _solar_w_now
            _grid_w  = abs(_grid_w_now)
            _hour    = datetime.now(timezone.utc).hour
            _batt_discharge = max(0.0, -getattr(self, "_last_battery_w", 0.0))  # ontladen = positief
            _house_w_check  = self._calc_house_load(_solar_w_now, _grid_w_now,
                                                    getattr(self, "_last_battery_w", 0.0))
            # Stroomstoring: PV=0, grid=0 én ook de accu ontlaadt niets en huis verbruikt niets
            # → alle meetpunten zijn 0 of nul terwijl het overdag is.
            # NOM/zelfvoorzienend: accu ontlaadt actief (batt_discharge > 50W) → geen storing
            _truly_zero = (
                _solar_w < 10
                and _grid_w < 5
                and _batt_discharge < 50      # accu ontlaadt niet → geen spanning in huis
                and _house_w_check < 50       # ook geen huidig huisverbruik meetbaar
            )
            if 7 <= _hour <= 20 and _truly_zero:
                self._outage_streak = getattr(self, '_outage_streak', 0) + 1
                if self._outage_streak >= 3 and not getattr(self, '_outage_active', False):
                    self._outage_active = True
                    _outage_detected = True
                    _outage_message = (
                        f"Mogelijke stroomstoring gedetecteerd: PV {_solar_w:.0f}W en "
                        f"netimport {_grid_w:.0f}W gedurende 3+ meting-cycli overdag ({_hour}:xx)."
                    )
                    _LOGGER.warning("CloudEMS: %s", _outage_message)
            else:
                self._outage_streak = 0
                self._outage_active = False
            _outage_detected = getattr(self, '_outage_active', False)
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
                # v4.6.60: controleer of Ariston cloud settings zijn aangekomen, retry indien niet
                try:
                    await self._boiler_ctrl.async_verify_pending()
                except Exception as _vp_err:
                    _LOGGER.debug("CloudEMS: boiler verify_pending fout (niet kritiek): %s", _vp_err)
                for bd in boiler_decisions:
                    # v4.5.11: log altijd — ook hold_off — zodat we kunnen zien waarom
                    # de boiler NIET aan ging terwijl dat misschien had gemoeten.
                    self._log_decision(
                        "boiler",
                        f"🔌 {bd.label}: {bd.action} — {bd.reason}",
                        payload={
                            "entity_id":       bd.entity_id,
                            "label":           bd.label,
                            "action":          bd.action,
                            "reason":          bd.reason,
                            "is_on":           bd.current_state,
                            "group_id":        getattr(bd, "group_id", None),
                            "priority_pct":    getattr(bd, "priority_pct", None),
                            "solar_surplus_w": round(solar_surplus, 1),
                            "price_eur_kwh":   round(current_price or 0, 5),
                        }
                    )
                    # v4.6.498: Fase 2 — registreer boilerbeslissing in DOL
                    try:
                        if bd.action in ("hold_on", "turn_on", "boost") and bd.current_state:
                            from .energy_manager.decision_outcome_learner import build_context_bucket
                            import datetime as _dt_b
                            _b_bucket = build_context_bucket(
                                "boiler", None, current_price or 0.0,
                                float((price_info or {}).get("avg_today") or 0),
                                solar_surplus,
                                month=_dt_b.datetime.now().month,
                                hour=_dt_b.datetime.now().hour,
                            )
                            # Schat energie: 2kWh per boost-beslissing (conservatief)
                            _b_kwh = 2.0
                            _b_alt = "hold_off" if bd.action in ("hold_on","turn_on","boost") else "boost"
                            self._decision_learner.record_decision(
                                component      = "boiler",
                                action         = bd.action,
                                alternative    = _b_alt,
                                context_bucket = _b_bucket,
                                price_eur_kwh  = current_price or 0.0,
                                energy_kwh     = _b_kwh,
                                eval_after_s   = 7200,  # evalueer na 2 uur
                            )
                    except Exception as _dol_b_err:
                        _LOGGER.debug("DOL boiler record fout: %s", _dol_b_err)
                # NILM-gebaseerd vermogen leren (als geen energiesensor geconfigureerd)
                try:
                    _nilm_devs = self._nilm.get_devices_for_ha() if self._nilm else []
                    if _nilm_devs:
                        self._boiler_ctrl.update_power_from_nilm(_nilm_devs)
                except Exception as _exc_ignored:
                    _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

            # Pool controller (zwembad filter + warmtepomp)
            pool_data: dict = {}
            if self._pool_ctrl and getattr(self, "_pool_enabled", True):
                try:
                    _pool_cfg     = self._config.get("pool", {}) or {}
                    _pool_temp_eid = _pool_cfg.get("temp_entity", "")
                    _pool_water_c: float | None = None
                    if _pool_temp_eid:
                        _pool_temp_st = self._safe_state(_pool_temp_eid)
                        if _pool_temp_st and _pool_temp_st.state not in ("unavailable","unknown"):
                            try:
                                _pool_water_c = float(_pool_temp_st.state)
                            except (ValueError, TypeError):
                                _pool_water_c = None
                    _pool_status = await self._pool_ctrl.async_evaluate(
                        pv_surplus_w = solar_surplus,
                        price_info   = price_info,
                        water_temp_c = _pool_water_c,
                    )
                    pool_data = self._pool_ctrl.get_status_dict(_pool_status)
                    await self._pool_ctrl.async_save()
                    # v4.5.11: log altijd (ook idle) voor volledig terugkijken
                    self._log_decision(
                        "pool_filter",
                        f"🏊 Filter: {_pool_status.filter_action.action} — {_pool_status.filter_action.reason}",
                        payload={
                            "action":          _pool_status.filter_action.action,
                            "reason":          _pool_status.filter_action.reason,
                            "solar_surplus_w": round(solar_surplus, 1),
                            "water_temp_c":    _pool_water_c,
                            "price_eur_kwh":   round(current_price or 0, 5),
                        }
                    )
                    self._log_decision(
                        "pool_heat",
                        f"🌡️ Warmtepomp: {_pool_status.heat_action.action} — {_pool_status.heat_action.reason}",
                        payload={
                            "action":          _pool_status.heat_action.action,
                            "reason":          _pool_status.heat_action.reason,
                            "solar_surplus_w": round(solar_surplus, 1),
                            "water_temp_c":    _pool_water_c,
                            "price_eur_kwh":   round(current_price or 0, 5),
                        }
                    )
                except Exception as _pool_exc:
                    _LOGGER.warning("CloudEMS PoolController fout: %s", _pool_exc)

            # Lamp Circulation — intelligente lampenbeveiliging + energiebesparing (v1.25.9)
            lamp_circ_data: dict = {
                "enabled": True, "active": False, "test_mode": False,
                "mode": "off", "reason": "Initialiseren...",
                "lamps_on": [], "lamps_on_labels": [], "next_switch_in_s": 0,
                "lamps_registered": 0, "lamps_active": 0, "lamps_excluded": 0,
                "lamps_with_phase": 0, "occupancy_state": "unknown",
                "occupancy_confidence": 0.0, "advice": "⏳ Lampen laden...",
                "phase_tip": "", "mimicry_active": False,
                "neg_price_active": False, "sun_derived_night": False, "lamp_phases": [],
            }
            if self._lamp_circulation and self._lamp_circulation_enabled:
                # Lazy re-discovery: als setup 0 lampen vond (HA nog niet volledig geladen),
                # probeer opnieuw bij elke update totdat er lampen zijn.
                if not self._lamp_circulation._lamps:
                    _discovered = [s.entity_id for s in self.hass.states.async_all("light")]
                    if _discovered:
                        # Lees altijd de actuele coordinator config — niet de stale lokale lamp_cfg.
                        # Zo blijft een via de UI uitgeschakelde module uitgeschakeld na lazy-discovery.
                        _lamp_cfg_live = self._config.get("lamp_circulation", {}) or {}
                        self._lamp_circulation.configure(
                            light_entities = _discovered,
                            excluded_ids   = _lamp_cfg_live.get("excluded_ids", []),
                            enabled        = _lamp_cfg_live.get("enabled", True),
                            min_confidence = float(_lamp_cfg_live.get("min_confidence", 0.55)),
                            night_start_h  = int(_lamp_cfg_live.get("night_start_h", 22)),
                            night_end_h    = int(_lamp_cfg_live.get("night_end_h", 7)),
                        )
                        _LOGGER.info(
                            "LampCirculation lazy-discovery: %d lampen gevonden",
                            len(_discovered),
                        )
                try:
                    _prev_occ = (self._data or {}).get("occupancy", {}) if hasattr(self, "_data") and self._data else {}
                    _occ_state = _prev_occ.get("state", "home")
                    _occ_conf  = _prev_occ.get("confidence", 0.3)
                    _phase_currents = getattr(self._limiter, "phase_currents", {}) if self._limiter else {}
                    _neg_price = (current_price is not None and current_price < 0)
                    _lamp_status = await self._lamp_circulation.async_tick(
                        occupancy_state      = _occ_state,
                        occupancy_confidence = _occ_conf,
                        phase_currents       = _phase_currents,
                        current_price_eur    = current_price,
                        negative_price       = _neg_price,
                    )
                    lamp_circ_data = self._lamp_circulation.get_status_dict(_lamp_status)
                    if _lamp_status.active:
                        _on = ", ".join(_lamp_status.lamps_on_labels) or "?"
                        self._log_decision("lamp_circulation",
                            f"💡 Lampcirculatie: [{_on}] aan — {_lamp_status.reason}")
                except Exception as _lc_exc:
                    _LOGGER.exception("CloudEMS LampCirculation fout: %s", _lc_exc)
                    # Zorg dat lamp_circ_data altijd een niet-lege dict is
                    # zodat de sensor "Standby" toont i.p.v. "Niet geconfigureerd"
                    lamp_circ_data = {
                        "enabled": True, "active": False, "test_mode": False,
                        "mode": "off", "reason": f"Fout: {_lc_exc}",
                        "lamps_on": [], "lamps_on_labels": [], "next_switch_in_s": 0,
                        "lamps_registered": len(getattr(self._lamp_circulation, "_lamps", [])),
                        "lamps_active": 0, "lamps_excluded": 0, "lamps_with_phase": 0,
                        "occupancy_state": "unknown", "occupancy_confidence": 0.0,
                        "advice": f"⚠️ Fout: {_lc_exc}", "phase_tip": "",
                        "mimicry_active": False, "neg_price_active": False,
                        "sun_derived_night": False, "lamp_phases": [],
                    }
            # ── Lamp Automation Engine ───────────────────────────────────────
            if self._lamp_auto and self._lamp_auto.enabled:
                try:
                    _sun_below = self._data.get("sun_below_horizon", False)
                    _la_actions = await self._lamp_auto.async_tick(
                        absence_state      = _occ_state,
                        sun_below_horizon  = bool(_sun_below),
                        lamp_learner       = self._lamp_circulation,
                        hour               = datetime.now().hour,
                        dow                = datetime.now().weekday(),
                    )
                    self._data["lamp_auto"] = self._lamp_auto.get_status()
                except Exception as _la_exc:
                    _LOGGER.debug("LampAutomation fout: %s", _la_exc)

            # ── Rolluiken evaluatie ───────────────────────────────────────────
            if self._shutter_ctrl is not None and getattr(self, "_shutter_enabled", False):
                try:
                    # v4.6.464: lees sun.sun automatisch — geen gebruikersconfiguratie nodig
                    _sun_state = self.hass.states.get("sun.sun")
                    _sol: dict = {}
                    if _sun_state and _sun_state.state not in ("unavailable", "unknown"):
                        _sun_az  = _sun_state.attributes.get("azimuth")
                        _sun_elv = _sun_state.attributes.get("elevation")
                        if _sun_az is not None and _sun_elv is not None:
                            _sol = {
                                "azimuth":   float(_sun_az),
                                "elevation": float(_sun_elv),
                            }
                    # Fallback: gebruik bestaande data["solar"] als sun.sun niet beschikbaar is
                    if not _sol:
                        _sol = data.get("solar", {})
                    _room_temps: dict = {}
                    _room_setpoints: dict = {}
                    # Haal kamertemperaturen op via zone_climate_manager indien beschikbaar
                    if hasattr(self, "_zone_climate") and self._zone_climate:
                        for zone in getattr(self._zone_climate, "_zones", []):
                            if getattr(zone, "area_id", None):
                                if zone.current_temp is not None:
                                    _room_temps[zone.area_id] = zone.current_temp
                                if zone.setpoint is not None:
                                    _room_setpoints[zone.area_id] = zone.setpoint
                                pass  # oriëntatie-learning verwijderd (ShutterThermalLearner heeft geen update())
                    # Voeg temperaturen toe van rolluiken met een losse sensor maar zonder zone climate
                    _az  = _sol.get("azimuth")
                    _elv = _sol.get("elevation")
                    for _scfg in getattr(self._shutter_ctrl, "_configs", []):
                        # v4.6.464: gebruik entity_id als fallback key als area_id leeg is
                        # zodat temp_sensor altijd gelezen wordt ongeacht HA-kamer koppeling
                        _rkey = _scfg.area_id or _scfg.entity_id
                        if _rkey and _rkey not in _room_temps and _scfg.temp_sensor:
                            _t = self._shutter_ctrl._read_temp_sensor(_scfg.temp_sensor)
                            if _t is not None:
                                _room_temps[_rkey] = _t
                                pass  # oriëntatie-learning verwijderd
                    # v4.3.7: poll weer en aanwezigheid elke cyclus
                    self._shutter_ctrl.poll_weather()
                    self._shutter_ctrl.poll_presence()
                    # v4.6.465: flush thermal learner
                    if getattr(self, "_shutter_thermal_learner", None):
                        await self._shutter_thermal_learner.async_flush_if_dirty()

                    # v4.6.538: outdoor_temp_c direct lezen — staat nooit in _gather_power_data()
                    # Prio 1: geconfigureerde buitentemperatuursensor
                    # Prio 2: vorige cyclus waarde uit self._data (fallback)
                    _shutter_outdoor_eid = self._config.get("outside_temp_entity", "")
                    _shutter_outdoor_t = self._read_state(_shutter_outdoor_eid) if _shutter_outdoor_eid else None
                    if _shutter_outdoor_t is None:
                        _shutter_outdoor_t = (self._data or {}).get("outdoor_temp_c")

                    shutter_decisions = await self._shutter_ctrl.async_evaluate(
                        outdoor_temp_c     = _shutter_outdoor_t,
                        solar_elevation_deg= _sol.get("elevation"),
                        solar_azimuth_deg  = _sol.get("azimuth"),
                        pv_surplus_w       = solar_surplus,
                        room_temps         = _room_temps,
                        room_setpoints     = _room_setpoints,
                    )
                    # v4.5.61: log de uitkomst per rolluik — gebruik de verse decision
                    # (niet last_action/last_reason want die worden niet bij idle bijgewerkt)
                    # v4.6.465: flush thermal learner
                    if getattr(self, "_shutter_thermal_learner", None):
                        await self._shutter_thermal_learner.async_flush_if_dirty()

                    try:
                        _sh_decisions_map = {d.entity_id: d for d in shutter_decisions}
                        for _sh_cfg in getattr(self._shutter_ctrl, "_configs", []):
                            _sh_eid   = getattr(_sh_cfg, "entity_id", None) or getattr(_sh_cfg, "cover_entity", None)
                            _sh_state = getattr(self._shutter_ctrl, "_states", {}).get(_sh_eid)
                            if _sh_state is None:
                                continue
                            _sh_dec      = _sh_decisions_map.get(_sh_eid)
                            _sh_action   = _sh_dec.action  if _sh_dec else getattr(_sh_state, "last_action", "idle")
                            _sh_reason   = _sh_dec.reason  if _sh_dec else getattr(_sh_state, "last_reason", "")
                            _sh_override = getattr(_sh_state, "override_action", "idle")
                            _sh_pos      = _sh_dec.position if _sh_dec else getattr(_sh_state, "last_position", None)
                            self._log_decision(
                                "shutter",
                                f"🪟 {_sh_eid}: {_sh_action} — {_sh_reason}",
                                payload={
                                    "entity_id":        _sh_eid,
                                    "action":           _sh_action,
                                    "reason":           _sh_reason,
                                    "position":         _sh_pos,
                                    "override":         _sh_override,
                                    "solar_elevation":  _sol.get("elevation"),
                                    "solar_azimuth":    _sol.get("azimuth"),
                                    "outdoor_temp_c":   _shutter_outdoor_t,
                                    "solar_surplus_w":  round(solar_surplus, 1),
                                    "room_temps":       _room_temps,
                                }
                            )
                    except Exception as _sh_log_err:
                        _LOGGER.debug("Rolluik-log mislukt: %s", _sh_log_err)

                    # v4.6.502: Fase 3 — registreer actieve rolluikbeslissingen in DOL
                    try:
                        from .energy_manager.decision_outcome_learner import build_context_bucket
                        import datetime as _dt_sh
                        _sh_hour = _dt_sh.datetime.now().hour
                        _sh_month = _dt_sh.datetime.now().month
                        for _sh_dec in shutter_decisions:
                            if _sh_dec.action in ("position", "close", "open"):
                                _sh_bucket = build_context_bucket(
                                    "shutter", None, current_price or 0.0,
                                    float((price_info or {}).get("avg_today") or 0),
                                    solar_surplus if 'solar_surplus' in dir() else 0.0,
                                    month=_sh_month, hour=_sh_hour,
                                )
                                # Schatting: 0.1 kWh thermisch voordeel per positie-stap
                                _sh_kwh  = 0.1
                                _sh_alt  = "idle"
                                self._decision_learner.record_decision(
                                    component      = "shutter",
                                    action         = _sh_dec.action,
                                    alternative    = _sh_alt,
                                    context_bucket = _sh_bucket,
                                    price_eur_kwh  = current_price or 0.0,
                                    energy_kwh     = _sh_kwh,
                                    eval_after_s   = 7200,  # evalueer na 2 uur
                                )
                    except Exception as _dol_sh_err:
                        _LOGGER.debug("DOL shutter record fout: %s", _dol_sh_err)
                except Exception as _sh_exc:
                    _LOGGER.exception("CloudEMS ShutterController fout: %s", _sh_exc)
            energy_tax   = float(self._config.get(CONF_ENERGY_TAX, 0.0))
            grid_power_w = p1_data.get("net_power_w") or data.get("grid_power", 0.0)
            # v4.5.6: energiebelasting alleen bij import (positief net), niet bij export
            # Bij export: geen energiebelasting → alleen spotprijs * export
            if grid_power_w >= 0:
                cost_ph = (grid_power_w / 1000.0) * (current_price + energy_tax)
            else:
                cost_ph = (grid_power_w / 1000.0) * current_price  # export: geen EB

            now_dt   = datetime.now(timezone.utc)
            day_k    = now_dt.strftime("%Y-%m-%d")
            month_k  = now_dt.strftime("%Y-%m")
            if self._cost_day_key   != day_k:   self._cost_today_eur = 0.0;  self._cost_day_key   = day_k
            if self._cost_month_key != month_k: self._cost_month_eur = 0.0;  self._cost_month_key = month_k
            self._cost_today_eur  = round(self._cost_today_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)
            self._cost_month_eur  = round(self._cost_month_eur  + cost_ph * (UPDATE_INTERVAL_FAST/3600.0), 4)

            # v4.5.11: prijslog — elk uur naar normal log, afwijkingen direct naar high log.
            # Zodat je later kunt controleren of EB, BTW en leverancier-opslag kloppen.
            _bk_price = getattr(self, "_learning_backup", None)
            if _bk_price is not None:
                _now_price_ts = time.time()
                _PRICE_LOG_INTERVAL_S = 3600  # elk uur
                if _now_price_ts - self._last_price_log >= _PRICE_LOG_INTERVAL_S:
                    self._last_price_log = _now_price_ts
                    try:
                        _pi       = price_info or {}
                        _from_prov = _pi.get("prices_from_provider", False)
                        _epex_raw  = _pi.get("current")           # kale EPEX in €/kWh
                        _all_in    = _pi.get("current_all_in")     # all-in zoals CloudEMS het berekent
                        _display   = _pi.get("current_display")
                        _eb        = _pi.get("tax_per_kwh", 0.0)
                        _btw_rate  = _pi.get("vat_rate", 0.21)
                        _markup    = _pi.get("supplier_markup_kwh", 0.0)
                        _inc_tax   = _pi.get("price_include_tax", False)
                        _inc_btw   = _pi.get("price_include_btw", False)
                        _country   = _pi.get("country", "NL")
                        _supplier  = self._config.get("selected_supplier", "none")
                        _cfg_eb    = float(self._config.get("energy_tax", 0.0))
                        _cfg_markup= float(self._config.get("supplier_markup", 0.0))
                        _learned_eb     = _pi.get("learned_eb_kwh")
                        _learned_btw    = _pi.get("learned_btw_rate")
                        _learned_markup = _pi.get("learned_markup_kwh")
                        _markup_samples = _pi.get("learned_markup_samples", 0)

                        # Reconstructie van de all-in berekening stap voor stap
                        _step_base   = round(_epex_raw, 5) if _epex_raw else None
                        _step_eb     = round(_eb, 5) if _inc_tax else 0.0
                        _step_markup = round(_markup, 5)
                        _step_sub    = round((_step_base or 0) + _step_eb + _step_markup, 5) if _step_base else None
                        _step_btw    = round(_step_sub * _btw_rate, 5) if (_step_sub and _inc_btw) else 0.0
                        _step_total  = round(_step_sub + _step_btw, 5) if _step_sub else None

                        _price_log = {
                            "supplier":           _supplier,
                            "country":            _country,
                            "from_provider":      _from_prov,
                            # Ruwe EPEX spotprijs
                            "epex_raw_eur_kwh":   round(_epex_raw, 5) if _epex_raw is not None else None,
                            # Configuratie-instellingen
                            "config_include_tax": _inc_tax,
                            "config_include_btw": _inc_btw,
                            "config_eb_eur_kwh":  round(_cfg_eb, 5),
                            "config_markup_eur_kwh": round(_cfg_markup, 5),
                            # Gebruikte waarden (kunnen geleerd zijn)
                            "used_eb_eur_kwh":    round(_eb, 5),
                            "used_markup_eur_kwh": round(_markup, 5),
                            "used_btw_rate":      round(_btw_rate, 4),
                            # Stap-voor-stap berekening
                            "calc": {
                                "step1_epex":   _step_base,
                                "step2_eb":     _step_eb,
                                "step3_markup": _step_markup,
                                "step4_subtotaal": _step_sub,
                                "step5_btw":    _step_btw,
                                "step6_all_in": _step_total,
                            },
                            # Uitkomst zoals CloudEMS het toont
                            "result_all_in_eur_kwh":  _all_in,
                            "result_display_eur_kwh": _display,
                            # Actueel verbruik en kosten
                            "grid_power_w":       round(grid_power_w, 1),
                            "cost_per_hour_eur":  round(cost_ph, 5),
                            "cost_today_eur":     round(self._cost_today_eur, 4),
                            "cost_month_eur":     round(self._cost_month_eur, 4),
                            # Zelfgeleerde correcties
                            "learned_eb_eur_kwh":    round(_learned_eb, 5) if _learned_eb else None,
                            "learned_btw_rate":      round(_learned_btw, 4) if _learned_btw else None,
                            "learned_markup_eur_kwh": round(_learned_markup, 5) if _learned_markup else None,
                            "learned_markup_samples": _markup_samples,
                            # Sanity: verschil tussen stap-voor-stap en gerapporteerde all-in
                            "sanity_diff_eur_kwh": round((_step_total - _all_in), 5)
                                if (_step_total is not None and _all_in is not None and not _from_prov) else None,
                        }
                        import asyncio as _aio_pr
                        _aio_pr.ensure_future(_bk_price.async_log_normal("price_hour", _price_log))

                        # Naar high log als de berekening niet klopt of verdacht is:
                        # - sanity_diff > 0.001 €/kWh (>0.1 ct verschil tussen reconstructie en output)
                        # - all-in < EPEX raw (BTW/EB werden niet opgeteld maar de vlag staat wel aan)
                        # - all-in > 1.00 €/kWh (extreem hoog — mogelijk dubbel-stapelen)
                        _sanity_diff = abs(_step_total - _all_in) if (_step_total and _all_in and not _from_prov) else 0.0
                        _price_too_low  = (_all_in is not None and _epex_raw is not None
                                           and _all_in < _epex_raw - 0.001
                                           and (_inc_tax or _inc_btw))
                        _price_too_high = (_all_in is not None and _all_in > 1.00)
                        # v4.5.11: waarschuw als EPEX actief is maar belastingen niet zijn aangevinkt
                        # all_in == epex_raw én geen provider → gebruiker heeft EB/BTW niet ingesteld
                        _price_no_tax   = (not _from_prov
                                           and not _inc_tax and not _inc_btw
                                           and _epex_raw is not None
                                           and abs(_all_in - _epex_raw) < 0.001
                                           and _eb > 0.01)
                        if _sanity_diff > 0.001 or _price_too_low or _price_too_high or _price_no_tax:
                            _reason = []
                            if _sanity_diff > 0.001: _reason.append(f"sanity_diff={_sanity_diff:.4f}")
                            if _price_too_low:        _reason.append("all_in<epex (EB/BTW geconfigureerd maar prijs daalt?)")
                            if _price_too_high:       _reason.append("all_in>1.00 EUR/kWh")
                            if _price_no_tax:         _reason.append(
                                f"prijs=EPEX-only (€{_all_in:.4f}/kWh) — "
                                f"energiebelasting (€{_eb:.5f}/kWh) en BTW ({int(_btw_rate*100)}%) "
                                f"zijn NIET aangevinkt in CloudEMS wizard → werkelijke prijs ~€{_all_in + _eb * (1 + _btw_rate):.4f}/kWh"
                            )
                            _price_log["anomaly_reasons"] = _reason
                            _aio_pr.ensure_future(_bk_price.async_log_high("price_anomaly", _price_log))
                    except Exception as _pe:
                        _LOGGER.debug("Prijs-log schrijven mislukt: %s", _pe)

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

            # v4.4.5: ML verbruiksforecast observatie (1x per uur)
            ml_forecast_data: dict = {}
            if self._ml_forecaster:
                try:
                    _now_h = datetime.now(timezone.utc)
                    if _now_h.minute == 0 and _now_h.second < 30:  # Begin van elk uur
                        _kwh_last_hour = data.get("import_kwh_today", 0.0)
                        _outside_temp  = float(self._read_state(self._config.get("outside_temp_entity","")) or self._thermal_model._last_outside_temp if self._thermal_model else 10.0)
                        _pv_yesterday  = data.get("pv_kwh_yesterday", 0.0)
                        if not self.learning_frozen:
                            self._ml_forecaster.add_observation(
                                kwh_this_hour    = _kwh_last_hour / max(1, _now_h.hour or 1),
                                t_outside_c      = _outside_temp,
                                pv_kwh_yesterday = _pv_yesterday,
                            )
                    # Voorspelling bouwen
                    _t_forecast = [float(self._read_state(self._config.get("outside_temp_entity","")) or 10.0)] * 24
                    ml_result = self._ml_forecaster.forecast(
                        t_outside_forecast = _t_forecast,
                        pv_kwh_yesterday   = data.get("pv_kwh_yesterday", 0.0),
                    )
                    ml_forecast_data = {
                        "next_hour_kwh":    ml_result.next_hour_kwh,
                        "forecast_24h":     ml_result.forecast_24h,
                        "model_trained":    ml_result.model_trained,
                        "training_samples": ml_result.training_samples,
                        "mape_7d_pct":      ml_result.mape_7d_pct,
                        "method":           ml_result.method,
                        "feature_importance": self._ml_forecaster.get_feature_importance(),
                    }
                    await self._ml_forecaster.async_maybe_save()
                except Exception as _ml_err:
                    _LOGGER.debug("MLForecast fout: %s", _ml_err)

                # v4.5.118: ML-verbruiksforecast opslaan in _data voor gebruik door zones en bridge
                if ml_forecast_data:
                    self._data["ml_consumption_forecast"] = ml_forecast_data
            if self._energy_balancer:
                try:
                    await self._store_balancer.async_save(
                        self._energy_balancer.to_dict()
                    )
                except Exception as _bal_err:
                    _LOGGER.debug("EnergyBalancer save fout: %s", _bal_err)
            # v4.6.522: sensor interval registry opslaan (rate-limited intern)
            if self._sensor_interval_registry:
                try:
                    await self._sensor_interval_registry.async_maybe_save()
                except Exception as _sir_err:
                    _LOGGER.debug("SensorIntervalRegistry save fout: %s", _sir_err)
            if self._phase_fusion:
                try:
                    await self._phase_fusion.async_maybe_save()
                except Exception as _pf_err:
                    _LOGGER.debug("PhaseCurrentFusion save fout: %s", _pf_err)
            if self._kirchhoff_monitor:
                try:
                    await self._kirchhoff_monitor.async_maybe_save()
                except Exception as _km_err:
                    _LOGGER.debug("KirchhoffDriftMonitor save fout: %s", _km_err)
            # v4.6.533: save alle nieuwe kwaliteitsmodules
            for _save_mod in (
                self._phase_consistency,   self._inverter_efficiency,
                self._tariff_consistency,  self._wiring_topology,
                self._sign_consistency,    self._appliance_degradation,
                self._standby_drift,       self._bde_quality,
                self._shutter_comfort,     self._integration_latency,
                self._p1_quality,          self._savings_attribution,
                self._arbitrage_quality,   self._topology_validator,
            ):
                if _save_mod and hasattr(_save_mod, "async_maybe_save"):
                    try:
                        await _save_mod.async_maybe_save()
                    except Exception as _sm_err:
                        _LOGGER.debug("%s save fout: %s", type(_save_mod).__name__, _sm_err)

            # v1.10.3: Home baseline anomaly + standby + occupancy (always-on)
            grid_w = data.get("grid_power", 0.0)
            baseline_data = self._home_baseline.update(grid_w) if (self._home_baseline and not self.learning_frozen) else {}

            # v1.10.3: EV session learner (auto-detects sessions from charger current)
            ev_session_data: dict = {}
            if self._ev_session:
                ev_current_a = 0.0
                ev_eid = self._config.get("ev_charger_entity", "")
                if ev_eid:
                    ev_st = self._safe_state(ev_eid)
                    if ev_st and ev_st.state not in ("unavailable", "unknown"):
                        try:
                            ev_current_a = float(ev_st.state)
                        except (ValueError, TypeError):
                            ev_current_a = 0.0
                ev_session_data = self._ev_session.update(
                    ev_current_a,
                    current_price or 0.0,
                    solar_w=float(data.get("solar_power", 0) or 0),
                    grid_w=float(data.get("grid_power", 0) or 0),
                    co2_g_per_kwh=float(data.get("grid_co2_g_per_kwh", 300) or 300),
                ) if not self.learning_frozen else {}

            # v1.10.3: NILM schedule learner (enriches device list with schedule metadata)
            nilm_devices_raw = self._nilm.get_devices_for_ha()

            # v1.17: Hybride NILM tick + anker-apparaten samenvoegen
            # v1.22: alleen als schakelaar AAN is
            if self._hybrid and self._nilm_active and self._hybrid_nilm_active:
                await self._hybrid.async_tick()
                anchored = self._hybrid.get_anchored_devices()
                # Verwijder NILM-dubbelingen op basis van entity_id (v1.17.1 fix:
                # niet op device_type+phase — alle stopcontacten hebben device_type='socket'
                # en dat zou alle maar 1 weggooien).
                anchored_eids = {a["entity_id"] for a in anchored if "entity_id" in a}
                # Verwijder ook NILM-apparaten die hetzelfde NAMED apparaat zijn als een anker
                # (bijv. als NILM ook een "washing_machine" detecteert die al via stekker gemeten wordt)
                anchored_named = {
                    (a["device_type"], a["phase"])
                    for a in anchored
                    if a.get("device_type") not in ("socket", "unknown", None)
                }
                nilm_devices_raw = [
                    d for d in nilm_devices_raw
                    if d.get("entity_id") not in anchored_eids
                    and (d.get("device_type"), d.get("phase")) not in anchored_named
                ] + anchored

            if self._nilm_schedule:
                nilm_devices_enriched = self._nilm_schedule.update(nilm_devices_raw)
                nilm_schedule_summary = self._nilm_schedule.get_schedule_summary()
            else:
                nilm_devices_enriched = nilm_devices_raw
                nilm_schedule_summary = []

            # v2.6: levensduur-verrijking (cycli + slijtage-%)
            try:
                nilm_devices_enriched = enrich_devices_with_wear(nilm_devices_enriched)
            except Exception as _lf_err:
                _LOGGER.debug("Levensduur verrijking fout: %s", _lf_err)

            # v4.6.484: realtime kWh accumulatie voor altijd-aan apparaten (smart_plug)
            # Gewone NILM apparaten ticken via detector.tick_energy() (alleen als is_on=True).
            # Smart_plug/anchor apparaten draaien altijd maar zitten niet in self._devices
            # van de detector → tick_energy wordt nooit aangeroepen → teller blijft 0.
            # Fix: accumuleer hier per cyclus op basis van huidig vermogen.
            try:
                import datetime as _dt_akwh
                _today_k = _dt_akwh.date.today().isoformat()
                if self._anchor_kwh_day != _today_k:
                    # Nieuwe dag — zet yesterday = today en reset today
                    self._anchor_kwh_yesterday = dict(self._anchor_kwh_today)
                    self._anchor_kwh_today     = {}
                    self._anchor_kwh_day       = _today_k
                # Accumuleer per cyclus: W × interval_s / 3600000 = kWh
                for _d in nilm_devices_enriched:
                    if _d.get("source") != "smart_plug":
                        continue
                    _did   = _d.get("device_id") or _d.get("entity_id", "")
                    _pw    = float(_d.get("current_power") or 0.0)
                    if _did and _pw > 0:
                        _kwh_inc = _pw * UPDATE_INTERVAL_FAST / 3_600_000.0
                        self._anchor_kwh_today[_did] = round(
                            self._anchor_kwh_today.get(_did, 0.0) + _kwh_inc, 4
                        )
                # Opslaan elke 60s
                if time.time() - self._anchor_kwh_last_save > 60:
                    self.hass.async_create_task(self._store_anchor_kwh.async_save({
                        "day":       _today_k,
                        "today":     self._anchor_kwh_today,
                        "yesterday": self._anchor_kwh_yesterday,
                    }))
                    # v4.6.493: sla ook per-uur solar kWh op
                    self.hass.async_create_task(self._store_pv_hourly.async_save({
                        "day":       _today_k,
                        "today":     list(self._pv_today_hourly_kwh),
                        "yesterday": list(getattr(self, "_pv_yesterday_hourly_kwh", [0.0] * 24)),
                    }))
                    self._anchor_kwh_last_save = time.time()
            except Exception as _akwh_err:
                _LOGGER.debug("CloudEMS: anchor kWh accumulatie fout: %s", _akwh_err)

            # v4.4.1: Trusted device lijst — één geïntegreerd vertrouwensmodel.
            #
            # Een apparaat telt mee in vermogenstotalen als het aan MINIMAAL ÉÉN
            # van de volgende criteria voldoet:
            #
            #   A. Fysiek gemeten     : source="smart_plug" → altijd vertrouwd
            #   B. Gebruiker bevestigd: confirmed=True + on_events >= 2
            #   C. PowerCalc HIGH     : SPE confidence=HIGH (merk/model profiel)
            #   D. NILM geleerd       : confidence >= 0.75 + on_events >= 5
            #                          + power_w <= max_fase_w * 0.80
            #
            # Harde uitsluitingen (ook bij A/B/C):
            #   • current_power > max_fase_w * 0.80  → hoogstwaarschijnlijk totaalmeting
            #   • current_power > 6000W              → boven 1 volbelaste 25A fase
            #
            # nilm_devices_enriched blijft VOLLEDIG voor het dashboard — gebruiker
            # kan lage-confidence apparaten zien en bevestigen/afwijzen.

            # Bouw SPE HIGH-set op (entity_ids met PowerCalc HIGH confidence)
            _spe_high_eids: set = set()
            if self._power_estimator:
                try:
                    for _spe_s in self._power_estimator.get_all_states():
                        if _spe_s.get("confidence") == "high":
                            _spe_high_eids.add(_spe_s.get("entity_id", ""))
                except Exception as _exc_ignored:
                    _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

            # Fasevermogen per fase uit de baselines van de NILM-detector
            _phase_baselines = getattr(self._nilm, "_baseline_power", {})
            _max_fase_w = max(_phase_baselines.values()) if _phase_baselines else 6000.0
            # Minimaal 500W als bovengrens zodat kleine installaties niet alles blokkeren
            _max_fase_w = max(_max_fase_w, 500.0)
            # Harde maximum: 1 fase bij 25A = 5750W, neem ruim 6000W als absoluut plafond
            _power_ceiling = min(_max_fase_w * 0.80, 6000.0)

            def _is_trusted(d: dict) -> bool:
                power_w = float(d.get("current_power") or 0)

                # Harde bovengrens — ongeacht bron
                if power_w > _power_ceiling and d.get("is_on"):
                    return False

                # A: fysiek gemeten via smart plug
                if d.get("source") == "smart_plug":
                    return True

                # B: gebruiker heeft bevestigd + minimaal 2× gezien
                if d.get("confirmed") and int(d.get("on_events", 0)) >= 2:
                    return True

                # C: PowerCalc HIGH confidence (merk/model profiel aanwezig)
                eid = d.get("entity_id") or d.get("source_entity_id", "")
                if eid and eid in _spe_high_eids:
                    return True

                # D: NILM geleerd met voldoende zekerheid en herhaling
                conf   = float(d.get("confidence", 0))
                events = int(d.get("on_events", 0))
                if conf >= 0.75 and events >= 5:
                    return True

                return False

            # Annoteer elk device met trust_status zodat dashboard dit kan tonen
            def _trust_reason(d: dict) -> str:
                power_w = float(d.get("current_power") or 0)
                if power_w > _power_ceiling and d.get("is_on"):
                    return f"uitgesloten: vermogen {power_w:.0f}W > plafond {_power_ceiling:.0f}W"
                if d.get("source") == "smart_plug":
                    return "vertrouwd: fysiek gemeten"
                if d.get("confirmed") and int(d.get("on_events", 0)) >= 2:
                    return "vertrouwd: bevestigd door gebruiker"
                eid = d.get("entity_id") or d.get("source_entity_id", "")
                if eid and eid in _spe_high_eids:
                    return "vertrouwd: PowerCalc profiel"
                conf   = float(d.get("confidence", 0))
                events = int(d.get("on_events", 0))
                if conf >= 0.75 and events >= 5:
                    return f"vertrouwd: {conf*100:.0f}% confidence, {events}× gezien"
                return f"onzeker: {conf*100:.0f}% confidence, {events}× gezien"

            for _d in nilm_devices_enriched:
                _d["trust_status"] = _trust_reason(_d)
                _d["is_trusted"]   = _is_trusted(_d)

            nilm_devices_trusted = [d for d in nilm_devices_enriched if _is_trusted(d)]

            _trusted_on_w = sum(
                float(d.get("current_power") or 0)
                for d in nilm_devices_trusted if d.get("is_on")
            )
            _total_on_w = sum(
                float(d.get("current_power") or 0)
                for d in nilm_devices_enriched if d.get("is_on")
            )
            if _total_on_w > _trusted_on_w + 50:
                _LOGGER.debug(
                    "NILM trusted filter: %.0fW → %.0fW "
                    "(%.0fW uitgesloten: lage confidence of >%.0fW phaseplafond)",
                    _total_on_w, _trusted_on_w,
                    _total_on_w - _trusted_on_w, _power_ceiling,
                )

            # v1.10.3: Weather calibration for PV forecast
            # v4.5.11: Periodieke diagnostiek naar cloudems_diag.log (elk uur)
            _backup = getattr(self, "_learning_backup", None)
            if _backup is not None:
                _now_ts = time.time()
                _DIAG_INTERVAL_S = 3600  # 1× per uur
                if _now_ts - self._last_diag_log >= _DIAG_INTERVAL_S:
                    self._last_diag_log = _now_ts
                    try:
                        _nilm_summary = [
                            {
                                "name":       d.get("user_name") or d.get("name", ""),
                                "type":       d.get("device_type", ""),
                                "phase":      d.get("phase", "?"),
                                "power_w":    round(float(d.get("current_power") or 0), 1),
                                "conf_pct":   round(float(d.get("confidence") or 0) * 100, 0),
                                "on_events":  d.get("on_events", 0),
                                "is_on":      d.get("is_on", False),
                                "confirmed":  d.get("confirmed", False),
                                "source":     d.get("source", "nilm"),
                            }
                            for d in nilm_devices_enriched
                        ]
                        _phase_src = getattr(self._nilm, "_sensor_input_log", {}) if self._nilm else {}
                        _phase_cert = getattr(self._nilm, "_phase_source_certain", {}) if self._nilm else {}
                        _bal_now = data.get("_balancer")
                        _bal_diag = self._energy_balancer.get_diagnostics() if self._energy_balancer else {}

                        # v4.5.64: onverklaard vermogen = house_w - NILM-som
                        _house_w_now = round(float(_bal_now.house_w if _bal_now else data.get("house_power", 0) or 0), 1)
                        _undefined_w = max(0.0, round(_house_w_now - _total_on_w, 1))
                        _undef_name = self._undefined_power_name or "Onverklaard vermogen"

                        _diag_payload = {
                            "nilm_device_count":    len(nilm_devices_enriched),
                            "nilm_active_count":    sum(1 for d in nilm_devices_enriched if d.get("is_on")),
                            "nilm_trusted_count":   len(nilm_devices_trusted),
                            "nilm_total_on_w":      round(_total_on_w, 1),
                            "nilm_trusted_on_w":    round(_trusted_on_w, 1),
                            "undefined_power_w":    _undefined_w,
                            "undefined_power_name": _undef_name,
                            "phase_sources":        _phase_src,
                            "phase_certain":        _phase_cert,
                            "nilm_devices":         _nilm_summary,
                            # v4.5.11: Kirchhoff-balancer data voor diagnose
                            "grid_power_w":         round(float(data.get("grid_power", 0)), 1),
                            "solar_power_w":        round(float(data.get("solar_power", 0) or 0), 1),
                            "battery_power_w":      round(float(getattr(self, "_last_battery_w", 0) or 0), 1),
                            "house_power_w":        _house_w_now,
                            "balancer": {
                                "house_w":          round(_bal_now.house_w, 1) if _bal_now else None,
                                "grid_w":           round(_bal_now.grid_w, 1) if _bal_now else None,
                                "solar_w":          round(_bal_now.solar_w, 1) if _bal_now else None,
                                "battery_w":        round(_bal_now.battery_w, 1) if _bal_now else None,
                                "imbalance_w":      round(_bal_now.imbalance_w, 1) if _bal_now else None,
                                "stale_sensors":    _bal_now.stale_sensors if _bal_now else [],
                                "lag_comp":         _bal_now.lag_compensated if _bal_now else False,
                                "battery_stale":    _bal_diag.get("battery_stale"),
                                "battery_interval_s": _bal_diag.get("battery_interval_s"),
                                "battery_lag_s":    _bal_diag.get("battery_learned_lag_s"),
                                "battery_lag_conf": _bal_diag.get("battery_lag_confidence"),
                            },
                        }
                        import asyncio as _asyncio
                        _asyncio.ensure_future(
                            _backup.async_log_normal("nilm_cycle", _diag_payload)
                        )
                    except Exception as _de:
                        _LOGGER.debug("DiagLog schrijven mislukt: %s", _de)
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
                    for dev in nilm_devices_trusted:
                        if dev.get("device_type") in ("heat_pump", "boiler", "cv_boiler", "heat") and dev.get("is_on"):
                            heating_w += float(dev.get("current_power") or 0)
                    if heating_w == 0:
                        # Fallback: use total grid import as rough proxy
                        heating_w = max(0.0, data.get("grid_power", 0.0))
                    self._thermal_model.update(heating_w=heating_w, outside_temp_c=outside_temp_c) if not self.learning_frozen else None
                therm_obj  = self._thermal_model.get_data()
                from .energy_manager.thermal_model import MIN_SAMPLES_RELIABLE as _TH_NEEDED
                thermal_data = {
                    "w_per_k":             therm_obj.w_per_k,
                    "samples":             therm_obj.samples,
                    "samples_needed":      _TH_NEEDED,
                    "progress_pct":        round(min(100, therm_obj.samples / _TH_NEEDED * 100)),
                    "reliable":            therm_obj.reliable,
                    "rating":              therm_obj.rating,
                    "advice":              therm_obj.advice,
                    "heating_days":        therm_obj.heating_days,
                    "last_heating_w":      therm_obj.last_heating_w,
                    "last_outside_temp_c": therm_obj.last_outside_temp_c,
                }
                await self._thermal_model.async_maybe_save()

            # v4.4.5: Vloer thermische buffer update
            floor_buffer_data: dict = {}
            if self._floor_buffer:
                try:
                    outside_temp_eid = self._config.get("outside_temp_entity", "")
                    _t_out  = self._read_state(outside_temp_eid) if outside_temp_eid else 5.0
                    _t_room = self._read_state(self._config.get("indoor_temp_entity", "")) or 20.0
                    _t_floor_eid = self._config.get("floor_temp_entity", "")
                    _t_floor = self._read_state(_t_floor_eid) if _t_floor_eid else None
                    # Vloerverwarmingsvermogen via NILM of config
                    _p_floor = 0.0
                    for dev in nilm_devices_trusted:
                        if dev.get("device_type") in ("floor_heat", "underfloor") and dev.get("is_on"):
                            _p_floor += float(dev.get("current_power") or 0)
                    if not self.learning_frozen:
                        self._floor_buffer.update(
                            p_floor_w   = _p_floor,
                            t_floor_c   = _t_floor,
                            t_room_c    = float(_t_room),
                            t_outside_c = float(_t_out or 5.0),
                        )
                    fb_status = self._floor_buffer.get_status()
                    floor_buffer_data = {
                        "state":             fb_status.state,
                        "t_floor_c":         fb_status.t_floor_c,
                        "c_floor_wh_k":      fb_status.c_floor_wh_k,
                        "ua_floor_w_k":      fb_status.ua_floor_w_k,
                        "charge_windows":    fb_status.charge_windows,
                        "savings_today_eur": fb_status.savings_today_eur,
                        "confidence":        fb_status.confidence,
                        "advice":            fb_status.advice,
                    }
                    await self._floor_buffer.async_maybe_save()
                except Exception as _fb_err:
                    _LOGGER.debug("FloorBuffer update fout: %s", _fb_err)

            # v1.15.0: Outdoor temp fallback via Open-Meteo when no sensor configured
            outside_temp_eid = self._config.get("outside_temp_entity", "")
            outside_temp_c_val = self._read_state(outside_temp_eid) if outside_temp_eid else None
            if outside_temp_c_val is None and self._thermal_model:
                outside_temp_c_val = await self._thermal_model.async_fetch_outdoor_temp(
                    session=self._session
                )
            # v4.6.477: automatische fallback via weather entiteit als nog geen buitentemp
            if outside_temp_c_val is None:
                for _w_eid in ["weather.forecast_thuis", "weather.forecast_home", "weather.home"]:
                    _w_st = self.hass.states.get(_w_eid)
                    if _w_st and _w_st.state not in ("unavailable", "unknown"):
                        _t = _w_st.attributes.get("temperature")
                        if _t is not None:
                            try:
                                outside_temp_c_val = float(_t)
                                break
                            except (ValueError, TypeError):
                                pass

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
                    for dev in nilm_devices_trusted:
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
                ) if not self.learning_frozen else COPReport(
                    cop_current=None, cop_at_7c=None, cop_at_2c=None,
                    cop_at_minus5c=None, defrost_today=0,
                    defrost_threshold_c=0.0, outdoor_temp_c=None,
                    reliable=False, method="frozen", curve={},
                )
                from .energy_manager.heat_pump_cop import MIN_SAMPLES_RELIABLE as _COP_NEEDED
                _cop_buckets = getattr(self._hp_cop, "_buckets", {})
                _cop_total   = sum(b.samples for b in _cop_buckets.values())
                _cop_rel_bkt = sum(1 for b in _cop_buckets.values() if b.samples >= _COP_NEEDED)
                hp_cop_data = {
                    "cop_current":       cop_result.cop_current,
                    "cop_at_7c":         cop_result.cop_at_7c,
                    "cop_at_2c":         cop_result.cop_at_2c,
                    "cop_at_minus5c":    cop_result.cop_at_minus5c,
                    "defrost_today":     cop_result.defrost_today,
                    "outdoor_temp_c":    cop_result.outdoor_temp_c,
                    "reliable":          cop_result.reliable,
                    "method":            cop_result.method,
                    "curve":             cop_result.curve,
                    "defrost_threshold_c": cop_result.defrost_threshold_c,
                    "total_samples":     _cop_total,
                    "reliable_buckets":  _cop_rel_bkt,
                    "progress_pct":      round(min(100, _cop_rel_bkt / max(1, len(_cop_buckets)) * 100)) if _cop_buckets else 0,
                    "degradation_detected": cop_result.degradation_detected,
                    "degradation_pct":   cop_result.degradation_pct,
                    "degradation_advice": cop_result.degradation_advice,
                }
                await self._hp_cop.async_maybe_save()

                # HeatPumpCOP → SmartClimate seed (koppeling feature 6)
                if cop_result.reliable and self._smart_climate:
                    _outdoor_c = cop_result.outdoor_temp_c
                    _rate_est  = self._hp_cop.get_heating_rate_estimate(_outdoor_c)
                    if _rate_est and hasattr(self._smart_climate, "_predictive"):
                        _pred = self._smart_climate._predictive
                        for _zone_name in getattr(self._smart_climate, "_zone_names", []):
                            _pred.seed_from_cop_estimate(_zone_name, _rate_est)

            # Feature 2: Flexible power score
            from .energy_manager.flex_score import calculate_flex_score
            ev_connected      = bool(self._config.get("ev_charger_entity") and data.get("ev_decision"))
            batt_soc          = self._read_state(self._config.get("battery_soc_entity", ""))
            if batt_soc is not None:
                try:
                    self._last_soc_pct = float(batt_soc)
                except (ValueError, TypeError):
                    pass
            # v4.5.66: Fallback via BatteryProviderRegistry (provider-onafhankelijk).
            # Voorheen: alleen Zonneplan — nu: elke geconfigureerde provider.
            # Fix: _last_soc_pct ook bijwerken als SOC via provider binnenkomt.
            if batt_soc is None and getattr(self, "_battery_providers", None):
                for _bp in self._battery_providers.available_providers:
                    if _bp.is_available:
                        _bp_state = _bp.read_state()
                        if _bp_state.soc_pct is not None:
                            batt_soc = _bp_state.soc_pct
                            try:
                                self._last_soc_pct = float(batt_soc)
                            except (ValueError, TypeError):
                                pass
                            break
            batt_capacity     = float(self._config.get("battery_capacity_kwh", 0) or 0)
            batt_max_kw       = float(self._config.get("battery_max_charge_kw", 0) or 0)
            import inspect as _inspect
            _flex_params = set(_inspect.signature(calculate_flex_score).parameters.keys())
            _flex_kwargs = {
                "battery_soc_pct":       batt_soc,
                "battery_capacity_kwh":  batt_capacity or None,
                "battery_max_charge_kw": batt_max_kw or None,
                "ev_connected":          ev_connected,
                "ev_max_charge_kw":      float(self._config.get("ev_max_charge_kw", 7.4) or 7.4),
                "ev_session_hours_remaining": float(ev_session_data.get("predicted_duration_h") or 2.0),
                "boiler_status":         self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                "boiler_groups_status":  self._boiler_ctrl.get_groups_status() if self._boiler_ctrl else [],
                "boiler_weekly_budget":  self._boiler_ctrl.get_weekly_budget() if self._boiler_ctrl else {},
                "boiler_p1_active":      (self._boiler_ctrl._p1_surplus_w > 0 and
                                          (time.time() - self._boiler_ctrl._p1_last_ts) < 90)
                                         if self._boiler_ctrl else False,
                "nilm_devices":          nilm_devices_enriched,
            }
            flex_result = calculate_flex_score(
                **{k: v for k, v in _flex_kwargs.items() if k in _flex_params}
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
                _grid_w   = float(data.get("grid_power_w") or data.get("grid_power") or 0.0)
                _import_w = max(0.0, data.get("import_power",  _grid_w if _grid_w > 0 else 0.0))
                _export_w = max(0.0, data.get("export_power", -_grid_w if _grid_w < 0 else 0.0))
                self._self_consumption.tick(
                    pv_w     = max(0.0, data.get("solar_power", 0.0)),
                    import_w = _import_w,
                    export_w = _export_w,
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
                if not self.learning_frozen:
                    self._day_classifier.observe_power(max(0.0, data.get("import_power", data.get("grid_power", 0.0))))
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
                # Feed current NILM detections — v1.20: alleen bevestigde apparaten
                # (user_feedback="correct" of confidence=1.0) krijgen drift-tracking.
                # Onbevestigde detecties hebben een onzekere baseline en geven anders
                # valse drift-waarschuwingen voor dingen die de NILM zelf nog niet
                # goed heeft geleerd.
                for dev in nilm_devices_trusted:
                    if not (dev.get("is_on") and dev.get("current_power")):
                        continue
                    _confirmed   = bool(dev.get("confirmed", False))
                    _confidence  = float(dev.get("confidence", 0))
                    _feedback_ok = dev.get("user_feedback", "") == "correct"
                    _is_anchor   = dev.get("source", "") == "smart_plug"
                    # Drift alleen tracken als: bevestigd door gebruiker, OF 100% confidence
                    # (smart plug anchor), OF eerder handmatig gecorrigeerd
                    if not (_confirmed or _confidence >= 1.0 or _feedback_ok or _is_anchor):
                        continue
                    # v1.25.8: Sla omvormer/PV/batterij-sensoren over — hun output varieert van nature
                    _label_lower = (dev.get("name") or dev.get("label") or "").lower()
                    _eid_lower   = dev.get("entity_id", "").lower()
                    _is_variable = any(k in _label_lower or k in _eid_lower for k in (
                        "pv", "solar", "omvormer", "inverter", "growatt", "goodwe",
                        "solaredge", "fronius", "enphase", "sma ", "output power",
                        "battery", "batterij", "soc",
                        "electricity meter", "energieproductie", "grid export", "grid import",
                    ))
                    if _is_variable:
                        continue
                    if not self.learning_frozen:
                        self._device_drift.record_detection(
                                device_id   = dev.get("device_id", ""),
                                device_type = dev.get("device_type", ""),
                                label       = dev.get("name") or dev.get("label") or dev.get("device_type", ""),
                                power_w     = float(dev.get("current_power", 0)),
                        )
                drift_report = self._device_drift.get_report()
                _drift_profiles = getattr(self._device_drift, "_profiles", {})
                from .energy_manager.device_drift import MIN_BASELINE_SAMPLES as _DR_NEEDED
                _drift_trained  = sum(1 for p in _drift_profiles.values() if p.baseline_frozen)
                drift_data = {
                    "any_alert":     drift_report.any_alert,
                    "any_warning":   drift_report.any_warning,
                    "summary":       drift_report.summary,
                    "trained_count": _drift_trained,
                    "total_count":   len(_drift_profiles),
                    "devices": [
                        {
                            "device_id":      s.device_id,
                            "label":          s.label,
                            "baseline_w":     s.baseline_w,
                            "current_w":      s.current_w,
                            "drift_pct":      s.drift_pct,
                            "level":          s.level,
                            "message":        s.message,
                            "baseline_frozen":_drift_profiles[s.device_id].baseline_frozen if s.device_id in _drift_profiles else True,
                            "samples_total":  _drift_profiles[s.device_id].samples_total if s.device_id in _drift_profiles else 0,
                            "samples_needed": _DR_NEEDED,
                        }
                        for s in drift_report.devices
                    ],
                }
                await self._device_drift.async_maybe_save()

            # ── v2.2: Other-bucket tracker ────────────────────────────────────
            standby_w_now = (
                self._home_baseline.get_standby_w()
                if self._home_baseline and hasattr(self._home_baseline, "get_standby_w")
                else 0.0
            )
            # v4.4.1: gebruik nilm_devices_trusted ipv enriched — de Other-bucket
            # moet alleen vertrouwde devices aftrekken, anders ontstaan
            # negatieve of onrealistische waarden door totaalmetingen.
            other_data = self._nilm_other_tracker.update(
                grid_import_w = max(0.0, data.get("grid_power", 0.0)),
                nilm_devices  = nilm_devices_trusted,
                estimator     = self._power_estimator,
                standby_w     = standby_w_now,
            )

            # ── v2.2: Fault notifier ──────────────────────────────────────────
            if self._fault_notifier and not self.learning_frozen:
                try:
                    self._fault_notifier.check(
                        drift_data    = drift_data,
                        nilm_profiles = getattr(self._nilm, "_profiles", {}),
                        energy_price  = current_price or 0.25,
                    )
                except Exception as _fn_err:
                    _LOGGER.debug("FaultNotifier fout: %s", _fn_err)

            # ── v2.2: Component merge advisor ─────────────────────────────────
            if self._merge_advisor and self._hmm:
                try:
                    self._merge_advisor.check(
                        hmm_sessions = self._hmm.get_active_sessions(),
                        nilm_devices = nilm_devices_enriched,
                    )
                except Exception as _ma_err:
                    _LOGGER.debug("ComponentMergeAdvisor fout: %s", _ma_err)

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
                if not self.learning_frozen:
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
                        # v4.6.533: inverter efficiency (AC vs rated DC)
                        try:
                            if self._inverter_efficiency:
                                _dh = getattr(self, "_decisions_history", None)
                                if _dh:
                                    self._inverter_efficiency.set_decisions_history(_dh)
                                _ac_w  = inv.get("current_w", 0.0)
                                _dc_w  = inv.get("rated_power_w")   # rated als DC-proxy
                                # Echte DC: gebruik estimated_peak als proxy als rated ontbreekt
                                _dc_w  = _dc_w or est_peak
                                if _dc_w and _ac_w > 100:
                                    self._inverter_efficiency.observe(
                                        inverter_id = eid,
                                        dc_power_w  = float(_dc_w),
                                        ac_power_w  = float(_ac_w),
                                    )
                        except Exception as _ie_err:
                            _LOGGER.debug("InverterEfficiency fout: %s", _ie_err)
                        # v4.6.533: integratie latency voor solar
                        try:
                            if self._integration_latency and inv.get("current_w", 0) > 10:
                                _inv_label = inv.get("label", eid)
                                self._integration_latency.record_update(
                                    f"solar_{_inv_label[:20]}"
                                )
                        except Exception:
                            pass
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
                    # v1.16.0: Clipping forecast voor morgen
                    clipping_forecast_list = []
                    if self._pv_forecast:
                        for inv in inverter_data:
                            eid  = inv["entity_id"]
                            lbl  = inv.get("label", eid)
                            # Haal het uurlijkse forecast op voor morgen (24 waarden)
                            tomorrow_fc = self._pv_forecast.get_forecast_tomorrow(eid)
                            fc_w_list   = [hf.forecast_w for hf in tomorrow_fc] if tomorrow_fc else []
                            if fc_w_list:
                                cf = self._clipping_loss.get_clipping_forecast(
                                    inverter_id       = eid,
                                    forecast_hourly_w = fc_w_list,
                                    label             = lbl,
                                )
                                clipping_forecast_list.append(cf)
                    clipping_loss_data["clipping_forecast_tomorrow"] = clipping_forecast_list
                    await self._clipping_loss.async_maybe_save()
                except Exception as _cl_err:
                    _LOGGER.debug("ClippingLoss error: %s", _cl_err)

            # v1.16.0: Schaduwdetectie
            shadow_data: dict = {}
            if self._shadow_detector and self._solar_learner and self._pv_forecast:
                try:
                    hour_utc = datetime.now(timezone.utc).hour
                    for inv in inverter_data:
                        eid    = inv["entity_id"]
                        fp     = {}
                        for p in self._pv_forecast.get_all_profiles():
                            if p["inverter_id"] == eid:
                                fp = p
                                break
                        # Verwacht fractie uit het geleerde uurprofiel van pv_forecast
                        hyf          = fp.get("hourly_yield_fraction", {})
                        expected_frac = float(hyf.get(str(hour_utc), 0.0))
                        peak_wp      = inv.get("estimated_wp") or inv.get("peak_w", 0.0)
                        self._shadow_detector.tick(
                            inverter_id   = eid,
                            label         = inv.get("label", eid),
                            current_w     = inv.get("current_w", 0.0),
                            peak_wp       = float(peak_wp),
                            expected_frac = expected_frac,
                            hour_utc      = hour_utc,
                        )
                    shadow_obj = self._shadow_detector.get_result()
                    _shad_profiles = getattr(self._shadow_detector, "_profiles", {})
                    from .energy_manager.shadow_detector import MIN_SHADOW_DAYS as _SH_NEEDED
                    _shad_trained  = sum(
                        sum(1 for p in hours.values() if p.samples >= _SH_NEEDED)
                        for hours in _shad_profiles.values()
                    )
                    _shad_total    = sum(len(hours) for hours in _shad_profiles.values())
                    shadow_data = {
                        "any_shadow":         shadow_obj.any_shadow,
                        "total_lost_kwh_day": shadow_obj.total_lost_kwh_day,
                        "summary":            shadow_obj.summary,
                        "trained_hours":      _shad_trained,
                        "total_hours":        _shad_total,
                        "progress_pct":       round(min(100, _shad_trained / max(1, _shad_total) * 100)) if _shad_total else 0,
                        "inverters": [
                            {
                                "inverter_id":     r.inverter_id,
                                "label":           r.label,
                                "shadowed_hours":  r.shadowed_hours,
                                "partial_hours":   r.partial_hours,
                                "direction":       r.direction,
                                "severity":        r.severity,
                                "lost_kwh_day_est":r.lost_kwh_day_est,
                                "advice":          r.advice,
                            }
                            for r in shadow_obj.inverters
                        ],
                    }
                    await self._shadow_detector.async_maybe_save()
                except Exception as _sd_err:
                    _LOGGER.debug("ShadowDetector error: %s", _sd_err)

            # v1.12.0: Verbruik categorieën
            categories_data: dict = {}
            if self._categories:
                try:
                    standby_w = float((data or {}).get("standby_w", 0.0))
                    self._categories.tick(
                        nilm_devices  = nilm_devices_enriched,
                        standby_w     = standby_w,
                        grid_import_w = float((data or {}).get("import_power", 0.0)),
                        battery_w     = self._last_battery_w,
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

            # v1.20: Virtuele stroommeter per kamer
            room_meter_data: dict = {}
            try:
                if hasattr(self, "_room_meter") and self._room_meter:
                    _rooms = await self._room_meter.async_update(
                        nilm_devices = nilm_devices_enriched,
                        interval_s   = 10.0,
                    )
                    _total_w = self._calc_house_load(
                        float(data.get("solar_power", 0.0) or 0.0),
                        float(data.get("grid_power", 0.0) or 0.0),
                        getattr(self, "_last_battery_w", 0.0),
                    )
                    room_meter_data = {
                        "overview": self._room_meter.get_overview(_total_w),
                        "rooms":    {name: r.to_dict() for name, r in _rooms.items()},
                    }
            except Exception as _room_err:
                _LOGGER.debug("RoomMeter error: %s", _room_err)

            # v1.20: Goedkope uren schakelaar planner
            cheap_switch_data: dict = {}
            try:
                if hasattr(self, "_cheap_switch_scheduler") and self._cheap_switch_scheduler:
                    _cs_price = self._enrich_price_info(price_info) if price_info else {}
                    _cs_actions = await self._cheap_switch_scheduler.async_evaluate(_cs_price)
                    _cs_status  = self._cheap_switch_scheduler.get_status(_cs_price)
                    cheap_switch_data = {
                        "switches": _cs_status,
                        "actions":  _cs_actions,
                        "count":    len(_cs_status),
                    }
                    # v4.5.11: log elke goedkoop-schakelaar actie
                    for _csa in (_cs_actions or []):
                        self._log_decision(
                            "cheap_switch",
                            f"💡 {_csa.get('entity_id','?')}: {_csa.get('action','?')} — {_csa.get('reason','')}",
                            payload={
                                "entity_id":    _csa.get("entity_id"),
                                "action":       _csa.get("action"),
                                "reason":       _csa.get("reason"),
                                "window_hours": _csa.get("window_hours"),
                                "start_hour":   _csa.get("start_hour"),
                                "price_eur_kwh": round(current_price or 0, 5),
                                "all_in_eur_kwh": ((_cs_price or {}).get("current_all_in") or None),
                            }
                        )
                    # Log ook de schakelaar-statussen (pending/skipped) voor volledigheid
                    for _css in (_cs_status or []):
                        if _css.get("state") not in ("on", "triggered"):
                            continue  # alleen actieve/triggered zijn interessant
                        self._log_decision(
                            "cheap_switch_status",
                            f"💡 {_css.get('entity_id','?')} status: {_css.get('state','?')}",
                            payload={**_css, "price_eur_kwh": round(current_price or 0, 5)}
                        )
            except Exception as _cs_err:
                _LOGGER.debug("CheapSwitch error: %s", _cs_err)

            # v4.6.217: NILM Load Shifter
            nilm_shift_data: dict = {}
            try:
                if hasattr(self, "_nilm_load_shifter") and self._nilm_load_shifter and self._nilm_load_shifting_enabled:
                    _shift_price = self._enrich_price_info(price_info) if price_info else {}
                    _shift_devices = nilm_devices_enriched if 'nilm_devices_enriched' in dir() else []
                    _shift_actions = await self._nilm_load_shifter.async_evaluate(
                        _shift_devices, _shift_price
                    )
                    _shift_status = self._nilm_load_shifter.get_status()
                    nilm_shift_data = {**_shift_status, "actions": _shift_actions}
                    for _sa in (_shift_actions or []):
                        self._log_decision(
                            "nilm_load_shift",
                            f"🔀 {_sa.get('label','?')}: {_sa.get('action','?')} — {_sa.get('reason','')}",
                            payload=_sa,
                        )
            except Exception as _shift_err:
                _LOGGER.warning("CloudEMS NILMLoadShifter fout: %s", _shift_err)

            # v4.2: Slimme uitstelmodus
            smart_delay_data: dict = {}
            try:
                if hasattr(self, "_smart_delay_scheduler") and self._smart_delay_scheduler:
                    _sd_price   = self._enrich_price_info(price_info) if price_info else {}
                    _sd_actions = await self._smart_delay_scheduler.async_evaluate(_sd_price, solar_surplus_w=solar_surplus if 'solar_surplus' in dir() else 0.0)
                    _sd_status  = self._smart_delay_scheduler.get_status(_sd_price)
                    smart_delay_data = {
                        "switches":      _sd_status,
                        "actions":       _sd_actions,
                        "count":         len(_sd_status),
                        "pending_count": sum(
                            1 for s in _sd_status
                            if s.get("delay_state") in ("detected", "intercepted")
                        ),
                    }
                    # v4.5.11: log elke smart-delay actie EN intercepted apparaten
                    for _sda in (_sd_actions or []):
                        self._log_decision(
                            "smart_delay",
                            f"⏱️ {_sda.get('entity_id','?')}: {_sda.get('action','?')} — {_sda.get('reason','')}",
                            payload={
                                "entity_id":      _sda.get("entity_id"),
                                "action":         _sda.get("action"),
                                "reason":         _sda.get("reason"),
                                "delay_until":    _sda.get("delay_until"),
                                "price_eur_kwh":  round(current_price or 0, 5),
                                "all_in_eur_kwh": ((_sd_price or {}).get("current_all_in") or None),
                            }
                        )
                    for _sds in (_sd_status or []):
                        if _sds.get("delay_state") in ("detected", "intercepted"):
                            self._log_decision(
                                "smart_delay_intercept",
                                f"⏱️ {_sds.get('entity_id','?')} onderschept — wacht op goedkoper uur",
                                payload={**_sds, "price_eur_kwh": round(current_price or 0, 5)}
                            )
            except Exception as _sd_err:
                _LOGGER.debug("SmartDelay error: %s", _sd_err)
            battery_schedule = {}
            cfg = self._config  # nodig voor battery_scheduler en zonneplan blokken hieronder

            # Effectieve batterijcapaciteit: geconfigureerd heeft voorrang, anders geleerde waarde
            # Wordt gebruikt door alle sub-modules zodat slijtagekosten altijd kloppen
            _eff_bat_cap: float = float(cfg.get("battery_capacity_kwh", 0) or 0)
            if _eff_bat_cap <= 0:
                try:
                    _bsl_ref_early = getattr(self, "_battery_soc_learner", None)
                    _bat_eid_early = None
                    for _b in (cfg.get("batteries") or []):
                        _bat_eid_early = _b.get("battery_soc_entity") or _b.get("soc_entity")
                        if _bat_eid_early:
                            break
                    if _bsl_ref_early and _bat_eid_early:
                        _diag_early = _bsl_ref_early.get_diagnostics(_bat_eid_early)
                        _eff_bat_cap = float(_diag_early.get("est_capacity_kwh") or 10.0)
                except Exception as _exc_ignored:
                    _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)
            if _eff_bat_cap <= 0:
                _eff_bat_cap = 10.0
            if self._battery_scheduler:
                # v1.18.1: pass soh_pct voor slijtage-bewust laden
                _soh = (
                    self._battery_degradation.update.__self__.state.soh_pct
                    if self._battery_degradation and hasattr(self._battery_degradation, '_state')
                    else None
                )
                _soh = getattr(getattr(self, '_battery_degradation', None), '_state', None)
                _soh_pct = getattr(_soh, 'soh_pct', None)

                # v1.20: build seasonal parameters
                from .energy_manager.seasonal_strategy import build_seasonal_parameters
                _pv_avg_14d_w = None
                _pv_peak_w    = None
                if self._solar_learner:
                    _all_profiles = self._solar_learner.get_all_profiles()
                    if _all_profiles:
                        _pv_peak_w    = sum(p.peak_power_w for p in _all_profiles if p.peak_power_w)
                        _pv_peak_7d   = sum(p.peak_power_w_7d for p in _all_profiles if p.peak_power_w_7d)
                        _pv_avg_14d_w = _pv_peak_7d  # best proxy without 14d rolling average

                _season_override = cfg.get("battery_season_override", None)
                _seasonal_params = build_seasonal_parameters(
                    latitude_deg          = self.hass.config.latitude or 52.1,
                    pv_avg_14d_w          = _pv_avg_14d_w,
                    pv_peak_w             = _pv_peak_w,
                    pv_forecast_today_kwh = pv_forecast_kwh,
                    battery_capacity_kwh  = _eff_bat_cap,
                    battery_max_charge_w  = float(cfg.get("battery_max_charge_w", 3000.0)),
                    pv_forecast_hourly    = pv_forecast_hourly,
                    override              = _season_override,
                )

                battery_schedule = await self._battery_scheduler.async_evaluate(
                    price_info         = price_info,
                    solar_surplus_w    = solar_surplus,
                    soh_pct            = _soh_pct,
                    pv_forecast_hourly = pv_forecast_hourly,
                    seasonal_params    = _seasonal_params,
                )
                # v4.5.11: log battery scheduler beslissing
                if battery_schedule:
                    self._log_decision(
                        "battery_scheduler",
                        f"📅 EPEX scheduler: {battery_schedule.get('mode','?')} — "
                        f"goedkoopste uren: {battery_schedule.get('cheap_hours',[])}",
                        payload={
                            "mode":              battery_schedule.get("mode"),
                            "action":            battery_schedule.get("action"),
                            "reason":            battery_schedule.get("reason"),
                            "cheap_hours":       battery_schedule.get("cheap_hours", []),
                            "expensive_hours":   battery_schedule.get("expensive_hours", []),
                            "charge_from_grid":  battery_schedule.get("charge_from_grid"),
                            "discharge_to_home": battery_schedule.get("discharge_to_home"),
                            "target_soc_pct":    battery_schedule.get("target_soc_pct"),
                            "soh_pct":           _soh_pct,
                            "solar_surplus_w":   round(solar_surplus, 1),
                            "pv_forecast_kwh":   round(pv_forecast_kwh or 0, 2),
                            "season":            getattr(_seasonal_params, "season", None),
                            "season_min_soc":    getattr(_seasonal_params, "min_soc_pct", None),
                            "season_target_soc": getattr(_seasonal_params, "target_soc_pct", None),
                        }
                    )

            # ── v4.0.2: BatteryDecisionEngine ────────────────────────────────
            _bde_result  = None
            _bde_explain = []
            try:
                from .energy_manager.battery_decision_engine import DecisionContext
                _zp_raw = {}
                _zp_br  = getattr(self, "_zonneplan_bridge", None)
                if _zp_br and _zp_br._last_state:
                    _zp_raw = _zp_br._last_state.raw
                _concurrent_w = 0.0
                # v4.0.3: correct attribuut is self._nilm (was _nilm_detector)
                _pl = getattr(self._nilm, "_power_learner", None)
                if _pl:
                    _concurrent_w = _pl.get_concurrent_load_w("L1")

                # v4.0.6: Budget → BDE zuinige modus
                _budget_override_mode = None
                try:
                    _eb = energy_budget_data if 'energy_budget_data' in dir() else {}
                    _eb_status = (_eb or {}).get("overall_status", "op_schema")
                    if _eb_status == "overschrijding":
                        # Budget overschreden: BDE mag minder laden (verhoog drempel)
                        _budget_override_mode = "conservative"
                    elif _eb_status == "attentie":
                        _budget_override_mode = "cautious"
                except Exception: pass

                # Off-peak detectie (gebruik price_hour_history)
                try:
                    import datetime as _dt_mod
                    _op_status = self._off_peak_detector.analyze(
                        self._price_hour_history,
                        current_hour=_dt_mod.datetime.now().hour,
                    )
                    self._off_peak_status = self._off_peak_detector.to_dict(_op_status)
                except Exception as _op_err:
                    _LOGGER.debug("OffPeakDetector fout: %s", _op_err)
                    _op_status = None

                # Peak shaving context
                _ps_active    = bool(peak_data.get("active", False)) if peak_data else False
                _ps_limit_w   = float(peak_data.get("limit_w", 0.0)) if peak_data else 0.0
                _grid_imp_w   = max(0.0, data.get("grid_power", 0.0))

                import datetime as _dt
                # v4.5.66: BatterySocLearner — vul ontbrekende BDE-inputs aan via geleerde waarden
                _bsl_diag = {}
                _bsl_ref  = getattr(self, "_battery_soc_learner", None)
                if _bsl_ref is not None:
                    try:
                        # Gebruik de eerste batterij-entity als sleutel
                        _bat_cfgs = self._config.get("battery_configs") or []
                        _bsl_eid  = (_bat_cfgs[0].get("power_sensor") or "") if _bat_cfgs else (
                            self._config.get("battery_sensor", ""))
                        if _bsl_eid:
                            _bsl_diag = _bsl_ref.get_diagnostics(_bsl_eid)
                    except Exception as _exc_ignored:
                        _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

                # Geconfigureerde waarden hebben voorrang; geleerde waarden vullen aan
                _bde_cap   = float(cfg.get("battery_capacity_kwh", 0)) or \
                             (_bsl_diag.get("est_capacity_kwh") or 10.0)
                _bde_chg_w = float(cfg.get("battery_max_charge_w", 0)) or \
                             (_bsl_diag.get("max_charge_w") or 3000.0)
                _bde_dis_w = float(cfg.get("battery_max_discharge_w", 0)) or \
                             (_bsl_diag.get("max_discharge_w") or 3000.0)

                # SOC: als batt_soc nog None is, gebruik de inferred waarde uit learner
                _bde_soc = batt_soc
                if _bde_soc is None and _bsl_diag.get("inferred_soc_pct") is not None:
                    _bde_soc = _bsl_diag["inferred_soc_pct"]
                    _LOGGER.debug(
                        "BDE: batt_soc inferred via BatterySocLearner: %.1f%% "
                        "(conf %.0f%%)",
                        _bde_soc,
                        (_bsl_diag.get("anchor_age_h") or 99),
                    )

                _bde_ctx = DecisionContext(
                    soc_pct                  = _bde_soc,
                    soh_pct                  = _soh_pct,
                    epex_eur_now             = price_info.get("current_price") if price_info else None,
                    epex_forecast            = price_info.get("prices", []) if price_info else [],
                    tariff_group             = _zp_raw.get("tariff_group", "normal") or "normal",
                    tariff_forecast          = _zp_raw.get("forecast_tariff_groups", []),
                    pv_surplus_w             = solar_surplus,
                    pv_forecast_today_kwh    = pv_forecast_kwh,
                    pv_forecast_tomorrow_kwh = pv_forecast_tomorrow_kwh or 0.0,
                    pv_forecast_hourly       = pv_forecast_hourly or [],
                    concurrent_load_w        = _concurrent_w,
                    battery_capacity_kwh     = _bde_cap,
                    max_charge_w             = _bde_chg_w,
                    max_discharge_w          = _bde_dis_w,
                    current_hour             = _dt.datetime.now().hour,
                    season                   = getattr(_seasonal_params, "season", "transition"),
                    peak_shaving_active      = _ps_active,
                    # v4.0.4: off-peak tarief
                    off_peak_active          = bool(_op_status and _op_status.is_off_peak_now) if '_op_status' in dir() else False,
                    grid_import_w            = _grid_imp_w,
                    grid_peak_limit_w        = _ps_limit_w,
                    # v4.6.416: energy demand — verwacht verbruik rest van de dag
                    expected_remaining_kwh   = float((self.data or {}).get("energy_demand", {}).get("device_total_kwh", 0.0)),
                    system_demand_kwh        = float((self.data or {}).get("energy_demand", {}).get("system_total_kwh", 0.0)),
                    # v4.6.507: saldering — beïnvloedt laad/ontlaad drempels
                    net_metering_pct         = get_net_metering_pct(self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")),
                )
                _bde_result  = self._battery_decision_engine.evaluate(_bde_ctx)
                _bde_explain = self._battery_decision_engine.explain(_bde_ctx)

                # v4.6.533: BDE kwaliteit en arbitrage tracking
                try:
                    import datetime as _dt_bde
                    _cur_price = _bde_ctx.epex_eur_now
                    if _cur_price and _bde_result:
                        if self._bde_quality:
                            _dh = getattr(self, "_decisions_history", None)
                            if _dh:
                                self._bde_quality.set_decisions_history(_dh)
                            if _bde_result.should_execute and _bde_result.action in ("charge", "discharge"):
                                self._bde_quality.record_decision(
                                    action        = _bde_result.action,
                                    price_eur_kwh = _cur_price,
                                    soc_pct       = _bde_ctx.soc_pct or 50.0,
                                )
                            self._bde_quality.tick(_cur_price)
                        if self._arbitrage_quality:
                            _dh = getattr(self, "_decisions_history", None)
                            if _dh:
                                self._arbitrage_quality.set_decisions_history(_dh)
                            _bde_action_str = (
                                _bde_result.action
                                if _bde_result.should_execute else None
                            )
                            self._arbitrage_quality.tick(
                                hour          = _dt_bde.datetime.now().hour,
                                price_eur_kwh = _cur_price,
                                bde_action    = _bde_action_str,
                            )
                        if self._tariff_consistency:
                            _dh = getattr(self, "_decisions_history", None)
                            if _dh:
                                self._tariff_consistency.set_decisions_history(_dh)
                            self._tariff_consistency.observe(
                                cloudems_price_eur_kwh = _cur_price,
                                hour = _dt_bde.datetime.now().hour,
                            )
                except Exception as _bq_err:
                    _LOGGER.debug("BDE quality/arbitrage fout: %s", _bq_err)

                # v4.5.11: log elk BDE resultaat — ook idle — want juist de NIET-uitgevoerde
                # beslissingen zijn interessant om achteraf te beoordelen.
                if _bde_result:
                    self._log_decision(
                        "battery_bde",
                        f"🔋 BDE: {_bde_result.action} (bron: {_bde_result.source}, "
                        f"conf: {_bde_result.confidence:.0%}) — {_bde_result.reason}",
                        payload={
                            "action":              _bde_result.action,
                            "source":              _bde_result.source,
                            "confidence":          round(_bde_result.confidence, 3),
                            "reason":              _bde_result.reason,
                            "should_execute":      _bde_result.should_execute,
                            "is_charging":         _bde_result.is_charging,
                            "is_discharging":      _bde_result.is_discharging,
                            "soc_pct":             batt_soc,
                            "soh_pct":             _soh_pct,
                            "epex_eur_kwh":        _bde_ctx.epex_eur_now,
                            "tariff_group":        _bde_ctx.tariff_group,
                            "pv_surplus_w":        round(solar_surplus, 1),
                            "pv_forecast_kwh":     round(pv_forecast_kwh or 0, 2),
                            "peak_shaving_active": _ps_active,
                            "off_peak_active":     _bde_ctx.off_peak_active,
                            "budget_override":     _budget_override_mode,
                            "season":              _bde_ctx.season,
                            "explain":             _bde_explain[:5],  # max 5 regels
                            "zonneplan_tariff":    _bde_ctx.tariff_group,
                        }
                    )

                # v1.32: pas confidence aan op basis van 24-uurs gewicht
                if _bde_result and self._bde_feedback:
                    try:
                        from datetime import datetime as _bdt
                        _hour_now = _bdt.now().hour
                        _hw = self._bde_feedback.get_weight_for_hour(
                            _bde_result.source, _hour_now
                        )
                        # Gewogen confidence: clamp 0.30–1.0
                        _bde_result.confidence = round(
                            max(0.30, min(1.0, _bde_result.confidence * _hw)), 3
                        )
                    except Exception as _exc_ignored:
                        _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

                # v4.0.4: feedback loop — registreer beslissing
                if _bde_result:
                    try:
                        self._bde_feedback.record(
                            action      = _bde_result.action,
                            source      = _bde_result.source,
                            confidence  = _bde_result.confidence,
                            timestamp   = __import__("time").time(),
                            epex_price  = ctx.epex_eur_now if '_bde_ctx' in dir() else None,
                        )
                    except Exception as _fb_err:
                        _LOGGER.debug("BDE feedback record fout: %s", _fb_err)

                # v4.6.498: Decision Outcome Learner — registreer batterijbeslissing
                if _bde_result and _bde_result.should_execute:
                    try:
                        from .energy_manager.decision_outcome_learner import build_context_bucket
                        _dol_kwh   = (_bde_ctx.battery_capacity_kwh * 0.5) if _bde_ctx else 5.0
                        _dol_soc   = _bde_ctx.soc_pct if _bde_ctx else None
                        _dol_price = _bde_ctx.epex_eur_now if _bde_ctx else 0.0
                        _dol_avg   = float((self.data or {}).get("avg_price_today", 0) or 0)
                        _dol_surp  = solar_surplus if 'solar_surplus' in dir() else 0.0
                        _dol_bucket = build_context_bucket(
                            "battery", _dol_soc, _dol_price or 0.0, _dol_avg, _dol_surp
                        )
                        _dol_alt = "hold"
                        if _bde_result.action == "charge":
                            _dol_alt = "hold"
                        elif _bde_result.action == "discharge":
                            _dol_alt = "hold"
                        elif _bde_result.action == "hold":
                            _dol_alt = "charge" if _dol_price < _dol_avg else "discharge"
                        self._decision_learner.record_decision(
                            component      = "battery",
                            action         = _bde_result.action,
                            alternative    = _dol_alt,
                            context_bucket = _dol_bucket,
                            price_eur_kwh  = _dol_price or 0.0,
                            energy_kwh     = _dol_kwh,
                        )
                    except Exception as _dol_rec_err:
                        _LOGGER.debug("DOL record fout: %s", _dol_rec_err)

                    # v4.6.533: savings attribution voor batterijcyclus
                    try:
                        if self._savings_attribution and _bde_ctx and _bde_ctx.epex_eur_now:
                            _feedin = float((self.data or {}).get("feedin_price", 0) or 0)
                            if _bde_result.action == "discharge" and _feedin > 0:
                                _cycle_kwh = (_bde_ctx.battery_capacity_kwh or 10.0) * 0.05
                                _charge_p  = float((self.data or {}).get("avg_charge_price", 0) or _bde_ctx.epex_eur_now * 0.7)
                                _saved = self._savings_attribution.record_battery_cycle(
                                    charge_price_eur_kwh    = _charge_p,
                                    discharge_price_eur_kwh = _bde_ctx.epex_eur_now,
                                    energy_kwh              = _cycle_kwh,
                                )
                                _LOGGER.debug("SavingsAttribution: batterij cyclus €%.4f", _saved)
                    except Exception as _sa_err:
                        _LOGGER.debug("SavingsAttribution battery fout: %s", _sa_err)

                # Uitvoering: stuur commando naar Zonneplan als confidence >= 0.75
                if _bde_result and _bde_result.should_execute and _zp_br:
                    try:
                        if _bde_result.is_charging:
                            await _zp_br.async_set_mode("self_consumption")
                        elif _bde_result.is_discharging:
                            await _zp_br.async_set_mode("home_optimization")
                        _LOGGER.debug(
                            "BDE uitvoering: %s via Zonneplan (bron: %s, conf: %.0f%%)",
                            _bde_result.action, _bde_result.source, _bde_result.confidence * 100,
                        )
                    except Exception as _bde_exec_err:
                        _LOGGER.debug("BDE uitvoering mislukt: %s", _bde_exec_err)

            except Exception as _bde_err:
                _LOGGER.debug("CloudEMS BatteryDecisionEngine fout: %s", _bde_err)

            # ── v4.0.1: ExportLimitMonitor — gebruikt echte dagtracker ──────
            export_limit_data: dict = {}
            try:
                # Real-time update vandaag (geen Store-schrijfactie)
                _exp_w = data.get("export_power", 0.0)
                if _exp_w > 0:
                    # Schat kWh-vandaag: power × uur van de dag als proxy
                    from datetime import datetime as _dt_cls
                    _hour_frac = _dt_cls.now().hour + _dt_cls.now().minute / 60.0
                    _rt_kwh = (_exp_w / 1000.0) * _hour_frac * 0.6
                    self._export_tracker.record_today_realtime(_rt_kwh)

                _elm_result = self._export_monitor.calculate(
                    tracker        = self._export_tracker,
                    import_tariff  = float(self._config.get("energy_tariff_import_eur_kwh") or 0.28),
                    fallback_export_w = _exp_w,
                )
                export_limit_data = self._export_monitor.to_sensor_dict(_elm_result)
            except Exception as _elm_err:
                _LOGGER.debug("CloudEMS ExportLimitMonitor fout: %s", _elm_err)


            # Draait automatisch elke coordinator-cyclus als de gebruiker
            # zonneplan_auto_forecast heeft ingeschakeld. Geeft alle beschikbare
            # PV-signalen mee zodat decide_action_v3() optimale beslissingen neemt.
            # v4.6.271: Altijd provider.read_state() aanroepen zodat _last_state
            # nooit stale wordt — fix voor battery freeze na reload (issue #27).
            # Rootcause: decide_action_v3() leest self._last_state maar die werd
            # alleen bijgewerkt als battery_soc_entity None teruggaf (fallback-pad).
            # Gevolg: _last_state.active_mode werd stale → idempotentie-check blokkeerde
            # alle verdere sturing → batterij "bevriest" na herstart integratie.
            _zp_provider = getattr(self, "_zonneplan_bridge", None)
            if _zp_provider is not None and getattr(_zp_provider, "is_available", False):
                _zp_prev_mode = getattr(_zp_provider, "_last_state", None)
                _zp_prev_mode = _zp_prev_mode.active_mode if _zp_prev_mode else None
                _zp_provider.read_state()
                _zp_new_mode = _zp_provider._last_state.active_mode
                if _zp_prev_mode != _zp_new_mode:
                    _LOGGER.info(
                        "CloudEMS ZonneplanProvider: mode gewijzigd %s → %s (state refresh)",
                        _zp_prev_mode, _zp_new_mode,
                    )
            if (
                _zp_provider is not None
                and getattr(_zp_provider, "is_available", False)
                and cfg.get("zonneplan_auto_forecast", False)
            ):
                _zp_soh = _soh_pct if self._battery_scheduler else None
                _zp_cap = _eff_bat_cap
                _zp_net_metering = get_net_metering_pct(cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL"))
                try:
                    # Geef all-in prijsinfo door (incl. energiebelasting, BTW, opslag)
                    if price_info:
                        _zp_provider.update_price_info(price_info)
                    # Geef externe context door: ML-huisverbruik, congestie, export-limiet, EV
                    _ctx_ml_w   = ml_forecast_data.get("next_hour_kwh", 0.0) * 1000 if ml_forecast_data else 0.0
                    _ctx_cong   = congestion_data.get("active", False) if locals().get("congestion_data") else False
                    _ctx_exp_lim= export_limit_data.get("limit_w", 0.0) if locals().get("export_limit_data") else 0.0
                    _ctx_ev_w   = abs(data.get("ev_power", 0.0) or 0.0)
                    _zp_provider.update_context(
                        house_load_next_h_w = _ctx_ml_w,
                        congestion_active   = _ctx_cong,
                        export_limit_w      = _ctx_exp_lim,
                        ev_charging_w       = _ctx_ev_w,
                    )
                    _zp_result = await _zp_provider.async_apply_forecast_decision_v3(
                        solar_now_w             = data.get("solar_power", 0.0) or 0.0,
                        solar_surplus_w         = solar_surplus,
                        pv_forecast_today_kwh   = pv_forecast_kwh or 0.0,
                        pv_forecast_tomorrow_kwh= pv_forecast_tomorrow_kwh or 0.0,
                        pv_forecast_hourly      = pv_forecast_hourly,
                        battery_capacity_kwh    = _zp_cap,
                        soh_pct                 = _zp_soh or 100.0,
                        net_metering_pct        = _zp_net_metering,
                    )
                    self._log_decision(
                        "zonneplan_auto",
                        f"🔋 Zonneplan v3: {_zp_result.action.value} "
                        f"(conf {_zp_result.confidence:.0%}) — "
                        f"{_zp_result.reasons[0] if _zp_result.reasons else ''}",
                        payload={
                            "action":              _zp_result.action.value if hasattr(_zp_result.action, "value") else str(_zp_result.action),
                            "confidence":          round(_zp_result.confidence, 3),
                            "reasons":             _zp_result.reasons,
                            "human_reason":        getattr(_zp_result, "human_reason", ""),
                            "net_metering_pct":    round(_zp_net_metering * 100),
                            "executed":            getattr(_zp_result, "executed", None),
                            "charge_w":            getattr(_zp_result, "charge_w", None),
                            "discharge_w":         getattr(_zp_result, "discharge_w", None),
                            "pv_forecast_kwh":     round(pv_forecast_kwh or 0, 2),
                            "pv_forecast_tomorrow_kwh": round(pv_forecast_tomorrow_kwh or 0, 2),
                            "soc_pct":             batt_soc,
                            "solar_surplus_w":     round(solar_surplus, 1),
                            "battery_capacity_kwh": _eff_bat_cap,
                            "via": "with_scheduler",
                        }
                    )
                    # Schrijf human_reason terug naar battery_schedule zodat sensor het toont
                    _hr = getattr(_zp_result, "human_reason", "")
                    if _hr:
                        battery_schedule["human_reason"] = _hr
                except Exception as _zp_err:
                    _LOGGER.warning("ZonneplanProvider auto-forecast fout: %s", _zp_err)

            # ── ZP auto-forecast als battery_scheduler UIT staat ──────────────
            # Zelfde logica als hierboven maar buiten de scheduler-guard,
            # zodat Zonneplan-gebruikers zonder EPEX-scheduler ook profiteren.
            elif (
                not self._battery_scheduler
                and getattr(self, "_zonneplan_bridge", None) is not None
                and getattr(self._zonneplan_bridge, "is_available", False)
                and cfg.get("zonneplan_auto_forecast", False)
            ):
                _zp_cap = _eff_bat_cap
                _zp_net_metering = get_net_metering_pct(cfg.get(CONF_ENERGY_PRICES_COUNTRY, "NL"))
                try:
                    if price_info:
                        self._zonneplan_bridge.update_price_info(price_info)
                    # Injecteer geleerde capaciteit zodat BatteryCycleEconomics altijd klopt
                    if _eff_bat_cap != float(cfg.get("battery_capacity_kwh", 0) or 0):
                        self._zonneplan_bridge.update_config({
                            **cfg,
                            "battery_capacity_kwh": _eff_bat_cap,
                        })
                    _ctx_ml_w   = ml_forecast_data.get("next_hour_kwh", 0.0) * 1000 if ml_forecast_data else 0.0
                    _ctx_cong   = congestion_data.get("active", False) if locals().get("congestion_data") else False
                    _ctx_exp_lim= export_limit_data.get("limit_w", 0.0) if locals().get("export_limit_data") else 0.0
                    _ctx_ev_w   = abs(data.get("ev_power", 0.0) or 0.0)
                    self._zonneplan_bridge.update_context(
                        house_load_next_h_w = _ctx_ml_w,
                        congestion_active   = _ctx_cong,
                        export_limit_w      = _ctx_exp_lim,
                        ev_charging_w       = _ctx_ev_w,
                    )
                    _zp_result = await self._zonneplan_bridge.async_apply_forecast_decision_v3(
                        solar_now_w             = data.get("solar_power", 0.0) or 0.0,
                        solar_surplus_w         = solar_surplus,
                        pv_forecast_today_kwh   = pv_forecast_kwh or 0.0,
                        pv_forecast_tomorrow_kwh= pv_forecast_tomorrow_kwh or 0.0,
                        pv_forecast_hourly      = pv_forecast_hourly,
                        battery_capacity_kwh    = _zp_cap,
                        soh_pct                 = 100.0,
                        net_metering_pct        = _zp_net_metering,
                    )
                    self._log_decision(
                        "zonneplan_auto",
                        f"🔋 Zonneplan v3 (standalone): {_zp_result.action.value} "
                        f"— {_zp_result.reasons[0] if _zp_result.reasons else ''}",
                        payload={
                            "action":              _zp_result.action.value if hasattr(_zp_result.action, "value") else str(_zp_result.action),
                            "confidence":          round(_zp_result.confidence, 3),
                            "reasons":             _zp_result.reasons,
                            "human_reason":        getattr(_zp_result, "human_reason", ""),
                            "net_metering_pct":    round(_zp_net_metering * 100),
                            "executed":            getattr(_zp_result, "executed", None),
                            "charge_w":            getattr(_zp_result, "charge_w", None),
                            "discharge_w":         getattr(_zp_result, "discharge_w", None),
                            "pv_forecast_kwh":     round(pv_forecast_kwh or 0, 2),
                            "pv_forecast_tomorrow_kwh": round(pv_forecast_tomorrow_kwh or 0, 2),
                            "soc_pct":             batt_soc,
                            "solar_surplus_w":     round(solar_surplus, 1),
                            "battery_capacity_kwh": _eff_bat_cap,
                            "via": "standalone",
                        }
                    )
                    # Schrijf human_reason terug naar battery_schedule zodat sensor het toont
                    _hr = getattr(_zp_result, "human_reason", "")
                    if _hr:
                        battery_schedule["human_reason"] = _hr
                except Exception as _zp_err:
                    _LOGGER.warning("ZonneplanProvider standalone auto-forecast fout: %s", _zp_err)


            congestion_data: dict = {}
            if self._congestion_detector:
                grid_import_w   = max(0.0, data.get("grid_power", 0.0))
                congestion_price = price_info.get("current", 0.0) if price_info else 0.0
                cong_result     = await self._congestion_detector.async_evaluate(
                    grid_import_w  = grid_import_w,
                    price_eur_kwh  = congestion_price,
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
                # v4.5.11: log altijd congestie-status (actief of niet)
                self._log_decision(
                    "congestion",
                    f"⚡ Netcongestie: {cong_result.utilisation_pct:.0f}% benutting"
                    + (f" — {len(cong_result.actions)} acties" if cong_result.congestion_active else " — geen congestie"),
                    payload={
                        "active":           cong_result.congestion_active,
                        "import_w":         round(cong_result.import_w, 1),
                        "threshold_w":      cong_result.threshold_w,
                        "utilisation_pct":  round(cong_result.utilisation_pct, 1),
                        "actions":          cong_result.actions,
                        "today_events":     cong_result.today_events,
                        "month_events":     cong_result.month_events,
                        "peak_today_w":     round(cong_result.peak_today_w, 1),
                    }
                )

            # v4.0.5: Tariefwijziging observe
            try:
                _actual_p = current_price or 0.0
                _epex_p   = (price_info or {}).get("epex_raw") or (price_info or {}).get("epex_now") or 0.0
                if _actual_p > 0 and _epex_p > 0:
                    self._tariff_detector.observe(_actual_p, _epex_p)
                    _tc = self._tariff_detector.analyze()
                    self._tariff_change = _tc.to_dict()
                    if _tc.change_detected and not self.hass.states.get("persistent_notification.cloudems_tariff_change"):
                        # v4.5.11: log tariefwijziging als decision voor terugkijken
                        self._log_decision(
                            "tariff_change",
                            f"💰 Tariefwijziging gedetecteerd: {_tc.tip[:80] if _tc.tip else ''}",
                            payload={
                                "change_detected": _tc.change_detected,
                                "tip":             _tc.tip,
                                "old_markup":      getattr(_tc, "old_markup", None),
                                "new_markup":      getattr(_tc, "new_markup", None),
                                "epex_price":      round(_epex_p, 5),
                                "actual_price":    round(_actual_p, 5),
                            }
                        )
                        self.hass.components.persistent_notification.async_create(
                            message=_tc.tip,
                            title="💰 CloudEMS — Tariefwijziging gedetecteerd",
                            notification_id="cloudems_tariff_change",
                        )
            except Exception as _tc_err:
                _LOGGER.debug("TariffChangeDetector fout: %s", _tc_err)

            # v4.5.51 / v4.6.535: Meter topologie — observeer alle bekende power-sensoren
            try:
                if hasattr(self, "_meter_topology"):
                    import time as _time
                    _ts_now = _time.time()

                    # Bouw current_powers dict: begin met bekende waarden
                    _current_powers: dict = {}

                    # Grid / P1
                    _grid_pw = data.get("grid_power") or data.get("net_power_w") or 0.0
                    if _grid_pw:
                        _grid_eid = (self._config.get("p1_sensor_entity")
                                     or self._config.get("grid_power_entity")
                                     or "sensor.cloudems_grid_net_power")
                        _current_powers[_grid_eid] = float(_grid_pw)

                    # Solar
                    _solar_pw = data.get("solar_power", 0.0)
                    if _solar_pw:
                        _solar_eid = self._config.get("pv_power_sensor", "")
                        if _solar_eid:
                            _current_powers[_solar_eid] = float(_solar_pw)

                    # Battery
                    if self._last_battery_w:
                        _bat_eid = self._config.get("battery_power_sensor", "")
                        if _bat_eid:
                            _current_powers[_bat_eid] = float(self._last_battery_w)

                    # v4.6.535: AutoFeeder vult aan met alle bekende sensoren
                    if self._topology_feeder:
                        _nilm_devs = self._nilm.get_devices() if self._nilm else None
                        _current_powers = self._topology_feeder.feed(
                            topology_learner = self._meter_topology,
                            current_powers   = _current_powers,
                            nilm_devices     = _nilm_devs,
                            room_meter       = getattr(self, "_room_meter", None),
                        )
                    else:
                        # Fallback: originele aanpak
                        for _m_eid in self._config.get("extra_meter_entities", []):
                            _m_pw = self._read_state(_m_eid)
                            if _m_pw is not None:
                                self._meter_topology.observe(_m_eid, float(_m_pw), _ts_now)
                                _current_powers[_m_eid] = float(_m_pw)
                        if hasattr(self, "_room_meter") and self._room_meter:
                            for _rm_eid, _rm_pw in getattr(self._room_meter, "_last_power", {}).items():
                                self._meter_topology.observe(_rm_eid, float(_rm_pw), _ts_now)
                                _current_powers[_rm_eid] = float(_rm_pw)

                    # v4.6.535: TopologyConsistencyValidator
                    if self._topology_validator:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._topology_validator.set_decisions_history(_dh)
                        _topo_issues = self._topology_validator.validate(
                            topology_learner = self._meter_topology,
                            current_powers   = _current_powers,
                        )
                        if _topo_issues:
                            _LOGGER.debug(
                                "TopologyConsistency: %d issues gevonden", len(_topo_issues)
                            )

                    # v4.6.535: NILMDoubleCountDetector
                    if self._nilm_double_count and self._nilm:
                        _dh = getattr(self, "_decisions_history", None)
                        if _dh:
                            self._nilm_double_count.set_decisions_history(_dh)
                        _active_devs = [
                            {
                                "entity_id": getattr(d, "entity_id", None),
                                "name":      getattr(d, "name", ""),
                                "power_w":   getattr(d, "power_w", 0),
                                "is_on":     getattr(d, "is_on", False),
                            }
                            for d in self._nilm.get_devices()
                            if getattr(d, "confirmed", False)
                               and getattr(d, "source", "") == "smart_plug"
                        ]
                        self._nilm_double_count.check(
                            topology_learner    = self._meter_topology,
                            active_nilm_devices = _active_devs,
                        )

                    # Periodiek opslaan (elke ~5 min)
                    _topo_cycle = getattr(self, "_topo_save_cycle", 0) + 1
                    self._topo_save_cycle = _topo_cycle
                    if _topo_cycle % 30 == 0:
                        await self._store_topo.async_save(self._meter_topology.dump())

            except Exception as _topo_err:
                _LOGGER.debug("MeterTopology observe fout: %s", _topo_err)

            # v4.0.5: Battery efficiency observe
            try:
                _bat_pw = data.get("battery_power", 0.0) or 0.0
                self._battery_eff.observe(_bat_pw, dt_s=30.0)
                self._battery_eff_status = self._battery_eff.get_status().to_dict()
            except Exception as _be_err:
                _LOGGER.debug("BatteryEfficiency observe fout: %s", _be_err)

            # v1.10: Battery degradation tracking
            degradation_data: dict = {}
            if self._battery_degradation:
                soc_eid  = self._config.get("battery_soc_entity", "")
                soc_val  = self._read_state(soc_eid) if soc_eid else None
                # v4.5.66: Fallback via BatteryProviderRegistry (provider-onafhankelijk)
                if soc_val is None and getattr(self, "_battery_providers", None):
                    for _bp2 in self._battery_providers.available_providers:
                        if _bp2.is_available:
                            _soc2 = _bp2.read_state().soc_pct
                            if _soc2 is not None:
                                soc_val = _soc2
                                break
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

            # v3.9: BatterySavingsTracker — saldering-bewuste besparingssensor
            battery_savings_data: dict = {}
            if self._battery_savings:
                try:
                    _batt_w    = getattr(self, "_last_battery_w", 0.0)
                    _solar_w   = float(data.get("solar_power", 0.0) or 0.0)
                    _grid_w    = float(data.get("grid_power",  0.0) or 0.0)
                    _house_w   = self._calc_house_load(_solar_w, _grid_w, _batt_w)
                    _price_now = float((price_info or {}).get("current_all_in")
                                       or (price_info or {}).get("current") or 0.25)
                    # v4.5.6: battery_savings_tracker verwacht positief=ONTladen, negatief=LADEN
                    # maar _last_battery_w is positief=LADEN, negatief=ONTLADEN → omkeren
                    await self._battery_savings.async_update(
                        battery_power_w = -_batt_w,
                        solar_power_w   = _solar_w,
                        grid_power_w    = _grid_w,
                        house_load_w    = _house_w,
                        current_price   = _price_now,
                        interval_s      = 10.0,
                    )
                    battery_savings_data = self._battery_savings.get_sensor_attributes()
                    if battery_savings_data.get("sessions_today", 0) % 5 == 0:
                        await self._battery_savings.async_save()
                except Exception as _bst_err:
                    _LOGGER.debug("BatterySavingsTracker update fout: %s", _bst_err)


            # v1.23: Geef huidige buitentemperatuur door aan Bayesian classifier
            if self._bayes and self._nilm_bayes_active:
                _tmp_eid = self._config.get("outside_temp_entity", "")
                _tmp_val = self._read_state(_tmp_eid) if _tmp_eid else None
                if _tmp_val is not None:
                    try:
                        self._bayes._last_temp_c = float(_tmp_val)
                    except (TypeError, ValueError):
                        pass

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
                # v4.5.18: provider batteries (e.g. Zonneplan Nexus) have no
                # battery_sensor but ARE configured via battery_configs with
                # battery_type="zonneplan"/"nexus". Treat these as has_battery=True
                # so the "Batterij niet gekoppeld?" hint is suppressed.
                _batt_cfgs      = cfg.get("battery_configs", [])
                _provider_types = {"zonneplan", "nexus", "vpp_flex", "powerplay"}
                _has_provider_battery = any(
                    bc.get("battery_type", "") in _provider_types
                    for bc in _batt_cfgs
                )
                has_battery = bool(cfg.get("battery_sensor", "")) or _has_provider_battery
                # Determine battery_type for logging context
                _battery_type = "none"
                if bool(cfg.get("battery_sensor", "")):
                    _battery_type = "direct"
                elif _has_provider_battery:
                    _provider_name = next(
                        (bc.get("battery_type","") for bc in _batt_cfgs
                         if bc.get("battery_type","") in _provider_types), "provider"
                    )
                    _battery_type = f"provider:{_provider_name}"
                has_curr_l1 = bool(cfg.get("phase_sensors_L1", ""))
                has_volt_l1 = bool(cfg.get("voltage_sensor_l1", ""))
                has_pwr_l1  = bool(cfg.get("power_sensor_l1", ""))
                # v4.5.18: detect DSMR4 (no voltage sensor on P1) — step-patterns
                # on DSMR4 are a known artifact, not a missing battery signal.
                _is_dsmr4 = not has_volt_l1 and bool(cfg.get("p1_sensor", ""))
                hints = self._sensor_hints.update(
                    grid_power_w        = data.get("grid_power", 0.0),
                    has_solar_sensor    = has_solar,
                    has_battery_sensor  = has_battery,
                    has_current_l1      = has_curr_l1,
                    has_voltage_l1      = has_volt_l1,
                    has_power_l1        = has_pwr_l1,
                    battery_type        = _battery_type,
                    is_dsmr4            = _is_dsmr4,
                )
                sensor_hints = self._sensor_hints.get_all_hints()
                # v4.5.11: dedup — log elke hint maximaal 1x per uur (hint_id als sleutel)
                _hint_logged: dict = getattr(self, "_sensor_hint_log_ts", {})
                _hint_now = __import__("time").time()
                for h in hints:
                    _hint_id = getattr(h, "hint_id", h.title)
                    if _hint_now - _hint_logged.get(_hint_id, 0) > 3600:
                        self._log_decision(
                            "sensor_hint",
                            f"💡 {h.title}: {h.message[:80]}…"
                        )
                        _hint_logged[_hint_id] = _hint_now
                self._sensor_hint_log_ts = _hint_logged
                await self._sensor_hints.async_save()

            sanity_data: dict = {}
            # Gebruik de al berekende _last_battery_w (som van alle batterijen + EMA-filter)
            battery_total_w: Optional[float] = getattr(self, "_last_battery_w", None)
            if battery_total_w == 0.0 and not self._config.get("battery_configs") and not self._config.get(CONF_BATTERY_SENSOR, ""):
                battery_total_w = None  # geen batterij geconfigureerd → None voor sanity check
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
            # v4.5.6: EMA diagnostics vervangen door EnergyBalancer diagnostics
            ema_diag: dict = (
                self._energy_balancer.get_diagnostics()
                if self._energy_balancer else {}
            )

            # v1.15.0: Absence / occupancy detection (energy-pattern based)
            occupancy_data: dict = {}
            if self._absence:
                occ = self._absence.update(self._calc_house_load(
                    float(data.get("solar_power", 0.0) or 0.0),
                    float(data.get("grid_power", 0.0) or 0.0),
                    getattr(self, "_last_battery_w", 0.0),
                ))
                occupancy_data = {
                    "state":         occ.state,
                    "confidence":    occ.confidence,
                    "vacation_hours": occ.vacation_hours,
                    "standby_w":     occ.standby_w,
                    "advice":        occ.advice,
                }
                # v1.32: cross-module loop — aanwezigheid → NILM gevoeligheid
                # Als niemand thuis is, verlaag de NILM-gevoeligheid: alleen grote
                # onverwachte verbruikers (> 800W) zijn werkelijk interessant.
                # Dit voorkomt NILM-detecties van standby-fluctuaties die normaal
                # zijn als het huis leeg is (koelkast, netwerk, alarm).
                if self._nilm and occ.confidence >= 0.70:
                    if occ.state in ("away", "vacation"):
                        # Verhoog drempel bij afwezigheid
                        self._nilm._adaptive.set_away_mode(True)
                    else:
                        self._nilm._adaptive.set_away_mode(False)
                # cross-module: standby → BatteryUncertainty baseline_w cache
                if occ.standby_w > 50:
                    self._house_baseline_w = occ.standby_w

            # v3.0: ZonePresenceManager — multi-signal aanwezigheid
            zone_presence_data: dict = {}
            if self._zone_presence:
                try:
                    zone_advies = self._zone_presence.evaluate(self.hass)
                    zone_presence_data = self._zone_presence.get_status()
                    # Combineer met energy-based absence als confidence laag is
                    if zone_advies.confidence < 0.4 and occupancy_data:
                        zone_presence_data["energy_fallback"] = occupancy_data.get("state")
                except Exception as _zp_err:
                    _LOGGER.debug("ZonePresence fout: %s", _zp_err)

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
                # v4.5.118: Preheat advies doorgeven aan SmartClimateManager
                if self._smart_climate and adv.mode != "normal":
                    self._smart_climate.apply_preheat_advice(
                        offset_c = adv.setpoint_offset_c,
                        mode     = adv.mode,
                    )

            # v1.15.0: PV forecast accuracy tracker
            pv_accuracy_data: dict = {}
            if self._pv_accuracy:
                try:
                    solar_w_now = max(0.0, data.get("solar_power", 0.0))
                    # Support both tick() and tick_production() across versions
                    if hasattr(self._pv_accuracy, 'tick_production'):
                        self._pv_accuracy.tick_production(pv_w=solar_w_now)
                    else:
                        self._pv_accuracy.tick(actual_w=solar_w_now)
                    # Day rollover: finalize yesterday and record MAPE
                    from datetime import datetime as _dt_acc
                    today_str = _dt_acc.now().strftime("%Y-%m-%d")
                    if self._acc_date and self._acc_date != today_str and pv_forecast_kwh:
                        try:
                            self._pv_accuracy.finalize_day(forecast_kwh=pv_forecast_kwh)
                        except Exception as _fe:
                            _LOGGER.debug("CloudEMS: pv_accuracy finalize_day failed: %s", _fe)
                    self._acc_date = today_str
                    _acc = self._pv_accuracy.get_data()
                    # v4.6.560: bewaar gisteren uurdata elke cyclus (niet alleen bij dagwisseling)
                    # _pv_yesterday_hourly_kwh is een list[24] — JS verwacht dict {hr: kwh}
                    _yst_list = getattr(self, "_pv_yesterday_hourly_kwh", [0.0] * 24)
                    _yst_kwh = {str(h): round(v, 4) for h, v in enumerate(_yst_list) if v > 0}
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
                        "yesterday_hourly_kwh": _yst_kwh,
                    }
                    await self._pv_accuracy.async_maybe_save()
                except Exception as _pvacc_err:
                    _LOGGER.warning("CloudEMS: pv_accuracy skipped: %s", _pvacc_err)

            # v1.18.1: Dagelijks leerrapport om 20:00
            _now_h = datetime.now(timezone.utc).hour
            _now_day = datetime.now(timezone.utc).day
            if _now_h == 20 and self._notification_engine:
                try:
                    _report = {"orientation_progress": [], "phase_progress": [], "samples_today": 0}
                    if self._solar_learner:
                        for _p in self._solar_learner.get_all_profiles():
                            if self._pv_forecast:
                                _prof = self._pv_forecast._profiles.get(_p.inverter_id)
                                if _prof:
                                    _have = _prof.clear_sky_samples or 0
                                    _need = _prof.orientation_samples_needed or 1800
                                    _ori_pct = min(100, round(_have / _need * 100)) if _need else 0
                                    _report["orientation_progress"].append({
                                        "label": _p.label, "pct": _ori_pct,
                                        "samples": _have, "needed": _need,
                                        "confident": _prof.orientation_confident,
                                    })
                            _report["phase_progress"].append({
                                "label": _p.label, "phase": _p.detected_phase,
                                "certain": _p.phase_certain, "confidence": 100.0 if _p.phase_certain else 0.0,
                            })
                    await self._notification_engine.send_daily_learning_report(_report)
                except Exception as _rep_err:
                    _LOGGER.debug("Leerrapport fout: %s", _rep_err)

            # v1.32: Nachtelijke NILM zelfverbetering — elke nacht om 03:00
            # auto_prune_ghosts() leert van drie autonome signalen (confidence-vloer,
            # duplicate watt-klasse, lange ghost-sessies) zonder gebruikersinteractie.
            if _now_h == 3 and self._nilm:
                try:
                    _prune_result = await self._nilm.auto_prune_ghosts()
                    if _prune_result.get("pruned_total", 0) > 0:
                        _LOGGER.info(
                            "NILM nachtcyclus: %d ghost(s) geleerd en verwijderd "
                            "(FP-geheugen: %d signatures)",
                            _prune_result["pruned_total"],
                            _prune_result["fp_signatures"],
                        )
                except Exception as _prune_err:
                    _LOGGER.debug("NILM nachtcyclus fout: %s", _prune_err)
                # v1.32: nachtcyclus — synchroniseer HomeBaseline met bevestigde NILM-apparaten
                if self._home_baseline and self._nilm:
                    try:
                        _confirmed_standby_w = sum(
                            d.get("current_power", 0) or 0
                            for d in self._nilm.get_devices_for_ha()
                            if d.get("confirmed") and not d.get("is_on", True)
                            and d.get("device_type") in (
                                "fridge", "refrigerator", "freezer",
                                "router", "modem", "alarm", "standby",
                            )
                        )
                        if _confirmed_standby_w > 0 and hasattr(self._home_baseline, "adjust_standby"):
                            self._home_baseline.adjust_standby(_confirmed_standby_w)
                    except Exception as _cs_err:
                        _LOGGER.debug("NILM→baseline sync fout: %s", _cs_err)

                # v1.32: SalderingCalibrator — dagelijkse import/export meting
                if self._saldering_cal:
                    try:
                        from datetime import datetime as _dts
                        _today_str = _dts.now().strftime("%Y-%m-%d")
                        _p1 = self._data or {}
                        _imp_kwh = float(_p1.get("electricity_import_today_kwh") or 0)
                        _exp_kwh = float(_p1.get("electricity_export_today_kwh") or 0)
                        if _exp_kwh > 0.5:
                            self._saldering_cal.record_day(
                                date_str   = _today_str,
                                import_kwh = _imp_kwh,
                                export_kwh = _exp_kwh,
                            )
                            await self._saldering_cal.async_save()
                    except Exception as _scal_err:
                        _LOGGER.debug("SalderingCalibrator dagmeting fout: %s", _scal_err)

                # v1.32: PVAccuracy bias → PVForecast kalibratiefactor
                # De PVAccuracyTracker meet dagelijks hoe ver de forecast afwijkt van
                # de werkelijke productie. Die bias wordt nu teruggedeeld aan PVForecast
                # zodat de volgende dag's voorspelling direct gecorrigeerd start.
                if self._pv_accuracy and self._pv_forecast:
                    try:
                        _acc_data = self._pv_accuracy.get_data()
                        _bias     = getattr(_acc_data, "bias_factor", 1.0) or 1.0
                        _monthly  = getattr(_acc_data, "monthly_bias", {}) or {}
                        from datetime import datetime as _pdt
                        _cur_month = _pdt.now().strftime("%B").lower()
                        _month_bias = _monthly.get(_cur_month, _bias)
                        # Geef per-inverter kalibratie door als calib_factor seed
                        if 0.5 <= _month_bias <= 1.5:
                            for _inv_id, _prof in self._pv_forecast._profiles.items():
                                if _prof._calib_factor is None and _month_bias != 1.0:
                                    _prof._calib_factor = _month_bias
                                    _LOGGER.debug(
                                        "PVForecast: kalibratiefactor omvormer '%s' "
                                        "gezaaid vanuit PVAccuracy bias=%.2f",
                                        _inv_id, _month_bias,
                                    )
                                elif _prof._calib_factor is not None:
                                    # EMA: 90% bestaand, 10% accuracy-bias
                                    _prof._calib_factor = (
                                        0.90 * _prof._calib_factor + 0.10 * _month_bias
                                    )
                    except Exception as _pv_bias_err:
                        _LOGGER.debug("PVAccuracy→PVForecast bias fout: %s", _pv_bias_err)

                # v1.32: Seizoenscalibratie — BoilerController setpoints
                # SeasonalStrategy levert het huidige seizoen. Als het seizoen wisselt
                # en de boiler heeft geen expliciete zomer/winter setpoints, corrigeer
                # automatisch op basis van de gemiddelde buitentemperatuur.
                if self._nilm:
                    try:
                        _outside_t = float((self._data or {}).get("outside_temp_c") or 15.0)
                        _boiler_ctrl = getattr(self, "_boiler_ctrl", None)
                        if _boiler_ctrl and hasattr(_boiler_ctrl, "auto_calibrate_season"):
                            _boiler_ctrl.auto_calibrate_season(_outside_t)
                    except Exception as _bc_err:
                        _LOGGER.debug("Boiler seizoenskalibratie fout: %s", _bc_err)

            # v2.2.2: Maandrapportage — 1e van de maand om 07:00
            if _now_day == 1 and _now_h == 7 and self._monthly_report:
                try:
                    await self._monthly_report.maybe_send(self._data)
                except Exception as _mr_err:
                    _LOGGER.debug("Maandrapport fout: %s", _mr_err)

            # v2.4.19: Mail maandrapport als PDF
            if _now_day == 1 and _now_h == 7 and self._config.get("mail_enabled"):
                try:
                    from .mail import CloudEMSMailer
                    from datetime import datetime as _dt, timezone as _tz
                    import calendar as _cal
                    _mailer = CloudEMSMailer(self.hass, self._config)
                    if _mailer.enabled and self._config.get("mail_monthly_report", True):
                        # Genereer eenvoudige tekst-samenvatting als fallback (PDF later)
                        _prev = _dt.now(_tz.utc).replace(day=1)
                        _month_label = f"{_cal.month_name[_prev.month]} {_prev.year}"
                        _report_data = self._data or {}
                        _summary = (
                            f"CloudEMS Maandrapport — {_month_label}\n\n"
                            f"Totaal verbruik: {_report_data.get('total_kwh_month', 0):.1f} kWh\n"
                            f"Zonne-energie:   {_report_data.get('solar_kwh_month', 0):.1f} kWh\n"
                            f"Kosten:          €{_report_data.get('total_cost_month', 0):.2f}\n"
                            f"Besparing:       €{_report_data.get('solar_saving_month', 0):.2f}\n"
                        )
                        await _mailer.async_send_monthly_report(
                            _summary.encode("utf-8"), _month_label
                        )
                except Exception as _mail_err:
                    _LOGGER.warning("CloudEMS mail maandrapport mislukt: %s", _mail_err)

            # v2.4.0: Dagelijkse samenvatting — elke ochtend om 07:30
            if self._daily_summary:
                try:
                    await self._daily_summary.maybe_send(self._data)
                except Exception as _ds_err:
                    _LOGGER.debug("Dagelijkse samenvatting fout: %s", _ds_err)

            # v4.0.5: Gas predictor — sla dagdata op
            try:
                import datetime as _dt_gas
                _gas_today = (self._data or {}).get("p1_data", {}).get("gas_m3_total")
                _gas_yesterday = getattr(self, "_gas_yesterday_total", 0.0)
                if _gas_today and _gas_yesterday and _gas_today > _gas_yesterday:
                    _gas_day_m3 = round(_gas_today - _gas_yesterday, 3)
                    # Buitentemperatuur ophalen
                    _weather_eid = self._config.get("weather_entity", "weather.forecast_home")
                    _temp_st = self._safe_state(_weather_eid)
                    _temp_c  = float(_temp_st.attributes.get("temperature", 10)) if _temp_st else 10.0
                    self._gas_predictor.record_day(
                        str(_dt_gas.date.today() - _dt_gas.timedelta(days=1)),
                        _gas_day_m3, _temp_c,
                    )
                    await self._gas_predictor.async_save()
                # _gas_today_start: gasstand aan het begin van vandaag (voor dag_m3 berekening)
                _today_key = _dt_gas.date.today().isoformat()
                if not hasattr(self, "_gas_today_date") or self._gas_today_date != _today_key:
                    # Nieuwe dag! Sla de huidige stand op als start van vandaag
                    if _gas_today and _gas_today > 0:
                        self._gas_today_start = _gas_today
                        self._gas_today_date = _today_key
                        _LOGGER.info("CloudEMS: gas dag-start voor %s = %.3f m³", _today_key, _gas_today)
                elif not hasattr(self, "_gas_today_start") and _gas_today and _gas_today > 0:
                    # Eerste keer na herstart — lees middernacht-waarde uit HA recorder
                    _midnight_val = await self._async_read_gas_at_midnight()
                    if _midnight_val and _midnight_val > 0 and _midnight_val <= _gas_today:
                        self._gas_today_start = _midnight_val
                        _LOGGER.info("CloudEMS: gas dag-start (recorder) = %.3f m³ → dag_m3 = %.3f m³",
                                     _midnight_val, _gas_today - _midnight_val)
                    else:
                        # Recorder niet beschikbaar — gebruik huidige als start (dag_m3 = 0 vandaag)
                        self._gas_today_start = _gas_today
                    self._gas_today_date = _today_key
                self._gas_yesterday_total = _gas_today or getattr(self, "_gas_yesterday_total", 0.0)
                # Voorspelling bijwerken
                _weather_eid = self._config.get("weather_entity", "weather.forecast_home")
                _temp_st     = self._safe_state(_weather_eid)
                _temp_tom    = float(_temp_st.attributes.get("temperature", 10)) if _temp_st else 10.0
                _gas_price   = self._read_gas_price()
                self._gas_prediction = self._gas_predictor.predict(_temp_tom, _gas_price).to_dict()
            except Exception as _gp_err:
                _LOGGER.debug("GasPredictor dagcyclus fout: %s", _gp_err)

            # v4.0.5: Tariff detector wekelijks opslaan

            # v4.5.88: Gas DHW hint — detecteer of gas voor warm water gebruikt wordt
            await self._async_check_gas_dhw_hint()
            try:
                import datetime as _dt_tc
                if _dt_tc.date.today().weekday() == 0:  # maandag
                    await self._tariff_detector.async_save()
            except Exception: pass

            # v4.0.5: Battery efficiency dagcyclus afsluiten
            try:
                from datetime import date as _date
                _be_rec = self._battery_eff.close_day(
                    date_str    = str(_date.today()),
                    eur_benefit = self._cost_today_eur or 0.0,
                )
                if _be_rec:
                    await self._battery_eff.async_save()
                    # v4.5.66: ook BatterySocLearner opslaan bij dagsluiting
                    if getattr(self, "_battery_soc_learner", None):
                        await self._battery_soc_learner.async_save()
                    if self._battery_eff.get_status().warn:
                        self.hass.components.persistent_notification.async_create(
                            message=(
                                f"Batterij round-trip efficiëntie is gedaald naar "
                                f"{self._battery_eff_status.get('avg_efficiency_pct', 0):.1f}% "
                                f"(nominaal {self._battery_eff_status.get('nominal_pct', 92):.0f}%). "
                                "Overweeg onderhoud of kalibratie."
                            ),
                            title="🔋 CloudEMS — Batterij-efficiëntie laag",
                            notification_id="cloudems_battery_efficiency_warn",
                        )
            except Exception as _be_day_err:
                _LOGGER.debug("BatteryEfficiency dagcyclus fout: %s", _be_day_err)

            # v4.0.4: TimePatternLearner — periodiek opslaan + anomalie-check
            try:
                _tpl = getattr(self._nilm, "_time_pattern_learner", None)
                if _tpl:
                    # Opslaan (elke dagstart = acceptabele frequentie)
                    await _tpl.async_save()
                    # Anomalie-check op actieve apparaten
                    import time as _time_mod
                    _active_ids = [
                        d.device_id for d in self._nilm.get_devices()
                        if d.is_on and d.confirmed
                    ]
                    _anomalies = _tpl.get_all_anomalous_now(_active_ids, _time_mod.time())
                    for _adev_id in _anomalies:
                        _dev = self._nilm._devices.get(_adev_id)
                        if _dev:
                            _LOGGER.info(
                                "CloudEMS tijdpatroon-anomalie: %s actief op ongewoon tijdstip",
                                _dev.display_name,
                            )
                            _msg = (f"**{_dev.display_name}** is actief op een ongewoon tijdstip. "
                                    "Dit apparaat draait normaal niet op dit moment.")
                            self.hass.components.persistent_notification.async_create(
                                message=_msg,
                                title="☀️ CloudEMS — Apparaat-anomalie",
                                notification_id=f"cloudems_anomaly_{_adev_id}",
                            )
            except Exception as _tpl_err:
                _LOGGER.debug("TimePatternLearner dagcyclus fout: %s", _tpl_err)

            # v4.0.1: ExportDailyTracker — sla gisteren op bij dagstart
            try:
                from datetime import datetime as _dt_cls, timedelta as _td
                _yesterday = (_dt_cls.now() - _td(days=1)).date().isoformat()
                # Gebruik energie-data van P1 / Tibber als beschikbaar,
                # anders schat op basis van gemiddeld vermogen × 24h
                _p1 = self._data.get("p1") or {}
                _tibber = self._data.get("tibber_today") or {}
                _day_export_kwh = (
                    float(_p1.get("electricity_export_today_kwh") or 0)
                    or float(_tibber.get("energy_export_kwh") or 0)
                    or round(float(self._data.get("export_power", 0)) / 1000.0 * 24 * 0.3, 2)
                )
                if _day_export_kwh > 0:
                    await self._export_tracker.record_day(_yesterday, _day_export_kwh)
            except Exception as _et_err:
                _LOGGER.debug("ExportDailyTracker record fout: %s", _et_err)

            # v2.6: Wekelijkse vergelijking — elke maandag om 08:00
            try:
                if not self.learning_frozen:
                    self._weekly_cmp.update(self._data)
                await self._weekly_cmp.maybe_send_weekly(self._data)
                self._data["weekly_comparison"] = self._weekly_cmp.get_comparison()
            except Exception as _wc_err:
                _LOGGER.debug("Wekelijkse vergelijking fout: %s", _wc_err)

            # v2.6: multi-zone klimaatbeheer
            # v4.2.1: gebruik _climate_mgr_override (live schakelaar) ipv config (statisch)
            _climate_active = bool(self._config.get("climate_zones_enabled") or self._config.get("climate_mgr_enabled")) and getattr(self, "_climate_mgr_override", True)
            if _climate_active and hasattr(self, "_zone_climate"):
                try:
                    self._data["zone_climate"] = await self._zone_climate.async_update(self._data)
                except Exception as _zc_err:
                    _LOGGER.debug("Zone klimaat fout: %s", _zc_err)

            # v2.6: Slaapstand detector
            try:
                # v3.9: sync bridge attr → detector (voor RestoreEntity persistentie)
                if self._sleep_detector.enabled != self._sleep_detector_enabled:
                    self._sleep_detector.set_enabled(self._sleep_detector_enabled)
                _sleep_status = await self._sleep_detector.async_update()
                self._data["sleep_detector"] = _sleep_status
                # SleepDetector → AbsenceDetector koppeling
                if self._absence and _sleep_status:
                    _is_sleeping = bool(_sleep_status.get("sleep_active", False))
                    self._absence.set_sleep_mode(_is_sleeping, confidence=0.8 if _is_sleeping else 0.3)
            except Exception as _sl_err:
                _LOGGER.debug("Slaapstand detector fout: %s", _sl_err)

            # v2.6 / v3.0: Capaciteits-piekbewaker
            try:
                _grid_w = float(self._data.get("grid_power", 0) or 0)
                # Bereken uitschakelbare lasten voor load-shedding advies
                _boiler_w = float(
                    (self._boiler_ctrl.get_status()[0].get("power_w") if self._boiler_ctrl and self._boiler_ctrl.get_status() else 0) or 0
                )
                _ev_w = float(self._data.get("ev_charging_power_w", 0) or 0)
                _sheddable_w = _boiler_w + _ev_w
                _peak_status = self._capacity_peak.update(abs(_grid_w), sheddable_loads_w=_sheddable_w) if not self.learning_frozen else self._capacity_peak.get_status()
                self._data["capacity_peak"] = _peak_status
                # Maandreset is nu automatisch in CapacityPeakMonitor v3.0
            except Exception as _cp_err:
                _LOGGER.debug("Capaciteitspiek fout: %s", _cp_err)

            # v2.6: Negatief tarief afvangen
            try:
                _price_now = float((self._data.get("energy_price") or {}).get("current_eur_kwh", 0) or 0)
                await self._neg_tariff.async_check(_price_now, self._data)
            except Exception as _nt_err:
                _LOGGER.debug("Negatief tarief fout: %s", _nt_err)

            # v2.6: Slim wassen verschuiven
            try:
                _price_now = float((self._data.get("energy_price") or {}).get("current_eur_kwh", 0) or 0)
                _forecast  = (self._data.get("energy_price") or {}).get("forecast", [])
                _nilm_devs = self._data.get("nilm_devices", [])
                await self._shift_advisor.async_check(_nilm_devs, _price_now, _forecast)
            except Exception as _sa_err:
                _LOGGER.debug("Verschuif-advisor fout: %s", _sa_err)

            # v2.6: wasbeurt cyclus detector
            try:
                _wash_result = await self._appliance_cycles.async_update(self._data)
                self._data["appliance_cycles"] = _wash_result
            except Exception as _wc_err:
                _LOGGER.debug("WashCycle fout: %s", _wc_err)

            # v4.6.432: Generator / ATS manager
            try:
                if getattr(self, "_generator_mgr", None):
                    _gen_status = self._generator_mgr.update(
                        self._data,
                        self.hass.states.async_all().__class__  # hass states as dict
                        if False else {s.entity_id: s for s in self.hass.states.async_all()},
                    )
                    self._generator_active  = _gen_status.active
                    self._generator_power_w = _gen_status.power_w
                    self._data["generator"] = _gen_status.to_dict()
                    # Notificaties
                    _gen_alerts = await self._generator_mgr.async_handle_notifications(self._data)
                    for _ga in _gen_alerts:
                        _LOGGER.info("Generator alert: %s — %s", _ga["title"], _ga["message"])
                        if _ga.get("persistent"):
                            self.hass.components.persistent_notification.async_create(
                                message=_ga["message"],
                                title=_ga["title"],
                                notification_id=f"cloudems_{_ga['key']}",
                            )
            except Exception as _gen_err:
                _LOGGER.debug("GeneratorManager fout: %s", _gen_err)

            # v4.6.445: Lamp automation engine
            try:
                if getattr(self, "_lamp_auto", None) and self._lamp_auto._enabled:
                    _absence   = (self._data.get("absence_state") or
                                  self._data.get("absence", {}).get("state", "unknown"))
                    _sun_down  = bool(self._data.get("is_night") or
                                      not self._data.get("sun_above_horizon", True))
                    _hour_now  = datetime.now().hour
                    _lc        = getattr(self, "_lamp_circulation", None)
                    _gen_st    = getattr(self, "_generator_active", False)
                    _ups_st    = (self._data.get("generator") or {}).get("ups_active", False)
                    _lamp_auto_result = await self._lamp_auto.async_tick(
                        _absence, _sun_down, _hour_now, _lc,
                        generator_active=_gen_st,
                        ups_active=_ups_st,
                    )
                    self._data["lamp_automation"] = _lamp_auto_result
            except Exception as _la_err:
                _LOGGER.debug("LampAutomation tick fout: %s", _la_err)

            # v4.6.447: Circuit monitor tick
            try:
                if getattr(self, "_circuit_monitor", None):
                    _circuit_result = self._circuit_monitor.update(self._data)
                    self._data["circuit_monitor"] = _circuit_result
                    if _circuit_result.get("alerts"):
                        await self._circuit_monitor.async_notify_alerts(
                            _circuit_result["alerts"]
                        )
            except Exception as _cm_err:
                _LOGGER.debug("CircuitMonitor tick fout: %s", _cm_err)

            # v4.6.450: UPS manager tick
            try:
                if getattr(self, "_ups_manager", None) and self._ups_manager._enabled:
                    _hass_states_ups = {s.entity_id: s for s in self.hass.states.async_all()}
                    _ups_result = await self._ups_manager.async_tick(
                        generator_active=self._generator_active,
                        hass_states=_hass_states_ups,
                    )
                    self._data["ups"] = _ups_result
            except Exception as _ups_err:
                _LOGGER.debug("UPSManager tick fout: %s", _ups_err)

            # v2.6: E-bike (multi-merk)
            try:
                _ebike_result = await self._ebike.async_update(self._data) if getattr(self, "_ebike_enabled", True) else None
                self._data["ebike"] = _ebike_result
            except Exception as _eb_err:
                _LOGGER.debug("EBike fout: %s", _eb_err)

            # v2.6: ERE certificaten
            try:
                _ere_result = await self._ere.async_update(self._data)
                self._data["ere"] = _ere_result
            except Exception as _ere_err:
                _LOGGER.debug("ERE fout: %s", _ere_err)

            # v2.6: smart climate manager
            # v4.2.1: gebruik _climate_mgr_override (live schakelaar) ipv config (statisch)
            try:
                if _climate_active:
                    _climate_result = await self._smart_climate.async_update(self._data)
                    self._data["smart_climate"] = _climate_result
            except Exception as _sc_err:
                _LOGGER.debug("SmartClimate fout: %s", _sc_err)

            # v2.6: altijd alle climate-entiteiten scannen voor dashboard
            try:
                self._data["climate_entities"] = _scan_all_climate_entities(self.hass)
            except Exception as _ce_err:
                _LOGGER.debug("Climate entity scan fout: %s", _ce_err)

            # v2.4.0: LLM naam-suggestie — elke 5 minuten checken (lichtgewicht)
            if _now_h != getattr(self, "_llm_name_last_h", -1) or \
               getattr(self, "_health_cycle_count", 0) % 30 == 0:
                try:
                    await self._async_suggest_device_names()
                    self._llm_name_last_h = _now_h
                except Exception as _llm_err:
                    _LOGGER.debug("LLM naam-suggestie fout: %s", _llm_err)

            # v2.2.2: Installatie-score berekenen (elke 30 min, lichtgewicht)
            if self._install_score:
                try:
                    _score_result = self._install_score.calculate()
                    self._data["installation_score"] = _score_result.to_dict()
                    # Trend-waarschuwing als score significant daalt
                    _trend_alert = self._install_score.get_trend_alert()
                    if _trend_alert:
                        _LOGGER.warning("CloudEMS installatie-score trend: %s", _trend_alert)
                        self._data["installation_score"]["trend_alert"] = _trend_alert
                        # v4.5.11: ook naar high log
                        _bk_trend = getattr(self, "_learning_backup", None)
                        if _bk_trend:
                            import asyncio as _aio_t
                            _aio_t.ensure_future(_bk_trend.async_log_high(
                                "score_trend_alert", {"alert": _trend_alert}
                            ))
                except Exception as _is_err:
                    _LOGGER.debug("Installatie-score fout: %s", _is_err)

            # Generate insights
            self._insights = self._generate_insights(
                data, price_info, inverter_data, peak_data, balance_data,
                self._limiter.phase_currents, solar_surplus, boiler_decisions
            )

            # Save NILM
            try:
                await self._nilm.async_save()
            except Exception as _nilm_save_err:
                _LOGGER.warning("CloudEMS: NILM opslaan mislukt: %s", _nilm_save_err)
                # v4.5.11: NILM save failures zijn belangrijk — naar high log
                _bk_ns = getattr(self, "_learning_backup", None)
                if _bk_ns:
                    import asyncio as _aio_ns
                    _aio_ns.ensure_future(_bk_ns.async_log_high(
                        "nilm_save_failed", {"error": str(_nilm_save_err)}
                    ))

            # v2.4.17: sla review-history en adaptieve drempels op
            try:
                await self._store_review.async_save({
                    "skip_set":     list(self._review_skip_set),
                    "skip_history": self._review_skip_history,
                })
                if self._adaptive_thresholds:
                    await self._store_adaptive.async_save(self._adaptive_thresholds)
            except Exception as _rv_err:
                _LOGGER.warning("CloudEMS: review-state opslaan mislukt: %s", _rv_err)

            # ── Periodiek opslaan: alle zelflerende modules ───────────────────
            # Modules die hun eigen dirty/interval-logica hebben maar geen
            # expliciete save-aanroep in de update-loop — max elke 2-10 min.
            for _mod, _method in (
                (getattr(self, "_solar_learner",       None), "_async_save"),
                (getattr(self, "_pv_forecast",         None), "async_save"),
                (getattr(self, "_battery_degradation", None), "async_save"),
                (getattr(self, "_sensor_hints",        None), "async_save"),
                (getattr(self, "_cost_forecaster",     None), "async_save"),
                (getattr(self, "_congestion_detector", None), "async_maybe_save"),
                (getattr(self, "_battery_scheduler",   None), "async_maybe_save"),
                (getattr(self, "_home_baseline",       None), "_async_save"),
            (getattr(self, "_absence",             None), "_async_save"),
            (getattr(self, "_sensor_sanity",       None), "_async_save"),
            (getattr(self, "_shutter_learner",     None), "_async_save"),
            (getattr(self._smart_climate, "_predictive", None) if getattr(self, "_smart_climate", None) else None, "async_maybe_save"),
                (getattr(self, "_ev_session",          None), "_async_save"),
                (getattr(self, "_nilm_schedule",       None), "_async_save"),
                (getattr(self, "_gas_analysis",        None), "async_maybe_save"),
                (getattr(self, "_climate_epex",        None), "async_maybe_save"),
                (getattr(self, "_energy_budget",       None), "async_maybe_save"),
                (getattr(self, "_notification_engine", None), "async_maybe_save"),
                # v4.3.5: nieuwe persistente modules
                (getattr(self, "_capacity_peak",       None), "async_maybe_save"),
                (getattr(self, "_install_score",       None), "async_maybe_save"),
                (getattr(self, "_load_plan_accuracy",  None), "async_maybe_save"),
            ):
                if _mod is None:
                    continue
                _fn = getattr(_mod, _method, None)
                if callable(_fn):
                    try:
                        await _fn()
                    except Exception:  # noqa: BLE001
                        pass

            # v2.2.3: Prijshistorie bijhouden voor BehaviourCoach (max 720 uur = 30 dagen)
            _cur_hour_ts = int(time.time()) - (int(time.time()) % 3600)
            # v4.0.4: BDE feedback evalueren bij uurwisseling
            if price_info and price_info.get("avg_today"):
                try:
                    _fb_results = self._bde_feedback.evaluate_and_learn(
                        avg_price_today=float(price_info.get("avg_today") or 0)
                    )
                    if _fb_results:
                        await self._bde_feedback.async_save()
                except Exception as _fb_eval_err:
                    _LOGGER.debug("BDE feedback eval fout: %s", _fb_eval_err)

                # v4.6.498: Decision Outcome Learner — evalueer rijpe records elke cyclus
                try:
                    _dol_evaluated = self._decision_learner.evaluate_outcomes(
                        current_price  = float(price_info.get("current") or 0),
                        price_history  = self._price_hour_history,
                    )
                    if _dol_evaluated > 0 or self._decision_learner._dirty:
                        await self._decision_learner.async_save()
                except Exception as _dol_eval_err:
                    _LOGGER.debug("DOL evaluate fout: %s", _dol_eval_err)

            if price_info and _cur_hour_ts != self._price_history_last_hour:
                _cur_price = price_info.get("current")
                if _cur_price is not None:
                    _kwh_net = data.get("import_power", 0.0) / 1000.0 * (UPDATE_INTERVAL_FAST / 3600.0)
                    self._price_hour_history.append({
                        "ts":      _cur_hour_ts,
                        "price":   float(_cur_price),
                        "kwh_net": round(_kwh_net, 4),
                    })
                    if len(self._price_hour_history) > 720:
                        self._price_hour_history = self._price_hour_history[-720:]
                    # v1.32: voed EV-lader kalibratie met verse prijshistorie
                    if hasattr(self, "_dynamic_ev") and self._dynamic_ev:
                        self._dynamic_ev.feed_price_history(
                            [h["price"] for h in self._price_hour_history[-168:] if h.get("price")]
                        )
                    self._price_history_last_hour = _cur_hour_ts
                    # v4.1: opslaan zodat het een HA-herstart overleeft
                    await self._store_price_history.async_save({
                        "hours":     self._price_hour_history,
                        "last_hour": self._price_history_last_hour,
                    })
                    # LoadPlanAccuracyTracker: evalueer gisteren rond 06:00
                    import datetime as _dt_lpa
                    if _dt_lpa.datetime.now().hour == 6 and self._load_plan_accuracy:
                        try:
                            _lpa_eval = self._load_plan_accuracy.evaluate_yesterday(
                                self._price_hour_history
                            )
                            if _lpa_eval:
                                await self._load_plan_accuracy.async_maybe_save()
                        except Exception as _lpa_err:
                            _LOGGER.debug("LoadPlanAccuracy eval fout: %s", _lpa_err)

            # v2.4.0: GasAnalyzer tick
            gas_analysis_data: dict = {}
            if self._gas_analysis:
                try:
                    _gas_m3_val = (
                        self._p1_reader.latest.gas_m3
                        if self._p1_reader and self._p1_reader.latest and self._p1_reader.latest.gas_m3
                        else self._read_gas_sensor()
                    ) or 0.0
                    # v4.6.154: also try p1_data gas_m3_total (set by DSMR/HomeWizard integrations)
                    if _gas_m3_val <= 0:
                        _p1d = self._data.get("p1_data", {}) if self._data else {}
                        _gas_m3_val = float(_p1d.get("gas_m3_total") or _p1d.get("gas_m3") or 0.0)
                    # v4.6.154: auto-detect common gas sensor entity_ids if still 0
                    if _gas_m3_val <= 0:
                        for _auto_eid in (
                            "sensor.gas_meterstand",
                            "sensor.homewizard_gas_m3",
                            "sensor.p1_gas_m3",
                            "sensor.dsmr_reading_extra_device_delivered",
                        ):
                            _auto_st = self._safe_state(_auto_eid)
                            if _auto_st and _auto_st.state not in ("unavailable", "unknown", ""):
                                try:
                                    _auto_val = float(_auto_st.state)
                                    if _auto_val > 0:
                                        _gas_m3_val = _auto_val
                                        _LOGGER.debug("GasAnalyzer: auto-detected gas sensor %s = %.3f m³", _auto_eid, _auto_val)
                                        break
                                except (ValueError, TypeError):
                                    pass
                    _outside_t = outside_temp_c_val if outside_temp_c_val is not None else 10.0
                    if _gas_m3_val > 0:
                        self._gas_analysis.tick(
                            gas_m3_cumulative = float(_gas_m3_val),
                            outside_temp_c    = float(_outside_t),
                        )
                        # v4.6.387: Push naar persistente ringbuffer
                        _ring_now = int(time.time() * 1000)
                        _ring_last = self._gas_ring[-1] if self._gas_ring else None
                        if not _ring_last or _ring_now - _ring_last["ts"] > 5000:
                            self._gas_ring.append({"ts": _ring_now, "val": round(_gas_m3_val, 3)})
                            _ring_cutoff = _ring_now - self._GAS_RING_TTL
                            while self._gas_ring and self._gas_ring[0]["ts"] < _ring_cutoff:
                                self._gas_ring.pop(0)
                            if len(self._gas_ring) > self._GAS_RING_MAX:
                                self._gas_ring = self._gas_ring[-self._GAS_RING_MAX:]
                            self.hass.async_create_task(self._store_gas_ring.async_save(self._gas_ring))
                    _gas_price = self._read_gas_price()
                    self._gas_analysis.update_price(_gas_price)
                    _gas_result = self._gas_analysis.get_data(gas_price_eur_m3=_gas_price, current_m3=float(_gas_m3_val))

                    # Dagrecords voor drill-down in JS kaart (laatste 30 dagen)
                    # Als leeg: start backfill asynchroon (tijdstip onbekend bij eerste cyclus)
                    if not self._gas_analysis._records:
                        if hasattr(self._gas_analysis, "_backfill_records_from_statistics"):
                            _eid_bf = self._gas_analysis._find_gas_sensor()
                            if _eid_bf:
                                import asyncio as _aio_bf
                                _aio_bf.ensure_future(
                                    self._gas_analysis._backfill_records_from_statistics(_eid_bf)
                                )
                    _day_records = [
                        {
                            "date":         r.date,
                            "gas_m3":       round(r.gas_m3_delta, 3),
                            "price_eur_m3": round(r.price_eur_m3, 4),
                            "cost_eur":     round(r.gas_m3_delta * r.price_eur_m3, 2),
                            "hdd":          round(r.hdd, 1),
                        }
                        for r in self._gas_analysis._records[-30:]
                    ] if self._gas_analysis else []

                    gas_analysis_data = {
                        "gas_m3_today":           _gas_result.gas_m3_today,
                        "gas_m3_week":            _gas_result.gas_m3_week,
                        "gas_m3_month":           _gas_result.gas_m3_month,
                        "gas_m3_year":            _gas_result.gas_m3_year,
                        "gas_cost_today_eur":     _gas_result.gas_cost_today_eur,
                        "gas_cost_week_eur":      _gas_result.gas_cost_week_eur,
                        "gas_cost_month_eur":     _gas_result.gas_cost_month_eur,
                        "gas_cost_year_eur":      _gas_result.gas_cost_year_eur,
                        "efficiency_m3_hdd":      _gas_result.efficiency_m3_hdd,
                        "efficiency_rating":      _gas_result.efficiency_rating,
                        "hdd_today":              _gas_result.hdd_today,
                        "hdd_month":              _gas_result.hdd_month,
                        "seasonal_forecast_m3":   _gas_result.seasonal_forecast_m3,
                        "seasonal_forecast_eur":  _gas_result.seasonal_forecast_eur,
                        "anomaly":                _gas_result.anomaly,
                        "anomaly_message":        _gas_result.anomaly_message,
                        "advice":                 _gas_result.advice,
                        "records_count":          _gas_result.records_count,
                        "isolation_advice":       _gas_result.isolation_advice,
                        "isolation_saving_pct":   _gas_result.isolation_saving_pct,
                        "day_records":            _day_records,
                    }
                except Exception as _ga_err:
                    _LOGGER.debug("GasAnalyzer fout: %s", _ga_err)

            # Climate EPEX compensatie tick
            if self._climate_epex:
                try:
                    self._climate_epex.tick(price_info or {})
                    # v4.6.502: Fase 3 — registreer warmtepomp-beslissingen in DOL
                    try:
                        _ce_status = self._climate_epex.get_status()
                        for _ce_dev in _ce_status:
                            _ce_offset = float(_ce_dev.get("active_offset_c", 0))
                            if abs(_ce_offset) > 0.05:
                                from .energy_manager.decision_outcome_learner import build_context_bucket
                                import datetime as _dt_hp
                                _hp_action  = "preheat" if _ce_offset > 0 else "reduce"
                                _hp_kwh     = abs(_ce_offset) * 0.3  # schatting: 0.3 kWh per graad
                                _hp_bucket  = build_context_bucket(
                                    "heatpump", None, current_price or 0.0,
                                    float((price_info or {}).get("avg_today") or 0),
                                    solar_surplus if 'solar_surplus' in dir() else 0.0,
                                    month=_dt_hp.datetime.now().month,
                                    hour=_dt_hp.datetime.now().hour,
                                )
                                self._decision_learner.record_decision(
                                    component      = "heatpump",
                                    action         = _hp_action,
                                    alternative    = "hold",
                                    context_bucket = _hp_bucket,
                                    price_eur_kwh  = current_price or 0.0,
                                    energy_kwh     = _hp_kwh,
                                    eval_after_s   = 10800,  # evalueer na 3 uur
                                )
                    except Exception as _dol_hp_err:
                        _LOGGER.debug("DOL heatpump record fout: %s", _dol_hp_err)
                except Exception as _ce_err:
                    _LOGGER.debug("ClimateEpex tick fout: %s", _ce_err)

            # v2.4.0: EnergyBudget tick
            energy_budget_data: dict = {}
            if self._energy_budget:
                try:
                    _kwh_delta  = max(0.0, grid_power_w / 1000.0 * (UPDATE_INTERVAL_FAST / 3600.0))
                    _cost_delta = _kwh_delta * (current_price + float(self._config.get("energy_tax_eur_kwh", 0.0)))
                    _gas_delta  = 0.0
                    if self._p1_reader and self._p1_reader.latest:
                        _prev_gas = getattr(self, "_prev_gas_m3", 0.0)
                        _cur_gas  = float(self._p1_reader.latest.gas_m3 or 0)
                        _gas_delta = max(0.0, _cur_gas - _prev_gas)
                        self._prev_gas_m3 = _cur_gas
                    self._energy_budget.tick(
                        cost_eur_delta = _cost_delta,
                        kwh_delta      = _kwh_delta,
                        gas_m3_delta   = _gas_delta,
                    )
                    _budget_result = self._energy_budget.get_data()
                    energy_budget_data = {
                        "overall_status":       _budget_result.overall_status,
                        "days_remaining":       _budget_result.days_remaining,
                        "days_elapsed":         _budget_result.days_elapsed,
                        "month_label":          _budget_result.month_label,
                        "summary":              _budget_result.summary,
                        "electricity_eur": {
                            "status":              _budget_result.electricity_eur.status,
                            "budget_value":        _budget_result.electricity_eur.budget_value,
                            "actual_so_far":       _budget_result.electricity_eur.actual_so_far,
                            "forecast_end_month":  _budget_result.electricity_eur.forecast_end_month,
                            "pct_used":            _budget_result.electricity_eur.pct_used,
                            "remaining":           _budget_result.electricity_eur.remaining,
                            "advice":              _budget_result.electricity_eur.advice,
                        },
                        "electricity_kwh": {
                            "status":              _budget_result.electricity_kwh.status,
                            "budget_value":        _budget_result.electricity_kwh.budget_value,
                            "actual_so_far":       _budget_result.electricity_kwh.actual_so_far,
                            "pct_used":            _budget_result.electricity_kwh.pct_used,
                        } if _budget_result.electricity_kwh else None,
                        "gas_m3": {
                            "status":              _budget_result.gas_m3.status,
                            "budget_value":        _budget_result.gas_m3.budget_value,
                            "actual_so_far":       _budget_result.gas_m3.actual_so_far,
                            "pct_used":            _budget_result.gas_m3.pct_used,
                        } if _budget_result.gas_m3 else None,
                    }
                except Exception as _eb_err:
                    _LOGGER.debug("EnergyBudget fout: %s", _eb_err)

            # v2.4.0: ApplianceROI — vervanging-advies per apparaat
            appliance_roi_data: dict = {}
            if self._appliance_roi and nilm_devices_enriched:
                try:
                    _avg_price = float((price_info or {}).get("avg_today") or 0.28)
                    _roi_result = self._appliance_roi.calculate(
                        nilm_devices        = nilm_devices_enriched,
                        price_eur_kwh       = _avg_price,
                        price_hour_history  = self._price_hour_history,
                    )
                    appliance_roi_data = self._appliance_roi.to_sensor_dict(_roi_result)
                except Exception as _roi_err:
                    _LOGGER.debug("ApplianceROI fout: %s", _roi_err)

            # v2.4.0: SolarDimmer — bescherming bij negatieve EPEX-prijzen
            if self._solar_dimmer:
                try:
                    self._solar_dimmer.update_solar_power(data.get("solar_power", 0.0))
                    self._solar_dimmer.tick_curtailment(interval_s=UPDATE_INTERVAL_FAST)
                    _sd_result = await self._solar_dimmer.async_evaluate(current_price)
                    # v4.5.11: log solar dimmer beslissing
                    if _sd_result:
                        self._log_decision(
                            "solar_dimmer",
                            f"☀️ Solar dimmer: {_sd_result.get('action','?')} — {_sd_result.get('reason','')}",
                            payload={
                                "action":           _sd_result.get("action"),
                                "reason":           _sd_result.get("reason"),
                                "curtailment_pct":  _sd_result.get("curtailment_pct"),
                                "target_w":         _sd_result.get("target_w"),
                                "price_eur_kwh":    round(current_price or 0, 5),
                                "solar_w":          round(float(data.get("solar_power", 0) or 0), 1),
                            }
                        )
                except Exception as _sd_err:
                    _LOGGER.debug("SolarDimmer fout: %s", _sd_err)
            behaviour_coach_data: dict = {}
            if self._behaviour_coach and self._nilm_schedule:
                try:
                    from .energy_manager.bill_simulator import HourRecord
                    _hr_list = [
                        HourRecord(ts=h["ts"], kwh_net=h["kwh_net"], price=h["price"])
                        for h in self._price_hour_history
                    ]
                    _coach_summary = self._behaviour_coach.analyse(
                        schedule_summary = self._nilm_schedule.get_schedule_summary(),
                        hour_records     = _hr_list,
                        device_energy    = nilm_devices_enriched,
                    )
                    behaviour_coach_data = self._behaviour_coach.to_sensor_dict(_coach_summary)
                    # v1.32: stuur aanbevelingen terug naar NILMScheduleLearner
                    if self._nilm_schedule and _coach_summary.devices:
                        self._nilm_schedule.apply_coach_feedback([
                            {
                                "device_id":         r.device_id,
                                "cheapest_hour":     r.cheapest_hour,
                                "saving_eur_month":  r.saving_eur_month,
                            }
                            for r in _coach_summary.devices
                        ])
                except Exception as _bc_err:
                    _LOGGER.debug("BehaviourCoach fout: %s", _bc_err)

            # v2.2.3: LoadPlanner — optimaal uurschema voor morgen
            load_plan_data: dict = {}
            try:
                _tomorrow_prices = (price_info or {}).get("tomorrow_all", [])
                if _tomorrow_prices:
                    _ev_conn = bool(self._config.get("ev_charger_entity"))
                    _batt_soc = data.get("battery_soc_pct") or 0.0
                    _batt_cap = float(self._config.get("battery_capacity_kwh") or 0)
                    _batt_chg_kw = float(self._config.get("battery_max_charge_kw") or 0)
                    _day_type_str = (day_type_data or {}).get("day_type", "unknown")
                    _avg_p = (price_info or {}).get("avg_today") or 0.15
                    _plan = plan_tomorrow(
                        tomorrow_prices       = _tomorrow_prices,
                        pv_forecast_hourly_w  = {int(k): float(v) for k, v in (pv_forecast_hourly_tomorrow or {}).items()},
                        ev_expected           = _ev_conn,
                        ev_max_kw             = float(self._config.get("ev_max_charge_kw") or 7.4),
                        ev_departure_hour     = int(self._config.get("ev_departure_hour") or 8),
                        boiler_power_w        = float((self._boiler_ctrl.get_status()[0].get("power_w") if self._boiler_ctrl and self._boiler_ctrl.get_status() else 0) or 0),
                        battery_soc_pct       = float(_batt_soc),
                        battery_capacity_kwh  = _batt_cap,
                        battery_max_charge_kw = _batt_chg_kw,
                        day_type              = _day_type_str,
                        avg_price_eur_kwh     = float(_avg_p),
                    )
                    load_plan_data = plan_to_dict(_plan)
                    self._load_planner_data = load_plan_data
                    # LoadPlanAccuracyTracker: sla plan op voor vergelijking morgen
                    if self._load_plan_accuracy:
                        self._load_plan_accuracy.store_plan(load_plan_data)
            except Exception as _lp_err:
                _LOGGER.debug("LoadPlanner fout: %s", _lp_err)
                load_plan_data = self._load_planner_data  # gebruik laatste geldig plan

            # v2.2.3: EnergyLabelSimulator
            energy_label_data: dict = {}
            if self._energy_label:
                try:
                    _wk = float((thermal_data or {}).get("heat_loss_w_per_k") or 0)
                    _gas_m3_yr = float((p1_data or {}).get("gas_m3_year") or 0)
                    _elec_yr = float((cost_forecast or {}).get("year_kwh_est") or 0)
                    _pv_yr = float(
                        (pv_forecast_kwh * 365.0) if (pv_forecast_kwh and pv_forecast_kwh > 0)
                        else 0
                    )
                    _floor = float(self._config.get("floor_area_m2") or 0)
                    _label_result = self._energy_label.calculate(
                        w_per_k           = _wk,
                        gas_m3_year       = _gas_m3_yr,
                        electric_kwh_year = _elec_yr,
                        pv_kwh_year       = _pv_yr,
                        floor_area_m2     = _floor if _floor > 0 else None,
                    )
                    energy_label_data = self._energy_label.to_sensor_dict(_label_result)
                except Exception as _el_err:
                    _LOGGER.debug("EnergyLabel fout: %s", _el_err)

            # v2.4.1: BillSimulator — vergelijkt kosten op vast, dag/nacht en dynamisch tarief
            bill_simulator_data: dict = {}
            if len(self._price_hour_history) >= 24:
                try:
                    from .energy_manager.bill_simulator import BillSimulator, HourRecord
                    _fixed_tariff = float(self._config.get("energy_tariff_import_eur_kwh") or 0.28)
                    _bill_sim = BillSimulator(
                        self.hass,
                        fixed_tariff=_fixed_tariff,
                        day_tariff=round(_fixed_tariff * 1.1, 4),
                        night_tariff=round(_fixed_tariff * 0.9, 4),
                    )
                    _bill_sim._hours = [  # type: ignore[attr-defined]
                        HourRecord(ts=h["ts"], kwh_net=h["kwh_net"], price=h["price"])
                        for h in self._price_hour_history
                    ]
                    _bill_result = _bill_sim.get_result()
                    bill_simulator_data = {
                        "dynamic_cost_eur":     round(_bill_result.dynamic_cost_eur, 2),
                        "fixed_cost_eur":       round(_bill_result.fixed_cost_eur, 2),
                        "day_night_cost_eur":   round(_bill_result.day_night_cost_eur, 2),
                        "saving_vs_fixed_eur":  round(_bill_result.saving_vs_fixed_eur, 2),
                        "saving_vs_fixed_pct":  round(_bill_result.saving_vs_fixed_pct, 1),
                        "months_data":          _bill_result.months_data,
                        "hours_recorded":       _bill_result.hours_recorded,
                        "advice":               _bill_result.advice,
                        "months_dynamic_won":   _bill_result.months_dynamic_won,
                    }
                except Exception as _bs_err:
                    _LOGGER.debug("BillSimulator fout: %s", _bs_err)

            # v2.2.3: SalderingSimulator — gebruikt dezelfde price history als BehaviourCoach
            saldering_data: dict = {}
            if self._saldering_sim and len(self._price_hour_history) >= 168:
                try:
                    from .energy_manager.bill_simulator import HourRecord
                    _sal_hr_list = [
                        HourRecord(ts=h["ts"], kwh_net=h["kwh_net"], price=h["price"])
                        for h in self._price_hour_history
                    ]
                    _fixed_tariff = float(self._config.get("energy_tariff_import_eur_kwh") or 0.28)
                    _sal_result = self._saldering_sim.calculate(
                        hour_records        = _sal_hr_list,
                        fixed_tariff        = _fixed_tariff,
                        current_return_pct  = 1.0,
                    )
                    saldering_data = self._saldering_sim.to_sensor_dict(_sal_result)
                except Exception as _ss_err:
                    _LOGGER.debug("SalderingSimulator fout: %s", _ss_err)

            # v4.0.5: Zelfconsumptie-ratio berekening (centrale helpers)
            _pv_w   = max(0.0, data.get("solar_power", 0.0) or 0.0)
            _exp_w  = max(0.0, data.get("export_power", 0.0) or 0.0)
            _imp_w  = max(0.0, data.get("import_power", 0.0) or 0.0)
            _bat_w  = getattr(self, "_last_battery_w", 0.0)
            _grid_w_final = float(data.get("grid_power", 0.0) or 0.0)
            _selfcons_pct, _self_use_w = self._calc_self_consumption(_pv_w, _exp_w)
            # v4.5.6: gebruik balancer-resultaat als beschikbaar, anders berekenen
            _bal = data.get("_balancer")
            _house_w_final = _bal.house_w if _bal is not None else self._calc_house_load(_pv_w, _grid_w_final, _bat_w)
            # v4.5.6: zelfvoorzieningsratio — batterij-ontlading dekt ook huisverbruik
            # self_use_w = PV-deel van huisverbruik; batterij-ontlading is ook eigen energie
            _discharge_w = max(0.0, -_bat_w)  # ontladen = positief
            _self_supplied_w = _self_use_w + min(_discharge_w, max(0.0, _house_w_final - _self_use_w))
            _selfsuff_pct  = round((_self_supplied_w / _house_w_final * 100) if _house_w_final > 10 else 0.0, 1)

            # v4.6.141: debug logging verwijderd uit hot path — ensure_future elke 10s
            # verstoorde de coordinator net als eerder (fase sensoren → 0A).
            # Boiler power wordt nu gelogd via bestaand decision_boiler log.

            self._data = {
                "grid_power_w":         grid_power_w,
                "power_w":              grid_power_w,
                "solar_power_w":        data.get("solar_power", 0.0),
                "import_power_w":       data.get("import_power", 0.0),
                "export_power_w":       data.get("export_power", 0.0),
                "solar_surplus_w":      solar_surplus,
                # v4.0.9+: huisverbruik berekend door CloudEMS (centrale _calc_house_load helper)
                # house = solar + grid_netto - battery_netto
                "house_load_w":         round(_house_w_final, 1),
                "selfcons_pct":         _selfcons_pct,
                "selfsuff_pct":         _selfsuff_pct,
                "phases":               self._limiter.get_phase_summary(),
                "phase_balance":        balance_data,
                "nilm_devices":         nilm_devices_enriched,
                "nilm_mode":            self._nilm.active_mode,
                # v4.6.584: NILM apparaatgroepen (Regelneef-stijl categorisering)
                "nilm_groups": (
                    self._nilm_group_tracker.update(
                        nilm_devices_enriched,
                        getattr(self, "_last_known_price", 0.0) or 0.0,
                    )
                    if self._nilm_group_tracker else {}
                ),
                # v4.5.64: onverklaard vermogen
                "undefined_power_w":    max(0.0, round(float(_house_w_final) - _total_on_w, 1))
                                        if _total_on_w > 0 else None,
                "undefined_power_name": self._undefined_power_name or "Onverklaard vermogen",
                # v4.6.427: wasbeurt cyclus data koppelen aan NILM sensor
                "appliance_cycles":     self._data.get("appliance_cycles") if self._data else None,
                "energy_price":         self._enrich_price_info(price_info),
                "ai_status":            self._build_ai_status(),
                "cost_per_hour":        round(cost_ph, 4),
                "cost_today_eur":       self._cost_today_eur,
                "cost_month_eur":       self._cost_month_eur,
                "config_price_alert_high": float(self._config.get("price_alert_high_eur_kwh", 0.30)),
                "config_nilm_confidence":  float(self._config.get("nilm_min_confidence", 0.65)),
                "ev_decision":          ev_decision,
                "ev_solar_plan":        ev_solar_plan,
                "outdoor_temp_c":       outside_temp_c_val,
                "p1_data":              p1_data,
                "inverter_data":        inverter_data if inverter_data else [
                    # v4.6.195: fallback als solar_learner nog geen profielen heeft (cold start)
                    {
                        "entity_id": c.get("entity_id", ""),
                        "label":     c.get("label") or c.get("name") or f"Omvormer {i+1}",
                        "current_w": 0.0,
                        "peak_w":    0.0,
                        "peak_w_7d": 0.0,
                        "estimated_wp": c.get("rated_power_w") or 0,
                        "rated_power_w": c.get("rated_power_w"),
                        "utilisation_pct": 0.0,
                        "clipping": False,
                        "phase": None,
                        "phase_certain": False,
                        "phase_display": None,
                        "phase_confidence": 0.0,
                        "phase_provisional": True,
                        "samples": 0,
                        "confident": False,
                        "azimuth_deg": None, "azimuth_learned": None, "azimuth_compass": "onbekend",
                        "tilt_deg": None, "tilt_learned": None,
                        "orientation_confident": False,
                        "orientation_learning_pct": 0,
                        "clear_sky_samples": 0,
                        "orientation_samples_needed": 60,
                        "clipping_ceiling_w": None,
                    }
                    for i, c in enumerate(self._config.get("inverter_configs", []))
                ],          # ← peak + clipping
                "pv_forecast_today_kwh":     pv_forecast_kwh,
                "forecast_solar_status":     _fcsolar_status if '_fcsolar_status' in dir() else {},
                "pv_payback":           self._calc_pv_payback(
                    pv_forecast_kwh,
                    price_info,
                    current_price,
                ),
                "pv_forecast_tomorrow_kwh":  pv_forecast_tomorrow_kwh,
                "pv_forecast_hourly":        pv_forecast_hourly,
                "pv_forecast_hourly_tomorrow": pv_forecast_hourly_tomorrow,
                "pv_today_hourly_kwh":       list(self._pv_today_hourly_kwh),  # v4.6.492
                "inverter_profiles":    inverter_profiles,
                "peak_shaving":         peak_data,
                "boiler_status":        self._boiler_ctrl.get_status() if self._boiler_ctrl else [],
                "energy_demand":        self._calc_energy_demand(data, price_info),
                "pool":                 pool_data,          # ← v1.25.8 zwembad controller
                "lamp_circulation":     lamp_circ_data,     # ← v1.25.9 intelligente lampenbeveiliging
                "shutters":             self._shutter_ctrl.get_status() if self._shutter_ctrl else {},  # ← v3.9.0 rolluiken
                "shutter_thermal_gains": getattr(self, "_shutter_thermal_learner", None).get_status() if getattr(self, "_shutter_thermal_learner", None) else [],
                "decision_log":         list(self._decision_log),
                "insights":             self._insights,
                "nilm_diagnostics":     self._nilm.get_diagnostics(),  # ← v1.7
                # v4.3.6: runtime_warnings — actieve waarschuwingen voor dashboard
                # (P1 spikes, fase-sensor clamp, stale data, etc.)
                "runtime_warnings":     self._build_runtime_warnings(),
                # v4.6.583: data_quality — puur data-kwaliteitsissues (subset van runtime_warnings)
                "data_quality":         [
                    w for w in self._build_runtime_warnings()
                    if w.get("category") == "data_quality"
                ],
                # v4.0.3: Laag C — concurrent load per fase voor dashboard + BDE
                "off_peak":    self._off_peak_status,             # v4.0.4
                "bde_feedback": self._bde_feedback.get_diagnostics(), # v4.0.4             # v4.0.4
                "concurrent_load": {
                    phase: round(
                        getattr(self._nilm, "_power_learner", None)
                        and sum(
                            w for w in (
                                getattr(self._nilm, "_power_learner").
                                _active_loads.get(phase, {}).values()
                            )
                        ) or 0.0, 1
                    )
                    for phase in ("L1", "L2", "L3")
                },
                "ollama_health":        self._ollama_health,            # ← v1.16
                "ollama_diagnostics":   self._nilm.get_ollama_diagnostics(),  # ← v1.16
                "hybrid_nilm":          self._hybrid.get_diagnostics() if self._hybrid else {},  # ← v1.17
                "ev_pid_state":         ev_pid_state,                   # ← v1.8
                "phase_pid_states":     self._get_phase_pid_states(),   # ← v1.8
                "co2_info":             co2_info,                       # ← v1.9
                "cost_forecast":        cost_forecast,                  # ← v1.9
                "battery_schedule":     battery_schedule,               # ← v1.9
                "gas_prediction":     self._gas_prediction,              # v4.0.5
                "tariff_change":      self._tariff_change,               # v4.0.5
                "battery_efficiency": self._battery_eff_status,         # v4.0.5
                "supplier_compare":   self._calc_supplier_compare(),          # v4.0.6
                "appliance_roi":      self._calc_appliance_roi(            # v4.0.5
                    nilm_devices_enriched, price_info, current_price
                ),
                "battery_decision": {                                   # ← v4.0.2
                    "action":        getattr(_bde_result, "action",          "idle")   if _bde_result else "idle",
                    "reason":        getattr(_bde_result, "reason",          "—")      if _bde_result else "—",
                    "priority":      getattr(_bde_result, "priority",        5)        if _bde_result else 5,
                    "confidence":    getattr(_bde_result, "confidence",      0.0)      if _bde_result else 0.0,
                    "source":        getattr(_bde_result, "source",          "—")      if _bde_result else "—",
                    "tariff_group":  getattr(_bde_result, "tariff_group",    "normal") if _bde_result else "normal",
                    "target_soc_pct":getattr(_bde_result, "target_soc_pct",  None)     if _bde_result else None,
                    "executed":      bool(_bde_result and _bde_result.should_execute),
                    "explain":       _bde_explain,
                },
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
                    # Dag-verbruik: lees direct van gas_analysis (today_gas_start_m3)
                    # Als gas_analysis nog geen start heeft, bootstrappen via HA recorder
                    # Dag-verbruik: gas_analysis heeft beste waarde, fallback op coordinator tracking
                    "dag_m3":    float(gas_analysis_data.get("gas_m3_today") or (
                        round(max(0.0, (
                            (_gas_now := (self._p1_reader.latest.gas_m3 if self._p1_reader and self._p1_reader.latest else self._read_gas_sensor()) or 0.0)
                            - getattr(self, "_gas_today_start", _gas_now)
                        )), 3) if getattr(self, "_gas_today_start", 0.0) > 0 else 0.0
                    )),
                    "week_m3":   float(gas_analysis_data.get("gas_m3_week")   or 0.0),
                    "maand_m3":  float(gas_analysis_data.get("gas_m3_month")  or 0.0),
                    "jaar_m3":   float(gas_analysis_data.get("gas_m3_year")   or 0.0),
                    # Kosten per periode (€)
                    "dag_eur":   float(gas_analysis_data.get("gas_cost_today_eur")  or 0.0),
                    "week_eur":  float(gas_analysis_data.get("gas_cost_week_eur")   or 0.0),
                    "maand_eur": float(gas_analysis_data.get("gas_cost_month_eur")  or 0.0),
                    "jaar_eur":  float(gas_analysis_data.get("gas_cost_year_eur")   or 0.0),
                    # Gasprijs €/m³
                    "gas_prijs_per_m3": self._read_gas_price(),
                    # v4.6.388: fibonacci m³/uur — coordinator berekent, JS toont alleen resultaten
                    "gas_fib_hours":     self._calc_gas_fib_and_update_max(),
                    # v4.6.574: geleerde maximale gasflow voor schaling balkjes in JS
                    "gas_rate_max_m3h": round(self._gas_rate_max_m3h, 4),
                },
                "batteries":            self._collect_multi_battery_data(),
                "micro_mobility":       micro_mobility_data,
                "clipping_loss":        clipping_loss_data,
                "shadow_detection":     shadow_data,
                "consumption_categories": categories_data,
                "room_meter":       room_meter_data,         # ← v1.20
                "cheap_switches":   cheap_switch_data,        # ← v1.20
                "smart_delay":      smart_delay_data,         # ← v4.2
                "nilm_load_shift":  nilm_shift_data,          # ← v4.6.217
                "battery_providers": (lambda: {               # ← v1.21 + v4.5.7 balancer-verrijking
                    **((getattr(self, "_battery_providers", None) and
                        self._battery_providers.get_info()) or {}),
                    # v4.5.7: verrijk elke provider met actuele interval + geleerde lag
                    # vanuit EnergyBalancer zodat de battery card dit kan tonen
                    "balancer": {
                        "battery_interval_s":  (self._energy_balancer.get_diagnostics().get("battery_interval_s") if self._energy_balancer else None),
                        "battery_stale":       (self._energy_balancer.get_diagnostics().get("battery_stale", False) if self._energy_balancer else False),
                        "battery_lag_s":       (self._energy_balancer.get_learned_battery_lag_s() if self._energy_balancer else None),
                        "battery_lag_conf":    (self._energy_balancer.get_diagnostics().get("battery_lag_confidence") if self._energy_balancer else None),
                        "battery_lag_samples": (self._energy_balancer.get_diagnostics().get("battery_lag_samples", 0) if self._energy_balancer else 0),
                    },
                })(),
                "zonneplan_bridge": (                         # ← v1.21 backwards-compat alias
                    getattr(self, "_battery_providers", None) and
                    self._battery_providers.get_info() or {}
                ),
                # v1.15.0: new intelligence
                "heat_pump_cop":    hp_cop_data,
                "sensor_sanity":    sanity_data,
                "ema_diagnostics":  ema_diag,
                "energy_balancer":  {
                    **(self._energy_balancer.get_diagnostics() if self._energy_balancer else {}),
                    # v4.6.522: P1-reader interval meting en DSMR-type
                    "p1_measured_interval_s":   (
                        getattr(self._p1_reader, "measured_interval_s", None)
                        if self._p1_reader else None
                    ),
                    "p1_telegram_samples":      (
                        getattr(self._p1_reader, "telegram_sample_count", 0)
                        if self._p1_reader else 0
                    ),
                    "dsmr_type_configured":     self._config.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL),
                    "dsmr_type_auto_corrected": getattr(self, "_dsmr_type_auto_corrected", False),
                    # v4.6.522: sensor interval registry samenvatting
                    "sensor_intervals":         (
                        self._sensor_interval_registry.get_diagnostics()
                        if self._sensor_interval_registry else {}
                    ),
                },
                "occupancy":        occupancy_data,
                "zone_presence":    zone_presence_data,
                "climate_preheat":  preheat_data,
                "pv_accuracy":      pv_accuracy_data,
                "outage_detected":  _outage_detected,
                "outage_message":   _outage_message if _outage_detected else "",
                "notifications":        {},  # gevuld na dispatch hieronder
                # v1.18.0: cross-validatie alerts voor notification engine
                "phase_conflict_alerts": (
                    self._solar_learner.get_phase_conflict_alerts()
                    if self._solar_learner else []
                ),
                "new_panel_resets": [
                    {
                        "inverter_id":  p.inverter_id,
                        "label":        p.label,
                        "reset_count":  p.new_panel_resets,
                    }
                    for p in (self._solar_learner.get_all_profiles() if self._solar_learner else [])
                    if p.new_panel_resets > 0
                ],
                # v2.2.3: nieuwe modules
                "behaviour_coach":      behaviour_coach_data,
                "other_bucket":         self._nilm_other_tracker.to_sensor_dict(),
                "active_faults":        self._fault_notifier.get_active_faults() if self._fault_notifier else [],
                "load_plan":            load_plan_data,
                "energy_label":         energy_label_data,
                "saldering":            saldering_data,
                "export_limit":         export_limit_data,              # ← v3.9.0
                "battery_savings":      battery_savings_data,
                # v2.4.1: bill simulator
                "bill_simulator":       bill_simulator_data,
                # v2.2.3: systeemgezondheid
                "system_health":        self._build_system_health(price_info),
                # v2.4.0: nieuwe modules
                "climate_epex_status":  self._climate_epex.get_status() if self._climate_epex else [],
                "climate_epex_power_w": self._climate_epex.get_total_power_w() if self._climate_epex else 0.0,
                "gas_analysis":         {
                    **gas_analysis_data,
                    "gas_kwh": (self._p1_reader.latest.gas_kwh if self._p1_reader and self._p1_reader.latest else round((self._read_gas_sensor() or 0.0) * 9.769, 3)),
                },
                "energy_budget":        energy_budget_data,
                "appliance_roi":        appliance_roi_data,
                "solar_dimmer":         self._solar_dimmer.get_curtailment_stats() if self._solar_dimmer else {},
                # v2.4.0: tarief-anomalie (berekende kosten vs geconfigureerd tarief × import)
                "tariff_check":         self._calc_tariff_check(p1_data, price_info),
                # v4.5.0: externe provider data (omvormers, EV, apparaten, leveranciers)
                "external_providers_status": (
                    self._provider_manager.get_status()
                    if self._provider_manager else []
                ),
            }

            # v4.5.0: poll alle externe providers asynchroon
            # v4.5.1: resultaat is al gecached in _provider_poll_cache (vroeg in de cyclus)
            if self._provider_manager and self._provider_manager.active_count > 0:
                try:
                    from .provider_manager import (
                        extract_inverter_summary, extract_ev_summary,
                        extract_appliance_summary, extract_energy_prices,
                    )
                    # Gebruik cache als die gevuld is, anders opnieuw pollen
                    _ext = locals().get("_provider_poll_cache") or await self._provider_manager.async_poll_all()
                    self._data["ext_inverters"]  = extract_inverter_summary(_ext)
                    self._data["ext_ev"]         = extract_ev_summary(_ext)
                    self._data["ext_appliances"] = extract_appliance_summary(_ext)
                    _ext_prices = extract_energy_prices(_ext)
                    if _ext_prices:
                        self._data["ext_energy_prices"] = _ext_prices
                except Exception as _ext_err:
                    _LOGGER.debug("ProviderManager poll fout: %s", _ext_err)

            # v1.12.0: Notification engine — ingest alle alerts en verstuur
            if self._notification_engine:
                try:
                    alert_dict = NotificationEngine.build_alerts_from_coordinator_data(self._data)
                    # v4.1: Overduration guard — apparaten die te lang aanstaan
                    if self._overduration_guard:
                        try:
                            _od_devs = self._data.get("nilm_devices", [])
                            _od_alerts = self._overduration_guard.update(_od_devs)
                            alert_dict.update(_od_alerts)
                        except Exception as _od_err:
                            _LOGGER.debug("OverdurationGuard error: %s", _od_err)
                    self._notification_engine.ingest(alert_dict)
                    await self._notification_engine.async_dispatch()
                    self._data["notifications"] = self._notification_engine.get_data()
                    await self._notification_engine.async_maybe_save()
                except Exception as _ne_err:
                    _LOGGER.debug("NotificationEngine error: %s", _ne_err)
            # Guardian: autonome bewaking evalueren
            if hasattr(self, "_guardian") and self._guardian:
                try:
                    await self._guardian.async_evaluate()
                    self._data["guardian"] = self._guardian.get_status()
                except Exception as _g_err:
                    _LOGGER.debug("SystemGuardian error: %s", _g_err)
            # Watchdog: update geslaagd
            if self._watchdog:
                self._watchdog.report_success()
            self._data["watchdog"] = self._watchdog.get_data() if self._watchdog else {}
            # v2.2.3: health cycle counter
            self._health_cycle_count = getattr(self, "_health_cycle_count", 0) + 1

            # v2.5: Periodieke herverificatie van NILM config-sensor excludes.
            # set_config_sensor_eids wordt ook bij init aangeroepen, maar nieuwe
            # apparaten kunnen daarna geleerd zijn. Elke 60 cycli (~10 min)
            # worden de exclusion sets opnieuw opgebouwd en doorgegeven zodat
            # bijv. EV-laders of warmtepompen die toch in NILM belandden worden
            # uitgeschoond — ook als ze als ze via de fasesensor zijn geleerd.
            if self._health_cycle_count % 60 == 0:
                try:
                    _refresh_eids: set = set()
                    for _key in (
                        "grid_sensor", "solar_sensor", "battery_sensor", "battery_soc_entity",
                        "import_power_sensor", "export_power_sensor",
                        "power_sensor_l1", "power_sensor_l2", "power_sensor_l3",
                        "voltage_sensor_l1", "voltage_sensor_l2", "voltage_sensor_l3",
                        "phase_sensors_L1", "phase_sensors_L2", "phase_sensors_L3",
                        "gas_sensor", "gas_price_sensor",
                        "heat_pump_power_entity", "heat_pump_thermal_entity",
                        "ev_charger_entity",
                    ):
                        _v = self._config.get(_key, "")
                        if _v:
                            _refresh_eids.add(_v)
                    for _inv in self._config.get("inverter_configs", []):
                        if _inv.get("entity_id"):
                            _refresh_eids.add(_inv["entity_id"])
                    for _bc in self._config.get("battery_configs", []):
                        for _bk in ("power_sensor", "soc_sensor", "charge_sensor", "discharge_sensor"):
                            if _bc.get(_bk):
                                _refresh_eids.add(_bc[_bk])
                    if _refresh_eids:
                        self._nilm.set_config_sensor_eids(_refresh_eids)
                        # Ververs ook blocked_friendly_names
                        _refresh_names: set = set()
                        for _eid in _refresh_eids:
                            _st = self._safe_state(_eid)
                            if _st:
                                _fn = _st.attributes.get("friendly_name") or ""
                                if _fn:
                                    _refresh_names.add(_fn)
                        if _refresh_names:
                            self._nilm.set_blocked_friendly_names(_refresh_names)
                except Exception as _pref_err:
                    _LOGGER.debug("CloudEMS: periodieke NILM-exclude refresh mislukt: %s", _pref_err)
            # v3.5.3: simulator — overschrijft live waarden, bevriest leerprocessen
            if self._simulator is not None:
                self._data["simulator"] = self._simulator.get_status()
                if self._simulator.active:
                    self._data = self._simulator.apply(self._data)

            # v4.6.13: EntityDeviceLog — tick + resultaat in data voor dashboard/diagnostics
            if self._entity_device_log is not None:
                try:
                    self._data["entity_log"] = await self._entity_device_log.async_tick()
                except Exception as _edl_err:
                    _LOGGER.debug("EntityDeviceLog tick fout: %s", _edl_err)

            # Flush decisions history naar JSON (periodiek, alleen als dirty)
            if self._decisions_history:
                self._decisions_history.flush_if_dirty()

            # Telemetry: uur-upload tick
            if self._telemetry:
                try:
                    await self._telemetry.async_tick()
                except Exception as _tel_err:
                    _LOGGER.debug("CloudEMS telemetry tick fout: %s", _tel_err)

            # v4.6.152: end cycle, measure time, adapt interval if needed
            _cycle_ms = self._perf.end_cycle()
            _new_interval = self._perf.interval_s
            if self.update_interval.seconds != _new_interval:
                self.update_interval = timedelta(seconds=_new_interval)
            # Expose performance data in coordinator data
            self._data["performance"] = self._perf.get_status_dict()

            # Log performance every 10 cycles to normal log
            if self._coordinator_tick % 10 == 0:
                _perf_status = self._perf.get_status_dict()
                _bk_perf = getattr(self, "_learning_backup", None)
                if _bk_perf:
                    import asyncio as _aio_perf
                    _aio_perf.ensure_future(_bk_perf.async_log_normal("performance", _perf_status))

            # v4.6.279: Auto-excludeer bekende integratie-apparaten uit energiebalans
            _nilm_det = getattr(self, "_nilm_detector", None)
            self._nilm_auto_excl_cycle = getattr(self, "_nilm_auto_excl_cycle", 0) + 1
            if _nilm_det and self._nilm_auto_excl_cycle % 60 == 1:  # ~elke 10 min
                try:
                    _all_eids = {eid for eid in self.hass.states.async_entity_ids()}
                    # Topology: geef bekende infra-entity_ids door aan NILM
                    _topo = getattr(self, "_meter_topology", None)
                    if _topo:
                        try:
                            _topo_tree = _topo.get_tree()
                            _topo_infra_eids = set()
                            _cfg = self._config
                            _known_infra = {
                                _cfg.get("battery_sensor", ""),
                                _cfg.get("solar_sensor", ""),
                                _cfg.get("grid_sensor", ""),
                                _cfg.get("battery_soc_entity", ""),
                            } - {""}
                            # Alle topo-nodes waarvan entity_id in bekende infra-set
                            def _collect_infra(nodes):
                                for n in nodes:
                                    if n.get("entity_id","") in _known_infra:
                                        _topo_infra_eids.add(n["entity_id"])
                                    _collect_infra(n.get("children", []))
                            _collect_infra(_topo_tree)
                            if _topo_infra_eids:
                                _topo_excl = _nilm_det.auto_exclude_by_entity_ids(_topo_infra_eids)
                                if _topo_excl:
                                    _LOGGER.info(
                                        "CloudEMS NILM: %d apparaten uitgesloten via topology (%s)",
                                        len(_topo_excl), ", ".join(_topo_excl[:3])
                                    )
                        except Exception as _te:
                            _LOGGER.debug("CloudEMS topology→NILM exclusie fout: %s", _te)

                    _excl_count  = _nilm_det.auto_exclude_managed_integration_devices(_all_eids)
                    _merge_count = _nilm_det.auto_merge_duplicate_names()
                    # Balans + correlatie check
                    _suspects = _nilm_det.check_balance_suspect_devices(
                        house_w   = float(self._data.get("house_power",    0) or 0) if self._data else 0,
                        battery_w = float(self._data.get("battery_power",  0) or 0) if self._data else 0,
                        solar_w   = float(self._data.get("solar_power",    0) or 0) if self._data else 0,
                        grid_w    = float(self._data.get("grid_power",     0) or 0) if self._data else 0,
                    )
                    _bal_count = _nilm_det.apply_balance_suspects(_suspects) if _suspects else 0
                    if _excl_count > 0 or _merge_count > 0 or _bal_count > 0:
                        _LOGGER.info(
                            "CloudEMS: %d NILM uitgesloten (integratie), "
                            "%d duplicaten samengevoegd, %d uitgesloten (balans/correlatie)",
                            _excl_count, _merge_count, _bal_count,
                        )
                        self.async_update_listeners()
                except Exception as _ae:
                    _LOGGER.debug("CloudEMS NILM auto-exclusie/merge fout: %s", _ae)

            # v4.6.276: AdaptiveHome bridge — stuur energiestatus, NILM en prijsinfo
            try:
                _ah = getattr(self, "_ah_bridge", None)
                if _ah is not None:
                    _ah.fire_state_update(self._data)
                    _nilm_devs = self._data.get("nilm_devices", [])
                    if _nilm_devs:
                        _ah.fire_nilm_update(_nilm_devs)
                    _pi = self._data.get("price_info", {}) or {}
                    if _pi:
                        _ah.fire_price_update(_pi)
                    _pres = self._data.get("presence_detected", False)
                    _ah.fire_presence_update(_pres, method="power")
            except Exception as _ah_err:  # noqa: BLE001
                _LOGGER.debug("CloudEMS AdaptiveHome bridge fire fout: %s", _ah_err)

            # ── Long-term statistics (InfluxDB/Grafana compatible) ────────────
            # Schrijf elk uur key metrics naar HA statistieken zodat
            # InfluxDB en Grafana ze automatisch oppikken via HA API
            _tick = getattr(self, "_coordinator_tick", 0)
            if _tick % 360 == 1:  # ~elk uur (360 × 10s)
                try:
                    await self._write_long_term_stats(self._data)
                except Exception as _lts_exc:
                    _LOGGER.debug("CloudEMS long-term stats fout: %s", _lts_exc)

            return self._data

        except Exception as exc:
            cycle = getattr(self, "_health_cycle_count", 0)
            _LOGGER.exception(
                "CloudEMS coordinator update failed at cycle %d: %s — zie HA logs voor volledige traceback",
                cycle, exc,
            )
            # v4.5.11: log fouten ook naar diag-log voor post-mortem analyse
            try:
                _bk = getattr(self, "_learning_backup", None)
                if _bk is not None:
                    import asyncio as _aio, traceback as _tb
                    _aio.ensure_future(_bk.async_log_high("error", {
                        "cycle": cycle,
                        "error": str(exc),
                        "type":  type(exc).__name__,
                        "trace": _tb.format_exc(limit=8),
                    }))
            except Exception as _exc_ignored:
                _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)
            # Watchdog: update mislukt — logt, slaat op, herstart indien nodig
            if self._watchdog:
                await self._watchdog.report_failure(exc)
                self._data["watchdog"] = self._watchdog.get_data()
            # Flush decisions history ook bij fouten
            if self._decisions_history:
                self._decisions_history.flush_if_dirty()
            raise UpdateFailed(str(exc)) from exc

    # ── Data gathering ────────────────────────────────────────────────────────

    def _build_runtime_warnings(self) -> list[dict]:
        """
        v4.3.6: Bouw een lijst van actieve runtime-waarschuwingen.

        Elke waarschuwing is een dict met:
          - code:    unieke identifier (voor dashboard filtering)
          - level:   'warning' | 'error'
          - message: leesbare tekst (NL)
          - detail:  optionele extra info

        Gebruikt door dashboard en toekomstige health check integratie.
        Cloud-ready: geen HA-specifieke imports — alleen self._* state.
        """
        warnings: list[dict] = []

        # ── P1 spike-teller ───────────────────────────────────────────────────
        if self._p1_reader:
            spikes = getattr(self._p1_reader, "spike_count", 0)
            if spikes > 0:
                warnings.append({
                    "code":    "p1_spikes",
                    "level":   "warning" if spikes < 5 else "error",
                    "message": f"P1 slimme meter heeft {spikes}× een ongeldige piek-meting gestuurd.",
                    "detail":  "De metingen zijn automatisch genegeerd. "
                               "Controleer de P1-verbinding als dit vaker voorkomt.",
                })

        # ── P1 data staleness ─────────────────────────────────────────────────
        p1_age = time.time() - getattr(self, "_last_p1_update", 0.0)
        if self._p1_reader and p1_age > 90:
            warnings.append({
                "code":    "p1_stale",
                "level":   "error",
                "message": f"P1 slimme meter heeft al {int(p1_age)}s geen nieuw telegram gestuurd.",
                "detail":  "Fase-vermogen sensoren tonen mogelijk verouderde waarden. "
                           "Controleer de P1-lezer verbinding.",
            })

        # ── DSMR-type mismatch detectie ───────────────────────────────────────
        try:
            if self._p1_reader:
                _measured = getattr(self._p1_reader, "measured_interval_s", None)
                _samples  = getattr(self._p1_reader, "telegram_sample_count", 0)
                _cfg_type = self._config.get(CONF_DSMR_TYPE, DSMR_TYPE_UNIVERSAL)
                if (
                    _measured is not None
                    and _samples >= DSMR_AUTODETECT_MIN_SAMPLES
                    and _cfg_type != DSMR_TYPE_UNIVERSAL
                ):
                    _expected = DSMR_TYPE_EXPECTED_INTERVAL.get(_cfg_type)
                    _detected_type = None
                    if _measured < DSMR_AUTODETECT_FAST_THRESHOLD_S:
                        _detected_type = DSMR_TYPE_5
                    elif _measured > DSMR_AUTODETECT_SLOW_THRESHOLD_S:
                        _detected_type = DSMR_TYPE_4

                    if _detected_type and _detected_type != _cfg_type:
                        warnings.append({
                            "code":    "dsmr_type_mismatch",
                            "level":   "warning",
                            "message": (
                                f"DSMR-type ingesteld op {DSMR_TYPE_LABELS.get(_cfg_type, _cfg_type)}, "
                                f"maar gemeten interval is {_measured:.1f}s "
                                f"(verwacht: {DSMR_TYPE_EXPECTED_INTERVAL.get(_cfg_type, '?')}s). "
                                f"Waarschijnlijk is dit een {DSMR_TYPE_LABELS.get(_detected_type, _detected_type)}."
                            ),
                            "detail":  (
                                f"CloudEMS heeft {_samples} telegram-intervallen gemeten (gemiddeld {_measured:.1f}s). "
                                f"Pas het DSMR-type aan via Instellingen → Netsensoren om de sturing te optimaliseren."
                            ),
                        })
        except Exception:
            pass

        # ── Fase-sensor clamp actief (wordt bijgehouden in sensor.py via attr) ─
        # Coordinator heeft geen directe toegang tot sensor state; dit wordt
        # bijgehouden via het aantal keer dat een None-waarde teruggegeven werd
        # door de clamp. Toekomstige versie: per-fase clamp-teller bijhouden.
        # (Nu: alleen de p1 spike teller is beschikbaar)

        # ── Learning freeze ───────────────────────────────────────────────────
        if self.learning_frozen:
            warnings.append({
                "code":    "learning_frozen",
                "level":   "warning",
                "message": "Leren is gepauzeerd (testmodus actief).",
                "detail":  "Historische data en NILM-leren worden niet bijgewerkt.",
            })

        # ── Data Quality checks ───────────────────────────────────────────────
        try:
            dq_issues = self._data_quality_monitor.check(
                self._data or {},
                self._config or {},
            )
            for issue in dq_issues:
                warnings.append({
                    "code":    issue["code"],
                    "level":   issue["level"],
                    "message": issue["message"],
                    "detail":  issue.get("detail", ""),
                    "category": "data_quality",
                })
        except Exception as _dq_err:
            _LOGGER.debug("DataQualityMonitor fout: %s", _dq_err)

        return warnings

    def _calc_supplier_compare(self) -> list:
        """v4.0.6: Vergelijk energiecontracten op basis van werkelijk verbruiksprofiel."""
        try:
            from .energy_manager.supplier_compare import compare_contracts, to_dict_list
            result = to_dict_list(compare_contracts(self._price_hour_history, days=30))
            # v4.3.5: voeg werkelijk afgeleid tarief toe als metadata
            _actual = derive_actual_tariff(self._price_hour_history, days=30)
            if _actual and result:
                for r in result:
                    r["actual_avg_import_eur"] = _actual.get("avg_import_eur_kwh")
                    r["actual_avg_export_eur"] = _actual.get("avg_export_eur_kwh")
                    r["actual_days_measured"]  = _actual.get("days_measured")
            return result
        except Exception as _sc_err:
            _LOGGER.debug("SupplierCompare fout: %s", _sc_err)
            return []

    def _calc_appliance_roi(self, devices: list, price_info: dict, current_price: float) -> list:
        """v4.0.5: Bereken ROI per NILM-apparaat."""
        try:
            from .energy_manager.appliance_roi import calculate_appliance_roi, to_dict_list
            if not devices:
                return []
            # Converteer enriched dicts naar objecten met benodigde attributen
            class _Dev:
                def __init__(self, d):
                    self.device_id   = d.get("device_id", "")
                    self.display_name = d.get("name", "") or d.get("device_id", "")
                    self.device_type = d.get("type", "")
                    self.avg_power_w = float(d.get("power_w") or d.get("avg_power_w") or 0)
                    self.daily_runtime_h = None

            devs = [_Dev(d) for d in devices if d.get("confirmed")]
            rois = calculate_appliance_roi(devs, self._price_hour_history, current_price or 0.25)
            return to_dict_list(rois)
        except Exception as _roi_err:
            _LOGGER.debug("ApplianceROI fout: %s", _roi_err)
            return []

    def _safe_state(self, entity_id: str):
        """
        v4.0.9: Veilige wrapper via EntityProvider.
        In HA: provider wikkelt hass.states.get().
        In cloud: provider haalt data van Tuya/MQTT/etc.
        """
        if not entity_id:
            return None
        try:
            return self._provider._hass.states.get(entity_id)
        except Exception as _ss_err:
            _LOGGER.debug("_safe_state(%s) fout: %s", entity_id, _ss_err)
            return None

    async def _async_get_state(self, entity_id: str) -> "Optional[EntityState]":
        """Async state opvragen via provider — cloud-compatibel."""
        return await self._provider.get_state(entity_id)

    async def _async_call_service(
        self, domain: str, service: str, entity_id: str, data: dict = None
    ) -> bool:
        """Service aanroepen via provider — cloud-compatibel."""
        return await self._provider.call_service(domain, service, entity_id, data)


    def _read_state(self, entity_id: str, stale_threshold_s: float = 120.0) -> Optional[float]:
        """Read HA state as float. Also feeds unit_of_measurement to the power calculator.
        
        Returns None if state is older than stale_threshold_s — prevents frozen sensor values
        from being used as if they are live readings (issue #31 battery freeze).
        """
        if not entity_id:
            return None
        state = self._safe_state(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        # Stale check: als de sensor al te lang niet geüpdatet is, beschouw als None
        # zodat de balancer de Kirchhoff-schatting gebruikt ipv de bevroren waarde
        try:
            import datetime as _dt_rs
            _age_s = (_dt_rs.datetime.now(_dt_rs.timezone.utc) - state.last_updated).total_seconds()
            if _age_s > stale_threshold_s:
                _LOGGER.debug(
                    "CloudEMS _read_state: %s is stale (%.0fs oud) — gebruik balancer schatting",
                    entity_id, _age_s
                )
                return None
        except Exception:
            pass  # geen last_updated beschikbaar — ga door
        # Feed UOM to power calculator so kW/W is determined from metadata first
        self._calc.observe_state(entity_id, state)
        try:
            raw = float(state.state)
        except (ValueError, TypeError):
            return None
        # v4.6.522: registreer update-interval voor elke vermogenssensor
        try:
            if self._sensor_interval_registry is not None:
                self._sensor_interval_registry.observe(entity_id, raw)
        except Exception:
            pass
        return raw


    async def _backfill_gas_ring_from_recorder(self) -> None:
        """Vul de gas ringbuffer vanuit HA statistieken (korte-termijn, uurlijks).
        Gebruikt de gas_m3_cumulative waarden van de laatste 25 uur.
        Geeft de fibonacci-sectie direct bruikbare data na herstart/eerste install.
        """
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period
            from homeassistant.util import dt as dt_util
            import datetime as _dt

            # Gebruik dezelfde gas-sensor detectie als GasAnalyzer
            gas_eid = None
            if self._gas_analysis and hasattr(self._gas_analysis, "_find_gas_sensor"):
                gas_eid = self._gas_analysis._find_gas_sensor()
            if not gas_eid:
                # Fallback: scan alle m³ sensoren > 100
                for _st in self.hass.states.async_all("sensor"):
                    if "cloudems" in _st.entity_id:
                        continue
                    if _st.attributes.get("unit_of_measurement") != "m³":
                        continue
                    try:
                        if float(_st.state) > 100:
                            gas_eid = _st.entity_id
                            break
                    except (ValueError, TypeError):
                        pass
            if not gas_eid:
                _LOGGER.debug("Gas ring backfill: geen gas sensor gevonden")
                return

            now    = dt_util.now()
            start  = now - _dt.timedelta(hours=26)
            now_ms = int(time.time() * 1000)

            recorder = get_instance(self.hass)
            stats = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass, start, now, {gas_eid}, "hour", None, {"sum"}
            )
            rows = stats.get(gas_eid, [])
            if not rows:
                _LOGGER.debug("Gas ring backfill: geen statistieken voor %s", gas_eid)
                return

            new_points = []
            for row in rows:
                val = row.get("sum")
                if val is None or val <= 0:
                    continue
                _start = row.get("start")
                try:
                    if isinstance(_start, (int, float)):
                        ts_ms = int(_start * 1000)
                    elif hasattr(_start, "timestamp"):
                        ts_ms = int(_start.timestamp() * 1000)
                    else:
                        continue
                except Exception:
                    continue
                if now_ms - ts_ms > self._GAS_RING_TTL:
                    continue
                new_points.append({"ts": ts_ms, "val": round(float(val), 3)})

            if not new_points:
                _LOGGER.debug("Gas ring backfill: %s heeft geen bruikbare sum-waarden", gas_eid)
                return

            # Merge met bestaande ring
            existing = {p["ts"]: p for p in self._gas_ring}
            for p in new_points:
                existing[p["ts"]] = p
            self._gas_ring = sorted(existing.values(), key=lambda x: x["ts"])
            if len(self._gas_ring) > self._GAS_RING_MAX:
                self._gas_ring = self._gas_ring[-self._GAS_RING_MAX:]
            await self._store_gas_ring.async_save(self._gas_ring)
            _LOGGER.info("Gas ring backfill: %d punten geladen vanuit recorder (%s)",
                         len(new_points), gas_eid)
        except Exception as _bf_err:
            _LOGGER.warning("Gas ring backfill mislukt: %s", _bf_err)

    def _calc_gas_fib(self) -> list:
        """Bereken m³-verbruik en gemiddeld verbruik/uur voor fibonacci-intervallen.
        Resultaat: [{"hours": int, "m3": float|None, "rate_m3h": float|None}, ...]
        FIX 3: validatie en debug logging toegevoegd.
        """
        FIB_HOURS = [1, 2, 3, 5, 8, 13, 21]
        ring = self._gas_ring
        now_ms = int(time.time() * 1000)
        current = ring[-1] if ring else None

        # FIX 3: Log ring-buffer status voor diagnose (alleen als er weinig data is)
        if len(ring) < 5:
            _LOGGER.warning(
                "GasAnalyzer fibonacci: ring-buffer heeft maar %d punten — "
                "wacht op meer P1-gas meetpunten (gasmeters pulsen soms slechts 1x/uur). "
                "Oldest: %s, Newest: %s",
                len(ring),
                str(ring[0]) if ring else "leeg",
                str(ring[-1]) if ring else "leeg",
            )
            return [{"hours": h, "m3": None, "rate_m3h": None, "debug": "te weinig data"} for h in FIB_HOURS]

        result = []
        for hours in FIB_HOURS:
            target_ts = now_ms - hours * 3_600_000
            # FIX 3: zoek het punt dat het dichtst bij de doeltijd ligt
            # maar wees strenger: het punt mag niet verder dan 50% van het interval afwijken
            max_deviation_ms = hours * 3_600_000 * 0.5
            best = None
            for pt in ring:
                dev = abs(pt["ts"] - target_ts)
                if dev > max_deviation_ms:
                    continue
                if best is None or dev < abs(best["ts"] - target_ts):
                    best = pt
            if best is None or current is None or best is current:
                result.append({"hours": hours, "m3": None, "rate_m3h": None,
                                "debug": f"geen punt binnen {hours*0.5:.0f}u van {hours}u grens"})
                continue
            consumed = max(0.0, current["val"] - best["val"])
            actual_h = (current["ts"] - best["ts"]) / 3_600_000
            if actual_h < 0.1:
                result.append({"hours": hours, "m3": None, "rate_m3h": None, "debug": "tijdsverschil te klein"})
                continue
            # FIX 3: sanity check — gasverbruik mag niet negatief zijn of onrealistisch hoog
            if consumed < 0 or consumed > 50:
                _LOGGER.warning("GasAnalyzer fibonacci %dh: onrealistisch verbruik %.3f m³ — skip", hours, consumed)
                result.append({"hours": hours, "m3": None, "rate_m3h": None, "debug": "onrealistisch verbruik"})
                continue
            rate = round(consumed / actual_h, 4) if actual_h > 0.01 else 0.0
            result.append({"hours": hours, "m3": round(consumed, 4), "rate_m3h": rate})
        _LOGGER.debug("GasAnalyzer fibonacci: %d van %d intervallen berekend (ring=%d punten)",
                      sum(1 for r in result if r["m3"] is not None), len(FIB_HOURS), len(ring))
        return result

    def _calc_gas_fib_and_update_max(self) -> list:
        """Bereken fibonacci gasflow én update de geleerde maximale flow via EMA.
        v4.6.574: geen hardcoded max — de balk in JS schaalt op de geleerde piek.
        """
        fib = self._calc_gas_fib()
        fib_1h = next((f for f in fib if f.get("hours") == 1), None)
        if fib_1h:
            rate = fib_1h.get("rate_m3h")
            if rate is not None and rate > 0:
                if rate > self._gas_rate_max_m3h:
                    # Nieuwe piek: EMA trekt max omhoog (traag)
                    self._gas_rate_max_m3h = (
                        self._GAS_RATE_EMA_ALPHA * rate
                        + (1 - self._GAS_RATE_EMA_ALPHA) * self._gas_rate_max_m3h
                    )
                    # Maar nooit lager dan de echte meting
                    self._gas_rate_max_m3h = max(self._gas_rate_max_m3h, rate)
        return fib

    def _read_gas_price(self) -> float:
        """Lees gasprijs van dynamische sensor of fall back naar vaste config waarde."""
        eid = self._config.get("gas_price_sensor", "")
        if eid:
            st = self.hass.states.get(eid)
            if st and st.state not in ("unavailable", "unknown", "", None):
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    pass
        return float(self._config.get("gas_price_eur_m3") or 1.25)

    async def _async_read_gas_at_midnight(self) -> Optional[float]:
        """Lees gasstand op middernacht vandaag uit HA recorder statistics.
        
        Gebruikt voor het berekenen van dag_m3 na een herstart.
        Geeft None terug als recorder niet beschikbaar is.
        """
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period
            from homeassistant.util import dt as dt_util
            import datetime as _dt

            # Gas entiteit
            _eid = self._config.get("gas_sensor", "")
            if not _eid:
                # Probeer cloudems gasstand sensor
                _eid = "sensor.cloudems_gasstand"

            now = dt_util.now()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Zoek 2 uur rond middernacht
            start = midnight - _dt.timedelta(hours=1)
            end   = midnight + _dt.timedelta(hours=2)

            _instance = get_instance(self.hass)
            stats = await _instance.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                end,
                {_eid},
                "hour",
                None,
                {"state", "mean"},
            )

            if not stats or _eid not in stats or not stats[_eid]:
                return None

            # Neem de waarde die het dichtst bij middernacht ligt
            best = None
            best_diff = float('inf')
            for row in stats[_eid]:
                ts = row.get("start")
                if ts is None:
                    continue
                diff = abs((ts - midnight).total_seconds())
                val  = row.get("state") or row.get("mean")
                if diff < best_diff and val is not None:
                    best_diff = diff
                    best = float(val)

            return best
        except Exception as _exc:
            _LOGGER.debug("CloudEMS: gas midnight recorder fout (niet kritiek): %s", _exc)
            return None

    def _read_gas_sensor(self) -> Optional[float]:
        """Read standalone gas sensor (m³) when P1 reader is not active.
        
        Probeert meerdere vormen:
        1. state direct als float (meest gebruikelijk bij DSMR P1)
        2. attribute 'value' of 'gas_m3' of 'total' als state niet bruikbaar is
        3. Als de geconfigureerde sensor een energy-sensor is met TOTAL_INCREASING
        """
        entity_id = self._config.get(CONF_GAS_SENSOR, "")
        if not entity_id:
            return None
        state = self._safe_state(entity_id)
        if state is None:
            return None
        raw = state.state
        if raw not in ("unavailable", "unknown", "", None):
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        # Fallback: probeer bekende attribuutnamen
        for attr_key in ("value", "gas_m3", "total", "last_period", "current_period"):
            attr_val = state.attributes.get(attr_key)
            if attr_val is not None:
                try:
                    val = float(attr_val)
                    if val > 0:
                        _LOGGER.debug("_read_gas_sensor: waarde via attribuut %s=%s", attr_key, val)
                        return val
                except (ValueError, TypeError):
                    pass
        # Nog een fallback: als state == 0.0 maar de sensor is van het type gas,
        # geef dan toch 0.0 terug zodat gas_analysis in ieder geval actief blijft.
        try:
            return float(state.state) if state.state not in ("unavailable", "unknown", "", None) else None
        except (ValueError, TypeError):
            return None

    async def _async_check_gas_dhw_hint(self) -> None:
        """v4.5.88: Detecteer of gas waarschijnlijk gebruikt wordt voor warm water (DHW)
        terwijl de gebruiker has_gas_heating=False heeft op zijn boiler(s).

        Signalen:
          1. Gas sensor aanwezig én gasverbruik > 0 (DSMR of standalone sensor)
          2. Geen enkele boiler heeft has_gas_heating=True ingesteld
          3. Zomer (maand 5-9): CV staat bijna zeker uit → gas = DHW of koken
             of: buitentemp > 18°C en er is toch significant gasverbruik vandaag
          4. NILM heeft een cv_ketel ontdekt maar er is geen elektrische boiler geconfigureerd

        Stuurt één keer per 14 dagen een persistent_notification als hint.
        Nooit als de gebruiker al has_gas_heating=True heeft ingesteld.
        """
        import datetime as _dt_dhw

        try:
            # Al een hint gestuurd in de afgelopen 14 dagen?
            _today = str(_dt_dhw.date.today())
            if self._gas_dhw_hint_sent:
                try:
                    _sent = _dt_dhw.date.fromisoformat(self._gas_dhw_hint_sent)
                    if (_dt_dhw.date.today() - _sent).days < 14:
                        return
                except ValueError:
                    pass

            # Zijn er al boilers met has_gas_heating="yes" of "no"? Dan weet de gebruiker het al.
            _boiler_cfgs = self._config.get("boiler_configs", [])
            _boiler_cfgs += [b for g in self._config.get("boiler_groups", []) for b in g.get("boilers", [])]
            if any(bc.get("has_gas_heating") in ("yes", "no") for bc in _boiler_cfgs):
                return

            # Heeft de installatie überhaupt gas?
            _gas_m3_total = (self._data or {}).get("p1_data", {}).get("gas_m3_total") or 0.0
            if _gas_m3_total <= 0:
                # Geen P1 gas — probeer standalone gas sensor
                _gas_m3_total = self._read_gas_sensor() or 0.0
            if _gas_m3_total <= 0:
                return  # geen gassensor → kunnen niets detecteren

            # Signaal 1: Zomermaanden (mei-sept) → CV bijna zeker uit, gas = DHW/koken
            _month = _dt_dhw.date.today().month
            _is_summer = 5 <= _month <= 9

            # Signaal 2: Buitentemp > 18°C én gasverbruik vandaag > 0.1 m³
            _gas_today = (self._data or {}).get("gas_analysis", {}).get("gas_m3_today", 0.0)
            _outside_eid = self._config.get("outside_temp_entity", "")
            _outside_c = self._read_state(_outside_eid) if _outside_eid else None
            _warm_buiten = _outside_c is not None and float(_outside_c) > 18.0

            # Signaal 3: NILM heeft cv_ketel ontdekt (gas CV aanwezig in huis)
            _nilm_devices = self._nilm.get_devices() if self._nilm else []
            _cv_in_nilm = any(
                getattr(d, "device_type", "") == "cv_ketel" or "cv" in getattr(d, "label", "").lower()
                for d in _nilm_devices
            )

            # Signaal 4: Geen elektrische boiler in config maar wel gas
            _has_electric_boiler = len(_boiler_cfgs) > 0

            # Beslissing: stuur hint als minstens 2 signalen positief zijn
            _score = sum([
                _is_summer and _gas_today > 0.05,   # zomer + gasverbruik vandaag
                _warm_buiten and _gas_today > 0.1,   # warm buiten + toch gas
                _cv_in_nilm,                          # CV ketel ontdekt via NILM
                not _has_electric_boiler and _gas_today > 0.1,  # geen el. boiler maar gas
            ])

            if _score < 1:
                return

            # Bouw de reden op
            _redenen = []
            if _is_summer and _gas_today > 0.05:
                _redenen.append(f"gasverbruik in de zomer ({_gas_today:.2f} m³ vandaag, maand {_month})")
            if _warm_buiten and _gas_today > 0.1:
                _redenen.append(f"buitentemp {_outside_c:.0f}°C — CV staat waarschijnlijk uit")
            if _cv_in_nilm:
                _redenen.append("CloudEMS heeft een CV-ketel herkend in uw installatie")
            if not _has_electric_boiler and _gas_today > 0.1:
                _redenen.append("geen elektrische boiler geconfigureerd, maar wel gasverbruik")

            _msg = (
                "☑️ **CloudEMS tip: Gas voor warm water?**\n\n"
                f"CloudEMS ziet gasverbruik terwijl er geen CV-verwarming nodig is. "
                f"Mogelijk gebruikt u gas voor warm tapwater (boiler/geiser).\n\n"
                f"**Gedetecteerd:**\n"
                + "\n".join(f"- {r}" for r in _redenen)
                + "\n\n"
                "Als u een **gasgestookte boiler** heeft voor warm water, zet dan bij de "
                "boiler-instellingen **'CV-ketel aanwezig (gas)'** aan. CloudEMS houdt dan "
                "rekening met de gasprijs bij de keuze om de elektrische boiler al dan niet "
                "bij te sturen.\n\n"
                "_U hoeft niets te doen als u alleen een elektrische boiler heeft._"
            )

            self.hass.components.persistent_notification.async_create(
                message=_msg,
                title="💧 CloudEMS — Gasverbruik voor warm water?",
                notification_id="cloudems_gas_dhw_hint",
            )
            self._gas_dhw_hint_sent = _today
            _LOGGER.info(
                "CloudEMS DHW-hint gestuurd (score=%d, redenen=%s)", _score, _redenen
            )

        except Exception as _dhw_err:
            _LOGGER.debug("Gas DHW hint detectie fout: %s", _dhw_err)

    def _collect_multi_battery_data(self) -> list:
        """Collect and self-learn stats for all configured batteries."""
        configs = self._config.get(CONF_BATTERY_CONFIGS, [])

        if not configs:
            legacy_pwr = self._config.get(CONF_BATTERY_SENSOR, "")
            legacy_soc = self._config.get("battery_soc_entity", "")
            if legacy_pwr or legacy_soc:
                configs = [{"power_sensor": legacy_pwr, "soc_sensor": legacy_soc, "label": "Batterij 1"}]

        results = []
        for cfg in configs:
            eid = cfg.get("power_sensor", "")
            soc_eid = cfg.get("soc_sensor", "")
            label = cfg.get("label", "Batterij")

            raw_power = self._read_state(eid) if eid else None
            power_w = self._calc.to_watts(eid, raw_power) if raw_power is not None else None
            soc_pct = self._read_state(soc_eid) if soc_eid else None

            # v4.5.66: Fallback via BatteryProviderRegistry (provider-onafhankelijk).
            # Werkt voor Zonneplan, Tibber Volt, Eneco, en toekomstige providers.
            _bat_type = cfg.get("battery_type", "")
            if (soc_pct is None or power_w is None) and getattr(self, "_battery_providers", None):
                for _bpx in self._battery_providers.available_providers:
                    if _bpx.is_available and (not _bat_type or _bpx.provider_id == _bat_type
                                               or _bat_type in ("provider", "cloud")):
                        _bpx_st = _bpx.read_state()
                        if soc_pct is None and _bpx_st.soc_pct is not None:
                            soc_pct = _bpx_st.soc_pct
                        if power_w is None and _bpx_st.power_w is not None:
                            power_w = _bpx_st.power_w
                        break

            # v4.5.66: BatterySocLearner — zelflerend SOC / capaciteit / vermogen
            # Persisteert over herstarts via HA Store.
            _bsl_key  = eid or label   # gebruik label als power_sensor leeg is
            _bsl_mode = None
            # Lees battery_mode van de provider als beschikbaar (provider-onafhankelijk)
            if getattr(self, "_battery_providers", None):
                for _bpx2 in self._battery_providers.available_providers:
                    if _bpx2.is_available:
                        try:
                            _bsl_mode = _bpx2.read_state().active_mode
                        except Exception as _exc_ignored:
                            _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)
                        break
            _bsl = getattr(self, "_battery_soc_learner", None)
            _bsl_result = None
            if _bsl is not None:
                try:
                    _bsl_result = _bsl.observe(
                        entity_id    = _bsl_key,
                        power_w      = power_w,
                        dt_s         = 10.0,   # CloudEMS coordinator-interval
                        soc_pct      = soc_pct,
                        battery_mode = _bsl_mode,
                    )
                except Exception as _bsl_err:
                    _LOGGER.debug("BatterySocLearner observe fout: %s", _bsl_err)

            # Geconfigureerde waarden hebben prioriteit; geleerde waarden vullen aan
            capacity_kwh    = float(cfg.get("capacity_kwh", 0))
            max_charge_w    = float(cfg.get("max_charge_w", 0))
            max_discharge_w = float(cfg.get("max_discharge_w", 0))

            if _bsl_result is not None:
                # Capaciteit: geconfigureerd heeft voorrang, anders geleerd
                if not capacity_kwh and _bsl_result.capacity_kwh:
                    capacity_kwh = _bsl_result.capacity_kwh
                # Vermogen: geconfigureerd heeft voorrang, anders geleerd
                if not max_charge_w and _bsl_result.max_charge_w:
                    max_charge_w = _bsl_result.max_charge_w
                if not max_discharge_w and _bsl_result.max_discharge_w:
                    max_discharge_w = _bsl_result.max_discharge_w
                # SOC: als sensor None was maar learner een schatting heeft
                if soc_pct is None and _bsl_result.soc_pct is not None:
                    soc_pct = _bsl_result.soc_pct

            results.append({
                "label":            label,
                "entity_id":        eid,
                "power_w":          round(power_w, 1) if power_w is not None else None,
                "soc_pct":          round(soc_pct, 1) if soc_pct is not None else None,
                "capacity_kwh":     capacity_kwh,
                "estimated_capacity_kwh": round(_bsl_result.capacity_kwh, 2) if _bsl_result and _bsl_result.capacity_kwh else 0.0,
                "capacity_cycles":        (getattr(self, "_battery_soc_learner", None).get_diagnostics(eid).get("capacity_cycles", 0) if getattr(self, "_battery_soc_learner", None) else 0),
                "capacity_cycles_needed": 3,   # MIN_CAP_CYCLES
                "max_charge_w":     round(max_charge_w, 0),
                "max_discharge_w":  round(max_discharge_w, 0),
                "learned_max_charge_w":    round(_bsl_result.max_charge_w, 0) if _bsl_result else 0.0,
                "learned_max_discharge_w": round(_bsl_result.max_discharge_w, 0) if _bsl_result else 0.0,
                "soc_inferred":     bool(_bsl_result and _bsl_result.inferred),
                "soc_confidence":   round(_bsl_result.confidence, 3) if _bsl_result else 0.0,
                "soc_source":       _bsl_result.source if _bsl_result else "unknown",
                "capacity_source":  _bsl_result.capacity_source if _bsl_result else "none",
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

        # EV-lader vermogen (optioneel — voor NILM-filter en surplus-bepaling)
        ev_eid  = cfg.get("ev_charger_entity", "") or cfg.get("ev_power_sensor", "")
        ev_w    = 0.0
        if ev_eid:
            raw_ev = self._read_state(ev_eid)
            if raw_ev is not None:
                ev_w = abs(self._calc.to_watts(ev_eid, raw_ev) or 0.0)

        # Warmtepomp elektrisch vermogen (optioneel — voor NILM-filter en COP)
        hp_eid  = cfg.get("heat_pump_power_entity", "")
        hp_w    = 0.0
        if hp_eid:
            raw_hp = self._read_state(hp_eid)
            if raw_hp is not None:
                hp_w = abs(self._calc.to_watts(hp_eid, raw_hp) or 0.0)

        # v4.5.6: EMA-smoothing verwijderd — de EnergyBalancer handelt stale
        # sensoren af via Kirchhoff-schatting. Ruwe sensorwaarden zijn leidend.
        # Interval-tracking voor diagnostics loopt nu via de balancer zelf.

        return {
            "grid_power":       grid_power or 0.0,
            "import_power":     import_w   or 0.0,
            "export_power":     export_w   or 0.0,
            "solar_power":      solar_w,
            "ev_power":         ev_w,
            "heat_pump_power":  hp_w,
        }

    # ── Centrale energiestroom-helpers ────────────────────────────────────────
    # Eén plek voor alle energieberekeningen zodat tekens en formules consistent zijn.
    #
    # Tekens-conventie (doorlopend in de gehele coordinator):
    #   grid_power  : positief = import van net, negatief = export naar net
    #   solar_power : altijd positief (omvormer productie)
    #   battery_w   : positief = laden (batterij neemt stroom op)
    #                 negatief = ontladen (batterij levert stroom)
    #
    # Afgeleid:
    #   import_w    = max(0, grid_power)      netto netimport
    #   export_w    = max(0, -grid_power)     netto teruglevering
    #   discharge_w = max(0, -battery_w)      batterij levert aan huis
    #   charge_w    = max(0,  battery_w)      batterij neemt stroom op
    #
    # Energiebalans huis (Kirchhoff):
    #   house_load = solar + import - export + discharge - charge
    #              = solar + grid_power - battery_w       (netto formule)
    #
    # PV-surplus (alleen echte zonne-overschot, geen batterij-ontlading):
    #   pv_surplus = max(0, solar - import - charge)
    #             = max(0, solar - max(0, grid) - max(0, battery_w))
    #   (= hoeveel PV naar het net of batterij gaat boven huis-gebruik)

    @staticmethod
    def _calc_house_load(solar_w: float, grid_w: float, battery_w: float) -> float:
        """Elektrisch huisverbruik in Watt (Kirchhoff elektrisch).

        solar_w   : PV productie (altijd >= 0)
        grid_w    : netflow (positief=import, negatief=export)
        battery_w : batterijflow (positief=laden, negatief=ontladen)

        Noot: gasverbruik valt buiten deze berekening — gas is een aparte
        energiedrager en wordt in p1_data/gas_analysis apart bijgehouden.
        EV en warmtepomp zijn al verdisconteerd in grid_w (ze verbruiken stroom
        uit het net of van PV, zichtbaar in de netmeting).
        """
        return max(0.0, solar_w + grid_w - battery_w)

    @staticmethod
    def _calc_pv_surplus(solar_w: float, grid_w: float, battery_w: float) -> float:
        """Echt PV-overschot in Watt — alleen zonne-energie, geen batterij-ontlading.

        PV-surplus = zonne-energie die naar het net gaat OF de batterij in gaat.
        Formule: surplus = max(0, solar - house_ex_battery)
                         = max(0, solar - (solar + grid - battery) + max(0, -battery))
        Vereenvoudigd:
          - Als batterij laadt (battery_w > 0): surplus = max(0, -grid_w - battery_w + solar ... )
            eigenlijk: wat solar produceert minus wat huis verbruikt exclusief batterij
          - Als batterij ontlaadt (battery_w < 0): ontlading is geen surplus

        Praktisch:
          export_w  = max(0, -grid_w)          → teruglevering aan net
          charge_w  = max(0, battery_w)         → laden van batterij via PV
          surplus   = max(0, export_w + charge_w)   maar nooit groter dan solar
        """
        export_w  = max(0.0, -grid_w)           # teruglevering (positief)
        charge_w  = max(0.0, battery_w)          # laden via PV (positief)
        raw = export_w + charge_w
        # Surplus kan nooit groter zijn dan totale PV-productie
        return min(raw, solar_w)

    def _calc_energy_demand(self, data: dict, price_info: dict) -> dict:
        """Bereken energievraag per subsysteem en retourneer als dict voor sensor."""
        if self._energy_demand_calc is None:
            return {}
        try:
            result = self._energy_demand_calc.calculate(
                data        = data,
                price_info  = price_info,
                config      = self._config,
                boiler_ctrl = self._boiler_ctrl,
                zone_climate= getattr(self, "_zone_climate", None),
            )
            return result.to_sensor_dict()
        except Exception as e:
            _LOGGER.debug("EnergyDemand berekening fout: %s", e)
            return {}

    @staticmethod
    def _calc_self_consumption(solar_w: float, export_w: float) -> tuple[float, float]:
        """Zelfconsumptie- en zelfvoorzieningsratio (0-100%).

        Returns: (selfcons_pct, selfsuff_pct)
          selfcons_pct: welk deel van PV gaat direct het huis in
          selfsuff_pct: welk deel van huis-verbruik van eigen PV
        """
        self_use_w = max(0.0, solar_w - export_w)
        selfcons_pct = round((self_use_w / solar_w * 100) if solar_w > 10 else 0.0, 1)
        return selfcons_pct, self_use_w

    def _discover_voltage_sensors(self) -> dict[str, list[str]]:
        """Autodiscover spanning-sensoren per fase vanuit omvormers en andere devices.

        Selectiecriteria (veilig, breed):
        - unit_of_measurement == 'V'
        - waarde in realistisch netspanningsbereik (195 – 265 V)
        - entity_id bevat 'voltage' of 'spanning' (case-insensitive)
        - GEEN cloudems eigen sensoren (filter op 'cloudems')

        Fase-toewijzing vanuit entity_id (bijv. 'grid_voltage_l1' → L1).
        Als geen fase detecteerbaar: sensor geldt voor alle actieve fasen.

        Returns: {'L1': ['sensor.abc', ...], 'L2': [...], 'L3': [...]}
        """
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(self.hass)
        phase_count = int(self._config.get(CONF_PHASE_COUNT, 1))
        active_phases = ["L1", "L2", "L3"] if phase_count == 3 else ["L1"]

        result: dict[str, list[str]] = {ph: [] for ph in active_phases}
        seen: set[str] = set()

        # Al geconfigureerde spanning-sensoren niet nogmaals meenemen
        already: set[str] = set()
        for ph_key in (CONF_VOLTAGE_L1, CONF_VOLTAGE_L2, CONF_VOLTAGE_L3):
            eid = self._config.get(ph_key, "")
            if eid:
                already.add(eid)

        for entry in reg.entities.values():
            eid = entry.entity_id
            if not eid.startswith("sensor."):
                continue
            if "cloudems" in eid.lower():
                continue
            if eid in already or eid in seen:
                continue

            eid_lower = eid.lower()
            name_lower = (entry.original_name or "").lower()
            combined = eid_lower + " " + name_lower

            # Alleen entiteiten met 'voltage' of 'spanning' in naam/id
            if "voltage" not in combined and "spanning" not in combined:
                continue

            # Unit check via state
            state_obj = self.hass.states.get(eid)
            if not state_obj:
                continue
            uom = state_obj.attributes.get("unit_of_measurement", "")
            if uom != "V":
                continue

            # Spanningsbereik check
            try:
                val = float(state_obj.state)
            except (ValueError, TypeError):
                continue
            if not (195.0 <= val <= 265.0):
                continue

            seen.add(eid)

            # Fase detectie
            assigned = False
            for ph in active_phases:
                ph_lower = ph.lower()     # "l1", "l2", "l3"
                ph_num   = ph[1]          # "1", "2", "3"
                if (ph_lower in eid_lower or
                        f"_{ph_num}" in eid_lower or
                        f"phase{ph_num}" in eid_lower or
                        f"phase_{ph_num}" in eid_lower or
                        f"phase {ph_num}" in name_lower):
                    result[ph].append(eid)
                    assigned = True
                    break

            if not assigned:
                # Geen fase in naam → toevoegen aan alle actieve fasen
                for ph in active_phases:
                    result[ph].append(eid)

        # v4.6.529: NILM-confirmed devices — zoek voltage-sensoren van hetzelfde HA-device
        # als een apparaat op een bevestigde fase staat (bijv. Shelly EM op L2).
        try:
            nilm_devices = getattr(self._nilm, "get_all_devices", lambda: [])()
            for dev in nilm_devices:
                confirmed_phase = getattr(dev, "phase", None)
                if not confirmed_phase or confirmed_phase not in active_phases:
                    continue
                # Zoek het HA entity_id van dit apparaat
                dev_eid = getattr(dev, "entity_id", None) or getattr(dev, "power_entity", None)
                if not dev_eid:
                    continue
                dev_entry = reg.async_get(dev_eid)
                if not dev_entry or not dev_entry.device_id:
                    continue
                # Doorzoek alle entiteiten van dit HA-device op voltagesensoren
                for other in er.async_entries_for_device(reg, dev_entry.device_id):
                    eid2 = other.entity_id
                    if not eid2.startswith("sensor."):
                        continue
                    if "cloudems" in eid2.lower() or eid2 in already or eid2 in seen:
                        continue
                    st2 = self.hass.states.get(eid2)
                    if not st2:
                        continue
                    if st2.attributes.get("device_class") != "voltage":
                        continue
                    if st2.attributes.get("unit_of_measurement") != "V":
                        continue
                    try:
                        v2 = float(st2.state)
                    except (ValueError, TypeError):
                        continue
                    if not (195.0 <= v2 <= 265.0):
                        continue
                    seen.add(eid2)
                    if eid2 not in result[confirmed_phase]:
                        result[confirmed_phase].append(eid2)
        except Exception as _nilm_v_err:
            _LOGGER.debug("CloudEMS NILM voltage discovery fout (genegeerd): %s", _nilm_v_err)

        # Log alleen als er iets gevonden is (eenmalig via cache check)
        cache_key = "_volt_discovery_logged"
        any_found = any(result[ph] for ph in active_phases)
        if any_found and not getattr(self, cache_key, False):
            setattr(self, cache_key, True)
            _LOGGER.info(
                "CloudEMS spanning-autodiscovery: %s",
                {ph: result[ph] for ph in active_phases if result[ph]},
            )

        return result

    def _get_auxiliary_voltage(self, phase: str) -> float | None:
        """Gewogen gemiddelde van autodiscovered spanning-sensoren voor deze fase.

        Geeft None terug als er geen bruikbare sensors zijn.
        """
        if not hasattr(self, "_volt_sensors_cache"):
            self._volt_sensors_cache: dict[str, list[str]] = {}
            self._volt_cache_tick: int = 0

        # Herdicover elke 60 coordinator-cycli (~10 minuten bij 10s polling)
        tick = getattr(self, "_coordinator_tick", 0)
        if tick - self._volt_cache_tick > 60 or not self._volt_sensors_cache:
            self._volt_sensors_cache = self._discover_voltage_sensors()
            self._volt_cache_tick = tick

        sensors = self._volt_sensors_cache.get(phase, [])
        readings: list[float] = []
        for eid in sensors:
            st = self.hass.states.get(eid)
            if not st or st.state in ("unavailable", "unknown", ""):
                continue
            try:
                v = float(st.state)
                if 195.0 <= v <= 265.0:
                    readings.append(v)
            except (ValueError, TypeError):
                continue

        if not readings:
            return None
        return round(sum(readings) / len(readings), 1)

    async def _process_p1_realtime(self, t) -> None:
        """v4.6.512: Realtime verwerking van een nieuw P1 telegram.

        Aangeroepen direct vanuit de P1Reader callback — buiten de 10s coordinator-cyclus.
        Verwerkt alleen de tijdkritische data:
          - Fase-stromen en -vermogens → limiter (piekschaving, fase-balans, dimmer)
          - Netto grid-vermogen → NILM (apparaatdetectie werkt beter bij hogere frequentie)
          - Grid/PV/batterij opgeslagen voor volgende coordinator-cyclus

        Geen zware berekeningen: geen prijzen, geen BDE, geen boiler, geen besluiten.
        """
        if t is None:
            return
        try:
            now = time.time()
            mains_v     = float(self._config.get(CONF_MAINS_VOLTAGE, DEFAULT_MAINS_VOLTAGE_V))
            phase_count = int(self._config.get(CONF_PHASE_COUNT, 1))
            phases      = ["L1", "L2", "L3"] if phase_count == 3 else ["L1"]

            # -- Fase-stromen en -vermogens direct naar limiter --
            phase_map = {
                "L1": (getattr(t, "power_l1_w", 0.0),      getattr(t, "power_l1_export_w", 0.0), getattr(t, "current_l1", None), getattr(t, "voltage_l1", None)),
                "L2": (getattr(t, "power_l2_w", 0.0),      getattr(t, "power_l2_export_w", 0.0), getattr(t, "current_l2", None), getattr(t, "voltage_l2", None)),
                "L3": (getattr(t, "power_l3_w", 0.0),      getattr(t, "power_l3_export_w", 0.0), getattr(t, "current_l3", None), getattr(t, "voltage_l3", None)),
            }
            for ph in phases:
                p_imp, p_exp, cur_a, volt_v = phase_map[ph]
                if not p_imp and not p_exp and cur_a is None:
                    continue
                net_p = float(p_imp or 0.0) - float(p_exp or 0.0)
                v     = float(volt_v) if (volt_v and volt_v > 50) else mains_v

                # v4.6.530: lichtgewicht fusie — gecachede gewichten, geen leren
                if self._phase_fusion:
                    estimates = PhaseCurrentFusion.build_estimates(
                        raw_sensor_a = None,        # geen HA-sensor beschikbaar realtime
                        p1_current_a = cur_a,
                        raw_power_w  = None,        # geen dedicated sensor realtime
                        p1_power_w   = net_p if (p_imp or p_exp) else None,
                        voltage_v    = v,
                        mains_v      = mains_v,
                    )
                    signed_a = self._phase_fusion.fuse_fast(ph, estimates, net_p)
                else:
                    # Fallback originele logica
                    if cur_a is not None and abs(net_p) > 5:
                        signed_a = abs(float(cur_a)) * (1.0 if net_p >= 0 else -1.0)
                    elif cur_a is not None:
                        signed_a = float(cur_a)
                    elif abs(net_p) > 5 and v > 0:
                        signed_a = net_p / v
                    else:
                        continue

                self._limiter.update_phase(
                    phase        = ph,
                    current_a    = round(signed_a, 3),
                    power_w      = round(net_p, 1),
                    voltage_v    = round(v, 1),
                    derived_from = "p1_realtime",
                )

            # -- Sla actueel grid-vermogen op voor volgende cyclus --
            net_grid_w = (t.power_import_w or 0.0) - (t.power_export_w or 0.0)
            self._last_p1_realtime_grid_w = net_grid_w
            self._last_p1_realtime_ts     = now

            # v4.6.512: push realtime update naar HA zodat fase-sensoren direct updaten
            # Gebruik async_set_extra_state_attributes via listeners ipv volledige refresh
            for listener in list(self._listeners):
                try:
                    listener()
                except Exception:
                    pass

            # -- NILM: stuur huis-verbruik door voor apparaatdetectie --
            # v4.6.514: Bug-fix — NILM moet huis-verbruik ontvangen, niet netto grid.
            # Bij zonne-overschot springt grid negatief, waardoor NILM onterecht
            # apparaten "detecteert" of mist terwijl het PV-variatie is.
            # Huis = grid_netto + solar. Solar is langzaam (10s polled), maar die
            # fout is kleiner dan het weggooien van alle edge-informatie.
            # "GRID" bestaat niet als sleutel in _power_buffers → stil genegeerd.
            # Fix: gebruik L1 als enkelfase fallback, en huis-vermogen per fase.
            if self._nilm and not self.learning_frozen:
                try:
                    _solar_now = getattr(self, "_last_solar_w", 0.0) or 0.0
                    # Per-fase naar NILM als beschikbaar (3-fase installatie)
                    _phases_sent = 0
                    for ph in phases:
                        p_imp, p_exp, _, _ = phase_map[ph]
                        if p_imp is not None or p_exp is not None:
                            ph_grid = (p_imp or 0.0) - (p_exp or 0.0)
                            # Voeg evenredig solar toe (split over actieve fases)
                            ph_solar = _solar_now / len(phases)
                            ph_house = max(0.0, ph_grid + ph_solar)
                            self._nilm.update_power(ph, ph_house, source="p1_realtime")
                            _phases_sent += 1
                    # Enkelfase fallback: gebruik totaal huis-vermogen op L1
                    if _phases_sent == 0:
                        house_w = max(0.0, net_grid_w + _solar_now)
                        self._nilm.update_power("L1", house_w, source="p1_realtime_l1")
                except Exception:
                    pass

            # -- Sla P1 data op zodat coordinator-cyclus hem kan gebruiken --
            self._last_p1_update = now

        except Exception as _rt_err:
            _LOGGER.debug("P1 realtime verwerking fout: %s", _rt_err)

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
        # P1 per-phase data — used as fallback when no dedicated phase sensors configured.
        # p1_data is populated earlier in _gather_power_data if P1 reader is active.
        # Staleness guard: negeer P1 fallback-data ouder dan 90 seconden zodat fase-sensoren
        # 'unavailable' worden in plaats van verouderde data te blijven tonen.
        _p1_age = time.time() - getattr(self, "_last_p1_update", 0.0)
        p1_data = getattr(self, "_last_p1_data", {}) if _p1_age < 90 else {}
        if _p1_age >= 90 and getattr(self, "_last_p1_data", {}):
            _LOGGER.debug("P1 data stale (%.0fs oud) — fase-fallback uitgeschakeld", _p1_age)
        # v4.6.516: _last_p1_data slaat import op als "power_l1_import_w" (zie opbouw ~regel 3696)
        # Dit is NIET hetzelfde als P1Telegram.as_dict() → de dict-keys zijn hier leidend.
        p1_phase_power  = {"L1": "power_l1_import_w", "L2": "power_l2_import_w", "L3": "power_l3_import_w"}
        p1_phase_export = {"L1": "power_l1_export_w",  "L2": "power_l2_export_w",  "L3": "power_l3_export_w"}
        p1_phase_current= {"L1": "current_l1",          "L2": "current_l2",          "L3": "current_l3"}

        phase_export_keys = {"L1": CONF_POWER_L1_EXPORT, "L2": CONF_POWER_L2_EXPORT, "L3": CONF_POWER_L3_EXPORT}

        # v4.6.546: Verzamel fase-resultaten voor post-loop Kirchhoff-tekencheck
        _phase_signed_a:    dict = {}
        _phase_voltage:     dict = {}
        _phase_netto_p:     dict = {}
        _phase_p1_unsigned: dict = {}

        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]

            # ── Ruwe meetwaarden ophalen ──────────────────────────────────────
            raw_a = self._read_state(cfg.get(amp_key, ""))

            _volt_eid = cfg.get(volt_key, "") or ""
            if "cloudems" in _volt_eid.lower():
                raw_v = None
            else:
                raw_v = self._read_state(_volt_eid)
            raw_p = self._read_state(cfg.get(pwr_key, ""))

            # Spanning-fallback: P1 (DSMR5) → omvormer/NILM autodiscovery → EMA → mains
            if raw_v is None or raw_v < 195.0:
                p1_v = p1_data.get(f"voltage_{ph.lower()}")
                if p1_v and 195.0 <= float(p1_v) <= 265.0:
                    raw_v = float(p1_v)
                else:
                    aux_v = self._get_auxiliary_voltage(ph)
                    if aux_v is not None:
                        raw_v = aux_v
                    else:
                        raw_v = self._limiter.get_voltage_ema(ph) or mains_v

            # Netto vermogen: exportsensor aftrekken indien geconfigureerd
            exp_eid = cfg.get(phase_export_keys.get(ph, ""), "")
            if exp_eid and raw_p is not None:
                raw_exp = self._read_state(exp_eid)
                if raw_exp is not None:
                    try:
                        raw_p = self._calc.to_watts(pwr_key, raw_p) - \
                                self._calc.to_watts(exp_eid, raw_exp)
                    except Exception as _exc_ignored:
                        _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)

            # P1 per-fase data
            p1_a_raw  = p1_data.get(p1_phase_current[ph])
            p1_a      = float(p1_a_raw) if p1_a_raw is not None else None
            p1_imp    = p1_data.get(p1_phase_power[ph])
            p1_exp_w  = p1_data.get(p1_phase_export[ph], 0.0) or 0.0
            p1_net_w  = float(p1_imp) - float(p1_exp_w) if p1_imp is not None else None

            # raw_p in Watt normaliseren (kan kW zijn bij sommige meters)
            if raw_p is not None:
                raw_p = self._calc.to_watts(pwr_key, raw_p)

            # ── v4.6.546: Zelflerend fusie model ─────────────────────────────
            # Bouw alle schattingen op en laat het model een gewogen gemiddelde
            # berekenen op basis van historische betrouwbaarheid per methode.
            voltage_for_fusion = float(raw_v) if raw_v else mains_v
            netto_p = raw_p if raw_p is not None else p1_net_w

            if self._phase_fusion:
                estimates = PhaseCurrentFusion.build_estimates(
                    raw_sensor_a  = raw_a,
                    p1_current_a  = p1_a,
                    raw_power_w   = raw_p,
                    p1_power_w    = p1_net_w,
                    voltage_v     = voltage_for_fusion,
                    mains_v       = mains_v,
                )
                signed_a = self._phase_fusion.fuse_and_learn(ph, estimates, netto_p)
            else:
                # Fallback als fusie niet geïnitialiseerd is
                if raw_p is not None:
                    signed_a = (raw_p / voltage_for_fusion) * (1.0 if (netto_p or 0) >= 0 else -1.0)
                elif raw_a is not None:
                    signed_a = abs(raw_a) * (1.0 if (netto_p or 0) >= 0 else -1.0)
                else:
                    signed_a = 0.0

            # Bewaar voor post-loop Kirchhoff-tekencheck (v4.6.546)
            _phase_signed_a[ph]     = signed_a
            _phase_voltage[ph]      = voltage_for_fusion
            _phase_netto_p[ph]      = netto_p
            # Vlag: alleen P1 unsigned stroom beschikbaar, geen vermogensrichting
            _phase_p1_unsigned[ph]  = (p1_a is not None and netto_p is None
                                       and raw_p is None and p1_net_w is None)

            _LOGGER.debug(
                "CloudEMS fase [%s]: signed_a=%.3f (raw_a=%s raw_p=%s p1_a=%s p1_p=%s v=%.0f)",
                ph, signed_a, raw_a, raw_p, p1_a, p1_net_w, voltage_for_fusion,
            )

            self._limiter.update_phase(
                phase            = ph,
                current_a        = round(signed_a, 3),
                power_w          = round(netto_p or (signed_a * voltage_for_fusion), 1),
                voltage_v        = round(voltage_for_fusion, 1),
                derived_from     = "fusion",
                # v4.6.548: broninformatie voor tooltip
                source_entity_a  = cfg.get(phase_conf[ph][0], "") or "p1",
                source_entity_p  = cfg.get(phase_conf[ph][2], "") or ("p1" if p1_net_w is not None else ""),
                raw_a            = float(raw_a) if raw_a is not None else 0.0,
                raw_p            = float(raw_p) if raw_p is not None else 0.0,
                p1_a             = float(p1_a)  if p1_a  is not None else 0.0,
                p1_net_w         = float(p1_net_w) if p1_net_w is not None else 0.0,
            )

            # ── v2.2: ESPHome NILM-meter features uitlezen ───────────────────
            # Als de gebruiker een DIY ESPHome-meter heeft geconfigureerd,
            # lees dan power factor en inrush uit als extra NILM-features.
            # v4.4.1: ook reactief vermogen (Q) en THD% — optioneel, None als afwezig.
            if self._config.get(CONF_DSMR_SOURCE) == DSMR_SOURCE_ESPHOME:
                def _esp_float(key: str) -> Optional[float]:
                    eid = self._config.get(key, "")
                    if not eid:
                        return None
                    val = self._read_state(eid)
                    try:
                        return float(val) if val is not None else None
                    except (TypeError, ValueError):
                        return None
                self._esp_power_factor_l1 = _esp_float(CONF_ESPHOME_POWER_FACTOR_L1)
                self._esp_power_factor_l2 = _esp_float(CONF_ESPHOME_POWER_FACTOR_L2)
                self._esp_power_factor_l3 = _esp_float(CONF_ESPHOME_POWER_FACTOR_L3)
                self._esp_inrush_peak_l1  = _esp_float(CONF_ESPHOME_INRUSH_L1)
                self._esp_inrush_peak_l2  = _esp_float(CONF_ESPHOME_INRUSH_L2)
                self._esp_inrush_peak_l3  = _esp_float(CONF_ESPHOME_INRUSH_L3)
                self._esp_rise_time_l1    = _esp_float(CONF_ESPHOME_RISE_TIME_L1)
                self._esp_rise_time_l2    = _esp_float(CONF_ESPHOME_RISE_TIME_L2)
                self._esp_rise_time_l3    = _esp_float(CONF_ESPHOME_RISE_TIME_L3)
                # Reactief vermogen Q (VAR) — None als ESP32-firmware dit niet meet
                self._esp_reactive_l1     = _esp_float(CONF_ESPHOME_REACTIVE_L1)
                self._esp_reactive_l2     = _esp_float(CONF_ESPHOME_REACTIVE_L2)
                self._esp_reactive_l3     = _esp_float(CONF_ESPHOME_REACTIVE_L3)
                # THD% — None als ESP32-firmware geen FFT/THD uitrekent
                self._esp_thd_l1          = _esp_float(CONF_ESPHOME_THD_L1)
                self._esp_thd_l2          = _esp_float(CONF_ESPHOME_THD_L2)
                self._esp_thd_l3          = _esp_float(CONF_ESPHOME_THD_L3)

            # Feed NILM — v1.8: smart fallback cascade
            #
            # Priority:
            #   1. Per-phase power sensor configured & valid  → best accuracy
            #   2. No phase sensor but total grid available   → split equally per phase
            #   3. Single-phase install                       → total on L1
            #
            # This ensures NILM always gets a meaningful signal even when
            # no per-phase sensors are installed.
            resolved = {"power_w": netto_p}
            phase_pw = resolved.get("power_w")
            if phase_pw is not None:
                # v1.17.1 — Aftrekken van bekende stopcontact-vermogens per fase
                # zodat NILM alleen op het restsignaal hoeft te werken.
                # v1.22: alleen als NILM-motor actief is
                if not self._nilm_active:
                    continue
                if self._hybrid and self._hybrid_nilm_active:
                    anchored_by_phase = self._hybrid.get_anchored_power_per_phase()
                    socket_w = anchored_by_phase.get(ph, 0.0)
                    nilm_input_w = max(0.0, phase_pw - socket_w)
                    if socket_w > 10.0:
                        _LOGGER.debug(
                            "NILM %s: fase=%.0fW − stopcontact=%.0fW = restsignaal=%.0fW",
                            ph, phase_pw, socket_w, nilm_input_w,
                        )
                else:
                    nilm_input_w = phase_pw
                self._nilm.update_power(ph, nilm_input_w, source="per_phase") if not self.learning_frozen else None
                # v1.22: HMM tick — energieboekhouding per fase
                if self._nilm_hmm_active and self._hmm:
                    self._hmm.tick(ph, nilm_input_w, ts=__import__("time").time())
            # (fallback handled below after all phases are processed)

        # ── v4.6.546: Post-loop Kirchhoff-consistentiecheck ──────────────────
        # DSMR4 geeft fase-stromen UNSIGNED (altijd positief, ook bij export).
        # Als som(Li×Ui) >> grid_total (factor >2): meetinconsistentie.
        # → Schaal alle fasestromen proportioneel naar grid_total.
        # Dit vangt gevallen op waarbij de P1 stroomsensor ook interne
        # accu/omvormer stromen meet die niet op de nettometing verschijnen.
        if len(phases) > 1 and any(_phase_p1_unsigned.get(ph) for ph in phases):
            grid_total_w = data.get("grid_power")
            if grid_total_w is not None:
                phase_sum_w = sum(
                    _phase_signed_a.get(p, 0.0) * _phase_voltage.get(p, mains_v)
                    for p in phases
                )
                all_unsigned  = all(_phase_p1_unsigned.get(p, False) for p in phases)
                sum_too_large = abs(phase_sum_w) > max(abs(grid_total_w) * 2.0, 500.0)

                if all_unsigned and sum_too_large:
                    # Proportioneel schalen: verdeling blijft gelijk, totaal = grid_total
                    total_abs_a = sum(abs(_phase_signed_a.get(p, 0.0)) for p in phases)
                    if total_abs_a > 0.1:
                        for p in phases:
                            frac   = abs(_phase_signed_a.get(p, 0.0)) / total_abs_a
                            v      = _phase_voltage.get(p, mains_v)
                            corr_w = grid_total_w * frac   # teken van grid_total overgenomen
                            corr_a = corr_w / v
                            _LOGGER.debug(
                                "fase-Kirchhoff [%s]: %.2fA → %.2fA "
                                "(som=%.0fW→%.0fW, grid=%.0fW)",
                                p, _phase_signed_a[p], corr_a,
                                phase_sum_w, grid_total_w, grid_total_w,
                            )
                            _phase_signed_a[p] = corr_a
                        # Update limiter met gecorrigeerde waarden
                        for p in phases:
                            v      = _phase_voltage.get(p, mains_v)
                            corr_a = _phase_signed_a[p]
                            self._limiter.update_phase(
                                phase           = p,
                                current_a       = round(corr_a, 3),
                                power_w         = round(corr_a * v, 1),
                                voltage_v       = round(v, 1),
                                derived_from    = "fusion_kirchhoff",
                                source_entity_a = cfg.get(phase_conf[p][0], "") or "p1",
                                source_entity_p = cfg.get(phase_conf[p][2], "") or "p1",
                                raw_a           = float(_phase_p1_unsigned.get(p, 0) and _phase_signed_a.get(p, 0) or 0),
                                p1_a            = abs(_phase_signed_a.get(p, 0.0)),
                            )

        phases_with_data = []
        for ph in phases:
            amp_key, volt_key, pwr_key = phase_conf[ph]
            if self._read_state(cfg.get(amp_key,"")) is not None or \
               self._read_state(cfg.get(pwr_key,"")) is not None:
                phases_with_data.append(ph)

        if not phases_with_data and self._nilm_active:
            # No per-phase sensors at all → distribute total grid power
            total_w = data.get("grid_power", 0.0)
            n       = len(phases)
            if n > 1:
                # Equal split — better than nothing; at least the total signature is preserved
                per_phase_w = total_w / n
                for ph in phases:
                    if not self.learning_frozen:
                        self._nilm.update_power(ph, per_phase_w, source="total_split")
                    if self._nilm_hmm_active and self._hmm:
                        self._hmm.tick(ph, per_phase_w, ts=__import__("time").time())
            else:
                # Single phase — send total directly to L1
                if not self.learning_frozen:
                    self._nilm.update_power("L1", total_w, source="total_l1")
                if self._nilm_hmm_active and self._hmm:
                    self._hmm.tick("L1", total_w, ts=__import__("time").time())

    def _get_phase_pid_states(self) -> dict:
        """Return PID state for all phase controllers (from multi-inverter manager)."""
        if self._multi_inv_manager:
            status = self._multi_inv_manager.get_status()
            return status.get("phase_pids", {})
        return {}

    def _calc_pv_payback(
        self,
        pv_forecast_today_kwh: float | None,
        price_info: dict | None,
        current_price: float,
    ) -> dict:
        """
        Bereken de terugverdientijd op basis van:
          - Geleerde jaarproductie (geëxtrapoleerd uit pv_forecast)
          - Huidige EPEX-prijs + net-terugleverprijs
          - Geconfigureerde investeringskosten (pv_investment_eur in config)
        Geeft {} terug als onvoldoende data.
        """
        investment_eur = float(self._config.get("pv_investment_eur", 0))
        if investment_eur <= 0 or not self._solar_learner:
            return {}

        # Geschatte jaarproductie in kWh
        total_wp = self._solar_learner.get_total_estimated_wp()
        if total_wp <= 0:
            return {}

        # Gebruik PV-forecast om correctiefactor te berekenen t.o.v. piekwaarden
        # Aanname: NL gemiddeld ~900 vollasturen per jaar per Wp (conservatief)
        vollasturen = float(self._config.get("pv_vollasturen", 900))
        annual_kwh_est = round(total_wp / 1000.0 * vollasturen, 0)

        # Opbrengst per jaar: mix van eigen gebruik (bespaarde inkoop) + terugleving
        # Gebruik actuele prijs als proxy; terugleverprijs typisch 30% van inkoop
        if not price_info:
            return {}
        avg_price = price_info.get("average_today") or current_price or 0.25
        avg_price = max(0.05, float(avg_price))

        # Config: percentage eigen gebruik (default 60%)
        eigenverbruik_pct = float(self._config.get("pv_eigenverbruik_pct", 60)) / 100.0
        eigenverbruik_pct = max(0.1, min(1.0, eigenverbruik_pct))

        # Eigen gebruik bespaart volle inkoopprijs; overschot levert terugleverprijs op
        feed_in_price = float(self._config.get("pv_feed_in_price_eur_kwh", avg_price * 0.30))
        revenue_per_kwh = (
            eigenverbruik_pct * avg_price
            + (1.0 - eigenverbruik_pct) * feed_in_price
        )
        annual_revenue_eur = round(annual_kwh_est * revenue_per_kwh, 2)

        if annual_revenue_eur <= 0:
            return {}

        payback_years = round(investment_eur / annual_revenue_eur, 1)
        roi_10y = round((annual_revenue_eur * 10 - investment_eur) / investment_eur * 100, 1)

        return {
            "investment_eur":     investment_eur,
            "total_wp_est":       total_wp,
            "annual_kwh_est":     annual_kwh_est,
            "annual_revenue_eur": annual_revenue_eur,
            "payback_years":      payback_years,
            "roi_10y_pct":        roi_10y,
            "avg_price_used":     round(avg_price, 4),
            "eigenverbruik_pct":  round(eigenverbruik_pct * 100, 1),
        }

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

        # v4.6.442: gebruik current_display (all-in als gebruiker dat wil, anders EPEX)
        price_raw = price_info.get("current")
        price = price_info.get("current_display") or price_raw
        avg   = price_info.get("avg_today_incl_tax") if price_info.get("price_include_tax") or price_info.get("price_include_btw") else price_info.get("avg_today", 0)
        price_label = price_info.get("price_label", "€/kWh")
        if price is not None:
            if price < 0:
                tips.append(f"⚡ Negatieve prijs ({price:.4f} €/kWh {price_label}): overweeg zware lasten in te schakelen of PV te begrenzen.")
            elif price_info.get("in_cheapest_3h"):
                tips.append(f"💰 Je bent nu in de goedkoopste 3 uur (prijs {price:.4f} €/kWh {price_label}). Goed moment voor vaatwasser/boiler.")
            elif avg and price > avg * 1.5:
                tips.append(f"💸 Dure stroom: prijs {price:.4f} €/kWh is {((price/max(avg,0.001)-1)*100):.0f}% boven daaggemiddelde.")

        if solar_surplus > 500:
            # v4.6.430: als boiler geconfigureerd is, toon wat CloudEMS doet i.p.v. een actietip
            _boiler_active = False
            _boiler_tip = ""
            if getattr(self, "_boiler_ctrl", None):
                _decisions = getattr(self._boiler_ctrl, "_last_decisions", []) or []
                for _bd in _decisions:
                    _sp = _bd.get("active_setpoint_c") or _bd.get("setpoint_c", 0)
                    _on = _bd.get("want_on") or _bd.get("is_heating")
                    _lbl = _bd.get("label", "Boiler")
                    if _on and _sp:
                        _boiler_active = True
                        _boiler_tip = f"☀️ PV-surplus {solar_surplus:.0f}W: boiler '{_lbl}' wordt verwarmd naar {_sp:.0f}°C."
                        break
                    elif _sp:
                        _boiler_active = True
                        _boiler_tip = f"☀️ PV-surplus {solar_surplus:.0f}W: boiler '{_lbl}' staat klaar op {_sp:.0f}°C (setpoint)."
                        break
            if _boiler_active and _boiler_tip:
                tips.append(_boiler_tip)
            elif getattr(self, "_boiler_ctrl", None):
                # Boiler is geconfigureerd — CloudEMS beheert hem, geen handmatige tip tonen
                tips.append(f"☀️ PV-surplus {solar_surplus:.0f}W: CloudEMS stuurt je boiler automatisch aan.")
            else:
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

    async def _async_configure_lamp_automation(self) -> None:
        """Bouw lamp-automation config op vanuit wizard + HA areas."""
        try:
            cfg = self._config
            lc_cfg = cfg.get("lamp_circulation", {}) or {}
            lamp_auto_cfg = cfg.get("lamp_automation", {}) or {}
            lamp_list = lamp_auto_cfg.get("lamps", [])

            if not lamp_list:
                # Auto-ontdekking: bouw prefill op basis van HA areas
                ha_areas    = {a.id: {"name": a.name} for a in self.hass.data.get("area_registry", type("", (), {"async_list_areas": lambda s: []})()).async_list_areas() or []} if hasattr(self.hass, "data") else {}
                ha_entities = {}
                try:
                    from homeassistant.helpers import entity_registry as er
                    ent_reg = er.async_get(self.hass)
                    from homeassistant.helpers import area_registry as ar
                    area_reg = ar.async_get(self.hass)
                    ha_areas = {a.id: {"name": a.name} for a in area_reg.async_list_areas()}
                    for entry in ent_reg.entities.values():
                        if entry.entity_id.startswith("light.") and not entry.disabled:
                            ha_entities[entry.entity_id] = {
                                "name":         entry.name or entry.original_name or entry.entity_id,
                                "area_id":      entry.area_id or "",
                                "device_class": getattr(entry, "device_class", ""),
                            }
                    for entry in ent_reg.entities.values():
                        if entry.entity_id.startswith("binary_sensor.") and not entry.disabled:
                            ha_entities[entry.entity_id] = {
                                "name":         entry.name or entry.original_name or entry.entity_id,
                                "area_id":      entry.area_id or "",
                                "device_class": getattr(entry, "device_class", "") or getattr(entry, "original_device_class", "") or "",
                            }
                except Exception as _err:
                    _LOGGER.debug("LampAuto: entity/area registry niet beschikbaar: %s", _err)

                lamp_list = self._lamp_auto.auto_configure_from_ha(ha_areas, ha_entities)

            self._lamp_auto.configure(lamp_list)
            _LOGGER.info("LampAutomation: geconfigureerd met %d lampen", len(lamp_list))
        except Exception as err:
            _LOGGER.warning("LampAutomation setup fout: %s", err)

    def _async_configure_circuit_monitor(self) -> None:
        """Initialiseer circuit monitor op basis van fase-count."""
        try:
            phase_count = int(self._config.get("phase_count", 3))
            self._circuit_monitor.configure(phase_count=phase_count)
        except Exception as err:
            _LOGGER.debug("CircuitMonitor configure: %s", err)

    def _async_configure_ups(self) -> None:
        """Laad UPS configuraties vanuit wizard."""
        try:
            ups_cfgs = self._config.get("ups_systems", []) or []
            if ups_cfgs:
                self._ups_manager.configure(ups_cfgs)
        except Exception as err:
            _LOGGER.debug("UPSManager configure: %s", err)

    # ── Decision log ──────────────────────────────────────────────────────────

    def _log_decision(self, category: str, message: str, payload: dict | None = None) -> None:
        """Sla een beslissing op in de in-memory ring en schrijf naar cloudems_high.log.

        Parameters
        ----------
        category : str
            Korte categorienaam, bijv. "boiler", "battery_bde", "shutter", ...
        message  : str
            Leesbare samenvatting (ook zichtbaar in het dashboard).
        payload  : dict | None
            Alle beschikbare context. Hoe meer, hoe beter voor terugkijken.
        """
        import asyncio as _aio_ld
        _p = payload or {}

        # Altijd energie-context meesturen zodat elk beslissingsmoment zichzelf verklaart
        _ctx = {
            "solar_w":              round(float(getattr(self, "_last_solar_w",   0) or 0), 1),
            "grid_w":               round(float(getattr(self, "_last_grid_w",    0) or 0), 1),
            "battery_w":            round(float(getattr(self, "_last_battery_w", 0) or 0), 1),
            "house_w":              round(float(getattr(self, "_last_house_w",   0) or 0), 1),
            "soc_pct":              getattr(self, "_last_soc_pct", None),
            "price_eur_kwh":        round(float(getattr(self, "_last_known_price", 0) or 0), 5),
            "price_all_in_eur_kwh": round(
                float((getattr(self, "_last_price_info", None) or {}).get("current_all_in") or 0), 5
            ),
        }
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "category": category,
            "message":  message,
            **_ctx,
            **_p,  # payload mag context-velden overschrijven met nauwkeuriger waarden
        }
        self._decision_log.appendleft(entry)
        _LOGGER.debug("CloudEMS decision [%s]: %s", category, message)

        # Telemetry: anonieme beslissing registreren (geen entity_id/label)
        _tel = getattr(self, "_telemetry", None)
        if _tel is not None:
            _tel.record_decision(
                category=category,
                action=_p.get("action", category),
                reason=_p.get("reason", "")[:50],
            )

        # Schrijf naar DecisionsHistory ring buffer (JSON + sensor attribuut)
        # Alle categorieën worden opgeslagen — JS card filtert per categorie.
        # Uitgesloten: interne/technische categorieën die geen gebruikerswaarde hebben.
        _HISTORY_EXCLUDE = {"ev_pid", "p1_update"}  # clipping+solar_dim nu wél gelogd
        _hist = getattr(self, "_decisions_history", None)
        if _hist is not None and category not in _HISTORY_EXCLUDE:
            _hist.add(
                category=category,
                action=_p.get("action", category),
                reason=_p.get("reason", _p.get("human_reason", message)),
                message=message,
                extra={
                    "solar_w":    _ctx["solar_w"],
                    "grid_w":     _ctx["grid_w"],
                    "soc_pct":    _ctx["soc_pct"],
                    "price_eur":  _ctx["price_all_in_eur_kwh"],
                    "label":      _p.get("label", _p.get("entity_id", "")),
                    "action_raw": _p.get("action", ""),
                }
            )

        # Schrijf naar cloudems_decisions.log (+ mirror naar high log)
        _bk = getattr(self, "_learning_backup", None)
        if _bk is not None:
            _aio_ld.ensure_future(_bk.async_log_decision(f"decision_{category}", entry))

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_nilm_device_found(self, device: DetectedDevice, all_matches: list):
        _LOGGER.info("CloudEMS NILM: device found → %s (%.0f%%)", device.name, device.confidence*100)
        self.async_update_listeners()

    def _on_nilm_device_update(self, device: DetectedDevice):
        self.async_update_listeners()
        # v4.6.533: wiring topology + appliance health op NILM events
        try:
            _phase = getattr(device, "phase", None)
            _power = getattr(device, "power_w", 0.0)
            _is_on = getattr(device, "is_on", False)
            _dev_type = getattr(device, "device_type", "unknown")
            _dev_id   = getattr(device, "entity_id", None) or getattr(device, "name", "unknown")

            if _phase and abs(_power) > 30:
                if self._wiring_topology:
                    self._wiring_topology.record_nilm_event(
                        device_name   = _dev_id,
                        nilm_phase    = _phase,
                        power_delta_w = _power if _is_on else -_power,
                    )

            if _is_on and _power > 50:
                if self._appliance_degradation:
                    self._appliance_degradation.observe_cycle(
                        device_type = _dev_type,
                        device_id   = _dev_id,
                        power_w     = _power,
                    )
            elif not _is_on and 0 < _power < 50:
                if self._standby_drift:
                    self._standby_drift.observe_standby(
                        device_type = _dev_type,
                        device_id   = _dev_id,
                        standby_w   = _power,
                    )
        except Exception as _ne_err:
            _LOGGER.debug("NILM kwaliteitsmodules fout: %s", _ne_err)

    # ── Shutter temperatuursensor runtime discovery ───────────────────────────

    async def _async_ensure_shutter_helpers(self, shutter_configs: list) -> None:
        """Maak input_text/input_number helpers aan per rolluik via storage collection.

        Helpers worden alleen aangemaakt als ze nog niet bestaan.
        Werkt ook als HA nog niet volledig opgestart is: planning via async_at_start.
        """
        async def _do_create(_now=None) -> None:  # noqa: ANN001
            try:
                from homeassistant.components.input_text   import DOMAIN as IT_DOMAIN, InputTextStorageCollection
                from homeassistant.components.input_number import DOMAIN as IN_DOMAIN, InputNumberStorageCollection
                from homeassistant.helpers.collection      import StorageCollection
            except ImportError:
                _LOGGER.debug("CloudEMS: input_text/input_number storage collection niet beschikbaar")
                return

            # Haal de storage collections op via component data
            it_comp  = self.hass.data.get(IT_DOMAIN)
            in_comp  = self.hass.data.get(IN_DOMAIN)
            it_coll  = getattr(it_comp, "collection", None) if it_comp else None
            in_coll  = getattr(in_comp, "collection", None) if in_comp else None

            for cfg_dict in shutter_configs:
                raw_id  = cfg_dict.get("entity_id", "")
                safe_id = raw_id.split(".")[-1].replace("-", "_") if raw_id else ""
                label   = cfg_dict.get("label", safe_id)
                if not safe_id:
                    continue

                night_close  = cfg_dict.get("night_close_time", "23:00")
                morning_open = cfg_dict.get("morning_open_time", "07:30")
                setpoint     = float(cfg_dict.get("default_setpoint", 20.0))

                # (domain_collection, entity_id_prefix, object_id, creation_data)
                helpers = [
                    (it_coll, IT_DOMAIN, f"cloudems_shutter_{safe_id}_night_close", {
                        "id":   f"cloudems_shutter_{safe_id}_night_close",
                        "name": f"{label} — Nacht sluiten",
                        "initial": night_close,
                        "min": 5, "max": 5,
                        "icon": "mdi:weather-night",
                        "mode": "text",
                    }),
                    (it_coll, IT_DOMAIN, f"cloudems_shutter_{safe_id}_morning_open", {
                        "id":   f"cloudems_shutter_{safe_id}_morning_open",
                        "name": f"{label} — Ochtend openen (00:00=zonsopgang)",
                        "initial": morning_open,
                        "min": 5, "max": 5,
                        "icon": "mdi:weather-sunrise",
                        "mode": "text",
                    }),
                    (in_coll, IN_DOMAIN, f"cloudems_shutter_{safe_id}_setpoint", {
                        "id":   f"cloudems_shutter_{safe_id}_setpoint",
                        "name": f"{label} — Setpoint",
                        "initial": setpoint,
                        "min": 10.0, "max": 30.0, "step": 0.5,
                        "unit_of_measurement": "°C", "mode": "slider",
                        "icon": "mdi:thermometer",
                    }),
                    (in_coll, IN_DOMAIN, f"cloudems_shutter_{safe_id}_sunrise_offset", {
                        "id":   f"cloudems_shutter_{safe_id}_sunrise_offset",
                        "name": f"{label} — Zonsopgang offset",
                        "initial": 15.0,
                        "min": -60.0, "max": 120.0, "step": 5.0,
                        "unit_of_measurement": "min", "mode": "slider",
                        "icon": "mdi:weather-sunset-up",
                    }),
                    (in_coll, IN_DOMAIN, f"cloudems_shutter_{safe_id}_away_position", {
                        "id":   f"cloudems_shutter_{safe_id}_away_position",
                        "name": f"{label} — Afwezig positie",
                        "initial": 50.0,
                        "min": 0.0, "max": 100.0, "step": 5.0,
                        "unit_of_measurement": "%", "mode": "slider",
                        "icon": "mdi:home-export-outline",
                    }),
                    (in_coll, IN_DOMAIN, f"cloudems_shutter_{safe_id}_summer_offset", {
                        "id":   f"cloudems_shutter_{safe_id}_summer_offset",
                        "name": f"{label} — Zomer correctie",
                        "initial": 1.0,
                        "min": 0.0, "max": 5.0, "step": 0.5,
                        "unit_of_measurement": "°C", "mode": "slider",
                        "icon": "mdi:weather-sunny",
                    }),
                    (in_coll, IN_DOMAIN, f"cloudems_shutter_{safe_id}_winter_offset", {
                        "id":   f"cloudems_shutter_{safe_id}_winter_offset",
                        "name": f"{label} — Winter correctie",
                        "initial": 0.5,
                        "min": 0.0, "max": 5.0, "step": 0.5,
                        "unit_of_measurement": "°C", "mode": "slider",
                        "icon": "mdi:snowflake",
                    }),
                ]

                for coll, domain, obj_id, data in helpers:
                    full_id = f"{domain}.{obj_id}"
                    if self.hass.states.get(full_id) is not None:
                        continue  # al aanwezig

                    # Probeer via storage collection
                    if coll is not None:
                        try:
                            await coll.async_create_item(data)
                            _LOGGER.debug("CloudEMS: helper aangemaakt via collection: %s", full_id)
                            continue
                        except Exception as exc:
                            _LOGGER.debug("CloudEMS: collection.async_create_item mislukt %s: %s", full_id, exc)

                    # Fallback: service call set_value / reload (werkt na HA opstart)
                    try:
                        await self.hass.services.async_call(
                            domain, "set_value" if domain == IT_DOMAIN else "set_value",
                            {"entity_id": full_id, "value": data.get("initial", "")},
                            blocking=False,
                        )
                    except Exception as _exc_ignored:
                        _LOGGER.debug("CloudEMS: exception genegeerd: %s", _exc_ignored)  # entity bestaat nog niet, skip silently

        # Uitvoeren na volledige HA-opstart zodat storage collections beschikbaar zijn
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        if self.hass.is_running:
            self.hass.async_create_task(_do_create())
        else:
            async def _on_ha_started(_event):
                await _do_create()
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

    async def _async_discover_shutter_temp_sensors(self) -> None:
        """Zoek bij opstarten naar temperatuursensoren in dezelfde ruimte als rolluiken.

        Wordt aangeroepen direct na aanmaken van ShutterController. Wijst sensoren
        toe aan rolluiken die nog geen temp_sensor hebben en ook geen zone climate
        koppeling hebben.
        """
        if not self._shutter_ctrl:
            return
        try:
            from homeassistant.helpers import entity_registry as er, area_registry as ar
            ent_reg  = er.async_get(self.hass)
            area_reg = ar.async_get(self.hass)
            for cfg in self._shutter_ctrl._configs:
                if cfg.temp_sensor or not cfg.area_id:
                    continue  # al geconfigureerd of geen ruimte bekend
                sensor = self._find_temp_sensor_in_area(cfg.area_id, ent_reg)
                if sensor:
                    self._shutter_ctrl.update_temp_sensor(cfg.entity_id, sensor)
        except Exception as exc:
            _LOGGER.debug("CloudEMS: shutter temp sensor discovery fout: %s", exc)

    async def _async_on_entity_registry_updated(self, event) -> None:
        """Luisteraar voor entity registry wijzigingen.

        Als een nieuwe temperatuursensor gekoppeld wordt aan een ruimte waar een
        rolluik zit zonder sensor, wordt deze automatisch toegewezen.
        """
        if not self._shutter_ctrl:
            return
        action = event.data.get("action")
        if action not in ("create", "update"):
            return
        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("sensor."):
            return
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)
            entry   = ent_reg.async_get(entity_id)
            if entry is None or entry.disabled:
                return
            if entry.device_class != "temperature" and entry.original_device_class != "temperature":
                return
            if not entry.area_id:
                return
            # Zoek een rolluik in dezelfde ruimte zonder sensor
            for cfg in self._shutter_ctrl._configs:
                if cfg.area_id == entry.area_id and not cfg.temp_sensor:
                    self._shutter_ctrl.update_temp_sensor(cfg.entity_id, entity_id)
                    break
        except Exception as exc:
            _LOGGER.debug("CloudEMS: entity registry handler fout: %s", exc)

    @staticmethod
    def _find_temp_sensor_in_area(area_id: str, ent_reg) -> str:
        """Geef de beste temperatuursensor in een ruimte terug (entity_id of '').

        Voorkeursvolgorde: climate current_temperature < sensor met device_class=temperature.
        We kiezen de sensor die er het meest op lijkt een kamertemperatuur te zijn
        (geen 'outdoor', 'buiten', 'external' in naam).
        """
        candidates = []
        for entry in ent_reg.entities.values():
            if entry.domain != "sensor":
                continue
            if entry.area_id != area_id:
                continue
            if entry.disabled:
                continue
            dc = entry.device_class or entry.original_device_class or ""
            if dc != "temperature":
                continue
            eid   = entry.entity_id.lower()
            label = (entry.original_name or entry.entity_id).lower()
            # Sla buiten-sensoren over
            if any(w in eid or w in label for w in ("outdoor", "buiten", "outside", "extern", "external")):
                continue
            candidates.append(entry.entity_id)
        # Geef de eerste kandidaat terug; meer verfijning kan later
        return candidates[0] if candidates else ""

    async def _write_long_term_stats(self, data: dict) -> None:
        """Schrijf key metrics naar HA long-term statistics.
        
        Hierdoor zijn alle metrics beschikbaar in InfluxDB, Grafana en
        HA energiedashboard via de standaard Statistics API.
        """
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import (
                async_import_statistics,
                StatisticData,
                StatisticMetaData,
            )
            from homeassistant.util import dt as dt_util
            import datetime
        except ImportError:
            return  # recorder niet beschikbaar

        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

        # Key metrics om te exporteren
        metrics = {
            "cloudems:solar_energy":    float(data.get("solar_power", 0) or 0) / 1000 / 6,  # W → kWh per 10min cyclus
            "cloudems:grid_import":     max(0.0, float(data.get("grid_power", 0) or 0)) / 1000 / 6,
            "cloudems:grid_export":     max(0.0, -(float(data.get("grid_power", 0) or 0))) / 1000 / 6,
            "cloudems:battery_charge":  max(0.0, float(data.get("battery_power", 0) or 0)) / 1000 / 6,
            "cloudems:battery_discharge": max(0.0, -(float(data.get("battery_power", 0) or 0))) / 1000 / 6,
            "cloudems:house_consumption": float(data.get("house_power", 0) or 0) / 1000 / 6,
        }

        # Prijs
        pi = data.get("price_info") or data.get("energy_price") or {}
        metrics["cloudems:price_all_in"] = float(pi.get("current_all_in") or pi.get("current_display") or 0)

        # SoC batterij
        bat_dec = data.get("battery_decision") or {}
        soc = None
        if bat_dec.get("soc_pct") is not None:
            soc = float(bat_dec["soc_pct"])
        if soc is not None:
            metrics["cloudems:battery_soc"] = soc

        _instance = get_instance(self.hass)
        for stat_id, value in metrics.items():
            if value is None:
                continue
            _unit = "kWh" if "energy" in stat_id or "charge" in stat_id or "discharge" in stat_id or "import" in stat_id or "export" in stat_id or "consumption" in stat_id else (
                "%" if "soc" in stat_id else
                "EUR/kWh" if "price" in stat_id else "W"
            )
            try:
                metadata = StatisticMetaData(
                    has_mean=True,
                    has_sum=("energy" in stat_id or "charge" in stat_id or "discharge" in stat_id
                             or "import" in stat_id or "export" in stat_id or "consumption" in stat_id),
                    name=stat_id.replace("cloudems:", "CloudEMS ").replace("_", " ").title(),
                    source="cloudems",
                    statistic_id=stat_id,
                    unit_of_measurement=_unit,
                )
                stat_data = [StatisticData(start=now, mean=value, sum=value if metadata.has_sum else None)]
                async_import_statistics(self.hass, metadata, stat_data)
            except Exception as _e:
                _LOGGER.debug("CloudEMS stats write fout voor %s: %s", stat_id, _e)

    async def _set_ev_current(self, ampere: float):
        entity_id = self._config.get("ev_charger_entity","")
        if not entity_id:
            return
        await self.hass.services.async_call(
            "number","set_value",{"entity_id": entity_id, "value": ampere}, blocking=False,
        )

    async def _set_solar_curtailment(self, pct: float):
        pass  # Handled by multi_inverter_manager
