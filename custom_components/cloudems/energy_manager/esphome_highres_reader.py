"""
CloudEMS ESPHome High-Resolution Energy Reader — v1.0.0

Leest 1kHz vermogensdata van een ESPHome device via TCP/UDP stream.
Werkt NAAST de coordinator (aparte async task, geen coordinator tick nodig).

Gebruik:
- ESPHome firmware stuurt ruwe ADC samples via TCP naar poort 6053 (of configureerbaar)
- Deze reader buffert de samples in een ringbuffer
- NILM Seq2Point CNN leest van de ringbuffer voor disaggregatie

Data flow:
    ESPHome (1kHz ADC) → TCP stream → ESPhomeHighResReader → ringbuffer → Seq2Point NILM
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable

_LOGGER = logging.getLogger(__name__)

# Ringbuffer: 5 seconden @ 1kHz = 5000 samples
_BUFFER_SIZE = 5000
# Verwacht pakketformaat: 4 bytes float32 (vermogen in W)
_SAMPLE_FORMAT = ">f"  # big-endian float32
_SAMPLE_SIZE   = 4     # bytes


@dataclass
class HighResSample:
    """Één hoge-resolutie vermogenssample."""
    ts:      float   # Unix timestamp (seconden, float)
    power_w: float   # Vermogen in Watt


class ESPhomeHighResReader:
    """
    Async reader voor ESPHome hoge-resolutie energie data.

    Ondersteunt twee modi:
    1. TCP stream: ESPHome stuurt float32 samples via raw TCP
    2. UDP stream: ESPHome stuurt UDP pakketjes met float32 samples

    De ringbuffer is thread-safe via asyncio.
    """

    def __init__(
        self,
        host: str,
        port: int = 6053,
        mode: str = "tcp",
        on_sample_callback: Optional[Callable[[HighResSample], None]] = None,
    ) -> None:
        self._host     = host
        self._port     = port
        self._mode     = mode
        self._callback = on_sample_callback

        # Ringbuffer: deque met max 5000 samples
        self._buffer: deque[HighResSample] = deque(maxlen=_BUFFER_SIZE)

        self._running  = False
        self._task:    Optional[asyncio.Task] = None
        self._sample_count = 0
        self._last_sample_ts = 0.0
        self._connect_errors = 0

        # Statistieken
        self._samples_per_sec: float = 0.0
        self._last_rate_calc  = time.time()
        self._rate_count      = 0

    async def async_start(self) -> None:
        """Start de high-res reader als achtergrondtaak."""
        self._running = True
        if self._mode == "tcp":
            self._task = asyncio.ensure_future(self._read_tcp())
        elif self._mode == "udp":
            self._task = asyncio.ensure_future(self._read_udp())
        else:
            _LOGGER.error("ESPhomeHighResReader: onbekende mode '%s'", self._mode)

    async def async_stop(self) -> None:
        """Stop de reader."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Buffer API ──────────────────────────────────────────────────────────

    def get_latest(self, n: int = 1000) -> list[HighResSample]:
        """Geef de laatste n samples terug."""
        return list(self._buffer)[-n:]

    def get_power_array(self, n: int = 1000) -> list[float]:
        """Geef alleen de vermogenswaarden terug (voor CNN input)."""
        return [s.power_w for s in self.get_latest(n)]

    @property
    def available(self) -> bool:
        return self._running and self._sample_count > 0

    @property
    def samples_per_sec(self) -> float:
        return self._samples_per_sec

    @property
    def stats(self) -> dict:
        return {
            "host":            self._host,
            "port":            self._port,
            "mode":            self._mode,
            "available":       self.available,
            "sample_count":    self._sample_count,
            "samples_per_sec": round(self._samples_per_sec, 1),
            "buffer_size":     len(self._buffer),
            "connect_errors":  self._connect_errors,
            "last_sample_ago": round(time.time() - self._last_sample_ts, 1) if self._last_sample_ts else None,
        }

    # ── Interne readers ─────────────────────────────────────────────────────

    def _accept_sample(self, power_w: float) -> None:
        """Verwerk een nieuw sample: voeg toe aan buffer en roep callback aan."""
        now = time.time()
        sample = HighResSample(ts=now, power_w=power_w)
        self._buffer.append(sample)
        self._sample_count += 1
        self._last_sample_ts = now
        self._rate_count += 1

        # Update samples/sec elke seconde
        elapsed = now - self._last_rate_calc
        if elapsed >= 1.0:
            self._samples_per_sec = self._rate_count / elapsed
            self._rate_count      = 0
            self._last_rate_calc  = now

        if self._callback:
            try:
                self._callback(sample)
            except Exception:
                pass

    async def _read_tcp(self) -> None:
        """Lees float32 samples van een TCP stream."""
        _LOGGER.info("ESPhomeHighResReader TCP: verbinden met %s:%d", self._host, self._port)
        while self._running:
            try:
                reader, _ = await asyncio.open_connection(self._host, self._port)
                _LOGGER.info("ESPhomeHighResReader TCP: verbonden met %s:%d", self._host, self._port)
                self._connect_errors = 0
                buf = b""
                while self._running:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while len(buf) >= _SAMPLE_SIZE:
                        (power_w,) = struct.unpack_from(_SAMPLE_FORMAT, buf, 0)
                        buf = buf[_SAMPLE_SIZE:]
                        self._accept_sample(power_w)
            except Exception as err:
                self._connect_errors += 1
                _LOGGER.debug(
                    "ESPhomeHighResReader TCP fout (poging %d): %s — opnieuw in 5s",
                    self._connect_errors, err
                )
                await asyncio.sleep(5)

    async def _read_udp(self) -> None:
        """Lees float32 samples van UDP pakketjes."""
        _LOGGER.info("ESPhomeHighResReader UDP: luisteren op poort %d", self._port)
        loop = asyncio.get_event_loop()

        class _UDPProtocol(asyncio.DatagramProtocol):
            def __init__(self, reader: "ESPhomeHighResReader") -> None:
                self._reader = reader

            def datagram_received(self, data: bytes, addr: tuple) -> None:
                offset = 0
                while offset + _SAMPLE_SIZE <= len(data):
                    (power_w,) = struct.unpack_from(_SAMPLE_FORMAT, data, offset)
                    self._reader._accept_sample(power_w)
                    offset += _SAMPLE_SIZE

        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UDPProtocol(self),
                local_addr=("0.0.0.0", self._port),
            )
            while self._running:
                await asyncio.sleep(1)
            transport.close()
        except Exception as err:
            _LOGGER.error("ESPhomeHighResReader UDP fout: %s", err)
