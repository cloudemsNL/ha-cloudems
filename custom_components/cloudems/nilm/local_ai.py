"""Local AI (scikit-learn) NILM classifier for CloudEMS."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
import json
import os
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from collections import deque

_LOGGER = logging.getLogger(__name__)

try:
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    import pickle
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    _LOGGER.warning("scikit-learn not available, local AI disabled")


@dataclass
class PowerEvent:
    """A detected change in power consumption."""
    timestamp: float
    delta_power: float       # Watt - positive = on, negative = off
    rise_time: float         # seconds
    duration: float          # seconds before next event
    peak_power: float        # peak Watt during event
    rms_power: float         # average Watt during event
    phase: str               # L1, L2, L3


class LocalAIClassifier:
    """
    Local AI classifier using Random Forest trained on power event features.
    Falls back to heuristic if not enough training data.
    """

    FEATURE_NAMES = [
        "delta_power", "rise_time", "fall_time", "peak_power",
        "rms_power", "duration", "time_of_day_sin", "time_of_day_cos",
        "day_of_week", "delta_normalized",
    ]

    MIN_TRAINING_SAMPLES = 50

    def __init__(self, model_path: str):
        self._model_path = model_path
        self._model: Optional[Pipeline] = None
        self._label_map: Dict[int, str] = {}
        self._training_data: List[Dict] = []
        self._is_trained = False
        self._event_buffer: deque = deque(maxlen=1000)

        if SKLEARN_AVAILABLE:
            self._load_or_create_model()

    def _load_or_create_model(self):
        """Load existing model or create new one."""
        model_file = os.path.join(self._model_path, "nilm_local_model.pkl")
        labels_file = os.path.join(self._model_path, "nilm_labels.json")

        if os.path.exists(model_file) and os.path.exists(labels_file):
            try:
                with open(model_file, "rb") as f:
                    self._model = pickle.load(f)
                with open(labels_file, "r") as f:
                    self._label_map = {int(k): v for k, v in json.load(f).items()}
                self._is_trained = True
                _LOGGER.info("CloudEMS: Loaded local AI model from %s", self._model_path)
            except Exception as e:
                _LOGGER.warning("Could not load local AI model: %s", e)
                self._create_new_model()
        else:
            self._create_new_model()

    def _create_new_model(self):
        """Create a new untrained model pipeline."""
        if not SKLEARN_AVAILABLE:
            return
        self._model = Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=3,
                random_state=42,
                n_jobs=-1,
            )),
        ])
        self._is_trained = False
        _LOGGER.info("CloudEMS: Created new local AI model (not yet trained)")

    def _extract_features(self, event: PowerEvent) -> List[float]:
        """Extract feature vector from a power event."""
        import math
        time_angle = (event.timestamp % 86400) / 86400 * 2 * math.pi
        day_of_week = (int(event.timestamp / 86400)) % 7

        return [
            event.delta_power,
            event.rise_time,
            event.duration,
            event.peak_power,
            event.rms_power,
            event.duration,
            math.sin(time_angle),
            math.cos(time_angle),
            day_of_week,
            event.delta_power / max(abs(event.peak_power), 1.0),
        ]

    def add_training_sample(self, event: PowerEvent, confirmed_device_type: str):
        """Add a confirmed device identification as training data."""
        features = self._extract_features(event)
        self._training_data.append({
            "features": features,
            "label": confirmed_device_type,
        })
        _LOGGER.debug("Added training sample for %s (total: %d)",
                      confirmed_device_type, len(self._training_data))

        if len(self._training_data) >= self.MIN_TRAINING_SAMPLES:
            self._retrain()

    def _retrain(self):
        """Retrain the model with accumulated training data."""
        if not SKLEARN_AVAILABLE or len(self._training_data) < self.MIN_TRAINING_SAMPLES:
            return

        try:
            labels = list(set(d["label"] for d in self._training_data))
            label_to_int = {l: i for i, l in enumerate(labels)}
            self._label_map = {i: l for l, i in label_to_int.items()}

            X = np.array([d["features"] for d in self._training_data])
            y = np.array([label_to_int[d["label"]] for d in self._training_data])

            self._model.fit(X, y)
            self._is_trained = True
            self._save_model()
            _LOGGER.info("CloudEMS: Local AI model retrained with %d samples", len(X))
        except Exception as e:
            _LOGGER.error("Error retraining local AI model: %s", e)

    def _save_model(self):
        """Save model to disk."""
        if not SKLEARN_AVAILABLE or not self._is_trained:
            return
        try:
            os.makedirs(self._model_path, exist_ok=True)
            with open(os.path.join(self._model_path, "nilm_local_model.pkl"), "wb") as f:
                pickle.dump(self._model, f)
            with open(os.path.join(self._model_path, "nilm_labels.json"), "w") as f:
                json.dump(self._label_map, f)
        except Exception as e:
            _LOGGER.error("Error saving local AI model: %s", e)

    def classify(self, event: PowerEvent) -> List[Dict]:
        """Classify a power event. Returns list of {device_type, confidence}."""
        if not SKLEARN_AVAILABLE:
            return []

        if not self._is_trained:
            _LOGGER.debug("Local AI model not yet trained, skipping")
            return []

        try:
            features = np.array([self._extract_features(event)])
            proba = self._model.predict_proba(features)[0]
            results = []
            for class_idx, confidence in enumerate(proba):
                if confidence > 0.1:
                    device_type = self._label_map.get(class_idx, "unknown")
                    results.append({
                        "device_type": device_type,
                        "name": f"Local AI: {device_type}",
                        "confidence": round(float(confidence), 3),
                        "source": "local_ai",
                    })
            results.sort(key=lambda x: x["confidence"], reverse=True)
            return results[:3]
        except Exception as e:
            _LOGGER.error("Local AI classification error: %s", e)
            return []

    @property
    def is_available(self) -> bool:
        return SKLEARN_AVAILABLE and self._is_trained

    @property
    def training_samples(self) -> int:
        return len(self._training_data)
