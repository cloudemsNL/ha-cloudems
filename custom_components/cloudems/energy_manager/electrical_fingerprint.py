# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.

"""CloudEMS — Elektrische Vingerafdruk v1.0.0

Analyseert de inschakel-curve van compressor-apparaten (koelkast, warmtepomp,
vriezer, airco) om slijtage vroeg te detecteren.

WERKING
═══════
Bij elke inschakelmoment wordt de "aanloopstroom-curve" opgeslagen:
  - Piek-vermogen in eerste 5s (inrush current)
  - Tijd tot stabiel vermogen (run-up time)
  - Stabiel loopvermogen

Na N cycli wordt een baseline gebouwd. Afwijkingen > drempel → waarschuwing.

DETECTEERBARE PROBLEMEN
═══════════════════════
  Piek hoger + run-up langer  → motorwikkeling degradatie / capacitor slijt
  Piek normaal + stabiel hoger → koelmiddelverlies / vuil verdamper
  Piek lager + sneller stabiel → kortsluiting wikkeling (gevaarlijk)
  Run-up veel langer            → lager/as probleem

APPARATEN
═════════
  refrigerator, freezer, heat_pump, airco, fridge_freezer, compressor

INTEGRATIE
══════════
  - Werkt via NILM device_id of directe power_sensor
  - Elke 10s tick: detecteer inschakelmoment en volg curve
  - Sla curves op in HA Store
  - Stuur notificatie via coordinator._notify_maintenance()
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_electrical_fingerprint_v1"
STORAGE_VERSION = 1

# Compressor device types die we monitoren
COMPRESSOR_TYPES = {
    "refrigerator", "freezer", "fridge_freezer", "fridge",
    "heat_pump", "airco", "air_conditioner", "compressor",
}

# Analyse parameters
MIN_CYCLES_FOR_BASELINE = 10    # minimaal cycli voor baseline
INRUSH_WINDOW_S         = 5.0   # eerste N seconden = inrush window
STABLE_WINDOW_S         = 30.0  # daarna stabiel vermogen meten
IDLE_THRESHOLD_W        = 15.0  # onder dit = apparaat uit
STARTUP_THRESHOLD_W     = 50.0  # boven dit = opstart gedetecteerd
DEVIATION_WARNING_PCT   = 25.0  # % afwijking voor waarschuwing
DEVIATION_CRITICAL_PCT  = 40.0  # % afwijking voor kritieke waarschuwing
LEARN_ALPHA             = 0.1   # EMA factor voor baseline update


@dataclass
class StartupCurve:
    """Eén inschakel-event."""
    ts:            float
    inrush_w:      float   # piek vermogen in eerste 5s
    runup_s:       float   # seconden tot stabiel vermogen
    stable_w:      float   # stabiel loopvermogen
    temp_c:        Optional[float] = None  # omgevingstemperatuur indien beschikbaar


@dataclass
class ApplianceFingerprint:
    """Geleerde vingerafdruk van één apparaat."""
    device_id:     str
    label:         str
    device_type:   str

    # Baseline (EMA over laatste MIN_CYCLES cycli)
    baseline_inrush_w:   float = 0.0
    baseline_runup_s:    float = 0.0
    baseline_stable_w:   float = 0.0
    baseline_samples:    int   = 0

    # Recente curves (max 50 bewaard)
    curves: list = field(default_factory=list)

    # Waarschuwingsstatus
    last_warning_ts:   float = 0.0
    warning_count:     int   = 0
    last_deviation_pct: float = 0.0
    last_deviation_type: str = ""

    def add_curve(self, curve: StartupCurve) -> None:
        self.curves.append({
            "ts":       curve.ts,
            "inrush_w": round(curve.inrush_w, 1),
            "runup_s":  round(curve.runup_s, 2),
            "stable_w": round(curve.stable_w, 1),
            "temp_c":   curve.temp_c,
        })
        if len(self.curves) > 50:
            self.curves = self.curves[-50:]

        # Update baseline via EMA
        if self.baseline_samples < MIN_CYCLES_FOR_BASELINE:
            # Bootstrap: gewogen gemiddelde
            n = self.baseline_samples + 1
            self.baseline_inrush_w = (self.baseline_inrush_w * (n-1) + curve.inrush_w) / n
            self.baseline_runup_s  = (self.baseline_runup_s  * (n-1) + curve.runup_s)  / n
            self.baseline_stable_w = (self.baseline_stable_w * (n-1) + curve.stable_w) / n
        else:
            self.baseline_inrush_w = self.baseline_inrush_w * (1-LEARN_ALPHA) + curve.inrush_w * LEARN_ALPHA
            self.baseline_runup_s  = self.baseline_runup_s  * (1-LEARN_ALPHA) + curve.runup_s  * LEARN_ALPHA
            self.baseline_stable_w = self.baseline_stable_w * (1-LEARN_ALPHA) + curve.stable_w * LEARN_ALPHA
        self.baseline_samples += 1

    def analyse_deviation(self, curve: StartupCurve) -> Optional[dict]:
        """Analyseer afwijking t.o.v. baseline. Returns None als OK."""
        if self.baseline_samples < MIN_CYCLES_FOR_BASELINE:
            return None
        if self.baseline_inrush_w < 10:
            return None

        inrush_dev = (curve.inrush_w - self.baseline_inrush_w) / self.baseline_inrush_w * 100
        runup_dev  = (curve.runup_s  - self.baseline_runup_s)  / max(self.baseline_runup_s, 0.1) * 100
        stable_dev = (curve.stable_w - self.baseline_stable_w) / max(self.baseline_stable_w, 10) * 100

        # Bepaal maximale afwijking
        max_dev = max(abs(inrush_dev), abs(runup_dev), abs(stable_dev))
        if max_dev < DEVIATION_WARNING_PCT:
            return None

        # Bepaal type probleem
        severity = "critical" if max_dev >= DEVIATION_CRITICAL_PCT else "warning"
        problem_type, advice = self._diagnose(inrush_dev, runup_dev, stable_dev)

        return {
            "severity":      severity,
            "problem_type":  problem_type,
            "advice":        advice,
            "max_dev_pct":   round(max_dev, 1),
            "inrush_dev_pct": round(inrush_dev, 1),
            "runup_dev_pct":  round(runup_dev, 1),
            "stable_dev_pct": round(stable_dev, 1),
            "current":  {"inrush_w": round(curve.inrush_w, 1), "runup_s": round(curve.runup_s, 2), "stable_w": round(curve.stable_w, 1)},
            "baseline": {"inrush_w": round(self.baseline_inrush_w, 1), "runup_s": round(self.baseline_runup_s, 2), "stable_w": round(self.baseline_stable_w, 1)},
        }

    def _diagnose(self, inrush_dev: float, runup_dev: float, stable_dev: float):
        """Vertaal afwijkingspatroon naar diagnose + advies."""
        if inrush_dev > 20 and runup_dev > 20:
            return (
                "motor_degradatie",
                "Aanloopstroom én starttijd zijn hoger dan normaal. "
                "Mogelijke oorzaak: slijtage aan condensator of motorwikkeling. "
                "Controleer of het apparaat schoon is (stofvrij aan achterkant/onderkant)."
            )
        if inrush_dev < -20 and runup_dev < -20:
            return (
                "wikkeling_kortsluiting",
                "Aanloopstroom lager dan normaal terwijl het apparaat sneller opstart. "
                "Dit kan wijzen op een kortgesloten motorwikkeling. "
                "Laat het apparaat controleren door een monteur — dit kan gevaarlijk zijn."
            )
        if stable_dev > 20 and abs(inrush_dev) < 15:
            return (
                "koelmiddel_of_vervuiling",
                "Het loopvermogen is hoger dan normaal maar de opstart is normaal. "
                "Mogelijke oorzaak: koelmiddelverlies of vuile verdamper/condensor. "
                "Reinig de roosters en controleer op ijsvorming."
            )
        if runup_dev > 30:
            return (
                "mechanische_weerstand",
                "Het apparaat doet er langer over om op toeren te komen. "
                "Mogelijke oorzaak: lager- of asprobleem, of te weinig smeermiddel. "
                "Laat de mechanische delen controleren."
            )
        return (
            "afwijking_onbekend",
            f"Meetafwijking van {max(abs(inrush_dev), abs(stable_dev), abs(runup_dev)):.0f}% t.o.v. normaal. "
            "Volg de volgende cycli voor meer zekerheid."
        )

    def to_dict(self) -> dict:
        return {
            "device_id":          self.device_id,
            "label":              self.label,
            "device_type":        self.device_type,
            "baseline_inrush_w":  round(self.baseline_inrush_w, 1),
            "baseline_runup_s":   round(self.baseline_runup_s, 2),
            "baseline_stable_w":  round(self.baseline_stable_w, 1),
            "baseline_samples":   self.baseline_samples,
            "curves":             self.curves[-10:],  # laatste 10 voor dashboard
            "last_warning_ts":    self.last_warning_ts,
            "warning_count":      self.warning_count,
            "last_deviation_pct": round(self.last_deviation_pct, 1),
            "last_deviation_type": self.last_deviation_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ApplianceFingerprint":
        fp = cls(
            device_id   = d.get("device_id", ""),
            label       = d.get("label", ""),
            device_type = d.get("device_type", ""),
        )
        fp.baseline_inrush_w  = float(d.get("baseline_inrush_w", 0))
        fp.baseline_runup_s   = float(d.get("baseline_runup_s", 0))
        fp.baseline_stable_w  = float(d.get("baseline_stable_w", 0))
        fp.baseline_samples   = int(d.get("baseline_samples", 0))
        fp.curves             = d.get("curves", [])
        fp.last_warning_ts    = float(d.get("last_warning_ts", 0))
        fp.warning_count      = int(d.get("warning_count", 0))
        fp.last_deviation_pct = float(d.get("last_deviation_pct", 0))
        fp.last_deviation_type = d.get("last_deviation_type", "")
        return fp


class ActiveStartup:
    """Volgt een actief opstart-event voor één apparaat."""
    def __init__(self, ts: float, power_w: float) -> None:
        self.start_ts    = ts
        self.inrush_w    = power_w
        self.samples:    list[tuple[float, float]] = [(ts, power_w)]
        self.stable_w    = 0.0
        self.runup_s     = 0.0
        self.complete    = False

    def update(self, ts: float, power_w: float) -> bool:
        """Update met nieuw sample. Returns True als curve compleet is."""
        self.samples.append((ts, power_w))
        elapsed = ts - self.start_ts

        # Inrush window: bijhouden piek
        if elapsed <= INRUSH_WINDOW_S:
            self.inrush_w = max(self.inrush_w, power_w)

        # Na inrush window: stabiel vermogen bepalen
        elif elapsed > INRUSH_WINDOW_S and elapsed <= INRUSH_WINDOW_S + STABLE_WINDOW_S:
            if self.runup_s == 0 and power_w < self.inrush_w * 0.75:
                self.runup_s = elapsed  # punt waarop vermogen daalt na inrush
            # Stabiel vermogen = gemiddelde in stable window
            stable_samples = [(t, p) for t, p in self.samples
                              if t > self.start_ts + INRUSH_WINDOW_S]
            if stable_samples:
                self.stable_w = sum(p for _, p in stable_samples) / len(stable_samples)

        # Curve compleet na INRUSH + STABLE window
        if elapsed >= INRUSH_WINDOW_S + STABLE_WINDOW_S:
            if self.runup_s == 0:
                self.runup_s = INRUSH_WINDOW_S  # geen duidelijke piek
            self.complete = True
            return True

        return False


class ElectricalFingerprintMonitor:
    """Monitort inschakel-curves voor alle compressor-apparaten via NILM."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self._hass       = hass
        self._store      = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._prints:    dict[str, ApplianceFingerprint] = {}
        self._active:    dict[str, ActiveStartup]        = {}
        self._prev_pw:   dict[str, float]                = {}
        self._notify_cb  = None  # callback: fn(title, message, severity)

    def set_notify_callback(self, cb) -> None:
        self._notify_cb = cb

    async def async_setup(self) -> None:
        saved = await self._store.async_load() or {}
        for device_id, d in saved.items():
            self._prints[device_id] = ApplianceFingerprint.from_dict(d)
        _LOGGER.info(
            "ElectricalFingerprint: %d apparaten geladen", len(self._prints)
        )

    async def async_save(self) -> None:
        await self._store.async_save({
            did: fp.to_dict() for did, fp in self._prints.items()
        })

    def tick(self, nilm_devices: list[dict], outside_temp_c: Optional[float] = None) -> list[dict]:
        """Aanroepen elke coordinator tick met NILM device lijst.

        Returns: lijst van warnings gegenereerd deze tick.
        """
        now     = time.time()
        warnings = []

        for dev in nilm_devices:
            dtype = dev.get("device_type", "")
            if dtype not in COMPRESSOR_TYPES:
                continue

            did     = dev.get("device_id") or dev.get("id") or dev.get("label", "")
            if not did:
                continue

            label   = dev.get("label") or dev.get("name") or did
            power_w = float(dev.get("power_w", dev.get("current_power", 0)) or 0)
            prev_w  = self._prev_pw.get(did, 0.0)
            self._prev_pw[did] = power_w

            # Zorg dat fingerprint bestaat
            if did not in self._prints:
                self._prints[did] = ApplianceFingerprint(
                    device_id=did, label=label, device_type=dtype
                )

            fp = self._prints[did]

            # Inschakeldetectie: van idle naar actief
            if prev_w < STARTUP_THRESHOLD_W and power_w >= STARTUP_THRESHOLD_W:
                if did not in self._active:
                    self._active[did] = ActiveStartup(now, power_w)
                    _LOGGER.debug("ElectricalFingerprint: %s inschakelmoment gedetecteerd (%.0fW)", label, power_w)

            # Volg actieve opstart
            if did in self._active:
                startup = self._active[did]

                if power_w < IDLE_THRESHOLD_W:
                    # Apparaat ging alweer uit — incomplete curve, gooi weg
                    del self._active[did]
                    continue

                complete = startup.update(now, power_w)
                if complete:
                    curve = StartupCurve(
                        ts       = startup.start_ts,
                        inrush_w = startup.inrush_w,
                        runup_s  = startup.runup_s,
                        stable_w = startup.stable_w,
                        temp_c   = outside_temp_c,
                    )

                    # Analyseer afwijking vóór baseline update
                    deviation = fp.analyse_deviation(curve)

                    # Voeg toe aan baseline
                    fp.add_curve(curve)
                    del self._active[did]

                    _LOGGER.debug(
                        "ElectricalFingerprint: %s curve opgeslagen — "
                        "inrush=%.0fW, runup=%.1fs, stable=%.0fW (n=%d)",
                        label, curve.inrush_w, curve.runup_s, curve.stable_w, fp.baseline_samples
                    )

                    # Waarschuwing indien afwijking
                    if deviation:
                        # Cooldown: max 1 waarschuwing per 24u per apparaat
                        if now - fp.last_warning_ts > 86400:
                            fp.last_warning_ts    = now
                            fp.warning_count     += 1
                            fp.last_deviation_pct = deviation["max_dev_pct"]
                            fp.last_deviation_type = deviation["problem_type"]

                            warning = {
                                "device_id":    did,
                                "label":        label,
                                "device_type":  dtype,
                                **deviation,
                            }
                            warnings.append(warning)

                            if self._notify_cb:
                                icon = "⚠️" if deviation["severity"] == "warning" else "🚨"
                                try:
                                    self._notify_cb(
                                        title=f"{icon} {label} — mogelijke slijtage",
                                        message=(
                                            f"CloudEMS detecteerde een afwijking in het inschakelpatroon "
                                            f"van {label}.\n\n"
                                            f"📊 Afwijking: {deviation['max_dev_pct']:.0f}%\n"
                                            f"🔍 Diagnose: {deviation['advice']}\n\n"
                                            f"Gemeten: {deviation['current']['inrush_w']:.0f}W piek, "
                                            f"{deviation['current']['runup_s']:.1f}s opstart\n"
                                            f"Normaal: {deviation['baseline']['inrush_w']:.0f}W piek, "
                                            f"{deviation['baseline']['runup_s']:.1f}s opstart"
                                        ),
                                        severity=deviation["severity"],
                                    )
                                except Exception as _cb_err:
                                    _LOGGER.debug("ElectricalFingerprint notify fout: %s", _cb_err)

                            _LOGGER.warning(
                                "ElectricalFingerprint: %s — %s (%.0f%% afwijking, waarschuwing #%d)",
                                label, deviation["problem_type"], deviation["max_dev_pct"], fp.warning_count
                            )

        return warnings

    def get_status(self) -> list[dict]:
        """Status voor dashboard sensor."""
        return [fp.to_dict() for fp in self._prints.values()]

    def get_fingerprint(self, device_id: str) -> Optional[ApplianceFingerprint]:
        return self._prints.get(device_id)
