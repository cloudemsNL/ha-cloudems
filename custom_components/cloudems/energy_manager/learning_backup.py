# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Learning Backup — v2.1.0

Tweede schrijfpad naast de HA Store voor alle zelflerende modules, plus twee
geroteerde diagnostische logbestanden voor post-mortem analyse en code-verbetering.

Logstrategie:
  cloudems_normal.log  — hoge frequentie, cyclische data (elk uur NILM-snapshot,
                         backup-flushes, startup/shutdown). 5 rotaties × 500 KB = 2.5 MB.

  cloudems_high.log    — bijzonderheden die aandacht vereisen: nieuwe apparaten,
                         fase-wijzigingen, false positives, infra-blokkades,
                         coordinator-fouten met stacktrace, warnings, auto-pruning.
                         10 rotaties × 200 KB = 2 MB. Lange bewaring zodat zeldzame
                         events altijd terug te vinden zijn.

Gebruik:
    backup = LearningBackup(hass)
    await backup.async_setup()

    # Module-data backuppen:
    await backup.async_write("pv_forecast", data_dict)

    # Normaal loggen (hoge frequentie):
    await backup.async_log_normal("nilm_cycle", {"device_count": 12, ...})

    # Bijzonder loggen (lage frequentie, lange bewaring):
    await backup.async_log_high("nilm_new_device", {"name": "Boiler", "phase": "L2"})

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BACKUP_DIR        = "cloudems_backup"
BACKUP_INTERVAL_S = 900                 # 15 min tussen module-backups

# Normal log: hoge frequentie, snel overgeschreven (cyclische NILM/balancer data)
NORMAL_LOG_NAME     = "cloudems_normal.log"
NORMAL_MAX_BYTES    = 500 * 1024        # 500 KB per bestand
NORMAL_BACKUP_COUNT = 5                 # 5 rotaties → max 2.5 MB

# High log: bijzonderheden + alle beslissingen voor terugkijken en leren
# v4.5.11: vergroot want we loggen nu alle beslissingen (boiler, accu, rolluik,
# EV, smart delay, zonneplan, BDE) elke 10s cyclus → meer volume nodig.
# 1 MB × 20 = 20 MB max: ruim genoeg voor ~48u volledige beslissingshistorie.
HIGH_LOG_NAME     = "cloudems_high.log"
HIGH_MAX_BYTES    = 1 * 1024 * 1024    # 1 MB per bestand
HIGH_BACKUP_COUNT = 20                  # 20 rotaties → max 20 MB

# Beslissingen log: apart bestand puur voor terugkijken / leerdata
# Dezelfde data als high log maar uitgesplitst op categorie "decision_*".
# Makkelijker te parsen voor analyse achteraf.
DECISIONS_LOG_NAME     = "cloudems_decisions.log"
DECISIONS_MAX_BYTES    = 2 * 1024 * 1024  # 2 MB per bestand
DECISIONS_BACKUP_COUNT = 10               # 10 rotaties → max 20 MB

# NILM log: dedicated logbestand voor alle NILM-gerelateerde events.
# NILM genereert elke cyclus meerdere log-entries (discovery, topology,
# fase-bevestiging, anchor-registratie, actief leren, restsignaal).
# Door dit apart te houden verdrinkt het niet in cloudems_high.log en
# is gericht debuggen via "tail -f cloudems_nilm.log" mogelijk.
# Categorieën: nilm_discovery, nilm_topology, nilm_phase, nilm_anchor,
#              nilm_active_learn, nilm_residual
NILM_LOG_NAME     = "cloudems_nilm.log"
NILM_MAX_BYTES    = 2 * 1024 * 1024  # 2 MB per bestand
NILM_BACKUP_COUNT = 10               # 10 rotaties → max 20 MB


class LearningBackup:
    """
    Beheert een backup-directory voor alle CloudEMS leerdata plus
    twee geroteerde diagnostische logbestanden.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass       = hass
        self._dir        = os.path.join(hass.config.config_dir, BACKUP_DIR)
        self._last_write: dict[str, float] = {}
        self._version    = "onbekend"  # v4.5.11: ingevuld door async_setup()
        self._normal_path    = os.path.join(self._dir, NORMAL_LOG_NAME)
        self._high_path      = os.path.join(self._dir, HIGH_LOG_NAME)
        self._decisions_path = os.path.join(self._dir, DECISIONS_LOG_NAME)
        self._nilm_path      = os.path.join(self._dir, NILM_LOG_NAME)

    async def async_setup(self) -> None:
        """Maak de backup-directory aan als die niet bestaat."""
        try:
            await self._hass.async_add_executor_job(self._ensure_dir)
            # v4.5.11: lees versie uit manifest.json voor startup log
            _version = "onbekend"
            try:
                import json as _json, pathlib as _pl
                _manifest = _pl.Path(__file__).parent.parent / "manifest.json"
                def _read_manifest():
                    return _json.loads(_manifest.read_text(encoding="utf-8")).get("version", "onbekend")
                _version = await self._hass.async_add_executor_job(_read_manifest)
            except Exception:
                pass
            self._version = _version
            _LOGGER.info("CloudEMS LearningBackup v2.1: directory gereed: %s (v%s)", self._dir, _version)
            # v4.5.11: test-schrijf om permissieproblemen vroeg te detecteren
            _test_path = os.path.join(self._dir, ".write_test")
            try:
                await self._hass.async_add_executor_job(
                    self._write_file, _test_path, "ok"
                )
                import os as _os_rm
                await self._hass.async_add_executor_job(_os_rm.remove, _test_path)
            except Exception as _test_exc:
                _LOGGER.error(
                    "CloudEMS LearningBackup: SCHRIJFTEST MISLUKT in '%s' — "
                    "logbestanden worden niet aangemaakt. Controleer bestandsrechten. Fout: %s",
                    self._dir, _test_exc,
                )
            await self.async_log_high("startup", {
                "event":             "CloudEMS gestart",
                "version":           _version,
                "backup_dir":        self._dir,
                "backup_interval_s": BACKUP_INTERVAL_S,
                "normal_log":        f"{NORMAL_LOG_NAME} ({NORMAL_MAX_BYTES//1024}KB×{NORMAL_BACKUP_COUNT})",
                "high_log":          f"{HIGH_LOG_NAME} ({HIGH_MAX_BYTES//1024}KB×{HIGH_BACKUP_COUNT})",
                "decisions_log":     f"{DECISIONS_LOG_NAME} ({DECISIONS_MAX_BYTES//1024//1024}MB×{DECISIONS_BACKUP_COUNT})",
            })
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS LearningBackup: setup mislukt: %s", exc)

    def _ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, module: str) -> str:
        safe = "".join(c for c in module if c.isalnum() or c in ("_", "-"))
        return os.path.join(self._dir, f"{safe}.json")

    # ── Module-data backup ────────────────────────────────────────────────────

    async def async_write(self, module: str, data: Any, force: bool = False) -> None:
        """Schrijf data naar de backup voor deze module (throttled)."""
        now  = time.time()
        last = self._last_write.get(module, 0.0)
        if not force and (now - last) < BACKUP_INTERVAL_S:
            return
        try:
            path    = self._path(module)
            payload = {"module": module, "timestamp": now, "data": data}
            raw     = json.dumps(payload, indent=2, default=str)
            await self._hass.async_add_executor_job(self._write_file, path, raw)
            self._last_write[module] = now
            _LOGGER.debug(
                "CloudEMS LearningBackup: '%s' opgeslagen (%d bytes)", module, len(raw)
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CloudEMS LearningBackup: schrijven '%s' mislukt: %s", module, exc
            )

    def _write_file(self, path: str, raw: str) -> None:
        """Atomisch schrijven via tmp-rename."""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, path)

    async def async_read(self, module: str) -> Optional[Any]:
        """Lees backup-data; geeft None terug als niet bestaat of corrupt."""
        path = self._path(module)
        try:
            raw = await self._hass.async_add_executor_job(self._read_file, path)
            if raw is None:
                return None
            payload = json.loads(raw)
            age_h   = (time.time() - payload.get("timestamp", 0)) / 3600
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
        _LOGGER.info(
            "CloudEMS LearningBackup: %d modules opgeslagen bij afsluiting",
            len(modules_data),
        )
        await self.async_log_normal("shutdown", {
            "event":   "CloudEMS afgesloten — backup geflushed",
            "modules": list(modules_data.keys()),
        })
        await self.async_log_high("shutdown", {
            "event":        "CloudEMS afgesloten",
            "modules_saved": list(modules_data.keys()),
        })

    # ── Normal log (hoge frequentie) ──────────────────────────────────────────

    async def async_log_normal(self, category: str, payload: dict) -> None:
        """
        Schrijf een gestructureerde regel naar cloudems_normal.log.

        Bedoeld voor: cyclische NILM-snapshots (elk uur), backup-events,
        startup/shutdown bevestigingen, sensor-voeding per fase.

        Rotatie: 5 × 500 KB = max 2.5 MB schijfruimte.
        """
        await self._write_log(self._normal_path, category, payload,
                              NORMAL_MAX_BYTES, NORMAL_BACKUP_COUNT)

    # ── High log (bijzonderheden, lange bewaring) ─────────────────────────────

    async def async_log_high(self, category: str, payload: dict) -> None:
        """
        Schrijf een gestructureerde regel naar cloudems_high.log.

        Bedoeld voor: nieuwe NILM-apparaten, fase-wijzigingen/-resoluties,
        false positive verwijderingen, infra-blokkades, coordinator-fouten
        met stacktrace, auto-pruning events, confidence-verlagingen,
        steady-state rejecties, en alle _LOGGER.warning()-equivalenten.

        Rotatie: 10 × 200 KB = max 2 MB schijfruimte. Langere bewaring
        zodat zeldzame events altijd terug te vinden zijn.
        """
        await self._write_log(self._high_path, category, payload,
                              HIGH_MAX_BYTES, HIGH_BACKUP_COUNT)

    # ── Beslissingen log (apart bestand, makkelijk te parsen) ───────────────

    async def async_log_decision(self, category: str, payload: dict) -> None:
        """Schrijf een beslissing naar cloudems_decisions.log.

        Dit bestand bevat ALLE beslissingen van CloudEMS:
        boiler, accu (BDE + scheduler), Zonneplan/Nexus, rolluiken, EV,
        smart delay, goedkoop-schakelaar, congestie, piekafschaving.

        Elk record is zelfbeschrijvend: energiecontext (solar/grid/battery/
        house/soc/prijs) is altijd aanwezig zodat je achteraf kunt beoordelen
        of de beslissing correct was.

        Rotatie: 10 × 2 MB = max 20 MB → ~48u volledige beslissingshistorie.
        """
        await self._write_log(self._decisions_path, category, payload,
                              DECISIONS_MAX_BYTES, DECISIONS_BACKUP_COUNT)
        # Mirror naar high log zodat alles op één plek terug te vinden is
        await self._write_log(self._high_path, category, payload,
                              HIGH_MAX_BYTES, HIGH_BACKUP_COUNT)

    # ── NILM log (dedicated NILM events — discovery, topology, fase, anker) ──

    async def async_log_nilm(self, category: str, payload: dict) -> None:
        """Schrijf een NILM-event naar cloudems_nilm.log.

        Categorieën:
          nilm_discovery    — classificatie per sensor (type, conf, bron, stap)
          nilm_topology     — upstream/downstream meter relaties
          nilm_phase        — fase-bevestigingen en streaks
          nilm_anchor       — anker registratie, updates, bron
          nilm_active_learn — actief-leer verzoeken en resultaten
          nilm_residual     — restsignaal per fase na aftrek anchor+powercalc

        Rotatie: 10 × 2 MB = max 20 MB.
        Tip voor debugging: tail -f cloudems_backup/cloudems_nilm.log
        """
        await self._write_log(self._nilm_path, category, payload,
                              NILM_MAX_BYTES, NILM_BACKUP_COUNT)

    # ── Interne loghelper ─────────────────────────────────────────────────────

    async def _write_log(
        self,
        log_path: str,
        category: str,
        payload:  dict,
        max_bytes: int,
        backup_count: int,
    ) -> None:
        """Generieke log-schrijver met ingebouwde rotatie."""
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            # v4.5.11: voeg versie toe aan elke logregel zodat troubleshooting
            # altijd weet welke versie de log produceerde
            _payload_with_ver = {"_v": self._version, **payload} if isinstance(payload, dict) else payload
            line = f"{ts} [{category}] {json.dumps(_payload_with_ver, default=str)}\n"
            await self._hass.async_add_executor_job(
                self._append_log, log_path, line, max_bytes, backup_count
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CloudEMS DiagLog '%s' schrijven mislukt: %s", log_path, exc)

    def _append_log(
        self,
        log_path:     str,
        line:         str,
        max_bytes:    int,
        backup_count: int,
    ) -> None:
        """Voeg een regel toe; roteer indien nodig."""
        self._ensure_dir()
        if os.path.exists(log_path) and os.path.getsize(log_path) >= max_bytes:
            self._rotate(log_path, backup_count)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _rotate(base: str, count: int) -> None:
        """
        Roteer een logbestand:
          base.{count} → verwijderd
          base.{count-1} → base.{count}
          ...
          base.1 → base.2
          base   → base.1
        """
        oldest = f"{base}.{count}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(count - 1, 0, -1):
            src = f"{base}.{i}"
            dst = f"{base}.{i + 1}"
            if os.path.exists(src):
                os.rename(src, dst)
        if os.path.exists(base):
            os.rename(base, f"{base}.1")

    # ── Achterwaartse compatibiliteit ─────────────────────────────────────────
    # v2.0 gebruikte async_write_diag() — doorsturen naar normal log
    # zodat bestaande aanroepen niet breken.

    async def async_write_diag(self, category: str, payload: dict) -> None:
        """Deprecated alias voor async_log_normal() — voor achterwaartse compat."""
        await self.async_log_normal(category, payload)
