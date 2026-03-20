"""
kirchhoff_drift_monitor.py — v4.6.531

Zelflerend, zelfcorrigerend Kirchhoff-consistentie monitor.

Kirchhoff: grid + solar - battery = house
(positief = import/productie/ontladen/verbruik)

Werking per cyclus:
  1. Ontvang ruwe waarden grid, solar, battery, house
  2. Bereken residueel per sensor (wat impliceert de rest over deze sensor?)
  3. Update EMA van residueel en correlatie met dP/dt per sensor
  4. Classificeer na MIN_SAMPLES: ok / offset / lag / sign_error / scale_error / frozen
  5. Bij hoog vertrouwen: pas correctiefactor toe (zelfcorrigerend)
  6. Bij drempeloverschrijding: emit hint via SensorHintEngine

Drie-tegen-één regel:
  Als drie sensoren consistent zijn en één afwijkt → die één corrigeren.
  Als twee tegen twee staan → alleen waarschuwen, niet corrigeren.

Classificatie logica:
  sign_error  : residueel ≈ -2 × gemeten waarde  (teken omgedraaid)
  scale_error : |residueel / gemeten| ≈ 999 of 0.001  (kW vs W factor ~1000)
  offset      : residueel constant, weinig correlatie met dP/dt
  lag         : residueel correleert sterk met dP/dt van die sensor
  frozen      : waarde verandert nooit ondanks variabele grid
  ok          : residueel klein t.o.v. totaalvermogen

Logging (decisions_history categorie: "kirchhoff_monitor"):
  - Elke classificatiewijziging
  - Elke correctie die toegepast wordt
  - Elke hint-emissie
  - Diagnostics snapshot elke 30 min

Persistentie: HA Storage cloudems_kirchhoff_monitor_v1
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_kirchhoff_monitor_v1"
STORAGE_VERSION = 1

# Leer-parameters
EMA_ALPHA          = 0.05    # heel traag — stabiele classificatie
MIN_SAMPLES        = 60      # ~10 minuten bij 10s polling
CORRECTION_SAMPLES = 120     # ~20 minuten voor zelfcorrectie
SAVE_INTERVAL      = 60      # dirty-saves voor opslaan

# Drempels
RESIDUAL_OK_FRAC       = 0.04   # <4% van totaal → ok
RESIDUAL_WARN_FRAC     = 0.12   # >12% → waarschuwing
RESIDUAL_ALERT_FRAC    = 0.25   # >25% → alert
SIGN_ERROR_RATIO       = 1.7    # residueel ≈ -2×waarde  → tekenfout
SCALE_ERROR_HIGH       = 500.0  # residueel > 500× waarde → kW-in-W
SCALE_ERROR_LOW        = 0.002  # residueel < 0.002× waarde → W-in-kW
LAG_CORRELATION_MIN    = 0.6    # correlatie dP/dt > 0.6 → vertraging
OFFSET_STABILITY_MAX   = 0.15   # std/mean residueel < 0.15 → offset
FROZEN_DELTA_MAX       = 0.5    # waarde verandert minder dan 0.5W → bevroren
FROZEN_GRID_MIN        = 300.0  # alleen detecteren als grid > 300W varieert
CORRECTION_CONF_MIN    = 0.80   # minimale zekerheid voor zelfcorrectie
HINT_CONF_WARN         = 0.65
HINT_CONF_ALERT        = 0.85

# Diagnostics log interval
DIAG_LOG_INTERVAL_S = 1800   # 30 minuten

SENSORS = ["grid", "solar", "battery", "house"]


@dataclass
class SensorDrift:
    """Toestand en statistieken per sensor."""
    name: str

    # EMA van residueel (W) — positief = sensor te hoog, negatief = te laag
    ema_residual: float = 0.0
    # EMA van |residueel| / totaal — relatieve afwijking
    ema_rel_deviation: float = 0.0
    # EMA van residueel² — voor stabiliteitsschatting
    ema_residual_sq: float = 0.0
    # Correlatie residueel met eigen dP/dt
    ema_lag_corr: float = 0.0
    # Vorige waarde voor dP/dt
    prev_value: float = 0.0
    prev_ts: float = 0.0

    # Klassi ficatie
    classification: str = "learning"   # learning/ok/offset/lag/sign_error/scale_error/frozen
    confidence: float = 0.0
    sample_count: int = 0

    # Correctiefactor (1.0 = geen correctie)
    correction_factor: float = 1.0
    correction_offset: float = 0.0    # W — voor constante offset
    corrections_applied: int = 0

    # Ring buffer residuelen voor std-berekening
    residual_history: deque = field(default_factory=lambda: deque(maxlen=60))

    def to_dict(self) -> dict:
        return {
            "ema_res":       round(self.ema_residual, 2),
            "ema_rel":       round(self.ema_rel_deviation, 4),
            "ema_lag":       round(self.ema_lag_corr, 4),
            "classification": self.classification,
            "confidence":    round(self.confidence, 4),
            "samples":       self.sample_count,
            "corr_factor":   round(self.correction_factor, 6),
            "corr_offset":   round(self.correction_offset, 2),
            "corrections":   self.corrections_applied,
        }

    def from_dict(self, d: dict) -> None:
        self.ema_residual       = float(d.get("ema_res", 0.0))
        self.ema_rel_deviation  = float(d.get("ema_rel", 0.0))
        self.ema_lag_corr       = float(d.get("ema_lag", 0.0))
        self.classification     = d.get("classification", "learning")
        self.confidence         = float(d.get("confidence", 0.0))
        self.sample_count       = int(d.get("samples", 0))
        self.correction_factor  = float(d.get("corr_factor", 1.0))
        self.correction_offset  = float(d.get("corr_offset", 0.0))
        self.corrections_applied = int(d.get("corrections", 0))


class KirchhoffDriftMonitor:
    """
    Zelflerend, zelfcorrigerend Kirchhoff-consistentie monitor.

    Aanroepen elke coordinator-cyclus via observe().
    Geeft gecorrigeerde waarden terug via apply_corrections().
    """

    def __init__(self, hass) -> None:
        self._hass = hass
        self._sensors: Dict[str, SensorDrift] = {
            s: SensorDrift(name=s) for s in SENSORS
        }
        self._store         = None
        self._dirty_count   = 0
        self._last_diag_ts  = 0.0
        self._decisions_history = None   # injecteerbaar
        self._hint_engine   = None       # injecteerbaar

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    def set_hint_engine(self, he) -> None:
        self._hint_engine = he

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        await self._async_load()

    async def _async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        for s in SENSORS:
            if s in data:
                self._sensors[s].from_dict(data[s])
        _LOGGER.debug("KirchhoffDriftMonitor: statistieken geladen uit storage")

    async def _async_save(self) -> None:
        data = {s: self._sensors[s].to_dict() for s in SENSORS}
        await self._store.async_save(data)
        self._dirty_count = 0

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL:
            await self._async_save()

    # ── Publieke interface ────────────────────────────────────────────────────

    def observe(
        self,
        grid_w:    Optional[float],
        solar_w:   Optional[float],
        battery_w: Optional[float],
        house_w:   Optional[float],
    ) -> None:
        """
        Verwerk één meetmoment. Geen van de waarden is verplicht.
        Alleen als alle vier beschikbaar zijn volgt een volledige analyse.
        """
        now = time.time()

        # Zet None → 0 voor berekeningen, maar markeer welke ontbreken
        vals = {
            "grid":    grid_w,
            "solar":   solar_w,
            "battery": battery_w,
            "house":   house_w,
        }
        available = {k: v for k, v in vals.items() if v is not None}
        if len(available) < 3:
            return   # Niet genoeg data voor kruiscontrole

        # Bereken residueel per sensor
        # Kirchhoff: house = grid + solar - battery
        # Residueel sensor X = gemeten X − wat de andere drie impliceren
        residuals = self._compute_residuals(vals)

        total_power = max(
            abs(available.get("grid", 0)),
            abs(available.get("house", 0)),
            100.0,
        )

        # Update statistieken per sensor
        for s, sd in self._sensors.items():
            if s not in residuals or vals[s] is None:
                continue
            res = residuals[s]
            val = vals[s]

            # dP/dt voor lag-detectie
            dpdt = 0.0
            if sd.prev_ts > 0:
                dt = max(now - sd.prev_ts, 1.0)
                dpdt = (val - sd.prev_value) / dt
            sd.prev_value = val
            sd.prev_ts    = now

            # EMA updates
            sd.ema_residual     = EMA_ALPHA * res + (1 - EMA_ALPHA) * sd.ema_residual
            rel_dev = abs(res) / total_power
            sd.ema_rel_deviation = EMA_ALPHA * rel_dev + (1 - EMA_ALPHA) * sd.ema_rel_deviation
            sd.ema_residual_sq  = EMA_ALPHA * res**2 + (1 - EMA_ALPHA) * sd.ema_residual_sq

            # Lag-correlatie: residueel correleert met dP/dt als sensor achterloopt
            if abs(dpdt) > 1.0:
                corr = 1.0 if (res * dpdt > 0) else -1.0
                sd.ema_lag_corr = EMA_ALPHA * corr + (1 - EMA_ALPHA) * sd.ema_lag_corr

            sd.residual_history.append(res)
            sd.sample_count = min(sd.sample_count + 1, 99999)

            self._dirty_count += 1

        # Classificeer en reageer na genoeg samples
        if min(sd.sample_count for sd in self._sensors.values()) >= MIN_SAMPLES:
            self._classify_all(vals, residuals, total_power, now)

        # Periodieke diagnostics log
        if now - self._last_diag_ts > DIAG_LOG_INTERVAL_S:
            self._log_diagnostics(vals, residuals)
            self._last_diag_ts = now

    def apply_corrections(
        self,
        grid_w:    Optional[float],
        solar_w:   Optional[float],
        battery_w: Optional[float],
        house_w:   Optional[float],
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        v4.6.545: Correcties uitgeschakeld — monitor is nu observe-only.
        De PowerCalculator (UOM-detectie + safety guard) is de juiste plek
        voor kW↔W normalisatie. Zelfcorrectie op basis van Kirchhoff-residuelen
        veroorzaakte cascaderende fouten (660 kW bug) na herstarten.
        Geeft altijd de ongewijzigde invoerwaarden terug.
        """
        return (grid_w, solar_w, battery_w, house_w)

    def get_diagnostics(self) -> dict:
        """Volledige diagnostics voor sensor/dashboard."""
        return {
            s: {
                **sd.to_dict(),
                "residual_std": self._residual_std(sd),
            }
            for s, sd in self._sensors.items()
        }

    # ── Interne berekeningen ──────────────────────────────────────────────────

    @staticmethod
    def _compute_residuals(
        vals: Dict[str, Optional[float]],
    ) -> Dict[str, float]:
        """
        Bereken residueel per sensor: gemeten − Kirchhoff-schatting.

        Kirchhoff: house = grid + solar - battery
        grid    = house - solar + battery
        solar   = house - grid  + battery
        battery = grid + solar  - house
        """
        g = vals.get("grid")
        s = vals.get("solar")
        b = vals.get("battery")
        h = vals.get("house")

        residuals: Dict[str, float] = {}

        # house: gemeten h vs (g + s - b)
        if h is not None and g is not None and s is not None and b is not None:
            residuals["house"]    = h - (g + s - b)
            residuals["grid"]     = g - (h - s + b)
            residuals["solar"]    = s - (h - g + b)
            residuals["battery"]  = b - (g + s - h)
        elif h is None and g is not None and s is not None and b is not None:
            # house ontbreekt — schat house en geef residuelen voor de drie
            h_est = g + s - b
            residuals["grid"]     = 0.0   # kan niet beoordelen zonder house
            residuals["solar"]    = 0.0
            residuals["battery"]  = 0.0
        elif b is None and g is not None and s is not None and h is not None:
            # battery ontbreekt
            b_est = g + s - h
            residuals["grid"]    = g - (h - s + b_est)
            residuals["solar"]   = s - (h - g + b_est)
            residuals["house"]   = 0.0
        # Andere combinaties: te weinig data

        return residuals

    def _residual_std(self, sd: SensorDrift) -> float:
        """Standaardafwijking van de residuelen in de ringbuffer."""
        if len(sd.residual_history) < 3:
            return 0.0
        mean = sum(sd.residual_history) / len(sd.residual_history)
        var  = sum((x - mean)**2 for x in sd.residual_history) / len(sd.residual_history)
        return var ** 0.5

    def _count_consistent(self, residuals: dict, total_power: float) -> Dict[str, bool]:
        """Bepaal welke sensoren consistent zijn (relatief residueel < ok-drempel)."""
        return {
            s: abs(residuals.get(s, 999)) / total_power < RESIDUAL_WARN_FRAC
            for s in SENSORS
        }

    # ── Classificatie ─────────────────────────────────────────────────────────

    def _classify_all(
        self,
        vals: Dict[str, Optional[float]],
        residuals: Dict[str, float],
        total_power: float,
        now: float,
    ) -> None:
        consistent = self._count_consistent(residuals, total_power)
        n_consistent = sum(consistent.values())

        for s, sd in self._sensors.items():
            if s not in residuals or vals[s] is None:
                continue

            old_class = sd.classification
            res  = residuals[s]
            val  = vals[s]
            rel  = sd.ema_rel_deviation

            # ── Tekenfout ─────────────────────────────────────────────────
            if (val != 0 and abs(sd.ema_residual / val) > SIGN_ERROR_RATIO
                    and sd.ema_residual * val < 0):
                new_class  = "sign_error"
                confidence = min(0.99, abs(sd.ema_residual / val) / 3.0)
                # v4.6.545: correctie uitgeschakeld — alleen observeren en melden

            # ── Schaalfout (kW vs W) ───────────────────────────────────────
            elif (val != 0 and (abs(res / val) > SCALE_ERROR_HIGH
                                or abs(res / val) < SCALE_ERROR_LOW)):
                new_class  = "scale_error"
                confidence = min(0.99, 0.7 + 0.1 * (sd.sample_count - MIN_SAMPLES) / MIN_SAMPLES)
                # v4.6.545: correctie uitgeschakeld — PowerCalculator doet kW↔W normalisatie

            # ── Vertraging ─────────────────────────────────────────────────
            elif sd.ema_lag_corr > LAG_CORRELATION_MIN and rel > RESIDUAL_OK_FRAC:
                new_class  = "lag"
                confidence = min(0.95, sd.ema_lag_corr)
                # Geen correctie — balancer doet lag-compensatie zelf

            # ── Offset ────────────────────────────────────────────────────
            elif (rel > RESIDUAL_OK_FRAC
                  and self._residual_std(sd) / max(abs(sd.ema_residual), 1.0) < OFFSET_STABILITY_MAX):
                new_class  = "offset"
                confidence = min(0.92, 1.0 - self._residual_std(sd) / max(abs(sd.ema_residual), 1.0))
                # v4.6.545: correctie uitgeschakeld — alleen observeren en melden via hints

            # ── Bevroren ──────────────────────────────────────────────────
            elif (self._residual_std(sd) < FROZEN_DELTA_MAX
                  and total_power > FROZEN_GRID_MIN
                  and sd.sample_count > MIN_SAMPLES * 2):
                new_class  = "frozen"
                confidence = min(0.90, 0.6 + 0.1 * (sd.sample_count / MIN_SAMPLES - 2))

            # ── OK ────────────────────────────────────────────────────────
            elif rel < RESIDUAL_OK_FRAC:
                new_class  = "ok"
                confidence = min(0.99, 1.0 - rel / RESIDUAL_OK_FRAC)

            else:
                new_class  = "learning"
                confidence = 0.3

            # Update classificatie
            sd.classification = new_class
            sd.confidence     = confidence

            # Log classificatiewijziging
            if new_class != old_class:
                self._log_classification_change(s, old_class, new_class, confidence,
                                                 sd.ema_residual, total_power)

            # Emit hints
            self._maybe_emit_hint(s, sd, vals[s], total_power)

    # ── Hints ─────────────────────────────────────────────────────────────────

    def _maybe_emit_hint(
        self,
        sensor: str,
        sd: SensorDrift,
        value: Optional[float],
        total_power: float,
    ) -> None:
        if not self._hint_engine:
            return
        if sd.classification == "ok" or sd.classification == "learning":
            return
        if sd.confidence < HINT_CONF_WARN:
            return

        hint_id = f"kirchhoff_drift_{sensor}_{sd.classification}"

        sensor_nl = {
            "grid": "netsensor", "solar": "solar-sensor",
            "battery": "batterijsensor", "house": "huisverbruik-sensor",
        }.get(sensor, sensor)

        messages = {
            "sign_error": (
                f"⚠️ {sensor_nl.capitalize()} heeft waarschijnlijk een verkeerd teken. "
                f"De gemeten waarde ({value:.0f}W) is tegengesteld aan wat "
                f"de andere sensoren impliceren (residueel: {sd.ema_residual:.0f}W). "
                f"Controleer of import/export correct geconfigureerd is."
            ),
            "scale_error": (
                f"⚠️ {sensor_nl.capitalize()} lijkt een schaalfout te hebben "
                f"(mogelijk kW i.p.v. W of omgekeerd). "
                f"Gemeten: {value:.3f}, verwacht: ~{value + sd.ema_residual:.0f}W."
            ),
            "offset": (
                f"ℹ️ {sensor_nl.capitalize()} heeft een structurele afwijking van "
                f"~{sd.ema_residual:.0f}W t.o.v. wat de andere sensoren impliceren. "
                f"{'CloudEMS past automatisch een correctie toe.' if sd.corrections_applied > 0 else 'Controleer de sensor of kalibreer hem.'}"
            ),
            "lag": (
                f"ℹ️ {sensor_nl.capitalize()} reageert vertraagd op wijzigingen. "
                f"Dit is normaal bij cloud-sensoren (Zonneplan, sommige omvormers). "
                f"CloudEMS houdt hier rekening mee via de EnergyBalancer."
            ),
            "frozen": (
                f"⚠️ {sensor_nl.capitalize()} lijkt bevroren — de waarde verandert nauwelijks "
                f"terwijl het netverbruik varieert. Controleer de sensor-verbinding."
            ),
        }

        msg = messages.get(sd.classification)
        if not msg:
            return

        level = "alert" if sd.confidence > HINT_CONF_ALERT else "warning"
        title = f"Kirchhoff: {sensor_nl} afwijking ({sd.classification})"

        try:
            self._hint_engine._emit_hint(
                hint_id    = hint_id,
                title      = title,
                message    = msg,
                action     = f"Controleer sensor '{sensor}' in CloudEMS instellingen",
                confidence = sd.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("KirchhoffDriftMonitor: hint-emissie mislukt: %s", _e)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log_correction(
        self, sensor: str, reason: str, factor: float, offset: float
    ) -> None:
        msg = (
            f"KirchhoffDriftMonitor: zelfcorrectie {sensor} "
            f"[{reason}] factor={factor:.4f} offset={offset:.1f}W"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "kirchhoff_monitor",
                    action   = f"correctie_{sensor}",
                    reason   = reason,
                    message  = msg,
                    extra    = {
                        "sensor": sensor,
                        "reason": reason,
                        "factor": round(factor, 4),
                        "offset": round(offset, 1),
                    },
                )
            except Exception:
                pass

    def _log_classification_change(
        self, sensor: str, old: str, new: str,
        confidence: float, ema_residual: float, total_power: float,
    ) -> None:
        msg = (
            f"KirchhoffDriftMonitor: {sensor} classificatie {old} → {new} "
            f"(vertrouwen {confidence:.0%}, residueel EMA {ema_residual:.0f}W, "
            f"totaal {total_power:.0f}W)"
        )
        _LOGGER.info(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "kirchhoff_monitor",
                    action   = f"classificatie_{sensor}",
                    reason   = f"{old}_naar_{new}",
                    message  = msg,
                    extra    = {
                        "sensor":      sensor,
                        "old_class":   old,
                        "new_class":   new,
                        "confidence":  round(confidence, 3),
                        "ema_residual": round(ema_residual, 1),
                        "total_w":     round(total_power, 1),
                    },
                )
            except Exception:
                pass

    def _log_diagnostics(
        self,
        vals: Dict[str, Optional[float]],
        residuals: Dict[str, float],
    ) -> None:
        diag = {
            s: {
                "val_w":   round(vals.get(s) or 0, 1),
                "res_w":   round(residuals.get(s, 0), 1),
                "class":   self._sensors[s].classification,
                "conf":    round(self._sensors[s].confidence, 2),
                "samples": self._sensors[s].sample_count,
                "corr_f":  round(self._sensors[s].correction_factor, 4),
                "corr_o":  round(self._sensors[s].correction_offset, 1),
            }
            for s in SENSORS
        }
        _LOGGER.debug("KirchhoffDriftMonitor diagnostics: %s", diag)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "kirchhoff_monitor",
                    action   = "diagnostics_snapshot",
                    reason   = "periodiek",
                    message  = f"KirchhoffDriftMonitor 30-min snapshot",
                    extra    = {"sensors": diag},
                )
            except Exception:
                pass
