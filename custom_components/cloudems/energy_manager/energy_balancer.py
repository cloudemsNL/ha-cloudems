# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS EnergyBalancer — v4.5.66.

Garandeert een Kirchhoff-consistente energiebalans, ook als cloud-sensoren
traag zijn. Nieuw in v4.5.7: zelf-lerende vertraging-compensatie.

── Kernidee ──────────────────────────────────────────────────────────────────
Cloud-batterij-APIs (Solarman, SolarEdge, Enphase, Growatt …) pollen hun
inverter/BMS eens per N seconden. Die N is per installatie anders en onbekend
van tevoren. Gevolg: als het net springt van 400W → 9400W (batterij start
laden), ziet CloudEMS dat direct via P1, maar de battery-sensor blijft nog
45s op 0W staan. Dat geeft een vals huisverbruik van 9400W.

Oplossing: meet de kruiscorrelatie tussen |Δgrid| en |Δbattery| over een
rollend venster, en leer zo de werkelijke vertraging van die specifieke
integratie. Na LAG_MIN_SAMPLES metingen wordt de geleerde vertraging gebruikt
om de battery-waarde te reconstrueren vanuit de ringbuffer.

Kirchhoff (altijd):
    house_w = solar_w + grid_w − battery_w      (battery+ = laden)

── Zelf-lerend model ─────────────────────────────────────────────────────────
Per sensor-paar (grid→battery, grid→solar) wordt bijgehouden:
  - Een ringbuffer van (timestamp, waarde) per sensor
  - Bij een significante grid-sprong: zoek wanneer de andere sensor reageerde
  - Geleerde lag = gewogen mediaan van de laatste LAG_HISTORY_N observaties
  - Na voldoende data: haal de "echte" waarde op uit de ringbuffer op
    tijdstip (nu − lag), want dat is wat de cloud-sensor straks gaat melden
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# ── Constanten ────────────────────────────────────────────────────────────────
STALE_FACTOR        = 2.5
MIN_STALE_AGE_S     = 15.0
MAX_STALE_AGE_S     = 600.0

TREND_ALPHA         = 0.05   # fallback EMA (wordt overschreven door sensor-snelheid)
REF_INTERVAL_S      = 5.0    # referentie-interval: sneller = alpha→1.0, trager = lage alpha

LAG_WINDOW_MAX_S    = 300.0  # maximale te leren vertraging (5 min)
LAG_RINGBUF_S       = 360.0  # hoe lang tijdreeksen bewaren
LAG_STEP_S          = 5.0    # tijdstap voor cross-correlatie scan
LAG_MIN_SAMPLES     = 8      # min observaties voor vertrouwen
LAG_HISTORY_N       = 20     # bewaar laatste N lag-observaties
LAG_JUMP_THRESHOLD  = 200.0  # minimale sprong (W) om lag-detectie te triggeren
LAG_MATCH_THRESHOLD = 0.6    # fractie van grid-sprong die target moet volgen

KIRCHHOFF_TOL_W     = 50.0

# ── Battery bijsturing bij sterke afwijking (v4.6.545) ────────────────────────
# Grid heeft max ~10s vertraging (P1 direct), battery tot 5 minuten (cloud-API).
# Bij een Kirchhoff-imbalans is de sensor met de grootste geleerde lag de schuldige.
# We vervangen die volledig via Kirchhoff-inverse — geen blend, geen stale-timeout.
BATTERY_DRIFT_THRESHOLD_W  = 300.0  # W: imbalans groter dan dit → battery bijsturen

# ── Slimme battery-vs-PV discriminatie (v4.5.66) ─────────────────────────────
# PV-omvormers veranderen langzaam (wolken, zonshoek) — max typisch ~200 W/s.
# Batterijen kunnen in één stap springen: 0 → ±10 000 W in <1 update-cyclus.
# Als grid snel springt maar de battery-sensor (nog) niet meekome, is de kans
# groot dat de battery de veroorzaker is en dat de sensor achterloopt (cloud-lag).
# We onderscheiden dit door de ramp-rate van beide sensoren te vergelijken.
FAST_RAMP_W_S       = 500.0   # W/s: boven dit niveau = te snel voor PV
BATTERY_RAMP_FRAC   = 0.7     # grid-sprong moet voor >= 70% van battery komen
FAST_RAMP_CONF_MIN  = 0.3     # minimale lag-confidence voor fast-ramp inference



# ── Sprong-toedeling constanten (v5.5.48) ─────────────────────────────────────
JUMP_SIGMOID_THRESHOLD = 6000.0   # W: midden sigmoid (leerbaar) — oven+kookplaat ~5-6kW
JUMP_SIGMOID_SCALE     = 2500.0   # W: steilheid — geleidelijker overgang
JUMP_MIN_BAT_FRAC      = 0.0      # minimale fractie naar accu (kleine sprongen = 0%)
JUMP_MAX_BAT_FRAC      = 0.92     # maximale fractie naar accu
JUMP_LEARN_RATE        = 0.05     # hoe snel threshold leert
JUMP_MIN_LEARN_W       = 200.0    # minimale sprong om van te leren (v5.5.151)


class JumpAttribution:
    """Leert hoe grid-sprongen verdeeld worden over accu vs huis.

    Model: battery_fraction = sigmoid((|jump| - threshold) / scale)
    - Klein (500W):  ~20% accu — waarschijnlijk huis (koelkast, lamp)
    - Middel (3kW):  ~40% accu — kan inductie OF accu zijn
    - Groot (7kW):   ~80% accu — vrijwel zeker accu (Nexus cloud-lag)
    - Enorm (10kW):  ~92% accu — zeker accu

    Leerbaar: als Nexus na ~45s de echte waarde levert, vergelijken we
    de voorspelde verdeling met de werkelijkheid en passen threshold aan.
    """

    def __init__(self) -> None:
        self._threshold = JUMP_SIGMOID_THRESHOLD
        self._scale     = JUMP_SIGMOID_SCALE
        self._obs: list = []   # [(jump_w, predicted_frac, actual_frac)]
        self._n_learned = 0

    def battery_fraction(self, jump_w: float) -> float:
        """Fractie van grid-sprong toe te kennen aan accu (0.0-0.96).

        Zelf-lerend via sigmoid. Drempel en steilheid leren uit Nexus-feedback.
        Klein (<150W):  bijna zeker huis (lamp, standby) → 0% naar accu
        Middel (500W):  kan huis of accu zijn → geleerde sigmoid
        Groot (>3kW):   kan oven MAAR ook Nexus-lag → geleerde sigmoid
        Altijd:         huis krijgt (1-bat_frac), accu krijgt bat_frac
        """
        j = abs(jump_w)
        # Kleine sprongen zijn vrijwel altijd echt huisverbruik
        if j < 150:
            return 0.0   # huis krijgt alles
        import math
        x = (j - self._threshold) / max(self._scale, 100.0)
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        return max(0.0, min(JUMP_MAX_BAT_FRAC,
               sigmoid * JUMP_MAX_BAT_FRAC))

    def house_alpha_factor(self, jump_w: float) -> float:
        """Hoe veel house_alpha reduceren bij deze sprong (0=geen reductie, 1=volledig)."""
        return self.battery_fraction(jump_w)

    def learn(self, jump_w: float, predicted_bat_frac: float, actual_bat_delta_w: float) -> None:
        """Update threshold op basis van werkelijke verdeling na Nexus-aankomst.

        jump_w: grootte van de grid-sprong
        predicted_bat_frac: wat we voorspelden
        actual_bat_delta_w: hoeveel de accu werkelijk veranderde
        """
        if abs(jump_w) < 200.0 or abs(jump_w) < 1:
            return  # te klein om van te leren — is sowieso huis
        actual_frac = min(0.99, max(0.01, abs(actual_bat_delta_w) / abs(jump_w)))
        self._obs.append((abs(jump_w), predicted_bat_frac, actual_frac))
        self._obs = self._obs[-50:]  # bewaar laatste 50

        # Stuur threshold bij: als we te veel naar accu wezen → threshold omhoog
        error = actual_frac - predicted_bat_frac
        self._threshold -= error * JUMP_LEARN_RATE * abs(jump_w) / 1000.0
        self._threshold = max(1000.0, min(8000.0, self._threshold))
        self._n_learned += 1
        _LOGGER.debug(
            "JumpAttribution: geleerd jump=%.0fW pred=%.2f actual=%.2f "
            "error=%.2f → threshold=%.0fW",
            jump_w, predicted_bat_frac, actual_frac, error, self._threshold,
        )

    def to_dict(self) -> dict:
        return {
            "threshold_w": round(self._threshold, 0),
            "scale_w":     round(self._scale, 0),
            "n_learned":   self._n_learned,
        }

    def from_dict(self, d: dict) -> None:
        self._threshold = float(d.get("threshold_w", JUMP_SIGMOID_THRESHOLD))
        self._scale     = float(d.get("scale_w",     JUMP_SIGMOID_SCALE))
        self._n_learned = int(d.get("n_learned", 0))

# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class BalancedReading:
    """Kirchhoff-consistente energiebalans op één tijdstip.

    v5.5.49: twee sets waarden:
      *_w     — ruwe/gecorrigeerde waarden voor display
      *_ema_w — EMA-gefilterde waarden (~20s) voor beslissingen
    """
    grid_w:    float
    solar_w:   float
    battery_w: float   # positief=laden, negatief=ontladen
    house_w:   float   # altijd >= 0, altijd via Kirchhoff

    grid_estimated:    bool = False
    solar_estimated:   bool = False
    battery_estimated: bool = False

    imbalance_w:    float = 0.0
    stale_sensors:  list  = field(default_factory=list)
    lag_compensated: bool = False

    # v5.5.49: EMA waarden
    # display_*  (~5s)  — nauwelijks filter, geen geflicker
    # *_ema_w    (~20s) — beslissingen, pieken gesmoothed
    grid_display_w:    float = 0.0
    solar_display_w:   float = 0.0
    battery_display_w: float = 0.0
    house_display_w:   float = 0.0
    grid_ema_w:    float = 0.0
    solar_ema_w:   float = 0.0
    battery_ema_w: float = 0.0
    house_ema_w:   float = 0.0

    @property
    def import_w(self) -> float:
        return max(0.0, self.grid_w)

    @property
    def export_w(self) -> float:
        return max(0.0, -self.grid_w)


# ── Hulpklassen ───────────────────────────────────────────────────────────────

class _RingBuffer:
    """Tijdgestempelde ringbuffer: bewaar (ts, value) tot LAG_RINGBUF_S oud."""

    def __init__(self) -> None:
        self._buf: deque = deque()

    def push(self, value: float, ts: Optional[float] = None) -> None:
        t = ts or time.time()
        self._buf.append((t, value))
        cutoff = t - LAG_RINGBUF_S
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def at_time(self, ts: float) -> Optional[float]:
        """Geef de waarde die op tijdstip ts geldig was (meest recente <= ts)."""
        result = None
        for t, v in self._buf:
            if t <= ts:
                result = v
            else:
                break
        return result

    def delta_around(self, ts: float, window_s: float = 15.0) -> float:
        """Maximale absolute verandering in [ts-window_s, ts+window_s]."""
        vals = [v for t, v in self._buf if abs(t - ts) <= window_s]
        return abs(max(vals) - min(vals)) if len(vals) >= 2 else 0.0

    def __len__(self) -> int:
        return len(self._buf)


class _LagLearner:
    """Leert de vertraging tussen twee sensoren via cross-correlatie van sprongen."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._observations: deque = deque(maxlen=LAG_HISTORY_N)
        self._last_jump_ts: float = 0.0

    def observe(
        self,
        reference_buf: _RingBuffer,
        target_buf:    _RingBuffer,
        jump_ts:       float,
        jump_dw:       float,
    ) -> None:
        """Zoek op welk tijdstip target reageerde op een reference-sprong."""
        if jump_ts - self._last_jump_ts < 30.0:
            return  # te snel na vorige — debounce
        if abs(jump_dw) < LAG_JUMP_THRESHOLD:
            return

        target_ref = target_buf.at_time(jump_ts)
        if target_ref is None:
            return

        best_lag   = None
        best_match = 0.0

        lag = 0.0
        while lag <= LAG_WINDOW_MAX_S:
            check_ts   = jump_ts + lag
            target_val = target_buf.at_time(check_ts)
            if target_val is None:
                lag += LAG_STEP_S
                continue
            delta      = abs(target_val - target_ref)
            match_frac = min(1.0, delta / abs(jump_dw)) if jump_dw else 0.0
            if match_frac > best_match:
                best_match = match_frac
                best_lag   = lag
            lag += LAG_STEP_S

        if best_lag is not None and best_match >= LAG_MATCH_THRESHOLD:
            self._observations.append(best_lag)
            self._last_jump_ts = jump_ts
            _LOGGER.info(
                "LagLearner[%s]: grid-sprong %.0fW → reactie na %.0fs "
                "(match=%.0f%%) n=%d mediaan=%.0fs",
                self.name, jump_dw, best_lag, best_match * 100,
                len(self._observations),
                median(self._observations) if self._observations else 0,
            )

    @property
    def learned_lag_s(self) -> Optional[float]:
        if len(self._observations) < LAG_MIN_SAMPLES:
            return None
        return median(self._observations)

    @property
    def confidence(self) -> float:
        return min(1.0, len(self._observations) / LAG_HISTORY_N)

    def to_dict(self) -> dict:
        return {
            "observations":  list(self._observations),
            "learned_lag_s": self.learned_lag_s,
            "confidence":    round(self.confidence, 2),
        }

    def from_dict(self, d: dict) -> None:
        obs = d.get("observations", [])
        self._observations = deque(obs[-LAG_HISTORY_N:], maxlen=LAG_HISTORY_N)


# ── EMA tijdconstantes (v5.5.49) ────────────────────────────────────────────
EMA_TAU_DISPLAY_S  =  5.0  # display: lichte filter, nauwelijks merkbaar
EMA_TAU_DECISION_S = 20.0  # beslissingen: stabiel, geen pieken
                           # alpha = dt / (tau + dt)
                           # display:   dt=10s, tau=5s  → alpha=0.67
                           # beslissen: dt=10s, tau=20s → alpha=0.33

class _SensorTracker:
    """Volgt één sensor: ruwe waarde, interval, EMA, trend, staleness, ringbuffer.

    v5.5.49: Twee waarden per sensor:
      last_value  — ruwe meting, voor display en lag-compensatie
      ema_value   — gefilterde EMA (~20s tijdconstante), voor beslissingen
    Beslissingen op EMA: stabieler, piekwaardes tellen minder mee.
    """

    __slots__ = ("last_value", "last_update_ts", "last_change_ts", "interval_ema",
                 "trend", "sample_count", "prev_value", "buf",
                 "ema_value", "display_ema", "_ema_init")

    def __init__(self, initial: float = 0.0) -> None:
        now = time.time()
        self.last_value:     float       = initial
        self.last_update_ts: float       = now
        self.last_change_ts: float       = now
        self.interval_ema:   float       = 10.0
        self.trend:          float       = initial
        self.ema_value:      float       = initial   # v5.5.49: beslissingen (~20s)
        self.display_ema:    float       = initial   # v5.5.49: display (~5s)
        self._ema_init:      bool        = False     # False = eerste sample
        self.sample_count:   int         = 0
        self.prev_value:     float       = initial
        self.buf:            _RingBuffer = _RingBuffer()

    def update(self, value: float) -> None:
        now = time.time()
        self.last_update_ts = now
        if abs(value - self.prev_value) > 5.0:
            elapsed = now - self.last_change_ts
            if 0.5 < elapsed < MAX_STALE_AGE_S:
                self.interval_ema = self.interval_ema * 0.85 + elapsed * 0.15
            self.last_change_ts = now
            self.prev_value     = value
        self.last_value = value
        self.sample_count += 1
        self.buf.push(value, now)
        self.trend = (TREND_ALPHA * value + (1.0 - TREND_ALPHA) * self.trend
                      if self.sample_count > 1 else value)
        # v5.5.49: twee EMA's — display (5s) en beslissingen (20s)
        _dt = max(1.0, self.interval_ema)
        _alpha_disp = _dt / (EMA_TAU_DISPLAY_S  + _dt)  # snel, nauwelijks merkbaar
        _alpha_decs = _dt / (EMA_TAU_DECISION_S + _dt)  # traag, pieken gesmoothed
        if not self._ema_init:
            self.ema_value   = value
            self.display_ema = value
            self._ema_init   = True
        else:
            self.ema_value   = _alpha_decs * value + (1.0 - _alpha_decs) * self.ema_value
            self.display_ema = _alpha_disp * value + (1.0 - _alpha_disp) * self.display_ema

    def is_stale(self) -> bool:
        # last_update_ts: elke update() → sensor is actief zolang updates binnenkomen
        # last_change_ts: alleen bij waarde-wijziging → voor interval-leren
        # Stale = geen update() aanroepen gehad (sensor offline/geen data)
        age = time.time() - self.last_update_ts
        if age < MIN_STALE_AGE_S:
            return False
        if age > MAX_STALE_AGE_S:
            return True
        return age > self.interval_ema * STALE_FACTOR

    @property
    def alpha(self) -> float:
        """EMA alpha op basis van geleerd update-interval.

        Snelle sensor (1s) → alpha=1.0 → ruwe waarde, geen smoothing.
        Langzame sensor (45s) → alpha=0.11 → stevige smoothing.
        Formule: min(1.0, REF_INTERVAL_S / interval_ema)
        """
        return min(1.0, REF_INTERVAL_S / max(self.interval_ema, 0.1))


# ── Hoofdklasse ───────────────────────────────────────────────────────────────

class EnergyBalancer:
    """Kirchhoff-balancer met zelf-lerende vertraging-compensatie.

    Elke coordinator-cyclus (~10s):
      1. Update sensor-trackers met ruwe waarden
      2. Detecteer grid-sprongen → trigger lag-leren voor battery en solar
      3. Stale sensor → lag-compensatie vanuit ringbuffer (bij geleerde lag)
         of Kirchhoff-schatting via house_trend (bij onvoldoende data)
      4. house_w = solar + grid − battery  (altijd, nooit via sensor)
    """

    def __init__(self) -> None:
        self._grid    = _SensorTracker()
        self._solar   = _SensorTracker()
        self._battery = _SensorTracker()

        self._lag_battery = _LagLearner("battery")

        # v4.5.66: ramp-rate tracking voor battery-vs-PV discriminatie
        self._prev_grid_ts:      float = 0.0
        self._prev_battery_w:    float = 0.0
        self._prev_solar_w:      float = 0.0
        self._fast_ramp_active:  bool  = False
        self._fast_ramp_battery_est: Optional[float] = None
        self._fast_ramp_start_battery_w: float = 0.0
        self._fast_ramp_cycles: int = 0
        self._lag_solar   = _LagLearner("solar")

        self._house_trend:         float = 0.0
        self._house_trend_samples: int   = 0   # v4.6.548: teller voor opwarmperiode
        self._prev_grid_w:         float = 0.0
        self._last_grid_jump_w:    float = 0.0  # v5.5.47: laatste grid sprong
        self._last_grid_jump_ts:   float = 0.0  # timestamp van sprong
        self._bat_blend_ts:        float = 0.0  # timestamp Nexus waarde arriveert
        self._jump_attr = JumpAttribution()     # v5.5.48: leerbare sprong-toedeling
        self._pending_learn: list  = []         # [(ts, jump_w, pred_frac, bat_before)]
        self._last_balanced:       Optional[BalancedReading] = None
        self._imbalance_log_ts:    float = 0.0
        self._start_ts:            float = time.time()  # v4.6.548: voor opwarmguard
        # v5.5.290: geleerd maximum battery-vermogen (EMA van hoogste gemeten waarde)
        self._bat_max_charge_learned:    float = 0.0
        self._bat_max_discharge_learned: float = 0.0

    # ── Publieke interface ────────────────────────────────────────────────────

    def reconcile(
        self,
        grid_w:          Optional[float],
        solar_w:         Optional[float],
        battery_w:       Optional[float],
        confirmed_house_w: float = 0.0,   # v5.5.152: bevestigd huisverbruik via smart plugs
    ) -> BalancedReading:
        now = time.time()

        # 1. Update trackers
        if grid_w    is not None: self._grid.update(grid_w)
        if solar_w   is not None: self._solar.update(solar_w)
        if battery_w is not None: self._battery.update(battery_w)

        # 2. Detecteer grid-sprong → feed lag-learner + battery-vs-PV discriminatie
        g_now  = self._grid.last_value
        g_jump = g_now - self._prev_grid_w
        dt_s   = (now - self._prev_grid_ts) if self._prev_grid_ts > 0 else 10.0
        dt_s   = max(dt_s, 0.1)  # division guard

        if abs(g_jump) >= LAG_JUMP_THRESHOLD:
            self._lag_battery.observe(self._grid.buf, self._battery.buf, now, g_jump)
            self._lag_solar.observe(self._grid.buf, self._solar.buf, now, g_jump)
            # v5.5.48: onthoud sprong voor leerbare toedeling
            if abs(g_jump) >= 200.0:
                self._last_grid_jump_w  = g_jump
                self._last_grid_jump_ts = now
                # Plan een learn-check in na ~60s (als Nexus waarde arriveert)
                pred_frac = self._jump_attr.battery_fraction(g_jump)
                self._pending_learn.append({
                    "ts":       now,
                    "jump_w":   g_jump,
                    "pred_frac": pred_frac,
                    "bat_before": self._battery.last_value,
                })
                self._pending_learn = self._pending_learn[-10:]

            # v4.5.66: battery-vs-PV discriminatie via ramp-rate
            # PV verandert langzaam (wolken/hoek: typisch <100 W/s).
            # Batterijen slaan op/ontladen in één stap (0→±10 000 W in <1 cyclus).
            # → Als grid-sprong > FAST_RAMP_W_S én battery-sensor nog niet reageerde:
            #   infereer battery = grid-jump (minus geschatte solar-bijdrage).
            grid_ramp_ws = abs(g_jump) / dt_s
            b_delta = abs(self._battery.last_value - self._prev_battery_w)
            s_delta = abs(self._solar.last_value   - self._prev_solar_w)

            if False:  # v4.6.543: fast-ramp uitgeschakeld — veroorzaakte 10+ MW vals bij herstart
                pass  # Lag-compensatie via _LagLearner + stale-detectie doet hetzelfde veiliger
            if False and (grid_ramp_ws >= FAST_RAMP_W_S
                    and b_delta < abs(g_jump) * 0.3):   # disabled
                # Solar kan maximaal langzaam veranderd zijn — alles wat sneller is dan PV
                # gaat naar de battery.
                max_solar_delta = self._solar.last_value * 0.15  # 15% max PV-variatie per stap
                _inferred_bat = g_jump - min(s_delta, max_solar_delta)
                _est = self._battery.last_value + _inferred_bat
                # v4.6.542: hard cap — nooit meer dan 2x grid_w (fysisch onmogelijk)
                self._fast_ramp_battery_est = min(_est, abs(g_now) * 2.0)
                self._fast_ramp_start_battery_w = self._battery.last_value
                self._fast_ramp_active = True
                _LOGGER.debug(
                    "EnergyBalancer: snelle grid-ramp %.0fW/s (%.0fW in %.1fs) → "
                    "battery inferentie %.0fW (sensor=%.0fW, lag nog niet geleerd)",
                    grid_ramp_ws, g_jump, dt_s,
                    self._fast_ramp_battery_est,
                    self._battery.last_value,
                )
            else:
                # Geen snelle ramp of battery reageerde al → reset inferentie
                self._fast_ramp_active = False
                self._fast_ramp_battery_est = None

        else:
            # Kleine of geen sprong — als ramp-inferentie actief was, reset na één stap
            # zodra de battery-sensor een waarde stuurt of bewogen is.
            # v4.6.542: eenvoudige veilige reset — vermijdt vastzetten bij herstart.
            if self._fast_ramp_active:
                b_delta = abs(self._battery.last_value - self._prev_battery_w)
                if b_delta > abs(g_jump) * 0.5 or battery_w is not None:
                    self._fast_ramp_active = False
                    self._fast_ramp_battery_est = None

        self._prev_grid_w     = g_now
        self._prev_grid_ts    = now
        self._prev_battery_w  = self._battery.last_value
        self._prev_solar_w    = self._solar.last_value

        # 3. Staleness
        g_stale = self._grid.is_stale()
        s_stale = self._solar.is_stale()
        b_stale = self._battery.is_stale()
        # v5.5.290: leer max battery-vermogen uit gemeten waarden
        if battery_w is not None and not b_stale:
            _bw = float(battery_w)
            if _bw > 0 and _bw > self._bat_max_charge_learned:
                self._bat_max_charge_learned = max(
                    self._bat_max_charge_learned * 0.99 + _bw * 0.01, _bw)
            elif _bw < 0 and abs(_bw) > self._bat_max_discharge_learned:
                self._bat_max_discharge_learned = max(
                    self._bat_max_discharge_learned * 0.99 + abs(_bw) * 0.01, abs(_bw))
        stale   = (["grid"]    if g_stale else []) + \
                  (["solar"]   if s_stale else []) + \
                  (["battery"] if b_stale else [])

        g_val = self._grid.last_value
        s_val = self._solar.last_value
        b_val = self._battery.last_value
        g_est = s_est = b_est = False
        lag_comp = False

        # 4. Compenseer stale sensoren
        # v4.5.66: battery fast-ramp inferentie heeft prioriteit boven lag-compensatie
        # als battery-sensor nog niet reageerde op een snelle grid-sprong.
        if b_stale or (self._fast_ramp_active and self._fast_ramp_battery_est is not None):
            if (self._fast_ramp_active
                    and self._fast_ramp_battery_est is not None
                    and not b_stale):
                # Sensor is niet stale maar loopt achter door cloud-lag na snelle sprong
                b_val = self._fast_ramp_battery_est
                b_est = True
                lag_comp = True
                _LOGGER.debug(
                    "EnergyBalancer: fast-ramp battery-inferentie toegepast: %.0fW",
                    b_val,
                )
            else:
                b_val, b_est, b_lag = self._compensate(
                    self._battery, self._lag_battery,
                    g_val, s_val, "battery", now)
                # Verfijn met fast-ramp schatting als die beschikbaar is en lag onzeker
                if (self._fast_ramp_active
                        and self._fast_ramp_battery_est is not None
                        and self._lag_battery.confidence < FAST_RAMP_CONF_MIN):
                    b_val = self._fast_ramp_battery_est
                lag_comp = lag_comp or b_lag

        if s_stale:
            raw_s, s_est, s_lag = self._compensate(
                self._solar, self._lag_solar,
                g_val, b_val, "solar", now)
            s_val = max(0.0, raw_s)
            lag_comp = lag_comp or s_lag

        if g_stale:
            g_val = self._house_trend + b_val - s_val
            g_est = True

        # v4.6.548: Proactieve battery bijsturing bij Kirchhoff-imbalans
        #
        # Principe: grid heeft max ~10s vertraging (P1 direct).
        #           battery kan tot 5 minuten achterlopen (cloud-API, Zonneplan Nexus).
        #           Bij een grote imbalans wijzen we altijd de sensor met de grootste
        #           geleerde lag aan als schuldige en vervangen die volledig via
        #           Kirchhoff-inverse — geen blend, geen wachten op stale-timeout.
        #
        # Kirchhoff:  battery_kirchhoff = solar + grid - house_trend
        # Imbalans:   |battery_sensor - battery_kirchhoff| > BATTERY_DRIFT_THRESHOLD_W
        #
        # We corrigeren alleen als:
        #   1. Battery niet al stale of geschat is (dan regelt de compensator het al)
        #   2. house_trend voldoende opgewarmd is (>= 30 samples ≈ 5 min)
        #   3. De battery-lag groter is dan de grid-lag (structureel de traagste)
        #
        # Opwarmguard (v4.6.548): bij een verse herstart is house_trend=0 of gebaseerd
        # op slechts enkele samples. De drift-correctie zou dan een lege trend als anker
        # gebruiken en een verkeerde battery-waarde berekenen (zie 5.30kW/6.80kW bug).
        # Battery altijd via Kirchhoff als meting ouder is dan 10s en trend warm.
        # Nexus is de traagste sensor (~45s) — bereken zodra de waarde niet meer vers is.
        # Opwarmguard: >= 30 samples (~5 min) voorkomt opstartfouten met lege house_trend.
        _trend_warm    = self._house_trend_samples >= 30
        # last_change_ts = leeftijd van de waarde zelf (niet wanneer sensor voor het laatst leefde)
        # Nexus stuurt ook updates als waarde niet verandert → last_update_ts is altijd jong
        _battery_age_s = now - self._battery.last_change_ts

        # Snelle export-detectie: als grid sterk negatief is (export) en solar bekend,
        # kan extra export ALLEEN van de batterij komen — direct Kirchhoff zonder wachten.
        # Bij laden is dit niet veilig (oven/inductie kan grid positief maken).
        # Drempel: export > solar + 500W → verschil is te groot voor huis-variatie.
        _large_export = g_val < -500.0 and not self._grid.is_stale()
        _solar_known  = not self._solar.is_stale() and s_val >= 0.0
        _export_exceeds_solar = _large_export and _solar_known and (-g_val) > (s_val + 500.0)

        # v5.5.46: EXPORT-DIRECT fix
        # Vroegere versie: vervang batterij door Kirchhoff-van-house_trend bij export.
        # Bug: als house_trend verouderd is (bijv. 8840W terwijl huis nu 2572W is)
        # geeft dat een onmogelijke batterijwaarde (-15898W) → circulaire fout.
        # Correct: als batterijsensor vers is EN export > solar → vertrouw sensor,
        # bereken house via Kirchhoff vanuit sensor (niet andersom).
        if not b_est and _export_exceeds_solar and _battery_age_s < 30.0:
            # Batterij vers + grote export → sensor is leidend, house volgt
            _house_kirchhoff = s_val + g_val - b_val
            if _house_kirchhoff >= 0:
                # Plausibel: gebruik sensor b_val, house via Kirchhoff
                _LOGGER.debug(
                    "EnergyBalancer: EXPORT-DIRECT sensor-leidend "
                    "(grid=%.0fW solar=%.0fW bat=%.0fW → house=%.0fW)",
                    g_val, s_val, b_val, _house_kirchhoff,
                )
                # b_val blijft ongewijzigd, house_w wordt via Kirchhoff berekend
                pass  # geen b_est — sensor is leidend
            # Anders (negatief huis): val door naar trend-gebaseerde schatting

        if not b_est and _trend_warm and _export_exceeds_solar and _battery_age_s >= 30.0:
            # Batterij oud (stale) + grote export → schat via Kirchhoff van trend
            kirchhoff_battery = s_val + g_val - self._house_trend
            _LOGGER.debug(
                "EnergyBalancer: battery Kirchhoff EXPORT-STALE (grid=%.0fW solar=%.0fW kirchhoff=%.0fW)",
                g_val, s_val, kirchhoff_battery,
            )
            b_val    = kirchhoff_battery
            b_est    = True
            lag_comp = True

        if not b_est and self._house_trend > 0 and _trend_warm and _battery_age_s > 30.0:
            # v5.5.47: Batterij stale → schat via stabiele house_trend
            # house_trend is nu bewust NIET geboost bij sprongen →
            # betrouwbaar anker voor battery-schatting
            kirchhoff_battery = s_val + g_val - self._house_trend
            _LOGGER.debug(
                "EnergyBalancer: battery Kirchhoff (age=%.0fs sensor=%.0fW kirchhoff=%.0fW)",
                _battery_age_s, b_val, kirchhoff_battery,
            )
            b_val    = kirchhoff_battery
            b_est    = True
            lag_comp = True

        # v5.5.110: Solar wordt NOOIT gecorrigeerd of geïnfereerd.
        # Solar (PV) is na grid de betrouwbaarste waarde — de zon gaat niet
        # plotseling aan of uit, en de sensor-waarde is al EMA-gefilterd.
        # Als solar=0 en grid exporteert, dan klopt de BATTERIJ niet.
        # Kirchhoff lost dat automatisch op in de battery-schatting hieronder.
        # (Verwijderd: v4.5.61 solar-inferentie die fundamenteel fout was)

        # 5. Kirchhoff → house (nooit negatief)
        house_w_raw = s_val + g_val - b_val

        # Spike-filter: onrealistische house_w afkappen maar som=0 bewaren
        # door battery bij te stellen zodat solar + grid - battery = house altijd klopt.
        if self._house_trend and self._house_trend > 0:
            if house_w_raw < 0:
                # Negatief: race-condition — corrigeer battery zodat house = trend
                house_w = max(0.0, self._house_trend)
                b_val   = s_val + g_val - house_w   # som=0
                b_est   = True
            elif house_w_raw > max(15000.0, self._house_trend * 5):
                # Extreme spike: corrigeer battery zodat house = trend
                house_w = self._house_trend
                b_val   = s_val + g_val - house_w   # som=0
                b_est   = True
                _LOGGER.debug(
                    "EnergyBalancer: house_w spike %.0fW → trend %.0fW (battery bijgesteld naar %.0fW)",
                    house_w_raw, house_w, b_val
                )
            else:
                house_w = max(0.0, house_w_raw)
        else:
            house_w = max(0.0, house_w_raw)

        # v5.5.47: House trend — altijd langzame EMA, nooit boosten bij sprongen.
        # Principe: huis (thermische lasten) kan nooit 7kW+ springen in 10s.
        # Een grote grid-sprong is bijna altijd de accu (Nexus cloud-lag ~45s).
        # Bij boosten van house_alpha volgt huis de sprong → Kirchhoff geeft fout beeld.
        # Fix: bij grote grid sprong → house_alpha minimaliseren zodat huis EMA stabiel blijft.
        # Battery = solar + grid - house_ema → altijd Kirchhoff=0, accu krijgt de sprong.
        _a_grid  = self._grid.alpha
        _a_solar = self._solar.alpha
        _a_bat   = self._battery.alpha
        _house_alpha = (_a_grid + _a_solar + _a_bat) / 3.0

        # v5.5.151: Zelf-lerend house_alpha op basis van sprong-grootte
        # Klein (<150W):  huis boost (bijna zeker echt verbruik) → snelle reactie
        # Middel/groot:   sigmoid verdeling geleerd uit Nexus-feedback
        # Altijd:         huis + accu display = Kirchhoff
        _jump_age_s = now - self._last_grid_jump_ts
        _bat_delta  = abs(b_val - self._prev_battery_w)
        _jump_w = self._last_grid_jump_w
        _dominant_jump = max(abs(_jump_w) if _jump_age_s < 60.0 else 0.0, _bat_delta)

        if _dominant_jump > 0:
            # NILM-correctie: als smart plugs een sprong bevestigen als huis,
            # verminder de "onverklaarde" sprong die naar accu zou gaan.
            # Voorbeeld: 2kW sprong, smart plug bevestigt 1.8kW inductie →
            #   onverklaarde rest = 200W → bat_frac op basis van 200W (laag)
            _confirmed_delta = min(_dominant_jump, max(0.0, confirmed_house_w))
            _unexplained_jump = max(0.0, _dominant_jump - _confirmed_delta)

            _bat_frac = self._jump_attr.battery_fraction(_unexplained_jump)

            if _dominant_jump < 150.0:
                # Kleine sprong: boost house_alpha — bijna zeker echt verbruik
                _house_alpha = min(1.0, _house_alpha * 2.5)
            elif _bat_frac > 0:
                # Verdeel proportioneel: huis krijgt (1-bat_frac), accu krijgt bat_frac
                # Altijd samen 0 (Kirchhoff): wat huis niet krijgt gaat naar accu display
                _house_alpha = _house_alpha * (1.0 - _bat_frac)
            _LOGGER.debug(
                "EnergyBalancer: jump=%.0fW confirmed=%.0fW unexplained=%.0fW "                "bat_frac=%.2f → house_alpha=%.3f",
                _dominant_jump, _confirmed_delta, _unexplained_jump,
                _bat_frac, _house_alpha,
            )

        # Leer van Nexus aankomst: als pending observaties > 60s oud zijn
        # en accu-sensor veranderd is → vergelijk met voorspelling
        _still_pending = []
        for _obs in self._pending_learn:
            _obs_age = now - _obs["ts"]
            if _obs_age > 45.0 and _obs_age < 120.0:
                # Nexus waarde is nu beschikbaar — leer van de werkelijke delta
                _actual_bat_delta = abs(self._battery.last_value - _obs["bat_before"])
                if _actual_bat_delta > 100.0:
                    self._jump_attr.learn(
                        _obs["jump_w"],
                        _obs["pred_frac"],
                        _actual_bat_delta,
                    )
            elif _obs_age <= 45.0:
                _still_pending.append(_obs)
        self._pending_learn = _still_pending
        # v5.5.288: opwarmperiode — hogere alpha zodat house_trend sneller convergeert.
        # Bij cold-start (weinig samples) is house_trend nog niet representatief.
        # Zonder dit blijft house_trend bevroren op lage cold-start waarde (~90W)
        # terwijl het werkelijke verbruik 1-2kW is → som nooit 0.
        if self._house_trend_samples < 30 and self._house_trend > 0:
            _cold_alpha = min(1.0, _house_alpha * 5.0)  # 5× sneller in opwarmperiode
            self._house_trend = _cold_alpha * house_w + (1.0 - _cold_alpha) * self._house_trend
        else:
            self._house_trend = (_house_alpha * house_w +
                                 (1.0 - _house_alpha) * self._house_trend
                                 if self._house_trend else house_w)
        self._house_trend_samples += 1

        # 6. Imbalans-check vs ruwe waarden
        imbalance = 0.0
        if grid_w is not None and solar_w is not None and battery_w is not None:
            raw_house = solar_w + grid_w - battery_w
            imbalance = abs(raw_house - house_w)
            if imbalance > KIRCHHOFF_TOL_W and now - self._imbalance_log_ts > 60:
                _LOGGER.debug(
                    "EnergyBalancer: imbalans %.0fW "
                    "(grid=%.0f solar=%.0f bat=%.0f → house_raw=%.0f house_bal=%.0f)",
                    imbalance, grid_w, solar_w, battery_w, raw_house, house_w,
                )
                self._imbalance_log_ts = now

        # v5.5.49: twee EMA sets
        # Display (~5s): nauwelijks filter, geen geflicker in UI
        _g_disp = self._grid.display_ema
        _s_disp = max(0.0, self._solar.display_ema)
        _g_fresh = not self._grid.is_stale()
        if b_est:
            # v5.5.297: fix house_display bevriezen bij Nexus-lag.
            #
            # Probleem: b_val is Kirchhoff-gecorrigeerd via house_trend.
            # Als we b_val gebruiken als display-battery, dan is:
            #   house_disp = solar_disp + grid_disp - b_val
            #              = solar_disp + grid_disp - (solar + grid - house_trend)
            #              = house_trend  (altijd, ongeacht grid-wijzigingen)
            # → house_display was wiskundig vastgepind op house_trend.
            #
            # Fix: gebruik battery.display_ema (de ruwe EMA van de batterijsensor)
            # voor de display-berekening, ook als b_est=True.
            # house_disp = solar_disp + grid_disp - battery.display_ema
            # → house volgt direct grid-wijzigingen, Kirchhoff=0 in display.
            # Beslissingen (house_ema) blijven via b_val (Kirchhoff-correct).
            #
            # Fallback als grid stale: val terug op house_trend (zoals eerder).
            if _g_fresh:
                # Battery EMA geeft de laatste bekende sensor-waarde terug
                # (EMA-init = sensor, daarna langzaam bijgewerkt).
                _b_disp = self._battery.display_ema
                _h_disp = max(0.0, _s_disp + _g_disp - _b_disp)
                # Spike-bescherming: nooit meer dan 3x house_trend of 15kW
                if self._house_trend > 0:
                    _h_disp = min(_h_disp, max(self._house_trend * 3.0, 15000.0))
                    _b_disp = _s_disp + _g_disp - _h_disp  # herbereken na clamp
            else:
                # Grid ook stale: val terug op house_trend als stabiel anker
                _h_disp = max(0.0, self._house_trend)
                _b_disp = _s_disp + _g_disp - _h_disp
        else:
            _b_disp = self._battery.display_ema
            _h_disp = max(0.0, _s_disp + _g_disp - _b_disp)
        # Beslissingen (~20s): stabiel, pieken gesmoothed
        _g_ema = self._grid.ema_value
        _s_ema = max(0.0, self._solar.ema_value)
        _b_ema = b_val if b_est else self._battery.ema_value
        _h_ema = max(0.0, _s_ema + _g_ema - _b_ema)

        result = BalancedReading(
            grid_w    = g_val,
            solar_w   = max(0.0, s_val),
            battery_w = b_val,
            house_w   = house_w,
            grid_estimated    = g_est,
            solar_estimated   = s_est,
            battery_estimated = b_est,
            imbalance_w       = round(imbalance, 1),
            stale_sensors     = stale,
            lag_compensated   = lag_comp,
            grid_display_w    = round(_g_disp, 1),
            solar_display_w   = round(_s_disp, 1),
            battery_display_w = round(_b_disp, 1),
            house_display_w   = round(_h_disp, 1),
            grid_ema_w    = round(_g_ema, 1),
            solar_ema_w   = round(_s_ema, 1),
            battery_ema_w = round(_b_ema, 1),
            house_ema_w   = round(_h_ema, 1),
        )
        self._last_balanced = result
        return result

    # ── Intern ───────────────────────────────────────────────────────────────

    def _compensate(
        self,
        tracker: _SensorTracker,
        learner: _LagLearner,
        anchor_a: float,  # grid_w
        anchor_b: float,  # solar (voor battery) of battery (voor solar)
        name: str,
        now: float,
    ) -> Tuple[float, bool, bool]:
        """Geef (geschatte_waarde, is_estimated, is_lag_compensated)."""

        lag = learner.learned_lag_s
        if lag is not None:
            # Kijk terug in ringbuffer: waarde van (nu - lag) seconden geleden
            # is de "echte" huidige waarde die de cloud nog niet heeft doorgegeven
            target_ts = now - lag
            historic  = tracker.buf.at_time(target_ts)
            if historic is not None:
                _LOGGER.debug(
                    "EnergyBalancer[%s]: lag-comp %.0fs → %.0fW "
                    "(sensor=%.0fW conf=%.0f%%)",
                    name, lag, historic, tracker.last_value,
                    learner.confidence * 100,
                )
                return historic, True, True

        # Nog geen geleerde lag of geen historisch punt: Kirchhoff
        if name == "battery":
            # battery = solar + grid - house_trend
            estimated = anchor_a + anchor_b - self._house_trend
        else:
            # solar = house_trend + battery - grid
            estimated = max(0.0, self._house_trend + anchor_b - anchor_a)

        _LOGGER.debug(
            "EnergyBalancer[%s]: Kirchhoff-schatting %.0fW (lag n=%d)",
            name, estimated, len(learner._observations),
        )
        return estimated, True, False

    # ── Persistentie ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Persisteer geleerde lag-waarden voor herstart."""
        return {
            "lag_battery": self._lag_battery.to_dict(),
            "lag_solar":   self._lag_solar.to_dict(),
            "house_trend": round(self._house_trend, 1),
        }

    def from_dict(self, d: dict) -> None:
        """Herstel na herstart — geen cold-start meer."""
        if "lag_battery" in d:
            self._lag_battery.from_dict(d["lag_battery"])
        if "lag_solar" in d:
            self._lag_solar.from_dict(d["lag_solar"])
        if "house_trend" in d:
            self._house_trend = float(d["house_trend"])
        _LOGGER.info(
            "EnergyBalancer hersteld: battery_lag=%s solar_lag=%s",
            self._lag_battery.learned_lag_s,
            self._lag_solar.learned_lag_s,
        )

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def get_learned_battery_lag_s(self) -> Optional[float]:
        """Geleerde vertraging (s) grid-sprong → battery-update.

        Geeft None als nog onvoldoende data (<5 observaties).
        NILM (BatteryUncertaintyTracker) gebruikt dit om het burst-masker
        automatisch te verlengen met de geleerde vertraging, zodat NILM nooit
        te vroeg een event accepteert terwijl de batterij nog 'inhalt'.
        """
        return self._lag_battery.learned_lag_s

    def get_last(self) -> Optional[BalancedReading]:
        return self._last_balanced

    def get_diagnostics(self) -> dict:
        bl = self._lag_battery
        sl = self._lag_solar
        return {
            "grid_interval_s":         round(self._grid.interval_ema, 1),
            "solar_interval_s":        round(self._solar.interval_ema, 1),
            "battery_interval_s":      round(self._battery.interval_ema, 1),
            "grid_stale":              self._grid.is_stale(),
            "solar_stale":             self._solar.is_stale(),
            "battery_stale":           self._battery.is_stale(),
            "jump_attribution":        self._jump_attr.to_dict(),
            "house_trend_w":           round(self._house_trend, 1),
            "house_trend_samples":     self._house_trend_samples,
            "drift_correction_active": self._house_trend_samples >= 30,
            "grid_trend_w":            round(self._grid.trend, 1),
            "solar_trend_w":           round(self._solar.trend, 1),
            "battery_trend_w":         round(self._battery.trend, 1),
            "battery_learned_lag_s":   bl.learned_lag_s,
            "battery_lag_confidence":  round(bl.confidence, 2),
            "battery_lag_samples":     len(bl._observations),
            "bat_max_charge_learned_w":    round(self._bat_max_charge_learned, 0),
            "bat_max_discharge_learned_w": round(self._bat_max_discharge_learned, 0),
            "solar_learned_lag_s":     sl.learned_lag_s,
            "solar_lag_confidence":    round(sl.confidence, 2),
            "solar_lag_samples":       len(sl._observations),
            "last_imbalance_w":        round(self._last_balanced.imbalance_w, 1) if self._last_balanced else 0.0,
            "stale_sensors":           self._last_balanced.stale_sensors if self._last_balanced else [],
            "lag_compensated":         self._last_balanced.lag_compensated if self._last_balanced else False,
            "fast_ramp_active":        self._fast_ramp_active,
            "fast_ramp_battery_est_w": round(self._fast_ramp_battery_est, 0) if self._fast_ramp_battery_est is not None else None,
            # Tooltip data: raw sensor waarden + leeftijd + estimated flag
            "battery_estimated":  self._last_balanced.battery_estimated if self._last_balanced else False,
            "battery_raw_w":      round(self._battery.last_value, 1),
            "solar_raw_w":        round(self._solar.last_value, 1),
            "grid_raw_w":         round(self._grid.last_value, 1),
            "battery_age_s":      round(time.time() - self._battery.last_update_ts, 1),
            "solar_age_s":        round(time.time() - self._solar.last_update_ts, 1),
            "grid_age_s":         round(time.time() - self._grid.last_update_ts, 1),
        }
