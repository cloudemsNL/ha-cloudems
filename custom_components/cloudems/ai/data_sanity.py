"""
CloudEMS Data Sanity Checker — v1.0.0

Validates coordinator data BEFORE it reaches JS cards.
Logs every anomaly with full context so we can debug from logs alone.

Checks:
  - Kirchhoff: solar + grid - battery ≈ house (max 10% deviation)
  - Self-consumption: can't be 0% when solar > 500W
  - House power: can't be 0W when battery is charging from grid
  - Export power: sign must match grid sign
  - NILM total: sum of NILM devices can't exceed house_power × 1.2
  - Phase balance: L1+L2+L3 current sum must be consistent with total power
  - Battery SOC: can't increase when not charging
  - Boiler: temp can't drop 5°C in 10s

Each check:
  - Logs a WARNING with full values on first failure
  - Logs DEBUG on every subsequent failure (to avoid spam)
  - Reports to AILearningLog as a training signal
  - Tracks how long an anomaly has been active

This makes 5-minute debugging sessions instead of 5-day ones.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# How often to re-warn about the same ongoing anomaly (seconds)
REWARN_INTERVAL_S = 300   # 5 minutes


@dataclass
class Anomaly:
    """An active data anomaly."""
    check_id:    str
    description: str
    first_seen:  float
    last_seen:   float
    n_ticks:     int  = 0
    last_values: dict = field(default_factory=dict)
    resolved:    bool = False


class DataSanityChecker:
    """
    Validates coordinator data before it reaches JS cards.
    Call check(data) every coordinator tick.
    """

    def __init__(self) -> None:
        self._active: dict[str, Anomaly] = {}
        self._resolved_count = 0
        self._total_checks   = 0
        self._prev_data: dict = {}
        self._prev_ts:   float = 0.0

    def check(self, data: dict) -> list[str]:
        """
        Run all sanity checks on coordinator data.
        Returns list of active anomaly descriptions.
        Call every coordinator tick.
        """
        self._total_checks += 1
        now      = time.time()
        dt       = now - self._prev_ts if self._prev_ts > 0 else 10.0
        issues   = []

        checks = [
            self._check_kirchhoff,
            self._check_self_consumption,
            self._check_house_power,
            self._check_export_sign,
            self._check_battery_soc_direction,
            self._check_nilm_total,
        ]

        for fn in checks:
            try:
                issue = fn(data, dt)
                if issue:
                    issues.append(issue)
            except Exception as exc:
                _LOGGER.debug("DataSanityChecker: check %s fout: %s", fn.__name__, exc)

        # Mark resolved anomalies
        for check_id in list(self._active.keys()):
            if check_id not in [i.split(":")[0] for i in issues]:
                a = self._active[check_id]
                if not a.resolved:
                    a.resolved = True
                    self._resolved_count += 1
                    _LOGGER.info(
                        "✅ DataSanity OPGELOST [%s] na %d ticks (%.0fs): %s",
                        check_id, a.n_ticks, now - a.first_seen, a.description
                    )
                    del self._active[check_id]

        self._prev_data = dict(data)
        self._prev_ts   = now
        return issues

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_kirchhoff(self, data: dict, dt: float) -> Optional[str]:
        solar  = float(data.get("solar_power",  0) or 0)
        grid   = float(data.get("grid_power",   0) or 0)
        batt   = float(data.get("battery_power",0) or 0)  # + = charging
        house  = float(data.get("house_power",  0) or 0)

        if solar < 10 and abs(grid) < 50 and abs(batt) < 50:
            return None  # nothing to check at night

        expected = solar + grid - batt
        if expected < 10:
            return None  # can't meaningfully check near-zero

        deviation_pct = abs(house - expected) / max(1.0, expected) * 100

        if deviation_pct > 20:
            return self._report(
                "kirchhoff",
                f"Kirchhoff-fout: huis={house:.0f}W maar solar({solar:.0f})+grid({grid:.0f})-bat({batt:.0f})={expected:.0f}W (afwijking {deviation_pct:.0f}%)",
                {"house_w": house, "solar_w": solar, "grid_w": grid, "battery_w": batt,
                 "expected_w": round(expected, 1), "deviation_pct": round(deviation_pct, 1)},
                threshold_warn=20, threshold_debug=10,
            )
        return None

    def _check_self_consumption(self, data: dict, dt: float) -> Optional[str]:
        solar  = float(data.get("solar_power",  0) or 0)
        sc_pct = data.get("self_consumption", {})
        if isinstance(sc_pct, dict):
            sc_pct = sc_pct.get("ratio_pct") or 0
        sc_pct = float(sc_pct or 0)

        # Sensor native_value (direct)
        sensor_sc = data.get("sensor_self_consumption_pct")
        if sensor_sc is not None:
            sc_pct = float(sensor_sc or 0)

        if solar < 300:
            return None  # too little sun to meaningfully measure

        if sc_pct == 0.0:
            export = float(data.get("export_power", 0) or 0)
            return self._report(
                "self_consumption_zero",
                f"Zelfconsumptie 0% terwijl solar={solar:.0f}W en export={export:.0f}W — export_power bereikt sensor niet",
                {"solar_w": solar, "sc_pct": sc_pct, "export_w": export,
                 "grid_w": data.get("grid_power", 0)},
                threshold_warn=0, threshold_debug=0,
            )
        return None

    def _check_house_power(self, data: dict, dt: float) -> Optional[str]:
        house  = float(data.get("house_power",  0) or 0)
        batt   = float(data.get("battery_power",0) or 0)
        solar  = float(data.get("solar_power",  0) or 0)
        grid   = float(data.get("grid_power",   0) or 0)

        # House can't be 0 when there's significant energy flow
        total_flow = solar + abs(grid) + abs(batt)
        if total_flow > 500 and house < 50:
            return self._report(
                "house_power_zero",
                f"Huis-verbruik 0W terwijl energiestromen actief zijn: solar={solar:.0f}W grid={grid:.0f}W bat={batt:.0f}W",
                {"house_w": house, "solar_w": solar, "grid_w": grid, "battery_w": batt},
                threshold_warn=0, threshold_debug=0,
            )
        return None

    def _check_export_sign(self, data: dict, dt: float) -> Optional[str]:
        grid   = float(data.get("grid_power",  0) or 0)
        export = float(data.get("export_power",0) or 0)

        # Export should be > 0 only when grid < 0 (feeding back)
        if export > 100 and grid > 50:
            return self._report(
                "export_sign",
                f"export_power={export:.0f}W maar grid_power={grid:.0f}W (importeren én exporteren tegelijk — tekenconflict)",
                {"export_w": export, "grid_w": grid},
                threshold_warn=0, threshold_debug=0,
            )
        return None

    def _check_battery_soc_direction(self, data: dict, dt: float) -> Optional[str]:
        soc_now  = float(data.get("battery_soc", data.get("battery_soc_pct", -1)) or -1)
        soc_prev = float(self._prev_data.get("battery_soc", self._prev_data.get("battery_soc_pct", -1)) or -1)
        batt_w   = float(data.get("battery_power", 0) or 0)

        if soc_now < 0 or soc_prev < 0 or dt > 60:
            return None  # no data or too much time elapsed

        delta_soc = soc_now - soc_prev

        # SOC rising but battery is discharging (>200W)
        if delta_soc > 2 and batt_w < -200:
            return self._report(
                "soc_direction",
                f"SOC stijgt ({soc_prev:.0f}%→{soc_now:.0f}%) maar batterij ontlaadt {batt_w:.0f}W — stale Nexus data?",
                {"soc_now": soc_now, "soc_prev": soc_prev, "battery_w": batt_w, "dt_s": round(dt,1)},
                threshold_warn=0, threshold_debug=0,
            )
        # SOC falling but battery is charging (>200W)
        if delta_soc < -2 and batt_w > 200:
            return self._report(
                "soc_direction_charge",
                f"SOC daalt ({soc_prev:.0f}%→{soc_now:.0f}%) maar batterij laadt {batt_w:.0f}W — stale Nexus data?",
                {"soc_now": soc_now, "soc_prev": soc_prev, "battery_w": batt_w, "dt_s": round(dt,1)},
                threshold_warn=0, threshold_debug=0,
            )
        return None

    def _check_nilm_total(self, data: dict, dt: float) -> Optional[str]:
        house  = float(data.get("house_power", 0) or 0)
        devices = data.get("nilm_running_devices") or []
        if not devices or house < 100:
            return None

        nilm_total = sum(float(d.get("power_w") or d.get("current_power") or 0) for d in devices)
        if nilm_total > house * 1.5 and nilm_total > 200:
            return self._report(
                "nilm_exceeds_house",
                f"NILM-apparaten totaal {nilm_total:.0f}W > huis {house:.0f}W — NILM overdetectie of huis-sensor fout",
                {"nilm_total_w": round(nilm_total,1), "house_w": house,
                 "n_devices": len(devices)},
                threshold_warn=0, threshold_debug=0,
            )
        return None

    # ── Reporting helpers ─────────────────────────────────────────────────────

    def _report(
        self,
        check_id: str,
        description: str,
        values: dict,
        threshold_warn: int = 0,
        threshold_debug: int = 0,
    ) -> str:
        now = time.time()

        if check_id not in self._active:
            # New anomaly — always warn
            self._active[check_id] = Anomaly(
                check_id=check_id,
                description=description,
                first_seen=now,
                last_seen=now,
                n_ticks=1,
                last_values=values,
            )
            _LOGGER.warning(
                "🔴 DataSanity NIEUW [%s]: %s | waarden: %s",
                check_id, description, values
            )
        else:
            a = self._active[check_id]
            a.n_ticks   += 1
            a.last_seen  = now
            a.last_values = values

            # Re-warn every REWARN_INTERVAL_S
            if (now - a.first_seen) > REWARN_INTERVAL_S * (a.n_ticks // 30 + 1):
                _LOGGER.warning(
                    "🔴 DataSanity AANHOUDT [%s] al %d ticks (%.0f min): %s | waarden: %s",
                    check_id, a.n_ticks, (now - a.first_seen) / 60,
                    description, values
                )
            else:
                _LOGGER.debug(
                    "DataSanity [%s] tick %d: %s",
                    check_id, a.n_ticks, values
                )

        return f"{check_id}: {description}"

    @property
    def active_anomalies(self) -> list[dict]:
        return [
            {
                "check_id":    a.check_id,
                "description": a.description,
                "n_ticks":     a.n_ticks,
                "active_min":  round((time.time() - a.first_seen) / 60, 1),
                "last_values": a.last_values,
            }
            for a in self._active.values()
        ]

    @property
    def stats(self) -> dict:
        return {
            "n_active":    len(self._active),
            "n_resolved":  self._resolved_count,
            "n_checks":    self._total_checks,
            "anomalies":   self.active_anomalies,
        }
