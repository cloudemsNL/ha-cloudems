from __future__ import annotations
"""
CloudEMS Storage Backend
Abstractie-laag voor persistente opslag — HA (JSON bestanden) of cloud (PostgreSQL/API).
Wissel de backend door een andere implementatie te configureren.

Gebruik:
    from .storage_backend import get_storage_backend
    backend = get_storage_backend(hass)
    await backend.write("decisions", entries)
    entries = await backend.read("decisions")
"""
import json, logging, os
from abc import ABC, abstractmethod
from typing import Any

_LOGGER = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstracte base class voor CloudEMS persistente opslag."""

    @abstractmethod
    async def write(self, key: str, data: Any) -> bool:
        """Schrijf data naar de store. Geeft True terug bij succes."""

    @abstractmethod
    async def read(self, key: str, default: Any = None) -> Any:
        """Lees data uit de store. Geeft default terug als key niet bestaat."""

    @abstractmethod
    async def append(self, key: str, entry: dict, max_age_s: float = 86400) -> bool:
        """Voeg een entry toe aan een lijst, verwijder entries ouder dan max_age_s."""


class LocalFileBackend(StorageBackend):
    """
    HA-implementatie: schrijft naar JSON bestanden in /config/.
    Klaar voor vervanging door CloudBackend bij cloud-migratie.
    """

    def __init__(self, config_dir: str) -> None:
        self._dir = config_dir

    def _path(self, key: str) -> str:
        safe = key.replace("/", "_").replace("..", "")
        return os.path.join(self._dir, f"cloudems_{safe}.json")

    async def write(self, key: str, data: Any) -> bool:
        import asyncio
        path = self._path(key)
        payload = json.dumps({"version": 1, "data": data}, ensure_ascii=False)
        def _do_write():
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _do_write)
            return True
        except Exception as err:
            _LOGGER.warning("CloudEMS StorageBackend write(%s): %s", key, err)
            return False

    async def read(self, key: str, default: Any = None) -> Any:
        import asyncio
        path = self._path(key)
        if not os.path.exists(path):
            return default
        def _do_read():
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("data", default)
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _do_read)
        except Exception as err:
            _LOGGER.warning("CloudEMS StorageBackend read(%s): %s", key, err)
            return default

    async def append(self, key: str, entry: dict, max_age_s: float = 86400) -> bool:
        import time
        entries = await self.read(key, [])
        if not isinstance(entries, list):
            entries = []
        entries.append(entry)
        # Verwijder te oude entries
        cutoff = time.time() - max_age_s
        entries = [e for e in entries if e.get("ts", 0) >= cutoff]
        return await self.write(key, entries)


# ── Factory ──────────────────────────────────────────────────────────────────

_BACKEND: StorageBackend | None = None


def get_storage_backend(config_dir: str | None = None) -> StorageBackend:
    """
    Geef de actieve storage backend.
    In de toekomst: lees uit CloudEMS config of omgevingsvariabele welke backend te gebruiken.
    """
    global _BACKEND
    if _BACKEND is None:
        if config_dir is None:
            raise RuntimeError("StorageBackend nog niet geïnitialiseerd — geef config_dir mee")
        _BACKEND = LocalFileBackend(config_dir)
    return _BACKEND


def init_storage_backend(config_dir: str) -> StorageBackend:
    """Initialiseer de storage backend bij opstarten van de integratie."""
    global _BACKEND
    _BACKEND = LocalFileBackend(config_dir)
    _LOGGER.info("CloudEMS StorageBackend: LocalFileBackend geïnitialiseerd (%s)", config_dir)
    return _BACKEND
