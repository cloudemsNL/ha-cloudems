"""NILM Appliance Signature Database for CloudEMS."""
# Copyright (c) 2024 CloudEMS - https://cloudems.eu

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


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
    harmonic_signature: Optional[List[float]] = None  # power factor harmonics
    tags: List[str] = field(default_factory=list)

    def matches(self, delta_power: float, rise_time: float) -> Tuple[bool, float]:
        """Check if a power event matches this appliance. Returns (match, confidence)."""
        abs_delta = abs(delta_power)
        confidence = 0.0

        # Power range check
        if self.power_on_min <= abs_delta <= self.power_on_max:
            range_mid = (self.power_on_min + self.power_on_max) / 2
            range_half = (self.power_on_max - self.power_on_min) / 2
            distance = abs(abs_delta - range_mid)
            confidence = max(0.0, 1.0 - (distance / max(range_half, 1.0))) * 0.7
        elif abs_delta < self.power_on_min * 0.8 or abs_delta > self.power_on_max * 1.2:
            return False, 0.0

        # Rise time check (bonus confidence)
        if self.rise_time > 0:
            rise_diff = abs(rise_time - self.rise_time) / max(self.rise_time, 1.0)
            rise_confidence = max(0.0, 1.0 - rise_diff) * 0.3
            confidence += rise_confidence

        return confidence >= 0.5, min(confidence, 1.0)


# ─── BUILT-IN APPLIANCE DATABASE ──────────────────────────────────────────────
# This is the internal database with known device signatures.
# Covers 100+ common European household appliances.

APPLIANCE_DATABASE: List[ApplianceSignature] = [
    # ── Refrigerators & Freezers ──────────────────────────────────────────────
    ApplianceSignature("refrigerator", "Refrigerator Small (A+++)", 80, 150, 2, 2.0, 3.0, 0.35),
    ApplianceSignature("refrigerator", "Refrigerator Medium (A++)", 100, 200, 3, 2.5, 3.5, 0.35),
    ApplianceSignature("refrigerator", "Refrigerator Large (A+)", 150, 300, 4, 3.0, 4.0, 0.35),
    ApplianceSignature("refrigerator", "Combined Fridge-Freezer", 150, 350, 4, 2.5, 3.5, 0.30),
    ApplianceSignature("refrigerator", "Chest Freezer", 100, 200, 2, 3.0, 4.0, 0.28),
    ApplianceSignature("refrigerator", "Upright Freezer", 120, 250, 3, 2.5, 3.5, 0.28),
    ApplianceSignature("refrigerator", "Wine Cooler", 60, 130, 2, 2.0, 3.0, 0.40),
    ApplianceSignature("refrigerator", "Drinks Fridge", 50, 120, 2, 2.0, 3.0, 0.40),

    # ── Washing Machines ──────────────────────────────────────────────────────
    ApplianceSignature("washing_machine", "Washing Machine Motor", 400, 800, 5, 5.0, 8.0, tags=["motor"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (30°)", 800, 1200, 5, 8.0, 10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (60°)", 1800, 2200, 5, 8.0, 10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Heat (90°)", 2000, 2500, 5, 8.0, 10.0, tags=["heat"]),
    ApplianceSignature("washing_machine", "Washing Machine Eco", 600, 1000, 5, 6.0, 9.0),
    ApplianceSignature("washing_machine", "Front Loader", 1500, 2200, 5, 7.0, 9.0),

    # ── Tumble Dryers ─────────────────────────────────────────────────────────
    ApplianceSignature("dryer", "Condenser Dryer", 2000, 2500, 5, 5.0, 8.0, tags=["heat"]),
    ApplianceSignature("dryer", "Vented Dryer", 2200, 2800, 5, 4.0, 7.0, tags=["heat"]),
    ApplianceSignature("dryer", "Heat Pump Dryer", 800, 1200, 5, 5.0, 8.0, tags=["heat_pump"]),
    ApplianceSignature("dryer", "Combined Washer-Dryer", 1800, 2500, 5, 7.0, 10.0),

    # ── Dishwashers ───────────────────────────────────────────────────────────
    ApplianceSignature("dishwasher", "Dishwasher Eco", 800, 1200, 3, 8.0, 10.0),
    ApplianceSignature("dishwasher", "Dishwasher Normal", 1500, 2000, 3, 7.0, 9.0),
    ApplianceSignature("dishwasher", "Dishwasher Intensive", 2000, 2500, 3, 7.0, 9.0),
    ApplianceSignature("dishwasher", "Compact Dishwasher", 1000, 1500, 3, 7.0, 9.0),

    # ── Ovens & Cooking ───────────────────────────────────────────────────────
    ApplianceSignature("oven", "Electric Oven Small", 1000, 1500, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Electric Oven Large", 1500, 2500, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Convection Oven", 1800, 2200, 5, 3.0, 5.0, tags=["heat"]),
    ApplianceSignature("oven", "Combination Microwave-Oven", 1200, 2000, 5, 3.0, 5.0),
    ApplianceSignature("oven", "Induction Hob (1 zone)", 1200, 2000, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Induction Hob (2 zones)", 2000, 4000, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Induction Hob (full)", 3500, 7200, 0, 0.5, 0.5, tags=["induction"]),
    ApplianceSignature("oven", "Electric Hob (single)", 800, 1500, 0, 2.0, 3.0, tags=["resistive"]),
    ApplianceSignature("oven", "Electric Hob (full)", 3000, 6000, 0, 2.0, 3.0, tags=["resistive"]),

    # ── Microwaves ────────────────────────────────────────────────────────────
    ApplianceSignature("microwave", "Microwave 600W", 800, 1000, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Microwave 800W", 1000, 1200, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Microwave 1000W", 1200, 1400, 3, 0.5, 0.5),
    ApplianceSignature("microwave", "Grill Microwave", 1400, 1700, 3, 0.5, 1.0),

    # ── Kettles & Coffee ──────────────────────────────────────────────────────
    ApplianceSignature("kettle", "Electric Kettle 1.5kW", 1400, 1600, 0, 0.3, 0.5, tags=["resistive"]),
    ApplianceSignature("kettle", "Electric Kettle 2kW", 1900, 2100, 0, 0.3, 0.5, tags=["resistive"]),
    ApplianceSignature("kettle", "Electric Kettle 3kW", 2900, 3100, 0, 0.3, 0.5, tags=["resistive"]),
    ApplianceSignature("kettle", "Coffee Machine (heating)", 800, 1200, 8, 1.0, 2.0),
    ApplianceSignature("kettle", "Coffee Machine (brewing)", 300, 600, 8, 1.0, 2.0),
    ApplianceSignature("kettle", "Nespresso/Pod Machine", 1200, 1600, 5, 1.0, 2.0),
    ApplianceSignature("kettle", "Filter Coffee Machine", 600, 1000, 5, 1.0, 2.0),

    # ── TVs & AV ──────────────────────────────────────────────────────────────
    ApplianceSignature("television", "LED TV 32\"", 30, 60, 0.5, 1.0, 2.0),
    ApplianceSignature("television", "LED TV 42\"", 50, 100, 0.5, 1.0, 2.0),
    ApplianceSignature("television", "LED TV 55\"", 80, 150, 0.5, 1.0, 2.0),
    ApplianceSignature("television", "LED TV 65\"", 100, 200, 0.5, 1.0, 2.0),
    ApplianceSignature("television", "OLED TV 55\"", 100, 180, 0.5, 1.0, 2.0),
    ApplianceSignature("television", "Projector", 200, 400, 5, 2.0, 5.0),
    ApplianceSignature("television", "Soundbar", 20, 60, 1, 0.5, 1.0),
    ApplianceSignature("television", "AV Receiver", 30, 100, 5, 1.0, 2.0),

    # ── Computers & Electronics ───────────────────────────────────────────────
    ApplianceSignature("computer", "Desktop PC (idle)", 50, 150, 2, 3.0, 5.0),
    ApplianceSignature("computer", "Desktop PC (load)", 150, 400, 2, 3.0, 5.0),
    ApplianceSignature("computer", "Gaming PC", 200, 600, 5, 3.0, 5.0),
    ApplianceSignature("computer", "Laptop", 20, 80, 1, 1.0, 2.0),
    ApplianceSignature("computer", "Monitor 24\"", 20, 40, 0.5, 1.0, 2.0),
    ApplianceSignature("computer", "NAS (spinup)", 30, 80, 8, 3.0, 5.0),
    ApplianceSignature("computer", "Router/Modem", 8, 20, 0, 0.0, 0.0),
    ApplianceSignature("computer", "Printer (warming)", 300, 800, 3, 2.0, 5.0),

    # ── Heat Pumps ────────────────────────────────────────────────────────────
    ApplianceSignature("heat_pump", "Air/Water Heat Pump 6kW", 1200, 2000, 10, 15.0, 20.0),
    ApplianceSignature("heat_pump", "Air/Water Heat Pump 9kW", 1800, 3000, 10, 15.0, 20.0),
    ApplianceSignature("heat_pump", "Air/Water Heat Pump 12kW", 2400, 4000, 10, 15.0, 20.0),
    ApplianceSignature("heat_pump", "Air Conditioning 2kW", 400, 800, 5, 5.0, 10.0),
    ApplianceSignature("heat_pump", "Air Conditioning 3.5kW", 700, 1400, 5, 5.0, 10.0),
    ApplianceSignature("heat_pump", "Air Conditioning 5kW", 1000, 2000, 5, 5.0, 10.0),
    ApplianceSignature("heat_pump", "Ground Source Heat Pump", 2000, 5000, 15, 20.0, 25.0),

    # ── Boilers & Water Heaters ───────────────────────────────────────────────
    ApplianceSignature("boiler", "Electric Water Boiler 2kW", 1800, 2200, 5, 3.0, 5.0, 0.2, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Water Boiler 3kW", 2800, 3200, 5, 3.0, 5.0, 0.2, tags=["resistive"]),
    ApplianceSignature("boiler", "Immersion Heater 1kW", 900, 1100, 2, 2.0, 3.0, 0.25),
    ApplianceSignature("boiler", "Immersion Heater 2kW", 1800, 2200, 2, 2.0, 3.0, 0.25),
    ApplianceSignature("boiler", "Electric Shower 6kW", 5500, 6500, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Shower 8kW", 7500, 8500, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("boiler", "Electric Shower 10kW", 9500, 10500, 0, 1.0, 2.0, tags=["resistive"]),

    # ── EV Chargers ───────────────────────────────────────────────────────────
    ApplianceSignature("ev_charger", "EV Charger 1-phase 6A", 1300, 1500, 0, 5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 1-phase 16A", 3400, 3700, 0, 5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 1-phase 32A", 7000, 7500, 0, 5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 3-phase 11kW", 10500, 11500, 0, 5.0, 10.0),
    ApplianceSignature("ev_charger", "EV Charger 3-phase 22kW", 21000, 23000, 0, 5.0, 10.0),

    # ── Lighting ──────────────────────────────────────────────────────────────
    ApplianceSignature("light", "LED Bulb 5-10W", 5, 12, 0, 0.1, 0.1),
    ApplianceSignature("light", "LED Spot Group 20-50W", 15, 55, 0, 0.2, 0.2),
    ApplianceSignature("light", "LED Strip", 10, 50, 0, 0.1, 0.2),
    ApplianceSignature("light", "Fluorescent Light", 18, 58, 0, 0.5, 1.0),
    ApplianceSignature("light", "Halogen Lamp", 35, 100, 0, 0.2, 0.5),
    ApplianceSignature("light", "Outdoor Lighting", 50, 200, 0, 0.2, 0.5),

    # ── Solar Inverters ───────────────────────────────────────────────────────
    ApplianceSignature("solar_inverter", "Solar Inverter 1.5kW", -1600, -1300, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 3kW", -3200, -2800, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 5kW", -5200, -4800, 0, 60.0, 30.0),
    ApplianceSignature("solar_inverter", "Solar Inverter 10kW", -10500, -9500, 0, 60.0, 30.0),

    # ── Misc Small Appliances ─────────────────────────────────────────────────
    ApplianceSignature("unknown", "Hair Dryer 1200W", 1100, 1300, 0, 0.5, 0.5),
    ApplianceSignature("unknown", "Hair Dryer 1800W", 1700, 1900, 0, 0.5, 0.5),
    ApplianceSignature("unknown", "Vacuum Cleaner", 800, 2200, 0, 1.0, 2.0),
    ApplianceSignature("unknown", "Iron", 1500, 2500, 0, 1.0, 2.0, 0.5),
    ApplianceSignature("unknown", "Bread Toaster", 800, 1200, 0, 0.3, 0.5),
    ApplianceSignature("unknown", "Electric Heater 1kW", 900, 1100, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Electric Heater 2kW", 1800, 2200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Electric Heater 3kW", 2800, 3200, 0, 1.0, 2.0, tags=["resistive"]),
    ApplianceSignature("unknown", "Pool Pump", 300, 1500, 5, 5.0, 8.0),
    ApplianceSignature("unknown", "Sump Pump", 200, 800, 0, 3.0, 5.0),
    ApplianceSignature("unknown", "Treadmill", 400, 2000, 5, 5.0, 8.0),
]


class NILMDatabase:
    """Interface for the built-in NILM appliance database."""

    def __init__(self):
        self._db = APPLIANCE_DATABASE
        _LOGGER.info("CloudEMS NILM Database loaded with %d signatures", len(self._db))

    def classify(self, delta_power: float, rise_time: float = 2.0) -> List[Dict]:
        """Classify a power event against the database. Returns ranked matches."""
        matches = []
        for sig in self._db:
            matched, confidence = sig.matches(delta_power, rise_time)
            if matched:
                matches.append({
                    "device_type": sig.device_type,
                    "name": sig.name,
                    "confidence": round(confidence, 3),
                    "power_min": sig.power_on_min,
                    "power_max": sig.power_on_max,
                    "source": "database",
                })
        # Sort by confidence descending
        matches.sort(key=lambda x: x["confidence"], reverse=True)
        return matches[:5]  # Return top 5

    def get_by_type(self, device_type: str) -> List[ApplianceSignature]:
        """Get all signatures of a given device type."""
        return [s for s in self._db if s.device_type == device_type]
