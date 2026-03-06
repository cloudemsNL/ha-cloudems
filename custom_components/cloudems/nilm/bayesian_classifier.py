# -*- coding: utf-8 -*-
"""
CloudEMS Bayesian NILM Classifier — v1.0.0

Voegt een echte Bayesiaanse laag toe bovenop de database-signatures.

Verschil met de bestaande contextpriors in HybridNILM:
────────────────────────────────────────────────────
De HybridNILM gebruikt losse multiplicatieve factoren (bijv. f *= 1.30 voor
warmtepomp bij kou). Dit is heuristisch en de factoren staan los van elkaar.

Deze module implementeert een proper Bayes-update:
  posterior ∝ likelihood × prior

  - Prior P(type): a priori kans dat een apparaat van dit type actief is,
    gegeven tijdstip + temperatuur + seizoen. Genormaliseerd over alle types.
  - Likelihood P(Δpower | type): kans dat we dit vermogen zien als dit type
    actief wordt. Gebaseerd op de Gaussische verdeling rond het signature-midden.
  - Posterior: de gecombineerde kans. Dit is de uiteindelijke confidence.

Voordelen boven de huidige aanpak:
  ✓ Priors zijn genormaliseerd → één boost gaat niet ten koste van anderen
  ✓ Likelihood is probabilistisch → zachter dan een harde bereikcheck
  ✓ Volledig uitschakelbaar zonder enig effect op andere lagen
  ✓ Online leren: prior-teliers worden bijgesteld na confirmed events

Veiligheidsmaatregelen:
  - Minimum prior = 0.05 (elk type blijft zichtbaar, nooit volledig geblokkeerd)
  - Maximum prior-boost = 5× baseline (nooit meer dan 5× meer kans dan gemiddeld)
  - Als de posterior lager is dan de originele confidence: originele wint
    (Bayesian laag kan alleen verbeteren, nooit verslechteren)
  - Per-hash deduplicatie: dezelfde Δpower binnen 2 s wordt niet twee keer geleerd

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
PRIOR_MIN          = 0.05   # nooit lager dan dit (elk type blijft bereikbaar)
PRIOR_MAX_BOOST    = 5.0    # nooit meer dan 5× gemiddeld a priori
LIKELIHOOD_SIGMA   = 0.30   # Gaussische breedte als fractie van het bereik
MIN_CONFIDENCE_WIN = 0.0    # Bayesian mag nooit lager dan originele confidence geven
LEARNING_RATE      = 0.15   # EMA-snelheid voor prior-update na confirmatie
DEDUP_WINDOW_S     = 2.0    # min. seconden tussen twee identieke leer-events

# ── Windrichting-effect ("bureneffect") ───────────────────────────────────────
# Bij koude oostenwind (continentale lucht) stijgt de vraag naar ruimteverwarming
# aanzienlijk. Dit verhoogt de a priori kans op warmtepomp, cv-ketel en
# elektrische verwarming — ook als de buitentemperatuur nog relatief mild is.
# Bronnen: KNMI windklimaat NL + Eurostat verwarmingsprofiel.
#
# Windrichting in graden (meteorologisch: 0° = Noord, 90° = Oost):
WIND_COLD_SECTOR_MIN   =  45   # koude sector: ONO t/m ZZO (warm pomp-boost)
WIND_COLD_SECTOR_MAX   = 135
WIND_COLD_BOOST_HP     = 1.35  # warmtepomp/cv-ketel boost bij koude aanvoer
WIND_COLD_BOOST_HEATER = 1.20
WIND_WARM_SECTOR_MIN   = 180   # warme sector: ZW t/m NW (minder verwarming)
WIND_WARM_SECTOR_MAX   = 270
WIND_WARM_PENALTY_HP   = 0.80  # warmtepomp iets minder kans bij SW-wind
WIND_SPEED_MIN_MS      =  3.0  # windeffect pas actief boven 3 m/s


# ── Device type prior tabel ───────────────────────────────────────────────────
# Basisprior P(type) — relatieve frequentie per uur en seizoen.
# Waarden zijn relatief t.o.v. elkaar (worden genormaliseerd).
# Bronnen: Eurostat huishoudverbruiksprofiel + eigen schattingen.

# BASE_PRIOR waarden zijn proportioneel aan P(apparaat aanwezig in NL huishouden)
# × P(apparaat actief op willekeurig moment).
# Zeldzame typen (power_tool, medical, garden) krijgen een zeer lage prior zodat
# zelfs een goede vermogensovereenkomst niet genoeg is zonder bevestiging.
# CBS NL 2022 bezitscijfers + WEEE data als bron.
BASE_PRIOR: Dict[str, float] = {
    "refrigerator":    1.8,   # 99% bezit × cycling ~30% → hoog
    "washing_machine": 0.6,   # 95% bezit
    "dryer":           0.4,   # 65% bezit
    "dishwasher":      0.5,   # 70% bezit
    "oven":            0.5,   # 90% bezit (fornuis/oven)
    "microwave":       0.5,   # 80% bezit
    "kettle":          0.6,   # 85% bezit
    "entertainment":   0.9,   # 95% bezit
    "computer":        0.7,   # 90% bezit
    "heat_pump":       0.4,   # 30% bezit, maar groot vermogen → verhoogd
    "boiler":          0.5,   # 80% bezit
    "ev_charger":      0.2,   # 15% bezit → laag
    "light":           1.0,   # 100% aanwezig
    "cv_boiler":       0.4,   # 70% bezit
    "electric_heater": 0.3,   # 60% bezit, seizoensgebonden
    "socket":          0.8,   # algemeen
    "unknown":         0.3,
    # Zeldzame / niche apparaten — bewust zeer laag
    "power_tool":      0.04,  # ~8% heeft gereedschap op net; zelden aan → 0.04
    "garden":          0.08,  # tuingereedschap seizoensgebonden + buitenstopcontact zeldzaam
    "medical":         0.02,  # CPAP, zuurstof etc. — niche
    "kitchen":         0.15,  # overige keukenapparatuur (broodmachine, sous vide)
}

# Tijdstip-gewichten — extra factor per uur (0–23) voor bepaalde types
# Formaat: device_type → list van 24 factoren (uur 0..23)
# Ontbrekende types = factor 1.0 voor alle uren

def _flat(v: float) -> List[float]:
    return [v] * 24

def _peak(low: float, high: float, peak_hours: tuple) -> List[float]:
    """Maak 24-uur profiel: low buiten peak_hours, high erbinnen."""
    return [high if h in peak_hours else low for h in range(24)]

HOURLY_WEIGHTS: Dict[str, List[float]] = {
    "kettle":          _peak(0.1, 1.5, (6,7,8,9,14,15,16,17)),
    "microwave":       _peak(0.1, 1.4, (7,8,9,12,13,14,17,18,19,20)),
    "washing_machine": _peak(0.2, 1.3, (6,7,8,9,10,11,18,19,20,21)),
    "dishwasher":      _peak(0.2, 1.4, (8,9,10,18,19,20,21,22)),
    "oven":            _peak(0.2, 1.5, (11,12,13,17,18,19,20,21)),
    "ev_charger":      _peak(0.5, 1.4, (0,1,2,3,4,5,6,18,19,20,21,22,23)),
    "light":           _peak(0.3, 1.5, (6,7,17,18,19,20,21,22,23)),
    "entertainment":   _peak(0.2, 1.5, (17,18,19,20,21,22,23)),
    "computer":        _peak(0.3, 1.3, (8,9,10,11,12,13,14,15,16,17,18,19,20,21)),
    "refrigerator":    _flat(1.0),
}

# Seizoen-gewichten per device type
SEASON_WEIGHTS: Dict[str, Dict[str, float]] = {
    "heat_pump":       {"winter": 1.6, "spring": 0.9, "summer": 1.2, "autumn": 1.1},
    "boiler":          {"winter": 1.4, "spring": 1.0, "summer": 0.6, "autumn": 1.1},
    "cv_boiler":       {"winter": 1.5, "spring": 0.8, "summer": 0.3, "autumn": 1.0},
    "electric_heater": {"winter": 1.5, "spring": 0.7, "summer": 0.1, "autumn": 0.9},
    "ev_charger":      {"winter": 1.1, "spring": 1.0, "summer": 0.9, "autumn": 1.0},
    "refrigerator":    {"winter": 0.9, "spring": 1.0, "summer": 1.1, "autumn": 1.0},
}


# ── Bayesian Classifier ───────────────────────────────────────────────────────

@dataclass
class BayesStats:
    """Leerstatistiek per apparaattype — voor online prior-update."""
    device_type:    str
    confirm_count:  int   = 0   # aantal keer bevestigd door gebruiker
    reject_count:   int   = 0   # aantal keer incorrect
    learned_prior:  float = 0.0 # geleerde prior-offset (0 = gebruik base)
    last_event_ts:  float = 0.0 # timestamp van laatste event (dedup)


class BayesianNILMClassifier:
    """
    Bayesiaanse post-processor voor NILM-matches.

    Gebruik:
        bayes = BayesianNILMClassifier()
        enriched = bayes.update_confidences(matches, delta_w, timestamp, temperature_c)

    Na een bevestiging door de gebruiker:
        bayes.on_confirmed(device_type, delta_w)
    """

    def __init__(self) -> None:
        self._stats: Dict[str, BayesStats] = {
            dt: BayesStats(device_type=dt)
            for dt in BASE_PRIOR
        }
        self._call_count  = 0
        self._boost_count = 0
        self._last_log_ts = 0.0

    # ── Hoofd-API ─────────────────────────────────────────────────────────────

    def update_confidences(
        self,
        matches:           List[dict],
        delta_w:           float,
        timestamp:         float,
        temperature_c:     float = 15.0,
        wind_direction_deg: Optional[float] = None,
        wind_speed_ms:     float = 0.0,
    ) -> List[dict]:
        """
        Pas Bayesiaanse posterior toe op een lijst NILM-matches.

        Voor elke match wordt de confidence bijgesteld op basis van:
          posterior ∝ likelihood(Δpower | type) × prior(type | context)

        Context omvat nu ook windrichting ("bureneffect"):
          - Koude oostenwind (45–135°) boost warmtepomp/cv-kansen.
          - Warme zuidwestenwind (180–270°) verlaagt ze licht.

        Veiligheid: als posterior < originele confidence → originele wint.
        Dus deze laag kan nooit matches *verslechteren*, alleen verbeteren.

        Returns: nieuwe matches-lijst, gesorteerd op confidence (hoog→laag).
        """
        if not matches:
            return matches

        self._call_count += 1
        priors = self._compute_priors(timestamp, temperature_c, wind_direction_deg, wind_speed_ms)
        abs_delta = abs(delta_w)

        out = []
        for m in matches:
            dt   = m.get("device_type", "unknown")
            orig = m["confidence"]

            # Likelihood: Gaussisch rondom het midden van het vermogensbereik
            p_min = float(m.get("power_min", abs_delta * 0.8))
            p_max = float(m.get("power_max", abs_delta * 1.2))
            likelihood = self._gaussian_likelihood(abs_delta, p_min, p_max)

            prior = priors.get(dt, 1.0 / len(priors))

            # Posterior (unnormalized) — we normaliseren later
            posterior_raw = likelihood * prior

            # Schaal zodat een "neutrale" prior+likelihood de originele confidence geeft
            # Door te normaliseren over alle matches behouden we relatieve verhoudingen
            out.append({**m, "_posterior_raw": posterior_raw, "_orig_conf": orig})

        # Normaliseer over alle matches
        total_raw = sum(x["_posterior_raw"] for x in out) or 1.0
        result = []
        for m in out:
            posterior_norm = m["_posterior_raw"] / total_raw
            # Schaal naar [0, 1] via lineaire mix: posterior vervangt originele conf
            # maar nooit lager dan origineel (veiligheidsregel)
            new_conf = max(m["_orig_conf"], min(1.0, posterior_norm * len(out)))
            if new_conf > m["_orig_conf"] + 0.01:
                self._boost_count += 1
            clean = {k: v for k, v in m.items()
                     if k not in ("_posterior_raw", "_orig_conf")}
            clean["confidence"]   = round(new_conf, 4)
            clean["bayes_prior"]  = round(priors.get(m.get("device_type",""), 1/len(priors)), 4)
            result.append(clean)

        result.sort(key=lambda x: x["confidence"], reverse=True)

        if time.time() - self._last_log_ts > 300:
            _LOGGER.debug(
                "BayesianNILM: %d calls, %d boosts (%.1f%%), top=%s %.0f%%",
                self._call_count, self._boost_count,
                100 * self._boost_count / max(self._call_count, 1),
                result[0].get("device_type") if result else "?",
                result[0]["confidence"] * 100 if result else 0,
            )
            self._last_log_ts = time.time()

        return result

    def on_confirmed(self, device_type: str, delta_w: float) -> None:
        """
        Meld een bevestigd apparaat — verhoog de geleerde prior voor dit type.
        Wordt aangeroepen vanuit NILMDetector.set_feedback(..., "correct").
        Deduplicatie: hetzelfde type binnen DEDUP_WINDOW_S wordt genegeerd.
        """
        stats = self._stats.setdefault(
            device_type, BayesStats(device_type=device_type)
        )
        now = time.time()
        if now - stats.last_event_ts < DEDUP_WINDOW_S:
            return
        stats.last_event_ts = now
        stats.confirm_count += 1
        # Verhoog geleerde prior via EMA (max PRIOR_MAX_BOOST - 1.0 offset)
        target = min(PRIOR_MAX_BOOST - 1.0, stats.confirm_count * 0.1)
        stats.learned_prior = round(
            LEARNING_RATE * target + (1 - LEARNING_RATE) * stats.learned_prior, 4
        )
        _LOGGER.debug(
            "BayesianNILM: prior voor %s verhoogd → +%.3f (bevestigd %d×)",
            device_type, stats.learned_prior, stats.confirm_count,
        )

    def on_rejected(self, device_type: str) -> None:
        """Meld een fout-positief — verlaag de geleerde prior."""
        stats = self._stats.setdefault(
            device_type, BayesStats(device_type=device_type)
        )
        stats.reject_count += 1
        target = max(-(1.0 - PRIOR_MIN), -stats.reject_count * 0.05)
        stats.learned_prior = round(
            LEARNING_RATE * target + (1 - LEARNING_RATE) * stats.learned_prior, 4
        )
        _LOGGER.debug(
            "BayesianNILM: prior voor %s verlaagd → %.3f (afgewezen %d×)",
            device_type, stats.learned_prior, stats.reject_count,
        )

    def get_diagnostics(self) -> dict:
        top_priors = sorted(
            [(dt, BASE_PRIOR.get(dt, 0.3) + s.learned_prior)
             for dt, s in self._stats.items()],
            key=lambda x: -x[1],
        )[:8]
        return {
            "calls_total":   self._call_count,
            "boosts_total":  self._boost_count,
            "boost_rate_pct": round(100 * self._boost_count / max(self._call_count, 1), 1),
            "wind_effect_enabled": True,
            "learned_stats": {
                dt: {
                    "confirmed":    s.confirm_count,
                    "rejected":     s.reject_count,
                    "learned_prior": s.learned_prior,
                }
                for dt, s in self._stats.items()
                if s.confirm_count > 0 or s.reject_count > 0
            },
            "top_priors_now": dict(top_priors),
        }

    # ── Interne methoden ──────────────────────────────────────────────────────

    def _compute_priors(
        self,
        timestamp:          float,
        temperature_c:      float,
        wind_direction_deg: Optional[float] = None,
        wind_speed_ms:      float = 0.0,
    ) -> Dict[str, float]:
        """
        Bereken genormaliseerde prior P(type) voor alle device types,
        gegeven tijdstip, seizoen, temperatuur en windrichting.
        """
        now    = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        hour   = now.hour
        month  = now.month
        season = (
            "winter" if month in (12, 1, 2) else
            "spring" if month in (3, 4, 5)  else
            "summer" if month in (6, 7, 8)  else
            "autumn"
        )

        # Temperatuurgewichten (warmtepomp/cv extra in de kou)
        temp_w: Dict[str, float] = {}
        if temperature_c < 5:
            temp_w["heat_pump"]       = 1.7
            temp_w["cv_boiler"]       = 1.6
            temp_w["boiler"]          = 1.3
            temp_w["electric_heater"] = 1.5
        elif temperature_c > 22:
            temp_w["heat_pump"]       = 1.3   # airco
            temp_w["refrigerator"]    = 1.2
        elif temperature_c > 15:
            temp_w["heat_pump"]       = 0.7

        # Windrichting-gewichten (bureneffect)
        wind_w: Dict[str, float] = {}
        if wind_direction_deg is not None and wind_speed_ms >= WIND_SPEED_MIN_MS:
            deg = wind_direction_deg % 360
            if WIND_COLD_SECTOR_MIN <= deg <= WIND_COLD_SECTOR_MAX:
                # Koude continentale lucht uit het oosten
                wind_w["heat_pump"]       = WIND_COLD_BOOST_HP
                wind_w["cv_boiler"]       = WIND_COLD_BOOST_HP
                wind_w["boiler"]          = WIND_COLD_BOOST_HP * 0.85
                wind_w["electric_heater"] = WIND_COLD_BOOST_HEATER
            elif WIND_WARM_SECTOR_MIN <= deg <= WIND_WARM_SECTOR_MAX:
                # Warme maritieme lucht uit het zuidwesten
                wind_w["heat_pump"]       = WIND_WARM_PENALTY_HP
                wind_w["cv_boiler"]       = WIND_WARM_PENALTY_HP
                wind_w["electric_heater"] = WIND_WARM_PENALTY_HP

        raw: Dict[str, float] = {}
        for dt, base in BASE_PRIOR.items():
            stats = self._stats.get(dt)
            learned = stats.learned_prior if stats else 0.0

            hourly  = HOURLY_WEIGHTS.get(dt, [1.0] * 24)[hour]
            season_f = SEASON_WEIGHTS.get(dt, {}).get(season, 1.0)
            temp_f   = temp_w.get(dt, 1.0)

            wind_f   = wind_w.get(dt, 1.0)
            p = (base + learned) * hourly * season_f * temp_f * wind_f
            p = max(PRIOR_MIN, min(base * PRIOR_MAX_BOOST, p))
            raw[dt] = p

        # Normaliseer → som = 1
        total = sum(raw.values()) or 1.0
        return {dt: p / total for dt, p in raw.items()}

    @staticmethod
    def _gaussian_likelihood(
        delta_w: float,
        power_min: float,
        power_max: float,
    ) -> float:
        """
        P(Δpower | type) via Gaussische verdeling rondom het bereiksmidden.
        Sigma = LIKELIHOOD_SIGMA × half-breedte, zodat de staarten zachter zijn
        dan de harde bereikgrenzen van de database.
        """
        mid    = (power_min + power_max) / 2.0
        half_w = max((power_max - power_min) / 2.0, 10.0)
        sigma  = half_w * LIKELIHOOD_SIGMA
        exponent = -((delta_w - mid) ** 2) / (2.0 * sigma ** 2)
        # Genormaliseerde Gaussiaan (max = 1 bij delta == mid)
        return math.exp(exponent)
