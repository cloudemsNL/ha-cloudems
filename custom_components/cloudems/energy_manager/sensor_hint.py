"""
CloudEMS Sensor Hint Engine — v1.10.2

Analyses grid power patterns to detect unconfigured sensors and notify the user.

Detections
──────────
1. **PV not configured**
   - Grid power drops significantly during daylight hours (07:00–19:00).
   - Pattern: import_w during midday is consistently lower than night-time baseline.
   - Confidence threshold: ≥ 3 consecutive days with midday drop > 300 W.
   - Notification: "Je net toont zonnepaneel-patronen. Heb je een omvormer sensor?"

2. **Battery not configured**
   - Grid power shows rapid step-changes (> 500 W in < 60 s) that are not
     correlated with known loads (no NILM event detected).
   - Pattern: sudden drops/rises that cancel each other within minutes.
   - Notification: "Je net toont batterij-achtige patronen. Heb je een batterij sensor?"

3. **Ampere/Voltage sensor completeness hint**
   - If power sensor configured but no current sensor → suggest adding for accuracy.
   - If current sensor configured but no voltage sensor → suggest adding voltage.

Hints are throttled: same hint not re-shown for 7 days after first shown.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_sensor_hints_v1"
STORAGE_VERSION = 1

# ── Tuning constants ──────────────────────────────────────────────────────────
# PV detection
PV_MIDDAY_DROP_W      = 300    # W — minimum midday vs night drop to flag PV
PV_MIN_DAYS           = 3      # days with clear pattern before flagging
PV_MIDDAY_HOURS       = (9, 16)  # hours considered "midday" for PV detection
PV_NIGHT_HOURS        = (1, 5)   # hours considered "night" baseline

# Battery detection
BATT_STEP_W           = 600    # W — minimum power step to consider battery-like
BATT_STEP_WINDOW_S    = 120    # seconds — step must reverse within this window
BATT_MIN_EVENTS       = 4      # events per day before flagging

# Throttle: don't repeat a hint for this many seconds (7 days)
HINT_THROTTLE_S       = 7 * 86_400

HINT_IDS = {
    "pv_missing":      "pv_missing",
    "battery_missing": "battery_missing",
    "add_current":     "add_current_sensor",
    "add_voltage":     "add_voltage_sensor",
}


@dataclass
class HintState:
    hint_id:        str
    title:          str
    message:        str
    action:         str      # "configure_solar" | "configure_battery" | "configure_phase"
    first_seen_ts:  float = field(default_factory=time.time)
    last_shown_ts:  float = 0.0
    dismissed:      bool  = False
    confidence:     float = 0.0   # 0.0–1.0


class SensorHintEngine:
    """
    Passive pattern observer — never blocks coordinator, never errors.

    Feed it grid power readings every cycle and it builds up evidence.
    When confidence crosses the threshold, a hint is emitted.
    """

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self._hass   = hass
        self._config = config
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._hints: dict[str, HintState] = {}

        # PV detection state
        self._midday_avg: deque  = deque(maxlen=48)   # (hour, grid_w) pairs
        self._night_baseline: Optional[float] = None
        self._pv_day_drops: int = 0

        # Battery detection state
        self._recent_powers: deque = deque(maxlen=30)   # (timestamp, grid_w)
        self._batt_events_today: int = 0
        self._last_batt_check_day: Optional[str] = None
        self._dirty: bool = False

    async def async_setup(self) -> None:
        data = await self._store.async_load()
        if data:
            for h in data.get("hints", []):
                self._hints[h["hint_id"]] = HintState(**h)
        _LOGGER.debug("SensorHintEngine ready (%d stored hints)", len(self._hints))

    async def async_save(self) -> None:
        if not self._dirty:
            return
        await self._store.async_save({
            "hints": [
                {
                    "hint_id":       h.hint_id,
                    "title":         h.title,
                    "message":       h.message,
                    "action":        h.action,
                    "first_seen_ts": h.first_seen_ts,
                    "last_shown_ts": h.last_shown_ts,
                    "dismissed":     h.dismissed,
                    "confidence":    h.confidence,
                }
                for h in self._hints.values()
            ]
        })
        self._dirty = False

    # ── Main update ───────────────────────────────────────────────────────────

    def update(
        self,
        grid_power_w: float,
        has_solar_sensor:   bool,
        has_battery_sensor: bool,
        has_current_l1:     bool,
        has_voltage_l1:     bool,
        has_power_l1:       bool,
    ) -> list[HintState]:
        """
        Feed current readings; return list of active (non-dismissed, non-throttled) hints.
        Safe to call every coordinator cycle (~10 s).
        """
        now  = time.time()
        hour = datetime.now(timezone.utc).hour
        day  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # ── PV pattern detection ───────────────────────────────────────────
        if not has_solar_sensor:
            self._midday_avg.append((hour, grid_power_w))
            self._detect_pv_pattern()

        # ── Battery pattern detection ──────────────────────────────────────
        if not has_battery_sensor:
            self._recent_powers.append((now, grid_power_w))
            # Reset daily counter
            if self._last_batt_check_day != day:
                self._batt_events_today    = 0
                self._last_batt_check_day  = day
            self._detect_battery_pattern()

        # ── Phase sensor completeness hints ───────────────────────────────
        self._check_phase_completeness(has_current_l1, has_voltage_l1, has_power_l1)

        # ── Return visible hints ───────────────────────────────────────────
        visible = [
            h for h in self._hints.values()
            if not h.dismissed and (now - h.last_shown_ts) > HINT_THROTTLE_S
        ]
        # Mark last_shown_ts for returned hints
        for h in visible:
            h.last_shown_ts = now

        return visible

    # ── PV detection ─────────────────────────────────────────────────────────

    def _detect_pv_pattern(self) -> None:
        midday_h = PV_MIDDAY_HOURS
        night_h  = PV_NIGHT_HOURS

        midday_vals = [w for h, w in self._midday_avg if midday_h[0] <= h < midday_h[1]]
        night_vals  = [w for h, w in self._midday_avg if night_h[0]  <= h < night_h[1]]

        if len(midday_vals) < 6 or len(night_vals) < 2:
            return

        midday_avg = sum(midday_vals) / len(midday_vals)
        night_avg  = sum(night_vals)  / len(night_vals)

        # Only apply on positive import values (exporting at night = already has PV probably)
        if night_avg < 0:
            return

        drop = night_avg - midday_avg
        if drop > PV_MIDDAY_DROP_W:
            self._pv_day_drops += 1
        else:
            self._pv_day_drops = max(0, self._pv_day_drops - 1)

        confidence = min(1.0, self._pv_day_drops / PV_MIN_DAYS)

        if confidence >= 0.8:
            self._emit_hint(
                hint_id    = HINT_IDS["pv_missing"],
                title      = "Zonnepanelen niet gekoppeld?",
                message    = (
                    f"Je netvermogen daalt overdag significant ({drop:.0f} W drop). "
                    "Dit lijkt op zonnepanelen. Koppel je omvormer sensor zodat CloudEMS "
                    "het PV-vermogen kan meten en de voorspelling kan leren."
                ),
                action     = "configure_solar",
                confidence = confidence,
            )

    # ── Battery detection ─────────────────────────────────────────────────────

    def _detect_battery_pattern(self) -> None:
        if len(self._recent_powers) < 10:
            return

        # Detect large rapid step-changes that reverse
        powers = list(self._recent_powers)
        for i in range(1, len(powers)):
            dt = powers[i][0] - powers[i-1][0]
            dw = abs(powers[i][1] - powers[i-1][1])
            if dw > BATT_STEP_W and dt < 30:
                # Look for reversal within window
                t0, w0 = powers[i]
                for j in range(i+1, len(powers)):
                    t1, w1 = powers[j]
                    if t1 - t0 > BATT_STEP_WINDOW_S:
                        break
                    if abs(w1 - w0) > BATT_STEP_W * 0.7:
                        self._batt_events_today += 1
                        break

        confidence = min(1.0, self._batt_events_today / BATT_MIN_EVENTS)
        if confidence >= 0.8:
            self._emit_hint(
                hint_id    = HINT_IDS["battery_missing"],
                title      = "Batterij niet gekoppeld?",
                message    = (
                    f"Je netstroom vertoont snelle stap-patronen ({self._batt_events_today} vandaag) "
                    "die typisch zijn voor een batterij die laadt/ontlaadt. "
                    "Koppel je batterij-vermogenssensor zodat CloudEMS de SoH kan bijhouden "
                    "en de batterij slim kan inplannen."
                ),
                action     = "configure_battery",
                confidence = confidence,
            )

    # ── Phase sensor completeness ─────────────────────────────────────────────

    def _check_phase_completeness(
        self, has_current: bool, has_voltage: bool, has_power: bool
    ) -> None:
        # If user has power sensor but no current sensor → suggest adding CT clamp
        if has_power and not has_current:
            self._emit_hint(
                hint_id    = HINT_IDS["add_current"],
                title      = "Nauwkeurigheid verbeteren met stroomsensor",
                message    = (
                    "Je hebt een vermogenssensor maar geen stroomsensor (A) per fase. "
                    "CloudEMS berekent stroom via I = P / V (230 V standaard), maar "
                    "een CT-klem per fase geeft een nauwkeuriger beeld van de belasting."
                ),
                action     = "configure_phase",
                confidence = 1.0,
            )

        # If user has current but no voltage → suggest voltage sensor
        if has_current and not has_voltage:
            self._emit_hint(
                hint_id    = HINT_IDS["add_voltage"],
                title      = "Spanningssensor toevoegen voor hogere nauwkeurigheid",
                message    = (
                    "Je hebt een stroomsensor maar geen spanningssensor. "
                    "CloudEMS gebruikt nu 230 V als aanname voor P = U × I. "
                    "Voeg een spanningssensor toe voor exactere vermogensberekening."
                ),
                action     = "configure_phase",
                confidence = 0.8,
            )

    # ── Emit helper ───────────────────────────────────────────────────────────

    def _emit_hint(
        self, hint_id: str, title: str, message: str,
        action: str, confidence: float
    ) -> None:
        if hint_id in self._hints and self._hints[hint_id].dismissed:
            return  # User dismissed → don't re-add
        existing = self._hints.get(hint_id)
        if existing:
            existing.confidence = confidence
        else:
            self._hints[hint_id] = HintState(
                hint_id    = hint_id,
                title      = title,
                message    = message,
                action     = action,
                confidence = confidence,
            )
            self._dirty = True
            _LOGGER.info("SensorHintEngine: new hint '%s' (confidence %.0f%%)", hint_id, confidence * 100)

    # ── Public API ────────────────────────────────────────────────────────────

    def dismiss_hint(self, hint_id: str) -> None:
        if hint_id in self._hints:
            self._hints[hint_id].dismissed = True
            self._dirty = True

    def get_all_hints(self) -> list[dict]:
        return [
            {
                "hint_id":    h.hint_id,
                "title":      h.title,
                "message":    h.message,
                "action":     h.action,
                "confidence": round(h.confidence, 2),
                "dismissed":  h.dismissed,
            }
            for h in self._hints.values()
        ]
