# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Diagnostics.

Implements the Home Assistant diagnostics platform so users can
download a full diagnostic report from Settings → Devices & Services.

Also exposes a `CloudEMSDiagnosticsButton` that writes a human-readable
Markdown report to a persistent notification.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_CLOUD_API_KEY

_LOGGER = logging.getLogger(__name__)

# Keys that must be redacted before sharing
TO_REDACT = {CONF_CLOUD_API_KEY, "password", "token", "api_key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostic data for a config entry (HA built-in download)."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator_data": _sanitise(data),
        "generated_at": datetime.now().isoformat(),
        "version": entry.version,
    }


def build_markdown_report(coordinator_data: dict, config: dict) -> str:
    """Build a human-readable Markdown diagnostics report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        "## 🔍 CloudEMS Diagnoserapport",
        f"*Gegenereerd: {now}*",
        "",
        "### ⚡ Fase-status",
    ]

    phases = coordinator_data.get("phases", {})
    if phases:
        for phase, info in phases.items():
            throttled = "🔴 gelimiteerd" if info.get("throttled") else "🟢 OK"
            lines.append(
                f"- **{phase}**: {info.get('current_a', 0):.1f} A / "
                f"{info.get('max_import_a', '?')} A "
                f"({info.get('utilisation_pct', 0):.0f}%) — {throttled}"
            )
    else:
        lines.append("- *(geen fase-data beschikbaar)*")

    lines += ["", "### 💶 Energieprijs"]
    price_data = coordinator_data.get("energy_price", {})
    if price_data:
        current = price_data.get("current", 0)
        lines += [
            f"- Huidige prijs: **{current:.4f} EUR/kWh**",
            f"- Min vandaag: {price_data.get('min_today', 0):.4f} EUR/kWh",
            f"- Max vandaag: {price_data.get('max_today', 0):.4f} EUR/kWh",
            f"- Negatief: {'ja ⚡' if price_data.get('is_negative') else 'nee'}",
        ]

    lines += ["", "### 🔌 EV & Zonne-energie"]
    ev_current = coordinator_data.get("ev_current", 0)
    solar_curtail = coordinator_data.get("solar_curtailment", 0)
    lines += [
        f"- EV laadstroom: **{ev_current} A**",
        f"- Zonne-energie begrenzing: {solar_curtail:.0f}%",
    ]

    lines += ["", "### 🤖 NILM apparaten"]
    devices = coordinator_data.get("nilm_devices", [])
    if devices:
        for dev in devices:
            state = "AAN" if dev.get("is_on") else "UIT"
            conf = dev.get("confirmed", False)
            lines.append(
                f"- **{dev['name']}** — {state} "
                f"({dev.get('power', 0):.0f}W) "
                f"{'✅' if conf else '⏳'}"
            )
    else:
        lines.append("- *(geen apparaten gedetecteerd)*")

    lines += [
        "",
        "---",
        "*CloudEMS — https://cloudems.eu | "
        "[☕ Support us](https://buymeacoffee.com/cloudems) | "
        "[📖 Docs](https://github.com/cloudemsNL/ha-cloudems)*",
    ]
    return "\n".join(lines)


def _sanitise(data: Any) -> Any:
    """Make coordinator data JSON-serialisable."""
    if isinstance(data, dict):
        return {k: _sanitise(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitise(i) for i in data]
    if isinstance(data, float):
        return round(data, 6)
    return data


async def async_generate_report(hass, entry) -> None:
    """Generate a diagnostic report and post it as a persistent notification."""
    from homeassistant.components import persistent_notification
    coordinator = hass.data.get("cloudems", {}).get(entry.entry_id)
    data = coordinator.data if coordinator else {}
    config = dict(entry.data)
    report = build_markdown_report(data, config)
    persistent_notification.async_create(
        hass,
        message=report,
        title="CloudEMS Diagnose",
        notification_id="cloudems_diagnostics",
    )
