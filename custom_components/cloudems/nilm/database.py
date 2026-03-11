# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""NILM Appliance Signature Database for CloudEMS — v1.21.0.

Provides a two-layer database:
  1. Built-in: ~200 European household appliance signatures baked into the code.
  2. Remote feed: Optional JSON feed from cloudems.eu with community-validated
     signatures. Downloaded once per day and cached in HA storage.
     If the feed is unavailable (no internet, server down), CloudEMS continues
     to function normally using only the built-in signatures — no errors raised.
"""

from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

REMOTE_FEED_URL     = "https://cloudems.eu/nilm/signatures-v1.json"
REMOTE_FEED_TTL_S   = 86_400   # refresh once per 24 h
REMOTE_FETCH_TIMEOUT = 10       # seconds — fail fast, never block HA startup


@dataclass
class ApplianceSignature:
    """Represents the power signature of a known appliance."""
    device_type: str
    name: str
    power_on_min: float    # Watt
    power_on_max: float    # Watt
    power_standby: float   # Watt
    rise_time: float       # seconds - how fast power rises on turn-on
    fall_time: float       # seconds - how fast power drops on turn-off
    duty_cycle: Optional[float] = None   # 0-1, cycling appliances like fridges
    harmonic_signature: Optional[List[float]] = None
    tags: List[str] = field(default_factory=list)
    source: str = "builtin"  # "builtin" | "community"
    name_nl: Optional[str] = None       # Dutch display name (None = use English name)
    three_phase: bool = False           # v4.5.13: apparaat verdeelt vermogen over 3 fasen

    def matches(self, delta_power: float, rise_time: float,
                rise_time_reliable: bool = True) -> Tuple[bool, float]:
        """Check if a power event matches this appliance. Returns (match, confidence).

        v1.21 — rise_time_reliable flag
        ─────────────────────────────────
        Polling-based detectors (HA coordinator at 10 s interval) always produce
        rise_time ≈ 20 s regardless of the actual appliance characteristics.
        Using this as a feature actively hurts classification:
          • Kettle (real rise 0.5 s) → rise_diff enormous → rise_time score ≈ 0
          • Old weight 0.70/0.30 → max power-only score = 0.70 < MIN_CONFIDENCE 0.80

        When rise_time_reliable=False (polling):
          Power weight = 1.00, rise_time weight = 0.00
          → Perfect center-range match yields confidence = 1.00
          → Any in-range match yields confidence ≥ 0.50 → passes

        When rise_time_reliable=True (direct clamp / 1 s sampling):
          Power weight = 0.80, rise_time weight = 0.20
          → Same behaviour as before but with corrected weights
        """
        abs_delta = abs(delta_power)

        POWER_W = 1.00 if not rise_time_reliable else 0.80
        RISE_W  = 0.00 if not rise_time_reliable else 0.20

        # ── Power range score ─────────────────────────────────────────────────
        if self.power_on_min <= abs_delta <= self.power_on_max:
            range_mid  = (self.power_on_min + self.power_on_max) / 2
            range_half = (self.power_on_max - self.power_on_min) / 2
            distance   = abs(abs_delta - range_mid)
            power_score = max(0.0, 1.0 - (distance / max(range_half, 1.0)))
        elif abs_delta < self.power_on_min * 0.8 or abs_delta > self.power_on_max * 1.2:
            # Far outside range — hard reject
            return False, 0.0
        else:
            # Soft zone: 0.8–1.0× min  or  1.0–1.2× max → partial credit
            if abs_delta < self.power_on_min:
                overshoot = (self.power_on_min - abs_delta) / max(self.power_on_min * 0.2, 1.0)
            else:
                overshoot = (abs_delta - self.power_on_max) / max(self.power_on_max * 0.2, 1.0)
            power_score = max(0.0, 1.0 - overshoot) * 0.50  # capped at 0.50 in soft zone

        confidence = power_score * POWER_W

        # ── Rise time score (only when sensor is fast enough to be meaningful) ─
        if RISE_W > 0 and self.rise_time > 0:
            rise_diff   = abs(rise_time - self.rise_time) / max(self.rise_time, 1.0)
            confidence += max(0.0, 1.0 - rise_diff) * RISE_W

        # v4.5.12: drempel omhoog — bij twijfel geen match teruggeven aan detector.
        # Zachte-zone partial matches die net boven 0.45 uitkomen zijn te onzeker.
        return confidence >= 0.60, min(confidence, 1.0)


# ─── BUILT-IN APPLIANCE DATABASE ──────────────────────────────────────────────
# ~200 common European household appliance signatures.
# Sources: REDD, UK-DALE, ECO, iAWE datasets + manufacturer specs.

APPLIANCE_DATABASE: List[ApplianceSignature] = [

    # ── Refrigerators & Freezers ─────────────────────────────────────────────
    ApplianceSignature("refrigerator", "Refrigerator Small (A+++)",       80,  150, 2, 2.0, 3.0, 0.35),
    ApplianceSignature("refrigerator", "Refrigerator Medium (A++)",      100,  200, 3, 2.5, 3.5, 0.35),
    ApplianceSignature("refrigerator", "Refrigerator Large (A+)",        150,  300, 4, 3.0, 4.0, 0.35),
    ApplianceSignature("refrigerator", "Combined Fridge-Freezer",        150,  350, 4, 2.5, 3.5, 0.30),
    ApplianceSignature("refrigerator", "Chest Freezer",                  100,  200, 2, 3.0, 4.0, 0.28),
    ApplianceSignature("refrigerator", "Upright Freezer",                120,  250, 3, 2.5, 3.5, 0.28),
    ApplianceSignature("refrigerator", "Wine Cooler",                     60,  130, 2, 2.0, 3.0, 0.40),
    ApplianceSignature("refrigerator", "Drinks Fridge",                   50,  120, 2, 2.0, 3.0, 0.40),
    ApplianceSignature("refrigerator", "American-style Fridge-Freezer",  200,  400, 5, 3.0, 4.0, 0.30),
    ApplianceSignature("refrigerator", "Drawer Freezer",                  80,  160, 2, 2.5, 3.5, 0.32),

    # ── Washing Machines ─────────────────────────────────────────────────────
    ApplianceSignature("washing_machine", "Washing Machine Motor",          400,   800, 5,  5.0, 8.0, tags=["motor"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (30°)",     800,  1200, 5,  8.0,10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (60°)",    1800,  2200, 5,  8.0,10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (90°)",    2000,  2500, 5,  8.0,10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Eco",            600,  1000, 5,  6.0, 9.0),
    ApplianceSignature("washing_machine", "Front Loader",                  1500,  2200, 5,  7.0, 9.0),
    ApplianceSignature("washing_machine", "Compact Washer",                 800,  1500, 5,  6.0, 9.0),
    ApplianceSignature("washing_machine", "Washing Machine Spin",           200,   600, 5,  3.0, 6.0, tags=["motor"]),

    # ── Tumble Dryers ────────────────────────────────────────────────────────
    ApplianceSignature("dryer", "Condenser Dryer",         2000, 2500, 5, 5.0, 8.0, tags=["heat"]),
    ApplianceSignature("dryer", "Vented Dryer",            2200, 2800, 5, 4.0, 7.0, tags=["heat"]),
    ApplianceSignature("dryer", "Heat Pump Dryer",          800, 1200, 5, 5.0, 8.0, tags=["heat_pump"]),
    ApplianceSignature("dryer", "Combined Washer-Dryer",   1800, 2500, 5, 7.0,10.0),
    ApplianceSignature("dryer", "Tumble Dryer Heat Only",  1500, 2200, 5, 4.0, 7.0, tags=["heat"]),

    # ── Dishwashers ──────────────────────────────────────────────────────────
    ApplianceSignature("dishwasher", "Dishwasher Eco",       800, 1200, 3, 8.0,10.0),
    ApplianceSignature("dishwasher", "Dishwasher Normal",   1500, 2000, 3, 7.0, 9.0),
    ApplianceSignature("dishwasher", "Dishwasher Intensive",2000, 2500, 3, 7.0, 9.0),
    ApplianceSignature("dishwasher", "Compact Dishwasher",  1000, 1500, 3, 7.0, 9.0),
    ApplianceSignature("dishwasher", "Dishwasher Motor",     100,  300, 3, 4.0, 6.0, tags=["motor"]),
    ApplianceSignature("dishwasher", "Dishwasher Dry Phase", 400,  800, 3, 5.0, 7.0, tags=["heat"]),

    # ── Ovens & Cooking ──────────────────────────────────────────────────────
    ApplianceSignature("oven", "Electric Oven Small",        1000, 1500, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Electric Oven Large",        1500, 2500, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Convection Oven",            1800, 2200, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Combination Microwave-Oven", 1200, 2000, 5, 3.0, 5.0),
    ApplianceSignature("oven", "Induction Hob (1 zone)",     1200, 2000, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Induction Hob (2 zones)",    2000, 4000, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Induction Hob (full)",       3500, 7200, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Electric Hob (single)",       800, 1500, 0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("oven", "Electric Hob (full)",        3000, 6000, 0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("oven", "Steam Oven",                 1500, 2000, 5, 3.0, 5.0),
    ApplianceSignature("oven", "Pyrolytic Oven",             2000, 3500, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Countertop Oven / Air Fryer", 800, 1800, 5, 2.0, 4.0),
    ApplianceSignature("oven", "Deep Fryer",                 1500, 2500, 0, 2.0, 4.0, tags=["heat"]),
    ApplianceSignature("oven", "Rice Cooker",                 400,  700, 0, 1.0, 2.0),
    ApplianceSignature("oven", "Slow Cooker",                 100,  300, 0, 2.0, 3.0),
    ApplianceSignature("oven", "Pressure Cooker (Electric)", 700, 1200, 0, 1.0, 2.0),
    ApplianceSignature("oven", "Waffle Iron",                1000, 1800, 0, 1.0, 2.0),

    # ── Microwaves ───────────────────────────────────────────────────────────
    ApplianceSignature("microwave", "Microwave 600W",     800, 1000, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Microwave 800W",    1000, 1200, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Microwave 1000W",   1200, 1400, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Grill Microwave",   1400, 1700, 3, 0.5, 1.0),
    ApplianceSignature("microwave", "Compact Microwave",  600,  900, 3, 0.5, 0.5),

    # ── Boilers & Water Heaters ──────────────────────────────────────────────
    ApplianceSignature("boiler", "Electric Water Boiler 2kW",  1800, 2200, 5, 3.0, 5.0, 0.20, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Water Boiler 3kW",  2800, 3200, 5, 3.0, 5.0, 0.20, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Water Boiler 6kW",  5500, 6500, 5, 3.0, 5.0, 0.18, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Water Boiler 9kW",  8500, 9500, 5, 3.0, 5.0, 0.15, tags=["resistive"]),
    ApplianceSignature("boiler", "Immersion Heater 1kW",        900, 1100, 2, 2.0, 3.0, 0.25),
    ApplianceSignature("boiler", "Immersion Heater 2kW",       1800, 2200, 2, 2.0, 3.0, 0.25),
    ApplianceSignature("boiler", "Electric Shower 6kW",        5500, 6500, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Shower 8kW",        7500, 8500, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Shower 10kW",       9500,10500, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Instantaneous Water Heater 4kW", 3800, 4200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Towel Radiator Electric",     200,  600, 5, 2.0, 3.0, tags=["resistive"]),

    # ── Heat Pumps & HVAC ────────────────────────────────────────────────────
    ApplianceSignature("heat_pump", "Air-Source Heat Pump 6kW",    1200, 2000, 50, 20.0, 30.0, 0.60, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Air-Source Heat Pump 9kW",    1800, 3000, 50, 20.0, 30.0, 0.60, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Air-Source Heat Pump 12kW",   2400, 4000, 50, 20.0, 30.0, 0.55, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Ground-Source Heat Pump 8kW", 1500, 2500, 50, 30.0, 40.0, 0.55, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Ground-Source Heat Pump 12kW",2200, 3500, 50, 30.0, 40.0, 0.55, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Heat Pump Water Heater",       500, 1200, 20, 15.0, 20.0, 0.40, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Split AC Cooling (1.5kW)",     400,  800, 30, 15.0, 20.0, 0.70, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Split AC Cooling (2.5kW)",     600, 1200, 30, 15.0, 20.0, 0.70, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Split AC Cooling (3.5kW)",     800, 1600, 30, 15.0, 20.0, 0.65, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Multi-Split AC",              1200, 3000, 50, 20.0, 30.0, 0.65, tags=["heat_pump"]),
    ApplianceSignature("heat_pump", "Air Curtain 2kW",             1800, 2200, 30, 5.0,  8.0),
    # v4.5.13: 3-fase warmtepompen — vergelijk op totaalvermogen (som L1+L2+L3)
    ApplianceSignature("heat_pump", "Lucht-WP 3-fase 6kW",   5000,  7000, 50, 20.0, 30.0, 0.55, tags=["heat_pump"], three_phase=True, name_nl="Lucht-warmtepomp 3-fase 6kW"),
    ApplianceSignature("heat_pump", "Lucht-WP 3-fase 9kW",   7500, 10500, 50, 20.0, 30.0, 0.55, tags=["heat_pump"], three_phase=True, name_nl="Lucht-warmtepomp 3-fase 9kW"),
    ApplianceSignature("heat_pump", "Lucht-WP 3-fase 12kW", 10000, 14000, 50, 20.0, 30.0, 0.55, tags=["heat_pump"], three_phase=True, name_nl="Lucht-warmtepomp 3-fase 12kW"),
    ApplianceSignature("heat_pump", "Bodem-WP 3-fase 8kW",   6500,  9500, 50, 30.0, 40.0, 0.55, tags=["heat_pump"], three_phase=True, name_nl="Bodem-warmtepomp 3-fase 8kW"),
    ApplianceSignature("heat_pump", "Bodem-WP 3-fase 12kW",  9500, 13500, 50, 30.0, 40.0, 0.55, tags=["heat_pump"], three_phase=True, name_nl="Bodem-warmtepomp 3-fase 12kW"),

    # ── CV & Central Heating ─────────────────────────────────────────────────
    ApplianceSignature("cv_boiler", "CV Boiler Burner",             1500, 2500, 10, 5.0, 8.0, tags=["heat"]),
    ApplianceSignature("cv_boiler", "CV Boiler Pump",                 50,  150,  5, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("cv_boiler", "HR Boiler 24kW",               1800, 2400, 10, 5.0, 8.0, tags=["heat"]),
    ApplianceSignature("cv_boiler", "HR Boiler 28kW",               2200, 2800, 10, 5.0, 8.0, tags=["heat"]),
    ApplianceSignature("cv_boiler", "Pellet Stove Fan",               150,  350,  5, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("cv_boiler", "Electric Radiator 500W",         450,  550,  0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("cv_boiler", "Electric Radiator 1kW",          900, 1100,  0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("cv_boiler", "Electric Radiator 2kW",         1800, 2200,  0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("cv_boiler", "Underfloor Heating Zone",        500, 2000, 10, 5.0, 8.0, tags=["resistive"]),
    ApplianceSignature("cv_boiler", "Zone Valve Actuator",             10,   30,  0, 1.0, 2.0),

    # ── EV Chargers ──────────────────────────────────────────────────────────
    ApplianceSignature("ev_charger", "EV Charger 1-phase 6A",     1300,  1500, 0,  5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 1-phase 10A",    2100,  2400, 0,  5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 1-phase 16A",    3400,  3700, 0,  5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 1-phase 32A",    7000,  7500, 0,  5.0, 10.0),
    # v4.5.13: 3-fase EV profielen matchen op totaalvermogen
    ApplianceSignature("ev_charger", "EV Charger 3-phase 11kW",  10500, 11500, 0,  5.0, 10.0, three_phase=True),
    ApplianceSignature("ev_charger", "EV Charger 3-phase 22kW",  21000, 23000, 0,  5.0, 10.0, three_phase=True),
    ApplianceSignature("ev_charger", "E-Bike Charger",               50,   200, 0,  2.0,  5.0),
    ApplianceSignature("ev_charger", "E-Scooter Charger",           100,   400, 0,  2.0,  5.0),
    ApplianceSignature("ev_charger", "E-Cargo Bike Charger",        100,   600, 0,  2.0,  5.0),

    # ── Thuisbatterij (laden) ─────────────────────────────────────────────────
    # v4.5.13: thuisbatterijen worden via inject_battery() apart bijgehouden,
    # maar als de SoC-sensor niet gekoppeld is valt de batterijlading als NILM-event binnen.
    # Deze profielen zorgen dat een 3-fase batterijlading correct gelabeld wordt
    # in plaats van als warmtepomp/boiler. Ze zijn altijd pending=True.
    ApplianceSignature("home_battery", "Thuisbatterij laden 3kW",   2700,  3300, 0, 10.0, 10.0, tags=["battery"], three_phase=True, name_nl="Thuisbatterij 3kW laden"),
    ApplianceSignature("home_battery", "Thuisbatterij laden 5kW",   4500,  5500, 0, 10.0, 10.0, tags=["battery"], three_phase=True, name_nl="Thuisbatterij 5kW laden"),
    ApplianceSignature("home_battery", "Thuisbatterij laden 6kW",   5500,  6500, 0, 10.0, 10.0, tags=["battery"], three_phase=True, name_nl="Thuisbatterij 6kW laden"),
    ApplianceSignature("home_battery", "Thuisbatterij laden 7kW",   6500,  7500, 0, 10.0, 10.0, tags=["battery"], three_phase=True, name_nl="Thuisbatterij 7kW laden"),
    ApplianceSignature("home_battery", "Thuisbatterij laden 10kW",  9000, 11000, 0, 10.0, 10.0, tags=["battery"], three_phase=True, name_nl="Thuisbatterij 10kW laden"),

    # ── Lighting ─────────────────────────────────────────────────────────────
    ApplianceSignature("light", "LED Bulb 5-10W",         5,   12, 0, 0.1, 0.1),
    ApplianceSignature("light", "LED Spot Group 20-50W", 15,   55, 0, 0.2, 0.2),
    ApplianceSignature("light", "LED Strip",              10,   50, 0, 0.1, 0.2),
    ApplianceSignature("light", "Fluorescent Light",      18,   58, 0, 0.5, 1.0),
    ApplianceSignature("light", "Halogen Lamp",           35,  100, 0, 0.2, 0.5),
    ApplianceSignature("light", "Outdoor Lighting",       50,  200, 0, 0.2, 0.5),
    ApplianceSignature("light", "Street / Garden LED",    20,  100, 0, 0.2, 0.5),
    ApplianceSignature("light", "Grow Light 300W",       250,  350, 0, 0.5, 1.0),
    ApplianceSignature("light", "Grow Light 600W",       550,  650, 0, 0.5, 1.0),
    ApplianceSignature("light", "Philips Hue Bridge",      2,    5, 0, 0.1, 0.1),

    # ── Solar Inverters ──────────────────────────────────────────────────────
    ApplianceSignature("solar_inverter", "Solar Inverter 1.5kW",  -1600,  -1300, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 3kW",    -3200,  -2800, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 5kW",    -5200,  -4800, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 10kW",  -10500,  -9500, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Micro-Inverter 300W",    -320,   -280, 0, 30.0, 15.0),
    ApplianceSignature("solar_inverter", "Micro-Inverter 600W",    -650,   -550, 0, 30.0, 15.0),

    # ── Entertainment & Office ───────────────────────────────────────────────
    ApplianceSignature("entertainment", "LED TV 40-55\" (on)",       60,  130, 0, 1.0, 2.0),
    ApplianceSignature("entertainment", "LED TV 65-75\" (on)",      100,  200, 0, 1.0, 2.0),
    ApplianceSignature("entertainment", "OLED TV 55\"",              80,  160, 0, 1.0, 2.0),
    ApplianceSignature("entertainment", "Projector Home Cinema",    200,  400, 5, 2.0, 3.0),
    ApplianceSignature("entertainment", "AV Receiver",               50,  200,10, 1.0, 2.0),
    ApplianceSignature("entertainment", "Gaming PC",                200,  600,10, 3.0, 5.0),
    ApplianceSignature("entertainment", "Gaming Console",            90,  200,10, 2.0, 3.0),
    ApplianceSignature("entertainment", "Desktop PC",               100,  300,10, 3.0, 5.0),
    ApplianceSignature("entertainment", "Monitor 27\"",              25,   50, 5, 1.0, 2.0),
    ApplianceSignature("entertainment", "Monitor 32\" 4K",           40,   80, 5, 1.0, 2.0),
    ApplianceSignature("entertainment", "NAS (idle)",                10,   30, 5, 3.0, 5.0),
    ApplianceSignature("entertainment", "NAS (active)",              30,   80, 5, 3.0, 5.0),
    ApplianceSignature("entertainment", "Home Server",               50,  200, 5, 5.0, 8.0),
    ApplianceSignature("entertainment", "Network Switch / Router",    5,   20, 0, 0.5, 1.0),

    # ── Kitchen Appliances ───────────────────────────────────────────────────
    ApplianceSignature("kitchen", "Kettle 1.5kW",              1400, 1600, 0, 0.5, 0.5),
    ApplianceSignature("kitchen", "Kettle 2kW",                1900, 2100, 0, 0.5, 0.5),
    ApplianceSignature("kitchen", "Kettle 3kW",                2800, 3200, 0, 0.5, 0.5),
    ApplianceSignature("kitchen", "Coffee Machine Espresso",    800, 1500, 5, 1.0, 2.0),
    ApplianceSignature("kitchen", "Coffee Machine Filter",      800, 1200, 5, 1.0, 2.0),
    ApplianceSignature("kitchen", "Coffee Machine Pod",         900, 1400, 5, 1.0, 2.0),
    ApplianceSignature("kitchen", "Blender / Mixer",            300,  900, 0, 0.5, 1.0),
    ApplianceSignature("kitchen", "Stand Mixer",                200,  600, 0, 1.0, 2.0),
    ApplianceSignature("kitchen", "Food Processor",             300,  800, 0, 0.5, 1.0),
    ApplianceSignature("kitchen", "Bread Machine",              400,  700, 0, 2.0, 3.0),
    ApplianceSignature("kitchen", "Sous Vide Circulator",       200,  500, 0, 1.0, 2.0),

    # ── Power Tools & Workshop ───────────────────────────────────────────────
    ApplianceSignature("power_tool", "Circular Saw",            800, 2000, 0, 1.0, 2.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Angle Grinder",           500, 1500, 0, 0.5, 1.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Drill Press",             300,  900, 0, 1.0, 2.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Table Saw",              1200, 3000, 0, 2.0, 3.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Air Compressor Small",    500, 1500, 0, 5.0, 8.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Air Compressor Large",   1500, 3000, 0, 5.0, 8.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Welder MIG/MAG",          800, 4000, 0, 1.0, 2.0),
    ApplianceSignature("power_tool", "3D Printer",              100,  350, 5, 3.0, 5.0),
    ApplianceSignature("power_tool", "CNC Router",              500, 2000, 0, 2.0, 3.0, tags=["motor"]),
    ApplianceSignature("power_tool", "Laser Cutter / Engraver", 200,  800, 0, 1.0, 2.0),

    # ── Garden & Outdoor ─────────────────────────────────────────────────────
    ApplianceSignature("garden", "Lawn Mower Electric",   800, 1800, 0, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("garden", "Robot Mower Charging",   30,   80, 0, 2.0, 4.0),
    ApplianceSignature("garden", "Garden Shredder",       1200, 2500, 0, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("garden", "Hedge Trimmer",          200,  600, 0, 0.5, 1.0),
    ApplianceSignature("garden", "Water Feature Pump",      30,  200, 5, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("garden", "Pool Pump Small",        300,  750, 5, 5.0, 8.0, tags=["motor"]),
    ApplianceSignature("garden", "Pool Pump Large",        750, 1500, 5, 5.0, 8.0, tags=["motor"]),
    ApplianceSignature("garden", "Pool Heater",           2000, 6000, 0, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("garden", "Irrigation Controller",    5,   30, 0, 1.0, 2.0),
    ApplianceSignature("garden", "Greenhouse Heater",      500, 2000, 0, 2.0, 3.0, tags=["heat"]),

    # ── Medical & Wellness ───────────────────────────────────────────────────
    ApplianceSignature("medical", "CPAP Machine",              30,  100, 5, 1.0, 2.0),
    ApplianceSignature("medical", "Oxygen Concentrator",      150,  400, 5, 3.0, 5.0),
    ApplianceSignature("medical", "Electric Blanket",          50,  200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("medical", "Infrared Sauna",           800, 2000, 0, 3.0, 5.0, tags=["resistive"]),
    ApplianceSignature("medical", "Traditional Sauna",       3000, 9000, 0, 5.0, 8.0, tags=["resistive"]),
    ApplianceSignature("medical", "Hot Tub / Jacuzzi",       1500, 6000, 50, 5.0, 8.0),

    # ── Misc Small Appliances ────────────────────────────────────────────────
    ApplianceSignature("unknown", "Hair Dryer 1200W",         1100, 1300, 0, 0.5, 0.5),
    ApplianceSignature("unknown", "Hair Dryer 1800W",         1700, 1900, 0, 0.5, 0.5),
    ApplianceSignature("unknown", "Hair Dryer 2200W",         2100, 2300, 0, 0.5, 0.5),
    ApplianceSignature("unknown", "Vacuum Cleaner",            800, 2200, 0, 1.0, 2.0),
    ApplianceSignature("unknown", "Robot Vacuum Charging",      30,   60, 0, 1.0, 2.0),
    ApplianceSignature("unknown", "Iron",                     1500, 2500, 0, 1.0, 2.0, 0.5),
    ApplianceSignature("unknown", "Steam Iron",               1800, 2800, 0, 1.0, 2.0, 0.4),
    ApplianceSignature("unknown", "Bread Toaster",             800, 1200, 0, 0.3, 0.5),
    ApplianceSignature("unknown", "Bread Toaster 2-slot",      800, 1000, 0, 0.3, 0.5),
    ApplianceSignature("unknown", "Bread Toaster 4-slot",     1600, 2000, 0, 0.3, 0.5),
    ApplianceSignature("unknown", "Electric Heater 1kW",       900, 1100, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Electric Heater 2kW",      1800, 2200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Electric Heater 3kW",      2800, 3200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Fan Heater (low)",          400,  700, 0, 0.5, 1.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Oil Radiator 1.5kW",       1400, 1600, 0, 2.0, 3.0, 0.6, tags=["resistive"]),
    ApplianceSignature("unknown", "Sump Pump",                 200,  800, 0, 3.0, 5.0),
    ApplianceSignature("unknown", "Treadmill",                 400, 2000, 5, 5.0, 8.0),
    ApplianceSignature("unknown", "Exercise Bike",             100,  400, 5, 3.0, 5.0),
    ApplianceSignature("unknown", "Dehumidifier",              200,  600, 5, 5.0, 8.0, 0.8, tags=["motor"]),
    ApplianceSignature("unknown", "Air Purifier",               20,   80, 5, 2.0, 3.0),
    ApplianceSignature("unknown", "Central Vacuum",            800, 1500, 0, 1.0, 2.0, tags=["motor"]),
    ApplianceSignature("unknown", "Stair Lift",                200,  600, 5, 3.0, 5.0, tags=["motor"]),
    ApplianceSignature("unknown", "Garage Door Opener",         200,  500, 5, 2.0, 4.0, tags=["motor"]),
    ApplianceSignature("unknown", "Smart Doorbell Camera",        5,   20, 0, 0.2, 0.5),
    ApplianceSignature("unknown", "Security Camera System",      20,   80, 5, 1.0, 2.0),
    ApplianceSignature("unknown", "Home Alarm System",            5,   30, 0, 0.5, 1.0),
    ApplianceSignature("unknown", "UPS / Battery Backup",        30,  200,10, 2.0, 3.0),
    ApplianceSignature("unknown", "Electric Piano",              10,   60, 2, 0.5, 1.0),
    ApplianceSignature("unknown", "Printing Press (inkjet)",      8,   25, 2, 1.0, 2.0),
    ApplianceSignature("unknown", "Printing Press (laser)",     300,  700, 5, 1.0, 2.0),
]


# ─── Nederlandse apparaatnamen ────────────────────────────────────────────────
# Vertalingen zijn verplaatst naar translations.py (alle talen).
from .translations import localized_device_name, nl_device_name  # noqa: F401

# ─── NILMDatabase class ────────────────────────────────────────────────────────

class NILMDatabase:
    """Two-layer NILM appliance database.

    Layer 1 (builtin):  ~200 signatures always available, no network needed.
    Layer 2 (community): Optional JSON feed from cloudems.eu, cached 24 h.
                         If unreachable → silently ignored, no impact on Layer 1.
    """

    CACHE_KEY = "cloudems_nilm_remote_cache_v1"

    def __init__(self):
        self._db: List[ApplianceSignature] = list(APPLIANCE_DATABASE)
        self._remote_loaded = False
        self._remote_last_fetch: float = 0.0
        _LOGGER.info(
            "CloudEMS NILM Database loaded — %d built-in signatures",
            len(self._db),
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self, hass) -> None:
        """Load cached remote signatures from HA storage, then refresh if stale."""
        from homeassistant.helpers.storage import Store
        import time

        store = Store(hass, 1, self.CACHE_KEY)
        cached = await store.async_load()
        if cached:
            self._apply_remote_entries(cached.get("signatures", []))
            self._remote_last_fetch = cached.get("fetched_at", 0.0)
            _LOGGER.debug("NILM remote cache: %d community signatures loaded", len(cached.get("signatures", [])))

        # Refresh in background if stale — never blocks startup
        import time as _time
        if _time.time() - self._remote_last_fetch > REMOTE_FEED_TTL_S:
            hass.async_create_task(self._async_refresh_remote(hass, store))

    async def _async_refresh_remote(self, hass, store) -> None:
        """Fetch remote feed and update cache. Fails silently on any error."""
        import time
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        try:
            session = async_get_clientsession(self._hass)
            async with session.get(
                    REMOTE_FEED_URL,
                    timeout=aiohttp.ClientTimeout(total=REMOTE_FETCH_TIMEOUT),
                    headers={"User-Agent": "CloudEMS-HA/1.10.0"},
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.debug("NILM remote feed HTTP %d — using built-in only", resp.status)
                        return
                    payload = await resp.json(content_type=None)
            sigs = payload.get("signatures", [])
            if not isinstance(sigs, list):
                return
            self._apply_remote_entries(sigs)
            self._remote_last_fetch = time.time()
            await store.async_save({"signatures": sigs, "fetched_at": self._remote_last_fetch})
            _LOGGER.info("NILM remote feed: %d community signatures loaded from cloudems.eu", len(sigs))

        except asyncio.TimeoutError:
            _LOGGER.debug("NILM remote feed timeout — using built-in only")
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.debug("NILM remote feed unavailable (%s) — using built-in only", exc)

    def _apply_remote_entries(self, raw: list) -> None:
        """Merge community signatures into the database (no duplicates by name)."""
        existing_names = {s.name for s in self._db}
        added = 0
        for entry in raw:
            try:
                name = entry["name"]
                if name in existing_names:
                    continue
                self._db.append(ApplianceSignature(
                    device_type   = entry["device_type"],
                    name          = name,
                    power_on_min  = float(entry["power_on_min"]),
                    power_on_max  = float(entry["power_on_max"]),
                    power_standby = float(entry.get("power_standby", 0)),
                    rise_time     = float(entry.get("rise_time", 2.0)),
                    fall_time     = float(entry.get("fall_time", 3.0)),
                    duty_cycle    = entry.get("duty_cycle"),
                    tags          = entry.get("tags", []),
                    source        = "community",
                ))
                existing_names.add(name)
                added += 1
            except (KeyError, TypeError, ValueError):
                continue
        if added:
            self._remote_loaded = True
            _LOGGER.debug("NILM: merged %d community signatures", added)

    # ── Query API ─────────────────────────────────────────────────────────────

    @property
    def device_count(self) -> int:
        return len(self._db)

    @property
    def community_count(self) -> int:
        return sum(1 for s in self._db if s.source == "community")

    def classify(self, delta_power: float, rise_time: float = 2.0, language: str = "en",
                 rise_time_reliable: bool = False,
                 power_factor: float | None = None,
                 inrush_peak_a: float | None = None,
                 reactive_power_var: float | None = None,
                 thd_pct: float | None = None,
                 total_power_w: float | None = None) -> list:
        """Classify a power event against the database. Returns top-5 ranked matches.

        v1.21: rise_time_reliable defaults to False because CloudEMS coordinator
        runs at 10 s intervals — measured rise_time is always ~20 s regardless of
        the actual appliance. Pass True only when a sub-second clamp meter is used.

        v1.22: niche-category confidence cap applied.
        Truly rare device categories (power tools, medical equipment, garden
        machinery) have a hard confidence cap below MIN_CONFIDENCE, so they
        can never reach the detection threshold from the database layer alone.
        They are effectively invisible until the user explicitly confirms them
        (at which point confidence is set to 1.0 by user feedback).

        Common energy-management devices (heat pump, boiler, EV charger) are
        intentionally NOT penalised here — they may be statistically less common
        but are critical for CloudEMS to detect accurately.

        v1.23 — ESP32 1kHz feature pipeline volledig benut:
          inrush_peak_a    — piekstroom bij opstarten → inrush_ratio (A / A_nominaal)
                             Resistief ≈ 1×, motor 3–8×, LED 50–100× (maar <1ms)
                             Sterk onderscheidend voor wasmachine vs oven vs waterkoker
          reactive_power_var — reactief vermogen Q in VAR → power_factor berekenen als
                             cos φ niet direct beschikbaar; Q≈0 = puur resistief
          thd_pct          — Total Harmonic Distortion in %
                             Resistief ≈ 0%, SMPS (laptop/TV) 60–120%, motor 30–70%
                             Dimmer 40–80%. Scheidend voor overlap P-bereik.
        """
        # Confidence caps for niche/hobby categories.
        # Set these below NILM_MIN_CONFIDENCE (typically 0.75) to block auto-detection.
        # A value of 0.55 means: even a perfect power match → confidence = 0.55 < 0.75
        # → never shown unless user confirms.
        # Confidence caps voor niche/hobby categorieën.
        # NILM_MIN_CONFIDENCE = 0.55 — caps hieronder betekenen: nooit auto-gedetecteerd.
        # Een waarde van 0.40 = zelfs een perfecte power-match → confidence 0.40 < 0.55
        # → verschijnt nooit in de apparatenlijst tenzij de gebruiker het zelf toevoegt.
        #
        # power_tool cap verlaagd naar 0.40 (was 0.55 = precies op de drempel):
        # - Een cirkelzaag/boor/lasser thuis is zeldzaam
        # - Het vermogensbereik overlapt enorm met warmtepompen, CV-ketels, ovens
        # - Auto-detectie leidt structureel tot verkeerde labels en drift-alerts
        # - De gebruiker kan power tools altijd handmatig bevestigen via de NILM-beheer tab
        NICHE_CONFIDENCE_CAP: dict = {
            "power_tool":  0.40,  # cirkelzaag, tafelzaag, lasser — nooit auto-detecteren
            "medical":     0.40,  # CPAP, zuurstofconcentrator — nooit auto-detecteren
            "garden":      0.50,  # grasmaaier, heggeschaar — buiten, seizoensgebonden
            "unknown":     0.55,  # v4.5.12: loopband/ijzer/stofzuiger — te vaag, nooit auto-detecteren
        }

        matches = []
        for sig in self._db:
            # v4.5.13: 3-fase apparaten matchen op totaalvermogen (huis_w), niet per-fase delta.
            # Bij total_split meting is delta_power = totaal/3, waardoor 3-fase last op
            # verkeerde (te lage) waarde wordt gematcht. Als total_power_w beschikbaar is
            # gebruiken we dat voor three_phase signatures.
            if sig.three_phase and total_power_w is not None:
                match_power = total_power_w
            else:
                match_power = delta_power
            matched, confidence = sig.matches(match_power, rise_time,
                                              rise_time_reliable=rise_time_reliable)
            if matched:
                # Apply niche cap: rare categories get capped below detection threshold
                cap = NICHE_CONFIDENCE_CAP.get(sig.device_type, 1.0)
                confidence = round(min(confidence, cap), 3)
                matches.append({
                    "device_type": sig.device_type,
                    "name":        localized_device_name(sig.name, language),
                    "confidence":  confidence,
                    "power_min":   sig.power_on_min,
                    "power_max":   sig.power_on_max,
                    "source":      sig.source,
                })
        matches.sort(key=lambda x: x["confidence"], reverse=True)

        # ── v2.2: Power factor scoring (alleen als ESPHome-meter aanwezig) ─────
        # Tags per apparaattype → verwacht power factor bereik
        # Resistief (oven, waterkoker): cos φ ≈ 1.0
        # Motor (wasmachine, pomp):     cos φ ≈ 0.55–0.80
        # Elektronisch (TV, PC):        cos φ ≈ 0.60–0.90
        # LED/SMPS:                     cos φ ≈ 0.40–0.70
        PF_RANGES: dict = {
            "resistive":  (0.95, 1.00),
            "heat":       (0.95, 1.00),
            "heat_pump":  (0.75, 0.90),
            "motor":      (0.55, 0.82),
            "electronic": (0.55, 0.90),
            "led":        (0.40, 0.70),
        }
        TYPE_LOAD: dict = {
            "oven":            "resistive",
            "boiler":          "resistive",
            "cv_boiler":       "resistive",
            "washing_machine": "motor",
            "dryer":           "motor",
            "heat_pump":       "heat_pump",
            "ev_charger":      "motor",
            "refrigerator":    "motor",
            "dishwasher":      "motor",
            "lighting":        "led",
            "computer":        "electronic",
            "tv":              "electronic",
            "gaming":          "electronic",
        }
        # ═══════════════════════════════════════════════════════════════════
        # GRACEFUL DEGRADATION — ESP32 1kHz features
        # ═══════════════════════════════════════════════════════════════════
        # Elk blok hieronder is volledig onafhankelijk en optioneel.
        # Als een feature None is (geen ESP32, of ESP32 zonder die sensor)
        # wordt het blok volledig overgeslagen — géén effect op confidence,
        # géén fout, géén gewijzigde ranking. De basisclassificatie (P + rise_time)
        # werkt altijd identiek als zonder ESP32.
        #
        # Volgorde van toepassing (elk blok sorteert opnieuw):
        #   1. Power factor (cos φ)  — ±0.10  — al aanwezig in v2.2
        #   2. Reactief vermogen Q   — ±0.10  — afleiden als PF niet direct beschikbaar
        #   3. Inrush ratio          — ±0.15  — sterkste discriminator
        #   4. THD%                  — ±0.12  — onderscheidt SMPS van resistief/motor
        # ═══════════════════════════════════════════════════════════════════

        # ── Gedeelde lookup-tabellen (hergebruikt in alle blokken) ───────────
        PF_RANGES: dict = {
            "resistive":  (0.95, 1.00),
            "heat":       (0.95, 1.00),
            "heat_pump":  (0.75, 0.90),
            "motor":      (0.55, 0.82),
            "electronic": (0.55, 0.90),
            "led":        (0.40, 0.70),
        }
        TYPE_LOAD: dict = {
            "oven":            "resistive",
            "boiler":          "resistive",
            "cv_boiler":       "resistive",
            "kettle":          "resistive",
            "washing_machine": "motor",
            "dryer":           "motor",
            "heat_pump":       "heat_pump",
            "ev_charger":      "motor",
            "refrigerator":    "motor",
            "dishwasher":      "motor",
            "lighting":        "led",
            "computer":        "electronic",
            "tv":              "electronic",
            "gaming":          "electronic",
        }

        def _load_type(device_type: str) -> str | None:
            """Vertaal apparaattype naar belastingcategorie. Gebruikt tags als fallback."""
            load = TYPE_LOAD.get(device_type)
            if load is None:
                sigs = self.get_by_type(device_type)
                for tag in ("resistive", "motor", "heat", "electronic", "led"):
                    if any(tag in (s.tags or []) for s in sigs):
                        return tag
            return load

        # ── [1+2] Power factor — direct of afgeleid uit Q ────────────────────
        # Alleen actief als power_factor of reactive_power_var beschikbaar is.
        # Bij geen van beide: blok overgeslagen, ranking ongewijzigd.
        _pf = power_factor
        if _pf is None and reactive_power_var is not None:
            # Q beschikbaar maar cos φ niet → afleiden: cos φ = P / √(P²+Q²)
            import math as _math
            _s = _math.sqrt(abs(delta_power) ** 2 + reactive_power_var ** 2)
            if _s > 1.0:
                _pf = round(abs(delta_power) / _s, 3)

        if _pf is not None and 0.0 < _pf <= 1.0:
            for m in matches:
                load = _load_type(m["device_type"])
                if load and load in PF_RANGES:
                    pf_min, pf_max = PF_RANGES[load]
                    pf_mid = (pf_min + pf_max) / 2
                    pf_dev = abs(_pf - pf_mid) / max(pf_max - pf_min, 0.01)
                    pf_adj = round(max(-0.10, min(0.10, (1.0 - pf_dev) * 0.10)), 3)
                    m["confidence"] = round(max(0.0, min(1.0, m["confidence"] + pf_adj)), 3)
                    m["pf_adj"] = pf_adj
            matches.sort(key=lambda x: x["confidence"], reverse=True)

        # ── [3] Inrush ratio scoring ──────────────────────────────────────────
        # Alleen actief als inrush_peak_a beschikbaar is (ESP32 1kHz CT-meting).
        # Geen ESP32 → inrush_peak_a is None → dit blok wordt volledig overgeslagen.
        #
        # inrush_ratio = gemeten piekstroom / nominale piekstroom (δP/230V × √2)
        # Verwachte ratios:
        #   resistief (oven, waterkoker):  1.0–1.5×   (geen inrush)
        #   motor (wasmachine, droger):    3.0–8.0×   (groot vliegwiel)
        #   compressor (koelkast, WP):     2.5–6.0×
        #   SMPS/elektronisch:             3.0–15×    (condensator laadt op)
        #   LED (SMPS):                   10–80×      (maar <1ms, snel uitgedoofd)
        # Max effect: ±0.15 — bewust groter dan PF, inrush is sterker onderscheidend.
        INRUSH_RANGES: dict = {
            "resistive":  (1.0,  1.5),
            "heat":       (1.0,  1.5),
            "motor":      (2.5,  8.0),
            "heat_pump":  (2.5,  6.0),
            "electronic": (3.0, 15.0),
            "led":        (10.0, 80.0),
        }
        if inrush_peak_a is not None and inrush_peak_a > 0.0:
            rated_a = abs(delta_power) / 230.0 * 1.414
            if rated_a > 0.1:
                inrush_ratio = inrush_peak_a / rated_a
                for m in matches:
                    load = _load_type(m["device_type"])
                    if load and load in INRUSH_RANGES:
                        ir_min, ir_max = INRUSH_RANGES[load]
                        ir_mid  = (ir_min + ir_max) / 2
                        ir_half = max((ir_max - ir_min) / 2, 0.1)
                        ir_dist = abs(inrush_ratio - ir_mid) / ir_half
                        if ir_min <= inrush_ratio <= ir_max:
                            ir_adj = round(max(0.0, min(0.15, (1.0 - ir_dist) * 0.15)), 3)
                        else:
                            # Buiten bereik: malus schaalt met afstand, max -0.15
                            overshoot = min(ir_dist - 1.0, 1.0)
                            ir_adj = round(max(-0.15, -overshoot * 0.15), 3)
                        m["confidence"] = round(max(0.0, min(1.0, m["confidence"] + ir_adj)), 3)
                        m["inrush_adj"] = ir_adj
                matches.sort(key=lambda x: x["confidence"], reverse=True)

        # ── [4] THD scoring ───────────────────────────────────────────────────
        # Alleen actief als thd_pct beschikbaar is (ESP32 FFT op 1kHz stream).
        # Geen ESP32 of geen THD-sensor → thd_pct is None → blok overgeslagen.
        #
        # THD% typische waarden:
        #   resistief (oven, waterkoker, gloeilamp):  0–5%
        #   motor (wasmachine, koelkast):            20–50%
        #   dimmer (fase-aansnijding):               40–80%
        #   SMPS (laptop, PC, TV, LED-driver):       60–120%
        #   warmtepomp (inverter-gestuurd):          15–40%
        # Max effect: ±0.12
        THD_RANGES: dict = {
            "resistive":  (0.0,  8.0),
            "heat":       (0.0,  8.0),
            "motor":      (15.0, 55.0),
            "heat_pump":  (10.0, 45.0),
            "electronic": (50.0, 130.0),
            "led":        (40.0, 110.0),
        }
        if thd_pct is not None and thd_pct >= 0.0:
            for m in matches:
                load = _load_type(m["device_type"])
                if load and load in THD_RANGES:
                    thd_min, thd_max = THD_RANGES[load]
                    thd_mid  = (thd_min + thd_max) / 2
                    thd_half = max((thd_max - thd_min) / 2, 1.0)
                    thd_dist = abs(thd_pct - thd_mid) / thd_half
                    if thd_min <= thd_pct <= thd_max:
                        thd_adj = round(max(0.0, min(0.12, (1.0 - thd_dist) * 0.12)), 3)
                    else:
                        overshoot = min(thd_dist - 1.0, 1.0)
                        thd_adj = round(max(-0.12, -overshoot * 0.12), 3)
                    m["confidence"] = round(max(0.0, min(1.0, m["confidence"] + thd_adj)), 3)
                    m["thd_adj"] = thd_adj
            matches.sort(key=lambda x: x["confidence"], reverse=True)

        return matches[:5]

    def get_by_type(self, device_type: str) -> List[ApplianceSignature]:
        return [s for s in self._db if s.device_type == device_type]

    def get_stats(self) -> dict:
        return {
            "total":         self.device_count,
            "builtin":       sum(1 for s in self._db if s.source == "builtin"),
            "community":     self.community_count,
            "remote_loaded": self._remote_loaded,
        }
