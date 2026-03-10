# -*- coding: utf-8 -*-
"""
CloudEMS Appliance Over-On Guard — v1.0.0

Detecteert apparaten die significant langer aan staan dan normaal, of die een
onacceptabel lange "aan"-tijd bereiken voor gevaarlijke/kritieke appliances
(friteuse, strijkijzer, grill, etc.).

Twee detectielagen
──────────────────
1. Geleerd maximum  — per apparaat: als de huidige aan-tijd de gemiddelde
   sessieduur met een instelbare factor overschrijdt, volgt een waarschuwing.
   Dit is adaptief: een oven die normaal 3 uur brandt, trigt pas veel later.

2. Hard maximum    — per apparaattype een absolute bovengrens (zie
   HARD_MAX_ON_SECONDS).  Gevaarlijke apparaten als een friteuse of strijkijzer
   worden na deze limiet altijd als CRITICAL gemeld, ongeacht de leergeschiedenis.

Prioriteit-escalatie:
  0h → geleerd maximum   : WARNING  ("al langer aan dan normaal")
  + 1 herinnering-interval: WARNING  (herhaling)
  Hard maximum bereikt    : CRITICAL ("gevaarlijk lang aan — controleer direct")

Integratie
──────────
Aanroepen vanuit notification_engine.build_alerts_from_coordinator_data():

    from .appliance_overon_guard import build_overon_alerts
    alerts.update(build_overon_alerts(nilm_devices))

Dat is de enige aanpassing buiten dit bestand.

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ── Hard maximale aan-tijden per apparaattype (seconden) ────────────────────
# Ongeacht de leergeschiedenis: bij overschrijding → CRITICAL.
# Apparaten zonder entry hier worden alleen bewaakt via de geleerde drempel.
HARD_MAX_ON_SECONDS: dict[str, int] = {
    # ⚠️  Brandgevaarlijk / hittegenererende apparaten
    "deep_fryer":       3600,       #  1 h  — friteuse
    "fryer":            3600,
    "air_fryer":        3600,       #  1 h  — airfryer
    "iron":             1800,       # 30 min — strijkijzer
    "grill":            5400,       #  1.5 h — contactgrill / tafelgrill
    "bbq":              7200,       #  2 h
    "heat_gun":         1800,
    "soldering_iron":   1800,
    "candle_warmer":    14400,      #  4 h
    "space_heater":     28800,      #  8 h  — elektrische kachel
    "fan_heater":       28800,

    # 🔧  Stroomverslindende apparaten die je normaal niet uren vergeet
    "kettle":           600,        # 10 min
    "coffee_maker":     5400,       #  1.5 h
    "toaster":          600,        # 10 min
    "microwave":        3600,       #  1 h

    # 🏠  Apparaten die je normaal bewust in/uitschakelt
    "oven":             21600,      #  6 h  (5 h geleerd max + veiligheidsmarge)
    "steamer":          7200,       #  2 h
    "slow_cooker":      43200,      # 12 h  — bewust lang, maar 12 h is genoeg
    "bread_maker":      10800,      #  3 h

    # 🧰  Workshop / garage
    "power_tool":       7200,       #  2 h  — cirkelzaag, boormachine
    "compressor":       7200,
    "welder":           3600,

    # 🚿  Badkamer
    "towel_rail":       28800,      #  8 h
    "hair_straightener": 1800,      # 30 min — stijltang
    "curling_iron":     1800,

    # 🌡️  Medisch / veiligheidsgevaarlijk
    "heating_pad":      7200,       #  2 h
    "electric_blanket": 14400,      #  4 h
}

# ── Herhaling-interval voor WARNING-meldingen (seconden) ────────────────────
# Na de eerste waarschuwing: elke REMINDER_INTERVAL een herinnering.
# Bij CRITICAL: gebruik cooldown van de NotificationEngine (6 h).
REMINDER_INTERVAL_S = 3600  # 1 uur

# ── Minimale sessiehistorie voor geleerd maximum ─────────────────────────────
MIN_SESSIONS_FOR_LEARNED_MAX = 5

# ── Factor waarboven de geleerde gemiddelde duur een warning geeft ───────────
LEARNED_MAX_FACTOR = 2.5   # 2.5× gemiddelde duur → warning


def _format_duration(seconds: float) -> str:
    """Mensvriendelijke tijdsduur: '2u 15m' of '45 minuten'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0 and m > 0:
        return f"{h}u {m}m"
    if h > 0:
        return f"{h} uur"
    return f"{m} minuten"


def build_overon_alerts(nilm_devices: list[dict[str, Any]]) -> dict[str, dict]:
    """
    Genereer 'vergeten-aan' alerts voor alle NILM-devices die momenteel aan
    staan en de maximale aan-tijd overschrijden.

    Parameters
    ----------
    nilm_devices : list[dict]
        Zoals teruggegeven door NILMDetector.get_devices_for_ha() — na de
        toevoeging van ``on_since_ts`` in detector.py v2.5.

    Returns
    -------
    dict[str, dict]
        alerts_dict-formaat dat direct aan NotificationEngine.ingest() kan
        worden meegegeven (of samengevoegd met de bestaande alerts dict).
    """
    alerts: dict[str, dict] = {}
    now = time.time()

    for dev in nilm_devices:
        # Alleen apparaten die momenteel aan zijn
        if not dev.get("is_on"):
            continue

        on_since_ts: float = dev.get("on_since_ts", 0.0)
        if on_since_ts <= 0:
            continue

        on_seconds = now - on_since_ts
        if on_seconds < 60:
            # Net ingeschakeld — nog geen actie nodig
            continue

        dev_id   = dev.get("device_id", "unknown")
        dev_type = (dev.get("user_type") or dev.get("device_type") or "").lower()
        dev_name = dev.get("user_name") or dev.get("name") or dev.get("suggested_name") or "Onbekend apparaat"

        # ── 1. Hard maximum (gevaarlijke apparaten) ──────────────────────────
        hard_max = HARD_MAX_ON_SECONDS.get(dev_type)
        if hard_max and on_seconds >= hard_max:
            on_str   = _format_duration(on_seconds)
            max_str  = _format_duration(hard_max)
            key      = f"overon_critical:{dev_id}"
            alerts[key] = {
                "priority": "critical",
                "category": "appliance",
                "title":    f"⚠️ {dev_name} staat al {on_str} aan",
                "message":  (
                    f"**{dev_name}** staat al **{on_str}** aan "
                    f"(maximum voor dit apparaat: {max_str}). "
                    f"Controleer direct of het apparaat daadwerkelijk in gebruik is. "
                    f"Een {dev_type.replace('_', ' ')} die onbeheerd aan staat kan gevaarlijk zijn."
                ),
                "active": True,
            }
            # Als CRITICAL actief is, WARNING resetten (niet dubbel melden)
            warning_key = f"overon_warning:{dev_id}"
            if warning_key not in alerts:
                alerts[warning_key] = {
                    "priority": "warning",
                    "category": "appliance",
                    "title":    f"{dev_name} staat lang aan",
                    "message":  "",
                    "active":   False,
                }
            continue

        # ── 2. Geleerd maximum ────────────────────────────────────────────────
        energy   = dev.get("energy") or {}
        sessions = energy.get("session_count", 0)
        total_s  = energy.get("total_on_seconds", 0.0)

        if sessions < MIN_SESSIONS_FOR_LEARNED_MAX or total_s <= 0:
            # Nog te weinig sessiehistorie — geen geleerde drempel beschikbaar
            # Geef alleen een warning als er een hard max is en dit 75% bereikt
            if hard_max and on_seconds >= hard_max * 0.75:
                on_str  = _format_duration(on_seconds)
                max_str = _format_duration(hard_max)
                key     = f"overon_warning:{dev_id}"
                alerts[key] = {
                    "priority": "warning",
                    "category": "appliance",
                    "title":    f"{dev_name} staat al {on_str} aan",
                    "message":  (
                        f"{dev_name} staat al {on_str} aan. "
                        f"Voor dit type apparaat geldt een maximum van {max_str}. "
                        f"Controleer of het apparaat bewust in gebruik is."
                    ),
                    "active": True,
                }
            continue

        avg_duration_s = total_s / sessions
        learned_max_s  = avg_duration_s * LEARNED_MAX_FACTOR

        if on_seconds < learned_max_s:
            # Binnen normale grenzen — eventuele eerdere alert opheffen
            for prefix in ("overon_warning:", "overon_critical:"):
                k = f"{prefix}{dev_id}"
                alerts[k] = {
                    "priority": "info",
                    "category": "appliance",
                    "title":    f"{dev_name} aan-tijd normaal",
                    "message":  "",
                    "active":   False,
                }
            continue

        # Geleerd maximum overschreden → WARNING
        on_str  = _format_duration(on_seconds)
        avg_str = _format_duration(avg_duration_s)
        key     = f"overon_warning:{dev_id}"
        alerts[key] = {
            "priority": "warning",
            "category": "appliance",
            "title":    f"{dev_name} staat ongewoon lang aan ({on_str})",
            "message":  (
                f"{dev_name} staat al **{on_str}** aan, terwijl de gemiddelde "
                f"sessieduur {avg_str} is. "
                f"Mogelijk is dit apparaat vergeten uit te zetten. "
                f"Controleer of het bewust in gebruik is."
            ),
            "active": True,
        }

    return alerts
