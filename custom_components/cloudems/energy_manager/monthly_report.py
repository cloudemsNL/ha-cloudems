# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Maandrapportage — v1.0.0

Genereert een maandelijks energierapport en stuurt dit via HA notify.

Inhoud van het rapport:
  • Netverbruik, teruglevering, eigen verbruik, PV-opbrengst
  • Kosten vs vorige maand
  • Top-3 apparaten op energieverbruik (NILM)
  • CO₂-uitstoot
  • Trend vs vorige maand (▲/▼ per categorie)

Activering:
  • Automatisch op de 1e van elke maand om 07:00 (via coordinator)
  • Handmatig via service: cloudems.send_monthly_report

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.components.persistent_notification import async_create

_LOGGER = logging.getLogger(__name__)

# Maandnamen NL
MONTHS_NL = [
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


class MonthlyReportGenerator:
    """
    Genereert een tekstueel maandrapport op basis van coordinator-data.

    Gebruik:
        gen = MonthlyReportGenerator(hass, notify_service="notify.mobile_app_x")
        await gen.maybe_send(coordinator_data)   # Stuur alleen op 1e dag van de maand
        await gen.send_now(coordinator_data)     # Stuur altijd (voor service call)
    """

    def __init__(self, hass: HomeAssistant, notify_service: str = "") -> None:
        self._hass = hass
        self._notify_service = notify_service
        self._last_sent_month: str = ""   # "YYYY-MM" — voorkomt dubbel verzenden

    async def maybe_send(self, data: dict) -> bool:
        """Stuur rapport als het de 1e van de maand is (07:00–08:00) en nog niet verstuurd."""
        now = datetime.now(timezone.utc)
        if now.day != 1 or now.hour != 7:
            return False
        month_key = now.strftime("%Y-%m")
        if self._last_sent_month == month_key:
            return False  # Al verstuurd deze maand
        await self.send_now(data, month_override=_prev_month_label(now))
        self._last_sent_month = month_key
        return True

    async def send_now(self, data: dict, month_override: str = "") -> None:
        """Bouw en stuur het rapport direct."""
        now   = datetime.now(timezone.utc)
        label = month_override or _prev_month_label(now)
        report = self._build(data, label)
        _LOGGER.info("CloudEMS maandrapport verstuurd voor %s", label)

        # HA persistent notification (altijd)
        try:
            async_create(
                self._hass,
                message=report,
                title=f"☀️ CloudEMS Maandrapport — {label}",
                notification_id=f"cloudems_monthly_{label.replace(' ', '_')}",
            )
        except Exception as exc:
            _LOGGER.debug("Persistent notification fout: %s", exc)

        # Mobiele push-notificatie (optioneel)
        if self._notify_service:
            try:
                await self._hass.services.async_call(
                    "notify",
                    self._notify_service.removeprefix("notify."),
                    {
                        "title": f"☀️ CloudEMS Maandrapport — {label}",
                        "message": report,
                    },
                    blocking=False,
                )
            except Exception as exc:
                _LOGGER.debug("Push-notificatie fout: %s", exc)

    # ── Bouw de rapporttekst ──────────────────────────────────────────────────

    def _build(self, data: dict, label: str) -> str:
        lines: list[str] = [f"## 📊 Energierapport — {label}\n"]

        # ── Netverbruik & teruglevering ───────────────────────────────────────
        p1 = data.get("p1_data") or data.get("p1") or {}
        import_kwh  = p1.get("import_kwh_month") or p1.get("electricity_import_t1_kwh", 0)
        export_kwh  = p1.get("export_kwh_month")  or p1.get("electricity_export_t1_kwh", 0)
        import_kwh  = float(import_kwh or 0)
        export_kwh  = float(export_kwh or 0)

        if import_kwh or export_kwh:
            lines.append("### ⚡ Net")
            lines.append(f"- Afname: **{import_kwh:.1f} kWh**")
            lines.append(f"- Teruglevering: **{export_kwh:.1f} kWh**")
            net = import_kwh - export_kwh
            lines.append(f"- Saldo: **{net:+.1f} kWh**\n")

        # ── PV ────────────────────────────────────────────────────────────────
        pv_month = data.get("pv_month_kwh") or 0
        sc_data  = data.get("self_consumption") or {}
        sc_pct   = sc_data.get("self_consumption_pct") or 0
        if float(pv_month):
            lines.append("### ☀️ Zonne-energie")
            lines.append(f"- Opbrengst: **{float(pv_month):.1f} kWh**")
            if sc_pct:
                lines.append(f"- Eigen verbruik: **{float(sc_pct):.0f}%**")
            lines.append("")

        # ── Kosten ────────────────────────────────────────────────────────────
        cost_month = data.get("cost_month_eur") or data.get("energy_cost_month") or 0
        if float(cost_month):
            lines.append("### 💶 Kosten")
            lines.append(f"- Geschatte maandkosten: **€ {float(cost_month):.2f}**\n")

        # ── Top-3 apparaten (NILM) ────────────────────────────────────────────
        nilm_devices = data.get("nilm_devices") or []
        # Filter op maand-energie > 0, sorteer aflopend
        with_energy = [
            d for d in nilm_devices
            if float(d.get("energy_month_kwh") or d.get("month_kwh") or 0) > 0.01
        ]
        with_energy.sort(
            key=lambda d: float(d.get("energy_month_kwh") or d.get("month_kwh") or 0),
            reverse=True,
        )
        if with_energy:
            lines.append("### 🏠 Top-3 apparaten")
            for i, dev in enumerate(with_energy[:3], 1):
                name  = dev.get("user_name") or dev.get("name", "?")
                kwh   = float(dev.get("energy_month_kwh") or dev.get("month_kwh") or 0)
                sess  = dev.get("session_count") or dev.get("on_events") or 0
                avg_d = dev.get("avg_duration_min") or 0
                sess_str = f" ({sess}× gem. {avg_d:.0f} min)" if sess and avg_d else (f" ({sess}×)" if sess else "")
                lines.append(f"{i}. **{name}**: {kwh:.2f} kWh{sess_str}")
            lines.append("")

        # ── CO₂ ──────────────────────────────────────────────────────────────
        co2 = data.get("co2_data") or {}
        co2_kg = co2.get("month_kg") or co2.get("co2_month_kg") or 0
        if float(co2_kg):
            lines.append("### 🌍 CO₂")
            lines.append(f"- Uitstoot: **{float(co2_kg):.1f} kg CO₂**\n")

        # ── Gas ───────────────────────────────────────────────────────────────
        gas = data.get("gas_analysis") or {}
        gas_m3 = gas.get("month_m3") or 0
        if float(gas_m3):
            lines.append("### 🔥 Gas")
            lines.append(f"- Verbruik: **{float(gas_m3):.1f} m³**\n")

        # ── Voettekst ─────────────────────────────────────────────────────────
        lines.append("---")
        lines.append("*Automatisch gegenereerd door CloudEMS*")

        return "\n".join(lines)


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _prev_month_label(now: datetime) -> str:
    """Geef de naam van de vorige maand terug, bijv. 'december 2025'."""
    month = now.month - 1 or 12
    year  = now.year if now.month > 1 else now.year - 1
    return f"{MONTHS_NL[month]} {year}"
