"""
CloudEMS — NILMAnomalyPush v1.0.0

Bewaakt realtime NILM-verbruik per apparaat.
Als een apparaat > THRESHOLD × geleerd gemiddelde verbruikt voor > MIN_DURATION,
stuurt een push-notificatie.

Voorbeelden:
  - Wasmachine doet er ineens 2× zo lang over → condenspomp defect?
  - Koelkast trekt ineens 3× meer vermogen → compressor problemen?
"""
from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ANOMALY_THRESHOLD   = 2.5   # huidig > 2.5× geleerd gemiddelde = anomalie
MIN_POWER_W         = 50    # onder 50W geen anomalie (stand-by ruis)
MIN_DURATION_S      = 300   # minimaal 5 minuten aanhoudend
NOTIFY_COOLDOWN_S   = 7200  # max 1x per 2 uur per apparaat


class NILMAnomalyPush:
    """Realtime anomalie-detector voor NILM-apparaten."""

    def __init__(self, notify_mgr=None) -> None:
        self._notify_mgr  = notify_mgr
        self._anomaly_ts: dict[str, float] = {}   # device_id → start_ts anomalie
        self._notified:   dict[str, float] = {}   # device_id → last_notify_ts

    def tick(self, nilm_devices: list[dict]) -> list[dict]:
        """Verwerk NILM-devices. Returnt lijst van gedetecteerde anomalieën."""
        now       = time.time()
        detected  = []

        for dev in nilm_devices:
            dev_id       = dev.get("id") or dev.get("device_id") or ""
            name         = dev.get("user_name") or dev.get("name") or dev_id
            current_w    = float(dev.get("power_w") or 0)
            learned_w    = float(dev.get("learned_power_w") or 0)

            if learned_w < MIN_POWER_W or current_w < MIN_POWER_W:
                self._anomaly_ts.pop(dev_id, None)
                continue

            ratio = current_w / learned_w

            if ratio >= ANOMALY_THRESHOLD:
                # Begin of aanhouden van anomalie
                if dev_id not in self._anomaly_ts:
                    self._anomaly_ts[dev_id] = now
                elif now - self._anomaly_ts[dev_id] >= MIN_DURATION_S:
                    # Lang genoeg aangehouden → melding
                    last_notif = self._notified.get(dev_id, 0)
                    if now - last_notif >= NOTIFY_COOLDOWN_S:
                        self._notified[dev_id] = now
                        anomaly = {
                            "device_id":  dev_id,
                            "name":       name,
                            "current_w":  round(current_w),
                            "learned_w":  round(learned_w),
                            "ratio":      round(ratio, 1),
                            "duration_s": round(now - self._anomaly_ts[dev_id]),
                        }
                        detected.append(anomaly)
                        import asyncio
                        asyncio.ensure_future(self._send(anomaly))
            else:
                self._anomaly_ts.pop(dev_id, None)

        return detected

    async def _send(self, a: dict) -> None:
        dur_min = a["duration_s"] // 60
        msg = (
            f"{a['name']} verbruikt {a['current_w']}W — "
            f"{a['ratio']}× meer dan normaal ({a['learned_w']}W). "
            f"Al {dur_min} minuten aangehouden. "
            f"Mogelijke oorzaak: defect, deur open of onverwacht gebruik."
        )
        _LOGGER.warning("NILMAnomalyPush: %s", msg)
        if self._notify_mgr:
            await self._notify_mgr.send(
                f"⚠️ Ongewoon verbruik: {a['name']}",
                msg,
                category="alert",
                notification_id=f"cloudems_nilm_anomaly_{a['device_id'].replace('.','_')}",
            )
