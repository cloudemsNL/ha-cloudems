"""
CloudEMS AI Confidence Bootstrap — v1.0.0

Provides initial confidence estimates before the k-NN model has enough data.
Uses simple but reliable heuristics based on time-of-day, day-of-week,
and the last few observations — no training required.

This prevents the model from being useless for the first few days.
Once k-NN has >= 200 samples, the bootstrap confidence is blended in
rather than used standalone.

Heuristics:
  - Solar hours (9:00–17:00) → charge_battery / export_surplus likely
  - Evening peak (17:00–21:00) → discharge_battery likely
  - Night (22:00–6:00) → idle likely
  - Price spike (> 1.5× daily avg) → defer_load / discharge likely
  - Price dip (< 0.5× daily avg) → charge_battery likely
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Minimum k-NN samples before bootstrap is deprecated (blended instead)
from ..const import BOOTSTRAP_STANDALONE_SAMPLES as BOOTSTRAP_STANDALONE_MAX, BOOTSTRAP_BLEND_SAMPLES as BOOTSTRAP_BLEND_MAX


class ConfidenceBootstrap:
    """
    Fast heuristic confidence estimates for cold-start situations.

    Returns (label, confidence) without any training data.
    Confidence is intentionally conservative (0.3–0.6) so safety rules
    and EPEX rules still dominate.
    """

    def predict(
        self,
        hour:          int,
        solar_w:       float,
        battery_soc:   float,
        epex_now:      float,
        epex_avg:      float,
        grid_w:        float,
        boiler_temp:   float,
        n_knn_samples: int,
    ) -> tuple[str, float]:
        """
        Returns (label, confidence). Confidence is 0.0 if bootstrap
        should not be used (k-NN has enough data).
        """
        # Phase out bootstrap as k-NN gains samples
        if n_knn_samples >= BOOTSTRAP_BLEND_MAX:
            return "idle", 0.0

        # Scale confidence based on how much k-NN data we have
        scale = 1.0 - (n_knn_samples / BOOTSTRAP_BLEND_MAX)
        # Cap at 0.55 so k-NN always wins when confident
        max_conf = 0.55 * scale

        label, raw_conf = self._heuristic(
            hour, solar_w, battery_soc, epex_now, epex_avg, grid_w, boiler_temp
        )
        return label, min(max_conf, raw_conf)

    def _heuristic(
        self,
        hour:        int,
        solar_w:     float,
        soc:         float,
        epex_now:    float,
        epex_avg:    float,
        grid_w:      float,
        boiler_temp: float,
    ) -> tuple[str, float]:

        price_ratio = (epex_now / epex_avg) if epex_avg > 0.01 else 1.0

        # Price spike → discharge or defer
        if price_ratio > 1.5 and soc > 40:
            return "discharge_battery", 0.55

        # Price dip → charge
        if price_ratio < 0.5 and soc < 90:
            return "charge_battery", 0.55

        # Negative price → definitely charge
        if epex_now < 0 and soc < 95:
            return "charge_battery", 0.60

        # Strong solar surplus → charge battery or export
        if solar_w > 1500 and grid_w < -800:
            if soc < 80:
                return "charge_battery", 0.50
            return "export_surplus", 0.45

        # Solar hours, moderate production → run boiler if cool
        if 9 <= hour <= 15 and solar_w > 500 and boiler_temp < 55:
            return "run_boiler", 0.45

        # Evening peak → discharge if price is above avg
        if 17 <= hour <= 21 and price_ratio > 1.1 and soc > 30:
            return "discharge_battery", 0.45

        # Night → idle
        if hour >= 22 or hour <= 5:
            return "idle", 0.50

        return "idle", 0.30


def blend_predictions(
    bootstrap: tuple[str, float],
    knn: tuple[str, float],
    n_samples: int,
) -> tuple[str, float]:
    """
    Blend bootstrap and k-NN predictions during the transition period.
    As n_samples grows, k-NN gets more weight.
    """
    b_label, b_conf = bootstrap
    k_label, k_conf = knn

    if n_samples < BOOTSTRAP_STANDALONE_MAX:
        # k-NN not reliable yet — use bootstrap if more confident
        if b_conf > k_conf:
            return b_label, b_conf
        return k_label, k_conf

    # Blend: k-NN weight grows linearly from 0.5 to 1.0
    knn_weight = 0.5 + 0.5 * min(1.0, (n_samples - BOOTSTRAP_STANDALONE_MAX) /
                                  (BOOTSTRAP_BLEND_MAX - BOOTSTRAP_STANDALONE_MAX))
    boot_weight = 1.0 - knn_weight

    if k_label == b_label:
        # Agreement → boost confidence
        blended_conf = k_conf * knn_weight + b_conf * boot_weight
        return k_label, min(0.95, blended_conf * 1.15)

    # Disagreement → higher weight wins
    if k_conf * knn_weight >= b_conf * boot_weight:
        return k_label, k_conf
    return b_label, b_conf
