# -*- coding: utf-8 -*-
"""
CloudEMS Learning Backup — v1.0.0

Tweede schrijfpad naast de HA Store voor alle zelflerende modules.

Probleem:
  HA Store schrijft naar .storage/cloudems_*.json
  Bij een harde crash tijdens het schrijven kan dit bestand corrupt raken.
  Alle geleerde data (fase, oriëntatie, thermisch model, etc.) gaat dan verloren.

Oplossing:
  LearningBackup schrijft elke BACKUP_INTERVAL_S seconden een snapshot van
  alle leerdata naar /config/cloudems_backup/<module>.json
  Dit bestand staat buiten de HA Store en wordt dus niet geraakt door
  Store-corruptie.

  Bij async_setup: als de Store leeg/corrupt is → automatisch terugvallen
  op de backup. De oproepende module bepaalt zelf of de backup geldig is.

Gebruik:
    backup = LearningBackup(hass)
    await backup.async_setup()

    # Schrijven (vanuit elke module):
    await backup.async_write("pv_forecast", data_dict)

    # Lezen bij fallback:
    data = await backup.async_read("pv_forecast")  # None als niet bestaat

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BACKUP_DIR        = "cloudems_backup"   # relatief t.o.v. hass.config.config_dir
BACKUP_INTERVAL_S = 900                 # 15 minuten — minder frequent dan Store (2 min)


class LearningBackup:
    """
    Beheert een backup-directory voor alle CloudEMS leerdata.

    Elke module heeft een eigen bestand: cloudems_backup/<module>.json
    Schrijven is throttled op BACKUP_INTERVAL_S per module.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass     = hass
        self._dir      = os.path.join(hass.config.config_dir, BACKUP_DIR)
        self._last_write: dict[str, float] = {}  # module → last write timestamp

    async def async_setup(self) -> None:
        """Maak de backup-directory aan als die niet bestaat."""
        try:
            await self._hass.async_add_executor_job(self._ensure_dir)
            _LOGGER.info("CloudEMS LearningBackup: directory gereed: %s", self._dir)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS LearningBackup: setup mislukt: %s", exc)

    def _ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, module: str) -> str:
        # Sanitize module name to prevent path traversal
        safe = "".join(c for c in module if c.isalnum() or c in ("_", "-"))
        return os.path.join(self._dir, f"{safe}.json")

    async def async_write(self, module: str, data: Any, force: bool = False) -> None:
        """
        Schrijf data naar de backup voor deze module.
        Throttled op BACKUP_INTERVAL_S tenzij force=True.
        """
        now = time.time()
        last = self._last_write.get(module, 0.0)
        if not force and (now - last) < BACKUP_INTERVAL_S:
            return

        try:
            path = self._path(module)
            payload = {
                "module":    module,
                "timestamp": now,
                "data":      data,
            }
            raw = json.dumps(payload, indent=2, default=str)
            await self._hass.async_add_executor_job(self._write_file, path, raw)
            self._last_write[module] = now
            _LOGGER.debug("CloudEMS LearningBackup: '%s' opgeslagen (%d bytes)", module, len(raw))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS LearningBackup: schrijven '%s' mislukt: %s", module, exc)

    def _write_file(self, path: str, raw: str) -> None:
        """Schrijf atomisch: eerst naar .tmp, dan rename (voorkomt half-beschreven bestanden)."""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, path)  # atomische rename op Linux

    async def async_read(self, module: str) -> Optional[Any]:
        """
        Lees backup-data voor deze module.
        Geeft None terug als het bestand niet bestaat of corrupt is.
        """
        path = self._path(module)
        try:
            raw = await self._hass.async_add_executor_job(self._read_file, path)
            if raw is None:
                return None
            payload = json.loads(raw)
            age_h = (time.time() - payload.get("timestamp", 0)) / 3600
            _LOGGER.info(
                "CloudEMS LearningBackup: '%s' geladen uit backup (%.1f uur oud)",
                module, age_h,
            )
            return payload.get("data")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CloudEMS LearningBackup: lezen '%s' mislukt (corrupt?): %s", module, exc
            )
            return None

    def _read_file(self, path: str) -> Optional[str]:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    async def async_flush_all(self, modules_data: dict[str, Any]) -> None:
        """Schrijf alle modules tegelijk, geforceerd (bij shutdown)."""
        for module, data in modules_data.items():
            await self.async_write(module, data, force=True)
        _LOGGER.info("CloudEMS LearningBackup: %d modules opgeslagen bij afsluiting", len(modules_data))
