"""
CloudEMS HistoricalBootstrapper — v5.5.504
Importeert historische sensordata vanuit HA recorder statistics.

Maakt learners, forecasts en kWh-totalen betrouwbaar vanaf dag 1
zonder weken te wachten op real-time accumulatie.

Ondersteunt:
- PV productie (uur voor uur profiel voor zonne-forecast learner)
- Grid import/export (historische dagbedragen)
- Batterij laden/ontladen (historische dagbedragen)
- Huisverbruik (uur voor uur profiel voor HouseConsumptionLearner)
- NILM apparaten (historisch verbruik per apparaat)
"""
from __future__ import annotations
import logging
import datetime
from typing import Optional, Callable

_LOGGER = logging.getLogger(__name__)

# Hoeveel dagen terugkijken per categorie
_LOOKBACK_DAYS = {
    "pv":             365,   # PV: 1 jaar voor seizoenspatroon
    "house":           90,   # Huis: 3 maanden voor weekpatroon
    "grid_import":     90,
    "grid_export":     90,
    "battery_charge":  30,
    "battery_discharge": 30,
    "device":          30,
}


class HistoricalBootstrapper:
    """
    Leest historische statistieken uit HA recorder en voedt daarmee
    de CloudEMS learners en kWh-accumulatoren.

    Gebruik:
        bootstrapper = HistoricalBootstrapper(hass, config)
        await bootstrapper.async_bootstrap_all(coordinator)
    """

    def __init__(self, hass, config: dict):
        self.hass = hass
        self.config = config
        self._done: set = set()  # gevulde categorieën (vermijd dubbel)

    async def _fetch_hourly_stats(self, entity_id: str, days: int,
                                   stat_type: str = "sum") -> list[dict]:
        """
        Haal uurstatistieken op vanuit HA recorder.
        Retourneert lijst van {start: datetime, value: float}.
        """
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period
            from homeassistant.util import dt as dt_util

            now   = dt_util.now()
            start = now - datetime.timedelta(days=days)
            recorder = get_instance(self.hass)

            stats = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass, start, now, {entity_id}, "hour", None, {stat_type}
            )
            rows = stats.get(entity_id, [])
            result = []
            for row in rows:
                val = row.get(stat_type)
                _start = row.get("start")
                if val is None or _start is None:
                    continue
                try:
                    val = float(val)
                    if isinstance(_start, (int, float)):
                        dt = datetime.datetime.fromtimestamp(_start,
                             tz=datetime.timezone.utc)
                    elif hasattr(_start, "timestamp"):
                        dt = _start
                    else:
                        continue
                    result.append({"start": dt, "value": val})
                except (ValueError, TypeError):
                    continue
            _LOGGER.debug("HistoricalBootstrapper: %s → %d uurpunten (%d dagen)",
                          entity_id, len(result), days)
            return result
        except Exception as exc:
            _LOGGER.debug("HistoricalBootstrapper._fetch_hourly_stats[%s]: %s",
                          entity_id, exc)
            return []

    async def _fetch_daily_stats(self, entity_id: str, days: int) -> list[dict]:
        """
        Haal dagstatistieken op (samengevat per dag).
        Retourneert lijst van {date: date, kwh: float}.
        """
        hourly = await self._fetch_hourly_stats(entity_id, days, "sum")
        if not hourly:
            return []

        # Groepeer per dag — gebruik delta voor cumulatieve sensoren
        from collections import defaultdict
        day_buckets: dict[datetime.date, list[float]] = defaultdict(list)
        for row in hourly:
            day = row["start"].astimezone().date()
            day_buckets[day].append(row["value"])

        result = []
        for day in sorted(day_buckets.keys()):
            vals = day_buckets[day]
            if len(vals) >= 2:
                # Cumulatieve sensor: delta = max - min (groei die dag)
                kwh = max(vals) - min(vals)
            else:
                # Enkel datapunt: gebruik direct
                kwh = vals[0]
            if kwh >= 0:
                result.append({"date": day, "kwh": round(kwh, 3)})
        return result

    async def bootstrap_pv(self, entity_ids: list[str],
                            pv_forecast=None) -> dict:
        """
        Laad historische PV-productie en voed de PV forecast learner.
        Retourneert dict {datum: kwh} voor de afgelopen periode.
        """
        if "pv" in self._done or not entity_ids:
            return {}

        all_daily: dict[datetime.date, float] = {}
        for eid in entity_ids:
            daily = await self._fetch_daily_stats(eid, _LOOKBACK_DAYS["pv"])
            for row in daily:
                d = row["date"]
                all_daily[d] = all_daily.get(d, 0.0) + row["kwh"]

        if not all_daily:
            return {}

        _LOGGER.info("HistoricalBootstrapper: PV %d historische dagwaarden geladen "
                     "(%d sensoren)", len(all_daily), len(entity_ids))

        # Voed PV forecast learner met historische data
        if pv_forecast and hasattr(pv_forecast, "feed_historical_daily"):
            try:
                for d, kwh in all_daily.items():
                    pv_forecast.feed_historical_daily(d, kwh)
                _LOGGER.info("HistoricalBootstrapper: PV forecast learner gevoed "
                             "met %d historische dagen", len(all_daily))
            except Exception as exc:
                _LOGGER.debug("PV forecast historical feed fout: %s", exc)

        self._done.add("pv")
        return {d.isoformat(): kwh for d, kwh in all_daily.items()}

    async def bootstrap_house(self, entity_id: str,
                               house_learner=None) -> dict:
        """
        Laad historisch huisverbruik (uur voor uur) en voed de HouseConsumptionLearner.
        """
        if "house" in self._done or not entity_id:
            return {}

        hourly = await self._fetch_hourly_stats(entity_id, _LOOKBACK_DAYS["house"], "mean")
        if not hourly:
            return {}

        _LOGGER.info("HistoricalBootstrapper: huis %d historische uurwaarden geladen",
                     len(hourly))

        # Voed HouseConsumptionLearner
        if house_learner and hasattr(house_learner, "feed_historical"):
            try:
                for row in hourly:
                    dt = row["start"].astimezone()
                    weekday = dt.weekday()
                    hour = dt.hour
                    # mean is in W (vermogen), niet kWh
                    house_learner.feed_historical(weekday, hour, row["value"])
                _LOGGER.info("HistoricalBootstrapper: HouseConsumptionLearner gevoed "
                             "met %d historische uurpunten", len(hourly))
            except Exception as exc:
                _LOGGER.debug("House learner historical feed fout: %s", exc)

        self._done.add("house")
        return {"hourly_points": len(hourly)}

    async def bootstrap_grid(self, import_eid: Optional[str],
                              export_eid: Optional[str]) -> dict:
        """Laad historische grid import/export dagbedragen."""
        result = {}
        if import_eid and "grid_import" not in self._done:
            daily = await self._fetch_daily_stats(import_eid, _LOOKBACK_DAYS["grid_import"])
            result["import"] = daily
            self._done.add("grid_import")
        if export_eid and "grid_export" not in self._done:
            daily = await self._fetch_daily_stats(export_eid, _LOOKBACK_DAYS["grid_export"])
            result["export"] = daily
            self._done.add("grid_export")
        if result:
            _LOGGER.info("HistoricalBootstrapper: grid %d import + %d export dagen geladen",
                         len(result.get("import", [])), len(result.get("export", [])))
        return result

    async def bootstrap_battery(self, charge_eid: Optional[str],
                                 discharge_eid: Optional[str]) -> dict:
        """Laad historische batterij laden/ontladen dagbedragen."""
        result = {}
        if charge_eid and "battery_charge" not in self._done:
            result["charge"] = await self._fetch_daily_stats(
                charge_eid, _LOOKBACK_DAYS["battery_charge"])
            self._done.add("battery_charge")
        if discharge_eid and "battery_discharge" not in self._done:
            result["discharge"] = await self._fetch_daily_stats(
                discharge_eid, _LOOKBACK_DAYS["battery_discharge"])
            self._done.add("battery_discharge")
        return result

    async def bootstrap_device(self, entity_id: str, device_id: str,
                                device_learner=None) -> dict:
        """Laad historisch apparaatverbruik voor een NILM device."""
        key = f"device_{device_id}"
        if key in self._done or not entity_id:
            return {}
        daily = await self._fetch_daily_stats(entity_id, _LOOKBACK_DAYS["device"])
        if daily and device_learner and hasattr(device_learner, "feed_historical_daily"):
            try:
                for row in daily:
                    device_learner.feed_historical_daily(device_id, row["date"], row["kwh"])
            except Exception as exc:
                _LOGGER.debug("Device learner historical feed[%s]: %s", device_id, exc)
        self._done.add(key)
        return {"daily_points": len(daily)}

    async def async_bootstrap_all(self, coordinator) -> dict:
        """
        Bootstrap alle beschikbare historische data voor alle geconfigureerde sensoren.
        Veilig om meerdere keren aan te roepen — overgeslagen als al gedaan.
        """
        cfg = self.config
        summary = {}

        # PV
        pv_eids = [inv.get("energy_sensor") for inv in cfg.get("inverter_configs", [])
                   if inv.get("energy_sensor")]
        if pv_eids:
            pv_forecast = getattr(coordinator, "_pv_forecast", None)
            summary["pv"] = await self.bootstrap_pv(pv_eids, pv_forecast)

        # Huis
        house_eid = (cfg.get("grid_sensor") or cfg.get("import_power_sensor") or
                     cfg.get(coordinator.CONF_GRID_SENSOR if hasattr(coordinator, "CONF_GRID_SENSOR") else "_", ""))
        house_learner = getattr(coordinator, "_house_consumption_learner", None)
        if house_learner:
            # Gebruik P1 data als proxy voor huisverbruik
            p1_eid = cfg.get("import_power_sensor") or cfg.get("grid_sensor")
            if p1_eid:
                summary["house"] = await self.bootstrap_house(p1_eid, house_learner)

        # Grid kWh sensoren
        summary["grid"] = await self.bootstrap_grid(
            cfg.get("grid_import_kwh_sensor"),
            cfg.get("grid_export_kwh_sensor")
        )

        # Batterij
        for i, bat in enumerate(cfg.get("battery_configs", [])):
            result = await self.bootstrap_battery(
                bat.get("charge_kwh_sensor"),
                bat.get("discharge_kwh_sensor")
            )
            if result:
                summary[f"battery_{i}"] = result

        # NILM devices
        for dev in cfg.get("nilm_device_configs", []):
            eid = dev.get("energy_sensor")
            did = dev.get("device_id") or dev.get("entity_id", "")
            if eid and did:
                nilm = getattr(coordinator, "_nilm", None)
                summary[f"device_{did}"] = await self.bootstrap_device(eid, did, nilm)

        _LOGGER.info("HistoricalBootstrapper.async_bootstrap_all: klaar — %d categorieën",
                     len(self._done))
        return summary
