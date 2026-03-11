# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS — Pure Python NILM Classifier (v2.0.0)

Vervangt de scikit-learn/numpy implementatie door een volledige
pure-Python oplossing. Geen externe afhankelijkheden.

Algoritme: gewogen k-Nearest Neighbors (k=5) met Manhattan distance.
Normalisatie: min-max per feature (opgeslagen naast trainingsdata).
Opslag: JSON — geen pickle, geen binaire bestanden.

Copyright 2025-2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class PowerEvent:
    """Een gedetecteerde vermogenswijziging."""
    timestamp:   float
    delta_power: float
    rise_time:   float
    duration:    float
    peak_power:  float
    rms_power:   float
    phase:       str
    # v2.2 — ESPHome 1kHz meter extra features (None = niet beschikbaar)
    power_factor:       float | None = None   # cos φ  0.0–1.0
    inrush_peak_a:      float | None = None   # piekstroom bij opstarten (A)
    # v4.5 — Reactief vermogen + THD: V-I trajectory benadering via P1-signaal.
    # Reactief vermogen Q (VAR) en Total Harmonic Distortion (%) zijn proxies
    # voor de V-I vingerafdruk — ze discrimineren o.a.:
    #   • motor-apparaten (wasmachine, droger): hoog Q bij opstarten
    #   • resistief (ketel, oven): Q ≈ 0, THD laag
    #   • elektronische lasten (laptop, TV): hoog THD, laag Q
    # Geen raw waveforms nodig — beschikbaar via DSMR P1 of ESPHome 1kHz meter.
    reactive_power_var: float | None = None   # Q in VAR  (negatief = capacitief)
    thd_pct:            float | None = None   # THD% totale harmonische vervorming


def _extract_features(event: PowerEvent) -> List[float]:
    angle = (event.timestamp % 86400) / 86400 * 2 * math.pi
    dow   = int(event.timestamp / 86400) % 7
    feats = [
        event.delta_power,
        event.rise_time,
        event.duration,
        event.peak_power,
        event.rms_power,
        event.duration,
        math.sin(angle),
        math.cos(angle),
        float(dow),
        event.delta_power / max(abs(event.peak_power), 1.0),
    ]
    # Optionele ESPHome-features: alleen toevoegen als beschikbaar
    # (backward compatible — bestaande modellen zien ze niet)
    if event.power_factor is not None:
        feats.append(float(event.power_factor))
    if event.inrush_peak_a is not None:
        # Genormaliseerd: inrush_ratio = piek / (delta_power/230 * √2)
        rated_a = abs(event.delta_power) / 230.0 * 1.414
        feats.append(event.inrush_peak_a / max(rated_a, 0.1))

    # v4.5 — V-I trajectory benadering via reactief vermogen + THD
    # Feature: reactive_fraction = Q / S (waarbij S = schijnbaar vermogen)
    # Discrimineert: motor-apparaten (hoog Q), resistief (Q≈0), elektronisch (hoog THD)
    # Formule: sin(φ) = Q / sqrt(P² + Q²) — geeft de hoek in het vermogensvlak
    p_abs = abs(event.delta_power)
    if event.reactive_power_var is not None:
        q = abs(event.reactive_power_var)
        s = math.sqrt(p_abs ** 2 + q ** 2)
        # sin(phi): 0.0 = puur resistief (ketel), 1.0 = puur reactief (motor)
        feats.append(q / max(s, 1.0))
        # Teken van Q: positief = inductief (motor), negatief = capacitief (condensator)
        feats.append(math.copysign(1.0, event.reactive_power_var))

    if event.thd_pct is not None:
        # THD genormaliseerd: 0–100% → 0.0–1.0
        # Hoog THD (>20%): elektronische lasten (laptop, LED-driver, TV)
        # Laag THD (<5%): resistief of motor
        feats.append(min(event.thd_pct / 100.0, 1.0))

    return feats


class _Normalizer:
    def __init__(self) -> None:
        self._min: List[float] = []
        self._max: List[float] = []

    def fit(self, rows: List[List[float]]) -> None:
        if not rows:
            return
        n = len(rows[0])
        self._min = [min(r[i] for r in rows) for i in range(n)]
        self._max = [max(r[i] for r in rows) for i in range(n)]

    def transform(self, row: List[float]) -> List[float]:
        if not self._min:
            return row
        result = []
        for i, v in enumerate(row):
            lo, hi = self._min[i], self._max[i]
            result.append((v - lo) / (hi - lo) if hi != lo else 0.0)
        return result

    def to_dict(self) -> dict:
        return {"min": self._min, "max": self._max}

    def from_dict(self, d: dict) -> None:
        self._min = d.get("min", [])
        self._max = d.get("max", [])


def _manhattan(a: List[float], b: List[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b))


class _KNNClassifier:
    """Gewogen k-Nearest Neighbors — gewicht = 1/(1+afstand)."""

    def __init__(self, k: int = 5) -> None:
        self._k  = k
        self._X: List[List[float]] = []
        self._y: List[str] = []

    def fit(self, X: List[List[float]], y: List[str]) -> None:
        self._X = X
        self._y = y

    def predict_proba(self, x: List[float]) -> Dict[str, float]:
        if not self._X:
            return {}
        dists = sorted(
            ((i, _manhattan(x, xi)) for i, xi in enumerate(self._X)),
            key=lambda t: t[1],
        )
        scores: Dict[str, float] = {}
        for idx, dist in dists[:self._k]:
            label  = self._y[idx]
            weight = 1.0 / (1.0 + dist)
            scores[label] = scores.get(label, 0.0) + weight
        total = sum(scores.values()) or 1.0
        return {k: round(v / total, 4) for k, v in scores.items()}

    def to_dict(self) -> dict:
        return {"X": self._X, "y": self._y, "k": self._k}

    def from_dict(self, d: dict) -> None:
        self._X = d.get("X", [])
        self._y = d.get("y", [])
        self._k = d.get("k", self._k)


class LocalAIClassifier:
    """
    Pure Python NILM classifier — geen numpy, geen sklearn, geen pickle.
    Werkt op elke HA-installatie zonder extra installatie.
    """

    MIN_TRAINING_SAMPLES = 20

    def __init__(self, model_path: str) -> None:
        self._model_path     = model_path
        self._knn            = _KNNClassifier(k=5)
        self._norm           = _Normalizer()
        self._is_trained     = False
        self._training_data: List[Dict] = []
        self._event_buffer: deque = deque(maxlen=1000)
        self._load()

    def _model_file(self) -> str:
        return os.path.join(self._model_path, "nilm_local_model.json")

    def _load(self) -> None:
        path = self._model_file()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._knn.from_dict(data.get("knn", {}))
            self._norm.from_dict(data.get("norm", {}))
            self._training_data = data.get("training", [])
            if self._knn._X:
                self._is_trained = True
                _LOGGER.info("CloudEMS local AI geladen: %d samples", len(self._training_data))
        except Exception as err:
            _LOGGER.warning("Local AI model laden mislukt: %s", err)

    def _save(self) -> None:
        try:
            os.makedirs(self._model_path, exist_ok=True)
            with open(self._model_file(), "w", encoding="utf-8") as f:
                json.dump({
                    "knn":      self._knn.to_dict(),
                    "norm":     self._norm.to_dict(),
                    "training": self._training_data[-500:],
                    "version":  "2.0",
                }, f)
        except Exception as err:
            _LOGGER.error("Local AI opslaan mislukt: %s", err)

    def add_training_sample(
        self,
        event: PowerEvent,
        confirmed_device_type: str,
        device_id: str = "",
    ) -> None:
        """Voeg een trainingsample toe en hertraïn indien voldoende data.

        v4.5: device_id wordt opgeslagen zodat relabel_device() bestaande
        samples kan bijwerken als de gebruiker een type corrigeert.
        """
        features = _extract_features(event)
        self._training_data.append({
            "features":  features,
            "label":     confirmed_device_type,
            "device_id": device_id,   # v4.5: voor relabeling bij type-correctie
        })
        _LOGGER.debug("Training sample: %s device=%s (totaal: %d)",
                      confirmed_device_type, device_id or "?", len(self._training_data))
        if len(self._training_data) >= self.MIN_TRAINING_SAMPLES:
            self._retrain()

    def relabel_device(self, device_id: str, old_type: str, new_type: str) -> int:
        """Hernoem alle trainingssamples van device_id van old_type naar new_type.

        Wordt aangeroepen vanuit set_feedback() als de gebruiker een type corrigeert.
        Voorkomt conflicterende labels in de kNN voor dezelfde feature-vector.

        v4.5 fix: zonder dit zouden bestaande samples het oude type blijven leren
        terwijl nieuwe samples het nieuwe type leren — de kNN raakt verward.

        Returns: aantal herschreven samples.
        """
        if not device_id or old_type == new_type:
            return 0
        rewritten = 0
        for sample in self._training_data:
            if sample.get("device_id") == device_id and sample.get("label") == old_type:
                sample["label"] = new_type
                rewritten += 1
        if rewritten > 0:
            _LOGGER.info(
                "LocalAI relabel: %s %d samples %s→%s",
                device_id, rewritten, old_type, new_type,
            )
            # Hertraïn direct zodat de correctie onmiddellijk effect heeft
            if len(self._training_data) >= self.MIN_TRAINING_SAMPLES:
                self._retrain()
        return rewritten

    def _retrain(self) -> None:
        rows   = [d["features"] for d in self._training_data]
        labels = [d["label"]    for d in self._training_data]
        self._norm.fit(rows)
        X_norm = [self._norm.transform(r) for r in rows]
        self._knn.fit(X_norm, labels)
        self._is_trained = True
        self._save()
        _LOGGER.info("CloudEMS local AI hertraind: %d samples, %d klassen",
                     len(rows), len(set(labels)))

    def classify(self, event: PowerEvent) -> List[Dict]:
        if not self._is_trained:
            return []
        try:
            x_norm = self._norm.transform(_extract_features(event))
            proba  = self._knn.predict_proba(x_norm)
            results = [
                {"device_type": dt, "name": f"Local AI: {dt}",
                 "confidence": conf, "source": "local_ai"}
                for dt, conf in proba.items() if conf > 0.1
            ]
            results.sort(key=lambda x: x["confidence"], reverse=True)
            return results[:3]
        except Exception as err:
            _LOGGER.error("Local AI classificatie fout: %s", err)
            return []

    @property
    def is_available(self) -> bool:
        return self._is_trained

    @property
    def training_samples(self) -> int:
        return len(self._training_data)
