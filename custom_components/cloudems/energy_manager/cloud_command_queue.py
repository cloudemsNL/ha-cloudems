# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
cloud_command_queue.py — CloudEMS v4.6.557

Generieke command queue met debounce, rate-limiting en backoff.

Ontworpen voor cloud-APIs die 429 Too Many Requests geven bij te frequente
aanroepen. Platform-agnostisch — werkt voor Ariston, Zonneplan, Solarman,
toekomstige CloudEMS SaaS, of elke andere cloud-API.

Architectuur:
─────────────
  CloudCommandQueue
    ├── CommandSlot per (device_id, command_type)
    │     ├── desired_*    — gewenste eindtoestand (laatste wint)
    │     ├── desired_since — ts van eerste wens, reset bij verandering
    │     ├── last_sent    — ts van laatste succesvolle send
    │     └── backoff_until — geblokkeerd tot deze ts (bij 429/fout)
    └── RateLimiter per api_key
          ├── token_bucket — tokens per seconde (sliding window)
          └── global_backoff_until — als API 429 geeft op account-niveau

Debounce-principe:
──────────────────
  Een commando wordt pas gestuurd als de gewenste state DEBOUNCE_S seconden
  onveranderd is. Als de state verandert, reset de timer. Dit voorkomt dat
  elk coordinator-cyclus (10s) een API-aanroep triggert.

  Voorbeeld: boiler wisselt elke 10s tussen boost/green door wisselend surplus?
  → Pas na 10 minuten stabiele staat wordt het commando echt gestuurd.

Backoff-principe:
─────────────────
  Bij 429 of connection error: exponentiële backoff per device.
  Bij globale API-storing: alle devices van die API wachten.

  Backoff schema: [60, 120, 300, 600, 1800] seconden
  Na max_retries: permanent geblokkeerd tot handmatig reset.

Token bucket:
─────────────
  Per api_key maximaal N calls per minuut (configureerbaar).
  Ariston: 6/min (conservatief), Zonneplan: 10/min, SaaS: 60/min.

Gebruik:
────────
    queue = CloudCommandQueue("ariston", debounce_s=600, rate_per_min=6)

    # Elke coordinator-cyclus: registreer de gewenste staat
    fired = await queue.request(
        device_id  = "water_heater.ariston_boiler",
        command    = {"preset": "boost", "setpoint": 53.0},
        executor   = lambda cmd: hass.services.async_call(...),
    )

    # Bij 429:
    queue.report_error("water_heater.ariston_boiler", status_code=429)

    # Bij succes:
    queue.report_success("water_heater.ariston_boiler")
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Standaard backoff schema in seconden
DEFAULT_BACKOFF_S: List[int] = [60, 120, 300, 600, 1800]
# Maximale backoff (30 min)
MAX_BACKOFF_S: int = 1800


@dataclass
class _CommandSlot:
    """Toestand per (device_id, command_type) combinatie."""
    device_id:     str
    api_key:       str

    # Gewenste eindtoestand — laatste wins
    desired:       Dict[str, Any] = field(default_factory=dict)
    desired_since: float = 0.0    # ts van eerste wens in huidige desired-run

    # Verstuurgeschiedenis
    last_sent_ts:  float = 0.0    # ts van laatste succesvolle send
    last_sent_cmd: Dict[str, Any] = field(default_factory=dict)

    # Foutafhandeling
    retry_count:   int   = 0
    backoff_until: float = 0.0
    last_error:    str   = ""
    consecutive_errors: int = 0

    def is_same_as_last(self) -> bool:
        """True als de gewenste staat gelijk is aan wat we de vorige keer stuurden."""
        return self.desired == self.last_sent_cmd

    def is_blocked(self, now: float) -> bool:
        """True als we nog in backoff zitten."""
        return now < self.backoff_until

    def backoff_remaining_s(self, now: float) -> float:
        return max(0.0, self.backoff_until - now)

    def to_dict(self) -> dict:
        return {
            "device_id":     self.device_id,
            "desired":       self.desired,
            "desired_since": round(self.desired_since, 1),
            "last_sent_ts":  round(self.last_sent_ts, 1),
            "retry_count":   self.retry_count,
            "backoff_until": round(self.backoff_until, 1),
            "last_error":    self.last_error,
            "consecutive_errors": self.consecutive_errors,
        }


@dataclass
class _TokenBucket:
    """Sliding-window token bucket voor rate limiting."""
    rate_per_min: float           # max calls per minuut
    _tokens:      float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens     = self.rate_per_min
        self._last_refill = time.time()

    def consume(self) -> bool:
        """Probeer één token te verbruiken. True als beschikbaar."""
        now = time.time()
        elapsed = now - self._last_refill
        # Vul tokens bij op basis van verstreken tijd
        refill = elapsed * (self.rate_per_min / 60.0)
        self._tokens = min(self.rate_per_min, self._tokens + refill)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def tokens_available(self) -> float:
        return round(self._tokens, 2)


class CloudCommandQueue:
    """
    Generieke cloud command queue met debounce, rate-limiting en backoff.

    Platform-agnostisch — één instantie per API/integratie.
    Thread-safe via asyncio (single-threaded HA event loop).
    """

    def __init__(
        self,
        api_key:      str,
        debounce_s:   float = 600.0,   # 10 minuten standaard
        rate_per_min: float = 6.0,     # 6 calls per minuut standaard
        backoff_schedule: Optional[List[int]] = None,
        max_retries:  int   = 5,
    ) -> None:
        self.api_key       = api_key
        self.debounce_s    = debounce_s
        self.max_retries   = max_retries
        self._backoff_s    = backoff_schedule or DEFAULT_BACKOFF_S
        self._bucket       = _TokenBucket(rate_per_min=rate_per_min)
        self._slots:       Dict[str, _CommandSlot] = {}
        self._global_backoff_until: float = 0.0
        self._global_error_count:   int   = 0
        self._total_sent:   int = 0
        self._total_errors: int = 0
        _LOGGER.info(
            "CloudCommandQueue [%s]: debounce=%.0fs rate=%.1f/min backoff=%s",
            api_key, debounce_s, rate_per_min, self._backoff_s,
        )

    # ── Publieke interface ───────────────────────────────────────────────────

    async def request(
        self,
        device_id: str,
        command:   Dict[str, Any],
        executor:  Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> bool:
        """
        Registreer een gewenst commando en stuur het als de tijd rijp is.

        Parameters
        ----------
        device_id : str
            Unieke identifier van het apparaat (bijv. entity_id).
        command : dict
            Gewenste eindtoestand ({"preset": "boost", "setpoint": 53.0}).
            Het laatste aangeleverde command wint altijd.
        executor : async callable
            Functie die het commando daadwerkelijk uitvoert.
            Moet een 429-exception gooien bij rate-limit (of een Exception
            met "429" in de message).

        Returns
        -------
        bool
            True als het commando gestuurd werd, False als gedebounced/geblokkeerd.
        """
        now  = time.time()
        slot = self._get_or_create_slot(device_id)

        # ── Stap 1: update gewenste staat ────────────────────────────────────
        if command != slot.desired:
            # Nieuw doel — reset debounce timer
            if slot.desired and slot.desired != command:
                _LOGGER.debug(
                    "CloudCommandQueue [%s/%s]: doel gewijzigd %s → %s, debounce gereset",
                    self.api_key, device_id, slot.desired, command,
                )
            slot.desired       = command
            slot.desired_since = now

        # ── Stap 2: al hetzelfde als laatste send? ───────────────────────────
        if slot.is_same_as_last():
            return False   # Niets te doen

        # ── Stap 3: debounce check ───────────────────────────────────────────
        time_stable = now - slot.desired_since
        if time_stable < self.debounce_s:
            _LOGGER.debug(
                "CloudCommandQueue [%s/%s]: debounce %.0f/%.0fs — nog niet sturen",
                self.api_key, device_id, time_stable, self.debounce_s,
            )
            return False

        # ── Stap 4: globale backoff check ────────────────────────────────────
        if now < self._global_backoff_until:
            _LOGGER.debug(
                "CloudCommandQueue [%s]: globale backoff nog %.0fs",
                self.api_key, self._global_backoff_until - now,
            )
            return False

        # ── Stap 5: per-device backoff check ─────────────────────────────────
        if slot.is_blocked(now):
            _LOGGER.debug(
                "CloudCommandQueue [%s/%s]: device backoff nog %.0fs",
                self.api_key, device_id, slot.backoff_remaining_s(now),
            )
            return False

        # ── Stap 6: rate limit token bucket ──────────────────────────────────
        if not self._bucket.consume():
            _LOGGER.debug(
                "CloudCommandQueue [%s]: token bucket leeg (%.2f tokens beschikbaar)",
                self.api_key, self._bucket.tokens_available,
            )
            return False

        # ── Stap 7: stuur het commando ───────────────────────────────────────
        try:
            _LOGGER.info(
                "CloudCommandQueue [%s/%s]: sturen na %.0fs stabiel — %s",
                self.api_key, device_id, time_stable, command,
            )
            await executor(command)
            # Succes
            slot.last_sent_ts    = now
            slot.last_sent_cmd   = dict(command)
            slot.retry_count     = 0
            slot.consecutive_errors = 0
            slot.last_error      = ""
            self._total_sent    += 1
            self._global_error_count = 0
            return True

        except Exception as exc:
            self._total_errors += 1
            err_str = str(exc)
            slot.last_error = err_str[:200]
            slot.consecutive_errors += 1

            if "429" in err_str or "too many" in err_str.lower() or "rate" in err_str.lower():
                self._handle_rate_limit(slot, now, device_id)
            elif "timeout" in err_str.lower() or "connection" in err_str.lower():
                self._handle_connection_error(slot, now, device_id)
            else:
                self._handle_generic_error(slot, now, device_id, err_str)
            return False

    def report_error(self, device_id: str, status_code: int = 0, message: str = "") -> None:
        """Rapporteer een fout buiten de executor (bijv. vanuit verify-loop)."""
        slot = self._get_or_create_slot(device_id)
        now  = time.time()
        slot.last_error = f"HTTP {status_code}: {message}"[:200]
        slot.consecutive_errors += 1
        if status_code == 429:
            self._handle_rate_limit(slot, now, device_id)
        else:
            self._handle_generic_error(slot, now, device_id, slot.last_error)

    def report_success(self, device_id: str) -> None:
        """Rapporteer succes (bijv. na verify-loop bevestiging)."""
        slot = self._get_or_create_slot(device_id)
        slot.retry_count        = 0
        slot.consecutive_errors = 0
        slot.last_error         = ""
        slot.backoff_until      = 0.0

    def reset_debounce(self, device_id: str) -> None:
        """Reset debounce-timer voor een device (bijv. na handmatige actie)."""
        slot = self._get_or_create_slot(device_id)
        slot.desired_since = 0.0  # onmiddellijk sturen bij volgende request()

    def get_diagnostics(self) -> dict:
        """Diagnostics voor dashboard/logging."""
        now = time.time()
        return {
            "api_key":              self.api_key,
            "debounce_s":           self.debounce_s,
            "rate_per_min":         self._bucket.rate_per_min,
            "tokens_available":     self._bucket.tokens_available,
            "global_backoff_until": round(self._global_backoff_until, 1),
            "global_backoff_remaining_s": round(max(0, self._global_backoff_until - now), 0),
            "total_sent":           self._total_sent,
            "total_errors":         self._total_errors,
            "devices":              {k: v.to_dict() for k, v in self._slots.items()},
        }

    # ── Interne helpers ──────────────────────────────────────────────────────

    def _get_or_create_slot(self, device_id: str) -> _CommandSlot:
        if device_id not in self._slots:
            self._slots[device_id] = _CommandSlot(
                device_id=device_id,
                api_key=self.api_key,
            )
        return self._slots[device_id]

    def _backoff_delay(self, retry_count: int) -> int:
        idx = min(retry_count, len(self._backoff_s) - 1)
        return self._backoff_s[idx]

    def _handle_rate_limit(self, slot: _CommandSlot, now: float, device_id: str) -> None:
        """429 ontvangen — backoff voor dit device én globale vertraging."""
        delay = self._backoff_delay(slot.retry_count)
        slot.retry_count  += 1
        slot.backoff_until = now + delay

        # Globale backoff: na 3 429s in een sessie → hele API pauze
        self._global_error_count += 1
        if self._global_error_count >= 3:
            global_delay = min(delay * 2, MAX_BACKOFF_S)
            self._global_backoff_until = now + global_delay
            _LOGGER.warning(
                "CloudCommandQueue [%s]: %d× 429 — GLOBALE backoff %.0fs tot %s",
                self.api_key, self._global_error_count, global_delay,
                time.strftime("%H:%M:%S", time.localtime(self._global_backoff_until)),
            )
        _LOGGER.warning(
            "CloudCommandQueue [%s/%s]: 429 rate-limit — device backoff %.0fs (retry %d)",
            self.api_key, device_id, delay, slot.retry_count,
        )

    def _handle_connection_error(self, slot: _CommandSlot, now: float, device_id: str) -> None:
        """Verbindingsfout — kortere backoff dan 429."""
        delay = min(self._backoff_delay(slot.retry_count), 120)
        slot.retry_count  += 1
        slot.backoff_until = now + delay
        _LOGGER.warning(
            "CloudCommandQueue [%s/%s]: verbindingsfout — backoff %.0fs",
            self.api_key, device_id, delay,
        )

    def _handle_generic_error(
        self, slot: _CommandSlot, now: float, device_id: str, err: str
    ) -> None:
        """Generieke fout — korte backoff."""
        delay = min(self._backoff_delay(slot.retry_count), 60)
        slot.retry_count  += 1
        slot.backoff_until = now + delay
        _LOGGER.warning(
            "CloudCommandQueue [%s/%s]: fout '%s' — backoff %.0fs",
            self.api_key, device_id, err[:80], delay,
        )
