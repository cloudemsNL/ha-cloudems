"""
time_pattern_learner.py — CloudEMS v4.0.4
==========================================
NILM Tijdpatroon Leren — uurhistogram per apparaat per weekdag.

Leert wanneer elk apparaat typisch actief is:
  - uurhistogram[weekdag][uur] = aantal keer actief
  - 7 weekdagen × 24 uur = 168 buckets per apparaat
  - Normalisatie → kansmatrix voor anomalie-detectie

Toepassingen:
  1. Anomalie-detectie — "wasmachine draait om 03:00, dit is ongewoon"
  2. BDE planning — "wasmachine draait altijd di/do/za 10:00 → vermijd laden op die momenten"
  3. Dashboard — visuele heatmap van gebruikspatronen

Persistent via HA Store — overleeft herstart.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_TIME_PATTERNS = "cloudems_nilm_time_patterns_v1"
STORAGE_VERSION = 1

# Minimale on-events om patroon als "betrouwbaar" te beschouwen
MIN_EVENTS_FOR_PATTERN = 5
# Anomalie-drempel: kans < x% voor dit uur/weekdag → anomalie
ANOMALY_THRESHOLD_PCT = 3.0
# Max events bijhouden per bucket (cap om geheugen te beperken)
MAX_EVENTS_PER_BUCKET = 500


class TimePatternLearner:
    """
    Uurhistogram per apparaat per weekdag.

    Gebruik:
        learner = TimePatternLearner(store)
        await learner.async_load()

        # Bij elk on-event:
        learner.record_on(device_id, device_type, timestamp)

        # Anomalie-check:
        is_odd = learner.is_anomalous(device_id, timestamp)

        # Voor BDE planning:
        busy_hours = learner.get_typical_hours(device_id)
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        # {device_id: {weekday(0-6): {hour(0-23): count}}}
        self._data: dict[str, dict[int, dict[int, int]]] = {}
        # {device_id: total_events}
        self._totals: dict[str, int] = {}
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
            if raw and isinstance(raw.get("patterns"), dict):
                for did, wd_data in raw["patterns"].items():
                    self._data[did] = {
                        int(wd): {int(h): int(c) for h, c in hr.items()}
                        for wd, hr in wd_data.items()
                    }
                self._totals = {k: int(v) for k, v in raw.get("totals", {}).items()}
                _LOGGER.debug(
                    "TimePatternLearner: %d apparaten geladen", len(self._data)
                )
        except Exception as err:
            _LOGGER.warning("TimePatternLearner: laden mislukt: %s", err)
        self._loaded = True

    def record_on(
        self,
        device_id: str,
        timestamp: float,
        save_now: bool = False,
    ) -> None:
        """
        Registreer een on-event voor dit apparaat op dit tijdstip.
        save_now=True voor expliciete persistentie (niet elke cyclus nodig).
        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        wd = dt.weekday()   # 0=maandag, 6=zondag
        hr = dt.hour

        if device_id not in self._data:
            self._data[device_id] = {}
        wd_map = self._data[device_id]
        if wd not in wd_map:
            wd_map[wd] = {}
        wd_map[wd][hr] = min(
            wd_map[wd].get(hr, 0) + 1,
            MAX_EVENTS_PER_BUCKET,
        )
        self._totals[device_id] = self._totals.get(device_id, 0) + 1

    async def async_save(self) -> None:
        try:
            await self._store.async_save({
                "version":  STORAGE_VERSION,
                "patterns": {
                    did: {str(wd): {str(h): c for h, c in hrs.items()}
                          for wd, hrs in wds.items()}
                    for did, wds in self._data.items()
                },
                "totals": self._totals,
            })
        except Exception as err:
            _LOGGER.warning("TimePatternLearner: opslaan mislukt: %s", err)

    def get_probability(self, device_id: str, weekday: int, hour: int) -> float:
        """
        Geeft de kans (0.0–1.0) dat dit apparaat actief is op weekdag/uur.
        Gebaseerd op genormaliseerd histogram.
        """
        wd_map = self._data.get(device_id, {})
        total_for_wd = sum(wd_map.get(weekday, {}).values())
        if total_for_wd == 0:
            return 0.0
        count = wd_map.get(weekday, {}).get(hour, 0)
        return round(count / total_for_wd, 4)

    def is_anomalous(
        self,
        device_id: str,
        timestamp: float,
        threshold_pct: float = ANOMALY_THRESHOLD_PCT,
    ) -> bool:
        """
        True als dit tijdstip ongewoon is voor dit apparaat.
        Alleen betrouwbaar als het apparaat MIN_EVENTS_FOR_PATTERN events heeft.
        """
        if self._totals.get(device_id, 0) < MIN_EVENTS_FOR_PATTERN:
            return False  # te weinig data
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        prob = self.get_probability(device_id, dt.weekday(), dt.hour)
        return prob < (threshold_pct / 100.0)

    def get_typical_hours(
        self, device_id: str, top_n: int = 5
    ) -> list[dict]:
        """
        Geeft de N meest typische (weekdag, uur) combinaties terug.
        Gebruikt door BDE om planning te informeren.

        Returns: [{weekday, hour, probability, label}]
        """
        wd_names = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        result = []
        for wd, hrs in self._data.get(device_id, {}).items():
            total = sum(hrs.values())
            if total == 0:
                continue
            for hr, cnt in hrs.items():
                result.append({
                    "weekday":     wd,
                    "hour":        hr,
                    "probability": round(cnt / total, 4),
                    "label":       f"{wd_names[wd]} {hr:02d}:00",
                })
        result.sort(key=lambda x: -x["probability"])
        return result[:top_n]

    def get_heatmap(self, device_id: str) -> list[list[int]]:
        """
        Geeft een 7×24 matrix terug [weekdag][uur] = count.
        Handig voor dashboard visualisatie.
        """
        matrix = [[0] * 24 for _ in range(7)]
        for wd, hrs in self._data.get(device_id, {}).items():
            for hr, cnt in hrs.items():
                matrix[wd][hr] = cnt
        return matrix

    def get_all_anomalous_now(
        self, active_device_ids: list[str], timestamp: float
    ) -> list[str]:
        """
        Geeft device_ids terug die nu actief zijn maar dat ongewoon is.
        Gebruikt door de coordinator voor persistent notifications.
        """
        return [
            did for did in active_device_ids
            if self.is_anomalous(did, timestamp)
        ]

    def get_diagnostics(self) -> dict:
        return {
            "devices_tracked":    len(self._data),
            "devices_reliable":   sum(
                1 for did, tot in self._totals.items()
                if tot >= MIN_EVENTS_FOR_PATTERN
            ),
            "top_devices": [
                {"device_id": did, "total_events": tot}
                for did, tot in sorted(
                    self._totals.items(), key=lambda x: -x[1]
                )[:5]
            ],
        }

    def on_device_removed(self, device_id: str) -> None:
        self._data.pop(device_id, None)
        self._totals.pop(device_id, None)
