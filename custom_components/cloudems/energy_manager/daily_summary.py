# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Dagelijkse Energiesamenvatting — v1.0.0

Stuurt elke ochtend om 07:30 een compacte samenvatting van gisteren:
  • Verbruik (kWh), opwek (kWh), netto import/export
  • Kosten en eventuele besparing
  • Top-3 NILM-apparaten op verbruik
  • Goedkoopste uur van gisteren

Verstuurt via persistent_notification en optioneel via notify.*-service.

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

SEND_HOUR   = 7
SEND_MINUTE = 30


class DailySummaryGenerator:
    """Genereert en verstuurt een dagelijkse energiesamenvatting."""

    STORAGE_KEY = "cloudems_daily_summary_yesterday"
    STORAGE_VERSION = 1

    def __init__(self, hass: HomeAssistant, notify_service: str = "") -> None:
        self._hass            = hass
        self._notify_service  = notify_service
        self._last_sent_date  = ""  # "YYYY-MM-DD" van de laatste verstuurde samenvatting
        # Accumulatoren voor gisteren — gevuld door _update_yesterday_accumulators()
        self._yesterday: dict = {}
        self._store = Store(hass, self.STORAGE_VERSION, self.STORAGE_KEY)

    async def async_load(self) -> None:
        """Laad persistente gisteren-data bij opstarten."""
        try:
            stored = await self._store.async_load()
            if stored and isinstance(stored, dict):
                self._yesterday = stored
                _LOGGER.debug("DailySummary: gisteren-data geladen uit store")
        except Exception as err:
            _LOGGER.debug("DailySummary: laden mislukt: %s", err)

    # ── Publieke API ──────────────────────────────────────────────────────────

    async def maybe_send(self, data: dict) -> None:
        """Stuur samenvatting als het 07:30 is op een nieuwe dag."""
        now  = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        if today_str == self._last_sent_date:
            return  # al verstuurd vandaag
        if now.hour != SEND_HOUR or now.minute < SEND_MINUTE:
            return  # nog niet 07:30

        await self.send_now(data)
        self._last_sent_date = today_str

    async def send_now(self, data: dict, date_override: str = "") -> None:
        """Stuur samenvatting direct (ook handmatig aanroepbaar)."""
        try:
            # v5.5.75: sla gisteren-snapshot op voor dagrapport-kaart
            p1  = (data.get("p1_data") or {})
            sc  = (data.get("self_consumption") or {})
            nilm = sorted(
                [d for d in (data.get("nilm_devices") or [])
                 if float((d.get("energy") or {}).get("today_kwh") or
                          d.get("energy_today_kwh") or 0) > 0.01],
                key=lambda d: float((d.get("energy") or {}).get("today_kwh")
                              or d.get("energy_today_kwh") or 0), reverse=True
            )[:5]
            # Sla ook battery_schedule op voor gisteren-tab in batterijplan kaart
            _bs = data.get("battery_schedule") or {}
            self._yesterday = {
                "date":            date_override or _yesterday_label(),
                "battery_schedule": _bs.get("schedule", []),
                "pv_kwh":          round(float(data.get("pv_forecast_today_kwh") or 0), 1),
                "import_kwh":      round(float(p1.get("electricity_import_today_kwh") or 0), 1),
                "export_kwh":      round(float(p1.get("electricity_export_today_kwh") or 0), 1),
                "self_cons_pct":   round(float(data.get("self_consumption_pct") or
                                              sc.get("self_consumption_pct") or 0), 1),
                "cost_eur":        round(float(data.get("cost_today_eur") or 0), 2),
                "cost_month_eur":  round(float(data.get("cost_month_eur") or 0), 2),
                "top_devices":     [
                    {"name": d.get("name", d.get("label", "?")),
                     "kwh":  round(float((d.get("energy") or {}).get("today_kwh")
                                   or d.get("energy_today_kwh") or 0), 2)}
                    for d in nilm
                ],
            }
            msg = self._build_message(data, date_override=date_override)
            title = f"☀️ CloudEMS dagrapport {date_override or _yesterday_label()}"

            self._hass.components.persistent_notification.async_create(
                message        = msg,
                title          = title,
                notification_id= "cloudems_daily_summary",
            )

            if self._notify_service:
                svc_domain, svc_name = self._notify_service.split(".", 1)
                await self._hass.services.async_call(
                    svc_domain, svc_name,
                    {"title": title, "message": msg},
                    blocking=False,
                )
            # Persisteer gisteren-data zodat het een herstart overleeft
            try:
                await self._store.async_save(self._yesterday)
            except Exception as _se:
                _LOGGER.debug("DailySummary: opslaan mislukt: %s", _se)
            _LOGGER.info("CloudEMS dagelijkse samenvatting verstuurd")
        except Exception as err:
            _LOGGER.debug("DailySummary send fout: %s", err)

    # ── Privé helpers ─────────────────────────────────────────────────────────

    def get_yesterday(self) -> dict:
        """Geef gisteren-snapshot terug voor dagrapport-kaart."""
        return self._yesterday

    def _build_message(self, data: dict, date_override: str = "") -> str:
        label = date_override or _yesterday_label()

        # Energiedata
        solar_kwh   = round(float(data.get("pv_forecast_today_kwh") or 0), 1)
        cost_today  = round(float(data.get("cost_today_eur") or 0), 2)
        cost_month  = round(float(data.get("cost_month_eur") or 0), 2)

        # P1 data
        p1 = data.get("p1_data") or {}
        import_kwh  = round(float(p1.get("electricity_import_today_kwh") or 0), 1)
        export_kwh  = round(float(p1.get("electricity_export_today_kwh") or 0), 1)
        gas_m3      = round(float(p1.get("gas_m3_today") or (data.get("gas_data") or {}).get("gas_m3") or 0), 2)

        # NILM top-3 verbruikers
        nilm = data.get("nilm_devices") or []
        top3 = sorted(
            [d for d in nilm if float((d.get("energy") or {}).get("today_kwh") or d.get("energy_today_kwh") or 0) > 0.01],
            key=lambda d: float((d.get("energy") or {}).get("today_kwh") or d.get("energy_today_kwh") or 0),
            reverse=True,
        )[:3]

        # Goedkoopste uur gisteren
        ep = data.get("energy_price") or {}
        cheapest_h = ep.get("cheapest_hour") or ep.get("cheapest_1h")

        # Bouw bericht
        lines = [
            f"**Energiesamenvatting {label}**\n",
            f"⚡ Verbruik: **{import_kwh} kWh** import  |  ☀️ Opwek: **{solar_kwh} kWh**",
        ]
        if export_kwh > 0:
            lines.append(f"↩️ Teruglevering: **{export_kwh} kWh**")
        if gas_m3 > 0:
            lines.append(f"🔥 Gas: **{gas_m3} m³**")

        lines.append(f"\n💰 Kosten gisteren: **€{cost_today:.2f}**  |  Deze maand tot nu: **€{cost_month:.2f}**")

        if top3:
            lines.append("\n🏠 **Top verbruikers gisteren:**")
            for dev in top3:
                name = dev.get("user_name") or dev.get("name") or dev.get("device_type", "Apparaat")
                kwh  = float((dev.get("energy") or {}).get("today_kwh") or dev.get("energy_today_kwh") or 0)
                lines.append(f"  • {name}: {kwh:.2f} kWh")

        if cheapest_h is not None:
            lines.append(f"\n⏱️ Goedkoopste uur vandaag: **{cheapest_h:02d}:00**")

        # Samenvatting advies
        behaviour = data.get("behaviour_coach") or {}
        total_saving = behaviour.get("total_saving_eur_month") or 0
        if total_saving >= 1.0:
            best = behaviour.get("best_device") or ""
            lines.append(
                f"\n💡 Verschuivingstip: **€{total_saving:.2f}/maand** bespaarbaar"
                + (f" — begin bij {best}" if best else "")
            )

        return "\n".join(lines)


def _yesterday_label() -> str:
    """Geef gisteren als leesbare string."""
    y = datetime.now(timezone.utc) - timedelta(days=1)
    return y.strftime("%-d %B %Y")
