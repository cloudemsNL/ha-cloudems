from __future__ import annotations
"""
CloudEMS Telemetry — Opt-in anonieme diagnostiek via Firebase Firestore REST API
GDPR-veilig: geen persoonlijke data, geen entiteit-namen, geen locatie.

Uploadt elk uur een samenvatting naar Firestore:
  Collection: cloudems_telemetry
  Document:   <installation_id>
  Subcollection: hours/<iso_hour>

Inhoud per uur-entry:
  - Versienummer + uptime
  - Beslissingen: categorie + actie + reden (geen label/entity_id)
  - Sensor errors: type (geen waarden)
  - Boiler cycli teller
  - Prestatie metrics: coordinator cyclus duur (ms)

Firebase project: cloudems-telemetry (Joan's project)
Firestore database: (default)
Toegang: API key voor schrijven, geen authenticatie nodig voor lezen door eigenaar
"""

import json
import logging
import os
import time
import uuid
from typing import Any

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY        = ".storage/cloudems_installation.json"
FIRESTORE_BASE_URL = "https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents"
COLLECTION         = "cloudems_telemetry"
MAX_HOURS          = 24 * 7   # 7 dagen rolling window in memory


class CloudEMSTelemetry:
    """Verzamelt en uploadt anonieme diagnostiekdata naar Firebase Firestore."""

    def __init__(self, hass, config_dir: str, version: str,
                 firebase_project_id: str = "",
                 firebase_api_key: str = "") -> None:
        self._hass               = hass
        self._config_dir         = config_dir
        self._version            = version
        self._project_id         = firebase_project_id
        self._api_key            = firebase_api_key
        self._install_id         = self._get_or_create_install_id()
        self._enabled            = False   # Opt-in — standaard uit
        self._start_ts           = time.time()
        self._last_upload        = 0.0
        self._reset_hour_buffer()

    # ── Publieke API ─────────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def configure(self, project_id: str, api_key: str) -> None:
        """Configureer Firebase project en API key vanuit CloudEMS instellingen."""
        self._project_id = project_id
        self._api_key    = api_key

    def record_decision(self, category: str, action: str, reason: str) -> None:
        """Sla een beslissing op — geen entiteit-namen, geen waarden."""
        if not self._enabled:
            return
        key = f"{category}:{action}"
        self._hour_decisions[key] = self._hour_decisions.get(key, 0) + 1
        reasons = self._hour_reasons.setdefault(category, set())
        if len(reasons) < 5:
            reasons.add(reason[:50])

    def record_error(self, error_type: str) -> None:
        """Sla een sensor/coordinator fout op — geen waarden."""
        if not self._enabled:
            return
        self._hour_errors[error_type] = self._hour_errors.get(error_type, 0) + 1

    def record_cycle_duration(self, duration_ms: float) -> None:
        """Sla coordinator cyclus duur op."""
        if not self._enabled:
            return
        self._cycle_durations.append(duration_ms)
        if len(self._cycle_durations) > 360:
            self._cycle_durations.pop(0)

    def record_boiler_cycle(self) -> None:
        """Teller voor boiler verwarmingscycli."""
        if not self._enabled:
            return
        self._boiler_cycles += 1

    async def async_tick(self) -> None:
        """Roep aan vanuit coordinator. Uploadt elk uur."""
        if not self._enabled or not self._project_id or not self._api_key:
            return
        now = time.time()
        if now - self._last_upload < 3600:
            return
        self._last_upload = now
        await self._hass.async_add_executor_job(self._upload_hour)

    # ── Intern ───────────────────────────────────────────────────────────────

    def _reset_hour_buffer(self) -> None:
        self._hour_decisions:   dict[str, int]  = {}
        self._hour_reasons:     dict[str, set]  = {}
        self._hour_errors:      dict[str, int]  = {}
        self._cycle_durations:  list[float]     = []
        self._boiler_cycles:    int             = 0

    def _build_hour_entry(self) -> dict:
        import datetime
        durations = self._cycle_durations
        return {
            "ts":           int(time.time()),
            "hour":         datetime.datetime.now().strftime("%Y-%m-%dT%H:00"),
            "version":      self._version,
            "uptime_h":     round((time.time() - self._start_ts) / 3600, 1),
            "decisions":    dict(self._hour_decisions),
            "reasons":      {k: list(v) for k, v in self._hour_reasons.items()},
            "errors":       dict(self._hour_errors),
            "boiler_cycles": self._boiler_cycles,
            "perf": {
                "cycle_avg_ms": round(sum(durations) / len(durations), 1) if durations else 0,
                "cycle_max_ms": round(max(durations), 1) if durations else 0,
                "cycle_p95_ms": round(sorted(durations)[int(len(durations) * 0.95)], 1)
                                if len(durations) > 20 else 0,
                "cycle_count":  len(durations),
            },
        }

    def _upload_hour(self) -> None:
        """Synchrone Firestore upload via REST API — geen SDK nodig."""
        import urllib.request
        import datetime

        entry   = self._build_hour_entry()
        self._reset_hour_buffer()

        hour_key = datetime.datetime.now().strftime("%Y%m%dT%H00")
        url = (
            f"{FIRESTORE_BASE_URL.format(project_id=self._project_id)}"
            f"/{COLLECTION}/{self._install_id}/hours/{hour_key}"
            f"?key={self._api_key}"
        )

        # Zet entry om naar Firestore document formaat
        doc = {"fields": {k: self._to_firestore(v) for k, v in entry.items()}}
        payload = json.dumps(doc).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="PATCH",   # PATCH = upsert in Firestore REST
                headers={
                    "Content-Type": "application/json",
                    "X-HTTP-Method-Override": "PATCH",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    _LOGGER.debug(
                        "CloudEMS telemetry: uur %s geüpload (%s)",
                        hour_key, self._install_id[:8]
                    )
                else:
                    _LOGGER.debug("CloudEMS telemetry: upload status %s", resp.status)
        except Exception as err:
            _LOGGER.debug("CloudEMS telemetry upload mislukt: %s", err)

        # Update installatie-metadata (versie, laatste upload)
        self._update_installation_doc()

    def _update_installation_doc(self) -> None:
        """Update het root document van deze installatie met metadata."""
        import urllib.request
        url = (
            f"{FIRESTORE_BASE_URL.format(project_id=self._project_id)}"
            f"/{COLLECTION}/{self._install_id}"
            f"?key={self._api_key}"
        )
        _meta = {
            "installation_id": self._install_id,
            "version":         self._version,
            "last_seen":       int(time.time()),
            "uptime_h":        round((time.time() - self._start_ts) / 3600, 1),
        }
        doc = {"fields": {k: self._to_firestore(v) for k, v in _meta.items()}}
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(doc).encode("utf-8"),
                method="PATCH",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    @staticmethod
    def _to_firestore(data: Any, _depth: int = 0) -> dict:
        """Zet Python dict/list/str/int/float/bool om naar Firestore REST veld-formaat."""
        if _depth > 10:
            return {"stringValue": str(data)}
        if data is None:
            return {"nullValue": None}
        if isinstance(data, bool):
            return {"booleanValue": data}
        if isinstance(data, int):
            return {"integerValue": str(data)}
        if isinstance(data, float):
            return {"doubleValue": data}
        if isinstance(data, dict):
            return {"mapValue": {"fields": {
                k: CloudEMSTelemetry._to_firestore(v, _depth + 1)
                for k, v in data.items()
            }}}
        if isinstance(data, (list, tuple)):
            return {"arrayValue": {"values": [
                CloudEMSTelemetry._to_firestore(i, _depth + 1) for i in data
            ]}}
        return {"stringValue": str(data)}

    def _get_or_create_install_id(self) -> str:
        """Lees of genereer een persistente anonieme installatie-ID."""
        path = os.path.join(self._config_dir, STORAGE_KEY)
        try:
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                    if "installation_id" in data:
                        return data["installation_id"]
        except Exception:
            pass
        new_id = str(uuid.uuid4())
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"installation_id": new_id, "created": int(time.time())}, f)
        except Exception:
            pass
        _LOGGER.info("CloudEMS telemetry: nieuwe installatie-ID aangemaakt: %s", new_id[:8])
        return new_id

    @property
    def installation_id(self) -> str:
        return self._install_id

    @property
    def installation_id_short(self) -> str:
        return self._install_id[:8]

    @property
    def is_configured(self) -> bool:
        return bool(self._project_id and self._api_key)
