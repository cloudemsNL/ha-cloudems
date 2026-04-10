"""
CloudEMS — WhatIfAnalyzer v1.0.0

Berekent scenario-kosten op basis van historische data:
  - Werkelijke kosten (huidige situatie)
  - Zonder batterij (zou duurder stroom hebben ingekocht)
  - Zonder solar (alles van net)
  - Besparing door solar / batterij apart

Werkt op dagelijkse P&L data die coordinator bijhoudt.
Verstuurt wekelijks via NotificationManager.
"""
from __future__ import annotations
import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GAS_KWH_PER_M3 = 9.77
AVG_GRID_CO2   = 300.0  # gCO2/kWh NL gemiddeld


class WhatIfAnalyzer:
    """Berekent wat-als scenario's op basis van coordinator data."""

    def __init__(self, hass: "HomeAssistant", notify_mgr=None) -> None:
        self._hass       = hass
        self._notify_mgr = notify_mgr
        self._daily: list[dict] = []     # rolling 7 dagen
        self._last_report_week: str = ""

    def record_day(self, data: dict) -> None:
        """Registreer dagelijkse energie-data. Aanroepen bij dag-rollover."""
        p1      = data.get("p1_data") or data.get("p1") or {}
        prices  = data.get("price_info") or {}
        arb     = data.get("arbitrage_pnl") or {}

        import_kwh  = float(p1.get("import_kwh_today") or p1.get("electricity_import_t1_kwh", 0) or 0)
        export_kwh  = float(p1.get("export_kwh_today") or p1.get("electricity_export_t1_kwh", 0) or 0)
        solar_kwh   = float(data.get("pv_today_kwh") or 0)
        house_kwh   = float(data.get("house_today_kwh") or 0)
        avg_price   = float(prices.get("avg_today") or 0.25)
        arb_eur     = float(arb.get("day_eur") or 0)
        co2_saved   = float(arb.get("co2_saved_kg") or 0)

        # Werkelijke kosten: import × prijs - export × prijs
        actual_eur = import_kwh * avg_price - export_kwh * avg_price

        # Zonder batterij: batterij-arbitrage terug optellen
        no_bat_eur = actual_eur + arb_eur

        # Zonder solar: alle huisverbruik van net (import + solar_consumed)
        solar_consumed = max(0, solar_kwh - export_kwh)
        no_solar_eur   = (import_kwh + solar_consumed) * avg_price

        entry = {
            "date":          time.strftime("%Y-%m-%d"),
            "actual_eur":    round(actual_eur, 3),
            "no_bat_eur":    round(no_bat_eur, 3),
            "no_solar_eur":  round(no_solar_eur, 3),
            "solar_saving":  round(no_solar_eur - actual_eur, 3),
            "bat_saving":    round(arb_eur, 3),
            "solar_kwh":     round(solar_kwh, 2),
            "import_kwh":    round(import_kwh, 2),
            "export_kwh":    round(export_kwh, 2),
            "co2_saved_kg":  round(co2_saved, 2),
        }
        self._daily.append(entry)
        if len(self._daily) > 30:
            self._daily.pop(0)

    def get_week_summary(self) -> dict:
        """Geeft 7-daagse wat-als samenvatting."""
        recent = self._daily[-7:]
        if not recent:
            return {}

        def _sum(key): return round(sum(d.get(key, 0) for d in recent), 2)

        actual    = _sum("actual_eur")
        no_bat    = _sum("no_bat_eur")
        no_solar  = _sum("no_solar_eur")
        sol_save  = _sum("solar_saving")
        bat_save  = _sum("bat_saving")
        co2_saved = _sum("co2_saved_kg")
        solar_kwh = _sum("solar_kwh")

        return {
            "days":              len(recent),
            "actual_eur":        actual,
            "without_battery_eur": no_bat,
            "without_solar_eur": no_solar,
            "solar_saving_eur":  sol_save,
            "battery_saving_eur": bat_save,
            "total_saving_eur":  round(sol_save + bat_save, 2),
            "solar_kwh":         solar_kwh,
            "co2_saved_kg":      co2_saved,
        }

    async def maybe_send_report(self) -> bool:
        """Stuur rapport elke maandagochtend."""
        now = self._local_now()
        if now.weekday() != 0 or now.hour != 7:
            return False
        week_key = now.strftime("%Y-W%W")
        if self._last_report_week == week_key:
            return False
        self._last_report_week = week_key

        summary = self.get_week_summary()
        if not summary or summary.get("days", 0) < 3:
            return False

        msg = self._build_report(summary)
        if self._notify_mgr:
            await self._notify_mgr.send(
                "💡 Wat als... — CloudEMS weekanalyse",
                msg, category="energy_report",
                notification_id=f"cloudems_whatif_{week_key}",
                force=True,
            )
        return True

    def _build_report(self, s: dict) -> str:
        lines = [f"## Wat als... — afgelopen {s['days']} dagen\n"]
        lines.append(f"**Werkelijke kosten:** €{s['actual_eur']:.2f}")
        lines.append(f"**Zonder batterij:** €{s['without_battery_eur']:.2f} "
                     f"(+€{s['battery_saving_eur']:.2f} duurder)")
        lines.append(f"**Zonder solar:** €{s['without_solar_eur']:.2f} "
                     f"(+€{s['solar_saving_eur']:.2f} duurder)")
        lines.append(f"\n**Totale besparing:** €{s['total_saving_eur']:.2f} 🎉")
        lines.append(f"**CO₂ bespaard:** {s['co2_saved_kg']:.1f} kg")
        lines.append(f"**Zonne-energie:** {s['solar_kwh']:.1f} kWh")
        return "\n".join(lines)

    def _local_now(self):
        from datetime import datetime
        tz_name = getattr(getattr(self._hass, "config", None), "time_zone", None)
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(tz=ZoneInfo(tz_name))
            except Exception:
                pass
        return datetime.now()
