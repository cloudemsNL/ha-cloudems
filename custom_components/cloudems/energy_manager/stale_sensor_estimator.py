"""
CloudEMS Stale Sensor Estimator — v1.0.0

Wanneer een geconfigureerde sensor communicatie verliest, vult CloudEMS
de ontbrekende waarde tijdelijk in via het geleerde patroon.

Ondersteunde sensoren:
  - PV omvormer (solar_power): per-uur EMA patroon + weercorrectie
  - Thuisbatterij (battery_power): laatste bekende waarde + Kirchhoff schatting
  - Boiler temperatuur: thermisch afkoelmodel

Garanties:
  - Alleen actief als sensor is_stale() retourneert True
  - Zodra sensor herstelt → direct terug naar echte waarde
  - Alert wordt gegenereerd zolang estimatie actief is
  - Schatting degradeert bij lang offline (confidence daalt)
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Na hoeveel seconden stale een waarschuwing genereren
ALERT_AFTER_STALE_S = 60.0
# Na hoeveel seconden stoppen met schatten (te onzeker)
GIVE_UP_AFTER_S     = 3600.0   # 1 uur
# Minimale confidence om schatting te gebruiken
MIN_CONFIDENCE      = 0.20


@dataclass
class SensorEstimate:
    """Eén geschatte sensorwaarde met metadata."""
    value:        float
    confidence:   float          # 0.0 – 1.0
    method:       str            # "pattern" | "last_known" | "kirchhoff" | "thermal"
    stale_since:  float          # timestamp waarop sensor stale werd
    sensor_id:    str

    @property
    def stale_age_s(self) -> float:
        return time.time() - self.stale_since

    @property
    def is_usable(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE and self.stale_age_s < GIVE_UP_AFTER_S

    def to_alert(self) -> dict:
        age_min = int(self.stale_age_s / 60)
        return {
            "type":       f"stale_{self.sensor_id}",
            "message":    f"{self._friendly_name()} — communicatie verloren ({age_min} min)",
            "detail":     f"Schatting via {self.method}: {self.value:.0f} "
                          f"(confidence {self.confidence*100:.0f}%)",
            "severity":   "warning" if self.stale_age_s < 300 else "critical",
            "estimated_value": round(self.value, 1),
            "confidence_pct":  round(self.confidence * 100, 1),
            "stale_age_s":     round(self.stale_age_s, 0),
        }

    def _friendly_name(self) -> str:
        names = {
            "solar":   "PV omvormer",
            "battery": "Thuisbatterij",
            "boiler":  "Boiler temperatuursensor",
        }
        return names.get(self.sensor_id, self.sensor_id)


class StaleSensorEstimator:
    """
    Beheert virtuele fallback-waarden voor stale sensoren.

    Gebruik:
        estimator = StaleSensorEstimator()
        # Bij elke coordinator tick:
        estimator.update_patterns(hour, solar_w, battery_w, boiler_temp)
        # Als sensor stale is:
        est = estimator.estimate_solar(hour, cloud_cover_pct)
        if est and est.is_usable:
            data["solar_power"] = est.value
    """

    def __init__(self) -> None:
        # Per-uur EMA voor solar (24 waarden in W)
        self._solar_hour_ema: list[float] = [0.0] * 24
        self._solar_hour_n:   list[int]   = [0] * 24
        self._solar_peak_w:   float       = 0.0

        # Laatste bekende waarden
        self._last_solar_w:   float = 0.0
        self._last_battery_w: float = 0.0
        self._last_boiler_c:  float = 0.0
        self._last_grid_w:    float = 0.0
        self._last_house_w:   float = 0.0

        # Stale timestamps (0 = niet stale)
        self._solar_stale_ts:   float = 0.0
        self._battery_stale_ts: float = 0.0
        self._boiler_stale_ts:  float = 0.0

        # Actieve schattingen
        self._solar_est:   Optional[SensorEstimate] = None
        self._battery_est: Optional[SensorEstimate] = None
        self._boiler_est:  Optional[SensorEstimate] = None

    # ── Patroon leren ─────────────────────────────────────────────────────────

    # ── Multi-omvormer correlatie ─────────────────────────────────────────────

    def register_inverter(self, inverter_id: str) -> None:
        """Registreer een omvormer voor correlatie-tracking."""
        if not hasattr(self, '_inverter_hour_ratios'):
            # Per uur EMA van de ratio t.o.v. het totaal
            # West ijlt na op Oost — ratio varieert sterk per uur
            self._inverter_hour_ratios: dict[str, list[float]] = {}  # id → 24 EMA waarden
            self._inverter_hour_n:      dict[str, list[int]]   = {}  # id → 24 tellers
            self._inverter_last_w:      dict[str, float]       = {}
        if inverter_id not in self._inverter_hour_ratios:
            self._inverter_hour_ratios[inverter_id] = [0.0] * 24
            self._inverter_hour_n[inverter_id]      = [0]   * 24
            self._inverter_last_w[inverter_id]      = 0.0

    def observe_inverter(self, inverter_id: str, power_w: float,
                         total_solar_w: float, hour: int = -1) -> None:
        """
        Leer de per-uur ratio van deze omvormer t.o.v. het totaal.
        West ijlt na op Oost: ratio op uur 10 ≠ ratio op uur 14.
        """
        if not hasattr(self, '_inverter_hour_ratios'):
            self.register_inverter(inverter_id)
        if inverter_id not in self._inverter_hour_ratios:
            self.register_inverter(inverter_id)

        self._inverter_last_w[inverter_id] = power_w

        if hour < 0:
            hour = __import__('datetime').datetime.now().hour

        if total_solar_w > 500 and power_w >= 0:
            ratio = power_w / total_solar_w
            n     = self._inverter_hour_n[inverter_id][hour]
            alpha = 0.2 if n > 5 else 0.5   # snel leren in het begin
            old_r = self._inverter_hour_ratios[inverter_id][hour]
            self._inverter_hour_ratios[inverter_id][hour] = (
                old_r * (1 - alpha) + ratio * alpha if n > 0 else ratio
            )
            self._inverter_hour_n[inverter_id][hour] = min(n + 1, 500)

    def estimate_stale_inverter(self,
                                stale_id:      str,
                                active_powers: dict[str, float],
                                hour:          int = -1) -> Optional[SensorEstimate]:
        """
        Schat stale omvormer via per-uur ratio t.o.v. werkende omvormers.
        West/Oost oriëntaties worden correct afgehandeld door per-uur leren.
        """
        if not hasattr(self, '_inverter_hour_ratios'):
            return None
        if stale_id not in self._inverter_hour_ratios:
            return None

        if hour < 0:
            hour = __import__('datetime').datetime.now().hour

        stale_ratio_h = self._inverter_hour_ratios[stale_id][hour]
        stale_n_h     = self._inverter_hour_n[stale_id][hour]

        if stale_n_h < 5 or stale_ratio_h < 0.01:
            return None  # onvoldoende data voor dit uur

        # Schat totaal op basis van actieve omvormers + hun geleerde ratio op dit uur
        active_total       = sum(active_powers.values())
        active_ratio_total = 0.0
        for inv_id in active_powers:
            r = self._inverter_hour_ratios.get(inv_id, [0]*24)[hour]
            active_ratio_total += r

        if active_ratio_total < 0.01:
            return None

        expected_total  = active_total / active_ratio_total
        estimated_stale = expected_total * stale_ratio_h

        # Confidence: observaties voor dit uur + stabiliteit ratio
        n_conf = min(1.0, stale_n_h / 20)
        # Buururen als stabiliteitscheck: uur-1 en uur+1 moeten consistent zijn
        h_prev = (hour - 1) % 24
        h_next = (hour + 1) % 24
        r_prev = self._inverter_hour_ratios[stale_id][h_prev]
        r_next = self._inverter_hour_ratios[stale_id][h_next]
        spread = max(abs(stale_ratio_h - r_prev), abs(stale_ratio_h - r_next))
        stab   = max(0.0, 1.0 - spread / max(stale_ratio_h, 0.01))
        confidence = n_conf * 0.6 + stab * 0.4

        return SensorEstimate(
            value       = max(0.0, round(estimated_stale, 1)),
            confidence  = round(confidence, 3),
            method      = f"inverter_correlation_h{hour:02d}",
            stale_since = self._solar_stale_ts or time.time(),
            sensor_id   = f"solar_{stale_id}",
        )

    # ── Export-gebaseerde inference ───────────────────────────────────────────

    def infer_from_export(self,
                          grid_w:        float,
                          known_solar_w: float,
                          house_w:       float,
                          battery_w:     float) -> Optional[SensorEstimate]:
        """
        Als export > bekende productie + batterij-ontlading, is er onverklaard vermogen.
        Dit kan alleen van een stale of onbekende omvormer komen.

        Gebruik: als stale omvormer geen correlatie-data heeft maar export wél klopt.
        """
        if grid_w >= 0:
            return None  # geen export

        export_w = -grid_w
        battery_discharge = max(0.0, -battery_w)
        # Wat kan de bekende productie verklaren?
        explained = known_solar_w + battery_discharge
        unaccounted = export_w + house_w - explained

        if unaccounted < 200:
            return None  # volledig verklaard

        # De export bewijst dat er meer geproduceerd wordt dan we weten
        # Confidence: hoe groter het verschil, hoe zekerder
        conf = min(0.9, unaccounted / max(1, unaccounted + 500))

        return SensorEstimate(
            value       = round(unaccounted, 1),
            confidence  = round(conf, 3),
            method      = "export_inference",
            stale_since = self._solar_stale_ts or time.time(),
            sensor_id   = "solar_unaccounted",
        )

    def observe(self,
                hour:       int,
                solar_w:    float,
                battery_w:  float,
                boiler_c:   float,
                grid_w:     float,
                house_w:    float) -> None:
        """Verwerk één tick echte sensordata — leert patronen."""
        # Solar per-uur EMA
        if solar_w > 0:
            n = self._solar_hour_n[hour]
            alpha = 0.15 if n > 10 else 0.3
            if n == 0:
                self._solar_hour_ema[hour] = solar_w
            else:
                self._solar_hour_ema[hour] = (1 - alpha) * self._solar_hour_ema[hour] + alpha * solar_w
            self._solar_hour_n[hour] = min(n + 1, 1000)
            self._solar_peak_w = max(self._solar_peak_w, solar_w)

        # Laatste bekende waarden bijhouden
        if solar_w >= 0:   self._last_solar_w   = solar_w
        if battery_w != 0: self._last_battery_w = battery_w
        if boiler_c > 0:   self._last_boiler_c  = boiler_c
        self._last_grid_w  = grid_w
        self._last_house_w = house_w

    # ── Stale markering ───────────────────────────────────────────────────────

    def mark_stale(self, sensor_id: str) -> None:
        """Markeer sensor als stale — start schatting."""
        now = time.time()
        if sensor_id == "solar" and self._solar_stale_ts == 0:
            self._solar_stale_ts = now
            _LOGGER.warning(
                "CloudEMS: PV omvormer sensor stale — schatting geactiveerd via geleerd patroon"
            )
        elif sensor_id == "battery" and self._battery_stale_ts == 0:
            self._battery_stale_ts = now
            _LOGGER.warning(
                "CloudEMS: Batterij sensor stale — schatting geactiveerd via Kirchhoff"
            )
        elif sensor_id == "boiler" and self._boiler_stale_ts == 0:
            self._boiler_stale_ts = now
            _LOGGER.warning(
                "CloudEMS: Boiler sensor stale — schatting geactiveerd via thermisch model"
            )

    def mark_recovered(self, sensor_id: str) -> None:
        """Sensor hersteld — stop schatting direct."""
        if sensor_id == "solar" and self._solar_stale_ts > 0:
            age = time.time() - self._solar_stale_ts
            _LOGGER.info(
                "CloudEMS: PV omvormer sensor hersteld na %.0f seconden — schatting gestopt",
                age,
            )
            self._solar_stale_ts = 0
            self._solar_est = None
        elif sensor_id == "battery" and self._battery_stale_ts > 0:
            self._battery_stale_ts = 0
            self._battery_est = None
        elif sensor_id == "boiler" and self._boiler_stale_ts > 0:
            self._boiler_stale_ts = 0
            self._boiler_est = None

    # ── Schattingen ───────────────────────────────────────────────────────────

    def estimate_solar(self,
                       hour:          int,
                       cloud_cover:   float = 50.0) -> Optional[SensorEstimate]:
        """
        Schat solar vermogen op basis van geleerd uur-profiel.
        cloud_cover: 0-100% bewolking
        """
        if self._solar_stale_ts == 0:
            return None

        stale_age = time.time() - self._solar_stale_ts
        if stale_age > GIVE_UP_AFTER_S:
            return None

        learned = self._solar_hour_ema[hour]
        n_obs   = self._solar_hour_n[hour]

        if learned < 10.0 or n_obs < 3:
            # Onvoldoende data voor dit uur — gebruik laatste bekende waarde
            value = self._last_solar_w
            method = "last_known"
            confidence = max(0.1, 0.4 - stale_age / GIVE_UP_AFTER_S * 0.3)
        else:
            # Gecorrigeerd voor bewolking
            cloud_factor = 1.0 - (cloud_cover / 100.0) * 0.85
            value = learned * cloud_factor
            # Confidence: hoe meer observaties en hoe korter stale, hoe hoger
            obs_conf  = min(1.0, n_obs / 20)
            age_conf  = max(0.0, 1.0 - stale_age / GIVE_UP_AFTER_S)
            confidence = obs_conf * 0.6 + age_conf * 0.4
            method = "pattern"

        self._solar_est = SensorEstimate(
            value       = max(0.0, value),
            confidence  = confidence,
            method      = method,
            stale_since = self._solar_stale_ts,
            sensor_id   = "solar",
        )
        return self._solar_est

    def estimate_battery(self,
                         grid_w:   float,
                         solar_w:  float,
                         house_w:  float) -> Optional[SensorEstimate]:
        """
        Schat batterijvermogen via Kirchhoff als sensor stale is.
        Valt terug op laatste bekende waarde als Kirchhoff onbetrouwbaar is.
        """
        if self._battery_stale_ts == 0:
            return None

        stale_age = time.time() - self._battery_stale_ts
        if stale_age > GIVE_UP_AFTER_S:
            return None

        # Kirchhoff: battery = solar + grid_export - house
        kirchhoff = solar_w - grid_w - house_w
        age_conf  = max(0.0, 1.0 - stale_age / GIVE_UP_AFTER_S)

        if abs(solar_w) > 50 or abs(grid_w) > 50:
            value      = kirchhoff
            confidence = 0.75 * age_conf
            method     = "kirchhoff"
        else:
            value      = self._last_battery_w
            confidence = 0.4 * age_conf
            method     = "last_known"

        self._battery_est = SensorEstimate(
            value       = value,
            confidence  = confidence,
            method      = method,
            stale_since = self._battery_stale_ts,
            sensor_id   = "battery",
        )
        return self._battery_est

    def estimate_boiler(self,
                        dt_s:         float,
                        boiler_on:    bool = False) -> Optional[SensorEstimate]:
        """
        Schat boilertemperatuur via thermisch afkoelmodel.
        Afkoelsnelheid: ~2°C/uur bij uitgeschakeld, ~8°C/uur bij aan.
        """
        if self._boiler_stale_ts == 0:
            return None

        stale_age = time.time() - self._boiler_stale_ts
        if stale_age > GIVE_UP_AFTER_S:
            return None

        if boiler_on:
            # Warmtestijging
            self._last_boiler_c = min(65.0, self._last_boiler_c + 8.0 * (dt_s / 3600))
        else:
            # Afkoeling naar koud water temperatuur (~15°C)
            self._last_boiler_c = max(15.0, self._last_boiler_c - 2.0 * (dt_s / 3600))

        age_conf = max(0.0, 1.0 - stale_age / GIVE_UP_AFTER_S)

        self._boiler_est = SensorEstimate(
            value       = round(self._last_boiler_c, 1),
            confidence  = 0.6 * age_conf,
            method      = "thermal",
            stale_since = self._boiler_stale_ts,
            sensor_id   = "boiler",
        )
        return self._boiler_est

    # ── Status & Alerts ───────────────────────────────────────────────────────

    def get_alerts(self) -> list[dict]:
        """Geeft actieve stale-sensor waarschuwingen."""
        alerts = []
        for est in [self._solar_est, self._battery_est, self._boiler_est]:
            if est and est.is_usable and est.stale_age_s >= ALERT_AFTER_STALE_S:
                alerts.append(est.to_alert())
        return alerts

    def get_status(self) -> dict:
        return {
            "solar_stale":   self._solar_stale_ts > 0,
            "battery_stale": self._battery_stale_ts > 0,
            "boiler_stale":  self._boiler_stale_ts > 0,
            "solar_est":     self._solar_est.value if self._solar_est else None,
            "battery_est":   self._battery_est.value if self._battery_est else None,
            "boiler_est":    self._boiler_est.value if self._boiler_est else None,
        }

    def get_learned_solar_profile(self) -> list[float]:
        """Geeft het geleerde per-uur solar profiel terug (voor dashboard)."""
        return [round(v, 1) for v in self._solar_hour_ema]
