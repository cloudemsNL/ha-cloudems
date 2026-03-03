"""CloudEMS DataUpdateCoordinator — v1.3.0"""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
import asyncio
import os
import time
from datetime import timedelta
from typing import Dict, List, Optional, Any

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from homeassistant.components import persistent_notification

from .const import (
    DOMAIN, UPDATE_INTERVAL_FAST,
    STORAGE_KEY_NILM_DEVICES, STORAGE_KEY_LEARNED_PROFILES,
    CONF_GRID_SENSOR, CONF_PHASE_SENSORS, CONF_SOLAR_SENSOR,
    CONF_BATTERY_SENSOR, CONF_EV_CHARGER_ENTITY,
    CONF_ENERGY_PRICES_COUNTRY, CONF_CLOUD_API_KEY,
    CONF_MAX_CURRENT_PER_PHASE, CONF_ENABLE_SOLAR_DIMMER,
    CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_MAX_CURRENT,
    EPEX_UPDATE_INTERVAL, DEFAULT_NEGATIVE_PRICE_THRESHOLD,
    CONF_PHASE_COUNT, CONF_ENERGY_TAX,
    CONF_DYNAMIC_LOADING, CONF_PHASE_BALANCE, CONF_P1_ENABLED,
    CONF_MAX_CURRENT_L1,
    CONF_INVERTER_CONFIGS, CONF_ENABLE_MULTI_INVERTER,
    ALL_PHASES,
)
from .nilm.detector import NILMDetector, DetectedDevice
from .energy.prices import EnergyPriceFetcher
from .energy.limiter import CurrentLimiter

_LOGGER = logging.getLogger(__name__)


class CloudEMSCoordinator(DataUpdateCoordinator):
    """Main coordinator for CloudEMS integration."""

    def __init__(self, hass: HomeAssistant, config: Dict):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_FAST),
        )
        self._config = config
        self._session: Optional[aiohttp.ClientSession] = None

        # Storage
        self._store_devices  = Store(hass, 1, STORAGE_KEY_NILM_DEVICES)
        self._store_profiles = Store(hass, 1, STORAGE_KEY_LEARNED_PROFILES)

        # Sub-components
        model_path = hass.config.path(".storage", "cloudems_models")
        os.makedirs(model_path, exist_ok=True)

        self._nilm = NILMDetector(
            model_path=model_path,
            api_key=config.get(CONF_CLOUD_API_KEY),
            session=None,
            on_device_found=self._on_nilm_device_found,
            on_device_update=self._on_nilm_device_update,
        )

        self._prices: Optional[EnergyPriceFetcher] = None
        self._limiter = CurrentLimiter(
            max_current_per_phase=config.get(CONF_MAX_CURRENT_PER_PHASE, DEFAULT_MAX_CURRENT),
            ev_charger_callback=self._set_ev_current,
            solar_inverter_callback=self._set_solar_curtailment,
        )

        self._pending_devices: List[DetectedDevice] = []
        self._prices_last_update: float = 0.0
        self._data: Dict = {}

        # v1.2 sub-modules
        self._dynamic_loader  = None
        self._phase_balancer  = None
        self._p1_reader       = None

        # v1.3 sub-modules
        self._solar_learner       = None
        self._multi_inv_manager   = None

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def nilm(self) -> NILMDetector:
        """Public access to NILM detector (used by sensor.py)."""
        return self._nilm

    @property
    def phase_currents(self) -> dict[str, float]:
        """Current per phase in Ampere (used by phase_limiter sub-module)."""
        return self._limiter.phase_currents

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def async_setup(self):
        """Initialize coordinator — called once at startup."""
        self._session = aiohttp.ClientSession()
        self._nilm._cloud_ai._session = self._session

        country = self._config.get(CONF_ENERGY_PRICES_COUNTRY, "NL")
        self._prices = EnergyPriceFetcher(
            country=country,
            session=self._session,
            api_key=self._config.get(CONF_CLOUD_API_KEY),
        )

        await self._load_saved_devices()
        await self._prices.update()

        cfg = self._config

        # ── v1.2: Dynamic EPEX loader ─────────────────────────────────────────
        if cfg.get(CONF_DYNAMIC_LOADING, False):
            from .energy_manager.dynamic_loader import DynamicLoader
            self._dynamic_loader = DynamicLoader(cfg, self._set_ev_current)
            _LOGGER.info("CloudEMS: DynamicLoader actief")

        # ── v1.2: Phase balancer ─────────────────────────────────────────────
        if cfg.get(CONF_PHASE_BALANCE, False):
            from .energy_manager.phase_balancer import PhaseBalancer
            self._phase_balancer = PhaseBalancer(self.hass, cfg)
            _LOGGER.info("CloudEMS: PhaseBalancer actief")

        # ── v1.2: P1 reader ──────────────────────────────────────────────────
        if cfg.get(CONF_P1_ENABLED, False):
            from .energy_manager.p1_reader import P1Reader
            self._p1_reader = P1Reader(cfg)
            await self._p1_reader.async_start()
            _LOGGER.info("CloudEMS: P1Reader gestart")

        # ── v1.3: Solar Learner + Multi-Inverter Manager ──────────────────────
        inverter_configs = cfg.get(CONF_INVERTER_CONFIGS, [])
        if inverter_configs and cfg.get(CONF_ENABLE_MULTI_INVERTER, False):
            from .energy_manager.solar_learner import SolarPowerLearner
            from .energy_manager.multi_inverter_manager import (
                MultiInverterManager, InverterControl,
            )
            self._solar_learner = SolarPowerLearner(self.hass, inverter_configs)
            await self._solar_learner.async_setup()

            controls = [
                InverterControl(
                    entity_id=inv["entity_id"],
                    control_entity=inv.get("control_entity", inv["entity_id"]),
                    label=inv.get("label", ""),
                    priority=int(inv.get("priority", 1)),
                    min_power_pct=float(inv.get("min_power_pct", 0.0)),
                )
                for inv in inverter_configs
            ]
            max_phase_a = {
                phase: float(cfg.get(f"max_current_{phase.lower()}", DEFAULT_MAX_CURRENT))
                for phase in ALL_PHASES
            }
            self._multi_inv_manager = MultiInverterManager(
                hass=self.hass,
                entry=None,  # Entry not needed — config dict used instead
                inverter_controls=controls,
                learner=self._solar_learner,
                max_phase_currents=max_phase_a,
                negative_price_threshold=float(
                    cfg.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)
                ),
            )
            await self._multi_inv_manager.async_setup()
            _LOGGER.info(
                "CloudEMS: MultiInverterManager actief (%d omvormers)", len(controls)
            )

    # ── Update loop ───────────────────────────────────────────────────────────

    async def _async_update_data(self) -> Dict:
        """Verzamel en verwerk alle energie-data."""
        try:
            data = await self._gather_power_data()
            await self._process_power_data(data)
            await self._limiter.evaluate_and_act()

            # Prijzen elk uur verversen
            if time.time() - self._prices_last_update > EPEX_UPDATE_INTERVAL:
                await self._prices.update()
                self._prices_last_update = time.time()

            # Negatieve prijs → solar dimmen
            if self._config.get(CONF_ENABLE_SOLAR_DIMMER, False):
                threshold = float(
                    self._config.get(CONF_NEGATIVE_PRICE_THRESHOLD, DEFAULT_NEGATIVE_PRICE_THRESHOLD)
                )
                is_neg = self._prices.is_negative_price(threshold) if self._prices else False
                self._limiter.set_negative_price_mode(is_neg)

            current_price = self._prices.current_price if self._prices else 0.0

            # ── v1.2: Dynamic loader ──────────────────────────────────────────
            ev_decision = None
            if self._dynamic_loader:
                solar_w   = data.get("solar_power", 0.0)
                max_a     = float(self._config.get(CONF_MAX_CURRENT_L1, DEFAULT_MAX_CURRENT))
                ev_decision = await self._dynamic_loader.async_evaluate(
                    price_eur_kwh=current_price,
                    solar_surplus_w=solar_w,
                    max_current_a=max_a,
                )

            # ── v1.2: Phase balancer ──────────────────────────────────────────
            balance_data: Dict = {}
            if self._phase_balancer:
                phase_currents = self._limiter.phase_currents
                status = await self._phase_balancer.async_check(phase_currents)
                balance_data = {
                    "imbalance_a":      status.imbalance_a,
                    "balanced":         status.balanced,
                    "overloaded_phase": status.overloaded_phase,
                    "lightest_phase":   status.lightest_phase,
                    "recommendation":   status.recommendation,
                    "phase_currents":   status.phase_currents,
                }

            # ── v1.2: P1 reader ───────────────────────────────────────────────
            p1_data: Dict = {}
            if self._p1_reader and self._p1_reader.available:
                t = self._p1_reader.latest
                p1_data = {
                    "net_power_w":       t.net_power_w,
                    "power_import_w":    t.power_import_w,
                    "power_export_w":    t.power_export_w,
                    "energy_import_kwh": t.energy_import_kwh,
                    "energy_export_kwh": t.energy_export_kwh,
                    "current_l1":        t.current_l1,
                    "current_l2":        t.current_l2,
                    "current_l3":        t.current_l3,
                    "tariff":            t.tariff,
                }

            # ── v1.3: Solar Learner ───────────────────────────────────────────
            if self._solar_learner:
                await self._solar_learner.async_update(
                    phase_currents=self._limiter.phase_currents
                )

            # ── v1.3: Multi-inverter manager ──────────────────────────────────
            inv_decisions: list = []
            if self._multi_inv_manager:
                inv_decisions = await self._multi_inv_manager.async_evaluate(
                    phase_currents=self._limiter.phase_currents,
                    current_epex_price=current_price,
                )

            # ── Kostenberekening ──────────────────────────────────────────────
            energy_tax    = float(self._config.get(CONF_ENERGY_TAX, 0.0))
            grid_power_w  = p1_data.get("net_power_w") or data.get("grid_power", 0.0)
            cost_per_hour = (grid_power_w / 1000.0) * (current_price + energy_tax)

            self._data = {
                # Basis
                "grid_power_w":  grid_power_w,
                "power_w":       grid_power_w,
                "solar_power_w": data.get("solar_power", 0.0),
                # Fasen
                "phases":        self._limiter.get_phase_summary(),
                "phase_status":  self._limiter.get_phase_summary(),   # legacy alias
                # NILM
                "nilm_devices":  [
                    {
                        "device_id":   d.device_id,
                        "name":        d.name,
                        "device_type": d.device_type,
                        "is_on":       d.is_on,
                        "power":       d.current_power,
                        "confidence":  d.confidence,
                        "confirmed":   d.confirmed,
                        "pending":     d.pending_confirmation,
                        "phase":       d.phase,
                        "energy_today": d.energy_today,
                        "source":      d.source,
                    }
                    for d in self._nilm.get_devices()
                ],
                # Prijzen
                "energy_price": {
                    "current":    current_price,
                    "min_today":  self._prices.min_price_today if self._prices else 0,
                    "max_today":  self._prices.max_price_today if self._prices else 0,
                    "avg_today":  self._prices.avg_price_today if self._prices else 0,
                    "is_negative": self._prices.is_negative_price() if self._prices else False,
                    "next_hours": self._prices.get_next_hours(6) if self._prices else [],
                },
                # EV / Solar
                "ev_current":         self._limiter.ev_charging_current,
                "solar_curtailment":  self._limiter.solar_curtailment_percent,
                "nilm_mode":          self._nilm.active_mode,
                # v1.2 toevoegingen
                "cost_eur_per_hour":  round(cost_per_hour, 4),
                "phase_balance":      balance_data,
                "p1":                 p1_data,
                "dynamic_loader": {
                    "target_current_a": ev_decision.target_current_a if ev_decision else 0,
                    "reason":           ev_decision.reason if ev_decision else "",
                    "price_eur_kwh":    ev_decision.price_eur_kwh if ev_decision else None,
                    "solar_surplus_w":  ev_decision.solar_surplus_w if ev_decision else 0,
                } if ev_decision else {},
                # v1.3 toevoegingen
                "inverter_decisions": [
                    {
                        "label":      d.label,
                        "action":     d.action,
                        "target_pct": d.target_pct,
                        "reason":     d.reason,
                    }
                    for d in inv_decisions
                ],
                "solar_learner": self._solar_learner.to_dict() if self._solar_learner else {},
                "multi_inverter": (
                    self._multi_inv_manager.get_status()
                    if self._multi_inv_manager else {}
                ),
            }
            return self._data

        except Exception as err:
            raise UpdateFailed(f"CloudEMS update fout: {err}") from err

    # ── Data gathering ────────────────────────────────────────────────────────

    async def _gather_power_data(self) -> Dict:
        """Lees vermogenswaarden uit geconfigureerde HA entiteiten."""

        def get_float(entity_id: str) -> float:
            if not entity_id:
                return 0.0
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unavailable", "unknown", None):
                try:
                    return float(state.state)
                except ValueError:
                    pass
            return 0.0

        grid_id = self._config.get(CONF_GRID_SENSOR)
        grid_power = get_float(grid_id)

        # Config flow stores per-phase sensors as flat keys: "phase_sensors_L1" etc.
        phase_power: Dict[str, float] = {}
        for phase in ALL_PHASES:
            sensor_id = self._config.get(f"{CONF_PHASE_SENSORS}_{phase}")
            phase_power[phase] = get_float(sensor_id) if sensor_id else grid_power / 3

        return {
            "grid_power":    grid_power,
            "phase_power":   phase_power,
            "solar_power":   get_float(self._config.get(CONF_SOLAR_SENSOR)),
            "battery_power": get_float(self._config.get(CONF_BATTERY_SENSOR)),
        }

    async def _process_power_data(self, data: Dict):
        """Voed vermogensdata aan NILM detector en limiter."""
        phase_power = data.get("phase_power", {})
        solar   = data.get("solar_power", 0)
        battery = data.get("battery_power", 0)

        for phase, power in phase_power.items():
            self._nilm.update_power(phase, power)
            phase_solar   = solar   / 3 if solar   else 0
            phase_battery = battery / 3 if battery else 0
            self._limiter.update_phase(phase, power, phase_solar, phase_battery)

        ev_id = self._config.get(CONF_EV_CHARGER_ENTITY)
        if ev_id and solar > 0:
            await self._limiter.optimize_ev_charging(solar)

    # ── Storage ───────────────────────────────────────────────────────────────

    async def _load_saved_devices(self):
        saved = await self._store_devices.async_load()
        if saved:
            for dev_data in saved.get("devices", []):
                try:
                    dev = DetectedDevice(**dev_data)
                    self._nilm._devices[dev.device_id] = dev
                except (TypeError, KeyError) as exc:
                    _LOGGER.warning("Fout bij laden NILM device: %s", exc)
            _LOGGER.info(
                "CloudEMS: %d NILM-apparaten geladen", len(self._nilm._devices)
            )

    async def _save_devices(self):
        devices_data = [
            {
                "device_id":            d.device_id,
                "device_type":          d.device_type,
                "name":                 d.name,
                "confidence":           d.confidence,
                "current_power":        d.current_power,
                "is_on":                d.is_on,
                "source":               d.source,
                "confirmed":            d.confirmed,
                "detection_count":      d.detection_count,
                "last_seen":            d.last_seen,
                "phase":                d.phase,
                "energy_today":         d.energy_today,
                "energy_total":         d.energy_total,
                "on_events":            d.on_events,
                "pending_confirmation": d.pending_confirmation,
            }
            for d in self._nilm.get_devices()
        ]
        await self._store_devices.async_save({"devices": devices_data})

    # ── Callbacks ─────────────────────────────────────────────────────────────

    @callback
    def _on_nilm_device_found(self, device: DetectedDevice, all_matches: List[Dict]):
        _LOGGER.info(
            "CloudEMS: Apparaat gevonden: %s (%.0f%% zekerheid)",
            device.name, device.confidence * 100,
        )
        self._pending_devices.append(device)
        if device.pending_confirmation:
            persistent_notification.async_create(
                self.hass,
                title="☀️ CloudEMS: Apparaat gevonden",
                message=(
                    f"**{device.name}** gedetecteerd op fase **{device.phase}**\n\n"
                    f"Vermogen: {device.current_power:.0f}W | "
                    f"Zekerheid: {device.confidence:.0%}\n\n"
                    "Bevestig via het CloudEMS dashboard."
                ),
                notification_id=f"cloudems_nilm_{device.device_id}",
            )
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, f"{DOMAIN}_device_found", device)
        self.hass.async_create_task(self._save_devices())

    @callback
    def _on_nilm_device_update(self, device: DetectedDevice):
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, f"{DOMAIN}_device_update", device)

    async def _set_ev_current(self, ampere: float):
        ev_id = self._config.get(CONF_EV_CHARGER_ENTITY)
        if not ev_id:
            return
        try:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": ev_id, "value": ampere},
            )
        except Exception as exc:
            _LOGGER.warning("EV stroom instellen mislukt: %s", exc)

    async def _set_solar_curtailment(self, percent: float):
        _LOGGER.debug("CloudEMS: Solar curtailment %.0f%%", percent)

    # ── Public API ────────────────────────────────────────────────────────────

    def confirm_nilm_device(self, device_id: str, device_type: str, name: str):
        self._nilm.confirm_device(device_id, device_type, name)
        self.hass.async_create_task(self._save_devices())

    def dismiss_nilm_device(self, device_id: str):
        self._nilm.dismiss_device(device_id)
        self.hass.async_create_task(self._save_devices())

    async def async_shutdown(self):
        if self._p1_reader:
            await self._p1_reader.async_stop()
        if self._session:
            await self._session.close()

    @property
    def nilm_devices(self) -> List[DetectedDevice]:
        return self._nilm.get_devices()

    @property
    def pending_devices(self) -> List[DetectedDevice]:
        return [d for d in self._nilm.get_devices() if d.pending_confirmation]

    @property
    def current_energy_price(self) -> float:
        return self._prices.current_price if self._prices else 0.0
