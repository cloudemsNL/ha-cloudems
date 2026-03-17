# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

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
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .battery_cycle_economics import BatteryCycleEconomics
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
    human_reason:      str   = ""              # begrijpelijke omschrijving voor UI
    executed:          Optional[str] = None    # modus die daadwerkelijk gestuurd is


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
        # Handmatige override: als gebruiker zelf een modus kiest, respecteer dat X minuten
        self._manual_override_until: float    = 0.0   # unix ts tot wanneer CloudEMS wacht
        self._manual_override_mode:  str      = ""    # welke modus de gebruiker koos
        # Configuratie-parameters
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
        self._startup_send_done:   bool            = False
        self._last_expected_action: str             = ""
        self._last_action_ts:       float           = 0.0
        self._last_battery_w_at_cmd: float          = 0.0
        self._last_sent_deliver_w: Optional[float] = None
        self._last_sent_solar_w:   Optional[float] = None
        # Slider maxima direct uit HA entiteit-attributen ('max' attribuut van number entity)
        self._slider_max_deliver_w: float = 10000.0  # wordt bijgewerkt via _read_slider_maxima()
        self._slider_max_solar_w:   float = 10000.0
        self._slider_max_dirty:     bool  = False
        # Prijsinformatie (all-in incl. belastingen) vanuit coordinator
        self._price_info:        dict  = {}
        # Cycle economics (slijtagekosten) — initialiseer met config
        self._cycle_economics:   Optional[BatteryCycleEconomics] = None
        # Externe context vanuit coordinator (ML-verbruik, congestie, export-limiet, EV)
        self._ctx_house_load_next_h_w: float = 0.0   # ML-voorspelling huisverbruik komend uur (W)
        self._ctx_congestion_active:   bool  = False  # netcongestie actief
        self._ctx_export_limit_w:      float = 0.0   # max teruglevering (W), 0 = geen limiet
        self._ctx_ev_charging_w:       float = 0.0   # EV laadvermogen nu (W)
        self._last_decision_ts:    Optional[float] = None   # time.time() van laatste decide_action_v3
        self._last_decision_result: Optional[object] = None  # laatste DecisionResult
        # Hysterese voor surplus-slider: voorkomt heen-en-weer schakelen bij schommelend surplus
        self._surplus_slider_high: bool  = False   # True = slider staat nu hoog (surplus-modus)
        self._surplus_high_since:  float = 0.0     # timestamp eerste keer surplus > drempel
        self._last_slider_write:   float = 0.0     # timestamp laatste slider/mode schrijfactie
        # Max-probe variabelen — worden gebruikt in async_force_slider_calibrate en get_state
        self._probe_active:        bool  = False
        self._probe_last_run:      float = 0.0
        self._probe_key:           Optional[str]   = None
        self._probe_current_w:     Optional[float] = None
        self._probe_confirmed_w:   Optional[float] = None
        self._probe_step_w:        Optional[float] = None

        self._last_state = BatteryProviderState(
            provider_id=self.PROVIDER_ID, provider_label=self.PROVIDER_LABEL
        )
        # Hysterese voor offline-melding: alleen 'offline' tonen na 3 opeenvolgende
        # cycli zonder data. Voorkomt valse melding bij tijdelijk unavailable entity.
        self._offline_count: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        await super().async_setup()
        saved = await self._store.async_load() or {}
        self._override_since = float(saved.get("override_since", 0.0))
        self._saved_mode     = saved.get("saved_mode")
        self._last_sent_mode = saved.get("last_sent_mode")
        self._startup_send_done: bool = False
        self._read_slider_maxima()
        _LOGGER.info(
            "ZonneplanProvider v2.1: detected=%s enabled=%s entities=%s slider_deliver=%.0fW slider_solar=%.0fW",
            self._detected, self._enabled, list(self._entities.keys()),
            self._slider_max_deliver_w, self._slider_max_solar_w,
        )
        # v4.6.326: Na herstart direct home_optimization sturen (ook als SoC nog null is)
        if self._enabled and self._detected and self._entities.get("control_mode"):
            import asyncio
            asyncio.ensure_future(self._async_startup_send())

    async def _async_startup_send(self) -> None:
        """Stuur home_optimization na herstart en verifieer via send_and_verify.
        Blijft oneindig retrying totdat bevestigd — geen aanname dat commando aankomt.
        """
        import asyncio
        from .command_verify import send_and_verify
        target = ZPControlMode.HOME_OPTIMIZATION.value
        # Wacht 10s zodat HA entities geladen zijn
        await asyncio.sleep(10)

        while True:
            eid = self._entities.get("control_mode")
            if not eid:
                _LOGGER.debug("ZonneplanProvider startup: control_mode entity nog niet beschikbaar, retry 15s")
                await asyncio.sleep(15)
                continue

            ok = await send_and_verify(
                hass=self._hass,
                domain="select", service="select_option",
                service_data={"entity_id": eid, "option": target},
                entity_id=eid,
                verify_fn=lambda s: target in (s.state or "").lower() or "thuisoptimalisatie" in (s.state or "").lower(),
                description=f"ZP startup → {target}",
                backoff=[5, 10, 15, 30, 60],
                max_attempts=0,  # oneindig
                verify_delay=5.0,
            )
            if ok:
                self._startup_send_done = True
                self._last_sent_mode = target
                await self._async_save()
                return

    def update_config(self, config: dict) -> None:
        super().update_config(config)
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
        # Herinitialiseer cycle economics bij config-wijziging
        self._cycle_economics = BatteryCycleEconomics(config)

    def update_price_info(self, price_info: dict) -> None:
        """Ontvang all-in prijsinformatie vanuit coordinator (incl. belastingen/BTW/opslag)."""
        if price_info:
            self._price_info = price_info

    def update_context(
        self,
        house_load_next_h_w: float = 0.0,
        congestion_active:   bool  = False,
        export_limit_w:      float = 0.0,
        ev_charging_w:       float = 0.0,
    ) -> None:
        """Ontvang externe context vanuit coordinator.

        house_load_next_h_w: ML-voorspelling van huisverbruik komend uur (W).
                             Gebruikt om netto ontlaadwinst te schatten (eigenverbruik vs. export).
        congestion_active:   Als True: beperk ontlaadvermogen (netcongestie = import verminderen
                             is prioriteit, maar extra export maakt het erger voor buren).
        export_limit_w:      Maximale teruglevering in W (bijv. netbeheerder-beperking).
                             0 = geen beperking.
        ev_charging_w:       Huidig EV-laadvermogen in W. Als EV laadt tijdens HIGH tarief
                             en batterij wil ontladen, blokkeer extra import (EV loopt op batterij).
        """
        self._ctx_house_load_next_h_w = max(0.0, house_load_next_h_w)
        self._ctx_congestion_active   = congestion_active
        self._ctx_export_limit_w      = max(0.0, export_limit_w)
        self._ctx_ev_charging_w       = max(0.0, ev_charging_w)

    def _get_effective_price(self) -> float:
        """All-in prijs in €/kWh (incl. energiebelasting, BTW, leveranciersopslag).

        Valt terug op kale Zonneplan-tariefprijs als coordinator geen price_info heeft.
        De all-in prijs is de werkelijke kosten voor de consument — essentieel voor
        correcte rentabiliteitsberekeningen van laden/ontladen.
        """
        all_in = self._price_info.get("current_all_in")
        if all_in is not None:
            return float(all_in)
        # Fallback: kale EPEX + geconfigureerde belasting
        raw_price = self._last_state.raw.get("electricity_tariff_eur") or 0.0
        tax       = self._price_info.get("tax_per_kwh", 0.0)
        markup    = self._price_info.get("supplier_markup_kwh", 0.0)
        vat       = self._price_info.get("vat_rate", 0.0)
        subtotal  = raw_price + tax + markup
        return round(subtotal * (1 + vat) if vat > 0 else subtotal, 5)

    @property
    def _effective_charge_w(self) -> float:
        """Laadvermogen: geconfigureerde waarde begrensd op geleerd slider maximum.

        Als de probe nog niet gelopen heeft is het geleerde max 10.000W,
        dus heeft dit geen effect totdat het max echt geleerd is.
        """
        return min(self._charge_w, self._slider_max_solar_w)

    @property
    def _effective_discharge_w(self) -> float:
        """Ontlaadvermogen: geconfigureerde waarde begrensd op geleerd slider maximum."""
        return min(self._discharge_w, self._slider_max_deliver_w)

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

        # v4.6.136: hysterese — alleen 'offline' na 3 opeenvolgende cycli zonder data.
        # Voorkomt valse offline-melding bij tijdelijk unavailable entity (split-second).
        _has_data = soc is not None or power is not None or mode is not None
        if _has_data:
            self._offline_count = 0
        else:
            self._offline_count = getattr(self, "_offline_count", 0) + 1
        _is_online = _has_data or self._offline_count < 3

        self._last_state = BatteryProviderState(
            provider_id    = self.PROVIDER_ID,
            provider_label = self.PROVIDER_LABEL,
            soc_pct        = soc,
            power_w        = power,
            is_charging    = (power or 0) > 20,
            is_discharging = (power or 0) < -20,
            active_mode    = mode,
            available_modes= [m["id"] for m in _AVAILABLE_MODES],
            is_online      = _is_online,
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
        max_ch_w  = self._effective_charge_w

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
        net_metering_pct: float = 1.0,
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
        _tg_raw  = raw.get("tariff_group", "") or ""
        # Cache laatste bekende tariefgroep — voorkomt "unknown" direkt na herstart
        if _tg_raw and _tg_raw.lower() not in ("unknown", ""):
            self._last_known_tariff = _tg_raw.lower()
        tg = _tg_raw.lower() if _tg_raw and _tg_raw.lower() not in ("unknown", "") else getattr(self, "_last_known_tariff", "normal")
        _LOGGER.debug(
            "ZonneplanProvider decide_v3: SoC=%.0f%% (from_state=%s) tarief=%s mode=%s last_sent=%s",
            soc, self._last_state.soc_pct is not None,
            tg, self._last_state.active_mode, self._last_sent_mode,
        )
        forecast = raw.get("forecast_tariff_groups", [])   # uur +1..+8
        # Gebruik all-in prijs (incl. energiebelasting, BTW, opslag) voor correcte berekeningen
        price    = self._get_effective_price()
        raw_price = raw.get("electricity_tariff_eur") or 0.0  # kale prijs voor logging
        cap_kwh  = battery_capacity_kwh

        # Cycle economics: zijn de slijtagekosten de winst waard?
        eco = self._cycle_economics or BatteryCycleEconomics({})

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
                    charge_power_w=self._effective_charge_w,
                    confidence=1.0,
                    reasons=reasons,
                    soc_target=max_soc,
                    soc_reachable=reachable_at_high,
                    human_reason=f"Stroom kost nu niets (of je wordt betaald). Batterij wordt maximaal geladen naar {max_soc:.0f}%."
                )
            reasons.append(f"Negatief tarief maar SoC {soc:.0f}% al op max {max_soc:.0f}%")
            return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                  soc_target=max_soc, soc_reachable=soc,
                                  human_reason=f"Stroom is gratis/negatief maar batterij staat al vol op {soc:.0f}%. Niets te doen.")

        # ══════════════════════════════════════════════════════════════════════
        # PRIORITEIT 2 — PRIJS ONDER FLOOR (niet HIGH)
        # ══════════════════════════════════════════════════════════════════════
        if price < self._price_floor and tg != "high":
            reasons.append(
                f"Prijs {price:.4f} €/kWh < drempel {self._price_floor:.4f} → hold"
            )
            return DecisionResult(action=ZPAction.HOLD, confidence=0.8, reasons=reasons,
                                  soc_target=soc_target, soc_reachable=soc,
                                  human_reason=f"Stroomprijs is erg laag (€{price:.4f}/kWh). Te goedkoop om rendabel actie te ondernemen — batterij vasthouden.")

        # ══════════════════════════════════════════════════════════════════════
        # PRIORITEIT 3 — SOC-GRENSBESCHERMING
        # ══════════════════════════════════════════════════════════════════════
        if tg == "low" and soc >= max_soc:
            reasons.append(f"SoC {soc:.0f}% ≥ max {max_soc:.0f}% → hold")
            return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                  soc_target=max_soc, soc_reachable=soc,
                                  human_reason=f"Batterij is volledig geladen ({soc:.0f}%). Niets te laden.")

        # ── Externe context: pas effectief ontlaadvermogen aan ────────────────
        # 1. Export-limiet: max teruglevering beperkt nuttig ontlaadvermogen
        #    (leverbaar = huislast + export_limiet, niet meer)
        _ctx_house = self._ctx_house_load_next_h_w
        _ctx_export_limit = self._ctx_export_limit_w
        _ctx_ev_w   = self._ctx_ev_charging_w
        _ctx_cong   = self._ctx_congestion_active

        # Schat netto huis-eigenverbruik (als ML forecast beschikbaar, anders 800W default)
        _house_load_est = _ctx_house if _ctx_house > 50 else 800.0

        # Export-limiet: beperk ontlaadvermogen tot wat het huis + limiet samen aankunnen
        _max_discharge_ctx = self._effective_discharge_w
        if _ctx_export_limit > 0 and _ctx_export_limit < self._effective_discharge_w:
            # Wat het huis eigenverbruikt hoeft niet geëxporteerd te worden
            _max_discharge_ctx = min(self._effective_discharge_w,
                                     _house_load_est + _ctx_export_limit)

        # Netcongestie: exporteer niet tijdens congestie (verhoogt netbelasting)
        if _ctx_cong:
            _max_discharge_ctx = min(_max_discharge_ctx, _house_load_est * 1.1)

        # ══════════════════════════════════════════════════════════════════════
        # TARIEFGROEP HIGH
        # ══════════════════════════════════════════════════════════════════════
        if tg == "high":
            if soc <= min_soc:
                reasons.append(
                    f"HIGH maar SoC {soc:.0f}% ≤ min {min_soc:.0f}% → hold (bescherming)"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=1.0, reasons=reasons,
                                      soc_target=soc_target, soc_reachable=soc,
                                      human_reason=f"Tarief is hoog maar batterij staat al op minimum ({min_soc:.0f}%) — ontladen is niet veilig.")

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
                                      soc_target=soc_target, soc_reachable=soc,
                                      human_reason=(
                                          f"Tarief is hoog maar de zon levert al energie aan het huis. "
                                          f"Ontladen naar het net levert bij {int(sal_ctx.saldering_pct*100)}% saldering "
                                          f"te weinig op om de batterijslijtage te rechtvaardigen."
                                      ))

            # PV surplus vermindert gewenst ontlaadvermogen
            # (PV dekt al een deel van het huis, batterij hoeft minder te doen)
            net_discharge_w = max(500.0, self._effective_discharge_w - pv.solar_surplus_w * 0.5)

            # Context-limieten toepassen (export-limiet, netcongestie)
            net_discharge_w = min(net_discharge_w, _max_discharge_ctx)

            # EV-conflict check: als EV laadt op net tijdens HIGH tarief,
            # kan batterij-ontlading voor EV zorgen (eigenverbruik) — dat is gewenst.
            # Maar als ontlaadvermogen < EV-verbruik, is het beter te melden.
            _ev_note = ""
            if _ctx_ev_w > 200 and net_discharge_w < _ctx_ev_w * 0.8:
                _ev_note = f" (EV laadt {_ctx_ev_w:.0f}W — deels gedekt)"
                reasons.append(f"EV laadt {_ctx_ev_w:.0f}W tijdens HIGH — batterij dekt gedeeltelijk{_ev_note}")

            # Dynamisch vermogen schalen op all-in prijs:
            # Hoe hoger de prijs, hoe harder ontladen loont (max bij ≥ 0.40 €/kWh)
            _price_scale = min(1.0, max(0.4, (price - 0.15) / (0.40 - 0.15)))
            net_discharge_w = round(net_discharge_w * _price_scale)
            net_discharge_w = max(500.0, net_discharge_w)

            # Cycle economics check: is ontladen de slijtage waard?
            # Gebruiken huidig prijs als discharge_price, prijs_floor als proxy charge_price
            _eco_check = eco.evaluate_slot_pair(
                charge_price    = self._price_floor,
                discharge_price = price,
                soc_at_discharge= soc,
            )
            if not _eco_check.worth_it and tg == "high" and n_future_high == 0:
                reasons.append(
                    f"HIGH maar netto spread na slijtage negatief ({_eco_check.reason}) → hold"
                )
                return DecisionResult(
                    action=ZPAction.HOLD, confidence=0.7,
                    reasons=reasons, soc_target=soc_target, soc_reachable=soc,
                    human_reason=(
                        f"Tarief is hoog (€{price:.3f}/kWh) maar na aftrek van batterijslijtage "
                        f"({_eco_check.cycle_cost*100:.1f} ct/kWh) is ontladen niet winstgevend. "
                        f"Batterij vasthouden."
                    ))

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
                    human_reason=(
                        f"Duur stroomtarief nu, geen duur uur meer verwacht later. "
                        f"Batterij wordt ontladen naar {eff_min:.0f}% om maximaal te profiteren "
                        f"van het hoge tarief."
                    ),
                )
            else:
                # Toekomstige HIGH-uren → proportionele reserve
                if soc > soc_target:
                    # Ontlaadvermogen evenredig met overschot boven target
                    fraction = min(1.0, (soc - soc_target) / 20.0)
                    disch_w  = max(500.0, round(self._effective_discharge_w * fraction))
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
                        human_reason=(
                            f"Duur tarief nu én nog {n_future_high} duur uur verwacht. "
                            f"Batterij wordt gedeeltelijk ontladen ({disch_w:.0f}W) — "
                            f"reserve van {soc_target:.0f}% wordt aangehouden voor later."
                        ),
                    )
                else:
                    reasons.append(
                        f"HIGH, {n_future_high} toekomstige HIGH-uren, "
                        f"SoC {soc:.0f}% ≤ reserve {soc_target:.0f}% → hold"
                    )
                    return DecisionResult(action=ZPAction.HOLD, confidence=0.9,
                                          reasons=reasons, soc_target=soc_target,
                                          soc_reachable=soc,
                                          human_reason=(
                                              f"Duur tarief maar batterij is al op reserveniveau ({soc:.0f}%). "
                                              f"Nog {n_future_high} duur uur verwacht — capaciteit bewaren."
                                          ))

        # ══════════════════════════════════════════════════════════════════════
        # TARIEFGROEP LOW
        # ══════════════════════════════════════════════════════════════════════
        elif tg == "low":
            # Saldering-bewuste PV-drempel:
            #   100% saldering → 0.50 kWh,  36% → 0.18 kWh,  0% → 0.10 kWh
            _pv_hold_threshold = max(0.10, 0.50 * net_metering_pct)
            _sal_label = f"{int(net_metering_pct * 100)}% saldering"

            if first_high_h is None:
                # Geen HIGH in forecast
                if pv.pv_kwh_next_8h > _pv_hold_threshold:
                    _sal_note = (
                        f" ({_sal_label} actief)"
                        if net_metering_pct < 1.0 else ""
                    )
                    reasons.append(
                        f"LOW, geen HIGH in forecast, {pv.pv_kwh_next_8h:.1f} kWh PV "
                        f"verwacht{_sal_note} → bewaar ruimte voor gratis PV"
                    )
                    return DecisionResult(
                        action=ZPAction.HOLD, confidence=0.85,
                        reasons=reasons, soc_target=soc_target, soc_reachable=soc,
                        human_reason=(
                            f"Goedkoop tarief, geen duur uur verwacht. "
                            f"Komende uren is er nog {pv.pv_kwh_next_8h:.1f} kWh zon verwacht — "
                            f"batterij wordt vrijgehouden om die op te vangen "
                            f"(bij {_sal_label} is zelfverbruik financieel het beste)."
                        ),
                    )

                reasons.append(
                    f"LOW, geen HIGH in forecast, geen PV verwacht ({_sal_label}) → hold"
                )
                return DecisionResult(
                    action=ZPAction.HOLD, confidence=0.7,
                    reasons=reasons, soc_target=soc_target, soc_reachable=soc,
                    human_reason=(
                        f"Goedkoop tarief, geen duur uur verwacht en geen zon meer vandaag — "
                        f"batterij vasthouden op {soc_target:.0f}%. "
                        f"Er is geen financieel voordeel om nu actie te ondernemen."
                    ),
                )

            # HIGH komt eraan — laad batterij naar charge_target

            # PV dekt laden al dit uur → netladen overbodig
            if pv.pv_covers_charge:
                reasons.append(
                    f"LOW, HIGH in {first_high_h}u, maar PV dekt laden al "
                    f"(piek {pv.pv_peak_next_8h_w:.0f}W dit uur) → wacht op gratis PV"
                )
                return DecisionResult(
                    action=ZPAction.HOLD, confidence=0.9,
                    reasons=reasons, soc_target=charge_target,
                    soc_reachable=reachable_at_high,
                    human_reason=(
                        f"Duur uur verwacht over {first_high_h} uur. "
                        f"De zon levert nu al voldoende om de batterij te laden — "
                        f"gratis zonne-energie is goedkoper dan stroom van het net."
                    ),
                )

            gap = charge_target - soc

            if gap <= 2:
                reasons.append(
                    f"LOW, SoC {soc:.0f}% ≈ laaddoel {charge_target:.0f}% → hold"
                )
                return DecisionResult(
                    action=ZPAction.HOLD, confidence=0.85,
                    reasons=reasons, soc_target=charge_target, soc_reachable=soc,
                    human_reason=(
                        f"Batterij staat al op {soc:.0f}% — dat is genoeg voor het "
                        f"verwachte dure uur over {first_high_h} uur. Niets te doen."
                    ),
                )

            # Laadvermogen schalen naar urgentie
            urgency  = max(0.3, 1.0 - (first_high_h - 1) / 6.0)
            charge_w = max(500.0, round(self._effective_charge_w * urgency))

            # Cycle economics check: is laden + later ontladen de slijtage waard?
            # Schat discharge prijs als 2× huidige LOW prijs (HIGH is typisch 2-3× LOW)
            _est_discharge_price = max(price * 2.0, price + 0.08)
            _eco_charge = eco.evaluate_slot_pair(
                charge_price    = price,
                discharge_price = _est_discharge_price,
                soc_at_charge   = soc,
            )
            if not _eco_charge.worth_it:
                reasons.append(
                    f"LOW, HIGH verwacht maar spread na slijtage te klein ({_eco_charge.reason}) → hold"
                )
                return DecisionResult(
                    action=ZPAction.HOLD, confidence=0.65,
                    reasons=reasons, soc_target=soc_target, soc_reachable=soc,
                    human_reason=(
                        f"Goedkoop tarief (€{price:.3f}/kWh), maar het verschil met het verwachte "
                        f"dure uur is na aftrek van batterijslijtage "
                        f"({_eco_charge.cycle_cost*100:.1f} ct/kWh) niet groot genoeg om te laden."
                    ),
                )

            note = ""
            _human_pv_note = ""
            if pv.forecast_tomorrow_kwh > cap_kwh * 0.3:
                note = (f", PV morgen {pv.forecast_tomorrow_kwh:.1f} kWh → "
                        f"max SoC beperkt tot {charge_target:.0f}%")
                _human_pv_note = (
                    f" Morgen wordt {pv.forecast_tomorrow_kwh:.1f} kWh zon verwacht, "
                    f"dus de batterij wordt niet verder dan {charge_target:.0f}% geladen "
                    f"zodat er ruimte blijft voor zonne-energie."
                )

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
                human_reason=(
                    f"Duur uur verwacht over {first_high_h} uur, batterij staat op {soc:.0f}% "
                    f"en moet naar {charge_target:.0f}%. Nu laden met {charge_w:.0f}W "
                    f"via goedkope stroom ({_sal_label}).{_human_pv_note}"
                ),
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
                    charge_w = max(500.0, round(self._effective_charge_w * urgency))
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
                        human_reason=(
                            f"Normaal tarief maar duur uur over {first_high_h} uur. "
                            f"Batterij staat op {soc:.0f}% terwijl {soc_target:.0f}% "
                            f"minimaal nodig is — snel bijladen met {charge_w:.0f}W."
                        ),
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
                        discharge_power_w=round(self._effective_discharge_w * 0.5),
                        bypass_antiround=False,
                        confidence=0.7,
                        reasons=reasons,
                        soc_target=max_soc - 20.0,
                        soc_reachable=soc,
                        human_reason=(
                            f"Over {first_low_h} uur wordt stroom goedkoop. "
                            f"Batterij nu gedeeltelijk ontladen zodat er ruimte is "
                            f"om goedkope stroom op te laden."
                        ),
                    )

            # PV surplus nu → hold, PV doet het werk
            if pv.solar_surplus_w > 200:
                reasons.append(
                    f"NORMAL, PV surplus {pv.solar_surplus_w:.0f}W → "
                    f"laat PV de batterij opladen"
                )
                return DecisionResult(action=ZPAction.HOLD, confidence=0.8,
                                      reasons=reasons, soc_target=soc_target,
                                      soc_reachable=soc,
                                      human_reason=(
                                          f"De zon levert nu {pv.solar_surplus_w:.0f}W "
                                          f"meer dan het huis verbruikt — gratis zonne-energie "
                                          f"laadt de batterij op. Geen actie nodig."
                                      ))

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
                    _anticipate_w = round(self._effective_discharge_w * 0.50)
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
                        human_reason=(
                            f"Batterij staat bijna vol ({soc:.0f}%) en er komt "
                            f"{pv.pv_kwh_next_8h:.1f} kWh zon aan. "
                            f"Alvast gedeeltelijk ontladen naar {_target_soc:.0f}% "
                            f"zodat de zonne-energie straks niet wordt verspild."
                        ),
                    )

            reasons.append("NORMAL, geen duidelijke kans → Powerplay")
            return DecisionResult(action=ZPAction.POWERPLAY, confidence=0.6,
                                  reasons=reasons, soc_target=soc_target,
                                  soc_reachable=soc,
                                  human_reason="Normaal tarief, geen duidelijk voordeel — Zonneplan bepaalt zelf.")

        # Fallback
        reasons.append(f"Onbekende tariefgroep '{tg}' → Powerplay")
        return DecisionResult(action=ZPAction.POWERPLAY, confidence=0.5,
                              reasons=reasons, soc_target=soc_target,
                              soc_reachable=soc,
                              human_reason="Onbekende situatie — Zonneplan bepaalt zelf.")

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
            "current_price_all_in_eur": self._get_effective_price(),
            "price_tax_eur": self._price_info.get("tax_per_kwh", 0.0),
            "price_vat_rate": self._price_info.get("vat_rate", 0.0),
            "cycle_cost_eur_kwh": round(
                (self._cycle_economics or BatteryCycleEconomics({}))._base_cycle_cost, 5
            ),
            "ctx_house_load_w":    round(self._ctx_house_load_next_h_w),
            "ctx_congestion":      self._ctx_congestion_active,
            "ctx_export_limit_w":  round(self._ctx_export_limit_w),
            "ctx_ev_charging_w":   round(self._ctx_ev_charging_w),
            "forecast_8h":       forecast,
            "high_hours":        forecast.count("high"),
            "low_hours":         forecast.count("low"),
            "normal_hours":      forecast.count("normal"),
            "recommended_action":result.action.value,
            "action_confidence": round(result.confidence, 2),
            "action_reasons":    all_reasons,
            "action_reasons_all": all_reasons,
            "action_human_reason": result.human_reason,
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
        w = power_w or self._effective_charge_w
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
        w = power_w or self._effective_discharge_w
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
            from .command_verify import send_switch
            await send_switch(
                self._hass, mc_eid, turn_on=False,
                description=f"ZP manual_control uit {mc_eid}",
                max_attempts=3, verify_delay=3.0,
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
        net_metering_pct:        float = 1.0,
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

        # Handmatige override: gebruiker heeft zelf een modus gekozen
        # CloudEMS respecteert dit en overschrijft NIET totdat de timeout verloopt
        _now_ts = time.time()
        if self._manual_override_until > _now_ts:
            _remaining_min = round((self._manual_override_until - _now_ts) / 60, 1)
            _LOGGER.debug(
                "ZonneplanProvider: handmatige override actief (%s, nog %.1f min)",
                self._manual_override_mode, _remaining_min,
            )
            return DecisionResult(
                action=ZPAction.HOLD,
                confidence=1.0,
                reasons=[f"Handmatige override: {self._manual_override_mode} (nog {_remaining_min:.0f}min)"],
                human_reason=f"Je hebt handmatig '{self._manual_override_mode}' ingesteld. CloudEMS wacht nog {_remaining_min:.0f} minuten.",
                executed=f"manual_override ({self._manual_override_mode})",
            )
        elif self._manual_override_until > 0:
            # Override verlopen — reset
            _LOGGER.info(
                "ZonneplanProvider: handmatige override verlopen (%s) — CloudEMS neemt weer over",
                self._manual_override_mode,
            )
            self._manual_override_until = 0.0
            self._manual_override_mode  = ""

        # Detecteer of gebruiker BUITEN CloudEMS om de modus heeft gewijzigd
        # Als active_mode verschilt van last_sent_mode → gebruiker heeft manueel ingegrepen
        _active = self._last_state.active_mode or ""
        _expected = self._last_sent_mode or ""
        if (_expected and _active and _active != _expected
                and self._startup_send_done
                and self._manual_override_until <= 0):
            # Standaard override duur: 30 minuten
            _override_min = 30
            self._manual_override_until = _now_ts + _override_min * 60
            self._manual_override_mode  = _active
            _LOGGER.info(
                "ZonneplanProvider: manuele override gedetecteerd — "
                "Zonneplan staat op '%s' (CloudEMS verwachtte '%s'). "
                "CloudEMS wacht %d minuten voor terugname.",
                _active, _expected, _override_min,
            )
            return DecisionResult(
                action=ZPAction.HOLD,
                confidence=1.0,
                reasons=[f"Manuele override gedetecteerd: {_active} ({_override_min}min respijt)"],
                human_reason=f"Je hebt handmatig '{_active}' ingesteld. CloudEMS wacht {_override_min} minuten.",
                executed=f"manual_override ({_active})",
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
                                       soh_pct=soh_pct, net_metering_pct=net_metering_pct)

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
            result.executed = f"charge ({result.charge_power_w or self._effective_charge_w:.0f}W)"
            self._last_expected_action = "charge"
            self._last_action_ts = __import__("time").time()
            self._last_battery_w_at_cmd = float(self._last_state.power_w or 0)
            await self.async_set_charge(power_w=result.charge_power_w)

        elif result.action == ZPAction.DISCHARGE:
            await self.async_set_discharge(
                power_w=result.discharge_power_w,
                bypass_antiround=result.bypass_antiround,
            )
            result.executed = f"discharge ({result.discharge_power_w or self._effective_discharge_w:.0f}W)"
            self._last_expected_action = "discharge"
            self._last_action_ts = __import__("time").time()
            self._last_battery_w_at_cmd = float(self._last_state.power_w or 0)

        elif result.action == ZPAction.HOLD:
            if self._last_state.active_mode != ZPControlMode.HOME_OPTIMIZATION.value or not self._startup_send_done:
                ok = await self._send_control_mode(ZPControlMode.HOME_OPTIMIZATION.value)
                if ok:
                    result.executed = ZPControlMode.HOME_OPTIMIZATION.value
            else:
                result.executed = f"hold ({self._last_state.active_mode})"
            # Sla verwachte actie op voor battery_verify check in guardian
            self._last_expected_action = "hold"
            self._last_action_ts = __import__("time").time()

        elif result.action == ZPAction.POWERPLAY:
            result.executed = "powerplay"  # ZP AI bepaalt, geen sturing
        else:
            pass
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
                    _optimal_deliver_w = max(800.0, min(self._effective_discharge_w, _surplus * 0.85))
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

        return result

    async def async_apply_forecast_decision(self) -> ZPAction:
        """Backwards-compat wrapper → async_apply_forecast_decision_v3() zonder PV."""
        result = await self.async_apply_forecast_decision_v3()
        return result.action



    async def async_force_slider_calibrate(self) -> dict:
        """Forceer een beslissing en schrijf sliders direct — negeert hysterese/debounce.

        Gebruikt de ongeclampte _charge_w / _discharge_w zodat deze actie ook correct
        werkt als het geleerde max nog op default staat of juist lager is dan geconfigureerd.
        Mag niet starten tijdens een actieve max-probe.
        """
        if self._probe_active:
            return {"error": "Max-probe is actief — wacht tot die klaar is"}

        soc     = self._last_state.soc_pct or 0.0
        pv      = self._build_pv_context()
        surplus = pv.solar_surplus_w if pv else 0.0
        max_soc = self._max_soc

        # Gebruik geconfigureerde waarden (niet begrensd op geleerd max)
        raw_discharge_w = self._discharge_w
        raw_charge_w    = self._charge_w

        # ── deliver_to_home ────────────────────────────────────────────────────
        if surplus > 700 and soc >= max_soc - 5.0:
            deliver_w      = max(800.0, min(raw_discharge_w, surplus * 0.85))
            deliver_reason = f"surplus {surplus:.0f}W, SoC {soc:.0f}% ≥ {max_soc-5:.0f}%"
        elif surplus > 300:
            deliver_w      = max(600.0, surplus * 0.6)
            deliver_reason = f"matig surplus {surplus:.0f}W"
        else:
            deliver_w      = 600.0
            deliver_reason = f"laag surplus {surplus:.0f}W → standaard"

        # ── solar_charge ───────────────────────────────────────────────────────
        if soc >= max_soc - 2.0:
            solar_w      = 0.0
            solar_reason = f"SoC {soc:.0f}% bijna vol ({max_soc:.0f}%)"
        elif surplus > 500:
            solar_w      = min(surplus * 0.9, raw_charge_w)
            solar_reason = f"surplus {surplus:.0f}W → maximaal laden"
        elif surplus > 100:
            solar_w      = surplus * 0.7
            solar_reason = f"klein surplus {surplus:.0f}W"
        else:
            solar_w      = 400.0
            solar_reason = "geen surplus → minimaal zonneladen"

        deliver_w = round(deliver_w)
        solar_w   = round(solar_w)

        # Schrijf direct — negeer idempotent-check
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

    def _read_slider_maxima(self) -> None:
        """Leest de slider-maxima direct uit het 'max' attribuut van de number-entiteiten."""
        for key, attr in (
            ("deliver_to_home", "_slider_max_deliver_w"),
            ("solar_charge",    "_slider_max_solar_w"),
        ):
            eid = self._entities.get(key)
            if not eid:
                continue
            st = self._hass.states.get(eid)
            if not st:
                continue
            try:
                max_w = float(st.attributes.get("max", 10000))
                if max_w > 0:
                    setattr(self, attr, max_w)
                    _LOGGER.debug(
                        "ZonneplanProvider: slider max '%s' = %.0fW (uit HA attribuut)",
                        key, max_w,
                    )
            except (ValueError, TypeError):
                pass

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
                "default": True,
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
            "manual_override_active": self._manual_override_until > time.time(),
            "manual_override_mode":   self._manual_override_mode or None,
            "manual_override_min_left": round((self._manual_override_until - time.time()) / 60, 1)
                                        if self._manual_override_until > time.time() else None,
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
            # slider maxima niet opslaan — komen uit entiteit-attributen
            "slider_max_deliver_w":   self._slider_max_deliver_w,
            "slider_max_solar_w":      self._slider_max_solar_w,
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
            if self._startup_send_done:
                _LOGGER.debug(
                    "ZonneplanProvider: mode al %s, geen call (idempotent: last_sent=%s, current=%s)",
                    mode_val, self._last_sent_mode, current,
                )
                return True
            # Na herstart altijd één keer sturen, ook als modus al klopt
            _LOGGER.info("ZonneplanProvider: startup-sturing %s (eenmalig na herstart)", mode_val)

        await self._save_current_mode()
        try:
            await self._hass.services.async_call(
                "select", "select_option",
                {"entity_id": eid, "option": mode_val},
                blocking=False,
            )
            self._last_sent_mode = mode_val
            self._startup_send_done = True
            self._last_executed_mode = mode_val
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
        """Stel slider in — sla over als waarde al gelijk is (idempotent).

        Begrenst op het geleerde maximum. Na 30s wordt de werkelijke staat
        teruggelezen: is de waarde afgeknepen dan slaan we dat op als nieuw max.
        """
        eid = self._entities.get(key)
        if not eid:
            return

        # Begrens op geleerd maximum
        learned_max = (self._slider_max_deliver_w if key == "deliver_to_home"
                       else self._slider_max_solar_w)
        clamped_w = min(round(value_w, 0), learned_max)

        if last_sent == clamped_w:
            _LOGGER.debug("ZonneplanProvider: slider %s al %.0fW, geen call", key, clamped_w)
            return

        try:
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": eid, "value": clamped_w},
                blocking=False,
            )
            self._last_slider_write = time.time()
            _LOGGER.debug(
                "ZonneplanProvider: slider %s → %.0fW (geleerd max: %.0fW)",
                key, clamped_w, learned_max,
            )
        except Exception as exc:
            _LOGGER.debug("ZonneplanProvider slider %s fout: %s", key, exc)
            return

        # Lees na 30s de werkelijke staat terug — geen extra cloud-call,
        # HA heeft de Zonneplan-entiteit al geupdated via polling.
        sent_w = clamped_w

        def _readback(_now) -> None:
            # Nooit learned_max aanpassen tijdens een actieve probe — probe doet dit zelf
            if self._probe_active:
                return
            st = self._hass.states.get(eid)
            if not st or st.state in ("unavailable", "unknown"):
                return
            try:
                actual_w = round(float(st.state), 0)
            except (ValueError, TypeError):
                return

            old_max = (self._slider_max_deliver_w if key == "deliver_to_home"
                       else self._slider_max_solar_w)

            if actual_w < sent_w - 50:
                # Nexus heeft afgeknepen → dit IS het plafond
                new_max = actual_w
                _LOGGER.info(
                    "ZonneplanProvider: slider %s afgeknepen %.0fW→%.0fW — "
                    "nieuw geleerd max: %.0fW",
                    key, sent_w, actual_w, new_max,
                )
            else:
                # Geaccepteerd → stapje omhoog (max 100W per keer)
                new_max = min(old_max + 100.0, sent_w + 100.0)
                _LOGGER.debug(
                    "ZonneplanProvider: slider %s geaccepteerd %.0fW — max: %.0fW→%.0fW",
                    key, sent_w, old_max, new_max,
                )

            if new_max != old_max:
                if key == "deliver_to_home":
                    self._slider_max_deliver_w = new_max
                else:
                    self._slider_max_solar_w = new_max
                self._slider_max_dirty = True
                self._hass.async_create_task(self._async_save())

        async_call_later(self._hass, 30, _readback)

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
            "override_since":         self._override_since,
            "saved_mode":             self._saved_mode,
            "last_sent_mode":         self._last_sent_mode,
            # slider maxima niet opslaan — komen uit entiteit-attributen
            "probe_last_run":         self._probe_last_run,
            # Probe-state: herstel voortgang na HA herstart
            "probe_active":           self._probe_active,
            "probe_key":              self._probe_key,
            "probe_current_w":        self._probe_current_w,
            "probe_confirmed_w":      self._probe_confirmed_w,
            "probe_step_w":           self._probe_step_w,
        })
        self._slider_max_dirty = False


# ── Registreer bij import ─────────────────────────────────────────────────────
BatteryProviderRegistry.register_provider(ZonneplanProvider)
