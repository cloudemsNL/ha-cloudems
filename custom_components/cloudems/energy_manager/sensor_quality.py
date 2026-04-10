"""
CloudEMS SensorQualityMonitor — v5.5.505
Beoordeelt per sensor/kolom of data van een echte sensor komt of berekend is.

Retourneert kwaliteitsscore per categorie:
- 'sensor':     directe sensor meting (groen)
- 'calculated': berekend via Kirchhoff/W×t (oranje)
- 'estimated':  geschat via learner/default (geel)
- 'missing':    geen data beschikbaar (rood)

Toont ook setup-volledigheid als percentage.
"""
from __future__ import annotations
from typing import Optional

QUALITY_SENSOR     = "sensor"      # groen
QUALITY_CALCULATED = "calculated"  # oranje  
QUALITY_ESTIMATED  = "estimated"   # geel
QUALITY_MISSING    = "missing"     # rood

# Gewichten voor setup score
_WEIGHTS = {
    "grid_sensor":           10,
    "pv_sensor":             10,
    "battery_sensor":         8,
    "battery_soc":            5,
    "battery_kwh_sensor":     7,  # charge + discharge kWh sensoren
    "pv_energy_sensor":       7,
    "grid_kwh_sensor":        6,
    "house_learned":          5,
    "pv_forecast_calibrated": 5,
    "p1_realtime":            8,
    "phase_sensors":          4,
    "ev_sensor":              3,
    "boiler_sensor":          3,
}

class SensorQualityMonitor:
    """Beoordeelt configuratiekwaliteit en databronnen."""

    def __init__(self, config: dict):
        self.config = config

    def get_data_quality(self, coordinator_data: dict,
                          energy_source_mgr: dict) -> dict:
        """
        Retourneert kwaliteit per categorie.
        
        Returns:
            dict met {categorie: QUALITY_*} waarden
        """
        quality = {}
        
        # PV
        if any(mgr.last_ok for k, mgr in energy_source_mgr.items() if k.startswith("pv_")):
            quality["pv"] = QUALITY_SENSOR
        elif coordinator_data.get("solar_power") is not None:
            quality["pv"] = QUALITY_CALCULATED
        else:
            quality["pv"] = QUALITY_MISSING

        # Batterij vermogen
        bats = coordinator_data.get("batteries", [])
        if bats and not coordinator_data.get("battery_estimated"):
            quality["battery_power"] = QUALITY_SENSOR
        elif coordinator_data.get("battery_estimated"):
            quality["battery_power"] = QUALITY_CALCULATED
        else:
            quality["battery_power"] = QUALITY_MISSING

        # Batterij kWh
        chg_ok = any(mgr.last_ok for k, mgr in energy_source_mgr.items()
                     if k.startswith("bat_chg_"))
        dis_ok = any(mgr.last_ok for k, mgr in energy_source_mgr.items()
                     if k.startswith("bat_dis_"))
        if chg_ok and dis_ok:
            quality["battery_kwh"] = QUALITY_SENSOR
        elif coordinator_data.get("battery_raw_w") is not None:
            quality["battery_kwh"] = QUALITY_CALCULATED
        else:
            quality["battery_kwh"] = QUALITY_ESTIMATED

        # Grid
        if coordinator_data.get("grid_power") is not None:
            quality["grid"] = QUALITY_SENSOR
        else:
            quality["grid"] = QUALITY_MISSING

        # Grid kWh
        imp_ok = energy_source_mgr.get("grid_import") and energy_source_mgr["grid_import"].last_ok
        exp_ok = energy_source_mgr.get("grid_export") and energy_source_mgr["grid_export"].last_ok
        if imp_ok and exp_ok:
            quality["grid_kwh"] = QUALITY_SENSOR
        elif coordinator_data.get("import_kwh_today"):
            quality["grid_kwh"] = QUALITY_CALCULATED
        else:
            quality["grid_kwh"] = QUALITY_ESTIMATED

        # Huis
        if coordinator_data.get("house_power_measured"):
            quality["house"] = QUALITY_SENSOR
        elif coordinator_data.get("house_power") is not None:
            quality["house"] = QUALITY_CALCULATED
        else:
            quality["house"] = QUALITY_ESTIMATED

        return quality

    def get_setup_score(self, coordinator=None) -> dict:
        """
        Berekent setup-volledigheid als percentage en lijst van verbeterpunten.
        """
        cfg = self.config
        score = 0
        max_score = sum(_WEIGHTS.values())
        issues = []
        improvements = []

        # Grid sensor
        if cfg.get("grid_sensor") or cfg.get("import_power_sensor"):
            score += _WEIGHTS["grid_sensor"]
        else:
            issues.append("❌ Geen net/grid sensor — energiebalans onbetrouwbaar")

        # PV sensor
        inv_cfgs = cfg.get("inverter_configs", [])
        if inv_cfgs and any(i.get("entity_id") for i in inv_cfgs):
            score += _WEIGHTS["pv_sensor"]
        else:
            improvements.append("💡 Geen PV omvormer geconfigureerd")

        # Battery sensor
        bat_cfgs = cfg.get("battery_configs", [])
        if bat_cfgs and any(b.get("power_sensor") for b in bat_cfgs):
            score += _WEIGHTS["battery_sensor"]
            # Battery kWh sensoren
            has_kwh = any(b.get("charge_kwh_sensor") and b.get("discharge_kwh_sensor")
                         for b in bat_cfgs)
            if has_kwh:
                score += _WEIGHTS["battery_kwh_sensor"]
            else:
                improvements.append(
                    "⚡ Stel batterij kWh-sensoren in voor nauwkeurige statistieken "
                    "(Instellingen → Batterij)")
            # Battery SoC
            if any(b.get("soc_sensor") for b in bat_cfgs):
                score += _WEIGHTS["battery_soc"]
        else:
            improvements.append("💡 Geen batterij geconfigureerd")

        # PV energy sensor
        if inv_cfgs and any(i.get("energy_sensor") for i in inv_cfgs):
            score += _WEIGHTS["pv_energy_sensor"]
        elif inv_cfgs:
            improvements.append(
                "⚡ Stel PV energie-sensor in voor nauwkeurige productiedata "
                "(Instellingen → Omvormer)")

        # Grid kWh sensor
        if cfg.get("grid_import_kwh_sensor") and cfg.get("grid_export_kwh_sensor"):
            score += _WEIGHTS["grid_kwh_sensor"]
        elif cfg.get("grid_import_kwh_sensor") or cfg.get("grid_export_kwh_sensor"):
            score += _WEIGHTS["grid_kwh_sensor"] // 2
            improvements.append("⚡ Stel ook de export kWh-sensor in voor volledig beeld")

        # P1 realtime
        if cfg.get("p1_enabled") or cfg.get("import_power_sensor"):
            score += _WEIGHTS["p1_realtime"]
        else:
            issues.append("⚠️ Geen P1/DSMR realtime data — tariefoptimalisatie minder accuraat")

        # House learned (via learner kwaliteit)
        if coordinator:
            learner = getattr(coordinator, "_house_consumption_learner", None)
            if learner and hasattr(learner, "_samples") and len(getattr(learner, "_samples", [])) > 100:
                score += _WEIGHTS["house_learned"]
        else:
            score += _WEIGHTS["house_learned"]  # geen info, geef voordeel van twijfel

        # PV forecast calibrated
        if coordinator:
            pv_fc = getattr(coordinator, "_pv_forecast", None)
            if pv_fc and hasattr(pv_fc, "_profiles") and pv_fc._profiles:
                score += _WEIGHTS["pv_forecast_calibrated"]
        else:
            score += _WEIGHTS["pv_forecast_calibrated"]

        # Phase sensors
        if any(cfg.get(f"power_l{i}_import") for i in [1,2,3]):
            score += _WEIGHTS["phase_sensors"]
        
        pct = round(score / max_score * 100)
        return {
            "score_pct":    pct,
            "score":        score,
            "max_score":    max_score,
            "issues":       issues,
            "improvements": improvements,
            "label": (
                "🟢 Uitstekend" if pct >= 85 else
                "🟡 Goed"       if pct >= 65 else
                "🟠 Matig"      if pct >= 45 else
                "🔴 Basis"
            ),
        }
