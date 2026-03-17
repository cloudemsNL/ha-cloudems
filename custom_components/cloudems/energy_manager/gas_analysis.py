# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.
"""
CloudEMS Gas Analyse

Per dag: m³ verbruik + prijs opslaan.
Periode verbruik = som dagrecords + lopende dag.
Periode kosten   = som (verbruik × prijs per dag).
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY      = "cloudems_gas_analysis_v1"
STORAGE_VERSION  = 1
HDD_SETPOINT_C   = 18.0
GAS_PRICE_DEFAULT = 1.25
SAVE_INTERVAL_S  = 60

NL_MONTHLY_HDD = {
    1: 310, 2: 265, 3: 195, 4: 90,  5: 30,  6: 5,
    7: 0,   8: 0,   9: 20,  10: 95, 11: 185, 12: 275,
}
BENCH_EXCELLENT = 0.06
BENCH_GOOD      = 0.09
BENCH_AVERAGE   = 0.13


@dataclass
class GasDayRecord:
    date:         str    # YYYY-MM-DD
    gas_m3_delta: float  # verbruik die dag in m³
    price_eur_m3: float  # gasprijs die dag €/m³
    hdd:          float  # graaddagen (voor efficiëntie analyse)
    outside_temp: float  # gemiddelde buitentemperatuur

    @property
    def cost_eur(self) -> float:
        return round(self.gas_m3_delta * self.price_eur_m3, 4)

    def to_dict(self) -> dict:
        return {
            "date":         self.date,
            "gas_m3_delta": round(self.gas_m3_delta, 3),
            "price_eur_m3": round(self.price_eur_m3, 4),
            "hdd":          round(self.hdd, 2),
            "outside_temp": round(self.outside_temp, 1),
        }


@dataclass
class GasAnalysisData:
    gas_m3_today:         float
    gas_m3_week:          float
    gas_m3_month:         float
    gas_m3_year:          float
    gas_cost_today_eur:   float
    gas_cost_week_eur:    float
    gas_cost_month_eur:   float
    gas_cost_year_eur:    float
    efficiency_m3_hdd:    float
    efficiency_rating:    str
    hdd_today:            float
    hdd_month:            float
    seasonal_forecast_m3: float
    seasonal_forecast_eur:float
    anomaly:              bool
    anomaly_message:      str
    advice:               str
    records_count:        int
    isolation_advice:     str = ""
    isolation_saving_pct: float = 0.0


def _rating(m3_per_hdd: float) -> str:
    if m3_per_hdd <= 0:              return "onbekend"
    if m3_per_hdd < BENCH_EXCELLENT: return "uitstekend"
    if m3_per_hdd < BENCH_GOOD:      return "goed"
    if m3_per_hdd < BENCH_AVERAGE:   return "gemiddeld"
    return "slecht"


class GasAnalyzer:

    def __init__(self, hass: HomeAssistant, gas_entity_id: str = "") -> None:
        self.hass = hass
        self._gas_entity_id  = gas_entity_id
        self._store          = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._records: list[GasDayRecord] = []

        # Lopende dag
        self._today_date     = ""
        self._today_start_m3 = 0.0   # meterstand om middernacht van vandaag
        self._today_temps:list[float] = []
        self._last_m3        = 0.0
        self._current_price  = GAS_PRICE_DEFAULT

        self._week_start_m3  = 0.0
        self._month_start_m3 = 0.0
        self._year_start_m3  = 0.0

        self._dirty     = False
        self._last_save = 0.0
        self._high_log_cb = None

        # Isolatie tracking
        self._isolation_date    = ""
        self._pre_isolation_eff = 0.0

    # ── Setup / opslag ────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for d in saved.get("records", []):
            try:
                self._records.append(GasDayRecord(**d))
            except Exception:
                pass
        self._today_date     = saved.get("today_date", "")
        self._today_start_m3 = float(saved.get("today_start_m3", 0.0))
        self._week_start_m3  = float(saved.get("week_start_m3",  0.0))
        self._month_start_m3 = float(saved.get("month_start_m3", 0.0))
        self._year_start_m3  = float(saved.get("year_start_m3",  0.0))
        self._last_m3        = float(saved.get("last_m3", 0.0))
        self._isolation_date    = saved.get("isolation_date", "")
        self._pre_isolation_eff = float(saved.get("pre_isolation_eff", 0.0))
        _LOGGER.info("GasAnalyzer: %d dagrecords geladen", len(self._records))

    async def async_save(self) -> None:
        await self._store.async_save({
            "records":           [r.to_dict() for r in self._records],
            "today_date":        self._today_date,
            "today_start_m3":    round(self._today_start_m3, 3),
            "week_start_m3":     round(self._week_start_m3,  3),
            "month_start_m3":    round(self._month_start_m3, 3),
            "year_start_m3":     round(self._year_start_m3,  3),
            "last_m3":           round(self._last_m3, 3),
            "isolation_date":    self._isolation_date,
            "pre_isolation_eff": round(self._pre_isolation_eff, 6),
        })
        self._dirty = False
        self._last_save = time.time()

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self.async_save()

    # ── Logging ───────────────────────────────────────────────────────────────

    def set_log_callback(self, cb) -> None:
        self._high_log_cb = cb

    def _high_log(self, category: str, payload: dict) -> None:
        if not self._high_log_cb:
            return
        try:
            import asyncio as _aio
            _aio.ensure_future(self._high_log_cb(category, payload))
        except Exception:
            pass

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _find_gas_sensor(self) -> Optional[str]:
        """Geconfigureerde sensor of auto-detect op unit=m³ >100."""
        if self._gas_entity_id:
            st = self.hass.states.get(self._gas_entity_id)
            if st and st.state not in ("unavailable", "unknown", ""):
                try:
                    if float(st.state) > 0:
                        return self._gas_entity_id
                except (ValueError, TypeError):
                    pass
        for st in self.hass.states.async_all("sensor"):
            if "cloudems" in st.entity_id:
                continue
            if st.attributes.get("unit_of_measurement") != "m³":
                continue
            try:
                if float(st.state) > 100:
                    return st.entity_id
            except (ValueError, TypeError):
                pass
        return None

    async def _get_value_at(self, entity_id: str, at: datetime) -> Optional[float]:
        """Haal sensorwaarde op uit HA history op tijdstip `at`."""
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import get_significant_states

            start = at - timedelta(hours=2)
            end   = at + timedelta(minutes=5)
            instance = get_instance(self.hass)
            # significant_changes_only=False zodat ook uren zonder verbruik teruggegeven worden
            states_map = await instance.async_add_executor_job(
                get_significant_states,
                self.hass, start, end, [entity_id], None, False,
            )
            states = states_map.get(entity_id, [])
            if not states:
                # Vergroot zoekvenster als niets gevonden
                states_map = await instance.async_add_executor_job(
                    get_significant_states,
                    self.hass, at - timedelta(hours=12), at + timedelta(hours=1),
                    [entity_id], None, False,
                )
                states = states_map.get(entity_id, [])
            best = None
            for s in states:
                if s.last_updated <= at:
                    best = s
            if best is None and states:
                best = states[0]
            if best and best.state not in ("unavailable", "unknown", ""):
                val = float(best.state)
                return val if val > 0 else None
        except Exception as e:
            _LOGGER.debug("GasAnalyzer history fout: %s", e)
        return None

    async def _ensure_period_starts(self) -> None:
        """Haal periode-startwaarden uit HA history als ze nog 0 zijn.
        Vandaag = meterstand om middernacht.
        Week/maand/jaar = meterstand begin van die periode.
        """
        eid = self._find_gas_sensor()
        if not eid:
            return
        now      = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_s   = midnight - timedelta(days=7)
        month_s  = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        year_s   = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        changed = False
        if self._today_start_m3 <= 0:
            val = await self._get_value_at(eid, midnight)
            if val:
                self._today_start_m3 = val
                changed = True
                _LOGGER.info("GasAnalyzer: dag-start = %.3f m³", val)

        if self._week_start_m3 <= 0:
            val = await self._get_value_at(eid, week_s)
            if val:
                self._week_start_m3 = val
                changed = True
                _LOGGER.info("GasAnalyzer: week-start = %.3f m³", val)

        if self._month_start_m3 <= 0:
            val = await self._get_value_at(eid, month_s)
            if val:
                self._month_start_m3 = val
                changed = True
                _LOGGER.info("GasAnalyzer: maand-start = %.3f m³ (history)", val)
            else:
                # Fallback: statistics sum-delta → bereken abs start
                usage = await self._get_usage_since(eid, month_s)
                if usage is not None and self._last_m3 > 0:
                    self._month_start_m3 = max(0.0, self._last_m3 - usage)
                    changed = True
                    _LOGGER.info("GasAnalyzer: maand-start = %.3f m³ (statistics, verbruik=%.3f)",
                                 self._month_start_m3, usage)

        if self._year_start_m3 <= 0:
            val = await self._get_value_at(eid, year_s)
            if val:
                self._year_start_m3 = val
                changed = True
                _LOGGER.info("GasAnalyzer: jaar-start = %.3f m³ (history)", val)
            else:
                usage = await self._get_usage_since(eid, year_s)
                if usage is not None and self._last_m3 > 0:
                    self._year_start_m3 = max(0.0, self._last_m3 - usage)
                    changed = True
                    _LOGGER.info("GasAnalyzer: jaar-start = %.3f m³ (statistics, verbruik=%.3f)",
                                 self._year_start_m3, usage)

        if changed:
            self._dirty = True
            self._high_log("gas_period_starts", {
                "sensor":         eid,
                "dag_start_m3":   round(self._today_start_m3, 3),
                "week_start_m3":  round(self._week_start_m3,  3),
                "maand_start_m3": round(self._month_start_m3, 3),
                "jaar_start_m3":  round(self._year_start_m3,  3),
            })

        # Backfill dagrecords uit statistics als er geen records zijn (verse installatie/herschrijving)
        if not self._records:
            await self._backfill_records_from_statistics(eid)

    async def _get_usage_since(self, entity_id: str, since: datetime) -> Optional[float]:
        """Haal verbruik op via long-term statistics: sum[nu] - sum[since].
        Werkt ook voor maand/jaar (history gaat maar 10 dagen terug)."""
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period
            from homeassistant.util import dt as dt_util

            now = dt_util.now()
            instance = get_instance(self.hass)
            stats = await instance.async_add_executor_job(
                statistics_during_period,
                self.hass, since, now, {entity_id}, "hour", None, {"sum"},
            )
            data = (stats or {}).get(entity_id, [])
            if not data:
                _LOGGER.warning("GasAnalyzer backfill: geen statistics data voor %s (sensor heeft mogelijk geen state_class: total_increasing)", entity_id)
                self._high_log("gas_backfill_no_data", {"sensor": entity_id})
                return None
            data_sorted = sorted(data, key=lambda r: r.get("start") or now)
            # sum[nu] = laatste entry
            sum_now = data_sorted[-1].get("sum")
            # sum[since] = eerste entry (net na since)
            sum_then = data_sorted[0].get("sum")
            if sum_now is None or sum_then is None:
                return None
            delta = float(sum_now) - float(sum_then)
            return max(0.0, delta) if delta >= 0 else None
        except Exception as e:
            _LOGGER.debug("GasAnalyzer statistics fout: %s", e)
            return None

    async def _backfill_records_from_statistics(self, entity_id: str) -> None:
        """Reconstrueer dagrecords uit HA statistics voor drill-down display.
        Gebruikt sum-delta per dag: verbruik dag N = sum[einde dag N] - sum[begin dag N].
        """
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period
            from homeassistant.util import dt as dt_util
            import datetime as _dt

            now = dt_util.now()
            # Haal 31 dagen terug
            start = now - timedelta(days=31)
            instance = get_instance(self.hass)
            # Probeer eerst met entity_id, dan met statistic_id (kan verschillen bij HomeWizard/DSMR)
            stats = await instance.async_add_executor_job(
                statistics_during_period,
                self.hass, start, now, {entity_id}, "hour", None, {"sum"},
            )
            data = (stats or {}).get(entity_id, [])

            # Fallback: zoek statistic_id via recorder metadata
            if not data:
                try:
                    from homeassistant.components.recorder.statistics import list_statistic_ids
                    all_stats = await instance.async_add_executor_job(
                        list_statistic_ids, self.hass, None, "sum"
                    )
                    # Zoek statistic_id die overeenkomt met entity_id
                    stat_id = None
                    for s in (all_stats or []):
                        if s.get("statistic_id") == entity_id or s.get("name","").lower() in entity_id.lower():
                            stat_id = s.get("statistic_id")
                            break
                        # HomeWizard patroon: sensor.xxx_gas_m3 → statistic_id kan anders zijn
                        if "gas" in s.get("statistic_id","").lower() and "cloudems" not in s.get("statistic_id",""):
                            stat_id = s.get("statistic_id")
                            # Neem de eerste niet-cloudems gas statistiek
                            break

                    if stat_id and stat_id != entity_id:
                        _LOGGER.info("GasAnalyzer backfill: gebruik statistic_id %s voor entity %s", stat_id, entity_id)
                        stats2 = await instance.async_add_executor_job(
                            statistics_during_period,
                            self.hass, start, now, {stat_id}, "hour", None, {"sum"},
                        )
                        data = (stats2 or {}).get(stat_id, [])
                except Exception as _meta_err:
                    _LOGGER.debug("GasAnalyzer backfill metadata fout: %s", _meta_err)

            if not data:
                _LOGGER.warning("GasAnalyzer backfill: geen statistics voor %s", entity_id)
                self._high_log("gas_backfill_no_data", {"sensor": entity_id})
                return

            # Groepeer per dag
            from collections import defaultdict
            day_sums = defaultdict(list)
            for row in data:
                ts = row.get("start")
                s  = row.get("sum")
                if ts and s is not None:
                    day_key = ts.astimezone().strftime("%Y-%m-%d")
                    day_sums[day_key].append(float(s))

            # Delta per dag = max(dag) - min(dag)
            for day_str in sorted(day_sums.keys()):
                vals = day_sums[day_str]
                if len(vals) < 2:
                    continue
                delta = max(vals) - min(vals)
                if delta < 0 or delta > 500:  # sanity check
                    continue
                record = GasDayRecord(
                    date=day_str,
                    gas_m3_delta=round(delta, 3),
                    price_eur_m3=self._current_price,  # indicatief
                    hdd=0.0,
                    outside_temp=10.0,
                )
                # Voeg alleen toe als niet al aanwezig
                if not any(r.date == day_str for r in self._records):
                    self._records.append(record)

            self._records.sort(key=lambda r: r.date)
            self._records = self._records[-365:]
            if self._records:
                self._dirty = True
                _LOGGER.info("GasAnalyzer: %d dagrecords hersteld uit statistics voor %s", len(self._records), entity_id)
                self._high_log("gas_backfill_done", {"sensor": entity_id, "records": len(self._records)})
            else:
                _LOGGER.warning("GasAnalyzer backfill: statistics aanwezig maar geen bruikbare dagrecords (delta <2 uur per dag?)")

        except Exception as e:
            _LOGGER.warning("GasAnalyzer backfill fout: %s", e)
            self._high_log("gas_backfill_error", {"error": str(e)})

    def update_price(self, price_eur_m3: float) -> None:
        self._current_price = price_eur_m3

    def tick(self, gas_m3_cumulative: float, outside_temp_c: float) -> None:
        if gas_m3_cumulative <= 0:
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if today != self._today_date:
            # Dag-overgang: sluit gisteren af
            if self._today_date and self._today_start_m3 > 0 and self._last_m3 > 0:
                self._finalize_day()
            # Begin nieuwe dag — reset starts bij periode-overgang
            self._today_date     = today
            self._today_start_m3 = gas_m3_cumulative
            # Week-overgang (maandag)
            new_week = (datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())).strftime("%Y-%m-%d")
            if today == new_week and self._week_start_m3 > 0 and today > (datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())).strftime("%Y-%m-%d"):
                self._week_start_m3 = gas_m3_cumulative
            # Maand-overgang (1e van de maand)
            if today.endswith("-01"):
                self._month_start_m3 = gas_m3_cumulative
            # Jaar-overgang (1 jan)
            if today.endswith("01-01"):
                self._year_start_m3 = gas_m3_cumulative
            self._today_temps    = []
            self._dirty = True

        self._last_m3 = gas_m3_cumulative
        self._today_temps.append(outside_temp_c)
        self._dirty = True

    def _finalize_day(self) -> None:
        delta = max(0.0, self._last_m3 - self._today_start_m3)
        avg_temp = sum(self._today_temps) / len(self._today_temps) if self._today_temps else 15.0
        hdd = max(0.0, HDD_SETPOINT_C - avg_temp)
        record = GasDayRecord(
            date=self._today_date,
            gas_m3_delta=round(delta, 3),
            price_eur_m3=self._current_price,
            hdd=round(hdd, 2),
            outside_temp=round(avg_temp, 1),
        )
        self._records.append(record)
        self._records = self._records[-365:]
        self._dirty = True
        _LOGGER.info("GasAnalyzer dag afgesloten: %s %.3f m³ €%.4f/m³",
                     self._today_date, delta, self._current_price)
        self._high_log("gas_day_closed", {
            "date": self._today_date,
            "gas_m3": round(delta, 3),
            "price_eur_m3": self._current_price,
            "kosten_eur": round(delta * self._current_price, 2),
        })

    # ── Get data ──────────────────────────────────────────────────────────────

    def get_data(self, gas_price_eur_m3: float = GAS_PRICE_DEFAULT,
                 current_m3: float = 0.0) -> GasAnalysisData:
        """
        Bereken periodes.
        Vandaag: live - today_start_m3
        Week/maand/jaar: som dagrecords in periode + vandaag
        Kosten: verbruik × prijs per dag uit records, vandaag × huidige prijs
        """
        now  = datetime.now(timezone.utc)
        live = current_m3 if current_m3 > 0 else self._last_m3

        # Vandaag
        gas_today  = max(0.0, live - self._today_start_m3) if self._today_start_m3 > 0 else 0.0
        cost_today = round(gas_today * gas_price_eur_m3, 2)

        # Datumgrenzen voor periode-filters
        today_str      = now.strftime("%Y-%m-%d")
        week_start_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        month_str      = now.strftime("%Y-%m")
        year_str       = now.strftime("%Y")

        def _sum_period(date_filter) -> tuple[float, float]:
            """Geeft (m3, kosten) voor records die aan date_filter voldoen, excl. vandaag."""
            recs = [r for r in self._records if date_filter(r.date) and r.date != today_str]
            m3   = sum(r.gas_m3_delta for r in recs)
            cost = sum(r.cost_eur     for r in recs)
            return m3, cost

        m3_week_hist,  cost_week_hist  = _sum_period(lambda d: d >= week_start_str)
        m3_month_hist, cost_month_hist = _sum_period(lambda d: d.startswith(month_str))
        m3_year_hist,  cost_year_hist  = _sum_period(lambda d: d.startswith(year_str))

        # Gebruik live - start als er geen dagrecords zijn (verse installatie)
        # Dagrecords zijn leidend zodra er data is
        gas_week  = round(m3_week_hist  + gas_today, 3) if m3_week_hist  > 0 else round(max(0.0, live - self._week_start_m3)  + 0, 3) if self._week_start_m3  > 0 else round(gas_today, 3)
        gas_month = round(m3_month_hist + gas_today, 1) if m3_month_hist > 0 else round(max(0.0, live - self._month_start_m3) + 0, 1) if self._month_start_m3 > 0 else round(gas_today, 1)
        gas_year  = round(m3_year_hist  + gas_today, 1) if m3_year_hist  > 0 else round(max(0.0, live - self._year_start_m3)  + 0, 1) if self._year_start_m3  > 0 else round(gas_today, 1)

        cost_week  = round(cost_week_hist  + cost_today, 2)
        cost_month = round(cost_month_hist + cost_today, 2)
        cost_year  = round(cost_year_hist  + cost_today, 2)

        # HDD vandaag
        avg_temp_today = (sum(self._today_temps) / len(self._today_temps)) if self._today_temps else 15.0
        hdd_today  = max(0.0, HDD_SETPOINT_C - avg_temp_today)
        hdd_month  = sum(r.hdd for r in self._records if r.date.startswith(month_str))

        # Efficiëntie (30 dagen met stookwarmte)
        heating = [r for r in self._records[-30:] if r.hdd > 1.0 and r.gas_m3_delta > 0]
        eff = (sum(r.gas_m3_delta / r.hdd for r in heating) / len(heating)) if heating else 0.0
        rating = _rating(eff)

        # Seizoensprognose
        remaining_hdd = sum(NL_MONTHLY_HDD.get(m, 0) for m in range(now.month, 13))
        seasonal_m3   = round(eff * remaining_hdd, 0) if eff > 0 else 0.0
        seasonal_eur  = round(seasonal_m3 * gas_price_eur_m3, 2)

        # Advies
        if eff <= 0:
            advice = "Data wordt verzameld — efficiëntie zichtbaar na minimaal 5 stookdagen."
        elif rating == "uitstekend":
            advice = f"Uitstekend! CV verbruikt {eff:.4f} m³/HDD — bijna HR-ketel optimaal."
        elif rating == "goed":
            advice = f"Goed! {eff:.4f} m³/HDD is beter dan gemiddeld."
        elif rating == "gemiddeld":
            advice = f"Gemiddeld: {eff:.4f} m³/HDD. HR-ketel haalt {BENCH_GOOD:.4f}. Overweeg onderhoud."
        else:
            advice = f"Hoog verbruik: {eff:.4f} m³/HDD. Laat CV onderhouden en controleer isolatie."

        return GasAnalysisData(
            gas_m3_today=gas_today,
            gas_m3_week=gas_week,
            gas_m3_month=gas_month,
            gas_m3_year=gas_year,
            gas_cost_today_eur=cost_today,
            gas_cost_week_eur=cost_week,
            gas_cost_month_eur=cost_month,
            gas_cost_year_eur=cost_year,
            efficiency_m3_hdd=round(eff, 4),
            efficiency_rating=rating,
            hdd_today=round(hdd_today, 2),
            hdd_month=round(hdd_month, 1),
            seasonal_forecast_m3=seasonal_m3,
            seasonal_forecast_eur=seasonal_eur,
            anomaly=False,
            anomaly_message="",
            advice=advice,
            records_count=len(self._records),
        )

    def register_isolation_investment(self, date_str: str = "") -> None:
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        heating = [r for r in self._records[-30:] if r.hdd > 1.0 and r.gas_m3_delta > 0]
        if heating:
            self._pre_isolation_eff = sum(r.gas_m3_delta / r.hdd for r in heating) / len(heating)
        self._isolation_date = date_str
        self._dirty = True
