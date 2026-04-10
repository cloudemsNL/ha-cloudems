# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Battery Degradation Tracker — v1.10.0

Tracks battery health (State of Health — SoH) by monitoring:
  1. Full charge cycles (0→100% equivalent)
  2. Partial cycles accumulated as equivalent full cycles
  3. SoC range stress (deep discharges / high overcharge)
  4. Temperature stress (if sensor available — optional)

SoH estimation model (simplified calendar + cycle ageing):
  - Each full equivalent cycle degrades the battery by ~0.003–0.005% capacity
    (varies by chemistry: LFP slower, NMC faster)
  - Deep discharges below 10% add extra stress
  - Charging above 95% continuously adds calendar stress
  - SoH alert thresholds: <90% warn, <80% critical

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_battery_degr_v1"
STORAGE_VERSION = 1

# Chemistry-specific cycle degradation factors (% SoH lost per full cycle)
CHEMISTRY_FACTORS = {
    "LFP":  0.0025,   # Lithium Iron Phosphate — very cycle-stable
    "NMC":  0.0045,   # Nickel Manganese Cobalt — standard home batteries
    "NCA":  0.0050,   # Nickel Cobalt Aluminium — Tesla-style
    "LTO":  0.0010,   # Lithium Titanate — extremely durable
}
DEFAULT_CHEMISTRY = "NMC"

SOH_WARN_PCT     = 90.0
SOH_CRITICAL_PCT = 80.0


@dataclass
class DegradationState:
    total_full_cycles:     float = 0.0   # equivalent full cycles since tracking started
    soh_pct:               float = 100.0
    last_soc:              Optional[float] = None
    soc_low_events:        int   = 0     # times SoC < 10%
    soc_high_events:       int   = 0     # times SoC > 95% for extended period
    tracking_start_ts:     float = field(default_factory=time.time)
    last_update_ts:        float = field(default_factory=time.time)
    chemistry:             str   = DEFAULT_CHEMISTRY
    capacity_kwh_nominal:  float = 10.0
    capacity_kwh_current:  float = 10.0  # estimated remaining usable capacity

    # ── Gemeten capaciteitsgeschiedenis (maandelijkse snapshots) ───────────────
    # Elke entry: {"ts": unix_ts, "date": "YYYY-MM", "kwh": float, "soh_pct": float}
    # Max 120 maanden (10 jaar)
    capacity_history:      list  = field(default_factory=list)
    last_snapshot_month:   str   = ""   # "YYYY-MM" van laatste snapshot
    # Laatste gemeten capaciteit van BatterySocLearner span-EMA
    measured_kwh:          Optional[float] = None
    measured_kwh_ts:       float = 0.0

    # v5.5.333: DoD-histogram — telt cycli per diepte-categorie
    # Buckets: 0-20%, 20-40%, 40-60%, 60-80%, 80-100% (DoD = depth of discharge)
    dod_histogram:         dict  = field(default_factory=lambda: {
        "0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0
    })
    _cycle_soc_high:       Optional[float] = None   # SOC bij start van ontlaadcyclus


@dataclass
class DegradationResult:
    soh_pct:            float    # 0-100 estimated state of health
    capacity_kwh:       float    # estimated usable kWh remaining
    total_cycles:       float    # equivalent full cycles
    cycles_per_day:     float
    alert_level:        str      # "ok" | "warn" | "critical"
    alert_message:      str
    soc_low_events:     int
    soc_high_events:    int
    days_tracked:       int


class BatteryDegradationTracker:
    """
    Tracks battery health over time.

    Usage in coordinator:
        bdt = BatteryDegradationTracker(hass, config)
        await bdt.async_setup()
        result = bdt.update(current_soc_pct)
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass      = hass
        self._chemistry = config.get("battery_chemistry", DEFAULT_CHEMISTRY).upper()
        if self._chemistry not in CHEMISTRY_FACTORS:
            self._chemistry = DEFAULT_CHEMISTRY
        self._nominal_kwh = float(config.get("battery_capacity_kwh", 10.0))
        self._soc_eid     = config.get("battery_soc_entity", "")
        self._store       = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._state       = DegradationState(
            chemistry            = self._chemistry,
            capacity_kwh_nominal = self._nominal_kwh,
            capacity_kwh_current = self._nominal_kwh,
        )
        self._dirty = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if data:
            s = self._state
            s.total_full_cycles    = float(data.get("total_full_cycles", 0.0))
            s.soh_pct              = float(data.get("soh_pct", 100.0))
            s.last_soc             = data.get("last_soc")
            s.soc_low_events       = int(data.get("soc_low_events", 0))
            s.soc_high_events      = int(data.get("soc_high_events", 0))
            s.tracking_start_ts    = float(data.get("tracking_start_ts", time.time()))
            s.chemistry            = data.get("chemistry", self._chemistry)
            s.capacity_kwh_nominal = float(data.get("capacity_kwh_nominal", self._nominal_kwh))
            s.capacity_kwh_current = float(data.get("capacity_kwh_current", self._nominal_kwh))
            s.capacity_history     = list(data.get("capacity_history", []))
            s.last_snapshot_month  = str(data.get("last_snapshot_month", ""))
            s.measured_kwh         = data.get("measured_kwh")
            # v5.5.356: laad dod_histogram — ontbrak in async_setup → reset bij elke herstart
            _saved_dod = data.get("dod_histogram")
            if isinstance(_saved_dod, dict) and _saved_dod:
                s.dod_histogram = _saved_dod
        _LOGGER.debug(
            "BatteryDegradationTracker ready — SoH=%.1f%% cycles=%.1f chemistry=%s",
            self._state.soh_pct, self._state.total_full_cycles, self._state.chemistry,
        )

    async def async_save(self) -> None:
        if not self._dirty:
            return
        s = self._state
        await self._store.async_save({
            "total_full_cycles":    round(s.total_full_cycles, 3),
            "soh_pct":              round(s.soh_pct, 3),
            "last_soc":             s.last_soc,
            "soc_low_events":       s.soc_low_events,
            "soc_high_events":      s.soc_high_events,
            "tracking_start_ts":    s.tracking_start_ts,
            "chemistry":            s.chemistry,
            "capacity_kwh_nominal": s.capacity_kwh_nominal,
            "capacity_kwh_current": s.capacity_kwh_current,
            "capacity_history":     s.capacity_history[-120:],
            "last_snapshot_month":  s.last_snapshot_month,
            "measured_kwh":         s.measured_kwh,
            "dod_histogram":        getattr(s, "dod_histogram", {}),
        })
        self._dirty = False

    # ── Update (called every coordinator cycle) ───────────────────────────────

    def update(self, soc_pct: Optional[float]) -> DegradationResult:
        """Update tracker with current SoC reading. Returns current degradation status."""
        s = self._state
        now = time.time()

        if soc_pct is not None and s.last_soc is not None:
            delta = soc_pct - s.last_soc

            # Accumulate equivalent cycles: sum of all positive deltas / 100
            if delta > 0:
                frac_cycle = delta / 100.0
                s.total_full_cycles += frac_cycle

                # Apply degradation
                factor   = CHEMISTRY_FACTORS.get(s.chemistry, CHEMISTRY_FACTORS[DEFAULT_CHEMISTRY])
                degraded = frac_cycle * factor
                s.soh_pct = max(0.0, s.soh_pct - degraded)
                s.capacity_kwh_current = round(s.capacity_kwh_nominal * (s.soh_pct / 100.0), 2)
                self._dirty = True

                # v5.5.365 #37: snellere leercurve via partial cycle coulomb counting
                # Accumuleer energie per richting; na voldoende data → capaciteitsschatting
                _energy_kwh = frac_cycle * s.capacity_kwh_nominal
                if not hasattr(s, 'partial_kwh_charged'):
                    s.__dict__.setdefault('partial_kwh_charged', 0.0)
                    s.__dict__.setdefault('partial_soc_start', soc_pct or 0.0)
                s.__dict__['partial_kwh_charged'] = s.__dict__.get('partial_kwh_charged', 0.0) + _energy_kwh
                _partial_delta_soc = abs((soc_pct or 0) - s.__dict__.get('partial_soc_start', soc_pct or 0))
                # Als we ≥20% SoC-range hebben gemeten → schat capaciteit
                if _partial_delta_soc >= 20 and s.__dict__.get('partial_kwh_charged', 0) > 0.5:
                    _implied_cap = s.__dict__['partial_kwh_charged'] / (_partial_delta_soc / 100.0)
                    if 3.0 < _implied_cap < 25.0:  # plausibel bereik
                        # EMA update op nominale capaciteit (conservatief: 10% gewicht)
                        s.capacity_kwh_nominal = round(
                            s.capacity_kwh_nominal * 0.90 + _implied_cap * 0.10, 2)
                        s.capacity_kwh_current = round(
                            s.capacity_kwh_nominal * (s.soh_pct / 100.0), 2)
                    # Reset partial cycle tracker
                    s.__dict__['partial_kwh_charged'] = 0.0
                    s.__dict__['partial_soc_start'] = soc_pct or 0.0

            # v5.5.333: DoD histogram — track ontlaaddiepte per cyclus
            if delta < 0:  # ontladen
                if s._cycle_soc_high is None:
                    s._cycle_soc_high = s.last_soc or soc_pct
            elif delta > 0 and s._cycle_soc_high is not None:
                # Cyclus voltooid: van _cycle_soc_high naar het laagste punt (soc_pct voor stijging)
                dod = max(0.0, s._cycle_soc_high - s.last_soc) if s.last_soc else 0.0
                bucket = ("0-20" if dod < 20 else "20-40" if dod < 40
                          else "40-60" if dod < 60 else "60-80" if dod < 80 else "80-100")
                if not hasattr(s, 'dod_histogram') or not isinstance(s.dod_histogram, dict):
                    s.dod_histogram = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
                s.dod_histogram[bucket] = s.dod_histogram.get(bucket, 0) + 1
                s._cycle_soc_high = None
                self._dirty = True

            # Stress events
            if soc_pct < 10.0 and (s.last_soc is None or s.last_soc >= 10.0):
                s.soc_low_events += 1
                # Extra stress for deep discharge
                s.soh_pct = max(0.0, s.soh_pct - 0.01)
                _LOGGER.debug("Battery deep discharge event (SoC %.1f%%)", soc_pct)
                self._dirty = True

            if soc_pct > 95.0 and (s.last_soc is None or s.last_soc <= 95.0):
                s.soc_high_events += 1
                self._dirty = True

        if soc_pct is not None:
            s.last_soc    = soc_pct
            s.last_update_ts = now

        # Build result
        days_tracked   = max(1, int((now - s.tracking_start_ts) / 86400))
        cycles_per_day = round(s.total_full_cycles / days_tracked, 3)

        if s.soh_pct < SOH_CRITICAL_PCT:
            alert_level   = "critical"
            alert_message = (
                f"Battery SoH {s.soh_pct:.1f}% — capacity severely reduced. "
                "Consider replacing or reconditioning."
            )
        elif s.soh_pct < SOH_WARN_PCT:
            alert_level   = "warn"
            alert_message = (
                f"Battery SoH {s.soh_pct:.1f}% — capacity degrading. "
                f"~{s.capacity_kwh_current:.1f} kWh usable of {s.capacity_kwh_nominal:.1f} kWh nominal."
            )
        else:
            alert_level   = "ok"
            alert_message = (
                f"Battery in good health ({s.soh_pct:.1f}%). "
                f"{s.total_full_cycles:.0f} equivalent full cycles."
            )

        return DegradationResult(
            soh_pct          = round(s.soh_pct, 2),
            dod_histogram    = getattr(s, 'dod_histogram', {}),
            capacity_kwh     = s.capacity_kwh_current,
            total_cycles     = round(s.total_full_cycles, 1),
            cycles_per_day   = cycles_per_day,
            alert_level      = alert_level,
            alert_message    = alert_message,
            soc_low_events   = s.soc_low_events,
            soc_high_events  = s.soc_high_events,
            days_tracked     = days_tracked,
        )

    # ── Gemeten capaciteit koppelen ───────────────────────────────────────────

    def record_measured_capacity(self, measured_kwh: float) -> None:
        """
        Koppel de gemeten capaciteit van BatterySocLearner span-EMA.
        Wordt aangeroepen vanuit de coordinator als span_cap_ema update.
        Maakt maandelijkse snapshot en herberekent SoH op basis van meting.
        """
        s = self._state
        now = time.time()
        month = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m")

        # Update huidige meting
        s.measured_kwh    = round(measured_kwh, 3)
        s.measured_kwh_ts = now

        # SoH herberekenen op basis van gemeten capaciteit
        if s.capacity_kwh_nominal > 0:
            measured_soh = (measured_kwh / s.capacity_kwh_nominal) * 100.0
            # EMA met bestaande SoH — meting heeft hoog gewicht (0.3)
            # want span-EMA is direct gemeten, niet geschat
            if abs(measured_soh - s.soh_pct) > 0.5:
                s.soh_pct = round(0.7 * s.soh_pct + 0.3 * measured_soh, 3)
                s.capacity_kwh_current = round(s.capacity_kwh_nominal * s.soh_pct / 100.0, 2)
                _LOGGER.info(
                    "BatteryDegradation: gemeten cap=%.2f kWh → SoH=%.1f%%",
                    measured_kwh, s.soh_pct,
                )

        # Maandelijkse snapshot
        if month != s.last_snapshot_month:
            s.capacity_history.append({
                "ts":      round(now, 0),
                "date":    month,
                "kwh":     round(measured_kwh, 3),
                "soh_pct": round(s.soh_pct, 2),
            })
            if len(s.capacity_history) > 120:
                s.capacity_history = s.capacity_history[-120:]
            s.last_snapshot_month = month
            _LOGGER.info(
                "BatteryDegradation: maandelijkse snapshot %s — %.2f kWh (SoH %.1f%%)",
                month, measured_kwh, s.soh_pct,
            )
        self._dirty = True

    def get_forecast(self) -> dict:
        """
        Berekent degradatieprognose op basis van historische capaciteitsmetingen.

        Returns dict met:
          degradation_kwh_per_year   — capaciteitsverlies per jaar
          degradation_pct_per_year   — SoH verlies per jaar
          years_to_eol               — jaren tot end-of-life (< eol_threshold)
          years_to_80pct             — jaren tot 80% SoH (fabrikant-grens)
          eol_kwh                    — capaciteit bij end-of-life
          projected_soh_5y           — verwachte SoH over 5 jaar
          projected_soh_10y          — verwachte SoH over 10 jaar
          history_months             — aantal maanden data
          confidence                 — 0-1 betrouwbaarheid
          history                    — capaciteitsgeschiedenis
        """
        s = self._state
        EOL_SOH_PCT = 70.0   # fabrikant-grens "versleten"
        now = time.time()

        # Minimaal 2 snapshots nodig voor trend
        hist = s.capacity_history
        if len(hist) < 2:
            # Terugvallen op cyclus-gebaseerde schatting
            days = max(1, (now - s.tracking_start_ts) / 86400)
            years = days / 365.25
            if years > 0.1 and s.soh_pct < 100.0:
                deg_pct_yr = (100.0 - s.soh_pct) / years
            else:
                # Schat op basis van chemie en cycli/dag
                cpd = s.total_full_cycles / max(1, days)
                factor = CHEMISTRY_FACTORS.get(s.chemistry, 0.004)
                deg_pct_yr = cpd * 365 * factor * 100
            confidence = 0.2
        else:
            # Lineaire regressie op kapaciteitsgeschiedenis
            # x = maanden geleden, y = kWh
            times  = [e["ts"] for e in hist]
            caps   = [e["kwh"] for e in hist]
            n = len(times)
            t0 = times[0]
            xs = [(t - t0) / (365.25 * 24 * 3600) for t in times]  # in jaren

            # Kleinste kwadraten regressie
            mx = sum(xs) / n
            my = sum(caps) / n
            num = sum((x - mx) * (c - my) for x, c in zip(xs, caps))
            den = sum((x - mx)**2 for x in xs)
            if den > 0.001:
                slope = num / den   # kWh per jaar (negatief = degradatie)
            else:
                slope = 0.0

            deg_kwh_yr   = -slope   # positief getal = verlies per jaar
            deg_pct_yr   = deg_kwh_yr / s.capacity_kwh_nominal * 100.0 if s.capacity_kwh_nominal > 0 else 0
            # Meer data = hogere confidence
            confidence   = min(0.95, 0.3 + len(hist) * 0.05)

        # Huidige capaciteit
        cur_kwh  = s.measured_kwh or s.capacity_kwh_current
        cur_soh  = s.soh_pct
        nom_kwh  = s.capacity_kwh_nominal

        # Prognose
        deg_kwh_yr = cur_soh / 100.0 * nom_kwh * (deg_pct_yr / 100.0) if 'deg_kwh_yr' not in dir() else deg_kwh_yr

        eol_kwh    = nom_kwh * EOL_SOH_PCT / 100.0
        kwh_to_eol = max(0.0, cur_kwh - eol_kwh)
        yr_to_eol  = round(kwh_to_eol / deg_kwh_yr, 1) if deg_kwh_yr > 0.001 else 99.0
        yr_to_80   = round(max(0.0, (cur_soh - 80.0) / max(deg_pct_yr, 0.001)), 1)

        soh_5y  = round(max(0.0, cur_soh - deg_pct_yr * 5), 1)
        soh_10y = round(max(0.0, cur_soh - deg_pct_yr * 10), 1)
        kwh_5y  = round(nom_kwh * soh_5y / 100.0, 2)
        kwh_10y = round(nom_kwh * soh_10y / 100.0, 2)

        # Levensduur bericht
        if yr_to_eol >= 20:
            life_msg = f"Uitstekend — accu gaat nog zeker 20+ jaar mee"
        elif yr_to_eol >= 10:
            life_msg = f"Goed — verwachte resterende levensduur ~{yr_to_eol:.0f} jaar"
        elif yr_to_eol >= 5:
            life_msg = f"Normaal — accu verliest {deg_kwh_yr:.2f} kWh/jaar, ~{yr_to_eol:.0f} jaar tot fabrieksgrens"
        else:
            life_msg = f"Let op — accu nadert het einde bij ~{yr_to_eol:.1f} jaar"

        return {
            "degradation_kwh_per_year":  round(deg_kwh_yr, 3),
            "degradation_pct_per_year":  round(deg_pct_yr, 2),
            "years_to_eol":              yr_to_eol,
            "years_to_80pct":            yr_to_80,
            "eol_threshold_pct":         EOL_SOH_PCT,
            "eol_kwh":                   round(eol_kwh, 2),
            "projected_soh_5y":          soh_5y,
            "projected_soh_10y":         soh_10y,
            "projected_kwh_5y":          kwh_5y,
            "projected_kwh_10y":         kwh_10y,
            "current_kwh":               round(cur_kwh, 2),
            "current_soh_pct":           round(cur_soh, 1),
            "nominal_kwh":               nom_kwh,
            "history_months":            len(hist),
            "confidence":                round(confidence, 2),
            "life_message":              life_msg,
            "history":                   hist[-24:],  # laatste 2 jaar
        }

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def soh_pct(self) -> float:
        return round(self._state.soh_pct, 2)

    @property
    def total_cycles(self) -> float:
        return round(self._state.total_full_cycles, 1)
