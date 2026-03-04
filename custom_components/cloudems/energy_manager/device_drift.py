"""
CloudEMS Apparaat Efficiëntie Drift Tracker — v1.0.0

Detecteert wanneer een apparaat meer stroom gaat verbruiken dan historisch
gebruikelijk, wat kan duiden op slijtage, kalkafzetting of een defect.

Methode:
  - Bij elke NILM-detectie: sla het gemeten vermogen op
  - Exponentieel voortschrijdend gemiddelde van vermogen per apparaat
  - Referentiegemiddelde = eerste 20 metingen (stabiele baseline)
  - Alert als huidig gemiddelde > DRIFT_THRESHOLD × referentie

Speciale case — koelkast:
  - Koelkasten zijn cyclisch (compressor aan/uit)
  - Meet ook duty_cycle (fractie van de tijd dat compressor aan is)
  - Hogere duty_cycle = slechtere isolatie of overvolle koelkast

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_device_drift_v1"
STORAGE_VERSION = 1

DRIFT_THRESHOLD     = 1.10   # 10% boven referentie → drift
ALERT_THRESHOLD     = 1.20   # 20% boven referentie → alert
DUTY_DRIFT_THRESH   = 0.20   # Duty cycle 20% hoger dan referentie → alert (koelkast)
MIN_BASELINE_SAMPLES = 15    # Metingen nodig voor baseline
ALPHA_CURRENT       = 0.15   # EMA voor huidig verbruik (sneller bijwerken)
ALPHA_BASELINE      = 0.02   # EMA voor baseline (traag leren)
SAVE_INTERVAL_S     = 600


@dataclass
class DeviceDriftProfile:
    """Vermogensprofiel per NILM-apparaat voor drift-detectie."""
    device_id:      str
    device_type:    str
    label:          str
    baseline_w:     float   = 0.0    # Referentie-gemiddelde (eerste weken)
    current_avg_w:  float   = 0.0    # Huidig voortschrijdend gemiddelde
    samples_total:  int     = 0      # Totaal aantal NILM-detecties
    baseline_frozen: bool   = False  # Baseline vastgezet na MIN_BASELINE_SAMPLES
    # Duty-cycle bijhouden (voor cyclische apparaten zoals koelkasten)
    duty_cycle_ref: float   = 0.0    # Referentie duty-cycle
    duty_cycle_now: float   = 0.0    # Huidige duty-cycle
    duty_samples:   int     = 0
    # Tijdstempel van de eerste/laatste drift
    first_drift_date: str   = ""
    last_updated:     str   = ""

    @property
    def drift_ratio(self) -> float:
        if self.baseline_w <= 0:
            return 1.0
        return self.current_avg_w / self.baseline_w

    @property
    def drift_pct(self) -> float:
        return round((self.drift_ratio - 1.0) * 100, 1)

    @property
    def has_alert(self) -> bool:
        return self.baseline_frozen and self.drift_ratio >= ALERT_THRESHOLD

    @property
    def has_warning(self) -> bool:
        return self.baseline_frozen and self.drift_ratio >= DRIFT_THRESHOLD


@dataclass
class DriftStatus:
    """Output voor één apparaat."""
    device_id:  str
    label:      str
    baseline_w: float
    current_w:  float
    drift_pct:  float
    level:      str    # "ok" | "warning" | "alert"
    message:    str


@dataclass
class DriftReport:
    """Globaal rapport van alle apparaatdrift."""
    devices: list[DriftStatus]
    any_alert: bool
    any_warning: bool
    summary: str


class DeviceDriftTracker:
    """
    Detecteert efficiëntiedrift bij NILM-apparaten.

    Gebruik vanuit coordinator:
        tracker.record_detection(device_id, device_type, label, power_w)
        tracker.record_duty_cycle(device_id, duty_cycle)
        report = tracker.get_report()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._profiles: dict[str, DeviceDriftProfile] = {}
        self._dirty    = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for did, d in saved.items():
            self._profiles[did] = DeviceDriftProfile(
                device_id       = d.get("device_id", did),
                device_type     = d.get("device_type", "unknown"),
                label           = d.get("label", did),
                baseline_w      = float(d.get("baseline_w", 0)),
                current_avg_w   = float(d.get("current_avg_w", 0)),
                samples_total   = int(d.get("samples_total", 0)),
                baseline_frozen = bool(d.get("baseline_frozen", False)),
                duty_cycle_ref  = float(d.get("duty_cycle_ref", 0)),
                duty_cycle_now  = float(d.get("duty_cycle_now", 0)),
                duty_samples    = int(d.get("duty_samples", 0)),
                first_drift_date= d.get("first_drift_date", ""),
                last_updated    = d.get("last_updated", ""),
            )
        _LOGGER.info("DeviceDriftTracker: %d profielen geladen", len(self._profiles))

    def record_detection(
        self,
        device_id: str,
        device_type: str,
        label: str,
        power_w: float,
    ) -> None:
        """Registreer een NILM-detectie met actueel vermogen."""
        if power_w <= 0:
            return

        if device_id not in self._profiles:
            self._profiles[device_id] = DeviceDriftProfile(
                device_id=device_id, device_type=device_type, label=label
            )

        profile = self._profiles[device_id]
        profile.label       = label
        profile.device_type = device_type

        if not profile.baseline_frozen:
            # Leer baseline: EMA maar traag, vries na genoeg samples
            if profile.samples_total == 0:
                profile.baseline_w   = power_w
                profile.current_avg_w = power_w
            else:
                profile.baseline_w   = ALPHA_BASELINE * power_w + (1 - ALPHA_BASELINE) * profile.baseline_w
                profile.current_avg_w = ALPHA_CURRENT * power_w + (1 - ALPHA_CURRENT) * profile.current_avg_w

            if profile.samples_total >= MIN_BASELINE_SAMPLES:
                profile.baseline_frozen = True
                _LOGGER.info(
                    "DeviceDrift '%s': baseline vastgezet op %.0f W (na %d metingen)",
                    label, profile.baseline_w, profile.samples_total,
                )
        else:
            # Update lopend gemiddelde (sneller dan baseline)
            profile.current_avg_w = ALPHA_CURRENT * power_w + (1 - ALPHA_CURRENT) * profile.current_avg_w

            # Log eerste drift-moment
            if profile.has_warning and not profile.first_drift_date:
                profile.first_drift_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                _LOGGER.warning(
                    "DeviceDrift '%s': drift gedetecteerd! %.0f W → %.0f W (+%.1f%%)",
                    label, profile.baseline_w, profile.current_avg_w, profile.drift_pct,
                )

        profile.samples_total += 1
        profile.last_updated   = datetime.now(timezone.utc).isoformat()
        self._dirty = True

    def record_duty_cycle(self, device_id: str, duty_cycle: float) -> None:
        """Sla duty cycle op (voor cyclische apparaten zoals koelkast)."""
        if device_id not in self._profiles:
            return
        profile = self._profiles[device_id]

        if profile.duty_samples == 0:
            profile.duty_cycle_ref = duty_cycle
            profile.duty_cycle_now = duty_cycle
        elif not profile.baseline_frozen:
            profile.duty_cycle_ref = 0.02 * duty_cycle + 0.98 * profile.duty_cycle_ref
            profile.duty_cycle_now = duty_cycle
        else:
            profile.duty_cycle_now = 0.05 * duty_cycle + 0.95 * profile.duty_cycle_now

        profile.duty_samples += 1
        self._dirty = True

    def get_report(self) -> DriftReport:
        """Genereer een driftrapport voor alle apparaten."""
        statuses: list[DriftStatus] = []

        for profile in self._profiles.values():
            if not profile.baseline_frozen or profile.baseline_w <= 0:
                continue   # Nog geen baseline

            level   = "ok"
            message = f"{profile.label} verbruikt gemiddeld {profile.current_avg_w:.0f} W — normaal."

            if profile.has_alert:
                level = "alert"
                message = (
                    f"{profile.label} verbruikt {profile.drift_pct:.0f}% meer dan normaal "
                    f"({profile.current_avg_w:.0f} W vs baseline {profile.baseline_w:.0f} W). "
                    "Mogelijke oorzaak: slijtage, kalkafzetting of defect. Controleer het apparaat."
                )
            elif profile.has_warning:
                level = "warning"
                message = (
                    f"{profile.label} verbruikt {profile.drift_pct:.0f}% meer dan bij de start "
                    f"({profile.current_avg_w:.0f} W vs {profile.baseline_w:.0f} W). "
                    "Let op mogelijke efficiency-daling."
                )

            # Duty cycle check voor koelkast
            if (profile.device_type == "refrigerator"
                    and profile.duty_cycle_ref > 0
                    and profile.duty_samples >= 20):
                duty_drift = (profile.duty_cycle_now - profile.duty_cycle_ref) / max(profile.duty_cycle_ref, 0.01)
                if duty_drift > DUTY_DRIFT_THRESH:
                    level = max(level, "warning", key=["ok", "warning", "alert"].index)
                    pct   = round(duty_drift * 100)
                    message += (
                        f" Bovendien is de compressor-duty-cycle {pct:.0f}% hoger dan normaal, "
                        "wat kan wijzen op een slechte afdichting of te volle koelkast."
                    )

            statuses.append(DriftStatus(
                device_id   = profile.device_id,
                label       = profile.label,
                baseline_w  = round(profile.baseline_w),
                current_w   = round(profile.current_avg_w),
                drift_pct   = profile.drift_pct,
                level       = level,
                message     = message,
            ))

        any_alert   = any(s.level == "alert" for s in statuses)
        any_warning = any(s.level in ("alert", "warning") for s in statuses)

        if not statuses:
            summary = "Nog geen apparaatprofielen beschikbaar."
        elif any_alert:
            alerts = [s for s in statuses if s.level == "alert"]
            summary = "; ".join(s.message for s in alerts)
        elif any_warning:
            warnings = [s for s in statuses if s.level == "warning"]
            summary = "; ".join(s.message for s in warnings)
        else:
            summary = f"Alle {len(statuses)} apparaten presteren normaal."

        return DriftReport(
            devices     = statuses,
            any_alert   = any_alert,
            any_warning = any_warning,
            summary     = summary,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            data = {}
            for did, p in self._profiles.items():
                data[did] = {
                    "device_id":       p.device_id,
                    "device_type":     p.device_type,
                    "label":           p.label,
                    "baseline_w":      round(p.baseline_w, 2),
                    "current_avg_w":   round(p.current_avg_w, 2),
                    "samples_total":   p.samples_total,
                    "baseline_frozen": p.baseline_frozen,
                    "duty_cycle_ref":  round(p.duty_cycle_ref, 4),
                    "duty_cycle_now":  round(p.duty_cycle_now, 4),
                    "duty_samples":    p.duty_samples,
                    "first_drift_date":p.first_drift_date,
                    "last_updated":    p.last_updated,
                }
            await self._store.async_save(data)
            self._dirty     = False
            self._last_save = time.time()
