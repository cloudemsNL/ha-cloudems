# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
signal_integrity.py — v4.6.533

Twee gerelateerde modules voor signaalintegriteit:

1. GridFeedbackLoopDetector
   Detecteert als een CloudEMS-eigen sensor als input terugkomt.
   Bijv. sensor.cloudems_house_power geconfigureerd als grid-sensor.
   Dit is de stilste fout: alles lijkt te werken maar data klopt niet.

2. SignConsistencyLearner
   Leert of het teken van elke sensor consistent is met de fysieke werkelijkheid.
   Solar kan nooit negatief zijn. Batterij heeft verwacht laad/ontlaad patroon.
   Detecteert omgekeerde sensoren vroeg.

Beide modules hebben cloud-sync via CloudSyncMixin.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cloud_sync_mixin import CloudSyncMixin

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_FB   = "cloudems_feedback_loop_v1"
STORAGE_KEY_SIGN = "cloudems_sign_consistency_v1"
STORAGE_VERSION  = 1

EMA_ALPHA    = 0.10
MIN_SAMPLES  = 30
SAVE_INTERVAL = 30

# Sensoren die fysiek nooit negatief kunnen zijn
ALWAYS_POSITIVE = {"solar", "pv"}
# Sensoren waarvan het teken van de context afhangt
BIDIRECTIONAL   = {"battery", "grid"}

# Correlation threshold voor feedback loop detectie
FEEDBACK_CORR_MIN = 0.95    # >95% correlatie = waarschijnlijk feedback
FEEDBACK_SAMPLES  = 50      # minimum samples voor uitspraak


# ─────────────────────────────────────────────────────────────────────────────
# GridFeedbackLoopDetector
# ─────────────────────────────────────────────────────────────────────────────

class GridFeedbackLoopDetector(CloudSyncMixin):
    """
    Detecteert feedback loops: CloudEMS-afgeleide waarden die als input
    terugkomen in de meting.

    Methode: pearson-correlatie tussen CloudEMS-outputwaarden en
    geconfigureerde inputsensoren over een rollend venster.
    Hoge correlatie + lage fase-verschuiving = feedback.
    """

    _cloud_module_name = "grid_feedback_loop"

    def __init__(self, hass, config: dict, hint_engine=None) -> None:
        self._hass   = hass
        self._config = config
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()

        # {sensor_key: deque van (cloudems_val, sensor_val)}
        self._buffers: Dict[str, deque] = {}
        self._detected: Dict[str, bool] = {}
        self._sample_counts: Dict[str, int] = {}
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    def observe(
        self,
        cloudems_house_w: Optional[float],
        cloudems_grid_w:  Optional[float],
        sensor_readings:  Dict[str, Optional[float]],   # {config_key: waarde}
    ) -> List[str]:
        """
        Vergelijk CloudEMS-outputwaarden met geconfigureerde inputsensoren.
        Geeft lijst van gedetecteerde feedback-loops terug.
        """
        detected_loops = []
        cloudems_outputs = {
            "house": cloudems_house_w,
            "grid":  cloudems_grid_w,
        }

        for sensor_key, sensor_val in sensor_readings.items():
            if sensor_val is None:
                continue
            for output_name, output_val in cloudems_outputs.items():
                if output_val is None:
                    continue
                buf_key = f"{sensor_key}_vs_{output_name}"
                if buf_key not in self._buffers:
                    self._buffers[buf_key]       = deque(maxlen=FEEDBACK_SAMPLES)
                    self._detected[buf_key]       = False
                    self._sample_counts[buf_key]  = 0

                self._buffers[buf_key].append((output_val, sensor_val))
                self._sample_counts[buf_key] += 1
                self._dirty_count += 1

                if self._sample_counts[buf_key] >= FEEDBACK_SAMPLES:
                    corr = self._pearson(list(self._buffers[buf_key]))
                    was_detected = self._detected[buf_key]

                    if corr > FEEDBACK_CORR_MIN and not was_detected:
                        self._detected[buf_key] = True
                        detected_loops.append(buf_key)
                        self._emit_hint(sensor_key, output_name, corr)
                        self._log(sensor_key, output_name, corr)
                    elif corr < 0.80 and was_detected:
                        self._detected[buf_key] = False

        return detected_loops

    @staticmethod
    def _pearson(pairs: List[tuple]) -> float:
        """Berekent pearson-correlatie van (x, y) paren."""
        n = len(pairs)
        if n < 10:
            return 0.0
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx  = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
        sy  = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
        if sx < 0.01 or sy < 0.01:
            return 0.0
        return cov / (n * sx * sy)

    def _emit_hint(self, sensor_key: str, output_name: str, corr: float) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"feedback_loop_{sensor_key}_{output_name}",
                title      = "Feedback loop gedetecteerd in sensor-configuratie",
                message    = (
                    f"De sensor '{sensor_key}' correleert {corr*100:.0f}% met "
                    f"de CloudEMS-berekende '{output_name}' waarde. "
                    f"Mogelijk is een CloudEMS-afgeleide sensor als input geconfigureerd, "
                    f"waardoor een feedback loop ontstaat. "
                    f"Controleer of de geconfigureerde sensor een ruwe meting levert "
                    f"en niet een CloudEMS-berekening."
                ),
                action     = f"Controleer sensor '{sensor_key}' in CloudEMS configuratie",
                confidence = min(0.95, corr),
            )
        except Exception as _e:
            _LOGGER.debug("FeedbackLoop hint fout: %s", _e)

    def _log(self, sensor_key: str, output_name: str, corr: float) -> None:
        msg = (
            f"GridFeedbackLoopDetector: feedback loop {sensor_key}↔{output_name} "
            f"(correlatie {corr:.3f})"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "feedback_loop",
                    action   = "loop_detected",
                    reason   = f"{sensor_key}_vs_{output_name}",
                    message  = msg,
                    extra    = {"sensor_key": sensor_key, "output": output_name,
                                "correlation": round(corr, 3)},
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            "detected_loops": sum(1 for v in self._detected.values() if v),
            "total_pairs":    len(self._detected),
        }

    def get_diagnostics(self) -> dict:
        return {
            k: {"detected": v, "samples": self._sample_counts.get(k, 0)}
            for k, v in self._detected.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# SignConsistencyLearner
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignStats:
    positive_count: int = 0
    negative_count: int = 0
    zero_count:     int = 0
    classification: str = "learning"
    confidence:     float = 0.0

    def total(self) -> int:
        return self.positive_count + self.negative_count + self.zero_count

    def positive_fraction(self) -> float:
        t = self.total() - self.zero_count
        return self.positive_count / t if t > 0 else 0.5

    def to_dict(self) -> dict:
        return {
            "pos": self.positive_count,
            "neg": self.negative_count,
            "zer": self.zero_count,
            "cls": self.classification,
            "conf": round(self.confidence, 3),
        }

    def from_dict(self, d: dict) -> None:
        self.positive_count = int(d.get("pos", 0))
        self.negative_count = int(d.get("neg", 0))
        self.zero_count     = int(d.get("zer", 0))
        self.classification = d.get("cls", "learning")
        self.confidence     = float(d.get("conf", 0.0))


class SignConsistencyLearner(CloudSyncMixin):
    """
    Leert of het teken van elke sensor consistent is met de
    fysieke werkelijkheid. Detecteert omgekeerde sensoren.
    """

    _cloud_module_name = "sign_consistency"

    SENSOR_RULES = {
        "solar":   {"expected": "always_positive", "hint": "Solar kan nooit negatief zijn."},
        "pv":      {"expected": "always_positive", "hint": "PV kan nooit negatief zijn."},
        "battery": {"expected": "bidirectional",   "hint": "Batterij is bidirectioneel."},
        "grid":    {"expected": "bidirectional",   "hint": "Grid is bidirectioneel."},
        "house":   {"expected": "always_positive", "hint": "Huisverbruik is altijd positief."},
    }

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._state: Dict[str, SignStats] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_SIGN)
        data = await self._store.async_load()
        if data:
            for sensor_type, d in data.items():
                self._state[sensor_type] = SignStats()
                self._state[sensor_type].from_dict(d)

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {k: v.to_dict() for k, v in self._state.items()}
            )
            self._dirty_count = 0

    def observe(
        self,
        sensor_type: str,
        value: Optional[float],
    ) -> Optional[str]:
        """
        Verwerk één meting.
        Geeft classificatie terug: 'ok' / 'inverted' / 'suspicious' / 'learning'
        """
        if value is None:
            return None

        if sensor_type not in self._state:
            self._state[sensor_type] = SignStats()

        st = self._state[sensor_type]
        if value > 5.0:
            st.positive_count += 1
        elif value < -5.0:
            st.negative_count += 1
        else:
            st.zero_count += 1
        self._dirty_count += 1

        if st.total() < MIN_SAMPLES:
            return "learning"

        rule = self.SENSOR_RULES.get(sensor_type)
        if not rule:
            return "unknown"

        old_class = st.classification
        pos_frac  = st.positive_fraction()

        if rule["expected"] == "always_positive":
            if pos_frac > 0.97:
                st.classification = "ok"
                st.confidence     = min(0.99, pos_frac)
            elif pos_frac < 0.05:
                st.classification = "inverted"
                st.confidence     = min(0.95, 1.0 - pos_frac)
            else:
                st.classification = "suspicious"
                st.confidence     = 0.5
        else:   # bidirectional
            if 0.05 < pos_frac < 0.95:
                st.classification = "ok"
                st.confidence     = 0.80
            elif pos_frac > 0.98:
                st.classification = "suspicious_always_positive"
                st.confidence     = 0.70
            elif pos_frac < 0.02:
                st.classification = "suspicious_always_negative"
                st.confidence     = 0.70

        if st.classification != old_class:
            self._on_classification_change(sensor_type, st, rule)

        return st.classification

    def _on_classification_change(
        self,
        sensor_type: str,
        st: SignStats,
        rule: dict,
    ) -> None:
        msg = (
            f"SignConsistencyLearner: {sensor_type} → {st.classification} "
            f"(pos_frac={st.positive_fraction():.2f}, n={st.total()})"
        )
        _LOGGER.info(msg)

        if st.classification in ("inverted", "suspicious") and self._hint_engine:
            try:
                self._hint_engine._emit_hint(
                    hint_id    = f"sign_consistency_{sensor_type}",
                    title      = f"Sensor-teken afwijking: {sensor_type}",
                    message    = (
                        f"De {sensor_type}-sensor toont {st.negative_count} negatieve "
                        f"en {st.positive_count} positieve metingen. "
                        f"{rule['hint']} "
                        f"Controleer of de sensor het juiste teken heeft "
                        f"(import positief, export negatief)."
                    ),
                    action     = f"Controleer teken van {sensor_type}-sensor",
                    confidence = st.confidence,
                )
            except Exception as _e:
                _LOGGER.debug("SignConsistency hint fout: %s", _e)

        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "sign_consistency",
                    action   = st.classification,
                    reason   = sensor_type,
                    message  = msg,
                    extra    = {
                        "sensor_type":   sensor_type,
                        "classification": st.classification,
                        "pos_frac":       round(st.positive_fraction(), 3),
                        "samples":        st.total(),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        return {
            k: {
                "classification": v.classification,
                "pos_frac":       round(v.positive_fraction(), 2),
                "samples":        v.total(),
            }
            for k, v in self._state.items()
            if v.total() >= MIN_SAMPLES
        }

    def _apply_prior(self, data: dict) -> None:
        """Verwerk cloud-prior: gebruik verwachte tekenrichting als startwaarde."""
        pass   # Sign-regels zijn deterministische fysica — geen prior nodig

    def get_diagnostics(self) -> dict:
        return {k: v.to_dict() for k, v in self._state.items()}
