"""
battery_efficiency.py — CloudEMS v4.0.5
=========================================
Bijhoudt het werkelijke rendement van de thuisbatterij.

Meting:
  - Elke cyclus: meet kWh ingeladen en uitgeladen
  - Round-trip efficiency = uitgeladen / ingeladen
  - Afwijking van nominaal (bijv. 92%) → degradatie-signaal

Persistent via HA Store (rolling 90-dagen buffer).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)
STORAGE_KEY_BATTERY_EFF = "cloudems_battery_efficiency_v1"

NOMINAL_EFFICIENCY = 0.92       # 92% round-trip
WARN_THRESHOLD     = 0.80       # waarschuw als < 80%
MIN_CYCLE_KWH      = 0.2        # minimale cyclusmaat om op te slaan


@dataclass
class CycleRecord:
    date:        str
    charged_kwh: float
    discharged_kwh: float
    efficiency:  float
    eur_benefit: float = 0.0    # optioneel: berekend voordeel


@dataclass
class BatteryEfficiencyStatus:
    avg_efficiency_pct:   float   # gemiddeld over 30 dgn
    last_efficiency_pct:  float   # laatste cyclus
    nominal_pct:          float   = NOMINAL_EFFICIENCY * 100
    degradation_pct:      float   = 0.0   # afwijking t.o.v. nominaal
    total_charged_kwh:    float   = 0.0
    total_discharged_kwh: float   = 0.0
    cycle_count:          int     = 0
    warn:                 bool    = False
    cycles_sample:        list    = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "avg_efficiency_pct":   round(self.avg_efficiency_pct, 1),
            "last_efficiency_pct":  round(self.last_efficiency_pct, 1),
            "nominal_pct":          round(self.nominal_pct, 1),
            "degradation_pct":      round(self.degradation_pct, 1),
            "total_charged_kwh":    round(self.total_charged_kwh, 2),
            "total_discharged_kwh": round(self.total_discharged_kwh, 2),
            "cycle_count":          self.cycle_count,
            "warn":                 self.warn,
            "cycles_sample":        self.cycles_sample[-5:],
        }


class BatteryEfficiencyTracker:
    """
    Bijhoudt ingeladen/uitgeladen kWh en berekent real-time efficiency.

    Gebruik in coordinator (elke cyclus):
        tracker.observe(battery_power_w, dt_s=UPDATE_INTERVAL)

    Bij dagwisseling:
        tracker.close_day()
        await tracker.async_save()
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        self._cycles: list[dict] = []
        # Accumulatoren voor lopende dag
        self._charged_today_kwh    = 0.0
        self._discharged_today_kwh = 0.0
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw:
                self._cycles = raw.get("cycles", [])[-90:]
                self._charged_today_kwh    = float(raw.get("charged_today_kwh",    0))
                self._discharged_today_kwh = float(raw.get("discharged_today_kwh", 0))
        except Exception as err:
            _LOGGER.warning("BatteryEfficiencyTracker: laden mislukt: %s", err)
        self._loaded = True

    async def async_save(self) -> None:
        try:
            await self._store.async_save({
                "cycles":               self._cycles[-90:],
                "charged_today_kwh":    self._charged_today_kwh,
                "discharged_today_kwh": self._discharged_today_kwh,
            })
        except Exception as err:
            _LOGGER.warning("BatteryEfficiencyTracker: opslaan mislukt: %s", err)

    def observe(self, battery_power_w: float, dt_s: float) -> None:
        """
        Aanroepen elke update-cyclus.
        battery_power_w > 0 = laden, < 0 = ontladen.
        """
        kwh = abs(battery_power_w) * dt_s / 3600.0 / 1000.0
        if battery_power_w > 10:
            self._charged_today_kwh    += kwh
        elif battery_power_w < -10:
            self._discharged_today_kwh += kwh

    def close_day(self, date_str: str, eur_benefit: float = 0.0) -> Optional[CycleRecord]:
        """
        Sla dagcyclus op. Aanroepen bij DailySummary.
        Geeft CycleRecord terug als de cyclus groot genoeg was.
        """
        c_kwh = self._charged_today_kwh
        d_kwh = self._discharged_today_kwh
        self._charged_today_kwh    = 0.0
        self._discharged_today_kwh = 0.0

        if c_kwh < MIN_CYCLE_KWH or d_kwh < MIN_CYCLE_KWH:
            return None

        eff = round(d_kwh / c_kwh, 4) if c_kwh > 0 else 0.0
        rec = {
            "date":           date_str,
            "charged_kwh":    round(c_kwh, 3),
            "discharged_kwh": round(d_kwh, 3),
            "efficiency":     eff,
            "eur_benefit":    round(eur_benefit, 3),
        }
        self._cycles.append(rec)
        _LOGGER.info(
            "Batterij cyclus %s: %.2f kWh in → %.2f kWh uit (η=%.1f%%)",
            date_str, c_kwh, d_kwh, eff * 100,
        )
        return CycleRecord(**rec)

    def get_status(self, days: int = 30) -> BatteryEfficiencyStatus:
        recent = self._cycles[-days:] if len(self._cycles) > days else self._cycles
        if not recent:
            return BatteryEfficiencyStatus(
                avg_efficiency_pct  = NOMINAL_EFFICIENCY * 100,
                last_efficiency_pct = NOMINAL_EFFICIENCY * 100,
            )
        effs = [r["efficiency"] for r in recent if r.get("efficiency", 0) > 0]
        avg_eff = (sum(effs) / len(effs)) if effs else NOMINAL_EFFICIENCY
        last_eff = recent[-1].get("efficiency", NOMINAL_EFFICIENCY)
        total_c = sum(r.get("charged_kwh", 0) for r in self._cycles)
        total_d = sum(r.get("discharged_kwh", 0) for r in self._cycles)
        degradation = round((NOMINAL_EFFICIENCY - avg_eff) * 100, 1)

        return BatteryEfficiencyStatus(
            avg_efficiency_pct   = round(avg_eff * 100, 1),
            last_efficiency_pct  = round(last_eff * 100, 1),
            degradation_pct      = degradation,
            total_charged_kwh    = round(total_c, 2),
            total_discharged_kwh = round(total_d, 2),
            cycle_count          = len(self._cycles),
            warn                 = avg_eff < WARN_THRESHOLD,
            cycles_sample        = recent[-5:],
        )
