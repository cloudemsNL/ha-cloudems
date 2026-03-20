# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Setup Health Check (v1.0).

Controleert na setup of alle geconfigureerde sensoren en entiteiten
ook daadwerkelijk bestaan en bruikbare data leveren in HA.

Resultaten worden gerapporteerd als:
  • 'ok'      — sensor bestaat en heeft geldige waarde
  • 'missing' — sensor-ID bestaat niet in HA entity registry
  • 'stale'   — sensor bestaat maar state is 'unavailable' of 'unknown'
  • 'zero'    — sensor levert altijd 0 (mogelijk verkeerd geconfigureerd)

Gebruik in coordinator:
    checker = SetupHealthCheck(hass, config)
    report  = await checker.async_run()
    # report.issues bevat lijst van problemen met uitlegbare foutmelding
    # report.ok is True als alles klopt

Output:
  sensor.cloudems_health_check  →  'ok' | 'warnings' | 'errors'
  Attributen:
    issues:  lijst van problemen [{sensor_id, level, message, suggestion}]
    checked: aantal gecheckte entiteiten
    ok_count, warn_count, error_count
"""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Optional

from homeassistant.core import HomeAssistant

# Grace period na HA-herstart: entiteiten die nog niet beschikbaar zijn
# worden gedurende deze tijd als waarschuwing (niet als fout) gerapporteerd.
_STARTUP_GRACE_SECONDS = 90

_LOGGER = logging.getLogger(__name__)

# Sensoren die kritiek zijn — ontbreken leidt tot 'error'
CRITICAL_SENSORS = [
    "grid_power_sensor",
    "pv_power_sensor",
]

# Sensoren die handig zijn maar optioneel — ontbreken leidt tot 'warning'
# Let op: alleen velden die een HA entity_id bevatten, geen poorten of getallen.
# p1_port is een TCP-poortnummer (int) en hoort hier dus NIET in thuis.
OPTIONAL_SENSORS = [
    "outside_temp_entity",
    "battery_power_sensor",
    "battery_soc_sensor",
    "ev_charger_entity",
]

# Boiler-specifieke velden om te controleren
BOILER_FIELDS = ["entity_id", "temp_sensor", "energy_sensor", "flow_sensor"]


@dataclass
class HealthIssue:
    sensor_id:  str
    level:      str    # 'error' | 'warning' | 'info'
    message:    str
    suggestion: str = ""


@dataclass
class HealthReport:
    issues:      list[HealthIssue] = field(default_factory=list)
    checked:     int = 0
    ok_count:    int = 0
    warn_count:  int = 0
    error_count: int = 0

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    @property
    def status(self) -> str:
        if self.error_count > 0:
            return "errors"
        if self.warn_count > 0:
            return "warnings"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "status":      self.status,
            "ok":          self.ok,
            "checked":     self.checked,
            "ok_count":    self.ok_count,
            "warn_count":  self.warn_count,
            "error_count": self.error_count,
            "issues": [
                {"sensor_id": i.sensor_id, "level": i.level,
                 "message": i.message, "suggestion": i.suggestion}
                for i in self.issues
            ],
        }


class SetupHealthCheck:
    """
    Controleert alle geconfigureerde sensoren en entiteiten in HA.

    Voert drie soorten checks uit:
    1. Bestaat de entiteit in het HA entity registry?
    2. Levert de entiteit een bruikbare waarde (niet unavailable/unknown)?
    3. Is de waarde niet verdacht (bijv. altijd 0 voor een vermogenssensor)?
    """

    def __init__(self, hass: HomeAssistant, config: dict, startup_time: float | None = None) -> None:
        self._hass         = hass
        self._config       = config
        self._startup_time = startup_time if startup_time is not None else _time.monotonic()

    async def async_run(self) -> HealthReport:
        """Voer alle checks uit en geef een HealthReport terug."""
        report = HealthReport()

        # ── Kritieke sensoren ─────────────────────────────────────────────────
        for key in CRITICAL_SENSORS:
            eid = self._config.get(key, "")
            if eid:
                self._check_entity(eid, key, report, level="error",
                                   zero_ok=False, expect_positive=True)

        # ── Optionele sensoren ────────────────────────────────────────────────
        for key in OPTIONAL_SENSORS:
            eid = self._config.get(key, "")
            if eid:
                self._check_entity(eid, key, report, level="warning")

        # ── Boiler-entiteiten ─────────────────────────────────────────────────
        for group_cfg in self._config.get("boiler_groups", []):
            for unit in group_cfg.get("units", []):
                self._check_boiler_unit(unit, report)
        for boiler_cfg in self._config.get("boiler_configs", []):
            self._check_boiler_unit(boiler_cfg, report)

        # ── EV-lader ─────────────────────────────────────────────────────────
        for ev_cfg in self._config.get("ev_chargers", []):
            eid = ev_cfg.get("charger_entity", "")
            if eid:
                self._check_entity(eid, f"ev_charger:{eid}", report, level="warning")

        # ── Fase-sensoren ─────────────────────────────────────────────────────
        for phase in ("l1", "l2", "l3"):
            eid = self._config.get(f"phase_{phase}_current_sensor", "")
            if eid:
                self._check_entity(eid, f"phase_{phase}", report, level="warning")

        # ── Samenvatting in logs ──────────────────────────────────────────────
        if report.error_count:
            _LOGGER.error(
                "CloudEMS health check: %d fout(en), %d waarschuwing(en) — "
                "controleer de configuratie",
                report.error_count, report.warn_count,
            )
            for issue in report.issues:
                if issue.level == "error":
                    _LOGGER.error(
                        "  ❌ %s — %s%s",
                        issue.sensor_id, issue.message,
                        f" (tip: {issue.suggestion})" if issue.suggestion else "",
                    )
            for issue in report.issues:
                if issue.level == "warning":
                    _LOGGER.warning(
                        "  ⚠️ %s — %s%s",
                        issue.sensor_id, issue.message,
                        f" (tip: {issue.suggestion})" if issue.suggestion else "",
                    )
        elif report.warn_count:
            _LOGGER.warning(
                "CloudEMS health check: %d waarschuwing(en) — "
                "sommige features werken mogelijk niet",
                report.warn_count,
            )
            for issue in report.issues:
                _LOGGER.warning(
                    "  ⚠️ %s — %s%s",
                    issue.sensor_id, issue.message,
                    f" (tip: {issue.suggestion})" if issue.suggestion else "",
                )
        else:
            _LOGGER.info(
                "CloudEMS health check: alles ok (%d entiteiten gecontroleerd)",
                report.checked,
            )

        return report

    def _check_entity(self, entity_id: str, config_key: str, report: HealthReport,
                      level: str = "warning", zero_ok: bool = True,
                      expect_positive: bool = False) -> None:
        """Controleer één entiteit en voeg eventuele issues toe aan het rapport."""
        report.checked += 1

        # Guard: config-veld kan per ongeluk een int/bool zijn (bijv. poortnummer).
        # In dat geval stilletjes overslaan — geen crash, geen fout-melding.
        if not entity_id or not isinstance(entity_id, str):
            return

        state = self._hass.states.get(entity_id)

        if state is None:
            # Binnen de grace period na herstart: entiteit kan nog laden —
            # downgrade error → warning zodat health check niet onterecht rood wordt.
            elapsed = _time.monotonic() - self._startup_time
            if elapsed < _STARTUP_GRACE_SECONDS:
                report.issues.append(HealthIssue(
                    sensor_id  = entity_id,
                    level      = "warning",
                    message    = (f"Entiteit '{entity_id}' nog niet beschikbaar "
                                  f"({elapsed:.0f}s na herstart — grace period {_STARTUP_GRACE_SECONDS}s)."),
                    suggestion = "Automatisch opgelost zodra de integratie klaar is met opstarten.",
                ))
                report.warn_count += 1
            else:
                report.issues.append(HealthIssue(
                    sensor_id  = entity_id,
                    level      = level,
                    message    = f"Entiteit '{entity_id}' bestaat niet in Home Assistant.",
                    suggestion = (f"Controleer de instelling '{config_key}' in de CloudEMS wizard. "
                                  f"Misschien is de entiteit hernoemd of verwijderd."),
                ))
                if level == "error":
                    report.error_count += 1
                else:
                    report.warn_count += 1
            return

        # v4.6.247: 'unavailable' na herstart of 429 rate-limit → waarschuwing, geen fout
        if state.state in ("unavailable", "unknown"):
            # Check if it's a known cloud integration that rate-limits (Ariston etc.)
            report.issues.append(HealthIssue(
                sensor_id  = entity_id,
                level      = "warning",
                message    = f"Entiteit '{entity_id}' is tijdelijk niet beschikbaar ({state.state}). Mogelijk herstart of 429 rate-limit van cloud-integratie.",
                suggestion = "Wacht een paar minuten. CloudEMS gaat automatisch door zodra de entiteit beschikbaar is.",
            ))
            report.warn_count += 1
            return

        if state.state in ("unavailable", "unknown", ""):
            report.issues.append(HealthIssue(
                sensor_id  = entity_id,
                level      = level,
                message    = f"Entiteit '{entity_id}' is {state.state}.",
                suggestion = (f"Controleer of het apparaat of de integratie die "
                              f"'{entity_id}' levert actief is."),
            ))
            if level == "error":
                report.error_count += 1
            else:
                report.warn_count += 1
            return

        # Waarde-checks voor numerieke sensoren
        if not zero_ok or expect_positive:
            try:
                val = float(state.state)
                if expect_positive and val == 0.0:
                    # Niet per se een fout, maar wel verdacht — info niveau
                    report.issues.append(HealthIssue(
                        sensor_id  = entity_id,
                        level      = "info",
                        message    = f"Entiteit '{entity_id}' levert waarde 0.",
                        suggestion = ("Dit kan normaal zijn als er geen verbruik/productie is, "
                                      "maar controleer of de sensor correct is gekoppeld."),
                    ))
            except (ValueError, TypeError):
                pass  # Niet-numerieke sensor (bijv. switch) — geen waardecheck

        report.ok_count += 1

    def _check_boiler_unit(self, unit: dict, report: HealthReport) -> None:
        """Controleer alle entiteiten van één boiler-unit."""
        eid = unit.get("entity_id", "")
        if eid:
            self._check_entity(eid, f"boiler:{eid}", report, level="error")

        for field_key in ("temp_sensor", "energy_sensor", "flow_sensor"):
            feid = unit.get(field_key, "")
            if feid:
                self._check_entity(feid, f"boiler.{field_key}:{feid}",
                                   report, level="warning")


# ── v4.6.531: Runtime ConfigDriftDetector ────────────────────────────────────

import time as _time_module


class ConfigDriftDetector:
    """
    Monitort tijdens runtime of geconfigureerde entity_ids nog steeds
    bestaan en bruikbare data leveren.

    Problemen die dit detecteert:
    - Entity verdwenen na HA-update of integratie-herinstallatie
    - Entity hernoemd (andere entity_id)
    - Entity structureel unavailable (hardware probleem)
    - Entity bevroren (waarde verandert nooit ondanks actieve installatie)

    Aanroepen elke coordinator-cyclus via check_runtime().
    Hints worden maximaal 1× per uur herhaald.
    """

    CHECK_INTERVAL_S   = 300      # hercheck elke 5 minuten
    HINT_INTERVAL_S    = 3600     # hint maximaal 1× per uur per entity
    FROZEN_WINDOW_S    = 900      # 15 minuten geen verandering = bevroren
    FROZEN_GRID_MIN_W  = 200      # alleen detecteren als grid actief is
    MIN_SAMPLES_FROZEN = 30       # minimaal 30 samples voor bevroren-detectie

    def __init__(self, hass, config: dict, hint_engine=None) -> None:
        self._hass        = hass
        self._config      = config
        self._hint_engine = hint_engine
        self._last_check  = 0.0
        # {entity_id: {"last_value": float, "last_change_ts": float,
        #              "samples": int, "last_hint_ts": float}}
        self._state: dict[str, dict] = {}

    def check_runtime(
        self,
        grid_w: float = 0.0,
        decisions_history=None,
    ) -> list[dict]:
        """
        Controleer geconfigureerde entiteiten. Geeft lijst van issues terug.
        Goedkoop genoeg voor elke 10s cyclus (throttled intern op 5 min).
        """
        now = _time_module.time()
        if now - self._last_check < self.CHECK_INTERVAL_S:
            return []
        self._last_check = now

        issues = []
        entity_ids = self._collect_entity_ids()

        for eid in entity_ids:
            if not eid or not isinstance(eid, str):
                continue

            state_obj = self._hass.states.get(eid)
            s = self._state.setdefault(eid, {
                "last_value":     None,
                "last_change_ts": now,
                "samples":        0,
                "last_hint_ts":   0.0,
            })

            # ── Verdwenen ─────────────────────────────────────────────────
            if state_obj is None:
                issue = {
                    "entity_id":  eid,
                    "problem":    "missing",
                    "message":    f"Entiteit '{eid}' bestaat niet meer in HA.",
                    "suggestion": "Controleer of de integratie actief is of de entity_id hernoemd is.",
                }
                issues.append(issue)
                self._maybe_emit_hint(eid, s, "missing", issue["message"], now)
                self._log_issue(eid, "missing", issue["message"], decisions_history)
                continue

            # ── Unavailable ───────────────────────────────────────────────
            if state_obj.state in ("unavailable", "unknown"):
                issue = {
                    "entity_id":  eid,
                    "problem":    "unavailable",
                    "message":    f"Entiteit '{eid}' is {state_obj.state}.",
                    "suggestion": "Controleer het apparaat of de integratie.",
                }
                issues.append(issue)
                self._maybe_emit_hint(eid, s, "unavailable", issue["message"], now)
                continue

            # ── Bevroren ──────────────────────────────────────────────────
            try:
                val = float(state_obj.state)
            except (ValueError, TypeError):
                continue

            s["samples"] += 1
            if s["last_value"] is None:
                s["last_value"]     = val
                s["last_change_ts"] = now
            elif abs(val - s["last_value"]) > 0.5:
                s["last_value"]     = val
                s["last_change_ts"] = now

            frozen_age = now - s["last_change_ts"]
            if (
                s["samples"] >= self.MIN_SAMPLES_FROZEN
                and frozen_age > self.FROZEN_WINDOW_S
                and grid_w > self.FROZEN_GRID_MIN_W
            ):
                issue = {
                    "entity_id":  eid,
                    "problem":    "frozen",
                    "message":    (
                        f"Entiteit '{eid}' heeft al {frozen_age/60:.0f} min "
                        f"dezelfde waarde ({val:.1f}) terwijl het net actief is."
                    ),
                    "suggestion": "Controleer de sensor-verbinding of integratie.",
                }
                issues.append(issue)
                self._maybe_emit_hint(eid, s, "frozen", issue["message"], now)
                self._log_issue(eid, "frozen", issue["message"], decisions_history)

        return issues

    def _collect_entity_ids(self) -> list[str]:
        """Verzamel alle relevante entity_ids uit de config."""
        eids = set()
        simple_keys = [
            "grid_power_sensor", "pv_power_sensor", "battery_power_sensor",
            "battery_soc_sensor", "outside_temp_entity",
        ]
        for k in simple_keys:
            v = self._config.get(k, "")
            if v and isinstance(v, str):
                eids.add(v)

        for phase in ("l1", "l2", "l3"):
            for suffix in ("current_sensor", "voltage_sensor", "power_sensor"):
                k = f"phase_{phase}_{suffix}"
                v = self._config.get(k, "")
                if v and isinstance(v, str):
                    eids.add(v)

        for boiler_cfg in self._config.get("boiler_configs", []):
            for field in ("entity_id", "temp_sensor", "energy_sensor"):
                v = boiler_cfg.get(field, "")
                if v and isinstance(v, str):
                    eids.add(v)

        for ev_cfg in self._config.get("ev_chargers", []):
            v = ev_cfg.get("charger_entity", "")
            if v and isinstance(v, str):
                eids.add(v)

        return list(eids)

    def _maybe_emit_hint(
        self, eid: str, s: dict, problem: str, message: str, now: float
    ) -> None:
        if not self._hint_engine:
            return
        if now - s.get("last_hint_ts", 0) < self.HINT_INTERVAL_S:
            return
        s["last_hint_ts"] = now
        hint_titles = {
            "missing":     "Sensor verdwenen",
            "unavailable": "Sensor niet beschikbaar",
            "frozen":      "Sensor lijkt bevroren",
        }
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"config_drift_{problem}_{eid.replace('.', '_')}",
                title      = hint_titles.get(problem, f"Sensor probleem: {problem}"),
                message    = message,
                action     = f"Controleer entiteit '{eid}' in CloudEMS instellingen",
                confidence = 0.85 if problem == "missing" else 0.70,
            )
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).debug("ConfigDriftDetector hint fout: %s", _e)

    @staticmethod
    def _log_issue(
        eid: str, problem: str, message: str, decisions_history
    ) -> None:
        import logging as _log
        _log.getLogger(__name__).warning("ConfigDrift [%s]: %s", problem, message)
        if decisions_history:
            try:
                decisions_history.add(
                    category = "config_drift",
                    action   = f"entity_{problem}",
                    reason   = eid,
                    message  = message,
                    extra    = {"entity_id": eid, "problem": problem},
                )
            except Exception:
                pass
