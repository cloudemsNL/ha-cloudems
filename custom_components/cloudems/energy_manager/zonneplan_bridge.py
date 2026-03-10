# -*- coding: utf-8 -*-
"""
CloudEMS Zonneplan Provider — v2.2.0

Wijzigingen t.o.v. v2.1.0:
  - decide_action_v3(): volledig herschreven beslissingslogica
      * PVContext: integreert actueel PV-vermogen + per-uur PV-forecast
      * SoH-correctie: max SoC verlaagd bij batterijslijtage
      * Proportionele SoC-reserve: schaalt met n toekomstige HIGH-uren
      * PV-gecorrigeerde max SoC: bewaar ruimte als morgen veel PV verwacht
      * Urgentie-schaling: laadvermogen proportioneel met tijd tot HIGH
      * Negatief tarief: altijd maximaal laden (prioriteit 1)
      * DecisionResult: bevat vermogen, confidence, reden — niet alleen actie
  - _build_pv_context(): verwerkt coordinator PV-data naar PVContext
  - async_apply_forecast_decision_v3(): gebruikt DecisionResult voor sturing
  - decide_action() behouden als backwards-compat alias (→ v3)

Sturingspaden:
  Pad A (modern): select battery_control_mode + number sliders
    - home_optimization  → deliver_to_home + solar_charge sliders
    - self_consumption   → eigen zonnestroom
    - powerplay          → Zonneplan AI
  Pad B (legacy): manual_control switch + manual_control_state

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .battery_provider import (
    BatteryProvider,
    BatteryProviderState,
    BatteryProviderRegistry,
    ProviderWizardHint,
)
from .saldering_context import SalderingContext

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY      = "cloudems_zonneplan_provider_v1"
STORAGE_VERSION  = 1
DOMAIN_ZONNEPLAN = "zonneplan_one"


# ── PV-context (aangeleverd door coordinator) ──────────────────────────────────

@dataclass
class PVContext:
    """
    Alle PV-informatie die de beslissingslogica nodig heeft.
    Aangeleverd door de coordinator via async_apply_forecast_decision_v3().
    """
    solar_now_w:            float = 0.0
    solar_surplus_w:        float = 0.0
    forecast_today_kwh:     float = 0.0
    forecast_tomorrow_kwh:  float = 0.0
    hourly:                 list  = field(default_factory=list)
    # Berekend door _build_pv_context():
    pv_kwh_next_8h:         float = 0.0   # verwachte PV komende 8 uur (kWh)
    pv_peak_next_8h_w:      float = 0.0   # verwacht piekvermogen komende 8 uur (W)
    pv_covers_charge:       bool  = False  # PV ≥ 60% van max laadvermogen dit uur


# ── Beslissingsresultaat ───────────────────────────────────────────────────────

@dataclass
class DecisionResult:
    """Volledig onderbouwd beslissingsresultaat — bevat vermogen, confidence en reden."""
    action:            "ZPAction"
    charge_power_w:    Optional[float] = None  # None = gebruik provider default
    discharge_power_w: Optional[float] = None
    confidence:        float = 1.0             # 0–1: zekerheid van de beslissing
    bypass_antiround:  bool  = False
    reasons:           list  = field(default_factory=list)
    soc_target:        float = 0.0
    soc_reachable:     float = 0.0


class ZPControlMode(str, Enum):
    HOME_OPTIMIZATION = "home_optimization"
    SELF_CONSUMPTION  = "self_consumption"
    POWERPLAY         = "powerplay"


class ZPManualState(str, Enum):
    CHARGE    = "charge"
    DISCHARGE = "discharge"
    STANDBY   = "standby"


class ZPTariffGroup(str, Enum):
    LOW    = "low"
    NORMAL = "normal"
    HIGH   = "high"


# ── Beslissing-uitkomsten van decide_action() ──────────────────────────────
class ZPAction(str, Enum):
    CHARGE    = "charge"     # laden is aanbevolen
    DISCHARGE = "discharge"  # ontladen is aanbevolen
    HOLD      = "hold"       # niets doen / huisoptimalisatie
    POWERPLAY = "powerplay"  # laat Zonneplan het zelf doen


_ENT_PATTERNS: dict[str, list[str]] = {
    # ── Besturingsmodus select ─────────────────────────────────────────────────
    # EN: select.{name}_battery_control_mode
    # NL: select.batterijbesturingsmodus (of select.{name}_batterijbesturingsmodus)
    "control_mode":         ["battery_control_mode",        "batterijbesturingsmodus"],

    # ── Huisoptimalisatie sliders (number entities) ────────────────────────────
    # EN: number.{name}_deliver_to_home_power / number.{name}_solar_charge_power
    # NL: number.leveren_aan_huis (of leveren_aan_huis_vermogen)
    #     number.zonnestroom_opslaan (of zonnestroom_opslaan_vermogen)
    "deliver_to_home":      ["deliver_to_home_power",       "delivery_to_home",
                             "leveren_aan_huis_vermogen",   "leveren_aan_huis"],
    "solar_charge":         ["solar_charge_power",          "solar_charging_power",
                             "zonnestroom_opslaan"],
    "max_charge_home":      ["max_charge_power_home_optimization",
                             "max_charge_home_optimization",
                             "maximaal_opladen_thuis"],
    "max_discharge_home":   ["max_discharge_power_home_optimization",
                             "max_discharge_home_optimization",
                             "maximaal_ontladen_thuis"],

    # ── SOC / Percentage ───────────────────────────────────────────────────────
    # EN: sensor.{name}_percentage  (README: "Percentage %")
    # NL: sensor.thuisbatterij_percentage  (Joan's install)
    # Fallback: battery_percentage, battery_so_c, batterijpercentage, laadniveau
    "soc":                  ["battery_percentage",          "battery_so_c",
                             "batterijpercentage",          "laadniveau",
                             "thuisbatterij_percentage"],

    # ── Vermogen (W) ───────────────────────────────────────────────────────────
    # EN: sensor.{name}_power  (README: "Power W (default disabled)")
    # NL: sensor.thuisbatterij_power  (Joan's install)
    # Fallback: battery_power, batterijvermogen
    "power":                ["battery_power",               "batterijvermogen",
                             "thuisbatterij_power"],

    # ── Status / Staat ─────────────────────────────────────────────────────────
    # EN: sensor.{name}_battery_state  (README: "Battery state")
    # NL: sensor.batterijstatus
    "state":                ["battery_state",               "batterijstatus",
                             "thuisbatterij_battery_state"],

    # ── Cycli ──────────────────────────────────────────────────────────────────
    # EN: sensor.{name}_battery_cycles  (README: "Battery cycles")
    # NL: sensor.thuisbatterij_battery_cycles  (Joan's install)
    "cycles":               ["battery_cycles",              "batterijcycli",
                             "laadcycli"],

    # ── Boolean switches / binary sensors ─────────────────────────────────────
    # EN: binary_sensor.{name}_dynamic_charging_enabled
    # NL: binary_sensor.dynamisch_laden / dynamische_load_balancing_ingeschakeld
    "dynamic_charging":     ["dynamic_charging_enabled",
                             "dynamisch_laden",
                             "dynamische_load_balancing_ingeschakeld"],
    "manual_control":       ["manual_control_enabled",
                             "handmatige_bediening"],
    "manual_state":         ["manual_control_state",
                             "handmatige_bedieningsstatus"],
    "home_opt_active":      ["home_optimization_active",
                             "huisoptimalisatie_actief"],
    "home_opt_enabled":     ["home_optimization_enabled",
                             "huisoptimalisatie_ingeschakeld"],
    "self_consumption":     ["self_consumption_enabled",
                             "zelfverbruik"],
    "grid_congestion":      ["grid_congestion_active",
                             "netcongestie_actief"],

    # ── Tariefgroep / forecast ─────────────────────────────────────────────────
    # EN: sensor.zonneplan_current_tariff_group / sensor.zonneplan_tariff_group
    # NL: sensor.huidig_tarief / sensor.tariefgroep
    "tariff_group":         ["current_tariff_group",        "tariff_group",
                             "huidig_tarief",               "tariefgroep",
                             "nexus_tariff_group",          "nexus_tariefgroep",
                             "current_tariff",              "electricity_tariff_group",
                             "actueel_tarief",              "huidig_tariffgroep"],
    "electricity_tariff":   ["current_electricity_tariff",  "electricity_tariff",
                             "huidig_elektriciteitstarief"],

    # ── Forecast tariefgroepen uur 1..8 ───────────────────────────────────────
    "forecast_h1":          ["forecast_tariff_group_hour_1",  "tariefgroep_uur_1"],
    "forecast_h2":          ["forecast_tariff_group_hour_2",  "tariefgroep_uur_2"],
    "forecast_h3":          ["forecast_tariff_group_hour_3",  "tariefgroep_uur_3"],
    "forecast_h4":          ["forecast_tariff_group_hour_4",  "tariefgroep_uur_4"],
    "forecast_h5":          ["forecast_tariff_group_hour_5",  "tariefgroep_uur_5"],
    "forecast_h6":          ["forecast_tariff_group_hour_6",  "tariefgroep_uur_6"],
    "forecast_h7":          ["forecast_tariff_group_hour_7",  "tariefgroep_uur_7"],
    "forecast_h8":          ["forecast_tariff_group_hour_8",  "tariefgroep_uur_8"],

    # ── Opbrengsten / productie (Zonneplan ONE integratie) ─────────────────────
    "production_today":     ["productie_vandaag",       "production_today",
                             "today_production"],
    "revenue_today":        ["thuisbatterij_today",     "vandaag",
                             "today_revenue",           "revenue_today"],
    "revenue_month":        ["result_this_month",       "opbrengst_deze_maand",
                             "revenue_this_month",      "this_month_revenue"],
    "revenue_year":         ["opbrengst_dit_jaar",      "revenue_this_year",
                             "annual_revenue"],
    "revenue_total":        ["totaal_verdiend",         "total_earnings",
                             "total_revenue"],
    "revenue_prev_month":   ["opbrengst_vorige_maand",  "revenue_last_month"],
    "revenue_prev_year":    ["opbrengst_vorig_jaar",    "revenue_last_year"],
    "energy_weekly":        ["nexus_energy_weekly",     "weekly_energy"],
    "powerplay_active":     ["powerplay"],
    "inverter_status":      ["omvormerstatus",          "inverter_status"],
}

_AVAILABLE_MODES = [
    {"id": "home_optimization", "label": "Huisoptimalisatie", "icon": "mdi:home-battery"},
    {"id": "self_consumption",  "label": "Zelfconsumptie",    "icon": "mdi:solar-power"},
    {"id": "powerplay",         "label": "Powerplay",         "icon": "mdi:lightning-bolt"},
]

# Anti-rondpomp drempel defaults (W)
_DEFAULT_MIN_HOUSE_LOAD_W = 300    # minimaal huisverbruik om te ontladen
_DEFAULT_EV_BLOCK_W       = 1000   # EV-verbruik waarboven ontladen geblokkeerd


class ZonneplanProvider(BatteryProvider):
    """Zonneplan Nexus batterij-provider voor CloudEMS — v2.1."""

    PROVIDER_ID    = "zonneplan"
    PROVIDER_LABEL = "Zonneplan Nexus"
    PROVIDER_ICON  = "mdi:home-battery-outline"

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(hass, config)
        self._store           = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entities:       dict[str, str]  = {}
        self._override_since: float           = 0.0
        self._saved_mode:     Optional[str]   = None
        # Configuratie-parameters
        self._restore_min:    int    = int(config.get("zonneplan_restore_after_min", 60))
        self._restore_mode:   bool   = config.get("zonneplan_restore_mode", True)
        self._min_soc:        float  = float(config.get("zonneplan_min_soc", 10.0))
        self._max_soc:        float  = float(config.get("zonneplan_max_soc", 95.0))
        self._charge_w:       float  = float(config.get("zonneplan_charge_w", 2500.0))
        self._discharge_w:    float  = float(config.get("zonneplan_discharge_w", 2500.0))
        # Anti-rondpompen
        self._min_house_w:    float  = float(config.get("zonneplan_min_house_load_w",
                                                        _DEFAULT_MIN_HOUSE_LOAD_W))
        self._ev_block_w:     float  = float(config.get("zonneplan_ev_block_w",
                                                        _DEFAULT_EV_BLOCK_W))
        self._ev_sensor:      Optional[str] = config.get("zonneplan_ev_sensor")
        self._house_sensor:   Optional[str] = config.get("zonneplan_house_sensor")
        # Forecast SOC-reserve
        self._soc_reserve_high: float = float(config.get("zonneplan_soc_reserve_high", 30.0))
        self._price_floor:      float = float(config.get("zonneplan_price_floor_eur", 0.05))
        # Idempotentie: cache van laatste gestuurde waarden
        self._last_sent_mode:      Optional[str]   = None
        self._last_sent_deliver_w: Optional[float] = None
        self._last_sent_solar_w:   Optional[float] = None
        self._last_decision_ts:    Optional[float] = None   # time.time() van laatste decide_action_v3
        self._last_decision_result: Optional[object] = None  # laatste DecisionResult
        # Hysterese voor surplus-slider: voorkomt heen-en-weer schakelen bij schommelend surplus
        self._surplus_slider_high: bool  = False   # True = slider staat nu hoog (surplus-modus)
        self._surplus_high_since:  float = 0.0     # timestamp eerste keer surplus > drempel
        self._last_slider_write:   float = 0.0     # timestamp laatste slider/mode schrijfactie

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        await super().async_setup()
        saved = await self._store.async_load() or {}
        self._override_since = float(saved.get("override_since", 0.0))
        self._saved_mode     = saved.get("saved_mode")
        self._last_sent_mode = saved.get("last_sent_mode")
        _LOGGER.info(
            "ZonneplanProvider v2.1: detected=%s enabled=%s entities=%s",
            self._detected, self._enabled, list(self._entities.keys()),
        )

    def update_config(self, config: dict) -> None:
        super().update_config(config)
        self._restore_min     = int(config.get("zonneplan_restore_after_min", self._restore_min))
        self._restore_mode    = config.get("zonneplan_restore_mode",   self._restore_mode)
        self._min_soc         = float(config.get("zonneplan_min_soc",  self._min_soc))
        self._max_soc         = float(config.get("zonneplan_max_soc",  self._max_soc))
        self._charge_w        = float(config.get("zonneplan_charge_w", self._charge_w))
        self._discharge_w     = float(config.get("zonneplan_discharge_w", self._discharge_w))
        self._min_house_w     = float(config.get("zonneplan_min_house_load_w", self._min_house_w))
        self._ev_block_w      = float(config.get("zonneplan_ev_block_w",      self._ev_block_w))
        self._ev_sensor       = config.get("zonneplan_ev_sensor",    self._ev_sensor)
        self._house_sensor    = config.get("zonneplan_house_sensor", self._house_sensor)
        self._soc_reserve_high= float(config.get("zonneplan_soc_reserve_high", self._soc_reserve_high))
        self._price_floor     = float(config.get("zonneplan_price_floor_eur",  self._price_floor))

    # ── Detectie ───────────────────────────────────────────────────────────────

    async def async_detect(self) -> bool:
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self._hass)
            found: dict[str, str] = {}

            # Eerste pass: doorzoek ALLE zonneplan_one platform entities (incl. tarieven, forecast)
            # én entities met "zonneplan" of "thuisbatterij" in de ID.
            # Tariefgroep-sensors staan op sensor.zonneplan_* — niet op thuisbatterij_* —
            # dus we splitsen de twee groepen: platform-match = alle keys, naam-match = batterij-keys.
            _battery_keys = {
                "control_mode", "deliver_to_home", "solar_charge", "max_charge_home",
                "max_discharge_home", "soc", "power", "state", "cycles",
                "dynamic_charging", "manual_control", "manual_state",
                "home_opt_active", "home_opt_enabled", "self_consumption", "grid_congestion",
            }
            _tariff_keys = {
                "tariff_group", "electricity_tariff",
                "forecast_h1", "forecast_h2", "forecast_h3", "forecast_h4",
                "forecast_h5", "forecast_h6", "forecast_h7", "forecast_h8",
            }
            _revenue_keys = {
                "production_today", "revenue_today", "revenue_month", "revenue_year",
                "revenue_total", "revenue_prev_month", "revenue_prev_year",
                "energy_weekly", "powerplay_active", "inverter_status",
            }

            for entry in reg.entities.values():
                eid = entry.entity_id
                platform = (entry.platform or "").lower()
                is_zp_platform = DOMAIN_ZONNEPLAN in platform
                is_zp_name     = "zonneplan" in eid.lower() or "thuisbatterij" in eid.lower()

                if not (is_zp_platform or is_zp_name):
                    continue

                # Bepaal welke keys we voor deze entity willen matchen
                # Platform-entries: alles (ook tarieven + opbrengsten)
                # Naam-only entries (thuisbatterij_*): batterij-keys + revenue-keys
                # (sensor.thuisbatterij_today / result_this_month staan NIET op zp platform)
                if is_zp_platform:
                    active_keys = _battery_keys | _tariff_keys | _revenue_keys
                elif is_zp_name:
                    active_keys = _battery_keys | _revenue_keys
                else:
                    active_keys = _battery_keys

                for key in active_keys:
                    if key not in found:
                        for pat in _ENT_PATTERNS.get(key, []):
                            if pat in eid:
                                found[key] = eid
                                break

            # Tweede pass: als soc of power nog ontbreekt, zoek generiek op suffix
            # (officiële fsaris integratie gebruikt {name}_percentage zonder "battery_" prefix)
            if "soc" not in found or "power" not in found:
                for entry in reg.entities.values():
                    eid = entry.entity_id
                    platform = (entry.platform or "").lower()
                    if DOMAIN_ZONNEPLAN not in platform:
                        continue
                    if "soc" not in found and eid.endswith("_percentage"):
                        found["soc"] = eid
                    if "power" not in found and eid.startswith("sensor.") and eid.endswith("_power"):
                        found["power"] = eid

            # Derde pass: tariefgroep-fallback — zoek sensor met state in {low,normal,high}
            # op het zonneplan_one platform, ook als naam niet matcht op bekende patronen.
            if "tariff_group" not in found:
                for entry in reg.entities.values():
                    eid = entry.entity_id
                    platform = (entry.platform or "").lower()
                    if DOMAIN_ZONNEPLAN not in platform:
                        continue
                    if not eid.startswith("sensor."):
                        continue
                    try:
                        state_obj = self._hass.states.get(eid)
                        if state_obj and state_obj.state.lower() in ("low", "normal", "high",
                                                                      "laag", "normaal", "hoog"):
                            found["tariff_group"] = eid
                            _LOGGER.debug(
                                "ZonneplanProvider: tariefgroep gevonden via state-scan: %s", eid
                            )
                            break
                    except Exception:
                        pass

            # Succes als soc OF control_mode gevonden (minimaal batterij aanwezig)
            if "soc" in found or "control_mode" in found:
                self._entities = found
                _LOGGER.debug(
                    "ZonneplanProvider detected: %d entities (%s)",
                    len(found), sorted(found.keys()),
                )
                return True
        except Exception as exc:
            _LOGGER.debug("ZonneplanProvider detectie fout: %s", exc)
        return False

    # ── State reading ──────────────────────────────────────────────────────────

    def read_state(self) -> BatteryProviderState:
        hs = self._hass.states

        def _f(key) -> Optional[float]:
            eid = self._entities.get(key)
            if not eid: return None
            st = hs.get(eid)
            if not st or st.state in ("unavailable", "unknown", "none", ""): return None
            try: return float(st.state)
            except: return None

        def _b(key) -> Optional[bool]:
            eid = self._entities.get(key)
            if not eid: return None
            st = hs.get(eid)
            if not st or st.state in ("unavailable", "unknown"): return None
            return st.state in ("on", "true")

        def _s(key) -> Optional[str]:
            eid = self._entities.get(key)
            if not eid: return None
            st = hs.get(eid)
            if not st or st.state in ("unavailable", "unknown", "none", ""): return None
            return st.state

        soc = _f("soc")
        if soc is not None and soc > 100:
            soc = round(soc / 10.0, 1)

        power = _f("power")
        if power is not None and abs(power) > 50_000:
            power = round(power / 1000.0, 1)
        elif power is not None and abs(power) < 50 and power != 0:
            # Waarschijnlijk kW (bv. -1.3 kW) — convert naar W
            power = round(power * 1000.0, 1)

        # Forecast tariefgroepen — normaliseer naar lowercase
        forecast = []
        for h in range(1, 9):
            val = _s(f"forecast_h{h}")
            if val:
                forecast.append(val.lower())

        mode_raw = _s("control_mode")
        # Normaliseer NL/EN labels van de Zonneplan select entity naar interne mode IDs
        _MODE_NORMALIZE: dict[str, str] = {
            "home_optimization":    "home_optimization",
            "self_consumption":     "self_consumption",
            "powerplay":            "powerplay",
            "manual_control":       "manual_control",
            # Nederlandse labels (Zonneplan NL integration)
            "thuisoptimalisatie":   "home_optimization",
            "zelfverbruik":         "self_consumption",
            "zelfconsumptie":       "self_consumption",
            "powerplay":            "powerplay",
            "handmatig":            "manual_control",
            # Engelse labels (mixed case)
            "home optimization":    "home_optimization",
            "self-consumption":     "self_consumption",
            "manual control":       "manual_control",
        }
        mode = _MODE_NORMALIZE.get(
            (mode_raw or "").lower().strip(), mode_raw
        ) if mode_raw else None
        self._last_state = BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc,
            power_w        = power,
            is_charging    = (power or 0) > 20,
            is_discharging = (power or 0) < -20,
            active_mode    = mode,
            available_modes= [m["id"] for m in _AVAILABLE_MODES],
            is_online      = soc is not None,
            raw = {
                "battery_state":        _s("state"),
                "control_mode":         mode,
                "deliver_to_home_w":    _f("deliver_to_home"),
                "solar_charge_w":       _f("solar_charge"),
                "max_charge_home_w":    _f("max_charge_home"),
                "max_discharge_home_w": _f("max_discharge_home"),
                "dynamic_charging":     _b("dynamic_charging"),
                "manual_control":       _b("manual_control"),
                "manual_state":         _s("manual_state"),
                "self_consumption":     _b("self_consumption"),
                "grid_congestion":      _b("grid_congestion"),
                # Gebruik "unknown" als geen tariefgroep gevonden — niet "normal"
                # zodat decide_action_v3() naar de POWERPLAY fallback gaat i.p.v. onjuiste NORMAL-logica
                "tariff_group":         (tg_raw := (_s("tariff_group") or "").lower()) or "unknown",
                "electricity_tariff_eur": _f("electricity_tariff"),
                "forecast_tariff_groups": forecast,
                "cycles":               int(c) if (c := _f("cycles")) else None,
            },
        )
        return self._last_state

    # ── Forecast beslissingslogica ─────────────────────────────────────────────

    # ── PV-helper ──────────────────────────────────────────────────────────────

    def _build_pv_context(
        self,
        solar_now_w:             float = 0.0,
        solar_surplus_w:         float = 0.0,
        pv_forecast_today_kwh:   float = 0.0,
        pv_forecast_tomorrow_kwh:float = 0.0,
        pv_forecast_hourly:      list  = None,
        battery_capacity_kwh:    float = 10.0,
    ) -> PVContext:
        """
        Verwerk ruwe PV-data van de coordinator naar een genormaliseerde PVContext.

        Dedupliceer op (inverter_id, hour) zodat meerdere inverters correct worden
        gesommeerd zonder dubbeltelling.
        """
        hourly    = pv_forecast_hourly or []
        now_h     = datetime.now(timezone.utc).hour
        max_ch_w  = self._charge_w

        # Dedupliceer op (inverter_id, hour) en sommeer forecast_w per uur
        hour_totals: dict[int, float] = {}
        seen: set = set()
        for h in hourly:
            key = (h.get("inverter_id", "?"), h.get("hour", -1))
            if key in seen:
                continue
            seen.add(key)
            hr = h.get("hour", -1)
            fw = float(h.get("forecast_w", 0.0) or 0.0)
            hour_totals[hr] = hour_totals.get(hr, 0.0) + fw

        pv_kwh_next_8h  = 0.0
        pv_peak_next_8h = 0.0
        pv_this_hour_w  = hour_totals.get(now_h, 0.0)

        for hr, fw in hour_totals.items():
            if now_h <= hr < now_h + 8:
                pv_kwh_next_8h  += fw / 1000.0   # W·h → kWh (1 uur)
                pv_peak_next_8h  = max(pv_peak_next_8h, fw)

        return PVContext(
            solar_now_w            = solar_now_w,
            solar_surplus_w        = solar_surplus_w,
            forecast_today_kwh     = pv_forecast_today_kwh,
            forecast_tomorrow_kwh  = pv_forecast_tomorrow_kwh,
            hourly                 = hourly,
            pv_kwh_next_8h         = round(pv_kwh_next_8h, 2),
            pv_peak_next_8h_w      = round(pv_peak_next_8h, 0),
            pv_covers_charge       = (pv_this_hour_w >= max_ch_w * 0.6),
        )

    # ── Kernbeslissing v3 ──────────────────────────────────────────────────────

    def decide_action_v3(
        self,
        pv: Optional[PVContext] = None,
        battery_capacity_kwh: float = 10.0,
        soh_pct: float = 100.0,
    ) -> DecisionResult:
        """
        Optimale batterijbeslissing v3 — combineert alle beschikbare signalen:

          Signalen:
            1. Zonneplan tariefgroep + 8-uurs forecast  (LOW/NORMAL/HIGH)
            2. EPEX prijs in €/kWh                      (absolute drempel)
            3. Actueel PV-vermogen + surplus             (anti-rondpomp input)
            4. Per-uur PV-forecast komende 8 uur        (laadurgentie bijstellen)
            5. PV-verwachting morgen                     (ruimte bewaren)
            6. SoC                                       (grenzen en target)
            7. SoH (batterijslijtage)                    (max SoC corrigeren)

          Prioriteitsvolgorde:
            1. Negatief tarief       → altijd laden (gratis/betaald krijgen)
            2. Prijs onder floor     → hold (te goedkoop voor actie)
            3. SoC-grensbescherming  → hold bij extremen
            4. HIGH tariefgroep      → ontladen, proportioneel met reserve + PV
            5. LOW tariefgroep       → laden, gecorrigeerd voor PV-verwachting
            6. NORMAL tariefgroep    → Powerplay tenzij duidelijke kans

          PV-correcties:
            - Neemt geen nettroom als PV dit uur al ≥ 60% van max laadvermogen dekt
            - Verlaagt max SoC als morgen veel PV verwacht (bewaar absorptieruimte)
            - Verhoogt minimale ontlaad-SoC als PV vandaag nog kWh levert
            - Vermindert ontlaadvermogen als PV surplus nu al bijdraagt

          Laadvermogen schaling:
            - Urgentie = 1.0 als HIGH over 1u, 0.3 als HIGH over 7u
            - Laadvermogen = max_charge_w × urgentie

          Returns:
            DecisionResult met action, vermogen, confidence, onderbouwing
        """
        if pv is None:
            pv = PVContext()

        raw      = self._last_state.raw
        soc      = self._last_state.soc_pct or 50.0
        tg       = raw.get("tariff_group", "normal") or "normal"
        forecast = raw.get("forecast_tariff_groups", [])   # uur +1..+8
        price    = raw.get("electricity_tariff_eur") or 0.0
        cap_kwh  = battery_capacity_kwh

        # ── SoH-gecorrigeerde SoC-grenzen ─────────────────────────────────────
        max_soc = self._max_soc
        if soh_pct < 80.0:
            max_soc = min(max_soc, 80.0)
        elif soh_pct < 90.0:
            max_soc = min(max_soc, 85.0)
        min_soc = self._min_soc

        # ── Toekomstige tariefgroepen (uur +1..+8, niet huidig uur) ───────────
        future_high  = [i for i, g in enumerate(forecast) if g == "high"]
        future_low   = [i for i, g in enumerate(forecast) if g == "low"]
        n_future_high = len(future_high)
        first_high_h  = future_high[0] + 1 if future_high else None
        first_low_h   = future_low[0]  + 1 if future_low  else None

        # ── Bereikbare SoC bij laden tot HIGH ─────────────────────────────────
        soc_per_hour = getattr(self, "_soc_per_hour", 20.0)
        reachable_at_high = (
            min(max_soc, soc + soc_per_hour * first_high_h)
            if first_high_h else soc
        )

        # ── Proportionele SoC-reserve: 12% per toekomstig HIGH-uur ───────────
        # Dit is de MINIMALE SoC die we willen hebben als HIGH begint.
        # Niet het laaddoel bij LOW (dat is adj_max).
        soc_reserve = (
            min(max_soc, min_soc + n_future_high * 12.0)
            if n_future_high else min_soc
        )
        # soc_target alias voor gebruik in HIGH-logica (behoud leesbaarheid)
        soc_target = soc_reserve

        # ── PV-gecorrigeerde max SoC: bewaar ruimte als morgen veel PV ────────
        pv_adjusted_max_soc = max_soc
        if pv.forecast_tomorrow_kwh > 0 and cap_kwh > 0:
            pv_space_pct = min(40.0, (pv.forecast_tomorrow_kwh / cap_kwh) * 100.0)
            pv_adjusted_max_soc = max(min_soc + 20.0, max_soc - pv_space_pct)

        # Bij LOW is het laaddoel: laad zo vol als nuttig is (adj_max), niet soc_reserve.
        # Bij HIGH is het ontlaaddoel: blijf boven soc_reserve.
        charge_target = pv_adjusted_max_soc   # maximale SoC om naartoe te laden

        # ── PV-gecorrigeerde minimale ontlaad-SoC ─────────────────────────────
        # Bewaar absorptieruimte als PV vandaag nog kWh levert
        pv_min_discharge = min_soc
        if pv.pv_kwh_next_8h > 0.5 and cap_kwh > 0:
            absorb_pct = min(30.0, (pv.pv_kwh_next_8h / cap_kwh) * 100.0)
            pv_min_discharge = min(min_soc + absorb_pct, 60.0)

        # ── Saldering-context ──────────────────────────────────────────────────
        # Haal huidig salderingspercentage op (automatisch op basis van jaar).
        # Gebruikt voor: ontlaaddrempel, spread-check bij LOW-laden, savings tracker.
        sal_ctx = SalderingContext.for_current_year(
            cycle_cost=getattr(self, "_cycle_cost_eur_kwh", 0.044)
        )
        # Bereken minimale verkoopprijs voor winstgevend ontladen.
        # Eigenverbruikfractie: schat 60% (typisch avondprofiel, batterij 3kW, huis 1.8kW)
        _sal_house_fraction = 0.6
        _sal_min_discharge_price = sal_ctx.min_discharge_price_for_profit(
            buy_price_eur_kwh   = max(0.0, price),   # huidige prijs als proxy voor laadkosten
            house_load_fraction = _sal_house_fraction,
        )

        reasons: list[str] = []

        # ══════════════════════════════════════════════════════════════════════
        # PRIORITEIT 1 — NEGATIEF TARIEF
        # ══════════════════════════════════════════════════════════════════════
        if price < 0.0:
            if soc < max_soc:
                reasons.append(f"Negatief tarief {price:.4f} €/kWh → maximaal laden")
                return DecisionResult(
                    action=ZPAction.CHARGE,
                    charge_power_w=self._charge_w,
                    confidence=1.0,
                    reasons=reasons,
                    soc_target=max_soc,
                    soc_reachable=reachable_at_high,
                )
            reasons.append(f"Negatief tarief maar SoC {soc:.0f}% al op max {max_soc:.0f}%")
            return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                  soc_target=max_soc, soc_reachable=soc)

        # ══════════════════════════════════════════════════════════════════════
        # PRIORITEIT 2 — PRIJS ONDER FLOOR (niet HIGH)
        # ══════════════════════════════════════════════════════════════════════
        if price < self._price_floor and tg != "high":
            reasons.append(
                f"Prijs {price:.4f} €/kWh < drempel {self._price_floor:.4f} → hold"
            )
            return DecisionResult(action=ZPAction.HOLD, confidence=0.8, reasons=reasons,
                                  soc_target=soc_target, soc_reachable=soc)

        # ══════════════════════════════════════════════════════════════════════
        # PRIORITEIT 3 — SOC-GRENSBESCHERMING
        # ══════════════════════════════════════════════════════════════════════
        if tg == "low" and soc >= max_soc:
            reasons.append(f"SoC {soc:.0f}% ≥ max {max_soc:.0f}% → hold")
            return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                  soc_target=max_soc, soc_reachable=soc)

        # ══════════════════════════════════════════════════════════════════════
        # TARIEFGROEP HIGH
        # ══════════════════════════════════════════════════════════════════════
        if tg == "high":
            if soc <= min_soc:
                reasons.append(
                    f"HIGH maar SoC {soc:.0f}% ≤ min {min_soc:.0f}% → hold (bescherming)"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                      soc_target=soc_target, soc_reachable=soc)

            # ── Saldering-check voor HIGH ontladen ────────────────────────────
            # Als HIGH-tarief onder de minimale winstgevende prijs valt, is
            # ontladen (deels) naar het net niet rendabel.
            # Uitzondering: als het huis veel stroom verbruikt (eigenverbruik > 80%)
            # is ontladen altijd zinvol — we besparen de volle importprijs.
            if price < _sal_min_discharge_price and pv.solar_surplus_w > 200:
                # PV dekt al het huis + we leveren toch terug → dubbelop verlies
                reasons.append(
                    f"HIGH, maar prijs €{price:.4f} < min €{_sal_min_discharge_price:.4f} "
                    f"bij {sal_ctx.saldering_pct:.0%} saldering + PV surplus → hold"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=0.8, reasons=reasons,
                                      soc_target=soc_target, soc_reachable=soc)

            # PV surplus vermindert gewenst ontlaadvermogen
            # (PV dekt al een deel van het huis, batterij hoeft minder te doen)
            net_discharge_w = max(500.0, self._discharge_w - pv.solar_surplus_w * 0.5)

            # Saldering-annotatie voor logboek
            sal_note = (
                f" [sal {sal_ctx.saldering_pct:.0%}, min €{_sal_min_discharge_price:.3f}/kWh]"
                if sal_ctx.saldering_pct < 1.0 else ""
            )

            if n_future_high == 0:
                # Laatste HIGH-blok — ontlaad naar PV-gecorrigeerde bodem
                eff_min = max(min_soc, pv_min_discharge * 0.5)  # minder terughoudend bij HIGH
                reasons.append(
                    f"HIGH, geen toekomstige HIGH → ontladen naar {eff_min:.0f}%"
                    + (f" (PV surplus {pv.solar_surplus_w:.0f}W → {net_discharge_w:.0f}W)"
                       if pv.solar_surplus_w > 100 else "")
                    + sal_note
                )
                return DecisionResult(
                    action=ZPAction.DISCHARGE,
                    discharge_power_w=round(net_discharge_w),
                    bypass_antiround=True,
                    confidence=0.95,
                    reasons=reasons,
                    soc_target=eff_min,
                    soc_reachable=soc,
                )
            else:
                # Toekomstige HIGH-uren → proportionele reserve
                if soc > soc_target:
                    # Ontlaadvermogen evenredig met overschot boven target
                    fraction = min(1.0, (soc - soc_target) / 20.0)
                    disch_w  = max(500.0, round(self._discharge_w * fraction))
                    reasons.append(
                        f"HIGH, {n_future_high} toekomstige HIGH-uren, "
                        f"reserve {soc_target:.0f}%, SoC {soc:.0f}% > target → "
                        f"ontladen {disch_w:.0f}W{sal_note}"
                    )
                    return DecisionResult(
                        action=ZPAction.DISCHARGE,
                        discharge_power_w=disch_w,
                        bypass_antiround=True,
                        confidence=0.85,
                        reasons=reasons,
                        soc_target=soc_target,
                        soc_reachable=soc,
                    )
                else:
                    reasons.append(
                        f"HIGH, {n_future_high} toekomstige HIGH-uren, "
                        f"SoC {soc:.0f}% ≤ reserve {soc_target:.0f}% → hold"
                    )
                    return DecisionResult(action=ZPAction.HOLD, confidence=0.9,
                                          reasons=reasons, soc_target=soc_target,
                                          soc_reachable=soc)

        # ══════════════════════════════════════════════════════════════════════
        # TARIEFGROEP LOW
        # ══════════════════════════════════════════════════════════════════════
        elif tg == "low":
            if first_high_h is None:
                # Geen HIGH in forecast
                if pv.pv_kwh_next_8h > 0.5:
                    reasons.append(
                        f"LOW, geen HIGH in forecast, {pv.pv_kwh_next_8h:.1f} kWh PV "
                        f"verwacht → bewaar ruimte voor gratis PV"
                    )
                    return DecisionResult(action=ZPAction.HOLD, confidence=0.85,
                                          reasons=reasons, soc_target=soc_target,
                                          soc_reachable=soc)
                reasons.append("LOW, geen HIGH in forecast, geen PV verwacht → hold")
                return DecisionResult(action=ZPAction.HOLD, confidence=0.7,
                                      reasons=reasons, soc_target=soc_target,
                                      soc_reachable=soc)

            # HIGH komt eraan — laad naar charge_target (PV-gecorrigeerde max SoC)

            # PV dekt laden al dit uur → netladen overbodig
            if pv.pv_covers_charge:
                reasons.append(
                    f"LOW, HIGH in {first_high_h}u, maar PV dekt laden al "
                    f"(piek {pv.pv_peak_next_8h_w:.0f}W dit uur) → wacht op gratis PV"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=0.9,
                                      reasons=reasons, soc_target=charge_target,
                                      soc_reachable=reachable_at_high)

            gap = charge_target - soc

            if gap <= 2:
                reasons.append(
                    f"LOW, SoC {soc:.0f}% ≈ laaddoel {charge_target:.0f}% → hold"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=0.85,
                                      reasons=reasons, soc_target=charge_target,
                                      soc_reachable=soc)

            # Laadvermogen schalen naar urgentie
            urgency  = max(0.3, 1.0 - (first_high_h - 1) / 6.0)
            charge_w = max(500.0, round(self._charge_w * urgency))

            note = ""
            if pv.forecast_tomorrow_kwh > cap_kwh * 0.3:
                note = (f", PV morgen {pv.forecast_tomorrow_kwh:.1f} kWh → "
                        f"max SoC beperkt tot {charge_target:.0f}%")

            reasons.append(
                f"LOW, HIGH in {first_high_h}u, gap {gap:.0f}% → "
                f"laden {charge_w:.0f}W (urgentie {urgency:.0%}){note}"
            )

            return DecisionResult(
                action=ZPAction.CHARGE,
                charge_power_w=charge_w,
                confidence=urgency,
                reasons=reasons,
                soc_target=charge_target,
                soc_reachable=reachable_at_high,
            )

        # ══════════════════════════════════════════════════════════════════════
        # TARIEFGROEP NORMAL
        # ══════════════════════════════════════════════════════════════════════
        elif tg == "normal":
            # HIGH nadert snel en SoC te laag voor minimale reserve + veiligheidsruimte
            if first_high_h is not None and first_high_h <= 3:
                gap = soc_target - soc   # hoeveel zit SoC ONDER de minimale reserve?
                # Laden als SoC onder reserve én PV dekt het niet
                # Threshold: 10% (niet 15%) zodat ook lage SoC's worden opgepikt
                if gap > 10 and not pv.pv_covers_charge:
                    urgency  = max(0.4, 1.0 - (first_high_h - 1) / 3.0)
                    charge_w = max(500.0, round(self._charge_w * urgency))
                    reasons.append(
                        f"NORMAL, HIGH in {first_high_h}u, SoC {soc:.0f}% < "
                        f"reserve {soc_target:.0f}% (gap {gap:.0f}%) → "
                        f"bijladen {charge_w:.0f}W (urgentie {urgency:.0%})"
                    )
                    return DecisionResult(
                        action=ZPAction.CHARGE,
                        charge_power_w=charge_w,
                        confidence=0.75,
                        reasons=reasons,
                        soc_target=soc_target,
                        soc_reachable=reachable_at_high,
                    )

            # LOW nadert en ruimte bijna vol → ontlaad om ruimte te maken
            if first_low_h is not None and first_low_h <= 2:
                headroom = max_soc - soc
                if headroom < 15 and soc > min_soc + 10:
                    reasons.append(
                        f"NORMAL, LOW in {first_low_h}u, ruimte slechts {headroom:.0f}% → "
                        f"ontladen om ruimte te maken voor goedkope stroom"
                    )
                    return DecisionResult(
                        action=ZPAction.DISCHARGE,
                        discharge_power_w=round(self._discharge_w * 0.5),
                        bypass_antiround=False,
                        confidence=0.7,
                        reasons=reasons,
                        soc_target=max_soc - 20.0,
                        soc_reachable=soc,
                    )

            # PV surplus nu → hold, PV doet het werk
            if pv.solar_surplus_w > 200:
                reasons.append(
                    f"NORMAL, PV surplus {pv.solar_surplus_w:.0f}W → "
                    f"laat PV de batterij opladen"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=0.8,
                                      reasons=reasons, soc_target=soc_target,
                                      soc_reachable=soc)

            # ── Anticiperend ontladen: ruimte maken voor verwachte PV ─────────
            # Als de batterij (bijna) vol is EN er zijn morgen/komende uren veel PV
            # verwacht, is het slim om nu alvast te ontladen zodat er absorptieruimte
            # is voor gratis zonne-energie — ook als het tarief NORMAL is.
            #
            # Activatievoorwaarden:
            #   1. SoC > 85% (batterij bijna vol)
            #   2. PV verwacht komende 8u > 30% van batterijcapaciteit (cap_kwh)
            #      OF morgen > 50% van capaciteit verwacht
            #   3. Geen actieve PV-surplus nu (anders doet PV het zelf)
            #   4. Ontladen is rendabel bij huidige prijs (saldering-check)
            _high_pv_expected = (
                pv.pv_kwh_next_8h > cap_kwh * 0.30
                or pv.forecast_tomorrow_kwh > cap_kwh * 0.50
            )
            _battery_nearly_full = soc > 85.0
            _no_surplus_now = pv.solar_surplus_w < 100
            _discharge_profitable = price >= _sal_min_discharge_price

            if (_battery_nearly_full and _high_pv_expected and
                    _no_surplus_now and _discharge_profitable and
                    soc > min_soc + 20.0):
                # Hoeveel ruimte moeten we maken?
                # Doel: zet SoC terug naar (max_soc - verwachte PV als % van cap)
                _pv_as_pct = min(40.0, (pv.pv_kwh_next_8h / max(cap_kwh, 1.0)) * 100.0)
                _target_soc = max(min_soc + 20.0, max_soc - _pv_as_pct)
                _gap = soc - _target_soc

                if _gap > 5.0:
                    # Ontlaad langzaam (50% vermogen) om ruimte te maken
                    _anticipate_w = round(self._discharge_w * 0.50)
                    reasons.append(
                        f"NORMAL, batterij {soc:.0f}% + PV {pv.pv_kwh_next_8h:.1f}kWh "
                        f"verwacht → anticiperend ontladen naar {_target_soc:.0f}% "
                        f"({_anticipate_w:.0f}W)"
                    )
                    return DecisionResult(
                        action=ZPAction.DISCHARGE,
                        discharge_power_w=_anticipate_w,
                        bypass_antiround=False,
                        confidence=0.65,
                        reasons=reasons,
                        soc_target=_target_soc,
                        soc_reachable=soc,
                    )

            reasons.append("NORMAL, geen duidelijke kans → Powerplay")
            return DecisionResult(action=ZPAction.POWERPLAY, confidence=0.6,
                                  reasons=reasons, soc_target=soc_target,
                                  soc_reachable=soc)

        # Fallback
        reasons.append(f"Onbekende tariefgroep '{tg}' → Powerplay")
        return DecisionResult(action=ZPAction.POWERPLAY, confidence=0.5,
                              reasons=reasons, soc_target=soc_target,
                              soc_reachable=soc)

    # ── Backwards-compat alias ─────────────────────────────────────────────────

    def decide_action(self) -> ZPAction:
        """Backwards-compatibel wrapper → decide_action_v3() zonder PV-context."""
        return self.decide_action_v3().action

    # ── Forecast samenvatting voor dashboard ──────────────────────────────────

    def get_forecast_summary(self) -> dict:
        """Samenvatting van forecast + laatste beslissing — voor dashboard."""
        raw      = self._last_state.raw
        forecast = raw.get("forecast_tariff_groups", [])
        result   = self.decide_action_v3()
        # Sla op voor tijdstempel weergave in dashboard
        import time as _t
        self._last_decision_ts     = _t.time()
        self._last_decision_result = result

        # Tijdstempel leesbaar maken
        import datetime as _dt
        _ts_str = _dt.datetime.fromtimestamp(self._last_decision_ts).strftime("%H:%M:%S")

        # Alle redenen samenvoegen
        all_reasons = result.reasons if result.reasons else ["Geen specifieke reden — standaard beleid"]

        return {
            "current_tariff":    raw.get("tariff_group", "unknown"),
            "current_price_eur": raw.get("electricity_tariff_eur"),
            "forecast_8h":       forecast,
            "high_hours":        forecast.count("high"),
            "low_hours":         forecast.count("low"),
            "normal_hours":      forecast.count("normal"),
            "recommended_action":result.action.value,
            "action_confidence": round(result.confidence, 2),
            "action_reasons":    all_reasons,
            "action_reasons_all": all_reasons,
            "decision_time":     _ts_str,
            "soc_target":        round(result.soc_target, 1),
            "soc_reachable":     round(result.soc_reachable, 1),
        }


    # ── Anti-rondpompen checks ─────────────────────────────────────────────────

    def _house_load_ok(self) -> bool:
        """Controleer of huisverbruik boven drempel is (anti-rondpompen)."""
        sensor = self._house_sensor
        if not sensor:
            return True  # geen sensor geconfigureerd → geen blokkade
        st = self._hass.states.get(sensor)
        if not st or st.state in ("unavailable", "unknown", ""):
            return True
        try:
            raw_val = float(st.state)
            unit = (st.attributes.get("unit_of_measurement") or "").lower()
            # kW → W normalisatie (zoals blueprint)
            if unit == "kw" or (unit != "w" and raw_val < 50):
                raw_val = raw_val * 1000.0
            # Export (negatief) → 0
            pwr_w = max(raw_val, 0.0)
            result = pwr_w >= self._min_house_w
            if not result:
                _LOGGER.debug(
                    "ZonneplanProvider anti-rondpomp: huislast %.0fW < drempel %.0fW",
                    pwr_w, self._min_house_w,
                )
            return result
        except Exception:
            return True

    def _ev_blocking(self) -> bool:
        """Controleer of EV actief laadt boven drempel (EV-blokker)."""
        sensor = self._ev_sensor
        if not sensor:
            return False
        st = self._hass.states.get(sensor)
        if not st or st.state in ("unavailable", "unknown", ""):
            return False
        try:
            raw_val = float(st.state)
            unit = (st.attributes.get("unit_of_measurement") or "").lower()
            if unit == "kw" or (unit != "w" and raw_val < 50):
                raw_val = raw_val * 1000.0
            blocking = raw_val >= self._ev_block_w
            if blocking:
                _LOGGER.debug(
                    "ZonneplanProvider EV-blokker actief: EV %.0fW >= drempel %.0fW",
                    raw_val, self._ev_block_w,
                )
            return blocking
        except Exception:
            return False

    # ── Sturing ────────────────────────────────────────────────────────────────

    async def async_set_charge(self, power_w: Optional[float] = None) -> bool:
        if not self.is_available: return False
        soc = self._last_state.soc_pct
        if soc is not None and soc >= self._max_soc:
            _LOGGER.debug("ZonneplanProvider: laden overgeslagen (SoC %.0f%% >= max %.0f%%)",
                          soc, self._max_soc)
            return False
        w = power_w or self._charge_w
        if self._entities.get("control_mode"):
            return await self._set_home_optimization(solar_w=w)
        return await self._legacy_set(ZPManualState.CHARGE)

    async def async_set_discharge(self, power_w: Optional[float] = None,
                                  bypass_antiround: bool = False) -> bool:
        """
        Ontlaad — met anti-rondpompen en EV-blokker checks.
        bypass_antiround=True: sla anti-rondpomp over (bijv. bij HIGH tarief).
        """
        if not self.is_available: return False
        soc = self._last_state.soc_pct
        if soc is not None and soc <= self._min_soc:
            _LOGGER.debug("ZonneplanProvider: ontladen overgeslagen (SoC %.0f%% <= min %.0f%%)",
                          soc, self._min_soc)
            return False
        # EV-blokker altijd (ook bij HIGH)
        if self._ev_blocking():
            _LOGGER.info("ZonneplanProvider: ontladen geblokkeerd door EV-lader")
            return False
        # Anti-rondpomp — alleen bij NORMAL/LOW
        if not bypass_antiround and not self._house_load_ok():
            _LOGGER.info("ZonneplanProvider: ontladen geblokkeerd door anti-rondpomp")
            return False
        w = power_w or self._discharge_w
        if self._entities.get("control_mode"):
            return await self._set_home_optimization(deliver_w=w)
        return await self._legacy_set(ZPManualState.DISCHARGE)

    async def async_set_auto(self) -> bool:
        """Herstel automatisch beheer (opgeslagen modus of Powerplay)."""
        if self._entities.get("control_mode"):
            target = self._saved_mode or ZPControlMode.POWERPLAY.value
            await self._send_control_mode(target)

        mc_eid = self._entities.get("manual_control")
        if mc_eid and self._last_state.raw.get("manual_control"):
            await self._hass.services.async_call(
                "switch", "turn_off", {"entity_id": mc_eid}, blocking=False
            )

        self._override_since   = 0.0
        self._saved_mode       = None
        self._last_sent_mode   = None
        await self._async_save()
        _LOGGER.info("ZonneplanProvider: → AUTO")
        return True

    async def async_set_mode(self, mode: str, **kwargs) -> bool:
        if not self.is_available: return False
        if mode == "home_optimization":
            return await self._set_home_optimization(
                deliver_w = kwargs.get("deliver_to_home_w"),
                solar_w   = kwargs.get("solar_charge_w"),
            )
        if mode == "self_consumption":
            return await self._send_control_mode(ZPControlMode.SELF_CONSUMPTION.value)
        if mode == "powerplay":
            return await self.async_set_auto()
        return await self._send_control_mode(mode)

    async def async_apply_forecast_decision_v3(
        self,
        solar_now_w:             float = 0.0,
        solar_surplus_w:         float = 0.0,
        pv_forecast_today_kwh:   float = 0.0,
        pv_forecast_tomorrow_kwh:float = 0.0,
        pv_forecast_hourly:      list  = None,
        battery_capacity_kwh:    float = 10.0,
        soh_pct:                 float = 100.0,
    ) -> DecisionResult:
        """
        Voer decide_action_v3() uit met volledige PV-context en stuur de batterij aan.
        Aangeroepen vanuit de coordinator update-loop als zonneplan_auto_forecast=True.

        Combineert alle beschikbare signalen — zie decide_action_v3() docstring.
        Gebruikt DecisionResult.charge_power_w / discharge_power_w voor vermogen.
        HIGH: bypass_antiround=True (ontladen naar net is gewenst bij HIGH tarief).
        """
        if not self.is_available:
            return DecisionResult(
                action=ZPAction.HOLD,
                reasons=["Provider niet beschikbaar of uitgeschakeld"],
            )

        pv = self._build_pv_context(
            solar_now_w             = solar_now_w,
            solar_surplus_w         = solar_surplus_w,
            pv_forecast_today_kwh   = pv_forecast_today_kwh,
            pv_forecast_tomorrow_kwh= pv_forecast_tomorrow_kwh,
            pv_forecast_hourly      = pv_forecast_hourly,
            battery_capacity_kwh    = battery_capacity_kwh,
        )

        result = self.decide_action_v3(pv=pv, battery_capacity_kwh=battery_capacity_kwh,
                                       soh_pct=soh_pct)

        _LOGGER.info(
            "ZonneplanProvider v3: %s (SoC=%.0f%%, tarief=%s, PV-nu=%.0fW, "
            "PV-8h=%.1fkWh, conf=%.0f%%) — %s",
            result.action.value,
            self._last_state.soc_pct or 0,
            self._last_state.raw.get("tariff_group", "?"),
            solar_now_w,
            pv.pv_kwh_next_8h,
            result.confidence * 100,
            " | ".join(result.reasons[:2]),   # eerste 2 redenen in log
        )

        if result.action == ZPAction.CHARGE:
            await self.async_set_charge(power_w=result.charge_power_w)

        elif result.action == ZPAction.DISCHARGE:
            await self.async_set_discharge(
                power_w=result.discharge_power_w,
                bypass_antiround=result.bypass_antiround,
            )

        elif result.action == ZPAction.HOLD:
            if self._last_state.active_mode != ZPControlMode.HOME_OPTIMIZATION.value:
                await self._send_control_mode(ZPControlMode.HOME_OPTIMIZATION.value)

        # POWERPLAY: niets doen, Zonneplan AI bepaalt

        # ── PV-surplus slider optimalisatie met hysterese ──────────────────────────
        # Drempels: hoog-in = 700W surplus aanhoudend ≥ 60s, laag-uit = < 300W voor ≥ 120s
        # Dit voorkomt dat de slider elke 10s heen en weer schuift bij schommelend surplus.
        if self._entities.get("deliver_to_home") and self._entities.get("control_mode"):
            import time as _time_hyst
            _soc_now = self._last_state.soc_pct or 0.0
            _surplus = pv.solar_surplus_w if pv else 0.0
            _current_mode = self._last_state.active_mode or ""
            _is_home_opt = ("home_optimization" in _current_mode or
                            "thuisoptimalisatie" in _current_mode.lower())
            _now_ts = _time_hyst.time()

            # Hoog-in drempel: surplus > 700W EN batterij vol
            _surplus_high_condition = (_soc_now >= self._max_soc - 5.0 and _surplus > 700)
            # Laag-uit drempel: surplus < 300W OF batterij niet vol
            _surplus_low_condition  = (_surplus < 300 or _soc_now < self._max_soc - 15.0)

            if _surplus_high_condition:
                if self._surplus_high_since == 0.0:
                    self._surplus_high_since = _now_ts
                # Activeer pas na 60s aanhoudend surplus (debounce)
                if (not self._surplus_slider_high and
                        _is_home_opt and
                        (_now_ts - self._surplus_high_since) >= 60.0):
                    _optimal_deliver_w = max(800.0, min(self._discharge_w, _surplus * 0.85))
                    _LOGGER.info(
                        "ZonneplanProvider surplus-modus: deliver_to_home → %.0fW "
                        "(surplus %.0fW, SoC %.0f%%, 60s bevestigd)",
                        _optimal_deliver_w, _surplus, _soc_now,
                    )
                    await self._set_slider_idempotent(
                        "deliver_to_home", _optimal_deliver_w, self._last_sent_deliver_w
                    )
                    self._last_sent_deliver_w = _optimal_deliver_w
                    self._surplus_slider_high = True
            else:
                self._surplus_high_since = 0.0

            if _surplus_low_condition and self._surplus_slider_high:
                if not hasattr(self, "_surplus_low_since"):
                    self._surplus_low_since = _now_ts
                # Deactiveer pas na 120s geen surplus (debounce terugzetten)
                if (_now_ts - getattr(self, "_surplus_low_since", _now_ts)) >= 120.0:
                    _default_deliver_w = 600.0
                    _LOGGER.info(
                        "ZonneplanProvider surplus weg (120s): deliver_to_home → %.0fW",
                        _default_deliver_w,
                    )
                    await self._set_slider_idempotent(
                        "deliver_to_home", _default_deliver_w, self._last_sent_deliver_w
                    )
                    self._last_sent_deliver_w = _default_deliver_w
                    self._surplus_slider_high  = False
                    self._surplus_low_since    = 0.0
            elif not _surplus_low_condition:
                self._surplus_low_since = 0.0

        await self.async_maybe_restore()
        return result

    async def async_apply_forecast_decision(self) -> ZPAction:
        """Backwards-compat wrapper → async_apply_forecast_decision_v3() zonder PV."""
        result = await self.async_apply_forecast_decision_v3()
        return result.action


    async def async_maybe_restore(self) -> None:
        if not self.is_available or not self._restore_mode or self._restore_min <= 0:
            return
        if self._override_since <= 0:
            return
        elapsed = (time.time() - self._override_since) / 60.0
        if elapsed >= self._restore_min:
            _LOGGER.info("ZonneplanProvider: auto-restore na %.0f min", elapsed)
            await self.async_set_auto()

    async def async_force_slider_calibrate(self) -> dict:
        """Bereken en schrijf optimale sliderwaarden op basis van huidige situatie.

        Negeert hysterese en debounce — bedoeld voor handmatige kalibratie/test.
        Retourneert een dict met de gekozen waarden en de reden.
        """
        soc      = self._last_state.soc_pct or 0.0
        pv       = self._build_pv_context()
        surplus  = pv.solar_surplus_w if pv else 0.0
        max_soc  = self._max_soc

        # ── deliver_to_home ────────────────────────────────────────────────────
        if surplus > 700 and soc >= max_soc - 5.0:
            # Batterij bijna vol + veel surplus → verhoog levering aan huis
            deliver_w = max(800.0, min(self._discharge_w, surplus * 0.85))
            deliver_reason = f"surplus {surplus:.0f}W, SoC {soc:.0f}% ≥ {max_soc-5:.0f}%"
        elif surplus > 300:
            # Matig surplus → proportieel
            deliver_w = max(600.0, surplus * 0.6)
            deliver_reason = f"matig surplus {surplus:.0f}W"
        else:
            # Weinig/geen surplus → conservatief
            deliver_w = 600.0
            deliver_reason = f"laag surplus {surplus:.0f}W → standaard"

        # ── solar_charge ───────────────────────────────────────────────────────
        if soc >= max_soc - 2.0:
            # Bijna vol → stop zonneladen
            solar_w = 0.0
            solar_reason = f"SoC {soc:.0f}% bijna vol ({max_soc:.0f}%)"
        elif surplus > 500:
            # Veel surplus → laad maximaal
            solar_w = min(surplus * 0.9, self._discharge_w)
            solar_reason = f"surplus {surplus:.0f}W → maximaal laden"
        elif surplus > 100:
            # Beetje surplus → laad proportioneel
            solar_w = surplus * 0.7
            solar_reason = f"klein surplus {surplus:.0f}W"
        else:
            solar_w = 400.0
            solar_reason = "geen surplus → minimaal zonneladen"

        deliver_w = round(deliver_w)
        solar_w   = round(solar_w)

        # Schrijf direct — negeer idempotent-check door last_sent op None te zetten
        self._last_sent_deliver_w = None
        self._last_sent_solar_w   = None

        has_deliver = bool(self._entities.get("deliver_to_home"))
        has_solar   = bool(self._entities.get("solar_charge"))

        if has_deliver:
            await self._set_slider_idempotent("deliver_to_home", deliver_w, None)
            self._last_sent_deliver_w = float(deliver_w)
        if has_solar:
            await self._set_slider_idempotent("solar_charge", solar_w, None)
            self._last_sent_solar_w = float(solar_w)

        # Reset hysterese-flags zodat normale logica daarna weer correct werkt
        self._surplus_slider_high = (surplus > 700 and soc >= max_soc - 5.0)

        result = {
            "deliver_to_home_w": deliver_w if has_deliver else None,
            "deliver_reason":    deliver_reason,
            "solar_charge_w":    solar_w   if has_solar   else None,
            "solar_reason":      solar_reason,
            "soc_pct":           soc,
            "surplus_w":         surplus,
            "has_deliver":       has_deliver,
            "has_solar":         has_solar,
        }
        _LOGGER.info(
            "ZonneplanProvider kalibratie: deliver_to_home=%sW (%s), solar_charge=%sW (%s)",
            deliver_w if has_deliver else "n/a", deliver_reason,
            solar_w   if has_solar   else "n/a", solar_reason,
        )
        return result

    def get_available_modes(self) -> list[dict]:
        return _AVAILABLE_MODES

    # ── Wizard hint ────────────────────────────────────────────────────────────

    def get_wizard_hint(self) -> ProviderWizardHint:
        configured  = self.is_enabled
        detected    = self.is_detected
        has_sliders = ("deliver_to_home" in self._entities or "solar_charge" in self._entities)
        has_forecast= "tariff_group"    in self._entities
        ent_count   = len(self._entities)

        config_fields = [
            {
                "key":     "zonneplan_enabled",
                "label":   "Zonneplan Nexus sturing inschakelen",
                "type":    "bool",
                "default": False,
                "description": "Laat CloudEMS de Zonneplan Nexus batterij aansturen.",
            },
            {
                "key":     "zonneplan_restore_mode",
                "label":   "Automatisch terugzetten naar vorige modus",
                "type":    "bool",
                "default": True,
            },
            {
                "key":     "zonneplan_restore_after_min",
                "label":   "Hersteltijd (minuten, 0 = nooit)",
                "type":    "int",
                "default": 60,
                "min":     0,
                "max":     1440,
            },
            {
                "key":     "zonneplan_min_soc",
                "label":   "Minimale SoC voor ontladen (%)",
                "type":    "float",
                "default": 10.0,
                "min":     0,
                "max":     50,
            },
            {
                "key":     "zonneplan_max_soc",
                "label":   "Maximale SoC voor laden (%)",
                "type":    "float",
                "default": 95.0,
                "min":     50,
                "max":     100,
            },
            {
                "key":     "zonneplan_soc_reserve_high",
                "label":   "SoC-reserve bij meerdere HIGH-uren (%)",
                "type":    "float",
                "default": 30.0,
                "min":     0,
                "max":     80,
            },
            {
                "key":     "zonneplan_min_house_load_w",
                "label":   "Min. huisverbruik voor ontladen (W, anti-rondpomp)",
                "type":    "float",
                "default": 300.0,
                "min":     0,
                "max":     5000,
            },
            {
                "key":     "zonneplan_ev_block_w",
                "label":   "EV-blokker drempel (W, 0 = uitgeschakeld)",
                "type":    "float",
                "default": 1000.0,
                "min":     0,
                "max":     22000,
            },
            {
                "key":     "zonneplan_auto_forecast",
                "label":   "Auto-forecast: CloudEMS stuurt automatisch op tariefgroep",
                "type":    "bool",
                "default": False,
                "description": (
                    "Als ingeschakeld beslist CloudEMS elk coordinator-interval op basis van "
                    "de tariefgroep-forecast of de batterij moet laden, ontladen of standby staan. "
                    "Schakel UIT als je Zonneplan Powerplay zelf wil gebruiken."
                ),
            },
        ]

        desc_parts = [
            f"De Zonneplan ONE integratie is gevonden met {ent_count} entiteiten.",
        ]
        if has_sliders:
            desc_parts.append("De Batterijbesturingsmodus select én vermogenssliders zijn beschikbaar (Pad A).")
        if has_forecast:
            desc_parts.append("Tariefgroep-forecast (8 uur) beschikbaar voor slimme laad/ontlaad-beslissingen.")
        if not configured:
            desc_parts.append("CloudEMS kan de modus automatisch aansturen op basis van tariefgroep en forecast.")
        else:
            desc_parts.append("CloudEMS beheert al deze batterij.")

        return ProviderWizardHint(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            detected       = detected,
            configured     = configured,
            icon           = self.PROVIDER_ICON,
            title          = "Zonneplan Nexus thuisbatterij gedetecteerd",
            description    = " ".join(desc_parts),
            warning        = (
                "" if configured else
                "Zonneplan Nexus gedetecteerd maar nog niet geconfigureerd in CloudEMS"
            ),
            suggestion     = (
                "" if configured else
                "Wil je dat CloudEMS de Nexus aanstuurt op basis van tariefgroep-forecast? We doorlopen dit nu samen."
            ),
            config_fields  = config_fields,
        )

    # ── Info voor dashboard ───────────────────────────────────────────────────

    def get_setup_warnings(self) -> list[dict]:
        """Provider-specifieke waarschuwingen: disabled power sensor, ontbrekende tariefgroep."""
        warnings: list[dict] = []
        if not self._detected:
            return warnings
        # Check: is de power sensor aanwezig maar disabled in HA?
        power_eid = self._entities.get("power")
        if power_eid:
            try:
                from homeassistant.helpers import entity_registry as er
                reg = er.async_get(self._hass)
                entry = reg.async_get(power_eid)
                if entry and entry.disabled_by:
                    warnings.append({
                        "type":     "entity_disabled",
                        "severity": "warning",
                        "provider": self.PROVIDER_ID,
                        "entity":   power_eid,
                        "message":  (
                            f"Batterijvermogen sensor ({power_eid}) is uitgeschakeld. "
                            f"Schakel hem in via Instellingen → Integraties → Zonneplan → "
                            f"Entiteiten → Vermogen → Inschakelen."
                        ),
                        "action":   "enable_entity",
                    })
            except Exception:
                pass
        # Check: tariff_group niet gevonden maar provider wel actief
        if self._enabled and "tariff_group" not in self._entities:
            warnings.append({
                "type":     "missing_tariff",
                "severity": "info",
                "provider": self.PROVIDER_ID,
                "message":  (
                    "Tariefgroep sensor niet gevonden. Tariefgestuurde EPEX-beslissingen "
                    "zijn beperkt. Zorg dat sensor.zonneplan_current_tariff_group "
                    "of vergelijkbaar beschikbaar is."
                ),
                "action":   "check_integration",
            })
        return warnings

    def get_info(self) -> dict:
        """Info voor dashboard — entities, sliders, modus, tariefgroep."""
        base = super().get_info()

        def _sv(key) -> str | None:
            eid = self._entities.get(key)
            if not eid: return None
            st = self._hass.states.get(eid)
            if not st or st.state in ("unavailable","unknown","none",""): return None
            return st.state

        def _fv(key) -> float | None:
            v = _sv(key)
            try: return round(float(v), 2) if v else None
            except: return None

        base.update({
            "entities_mapped":    list(self._entities.keys()),
            "has_control_mode":   "control_mode"   in self._entities,
            "has_sliders":        ("deliver_to_home" in self._entities or "solar_charge" in self._entities),
            "has_max_sliders":    "max_charge_home" in self._entities,
            "has_legacy":         "manual_control"  in self._entities,
            "has_forecast":       "tariff_group"    in self._entities,
            "override_since_min": round((time.time() - self._override_since) / 60, 1)
                                  if self._override_since > 0 else None,
            "saved_mode":         self._saved_mode,
            "available_modes":    _AVAILABLE_MODES,
            "forecast":           self.get_forecast_summary(),
            "state":              self._last_state.to_dict(),
            "anti_roundpump": {
                "house_sensor":    self._house_sensor,
                "min_house_load_w":self._min_house_w,
                "ev_sensor":       self._ev_sensor,
                "ev_block_w":      self._ev_block_w,
            },
            "auto_forecast_enabled": getattr(self, "_auto_forecast_enabled", False),
            "last_slider_write_min": round((time.time() - self._last_slider_write) / 60, 1)
                                     if self._last_slider_write > 0 else None,
            "pv_integration": {
                "soc_per_hour":          getattr(self, "_soc_per_hour", 20.0),
                "battery_capacity_kwh":  getattr(self, "_battery_capacity_kwh", 10.0),
            },
            # v4.1: opbrengsten & productie rechtstreeks uit Zonneplan ONE entiteiten
            "production_today_kwh":  _fv("production_today"),
            "revenue_today_eur":     _fv("revenue_today"),
            "revenue_month_eur":     _fv("revenue_month"),
            "revenue_year_eur":      _fv("revenue_year"),
            "revenue_prev_month_eur":_fv("revenue_prev_month"),
            "revenue_prev_year_eur": _fv("revenue_prev_year"),
            "revenue_total_eur":     _fv("revenue_total"),
            "energy_weekly_kwh":     _fv("energy_weekly"),
            "powerplay_active":      _sv("powerplay_active"),
            "inverter_status":       _sv("inverter_status"),
            # Update-interval info
            "update_interval_s":     10,   # coordinator-cyclus (vast: 10s)
            "idempotent":            True, # slider wordt alleen gezet als waarde verandert
        })
        return base


    # ── Interne helpers ────────────────────────────────────────────────────────

    async def _send_control_mode(self, mode_val: str) -> bool:
        """Stuur select.control_mode — IDEMPOTENT: geen call als al hetzelfde."""
        eid = self._entities.get("control_mode")
        if not eid: return False

        # Idempotentie: check huidige staat
        current = self._last_state.active_mode
        if current == mode_val and self._last_sent_mode == mode_val:
            _LOGGER.debug("ZonneplanProvider: mode al %s, geen call", mode_val)
            return True

        await self._save_current_mode()
        try:
            await self._hass.services.async_call(
                "select", "select_option",
                {"entity_id": eid, "option": mode_val},
                blocking=False,
            )
            self._last_sent_mode = mode_val
            await self._async_save()
            return True
        except Exception as exc:
            _LOGGER.error("ZonneplanProvider _send_control_mode fout: %s", exc)
            return False

    async def _set_home_optimization(self,
                                     deliver_w: Optional[float] = None,
                                     solar_w:   Optional[float] = None) -> bool:
        ok = await self._send_control_mode(ZPControlMode.HOME_OPTIMIZATION.value)
        if ok:
            if deliver_w is not None:
                await self._set_slider_idempotent(
                    "deliver_to_home", deliver_w, self._last_sent_deliver_w
                )
                self._last_sent_deliver_w = deliver_w
            if solar_w is not None:
                await self._set_slider_idempotent(
                    "solar_charge", solar_w, self._last_sent_solar_w
                )
                self._last_sent_solar_w = solar_w
        return ok

    async def _set_slider_idempotent(self, key: str, value_w: float,
                                      last_sent: Optional[float]) -> None:
        """Stel slider in — sla over als waarde al gelijk is (idempotent)."""
        eid = self._entities.get(key)
        if not eid: return
        # Check huidige staat
        current_raw = self._last_state.raw.get(f"{key.replace('_', '_')}_w") or                       self._last_state.raw.get(key)
        if last_sent == round(value_w, 0):
            _LOGGER.debug("ZonneplanProvider: slider %s al %.0fW, geen call", key, value_w)
            return
        try:
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": eid, "value": round(value_w, 0)},
                blocking=False,
            )
            self._last_slider_write = time.time()
        except Exception as exc:
            _LOGGER.debug("ZonneplanProvider slider %s fout: %s", key, exc)

    async def _legacy_set(self, state: ZPManualState) -> bool:
        mc_eid  = self._entities.get("manual_control")
        sel_eid = self._entities.get("manual_state")
        if not mc_eid: return False
        await self._save_current_mode()
        try:
            await self._hass.services.async_call(
                "switch", "turn_on", {"entity_id": mc_eid}, blocking=False
            )
            if sel_eid:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": sel_eid, "option": state.value},
                    blocking=False,
                )
            return True
        except Exception as exc:
            _LOGGER.error("ZonneplanProvider legacy_set fout: %s", exc)
            return False

    async def _save_current_mode(self) -> None:
        if self._saved_mode is None:
            self._saved_mode = (self._last_state.active_mode or
                                ZPControlMode.POWERPLAY.value)
        if self._override_since <= 0:
            self._override_since = time.time()
            await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save({
            "override_since": self._override_since,
            "saved_mode":     self._saved_mode,
            "last_sent_mode": self._last_sent_mode,
        })


# ── Registreer bij import ─────────────────────────────────────────────────────
BatteryProviderRegistry.register_provider(ZonneplanProvider)
