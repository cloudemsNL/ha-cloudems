"""
CloudEMS AI Registry — v1.0.0

Central manager for AI providers. Collects training samples from the coordinator,
dispatches predictions, and manages the provider lifecycle.

One registry instance per CloudEMS installation. Providers can be added/removed
at runtime. The default OnnxProvider is always present.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from .provider import AIProvider, AIModelContract, PredictionResult
from .onnx_provider import OnnxProvider
from .seq2point_nilm import Seq2PointNILM
from .ev_pattern_learner import EVPatternLearner
from .shutter_pattern_learner import ShutterPatternLearner
from .nexus_latency_learner import NexusLatencyLearner
from .phase_balance_optimizer import PhaseBalanceOptimizer
from .threshold_learner import ThresholdLearner
from .learning_log import AILearningLog
from .data_sanity import DataSanityChecker

_LOGGER = logging.getLogger(__name__)

# Collect a training sample every N coordinator ticks (1 tick = 10s → 1 sample/min)
SAMPLE_EVERY_N_TICKS = 6


class AIRegistry:
    """
    Manages CloudEMS AI providers.

    Usage from coordinator:
        registry = AIRegistry(hass)
        await registry.async_setup()

        # Every tick:
        await registry.async_observe(coordinator_data)

        # For a decision:
        result = await registry.async_predict(features)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._providers: dict[str, AIProvider] = {}
        self._default: str = "onnx_local"
        self._tick_count = 0
        self._last_prediction: PredictionResult | None = None
        self._sample_buffer: list[dict[str, Any]] = []
        self._nilm_seq2p:  Seq2PointNILM        = Seq2PointNILM(hass)
        self._ev_learner:  EVPatternLearner      = EVPatternLearner(hass)
        self._shutter_lrn:  ShutterPatternLearner = ShutterPatternLearner(hass)
        self._nexus_lrn:    NexusLatencyLearner   = NexusLatencyLearner(hass)
        self._phase_opt:    PhaseBalanceOptimizer = PhaseBalanceOptimizer(hass)

        # ThresholdLearner — single source of truth for all tunable thresholds
        from ..const import (
            BATTERY_STALE_THRESHOLD_S, BATTERY_STALE_MIN_S, P1_STALE_THRESHOLD_S,
            AI_MIN_CONFIDENCE, AI_BATTERY_MIN_CONFIDENCE, AI_BOILER_MIN_CONFIDENCE,
            AI_SHUTTER_MIN_CONFIDENCE, AI_EV_MIN_CONFIDENCE,
            PHASE_IMBALANCE_THRESHOLD_A, NILM_MIN_THRESHOLD_W,
            NEXUS_MEASURE_WINDOW_S, NEXUS_MIN_POWER_DELTA_W,
        )
        self._learning_log      = AILearningLog(hass)
        self._sanity            = DataSanityChecker()
        self._threshold_learner = ThresholdLearner(hass, defaults={
            "BATTERY_STALE_THRESHOLD_S":   BATTERY_STALE_THRESHOLD_S,
            "P1_STALE_THRESHOLD_S":        P1_STALE_THRESHOLD_S,
            "AI_MIN_CONFIDENCE":           AI_MIN_CONFIDENCE,
            "AI_BATTERY_MIN_CONFIDENCE":   AI_BATTERY_MIN_CONFIDENCE,
            "AI_BOILER_MIN_CONFIDENCE":    AI_BOILER_MIN_CONFIDENCE,
            "AI_SHUTTER_MIN_CONFIDENCE":   AI_SHUTTER_MIN_CONFIDENCE,
            "AI_EV_MIN_CONFIDENCE":        AI_EV_MIN_CONFIDENCE,
            "PHASE_IMBALANCE_THRESHOLD_A": PHASE_IMBALANCE_THRESHOLD_A,
            "NILM_MIN_THRESHOLD_W":        NILM_MIN_THRESHOLD_W,
            "NEXUS_MEASURE_WINDOW_S":      NEXUS_MEASURE_WINDOW_S,
            "NEXUS_MIN_POWER_DELTA_W":     NEXUS_MIN_POWER_DELTA_W,
            "AI_PRICE_NUDGE_EUR_KWH":      0.02,
            "BOILER_SURPLUS_NUDGE_W":      200.0,
            "PRICE_CHEAP_EUR_KWH":         0.10,
            "PRICE_EXPENSIVE_EUR_KWH":     0.25,
        })

    async def async_setup(self) -> None:
        """Initialize default ONNX provider."""
        onnx = OnnxProvider(self.hass)
        await onnx.async_setup()
        self._providers["onnx_local"] = onnx
        await self._nilm_seq2p.async_setup()
        # Wire threshold feedback callback into all providers
        for provider in self._providers.values():
            if hasattr(provider, '_threshold_callback'):
                provider._threshold_callback = self._threshold_learner.report_outcome
        await self._ev_learner.async_setup()
        await self._shutter_lrn.async_setup()
        await self._nexus_lrn.async_setup()
        await self._phase_opt.async_setup()
        await self._threshold_learner.async_setup()
        await self._learning_log.async_setup()
        _LOGGER.info("CloudEMS AI registry initialized (default: onnx_local)")

    async def async_shutdown(self) -> None:
        """Save all providers on HA shutdown."""
        for p in self._providers.values():
            await p.async_shutdown()
        await self._nilm_seq2p.async_save()
        await self._ev_learner._save()
        await self._shutter_lrn._save()
        await self._nexus_lrn.async_save()
        await self._phase_opt.async_save()
        await self._threshold_learner.async_save()
        await self._learning_log.async_save()

    # ── Provider management ───────────────────────────────────────────────────

    def add_provider(self, provider: AIProvider) -> None:
        """Register an additional provider (e.g. Ollama, AdaptiveHome)."""
        self._providers[provider.name] = provider
        _LOGGER.info("CloudEMS AI: registered provider %r", provider.name)

    def remove_provider(self, name: str) -> None:
        if name == self._default:
            _LOGGER.warning("Cannot remove default provider %r", name)
            return
        self._providers.pop(name, None)

    def set_default(self, name: str) -> bool:
        if name not in self._providers:
            return False
        self._default = name
        return True

    @property
    def default_provider(self) -> AIProvider | None:
        return self._providers.get(self._default)

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    # ── Observation (training data collection) ────────────────────────────────

    async def async_observe(self, data: dict[str, Any]) -> None:
        """
        Called every coordinator tick with the current system state.
        Builds feature vectors and periodically sends to providers for training.
        """
        self._tick_count += 1
        # v5.5.161: diagnose logging elke 60 ticks (~10 min)
        if self._tick_count % 60 == 0:
            _onnx = self._providers.get("onnx_local")
            _buf  = len(_onnx._buffer) if _onnx else -1
            _nst  = _onnx._n_since_train if _onnx else -1
            _rdy  = _onnx._ready if _onnx else False
            _sbuf = len(self._sample_buffer)
            _LOGGER.info(
                "CloudEMS AI diagnose: tick=%d sample_buf=%d onnx_buf=%d n_since=%d ready=%s",
                self._tick_count, _sbuf, _buf, _nst, _rdy
            )

        # Sanity check EVERY tick — validate data before it reaches JS cards
        _sanity_issues = self._sanity.check(data)
        if _sanity_issues:
            # Feed anomalies into learning log as negative reward signals
            for _issue in _sanity_issues:
                self._learning_log.update_outcome(
                    decision_ts=time.time(),
                    reward=-0.5,
                    hindsight_label="data_error",
                )

        if self._tick_count % SAMPLE_EVERY_N_TICKS != 0:
            # Still feed NILM every tick (needs high resolution)
            # Also tick Nexus latency learner every tick
            _bat_pw = float(data.get("battery_power", 0) or 0)
            _nexus_meas = self._nexus_lrn.tick(current_power_w=_bat_pw)
            if _nexus_meas:
                # Feed measured latency back to threshold learner
                self._threshold_learner.update_from_measurement(
                    "BATTERY_STALE_THRESHOLD_S", _nexus_meas.latency_s * 0.8
                )
            # Phase balance optimizer
            _phases = data.get("phases", {})
            self._phase_opt.tick(
                l1_a = float((_phases.get("L1") or {}).get("current_a", 0)),
                l2_a = float((_phases.get("L2") or {}).get("current_a", 0)),
                l3_a = float((_phases.get("L3") or {}).get("current_a", 0)),
                active_devices = data.get("nilm_running_devices"),
            )
            self._nilm_seq2p.tick(
                total_w = float(data.get("house_load_w", data.get("house_power", 0)) or 0),
                l1_w    = float((data.get("phases", {}).get("L1") or {}).get("power_w", 0)),
                l2_w    = float((data.get("phases", {}).get("L2") or {}).get("power_w", 0)),
                l3_w    = float((data.get("phases", {}).get("L3") or {}).get("power_w", 0)),
                known_devices = data.get("nilm_running_devices"),
            )
            return

        features = self._build_features(data)
        if features is None:
            _LOGGER.warning("CloudEMS AI: _build_features returned None — sample overgeslagen (tick=%d)", self._tick_count)
            return

        # Determine ground-truth label from current system state
        label = self._infer_label(data)

        # EV pattern learner
        ev_sessions = data.get("ev_sessions", data.get("ev", {}).get("active_sessions", []))
        ev_connected = len(ev_sessions) > 0
        ev_soc = float((ev_sessions[0].get("soc_pct") if ev_sessions else None) or
                       data.get("battery_soc", 0) or 0)
        self._ev_learner.tick(is_connected=ev_connected, soc_pct=ev_soc)

        # Feed per-module learner stats into learning log (every 6th tick = 1/min)
        if self._tick_count % 6 == 0 and _ai_pred_now:
            # EV departure prediction → log as context feature
            if ev_connected and self._ev_learner.stats.get("ready"):
                import datetime as _dt_ll
                _ev_dow = _dt_ll.datetime.now().weekday()
                _ev_h   = _dt_ll.datetime.now().hour + _dt_ll.datetime.now().minute/60.0
                _ev_dep = self._ev_learner.predict_departure(_ev_dow, _ev_h)
                if _ev_dep.get("confidence", 0) >= 0.5:
                    _LOGGER.debug(
                        "AI EV: depart ~%.1f:00 (conf=%.0f%%, %d ritten)",
                        _ev_dep.get("departure_hour", 0),
                        _ev_dep.get("confidence", 0) * 100,
                        _ev_dep.get("based_on_trips", 0),
                    )
            # Phase balance warning → log
            _pb_warn = self._phase_opt.tick(
                l1_a = float((data.get("phases", {}).get("L1") or {}).get("current_a", 0)),
                l2_a = float((data.get("phases", {}).get("L2") or {}).get("current_a", 0)),
                l3_a = float((data.get("phases", {}).get("L3") or {}).get("current_a", 0)),
                active_devices = data.get("nilm_running_devices"),
            )
            if _pb_warn:
                _LOGGER.warning("CloudEMS AI fase-onbalans: %s", _pb_warn)

        # Every ~16 minutes (100 ticks): feed learning log into Seq2Point trainer
        if self._tick_count % 100 == 0:
            try:
                _td = self._learning_log.export_training_data()
                if _td:
                    _n = self._nilm_seq2p.train_from_learning_log(_td)
                    if _n > 0:
                        _LOGGER.debug("AI: %d log entries → Seq2Point trainer", _n)
            except Exception as _seq_err:
                _LOGGER.debug("Seq2Point training fout: %s", _seq_err)

        # Shutter pattern learner
        shutters = data.get("shutters", {})
        for shutter_id, sh_state in (shutters.items() if isinstance(shutters, dict) else []):
            pos = sh_state.get("position", sh_state.get("current_position"))
            if pos is not None:
                self._shutter_lrn.observe(
                    shutter_id = shutter_id,
                    position   = int(pos),
                    solar_w    = float(data.get("solar_power", 0) or 0),
                    temp_out   = float(data.get("temp_outside", 0) or 0),
                    cloud_pct  = float(data.get("cloud_cover_pct", 50) or 50),
                )

        # Record to learning log
        _ai_pred_now = await self._default_provider.async_predict(features) if self._ready else None
        if _ai_pred_now:
            self._learning_log.record_from_data(
                data          = data,
                ai_label      = _ai_pred_now.label,
                ai_conf       = _ai_pred_now.confidence,
                ai_source     = "knn" if self._ready else "bootstrap",
                action_taken  = self._infer_label(data),
                action_source = "coordinator",
                thresholds    = self._threshold_learner.all_values,
            )

        sample = {
            "features": features.to_vector(),
            "label":    label,
            "value":    float(data.get("solar_power", 0.0)),
            "ts":       time.time(),
        }
        self._sample_buffer.append(sample)

        # Elke 60 ticks (10 min) status loggen
        if self._tick_count % 60 == 0:
            for _pname, _prov in self._providers.items():
                _LOGGER.info(
                    "CloudEMS AI status: provider=%s buffer=%d n_since=%d n_trained=%d ready=%s",
                    _pname,
                    getattr(_prov, '_buffer', []) and len(getattr(_prov, '_buffer', [])) or 0,
                    getattr(_prov, '_n_since_train', -1),
                    getattr(_prov, '_model', None) and getattr(getattr(_prov, '_model', None), '_n_trained', 0) or 0,
                    getattr(_prov, '_ready', False),
                )

        # Send batch to providers every 12 samples (~2 minutes)
        if len(self._sample_buffer) >= 12:
            batch = self._sample_buffer.copy()
            self._sample_buffer.clear()
            _LOGGER.info(
                "CloudEMS AI: batch van %d samples naar %d provider(s) — labels: %s",
                len(batch), len(self._providers),
                list({s.get('label','?') for s in batch}),
            )
            for provider in self._providers.values():
                try:
                    # Add current state snapshot for outcome tracking
                    for s in batch:
                        s["state_snapshot"] = {
                            "battery_soc":    data.get("battery_soc", data.get("battery_soc_pct", 0)),
                            "epex_price_now": data.get("epex_price_now", data.get("current_price", 0)),
                            "boiler_temp_c":  data.get("boiler_temp_c", 0),
                            "solar_power":    data.get("solar_power", 0),
                            "export_power":   data.get("export_power", 0),
                        }
                    await provider.async_train(batch)
                    # Update learning log outcomes from completed OutcomeTracker results
                    for _comp in getattr(provider, '_outcome_tracker', None) and [] or []:
                        if _comp.get("reward") is not None:
                            self._learning_log.update_outcome(
                                decision_ts=_comp.get("ts", 0),
                                reward=_comp["reward"],
                                hindsight_label=_comp.get("label"),
                            )
                except Exception as exc:
                    _LOGGER.debug("CloudEMS AI: train error in %s: %s", provider.name, exc)

    # ── Prediction ────────────────────────────────────────────────────────────

    async def async_predict(self, data: dict[str, Any]) -> PredictionResult | None:
        """
        Run prediction using the default provider.
        Returns None if provider is not ready yet.
        """
        provider = self.default_provider
        if not provider or not provider.is_ready:
            return None

        features = self._build_features(data)
        if features is None:
            _LOGGER.warning("CloudEMS AI: _build_features returned None — sample overgeslagen (tick=%d)", self._tick_count)
            return None

        try:
            result = await provider.async_predict(features)
            self._last_prediction = result
            return result
        except Exception as exc:
            _LOGGER.debug("CloudEMS AI: predict error: %s", exc)
            return None

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        """Status dict for dashboard sensor."""
        default = self.default_provider
        return {
            "ready": default.is_ready if default else False,
            "default_provider": self._default,
            "providers": list(self._providers.keys()),
            "last_label": self._last_prediction.label if self._last_prediction else None,
            "last_confidence": self._last_prediction.confidence if self._last_prediction else None,
            "last_explanation": self._last_prediction.explanation if self._last_prediction else None,
            **(default.stats if hasattr(default, "stats") else {}),
            "nilm_seq2p":    self._nilm_seq2p.stats,
            "ev_learner":    self._ev_learner.stats,
            "shutter_learner": self._shutter_lrn.stats,
            "nexus_latency":   self._nexus_lrn.stats,
            "phase_balance":   self._phase_opt.stats,
            "thresholds":      self._threshold_learner.stats,
            "learning_log":    self._learning_log.stats,
            "sanity":          self._sanity.stats,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_features(self, data: dict[str, Any]) -> AIModelContract | None:
        """Build a feature vector from coordinator data. Returns None if insufficient data."""
        try:
            now = datetime.now(timezone.utc)
            phases = data.get("phases", {})

            return AIModelContract(
                # Time
                hour_of_day    = float(now.hour),
                day_of_week    = float(now.weekday()),
                month          = float(now.month),
                is_weekend     = 1.0 if now.weekday() >= 5 else 0.0,
                # Power
                grid_w         = float(data.get("grid_power", data.get("grid_power_w", 0.0)) or 0.0),
                solar_w        = float(data.get("solar_power", data.get("solar_power_w", 0.0)) or 0.0),
                battery_w      = float(data.get("battery_power", data.get("battery_power_w", 0.0)) or 0.0),
                battery_soc_pct= float(data.get("battery_soc", data.get("battery_soc_pct", 0.0)) or 0.0),
                house_load_w   = float(data.get("house_load_w", data.get("house_power", 0.0)) or 0.0),
                # Prices
                epex_now       = float(data.get("epex_price_now", data.get("current_price", 0.0)) or 0.0),
                epex_next_hour = float(data.get("epex_price_next", 0.0) or 0.0),
                epex_avg_today = float(data.get("epex_avg_today", 0.0) or 0.0),
                # Phases
                l1_a           = float((phases.get("L1") or {}).get("current_a", 0.0)),
                l2_a           = float((phases.get("L2") or {}).get("current_a", 0.0)),
                l3_a           = float((phases.get("L3") or {}).get("current_a", 0.0)),
                # Weather
                temp_outside   = float(data.get("temp_outside", 0.0) or 0.0),
                cloud_cover_pct= float(data.get("cloud_cover_pct", 50.0) or 50.0),
                pv_forecast_w  = float(data.get("pv_forecast_next_hour_w", 0.0) or 0.0),
                # Context
                nilm_active_count = int(data.get("nilm_device_count", 0) or 0),
                boiler_temp    = float(data.get("boiler_temp_c", 0.0) or 0.0),
            )
        except Exception as exc:
            _LOGGER.debug("CloudEMS AI: failed to build features: %s", exc)
            return None

    def predict_ev_departure(self, dow: int, hour: float) -> dict:
        """Get EV departure prediction from pattern learner."""
        return self._ev_learner.predict_departure(dow, hour)

    def get_sanity_anomalies(self) -> list[dict]:
        """Get current data anomalies for dashboard display."""
        return self._sanity.active_anomalies

    def log_outcome(self, decision_ts: float, reward: float, hindsight: str = None) -> None:
        """Update learning log with measured outcome."""
        self._learning_log.update_outcome(decision_ts, reward, hindsight)

    def get_training_data(self) -> list:
        """Export training data for Seq2Point model."""
        return self._learning_log.export_training_data()

    def threshold(self, name: str) -> float:
        """Get current best value for any threshold. Modules call this instead of const.py."""
        return self._threshold_learner.get(name)

    def report_threshold_outcome(self, name: str, good: bool, reward: float = 0.0) -> None:
        """Report whether using a threshold led to a good outcome."""
        self._threshold_learner.report_outcome(name, good, reward)

    def report_threshold_outcome_for_hour(self, name: str, hour: int, good: bool, reward: float = 0.0) -> None:
        """Report outcome with hour-of-day context (from BDEFeedback)."""
        self._threshold_learner.report_outcome_for_hour(name, hour, good, reward)

    def update_threshold(self, name: str, measured_value: float) -> None:
        """Directly update a threshold from a measurement."""
        self._threshold_learner.update_from_measurement(name, measured_value)

    def record_battery_command(self, commanded_w: float, current_power_w: float) -> None:
        """Record a battery command for latency learning."""
        self._nexus_lrn.record_command(commanded_w, current_power_w)

    def predict_battery_latency(self, hour: int | None = None) -> dict:
        """Get Nexus latency prediction."""
        return self._nexus_lrn.predict_latency(hour)

    def correct_battery_power(self, requested_w: float) -> float:
        """Apply Nexus power correction factor."""
        return self._nexus_lrn.get_power_correction(requested_w)

    def predict_phase_balance(self, horizon_min: int = 15) -> dict:
        """Get phase balance forecast and EV phase recommendation."""
        fc = self._phase_opt.forecast(horizon_min)
        return {"warning_phase": fc.warning_phase, "warning_in_min": fc.warning_in_min,
                "confidence": fc.confidence}

    def recommend_ev_phase(self, l1: float, l2: float, l3: float) -> dict:
        return self._phase_opt.recommend_ev_phase(l1, l2, l3)

    def predict_shutter(self, shutter_id: str, hour: float, dow: int,
                        solar_w: float, temp_out: float, cloud_pct: float) -> dict:
        """Get shutter position prediction from pattern learner."""
        return self._shutter_lrn.predict(shutter_id, hour, dow, solar_w, temp_out, cloud_pct)

    def _infer_label(self, data: dict[str, Any]) -> str:
        """
        Infer ground-truth label from current system state.
        This is what the system IS doing right now — used as training signal.
        """
        solar_w   = float(data.get("solar_power", 0.0) or 0.0)
        grid_w    = float(data.get("grid_power", data.get("grid_power_w", 0.0)) or 0.0)
        battery_w = float(data.get("battery_power", 0.0) or 0.0)
        boiler_w  = float(data.get("boiler_power_w", 0.0) or 0.0)
        epex      = float(data.get("epex_price_now", data.get("current_price", 0.0)) or 0.0)

        # Determine dominant action
        if battery_w > 200:
            return "charge_battery"
        if battery_w < -200:
            return "discharge_battery"
        if boiler_w > 500:
            return "run_boiler"
        if grid_w < -200:
            return "export_surplus"
        if grid_w > 500 and epex > 0.20:
            return "defer_load"
        return "idle"
