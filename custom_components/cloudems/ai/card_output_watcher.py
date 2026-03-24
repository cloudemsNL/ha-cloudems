"""
CloudEMS Card Output Watcher — v1.0.0

Monitors the values that feed every JS card and logs anomalies.
Answers the question: "why is card X showing 0 / wrong data?"

Checks every coordinator tick:
  - Is the value plausible given other known values? (Kirchhoff sanity)
  - Is a value stuck at 0 when it shouldn't be?
  - Is a value missing when its source sensor is available?
  - Does the value match what the JS card would show?

Logged at WARNING level so they appear in HA logs without debug mode.
Also stored as sensor.cloudems_card_health attributes for the Diagnose tab.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# How often to re-log the same issue (seconds) — avoid log spam
RELOG_INTERVAL_S = 300   # 5 minutes


@dataclass
class CardIssue:
    """One detected anomaly in card output."""
    card:       str        # card name
    field:      str        # which value
    expected:   str        # what we expected
    actual:     str        # what we got
    severity:   str        # "error" | "warning" | "info"
    first_seen: float = field(default_factory=time.time)
    last_seen:  float = field(default_factory=time.time)
    last_logged: float = 0.0
    count:      int   = 1


class CardOutputWatcher:
    """
    Monitors coordinator data dict and checks card output plausibility.

    Call watcher.check(data) every coordinator tick.
    Issues are logged and returned as a dict for the diagnose sensor.
    """

    def __init__(self) -> None:
        self._issues: dict[str, CardIssue] = {}  # key = "card:field"
        self._resolved: list[str] = []            # recently resolved
        self._check_count = 0
        self._last_summary_ts = 0.0

    def check(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Run all checks. Returns health status dict.
        Call every coordinator tick.
        """
        self._check_count += 1
        now = time.time()
        new_issues = []
        resolved   = []

        # ── 1. Zelfconsumptie ─────────────────────────────────────────────────
        solar_w  = float(data.get("solar_power", 0) or 0)
        export_w = float(data.get("export_power", 0) or 0)
        import_w = float(data.get("import_power", 0) or 0)
        grid_w   = float(data.get("grid_power",   0) or 0)
        sc       = data.get("self_consumption", {}) or {}
        sc_pct   = sc.get("ratio_pct") or 0.0

        if solar_w >= 200:
            # Zon schijnt — zelfconsumptie mag niet 0 zijn
            if sc_pct <= 0.1:
                # Root cause analyse: waarom is zelfconsumptie 0?
                if export_w == 0 and import_w == 0 and abs(grid_w) < 50:
                    cause = f"export_power=0 EN import_power=0 EN grid≈0 — P1/balancer levert geen gridwaarde"
                elif export_w == 0 and solar_w > 200:
                    cause = f"export_power=0 terwijl solar={solar_w:.0f}W — sign-fout of balancer schrijft niet terug"
                elif sc.get("pv_today_kwh", 0) == 0:
                    cause = f"pv_today_kwh=0 — zelfconsumptie tracker heeft geen PV data ontvangen vandaag"
                else:
                    cause = f"onbekend — solar={solar_w:.0f}W export={export_w:.0f}W grid={grid_w:.0f}W sc_raw={sc}"
                self._raise(
                    "zelfconsumptie-card", "ratio_pct",
                    f">{0:.0f}% want solar={solar_w:.0f}W",
                    f"{sc_pct:.1f}% — oorzaak: {cause}",
                    "error", new_issues
                )
            else:
                self._resolve("zelfconsumptie-card:ratio_pct", resolved)

            # export_power moet aanwezig zijn als zon schijnt
            if export_w == 0 and import_w == 0 and abs(grid_w) < 50:
                self._raise(
                    "zelfconsumptie-card", "export_power",
                    f"!= 0 want solar={solar_w:.0f}W en grid≈0",
                    f"export={export_w:.0f}W import={import_w:.0f}W grid={grid_w:.0f}W",
                    "error", new_issues
                )
            else:
                self._resolve("zelfconsumptie-card:export_power", resolved)
        else:
            self._resolve("zelfconsumptie-card:ratio_pct", resolved)
            self._resolve("zelfconsumptie-card:export_power", resolved)

        # ── 2. Energiestroom / THUIS ──────────────────────────────────────────
        house_w   = float(data.get("house_power", 0) or 0)
        battery_w = float(data.get("battery_power", 0) or 0)
        batt_age  = float(data.get("battery_age_s", 0) or 0)

        # Kirchhoff: house = solar + grid - battery (met teken: + = laden)
        kirchhoff = solar_w + grid_w - battery_w
        if abs(solar_w) + abs(grid_w) > 200:
            if house_w < -100:
                self._raise(
                    "flow-card", "house_power",
                    f">= 0W (Kirchhoff={kirchhoff:.0f}W)",
                    f"{house_w:.0f}W",
                    "error", new_issues
                )
            elif abs(house_w - kirchhoff) > 1000 and batt_age < 90:
                self._raise(
                    "flow-card", "house_power",
                    f"≈{kirchhoff:.0f}W (Kirchhoff)",
                    f"{house_w:.0f}W (delta={house_w-kirchhoff:+.0f}W)",
                    "warning", new_issues
                )
            else:
                self._resolve("flow-card:house_power", resolved)
        
        # Nexus battery stale check
        if batt_age > 90 and abs(battery_w) > 100:
            self._raise(
                "flow-card", "battery_stale",
                f"< 90s oud",
                f"battery_age={batt_age:.0f}s — Kirchhoff compenseert",
                "warning", new_issues
            )
        else:
            self._resolve("flow-card:battery_stale", resolved)

        # ── 3. Solar card ──────────────────────────────────────────────────────
        pv_today = float((data.get("self_consumption") or {}).get("pv_today_kwh") or 0)
        if solar_w > 500 and pv_today < 0.01:
            self._raise(
                "solar-card", "pv_today_kwh",
                f"> 0 want solar={solar_w:.0f}W actief",
                f"{pv_today:.3f} kWh",
                "warning", new_issues
            )
        else:
            self._resolve("solar-card:pv_today_kwh", resolved)

        # ── 4. Battery card ────────────────────────────────────────────────────
        batt_soc = data.get("battery_soc") or data.get("battery_soc_pct")
        if batt_soc is None:
            self._raise(
                "battery-card", "battery_soc",
                "aanwezig",
                "None — geen SoC sensor gekoppeld",
                "warning", new_issues
            )
        else:
            self._resolve("battery-card:battery_soc", resolved)

        # ── 5. P1 card ─────────────────────────────────────────────────────────
        p1_data = data.get("p1_data") or {}
        p1_age  = float(data.get("p1_age_s", 0) or 0)
        if p1_age > 90 and p1_age < 3600:
            self._raise(
                "p1-card", "p1_data",
                f"< 90s oud",
                f"p1_age={p1_age:.0f}s — P1 reader traag of offline",
                "warning", new_issues
            )
        else:
            self._resolve("p1-card:p1_data", resolved)

        # ── 6. Price card ──────────────────────────────────────────────────────
        cur_price = data.get("current_price") or data.get("epex_price_now")
        if cur_price is None:
            self._raise(
                "price-card", "current_price",
                "aanwezig",
                "None — EPEX data ontbreekt",
                "warning", new_issues
            )
        else:
            self._resolve("price-card:current_price", resolved)

        # ── Log new issues ─────────────────────────────────────────────────────
        for key in new_issues:
            issue = self._issues[key]
            if now - issue.last_logged >= RELOG_INTERVAL_S:
                fn = _LOGGER.error if issue.severity == "error" else _LOGGER.warning
                fn(
                    "CloudEMS kaart-output fout [%s.%s]: verwacht %s, got %s (gezien %dx)",
                    issue.card, issue.field, issue.expected, issue.actual, issue.count
                )
                issue.last_logged = now

        # Log resolutions
        for key in resolved:
            _LOGGER.info("CloudEMS kaart-output hersteld: %s", key)

        # Periodic summary if issues persist
        if self._issues and (now - self._last_summary_ts) >= 600:
            self._last_summary_ts = now
            errors   = [i for i in self._issues.values() if i.severity == "error"]
            warnings = [i for i in self._issues.values() if i.severity == "warning"]
            if errors:
                _LOGGER.error(
                    "CloudEMS kaart-health samenvatting: %d errors, %d warnings — "
                    "zie sensor.cloudems_card_health voor details",
                    len(errors), len(warnings)
                )

        return self.status

    def _raise(self, card: str, field: str, expected: str, actual: str,
               severity: str, new_list: list) -> None:
        key = f"{card}:{field}"
        now = time.time()
        if key in self._issues:
            self._issues[key].last_seen = now
            self._issues[key].count    += 1
            self._issues[key].actual    = actual
        else:
            self._issues[key] = CardIssue(
                card=card, field=field,
                expected=expected, actual=actual,
                severity=severity,
            )
            new_list.append(key)

    def _resolve(self, key: str, resolved_list: list) -> None:
        if key in self._issues:
            resolved_list.append(key)
            del self._issues[key]

    @property
    def status(self) -> dict:
        issues = list(self._issues.values())
        errors   = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        return {
            "healthy":   len(errors) == 0,
            "n_errors":  len(errors),
            "n_warnings": len(warnings),
            "issues": [
                {
                    "card":      i.card,
                    "field":     i.field,
                    "severity":  i.severity,
                    "expected":  i.expected,
                    "actual":    i.actual,
                    "count":     i.count,
                    "age_s":     round(time.time() - i.first_seen),
                }
                for i in sorted(issues, key=lambda x: x.severity)
            ],
            "checks_run": self._check_count,
        }
