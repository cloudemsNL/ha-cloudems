"""
export_limit_monitor.py — CloudEMS v4.0.1
==========================================
v2.0 — volledig herbouwd met persistente dagtracking.

Nederlandse salderingsafbouw (definitieve wetgeving):
  2025: 64%   2026: 36%   2027: 0%
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_EXPORT_HISTORY = "cloudems_export_daily_history_v1"

_SALDERING_PCT: dict[int, float] = {
    2024: 100.0,
    2025:  64.0,
    2026:  36.0,
    2027:   0.0,
}

ALERT_THRESHOLD_EUR    = 50.0
DEFAULT_IMPORT_TARIFF  = 0.28
DEFAULT_RETURN_RATIO   = 0.30
DEFAULT_HISTORY_DAYS   = 30


# ── ExportDailyTracker ────────────────────────────────────────────────────────

class ExportDailyTracker:
    """Persistente rolling 30-dagen buffer voor dagelijkse export-kWh."""

    def __init__(self, store: "Store") -> None:
        self._store = store
        self._data: dict[str, float] = {}
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw and isinstance(raw.get("days"), dict):
                self._data = {k: float(v) for k, v in raw["days"].items()}
                _LOGGER.debug("ExportDailyTracker: %d dag(en) geladen", len(self._data))
        except Exception as err:
            _LOGGER.warning("ExportDailyTracker: laden mislukt: %s", err)
        self._loaded = True

    async def record_day(self, date_str: str, kwh: float) -> None:
        """Registreer dag-export. Sla op en verwijder data > 60 dagen."""
        if not self._loaded:
            await self.async_load()
        self._data[date_str] = max(0.0, round(float(kwh), 3))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).date()
        self._data = {k: v for k, v in self._data.items()
                      if date.fromisoformat(k) >= cutoff}
        await self._save()
        _LOGGER.debug("ExportDailyTracker: %s → %.3f kWh (%d dagen)",
                      date_str, self._data[date_str], len(self._data))

    def record_today_realtime(self, kwh_today: float) -> None:
        """Update vandaag in memory (geen Store-schrijfactie)."""
        self._data[date.today().isoformat()] = max(0.0, float(kwh_today))

    async def _save(self) -> None:
        try:
            await self._store.async_save({"days": self._data})
        except Exception as err:
            _LOGGER.warning("ExportDailyTracker: opslaan mislukt: %s", err)

    def _recent(self, days: int) -> list[float]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        return [v for k, v in self._data.items()
                if date.fromisoformat(k) >= cutoff]

    def avg_daily_kwh(self, days: int = DEFAULT_HISTORY_DAYS) -> float:
        vals = self._recent(days)
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    def peak_daily_kwh(self, days: int = DEFAULT_HISTORY_DAYS) -> float:
        return round(max(self._recent(days), default=0.0), 3)

    def days_of_data(self, days: int = DEFAULT_HISTORY_DAYS) -> int:
        return len(self._recent(days))

    def total_export_kwh(self, days: int = DEFAULT_HISTORY_DAYS) -> float:
        return round(sum(self._recent(days)), 3)

    def get_monthly_avg(self) -> dict:
        """Gemiddelde dagexport per maandnummer (1-12) voor seizoenspatroon."""
        from datetime import date as _date
        monthly: dict = {}
        for k, v in self._data.items():
            try:
                m = _date.fromisoformat(k).month
                monthly.setdefault(m, []).append(v)
            except ValueError:
                continue
        return {m: round(sum(vals)/len(vals), 3) for m, vals in monthly.items()}

    def get_season_factor(self) -> float:
        """Factor huidig seizoen vs. jaargemiddelde (>1=zomer, <1=winter)."""
        from datetime import date as _date
        monthly = self.get_monthly_avg()
        if len(monthly) < 3:
            return 1.0
        overall = sum(monthly.values()) / len(monthly)
        if overall <= 0:
            return 1.0
        cur = monthly.get(_date.today().month, overall)
        return round(cur / overall, 3)

    def extrapolate_annual_kwh(self) -> float:
        """Seizoensgecorrigeerde jaarschatting."""
        avg = self.avg_daily_kwh()
        if avg <= 0:
            return 0.0
        factor = self.get_season_factor()
        corrected = avg / factor if factor > 0 else avg
        return round(corrected * 365, 1)



# ── ExportLimitStatus ─────────────────────────────────────────────────────────

@dataclass
class ExportLimitStatus:
    year:                  int
    return_pct_this_year:  float
    return_pct_next_year:  float
    avg_daily_export_kwh:  float
    annual_export_kwh:     float
    unsaldered_kwh:        float
    unsaldered_eur:        float
    recommend_battery_kwh: float
    battery_roi_years:     float
    days_of_data:          int
    peak_daily_kwh:        float
    advice:                str
    alert:                 bool


# ── ExportLimitMonitor ────────────────────────────────────────────────────────

class ExportLimitMonitor:
    """Berekent salderingsverlies en geeft batterij-advies."""

    @staticmethod
    def get_saldering_pct(year: int) -> float:
        if year >= 2027:
            return 0.0
        return _SALDERING_PCT.get(year, 100.0)

    def calculate(
        self,
        tracker: ExportDailyTracker,
        import_tariff:     float = DEFAULT_IMPORT_TARIFF,
        return_tariff:     Optional[float] = None,
        history_days:      int = DEFAULT_HISTORY_DAYS,
        fallback_export_w: float = 0.0,
    ) -> ExportLimitStatus:
        today     = date.today()
        this_year = today.year
        next_year = this_year + 1

        pct_now  = self.get_saldering_pct(this_year) / 100.0
        pct_next = self.get_saldering_pct(next_year) / 100.0

        days_tracked = tracker.days_of_data(history_days)
        avg_daily    = tracker.avg_daily_kwh(history_days)
        peak_daily   = tracker.peak_daily_kwh(history_days)

        # Fallback als < 2 dagen data
        if days_tracked < 2 and fallback_export_w > 0:
            avg_daily  = round((fallback_export_w / 1000.0) * 6 * 0.5, 3)
            peak_daily = round(avg_daily * 1.5, 3)
            _LOGGER.debug("ExportLimitMonitor: fallback %.0fW → %.2f kWh/dag",
                          fallback_export_w, avg_daily)

        if days_tracked >= 14:
            annual_export_kwh = tracker.extrapolate_annual_kwh()
            if annual_export_kwh <= 0:
                annual_export_kwh = round(avg_daily * 365.0, 1)
        else:
            annual_export_kwh = round(avg_daily * 365.0, 1)
        unsaldered_kwh    = round(annual_export_kwh * (1.0 - pct_now), 1)

        ret_tariff     = return_tariff if return_tariff else import_tariff * DEFAULT_RETURN_RATIO
        loss_per_kwh   = import_tariff - ret_tariff
        unsaldered_eur = round(unsaldered_kwh * loss_per_kwh, 2)

        # Batterij-aanbeveling: 80% van piekdag, max 15 kWh
        recommend_battery_kwh = round(min(peak_daily * 0.8, 15.0), 1) if peak_daily > 0 else 0.0
        if unsaldered_eur > 0 and recommend_battery_kwh > 0:
            battery_cost  = recommend_battery_kwh * 900
            annual_saving = min(unsaldered_eur,
                                recommend_battery_kwh * 365 * loss_per_kwh)
            battery_roi_years = round(battery_cost / annual_saving, 1) if annual_saving > 0 else 99.0
        else:
            battery_roi_years = 99.0
        battery_roi_years = min(battery_roi_years, 99.0)

        alert = unsaldered_eur > ALERT_THRESHOLD_EUR
        conf  = (f" ({days_tracked} dagen gemeten)"
                 if days_tracked >= 2 else " (schatting)")

        if pct_now >= 1.0:
            advice = (
                f"Volledige saldering in {this_year}. "
                f"~{annual_export_kwh:.0f} kWh/jaar teruglevering{conf}. "
                f"In {next_year}: {pct_next*100:.0f}%."
            )
        elif pct_now == 0.0:
            advice = (
                f"Saldering afgeschaft. {annual_export_kwh:.0f} kWh/jaar levert "
                f"€{ret_tariff:.2f}/kWh op. Aanbevolen batterij: "
                f"{recommend_battery_kwh:.0f} kWh (~{battery_roi_years:.0f} jr ROI){conf}."
            )
        elif alert:
            advice = (
                f"{(1-pct_now)*100:.0f}% niet gesaldeerd in {this_year} → "
                f"~{unsaldered_kwh:.0f} kWh = ~€{unsaldered_eur:.0f}/jaar verlies{conf}. "
                f"Batterij {recommend_battery_kwh:.0f} kWh → ROI ~{battery_roi_years:.0f} jaar."
            )
        else:
            advice = (
                f"Saldering {this_year}: {pct_now*100:.0f}%. "
                f"Verlies €{unsaldered_eur:.0f}/jaar — binnen grens{conf}."
            )

        return ExportLimitStatus(
            year                  = this_year,
            return_pct_this_year  = round(pct_now * 100.0, 1),
            return_pct_next_year  = round(pct_next * 100.0, 1),
            avg_daily_export_kwh  = avg_daily,
            annual_export_kwh     = annual_export_kwh,
            unsaldered_kwh        = unsaldered_kwh,
            unsaldered_eur        = unsaldered_eur,
            recommend_battery_kwh = recommend_battery_kwh,
            battery_roi_years     = battery_roi_years,
            days_of_data          = days_tracked,
            peak_daily_kwh        = peak_daily,
            advice                = advice,
            alert                 = alert,
        )

    def to_sensor_dict(self, status: ExportLimitStatus) -> dict:
        return {
            "year":                   status.year,
            "return_pct_this_year":   status.return_pct_this_year,
            "return_pct_next_year":   status.return_pct_next_year,
            "avg_daily_export_kwh":   status.avg_daily_export_kwh,
            "annual_export_kwh":      status.annual_export_kwh,
            "unsaldered_kwh":         status.unsaldered_kwh,
            "unsaldered_eur":         status.unsaldered_eur,
            "recommend_battery_kwh":  status.recommend_battery_kwh,
            "battery_roi_years":      status.battery_roi_years,
            "days_of_data":           status.days_of_data,
            "peak_daily_kwh":         status.peak_daily_kwh,
            "advice":                 status.advice,
            "alert":                  status.alert,
        }
