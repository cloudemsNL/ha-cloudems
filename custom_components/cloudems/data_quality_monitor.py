# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""
DataQualityMonitor — v4.6.583

Detecteert automatisch dashboard-dataproblemen die de gebruiker anders handmatig zou moeten melden:
  1. self_cons_zero_with_pv   — zelfconsumptie 0% terwijl PV actief is
  2. phase_badge_mismatch     — fase richting inconsistent met netto grid richting
  3. boiler_power_while_off   — boiler toont vermogen terwijl is_on=False
  4. capacity_null_with_soc   — capaciteit 0 terwijl SoC valide is

Elke issue is een dict:
  {code, level ('warning'|'error'), category, message, detail}

Cloud-ready: geen HA-afhankelijkheden — werkt alleen op coordinator.data en config.
"""

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Drempels
_PV_MIN_W = 50          # minimaal PV-vermogen om check te activeren
_SC_ZERO_HOLD_S = 600   # 10 minuten aanhoudend 0% vóór melding
_PHASE_BADGE_HOLD_S = 86400  # 24 uur aanhoudend vóór fase-badge melding
_PHASE_GRID_MIN_W = 200 # netto grid moet >200W afwijken voor badge-check
_BOILER_PWR_MIN_W = 50  # minimaal boiler-vermogen om mismatch te melden
_SENSOR_UNKNOWN = {"unknown", "unavailable", "none", "", "-", None}


class DataQualityMonitor:
    """
    Periodieke checks op coordinator.data voor dashboard-dataproblemen.

    Gebruik:
        dqm = DataQualityMonitor()
        issues = dqm.check(coordinator_data, config)
    """

    def __init__(self) -> None:
        # Timestamps voor debounce (code → float unix)
        self._first_seen: dict[str, float] = {}

    def check(self, data: dict, config: dict) -> list[dict]:
        """
        Voer alle checks uit en retourneer lijst van actieve issues.
        Elke issue heeft: code, level, category, message, detail.
        """
        issues: list[dict] = []
        now = time.time()

        try:
            issues += self._check_self_consumption(data, now)
        except Exception as exc:
            _LOGGER.debug("DQM self_consumption check fout: %s", exc)

        try:
            issues += self._check_phase_badge(data, now)
        except Exception as exc:
            _LOGGER.debug("DQM phase_badge check fout: %s", exc)

        try:
            issues += self._check_boiler_power(data, now)
        except Exception as exc:
            _LOGGER.debug("DQM boiler_power check fout: %s", exc)

        try:
            issues += self._check_capacity(data, config, now)
        except Exception as exc:
            _LOGGER.debug("DQM capacity check fout: %s", exc)

        # Reset first_seen voor codes die niet meer actief zijn
        active_codes = {i["code"] for i in issues}
        stale = [c for c in self._first_seen if c not in active_codes]
        for c in stale:
            del self._first_seen[c]

        return issues

    # ── Check 1: Zelfconsumptie 0% terwijl PV actief ─────────────────────────
    def _check_self_consumption(self, data: dict, now: float) -> list[dict]:
        sc_data = data.get("self_consumption") or {}
        ratio = sc_data.get("ratio_pct")
        solar_w = float(data.get("solar_power", 0) or 0)

        if solar_w < _PV_MIN_W:
            return []
        if ratio is None or float(ratio) > 0.5:
            return []

        code = "self_cons_zero_with_pv"
        first = self._first_seen.setdefault(code, now)
        held = now - first

        if held < _SC_ZERO_HOLD_S:
            return []

        return [{
            "code": code,
            "level": "warning",
            "category": "data_quality",
            "message": (
                f"Zelfconsumptie toont 0% terwijl er {solar_w:.0f} W PV-productie is."
            ),
            "detail": (
                "Dit duurt al meer dan 10 minuten. Mogelijk is de self-consumption "
                "tracker niet opgestart na herstart, of ontbreekt een export-sensor. "
                "Herstart CloudEMS via Instellingen → Integraties als dit aanhoudt."
            ),
        }]

    # ── Check 2: Fase-badges inconsistent met netto grid richting ─────────────
    def _check_phase_badge(self, data: dict, now: float) -> list[dict]:
        phases = data.get("phases") or {}
        if not phases:
            return []

        grid_w = float(data.get("grid_power_w") or data.get("grid_power") or 0)
        if abs(grid_w) < _PHASE_GRID_MIN_W:
            return []

        # Netto grid-richting: positief = import, negatief = export
        net_import = grid_w > 0

        # Check: zijn alle fasen eenzijdig maar wijst grid de andere kant op?
        p1_nets = []
        for ph, pdata in phases.items():
            p1_net = pdata.get("p1_net_w")
            if p1_net is not None:
                p1_nets.append(float(p1_net))

        if len(p1_nets) < 2:
            return []

        all_import = all(v > 50 for v in p1_nets)
        all_export = all(v < -50 for v in p1_nets)

        mismatch = (all_import and not net_import) or (all_export and net_import)
        if not mismatch:
            return []

        code = "phase_badge_mismatch"
        self._first_seen.setdefault(code, now)
        # Alleen tonen na 24 uur aanhoudende mismatch — kortdurende afwijkingen zijn normaal
        if now - self._first_seen[code] < _PHASE_BADGE_HOLD_S:
            return []

        fase_richting = "IMPORT" if all_import else "EXPORT"
        grid_richting = "IMPORT" if net_import else "EXPORT"
        return [{
            "code": code,
            "level": "warning",
            "category": "data_quality",
            "message": (
                f"Fase-badges tonen allemaal {fase_richting} "
                f"maar netto grid is {grid_richting} ({grid_w:.0f} W)."
            ),
            "detail": (
                "Mogelijke oorzaak: P1-fase-sensoren zijn niet gesynchroniseerd "
                "met de netto grid-sensor, of de import/export sensor zijn omgekeerd "
                "geconfigureerd. Controleer sensor.cloudems_energy_balancer attributen."
            ),
        }]

    # ── Check 3: Boiler toont vermogen terwijl is_on=False ───────────────────
    def _check_boiler_power(self, data: dict, now: float) -> list[dict]:
        boiler_status = data.get("boiler_status") or []
        if not boiler_status:
            return []

        issues = []
        for i, b in enumerate(boiler_status):
            power_w = float(b.get("power_w") or b.get("current_power_w") or 0)
            is_on = b.get("is_on", True)  # default True = geen valse melding
            name = b.get("name") or b.get("entity_id") or f"Boiler {i+1}"

            if power_w > _BOILER_PWR_MIN_W and is_on is False:
                code = f"boiler_power_while_off_{i}"
                self._first_seen.setdefault(code, now)
                issues.append({
                    "code": code,
                    "level": "warning",
                    "category": "data_quality",
                    "message": (
                        f"Boiler '{name}' toont {power_w:.0f} W vermogen "
                        f"maar is_on=False."
                    ),
                    "detail": (
                        "Vermogen-sensor en schakelstatus zijn niet synchroon. "
                        "Dit kan een verouderde NILM-schatting zijn of een "
                        "sensor die trager bijwerkt dan de schakelstatus. "
                        "Controleer de vermogen-sensor van deze boiler."
                    ),
                })

        return issues

    # ── Check 4: Capaciteit 0 terwijl SoC valide is ──────────────────────────
    def _check_capacity(self, data: dict, config: dict, now: float) -> list[dict]:
        soc_pct = data.get("battery_soc_pct")
        if soc_pct is None or str(soc_pct) in _SENSOR_UNKNOWN:
            return []

        soc_val = float(soc_pct)
        if soc_val <= 0:
            return []

        cap = float(config.get("battery_capacity_kwh") or 0)
        if cap > 0.5:
            return []

        # Controleer ook of estimated_capacity_kwh al beschikbaar is uit leren
        batt_data = data.get("battery") or {}
        est_cap = float(batt_data.get("estimated_capacity_kwh") or 0)
        if est_cap > 0.5:
            return []

        code = "capacity_null_with_soc"
        self._first_seen.setdefault(code, now)

        return [{
            "code": code,
            "level": "warning",
            "category": "data_quality",
            "message": (
                f"Batterijcapaciteit staat op 0 kWh terwijl SoC "
                f"{soc_val:.1f}% is."
            ),
            "detail": (
                "Vul de capaciteit in via CloudEMS Instellingen → Batterij → "
                "Batterijcapaciteit (kWh). Zonder capaciteit kunnen EPEX-beslissingen "
                "en kosten-berekeningen niet correct werken. "
                "CloudEMS probeert de capaciteit ook zelf te leren na ~3 volledige cycli."
            ),
        }]
