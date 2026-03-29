"""
CloudEMS Demo Engine — v1.0.0

Simuleert een volledige energie-installatie met virtuele sensoren.
Tijdversnelling instelbaar: 1x (realtime) t/m 96x (dag in 15 min).

Virtuele entiteiten (nooit echte sensoren):
  sensor.cloudems_demo_solar_power      — PV vermogen W
  sensor.cloudems_demo_grid_power       — Net netto W (+ = import)
  sensor.cloudems_demo_battery_power    — Batterij W (+ = laden)
  sensor.cloudems_demo_battery_soc      — Batterij SoC %
  sensor.cloudems_demo_boiler_temp      — Boiler watertemperatuur °C
  sensor.cloudems_demo_ev_power         — EV lader W
  sensor.cloudems_demo_ev_soc           — EV SoC %
  switch.cloudems_demo_boiler           — Virtuele boiler schakelaar
  switch.cloudems_demo_ev_charger       — Virtuele EV lader schakelaar

Garanties:
  - Raakt NOOIT echte sensor entity_ids aan
  - AI learning blijft gepauzeerd zolang demo actief is
  - Alle virtuele states verdwijnen bij demo_stop()
  - Geleerde data blijft intact
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

CONF_DEMO_ENABLED   = "demo_mode_enabled"
CONF_DEMO_SPEED     = "demo_speed"          # tijdversnelling (1/10/48/96)

DEMO_SPEED_OPTIONS  = [1, 10, 48, 96]       # 1x=realtime, 48x=dag in 30min, 96x=dag in 15min
DEMO_TICK_REAL_S    = 5.0                    # elke 5 echte seconden een simulatiestap

# Virtuele entity IDs — nooit aanpassen aan echte sensoren
DEMO_SOLAR_EID      = "sensor.cloudems_demo_solar_power"
DEMO_GRID_EID       = "sensor.cloudems_demo_grid_power"
DEMO_BAT_POWER_EID  = "sensor.cloudems_demo_battery_power"
DEMO_BAT_SOC_EID    = "sensor.cloudems_demo_battery_soc"
DEMO_BOILER_EID     = "sensor.cloudems_demo_boiler_temp"
DEMO_EV_POWER_EID   = "sensor.cloudems_demo_ev_power"
DEMO_EV_SOC_EID     = "sensor.cloudems_demo_ev_soc"
DEMO_BOILER_SW_EID  = "switch.cloudems_demo_boiler"

# Reverse NILM demo: na 2 minuten (bij 48x = ~1.5 demo-uur) verschijnt een
# 'vergeten' tweede omvormer van 1.5kW die CloudEMS automatisch detecteert
DEMO_GHOST_PV_DELAY_TICKS = 24    # 24 ticks * 5s = 2 minuten echt = ~1.5u demo
DEMO_GHOST_PV_W           = 1500  # vermogen van de vergeten omvormer
DEMO_EV_SW_EID      = "switch.cloudems_demo_ev_charger"

ALL_DEMO_EIDS = [
    DEMO_SOLAR_EID, DEMO_GRID_EID, DEMO_BAT_POWER_EID, DEMO_BAT_SOC_EID,
    DEMO_BOILER_EID, DEMO_EV_POWER_EID, DEMO_EV_SOC_EID,
    DEMO_BOILER_SW_EID, DEMO_EV_SW_EID,
]


@dataclass
class DemoState:
    """Interne simulatiestaat — niet persistent."""
    demo_hour:      float = 6.0     # start om 06:00
    bat_soc:        float = 20.0    # %
    boiler_temp:    float = 45.0    # °C
    ev_soc:         float = 30.0    # %
    boiler_on:      bool  = False
    ev_charging:    bool  = False
    house_base_w:   float = 800.0   # basisverbruik huis


class DemoEngine:
    """
    Demo-engine die een realistische energie-dag simuleert.

    Gebruik:
        engine = DemoEngine(hass, speed=48)
        await engine.async_start()
        ...
        await engine.async_stop()
    """

    def __init__(self, hass, speed: int = 48) -> None:
        self._hass   = hass
        self._speed  = max(1, min(96, speed))
        self._state  = DemoState()
        self._task:  Optional[asyncio.Task] = None
        self._running = False
        self._tick_count = 0   # voor ghost PV demo timing
        self._ghost_detector = None   # reverse NILM detector

    @property
    def running(self) -> bool:
        return self._running

    @property
    def demo_hour(self) -> float:
        return self._state.demo_hour

    @property
    def speed(self) -> int:
        return self._speed

    def set_speed(self, speed: int) -> None:
        self._speed = max(1, min(96, speed))

    async def async_start(self) -> None:
        """Start de demo simulatielus."""
        if self._running:
            return
        self._running = True
        self._state   = DemoState()
        await self._inject_all()
        self._task = self._hass.async_create_task(self._loop())
        from ..energy_manager.ghost_battery_detector import GhostBatteryDetector
        self._ghost_detector = GhostBatteryDetector()
        self._tick_count = 0
        _LOGGER.info("CloudEMS Demo: gestart op %dx tijdversnelling", self._speed)

    async def async_stop(self) -> None:
        """Stop de demo en verwijder alle virtuele states."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._remove_all()
        _LOGGER.info("CloudEMS Demo: gestopt, virtuele sensoren verwijderd")

    def get_sensor_config(self) -> dict:
        """
        Geeft een config-dict terug waarmee de coordinator demo-sensoren gebruikt.
        De coordinator mag dit gebruiken als tijdelijke overlay — echte config blijft intact.
        """
        return {
            "grid_sensor":             DEMO_GRID_EID,
            "solar_sensor":            DEMO_SOLAR_EID,
            "battery_sensor":          DEMO_BAT_POWER_EID,
            "battery_soc_entity":      DEMO_BAT_SOC_EID,
            "use_separate_import_export": False,
        }

    def get_status(self) -> dict:
        """Diagnostics voor de versie-kaart."""
        h = self._state.demo_hour
        ghost_alerts = []
        if self._ghost_detector:
            try:
                ghost_alerts = self._ghost_detector.get_alerts()
            except Exception:
                pass
        return {
            "running":    self._running,
            "speed":      self._speed,
            "ghost_alerts": ghost_alerts,
            "demo_hour":  round(h, 2),
            "demo_time":  f"{int(h):02d}:{int((h % 1) * 60):02d}",
            "bat_soc":    round(self._state.bat_soc, 1),
            "boiler_temp": round(self._state.boiler_temp, 1),
            "ev_soc":     round(self._state.ev_soc, 1),
        }

    # ── Simulatielus ──────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Hoofdlus: elke DEMO_TICK_REAL_S echte seconden een stap."""
        while self._running:
            try:
                await asyncio.sleep(DEMO_TICK_REAL_S)
                if not self._running:
                    break
                # Vooruit in demo-tijd
                demo_dt_h = (DEMO_TICK_REAL_S / 3600.0) * self._speed
                self._state.demo_hour = (self._state.demo_hour + demo_dt_h) % 24.0
                self._tick_count += 1
                self._step(demo_dt_h)
                await self._inject_all()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _LOGGER.debug("CloudEMS Demo: stap fout: %s", exc)

    def _step(self, dt_h: float) -> None:
        """Bereken nieuwe sensorwaarden op basis van de demo-tijd."""
        s = self._state
        h = s.demo_hour

        # ── PV curve (opkomt 07:00, piek 13:00, zakt 20:00) ──────────────────
        solar_w = self._pv_curve(h)

        # ── Huisverbruik (laag 's nachts, piek ochtend/avond) ─────────────────
        house_w = self._house_curve(h)

        # ── Boiler logica ─────────────────────────────────────────────────────
        # Koel langzaam af, warm op als aan
        if s.boiler_on:
            s.boiler_temp = min(65.0, s.boiler_temp + 8.0 * dt_h)
        else:
            s.boiler_temp = max(40.0, s.boiler_temp - 2.0 * dt_h)

        # CloudEMS beslissing: zet boiler aan bij PV-surplus overdag
        surplus = solar_w - house_w
        if surplus > 800 and s.boiler_temp < 58.0 and 8 <= h <= 17:
            s.boiler_on = True
        elif s.boiler_temp >= 60.0 or surplus < 200:
            s.boiler_on = False
        boiler_w = 1500.0 if s.boiler_on else 0.0

        # ── EV lader (laadt 's avonds 22:00–07:00) ────────────────────────────
        ev_w = 0.0
        if s.ev_soc < 90.0 and (h >= 22.0 or h < 7.0):
            s.ev_charging = True
        elif s.ev_soc >= 90.0:
            s.ev_charging = False
        if s.ev_charging:
            ev_w = 7400.0  # 7.4kW wallbox
            s.ev_soc = min(100.0, s.ev_soc + (ev_w / 52000.0) * dt_h * 60)

        # ── Batterij (laadt op PV-surplus, ontlaadt 's avonds) ───────────────
        total_load = house_w + boiler_w + ev_w
        net_solar  = solar_w - total_load

        bat_w = 0.0
        if net_solar > 200 and s.bat_soc < 95.0:
            # Laad batterij op surplus
            bat_w = min(5000.0, net_solar)
            s.bat_soc = min(100.0, s.bat_soc + (bat_w / 10000.0) * dt_h)
        elif net_solar < -300 and s.bat_soc > 10.0 and not (h >= 22 or h < 7):
            # Ontlaad batterij bij tekort (niet 's nachts)
            bat_w = max(-5000.0, net_solar)
            s.bat_soc = max(0.0, s.bat_soc + (bat_w / 10000.0) * dt_h)

        # ── Grid = wat overblijft (Kirchhoff) ─────────────────────────────────
        grid_w = total_load + bat_w - solar_w  # + = import, - = export

        # Sla op voor injectie
        # Reverse NILM demo: vergeten tweede omvormer wordt zichtbaar na DEMO_GHOST_PV_DELAY_TICKS
        # CloudEMS detecteert dit automatisch en toont waarschuwing
        ghost_pv_w = 0.0
        if self._tick_count >= DEMO_GHOST_PV_DELAY_TICKS and solar_w > 100:
            ghost_pv_w = max(0.0, DEMO_GHOST_PV_W * (solar_w / 5000.0))
        # Grid klopt Kirchhoff ook met ghost PV (echte export stijgt)
        grid_w -= ghost_pv_w   # meer export

        # Feed ghost detector
        if self._ghost_detector:
            try:
                self._ghost_detector.observe(
                    solar_w   = solar_w,
                    grid_w    = grid_w,
                    house_w   = house_w,
                    battery_w = bat_w,
                    dt_s      = DEMO_TICK_REAL_S * self._speed / 3600 * 3600,
                )
            except Exception:
                pass

        s._solar_w   = round(solar_w, 1)
        s._grid_w    = round(grid_w, 1)
        s._bat_w     = round(bat_w, 1)
        s._house_w   = round(house_w, 1)
        s._boiler_w  = round(boiler_w, 1)
        s._ev_w      = round(ev_w, 1)

    def _pv_curve(self, h: float) -> float:
        """Realistische PV-curve: bell-curve tussen 07:00 en 20:00, piek 13:00 bij 5kW."""
        if h < 7.0 or h > 20.0:
            return 0.0
        # Gaussian piek om 13:00
        peak_w = 5000.0
        sigma  = 3.0
        return max(0.0, peak_w * math.exp(-((h - 13.0) ** 2) / (2 * sigma ** 2)))

    def _house_curve(self, h: float) -> float:
        """Huisverbruik: laag 's nachts, ochtendpiek 07-09, avondpiek 18-22."""
        base = 400.0
        if 7 <= h < 9:
            return base + 1200.0 * math.sin(math.pi * (h - 7) / 2)
        elif 18 <= h < 22:
            return base + 1800.0 * math.sin(math.pi * (h - 18) / 4)
        elif 0 <= h < 6:
            return base * 0.5
        return base

    # ── State injection ───────────────────────────────────────────────────────

    async def _inject_all(self) -> None:
        s = self._state
        solar_w = getattr(s, '_solar_w', self._pv_curve(s.demo_hour))
        grid_w  = getattr(s, '_grid_w',  500.0)
        bat_w   = getattr(s, '_bat_w',   0.0)
        boiler_w = getattr(s, '_boiler_w', 0.0)
        ev_w    = getattr(s, '_ev_w',    0.0)

        self._set(DEMO_SOLAR_EID,    round(solar_w, 1),  "W",  "power")
        self._set(DEMO_GRID_EID,     round(grid_w,  1),  "W",  "power")
        self._set(DEMO_BAT_POWER_EID, round(bat_w,  1),  "W",  "power")
        self._set(DEMO_BAT_SOC_EID,  round(s.bat_soc, 1), "%", "battery")
        self._set(DEMO_BOILER_EID,   round(s.boiler_temp, 1), "°C", "temperature")
        self._set(DEMO_EV_POWER_EID, round(ev_w, 1),     "W",  "power")
        self._set(DEMO_EV_SOC_EID,   round(s.ev_soc, 1), "%",  "battery")
        self._set_switch(DEMO_BOILER_SW_EID, s.boiler_on,   "Demo Boiler")
        self._set_switch(DEMO_EV_SW_EID,     getattr(s, 'ev_charging', False), "Demo EV Lader")

    def _set(self, eid: str, value: float, unit: str, device_class: str) -> None:
        self._hass.states.async_set(eid, str(value), {
            "unit_of_measurement": unit,
            "device_class":        device_class,
            "friendly_name":       eid.replace("sensor.cloudems_demo_", "Demo ").replace("_", " ").title(),
            "_cloudems_demo":      True,
        })

    def _set_switch(self, eid: str, on: bool, name: str) -> None:
        self._hass.states.async_set(eid, "on" if on else "off", {
            "friendly_name":  name,
            "_cloudems_demo": True,
        })

    async def _remove_all(self) -> None:
        for eid in ALL_DEMO_EIDS:
            try:
                self._hass.states.async_remove(eid)
            except Exception:
                pass
        _LOGGER.debug("CloudEMS Demo: alle virtuele states verwijderd")
