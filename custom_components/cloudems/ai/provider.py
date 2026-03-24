"""
CloudEMS AI Provider — Base classes and model contract.

The model contract defines the input/output format that is identical between
local ONNX models and cloud-trained community models. This ensures a cloud-trained
model can be dropped in locally without any code changes.

Architecture:
  AIProvider (abstract)
    ├── OnnxProvider       — default, trains on HA recorder data, fully offline
    ├── OllamaProvider     — local LLM (future)
    ├── OpenAIProvider     — cloud LLM (future)
    └── AdaptiveHomeProvider — community model from cloudems.eu (future)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


# ── Model contract ────────────────────────────────────────────────────────────
# Input features and output format are IDENTICAL between local and cloud variants.
# Never change field names without bumping CONTRACT_VERSION.

CONTRACT_VERSION = "1.0"

@dataclass
class AIModelContract:
    """
    Standard input feature vector for all CloudEMS AI models.
    Identical between local ONNX and cloud community models.
    """
    # Time features
    hour_of_day: float          # 0–23
    day_of_week: float          # 0=mon … 6=sun
    month: float                # 1–12
    is_weekend: float           # 0 or 1

    # Power features (W)
    grid_w: float               # positive=import, negative=export
    solar_w: float
    battery_w: float            # positive=charging, negative=discharging
    battery_soc_pct: float      # 0–100
    house_load_w: float

    # Price features (€/kWh)
    epex_now: float
    epex_next_hour: float
    epex_avg_today: float

    # Phase features (A)
    l1_a: float
    l2_a: float
    l3_a: float

    # Weather features
    temp_outside: float         # °C
    cloud_cover_pct: float      # 0–100
    pv_forecast_w: float        # forecast for next hour

    # NILM context
    nilm_active_count: int      # number of active detected devices
    boiler_temp: float          # °C, 0 if unknown

    def to_vector(self) -> list[float]:
        """Serialize to flat float list — order must never change."""
        return [
            self.hour_of_day, self.day_of_week, self.month, self.is_weekend,
            self.grid_w, self.solar_w, self.battery_w, self.battery_soc_pct, self.house_load_w,
            self.epex_now, self.epex_next_hour, self.epex_avg_today,
            self.l1_a, self.l2_a, self.l3_a,
            self.temp_outside, self.cloud_cover_pct, self.pv_forecast_w,
            float(self.nilm_active_count), self.boiler_temp,
        ]

    @classmethod
    def feature_names(cls) -> list[str]:
        """Feature names in vector order — used for ONNX model metadata."""
        return [
            "hour_of_day", "day_of_week", "month", "is_weekend",
            "grid_w", "solar_w", "battery_w", "battery_soc_pct", "house_load_w",
            "epex_now", "epex_next_hour", "epex_avg_today",
            "l1_a", "l2_a", "l3_a",
            "temp_outside", "cloud_cover_pct", "pv_forecast_w",
            "nilm_active_count", "boiler_temp",
        ]

    FEATURE_COUNT = 20  # must match len(feature_names())


@dataclass
class PredictionResult:
    """
    Standard output from all CloudEMS AI models.
    Identical between local ONNX and cloud community models.
    """
    # Primary output
    label: str                  # e.g. "charge_battery", "run_boiler", "idle"
    confidence: float           # 0.0–1.0
    value: float                # numeric output (e.g. recommended power W)

    # Explainability
    explanation: str            # human-readable reason
    top_features: list[str] = field(default_factory=list)  # most influential features
    alternatives: list[dict] = field(default_factory=list) # runner-up predictions

    # Metadata
    model_version: str = "local-untrained"
    contract_version: str = CONTRACT_VERSION
    source: str = "onnx_local"  # "onnx_local" | "onnx_cloud" | "ollama" | "openai" | "adaptive_home"


# ── Abstract provider ─────────────────────────────────────────────────────────

class AIProvider(ABC):
    """
    Abstract base class for all CloudEMS AI providers.

    All providers implement the same interface so CloudEMS doesn't know
    whether it's talking to a local ONNX model or the AdaptiveHome cloud.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._ready = False

    @property
    def is_ready(self) -> bool:
        """True if the provider has a trained model available."""
        return self._ready

    @abstractmethod
    async def async_setup(self) -> None:
        """Initialize the provider — load model if available."""

    @abstractmethod
    async def async_predict(self, features: AIModelContract) -> PredictionResult:
        """Run inference on the given feature vector."""

    @abstractmethod
    async def async_train(self, samples: list[dict[str, Any]]) -> bool:
        """
        Train or fine-tune the model on new samples.
        Each sample is a dict with keys from AIModelContract + 'outcome' label.
        Returns True if training succeeded.
        """

    @abstractmethod
    async def async_explain(self, features: AIModelContract) -> str:
        """Return a human-readable explanation for the last prediction."""

    async def async_shutdown(self) -> None:
        """Optional cleanup on HA shutdown."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, ready={self._ready})"
