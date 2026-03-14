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

_LOGGER = logging.getLogger(__name__)

# ─── Sturingmodi ─────────────────────────────────────────────────────────────
MODE_CHEAP_HOURS    = "cheap_hours"
MODE_NEGATIVE_PRICE = "negative_price"
MODE_PV_SURPLUS     = "pv_surplus"
MODE_EXPORT_REDUCE  = "export_reduce"

# ─── ACRouter (RobotDyn DimmerLink hardware) ──────────────────────────────────
# REST API modus-codes voor ACRouter firmware v1.2.0+
# POST /api/mode  {"mode": N}
ACROUTER_MODE_OFF     = 0   # Uit
ACROUTER_MODE_AUTO    = 1   # Autonoom grid-balancering (niet gebruikt door CloudEMS)
ACROUTER_MODE_ECO     = 2   # Voorkomt export, laat import toe
ACROUTER_MODE_OFFGRID = 3   # Alleen zonne-overschot (niet gebruikt)
ACROUTER_MODE_MANUAL  = 4   # Handmatig dimmer-niveau (CloudEMS stuurt dit)
ACROUTER_MODE_BOOST   = 5   # 100% vermogen (goedkope uren)
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
#              Lange opwarmtijd (8-12u) — proactief starten via heat_up_hours.
#
#  HYBRID    — Warmtepomp + weerstandselement (bijv. Ariston Lydos Hybrid).
#              green-preset = WP-element: ALTIJD aan bij temperatuurtekort.
#              boost-preset = weerstandselement: alleen goedkoopste uren/surplus.
#              control_mode="preset", preset_off="green", preset_on="boost".
#
#  VARIABLE  — Variabele boiler 0-100% (bijv. SolarEdge MyHeat, ESPHome dimmer).
#              Proportioneel op PV-surplus. Bij geen surplus: minimumvermogen in
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

# ─── Gas-vs-stroom vergelijking ───────────────────────────────────────────────
# Gebruikt bij resistive/variable boilers als has_gas_heating=True:
# gas_eur_kwh_th  = gas_prijs_m3 / (9.769 kWh/m³ × 0.90 rendement CV)
# elec_eur_kwh_th = stroom_prijs_kwh / 1.0   (weerstandselement COP=1)
# → boiler alleen aan als elec_eur_kwh_th < gas_eur_kwh_th
GAS_KWH_PER_M3_BOILER = 9.769   # calorische waarde aardgas (kWh/m³)
GAS_BOILER_EFF_BOILER  = 0.90   # rendement CV-ketel (typisch 90%)
GAS_VS_ELEC_MARGIN     = 0.01   # €/kWh drempel: stroom mag max 1ct/kWh duurder
                                  # dan gas thermisch voor kleine onzekerheidsband

# ─── Legionella preventie ─────────────────────────────────────────────────────
LEGIONELLA_TEMP_C         = 65.0   # minimale temperatuur voor legionella-doding
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
ARISTON_MAX_RETRIES       = 4      # maximaal 4 pogingen na de initiële send
ARISTON_RATE_LIMIT_S      = 180    # bij 429: 3 minuten wachten voor nieuwe pogingen
ARISTON_PRESET_TOLERANCE  = 0      # preset moet exact kloppen (string compare)
ARISTON_TEMP_TOLERANCE    = 1.0    # setpoint mag ±1°C afwijken (float compare)

# ─── Thermisch model: geleerde opwarmsnelheid ────────────────────────────────
HEAT_RATE_ALPHA           = 0.10   # EMA-factor voor g_heat_rate bijwerking
HEAT_RATE_MIN_C_H         = 0.5    # minimum plausibele opwarmsnelheid (°C/h)
HEAT_RATE_MAX_C_H         = 30.0   # maximum plausibele opwarmsnelheid (°C/h)
HEAT_RATE_INIT_C_H        = 5.0    # startseed (≈ 2kW op 80L)
HEAT_RATE_MIN_DELTA_C     = 1.0    # minimale temperatuurstijging voor leermoment
HEAT_RATE_MIN_ON_S        = 300    # minimaal 5 min aan voor betrouwbaar leermoment

# ─── Temperatuurafhankelijke COP (HEAT_PUMP / HYBRID) ─────────────────────────
# cop = a×T² + b×T + c    (T = buitentemperatuur °C, standaard Daikin/Vaillant curve)
COP_A                     =  0.0008  # kwadratisch
COP_B                     =  0.08    # lineair
COP_C                     =  3.0     # constante (COP @ 0°C ≈ 3.0)
COP_DHW_FACTOR            =  0.70    # DHW heeft lagere COP dan ruimteverwarming
COP_MIN                   =  1.2     # minimale COP (ijzig weer)
COP_MAX                   =  6.0     # maximale COP (warm weer)

# ─── Kalkdetectie (limescale) ─────────────────────────────────────────────────
SCALE_WARN_PCT            = 60.0   # waarschuwing bij ≥60% kalkindex
SCALE_SCORE_FACTOR        = 200.0  # drop_frac → score: 50% daling = 100% score

# ─── Anode-slijtage ───────────────────────────────────────────────────────────
ANODE_DEFAULT_KWH         = 5000.0  # typische anode-levensduur (kWh doorvoer)
ANODE_WARN_PCT            = 80.0    # waarschuwing bij ≥80% van drempelwaarde
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
    surplus_setpoint_c:  float = 75.0    # setpoint bij PV-surplus (setpoint_boost modus)
    # v4.6.13: hardware_max_c — absolute bovengrens voor alle setpoints die naar de
    # hardware gestuurd worden. Voorkomt dat CloudEMS bijv. 78°C stuurt terwijl de boiler
    # maar 60°C aankan. 0.0 = niet ingesteld (systeem gebruikt SAFETY_MAX_C - 2.0 = 78°C).
    # Voor resistive boilers met een lager maximum: stel in op bijv. 60.0 of 65.0.
    # Voor heat_pump/hybrid: max_setpoint_boost_c heeft dezelfde rol en heeft prioriteit.
    hardware_max_c:      float = 0.0
    preset_on:           str   = "boost"
    preset_off:          str   = "green"
    # v4.6.5: Ariston Lydos e.d. begrenzen setpoint per modus via een apart number-entity
    # (bijv. number.ariston_max_setpoint_temperature). In GREEN-modus is dit bijv. 53°C.
    # CloudEMS zet dit entity op 75°C bij BOOST zodat het gewenste setpoint ook echt
    # bereikt kan worden. Bij terugschakelen naar GREEN wordt het teruggezet op preset_off_max_c.
    max_setpoint_entity: str   = ""    # bijv. "number.ariston_max_setpoint_temperature"
    max_setpoint_boost_c: float = 75.0  # waarde die gezet wordt bij BOOST
    max_setpoint_green_c: float = 53.0  # waarde die teruggezet wordt bij GREEN
    dimmer_on_pct:       float = 100.0
    dimmer_off_pct:      float = 0.0
    dimmer_proportional: bool  = False
    post_saldering_mode: bool  = False
    delta_t_optimize:    bool  = False
    # v4.5.86: boilertype + WP-boiler instellingen
    boiler_type:         str   = BOILER_TYPE_RESISTIVE  # resistive | heat_pump | hybrid | variable
    heat_up_hours:       float = 0.0    # verwachte opwarmtijd (u). 0=auto schatten.
                                         # heat_pump/hybrid: typisch 8-12u
                                         # resistive: typisch 1-3u, variable: n.v.t.
    boost_only_cheapest: int   = 2      # boost/100% alleen in de N goedkoopste uren
                                         # (0 = altijd boost toegestaan als want_on)
    has_gas_heating:     str   = ""    # CV-ketel aanwezig voor warm water?
                                         # ""    = niet geconfigureerd (hint mogelijk)
                                         # "yes" = ja → gas-vs-stroom vergelijking actief
                                         # "no"  = nee → hint nooit meer tonen
    # v4.5.90: tijdelijk per evaluatieronde — True = gebruik preset_off (green/WP-element)
    #          False = gebruik preset_on (boost/weerstandselement)
    force_green:         bool  = False
    # Deprecated veld — gebruik boiler_type="heat_pump" of "hybrid"
    heat_pump_boiler:    bool  = False

    # ── v4.5.92: Gezondheids- en veiligheidsintelligentie ─────────────────────
    # Legionella
    water_hardness_dh:   float = 14.0   # waterhardheid in °dH (voor anode-slijtage)
    anode_threshold_kwh: float = ANODE_DEFAULT_KWH  # configureerbaar per boiler
    # Kalkdetectie: configureerbaar aan/uit
    limescale_detect:    bool  = True
    # COP-curve overschrijving (None = gebruik standaard parabool)
    cop_curve_override:  Optional[dict] = None  # {temp_c: cop, ...} interpolatietabel

    _temp_history:       list  = field(default_factory=list, repr=False)
    _energy_kwh_last:    Optional[float] = field(default=None, repr=False)
    _energy_ts_last:     Optional[float] = field(default=None, repr=False)
    _dimmer_last_pct:    float = field(default=0.0, repr=False)
    _dimmer_last_ts:     float = field(default=0.0, repr=False)

    # ── v4.6.12: Hardware deadband compensatie + stall detectie ──────────────
    # Ariston WP-boilers starten pas als de watertemperatuur ver genoeg onder het
    # ingestelde setpoint zakt (interne hardware deadband van de boiler zelf).
    # hardware_deadband_c wordt bij het verzonden setpoint opgeteld zodat de
    # hardware-trigger eerder afgaat. Waarde 0.0 = automatisch:
    #   heat_pump / hybrid → 2.0°C   resistive / variable → 0.0°C
    hardware_deadband_c: float = 0.0
    # Stall-detectie: als de boiler stall_timeout_s lang 0W trekt terwijl hij
    # aan hoort te staan, wordt het setpoint tijdelijk met stall_boost_c verhoogd
    # om de interne hardware-deadband te doorbreken.
    stall_boost_c:       float = 5.0    # tijdelijke setpoint-boost bij stall (°C)
    stall_timeout_s:     float = 300.0  # seconden 0W + want_on voor stall-detectie

    _stall_start_ts:     float = field(default=0.0,   repr=False)
    _stall_active:       bool  = field(default=False,  repr=False)
    # v4.6.26: gebruiker kan BOOST pauzeren via virtual_boiler UI ("auto" kiezen)
    _boost_paused_until: float = field(default=0.0,   repr=False)
    # v4.6.42: handmatige override — coordinator slaat setpoint-berekening over
    _manual_override_until: float = field(default=0.0, repr=False)
    # v4.6.52: gecachede max_setpoint_entity (voorkomt entity-registry scan elke 10s)
    _cached_max_setpoint_entity: str = field(default="", repr=False)

    # v4.6.60: Cloud verify/retry — Ariston cloud is onbetrouwbaar, settings komen
    # niet altijd aan. Na elke send slaan we het gewenste doel op en controleren
    # periodiek of de echte state overeen komt. Zo niet → retry (max 4x, backoff).
    _pending_preset:    str   = field(default="",  repr=False)  # gewenste operation_mode
    _pending_setpoint:  float = field(default=0.0, repr=False)  # gewenste temperature
    _pending_max_sp:    float = field(default=0.0, repr=False)  # gewenste max_setpoint
    _pending_since:     float = field(default=0.0, repr=False)  # timestamp van laatste send
    _pending_retries:   int   = field(default=0,   repr=False)  # aantal retries gedaan
    _next_verify_ts:    float = field(default=0.0, repr=False)  # wanneer volgende verify
    _rate_limited_until:float = field(default=0.0, repr=False)  # 429-block tot ts

    # ── v4.5.125: ACRouter (RobotDyn DimmerLink) hardware-integratie ──────────
    # Configuratie: stel control_mode="acrouter" + acrouter_host="192.168.x.x" in.
    # power_w blijft het nominale vermogen van het weerstandselement (bijv. 2000).
    acrouter_host:       str   = ""     # IP-adres van het ACRouter device
    # v4.6.18: merk-identificatie (opgeslagen vanuit config_flow wizard)
    brand:               str   = ""     # bijv. "ariston_lydos_hybrid", "midea_e2", "unknown"
    # Interne state (niet in config):
    _acrouter_last_mode: int   = field(default=-1,  repr=False)  # -1 = onbekend
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
        # v4.6.16: max_setpoint_boost_c altijd als ceiling gebruiken als het geconfigureerd is,
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
    def minutes_to_setpoint(self) -> Optional[float]:
        if self.current_temp_c is None or self.temp_deficit_c <= 0:
            return 0.0
        if self.power_w <= 0:
            return None
        kwh_needed = self.temp_deficit_c * 50 * 4.18 / 3600
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

        # Dag-van-de-week patroon heeft prioriteit als er voldoende data is
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
        # Bereken gemiddeld dagelijks verbruik uit historische data
        dow      = self.get_usage_pattern_dow()
        weekday  = datetime.now().weekday()
        day_sum  = sum(dow[weekday])
        # Schat normaal aantal cycli: als day_sum > 0.5 dan hebben we data
        # Elke 0.1 eenheid ≈ 1 cyclus; threshold bij 2.5× normaal
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

    # ── 5. Geleerde opwarmsnelheid (heat_rate) ────────────────────────────────

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

    # ── 6. Legionella cyclus ──────────────────────────────────────────────────

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

    def legionella_deadline(self, entity_id: str) -> bool:
        """True als de cyclus forceer-nodig is (LEGIONELLA_DEADLINE_DAYS overschreden)."""
        days = self.legionella_days_since(entity_id)
        return days is None or days >= LEGIONELLA_DEADLINE_DAYS

    def legionella_planned_hour(self, entity_id: str, hourly_prices: list) -> int:
        """
        Kies het goedkoopste uur van vandaag voor de legionella-cyclus.
        Herplan elke dag opnieuw. Geeft het geplande uur terug (0-23).
        """
        leg  = self._leg_g(entity_id)
        today = datetime.now().strftime("%Y-%m-%d")
        if leg.get("plan_day") == today and leg.get("planned_hour", -1) >= 0:
            return int(leg["planned_hour"])

        # Kies één van de goedkoopste N uren, bij voorkeur 's nachts (0-6)
        if not hourly_prices:
            planned = 2  # fallback: 02:00
        else:
            ranked  = sorted(range(len(hourly_prices)), key=lambda i: hourly_prices[i])
            cheapest_n = ranked[:LEGIONELLA_PRICE_RANK]
            # Voorkeur: nachtelijk uur (0-6), anders gewoon goedkoopst
            night = [h for h in cheapest_n if 0 <= h <= 6]
            planned = night[0] if night else cheapest_n[0]

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
        return {
            "days_since":    days,
            "needed":        self.legionella_needed(entity_id),
            "deadline":      self.legionella_deadline(entity_id),
            "planned_hour":  leg.get("planned_hour", -1),
            "confirm_ticks": leg.get("confirm_ticks", 0),
            "confirm_pct":   round(leg.get("confirm_ticks", 0) / LEGIONELLA_CONFIRM_S * 100, 1),
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
            # Groep-dict heeft "units" (lijst van boilers) en optioneel "id"/"name"
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

    def _build_boiler(self, cfg: dict) -> BoilerState:
        # v4.6.16: brand-veld → auto-defaults voor bekende merken.
        # Waarden uit cfg hebben altijd prioriteit; brand vult alleen gaps.
        _brand_defaults: dict = {}
        _brand = cfg.get("brand", "")
        if _brand:
            # Importeer de preset-tabel uit config_flow indien beschikbaar,
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

        # v4.6.22: voor bekende merken zijn sturingsvelden vergrendeld op het preset-waarde.
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
        self._power_dirty     = False
        self._power_last_save = _time.time()

    # ── Hoofdevaluatie ────────────────────────────────────────────────────────

    async def async_evaluate(
        self,
        price_info:          dict,
        solar_surplus_w:     float = 0.0,
        phase_currents:      Optional[dict] = None,
        phase_max_currents:  Optional[dict] = None,
        surplus_threshold_w: float = DEFAULT_SURPLUS_THRESHOLD_W,
        export_threshold_a:  float = DEFAULT_EXPORT_THRESHOLD_A,
    ) -> list[BoilerDecision]:
        phase_currents = phase_currents or {}
        decisions: list[BoilerDecision] = []

        # P1 directe respons: gebruik de meest recente P1-waarde als die recent is (< 90s)
        now = time.time()
        effective_surplus = solar_surplus_w
        if self._p1_surplus_w > 0 and (now - self._p1_last_ts) < 90:
            effective_surplus = max(solar_surplus_w, self._p1_surplus_w)

        await self._read_sensors()

        # Tijdens PV-surplus: gebruik maximaal setpoint om zoveel mogelijk zonne-energie op te slaan
        surplus_active = effective_surplus >= surplus_threshold_w
        _is_neg      = bool(price_info.get("is_negative", False))
        # v4.6.6: bij negatieve prijs OF groot surplus (≥2× drempel) → hardware-max setpoint (bijv. 75°C)
        _big_surplus = effective_surplus >= surplus_threshold_w * 2.0
        _max_charge  = _is_neg or _big_surplus

        for b in self._boilers:
            # v4.6.42: handmatige override actief → setpoint niet overschrijven
            if b._manual_override_until > time.time():
                pass
            elif b.boiler_type == BOILER_TYPE_VARIABLE:
                # Variable boilers hebben intern vast setpoint — niet aanraken
                b.active_setpoint_c = b.setpoint_c
            elif surplus_active and MODE_PV_SURPLUS in b.modes:
                if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                    _hw_max = b.hw_ceiling
                    # Negatief of groot surplus → hardware-max (75°C); normaal surplus → surplus_setpoint_c
                    _target = _hw_max if _max_charge else min(b.surplus_setpoint_c, _hw_max)
                    b.active_setpoint_c = min(_target, b.hw_ceiling)
                else:
                    # Resistive/variable: begrensd door hardware_max_c als ingesteld, anders 78°C
                    _target = b.surplus_setpoint_c if not _max_charge else b.hw_ceiling
                    b.active_setpoint_c = min(_target, b.hw_ceiling)
            elif _is_neg and b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                # Negatieve prijs zonder (groot) PV-surplus: ook naar hardware-max
                b.active_setpoint_c = b.hw_ceiling
            elif _is_neg:
                # Resistive bij negatieve prijs: naar hardware-max
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
                        pass  # manual override actief → setpoint niet overschrijven
                    elif b.boiler_type == BOILER_TYPE_VARIABLE:
                        b.active_setpoint_c = b.setpoint_c  # variable: intern vast
                    elif surplus_active and MODE_PV_SURPLUS in b.modes:
                        if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
                            _hw_max = b.hw_ceiling
                            _target = _hw_max if _max_charge else min(b.surplus_setpoint_c, _hw_max)
                            b.active_setpoint_c = min(_target, b.hw_ceiling)
                        else:
                            _target = b.surplus_setpoint_c if not _max_charge else b.hw_ceiling
                            b.active_setpoint_c = min(_target, b.hw_ceiling)
                    elif _is_neg and b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
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
        # Verlaag setpoint proportioneel: max 8°C lager bij grote marge
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

        # v4.5.12: controleer of entiteit beschikbaar is — unavailable = geen sturing, wel loggen.
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

        # v4.6.45: manual override actief → CloudEMS blijft af, virtual boiler stuurt zelf
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
        # v4.6.26: als gebruiker BOOST pauzeerde → force_green herstellen tot pauze voorbij
        if b._boost_paused_until > 0:
            if time.time() < b._boost_paused_until:
                b.force_green = True   # blijf in GREEN/ECO zolang pauze actief
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

        # v4.6.5: heat_pump/hybrid met GREEN-mode temperatuurcap (bijv. Ariston GREEN = max 53°C).
        # Pas active_setpoint_c aan naar de modus-specifieke grens zodat needs_heat en
        # temp_deficit_c de werkelijk haalbare temperatuur weerspiegelen:
        #   • Geen boost beschikbaar → gaan GREEN gebruiken → cap op max_setpoint_green_c
        #   • Boost beschikbaar (surplus / goedkoop uur) → gaan BOOST gebruiken → cap op max_setpoint_boost_c
        # Dit voorkomt dat CloudEMS denkt dat de boiler 26°C tekort heeft terwijl de boiler
        # gewoon op zijn GREEN-maximum (53°C) staat.
        if btype in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) and b.max_setpoint_green_c > 0:
            _mode_cap = b.max_setpoint_boost_c if _boost_allowed else b.max_setpoint_green_c
            if b.active_setpoint_c > _mode_cap + 0.5:
                b.active_setpoint_c = _mode_cap
            # Herbereken deficit met de gecorrigeerde setpoint
            _deficit = b.temp_deficit_c

        # ── TYPE 1: RESISTIVE — prijs en surplus domineren ───────────────────────────────
        if btype == BOILER_TYPE_RESISTIVE:
            if MODE_NEGATIVE_PRICE in b.modes and _is_negative:
                want_on = True; reason = f"Negatieve prijs: {_current_price:.4f} €/kWh"

            # Gas-vs-stroom: als CV aanwezig, check of stroom goedkoper is dan gas thermisch.
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
        # green ALTIJD aan bij temperatuurtekort, ongeacht stroomprijs.
        # boost (weerstandselement) alleen bij goedkoopste N uren of surplus.
        #
        # v4.6.5: Ariston e.a. WP-boilers met GREEN/BOOST-modi:
        #   • Onder green_mode_max_c (bijv. 53°C): GREEN verwarmt via WP (force_green=True)
        #   • Bij surplus of goedkoop uur: ga naar BOOST (ook als temp < green_mode_max_c),
        #     zodat de boiler al in de juiste modus staat vóór het setpoint bereikt is.
        #   • Boven green_mode_max_c: ALTIJD BOOST (GREEN kan dit niet bereiken).
        elif btype == BOILER_TYPE_HEAT_PUMP:
            # COP-bewuste gas-vs-WP vergelijking: WP bijna altijd goedkoper dan gas
            _cop_wp  = _cop_from_temp(_outside, b.cop_curve_override) * COP_DHW_FACTOR
            _gas_p_m3 = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th_wp = _gas_p_m3 / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _wp_th     = _current_price / max(_cop_wp, 0.1)
            _wp_cheaper_than_gas = (b.has_gas_heating != "yes") or (_wp_th <= _gas_th_wp + GAS_VS_ELEC_MARGIN)

            # Boven green_mode_max_c: GREEN-modus kan dit niet bereiken → BOOST verplicht
            _above_green_max = (
                b.max_setpoint_green_c > 0
                and _has_temp
                and b.current_temp_c >= b.max_setpoint_green_c - 1.0
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
                if _boost_allowed or _above_green_max:
                    b.force_green = False  # boost: weerstandselement
                    if _above_green_max and not _boost_allowed:
                        # Temp al boven GREEN-cap: BOOST nodig om setpoint te halen
                        cop_str = f" COP≈{_cop_wp:.1f}" if _outside is not None else ""
                        reason = f"WP boost{cop_str}: {b.current_temp_c:.1f}°C > GREEN-max ({b.max_setpoint_green_c:.0f}°C)"
                    else:
                        reason = f"WP boost+green: {_deficit:.1f}°C tekort"
                        reason += f" (goedkoopste {boost_n}u)" if boost_n > 0 else ""
                else:
                    b.force_green = True   # alleen WP-element (green)
                    cop_str = f" COP≈{_cop_wp:.1f}" if _outside is not None else ""
                    if _mts > 0:
                        reason = f"WP green{cop_str}: {_deficit:.1f}°C tekort (~{_mts:.0f} min tot setpoint)"
                    else:
                        reason = f"WP green{cop_str}: {_deficit:.1f}°C tekort"
                if b.has_gas_heating == "yes" and not _wp_cheaper_than_gas and not _is_negative:
                    reason += f" [WP €{_wp_th*100:.1f}ct vs gas €{_gas_th_wp*100:.1f}ct/kWh_th]"
            elif not _has_temp and price_info.get(f"in_cheapest_{effective_rank}h"):
                want_on = True; reason = f"WP green: goedkoopste {effective_rank}u (geen temp sensor)"
            if not want_on and _boost_allowed and solar_surplus_w > surplus_threshold_w:
                want_on = True; b.force_green = False
                reason = f"WP boost: PV surplus {solar_surplus_w:.0f}W"

        # ── TYPE 3: HYBRID — green (WP) altijd bij tekort, boost selectief ────────────
        # Bijv. Ariston Lydos Hybrid. green = WP-element, boost = weerstandselement.
        # v4.6.5: boven green_mode_max_c ALTIJD BOOST (GREEN kan dit niet bereiken).
        elif btype == BOILER_TYPE_HYBRID:
            _cop_hyb   = _cop_from_temp(_outside, b.cop_curve_override) * COP_DHW_FACTOR
            _gas_p_m3h = price_info.get("gas_price_eur_m3", 1.25)
            _gas_th_h  = _gas_p_m3h / (GAS_KWH_PER_M3_BOILER * GAS_BOILER_EFF_BOILER)
            _hyb_th    = _current_price / max(_cop_hyb, 0.1)
            cop_str_h  = f" COP≈{_cop_hyb:.1f}" if _outside is not None else ""

            _above_green_max_h = (
                b.max_setpoint_green_c > 0
                and _has_temp
                and b.current_temp_c >= b.max_setpoint_green_c - 1.0
            )

            if not b.needs_heat:
                want_on = False
                reason  = f"Hybrid op setpoint ({b.current_temp_c:.1f}°C)" if _has_temp else "Hybrid op setpoint"
            elif _is_negative:
                want_on = True; reason = f"Hybrid boost: negatieve prijs {_current_price:.4f} €/kWh"
            else:
                want_on = True
                if _boost_allowed or _above_green_max_h:
                    b.force_green = False  # boost actief
                    if _above_green_max_h and not _boost_allowed:
                        reason = f"Hybrid boost verplicht: {b.current_temp_c:.1f}°C > GREEN-max ({b.max_setpoint_green_c:.0f}°C)"
                    else:
                        base = f"Hybrid green+boost{cop_str_h}: {_deficit:.1f}°C tekort" if _has_temp else f"Hybrid green+boost{cop_str_h}: geen temp sensor"
                        if solar_surplus_w > surplus_threshold_w:
                            reason = base + f" (surplus {solar_surplus_w:.0f}W)"
                        else:
                            reason = base + (f" (goedkoopste {boost_n}u)" if boost_n > 0 else "")
                else:
                    b.force_green = True   # alleen WP-element
                    reason = f"Hybrid green (WP{cop_str_h}): {_deficit:.1f}°C tekort" if _has_temp else f"Hybrid green (WP{cop_str_h}): geen temp sensor"
            if not want_on and _boost_allowed and solar_surplus_w > surplus_threshold_w:
                want_on = True; reason = f"Hybrid boost: PV surplus {solar_surplus_w:.0f}W"

        # ── TYPE 4: VARIABLE — proportioneel 0-100% op surplus/prijs ────────────────
        # Dimmerlink boiler: intern vast setpoint, CloudEMS regelt alleen vermogen%.
        elif btype == BOILER_TYPE_VARIABLE:
            # Gas-vs-stroom: hergebruik berekening van TYPE 1 (of bereken opnieuw als type 4 alleen)
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
                else:
                    if days_since >= LEGIONELLA_INTERVAL_DAYS and not want_on:
                        # Boiler nodig voor legionella — override want_on
                        want_on = True
                        if days_since >= LEGIONELLA_DEADLINE_DAYS:
                            reason = f"Legionella DEADLINE: {days_since:.0f} dagen geleden (force)"
                        else:
                            reason = f"Legionella preventie: {days_since:.0f} dagen geleden"
                        _LOGGER.info("BoilerController [%s]: %s", b.label, reason)
                    elif days_since >= LEGIONELLA_DEADLINE_DAYS:
                        want_on = True
                        reason = f"Legionella DEADLINE overschreden: {days_since:.0f} dagen"
                        _LOGGER.warning("BoilerController [%s]: %s", b.label, reason)

        # ── v4.6.12: Hardware deadband compensatie ────────────────────────────
        # Ariston/WP-boilers starten pas als de watertemperatuur ver genoeg onder
        # het setpoint zakt. We sturen een iets hoger setpoint om dit te compenseren.
        # Auto-waarde: 2.0°C voor heat_pump/hybrid, 0.0 voor andere typen.
        _hw_deadband = b.hardware_deadband_c
        if _hw_deadband == 0.0 and btype in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID):
            _hw_deadband = 2.0
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
        # boost het setpoint tijdelijk om de hardware te forceren te starten.
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
            await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
        if action == "turn_off":
            await self._switch_smart(b.entity_id, False, b, solar_surplus_w); b.last_off_ts = now
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

        # Legionella: trigger groep als één van de boilers een cyclus nodig heeft
        for b in group.boilers:
            if group.learner.legionella_needed(b.entity_id):
                return True

        return False

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

            # manual override actief → volledig overslaan
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
                tag    = " [geleerd]" if delivery_eid else " [standaard]"
                suffix = f" [levering{tag}]" if b.is_delivery else ""
                # v4.5.15: toon duidelijke reden als temperatuursensor ontbreekt
                # (ook na climate + vermogensfallback — dan is er echt niets)
                if b.current_temp_c is None:
                    reason = f"seq{suffix}: geen temperatuursensor (ook geen climate/vermogen) — trigger actief"
                else:
                    reason = f"seq{suffix}: {b.temp_deficit_c:.1f}°C onder setpoint"
                action = self._apply_timers(b, True, is_on, now, reason)
                if action == "turn_on":
                    await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
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
            action = self._apply_timers(b, True, is_on, now, reason)
            if action == "turn_on":
                await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
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
                await self._switch_smart(b.entity_id, True, b, solar_surplus_w); b.last_on_ts = now
            decisions.append(BoilerDecision(b.entity_id, b.label, action, reason, is_on, group.id, 100.0))
        await self._async_save_power()
        return decisions

    def _group_standby(self, group: CascadeGroup) -> list[BoilerDecision]:
        return [BoilerDecision(b.entity_id, b.label, "hold_off", "Standby — geen trigger",
                               self._is_on(b.entity_id, b), group.id, 0.0) for b in group.boilers]

    # ── Sensoren lezen ────────────────────────────────────────────────────────

    async def _read_sensors(self) -> None:
        now = time.time()
        for b in list(self._boilers) + [b for g in self._groups for b in g.boilers]:
            # Lees altijd eerst de temperatuur uit de boiler-entiteit zelf
            # (water_heater / climate leveren current_temperature als attribuut)
            _entity_temp_c: float | None = None
            _boiler_state = self._hass.states.get(b.entity_id)
            if _boiler_state:
                _cur_t = _boiler_state.attributes.get("current_temperature")
                if _cur_t is not None:
                    try:
                        _entity_temp_c = float(_cur_t)
                    except (ValueError, TypeError):
                        pass

            # Lees geconfigureerde temp_sensor
            _sensor_temp_c: float | None = None
            if b.temp_sensor:
                s = self._hass.states.get(b.temp_sensor)
                if s and s.state not in ("unavailable", "unknown", ""):
                    try:
                        _sensor_temp_c = float(s.state)
                    except (ValueError, TypeError):
                        pass

            # Kies de beste temperatuursbron:
            # Als de geconfigureerde sensor >15°C afwijkt van de boiler-entiteit,
            # is de sensor waarschijnlijk verkeerd geconfigureerd (bijv. koud-inlaat).
            # Geef dan voorrang aan de boiler-entiteit zelf.
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

            # Laatste fallback: boiler aan maar trekt geen vermogen → al op temperatuur
            if b.current_temp_c is None and b.current_power_w is not None:
                _is_on = self._is_on(b.entity_id, b)
                if _is_on and b.current_power_w < 50 and b.power_w > 100:
                    b.current_temp_c = b.setpoint_c  # voorkomt onnodige trigger

            if b.energy_sensor:
                s = self._hass.states.get(b.energy_sensor)
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
                                if measured_w > 50:
                                    # Leer het vermogen als exponentieel voortschrijdend gemiddelde
                                    b.power_w = round(b.power_w * 0.85 + measured_w * 0.15, 0)
                                    self._power_dirty = True
                                b.current_power_w = measured_w
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
                    except (ValueError, TypeError):
                        pass
            else:
                # Geen energiesensor: gebruik huidige schakelaarstatus als schatting
                # current_power_w = power_w als aan, 0 als uit (voor dashboardweergave)
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

            # ── Thermisch model: heat_rate leren + legionella tick ────────────
            # Alleen als de boiler bij een groep met learner hoort
            for _grp in self._groups:
                if b not in _grp.boilers or not _grp.learner:
                    continue
                _is_on_now = self._is_on(b.entity_id, b)

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

                # Anode-waarschuwing
                _anode_pct = _grp.learner.get_anode_wear_pct(b)
                if _anode_pct >= ANODE_WARN_PCT:
                    _anode_kwh = _grp.learner.get_anode_kwh(b)
                    _LOGGER.warning(
                        "BoilerController [%s]: anode-slijtage %.0f%% (%.0f kWh doorvoer, "
                        "waterhardheid %.0f°dH) — anode controleren",
                        b.label, _anode_pct, _anode_kwh, b.water_hardness_dh,
                    )
                break  # boiler gevonden in groep, stop zoeken

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
                return (op or "").lower() == preset_on.lower()
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
        # Val terug op setpoint-logica voor dit domain.
        if domain == "water_heater":
            return s.state not in ("off", "unavailable", "unknown")

        return s.state == "on"

    # ── Schakelaar / dimmer ───────────────────────────────────────────────────

    async def _switch_smart(self, entity_id: str, on: bool,
                             boiler: Optional[BoilerState] = None,
                             solar_surplus_w: float = 0.0) -> None:
        if boiler and boiler.control_mode == "acrouter":
            await self._acrouter_set(boiler, on, solar_surplus_w)
            return
        if on and boiler and boiler.control_mode == "dimmer" and boiler.dimmer_proportional:
            await self._switch_dimmer_prop(entity_id, boiler, solar_surplus_w)
            return
        await self._switch(entity_id, on, boiler)

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

        # Bepaal gewenste modus en dimmer-percentage
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

        # Debounce: stuur alleen als mode of pct significant veranderd is
        mode_changed = (target_mode != boiler._acrouter_last_mode)
        pct_changed  = (target_mode == ACROUTER_MODE_MANUAL and
                        abs(target_pct - boiler._acrouter_last_pct) >= 5.0)
        throttled    = (now - boiler._acrouter_last_ts < ACROUTER_UPDATE_S)

        if not mode_changed and not pct_changed:
            return
        if pct_changed and not mode_changed and throttled:
            return  # kleine surplus-variatie, wacht op throttle-interval

        base_url = f"http://{boiler.acrouter_host}"
        try:
            timeout = _aiohttp.ClientTimeout(total=ACROUTER_HTTP_TIMEOUT)
            async with _aiohttp.ClientSession(timeout=timeout) as session:

                # Stuur modus
                async with session.post(
                    f"{base_url}/api/mode",
                    json={"mode": target_mode},
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("ACRouter: /api/mode → HTTP %d", resp.status)
                        return

                # In MANUAL mode: stuur ook dimmer-percentage
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
                    # v4.6.24: BOOST stuurt altijd max_setpoint_boost_c als temperature.
                    # Ariston Lydos respecteert set_temperature ook in BOOST-modus —
                    # zonder dit getal stuurt CloudEMS het normale setpoint (bijv. 58°C)
                    # en haalt de boiler nooit 75°C, ook al staat BOOST aan.
                    # v4.6.57: uitzondering bij handmatige override — als active_setpoint_c
                    # bewust lager is ingesteld (bijv. 71°C < 75°C), respecteer dat setpoint.
                    # Zo kan de gebruiker via de virtuele thermostaat een tussenwaarde kiezen.
                    _auto_boost_sp = boiler.max_setpoint_boost_c if boiler.max_setpoint_boost_c > 0 else boiler.surplus_setpoint_c
                    _active_sp = boiler.active_setpoint_c or boiler.setpoint_c
                    _is_manual = boiler._manual_override_until > time.time()
                    if _is_manual and _active_sp > 0 and _active_sp < _auto_boost_sp:
                        target_sp = _active_sp
                    else:
                        target_sp = _auto_boost_sp
                elif not on:
                    # uitzetten: min_temp_c zodat boiler niet onnodig door blijft lopen
                    target_sp = boiler.min_temp_c
                else:
                    target_sp = boiler.active_setpoint_c or boiler.setpoint_c
                # v4.6.16: cap target_sp per modus — GREEN kan nooit boven max_setpoint_green_c
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
                target_sp = 60.0 if on else 40.0

            if domain == "climate":
                await self._hass.services.async_call("climate", "set_preset_mode",
                    {"entity_id": entity_id, "preset_mode": preset}, blocking=False)
                # Stuur ook setpoint zodat de boiler weet wanneer hij klaar is
                if self._hass.services.has_service("climate", "set_temperature"):
                    await self._hass.services.async_call("climate", "set_temperature",
                        {"entity_id": entity_id, "temperature": target_sp}, blocking=False)
                _LOGGER.debug("BoilerController [%s]: climate preset=%s + setpoint=%.1f°C",
                              boiler.label if boiler else entity_id, preset, target_sp)
                return
            if domain == "water_heater":
                # v4.6.5: Ariston Lydos e.d. begrenzen setpoint per modus via een apart
                # number-entity (bijv. number.ariston_max_setpoint_temperature).
                # In GREEN-modus staat dit op bijv. 53°C — dan kan set_temperature(60) nooit
                # effectief zijn. Zet het number EERST op de juiste waarde vóór de moduswisseling:
                #   BOOST aan  → max_setpoint_boost_c (bijv. 75°C) zodat het setpoint bereikt kan worden
                #   GREEN aan  → max_setpoint_green_c (bijv. 53°C) zodat GREEN correct werkt

                # v4.6.52: gebruik gecachede waarde, scan entity registry maar 1x
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

                # v4.6.57: stuurvolgorde voor Ariston Lydos (mode → max_setpoint → temperature)
                # met delays zodat de cloud-sync niet wordt overgeslagen:
                # 1) set_operation_mode — blocking
                # 2) 2s wachten zodat Ariston cloud de mode-switch verwerkt
                # 3) max_setpoint number aanpassen — blocking
                # 4) 1s wachten zodat max_setpoint actief is
                # 5) set_temperature — blocking

                # Stap 1: mode-switch
                if self._hass.services.has_service("water_heater", "set_operation_mode"):
                    await self._hass.services.async_call("water_heater", "set_operation_mode",
                        {"entity_id": entity_id, "operation_mode": _preset_to_send}, blocking=True)
                elif self._hass.services.has_service("water_heater", "set_preset_mode"):
                    await self._hass.services.async_call("water_heater", "set_preset_mode",
                        {"entity_id": entity_id, "preset_mode": _preset_to_send}, blocking=True)
                else:
                    _LOGGER.debug("BoilerController [%s]: geen preset service beschikbaar, overgeslagen",
                                  boiler.label if boiler else entity_id)

                # Stap 2: korte pauze na mode-switch voor cloud-sync
                if boiler and _resolved_max_entity:
                    await asyncio.sleep(2)

                # Stap 3: max_setpoint number aanpassen ná mode-switch
                if boiler and _resolved_max_entity:
                    _max_ent_state2 = self._hass.states.get(_resolved_max_entity)
                    if _max_ent_state2 is not None:
                        _is_boost_preset2 = (preset == boiler.preset_on)
                        _desired_max2 = boiler.max_setpoint_boost_c if _is_boost_preset2 else boiler.max_setpoint_green_c
                        _hw_max2 = _max_ent_state2.attributes.get("max")
                        if _hw_max2 is not None:
                            try:
                                _desired_max2 = min(_desired_max2, float(_hw_max2))
                            except (ValueError, TypeError):
                                pass
                        try:
                            _cur_max2 = float(_max_ent_state2.state)
                        except (ValueError, TypeError):
                            _cur_max2 = None
                        if _cur_max2 is None or abs(_cur_max2 - _desired_max2) > 0.5:
                            _max_domain2 = _resolved_max_entity.split(".")[0]
                            if self._hass.services.has_service(_max_domain2, "set_value"):
                                _ent_attrs2 = _max_ent_state2.attributes
                                _ent_min2 = float(_ent_attrs2.get("min", 0))
                                _ent_max2 = float(_ent_attrs2.get("max", 99999))
                                _desired_max2 = max(_ent_min2, min(_ent_max2, _desired_max2))
                                await self._hass.services.async_call(
                                    _max_domain2, "set_value",
                                    {"entity_id": _resolved_max_entity, "value": _desired_max2},
                                    blocking=True,
                                )
                                _LOGGER.debug(
                                    "BoilerController [%s]: max_setpoint '%s' → %.1f°C (preset=%s)",
                                    boiler.label, _resolved_max_entity, _desired_max2, preset,
                                )
                                # Stap 4: wacht tot max_setpoint actief is voordat setpoint gestuurd wordt
                                await asyncio.sleep(1)

                # Stap 5: setpoint sturen
                if self._hass.services.has_service("water_heater", "set_temperature"):
                    await self._hass.services.async_call("water_heater", "set_temperature",
                        {"entity_id": entity_id, "temperature": target_sp}, blocking=True)
                _LOGGER.info("BoilerController [%s]: ✓ water_heater preset=%s max=%.0f°C setpoint=%.1f°C",
                              boiler.label if boiler else entity_id, _preset_to_send,
                              boiler.max_setpoint_boost_c if boiler else 0, target_sp)

                # v4.6.60: registreer als pending voor cloud verify/retry
                if boiler:
                    _max_sp_pending = 0.0
                    if _resolved_max_entity:
                        _is_boost_p = (preset == boiler.preset_on)
                        _max_sp_pending = boiler.max_setpoint_boost_c if _is_boost_p else boiler.max_setpoint_green_c
                    self._set_pending(boiler, _preset_to_send, target_sp, _max_sp_pending)
                return

        if ctrl in ("setpoint", "setpoint_boost"):
            sp = ((boiler.active_setpoint_c or boiler.setpoint_c) if on else boiler.min_temp_c) if boiler else (60.0 if on else 40.0)
            svc_domain = domain if domain in ("climate", "water_heater") else None
            if svc_domain:
                # v4.6.16: water_heater met ON_OFF feature (bijv. Midea E2/E3) vereist
                # turn_on/turn_off om de boiler echt aan/uit te zetten.
                # Stuur ALTIJD turn_on/turn_off zodat de boiler-power correct is,
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
                # geladen is. Bij ontbrekende service terugvallen op turn_on/off zodat de
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
                continue  # Energiesensor heeft prioriteit boven NILM
            eid = b.entity_id
            # Zoek dit apparaat op in de NILM-lijst op entity_id of naam
            for dev in nilm_devices:
                dev_eid = dev.get("source_entity_id", "") or dev.get("entity_id", "")
                dev_name = (dev.get("name") or dev.get("label") or "").lower()
                b_name = b.label.lower()
                if (dev_eid and dev_eid == eid) or (b_name and b_name in dev_name) or (dev_name and dev_name in b_name):
                    power_w = float(dev.get("current_power") or dev.get("power_w") or 0)
                    if power_w > 50 and dev.get("is_on"):
                        # EMA-update van geleerd vermogen via NILM
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
        Bij preset-boilers (Ariston) wordt altijd GREEN + gebruikerssetpoint gestuurd,
        nooit BOOST — dat is de taak van CloudEMS, niet van de handmatige override."""
        all_b = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        boiler = next((b for b in all_b if b.entity_id == entity_id), None)
        if boiler is None:
            _LOGGER.warning("BoilerController.send_now: entity_id %s niet gevonden", entity_id)
            return False
        if setpoint_c is not None:
            boiler.setpoint_c        = float(setpoint_c)
            boiler.active_setpoint_c = min(float(setpoint_c), boiler.hw_ceiling)
        # v4.6.48: voor preset-boilers: kies GREEN of BOOST op basis van het setpoint.
        # Als het setpoint binnen de GREEN-grens valt → GREEN (zuiniger, stiller).
        # Als het setpoint boven de GREEN-grens ligt → BOOST (enige manier om het te halen).
        _prev_force_green = boiler.force_green
        if boiler.control_mode == "preset":
            green_max = boiler.max_setpoint_green_c if boiler.max_setpoint_green_c > 0 else 53.0
            target = boiler.active_setpoint_c or boiler.setpoint_c
            boiler.force_green = (target <= green_max)
        _LOGGER.info(
            "BoilerController [%s]: send_now on=%s setpoint=%.1f°C (handmatig)",
            boiler.label, on, boiler.active_setpoint_c or boiler.setpoint_c,
        )
        await self._switch(entity_id, on, boiler)
        boiler.force_green = _prev_force_green
        return True

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
            # Geen pending commando
            if not b._pending_preset or b._next_verify_ts == 0.0:
                continue
            # Nog niet tijd voor verify
            if now < b._next_verify_ts:
                continue
            # Rate-limited
            if now < b._rate_limited_until:
                _LOGGER.debug(
                    "BoilerController [%s]: rate-limited, verify uitgesteld (nog %.0fs)",
                    b.label, b._rate_limited_until - now,
                )
                b._next_verify_ts = b._rate_limited_until + 5
                continue
            # Max retries bereikt → opgeven
            if b._pending_retries >= ARISTON_MAX_RETRIES:
                _LOGGER.warning(
                    "BoilerController [%s]: verify mislukt na %d pogingen — "
                    "Ariston cloud heeft preset=%s setpoint=%.1f°C niet geaccepteerd. Opgegeven.",
                    b.label, ARISTON_MAX_RETRIES, b._pending_preset, b._pending_setpoint,
                )
                b._pending_preset  = ""
                b._next_verify_ts  = 0.0
                continue

            # Lees actuele Ariston state
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

            # Stuur opnieuw — stap voor stap zoals in de normale _switch()
            try:
                # Stap 1: operation mode
                if self._hass.services.has_service("water_heater", "set_operation_mode"):
                    await self._hass.services.async_call(
                        "water_heater", "set_operation_mode",
                        {"entity_id": b.entity_id, "operation_mode": b._pending_preset},
                        blocking=True,
                    )
                await asyncio.sleep(2)

                # Stap 2: max_setpoint indien nodig
                max_ent = b.max_setpoint_entity or b._cached_max_setpoint_entity
                if b._pending_max_sp > 0.1 and max_ent:
                    ms = self._hass.states.get(max_ent)
                    if ms:
                        try:
                            cur = float(ms.state)
                        except (ValueError, TypeError):
                            cur = None
                        if cur is None or abs(cur - b._pending_max_sp) > ARISTON_TEMP_TOLERANCE:
                            _dom = max_ent.split(".")[0]
                            if self._hass.services.has_service(_dom, "set_value"):
                                _attrs = ms.attributes
                                _min = float(_attrs.get("min", 0))
                                _max = float(_attrs.get("max", 99999))
                                _v = max(_min, min(_max, b._pending_max_sp))
                                await self._hass.services.async_call(
                                    _dom, "set_value",
                                    {"entity_id": max_ent, "value": _v},
                                    blocking=True,
                                )
                                await asyncio.sleep(1)

                # Stap 3: setpoint
                if b._pending_setpoint > 0.1:
                    if self._hass.services.has_service("water_heater", "set_temperature"):
                        await self._hass.services.async_call(
                            "water_heater", "set_temperature",
                            {"entity_id": b.entity_id, "temperature": b._pending_setpoint},
                            blocking=True,
                        )

            except Exception as _retry_err:
                err_str = str(_retry_err)
                if "429" in err_str or "Too Many" in err_str.lower() or "rate" in err_str.lower():
                    b._rate_limited_until = now + ARISTON_RATE_LIMIT_S
                    b._next_verify_ts = now + ARISTON_RATE_LIMIT_S + 5
                    _LOGGER.warning(
                        "BoilerController [%s]: Ariston 429 rate-limit — pauze %ds",
                        b.label, ARISTON_RATE_LIMIT_S,
                    )
                else:
                    _LOGGER.warning(
                        "BoilerController [%s]: Ariston retry fout: %s", b.label, _retry_err,
                    )



    def get_status(self) -> list[dict]:
        # Inclusief groepsboilers — anders ziet de flow-kaart 0W bij cascade-configuraties
        all_boilers = list(self._boilers) + [b for g in self._groups for b in g.boilers]
        return [
            {"entity_id": b.entity_id, "label": b.label,
             "is_on": self._is_on(b.entity_id, b),
             "temp_c": b.current_temp_c, "setpoint_c": b.active_setpoint_c or b.setpoint_c,
             "active_setpoint_c": b.active_setpoint_c,  # gecapped op hw-max; None vóór eerste cyclus
             # current_power_w kan None zijn voor de eerste _read_sensors() cyclus.
             # Fallback: als de boiler nu aan staat, gebruik b.power_w als schatting.
             "power_w": b.current_power_w if b.current_power_w is not None
                        else (b.power_w if self._is_on(b.entity_id, b) else 0.0),
             "current_power_w": b.current_power_w if b.current_power_w is not None
                        else (b.power_w if self._is_on(b.entity_id, b) else 0.0),
             "cycle_kwh": round(b.cycle_kwh, 3),
             "thermal_loss_c_h": b.thermal_loss_c_h, "control_mode": b.control_mode,
             "boiler_type": b.boiler_type, "has_gas_heating": b.has_gas_heating,
             "post_saldering_mode": b.post_saldering_mode, "delta_t_optimize": b.delta_t_optimize,
             # v4.6.12: actieve modus + werkelijk verwarmt op basis van vermogen
             # v4.6.16: ook preset-mode boilers (bijv. Ariston via water_heater) correct weergeven
             "actual_mode": (b.preset_off if b.force_green else b.preset_on)
                            if (b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID)
                                or b.control_mode == "preset")
                            else ("on" if self._is_on(b.entity_id, b) else "off"),
             "is_heating": (b.current_power_w or 0.0) > 50.0,
             "stall_active": b._stall_active,
             "brand": b.brand,
             "brand_label": _BRAND_LABELS.get(b.brand, b.brand) if b.brand else "",
             # v4.5.92: gezondheid & veiligheid
             "cop_at_current_temp": _cop_from_temp(b.outside_temp_c, b.cop_curve_override)
                                    if b.boiler_type in (BOILER_TYPE_HEAT_PUMP, BOILER_TYPE_HYBRID) else None,
             "water_hardness_dh": b.water_hardness_dh,
             "legionella_days": getattr(b, "_leg_last_done", 0) and
                                round((time.time() - b._leg_last_done) / 86400, 1) if getattr(b, "_leg_last_done", 0) > 0 else None,
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
