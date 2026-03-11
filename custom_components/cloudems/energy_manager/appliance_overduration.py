# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Appliance Overduration Guard — v1.0.0

Detecteert apparaten die ongewoon lang aanstaan en stuurt gerichte
waarschuwingen, voordat dit brandgevaar of energieverspilling oplevert.

Probleemscenario:
    Iemand zet een frietpan aan in een tuinhuisje en vergeet hem. Na een
    week loopt het risico op brand en zijn er onnodige kosten gemaakt.
    CloudEMS moet dit opvangen met duidelijke, gelaagde waarschuwingen.

Aanpak — twee detectielagen:
  1. Typegebaseerde veiligheidslimieten
       Gevaarlijke apparaattypen (oven, frietpan, strijkijzer, kachel, …)
       krijgen harde maximale aan-tijden. Ongeacht de leerhistorie wordt er
       een CRITICAL-alert gestuurd als een apparaat langer aanstaat dan de
       absolute veiligheidslimiet.

  2. Leergebaseerde afwijkingsdetectie
       Als NILM genoeg sessies heeft gezien (>= MIN_SESSIONS_FOR_LEARNING),
       geldt als drempel: avg_duration * WARN_FACTOR (warning) en
       avg_duration * CRIT_FACTOR (critical). Dit pikt ook af-wijkingen op
       voor apparaten zonder type-limiet (bijv. een computer die altijd 4u
       aanstaat maar nu al 20u loopt).

  3. Naamgebaseerde override
       Trefwoorden in apparaatnaam (user_name of NILM-name) overschrijven
       het detectie-type. Zo wordt een stopcontact dat "frietpan" heet
       behandeld als oven-type met bijbehorende limieten.

Prioriteitslogica:
    - WARN_FACTOR bereikt  → priority = "warning"
    - CRIT_FACTOR of absolute type-limiet bereikt → priority = "critical"
    - Alert verdwijnt automatisch zodra apparaat UIT gaat

Integratie:
    Aanroepen vanuit coordinator (na nilm_devices_enriched is bepaald):

        from .energy_manager.appliance_overduration import ApplianceOverdurationGuard
        _overduration = ApplianceOverdurationGuard()

        # In de update-loop:
        overdur_alerts = _overduration.update(nilm_devices_enriched)
        # overdur_alerts is een alerts_dict voor NotificationEngine.ingest()

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

_LOGGER = logging.getLogger(__name__)

# ── Leerdrempels ──────────────────────────────────────────────────────────────
MIN_SESSIONS_FOR_LEARNING = 5    # Minimale sessies voor leergebaseerde detectie
WARN_FACTOR               = 2.0  # Waarschuwing bij 2× gemiddelde duur
CRIT_FACTOR               = 4.0  # Kritiek bij 4× gemiddelde duur
MIN_LEARNED_WARN_MIN      = 15   # Leergebaseerde waarschuwing nooit onder 15 min
                                  # (voorkomt spam bij korte apparaten)

# ── Typegebaseerde absolute veiligheidslimieten (minuten) ─────────────────────
# Format: device_type → (warn_min, critical_min)
# warn_min   = na hoeveel minuten een WAARSCHUWING wordt gestuurd
# critical_min = na hoeveel minuten een KRITIEKE alert wordt gestuurd
#
# Stelregel: critical = realistisch maximum normaal gebruik + ruime marge.
# CloudEMS mag NIET vals-positief alerteren bij normaal langdurig gebruik
# (bijv. een slowcooker of elektrische deken).
TYPE_LIMITS: Dict[str, tuple[int, int]] = {
    # ── Brandgevaarlijke keukenapparaten ─────────────────────────────────────
    "oven":            (90,   300),   # 1.5h warn / 5h crit  (braadstuk kan lang duren)
    "kettle":          (12,    25),   # 12 min warn / 25 min crit (ketel = nooit langer)
    "microwave":       (45,   120),   # 45 min warn / 2h crit

    # ── Wasserij ─────────────────────────────────────────────────────────────
    "washing_machine": (180,  360),   # 3h warn / 6h crit
    "dryer":           (180,  360),   # 3h warn / 6h crit (mag niet blijven draaien)
    "dishwasher":      (180,  360),   # 3h warn / 6h crit

    # ── Verwarming ────────────────────────────────────────────────────────────
    "boiler":          (90,   180),   # boilercyclus: 90 min is al lang
    "heat_pump":       (480,  720),   # 8h warn / 12h crit (mag lang lopen, maar niet eindeloos)

    # ── Elektronica ───────────────────────────────────────────────────────────
    "entertainment":   (480,  720),   # 8h / 12h
    "computer":        (720, 1080),   # 12h / 18h

    # ── Verlichting ───────────────────────────────────────────────────────────
    # "light" is doelbewust niet opgenomen: verlichting mag lang aan blijven.

    # ── EV ────────────────────────────────────────────────────────────────────
    # "ev_charger" is doelbewust niet opgenomen: laden duurt van nature lang.
}

# ── Naamgebaseerde keyword overrides ─────────────────────────────────────────
# Trefwoorden in lowercase → overschrijf type-limieten.
# Wordt gecontroleerd in user_name + NILM name.
# Format: keyword → (warn_min, critical_min, friendly_type_label)
KEYWORD_OVERRIDES: Dict[str, tuple[int, int, str]] = {
    # Keuken
    "friet":       (45, 90,  "Frietpan / -ketel"),
    "fryer":       (45, 90,  "Friteuse / Airfryer"),
    "airfryer":    (60, 120, "Airfryer"),
    "air fryer":   (60, 120, "Airfryer"),
    "frituur":     (45, 90,  "Friteuse"),
    "frituurpan":  (45, 90,  "Friteuse"),
    "wok":         (60, 120, "Wok"),
    "panini":      (30, 60,  "Paninikast / Grill"),
    "grill":       (60, 120, "Tafelgrill"),
    "raclette":    (90, 180, "Raclette"),
    "fondue":      (120, 240,"Fondue"),
    "broodroost":  (15, 30,  "Broodrooster"),
    "toaster":     (15, 30,  "Broodrooster"),
    "waffle":      (20, 40,  "Wafelijzer"),
    "wafel":       (20, 40,  "Wafelijzer"),
    "koffiez":     (60, 180, "Koffiezetapparaat"),
    "espresso":    (120,240, "Espressomachine"),
    "waterkoker":  (12, 25,  "Waterkoker"),

    # Strijken / kleding
    "strijkijzer": (45, 90,  "Strijkijzer"),
    "strijk":      (60, 120, "Strijksysteem"),
    "iron":        (45, 90,  "Strijkijzer"),
    "ironing":     (45, 90,  "Strijkijzer"),
    "steamer":     (30, 60,  "Stoomstrijker"),
    "garment":     (30, 60,  "Kledingstomer"),

    # Verwarming / kachel
    "kachel":      (480, 720,"Elektrische kachel"),
    "heater":      (480, 720,"Verwarmingstoestel"),
    "ventilatork": (480, 720,"Ventilatorkachel"),
    "convector":   (480, 720,"Convectorheater"),
    "badkamerkach":(240, 480,"Badkamerkachel"),
    "terrasverw":  (240, 480,"Terrasverwarmer"),
    "heat gun":    (20, 40,  "Heteluchtpistool"),

    # Gereedschap / workshop
    "soldeer":     (30, 60,  "Soldeerbout"),
    "soldering":   (30, 60,  "Soldeerbout"),
    "heat press":  (30, 60,  "Hittepers"),
    "lasapparaat": (120,240, "Lasapparaat"),

    # Overig brandrisico
    "sauna":       (120,240, "Sauna"),
    "steam room":  (120,240, "Stoomcabine"),
    "infrarood":   (180,360, "Infraroodcabine"),
    "smoker":      (360,720, "BBQ Smoker"),
    "bbq":         (240,480, "Elektrische BBQ"),
}

# ── Minimale AAN-tijd voor overduration alert (seconden) ─────────────────────
# Apparaten die minder dan ALERT_GRACE_S aanstaan krijgen geen alert.
# Voorkomt alerts meteen na het inschakelen.
ALERT_GRACE_S = 60  # 1 minuut — genoeg tijd voor normale opstartfase


def _format_duration(seconds: float) -> str:
    """Zet seconden om naar leesbare tekst: '2 uur 15 min' of '45 min'."""
    total_min = int(seconds / 60)
    if total_min < 60:
        return f"{total_min} min"
    hours = total_min // 60
    mins  = total_min % 60
    if mins == 0:
        return f"{hours} uur"
    return f"{hours} uur {mins} min"


class ApplianceOverdurationGuard:
    """
    Bewaakt actieve NILM-apparaten op te lange aan-tijden.

    Gebruik:
        guard = ApplianceOverdurationGuard()
        # Elke coordinator-cyclus:
        alerts = guard.update(nilm_devices_enriched)
        notification_engine.ingest(alerts)
    """

    def __init__(self) -> None:
        # Bijhouden: device_id → tijdstip waarop eerste overduration alert actief werd
        self._alerted_since: Dict[str, float] = {}

    def update(self, nilm_devices: List[dict]) -> Dict[str, dict]:
        """
        Verwerk de huidige NILM-apparatenlijst en geef een alerts_dict terug.

        Parameters
        ----------
        nilm_devices : list[dict]
            Verrijkte apparaatlijst zoals geproduceerd door coordinator
            (output van get_devices_for_ha() + enrichment).

        Returns
        -------
        dict[str, dict]
            alerts_dict compatibel met NotificationEngine.ingest().
        """
        alerts: Dict[str, dict] = {}

        for dev in nilm_devices:
            device_id   = dev.get("device_id", "")
            is_on       = dev.get("is_on", False)
            on_duration = float(dev.get("current_on_duration_s") or 0.0)
            user_name   = (dev.get("user_name") or "").strip()
            nilm_name   = (dev.get("name")      or "").strip()
            device_type = dev.get("user_type")  or dev.get("device_type") or ""
            avg_min     = float(dev.get("avg_duration_min") or 0.0)
            sess_count  = int(dev.get("session_count") or dev.get("on_events") or 0)
            current_w   = float(dev.get("current_power") or 0.0)

            display_name = user_name or nilm_name or device_id
            alert_key    = f"overduration:{device_id}"

            if not is_on or on_duration < ALERT_GRACE_S:
                # Apparaat is UIT of nog in grace-periode → zet alert inactief
                if alert_key in alerts:
                    alerts[alert_key]["active"] = False
                elif device_id in self._alerted_since:
                    # Stuur expliciet inactief door zodat NotificationEngine hem resolvet
                    alerts[alert_key] = {
                        "priority": "info",
                        "category": "appliance",
                        "title":    f"Apparaat uitgeschakeld: {display_name}",
                        "message":  "",
                        "active":   False,
                    }
                    del self._alerted_since[device_id]
                continue

            # ── Bepaal drempelwaarden ─────────────────────────────────────────
            warn_min: int | None  = None
            crit_min: int | None  = None
            type_label: str       = device_type

            # 1. Naamgebaseerde override (hoogste prioriteit)
            search_str = (user_name + " " + nilm_name).lower()
            for keyword, (kw_warn, kw_crit, kw_label) in KEYWORD_OVERRIDES.items():
                if keyword in search_str:
                    warn_min   = kw_warn
                    crit_min   = kw_crit
                    type_label = kw_label
                    break

            # 2. Typegebaseerde limiet (als geen keyword match)
            if warn_min is None and device_type in TYPE_LIMITS:
                warn_min, crit_min = TYPE_LIMITS[device_type]

            # 3. Leergebaseerde drempel (aanvullend of primair als geen type-limiet)
            learned_warn_min: float | None = None
            learned_crit_min: float | None = None
            if avg_min > 0 and sess_count >= MIN_SESSIONS_FOR_LEARNING:
                lw = avg_min * WARN_FACTOR
                lc = avg_min * CRIT_FACTOR
                if lw >= MIN_LEARNED_WARN_MIN:
                    learned_warn_min = lw
                    learned_crit_min = lc

            # Gebruik de strengste (laagste) drempel van type + leren
            final_warn_min: float | None = None
            final_crit_min: float | None = None

            if warn_min is not None:
                final_warn_min = float(warn_min)
                final_crit_min = float(crit_min) if crit_min else float(warn_min) * 2

            if learned_warn_min is not None:
                if final_warn_min is None:
                    final_warn_min = learned_warn_min
                    final_crit_min = learned_crit_min
                else:
                    # Neem de laagste drempel (meest conservatief)
                    final_warn_min = min(final_warn_min, learned_warn_min)
                    final_crit_min = min(final_crit_min, learned_crit_min)

            if final_warn_min is None:
                # Geen bekende limieten → geen overduration alert voor dit apparaat
                continue

            # ── Huidige status vergelijken met drempels ───────────────────────
            on_min = on_duration / 60.0

            if on_min < final_warn_min:
                # Nog binnen normale grenzen
                if device_id in self._alerted_since:
                    # Was eerder in alarm → stuur inactief
                    alerts[alert_key] = {
                        "priority": "info",
                        "category": "appliance",
                        "title":    f"Overduration opgelost: {display_name}",
                        "message":  "",
                        "active":   False,
                    }
                    del self._alerted_since[device_id]
                continue

            # Drempel bereikt — bepaal ernst
            is_critical = (on_min >= final_crit_min)
            priority    = "critical" if is_critical else "warning"

            # Track eerste keer dat we alarmeren
            if device_id not in self._alerted_since:
                self._alerted_since[device_id] = time.time()
                _LOGGER.warning(
                    "ApplianceOverdurationGuard: %s [%s] staat al %s AAN "
                    "(drempel: warn=%d min / crit=%d min) — %s alert",
                    display_name, device_type,
                    _format_duration(on_duration),
                    int(final_warn_min), int(final_crit_min),
                    priority.upper(),
                )

            # ── Bericht opmaken ───────────────────────────────────────────────
            on_str   = _format_duration(on_duration)
            power_str = f" ({current_w:.0f}W)" if current_w > 10 else ""
            avg_str  = (
                f" Normaal staat dit apparaat ~{avg_min:.0f} min aan."
                if avg_min > 0 and sess_count >= MIN_SESSIONS_FOR_LEARNING
                else ""
            )

            if is_critical:
                title = f"🚨 {display_name} staat al {on_str} aan!"
                message = (
                    f"{display_name}{power_str} staat al {on_str} aan — "
                    f"dit is {on_min / final_warn_min:.1f}× langer dan normaal verwacht "
                    f"voor een {type_label}.{avg_str} "
                    f"Controleer of het apparaat bewust aanstaat. "
                    f"Bij twijfel: schakel het nu direct UIT."
                )
            else:
                title = f"⚠️ {display_name} staat ongewoon lang aan ({on_str})"
                message = (
                    f"{display_name}{power_str} staat al {on_str} aan. "
                    f"Verwacht voor een {type_label} is maximaal "
                    f"~{int(final_warn_min)} min.{avg_str} "
                    f"Is dit opzettelijk? Geen actie nodig als het klopt. "
                    f"Vergeten? Schakel het apparaat dan nu uit."
                )

            alerts[alert_key] = {
                "priority": priority,
                "category": "appliance",
                "title":    title,
                "message":  message,
                "active":   True,
            }

        return alerts


def build_overduration_alerts(nilm_devices: list[dict]) -> dict[str, dict]:
    """
    Module-level helper: maak een tijdelijke guard-instantie en geef alerts terug.
    Gebruik dit ALLEEN als je geen persistente guard-instantie wilt bijhouden
    (bijv. in unit tests). Gebruik in productie de klasse-instantie op coordinator.
    """
    guard = ApplianceOverdurationGuard()
    return guard.update(nilm_devices)
