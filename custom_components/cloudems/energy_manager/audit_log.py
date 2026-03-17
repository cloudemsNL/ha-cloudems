"""
CloudEMS — audit_log.py
Gestructureerd audit log voor alle sturings-events.

Principe:
  - Elk commando dat gestuurd wordt → AUDIT entry
  - Elk verificatie-resultaat → UPDATE op die entry  
  - Elk uur na zonsondergang → PV forecast vs actual vergelijking
  - Guardian leest dit log en detecteert patronen

Het log is zelf-lerend: het detecteert wanneer het informatie mist en
voegt automatisch nieuwe velden toe zodra die beschikbaar komen.

Structuur per entry:
  {
    "id":          str,          # uniek ID (timestamp + type)
    "ts":          float,        # unix timestamp
    "type":        str,          # "command" | "battery_verify" | "pv_forecast" | "sensor_check"
    "module":      str,          # welk module (zonneplan_bridge, shutter_controller, ...)
    "entity_id":   str,          # welke entity
    "action":      str,          # wat gedaan
    "expected":    Any,          # wat verwacht
    "actual":      Any,          # wat gemeten (None = nog niet geverifieerd)
    "success":     bool | None,  # None = pending
    "attempts":    int,
    "duration_ms": float | None, # hoe lang duurde de verificatie
    "context":     dict,         # extra context (solar_w, soc_pct, etc.)
    "missing_fields": list[str], # velden die ontbreken maar nuttig zouden zijn
  }
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# Max entries in ringbuffer
_MAX_ENTRIES = 500
_MAX_FAILURES = 100  # aparte failure ringbuffer

# Velden die nuttig zijn per type — detecteert ontbrekende context
_DESIRED_CONTEXT = {
    "command": {"solar_w", "grid_w", "battery_w", "soc_pct", "price_eur_kwh"},
    "battery_verify": {"solar_w", "grid_w", "soc_pct", "battery_w_before", "battery_w_after"},
    "pv_forecast": {"forecast_kwh", "actual_kwh", "deviation_pct", "hour"},
    "sensor_check": {"sensor_age_s", "last_known_value"},
    "zp_drift": {"expected_mode", "actual_mode", "drift_duration_s"},
}


class AuditLog:
    """Zelf-lerend audit log voor alle CloudEMS sturings-events."""

    def __init__(self):
        self._entries: deque = deque(maxlen=_MAX_ENTRIES)
        self._failures: deque = deque(maxlen=_MAX_FAILURES)
        # Patroon-detectie: per entity bijhouden hoeveel failures
        self._fail_counts: dict[str, int] = {}
        self._total_commands = 0
        self._total_failures = 0
        self._total_verifications = 0
        # Zelf-lerend: bijhouden welke context-velden vaak ontbreken
        self._missing_field_counts: dict[str, int] = {}
        # PV forecast tracking: {hour: {"forecast": float, "actual": float}}
        self._pv_forecast_by_hour: dict[int, dict] = {}

    # ── Primaire API ──────────────────────────────────────────────────────────

    def record_command(
        self,
        module: str,
        entity_id: str,
        action: str,
        expected: Any,
        context: dict | None = None,
    ) -> str:
        """Registreer een nieuw commando. Geeft entry_id terug voor latere update."""
        entry_id = f"{time.time():.3f}_{module}_{entity_id[:20]}"
        context = context or {}

        # Detecteer ontbrekende nuttige context
        desired = _DESIRED_CONTEXT.get("command", set())
        missing = [f for f in desired if f not in context]
        for f in missing:
            self._missing_field_counts[f] = self._missing_field_counts.get(f, 0) + 1

        entry = {
            "id":           entry_id,
            "ts":           time.time(),
            "type":         "command",
            "module":       module,
            "entity_id":    entity_id,
            "action":       action,
            "expected":     expected,
            "actual":       None,
            "success":      None,
            "attempts":     1,
            "duration_ms":  None,
            "context":      context,
            "missing_fields": missing,
        }
        self._entries.append(entry)
        self._total_commands += 1
        return entry_id

    def update_command(
        self,
        entry_id: str,
        success: bool,
        actual: Any,
        attempts: int,
        duration_ms: float | None = None,
        extra_context: dict | None = None,
    ) -> None:
        """Update een eerder geregistreerd commando met verificatie-resultaat."""
        self._total_verifications += 1
        for entry in reversed(self._entries):
            if entry.get("id") == entry_id:
                entry["success"] = success
                entry["actual"] = actual
                entry["attempts"] = attempts
                entry["duration_ms"] = duration_ms
                if extra_context:
                    entry["context"].update(extra_context)
                    # Hercheck missing fields
                    desired = _DESIRED_CONTEXT.get("command", set())
                    entry["missing_fields"] = [
                        f for f in desired if f not in entry["context"]
                    ]
                if not success:
                    self._total_failures += 1
                    self._fail_counts[entry["entity_id"]] = (
                        self._fail_counts.get(entry["entity_id"], 0) + 1
                    )
                    self._failures.append(entry)
                    _LOGGER.warning(
                        "CloudEMS audit: FAILURE %s → %s (poging %d, verwacht %s, werkelijk %s)",
                        entry["module"], entry["entity_id"], attempts,
                        entry["expected"], actual,
                    )
                return
        _LOGGER.debug("CloudEMS audit: entry_id %s niet gevonden voor update", entry_id)

    def record_battery_verify(
        self,
        expected_action: str,
        battery_w_before: float,
        battery_w_after: float,
        soc_pct: float | None,
        context: dict | None = None,
    ) -> None:
        """Registreer een battery-control verificatie (was effect zichtbaar?)."""
        context = context or {}
        # Bepaal of de actie effect had
        delta = battery_w_after - battery_w_before
        if expected_action == "charge":
            success = battery_w_after > 100 or delta > 200
        elif expected_action == "discharge":
            success = battery_w_after < -100 or delta < -200
        else:  # hold / powerplay
            success = True  # hold heeft altijd "succes" — geen meetbare verwachting

        missing = [f for f in _DESIRED_CONTEXT.get("battery_verify", set())
                   if f not in {**context, "battery_w_before": battery_w_before,
                                 "battery_w_after": battery_w_after, "soc_pct": soc_pct}]
        entry = {
            "id":           f"{time.time():.3f}_bat_verify",
            "ts":           time.time(),
            "type":         "battery_verify",
            "module":       "battery_control",
            "entity_id":    "battery",
            "action":       expected_action,
            "expected":     {"action": expected_action},
            "actual":       {"battery_w_before": battery_w_before,
                             "battery_w_after": battery_w_after,
                             "delta_w": delta},
            "success":      success,
            "attempts":     1,
            "duration_ms":  None,
            "context":      {**context, "soc_pct": soc_pct},
            "missing_fields": missing,
        }
        self._entries.append(entry)
        if not success:
            self._failures.append(entry)
            self._total_failures += 1
            _LOGGER.warning(
                "CloudEMS audit: batterij-actie %s had geen zichtbaar effect "
                "(voor: %.0fW, na: %.0fW, delta: %.0fW)",
                expected_action, battery_w_before, battery_w_after, delta,
            )

    def record_pv_forecast(
        self,
        hour: int,
        forecast_kwh: float,
        actual_kwh: float,
    ) -> None:
        """Vergelijk PV forecast vs actual voor een afgelopen uur."""
        deviation_pct = (
            round((actual_kwh - forecast_kwh) / forecast_kwh * 100, 1)
            if forecast_kwh > 0.01 else 0.0
        )
        self._pv_forecast_by_hour[hour] = {
            "forecast_kwh": round(forecast_kwh, 3),
            "actual_kwh":   round(actual_kwh, 3),
            "deviation_pct": deviation_pct,
            "ts":           time.time(),
        }
        entry = {
            "id":           f"{time.time():.3f}_pv_h{hour}",
            "ts":           time.time(),
            "type":         "pv_forecast",
            "module":       "pv_forecast",
            "entity_id":    f"pv_hour_{hour}",
            "action":       "forecast_check",
            "expected":     forecast_kwh,
            "actual":       actual_kwh,
            "success":      abs(deviation_pct) < 25,
            "attempts":     1,
            "duration_ms":  None,
            "context":      {"hour": hour, "deviation_pct": deviation_pct},
            "missing_fields": [],
        }
        self._entries.append(entry)
        if abs(deviation_pct) >= 25:
            _LOGGER.info(
                "CloudEMS audit: PV forecast uur %d afwijking %.1f%% "
                "(verwacht %.3f kWh, werkelijk %.3f kWh)",
                hour, deviation_pct, forecast_kwh, actual_kwh,
            )

    def record_zp_drift(
        self,
        expected_mode: str,
        actual_mode: str,
        drift_duration_s: float,
        context: dict | None = None,
    ) -> None:
        """Registreer dat Zonneplan van de verwachte modus afgeweken is."""
        entry = {
            "id":           f"{time.time():.3f}_zp_drift",
            "ts":           time.time(),
            "type":         "zp_drift",
            "module":       "zonneplan_bridge",
            "entity_id":    "zonneplan_control_mode",
            "action":       "drift_detected",
            "expected":     expected_mode,
            "actual":       actual_mode,
            "success":      False,
            "attempts":     0,
            "duration_ms":  drift_duration_s * 1000,
            "context":      context or {},
            "missing_fields": [f for f in _DESIRED_CONTEXT.get("zp_drift", set())
                                if f not in (context or {})],
        }
        self._entries.append(entry)
        self._failures.append(entry)
        self._total_failures += 1
        _LOGGER.warning(
            "CloudEMS audit: ZP drift gedetecteerd — verwacht %s, werkelijk %s (%.0fs)",
            expected_mode, actual_mode, drift_duration_s,
        )

    # ── Statistieken & zelf-lerende inzichten ────────────────────────────────

    def get_problematic_entities(self, min_failures: int = 2) -> list[dict]:
        """Geef entities die meerdere keren gefaald hebben."""
        return [
            {"entity_id": eid, "failures": cnt}
            for eid, cnt in sorted(
                self._fail_counts.items(), key=lambda x: -x[1]
            )
            if cnt >= min_failures
        ]

    def get_missing_context_report(self) -> list[dict]:
        """Geef velden die vaak ontbreken — input voor verbetering van logging."""
        return [
            {"field": f, "missing_count": cnt}
            for f, cnt in sorted(
                self._missing_field_counts.items(), key=lambda x: -x[1]
            )
            if cnt >= 3
        ]

    def get_pv_accuracy_summary(self) -> dict:
        """Geef nauwkeurigheid van PV forecast per uur."""
        if not self._pv_forecast_by_hour:
            return {}
        devs = [abs(v["deviation_pct"]) for v in self._pv_forecast_by_hour.values()]
        return {
            "hours_tracked":  len(devs),
            "avg_deviation_pct": round(sum(devs) / len(devs), 1),
            "max_deviation_pct": round(max(devs), 1),
            "by_hour": self._pv_forecast_by_hour,
        }

    def get_summary(self) -> dict:
        """Samenvatting voor sensor/dashboard."""
        recent = list(self._entries)[-20:]
        failures_24h = [
            e for e in self._failures
            if time.time() - e["ts"] < 86400
        ]
        return {
            "total_commands":       self._total_commands,
            "total_verifications":  self._total_verifications,
            "total_failures":       self._total_failures,
            "failures_24h":         len(failures_24h),
            "failure_rate_pct":     round(
                self._total_failures / max(self._total_verifications, 1) * 100, 1
            ),
            "problematic_entities": self.get_problematic_entities(),
            "missing_context":      self.get_missing_context_report(),
            "pv_accuracy":          self.get_pv_accuracy_summary(),
            "recent_failures": [
                {
                    "ts":        e["ts"],
                    "module":    e["module"],
                    "entity_id": e["entity_id"],
                    "action":    e["action"],
                    "expected":  str(e["expected"])[:50],
                    "actual":    str(e["actual"])[:50],
                    "attempts":  e["attempts"],
                }
                for e in sorted(failures_24h, key=lambda x: -x["ts"])[:10]
            ],
            "recent_entries": [
                {
                    "ts":      e["ts"],
                    "type":    e["type"],
                    "module":  e["module"],
                    "action":  e["action"],
                    "success": e["success"],
                }
                for e in reversed(recent)
            ],
        }


# Singleton — gedeeld door alle modules
_GLOBAL_AUDIT: AuditLog | None = None


def get_audit_log() -> AuditLog:
    """Geef de globale audit log instantie."""
    global _GLOBAL_AUDIT
    if _GLOBAL_AUDIT is None:
        _GLOBAL_AUDIT = AuditLog()
    return _GLOBAL_AUDIT
