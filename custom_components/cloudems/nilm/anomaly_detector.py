"""
CloudEMS NILM Anomaly Detector — v1.22.0

Detecteert afwijkend vermogensverbruik per apparaat:
  - Rollend gemiddelde vermogen per device_type bijhouden
  - Waarschuwing als het huidige verbruik >THRESHOLD_PCT% afwijkt van het verwachte
  - Werkt op basis van bevestigde apparaten (confirmed=True)
  - Resultaat beschikbaar via coordinator.data["nilm_anomalies"]

Typische use-cases:
  - Verkalkte waterkoker: +15% extra vermogen
  - Defect verwarmingselement: plotseling ×2 vermogen
  - Koelkast die het moeilijk krijgt zomers: langere cycli

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# ── Instellingen ──────────────────────────────────────────────────────────────
ANOMALY_MIN_SAMPLES      = 20      # min metingen vóór anomalie-detectie actief is
ANOMALY_THRESHOLD_PCT    = 25.0    # % afwijking van het rolgemiddelde → anomalie
ANOMALY_WINDOW           = 200     # aantal metingen in het rolvenster per apparaat
ANOMALY_MIN_POWER_W      = 30.0    # minste vermogen; onder dit niveau geen detectie
ANOMALY_COOLDOWN_S       = 3600    # min. 1 uur tussen dezelfde apparaat-waarschuwing
ANOMALY_HIGH_THRESHOLD   = 50.0    # % → ernstige afwijking (andere severity)


@dataclass
class DeviceAnomalyState:
    """Rollend vermogensgemiddelde + anomalie-status per apparaat."""
    device_id:    str
    device_type:  str
    name:         str

    _samples:     deque = field(default_factory=lambda: deque(maxlen=ANOMALY_WINDOW))
    last_alert_ts: float = 0.0
    alert_count:   int   = 0

    def update(self, power_w: float) -> None:
        if power_w >= ANOMALY_MIN_POWER_W:
            self._samples.append(power_w)

    @property
    def mean_w(self) -> float:
        if not self._samples:
            return 0.0
        return sum(self._samples) / len(self._samples)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def is_ready(self) -> bool:
        return len(self._samples) >= ANOMALY_MIN_SAMPLES

    def deviation_pct(self, current_w: float) -> float:
        """Procentuele afwijking van het verwachte vermogen."""
        mean = self.mean_w
        if mean <= 0:
            return 0.0
        return ((current_w - mean) / mean) * 100.0

    def to_dict(self) -> dict:
        return {
            "device_id":    self.device_id,
            "device_type":  self.device_type,
            "name":         self.name,
            "mean_w":       round(self.mean_w, 1),
            "samples":      self.sample_count,
            "ready":        self.is_ready,
            "alert_count":  self.alert_count,
        }


@dataclass
class AnomalyAlert:
    """Een gedetecteerde vermogensafwijking."""
    device_id:     str
    device_type:   str
    name:          str
    expected_w:    float
    actual_w:      float
    deviation_pct: float
    severity:      str       # "warning" | "critical"
    timestamp:     float = field(default_factory=time.time)
    message_nl:    str   = ""
    message_en:    str   = ""

    def to_dict(self) -> dict:
        return {
            "device_id":     self.device_id,
            "device_type":   self.device_type,
            "name":          self.name,
            "expected_w":    round(self.expected_w, 1),
            "actual_w":      round(self.actual_w, 1),
            "deviation_pct": round(self.deviation_pct, 1),
            "severity":      self.severity,
            "timestamp":     self.timestamp,
            "message_nl":    self.message_nl,
            "message_en":    self.message_en,
        }


class NILMAnomalyDetector:
    """
    Detecteert afwijkend vermogensgedrag van bekende NILM-apparaten.

    Gebruik via coordinator:
        anomaly_detector.update(nilm_devices)
        alerts = anomaly_detector.get_active_alerts()
    """

    def __init__(self) -> None:
        self._states: Dict[str, DeviceAnomalyState] = {}
        self._active_alerts: List[AnomalyAlert] = []
        self._alert_history: deque = deque(maxlen=50)
        self._total_alerts: int = 0
        _LOGGER.info("CloudEMS NILM AnomalyDetector initialized")

    # ── Publieke API ──────────────────────────────────────────────────────────

    def update(self, nilm_devices: List[dict]) -> List[AnomalyAlert]:
        """
        Verwerk de huidige NILM-apparaatlijst en detecteer anomalieën.
        Geeft lijst van nieuwe alerts terug (leeg als alles normaal is).
        """
        now = time.time()
        new_alerts: List[AnomalyAlert] = []
        current_device_ids = set()

        for dev in nilm_devices:
            dev_id   = dev.get("device_id", "")
            dtype    = dev.get("device_type", "")
            name     = dev.get("display_name") or dev.get("name") or dtype
            power_w  = float(dev.get("current_power") or 0)
            is_on    = dev.get("is_on", False)
            confirmed = dev.get("confirmed", False) or dev.get("source") == "smart_plug"

            if not dev_id or not confirmed or not is_on or power_w < ANOMALY_MIN_POWER_W:
                continue

            current_device_ids.add(dev_id)

            # Initialiseer state als nog niet bekend
            if dev_id not in self._states:
                self._states[dev_id] = DeviceAnomalyState(
                    device_id=dev_id, device_type=dtype, name=name
                )

            state = self._states[dev_id]
            state.name = name  # naam kan zijn bijgewerkt

            # Voeg sample toe
            state.update(power_w)

            # Controleer op anomalie als genoeg data beschikbaar is
            if not state.is_ready:
                continue

            dev_pct = state.deviation_pct(power_w)

            if abs(dev_pct) < ANOMALY_THRESHOLD_PCT:
                continue  # normaal gedrag

            # Cooldown check: zelfde apparaat niet elke seconde melden
            if (now - state.last_alert_ts) < ANOMALY_COOLDOWN_S:
                continue

            severity = "critical" if abs(dev_pct) >= ANOMALY_HIGH_THRESHOLD else "warning"
            alert = self._build_alert(state, power_w, dev_pct, severity)
            state.last_alert_ts = now
            state.alert_count += 1
            self._total_alerts += 1
            new_alerts.append(alert)
            self._alert_history.appendleft(alert)

            _LOGGER.warning(
                "NILM Anomalie %s: %s — verwacht %.0fW, actueel %.0fW (%.0f%% afwijking)",
                severity.upper(), name, state.mean_w, power_w, dev_pct,
            )

        # Verwijder states van apparaten die niet meer in de lijst staan
        gone = set(self._states.keys()) - current_device_ids
        for did in gone:
            del self._states[did]

        self._active_alerts = [
            a for a in self._active_alerts
            if (now - a.timestamp) < ANOMALY_COOLDOWN_S
        ]
        self._active_alerts.extend(new_alerts)

        return new_alerts

    def get_active_alerts(self) -> List[dict]:
        return [a.to_dict() for a in self._active_alerts]

    def get_alert_history(self) -> List[dict]:
        return [a.to_dict() for a in self._alert_history]

    def get_device_states(self) -> List[dict]:
        return [s.to_dict() for s in self._states.values()]

    def get_diagnostics(self) -> dict:
        ready = sum(1 for s in self._states.values() if s.is_ready)
        return {
            "tracked_devices":  len(self._states),
            "ready_devices":    ready,
            "active_alerts":    len(self._active_alerts),
            "total_alerts":     self._total_alerts,
            "alert_history":    self.get_alert_history(),
            "device_states":    self.get_device_states(),
        }

    # ── Interne methoden ──────────────────────────────────────────────────────

    def _build_alert(
        self,
        state: DeviceAnomalyState,
        actual_w: float,
        dev_pct: float,
        severity: str,
    ) -> AnomalyAlert:
        direction_nl = "hoger" if dev_pct > 0 else "lager"
        direction_en = "higher" if dev_pct > 0 else "lower"
        cause_nl = self._guess_cause_nl(state.device_type, dev_pct)
        cause_en = self._guess_cause_en(state.device_type, dev_pct)

        msg_nl = (
            f"{state.name} verbruikt {abs(dev_pct):.0f}% {direction_nl} dan verwacht "
            f"({actual_w:.0f}W vs normaal {state.mean_w:.0f}W). {cause_nl}"
        )
        msg_en = (
            f"{state.name} uses {abs(dev_pct):.0f}% {direction_en} than expected "
            f"({actual_w:.0f}W vs normal {state.mean_w:.0f}W). {cause_en}"
        )

        return AnomalyAlert(
            device_id=state.device_id,
            device_type=state.device_type,
            name=state.name,
            expected_w=state.mean_w,
            actual_w=actual_w,
            deviation_pct=dev_pct,
            severity=severity,
            message_nl=msg_nl,
            message_en=msg_en,
        )

    @staticmethod
    def _guess_cause_nl(device_type: str, dev_pct: float) -> str:
        if dev_pct > 0:
            causes = {
                "boiler":          "Mogelijk kalkaanslag op het verwarmingselement.",
                "kettle":          "Mogelijk kalk in de waterkoker — ontkalken aanbevolen.",
                "refrigerator":    "Mogelijk vuile condensor of kapotte afdichting.",
                "washing_machine": "Mogelijk verstopping of extra belading.",
                "heat_pump":       "Mogelijk lage buitentemperatuur of onderhoud nodig.",
                "ev_charger":      "Onverwacht hoog laadvermogen — controleer lader.",
            }
        else:
            causes = {
                "boiler":          "Verwarmingselement mogelijk defect.",
                "washing_machine": "Lichte lading of eco-programma actief.",
                "heat_pump":       "Warmtepomp draait in zuinige modus.",
            }
        return causes.get(device_type, "Controleer het apparaat op afwijkingen.")

    @staticmethod
    def _guess_cause_en(device_type: str, dev_pct: float) -> str:
        if dev_pct > 0:
            causes = {
                "boiler":          "Possible limescale on heating element.",
                "kettle":          "Possible limescale — descaling recommended.",
                "refrigerator":    "Possible dirty condenser or worn door seal.",
                "washing_machine": "Possible blockage or extra load.",
                "heat_pump":       "Possible low outdoor temperature or maintenance needed.",
                "ev_charger":      "Unexpectedly high charge power — check charger.",
            }
        else:
            causes = {
                "boiler":          "Heating element may be failing.",
                "washing_machine": "Light load or eco programme active.",
                "heat_pump":       "Heat pump running in efficient mode.",
            }
        return causes.get(device_type, "Check the appliance for anomalies.")

    # ── Persistentie ─────────────────────────────────────────────────────────

    def to_persist(self) -> dict:
        """Serialiseer state voor opslag (alleen rolgemiddelden, geen timestamps)."""
        return {
            did: {
                "device_type": s.device_type,
                "name":        s.name,
                "samples":     list(s._samples),
                "alert_count": s.alert_count,
            }
            for did, s in self._states.items()
        }

    def from_persist(self, data: dict) -> None:
        """Herstel state vanuit opgeslagen data."""
        for did, d in data.items():
            state = DeviceAnomalyState(
                device_id=did,
                device_type=d.get("device_type", "unknown"),
                name=d.get("name", did),
            )
            for sample in d.get("samples", []):
                state._samples.append(float(sample))
            state.alert_count = d.get("alert_count", 0)
            self._states[did] = state
        _LOGGER.info("NILM AnomalyDetector: %d apparaatstates hersteld", len(self._states))
