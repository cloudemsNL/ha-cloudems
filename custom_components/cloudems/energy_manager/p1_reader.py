"""
CloudEMS P1 Smart Meter Reader (DSMR).

Reads the Dutch/Belgian DSMR P1 telegram either from:
  • a local network socket (e.g. HomeWizard, SLIMMELEZER, P1 USB gateway)
  • a serial port (direct USB connection)

Parsed values are made available via the `latest` property so the
coordinator can use them instead of (or to supplement) HA sensor values.

Supported DSMR versions: 2.2, 4.x, 5.x (including ESMR 5.0.2)

Copyright © 2025 CloudEMS — https://cloudems.eu
"""

from __future__ import annotations
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ..const import (
    CONF_P1_HOST, CONF_P1_PORT, CONF_P1_SERIAL_PORT,
    DEFAULT_P1_PORT, DSMR_TELEGRAM_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# ── DSMR OBIS reference codes ──────────────────────────────────────────────────
_OBIS = {
    # Total delivered (import) kWh
    "power_import_t1":  r"1-0:1\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_import_t2":  r"1-0:1\.8\.2\((\d+\.\d+)\*kWh\)",
    # Total returned (export) kWh
    "power_export_t1":  r"1-0:2\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_export_t2":  r"1-0:2\.8\.2\((\d+\.\d+)\*kWh\)",
    # Current actual power W
    "power_import_w":   r"1-0:1\.7\.0\((\d+\.\d+)\*kW\)",
    "power_export_w":   r"1-0:2\.7\.0\((\d+\.\d+)\*kW\)",
    # Per-phase current (A)
    "current_l1":       r"1-0:31\.7\.0\((\d+\.\d+)\*A\)",
    "current_l2":       r"1-0:51\.7\.0\((\d+\.\d+)\*A\)",
    "current_l3":       r"1-0:71\.7\.0\((\d+\.\d+)\*A\)",
    # Per-phase power (W) DSMR5
    "power_l1_import":  r"1-0:21\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l2_import":  r"1-0:41\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l3_import":  r"1-0:61\.7\.0\((\d+\.\d+)\*kW\)",
    # Gas (m³) — DSMR MSN telegram
    "gas_m3":           r"0-1:24\.2\.1\(\d+W\)\(\d+\.\d+\*m3\)",
    # Tariff indicator (1=low, 2=high)
    "tariff":           r"0-0:96\.14\.0\((\d+)\)",
}


@dataclass
class P1Telegram:
    """Parsed P1 telegram values. All power in W, current in A."""
    power_import_w: float = 0.0
    power_export_w: float = 0.0
    # Per-phase power (DSMR5 only, kW in telegram → stored as W)
    power_l1_import_w: float = 0.0
    power_l2_import_w: float = 0.0
    power_l3_import_w: float = 0.0
    energy_import_kwh: float = 0.0
    energy_export_kwh: float = 0.0
    current_l1: float = 0.0
    current_l2: float = 0.0
    current_l3: float = 0.0
    power_l1_w: float = 0.0
    power_l2_w: float = 0.0
    power_l3_w: float = 0.0
    tariff: int = 1
    raw: str = field(default="", repr=False)

    @property
    def net_power_w(self) -> float:
        """Positive = import, negative = export."""
        return self.power_import_w - self.power_export_w

    @property
    def phase_currents(self) -> dict[str, float]:
        return {"L1": self.current_l1, "L2": self.current_l2, "L3": self.current_l3}


def parse_telegram(raw: str) -> P1Telegram:
    """Parse a raw DSMR telegram string into a P1Telegram."""
    t = P1Telegram(raw=raw)

    def _get(key: str) -> Optional[float]:
        m = re.search(_OBIS[key], raw)
        return float(m.group(1)) if m else None

    t1 = _get("power_import_t1") or 0.0
    t2 = _get("power_import_t2") or 0.0
    t.energy_import_kwh = t1 + t2

    x1 = _get("power_export_t1") or 0.0
    x2 = _get("power_export_t2") or 0.0
    t.energy_export_kwh = x1 + x2

    # Power in kW → W
    imp = _get("power_import_w")
    exp = _get("power_export_w")
    t.power_import_w = (imp or 0.0) * 1000
    t.power_export_w = (exp or 0.0) * 1000

    t.current_l1 = _get("current_l1") or 0.0
    t.current_l2 = _get("current_l2") or 0.0
    t.current_l3 = _get("current_l3") or 0.0

    # Phase power kW → W
    t.power_l1_w = (_get("power_l1_import") or 0.0) * 1000
    t.power_l2_w = (_get("power_l2_import") or 0.0) * 1000
    t.power_l3_w = (_get("power_l3_import") or 0.0) * 1000

    tariff = _get("tariff")
    t.tariff = int(tariff) if tariff else 1

    return t


class P1Reader:
    """
    Async P1 telegram reader.

    Connects to a TCP socket (HomeWizard, SLIMMELEZER, …) or a serial
    port and continuously parses DSMR telegrams.
    """

    def __init__(self, config: dict) -> None:
        self._host: str | None = config.get(CONF_P1_HOST)
        self._port: int = int(config.get(CONF_P1_PORT, DEFAULT_P1_PORT))
        self._serial: str | None = config.get(CONF_P1_SERIAL_PORT)
        self._latest: P1Telegram | None = None
        self._running: bool = False
        self._task: asyncio.Task | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def latest(self) -> P1Telegram | None:
        return self._latest

    @property
    def available(self) -> bool:
        return self._latest is not None

    async def async_start(self) -> None:
        """Start background reading task."""
        self._running = True
        if self._host:
            self._task = asyncio.ensure_future(self._read_tcp())
        elif self._serial:
            self._task = asyncio.ensure_future(self._read_serial())
        else:
            _LOGGER.warning("P1Reader: no host or serial port configured — disabled")

    async def async_stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ── TCP reader ─────────────────────────────────────────────────────────────

    async def _read_tcp(self) -> None:
        """Read telegrams from a TCP socket, reconnect on error."""
        _LOGGER.info("P1Reader: connecting to %s:%d", self._host, self._port)
        while self._running:
            try:
                reader, _ = await asyncio.open_connection(self._host, self._port)
                _LOGGER.info("P1Reader: connected to %s:%d", self._host, self._port)
                buffer = ""
                async for line in reader:
                    if not self._running:
                        break
                    text = line.decode("ascii", errors="replace")
                    buffer += text
                    # DSMR telegram ends with "!" followed by CRC
                    if text.startswith("!"):
                        try:
                            self._latest = parse_telegram(buffer)
                        except Exception as ex:
                            _LOGGER.debug("P1Reader parse error: %s", ex)
                        buffer = ""
            except Exception as err:
                _LOGGER.warning("P1Reader TCP error: %s — retry in 30s", err)
                await asyncio.sleep(30)

    # ── Serial reader ──────────────────────────────────────────────────────────

    async def _read_serial(self) -> None:
        """Read telegrams from serial port (requires pyserial-asyncio)."""
        try:
            import serial_asyncio  # type: ignore
        except ImportError:
            _LOGGER.error(
                "P1Reader: pyserial-asyncio is required for serial mode. "
                "Add 'pyserial-asyncio>=0.6' to requirements."
            )
            return

        while self._running:
            try:
                reader, _ = await serial_asyncio.open_serial_connection(
                    url=self._serial, baudrate=115200
                )
                _LOGGER.info("P1Reader: serial connected on %s", self._serial)
                buffer = ""
                async for line in reader:
                    if not self._running:
                        break
                    text = line.decode("ascii", errors="replace")
                    buffer += text
                    if text.startswith("!"):
                        try:
                            self._latest = parse_telegram(buffer)
                        except Exception as ex:
                            _LOGGER.debug("P1Reader serial parse error: %s", ex)
                        buffer = ""
            except Exception as err:
                _LOGGER.warning("P1Reader serial error: %s — retry in 30s", err)
                await asyncio.sleep(30)
