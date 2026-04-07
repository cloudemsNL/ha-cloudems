# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Watchdog — v1.0.0

Monitort de coordinator op herhaalde UpdateFailed crashes en herstart
de integratie automatisch via config entry reload.

Gedrag:
  - Telt opeenvolgende mislukte updates
  - Na MAX_CONSECUTIVE_FAILURES → reload config entry (zachte herstart)
  - Exponential backoff: wacht steeds langer tussen herstarts
  - Slaat crashgeschiedenis op in HA storage (persistent over reboots)
  - Biedt get_data() voor de watchdog sensor op het dashboard

Copyright © 2026 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_watchdog_v1"
STORAGE_VERSION = 1

# Na hoeveel opeenvolgende fouten herstarten
MAX_CONSECUTIVE_FAILURES = 5  # v5.5.139: verhoogd van 3 → 5

# Minimale wachttijd tussen twee herstarts (seconden), verdubbelt elke keer
BACKOFF_BASE_S   = 30
BACKOFF_MAX_S    = 3600   # maximaal 1 uur wachten

# Hoeveel crashmeldingen we bewaren in de geschiedenis
HISTORY_MAX      = 50
SILENT_TIMEOUT_S = 300      # v4.0.5: 5 min zonder success = silent hang


class CloudEMSWatchdog:
    """
    Watchdog voor de CloudEMS coordinator.

    Gebruik:
        watchdog = CloudEMSWatchdog(hass, entry_id)
        await watchdog.async_setup()

        # In coordinator._async_update_data():
        #   bij succes:  watchdog.report_success()
        #   bij fout:    await watchdog.report_failure(exc)
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass      = hass
        self._entry_id  = entry_id
        self._store     = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Runtime state
        self._consecutive_failures: int   = 0
        self._total_failures:       int   = 0
        self._total_restarts:       int   = 0
        self._last_failure_ts:      Optional[float] = None
        self._last_failure_msg:     str   = ""
        self._last_restart_ts:      Optional[float] = None
        self._last_success_ts:      Optional[float] = None
        # v4.0.5: silent hang
        self._silent_warn_sent:     bool  = False
        self._update_start_ts:      Optional[float] = None
        # Grace period: geen reload in de eerste 2 minuten na (her)start van HA.
        # Tijdens het opstarten zijn sensors tijdelijk unavailable — dat zijn geen echte crashes.
        self._next_restart_allowed: float = time.time() + 120
        self._backoff_s:            float = BACKOFF_BASE_S
        self._restarting:           bool  = False

        # Uptime tracking
        self._setup_ts: float = time.time()

        # Crashgeschiedenis (persistent)
        self._history: deque = deque(maxlen=HISTORY_MAX)

    # ── Setup & Persistence ───────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Laad opgeslagen crashgeschiedenis."""
        try:
            stored = await self._store.async_load()
            if stored:
                self._total_failures  = stored.get("total_failures", 0)
                self._total_restarts  = stored.get("total_restarts", 0)
                raw_backoff           = stored.get("backoff_s", BACKOFF_BASE_S)
                self._last_restart_ts = stored.get("last_restart_ts")

                # v2.4.17: als de laatste herstart > 30 minuten geleden was,
                # beschouw dit als een schone start en reset de backoff.
                # Dit voorkomt dat een oude hoge backoff (bijv. 3600s) altijd
                # wordt meegenomen na een stabiele nacht.
                if self._last_restart_ts:
                    time_since_restart = time.time() - self._last_restart_ts
                    if time_since_restart > 1800:  # 30 minuten
                        raw_backoff = BACKOFF_BASE_S
                        _LOGGER.info(
                            "CloudEMS Watchdog: backoff gereset naar %ds "
                            "(laatste herstart was %.0f min geleden)",
                            BACKOFF_BASE_S, time_since_restart / 60,
                        )
                self._backoff_s = raw_backoff

                history = stored.get("history", [])
                self._history = deque(history[-HISTORY_MAX:], maxlen=HISTORY_MAX)
                _LOGGER.info(
                    "CloudEMS Watchdog geladen: %d totaal crashes, %d herstarts",
                    self._total_failures, self._total_restarts,
                )
        except Exception as err:
            _LOGGER.warning("CloudEMS Watchdog: kon opgeslagen data niet laden: %s", err)

    async def _async_save(self) -> None:
        try:
            await self._store.async_save({
                "total_failures":  self._total_failures,
                "total_restarts":  self._total_restarts,
                "backoff_s":       self._backoff_s,
                "last_restart_ts": self._last_restart_ts,
                "history":         list(self._history),
            })
        except Exception as err:
            _LOGGER.warning("CloudEMS Watchdog: opslaan mislukt: %s", err)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def report_update_started(self) -> None:
        """v4.0.5: Aanroepen bij START coordinator update."""
        self._update_start_ts = time.time()

    def check_silent_hang(self) -> bool:
        """Detecteert silent hang: geen exception maar ook geen success > 5 min."""
        if self._last_success_ts is None:
            return False
        silent_s = time.time() - self._last_success_ts
        if silent_s > SILENT_TIMEOUT_S and not self._silent_warn_sent:
            self._silent_warn_sent = True
            _LOGGER.warning(
                "CloudEMS Watchdog: SILENT HANG — geen update in %.0fs", silent_s
            )
            return True
        if silent_s <= SILENT_TIMEOUT_S:
            self._silent_warn_sent = False
        return False

    def report_success(self) -> None:
        """Coordinator update geslaagd — reset consecutive teller."""
        if self._consecutive_failures > 0:
            _LOGGER.info(
                "CloudEMS Watchdog: update geslaagd na %d opeenvolgende fouten — teller gereset",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._last_success_ts = time.time()
        # Backoff langzaam terugbrengen na succes
        self._backoff_s = max(BACKOFF_BASE_S, self._backoff_s / 2)

    # Tijdelijke fouten (netwerk/timeout) triggeren geen herstart zo snel
    _TRANSIENT_ERRORS = (
        "TimeoutError", "ClientConnectionError", "ClientConnectorError",
        "ServerTimeoutError", "asyncio.TimeoutError", "ClientOSError",
        "aiohttp.ServerDisconnectedError", "ConnectionResetError",
    )

    async def report_failure(self, exc: Exception) -> None:
        """Coordinator update mislukt — log, sla op, herstart indien nodig."""
        now       = time.time()
        now_dt    = datetime.now(timezone.utc).isoformat(timespec="seconds")
        msg       = f"{type(exc).__name__}: {exc}"
        short_msg = str(exc)[:200]

        # Tijdelijke netwerk/timeout fouten tellen als 0.3 i.p.v. 1
        # zodat kortstondige cloud/P1 storingen geen herstart veroorzaken
        exc_name = type(exc).__name__
        is_transient = any(t in exc_name or t in msg for t in self._TRANSIENT_ERRORS)
        if is_transient:
            self._consecutive_failures = min(
                self._consecutive_failures + 0.34,  # 3x tijdelijk = 1 echte fout
                MAX_CONSECUTIVE_FAILURES - 0.1       # nooit direct over de grens
            )
        else:
            self._consecutive_failures += 1
        self._total_failures       += 1
        self._last_failure_ts       = now
        self._last_failure_msg      = short_msg

        # Voeg toe aan geschiedenis
        self._history.append({
            "ts":          now_dt,
            "error":       short_msg,
            "consecutive": self._consecutive_failures,
        })

        _LOGGER.error(
            "CloudEMS Watchdog: update fout #%d (opeenvolgend: %d/%d): %s",
            self._total_failures,
            self._consecutive_failures,
            MAX_CONSECUTIVE_FAILURES,
            msg,
        )

        await self._async_save()

        # Herstart triggeren?
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            await self._maybe_restart(now)

    # ── Restart logic ─────────────────────────────────────────────────────────

    async def _maybe_restart(self, now: float) -> None:
        """Herstart de config entry als backoff-wachttijd verstreken is."""
        if self._restarting:
            _LOGGER.debug("CloudEMS Watchdog: herstart al bezig, overgeslagen")
            return

        if now < self._next_restart_allowed:
            remaining = int(self._next_restart_allowed - now)
            _LOGGER.warning(
                "CloudEMS Watchdog: %d opeenvolgende fouten maar backoff actief — "
                "wacht nog %ds voor herstart",
                self._consecutive_failures, remaining,
            )
            return

        self._restarting           = True
        self._total_restarts      += 1
        self._last_restart_ts      = now
        self._consecutive_failures = 0
        self._next_restart_allowed = now + self._backoff_s
        self._backoff_s            = min(self._backoff_s * 2, BACKOFF_MAX_S)

        restart_dt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _LOGGER.warning(
            "CloudEMS Watchdog: herstart #%d gestart om %s (volgende herstart niet voor %ds)",
            self._total_restarts, restart_dt, int(self._backoff_s),
        )

        # Voeg herstart toe aan geschiedenis
        self._history.append({
            "ts":      restart_dt,
            "error":   f"WATCHDOG HERSTART #{self._total_restarts}",
            "consecutive": 0,
        })
        await self._async_save()

        try:
            entry = self._hass.config_entries.async_get_entry(self._entry_id)
            if entry:
                self._hass.async_create_task(
                    self._hass.config_entries.async_reload(self._entry_id)
                )
                _LOGGER.info("CloudEMS Watchdog: config entry reload getriggerd")
            else:
                _LOGGER.error("CloudEMS Watchdog: config entry niet gevonden — herstart mislukt")
        except Exception as err:
            _LOGGER.error("CloudEMS Watchdog: reload mislukt: %s", err)
        finally:
            self._restarting = False

    # ── Dashboard data ────────────────────────────────────────────────────────

    def get_data(self) -> dict:
        """Retourneer watchdog-data voor de sensor en het dashboard."""
        now = time.time()

        def _fmt(ts: Optional[float]) -> Optional[str]:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")

        def _ago(ts: Optional[float]) -> Optional[str]:
            if ts is None:
                return None
            diff = int(now - ts)
            if diff < 60:
                return f"{diff}s geleden"
            if diff < 3600:
                return f"{diff // 60}m geleden"
            if diff < 86400:
                return f"{diff // 3600}u geleden"
            return f"{diff // 86400}d geleden"

        status = "ok"
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            status = "critical"
        elif self._consecutive_failures > 0:
            status = "warning"

        return {
            "status":                status,
            "consecutive_failures":  self._consecutive_failures,
            "total_failures":        self._total_failures,
            "total_restarts":        self._total_restarts,
            "last_failure":          _fmt(self._last_failure_ts),
            "last_failure_ago":      _ago(self._last_failure_ts),
            "last_failure_msg":      self._last_failure_msg,
            "last_restart":          _fmt(self._last_restart_ts),
            "last_restart_ago":      _ago(self._last_restart_ts),
            "last_success":          _fmt(self._last_success_ts),
            "silent_hang":           self.check_silent_hang(),
            "last_success_ago":      _ago(self._last_success_ts),
            "next_restart_in_s":     max(0, int(self._next_restart_allowed - now)),
            "backoff_s":             int(self._backoff_s),
            "max_consecutive":       MAX_CONSECUTIVE_FAILURES,
            "history":               list(self._history)[-10:],  # laatste 10
            "uptime_s":              int(now - self._setup_ts),
            "uptime_h":              round((now - self._setup_ts) / 3600, 1),
            "uptime_str":            _ago(self._setup_ts).replace(" geleden", "") if self._setup_ts else "0s",
            "started_at":            _fmt(self._setup_ts),
        }
