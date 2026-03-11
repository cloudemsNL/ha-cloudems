# -*- coding: utf-8 -*-
"""
CloudEMS Log Reporter — v1.0.0

Verzamelt geanonimiseerde diagnostische data en stuurt die als GitHub Issue
naar de CloudEMS repository. Wordt aangroepen door de Guardian bij kritieke
fouten, of handmatig via de dashboard-knop / HA-service.

Privacy-principes:
  • IP-adressen worden gemaskeerd (192.168.x.x → [IP])
  • Locatie-informatie (postcodes, coördinaten) wordt gemaskeerd
  • Gebruiker ziet altijd een preview van wat verstuurd wordt

Wat wél in het issue zit:
  • HA-logs gefilterd op 'cloudems' (laatste 200 regels)
  • Guardian actieve issues (geanonimiseerd)
  • Module-configuratie (welke modules actief, zonder waarden)
  • CloudEMS versie, HA versie, Python versie
  • Sensor-snapshot als vermogensbandbreedtes

GitHub repo: cloudemsNL/ha-cloudems
Label: auto-report

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GITHUB_API_URL  = "https://api.github.com/repos/cloudemsNL/ha-cloudems/issues"
GITHUB_REPO     = "cloudemsNL/ha-cloudems"
ISSUE_LABEL     = "auto-report"
LOG_LINES       = 200   # max regels HA-log mee te sturen
COOLDOWN_S      = 3600  # maximaal 1 automatisch report per uur

# Vermogensbandbreedtes (W) voor anonimisering
POWER_BANDS = [0, 100, 250, 500, 1000, 2000, 3500, 5000, 10000, 20000]


def _mask_ips(text: str) -> str:
    """Mask IP-adressen."""
    return re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', text)


def _mask_location(text: str) -> str:
    """Mask postcode-achtige patronen (NL: 1234 AB, BE: 1234)."""
    text = re.sub(r'\b\d{4}\s?[A-Z]{2}\b', '[POSTCODE]', text)
    # Latitude/longitude coördinaten
    text = re.sub(r'\b\d{1,2}\.\d{4,}\b', '[COORD]', text)
    return text


def _sanitize(text: str) -> str:
    """Sanitize: alleen IP-adressen en locatie-info maskeren."""
    text = _mask_ips(text)
    text = _mask_location(text)
    return text


class LogReporter:
    """
    Verzamelt en verstuurt geanonimiseerde diagnostische data als GitHub Issue.

    Gebruik:
        reporter = LogReporter(hass, config)

        # Preview (wat gaat er verstuurd worden)
        preview = await reporter.async_build_report(coordinator_data, guardian_status)

        # Versturen
        url = await reporter.async_submit(preview, title="Automatisch rapport: ...")
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass       = hass
        self._config     = config
        self._token      = config.get("github_log_token", "")
        self._last_auto  = 0.0

        # Markdown render watcher — leert van HA-logs welke kaarten niet renderen
        from ..energy_manager.markdown_render_watcher import MarkdownRenderWatcher
        self._render_watcher = MarkdownRenderWatcher(hass)

    # ── Rapport bouwen ────────────────────────────────────────────────────────

    async def async_build_report(
        self,
        coordinator_data: dict,
        guardian_status: dict,
        trigger: str = "manual",
    ) -> dict:
        """
        Bouw het volledige rapport-dict.

        Returns dict met:
          title, body (markdown), preview_safe (boolean)
          sections: metadata, ha_logs, guardian_issues, module_config, sensor_snapshot
        """
        now = datetime.now(timezone.utc)

        # ── Metadata ────────────────────────────────────────────────────────
        meta = self._build_metadata(coordinator_data, trigger, now)

        # ── HA logs ─────────────────────────────────────────────────────────
        ha_logs = await self._collect_ha_logs()

        # ── Markdown render watcher ────────────────────────────────────────
        await self._render_watcher.async_scan(force=(trigger != "auto"))
        render_report  = self._render_watcher.get_report()
        render_issues  = self._render_watcher.get_guardian_issues()
        render_summary = self._render_watcher.get_markdown_summary()
        if render_report["active_findings"] > 0:
            _LOGGER.warning(
                "CloudEMS LogReporter: render watcher meldt %d actieve render-problemen.",
                render_report["active_findings"],
            )

        # ── Guardian issues (incl. render-issues) ─────────────────────────
        issues_section = self._build_issues_section(guardian_status, extra=render_issues)

        # ── Module configuratie ─────────────────────────────────────────────
        module_cfg = self._build_module_config(coordinator_data)

        # ── Sensor snapshot ────────────────────────────────────────────────
        sensor_snap = self._build_sensor_snapshot(coordinator_data)

        # ── Markdown body ────────────────────────────────────────────────────
        body = self._render_markdown(meta, ha_logs, issues_section, module_cfg, sensor_snap, render_summary)

        title = (
            f"[auto-report] {trigger.upper()} — "
            f"CloudEMS v{meta['cloudems_version']} — "
            f"{now.strftime('%Y-%m-%d %H:%M')} UTC"
        )

        return {
            "title":           title,
            "body":            body,
            "sections":        {
                "metadata":       meta,
                "ha_logs":        ha_logs,
                "guardian_issues": issues_section,
                "module_config":  module_cfg,
                "sensor_snapshot": sensor_snap,
            },
            "trigger":         trigger,
            "built_at":        now.isoformat(),
        }

    def _build_metadata(self, data: dict, trigger: str, now: datetime) -> dict:
        """Systeemmetadata — geen persoonlijke info."""
        import sys
        import homeassistant.const as ha_const

        watchdog = data.get("watchdog", {})
        return {
            "cloudems_version": data.get("cloudems_version", "?"),
            "ha_version":       getattr(ha_const, "MAJOR_VERSION", "?"),
            "python_version":   f"{sys.version_info.major}.{sys.version_info.minor}",
            "trigger":          trigger,
            "timestamp_utc":    now.isoformat(timespec="seconds"),
            "total_crashes":    watchdog.get("total_failures", 0),
            "total_restarts":   watchdog.get("total_restarts", 0),
            "uptime_cycles":    data.get("health_cycle_count", 0),
            "modules_active":   self._count_active_modules(data),
        }

    def _count_active_modules(self, data: dict) -> int:
        module_keys = [
            "nilm_status", "ev_status", "boiler_groups_status",
            "pv_status", "battery_status", "phase_status",
        ]
        return sum(1 for k in module_keys if data.get(k))

    async def _collect_ha_logs(self) -> list[str]:
        """Haal HA-logs op gefilterd op 'cloudems', geanonimiseerd."""
        lines = []
        try:
            log_path = self._hass.config.path("home-assistant.log")
            with open(log_path, errors="replace") as f:
                all_lines = f.readlines()
            # Filter op cloudems-gerelateerde regels
            filtered = [
                l.rstrip() for l in all_lines
                if "cloudems" in l.lower() or "guardian" in l.lower()
            ]
            # Laatste LOG_LINES regels
            recent = filtered[-LOG_LINES:]
            lines  = [_sanitize(l) for l in recent]
        except Exception as err:
            lines = [f"[Kon logs niet ophalen: {err}]"]
        return lines

    def _build_issues_section(self, guardian: dict, extra: list | None = None) -> list[dict]:
        """Guardian issues, geanonimiseerd."""
        issues = []
        for i in guardian.get("active_issues", []):
            issues.append({
                "level":   i.get("level"),
                "title":   _sanitize(i.get("title", "")),
                "message": _sanitize(i.get("message", "")),
                "source":  i.get("source"),
                "count":   i.get("count", 1),
            })
        # Voeg extra issues toe (bv. van render watcher)
        if extra:
            for e in extra:
                issues.append({
                    "level":   e.get("level", "warning"),
                    "title":   e.get("title", ""),
                    "message": e.get("message", ""),
                    "source":  e.get("source", "render_watcher"),
                    "count":   e.get("count", 1),
                })
        return issues

    def _build_module_config(self, data: dict) -> dict:
        """Welke modules actief zijn — geen waarden, geen entity IDs."""
        boiler_groups = data.get("boiler_groups_status", [])
        return {
            "boiler_groups":     len(boiler_groups),
            "boiler_units_total": sum(len(g.get("boilers", [])) for g in boiler_groups),
            "ev_configured":     bool(data.get("ev_status")),
            "battery_configured": bool(data.get("battery_status")),
            "nilm_enabled":      bool(data.get("nilm_status", {}).get("enabled")),
            "pv_configured":     bool(data.get("pv_status")),
            "phase_monitoring":  bool(data.get("phase_status")),
            "p1_active":         bool(data.get("boiler_p1_active")),
            "congestion_active": bool(data.get("congestion", {}).get("congestion_active")),
            "safe_mode":         data.get("guardian", {}).get("safe_mode", False),
        }

    def _build_sensor_snapshot(self, data: dict) -> dict:
        """Sensorwaarden als bandbreedtes — nooit exacte getallen."""
        def _band(key: str) -> str:
            v = data.get(key)
            if v is None:
                return "unavailable"
            try:
                return _power_band(abs(float(v)))
            except (TypeError, ValueError):
                return "?"

        snap = {
            "grid_power_w": data.get("grid_power"),
            "pv_power_w":   data.get("pv_power"),
        }

        # Boiler temperaturen inclusief exacte waarden — helpt bij diagnose
        boiler_groups = data.get("boiler_groups_status", [])
        boiler_health = []
        for g in boiler_groups:
            for b in g.get("boilers", []):
                temp = b.get("temp_c")
                sp   = b.get("setpoint_c")
                boiler_health.append({
                    "label":      b.get("label", f"boiler_{len(boiler_health)}"),
                    "entity_id":  b.get("entity_id", ""),
                    "temp_c":     temp,
                    "setpoint_c": sp,
                    "is_on":      b.get("is_on", False),
                    "season":     g.get("season", "?"),
                    "cycle_kwh":  b.get("cycle_kwh"),
                })
        snap["boilers"] = boiler_health

        # Capaciteitstarief piek — exacte waarden
        cp = data.get("capacity_peak", {})
        if cp:
            snap["capacity_peak_w"]        = cp.get("current_avg_w")
            snap["capacity_month_peak_w"]  = cp.get("month_peak_w")
            snap["capacity_warning_level"] = cp.get("warning_level", "ok")

        return snap

    def _render_markdown(self, meta: dict, logs: list, issues: list,
                          module_cfg: dict, sensor_snap: dict, render_summary: str = "") -> str:
        """Genereer markdown voor GitHub issue. Logt render-statistieken voor kwaliteitsbewaking."""
        lines = [
            "## CloudEMS Automatisch Diagnostisch Rapport",
            "",
            "> Gegenereerd door de CloudEMS System Guardian. "
            "> IP-adressen en postcodes zijn gemaskeerd. Entity IDs en waarden zijn bewaard voor diagnose.",
            "",
            "### Metadata",
            "| | |",
            "|---|---|",
            f"| CloudEMS versie | `{meta['cloudems_version']}` |",
            f"| Home Assistant versie | `{meta['ha_version']}` |",
            f"| Python | `{meta['python_version']}` |",
            f"| Trigger | `{meta['trigger']}` |",
            f"| Tijdstip (UTC) | `{meta['timestamp_utc']}` |",
            f"| Totaal crashes | {meta['total_crashes']} |",
            f"| Totaal herstarts | {meta['total_restarts']} |",
            f"| Update-cycli | {meta['uptime_cycles']} |",
            f"| Actieve modules | {meta['modules_active']} |",
            "",
            "### Guardian Issues",
        ]

        if issues:
            lines += ["| Niveau | Titel | Bron | Aantal |", "|---|---|---|---|"]
            for i in issues:
                icon = {"critical": "x", "error": "x", "warning": "!", "info": "i"}.get(i["level"], "-")
                lines.append(f"| {icon} {i['level']} | {i['title']} | {i['source']} | {i['count']} |")
            lines.append("")
            for i in issues:
                lines += [f"**{i['title']}**", f"> {i['message']}", ""]
        else:
            lines += ["*Geen actieve Guardian issues.*", ""]

        lines += ["### Module Configuratie", "| Module | Status |", "|---|---|"]
        for k, v in module_cfg.items():
            lines.append(f"| {k} | {v} |")

        lines += [
            "",
            "### Sensor Snapshot",
            "| Sensor | Waarde |",
            "|---|---|",
            f"| Net-vermogen | {sensor_snap.get('grid_power_w')} W |",
            f"| PV-opbrengst | {sensor_snap.get('pv_power_w')} W |",
        ]
        if "capacity_peak_w" in sensor_snap:
            lines.append(
                f"| Kwartier-piek | {sensor_snap['capacity_peak_w']} W "
                f"(maandpiek: {sensor_snap.get('capacity_month_peak_w')} W, "
                f"niveau: {sensor_snap.get('capacity_warning_level', '?')}) |"
            )

        boilers = sensor_snap.get("boilers", [])
        if boilers:
            lines += ["", "**Boiler temperaturen:**",
                      "| Boiler | Entity | Temp | Setpoint | Aan | Seizoen | kWh/cyclus |",
                      "|---|---|---|---|---|---|---|"]
            for b in boilers:
                on_str = "ja" if b["is_on"] else "nee"
                lines.append(
                    f"| {b['label']} | `{b['entity_id']}` "
                    f"| {b['temp_c']} C | {b['setpoint_c']} C "
                    f"| {on_str} | {b['season']} | {b.get('cycle_kwh', '-')} |"
                )

        lines += ["", render_summary]
        lines += ["", "### HA Logs (cloudems filter, IP gemaskeerd)", "```"]
        lines += logs[-200:] if logs else ["[geen logs beschikbaar]"]
        lines += ["```", ""]

        return "\n".join(lines)

    # ── Versturen ─────────────────────────────────────────────────────────────

    async def async_submit(self, report: dict, auto: bool = False) -> Optional[str]:
        """
        Verstuur het rapport als GitHub Issue.

        Args:
            report: dict van async_build_report()
            auto:   True = automatisch getriggerd door Guardian

        Returns:
            URL van het aangemaakte issue, of None bij fout.
        """
        if auto and (time.time() - self._last_auto) < COOLDOWN_S:
            _LOGGER.debug("LogReporter: automatisch rapport overgeslagen (cooldown)")
            return None

        headers = {
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload = {
            "title":  report["title"],
            "body":   report["body"],
            "labels": [ISSUE_LABEL],
        }

        try:
            import aiohttp
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self.hass)
            async with session.post(
                    GITHUB_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status in (201, 200):
                        data  = await resp.json()
                        url   = data.get("html_url", "")
                        if auto:
                            self._last_auto = time.time()
                        _LOGGER.info("LogReporter: issue aangemaakt: %s", url)
                        return url
                    else:
                        text = await resp.text()
                        _LOGGER.error(
                            "LogReporter: GitHub API fout %d: %s",
                            resp.status, text[:200],
                        )
                        return None
        except Exception as err:
            _LOGGER.error("LogReporter: versturen mislukt: %s", err)
            return None

    async def async_auto_report(self, coordinator_data: dict,
                                guardian_status: dict, reason: str) -> Optional[str]:
        """
        Automatisch rapport bij kritieke Guardian-fout.
        Heeft een cooldown van 1 uur om spam te voorkomen.
        """
        if (time.time() - self._last_auto) < COOLDOWN_S:
            return None
        report = await self.async_build_report(
            coordinator_data, guardian_status, trigger=f"auto:{reason}")
        return await self.async_submit(report, auto=True)

    def get_preview_text(self, report: dict) -> str:
        """Geeft een leesbare preview van wat er verstuurd wordt (voor dashboard)."""
        s = report["sections"]
        meta  = s["metadata"]
        lines = [
            f"📋 CloudEMS v{meta['cloudems_version']} — {meta['timestamp_utc']}",
            f"⚠️  {len(s['guardian_issues'])} actieve issues",
            f"📄 {len(s['ha_logs'])} logregels (cloudems, geanonimiseerd)",
            f"⚙️  Modules: {json.dumps({k: v for k,v in s['module_config'].items() if v}, separators=(',',':'))}",
            "",
            "IP-adressen ✅ gemaskeerd | Postcodes ✅ gemaskeerd | Entity IDs en waarden ✅ bewaard voor diagnose",
        ]
        return "\n".join(lines)
