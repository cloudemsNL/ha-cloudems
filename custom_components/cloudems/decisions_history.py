from __future__ import annotations
"""
CloudEMS Decisions History
Ring buffer voor beslissingsgeschiedenis — 24 uur, alle categorieën.
Schrijft naar JSON bestand én exposeert via sensor attribuut.
"""

import json
import logging
import os
import time
from collections import deque
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Max entries in memory (24u bij 1 beslissing per minuut per categorie = 24*60*5 ≈ 7200)
# We bewaren max 1000 entries — bij 5 categorieën elke 10s = ~2880/uur → we samplen
MAX_ENTRIES        = 1000
MAX_SENSOR_ENTRIES = 60    # Max entries in sensor attribuut (HA size limit)
HISTORY_FILENAME   = "cloudems_decisions_history.json"
# Dedupliceer: sla beslissing alleen op als actie/reden gewijzigd is (per categorie)
DEDUPE_WINDOW_S    = 30    # Minimaal interval per categorie voor identieke beslissingen


class DecisionsHistory:
    """Ring buffer voor CloudEMS beslissingsgeschiedenis."""

    def __init__(self, config_dir: str) -> None:
        self._path    = os.path.join(config_dir, HISTORY_FILENAME)
        self._entries: deque[dict] = deque(maxlen=MAX_ENTRIES)
        self._last_per_category: dict[str, dict] = {}  # categorie → laatste entry
        self._dirty   = False
        self._load()

    # ── Publieke API ─────────────────────────────────────────────────────────

    def add(self, category: str, action: str, reason: str, message: str,
            extra: dict | None = None) -> None:
        """Voeg een beslissing toe. Dedupliceert identieke actie+reden binnen 30s."""
        now = time.time()
        last = self._last_per_category.get(category)
        if last:
            same = (last["action"] == action and last["reason"] == reason)
            recent = (now - last["ts"]) < DEDUPE_WINDOW_S
            if same and recent:
                return  # Skip duplicaat

        entry: dict[str, Any] = {
            "ts":       now,
            "iso":      _iso(now),
            "cat":      category,
            "action":   action,
            "reason":   reason,
            "message":  message,
        }
        if extra:
            entry.update(extra)

        self._entries.append(entry)
        self._last_per_category[category] = entry
        self._dirty = True

    def get_recent(self, max_age_s: float = 86400,
                   categories: list[str] | None = None,
                   limit: int = MAX_SENSOR_ENTRIES) -> list[dict]:
        """Geef recente beslissingen, nieuwste eerst."""
        cutoff = time.time() - max_age_s
        result = [
            e for e in reversed(self._entries)
            if e["ts"] >= cutoff
            and (categories is None or e["cat"] in categories)
        ]
        return result[:limit]

    def flush_if_dirty(self) -> None:
        """Schrijf naar schijf als er nieuwe entries zijn. Gebruikt StorageBackend indien beschikbaar."""
        if not self._dirty:
            return
        try:
            cutoff = time.time() - 86400
            to_save = [e for e in self._entries if e["ts"] >= cutoff]
            # Probeer StorageBackend te gebruiken (cloud-migratie klaar)
            try:
                from .storage_backend import get_storage_backend
                backend = get_storage_backend()
                # Synchrone write via threading (flush_if_dirty wordt vanuit sync context aangeroepen)
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(backend.write("decisions_history", to_save))
                else:
                    loop.run_until_complete(backend.write("decisions_history", to_save))
            except Exception:
                # Fallback: direct naar JSON
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "entries": to_save}, f, ensure_ascii=False)
            self._dirty = False
        except Exception as err:
            _LOGGER.warning("CloudEMS DecisionsHistory: schrijffout: %s", err)

    def sensor_attributes(self) -> dict:
        """Geef attributen voor de sensor entity."""
        recent = self.get_recent(limit=MAX_SENSOR_ENTRIES)
        return {
            "decisions":    recent,
            "total_24h":    len(self.get_recent(limit=99999)),
            "last_updated": _iso(time.time()),
        }

    # ── Intern ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Laad bestaande history van schijf bij startup."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            cutoff = time.time() - 86400
            entries = [e for e in data.get("entries", []) if e.get("ts", 0) >= cutoff]
            self._entries.extend(entries)
            _LOGGER.info("CloudEMS DecisionsHistory: %d entries geladen", len(entries))
        except Exception as err:
            _LOGGER.warning("CloudEMS DecisionsHistory: laadfout: %s", err)


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
