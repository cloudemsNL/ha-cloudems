# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Smart Boiler / Socket Controller — v3.1.0

v1.x  Enkelvoudige boilers, aan/uit op basis van goedkope uren / PV-surplus.
v2.0  Cascade-groepen: sequential / parallel / priority / auto.
v2.1  Zelflerend leveringsboiler-detectie (temp + energie).
v3.0  Volledig intelligent systeem:
        - cycle_kwh persistent over HA-restarts
        - Gebruikspatroon per uur (voorspellend opwarmen)
        - Thermische verliescompensatie (afkoelsnelheid per boiler)
        - Vraaggestuurde prioriteit via flow-sensor / debietmeter
        - Seizoenspatroon (automatisch zomer/winter setpoints)
        - Netcongestie koppeling (comfort vs buffer prioriteit)
        - Proportionele dimmer sturing (kW-nauwkeurig op PV-surplus)
v3.1  Volledige preventieve gezondheids- en veiligheidsintelligentie:
        - Legionella-cyclus: wekelijks 65°C, gepland in goedkoopste uur
          Ontsmet pas als 1 uur aaneengesloten ≥65°C gehouden (confirm ticks)
          Deadline-bewaking: na 8 dagen forceer op eerstvolgende midnight
        - Geleerde opwarmsnelheid (°C/h) per boiler via EMA
          → nauwkeurige reheat_eta_min: minuten tot boiler weer nodig
          → proactief starten vóór piekverbruik op basis van patroon
        - Temperatuurafhankelijke COP voor HEAT_PUMP/HYBRID:
          cop = f(buitentemp), DHW-correctie 0.70×, gas-vs-WP per uur
        - Kalkdetectie: stijgend verschil opwarmsnelheid vs baseline
          Schaal 0-100%, waarschuwing bij >60%
        - Anode-slijtage: kWh-doorvoerteller per boiler
          Waterhardheid-gewogen, waarschuwing bij >80% van drempelwaarde

Copyright 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import aiohttp as _aiohttp  # type: ignore[import]
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from .cloud_command_queue import CloudCommandQueue

_LOGGER = logging.getLogger(__name__)

# ─── Sturingmodi ─────────────────────────────────────────────────────────────
MODE_CHEAP_HOURS    = "cheap_hours"
MODE_NEGATIVE_PRICE = "negative_price"
MODE_PV_SURPLUS     = "pv_surplus"
MODE_EXPORT_REDUCE  = "export_reduce"

# ─── ACRouter (RobotDyn DimmerLink hardware) ──────────────────────────────────
# REST API mode-codes voor ACRouter firmware v1.2.0+
# POST /api/mode  {"mode": N}
ACROUTER_MODE_OFF     = 0   # Uit
ACROUTER_MODE_AUTO    = 1   # Autonoom grid-balancering (niet gebruikt door CloudEMS)
ACROUTER_MODE_ECO     = 2   # Voorkomt export, laat import toe
ACROUTER_MODE_OFFGRID = 3   # Alleen zonne-overschot (niet gebruikt)
ACROUTER_MODE_MANUAL  = 4   # Manual dimmer-niveau (CloudEMS stuurt dit)
ACROUTER_MODE_BOOST   = 5   # 100% power (goedkope uren)
ACROUTER_HTTP_TIMEOUT = 3   # seconden timeout per REST-call
ACROUTER_UPDATE_S     = 10  # minimale tijd tussen dimmer-updates (voorkom flicker)
MODE_HEAT_DEMAND    = "heat_demand"
MODE_CONGESTION_OFF = "congestion_off"

# ─── Boilertypen ──────────────────────────────────────────────────────────────
# Bepaalt de sturingsstrategie in _evaluate_single():
#
#  RESISTIVE — Weerstandsboiler (aan/uit schakelbaar). Snel warm (1-3u).
#              Prijs en PV-surplus domineren volledig.
#
#  HEAT_PUMP — Pure warmtepomp-boiler (bijv. Ariston Nuos, Atlantic Calypso).
#              COP>1: altijd goedkoper dan weerstand. green ALTIJD aan bij tekort.
#              boost (weerstand) alleen in goedkoopste N uren of negatieve prijs.
#              Lange opwarmtijd (8-12u) — proactive starten via heat_up_hours.
#
#  HYBRID    — Warmtepomp + weerstandselement (bijv. Ariston Lydos Hybrid).
#              green-preset = WP-element: ALTIJD aan bij temperaturetekort.
#              boost-preset = weerstandselement: alleen goedkoopste uren/surplus.
#              control_mode="preset", preset_off="green", preset_on="boost".
#
#  VARIABLE  — Variabele boiler 0-100% (bijv. SolarEdge MyHeat, ESPHome dimmer).
#              Proportioneel op PV-surplus. Bij geen surplus: minimumpower in
#              goedkoopste uren. Bij negatieve prijs: 100%.
#
BOILER_TYPE_RESISTIVE = "resistive"
BOILER_TYPE_HEAT_PUMP = "heat_pump"
BOILER_TYPE_HYBRID    = "hybrid"

# v4.6.18: leesbare merknamen voor dashboard / diagnostiek
_BRAND_LABELS: dict[str, str] = {
    "ariston_lydos_hybrid": "Ariston Lydos Hybrid",
    "ariston_velis_evo":    "Ariston Velis Evo",
    "ariston_andris":       "Ariston Andris Lux",
    "midea_e2":             "Midea / Comfee E2",
    "midea_e3":             "Midea / Comfee E3",
    "daikin_altherma_dhw":  "Daikin Altherma DHW",
    "vaillant_unistor":     "Vaillant uniSTOR / aroSTOR",
    "stiebel_wwk":          "Stiebel Eltron WWK",
    "aosmith_electric":     "A.O. Smith elektrisch",
    "itho_heatpump":        "Itho Daalderop WP",
    "generic_resistive":    "Generiek elektrisch",
    "generic_heatpump":     "Generiek warmtepomp",
    "unknown":              "Onbekend",
}
BOILER_TYPE_VARIABLE  = "variable"

CASCADE_SEQUENTIAL  = "sequential"
CASCADE_PARALLEL    = "parallel"
CASCADE_PRIORITY    = "priority"
CASCADE_AUTO        = "auto"
CASCADE_STANDBY     = "standby"

# ─── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_SURPLUS_THRESHOLD_W = 300
DEFAULT_EXPORT_THRESHOLD_A  = 1.0
DEFAULT_HEAT_DEMAND_TEMP_C  = 5.0
DEFAULT_MIN_ON_MINUTES      = 10
DEFAULT_MIN_OFF_MINUTES     = 5
STAGGER_DEFAULT_S           = 45
SAFETY_MAX_C                = 80.0
HYSTERESIS_C                = 2.0

# ─── Gas-vs-current vergelijking ───────────────────────────────────────────────
# Gebruikt bij resistive/variable boilers als has_gas_heating=True:
# gas_eur_kwh_th  = gas_prijs_m3 / (9.769 kWh/m³ × 0.90 rendement CV)
# elec_eur_kwh_th = current_prijs_kwh / 1.0   (weerstandselement COP=1)
# → boiler alleen aan als elec_eur_kwh_th < gas_eur_kwh_th
GAS_KWH_PER_M3_BOILER = 9.769   # calorische value aardgas (kWh/m³)
GAS_BOILER_EFF_BOILER  = 0.90   # rendement CV-ketel (typisch 90%)
GAS_VS_ELEC_MARGIN     = 0.01   # €/kWh threshold: current mag max 1ct/kWh duurder
                                  # dan gas thermisch voor kleine onzekerheidsband

# ─── Legionella preventie ─────────────────────────────────────────────────────
LEGIONELLA_TEMP_C         = 65.0   # minimale temperature voor legionella-doding
LEGIONELLA_CONFIRM_S      = 3600   # seconden ≥65°C nodig voor bevestigde ontsmet.
LEGIONELLA_INTERVAL_DAYS  = 7      # maximaal interval tussen cycli
LEGIONELLA_DEADLINE_DAYS  = 8      # na N dagen: force-cycle ongeacht prijs/tijd
LEGIONELLA_PRICE_RANK     = 4      # plan in één van de goedkoopste N uren van dag

# ─── Ariston cloud verify/retry ──────────────────────────────────────────────
# De Ariston cloud is onbetrouwbaar: settings komen soms niet aan of worden
# overschreven. Na elke send controleren we of de state overeenkomt en retrien
# indien nodig — met toenemende backoff om 429-blocks te vermijden.
ARISTON_VERIFY_DELAY_S    = 15     # eerste verify: 15s na send
ARISTON_RETRY_BACKOFF     = [15, 30, 60, 120]  # delays tussen retries (seconden)
ARISTON_MAX_RETRIES       = 4      # maximaal 4 attempten na de initiële send
ARISTON_RATE_LIMIT_S      = 180    # DEPRECATED v4.6.560 — backoff nu via CloudCommandQueue
ARISTON_PRESET_TOLERANCE  = 0      # preset moet exact kloppen (string compare)
ARISTON_TEMP_TOLERANCE    = 1.0    # setpoint mag ±1°C afwijken (float compare)
# v4.6.550: debounce — send commando pas als gewenste state 10 min stable is.
# Voorkomt 429-errors bij Ariston cloud door te frequente API-aanroepen.
# Het laatste gewenste commando wint altijd (geen stale commands).
ARISTON_CMD_DEBOUNCE_S    = 30     # 30s debounce — iMemory brug vereist snel reageren

# ─── Thermisch model: learnede opwarmsnelheid ────────────────────────────────
HEAT_RATE_ALPHA           = 0.10   # EMA-factor voor g_heat_rate bijwerking
HEAT_RATE_MIN_C_H         = 0.5    # minimum plausibele opwarmsnelheid (°C/h)
HEAT_RATE_MAX_C_H         = 30.0   # maximum plausibele opwarmsnelheid (°C/h)
HEAT_RATE_INIT_C_H        = 5.0    # startseed (≈ 2kW op 80L)
HEAT_RATE_MIN_DELTA_C     = 1.0    # minimale temperaturestijging voor leermoment
HEAT_RATE_MIN_ON_S        = 300    # minimaal 5 min aan voor betrouwbaar leermoment

# ─── Temperatuurafhankelijke COP (HEAT_PUMP / HYBRID) ─────────────────────────
# cop = a×T² + b×T + c    (T = buitentemperature °C, default Daikin/Vaillant curve)
COP_A                     =  0.0008  # kwadratisch
COP_B                     =  0.08    # lineair
COP_C                     =  3.0     # constante (COP @ 0°C ≈ 3.0)
COP_DHW_FACTOR            =  0.70    # DHW heeft lagere COP dan ruimteverwarming
COP_MIN                   =  1.2     # minimale COP (ijzig weer)
COP_MAX                   =  6.0     # maximale COP (warm weer)

# ─── Kalkdetectie (limescale) ─────────────────────────────────────────────────
SCALE_WARN_PCT            = 60.0   # warning bij ≥60% kalkindex
SCALE_SCORE_FACTOR        = 200.0  # drop_frac → score: 50% daling = 100% score

# ─── Anode-slijtage ───────────────────────────────────────────────────────────
ANODE_DEFAULT_KWH         = 5000.0  # typische anode-levensduur (kWh doorvoer)
ANODE_WARN_PCT            = 80.0    # warning bij ≥80% van thresholdvalue
# Waterhardheid-factor: harder water → snellere slijtage
# 0-7°dH zacht=1.0, 7-14°dH matig=1.3, 14-21°dH hard=1.7, >21°dH zeer hard=2.2
ANODE_HARDNESS_FACTORS    = [(7, 1.0), (14, 1.3), (21, 1.7), (99, 2.2)]

# ─── Leerdata ────────────────────────────────────────────────────────────────
LEARN_FILE           = "/config/.storage/cloudems_boiler_learn.json"
DELIVERY_MIN_EVENTS  = 5
DELIVERY_CONFIDENCE  = 0.65
DELIVERY_DECAY_HOURS = 168

# ─── Seizoen ─────────────────────────────────────────────────────────────────
SEASON_SUMMER_C  = 15.0
SEASON_WINTER_C  = 8.0
SEASON_DELTA_C   = -5.0
SEASON_HYST_DAYS = 3

# ─── Thermisch verlies ────────────────────────────────────────────────────────
THERMAL_WINDOW_S  = 3600
THERMAL_MIN_DELTA = 0.3

# ─── Proportionele dimmer ─────────────────────────────────────────────────────
DIMMER_MIN_PCT  = 10.0
DIMMER_UPDATE_S = 30

# Demand-boost drempel grenzen (minuten)
DEMAND_BOOST_THRESHOLD_MIN_S = 45.0   # ondergrens bij goede leerdata
DEMAND_BOOST_THRESHOLD_MAX_S = 150.0  # bovengrens bij weinig leerdata
DEMAND_BOOST_RATIO_HIGH      = 0.75   # ratio ≥ dit → min drempel
DEMAND_BOOST_RATIO_LOW       = 0.40   # ratio ≤ dit → max drempel

# Hardware deadband fallback voor warmtepompen/hybrid (°C)
HP_HW_DEADBAND_DEFAULT_C = 2.0

# Fallback setpoints als geen boiler config beschikbaar
FALLBACK_SETPOINT_ON_C   = 60.0
FALLBACK_SETPOINT_OFF_C  = 40.0


@dataclass
class BoilerDecision:
    entity_id:     str
    label:         str
    action:        str
    reason:        str
    current_state: bool
    group_id:      str   = ""
    power_pct:     float = 0.0


@dataclass
class BoilerState:
    entity_id:           str
    label:               str
    phase:               str   = "L1"
    power_w:             float = 1000.0
    min_on_s:            float = DEFAULT_MIN_ON_MINUTES  * 60
    min_off_s:           float = DEFAULT_MIN_OFF_MINUTES * 60
    modes:               list  = field(default_factory=lambda: [
        MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE, MODE_PV_SURPLUS, MODE_EXPORT_REDUCE])
    cheap_hours_rank:    int   = 4
    temp_sensor:         str   = ""
    energy_sensor:       str   = ""
    flow_sensor:         str   = ""
    setpoint_c:          float = 60.0
    min_temp_c:          float = 40.0
    comfort_floor_c:     float = 50.0
    setpoint_summer_c:   float = 0.0
    setpoint_winter_c:   float = 0.0
    priority:            int   = 0
    last_on_ts:          float = 0.0
    last_off_ts:         float = 0.0
    current_temp_c:      Optional[float] = None
    _last_known_temp_c:  Optional[float] = None   # cache — nooit None na eerste succesvolle lezing
    current_power_w:     Optional[float] = None
    cycle_kwh:           float = 0.0
    active_setpoint_c:   float = 0.0
    is_delivery:         bool  = False
    outside_temp_c:      Optional[float] = None
    heat_demand_temp_c:  float = DEFAULT_HEAT_DEMAND_TEMP_C
    congestion_active:   bool  = False
    thermal_loss_c_h:    float = 0.0
    last_demand_ts:      float = 0.0
    stagger_ticks:       int   = 0
    control_mode:        str   = "switch"
    surplus_setpoint_c:  float = 75.0    # setpoint bij PV-surplus (setpoint_boost mode)
    # v4.6.507: communicatiestoring detectie — telt opeenvolgende turn_on zonder respons
    _no_response_count:  int   = 0       # hoe vaak turn_on gestuurd maar is_on bleef False
    _no_response_backoff_until: float = 0.0  # wait tot deze ts voor volgende attempt
    # v4.6.13: hardware_max_c — absolute bovengrens voor alle setpoints die naar de
    # hardware gestuurd worden. Voorkomt dat CloudEMS bijv. 78°C stuurt terwijl de boiler
    # maar 60°C aankan. 0.0 = niet ingesteld (systeem gebruikt SAFETY_MAX_C - 2.0 = 78°C).
    # Voor resistive boilers met een lager maximum: stel in op bijv. 60.0 of 65.0.
    # Voor heat_pump/hybrid: max_setpoint_boost_c heeft dezelfde rol en heeft priority.
    hardware_max_c:      float = 0.0
    # v4.6.405: tankvolume in liters. 0 = leer automatic via EMA op basis van kWh/°C.
    tank_liters:         float = 0.0
    _learned_tank_l:     float = 0.0   # learned via EMA — wordt gepersisteerd
    _cycle_start_temp_c: Optional[float] = None  # temp bij start verwarmingscycle
    _cycle_start_kwh:    float = 0.0             # kWh bij start verwarmingscycle
    preset_on:           str   = "boost"
    preset_off:          str   = "green"
    # v4.6.5: Ariston Lydos e.d. begrenzen setpoint per mode via een apart number-entity
    # (bijv. number.ariston_max_setpoint_temperature). In GREEN-mode is dit bijv. 53°C.
    # CloudEMS set dit entity op 75°C bij BOOST zodat het gewenste setpoint ook echt
    # ranget kan worden. Bij terugschakelen naar GREEN wordt het teruggeset op preset_off_max_c.
    max_setpoint_entity: str   = ""    # bijv. "number.ariston_max_setpoint_temperature"
    max_setpoint_boost_c: float = 75.0  # value die geset wordt bij BOOST
    max_setpoint_green_c: float = 53.0  # value die teruggeset wordt bij GREEN
    dimmer_on_pct:       float = 100.0
    dimmer_off_pct:      float = 0.0
    dimmer_proportional: bool  = False
    post_saldering_mode: bool  = False
    delta_t_optimize:    bool  = False
    # v4.5.86: boilertype + WP-boiler settings
    boiler_type:         str   = BOILER_TYPE_RESISTIVE  # resistive | heat_pump | hybrid | variable
    heat_up_hours:       float = 0.0    # verwachte opwarmtijd (u). 0=auto schatten.
                                         # heat_pump/hybrid: typisch 8-12u
                                         # resistive: typisch 1-3u, variable: n.v.t.
    boost_only_cheapest: int   = 2      # boost/100% alleen in de N goedkoopste uren
                                         # (0 = altijd boost toegestaan als want_on)
    has_gas_heating:     str   = ""    # CV-ketel aanwezig voor warm water?
                                         # ""    = niet configured (hint mogelijk)
                                         # "yes" = ja → gas-vs-current vergelijking active
                                         # "no"  = nee → hint nooit meer tonen
    # v4.5.90: temporary per evaluatieronde — True = gebruik preset_off (green/WP-element)
    #          False = gebruik preset_on (boost/weerstandselement)
    force_green:         bool  = False
    # v4.6.405: demand-boost feedback
    _demand_boost_ts:    float = 0.0   # timestamp van laatste demand-boost besluit
    _temp_before_demand: Optional[float] = None  # temp op moment van demand-boost
    # FIX 5: runtime-velden die voorheen via getattr(b, ..., default) werden gelezen
    _ramp_on_min_acc:    float = 0.0   # geaccumuleerde AAN-minuten voor volgende ramp-stap
    _prev_temp_for_dip:  Optional[float] = None  # vorige temp voor dip-detectie (geen flow sensor)
    # v4.6.403: gradueel setpoint voor hybrid bij goedkope current.
    # Stijgt in stappen van cheap_ramp_step_c wanneer current significant goedkoper is dan gas,
    # daalt terug naar max_setpoint_green_c als prijs normaal/duur wordt.
    # Voorkomt dat setpoint in één sprong naar 75°C gaat (veilig bij HA/internet uitval).
    _cheap_ramp_setpoint_c: float = 0.0   # 0.0 = niet geïnitialiseerd (wordt geset op green_max)
    cheap_ramp_step_c:      float = 5.0   # °C per stap omhoog
    cheap_ramp_max_c:       float = 65.0  # maximum via ramp (nooit hoger dan max_setpoint_boost_c)
    cheap_ramp_ratio:       float = 0.6   # current moet ≤ ratio × gas_th zijn om te rampen
    # Deprecated veld — gebruik boiler_type="heat_pump" of "hybrid"
    heat_pump_boiler:    bool  = False

    # ── v4.5.92: Gezondheids- en veiligheidsintelligentie ─────────────────────
    # Legionella
    water_hardness_dh:   float = 14.0   # waterhardheid in °dH (voor anode-slijtage)
    anode_threshold_kwh: float = ANODE_DEFAULT_KWH  # configureerbaar per boiler
    # Kalkdetectie: configureerbaar aan/uit
    limescale_detect:    bool  = True
    # COP-curve overschrijving (None = gebruik default parabool)
    cop_curve_override:  Optional[dict] = None  # {temp_c: cop, ...} interpolatietabel

    _temp_history:       list  = field(default_factory=list, repr=False)
    _power_history:      list  = field(default_factory=list, repr=False)
    _energy_kwh_last:    Optional[float] = field(default=None, repr=False)
    _energy_ts_last:     Optional[float] = field(default=None, repr=False)
    _dimmer_last_pct:    float = field(default=0.0, repr=False)
    _dimmer_last_ts:     float = field(default=0.0, repr=False)

    # ── v4.6.12: Hardware deadband compensatie + stall detectie ──────────────
    # Ariston WP-boilers starten pas als de watertemperature ver genoeg onder het
    # ingestelde setpoint zakt (interne hardware deadband van de boiler zelf).
    # hardware_deadband_c wordt bij het verzonden setpoint opgeteld zodat de
    # hardware-trigger eerder afgaat. Value 0.0 = automatic:
    #   heat_pump / hybrid → 2.0°C   resistive / variable → 0.0°C
    hardware_deadband_c: float = 0.0
    # Stall-detectie: als de boiler stall_timeout_s lang 0W trekt terwijl hij
    # aan hoort te staan, wordt het setpoint temporary met stall_boost_c verhoogd
    # om de interne hardware-deadband te doorbreken.
    stall_boost_c:       float = 5.0    # temporarye setpoint-boost bij stall (°C)
    stall_timeout_s:     float = 300.0  # seconden 0W + want_on voor stall-detectie

    _stall_start_ts:     float = field(default=0.0,   repr=False)
    _stall_active:       bool  = field(default=False,  repr=False)
    # v4.6.26: gebruiker kan BOOST pauzeren via virtual_boiler UI ("auto" kiezen)
    _boost_paused_until: float = field(default=0.0,   repr=False)
    # v4.6.42: manuale override — coordinator slaat setpoint-berekening over
    _manual_override_until: float = field(default=0.0, repr=False)
    # v4.6.52: gecachede max_setpoint_entity (voorkomt entity-registry scan elke 10s)
    _cached_max_setpoint_entity: str = field(default="", repr=False)
    _cached_power_entity: str = field(default="", repr=False)  # auto-detected power sensor

    # v4.6.60: Cloud verify/retry — Ariston cloud is onbetrouwbaar, settings komen
    # niet altijd aan. Na elke send slaan we het gewenste doel op en controleren
    # periodiek of de echte state overeen komt. Zo niet → retry (max 4x, backoff).
    _pending_preset:    str   = field(default="",  repr=False)  # gewenste operation_mode
    _imemory_since:     float = field(default=0.0, repr=False)  # timestamp when iMemory first detected
    _pending_setpoint:  float = field(default=0.0, repr=False)  # gewenste temperature
    _pending_max_sp:    float = field(default=0.0, repr=False)  # gewenste max_setpoint
    _pending_since:     float = field(default=0.0, repr=False)  # timestamp van laatste send
    _pending_retries:   int   = field(default=0,   repr=False)  # aantal retries gedaan
    _next_verify_ts:    float = field(default=0.0, repr=False)  # wanneer volgende verify
    _rate_limited_until:float = field(default=0.0, repr=False)  # 429-block tot ts

    # v4.6.557: Debounce voor preset-commando's (Ariston 429-preventie)
    # Gewenste preset wordt pas gestuurd als die ARISTON_CMD_DEBOUNCE_S stable is.
    # Het laatste gewenste commando wint altijd.
    _desired_preset:    str   = field(default="",  repr=False)  # gewenste preset (nog niet gestuurd)
    _desired_setpoint:  float = field(default=0.0, repr=False)  # gewenst setpoint (nog niet gestuurd)
    _desired_max_sp:    float = field(default=0.0, repr=False)  # gewenste max_sp (nog niet gestuurd)
    _desired_since:     float = field(default=0.0, repr=False)  # ts van eerste keer dat dit doel gezien werd
    # v4.6.557: Tijd in huidige werkelijke mode (voor display)
    _actual_preset:     str   = field(default="",  repr=False)  # laatste bekende werkelijke preset
    _actual_mode_since: float = field(default=0.0, repr=False)  # ts waarop werkelijke mode veranderde

    # ── v4.5.125: ACRouter (RobotDyn DimmerLink) hardware-integratie ──────────
    # Configuratie: stel control_mode="acrouter" + acrouter_host="192.168.x.x" in.
    # power_w blijft het nominale power van het weerstandselement (bijv. 2000).
    acrouter_host:       str   = ""     # IP-adres van het ACRouter device
    # v4.6.18: merk-identificatie (opgeslagen vanuit config_flow wizard)
    brand:               str   = ""     # bijv. "ariston_lydos_hybrid", "midea_e2", "unknown"
    # Interne state (niet in config):
    _acrouter_last_mode: int   = field(default=-1,  repr=False)  # -1 = unknown
    _acrouter_last_pct:  float = field(default=0.0, repr=False)
    _acrouter_last_ts:   float = field(default=0.0, repr=False)

    @property
    def hw_ceiling(self) -> float:
        """Absolute hardware-bovengrens voor setpoints (°C).

        Prioriteit:
          1. hardware_max_c als > 0 (expliciet ingesteld door gebruiker)
          2. max_setpoint_boost_c voor heat_pump/hybrid of preset-mode
             (preset-mode impliceert altijd een WP/hybrid boiler zoals Ariston Lydos)
          3. SAFETY_MAX_C - 2.0 als fallback (78°C)

        Gebruikt op alle plaatsen waar we een setpoint naar de hardware sturen.
        """
        if self.hardware_max_c > 0:
            return min(self.hardware_max_c, SAFETY_MAX_C - 1.0)
        # v4.6.16: max_setpoint_boost_c altijd als ceiling gebruiken als het configured is,
        # ook voor resistive/switch boilers (bijv. Midea E2 max 75°C).
        # Voorheen alleen voor heat_pump/hybrid/preset → resistive viel terug op 78°C fallback.
        if self.max_setpoint_boost_c > 0:
            return min(self.max_setpoint_boost_c, SAFETY_MAX_C - 1.0)
        return SAFETY_MAX_C - 2.0  # default 78°C (softwareveiligheidsgrens)

    @property
    def needs_heat(self) -> bool:
        """True als de boiler verwarming nodig heeft t.o.v. het actieve setpoint.

        Zonder temperatuursensor (current_temp_c is None): altijd True zodat
        triggers (PV-surplus, goedkope uren) de boiler kunnen aansturen.
        """
        if self.current_temp_c is None:
            return True   # geen sensor → vertrouw op triggers
        sp = self.active_setpoint_c or self.setpoint_c
        return self.current_temp_c <= (sp - HYSTERESIS_C)

    @property
    def temp_deficit_c(self) -> float:
        sp = self.active_setpoint_c or self.setpoint_c
        if self.current_temp_c is None:
            return 0.0
        return max(0.0, sp - self.current_temp_c)

    @property
    def _effective_tank_liters(self) -> float:
        """Gebruik geconfigureerd tankvolume, anders geleerd, anders standaard 80L."""
        if self.tank_liters > 0:
            return self.tank_liters
        if self._learned_tank_l > 20:
            return self._learned_tank_l
        return 80.0  # veilige fallback

    @property
    def shower_minutes_available(self) -> Optional[float]:
        """
        Bereken hoeveel minuten douchen beschikbaar is met het huidige warme water.

        Formule: bruikbare energie = tank_vol × 4186 × (T_boiler - T_douche)
                 benodigde energie per minuut = flow_l_min × 4186 × (T_douche - T_koud)
                 minuten = bruikbaar / per_minuut

        Standaard waarden:
          T_douche  = 38°C, T_koud = 10°C, flow = 8 L/min (gemiddelde douchekop)
        """
        if self.current_temp_c is None:
            return None
        t_boiler = self.current_temp_c
        t_shower = 38.0
        t_cold   = 10.0
        flow_l_min = 8.0   # L/min gemiddelde douchekop
        tank_l   = self._effective_tank_liters

        if t_boiler <= t_shower:
            return 0.0  # water is al te koud voor douchen

        # Energie beschikbaar boven douchetemperatuur (J)
        energy_avail = tank_l * 4186 * (t_boiler - t_shower)
        # Energie per minuut nodig om koud water op te warmen naar douchetemperatuur
        energy_per_min = flow_l_min * 4186 * (t_shower - t_cold)

        if energy_per_min <= 0:
            return None
        return round(energy_avail / energy_per_min, 1)

    @property
    def minutes_to_setpoint(self) -> Optional[float]:
        if self.current_temp_c is None or self.temp_deficit_c <= 0:
            return 0.0
        if self.power_w <= 0:
            return None
        # FIX 3: gebruik configured of learned tankvolume ipv hardcoded 50L
        # Q = m * c * ΔT, c_water = 0.001163 kWh/(kg·°C), 1L water ≈ 1kg
        kwh_needed = self.temp_deficit_c * self._effective_tank_liters * 0.001163
        return (kwh_needed / (self.power_w / 1000.0)) * 60


@dataclass
class CascadeGroup:
    id:              str
    name:            str
    mode:            str               = CASCADE_AUTO
    boilers:         list[BoilerState] = field(default_factory=list)
    stagger_delay_s: float             = STAGGER_DEFAULT_S
    learner:         Optional[object]  = field(default=None, repr=False)

    @property
    def total_power_w(self) -> float:
        return sum(b.power_w for b in self.boilers)

    @property
    def avg_temp_c(self) -> Optional[float]:
        temps = [b.current_temp_c for b in self.boilers if b.current_temp_c is not None]
        return round(sum(temps) / len(temps), 1) if temps else None

    def get_sequential_order(self) -> list[BoilerState]:
        delivery_eid = self.learner.get_delivery_entity(self.boilers) if self.learner else None

        def sort_key(b: BoilerState):
            is_delivery = (b.entity_id == delivery_eid) if delivery_eid else False
            return (0 if is_delivery else 1, b.priority, -(b.current_temp_c or 0))

        return sorted(self.boilers, key=sort_key)


# ─── BoilerLearner ────────────────────────────────────────────────────────────

class BoilerLearner:
    """
    Persistent leergeheugen voor één cascade-groep.
    Bevat: leveringsboiler-detectie, gebruikspatroon per uur,
    thermisch verlies per boiler, seizoensstatus, cycle_kwh.
    """

    def __init__(self, group_id: str, hass=None) -> None:
        self._gid  = group_id
        self._hass = hass
        self._data: dict = {}
        # Sync load via executor om blocking I/O in event loop te vermijden
        if hass:
            try:
                loop = hass.loop
                if loop and loop.is_running():
                    loop.run_in_executor(None, self._load)
                else:
                    self._load()
            except Exception:
                self._load()
        else:
            self._load()

    def _load(self) -> None:
        """Sync load — altijd via executor aanroepen vanuit event loop."""
        try:
            if os.path.exists(LEARN_FILE):
                with open(LEARN_FILE) as f:
                    self._data = json.load(f)
        except Exception as exc:
            _LOGGER.warning("BoilerLearner: load fout: %s", exc)
            self._data = {}

    def _save(self) -> None:
        """Save via executor als hass beschikbaar, anders direct (alleen bij opstarten)."""
        if self._hass is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, self._save_sync)
                return
            except RuntimeError:
                pass
        self._save_sync()

    def _save_sync(self) -> None:
        try:
            os.makedirs(os.path.dirname(LEARN_FILE), exist_ok=True)
            with open(LEARN_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            _LOGGER.warning("BoilerLearner: save fout: %s", exc)

    def _g(self) -> dict:
        return self._data.setdefault(self._gid, {})

    # ── 1. Leveringsboiler ────────────────────────────────────────────────────

    def record_cycle_start(self, boilers: list) -> None:
        now = time.time()
        temp_cands = [b for b in boilers if b.current_temp_c is not None and b.needs_heat]
        if temp_cands:
            winner = max(temp_cands, key=lambda b: b.temp_deficit_c)
            score  = winner.temp_deficit_c
            method = "temp"
        else:
            kwh_cands = [b for b in boilers if b.cycle_kwh > 0.05]
            if not kwh_cands:
                return
            winner = max(kwh_cands, key=lambda b: b.cycle_kwh)
            score  = winner.cycle_kwh * 10.0
            method = "energy"

        events  = self._g().setdefault("delivery_events", {})
        eid_evs = events.setdefault(winner.entity_id, [])
        eid_evs.append({"ts": now, "score": score, "method": method})
        events[winner.entity_id] = eid_evs[-200:]
        _LOGGER.debug("BoilerLearner [%s]: cyclus → %s (%.2f, %s)", self._gid, winner.label, score, method)

        kwh_store = self._g().setdefault("cycle_kwh", {})
        for b in boilers:
            kwh_store[b.entity_id] = 0.0
            b.cycle_kwh = 0.0
        self._save()

    def restore_cycle_kwh(self, boilers: list) -> None:
        store = self._g().get("cycle_kwh", {})
        for b in boilers:
            b.cycle_kwh = float(store.get(b.entity_id, 0.0))

    def update_cycle_kwh(self, boilers: list) -> None:
        store   = self._g().setdefault("cycle_kwh", {})
        changed = False
        for b in boilers:
            old = store.get(b.entity_id, 0.0)
            if abs(b.cycle_kwh - old) > 0.005:
                store[b.entity_id] = round(b.cycle_kwh, 4)
                changed = True
        if changed:
            self._save()

    def get_delivery_entity(self, boilers: list) -> Optional[str]:
        events = self._g().get("delivery_events", {})
        if not events:
            return None
        now     = time.time()
        decay_s = DELIVERY_DECAY_HOURS * 3600
        eids    = [b.entity_id for b in boilers]
        weighted: dict[str, float] = {}
        total_w = 0.0
        for eid in eids:
            w = sum(e.get("score", 1.0) * (0.5 ** ((now - e["ts"]) / decay_s))
                    for e in events.get(eid, []))
            weighted[eid] = w
            total_w += w
        if total_w < 1e-6:
            return None
        if sum(len(events.get(eid, [])) for eid in eids) < DELIVERY_MIN_EVENTS:
            return None
        best = max(weighted, key=weighted.__getitem__)
        return best if weighted[best] / total_w >= DELIVERY_CONFIDENCE else None

    # ── 2. Gebruikspatroon per uur + dag van de week ──────────────────────────

    def record_demand(self, hour: int) -> None:
        """Registreer warm-water gebruik: globaal patroon + dag-van-de-week matrix."""
        # Globaal 24-uurs patroon (achterwaarts compatibel)
        pattern = self._g().setdefault("usage_pattern", [0.0] * 24)
        pattern[hour] = pattern[hour] * 0.85 + 0.15
        self._g()["usage_pattern"] = pattern

        # Dag-van-de-week matrix: 7 × 24, index 0 = maandag
        weekday = datetime.now().weekday()
        dow = self._g().setdefault("usage_pattern_dow", [[0.0] * 24 for _ in range(7)])
        dow[weekday][hour] = dow[weekday][hour] * 0.90 + 0.10
        self._g()["usage_pattern_dow"] = dow

        # Anomalie-teller: cycli per dag
        today_key = datetime.now().strftime("%Y-%m-%d")
        anomaly   = self._g().setdefault("anomaly", {"date": today_key, "count": 0, "alerted": False})
        if anomaly["date"] != today_key:
            anomaly = {"date": today_key, "count": 0, "alerted": False}
        anomaly["count"] += 1
        self._g()["anomaly"] = anomaly
        self._save()

    def get_usage_pattern(self) -> list:
        return self._g().get("usage_pattern", [0.0] * 24)

    def get_usage_pattern_dow(self) -> list:
        """7 × 24 matrix: dow[weekdag][uur]."""
        return self._g().get("usage_pattern_dow", [[0.0] * 24 for _ in range(7)])

    def should_preheat(self, hour_now: int, minutes_to_setpoint: Optional[float]) -> bool:
        """Controleer of preventief opwarmen nodig is op basis van dag+uur patroon."""
        if minutes_to_setpoint is None or minutes_to_setpoint <= 0:
            return False
        lookahead = max(1, int(minutes_to_setpoint / 60) + 1)

        # Dag-van-de-week patroon heeft priority als er voldoende data is
        dow     = self.get_usage_pattern_dow()
        weekday = datetime.now().weekday()
        day_pat = dow[weekday]
        day_sum = sum(day_pat)
        if day_sum > 0.5:
            future = sum(day_pat[(hour_now + i) % 24] for i in range(1, lookahead + 1))
            avg    = day_sum / 24
            if future > max(0.15, avg * 1.4):
                _LOGGER.debug("BoilerLearner [%s]: preheat via dag-%d patroon", self._gid, weekday)
                return True

        # Fallback: globaal 24-uurs patroon
        pattern       = self.get_usage_pattern()
        future_demand = sum(pattern[(hour_now + i) % 24] for i in range(1, lookahead + 1))
        avg_demand    = sum(pattern) / 24 if any(pattern) else 0.0
        return future_demand > max(0.2, avg_demand * 1.5)

    def optimal_start_before_minutes(self, hour_target: int, minutes_to_setpoint: float) -> float:
        """
        Bereken hoeveel minuten vóór het verwachte piekuur gestart moet worden.
        Geeft 0 terug als er geen opwarmtijd nodig is.
        """
        if minutes_to_setpoint <= 0:
            return 0.0
        # Zoek het eerstvolgende piekuur op basis van dag-van-de-week patroon
        dow     = self.get_usage_pattern_dow()
        weekday = datetime.now().weekday()
        day_pat = dow[weekday]
        avg     = sum(day_pat) / 24 if any(day_pat) else 0.0
        # Vind de eerstvolgende piek na huidig uur
        for offset in range(1, 13):
            h = (hour_target + offset) % 24
            if day_pat[h] > max(0.15, avg * 1.4):
                # Start `minutes_to_setpoint` minuten vóór dat uur
                return max(0.0, offset * 60 - minutes_to_setpoint)
        return 0.0

    # ── Afwijkingsdetectie ────────────────────────────────────────────────────

    def check_anomaly(self, boilers: list) -> Optional[str]:
        """
        Detecteer ongewoon hoog verbruik (bijv. lekkage, logeerpartij).
        Geeft een notificatiebericht terug als er een anomalie is, anders None.
        """
        anom = self._g().get("anomaly", {})
        today_key = datetime.now().strftime("%Y-%m-%d")
        if anom.get("date") != today_key or anom.get("alerted"):
            return None

        count = anom.get("count", 0)
        # Calculate gemiddeld dagelijks consumption uit historische data
        dow      = self.get_usage_pattern_dow()
        weekday  = datetime.now().weekday()
        day_sum  = sum(dow[weekday])
        # Schat normaal aantal cycli: als day_sum > 0.5 dan hebben we data
        # Elke 0.1 eenheid ≈ 1 cycle; threshold bij 2.5× normaal
        normal_cycles = max(2.0, day_sum * 10)
        if count > normal_cycles * 2.5:
            # Markeer als gestuurd
            anom["alerted"] = True
            self._g()["anomaly"] = anom
            self._save()
            label_list = ", ".join(b.label for b in boilers)
            return (f"CloudEMS Boiler Cascade [{self._gid}]: ongewoon hoog verbruik vandaag — "
                    f"{int(count)} cycli (normaal ~{int(normal_cycles)}). "
                    f"Controleer boilers: {label_list}.")

    # ── 3. Thermisch verlies ──────────────────────────────────────────────────

    def update_thermal_loss(self, boiler: BoilerState) -> None:
        if boiler.current_temp_c is None:
            return
        now  = time.time()
        hist = boiler._temp_history
        hist.append((now, boiler.current_temp_c))
        boiler._temp_history = hist[-30:]
        # Sla ook vermogen op voor grafiek
        pw = boiler.current_power_w if boiler.current_power_w is not None else 0.0
        boiler._power_history = (boiler._power_history + [(now, pw)])[-48:]
        if len(hist) < 2:
            return
        dt_s    = hist[-1][0] - hist[0][0]
        delta_c = hist[0][1] - hist[-1][1]
        if dt_s < THERMAL_WINDOW_S * 0.5 or delta_c < THERMAL_MIN_DELTA:
            return
        boiler.thermal_loss_c_h = round(delta_c / (dt_s / 3600.0), 3)
        losses = self._g().setdefault("thermal_loss", {})
        losses[boiler.entity_id] = boiler.thermal_loss_c_h
        self._save()

    def restore_thermal_loss(self, boilers: list) -> None:
        losses = self._g().get("thermal_loss", {})
        for b in boilers:
            if b.entity_id in losses:
                b.thermal_loss_c_h = float(losses[b.entity_id])

    def time_until_cold(self, boiler: BoilerState) -> Optional[float]:
        if boiler.thermal_loss_c_h <= 0 or boiler.current_temp_c is None:
            return None
        margin = boiler.current_temp_c - boiler.comfort_floor_c
        return None if margin < 0 else (margin / boiler.thermal_loss_c_h) * 60.0

    # ── 3b. Boiler thermische kwaliteit + vervangingsadvies ─────────────────

    def boiler_thermal_quality(self, boiler) -> dict:
        """Bereken boilerkwaliteit en vervangingsadvies op basis van thermisch verlies.

        Methode:
          thermal_loss_c_h = gemeten afkoelsnelheid in °C/uur bij stand-by
          → kWh/dag verlies = (cap_L × verlies_c_h × 24) × 1.163 / 1000
          → jaarkosten verlies = kWh/dag × 365 × stroomprijs
          → terugverdientijd = (nieuwe_boiler_prijs - huidige_restwaarde) / jaarkosten

        Benchmark:
          Slechte boiler (jaren 80): 5-8 °C/uur verlies
          Gemiddeld (2000s):         2-4 °C/uur
          Modern A-label:            0.5-1.5 °C/uur
        """
        loss_c_h = getattr(boiler, "thermal_loss_c_h", 0.0)
        cap_l    = getattr(boiler, "tank_volume_l", None) or 80.0
        if loss_c_h <= 0:
            return {"status": "no_data",
                    "message": "Thermisch verlies nog niet gemeten (wacht op afkoelperiode)."}

        # kWh verlies per dag via stand-by verlies
        # q_kwh = cap_l × verlies_c × 1.163/1000  (1.163 = Wh/L/°C)
        daily_loss_kwh = round(cap_l * loss_c_h * 24 * 1.163 / 1000, 2)
        AVG_PRICE_EUR_KWH = 0.28
        annual_loss_eur  = round(daily_loss_kwh * 365 * AVG_PRICE_EUR_KWH, 1)

        # Benchmark score
        if loss_c_h < 1.5:
            grade, label = "A", "uitstekend"
        elif loss_c_h < 3.0:
            grade, label = "B", "goed"
        elif loss_c_h < 5.0:
            grade, label = "C", "matig"
        else:
            grade, label = "D", "slecht"

        result = {
            "status":            "ok" if grade in ("A", "B") else "suboptimal",
            "thermal_loss_c_h":  round(loss_c_h, 2),
            "daily_loss_kwh":    daily_loss_kwh,
            "annual_loss_eur":   annual_loss_eur,
            "grade":             grade,
            "label":             label,
            "tank_volume_l":     cap_l,
        }

        if grade in ("C", "D"):
            # Terugverdientijd bij vervanging door A-label
            MODERN_LOSS_C_H   = 1.0   # A-label boiler
            modern_daily_kwh  = cap_l * MODERN_LOSS_C_H * 24 * 1.163 / 1000
            saving_eur_year   = round((daily_loss_kwh - modern_daily_kwh) * 365 * AVG_PRICE_EUR_KWH, 1)
            NEW_BOILER_EUR    = 1200.0  # Inclusief installatie
            payback_years     = round(NEW_BOILER_EUR / saving_eur_year, 1) if saving_eur_year > 0 else None
            result["saving_eur_year"]   = saving_eur_year
            result["new_boiler_cost_eur"] = NEW_BOILER_EUR
            result["payback_years"]      = payback_years
            if payback_years and payback_years <= 8:
                result["recommend_replacement"] = True
                result["message"] = (
                    f"Boiler verliest {loss_c_h:.1f}°C/uur (label {grade} — {label}). "
                    f"Jaarlijkse standby-kosten: €{annual_loss_eur:.0f}. "
                    f"Een A-label boiler bespaart €{saving_eur_year:.0f}/jaar "
                    f"en verdient zich in ±{payback_years} jaar terug."
                )
            else:
                result["recommend_replacement"] = False
                result["message"] = (
                    f"Boiler verliest {loss_c_h:.1f}°C/uur (label {grade}). "
                    f"Vervanging verdient zich in {payback_years} jaar terug "
                    f"— wacht op einde technische levensduur."
                )
        else:
            result["message"] = (
                f"Boiler presteert goed: {loss_c_h:.1f}°C/uur verlies (label {grade})."
            )
            result["recommend_replacement"] = False

        return result

    # ── 4. Seizoenspatroon ────────────────────────────────────────────────────

    def update_season(self, outside_temp_c: Optional[float]) -> str:
        if outside_temp_c is None:
            return self.get_season()
        sd      = self._g().setdefault("season_data", {"season": "winter", "transition_days": 0, "last_ts": 0.0})
        now_day  = int(time.time() / 86400)
        last_day = int(sd.get("last_ts", 0) / 86400)
        current  = sd.get("season", "winter")
        if now_day != last_day:
            sd["last_ts"] = time.time()
            target = "summer" if outside_temp_c > SEASON_SUMMER_C else ("winter" if outside_temp_c < SEASON_WINTER_C else current)
            if target != current:
                sd["transition_days"] = sd.get("transition_days", 0) + 1
                if sd["transition_days"] >= SEASON_HYST_DAYS:
                    sd["season"] = target
                    sd["transition_days"] = 0
                    _LOGGER.info("BoilerLearner [%s]: seizoen → %s (%.1f°C)", self._gid, target, outside_temp_c)
            else:
                sd["transition_days"] = 0
            self._save()
        return sd.get("season", "winter")

    def get_season(self) -> str:
        return self._g().get("season_data", {}).get("season", "winter")

    # ── Status ────────────────────────────────────────────────────────────────

    def get_demand_boost_threshold_min(self) -> float:
        """
        Geleerde drempel (minuten) voor demand-boost.
        Start op 90 min. Pas aan op basis van correct/incorrect ratio:
          - ratio > 0.75 → drempel omlaag (boost vaker nuttig → eerder boosten)
          - ratio < 0.40 → drempel omhoog (boost vaak overbodig → minder snel boosten)
        Bereik: 45–150 minuten. Minimaal 10 metingen voor aanpassing.
        """
        stats = self._g().get("demand_boost_stats", {})
        correct   = int(stats.get("correct",   0))
        incorrect = int(stats.get("incorrect", 0))
        total = correct + incorrect
        if total < 10:
            return 90.0  # te weinig data — gebruik default
        ratio = correct / total
        # Lineaire mapping: ratio 0.40→0.75 returns threshold 150→45 min
        if ratio >= 0.75:
            threshold = DEMAND_BOOST_THRESHOLD_MIN_S
        elif ratio <= DEMAND_BOOST_RATIO_LOW:
            threshold = DEMAND_BOOST_THRESHOLD_MAX_S
        else:
            # Interpoleer
            threshold = DEMAND_BOOST_THRESHOLD_MAX_S - (ratio - DEMAND_BOOST_RATIO_LOW) / (DEMAND_BOOST_RATIO_HIGH - DEMAND_BOOST_RATIO_LOW) * (DEMAND_BOOST_THRESHOLD_MAX_S - DEMAND_BOOST_THRESHOLD_MIN_S)
        threshold = round(max(DEMAND_BOOST_THRESHOLD_MIN_S, min(DEMAND_BOOST_THRESHOLD_MAX_S, threshold)), 0)
        _LOGGER.debug(
            "BoilerLearner [%s]: demand_boost drempel %.0f min "
            "(correct=%d, incorrect=%d, ratio=%.2f)",
            self._gid, threshold, correct, incorrect, ratio,
        )
        return threshold

    def get_demand_boost_stats(self) -> dict:
        """Geef demand-boost statistieken terug voor de sensor."""
        stats = self._g().get("demand_boost_stats", {})
        correct   = int(stats.get("correct",   0))
        incorrect = int(stats.get("incorrect", 0))
        total = correct + incorrect
        return {
            "correct":   correct,
            "incorrect": incorrect,
            "total":     total,
            "ratio":     round(correct / total, 2) if total > 0 else None,
            "threshold_min": self.get_demand_boost_threshold_min(),
        }

    def get_learn_status(self, boilers: list) -> dict:
        events  = self._g().get("delivery_events", {})
        now     = time.time()
        decay_s = DELIVERY_DECAY_HOURS * 3600
        result: dict = {}
        total_w = 0.0
        for b in boilers:
            evs = events.get(b.entity_id, [])
            w   = sum(e.get("score", 1.0) * (0.5 ** ((now - e["ts"]) / decay_s)) for e in evs)
            result[b.entity_id] = {"label": b.label, "events": len(evs), "weight": round(w, 2),
                                   "loss_c_h": b.thermal_loss_c_h, "cycle_kwh": round(b.cycle_kwh, 3)}
            total_w += w
        if total_w > 0:
            for eid in result:
                result[eid]["confidence_pct"] = round(result[eid]["weight"] / total_w * 100, 1)
        return {
            "delivery_events":      result,
            "usage_pattern":        self.get_usage_pattern(),
            "usage_pattern_dow":    self.get_usage_pattern_dow(),
            "season":               self.get_season(),
            "total_events":         sum(r["events"] for r in result.values()),
            "anomaly":              self._g().get("anomaly", {}),
        }

    def reset(self) -> None:
        self._data.pop(self._gid, None)
        self._save()
        _LOGGER.info("BoilerLearner [%s]: leerdata gewist", self._gid)

    # ── 5. Learnede opwarmsnelheid (heat_rate) ────────────────────────────────

    def update_heat_rate(self, boiler: BoilerState, was_on_s: float) -> None:
        """
        Leer de opwarmsnelheid (°C/h) via EMA zodra de boiler warm genoeg gedraaid heeft.
        Wordt aangeroepen vanuit _read_sensors() als de boiler aan is en temp stijgt.
        """
        if boiler.current_temp_c is None or was_on_s < HEAT_RATE_MIN_ON_S:
            return
        hist = boiler._temp_history
        if len(hist) < 2:
            return
        # Gebruik eerste en laatste punt uit de huidige aan-periode
        dt_s    = hist[-1][0] - hist[0][0]
        delta_c = hist[-1][1] - hist[0][1]
        if dt_s < HEAT_RATE_MIN_ON_S or delta_c < HEAT_RATE_MIN_DELTA_C:
            return
        measured = delta_c / (dt_s / 3600.0)
        measured = max(HEAT_RATE_MIN_C_H, min(HEAT_RATE_MAX_C_H, measured))

        rates = self._g().setdefault("heat_rate", {})
        prev  = float(rates.get(boiler.entity_id, HEAT_RATE_INIT_C_H))
        new   = prev * (1 - HEAT_RATE_ALPHA) + measured * HEAT_RATE_ALPHA
        new   = round(new, 3)
        rates[boiler.entity_id] = new
        self._save()
        _LOGGER.debug("BoilerLearner [%s] %s: heat_rate %.2f→%.2f °C/h",
                      self._gid, boiler.label, prev, new)

    def get_heat_rate(self, boiler: BoilerState) -> float:
        """Geleerde opwarmsnelheid in °C/h. Fallback: HEAT_RATE_INIT_C_H."""
        return float(self._g().get("heat_rate", {}).get(boiler.entity_id, HEAT_RATE_INIT_C_H))

    def reheat_eta_min(self, boiler: BoilerState) -> float:
        """
        Minuten tot de boiler zijn setpoint-trigger bereikt als hij NIET verwarmt.
        Gebaseerd op geleerde passive_loss. 0 = al op temp of geen data.
        9999 = boiler verwarmt nu (ETA niet relevant).
        """
        if boiler.current_temp_c is None or boiler.thermal_loss_c_h <= 0:
            return 0.0
        trig       = (boiler.active_setpoint_c or boiler.setpoint_c) - HYSTERESIS_C
        deg_above  = boiler.current_temp_c - trig
        if deg_above <= 0:
            return 0.0   # al onder trigger → nu verwarming nodig
        return round((deg_above / boiler.thermal_loss_c_h) * 60.0, 1)

    def minutes_to_heat(self, boiler: BoilerState) -> Optional[float]:
        """
        Minuten die de boiler nodig heeft om van huidige temp naar setpoint te stijgen,
        gebaseerd op de geleerde opwarmsnelheid. None als geen data.
        """
        if boiler.current_temp_c is None:
            return None
        deficit = (boiler.active_setpoint_c or boiler.setpoint_c) - boiler.current_temp_c
        if deficit <= 0:
            return 0.0
        rate = self.get_heat_rate(boiler)
        if rate <= 0:
            return None
        return round((deficit / rate) * 60.0, 1)

    # ── 6. Legionella cycle ──────────────────────────────────────────────────

    def _leg_g(self, entity_id: str) -> dict:
        return self._g().setdefault("legionella", {}).setdefault(entity_id, {})

    def legionella_days_since(self, entity_id: str) -> Optional[float]:
        """Dagen geleden dat de legionella-cyclus voltooid werd. None als nooit."""
        ts = self._leg_g(entity_id).get("last_completed_ts")
        if not ts:
            return None
        return round((time.time() - float(ts)) / 86400.0, 1)

    def legionella_needed(self, entity_id: str) -> bool:
        """True als de cyclus langer dan LEGIONELLA_INTERVAL_DAYS geleden was."""
        days = self.legionella_days_since(entity_id)
        return days is None or days >= LEGIONELLA_INTERVAL_DAYS

    def legionella_register_boost_high(self, entity_id: str, temp_c: float, duration_s: float) -> bool:
        """
        FIX 3: Registreer een BOOST-cyclus die hoog genoeg was voor legionella.
        Als de boiler tijdens BOOST >= LEGIONELLA_TEMP_C bereikt voor voldoende tijd,
        telt dat als een geldige legionella-cyclus — voorkomt dubbele planning.
        Geeft True als cyclus hiermee als voltooid is geregistreerd.
        """
        if temp_c < LEGIONELLA_TEMP_C or duration_s < LEGIONELLA_CONFIRM_S:
            return False
        leg = self._leg_g(entity_id)
        last_ts = float(leg.get("last_completed_ts", 0))
        # Niet dubbel registreren binnen 12u
        if time.time() - last_ts < 43200:
            return False
        leg["last_completed_ts"] = time.time()
        leg["confirm_ticks"]     = 0
        leg["via_boost"]         = True
        self._g().setdefault("legionella", {})[entity_id] = leg
        self._save()
        _LOGGER.info(
            "BoilerLearner [%s] %s: legionella afgedekt via BOOST-cyclus (%.1f°C, %.0fs)",
            self._gid, entity_id, temp_c, duration_s,
        )
        return True

    def legionella_deadline(self, entity_id: str) -> bool:
        """True als de cyclus forceer-nodig is (LEGIONELLA_DEADLINE_DAYS overschreden)."""
        days = self.legionella_days_since(entity_id)
        return days is None or days >= LEGIONELLA_DEADLINE_DAYS

    def legionella_planned_hour(
        self,
        entity_id:     str,
        hourly_prices: list,
        tomorrow_prices: list | None = None,
        days_until_needed: int = 99,
    ) -> int:
        """
        FIX 5: Kies het beste uur voor de legionella-cyclus.

        Prioritering:
          1. Negatieve prijsuren (gratis/betaald krijgen) — altijd ideaal
          2. Nachtelijke uren (0-6) in top-N goedkoopst
          3. Goedkoopste uur van de dag ongeacht tijdstip

        Als legionella dringend nodig (≤2 dagen) en er zijn negatieve prijzen
        morgen maar niet vandaag → plan voor morgen en geef -1 terug als signaal.
        """
        leg   = self._leg_g(entity_id)
        today = datetime.now().strftime("%Y-%m-%d")
        if leg.get("plan_day") == today and leg.get("planned_hour", -1) >= 0:
            return int(leg["planned_hour"])

        if not hourly_prices:
            planned = 2  # fallback: 02:00
        else:
            # Stap 1: negatieve uren (prijs ≤ 0) — bij voorkeur nacht
            neg_hours = [h for h, p in enumerate(hourly_prices) if p <= 0.0]
            neg_night = [h for h in neg_hours if 0 <= h <= 6]
            if neg_night:
                planned = neg_night[0]
                _LOGGER.info("BoilerLearner [%s] %s: legionella op negatief-prijs uur %02d:00",
                             self._gid, entity_id, planned)
            elif neg_hours:
                planned = neg_hours[0]
                _LOGGER.info("BoilerLearner [%s] %s: legionella op negatief-prijs uur %02d:00 (niet nacht)",
                             self._gid, entity_id, planned)
            else:
                # Stap 2: goedkoopste N uren, voorkeur nacht
                ranked     = sorted(range(len(hourly_prices)), key=lambda i: hourly_prices[i])
                cheapest_n = ranked[:LEGIONELLA_PRICE_RANK]
                night      = [h for h in cheapest_n if 0 <= h <= 6]
                planned    = night[0] if night else cheapest_n[0]

                # Stap 3: als urgent (≤2 dagen) en morgen negatieve prijzen
                # → sla vandaag over, plan morgen (signaal via via_boost hint in status)
                if days_until_needed <= 2 and tomorrow_prices:
                    neg_tomorrow = [h for h, p in enumerate(tomorrow_prices) if p <= 0.0]
                    if neg_tomorrow and min(tomorrow_prices) < min(hourly_prices) * 0.5:
                        # Morgen significant goedkoper — sla over als er nog tijd is
                        leg["prefer_tomorrow"] = True
                        _LOGGER.info(
                            "BoilerLearner [%s] %s: legionella uitgesteld naar morgen "                            "(negatieve prijs uur %02d:00, urgent=%d dagen)",
                            self._gid, entity_id, neg_tomorrow[0], days_until_needed,
                        )
                    else:
                        leg["prefer_tomorrow"] = False

        leg["planned_hour"] = planned
        leg["plan_day"]     = today
        self._g().setdefault("legionella", {})[entity_id] = leg
        self._save()
        _LOGGER.debug("BoilerLearner [%s] %s: legionella gepland op %02d:00",
                      self._gid, entity_id, planned)
        return planned

    def legionella_tick(self, entity_id: str, current_temp_c: float) -> bool:
        """
        Registreer een seconde ≥ LEGIONELLA_TEMP_C. Geeft True als cyclus compleet.
        Cyclus is compleet na LEGIONELLA_CONFIRM_S aaneengesloten seconden op temp.
        """
        leg  = self._leg_g(entity_id)
        if current_temp_c >= LEGIONELLA_TEMP_C:
            ticks = leg.get("confirm_ticks", 0) + 1
            leg["confirm_ticks"] = ticks
            if ticks >= LEGIONELLA_CONFIRM_S:
                leg["last_completed_ts"] = time.time()
                leg["confirm_ticks"]     = 0
                self._g().setdefault("legionella", {})[entity_id] = leg
                self._save()
                _LOGGER.info("BoilerLearner [%s] %s: legionella-cyclus voltooid (%ds op %.1f°C)",
                             self._gid, entity_id, LEGIONELLA_CONFIRM_S, current_temp_c)
                return True
        else:
            # Temperatuur gedaald — reset teller (moet aaneengesloten zijn)
            leg["confirm_ticks"] = 0
        self._g().setdefault("legionella", {})[entity_id] = leg
        return False

    def get_legionella_status(self, entity_id: str) -> dict:
        leg = self._leg_g(entity_id)
        days = self.legionella_days_since(entity_id)
        # v4.6.438: build history lijst van voltooide cycli (laatste 49 = 7 weken)
        raw_hist = self._g().get("legionella_history", {}).get(entity_id, [])
        history = [{"date": h} for h in raw_hist[-49:]] if raw_hist else []
        return {
            "days_since":    days,
            "needed":        self.legionella_needed(entity_id),
            "deadline":      self.legionella_deadline(entity_id),
            "planned_hour":  leg.get("planned_hour", -1),
            "confirm_ticks": leg.get("confirm_ticks", 0),
            "confirm_pct":   round(leg.get("confirm_ticks", 0) / LEGIONELLA_CONFIRM_S * 100, 1),
            "via_boost":     bool(leg.get("via_boost", False)),
            "history":       history,
        }

    # ── 7. Kalkdetectie (limescale score) ────────────────────────────────────

    def update_scale_score(self, boiler: BoilerState) -> float:
        """
        Bereken kalkscore 0-100% op basis van de daling in opwarmsnelheid t.o.v. baseline.
        Baseline = eerste gemeten heat_rate nadat hij geleerd is.
        Score 0% = schoon, 100% = opwarmsnelheid gehalveerd (50% daling).
        """
        if not boiler.limescale_detect:
            return 0.0
        rates = self._g().get("heat_rate", {})
        current_rate = float(rates.get(boiler.entity_id, 0))
        if current_rate <= 0:
            return 0.0

        scale_data   = self._g().setdefault("scale", {}).setdefault(boiler.entity_id, {})
        baseline     = scale_data.get("baseline_rate", 0.0)

        if baseline <= 0 and current_rate > HEAT_RATE_MIN_C_H:
            # Sla eerste betrouwbare meting op als baseline
            scale_data["baseline_rate"] = current_rate
            self._g()["scale"][boiler.entity_id] = scale_data
            self._save()
            return 0.0

        if baseline <= 0:
            return 0.0

        drop_frac = max(0.0, (baseline - current_rate) / baseline)
        score     = min(100.0, drop_frac * SCALE_SCORE_FACTOR)
        scale_data["score"] = round(score, 1)
        self._g()["scale"][boiler.entity_id] = scale_data
        return round(score, 1)

    def get_scale_score(self, boiler: BoilerState) -> float:
        return float(self._g().get("scale", {}).get(boiler.entity_id, {}).get("score", 0.0))

    # ── 8. Anode-slijtage ────────────────────────────────────────────────────

    def update_anode_wear(self, boiler: BoilerState, delta_kwh: float) -> float:
        """
        Tel kWh doorvoer op, gewogen voor waterhardheid.
        Geeft slijtage-% terug (0-100). Waarschuwing bij >80%.
        """
        if delta_kwh <= 0:
            return 0.0
        hardness_factor = _anode_hardness_factor(boiler.water_hardness_dh)
        weighted_kwh    = delta_kwh * hardness_factor

        anode = self._g().setdefault("anode", {}).setdefault(boiler.entity_id, {"kwh": 0.0})
        anode["kwh"] = round(anode["kwh"] + weighted_kwh, 3)
        self._g()["anode"][boiler.entity_id] = anode
        self._save()

        thr = boiler.anode_threshold_kwh or ANODE_DEFAULT_KWH
        return round(min(100.0, anode["kwh"] / thr * 100.0), 1)

    def get_anode_wear_pct(self, boiler: BoilerState) -> float:
        kwh = float(self._g().get("anode", {}).get(boiler.entity_id, {}).get("kwh", 0.0))
        thr = boiler.anode_threshold_kwh or ANODE_DEFAULT_KWH
        return round(min(100.0, kwh / thr * 100.0), 1)

    def get_anode_kwh(self, boiler: BoilerState) -> float:
        return float(self._g().get("anode", {}).get(boiler.entity_id, {}).get("kwh", 0.0))


# ─── Vrije helperfuncties ─────────────────────────────────────────────────────

def _cop_from_temp(outside_temp_c: Optional[float], cop_curve: Optional[dict] = None) -> float:
    """
    Bereken COP op basis van buitentemperatuur.
    Gebruikt de geleerde curve als beschikbaar, anders de standaard parabool.
    DHW-correctie wordt NIET hier toegepast — doe dat apart met × COP_DHW_FACTOR.
    """
    if outside_temp_c is None:
        outside_temp_c = 7.0  # Europees gemiddeld ontwerppunt

    if cop_curve and len(cop_curve) >= 2:
        temps = sorted(cop_curve.keys())
        cops  = [cop_curve[t] for t in temps]
        if outside_temp_c <= temps[0]:
            return max(COP_MIN, cops[0])
        if outside_temp_c >= temps[-1]:
            return min(COP_MAX, cops[-1])
        for i in range(len(temps) - 1):
            if temps[i] <= outside_temp_c <= temps[i + 1]:
                frac = (outside_temp_c - temps[i]) / (temps[i + 1] - temps[i])
                return round(max(COP_MIN, min(COP_MAX, cops[i] + frac * (cops[i + 1] - cops[i]))), 2)

    cop = COP_A * outside_temp_c ** 2 + COP_B * outside_temp_c + COP_C
    return round(max(COP_MIN, min(COP_MAX, cop)), 2)


def _anode_hardness_factor(hardness_dh: float) -> float:
    """Waterhardheid-factor voor anode-slijtage: harder water → sneller verbruik."""
    for threshold, factor in ANODE_HARDNESS_FACTORS:
        if hardness_dh <= threshold:
            return factor
    return ANODE_HARDNESS_FACTORS[-1][1]


# ─── BoilerController ─────────────────────────────────────────────────────────

class BoilerController:
    """CloudEMS boiler/stopcontact controller v3.1."""

    def __init__(self, hass: HomeAssistant, boiler_configs: list[dict]) -> None:
        self._hass    = hass
        self._boilers: list[BoilerState]  = []
        self._groups:  list[CascadeGroup] = []
        self._p1_surplus_w: float = 0.0
        self._p1_last_ts:   float = 0.0
        self._weekly_kwh:   dict  = {}  # entity_id → {week_key: kwh}
        for cfg in boiler_configs:
            # Groep-dict heeft "units" (lijst van boilers) en optional "id"/"name"
            # Enkelvoudige boiler-dict heeft "entity_id" direct
            if cfg.get("units") is not None or cfg.get("group"):
                self._groups.append(self._build_group(cfg))
            elif cfg.get("entity_id"):
                self._boilers.append(self._build_boiler(cfg))
            else:
                _LOGGER.warning(
                    "BoilerController: onbekende config-structuur overgeslagen: %s",
                    list(cfg.keys())[:6]
                )
        _LOGGER.info("BoilerController v3.1: %d enkelvoudig + %d cascade (%d groepen)",
                     len(self._boilers), sum(len(g.boilers) for g in self._groups), len(self._groups))
        self._power_store = Store(hass, 1, "cloudems_boiler_learned_power_v1")
        self._power_dirty = False
        self._power_last_save = 0.0
        # v4.6.125: persisteer laatste bekende temp per boiler — overleeft restart + Ariston 429
        self._temp_store  = Store(hass, 1, "cloudems_boiler_last_temp_v1")
        self._ramp_store  = Store(hass, 1, "cloudems_boiler_ramp_state_v1")
        self._ramp_min_on_per_step: float = 30.0

        # v4.6.557: generieke command queue voor cloud-API rate-limiting
        # Ariston: max 6 calls/min, 10 min debounce om 429 te voorkomen
        # Debounce voorkomt dat elke 10s coordinator-cycle een API-aanroep doet.
        self._cmd_queue = CloudCommandQueue(
            api_key      = "ariston",
            debounce_s   = ARISTON_CMD_DEBOUNCE_S,
            rate_per_min = 6.0,
        )  # minuten AAN vereist voor +1 ramp-stap

    def _build_boiler(self, cfg: dict) -> BoilerState:
        # v4.6.16: brand-veld → auto-defaults voor bekende merken.
        # Valuen uit cfg hebben altijd priority; brand vult alleen gaps.
        _brand_defaults: dict = {}
        _brand = cfg.get("brand", "")
        if _brand:
            # Importeer de preset-tabel uit config_flow indien available,
            # anders gebruik ingebakken kopie voor de meest voorkomende merken.
            _BRAND_BUILTIN: dict[str, dict] = {
                "ariston_lydos_hybrid": {
                    "boiler_type": "hybrid", "control_mode": "preset",
                    "preset_on": "BOOST", "preset_off": "GREEN",
                    "max_setpoint_boost_c": 75.0, "max_setpoint_green_c": 53.0,
                    "hardware_max_c": 75.0, "surplus_setpoint_c": 75.0,
                    "hardware_deadband_c": 2.0, "stall_timeout_s": 300.0, "stall_boost_c": 5.0,
                },
                "ariston_velis_evo": {
                    "boiler_type": "resistive", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 80.0, "hardware_max_c": 80.0,
                    "surplus_setpoint_c": 80.0,
                },
                "ariston_andris": {
                    "boiler_type": "resistive", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 75.0, "hardware_max_c": 75.0,
                    "surplus_setpoint_c": 75.0,
                },
                "midea_e2": {
                    "boiler_type": "resistive", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 75.0, "hardware_max_c": 75.0,
                    "surplus_setpoint_c": 75.0,
                },
                "midea_e3": {
                    "boiler_type": "resistive", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 65.0, "hardware_max_c": 65.0,
                    "surplus_setpoint_c": 65.0,
                },
                "daikin_altherma_dhw": {
                    "boiler_type": "heat_pump", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 60.0, "hardware_max_c": 60.0,
                    "surplus_setpoint_c": 60.0, "hardware_deadband_c": 3.0,
                },
                "vaillant_unistor": {
                    "boiler_type": "heat_pump", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 65.0, "hardware_max_c": 65.0,
                    "surplus_setpoint_c": 65.0, "hardware_deadband_c": 3.0,
                },
                "stiebel_wwk": {
                    "boiler_type": "heat_pump", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 65.0, "hardware_max_c": 65.0,
                    "surplus_setpoint_c": 65.0, "hardware_deadband_c": 2.0,
                },
                "aosmith_electric": {
                    "boiler_type": "resistive", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 60.0, "hardware_max_c": 60.0,
                    "surplus_setpoint_c": 60.0,
                },
                "itho_heatpump": {
                    "boiler_type": "heat_pump", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 60.0, "hardware_max_c": 60.0,
                    "surplus_setpoint_c": 60.0, "hardware_deadband_c": 3.0,
                },
                "generic_heatpump": {
                    "boiler_type": "heat_pump", "control_mode": "setpoint",
                    "max_setpoint_boost_c": 60.0, "hardware_max_c": 60.0,
                    "surplus_setpoint_c": 60.0, "hardware_deadband_c": 2.0,
                },
            }
            _brand_defaults = _BRAND_BUILTIN.get(_brand, {})
            if _brand_defaults:
                _LOGGER.debug("BoilerController: merk '%s' → auto-defaults toegepast", _brand)

        # v4.6.22: voor bekende merken zijn sturingsvelden vergrendeld op het preset-value.
        # Dit voorkomt dat een oude opgeslagen config (bijv. control_mode="setpoint") de
        # brand-specifieke instelling (bijv. control_mode="preset" voor Ariston Lydos Hybrid)
        # blijft overschrijven na een merk-selectie.
        _BRAND_LOCKED_KEYS = {"control_mode", "preset_on", "preset_off", "boiler_type"}
        _known_brand = bool(_brand_defaults)

        def _g(key, fallback):
            """Brand-locked keys komen altijd uit brand-defaults voor bekende merken.
            Overige keys: cfg heeft prioriteit, dan brand-default, dan fallback."""
            if _known_brand and key in _BRAND_LOCKED_KEYS and key in _brand_defaults:
                return _brand_defaults[key]
            if key in cfg:
                return cfg[key]
            if key in _brand_defaults:
                return _brand_defaults[key]
            return fallback

        return BoilerState(
            entity_id          = cfg["entity_id"],
            label              = cfg.get("label", cfg["entity_id"]),
            phase              = cfg.get("phase", "L1"),
            power_w            = float(cfg.get("power_w", 1000.0)),
            min_on_s           = float(cfg.get("min_on_minutes",  DEFAULT_MIN_ON_MINUTES))  * 60,
            min_off_s          = float(cfg.get("min_off_minutes", DEFAULT_MIN_OFF_MINUTES)) * 60,
            modes              = cfg.get("modes", [MODE_CHEAP_HOURS, MODE_NEGATIVE_PRICE, MODE_PV_SURPLUS, MODE_EXPORT_REDUCE]),
            cheap_hours_rank   = int(cfg.get("cheap_hours_rank", 4)),
            temp_sensor        = cfg.get("temp_sensor", ""),
            energy_sensor      = cfg.get("energy_sensor", ""),
            flow_sensor        = cfg.get("flow_sensor", ""),
            setpoint_c         = float(_g("setpoint_c",         60.0)),
            min_temp_c         = float(_g("min_temp_c",         40.0)),
            comfort_floor_c    = float(cfg.get("comfort_floor_c", 50.0)),
            setpoint_summer_c  = float(cfg.get("setpoint_summer_c", 0.0)),
            setpoint_winter_c  = float(cfg.get("setpoint_winter_c", 0.0)),
            priority           = int(cfg.get("priority", 0)),
            control_mode       = _g("control_mode",       "switch"),
            surplus_setpoint_c = float(_g("surplus_setpoint_c", 75.0)),
            preset_on          = _g("preset_on",           "boost"),
            preset_off         = _g("preset_off",          "green"),
            max_setpoint_entity  = cfg.get("max_setpoint_entity", ""),
            max_setpoint_boost_c = float(_g("max_setpoint_boost_c", 75.0)),
            max_setpoint_green_c = float(_g("max_setpoint_green_c", 53.0)),
            dimmer_on_pct      = float(cfg.get("dimmer_on_pct",  100.0)),
            dimmer_off_pct      = float(cfg.get("dimmer_off_pct", 0.0)),
            dimmer_proportional = bool(cfg.get("dimmer_proportional", False)),
            post_saldering_mode = bool(cfg.get("post_saldering_mode", False)),
            delta_t_optimize    = bool(cfg.get("delta_t_optimize", False)),
            boiler_type         = _g("boiler_type",        BOILER_TYPE_RESISTIVE),
            heat_up_hours       = float(cfg.get("heat_up_hours", 0.0)),
            boost_only_cheapest = int(cfg.get("boost_only_cheapest", 2)),
            has_gas_heating     = str(cfg.get("has_gas_heating", "")),
            heat_pump_boiler    = bool(cfg.get("heat_pump_boiler", False)),
            water_hardness_dh   = float(cfg.get("water_hardness_dh", 14.0)),
            anode_threshold_kwh = float(cfg.get("anode_threshold_kwh", ANODE_DEFAULT_KWH)),
            limescale_detect    = bool(cfg.get("limescale_detect", True)),
            cop_curve_override  = cfg.get("cop_curve_override", None),
            acrouter_host       = cfg.get("acrouter_host", ""),
            brand               = cfg.get("brand", ""),
            hardware_deadband_c = float(_g("hardware_deadband_c", 0.0)),
            stall_boost_c       = float(_g("stall_boost_c",       5.0)),
            stall_timeout_s     = float(_g("stall_timeout_s",     300.0)),
            hardware_max_c      = float(_g("hardware_max_c",      0.0)),
        )

    def _build_group(self, cfg: dict) -> CascadeGroup:
        group_id = cfg.get("id", "group")
        learner  = BoilerLearner(group_id, hass=self._hass)
        raw_units = cfg.get("units", [])
        skipped = [u for u in raw_units if not u.get("entity_id")]
        if skipped:
            _LOGGER.warning(
                "BoilerController: %d unit(s) in groep '%s' overgeslagen — entity_id ontbreekt. "                "Controleer de boiler-configuratie.",
                len(skipped), cfg.get("name", "?")
            )
        boilers  = [self._build_boiler(u) for u in raw_units if u.get("entity_id")]
        learner.restore_cycle_kwh(boilers)
        learner.restore_thermal_loss(boilers)
        return CascadeGroup(
            id              = group_id,
            name            = cfg.get("name", "Cascade groep"),
            mode            = cfg.get("mode", CASCADE_AUTO),
            boilers         = boilers,
            stagger_delay_s = float(cfg.get("stagger_delay_s", STAGGER_DEFAULT_S)),
            learner         = learner,
        )

    async def async_setup(self) -> None:
        """Laad eerder geleerde vermogens uit opslag."""
        import time as _time
        saved = await self._power_store.async_load() or {}
        # Herstel temp/power histories
        for b in list(self._boilers) + [bb for g in self._groups for bb in g.boilers]:
            th = saved.get("_temp_hist_" + b.entity_id)
            ph = saved.get("_pow_hist_"  + b.entity_id)
            if isinstance(th, list): b._temp_history  = th
            if isinstance(ph, list): b._power_history = ph

        # Laad persistente temp cache — restore last_known_temp_c voor alle boilers
        _saved_temps = await self._temp_store.async_load() or {}
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            _t = _saved_temps.get(b.entity_id)
            if _t is not None:
                try:
                    _tv = float(_t)
                    if 5.0 <= _tv <= 95.0:
                        b._last_known_temp_c = _tv
                        b.current_temp_c = _tv
                except (ValueError, TypeError):
                    pass
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            stored_w = saved.get(b.entity_id)
            if stored_w and float(stored_w) > 50:
                b.power_w = float(stored_w)
                _LOGGER.debug(
                    "BoilerController: geleerd vermogen hersteld voor %s: %.0fW",
                    b.label, b.power_w,
                )
        if saved:
            _LOGGER.info("BoilerController: vermogensgeheugen geladen (%d boilers)", len(saved))

        # FIX 5: restore ramp-setpoints na restart
        # FIX 3: restore learnede tankvolumes na restart
        _saved_ramp = await self._ramp_store.async_load() or {}
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            # v4.6.507: altijd initialiseren voor hybrid — ook als er geen opgeslagen data is.
            # Zonder dit blijft _cheap_ramp_setpoint_c=0 als PV-surplus de eerste trigger is,
            # waardoor de ramp-check faalt en direct 75°C verstuurd wordt.
            if b.boiler_type == BOILER_TYPE_HYBRID and b._cheap_ramp_setpoint_c <= 0:
                _green_init = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                b._cheap_ramp_setpoint_c = _green_init
                _LOGGER.info(
                    "BoilerController [%s]: ramp geïnitialiseerd op %.0f°C (green_base)",
                    b.label, _green_init,
                )
            _ramp_data = _saved_ramp.get(b.entity_id, {})
            if _ramp_data:
                _green_base = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                _saved_sp   = float(_ramp_data.get("ramp_setpoint_c", _green_base))
                # v4.6.425: bij restart altijd starten op green_base, ongeacht het opgeslagen
                # ramp-setpoint. De watertemperature staat na een restart nog op de werkelijke
                # boilertemperature — als we direct naar 75°C zouden springen terwijl het water
                # op 53°C staat, verwarmt de boiler door bij verbindingsverlies of crash.
                # Gebruik het opgeslagen setpoint alleen als de watertemp er al dichtbij zit (< 5°C).
                _current_temp = getattr(b, "current_temp_c", None) or _green_base
                _temp_margin  = 5.0  # °C — als water al binnen dit range zit, restore opgeslagen sp
                if _saved_sp > _green_base and _current_temp < (_saved_sp - _temp_margin):
                    # Water is ver van het opgeslagen setpoint → start veilig op green_base
                    b._cheap_ramp_setpoint_c = _green_base
                    _LOGGER.info(
                        "BoilerController [%s]: herstart veilig — ramp reset naar %.0f°C "
                        "(opgeslagen %.0f°C, watertemp %.1f°C)",
                        b.label, _green_base, _saved_sp, _current_temp,
                    )
                else:
                    # Water is al warm genoeg — restore opgeslagen ramp-setpoint
                    b._cheap_ramp_setpoint_c = max(_green_base, min(_saved_sp, b.cheap_ramp_max_c))
                _learned_l = float(_ramp_data.get("learned_tank_l", 0.0))
                if 20.0 <= _learned_l <= 500.0:
                    b._learned_tank_l = _learned_l
                # FIX 5: restore ramp-on accumulator
                b._ramp_on_min_acc = float(_ramp_data.get("ramp_on_min_acc", 0.0))
                _LOGGER.info(
                    "BoilerController [%s]: ramp=%.0f°C, tankvolume=%.0fL, "
                    "ramp-acc=%.0f min hersteld",
                    b.label, b._cheap_ramp_setpoint_c,
                    b._learned_tank_l, b._ramp_on_min_acc,
                )

    async def _save_temp(self, entity_id: str, temp_c: float) -> None:
        """Sla laatste bekende temperatuur op — overleeft herstart + Ariston 429."""
        try:
            existing = await self._temp_store.async_load() or {}
            existing[entity_id] = round(temp_c, 1)
            await self._temp_store.async_save(existing)
        except Exception:
            pass

    async def _async_save_power(self) -> None:
        """Sla geleerde vermogens op — max 1x per 5 minuten."""
        import time as _time
        if not self._power_dirty:
            return
        if (_time.time() - self._power_last_save) < 300:
            return
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        await self._power_store.async_save(
            {b.entity_id: round(b.power_w, 0) for b in all_b if b.power_w > 50}
        )
        # Sla ook temp/power histories op voor grafieken
        await self._power_store.async_save({
            **{b.entity_id: round(b.power_w, 0) for b in all_b if b.power_w > 50},
            **{"_temp_hist_" + b.entity_id: b._temp_history[-48:] for b in all_b},
            **{"_pow_hist_"  + b.entity_id: b._power_history[-48:] for b in all_b},
        })
        self._power_dirty     = False
        self._power_last_save = _time.time()

    async def _async_save_ramp(self) -> None:
        """Persisteer ramp-setpoint en geleerd tankvolume — max 1x per 5 minuten."""
        import time as _time
        if not hasattr(self, "_ramp_last_save"):
            self._ramp_last_save = 0.0
        if (_time.time() - self._ramp_last_save) < 300:
            return
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        data  = {}
        for b in all_b:
            if b.boiler_type == BOILER_TYPE_HYBRID and b._cheap_ramp_setpoint_c > 0:
                data[b.entity_id] = {
                    "ramp_setpoint_c":  round(b._cheap_ramp_setpoint_c, 1),
                    "learned_tank_l":   round(b._learned_tank_l, 1),
                    "ramp_on_min_acc":  round(b._ramp_on_min_acc, 1),  # FIX 5: persisteer teller
                }
        if data:
            await self._ramp_store.async_save(data)
            self._ramp_last_save = _time.time()

    # ── Hoofdevaluatie ────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_info:          dict,
        solar_surplus_w:     float = 0.0,
        phase_currents:      Optional[dict] = None,
        phase_max_currents:  Optional[dict] = None,
        surplus_threshold_w: float = DEFAULT_SURPLUS_THRESHOLD_W,
        export_threshold_a:  float = DEFAULT_EXPORT_THRESHOLD_A,
        battery_w:           float = 0.0,
    ) -> list[BoilerDecision]:
        # v5.5.30: battery_w < 0 = ontladen, > 0 = laden
        # Sla op voor gebruik in setpoint logica
        self._battery_w = battery_w
        # v5.5.35: sla price_info op voor gebruik in _switch_smart
        self._last_price_info = price_info
        phase_currents = phase_currents or {}
        decisions: list[BoilerDecision] = []

        # P1 directe respons: gebruik de meest recente P1-value als die recent is (< 90s)
        now = time.time()
        effective_surplus = solar_surplus_w
        if self._p1_surplus_w > 0 and (now - self._p1_last_ts) < 90:
            effective_surplus = max(solar_surplus_w, self._p1_surplus_w)

        await self._read_sensors()

        # Tijdens PV-surplus: gebruik maximaal setpoint om zoveel mogelijk zonne-energie op te slaan
        surplus_active = effective_surplus >= surplus_threshold_w
        _is_neg        = bool(price_info.get("is_negative", False))
        _current_price = float(price_info.get("current", 0.25) or 0.25)
        _avg_price     = float(price_info.get("avg_today", 0.25) or 0.25)
        # v4.6.6: bij negatieve prijs OF groot surplus (≥2× threshold) → hardware-max setpoint (bijv. 75°C)
        _big_surplus = effective_surplus >= surplus_threshold_w * 2.0
        _max_charge  = _is_neg or _big_surplus

        for b in self._boilers:
            # v5.5.30: tijdens accu-ontlading + duur tarief → verlaag setpoint
            # Logica: accu ontlaadt (battery_w < -500W) + stroom duurder dan gas
            # → gebruik nacht-setpoint om accu-energie te sparen
            # Niet van toepassing bij: negatieve prijs, PV-surplus, manual override
            _bat_discharging = getattr(self, "_battery_w", 0.0) < -500.0
            _is_neg_price = bool(price_info.get("is_negative", False))
            _has_surplus = solar_surplus_w >= surplus_threshold_w
            if (_bat_discharging
                    and not _is_neg_price
                    and not _has_surplus
                    and b._manual_override_until <= time.time()
                    and b.boiler_type in (BOILER_TYPE_HYBRID, BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_RESISTIVE)
                    and b.min_temp_c > 0
                    and b.active_setpoint_c > b.min_temp_c + 5.0):
                # Gebruik nacht-setpoint (laagste comfortabele temp)
                # Standaard: max(min_temp_c, max_setpoint_green_c × 0.85) → bijv. 45°C
                _discharge_sp = max(
                    b.min_temp_c,
                    (b.max_setpoint_green_c * 0.85) if b.max_setpoint_green_c > 0 else 45.0
                )
                if b.active_setpoint_c > _discharge_sp + 1.0:
                    b.active_setpoint_c = round(_discharge_sp, 1)
                    _LOGGER.debug(
                        "BoilerController [%s]: accu ontlaadt (%.0fW) → setpoint verlaagd naar %.0f°C",
                        b.label, getattr(self, "_battery_w", 0.0), _discharge_sp
                    )

            # v4.6.42: manuale override active → setpoint niet overschrijven
            if b._manual_override_until > time.time():
                pass
            elif b.boiler_type == BOILER_TYPE_VARIABLE:
                b.active_setpoint_c = b.setpoint_c
            elif surplus_active and MODE_PV_SURPLUS in b.modes:
                if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                    _hw_max = b.hw_ceiling
                    _target = _hw_max if _max_charge else min(b.surplus_setpoint_c, _hw_max)
                    if b.boiler_type == BOILER_TYPE_HYBRID:
                        # v4.6.507: ook bij PV-surplus de ramp gebruiken voor hybrid.
                        # Voorheen sprong active_setpoint_c direct naar surplus_setpoint_c (75°C).
                        # Nu: gebruik _cheap_ramp_setpoint_c als tussenstap, zodat bij
                        # communicatiestoring de boiler niet doorverwarmt naar 75°C.
                        _green_base_s = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                        _rmax_s = min(b.cheap_ramp_max_c, b.surplus_setpoint_c, _hw_max)
                        if b._cheap_ramp_setpoint_c < _green_base_s:
                            b._cheap_ramp_setpoint_c = _green_base_s
                        # Ramp omhoog bij voldoende AAN-tijd (surplus = snel rampen: 15 min)
                        _ramp_on_s = getattr(b, "_ramp_on_min_acc", 0.0)
                        _ramp_step_min = min(self._ramp_min_on_per_step, 15.0)  # surplus: sneller
                        if _ramp_on_s >= _ramp_step_min:
                            b._cheap_ramp_setpoint_c = min(b._cheap_ramp_setpoint_c + b.cheap_ramp_step_c, _rmax_s)
                            b._ramp_on_min_acc = 0.0
                            _LOGGER.debug(
                                "BoilerController [%s]: surplus ramp stap → %.0f°C",
                                b.label, b._cheap_ramp_setpoint_c,
                            )
                        b.active_setpoint_c = min(b._cheap_ramp_setpoint_c, _hw_max)
                    else:
                        b.active_setpoint_c = min(_target, _hw_max)
                else:
                    _target = b.surplus_setpoint_c if not _max_charge else b.hw_ceiling
                    b.active_setpoint_c = min(_target, b.hw_ceiling)
            elif b.boiler_type == BOILER_TYPE_HYBRID:
                # v4.6.403: gradueel setpoint voor hybrid.
                # Ramp-up: negatieve prijs ODER current veel goedkoper dan gas (ratio).
                # Ramp-down: prijs normaal/duur → terug naar green_max in stappen.
                # Dit voorkomt dat bij HA/internet-uitval de boiler op 75°C blijft doorverwarmen.
                _gas_p   = price_info.get("gas_price_eur_m3", 1.25)
                _gas_th  = _gas_p / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
                _cop_r   = _cop_from_temp(b.outside_temp_c, b.cop_curve_override) * COP_DHW_FACTOR
                _wp_th   = _current_price / max(_cop_r, 0.1)  # WP-kosten per kWh thermisch
                # Ramp-up als: negatieve prijs OF WP significant goedkoper dan gas
                _ramp_up = _is_neg or (_wp_th <= _gas_th * b.cheap_ramp_ratio and not _current_price > _avg_price * 1.1)
                _green_base = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                _rmax    = min(b.cheap_ramp_max_c, b.max_setpoint_boost_c, b.hw_ceiling)
                # Initialize ramp op eerste cycle
                if b._cheap_ramp_setpoint_c < _green_base:
                    b._cheap_ramp_setpoint_c = _green_base
                if _ramp_up:
                    # FIX 1: stap omhoog alleen na voldoende AAN-tijd (default 30 min)
                    _ramp_on_acc = getattr(b, "_ramp_on_min_acc", 0.0)
                    if _ramp_on_acc >= self._ramp_min_on_per_step:
                        b._cheap_ramp_setpoint_c = min(b._cheap_ramp_setpoint_c + b.cheap_ramp_step_c, _rmax)
                        b._ramp_on_min_acc = 0.0  # reset teller na stap
                        _LOGGER.debug(
                            "BoilerController [%s]: ramp stap → %.0f°C (na %.0f min AAN)",
                            b.label, b._cheap_ramp_setpoint_c, _ramp_on_acc,
                        )
                else:
                    # Ramp-down: stap terug naar green_base — ook op basis van AAN-tijd
                    _ramp_on_acc = getattr(b, "_ramp_on_min_acc", 0.0)
                    if _ramp_on_acc >= self._ramp_min_on_per_step or b._cheap_ramp_setpoint_c > _green_base + b.cheap_ramp_step_c:
                        b._cheap_ramp_setpoint_c = max(b._cheap_ramp_setpoint_c - b.cheap_ramp_step_c, _green_base)
                        b._ramp_on_min_acc = 0.0
                    # Als prijs ineens heel duur wordt: direct terug naar green_base
                    if _current_price > _avg_price * 1.5:
                        b._cheap_ramp_setpoint_c = _green_base
                        b._ramp_on_min_acc = 0.0
                b.active_setpoint_c = b._cheap_ramp_setpoint_c
            elif _is_neg:
                b.active_setpoint_c = b.hw_ceiling
            else:
                _sp = self._delta_t_setpoint(b, b.setpoint_c)
                b.active_setpoint_c = min(_sp, b.hw_ceiling)
            decisions.append(await self._evaluate_single(
                b, price_info, effective_surplus, phase_currents, surplus_threshold_w, export_threshold_a))

        for group in self._groups:
            if group.learner:
                outside_c = next((b.outside_temp_c for b in group.boilers if b.outside_temp_c is not None), None)
                season    = group.learner.update_season(outside_c)
                for b in group.boilers:
                    if b._manual_override_until > time.time():
                        pass  # manual override active → setpoint niet overschrijven
                    elif b.boiler_type == BOILER_TYPE_VARIABLE:
                        b.active_setpoint_c = b.setpoint_c  # variable: intern vast
                    elif surplus_active and MODE_PV_SURPLUS in b.modes:
                        if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                            _hw_max = b.hw_ceiling
                            _target = _hw_max if _max_charge else min(b.surplus_setpoint_c, _hw_max)
                            if b.boiler_type == BOILER_TYPE_HYBRID:
                                # v4.6.507: ramp ook voor groep-hybrid bij PV-surplus
                                _green_base_sg = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                                _rmax_sg = min(b.cheap_ramp_max_c, b.surplus_setpoint_c, _hw_max)
                                if b._cheap_ramp_setpoint_c < _green_base_sg:
                                    b._cheap_ramp_setpoint_c = _green_base_sg
                                _ramp_on_sg = getattr(b, "_ramp_on_min_acc", 0.0)
                                if _ramp_on_sg >= min(self._ramp_min_on_per_step, 15.0):
                                    b._cheap_ramp_setpoint_c = min(b._cheap_ramp_setpoint_c + b.cheap_ramp_step_c, _rmax_sg)
                                    b._ramp_on_min_acc = 0.0
                                b.active_setpoint_c = min(b._cheap_ramp_setpoint_c, _hw_max)
                            else:
                                b.active_setpoint_c = min(_target, _hw_max)
                        else:
                            _target = b.surplus_setpoint_c if not _max_charge else b.hw_ceiling
                            b.active_setpoint_c = min(_target, b.hw_ceiling)
                    elif b.boiler_type == BOILER_TYPE_HYBRID:
                        # v4.6.403: zelfde graduele ramp als standalone
                        _gas_pg  = price_info.get("gas_price_eur_m3", 1.25)
                        _gas_thg = _gas_pg / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
                        _cop_rg  = _cop_from_temp(b.outside_temp_c, b.cop_curve_override) * COP_DHW_FACTOR
                        _wp_thg  = _current_price / max(_cop_rg, 0.1)
                        _ramp_up_g = _is_neg or (_wp_thg <= _gas_thg * b.cheap_ramp_ratio and not _current_price > _avg_price * 1.1)
                        _green_bg  = b.max_setpoint_green_c if b.max_setpoint_green_c > 0 else b.setpoint_c
                        _rmax_g    = min(b.cheap_ramp_max_c, b.max_setpoint_boost_c, b.hw_ceiling)
                        if b._cheap_ramp_setpoint_c < _green_bg:
                            b._cheap_ramp_setpoint_c = _green_bg
                        if _ramp_up_g:
                            _ramp_on_g = getattr(b, "_ramp_on_min_acc", 0.0)
                            if _ramp_on_g >= self._ramp_min_on_per_step:
                                b._cheap_ramp_setpoint_c = min(b._cheap_ramp_setpoint_c + b.cheap_ramp_step_c, _rmax_g)
                                b._ramp_on_min_acc = 0.0
                        else:
                            _ramp_on_g = getattr(b, "_ramp_on_min_acc", 0.0)
                            if _ramp_on_g >= self._ramp_min_on_per_step or b._cheap_ramp_setpoint_c > _green_bg + b.cheap_ramp_step_c:
                                b._cheap_ramp_setpoint_c = max(b._cheap_ramp_setpoint_c - b.cheap_ramp_step_c, _green_bg)
                                b._ramp_on_min_acc = 0.0
                            if _current_price > _avg_price * 1.5:
                                b._cheap_ramp_setpoint_c = _green_bg
                                b._ramp_on_min_acc = 0.0
                        b.active_setpoint_c = b._cheap_ramp_setpoint_c
                    elif _is_neg and b.boiler_type == BOILER_TYPE_HEAT_PUMP:
                        b.active_setpoint_c = b.hw_ceiling
                    elif _is_neg:
                        b.active_setpoint_c = b.hw_ceiling
                    else:
                        sp = self._seasonal_setpoint(b, season)
                        _sp = self._delta_t_setpoint(b, sp)
                        b.active_setpoint_c = min(_sp, b.hw_ceiling)

                # Anomalie check — notificatie sturen als nodig
                msg = group.learner.check_anomaly(group.boilers)
                if msg:
                    _LOGGER.warning("BoilerController anomalie: %s", msg)
                    try:
                        await self._hass.services.async_call(
                            "persistent_notification", "create",
                            {"title": "CloudEMS — Boiler anomalie", "message": msg,
                             "notification_id": f"cloudems_boiler_anomaly_{group.id}"},
                            blocking=False)
                    except Exception:
                        pass

            # v5.5.43: directe gas-correctie VOOR evaluate_group
            _cp43 = float(price_info.get("current_all_in") or price_info.get("current", 0.25) or 0.25)
            _gp43 = float(price_info.get("gas_price_eur_m3", 1.25) or 1.25)
            _gt43 = _gp43 / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            for _b43 in group.boilers:
                if (_b43.control_mode == "preset"
                        and _b43.has_gas_heating == "yes"
                        and _b43._manual_override_until <= time.time()
                        and _cp43 > _gt43):
                    _b43.force_green = True
                    _wh43 = self._hass.states.get(_b43.entity_id)
                    if _wh43 and _wh43.state not in ("unavailable", "unknown"):
                        _cur43 = (_wh43.attributes.get("operation_mode") or
                                  _wh43.attributes.get("current_operation") or
                                  _wh43.attributes.get("preset_mode") or "").lower()
                        _want43 = _b43.preset_off.lower()
                        if _cur43 and _cur43 != _want43 and _cur43 not in ("imemory", ""):
                            _b43._pending_preset = ""
                            _b43._next_verify_ts = 0.0
                            _LOGGER.warning(
                                "BoilerController [%s]: GAS CORRECTIE %s->%s (%.1fct > %.1fct gas)",
                                _b43.label, _cur43, _want43, _cp43*100, _gt43*100,
                            )
                            await self._switch_smart(_b43.entity_id, True, _b43, effective_surplus)
            decisions.extend(await self._evaluate_group(group, price_info, effective_surplus, surplus_threshold_w))

        # Weekbudget bijwerken
        self._update_weekly_kwh()

        return decisions

    def _delta_t_setpoint(self, b: BoilerState, base_sp: float) -> float:
        """
        Delta-T optimalisatie: verlaag het setpoint dynamisch als de boiler nog
        ruim boven de comfort-grens zit, om onnodige warmte-overschotten te vermijden.
        Alleen actief als delta_t_optimize=True en thermal_loss_c_h bekend is.
        """
        if not b.delta_t_optimize or b.thermal_loss_c_h <= 0 or b.current_temp_c is None:
            return base_sp
        margin = b.current_temp_c - b.comfort_floor_c
        if margin < 5:
            return base_sp  # Te krap — normaal setpoint
        # Decrease setpoint proportioneel: max 8°C lager bij grote marge
        reduction = min(8.0, margin * 0.25)
        optimized = max(b.comfort_floor_c + 5, base_sp - reduction)
        _LOGGER.debug("DeltaT [%s]: setpoint %.1f→%.1f°C (marge %.1f°C)",
                      b.label, base_sp, optimized, margin)
        return optimized

    def _weekly_budget_key(self) -> str:
        now = datetime.now()
        return f"{now.year}-W{now.isocalendar()[1]:02d}"

    def _update_weekly_kwh(self) -> None:
        week = self._weekly_budget_key()
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            eid = b.entity_id
            if eid not in self._weekly_kwh:
                self._weekly_kwh[eid] = {}
            self._weekly_kwh[eid][week] = self._weekly_kwh[eid].get(week, 0.0) + b.cycle_kwh

    def get_weekly_budget(self) -> dict:
        """Geeft per boiler het kWh-verbruik van de huidige en vorige week."""
        week     = self._weekly_budget_key()
        all_b    = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        result   = {}
        for b in all_b:
            wdata = self._weekly_kwh.get(b.entity_id, {})
            weeks = sorted(wdata.keys(), reverse=True)[:4]
            result[b.entity_id] = {
                "label":        b.label,
                "current_week": round(wdata.get(week, 0.0), 3),
                "history":      {w: round(wdata[w], 3) for w in weeks},
                "cycle_kwh":    round(b.cycle_kwh, 3),
            }
        return result

    def _seasonal_setpoint(self, b: BoilerState, season: str) -> float:
        if season == "summer":
            return b.setpoint_summer_c if b.setpoint_summer_c > 0 else max(b.min_temp_c + 5, b.setpoint_c + SEASON_DELTA_C)
        return b.setpoint_winter_c if b.setpoint_winter_c > 0 else b.setpoint_c

    def auto_calibrate_season(self, outside_temp_c: float) -> None:
        """
        v1.32: Pas boilersetpoints automatisch aan op basis van buitentemperatuur.
        Alleen actief als de gebruiker GEEN expliciete zomer/winter setpoints heeft
        geconfigureerd (setpoint_summer_c == 0 of setpoint_winter_c == 0).

        Logica:
          - Warm buiten (>= 15°C): zomersetpoint = setpoint_c - 5°C (minder legionella-risico,
            minder stilstandsverlies, sneller opgewarmd door zon)
          - Koud buiten (<= 5°C):  wintersetpoint = setpoint_c + 3°C (extra buffer voor
            piekverbruik verwarming, grotere thermische massa beschikbaar)
        """
        import logging as _l
        log = _l.getLogger(__name__)
        for b in getattr(self, "_boilers", []):
            changed = False
            if outside_temp_c >= 15.0 and b.setpoint_summer_c == 0:
                new_sp = max(b.min_temp_c + 5, b.setpoint_c - 5.0)
                if abs(new_sp - b.setpoint_c) > 0.5:
                    b.setpoint_summer_c = round(new_sp, 1)
                    changed = True
                    log.info(
                        "BoilerController '%s': auto zomersetpoint %.1f°C "
                        "(buiten %.1f°C)",
                        b.name, b.setpoint_summer_c, outside_temp_c,
                    )
            elif outside_temp_c <= 5.0 and b.setpoint_winter_c == 0:
                new_sp = min(b.setpoint_c + 3.0, 70.0)
                if abs(new_sp - b.setpoint_c) > 0.5:
                    b.setpoint_winter_c = round(new_sp, 1)
                    changed = True
                    log.info(
                        "BoilerController '%s': auto wintersetpoint %.1f°C "
                        "(buiten %.1f°C)",
                        b.name, b.setpoint_winter_c, outside_temp_c,
                    )

    # ── Enkelvoudige boiler ───────────────────────────────────────────────────

    async def _evaluate_single(self, b, price_info, solar_surplus_w,
                                phase_currents, surplus_threshold_w, export_threshold_a):
        now     = time.time()

        # v4.5.12: check of entity available is — unavailable = geen sturing, wel loggen.
        _state = self._hass.states.get(b.entity_id)
        if _state is None or _state.state in ("unavailable", "unknown"):
            _LOGGER.warning(
                "BoilerController [%s]: entiteit '%s' is %s — sturing overgeslagen. "
                "Controleer of de entiteit correct geconfigureerd is in HA.",
                b.label, b.entity_id,
                "niet gevonden" if _state is None else _state.state,
            )
            return BoilerDecision(
                entity_id=b.entity_id, label=b.label,
                action="hold_off",
                reason=f"entiteit {b.entity_id} {'niet gevonden' if _state is None else _state.state}",
                current_state=False,
            )

        # v4.6.45: manual override active → CloudEMS blijft af, virtual boiler stuurt zelf
        if b._manual_override_until > time.time():
            return BoilerDecision(
                entity_id=b.entity_id, label=b.label,
                action="hold_off", reason="manual override actief",
                current_state=self._is_on(b.entity_id, b),
            )

        is_on   = self._is_on(b.entity_id, b)
        want_on = False
        reason  = ""

        # Reset per-round flags
        # v4.6.26: als gebruiker BOOST pauzeerde → force_green recoverylen tot pauze voorbij
        if b._boost_paused_until > 0:
            if time.time() < b._boost_paused_until:
                b.force_green = True   # blijf in GREEN/ECO zolang pauze active
            else:
                b._boost_paused_until = 0.0  # pauze verlopen
                b.force_green = False
        else:
            b.force_green = False
        # Backwards-compat: heat_pump_boiler=True → upgrade naar boiler_type
        if b.heat_pump_boiler and b.boiler_type == BOILER_TYPE_RESISTIVE:
            b.boiler_type = BOILER_TYPE_HEAT_PUMP

        btype          = b.boiler_type
        _current_price = price_info.get("current", 0.5)
        _avg_price     = price_info.get("avg_today", 0.5)
        _is_negative   = bool(price_info.get("is_negative", False))
        _deficit       = b.temp_deficit_c
        _has_temp      = b.current_temp_c is not None
        _outside       = b.outside_temp_c
        _hour          = datetime.now().hour

        # Effectieve cheap-rank: WP/hybrid hebben langere horizon nodig
        effective_rank = b.cheap_hours_rank
        if btype in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) and b.heat_up_hours > 0:
            effective_rank = max(b.cheap_hours_rank, int(b.heat_up_hours))
            effective_rank = min(effective_rank, 14)

        # Boost-toegang: weerstandselement alleen in goedkoopste N uren,
        # bij groot PV-surplus, of bij negatieve prijs
        boost_n = b.boost_only_cheapest
        _boost_allowed = (
            boost_n == 0
            or _is_negative
            or price_info.get(f"in_cheapest_{boost_n}h", False)
            or solar_surplus_w > surplus_threshold_w * 0.8
        )

        # v4.6.394: heat_pump/hybrid met GREEN-mode temperaturecap (bijv. Ariston GREEN = max 53°C).
        # Pas active_setpoint_c aan naar de mode-specifieke grens zodat needs_heat en
        # temp_deficit_c de werkelijk haalbare temperature weerspiegelen:
        #   • Geen actieve boost-reden → GREEN gebruiken → cap op max_setpoint_green_c
        #   • Actieve boost-reden (surplus / goedkoop uur / negatieve prijs) → cap op max_setpoint_boost_c
        # LET OP: _boost_allowed (boost_n==0) telt hier NIET mee — dat returns alleen aan of boost
        # technisch toegestaan is, niet of er een actieve reden is om te boosen.
        # Zonder dit onderscheid zou active_setpoint_c (bijv. 54°C) nooit bijgesneden worden
        # naar de GREEN-grens (53°C), en zou CloudEMS onnodig BOOST kiezen.
        if btype in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) and b.max_setpoint_green_c > 0:
            _has_boost_reason = (
                _is_negative
                or price_info.get(f"in_cheapest_{boost_n}h", False)
                or solar_surplus_w > surplus_threshold_w * 0.8
            )
            _mode_cap = b.max_setpoint_boost_c if _has_boost_reason else b.max_setpoint_green_c
            if b.active_setpoint_c > _mode_cap + 0.5:
                b.active_setpoint_c = _mode_cap
            # Hercalculate deficit met de gecorrigeerde setpoint
            _deficit = b.temp_deficit_c

        # ── TYPE 1: RESISTIVE — prijs en surplus domineren ───────────────────────────────
        if btype == BOILER_TYPE_RESISTIVE:
            if MODE_NEGATIVE_PRICE in b.modes and _is_negative:
                want_on = True; reason = f"Negatieve prijs: {_current_price:.4f} €/kWh"

            # Gas-vs-current: als CV aanwezig, check of current goedkoper is dan gas thermisch.
            # Negatieve prijs en PV-surplus zijn altijd voordelig → niet geblokkeerd.
            _gas_price_m3     = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th           = _gas_price_m3 / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _elec_th          = _current_price  # weerstandselement: COP=1
            _stroom_goedkoper = (b.has_gas_heating != "yes") or (_elec_th <= _gas_th + GAS_VS_ELEC_MARGIN)

            if not want_on and MODE_CHEAP_HOURS in b.modes and price_info.get(f"in_cheapest_{effective_rank}h"):
                if _stroom_goedkoper:
                    want_on = True; reason = f"Goedkoopste {effective_rank}u ({_current_price:.4f} €/kWh)"
                else:
                    reason = (f"Gas goedkoper ({_gas_th*100:.1f}ct vs stroom {_elec_th*100:.1f}ct/kWh_th)"
                              f" — CV verwarmt, boiler wacht op surplus")
            eff_thr = (surplus_threshold_w * 0.4) if b.post_saldering_mode else surplus_threshold_w
            if not want_on and MODE_PV_SURPLUS in b.modes and solar_surplus_w >= eff_thr:
                tag = " [post-saldering]" if b.post_saldering_mode and solar_surplus_w < surplus_threshold_w else ""
                want_on = True; reason = f"PV surplus {solar_surplus_w:.0f}W{tag}"
            if not want_on and MODE_EXPORT_REDUCE in b.modes:
                pc = phase_currents.get(b.phase, 0.0)
                if pc < -export_threshold_a:
                    want_on = True; reason = f"Export afschaven: {b.phase} {abs(pc):.2f}A"
            if not want_on and MODE_HEAT_DEMAND in b.modes:
                if _stroom_goedkoper:
                    _price_ok = _current_price < _avg_price * 1.5 or solar_surplus_w > 200
                    if _outside is not None and _outside < b.heat_demand_temp_c and _price_ok:
                        want_on = True; reason = f"Warmtevraag buitentemp: {_outside:.1f}°C"
                    elif _deficit > 10.0 and _price_ok:
                        want_on = True; reason = f"Warmtevraag urgent: {_deficit:.1f}°C tekort"
                    elif _deficit > 3.0 and 5 <= _hour <= 8 and _price_ok:
                        want_on = True; reason = f"Warmtevraag ochtend {_hour}:00 ({_deficit:.1f}°C tekort)"
                # Als gas goedkoper: warmtevraag via CV — boiler doet niets extra

        # ── TYPE 2: HEAT_PUMP — altijd warm via WP-element, boost selectief ─────────────
        # COP > 1: green (WP) is altijd goedkoper dan weerstand of gas.
        # green ALTIJD aan bij temperaturetekort, ongeacht currentprijs.
        # boost (weerstandselement) alleen bij goedkoopste N uren of surplus.
        #
        # v4.6.5: Ariston e.a. WP-boilers met GREEN/BOOST-modi:
        #   • Onder green_mode_max_c (bijv. 53°C): GREEN verwarmt via WP (force_green=True)
        #   • Bij surplus of goedkoop uur: ga naar BOOST (ook als temp < green_mode_max_c),
        #     zodat de boiler al in de juiste mode staat vóór het setpoint ranget is.
        #   • Boven green_mode_max_c: ALTIJD BOOST (GREEN kan dit niet rangeen).
        elif btype == BOILER_TYPE_HEAT_PUMP:
            # COP-bewuste gas-vs-WP vergelijking: WP bijna altijd goedkoper dan gas
            _cop_wp  = _cop_from_temp(_outside, b.cop_curve_override) * COP_DHW_FACTOR
            _gas_p_m3 = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th_wp = _gas_p_m3 / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _wp_th     = _current_price / max(_cop_wp, 0.1)
            _wp_cheaper_than_gas = (b.has_gas_heating != "yes") or (_wp_th <= _gas_th_wp + GAS_VS_ELEC_MARGIN)

            # v4.6.273: vergelijk het actieve setpoint met GREEN-max, niet de huidige temp.
            # BOOST required alleen als het SETPOINT boven GREEN-max uitkomt.
            _above_green_max = (
                b.max_setpoint_green_c > 0
                and b.active_setpoint_c > b.max_setpoint_green_c
            )

            if not b.needs_heat:
                want_on = False
                reason  = f"WP op setpoint ({b.current_temp_c:.1f}°C)" if _has_temp else "WP op setpoint"
            elif _is_negative:
                want_on = True; reason = f"WP + boost: negatieve prijs {_current_price:.4f} €/kWh"
            elif _has_temp and _deficit > 0:
                want_on = True
                _heat_up_min = b.heat_up_hours * 60 if b.heat_up_hours > 0 else 600
                _mts = b.minutes_to_setpoint or 0

                # v4.6.550: Harde regel — als GREEN het setpoint kan rangeen, NOOIT boost.
                # Boost (weerstandselement, COP=1) is altijd duurder dan GREEN (warmtepomp, COP≈3-4).
                # Ongeacht surplus, goedkope uren of andere redenen: als setpoint ≤ green_max → force_green.
                # Definitie: GREEN kan setpoint rangeen als active_setpoint_c ≤ max_setpoint_green_c.
                _boost_green_possible = (
                    b.max_setpoint_green_c > 0
                    and b.active_setpoint_c <= b.max_setpoint_green_c
                )
                _above_green_max = b.max_setpoint_green_c > 0 and b.active_setpoint_c > b.max_setpoint_green_c

                _boost_by_price   = _is_negative
                _boost_needed     = _above_green_max  # setpoint boven GREEN-cap → boost onvermijdelijk
                # Goedkoop uur: boost alleen als GREEN setpoint NIET kan halen
                _boost_cheap_ok   = _boost_allowed and not _boost_green_possible
                # Surplus: boost alleen als GREEN setpoint NIET kan halen
                _boost_by_surplus = (
                    solar_surplus_w > surplus_threshold_w * 0.8
                    and not _boost_green_possible
                )

                if _boost_by_surplus or _boost_by_price or _boost_needed or _boost_cheap_ok:
                    b.force_green = False  # boost: weerstandselement
                    if _above_green_max and not (_boost_by_surplus or _boost_by_price):
                        cop_str = f" COP≈{_cop_wp:.1f}" if _outside is not None else ""
                        reason = f"WP boost{cop_str}: setpoint ({b.active_setpoint_c:.0f}°C) > GREEN-max ({b.max_setpoint_green_c:.0f}°C)"
                    elif _boost_by_surplus:
                        reason = f"WP boost: PV surplus {solar_surplus_w:.0f}W (boven GREEN-cap)"
                    elif _boost_by_price:
                        reason = f"WP boost: negatieve prijs {_current_price:.4f} €/kWh"
                    else:
                        reason = f"WP boost: {_deficit:.1f}°C tekort, GREEN-cap ({b.max_setpoint_green_c:.0f}°C) bereikt"
                else:
                    b.force_green = True   # GREEN/WP-element — efficiënter
                    cop_str = f" COP≈{_cop_wp:.1f}" if _outside is not None else ""
                    if _mts > 0:
                        reason = f"WP green{cop_str}: {_deficit:.1f}°C tekort (~{_mts:.0f} min tot setpoint)"
                    else:
                        reason = f"WP green{cop_str}: {_deficit:.1f}°C tekort"
                if b.has_gas_heating == "yes" and not _wp_cheaper_than_gas and not _is_negative:
                    reason += f" [WP €{_wp_th*100:.1f}ct vs gas €{_gas_th_wp*100:.1f}ct/kWh_th]"
            elif not _has_temp and price_info.get(f"in_cheapest_{effective_rank}h"):
                want_on = True; reason = f"WP green: goedkoopste {effective_rank}u (geen temp sensor)"
            # v4.6.550: onderstaande fallback ALLEEN boost als GREEN setpoint niet kan halen
            if not want_on and _boost_allowed and solar_surplus_w > surplus_threshold_w:
                _bgp = b.max_setpoint_green_c > 0 and b.active_setpoint_c <= b.max_setpoint_green_c
                if not _bgp:
                    want_on = True; b.force_green = False
                    reason = f"WP boost: PV surplus {solar_surplus_w:.0f}W (boven GREEN-cap)"
                else:
                    want_on = True; b.force_green = True
                    reason = f"WP green: PV surplus {solar_surplus_w:.0f}W (setpoint ≤ GREEN-max, geen boost nodig)"

        # ── TYPE 3: HYBRID — green (WP) altijd bij tekort, boost selectief ────────────
        # Bijv. Ariston Lydos Hybrid. green = WP-element, boost = weerstandselement.
        # v4.6.5: boven green_mode_max_c ALTIJD BOOST (GREEN kan dit niet rangeen).
        elif btype == BOILER_TYPE_HYBRID:
            _cop_hyb   = _cop_from_temp(_outside, b.cop_curve_override) * COP_DHW_FACTOR
            _gas_p_m3h = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th_h  = _gas_p_m3h / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _hyb_th    = _current_price / max(_cop_hyb, 0.1)
            cop_str_h  = f" COP≈{_cop_hyb:.1f}" if _outside is not None else ""

            # v4.6.273: vergelijk het actieve setpoint met GREEN-max, niet de huidige temp.
            # Error: temp=52 >= green_max-1=52 → True → BOOST, terwijl GREEN 53°C WEL kan halen.
            # Fix: BOOST required alleen als het SETPOINT boven GREEN-max uitkomt.
            _above_green_max_h = (
                b.max_setpoint_green_c > 0
                and b.active_setpoint_c > b.max_setpoint_green_c
            )

            if not b.needs_heat:
                want_on = False
                reason  = f"Hybrid op setpoint ({b.current_temp_c:.1f}°C)" if _has_temp else "Hybrid op setpoint"
            elif _is_negative:
                want_on = True; reason = f"Hybrid boost: negatieve prijs {_current_price:.4f} €/kWh"
            else:
                want_on = True
                # v4.6.229: zelfde logic als heat_pump — boost alleen bij surplus,
                # negatieve prijs of boven GREEN-cap. Niet alleen op basis van goedkoop uur.
                _boost_green_possible_h = (
                    b.max_setpoint_green_c > 0
                    and b.active_setpoint_c <= b.max_setpoint_green_c
                )
                _boost_by_surplus_h = (
                    solar_surplus_w > surplus_threshold_w * 0.8
                    and not _boost_green_possible_h   # v4.6.550: GREEN kan setpoint rangeen → geen boost
                )
                _boost_by_price_h   = _is_negative
                _boost_needed_h     = _above_green_max_h
                # v4.6.402: _boost_cheap_ok_h verwijderd voor HYBRID.
                # GREEN (WP, COP≈2.8) is bij dezelfde currentprijs altijd goedkoper dan BOOST.
                _boost_cheap_ok_h = False  # nooit puur op prijs — GREEN is goedkoper

                # v4.6.404: Demand-based BOOST voor hybrid.
                # Als GREEN structureel de setpoint niet tijdig haalt (learnede opwarmsnelheid)
                # EN current is goedkoper dan gas (anders verwarmt CV sowieso)
                # EN er binnenkort veel warm water verwait wordt (learned consumptionspatroon)
                # → dan is BOOST nu goedkoper dan gas-fallback straks.
                _boost_demand_h = False
                if (not _boost_by_surplus_h and not _boost_by_price_h and not _boost_needed_h
                        and _has_temp):
                    try:
                        # Zoek learner: boiler zit in groep → gebruik die learner.
                        # Standalone boiler → gebruik eerste beschikbare groep-learner (gedeeld consumptionspatroon).
                        _learner = next(
                            (g.learner for g in self._groups
                             if g.learner and any(gb.entity_id == b.entity_id for gb in g.boilers)),
                            next((g.learner for g in self._groups if g.learner), None),
                        )
                        if _learner is None:
                            raise ValueError("geen learner beschikbaar")
                        # Learnede opwarmsnelheid GREEN (WP): °C/h
                        _green_rate   = _learner.get_heat_rate(b)  # °C/h van WP
                        _mts_green    = (_deficit / _green_rate * 60.0) if _green_rate > 0 else None
                        # Verwachte warm-waterconsumption komend uur (0..1 schaal)
                        _hour_now     = datetime.now().hour
                        _demand_soon  = _learner.should_preheat(_hour_now, _mts_green)
                        # Stroom goedkoper dan gas?
                        _wp_th_h      = _current_price / max(_cop_hyb, 0.1)
                        _gas_th_boost = _gas_th_h  # gas-kosten per kWh thermisch
                        _stroom_gdk   = _wp_th_h < _gas_th_boost * 0.9  # marge: 10%
                        # GREEN haalt setpoint niet op tijd?
                        # FIX 2: gebruik learnede threshold i.p.v. hardcoded 90 min
                        _demand_threshold = _learner.get_demand_boost_threshold_min()
                        # FIX 5: gebruik minutes_to_heat() (learnede opwarmsnelheid) i.p.v. heat_up_hours
                        _mts_learned = _learner.minutes_to_heat(b)
                        _mts_for_check = _mts_learned if _mts_learned is not None else _mts_green
                        _green_too_slow = (
                            _mts_for_check is not None
                            and _mts_for_check > _demand_threshold
                        )
                        if _demand_soon and _stroom_gdk and _green_too_slow:
                            _boost_demand_h = True
                            _mts_display = _mts_for_check or _mts_green or 0
                            _LOGGER.info(
                                "BoilerController [%s]: BOOST demand-based: "
                                "WP %.0f min nodig (drempel=%.0f min, geleerd=%s), "
                                "verbruik verwacht, WP=%.1fct vs gas=%.1fct/kWh_th",
                                b.label, _mts_display, _demand_threshold,
                                f"{_mts_learned:.0f} min" if _mts_learned else "n.v.t.",
                                _wp_th_h * 100, _gas_th_boost * 100,
                            )
                            # FIX 2: Sla moment + temp op voor feedback-loop
                            b._demand_boost_ts    = now
                            b._temp_before_demand = b.current_temp_c
                    except Exception as _dem_err:
                        _LOGGER.debug("BoilerController demand-boost check fout: %s", _dem_err)

                if _boost_by_surplus_h or _boost_by_price_h or _boost_needed_h or _boost_cheap_ok_h or _boost_demand_h:
                    # v4.6.550: harde blokkade — als GREEN setpoint kan rangeen én geen demand-boost,
                    # nooit boost sturen ongeacht andere redenen
                    if _boost_green_possible_h and not _boost_needed_h and not _boost_demand_h:
                        b.force_green = True
                        reason = f"Hybrid green (WP{cop_str_h}): {_deficit:.1f}°C tekort (GREEN kan setpoint bereiken, geen boost)"
                    else:
                        b.force_green = False  # boost active
                        if _above_green_max_h and not (_boost_by_surplus_h or _boost_by_price_h):
                            reason = f"Hybrid boost verplicht: setpoint ({b.active_setpoint_c:.0f}°C) > GREEN-max ({b.max_setpoint_green_c:.0f}°C)"
                        elif _boost_by_surplus_h:
                            reason = f"Hybrid boost: PV surplus {solar_surplus_w:.0f}W (boven GREEN-cap)"
                        elif _boost_by_price_h:
                            reason = f"Hybrid boost: negatieve prijs {_current_price:.4f} €/kWh"
                        elif _boost_demand_h:
                            reason = f"Hybrid boost: warm water verwacht, WP te traag, stroom goedkoper dan gas"
                        else:
                            reason = f"Hybrid boost: {_deficit:.1f}°C tekort, GREEN-cap ({b.max_setpoint_green_c:.0f}°C) bereikt"
                else:
                    b.force_green = True   # alleen WP-element
                    reason = f"Hybrid green (WP{cop_str_h}): {_deficit:.1f}°C tekort" if _has_temp else f"Hybrid green (WP{cop_str_h}): geen temp sensor"
            # v4.6.550: fallback surplus — ook hier harde blokkade als GREEN setpoint kan rangeen
            if not want_on and _boost_allowed and solar_surplus_w > surplus_threshold_w:
                _bgp_h = b.max_setpoint_green_c > 0 and b.active_setpoint_c <= b.max_setpoint_green_c
                want_on = True
                if not _bgp_h:
                    b.force_green = False
                    reason = f"Hybrid boost: PV surplus {solar_surplus_w:.0f}W (boven GREEN-cap)"
                else:
                    b.force_green = True
                    reason = f"Hybrid green: PV surplus {solar_surplus_w:.0f}W (setpoint ≤ GREEN-max, geen boost nodig)"

        # ── TYPE 4: VARIABLE — proportioneel 0-100% op surplus/prijs ────────────────
        # Dimmerlink boiler: intern vast setpoint, CloudEMS regelt alleen power%.
        elif btype == BOILER_TYPE_VARIABLE:
            # Gas-vs-current: hergebruik berekening van TYPE 1 (of calculate opnieuw als type 4 alleen)
            _gas_price_m3_v   = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th_v         = _gas_price_m3_v / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _stroom_gdk_v     = (b.has_gas_heating != "yes") or (_current_price <= _gas_th_v + GAS_VS_ELEC_MARGIN)

            if _is_negative:
                want_on = True; reason = f"Variable 100%: negatieve prijs {_current_price:.4f} €/kWh"
            elif solar_surplus_w >= surplus_threshold_w * 0.3:
                want_on = True; reason = f"Variable proportioneel: surplus {solar_surplus_w:.0f}W"
            elif MODE_CHEAP_HOURS in b.modes and price_info.get(f"in_cheapest_{effective_rank}h") and b.needs_heat:
                if _stroom_gdk_v:
                    want_on = True; reason = f"Variable min%: goedkoopste {effective_rank}u"
                else:
                    reason = f"Gas goedkoper ({_gas_th_v*100:.1f}ct vs stroom {_current_price*100:.1f}ct/kWh_th) — wacht op surplus"
            elif MODE_EXPORT_REDUCE in b.modes:
                pc = phase_currents.get(b.phase, 0.0)
                if pc < -export_threshold_a:
                    want_on = True; reason = f"Variable export afschaven: {b.phase}"

        # ── Congestie en veiligheid — alle typen ───────────────────────────────────────────
        if MODE_CONGESTION_OFF in b.modes and b.congestion_active:
            want_on = False; reason = "Netcongestie — uitgesteld"
        if _has_temp and b.current_temp_c >= SAFETY_MAX_C:
            want_on = False; reason = f"Veiligheidslimiet {b.current_temp_c:.1f}°C"

        # ── Legionella override (enkelvoudige boiler zonder learner) ───────────────────
        # Cascade-boilers worden via BoilerLearner per groep beheerd.
        # Voor enkelvoudige boilers: simpele tijd+temp check.
        if _has_temp and b.current_temp_c is not None:
            # Als boiler al op legionella-temp zit: registreer tick (warm genoeg)
            # We slaan legionella-state op als enkelvoudige-boiler sentinel in een
            # eigen minimale dict op b-niveau (geen persist nodig, learner-loos).
            if not hasattr(b, "_leg_ticks"):
                b._leg_ticks = 0   # type: ignore[attr-defined]
                b._leg_last_check = 0.0  # type: ignore[attr-defined]
                b._leg_last_done = 0.0   # type: ignore[attr-defined]
            now_t = time.time()
            if now_t - b._leg_last_check >= 60:  # 1x per minuut
                b._leg_last_check = now_t
                days_since = (now_t - b._leg_last_done) / 86400 if b._leg_last_done > 0 else 999
                if b.current_temp_c >= LEGIONELLA_TEMP_C:
                    b._leg_ticks += 60  # tellen in seconden
                    if b._leg_ticks >= LEGIONELLA_CONFIRM_S and days_since > 0.5:
                        b._leg_last_done = now_t
                        b._leg_ticks = 0
                        _LOGGER.info("BoilerController [%s]: legionella-cyclus voltooid", b.label)
                        # v4.6.438: sla datum op in history
                        from datetime import date as _date_leg
                        _leg_hist = self._g().setdefault("legionella_history", {})
                        _leg_hist.setdefault(b.entity_id, [])
                        _today_str = str(_date_leg.today())
                        if not _leg_hist[b.entity_id] or _leg_hist[b.entity_id][-1] != _today_str:
                            _leg_hist[b.entity_id].append(_today_str)
                            _leg_hist[b.entity_id] = _leg_hist[b.entity_id][-365:]  # max 1 jaar
                else:
                    if days_since >= LEGIONELLA_INTERVAL_DAYS and not want_on:
                        # v4.6.437: Kies het goedkoopste uur voor legionella via price-aware planning
                        _is_deadline = days_since >= LEGIONELLA_DEADLINE_DAYS
                        _days_left   = max(0, int(LEGIONELLA_DEADLINE_DAYS - days_since))
                        _hourly      = price_info.get("hourly_prices", [])
                        _tomorrow    = price_info.get("hourly_prices_tomorrow")
                        _cur_hour    = datetime.now().hour

                        if _hourly and not _is_deadline:
                            # Bepaal het gepland uur — leg_learner houdt dit per dag bij
                            _leg_learner = next(
                                (g.learner for g in self._groups
                                 if g.learner and any(gb.entity_id == b.entity_id for gb in g.boilers)),
                                next((g.learner for g in self._groups if g.learner), None),
                            )
                            if _leg_learner and hasattr(_leg_learner, "legionella_planned_hour"):
                                _planned_h = _leg_learner.legionella_planned_hour(
                                    b.entity_id,
                                    _hourly,
                                    _tomorrow,
                                    days_until_needed=_days_left,
                                )
                            else:
                                # Fallback: goedkoopste nachtuur
                                _ranked = sorted(range(len(_hourly)), key=lambda i: _hourly[i])
                                _night  = [h for h in _ranked[:6] if 0 <= h <= 6]
                                _planned_h = _night[0] if _night else _ranked[0]

                            if _cur_hour == _planned_h:
                                want_on = True
                                reason  = (f"Legionella preventie: {days_since:.0f} dagen geleden "
                                           f"— gepland uur {_planned_h:02d}:00 "
                                           f"({_hourly[_planned_h]*100:.1f}ct/kWh)")
                                _LOGGER.info("BoilerController [%s]: %s", b.label, reason)
                            else:
                                _LOGGER.debug(
                                    "BoilerController [%s]: legionella uitgesteld naar %02d:00 "
                                    "(nu %02d:00, prijs %.4f €/kWh)",
                                    b.label, _planned_h, _cur_hour,
                                    _hourly[_cur_hour] if _cur_hour < len(_hourly) else 0,
                                )
                        else:
                            # Geen prijsdata of deadline: gewoon aan
                            want_on = True
                            if _is_deadline:
                                reason = f"Legionella DEADLINE: {days_since:.0f} dagen geleden (force)"
                            else:
                                reason = f"Legionella preventie: {days_since:.0f} dagen geleden"
                            _LOGGER.info("BoilerController [%s]: %s", b.label, reason)
                    elif days_since >= LEGIONELLA_DEADLINE_DAYS:
                        want_on = True
                        reason = f"Legionella DEADLINE overschreden: {days_since:.0f} dagen"
                        _LOGGER.warning("BoilerController [%s]: %s", b.label, reason)

        # ── v4.6.12: Hardware deadband compensatie ────────────────────────────
        # Ariston/WP-boilers starten pas als de watertemperature ver genoeg onder
        # het setpoint zakt. We sturen een iets hoger setpoint om dit te compenseren.
        # Auto-value: 2.0°C voor heat_pump/hybrid, 0.0 voor andere typen.
        _hw_deadband = b.hardware_deadband_c
        if _hw_deadband == 0.0 and btype in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
            _hw_deadband = HP_HW_DEADBAND_DEFAULT_C
        if _hw_deadband > 0.0 and b.active_setpoint_c > 0:
            _compensated = min(b.active_setpoint_c + _hw_deadband, SAFETY_MAX_C - 1.0)
            if abs(_compensated - b.active_setpoint_c) > 0.1:
                _LOGGER.debug(
                    "BoilerController [%s]: hardware deadband +%.1f°C → setpoint %.1f→%.1f°C",
                    b.label, _hw_deadband, b.active_setpoint_c, _compensated,
                )
                b.active_setpoint_c = _compensated

        # ── v4.6.12: Stall-detectie ───────────────────────────────────────────
        # Als de boiler want_on=True maar 0W trekt (hardware deadband niet doorbroken),
        # boost het setpoint temporary om de hardware te forceren te starten.
        _power_now = b.current_power_w or 0.0
        _is_stalling = want_on and is_on and _power_now < 50.0 and b.current_temp_c is not None
        if _is_stalling:
            if b._stall_start_ts == 0.0:
                b._stall_start_ts = now
            elif now - b._stall_start_ts >= b.stall_timeout_s:
                if not b._stall_active:
                    b._stall_active = True
                    _LOGGER.warning(
                        "BoilerController [%s]: STALL gedetecteerd — %.0fs geen vermogen terwijl want_on. "
                        "Setpoint tijdelijk +%.1f°C om hardware deadband te doorbreken.",
                        b.label, b.stall_timeout_s, b.stall_boost_c,
                    )
                _boost_sp = min(b.active_setpoint_c + b.stall_boost_c, SAFETY_MAX_C - 1.0)
                b.active_setpoint_c = _boost_sp
                reason = reason + f" [stall boost +{b.stall_boost_c:.0f}°C → {_boost_sp:.0f}°C]"
        else:
            # Geen stall: reset teller
            if b._stall_start_ts > 0 and not _is_stalling:
                if b._stall_active:
                    _LOGGER.info("BoilerController [%s]: stall opgelost — boiler trekt weer vermogen", b.label)
                b._stall_start_ts = 0.0
                b._stall_active   = False

        action = self._apply_timers(b, want_on, is_on, now, reason)
        if action == "turn_on":
            # v4.6.507: back-off bij herhaalde no-response
            if self._check_turn_on_no_response(b, is_on):
                await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
            else:
                action = "hold_off"
                reason = f"back-off: {b._no_response_count}x geen respons op turn_on"
        if action == "turn_off":
            await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
        # v5.5.38: gas-check via helper (ook voor standalone boilers)
        self._apply_gas_check_and_mismatch(b, is_on, "single", solar_surplus_w)

        # v5.5.30: preset mismatch correctie — altijd, niet alleen bij hold_on
        # Vergelijk actuele preset met wat CloudEMS wil. Als ze afwijken:
        # zet _pending_preset zodat de verify loop het oppakt én stuur direct.
        # Dit vangt ook gevallen op na herstart, iMemory drift, etc.
        await self._do_mismatch_correction(b, is_on, action, solar_surplus_w)
        return BoilerDecision(entity_id=b.entity_id, label=b.label,
                              action=action, reason=reason, current_state=is_on)

    # ── Cascade evaluatie ─────────────────────────────────────────────────────

    async def _evaluate_group(self, group, price_info, solar_surplus_w, surplus_threshold_w):
        mode = group.mode
        if mode == CASCADE_AUTO:
            if price_info.get("is_negative") or solar_surplus_w >= group.total_power_w * 0.8:
                mode = CASCADE_PARALLEL
            elif price_info.get("in_cheapest_3h") or solar_surplus_w >= surplus_threshold_w:
                mode = CASCADE_SEQUENTIAL
            elif self._should_preheat_group(group):
                mode = CASCADE_SEQUENTIAL
            else:
                mode = CASCADE_STANDBY

        if mode == CASCADE_SEQUENTIAL: return await self._group_sequential(group, solar_surplus_w)
        if mode == CASCADE_PARALLEL:   return await self._group_parallel(group, solar_surplus_w)
        if mode == CASCADE_PRIORITY:   return await self._group_priority(group, solar_surplus_w)
        return self._group_standby(group)

    def _should_preheat_group(self, group: CascadeGroup) -> bool:
        if not group.learner:
            return False
        now_dt   = datetime.now()
        hour_now = now_dt.hour
        for b in group.boilers:
            if not b.needs_heat:
                continue
            mts = b.minutes_to_setpoint
            if group.learner.should_preheat(hour_now, mts):
                _LOGGER.debug("BoilerController [%s]: preventief opwarmen geactiveerd (dag-%d patroon)",
                              group.id, now_dt.weekday())
                return True
            # Optimal start: check of we nu moeten beginnen voor het volgende piekuur
            if mts and mts > 0:
                wait_min = group.learner.optimal_start_before_minutes(hour_now, mts)
                if wait_min <= 5:  # binnen 5 minuten van ideale starttijd
                    _LOGGER.debug("BoilerController [%s]: optimal start geactiveerd (wacht %.0f min)",
                                  group.id, wait_min)
                    return True

        # Legionella: trigger groep als één van de boilers een cycle nodig heeft
        for b in group.boilers:
            if group.learner.legionella_needed(b.entity_id):
                return True

        return False

    def _apply_gas_check_and_mismatch(self, b, is_on: bool, action: str, solar_surplus_w: float) -> None:
        """v5.5.38: Centrale gas-check + mismatch correctie voor alle group paden.
        
        Als has_gas_heating=yes en gas goedkoper dan stroom → force_green=True.
        Als boiler aan is in de verkeerde preset → stuur correctie.
        Asynchroon commando via _switch_smart wordt als coroutine teruggegeven.
        """
        now = time.time()
        if b._manual_override_until > now:
            return None
        # Gas-check: zet force_green als gas goedkoper dan stroom
        if b.control_mode == "preset" and b.has_gas_heating == "yes":
            _pi = getattr(self, "_last_price_info", {})
            # v5.5.39: gebruik all-in prijs, niet EPEX raw
            _cp = float(_pi.get("current_all_in") or _pi.get("current", 0.25) or 0.25)
            _gp = float(_pi.get("gas_price_eur_m3", 1.25) or 1.25)
            _gt = _gp / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            if _cp > _gt:
                b.force_green = True
                _LOGGER.info(
                    "BoilerController [%s]: gas-check → force_green=True (all_in=%.1fct > gas=%.1fct/kWh_th)",
                    b.label, _cp * 100, _gt * 100,
                )
            else:
                _LOGGER.debug(
                    "BoilerController [%s]: gas-check → stroom goedkoper (all_in=%.1fct < gas=%.1fct/kWh_th)",
                    b.label, _cp * 100, _gt * 100,
                )
        return None  # mismatch correctie via _do_mismatch_correction

    async def _do_mismatch_correction(self, b, is_on: bool, action: str, solar_surplus_w: float) -> None:
        """v5.5.40: Mismatch correctie — stuur commando als preset verkeerd is.
        Ook als pending_preset gevuld is: als force_green de gewenste preset verandert,
        reset pending_preset zodat de correctie wél doorgaat.
        """
        _LOGGER.info(
            "BoilerController [%s]: _do_mismatch_correction aangeroepen — control=%s is_on=%s force_green=%s pending=%s",
            b.label, b.control_mode, is_on, b.force_green, b._pending_preset or "(leeg)",
        )
        if not (b.control_mode == "preset" and is_on):
            return
        # v5.5.40: als force_green de gewenste preset verandert tov pending_preset → reset
        if b._pending_preset:
            _wanted = (b.preset_on if not b.force_green else b.preset_off).lower()
            if b._pending_preset.lower() != _wanted:
                _LOGGER.info(
                    "BoilerController [%s]: pending_preset=%s maar gewenst=%s → reset (gas goedkoper)",
                    b.label, b._pending_preset, _wanted,
                )
                b._pending_preset = ""
                b._next_verify_ts = 0.0
        if b._pending_preset:
            return  # correct commando al onderweg
        _wh_st = self._hass.states.get(b.entity_id)
        if not _wh_st or _wh_st.state in ("unavailable", "unknown"):
            return
        _cur = (_wh_st.attributes.get("operation_mode") or
                _wh_st.attributes.get("current_operation") or
                _wh_st.attributes.get("preset_mode") or "").lower()
        _want = (b.preset_on if not b.force_green else b.preset_off).lower()
        _LOGGER.warning(
            "BoilerController [%s]: mismatch check — cur=%s want=%s force_green=%s pending=%s",
            b.label, _cur, _want, b.force_green, b._pending_preset or "(leeg)",
        )
        if _cur and _want and _cur != _want and _cur != "imemory":
            _LOGGER.warning(
                "BoilerController [%s]: preset mismatch %s → %s CORRIGEREN",
                b.label, _cur, _want,
            )
            await self._switch_smart(b.entity_id, True, b, solar_surplus_w)

    async def _group_sequential(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        order = group.get_sequential_order()
        decisions = []

        delivery_eid = group.learner.get_delivery_entity(group.boilers) if group.learner else None
        for b in order:
            b.is_delivery = (b.entity_id == delivery_eid) if delivery_eid else (b is order[0])

        if group.learner:
            group.learner.record_cycle_start(group.boilers)
            group.learner.update_cycle_kwh(group.boilers)

        active = None
        for b in order:
            is_on = self._is_on(b.entity_id, b)

            # manual override active → volledig overslaan
            if b._manual_override_until > time.time():
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "hold_off", "manual override actief", is_on, group.id, 0.0))
                continue

            # Netcongestie: leveringsboiler wel, buffers niet
            if b.congestion_active and not b.is_delivery:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Netcongestie — buffer uitgesteld", is_on, group.id, 0.0))
                continue

            if b.current_temp_c is not None and b.current_temp_c >= SAFETY_MAX_C:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label, "turn_off",
                    f"Veiligheidslimiet {b.current_temp_c:.1f}°C", is_on, group.id))
                continue

            if not b.needs_heat:
                if not is_on and group.learner:
                    group.learner.update_thermal_loss(b)
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                if b.current_temp_c is not None:
                    t = f"{b.current_temp_c:.1f}°C"
                    reden = f"Op setpoint ({t})"
                else:
                    reden = "Op setpoint (geen temp.sensor)"
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", reden, is_on, group.id, 0.0))
                continue

            if active is None:
                # v5.5.38: gas-check via helper
                self._apply_gas_check_and_mismatch(b, is_on, "seq", solar_surplus_w)
                tag    = " [geleerd]" if delivery_eid else " [standaard]"
                suffix = f" [levering{tag}]" if b.is_delivery else ""
                # v4.5.15: toon duidelijke reden als temperaturesensor ontbreekt
                # (ook na climate + powersfallback — dan is er echt niets)
                if b.current_temp_c is None:
                    reason = f"seq{suffix}: geen temperatuursensor (ook geen climate/vermogen) — trigger actief"
                else:
                    _fg_str = f" [force_green={b.force_green}]"
                    reason = f"seq{suffix}: {b.temp_deficit_c:.1f}°C onder setpoint{_fg_str}"
                action = self._apply_timers(b, True, is_on, now, reason)
                if action == "turn_on":
                    # v4.6.507: back-off bij herhaalde no-response
                    if self._check_turn_on_no_response(b, is_on):
                        await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
                    else:
                        action = "hold_off"
                        reason = f"back-off: {b._no_response_count}x geen respons op turn_on"
                await self._do_mismatch_correction(b, is_on, action, solar_surplus_w)
                decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, 100.0))
                active = b
            else:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label, "hold_off",
                    f"seq: wacht op {active.label}", is_on, group.id, 0.0))

        return decisions

    async def _group_parallel(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        decisions = []
        needs = [b for b in group.boilers if b.needs_heat and (b.current_temp_c is None or b.current_temp_c < SAFETY_MAX_C)]
        if not needs:
            return self._group_standby(group)
        total = sum(b.temp_deficit_c for b in needs) or 1.0
        slot  = 0
        for b in group.boilers:
            is_on = self._is_on(b.entity_id, b)
            if b._manual_override_until > time.time():
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "hold_off", "manual override actief", is_on, group.id, 0.0))
                continue
            if b not in needs:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Op setpoint", is_on, group.id, 0.0))
                continue
            if not is_on and b.stagger_ticks <= 0:
                b.stagger_ticks = slot * int(group.stagger_delay_s); slot += 1
            if b.stagger_ticks > 0:
                b.stagger_ticks -= 1
                decisions.append(BoilerDecision(b.entity_id, b.label, "hold_off",
                    f"parallel: stagger {b.stagger_ticks}s", is_on, group.id, 0.0))
                continue
            pct    = round(b.temp_deficit_c / total * 100, 1)
            reason = f"parallel: {pct:.0f}% (tekort {b.temp_deficit_c:.1f}°C)"
            self._apply_gas_check_and_mismatch(b, is_on, "parallel", solar_surplus_w)
            action = self._apply_timers(b, True, is_on, now, reason)
            if action == "turn_on":
                # v4.6.507: back-off bij herhaalde no-response
                if self._check_turn_on_no_response(b, is_on):
                    await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
                else:
                    action = "hold_off"
                    reason = f"back-off: {b._no_response_count}x geen respons op turn_on"
            await self._do_mismatch_correction(b, is_on, action, solar_surplus_w)
            decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, pct))
        return decisions

    async def _group_priority(self, group: CascadeGroup, solar_surplus_w: float = 0.0) -> list[BoilerDecision]:
        now   = time.time()
        decisions = []
        candidates = sorted(
            [b for b in group.boilers if b.needs_heat and (b.current_temp_c is None or b.current_temp_c < SAFETY_MAX_C)],
            key=lambda b: (b.priority, -b.temp_deficit_c))
        for b in group.boilers:
            is_on = self._is_on(b.entity_id, b)
            if b._manual_override_until > time.time():
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "hold_off", "manual override actief", is_on, group.id, 0.0))
                continue
            if b not in candidates:
                if is_on: await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
                decisions.append(BoilerDecision(b.entity_id, b.label,
                    "turn_off" if is_on else "hold_off", "Op setpoint", is_on, group.id, 0.0))
                continue
            reason = f"prio={b.priority}, tekort {b.temp_deficit_c:.1f}°C"
            action = self._apply_timers(b, True, is_on, now, reason)
            if action == "turn_on":
                # v4.6.507: back-off bij herhaalde no-response
                if self._check_turn_on_no_response(b, is_on):
                    await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
                else:
                    action = "hold_off"
                    reason = f"back-off: {b._no_response_count}x geen respons op turn_on"
            decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, 100.0))
        await self._async_save_power()
        await self._async_save_ramp()
        return decisions

    def _group_standby(self, group: CascadeGroup) -> list[BoilerDecision]:
        return [BoilerDecision(b.entity_id, b.label, "hold_off", "Standby — geen trigger",
                               self._is_on(b.entity_id, b), group.id, 0.0) for b in group.boilers]

    # ── Sensoren lezen ────────────────────────────────────────────────────────

    async def _read_sensors(self) -> None:
        now = time.time()
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            # Read altijd eerst de temperature uit de boiler-entity zelf
            # (water_heater / climate leveren current_temperature als attribuut)
            _entity_temp_c: float | None = None
            _boiler_state = self._hass.states.get(b.entity_id)
            if _boiler_state:
                # Read current_temperature ook bij "unavailable" state —
                # cloud-integraties (Ariston, 429) bewaren attributes na temporary falen.
                # Alleen overslaan bij volledig ontbrekende state (None entity).
                _cur_t = _boiler_state.attributes.get("current_temperature")
                if _cur_t is not None:
                    try:
                        _candidate = float(_cur_t)
                        # Saniteitscheck: valide watertemperature 5-95°C
                        if 5.0 <= _candidate <= 95.0:
                            _entity_temp_c = _candidate
                    except (ValueError, TypeError):
                        pass

            # Read configurede temp_sensor
            _sensor_temp_c: float | None = None
            if b.temp_sensor:
                s = self._hass.states.get(b.temp_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        _sensor_temp_c = float(s.state)
                    except (ValueError, TypeError):
                        pass

            # Kies de beste temperaturesbron:
            # Als de configurede sensor >15°C afwijkt van de boiler-entity,
            # is de sensor waarschijnlijk verkeerd configured (bijv. koud-inlaat).
            # Return dan voorrang aan de boiler-entity zelf.
            if _sensor_temp_c is not None and _entity_temp_c is not None:
                if abs(_sensor_temp_c - _entity_temp_c) > 15.0:
                    _LOGGER.warning(
                        "BoilerController [%s]: temp_sensor '%s' geeft %.1f°C maar "
                        "boiler-entiteit rapporteert %.1f°C (verschil >15°C). "
                        "Gebruik boiler-entiteit temperatuur. "
                        "Controleer bu_temp_sensor configuratie.",
                        b.entity_id, b.temp_sensor, _sensor_temp_c, _entity_temp_c,
                    )
                    b.current_temp_c = _entity_temp_c
                else:
                    b.current_temp_c = _sensor_temp_c
            elif _sensor_temp_c is not None:
                b.current_temp_c = _sensor_temp_c
            elif _entity_temp_c is not None:
                b.current_temp_c = _entity_temp_c

            # v4.6.94: update cache bij elke succesvolle lezing
            if b.current_temp_c is not None:
                b._last_known_temp_c = b.current_temp_c
                # v4.6.125: persist naar storage zodat temp restart overleeft
                # v4.6.129: gebruik hass.async_create_task ipv ensure_future (correct HA patroon)
                try:
                    self._hass.async_create_task(self._save_temp(b.entity_id, b.current_temp_c))
                except Exception:
                    pass
            elif b._last_known_temp_c is not None:
                # Entiteit temporary unavailable (bijv. Ariston cloud write) — gebruik cache
                b.current_temp_c = b._last_known_temp_c
            elif b._last_known_temp_c is None:
                # v4.6.121: eerste cycle na restart — read uit recorder sensor als fallback
                import re as _re
                _slug = _re.sub(r"[^a-z0-9]+", "_", (b.label or "").lower()).strip("_")
                _rec_eid = f"sensor.cloudems_boiler_{_slug}_temp"
                try:
                    _rec_st = self._hass.states.get(_rec_eid)
                    if _rec_st and _rec_st.state not in ("unavailable", "unknown", "None", ""):
                        _rec_val = float(_rec_st.state)
                        if 5.0 <= _rec_val <= 95.0:
                            b._last_known_temp_c = _rec_val
                            b.current_temp_c = _rec_val
                except Exception:
                    pass

            # Laatste fallback: boiler aan maar trekt geen power → al op temperature
            if b.current_temp_c is None and b.current_power_w is not None:
                _is_on = self._is_on(b.entity_id, b)
                if _is_on and b.current_power_w < 50 and b.power_w > 100:
                    b.current_temp_c = b.setpoint_c  # voorkomt onnodige trigger

            if b.energy_sensor:
                s = self._hass.states.get(b.energy_sensor)
                _s_state = s.state if s else "ENTITY_NOT_FOUND"
                _LOGGER.debug(
                    "BoilerController [%s]: energy_sensor='%s' state='%s'",
                    b.label, b.energy_sensor, _s_state,
                )
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        val  = float(s.state)
                        unit = (s.attributes.get("unit_of_measurement") or "").lower()
                        prev_ts = b._energy_ts_last
                        if "kwh" in unit:
                            prev = b._energy_kwh_last
                            b._energy_kwh_last = val
                            if prev is not None and val >= prev and prev_ts is not None:
                                delta = val - prev
                                dt_h  = (now - prev_ts) / 3600
                                b.cycle_kwh += delta
                                measured_w = (delta / dt_h * 1000) if dt_h > 0 else 0
                                # v5.5.52: altijd current_power_w zetten (ook laag vermogen)
                                # Leren alleen bij > 50W (voorkomt leren van standby)
                                b.current_power_w = measured_w
                                if measured_w > 50:
                                    b.power_w = round(b.power_w * 0.85 + measured_w * 0.15, 0)
                                    self._power_dirty = True
                                # ── Anode-slijtage bijwerken ─────────────────
                                # Zoek de learner van de groep waartoe deze boiler behoort
                                for _g in self._groups:
                                    if b in _g.boilers and _g.learner:
                                        _g.learner.update_anode_wear(b, delta)
                                        break
                        else:
                            b.current_power_w = val
                            if val > 50:
                                b.power_w = round(b.power_w * 0.85 + val * 0.15, 0)
                            if prev_ts is not None:
                                b.cycle_kwh += val * ((now - prev_ts) / 3_600_000)
                        b._energy_ts_last = now
                        _LOGGER.debug(
                            "BoilerController [%s]: energy_sensor gelezen → current_power_w=%.1f W",
                            b.label, b.current_power_w or 0.0,
                        )
                    except (ValueError, TypeError) as _e:
                        _LOGGER.warning(
                            "BoilerController [%s]: energy_sensor '%s' parse fout: %s (state='%s')",
                            b.label, b.energy_sensor, _e, s.state if s else "?",
                        )
            else:
                # Geen energiesensor configured — probeer auto-detectie op hetzelfde HA-device
                # (bijv. Ariston Lydos Hybrid heeft sensor.*_electric_power of sensor.*_power_w)
                _auto_power_read = False
                if not b._cached_power_entity:
                    try:
                        from homeassistant.helpers import entity_registry as _er_mod
                        _er = _er_mod.async_get(self._hass)
                        _entry = _er.async_get(b.entity_id)
                        if _entry and _entry.device_id:
                            # Sla per-fase en current-sensoren over (Ariston heeft bijv. Fase L1/L2/L3)
                            # Sla per-fase, current en energietellers over.
                            # "energy"/"kwh" NIET skippen — device_class=power check voorkomt kWh-sensoren al.
                            # Ariston heeft bijv. sensor.*_electric_power die "energy" niet bevat maar
                            # ook sensors die het wel bevatten.
                            _SKIP_KW = ("fase", "_l1", "_l2", "_l3", "phase",
                                        "current", "average", "import", "export",
                                        "tariff", "tari")
                            _best: tuple = (0.0, "")  # (power_w, entity_id)
                            for _e in _er.entities.values():
                                if _e.device_id != _entry.device_id or _e.domain != "sensor":
                                    continue
                                _eid_low = _e.entity_id.lower()
                                if any(kw in _eid_low for kw in _SKIP_KW):
                                    continue
                                _st = self._hass.states.get(_e.entity_id)
                                if not _st or _st.state in ("unavailable", "unknown", ""):
                                    continue
                                _dc = (_st.attributes.get("device_class") or "").lower()
                                if _dc != "power":
                                    continue
                                try:
                                    _pw = float(_st.state)
                                    _unit = (_st.attributes.get("unit_of_measurement") or "").lower()
                                    if "kw" in _unit and "kwh" not in _unit:
                                        _pw *= 1000.0
                                    # Kies sensor met hoogste power = meest waarschijnlijk totaal
                                    if _pw > _best[0]:
                                        _best = (_pw, _e.entity_id)
                                except (ValueError, TypeError):
                                    pass
                            if _best[1]:
                                b._cached_power_entity = _best[1]
                                _LOGGER.debug(
                                    "BoilerController [%s]: auto-detected power_entity='%s' (%.0fW)",
                                    b.label, _best[1], _best[0],
                                )
                    except Exception:
                        pass

                if b._cached_power_entity:
                    _ps = self._hass.states.get(b._cached_power_entity)
                    if _ps and _ps.state not in ("unavailable", "unknown", ""):
                        try:
                            _pw = float(_ps.state)
                            _unit = (_ps.attributes.get("unit_of_measurement") or "").lower()
                            if "kw" in _unit and "kwh" not in _unit:
                                _pw *= 1000.0
                            b.current_power_w = round(_pw, 1)
                            if _pw > 50:
                                b.power_w = round(b.power_w * 0.9 + _pw * 0.1, 0)
                            _auto_power_read = True
                        except (ValueError, TypeError):
                            pass

                if not _auto_power_read:
                    # NILM fallback: zoek boiler in sensor.cloudems_nilm_devices
                    # op basis van label-match of entity_id. NILM detecteert power
                    # passief via de P1-meter — ook zonder energiesensor op de boiler zelf.
                    try:
                        _nilm_st = self._hass.states.get("sensor.cloudems_nilm_devices")
                        if _nilm_st:
                            _nilm_devs = (_nilm_st.attributes.get("devices")
                                          or _nilm_st.attributes.get("device_list") or [])
                            _b_label_low = (b.label or "").lower()
                            _b_eid_low   = b.entity_id.lower()
                            for _nd in _nilm_devs:
                                _nd_name = (_nd.get("name") or _nd.get("user_name") or "").lower()
                                _nd_type = (_nd.get("device_type") or "").lower()
                                # Match op label of 'boiler'/'water_heater' type
                                _match = (
                                    (_b_label_low and _nd_name and _b_label_low in _nd_name)
                                    or (_nd_type in ("boiler", "water_heater", "electric_water_heater"))
                                )
                                if _match and _nd.get("is_on"):
                                    _nilm_w = float(_nd.get("power_w") or 0.0)
                                    if _nilm_w > 1:
                                        b.current_power_w = _nilm_w
                                        # Leer via EMA — NILM is minder nauwkeurig dan directe sensor
                                        b.power_w = round(b.power_w * 0.95 + _nilm_w * 0.05, 0)
                                        # Accumuleer kWh via NILM power (10s interval)
                                        b.cycle_kwh += (_nilm_w / 1000.0) * (10.0 / 3600.0)
                                        _auto_power_read = True
                                        _LOGGER.debug(
                                            "BoilerController [%s]: NILM vermogen %.0fW "
                                            "(device: %s)",
                                            b.label, _nilm_w, _nd.get("name", "?"),
                                        )
                                        break
                    except Exception as _nilm_err:
                        _LOGGER.debug("BoilerController NILM-fallback fout: %s", _nilm_err)

                if not _auto_power_read:
                    # Laatste fallback: switchstatus als schatting
                    is_currently_on = self._is_on(b.entity_id, b)
                    b.current_power_w = b.power_w if is_currently_on else 0.0

            if b.flow_sensor:
                s = self._hass.states.get(b.flow_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        flow_active = s.state in ("on", "true", "1") or float(s.state) > 0.5
                        if flow_active:
                            b.last_demand_ts = now
                            for g in self._groups:
                                if b in g.boilers and g.learner:
                                    g.learner.record_demand(datetime.now().hour)
                    except (ValueError, TypeError):
                        pass
            else:
                # FIX 1: temperaturedip als consumptionssignaal (geen flow sensor nodig).
                # Als boiler UIT is en temp daalt > 3°C t.o.v. vorige meting → warm water getapt.
                # Sla vorige temp op in _prev_temp_for_dip en detect de dip.
                if b.current_temp_c is not None:
                    _prev_dip = getattr(b, "_prev_temp_for_dip", None)
                    if _prev_dip is not None and not self._is_on(b.entity_id, b):
                        _dip = _prev_dip - b.current_temp_c
                        if _dip >= 3.0:
                            b.last_demand_ts = now
                            for g in self._groups:
                                if b in g.boilers and g.learner:
                                    g.learner.record_demand(datetime.now().hour)
                                    _LOGGER.debug(
                                        "BoilerController [%s]: temp-dip %.1f°C → warm water "
                                        "verbruik geregistreerd (%02d:00)",
                                        b.label, _dip, datetime.now().hour,
                                    )
                    b._prev_temp_for_dip = b.current_temp_c

            # ── Thermisch model: heat_rate leren + legionella tick ────────────
            # Alleen als de boiler bij een groep met learner hoort
            for _grp in self._groups:
                if b not in _grp.boilers or not _grp.learner:
                    continue
                _is_on_now = self._is_on(b.entity_id, b)

                # FIX 1+3: Tankvolume leren + ramp AAN-tijd bijhouden
                # Generaliseerd voor alle boilertypen waarbij power bekend is.
                # COP-correctie: voor WP/hybrid is consumption elektrisch → thermisch = elec × COP.
                _has_power_data = (b.cycle_kwh > 0.0 or b.current_power_w is not None)
                if _has_power_data and b.current_temp_c is not None:
                    if _is_on_now:
                        # Start nieuwe verwarmingscycle
                        if b._cycle_start_temp_c is None:
                            b._cycle_start_temp_c = b.current_temp_c
                            b._cycle_start_kwh    = b.cycle_kwh
                        # FIX 1: accumuleer AAN-minuten voor ramp-stap (hybrid)
                        if b.boiler_type == BOILER_TYPE_HYBRID:
                            if not hasattr(b, "_ramp_on_min_acc"):
                                b._ramp_on_min_acc = 0.0
                            b._ramp_on_min_acc += (10.0 / 60.0)  # 10s cycle → minuten
                    else:
                        # Boiler net UIT — probeer tankvolume te leren
                        if (b._cycle_start_temp_c is not None
                                and b.current_temp_c is not None
                                and b.current_temp_c > b._cycle_start_temp_c + 2.0):
                            _delta_t   = b.current_temp_c - b._cycle_start_temp_c
                            _delta_kwh_elec = b.cycle_kwh - b._cycle_start_kwh
                            # COP-correctie: WP/hybrid consumptionen elektrisch, leveren thermisch.
                            # Resistief: COP=1 (elektr. = thermisch).
                            # Gebruik buiten-COP als available, anders type-gebaseerde schatting.
                            if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                                _cop_learn = _cop_from_temp(
                                    b.outside_temp_c, b.cop_curve_override
                                ) * COP_DHW_FACTOR
                            else:
                                _cop_learn = 1.0  # resistief of variabel
                            _delta_kwh_therm = _delta_kwh_elec * _cop_learn
                            # Alternatief als cycle_kwh nul is maar power_w bekend:
                            # schat op basis van AAN-tijd × power
                            if _delta_kwh_therm < 0.02 and b.current_power_w and b.current_power_w > 50:
                                _elapsed_h = (now - b.last_on_ts) / 3600.0 if b.last_on_ts > 0 else 0
                                _delta_kwh_therm = (b.current_power_w / 1000.0) * _elapsed_h * _cop_learn
                            # Q = m × c × ΔT  →  m [liter] = Q_therm / (0.001163 × ΔT)
                            if _delta_t > 2.0 and _delta_kwh_therm > 0.02:
                                _meas_l = _delta_kwh_therm / (0.001163 * _delta_t)
                                _meas_l = max(20.0, min(500.0, _meas_l))
                                # EMA α=0.15 — traag leren, filtert meetpieken
                                if b._learned_tank_l < 1.0:
                                    b._learned_tank_l = _meas_l
                                else:
                                    b._learned_tank_l = round(
                                        b._learned_tank_l * 0.85 + _meas_l * 0.15, 1
                                    )
                                _LOGGER.info(
                                    "BoilerController [%s]: geleerd tankvolume %.0fL "
                                    "(meting: %.0fL, ΔT=%.1f°C, ΔkWh_therm=%.3f, COP=%.2f)",
                                    b.label, b._learned_tank_l, _meas_l,
                                    _delta_t, _delta_kwh_therm, _cop_learn,
                                )
                        b._cycle_start_temp_c = None
                        b._cycle_start_kwh    = 0.0

                # FIX 2: Demand-boost feedback — was de boost nuttig?
                # Check 1.5-3u na demand-boost of er een temp-dip was (warm water consumptiont).
                # Zo ja → demand_correct teller omhoog (threshold verlagen).
                # Zo nee → demand_incorrect teller omhoog (threshold verhogen).
                if (b.boiler_type == BOILER_TYPE_HYBRID
                        and b._demand_boost_ts > 0
                        and b._temp_before_demand is not None
                        and b.current_temp_c is not None):
                    _since_boost = (now - b._demand_boost_ts) / 3600.0  # uren
                    if 1.5 <= _since_boost <= 3.0:
                        _temp_dip = b._temp_before_demand - b.current_temp_c
                        if _temp_dip > 3.0:
                            # Warm water consumptiont → boost was nuttig
                            _grp.learner._g().setdefault("demand_boost_stats", {})
                            _grp.learner._g()["demand_boost_stats"]["correct"] =                                 _grp.learner._g()["demand_boost_stats"].get("correct", 0) + 1
                            _LOGGER.info("BoilerController [%s]: demand-boost correct (dip %.1f°C)", b.label, _temp_dip)
                        elif _since_boost >= 2.5:
                            # Geen dip na 2.5u → boost was niet nodig
                            _grp.learner._g().setdefault("demand_boost_stats", {})
                            _grp.learner._g()["demand_boost_stats"]["incorrect"] =                                 _grp.learner._g()["demand_boost_stats"].get("incorrect", 0) + 1
                            _LOGGER.info("BoilerController [%s]: demand-boost overbodig (geen dip)", b.label)
                            b._demand_boost_ts    = 0.0  # reset
                            b._temp_before_demand = None
                        if _temp_dip > 3.0 or _since_boost >= 3.0:
                            b._demand_boost_ts    = 0.0
                            b._temp_before_demand = None

                # Heat_rate learning: alleen als boiler aan is en temp stijgt
                if _is_on_now and b.current_temp_c is not None:
                    _on_duration = now - b.last_on_ts if b.last_on_ts > 0 else 0
                    _grp.learner.update_heat_rate(b, _on_duration)

                # Kalkdetectie: bijwerken score op basis van heat_rate vs baseline
                if b.limescale_detect:
                    _scale = _grp.learner.update_scale_score(b)
                    if _scale >= SCALE_WARN_PCT:
                        _LOGGER.warning(
                            "BoilerController [%s]: kalkindex %.0f%% — overweeg ontkalkingsbeurt",
                            b.label, _scale,
                        )

                # Legionella-tick: registreer seconden op ≥65°C
                # FIX 3: BOOST boven legionella-temp telt ook als afgedekte cycle
                if (b.current_temp_c is not None
                        and b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID)
                        and not b.force_green
                        and b.current_temp_c >= LEGIONELLA_TEMP_C
                        and b.last_on_ts > 0):
                    _boost_duration_s = now - b.last_on_ts
                    _grp.learner.legionella_register_boost_high(
                        b.entity_id, b.current_temp_c, _boost_duration_s
                    )
                if b.current_temp_c is not None:
                    _completed = _grp.learner.legionella_tick(b.entity_id, b.current_temp_c)
                    if _completed:
                        try:
                            await self._hass.services.async_call(
                                "persistent_notification", "create",
                                {"title": "CloudEMS — Legionella cyclus voltooid",
                                 "message": (
                                     f"Boiler **{b.label}** heeft 1 uur op ≥{LEGIONELLA_TEMP_C:.0f}°C gestaan. "
                                     f"Legionella-preventie succesvol voltooid. "
                                     f"Volgende cyclus over ~{LEGIONELLA_INTERVAL_DAYS} dagen."
                                 ),
                                 "notification_id": f"cloudems_legionella_{b.entity_id}"},
                                blocking=False,
                            )
                        except Exception:
                            pass

                # Anode-warning
                _anode_pct = _grp.learner.get_anode_wear_pct(b)
                if _anode_pct >= ANODE_WARN_PCT:
                    _anode_kwh = _grp.learner.get_anode_kwh(b)
                    _LOGGER.warning(
                        "BoilerController [%s]: anode-slijtage %.0f%% (%.0f kWh doorvoer, "
                        "waterhardheid %.0f°dH) — anode controleren",
                        b.label, _anode_pct, _anode_kwh, b.water_hardness_dh,
                    )
                break  # boiler found in groep, stop zoeken

    # ── Timers ────────────────────────────────────────────────────────────────

    def _apply_timers(self, b, want_on, is_on, now, reason):
        if want_on  and not is_on: return "turn_on"  if now - b.last_off_ts >= b.min_off_s else "hold_off"
        if want_on  and is_on:     return "hold_on"
        if not want_on and is_on:  return "turn_off" if now - b.last_on_ts  >= b.min_on_s  else "hold_on"
        return "hold_off"

    # ── Is-on detectie ────────────────────────────────────────────────────────

    def _is_on(self, entity_id: str, boiler: Optional[BoilerState] = None) -> bool:
        s = self._hass.states.get(entity_id)
        if s is None:
            return False
        domain = entity_id.split(".")[0]
        ctrl   = boiler.control_mode if boiler else "switch"

        if ctrl == "preset":
            preset_on = boiler.preset_on if boiler else "boost"
            if domain == "water_heater":
                # v4.5.61: Ariston en andere water_heater integraties gebruiken
                # 'operation_mode' als attribuut, niet 'preset_mode'
                # v4.6.16: case-insensitief vergelijken (Ariston: UPPERCASE enum namen)
                op = s.attributes.get("operation_mode") or s.attributes.get("current_operation") or s.attributes.get("preset_mode") or s.state
                op_lower = (op or "").lower()
                # v4.6.615: generieke preset-check — als de huidige preset niet de
                # gewenste preset is, return False terug zodat CloudEMS opnieuw stuurt.
                # Werkt voor iMemory, eco, auto, of elke andere ongewenste toestand.
                # Geen specifieke Ariston-modelnamen nodig.
                return op_lower == preset_on.lower()
            return s.attributes.get("preset_mode", s.state) == preset_on

        if ctrl == "acrouter":
            # ACRouter heeft geen HA-entity — gebruik interne mode-tracking
            return (boiler._acrouter_last_mode if boiler else -1) > 0

        if ctrl == "dimmer":
            off_pct = boiler.dimmer_off_pct if boiler else 0.0
            if domain == "light":
                bri_pct = s.attributes.get("brightness_pct")
                if bri_pct is None:
                    bri_pct = round(s.attributes.get("brightness", 0) / 2.55)
                return float(bri_pct) > (off_pct + 2.0)
            try:
                return float(s.state) > (off_pct + 2.0)
            except (ValueError, TypeError):
                return False

        if ctrl in ("setpoint", "setpoint_boost"):
            if domain in ("climate", "water_heater"):
                return s.state not in ("off", "unavailable", "unknown")
            return s.state == "on"

        # v4.5.61: water_heater met control_mode="switch" (default) werd altijd False
        # omdat water_heater state nooit "on" is (bijv. "electric", "heat_pump").
        # Val terug op setpoint-logic voor dit domain.
        if domain == "water_heater":
            return s.state not in ("off", "unavailable", "unknown")

        return s.state == "on"

    # ── Schakelaar / dimmer ───────────────────────────────────────────────────


    def _check_turn_on_no_response(self, b: "BoilerState", is_on: bool) -> bool:
        """v4.6.507: Detecteer communicatiestoring — back-off als turn_on herhaaldelijk
        geen effect heeft (is_on blijft False terwijl we AAN proberen te zetten).

        Returns True als we mogen proberen aan te zetten, False als we in back-off zitten.
        Back-off schema: na 3 pogingen → 2 min wachten, na 6 → 5 min, na 10 → 15 min.
        """
        now = time.time()

        # v4.6.614: Als entity unavailable/unknown is → geen back-off tellen.
        # Unavailability is een HA/integratie probleem, geen communicatieerror CloudEMS→boiler.
        # Reset de teller en wait tot entity weer available is.
        _st = self._hass.states.get(b.entity_id)
        if _st is None or _st.state in ("unavailable", "unknown"):
            if b._no_response_count > 0:
                _LOGGER.info(
                    "BoilerController [%s]: entity '%s' is %s — back-off teller gereset, "
                    "wacht op herstel",
                    b.label, b.entity_id, _st.state if _st else "None",
                )
                b._no_response_count = 0
                b._no_response_backoff_until = 0.0
            return False  # niet aansturen zolang entity unavailable is

        if b._no_response_backoff_until > now:
            # v4.6.615: generieke preset mismatch check — als de huidige preset niet
            # de gewenste preset is, is dat geen communicatieerror maar een toestandswijziging
            # door de boiler zelf (iMemory, eco, auto, of toekomstige modes).
            # Reset back-off en send gewenste preset opnieuw.
            if b.entity_id.split(".")[0] == "water_heater" and b.control_mode == "preset":
                _wh_s = self._hass.states.get(b.entity_id)
                if _wh_s and _wh_s.state not in ("unavailable", "unknown"):
                    _op = (_wh_s.attributes.get("operation_mode") or
                           _wh_s.attributes.get("current_operation") or
                           _wh_s.attributes.get("preset_mode") or "").lower()
                    _want = b.preset_on.lower()  # altijd preset_on: deze functie is turn-on context
                    if _op and _op != _want:
                        _LOGGER.info(
                            "BoilerController [%s]: preset mismatch ('%s' ipv '%s') "
                            "— back-off gereset, stuur gewenste preset opnieuw",
                            b.label, _op, _want,
                        )
                        b._no_response_count = 0
                        b._no_response_backoff_until = 0.0
                        return True
            return False  # nog in back-off
        if is_on:
            # Boiler is AAN → reset teller
            b._no_response_count = 0
            return True
        # v4.6.615: generieke preset mismatch — niet tellen als geen respons.
        # Als de boiler een andere preset heeft dan gewenst (iMemory, eco, auto, enz.)
        # is dat geen communicatieerror maar een toestandswijziging door de boiler zelf.
        # CloudEMS stuurt gewenste preset opnieuw — geen back-off optellen.
        if b.entity_id.split(".")[0] == "water_heater" and b.control_mode == "preset":
            _wh_st = self._hass.states.get(b.entity_id)
            if _wh_st and _wh_st.state not in ("unavailable", "unknown"):
                _op = (_wh_st.attributes.get("operation_mode") or
                       _wh_st.attributes.get("current_operation") or
                       _wh_st.attributes.get("preset_mode") or "").lower()
                _want = b.preset_on.lower()  # altijd preset_on: deze functie is turn-on context
                if _op and _op != _want:
                    # Preset klopt niet — geen back-off, blijf rustig sturen
                    b._no_response_count = 0
                    return True
        # Boiler is UIT terwijl we al eerder turn_on stuurden
        if b.last_on_ts > 0 and (now - b.last_on_ts) < 120:
            # Binnen 2 minuten na turn_on: tel als geen respons
            b._no_response_count += 1
        else:
            b._no_response_count = 0
            return True
        # Back-off thresholds
        if b._no_response_count >= 10:
            b._no_response_backoff_until = now + 900  # 15 min
            _LOGGER.warning(
                "BoilerController [%s]: 10x turn_on zonder respons — 15 min pauze "
                "(communicatiestoring?)", b.label,
            )
            return False
        elif b._no_response_count >= 6:
            b._no_response_backoff_until = now + 300  # 5 min
            _LOGGER.warning(
                "BoilerController [%s]: 6x turn_on zonder respons — 5 min pauze", b.label,
            )
            return False
        elif b._no_response_count >= 3:
            b._no_response_backoff_until = now + 120  # 2 min
            _LOGGER.info(
                "BoilerController [%s]: 3x turn_on zonder respons — 2 min pauze", b.label,
            )
            return False
        return True

    async def _switch_smart(self, entity_id: str, on: bool,
                             boiler: Optional[BoilerState] = None,
                             solar_surplus_w: float = 0.0) -> None:
        try:
            if boiler and boiler.control_mode == "acrouter":
                await self._acrouter_set(boiler, on, solar_surplus_w)
                return
            if on and boiler and boiler.control_mode == "dimmer" and boiler.dimmer_proportional:
                await self._switch_dimmer_prop(entity_id, boiler, solar_surplus_w)
                return
            # v5.5.35: centrale gas-check — één plek voor alle BOOST paden
            # Als boiler AAN wordt gezet (on=True) en force_green=False (→ BOOST)
            # én gebruiker heeft gas én gas goedkoper dan stroom → forceer GREEN
            # Dit vangt elk pad op: demand boost, seq levering, direct hybrid, etc.
            if (on and boiler
                    and boiler.control_mode == "preset"
                    and not boiler.force_green
                    and boiler.has_gas_heating == "yes"
                    and boiler._manual_override_until <= 0.0):
                _price_info = getattr(self, "_last_price_info", {})
                # v5.5.39: gebruik all-in prijs, niet EPEX raw
                _cp = float(_price_info.get("current_all_in") or _price_info.get("current", 0.25) or 0.25)
                _gp = float(_price_info.get("gas_price_eur_m3", 1.25) or 1.25)
                _gt = _gp / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
                if _cp > _gt:  # stroom duurder dan gas → geen BOOST
                    _LOGGER.info(
                        "BoilerController [%s]: BOOST geblokkeerd — gas (%.1fct) goedkoper dan stroom (%.1fct/kWh_th)",
                        boiler.label, _gt * 100, _cp * 100,
                    )
                    boiler.force_green = True
            await self._switch(entity_id, on, boiler)
        except Exception as _sw_exc:
            # v4.6.186: vang cloud-erroren op (bijv. Ariston 429) zodat de coordinator
            # cycle niet crasht. De boiler houdt zijn huidige toestand tot de volgende cycle.
            _LOGGER.warning(
                "BoilerController [%s]: schakelcommando mislukt (%s → %s), overgeslagen: %s",
                boiler.label if boiler else entity_id, entity_id, "AAN" if on else "UIT", _sw_exc,
            )

    async def _switch_dimmer_prop(self, entity_id: str, boiler: BoilerState,
                                   solar_surplus_w: float) -> None:
        now = time.time()
        if now - boiler._dimmer_last_ts < DIMMER_UPDATE_S:
            return
        domain  = entity_id.split(".")[0]
        raw_pct = (solar_surplus_w / boiler.power_w * 100.0) if solar_surplus_w > 0 else DIMMER_MIN_PCT
        pct     = max(DIMMER_MIN_PCT, min(boiler.dimmer_on_pct, raw_pct))
        pct     = round(pct / 5) * 5
        if abs(pct - boiler._dimmer_last_pct) < 5.0:
            return
        boiler._dimmer_last_pct = pct
        boiler._dimmer_last_ts  = now
        if domain == "light":
            await self._hass.services.async_call("light", "turn_on",
                {"entity_id": entity_id, "brightness_pct": round(pct)}, blocking=False)
        else:
            await self._hass.services.async_call("number", "set_value",
                {"entity_id": entity_id, "value": pct}, blocking=False)
        _LOGGER.debug("Dimmer prop %s → %.0f%% (surplus %.0fW)", entity_id, pct, solar_surplus_w)

    async def _acrouter_set(self, boiler: BoilerState, on: bool,
                             solar_surplus_w: float) -> None:
        """Stuur ACRouter device aan via REST API.

        Modi die CloudEMS gebruikt:
          - on=True,  surplus > 0  → MANUAL mode, dimmer = surplus_w / power_w * 100%
          - on=True,  surplus = 0  → BOOST mode (goedkoop uur, volgas)
          - on=False              → OFF mode

        REST API (ACRouter firmware v1.2.0+):
          POST /api/mode   {"mode": N}   — stel modus in
          POST /api/dimmer {"level": N}  — dimmer 0-100% (alleen in MANUAL mode)
        """
        if not boiler.acrouter_host:
            _LOGGER.warning("ACRouter: acrouter_host niet geconfigureerd voor boiler '%s'",
                            boiler.label)
            return

        if not _AIOHTTP_AVAILABLE:
            _LOGGER.error("ACRouter: aiohttp niet beschikbaar — kan device niet aansturen")
            return

        now = time.time()

        # Bepaal gewenste mode en dimmer-percentage
        if not on:
            target_mode = ACROUTER_MODE_OFF
            target_pct  = 0.0
        elif solar_surplus_w > 0:
            target_mode = ACROUTER_MODE_MANUAL
            raw_pct     = (solar_surplus_w / boiler.power_w * 100.0) if boiler.power_w > 0 else 100.0
            target_pct  = max(5.0, min(100.0, round(raw_pct / 5) * 5))  # stap 5%, min 5%
        else:
            # on=True maar geen surplus → goedkoop uur, boost
            target_mode = ACROUTER_MODE_BOOST
            target_pct  = 100.0

        # Debounce: send alleen als mode of pct significant veranderd is
        mode_changed = (target_mode != boiler._acrouter_last_mode)
        pct_changed  = (target_mode == ACROUTER_MODE_MANUAL and
                        abs(target_pct - boiler._acrouter_last_pct) >= 5.0)
        throttled    = (now - boiler._acrouter_last_ts < ACROUTER_UPDATE_S)

        if not mode_changed and not pct_changed:
            return
        if pct_changed and not mode_changed and throttled:
            return  # kleine surplus-variatie, wait op throttle-interval

        base_url = f"http://{boiler.acrouter_host}"
        try:
            timeout = _aiohttp.ClientTimeout(total=ACROUTER_HTTP_TIMEOUT)
            async with _aiohttp.ClientSession(timeout=timeout) as session:

                # Send mode
                async with session.post(
                    f"{base_url}/api/mode",
                    json={"mode": target_mode},
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("ACRouter: /api/mode → HTTP %d", resp.status)
                        return

                # In MANUAL mode: send ook dimmer-percentage
                if target_mode == ACROUTER_MODE_MANUAL:
                    async with session.post(
                        f"{base_url}/api/dimmer",
                        json={"level": int(target_pct)},
                    ) as resp:
                        if resp.status != 200:
                            _LOGGER.warning("ACRouter: /api/dimmer → HTTP %d", resp.status)
                            return

            # Sla succesvolle state op
            boiler._acrouter_last_mode = target_mode
            boiler._acrouter_last_pct  = target_pct
            boiler._acrouter_last_ts   = now

            mode_name = {0: "OFF", 4: "MANUAL", 5: "BOOST"}.get(target_mode, str(target_mode))
            if target_mode == ACROUTER_MODE_MANUAL:
                _LOGGER.debug("ACRouter [%s] → %s %.0f%% (surplus %.0fW)",
                              boiler.label, mode_name, target_pct, solar_surplus_w)
            else:
                _LOGGER.debug("ACRouter [%s] → %s", boiler.label, mode_name)

        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ACRouter [%s]: communicatiefout — %s", boiler.label, err)

    async def _send_setpoint_sequence(
        self,
        boiler: Optional["BoilerState"],
        entity_id: str,
        preset: str,
        target_sp: float,
        max_setpoint_entity: str,
    ) -> None:
        """
        Stap 2-5 van de Ariston stuurvolgorde: max_setpoint + temperature.
        Aangroepen vanuit de CloudCommandQueue executor.
        """
        # Stap 3: max_setpoint number aanpassen ná mode-switch
        if boiler and max_setpoint_entity:
            _max_ent_state = self._hass.states.get(max_setpoint_entity)
            if _max_ent_state is not None:
                _is_boost = (preset == boiler.preset_on)
                if _is_boost:
                    _ramp_active = (
                        boiler.boiler_type == BOILER_TYPE_HYBRID
                        and boiler._cheap_ramp_setpoint_c > 0
                        and boiler._manual_override_until <= time.time()
                    )
                    _desired_max = (
                        min(boiler._cheap_ramp_setpoint_c + 2.0, boiler.max_setpoint_boost_c)
                        if _ramp_active else boiler.max_setpoint_boost_c
                    )
                else:
                    _desired_max = boiler.max_setpoint_green_c
                try:
                    _hw_max = _max_ent_state.attributes.get("max")
                    if _hw_max is not None:
                        _desired_max = min(_desired_max, float(_hw_max))
                    _cur_max = float(_max_ent_state.state)
                except (ValueError, TypeError):
                    _cur_max = None
                if _cur_max is None or abs(_cur_max - _desired_max) > 0.5:
                    _domain = max_setpoint_entity.split(".")[0]
                    if self._hass.services.has_service(_domain, "set_value"):
                        _attrs = _max_ent_state.attributes
                        _min = float(_attrs.get("min", 0))
                        _max = float(_attrs.get("max", 99999))
                        _desired_max = max(_min, min(_max, _desired_max))
                        await self._hass.services.async_call(
                            _domain, "set_value",
                            {"entity_id": max_setpoint_entity, "value": _desired_max},
                            blocking=True,
                        )
                        _LOGGER.debug(
                            "BoilerController [%s]: max_setpoint '%s' → %.1f°C (preset=%s)",
                            boiler.label, max_setpoint_entity, _desired_max, preset,
                        )
                        # Stap 4: wait tot max_setpoint active is
                        await asyncio.sleep(1)

        # Stap 5: setpoint sturen
        if self._hass.services.has_service("water_heater", "set_temperature"):
            await self._hass.services.async_call(
                "water_heater", "set_temperature",
                {"entity_id": entity_id, "temperature": target_sp},
                blocking=True,
            )
        _LOGGER.info(
            "BoilerController [%s]: ✓ water_heater preset=%s max=%.0f°C setpoint=%.1f°C",
            boiler.label if boiler else entity_id, preset,
            boiler.max_setpoint_boost_c if boiler else 0, target_sp,
        )

    async def _switch(self, entity_id: str, on: bool,
                      boiler: Optional[BoilerState] = None) -> None:
        domain = entity_id.split(".")[0] if "." in entity_id else "switch"
        ctrl   = boiler.control_mode if boiler else "switch"

        if ctrl == "preset":
            # HEAT_PUMP/HYBRID: als force_green=True → gebruik preset_off (WP-element)
            # anders gebruik preset_on (boost/weerstandselement)
            if boiler and on and boiler.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                preset = boiler.preset_off if boiler.force_green else boiler.preset_on
            else:
                preset = (boiler.preset_on if on else boiler.preset_off) if boiler else ("boost" if on else "green")

            # Bepaal het juiste setpoint voor dit preset:
            # - green (WP-element): normaal setpoint (active_setpoint_c of setpoint_c)
            # - boost (weerstandselement bij surplus): surplus_setpoint_c voor maximale buffer
            # - boost (bij goedkope uren, geen surplus): normaal setpoint volstaat
            if boiler:
                is_boost = (preset == boiler.preset_on)
                if is_boost and boiler.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                    # v4.6.495: respecteer de graduele ramp (active_setpoint_c) ook in BOOST.
                    # Eerder stuurde BOOST altijd max_setpoint_boost_c (75°C) als temperature,
                    # waardoor de ramp-bescherming tegen doorverwarmen bij communicatiestoring
                    # volledig werd genegeerd.
                    # Nu: gebruik active_setpoint_c als die via de ramp is geset (hybrid),
                    # anders val terug op max_setpoint_boost_c (niet-ramp boilers).
                    _auto_boost_sp = boiler.max_setpoint_boost_c if boiler.max_setpoint_boost_c > 0 else boiler.surplus_setpoint_c
                    _active_sp = boiler.active_setpoint_c or boiler.setpoint_c
                    _is_manual = boiler._manual_override_until > time.time()
                    _ramp_active = (
                        boiler.boiler_type == BOILER_TYPE_HYBRID
                        and boiler._cheap_ramp_setpoint_c > 0
                        and not _is_manual
                    )
                    if _is_manual and _active_sp > 0 and _active_sp < _auto_boost_sp:
                        target_sp = _active_sp
                    elif _ramp_active:
                        # Ramp active: send de graduele ramp-value, nooit direct de max
                        target_sp = round(min(boiler._cheap_ramp_setpoint_c, _auto_boost_sp), 1)
                    else:
                        target_sp = _auto_boost_sp
                elif not on:
                    # uitzetten: min_temp_c zodat boiler niet onnodig door blijft lopen
                    target_sp = boiler.min_temp_c
                else:
                    target_sp = boiler.active_setpoint_c or boiler.setpoint_c
                # v4.6.16: cap target_sp per mode — GREEN kan nooit boven max_setpoint_green_c
                # komen, BOOST nooit boven max_setpoint_boost_c. Voorkomt dat CloudEMS
                # 78°C stuurt naar een Ariston Lydos die maar 53°C (GREEN) of 75°C (BOOST) aankan.
                if boiler.control_mode == "preset" and is_boost:
                    _preset_cap = boiler.max_setpoint_boost_c if boiler.max_setpoint_boost_c > 0 else boiler.hw_ceiling
                elif boiler.control_mode == "preset" and on:
                    # GREEN aan: cap op green-maximum
                    _preset_cap = boiler.max_setpoint_green_c if boiler.max_setpoint_green_c > 0 else boiler.hw_ceiling
                else:
                    _preset_cap = boiler.hw_ceiling
                target_sp = round(min(target_sp, _preset_cap, boiler.hw_ceiling), 1)
            else:
                target_sp = FALLBACK_SETPOINT_ON_C if on else FALLBACK_SETPOINT_OFF_C

            if domain == "climate":
                await self._hass.services.async_call("climate", "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": preset}, blocking=False)
                # Send ook setpoint zodat de boiler weet wanneer hij klaar is
                if self._hass.services.has_service("climate", "set_temperature"):
                    await self._hass.services.async_call("climate", "set_temperature",
                        {"entity_id": entity_id, "temperature": target_sp}, blocking=False)
                _LOGGER.debug("BoilerController [%s]: climate preset=%s + setpoint=%.1f°C",
                              boiler.label if boiler else entity_id, preset, target_sp)
                return
            if domain == "water_heater":
                # v4.6.5: Ariston Lydos e.d. begrenzen setpoint per mode via een apart
                # number-entity (bijv. number.ariston_max_setpoint_temperature).
                # In GREEN-mode staat dit op bijv. 53°C — dan kan set_temperature(60) nooit
                # effectief zijn. Set het number EERST op de juiste value vóór de modewisseling:
                #   BOOST aan  → max_setpoint_boost_c (bijv. 75°C) zodat het setpoint ranget kan worden
                #   GREEN aan  → max_setpoint_green_c (bijv. 53°C) zodat GREEN correct werkt

                # v4.6.52: gebruik gecachede value, scan entity registry maar 1x
                _resolved_max_entity = boiler.max_setpoint_entity if boiler else ""
                if boiler and not _resolved_max_entity:
                    if boiler._cached_max_setpoint_entity:
                        _resolved_max_entity = boiler._cached_max_setpoint_entity
                    else:
                        try:
                            from homeassistant.helpers import entity_registry as er
                            _er = er.async_get(self._hass)
                            _boiler_entry = _er.async_get(entity_id)
                            if _boiler_entry and _boiler_entry.device_id:
                                _device_id = _boiler_entry.device_id
                                for _entry in _er.entities.values():
                                    if (
                                        _entry.device_id == _device_id
                                        and _entry.domain == "number"
                                        and "max_setpoint" in _entry.entity_id
                                    ):
                                        _resolved_max_entity = _entry.entity_id
                                        boiler._cached_max_setpoint_entity = _entry.entity_id
                                        _LOGGER.debug(
                                            "BoilerController [%s]: auto-detected max_setpoint_entity='%s' (gecached)",
                                            boiler.label, _resolved_max_entity,
                                        )
                                        break
                        except Exception as _e:
                            _LOGGER.debug("BoilerController: max_setpoint auto-detect fout: %s", _e)

                # v4.6.16: Case-correctie voor integraties die UPPERCASE operation modes
                # gebruiken (bijv. Ariston library: LydosPlantMode.GREEN/BOOST).
                _wh_state = self._hass.states.get(entity_id)
                _op_list  = _wh_state.attributes.get("operation_list", []) if _wh_state else []
                _preset_to_send = preset
                if _op_list and preset not in _op_list:
                    _matched = next((op for op in _op_list if op.lower() == preset.lower()), None)
                    if _matched:
                        _LOGGER.debug(
                            "BoilerController [%s]: preset '%s' → '%s' (case-correctie operation_list)",
                            boiler.label if boiler else entity_id, preset, _matched,
                        )
                        _preset_to_send = _matched

                # v4.6.557: CloudCommandQueue gate — debounce + rate-limit + backoff
                # Build het volledige commando dat we willen sturen
                _desired_cmd = {
                    "preset":   _preset_to_send,
                    "setpoint": target_sp,
                    "entity":   entity_id,
                }
                # executor: de volledige stuurvolgorde als async callable
                #
                # Ariston BOOST accepteert NOOIT directe temperatuurwijzigingen (v5.5.2).
                # iMemory heeft geen setpoint-cap en BOOST erft altijd het iMemory setpoint over.
                #
                # Correcte volgorde voor BOOST (altijd, ongeacht setpoint):
                #   1. iMemory activeren  (tenzij al in iMemory)
                #   2. sleep 3s
                #   3. set_temperature → gewenst setpoint (geen hardware cap)
                #   4. sleep 3s
                #   5. BOOST activeren → erft setpoint van iMemory automatisch over
                #
                # Ook 45°C via BOOST gaat via iMemory — BOOST accepteert geen set_temperature.
                # GREEN-commando's: geen brug nodig, GREEN accepteert wel set_temperature.

                # Zoek iMemory in de operation_list
                _imemory_mode = None
                for _om in _op_list:
                    if _om.lower() == "imemory":
                        _imemory_mode = _om
                        break

                # iMemory brug: altijd bij BOOST als iMemory beschikbaar is in operation_list
                _use_imemory_bridge = (
                    boiler is not None
                    and _imemory_mode is not None
                    and _desired_cmd["preset"].lower() == (boiler.preset_on or "boost").lower()
                )

                async def _ariston_executor(cmd: dict) -> None:
                    _ep  = cmd["preset"]
                    _esp = cmd["setpoint"]
                    _eid = cmd["entity"]

                    if _use_imemory_bridge and _imemory_mode:
                        # Reset back-off teller — iMemory brug is een bewuste actie, geen fout
                        if boiler:
                            boiler._no_response_count = 0
                            boiler._no_response_backoff_until = 0.0
                        # Controleer of boiler al in iMemory zit → sla stap 1+2 over
                        _current_state = self._hass.states.get(_eid)
                        _current_mode  = ""
                        if _current_state:
                            _current_mode = (
                                _current_state.attributes.get("operation_mode")
                                or _current_state.attributes.get("current_operation")
                                or _current_state.state or ""
                            ).lower()

                        _already_imemory = _current_mode == "imemory"

                        if not _already_imemory:
                            # Stap 1: iMemory activeren
                            _LOGGER.info(
                                "BoilerController [%s]: iMemory-brug → setpoint=%.1f°C",
                                boiler.label if boiler else _eid, _esp,
                            )
                            if self._hass.services.has_service("water_heater", "set_operation_mode"):
                                await self._hass.services.async_call("water_heater", "set_operation_mode",
                                    {"entity_id": _eid, "operation_mode": _imemory_mode}, blocking=True)
                            elif self._hass.services.has_service("water_heater", "set_preset_mode"):
                                await self._hass.services.async_call("water_heater", "set_preset_mode",
                                    {"entity_id": _eid, "preset_mode": _imemory_mode}, blocking=True)
                            # Stap 2: wacht tot iMemory actief is
                            await asyncio.sleep(3)
                        else:
                            _LOGGER.info(
                                "BoilerController [%s]: al in iMemory → stap 1 overgeslagen, setpoint=%.1f°C",
                                boiler.label if boiler else _eid, _esp,
                            )

                        # Stap 3: max_setpoint op 75°C zetten zodat hogere temperaturen
                        # geaccepteerd worden door de Ariston in iMemory
                        _max_eid = _resolved_max_entity
                        if _max_eid:
                            _ms = self._hass.states.get(_max_eid)
                            if _ms and _ms.state not in ("unavailable", "unknown"):
                                try:
                                    _hw_max  = float(_ms.attributes.get("max", 75.0))
                                    _hw_min  = float(_ms.attributes.get("min", 40.0))
                                    _want_max = min(75.0, _hw_max)
                                    _cur_max  = float(_ms.state)
                                    if abs(_cur_max - _want_max) > 0.5:
                                        _dom_max = _max_eid.split(".")[0]
                                        if self._hass.services.has_service(_dom_max, "set_value"):
                                            await self._hass.services.async_call(
                                                _dom_max, "set_value",
                                                {"entity_id": _max_eid, "value": _want_max},
                                                blocking=True,
                                            )
                                            _LOGGER.info(
                                                "BoilerController [%s]: max_setpoint → %.0f°C (was %.0f°C)",
                                                boiler.label if boiler else _eid, _want_max, _cur_max,
                                            )
                                            # Stap 3b: wacht op Ariston cloud bevestiging
                                            await asyncio.sleep(2)
                                            # Stap 3c: controleer of max_setpoint correct is
                                            _ms2 = self._hass.states.get(_max_eid)
                                            if _ms2 and _ms2.state not in ("unavailable", "unknown"):
                                                try:
                                                    _confirmed_max = float(_ms2.state)
                                                    if abs(_confirmed_max - _want_max) > 1.0:
                                                        _LOGGER.warning(
                                                            "BoilerController [%s]: max_setpoint niet bevestigd"
                                                            " (verwacht=%.0f actueel=%.0f) — toch doorgaan",
                                                            boiler.label if boiler else _eid,
                                                            _want_max, _confirmed_max,
                                                        )
                                                except (ValueError, TypeError):
                                                    pass
                                except (ValueError, TypeError):
                                    pass

                        # Stap 4: setpoint instellen in iMemory
                        if self._hass.services.has_service("water_heater", "set_temperature"):
                            await self._hass.services.async_call("water_heater", "set_temperature",
                                {"entity_id": _eid, "temperature": _esp}, blocking=True)
                        # Stap 5: wacht tot setpoint is overgenomen door Ariston cloud
                        await asyncio.sleep(3)
                        # Stap 6: BOOST activeren — erft iMemory setpoint automatisch over
                        if self._hass.services.has_service("water_heater", "set_operation_mode"):
                            await self._hass.services.async_call("water_heater", "set_operation_mode",
                                {"entity_id": _eid, "operation_mode": _ep}, blocking=True)
                        elif self._hass.services.has_service("water_heater", "set_preset_mode"):
                            await self._hass.services.async_call("water_heater", "set_preset_mode",
                                {"entity_id": _eid, "preset_mode": _ep}, blocking=True)
                        _LOGGER.info(
                            "BoilerController [%s]: iMemory-brug voltooid → BOOST actief met %.1f°C",
                            boiler.label if boiler else _eid, _esp,
                        )
                    else:
                        # Normale flow: directe mode-switch
                        if self._hass.services.has_service("water_heater", "set_operation_mode"):
                            await self._hass.services.async_call("water_heater", "set_operation_mode",
                                {"entity_id": _eid, "operation_mode": _ep}, blocking=True)
                        elif self._hass.services.has_service("water_heater", "set_preset_mode"):
                            await self._hass.services.async_call("water_heater", "set_preset_mode",
                                {"entity_id": _eid, "preset_mode": _ep}, blocking=True)
                        # Pauze na mode-switch
                        if boiler and _resolved_max_entity:
                            await asyncio.sleep(2)
                        # max_setpoint + setpoint
                        await self._send_setpoint_sequence(boiler, _eid, _ep, _esp, _resolved_max_entity)

                _sent = await self._cmd_queue.request(
                    device_id = entity_id,
                    command   = _desired_cmd,
                    executor  = _ariston_executor,
                )
                if not _sent:
                    # Gedebounced of geblokkeerd — log alleen op debug niveau
                    _q_diag = self._cmd_queue.get_diagnostics()
                    _slot   = _q_diag.get("devices", {}).get(entity_id, {})
                    _stable = time.time() - _slot.get("desired_since", time.time())
                    _backoff = _slot.get("backoff_until", 0) - time.time()
                    if _backoff > 0:
                        _LOGGER.debug(
                            "BoilerController [%s]: commando geblokkeerd (backoff %.0fs)",
                            boiler.label if boiler else entity_id, _backoff,
                        )
                    else:
                        _LOGGER.debug(
                            "BoilerController [%s]: debounce %.0f/%.0fs (preset=%s sp=%.1f°C)",
                            boiler.label if boiler else entity_id,
                            _stable, self._cmd_queue.debounce_s,
                            _preset_to_send, target_sp,
                        )
                    return

                # Succes — registreer als pending voor cloud verify/retry
                if boiler:
                    _max_sp_pending = 0.0
                    if _resolved_max_entity:
                        _is_boost_p = (preset == boiler.preset_on)
                        _max_sp_pending = boiler.max_setpoint_boost_c if _is_boost_p else boiler.max_setpoint_green_c
                    self._set_pending(boiler, _preset_to_send, target_sp, _max_sp_pending)
                return


                return

        if ctrl in ("setpoint", "setpoint_boost"):
            sp = ((boiler.active_setpoint_c or boiler.setpoint_c) if on else boiler.min_temp_c) if boiler else (FALLBACK_SETPOINT_ON_C if on else FALLBACK_SETPOINT_OFF_C)
            svc_domain = domain if domain in ("climate", "water_heater") else None
            if svc_domain:
                # v4.6.16: water_heater met ON_OFF feature (bijv. Midea E2/E3) vereist
                # turn_on/turn_off om de boiler echt aan/uit te zetten.
                # Send ALTIJD turn_on/turn_off zodat de boiler-power correct is,
                # daarna set_temperature voor het gewenste setpoint.
                if domain == "water_heater":
                    _on_off_svc = "turn_on" if on else "turn_off"
                    if self._hass.services.has_service("water_heater", _on_off_svc):
                        await self._hass.services.async_call(
                            "water_heater", _on_off_svc, {"entity_id": entity_id}, blocking=False
                        )
                    if not on:
                        # Uitzetten: geen set_temperature nodig, turn_off volstaat
                        _LOGGER.debug("BoilerController [%s]: water_heater turn_off",
                                      boiler.label if boiler else entity_id)
                        return

                # water_heater.set_temperature bestaat alleen als de water_heater-platform
                # geladen is. Bij ontbrekende service fallbacklen op turn_on/off zodat de
                # coordinator niet crasht.
                if self._hass.services.has_service(svc_domain, "set_temperature"):
                    await self._hass.services.async_call(svc_domain, "set_temperature",
                        {"entity_id": entity_id, "temperature": sp}, blocking=False)
                else:
                    _LOGGER.warning(
                        "BoilerController [%s]: service %s.set_temperature niet beschikbaar "
                        "— teruggevallen op turn_%s. Controleer of de %s-integratie actief is.",
                        boiler.label if boiler else entity_id, svc_domain,
                        "on" if on else "off", svc_domain,
                    )
                    fallback_svc = "turn_on" if on else "turn_off"
                    if self._hass.services.has_service(svc_domain, fallback_svc):
                        await self._hass.services.async_call(
                            svc_domain, fallback_svc, {"entity_id": entity_id}, blocking=False
                        )
                # setpoint_boost: bij surplus ook preset op boost zetten voor maximale opwarming
                if ctrl == "setpoint_boost" and on and domain == "climate":
                    surplus_sp = boiler.surplus_setpoint_c if boiler else 75.0
                    _is_surplus = (boiler.active_setpoint_c or 0) > (boiler.setpoint_c or 0) if boiler else False
                    if _is_surplus:
                        await self._hass.services.async_call("climate", "set_preset_mode",
                            {"entity_id": entity_id,
                             "preset_mode": boiler.preset_on if boiler else "boost"},
                            blocking=False)
                        _LOGGER.debug("BoilerController [%s]: setpoint_boost → preset=%s + %.0f°C",
                                      boiler.label if boiler else entity_id,
                                      boiler.preset_on if boiler else "boost", surplus_sp)
                    else:
                        # Normaal gebruik: preset terug naar off/green
                        await self._hass.services.async_call("climate", "set_preset_mode",
                            {"entity_id": entity_id,
                             "preset_mode": boiler.preset_off if boiler else "green"},
                            blocking=False)
                return

        if ctrl == "dimmer":
            pct = (boiler.dimmer_on_pct if on else boiler.dimmer_off_pct) if boiler else (100.0 if on else 0.0)
            if domain == "light":
                if pct <= 0:
                    await self._hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=False)
                else:
                    await self._hass.services.async_call("light", "turn_on",
                        {"entity_id": entity_id, "brightness_pct": round(pct)}, blocking=False)
            else:
                await self._hass.services.async_call("number", "set_value",
                    {"entity_id": entity_id, "value": pct}, blocking=False)
            return

        await self._hass.services.async_call(domain, "turn_on" if on else "turn_off",
            {"entity_id": entity_id}, blocking=False)

    # ── Externe updates ───────────────────────────────────────────────────────

    def update_outside_temp(self, temp_c: Optional[float]) -> None:
        for b in self._boilers: b.outside_temp_c = temp_c
        for g in self._groups:
            for b in g.boilers: b.outside_temp_c = temp_c

    def update_congestion_state(self, active: bool) -> None:
        for b in self._boilers: b.congestion_active = active
        for g in self._groups:
            for b in g.boilers: b.congestion_active = active

    def update_power_from_nilm(self, nilm_devices: list[dict]) -> None:
        """Leer boilervermogen uit NILM-metingen (wordt aangeroepen vanuit coordinator)."""
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            if b.energy_sensor:
                continue  # Energiesensor heeft priority boven NILM
            eid = b.entity_id
            # Zoek dit device op in de NILM-lijst op entity_id of naam
            for dev in nilm_devices:
                dev_eid = dev.get("source_entity_id", "") or dev.get("entity_id", "")
                dev_name = (dev.get("name") or dev.get("label") or "").lower()
                b_name = b.label.lower()
                if (dev_eid and dev_eid == eid) or (b_name and b_name in dev_name) or (dev_name and dev_name in b_name):
                    power_w = float(dev.get("current_power") or dev.get("power_w") or 0)
                    if power_w > 1 and dev.get("is_on"):
                        # EMA-update van learned power via NILM
                        b.power_w = round(b.power_w * 0.90 + power_w * 0.10, 0)
                        b.current_power_w = power_w
                        self._power_dirty = True
                        _LOGGER.debug(
                            "BoilerController [%s]: vermogen geleerd via NILM: %.0fW (EMA→%.0fW)",
                            b.label, power_w, b.power_w
                        )
                    break

    def async_p1_update(self, net_power_w: float) -> None:
        """
        Directe P1-telegramupdate (< 1s responstijd).
        net_power_w: positief = verbruik van net, negatief = teruglevering.
        Bij teruglevering wordt surplus gebruikt voor boiler-sturing bij volgende evaluatie.
        """
        surplus = max(0.0, -net_power_w)
        if surplus > 100:
            self._p1_surplus_w = surplus
            self._p1_last_ts   = time.time()
            _LOGGER.debug("P1 update: teruglevering %.0fW → boiler surplus bijgewerkt", surplus)

    # ── Setpoint bijwerken vanuit dashboard ──────────────────────────────────

    def update_setpoint(self, entity_id: str, setpoint_c: float) -> bool:
        """Pas setpoint_c aan voor de boiler met het opgegeven entity_id.
        Geeft True terug als de boiler gevonden en bijgewerkt is."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                old = b.setpoint_c
                b.setpoint_c        = float(setpoint_c)
                b.active_setpoint_c = float(setpoint_c)
                _LOGGER.info(
                    "BoilerController [%s]: setpoint bijgewerkt %.1f → %.1f°C (via dashboard)",
                    entity_id, old, setpoint_c,
                )
                return True
        _LOGGER.warning("BoilerController.update_setpoint: entity_id %s niet gevonden", entity_id)
        return False

    def set_manual_override(self, entity_id: str, setpoint_c: float, seconds: float) -> bool:
        """Zet handmatige override: setpoint vastzetten voor 'seconds' seconden.
        Coordinator slaat setpoint-berekening over zolang override actief is."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b.setpoint_c             = float(setpoint_c)
                b.active_setpoint_c      = float(setpoint_c)
                b._manual_override_until = time.time() + seconds
                _LOGGER.info(
                    "BoilerController [%s]: manual override %.1f°C voor %.0fs",
                    b.label, setpoint_c, seconds,
                )
                return True
        return False

    def clear_manual_override(self, entity_id: str) -> None:
        """Wis handmatige override zodat coordinator het setpoint weer beheert."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._manual_override_until = 0.0
                _LOGGER.info("BoilerController [%s]: manual override gewist", b.label)
                return

    async def send_now(self, entity_id: str, on: bool, setpoint_c: float | None = None) -> bool:
        """Stuur direct een commando naar de echte boiler-entity, zonder te wachten op de
        volgende evaluatiecyclus. Gebruikt door de virtual boiler bij handmatige bediening.

        v5.5.16 fix:
          - Zet manual_override_until zodat CloudEMS niet direct terugschrijft
          - Bij preset-boilers met setpoint > green_max → BOOST via iMemory-brug
          - Bij preset-boilers met setpoint <= green_max → GREEN
        """
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        boiler = next((b for b in all_b if b.entity_id == entity_id), None)
        if boiler is None:
            _LOGGER.warning("BoilerController.send_now: entity_id %s niet gevonden", entity_id)
            return False
        if setpoint_c is not None:
            boiler.setpoint_c        = float(setpoint_c)
            boiler.active_setpoint_c = min(float(setpoint_c), boiler.hw_ceiling)

        # Manual override 2 uur zodat CloudEMS niet direct terugschrijft
        # Gebruiker heeft bewust op BOOST geklikt — respecteer dat
        boiler._manual_override_until = time.time() + 7200.0
        self._cmd_queue.reset_debounce(entity_id)

        # Voor preset-boilers: kies GREEN of BOOST op basis van setpoint
        _prev_force_green = boiler.force_green
        if boiler.control_mode == "preset":
            green_max = boiler.max_setpoint_green_c if boiler.max_setpoint_green_c > 0 else 53.0
            target = boiler.active_setpoint_c or boiler.setpoint_c
            # Setpoint > green_max → BOOST nodig (iMemory-brug activeert automatisch in _switch)
            # Setpoint <= green_max → GREEN volstaat
            boiler.force_green = (target <= green_max)
            _LOGGER.info(
                "BoilerController [%s]: send_now on=%s setpoint=%.1f°C → %s "
                "(green_max=%.0f°C, manual override 2u)",
                boiler.label, on, target,
                "GREEN" if boiler.force_green else "BOOST via iMemory",
                green_max,
            )
        else:
            _LOGGER.info(
                "BoilerController [%s]: send_now on=%s setpoint=%.1f°C (handmatig, override 2u)",
                boiler.label, on, boiler.active_setpoint_c or boiler.setpoint_c,
            )
        await self._switch(entity_id, on, boiler)
        boiler.force_green = _prev_force_green
        return True

    def force_green_permanent(self, entity_id: str) -> bool:
        """Forceer GREEN mode permanent — CloudEMS stuurt nooit BOOST tenzij gebruiker reset.
        Verschil met pause_boost: geen tijdslimiet, boost_paused_until blijft 0.
        CloudEMS respecteert force_green=True totdat gebruiker resume_boost aanroept."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b.force_green          = True
                b._boost_paused_until  = 0.0   # geen tijdslimiet
                b._manual_override_until = 0.0
                # Reset debounce zodat de GREEN-opdracht onmiddellijk gestuurd wordt
                self._cmd_queue.reset_debounce(entity_id)
                _LOGGER.info("BoilerController [%s]: GREEN mode geforceerd (permanent tot reset)", b.label)
                return True
        return False

    def pause_boost(self, entity_id: str, seconds: float = 3600.0) -> bool:
        """Pauzeer BOOST voor de opgegeven boiler voor `seconds` seconden.
        De boiler schakelt direct naar preset_off (GREEN/ECO) en CloudEMS
        start geen nieuwe BOOST-cyclus tot de pauze verstreken is."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._boost_paused_until = time.time() + seconds
                b.force_green = True
                _LOGGER.info(
                    "BoilerController [%s]: BOOST gepauzeerd voor %.0f s",
                    b.label, seconds,
                )
                return True
        return False

    def resume_boost(self, entity_id: str) -> bool:
        """Hef BOOST-pauze op voor de opgegeven boiler.
        force_green wordt NIET gereset — de coordinator bepaalt zelf op basis van
        surplus/prijs of BOOST of GREEN passend is."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._boost_paused_until = 0.0
                _LOGGER.info("BoilerController [%s]: BOOST-pauze opgeheven", b.label)
                return True
        return False

    def force_boost_once(self, entity_id: str, seconds: float = 4 * 3600) -> bool:
        """Forceer BOOST voor `seconds` seconden, daarna terug naar normaal.
        Zet _boost_paused_until op 0 (geen pauze) en zet active_setpoint_c op hw_ceiling
        zodat de volgende evaluatiecyclus BOOST kiest."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._boost_paused_until = 0.0
                b.force_green = False
                b._manual_override_until = time.time() + seconds
                b.active_setpoint_c = min(b.max_setpoint_boost_c or b.hw_ceiling, b.hw_ceiling)
                b.setpoint_c = b.active_setpoint_c
                _LOGGER.info(
                    "BoilerController [%s]: BOOST geforceerd voor %.0fs (setpoint=%.1f°C)",
                    b.label, seconds, b.active_setpoint_c,
                )
                return True
        return False

    def force_legionella(self, entity_id: str) -> bool:
        """Forceer een legionella-cyclus: zet setpoint op LEGIONELLA_TEMP_C en
        zet een manual override van 2 uur zodat CloudEMS niet tussenkomt."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._boost_paused_until = 0.0
                b.force_green = False
                leg_sp = max(LEGIONELLA_TEMP_C, b.hw_ceiling * 0.85)
                leg_sp = min(leg_sp, b.hw_ceiling)
                b._manual_override_until = time.time() + 2 * 3600
                b.active_setpoint_c = leg_sp
                b.setpoint_c = leg_sp
                _LOGGER.info(
                    "BoilerController [%s]: legionella-cyclus geforceerd (setpoint=%.1f°C, 2u)",
                    b.label, leg_sp,
                )
                return True
        return False

    def force_stall_reset(self, entity_id: str) -> bool:
        """Reset stall-detectie en stuur boiler opnieuw aan."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        for b in all_b:
            if b.entity_id == entity_id:
                b._stall_active = False
                b._stall_start_ts = 0.0
                _LOGGER.info("BoilerController [%s]: stall gereset via virtual boiler", b.label)
                return True
        return False

    # ── Ariston cloud verify / retry ──────────────────────────────────────────────────────────

    def _set_pending(
        self,
        boiler: BoilerState,
        preset: str,
        setpoint_c: float,
        max_sp: float = 0.0,
    ) -> None:
        """Registreer een verzonden commando als 'pending verificatie'.
        Wordt aangeroepen direct na elke _switch() voor water_heater preset-boilers."""
        boiler._pending_preset   = preset
        boiler._pending_setpoint = setpoint_c
        boiler._pending_max_sp   = max_sp
        boiler._pending_since    = time.time()
        boiler._pending_retries  = 0
        boiler._next_verify_ts   = time.time() + ARISTON_VERIFY_DELAY_S
        _LOGGER.debug(
            "BoilerController [%s]: pending → preset=%s setpoint=%.1f°C (verify in %ds)",
            boiler.label, preset, setpoint_c, ARISTON_VERIFY_DELAY_S,
        )

    def _read_ariston_state(self, boiler: BoilerState) -> tuple[str, float, float]:
        """Lees de actuele state van de Ariston water_heater entity.
        Geeft (operation_mode, current_setpoint, current_max_sp) terug.
        Waarden zijn leeg/"0.0" als de entity niet beschikbaar is."""
        s = self._hass.states.get(boiler.entity_id)
        if s is None or s.state in ("unavailable", "unknown"):
            return ("", 0.0, 0.0)
        op = (
            s.attributes.get("operation_mode")
            or s.attributes.get("current_operation")
            or s.attributes.get("preset_mode")
            or s.state
            or ""
        )
        try:
            sp = float(s.attributes.get("temperature") or s.attributes.get("target_temp_high") or 0.0)
        except (ValueError, TypeError):
            sp = 0.0
        # max_setpoint uit de number-entity
        max_sp = 0.0
        max_ent = boiler.max_setpoint_entity or boiler._cached_max_setpoint_entity
        if max_ent:
            ms = self._hass.states.get(max_ent)
            if ms and ms.state not in ("unavailable", "unknown"):
                try:
                    max_sp = float(ms.state)
                except (ValueError, TypeError):
                    pass
        return (op, sp, max_sp)

    async def async_verify_pending(self) -> None:
        """Controleer voor alle preset-boilers of de pending state is aangekomen.
        Aangeroepen vanuit de coordinator-updatecyclus (elke 10s).
        Retriet automatisch met backoff als de state niet klopt.
        Respecteert 429-rate-limit window."""
        now = time.time()
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]

        for b in all_b:
            # Alleen preset water_heater boilers — die hebben Ariston cloud sync nodig
            if b.control_mode != "preset" or b.entity_id.split(".")[0] != "water_heater":
                continue

            # iMemory watchdog: als boiler in iMemory zit, stuur ALTIJD preset_off (GREEN)
            # iMemory is nooit de gewenste staat — ook niet als de boiler niet hoeft te verwarmen.
            # preset_off = GREEN = veilige standaard. preset_on = BOOST/GREEN verwarmen.
            _actual_now, _, _ = self._read_ariston_state(b)
            if _actual_now and _actual_now.lower() == "imemory":
                # iMemory watchdog: alleen ingrijpen als CloudEMS zelf NIET in iMemory-brug zit
                # (tijdens iMemory-brug is iMemory een bewuste tussenstap)
                _in_imemory_bridge = (
                    b._pending_preset
                    and b._pending_preset.lower() not in ("imemory",)
                    and b._pending_retries == 0
                    and now - b._pending_since < 30.0
                )
                if not _in_imemory_bridge:
                    _want = b.preset_off or b.preset_on or "GREEN"
                    if _want and _actual_now.lower() != _want.lower():
                        if b._imemory_since == 0.0:
                            b._imemory_since = now
                            _LOGGER.warning(
                                "BoilerController [%s]: iMemory gedetecteerd (niet via brug) — "
                                "bewaking gestart, gewenste preset=%s wordt over 30s opnieuw gestuurd",
                                b.label, _want,
                            )
                        elif now - b._imemory_since >= 30.0:
                            _LOGGER.warning(
                                "BoilerController [%s]: iMemory watchdog — %.0fs in iMemory, "
                                "stuur preset=%s opnieuw",
                                b.label, now - b._imemory_since, _want,
                            )
                            b._imemory_since = now
                            b._pending_preset   = _want
                            b._pending_retries  = 0
                            b._next_verify_ts   = now + 5.0
            else:
                b._imemory_since = 0.0  # niet in iMemory → reset teller

            # Geen pending commando
            if not b._pending_preset or b._next_verify_ts == 0.0:
                continue
            # Nog niet tijd voor verify
            if now < b._next_verify_ts:
                continue
            # Rate-limited — gebruik de queue's backoff ipv de verouderde _rate_limited_until
            _q_slot = self._cmd_queue.get_diagnostics().get("devices", {}).get(b.entity_id, {})
            _q_backoff = _q_slot.get("backoff_until", 0)
            if now < _q_backoff:
                _LOGGER.debug(
                    "BoilerController [%s]: rate-limited via queue, verify uitgesteld (nog %.0fs)",
                    b.label, _q_backoff - now,
                )
                b._next_verify_ts = _q_backoff + 5
                continue
            # Max retries ranget → opgeven
            if b._pending_retries >= ARISTON_MAX_RETRIES:
                _LOGGER.warning(
                    "BoilerController [%s]: verify mislukt na %d pogingen — "
                    "Ariston cloud heeft preset=%s setpoint=%.1f°C niet geaccepteerd. Opgegeven.",
                    b.label, ARISTON_MAX_RETRIES, b._pending_preset, b._pending_setpoint,
                )
                b._pending_preset  = ""
                b._next_verify_ts  = 0.0
                continue

            # Read actuele Ariston state
            actual_preset, actual_sp, actual_max_sp = self._read_ariston_state(b)
            if not actual_preset:
                # Entity unavailable — probeer later
                b._next_verify_ts = now + ARISTON_RETRY_BACKOFF[min(b._pending_retries, len(ARISTON_RETRY_BACKOFF)-1)]
                continue

            preset_ok  = actual_preset.lower() == b._pending_preset.lower()
            setpoint_ok = b._pending_setpoint <= 0.1 or abs(actual_sp - b._pending_setpoint) <= ARISTON_TEMP_TOLERANCE
            max_sp_ok  = b._pending_max_sp <= 0.1 or actual_max_sp <= 0.1 or abs(actual_max_sp - b._pending_max_sp) <= ARISTON_TEMP_TOLERANCE

            if preset_ok and setpoint_ok and max_sp_ok:
                _LOGGER.info(
                    "BoilerController [%s]: ✓ Ariston cloud verify OK — "
                    "preset=%s setpoint=%.1f°C (na %d retry(s))",
                    b.label, actual_preset, actual_sp, b._pending_retries,
                )
                b._pending_preset = ""
                b._next_verify_ts = 0.0
                continue

            # State klopt niet → retry
            b._pending_retries += 1
            delay = ARISTON_RETRY_BACKOFF[min(b._pending_retries - 1, len(ARISTON_RETRY_BACKOFF) - 1)]
            # v4.6.593: specifiek iMemory log
            if actual_preset.lower() == "imemory":
                _LOGGER.warning(
                    "BoilerController [%s]: Ariston in iMemory — gewenste preset=%s wordt opnieuw gestuurd "
                    "(poging %d/%d, over %ds)",
                    b.label, b._pending_preset, b._pending_retries, ARISTON_MAX_RETRIES, delay,
                )
            else:
                _LOGGER.warning(
                    "BoilerController [%s]: Ariston verify mismatch (poging %d/%d) — "
                    "preset: verwacht=%s actueel=%s | setpoint: verwacht=%.1f actueel=%.1f | "
                    "max_sp: verwacht=%.1f actueel=%.1f → retry over %ds",
                    b.label, b._pending_retries, ARISTON_MAX_RETRIES,
                    b._pending_preset, actual_preset,
                    b._pending_setpoint, actual_sp,
                    b._pending_max_sp, actual_max_sp,
                    delay,
                )
            b._next_verify_ts = now + delay

            # Send opnieuw via de CloudCommandQueue — rate-limiting + backoff
            try:
                async def _retry_executor(cmd: dict) -> None:
                    # Stap 1: operation mode
                    if self._hass.services.has_service("water_heater", "set_operation_mode"):
                        await self._hass.services.async_call(
                            "water_heater", "set_operation_mode",
                            {"entity_id": b.entity_id, "operation_mode": b._pending_preset},
                            blocking=True,
                        )
                    await asyncio.sleep(2)
                    # Stap 2 + 3: max_setpoint + setpoint
                    max_ent = b.max_setpoint_entity or b._cached_max_setpoint_entity
                    await self._send_setpoint_sequence(
                        b, b.entity_id, b._pending_preset,
                        b._pending_setpoint, max_ent or "",
                    )

                # reset_debounce: retry moet onmiddellijk sturen, niet wachten op debounce
                self._cmd_queue.reset_debounce(b.entity_id)
                _sent = await self._cmd_queue.request(
                    device_id = b.entity_id,
                    command   = {
                        "preset":   b._pending_preset,
                        "setpoint": b._pending_setpoint,
                        "entity":   b.entity_id,
                    },
                    executor  = _retry_executor,
                )
                if not _sent:
                    _LOGGER.debug(
                        "BoilerController [%s]: verify-retry geblokkeerd door queue (backoff/rate-limit)",
                        b.label,
                    )

            except Exception as _retry_err:
                err_str = str(_retry_err)
                self._cmd_queue.report_error(
                    b.entity_id,
                    status_code=429 if ("429" in err_str or "too many" in err_str.lower()) else 500,
                    message=err_str[:100],
                )
                if "429" in err_str or "Too Many" in err_str.lower() or "rate" in err_str.lower():
                    _LOGGER.warning(
                        "BoilerController [%s]: Ariston 429 rate-limit — queue neemt het over",
                        b.label,
                    )
                else:
                    _LOGGER.warning(
                        "BoilerController [%s]: Ariston retry fout: %s", b.label, _retry_err,
                    )



    def _get_actual_preset(self, b: BoilerState) -> str:
        """Geef de werkelijke operation mode terug van de boiler entity.

        Voor preset-mode boilers (water_heater): lees operation_mode direct uit HA state.
        Fallback naar CloudEMS desired state als de entity niet leesbaar is.
        Bijwerken van _actual_mode_since bij mode-wisseling.
        """
        if b.control_mode == "preset" or b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
            actual_preset, _, _ = self._read_ariston_state(b)
            if actual_preset:
                # Track wanneer de mode veranderde
                if actual_preset.lower() != b._actual_preset.lower():
                    b._actual_preset     = actual_preset
                    b._actual_mode_since = time.time()
                return actual_preset
            # Fallback: CloudEMS desired state
            desired = b.preset_off if b.force_green else b.preset_on
            if desired.lower() != b._actual_preset.lower():
                b._actual_preset     = desired
                b._actual_mode_since = time.time()
            return desired
        # Niet-preset boilers
        state = "on" if self._is_on(b.entity_id, b) else "off"
        if state != b._actual_preset:
            b._actual_preset     = state
            b._actual_mode_since = time.time()
        return state

    def get_status(self) -> list[dict]:
        # Inclusief groepsboilers — anders ziet de flow-kaart 0W bij cascade-configuraties
        all_boilers = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        return [
            {"entity_id": b.entity_id, "label": b.label,
             "is_on": self._is_on(b.entity_id, b),
             "temp_c": b.current_temp_c, "setpoint_c": b.active_setpoint_c or b.setpoint_c,
             "active_setpoint_c": b.active_setpoint_c,  # gecapped op hw-max; None vóór eerste cycle
             # v4.6.575: power_w = 0 als boiler niet aan staat (is_on=False).
             # Een niet-geïnstalleerde of offline boiler kan via cloud-sensor toch
             # een value rapporteren — die negeren we als de boiler niet active is.
             # v4.6.595: als current_power_w nog None is (eerste seconden na restart),
             # gebruik het learnede nominale power als schatting zodat de energy flow
             # direct een value toont ipv 0W te wachten op de eerste meting.
             "power_w": (b.current_power_w if b.current_power_w is not None else b.power_w)
                        if self._is_on(b.entity_id, b) else 0.0,
             "current_power_w": b.current_power_w,
             "cycle_kwh": round(b.cycle_kwh, 3),
             "thermal_loss_c_h": b.thermal_loss_c_h, "control_mode": b.control_mode,
             "boiler_type": b.boiler_type, "has_gas_heating": b.has_gas_heating,
             "post_saldering_mode": b.post_saldering_mode, "delta_t_optimize": b.delta_t_optimize,
             # v4.6.555: actieve mode — read de werkelijke mode van de water_heater entity
             # zodat de badge de Ariston-staat toont, niet de CloudEMS-gewenste staat.
             # Fallback naar CloudEMS desired state als de entity niet leesbaar is.
             "actual_mode": self._get_actual_preset(b),
             "actual_mode_since_s": round(time.time() - b._actual_mode_since, 0) if b._actual_mode_since > 0 else None,
             "pending_preset": b._pending_preset or "",
             "preset_on":      b.preset_on or "BOOST",
             "preset_off":     b.preset_off or "GREEN",
             "is_heating": (b.current_power_w or 0.0) > 5.0,
             "stall_active": b._stall_active,
             "boost_paused_until": b._boost_paused_until if b._boost_paused_until > time.time() else 0.0,
             "boost_paused_remaining_s": max(0.0, round(b._boost_paused_until - time.time(), 0)) if b._boost_paused_until > time.time() else 0.0,
             "brand": b.brand,
             "brand_label": _BRAND_LABELS.get(b.brand, b.brand) if b.brand else "",
             # v4.5.92: gezondheid & veiligheid
             "cop_at_current_temp": _cop_from_temp(b.outside_temp_c, b.cop_curve_override)
                                    if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) else None,
             "water_hardness_dh": b.water_hardness_dh,
             "legionella_days": getattr(b, "_leg_last_done", 0) and
                                round((time.time() - b._leg_last_done) / 86400, 1) if getattr(b, "_leg_last_done", 0) > 0 else None,
             # FIX 4: learned tankvolume en ramp-setpoint zichtbaar in sensor
             "tank_liters_config":  b.tank_liters if b.tank_liters > 0 else None,
             "tank_liters_learned": round(b._learned_tank_l, 0) if b._learned_tank_l > 1.0 else None,
             "tank_liters_active":  round(b._effective_tank_liters, 0),
             "ramp_setpoint_c":     round(b._cheap_ramp_setpoint_c, 1) if b.boiler_type == BOILER_TYPE_HYBRID and b._cheap_ramp_setpoint_c > 0 else None,
             "ramp_max_c":          b.cheap_ramp_max_c if b.boiler_type == BOILER_TYPE_HYBRID else None,
             # Geschiedenis voor grafieken in boiler card
             "temp_history":  [
                 {"t": round(ts), "v": round(v, 1)}
                 for ts, v in (b._temp_history or [])[-48:]
             ],
             "power_history": [
                 {"t": round(ts), "v": round(v, 0)}
                 for ts, v in (b._power_history or [])[-48:]
             ],
             }
            for b in all_boilers
        ]

    def get_groups_status(self) -> list[dict]:
        hour_now = datetime.now().hour
        return [
            {"id": g.id, "name": g.name, "mode": g.mode,
             "avg_temp_c": g.avg_temp_c, "total_power_w": g.total_power_w,
             "boiler_count": len(g.boilers),
             "active_count": sum(1 for b in g.boilers if self._is_on(b.entity_id, b)),
             "delivery_entity":  (g.learner.get_delivery_entity(g.boilers) if g.learner else None),
             "delivery_learned": bool(g.learner and g.learner.get_delivery_entity(g.boilers)),
             "season":           (g.learner.get_season() if g.learner else "unknown"),
             "learn_status":     (g.learner.get_learn_status(g.boilers) if g.learner else {}),
             "boilers": [
                 {"label": b.label, "entity_id": b.entity_id,
                  "is_on": self._is_on(b.entity_id, b),
                  "temp_c": b.current_temp_c, "setpoint_c": b.active_setpoint_c or b.setpoint_c,
                  "is_delivery": b.is_delivery, "priority": b.priority,
                  "active_setpoint_c": b.active_setpoint_c,
                  "control_mode": b.control_mode, "power_w": b.current_power_w,
                  "cycle_kwh": round(b.cycle_kwh, 3),
                  "thermal_loss_c_h": b.thermal_loss_c_h,
                  "brand": b.brand,
                  "brand_label": _BRAND_LABELS.get(b.brand, b.brand) if b.brand else "",
                  "minutes_to_cold": g.learner.time_until_cold(b) if g.learner else None,
                  "post_saldering_mode": b.post_saldering_mode,
                  "delta_t_optimize": b.delta_t_optimize,
                  "optimal_start_min": (
                      g.learner.optimal_start_before_minutes(hour_now, b.minutes_to_setpoint or 0)
                      if g.learner and b.minutes_to_setpoint else None),
                  "minutes_to_setpoint": b.minutes_to_setpoint,
                  # v4.5.92: gezondheid & veiligheid
                  "heat_rate_c_h":  g.learner.get_heat_rate(b) if g.learner else None,
                  "reheat_eta_min": g.learner.reheat_eta_min(b) if g.learner else None,
                  "minutes_to_heat": g.learner.minutes_to_heat(b) if g.learner else None,
                  "scale_score_pct": g.learner.get_scale_score(b) if g.learner else None,
                  "anode_wear_pct": g.learner.get_anode_wear_pct(b) if g.learner else None,
                  "anode_kwh": g.learner.get_anode_kwh(b) if g.learner else None,
                  "water_hardness_dh": b.water_hardness_dh,
                  "legionella": g.learner.get_legionella_status(b.entity_id) if g.learner else None,
                  "cop_at_current_temp": _cop_from_temp(b.outside_temp_c, b.cop_curve_override)
                                         if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) else None,
                  # FIX 4: learnede tankvolume + ramp
                  "tank_liters_config":  b.tank_liters if b.tank_liters > 0 else None,
                  "tank_liters_learned": round(b._learned_tank_l, 0) if b._learned_tank_l > 1.0 else None,
                  "tank_liters_active":  round(b._effective_tank_liters, 0),
                  "ramp_setpoint_c":     round(b._cheap_ramp_setpoint_c, 1) if b.boiler_type == BOILER_TYPE_HYBRID and b._cheap_ramp_setpoint_c > 0 else None,
                  # FIX 2: demand boost statistieken
                  "demand_boost_stats":  g.learner.get_demand_boost_stats() if g.learner else None,
                  # Douche-teller
                  "shower_minutes":      b.shower_minutes_available,
                  "shower_temp_c":       38.0,
                  "cold_water_temp_c":   10.0,
                  }
                 for b in g.boilers
             ]}
            for g in self._groups
        ]

    def get_full_status(self) -> dict:
        """Gecombineerde status inclusief weekly budget en P1-direct state."""
        return {
            "boilers":        self.get_status(),
            "groups":         self.get_groups_status(),
            "weekly_budget":  self.get_weekly_budget(),
            "p1_surplus_w":   round(self._p1_surplus_w, 1),
            "p1_active":      (time.time() - self._p1_last_ts) < 90 and self._p1_surplus_w > 0,
        }

    def reset_delivery_learning(self, group_id: Optional[str] = None) -> None:
        for g in self._groups:
            if g.learner and (group_id is None or g.id == group_id):
                g.learner.reset()
        _LOGGER.info("BoilerLearner: leerdata gewist voor %s", group_id or "alle groepen")
