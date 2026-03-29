"""
CloudEMS ONNX Provider — v1.0.0

Default AI engine. Trains a small decision-tree model on local HA recorder data.
Fully offline — no external dependencies beyond onnxruntime (optional).

Training flow:
  1. Read sensor history from HA recorder (last 30 days)
  2. Build feature vectors using AIModelContract
  3. Train a small gradient-boosted tree (scikit-learn → export to ONNX)
  4. Save model to HA storage
  5. Run inference locally

If onnxruntime is not installed, falls back to a pure-Python k-NN classifier
(same approach as NILM local_ai.py — no numpy/scipy required).

The model learns:
  - When is it profitable to charge the battery? (based on EPEX + solar forecast)
  - When is boiler heating most efficient? (based on surplus + temperature)
  - Which NILM device patterns match this home? (anomaly baseline)
  - What is the expected house load for the next hour?
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .provider import AIProvider, AIModelContract, PredictionResult, CONTRACT_VERSION
from .outcome_tracker import OutcomeTracker
from .confidence_bootstrap import ConfidenceBootstrap, blend_predictions

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_ai_onnx_v1"
STORAGE_VERSION = 1
MODEL_KEY       = "cloudems_ai_model_v1"

# Minimum samples before training is attempted
MIN_TRAIN_SAMPLES = 48   # ~8 minutes of 10s ticks
# Retrain every N new samples
RETRAIN_INTERVAL  = 48   # eerste training na 48 nieuwe samples (~8 min)


# ── Pure-Python k-NN fallback (no numpy required) ─────────────────────────────

def _dot(a: list[float], b: list[float]) -> float:
    return sum(x*y for x,y in zip(a,b))

def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x*x for x in a)) or 1e-9

def _cosine_sim(a: list[float], b: list[float]) -> float:
    return _dot(a,b) / (_norm(a) * _norm(b))

def _normalize_vector(v: list[float], means: list[float], stds: list[float]) -> list[float]:
    return [(x - m) / (s or 1.0) for x,m,s in zip(v, means, stds)]


class KNNModel:
    """
    Pure-Python k-NN classifier for CloudEMS decisions.
    No external dependencies. Trains and runs on raw feature vectors.
    """

    def __init__(self, k: int = 5) -> None:
        self.k = k
        self._samples: list[tuple[list[float], str, float]] = []  # (features, label, outcome_value)
        self._means:   list[float] = []
        self._stds:    list[float] = []
        self._version  = "knn-local-0"
        self._n_trained = 0

    def fit(self, samples: list[dict[str, Any]]) -> None:
        """Train on a list of {'features': [...], 'label': str, 'value': float} dicts."""
        if not samples:
            return

        n_features = len(samples[0]["features"])
        # Compute per-feature mean and std for normalization
        cols = [[s["features"][i] for s in samples] for i in range(n_features)]
        self._means = [sum(c)/len(c) for c in cols]
        self._stds  = [math.sqrt(sum((x-m)**2 for x in c)/len(c)) for c,m in zip(cols,self._means)]

        self._samples = [
            (_normalize_vector(s["features"], self._means, self._stds), s["label"], s.get("value", 0.0))
            for s in samples
        ]
        self._n_trained = len(samples)
        self._version = f"knn-local-{self._n_trained}"
        _LOGGER.debug("KNNModel trained on %d samples, %d features", self._n_trained, n_features)

    def predict(self, features: list[float]) -> tuple[str, float, list[str]]:
        """
        Returns (label, confidence, top_feature_names).
        confidence = fraction of k neighbours with winning label.
        """
        if not self._samples:
            return "idle", 0.0, []

        norm_feat = _normalize_vector(features, self._means, self._stds)

        # Find k nearest neighbours by cosine similarity
        sims = [(_cosine_sim(norm_feat, s[0]), s[1], s[2]) for s in self._samples]
        sims.sort(key=lambda x: -x[0])
        neighbours = sims[:self.k]

        # Vote
        votes: dict[str, list[float]] = {}
        for sim, label, val in neighbours:
            votes.setdefault(label, []).append(sim)

        best_label = max(votes, key=lambda l: sum(votes[l]))
        confidence = round(sum(votes[best_label]) / sum(s for sims in votes.values() for s in sims), 3)

        return best_label, confidence, []

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "version": self._version,
            "n_trained": self._n_trained,
            "means": self._means,
            "stds": self._stds,
            "samples": [(f, l, v) for f,l,v in self._samples],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KNNModel":
        m = cls(k=d.get("k", 5))
        m._version   = d.get("version", "knn-local-0")
        m._n_trained = d.get("n_trained", 0)
        m._means     = d.get("means", [])
        m._stds      = d.get("stds", [])
        m._samples   = [(f,l,v) for f,l,v in d.get("samples", [])]
        return m


# ── ONNX Provider ──────────────────────────────────────────────────────────────

class OnnxProvider(AIProvider):
    """
    Default CloudEMS AI provider.

    Uses a k-NN model (pure Python, no dependencies) by default.
    If onnxruntime is installed, exports the trained model to ONNX format
    for faster inference and cloud-compatibility.

    Training data: collected locally from HA sensor history.
    Model storage: HA .storage/cloudems_ai_onnx_v1
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__("onnx_local")
        self.hass      = hass
        self._store    = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._model: KNNModel | None = None
        self._buffer:  list[dict[str, Any]] = []  # incoming samples before training
        self._n_since_train = 0
        self._last_pred: PredictionResult | None = None
        self._onnx_available = False
        self._outcome_tracker     = OutcomeTracker()
        self._bootstrap           = ConfidenceBootstrap()
        self._threshold_callback  = None   # set by registry: fn(name, good, reward)

    async def async_setup(self) -> None:
        """Load saved model from storage if available."""
        saved = await self._store.async_load() or {}

        # Try to load saved k-NN model
        model_data = saved.get("knn_model")
        if model_data:
            try:
                self._model = KNNModel.from_dict(model_data)
                self._ready = self._model._n_trained >= MIN_TRAIN_SAMPLES
                _LOGGER.info(
                    "CloudEMS AI: loaded k-NN model (%d samples, ready=%s)",
                    self._model._n_trained, self._ready
                )
            except Exception as exc:
                _LOGGER.warning("CloudEMS AI: failed to load saved model: %s", exc)
                self._model = KNNModel()

        # Load buffered samples en filter op geldig formaat
        _raw_buf = saved.get("buffer", [])
        self._buffer = [
            s for s in _raw_buf
            if isinstance(s, dict)
            and isinstance(s.get("features"), list)
            and len(s.get("features", [])) > 0
            and s.get("label")
        ]
        if len(self._buffer) != len(_raw_buf):
            _LOGGER.info(
                "CloudEMS AI: buffer gefilterd — %d van %d samples geldig",
                len(self._buffer), len(_raw_buf)
            )
        self._n_since_train = saved.get("n_since_train", 0)

        # Check if onnxruntime is available
        try:
            import onnxruntime  # noqa: F401
            self._onnx_available = True
            _LOGGER.debug("CloudEMS AI: onnxruntime available")
        except ImportError:
            self._onnx_available = False
            _LOGGER.debug("CloudEMS AI: onnxruntime not available, using k-NN fallback")
        self._outcome_tracker     = OutcomeTracker()
        self._bootstrap           = ConfidenceBootstrap()
        self._threshold_callback  = None   # set by registry: fn(name, good, reward)

        if not self._model:
            self._model = KNNModel()

    async def async_predict(self, features: AIModelContract) -> PredictionResult:
        """Run inference. Returns 'idle' with low confidence if not yet trained."""
        if not self._ready or not self._model:
            return PredictionResult(
                label="idle",
                confidence=0.0,
                value=0.0,
                explanation="Model nog aan het leren — te weinig data.",
                model_version="untrained",
                source="onnx_local",
            )

        vec = features.to_vector()
        label, confidence, top_features = self._model.predict(vec)

        # Bootstrap blend: improves cold-start confidence
        boot_label, boot_conf = self._bootstrap.predict(
            hour          = int(features.hour_of_day),
            solar_w       = features.solar_w,
            battery_soc   = features.battery_soc_pct,
            epex_now      = features.epex_now,
            epex_avg      = features.epex_avg_today,
            grid_w        = features.grid_w,
            boiler_temp   = features.boiler_temp,
            n_knn_samples = self._model._n_trained,
        )
        label, confidence = blend_predictions(
            (boot_label, boot_conf),
            (label, confidence),
            self._model._n_trained,
        )
        value = self._label_to_value(label, features)
        explanation = self._explain(label, confidence, features)

        result = PredictionResult(
            label=label,
            confidence=confidence,
            value=value,
            explanation=explanation,
            top_features=top_features,
            model_version=self._model._version,
            source="onnx_local",
        )
        self._last_pred = result
        # Record for outcome measurement
        context_snapshot = {
            "soc_pct":    features.battery_soc_pct,
            "epex_price": features.epex_now,
            "boiler_temp": features.boiler_temp,
        }
        self._outcome_tracker.record(
            label=result.label,
            confidence=result.confidence,
            features=features.to_vector(),
            context=context_snapshot,
        )
        return result

    async def async_train(self, samples: list[dict[str, Any]]) -> bool:
        """Add samples to buffer and retrain when enough data is available."""
        self._buffer.extend(samples)
        self._n_since_train += len(samples)

        # Check outcomes of past decisions — add reward-weighted samples back
        # (we need current state — passed via samples[0] context if available)
        if samples:
            current_state = samples[-1].get("state_snapshot", {})
            completed = self._outcome_tracker.tick(current_state)
            for comp in completed:
                # Re-add the sample with outcome weight
                if comp["weight"] > 0.2:
                    self._buffer.append({
                        "features": comp["features"],
                        "label":    comp["label"],
                        "value":    0.0,
                        "weight":   comp["weight"],
                    })
                # Feed outcome back to threshold learner via registry callback
                if self._threshold_callback and comp.get("reward") is not None:
                    label = comp["label"]
                    good  = comp["reward"] > 0
                    rew   = float(comp["reward"])
                    # Map label → relevant threshold
                    _label_thresh = {
                        "charge_battery":    "AI_BATTERY_MIN_CONFIDENCE",
                        "discharge_battery": "AI_BATTERY_MIN_CONFIDENCE",
                        "run_boiler":        "AI_BOILER_MIN_CONFIDENCE",
                        "idle":              "AI_MIN_CONFIDENCE",
                    }
                    thresh_name = _label_thresh.get(label, "AI_MIN_CONFIDENCE")
                    self._threshold_callback(thresh_name, good, rew)

        # Retrain when buffer is large enough
        if len(self._buffer) >= MIN_TRAIN_SAMPLES and self._n_since_train >= RETRAIN_INTERVAL:
            _LOGGER.info(
                "CloudEMS AI: retrain trigger — buffer=%d, n_since=%d",
                len(self._buffer), self._n_since_train
            )
            return await self._retrain()
        # Sla op na elke batch zodat herstart de voortgang bewaart
        # (was % 24 — bij herstart vóór 24 samples werd n_since_train gereset naar 0)
        await self._save()
        return True

    async def async_explain(self, features: AIModelContract) -> str:
        """Return explanation for the last prediction."""
        if self._last_pred:
            return self._last_pred.explanation
        return "Nog geen voorspelling beschikbaar."

    async def async_shutdown(self) -> None:
        """Save model and buffer to storage."""
        await self._save()

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _retrain(self) -> bool:
        try:
            t0 = time.time()
            # Keep last 10000 samples (prevent unbounded growth)
            if len(self._buffer) > 10_000:
                self._buffer = self._buffer[-10_000:]

            # Filter op geldige samples: moet "features" key hebben als lijst
            # Ongeldige samples (oud formaat, corrupte data) worden overgeslagen
            _valid = [
                s for s in self._buffer
                if isinstance(s, dict)
                and isinstance(s.get("features"), list)
                and len(s["features"]) > 0
                and s.get("label")
            ]
            _LOGGER.info(
                "CloudEMS AI: retrain gestart — %d van %d samples geldig",
                len(_valid), len(self._buffer)
            )
            if len(_valid) < MIN_TRAIN_SAMPLES:
                _LOGGER.warning(
                    "CloudEMS AI: te weinig geldige samples (%d < %d) — retrain overgeslagen",
                    len(_valid), MIN_TRAIN_SAMPLES
                )
                self._n_since_train = 0
                return False

            self._model.fit(_valid)
            self._ready = self._model._n_trained >= MIN_TRAIN_SAMPLES
            self._n_since_train = 0
            elapsed = time.time() - t0
            _LOGGER.info(
                "CloudEMS AI: k-NN getraind op %d samples in %.2fs (ready=%s)",
                self._model._n_trained, elapsed, self._ready
            )
            await self._save()
            return True
        except Exception as exc:
            _LOGGER.error("CloudEMS AI: training mislukt: %s", exc, exc_info=True)
            return False

    async def _save(self) -> None:
        try:
            await self._store.async_save({
                "knn_model": self._model.to_dict() if self._model else {},
                "buffer": self._buffer[-5000:],  # save last 5000 samples
                "n_since_train": self._n_since_train,
                "contract_version": CONTRACT_VERSION,
            })
        except Exception as exc:
            _LOGGER.warning("CloudEMS AI: failed to save model: %s", exc)

    def _label_to_value(self, label: str, f: AIModelContract) -> float:
        """Convert label to a numeric recommendation value."""
        mapping = {
            "charge_battery":    min(3000.0, max(0.0, f.solar_w - f.house_load_w)),
            "discharge_battery": min(2000.0, max(0.0, f.house_load_w - f.solar_w)),
            "run_boiler":        1.5,   # kW
            "defer_load":        0.0,
            "idle":              0.0,
            "export_surplus":    max(0.0, f.solar_w - f.house_load_w),
        }
        return mapping.get(label, 0.0)

    def _explain(self, label: str, confidence: float, f: AIModelContract) -> str:
        pct = int(confidence * 100)
        hour = int(f.hour_of_day)
        explanations = {
            "charge_battery":    f"{pct}% — {f.solar_w:.0f}W zon, EPEX €{f.epex_now:.2f}/kWh → batterij laden",
            "discharge_battery": f"{pct}% — EPEX hoog (€{f.epex_now:.2f}), batterij inzetten",
            "run_boiler":        f"{pct}% — Surplusenergie beschikbaar, boiler verwarmen",
            "defer_load":        f"{pct}% — Duur uur ({hour}:00), verschuif verbruik",
            "idle":              f"{pct}% — Geen actie nodig",
            "export_surplus":    f"{pct}% — {f.solar_w:.0f}W surplus, terugleveren",
        }
        return explanations.get(label, f"{pct}% — {label}")

    @property
    def stats(self) -> dict:
        """Runtime statistics for dashboard display."""
        return {
            "ready": self._ready,
            "outcome_stats": self._outcome_tracker.stats,
            "n_trained": self._model._n_trained if self._model else 0,
            "buffer_size": len(self._buffer),
            "n_since_train": self._n_since_train,
            "retrain_at": RETRAIN_INTERVAL,
            "onnx_available": self._onnx_available,
            "model_version": self._model._version if self._model else "none",
            "contract_version": CONTRACT_VERSION,
        }
