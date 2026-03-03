"""
CloudEMS Power Calculator — v1.4.0

Handles:
  - Auto-scaling: sensors that report in W or kW (self-learning per entity)
  - P = U * I  derivation when only two of three values are known
  - U = P / I  derivation
  - I = P / U  derivation  (most common: fix ampere underreading)
  - Per-phase fallback voltage (default 230 V NL)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

DEFAULT_VOLTAGE_V = 230.0   # NL/EU mains voltage

# If a sensor consistently returns values below this we assume it's in kW
KW_THRESHOLD = 50.0         # values < 50 → likely kW


@dataclass
class ScaleState:
    """Tracks whether an entity reports in W or kW (self-learning)."""
    entity_id: str
    is_kw: bool = False
    samples: int = 0
    _sum: float = field(default=0.0, repr=False)

    def update(self, raw: float) -> None:
        """Feed a new raw value and update W/kW determination."""
        self._sum += abs(raw)
        self.samples += 1
        if self.samples >= 5:
            avg = self._sum / self.samples
            self.is_kw = avg < KW_THRESHOLD
            if self.samples % 100 == 0:
                _LOGGER.debug(
                    "CloudEMS scale: %s avg=%.2f → %s",
                    self.entity_id, avg, "kW" if self.is_kw else "W"
                )

    def to_watts(self, raw: float) -> float:
        """Return value normalised to Watts."""
        return raw * 1000.0 if self.is_kw else raw


class PowerCalculator:
    """
    Resolves power (W), voltage (V) and current (A) using P = U * I.

    Each phase has its own scale tracker so kW/W is detected independently.
    """

    def __init__(self, default_voltage: float = DEFAULT_VOLTAGE_V):
        self._default_v = default_voltage
        self._scale: dict[str, ScaleState] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def to_watts(self, entity_id: str, raw: float) -> float:
        """Feed raw sensor value; return normalised Watts."""
        st = self._scale.setdefault(entity_id, ScaleState(entity_id=entity_id))
        st.update(raw)
        return st.to_watts(raw)

    def is_kw(self, entity_id: str) -> bool:
        return self._scale.get(entity_id, ScaleState(entity_id=entity_id)).is_kw

    @staticmethod
    def derive_current(power_w: Optional[float], voltage_v: Optional[float],
                       default_v: float = DEFAULT_VOLTAGE_V) -> Optional[float]:
        """
        I = P / U
        Used when only power is available (most common case).
        Falls back to default_v (230 V) when no voltage sensor.
        """
        if power_w is None:
            return None
        v = voltage_v if (voltage_v and voltage_v > 50) else default_v
        if v == 0:
            return None
        return round(power_w / v, 3)

    @staticmethod
    def derive_power(current_a: Optional[float], voltage_v: Optional[float],
                     default_v: float = DEFAULT_VOLTAGE_V) -> Optional[float]:
        """P = U * I"""
        if current_a is None:
            return None
        v = voltage_v if (voltage_v and voltage_v > 50) else default_v
        return round(current_a * v, 1)

    @staticmethod
    def derive_voltage(power_w: Optional[float],
                       current_a: Optional[float]) -> Optional[float]:
        """U = P / I"""
        if power_w is None or current_a is None or current_a == 0:
            return None
        return round(power_w / current_a, 1)

    def resolve_phase(
        self,
        phase: str,
        *,
        power_entity: Optional[str] = None,
        raw_power: Optional[float] = None,
        raw_current: Optional[float] = None,
        raw_voltage: Optional[float] = None,
    ) -> dict:
        """
        Given whichever values are available, derive the missing ones.
        Returns dict with keys: power_w, current_a, voltage_v, derived_from
        """
        # Normalise power
        power_w: Optional[float] = None
        if raw_power is not None and power_entity:
            power_w = self.to_watts(power_entity, raw_power)
        elif raw_power is not None:
            power_w = raw_power

        voltage_v = raw_voltage if (raw_voltage and raw_voltage > 50) else self._default_v
        current_a = raw_current
        derived_from: list[str] = []

        # Case 1: have P and U → derive I
        if power_w is not None and current_a is None:
            current_a = self.derive_current(power_w, voltage_v, self._default_v)
            derived_from.append("I=P/U")

        # Case 2: have I and U → derive P
        elif current_a is not None and power_w is None:
            power_w = self.derive_power(current_a, voltage_v, self._default_v)
            derived_from.append("P=U*I")

        # Case 3: have P and I → derive U
        if power_w is not None and current_a is not None and raw_voltage is None:
            derived_v = self.derive_voltage(power_w, current_a)
            if derived_v:
                voltage_v = derived_v
                derived_from.append("U=P/I")

        return {
            "power_w":    round(power_w, 1) if power_w is not None else None,
            "current_a":  round(current_a, 3) if current_a is not None else None,
            "voltage_v":  round(voltage_v, 1) if voltage_v is not None else None,
            "derived_from": ", ".join(derived_from) if derived_from else "direct",
        }
