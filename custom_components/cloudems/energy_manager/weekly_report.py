"""
CloudEMS — WeeklyReportGenerator v1.0.0

Genereert een wekelijks energierapport elke maandagochtend (07:00-08:00).
Vergelijkt met de vorige week. Verstuurt via NotificationManager (mobile_app + persistent).

Inhoud:
  - Net import/export (kWh en €)
  - PV-opbrengst + zelfconsumptie %
  - Batterij-cycli en benutting
  - Top-3 apparaten (NILM)
  - CO₂-besparing
  - Vergelijking vorige week (↑↓)

Copyright © 2025 CloudEMS
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SEND_WEEKDAY  = 0     # Maandag
SEND_HOUR     = 7     # 07:00 lokaal


class WeeklyReportGenerator:
    """Genereert en verstuurt een wekelijks energierapport."""

    def __init__(self, hass: "HomeAssistant", notify_mgr=None) -> None:
        self._hass       = hass
        self._notify_mgr = notify_mgr
        self._last_sent_week: str = ""  # "YYYY-WW"
        self._prev_week_snapshot: dict = {}  # snapshot van vorige week voor vergelijking

    # ── Publieke API ──────────────────────────────────────────────────────────

    async def maybe_send(self, data: dict) -> bool:
        """Stuur rapport als het maandag 07:00-08:00 is en nog niet verstuurd."""
        now_local = self._local_now()
        if now_local.weekday() != SEND_WEEKDAY or now_local.hour != SEND_HOUR:
            return False
        week_key = now_local.strftime("%Y-W%W")
        if self._last_sent_week == week_key:
            return False
        await self.send_now(data)
        self._last_sent_week = week_key
        return True

    async def send_now(self, data: dict, label: str = "") -> None:
        """Bouw en stuur het rapport direct."""
        now_local = self._local_now()
        week_label = label or f"week {now_local.strftime('%W')} {now_local.year}"
        report = self._build(data, week_label)
        title  = f"📊 CloudEMS Weekrapport — {week_label}"

        _LOGGER.info("CloudEMS weekrapport verstuurd voor %s", week_label)

        if self._notify_mgr:
            await self._notify_mgr.send(
                title, report,
                category="energy_report",
                notification_id=f"cloudems_weekly_{now_local.strftime('%Y_W%W')}",
                force=True,
            )
        else:
            # Fallback: persistent_notification
            try:
                from homeassistant.components.persistent_notification import async_create
                async_create(self._hass, message=report, title=title,
                             notification_id=f"cloudems_weekly_{now_local.strftime('%Y_W%W')}")
            except Exception as exc:
                _LOGGER.debug("WeeklyReport persistent_notification fout: %s", exc)

        # Sla snapshot op voor volgende week vergelijking
        self._prev_week_snapshot = self._extract_snapshot(data)

    # ── Rapport bouwen ────────────────────────────────────────────────────────

    def _build(self, data: dict, label: str) -> str:
        lines: list[str] = [f"## 📊 Weekrapport — {label}\n"]
        prev  = self._prev_week_snapshot
        has_prev = bool(prev)

        def _delta(cur: float, prv: float, unit: str = "", higher_is_better: bool = True) -> str:
            """Geeft een ↑/↓ indicator terug met verschil."""
            if not has_prev or prv == 0:
                return ""
            diff = cur - prv
            if abs(diff) < 0.01:
                return " (≈ zelfde)"
            arrow = "↑" if diff > 0 else "↓"
            good  = (diff > 0) == higher_is_better
            sign  = "+" if diff > 0 else ""
            return f" {arrow} {sign}{diff:.1f}{unit} {'✅' if good else '⚠️'}"

        # ── Net ────────────────────────────────────────────────────────────────
        p1         = data.get("p1_data") or data.get("p1") or {}
        import_kwh = float(p1.get("import_kwh_week") or p1.get("electricity_import_t1_kwh", 0) or 0)
        export_kwh = float(p1.get("export_kwh_week") or p1.get("electricity_export_t1_kwh", 0) or 0)
        price_avg  = float((data.get("price_info") or {}).get("avg_today", 0.25) or 0.25)
        import_eur = import_kwh * price_avg
        export_eur = export_kwh * price_avg

        if import_kwh or export_kwh:
            lines.append("### ⚡ Net")
            lines.append(f"- Afname: **{import_kwh:.1f} kWh** (≈ €{import_eur:.2f})"
                         + _delta(import_kwh, prev.get("import_kwh", 0), " kWh", higher_is_better=False))
            lines.append(f"- Teruglevering: **{export_kwh:.1f} kWh** (≈ €{export_eur:.2f})"
                         + _delta(export_kwh, prev.get("export_kwh", 0), " kWh", higher_is_better=True))
            net = import_kwh - export_kwh
            lines.append(f"- Netto saldo: **{net:+.1f} kWh**\n")

        # ── Zon ────────────────────────────────────────────────────────────────
        pv_kwh  = float(data.get("pv_week_kwh") or data.get("pv_today_kwh", 0) or 0)
        sc_data = data.get("self_consumption") or {}
        sc_pct  = float(sc_data.get("self_consumption_pct") or 0)
        if pv_kwh:
            lines.append("### ☀️ Zonne-energie")
            lines.append(f"- Opbrengst: **{pv_kwh:.1f} kWh**"
                         + _delta(pv_kwh, prev.get("pv_kwh", 0), " kWh", higher_is_better=True))
            if sc_pct:
                lines.append(f"- Eigen verbruik: **{sc_pct:.0f}%**"
                             + _delta(sc_pct, prev.get("sc_pct", 0), "%", higher_is_better=True))
            lines.append("")

        # ── Batterij ───────────────────────────────────────────────────────────
        bat = data.get("battery_status") or data.get("battery") or {}
        bat_cycles  = float(bat.get("cycles_week") or bat.get("cycles_today", 0) or 0)
        bat_arb_eur = float(data.get("arbitrage_pnl", {}).get("week_eur", 0) or 0)
        if bat_cycles or bat_arb_eur:
            lines.append("### 🔋 Batterij")
            if bat_cycles:
                lines.append(f"- Cycli: **{bat_cycles:.1f}**"
                             + _delta(bat_cycles, prev.get("bat_cycles", 0), "", higher_is_better=True))
            if bat_arb_eur:
                lines.append(f"- Arbitrage-winst: **€{bat_arb_eur:.2f}**"
                             + _delta(bat_arb_eur, prev.get("bat_arb", 0), "€", higher_is_better=True))
            lines.append("")

        # ── Top-3 apparaten (NILM) ─────────────────────────────────────────────
        nilm = data.get("nilm_devices") or []
        with_energy = sorted(
            [d for d in nilm if float(d.get("energy_week_kwh") or d.get("week_kwh") or 0) > 0.01],
            key=lambda d: float(d.get("energy_week_kwh") or d.get("week_kwh") or 0),
            reverse=True,
        )
        if with_energy:
            lines.append("### 🏠 Top-3 verbruikers")
            for i, dev in enumerate(with_energy[:3], 1):
                name  = dev.get("user_name") or dev.get("name", "?")
                kwh   = float(dev.get("energy_week_kwh") or dev.get("week_kwh") or 0)
                sess  = dev.get("session_count_week") or dev.get("on_events") or 0
                sess_str = f" ({sess}×)" if sess else ""
                lines.append(f"{i}. **{name}**: {kwh:.2f} kWh{sess_str}")
            lines.append("")

        # ── CO₂ ───────────────────────────────────────────────────────────────
        co2_saved = float((data.get("co2_data") or {}).get("week_saved_kg")
                          or (data.get("arbitrage_pnl") or {}).get("co2_saved_kg") or 0)
        if co2_saved:
            lines.append("### 🌍 CO₂-besparing")
            lines.append(f"- Bespaard t.o.v. netgemiddelde: **{co2_saved:.1f} kg CO₂**"
                         + _delta(co2_saved, prev.get("co2_saved", 0), " kg", higher_is_better=True))
            lines.append("")

        # ── Gas ────────────────────────────────────────────────────────────────
        gas    = data.get("gas_analysis") or {}
        gas_m3 = float(gas.get("week_m3") or 0)
        if gas_m3:
            lines.append("### 🔥 Gas")
            lines.append(f"- Verbruik: **{gas_m3:.1f} m³**"
                         + _delta(gas_m3, prev.get("gas_m3", 0), " m³", higher_is_better=False))
            lines.append("")

        # ── Samenvatting ───────────────────────────────────────────────────────
        total_save = export_eur + bat_arb_eur
        if total_save > 0:
            lines.append(f"**Totale besparing deze week: ≈ €{total_save:.2f}** 🎉\n")

        lines.append("---")
        lines.append("_CloudEMS weekrapport — instelbaar via Instellingen → Notificaties_")
        return "\n".join(lines)

    def _extract_snapshot(self, data: dict) -> dict:
        """Sla huidige week-waarden op voor vergelijking volgende week."""
        p1 = data.get("p1_data") or data.get("p1") or {}
        sc = data.get("self_consumption") or {}
        bat = data.get("battery_status") or data.get("battery") or {}
        gas = data.get("gas_analysis") or {}
        return {
            "import_kwh":  float(p1.get("import_kwh_week") or 0),
            "export_kwh":  float(p1.get("export_kwh_week") or 0),
            "pv_kwh":      float(data.get("pv_week_kwh") or 0),
            "sc_pct":      float(sc.get("self_consumption_pct") or 0),
            "bat_cycles":  float(bat.get("cycles_week") or 0),
            "bat_arb":     float((data.get("arbitrage_pnl") or {}).get("week_eur") or 0),
            "co2_saved":   float((data.get("co2_data") or {}).get("week_saved_kg") or 0),
            "gas_m3":      float(gas.get("week_m3") or 0),
        }

    def _local_now(self) -> datetime:
        tz_name = getattr(getattr(self._hass, "config", None), "time_zone", None)
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(tz=ZoneInfo(tz_name))
            except Exception:
                pass
        return datetime.now()
