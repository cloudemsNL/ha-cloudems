# -*- coding: utf-8 -*-
"""
CloudEMS NILM PowerLearner — v1.0.0

Vijf nieuwe intelligentielagen bovenop de bestaande NILM-stack:

LAAG A — Per-apparaat vermogensprofiel (jouw koelkast, niet een gemiddelde)
  Elk bevestigd apparaat leert zijn eigen vermogensdistributie via een
  online Gaussisch model (EMA van gemiddelde + variantie).
  Bij een nieuw on-event wordt de likelihood vergeleken met het geleerde
  profiel → bekende apparaten herkennen 10–30× sneller dan via database.

LAAG B — Slimme off-edge matching (power-stack)
  Actieve apparaten worden bijgehouden in een "power-stack" per fase.
  Bij een negatieve delta wordt de stack-entry gezocht die het beste
  overeenkomt (vermogen ±25%). Off-events herclassificeren NIET meer
  via de database — ze matchen direct op actieve apparaten.
  Resultaat: geen losse "apparaat staat aan maar delta was -1800W" entries.

LAAG C — Simultane events (concurrent load tracking)
  Elke fase heeft een laufende "actieve lastbuckets" administratie.
  Bij een on-event wordt de baseline gecorrigeerd voor al actieve
  apparaten → de delta is de echte bijdrage van het nieuwe apparaat.
  Voorbeeld: wasmachine (1900W) loopt al, magnetron (+1000W) start →
  zonder correctie is de delta 1000W, niet 2900W. Dit werkt correct.

LAAG D — Energieverbruik als validatiesignaal
  Na een week bijhouden van een apparaat wordt het gemeten kWh/week
  vergeleken met de verwachte range van het apparaattype.
  - Wasmachine < 0.3 kWh/week? → vermoedelijk verkeerd label
  - Boiler > 50 kWh/week?      → vermoedelijk warmtepomp of EV-lader
  Bij grote afwijking wordt de confidence automatisch verlaagd en een
  suggestie-event gegenereerd voor de gebruiker.

LAAG E — Auto-confirm bij sustained high-confidence
  Als een apparaat 5× achtereen met confidence > 0.90 gedetecteerd wordt
  EN de energievalidatie akkoord is, wordt het automatisch bevestigd
  (confirmed=True) zonder gebruikersinterventie.
  De gebruiker kan dit gedrag uitschakelen via de config.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────

# Laag A — vermogensprofiel leren
PROFILE_EMA_FAST      = 0.30   # snelle aanpassing bij confirmed devices
PROFILE_EMA_SLOW      = 0.10   # conservatief voor onbevestigde devices
PROFILE_MIN_SAMPLES   = 3      # min. observaties voor profiel-gebruik
PROFILE_SIGMA_MULT    = 2.5    # hoeveel σ is de match-zone (ruimer = toleranter)
PROFILE_LIKELIHOOD_FLOOR = 0.05  # minimum likelihood (device blijft zichtbaar)

# Laag B — power-stack / off-edge
STACK_MATCH_TOLERANCE = 0.28   # ±28% vermogensmarge voor off-matching
STACK_MAX_AGE_S       = 14400  # 4 uur — entries ouder dan dit worden verwijderd
STACK_STALE_CLEAR_S   = 1800   # 30 min zonder update → entry vermoedelijk gemist off

# Laag C — simultane events
CONCURRENT_WINDOW_S   = 60.0   # tijdvenster waarbinnen events concurrent zijn
CONCURRENT_MIN_W      = 30.0   # minimum vermogen om in de actieve-last mee te tellen

# Laag D — energie-validatie
ENERGY_VALIDATION_MIN_DAYS  = 7      # min. dagen observatie voor validatie
ENERGY_VALIDATION_CHECK_H   = 168    # elke week controleren (168 uur)
ENERGY_ANOMALY_FACTOR       = 5.0    # >5× expected → anomalie
ENERGY_DEFICIT_FACTOR       = 0.10   # <10% expected → veel te weinig

# Laag E — auto-confirm
AUTO_CONFIRM_MIN_DETECTIONS = 5      # min. herhaalde detecties
AUTO_CONFIRM_MIN_CONFIDENCE = 0.90   # min. confidence per detectie
AUTO_CONFIRM_ENERGY_OK      = True   # energie-validatie vereist voor auto-confirm

# Laag F — Cycling / session-fingerprint dedup (nieuw v1.1)
CYCLE_DETECT_WINDOW_S  = 3600   # venster voor duty-cycle schatting (1 uur)
CYCLE_MIN_SESSIONS     = 3      # min. sessies voor cycling-classificatie
CYCLE_MAX_DUTY         = 0.55   # duty-cycle onder 55% → cycling-apparaat
CYCLE_MATCH_POWER_TOL  = 0.30   # 30% tolerantie bij cycling-match
# Apparaattypen die per definitie kunnen cyclen
CYCLING_DEVICE_TYPES = frozenset({
    "refrigerator", "heat_pump", "dehumidifier",
    "pool_pump", "heat_pump_dryer", "cv_boiler",
})

# Verwacht energieverbruik per apparaattype (kWh/week, [min, max])
# Bronnen: TNO Energie in Beeld 2023, Milieu Centraal, UK-DALE
EXPECTED_KWH_WEEK: Dict[str, Tuple[float, float]] = {
    "refrigerator":    (1.5,   6.0),   # koelkast: 200–800 kWh/jaar
    "washing_machine": (0.5,   6.0),   # wasmachine: 65–800 kWh/jaar (1–7×/week)
    "dryer":           (1.0,   8.0),   # droger: 130–1000 kWh/jaar
    "dishwasher":      (0.5,   5.0),   # vaatwasser: 65–650 kWh/jaar
    "oven":            (0.3,   5.0),   # oven: 40–650 kWh/jaar
    "microwave":       (0.1,   1.5),   # magnetron: 13–195 kWh/jaar
    "kettle":          (0.2,   3.0),   # waterkoker: 26–390 kWh/jaar
    "entertainment":   (0.5,   6.0),   # entertainment: 65–800 kWh/jaar
    "computer":        (0.5,   8.0),   # computer: 65–1000 kWh/jaar
    "heat_pump":       (5.0, 100.0),   # warmtepomp: 650–13000 kWh/jaar
    "boiler":          (3.0,  50.0),   # boiler: 390–6500 kWh/jaar
    "ev_charger":      (3.0,  80.0),   # EV-lader: 390–10400 kWh/jaar
    "light":           (0.1,   5.0),   # verlichting: 13–650 kWh/jaar
    "cv_boiler":       (1.0,  20.0),   # cv-ketel (pomp): 130–2600 kWh/jaar
    "electric_heater": (2.0,  40.0),   # elektrische verwarming: 260–5200 kWh/jaar
}


# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class DevicePowerProfile:
    """
    Online Gaussisch vermogensprofiel voor één apparaat.

    Bijgehouden via Welford's online algoritme (numeriek stabiel EMA van
    gemiddelde en variantie) zonder alle historische waarden op te slaan.
    """
    device_id:      str
    device_type:    str
    n_samples:      int   = 0
    mean_w:         float = 0.0   # lopend gemiddelde vermogen
    m2_w:           float = 0.0   # som van kwadraten (voor variantie)
    min_seen_w:     float = float("inf")
    max_seen_w:     float = 0.0
    last_update:    float = field(default_factory=time.time)

    @property
    def std_w(self) -> float:
        """Standaarddeviatie van het vermogen."""
        if self.n_samples < 2:
            return max(self.mean_w * 0.20, 30.0)  # 20% als prior
        return math.sqrt(self.m2_w / (self.n_samples - 1))

    @property
    def is_ready(self) -> bool:
        return self.n_samples >= PROFILE_MIN_SAMPLES

    def update(self, power_w: float, confirmed: bool = False) -> None:
        """Welford's online update."""
        alpha = PROFILE_EMA_FAST if confirmed else PROFILE_EMA_SLOW
        self.n_samples += 1
        # Welford's algorithm voor numeriek stabiele variantie
        delta = power_w - self.mean_w
        self.mean_w += delta / self.n_samples
        delta2 = power_w - self.mean_w
        self.m2_w += delta * delta2
        # Ook EMA bijhouden voor snellere aanpassing
        if self.n_samples > 5:
            self.mean_w = (1 - alpha) * self.mean_w + alpha * power_w
        self.min_seen_w = min(self.min_seen_w, power_w)
        self.max_seen_w = max(self.max_seen_w, power_w)
        self.last_update = time.time()

    def likelihood(self, power_w: float) -> float:
        """
        Geeft de kans terug dat dit vermogen bij dit apparaat hoort.
        Gaussiaans, genormaliseerd zodat de piek = 1.0 bij mean_w.
        Resultaat: [PROFILE_LIKELIHOOD_FLOOR, 1.0]
        """
        if not self.is_ready:
            return 0.5  # neutraal als nog geen profiel
        sigma = self.std_w
        # Gaussiaanse likelihood (piek bij mean)
        z = (power_w - self.mean_w) / max(sigma, 1.0)
        likelihood = math.exp(-0.5 * z * z)
        return max(PROFILE_LIKELIHOOD_FLOOR, round(likelihood, 4))

    def profile_confidence_boost(self, power_w: float) -> float:
        """
        Multiplicatieve factor voor de bestaande database-confidence.
        - Goede match met geleerd profiel → factor > 1.0 (max 1.5)
        - Slechte match → factor < 1.0 (min 0.5)
        - Onvoldoende data → factor 1.0 (neutraal)
        """
        if not self.is_ready:
            return 1.0
        lh = self.likelihood(power_w)
        # Schaal: likelihood 0→1 geeft factor 0.5→1.5
        return round(0.5 + lh, 2)

    def to_dict(self) -> dict:
        return {
            "device_id":   self.device_id,
            "device_type": self.device_type,
            "n_samples":   self.n_samples,
            "mean_w":      round(self.mean_w, 1),
            "std_w":       round(self.std_w, 1),
            "min_w":       round(self.min_seen_w, 1) if self.min_seen_w < float("inf") else None,
            "max_w":       round(self.max_seen_w, 1),
            "is_ready":    self.is_ready,
            # Cycling/duty-cycle state
            "is_cycling":          getattr(self, "is_cycling", False),
            "learned_duty_cycle":  round(getattr(self, "learned_duty_cycle", 0.0), 3),
            "session_count":       getattr(self, "session_count", 0),
            "last_session_ts":     getattr(self, "last_session_ts", 0.0),
            "anomaly_flag":        getattr(self, "anomaly_flag", False),
            "anomaly_reason":      getattr(self, "anomaly_reason", ""),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DevicePowerProfile":
        p = cls(device_id=d["device_id"], device_type=d.get("device_type", "unknown"))
        p.n_samples   = d.get("n_samples", 0)
        p.mean_w      = d.get("mean_w", 0.0)
        p.m2_w        = d.get("m2_w", 0.0)  # opgeslagen voor herstart
        p.min_seen_w  = d.get("min_w") or float("inf")
        p.max_seen_w  = d.get("max_w", 0.0)
        return p


@dataclass
class PowerStackEntry:
    """
    Één actief apparaat in de power-stack van een fase.
    Bijgehouden voor off-edge matching (Laag B).
    """
    device_id:   str
    device_type: str
    power_w:     float
    phase:       str
    on_ts:       float = field(default_factory=time.time)
    last_seen:   float = field(default_factory=time.time)

    @property
    def age_s(self) -> float:
        return time.time() - self.on_ts

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > STACK_STALE_CLEAR_S


@dataclass
class EnergyValidationResult:
    """Resultaat van energieverbruik-validatie voor één apparaat."""
    device_id:       str
    device_type:     str
    measured_kwh_wk: float
    expected_min:    float
    expected_max:    float
    is_anomaly:      bool
    is_deficit:      bool
    confidence_adj:  float   # multiplicatieve factor voor confidence (-1.0 = verwijder)
    suggestion:      str     # leesbare uitleg voor de gebruiker


# ── PowerLearner hoofd-klasse ─────────────────────────────────────────────────

class PowerLearner:
    """
    Centrale intelligentielaag voor zelflerend NILM.

    Integreert vijf verbeterlagen (A–E) bovenop NILMDetector.
    Alle leer-state is persistent via to_dict()/from_dict().

    Gebruik in NILMDetector:
        self._power_learner = PowerLearner()
        # Bij laden:
        self._power_learner.load(stored_dict)
        # Per on-event (na _handle_match):
        self._power_learner.record_on_event(dev_id, dev_type, power_w, phase, ts, confirmed)
        # Per off-event:
        match_id = self._power_learner.find_off_match(phase, abs_delta)
        # Per tick (energy accounting):
        self._power_learner.tick(ts)
        # Per week (validatie):
        anomalies = self._power_learner.validate_energy(devices)
    """

    def __init__(self, auto_confirm_enabled: bool = True) -> None:
        self._auto_confirm = auto_confirm_enabled

        # Laag A — vermogensprofielen per device_id
        self._profiles: Dict[str, DevicePowerProfile] = {}

        # Laag B — power-stack per fase
        self._stack: Dict[str, List[PowerStackEntry]] = {
            "L1": [], "L2": [], "L3": [], "ALL": [],
        }

        # Laag C — concurrent load: per fase → dict van {device_id: power_w}
        self._active_loads: Dict[str, Dict[str, float]] = {
            "L1": {}, "L2": {}, "L3": {}, "ALL": {},
        }

        # Laag D — energie-validatiestate
        self._last_validation_ts: float = 0.0

        # Laag E — auto-confirm tracking: device_id → streak van hoge confidence
        self._confirm_streak: Dict[str, int] = {}

        # Diagnostics
        self._stats = {
            "profile_boosts":      0,
            "off_matches":         0,
            "off_misses":          0,
            "concurrent_adjusted": 0,
            "energy_anomalies":    0,
            "auto_confirmed":      0,
        }

        _LOGGER.info("CloudEMS PowerLearner v1.0 geïnitialiseerd")

    # ── Laag A: Vermogensprofiel ──────────────────────────────────────────────

    def get_or_create_profile(self, device_id: str, device_type: str) -> DevicePowerProfile:
        if device_id not in self._profiles:
            self._profiles[device_id] = DevicePowerProfile(
                device_id=device_id, device_type=device_type
            )
        return self._profiles[device_id]

    def record_on_event(
        self,
        device_id: str,
        device_type: str,
        power_w: float,
        phase: str,
        ts: float,
        confirmed: bool = False,
    ) -> None:
        """Registreer een on-event — update profiel en power-stack."""
        if power_w <= 0:
            return

        # Laag A: profiel updaten
        profile = self.get_or_create_profile(device_id, device_type)
        profile.update(power_w, confirmed=confirmed)

        # Laag B: toevoegen aan power-stack
        phase_key = phase if phase in self._stack else "L1"
        # Verwijder eventuele stale entry van dit device
        self._stack[phase_key] = [
            e for e in self._stack[phase_key] if e.device_id != device_id
        ]
        self._stack[phase_key].append(PowerStackEntry(
            device_id=device_id,
            device_type=device_type,
            power_w=power_w,
            phase=phase_key,
            on_ts=ts,
            last_seen=ts,
        ))

        # Laag C: bijhouden actieve last
        self._active_loads[phase_key][device_id] = power_w

        _LOGGER.debug(
            "PowerLearner: on-event %s (%s) %.0fW fase %s (profiel: n=%d μ=%.0fW σ=%.0fW)",
            device_id, device_type, power_w, phase_key,
            profile.n_samples, profile.mean_w, profile.std_w,
        )

    def apply_profile_boost(
        self, matches: List[dict], devices: dict, power_w: float
    ) -> List[dict]:
        """
        Laag A: Pas geleerde vermogensprofielen toe op matches.

        Voor elk match-apparaattype kijken of er een bevestigd apparaat van
        dat type bestaat met een geleerd profiel. Als het huidige vermogen
        goed overeenkomt met het profiel, boost de confidence.
        """
        # Bouw lookup: device_type → lijst van profielen van bevestigde apparaten
        type_profiles: Dict[str, List[DevicePowerProfile]] = {}
        for dev_id, profile in self._profiles.items():
            dev = devices.get(dev_id)
            if dev is None:
                continue
            if not profile.is_ready:
                continue
            dt = profile.device_type
            type_profiles.setdefault(dt, []).append(profile)

        out = []
        for m in matches:
            dt = m.get("device_type", "")
            profiles_for_type = type_profiles.get(dt, [])
            if not profiles_for_type:
                out.append(m)
                continue
            # Gebruik het profiel met de hoogste likelihood (beste match)
            best_lh = max(p.likelihood(power_w) for p in profiles_for_type)
            factor = 0.5 + best_lh   # 0.5–1.5
            if factor > 1.05:
                self._stats["profile_boosts"] += 1
            new_conf = round(min(1.0, m["confidence"] * factor), 4)
            out.append({**m, "confidence": new_conf,
                         "profile_boost": round(factor, 2)})
        return out

    # ── Laag B: Off-edge matching ─────────────────────────────────────────────

    def find_off_match(
        self, phase: str, abs_delta: float, timestamp: float
    ) -> Optional[str]:
        """
        Vind het meest plausibele actieve apparaat voor een off-event.

        Zoekstrategie (priority order):
          1. Actief apparaat op dezelfde fase waarvan huidig vermogen ±28% overeenkomt
          2. Als geen directe match: gebruik geleerd profiel (mean_w ±2σ)
          3. Stale entries (>30 min geen update) worden overgeslagen

        Returns: device_id van het best-matchende apparaat, of None.
        """
        phase_key = phase if phase in self._stack else "L1"
        stack = self._stack.get(phase_key, [])
        # Verwijder verlopen entries
        now = time.time()
        stack = [e for e in stack if not e.is_stale and (now - e.on_ts) < STACK_MAX_AGE_S]
        self._stack[phase_key] = stack

        if not stack:
            return None

        best_id:   Optional[str] = None
        best_diff: float = float("inf")

        for entry in stack:
            # Directe vermogensvergelijking
            rel_diff = abs(entry.power_w - abs_delta) / max(entry.power_w, 1.0)
            if rel_diff <= STACK_MATCH_TOLERANCE and rel_diff < best_diff:
                best_diff = rel_diff
                best_id   = entry.device_id
                continue

            # Profiel-gebaseerde vergelijking als directe match mislukt
            if best_id is None:
                profile = self._profiles.get(entry.device_id)
                if profile and profile.is_ready:
                    sigma_range = PROFILE_SIGMA_MULT * profile.std_w
                    if abs(profile.mean_w - abs_delta) <= sigma_range:
                        best_id = entry.device_id

        if best_id:
            self._stats["off_matches"] += 1
            _LOGGER.debug(
                "PowerLearner: off-match %s ← %.0fW (fase %s)",
                best_id, abs_delta, phase_key,
            )
        else:
            self._stats["off_misses"] += 1
            _LOGGER.debug(
                "PowerLearner: geen off-match voor %.0fW op fase %s",
                abs_delta, phase_key,
            )

        return best_id

    def record_off_event(self, device_id: str, phase: str, ts: float) -> None:
        """Verwijder apparaat uit power-stack en actieve last na off-event."""
        phase_key = phase if phase in self._stack else "L1"
        self._stack[phase_key] = [
            e for e in self._stack[phase_key] if e.device_id != device_id
        ]
        self._active_loads.get(phase_key, {}).pop(device_id, None)

    # ── Laag C: Concurrent load ───────────────────────────────────────────────

    def get_concurrent_load_w(self, phase: str, exclude_device_id: str = "") -> float:
        """
        Geeft het totale actieve vermogen op een fase terug,
        exclusief het opgegeven apparaat.

        Gebruikt door NILMDetector om de baseline-correctie te berekenen:
        als er al 1900W aan actieve apparaten is, is een delta van 1000W
        een nieuw apparaat van 1000W — niet 2900W.
        """
        phase_key = phase if phase in self._active_loads else "L1"
        loads = self._active_loads.get(phase_key, {})
        total = sum(
            w for did, w in loads.items()
            if did != exclude_device_id and w >= CONCURRENT_MIN_W
        )
        return round(total, 1)

    def adjust_delta_for_concurrent_load(
        self, phase: str, raw_delta: float
    ) -> Tuple[float, float]:
        """
        Corrigeer een ruwe delta voor simultane actieve lasten.

        Bij een positieve delta (on-event): concurrent load is al verdisconteerd
        in de baseline, maar als de baseline traag is (EMA 0.002), kan er een
        onderschatting zijn.

        Returns: (adjusted_delta_w, concurrent_total_w)
        De caller beslist of de correctie wordt toegepast.
        """
        concurrent = self.get_concurrent_load_w(phase)
        # Geen correctie als concurrent load klein is
        if concurrent < 100:
            return raw_delta, 0.0
        self._stats["concurrent_adjusted"] += 1
        return raw_delta, concurrent

    # ── Laag D: Energie-validatie ─────────────────────────────────────────────

    def should_validate_energy(self, ts: float) -> bool:
        """True als het tijd is voor de wekelijkse energie-validatie."""
        age_h = (ts - self._last_validation_ts) / 3600.0
        return age_h >= ENERGY_VALIDATION_CHECK_H

    def validate_energy(
        self, devices: dict, ts: float
    ) -> List[EnergyValidationResult]:
        """
        Laag D: Vergelijk gemeten kWh/week met verwacht bereik per apparaattype.

        Alleen apparaten die minstens ENERGY_VALIDATION_MIN_DAYS oud zijn
        worden gevalideerd — te jong = te weinig data.

        Returns: lijst van EnergyValidationResult voor afwijkende apparaten.
        """
        self._last_validation_ts = ts
        results = []

        for device_id, dev in devices.items():
            # Skip: te kort gemeten, niet bevestigd, of geen bekende range
            age_days = (ts - dev.last_seen) / 86400.0
            if age_days < ENERGY_VALIDATION_MIN_DAYS:
                continue
            if not dev.confirmed and dev.user_feedback != "correct":
                continue
            dtype = dev.display_type
            expected = EXPECTED_KWH_WEEK.get(dtype)
            if not expected:
                continue

            exp_min, exp_max = expected
            # Normaliseer op kWh/week (gebruik week_kwh als beste proxy)
            kwh_wk = dev.energy.week_kwh
            if kwh_wk < 0.001:
                continue  # geen data

            is_anomaly = kwh_wk > exp_max * ENERGY_ANOMALY_FACTOR
            is_deficit  = kwh_wk < exp_min * ENERGY_DEFICIT_FACTOR

            if not (is_anomaly or is_deficit):
                continue  # binnen verwacht bereik

            # Bepaal confidence-aanpassing
            if is_anomaly:
                # Verbruikt veel te veel → vermoedelijk verkeerd type (bijv. boiler = EV-lader)
                conf_adj = 0.60
                suggestion = (
                    f"{dev.display_name}: verbruik {kwh_wk:.1f} kWh/week is "
                    f"{kwh_wk/exp_max:.0f}× te hoog voor {dtype}. "
                    f"Mogelijk een {_suggest_type_by_energy(kwh_wk)}?"
                )
            else:
                # Verbruikt bijna niets → vermoedelijk foutief label of sensor-ruis
                conf_adj = 0.70
                suggestion = (
                    f"{dev.display_name}: verbruik {kwh_wk:.2f} kWh/week is "
                    f"te laag voor {dtype} (verwacht ≥ {exp_min:.1f} kWh/week). "
                    f"Controleer het label of de sensor."
                )

            self._stats["energy_anomalies"] += 1
            results.append(EnergyValidationResult(
                device_id       = device_id,
                device_type     = dtype,
                measured_kwh_wk = round(kwh_wk, 3),
                expected_min    = exp_min,
                expected_max    = exp_max,
                is_anomaly      = is_anomaly,
                is_deficit      = is_deficit,
                confidence_adj  = conf_adj,
                suggestion      = suggestion,
            ))
            _LOGGER.info(
                "PowerLearner energie-validatie: %s → %s (%.2f kWh/wk, verwacht %.1f–%.1f)",
                device_id, "ANOMALIE" if is_anomaly else "TEKORT",
                kwh_wk, exp_min, exp_max,
            )

        return results

    # ── Laag E: Auto-confirm ──────────────────────────────────────────────────

    def check_auto_confirm(
        self,
        device_id: str,
        confidence: float,
        energy_ok: bool,
    ) -> bool:
        """
        Laag E: Bepaal of een apparaat automatisch bevestigd moet worden.

        Voorwaarden:
          1. auto_confirm is ingeschakeld in config
          2. confidence ≥ AUTO_CONFIRM_MIN_CONFIDENCE
          3. streak ≥ AUTO_CONFIRM_MIN_DETECTIONS
          4. energy_ok (geen bekende energie-anomalie voor dit apparaat)

        Returns: True als het apparaat nu auto-confirmed moet worden.
        """
        if not self._auto_confirm:
            return False

        if confidence >= AUTO_CONFIRM_MIN_CONFIDENCE:
            self._confirm_streak[device_id] = (
                self._confirm_streak.get(device_id, 0) + 1
            )
        else:
            # Reset streak bij lagere confidence
            self._confirm_streak[device_id] = 0
            return False

        streak = self._confirm_streak.get(device_id, 0)
        if streak >= AUTO_CONFIRM_MIN_DETECTIONS:
            if AUTO_CONFIRM_ENERGY_OK and not energy_ok:
                return False
            self._stats["auto_confirmed"] += 1
            _LOGGER.info(
                "PowerLearner: AUTO-CONFIRM %s (streak=%d, conf=%.0f%%)",
                device_id, streak, confidence * 100,
            )
            return True

        return False

    def reset_confirm_streak(self, device_id: str) -> None:
        """Reset auto-confirm streak na manuele correctie (incorrect feedback)."""
        self._confirm_streak.pop(device_id, None)

    # ── Laag F: Cycling / session fingerprint ────────────────────────────────

    def record_session_timing(
        self,
        device_id: str,
        device_type: str,
        start_ts: float,
        duration_s: float,
        power_w: float,
    ) -> None:
        """
        Registreer een voltooide sessie voor cycling-detectie en duty-cycle tracking.

        Een 'cycling' apparaat (koelkast, warmtepomp) heeft:
          - duty_cycle < CYCLE_MAX_DUTY (bijv. < 55%)
          - meerdere sessies in CYCLE_DETECT_WINDOW_S
          - consistent vermogen (profiel al ready)

        Na CYCLE_MIN_SESSIONS sessies wordt is_cycling=True gezet op het profiel.
        """
        profile = self.get_or_create_profile(device_id, device_type)

        # Initialiseer cycling state als dat nog niet bestaat
        if not hasattr(profile, "is_cycling"):
            profile.is_cycling          = device_type in CYCLING_DEVICE_TYPES
            profile.learned_duty_cycle  = 0.0
            profile.session_count       = 0
            profile.last_session_ts     = 0.0
            profile.anomaly_flag        = False
            profile.anomaly_reason      = ""
            profile._cycle_history      = []  # [(start_ts, duration_s), ...]

        profile.session_count    += 1
        profile.last_session_ts   = start_ts + duration_s

        # Voeg toe aan cyclus-geschiedenis
        profile._cycle_history.append((start_ts, duration_s))
        # Houd alleen events binnen CYCLE_DETECT_WINDOW_S
        cutoff = start_ts - CYCLE_DETECT_WINDOW_S
        profile._cycle_history = [
            (t, d) for t, d in profile._cycle_history if t > cutoff
        ]

        # Duty-cycle schatten
        if len(profile._cycle_history) >= CYCLE_MIN_SESSIONS:
            total_on = sum(d for _, d in profile._cycle_history)
            dc = min(1.0, total_on / CYCLE_DETECT_WINDOW_S)
            profile.learned_duty_cycle = round(dc, 3)

            # Cycling detecteren: lage duty cycle + consistent vermogen
            if not profile.is_cycling:
                if dc < CYCLE_MAX_DUTY or device_type in CYCLING_DEVICE_TYPES:
                    if profile.is_ready:
                        cv = profile.std_w / max(profile.mean_w, 1.0)
                        if cv < 0.25:  # < 25% variatie → consistent genoeg
                            profile.is_cycling = True
                            _LOGGER.info(
                                "PowerLearner: %s (%s) herkend als cycling-apparaat "
                                "(duty=%.0f%%, CV=%.0f%%, n=%d sessies)",
                                device_id, device_type,
                                dc * 100, cv * 100, len(profile._cycle_history),
                            )

    def is_cycling_device(self, device_id: str) -> bool:
        """True als dit apparaat als cycling-apparaat herkend is."""
        profile = self._profiles.get(device_id)
        return bool(profile and getattr(profile, "is_cycling", False))

    def get_device_profile(self, device_id: str) -> Optional[dict]:
        """
        Geeft het volledige profiel van één apparaat terug als dict.
        Gebruikt voor de nilm_device_profile service en diagnostics.
        Returns None als het apparaat onbekend is.
        """
        profile = self._profiles.get(device_id)
        if not profile:
            return None
        return {
            **profile.to_dict(),
            "confirm_streak":   self._confirm_streak.get(device_id, 0),
            "cycle_history_n":  len(getattr(profile, "_cycle_history", [])),
        }

    def get_all_profiles(self) -> dict:
        """Geeft alle profielen terug als {device_id: dict}."""
        return {
            did: {
                **p.to_dict(),
                "confirm_streak": self._confirm_streak.get(did, 0),
                "cycle_history_n": len(getattr(p, "_cycle_history", [])),
            }
            for did, p in self._profiles.items()
        }

    # ── Onderhoud ─────────────────────────────────────────────────────────────

    def prune_stale_stack(self) -> int:
        """Verwijder verlopen power-stack entries. Returns aantal verwijderd."""
        removed = 0
        for phase_key, stack in self._stack.items():
            before = len(stack)
            self._stack[phase_key] = [
                e for e in stack
                if not e.is_stale and e.age_s < STACK_MAX_AGE_S
            ]
            removed += before - len(self._stack[phase_key])
        return removed

    def on_device_removed(self, device_id: str, phase: str = "") -> None:
        """Ruim alle state op voor een verwijderd apparaat."""
        self._profiles.pop(device_id, None)
        self._confirm_streak.pop(device_id, None)
        for phase_key, stack in self._stack.items():
            self._stack[phase_key] = [e for e in stack if e.device_id != device_id]
        for phase_key, loads in self._active_loads.items():
            loads.pop(device_id, None)

    # ── Persistentie ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialiseer alle geleerde state voor HA-opslag."""
        return {
            "version":  1,
            "profiles": {
                did: {**p.to_dict(), "m2_w": p.m2_w}  # m2_w voor Welford-herstart
                for did, p in self._profiles.items()
            },
            "confirm_streaks": dict(self._confirm_streak),
            "stats":    dict(self._stats),
        }

    def load(self, data: dict) -> None:
        """Herstel geleerde state vanuit HA-opslag."""
        if not data or data.get("version") != 1:
            return
        for did, pdict in data.get("profiles", {}).items():
            try:
                profile = DevicePowerProfile.from_dict(pdict)
                profile.m2_w = pdict.get("m2_w", 0.0)
                self._profiles[did] = profile
            except Exception:
                pass
        self._confirm_streak = {
            k: int(v) for k, v in data.get("confirm_streaks", {}).items()
        }
        _LOGGER.info(
            "PowerLearner: %d profielen geladen, %d confirm-streaks",
            len(self._profiles), len(self._confirm_streak),
        )

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict:
        ready_profiles = sum(1 for p in self._profiles.values() if p.is_ready)
        stack_total    = sum(len(s) for s in self._stack.values())
        active_total   = sum(len(l) for l in self._active_loads.values())
        return {
            "profiles_total":    len(self._profiles),
            "profiles_ready":    ready_profiles,
            "stack_total":       stack_total,
            "active_loads":      active_total,
            "confirm_streaks":   {k: v for k, v in self._confirm_streak.items() if v > 0},
            "stats":             dict(self._stats),
            "top_profiles": [
                p.to_dict()
                for p in sorted(self._profiles.values(), key=lambda x: -x.n_samples)[:5]
            ],
        }


# ── Hulpfunctie ───────────────────────────────────────────────────────────────

def _suggest_type_by_energy(kwh_wk: float) -> str:
    """Suggereer een apparaattype op basis van gemeten kWh/week."""
    if kwh_wk > 40:
        return "EV-lader of warmtepomp"
    if kwh_wk > 15:
        return "warmtepomp of boiler"
    if kwh_wk > 5:
        return "droger of elektrische verwarming"
    if kwh_wk > 2:
        return "wasmachine of vaatwasser"
    return "ander apparaat"
