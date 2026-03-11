# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Apparaat Levensduur Tracker (v2.6).

Telt aan/uit-cycli per NILM-apparaat en schat slijtage op basis van
bekende verwachte levensduur per apparaattype.

Referentiewaarden voor typische levensduur in cycli:
  • Wasmachine:    ~3.000 cycli (15 jaar × 200/jaar)
  • Vaatwasser:    ~5.000 cycli
  • CV-ketel:      ~100.000 start-stops
  • Koelkast:      niet relevant (continu)
  • Droger:        ~2.500 cycli
  • Magnetron:     ~10.000 cycli
  • Oven:          ~5.000 cycli
  • EV-lader:      ~1.500 laadcycli (accu)
  • Boiler:        ~50.000 cycli
"""
from __future__ import annotations
import logging

_LOGGER = logging.getLogger(__name__)

# Verwachte levensduur in cycli per apparaattype
EXPECTED_CYCLES: dict[str, int] = {
    "washer":           3_000,
    "washing_machine":  3_000,
    "dryer":            2_500,
    "dishwasher":       5_000,
    "oven":             5_000,
    "microwave":        10_000,
    "boiler":           50_000,
    "heat_pump":        80_000,
    "cv_ketel":         100_000,
    "heater":           20_000,
    "ev_charger":       1_500,
    "freezer":          15_000,
    "vacuum":           3_000,
    "coffee_machine":   10_000,
}

# Slijtage-waarschuwingsdrempels (% van verwachte levensduur)
WARN_AT_PCT  = 75
ALERT_AT_PCT = 90


def get_expected_cycles(device_type: str) -> int | None:
    """Geef verwacht aantal cycli voor dit apparaattype, of None als onbekend."""
    return EXPECTED_CYCLES.get(device_type.lower().replace(" ", "_"))


def calculate_wear(cycles: int, device_type: str) -> dict:
    """Bereken slijtage op basis van cycli en apparaattype.

    Returns:
        wear_pct:         0-100 (of >100 = overschreden)
        expected_cycles:  verwachte levensduur of None
        status:           'ok' | 'warn' | 'alert' | 'unknown'
        cycles_remaining: geschatte resterende cycli of None
    """
    expected = get_expected_cycles(device_type)
    if not expected:
        return {
            "wear_pct": None,
            "expected_cycles": None,
            "status": "unknown",
            "cycles_remaining": None,
        }

    pct = round(cycles / expected * 100, 1)
    remaining = max(0, expected - cycles)

    if pct >= ALERT_AT_PCT:
        status = "alert"
    elif pct >= WARN_AT_PCT:
        status = "warn"
    else:
        status = "ok"

    return {
        "wear_pct":        pct,
        "expected_cycles": expected,
        "status":          status,
        "cycles_remaining": remaining,
    }


def enrich_devices_with_wear(devices: list[dict]) -> list[dict]:
    """Voeg slijtage-informatie toe aan een lijst van NILM device dicts."""
    enriched = []
    for d in devices:
        dtype  = d.get("device_type", "")
        cycles = int(d.get("on_events", 0))
        wear   = calculate_wear(cycles, dtype)
        enriched.append({
            **d,
            "wear_pct":         wear["wear_pct"],
            "expected_cycles":  wear["expected_cycles"],
            "wear_status":      wear["status"],
            "cycles_remaining": wear["cycles_remaining"],
        })
    return enriched
