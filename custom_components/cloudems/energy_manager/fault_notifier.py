# -*- coding: utf-8 -*-
"""
CloudEMS Fault Notifier — v1.0.0

Verbindt twee bestaande fault-detectie bronnen met HA persistent_notifications:

BRON 1: DeviceDriftTracker (energy_manager/device_drift.py)
  Detecteert wanneer een apparaat structureel meer verbruikt dan zijn baseline.
  Was al beschikbaar als data in coordinator.data["device_drift"] maar
  produceerde nooit een gebruikersmelding.

BRON 2: DevicePowerProfile.anomaly_flag (nilm/device_profile.py)
  Detecteert een kWh-anomalie op maandbasis (z-score).
  Was al berekend maar werd nooit naar de gebruiker gecommuniceerd.

NIEUW in v1.0:
  - Beide bronnen worden gecombineerd in één notificatiekanaal
  - Per apparaat wordt een schatting gemaakt van de extra kosten per maand
  - Notificaties worden per device_id gededupliceerd (geen spam)
  - Na 7 dagen zonder nieuwe detectie wordt een notificatie automatisch opgelost
  - Drempelwaarden: DRIFT ≥ 30% + ≥ 50W absoluut verschil → waarschuwing
                    DRIFT ≥ 50% + ≥ 100W absoluut verschil → alert

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

_LOGGER = logging.getLogger(__name__)

# Drempelwaarden voor notificaties
DRIFT_WARN_PCT    = 0.30    # 30% boven baseline
DRIFT_ALERT_PCT   = 0.50    # 50% boven baseline
DRIFT_WARN_ABS_W  = 50.0    # minimaal 50W absoluut verschil
DRIFT_ALERT_ABS_W = 100.0   # minimaal 100W absoluut verschil
NOTIF_COOLDOWN_S  = 86_400  # max 1 notificatie per apparaat per dag
NOTIF_RESOLVE_S   = 604_800 # 7 dagen → notificatie automatisch opgelost

# Gemiddeld gebruik apparaat voor kostenberekening
DEFAULT_HOURS_PER_DAY: Dict[str, float] = {
    "refrigerator":    24.0,
    "washing_machine":  1.5,
    "dryer":            1.5,
    "dishwasher":       1.5,
    "heat_pump":       12.0,
    "boiler":           6.0,
    "ev_charger":       2.0,
    "oven":             0.5,
    "default":          4.0,
}


@dataclass
class FaultRecord:
    device_id:      str
    label:          str
    device_type:    str
    level:          str       # "warning" | "alert"
    drift_pct:      float
    extra_w:        float
    extra_eur_month: float
    message:        str
    first_seen:     float
    last_notified:  float = 0.0


class FaultNotifier:
    """
    Vertaalt drift/anomaly-signalen naar HA persistent_notifications.

    Gebruik in coordinator._async_update_data():
        faults = self._fault_notifier.check(
            drift_data      = drift_data,
            nilm_profiles   = self._nilm._profiles,
            energy_price    = current_price or 0.25,
        )
    """

    def __init__(self, hass) -> None:
        self._hass   = hass
        self._faults: Dict[str, FaultRecord] = {}

    def check(
        self,
        drift_data:    dict,
        nilm_profiles: dict,
        energy_price:  float = 0.25,
    ) -> int:
        """
        Controleer op nieuwe faults en stuur notificaties.
        Geeft het aantal actieve faults terug.
        """
        now = time.time()
        new_alerts = 0

        # ── Bron 1: DeviceDriftTracker ────────────────────────────────────────
        for dev in drift_data.get("devices", []):
            did   = dev.get("device_id", "")
            label = dev.get("label", did)
            level = dev.get("level", "")
            drift = float(dev.get("drift_pct", 0)) / 100.0
            base_w  = float(dev.get("baseline_w", 0))
            curr_w  = float(dev.get("current_w", 0))
            extra_w = max(0.0, curr_w - base_w)
            dtype   = dev.get("device_type", "default")

            if not did or level not in ("warning", "alert"):
                continue
            if (level == "warning" and (drift < DRIFT_WARN_PCT or extra_w < DRIFT_WARN_ABS_W)):
                continue
            if (level == "alert" and (drift < DRIFT_ALERT_PCT or extra_w < DRIFT_ALERT_ABS_W)):
                continue

            hours_day  = DEFAULT_HOURS_PER_DAY.get(dtype, DEFAULT_HOURS_PER_DAY["default"])
            extra_kwh  = extra_w / 1000.0 * hours_day * 30
            extra_eur  = round(extra_kwh * energy_price, 2)

            if did not in self._faults:
                self._faults[did] = FaultRecord(
                    device_id=did, label=label, device_type=dtype,
                    level=level, drift_pct=drift, extra_w=extra_w,
                    extra_eur_month=extra_eur,
                    message=dev.get("message", ""),
                    first_seen=now,
                )

            rec = self._faults[did]
            rec.extra_w = extra_w
            rec.extra_eur_month = extra_eur
            rec.drift_pct = drift
            rec.level = level

            if now - rec.last_notified > NOTIF_COOLDOWN_S:
                self._send_drift_notification(rec)
                rec.last_notified = now
                new_alerts += 1

        # ── Bron 2: NILM DevicePowerProfile anomaly_flag ─────────────────────
        for did, profile in nilm_profiles.items():
            if not getattr(profile, "anomaly_flag", False):
                continue
            reason = getattr(profile, "anomaly_reason", "onbekend")
            label  = f"NILM {did[:20]}"
            key    = f"kwh_anomaly_{did}"

            if key not in self._faults:
                self._faults[key] = FaultRecord(
                    device_id=key, label=label, device_type="unknown",
                    level="warning", drift_pct=0.0, extra_w=0.0,
                    extra_eur_month=0.0,
                    message=reason,
                    first_seen=now,
                )

            rec = self._faults[key]
            if now - rec.last_notified > NOTIF_COOLDOWN_S:
                self._send_kwh_anomaly_notification(rec)
                rec.last_notified = now
                new_alerts += 1

        # ── Opruimen van oude faults ──────────────────────────────────────────
        to_remove = [
            k for k, v in self._faults.items()
            if now - v.first_seen > NOTIF_RESOLVE_S
        ]
        for k in to_remove:
            self._faults.pop(k, None)
            notif_id = f"cloudems_fault_{k}"
            try:
                self._hass.components.persistent_notification.async_dismiss(notif_id)
            except Exception:
                pass

        return len(self._faults)

    def _send_drift_notification(self, rec: FaultRecord) -> None:
        icon  = "🔴" if rec.level == "alert" else "🟡"
        title = f"{icon} CloudEMS — Apparaat verbruikt meer dan normaal"
        msg   = (
            f"**{rec.label}** verbruikt **{rec.drift_pct*100:.0f}% meer** dan normaal "
            f"({rec.extra_w:.0f}W extra).\n\n"
            f"Mogelijke oorzaak: slijtage, kalkafzetting of defect.\n"
            f"Geschatte extra kosten: **\u20ac{rec.extra_eur_month:.2f}/maand**.\n\n"
            f"_{rec.message}_"
        )
        try:
            self._hass.components.persistent_notification.async_create(
                message         = msg,
                title           = title,
                notification_id = f"cloudems_fault_{rec.device_id}",
            )
            _LOGGER.info("FaultNotifier: %s drift-alert voor %s", rec.level, rec.label)
        except Exception as ex:
            _LOGGER.debug("FaultNotifier notificatie fout: %s", ex)

    def _send_kwh_anomaly_notification(self, rec: FaultRecord) -> None:
        title = "🟡 CloudEMS — Ongebruikelijk maandverbruik"
        msg   = (
            f"**{rec.label}** heeft een afwijkend maandverbruik.\n\n"
            f"{rec.message}\n\n"
            f"Controleer of dit apparaat normaal functioneert."
        )
        try:
            self._hass.components.persistent_notification.async_create(
                message         = msg,
                title           = title,
                notification_id = f"cloudems_fault_{rec.device_id}",
            )
        except Exception as ex:
            _LOGGER.debug("FaultNotifier kWh-anomalie notificatie fout: %s", ex)

    def get_active_faults(self) -> list:
        return [
            {
                "device_id":       r.device_id,
                "label":           r.label,
                "level":           r.level,
                "extra_w":         r.extra_w,
                "extra_eur_month": r.extra_eur_month,
                "message":         r.message,
            }
            for r in self._faults.values()
        ]
