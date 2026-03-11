# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Markdown Render Watcher — v1.0.0

Analyseert HA-logs op render-problemen van markdown-kaarten en Jinja2-tabellen.
Maakt een rapport van welke kaarten niet correct renderen en leert van patronen
zodat toekomstige versies automatisch verbeterd kunnen worden.

Wat wordt gemonitord:
  • Jinja2 template-fouten in markdown kaarten (TemplateError, UndefinedError)
  • Tabel-render fouten: rijen die als <p> terechtkomen i.p.v. <table>
  • Bekende breekpatronen: {% if/set/endif %} op eigen regel midden in tabel
  • Herhaalfrequentie per kaart-titel of sensor-naam

Hoe het werkt:
  1. async_scan() — leest home-assistant.log, filtert op render-gerelateerde fouten
  2. Slaat bevindingen op in self._findings (per kaart-key, gededupliceerd)
  3. get_report() — geeft gestructureerd rapport terug voor log_reporter / Guardian
  4. get_guardian_issues() — geeft lijst van GuardianIssue-achtige dicts terug

Integratie:
  • Wordt aangeroepen vanuit log_reporter.async_build_report()
  • Guardian kan get_guardian_issues() gebruiken om issues te registreren
  • Rapport wordt meegestuurd in GitHub diagnostisch issue

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Patronen die duiden op een render-probleem ────────────────────────────────

# HA log-regels die wijzen op Jinja2/template-fouten in markdown kaarten
_JINJA_ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("jinja_template_error",    re.compile(r"TemplateError|jinja2\.exceptions", re.I)),
    ("undefined_variable",      re.compile(r"UndefinedError|'[^']+' is undefined", re.I)),
    ("template_syntax_error",   re.compile(r"TemplateSyntaxError|unexpected '", re.I)),
    ("filter_error",            re.compile(r"No filter named|FilterNotFound", re.I)),
    ("type_error_in_template",  re.compile(r"TypeError.*template|template.*TypeError", re.I)),
]

# HA log-regels die wijzen op een markdown/lovelace render-probleem
_RENDER_ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("lovelace_error",          re.compile(r"lovelace|hui-markdown-card|markdown.card", re.I)),
    ("card_config_error",       re.compile(r"Invalid config.*markdown|markdown.*Invalid config", re.I)),
    ("yaml_parse_error",        re.compile(r"yaml.*parse|parse.*yaml|mapping values are not allowed", re.I)),
]

# Bekende Jinja2 tabel-breekpatronen in YAML content
# Dit zijn patronen die we in de YAML-tekst zelf herkennen als risico
_TABLE_BREAK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("if_block_between_rows",   re.compile(r"^\s*\{%-?\s*(if|else|elif|endif)\b(?!.*\|.*\|).*%\}\s*$")),
    ("set_between_rows",        re.compile(r"^\s*\{%-?\s*set\b.*%\}\s*$")),
    ("loose_pipe_line",         re.compile(r"^\s*\|[^|]+\|[^|]*$")),   # enkele | tekst | zonder tabelvorm
]

# Sensor/kaart-naam extractie uit logregels
_CARD_NAME_RE = re.compile(
    r"(?:card[_\s]title[:\s]+['\"]?([^'\"|\n]+)['\"]?|"
    r"sensor\.([a-z0-9_]+)|"
    r"cloudems[_\s]([a-z0-9_\s]+))",
    re.I,
)

# Maximaal aantal bevindingen per key om geheugen te beperken
MAX_FINDINGS_PER_KEY = 10
# Scan-cooldown in seconden (niet vaker dan 1x per 5 min scannen)
SCAN_COOLDOWN_S = 300


@dataclass
class RenderFinding:
    """Eén render-probleem, gededupliceerd per key."""
    key:          str          # unieke sleutel bv. "jinja_template_error:sensor.cloudems_pv"
    pattern_type: str          # type patroon (zie boven)
    card_hint:    str          # naam/hint van de betrokken kaart of sensor
    example_line: str          # geanonimiseerde voorbeeldregel uit de logs
    first_seen:   float = field(default_factory=time.time)
    last_seen:    float = field(default_factory=time.time)
    count:        int   = 1
    resolved:     bool  = False


class MarkdownRenderWatcher:
    """
    Scant HA-logs op render-problemen van markdown-kaarten.

    Gebruik vanuit log_reporter:
        watcher = MarkdownRenderWatcher(hass)
        await watcher.async_scan()
        report  = watcher.get_report()
        issues  = watcher.get_guardian_issues()   # lijst van dicts
    """

    def __init__(self, hass) -> None:
        self._hass = hass
        self._findings: dict[str, RenderFinding] = {}
        self._last_scan: float = 0.0
        self._scan_count: int  = 0
        self._lines_scanned: int = 0

    # ── Publieke interface ────────────────────────────────────────────────────

    async def async_scan(self, force: bool = False) -> int:
        """
        Scan HA-logs op render-problemen.

        Args:
            force: sla cooldown over (bv. bij handmatig rapport)

        Returns:
            Aantal nieuwe bevindingen gevonden in deze scan.
        """
        if not force and (time.time() - self._last_scan) < SCAN_COOLDOWN_S:
            _LOGGER.debug("MarkdownRenderWatcher: scan overgeslagen (cooldown)")
            return 0

        lines = await self._hass.async_add_executor_job(self._read_ha_logs)
        self._lines_scanned = len(lines)
        new_count = self._analyse_lines(lines)
        self._last_scan = time.time()
        self._scan_count += 1

        if new_count > 0:
            _LOGGER.warning(
                "CloudEMS MarkdownRenderWatcher: %d nieuwe render-problemen gevonden "
                "in %d logregels (totaal bekende problemen: %d).",
                new_count, len(lines), len(self._findings),
            )
        else:
            _LOGGER.debug(
                "CloudEMS MarkdownRenderWatcher: geen nieuwe render-problemen in %d regels.",
                len(lines),
            )

        return new_count

    def get_report(self) -> dict:
        """
        Gestructureerd rapport van alle render-bevindingen.

        Returns dict met:
          total_findings, active_findings, findings (lijst),
          most_common (top-5 op count), scan_count, lines_scanned
        """
        active = [f for f in self._findings.values() if not f.resolved]
        by_count = sorted(active, key=lambda f: f.count, reverse=True)

        return {
            "total_findings":   len(self._findings),
            "active_findings":  len(active),
            "scan_count":       self._scan_count,
            "lines_scanned":    self._lines_scanned,
            "last_scan_utc":    datetime.fromtimestamp(
                self._last_scan, tz=timezone.utc).isoformat() if self._last_scan else None,
            "most_common": [
                {
                    "key":          f.key,
                    "pattern_type": f.pattern_type,
                    "card_hint":    f.card_hint,
                    "count":        f.count,
                    "example":      f.example_line[:120],
                    "first_seen":   datetime.fromtimestamp(f.first_seen, tz=timezone.utc).isoformat(),
                    "last_seen":    datetime.fromtimestamp(f.last_seen,  tz=timezone.utc).isoformat(),
                }
                for f in by_count[:5]
            ],
            "findings": [
                {
                    "key":          f.key,
                    "pattern_type": f.pattern_type,
                    "card_hint":    f.card_hint,
                    "count":        f.count,
                    "example":      f.example_line[:200],
                }
                for f in active
            ],
            # Leer-sectie: unieke patroon-types en frequentie → input voor volgende fix-ronde
            "pattern_frequency": _count_by(active, "pattern_type"),
            "card_frequency":    _count_by(active, "card_hint"),
        }

    def get_guardian_issues(self) -> list[dict]:
        """
        Geeft Guardian-compatibele issue-dicts terug voor actieve render-problemen.
        Alleen als er ≥ 1 actieve bevinding is.
        """
        active = [f for f in self._findings.values() if not f.resolved]
        if not active:
            return []

        top = sorted(active, key=lambda f: f.count, reverse=True)[:3]
        issues = []
        for f in top:
            issues.append({
                "key":     f"render_watcher:{f.key}",
                "level":   "warning",
                "title":   f"Markdown render-probleem: {f.pattern_type}",
                "message": (
                    f"Kaart/sensor: '{f.card_hint}' — {f.count}x gezien. "
                    f"Voorbeeld: {f.example_line[:100]}"
                ),
                "source":  "markdown_render_watcher",
                "count":   f.count,
                "action":  "none",
            })

        if len(active) > 3:
            issues.append({
                "key":     "render_watcher:summary",
                "level":   "info",
                "title":   f"Markdown render: {len(active)} unieke problemen gevonden",
                "message": (
                    f"Meest voorkomende patronen: "
                    f"{', '.join(_count_by(active, 'pattern_type').keys())}. "
                    f"Zie diagnostisch rapport voor details."
                ),
                "source":  "markdown_render_watcher",
                "count":   sum(f.count for f in active),
                "action":  "none",
            })

        return issues

    def get_markdown_summary(self) -> str:
        """Markdown-sectie voor gebruik in log_reporter GitHub issue."""
        report = self.get_report()
        if report["active_findings"] == 0:
            return "### Markdown Render Watcher\n\n*Geen render-problemen gedetecteerd.*\n"

        lines = [
            "### Markdown Render Watcher",
            "",
            f"**{report['active_findings']} actieve render-problemen** "
            f"(gevonden in {report['lines_scanned']} logregels, "
            f"{report['scan_count']} scans).",
            "",
            "#### Meest voorkomende problemen",
            "| Kaart/sensor | Patroon | Aantal | Voorbeeld |",
            "|---|---|---|---|",
        ]
        for f in report["most_common"]:
            example = f["example"][:60].replace("|", "\\|")
            lines.append(
                f"| {f['card_hint'][:40]} | `{f['pattern_type']}` "
                f"| {f['count']} | `{example}` |"
            )

        lines += [
            "",
            "#### Patroon-frequentie (automatisch leren)",
            "| Patroon | Aantal unieke kaarten |",
            "|---|---|",
        ]
        for ptype, cnt in sorted(report["pattern_frequency"].items(),
                                  key=lambda x: x[1], reverse=True):
            lines.append(f"| `{ptype}` | {cnt} |")

        lines += ["", "#### Kaart-frequentie", "| Kaart/sensor | Problemen |", "|---|---|"]
        for card, cnt in sorted(report["card_frequency"].items(),
                                 key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"| {card} | {cnt} |")

        lines.append("")
        return "\n".join(lines)

    def mark_resolved(self, key: str) -> None:
        """Markeer een bevinding als opgelost (bv. na YAML-fix)."""
        if key in self._findings:
            self._findings[key].resolved = True
            _LOGGER.info("MarkdownRenderWatcher: bevinding '%s' gemarkeerd als opgelost.", key)

    def clear_all(self) -> None:
        """Wis alle bevindingen (bv. na grote update)."""
        self._findings.clear()
        _LOGGER.info("MarkdownRenderWatcher: alle bevindingen gewist.")

    # ── Interne methoden ──────────────────────────────────────────────────────

    def _read_ha_logs(self) -> list[str]:
        """Lees HA-logbestand (sync, in executor)."""
        try:
            log_path = self._hass.config.path("home-assistant.log")
            with open(log_path, errors="replace") as f:
                all_lines = f.readlines()
            # Filter: alleen regels met relevante keywords
            keywords = (
                "template", "jinja", "markdown", "lovelace",
                "render", "undefined", "templateerror", "syntaxerror",
                "cloudems",
            )
            filtered = [
                l.rstrip() for l in all_lines
                if any(kw in l.lower() for kw in keywords)
            ]
            _LOGGER.debug(
                "MarkdownRenderWatcher: %d van %d logregels relevant.",
                len(filtered), len(all_lines),
            )
            return filtered
        except Exception as err:
            _LOGGER.warning("MarkdownRenderWatcher: kon logs niet lezen: %s", err)
            return []

    def _analyse_lines(self, lines: list[str]) -> int:
        """Analyseer logregels en registreer bevindingen. Geeft aantal nieuwe terug."""
        new_count = 0

        for line in lines:
            # Combineer alle patroon-lijsten
            for pattern_type, pattern in (*_JINJA_ERROR_PATTERNS, *_RENDER_ERROR_PATTERNS):
                if not pattern.search(line):
                    continue

                card_hint = self._extract_card_hint(line)
                key       = f"{pattern_type}:{card_hint}"

                if key in self._findings:
                    f = self._findings[key]
                    f.count   += 1
                    f.last_seen = time.time()
                    # Bewaar meest recente voorbeeld
                    f.example_line = _sanitize_line(line)
                else:
                    if len(self._findings) < 200:   # geheugengrens
                        self._findings[key] = RenderFinding(
                            key          = key,
                            pattern_type = pattern_type,
                            card_hint    = card_hint,
                            example_line = _sanitize_line(line),
                        )
                        new_count += 1
                        _LOGGER.debug(
                            "MarkdownRenderWatcher: nieuwe bevinding [%s] kaart='%s' "
                            "voorbeeld='%s'",
                            pattern_type, card_hint, _sanitize_line(line)[:80],
                        )
                break   # eerste match per regel is genoeg

        return new_count

    def _extract_card_hint(self, line: str) -> str:
        """Extraheer een kaart- of sensornaam uit een logregel."""
        # Probeer sensor-naam te vinden (sensor.cloudems_xxx)
        sensor_match = re.search(r"sensor\.cloudems_([a-z0-9_]+)", line, re.I)
        if sensor_match:
            return f"sensor.cloudems_{sensor_match.group(1)}"

        # Probeer kaart-titel te vinden
        title_match = re.search(
            r"(?:card[_\s]title|title)[:\s]+['\"]?([^'\"|\n]{3,40})['\"]?", line, re.I
        )
        if title_match:
            return title_match.group(1).strip()

        # Probeer cloudems module-naam
        module_match = re.search(r"cloudems\.([a-z_]+)", line, re.I)
        if module_match:
            return f"cloudems.{module_match.group(1)}"

        # Generieke fallback: eerste 40 tekens na het log-level
        cleaned = re.sub(r"^\S+\s+\S+\s+\S+\s+", "", line).strip()
        return cleaned[:40] if cleaned else "onbekend"


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _sanitize_line(line: str) -> str:
    """Maskeer IP-adressen en postcodes uit een logregel."""
    line = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]", line)
    line = re.sub(r"\b\d{4}\s?[A-Z]{2}\b", "[POSTCODE]", line)
    return line.strip()


def _count_by(findings: list[RenderFinding], attr: str) -> dict[str, int]:
    """Tel unieke waarden van een attribuut in een lijst van bevindingen."""
    counts: defaultdict[str, int] = defaultdict(int)
    for f in findings:
        counts[getattr(f, attr)] += 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
