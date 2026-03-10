# -*- coding: utf-8 -*-
"""CloudEMS — Wasbeurt Cyclus Detector (v2.6).

Detecteert de actieve wasfase, herkent het programma en schat de
resterende tijd — volledig zelf-lerend, geen vaste tijden.

WERKING
═══════
Input: vermogen in Watt per coordinator-cyclus (van smart plug of NILM).

Fase-detectie via vermogensprofiel:
  voorwas     laag vermogen (<300W), < 5 min
  verwarmen   hoog stabiel vermogen (>1500W), temperatuur opbouwen
  wassen      wisselend vermogen, trommelbewegingen zichtbaar
  spoelen     pieken door centrifuge-aanloop
  centrifuge  hoog pieken (>1800W), korte bursts

Programma-herkenning via EMA-leermodel:
  Elke voltooide cyclus slaat een "handtekening" op:
    - duurtijd per fase
    - gemiddeld en piek-vermogen per fase
    - totale kWh
  Na 3+ cycli: herkent terugkerende patronen als een "programma"
  en geeft het een naam (Katoen 60°, Eco, Snel 30 min, etc.)

Resterende tijd:
  Fysisch model: verstreken_tijd / geleerde_totaalduur × -1
  PID-correctie: past bij op basis van hoe snel de huidige cyclus
  vordert t.o.v. het geleerde profiel.

Integratie met CloudEMS:
  - Werkt op smart plug entity (sensor.wasmachine_vermogen)
  - Of op NILM device_id (cloudems detecteert automatisch)
  - Stuurt notificatie bij start, einde, en resterende <10 min
  - Integreert met ApplianceShiftAdvisor (beste tijd plannen)
  - Integreert met device_lifespan (cycli tellen)

Copyright 2025 CloudEMS
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .pid_controller import PIDController

_LOGGER = logging.getLogger(__name__)

# ── Apparaat-type ─────────────────────────────────────────────────────────────

class ApparaatType(str, Enum):
    WASMACHINE  = "wasmachine"
    DROGER      = "droger"
    VAATWASSER  = "vaatwasser"


# ── Fasen ─────────────────────────────────────────────────────────────────────

class WasFase(str, Enum):
    IDLE        = "idle"
    VOORWAS     = "voorwas"
    VERWARMEN   = "verwarmen"
    WASSEN      = "wassen"
    SPOELEN     = "spoelen"
    CENTRIFUGE  = "centrifuge"
    KLAAR       = "klaar"
    # Droger-specifieke fasen
    OPWARMEN    = "opwarmen"     # Droger: verwarmingselement aan, temperatuur opbouwen
    DROGEN      = "drogen"       # Droger: stabiel hoog vermogen, trommel draait
    AFKOELEN    = "afkoelen"     # Droger: element uit, trommel draait door (koelfase)


FASE_NL = {
    WasFase.IDLE:       "Uit",
    WasFase.VOORWAS:    "Voorwas",
    WasFase.VERWARMEN:  "Verwarmen",
    WasFase.WASSEN:     "Wassen",
    WasFase.SPOELEN:    "Spoelen",
    WasFase.CENTRIFUGE: "Centrifuge",
    WasFase.KLAAR:      "Klaar",
    WasFase.OPWARMEN:   "Opwarmen",
    WasFase.DROGEN:     "Drogen",
    WasFase.AFKOELEN:   "Afkoelen",
}

FASE_ICON = {
    WasFase.IDLE:       "💤",
    WasFase.VOORWAS:    "💧",
    WasFase.VERWARMEN:  "🌡️",
    WasFase.WASSEN:     "🌀",
    WasFase.SPOELEN:    "💦",
    WasFase.CENTRIFUGE: "⚡",
    WasFase.KLAAR:      "✅",
    WasFase.OPWARMEN:   "🔥",
    WasFase.DROGEN:     "♨️",
    WasFase.AFKOELEN:   "❄️",
}

# Apparaat-label voor notificaties
APPARAAT_LABEL = {
    ApparaatType.WASMACHINE: "Wasmachine",
    ApparaatType.DROGER:     "Droger",
    ApparaatType.VAATWASSER: "Vaatwasser",
}

APPARAAT_ICON = {
    ApparaatType.WASMACHINE: "🧺",
    ApparaatType.DROGER:     "🌬️",
    ApparaatType.VAATWASSER: "🍽️",
}

# Standaard "bijna klaar" drempel in minuten
DEFAULT_BIJNA_KLAAR_MIN = 10


# ── Geleerd programma ─────────────────────────────────────────────────────────

@dataclass
class ProgrammaProfiel:
    """Geleerd vermogensprofiel van één wasbeurt-type."""
    naam:           str
    cycli:          int   = 0

    # Per fase: gemiddelde duur (minuten) en gemiddeld vermogen (W)
    fase_duur:      dict  = field(default_factory=dict)   # fase → minuten
    fase_vermogen:  dict  = field(default_factory=dict)   # fase → watt
    totaal_duur:    float = 0.0   # minuten
    totaal_kwh:     float = 0.0

    _ALPHA = 0.25   # EMA-factor per nieuwe cyclus

    def update(self, fase_data: dict) -> None:
        """Verwerk één nieuwe cyclus in het geleerde profiel."""
        self.cycli += 1
        for fase, data in fase_data.items():
            duur = data.get("duur_min", 0)
            verm = data.get("avg_w", 0)
            if fase not in self.fase_duur:
                self.fase_duur[fase]     = duur
                self.fase_vermogen[fase] = verm
            else:
                self.fase_duur[fase]     = self._ALPHA * duur     + (1 - self._ALPHA) * self.fase_duur[fase]
                self.fase_vermogen[fase] = self._ALPHA * verm     + (1 - self._ALPHA) * self.fase_vermogen[fase]

        total = sum(self.fase_duur.values())
        kwh   = fase_data.get("_totaal_kwh", 0)
        self.totaal_duur = self._ALPHA * total + (1 - self._ALPHA) * self.totaal_duur if self.cycli > 1 else total
        self.totaal_kwh  = self._ALPHA * kwh   + (1 - self._ALPHA) * self.totaal_kwh  if self.cycli > 1 else kwh

    def similarity(self, fase_data: dict) -> float:
        """Gelijkenis (0-1) tussen nieuwe cyclus en dit profiel."""
        if self.cycli < 2:
            return 0.0
        scores = []
        for fase, data in fase_data.items():
            if fase not in self.fase_duur:
                continue
            duur_ref = self.fase_duur[fase]
            duur_act = data.get("duur_min", 0)
            if duur_ref > 0:
                scores.append(1.0 - min(1.0, abs(duur_act - duur_ref) / duur_ref))
        return sum(scores) / len(scores) if scores else 0.0

    def to_dict(self) -> dict:
        return {
            "naam": self.naam, "cycli": self.cycli,
            "fase_duur": self.fase_duur, "fase_vermogen": self.fase_vermogen,
            "totaal_duur": round(self.totaal_duur, 1),
            "totaal_kwh": round(self.totaal_kwh, 3),
        }


# ── Fase-detector ─────────────────────────────────────────────────────────────

class FaseDetector:
    """Detecteert de huidige wasfase op basis van het vermogenssignaal.

    Volledig zelf-lerend: de drempelwaarden worden geleerd uit de
    vermogensdistributie van de eerste paar cycli.

    Geleerde parameters per wasmachine:
      idle_max_w       max vermogen bij stilstand (standby)
      heat_min_w       min vermogen bij verwarmen
      spin_peak_w      typisch piek-vermogen bij centrifuge
      wash_avg_w       gemiddeld vermogen tijdens wassen

    Fase-overgang logica (histerese om pendelen te voorkomen):
      IDLE      → VERWARMEN/VOORWAS  als power > idle_max + 50W voor >30s
      VERWARMEN → WASSEN             als power daalt >30% van verwarm-gem.
      WASSEN    → SPOELEN             als power tijdelijk stijgt (centrifuge-poging)
      SPOELEN   → CENTRIFUGE          als power > spin_peak * 0.8 voor >20s
      CENTRIFUGE→ KLAAR              als power < idle_max + 20W voor >60s
    """

    _ALPHA_IDLE  = 0.05   # traag — standby verandert nauwelijks
    _ALPHA_HEAT  = 0.15
    _ALPHA_SPIN  = 0.20
    _ALPHA_WASH  = 0.15

    # Minimale tijden in seconden voor fase-confirmatie
    _MIN_ACTIVE_S   = 30
    _MIN_HEAT_S     = 120
    _MIN_SPIN_S     = 20
    _MIN_IDLE_END_S = 60

    def __init__(self) -> None:
        # Geleerde drempelwaarden
        self._idle_max:   Optional[float] = None
        self._heat_min:   Optional[float] = None
        self._spin_peak:  Optional[float] = None
        self._wash_avg:   Optional[float] = None

        # Huidige fase-state
        self._fase          = WasFase.IDLE
        self._fase_sinds_ts: float = 0.0
        self._fase_samples: deque = deque(maxlen=20)
        self._prev_fase     = WasFase.IDLE

        # Buffer voor histerese
        self._candidate_fase: Optional[WasFase] = None
        self._candidate_ts:   float = 0.0

        # Running stats voor leren
        self._cycle_max_w:   float = 0.0
        self._heat_samples:  list  = []
        self._wash_samples:  list  = []

    @property
    def fase(self) -> WasFase:
        return self._fase

    @property
    def fase_duur_s(self) -> float:
        return time.time() - self._fase_sinds_ts if self._fase_sinds_ts > 0 else 0.0

    def update(self, power_w: float) -> WasFase:
        """Verwerk één vermogensmeting. Geeft huidige fase terug."""
        now = time.time()
        self._fase_samples.append(power_w)

        # Leer idle_max in IDLE staat
        if self._fase == WasFase.IDLE:
            if self._idle_max is None:
                self._idle_max = power_w
            elif power_w < (self._idle_max + 20):
                self._idle_max = self._ALPHA_IDLE * power_w + (1 - self._ALPHA_IDLE) * self._idle_max

        self._cycle_max_w = max(self._cycle_max_w, power_w)

        idle_threshold = (self._idle_max or 10) + 50

        # Fase-transitie logica
        new_fase = self._evaluate_transition(power_w, now, idle_threshold)

        if new_fase != self._fase:
            self._on_fase_change(new_fase, power_w, now)

        return self._fase

    def _evaluate_transition(self, power_w: float, now: float, idle_thr: float) -> WasFase:
        avg_recent = sum(self._fase_samples) / len(self._fase_samples) if self._fase_samples else power_w

        if self._fase == WasFase.IDLE:
            if power_w > idle_thr:
                return self._confirm(WasFase.VERWARMEN, now, self._MIN_ACTIVE_S)
            return WasFase.IDLE

        elif self._fase in (WasFase.VERWARMEN, WasFase.VOORWAS):
            self._heat_samples.append(power_w)
            if self._heat_min is None and len(self._heat_samples) > 10:
                self._heat_min = sum(self._heat_samples) / len(self._heat_samples)
            # Verwarmen→Wassen: vermogen daalt significant
            heat_ref = self._heat_min or (idle_thr + 500)
            if avg_recent < heat_ref * 0.65 and self.fase_duur_s > self._MIN_HEAT_S:
                return self._confirm(WasFase.WASSEN, now, 30)
            return self._fase

        elif self._fase == WasFase.WASSEN:
            self._wash_samples.append(power_w)
            if self._wash_avg is None and len(self._wash_samples) > 20:
                self._wash_avg = sum(self._wash_samples) / len(self._wash_samples)
            wash_ref = self._wash_avg or idle_thr * 2
            # Wassen→Spoelen: tijdelijke piek (centrifuge-poging) dan daling
            if power_w > wash_ref * 2.0:
                return self._confirm(WasFase.SPOELEN, now, 15)
            return WasFase.WASSEN

        elif self._fase == WasFase.SPOELEN:
            spin_ref = self._spin_peak or self._cycle_max_w * 0.7
            if power_w > spin_ref * 0.8:
                return self._confirm(WasFase.CENTRIFUGE, now, self._MIN_SPIN_S)
            return WasFase.SPOELEN

        elif self._fase == WasFase.CENTRIFUGE:
            if power_w < idle_thr and self.fase_duur_s > self._MIN_IDLE_END_S:
                return self._confirm(WasFase.KLAAR, now, 10)
            # Leer spin_peak
            if power_w > (self._spin_peak or 0):
                self._spin_peak = self._ALPHA_SPIN * power_w + (1 - self._ALPHA_SPIN) * (self._spin_peak or power_w)
            return WasFase.CENTRIFUGE

        elif self._fase == WasFase.KLAAR:
            if power_w < idle_thr:
                return self._confirm(WasFase.IDLE, now, self._MIN_IDLE_END_S)
            return WasFase.KLAAR

        return self._fase

    def _confirm(self, candidate: WasFase, now: float, min_s: float) -> WasFase:
        """Histerese: bevestig fase-overgang pas na min_s seconden."""
        if self._candidate_fase != candidate:
            self._candidate_fase = candidate
            self._candidate_ts   = now
            return self._fase
        if (now - self._candidate_ts) >= min_s:
            return candidate
        return self._fase

    def _on_fase_change(self, new_fase: WasFase, power_w: float, now: float) -> None:
        _LOGGER.info(
            "WasCyclus: fase %s → %s (na %.0fs, %.0fW)",
            self._fase.value, new_fase.value, self.fase_duur_s, power_w
        )
        self._prev_fase      = self._fase
        self._fase           = new_fase
        self._fase_sinds_ts  = now
        self._fase_samples.clear()
        self._candidate_fase = None

        # Reset leer-buffers bij nieuwe cyclus
        if new_fase == WasFase.VERWARMEN:
            self._heat_samples.clear()
            self._wash_samples.clear()
            self._cycle_max_w = power_w

    def get_learned_params(self) -> dict:
        return {
            "idle_max_w":  round(self._idle_max, 1)  if self._idle_max  else None,
            "heat_min_w":  round(self._heat_min, 1)  if self._heat_min  else None,
            "spin_peak_w": round(self._spin_peak, 1) if self._spin_peak else None,
            "wash_avg_w":  round(self._wash_avg, 1)  if self._wash_avg  else None,
        }


# ── Droger fase-detector ──────────────────────────────────────────────────────

class DrogerFaseDetector:
    """Detecteert droger-fasen op basis van vermogenssignaal.

    Droger-profiel verschilt fundamenteel van wasmachine:
      IDLE      → standby / uit
      OPWARMEN  → hoog stabiel vermogen (verwarmingselement + motor), eerste fase
      DROGEN    → wisselend vermogen: element cycled aan/uit via thermostaat
                  Kenmerk: blokken hoog vermogen (~2000-3000W) afgewisseld met
                  laag vermogen (~100-200W motorloop)
      AFKOELEN  → aanzienlijke daling: alleen motor (~100-300W), geen element
                  Dit is de koelfase — trommel draait door zonder warmte
      KLAAR     → terug naar idle-niveau

    Zelf-lerend: drempelwaarden worden geleerd uit eerste 2-3 cycli.
    """

    _ALPHA_IDLE   = 0.05
    _ALPHA_HEAT   = 0.15
    _ALPHA_DRY    = 0.10
    _ALPHA_COOL   = 0.15

    # Fase-confirmatie tijden (seconden)
    _MIN_ACTIVE_S  = 45    # minimaal 45s boven drempel voor OPWARMEN
    _MIN_DRY_S     = 120   # droging duurt altijd > 2 min voor bevestiging
    _MIN_COOL_S    = 30    # koelfase bevestigen na 30s
    _MIN_END_S     = 60    # machine echt uit na 60s idle

    def __init__(self) -> None:
        self._idle_max:    Optional[float] = None
        self._heat_avg:    Optional[float] = None   # gemiddeld verwarmingsvermogen
        self._cool_max:    Optional[float] = None   # max vermogen koelfase (motor only)
        self._dry_on_avg:  Optional[float] = None   # gemiddeld AAN-vermogen tijdens drogen
        self._dry_off_avg: Optional[float] = None   # gemiddeld UIT-vermogen tijdens drogen

        self._fase            = WasFase.IDLE
        self._fase_sinds_ts:  float = 0.0
        self._fase_samples:   deque = deque(maxlen=20)
        self._candidate_fase: Optional[WasFase] = None
        self._candidate_ts:   float = 0.0

        # Cyclus-stats voor leren
        self._cycle_max_w:    float = 0.0
        self._heat_samples:   list  = []
        self._dry_samples_on: list  = []
        self._dry_samples_off:list  = []
        self._cool_samples:   list  = []

    @property
    def fase(self) -> WasFase:
        return self._fase

    @property
    def fase_duur_s(self) -> float:
        return time.time() - self._fase_sinds_ts if self._fase_sinds_ts > 0 else 0.0

    def update(self, power_w: float) -> WasFase:
        """Verwerk één vermogensmeting en geef huidige fase terug."""
        now = time.time()
        self._fase_samples.append(power_w)
        if self._fase == WasFase.IDLE:
            if self._idle_max is None:
                self._idle_max = power_w
            elif power_w < (self._idle_max + 20):
                self._idle_max = self._ALPHA_IDLE * power_w + (1 - self._ALPHA_IDLE) * self._idle_max
        self._cycle_max_w = max(self._cycle_max_w, power_w)
        idle_thr = (self._idle_max or 15) + 60

        new_fase = self._evaluate_transition(power_w, now, idle_thr)
        if new_fase != self._fase:
            self._on_fase_change(new_fase, power_w, now)
        return self._fase

    def _evaluate_transition(self, power_w: float, now: float, idle_thr: float) -> WasFase:
        avg = sum(self._fase_samples) / len(self._fase_samples) if self._fase_samples else power_w

        if self._fase == WasFase.IDLE:
            if power_w > idle_thr:
                return self._confirm(WasFase.OPWARMEN, now, self._MIN_ACTIVE_S)
            return WasFase.IDLE

        elif self._fase == WasFase.OPWARMEN:
            self._heat_samples.append(power_w)
            if self._heat_avg is None and len(self._heat_samples) > 15:
                self._heat_avg = sum(self._heat_samples) / len(self._heat_samples)
            heat_ref = self._heat_avg or (idle_thr + 800)

            # Droger gaat van opwarmen naar drogen zodra vermogen gaat cyclen:
            # het element schakelt periodiek → we zien daling gevolgd door puls-patroon
            # Indicator: recent gemiddelde daalt > 35% t.o.v. verwarmingsgemiddelde
            if avg < heat_ref * 0.65 and self.fase_duur_s > self._MIN_DRY_S:
                return self._confirm(WasFase.DROGEN, now, 30)
            return WasFase.OPWARMEN

        elif self._fase == WasFase.DROGEN:
            heat_ref = self._heat_avg or (idle_thr + 800)
            cool_threshold = (self._cool_max or idle_thr * 3)

            # Verzamel dry-on/off samples voor leren
            if power_w > heat_ref * 0.5:
                self._dry_samples_on.append(power_w)
                if len(self._dry_samples_on) > 5 and self._dry_on_avg is None:
                    self._dry_on_avg = sum(self._dry_samples_on) / len(self._dry_samples_on)
            else:
                self._dry_samples_off.append(power_w)
                if len(self._dry_samples_off) > 5 and self._dry_off_avg is None:
                    self._dry_off_avg = sum(self._dry_samples_off) / len(self._dry_samples_off)

            # Overgang naar AFKOELEN: vermogen zakt sterk en blijft laag
            # Koelfase: motor draait (~100-400W), geen verwarmingselement meer
            cool_ref = (self._dry_off_avg or idle_thr) * 2.5
            if avg < cool_ref and self.fase_duur_s > 300:   # minimaal 5 min droogfase
                return self._confirm(WasFase.AFKOELEN, now, self._MIN_COOL_S)
            return WasFase.DROGEN

        elif self._fase == WasFase.AFKOELEN:
            self._cool_samples.append(power_w)
            if self._cool_max is None and len(self._cool_samples) > 10:
                self._cool_max = max(self._cool_samples)

            # Afkoelen → KLAAR: vermogen daalt richting idle
            if power_w < idle_thr and self.fase_duur_s > self._MIN_END_S:
                return self._confirm(WasFase.KLAAR, now, 10)
            return WasFase.AFKOELEN

        elif self._fase == WasFase.KLAAR:
            if power_w < idle_thr:
                return self._confirm(WasFase.IDLE, now, self._MIN_END_S)
            return WasFase.KLAAR

        return self._fase

    def _confirm(self, candidate: WasFase, now: float, min_s: float) -> WasFase:
        if self._candidate_fase != candidate:
            self._candidate_fase = candidate
            self._candidate_ts   = now
            return self._fase
        if (now - self._candidate_ts) >= min_s:
            return candidate
        return self._fase

    def _on_fase_change(self, new_fase: WasFase, power_w: float, now: float) -> None:
        _LOGGER.info(
            "DrogerCyclus: fase %s → %s (na %.0fs, %.0fW)",
            self._fase.value, new_fase.value, self.fase_duur_s, power_w,
        )
        self._fase          = new_fase
        self._fase_sinds_ts = now
        self._fase_samples.clear()
        self._candidate_fase = None
        if new_fase == WasFase.OPWARMEN:
            self._heat_samples.clear()
            self._dry_samples_on.clear()
            self._dry_samples_off.clear()
            self._cool_samples.clear()
            self._cycle_max_w = power_w

    def get_learned_params(self) -> dict:
        return {
            "idle_max_w":    round(self._idle_max, 1)    if self._idle_max    else None,
            "heat_avg_w":    round(self._heat_avg, 1)    if self._heat_avg    else None,
            "dry_on_avg_w":  round(self._dry_on_avg, 1)  if self._dry_on_avg  else None,
            "dry_off_avg_w": round(self._dry_off_avg, 1) if self._dry_off_avg else None,
            "cool_max_w":    round(self._cool_max, 1)    if self._cool_max    else None,
        }


# ── Hoofd WasCyclus klasse ────────────────────────────────────────────────────

class WashCycleDetector:
    """Detecteert wasbeurten, herkent programma's en schat resterende tijd.

    Gebruik:
        detector = WashCycleDetector(hass, {
            "power_sensor": "sensor.wasmachine_vermogen",   # smart plug
            # of:
            "nilm_device_id": "device_wasmachine_abc123",  # NILM
        })
        result = await detector.async_update(coordinator_data)
    """

    _MIN_CYCLE_MIN = 10     # minimale cyclustijd om te registreren

    def __init__(self, hass: "HomeAssistant", cfg: dict) -> None:
        self._hass         = hass
        self._power_sensor = cfg.get("power_sensor")
        self._nilm_id      = cfg.get("nilm_device_id")
        self._label        = cfg.get("label", "wasmachine")

        # Apparaat-type bepaalt welke fase-detector en notificatieteksten gebruikt worden
        apparaat_str = cfg.get("apparaat_type", "wasmachine").lower()
        try:
            self._apparaat_type = ApparaatType(apparaat_str)
        except ValueError:
            self._apparaat_type = ApparaatType.WASMACHINE

        # Kies juiste fase-detector op basis van apparaat-type
        if self._apparaat_type == ApparaatType.DROGER:
            self._fase_detector: FaseDetector | DrogerFaseDetector = DrogerFaseDetector()
        else:
            self._fase_detector = FaseDetector()

        self._programmas:    list[ProgrammaProfiel] = []
        self._actief_profiel: Optional[ProgrammaProfiel] = None

        # Notificatie-instellingen
        # notify_targets: lijst van HA-notify-service-namen, bijv. ["notify.mobile_app_jan"]
        # Als leeg: wordt auto-ontdekt via async_setup (alle mobile_app notify-services)
        self._notify_targets: list[str] = cfg.get("notify_targets", [])
        self._notify_targets_autodiscovered: bool = False
        self._bijna_klaar_min: float = float(cfg.get("bijna_klaar_min", DEFAULT_BIJNA_KLAAR_MIN))
        self._notify_start: bool = cfg.get("notify_start", False)  # optioneel: melding bij start

        # Huidige cyclus tracking
        self._cyclus_start_ts:  float = 0.0
        self._cyclus_fase_data: dict  = {}   # fase → {duur_min, avg_w, samples}
        self._cyclus_kwh:       float = 0.0
        self._is_active:        bool  = False
        self._klaar_notif_sent: bool  = False
        self._bijna_klaar_sent: bool  = False

        # PID voor resterende-tijd voorspelling
        # Setpoint = 1.0 (= 100% voortgang), meting = huidige voortgang
        # Output = gecorrigeerde resterende minuten
        self._pid = PIDController(
            kp=3.0, ki=0.1, kd=0.5,
            setpoint=1.0,
            output_min=0.0,
            output_max=180.0,
            deadband=0.02,
            sample_time=60.0,
            label=f"wascyclus_{self._label}_pid",
        )

        # Stats
        self._totaal_cycli:   int   = 0
        self._totaal_kwh:     float = 0.0
        self._laatste_klaar:  Optional[datetime] = None

    # ── Hoofd update ─────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Auto-discover notify-targets als niet handmatig geconfigureerd."""
        if self._notify_targets or self._notify_targets_autodiscovered:
            return
        try:
            # Zoek alle mobile_app notify-services (HA Companion App)
            all_services = self._hass.services.async_services()
            notify_services = all_services.get("notify", {})
            mobile_targets = [
                f"notify.{svc}"
                for svc in notify_services
                if svc.startswith("mobile_app_")
            ]
            if mobile_targets:
                self._notify_targets = mobile_targets
                _LOGGER.info(
                    "%s: %d mobiele notify-services auto-ontdekt: %s",
                    self._label, len(mobile_targets), mobile_targets,
                )
            self._notify_targets_autodiscovered = True
        except Exception as err:
            _LOGGER.debug("Notify auto-discovery mislukt: %s", err)

    async def async_update(self, data: dict) -> dict:
        power_w = self._read_power(data)
        if power_w is None:
            return self.get_status()

        now_ts = time.time()
        fase   = self._fase_detector.update(power_w)

        # Cyclus-start detectie
        if fase != WasFase.IDLE and not self._is_active:
            self._start_cyclus(now_ts)
            if self._notify_start:
                await self._notify_gestart()

        # Lopende cyclus
        if self._is_active:
            self._track_fase(fase, power_w, now_ts)

            # kWh bijhouden (vermogen × tijdstap)
            dt_h = 10 / 3600   # coordinator cyclus ~10s in uren
            self._cyclus_kwh += power_w * dt_h / 1000

            # Bijna-klaar notificatie op basis van geschatte resterende tijd
            if not self._bijna_klaar_sent and self._bijna_klaar_min > 0:
                remaining = self._calc_remaining_min()
                if remaining is not None and 0 < remaining <= self._bijna_klaar_min:
                    await self._notify_bijna_klaar(remaining)

        # Cyclus einde
        if fase == WasFase.KLAAR and self._is_active:
            await self._einde_cyclus(data)

        elif fase == WasFase.IDLE and self._is_active:
            # Machine uit zonder KLAAR fase (stroom eruit getrokken?)
            duur = (now_ts - self._cyclus_start_ts) / 60
            if duur >= self._MIN_CYCLE_MIN:
                await self._einde_cyclus(data)
            else:
                self._reset_cyclus()

        return self.get_status()

    # ── Cyclus tracking ───────────────────────────────────────────────────────

    def _start_cyclus(self, ts: float) -> None:
        self._is_active       = True
        self._cyclus_start_ts = ts
        self._cyclus_fase_data= {}
        self._cyclus_kwh      = 0.0
        self._klaar_notif_sent= False
        self._bijna_klaar_sent= False
        self._pid.reset()
        _LOGGER.info("%s: wasbeurt gestart", self._label)

    def _track_fase(self, fase: WasFase, power_w: float, ts: float) -> None:
        if fase in (WasFase.IDLE, WasFase.KLAAR):
            return
        key = fase.value
        if key not in self._cyclus_fase_data:
            self._cyclus_fase_data[key] = {
                "start_ts": ts, "duur_min": 0.0,
                "avg_w": power_w, "samples": 1, "max_w": power_w
            }
        else:
            d = self._cyclus_fase_data[key]
            d["duur_min"] = (ts - d["start_ts"]) / 60
            n = d["samples"] + 1
            d["avg_w"]   = (d["avg_w"] * d["samples"] + power_w) / n
            d["max_w"]   = max(d["max_w"], power_w)
            d["samples"] = n

    async def _einde_cyclus(self, data: dict) -> None:
        duur_min = (time.time() - self._cyclus_start_ts) / 60
        if duur_min < self._MIN_CYCLE_MIN:
            self._reset_cyclus()
            return

        self._cyclus_fase_data["_totaal_kwh"] = self._cyclus_kwh
        self._totaal_cycli += 1
        self._totaal_kwh   += self._cyclus_kwh
        self._laatste_klaar = datetime.now(timezone.utc)

        # Programma herkennen of nieuw aanmaken
        programma = self._match_or_create_programma(self._cyclus_fase_data, duur_min)
        programma.update(self._cyclus_fase_data)
        self._actief_profiel = programma

        _LOGGER.info(
            "%s: cyclus klaar — %.0f min, %.3f kWh, programma: %s (cyclus #%d)",
            self._label, duur_min, self._cyclus_kwh, programma.naam, self._totaal_cycli
        )

        # Notificatie
        await self._notify_klaar(data, programma, duur_min)
        self._reset_cyclus()

    def _reset_cyclus(self) -> None:
        self._is_active       = False
        self._cyclus_start_ts = 0.0
        self._cyclus_fase_data= {}
        self._cyclus_kwh      = 0.0

    # ── Programma-herkenning ──────────────────────────────────────────────────

    def _match_or_create_programma(self, fase_data: dict, duur_min: float) -> ProgrammaProfiel:
        """Zoek het beste passende profiel of maak een nieuw programma aan."""
        if not self._programmas:
            return self._nieuw_programma(duur_min)

        beste_score = 0.0
        beste       = None
        for p in self._programmas:
            score = p.similarity(fase_data)
            if score > beste_score and score > 0.65:
                beste_score = score
                beste       = p

        if beste:
            return beste
        return self._nieuw_programma(duur_min)

    def _nieuw_programma(self, duur_min: float) -> ProgrammaProfiel:
        """Maak een nieuw programma-profiel met automatische naam."""
        n = len(self._programmas) + 1
        # Schatte programmanaam op basis van duur
        if duur_min < 35:
            naam = f"Snel ({duur_min:.0f} min)"
        elif duur_min < 80:
            naam = f"Normaal ({duur_min:.0f} min)"
        elif duur_min < 130:
            naam = f"Katoen ({duur_min:.0f} min)"
        else:
            naam = f"Intensief ({duur_min:.0f} min)"
        profiel = ProgrammaProfiel(naam=naam)
        self._programmas.append(profiel)
        _LOGGER.info("%s: nieuw programma aangemaakt: %s", self._label, naam)
        return profiel

    # ── Resterende tijd ───────────────────────────────────────────────────────

    def _calc_remaining_min(self) -> Optional[float]:
        """Schat resterende tijd op basis van geleerd profiel + PID-correctie."""
        if not self._is_active or not self._actief_profiel:
            return None
        if self._actief_profiel.totaal_duur <= 0:
            return None

        elapsed   = (time.time() - self._cyclus_start_ts) / 60
        progress  = min(1.0, elapsed / self._actief_profiel.totaal_duur)
        remaining = max(0.0, self._actief_profiel.totaal_duur - elapsed)

        # PID bijsturen op basis van voortgang
        pid_out = self._pid.compute(progress)
        if pid_out is not None:
            # PID output = gecorrigeerde voortgang → resterende tijd
            remaining = max(0.0, self._actief_profiel.totaal_duur * (1.0 - progress) - pid_out * 0.1)

        return round(remaining, 0)

    # ── Notificaties ──────────────────────────────────────────────────────────

    async def _stuur_notificatie(
        self,
        title: str,
        message: str,
        notification_id: str,
        data: Optional[dict] = None,
    ) -> None:
        """Stuur notificatie naar alle geconfigureerde targets.

        Altijd: persistent_notification (HA UI).
        Optioneel: elke notify.*-service in self._notify_targets (mobiele push).
        """
        # 1. Altijd persistent_notification in de HA UI
        try:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title":           title,
                    "message":         message,
                    "notification_id": notification_id,
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.debug("persistent_notification mislukt: %s", err)

        # 2. Mobiele push / andere notify-targets
        for target in self._notify_targets:
            # target kan zijn: "notify.mobile_app_jan" of gewoon "mobile_app_jan"
            service = target if "." in target else f"notify.{target}"
            domain, svc = service.split(".", 1)
            try:
                payload: dict = {"title": title, "message": message}
                if data:
                    payload["data"] = data
                await self._hass.services.async_call(
                    domain, svc, payload, blocking=False,
                )
                _LOGGER.debug("Notificatie verstuurd naar %s", service)
            except Exception as err:
                _LOGGER.debug("Notificatie naar %s mislukt: %s", service, err)

    async def _notify_gestart(self) -> None:
        """Optionele melding bij start van een cyclus."""
        icon  = APPARAAT_ICON.get(self._apparaat_type, "🧺")
        label = APPARAAT_LABEL.get(self._apparaat_type, self._label)
        await self._stuur_notificatie(
            title=f"{icon} {self._label} gestart",
            message=f"{label} is begonnen.",
            notification_id=f"cloudems_{self._apparaat_type.value}_{self._label}_start",
        )

    async def _notify_bijna_klaar(self, remaining_min: float) -> None:
        """Melding wanneer de resterende tijd onder de drempel zakt."""
        if self._bijna_klaar_sent:
            return
        self._bijna_klaar_sent = True
        icon  = APPARAAT_ICON.get(self._apparaat_type, "🧺")
        label = APPARAAT_LABEL.get(self._apparaat_type, self._label)
        await self._stuur_notificatie(
            title=f"{icon} {self._label} bijna klaar",
            message=(
                f"{label} is over ~{remaining_min:.0f} minuten klaar.\n"
                f"⚡ Verbruik tot nu: {self._cyclus_kwh:.3f} kWh"
            ),
            notification_id=f"cloudems_{self._apparaat_type.value}_{self._label}_bijna",
            data={"tag": f"cloudems_{self._label}_bijna"},
        )
        _LOGGER.info("%s: bijna-klaar notificatie verstuurd (%.0f min resterend)", self._label, remaining_min)

    async def _notify_klaar(self, data: dict, programma: ProgrammaProfiel, duur_min: float) -> None:
        if self._klaar_notif_sent:
            return
        self._klaar_notif_sent = True
        icon  = APPARAAT_ICON.get(self._apparaat_type, "🧺")
        label = APPARAAT_LABEL.get(self._apparaat_type, self._label)
        await self._stuur_notificatie(
            title=f"{icon} {self._label} klaar",
            message=(
                f"{label} klaar — {programma.naam}\n"
                f"⏱️ Duur: {duur_min:.0f} min | "
                f"⚡ Verbruik: {self._cyclus_kwh:.3f} kWh\n"
                f"(Cyclus #{self._totaal_cycli} van dit apparaat)"
            ),
            notification_id=f"cloudems_{self._apparaat_type.value}_{self._label}_klaar",
            data={"tag": f"cloudems_{self._label}_klaar"},
        )

    # ── Sensor lezen ─────────────────────────────────────────────────────────

    def _read_power(self, data: dict) -> Optional[float]:
        # Prioriteit 1: directe smart plug sensor
        if self._power_sensor:
            st = self._hass.states.get(self._power_sensor)
            if st:
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    pass

        # Prioriteit 2: NILM device op ID
        if self._nilm_id:
            devices = data.get("nilm_devices", [])
            for dev in devices:
                if dev.get("device_id") == self._nilm_id:
                    return float(dev.get("power_w", 0) or 0)

        # Prioriteit 3: NILM op apparaat-type
        nilm_types_per_apparaat = {
            ApparaatType.WASMACHINE: ("washing_machine", "washer"),
            ApparaatType.DROGER:     ("dryer", "tumble_dryer", "droger"),
            ApparaatType.VAATWASSER: ("dishwasher", "vaatwasser"),
        }
        target_types = nilm_types_per_apparaat.get(self._apparaat_type, ())
        devices = data.get("nilm_devices", [])
        for dev in devices:
            if dev.get("device_type") in target_types:
                return float(dev.get("power_w", 0) or 0)

        return None

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        fase    = self._fase_detector.fase
        elapsed = (time.time() - self._cyclus_start_ts) / 60 if self._is_active else 0
        remaining = self._calc_remaining_min()

        return {
            "label":           self._label,
            "apparaat_type":   self._apparaat_type.value,
            "is_active":       self._is_active,
            "fase":            fase.value,
            "fase_nl":         FASE_NL.get(fase, fase.value),
            "fase_icon":       FASE_ICON.get(fase, "❓"),
            "elapsed_min":     round(elapsed, 0) if self._is_active else None,
            "remaining_min":   remaining,
            "bijna_klaar_min": self._bijna_klaar_min,
            "bijna_klaar_sent":self._bijna_klaar_sent,
            "huidig_programma":self._actief_profiel.naam if self._actief_profiel else None,
            "cyclus_kwh":      round(self._cyclus_kwh, 3) if self._is_active else None,
            "totaal_cycli":    self._totaal_cycli,
            "totaal_kwh":      round(self._totaal_kwh, 3),
            "laatste_klaar":   self._laatste_klaar.isoformat() if self._laatste_klaar else None,
            "notify_targets":  self._notify_targets,
            "programmas":      [p.to_dict() for p in self._programmas],
            "geleerde_params": self._fase_detector.get_learned_params(),
            "pid":             self._pid.to_dict(),
        }

    def to_persist(self) -> dict:
        """Sla geleerde data op (via HA Store)."""
        return {
            "totaal_cycli":  self._totaal_cycli,
            "totaal_kwh":    self._totaal_kwh,
            "programmas":    [p.to_dict() for p in self._programmas],
            "fase_params":   self._fase_detector.get_learned_params(),
        }

    def from_persist(self, data: dict) -> None:
        """Herstel geleerde data na herstart."""
        self._totaal_cycli = int(data.get("totaal_cycli", 0))
        self._totaal_kwh   = float(data.get("totaal_kwh", 0))
        for pd in data.get("programmas", []):
            p = ProgrammaProfiel(naam=pd["naam"], cycli=pd.get("cycli", 0))
            p.fase_duur     = pd.get("fase_duur", {})
            p.fase_vermogen = pd.get("fase_vermogen", {})
            p.totaal_duur   = pd.get("totaal_duur", 0)
            p.totaal_kwh    = pd.get("totaal_kwh", 0)
            self._programmas.append(p)
        # Activeer meest recente profiel als standaard
        if self._programmas:
            self._actief_profiel = max(self._programmas, key=lambda p: p.cycli)


# ── Manager voor meerdere apparaten ───────────────────────────────────────────

class ApplianceCycleManager:
    """Beheert WashCycleDetectors voor alle geconfigureerde apparaten.

    Werkt ook voor:
      - Droogkast (dryer)   → zelfde fase-logica, andere vermogensprofielen
      - Vaatwasser           → zelfde aanpak

    Gebruik vanuit coordinator:
        mgr = ApplianceCycleManager(hass, config)
        await mgr.async_setup()
        result = await mgr.async_update(coordinator_data)
    """

    STORAGE_KEY = "cloudems_appliance_cycles_v1"

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass      = hass
        self._detectors: list[WashCycleDetector] = []
        self._config    = config

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, 1, self.STORAGE_KEY)
        saved = await self._store.async_load() or {}

        # Bouw detectors op basis van expliciete config
        for app_cfg in self._config.get("appliance_cycle_devices", []):
            det = WashCycleDetector(self._hass, app_cfg)
            label = app_cfg.get("label", "wasmachine")
            if label in saved:
                det.from_persist(saved[label])
            self._detectors.append(det)
            _LOGGER.info(
                "ApplianceCycleManager: %s (%s) geladen (%d programma's, %d cycli)",
                label, det._apparaat_type.value, len(det._programmas), det._totaal_cycli,
            )

        # Auto-discovery via NILM: voeg apparaten toe die nog niet geconfigureerd zijn
        # Checkt op device_type in NILM resultaten bij eerste update
        if not self._detectors:
            # Minimale fallback: wasmachine zonder smart plug (puur NILM)
            self._detectors.append(WashCycleDetector(self._hass, {
                "label": "wasmachine",
                "apparaat_type": "wasmachine",
            }))

        # Auto-discover notify-targets voor alle detectors
        for det in self._detectors:
            await det.async_setup()

    async def async_update(self, data: dict) -> dict:
        # NILM auto-discovery: voeg droger toe als NILM hem detecteert en hij nog niet geconfigureerd is
        known_types = {det._apparaat_type for det in self._detectors}
        nilm_devices = data.get("nilm_devices", [])
        for dev in nilm_devices:
            dev_type = dev.get("device_type", "")
            if dev_type in ("dryer", "tumble_dryer", "droger") and ApparaatType.DROGER not in known_types:
                _LOGGER.info("ApplianceCycleManager: droger ontdekt via NILM, detector aangemaakt")
                saved = {}
                if hasattr(self, "_store"):
                    try:
                        saved = await self._store.async_load() or {}
                    except Exception:
                        pass
                new_det = WashCycleDetector(self._hass, {
                    "label": "droger",
                    "apparaat_type": "droger",
                })
                if "droger" in saved:
                    new_det.from_persist(saved["droger"])
                await new_det.async_setup()
                self._detectors.append(new_det)
                known_types.add(ApparaatType.DROGER)

        results = []
        for det in self._detectors:
            try:
                status = await det.async_update(data)
                results.append(status)
            except Exception as err:
                _LOGGER.error("ApplianceCycle %s fout: %s", det._label, err)

        # Periodiek opslaan
        if hasattr(self, "_store"):
            try:
                await self._store.async_save({
                    det._label: det.to_persist() for det in self._detectors
                })
            except Exception:
                pass

        return {"apparaten": results}

    def get_all_status(self) -> list[dict]:
        return [det.get_status() for det in self._detectors]
