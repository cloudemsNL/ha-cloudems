"""
CloudEMS — PhaseAdvisor v1.0.0

Leert welke fases structureel zwaarder belast zijn op basis van
historische fase-stromen. Geeft advies via NotificationManager als
er structurele onbalans is (> 4A verschil gemiddeld over de dag).

Gebruikt bestaande fase-data van de P1/HAFallbackReader.
"""
from __future__ import annotations
import logging
import time
from collections import deque
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

IMBALANCE_THRESHOLD_A   = 4.0   # A verschil tussen zwaarste en lichtste fase
ADVISE_COOLDOWN_S       = 86400  # max 1x per dag notificatie
HISTORY_SAMPLES         = 360    # 1u bij 10s interval


class PhaseAdvisor:
    """Bewaakt fase-onbalans en geeft advies."""

    def __init__(self, hass: "HomeAssistant", notify_mgr=None) -> None:
        self._hass       = hass
        self._notify_mgr = notify_mgr
        self._history: dict[str, deque] = {
            "L1": deque(maxlen=HISTORY_SAMPLES),
            "L2": deque(maxlen=HISTORY_SAMPLES),
            "L3": deque(maxlen=HISTORY_SAMPLES),
        }
        self._last_advice_ts: float = 0.0
        self._imbalance_count: int  = 0  # aaneengesloten ticks met onbalans

    def tick(self, phase_currents: dict[str, float]) -> dict:
        """
        Verwerk fase-stromen. Geeft status dict terug.
        phase_currents: {"L1": 12.3, "L2": 8.1, "L3": 15.2}  (A)
        """
        now = time.time()
        for ph in ("L1", "L2", "L3"):
            val = phase_currents.get(ph)
            if val is not None:
                self._history[ph].append(abs(float(val)))

        status = self._analyse()
        if status.get("imbalanced") and now - self._last_advice_ts > ADVISE_COOLDOWN_S:
            self._last_advice_ts = now
            import asyncio
            asyncio.ensure_future(self._send_advice(status))

        return status

    def _analyse(self) -> dict:
        """Analyseer gemiddelde belasting per fase."""
        avgs = {}
        for ph, hist in self._history.items():
            if len(hist) >= 10:
                avgs[ph] = round(sum(hist) / len(hist), 2)

        if len(avgs) < 3:
            return {"imbalanced": False, "averages": avgs}

        heaviest = max(avgs, key=avgs.get)
        lightest = min(avgs, key=avgs.get)
        spread   = round(avgs[heaviest] - avgs[lightest], 2)
        imbalanced = spread >= IMBALANCE_THRESHOLD_A

        return {
            "imbalanced":    imbalanced,
            "spread_a":      spread,
            "heaviest_phase": heaviest,
            "lightest_phase": lightest,
            "averages":      avgs,
            "advice": (
                f"Fase {heaviest} is structureel {spread:.1f}A zwaarder dan {lightest}. "
                f"Overweeg om een apparaat van {heaviest} naar {lightest} te verplaatsen "
                f"(bijv. EV-lader of wasmachine)."
            ) if imbalanced else "",
        }

    async def _send_advice(self, status: dict) -> None:
        msg = status.get("advice", "")
        if not msg:
            return
        avgs = status.get("averages", {})
        detail = " · ".join(f"{ph}: {avgs[ph]:.1f}A" for ph in ("L1","L2","L3") if ph in avgs)
        full_msg = f"{msg}\n\nGemiddelde belasting (laatste uur): {detail}"
        if self._notify_mgr:
            await self._notify_mgr.send(
                "⚡ Fase-onbalans gedetecteerd", full_msg,
                category="alert",
                notification_id="cloudems_phase_imbalance",
            )
        else:
            _LOGGER.warning("PhaseAdvisor: %s", msg)

    def get_status(self) -> dict:
        return self._analyse()
