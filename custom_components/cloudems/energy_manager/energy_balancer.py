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


# ── Dataklassen ───────────────────────────────────────────────────────────────

@dataclass
class BalancedReading:
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


class _SensorTracker:
    """Volgt één sensor: ruwe waarde, interval, trend, staleness, ringbuffer."""

    __slots__ = ("last_value", "last_update_ts", "last_change_ts", "interval_ema",
                 "trend", "sample_count", "prev_value", "buf")

    def __init__(self, initial: float = 0.0) -> None:
        now = time.time()
        self.last_value:     float       = initial
        self.last_update_ts: float       = now   # versheid: elke update()
        self.last_change_ts: float       = now   # interval-leren: alleen bij waarde-wijziging
        self.interval_ema:   float       = 10.0
        self.trend:          float       = initial
        self.sample_count:   int         = 0
        self.prev_value:     float       = initial
        self.buf:            _RingBuffer = _RingBuffer()

    def update(self, value: float) -> None:
        now = time.time()
        self.last_update_ts = now   # sensor leeft: altijd bijwerken
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
        self._last_balanced:       Optional[BalancedReading] = None
        self._imbalance_log_ts:    float = 0.0
        self._start_ts:            float = time.time()  # v4.6.548: voor opwarmguard

    # ── Publieke interface ────────────────────────────────────────────────────

    def reconcile(
        self,
        grid_w:    Optional[float],
        solar_w:   Optional[float],
        battery_w: Optional[float],
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
        if not b_est and _trend_warm and _export_exceeds_solar:
            kirchhoff_battery = s_val + g_val - self._house_trend
            _LOGGER.debug(
                "EnergyBalancer: battery Kirchhoff EXPORT-DIRECT (grid=%.0fW solar=%.0fW kirchhoff=%.0fW)",
                g_val, s_val, kirchhoff_battery,
            )
            b_val    = kirchhoff_battery
            b_est    = True
            lag_comp = True

        if not b_est and self._house_trend > 0 and _trend_warm and _battery_age_s > 10.0:
            kirchhoff_battery = s_val + g_val - self._house_trend
            _LOGGER.debug(
                "EnergyBalancer: battery Kirchhoff (age=%.0fs sensor=%.0fW kirchhoff=%.0fW)",
                _battery_age_s, b_val, kirchhoff_battery,
            )
            b_val    = kirchhoff_battery
            b_est    = True
            lag_comp = True

        # v4.5.61 Fix: solar sensor rapporteert 0 terwijl grid sterk negatief is
        # (teruglevering zonder solar is fysiek onmogelijk tenzij accu leeg is).
        # Als grid < -500W én solar = 0 én solar is niet stale → sensor geeft
        # waarschijnlijk een false-zero. Infereer solar via Kirchhoff met house_trend
        # zodat house_w niet onterecht op 0 blijft staan.
        if s_val == 0.0 and not s_stale and g_val < -500.0 and b_val >= -100.0:
            _inferred_solar = max(0.0, self._house_trend - g_val + b_val)
            if _inferred_solar > 200.0:
                _LOGGER.debug(
                    "EnergyBalancer: solar=0 maar grid=%.0fW → infereer solar=%.0fW via Kirchhoff",
                    g_val, _inferred_solar,
                )
                s_val = _inferred_solar
                s_est = True

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

        # House trend bijhouden — alpha = gemiddelde van input-sensor alpha's
        # Snelle sensoren (P1, omvormer) trekken alpha omhoog → huis volgt sneller
        # Trage sensoren (Nexus) trekken alpha omlaag → meer smoothing
        _a_grid = self._grid.alpha
        _a_solar = self._solar.alpha
        _a_bat   = self._battery.alpha
        _house_alpha = (_a_grid + _a_solar + _a_bat) / 3.0

        # v5.5.13: bij grote verandering in batterij of grid → house_alpha boosten
        # Scenario 1: battery springt van 0 naar -9kW (Nexus ontladen gestart)
        # Scenario 2: grid stopt opeens met exporteren (export → 0) terwijl battery nog -9kW toont
        # Zonder boost: house_w spikt tijdelijk omdat trage battery.alpha nog niet bijgewerkt is
        _bat_delta  = abs(self._battery.trend - (b_val or 0))
        _grid_delta = abs(self._grid.trend    - (g_val or 0))
        _max_delta  = max(_bat_delta, _grid_delta)
        if _max_delta > 2000:
            # Schaal: 2kW = +6%, 9kW = +27% boost op house_alpha
            _boost = min(0.9, _max_delta / 10000.0)
            _house_alpha = min(1.0, _house_alpha + _boost * 0.3)
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
            "house_trend_w":           round(self._house_trend, 1),
            "house_trend_samples":     self._house_trend_samples,
            "drift_correction_active": self._house_trend_samples >= 30,
            "grid_trend_w":            round(self._grid.trend, 1),
            "solar_trend_w":           round(self._solar.trend, 1),
            "battery_trend_w":         round(self._battery.trend, 1),
            "battery_learned_lag_s":   bl.learned_lag_s,
            "battery_lag_confidence":  round(bl.confidence, 2),
            "battery_lag_samples":     len(bl._observations),
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
