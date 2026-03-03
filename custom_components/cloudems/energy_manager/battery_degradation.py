"""
CloudEMS Battery Degradation Tracker — v1.10.0

Tracks battery health (State of Health — SoH) by monitoring:
  1. Full charge cycles (0→100% equivalent)
  2. Partial cycles accumulated as equivalent full cycles
  3. SoC range stress (deep discharges / high overcharge)
  4. Temperature stress (if sensor available — optional)

SoH estimation model (simplified calendar + cycle ageing):
  - Each full equivalent cycle degrades the battery by ~0.003–0.005% capacity
    (varies by chemistry: LFP slower, NMC faster)
  - Deep discharges below 10% add extra stress
  - Charging above 95% continuously adds calendar stress
  - SoH alert thresholds: <90% warn, <80% critical

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_battery_degr_v1"
STORAGE_VERSION = 1

# Chemistry-specific cycle degradation factors (% SoH lost per full cycle)
CHEMISTRY_FACTORS = {
    "LFP":  0.0025,   # Lithium Iron Phosphate — very cycle-stable
    "NMC":  0.0045,   # Nickel Manganese Cobalt — standard home batteries
    "NCA":  0.0050,   # Nickel Cobalt Aluminium — Tesla-style
    "LTO":  0.0010,   # Lithium Titanate — extremely durable
}
DEFAULT_CHEMISTRY = "NMC"

SOH_WARN_PCT     = 90.0
SOH_CRITICAL_PCT = 80.0


@dataclass
class DegradationState:
    total_full_cycles:     float = 0.0   # equivalent full cycles since tracking started
    soh_pct:               float = 100.0
    last_soc:              Optional[float] = None
    soc_low_events:        int   = 0     # times SoC < 10%
    soc_high_events:       int   = 0     # times SoC > 95% for extended period
    tracking_start_ts:     float = field(default_factory=time.time)
    last_update_ts:        float = field(default_factory=time.time)
    chemistry:             str   = DEFAULT_CHEMISTRY
    capacity_kwh_nominal:  float = 10.0
    capacity_kwh_current:  float = 10.0  # estimated remaining usable capacity


@dataclass
class DegradationResult:
    soh_pct:            float    # 0-100 estimated state of health
    capacity_kwh:       float    # estimated usable kWh remaining
    total_cycles:       float    # equivalent full cycles
    cycles_per_day:     float
    alert_level:        str      # "ok" | "warn" | "critical"
    alert_message:      str
    soc_low_events:     int
    soc_high_events:    int
    days_tracked:       int


class BatteryDegradationTracker:
    """
    Tracks battery health over time.

    Usage in coordinator:
        bdt = BatteryDegradationTracker(hass, config)
        await bdt.async_setup()
        result = bdt.update(current_soc_pct)
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass      = hass
        self._chemistry = config.get("battery_chemistry", DEFAULT_CHEMISTRY).upper()
        if self._chemistry not in CHEMISTRY_FACTORS:
            self._chemistry = DEFAULT_CHEMISTRY
        self._nominal_kwh = float(config.get("battery_capacity_kwh", 10.0))
        self._soc_eid     = config.get("battery_soc_entity", "")
        self._store       = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._state       = DegradationState(
            chemistry            = self._chemistry,
            capacity_kwh_nominal = self._nominal_kwh,
            capacity_kwh_current = self._nominal_kwh,
        )
        self._dirty = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if data:
            s = self._state
            s.total_full_cycles    = float(data.get("total_full_cycles", 0.0))
            s.soh_pct              = float(data.get("soh_pct", 100.0))
            s.last_soc             = data.get("last_soc")
            s.soc_low_events       = int(data.get("soc_low_events", 0))
            s.soc_high_events      = int(data.get("soc_high_events", 0))
            s.tracking_start_ts    = float(data.get("tracking_start_ts", time.time()))
            s.chemistry            = data.get("chemistry", self._chemistry)
            s.capacity_kwh_nominal = float(data.get("capacity_kwh_nominal", self._nominal_kwh))
            s.capacity_kwh_current = float(data.get("capacity_kwh_current", self._nominal_kwh))
        _LOGGER.debug(
            "BatteryDegradationTracker ready — SoH=%.1f%% cycles=%.1f chemistry=%s",
            self._state.soh_pct, self._state.total_full_cycles, self._state.chemistry,
        )

    async def async_save(self) -> None:
        if not self._dirty:
            return
        s = self._state
        await self._store.async_save({
            "total_full_cycles":    round(s.total_full_cycles, 3),
            "soh_pct":              round(s.soh_pct, 3),
            "last_soc":             s.last_soc,
            "soc_low_events":       s.soc_low_events,
            "soc_high_events":      s.soc_high_events,
            "tracking_start_ts":    s.tracking_start_ts,
            "chemistry":            s.chemistry,
            "capacity_kwh_nominal": s.capacity_kwh_nominal,
            "capacity_kwh_current": s.capacity_kwh_current,
        })
        self._dirty = False

    # ── Update (called every coordinator cycle) ───────────────────────────────

    def update(self, soc_pct: Optional[float]) -> DegradationResult:
        """Update tracker with current SoC reading. Returns current degradation status."""
        s = self._state
        now = time.time()

        if soc_pct is not None and s.last_soc is not None:
            delta = soc_pct - s.last_soc

            # Accumulate equivalent cycles: sum of all positive deltas / 100
            if delta > 0:
                frac_cycle = delta / 100.0
                s.total_full_cycles += frac_cycle

                # Apply degradation
                factor   = CHEMISTRY_FACTORS.get(s.chemistry, CHEMISTRY_FACTORS[DEFAULT_CHEMISTRY])
                degraded = frac_cycle * factor
                s.soh_pct = max(0.0, s.soh_pct - degraded)
                s.capacity_kwh_current = round(s.capacity_kwh_nominal * (s.soh_pct / 100.0), 2)
                self._dirty = True

            # Stress events
            if soc_pct < 10.0 and (s.last_soc is None or s.last_soc >= 10.0):
                s.soc_low_events += 1
                # Extra stress for deep discharge
                s.soh_pct = max(0.0, s.soh_pct - 0.01)
                _LOGGER.debug("Battery deep discharge event (SoC %.1f%%)", soc_pct)
                self._dirty = True

            if soc_pct > 95.0 and (s.last_soc is None or s.last_soc <= 95.0):
                s.soc_high_events += 1
                self._dirty = True

        if soc_pct is not None:
            s.last_soc    = soc_pct
            s.last_update_ts = now

        # Build result
        days_tracked   = max(1, int((now - s.tracking_start_ts) / 86400))
        cycles_per_day = round(s.total_full_cycles / days_tracked, 3)

        if s.soh_pct < SOH_CRITICAL_PCT:
            alert_level   = "critical"
            alert_message = (
                f"Battery SoH {s.soh_pct:.1f}% — capacity severely reduced. "
                "Consider replacing or reconditioning."
            )
        elif s.soh_pct < SOH_WARN_PCT:
            alert_level   = "warn"
            alert_message = (
                f"Battery SoH {s.soh_pct:.1f}% — capacity degrading. "
                f"~{s.capacity_kwh_current:.1f} kWh usable of {s.capacity_kwh_nominal:.1f} kWh nominal."
            )
        else:
            alert_level   = "ok"
            alert_message = (
                f"Battery in good health ({s.soh_pct:.1f}%). "
                f"{s.total_full_cycles:.0f} equivalent full cycles."
            )

        return DegradationResult(
            soh_pct          = round(s.soh_pct, 2),
            capacity_kwh     = s.capacity_kwh_current,
            total_cycles     = round(s.total_full_cycles, 1),
            cycles_per_day   = cycles_per_day,
            alert_level      = alert_level,
            alert_message    = alert_message,
            soc_low_events   = s.soc_low_events,
            soc_high_events  = s.soc_high_events,
            days_tracked     = days_tracked,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def soh_pct(self) -> float:
        return round(self._state.soh_pct, 2)

    @property
    def total_cycles(self) -> float:
        return round(self._state.total_full_cycles, 1)
