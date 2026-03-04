"""CloudEMS SensorSanityGuard — v1.15.0.

Detects misconfigured sensors and impossible readings before they corrupt
NILM, scheduling, and cost calculations.

Checks performed
----------------
1. Hard magnitude limits  — > 55 kW grid / > 50 kW PV / > 30 kW battery
2. kW/W unit confusion    — value is a small integer (e.g. 5.2) that should be kW
3. Spike vs own history   — > 8× learned mean over last 200 samples
4. Sign / teken fout      — export while sun=0 and battery=0
5. Aansluiting exceeded   — grid power > configured max_current × voltage × phases
6. Per-phase limit        — phase current > 80 A × 230 V = 18.4 kW
"""
from __future__ import annotations
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Limits
GRID_MAX_KW   = 55.0
PV_MAX_KW     = 50.0
BATT_MAX_KW   = 30.0
PHASE_MAX_KW  = 18.4   # 80 A × 230 V
SPIKE_RATIO   = 8.0    # blocked if raw > SPIKE_RATIO × learned mean
CONFIRM_N     = 3      # need 3 consecutive hits to raise alert (avoids transients)
HISTORY_LEN   = 200


@dataclass
class SanityIssue:
    sensor_type: str        # "grid", "solar", "battery", "phase_L1" …
    entity_id:   str
    code:        str        # machine-readable code
    level:       str        # "warning" | "critical"
    description: str        # Dutch short description
    advice:      str        # Dutch action advice with concrete template
    value:       float
    expected:    str        # human readable expected range


@dataclass
class SanityResult:
    issues: List[SanityIssue] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(i.level == "critical" for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    @property
    def summary(self) -> str:
        if not self.issues:
            return "Alle sensoren OK"
        crits = [i for i in self.issues if i.level == "critical"]
        warns = [i for i in self.issues if i.level == "warning"]
        parts = []
        if crits:
            parts.append(f"{len(crits)} kritiek")
        if warns:
            parts.append(f"{len(warns)} waarschuwing{'en' if len(warns) > 1 else ''}")
        return "Sensorfout gedetecteerd: " + ", ".join(parts)


class SensorSanityGuard:
    """
    Runs on every coordinator tick. Accumulates hit-counts before raising
    alerts to avoid false positives from transient readings.
    """

    def __init__(self, config: dict):
        self._config  = config
        self._history: Dict[str, deque] = {}
        self._hits:    Dict[str, int]   = {}   # consecutive hit counter
        self._issues:  Dict[str, SanityIssue] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def update(
        self,
        grid_w:    Optional[float] = None,
        solar_w:   Optional[float] = None,
        battery_w: Optional[float] = None,
        phase_currents: Optional[Dict[str, float]] = None,
        max_current_a: float = 25.0,
        phases: int = 1,
        mains_v: float = 230.0,
    ) -> SanityResult:
        """Run all checks and return current SanityResult."""
        cfg = self._config
        grid_eid  = cfg.get("grid_sensor", "?")
        solar_eid = cfg.get("solar_sensor", "?")
        batt_eid  = cfg.get("battery_sensor", "?")

        checks = []

        # 1. Hard magnitude limits
        if grid_w is not None:
            if abs(grid_w) > GRID_MAX_KW * 1000:
                checks.append(("grid_max", "critical", grid_eid, "grid",
                    f"Netvermogen {grid_w/1000:.1f} kW is groter dan de fysieke limiet van {GRID_MAX_KW} kW.",
                    f"Controleer of sensor {grid_eid!r} in W rapporteert. "
                    f"Als de sensor in kW rapporteert, gebruik dan: template: '{{{{ states(\"{grid_eid}\") | float * 1000 }}}}'",
                    grid_w, f"−{GRID_MAX_KW}…+{GRID_MAX_KW} kW"))

        if solar_w is not None and solar_w > PV_MAX_KW * 1000:
            checks.append(("solar_max", "critical", solar_eid, "solar",
                f"Zonnestroom {solar_w/1000:.1f} kW overschrijdt de max van {PV_MAX_KW} kW.",
                f"Controleer sensor {solar_eid!r} op eenheid (W vs kW).",
                solar_w, f"0…+{PV_MAX_KW} kW"))

        if battery_w is not None and abs(battery_w) > BATT_MAX_KW * 1000:
            checks.append(("battery_max", "critical", batt_eid, "battery",
                f"Batterijvermogen {battery_w/1000:.1f} kW is onrealistisch hoog.",
                f"Controleer sensor {batt_eid!r}. Batterijen zijn doorgaans < {BATT_MAX_KW} kW.",
                battery_w, f"−{BATT_MAX_KW}…+{BATT_MAX_KW} kW"))

        # 2. kW/W confusion — small integer values while appliances are running
        for name, eid, val, expected_kw_min in [
            ("grid",    grid_eid,  grid_w,    0.3),
            ("solar",   solar_eid, solar_w,   0.3),
            ("battery", batt_eid,  battery_w, 0.1),
        ]:
            if val is None:
                continue
            abs_v = abs(val)
            # Plausible kW range if it's a small number AND historically low
            if 0.1 < abs_v < 50 and abs_v == round(abs_v, 1):
                hist = self._get_history(eid)
                if len(hist) >= 20 and max(abs(h) for h in hist) < 50:
                    checks.append((f"{name}_kw_unit", "warning", eid, name,
                        f"Sensor {eid!r} geeft waarden rond {abs_v} — lijkt op kW in plaats van W.",
                        f"Voeg een template-sensor toe die de waarde met 1000 vermenigvuldigt:\n"
                        f"  template: '{{{{ states(\"{eid}\") | float * 1000 }}}}'",
                        val, "W (bijv. 1500, niet 1.5)"))

        # 3. Spike vs own history
        for name, eid, val in [("grid", grid_eid, grid_w), ("solar", solar_eid, solar_w)]:
            if val is None:
                continue
            hist = self._get_history(eid)
            self._push_history(eid, val)
            if len(hist) >= 30:
                mean = sum(abs(h) for h in hist) / len(hist)
                if mean > 10 and abs(val) > mean * SPIKE_RATIO:
                    checks.append((f"{name}_spike", "warning", eid, name,
                        f"Uitschieter gedetecteerd op {eid!r}: {val:.0f} W terwijl gemiddelde {mean:.0f} W is.",
                        f"Kan een cloud-sensor zijn die meerdere minuten niet geüpdateerd heeft. "
                        f"Overweeg CloudEMS te herstarten als dit aanhoudt.",
                        val, f"< {mean * SPIKE_RATIO:.0f} W"))

        # 4. Energy conservation: large export but no sun and no battery
        if (grid_w is not None and grid_w < -1000
                and (solar_w is None or solar_w < 100)
                and (battery_w is None or abs(battery_w) < 100)):
            checks.append(("sign_error", "warning", grid_eid, "grid",
                f"Netsensor toont {abs(grid_w):.0f} W teruglevering zonder zon of batterij.",
                f"Mogelijk staat het teken van sensor {grid_eid!r} omgekeerd. "
                f"Controleer of import positief en export negatief is.",
                grid_w, "positief = afname, negatief = teruglevering"))

        # 5. Grid exceeds configured connection capacity
        if grid_w is not None:
            max_w = max_current_a * mains_v * phases
            if abs(grid_w) > max_w * 1.2:
                checks.append(("grid_overcapacity", "warning", grid_eid, "grid",
                    f"Netvermogen {grid_w:.0f} W overschrijdt de geconfigureerde aansluiting "
                    f"({max_current_a:.0f}A × {mains_v:.0f}V × {phases}f = {max_w:.0f}W).",
                    f"Pas de max-stroomsterkte aan in CloudEMS instellingen of corrigeer sensor {grid_eid!r}.",
                    grid_w, f"< {max_w:.0f} W"))

        # 6. Per-phase limits
        if phase_currents:
            phase_max_w = 80 * mains_v  # 80A hard limit per phase
            for ph, cur_a in phase_currents.items():
                if cur_a and abs(cur_a) * mains_v > phase_max_w:
                    eid = cfg.get(f"phase_sensors_{ph}", f"fase {ph}")
                    checks.append((f"phase_{ph}_max", "critical", eid, f"phase_{ph}",
                        f"Fase {ph}: {cur_a:.1f}A × {mains_v:.0f}V = {cur_a*mains_v:.0f}W — boven 80A fysieke limiet.",
                        f"Sensor {eid!r} geeft onmogelijke stroom. Controleer de eenheid (A vs mA).",
                        cur_a * mains_v, "< 18400 W"))

        # Apply confirmation (CONFIRM_N consecutive hits before raising)
        for (code, level, eid, stype, desc, advice, val, expected) in checks:
            self._hits[code] = self._hits.get(code, 0) + 1
            if self._hits[code] >= CONFIRM_N:
                self._issues[code] = SanityIssue(
                    sensor_type=stype, entity_id=eid, code=code,
                    level=level, description=desc, advice=advice,
                    value=val, expected=expected,
                )
        # Clear codes that no longer trigger
        active_codes = {c for (c, *_) in checks}
        for code in list(self._issues.keys()):
            if code not in active_codes:
                self._hits[code] = 0
                del self._issues[code]

        return SanityResult(issues=list(self._issues.values()))

    def get_result(self) -> SanityResult:
        return SanityResult(issues=list(self._issues.values()))

    # ── Internal ─────────────────────────────────────────────────────────

    def _get_history(self, eid: str) -> deque:
        if eid not in self._history:
            self._history[eid] = deque(maxlen=HISTORY_LEN)
        return self._history[eid]

    def _push_history(self, eid: str, val: float) -> None:
        self._get_history(eid).append(val)
