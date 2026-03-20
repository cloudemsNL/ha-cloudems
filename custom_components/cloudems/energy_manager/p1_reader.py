# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS P1 / DSMR Smart Meter Reader -- v2.0.0

Drop-in vervanging voor de officiele HA DSMR-integratie.
Gebruikers hoeven GEEN aparte DSMR/HomeWizard integratie te installeren.

VERBINDINGEN (automatisch geprobeerd in deze volgorde)
======================================================
1. Direct TCP  -- HomeWizard Energy, SLIMMELEZER+, P1ib, esp-p1reader (TCP-modus)
2. Serieel USB -- directe P1-kabel op /dev/ttyUSB0 (of ingesteld pad)
3. MQTT        -- SLIMMELEZER v2, esp-p1reader, P1ib in MQTT-modus
4. Fallback    -- lees van bestaande DSMR/HomeWizard HA-entiteiten
                  (als een van deze integraties al geinstalleerd is)

DSMR VERSIES
============
- DSMR 2.2     (baudrate 9600, MSN op 0-0:96.1.0)
- DSMR 4.x     (baudrate 115200)
- DSMR 5.x     (per-fase vermogen + spanning)
- ESMR 5.0.2   (uitgebreide OBIS-set, MSN waterkanalen)
- Fluvius 1.0  (Belgie, deels andere OBIS-codes)

OBIS-SET (volledig)
===================
Elektriciteit: import/export kWh T1/T2, actueel vermogen W, per-fase W+A+V,
               power factor, spanningsafwijkingen, storingen
Gas:           MSN 0-1 t/m 0-4 (gas, water, warmte, koude)
Meta:          tariefstand, meterstatus, identifikatiestrings

CRC VALIDATIE
=============
Elke telegram wordt gevalideerd via CRC16 (IBM polynomial 0xA001).
Corrupte telegrams worden gelogd en genegeerd.

HA SENSOR ENTITIES
==================
Alle P1-waarden worden als CloudEMS sensor entities beschikbaar gesteld
(prefix: sensor.cloudems_p1_*) zodat andere integraties en dashboards
er gebruik van kunnen maken, ook zonder aparte DSMR-integratie.

Copyright (c) 2025 CloudEMS -- https://cloudems.eu
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

try:
    from ..const import (
        CONF_P1_HOST, CONF_P1_PORT, CONF_P1_SERIAL_PORT,
        DEFAULT_P1_PORT, DSMR_TELEGRAM_INTERVAL,
    )
except ImportError:
    CONF_P1_HOST       = "p1_host"
    CONF_P1_PORT       = "p1_port"
    CONF_P1_SERIAL_PORT = "p1_serial_port"
    DEFAULT_P1_PORT    = 8088
    DSMR_TELEGRAM_INTERVAL = 10

# ── Baudrates per DSMR versie ─────────────────────────────────────────────────
DSMR_BAUD = {
    "2.2": 9600,
    "4":   115200,
    "5":   115200,
    "fluvius": 115200,
}

# ── CRC16 (IBM / ANSI polynomial 0xA001) ─────────────────────────────────────
def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def _validate_crc(raw: str) -> bool:
    """Validate CRC of a DSMR telegram. Returns True if valid or no CRC present."""
    bang = raw.rfind("!")
    if bang == -1:
        return False
    body     = raw[:bang + 1]
    crc_str  = raw[bang + 1:].strip().split()[0] if raw[bang + 1:].strip() else ""
    if not crc_str:
        return True   # DSMR 2.2 has no CRC -- accept without validation
    try:
        expected = int(crc_str, 16)
    except ValueError:
        return True   # unparseable CRC -- accept (lenient)
    computed = _crc16(body.encode("ascii", errors="replace"))
    if computed != expected:
        _LOGGER.debug("P1Reader: CRC mismatch computed=0x%04X expected=0x%04X", computed, expected)
    return computed == expected

# ── OBIS codes -- volledig (NL DSMR5 + Fluvius BE) ───────────────────────────
# Regex groups: alle keys geven float(group(1)), integers via int() na parsen
_OBIS_NL: Dict[str, str] = {
    # Energie totalen (kWh)
    "power_import_t1":        r"1-0:1\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_import_t2":        r"1-0:1\.8\.2\((\d+\.\d+)\*kWh\)",
    "power_export_t1":        r"1-0:2\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_export_t2":        r"1-0:2\.8\.2\((\d+\.\d+)\*kWh\)",
    # Actueel vermogen (kW)
    "power_import_w":         r"1-0:1\.7\.0\((\d+\.\d+)\*kW\)",
    "power_export_w":         r"1-0:2\.7\.0\((\d+\.\d+)\*kW\)",
    # Per-fase vermogen import (kW) -- DSMR5
    "power_l1_import":        r"1-0:21\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l2_import":        r"1-0:41\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l3_import":        r"1-0:61\.7\.0\((\d+\.\d+)\*kW\)",
    # Per-fase vermogen export (kW) -- DSMR5
    "power_l1_export":        r"1-0:22\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l2_export":        r"1-0:42\.7\.0\((\d+\.\d+)\*kW\)",
    "power_l3_export":        r"1-0:62\.7\.0\((\d+\.\d+)\*kW\)",
    # Per-fase stroom (A)
    "current_l1":             r"1-0:31\.7\.0\((\d+\.\d+)\*A\)",
    "current_l2":             r"1-0:51\.7\.0\((\d+\.\d+)\*A\)",
    "current_l3":             r"1-0:71\.7\.0\((\d+\.\d+)\*A\)",
    # Per-fase spanning (V) -- DSMR5
    "voltage_l1":             r"1-0:32\.7\.0\((\d+\.\d+)\*V\)",
    "voltage_l2":             r"1-0:52\.7\.0\((\d+\.\d+)\*V\)",
    "voltage_l3":             r"1-0:72\.7\.0\((\d+\.\d+)\*V\)",
    # Per-fase power factor (0-1) -- DSMR5
    "power_factor_l1":        r"1-0:33\.7\.0\((\d+\.\d+)\)",
    "power_factor_l2":        r"1-0:53\.7\.0\((\d+\.\d+)\)",
    "power_factor_l3":        r"1-0:73\.7\.0\((\d+\.\d+)\)",
    "power_factor_total":     r"1-0:13\.7\.0\((\d+\.\d+)\)",
    # Tariefstand (1=laag, 2=hoog)
    "tariff":                 r"0-0:96\.14\.0\((\d+)\)",
    # Storingen
    "power_failures":         r"0-0:96\.7\.21\((\d+)\)",
    "long_power_failures":    r"0-0:96\.7\.9\((\d+)\)",
    # Spanningsafwijkingen per fase
    "voltage_sags_l1":        r"1-0:32\.32\.0\((\d+)\)",
    "voltage_sags_l2":        r"1-0:52\.32\.0\((\d+)\)",
    "voltage_sags_l3":        r"1-0:72\.32\.0\((\d+)\)",
    "voltage_swells_l1":      r"1-0:32\.36\.0\((\d+)\)",
    "voltage_swells_l2":      r"1-0:52\.36\.0\((\d+)\)",
    "voltage_swells_l3":      r"1-0:72\.36\.0\((\d+)\)",
    # Gas -- MSN kanaal 0-1 (standaard NL)
    "gas_m3":                 r"0-1:24\.2\.1\(\d{12}[SW]\)\((\d+\.\d+)\*m3\)",
    # Water -- MSN kanaal 0-2 (ESMR5, sommige netbeheerders)
    "water_m3":               r"0-2:24\.2\.1\(\d{12}[SW]\)\((\d+\.\d+)\*m3\)",
    # Warmte -- MSN kanaal 0-3 (stadswarmte)
    "heat_gj":                r"0-3:24\.2\.1\(\d{12}[SW]\)\((\d+\.\d+)\*GJ\)",
    # Koude -- MSN kanaal 0-4
    "cold_gj":                r"0-4:24\.2\.1\(\d{12}[SW]\)\((\d+\.\d+)\*GJ\)",
}

# Fluvius (Belgie) -- afwijkende OBIS voor sommige velden
_OBIS_FLUVIUS_EXTRA: Dict[str, str] = {
    "power_import_t1":        r"1-0:1\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_import_t2":        r"1-0:1\.8\.2\((\d+\.\d+)\*kWh\)",
    "power_export_t1":        r"1-0:2\.8\.1\((\d+\.\d+)\*kWh\)",
    "power_export_t2":        r"1-0:2\.8\.2\((\d+\.\d+)\*kWh\)",
    # Fluvius gebruikt dezelfde OBIS maar soms ander formaat (geen *kW, maar *W)
    "power_import_w_fluvius": r"1-0:1\.7\.0\((\d+\.\d+)\*W\)",
    "power_export_w_fluvius": r"1-0:2\.7\.0\((\d+\.\d+)\*W\)",
    # Gas BE (MSN 0-1, maar soms m3 per uur ipv absoluut)
    "gas_m3_be":              r"0-1:24\.2\.3\(\d{12}[SW]\)\((\d+\.\d+)\*m3\)",
}

# DSMR 2.2 identificatieregels (header begint met /)
_DSMR22_HEADER = re.compile(r"^/[A-Z]{3}\\d|^/[A-Z]{3}[0-9]")


@dataclass
class MsnDevice:
    """Een MSN (Meter Sub Network) sub-apparaat."""
    channel:     int        # 0-1=gas, 0-2=water, 0-3=warmte, 0-4=koude
    device_type: str        # "gas" | "water" | "heat" | "cold"
    value:       float = 0.0
    unit:        str   = "m3"
    timestamp:   str   = ""


@dataclass
class P1Telegram:
    """Volledig geparsed DSMR P1 telegram. Alle vermogens in W, stroom in A, spanning in V."""

    # ── Energie totalen ──────────────────────────────────────────────────────
    power_import_w:        float = 0.0
    power_export_w:        float = 0.0
    energy_import_kwh:     float = 0.0
    energy_export_kwh:     float = 0.0
    energy_import_t1_kwh:  float = 0.0
    energy_import_t2_kwh:  float = 0.0
    energy_export_t1_kwh:  float = 0.0
    energy_export_t2_kwh:  float = 0.0

    # ── Per-fase import vermogen (W) ─────────────────────────────────────────
    power_l1_w:            float = 0.0
    power_l2_w:            float = 0.0
    power_l3_w:            float = 0.0

    # ── Per-fase export vermogen (W) ─────────────────────────────────────────
    power_l1_export_w:     float = 0.0
    power_l2_export_w:     float = 0.0
    power_l3_export_w:     float = 0.0

    # ── Per-fase stroom (A) ──────────────────────────────────────────────────
    current_l1:            Optional[float] = None  # None = veld niet in telegram
    current_l2:            Optional[float] = None
    current_l3:            Optional[float] = None

    # ── Per-fase spanning (V) ────────────────────────────────────────────────
    voltage_l1:            float = 0.0
    voltage_l2:            float = 0.0
    voltage_l3:            float = 0.0

    # ── Power factor ─────────────────────────────────────────────────────────
    power_factor_l1:       float = 0.0
    power_factor_l2:       float = 0.0
    power_factor_l3:       float = 0.0
    power_factor_total:    float = 0.0

    # ── Tarief en storingen ──────────────────────────────────────────────────
    tariff:                int   = 1
    power_failures:        int   = 0
    long_power_failures:   int   = 0
    voltage_sags_l1:       int   = 0
    voltage_sags_l2:       int   = 0
    voltage_sags_l3:       int   = 0
    voltage_swells_l1:     int   = 0
    voltage_swells_l2:     int   = 0
    voltage_swells_l3:     int   = 0

    # ── MSN sub-apparaten ────────────────────────────────────────────────────
    gas_m3:                float = 0.0
    gas_kwh:               float = 0.0
    water_m3:              float = 0.0
    heat_gj:               float = 0.0
    cold_gj:               float = 0.0
    msn_devices:           List[MsnDevice] = field(default_factory=list)

    # ── Meta ─────────────────────────────────────────────────────────────────
    dsmr_version:          str   = "5"
    meter_id:              str   = ""
    crc_valid:             bool  = True
    timestamp:             float = field(default_factory=time.time)
    raw:                   str   = field(default="", repr=False)

    @property
    def net_power_w(self) -> float:
        """Positief = afname, negatief = teruglevering."""
        return self.power_import_w - self.power_export_w

    @property
    def phase_currents(self) -> Dict[str, float]:
        return {"L1": self.current_l1, "L2": self.current_l2, "L3": self.current_l3}

    @property
    def phase_voltages(self) -> Dict[str, float]:
        return {"L1": self.voltage_l1, "L2": self.voltage_l2, "L3": self.voltage_l3}

    @property
    def phase_powers_net(self) -> Dict[str, float]:
        """Netto per-fase vermogen (import - export), in W."""
        return {
            "L1": self.power_l1_w - self.power_l1_export_w,
            "L2": self.power_l2_w - self.power_l2_export_w,
            "L3": self.power_l3_w - self.power_l3_export_w,
        }

    def to_sensor_dict(self) -> Dict[str, Any]:
        """Geef alle waarden als plat dict voor sensor-entity-aanmaak."""
        return {
            "net_power_w":          round(self.net_power_w, 0),
            "power_import_w":       round(self.power_import_w, 0),
            "power_export_w":       round(self.power_export_w, 0),
            "energy_import_kwh":    round(self.energy_import_kwh, 3),
            "energy_export_kwh":    round(self.energy_export_kwh, 3),
            "energy_import_t1_kwh": round(self.energy_import_t1_kwh, 3),
            "energy_import_t2_kwh": round(self.energy_import_t2_kwh, 3),
            "energy_export_t1_kwh": round(self.energy_export_t1_kwh, 3),
            "energy_export_t2_kwh": round(self.energy_export_t2_kwh, 3),
            "power_l1_w":           round(self.power_l1_w, 0),
            "power_l2_w":           round(self.power_l2_w, 0),
            "power_l3_w":           round(self.power_l3_w, 0),
            "current_l1":           round(self.current_l1, 2) if self.current_l1 is not None else None,
            "current_l2":           round(self.current_l2, 2) if self.current_l2 is not None else None,
            "current_l3":           round(self.current_l3, 2) if self.current_l3 is not None else None,
            "voltage_l1":           round(self.voltage_l1, 1),
            "voltage_l2":           round(self.voltage_l2, 1),
            "voltage_l3":           round(self.voltage_l3, 1),
            "power_factor_total":   round(self.power_factor_total, 2),
            "tariff":               self.tariff,
            "gas_m3":               round(self.gas_m3, 3),
            "water_m3":             round(self.water_m3, 3),
            "heat_gj":              round(self.heat_gj, 3),
            "power_failures":       self.power_failures,
            "dsmr_version":         self.dsmr_version,
            "meter_id":             self.meter_id,
            "crc_valid":            self.crc_valid,
        }


# ── Telegram parser ───────────────────────────────────────────────────────────

def _detect_version(raw: str) -> str:
    """Detecteer DSMR-versie uit telegram-header."""
    # DSMR5: 0-0:96.1.4 bevat versiestring "50" of "42"
    m = re.search(r"0-0:96\.1\.4\((\d+)\)", raw)
    if m:
        v = m.group(1)
        if v.startswith("50"):  return "5"
        if v.startswith("42"):  return "4"
        if v.startswith("FLU"): return "fluvius"
    # Fluvius: header bevat /FLU of /ELX
    if re.search(r"^/(?:FLU|ELX|SAG|MSN)", raw, re.MULTILINE):
        return "fluvius"
    # DSMR2.2: header begint met /XXX\ (backslash)
    if re.search(r"^/[A-Z]{3}\\", raw, re.MULTILINE):
        return "2.2"
    return "5"   # standaard aannemen


def _get_obis(raw: str, obis_table: Dict[str, str], key: str) -> Optional[float]:
    pattern = obis_table.get(key)
    if not pattern:
        return None
    m = re.search(pattern, raw)
    return float(m.group(1)) if m else None


def _parse_meter_id(raw: str) -> str:
    """Lees meter-serienummer uit telegram."""
    # 0-0:96.1.1 = equipment identifier
    m = re.search(r"0-0:96\.1\.1\(([0-9A-Fa-f]+)\)", raw)
    if m:
        try:
            return bytes.fromhex(m.group(1)).decode("ascii", errors="replace").strip()
        except Exception:
            return m.group(1)
    return ""


def _parse_msn_devices(raw: str) -> List[MsnDevice]:
    """Detecteer alle MSN sub-apparaten (gas, water, warmte, koude)."""
    devices: List[MsnDevice] = []

    # MSN type-codes: 3=gas, 7=water, 5=warmte, 255=overig
    type_map = {
        "003": "gas",  "3": "gas",
        "007": "water","7": "water",
        "005": "heat", "5": "heat",
        "006": "cold", "6": "cold",
    }
    unit_map = {"gas": "m3", "water": "m3", "heat": "GJ", "cold": "GJ"}

    for channel in range(1, 5):
        # Device-type code
        m_type = re.search(
            rf"0-{channel}:24\.1\.0\((\d+)\)", raw
        )
        if not m_type:
            continue
        type_code = m_type.group(1).lstrip("0") or "0"
        device_type = type_map.get(type_code, "unknown")

        # Meterstand + timestamp
        # ESMR5 formaat: (timestamp)(waarde*eenheid)
        m_val = re.search(
            rf"0-{channel}:24\.2\.[13]\((\d{{12}}[SW])\)\((\d+\.\d+)\*(\w+)\)",
            raw,
        )
        if m_val:
            devices.append(MsnDevice(
                channel=channel,
                device_type=device_type,
                value=float(m_val.group(2)),
                unit=m_val.group(3),
                timestamp=m_val.group(1),
            ))

    return devices


def parse_telegram(raw: str) -> P1Telegram:
    """
    Parseer een rauw DSMR P1 telegramstring naar P1Telegram.

    Ondersteunt: DSMR 2.2 / 4.x / 5.x / ESMR5 / Fluvius
    Valideert CRC (indien aanwezig).
    """
    t = P1Telegram(raw=raw)
    t.crc_valid   = _validate_crc(raw)
    t.dsmr_version = _detect_version(raw)
    t.meter_id    = _parse_meter_id(raw)

    # Gebruik juiste OBIS-tabel
    obis = _OBIS_NL.copy()
    if t.dsmr_version == "fluvius":
        obis.update(_OBIS_FLUVIUS_EXTRA)

    def _get(key: str) -> Optional[float]:
        return _get_obis(raw, obis, key)

    # ── Energie totalen ──────────────────────────────────────────────────────
    t1 = _get("power_import_t1") or 0.0
    t2 = _get("power_import_t2") or 0.0
    t.energy_import_kwh    = round(t1 + t2, 3)
    t.energy_import_t1_kwh = round(t1, 3)
    t.energy_import_t2_kwh = round(t2, 3)

    x1 = _get("power_export_t1") or 0.0
    x2 = _get("power_export_t2") or 0.0
    t.energy_export_kwh    = round(x1 + x2, 3)
    t.energy_export_t1_kwh = round(x1, 3)
    t.energy_export_t2_kwh = round(x2, 3)

    # ── Actueel vermogen ─────────────────────────────────────────────────────
    imp = _get("power_import_w")
    exp = _get("power_export_w")

    if t.dsmr_version == "fluvius":
        # Fluvius kan in W of kW staan
        imp_w = _get("power_import_w_fluvius")
        exp_w = _get("power_export_w_fluvius")
        if imp_w is not None:
            t.power_import_w = imp_w   # al in W
        elif imp is not None:
            t.power_import_w = imp * 1000
        if exp_w is not None:
            t.power_export_w = exp_w
        elif exp is not None:
            t.power_export_w = exp * 1000
    else:
        t.power_import_w = (imp or 0.0) * 1000
        t.power_export_w = (exp or 0.0) * 1000

    # ── Per-fase import vermogen ─────────────────────────────────────────────
    t.power_l1_w = (_get("power_l1_import") or 0.0) * 1000
    t.power_l2_w = (_get("power_l2_import") or 0.0) * 1000
    t.power_l3_w = (_get("power_l3_import") or 0.0) * 1000

    # ── Per-fase export vermogen ─────────────────────────────────────────────
    t.power_l1_export_w = (_get("power_l1_export") or 0.0) * 1000
    t.power_l2_export_w = (_get("power_l2_export") or 0.0) * 1000
    t.power_l3_export_w = (_get("power_l3_export") or 0.0) * 1000

    # ── Stroom ───────────────────────────────────────────────────────────────
    t.current_l1 = _get("current_l1")  # None als veld ontbreekt in telegram (DSMR4)
    t.current_l2 = _get("current_l2")
    t.current_l3 = _get("current_l3")

    # ── Spanning ─────────────────────────────────────────────────────────────
    t.voltage_l1 = _get("voltage_l1") or 0.0
    t.voltage_l2 = _get("voltage_l2") or 0.0
    t.voltage_l3 = _get("voltage_l3") or 0.0

    # ── Power factor ─────────────────────────────────────────────────────────
    t.power_factor_l1    = _get("power_factor_l1")    or 0.0
    t.power_factor_l2    = _get("power_factor_l2")    or 0.0
    t.power_factor_l3    = _get("power_factor_l3")    or 0.0
    t.power_factor_total = _get("power_factor_total") or 0.0

    # ── Tarief en storingen ──────────────────────────────────────────────────
    tariff = _get("tariff")
    t.tariff = int(tariff) if tariff else 1
    for fld in ("power_failures", "long_power_failures",
                "voltage_sags_l1",   "voltage_sags_l2",   "voltage_sags_l3",
                "voltage_swells_l1", "voltage_swells_l2", "voltage_swells_l3"):
        v = _get(fld)
        if v is not None:
            setattr(t, fld, int(v))

    # ── MSN sub-apparaten ────────────────────────────────────────────────────
    t.msn_devices = _parse_msn_devices(raw)
    for dev in t.msn_devices:
        if dev.device_type == "gas":
            t.gas_m3  = dev.value
            t.gas_kwh = round(dev.value * 9.769, 3)
        elif dev.device_type == "water":
            t.water_m3 = dev.value
        elif dev.device_type == "heat":
            t.heat_gj = dev.value
        elif dev.device_type == "cold":
            t.cold_gj = dev.value

    # Fallback gas via enkelvoudig OBIS (als MSN geen resultaat gaf)
    if t.gas_m3 == 0.0:
        gas = _get("gas_m3")
        if gas:
            t.gas_m3  = round(gas, 3)
            t.gas_kwh = round(gas * 9.769, 3)

    t.timestamp = time.time()
    return t


# ── HA entity fallback reader ─────────────────────────────────────────────────

class HAEntityFallbackReader:
    """
    Leest P1-data vanuit bestaande HA DSMR/HomeWizard sensor-entities.
    Wordt gebruikt als er geen directe P1-verbinding beschikbaar is
    maar de DSMR- of HomeWizard-integratie al geinstalleerd is.
    """

    # Bekende entity-ID patronen per netwerk van integraties
    _PATTERNS: Dict[str, List[str]] = {
        "power_import_w": [
            "sensor.dsmr_reading_electricity_currently_delivered",
            "sensor.homewizard_p1_active_power_w",
            "sensor.p1_active_power",
            "sensor.slimmelezer_power_delivered",
            "sensor.electricity_power_usage",
            "sensor.active_power",
        ],
        "power_export_w": [
            "sensor.dsmr_reading_electricity_currently_returned",
            "sensor.homewizard_p1_active_power_l1_w",
            "sensor.p1_active_power_returned",
        ],
        "energy_import_kwh": [
            "sensor.dsmr_day_consumption_electricity_merged",
            "sensor.homewizard_p1_total_power_import_kwh",
            "sensor.electricity_imported_total",
        ],
        "energy_export_kwh": [
            "sensor.dsmr_day_consumption_electricity_returned_merged",
            "sensor.homewizard_p1_total_power_export_kwh",
        ],
        "gas_m3": [
            "sensor.dsmr_day_consumption_gas",
            "sensor.homewizard_p1_total_gas_m3",
            "sensor.gas_meter_reading",
        ],
    }

    def __init__(self, hass) -> None:
        self._hass = hass
        self._resolved: Dict[str, str] = {}   # key -> entity_id
        self._last_scan: float = 0.0

    def _resolve(self) -> None:
        """Zoek eenmalig de best passende entities op."""
        if time.time() - self._last_scan < 300:   # elke 5 min opnieuw scannen
            return
        self._last_scan = time.time()
        all_states = {s.entity_id for s in self._hass.states.async_all()}
        for key, candidates in self._PATTERNS.items():
            for eid in candidates:
                if eid in all_states:
                    if key not in self._resolved:
                        _LOGGER.debug("P1 HAFallback: %s -> %s", key, eid)
                    self._resolved[key] = eid
                    break

    def read(self) -> Optional[P1Telegram]:
        """Lees een synthetisch telegram vanuit HA entiteiten."""
        self._resolve()
        if not self._resolved:
            return None

        t = P1Telegram()
        t.dsmr_version = "ha_entity"
        t.crc_valid    = True

        hass = self._hass

        def _r(key: str, scale: float = 1.0) -> float:
            eid = self._resolved.get(key)
            if not eid:
                return 0.0
            state = hass.states.get(eid)
            if not state or state.state in ("unavailable", "unknown", ""):
                return 0.0
            try:
                return float(state.state) * scale
            except (ValueError, TypeError):
                return 0.0

        t.power_import_w   = _r("power_import_w", 1000.0)   # kW -> W
        t.power_export_w   = _r("power_export_w", 1000.0)
        t.energy_import_kwh = _r("energy_import_kwh")
        t.energy_export_kwh = _r("energy_export_kwh")
        t.gas_m3            = _r("gas_m3")
        t.gas_kwh           = round(t.gas_m3 * 9.769, 3)
        t.timestamp         = time.time()
        return t


# ── MQTT P1 reader ────────────────────────────────────────────────────────────

class MQTTP1Reader:
    """
    Ontvangt P1-telegrams via MQTT.
    Compatibel met: SLIMMELEZER v2, esp-p1reader, P1ib, DSMR-logger v5.

    Topic-formaat (autodetect):
      - Raw telegram als payload (meest voorkomend)
      - JSON payload met veld 'telegram' of 'raw'
    """

    def __init__(self, hass, topic: str) -> None:
        self._hass    = hass
        self._topic   = topic
        self._latest: Optional[P1Telegram] = None
        self._unsub:  Optional[Callable] = None

    @property
    def latest(self) -> Optional[P1Telegram]:
        return self._latest

    @property
    def available(self) -> bool:
        return self._latest is not None

    async def async_start(self) -> None:
        try:
            from homeassistant.components import mqtt
            self._unsub = await mqtt.async_subscribe(
                self._hass, self._topic, self._on_message
            )
            _LOGGER.info("P1 MQTT reader gestart op topic: %s", self._topic)
        except Exception as err:
            _LOGGER.warning("P1 MQTT reader kon niet starten: %s", err)

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _on_message(self, msg) -> None:
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        # JSON payload?
        if payload.strip().startswith("{"):
            import json
            try:
                data = json.loads(payload)
                payload = data.get("telegram") or data.get("raw") or payload
            except Exception:
                pass

        # Rauw telegram?
        if "/" in payload and "!" in payload:
            try:
                t = parse_telegram(payload)
                if t.crc_valid:
                    self._latest = t
                    # v4.6.512: parent callback voor realtime updates
                    if getattr(self, '_on_telegram_callback', None):
                        try:
                            self._on_telegram_callback(t)
                        except Exception:
                            pass
                else:
                    _LOGGER.debug("P1 MQTT: CRC ongeldig, telegram genegeerd")
            except Exception as ex:
                _LOGGER.debug("P1 MQTT parse fout: %s", ex)


# ── Hoofd P1Reader klasse ─────────────────────────────────────────────────────

class P1Reader:
    """
    Universele async P1 telegram reader met automatische verbindingsketen.

    Prioriteitsvolgorde:
      1. Direct TCP (HomeWizard, SLIMMELEZER, P1ib)
      2. Serieel USB
      3. MQTT
      4. HA entity fallback (bestaande DSMR/HomeWizard integratie)

    Gebruikers hoeven NIETS te configureren als DSMR al geinstalleerd is.
    """

    _PHASE_SPIKE_W = 20_000.0
    _TOTAL_SPIKE_W = 60_000.0

    def __init__(self, config: dict, hass=None) -> None:
        self._host:    Optional[str] = config.get(CONF_P1_HOST)
        self._port:    int           = int(config.get(CONF_P1_PORT, DEFAULT_P1_PORT))
        self._serial:  Optional[str] = config.get(CONF_P1_SERIAL_PORT)
        self._mqtt_topic: Optional[str] = config.get("p1_mqtt_topic")
        self._hass    = hass

        self._latest: Optional[P1Telegram] = None
        self._running = False
        self._task:   Optional[asyncio.Task] = None
        self._spike_count = 0

        # v4.6.512: callback die aangeroepen wordt bij elk nieuw geldig telegram
        # Hiermee kan de coordinator direct updaten i.p.v. wachten op 10s poll
        self._on_telegram_callback = None

        # v4.6.522: interval-meting — bijhouden van timestamps per geldig telegram
        # Gebruikt voor auto-detectie van DSMR4 vs DSMR5 in coordinator
        import time as _time_mod
        self._telegram_timestamps: list = []   # laatste N timestamps (unix)
        self._telegram_ts_maxlen  = 20         # bewaar max 20 samples
        self._telegram_ts_module  = _time_mod  # bewaard voor gebruik in methoden

        # Sub-readers
        self._mqtt_reader:     Optional[MQTTP1Reader] = None
        self._fallback_reader: Optional[HAEntityFallbackReader] = None

    def set_telegram_callback(self, callback) -> None:
        """Registreer een callback voor elk nieuw geldig telegram (realtime updates)."""
        self._on_telegram_callback = callback

    @property
    def latest(self) -> Optional[P1Telegram]:
        """Geef meest recente telegram, via welke bron dan ook."""
        if self._latest:
            return self._latest
        if self._mqtt_reader and self._mqtt_reader.available:
            return self._mqtt_reader.latest
        if self._fallback_reader:
            return self._fallback_reader.read()
        return None

    @property
    def available(self) -> bool:
        return self.latest is not None

    @property
    def spike_count(self) -> int:
        return self._spike_count

    @property
    def measured_interval_s(self) -> Optional[float]:
        """Gemiddeld gemeten interval tussen telegrams (seconden), of None als te weinig data.

        Betrouwbaar na DSMR_AUTODETECT_MIN_SAMPLES geldige telegrams.
        """
        ts = self._telegram_timestamps
        if len(ts) < 2:
            return None
        deltas = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
        return round(sum(deltas) / len(deltas), 2)

    @property
    def telegram_sample_count(self) -> int:
        """Aantal gemeten telegram-intervallen (= timestamps - 1)."""
        return max(0, len(self._telegram_timestamps) - 1)

    def _record_telegram_time(self) -> None:
        """Sla huidige timestamp op voor interval-meting."""
        now = self._telegram_ts_module.time()
        self._telegram_timestamps.append(now)
        if len(self._telegram_timestamps) > self._telegram_ts_maxlen:
            self._telegram_timestamps.pop(0)

    @property
    def source(self) -> str:
        """Geef aan via welke bron de data binnenkomt."""
        if self._latest:
            return "tcp" if self._host else "serial"
        if self._mqtt_reader and self._mqtt_reader.available:
            return "mqtt"
        if self._fallback_reader:
            t = self._fallback_reader.read()
            return "ha_entity" if t else "none"
        return "none"

    def _accept_telegram(self, t: P1Telegram) -> bool:
        """Spike-filter + CRC check."""
        if not t.crc_valid:
            _LOGGER.debug("P1Reader: CRC ongeldig -- telegram genegeerd")
            self._spike_count += 1
            return False
        if t.power_import_w > self._TOTAL_SPIKE_W:
            _LOGGER.warning("P1Reader: spike import=%.0fW (max %.0f)", t.power_import_w, self._TOTAL_SPIKE_W)
            self._spike_count += 1
            return False
        if t.power_export_w > self._TOTAL_SPIKE_W:
            _LOGGER.warning("P1Reader: spike export=%.0fW (max %.0f)", t.power_export_w, self._TOTAL_SPIKE_W)
            self._spike_count += 1
            return False
        for ph, pw in (("L1", t.power_l1_w), ("L2", t.power_l2_w), ("L3", t.power_l3_w)):
            if pw > self._PHASE_SPIKE_W:
                _LOGGER.warning("P1Reader: spike fase %s=%.0fW", ph, pw)
                self._spike_count += 1
                return False
        if self._latest:
            prev = abs(self._latest.net_power_w)
            cur  = abs(t.net_power_w)
            if prev > 200 and cur > prev * 10:
                _LOGGER.warning("P1Reader: spike sprong %.0fW->%.0fW", prev, cur)
                self._spike_count += 1
                return False
        self._record_telegram_time()
        return True

    async def async_start(self) -> None:
        self._running = True

        # MQTT reader starten (parallel aan TCP/serial)
        if self._mqtt_topic and self._hass:
            self._mqtt_reader = MQTTP1Reader(self._hass, self._mqtt_topic)
            # v4.6.512: geef callback door aan MQTT sub-reader
            if self._on_telegram_callback:
                self._mqtt_reader._on_telegram_callback = self._on_telegram_callback
            await self._mqtt_reader.async_start()

        # HA entity fallback altijd beschikbaar als hass meegegeven
        if self._hass:
            self._fallback_reader = HAEntityFallbackReader(self._hass)

        if self._host:
            self._task = asyncio.ensure_future(self._read_tcp())
        elif self._serial:
            self._task = asyncio.ensure_future(self._read_serial())
        elif not self._mqtt_topic:
            _LOGGER.info(
                "P1Reader: geen directe verbinding geconfigureerd -- "
                "gebruik HA entity fallback of MQTT als beschikbaar"
            )

    async def async_stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        if self._mqtt_reader:
            await self._mqtt_reader.async_stop()

    async def _read_tcp(self) -> None:
        _LOGGER.info("P1Reader TCP: verbinden met %s:%d", self._host, self._port)
        while self._running:
            try:
                reader, _ = await asyncio.open_connection(self._host, self._port)
                _LOGGER.info("P1Reader TCP: verbonden met %s:%d", self._host, self._port)
                buffer = ""
                async for line in reader:
                    if not self._running:
                        break
                    text = line.decode("ascii", errors="replace")
                    buffer += text
                    if text.startswith("!"):
                        try:
                            parsed = parse_telegram(buffer)
                            if self._accept_telegram(parsed):
                                self._latest = parsed
                                # v4.6.512: trigger coordinator direct (realtime)
                                if self._on_telegram_callback:
                                    try:
                                        self._on_telegram_callback(parsed)
                                    except Exception:
                                        pass
                        except Exception as ex:
                            _LOGGER.debug("P1Reader TCP parse fout: %s", ex)
                        buffer = ""
            except Exception as err:
                _LOGGER.warning("P1Reader TCP fout: %s -- opnieuw proberen in 30s", err)
                await asyncio.sleep(30)

    async def _read_serial(self) -> None:
        try:
            import serial_asyncio  # type: ignore
        except ImportError:
            _LOGGER.error(
                "P1Reader serieel: pyserial-asyncio niet beschikbaar. "
                "Voeg 'pyserial-asyncio>=0.6' toe aan requirements."
            )
            return

        # Baudrate op basis van DSMR-versie (2.2 = 9600, rest = 115200)
        baud = 9600 if getattr(self, "_dsmr_version", "5") == "2.2" else 115200

        while self._running:
            try:
                reader, _ = await serial_asyncio.open_serial_connection(
                    url=self._serial, baudrate=baud
                )
                _LOGGER.info("P1Reader serieel: verbonden op %s (baud=%d)", self._serial, baud)
                buffer = ""
                async for line in reader:
                    if not self._running:
                        break
                    text = line.decode("ascii", errors="replace")
                    buffer += text
                    if text.startswith("!"):
                        try:
                            parsed = parse_telegram(buffer)
                            # Auto-detecteer DSMR2.2 aan baudrate
                            if parsed.dsmr_version == "2.2" and baud != 9600:
                                _LOGGER.info("P1Reader: DSMR 2.2 gedetecteerd -- herverbinden op 9600 baud")
                                break
                            if self._accept_telegram(parsed):
                                self._latest = parsed
                                # v4.6.512: trigger coordinator direct (realtime)
                                if self._on_telegram_callback:
                                    try:
                                        self._on_telegram_callback(parsed)
                                    except Exception:
                                        pass
                        except Exception as ex:
                            _LOGGER.debug("P1Reader serieel parse fout: %s", ex)
                        buffer = ""
            except Exception as err:
                _LOGGER.warning("P1Reader serieel fout: %s -- opnieuw proberen in 30s", err)
                await asyncio.sleep(30)
