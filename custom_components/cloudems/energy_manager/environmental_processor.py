"""
CloudEMS EnvironmentalProcessor — v5.5.512
Verwerkt omgevingssensoren en past sturing aan.

Elke sensor heeft concrete impact op de sturing:
- Irradiantie   → PV forecast real-time bijsturen
- Regen         → PV reinigingsadvies + forecast correctie
- CO₂           → Ventilatie koppeling aanbeveling
- Batterijtemp  → Laadbeperking bij lage/hoge temperatuur
- PV paneel T°  → Vermogenscorrectie (panelen leveren minder bij hitte)
- Waterverbruik → Lekdetectie + totale energierekening
- Wind          → Al verwerkt in coordinator/shutters
"""
from __future__ import annotations
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# LFP laadlimieten op basis van temperatuur (veilig bereik)
BATTERY_TEMP_LIMITS = [
    (-20, 0,    0.0,   "🚫 Laden gestopt: te koud (<0°C)"),
    (0,   5,    0.2,   "⚠️ Laden beperkt tot 20% (0-5°C)"),
    (5,   10,   0.5,   "⚠️ Laden beperkt tot 50% (5-10°C)"),
    (10,  45,   1.0,   None),  # normaal bereik
    (45,  50,   0.5,   "⚠️ Laden beperkt tot 50% (45-50°C)"),
    (50,  100,  0.0,   "🚫 Laden gestopt: te warm (>50°C)"),
]

# PV temperatuurcoëfficiënt (typisch -0.35%/°C voor monocrystallijn)
PV_TEMP_COEFF_PCT_PER_C = -0.35
PV_STCTEST_TEMP_C = 25.0  # standaardtestcondities

# Regensensor: hoeveel mm regen wast panelen schoon
RAIN_CLEANING_THRESHOLD_MM = 2.0

# CO₂ drempel voor ventilatie aanbeveling (ppm)
CO2_VENTILATION_THRESHOLD_PPM = 1000
CO2_HIGH_PPM = 1500

# Water lekkage drempel (liter per kwartier, bij nacht)
WATER_LEAK_THRESHOLD_L_PER_15MIN = 5.0


class EnvironmentalProcessor:
    """Verwerkt alle omgevingssensoren en genereert acties/correcties."""

    def __init__(self):
        self._rain_accumulator_mm: float = 0.0
        self._last_clean_date: Optional[str] = None
        self._pv_soiling_factor: float = 1.0  # 1.0 = schoon, 0.9 = 10% vervuiling

        self._water_yesterday_l: float = 0.0
        self._water_night_l: float = 0.0
        self._water_night_start: bool = False

        self._last_battery_temp_action: Optional[str] = None

    def process_irradiance(self, irradiance_wm2: Optional[float],
                           pv_forecast_w: float,
                           solar_power_w: float) -> dict:
        """
        Vergelijk gemeten irradiantie met PV-output voor real-time forecast correctie.
        Als panelen minder leveren dan verwacht op basis van straling → clipping of vervuiling.
        """
        if irradiance_wm2 is None or irradiance_wm2 < 10:
            return {"correction_factor": 1.0, "source": "no_sensor"}

        # Verwacht vermogen op basis van irradiantie
        # 1000 W/m² = STC, lineaire relatie
        expected_fraction = irradiance_wm2 / 1000.0
        if expected_fraction < 0.05:
            return {"correction_factor": 1.0, "source": "low_irradiance"}

        # Pas soiling factor toe
        effective_fraction = expected_fraction * self._pv_soiling_factor

        return {
            "correction_factor": effective_fraction,
            "irradiance_wm2": irradiance_wm2,
            "soiling_factor": self._pv_soiling_factor,
            "source": "measured",
        }

    def process_rain(self, rain_mm: Optional[float],
                     interval_s: float = 15.0) -> dict:
        """
        Detecteer regen en pas PV soiling factor aan.
        Regen reinigt panelen → betere opbrengst daarna.
        """
        if rain_mm is None or rain_mm <= 0:
            return {"cleaning_event": False, "soiling_factor": self._pv_soiling_factor}

        import datetime
        today = datetime.date.today().isoformat()
        self._rain_accumulator_mm += rain_mm

        cleaning_event = False
        if (self._rain_accumulator_mm >= RAIN_CLEANING_THRESHOLD_MM
                and self._last_clean_date != today):
            # Panelen worden schoongespoeld
            old_factor = self._pv_soiling_factor
            self._pv_soiling_factor = min(1.0, self._pv_soiling_factor + 0.05)
            self._last_clean_date = today
            self._rain_accumulator_mm = 0.0
            cleaning_event = True
            _LOGGER.info(
                "EnvironmentalProcessor: regen %.1f mm → panelen gereinigd, "
                "soiling %.2f → %.2f",
                rain_mm, old_factor, self._pv_soiling_factor
            )

        return {
            "cleaning_event":    cleaning_event,
            "rain_mm_today":     self._rain_accumulator_mm,
            "soiling_factor":    self._pv_soiling_factor,
            "last_cleaned":      self._last_clean_date,
        }

    def process_battery_temp(self, battery_temp_c: Optional[float],
                              max_charge_w: float) -> dict:
        """
        Pas maximale laadstroom aan op basis van batterijtemperatuur.
        Voorkomt schade bij extreme temperaturen.
        """
        if battery_temp_c is None:
            return {"charge_limit_factor": 1.0, "action": None}

        for t_min, t_max, factor, message in BATTERY_TEMP_LIMITS:
            if t_min <= battery_temp_c < t_max:
                if message and message != self._last_battery_temp_action:
                    _LOGGER.warning("CloudEMS batterijtemperatuur: %.1f°C — %s",
                                   battery_temp_c, message)
                    self._last_battery_temp_action = message
                elif not message:
                    self._last_battery_temp_action = None
                return {
                    "charge_limit_factor": factor,
                    "charge_limit_w":      round(max_charge_w * factor),
                    "battery_temp_c":      battery_temp_c,
                    "action":              message,
                }

        return {"charge_limit_factor": 1.0, "action": None}

    def process_pv_panel_temp(self, panel_temp_c: Optional[float],
                               nominal_power_w: float) -> dict:
        """
        Corrigeer PV vermogen voor paneeltemperatuur.
        Warmere panelen leveren minder: -0.35%/°C boven 25°C.
        """
        if panel_temp_c is None:
            return {"temp_correction_factor": 1.0, "source": "no_sensor"}

        delta_c = panel_temp_c - PV_STCTEST_TEMP_C
        correction = 1.0 + (PV_TEMP_COEFF_PCT_PER_C / 100.0) * delta_c
        correction = max(0.5, min(1.1, correction))  # sanity bounds

        return {
            "temp_correction_factor": round(correction, 4),
            "panel_temp_c":           panel_temp_c,
            "power_corrected_w":      round(nominal_power_w * correction),
            "source":                 "measured",
        }

    def process_co2(self, co2_ppm: Optional[float],
                    indoor_co2_ppm: Optional[float]) -> dict:
        """
        Detecteer hoge CO₂ en geef ventilatie aanbeveling.
        Hoge CO₂ + goedkope stroom → ventileer nu.
        """
        result = {"ventilation_needed": False, "co2_level": "ok", "action": None}

        ppm = indoor_co2_ppm or co2_ppm
        if ppm is None:
            return result

        if ppm >= CO2_HIGH_PPM:
            result.update({
                "ventilation_needed": True,
                "co2_level": "high",
                "action": f"🌬️ CO₂ {ppm:.0f} ppm — ventileer direct",
                "co2_ppm": ppm,
            })
        elif ppm >= CO2_VENTILATION_THRESHOLD_PPM:
            result.update({
                "ventilation_needed": True,
                "co2_level": "elevated",
                "action": f"💨 CO₂ {ppm:.0f} ppm — ventilatie aanbevolen",
                "co2_ppm": ppm,
            })
        else:
            result["co2_ppm"] = ppm

        return result

    def process_water(self, water_liter: Optional[float],
                      hour: int) -> dict:
        """
        Detecteer waterlekkage op basis van onverwacht verbruik 's nachts.
        """
        if water_liter is None:
            return {"leak_suspected": False}

        # Nacht: 23:00 - 06:00
        is_night = hour >= 23 or hour < 6

        if is_night:
            if not self._water_night_start:
                self._water_night_l = 0.0
                self._water_night_start = True
            self._water_night_l += water_liter
        else:
            self._water_night_start = False

        leak = (is_night and
                self._water_night_l > WATER_LEAK_THRESHOLD_L_PER_15MIN)

        if leak:
            _LOGGER.warning(
                "EnvironmentalProcessor: mogelijke waterlekkage! "
                "Nachtverbruik %.1f L (drempel: %.1f L)",
                self._water_night_l, WATER_LEAK_THRESHOLD_L_PER_15MIN
            )

        return {
            "leak_suspected":   leak,
            "night_usage_l":    round(self._water_night_l, 2),
            "water_liter":      water_liter,
        }

    def process_all(self, data: dict, max_charge_w: float = 3000.0,
                    nominal_pv_w: float = 0.0) -> dict:
        """Verwerk alle omgevingssensoren in één aanroep."""
        import datetime
        hour = datetime.datetime.now().hour

        results = {}

        results["irradiance"] = self.process_irradiance(
            data.get("irradiance_wm2"),
            data.get("solar_power", 0.0),
            data.get("solar_power", 0.0),
        )
        results["rain"] = self.process_rain(data.get("rain_mm"))
        results["battery_temp"] = self.process_battery_temp(
            data.get("battery_temp_c"), max_charge_w)
        results["pv_panel_temp"] = self.process_pv_panel_temp(
            data.get("pv_panel_temp_c"), nominal_pv_w)
        results["co2"] = self.process_co2(
            data.get("co2_ppm"), data.get("indoor_co2_ppm"))
        results["water"] = self.process_water(
            data.get("water_liter"), hour)

        return results
