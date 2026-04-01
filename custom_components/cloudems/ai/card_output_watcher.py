"""
CloudEMS Card Output Watcher — v2.0.0

Monitort de waarden die elke JS kaart voedt en logt problemen.
Antwoordt op: "waarom toont kaart X 0 / foute data?"

Elke coordinator tick:
  - Zijn waarden plausibel gezien andere waarden? (Kirchhoff)
  - Staat een waarde op 0 terwijl dat niet kan?
  - Ontbreekt een waarde terwijl de bronsenor beschikbaar is?

Elke 5 minuten: kaart-snapshot in de log zodat problemen zichtbaar zijn
ZONDER dat Joan screenshots hoeft te sturen.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

RELOG_INTERVAL_S   = 300   # hoe vaak dezelfde issue opnieuw loggen
SNAPSHOT_INTERVAL_S = 300  # hoe vaak een kaart-snapshot loggen


@dataclass
class CardIssue:
    card:       str
    field:      str
    expected:   str
    actual:     str
    severity:   str
    first_seen: float = field(default_factory=time.time)
    last_seen:  float = field(default_factory=time.time)
    last_logged: float = 0.0
    count:      int   = 1


class CardOutputWatcher:
    """
    Controleert coordinator data en logt kaart-output problemen.
    Roep watcher.check(data) elke coordinator tick aan.
    """

    def __init__(self) -> None:
        self._issues: dict[str, CardIssue] = {}
        self._resolved: list[str] = []
        self._check_count = 0
        self._last_snapshot_ts = 0.0
        self._last_summary_ts  = 0.0

    def check(self, data: dict[str, Any]) -> dict[str, Any]:
        self._check_count += 1
        now = time.time()
        new_issues: list[str] = []
        resolved:   list[str] = []

        solar_w   = float(data.get("solar_power",  0) or 0)
        export_w  = float(data.get("export_power", 0) or 0)
        import_w  = float(data.get("import_power", 0) or 0)
        grid_w    = float(data.get("grid_power",   0) or 0)
        house_w   = float(data.get("house_power",  0) or 0)
        battery_w = float(data.get("battery_power",0) or 0)
        batt_age  = float(data.get("battery_age_s",0) or 0)
        sc        = data.get("self_consumption", {}) or {}
        sc_pct    = sc.get("ratio_pct") or 0.0
        pv_today  = float(sc.get("pv_today_kwh") or 0)
        batt_soc  = data.get("battery_soc") or data.get("battery_soc_pct")
        p1_age    = float(data.get("p1_age_s", 0) or 0)
        cur_price = data.get("current_price") or data.get("epex_price_now")
        perf      = data.get("performance", {}) or {}

        # ── 1. Zelfconsumptie ─────────────────────────────────────────────────
        if solar_w >= 200:
            if sc_pct <= 0.1:
                if export_w == 0 and import_w == 0 and abs(grid_w) < 50:
                    cause = "export_power=0 EN import_power=0 EN grid≈0 — P1/balancer levert geen gridwaarde"
                elif export_w == 0 and solar_w > 200:
                    cause = f"export_power=0 terwijl solar={solar_w:.0f}W — sign-fout of balancer schrijft niet terug"
                elif sc.get("pv_today_kwh", 0) == 0:
                    cause = "pv_today_kwh=0 — zelfconsumptie tracker heeft geen PV data ontvangen vandaag"
                else:
                    cause = f"onbekend — solar={solar_w:.0f}W export={export_w:.0f}W grid={grid_w:.0f}W"
                self._raise("zelfconsumptie-card", "ratio_pct",
                            f">0% want solar={solar_w:.0f}W",
                            f"{sc_pct:.1f}% — {cause}", "error", new_issues)
            else:
                self._resolve("zelfconsumptie-card:ratio_pct", resolved)
        else:
            self._resolve("zelfconsumptie-card:ratio_pct", resolved)

        # ── 2. Self-healing card solar ────────────────────────────────────────
        # solar_power in coordinator.data moet zichtbaar zijn in de kaart.
        # Vuur alleen als solar_w PRECIES 0 is (sensor niet gevuld) én pv_today
        # substantieel is (>1 kWh) én het primaire zonne-uren zijn (9-17u).
        # Dit voorkomt false positives bij zonsop-/ondergang (legitiem <50W)
        # en bij de eerste cyclus na herstart.
        _solar_check_hour = __import__('datetime').datetime.now().hour
        _solar_zero = solar_w == 0 and pv_today > 1.0 and 9 <= _solar_check_hour <= 17
        if _solar_zero:
            # PV data accumuleert maar solar_power = 0 — sensor levert geen live waarde
            self._raise("self-healing-card", "solar_power",
                        f">0W want pv_today={pv_today:.2f}kWh",
                        f"{solar_w:.0f}W — coordinator solar_power niet gevuld", "error", new_issues)
        else:
            self._resolve("self-healing-card:solar_power", resolved)

        # ── 3. Self-healing card prijs ────────────────────────────────────────
        if cur_price is None:
            self._raise("price-card", "current_price",
                        "aanwezig", "None — EPEX data ontbreekt", "warning", new_issues)
        else:
            self._resolve("price-card:current_price", resolved)

        # ── 4. Flow card / huis Kirchhoff ─────────────────────────────────────
        if abs(solar_w) + abs(grid_w) > 200:
            kirchhoff = solar_w + grid_w - battery_w
            if house_w < -100:
                self._raise("flow-card", "house_power",
                            f">=0W (Kirchhoff={kirchhoff:.0f}W)",
                            f"{house_w:.0f}W", "error", new_issues)
            elif abs(house_w - kirchhoff) > 1000 and batt_age < 90:
                self._raise("flow-card", "house_power",
                            f"≈{kirchhoff:.0f}W",
                            f"{house_w:.0f}W (delta={house_w-kirchhoff:+.0f}W)", "warning", new_issues)
            else:
                self._resolve("flow-card:house_power", resolved)

        # ── 5. Battery card SoC ───────────────────────────────────────────────
        if batt_soc is None:
            self._raise("battery-card", "battery_soc",
                        "aanwezig", "None — geen SoC sensor", "warning", new_issues)
        else:
            self._resolve("battery-card:battery_soc", resolved)

        # ── 6. P1 kaart age ───────────────────────────────────────────────────
        if 90 < p1_age < 3600:
            self._raise("p1-card", "p1_data",
                        "<90s oud", f"p1_age={p1_age:.0f}s — P1 traag of offline", "warning", new_issues)
        else:
            self._resolve("p1-card:p1_data", resolved)

        # ── 7. Solar card pv_today_kwh ────────────────────────────────────────
        if solar_w > 500 and pv_today < 0.01:
            self._raise("solar-card", "pv_today_kwh",
                        f">0 want solar={solar_w:.0f}W",
                        f"{pv_today:.3f} kWh", "warning", new_issues)
        else:
            self._resolve("solar-card:pv_today_kwh", resolved)

        # ── 8. Performance / coordinator gezondheid ───────────────────────────
        avg_ms = float(perf.get("avg_ms", 0) or 0)
        if avg_ms > 500 and avg_ms > 0:
            self._raise("diagnose-card", "cycle_ms",
                        "<500ms", f"{avg_ms:.0f}ms — coordinator traag", "warning", new_issues)
        else:
            self._resolve("diagnose-card:cycle_ms", resolved)

        # ── Log nieuwe issues ─────────────────────────────────────────────────
        for key in new_issues:
            issue = self._issues[key]
            if now - issue.last_logged >= RELOG_INTERVAL_S:
                fn = _LOGGER.error if issue.severity == "error" else _LOGGER.warning
                fn("CloudEMS kaart-output fout [%s.%s]: verwacht %s, got %s (gezien %dx)",
                   issue.card, issue.field, issue.expected, issue.actual, issue.count)
                issue.last_logged = now

        for key in resolved:
            _LOGGER.info("CloudEMS kaart-output hersteld: %s", key)

        # ── Periodieke kaart-snapshot ─────────────────────────────────────────
        # Elke 5 min: log wat elke kaart zou tonen zodat diagnose mogelijk is
        # zonder screenshots
        if now - self._last_snapshot_ts >= SNAPSHOT_INTERVAL_S:
            self._last_snapshot_ts = now
            self._log_card_snapshot(data, solar_w, grid_w, house_w, battery_w,
                                     batt_soc, sc_pct, pv_today, cur_price, perf)

        # Periodieke samenvatting als er issues zijn
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

    def _log_card_snapshot(self, data: dict, solar_w: float, grid_w: float,
                            house_w: float, battery_w: float, batt_soc,
                            sc_pct: float, pv_today: float, cur_price, perf: dict) -> None:
        """Log een snapshot van alle kaartwaarden. Elke 5 minuten."""
        batt_str  = f"SoC={batt_soc:.0f}% {battery_w:+.0f}W" if batt_soc is not None else "SoC=?"
        price_str = f"{cur_price*100:.1f}ct/kWh" if cur_price is not None else "geen prijs"
        sc_str    = f"{sc_pct:.0f}% ({pv_today:.2f}kWh vandaag)" if sc_pct > 0 else f"0% (pv={pv_today:.2f}kWh)"
        mode      = perf.get("mode", "?")
        avg_ms    = perf.get("avg_ms", 0)
        _LOGGER.info(
            "CloudEMS kaart-snapshot | solar=%dW grid=%+.0fW huis=%.0fW accu=[%s] "
            "prijs=%s zelfconsumptie=%s mode=%s %.0fms",
            solar_w, grid_w, house_w, batt_str, price_str, sc_str, mode, avg_ms
        )

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
                card=card, field=field, expected=expected,
                actual=actual, severity=severity,
            )
            new_list.append(key)

    def _resolve(self, key: str, resolved_list: list) -> None:
        if key in self._issues:
            resolved_list.append(key)
            del self._issues[key]

    @property
    def status(self) -> dict:
        issues   = list(self._issues.values())
        errors   = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        return {
            "healthy":    len(errors) == 0,
            "n_errors":   len(errors),
            "n_warnings": len(warnings),
            "issues": [
                {
                    "card":     i.card,
                    "field":    i.field,
                    "severity": i.severity,
                    "expected": i.expected,
                    "actual":   i.actual,
                    "count":    i.count,
                    "age_s":    round(time.time() - i.first_seen),
                }
                for i in sorted(issues, key=lambda x: x.severity)
            ],
            "checks_run": self._check_count,
        }
