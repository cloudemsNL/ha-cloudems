from __future__ import annotations
from homeassistant.core import callback
import re
# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS sensor + binary_sensor platform — v1.5.0."""
import logging
import time as _time_mod

# Shortcut for use in property expressions
def import_time() -> float:
    return _time_mod.time()

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower, UnitOfElectricCurrent, UnitOfElectricPotential,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, NAME, MANUFACTURER, VERSION, WEBSITE, ATTRIBUTION,
    ICON_NILM, ICON_LIMITER, ICON_PRICE, ICON_SOLAR, ICON_VOLTAGE,
    ICON_POWER, ICON_FORECAST, ICON_ENERGY, ICON_PEAK,
    CONF_PHASE_COUNT, CONF_INVERTER_CONFIGS,
    DEVICE_ICONS,
    GAS_KWH_PER_M3, GAS_BOILER_EFFICIENCY,
    DEFAULT_BOILER_EFFICIENCY, DEFAULT_HEAT_PUMP_COP, DEFAULT_GAS_PRICE_EUR_M3,
    CONF_GAS_PRICE_SENSOR, CONF_GAS_PRICE_FIXED, CONF_BOILER_EFFICIENCY, CONF_HEAT_PUMP_COP,
    CONF_HEAT_PUMP_ENTITY,
    CONF_NILM_PRUNE_THRESHOLD, DEFAULT_NILM_PRUNE_THRESHOLD,
    CONF_NILM_PRUNE_MIN_DAYS, DEFAULT_NILM_PRUNE_MIN_DAYS,
)
from .sub_devices import sub_device_info, SUB_SOLAR, SUB_ZONE_CLIMATE, SUB_NILM, SUB_BOILER, SUB_PRICE, SUB_LAMP, SUB_SHUTTER, SUB_BATTERY, SUB_GRID, SUB_EV, SUB_POOL, SUB_GAS, SUB_GENERATOR, SUB_HOUSE, SUB_SYSTEM
from .performance_monitor import AdaptiveForceUpdateMixin
from .coordinator import CloudEMSCoordinator

_LOGGER = logging.getLogger(__name__)



# ═══════════════════════════════════════════════════════════════════════════════
# Helper — keep HA recorder happy (16 KB attribute limit)
# ═══════════════════════════════════════════════════════════════════════════════

_ATTR_LIMIT = 14_000  # bytes — stay safely below the 16 384 hard limit

def _trim_attrs(attrs: dict) -> dict:
    """Truncate sensor attributes to always stay under the HA recorder limit.

    Strategy (in order):
      1. Measure serialised JSON size.
      2. If within limit → return as-is.
      3. Find all list values, sorted by size (largest first).
      4. Shorten each list by 25 % per iteration until payload fits.
      5. If still too large → clear remaining lists, then drop non-scalar values.
    """
    import json as _json
    raw = _json.dumps(attrs, default=str)
    if len(raw) <= _ATTR_LIMIT:
        return attrs
    result = dict(attrs)
    list_keys = sorted(
        [k for k, v in result.items() if isinstance(v, list)],
        key=lambda k: len(_json.dumps(result[k], default=str)),
        reverse=True,
    )
    for key in list_keys:
        while result[key] and len(_json.dumps(result, default=str)) > _ATTR_LIMIT:
            result[key] = result[key][:max(0, int(len(result[key]) * 0.75))]
        if not result[key]:
            result[key] = []
    if len(_json.dumps(result, default=str)) > _ATTR_LIMIT:
        for key in sorted(result, key=lambda k: len(_json.dumps(result[k], default=str)), reverse=True):
            if not isinstance(result[key], (int, float, bool, type(None))):
                result[key] = None
            if len(_json.dumps(result, default=str)) <= _ATTR_LIMIT:
                break
    return result

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CloudEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    phase_count = int(entry.data.get(CONF_PHASE_COUNT, 1))
    inv_cfgs    = {**entry.data, **entry.options}.get(CONF_INVERTER_CONFIGS, [])

    entities: list = [
        CloudEMSPowerSensor(coordinator, entry),
        CloudEMSHomeLoadSensor(coordinator, entry),   # v4.0.9+: EMA-gefilterd huisverbruik
        CloudEMSHomeRestSensor(coordinator, entry),   # v4.5.98+: REST voor flow kaart
        # CloudEMSGridNetPowerSensor removed – CloudEMSPowerSensor owns
        # sensor.cloudems_power (unique_id _power). Name was fixed from
        # "CloudEMS Grid · Net Power" → "CloudEMS Power" to match expected entity_id.
        CloudEMSGridImportPowerSensor(coordinator, entry),
        CloudEMSGridExportPowerSensor(coordinator, entry),
        CloudEMSGridImportEnergySensor(coordinator, entry, tariff=1),
        CloudEMSGridImportEnergySensor(coordinator, entry, tariff=2),
        CloudEMSGridExportEnergySensor(coordinator, entry, tariff=1),
        CloudEMSGridExportEnergySensor(coordinator, entry, tariff=2),
        # v1.10.2: NILM top-5 highest-power running devices
        *[CloudEMSNILMTopDeviceSensor(coordinator, entry, rank) for rank in range(1, 16)],
        # v1.10.3: Solar ROI sensor
        CloudEMSSolarROISensor(coordinator, entry),
        # v1.10.3: Self-learning intelligence sensors (zero-config)
        CloudEMSHomeBaselineSensor(coordinator, entry),
        CloudEMSStandbyHunterSensor(coordinator, entry),  # occupancy + anomaly → binary_sensor.py
        CloudEMSEVSessionSensor(coordinator, entry),
        CloudEMSNILMScheduleSensor(coordinator, entry),
        CloudEMSWeatherCalibrationSensor(coordinator, entry),
        # v1.11.0: 8 new intelligence sensors
        CloudEMSThermalModelSensor(coordinator, entry),
        CloudEMSFlexScoreSensor(coordinator, entry),
        CloudEMSPVHealthSensor(coordinator, entry),
        CloudEMSGasSensor(coordinator, entry),
        CloudEMSEnergySourceSensor(coordinator, entry),
        CloudEMSDayTypeSensor(coordinator, entry),
        CloudEMSDeviceDriftSensor(coordinator, entry),
        CloudEMSPhaseMigrationSensor(coordinator, entry),
        CloudEMSMicroMobilitySensor(coordinator, entry),
        CloudEMSNotificationSensor(coordinator, entry),
        CloudEMSClippingLossSensor(coordinator, entry),
        CloudEMSConsumptionCategoriesSensor(coordinator, entry),
        CloudEMSRoomMeterOverviewSensor(coordinator, entry),     # v1.20
        CloudEMSSolarSystemSensor(coordinator, entry),
        # v1.5: dedicated previous / current / next-hour price sensors
        CloudEMSPriceSensor(coordinator, entry),
        CloudEMSPricePreviousHourSensor(coordinator, entry),
        CloudEMSPriceCurrentSensor(coordinator, entry),
        CloudEMSPriceNextHourSensor(coordinator, entry),
        CloudEMSNILMStatsSensor(coordinator, entry),
        # v1.5: NILM running-devices list sensors (plain + with power)
        CloudEMSNILMRunningDevicesSensor(coordinator, entry),
        CloudEMSNILMRunningDevicesPowerSensor(coordinator, entry),
        CloudEMSNILMReviewCurrentSensor(coordinator, entry),
        CloudEMSCostSensor(coordinator, entry),
        CloudEMSDagkostenSensor(coordinator, entry),
        CloudEMSComfortScoreSensor(coordinator, entry),
        CloudEMSP1Sensor(coordinator, entry),
        CloudEMSForecastSensor(coordinator, entry),
        CloudEMSForecastTomorrowSensor(coordinator, entry),
        CloudEMSForecastPeakSensor(coordinator, entry),
        CloudEMSPeakShavingSensor(coordinator, entry),
        CloudEMSGridCongestionSensor(coordinator, entry),
        CloudEMSBatteryHealthSensor(coordinator, entry),
        CloudEMSBatterySocSensor(coordinator, entry),
        CloudEMSMonthlyPeakSensor(coordinator, entry),
        CloudEMSNILMDatabaseSensor(coordinator, entry),
        CloudEMSSensorHintsSensor(coordinator, entry),
        CloudEMSScaleInfoSensor(coordinator, entry),
        CloudEMSInsightsSensor(coordinator, entry),
        CloudEMSDecisionLogSensor(coordinator, entry),
        CloudEMSBoilerStatusSensor(coordinator, entry),
        CloudEMSEnergyDemandSensor(coordinator, entry),
        CloudEMSClimateEpexStatusSensor(coordinator, entry),
        CloudEMSPoolStatusSensor(coordinator, entry),
        # v4.6.89: eigen recorder-sensoren voor waarden die anders alleen uit externe
        # entities komen — altijd beschikbaar ook als cloud/device tijdelijk offline is
        CloudEMSBuitenTempSensor(coordinator, entry),
        CloudEMSPoolWaterTempSensor(coordinator, entry),
        CloudEMSEVPowerSensor(coordinator, entry),
        CloudEMSDecisionsHistorySensor(coordinator, entry),  # v4.6.104: beslissingsgeschiedenis
        CloudEMSDecisionLearnerSensor(coordinator, entry),    # v4.6.498: decision outcome learner
        # v4.6.104: energie & batterij recorder-sensoren
        CloudEMSBatterijSOCSensor(coordinator, entry),
        CloudEMSNetVermogenSensor(coordinator, entry),
        CloudEMSZonVermogenSensor(coordinator, entry),
        CloudEMSBoilerSetpointSensor(coordinator, entry),
        CloudEMSSliderLeverenSensor(coordinator, entry),
        CloudEMSSliderZonladenSensor(coordinator, entry),
        CloudEMSGoedkoopstelaadmomentSensor(coordinator, entry),
        # v4.6.106: nieuwe feature sensoren
        CloudEMSSeizoensvergelijkingSensor(coordinator, entry),
        CloudEMSBoilerPlanningsSensor(coordinator, entry),
        CloudEMSBoilerEfficiencyV2Sensor(coordinator, entry),
        CloudEMSTelemetrySensor(coordinator, entry),
        CloudEMSEntityLogSensor(coordinator, entry),    # v4.6.13: entity/device log
        CloudEMSLampCirculationSensor(coordinator, entry),
        # v1.5: AI / NILM status sensor
        CloudEMSAIStatusSensor(coordinator, entry),
        # v1.6: EPEX all-hours chart sensor
        CloudEMSEPEXTodaySensor(coordinator, entry),
        # v1.20: dedicated goedkoopste 4-uursblok sensor
        CloudEMSCheapest4hBlockSensor(coordinator, entry),
        # v1.20: goedkope uren schakelaar planner status
        CloudEMSCheapSwitchesSensor(coordinator, entry),
        # v1.7: NILM Diagnostics sensor
        CloudEMSNILMDiagSensor(coordinator, entry),
        # v1.8: PID diagnostics sensor
        CloudEMSPIDDiagSensor(coordinator, entry),
        # v1.8: NILM sensor input info
        CloudEMSNILMInputSensor(coordinator, entry),
        # v4.3.26: SmartPowerEstimator (ingebouwde PowerCalc)
        CloudEMSPowerCalcSensor(coordinator, entry),
        # v1.9: CO2 intensity
        CloudEMSCO2Sensor(coordinator, entry),
        # v1.9: energy cost forecast
        CloudEMSCostForecastSensor(coordinator, entry),
        # v1.9: battery EPEX schedule
        CloudEMSBatteryScheduleSensor(coordinator, entry),
        # v1.15.4: new intelligence sensors (absence detector, climate preheat, PV accuracy, EMA diag, sanity)
        CloudEMSAbsenceDetectorSensor(coordinator, entry),
        CloudEMSClimatePreheatSensor(coordinator, entry),
        CloudEMSPVForecastAccuracySensor(coordinator, entry),
        CloudEMSBalancerSensor(coordinator, entry),
        CloudEMSSanitySensor(coordinator, entry),
        # v4.3.6: runtime warnings sensor (P1 spikes, fase-clamp, learning freeze)
        CloudEMSRuntimeWarningsSensor(coordinator, entry),
        # v4.5.51: meter topologie boom + upstream learning
        CloudEMSMeterTopologySensor(coordinator, entry),
        # v1.16.0: schaduwdetectie & clipping-voorspelling
        CloudEMSShadowDetectionSensor(coordinator, entry),
        CloudEMSClippingForecastSensor(coordinator, entry),
        # v1.16.0: Ollama AI diagnostics
        CloudEMSOllamaDiagSensor(coordinator, entry),
        # v1.17.0: Hybride NILM diagnostics
        CloudEMSHybridNILMSensor(coordinator, entry),
        # v2.1.9: Watchdog — crashgeschiedenis en herstartteller
        CloudEMSWatchdogSensor(coordinator, entry),
        # v4.0.5: Zelfconsumptie & zelfvoorzieningsgraad
        CloudEMSSelfConsumptionSensor(coordinator, entry),
        CloudEMSSelfSufficiencySensor(coordinator, entry),
        # v2.2.2: Installatie-kwaliteitsscore
        CloudEMSInstallationScoreSensor(coordinator, entry),
        # v2.2.3: nieuwe module-sensoren
        CloudEMSBehaviourCoachSensor(coordinator, entry),
        CloudEMSLoadPlanSensor(coordinator, entry),
        CloudEMSEnergyLabelSensor(coordinator, entry),
        CloudEMSSalderingSensor(coordinator, entry),
        CloudEMSSystemHealthSensor(coordinator, entry),
        # v2.2.5: nieuwe module-sensoren
        CloudEMSGasAnalysisSensor(coordinator, entry),
        CloudEMSEnergyBudgetSensor(coordinator, entry),
        CloudEMSApplianceROISensor(coordinator, entry),
        # v2.4.0: warmtepomp COP sensor (was missing from registration)
        CloudEMSWarmtepompCOPSensor(coordinator, entry),
        # v2.4.1: ontbrekende sensoren voor dashboard
        CloudEMSBillSimulatorSensor(coordinator, entry),
        CloudEMSNILMOverzichtSensor(coordinator, entry),
        # v2.2: Other-bucket sensor (onverklaard verbruik)
        CloudEMSOnbekendVerbruikSensor(coordinator, entry),
        # v2.4.19: mail-status sensor (vervangt config_entry_attr in dashboard)
        CloudEMSMailStatusSensor(coordinator, entry),
        # v4.6.445: slimme verlichting automatisering
        CloudEMSLampAutomationSensor(coordinator, entry),
        # v3.9.0: systeemstatus + guardian + battery savings
        CloudEMSStatusSensor(coordinator, entry),
        CloudEMSGuardianSensor(coordinator, entry),
        CloudEMSBatterySavingsSensor(coordinator, entry),
        # v4.5.131: batterij totaal vermogen + kWh accumulatie
        CloudEMSBatteryPowerSensor(coordinator, entry),
        # v4.5.121: losse Zonneplan slider kalibratie sensor
        CloudEMSZonneplanKalibratieSensor(coordinator, entry),
        # v4.6.438: generator brandstofkosten sensor
        CloudEMSGeneratorKostenSensor(coordinator, entry),
    ]

    phases = ["L1","L2","L3"] if phase_count == 3 else ["L1"]
    for ph in phases:
        entities.append(CloudEMSPhaseCurrentSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseSignedCurrentSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseVoltageSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhasePowerSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseImportPowerSensor(coordinator, entry, ph))
        entities.append(CloudEMSPhaseExportPowerSensor(coordinator, entry, ph))

    if phase_count == 3:
        entities.append(CloudEMSPhaseBalanceSensor(coordinator, entry))

    # Per-inverter sensors (peak, clipping, forecast)
    for inv in inv_cfgs:
        entities.append(CloudEMSInverterSensor(coordinator, entry, inv))

    # EPEX cheap-hour binary sensors (registered in binary_sensor.py for correct binary_sensor.* entity_ids)
    # for rank in [1, 2, 3]: entities.append(CloudEMSCheapHourBinarySensor(...))

    # v2.4.22: Rapport download URL sensor
    entities.append(CloudEMSReportURLSensor(coordinator, entry))

    # v2.6: Slaapstand, kwartier-piek, wekelijkse vergelijking
    entities.append(CloudEMSSlaapstandSensor(coordinator, entry))
    entities.append(CloudEMSKwartierPiekSensor(coordinator, entry))
    entities.append(CloudEMSWekelijkseVergelijkingSensor(coordinator, entry))

    # Zone climate cost sensor (sensor.cloudems_zone_klimaat_kosten_vandaag)
    entities.append(CloudEMSZoneClimateCostSensor(coordinator, entry))

    # v4.6.152: Adaptive performance monitor sensor
    entities.append(CloudEMSPerformanceSensor(coordinator, entry))

    async_add_entities(entities, update_before_add=True)

    # Pre-populate registered sets from the HA entity registry so that on HA
    # restart, already-known dynamic entities are not re-added (which causes
    # "ID already exists - ignoring" warnings in the log).
    from homeassistant.helpers import entity_registry as er
    _er = er.async_get(hass)
    _existing_uids: set = {
        e.unique_id
        for e in er.async_entries_for_config_entry(_er, entry.entry_id)
    }

    # Dynamically add NILM device sensors when detected + prune orphaned ones
    registered_nilm_ids: set = set(_existing_uids)

    # v4.6.158: one-time startup cleanup — remove NILM entities beyond cap
    # Cap verhoogd van 200 → 500 (v4.6.158) — grote installaties met veel devices
    _MAX_NILM_STARTUP = 500
    _nilm_pfx = f"{entry.entry_id}_nilm_"
    _static_suf = frozenset({"db","stats","running","running_power","diag","input","schedule","overzicht","review_current"})
    _all_nilm_dynamic = sorted(
        [e for e in er.async_entries_for_config_entry(_er, entry.entry_id)
         if e.unique_id and e.unique_id.startswith(_nilm_pfx)
         and e.domain == "sensor"
         and e.unique_id[len(_nilm_pfx):] not in _static_suf
         and not e.unique_id[len(_nilm_pfx):].startswith("__")
         and not e.unique_id[len(_nilm_pfx):].startswith("top_")
         and not e.unique_id[len(_nilm_pfx):].startswith("confirm_")
         and not e.unique_id[len(_nilm_pfx):].startswith("reject_")],
        key=lambda e: e.unique_id
    )
    if len(_all_nilm_dynamic) > _MAX_NILM_STARTUP:
        _to_remove = _all_nilm_dynamic[_MAX_NILM_STARTUP:]
        _LOGGER.warning(
            "CloudEMS NILM: %d NILM-sensoren gevonden, cap is %d — verwijder %d oudste orphaned sensoren bij startup.",
            len(_all_nilm_dynamic), _MAX_NILM_STARTUP, len(_to_remove),
        )
        for _orphan in _to_remove:
            try:
                _er.async_remove(_orphan.entity_id)
                registered_nilm_ids.discard(_orphan.unique_id)
            except Exception:
                pass

    # Pruning safety: only remove entiteiten die CloudEMS zelf heeft aangemaakt
    # (unique_id begint met "{entry_id}_nilm_") en nooit power sockets of andere
    # HA-entiteiten aanraken. Extra bescherming: wacht minimaal 2 coordinator-cycli
    # voordat een absent device als definitief verdwenen wordt beschouwd.
    _nilm_absent_counter: dict = {}   # uid → aantal cycli afwezig
    # v2.2.2: drempel instelbaar via config (default 2 cycli)
    _cfg_all = {**entry.data, **entry.options}
    _PRUNE_THRESHOLD = int(_cfg_all.get(CONF_NILM_PRUNE_THRESHOLD, DEFAULT_NILM_PRUNE_THRESHOLD))
    _PRUNE_MIN_DAYS  = int(_cfg_all.get(CONF_NILM_PRUNE_MIN_DAYS,  DEFAULT_NILM_PRUNE_MIN_DAYS))

    @callback
    def _nilm_updated():
        _er = er.async_get(hass)

        # ── Stap 1: toevoegen van nieuwe NILM-sensoren ────────────────────
        # v4.6.158: hard cap op 500 NILM device-sensoren — verhoogd van 200
        MAX_NILM_DEVICE_SENSORS = 500
        new_ents = []
        active_uids: set = set()
        # Tel huidige NILM device sensors (niet statische sensors)
        _nilm_uid_prefix_check = f"{entry.entry_id}_nilm_"
        _static_suffixes = frozenset({"db","stats","running","running_power","diag","input","schedule","overzicht","review_current"})
        _current_dynamic_count = sum(
            1 for uid in registered_nilm_ids
            if uid.startswith(_nilm_uid_prefix_check)
            and uid[len(_nilm_uid_prefix_check):] not in _static_suffixes
        )
        for dev in coordinator.nilm.get_devices():
            uid = f"{entry.entry_id}_nilm_{dev.device_id}"
            active_uids.add(uid)
            if uid not in registered_nilm_ids:
                if _current_dynamic_count >= MAX_NILM_DEVICE_SENSORS:
                    if not getattr(_nilm_cap_warned := True, '__class__', False):
                        pass  # suppress UnboundLocalError
                    _LOGGER.warning(
                        "CloudEMS NILM: entity cap bereikt (%d actief) — sensor voor '%s' (id=%s) overgeslagen. "
                        "Verwijder ongebruikte apparaten via NILM-tab → Overzicht → prullenbak.",
                        _current_dynamic_count, dev.name, dev.device_id,
                    )
                    continue
                new_ents.append(CloudEMSNILMDeviceSensor(coordinator, entry, dev))
                registered_nilm_ids.add(uid)
                _current_dynamic_count += 1
        if new_ents:
            async_add_entities(new_ents)

        # ── Stap 2: intelligente pruning van verdwenen NILM-sensoren ──────
        # Vind alle HA-entiteiten die door CloudEMS NILM zijn aangemaakt
        # (unique_id patroon: "<entry_id>_nilm_<device_id>")
        # maar waarvan het device_id niet meer voorkomt in de actieve NILM-lijst.
        #
        # Veiligheidsregels:
        #  • Alleen entiteiten met exact ons unique_id-patroon worden aangeraakt
        #  • Power sockets, grid, solar, battery sensoren worden NOOIT verwijderd
        #
        # v2.4.11: skip pruning zolang de NILM-storage nog niet volledig is geladen.
        # Bij herstart geeft get_devices() tijdelijk [] terug → sensoren zouden
        # onterecht worden weggegooid voordat de Store zijn data heeft ingelezen.
        if not getattr(coordinator.nilm, "_storage_loaded", False):
            return
        #  • Hybrid-ankers (__hybrid_*) worden NOOIT verwijderd (zijn smart plugs)
        #  • Een entity pas verwijderen na _PRUNE_THRESHOLD opeenvolgende afwezige cycli
        #    (beschermt tegen tijdelijke NILM-reset of herstart)
        #  • __battery_injected__ wordt nooit verwijderd
        nilm_uid_prefix = f"{entry.entry_id}_nilm_"

        # Bepaal welke uid's in de registry staan maar niet meer actief zijn.
        # v2.4.19: alleen sensor-platform entiteiten — switches, buttons en andere
        # platforms vallen buiten de verantwoordelijkheid van de sensor-pruner.
        registry_nilm_uids = {
            e.unique_id
            for e in er.async_entries_for_config_entry(_er, entry.entry_id)
            if e.unique_id
            and e.unique_id.startswith(nilm_uid_prefix)
            and e.domain == "sensor"
        }

        absent_uids = registry_nilm_uids - active_uids

        # Statische sensoren waarvan het unique_id toevallig ook met _nilm_ begint
        # maar die GEEN dynamische apparaat-sensoren zijn — nooit verwijderen.
        _STATIC_NILM_SUFFIXES = frozenset({
            "db", "stats", "running", "running_power",
            "diag", "input", "schedule", "overzicht",
            "review_current",
        })

        for uid in absent_uids:
            # Beschermde device_id's die nooit mogen worden verwijderd
            device_id_part = uid[len(nilm_uid_prefix):]
            if (
                device_id_part.startswith("__hybrid_")      # smart plug ankers
                or device_id_part == "__battery_injected__"  # batterij-injectie
                or device_id_part.startswith("__")           # toekomstige interne ids
                or device_id_part in _STATIC_NILM_SUFFIXES  # vaste module-sensoren
                or device_id_part.startswith("top_")        # nilm_top_1 … top_15
                or device_id_part.startswith("confirm_")    # bevestig-knoppen (button.py)
                or device_id_part.startswith("reject_")     # afwijs-knoppen (button.py)
            ):
                _nilm_absent_counter.pop(uid, None)
                continue

            # Tel opeenvolgende afwezige cycli
            _nilm_absent_counter[uid] = _nilm_absent_counter.get(uid, 0) + 1

            if _nilm_absent_counter[uid] >= _PRUNE_THRESHOLD:
                # v2.2.2: optionele minimum-inactiviteit in dagen
                if _PRUNE_MIN_DAYS > 0:
                    # Haal last_seen op uit het device (via registry entity_id → coordinator)
                    _dev_obj = coordinator.nilm.get_device(device_id_part)
                    if _dev_obj:
                        _age_days = (_time_mod.time() - _dev_obj.last_seen) / 86400.0
                        if _age_days < _PRUNE_MIN_DAYS:
                            continue  # Nog niet lang genoeg inactief
                # Verwijder uit HA entity registry
                entity_entry = _er.async_get_entity_id("sensor", "cloudems", uid)
                if entity_entry is None:
                    # Zoek op unique_id via de registry entries
                    for reg_entry in er.async_entries_for_config_entry(_er, entry.entry_id):
                        if reg_entry.unique_id == uid:
                            entity_entry = reg_entry.entity_id
                            break

                if entity_entry:
                    _LOGGER.info(
                        "CloudEMS NILM pruning: verwijder orphaned sensor '%s' (device_id=%s, "
                        "%d cycli afwezig)",
                        entity_entry, device_id_part, _nilm_absent_counter[uid],
                    )
                    _er.async_remove(entity_entry)
                    registered_nilm_ids.discard(uid)
                    _nilm_absent_counter.pop(uid, None)
                    # v4.2.2: knoppen + notificaties worden afgehandeld door OrphanPruner (orphan_pruner.py)

        # Reset teller voor uid's die weer actief zijn (los van de for-loop)
        for uid in list(_nilm_absent_counter.keys()):
            if uid in active_uids:
                _nilm_absent_counter.pop(uid, None)

    coordinator.async_add_listener(_nilm_updated)

    # Dynamically add per-inverter profile sensors and clipping binary sensors
    registered_inv_ids: set = set(_existing_uids)

    @callback
    def _inverters_updated():
        new_ents = []
        for inv in (coordinator.data or {}).get("inverter_data", []):
            eid = inv.get("entity_id", "")
            uid_sensor  = f"{entry.entry_id}_inv_profile_{eid}"
            uid_clip    = f"{entry.entry_id}_inv_clipping_{eid}"
            if uid_sensor not in registered_inv_ids:
                new_ents.append(CloudEMSInverterProfileSensor(coordinator, entry, eid))
                new_ents.append(CloudEMSInverterClippingBinarySensor(coordinator, entry, eid))
                registered_inv_ids.add(uid_sensor)
                registered_inv_ids.add(uid_clip)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_inverters_updated)

    # v1.20: Dynamically add per-room sensors when rooms are detected
    registered_room_ids: set = set(_existing_uids)

    @callback
    def _rooms_updated():
        new_ents = []
        room_data = (coordinator.data or {}).get("room_meter", {}).get("rooms", {})
        for room_name in room_data:
            uid = f"{entry.entry_id}_room_{room_name}"
            if uid not in registered_room_ids:
                new_ents.append(CloudEMSRoomMeterSensor(coordinator, entry, room_name))
                registered_room_ids.add(uid)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_rooms_updated)

    # Dynamically add per-zone climate sensors when zones are discovered
    registered_zone_climate_ids: set = set(_existing_uids)

    @callback
    def _zone_climate_updated():
        new_ents = []
        zm = getattr(coordinator, "_zone_climate", None)
        if not zm:
            return
        for zone_attrs in zm.get_zone_attrs():
            area_id   = zone_attrs.get("area") or zone_attrs.get("area_id", "")
            area_name = zone_attrs.get("area") or zone_attrs.get("area_name", area_id)
            uid = f"{entry.entry_id}_zone_climate_{area_id}"
            if uid not in registered_zone_climate_ids:
                new_ents.append(CloudEMSZoneClimateSensor(coordinator, entry, area_id, area_name))
                registered_zone_climate_ids.add(uid)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_zone_climate_updated)

    # ── v4.6.89: Per-boiler temperatuursensoren (recorder-opgeslagen) ─────────
    # sensor.cloudems_boiler_<slug>_temp — gebruikt door JS boiler card voor grafieken
    _registered_boiler_temp_ids: set = set(_existing_uids)

    @callback
    def _boiler_temps_updated():
        new_ents = []
        data = coordinator.data or {}
        all_boilers = list(data.get("boiler_status", []))
        for g in data.get("boiler_groups_status", []):
            all_boilers.extend(g.get("boilers", []))
        seen = set()
        for b in all_boilers:
            eid   = b.get("entity_id", "")
            label = b.get("label", eid.split(".")[-1])
            if not eid or eid in seen:
                continue
            seen.add(eid)
            slug_eid   = eid.split(".")[-1].replace("-", "_")
            slug_label = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            uid_temp  = f"{entry.entry_id}_boiler_temp_{slug_eid}"
            uid_power = f"{entry.entry_id}_boiler_power_{slug_label}"
            if uid_temp not in _registered_boiler_temp_ids:
                new_ents.append(CloudEMSBoilerTempSensor(coordinator, entry, eid, label))
                _registered_boiler_temp_ids.add(uid_temp)
            if uid_power not in _registered_boiler_temp_ids:
                new_ents.append(CloudEMSBoilerPowerSensor(coordinator, entry, eid, label))
                _registered_boiler_temp_ids.add(uid_power)
        if new_ents:
            async_add_entities(new_ents)

    coordinator.async_add_listener(_boiler_temps_updated)
    _boiler_temps_updated()  # meteen registreren als boilers al bekend zijn

    # ── v4.3.6: Shutter override countdown sensoren (1 per rolluik) ──────────
    _cfg_all2 = {**entry.data, **entry.options}
    shutter_cfgs = _cfg_all2.get("shutter_configs", [])
    # Gebruik shutter_count > 0 als guard — shutter_enabled wordt niet altijd gezet
    # vanuit de config flow maar shutter_configs aanwezig = rolluiken geconfigureerd.
    if shutter_cfgs:
        shutter_override_entities = [
            CloudEMSShutterOverrideSensor(coordinator, entry, sc)
            for sc in shutter_cfgs
            if sc.get("entity_id")
        ]
        if shutter_override_entities:
            async_add_entities(shutter_override_entities, update_before_add=False)
        # v4.6.157: leer-voortgang sensoren (1 per rolluik)
        shutter_learn_entities = [
            CloudEMSShutterLearnProgressSensor(coordinator, entry, sc)
            for sc in shutter_cfgs
            if sc.get("entity_id")
        ]
        if shutter_learn_entities:
            async_add_entities(shutter_learn_entities, update_before_add=False)

        # v4.6.456: windsnelheid sensor (leest van ShutterController)
        async_add_entities([CloudEMSWindsnelheidSensor(coordinator, entry)], update_before_add=False)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME, manufacturer=MANUFACTURER,
        model=f"CloudEMS v{VERSION}", sw_version=VERSION,
        configuration_url=WEBSITE,
        suggested_area="CloudEMS",
    )

# Alias voor gebruik door nieuwe sensoren
def main_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Hoofd-device (CloudEMS integratie)."""
    return _device_info(entry)
# sub_device_info is geïmporteerd uit sub_devices.py


# ═══════════════════════════════════════════════════════════════════════════════
# Core sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    _attr_name = "CloudEMS Grid · Net Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_power"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        # BUG FIX: use `is not None` so value 0 is returned correctly (or → falsy on 0)
        v = d.get("power_w")
        if v is not None:
            return v
        return d.get("grid_power_w", 0)

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "solar_power_w":   d.get("solar_power", 0),
            "import_power_w":  d.get("import_power_w", 0),
            "export_power_w":  d.get("export_power_w", 0),
            "solar_surplus_w": d.get("solar_surplus_w", 0),
            "ev_current_a":    d.get("ev_decision", {}).get("target_current_a", 0),
        }


class CloudEMSHomeLoadSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """Berekend huisverbruik — solar + grid_import - grid_export ± batterij.

    Gebruikt CloudEMS-eigen EMA-gefilterde waarden zodat vertraagde cloud-batterij
    (bv. Zonneplan Nexus ~60s vertraging) het dashboard niet verstoort.
    """
    _attr_name = "CloudEMS · Huisverbruik"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:home-lightning-bolt"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_house_load"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        v = d.get("house_load_w")
        return round(v, 1) if v is not None else None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "solar_w":        d.get("solar_power_w", 0),
            "import_w":       d.get("import_power_w", 0),
            "export_w":       d.get("export_power_w", 0),
            "battery_w":      d.get("battery_providers", {}).get("total_power_w", 0),
        }


class CloudEMSHomeRestSensor(CoordinatorEntity, SensorEntity):
    """Resterend huisverbruik voor de flow kaart.

    Berekening (Kirchhoff):
        REST = ZON + NET_netto - ACCU_netto - BOILER - EV - EBIKE - POOL

    Dit is het verbruik dat niet door een eigen CloudEMS-module wordt beheerd.
    Wordt gebruikt door cloudems-flow-card als THUIS-node zodat de som klopt.
    """
    _attr_name      = "CloudEMS · Huis Rest Verbruik"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon      = "mdi:home-minus"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_home_rest"
        self.entity_id = "sensor.cloudems_home_rest"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @staticmethod
    def _boiler_w(data: dict) -> float:
        boilers = data.get("boiler_status", [])
        return sum(float(b.get("power_w") or 0) for b in boilers)

    @staticmethod
    def _ev_w(data: dict) -> float:
        ev = data.get("ev_session", {})
        if ev.get("session_active"):
            return float(ev.get("session_current_a") or 0) * 230.0
        return 0.0

    @staticmethod
    def _ebike_w(data: dict) -> float:
        mm = data.get("micro_mobility")
        if not mm or not isinstance(mm, dict):
            return 0.0
        return sum(float(s.get("power_w", 0)) for s in mm.get("active_sessions", []))

    @staticmethod
    def _pool_w(data: dict) -> float:
        pool = data.get("pool", {}) or {}
        return float(pool.get("filter_power_w") or 0) + float(pool.get("heat_power_w") or 0)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        # v4.6.169: gebruik coordinator house_power (Kirchhoff-balancer) als die beschikbaar is.
        # De sensor deed voorheen een eigen herberekening die negatief kon worden (→ 0)
        # bij grote batterijlading, ook als het huisverbruik reëel was.
        house_w = d.get("house_power")
        if house_w is not None:
            # Trek beheerde apparaten eraf zodat "rest" = onbeheerd verbruik
            rest = float(house_w) \
                   - self._boiler_w(d) \
                   - self._ev_w(d) \
                   - self._ebike_w(d) \
                   - self._pool_w(d)
            return round(max(0.0, rest), 1)
        # Fallback als balancer nog niet beschikbaar is (eerste seconden na herstart)
        solar_w = float(d.get("solar_power_w", 0) or 0)
        grid_w  = float(d.get("grid_power_w",  0) or 0)
        bat_w   = sum(float(b.get("power_w") or 0) for b in (d.get("batteries") or []))
        rest = solar_w + grid_w - bat_w \
               - self._boiler_w(d) \
               - self._ev_w(d) \
               - self._ebike_w(d) \
               - self._pool_w(d)
        return round(max(0.0, rest), 1)

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        solar_w = float(d.get("solar_power_w", 0) or 0)
        grid_w  = float(d.get("grid_power_w",  0) or 0)
        bat_w   = sum(float(b.get("power_w") or 0) for b in (d.get("batteries") or []))
        boiler  = self._boiler_w(d)
        ev      = self._ev_w(d)
        ebike   = self._ebike_w(d)
        pool    = self._pool_w(d)
        return {
            "solar_w":   round(solar_w, 1),
            "grid_w":    round(grid_w, 1),
            "battery_w": round(bat_w, 1),
            "boiler_w":  round(boiler, 1),
            "ev_w":      round(ev, 1),
            "ebike_w":   round(ebike, 1),
            "pool_w":    round(pool, 1),
            "total_managed_w": round(boiler + ev + ebike + pool, 1),
        }


class CloudEMSPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Energy · Price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_price"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("energy_price", {}).get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            "is_negative":       ep.get("is_negative", False),
            "min_today":         ep.get("min_today"),
            "max_today":         ep.get("max_today"),
            "avg_today":         ep.get("avg_today"),
            "next_hours":        ep.get("next_hours", []),
            "cheapest_hour_1":   ep.get("cheapest_hour_1"),
            "cheapest_hour_2":   ep.get("cheapest_hour_2"),
            "cheapest_hour_3":   ep.get("cheapest_hour_3"),
            "cheapest_2h_start": ep.get("cheapest_2h_start"),
            "cheapest_3h_start": ep.get("cheapest_3h_start"),
            "cheapest_4h_start": ep.get("cheapest_4h_start"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NEW v1.4.1 — Insights + Decision log + Boiler
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInsightsSensor(CoordinatorEntity, SensorEntity):
    """Text sensor: human-readable insights and advice (inzicht & advies)."""
    _attr_name = "CloudEMS Energy · Insights"
    _attr_icon = "mdi:lightbulb-on"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_insights"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        text = data.get("insights", "")
        # If coordinator has no data yet: show helpful startup message, not "unavailable"
        if not data:
            return "⏳ CloudEMS start op — even geduld..."
        if not text:
            return "✅ Bezig met leren — over enkele minuten verschijnen hier tips."
        # HA state max 255 chars — show first tip only
        if " | " in text:
            return text.split(" | ")[0][:255]
        return text[:255]

    @property
    def extra_state_attributes(self):
        text = (self.coordinator.data or {}).get("insights", "")
        tips = text.split(" | ") if text else []
        return {
            "all_tips":   tips,
            "tip_count":  len(tips),
            "full_text":  text,
        }


class CloudEMSDecisionLogSensor(CoordinatorEntity, SensorEntity):
    """Text sensor: why CloudEMS dimmed solar / switched devices."""
    _attr_name = "CloudEMS System · Decision Log"
    _attr_icon  = "mdi:text-box-multiple"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_attribution = ATTRIBUTION

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_decision_log"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        log = (self.coordinator.data or {}).get("decision_log", [])
        if log:
            return log[0].get("message","")[:255]
        return "Geen acties"

    @property
    def extra_state_attributes(self):
        log = (self.coordinator.data or {}).get("decision_log", [])
        return {
            "last_10": log[:10],
            "count":   len(log),
        }


class CloudEMSBoilerStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor: boiler/socket controller status."""
    _attr_name = "CloudEMS Boiler · Status"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_boiler_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        boilers = (self.coordinator.data or {}).get("boiler_status", [])
        on_count = sum(1 for b in boilers if b.get("is_on"))
        # Voeg temp toe aan state zodat HA altijd een WebSocket update stuurt
        temps = [round(b["temp_c"], 1) for b in boilers if b.get("temp_c") is not None]
        temp_str = f" · {temps[0]}°C" if temps else ""
        return f"{on_count}/{len(boilers)} aan{temp_str}"

    @property
    def extra_state_attributes(self):
        data    = self.coordinator.data or {}
        boilers = data.get("boiler_status", [])
        groups  = data.get("boiler_groups_status", [])
        on      = [b for b in boilers if b.get("is_on")]
        # Modus-samenvatting per groep
        mode_summary = {g["name"]: g["mode"] for g in groups} if groups else {}
        return {
            "boilers":        boilers,
            "groups":         groups,
            "mode_summary":   mode_summary,
            "cascade_active": len(groups) > 0,
            "weekly_budget":  data.get("boiler_weekly_budget", {}),
            "p1_direct_active": data.get("boiler_p1_active", False),
            "log":            [(d["ts"], d["message"]) for d in
                               data.get("decision_log", [])
                               if d.get("category") == "boiler"][:5],
            "_seq":           getattr(self.coordinator, "_coordinator_tick", 0),
        }


class CloudEMSEnergyDemandSensor(CoordinatorEntity, SensorEntity):
    """sensor.cloudems_energy_demand — verwachte energievraag per subsysteem."""
    _attr_name  = "CloudEMS Energy Demand"
    _attr_icon  = "mdi:lightning-bolt-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_demand"
        self.entity_id = "sensor.cloudems_energy_demand"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        d = (self.coordinator.data or {}).get("energy_demand", {})
        total = d.get("total_kwh", 0.0)
        count = d.get("count", 0)
        # Altijd veranderend via coordinator tick zodat WebSocket updates komen
        tick  = getattr(self.coordinator, "_coordinator_tick", 0)
        return f"{total:.2f}:{count}:{tick % 120}"

    @property
    def extra_state_attributes(self) -> dict:
        d = (self.coordinator.data or {}).get("energy_demand", {})
        return d or {"subsystems": [], "total_kwh": 0.0}


class CloudEMSClimateEpexStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor: Climate EPEX Compensatie status."""
    _attr_name = "CloudEMS Klimaat EPEX Status"
    _attr_icon = "mdi:thermostat-auto"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate_epex_status"
        self.entity_id = "sensor.cloudems_climate_epex_status"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        devices = (self.coordinator.data or {}).get("climate_epex_status", [])
        if not devices:
            return "inactief"
        active = [d for d in devices if d.get("is_on")]
        offsets = [d for d in devices if abs(d.get("applied_offset", 0)) > 0.05]
        if offsets:
            modes = set(d["mode"] for d in offsets)
            if "cheap" in modes:
                return f"{len(active)} actief · voorladen"
            elif "dear" in modes:
                return f"{len(active)} actief · bezuinigen"
        return f"{len(active)}/{len(devices)} actief"

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        devices = data.get("climate_epex_status", [])
        return {
            "devices":      devices,
            "total_power_w": data.get("climate_epex_power_w", 0.0),
            "device_count": len(devices),
            "active_count": sum(1 for d in devices if d.get("is_on")),
            "offset_active": any(abs(d.get("applied_offset", 0)) > 0.05 for d in devices),
        }


class CloudEMSBoilerTempSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """v4.6.89: Per-boiler temperatuursensor — opgeslagen in recorder voor grafieken.

    entity_id: sensor.cloudems_boiler_<slug>_temp
    Gebruik: JS boiler card haalt history op via /api/history op deze sensor.
    """
    _attr_device_class  = SensorDeviceClass.TEMPERATURE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coord, entry, boiler_entity_id: str, boiler_label: str):
        super().__init__(coord)
        self._entry          = entry
        self._boiler_eid     = boiler_entity_id
        slug = re.sub(r"[^a-z0-9]+", "_", boiler_label.lower()).strip("_")
        self._attr_name       = f"CloudEMS Boiler · {boiler_label} · Temperatuur"
        self._attr_unique_id  = f"{entry.entry_id}_boiler_temp_{slug}"
        self.entity_id        = f"sensor.cloudems_boiler_{slug}_temp"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        boilers = (self.coordinator.data or {}).get("boiler_status", [])
        for b in boilers:
            if b.get("entity_id") == self._boiler_eid:
                v = b.get("temp_c")
                return round(float(v), 1) if v is not None else None
        # Ook in groepen zoeken
        for g in (self.coordinator.data or {}).get("boiler_groups_status", []):
            for b in g.get("boilers", []):
                if b.get("entity_id") == self._boiler_eid:
                    v = b.get("temp_c")
                    return round(float(v), 1) if v is not None else None
        return None



class CloudEMSBoilerPowerSensor(CoordinatorEntity, SensorEntity):
    """v4.6.89: Per-boiler vermogensensor — opgeslagen in recorder voor grafieken.

    entity_id: sensor.cloudems_boiler_<slug>_power
    """
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coord, entry, boiler_entity_id: str, boiler_label: str):
        super().__init__(coord)
        self._entry      = entry
        self._boiler_eid = boiler_entity_id
        self._last_nonzero_w: float | None = None  # cache laatste bekende vermogen
        slug = re.sub(r"[^a-z0-9]+", "_", boiler_label.lower()).strip("_")
        self._attr_name       = f"CloudEMS Boiler · {boiler_label} · Vermogen"
        self._attr_unique_id  = f"{entry.entry_id}_boiler_power_{slug}"
        self.entity_id        = f"sensor.cloudems_boiler_{slug}_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    def _get_boiler(self) -> dict | None:
        data = self.coordinator.data or {}
        for b in data.get("boiler_status", []):
            if b.get("entity_id") == self._boiler_eid:
                return b
        for g in data.get("boiler_groups_status", []):
            for b in g.get("boilers", []):
                if b.get("entity_id") == self._boiler_eid:
                    return b
        return None

    @property
    def native_value(self):
        b = self._get_boiler()
        if b is None:
            return self._last_nonzero_w  # Ariston 429 — toon laatste bekende waarde
        # v4.6.170: gebruik ALLEEN current_power_w (echte meting).
        # power_w is het geleerde nominale vermogen — dat nooit tonen als huidig vermogen.
        v = b.get("current_power_w")
        if v is None:
            # Geen meting beschikbaar — toon laatste bekende waarde uit cache
            return self._last_nonzero_w
        val = round(float(v), 0)
        if val > 0:
            self._last_nonzero_w = val  # cache bijwerken voor volgende unavailable periode
        return val



class CloudEMSBuitenTempSensor(CoordinatorEntity, SensorEntity):
    """v4.6.89: Buitentemperatuur — eigen recorder-sensor zodat data altijd beschikbaar
    blijft ook als de externe weer-entity tijdelijk unavailable is.

    entity_id: sensor.cloudems_buiten_temp
    Waarde: gelezen uit thermal_model.last_outside_temp_c (coordinator cached waarde).
    """
    _attr_name        = "CloudEMS Buitentemperatuur"
    _attr_device_class  = SensorDeviceClass.TEMPERATURE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_buiten_temp"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self):
        t = (self.coordinator.data or {}).get("thermal_model", {})
        v = t.get("last_outside_temp_c")
        if v is not None:
            return round(float(v), 1)
        # thermal_model is de enige betrouwbare bron — outdoor_temp_c bestaat
        # niet in boiler_groups_status boiler dicts, dus geen fallback nodig.
        return None


class CloudEMSPoolWaterTempSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """v4.6.89: Zwembad watertemperatuur — eigen recorder-sensor.

    entity_id: sensor.cloudems_pool_water_temp
    Alleen actief als zwembad geconfigureerd is.
    """
    _attr_name        = "CloudEMS Zwembad · Watertemperatuur"
    _attr_device_class  = SensorDeviceClass.TEMPERATURE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:pool-thermometer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pool_water_temp"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_POOL)

    @property
    def native_value(self):
        pool = (self.coordinator.data or {}).get("pool", {})
        v = pool.get("water_temp_c")
        return round(float(v), 1) if v is not None else None


class CloudEMSEVPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """v4.6.89: Actueel EV-laadvermogen — eigen recorder-sensor.

    entity_id: sensor.cloudems_ev_laad_power
    Waarde: ev_power uit coordinator data (W, positief = laden).
    """
    _attr_name        = "CloudEMS EV · Laadvermogen"
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_laad_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_EV)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        ev = data.get("ev_session", {}) or {}
        if ev.get("session_active"):
            amps = float(ev.get("session_current_a") or 0)
            return round(amps * 230.0, 0)
        return 0.0

    @property
    def extra_state_attributes(self) -> dict:
        ev = (self.coordinator.data or {}).get("ev_session", {}) or {}
        # evcc-inspired: sessie + statistieken
        attrs = {
            # Actieve sessie
            "session_active":       ev.get("session_active", False),
            "session_current_a":    ev.get("session_current_a"),
            "session_kwh":          ev.get("session_kwh_so_far"),
            "session_cost_eur":     ev.get("session_cost_so_far"),
            "session_solar_pct":    ev.get("session_solar_pct"),
            "session_solar_kwh":    ev.get("session_solar_kwh"),
            "session_co2_g":        ev.get("session_co2_g"),
            "session_price_per_kwh": ev.get("session_price_per_kwh"),
            # Model
            "model_ready":          ev.get("model_ready", False),
            "predicted_kwh":        ev.get("predicted_kwh"),
            "typical_start_hour":   ev.get("typical_start_hour"),
            "typical_weekdays":     ev.get("typical_weekdays", []),
            # Statistieken (evcc-stijl: total/365d/30d)
            "stats":                ev.get("stats", {}),
            # Plan
            "plan_status": None,
        }
        # Plan status van dynamic_ev_charger
        try:
            _dyn_ev = getattr(self.coordinator, "_dynamic_ev_charger", None)
            if _dyn_ev and hasattr(_dyn_ev, "get_plan_status"):
                attrs["plan_status"] = _dyn_ev.get_plan_status()
                attrs["smart_cost_limit_eur"] = getattr(_dyn_ev, "_smart_cost_limit", None)
        except Exception:
            pass
        return _trim_attrs(attrs)


class CloudEMSPoolStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor: slimme zwembad controller status (filter + warmtepomp)."""
    _attr_name = "CloudEMS Zwembad · Status"
    _attr_icon = "mdi:pool"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pool_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_POOL)

    @property
    def native_value(self) -> str:
        pool = (self.coordinator.data or {}).get("pool", {})
        if not pool:
            return "Niet geconfigureerd"
        parts = []
        if pool.get("filter_is_on"):
            parts.append("Filter ▶")
        if pool.get("heat_is_on"):
            parts.append("Verwarming ▶")
        if not parts:
            parts.append("Standby")
        return " | ".join(parts)

    @property
    def extra_state_attributes(self) -> dict:
        pool = (self.coordinator.data or {}).get("pool", {})
        cfg  = (self.coordinator._config.get("pool") or {})
        return {
            "filter_is_on":        pool.get("filter_is_on", False),
            "filter_mode":         pool.get("filter_mode", "off"),
            "filter_reason":       pool.get("filter_reason", ""),
            "filter_hours_today":  pool.get("filter_hours_today", 0.0),
            "filter_target_hours": pool.get("filter_target_hours", 4.0),
            "filter_power_w":      pool.get("filter_power_w", 0),
            "heat_is_on":          pool.get("heat_is_on", False),
            "heat_mode":           pool.get("heat_mode", "off"),
            "heat_reason":         pool.get("heat_reason", ""),
            "water_temp_c":        pool.get("water_temp_c"),
            "heat_setpoint_c":     pool.get("heat_setpoint_c", 28.0),
            "heat_power_w":        pool.get("heat_power_w", 0),
            "uv_is_on":            pool.get("uv_is_on", False),
            "robot_is_on":         pool.get("robot_is_on", False),
            "advice":              pool.get("advice", ""),
            # Entity ids exposed for dashboard conditional checks
            "filter_entity_id":    cfg.get("filter_entity", ""),
            "heat_entity_id":      cfg.get("heat_entity", ""),
            "temp_entity_id":      cfg.get("temp_entity", ""),
            # Geleerde vermogenswaardes (zichtbaar voor diagnostiek)
            "learned_filter_w":    getattr(self.coordinator._pool_ctrl, "_learned_filter_w", None)
                                   if getattr(self.coordinator, "_pool_ctrl", None) else None,
            "learned_heat_w":      getattr(self.coordinator._pool_ctrl, "_learned_heat_w", None)
                                   if getattr(self.coordinator, "_pool_ctrl", None) else None,
        }



# ═══════════════════════════════════════════════════════════════════════════════
# Lamp Circulation sensor — v1.25.9
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSLampCirculationSensor(CoordinatorEntity, SensorEntity):
    """Sensor: intelligente lampenbeveiliging & energiebesparing status."""
    _attr_name = "CloudEMS Lampcirculatie · Status"
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lamp_circulation_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_LAMP)

    @property
    def native_value(self) -> str:
        lc = (self.coordinator.data or {}).get("lamp_circulation", {})
        if not lc:
            return "Niet geconfigureerd"
        if lc.get("test_mode"):
            return "Test actief"
        mode_labels = {
            "circulation":   "Beveiliging actief",
            "night_off":     "Nachtmodus",
            "energy_saving": "Energiebesparing",
            "off":           "Standby",
        }
        return mode_labels.get(lc.get("mode", "off"), lc.get("mode", "off"))

    @property
    def extra_state_attributes(self) -> dict:
        lc = (self.coordinator.data or {}).get("lamp_circulation", {})
        return {
            "enabled":              lc.get("enabled", True),
            "active":               lc.get("active", False),
            "test_mode":            lc.get("test_mode", False),
            "mode":                 lc.get("mode", "off"),
            "reason":               lc.get("reason", ""),
            "lamps_on":             lc.get("lamps_on", []),
            "lamps_on_labels":      lc.get("lamps_on_labels", []),
            "next_switch_in_s":     lc.get("next_switch_in_s", 0),
            "lamps_registered":     lc.get("lamps_registered", 0),
            "lamps_active":         lc.get("lamps_active", 0),
            "lamps_excluded":       lc.get("lamps_excluded", 0),
            "lamps_with_phase":     lc.get("lamps_with_phase", 0),
            "occupancy_state":      lc.get("occupancy_state", "unknown"),
            "occupancy_confidence": lc.get("occupancy_confidence", 0.0),
            "advice":               lc.get("advice", ""),
            "phase_tip":            lc.get("phase_tip", ""),
            "mimicry_active":       lc.get("mimicry_active", False),
            "neg_price_active":     lc.get("neg_price_active", False),
            "sun_derived_night":    lc.get("sun_derived_night", False),
            "lamp_phases":          lc.get("lamp_phases", []),
            # v4.6.445: automation status meegeven zodat JS card beide kan tonen
            "automation":           (self.coordinator.data or {}).get("lamp_automation", {}),
        }




class CloudEMSLampAutomationSensor(CoordinatorEntity, SensorEntity):
    """Sensor: slimme verlichting automatisering status."""
    _attr_name = "CloudEMS Slimme Verlichting · Status"
    _attr_icon = "mdi:home-lightbulb"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lamp_automation_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_LAMP)

    @property
    def native_value(self) -> str:
        la = (self.coordinator.data or {}).get("lamp_automation", {})
        if not la or not la.get("enabled"):
            return "Niet ingeschakeld"
        if la.get("away"):
            return "Afwezig — vergeten lichten bewaken"
        if la.get("asleep"):
            return "Slaapstand"
        auto_cnt = sum(1 for l in la.get("lamps", []) if l.get("mode") == "auto")
        semi_cnt = sum(1 for l in la.get("lamps", []) if l.get("mode") == "semi")
        return f"Actief — {auto_cnt} auto, {semi_cnt} semi"

    @property
    def extra_state_attributes(self) -> dict:
        la = (self.coordinator.data or {}).get("lamp_automation", {})
        return {
            "enabled":    la.get("enabled", False),
            "home":       la.get("home", False),
            "away":       la.get("away", False),
            "asleep":     la.get("asleep", False),
            "actions":    la.get("actions", [])[-10:],  # laatste 10 acties
            "lamps":      la.get("lamps", []),
        }


class CloudEMSPhaseCurrentSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = ICON_LIMITER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Current"
        self._attr_unique_id = f"{entry.entry_id}_current_{phase.lower()}"
        # v4.5.4: explicit entity_id — dashboard uses sensor.cloudems_current_l1/l2/l3
        self.entity_id = f"sensor.cloudems_current_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        a = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("current_a")
        return round(a, 3) if a is not None else None

    @property
    def extra_state_attributes(self):
        pd = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{})
        return {
            "max_current_a":    pd.get("max_import_a"),
            "utilisation_pct":  pd.get("utilisation_pct"),
            "limited":          pd.get("limited", False),
            "power_w":          pd.get("power_w"),
            "voltage_v":        pd.get("voltage_v"),
            "derived_from":     pd.get("derived_from","direct"),
        }


class CloudEMSPhaseSignedCurrentSensor(CoordinatorEntity, SensorEntity):
    """
    Gesigneerde fasestroom (A).

    Positief = import, negatief = export.
    DSMR4 P1-meters rapporteren current_a altijd positief — dit sensor
    leidt het teken af uit power_w (negatief = export).

    Berekening (prioriteit):
      1. power_w / voltage_v  — meest nauwkeurig als voltage bekend is
      2. current_a * sign(power_w) — als alleen DSMR current beschikbaar is
      3. None — onvoldoende data
    """
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Signed Current"
        self._attr_unique_id = f"{entry.entry_id}_signed_current_{phase.lower()}"
        self.entity_id = f"sensor.cloudems_signed_current_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        # v4.6.512: lees direct uit de limiter voor realtime waarden
        # (coordinator.data["phases"] wordt maar elke 10s bijgewerkt)
        limiter = getattr(self.coordinator, "_limiter", None)
        if limiter:
            pd = limiter.get_phase_summary().get(self._phase, {})
        else:
            pd = (self.coordinator.data or {}).get("phases", {}).get(self._phase, {})

        current_a = pd.get("current_a")
        power_w   = pd.get("power_w")

        if current_a is None:
            return None

        # Sanity: >100A is opstartartefact
        if abs(current_a) > 100:
            return None

        # current_a is al gesigneerd door coordinator (import=+, export=-)
        # Alleen als power_w beschikbaar is als extra richtingscheck
        if power_w is not None and abs(power_w) > 5:
            sign = -1 if power_w < 0 else 1
            return round(abs(current_a) * sign, 2)

        return round(current_a, 2)

    @property
    def extra_state_attributes(self):
        pd = (self.coordinator.data or {}).get("phases", {}).get(self._phase, {})
        power_w   = pd.get("power_w")
        voltage_v = pd.get("voltage_v")
        current_a = pd.get("current_a")
        method = "p_div_v" if (voltage_v and voltage_v > 10) else ("abs_times_sign" if current_a is not None else "none")
        return {
            "power_w":    power_w,
            "voltage_v":  voltage_v,
            "current_a":  current_a,
            "method":     method,
            "is_export":  power_w < 0 if power_w is not None else None,
        }


class CloudEMSPhaseVoltageSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_icon = ICON_VOLTAGE

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Voltage"
        self._attr_unique_id = f"{entry.entry_id}_voltage_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        v = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("voltage_v")
        return round(v, 1) if v is not None else None


class CloudEMSPhasePowerSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Power"
        self._attr_unique_id = f"{entry.entry_id}_power_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        w = (self.coordinator.data or {}).get("phases",{}).get(self._phase,{}).get("power_w")
        return round(w, 1) if w is not None else None


class CloudEMSPhaseBalanceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · Phase Imbalance"
    _attr_icon  = "mdi:scale-unbalanced"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_phase_balance"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("phase_balance",{}).get("imbalance_a")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("phase_balance", {})


# ═══════════════════════════════════════════════════════════════════════════════
# NEW v1.4.1 — Per-inverter sensor (peak power + clipping)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInverterSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """
    Shows current PV output, learned peak power, clipping status,
    estimated Wp, utilisation — for each inverter.
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, inv_cfg: dict):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_cfg.get("entity_id","")
        self._label  = inv_cfg.get("label", self._inv_id)
        self._attr_name = f"CloudEMS Solar · {self._label}"
        self._attr_unique_id = f"{entry.entry_id}_inverter_{self._inv_id}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    def _inv_data(self) -> dict:
        for inv in (self.coordinator.data or {}).get("inverter_data", []):
            if inv.get("entity_id") == self._inv_id:
                return inv
        return {}

    @property
    def native_value(self):
        d = self._inv_data()
        return d.get("current_w")

    @property
    def extra_state_attributes(self):
        d = self._inv_data()
        return {
            "peak_power_w":        d.get("peak_w", 0),
            "estimated_wp":        d.get("estimated_wp", 0),
            "utilisation_pct":     d.get("utilisation_pct", 0),
            "clipping":            d.get("clipping", False),
            "clipping_ceiling_w":  d.get("clipping_ceiling_w"),
            "phase":               d.get("phase", "unknown"),
            "phase_certain":       d.get("phase_certain", False),
            "phase_display":       d.get("phase_display"),
            "phase_confidence":    d.get("phase_confidence", 0.0),
            "phase_provisional":   d.get("phase_provisional", True),
            "samples":             d.get("samples", 0),
            "confident":           d.get("confident", False),
            # Learning progress — how far along the self-learning cycle is (%)
            "learn_confidence_pct": d.get("orientation_learning_pct", 0),
            "orientation_learned":  d.get("orientation_confident", False),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Forecast + Peak shaving
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSForecastSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Solar · PV Forecast Today"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_today"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("pv_forecast_today_kwh")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return _trim_attrs({
            "hourly":   d.get("pv_forecast_hourly", []),
            "actual_hourly_kwh": d.get("pv_today_hourly_kwh", [0.0] * 24),  # v4.6.492
            "minutes_into_hour": __import__("datetime").datetime.now().minute,  # v4.6.506
            "profiles": [
                {k: v for k, v in p.items() if k in {"entity_id", "label", "peak_w", "today_kwh"}}
                for p in d.get("inverter_profiles", [])
            ],
        })


class CloudEMSForecastTomorrowSensor(CoordinatorEntity, SensorEntity):
    """PV forecast for tomorrow in kWh — with per-hour breakdown."""
    _attr_name = "CloudEMS Solar · PV Forecast Tomorrow"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_tomorrow"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("pv_forecast_tomorrow_kwh")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return _trim_attrs({
            "hourly_tomorrow": d.get("pv_forecast_hourly_tomorrow", []),
            "profiles": [
                {k: v for k, v in p.items() if k in {"entity_id", "label", "peak_w", "tomorrow_kwh"}}
                for p in d.get("inverter_profiles", [])
            ],
        })


class CloudEMSForecastPeakSensor(CoordinatorEntity, SensorEntity):
    """Peak PV power expected today in Watt (best single hour)."""
    _attr_name = "CloudEMS Solar · PV Forecast Peak Today"
    _attr_icon  = ICON_FORECAST
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_peak_today"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        hourly = (self.coordinator.data or {}).get("pv_forecast_hourly", [])
        if not hourly:
            return None
        # hourly is a list of dicts with key "wh" or a list of float values
        try:
            values = [h["wh"] if isinstance(h, dict) else h for h in hourly]
            return max(values) if values else None
        except (KeyError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {"hourly": d.get("pv_forecast_hourly", [])}


class CloudEMSGridCongestionSensor(CoordinatorEntity, SensorEntity):
    """Grid utilisation percentage — triggers congestion alerts."""
    _attr_name  = "CloudEMS Grid · Congestion Utilisation"
    _attr_icon  = "mdi:transmission-tower-export"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_congestion"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("congestion", {})
        return d.get("utilisation_pct")

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("congestion", {})
        return {
            "active":          d.get("active", False),
            "import_w":        d.get("import_w"),
            "threshold_w":     d.get("threshold_w"),
            "actions":         d.get("actions", []),
            "today_events":    d.get("today_events", 0),
            "month_events":    d.get("month_events", 0),
            "peak_today_w":    d.get("peak_today_w"),
            "monthly_summary": d.get("monthly_summary", []),
        }


class CloudEMSBatteryHealthSensor(CoordinatorEntity, SensorEntity):
    """Battery State of Health (SoH) in percent."""
    _attr_name  = "CloudEMS Battery · State of Health"
    _attr_icon  = "mdi:battery-heart"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_soh"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("battery_degradation", {})
        return d.get("soh_pct")

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("battery_degradation", {})
        return {
            "capacity_kwh":   d.get("capacity_kwh"),
            "total_cycles":   d.get("total_cycles"),
            "cycles_per_day": d.get("cycles_per_day"),
            "alert_level":    d.get("alert_level"),
            "alert_message":  d.get("alert_message"),
            "soc_low_events": d.get("soc_low_events"),
            "days_tracked":   d.get("days_tracked"),
        }



class CloudEMSBatterySocSensor(CoordinatorEntity, SensorEntity):
    """Battery State of Charge (SOC) in percent.

    Leest primair uit multi-battery data (batteries[0].soc_pct).
    Valt terug op battery_schedule.soc_pct voor legacy single-battery configuraties.
    """
    _attr_name  = "CloudEMS Battery · SoC"
    _attr_icon  = "mdi:battery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_soc"
        # v4.5.4: explicit entity_id — dashboard uses sensor.cloudems_battery_so_c
        self.entity_id = "sensor.cloudems_battery_so_c"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        batteries = data.get("batteries", [])
        if batteries:
            soc = batteries[0].get("soc_pct")
            if soc is not None:
                return round(float(soc), 1)
        soc = data.get("battery_schedule", {}).get("soc_pct")
        if soc is not None:
            return round(float(soc), 1)
        return None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        batteries = data.get("batteries", [])
        attrs: dict = {}
        if batteries:
            b = batteries[0]
            attrs["label"]        = b.get("label")
            attrs["power_w"]      = b.get("power_w")
            attrs["action"]       = b.get("action")
            attrs["reason"]       = b.get("reason")
            attrs["capacity_kwh"] = b.get("capacity_kwh")
        if len(batteries) > 1:
            attrs["all_batteries"] = [
                {"label": bx.get("label"), "soc_pct": bx.get("soc_pct"),
                 "power_w": bx.get("power_w"), "action": bx.get("action")}
                for bx in batteries
            ]
        return attrs

# ═══════════════════════════════════════════════════════════════════════════════
# v4.5.131: Batterij totaal vermogen + kWh accumulatie (alle batterijen t/m 9)
# sensor.cloudems_battery_power  →  W  (positief=laden, negatief=ontladen)
# Attributes: charge_kwh_today, discharge_kwh_today, batteries[]
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBatteryPowerSensor(CoordinatorEntity, SensorEntity):
    """Totaal laad-/ontlaadvermogen van alle geconfigureerde batterijen (max 9).

    State:
        Positief (W)  → laden
        Negatief (W)  → ontladen

    Attributes:
        charge_w            — positief laadvermogen (0 als ontladen)
        discharge_w         — positief ontlaadvermogen (0 als laden)
        charge_kwh_today    — gecumuleerd geladen kWh vandaag
        discharge_kwh_today — gecumuleerd ontladen kWh vandaag
        batteries           — lijst per batterij met label, power_w, soc_pct, action
        battery_count       — aantal actieve batterijen
    """
    _attr_name       = "CloudEMS Battery · Totaal vermogen"
    _attr_icon       = "mdi:battery-charging"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    # kWh accumulatie — bijgehouden in geheugen, reset bij middernacht
    _DT_S = 10.0   # coordinator interval

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry             = entry
        self._attr_unique_id    = f"{entry.entry_id}_battery_power_total"
        self.entity_id          = "sensor.cloudems_battery_power"
        self._charge_kwh        = 0.0
        self._discharge_kwh     = 0.0
        self._last_day: int | None = None
        # v4.6.190: persistent store zodat kWh niet reset bij reload
        from homeassistant.helpers.storage import Store
        self._store = Store(coord.hass, 1, "cloudems_battery_kwh_today_v1")
        self._store_loaded = False

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)

    async def async_added_to_hass(self) -> None:
        """Herstel kWh na herstart vanuit persistent storage."""
        await super().async_added_to_hass()
        from homeassistant.util import dt as dt_util
        try:
            saved = await self._store.async_load()
            if saved and saved.get("day") == dt_util.now().day:
                self._charge_kwh    = float(saved.get("charge_kwh", 0))
                self._discharge_kwh = float(saved.get("discharge_kwh", 0))
                self._last_day      = saved["day"]
        except Exception:
            pass
        self._store_loaded = True

    def _accumulate(self, total_w: float) -> None:
        """Accumuleer kWh op basis van 10s-interval. Reset om middernacht."""
        from homeassistant.util import dt as dt_util
        today = dt_util.now().day
        if self._last_day is not None and self._last_day != today:
            self._charge_kwh    = 0.0
            self._discharge_kwh = 0.0
        self._last_day = today
        kwh = abs(total_w) * (self._DT_S / 3600.0) / 1000.0
        if total_w > 50:
            self._charge_kwh    += kwh
        elif total_w < -50:
            self._discharge_kwh += kwh
        # Sla elke minuut op (elke 6e cyclus van 10s)
        if not hasattr(self, '_save_tick'): self._save_tick = 0
        self._save_tick += 1
        if self._save_tick % 6 == 0 and self._store_loaded:
            self.coordinator.hass.async_create_task(self._store.async_save({
                "day": today,
                "charge_kwh": round(self._charge_kwh, 4),
                "discharge_kwh": round(self._discharge_kwh, 4),
            }))

    @property
    def native_value(self):
        data     = self.coordinator.data or {}
        bats     = data.get("batteries", [])
        total_w  = sum(float(b.get("power_w") or 0) for b in bats)
        # Fallback: battery_providers.total_power_w
        if not bats:
            total_w = float(data.get("battery_providers", {}).get("total_power_w") or 0)
        self._accumulate(total_w)
        return round(total_w, 0)

    @property
    def extra_state_attributes(self) -> dict:
        data    = self.coordinator.data or {}
        bats    = data.get("batteries", [])
        total_w = sum(float(b.get("power_w") or 0) for b in bats)
        if not bats:
            total_w = float(data.get("battery_providers", {}).get("total_power_w") or 0)
        charge_w    = round(total_w, 0) if total_w > 0 else 0
        discharge_w = round(abs(total_w), 0) if total_w < 0 else 0
        return {
            "charge_w":            charge_w,
            "discharge_w":         discharge_w,
            "charge_kwh_today":    round(self._charge_kwh, 3),
            "discharge_kwh_today": round(self._discharge_kwh, 3),
            "battery_count":       len(bats),
            "batteries": [
                {
                    "label":    b.get("label", f"Batterij {i+1}"),
                    "power_w":  b.get("power_w"),
                    "soc_pct":  b.get("soc_pct"),
                    "action":   b.get("action"),
                    "charging": bool(b.get("power_w") and float(b.get("power_w") or 0) > 50),
                    "discharging": bool(b.get("power_w") and float(b.get("power_w") or 0) < -50),
                }
                for i, b in enumerate(bats)
            ],
        }


class CloudEMSMonthlyPeakSensor(CoordinatorEntity, SensorEntity):
    """Peak grid import power this month — relevant for capacity tariffs (Belgium / NL 2025)."""
    _attr_name  = "CloudEMS Grid · Monthly Peak Import"
    _attr_icon  = ICON_PEAK
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_monthly_peak_import"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        ps = (self.coordinator.data or {}).get("peak_shaving", {})
        return ps.get("peak_month_w") or ps.get("peak_this_month_w")

    @property
    def extra_state_attributes(self):
        cong = (self.coordinator.data or {}).get("congestion", {})
        ps   = (self.coordinator.data or {}).get("peak_shaving", {})
        return {
            "peak_today_w":    ps.get("peak_today_w") or cong.get("peak_today_w"),
            "monthly_history": cong.get("monthly_summary", []),
        }


class CloudEMSSensorHintsSensor(CoordinatorEntity, SensorEntity):
    """Active sensor configuration hints — unconfigured PV, battery, phase sensors."""
    _attr_name  = "CloudEMS · Sensor Hints"
    _attr_icon  = "mdi:lightbulb-alert"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sensor_hints"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self):
        hints = (self.coordinator.data or {}).get("sensor_hints", [])
        active = [h for h in hints if not h.get("dismissed")]
        return len(active)

    @property
    def extra_state_attributes(self):
        hints = (self.coordinator.data or {}).get("sensor_hints", [])
        return {
            "hints":        hints,
            "active_count": sum(1 for h in hints if not h.get("dismissed")),
        }


class CloudEMSScaleInfoSensor(CoordinatorEntity, SensorEntity):
    """Power scale diagnostics — shows W/kW detection result per sensor."""
    _attr_name  = "CloudEMS · Power Scale Info"
    _attr_icon  = "mdi:scale"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scale_info"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        # Returns number of entities whose scale is confirmed (not pending)
        si = (self.coordinator.data or {}).get("scale_info", {})
        return sum(1 for v in si.values() if v.get("source") != "pending")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("scale_info", {})


class CloudEMSNILMDatabaseSensor(CoordinatorEntity, SensorEntity):
    """NILM database status — total signatures, community count, remote feed health."""
    _attr_name  = "CloudEMS NILM · DB"
    _attr_icon  = "mdi:database-check"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_db"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        stats = (self.coordinator.data or {}).get("nilm_db_stats", {})
        return stats.get("total")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("nilm_db_stats", {})


class CloudEMSPeakShavingSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Grid · Peak Shaving"
    _attr_icon  = ICON_PEAK
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_peak_shaving"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("peak_shaving",{}).get("peak_today_w")

    @property
    def extra_state_attributes(self):
        ps = (self.coordinator.data or {}).get("peak_shaving", {})
        return {
            "active":       ps.get("active", False),
            "limit_w":      ps.get("limit_w"),
            "headroom_w":   ps.get("headroom_w"),
            "peak_today_w": ps.get("peak_today_w"),
            "peak_month_w": ps.get("peak_month_w"),
            "history":      ps.get("peak_history", [])[:30],
            "last_action":  ps.get("action","none"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EPEX cheap-hour binary sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCheapHourBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:clock-check"

    def __init__(self, coord, entry, rank: int):
        super().__init__(coord)
        self._entry = entry
        self._rank  = rank
        self._attr_name = f"CloudEMS Energy · Cheapest {rank}h"
        self._attr_unique_id = f"{entry.entry_id}_cheap_hour_{rank}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def is_on(self) -> bool:
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return bool(ep.get(f"in_cheapest_{self._rank}h", False))

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return {
            f"hours":        ep.get(f"cheapest_{self._rank}h_hours", []),
            "current_price": ep.get("current"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NILM sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMStatsSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS NILM · Devices"
    _attr_icon  = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_stats"
        self.entity_id = "sensor.cloudems_nilm_devices"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("nilm_devices", []))

    @property
    def extra_state_attributes(self):
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        d = self.coordinator.data or {}
        # v1.16.1: trim to essential fields only to stay under HA recorder 16 KB limit
        _src_map = {"smart_plug":"smart_plug","injected":"smart_plug",
                    "cloud_ai":"cloud_ai","ollama":"ollama","local_ai":"local_ai"}
        # v4.5.51: room ophalen uit room_meter engine (device_id → room mapping)
        _room_map: dict = {}
        if hasattr(self.coordinator, "_room_meter") and self.coordinator._room_meter:
            try:
                for _rname, _rstate in self.coordinator._room_meter._rooms.items():
                    for _rd in (_rstate.devices or []):
                        _room_map[_rd.device_id] = _rname
            except Exception:
                pass

        slim_devices = [
            {
                # v4.5.51: device_id en room zijn essentieel voor de JS-kaart
                "device_id":     dv.get("device_id", dv.get("id", "")),
                "name":          dv.get("user_name") or dv.get("name", "Unknown"),
                "user_name":     dv.get("user_name", ""),
                "device_type":   dv.get("device_type", "unknown"),
                "type":          dv.get("device_type", "unknown"),   # alias for card
                "is_on":         dv.get("is_on", False),
                "state":         "on" if dv.get("is_on") else "off",
                "running":       dv.get("is_on", False),
                "power_w":       round(dv.get("current_power", 0), 1),
                "power_min":     round(dv.get("power_min", dv.get("current_power", 0)), 1),
                "confidence":    round(dv.get("confidence", 0) * 100, 0),
                "confirmed":     dv.get("confirmed", False),
                "pending":       dv.get("pending", False),  # v4.5.51: wacht op gebruikersbevestiging
                "user_suppressed": dv.get("user_suppressed", False),
                "last_seen_days":  round((_time_mod.time() - dv.get("last_seen", _time_mod.time())) / 86400.0, 1) if dv.get("last_seen") else None,
                "on_events":     dv.get("on_events", 0),
                "dismissed":     dv.get("dismissed", False),
                # v1.17: fase + bron
                "phase":         dv.get("phase", "L1") or "L1",
                "phase_label":   dv.get("phase", "L1") if dv.get("phase","L1") not in ("ALL","") else "3∅",
                "phase_confirmed": dv.get("phase_confirmed", False),
                "source":        dv.get("source", "database"),
                "source_type":   _src_map.get(dv.get("source",""), "nilm"),
                # v2.4.19: tijdprofiel
                "primary_slot":  dv.get("primary_slot", ""),
                "time_mismatch": dv.get("time_mismatch", False),
                # v4.5.51: kamer uit room_meter engine
                "room":          _room_map.get(dv.get("device_id", dv.get("id", "")), ""),
                # v4.6.314: energie + runtime voor detail panel
                # v4.6.484: smart_plug apparaten gebruiken realtime kWh teller uit coordinator
                "today_kwh":        round(
                    (self.coordinator._anchor_kwh_today.get(dv.get("device_id") or dv.get("entity_id", ""), None)
                     if dv.get("source") == "smart_plug"
                     else None)
                    or (dv.get("energy") or {}).get("today_kwh", 0.0), 3),
                "energy_kwh_today": round(
                    (self.coordinator._anchor_kwh_today.get(dv.get("device_id") or dv.get("entity_id", ""), None)
                     if dv.get("source") == "smart_plug"
                     else None)
                    or (dv.get("energy") or {}).get("today_kwh", 0.0), 3),
                "yesterday_kwh":    round(
                    (self.coordinator._anchor_kwh_yesterday.get(dv.get("device_id") or dv.get("entity_id", ""), None)
                     if dv.get("source") == "smart_plug"
                     else None)
                    or (dv.get("energy") or {}).get("yesterday_kwh", 0.0), 3),
                "total_on_seconds": round((dv.get("energy") or {}).get("total_on_seconds", 0.0), 0),
                "session_count": dv.get("session_count", 0),
                "avg_duration_min": round(dv.get("avg_duration_min", 0.0), 1),
            }
            for dv in devices
        ]
        return _trim_attrs({
            "devices":         slim_devices[:50],
            "device_list":     slim_devices[:50],   # alias — dashboard leest dit
            "active_mode":     d.get("nilm_mode", "database"),
            "confirmed_count": sum(1 for dv in devices if dv.get("confirmed")),
            "pending_count":   sum(1 for dv in devices if dv.get("pending")),
            "active_count":    sum(1 for dv in devices if dv.get("is_on")),
            "total_power_w":   sum(dv.get("current_power", 0) for dv in devices if dv.get("is_on")),
            # v4.5.64: onverklaard vermogen
            "undefined_power_w":    d.get("undefined_power_w"),
            "undefined_power_name": d.get("undefined_power_name", "Onverklaard vermogen"),
            # v4.6.427: wasbeurt cyclus data — leesbaar door dashboard template
            "appliance_cycles":     d.get("appliance_cycles"),
        })


class CloudEMSNILMDeviceSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry, device):
        super().__init__(coord)
        self._entry     = entry
        self._device_id = device.device_id
        self._attr_name = f"CloudEMS NILM · {device.display_name}"
        self._attr_icon      = DEVICE_ICONS.get(device.device_type, "mdi:help-circle")
        self._attr_unique_id = f"{entry.entry_id}_nilm_{device.device_id}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def _dev(self):
        return self.coordinator.nilm.get_device(self._device_id)

    @property
    def native_value(self):
        dev = self._dev
        return round(dev.current_power, 1) if dev else None

    @staticmethod
    def _source_type(source: str) -> str:
        return {
            "smart_plug": "smart_plug", "injected": "smart_plug",
            "cloud_ai": "cloud_ai", "ollama": "ollama",
            "local_ai": "local_ai", "database": "nilm",
            "community": "nilm", "builtin": "nilm",
        }.get(source, "nilm")

    @property
    def extra_state_attributes(self):
        dev = self._dev
        if not dev:
            return {}
        src_type = self._source_type(dev.source)
        return {
            "device_id":        dev.device_id,
            "device_type":      dev.display_type,
            "is_on":            dev.is_on,
            "confidence_pct":   round(dev.effective_confidence * 100, 1),
            "source":           dev.source,
            # v1.17: bron-type + fase voor dashboard
            "source_type":      src_type,
            "source_label":     {
                "smart_plug": "Stekker", "nilm": "NILM",
                "local_ai": "Lokale AI", "cloud_ai": "Cloud AI", "ollama": "Ollama",
            }.get(src_type, "NILM"),
            "confirmed":        dev.confirmed,
            "user_feedback":    dev.user_feedback,
            "pending":          dev.pending_confirmation,
            "user_suppressed":  dev.user_suppressed,
            "phase":            dev.phase,
            "phase_label":      dev.phase if dev.phase not in ("ALL", "") else "3∅",
            "on_events":        dev.on_events,
            "energy_today_kwh": dev.energy.today_kwh,
            "energy_week_kwh":  dev.energy.week_kwh,
            "energy_month_kwh": dev.energy.month_kwh,
            "energy_year_kwh":  dev.energy.year_kwh,
            "energy_total_kwh": dev.energy.total_kwh,
            # v2.2.2: sessie-statistieken
            "session_count":         dev.energy.session_count,
            "avg_duration_min":      dev.energy.avg_duration_min,
            "last_12_months_kwh":    dev.energy.last_12_months_kwh,
            # v2.2.2: confidence decay info
            "confidence_raw":        round(dev.confidence, 3),
            "confidence_decay_days": max(0, round((import_time() - dev.last_seen) / 86400.0 - 7, 1))
                                     if not dev.confirmed else 0,
            # v2.2.3: fix 5 — schedule attributen uit nilm_devices_enriched
            **self._get_schedule_attrs(dev.device_id),
            # v2.2.3: fix 9 — energie trend tov gemiddelde laatste 3 maanden
            "energy_trend_pct":      self._calc_energy_trend(dev),
            # v2.2.5: LLM naam-suggestie
            "suggested_name":        dev.suggested_name,
        }

    def _get_schedule_attrs(self, device_id: str) -> dict:
        """Haal schedule-verrijkingsdata op uit coordinator nilm_devices."""
        nilm_list = (self.coordinator.data or {}).get("nilm_devices", [])
        for d in nilm_list:
            if d.get("device_id") == device_id:
                return {
                    "schedule_peak_weekday":  d.get("schedule_peak_weekday"),
                    "schedule_peak_hour":     d.get("schedule_peak_hour"),
                    "schedule_unusual":       d.get("schedule_unusual", False),
                    "schedule_observations":  d.get("schedule_observations", 0),
                    "schedule_ready":         d.get("schedule_ready", False),
                    "schedule_weekly_profile": d.get("schedule_weekly_profile", []),
                    "schedule_always_on":     d.get("schedule_always_on", False),
                    "schedule_on_ratio":      d.get("schedule_on_ratio", 0.0),
                }
        return {}

    @staticmethod
    def _calc_energy_trend(dev) -> float | None:
        """Bereken trend: huidige maand vs gemiddelde van laatste 3 maanden. None als onvoldoende data."""
        history = dev.energy.last_12_months_kwh
        if len(history) < 3 or dev.energy.month_kwh <= 0:
            return None
        avg_3m = sum(history[-3:]) / 3
        if avg_3m <= 0:
            return None
        return round((dev.energy.month_kwh - avg_3m) / avg_3m * 100, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Cost / P1
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCostSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "CloudEMS Energy Cost"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/h"
    _attr_icon  = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_cost"
        self.entity_id = "sensor.cloudems_energy_cost"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cost_per_hour")

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "cost_today_eur": d.get("cost_today_eur", 0.0),
            "cost_month_eur": d.get("cost_month_eur", 0.0),
            "bill_simulator": d.get("bill_simulator", {}),
        }


class CloudEMSDagkostenSensor(CoordinatorEntity, SensorEntity):
    """
    Werkelijke dagkosten stroom (€).

    Berekening: (import_kwh × import_prijs) − (export_kwh × export_prijs)
    Prijs per kWh wordt afgeleid uit de gemiddelde EPEX prijs of de
    geconfigureerde vaste prijs. Export prijs = geconfigureerde
    terugleverprijs of 70% van importprijs als fallback.

    Attribuut 'gas_cost_today_eur' bevat gas kosten vandaag als P1 gas
    beschikbaar is.
    """
    _attr_name  = "CloudEMS · Dagkosten Stroom"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon  = "mdi:cash-clock"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_dagkosten_stroom"
        self.entity_id = "sensor.cloudems_dagkosten_stroom"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data") or {}
        imp_kwh = float(p1.get("electricity_import_today_kwh") or 0)
        exp_kwh = float(p1.get("electricity_export_today_kwh") or 0)

        # Prijzen ophalen
        price_info = d.get("energy_price") or {}
        import_eur_kwh = float(
            price_info.get("price_incl_tax_eur_kwh")
            or price_info.get("all_in_price_eur_kwh")
            or self.coordinator._config.get("fixed_price", 0.0)
            or 0.25
        )
        cfg = self.coordinator._config
        export_eur_kwh = float(
            cfg.get("fixed_export_price") or import_eur_kwh * 0.70
        )

        cost = round(imp_kwh * import_eur_kwh - exp_kwh * export_eur_kwh, 4)
        return max(cost, 0.0)  # negatief (netto opbrengst) als 0 rapporteren

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data") or {}
        imp_kwh = float(p1.get("electricity_import_today_kwh") or 0)
        exp_kwh = float(p1.get("electricity_export_today_kwh") or 0)
        price_info = d.get("energy_price") or {}
        import_eur_kwh = float(
            price_info.get("price_incl_tax_eur_kwh")
            or price_info.get("all_in_price_eur_kwh")
            or self.coordinator._config.get("fixed_price", 0.0)
            or 0.25
        )
        cfg = self.coordinator._config
        export_eur_kwh = float(cfg.get("fixed_export_price") or import_eur_kwh * 0.70)

        gross_import = round(imp_kwh * import_eur_kwh, 4)
        gross_export = round(exp_kwh * export_eur_kwh, 4)
        netto = round(gross_import - gross_export, 4)

        # Gas kosten vandaag
        gas_m3 = float(p1.get("gas_today_m3") or 0)
        gas_sensor_eid = cfg.get("gas_price_sensor", "")
        gas_price = 0.0
        if gas_sensor_eid:
            try:
                gs = self.coordinator.hass.states.get(gas_sensor_eid)
                gas_price = float(gs.state) if gs else 0.0
            except Exception:
                gas_price = 0.0
        if not gas_price:
            gas_price = float(cfg.get("gas_price_fixed", 0.0) or 0.0)
        gas_cost = round(gas_m3 * gas_price, 4)

        return {
            "import_kwh":           round(imp_kwh, 3),
            "export_kwh":           round(exp_kwh, 3),
            "import_cost_eur":      gross_import,
            "export_revenue_eur":   gross_export,
            "netto_cost_eur":       netto,
            "netto_opbrengst":      netto < 0,
            "import_price_eur_kwh": round(import_eur_kwh, 4),
            "export_price_eur_kwh": round(export_eur_kwh, 4),
            "gas_m3_today":         round(gas_m3, 3),
            "gas_price_eur_m3":     round(gas_price, 4),
            "gas_cost_today_eur":   gas_cost,
            "totaal_incl_gas_eur":  round(max(netto, 0) + gas_cost, 4),
        }


class CloudEMSComfortScoreSensor(CoordinatorEntity, SensorEntity):
    """
    Comfort score (0-100).

    Samengestelde score op basis van:
      - Temperatuurcomfort: gemiddeld verschil actueel vs setpoint per ruimte (40%)
      - Aanwezigheid: is het huis bezet? (20%)
      - Weersomstandigheden: buitentemp en neerslagrisico (20%)
      - Energieprestatie: zelfconsumptie % vandaag (20%)

    Score 80-100 = uitstekend, 60-79 = goed, 40-59 = matig, <40 = slecht.
    """
    _attr_name  = "CloudEMS · Comfort Score"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon  = "mdi:home-heart"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_comfort_score"
        self.entity_id = "sensor.cloudems_comfort_score"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    def _temp_score(self) -> tuple[float, dict]:
        """0-100 score op basis van temperatuur vs setpoint in alle ruimtes."""
        climate_data = (self.coordinator.data or {}).get("climate_entities", {})
        all_ents = climate_data.get("all", []) if isinstance(climate_data, dict) else []
        if not all_ents:
            return 70.0, {}  # geen data → neutraal
        diffs = []
        details = {}
        for e in all_ents:
            cur = e.get("current_temp")
            tgt = e.get("target_temp")
            mode = e.get("mode", "off")
            if cur is None or tgt is None or mode in ("off", "unavailable"):
                continue
            diff = abs(float(cur) - float(tgt))
            diffs.append(diff)
            details[e.get("name", e.get("entity_id", "?"))] = round(diff, 1)
        if not diffs:
            return 70.0, details
        avg_diff = sum(diffs) / len(diffs)
        # 0°C diff = 100, 2°C diff = 60, 4°C diff = 20, >5°C = 0
        score = max(0, min(100, 100 - avg_diff * 20))
        return round(score, 1), details

    def _presence_score(self) -> float:
        """Aanwezigheid: 100 als thuis, 50 als afwezig (we weten het niet zeker)."""
        try:
            s = self.coordinator.hass.states.get(
                "binary_sensor.cloudems_aanwezigheid_op_basis_van_stroom"
            )
            if s:
                return 100.0 if s.state == "on" else 50.0
        except Exception:
            pass
        return 50.0

    def _weather_score(self) -> float:
        """Weerscore: buitentemp rond 18°C = 100, extremen lager."""
        try:
            weather_cfg = self.coordinator._config.get("weather_entity", "")
            if not weather_cfg:
                # Probeer generieke HA weather entity
                for eid in ["weather.knmi_thuis", "weather.home", "weather.forecast_home"]:
                    s = self.coordinator.hass.states.get(eid)
                    if s:
                        temp = s.attributes.get("temperature")
                        if temp is not None:
                            diff = abs(float(temp) - 18.0)
                            return max(0, min(100, 100 - diff * 4))
            else:
                s = self.coordinator.hass.states.get(weather_cfg)
                if s:
                    temp = s.attributes.get("temperature")
                    if temp is not None:
                        diff = abs(float(temp) - 18.0)
                        return max(0, min(100, 100 - diff * 4))
        except Exception:
            pass
        return 60.0  # neutraal fallback

    def _energy_score(self) -> float:
        """Zelfconsumptie % → hogere zelfconsumptie = beter energieprestatie."""
        try:
            s = self.coordinator.hass.states.get("sensor.cloudems_self_consumption")
            if s and s.state not in ("unavailable", "unknown"):
                pct = float(s.state)
                return min(100, pct * 1.2)  # 83% zelfcons = 100 score
        except Exception:
            pass
        return 50.0

    @property
    def native_value(self):
        t_score, _ = self._temp_score()
        p_score = self._presence_score()
        w_score = self._weather_score()
        e_score = self._energy_score()
        total = round(t_score * 0.40 + p_score * 0.20 + w_score * 0.20 + e_score * 0.20, 1)
        return total

    @property
    def extra_state_attributes(self):
        t_score, temp_details = self._temp_score()
        p_score = self._presence_score()
        w_score = self._weather_score()
        e_score = self._energy_score()
        total = round(t_score * 0.40 + p_score * 0.20 + w_score * 0.20 + e_score * 0.20, 1)
        label = "Uitstekend" if total >= 80 else "Goed" if total >= 60 else "Matig" if total >= 40 else "Slecht"
        return {
            "score_totaal":        total,
            "score_label":         label,
            "score_temperatuur":   t_score,
            "score_aanwezigheid":  p_score,
            "score_weer":          w_score,
            "score_energieprestatie": e_score,
            "temperatuur_details": temp_details,
        }


class CloudEMSP1Sensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    _attr_name = "CloudEMS P1 Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_p1_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("p1_data",{}).get("net_power_w")

    @property
    def extra_state_attributes(self):
        return (self.coordinator.data or {}).get("p1_data", {})


# ═══════════════════════════════════════════════════════════════════════════════
# Grid Import / Export sensors (power + energy totals per tariff)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSGridNetPowerSensor(CoordinatorEntity, SensorEntity):
    """Current net grid power in Watt. Positive = import, negative = export.

    BUG FIX v1.13.0: This sensor was referenced in the dashboard as
    sensor.cloudems_grid_net_power but never registered, causing a
    Configuratiefout.  The value is always available in coordinator data
    as 'grid_power' regardless of whether the user configured a net sensor
    or separate import/export sensors.
    """
    _attr_name = "CloudEMS Grid · Net Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_net_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        d  = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # P1 net power takes priority; fall back to coordinator-computed grid_power
        v = p1.get("net_power_w")
        if v is not None:
            return v
        v = d.get("grid_power")
        return v if v is not None else 0

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        return {
            "import_power_w": d.get("import_power_w", 0),
            "export_power_w": d.get("export_power_w", 0),
            "source":         "p1" if d.get("p1_data", {}).get("net_power_w") is not None else "calculated",
        }


class CloudEMSGridImportPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """Current grid import power in Watt (Energieverbruik)."""
    _attr_name = "CloudEMS Grid · Import Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_import_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def available(self) -> bool:
        return True  # Always available; returns 0 when no import is happening

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # BUG FIX: or-chain skips 0 (falsy) → use is-not-None priority chain
        for v in (p1.get("power_import_w"), d.get("import_power_w"), d.get("import_power")):
            if v is not None:
                return v
        return 0

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {
            "energy_total_kwh":  p1.get("energy_import_kwh"),
            "energy_t1_kwh":     p1.get("energy_import_t1_kwh"),
            "energy_t2_kwh":     p1.get("energy_import_t2_kwh"),
            "tariff":            p1.get("tariff"),
        }


class CloudEMSGridExportPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """Current grid export power in Watt (Energieproductie)."""
    _attr_name = "CloudEMS Grid · Export Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grid_export_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def available(self) -> bool:
        return True  # Always available; returns 0 when no export is happening

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        # BUG FIX: or-chain skips 0 (falsy) → use is-not-None priority chain
        for v in (p1.get("power_export_w"), d.get("export_power_w"), d.get("export_power")):
            if v is not None:
                return v
        return 0

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {
            "energy_total_kwh":  p1.get("energy_export_kwh"),
            "energy_t1_kwh":     p1.get("energy_export_t1_kwh"),
            "energy_t2_kwh":     p1.get("energy_export_t2_kwh"),
            "tariff":            p1.get("tariff"),
        }


class CloudEMSGridImportEnergySensor(CoordinatorEntity, SensorEntity):
    """Total grid import energy in kWh for a single tariff (meter reading)."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coord, entry, tariff: int):
        super().__init__(coord)
        self._entry = entry
        self._tariff = tariff
        self._attr_name = f"CloudEMS Grid · Import Energy Tariff {tariff}"
        self._attr_unique_id = f"{entry.entry_id}_grid_import_energy_t{tariff}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return p1.get(f"energy_import_t{self._tariff}_kwh")

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {"tariff": self._tariff, "total_all_tariffs_kwh": p1.get("energy_import_kwh")}


class CloudEMSGridExportEnergySensor(CoordinatorEntity, SensorEntity):
    """Total grid export energy in kWh for a single tariff (meter reading)."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coord, entry, tariff: int):
        super().__init__(coord)
        self._entry = entry
        self._tariff = tariff
        self._attr_name = f"CloudEMS Grid · Export Energy Tariff {tariff}"
        self._attr_unique_id = f"{entry.entry_id}_grid_export_energy_t{tariff}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return p1.get(f"energy_export_t{self._tariff}_kwh")

    @property
    def extra_state_attributes(self):
        p1 = (self.coordinator.data or {}).get("p1_data", {})
        return {"tariff": self._tariff, "total_all_tariffs_kwh": p1.get("energy_export_kwh")}


# ═══════════════════════════════════════════════════════════════════════════════
# Per-phase import / export power sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPhaseImportPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """Per-phase import power in Watt — zero when exporting (Energieverbruik Fase Lx)."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Import Power"
        self._attr_unique_id = f"{entry.entry_id}_import_power_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        ph_key = f"power_{self._phase.lower()}_import_w"
        # Prefer direct P1 per-phase import; fall back to max(0, net phase power)
        val = p1.get(ph_key)
        if val is not None and val > 0:
            raw = round(val, 1)
            # Sanity: per-fase max ~25A — 265V ≈ 6625W; clamp anything absurd
            # (catches kW→W double-conversion e.g. 379 kW sensor → 379000)
            if raw > 20000:
                import logging
                logging.getLogger(__name__).warning(
                    "CloudEMS fase %s import: waarde %.0fW lijkt te hoog (kW sensor?). "
                    "Controleer sensor configuratie.", self._phase, raw
                )
                return None
            return raw
        net = d.get("phases", {}).get(self._phase, {}).get("power_w")
        if net is not None:
            raw = round(max(0.0, net), 1)
            if raw > 20000:
                return None
            return raw
        return None


class CloudEMSPhaseExportPowerSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """Per-phase export power in Watt — zero when importing (Energieproductie Fase Lx)."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, phase: str):
        super().__init__(coord)
        self._entry = entry
        self._phase = phase
        self._attr_name = f"CloudEMS Grid · Phase {phase} Export Power"
        self._attr_unique_id = f"{entry.entry_id}_export_power_{phase.lower()}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        p1 = d.get("p1_data", {})
        ph_key = f"power_{self._phase.lower()}_export_w"
        # Prefer direct P1 per-phase export (DSMR5); fall back to max(0, -net phase power)
        val = p1.get(ph_key)
        if val is not None and val > 0:
            raw = round(val, 1)
            if raw > 20000:
                import logging
                logging.getLogger(__name__).warning(
                    "CloudEMS fase %s export: waarde %.0fW lijkt te hoog (kW sensor?). "
                    "Controleer sensor configuratie.", self._phase, raw
                )
                return None
            return raw
        net = d.get("phases", {}).get(self._phase, {}).get("power_w")
        if net is not None:
            raw = round(max(0.0, -net), 1)
            if raw > 20000:
                return None
            return raw
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — Price: Previous / Current / Next hour sensors
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPricePreviousHourSensor(CoordinatorEntity, SensorEntity):
    """Price of the previous hour — useful for comparison on dashboards."""
    _attr_name = "CloudEMS Energy · Price Previous Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_prev_hour"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        prev = ep.get("prev_hour_price")
        return round(prev, 5) if prev is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        cur = ep.get("current")
        prev = ep.get("prev_hour_price")
        delta = None
        if cur is not None and prev is not None:
            delta = round(cur - prev, 5)
        return {"delta_vs_current_eur_kwh": delta}


class CloudEMSPriceCurrentSensor(CoordinatorEntity, SensorEntity):
    """Current EPEX price — dedicated sensor for dashboard cards."""
    _attr_name = "CloudEMS Energy · Price Current Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_current_hour"
        # v4.5.4: explicit entity_id — dashboard uses sensor.cloudems_price_current_hour
        self.entity_id = "sensor.cloudems_price_current_hour"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        # Show all-in price (with tax/BTW/markup) if toggles are on, else base EPEX
        # v4.5.3: gebruik 'is not None' i.p.v. 'or' om prijs=0.0 correct door te geven
        p = ep.get("current_display")
        if p is None:
            p = ep.get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        next_hours = ep.get("next_hours", [])
        # next_hour = het slot ná het huidige (index 1, want index 0 = huidig uur)
        next_hour_price = next_hours[1].get("price") if len(next_hours) > 1 else None
        return {
            "is_negative":          ep.get("is_negative", False),
            "is_cheap":             ep.get("is_cheap_hour", False),
            "rank_today":           ep.get("rank_today"),
            # Prijs zonder belasting (kale EPEX of provider excl. EB+BTW)
            "price_excl_tax":       ep.get("current_excl_tax") or ep.get("current"),
            "min_today_excl_tax":   ep.get("min_today_excl_tax") or ep.get("min_today"),
            "max_today_excl_tax":   ep.get("max_today_excl_tax") or ep.get("max_today"),
            "avg_today_excl_tax":   ep.get("avg_today_excl_tax") or ep.get("avg_today"),
            # Prijs met belasting (all-in incl. EB+BTW+markup)
            "price_incl_tax":       ep.get("current_all_in") or ep.get("current_display"),
            "min_today_incl_tax":   ep.get("min_today_incl_tax") or ep.get("min_today"),
            "max_today_incl_tax":   ep.get("max_today_incl_tax") or ep.get("max_today"),
            "avg_today_incl_tax":   ep.get("avg_today_incl_tax") or ep.get("avg_today"),
            # Labels voor dashboard display
            "price_label":          ep.get("price_label", "EPEX"),
            "price_label_excl":     ep.get("price_label_excl", "excl. belasting"),
            # Tax breakdown
            "base_epex_price":      ep.get("current"),
            "price_all_in":         ep.get("current_all_in") or ep.get("current_display"),
            "tax_per_kwh":          ep.get("tax_per_kwh"),
            "vat_rate":             ep.get("vat_rate"),
            "supplier_markup_kwh":  ep.get("supplier_markup_kwh"),
            "price_include_tax":    ep.get("price_include_tax", False),
            "price_include_btw":    ep.get("price_include_btw", False),
            # v4.5.1: prijsbron info voor dashboard
            "prices_from_provider": ep.get("prices_from_provider", False),
            "price_source":         ep.get("source", "epex"),
            "provider_key":         ep.get("provider_key", ""),
            # Volgend uur (index 1 van next_hours = slot na het huidige)
            "next_hour_eur_kwh":    round(next_hour_price, 5) if next_hour_price is not None else None,
            # v4.5.9: zelflerende totale opslag diagnostics
            "total_opslag_kwh":        ep.get("total_opslag_kwh"),
            "opslag_learned":          ep.get("opslag_learned", False),
            "opslag_source":           ep.get("opslag_source"),
            "learned_opslag_kwh":      ep.get("learned_opslag_kwh"),
            "learned_opslag_samples":  ep.get("learned_opslag_samples", 0),
            # Legacy velden
            "learned_markup_kwh":      ep.get("learned_markup_kwh"),
            "learned_markup_samples":  ep.get("learned_markup_samples", 0),
            "learned_eb_kwh":          ep.get("learned_eb_kwh"),
            "learned_btw_rate":        ep.get("learned_btw_rate"),
        }


class CloudEMSPriceNextHourSensor(CoordinatorEntity, SensorEntity):
    """Price of the next hour — helps decide when to shift loads."""
    _attr_name = "CloudEMS Energy · Price Next Hour"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_price_next_hour"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self):
        next_hours = (self.coordinator.data or {}).get("energy_price", {}).get("next_hours", [])
        if next_hours:
            return round(next_hours[0].get("price", 0), 5)
        return None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        next_hours = ep.get("next_hours", [])
        cur = ep.get("current")
        nxt = next_hours[0].get("price") if next_hours else None
        delta = round(nxt - cur, 5) if (nxt is not None and cur is not None) else None
        return {
            "hour":                   next_hours[0].get("hour") if next_hours else None,
            "delta_vs_current_eur_kwh": delta,
            "next_2h":                [{"hour": h.get("hour"), "price": h.get("price")} for h in next_hours[:2]],
            "cheapest_2h_start":      ep.get("cheapest_2h_start"),
            "cheapest_3h_start":      ep.get("cheapest_3h_start"),
            "cheapest_4h_start":      ep.get("cheapest_4h_start"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v2.4.14 — NILM review queue sensor (voor dashboard goedkeur-UI)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMReviewCurrentSensor(CoordinatorEntity, SensorEntity):
    """
    State = device_id van het eerste onbevestigde NILM-apparaat, of 'none'.
    Attributen bevatten naam, type, vermogen, confidence en queue-grootte
    zodat het dashboard dit zonder templates kan tonen.
    """
    _attr_name       = "CloudEMS NILM · Te beoordelen"
    _attr_icon       = "mdi:help-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_review_current"
        self.entity_id       = "sensor.cloudems_nilm_review_current"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self) -> str:
        dev = self.coordinator.get_review_current()
        return dev.device_id if dev else "none"

    @property
    def extra_state_attributes(self) -> dict:
        dev   = self.coordinator.get_review_current()
        count = self.coordinator.get_review_pending_count()
        if not dev:
            return {"pending_count": count, "name": None, "device_type": None,
                    "power_w": None, "confidence": None, "phase": None, "on_events": None}
        return {
            "pending_count": count,
            "name":          dev.name or dev.device_type,
            "device_type":   dev.device_type,
            "power_w":       round(dev.current_power, 1),
            "confidence":    round(dev.confidence * 100, 0),
            "phase":         dev.phase or "L1",
            "on_events":     dev.on_events,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — NILM: Running devices list sensors (for dashboard)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMRunningDevicesSensor(CoordinatorEntity, SensorEntity):
    """
    State = number of devices currently ON.
    Attributes contain a clean list of running device names — suitable for
    dashboard display cards (e.g. Markdown card, custom:auto-entities).
    """
    _attr_name = "CloudEMS NILM · Running Devices"
    _attr_icon = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_running"
        self.entity_id = "sensor.cloudems_nilm_running_devices"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def _running(self) -> list:
        return [d for d in (self.coordinator.data or {}).get("nilm_devices", []) if d.get("is_on")]

    @property
    def native_value(self):
        return len(self._running)

    @property
    def extra_state_attributes(self):
        running = self._running
        return _trim_attrs({
            "device_names": [d.get("user_name") or d.get("name", d.get("device_type", "Unknown")) for d in running],
            "device_list": [
                {
                    "name":         d.get("user_name") or d.get("name", "Unknown"),
                    "type":         d.get("device_type", "unknown"),
                    "confirmed":    d.get("confirmed", False),
                    "confidence":   round(d.get("confidence", 0) * 100, 0),
                    # v1.17: fase + bron voor dashboard
                    "phase":        d.get("phase", "L1"),
                    "phase_label":  d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3∅",
                    "source":       d.get("source", "database"),
                    "source_type":  {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "power_w":      round(d.get("current_power", 0), 1),
                    "running":      True,
                    "state":        "on",
                }
                for d in running
            ],
            "nilm_mode": (self.coordinator.data or {}).get("nilm_mode", "database"),
            # Backward-compat alias: oudere kaartversies lezen "devices"
            "devices": [
                {
                    "name":         d.get("user_name") or d.get("name", "Unknown"),
                    "device_type":  d.get("device_type", "unknown"),
                    "type":         d.get("device_type", "unknown"),
                    "state":        "on",
                    "running":      True,
                    "power_w":      round(d.get("current_power", 0), 1),
                    "confidence":   round(d.get("confidence", 0) * 100, 0),
                    "phase":        d.get("phase", "L1"),
                    "phase_label":  d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3\u2205",
                    "source":       d.get("source", "database"),
                    "source_type":  {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "confirmed":    d.get("confirmed", False),
                }
                for d in running
            ],
        })


class CloudEMSNILMRunningDevicesPowerSensor(CoordinatorEntity, SensorEntity):
    """
    State = total power of all detected running devices (W).
    Attributes contain a per-device power breakdown — suitable for
    energy breakdown dashboard cards.
    """
    _attr_name = "CloudEMS NILM · Running Devices Power"
    _attr_icon = ICON_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_running_power"
        self.entity_id = "sensor.cloudems_nilm_running_devices_power"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def _running(self) -> list:
        return [d for d in (self.coordinator.data or {}).get("nilm_devices", []) if d.get("is_on")]

    @property
    def native_value(self):
        return round(sum(d.get("current_power", 0) for d in self._running), 1)

    @property
    def extra_state_attributes(self):
        running = self._running
        return _trim_attrs({
            "devices": [
                {
                    "name":        d.get("user_name") or d.get("name", "Unknown"),
                    "type":        d.get("device_type", "unknown"),
                    "power_w":     round(d.get("current_power", 0), 1),
                    "confirmed":   d.get("confirmed", False),
                    "confidence":  round(d.get("confidence", 0) * 100, 0),
                    # v1.17: fase + bron
                    "phase":       d.get("phase", "L1"),
                    "phase_label": d.get("phase", "L1") if d.get("phase", "L1") not in ("ALL", "") else "3∅",
                    "source":      d.get("source", "database"),
                    "source_type": {
                        "smart_plug": "smart_plug", "injected": "smart_plug",
                        "cloud_ai": "cloud_ai", "ollama": "ollama",
                        "local_ai": "local_ai",
                    }.get(d.get("source", ""), "nilm"),
                    "state":       "on",
                    "running":     True,
                }
                for d in sorted(running, key=lambda x: x.get("current_power", 0), reverse=True)
            ],
        })


class CloudEMSNILMTopDeviceSensor(CoordinatorEntity, SensorEntity):
    """
    Nth drukste verbruiker op dit moment — voor power-flow-card-plus individual sectie.

    State = vermogen in Watt van het Nth zwaarste actieve apparaat.
    De friendly_name en het icon updaten automatisch mee met welk apparaat er
    op die positie staat, zodat power-flow-card-plus altijd de juiste naam en
    het juiste icoontje toont zonder extra configuratie.

    Rank 1 = hoogste verbruiker, rank 2 = op één na hoogste, etc.
    Geeft None (unavailable) terug als er minder dan N apparaten actief zijn.
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    # Naam en icon zijn NIET statisch — zie name/icon properties hieronder
    _attr_should_poll  = False

    # Kleuren per apparaattype (voor power-flow-card-plus color hint attribuut)
    _DEVICE_COLORS: dict[str, str] = {
        "washing_machine": "#5b9bd5",
        "dryer":           "#e8a838",
        "dishwasher":      "#5bc8af",
        "oven":            "#e86736",
        "microwave":       "#e86736",
        "kettle":          "#e84040",
        "ev_charger":      "#3bba4c",
        "heat_pump":       "#a855f7",
        "boiler":          "#f97316",
        "cv_boiler":       "#f97316",
        "refrigerator":    "#60a5fa",
        "tv":              "#c084fc",
        "computer":        "#94a3b8",
        "light":           "#fbbf24",
    }

    def __init__(self, coord, entry, rank: int):
        super().__init__(coord)
        self._entry = entry
        self._rank  = rank
        self._attr_unique_id = f"{entry.entry_id}_nilm_top_{rank}"
        # entity_id expliciet zodat de YAML ernaar kan verwijzen
        self.entity_id = f"sensor.cloudems_nilm_top_{rank}_device"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    def _sorted_running(self) -> list:
        devices = (self.coordinator.data or {}).get("nilm_devices", [])
        running = [d for d in devices if d.get("is_on") and d.get("current_power", 0) > 0]
        return sorted(running, key=lambda x: x.get("current_power", 0), reverse=True)

    def _current_device(self) -> dict | None:
        top = self._sorted_running()
        return top[self._rank - 1] if len(top) >= self._rank else None

    @property
    def name(self) -> str:
        """Dynamische naam — power-flow-card-plus leest dit als label."""
        d = self._current_device()
        if d:
            label = d.get("user_name") or d.get("name") or d.get("device_type", "")
            # Maak leesbaar: "washing_machine" → "Wasmachine"
            return _nilm_display_name(label, self._rank)
        return f"Verbruiker {self._rank}"

    @property
    def icon(self) -> str:
        """Dynamisch icon op basis van het actieve apparaattype."""
        d = self._current_device()
        if d:
            dtype = d.get("device_type", "unknown")
            return DEVICE_ICONS.get(dtype, "mdi:lightning-bolt")
        return "mdi:lightning-bolt-outline"

    @property
    def native_value(self):
        d = self._current_device()
        return round(d.get("current_power", 0), 1) if d else None

    @property
    def extra_state_attributes(self):
        top = self._sorted_running()
        d   = top[self._rank - 1] if len(top) >= self._rank else None
        if d:
            dtype = d.get("device_type", "unknown")
            return {
                # power-flow-card-plus leest 'color' als kleurhint
                "color":         self._DEVICE_COLORS.get(dtype, "#94a3b8"),
                "name":          d.get("user_name") or d.get("name", dtype),
                "type":          dtype,
                "confirmed":     d.get("confirmed", False),
                "confidence":    round(d.get("confidence", 0) * 100, 1),
                "phase":         d.get("phase", "?"),
                "source":        d.get("source", "database"),
                "source_type":   "smart_plug" if d.get("source") == "smart_plug" else "nilm",
                "rank":          self._rank,
                "total_running": len(top),
            }
        return {
            "color":         "#374151",
            "rank":          self._rank,
            "name":          None,
            "total_running": len(top),
        }


# Hulpfunctie voor leesbare apparaatnamen (NL)
_NILM_NAMES_NL: dict[str, str] = {
    "washing_machine": "Wasmachine",
    "dryer":           "Droger",
    "dishwasher":      "Vaatwasser",
    "oven":            "Oven",
    "microwave":       "Magnetron",
    "kettle":          "Waterkoker",
    "ev_charger":      "Auto laden",
    "heat_pump":       "Warmtepomp",
    "boiler":          "Boiler",
    "cv_boiler":       "CV-ketel",
    "refrigerator":    "Koelkast",
    "freezer":         "Vriezer",
    "tv":              "TV",
    "computer":        "Computer",
    "light":           "Verlichting",
    "socket":          "Stopcontact",
    "battery":         "Batterij",
    "solar_inverter":  "Omvormer",
    "unknown":         "Onbekend",
}

def _nilm_display_name(raw: str, rank: int) -> str:
    """Geef een leesbare NL naam terug voor een NILM device_type of user_name."""
    if not raw:
        return f"Verbruiker {rank}"
    # Als het al een leesbare naam is (geen underscore, geen snake_case)
    if " " in raw or (raw[0].isupper() and "_" not in raw):
        return raw
    # Snake_case → NL vertaling of capitalize
    return _NILM_NAMES_NL.get(raw.lower(), raw.replace("_", " ").capitalize())


# ═══════════════════════════════════════════════════════════════════════════════
# v1.5.0 — AI / NILM status sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSAIStatusSensor(CoordinatorEntity, SensorEntity):
    """
    Shows the active AI provider and self-learning status.
    Helps users understand which AI backend is running and how well
    the system has learned so far.
    """
    _attr_name = "CloudEMS AI · Status"
    _attr_icon = "mdi:robot"
    # Note: NOT DIAGNOSTIC — users need to see this to understand NILM state

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ai_status"
        self.entity_id = "sensor.cloudems_ai_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("nilm_mode", "database")

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        ai = d.get("ai_status", {})
        return {
            "provider":           d.get("nilm_mode", "database"),
            "api_calls_total":    ai.get("call_count", 0),
            "provider_available": ai.get("available", True),
            "confidence_threshold_pct": round(ai.get("min_confidence", 0.65) * 100, 0),
            "devices_confirmed":  ai.get("confirmed_count", 0),
            "devices_total":      ai.get("total_devices", 0),
            "solar_learning": {
                "profiles":      ai.get("solar_profiles", 0),
                "total_peak_w":  ai.get("solar_peak_w", 0),
                "estimated_kwp": round(ai.get("solar_peak_w", 0) / 1000, 2),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.6.0 — EPEX today all-hours price sensor (for dashboard charts)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEPEXTodaySensor(CoordinatorEntity, SensorEntity):
    """
    State  = current EPEX spot price (EUR/kWh).
    Attributes contain the full list of today's hourly prices — ideal for
    a Lovelace ApexCharts card or custom:plotly-graph.

    Example attribute value:
        today_prices: [{hour: 0, price: 0.082}, {hour: 1, price: 0.071}, ...]
    """
    _attr_name = "CloudEMS Energy · EPEX Today"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = ICON_PRICE

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_epex_today"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("energy_price", {}).get("current")
        return round(p, 5) if p is not None else None

    @property
    def extra_state_attributes(self):
        ep = (self.coordinator.data or {}).get("energy_price", {})
        today_all         = ep.get("today_all", [])
        today_all_display = ep.get("today_all_display", [])  # all-in (met tax/BTW/markup)
        tomorrow_all      = ep.get("tomorrow_all", [])
        cur = ep.get("current")
        avg = ep.get("avg_today")

        # v4.5.9: normaliseer today_prices zodat .price altijd de display-prijs is
        # (all-in met EB/BTW als gebruiker dat heeft ingesteld, anders kale EPEX)
        # Alle dashboard-code leest .price — één bron van waarheid.
        def _normalize_slots(slots):
            """Vervang .price door price_display als dat beschikbaar is."""
            result = []
            for s in slots:
                display = s.get("price_display") or s.get("price_all_in")
                if display is not None:
                    result.append({**s, "price": display})
                else:
                    result.append(s)
            return result

        if today_all_display:
            today_prices = _normalize_slots(today_all_display)
        else:
            today_prices = today_all

        # Herbereken avg/min/max op basis van de display-prijs
        display_prices = [s["price"] for s in today_prices if s.get("price") is not None]
        avg_display = round(sum(display_prices) / len(display_prices), 5) if display_prices else avg
        min_display = min(display_prices) if display_prices else ep.get("min_today")
        max_display = max(display_prices) if display_prices else ep.get("max_today")

        # Morgen: zelfde normalisatie
        tomorrow_display = ep.get("tomorrow_all_display", [])
        if tomorrow_display:
            tomorrow_prices = _normalize_slots(tomorrow_display)
        else:
            tomorrow_prices = tomorrow_all

        # v4.5.66 fix: current_price_display = display-prijs voor huidig uur
        # (all-in indien beschikbaar, anders kale EPEX) — voor gebruik in dashboard template
        cur_display = ep.get("current_display") or ep.get("current_all_in") or ep.get("current")

        # v4.5.67 fix: next_hours prijzen ook normaliseren naar display-prijs
        # next_hours[0] = huidig uur, next_hours[1] = volgend uur
        # Bouw lookup: hour -> display price vanuit today_prices + tomorrow_prices
        _price_lookup = {}
        for _s in today_prices:
            if _s.get("hour") is not None:
                _price_lookup[_s["hour"]] = _s.get("price")
        # tomorrow prices: uren kunnen overlappen (0-23), markeer met offset
        for _s in (tomorrow_prices if tomorrow_prices else []):
            if _s.get("hour") is not None:
                _price_lookup[1000 + _s["hour"]] = _s.get("price")

        _raw_next = ep.get("next_hours", [])
        _today_hours_seen = set()
        _use_tomorrow = False
        _next_hours_display = []
        for _nh in _raw_next:
            _h = _nh.get("hour")
            # Detect rollover to tomorrow (hour resets to 0 after 23)
            if _today_hours_seen and _h is not None and _h < min(_today_hours_seen):
                _use_tomorrow = True
            if _h is not None:
                _today_hours_seen.add(_h)
            _lookup_key = (1000 + _h) if _use_tomorrow else _h
            _display_p = _price_lookup.get(_lookup_key, _nh.get("price"))
            _next_hours_display.append({**_nh, "price": _display_p if _display_p is not None else _nh.get("price")})

        return {
            "current_price_display": cur_display,  # altijd de display-prijs voor dashboard
            "today_prices":       today_prices,   # .price = display-prijs (all-in of EPEX)
            "today_prices_base":  today_all,       # altijd kale EPEX (voor debugging)
            "tomorrow_prices":    tomorrow_prices,
            "yesterday_prices":   ep.get("yesterday_prices", []),
            "tomorrow_available": ep.get("tomorrow_available", False),
            "next_hours":         _next_hours_display,
            "min_today":          min_display,
            "max_today":          max_display,
            "avg_today":          avg_display,
            "is_cheap_now":       (cur < avg) if (cur is not None and avg is not None) else None,
            "is_negative":        ep.get("is_negative", False),
            "cheapest_hour_1":    ep.get("cheapest_hour_1"),
            "cheapest_hour_2":    ep.get("cheapest_hour_2"),
            "cheapest_hour_3":    ep.get("cheapest_hour_3"),
            "cheapest_2h_start":  ep.get("cheapest_2h_start"),
            "cheapest_3h_start":  ep.get("cheapest_3h_start"),
            "cheapest_4h_start":  ep.get("cheapest_4h_start"),
            "data_source":        ep.get("source", "unknown"),
            "country":            ep.get("country", ""),
            "slot_count":         ep.get("slot_count", 0),
            "prev_hour_price":    ep.get("prev_hour_price"),
            "rank_today":         ep.get("rank_today"),
            "is_cheap_hour":      ep.get("is_cheap_hour"),
            # v4.5.3: prijscomponenten voor transparantie
            "price_include_tax":  ep.get("price_include_tax", False),
            "price_include_btw":  ep.get("price_include_btw", False),
            "tax_per_kwh":        ep.get("tax_per_kwh", 0.0),
            "vat_rate":           ep.get("vat_rate", 0.0),
            "supplier_markup_kwh": ep.get("supplier_markup_kwh", 0.0),
            "prices_from_provider": ep.get("prices_from_provider", False),
            # v4.5.61: beide varianten altijd beschikbaar voor dashboard toggle
            "price_label":        ep.get("price_label", "EPEX"),
            "price_label_excl":   ep.get("price_label_excl", "excl. belasting"),
            "min_today_incl_tax": ep.get("min_today_incl_tax") or min_display,
            "max_today_incl_tax": ep.get("max_today_incl_tax") or max_display,
            "avg_today_incl_tax": ep.get("avg_today_incl_tax") or avg_display,
            "min_today_excl_tax": ep.get("min_today_excl_tax") or ep.get("min_today"),
            "max_today_excl_tax": ep.get("max_today_excl_tax") or ep.get("max_today"),
            "avg_today_excl_tax": ep.get("avg_today_excl_tax") or ep.get("avg_today"),
            # today_prices_excl_tax: slots met kale EPEX prijs voor dashboard toggle
            "today_prices_excl_tax": [
                {**s, "price": s.get("price_excl_tax") or s.get("price")}
                for s in (ep.get("today_all_display") or today_all)
            ],
            "today_prices_incl_tax": [
                {**s, "price": s.get("price_incl_tax") or s.get("price_all_in") or s.get("price")}
                for s in (ep.get("today_all_display") or today_all)
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.20 — Goedkoopste 4-uursblok sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCheapest4hBlockSensor(CoordinatorEntity, SensorEntity):
    """Dedicated sensor voor het goedkoopste aaneengesloten 4-uursblok vandaag.

    State  = starttijd als string "HH:00" (bijv. "14:00"), of "onbekend"
    Attrs  = volledig blok: uren, prijzen per uur, gemiddelde prijs, label,
             in_block (True als huidig uur in blok valt), minuten tot start

    Ideaal voor Lovelace: toon als entity-card of in een markdown card.
    Gebruik binary_sensor.cloudems_energy_cheapest_4h voor automations.
    """
    _attr_name  = "CloudEMS Cheapest 4h Block"
    _attr_icon  = "mdi:clock-star-four-points"
    _attr_device_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cheapest_4h_block"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    def _block(self) -> dict:
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return ep.get("cheapest_4h_block") or {}

    @property
    def native_value(self) -> str:
        b = self._block()
        if not b:
            return "onbekend"
        return f"{b['start_hour']:02d}:00"

    @property
    def extra_state_attributes(self) -> dict:
        from datetime import datetime, timezone
        ep  = (self.coordinator.data or {}).get("energy_price", {})
        b   = self._block()
        if not b:
            return {"beschikbaar": False}

        now_h   = datetime.now(timezone.utc).hour
        in_block = now_h in b.get("hours", [])
        start_h  = b.get("start_hour", 0)
        mins_to_start = ((start_h - now_h) % 24) * 60 if not in_block else 0

        return {
            "label":          b.get("label"),          # "14:00–18:00"
            "start_hour":     b.get("start_hour"),
            "end_hour":       b.get("end_hour"),
            "hours":          b.get("hours", []),
            "prices":         b.get("prices", []),
            "avg_price":      b.get("avg_price"),
            "total_cost":     b.get("total_cost"),
            "in_block":       in_block,
            "mins_to_start":  mins_to_start,
            # context
            "avg_today":      ep.get("avg_today"),
            "current_price":  ep.get("current"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.7.0 — NILM Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMDiagSensor(CoordinatorEntity, SensorEntity):
    """
    NILM diagnostics sensor — shows exactly what the detector is doing.

    State  = classification success rate (%)
    Attributes contain:
      - Total events detected / classified / missed
      - Per-phase baseline power (what NILM thinks is always-on load)
      - Last 20 power events with timestamps, delta W and classification result
      - Power threshold and debounce settings

    Use this to diagnose WHY NILM is or isn't detecting devices:
      - Is the threshold too high? (small appliances missed)
      - Is baseline drifting? (noisy grid)
      - Are events classified but below confidence threshold?
    """
    _attr_name = "CloudEMS NILM · Diagnostics"
    _attr_icon = "mdi:stethoscope"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_diag"
        self.entity_id = "sensor.cloudems_nilm_diagnostics"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        return diag.get("classification_rate_pct", 0.0)

    @property
    def extra_state_attributes(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        # v1.16.1: limit recent_events to 10 entries with essential fields only (16 KB recorder limit)
        raw_events = diag.get("recent_events", [])
        slim_events = [
            {
                "ts":        e.get("ts", ""),
                "phase":     e.get("phase", ""),
                "delta_w":   e.get("delta_w", 0),
                "result":    e.get("result", ""),
            }
            for e in raw_events[:10]
        ]
        return {
            # Summary counters
            "events_total":            diag.get("events_total", 0),
            "events_classified":       diag.get("events_classified", 0),
            "events_missed":           diag.get("events_missed", 0),
            "classification_rate_pct": diag.get("classification_rate_pct", 0.0),
            # Last event info
            "last_event_ts":       diag.get("last_event_ts"),
            "last_event_delta_w":  diag.get("last_event_delta_w", 0.0),
            "last_match":          diag.get("last_match", ""),
            # Per-phase baselines — shows what NILM sees as always-on load
            "baseline_l1_w":  diag.get("baselines_w", {}).get("L1", 0.0),
            "baseline_l2_w":  diag.get("baselines_w", {}).get("L2", 0.0),
            "baseline_l3_w":  diag.get("baselines_w", {}).get("L3", 0.0),
            # Device counts
            "devices_known":     diag.get("devices_known", 0),
            "devices_confirmed": diag.get("devices_confirmed", 0),
            "ai_mode":           diag.get("ai_mode", "database"),
            # Settings
            "power_threshold_w": diag.get("power_threshold_w", 25),
            "debounce_s":        diag.get("debounce_s", 2.0),
            # Recent event log (last 10, trimmed)
            "recent_events":     slim_events,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — PID Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPIDDiagSensor(CoordinatorEntity, SensorEntity):
    """
    Toont de live toestand van alle PID-regelaars in CloudEMS:
      - Fase-begrenzing PID (L1/L2/L3)
      - EV-laadstroom PID
      - Auto-tune status

    State = EV PID huidige uitgang in Ampere (handig als quick-view).
    Attributen bevatten de volledige PID-toestand per controller.
    """
    _attr_name = "CloudEMS System · PID Diagnostics"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "A"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pid_diag"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        ev = (self.coordinator.data or {}).get("ev_pid_state", {})
        return ev.get("last_output_a")

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        ev   = data.get("ev_pid_state", {})
        ph   = data.get("phase_pid_states", {})

        def _pid_attrs(d: dict) -> dict:
            if not d: return {}
            return {
                "kp": d.get("kp"), "ki": d.get("ki"), "kd": d.get("kd"),
                "setpoint":    d.get("setpoint"),
                "integral":    d.get("integral"),
                "last_error":  d.get("last_error"),
                "last_output": d.get("last_output"),
                "last_state":  d.get("last_state"),
            }

        return {
            "ev_pid":         _pid_attrs(ev),
            "ev_target_grid_w":   ev.get("target_grid_w"),
            "ev_auto_tuner":  ev.get("auto_tuner"),
            "phase_pids":     {phase: _pid_attrs(pstate) for phase, pstate in ph.items()},
            "pid_settings": {
                "phase_kp": self.coordinator._config.get("pid_phase_kp"),
                "phase_ki": self.coordinator._config.get("pid_phase_ki"),
                "phase_kd": self.coordinator._config.get("pid_phase_kd"),
                "ev_kp":    self.coordinator._config.get("pid_ev_kp"),
                "ev_ki":    self.coordinator._config.get("pid_ev_ki"),
                "ev_kd":    self.coordinator._config.get("pid_ev_kd"),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.8.0 — NILM Sensor Input sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMInputSensor(CoordinatorEntity, SensorEntity):
    """
    Laat zien welke sensoren NILM gebruikt als invoer.

    State = invoermodus ('per_phase' / 'total_split' / 'total_l1')
    Attributen tonen per fase de gebruikte bron en de adaptieve drempel.

    Gebruik dit om snel te zien of NILM de beste data krijgt:
      per_phase   → ideaal: aparte stroomsensoren per fase
      total_split → OK: totaal netverbruik gelijkmatig verdeeld
      total_l1    → basis: enkelfasig, alles via L1
    """
    _attr_name = "CloudEMS NILM · Sensor Input"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_input"
        self.entity_id = "sensor.cloudems_nilm_sensor_input"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        inputs = diag.get("sensor_inputs", {})
        # If all phases use per_phase → best mode
        modes = set(inputs.values())
        if "per_phase" in modes and len(modes) == 1:
            return "per_phase"
        if "total_split" in modes:
            return "total_split"
        if "total_l1" in modes:
            return "total_l1"
        return "unknown"

    @property
    def extra_state_attributes(self):
        diag = (self.coordinator.data or {}).get("nilm_diagnostics", {})
        thresh = diag.get("adaptive_threshold", {})
        return {
            "sensor_per_phase": diag.get("sensor_inputs", {}),
            "adaptive_threshold_w":   thresh.get("threshold_w"),
            "threshold_adapted":      thresh.get("adapted", False),
            "noise_p80_w":            thresh.get("noise_p80_w"),
            "threshold_samples":      thresh.get("samples", 0),
            "recommendation": (
                "✅ Per-fase sensoren actief — beste NILM nauwkeurigheid"
                if self.native_value == "per_phase"
                else "⚠️ Geen fase-sensoren — voeg stroomsensoren (A) per fase toe voor betere NILM"
                if self.native_value in ("total_split", "total_l1")
                else "❓ NILM invoer onbekend"
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.3.26 — SmartPowerEstimator sensor (ingebouwde PowerCalc)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPowerCalcSensor(CoordinatorEntity, SensorEntity):
    """
    Overzichtssensor van de ingebouwde PowerCalc-engine.

    State: totaal geschat vermogen van alle getrackte entiteiten (W).
    Attributen: statistieken, per-entiteit breakdown.
    """
    _attr_name                     = "CloudEMS · PowerCalc"
    _attr_icon                     = "mdi:lightning-bolt-outline"
    _attr_native_unit_of_measurement = "W"
    _attr_state_class              = SensorStateClass.MEASUREMENT
    _attr_device_class             = SensorDeviceClass.POWER

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_powercalc"

    @property
    def native_value(self):
        est = getattr(self.coordinator, "_power_estimator", None)
        if not est:
            return None
        total = sum(
            s.get("estimated_w", 0)
            for s in est.get_all_states()
            if s.get("confidence") != "unknown"
        )
        return round(total, 0)

    @property
    def extra_state_attributes(self):
        est = getattr(self.coordinator, "_power_estimator", None)
        if not est:
            return {}
        stats  = est.get_stats()
        states = est.get_all_states()
        # Top-10 op vermogen
        top10 = [
            {
                "entity_id":  s["entity_id"],
                "estimated_w": s["estimated_w"],
                "confidence":  s["confidence"],
                "confidence_score": round(s.get("confidence_score", 0), 2),
                "source":      s["source"],
                "standby_w":   s.get("standby_w", 0),
            }
            for s in states[:10]
        ]
        return {
            "stats":            stats,
            "top_entities":     top10,
            "total_tracked":    stats.get("total_entities", 0),
            "high_confidence":  stats.get("by_confidence", {}).get("high", 0),
            "medium_confidence":stats.get("by_confidence", {}).get("medium", 0),
            "infra_filtered":   stats.get("infra_filtered", 0),
            "powercalc_active": bool(stats.get("powercalc_available")),
            "standby_total_w":  round(sum(
                s.get("standby_w", 0) for s in states
                if s.get("confidence") in ("medium", "high")
            ), 1),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — CO2 Intensity sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCO2Sensor(CoordinatorEntity, SensorEntity):
    """
    Huidige CO2-intensiteit van het elektriciteitsnet (gCO2/kWh).

    State = huidige intensiteit in gCO2eq/kWh.
    Attributen tonen of het netwerk groen of vuil is, en de databron.

    Gebruikt automatisch de beste beschikbare bron:
      1. Electricity Maps (gratis, geen API-sleutel nodig)
      2. CO2 Signal API (gratis token)
      3. Statisch Europees gemiddelde (EEA 2023, altijd beschikbaar)

    Gebruik in automaties:
      - Verschuif EV-laden naar groene uren (< 200 gCO2/kWh)
      - Toon CO2-besparingen van zelfopwekking
    """
    _attr_name = "CloudEMS Net · CO2 Intensiteit"
    _attr_icon = "mdi:molecule-co2"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "g/kWh"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_co2_intensity"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("co2_info", {}).get("current_gco2_kwh")

    @property
    def extra_state_attributes(self):
        info = (self.coordinator.data or {}).get("co2_info", {})
        return {
            "label":            info.get("label"),
            "is_green":         info.get("is_green"),
            "is_dirty":         info.get("is_dirty"),
            "source":           info.get("source"),
            "is_live":          info.get("is_live"),
            "country":          info.get("country"),
            "static_default_g": info.get("static_default_g"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — Energy Cost Forecast sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCostForecastSensor(CoordinatorEntity, SensorEntity):
    """
    Verwachte energiekosten voor vandaag en morgen.

    State = verwachte totale dagkosten vandaag (EUR).
    Attributen tonen reeds betaalde kosten, resterende verwachting en morgen.

    Het model leert jouw verbruikspatroon per uur en wordt steeds nauwkeuriger
    naarmate het meer dagen meet. Na ~5 dagen is het bruikbaar, na 14+ dagen
    betrouwbaar.

    Gebruik in dashboards:
      - "Vandaag naar verwachting €{state}" kaart
      - Vergelijk met gisteren/vorige week
    """
    _attr_name = "CloudEMS Energie · Kosten Verwachting"
    _attr_icon = "mdi:currency-eur"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cost_forecast"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("cost_forecast", {}).get("today_forecast_eur")

    @property
    def extra_state_attributes(self):
        fc = (self.coordinator.data or {}).get("cost_forecast", {})
        return {
            "today_actual_eur":     fc.get("today_actual_eur"),
            "today_remaining_eur":  fc.get("today_remaining_eur"),
            "tomorrow_forecast_eur":fc.get("tomorrow_forecast_eur"),
            "today_kwh_actual":     fc.get("today_kwh_actual"),
            "model_trained":        fc.get("model_trained"),
            "trained_hours":        fc.get("trained_hours"),
            "mape_pct":             fc.get("mape_pct"),
            "peak_consumption_hour":fc.get("peak_consumption_hour"),
            # hourly_patterns useful for ApexCharts
            "hourly_patterns":      fc.get("hourly_patterns", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.9.0 — Battery EPEX Schedule sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBatteryScheduleSensor(CoordinatorEntity, SensorEntity):
    """
    Huidige batterij-actie op basis van EPEX-schema.

    State = huidige actie ('charge' / 'discharge' / 'idle').
    Attributen tonen het volledige schema voor vandaag.

    Gebruik in dashboards:
      - Toon planning als tabel / tijdlijn
      - Trigger automaties op basis van batterij-actie
    """
    _attr_name = "CloudEMS Batterij · EPEX Schema"
    _attr_icon = "mdi:battery-clock"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_schedule"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        bs   = data.get("battery_schedule", {})
        # _seq in state zodat HA altijd een WebSocket event stuurt
        return bs.get("action", "idle")

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        bs   = data.get("battery_schedule", {})
        bats = data.get("batteries", [])

        soc_pct = bs.get("soc_pct")
        if soc_pct is None and bats:
            soc_pct = bats[0].get("soc_pct")

        # v3.9: Zonneplan provider info voor dashboard
        # Lees direct van de coordinator instantie (meest actueel, geen serialisatie-verlies)
        _zp_provider = None
        _coord = self.coordinator
        if hasattr(_coord, "_battery_providers") and _coord._battery_providers:
            _zp_provider = _coord._battery_providers.get_provider("zonneplan")

        if _zp_provider is not None:
            zp = _zp_provider.get_info()
        else:
            # Fallback: lees uit coordinator data (na restart voor coordinator klaar is)
            bp_data = data.get("battery_providers", {})
            if isinstance(bp_data, list):
                bp_data = {}
            providers_list = bp_data.get("providers", [])
            zp = next(
                (p for p in providers_list if isinstance(p, dict) and p.get("provider_id") == "zonneplan"),
                {},
            )

        bp = data.get("battery_providers", {}) if not isinstance(data.get("battery_providers"), list) else {}
        zp_state    = zp.get("state", {})
        zp_entities = zp.get("entities_mapped", [])

        # Bouw entity_id mapping op zodat dashboard direct sliders kan tonen
        def _zp_eid(key: str) -> str | None:
            """Geef de volledige entity_id terug voor een Zonneplan slider-sleutel."""
            # Direct van provider instantie (meest betrouwbaar)
            if _zp_provider is not None and hasattr(_zp_provider, "_entities"):
                eid = _zp_provider._entities.get(key)
                if eid:
                    return eid
            return None

        # Toon Zonneplan kaart zodra de provider gedetecteerd is (ook als niet enabled).
        _zp_detected = (
            (_zp_provider is not None and _zp_provider.is_detected)
            or bool(zp.get("detected"))
            or bool(zp_entities)
            or int(bp.get("detected_count", 0)) > 0
        )
        _forecast_data: dict = {}
        zonneplan_info: dict | None = None
        if _zp_detected:
            # Lees has_sliders en entities_mapped direct van provider (meest betrouwbaar)
            _has_sliders = False
            _entities_mapped = zp_entities
            if _zp_provider is not None and hasattr(_zp_provider, "_entities"):
                _ents = _zp_provider._entities
                _has_sliders = ("deliver_to_home" in _ents or "solar_charge" in _ents)
                if _ents:
                    _entities_mapped = list(_ents.keys())
            else:
                _has_sliders = zp.get("has_sliders", False)

            # Haal forecast + beslissing op direct van de provider
            _forecast_data = {}
            if _zp_provider is not None and hasattr(_zp_provider, "get_forecast_summary"):
                try:
                    _forecast_data = _zp_provider.get_forecast_summary()
                except Exception:
                    pass

            # Laatste beslissing met tijdstip (ook als auto-sturing UIT staat)
            _last_decision_ts  = getattr(_zp_provider, "_last_decision_ts", None)  if _zp_provider else None
            _last_decision_res = getattr(_zp_provider, "_last_decision_result", None) if _zp_provider else None
            _last_decision_str = ""
            if _last_decision_ts is not None:
                import datetime as _sensor_dt
                _last_decision_str = _sensor_dt.datetime.fromtimestamp(_last_decision_ts).strftime("%H:%M:%S")

            # auto_forecast_enabled: lees van coordinator (switch-state is leidend)
            _auto_fc_enabled = getattr(self.coordinator, "_zonneplan_auto_forecast", False)

            # Voeg action_label toe aan _forecast_data
            if _forecast_data and "recommended_action" in _forecast_data:
                _action_map = {
                    "hold": "⏸ Home optimalisatie",
                    "charge": "⚡ Laden",
                    "discharge": "⬇ Ontladen",
                    "powerplay": "🤖 Powerplay",
                    "idle": "○ Idle",
                }
                _forecast_data["action_label"] = _action_map.get(
                    _forecast_data.get("recommended_action", ""), 
                    _forecast_data.get("recommended_action", "—")
                )

            zonneplan_info = {
                "available":           zp.get("available", False),
                "detected":            True,
                "enabled":             zp.get("enabled", False),
                "has_sliders":         _has_sliders,
                "has_control_mode":    zp.get("has_control_mode", False),
                "active_mode":         zp_state.get("active_mode") or zp.get("saved_mode") or (
                    # Fallback: lees direct van de HA select entity — filter unavailable/unknown
                    _cm_st.state if (
                        _zp_eid("control_mode") and
                        (_cm_st := self.coordinator.hass.states.get(_zp_eid("control_mode"))) and
                        _cm_st.state not in ("unavailable", "unknown", "none", "")
                    ) else None
                ),
                "tariff_group":        zp_state.get("tariff_group"),
                "override_since_min":  zp.get("override_since_min"),
                "auto_forecast_enabled": _auto_fc_enabled,   # correcte key voor dashboard
                "auto_forecast":         _auto_fc_enabled,   # compat alias
                "saved_mode":          zp.get("saved_mode"),
                "last_slider_write_min": zp.get("last_slider_write_min"),
                "entities_mapped":     _entities_mapped,
                # Slider kalibratie / max leren — nodig voor progress bar in dashboard
                # slider_max = werkelijke max van HA number entity (meest betrouwbaar)
                # learned_max = gelerend via probing (kan None zijn)
                "learned_max_deliver_w": zp.get("slider_max_deliver_w") or zp.get("learned_max_deliver_w"),
                "learned_max_solar_w":   zp.get("slider_max_solar_w")   or zp.get("learned_max_solar_w"),
                "probe_active":          zp.get("probe_active", False),
                "probe_current_w":       zp.get("probe_current_w"),
                "probe_confirmed_w":     zp.get("probe_confirmed_w"),
                "probe_step_w":          zp.get("probe_step_w"),
                "probe_key":             zp.get("probe_key"),
                # Forecast + laatste beslissing (altijd aanwezig, ook zonder auto-sturing)
                "forecast":            _forecast_data,
                # Laatste sturing voor dashboard weergave
                "last_sent_str":       (
                    getattr(_zp_provider, "_last_sent_mode", None)
                    if _zp_provider else None
                ),
                "last_decision_str":   _last_decision_str or None,
                # Directe entity_ids voor dashboard sliders
                "entity_deliver_to_home": _zp_eid("deliver_to_home"),
                "entity_solar_charge":    _zp_eid("solar_charge"),
                "entity_max_charge_home": _zp_eid("max_charge_home"),
                "entity_control_mode":    _zp_eid("control_mode"),
                "entity_soc":             _zp_eid("soc"),
                "entity_power":           _zp_eid("power"),
                "entity_cycles":          _zp_eid("cycles"),
                "entity_state":           _zp_eid("state"),
            }

        return {
            "action":           bs.get("action"),
            "reason":           bs.get("reason"),
            "human_reason":     bs.get("human_reason", "") or _forecast_data.get("action_human_reason", ""),
            "soc_pct":          soc_pct,
            "schedule_date":    bs.get("schedule_date"),
            "schedule":         bs.get("schedule", []),
            "charge_hours":     bs.get("charge_hours"),
            "discharge_hours":  bs.get("discharge_hours"),
            "plan_accuracy_pct":bs.get("plan_accuracy_pct"),
            "season":           bs.get("season"),
            "season_reason":    bs.get("season_reason"),
            "season_auto":      bs.get("season_auto"),
            "discharge_window": bs.get("discharge_window"),
            "batteries":        [
                {
                    "label":    b.get("label"),
                    "soc_pct":  b.get("soc_pct"),
                    "power_w":  b.get("power_w"),
                    "action":   b.get("action"),
                    "reason":   b.get("reason"),
                }
                for b in bats
            ] if bats else None,
            "zonneplan":            zonneplan_info,
            "battery_providers":    bp,  # volledige registry info incl. providers list & warnings
            "_seq":           getattr(self.coordinator, "_coordinator_tick", 0),
        }
# ═══════════════════════════════════════════════════════════════════════════════
# v1.10.2 — Solar Intelligence: per-inverter profile + system overview
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSSolarSystemSensor(CoordinatorEntity, SensorEntity):
    """
    Fleet-wide solar intelligence overview.

    State = total current PV production (W).
    Attributes expose the combined learned knowledge across all inverters:
      - Total estimated panel capacity (Wp)
      - All-time peak production (W)
      - How many inverters are confident / learning
      - Whether any inverter is clipping right now
      - Total orientation learning progress (%)

    This is the 'wow' sensor: shows what the system has learned automatically
    without any manual configuration.
    """
    _attr_name = "CloudEMS Solar · System Intelligence"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_system"
        # v4.5.4: explicit entity_id — dashboard uses sensor.cloudems_solar_system
        self.entity_id = "sensor.cloudems_solar_system"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def _invs(self) -> list:
        return (self.coordinator.data or {}).get("inverter_data", [])

    @property
    def native_value(self):
        invs = self._invs
        # Return 0.0 when no inverter data yet (e.g. cold start) so card
        # does not show "geen omvormer geconfigureerd". Return None only
        # when coordinator has no data at all.
        if self.coordinator.data is None:
            return None
        return round(sum(i.get("current_w", 0) for i in invs), 1)

    @property
    def extra_state_attributes(self):
        invs = self._invs
        total_wp    = sum(i.get("estimated_wp", 0) for i in invs)
        total_peak  = sum(i.get("peak_w", 0) for i in invs)
        n_confident = sum(1 for i in invs if i.get("confident"))
        n_orient    = sum(1 for i in invs if i.get("orientation_confident"))
        clipping_any = any(i.get("clipping") for i in invs)
        avg_orient_pct = (
            round(sum(i.get("orientation_learning_pct", 0) for i in invs) / len(invs))
            if invs else 0
        )
        phases_known = {i.get("label"): i.get("phase") for i in invs if i.get("phase_certain")}
        return {
            "inverter_count":         len(invs),
            "total_estimated_wp":     round(total_wp, 0),
            "total_peak_w":           round(total_peak, 1),
            "inverters_confident":    n_confident,
            "inverters_orient_known": n_orient,
            "clipping_active":        clipping_any,
            "orientation_progress_pct": avg_orient_pct,
            "phases_detected":        phases_known,
            "inverters": [
                {
                    "label":                    i.get("label"),
                    "current_w":                i.get("current_w"),
                    "peak_w":                   i.get("peak_w"),
                    "peak_w_7d":                i.get("peak_w_7d"),
                    "rated_power_w":            i.get("rated_power_w"),
                    "clipping_ceiling_w":       i.get("clipping_ceiling_w"),
                    "utilisation_pct":          i.get("utilisation_pct"),
                    "estimated_wp":             i.get("estimated_wp"),
                    "azimuth_compass":          i.get("azimuth_compass"),
                    "azimuth_learned":          i.get("azimuth_learned"),
                    "tilt_deg":                 i.get("tilt_deg"),
                    "tilt_learned":             i.get("tilt_learned"),
                    "phase":                    i.get("phase"),
                    "phase_certain":            i.get("phase_certain"),
                    "phase_display":            i.get("phase_display"),
                    "phase_confidence":         i.get("phase_confidence", 0.0),
                    "phase_provisional":        i.get("phase_provisional", True),
                    "clipping":                 i.get("clipping"),
                    "orientation_confident":    i.get("orientation_confident"),
                    "orientation_learning_pct": i.get("orientation_learning_pct", 0),
                    "clear_sky_samples":        i.get("clear_sky_samples"),
                    "orientation_samples_needed": i.get("orientation_samples_needed"),
                }
                for i in invs
            ],
        }


class CloudEMSInverterProfileSensor(CoordinatorEntity, SensorEntity):
    """
    Deep solar intelligence for a single PV inverter.

    State = current power (W).

    Attributes show everything the system has learned automatically:
      • Peak Wp estimate (no nameplate needed!)
      • Phase detection via current correlation + vote counts
      • Azimuth & tilt (manual override OR self-learned from yield curve)
      • Compass direction label (Z, ZZW, etc.)
      • Per-hour yield fraction curve (for visualisation)
      • Peak production hour of the day
      • Orientation learning progress (%)
      • Clipping detection
    """
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_SOLAR

    def __init__(self, coord, entry, inv_entity_id: str):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_entity_id
        self._attr_unique_id = f"{entry.entry_id}_inv_profile_{inv_entity_id}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    def _inv(self) -> dict:
        for i in (self.coordinator.data or {}).get("inverter_data", []):
            if i.get("entity_id") == self._inv_id:
                return i
        return {}

    @property
    def name(self):
        label = self._inv().get("label") or self._inv_id
        return f"CloudEMS Solar · {label} Profiel"

    @property
    def native_value(self):
        return self._inv().get("current_w")

    @property
    def extra_state_attributes(self):
        i = self._inv()
        az = i.get("azimuth_deg")
        az_l = i.get("azimuth_learned")
        ti = i.get("tilt_deg")
        ti_l = i.get("tilt_learned")
        confident = i.get("orientation_confident", False)
        n_samples = i.get("clear_sky_samples", 0)

        # Effective values: manual config > learned > None
        az_eff = az if az is not None else az_l
        ti_eff = ti if ti is not None else ti_l

        if az is not None and az != az_l:
            az_source = "manueel"
        elif az_l is not None:
            az_source = "bevestigd" if confident else f"voorlopig ({n_samples} metingen)"
        else:
            az_source = "onbekend"

        if ti is not None and ti != ti_l:
            ti_source = "manueel"
        elif ti_l is not None:
            ti_source = "bevestigd" if confident else f"voorlopig ({n_samples} metingen)"
        else:
            ti_source = "onbekend"

        # Compass label for provisional azimuth
        def _az_compass(deg):
            if deg is None:
                return "onbekend"
            dirs = ["N","NNO","NO","ONO","O","OZO","ZO","ZZO","Z","ZZW","ZW","WZW","W","WNW","NW","NNW"]
            return dirs[round(deg / 22.5) % 16]

        az_compass = i.get("azimuth_compass") or _az_compass(az_eff)
        votes = i.get("phase_votes") or {}
        total_v = i.get("phase_total_votes", 0) or 1
        return {
            # Power & utilisation
            "utilisation_pct":        i.get("utilisation_pct"),
            "clipping":               i.get("clipping", False),
            "clipping_ceiling_w":     i.get("clipping_ceiling_w"),
            "rated_power_w":          i.get("rated_power_w"),
            "peak_w_alltime":         i.get("peak_w"),
            "peak_w_7d":              i.get("peak_w_7d"),
            "estimated_wp":           i.get("estimated_wp"),
            # Orientation
            "azimuth_deg":            az_eff,
            "azimuth_learned":        az_l,
            "azimuth_source":         az_source,
            "azimuth_compass":        az_compass,
            "tilt_deg":               ti_eff,
            "tilt_learned":           ti_l,
            "tilt_source":            ti_source,
            "orientation_confident":  i.get("orientation_confident", False),
            "clear_sky_days":         i.get("clear_sky_samples", 0),
            "orientation_progress_pct": min(100, round(i.get("clear_sky_samples", 0) / 3600 * 100, 1)),
            "orientation_samples_needed": 3600,
            "clear_sky_days_needed":  i.get("orientation_samples_needed", 30),
            "orientation_progress_pct": i.get("orientation_learning_pct", 0),
            "peak_production_hour":   i.get("peak_production_hour"),
            "hourly_yield_fraction":  i.get("hourly_yield_fraction", {}),
            # Phase
            "phase":                  i.get("phase", "unknown"),
            "phase_certain":          i.get("phase_certain", False),
            "phase_vote_l1_pct":      round(votes.get("L1", 0) / total_v * 100, 0),
            "phase_vote_l2_pct":      round(votes.get("L2", 0) / total_v * 100, 0),
            "phase_vote_l3_pct":      round(votes.get("L3", 0) / total_v * 100, 0),
            "phase_total_votes":      i.get("phase_total_votes", 0),
            # Learning
            "learning_samples":       i.get("samples", 0),
            "learning_confident":     i.get("confident", False),
        }


class CloudEMSInverterClippingBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    ON when an inverter is actively clipping (panels generate more than inverter capacity).
    Use in automations or alerts: dim the inverter, alert the user, or log for diagnostics.
    """
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:solar-panel"

    def __init__(self, coord, entry, inv_entity_id: str):
        super().__init__(coord)
        self._entry  = entry
        self._inv_id = inv_entity_id
        self._attr_unique_id = f"{entry.entry_id}_inv_clipping_{inv_entity_id}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    def _inv(self) -> dict:
        for i in (self.coordinator.data or {}).get("inverter_data", []):
            if i.get("entity_id") == self._inv_id:
                return i
        return {}

    @property
    def name(self):
        label = self._inv().get("label") or self._inv_id
        return f"CloudEMS Solar · {label} Clipping"

    @property
    def is_on(self) -> bool:
        return bool(self._inv().get("clipping", False))

    @property
    def extra_state_attributes(self):
        i = self._inv()
        return {
            "current_w":       i.get("current_w"),
            "peak_w":          i.get("peak_w"),
            "utilisation_pct": i.get("utilisation_pct"),
            "estimated_wp":    i.get("estimated_wp"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.10.3 — Self-learning Intelligence Sensors (zero-config)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSHomeBaselineSensor(CoordinatorEntity, SensorEntity):
    """
    State = current deviation from learned normal (W, positive = more than usual).
    Anomaly = True when consuming significantly more than the learned pattern.

    Attributes contain the full picture: expected, current, standby baseline,
    occupancy inference, and standby-hunters (always-on wasters).
    """
    _attr_name      = "CloudEMS Home Baseline Anomalie"  # slug → sensor.cloudems_home_baseline_anomalie
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:home-lightning-bolt-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_home_baseline"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def _bl(self) -> dict:
        return (self.coordinator.data or {}).get("baseline", {})

    @property
    def native_value(self):
        return self._bl.get("deviation_w", 0.0)

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_home_baseline"
        self._anomaly_start_ts = 0.0
        self._last_notify_ts   = 0.0

    @property
    def extra_state_attributes(self):
        import time
        b       = self._bl
        anomaly = b.get("anomaly", False)
        dev_w   = b.get("deviation_w", 0.0) or 0.0
        exp_w   = b.get("expected_w", 0.0) or 0.0
        cur_w   = b.get("current_w", 0.0) or 0.0
        now     = time.time()

        if anomaly:
            if self._anomaly_start_ts == 0:
                self._anomaly_start_ts = now
            duration_min = round((now - self._anomaly_start_ts) / 60)
            if duration_min >= 15 and (now - self._last_notify_ts) > 3600:
                self._last_notify_ts = now
                try:
                    self.coordinator.hass.components.persistent_notification.async_create(
                        message=(
                            f"⚠️ Ongewoon hoog netverbruik al **{duration_min} minuten**.\n\n"
                            f"Verwacht: {round(exp_w)} W · Huidig: {round(cur_w)} W\n"
                            f"Afwijking: **+{round(dev_w)} W**\n\n"
                            "Controleer of er een apparaat aan staat dat dat niet hoort."
                        ),
                        title="CloudEMS — Anomalie netverbruik",
                        notification_id="cloudems_anomalie_grid",
                    )
                except Exception:
                    pass
        else:
            self._anomaly_start_ts = 0.0
            duration_min = 0

        return {
            "anomaly":           anomaly,
            "current_w":         cur_w,
            "expected_w":        exp_w,
            "deviation_w":       dev_w,
            "sigma_w":           b.get("sigma_w"),
            "sigma_threshold":   b.get("sigma_threshold", 2.5),
            "standby_w":         b.get("standby_w"),
            "standby_samples":   b.get("standby_samples"),
            "is_home":           b.get("is_home"),
            "model_ready":       b.get("model_ready", False),
            "trained_slots":     b.get("trained_slots", 0),
            "total_slots":       168,
            "training_pct":      round(b.get("trained_slots", 0) / 168 * 100, 0),
            "standby_hunters":   b.get("standby_hunters", []),
            "aanhoudend_min":    duration_min,
            "status": (
                f"⚠️ +{round(dev_w)}W boven normaal ({duration_min} min)"
                if anomaly else "✅ Normaal verbruik"
            ),
        }




class CloudEMSStandbyHunterSensor(CoordinatorEntity, SensorEntity):
    """
    State = estimated always-on standby load (W).
    Attributes list individual appliances that appear to never switch off
    during deep-night hours — candidates for energy waste.
    """
    _attr_name = "CloudEMS Standby Verbruik (Altijd Aan)"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:power-sleep"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_standby_hunter"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("baseline", {}).get("standby_w")

    @property
    def extra_state_attributes(self):
        b = (self.coordinator.data or {}).get("baseline", {})
        hunters = b.get("standby_hunters", [])
        return {
            "standby_w":       b.get("standby_w"),
            "standby_samples": b.get("standby_samples", 0),
            "suspicious_devices": hunters,
            "suspicious_count":   len(hunters),
            "tip": "Apparaten die 's nachts meer verbruiken dan de standby-drempel — controleer of ze uit kunnen.",
        }


class CloudEMSEVSessionSensor(CoordinatorEntity, SensorEntity):
    """
    State = predicted kWh for the next EV charging session (learned from history).
    When a session is active, state = kWh loaded so far.

    Attributes include typical schedule, cost history, and current session info.
    """
    _attr_name = "CloudEMS EV · Sessie Leermodel"
    _attr_device_class = None
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_session"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_EV)

    @property
    def _ev(self) -> dict:
        return (self.coordinator.data or {}).get("ev_session", {})

    @property
    def native_value(self):
        ev = self._ev
        if ev.get("session_active"):
            return ev.get("session_kwh_so_far", 0.0)
        return ev.get("predicted_kwh")

    @property
    def extra_state_attributes(self):
        ev = self._ev
        return {
            "session_active":       ev.get("session_active", False),
            "session_current_a":    ev.get("session_current_a"),
            "session_kwh_so_far":   ev.get("session_kwh_so_far"),
            "session_cost_so_far":  ev.get("session_cost_so_far"),
            "predicted_kwh":        ev.get("predicted_kwh"),
            "predicted_duration_h": ev.get("predicted_duration_h"),
            "typical_start_hour":   ev.get("typical_start_hour"),
            "typical_weekdays":     ev.get("typical_weekdays", []),
            "sessions_total":       ev.get("sessions_total", 0),
            "model_ready":          ev.get("model_ready", False),
            "avg_cost_per_session": ev.get("avg_cost_per_session"),
            "recent_sessions":      ev.get("recent_sessions", []),
        }


class CloudEMSNILMScheduleSensor(CoordinatorEntity, SensorEntity):
    """
    State = number of NILM devices with a reliable learned schedule.
    Attributes contain the full schedule summary per device:
    which weekday + hour they typically run.
    """
    _attr_name = "CloudEMS NILM · Apparaat Schemas"
    _attr_icon = "mdi:calendar-clock"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_schedule"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def _schedules(self) -> list:
        return (self.coordinator.data or {}).get("nilm_schedule", [])

    @property
    def native_value(self) -> int:
        return sum(1 for s in self._schedules if s.get("ready"))

    @property
    def extra_state_attributes(self):
        schedules = self._schedules
        # Flag any devices running at unusual times right now
        unusual = [
            d for d in (self.coordinator.data or {}).get("nilm_devices", [])
            if d.get("schedule_unusual")
        ]
        # Trim to essential summary fields — stay under HA 16 KB recorder limit
        _KEEP = {"device_id", "label", "device_type", "ready",
                 "peak_weekday", "peak_hour", "observations"}
        schedules_trimmed = [
            {k: v for k, v in s.items() if k in _KEEP}
            for s in schedules[:40]
        ]
        return {
            "schedules":         schedules_trimmed,
            "total_devices":     len(schedules),
            "schedules_ready":   sum(1 for s in schedules if s.get("ready")),
            "unusual_now":       [d.get("user_name") or d.get("name", d.get("device_type")) for d in unusual],
            "unusual_count":     len(unusual),
        }


class CloudEMSWeatherCalibrationSensor(CoordinatorEntity, SensorEntity):
    """
    State = overall weather calibration factor (actual / open-meteo-expected).
    <1.0 means the installation produces less than the model expects
    (e.g. partial shading, non-optimal tilt).
    >1.0 means it over-performs (e.g. cooler climate, very clean panels).

    After ~30 sunny days this calibration makes the PV forecast significantly
    more accurate than a generic irradiance model.
    """
    _attr_name = "CloudEMS PV · Weerkalibratie"
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_weather_calibration"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def _calib(self) -> dict:
        return (self.coordinator.data or {}).get("weather_calibration", {})

    @property
    def native_value(self):
        invs = self._calib.get("inverters", [])
        factors = [i["calib_factor"] for i in invs if i.get("calib_factor") is not None]
        if not factors:
            return None
        return round(sum(factors) / len(factors), 3)

    @property
    def extra_state_attributes(self):
        c = self._calib
        return {
            "global_confident":  c.get("global_confident", False),
            "global_samples":    c.get("global_samples", 0),
            "samples_needed":    30,
            "progress_pct":      round(min(100, c.get("global_samples", 0) / 30 * 100), 0),
            "inverters":         c.get("inverters", []),
            "interpretation":    (
                "installatie presteert beter dan model verwacht" if (self.native_value or 1) > 1.05
                else "installatie presteert slechter dan model verwacht" if (self.native_value or 1) < 0.90
                else "installatie presteert conform model"
            ),
        }


class CloudEMSSolarROISensor(CoordinatorEntity, SensorEntity):
    """
    State = total euro saved / earned by the solar installation since CloudEMS
    started tracking (self-import saving + export revenue).

    Attributes show the daily/monthly rate and an extrapolated payback estimate.
    This requires no installation cost input — it simply tracks value generated.
    """
    _attr_name = "CloudEMS PV · Opbrengst & Terugverdientijd"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:cash-plus"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_solar_roi"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        # Use cost tracking data as proxy for cumulative savings
        d = self.coordinator.data or {}
        cost_month = d.get("cost_month_eur", 0.0)
        # Export revenue estimate: export_kwh — avg_price
        price_info = d.get("energy_price") or {}
        avg_price  = price_info.get("avg_today") or 0.12
        invs = d.get("inverter_data", [])
        total_peak_w = sum(i.get("peak_w", 0) for i in invs)
        # Very rough: daily PV value ≈ peak_kWp — 3h_equivalent — avg_price
        if total_peak_w > 0:
            daily_eur = (total_peak_w / 1000) * 3.0 * avg_price
            return round(daily_eur, 2)
        return None

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        pi = d.get("energy_price") or {}
        cfg = self.coordinator._config

        # ── Prijs bepalen ──────────────────────────────────────────────────
        # Vaste contract: gebruik de geconfigureerde importprijs (1 getal, altijd correct)
        # Dynamisch:      gebruik de all-in prijs inclusief belasting/leverancier-markup
        #                 én toon 30-daags rollend gemiddelde ipv. enkel vandaag.
        from .const import (
            CONF_CONTRACT_TYPE, CONTRACT_TYPE_FIXED,
            CONF_FIXED_IMPORT_PRICE,
        )
        contract_type = cfg.get(CONF_CONTRACT_TYPE, "dynamic")
        is_fixed = (contract_type == CONTRACT_TYPE_FIXED)

        if is_fixed:
            # Vaste prijs — direct uit config
            roi_price     = float(cfg.get(CONF_FIXED_IMPORT_PRICE, 0.25))
            price_label   = "vast"
            price_display = roi_price
        else:
            # Dynamisch — gebruik all-in gemiddelde van vandaag als proxy;
            # bij voorkeur het 30-daags rollend gemiddelde als dat beschikbaar is.
            rolling_avg = pi.get("rolling_avg_30d_all_in")
            if rolling_avg and rolling_avg > 0.02:
                roi_price   = float(rolling_avg)
                price_label = "gem. 30d (all-in)"
            else:
                # Fallback: all-in gemiddelde van vandaag
                all_in_today = [s.get("price_all_in", s.get("price", 0))
                                for s in pi.get("today_all_display", pi.get("today_all", []))]
                if all_in_today:
                    roi_price = sum(all_in_today) / len(all_in_today)
                else:
                    # Laatste redmiddel: avg_today + geleerde totale opslag
                    opslag = pi.get("total_opslag_kwh") or pi.get("tax_per_kwh", 0.1228)
                    base   = pi.get("avg_today") or 0.10
                    roi_price = base + opslag
                price_label = "gem. vandaag (all-in)"
            price_display = roi_price

        # ── Opbrengst & investering ────────────────────────────────────────
        invs         = d.get("inverter_data", [])
        total_wp     = sum(i.get("estimated_wp", 0) for i in invs)
        total_peak_w = sum(i.get("peak_w", 0) for i in invs)

        # NL gemiddeld: 850 kWh/kWp/jaar
        NL_YIELD_KWH_KWP = 850
        annual_kwh = (total_wp / 1000) * NL_YIELD_KWH_KWP if total_wp > 0 else None
        annual_eur = round(annual_kwh * roi_price, 0) if annual_kwh else None

        # ── Uitbreidingsadvies ─────────────────────────────────────────────
        # Optimaal PV-vermogen = jaarverbruik / NL_YIELD zodat ~100% van verbruik
        # gedekt wordt. Advies = optimaal - huidig, afgerond op 500 Wp stappen.
        # Jaarverbruik: probeer uit baseline expected_w (gemiddeld), anders DSMR totaal.
        baseline    = d.get("baseline") or {}
        expected_w  = float(baseline.get("expected_w") or 0)

        # Schat jaarverbruik: expected_w = gemiddeld vermogen huis (W)
        # kWh/jaar = W — 8760 / 1000
        if expected_w > 50:                       # basislijn geleerd (> 50W = plausibel)
            annual_consumption_kwh = expected_w * 8760 / 1000
        else:
            # Geen basislijn — probeer DSMR totaal afname (vandaag — 365 als proxy)
            consumption_today = d.get("energy_consumed_today_kwh") or 0
            if consumption_today > 0.5:
                annual_consumption_kwh = consumption_today * 365
            else:
                annual_consumption_kwh = None

        expansion_advice_wp   = None
        expansion_advice_kwp  = None
        optimal_wp            = None
        self_sufficiency_pct  = None

        if annual_consumption_kwh and annual_consumption_kwh > 100:
            optimal_wp = (annual_consumption_kwh / NL_YIELD_KWH_KWP) * 1000  # Wp
            delta_wp   = optimal_wp - total_wp
            if delta_wp > 200:
                # Afronden op 500 Wp stappen (= typisch 1-2 panelen)
                expansion_advice_wp  = round(delta_wp / 500) * 500
                expansion_advice_kwp = round(expansion_advice_wp / 1000, 1)
            else:
                expansion_advice_wp  = 0   # al optimaal of overdimensioneerd
                expansion_advice_kwp = 0.0
            if total_wp > 0:
                self_sufficiency_pct = round(min(100.0, (annual_kwh / annual_consumption_kwh) * 100), 1)

        cf = d.get("cost_forecast") or {}
        return {
            "estimated_wp_total":        round(total_wp, 0),
            "peak_w_alltime":            round(total_peak_w, 1),
            "annual_yield_kwh_est":      round(annual_kwh, 0) if annual_kwh else None,
            "annual_value_eur_est":      annual_eur,
            "roi_price_eur_kwh":         round(roi_price, 4),
            "roi_price_label":           price_label,
            "is_fixed_contract":         is_fixed,
            # Legacy key — zelfde waarde als roi_price zodat dashboard niet breekt
            "avg_price_eur_kwh":         round(roi_price, 4),
            # Uitbreiding
            "annual_consumption_kwh_est":round(annual_consumption_kwh, 0) if annual_consumption_kwh else None,
            "optimal_wp":                round(optimal_wp, 0) if optimal_wp else None,
            "expansion_advice_wp":       expansion_advice_wp,
            "expansion_advice_kwp":      expansion_advice_kwp,
            "self_sufficiency_pct":      self_sufficiency_pct,
            # Overig
            "daily_forecast_cost_eur":   cf.get("today_forecast_eur"),
            "monthly_cost_eur":          d.get("cost_month_eur"),
            "note": f"Prijs: {price_label} | Opbrengst: {NL_YIELD_KWH_KWP} kWh/kWp/jaar (NL gemiddeld)",
        }


# ══════════════════════════════════════════════════════════════════════════════
# v1.11.0 — 8 New Intelligence Sensors
# ══════════════════════════════════════════════════════════════════════════════

class CloudEMSThermalModelSensor(CoordinatorEntity, SensorEntity):
    """Thermische verliescoëfficiënt van het huis in W/°C."""
    _attr_name = "CloudEMS · Thermisch Huismodel"
    _attr_native_unit_of_measurement = "W/K"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_thermal_model"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        t = (self.coordinator.data or {}).get("thermal_model", {})
        v = t.get("w_per_k", 0.0)
        return round(v, 1) if v else None

    @property
    def extra_state_attributes(self):
        t = (self.coordinator.data or {}).get("thermal_model", {})
        return {
            "rating":              t.get("rating", "onbekend"),
            "advice":              t.get("advice", ""),
            "samples":             t.get("samples", 0),
            "samples_needed":      t.get("samples_needed", 20),
            "progress_pct":        t.get("progress_pct", 0),
            "reliable":            t.get("reliable", False),
            "heating_days":        t.get("heating_days", 0),
            "last_heating_w":      t.get("last_heating_w", 0),
            "last_outside_temp_c": t.get("last_outside_temp_c"),
            "benchmark_excellent": 100,
            "benchmark_good":      200,
            "benchmark_average":   350,
        }


class CloudEMSFlexScoreSensor(CoordinatorEntity, SensorEntity):
    """Beschikbaar flexibel vermogen in kW."""
    _attr_name = "CloudEMS Flexibel Vermogen"
    _attr_native_unit_of_measurement = "kW"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_flex_score"
        self.entity_id = "sensor.cloudems_flexibel_vermogen"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        f = (self.coordinator.data or {}).get("flex_score", {})
        return f.get("total_kw", 0.0)

    @property
    def extra_state_attributes(self):
        f = (self.coordinator.data or {}).get("flex_score", {})
        return {
            "battery_kw":   f.get("battery_kw", 0.0),
            "ev_kw":        f.get("ev_kw", 0.0),
            "boiler_kw":    f.get("boiler_kw", 0.0),
            "nilm_kw":      f.get("nilm_kw", 0.0),
            "breakdown":    f.get("breakdown", ""),
            "components":   f.get("components", []),
        }


class CloudEMSPVHealthSensor(CoordinatorEntity, SensorEntity):
    """PV paneel gezondheid — soiling en degradatie detectie."""
    _attr_name = "CloudEMS PV · Paneelgezondheid"
    _attr_icon = "mdi:solar-panel"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_health"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        p = (self.coordinator.data or {}).get("pv_health", {})
        if p.get("any_alert"):
            return "alert"
        invs = p.get("inverters", [])
        if not invs:
            return "onbekend"
        avg_ratio = sum(i.get("ratio", 1.0) for i in invs) / len(invs)
        return f"{avg_ratio * 100:.0f}%"

    @property
    def extra_state_attributes(self):
        p = (self.coordinator.data or {}).get("pv_health", {})
        return {
            "any_alert":  p.get("any_alert", False),
            "summary":    p.get("summary", ""),
            "inverters":  p.get("inverters", []),
        }


class CloudEMSGasSensor(CoordinatorEntity, SensorEntity):
    """Gasverbruik meter (m³) uit P1 telegram."""
    _attr_name = "CloudEMS Gasstand"  # slug → sensor.cloudems_gasstand
    _attr_native_unit_of_measurement = "m³"
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.GAS
    _attr_icon = "mdi:fire"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_gas_m3"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GAS)

    @property
    def native_value(self):
        g = (self.coordinator.data or {}).get("gas_data", {})
        v = g.get("gas_m3", 0.0)
        return round(v, 3) if v else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        g = data.get("gas_data", {})
        ga = data.get("gas_analysis", {})
        prijs = float(g.get("gas_prijs_per_m3") or 1.25)
        # Gebruik gas_analysis voor periode-data als beschikbaar (nauwkeuriger)
        dag_m3   = float(ga.get("gas_m3_today")  or g.get("dag_m3")   or 0)
        week_m3  = float(ga.get("gas_m3_week")   or g.get("week_m3")  or 0)
        maand_m3 = float(ga.get("gas_m3_month")  or g.get("maand_m3") or 0)
        jaar_m3  = float(ga.get("gas_m3_year")   or g.get("jaar_m3")  or 0)
        attrs = {
            "gas_kwh":           round(g.get("gas_kwh", 0.0), 3),
            "conversion_factor": 9.769,
            "source":            "P1 DSMR (OBIS 0-1:24.2.1)",
            "gas_prijs_per_m3":  prijs,
            # Periode verbruik m³
            "dag_m3":    round(dag_m3, 3),
            "week_m3":   round(week_m3, 3),
            "maand_m3":  round(maand_m3, 3),
            "jaar_m3":   round(jaar_m3, 3),
            # Kosten €
            "dag_eur":   round(dag_m3   * prijs, 2),
            "week_eur":  round(week_m3  * prijs, 2),
            "maand_eur": round(maand_m3 * prijs, 2),
            "jaar_eur":  round(jaar_m3  * prijs, 2),
            # Extra uit gas_analysis
            "efficiency_rating":    ga.get("efficiency_rating"),
            "records_count":        ga.get("records_count", 0),
            "seasonal_forecast_m3": ga.get("seasonal_forecast_m3"),
            # Dagrecords voor drill-down (laatste 30 dagen)
            "day_records":          ga.get("day_records", []),
            # v4.6.388: fibonacci m³/uur resultaten (server-berekend, veilig formaat)
            "gas_fib_hours":        g.get("gas_fib_hours", []),
        }
        return attrs


# ═══════════════════════════════════════════════════════════════════════════════
# v1.13.0 — Energie bronvergelijking: elektriciteit vs. gas per kWh warmte
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEnergySourceSensor(CoordinatorEntity, SensorEntity):
    """
    Vergelijkt de actuele kosten van elektriciteit vs. gas per kWh warmte.

    Rekent gas om van €/m³ → €/kWh (calorische waarde 9,769 kWh/m³, NL-standaard)
    en houdt rekening met rendementen:
      - Gas CV-ketel:         90% rendement → effectief €/kWh = (€/m³ / 9,769) / 0,90
      - Elektrische boiler:   95% rendement (instelbaar)
      - Warmtepomp:           COP 3,5 (instelbaar)

    State = "elektriciteit" | "gas" | "gelijk"
    Gebruik dit voor automaties: verhit boiler via stroom als sensor = "elektriciteit".
    """
    _attr_name      = "CloudEMS · Goedkoopste Warmtebron"
    _attr_icon      = "mdi:heat-wave"
    _attr_device_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_source_compare"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GAS)

    def _get_electricity_price(self) -> Optional[float]:
        """Current electricity price from EPEX sensor (€/kWh, incl. tax)."""
        ep = (self.coordinator.data or {}).get("energy_price", {})
        return ep.get("current")

    def _get_gas_price_m3(self) -> float:
        """Gas price per m³. Try HA sensor first, then fixed config, then default."""
        cfg = self.coordinator._config
        # 1. HA sensor (energy provider app, DSMR, etc.)
        sensor_eid = cfg.get(CONF_GAS_PRICE_SENSOR, "")
        if sensor_eid:
            state = self.hass.states.get(sensor_eid)
            if state and state.state not in ("unavailable", "unknown", ""):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        # 2. Fixed value from config
        fixed = cfg.get(CONF_GAS_PRICE_FIXED, 0.0)
        if fixed and float(fixed) > 0:
            return float(fixed)
        # 3. Default NL indicative price
        return DEFAULT_GAS_PRICE_EUR_M3

    @property
    def native_value(self) -> Optional[str]:
        elec = self._get_electricity_price()
        if elec is None:
            return None

        gas_m3        = self._get_gas_price_m3()
        cfg           = self.coordinator._config
        boiler_eff    = float(cfg.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))
        has_hp        = bool(cfg.get(CONF_HEAT_PUMP_ENTITY, ""))
        _hp_cop_data  = (self.coordinator.data or {}).get("heat_pump_cop", {})
        _learned_cop  = _hp_cop_data.get("cop_current") if _hp_cop_data.get("reliable") else None
        hp_cop        = float(_learned_cop or cfg.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))

        # Gas CV-ketel: €/kWh warmte
        gas_kwh_heat  = (gas_m3 / GAS_KWH_PER_M3) / GAS_BOILER_EFFICIENCY

        # Elektrische boiler (resistief, COP ≈ 1): altijd beschikbaar
        elec_boiler   = elec / boiler_eff

        # Warmtepomp: alleen meenemen als er een WP geconfigureerd is.
        # Zonder WP-entiteit berekenen we de kosten WEL voor de attributen (informatief),
        # maar baseren we de state NIET op de WP — dat zou misleidend zijn.
        elec_hp       = elec / hp_cop

        # Vergelijking: staat = goedkoopste BESCHIKBARE elektrische optie vs. gas
        if has_hp:
            best_elec_kwh    = min(elec_boiler, elec_hp)
            best_elec_source = "warmtepomp" if elec_hp <= elec_boiler else "elektrische_boiler"
        else:
            # Alleen resistief beschikbaar — vergelijk enkel boiler vs. gas
            best_elec_kwh    = elec_boiler
            best_elec_source = "elektrische_boiler"

        if best_elec_kwh < gas_kwh_heat * 0.98:
            return "elektriciteit"
        elif gas_kwh_heat < best_elec_kwh * 0.98:
            return "gas"
        else:
            return "gelijk"

    @property
    def extra_state_attributes(self) -> dict:
        elec = self._get_electricity_price()
        gas_m3 = self._get_gas_price_m3()
        cfg = self.coordinator._config
        boiler_eff = float(cfg.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY))
        has_hp     = bool(cfg.get(CONF_HEAT_PUMP_ENTITY, ""))

        # Gebruik geleerde COP als beschikbaar, anders config/default
        _hp_cop_data  = (self.coordinator.data or {}).get("heat_pump_cop", {})
        _learned_cop  = _hp_cop_data.get("cop_current") if _hp_cop_data.get("reliable") else None
        _cop_source   = "geleerd" if _learned_cop else ("config" if cfg.get(CONF_HEAT_PUMP_COP) else "default")
        hp_cop        = float(_learned_cop or cfg.get(CONF_HEAT_PUMP_COP, DEFAULT_HEAT_PUMP_COP))

        # WP boiler COP: typisch 2.5-3.0 (lager dan lucht/water WP door condensatiewarmte)
        _wp_boiler_cop = float(_hp_cop_data.get("cop_boiler") or cfg.get("heat_pump_boiler_cop", 2.8))

        gas_kwh_raw    = round(gas_m3 / GAS_KWH_PER_M3, 5)
        gas_kwh_heat   = round(gas_kwh_raw / GAS_BOILER_EFFICIENCY, 5)
        elec_boiler    = round(elec / boiler_eff, 5) if elec else None
        elec_hp        = round(elec / hp_cop, 5) if elec else None
        elec_wp_boiler = round(elec / _wp_boiler_cop, 5) if elec else None

        # Savings: positief = elektrisch goedkoper, negatief = gas goedkoper
        savings_boiler = round(gas_kwh_heat - elec_boiler, 5) if elec_boiler else None
        savings_hp     = round(gas_kwh_heat - elec_hp, 5) if elec_hp else None

        # Cheapest available electric source
        if has_hp and elec_hp and elec_boiler:
            cheapest_elec_source = "warmtepomp" if elec_hp <= elec_boiler else "elektrische_boiler"
            cheapest_elec_kwh    = min(elec_boiler, elec_hp)
        else:
            cheapest_elec_source = "elektrische_boiler"
            cheapest_elec_kwh    = elec_boiler

        # Recommendation: specific about WHICH option and WHY
        state = self.native_value
        if state == "elektriciteit":
            if cheapest_elec_source == "warmtepomp":
                recommendation = (
                    f"Warmtepomp is goedkoopst: €{elec_hp:.4f}/kWh warmte "
                    f"vs. gas €{gas_kwh_heat:.4f}/kWh — besparing {savings_hp*100:.1f} ct/kWh."
                )
            else:
                recommendation = (
                    f"Elektrische boiler is goedkoper dan gas: €{elec_boiler:.4f}/kWh warmte "
                    f"vs. gas €{gas_kwh_heat:.4f}/kWh — besparing {savings_boiler*100:.1f} ct/kWh."
                )
        elif state == "gas":
            if has_hp:
                cheapest_electric_str = f"warmtepomp €{elec_hp:.4f}" if elec_hp < elec_boiler else f"boiler €{elec_boiler:.4f}"
                recommendation = (
                    f"Gas is goedkoper: CV €{gas_kwh_heat:.4f}/kWh warmte "
                    f"vs. {cheapest_electric_str}/kWh — gebruik gas."
                )
            else:
                recommendation = (
                    f"Gas is goedkoper: CV €{gas_kwh_heat:.4f}/kWh warmte "
                    f"vs. elektrische boiler €{elec_boiler:.4f}/kWh — gebruik gas."
                )
        else:
            recommendation = "Elektriciteit en gas zijn nagenoeg even duur per kWh warmte."

        source_eid = cfg.get(CONF_GAS_PRICE_SENSOR, "")
        source = "sensor" if source_eid else ("config" if cfg.get(CONF_GAS_PRICE_FIXED) else "default")

        return {
            # Elektriciteit
            "elec_price_kwh":                 elec,
            "elec_boiler_per_kwh_heat":       elec_boiler,
            "elec_hp_per_kwh_heat":           elec_hp if has_hp else None,
            "elec_wp_boiler_per_kwh_heat":    elec_wp_boiler if has_hp else None,
            "electric_boiler_efficiency_pct": round(boiler_eff * 100),
            "heat_pump_cop":                  round(hp_cop, 2) if has_hp else None,
            "heat_pump_cop_source":           _cop_source if has_hp else None,
            "heat_pump_boiler_cop":           round(_wp_boiler_cop, 2) if has_hp else None,
            "has_heat_pump":                  has_hp,
            "cheapest_electric_source":       cheapest_elec_source,
            # Gas
            "gas_price_m3":                   round(gas_m3, 4),
            "gas_kwh_per_m3":                 GAS_KWH_PER_M3,
            "gas_price_per_kwh_raw":          gas_kwh_raw,
            "gas_cv_efficiency_pct":          round(GAS_BOILER_EFFICIENCY * 100),
            "gas_per_kwh_heat":               gas_kwh_heat,
            "gas_price_source":               source,
            # Vergelijking
            "savings_electric_boiler_vs_gas": savings_boiler,
            "savings_heat_pump_vs_gas":       savings_hp if has_hp else None,
            "recommendation":                 recommendation,
        }


class CloudEMSSelfConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Zelfconsumptiegraad: % van PV-productie direct verbruikt."""
    _attr_name = "CloudEMS PV · Zelfconsumptiegraad"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_self_consumption"
        # v4.5.4: explicit entity_id — dashboard uses sensor.cloudems_self_consumption
        self.entity_id = "sensor.cloudems_self_consumption"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        return sc.get("ratio_pct", None)

    @property
    def extra_state_attributes(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        return {
            "export_pct":         sc.get("export_pct"),
            "pv_today_kwh":       sc.get("pv_today_kwh"),
            "self_consumed_kwh":  sc.get("self_consumed_kwh"),
            "exported_kwh":       sc.get("exported_kwh"),
            "best_solar_hour":    sc.get("best_solar_hour"),
            "best_solar_label":   sc.get("best_solar_label"),
            "advice":             sc.get("advice", ""),
            "monthly_saving_eur": sc.get("monthly_saving_eur"),
        }


class CloudEMSSelfSufficiencySensor(CoordinatorEntity, SensorEntity):
    """Zelfvoorzieningsgraad: % van verbruik gedekt door eigen PV."""
    _attr_name = "CloudEMS PV · Zelfvoorzieningsgraad"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:solar-power-variant"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_self_sufficiency"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        # self_sufficiency = zelfconsumptie / totaal verbruik * 100
        return sc.get("self_sufficiency_pct", None)

    @property
    def extra_state_attributes(self):
        sc = (self.coordinator.data or {}).get("self_consumption", {})
        return {
            "total_consumption_kwh": sc.get("total_consumption_kwh"),
            "self_covered_kwh":      sc.get("self_consumed_kwh"),
            "grid_import_kwh":       sc.get("grid_import_kwh"),
            "advice":                sc.get("advice", ""),
        }



class CloudEMSDayTypeSensor(CoordinatorEntity, SensorEntity):
    """Dag-type classificatie: werkdag-thuis, kantoor, weekend, vakantie."""
    _attr_name = "CloudEMS · Dag-type Classificatie"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_day_type"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self):
        dt = (self.coordinator.data or {}).get("day_type", {})
        return dt.get("today_type", "unknown")

    @property
    def extra_state_attributes(self):
        dt = (self.coordinator.data or {}).get("day_type", {})
        return {
            "today_label":        dt.get("today_label", "Onbekend"),
            "confidence":         dt.get("confidence", 0.0),
            "expected_kwh":       dt.get("expected_kwh"),
            "total_days_learned": dt.get("total_days_learned", 0),
            "advice":             dt.get("advice", ""),
        }


class CloudEMSDeviceDriftSensor(CoordinatorEntity, SensorEntity):
    """Apparaat efficiëntie drift detectie — slijtage, kalk, defect."""
    _attr_name = "CloudEMS · Apparaat Efficientiedrift"
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_device_drift"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("device_drift", {})
        if d.get("any_alert"):
            return "alert"
        if d.get("any_warning"):
            return "warning"
        devs = d.get("devices", [])
        return f"ok ({len(devs)} apparaten)" if devs else "geen data"

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("device_drift", {})
        # Trim to essential fields only — stay under HA 16 KB recorder limit
        _KEEP = {"device_id", "label", "baseline_w", "current_w",
                 "drift_pct", "level", "message", "baseline_frozen",
                 "samples_total", "samples_needed"}
        devices_trimmed = [
            {k: v for k, v in dev.items() if k in _KEEP}
            for dev in (d.get("devices") or [])[:30]
        ]
        return {
            "any_alert":    d.get("any_alert", False),
            "any_warning":  d.get("any_warning", False),
            "summary":      d.get("summary", ""),
            "trained_count":d.get("trained_count", 0),
            "total_count":  d.get("total_count", 0),
            "devices":      devices_trimmed,
        }


class CloudEMSPhaseMigrationSensor(CoordinatorEntity, SensorEntity):
    """Fase-migratie advies voor betere fase-balans."""
    _attr_name = "CloudEMS · Fase-Migratie Advies"
    _attr_icon = "mdi:swap-horizontal-bold"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_phase_migration"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        pm = (self.coordinator.data or {}).get("phase_migration", {})
        if pm.get("has_advice"):
            top = (pm.get("advices") or [{}])[0]
            text = (
                f"Verplaats {top.get('device_label','?')} "
                f"van {top.get('from_phase','?')} naar {top.get('to_phase','?')} "
                f"(+{top.get('balance_gain_pct',0):.0f}%)"
            )
        else:
            text = pm.get("summary", "geen advies") or "geen advies"
        return text[:255]

    @property
    def extra_state_attributes(self):
        pm = (self.coordinator.data or {}).get("phase_migration", {})
        if pm.get("has_advice"):
            top = (pm.get("advices") or [{}])[0]
            full_advice = (
                f"Verplaats {top.get('device_label','?')} "
                f"van {top.get('from_phase','?')} naar {top.get('to_phase','?')} "
                f"(+{top.get('balance_gain_pct',0):.0f}%)"
            )
        else:
            full_advice = pm.get("summary", "")
        return {
            "has_advice":       pm.get("has_advice", False),
            "summary":          pm.get("summary", ""),
            "full_advice":      full_advice,
            "overloaded_phase": pm.get("overloaded_phase"),
            "lightest_phase":   pm.get("lightest_phase"),
            "imbalance_a":      pm.get("imbalance_a", 0.0),
            "advices":          pm.get("advices", []),
        }


class CloudEMSMicroMobilitySensor(CoordinatorEntity, SensorEntity):
    """E-bike en scooter laadtracker voor het gezin."""
    _attr_name = "CloudEMS Micro-Mobiliteit"  # slug → sensor.cloudems_micro_mobiliteit
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:bicycle-electric"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_micro_mobility"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_EV)

    @property
    def native_value(self):
        m = (self.coordinator.data or {}).get("micro_mobility", {})
        return m.get("total_kwh", 0.0)

    @property
    def extra_state_attributes(self):
        m = (self.coordinator.data or {}).get("micro_mobility", {})
        return {
            "vehicles_today":   m.get("vehicles_today", 0),
            "kwh_today":        m.get("kwh_today", 0.0),
            "cost_today_eur":   m.get("cost_today_eur", 0.0),
            "active_sessions":  m.get("active_sessions", []),
            "active_session_count": len(m.get("active_sessions", [])),
            "sessions_today":   m.get("sessions_today", []),
            "vehicle_profiles": m.get("vehicle_profiles", []),
            "best_charge_hour": m.get("best_charge_hour"),
            "advice":           m.get("advice", ""),
            "total_sessions":   m.get("total_sessions", 0),
            "weekly_kwh_avg":   m.get("weekly_kwh_avg", 0.0),
        }


class CloudEMSNotificationSensor(CoordinatorEntity, SensorEntity):
    """Telt actieve CloudEMS-meldingen en toont ze als attributen."""
    _attr_name = "CloudEMS · Actieve Meldingen"
    _attr_native_unit_of_measurement = "meldingen"
    _attr_icon = "mdi:bell-ring"
    _attr_state_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_notifications"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("notifications", {}).get("active_count", 0)

    @property
    def state_class(self):
        return None

    @property
    def extra_state_attributes(self):
        n = (self.coordinator.data or {}).get("notifications", {})
        return {
            "critical_count":  n.get("critical_count", 0),
            "warning_count":   n.get("warning_count", 0),
            "info_count":      n.get("info_count", 0),
            "muted_count":     n.get("muted_count", 0),
            "active_alerts":   n.get("active_alerts", []),
        }


class CloudEMSClippingLossSensor(CoordinatorEntity, SensorEntity):
    """Geschat financieel verlies door PV-clipping per jaar."""
    _attr_name = "CloudEMS · Clipping Verlies"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power-variant-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clipping_loss"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("clipping_loss", {}).get("total_kwh_lost_30d", None)

    @property
    def extra_state_attributes(self):
        c = (self.coordinator.data or {}).get("clipping_loss", {})
        return {
            "total_eur_lost_year":  c.get("total_eur_lost_year", 0.0),
            "worst_inverter":       c.get("worst_inverter", ""),
            "expansion_roi_years":  c.get("expansion_roi_years"),
            "any_curtailment":      c.get("any_curtailment", False),
            "inverters":            c.get("inverters", []),
            "advice":               c.get("advice", ""),
        }


class CloudEMSConsumptionCategoriesSensor(CoordinatorEntity, SensorEntity):
    """Verbruik uitgesplitst per categorie (verwarming, mobiliteit, wit goed, enz.)."""
    _attr_name = "CloudEMS Verbruik Categorien"  # slug → sensor.cloudems_verbruik_categorien
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class  = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:chart-pie"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_consumption_categories"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("consumption_categories", {}).get("total_kwh_today", None)

    @property
    def extra_state_attributes(self):
        c = (self.coordinator.data or {}).get("consumption_categories", {})
        return {
            "total_kwh_today":   c.get("total_kwh_today", 0.0),   # v1.16 fix: was missing, dashboard showed 0.0
            "top_category":      c.get("top_category", ""),
            "top_category_pct":  c.get("top_category_pct", 0.0),
            "breakdown_pct":     c.get("breakdown_pct", {}),
            "breakdown_kwh":     c.get("breakdown_kwh", {}),
            "breakdown_w_now":   c.get("breakdown_w_now", {}),
            "total_w_now":       c.get("total_w_now", 0.0),
            "pie_data":          c.get("pie_data", []),
            "dominant_insight":  c.get("dominant_insight", ""),
            "avg_breakdown_pct": c.get("avg_breakdown_pct", {}),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.15.4: NEW HA Sensor entities voor absence/occupancy, climate preheat,
#          PV forecast accuracy, EMA diagnostics en sensor sanity guard.
#          Deze modules bestonden al in coordinator maar hadden geen HA entiteiten.
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSAbsenceDetectorSensor(CoordinatorEntity, SensorEntity):
    """Aanwezigheidsstatus via AbsenceDetector (verbruikspatroon-gebaseerd).
    
    Meldt: home / away / sleeping / vacation.
    Attributes: confidence, standby_w, vacation_hours, advice.
    """
    _attr_name  = "CloudEMS Absence Detector"
    _attr_icon  = "mdi:home-account"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_absence_detector"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("occupancy", {}).get("state", "unknown")

    @property
    def extra_state_attributes(self):
        o = (self.coordinator.data or {}).get("occupancy", {})
        return {
            "confidence":     o.get("confidence", 0.0),
            "state":          o.get("state", "unknown"),
            "standby_w":      o.get("standby_w"),
            "vacation_hours": o.get("vacation_hours", 0),
            "advice":         o.get("advice", ""),
        }


class CloudEMSClimatePreheatSensor(CoordinatorEntity, SensorEntity):
    """Verwarmingsadvies van ClimatePreHeatAdvisor.
    
    Meldt: pre_heat / reduce / normal.
    Attributes: setpoint_offset_c, reason, price_ratio, w_per_k, reliable.
    """
    _attr_name  = "CloudEMS Climate Preheat"
    _attr_icon  = "mdi:thermometer-auto"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate_preheat"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("climate_preheat", {}).get("mode", "normal")

    @property
    def extra_state_attributes(self):
        p = (self.coordinator.data or {}).get("climate_preheat", {})
        return {
            "mode":              p.get("mode", "normal"),
            "setpoint_offset_c": p.get("setpoint_offset_c", 0.0),
            "reason":            p.get("reason", ""),
            "price_ratio":       p.get("price_ratio"),
            "w_per_k":           p.get("w_per_k"),
            "reliable":          p.get("reliable", False),
        }


class CloudEMSPVForecastAccuracySensor(CoordinatorEntity, SensorEntity):
    """PV prognose nauwkeurigheid (MAPE 14d / 30d, biasfactor).
    
    State = MAPE 14d in %.
    """
    _attr_name  = "CloudEMS PV Forecast Accuracy"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon  = "mdi:weather-sunny-alert"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pv_forecast_accuracy"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @staticmethod
    def _acc_dict(raw) -> dict:
        """Normalise pv_accuracy to a plain dict.

        The coordinator now always returns a dict, but during the very first
        async_write_ha_state (called inside async_add_entities before the
        coordinator has run with the new code) the value may still be a
        PVAccuracyData dataclass from the initial coordinator run.
        This helper handles both cases gracefully.
        """
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        # PVAccuracyData dataclass — map fields to the expected dict keys
        return {
            "mape_14d_pct":      getattr(raw, "mape_14d", None),
            "mape_30d_pct":      getattr(raw, "mape_30d", None),
            "bias_factor":       getattr(raw, "bias_factor", None),
            "samples":           getattr(raw, "days_with_data", 0),
            "last_day_mape":     abs(getattr(raw, "last_day_error_pct", 0) or 0),
            "quality_label":     getattr(raw, "quality_label", None),
            "advice":            getattr(raw, "advice", None),
            "days_tracked":      getattr(raw, "days_tracked", 0),
            "calibration_month": getattr(raw, "calibration_month", None),
            "consecutive_over":  getattr(raw, "consecutive_over", 0),
            "consecutive_under": getattr(raw, "consecutive_under", 0),
            "monthly_bias":      getattr(raw, "monthly_bias", {}),
        }

    @property
    def native_value(self):
        a = self._acc_dict((self.coordinator.data or {}).get("pv_accuracy"))
        mape = a.get("mape_14d_pct")
        if mape is None:
            return None
        try:
            return round(float(mape), 1)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        a = self._acc_dict((self.coordinator.data or {}).get("pv_accuracy"))
        # v4.6.453: voeg gisteren uurdata toe voor solar card forecast history
        yesterday_kwh = a.get("yesterday_hourly_kwh") or {}
        if not yesterday_kwh:
            # Fallback: haal actual_kwh_per_hour uit de solar learner
            pv_acc_data = (self.coordinator.data or {}).get("pv_accuracy") or {}
            yesterday_kwh = pv_acc_data.get("yesterday_hourly_kwh", {})
        return {
            "mape_14d_pct":        a.get("mape_14d_pct"),
            "mape_30d_pct":        a.get("mape_30d_pct"),
            "bias_factor":         a.get("bias_factor"),
            "samples":             a.get("samples", 0),
            "last_day_mape":       a.get("last_day_mape"),
            "yesterday_hourly_kwh": yesterday_kwh,
        }


class CloudEMSBalancerSensor(CoordinatorEntity, SensorEntity):
    """EnergyBalancer diagnostiek — Kirchhoff-balans, sensor-intervallen en geleerde battery-lag.

    State = Kirchhoff-imbalans in Watt (ideaal: 0).
    Attributes: per-sensor interval, stale-status, geleerde battery-vertraging,
                house_trend_w, lag_learner statistieken.
    """
    _attr_name  = "CloudEMS Energy Balancer"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon  = "mdi:scale-balance"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_balancer"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("energy_balancer", {})
        return round(d.get("last_imbalance_w", 0.0), 1)

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("energy_balancer", {})
        return {
            # Sensor update-intervallen (adaptief gemeten)
            "grid_interval_s":    d.get("grid_interval_s"),
            "solar_interval_s":   d.get("solar_interval_s"),
            "battery_interval_s": d.get("battery_interval_s"),
            # Stale-status
            "grid_stale":         d.get("grid_stale", False),
            "solar_stale":        d.get("solar_stale", False),
            "battery_stale":      d.get("battery_stale", False),
            "stale_sensors":      d.get("stale_sensors", []),
            # Kirchhoff
            "imbalance_w":        d.get("last_imbalance_w", 0.0),
            "house_trend_w":      d.get("house_trend_w"),
            "lag_compensated":    d.get("lag_compensated", False),
            # Geleerde battery-vertraging (lag-learner)
            "battery_lag_learned_s":   d.get("battery_learned_lag_s"),
            "battery_lag_confidence":  d.get("battery_lag_confidence"),
            "battery_lag_samples":     d.get("battery_lag_samples", 0),
            "solar_lag_learned_s":     d.get("solar_learned_lag_s"),
            "solar_lag_confidence":    d.get("solar_lag_confidence"),
        }


class CloudEMSSanitySensor(CoordinatorEntity, SensorEntity):
    """Sensor sanity guard — detecteert misconfigureerde sensoren (kW/W verwarring, te hoge waarden, enz.).
    
    State = totaal actieve issues.
    Attributes: issues (lijst), summary, has_critical, has_warning.
    """
    _attr_name  = "CloudEMS Sensor Sanity"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon  = "mdi:shield-check"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sensor_sanity"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self):
        s = (self.coordinator.data or {}).get("sensor_sanity", {})
        issues = s.get("issues", [])
        return len(issues) if isinstance(issues, list) else 0

    @property
    def extra_state_attributes(self):
        s = (self.coordinator.data or {}).get("sensor_sanity", {})
        return {
            "has_critical": s.get("has_critical", False),
            "has_warning":  s.get("has_warning", False),
            "summary":      s.get("summary", "Alle sensoren OK"),
            "issues":       s.get("issues", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.16.0: Schaduwdetectie & Clipping-voorspelling
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSShadowDetectionSensor(CoordinatorEntity, SensorEntity):
    """Structurele schaduwdetectie per omvormer.

    State  = geschat totaal dagelijks verlies door schaduw (kWh).
    Attributes:
        any_shadow          — True als er schaduw gedetecteerd is
        summary             — leesbare samenvatting
        inverters           — per-omvormer details:
            label, shadowed_hours, partial_hours, direction,
            severity, lost_kwh_day_est, advice
    """
    _attr_name       = "CloudEMS Schaduwdetectie"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = None
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon       = "mdi:weather-partly-cloudy"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_shadow_detection"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        s = (self.coordinator.data or {}).get("shadow_detection", {})
        return s.get("total_lost_kwh_day", None)

    @property
    def extra_state_attributes(self):
        s = (self.coordinator.data or {}).get("shadow_detection", {})
        return {
            "any_shadow":    s.get("any_shadow", False),
            "summary":       s.get("summary", "Onvoldoende data voor schaduwanalyse."),
            "trained_hours": s.get("trained_hours", 0),
            "total_hours":   s.get("total_hours", 0),
            "progress_pct":  s.get("progress_pct", 0),
            "inverters":     s.get("inverters", []),
        }


class CloudEMSClippingForecastSensor(CoordinatorEntity, SensorEntity):
    """Clipping-voorspelling voor morgen op basis van PV-forecast en geleerde omvormergrens.

    State  = totaal verwacht geclipte energie morgen (kWh, som over alle omvormers).
    Attributes:
        forecasts           — per-omvormer:
            ceiling_w, predicted_clip_kwh, clipped_hours, advice
        total_clipped_kwh   — som over alle omvormers
        advice              — gecombineerd advies
    """
    _attr_name       = "CloudEMS Clipping Voorspelling Morgen"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = None
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon       = "mdi:solar-power-variant-outline"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clipping_forecast"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        forecasts = (
            (self.coordinator.data or {})
            .get("clipping_loss", {})
            .get("clipping_forecast_tomorrow", [])
        )
        if not forecasts:
            return None
        return round(sum(f.get("predicted_clip_kwh", 0.0) for f in forecasts), 2)

    @property
    def extra_state_attributes(self):
        forecasts = (
            (self.coordinator.data or {})
            .get("clipping_loss", {})
            .get("clipping_forecast_tomorrow", [])
        )
        total = round(sum(f.get("predicted_clip_kwh", 0.0) for f in forecasts), 2)
        # Combineer adviezen — toon alleen omvormers met verwachte clipping
        clipping_fcasts = [f for f in forecasts if f.get("predicted_clip_kwh", 0) > 0.05]
        if clipping_fcasts:
            advice = " | ".join(f.get("advice", "") for f in clipping_fcasts)
        elif forecasts:
            advice = "Geen significante clipping verwacht morgen."
        else:
            advice = "Onvoldoende data voor voorspelling."
        return {
            "forecasts":          forecasts,
            "total_clipped_kwh":  total,
            "advice":             advice,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.16.0 — Ollama AI Diagnostics sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSOllamaDiagSensor(CoordinatorEntity, SensorEntity):
    """Ollama health + NILM activity diagnostics.

    State  = online / offline / timeout / error / disabled
    Attributes:
        host, port, model              — configured Ollama endpoint
        active_model_found             — is the configured model loaded in Ollama?
        models_available               — list of all models Ollama reports
        last_check_ts                  — ISO timestamp of last health-check
        last_error                     — last error string, if any
        calls_total                    — number of NILM events sent to Ollama (session)
        calls_success                  — successful responses
        calls_failed                   — failed/timeout responses
        success_rate_pct               — success %
        last_success_ts                — ISO timestamp of last successful call
        last_response_ms               — last round-trip time (ms)
        avg_response_ms                — rolling average round-trip (ms)
        fallback_to_database           — True when Ollama is down and DB is used
        recent_calls                   — ring buffer last 20 Ollama queries
    """
    _attr_name  = "CloudEMS Ollama · Diagnostics"
    _attr_icon  = "mdi:head-cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ollama_diagnostics"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> str:
        health = (self.coordinator.data or {}).get("ollama_health", {})
        diag   = (self.coordinator.data or {}).get("ollama_diagnostics", {})
        if not diag.get("enabled"):
            return "disabled"
        return health.get("status", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        d      = self.coordinator.data or {}
        health = d.get("ollama_health", {})
        diag   = d.get("ollama_diagnostics", {})

        enabled     = diag.get("enabled", False)
        total       = diag.get("calls_total", 0)
        success     = diag.get("calls_success", 0)
        status      = health.get("status", "unknown")
        fallback    = enabled and status != "online"

        return {
            # Connection info
            "host":                 diag.get("host", "localhost"),
            "port":                 diag.get("port", 11434),
            "model":                diag.get("model", "llama3"),
            "active_model_found":   health.get("active_model_found", False),
            "models_available":     health.get("models_available", []),
            "last_check_ts":        health.get("last_check_ts"),
            "last_error":           health.get("last_error") or diag.get("last_error"),
            # Call stats
            "calls_total":          total,
            "calls_success":        success,
            "calls_failed":         diag.get("calls_failed", 0),
            "success_rate_pct":     diag.get("success_rate_pct", 0.0),
            "last_success_ts":      diag.get("last_success_ts"),
            "last_response_ms":     diag.get("last_response_ms", 0),
            "avg_response_ms":      diag.get("avg_response_ms", 0),
            # Fallback indicator
            "fallback_to_database": fallback,
            "nilm_active_mode":     d.get("nilm_mode", "database"),
            # Recent activity
            "recent_calls":         diag.get("recent_calls", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.17.0 — Hybride NILM sensor (ankers + weer + diagnostics)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSHybridNILMSensor(CoordinatorEntity, SensorEntity):
    """
    Toont de status van de Hybride NILM-laag:
      • Aantal actieve smart-plug ankers
      • Actuele buitentemperatuur (voor contextpriors)
      • Seizoen
      • Statistieken: enrich-calls, anchor hits, prior boosts/penalties, fase-hints
    """
    _attr_name       = "CloudEMS NILM · Hybride Status"
    _attr_icon       = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_hybrid_nilm"
        self.entity_id = "sensor.cloudems_nilm_hybride_status"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("hybrid_nilm", {})
        return d.get("anchors_active", 0)

    @property
    def native_unit_of_measurement(self): return "ankers"

    @property
    def extra_state_attributes(self):
        d = (self.coordinator.data or {}).get("hybrid_nilm", {})
        stats = d.get("stats", {})
        return {
            "anchors_total":           d.get("anchors_total", 0),
            "anchors_active":          d.get("anchors_active", 0),
            "weather_temperature_c":   d.get("weather_temperature_c"),
            "weather_season":          d.get("weather_season"),
            "weather_irradiance_w":    d.get("weather_irradiance_w"),
            "weather_sensors":         d.get("weather_sensors", []),
            "anchors":                 d.get("anchors", []),
            # stats
            "stat_enrich_calls":       stats.get("enrich_calls", 0),
            "stat_anchor_hits":        stats.get("anchor_hits", 0),
            "stat_prior_boosts":       stats.get("prior_boosts", 0),
            "stat_prior_penalties":    stats.get("prior_penalties", 0),
            "stat_phase_balance_hints":stats.get("phase_balance_hints", 0),
            "stat_discoveries":        stats.get("discoveries", 0),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.20 — Virtuele Stroommeter per Kamer
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSRoomMeterOverviewSensor(CoordinatorEntity, SensorEntity):
    """Master overview sensor: kamer met hoogste huidig verbruik.

    State  = naam van de kamer met meeste verbruik op dit moment
    Attrs  = verbruik, kWh en percentage per kamer (tabel voor Lovelace)
    """
    _attr_name       = "CloudEMS Kamers · Overzicht"
    _attr_icon       = "mdi:home-lightning-bolt"
    _attr_device_class = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_room_overview"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self) -> str:
        ov = (self.coordinator.data or {}).get("room_meter", {}).get("overview", {})
        return ov.get("top_room", "onbekend")

    @property
    def extra_state_attributes(self) -> dict:
        ov = (self.coordinator.data or {}).get("room_meter", {}).get("overview", {})
        return {
            "top_room":      ov.get("top_room"),
            "total_power_w": ov.get("total_power_w"),
            "room_count":    ov.get("room_count", 0),
            "rooms":         ov.get("rooms", []),
        }


class CloudEMSRoomMeterSensor(CoordinatorEntity, SensorEntity):
    """Per-kamer stroomverbruik sensor — dynamisch aangemaakt per ontdekte kamer.

    State  = huidig verbruik (W)
    Attrs  = apparaten in de kamer, kWh vandaag/maand, % van totaal
    """
    _attr_device_class   = SensorDeviceClass.POWER
    _attr_state_class    = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"

    def __init__(self, coord, entry, room_name: str):
        super().__init__(coord)
        self._entry     = entry
        self._room_name = room_name
        self._attr_unique_id = f"{entry.entry_id}_room_{room_name}"
        self._attr_name      = f"CloudEMS Kamer · {room_name.title()}"

        from .energy_manager.room_meter import ROOM_ICONS
        self._attr_icon = ROOM_ICONS.get(room_name, "mdi:home-outline")

    @property
    def device_info(self): return _device_info(self._entry)

    def _room_data(self) -> dict:
        return (self.coordinator.data or {}) \
            .get("room_meter", {}) \
            .get("rooms", {}) \
            .get(self._room_name, {})

    @property
    def native_value(self) -> float:
        return self._room_data().get("current_power_w", 0.0)

    @property
    def extra_state_attributes(self) -> dict:
        rd = self._room_data()
        ov = (self.coordinator.data or {}).get("room_meter", {}).get("overview", {})
        total_w = ov.get("total_power_w", 1) or 1
        pct = round(rd.get("current_power_w", 0) / total_w * 100, 1)
        return {
            "room":          self._room_name,
            "kwh_today":     rd.get("kwh_today", 0),
            "kwh_this_month":rd.get("kwh_this_month", 0),
            "pct_of_total":  pct,
            "devices":       rd.get("devices", []),
            "device_count":  len(rd.get("devices", [])),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v1.20 — Goedkope Uren Schakelaar Status sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSCheapSwitchesSensor(CoordinatorEntity, SensorEntity):
    """Overzicht van alle aan goedkope uren gekoppelde schakelaars.

    State  = aantal geconfigureerde schakelaars
    Attrs  = per schakelaar: entiteit, blok, huidige staat, actie-log
    """
    _attr_name = "CloudEMS · Goedkope Uren Schakelaars"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cheap_switches"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_PRICE)

    @property
    def native_value(self) -> int:
        cs = (self.coordinator.data or {}).get("cheap_switches", {})
        return cs.get("count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        cs = data.get("cheap_switches", {})
        # v4.5 fix: voeg smart_delay toe zodat dashboard YAML
        # state_attr(..., 'smart_delay') correct leest
        # v4.6.479: kaart verwacht array, niet dict
        sd = data.get("smart_delay", {})
        sd_list = sd.get("switches", []) if isinstance(sd, dict) else (sd if isinstance(sd, list) else [])
        return {
            "switches":     cs.get("switches", []),
            "last_actions": cs.get("actions", []),
            "smart_delay":  sd_list,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v2.1.9: Watchdog sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSWatchdogSensor(CoordinatorEntity, SensorEntity):
    """Toont watchdog gezondheid: crashes, herstarts, foutgeschiedenis."""
    _attr_name = "CloudEMS · Watchdog"
    _attr_icon = "mdi:shield-refresh"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_watchdog"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> str:
        wd = (self.coordinator.data or {}).get("watchdog", {})
        return wd.get("status", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        attrs = dict((self.coordinator.data or {}).get("watchdog", {}))
        attrs["cloudems_version"] = VERSION
        # v4.6.333: audit log summary
        try:
            from .energy_manager.audit_log import get_audit_log
            attrs["audit"] = get_audit_log().get_summary()
        except Exception:
            pass
        return _trim_attrs(attrs)


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.2: Installatie-kwaliteitsscore sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSInstallationScoreSensor(CoordinatorEntity, SensorEntity):
    """Toont de installatie-kwaliteitsscore (0–100) met grade en advies."""
    _attr_name  = "CloudEMS · Installatie Score"
    _attr_icon  = "mdi:clipboard-check-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_installation_score"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> int | None:
        score_data = (self.coordinator.data or {}).get("installation_score", {})
        return score_data.get("score")

    @property
    def extra_state_attributes(self) -> dict:
        score_data = (self.coordinator.data or {}).get("installation_score", {})
        if not score_data:
            return {}
        return {
            "grade":   score_data.get("grade", "?"),
            "emoji":   score_data.get("emoji", ""),
            "summary": score_data.get("summary", ""),
            "items":   score_data.get("items", []),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.3: BehaviourCoach sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBehaviourCoachSensor(CoordinatorEntity, SensorEntity):
    """Toont potentiële besparing door apparaten te verschuiven naar goedkopere uren."""
    _attr_name  = "CloudEMS · Gedragscoach"
    _attr_icon  = "mdi:lightbulb-on-outline"
    _attr_native_unit_of_measurement = "EUR/maand"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_behaviour_coach"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> float | None:
        d = (self.coordinator.data or {}).get("behaviour_coach", {})
        v = d.get("total_saving_eur_month")
        return round(float(v), 2) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("behaviour_coach", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.3: LoadPlan sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSLoadPlanSensor(CoordinatorEntity, SensorEntity):
    """Toont het geoptimaliseerde uurschema voor morgen."""
    _attr_name  = "CloudEMS · Dagplan Morgen"
    _attr_icon  = "mdi:calendar-clock"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_load_plan"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> float | None:
        d = (self.coordinator.data or {}).get("load_plan", {})
        return round(float(d["total_saving_eur"]), 2) if d.get("total_saving_eur") is not None else None

    @property
    def native_unit_of_measurement(self) -> str:
        return "EUR"

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("load_plan", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.3: EnergyLabel sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEnergyLabelSensor(CoordinatorEntity, SensorEntity):
    """Toont het geschatte energielabel van de woning (A++++ t/m G)."""
    _attr_name  = "CloudEMS · Energielabel"
    _attr_icon  = "mdi:home-energy-outline"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_label"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str | None:
        d = (self.coordinator.data or {}).get("energy_label", {})
        return d.get("label")

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("energy_label", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.4.1: BillSimulator sensor — sensor.cloudems_bill_simulator
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBillSimulatorSensor(CoordinatorEntity, SensorEntity):
    """Vergelijkt kosten op vast, dag/nacht en dynamisch tarief."""
    _attr_name  = "CloudEMS Bill Simulator"
    _attr_icon  = "mdi:cash-multiple"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_bill_simulator"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("bill_simulator", {})
        return round(d.get("dynamic_cost_eur", 0.0), 2)

    @property
    def extra_state_attributes(self):
        raw = (self.coordinator.data or {}).get("bill_simulator", {})
        return _trim_attrs(raw) if isinstance(raw, dict) else {}


# ═══════════════════════════════════════════════════════════════════════════════
# v2.4.1: NILM Overzicht sensor — sensor.cloudems_nilm_overzicht
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSNILMOverzichtSensor(CoordinatorEntity, SensorEntity):
    """NILM overzicht met ROI-data voor apparaatvervanging."""
    _attr_name  = "CloudEMS NILM Overzicht"
    _attr_icon  = ICON_NILM
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_nilm_overzicht"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("nilm_devices", []))

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        roi_raw = d.get("appliance_roi", {})
        devices = d.get("nilm_devices", [])
        return _trim_attrs({
            "roi": roi_raw,
            "device_count": len(devices),
            "devices": [
                {
                    "name": dev.get("display_name", dev.get("device_id", "")),
                    "device_type": dev.get("device_type", ""),
                    "confirmed": dev.get("confirmed", False),
                    "power_w": dev.get("power_w", 0),
                }
                for dev in devices[:20]
            ],
        })


# ═══════════════════════════════════════════════════════════════════════════════
# v2.4.1: Warmtepomp COP sensor — sensor.cloudems_warmtepomp_cop
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSOnbekendVerbruikSensor(CoordinatorEntity, SensorEntity):
    """
    Toont het onverklaard ('Other') verbruik in watt.

    Geïnspireerd door Sense's 'Other' bubble.
    Berekend als: grid_import − NILM_known − estimator_known − standby.

    Hoog = veel verbruik dat CloudEMS nog niet herkent.
    Laag = bijna alles wordt verklaard door NILM + SmartPowerEstimator.
    """
    _attr_name         = "CloudEMS Onbekend Verbruik"
    _attr_icon         = "mdi:help-circle-outline"
    _attr_native_unit_of_measurement = "W"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_onbekend_verbruik"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_NILM)

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        return (d.get("other_bucket") or {}).get("other_w")

    @property
    def extra_state_attributes(self):
        d  = self.coordinator.data or {}
        ob = d.get("other_bucket") or {}
        bd = ob.get("breakdown") or {}

        # Actieve NILM apparaten voor in de breakdown tabel
        nilm_devices = d.get("nilm_devices") or []
        active_devices = [
            {
                "name":    dev.get("name", "Onbekend"),
                "power_w": round(float(dev.get("current_power") or dev.get("power_w") or 0), 0),
                "phase":   dev.get("phase", "L1"),
            }
            for dev in nilm_devices
            if dev.get("is_on") and dev.get("confirmed")
            and float(dev.get("current_power") or dev.get("power_w") or 0) > 1.0
        ]

        return _trim_attrs({
            "coverage_pct":      ob.get("coverage_pct"),
            "trend":             ob.get("trend"),
            "grid_import_w":     bd.get("grid_import_w"),
            "nilm_known_w":      bd.get("nilm_known_w"),
            "powercalc_w":       bd.get("powercalc_w"),
            "learned_w":         bd.get("learned_w"),
            "standby_w":         bd.get("standby_w"),
            "active_devices":    active_devices,
            "active_faults":     d.get("active_faults", []),
        })


# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSWarmtepompCOPSensor(CoordinatorEntity, SensorEntity):
    """Leert de COP-curve van de warmtepomp en detecteert degradatie."""
    _attr_name  = "CloudEMS Warmtepomp COP"
    _attr_icon  = "mdi:heat-pump"
    _attr_native_unit_of_measurement = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_warmtepomp_cop"
        self.entity_id = "sensor.cloudems_warmtepomp_cop"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GAS)

    @property
    def native_value(self):
        cop = (self.coordinator.data or {}).get("heat_pump_cop", {})
        val = cop.get("cop_current")
        return round(val, 2) if val is not None else None

    @property
    def extra_state_attributes(self):
        cop = (self.coordinator.data or {}).get("heat_pump_cop", {})
        return {
            "cop_current":          cop.get("cop_current"),
            "cop_at_7c":            cop.get("cop_at_7c"),
            "cop_at_2c":            cop.get("cop_at_2c"),
            "cop_at_minus5c":       cop.get("cop_at_minus5c"),
            "reliable":             cop.get("reliable", False),
            "method":               cop.get("method"),
            "outdoor_temp_c":       cop.get("outdoor_temp_c"),
            "defrost_today":        cop.get("defrost_today", False),
            "defrost_threshold_c":  cop.get("defrost_threshold_c"),
            "total_samples":        cop.get("total_samples", 0),
            "progress_pct":         cop.get("progress_pct", 0),
            "curve":                {k: round(float(v), 3) for k, v in list((cop.get("curve") or {}).items())[:10]},
            "degradation_detected": cop.get("degradation_detected", False),
            "degradation_pct":      cop.get("degradation_pct", 0.0),
            "degradation_advice":   cop.get("degradation_advice", ""),
            "cop_report":           {k: v for k, v in cop.items() if k not in ("curve",)},
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.3: Saldering sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSSalderingSensor(CoordinatorEntity, SensorEntity):
    """Toont impact van de salderingsafbouw op de jaarrekening."""
    _attr_name  = "CloudEMS · Salderingsafbouw"
    _attr_icon  = "mdi:solar-power-variant"
    _attr_native_unit_of_measurement = "EUR/jaar"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_saldering"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> float | None:
        d = (self.coordinator.data or {}).get("saldering", {})
        # extra_cost_at_zero_eur = meerkosten bij 0% saldering (2027)
        v = d.get("extra_cost_at_zero_eur")
        return round(float(v), 2) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("saldering", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.3: SystemHealth sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSSystemHealthSensor(CoordinatorEntity, SensorEntity):
    """Toont de algehele systeemgezondheid van CloudEMS als score 0-10."""
    _attr_name  = "CloudEMS · Systeemgezondheid"
    _attr_icon  = "mdi:heart-pulse"
    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = "/10"      # v4.0.6
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_system_health"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> int | None:         # v4.0.6: numeriek
        d = (self.coordinator.data or {}).get("system_health", {})
        return d.get("score")

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("system_health", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.5: GasAnalysis sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSGasAnalysisSensor(CoordinatorEntity, SensorEntity):
    """Toont gasverbruik dag/maand/jaar + CV-efficiëntie."""
    _attr_name  = "CloudEMS · Gasanalyse"
    _attr_icon  = "mdi:gas-burner"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_gas_analysis"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GAS)

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        d = data.get("gas_analysis", {})
        gd = data.get("gas_data", {})
        # Toon dag-verbruik als primaire waarde, efficiëntie als extra
        dag_m3 = float(d.get("gas_m3_today") or gd.get("dag_m3") or 0)
        prijs = float(gd.get("gas_prijs_per_m3") or 1.25)
        dag_eur = round(dag_m3 * prijs, 2)
        rating = d.get("efficiency_rating") or "onbekend"
        if dag_m3 > 0:
            return f"{dag_m3:.3f} m³ · €{dag_eur:.2f} · {rating}"
        return rating

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        d = dict(data.get("gas_analysis", {}))
        gd = data.get("gas_data", {})
        prijs = float(gd.get("gas_prijs_per_m3") or 1.25)
        # Voeg periode-verbruik toe
        d["prijs_per_m3"] = prijs
        d["dag_m3"]       = float(d.get("gas_m3_today")  or gd.get("dag_m3")  or 0)
        d["week_m3"]      = float(d.get("gas_m3_week")   or gd.get("week_m3") or 0)
        d["maand_m3"]     = float(d.get("gas_m3_month")  or gd.get("maand_m3") or 0)
        d["jaar_m3"]      = float(d.get("gas_m3_year")   or gd.get("jaar_m3") or 0)
        d["dag_eur"]      = round(d["dag_m3"]   * prijs, 2)
        d["week_eur"]     = round(d["week_m3"]  * prijs, 2)
        d["maand_eur"]    = round(d["maand_m3"] * prijs, 2)
        d["jaar_eur"]     = round(d["jaar_m3"]  * prijs, 2)
        return d


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.5: EnergyBudget sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSEnergyBudgetSensor(CoordinatorEntity, SensorEntity):
    """Toont de voortgang tov het ingestelde energiebudget voor deze maand."""
    _attr_name  = "CloudEMS · Energiebudget"
    _attr_icon  = "mdi:cash-check"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_budget"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str | None:
        d = (self.coordinator.data or {}).get("energy_budget", {})
        return d.get("overall_status")

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("energy_budget", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v2.2.5: ApplianceROI sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSApplianceROISensor(CoordinatorEntity, SensorEntity):
    """Toont welke apparaten financieel interessant zijn om te vervangen."""
    _attr_name  = "CloudEMS · Apparaatvervangings-ROI"
    _attr_icon  = "mdi:washing-machine"
    _attr_native_unit_of_measurement = "EUR/jaar"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_appliance_roi"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> float | None:
        d = (self.coordinator.data or {}).get("appliance_roi", {})
        v = d.get("total_saving_eur_year")
        return round(float(v), 2) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("appliance_roi", {})


class CloudEMSGeneratorKostenSensor(CoordinatorEntity, SensorEntity):
    """v4.6.438: Generator brandstofkosten — berekend uit vermogen × brandstofkosten/kWh."""
    _attr_name  = "CloudEMS · Generator Kosten"
    _attr_icon  = "mdi:fuel"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_generator_kosten"
        self.entity_id = "sensor.cloudems_generator_kosten_eur"
        self._session_kwh:   float = 0.0
        self._session_cost:  float = 0.0
        self._total_cost:    float = 0.0
        self._last_ts: float = 0.0

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GENERATOR)

    @property
    def native_value(self) -> float | None:
        gen = (self.coordinator.data or {}).get("generator", {})
        if not gen.get("enabled"):
            return None
        return round(self._total_cost, 4)

    @property
    def extra_state_attributes(self) -> dict:
        gen = (self.coordinator.data or {}).get("generator", {})
        return {
            "session_kwh":        round(self._session_kwh, 4),
            "session_cost_eur":   round(self._session_cost, 4),
            "total_cost_eur":     round(self._total_cost, 4),
            "fuel_type":          gen.get("fuel_type", "onbekend"),
            "fuel_cost_eur_kwh":  gen.get("fuel_cost_eur_kwh", 0.0),
            "generator_active":   gen.get("active", False),
            "power_w":            gen.get("power_w", 0.0),
        }

    def _handle_coordinator_update(self) -> None:
        """Accumuleer kosten elke coordinator-cyclus."""
        import time as _t
        gen = (self.coordinator.data or {}).get("generator", {})
        now = _t.time()

        if gen.get("active") and gen.get("power_w", 0) > 0:
            dt_s = (now - self._last_ts) if self._last_ts > 0 else 10.0
            dt_s = min(dt_s, 60.0)  # max 60s per stap — bescherming tegen gaps
            kwh = gen["power_w"] * dt_s / 3_600_000.0
            cost = kwh * float(gen.get("fuel_cost_eur_kwh", 0.35))
            self._session_kwh  += kwh
            self._session_cost += cost
            self._total_cost   += cost
        else:
            # Generator gestopt → reset sessie
            if self._session_kwh > 0:
                self._session_kwh  = 0.0
                self._session_cost = 0.0

        self._last_ts = now
        super()._handle_coordinator_update()


class CloudEMSMailStatusSensor(CoordinatorEntity, SensorEntity):
    """v2.4.19: Mail-status sensor — geeft aan of e-mailrapporten zijn geconfigureerd.

    State: 'configured' | 'disabled'
    Attrs: enabled, host, to, monthly, weekly
    Gebruikt door dashboard om config_entry_attr() (ongeldig) te vervangen.
    """
    _attr_icon = "mdi:email-fast-outline"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mail_status"
        self._attr_name = "CloudEMS Mail Status"
        self.entity_id = "sensor.cloudems_mail_status"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> str:
        return "configured" if self._entry.data.get("mail_enabled") else "disabled"

    @property
    def extra_state_attributes(self) -> dict:
        d = self._entry.data
        return {
            "enabled":  bool(d.get("mail_enabled", False)),
            "host":     d.get("mail_host", ""),
            "to":       d.get("mail_to", ""),
            "monthly":  bool(d.get("mail_monthly_report", False)),
            "weekly":   bool(d.get("mail_weekly_report", False)),
        }


class CloudEMSReportURLSensor(CoordinatorEntity, SensorEntity):
    """Houdt de URL bij van het laatste gegenereerde energierapport (v2.4.22).

    State  = URL van het rapport (of 'geen' als er nog geen is gegenereerd)
    Attrs  = label, gegenereerd_op
    """
    _attr_icon  = "mdi:file-chart"
    _attr_name  = "CloudEMS Laatste Rapport"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_report_url"
        self.entity_id = "sensor.cloudems_last_report_url"

    @property
    def device_info(self): return _device_info(self._entry)

    def _report_data(self) -> dict:
        return (
            self.hass.data
            .get(DOMAIN, {})
            .get("_reports", {})
            .get(self._entry.entry_id, {})
        )

    @property
    def native_value(self) -> str:
        return self._report_data().get("last_report_url", "geen")

    @property
    def extra_state_attributes(self) -> dict:
        d = self._report_data()
        return {
            "label": d.get("last_report_label", ""),
            "url":   d.get("last_report_url", ""),
        }


# ── v2.6: Slaapstand sensor ─────────────────────────────────────────────────

class CloudEMSSlaapstandSensor(CoordinatorEntity, SensorEntity):
    """Toont of de slaapstand actief is (v2.6)."""
    _attr_icon = "mdi:sleep"
    _attr_name = "CloudEMS Slaapstand"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_slaapstand"
        self.entity_id = "sensor.cloudems_slaapstand"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self) -> str:
        d = (self.coordinator.data or {}).get("sleep_detector", {})
        if not d.get("enabled"):
            return "uitgeschakeld"
        return "actief" if d.get("sleep_active") else "inactief"

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("sleep_detector", {})


# ── v2.6: Capaciteits-piek sensor ──────────────────────────────────────────

class CloudEMSKwartierPiekSensor(CoordinatorEntity, SensorEntity):
    """Toont het 15-minuten gemiddelde vermogen en maandpiek (v2.6)."""
    _attr_device_class   = SensorDeviceClass.POWER
    _attr_state_class    = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:lightning-bolt-circle"
    _attr_name = "CloudEMS Kwartier Piek"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_kwartier_piek"
        self.entity_id = "sensor.cloudems_kwartier_piek"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self) -> float:
        d = (self.coordinator.data or {}).get("capacity_peak", {})
        return d.get("current_avg_w", 0)

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("capacity_peak", {})


# ── v2.6: Wekelijkse vergelijking sensor ────────────────────────────────────

class CloudEMSWekelijkseVergelijkingSensor(CoordinatorEntity, SensorEntity):
    """Vergelijkt huidig weekverbruik met vorige week (v2.6)."""
    _attr_icon = "mdi:calendar-week"
    _attr_name = "CloudEMS Wekelijkse Vergelijking"
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_weekly_comparison"
        self.entity_id = "sensor.cloudems_weekly_comparison"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GAS)

    @property
    def native_value(self) -> float:
        d = (self.coordinator.data or {}).get("weekly_comparison", {})
        return round(d.get("this_week_kwh", 0), 2)

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("weekly_comparison", {})


# ══════════════════════════════════════════════════════════════════════════════
# v2.6 — Multi-Zone Klimaat Sensoren
# ══════════════════════════════════════════════════════════════════════════════

class CloudEMSZoneClimateSensor(CoordinatorEntity, SensorEntity):
    """Eén sensor per zone — state = huidige temperatuur, attrs = alles."""

    def __init__(self, coordinator, entry: ConfigEntry, area_id: str, area_name: str):
        super().__init__(coordinator)
        self._entry     = entry
        self._area_id   = area_id
        self._area_name = area_name
        self._attr_unique_id  = f"{entry.entry_id}_zone_climate_{area_id}"
        self._attr_name       = f"CloudEMS Zone {area_name}"
        self._attr_icon       = "mdi:home-thermometer"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_device_class = "temperature"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_ZONE_CLIMATE)

    def _zone_data(self) -> dict:
        zm = getattr(self.coordinator, "_zone_climate", None)
        if not zm:
            return {}
        for attrs in zm.get_zone_attrs():
            if attrs.get("area") == self._area_name:
                return attrs
        return {}

    @property
    def native_value(self):
        return self._zone_data().get("huidige_temp")

    @property
    def extra_state_attributes(self) -> dict:
        return self._zone_data()


class CloudEMSZoneClimateCostSensor(CoordinatorEntity, SensorEntity):
    """Totale klimaatkosten over alle zones vandaag."""

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry           = entry
        self._attr_unique_id  = f"{entry.entry_id}_zone_climate_cost_today"
        self.entity_id        = "sensor.cloudems_zone_klimaat_kosten_vandaag"
        self._attr_name       = "CloudEMS Klimaatkosten Vandaag"
        self._attr_icon       = "mdi:currency-eur"
        self._attr_native_unit_of_measurement = "EUR"
        self._attr_device_class = "monetary"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_ZONE_CLIMATE)

    @property
    def native_value(self):
        zc = (self.coordinator.data or {}).get("zone_climate", {})
        return zc.get("total_today", 0.0)

    @property
    def extra_state_attributes(self) -> dict:
        zc = (self.coordinator.data or {}).get("zone_climate", {})
        return {
            "total_today": zc.get("total_today"),
            "total_month": zc.get("total_month"),
            "boiler":      zc.get("boiler", {}),
            "zones":       [
                {
                    "name":       z.get("area_name"),
                    "preset":     z.get("preset"),
                    "bron":       z.get("best_source"),
                    "kosten_vandaag": z.get("cost_today"),
                    "kosten_maand":   z.get("cost_month"),
                }
                for z in zc.get("zones", [])
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v3.9.0: CloudEMS Status sensor — diagnose-kaart systeemstatus
# Serveert sensor.cloudems_status met 'system' attribuut voor dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSStatusSensor(CoordinatorEntity, SensorEntity):
    """Systeemstatus: versie, uptime, actieve modules."""
    _attr_name  = "CloudEMS Status"
    _attr_icon  = "mdi:information-outline"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        g = (self.coordinator.data or {}).get("guardian", {})
        return g.get("status", "ok")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        cfg  = getattr(self.coordinator, "_config", {})
        g    = data.get("guardian", {})
        wd   = data.get("watchdog", {})

        uptime_s = g.get("uptime_s") or wd.get("uptime_s") or 0
        uptime_h = round(uptime_s / 3600, 1)

        system = {
            "version":                VERSION,
            "uptime_s":               uptime_s,
            "uptime_h":               uptime_h,
            "uptime_str":             g.get("uptime_str") or wd.get("uptime_str", ""),
            "started_at":             g.get("started_at") or wd.get("started_at"),
            # Module actief-vlaggen (bool) — lees van coördinator, niet van cfg
            "nilm_active":            bool(getattr(self.coordinator, "_nilm_active", False)),
            "pv_forecast_active":     bool(getattr(self.coordinator, "_pv_forecast_enabled", False)),
            "climate_mgr_active":     bool(cfg.get("climate_management_enabled", False)),
            "ev_charger_active":      bool(cfg.get("ev_charger_entity")),
            "battery_scheduler_active": bool(getattr(self.coordinator, "_battery_sched_enabled", False)),
            "ere_active":             bool(cfg.get("ere_enabled", False)),
            "shutters_active":        bool(getattr(self.coordinator, "_shutter_enabled", False)),
            # Guardian
            "guardian_status":        g.get("status", "ok"),
            "active_issues":          g.get("error_count", 0) + g.get("warning_count", 0),
            "safe_mode":              g.get("safe_mode", False),
            # Watchdog
            "watchdog_restarts":      wd.get("total_restarts", 0),
            "watchdog_failures":      wd.get("total_failures", 0),
        }
        shutters = (self.coordinator.data or {}).get("shutters", {})
        # v4.6.520: fase-data uit de limiter exposeren zodat home-card piekschaving correct werkt
        limiter = getattr(self.coordinator, "_limiter", None)
        phases = limiter.get_phase_summary() if limiter else {}
        # v4.6.256: expose inverter_data zodat solar card fallback werkt bij opstarten
        inverter_data = (self.coordinator.data or {}).get("inverter_data", [])
        # v4.6.432: generator status meegeven aan flow card
        generator = (self.coordinator.data or {}).get("generator", {})
        # v4.6.449: circuit monitor
        circuit_monitor = (self.coordinator.data or {}).get("circuit_monitor", {})
        ups = (self.coordinator.data or {}).get("ups", {})
        return {"system": system, "guardian": g, "watchdog": wd, "shutters": shutters, "phases": phases, "inverter_data": inverter_data, "generator": generator, "circuit_monitor": circuit_monitor, "ups": ups}


# ═══════════════════════════════════════════════════════════════════════════════
# v3.9.0: Guardian sensor — zichtbaar in diagnose-tab
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSGuardianSensor(CoordinatorEntity, SensorEntity):
    """Toont SystemGuardian status: issues, veilige stand, uptime."""
    _attr_name  = "CloudEMS · Guardian"
    _attr_icon  = "mdi:shield-check"
    _attr_has_entity_name = False

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_guardian"

    @property
    def device_info(self): return _device_info(self._entry)

    @property
    def native_value(self) -> str:
        g = (self.coordinator.data or {}).get("guardian", {})
        return g.get("status", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("guardian", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v3.9.0: BatterySavings sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSBatterySavingsSensor(CoordinatorEntity, SensorEntity):
    """Besparing door thuisbatterij (eigenverbruik + arbitrage + PV-zelfconsumptie)."""
    _attr_name              = "CloudEMS Battery · Besparingen"
    _attr_icon              = "mdi:piggy-bank-outline"
    _attr_has_entity_name   = False
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class       = SensorStateClass.TOTAL
    _attr_device_class      = "monetary"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_battery_savings"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BATTERY)

    @property
    def native_value(self):
        d = (self.coordinator.data or {}).get("battery_savings", {})
        v = d.get("total_savings_eur")
        return round(v, 2) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("battery_savings", {})


# ═══════════════════════════════════════════════════════════════════════════════
# v4.3.6: ShutterOverride — countdown resterende pauze/override tijd
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSShutterOverrideSensor(CoordinatorEntity, SensorEntity):
    """Toont hoelang de automaat-pauze of handmatige override nog duurt.

    State:
        • None / "geen"  — geen actieve pauze of override
        • "X u YY min"   — resterende tijd in uren + minuten (label)
        • native_value   — resterende seconden (voor Lovelace timers/progress bars)
    """

    _attr_icon              = "mdi:timer-pause-outline"
    _attr_has_entity_name   = False
    _attr_native_unit_of_measurement = None
    _attr_state_class       = None

    def __init__(self, coordinator, entry, shutter_cfg: dict):
        super().__init__(coordinator)
        self._entry      = entry
        self._shutter_id = shutter_cfg.get("entity_id", "")
        self._label      = shutter_cfg.get("label") or self._shutter_id.split(".")[-1]
        safe             = self._shutter_id.split(".")[-1].replace("-", "_")
        self._attr_name      = self._label
        self._attr_unique_id = f"{entry.entry_id}_shutter_override_{safe}"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SHUTTER)

    def _remaining_seconds(self) -> int | None:
        """Bereken resterende seconden vanuit shutter controller state."""
        from homeassistant.util import dt as dt_util
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return None
        # Timed automaat pauze
        until = sc.get_auto_disabled_until(self._shutter_id)
        if until is not None:
            delta = (until - dt_util.now()).total_seconds()
            return max(0, int(delta))
        # Handmatige override (2u knop)
        state = sc._states.get(self._shutter_id)
        if state and state.override_until is not None and dt_util.now() < state.override_until:
            delta = (state.override_until - dt_util.now()).total_seconds()
            return max(0, int(delta))
        return None

    @property
    def available(self) -> bool:
        """Altijd beschikbaar zodra de coordinator draait — ook zonder actieve pauze.
        Zichtbaarheid in auto-entities wordt geregeld via het 'actief' attribuut,
        niet via de unavailable-state (die veroorzaakte dat auto-entities de overgang
        van unavailable → actieve waarde niet betrouwbaar oppikte)."""
        return self.coordinator.last_update_success

    @staticmethod
    def _fmt_hms(secs: int) -> str:
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def native_value(self) -> str:
        secs = self._remaining_seconds()
        return self._fmt_hms(secs) if secs else "00:00:00"

    @property
    def extra_state_attributes(self) -> dict:
        secs = self._remaining_seconds()
        if secs is None or secs == 0:
            return {
                "label":    self._label,
                "actief":   False,
                "restant":  "—",
            }
        uren   = secs // 3600
        minuten = (secs % 3600) // 60
        if uren > 0:
            label = f"{uren} u {minuten:02d} min"
        else:
            label = f"{minuten} min"

        # Type onderscheiden
        sc    = getattr(self.coordinator, "_shutter_ctrl", None)
        until = sc.get_auto_disabled_until(self._shutter_id) if sc else None
        soort = "pauze" if until is not None else "override"

        return {
            "label":   self._label,
            "actief":  True,
            "restant": label,
            "soort":   soort,
            "seconden": secs,
        }

    @property
    def icon(self) -> str:
        secs = self._remaining_seconds()
        if secs and secs > 0:
            return "mdi:timer-pause"
        return "mdi:timer-pause-outline"


# ═══════════════════════════════════════════════════════════════════════════════
# v4.3.6 — Runtime Warnings sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSRuntimeWarningsSensor(CoordinatorEntity, SensorEntity):
    """
    Actieve runtime-waarschuwingen van CloudEMS.

    State  = aantal actieve waarschuwingen (0 = alles ok)
    Attributes:
        warnings  — lijst van actieve waarschuwingen (code, level, message, detail)
        errors    — aantal warnings met level='error'
        has_error — True als er minstens één error is

    Cloud-ready: gebruikt alleen coordinator.data, geen directe HA-afhankelijkheden.
    """
    _attr_name  = "CloudEMS · Runtime Warnings"
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_icon  = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_runtime_warnings"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> int:
        warnings = (self.coordinator.data or {}).get("runtime_warnings", [])
        return len(warnings)

    @property
    def icon(self) -> str:
        w = (self.coordinator.data or {}).get("runtime_warnings", [])
        if any(x.get("level") == "error" for x in w):
            return "mdi:alert-circle"
        if w:
            return "mdi:alert"
        return "mdi:check-circle-outline"

    @property
    def extra_state_attributes(self) -> dict:
        warnings = (self.coordinator.data or {}).get("runtime_warnings", [])
        errors = [w for w in warnings if w.get("level") == "error"]
        return {
            "warnings":   warnings,
            "errors":     len(errors),
            "has_error":  bool(errors),
            "codes":      [w.get("code") for w in warnings],
            # P1-specifiek voor snelle dashboard-check
            "p1_spikes":  next((w.get("detail", "") for w in warnings if w.get("code") == "p1_spikes"), None),
            "p1_stale":   any(w.get("code") == "p1_stale" for w in warnings),
        }


class CloudEMSMeterTopologySensor(CoordinatorEntity, SensorEntity):
    """
    Meter topologie — boom van upstream/downstream meter-relaties.

    State  = aantal bevestigde relaties
    Attributes:
        tree        — boom als geneste dict (root→kinderen)
        stats       — { approved, tentative, learning, declined }
        suggestions — tentative relaties boven de leer-drempel
    """
    _attr_name  = "CloudEMS · Meter Topologie"
    _attr_icon  = "mdi:sitemap"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_meter_topology"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_GRID)

    @property
    def native_value(self) -> int:
        topo = getattr(self.coordinator, "_meter_topology", None)
        if topo is None:
            return 0
        return topo.get_stats().get("approved", 0)

    @property
    def extra_state_attributes(self) -> dict:
        topo = getattr(self.coordinator, "_meter_topology", None)
        if topo is None:
            return {"tree": [], "stats": {}, "suggestions": []}

        def _name(eid: str) -> str:
            st = self.coordinator.hass.states.get(eid)
            return st.attributes.get("friendly_name", eid) if st else eid

        return {
            "tree":        topo.get_tree(name_resolver=_name),
            "stats":       topo.get_stats(),
            "suggestions": topo.get_tentative_relations(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.5.121: ZonneplanKalibratie — losse sensor voor slider max-leren voortgang
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSZonneplanKalibratieSensor(CoordinatorEntity, SensorEntity):
    """Toont de voortgang van het Zonneplan slider max-leren als losse sensor.

    State:
        • "niet_gestart"   — max nooit geleerd (nog op default)
        • "bezig"          — probe actief
        • "klaar"          — beide sliders geleerd
    Attributen bevatten voortgang, geleerde maxima en fase (grof/fijn).
    """
    _attr_name            = "CloudEMS Zonneplan · Slider Kalibratie"
    _attr_icon            = "mdi:tune-variant"
    _attr_has_entity_name = False
    _attr_state_class     = None
    _attr_device_class    = None
    _attr_native_unit_of_measurement = None

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_zonneplan_kalibratie"

    @property
    def device_info(self): return _device_info(self._entry)

    def _zp(self) -> dict:
        bs = (self.coordinator.data or {}).get("battery_schedule", {})
        return bs.get("zonneplan") or {}

    @property
    def native_value(self) -> str:
        zp = self._zp()
        if not zp.get("detected"):
            return "niet_gedetecteerd"
        if zp.get("probe_active"):
            return "bezig"
        lmd = zp.get("learned_max_deliver_w") or 10000
        lms = zp.get("learned_max_solar_w") or 10000
        if lmd >= 9999 or lms >= 9999:
            return "niet_gestart"
        return "klaar"

    @property
    def extra_state_attributes(self) -> dict:
        zp = self._zp()
        lmd = zp.get("learned_max_deliver_w")
        lms = zp.get("learned_max_solar_w")
        probe_active    = zp.get("probe_active", False)
        confirmed_w     = zp.get("probe_confirmed_w") or 0
        current_w       = zp.get("probe_current_w") or 0
        step_w          = zp.get("probe_step_w") or 1000
        probe_key       = zp.get("probe_key", "")
        est_max         = 12000

        # Progress percentage: gebaseerd op confirmed_w t.o.v. verwacht maximum
        progress_pct = round(min(100, (confirmed_w / est_max) * 100), 1) if probe_active else (
            100.0 if (lmd and lmd < 9999 and lms and lms < 9999) else 0.0
        )

        fase = None
        if probe_active:
            fase = "Fase 1 — grove stappen (1000 W)" if step_w >= 1000 else "Fase 2 — verfijning (100 W)"

        key_label = None
        if probe_key == "deliver_to_home":
            key_label = "Leveren aan huis"
        elif probe_key == "solar_charge":
            key_label = "Zonneladen"

        return {
            "state":                self.native_value,
            "probe_active":         probe_active,
            "probe_key":            probe_key,
            "probe_key_label":      key_label,
            "probe_fase":           fase,
            "probe_current_w":      current_w if probe_active else None,
            "probe_confirmed_w":    confirmed_w if probe_active else None,
            "progress_pct":         progress_pct,
            "learned_max_deliver_w": lmd if lmd and lmd < 9999 else None,
            "learned_max_solar_w":   lms if lms and lms < 9999 else None,
            "has_sliders":           zp.get("has_sliders", False),
        }


class CloudEMSEntityLogSensor(CoordinatorEntity, SensorEntity):
    """Sensor: entity/device log — toont aangemakte entities en orphan status.

    State: "X actief / Y orphan"
    Attributes: volledige lijst per source, orphan details, pruned count.
    """
    _attr_name = "CloudEMS · Entity Log"
    _attr_icon = "mdi:format-list-checks"

    def __init__(self, coord, entry):
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_entity_log"

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self) -> str:
        log = (self.coordinator.data or {}).get("entity_log", {})
        active  = log.get("active",   0)
        orphans = log.get("orphaned", 0)
        total   = log.get("total",    0)
        if orphans:
            return f"{active}/{total} actief ⚠ {orphans} orphan"
        return f"{active}/{total} actief"

    @property
    def extra_state_attributes(self) -> dict:
        log = (self.coordinator.data or {}).get("entity_log", {})
        entries = log.get("entries", [])

        # Groepeer op source
        by_source: dict[str, dict] = {}
        for e in entries:
            src = e.get("source", "unknown")
            if src not in by_source:
                by_source[src] = {"active": 0, "orphaned": 0, "entities": []}
            if e.get("absent_ticks", 0) == 0:
                by_source[src]["active"] += 1
            else:
                by_source[src]["orphaned"] += 1
            by_source[src]["entities"].append({
                "entity_id":    e.get("entity_id"),
                "absent_ticks": e.get("absent_ticks", 0),
                "created_at":   e.get("created_at"),
            })

        orphan_list = [
            {"entity_id": e.get("entity_id"), "absent_ticks": e.get("absent_ticks")}
            for e in entries if e.get("absent_ticks", 0) > 0
        ]

        return {
            "total":       log.get("total",   0),
            "active":      log.get("active",  0),
            "orphaned":    log.get("orphaned",0),
            "pruned_ever": log.get("pruned",  0),
            "by_source":   by_source,
            "orphans":     orphan_list,
        }


# ── Beslissingsgeschiedenis sensor ───────────────────────────────────────────

class CloudEMSDecisionsHistorySensor(CoordinatorEntity, SensorEntity):
    """Sensor die de beslissingsgeschiedenis van CloudEMS exposeert als attribuut."""

    _attr_icon       = "mdi:history"
    _attr_state_class = None  # Geen numerieke waarde
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Beslissingen Geschiedenis"
        self._attr_unique_id = f"{entry.entry_id}_decisions_history"
        self.entity_id       = "sensor.cloudems_decisions_history"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self) -> str:
        hist = getattr(self.coordinator, "_decisions_history", None)
        if hist is None:
            return "0"
        # v4.6.409: voeg coordinator tick toe zodat sensor altijd wijzigt en HA
        # de WebSocket update verstuurt — voorkomt dat kaart vastloopt op 00:40
        tick = getattr(self.coordinator, "_coordinator_tick", 0)
        total = len(hist.get_recent(limit=99999))
        return f"{total}:{tick % 60}"

    @property
    def extra_state_attributes(self) -> dict:
        hist = getattr(self.coordinator, "_decisions_history", None)
        if hist is None:
            return {"decisions": [], "total_24h": 0}
        return hist.sensor_attributes()


# ── Eigen recorder-sensoren: energie & batterij ──────────────────────────────

class CloudEMSBatterijSOCSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 1
    """sensor.cloudems_batterij_soc — batterij laadtoestand (%)."""
    _attr_device_class  = SensorDeviceClass.BATTERY
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Batterij SOC"
        self._attr_unique_id = f"{entry.entry_id}_batterij_soc"
        self.entity_id       = "sensor.cloudems_batterij_soc"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        # Probeer uit battery_providers data
        zp = data.get("zonneplan") or {}
        soc = zp.get("soc_pct")
        if soc is None:
            # Uit battery_providers attribuut van EPEX sensor
            for bat in data.get("batteries", []):
                soc = bat.get("soc_pct")
                if soc is not None:
                    break
        # Fallback: uit coordinator _last_soc_pct
        if soc is None:
            soc = getattr(self.coordinator, "_last_soc_pct", None)
        return round(float(soc), 1) if soc is not None else None


class CloudEMSNetVermogenSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 2
    """sensor.cloudems_net_vermogen — netlevering/afname (W, positief = afname)."""
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:transmission-tower"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Net Vermogen"
        self._attr_unique_id = f"{entry.entry_id}_net_vermogen"
        self.entity_id       = "sensor.cloudems_net_vermogen"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self):
        v = getattr(self.coordinator, "_last_grid_w", None)
        return round(float(v), 1) if v is not None else None


class CloudEMSZonVermogenSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 2
    """sensor.cloudems_zon_vermogen — totaal PV vermogen (W)."""
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:solar-power"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Zon Vermogen"
        self._attr_unique_id = f"{entry.entry_id}_zon_vermogen"
        self.entity_id       = "sensor.cloudems_zon_vermogen"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SOLAR)

    @property
    def native_value(self):
        v = getattr(self.coordinator, "_last_solar_w", None)
        return round(float(v), 1) if v is not None else None


class CloudEMSBoilerSetpointSensor(AdaptiveForceUpdateMixin, CoordinatorEntity, SensorEntity):
    _force_update_priority = 2
    """sensor.cloudems_boiler_setpoint — actueel setpoint van de primaire boiler (°C)."""
    _attr_device_class  = SensorDeviceClass.TEMPERATURE
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer-water"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Boiler Setpoint"
        self._attr_unique_id = f"{entry.entry_id}_boiler_setpoint"
        self.entity_id       = "sensor.cloudems_boiler_setpoint"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        # Lees eerst van virtual thermostat entity (heeft override setpoint bij manual/boost)
        ctrl = getattr(self.coordinator, "_boiler_ctrl", None)
        if ctrl:
            all_b = list(getattr(ctrl, "_boilers", [])) + [
                b for g in getattr(ctrl, "_groups", []) for b in g.boilers
            ]
            if all_b:
                import re as _re
                b0 = all_b[0]
                slug = _re.sub(r"[^a-z0-9]+", "_", (b0.label or "").lower()).strip("_")
                vb_st = self.coordinator.hass.states.get(f"water_heater.cloudems_boiler_{slug}")
                if vb_st:
                    t = vb_st.attributes.get("temperature")
                    if t is not None:
                        return round(float(t), 1)
        # Fallback: uit boiler_status
        data = self.coordinator.data or {}
        for b in data.get("boiler_status", []):
            sp = b.get("active_setpoint_c") or b.get("setpoint_c")
            if sp:
                return round(float(sp), 1)
        for g in data.get("boiler_groups_status", []):
            for b in g.get("boilers", []):
                sp = b.get("active_setpoint_c") or b.get("setpoint_c")
                if sp:
                    return round(float(sp), 1)
        return None


class CloudEMSSliderLeverenSensor(CoordinatorEntity, SensorEntity):
    """sensor.cloudems_slider_leveren — Zonneplan 'leveren aan huis' slider waarde (W)."""
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:home-export-outline"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Slider Leveren aan Huis"
        self._attr_unique_id = f"{entry.entry_id}_slider_leveren"
        self.entity_id       = "sensor.cloudems_slider_leveren"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        zp = data.get("zonneplan") or {}
        v = zp.get("deliver_to_home_w")
        return round(float(v), 0) if v is not None else None


class CloudEMSSliderZonladenSensor(CoordinatorEntity, SensorEntity):
    """sensor.cloudems_slider_zonladen — Zonneplan 'zonneladen' slider waarde (W)."""
    _attr_device_class  = SensorDeviceClass.POWER
    _attr_state_class   = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_icon = "mdi:solar-power"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Slider Zonneladen"
        self._attr_unique_id = f"{entry.entry_id}_slider_zonladen"
        self.entity_id       = "sensor.cloudems_slider_zonladen"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        zp = data.get("zonneplan") or {}
        v = zp.get("solar_charge_w")
        return round(float(v), 0) if v is not None else None


class CloudEMSBoilerEfficiencySensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_boiler_efficiency — boiler efficiëntiescore (0-100).
    Berekend als: (graden gestegen × tank_liter × 1.163) / kWh_verbruikt
    Vergeleken met theoretisch maximum → percentage.
    Detecteert vroege slijtage bij consistent lage score.
    """
    _attr_icon       = "mdi:water-boiler"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0

    # Theoretisch: 1 kWh verwarmt 860 liter water 1°C (waterspecifieke warmte)
    # In praktijk: 85-95% efficiënt voor een goede boiler
    _THEORETICAL_WH_PER_LITER_PER_DEGREE = 1.163  # Wh/(L·°C)

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Boiler Efficiëntie"
        self._attr_unique_id = f"{entry.entry_id}_boiler_efficiency"
        self.entity_id       = "sensor.cloudems_boiler_efficiency"
        self._samples: list[dict] = []  # rolling window van heating cycles

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        boilers = data.get("boiler_status", [])
        if not boilers:
            for g in data.get("boiler_groups_status", []):
                boilers = g.get("boilers", [])
                if boilers:
                    break
        if not boilers:
            return None

        b = boilers[0]
        temp_c    = b.get("temp_c")
        setpoint  = b.get("active_setpoint_c") or b.get("setpoint_c", 55)
        power_w   = b.get("current_power_w") or b.get("power_w", 0)
        cycle_kwh = b.get("cycle_kwh", 0)
        tank_l    = b.get("tank_liters", 80)
        is_on     = b.get("is_on", False)

        if temp_c is None or cycle_kwh <= 0:
            return None

        # Bereken efficiëntie op basis van huidige verwarmingscyclus
        # temp_rise = verschil tussen huidige temp en start van cyclus
        # We schatten start als (setpoint - temp_deficit)
        temp_deficit = b.get("temp_deficit_c")
        if temp_deficit is None:
            return None

        temp_rise = max(0, setpoint - temp_c - temp_deficit + temp_deficit)
        # Eenvoudiger: bereken op basis van totaal kWh en temp
        if setpoint > temp_c:
            temp_rise = setpoint - temp_c
        else:
            temp_rise = 5.0  # boiler is op temp, kleine maintenance warmte

        theoretical_kwh = (temp_rise * tank_l * self._THEORETICAL_WH_PER_LITER_PER_DEGREE) / 1000
        if theoretical_kwh <= 0 or cycle_kwh <= 0:
            return None

        efficiency = min(100, round((theoretical_kwh / max(cycle_kwh, theoretical_kwh * 0.5)) * 100))
        return efficiency

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        boilers = data.get("boiler_status", [])
        if not boilers:
            return {}
        b = boilers[0]
        return {
            "cycle_kwh":     b.get("cycle_kwh", 0),
            "temp_c":        b.get("temp_c"),
            "setpoint_c":    b.get("active_setpoint_c") or b.get("setpoint_c"),
            "tank_liters":   b.get("tank_liters", 80),
            "interpretatie": self._interpret(),
        }

    def _interpret(self) -> str:
        v = self.native_value
        if v is None:   return "Geen data"
        if v >= 90:     return "Uitstekend"
        if v >= 75:     return "Goed"
        if v >= 60:     return "Matig — controleer isolatie"
        return "Slecht — mogelijk slijtage of kalkafzetting"


class CloudEMSGoedkoopstelaadmomentSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_goedkoopste_laadmoment
    Toont het goedkoopste laadmoment in de komende 8 uur.
    Stuurt HA-notificatie als de huidige prijs >30% hoger is dan het goedkoopste moment.
    """
    _attr_icon       = "mdi:clock-star-four-points"
    _attr_state_class = None
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Goedkoopste Laadmoment"
        self._attr_unique_id = f"{entry.entry_id}_goedkoopste_laadmoment"
        self.entity_id       = "sensor.cloudems_goedkoopste_laadmoment"
        self._last_notify_ts = 0.0

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_EV)

    @property
    def native_value(self) -> str | None:
        info = self._get_info()
        if not info:
            return None
        return info["best_hour_label"]

    @property
    def extra_state_attributes(self) -> dict:
        info = self._get_info()
        if not info:
            return {}
        return info

    def _get_info(self) -> dict | None:
        import time
        data = self.coordinator.data or {}
        # Lees prijsforecast uit _last_price_info.next_hours
        price_info    = getattr(self.coordinator, "_last_price_info", None) or {}
        next_hours    = price_info.get("next_hours", [])
        current_price = getattr(self.coordinator, "_last_known_price", None)
        if not next_hours or current_price is None:
            return None

        # Goedkoopste moment in komende 8 uur
        import datetime
        now_h = datetime.datetime.now().hour
        window = [h for h in next_hours if h.get("price") is not None][:8]
        if not window:
            return None

        best = min(window, key=lambda h: h.get("price", 999))
        best_price = best.get("price", 0)
        best_label = best.get("label", f"{best.get('hour', 0):02d}:00")

        saving_pct = round((current_price - best_price) / max(current_price, 0.001) * 100)

        # Notificatie als besparing > 30% en nog niet recent gestuurd (max 1x per 2u)
        if saving_pct >= 30 and (time.time() - self._last_notify_ts) > 7200:
            self._last_notify_ts = time.time()
            self._send_notification(best_label, best_price, current_price, saving_pct)

        return {
            "best_hour":       best_label,
            "best_hour_label": best_label,
            "best_price_ct":   round(best_price * 100, 1),
            "current_price_ct": round(current_price * 100, 1),
            "saving_pct":      saving_pct,
            "advies":          f"Wacht tot {best_label} — {saving_pct}% goedkoper" if saving_pct > 10 else "Nu laden is gunstig",
        }

    def _send_notification(self, best_hour: str, best_price: float,
                           current_price: float, saving_pct: int) -> None:
        """Stuur HA persistent notificatie."""
        try:
            self.coordinator.hass.components.persistent_notification.async_create(
                message=(
                    f"💡 Over een uur is stroom **{saving_pct}% goedkoper**.\n\n"
                    f"Goedkoopste moment: **{best_hour}** "
                    f"({round(best_price*100,1)} ct/kWh)\n"
                    f"Nu: {round(current_price*100,1)} ct/kWh\n\n"
                    f"Overweeg boiler of EV-lading uit te stellen."
                ),
                title="CloudEMS — Goedkoper laadmoment",
                notification_id="cloudems_goedkoopste_laadmoment",
            )
        except Exception:
            pass


# ── Seizoensvergelijking sensor ───────────────────────────────────────────────

class CloudEMSSeizoensvergelijkingSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_seizoensvergelijking
    Vergelijkt huidige maand met vorige maand en vorig jaar.
    Data komt uit solar_learner (PV) + cost_forecaster (verbruik) + coordinator accumulators.
    """
    _attr_icon       = "mdi:calendar-compare"
    _attr_state_class = None
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Seizoensvergelijking"
        self._attr_unique_id = f"{entry.entry_id}_seizoensvergelijking"
        self.entity_id       = "sensor.cloudems_seizoensvergelijking"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self) -> str:
        import datetime
        return datetime.datetime.now().strftime("%Y-%m")

    @property
    def extra_state_attributes(self) -> dict:
        import datetime, time
        data  = self.coordinator.data or {}
        now   = datetime.datetime.now()
        MONTHS = ["","Jan","Feb","Mrt","Apr","Mei","Jun","Jul","Aug","Sep","Okt","Nov","Dec"]

        # Huidige maand accumulatoren uit coordinator
        cost_month    = getattr(self.coordinator, "_cost_month_eur", 0.0) or 0.0
        solar_learner = getattr(self.coordinator, "_solar_learner", None)

        # PV data per inverter uit solar_learner
        pv_peak_w = 0.0
        pv_confident = False
        if solar_learner:
            try:
                for inv_data in solar_learner._profiles.values():
                    pv_peak_w += getattr(inv_data, "peak_power_w", 0) or 0
                    if getattr(inv_data, "confident", False):
                        pv_confident = True
            except Exception as _err:
                pass

        # Cost forecaster seizoensdata
        cf = getattr(self.coordinator, "_cost_forecaster", None)
        seasonal = cf.get_seasonal_summary() if cf else {}

        # Huidige maand vs vorige maand (uit cost_forecaster patterns)
        this_month_daily = 0.0
        prev_month_daily = 0.0
        if cf and hasattr(cf, "_patterns"):
            try:
                daily_total = sum(p.avg_kwh for p in cf._patterns.values())
                this_month_daily = round(daily_total, 2)
                # Vorige maand: simpele benadering via patterns (zelfde model, andere seizoensfactor)
                prev_month_daily = this_month_daily  # TODO: per-maand opslag in toekomstige versie
            except Exception:
                pass

        return {
            "huidige_maand":        MONTHS[now.month],
            "huidig_jaar":          now.year,
            "vorige_maand":         MONTHS[now.month - 1] if now.month > 1 else MONTHS[12],
            "cost_month_eur":       round(cost_month, 2),
            "daily_avg_kwh":        seasonal.get("daily_avg_kwh", 0),
            "peak_consumption_hour": seasonal.get("peak_consumption_hour"),
            "model_trained":        seasonal.get("model_trained", False),
            "pv_peak_wp":           round(pv_peak_w, 0),
            "pv_confident":         pv_confident,
            "vergelijking_beschikbaar": seasonal.get("model_trained", False),
            "tip": self._get_tip(now.month, seasonal.get("daily_avg_kwh", 0)),
        }

    def _get_tip(self, month: int, daily_kwh: float) -> str:
        if month in (11, 12, 1, 2):
            return "Wintermaand — verwarmingsvraag hoog, minimale PV. Overweeg nachttarief voor boiler."
        if month in (3, 4, 9, 10):
            return "Overgangsmaand — PV neemt toe/af. Goede periode om setpoints te optimaliseren."
        return "Zomermaand — maximale PV. Boiler en EV zoveel mogelijk op zonne-energie laden."


# ── Boiler planning sensor ────────────────────────────────────────────────────

class CloudEMSBoilerPlanningsSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_boiler_planning
    Voorspelt wanneer de boiler de volgende keer moet opwarmen op basis van:
    - Huidige temperatuur
    - Geleerde thermisch verlies (°C/uur)
    - Geconfigureerd setpoint en hysterese
    """
    _attr_icon       = "mdi:water-boiler-auto"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "min"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Boiler Planning"
        self._attr_unique_id = f"{entry.entry_id}_boiler_planning"
        self.entity_id       = "sensor.cloudems_boiler_planning"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self) -> float | None:
        info = self._get_info()
        return info.get("min_tot_trigger") if info else None

    @property
    def extra_state_attributes(self) -> dict:
        return self._get_info() or {}

    def _get_info(self) -> dict | None:
        data = self.coordinator.data or {}
        boilers = data.get("boiler_status", [])
        if not boilers:
            for g in data.get("boiler_groups_status", []):
                boilers = g.get("boilers", [])
                if boilers:
                    break
        if not boilers:
            return None

        b = boilers[0]
        temp_c       = b.get("temp_c")
        setpoint     = b.get("active_setpoint_c") or b.get("setpoint_c", 55)
        loss_c_h     = b.get("thermal_loss_c_h", 0)
        hysteresis   = 3.0  # standaard CloudEMS hysterese

        if temp_c is None or loss_c_h <= 0:
            return {
                "status": "Onbekend — thermisch verlies nog niet geleerd",
                "min_tot_trigger": None,
                "loss_c_h": loss_c_h,
            }

        trigger_temp = setpoint - hysteresis
        if temp_c <= trigger_temp:
            return {
                "status": "Nu actief of wacht op trigger",
                "min_tot_trigger": 0,
                "temp_c": temp_c,
                "trigger_temp": trigger_temp,
                "loss_c_h": loss_c_h,
            }

        delta_to_trigger = temp_c - trigger_temp
        hours_until = delta_to_trigger / loss_c_h
        min_until = round(hours_until * 60)

        import datetime
        trigger_at = datetime.datetime.now() + datetime.timedelta(hours=hours_until)

        return {
            "status": f"Trigger over {min_until} min ({trigger_at.strftime('%H:%M')})",
            "min_tot_trigger":  min_until,
            "trigger_om":       trigger_at.strftime("%H:%M"),
            "temp_nu_c":        round(temp_c, 1),
            "trigger_temp_c":   round(trigger_temp, 1),
            "setpoint_c":       round(setpoint, 1),
            "loss_c_h":         round(loss_c_h, 3),
            "label":            b.get("label", "Boiler 1"),
        }


# ── Anomalie grid sensor met notificatie ─────────────────────────────────────

class CloudEMSAnomalieGridSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_anomalie_grid
    Detecteert structureel afwijkend netverbruik t.o.v. geleerd patroon.
    Stuurt HA notificatie bij aanhoudende anomalie (>15 min).
    Gebouwd bovenop de bestaande HomeBaselineLearner.
    """
    _attr_icon       = "mdi:transmission-tower-export"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry              = entry
        self._attr_name          = "CloudEMS Anomalie Netverbruik"
        self._attr_unique_id     = f"{entry.entry_id}_anomalie_grid"
        self.entity_id           = "sensor.cloudems_anomalie_grid"
        self._anomaly_start_ts   = 0.0
        self._last_notify_ts     = 0.0
        self._notify_threshold_s = 15 * 60  # 15 minuten aanhoudend

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_HOUSE)

    @property
    def native_value(self) -> float:
        bl = (self.coordinator.data or {}).get("baseline", {})
        return bl.get("deviation_w", 0.0) or 0.0

    @property
    def extra_state_attributes(self) -> dict:
        import time
        bl       = (self.coordinator.data or {}).get("baseline", {})
        anomaly  = bl.get("anomaly", False)
        dev_w    = bl.get("deviation_w", 0.0) or 0.0
        exp_w    = bl.get("expected_w", 0.0) or 0.0
        cur_w    = bl.get("current_w", 0.0) or 0.0

        # Track aanhoudende anomalie
        now = time.time()
        if anomaly:
            if self._anomaly_start_ts == 0:
                self._anomaly_start_ts = now
            duration_min = round((now - self._anomaly_start_ts) / 60)
            # Stuur notificatie na drempel, max 1x per uur
            if duration_min >= 15 and (now - self._last_notify_ts) > 3600:
                self._last_notify_ts = now
                self._send_notification(dev_w, exp_w, cur_w, duration_min)
        else:
            self._anomaly_start_ts = 0.0
            duration_min = 0

        return {
            "anomalie":         anomaly,
            "afwijking_w":      round(dev_w, 0),
            "verwacht_w":       round(exp_w, 0),
            "huidig_w":         round(cur_w, 0),
            "aanhoudend_min":   duration_min if anomaly else 0,
            "model_gereed":     bl.get("model_ready", False),
            "getrainde_slots":  bl.get("trained_slots", 0),
            "status": (
                f"⚠️ +{round(dev_w)}W boven normaal ({duration_min} min)" if anomaly
                else "✅ Normaal verbruik"
            ),
        }

    def _send_notification(self, dev_w: float, exp_w: float,
                           cur_w: float, duration_min: int) -> None:
        try:
            self.coordinator.hass.components.persistent_notification.async_create(
                message=(
                    f"⚠️ Ongewoon hoog netverbruik al **{duration_min} minuten**.\n\n"
                    f"Verwacht: {round(exp_w)} W · Huidig: {round(cur_w)} W\n"
                    f"Afwijking: **+{round(dev_w)} W**\n\n"
                    f"Controleer of er een apparaat aan staat dat dat niet hoort."
                ),
                title="CloudEMS — Anomalie netverbruik",
                notification_id="cloudems_anomalie_grid",
            )
        except Exception:
            pass


# ── Boiler efficiency verbeterd met rolling average ──────────────────────────

class CloudEMSBoilerEfficiencyV2Sensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_boiler_efficiency_avg
    Rolling average efficiency over de laatste 5 verwarmingscycli.
    Detecteert slijtage als de trend daalt over meerdere cycli.
    """
    _attr_icon       = "mdi:water-boiler"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0

    _THEORETICAL_WH_PER_LITER_PER_DEGREE = 1.163

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Boiler Efficiëntie Gemiddeld"
        self._attr_unique_id = f"{entry.entry_id}_boiler_efficiency_avg"
        self.entity_id       = "sensor.cloudems_boiler_efficiency_avg"
        self._samples:   list[float] = []   # laatste 10 cyclus-efficiënties
        self._last_cycle_kwh = 0.0
        self._last_temp_c    = None

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_BOILER)

    @property
    def native_value(self) -> float | None:
        self._maybe_record_sample()
        if not self._samples:
            return None
        return round(sum(self._samples) / len(self._samples))

    @property
    def extra_state_attributes(self) -> dict:
        samples = list(self._samples)
        if not samples:
            return {"status": "Wacht op verwarmingscycli"}
        avg = round(sum(samples) / len(samples))
        # Trend: vergelijk eerste helft met tweede helft
        mid = len(samples) // 2
        if mid > 0:
            trend_old = sum(samples[:mid]) / mid
            trend_new = sum(samples[mid:]) / len(samples[mid:])
            trend = round(trend_new - trend_old, 1)
        else:
            trend = 0.0

        return {
            "gemiddeld_pct":   avg,
            "samples":         len(samples),
            "laatste_5":       [round(s) for s in samples[-5:]],
            "trend":           trend,
            "trend_label":     "📈 Verbeterend" if trend > 2 else ("📉 Verslechterend — check kalk/slijtage" if trend < -5 else "➡️ Stabiel"),
            "interpretatie":   self._interpret(avg),
        }

    def _maybe_record_sample(self) -> None:
        """Sla efficiëntie op bij het einde van een verwarmingscyclus."""
        data = self.coordinator.data or {}
        boilers = data.get("boiler_status", [])
        if not boilers:
            return

        b        = boilers[0]
        is_on    = b.get("is_on", False)
        temp_c   = b.get("temp_c")
        setpoint = b.get("active_setpoint_c") or b.get("setpoint_c", 55)
        cycle_kwh = b.get("cycle_kwh", 0)
        tank_l   = b.get("tank_liters", 80)

        # Cyclus klaar: boiler was aan en is net uit + heeft kWh verbruikt
        if (not is_on and self._last_cycle_kwh > 0.1
                and temp_c is not None and self._last_temp_c is not None):
            temp_rise = max(0, temp_c - self._last_temp_c)
            if temp_rise > 2:
                theoretical = (temp_rise * tank_l * self._THEORETICAL_WH_PER_LITER_PER_DEGREE) / 1000
                eff = min(100, (theoretical / self._last_cycle_kwh) * 100)
                self._samples.append(round(eff, 1))
                if len(self._samples) > 10:
                    self._samples.pop(0)

        if is_on:
            self._last_cycle_kwh = cycle_kwh
            self._last_temp_c    = temp_c or self._last_temp_c
        else:
            self._last_cycle_kwh = 0.0

    def _interpret(self, avg: float) -> str:
        if avg >= 90: return "Uitstekend"
        if avg >= 75: return "Goed"
        if avg >= 60: return "Matig — controleer isolatie of kalkafzetting"
        return "Slecht — mogelijke slijtage, aanbevolen onderhoud"


class CloudEMSTelemetrySensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_telemetry
    Toont telemetry status: opt-in staat, installatie-ID (kort), laatste upload.
    Gebruiker kan opt-in aan/uitzetten via CloudEMS instellingen.
    """
    _attr_icon  = "mdi:cloud-upload"
    _attr_state_class = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Telemetrie"
        self._attr_unique_id = f"{entry.entry_id}_telemetry"
        self.entity_id       = "sensor.cloudems_telemetry"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> str:
        tel = getattr(self.coordinator, "_telemetry", None)
        if tel is None:
            return "niet actief"
        return "actief" if tel._enabled else "opt-out"

    @property
    def extra_state_attributes(self) -> dict:
        tel = getattr(self.coordinator, "_telemetry", None)
        if tel is None:
            return {}
        return {
            "installation_id":  tel.installation_id_short,
            "enabled":          tel._enabled,
            "geconfigureerd":   tel.is_configured,
            "gdpr_info":        "Alleen anonieme metrics. Geen persoonlijke data. Opt-in.",
            "data_bevat":       "versie, beslissingstypes, foutcodes, cyclusduur, boilercycli",
            "backend":          "Firebase Firestore",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.6.152 — Performance Monitor Sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSPerformanceSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_performance

    Shows current performance mode (NORMAL/REDUCED/MINIMAL/CRITICAL)
    and cycle timing statistics. Used on the diagnostics dashboard.
    """
    _attr_icon       = "mdi:speedometer"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "ms"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Performance"
        self._attr_unique_id = f"{entry.entry_id}_performance"
        self.entity_id       = "sensor.cloudems_performance"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SYSTEM)

    @property
    def native_value(self) -> float:
        """Returns average cycle time in ms."""
        perf = getattr(self.coordinator, "_perf", None)
        if perf is None:
            return 0.0
        return perf.avg_ms

    @property
    def extra_state_attributes(self) -> dict:
        perf = getattr(self.coordinator, "_perf", None)
        if perf is None:
            return {}
        return perf.get_status_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# v4.6.157 — Shutter Schedule Learning Progress Sensor (per rolluik)
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSShutterLearnProgressSensor(CoordinatorEntity, SensorEntity):
    """
    sensor.cloudems_rolluik_<safe>_leer_voortgang

    State:
      • 0        — leren voltooid (genoeg data voor alle dagen)
      • N (int)  — nog N waarnemingen nodig
      • None     — leren uitgeschakeld of controller niet beschikbaar

    Attributes:
      • needs_data       — zelfde als state (int)
      • learning_enabled — bool
      • open_confidence  — gem. confidence open-tijden (0.0–1.0)
      • close_confidence — gem. confidence sluit-tijden (0.0–1.0)
      • open_today       — vandaag toegepaste opentijd
      • close_today      — vandaag toegepaste sluittijd
    """

    _attr_icon = "mdi:school-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None
    _attr_has_entity_name = False

    def __init__(self, coordinator, entry, shutter_cfg: dict):
        super().__init__(coordinator)
        self._entry      = entry
        self._shutter_id = shutter_cfg.get("entity_id", "")
        label            = shutter_cfg.get("label") or self._shutter_id.split(".")[-1]
        safe             = self._shutter_id.split(".")[-1].replace("-", "_")
        self._attr_name      = f"CloudEMS Tijdleren Voortgang {label}"
        self._attr_unique_id = f"{entry.entry_id}_shutter_learn_progress_{safe}"
        self.entity_id       = f"sensor.cloudems_rolluik_{safe}_leer_voortgang"

    @property
    def device_info(self): return sub_device_info(self._entry, SUB_SHUTTER)

    def _shutter_status(self) -> dict:
        """Haal de status dict van dit rolluik op uit coordinator data."""
        d = self.coordinator.data or {}
        shutters = (d.get("shutters") or {}).get("shutters", [])
        for s in shutters:
            if s.get("entity_id") == self._shutter_id:
                return s
        return {}

    @property
    def native_value(self):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return None
        if not sc.get_schedule_learning(self._shutter_id):
            return None
        s = self._shutter_status()
        return s.get("schedule_needs_data", None)

    @property
    def extra_state_attributes(self) -> dict:
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return {}
        learning = sc.get_schedule_learning(self._shutter_id)
        s = self._shutter_status()
        schedule = s.get("schedule_learned", {})
        # Gemiddelde confidence open / sluit over alle dagen
        def avg_conf(action: str) -> float:
            vals = [v.get("confidence", 0.0) for v in schedule.get(action, {}).values()]
            return round(sum(vals) / len(vals), 2) if vals else 0.0
        return {
            "needs_data":       s.get("schedule_needs_data", 0),
            "learning_enabled": learning,
            "open_confidence":  avg_conf("open"),
            "close_confidence": avg_conf("close"),
            "open_today":       s.get("schedule_open_today"),
            "close_today":      s.get("schedule_close_today"),
        }


# ── v4.6.456: CloudEMS Windsnelheid Sensor ───────────────────────────────────
class CloudEMSWindsnelheidSensor(CoordinatorEntity, SensorEntity):
    """Exposeert de windsnelheid die ShutterController intern gebruikt (km/h)."""

    _attr_has_entity_name   = False
    _attr_name              = "CloudEMS Windsnelheid"
    _attr_icon              = "mdi:weather-windy"
    _attr_device_class      = SensorDeviceClass.WIND_SPEED
    _attr_state_class       = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "km/h"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_windsnelheid"
        self.entity_id       = "sensor.cloudems_windsnelheid"

    @property
    def device_info(self):
        return sub_device_info(self._entry, SUB_SHUTTER)

    @property
    def native_value(self):
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return None
        wind_ms = getattr(sc, "_current_wind_speed", None)
        if wind_ms is None:
            return None
        return round(float(wind_ms) * 3.6, 1)  # m/s → km/h

    @property
    def extra_state_attributes(self) -> dict:
        sc = getattr(self.coordinator, "_shutter_ctrl", None)
        if sc is None:
            return {}
        wind_ms  = getattr(sc, "_current_wind_speed", None)
        thr_ms   = getattr(sc, "_wind_threshold_ms", 12.0)
        storm    = getattr(sc, "_is_storm", False)
        thr_kmh  = round(float(thr_ms) * 3.6, 1)
        return {
            "wind_ms":          wind_ms,
            "drempel_kmh":      thr_kmh,
            "storm_actief":     storm,
            "windbeveiliging":  (wind_ms is not None and wind_ms >= thr_ms) or storm,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.6.498 — Decision Outcome Learner Sensor
# ═══════════════════════════════════════════════════════════════════════════════

class CloudEMSDecisionLearnerSensor(CoordinatorEntity, SensorEntity):
    """Sensor die de status van de Decision Outcome Learner exposeert."""

    _attr_icon       = "mdi:brain"
    _attr_state_class = None
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry          = entry
        self._attr_name      = "CloudEMS Decision Outcome Learner"
        self._attr_unique_id = f"{entry.entry_id}_decision_learner"
        self.entity_id       = "sensor.cloudems_decision_learner"

    @property
    def device_info(self): return main_device_info(self._entry)

    @property
    def native_value(self) -> str:
        learner = getattr(self.coordinator, "_decision_learner", None)
        if learner is None:
            return "0"
        status = learner.get_status()
        return str(status.get("total_evaluated", 0))

    @property
    def extra_state_attributes(self) -> dict:
        learner = getattr(self.coordinator, "_decision_learner", None)
        if learner is None:
            return {"status": "niet geladen"}
        return _trim_attrs(learner.get_status())
