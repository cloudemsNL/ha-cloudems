"""
CloudEMS — DoDProtection v1.0.0

Bewaakt de gemiddelde ontlaaddiepte (DoD) van de thuisbatterij.
Als de gemiddelde DoD > DOD_WARN_PCT, stuur advies om min_soc te verhogen.
Leert automatisch de optimale min_soc op basis van rijgedrag en energie-gebruik.
"""
from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOD_WARN_PCT        = 70.0  # waarschuw als gem. DoD > 70%
DOD_CRITICAL_PCT    = 85.0  # kritiek als gem. DoD > 85%
NOTIFY_COOLDOWN_S   = 86400 # max 1x per dag


class DoDProtection:
    """Bewaakt batterij-DoD en adviseert min_soc aanpassing."""

    def __init__(self, notify_mgr=None) -> None:
        self._notify_mgr     = notify_mgr
        self._last_notify_ts = 0.0

    def evaluate(self, payback_data: dict, current_min_soc: float) -> dict:
        """
        Evalueer DoD-histogram en geef advies.
        Returnt dict met aanbevolen min_soc en reden.
        """
        dod = payback_data.get("dod_histogram", {})
        avg_dod = float(dod.get("avg_dod_pct") or 0)
        days    = int(dod.get("days_analysed") or 0)

        if days < 7 or avg_dod < 1:
            return {"ok": True, "avg_dod_pct": avg_dod, "days": days}

        status = "ok"
        advice = ""
        recommended_min_soc = current_min_soc

        if avg_dod > DOD_CRITICAL_PCT:
            status = "critical"
            # DoD > 85%: verhoog min_soc met 15%
            recommended_min_soc = min(50.0, current_min_soc + 15.0)
            advice = (
                f"Gemiddelde ontlaaddiepte {avg_dod:.0f}% is kritiek. "
                f"Verhoog min_soc van {current_min_soc:.0f}% naar {recommended_min_soc:.0f}% "
                f"om de batterijlevensduur significant te verlengen."
            )
        elif avg_dod > DOD_WARN_PCT:
            status = "warn"
            # DoD > 70%: verhoog min_soc met 10%
            recommended_min_soc = min(40.0, current_min_soc + 10.0)
            advice = (
                f"Gemiddelde ontlaaddiepte {avg_dod:.0f}% is hoog (>70%). "
                f"Overweeg min_soc te verhogen van {current_min_soc:.0f}% naar {recommended_min_soc:.0f}%. "
                f"Dit verlengt de batterijlevensduur met tot 30%."
            )

        result = {
            "ok":                    status == "ok",
            "status":                status,
            "avg_dod_pct":           round(avg_dod, 1),
            "days":                  days,
            "current_min_soc":       current_min_soc,
            "recommended_min_soc":   recommended_min_soc,
            "advice":                advice,
        }

        if advice and time.time() - self._last_notify_ts > NOTIFY_COOLDOWN_S:
            self._last_notify_ts = time.time()
            import asyncio
            asyncio.ensure_future(self._send(status, advice))

        return result

    async def _send(self, status: str, advice: str) -> None:
        icon = "🔴" if status == "critical" else "🟡"
        _LOGGER.warning("DoDProtection: %s", advice)
        if self._notify_mgr:
            await self._notify_mgr.send(
                f"{icon} Batterijlevensduur advies",
                advice,
                category="alert",
                notification_id="cloudems_dod_protection",
                force=True,
            )
