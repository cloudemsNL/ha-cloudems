# -*- coding: utf-8 -*-
"""
CloudEMS Power Calculator — v1.10.3

Handles:
  - Auto-scaling: sensors that report in W or kW.
    Priority order:
      1. Read unit_of_measurement attribute from HA state — most reliable.
      2. If UOM is absent/ambiguous, use self-learning statistical detection:
         - values consistently < 50 → assume kW
         - values > 1000 are always Watts even if UOM says "kW" (guards against
           mis-labelled sensors that actually report Watt)
  - P = U × I  derivation when only two of three values are known
  - U = P / I  derivation
  - I = P / U  derivation  (most common: fallback when only power sensor present)
  - Per-phase fallback voltage (configurable, default 230 V NL/EU)
  - Ampere fallback: if no current sensor but power sensor → I = P / V
  - Voltage fallback: if no voltage sensor but power + current → U = P / I

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

DEFAULT_VOLTAGE_V = 230.0   # NL/EU mains voltage

# Statistical kW detection threshold:
# If avg of first N samples is < this → likely kW sensor
KW_STAT_THRESHOLD    = 50.0
# Safety guard: values above this are ALWAYS Watts even if UOM says kW
# (catches mis-configured sensors e.g. GoodWe reporting "1234" with unit "kW")
ALWAYS_WATT_ABOVE    = 800.0   # Values > 800 are always Watts (guards mis-labelled sensors)
# Minimum samples before statistical detection is trusted
STAT_MIN_SAMPLES     = 5

# HA UOM strings that mean kilowatt
_KW_UNITS = {"kw", "kilowatt"}
# HA UOM strings that mean watt (includes common variants)
_W_UNITS  = {"w", "watt", "watts"}


@dataclass
class ScaleState:
    """Tracks whether an entity reports in W or kW, using UOM-first logic."""
    entity_id:  str
    # Determined by UOM: True=kW, False=W, None=unknown (use statistical)
    uom_is_kw:  Optional[bool] = None
    uom_locked: bool           = False   # True once UOM was read successfully

    # Statistical fallback
    is_kw_stat:   bool  = False
    samples:      int   = 0
    _sum:         float = field(default=0.0, repr=False)

    def observe_uom(self, uom: Optional[str]) -> None:
        """Feed the unit_of_measurement string from HA state attributes."""
        if uom is None or self.uom_locked:
            return
        clean = uom.strip().lower()
        if clean in _KW_UNITS:
            self.uom_is_kw  = True
            self.uom_locked = True
            _LOGGER.debug("PowerCalculator: %s → unit is kW (from UOM attr)", self.entity_id)
        elif clean in _W_UNITS:
            self.uom_is_kw  = False
            self.uom_locked = True
            _LOGGER.debug("PowerCalculator: %s → unit is W (from UOM attr)", self.entity_id)
        # If neither, leave uom_is_kw=None → fall through to statistical

    def update_stat(self, raw: float) -> None:
        """Feed raw value for statistical kW/W learning."""
        self._sum += abs(raw)
        self.samples += 1
        if self.samples >= STAT_MIN_SAMPLES:
            avg = self._sum / self.samples
            self.is_kw_stat = avg < KW_STAT_THRESHOLD
            if self.samples % 100 == 0:
                _LOGGER.debug(
                    "PowerCalculator stat: %s avg=%.3f → %s",
                    self.entity_id, avg, "kW" if self.is_kw_stat else "W",
                )

    @property
    def is_kw(self) -> bool:
        """Final determination: UOM wins, statistical is fallback."""
        if self.uom_is_kw is not None:
            return self.uom_is_kw
        return self.is_kw_stat

    def to_watts(self, raw: float) -> float:
        """Return value normalised to Watts.

        Safety guard: if raw > ALWAYS_WATT_ABOVE we NEVER multiply by 1000 —
        a sensor sending 1234 with unit kW would give 1 234 000 W which is wrong.
        """
        if abs(raw) > ALWAYS_WATT_ABOVE:
            # Definitely Watts regardless of what UOM says.
            # Warn once, then lock to W so subsequent calls are silent.
            if self.uom_is_kw:
                _LOGGER.warning(
                    "PowerCalculator: %s has UOM=kW but value=%.1f > %.0f — "
                    "treating as Watts (probable sensor mis-label). "
                    "Scale locked to W; this message will not repeat.",
                    self.entity_id, raw, ALWAYS_WATT_ABOVE,
                )
                self.uom_is_kw  = False
                self.uom_locked = True
            return raw
        return raw * 1000.0 if self.is_kw else raw


class PowerCalculator:
    """
    Resolves power (W), voltage (V) and current (A) using P = U × I.

    For each entity we:
      1. Read unit_of_measurement from the HA state object if available.
      2. Fall back to statistical kW/W detection.
      3. Apply safety guard (values > 800 are always Watts).

    The caller should pass the full HA state object via observe_state()
    before calling to_watts() so the UOM can be read.
    """

    def __init__(self, default_voltage: float = DEFAULT_VOLTAGE_V):
        self._default_v = default_voltage
        self._scale: dict[str, ScaleState] = {}

    # ── State/UOM registration ─────────────────────────────────────────────

    def observe_state(self, entity_id: str, ha_state) -> None:
        """Feed the HA state object to extract unit_of_measurement."""
        if not entity_id or ha_state is None:
            return
        st = self._scale.setdefault(entity_id, ScaleState(entity_id=entity_id))
        uom = ha_state.attributes.get("unit_of_measurement")
        st.observe_uom(uom)

    # ── Public API ─────────────────────────────────────────────────────────

    def to_watts(self, entity_id: str, raw: float) -> float:
        """Feed raw sensor value; return normalised Watts."""
        st = self._scale.setdefault(entity_id, ScaleState(entity_id=entity_id))
        st.update_stat(raw)
        return st.to_watts(raw)

    def is_kw(self, entity_id: str) -> bool:
        return self._scale.get(entity_id, ScaleState(entity_id=entity_id)).is_kw

    def get_scale_info(self, entity_id: str) -> dict:
        """Return diagnostics about scale detection for this entity."""
        st = self._scale.get(entity_id)
        if not st:
            return {"entity_id": entity_id, "scale": "unknown"}
        return {
            "entity_id":  entity_id,
            "scale":      "kW" if st.is_kw else "W",
            "source":     "uom" if st.uom_locked else ("stat" if st.samples >= STAT_MIN_SAMPLES else "pending"),
            "uom_is_kw":  st.uom_is_kw,
            "stat_is_kw": st.is_kw_stat,
            "samples":    st.samples,
        }

    # ── Derivation helpers ─────────────────────────────────────────────────

    @staticmethod
    def derive_current(power_w: Optional[float], voltage_v: Optional[float],
                       default_v: float = DEFAULT_VOLTAGE_V) -> Optional[float]:
        """I = P / U  — derive current when only power (and optionally voltage) is known."""
        if power_w is None:
            return None
        v = voltage_v if (voltage_v and voltage_v > 50) else default_v
        if v == 0:
            return None
        return round(power_w / v, 3)

    @staticmethod
    def derive_power(current_a: Optional[float], voltage_v: Optional[float],
                     default_v: float = DEFAULT_VOLTAGE_V) -> Optional[float]:
        """P = U × I  — derive power when current is known but power sensor is absent."""
        if current_a is None:
            return None
        v = voltage_v if (voltage_v and voltage_v > 50) else default_v
        return round(current_a * v, 1)

    @staticmethod
    def derive_voltage(power_w: Optional[float],
                       current_a: Optional[float]) -> Optional[float]:
        """U = P / I  — derive actual voltage when both power and current are measured."""
        if power_w is None or current_a is None or current_a == 0:
            return None
        return round(power_w / current_a, 1)

    def resolve_phase(
        self,
        phase: str,
        *,
        power_entity: Optional[str] = None,
        raw_power:    Optional[float] = None,
        raw_current:  Optional[float] = None,
        raw_voltage:  Optional[float] = None,
        ema_voltage:  Optional[float] = None,   # EMA van limiter — betere fallback dan vaste 230V
    ) -> dict:
        """
        Given whichever phase values are available, derive the rest.

        Derivation priority:
          1. power + voltage (or default V)  → derive current  (I = P/V)
          2. current + voltage (or default V) → derive power   (P = U*I)
          3. power + current                 → derive voltage  (U = P/I)

        Returns dict: power_w, current_a, voltage_v, derived_from
        """
        # Normalise power through kW auto-detection
        power_w: Optional[float] = None
        power_was_measured = False   # True only when power came from a real sensor
        if raw_power is not None and power_entity:
            power_w = self.to_watts(power_entity, raw_power)
            power_was_measured = True
        elif raw_power is not None:
            power_w = raw_power
            power_was_measured = True

        # Fallback-volgorde: gemeten spanning → EMA van lopend gemiddelde → fabrieksinstelling
        _fallback_v = ema_voltage if (ema_voltage and ema_voltage > 50) else self._default_v
        voltage_v = raw_voltage if (raw_voltage and raw_voltage > 50) else _fallback_v
        current_a = raw_current
        derived_from: list[str] = []

        # Case 1: have P, no I → derive I = P/V
        if power_w is not None and current_a is None:
            current_a = self.derive_current(power_w, voltage_v, _fallback_v)
            derived_from.append("I=P/U")

        # Case 2: have I, no P → derive P = U*I
        elif current_a is not None and power_w is None:
            power_w = self.derive_power(current_a, voltage_v, _fallback_v)
            derived_from.append("P=U*I")
            # power_was_measured stays False — derived from fallback voltage

        # Case 3: derive U = P/I only when BOTH came from real sensors.
        # Guard: if power was derived from the 230V default (Case 2), then
        # P/I = (I×230)/I = 230 — circular, adds no information.
        if (power_was_measured and current_a is not None
                and raw_voltage is None and raw_current is not None):
            derived_v = self.derive_voltage(power_w, current_a)
            if derived_v and abs(derived_v - self._default_v) < 50:
                # Only accept if plausible (within 50V of nominal)
                voltage_v = derived_v
                derived_from.append("U=P/I")

        return {
            "power_w":      round(power_w, 1)    if power_w   is not None else None,
            "current_a":    round(current_a, 3)  if current_a is not None else None,
            "voltage_v":    round(voltage_v, 1)  if voltage_v is not None else None,
            "derived_from": ", ".join(derived_from) if derived_from else "direct",
        }
