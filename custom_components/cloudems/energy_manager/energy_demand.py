"""
CloudEMS Energy Demand Forecast
v1.0.0

Berekent per subsysteem hoeveel kWh er nog nodig is om het doel te bereiken,
en wat dat kost aan huidige en goedkoopste verwachte prijs.

Resultaat wordt gepubliceerd via sensor.cloudems_energy_demand en gebruikt
door de coördinator voor betere beslissingen.

Subsystemen:
  • boiler       — warm water tot setpoint (rekening met COP)
  • battery      — batterij tot SOC-doel
  • zones        — ruimteverwarming tot setpoint (per zone)
  • ev           — EV laden tot doel-SOC
  • ebike        — e-bike laden
  • pool         — zwembad circulatie + verwarming
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Warmtecapaciteit water: kWh per kg per °C
C_WATER_KWH = 0.001163

# Warmtecapaciteit lucht/beton (ruimteverwarming): effectieve thermische massa
# Vuistregel: 1 kW WP verwarmt ~30m³ woning met 1°C in ~30 min
# => massa_kg ≈ 50 × oppervlak_m2 (incl. muren, vloer, meubels)
C_ROOM_KWH_PER_M2_PER_K = 0.012   # kWh per m² per °C temperatuurverschil

# Zwembad
C_POOL_KWH_PER_M3_PER_K = 1.163    # kWh per m³ per °C (= 1000 kg × C_WATER)


@dataclass
class SubsystemDemand:
    """Energievraag van één subsysteem."""
    name:             str
    label:            str
    kwh_needed:       float          # kWh tot doel bereikt
    kwh_per_hour:     float          # huidig vermogen (kW = kWh/h)
    eta_minutes:      Optional[float] # geschatte minuten tot doel (None = onbekend)
    cost_now_eur:     float          # kosten bij huidige prijs
    cost_cheap_eur:   float          # kosten bij goedkoopste verwachte prijs
    saving_eur:       float          # potentiële besparing bij slim plannen
    current_val:      Optional[float] # huidige waarde (temp, SOC%, etc.)
    target_val:       Optional[float] # doelwaarde
    unit:             str = ""        # eenheid (°C, %, kWh)
    active:           bool = True     # is dit subsysteem actief/geconfigureerd?
    reason:           str = ""        # uitleg

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "label":         self.label,
            "kwh_needed":    round(self.kwh_needed, 3),
            "kwh_per_hour":  round(self.kwh_per_hour, 3),
            "eta_minutes":   round(self.eta_minutes, 0) if self.eta_minutes is not None else None,
            "cost_now_eur":  round(self.cost_now_eur, 3),
            "cost_cheap_eur": round(self.cost_cheap_eur, 3),
            "saving_eur":    round(self.saving_eur, 3),
            "current_val":   round(self.current_val, 2) if self.current_val is not None else None,
            "target_val":    round(self.target_val, 2)  if self.target_val  is not None else None,
            "unit":          self.unit,
            "active":        self.active,
            "reason":        self.reason,
        }


@dataclass
class EnergyAdvice:
    """Eén concreet besparingsadvies met berekende besparing."""
    id:           str           # unieke sleutel (bijv. "thermostat_down")
    category:     str           # "gas" | "electric" | "battery" | "behavior"
    icon:         str
    title:        str
    description:  str
    saving_eur:   float         # geschatte besparing in €
    saving_unit:  str           # "vandaag" | "deze week" | "per maand"
    action:       str           # korte actie-string voor weergave
    priority:     int = 5       # 1=urgent, 5=gewoon, 10=optioneel
    kwh_saved:    float = 0.0
    m3_saved:     float = 0.0

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "category":    self.category,
            "icon":        self.icon,
            "title":       self.title,
            "description": self.description,
            "saving_eur":  round(self.saving_eur, 2),
            "saving_unit": self.saving_unit,
            "action":      self.action,
            "priority":    self.priority,
            "kwh_saved":   round(self.kwh_saved, 3),
            "m3_saved":    round(self.m3_saved, 3),
        }


@dataclass
class EnergyDemandResult:
    """Totale energievraag over alle subsystemen."""
    subsystems:       list[SubsystemDemand] = field(default_factory=list)
    advices:          list[EnergyAdvice]    = field(default_factory=list)
    total_kwh:        float = 0.0
    total_cost_now:   float = 0.0
    total_cost_cheap: float = 0.0
    total_saving:     float = 0.0

    def to_sensor_dict(self) -> dict:
        active = [s for s in self.subsystems if s.active and s.kwh_needed > 0]
        # Splits apparaten van subsystemen voor overzichtelijkheid
        devices   = [s for s in active if s.name == "device"]
        systems   = [s for s in active if s.name != "device"]
        sorted_adv = sorted(self.advices, key=lambda a: (a.priority, -a.saving_eur))
        return {
            "subsystems":        [s.to_dict() for s in systems],
            "devices":           [s.to_dict() for s in devices],
            "advices":           [a.to_dict() for a in sorted_adv],
            "total_kwh":         round(self.total_kwh, 3),
            "total_cost_now":    round(self.total_cost_now, 3),
            "total_cost_cheap":  round(self.total_cost_cheap, 3),
            "total_saving":      round(self.total_saving, 3),
            "count":             len(active),
            "device_total_kwh":  round(sum(s.kwh_needed for s in devices), 3),
            "system_total_kwh":  round(sum(s.kwh_needed for s in systems), 3),
        }


class EnergyDemandCalculator:
    """
    Berekent de energievraag per subsysteem.

    Aanroepen vanuit de coordinator elke cyclus:
        result = calculator.calculate(data, price_info, config)
    """

    def __init__(self, hass) -> None:
        self.hass = hass

    def calculate(
        self,
        data:        dict,
        price_info:  dict,
        config:      dict,
        boiler_ctrl  = None,
        zone_climate = None,
    ) -> EnergyDemandResult:
        """Bereken energievraag voor alle subsystemen."""
        current_price = float(price_info.get("current_all_in") or price_info.get("current") or 0.0)
        cheap_price   = float(price_info.get("cheapest_remaining") or price_info.get("min_today") or current_price * 0.7)

        subsystems: list[SubsystemDemand] = []

        # ── 1. Boiler ────────────────────────────────────────────────────────
        boiler_demand = self._calc_boiler(data, config, boiler_ctrl, current_price, cheap_price)
        if boiler_demand:
            subsystems.extend(boiler_demand)

        # ── 2. Thuisbatterij ─────────────────────────────────────────────────
        bat_demand = self._calc_battery(data, config, price_info, current_price, cheap_price)
        if bat_demand:
            subsystems.append(bat_demand)

        # ── 3. Ruimteverwarming per zone ─────────────────────────────────────
        zone_demands = self._calc_zones(data, config, zone_climate, current_price, cheap_price)
        subsystems.extend(zone_demands)

        # ── 4. EV ─────────────────────────────────────────────────────────────
        ev_demand = self._calc_ev(data, config, current_price, cheap_price)
        if ev_demand:
            subsystems.append(ev_demand)

        # ── 5. E-bike ─────────────────────────────────────────────────────────
        ebike_demand = self._calc_ebike(data, config, current_price, cheap_price)
        if ebike_demand:
            subsystems.append(ebike_demand)

                # ── 5b. Gas verbruiksprognose ──────────────────────────────
        gas_demand = self._calc_gas(data, config)
        if gas_demand:
            subsystems.append(gas_demand)

# ── 6. Zwembad ────────────────────────────────────────────────────────
        pool_demand = self._calc_pool(data, config, current_price, cheap_price)
        if pool_demand:
            subsystems.append(pool_demand)

        
        # ── 7. Apparaat verbruiksprognose (NILM historisch) ────────────────
        device_forecasts = self._calc_device_forecast(data, config, current_price, cheap_price)
        subsystems.extend(device_forecasts)


        # ── Besparingsadvies ─────────────────────────────────────────────────
        _interim = EnergyDemandResult(subsystems=subsystems)
        advices  = self._calc_advice(data, config, _interim, current_price, cheap_price)

                # ── Totalen ───────────────────────────────────────────────────────────
        active = [s for s in subsystems if s.active and s.kwh_needed > 0]
        total_kwh       = sum(s.kwh_needed      for s in active)
        total_cost_now  = sum(s.cost_now_eur    for s in active)
        total_cost_cheap= sum(s.cost_cheap_eur  for s in active)
        total_saving    = sum(s.saving_eur       for s in active)

        return EnergyDemandResult(
            subsystems      = subsystems,
            advices         = advices,
            total_kwh       = total_kwh,
            total_cost_now  = total_cost_now,
            total_cost_cheap= total_cost_cheap,
            total_saving    = total_saving,
        )

    # ── Boiler ────────────────────────────────────────────────────────────────
    def _calc_boiler(self, data, config, boiler_ctrl, price_now, price_cheap) -> list[SubsystemDemand]:
        demands = []
        if not boiler_ctrl:
            return demands
        try:
            all_boilers = list(boiler_ctrl._boilers) + [
                b for g in boiler_ctrl._groups for b in g.boilers
            ]
            for b in all_boilers:
                if b.current_temp_c is None:
                    continue
                setpoint = b.active_setpoint_c or b.setpoint_c or 60.0
                deficit  = max(0.0, setpoint - b.current_temp_c)
                if deficit < 0.5:
                    demands.append(SubsystemDemand(
                        name="boiler", label=f"Boiler {b.label}",
                        kwh_needed=0.0, kwh_per_hour=0.0, eta_minutes=0.0,
                        cost_now_eur=0.0, cost_cheap_eur=0.0, saving_eur=0.0,
                        current_val=b.current_temp_c, target_val=setpoint, unit="°C",
                        active=True, reason="Op setpoint",
                    ))
                    continue

                tank_l = b._effective_tank_liters
                # COP voor WP/hybrid, anders 1.0
                from homeassistant.const import __version__ as _  # force import chain
                cop = 1.0
                if b.boiler_type in ("heat_pump", "hybrid"):
                    try:
                        from .boiler_controller import _cop_from_temp, COP_DHW_FACTOR
                        cop = _cop_from_temp(b.outside_temp_c, b.cop_curve_override) * COP_DHW_FACTOR
                    except Exception:
                        cop = 2.5

                kwh_therm = deficit * tank_l * C_WATER_KWH
                kwh_elec  = kwh_therm / max(cop, 0.1)

                power_kw  = b.power_w / 1000.0 if b.power_w > 0 else 1.5
                eta_min   = (kwh_elec / power_kw) * 60.0 if power_kw > 0 else None

                cost_now   = kwh_elec * price_now
                cost_cheap = kwh_elec * price_cheap
                saving     = max(0.0, cost_now - cost_cheap)

                reason = (
                    f"{deficit:.1f}°C tekort · {tank_l:.0f}L tank · "
                    f"COP {cop:.1f} · {kwh_elec:.2f} kWh elektrisch"
                )
                demands.append(SubsystemDemand(
                    name="boiler", label=f"Boiler {b.label}",
                    kwh_needed=kwh_elec, kwh_per_hour=power_kw,
                    eta_minutes=eta_min,
                    cost_now_eur=cost_now, cost_cheap_eur=cost_cheap, saving_eur=saving,
                    current_val=b.current_temp_c, target_val=setpoint, unit="°C",
                    active=True, reason=reason,
                ))
        except Exception as e:
            _LOGGER.debug("EnergyDemand boiler fout: %s", e)
        return demands

    # ── Batterij ──────────────────────────────────────────────────────────────
    def _calc_battery(self, data, config, price_info, price_now, price_cheap) -> Optional[SubsystemDemand]:
        try:
            soc_now    = data.get("battery_soc_pct")
            cap_kwh    = float(data.get("battery_capacity_kwh") or config.get("battery_capacity_kwh") or 0)
            if soc_now is None or cap_kwh <= 0:
                return None

            # Doelpercentage: uit price_info of config
            soc_target = float(
                price_info.get("battery_target_soc")
                or config.get("battery_target_soc_pct")
                or 100.0
            )
            deficit_pct = max(0.0, soc_target - float(soc_now))
            if deficit_pct < 1.0:
                return SubsystemDemand(
                    name="battery", label="Thuisbatterij",
                    kwh_needed=0.0, kwh_per_hour=0.0, eta_minutes=0.0,
                    cost_now_eur=0.0, cost_cheap_eur=0.0, saving_eur=0.0,
                    current_val=soc_now, target_val=soc_target, unit="%",
                    active=True, reason="Op doel-SOC",
                )

            kwh_needed = deficit_pct / 100.0 * cap_kwh
            # Laadvermogen: typisch 2-5 kW thuis
            charge_kw  = float(config.get("battery_charge_power_kw") or 2.0)
            eta_min    = (kwh_needed / charge_kw) * 60.0

            cost_now   = kwh_needed * price_now
            cost_cheap = kwh_needed * price_cheap
            saving     = max(0.0, cost_now - cost_cheap)

            return SubsystemDemand(
                name="battery", label="Thuisbatterij",
                kwh_needed=kwh_needed, kwh_per_hour=charge_kw,
                eta_minutes=eta_min,
                cost_now_eur=cost_now, cost_cheap_eur=cost_cheap, saving_eur=saving,
                current_val=float(soc_now), target_val=soc_target, unit="%",
                active=True,
                reason=f"{deficit_pct:.0f}% laden · {cap_kwh:.1f}kWh accu · {kwh_needed:.2f}kWh nodig",
            )
        except Exception as e:
            _LOGGER.debug("EnergyDemand battery fout: %s", e)
        return None

    # ── Ruimteverwarming zones ────────────────────────────────────────────────
    def _calc_zones(self, data, config, zone_climate, price_now, price_cheap) -> list[SubsystemDemand]:
        demands = []
        if not zone_climate:
            return demands
        try:
            outside_t = data.get("outside_temp_c")
            # COP warmtepomp ruimteverwarming (hoger dan DHW want lagere aanvoertemp)
            cop_room = 3.5  # standaard bij 7°C buiten
            try:
                from .boiler_controller import _cop_from_temp
                cop_room = _cop_from_temp(outside_t) * 1.2  # ruimte-COP hoger dan DHW
            except Exception:
                pass

            for zone in zone_climate._zones:
                try:
                    snap = zone._last_snap
                    if snap is None:
                        continue
                    cur_t  = snap.current_temp
                    tgt_t  = snap.target_temp
                    if cur_t is None or tgt_t is None:
                        continue
                    deficit = max(0.0, tgt_t - cur_t)
                    if deficit < 0.3:
                        continue

                    # Schat oppervlak uit zone-naam of gebruik standaard 30m²
                    area_m2 = float(getattr(zone, "_floor_area_m2", 0) or
                                    config.get(f"zone_{zone.name}_area_m2") or 30.0)
                    kwh_therm  = deficit * area_m2 * C_ROOM_KWH_PER_M2_PER_K
                    kwh_elec   = kwh_therm / max(cop_room, 0.1)

                    # Geschat vermogen WP ruimte: 0.5–3 kW afhankelijk van zone
                    power_kw   = float(getattr(zone, "_rated_power_kw", 0) or 1.5)
                    eta_min    = (kwh_elec / power_kw) * 60.0

                    cost_now   = kwh_elec * price_now
                    cost_cheap = kwh_elec * price_cheap
                    saving     = max(0.0, cost_now - cost_cheap)

                    demands.append(SubsystemDemand(
                        name="zone", label=f"Zone {zone.name}",
                        kwh_needed=kwh_elec, kwh_per_hour=power_kw,
                        eta_minutes=eta_min,
                        cost_now_eur=cost_now, cost_cheap_eur=cost_cheap, saving_eur=saving,
                        current_val=cur_t, target_val=tgt_t, unit="°C",
                        active=True,
                        reason=f"{deficit:.1f}°C tekort · {area_m2:.0f}m² · COP {cop_room:.1f}",
                    ))
                except Exception as ze:
                    _LOGGER.debug("EnergyDemand zone %s fout: %s", getattr(zone, "name", "?"), ze)
        except Exception as e:
            _LOGGER.debug("EnergyDemand zones fout: %s", e)
        return demands

    # ── EV ────────────────────────────────────────────────────────────────────
    def _calc_ev(self, data, config, price_now, price_cheap) -> Optional[SubsystemDemand]:
        try:
            ev_data = data.get("ev_session") or {}
            if not ev_data:
                return None
            soc_now    = ev_data.get("soc_pct") or ev_data.get("ev_soc_pct")
            soc_target = ev_data.get("target_soc_pct") or float(config.get("ev_target_soc_pct") or 80.0)
            cap_kwh    = float(ev_data.get("battery_kwh") or config.get("ev_battery_kwh") or 0)
            if soc_now is None or cap_kwh <= 0:
                return None

            deficit_pct = max(0.0, soc_target - float(soc_now))
            if deficit_pct < 1.0:
                return None

            eff = 0.92  # laadefficiëntie
            kwh_needed = deficit_pct / 100.0 * cap_kwh / eff
            charge_kw  = float(ev_data.get("charge_power_kw") or config.get("ev_charge_power_kw") or 7.4)
            eta_min    = (kwh_needed / charge_kw) * 60.0

            cost_now   = kwh_needed * price_now
            cost_cheap = kwh_needed * price_cheap
            saving     = max(0.0, cost_now - cost_cheap)

            return SubsystemDemand(
                name="ev", label="EV",
                kwh_needed=kwh_needed, kwh_per_hour=charge_kw,
                eta_minutes=eta_min,
                cost_now_eur=cost_now, cost_cheap_eur=cost_cheap, saving_eur=saving,
                current_val=float(soc_now), target_val=soc_target, unit="%",
                active=True,
                reason=f"{deficit_pct:.0f}% laden · {cap_kwh:.0f}kWh accu · {charge_kw:.1f}kW",
            )
        except Exception as e:
            _LOGGER.debug("EnergyDemand EV fout: %s", e)
        return None

    # ── E-bike ────────────────────────────────────────────────────────────────
    def _calc_ebike(self, data, config, price_now, price_cheap) -> Optional[SubsystemDemand]:
        try:
            mm_data = data.get("micro_mobility") or {}
            sessions = mm_data.get("active_sessions") or []
            if not sessions:
                return None

            total_kwh = 0.0
            total_kw  = 0.0
            labels    = []
            for s in sessions:
                soc_now    = s.get("soc_pct") or 0
                soc_target = 100.0
                cap_kwh    = float(s.get("battery_kwh") or config.get("ebike_battery_kwh") or 0.5)
                deficit    = max(0.0, soc_target - soc_now) / 100.0 * cap_kwh
                charge_kw  = float(s.get("power_w") or 100) / 1000.0
                total_kwh += deficit
                total_kw  += charge_kw
                labels.append(s.get("label", "E-bike"))

            if total_kwh < 0.01:
                return None

            eta_min    = (total_kwh / max(total_kw, 0.05)) * 60.0
            cost_now   = total_kwh * price_now
            cost_cheap = total_kwh * price_cheap

            return SubsystemDemand(
                name="ebike", label=", ".join(labels[:2]),
                kwh_needed=total_kwh, kwh_per_hour=total_kw,
                eta_minutes=eta_min,
                cost_now_eur=cost_now, cost_cheap_eur=cost_cheap, saving_eur=max(0, cost_now - cost_cheap),
                current_val=None, target_val=100.0, unit="%",
                active=True, reason=f"{len(sessions)} voertuig(en) · {total_kwh:.2f} kWh nodig",
            )
        except Exception as e:
            _LOGGER.debug("EnergyDemand ebike fout: %s", e)
        return None

    # ── Apparaat verbruiksprognose ───────────────────────────────────────────
    def _calc_device_forecast(
        self, data: dict, config: dict, price_now: float, price_cheap: float
    ) -> list[SubsystemDemand]:
        """
        Voorspel het resterende dagverbruik per bekend NILM-apparaat.

        Methode:
          1. Dagbaseline = max(yesterday_kwh, week_kwh/7) — routineapparaten
          2. Verwacht_vandaag = baseline × dag-van-de-week-correctie
          3. Huidig uur + time_profile → hoeveel van de dag is al "voorbij"
          4. Resterend = verwacht_vandaag − today_kwh (nooit negatief)
          5. kWh/uur = huidig vermogen of gemiddeld op basis van sessieduur

        Alleen apparaten met voldoende historische data (≥7 sessies of
        yesterday_kwh > 0.05) worden meegenomen.
        """
        import time as _time
        from datetime import datetime, timezone

        demands: list[SubsystemDemand] = []
        try:
            nilm_devices = data.get("nilm_devices", [])
            if not nilm_devices:
                return demands

            now       = datetime.now()
            hour_now  = now.hour
            weekday   = now.weekday()   # 0=ma, 6=zo
            # Fractie van de dag die al voorbij is (0.0 = middernacht, 1.0 = 23:59)
            frac_done = hour_now / 24.0

            # Slot-fractie per dagdeel
            SLOT_FRACS = {
                "night":   (0, 6),    # 00-06
                "day":     (6, 18),   # 06-18
                "evening": (18, 24),  # 18-24
            }

            for dv in nilm_devices:
                try:
                    name          = dv.get("user_name") or dv.get("name", "")
                    today_kwh     = float(dv.get("today_kwh") or 0)
                    yesterday_kwh = float(dv.get("yesterday_kwh") or 0)
                    week_kwh      = float(dv.get("week_kwh") or dv.get("energy", {}).get("week_kwh") or 0)
                    session_count = int(dv.get("session_count") or 0)
                    avg_dur_min   = float(dv.get("avg_duration_min") or 0)
                    current_power = float(dv.get("power_w") or dv.get("current_power") or 0)
                    time_profile  = dv.get("time_profile") or {}
                    is_on         = bool(dv.get("is_on") or dv.get("running"))
                    device_type   = dv.get("device_type") or dv.get("type") or "unknown"

                    # Sla infra-apparaten over (netwerk, server, etc.)
                    INFRA_TYPES = {"network", "server", "router", "modem", "nas", "infrastructure"}
                    if device_type.lower() in INFRA_TYPES:
                        # Infra-apparaten lopen 24/7 — dagbaseline eenvoudig
                        if yesterday_kwh < 0.01 and week_kwh < 0.1:
                            continue
                        baseline = yesterday_kwh if yesterday_kwh > 0.01 else week_kwh / 7.0
                        expected_today = baseline
                        remaining_kwh  = max(0.0, expected_today - today_kwh)
                        if remaining_kwh < 0.01:
                            continue
                        power_kw = current_power / 1000.0 if current_power > 0 else (remaining_kwh / ((24 - hour_now) / 24.0) if hour_now < 23 else 0.01)
                        eta_min  = (remaining_kwh / power_kw * 60) if power_kw > 0 else None
                        demands.append(SubsystemDemand(
                            name="device", label=name,
                            kwh_needed=round(remaining_kwh, 3),
                            kwh_per_hour=round(power_kw, 3),
                            eta_minutes=eta_min,
                            cost_now_eur=round(remaining_kwh * price_now, 3),
                            cost_cheap_eur=round(remaining_kwh * price_cheap, 3),
                            saving_eur=round(max(0, remaining_kwh * (price_now - price_cheap)), 3),
                            current_val=today_kwh, target_val=expected_today, unit="kWh",
                            active=True, reason=f"Altijd aan · baseline {baseline:.2f} kWh/dag",
                        ))
                        continue

                    # Routineapparaten: minimaal 7 sessies of gisteren data
                    if session_count < 7 and yesterday_kwh < 0.05:
                        continue

                    # Dagbaseline: voorkeur gisteren, fallback weekgemiddelde
                    baseline_yd  = yesterday_kwh if yesterday_kwh > 0.05 else 0.0
                    baseline_wk  = week_kwh / 7.0 if week_kwh > 0.1 else 0.0
                    baseline     = baseline_yd if baseline_yd > 0 else baseline_wk
                    if baseline < 0.02:
                        continue

                    # Weekdag-correctie: weekend vs doordeweeks
                    # Als week_kwh beschikbaar: schat weekend vs doordeweeks
                    # Eenvoudige benadering: geen correctie (toekomstige verbetering)
                    expected_today = baseline

                    # Tijdprofiel: hoeveel van het verwachte verbruik valt na nu?
                    if time_profile:
                        total_prof = sum(time_profile.values()) or 1
                        # Bereken gewogen fractie van het profiel na het huidige uur
                        frac_remaining_in_profile = 0.0
                        for slot, count_s in time_profile.items():
                            slot_range = SLOT_FRACS.get(slot, (0, 24))
                            slot_start, slot_end = slot_range
                            # Hoeveel van dit slot valt na hour_now?
                            remaining_in_slot = max(0, slot_end - max(hour_now, slot_start))
                            slot_duration = slot_end - slot_start
                            if slot_duration > 0:
                                frac_remaining_in_profile += (count_s / total_prof) * (remaining_in_slot / slot_duration)
                        remaining_kwh = max(0.0, expected_today * frac_remaining_in_profile - max(0, today_kwh - expected_today * (1 - frac_remaining_in_profile)))
                    else:
                        # Geen profiel: lineaire resterende fractie van de dag
                        frac_remaining = max(0.0, 1.0 - frac_done)
                        remaining_kwh  = max(0.0, expected_today * frac_remaining - (today_kwh - expected_today * frac_done))

                    remaining_kwh = max(0.0, remaining_kwh)
                    if remaining_kwh < 0.02:
                        continue

                    # Vermogen: huidig als aan, anders geschat op basis van sessieduur
                    if is_on and current_power > 20:
                        power_kw = current_power / 1000.0
                    elif avg_dur_min > 0 and session_count > 0:
                        # Schat vermogen uit historische sessie-energie
                        kwh_per_session = baseline / max(session_count / 30.0, 1.0)  # per dag × sessies/dag
                        power_kw = (kwh_per_session / (avg_dur_min / 60.0)) if avg_dur_min > 0 else 0.1
                    else:
                        power_kw = 0.1

                    eta_min = (remaining_kwh / power_kw * 60.0) if power_kw > 0 else None

                    # Besparingspotentieel
                    cost_now   = remaining_kwh * price_now
                    cost_cheap = remaining_kwh * price_cheap
                    saving     = max(0.0, cost_now - cost_cheap)

                    primary_slot = max(time_profile, key=time_profile.get) if time_profile else "onbekend"
                    reason = (
                        f"Baseline {baseline:.2f} kWh/dag · "
                        f"al {today_kwh:.2f} kWh · "
                        f"primair: {primary_slot}"
                    )

                    demands.append(SubsystemDemand(
                        name="device", label=name,
                        kwh_needed=round(remaining_kwh, 3),
                        kwh_per_hour=round(power_kw, 3),
                        eta_minutes=round(eta_min, 0) if eta_min else None,
                        cost_now_eur=round(cost_now, 3),
                        cost_cheap_eur=round(cost_cheap, 3),
                        saving_eur=round(saving, 3),
                        current_val=round(today_kwh, 3),
                        target_val=round(expected_today, 3),
                        unit="kWh",
                        active=True,
                        reason=reason,
                    ))
                except Exception as de:
                    _LOGGER.debug("EnergyDemand device %s fout: %s", dv.get("name", "?"), de)

        except Exception as e:
            _LOGGER.debug("EnergyDemand device forecast fout: %s", e)
        return demands

    # ── Gas verbruiksprognose ────────────────────────────────────────────────
    def _calc_gas(self, data: dict, config: dict) -> Optional[SubsystemDemand]:
        """
        Schat verwacht gasverbruik voor rest van de dag.

        Methode:
          1. Baseline = gemiddeld dagverbruik laatste 7 dagen uit day_records
          2. HDD-correctie: pas baseline aan op basis van vandaag vs gemiddeld HDD
             (koudere dag → meer gas, warmere dag → minder)
          3. Tijdprofiel: gas wordt verbruikt in ochtend (06-09) en avond (17-22)
             → schat hoeveel van die pieken nog voor ons liggen
          4. Resterend = verwacht_vandaag × resterende_fractie − al_verbruikt

        Gas demand heeft geen directe "kosten bij ander tijdstip" zoals stroom —
        gasverbruik is moeilijk te verschuiven — maar de prognose is waardevol
        voor de accu-beslissing ("hoeveel stroom sla ik op vs gas-equivalent").
        """
        import time as _time
        from datetime import datetime

        try:
            gas_sensor = data.get("gas_analysis") or {}
            day_records = gas_sensor.get("day_records", [])

            # Vandaag al verbruikt
            today_m3 = float(gas_sensor.get("dag_m3") or 0.0)
            gas_price = float(gas_sensor.get("gas_prijs_per_m3") or
                              config.get("gas_price_eur_m3") or 1.25)

            # Huidig HDD (graaddagen vandaag)
            outside_t   = data.get("outside_temp_c")
            HDD_BASE    = 18.0
            hdd_today   = max(0.0, HDD_BASE - float(outside_t or 10.0))

            # Baseline uit day_records (laatste 7 dagen, excl vandaag)
            from datetime import date as _date
            today_str = _date.today().isoformat()
            recent = [r for r in day_records if r.get("date", "") != today_str][-7:]

            if len(recent) < 2:
                return None  # te weinig data

            avg_m3    = sum(r.get("gas_m3", 0) for r in recent) / len(recent)
            avg_hdd   = sum(r.get("hdd", 1.0) for r in recent) / len(recent)

            if avg_m3 < 0.05:
                return None  # geen significant gasverbruik (zomer)

            # HDD-correctie: schaal baseline naar verwacht verbruik vandaag
            if avg_hdd > 0.1:
                hdd_factor = hdd_today / avg_hdd
                # Begrenzen: niet meer dan 2× of minder dan 0.1× baseline
                hdd_factor = max(0.1, min(2.5, hdd_factor))
            else:
                hdd_factor = 1.0  # geen stookdag — geen correctie

            expected_today_m3 = avg_m3 * hdd_factor

            # Tijdprofiel: gas piekt in ochtend (06-09) en avond (17-22)
            # Geschatte verdeling over de dag:
            #   nacht 00-06: 10%  (nagloeien CV)
            #   ochtend 06-09: 35%  (opwarmen huis)
            #   dag 09-17: 15%  (laag verbruik)
            #   avond 17-22: 35%  (opwarmen, koken, douchen)
            #   laat 22-24: 5%
            now_h = datetime.now().hour
            GAS_PROFILE = [
                (0,  6,  0.10),   # nacht
                (6,  9,  0.35),   # ochtend piek
                (9,  17, 0.15),   # dag
                (17, 22, 0.35),   # avond piek
                (22, 24, 0.05),   # laat
            ]
            # Bereken hoeveel van het dagprofiel nog vóór ons ligt
            frac_remaining = 0.0
            for start, end, weight in GAS_PROFILE:
                if now_h >= end:
                    continue  # dit blok is voorbij
                elif now_h <= start:
                    frac_remaining += weight  # volledig voor ons
                else:
                    # Deel van dit blok
                    frac_remaining += weight * (end - now_h) / (end - start)

            remaining_m3 = max(0.0, expected_today_m3 * frac_remaining - max(0.0, today_m3 - expected_today_m3 * (1 - frac_remaining)))
            remaining_m3 = max(0.0, remaining_m3)

            if remaining_m3 < 0.02:
                # Alles al verbruikt of verwaarloosbaar
                return SubsystemDemand(
                    name="gas", label="Gas (CV/boiler)",
                    kwh_needed=0.0, kwh_per_hour=0.0, eta_minutes=0.0,
                    cost_now_eur=0.0, cost_cheap_eur=0.0, saving_eur=0.0,
                    current_val=round(today_m3, 3), target_val=round(expected_today_m3, 3),
                    unit="m³", active=True, reason="Verwacht verbruik al bereikt",
                )

            # kWh equivalent voor energie-vergelijking (1 m³ aardgas ≈ 9.769 kWh, ketel 90% eff)
            kwh_per_m3  = 9.769 * 0.90
            remaining_kwh_therm = remaining_m3 * kwh_per_m3
            cost_eur     = remaining_m3 * gas_price

            # HDD-info voor reason
            hdd_str = f"HDD {hdd_today:.1f}°" if hdd_today > 0.5 else "geen stookdag"
            reason  = (
                f"Baseline {avg_m3:.2f} m³/dag (7d gem) · "
                f"HDD-factor ×{hdd_factor:.2f} · {hdd_str} · "
                f"vandaag al {today_m3:.2f} m³"
            )

            return SubsystemDemand(
                name="gas", label="Gas (CV/boiler)",
                kwh_needed=round(remaining_kwh_therm, 3),
                kwh_per_hour=0.0,   # gas heeft geen "vermogen" in kW
                eta_minutes=None,
                cost_now_eur=round(cost_eur, 3),
                cost_cheap_eur=round(cost_eur, 3),  # gas is niet tijdsafhankelijk
                saving_eur=0.0,
                current_val=round(today_m3, 3),
                target_val=round(expected_today_m3, 3),
                unit="m³",
                active=True,
                reason=reason,
            )
        except Exception as e:
            _LOGGER.debug("EnergyDemand gas fout: %s", e)
        return None

    # ── Besparingsadvies ─────────────────────────────────────────────────────
    def _calc_advice(
        self,
        data:       dict,
        config:     dict,
        result:     "EnergyDemandResult",
        price_now:  float,
        price_cheap: float,
    ) -> list["EnergyAdvice"]:
        """
        Genereer concrete besparingsadviezen op basis van de berekende demand.

        Elk advies heeft een berekende besparing in € voor vandaag zodat de
        gebruiker een bewuste keuze kan maken.
        """
        from datetime import datetime

        advices: list[EnergyAdvice] = []
        gas_price  = float(config.get("gas_price_eur_m3") or 1.25)
        hour_now   = datetime.now().hour
        outside_t  = float(data.get("outside_temp_c") or 10.0)
        HDD_BASE   = 18.0
        hdd_today  = max(0.0, HDD_BASE - outside_t)

        # ── Advies 1: Thermostaat 0.5°C lager ────────────────────────────────
        # Op basis van HDD-model: 0.5°C lagere setpoint ≈ 0.5/hdd_today × dagverbruik gas
        gas_sys = next((s for s in result.subsystems if s.name == "gas"), None)
        if gas_sys and gas_sys.kwh_needed > 0 and hdd_today > 1.0:
            # m³ besparing = avg_m3_per_hdd × 0.5°C × resterende_dag_fractie
            frac_left = max(0.0, (23 - hour_now) / 24.0)
            # Gas verbruik per HDD: baseline / hdd_today (al gecorrigeerd)
            remaining_m3 = gas_sys.target_val - gas_sys.current_val if gas_sys.target_val else 0
            if remaining_m3 > 0.1 and hdd_today > 0:
                m3_saved  = remaining_m3 * (0.5 / hdd_today) * 0.8  # 80% eff
                m3_saved  = min(m3_saved, remaining_m3 * 0.15)       # max 15% van verwacht
                eur_saved = round(m3_saved * gas_price, 2)
                if eur_saved >= 0.03:
                    advices.append(EnergyAdvice(
                        id="thermostat_down_half",
                        category="gas",
                        icon="🌡️",
                        title="Thermostaat 0,5°C lager",
                        description=(
                            f"Bij {outside_t:.0f}°C buiten en HDD {hdd_today:.1f} "
                            f"bespaart 0,5°C minder verwarming ca. {m3_saved:.2f} m³ gas "
                            f"voor de rest van vandaag."
                        ),
                        saving_eur=eur_saved,
                        saving_unit="vandaag",
                        action="Zet thermostaat 0,5°C lager",
                        priority=4,
                        m3_saved=round(m3_saved, 3),
                        kwh_saved=round(m3_saved * 9.769 * 0.90, 3),
                    ))
                # Extra: 1°C lager
                m3_saved_1 = min(remaining_m3 * (1.0 / max(hdd_today, 1.0)) * 0.8, remaining_m3 * 0.25)
                eur_saved_1 = round(m3_saved_1 * gas_price, 2)
                if eur_saved_1 >= 0.05:
                    advices.append(EnergyAdvice(
                        id="thermostat_down_one",
                        category="gas",
                        icon="🌡️",
                        title="Thermostaat 1°C lager",
                        description=(
                            f"1°C minder levert ca. {m3_saved_1:.2f} m³ gas besparing "
                            f"(≈ €{eur_saved_1:.2f}) voor de rest van vandaag. "
                            f"Zorg voor voldoende opwarmtijd 's ochtends."
                        ),
                        saving_eur=eur_saved_1,
                        saving_unit="vandaag",
                        action="Zet thermostaat 1°C lager",
                        priority=5,
                        m3_saved=round(m3_saved_1, 3),
                        kwh_saved=round(m3_saved_1 * 9.769 * 0.90, 3),
                    ))

        # ── Advies 2: Boiler setpoint 2°C lager ──────────────────────────────
        boiler_sys = next((s for s in result.subsystems if s.name == "boiler"), None)
        if boiler_sys and boiler_sys.kwh_needed > 0.1:
            # 2°C lager setpoint → minder kWh nodig
            cur   = boiler_sys.current_val or 50.0
            tgt   = boiler_sys.target_val  or 60.0
            delta = max(0.0, tgt - cur)
            if delta > 2.0:
                kwh_saved  = boiler_sys.kwh_needed * (2.0 / delta)
                eur_saved  = round(kwh_saved * price_now, 2)
                advices.append(EnergyAdvice(
                    id="boiler_setpoint_down",
                    category="electric",
                    icon="🚿",
                    title="Boiler setpoint 2°C lager",
                    description=(
                        f"Boiler nu op {cur:.0f}°C, doel {tgt:.0f}°C. "
                        f"2°C lager bespaart ca. {kwh_saved:.2f} kWh (€{eur_saved:.2f}) "
                        f"zonder merkbaar verlies aan comfort bij normaal gebruik."
                    ),
                    saving_eur=eur_saved,
                    saving_unit="vandaag",
                    action=f"Zet boiler setpoint op {tgt-2:.0f}°C",
                    priority=4,
                    kwh_saved=round(kwh_saved, 3),
                ))

        # ── Advies 3: EV laden verschuiven ───────────────────────────────────
        ev_sys = next((s for s in result.subsystems if s.name == "ev"), None)
        if ev_sys and ev_sys.kwh_needed > 1.0 and price_cheap < price_now * 0.75:
            kwh    = ev_sys.kwh_needed
            saving = round(kwh * (price_now - price_cheap), 2)
            if saving >= 0.10:
                advices.append(EnergyAdvice(
                    id="ev_charge_shift",
                    category="electric",
                    icon="🚗",
                    title="EV laden verschuiven",
                    description=(
                        f"{kwh:.1f} kWh te laden. Bij huidige prijs {price_now*100:.1f}ct "
                        f"kost dat €{kwh*price_now:.2f}. Verschuiven naar goedkoopste uur "
                        f"({price_cheap*100:.1f}ct) bespaart €{saving:.2f}."
                    ),
                    saving_eur=saving,
                    saving_unit="deze laadbeurt",
                    action="Stel EV in op daluren laden",
                    priority=2,
                    kwh_saved=0.0,
                ))

        # ── Advies 4: Batterij tekort — laden aanbevolen ─────────────────────
        bat_sys = next((s for s in result.subsystems if s.name == "battery"), None)
        bat_kwh_avail = 0.0
        bat_soc_st = data.get("battery_soc_pct")
        bat_cap    = float(config.get("battery_capacity_kwh") or 0)
        if bat_soc_st and bat_cap > 0:
            bat_kwh_avail = max(0.0, (float(bat_soc_st) - 10) / 100.0 * bat_cap)

        total_demand = result.total_kwh
        if bat_kwh_avail > 0 and total_demand > bat_kwh_avail + 0.5:
            gap = total_demand - bat_kwh_avail
            eur_gap = round(gap * price_now, 2)
            advices.append(EnergyAdvice(
                id="battery_shortage",
                category="battery",
                icon="🔋",
                title=f"Batterij tekort: {gap:.1f} kWh",
                description=(
                    f"Verwacht verbruik {total_demand:.1f} kWh, "
                    f"accu heeft {bat_kwh_avail:.1f} kWh beschikbaar. "
                    f"Tekort van {gap:.1f} kWh = €{eur_gap:.2f} van het net. "
                    f"Overweeg nu bij te laden als de prijs gunstig is."
                ),
                saving_eur=round(gap * (price_now - price_cheap), 2),
                saving_unit="vandaag",
                action="Laad accu bij voor nacht",
                priority=1,
                kwh_saved=0.0,
            ))

        # ── Advies 5: Douche korter ───────────────────────────────────────────
        if boiler_sys and boiler_sys.kwh_needed > 0.3:
            # Kortere douche: 2 minuten × 8 L/min = 16L warm water
            shower_l   = 2 * 8  # 16 liter
            cold_t     = 10.0
            shower_t   = 38.0
            tank_t     = float(boiler_sys.target_val or 60.0)
            if tank_t > shower_t:
                # Gemengd water: liter warm + liter koud nodig voor 16L op 38°C
                ratio_warm = (shower_t - cold_t) / (tank_t - cold_t)
                warm_l     = shower_l * ratio_warm
                kwh_saved  = warm_l * 0.001163 * (tank_t - cold_t)
                # COP correctie indien WP
                cop = 1.0
                if boiler_sys.reason and "COP" in boiler_sys.reason:
                    try:
                        cop = float(boiler_sys.reason.split("COP")[1].split()[0])
                    except Exception:
                        cop = 2.5
                kwh_elec = kwh_saved / max(cop, 1.0)
                eur_saved = round(kwh_elec * price_now, 2)
                if eur_saved >= 0.01:
                    advices.append(EnergyAdvice(
                        id="shorter_shower",
                        category="behavior",
                        icon="🚿",
                        title="Douche 2 minuten korter",
                        description=(
                            f"2 minuten minder douchen bespaart ~{warm_l:.0f}L warm water "
                            f"= {kwh_elec:.2f} kWh = €{eur_saved:.2f} per persoon per dag."
                        ),
                        saving_eur=eur_saved,
                        saving_unit="per douche",
                        action="Douche 2 minuten korter",
                        priority=7,
                        kwh_saved=round(kwh_elec, 3),
                    ))

        # ── Advies 6: Nacht-instelling (alleen 's avonds) ────────────────────
        if 19 <= hour_now <= 23 and gas_sys and gas_sys.kwh_needed > 0:
            remaining_night_m3 = (gas_sys.target_val or 0) * 0.05  # nacht ≈ 5% dagverbruik
            if remaining_night_m3 > 0.05:
                eur_saved = round(remaining_night_m3 * 0.5 * gas_price, 2)  # 50% besparing nacht
                if eur_saved >= 0.02:
                    advices.append(EnergyAdvice(
                        id="night_setback",
                        category="gas",
                        icon="🌙",
                        title="Nachtmodus inschakelen",
                        description=(
                            f"Thermostaat naar nachtinstelling (bijv. 15°C) bespaart "
                            f"ca. €{eur_saved:.2f} aan gaskosten deze nacht."
                        ),
                        saving_eur=eur_saved,
                        saving_unit="nacht",
                        action="Zet nachtmodus aan",
                        priority=3,
                        m3_saved=round(remaining_night_m3 * 0.5, 3),
                    ))

        return advices

    # ── Zwembad ───────────────────────────────────────────────────────────────
    def _calc_pool(self, data, config, price_now, price_cheap) -> Optional[SubsystemDemand]:
        try:
            pool = data.get("pool") or {}
            if not pool:
                return None

            # Circulatie
            filter_kw   = float(config.get("pool_filter_power_kw") or 0.3)
            filter_h    = float(pool.get("remaining_filter_h") or 0)
            filter_kwh  = filter_kw * filter_h

            # Verwarming
            cur_t       = pool.get("current_temp_c")
            tgt_t       = pool.get("target_temp_c")
            vol_m3      = float(config.get("pool_volume_m3") or 0)
            heat_kwh    = 0.0
            if cur_t and tgt_t and vol_m3 > 0:
                deficit   = max(0.0, tgt_t - cur_t)
                heat_kwh  = deficit * vol_m3 * C_POOL_KWH_PER_M3_PER_K

            total_kwh = filter_kwh + heat_kwh
            if total_kwh < 0.01:
                return None

            pool_kw    = filter_kw + float(config.get("pool_heater_kw") or 0)
            eta_min    = (total_kwh / max(pool_kw, 0.1)) * 60.0
            cost_now   = total_kwh * price_now
            cost_cheap = total_kwh * price_cheap

            return SubsystemDemand(
                name="pool", label="Zwembad",
                kwh_needed=total_kwh, kwh_per_hour=pool_kw,
                eta_minutes=eta_min,
                cost_now_eur=cost_now, cost_cheap_eur=cost_cheap,
                saving_eur=max(0, cost_now - cost_cheap),
                current_val=cur_t, target_val=tgt_t, unit="°C",
                active=True,
                reason=f"Filter {filter_kwh:.2f}kWh + verwarming {heat_kwh:.2f}kWh",
            )
        except Exception as e:
            _LOGGER.debug("EnergyDemand pool fout: %s", e)
        return None
