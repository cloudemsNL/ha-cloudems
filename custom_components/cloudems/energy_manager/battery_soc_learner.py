# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
battery_soc_learner.py — CloudEMS v4.5.66
==========================================
Zelflerend systeem voor SOC, capaciteit en max-vermogen van thuisbatterijen.
Werkt met én zonder geconfigureerde SOC-sensor.

Drie leerniveaus
─────────────────

1. VERMOGEN (max_charge_w / max_discharge_w)
   Elke gemeten waarde boven de huidige max wordt opgeslagen.
   Plateau-detectie: als P stabiel blijft (±15%) gedurende ≥30 s op een hoog
   niveau → dit is het werkelijke hardware-maximum, niet een toevalspiek.
   Na MIN_POWER_SAMPLES metingen geldt de schatting als betrouwbaar.

2. CAPACITEIT (capacity_kwh)
   Methode A  — SOC-sensor aanwezig:
     Meet Wh per SoC-procent (∫P·dt / ΔSOC) bij elke actieve tijdstap.
     Mediaan van ≥10 samples × 100 → capaciteit in kWh.

   Methode B  — geen SOC-sensor:
     Detecteer volledige laad- en ontlaadcycli via ankerpunten.
     De totaal geïntegreerde Wh tussen twee ankerpunten = feitelijke capaciteit.
     Mediaan van ≥3 cycli → betrouwbare schatting.

3. SOC (state of charge, 0–100 %)
   Methode A  — sensor beschikbaar: direct overnemen als ground-truth.
   Methode B  — geen sensor (volledig zelflerend):
     Ankerdetectie (reset-punten die stapelende integratiefout voorkomen):
       • Vol-anker  : P daalt naar ≈ 0 W na ≥10 min laden   → SOC = 100 %
       • Leeg-anker : P daalt naar ≈ 0 W na ≥ 5 min ontladen → SOC =   0 %
       • Sensor-100 : SOC-sensor ≥ 98 %                      → vol-anker
       • Sensor-0   : SOC-sensor ≤  3 %                      → leeg-anker
       • Zonneplan  : modus self_consumption + P ≈ 0          → vol-anker
     Tussen ankerpunten: SOC integreren via P × dt / capacity.
     Laadrendement 96 %, ontlaadrendement 96 % (configureerbaar).

   Confidence-afbraak zonder anker:
     < 1 h  → 0.90    1–4 h → lineair naar 0.60
     4–12 h → lineair naar 0.20    > 12 h → 0.20
     Zonder capaciteitsschatting: confidence ≤ 0.30.
     Na >24 h zonder anker: SOC drijft geleidelijk terug naar 50 %.

Persistentie
─────────────
Alle geleerde waarden worden via HA Store bewaard over herstarts.
Sleutel per entity_id → meerdere batterijen tegelijk ondersteund.

Gebruik
───────
    learner = BatterySocLearner(Store(hass, 1, STORAGE_KEY_SOC_LEARNER))
    await learner.async_load()

    result = learner.observe(
        entity_id    = "sensor.battery_power",
        power_w      = -1200.0,   # + = laden, - = ontladen
        dt_s         = 10.0,      # tijdstap (seconden)
        soc_pct      = None,      # None als geen sensor
        battery_mode = "home_optimization",
    )
    # result.soc_pct, result.capacity_kwh, result.max_charge_w,
    # result.max_discharge_w, result.confidence, result.source
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from statistics import median
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_SOC_LEARNER = "cloudems_battery_soc_learner_v1"

# ── Constanten ─────────────────────────────────────────────────────────────────
EFF_CHARGE       = 0.96    # laadrendement: 96 % van netenergie komt in accu
EFF_DISCHARGE    = 0.96    # ontlaadrendement: 96 % van accuenergie naar huis

MIN_POWER_W      = 30.0    # onder dit = idle
PLATEAU_TOL      = 0.15    # 15 % tolerantie voor plateaudetectie
PLATEAU_MIN_S    = 30.0    # minimum plateauduur (seconden)
MIN_POWER_SAMP   = 20      # samples voor betrouwbaar vermogen
MIN_CHARGE_MIN   = 10.0    # minuten laden voor vol-anker
MIN_DISCHARGE_MIN = 5.0    # minuten ontladen voor leeg-anker
MIN_CAP_CYCLES   = 3       # cycli voor betrouwbare capaciteit (methode B)
MIN_CAP_SAMP     = 10      # samples voor betrouwbare capaciteit (methode A)

MAX_DT_H         = 6 / 60  # max tijdstap 6 minuten (sanity)
MIN_CAP_KWH      = 0.3
MAX_CAP_KWH      = 100.0

CONF_4H          = 0.60
CONF_12H         = 0.20


# ── Resultaat-dataclass ────────────────────────────────────────────────────────

@dataclass
class BatterySocResult:
    entity_id:       str
    soc_pct:         Optional[float]   # None = onbekend
    capacity_kwh:    Optional[float]   # None = nog niet geleerd
    max_charge_w:    float
    max_discharge_w: float
    confidence:      float             # 0.0 – 1.0
    source:          str               # "sensor" / "inferred" / "unknown"
    anchor_type:     Optional[str]     # "full" / "empty" / None
    power_confident: bool
    capacity_source: str               # "sensor_integral" / "cycle_integral" / "none"

    @property
    def inferred(self) -> bool:
        """True als de SOC afgeleid is (niet direct van sensor). Gebruikt door coordinator."""
        return self.source == "inferred"


# ── Interne staat per batterij ────────────────────────────────────────────────

@dataclass
class _State:
    # ── vermogen ──────────────────────────────────────────────────────────────
    max_charge_w:     float = 0.0
    max_discharge_w:  float = 0.0
    power_samples:    int   = 0
    plateau_w:        float = 0.0
    plateau_start_s:  float = 0.0

    # ── capaciteit: methode A (met sensor) ────────────────────────────────────
    wh_per_pct:       list  = field(default_factory=list)  # max 100 samples
    prev_soc:         Optional[float] = None
    prev_ts:          float = 0.0

    # ── capaciteit: methode B (zonder sensor, cyclus-integratie) ─────────────
    cycle_kwh_hist:   list  = field(default_factory=list)  # max 20 cycli
    cycle_active:     bool  = False
    cycle_wh_acc:     float = 0.0
    cycle_dir:        str   = ""   # "charge" / "discharge"

    # ── SOC-inferentie ────────────────────────────────────────────────────────
    inferred_soc:     Optional[float] = None
    anchor_soc:       float = 50.0
    anchor_ts:        float = 0.0
    anchor_type:      Optional[str]   = None

    # ── richting-tracking (voor ankerdetectie) ────────────────────────────────
    cur_dir:          str   = ""
    dir_since_s:      float = 0.0

    # ── gecombineerde capaciteitsschatting ────────────────────────────────────
    est_capacity_kwh: Optional[float] = None

    # ── serialisatie ──────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "max_charge_w":    self.max_charge_w,
            "max_discharge_w": self.max_discharge_w,
            "power_samples":   self.power_samples,
            "wh_per_pct":      self.wh_per_pct[-100:],
            "prev_soc":        self.prev_soc,
            "prev_ts":         self.prev_ts,
            "cycle_kwh_hist":  self.cycle_kwh_hist[-20:],
            "cycle_active":    self.cycle_active,
            "cycle_wh_acc":    self.cycle_wh_acc,
            "cycle_dir":       self.cycle_dir,
            "inferred_soc":    self.inferred_soc,
            "anchor_soc":      self.anchor_soc,
            "anchor_ts":       self.anchor_ts,
            "anchor_type":     self.anchor_type,
            "cur_dir":         self.cur_dir,
            "dir_since_s":     self.dir_since_s,
            "est_capacity_kwh": self.est_capacity_kwh,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_State":
        s = cls()
        s.max_charge_w    = float(d.get("max_charge_w",    0))
        s.max_discharge_w = float(d.get("max_discharge_w", 0))
        s.power_samples   = int(d.get("power_samples", 0))
        s.wh_per_pct      = list(d.get("wh_per_pct", []))
        s.prev_soc        = d.get("prev_soc")
        s.prev_ts         = float(d.get("prev_ts", 0))
        s.cycle_kwh_hist  = list(d.get("cycle_kwh_hist", []))
        s.cycle_active    = bool(d.get("cycle_active", False))
        s.cycle_wh_acc    = float(d.get("cycle_wh_acc", 0))
        s.cycle_dir       = str(d.get("cycle_dir", ""))
        s.inferred_soc    = d.get("inferred_soc")
        s.anchor_soc      = float(d.get("anchor_soc", 50.0))
        s.anchor_ts       = float(d.get("anchor_ts", 0))
        s.anchor_type     = d.get("anchor_type")
        s.cur_dir         = str(d.get("cur_dir", ""))
        s.dir_since_s     = float(d.get("dir_since_s", 0))
        s.est_capacity_kwh = d.get("est_capacity_kwh")
        return s


# ── Hoofd-klasse ──────────────────────────────────────────────────────────────

class BatterySocLearner:
    """
    Zelflerend SOC / capaciteit / vermogen voor thuisbatterijen.

    Aanroepen vanuit coordinator elke update-cyclus (typisch 10 s).
    Persistentie via HA Store — overleeft HA-herstart.
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        self._states: dict[str, _State] = {}

    # ── Persistentie ──────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load() or {}
            for eid, d in raw.items():
                self._states[eid] = _State.from_dict(d)
            _LOGGER.debug(
                "BatterySocLearner: %d batterijen geladen uit store.", len(self._states)
            )
        except Exception as exc:
            _LOGGER.warning("BatterySocLearner async_load fout: %s", exc)

    async def async_save(self) -> None:
        try:
            await self._store.async_save(
                {eid: s.to_dict() for eid, s in self._states.items()}
            )
        except Exception as exc:
            _LOGGER.warning("BatterySocLearner async_save fout: %s", exc)

    # ── Publieke interface ─────────────────────────────────────────────────────

    def observe(
        self,
        entity_id:    str,
        power_w:      Optional[float],
        dt_s:         float,
        soc_pct:      Optional[float] = None,
        battery_mode: Optional[str]   = None,
    ) -> BatterySocResult:
        """
        Verwerk één tijdstap voor een batterij.

        Parameters
        ----------
        entity_id     : Unieke ID (power-sensor entity of label).
        power_w       : Vermogen in Watt. + = laden, - = ontladen, None = onbekend.
        dt_s          : Tijdstap in seconden (typisch 10).
        soc_pct       : SOC van externe sensor (None als niet aanwezig).
        battery_mode  : Optionele modus-string (bijv. "self_consumption").
        """
        s   = self._states.setdefault(entity_id, _State())
        now = time.time()

        # Stap 1 — vermogen leren (altijd)
        self._learn_power(s, power_w, now)

        # Stap 2 — capaciteit + SOC
        anchor: Optional[str] = None
        if soc_pct is not None:
            anchor = self._observe_with_sensor(s, soc_pct, power_w, dt_s, now)
        else:
            anchor = self._observe_without_sensor(s, power_w, dt_s, now, battery_mode)

        # Stap 3 — samenvatten
        cap = self._best_capacity(s)
        soc, conf, source = self._final_soc(s, soc_pct, power_w, cap, now)

        cap_source = "none"
        if cap:
            cap_source = "sensor_integral" if len(s.wh_per_pct) >= MIN_CAP_SAMP else "cycle_integral"

        return BatterySocResult(
            entity_id       = entity_id,
            soc_pct         = round(soc,  1) if soc  is not None else None,
            capacity_kwh    = round(cap,  2) if cap  is not None else None,
            max_charge_w    = round(s.max_charge_w,    0),
            max_discharge_w = round(s.max_discharge_w, 0),
            confidence      = round(conf, 3),
            source          = source,
            anchor_type     = anchor,
            power_confident = s.power_samples >= MIN_POWER_SAMP,
            capacity_source = cap_source,
        )

    def get_diagnostics(self, entity_id: str) -> dict:
        """Geeft diagnose-dict terug voor dashboard/log."""
        s = self._states.get(entity_id)
        if not s:
            return {"status": "no_data"}
        age_h = (time.time() - s.anchor_ts) / 3600.0 if s.anchor_ts else None
        return {
            "max_charge_w":         round(s.max_charge_w, 0),
            "max_discharge_w":      round(s.max_discharge_w, 0),
            "power_samples":        s.power_samples,
            "power_confident":      s.power_samples >= MIN_POWER_SAMP,
            "est_capacity_kwh":     round(s.est_capacity_kwh, 2) if s.est_capacity_kwh else None,
            "capacity_cycles":      len(s.cycle_kwh_hist),
            "capacity_wh_pct_samp": len(s.wh_per_pct),
            "capacity_confident":   (len(s.cycle_kwh_hist) >= MIN_CAP_CYCLES
                                     or len(s.wh_per_pct) >= MIN_CAP_SAMP),
            "inferred_soc_pct":     round(s.inferred_soc, 1) if s.inferred_soc is not None else None,
            "anchor_type":          s.anchor_type,
            "anchor_age_h":         round(age_h, 1) if age_h is not None else None,
        }

    # ── Intern: vermogen leren ─────────────────────────────────────────────────

    def _learn_power(self, s: _State, power_w: Optional[float], now: float) -> None:
        if power_w is None:
            return
        abs_w = abs(power_w)
        if abs_w < MIN_POWER_W:
            s.plateau_w = 0.0
            return

        s.power_samples += 1

        # Observed maximum
        if power_w > MIN_POWER_W and power_w > s.max_charge_w:
            s.max_charge_w = power_w
        elif power_w < -MIN_POWER_W and abs_w > s.max_discharge_w:
            s.max_discharge_w = abs_w

        # Plateau: stabiel vermogen ≥ PLATEAU_MIN_S → hardware-maximum
        if s.plateau_w > 0:
            dev = abs(abs_w - s.plateau_w) / max(s.plateau_w, 1.0)
            if dev > PLATEAU_TOL:
                s.plateau_w = abs_w
                s.plateau_start_s = now
        else:
            s.plateau_w = abs_w
            s.plateau_start_s = now

        if (now - s.plateau_start_s) >= PLATEAU_MIN_S:
            if power_w > 0:
                s.max_charge_w    = max(s.max_charge_w,    s.plateau_w)
            else:
                s.max_discharge_w = max(s.max_discharge_w, s.plateau_w)

    # ── Intern: met sensor ─────────────────────────────────────────────────────

    def _observe_with_sensor(
        self,
        s:       _State,
        soc_pct: float,
        power_w: Optional[float],
        dt_s:    float,
        now:     float,
    ) -> Optional[str]:
        """Leer capaciteit via Wh/SoC%-methode. Detecteer vol/leeg-ankerpunten."""
        anchor = None

        # Ankerpunten via sensor zelf
        if s.prev_soc is not None:
            if soc_pct >= 98.0 and s.prev_soc < 98.0:
                self._set_anchor(s, 100.0, "full", now)
                anchor = "full"
                _LOGGER.debug("BatterySocLearner [%s]: vol-anker via sensor", "battery")
            elif soc_pct <= 3.0 and s.prev_soc > 3.0:
                self._set_anchor(s, 0.0, "empty", now)
                anchor = "empty"
                _LOGGER.debug("BatterySocLearner [%s]: leeg-anker via sensor", "battery")

        # Wh per SoC-% meten
        if (s.prev_soc is not None and power_w is not None and s.prev_ts > 0):
            dt_h = (now - s.prev_ts) / 3600.0
            if 0 < dt_h < MAX_DT_H:
                dsoc = abs(soc_pct - s.prev_soc)
                dwh  = abs(power_w) * dt_h
                if dsoc > 0.2 and abs(power_w) > MIN_POWER_W:
                    ratio = dwh / dsoc
                    if 10 <= ratio <= 1000:   # sanity: 1 kWh–100 kWh
                        s.wh_per_pct.append(ratio)
                        if len(s.wh_per_pct) > 100:
                            s.wh_per_pct = s.wh_per_pct[-100:]

        s.prev_soc    = soc_pct
        s.prev_ts     = now
        s.inferred_soc = soc_pct   # sensor = ground truth
        return anchor

    # ── Intern: zonder sensor ─────────────────────────────────────────────────

    def _observe_without_sensor(
        self,
        s:            _State,
        power_w:      Optional[float],
        dt_s:         float,
        now:          float,
        battery_mode: Optional[str],
    ) -> Optional[str]:
        """
        Detecteer ankerpunten en integreer SOC zonder externe sensor.
        Accumuleert ook Wh voor capaciteitsschatting via volledige cycli.
        """
        if power_w is None:
            return None

        dt_h   = dt_s / 3600.0
        anchor: Optional[str] = None

        # Richting bepalen
        if power_w > MIN_POWER_W:
            new_dir = "charge"
        elif power_w < -MIN_POWER_W:
            new_dir = "discharge"
        else:
            new_dir = "idle"

        # ── Richtingsovergang ──────────────────────────────────────────────────
        if new_dir != s.cur_dir:
            dur_min = (now - s.dir_since_s) / 60.0 if s.dir_since_s > 0 else 0.0
            prev    = s.cur_dir

            # Overgang naar idle → ankerdetectie
            if new_dir == "idle" and prev in ("charge", "discharge"):

                if prev == "charge" and dur_min >= MIN_CHARGE_MIN:
                    self._set_anchor(s, 100.0, "full", now)
                    anchor = "full"
                    _LOGGER.info(
                        "BatterySocLearner: vol-anker (laden %.0f min, %.0f Wh geïntegreerd)",
                        dur_min, s.cycle_wh_acc,
                    )
                    # Sluit cyclus op als vorig anker leeg was
                    self._close_cycle(s, expected_dir="charge")

                elif prev == "discharge" and dur_min >= MIN_DISCHARGE_MIN:
                    self._set_anchor(s, 0.0, "empty", now)
                    anchor = "empty"
                    _LOGGER.info(
                        "BatterySocLearner: leeg-anker (ontladen %.0f min, %.0f Wh geïntegreerd)",
                        dur_min, s.cycle_wh_acc,
                    )
                    self._close_cycle(s, expected_dir="discharge")

            # Nieuwe actieve richting → start cyclus-tracking
            if new_dir in ("charge", "discharge"):
                s.cycle_active  = True
                s.cycle_dir     = new_dir
                s.cycle_wh_acc  = 0.0

            s.cur_dir    = new_dir
            s.dir_since_s = now

        # ── Energie accumuleren ────────────────────────────────────────────────
        if s.cycle_active:
            if new_dir == "charge":
                s.cycle_wh_acc += abs(power_w) * dt_h * EFF_CHARGE
            elif new_dir == "discharge":
                s.cycle_wh_acc += abs(power_w) * dt_h   # bruto ontlading

        # ── Zonneplan: self_consumption + idle → vol-anker ────────────────────
        if (battery_mode == "self_consumption"
                and new_dir == "idle"
                and s.anchor_type != "full"
                and s.dir_since_s > 0
                and (now - s.dir_since_s) > 60):
            self._set_anchor(s, 100.0, "full", now)
            anchor = "full"
            _LOGGER.debug("BatterySocLearner: vol-anker via Zonneplan self_consumption")

        # ── SOC integreren ────────────────────────────────────────────────────
        cap = self._best_capacity(s)
        if cap and cap > 0 and s.anchor_ts > 0:
            wh_per_pct = (cap * 1000) / 100.0   # Wh per 1 %
            if new_dir == "charge":
                delta = (abs(power_w) * dt_h * EFF_CHARGE) / wh_per_pct
            elif new_dir == "discharge":
                delta = -(abs(power_w) * dt_h / EFF_DISCHARGE) / wh_per_pct
            else:
                delta = 0.0

            base = s.inferred_soc if s.inferred_soc is not None else s.anchor_soc
            s.inferred_soc = max(0.0, min(100.0, base + delta))

        return anchor

    # ── Intern: cyclus afsluiten ───────────────────────────────────────────────

    def _close_cycle(self, s: _State, expected_dir: str) -> None:
        if not s.cycle_active or s.cycle_dir != expected_dir:
            return
        wh = s.cycle_wh_acc
        kwh = wh / 1000.0
        if MIN_CAP_KWH <= kwh <= MAX_CAP_KWH:
            s.cycle_kwh_hist.append(round(kwh, 2))
            if len(s.cycle_kwh_hist) > 20:
                s.cycle_kwh_hist = s.cycle_kwh_hist[-20:]
            _LOGGER.info(
                "BatterySocLearner: capaciteitscyclus opgeslagen %.2f kWh "
                "(totaal %d cycli, mediaan %.2f kWh)",
                kwh,
                len(s.cycle_kwh_hist),
                median(s.cycle_kwh_hist),
            )
        s.cycle_active = False
        s.cycle_wh_acc = 0.0

    # ── Intern: anker zetten ──────────────────────────────────────────────────

    def _set_anchor(self, s: _State, soc: float, atype: str, now: float) -> None:
        s.anchor_soc   = soc
        s.anchor_ts    = now
        s.anchor_type  = atype
        s.inferred_soc = soc

    # ── Intern: beste capaciteitsschatting ────────────────────────────────────

    def _best_capacity(self, s: _State) -> Optional[float]:
        """
        Kies de beste capaciteitsschatting:
          1. Cyclus-mediaan  (methode B, prioriteit als ≥ MIN_CAP_CYCLES)
          2. Wh/SoC%-mediaan (methode A, met sensor)
          3. Vorige schatting (cached)
        """
        # Methode B
        if len(s.cycle_kwh_hist) >= MIN_CAP_CYCLES:
            cap = median(s.cycle_kwh_hist)
            if MIN_CAP_KWH <= cap <= MAX_CAP_KWH:
                s.est_capacity_kwh = round(cap, 2)
                return s.est_capacity_kwh

        # Methode A
        if len(s.wh_per_pct) >= MIN_CAP_SAMP:
            wh_per = median(s.wh_per_pct)
            cap = wh_per * 100.0 / 1000.0
            if MIN_CAP_KWH <= cap <= MAX_CAP_KWH:
                s.est_capacity_kwh = round(cap, 2)
                return s.est_capacity_kwh

        return s.est_capacity_kwh   # cached of None

    # ── Intern: definitieve SOC + confidence ──────────────────────────────────

    def _final_soc(
        self,
        s:       _State,
        soc_pct: Optional[float],
        power_w: Optional[float],
        cap:     Optional[float],
        now:     float,
    ) -> tuple[Optional[float], float, str]:
        """
        Geeft (soc, confidence, source) terug.
        """
        # Sensor aanwezig → direct gebruiken
        if soc_pct is not None:
            return soc_pct, 0.95, "sensor"

        # Inferentie: nog nooit een anker
        if s.inferred_soc is None:
            return None, 0.0, "unknown"

        # Confidence op basis van ankerstijd
        age_s = (now - s.anchor_ts) if s.anchor_ts > 0 else 99_999
        age_h = age_s / 3600.0

        if age_h <= 1.0:
            conf = 0.90
        elif age_h <= 4.0:
            t    = (age_h - 1.0) / 3.0
            conf = 0.90 + t * (CONF_4H - 0.90)
        elif age_h <= 12.0:
            t    = (age_h - 4.0) / 8.0
            conf = CONF_4H + t * (CONF_12H - CONF_4H)
        else:
            conf = CONF_12H

        # Geen capaciteit → extra onzeker
        if not cap or cap <= 0:
            conf = min(conf, 0.30)

        # Langdurig geen anker → drift richting 50 %
        soc = s.inferred_soc
        if conf <= CONF_12H and age_h > 24:
            soc = soc * 0.97 + 50.0 * 0.03
            s.inferred_soc = soc

        return soc, conf, "inferred"
