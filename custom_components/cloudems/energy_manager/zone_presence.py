# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""CloudEMS — Zone Aanwezigheidsbeheer (v3.0).

Vier lagen aanwezigheid, gecombineerd via gewogen confidence-fusie:
  1. Device trackers / person entities  (meerdere bewoners)
  2. BLE / WiFi signaalsterkte          (lokaal, geen cloud)
  3. Kalender-integratie               (Google Calendar / HA Calendar)
  4. Zelf-lerend aanwezigheidspatroon  (leert na 2 weken)

Elke laag geeft een AanwezigheidAdvies met confidence (0-1) terug.
De uiteindelijke status is een gewogen fusie — geen harde prioriteit meer.

Events worden gefired op hass.bus voor energiebeslissingen:
  cloudems_presence_changed  →  {"status": "thuis/weg", "bron": "...", "confidence": 0.9}

Copyright 2025 CloudEMS
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class Aanwezigheid(str, Enum):
    THUIS    = "thuis"
    WEG      = "weg"
    ONBEKEND = "onbekend"


@dataclass
class AanwezigheidAdvies:
    status:  Aanwezigheid
    bron:    str            # "tracker" / "ble_wifi" / "kalender" / "geleerd" / "standaard"
    detail:  str            # mensleesbare toelichting
    confidence: float = 0.5  # 0.0 = onzeker, 1.0 = zeker
    personen_thuis: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# LAAG 1: Device trackers / person entities
# ─────────────────────────────────────────────────────────────────────────────

class PersonPresenceLayer:
    """Volgt meerdere bewoners via person.* of device_tracker.* entities.

    Logica: als MINSTENS ÉÉN persoon thuis is → THUIS.
    Confidence stijgt met het aantal trackers dat eens is.
    """

    def __init__(self, person_entities: list[str]) -> None:
        self._entities = person_entities  # ["person.jan", "person.marie", ...]

    def evaluate(self, hass: "HomeAssistant") -> AanwezigheidAdvies:
        if not self._entities:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "tracker", "Geen trackers geconfigureerd", confidence=0.0)

        thuis = []
        weg   = []
        for eid in self._entities:
            st = hass.states.get(eid)
            if not st:
                continue
            naam = st.attributes.get("friendly_name") or eid.split(".")[-1]
            if st.state in ("home", "thuis", "on", "true"):
                thuis.append(naam)
            elif st.state in ("not_home", "away", "weg", "off", "false"):
                weg.append(naam)

        total = len(thuis) + len(weg)
        if total == 0:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "tracker", "Status onbekend", confidence=0.0)

        if thuis:
            # Confidence: hoger als méér trackers eens zijn
            confidence = min(1.0, 0.7 + 0.1 * len(thuis))
            return AanwezigheidAdvies(
                Aanwezigheid.THUIS, "tracker",
                f"{', '.join(thuis)} thuis",
                confidence=round(confidence, 2),
                personen_thuis=thuis,
            )
        # Iedereen weg
        confidence = min(1.0, 0.7 + 0.1 * len(weg))
        return AanwezigheidAdvies(
            Aanwezigheid.WEG, "tracker",
            f"Niemand thuis ({', '.join(weg)} weg)",
            confidence=round(confidence, 2),
        )


# ─────────────────────────────────────────────────────────────────────────────
# LAAG 2: Kalender-integratie
# ─────────────────────────────────────────────────────────────────────────────

# Keywords in kalender-evenementen die aanwezigheid impliceren
THUIS_KEYWORDS  = {"thuis", "home", "werk thuis", "werken thuis", "wfh",
                   "thuiswerken", "vakantie thuis", "ziek thuis"}
WEG_KEYWORDS    = {"vakantie", "vacation", "holiday", "weg", "away",
                   "reis", "trip", "werk", "work", "kantoor", "office",
                   "school", "sport", "training"}
# Keywords die heating-boost suggereren (feestje, gasten)
BOOST_KEYWORDS  = {"feestje", "party", "gasten", "guests", "bezoek",
                   "verjaardag", "birthday", "diner", "dinner"}


class CalendarPresenceLayer:
    """Leest HA Calendar entities en vertaalt actieve evenementen naar aanwezigheid.

    Werkt met elk HA calendar platform:
      - calendar.google_*     (Google Calendar integratie)
      - calendar.local_*      (HA Local Calendar)
      - calendar.*            (elke calendar entity)

    Evenement-titel matching (hoofdletteronafhankelijk):
      "Vakantie Parijs"  → WEG
      "Thuis werken"     → THUIS
      "Feestje"          → THUIS + hint: boost
    """

    def __init__(self, calendar_entities: list[str]) -> None:
        self._entities = calendar_entities
        self._boost_hint = False

    @property
    def boost_hint(self) -> bool:
        """True als er een feestje/gasten-evenement actief is."""
        return self._boost_hint

    def evaluate(self, hass: "HomeAssistant") -> AanwezigheidAdvies:
        if not self._entities:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "kalender", "Geen kalenders geconfigureerd")

        self._boost_hint = False
        active_events = []

        for eid in self._entities:
            st = hass.states.get(eid)
            if not st or st.state != "on":
                continue
            msg   = (st.attributes.get("message") or
                     st.attributes.get("description") or
                     st.attributes.get("summary") or "").lower()
            start = st.attributes.get("start_time", "")
            end   = st.attributes.get("end_time", "")
            active_events.append((msg, start, end))

            if any(k in msg for k in BOOST_KEYWORDS):
                self._boost_hint = True

        if not active_events:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "kalender", "Geen actieve evenementen", confidence=0.0)

        # Check keywords — WEG heeft hogere prioriteit dan THUIS
        for msg, start, end in active_events:
            if any(k in msg for k in WEG_KEYWORDS) and not any(k in msg for k in THUIS_KEYWORDS):
                return AanwezigheidAdvies(
                    Aanwezigheid.WEG, "kalender",
                    f"Kalender: '{msg}' → weg",
                    confidence=0.85,
                )

        for msg, start, end in active_events:
            if any(k in msg for k in THUIS_KEYWORDS) or self._boost_hint:
                return AanwezigheidAdvies(
                    Aanwezigheid.THUIS, "kalender",
                    f"Kalender: '{msg}' → thuis",
                    confidence=0.75,
                )

        return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "kalender", "Evenement niet herkend", confidence=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# LAAG 2b: Signaalsterkte / lokale aanwezigheid — volledig auto-discovery
# ─────────────────────────────────────────────────────────────────────────────

# Platform-naam → SignaalType mapping (entity registry lookup)
# Sleutels zijn platform-strings zoals HA ze registreert
_PLATFORM_SIGNAAL: dict[str, str] = {
    # BLE triangulatie
    "bermuda":          "distance",   # sensor.*_distance (meters)
    "espresense":       "rssi",       # sensor.espresense_* (dBm, negatief)
    # WiFi / netwerk presence
    "unifi":            "tracker",    # device_tracker.*
    "unifi_network":    "tracker",
    "fritz":            "tracker",    # device_tracker.fritz_*
    "fritzbox":         "tracker",
    "nmap_tracker":     "tracker",
    "ping":             "tracker",    # binary_sensor.ping_*
    "bluetooth_le_tracker": "tracker",
    "bluetooth":        "tracker",
    # Router-gebaseerde trackers
    "asuswrt":          "tracker",
    "netgear":          "tracker",
    "tplink":           "tracker",
    "mikrotik":         "tracker",
    "openwrt":          "tracker",
    "tomato":           "tracker",
    "ddwrt":            "tracker",
    # Mobiele apps / GPS
    "mobile_app":       "tracker",    # device_tracker via HA companion app (GPS)
    "owntracks":        "tracker",
    "gpsd":             "tracker",
    # Zigbee/Z-Wave aanwezigheidssensoren
    "zha":              "binary_pir",
    "zwave_js":         "binary_pir",
    "zigbee2mqtt":      "binary_pir",
    "mqtt":             "binary_pir",
}

# Entity_id of friendly_name patronen → SignaalType
# (Fallback als platform niet in _PLATFORM_SIGNAAL staat)
_NAME_SIGNAAL: list[tuple[str, str]] = [
    # BLE afstand
    ("_distance",    "distance"),
    ("_afstand",     "distance"),
    # BLE home/away binary
    ("_home",        "binary_home"),
    ("bermuda_",     "binary_home"),
    ("espresense_",  "rssi"),
    # RSSI
    ("_rssi",        "rssi"),
    ("_signal",      "rssi"),
    # PIR / bewegingssensoren
    ("motion",       "binary_pir"),
    ("beweging",     "binary_pir"),
    ("presence",     "binary_pir"),
    ("aanwezigheid", "binary_pir"),
    ("occupancy",    "binary_pir"),
    ("bezetting",    "binary_pir"),
    # WiFi/ping
    ("_ping",        "binary_home"),
    ("_connected",   "binary_home"),
]

# device_class → signaaltype (voor binary_sensor)
_DEVICE_CLASS_SIGNAAL: dict[str, str] = {
    "presence":     "binary_home",
    "occupancy":    "binary_pir",
    "motion":       "binary_pir",
    "connectivity": "binary_home",
}

# Welke domeinen zijn relevant voor aanwezigheidsdetectie?
_PRESENCE_DOMAINS = {"device_tracker", "person", "binary_sensor", "sensor"}

# PIR-sensoren tellen minder zwaar mee: het zijn korte activaties, geen blijvende aanwezigheid
_SIGNAAL_WEIGHT: dict[str, float] = {
    "distance":    1.0,   # meest betrouwbaar — continues afstandsmeting
    "binary_home": 1.0,   # home/not_home binary
    "tracker":     0.95,  # device tracker
    "rssi":        0.85,  # RSSI minder stabiel
    "binary_pir":  0.35,  # PIR: beweegt = thuis, maar geen beweging ≠ weg
}

# PIR: houd activaties bij in een rolling window (als PIR actief is geweest
# in de laatste N minuten, telt dat als beperkt bewijs van aanwezigheid)
_PIR_MEMORY_MIN = 20   # minuten


@dataclass
class _DiscoveredSignal:
    """Eén ontdekt aanwezigheidssignaal."""
    entity_id:    str
    signaal_type: str         # distance / rssi / tracker / binary_home / binary_pir
    platform:     str         # HA-platform (bermuda, unifi, mobile_app, ...)
    friendly_name: str
    weight:       float       # effectief gewicht voor fusie
    persoon:      str = ""    # gekoppeld aan persoon/bewoner (optioneel)


class SignalPresenceLayer:
    """Detecteert aanwezigheid via alle beschikbare lokale signalen in HA.

    Volledig zelflerend — geen handmatige configuratie nodig.
    Scant bij setup de entity/device registry en vindt automatisch:
      - person.* / device_tracker.*  (alle trackers)
      - Bermuda BLE afstandssensoren
      - ESPresense RSSI sensoren
      - UniFi / Fritz / Nmap device trackers
      - HA Companion App (mobile_app) trackers
      - PIR / bewegings- / aanwezigheidssensoren
      - Elke binary_sensor met device_class presence/occupancy/connectivity

    Aanroep: eerst async_setup(hass) één keer, dan evaluate(hass) elke cyclus.
    """

    def __init__(self, manual_overrides: list[dict] | None = None) -> None:
        """
        manual_overrides: optioneel lijst van extra entiteiten die niet
        auto-discoverd worden. Zelfde dict-formaat als _DiscoveredSignal.
        Normaal leeg laten — alleen voor edge cases.
        """
        self._signals:    list[_DiscoveredSignal] = []
        self._overrides:  list[dict] = manual_overrides or []
        self._pir_last_on: dict[str, float] = {}   # entity_id → laatste activatie timestamp
        self._setup_done: bool = False
        # v4.5.6: zelflerend drempel per afstandssensor
        self._dist_samples:     dict[str, dict] = {}   # eid → {home:[float], away:[float]}
        self._dist_ground_truth: dict[str, bool] = {}  # eid → bool (gevoed door tracker-verdict)

    async def async_setup(self, hass: "HomeAssistant") -> None:
        """Scan de HA registry en bouw de signaallijst op."""
        from homeassistant.helpers import entity_registry as er, device_registry as dr

        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        found: list[_DiscoveredSignal] = []

        # ── Stap 1: alle person.* entiteiten ──────────────────────────────────
        for state in hass.states.async_all("person"):
            found.append(_DiscoveredSignal(
                entity_id=state.entity_id,
                signaal_type="tracker",
                platform="person",
                friendly_name=state.attributes.get("friendly_name", state.entity_id),
                weight=_SIGNAAL_WEIGHT["tracker"],
                persoon=state.attributes.get("friendly_name", state.entity_id.split(".")[-1]),
            ))

        # ── Stap 2: device_tracker.* via entity registry ───────────────────────
        for state in hass.states.async_all("device_tracker"):
            eid     = state.entity_id
            entry   = ent_reg.async_get(eid)
            platform = entry.platform if entry else ""
            stype   = _PLATFORM_SIGNAAL.get(platform, "")

            if not stype:
                # Probeer naam-heuristiek
                stype = self._stype_from_name(eid, state)
            if not stype:
                stype = "tracker"   # alle device_trackers tellen

            persoon = self._persoon_van_tracker(eid, state, hass)
            found.append(_DiscoveredSignal(
                entity_id=eid,
                signaal_type=stype,
                platform=platform,
                friendly_name=state.attributes.get("friendly_name", eid),
                weight=_SIGNAAL_WEIGHT.get(stype, 0.7),
                persoon=persoon,
            ))

        # ── Stap 3: binary_sensor.* met relevante device_class ────────────────
        for state in hass.states.async_all("binary_sensor"):
            eid   = state.entity_id
            dc    = state.attributes.get("device_class", "")
            entry = ent_reg.async_get(eid)
            platform = entry.platform if entry else ""

            stype = _DEVICE_CLASS_SIGNAAL.get(dc, "")
            if not stype:
                stype = _PLATFORM_SIGNAAL.get(platform, "")
            if not stype:
                stype = self._stype_from_name(eid, state)
            if not stype:
                continue   # niet relevant

            found.append(_DiscoveredSignal(
                entity_id=eid,
                signaal_type=stype,
                platform=platform,
                friendly_name=state.attributes.get("friendly_name", eid),
                weight=_SIGNAAL_WEIGHT.get(stype, 0.5),
            ))

        # ── Stap 4: sensor.* — BLE afstand / RSSI ─────────────────────────────
        for state in hass.states.async_all("sensor"):
            eid      = state.entity_id
            entry    = ent_reg.async_get(eid)
            platform = entry.platform if entry else ""

            stype = _PLATFORM_SIGNAAL.get(platform, "")
            if not stype:
                stype = self._stype_from_name(eid, state)
            if stype not in ("distance", "rssi"):
                continue   # sensoren alleen voor BLE/afstand/RSSI

            found.append(_DiscoveredSignal(
                entity_id=eid,
                signaal_type=stype,
                platform=platform,
                friendly_name=state.attributes.get("friendly_name", eid),
                weight=_SIGNAAL_WEIGHT.get(stype, 0.8),
            ))

        # ── Stap 5: handmatige overrides toevoegen ────────────────────────────
        for ov in self._overrides:
            found.append(_DiscoveredSignal(
                entity_id=ov.get("entity_id", ""),
                signaal_type=ov.get("type", "binary_home"),
                platform=ov.get("platform", "manual"),
                friendly_name=ov.get("label", ov.get("entity_id", "")),
                weight=float(ov.get("weight", 1.0)),
                persoon=ov.get("persoon", ""),
            ))

        # Dedupliceer op entity_id (person.* en device_tracker.* kunnen overlappen)
        seen: set[str] = set()
        for sig in found:
            if sig.entity_id and sig.entity_id not in seen:
                self._signals.append(sig)
                seen.add(sig.entity_id)

        self._setup_done = True
        _LOGGER.info(
            "SignalPresenceLayer: %d signalen ontdekt (%s)",
            len(self._signals),
            ", ".join(f"{s.platform}:{s.signaal_type}" for s in self._signals[:8])
            + ("…" if len(self._signals) > 8 else ""),
        )

    def get_discovered(self) -> list[dict]:
        """Geef de lijst van ontdekte signalen terug (voor diagnostics/dashboard)."""
        return [
            {
                "entity_id":    s.entity_id,
                "type":         s.signaal_type,
                "platform":     s.platform,
                "naam":         s.friendly_name,
                "weight":       s.weight,
                "persoon":      s.persoon,
            }
            for s in self._signals
        ]

    def evaluate(self, hass: "HomeAssistant") -> AanwezigheidAdvies:
        import time as _time
        if not self._signals:
            return AanwezigheidAdvies(
                Aanwezigheid.ONBEKEND, "signaal",
                "Geen signalen ontdekt (nog geen setup of geen geschikte entiteiten in HA)",
                confidence=0.0,
            )

        now_ts = _time.time()
        score_thuis  = 0.0
        score_weg    = 0.0
        total_weight = 0.0
        personen_thuis: list[str] = []
        detail_parts: list[str]   = []

        for sig in self._signals:
            st = hass.states.get(sig.entity_id)
            if not st or st.state in ("unavailable", "unknown", "none", ""):
                continue

            # Recency-factor: geeft minder gewicht aan verouderde states
            recency = self._recency_factor(st, sig.signaal_type, now_ts)
            eff_weight = sig.weight * recency

            verdict = self._parse_state(sig, st.state, now_ts)
            if verdict is None:
                continue

            total_weight += eff_weight
            naam = sig.persoon or sig.friendly_name.split("_")[-1][:12]

            if verdict is True:
                score_thuis += eff_weight
                detail_parts.append(f"{naam}✅")
                if sig.persoon:
                    personen_thuis.append(sig.persoon)
                # v4.5.6: tracker/binary geeft ground-truth voor afstandssensoren
                if sig.signaal_type in ("tracker", "binary_home"):
                    for eid in self._dist_samples:
                        self._dist_ground_truth[eid] = True
            else:
                score_weg += eff_weight
                detail_parts.append(f"{naam}❌")
                if sig.signaal_type in ("tracker", "binary_home"):
                    for eid in self._dist_samples:
                        self._dist_ground_truth[eid] = False

        if total_weight < 0.1:
            return AanwezigheidAdvies(
                Aanwezigheid.ONBEKEND, "signaal",
                "Geen bruikbare signaaldata beschikbaar",
                confidence=0.0,
            )

        ratio = score_thuis / total_weight
        # Confidence: hoe groter het verschil, hoe zekerder
        confidence = min(1.0, abs(ratio - 0.5) * 2.2 * min(1.0, total_weight / 1.5))
        detail = ", ".join(detail_parts[:6]) + ("…" if len(detail_parts) > 6 else "")

        if ratio >= 0.52:
            return AanwezigheidAdvies(
                Aanwezigheid.THUIS, "signaal",
                f"Signalen: thuis ({detail})",
                confidence=round(confidence, 2),
                personen_thuis=list(set(personen_thuis)),
            )
        elif ratio <= 0.48:
            return AanwezigheidAdvies(
                Aanwezigheid.WEG, "signaal",
                f"Signalen: weg ({detail})",
                confidence=round(confidence, 2),
            )
        return AanwezigheidAdvies(
            Aanwezigheid.ONBEKEND, "signaal",
            f"Signalen: onzeker (ratio={ratio:.2f}, {detail})",
            confidence=round(confidence * 0.4, 2),
        )

    # ── Hulpmethoden ──────────────────────────────────────────────────────────

    def _stype_from_name(self, entity_id: str, state) -> str:
        """Bepaal signaaltype op basis van entity_id en friendly_name."""
        naam = (
            entity_id.lower() + " " +
            (state.attributes.get("friendly_name") or "").lower()
        )
        for patroon, stype in _NAME_SIGNAAL:
            if patroon in naam:
                return stype
        return ""

    def _persoon_van_tracker(self, entity_id: str, state, hass: "HomeAssistant") -> str:
        """Probeer de persoonsnaam te achterhalen van een device_tracker."""
        # HA koppelt device_trackers aan person.* via source_type / linked_persons
        for ps in hass.states.async_all("person"):
            sources = ps.attributes.get("device_trackers") or []
            if entity_id in sources:
                return ps.attributes.get("friendly_name", ps.entity_id.split(".")[-1])
        # Fallback: friendly_name van de tracker zelf
        fn = state.attributes.get("friendly_name", entity_id)
        return fn.split(" ")[0] if fn else entity_id.split(".")[-1]

    def _recency_factor(self, state, stype: str, now_ts: float) -> float:
        """Bereken recency-factor (0.2–1.0) op basis van last_changed."""
        try:
            import datetime as _dt
            from datetime import timezone as _tz
            lc = state.last_changed
            if lc.tzinfo is None:
                lc = lc.replace(tzinfo=_tz.utc)
            age_s = (_dt.datetime.now(_tz.utc) - lc).total_seconds()

            # Trackers en BLE-afstand: minder snel verouderen (stabielere signalen)
            if stype in ("tracker", "binary_home", "distance"):
                max_age = 600     # 10 minuten
            elif stype == "rssi":
                max_age = 300     # 5 minuten
            else:  # PIR
                max_age = _PIR_MEMORY_MIN * 60

            return max(0.2, 1.0 - (age_s / max_age) * 0.8)
        except Exception:
            return 1.0

    def _parse_state(self, sig: _DiscoveredSignal, state_str: str, now_ts: float) -> Optional[bool]:
        """Vertaal state-string naar True=thuis / False=weg / None=onbekend."""
        stype = sig.signaal_type

        if stype == "distance":
            try:
                dist = float(state_str)
                # v4.5.6: zelflerend drempel per entiteit
                # Bijhouden van home/away distributies via percentiel-schatting
                eid = sig.entity_id
                samples = self._dist_samples.setdefault(eid, {"home": [], "away": []})
                # Gebruik gevalideerde tracker-status als label indien beschikbaar
                label = self._dist_ground_truth.get(eid)
                if label is True:
                    samples["home"].append(dist)
                    if len(samples["home"]) > 200:
                        samples["home"] = samples["home"][-200:]
                elif label is False:
                    samples["away"].append(dist)
                    if len(samples["away"]) > 200:
                        samples["away"] = samples["away"][-200:]
                # Bereken geleerde drempels als er genoeg data is
                thuis_drempel = 15.0
                weg_drempel   = 30.0
                if len(samples["home"]) >= 10 and len(samples["away"]) >= 10:
                    home_sorted  = sorted(samples["home"])
                    away_sorted  = sorted(samples["away"])
                    # Thuis-drempel: 90e percentiel van home-distributies
                    thuis_drempel = home_sorted[int(len(home_sorted) * 0.90)]
                    # Weg-drempel: 10e percentiel van away-distributies
                    weg_drempel   = away_sorted[int(len(away_sorted) * 0.10)]
                    # Zorg dat drempels logisch blijven
                    if thuis_drempel >= weg_drempel:
                        midden = (thuis_drempel + weg_drempel) / 2
                        thuis_drempel = midden * 0.8
                        weg_drempel   = midden * 1.2
                if dist <= thuis_drempel:
                    return True
                if dist >= weg_drempel:
                    return False
                return None  # tussenzone
            except (ValueError, TypeError):
                return None

        elif stype == "rssi":
            try:
                rssi = float(state_str)
                # RSSI: hoe dichter bij 0, hoe sterker het signaal
                if rssi >= -70.0:
                    return True
                if rssi <= -85.0:
                    return False
                return None
            except (ValueError, TypeError):
                return None

        elif stype in ("tracker", "binary_home"):
            if state_str in ("home", "thuis", "on", "true", "connected", "1"):
                return True
            if state_str in ("not_home", "away", "weg", "off", "false", "disconnected", "0"):
                return False
            return None

        elif stype == "binary_pir":
            # PIR: 'on' = beweging nu → thuis
            # 'off' = geen beweging NU → geeft geen bewijs voor WEG
            #         (iemand kan stil zitten), dus: None als off
            if state_str in ("on", "true", "1"):
                self._pir_last_on[sig.entity_id] = now_ts
                return True
            # Kijk of er recentelijk beweging was (PIR memory window)
            last = self._pir_last_on.get(sig.entity_id)
            if last and (now_ts - last) < (_PIR_MEMORY_MIN * 60):
                return True   # was recent actief → beperkt bewijs thuis
            return None   # geen oordeel op basis van inactieve PIR

        return None

class BleWifiPresenceLayer:
    """Detecteert aanwezigheid via BLE- en WiFi-signalen zonder cloud.

    Werkt met elke HA-integratie die RSSI of connected-status levert:
      - Bermuda BLE Triangulation  → sensor.bermuda_<device>_distance of
                                     binary_sensor.bermuda_<device>_home
      - ESPresense                 → sensor.espresense_<device> (RSSI-waarde)
      - UniFi Network              → device_tracker.unifi_<device>
      - Fritz!Box                  → device_tracker.fritz_<device>
      - Bluetooth integration      → device_tracker.ble_<device>
      - Elke binary_sensor met
        device_class "connectivity" of "presence"

    Per geconfigureerd signaal:
      - Numerieke waarden (RSSI, distance): drempel-gebaseerd
      - Boolean/binary: on/off vertaling
      - device_tracker: home/not_home

    Fusie over alle signalen: gewogen meerderheid
    Recency-weging: signalen die > max_age_s oud zijn wegen minder mee.
    """

    # RSSI: hoe dichter bij 0, hoe sterker het signaal
    # Typische waarden: -40 dBm = dichtbij, -80 dBm = ver weg / weg
    _RSSI_THUIS  = -70.0   # sterker dan dit → thuis
    _RSSI_WEG    = -85.0   # zwakker dan dit → weg

    # Afstand (Bermuda): in meters
    _DIST_THUIS  = 15.0    # dichter dan dit → thuis
    _DIST_WEG    = 30.0    # verder dan dit → weg

    # Recency: signalen ouder dan dit seconden krijgen lagere weight
    _MAX_AGE_S   = 300     # 5 minuten

    def __init__(self, signal_entities: list[dict | str]) -> None:
        """
        signal_entities: lijst van dicts of strings.
          Strings: entity_id, type automatisch herkend.
          Dicts: {
            "entity_id": "sensor.bermuda_jan_distance",
            "type": "distance" | "rssi" | "binary" | "tracker",  # optioneel
            "weight": 1.0,       # relatief gewicht (standaard 1.0)
            "invert": False,     # True: on = weg (bijv. "niet thuis" sensor)
          }
        """
        self._signals: list[dict] = []
        for s in signal_entities:
            if isinstance(s, str):
                self._signals.append({"entity_id": s, "type": "auto", "weight": 1.0, "invert": False})
            else:
                self._signals.append({
                    "entity_id": s.get("entity_id", ""),
                    "type":      s.get("type", "auto"),
                    "weight":    float(s.get("weight", 1.0)),
                    "invert":    bool(s.get("invert", False)),
                })

    def evaluate(self, hass: "HomeAssistant") -> AanwezigheidAdvies:
        if not self._signals:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "ble_wifi", "Geen BLE/WiFi signalen geconfigureerd", confidence=0.0)

        import time as _time
        now = _time.time()

        score_thuis = 0.0
        score_weg   = 0.0
        total_weight = 0.0
        detail_parts = []

        for sig in self._signals:
            eid    = sig["entity_id"]
            weight = sig["weight"]
            invert = sig["invert"]
            stype  = sig["type"]

            st = hass.states.get(eid)
            if not st or st.state in ("unavailable", "unknown", "none"):
                continue

            # Recency-factor: verminder gewicht voor oude metingen
            try:
                from datetime import timezone as _tz
                import datetime as _dt
                last_changed = st.last_changed
                if last_changed.tzinfo is None:
                    last_changed = last_changed.replace(tzinfo=_tz.utc)
                age_s = (
                    _dt.datetime.now(_tz.utc) - last_changed
                ).total_seconds()
                recency = max(0.2, 1.0 - (age_s / self._MAX_AGE_S) * 0.8)
            except Exception:
                recency = 1.0

            effective_weight = weight * recency
            verdict = self._parse_signal(st.state, eid, stype)

            if verdict is None:
                continue

            is_thuis = (not invert and verdict) or (invert and not verdict)
            if is_thuis:
                score_thuis   += effective_weight
                detail_parts.append(f"{eid.split('.')[-1]}:✅")
            else:
                score_weg     += effective_weight
                detail_parts.append(f"{eid.split('.')[-1]}:❌")
            total_weight += effective_weight

        if total_weight == 0:
            return AanwezigheidAdvies(Aanwezigheid.ONBEKEND, "ble_wifi", "Geen BLE/WiFi data beschikbaar", confidence=0.0)

        ratio_thuis = score_thuis / total_weight
        confidence  = min(1.0, abs(ratio_thuis - 0.5) * 2 + 0.3) * min(1.0, total_weight / 2.0)
        detail      = ", ".join(detail_parts[:5])  # max 5 in detail

        if ratio_thuis >= 0.55:
            return AanwezigheidAdvies(
                Aanwezigheid.THUIS, "ble_wifi",
                f"BLE/WiFi: thuis ({detail})",
                confidence=round(confidence, 2),
            )
        elif ratio_thuis <= 0.45:
            return AanwezigheidAdvies(
                Aanwezigheid.WEG, "ble_wifi",
                f"BLE/WiFi: weg ({detail})",
                confidence=round(confidence, 2),
            )
        return AanwezigheidAdvies(
            Aanwezigheid.ONBEKEND, "ble_wifi",
            f"BLE/WiFi: onzeker (ratio={ratio_thuis:.2f}, {detail})",
            confidence=round(confidence * 0.5, 2),
        )

    def _parse_signal(self, state_str: str, entity_id: str, stype: str) -> Optional[bool]:
        """Vertaal entity-state naar True=thuis / False=weg / None=onbekend."""
        eid_lower = entity_id.lower()

        # Auto-detectie van type op basis van entity_id en domein
        if stype == "auto":
            if any(x in eid_lower for x in ("distance", "afstand")):
                stype = "distance"
            elif any(x in eid_lower for x in ("rssi", "signal", "signaal")):
                stype = "rssi"
            elif entity_id.startswith("device_tracker."):
                stype = "tracker"
            else:
                stype = "binary"

        if stype == "distance":
            try:
                dist = float(state_str)
                if dist <= self._DIST_THUIS:
                    return True
                if dist >= self._DIST_WEG:
                    return False
                return None
            except (ValueError, TypeError):
                return None

        elif stype == "rssi":
            try:
                rssi = float(state_str)
                if rssi >= self._RSSI_THUIS:
                    return True
                if rssi <= self._RSSI_WEG:
                    return False
                return None
            except (ValueError, TypeError):
                return None

        elif stype == "tracker":
            if state_str in ("home", "thuis"):
                return True
            if state_str in ("not_home", "away", "weg"):
                return False
            return None

        else:  # binary
            if state_str in ("on", "true", "1", "home", "connected", "present"):
                return True
            if state_str in ("off", "false", "0", "not_home", "disconnected", "absent"):
                return False
            return None


# ─────────────────────────────────────────────────────────────────────────────
# LAAG 3: Zelf-lerend aanwezigheidspatroon
# ─────────────────────────────────────────────────────────────────────────────

class LearnedPresenceLayer:
    """Leert wanneer er normaal iemand thuis is — per uur per weekdag.

    Methode:
      - Elke coordinator-cyclus wordt de aanwezigheidsstatus (van laag 1)
        geregistreerd per (weekdag, uur) bucket.
      - EMA per bucket: α=0.1 (langzaam leren, stabiel)
      - Score 0.0 = altijd weg, 1.0 = altijd thuis
      - Drempel 0.5: boven → verwacht thuis, onder → verwacht weg
      - Na MIN_SAMPLES_PER_BUCKET samples: betrouwbaar

    Opgeslagen via HA Store voor persistentie over herstarts.
    """

    _ALPHA              = 0.10
    _THUIS_DREMPEL      = 0.55   # score ≥ dit → verwacht thuis
    _WEG_DREMPEL        = 0.35   # score ≤ dit → verwacht weg
    _MIN_SAMPLES        = 14     # minimaal 2 weken data per bucket

    def __init__(self) -> None:
        # bucket: (weekday 0-6, hour 0-23) → {"score": float, "samples": int}
        self._buckets: dict[tuple, dict] = defaultdict(lambda: {"score": 0.5, "samples": 0})
        self._loaded = False

    def record(self, is_thuis: bool) -> None:
        """Registreer huidige aanwezigheid. Aanroepen elke coordinator-cyclus."""
        now = datetime.now(timezone.utc)
        key = (now.weekday(), now.hour)
        b   = self._buckets[key]
        b["score"]   = self._ALPHA * (1.0 if is_thuis else 0.0) + (1 - self._ALPHA) * b["score"]
        b["samples"] = min(b["samples"] + 1, 9999)

    def _nearest_score(self, weekday: int, hour: int) -> tuple[float, int, str]:
        """Zoek de dichtstbijzijnde betrouwbare bucket als fallback voor lege buckets.

        Prioriteit: zelfde weekdag (nabijgelegen uren) → zelfde uurtype (ma-vr/weekend) → globaal gemiddelde.
        Geeft (score, samples, beschrijving) terug.
        """
        # 1. Zelfde weekdag, uitbreidend zoeken in uren (max ±3 uur)
        for delta in range(1, 4):
            for h_off in (delta, -delta):
                nb_h = (hour + h_off) % 24
                nb = self._buckets.get((weekday, nb_h))
                if nb and nb["samples"] >= self._MIN_SAMPLES:
                    dagen = ["ma","di","wo","do","vr","za","zo"]
                    return nb["score"], nb["samples"], f"nabij {dagen[weekday]} {nb_h}:00"

        # 2. Zelfde uurtype op andere dagen (werkdag/weekend)
        is_weekend = weekday >= 5
        same_type  = [5, 6] if is_weekend else [0, 1, 2, 3, 4]
        scores = []
        for wd in same_type:
            b = self._buckets.get((wd, hour))
            if b and b["samples"] >= self._MIN_SAMPLES:
                scores.append(b["score"])
        if scores:
            avg = sum(scores) / len(scores)
            label = "weekend" if is_weekend else "werkdagen"
            return avg, len(scores) * self._MIN_SAMPLES, f"gemiddelde {label} {hour}:00"

        # 3. Globaal gemiddelde over alle betrouwbare buckets
        all_scores = [v["score"] for v in self._buckets.values() if v["samples"] >= self._MIN_SAMPLES]
        if all_scores:
            return sum(all_scores) / len(all_scores), len(all_scores), "globaal gemiddelde"

        return 0.5, 0, "geen data"

    def evaluate(self, now: Optional[datetime] = None) -> AanwezigheidAdvies:
        if now is None:
            now = datetime.now(timezone.utc)
        key   = (now.weekday(), now.hour)
        b     = self._buckets.get(key)

        # v4.5.6: als deze bucket onvoldoende data heeft, val terug op dichtstbijzijnde
        # betrouwbare bucket in plaats van ONBEKEND te retourneren.
        if b is None or b["samples"] < self._MIN_SAMPLES:
            fb_score, fb_n, fb_desc = self._nearest_score(now.weekday(), now.hour)
            cur_n = b["samples"] if b else 0
            if fb_n > 0:
                # Geef lagere confidence omdat het een schatting is
                fb_confidence = round(min(0.55, 0.2 + abs(fb_score - 0.5) * 0.7), 2)
                if fb_score >= self._THUIS_DREMPEL:
                    return AanwezigheidAdvies(
                        Aanwezigheid.THUIS, "geleerd",
                        f"Schatting op basis van {fb_desc} ({cur_n}/{self._MIN_SAMPLES} metingen dit uur)",
                        confidence=fb_confidence,
                    )
                if fb_score <= self._WEG_DREMPEL:
                    return AanwezigheidAdvies(
                        Aanwezigheid.WEG, "geleerd",
                        f"Schatting op basis van {fb_desc} ({cur_n}/{self._MIN_SAMPLES} metingen dit uur)",
                        confidence=fb_confidence,
                    )
            return AanwezigheidAdvies(
                Aanwezigheid.ONBEKEND, "geleerd",
                f"Nog te weinig data ({cur_n}/{self._MIN_SAMPLES} metingen)",
            )

        score = b["score"]
        dagen = ["ma","di","wo","do","vr","za","zo"]
        dag   = dagen[now.weekday()]

        if score >= self._THUIS_DREMPEL:
            return AanwezigheidAdvies(
                Aanwezigheid.THUIS, "geleerd",
                f"Geleerd: {dag} {now.hour}:00 normaal thuis (score {score:.2f})",
                confidence=round(min(1.0, 0.4 + score * 0.6), 2),
            )
        if score <= self._WEG_DREMPEL:
            return AanwezigheidAdvies(
                Aanwezigheid.WEG, "geleerd",
                f"Geleerd: {dag} {now.hour}:00 normaal weg (score {score:.2f})",
                confidence=round(min(1.0, 0.4 + (1.0 - score) * 0.6), 2),
            )
        return AanwezigheidAdvies(
            Aanwezigheid.ONBEKEND, "geleerd",
            f"Onzeker: {dag} {now.hour}:00 score {score:.2f}",
            confidence=0.2,
        )

    def get_week_heatmap(self) -> dict:
        """Geeft een 7×24 heatmap terug voor dashboard-visualisatie."""
        result = {}
        for wd in range(7):
            for h in range(24):
                b = self._buckets.get((wd, h), {"score": 0.5, "samples": 0})
                result[f"{wd}_{h}"] = {
                    "score":   round(b["score"], 2),
                    "samples": b["samples"],
                    "reliable": b["samples"] >= self._MIN_SAMPLES,
                }
        return result

    def to_dict(self) -> dict:
        return {
            f"{k[0]}_{k[1]}": {"score": round(v["score"], 3), "samples": v["samples"]}
            for k, v in self._buckets.items()
        }

    def from_dict(self, data: dict) -> None:
        for key_str, val in data.items():
            try:
                wd, h = map(int, key_str.split("_"))
                self._buckets[(wd, h)] = val
            except (ValueError, KeyError):
                pass


# ─────────────────────────────────────────────────────────────────────────────
# GECOMBINEERDE AANWEZIGHEIDS-EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# GECOMBINEERDE AANWEZIGHEIDS-EVALUATOR — volledig zelflerend
# ─────────────────────────────────────────────────────────────────────────────

_LAAG_GEWICHTEN = {
    "tracker":  1.0,
    "signaal":  0.8,
    "kalender": 0.7,
    "geleerd":  0.4,
}

_MIN_CONFIDENCE = 0.15
_HYSTERESE      = 0.15


class ZonePresenceManager:
    """Combineert alle aanwezigheidslagen via gewogen confidence-fusie.

    Volledig zelflerend en zero-config:
      - Vindt automatisch alle person.*, device_tracker.*, BLE/WiFi-signalen,
        PIR-sensoren en kalender-entiteiten in HA
      - Handmatige configuratie is optioneel (alleen nodig voor overrides)
      - Na 2 weken leert het weekpatroon als aanvullende laag

    Gebruik vanuit coordinator:
        mgr = ZonePresenceManager(hass, cfg)
        await mgr.async_setup()            # eenmalig bij start
        advies = mgr.evaluate(hass)        # elke coordinator-cyclus

    Minimale config (alles optioneel):
        {
          # Kalenders voor vakantie/agenda detectie (auto-gevonden als leeg)
          "presence_calendar_entities": ["calendar.gezin"],
          # Extra signalen die niet auto-discoverd worden (edge cases)
          "ble_wifi_overrides": [],
        }

    Events op hass.bus bij statuswijziging:
        cloudems_presence_arrived  →  iemand komt thuis
        cloudems_presence_left     →  iedereen vertrekt
    """

    _MIN_FUSED_CONFIDENCE = 0.25
    STORAGE_KEY = "cloudems_presence_learned_v1"

    def __init__(self, hass: "HomeAssistant | None", cfg: dict) -> None:
        self._hass      = hass
        self._cfg       = cfg
        # Signaal-laag wordt gevuld door async_setup
        self._signal    = SignalPresenceLayer(
            manual_overrides=cfg.get("ble_wifi_overrides", [])
        )
        # Kalender: auto-ontdekt in async_setup als niet geconfigureerd
        cal_entities = cfg.get("presence_calendar_entities", [])
        self._calendar  = CalendarPresenceLayer(cal_entities)
        self._learned   = LearnedPresenceLayer()
        self._last_advies:   Optional[AanwezigheidAdvies] = None
        self._prev_status:   Optional[Aanwezigheid] = None
        self._layer_results: dict[str, AanwezigheidAdvies] = {}
        self._setup_done = False

    async def async_setup(self) -> None:
        """Eenmalige setup: scan HA en herstel geleerde data."""
        if not self._hass or self._setup_done:
            return

        # Auto-discover alle signalen (person, trackers, BLE, PIR, ...)
        await self._signal.async_setup(self._hass)

        # Auto-discover kalenders als niet handmatig geconfigureerd
        if not self._calendar._entities:
            self._calendar = CalendarPresenceLayer(
                self._autodiscover_calendars(self._hass)
            )

        # Herstel geleerde data uit HA Store
        try:
            from homeassistant.helpers.storage import Store
            store = Store(self._hass, 1, self.STORAGE_KEY)
            saved = await store.async_load() or {}
            if saved.get("learned"):
                self._learned.from_dict(saved["learned"])
                _LOGGER.info(
                    "ZonePresenceManager: geleerd patroon hersteld (%d buckets)",
                    len(saved["learned"]),
                )
            self._store = store
        except Exception as err:
            _LOGGER.debug("ZonePresence store laden mislukt: %s", err)

        self._setup_done = True
        _LOGGER.info(
            "ZonePresenceManager: setup klaar — %d signalen, %d kalenders",
            len(self._signal._signals),
            len(self._calendar._entities),
        )

    def _autodiscover_calendars(self, hass: "HomeAssistant") -> list[str]:
        """Zoek alle calendar.* entiteiten in HA."""
        cals = [s.entity_id for s in hass.states.async_all("calendar")]
        if cals:
            _LOGGER.info("ZonePresenceManager: %d kalenders auto-ontdekt: %s", len(cals), cals)
        return cals

    def evaluate(self, hass: "HomeAssistant") -> AanwezigheidAdvies:
        """Evalueer alle lagen en geef een gefuseerd advies terug."""
        self._hass = hass

        layers: list[tuple[str, AanwezigheidAdvies]] = [
            ("signaal",  self._signal.evaluate(hass)),
            ("kalender", self._calendar.evaluate(hass)),
            ("geleerd",  self._learned.evaluate()),
        ]
        self._layer_results = {n: a for n, a in layers}

        score_thuis    = 0.0
        score_weg      = 0.0
        total_weight   = 0.0
        best_bron      = "standaard"
        best_confidence= 0.0
        personen_thuis: list[str] = []

        for laagnaam, advies in layers:
            if advies.confidence < _MIN_CONFIDENCE:
                continue
            if advies.status == Aanwezigheid.ONBEKEND:
                continue

            gewicht      = _LAAG_GEWICHTEN.get(laagnaam, 0.5)
            gewogen_conf = advies.confidence * gewicht
            total_weight += gewogen_conf

            if advies.status == Aanwezigheid.THUIS:
                score_thuis += gewogen_conf
                if gewogen_conf > best_confidence:
                    best_confidence = gewogen_conf
                    best_bron = laagnaam
                personen_thuis.extend(advies.personen_thuis)
            else:
                score_weg += gewogen_conf
                if gewogen_conf > best_confidence:
                    best_confidence = gewogen_conf
                    best_bron = laagnaam

        if total_weight < self._MIN_FUSED_CONFIDENCE:
            status = Aanwezigheid.ONBEKEND
            detail = "Onvoldoende data — aan het leren…"
            fused_confidence = 0.1
        else:
            diff = score_thuis - score_weg
            prev = self._prev_status
            if prev == Aanwezigheid.THUIS:
                status = Aanwezigheid.THUIS if diff > -_HYSTERESE else Aanwezigheid.WEG
            elif prev == Aanwezigheid.WEG:
                status = Aanwezigheid.WEG if diff < _HYSTERESE else Aanwezigheid.THUIS
            else:
                status = Aanwezigheid.THUIS if diff >= 0 else Aanwezigheid.WEG

            fused_confidence = min(1.0, abs(diff) / max(total_weight, 0.01) + 0.3)
            detail = (
                f"Fusie: thuis={score_thuis:.2f} weg={score_weg:.2f} "
                f"(bron: {best_bron}, conf: {fused_confidence:.2f})"
            )

        advies = AanwezigheidAdvies(
            status=status,
            bron=f"fusie/{best_bron}",
            detail=detail,
            confidence=round(fused_confidence, 2),
            personen_thuis=list(set(personen_thuis)),
        )

        # Leer van betrouwbare uitkomsten
        if fused_confidence >= 0.5 and status != Aanwezigheid.ONBEKEND:
            self._learned.record(status == Aanwezigheid.THUIS)

        # Fire HA-event bij statuswijziging
        if hass and status != Aanwezigheid.ONBEKEND and status != self._prev_status:
            self._fire_presence_event(status, advies, hass)

        self._prev_status = status if status != Aanwezigheid.ONBEKEND else self._prev_status
        self._last_advies  = advies
        return advies

    def _fire_presence_event(
        self,
        status: Aanwezigheid,
        advies: AanwezigheidAdvies,
        hass: "HomeAssistant",
    ) -> None:
        event_type = "cloudems_presence_arrived" if status == Aanwezigheid.THUIS else "cloudems_presence_left"
        try:
            hass.bus.fire(event_type, {
                "status":         status.value,
                "bron":           advies.bron,
                "confidence":     advies.confidence,
                "personen_thuis": advies.personen_thuis,
                "detail":         advies.detail,
            })
            _LOGGER.info(
                "ZonePresence: %s → %s (conf=%.2f, bron=%s)",
                self._prev_status.value if self._prev_status else "?",
                status.value, advies.confidence, advies.bron,
            )
        except Exception as err:
            _LOGGER.debug("Presence event fout: %s", err)

    async def async_save_learned(self) -> None:
        """Sla geleerde patronen op in HA Store (aanroepen bij shutdown of periodiek)."""
        if hasattr(self, "_store"):
            try:
                await self._store.async_save({"learned": self._learned.to_dict()})
            except Exception as err:
                _LOGGER.debug("ZonePresence opslaan mislukt: %s", err)

    @property
    def calendar_boost_hint(self) -> bool:
        return self._calendar.boost_hint

    @property
    def last_advies(self) -> Optional[AanwezigheidAdvies]:
        return self._last_advies

    def get_heatmap(self) -> dict:
        return self._learned.get_week_heatmap()

    def get_status(self) -> dict:
        a = self._last_advies
        layers_debug = {
            naam: {
                "status":     adv.status.value,
                "confidence": adv.confidence,
                "detail":     adv.detail,
            }
            for naam, adv in self._layer_results.items()
        }
        return {
            "status":           a.status.value if a else "onbekend",
            "bron":             a.bron if a else None,
            "confidence":       a.confidence if a else 0.0,
            "detail":           a.detail if a else None,
            "personen_thuis":   a.personen_thuis if a else [],
            "calendar_boost":   self.calendar_boost_hint,
            "lagen":            layers_debug,
            "ontdekte_signalen": self._signal.get_discovered(),
            "setup_klaar":      self._setup_done,
        }

    def learned_to_dict(self) -> dict:
        return self._learned.to_dict()

    def learned_from_dict(self, data: dict) -> None:
        self._learned.from_dict(data)

