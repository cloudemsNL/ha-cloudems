"""
CloudEMS — frozen_sensor_watchdog.py  v1.0.0

Detecteert bevroren sensoren: sensoren die te lang dezelfde waarde houden
terwijl andere data aantoont dat ze zouden moeten veranderen.

Probleem: coordinator levert nog data aan NILM/fase maar de home/grid sensor
bevriest op 0W terwijl batterij ontlaadt en import niet nul is.

Aanpak:
  - Houd per kritieke sensor de laatste N waarden bij
  - Als de sensor langer dan FREEZE_THRESHOLD_S dezelfde waarde heeft
    én er "contradictie-bewijs" is (andere sensoren zeggen iets anders)
    → meld frozen sensor + trigger coordinator refresh
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

_LOGGER = logging.getLogger(__name__)

FREEZE_THRESHOLD_S  = 90    # na 90s zelfde waarde = verdacht
CONTRADICTION_W     = 200   # als andere sensoren >200W tonen en home=0 → frozen
HISTORY_SIZE        = 30    # bewaar laatste 30 metingen


@dataclass
class SensorHistory:
    name:        str
    values:      deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    timestamps:  deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    frozen_since: Optional[float] = None
    last_alert_ts: float = 0.0

    def push(self, value: float, ts: float) -> None:
        self.values.append(value)
        self.timestamps.append(ts)

    @property
    def is_frozen(self) -> bool:
        """True als de laatste waarden allemaal gelijk zijn."""
        if len(self.values) < 3:
            return False
        last = list(self.values)[-5:]  # kijk naar laatste 5
        return len(set(round(v, 1) for v in last)) == 1

    @property
    def frozen_duration_s(self) -> float:
        if self.frozen_since is None:
            return 0.0
        return time.time() - self.frozen_since

    @property
    def current_value(self) -> Optional[float]:
        return self.values[-1] if self.values else None


class FrozenSensorWatchdog:
    """
    Bewaakt kritieke CloudEMS sensoren op bevriezen.

    Gebruik:
        watchdog = FrozenSensorWatchdog(refresh_callback)
        watchdog.tick(home_w=1500, grid_w=3600, solar_w=0, battery_w=-500)
    """

    def __init__(
        self,
        refresh_cb: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._refresh_cb = refresh_cb
        self._sensors = {
            "home":    SensorHistory("home_rest_w"),
            "grid":    SensorHistory("grid_w"),
            "solar":   SensorHistory("solar_w"),
            "battery": SensorHistory("battery_w"),
        }
        self._freeze_count = 0
        self._last_refresh_ts = 0.0
        self._alerts: list[dict] = []

    async def tick(
        self,
        home_w:    Optional[float],
        grid_w:    Optional[float],
        solar_w:   Optional[float],
        battery_w: Optional[float],
    ) -> list[str]:
        """
        Aanroepen elke coordinator tick.
        Returnt lijst van frozen sensor namen (leeg als alles OK).
        """
        now = time.time()
        data = {
            "home":    home_w,
            "grid":    grid_w,
            "solar":   solar_w,
            "battery": battery_w,
        }

        frozen = []

        for key, val in data.items():
            if val is None:
                continue
            hist = self._sensors[key]
            hist.push(val, now)

            if hist.is_frozen:
                if hist.frozen_since is None:
                    hist.frozen_since = now
            else:
                hist.frozen_since = None

        home_hist = self._sensors["home"]
        grid_hist = self._sensors["grid"]
        batt_hist = self._sensors["battery"]
        sol_hist  = self._sensors["solar"]

        home_val = home_hist.current_value or 0
        grid_val = grid_hist.current_value or 0
        batt_val = batt_hist.current_value or 0

        # ── Geval 1 (MEEST VOORKOMEND): grid+battery+solar allemaal bevroren op 0
        # terwijl house een reële waarde toont
        # Dit is het patroon uit de Zonneplan/P1 sensor freeze
        sources_frozen_on_zero = (
            abs(grid_val) < 50 and grid_hist.is_frozen and
            abs(batt_val) < 50 and batt_hist.is_frozen
        )
        # house_real: de house waarde is substantieel (>200W), ongeacht of hij varieert
        # (in een echte freeze blijft house constant maar is wel reeel)
        house_real = abs(home_val) > CONTRADICTION_W

        if sources_frozen_on_zero and house_real:
            alert_key = "grid+battery"
            # Gebruik grid_hist als primaire voor timing
            if grid_hist.frozen_since is None:
                grid_hist.frozen_since = now
            if grid_hist.frozen_duration_s > FREEZE_THRESHOLD_S:
                frozen.append("grid")
                frozen.append("battery")
                if now - grid_hist.last_alert_ts > 120:
                    grid_hist.last_alert_ts = now
                    _LOGGER.warning(
                        "FrozenSensorWatchdog: grid+battery bevroren op 0W "
                        "gedurende %.0fs terwijl house=%.0fW. "
                        "Waarschijnlijk P1/Zonneplan sensor timeout. Refresh gestart.",
                        grid_hist.frozen_duration_s, home_val,
                    )
                    await self._do_refresh()
        else:
            grid_hist.frozen_since = None

        # ── Geval 2: home sensor bevroren op 0 terwijl grid of battery actief
        if (home_hist.frozen_since is not None
                and home_hist.frozen_duration_s > FREEZE_THRESHOLD_S):
            evidence = max(abs(grid_val), abs(batt_val))
            if abs(home_val) < 50 and evidence > CONTRADICTION_W:
                frozen.append("home")
                if now - home_hist.last_alert_ts > 120:
                    home_hist.last_alert_ts = now
                    _LOGGER.warning(
                        "FrozenSensorWatchdog: home_rest_w bevroren op %.0fW "
                        "gedurende %.0fs — grid=%.0fW batterij=%.0fW. Refresh gestart.",
                        home_val, home_hist.frozen_duration_s, grid_val, batt_val,
                    )
                    await self._do_refresh()

        return frozen

    async def _do_refresh(self) -> None:
        """Trigger coordinator refresh om bevroren sensoren los te schudden."""
        now = time.time()
        if now - self._last_refresh_ts < 60:
            return  # max 1 refresh per minuut
        self._last_refresh_ts = now
        self._freeze_count += 1
        if self._refresh_cb:
            try:
                await self._refresh_cb()
                _LOGGER.info(
                    "FrozenSensorWatchdog: coordinator refresh #%d uitgevoerd",
                    self._freeze_count,
                )
            except Exception as err:
                _LOGGER.error("FrozenSensorWatchdog: refresh mislukt: %s", err)

    @property
    def stats(self) -> dict:
        return {
            "freeze_count": self._freeze_count,
            "sensors": {
                k: {
                    "frozen": v.frozen_since is not None,
                    "frozen_s": round(v.frozen_duration_s),
                    "current": v.current_value,
                }
                for k, v in self._sensors.items()
            }
        }
