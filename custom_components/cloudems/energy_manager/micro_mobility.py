# -*- coding: utf-8 -*-
"""
CloudEMS Micro-Mobiliteit Tracker — v1.1.0

Ondersteunt e-bikes, elektrische scooters en andere kleine accu's van het
gezin. Verschil met auto-EV:
  • Veel kleinere batterijen (0.3–1.5 kWh)
  • Korter laden (1–6 uur)
  • Hogere frequentie (dagelijks)
  • Lagere prioriteit: kan prima schakelen op PV-surplus of goedkoopste uur

Detectie via NILM:
  E-bike lader:     doorgaans 40–180 W, 2–5 uur, regelmatig
  Scooter lader:    doorgaans 181–700 W (typisch ≥ 200 W), 2–8 uur

Slimme laadplanning:
  1. NILM herkent de lader automatisch (nieuw device-type "micro_ev_charger")
  2. Tracker leert laadpatroon per voertuig (welk gezinslid, hoe laat, hoeveel kWh)
  3. Stuurt (optioneel) slimme schakelaar aan: laad op goedkoopste uur of PV-surplus

Sensor output:
  • Aantal geladen voertuigen vandaag
  • Totaal kWh micro-mobiliteit vandaag
  • Kosten vandaag
  • Aanbeveling voor optimale laadtijd morgen

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_micro_mobility_v1"
STORAGE_VERSION = 1

# Vermogensprofiel voor micro-EV detectie (W)
# Grenzen zijn bewust non-overlappend: [40–180] = e-bike, [181–700] = scooter.
# Apparaten in de zone 181–250 W zijn ambigue bij de eerste meting; het type
# wordt verfijnd naarmate meer sessiedata beschikbaar is (avg_power + duur).
EBIKE_POWER_MIN    =  40
EBIKE_POWER_MAX    = 180     # e-bike laders: typisch 4A×36V ≈ 144 W max
SCOOTER_POWER_MIN  = 181     # scooter laders: doorgaans ≥ 200 W
SCOOTER_POWER_MAX  = 700

# Zone waarbinnen het type ambigue is bij een eerste meting (W).
AMBIGUOUS_POWER_MIN = 181
AMBIGUOUS_POWER_MAX = 250

# Minimale laadduur voor een volledige sessie
MIN_SESSION_MINUTES = 20
SAVE_INTERVAL_S     = 300

# Maximale laadduur voor een micro-EV sessie.
# Een luchtreiniger / verwarming / koelkast draait uren of dagen aan één stuk;
# een echte e-bike of scooter lader stopt na het volladen (max ~10 uur).
MAX_SESSION_HOURS   = 10.0

# Minimaal geladen energie voor een echte accu-sessie.
# Voorkomt dat kleine continue verbruikers (luchtreiniger, TV standby) als
# e-bike worden geregistreerd.
MIN_SESSION_KWH     = 0.05   # 50 Wh — een e-bike laadt altijd meer dan dit
GRACE_PERIOD_S      = 180    # 3 min wachten voor sessie te sluiten (NILM-ruis)

# Device-types die door NILM al herkend zijn als iets anders dan een lader.
# Deze worden nooit als micro-EV behandeld, ook al valt hun vermogen in het bereik.
EXCLUDED_DEVICE_TYPES = {
    "socket", "light", "entertainment", "refrigerator",
    "heat_pump", "boiler", "cv_boiler", "electric_heater",
    "washing_machine", "dryer", "dishwasher", "oven", "microwave",
    "ev_charger", "kettle", "air_purifier",
}

# Meest gangbare e-bike batterijcapaciteit (Wh)
TYPICAL_EBIKE_CAPACITY_WH    = 500
TYPICAL_SCOOTER_CAPACITY_WH  = 1500

DAYS_NL = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]


@dataclass
class MicroEVSession:
    """Één laadsessie van een e-bike of scooter."""
    device_id:    str
    vehicle_type: str     # "ebike" | "scooter" | "micro_ev"
    label:        str
    start_ts:     float
    end_ts:       float   = 0.0
    kwh:          float   = 0.0
    cost_eur:     float   = 0.0
    peak_power_w:    float = 0.0
    current_power_w: float = 0.0
    phase:           str   = "L1"

    @property
    def duration_min(self) -> float:
        if self.end_ts:
            return (self.end_ts - self.start_ts) / 60
        return (time.time() - self.start_ts) / 60

    @property
    def weekday(self) -> int:
        return datetime.fromtimestamp(self.start_ts, tz=timezone.utc).weekday()

    @property
    def start_hour(self) -> int:
        return datetime.fromtimestamp(self.start_ts, tz=timezone.utc).hour

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id, "vehicle_type": self.vehicle_type,
            "label": self.label, "start_ts": self.start_ts, "end_ts": self.end_ts,
            "kwh": round(self.kwh, 3), "cost_eur": round(self.cost_eur, 3),
            "peak_power_w": self.peak_power_w, "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MicroEVSession":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class VehicleProfile:
    """Geleerd profiel per voertuig / gezinslid."""
    device_id:    str
    vehicle_type: str
    label:        str
    sessions:     int   = 0
    total_kwh:    float = 0.0
    avg_kwh:      float = 0.0
    avg_duration_min: float = 0.0
    avg_start_hour:   float = 0.0
    typical_weekdays: list  = field(default_factory=list)
    peak_power_w:     float = 0.0
    # Laadfrequentie: gemiddeld X dagen per week
    sessions_per_week: float = 0.0


@dataclass
class MicroMobilityData:
    """Output voor de HA-sensor."""
    vehicles_today:        int
    kwh_today:             float
    cost_today_eur:        float
    sessions_today:        list[dict]
    active_sessions:       list[dict]
    vehicle_profiles:      list[dict]
    best_charge_hour:      Optional[int]
    best_charge_label:     str
    advice:                str
    total_sessions:        int
    total_kwh:             float
    weekly_kwh_avg:        float


def _classify_vehicle(power_w: float, profile: "VehicleProfile | None" = None) -> str:
    """Classificeer voertuigtype op basis van laadvermogen.

    Bij een eerste meting in de ambigue zone (181–250 W) wordt "ambiguous_micro_ev"
    teruggegeven. Zodra een voertuigprofiel ≥ 3 sessies heeft, wordt het
    historisch gemiddeld vermogen gebruikt om het type te verfijnen.
    """
    # Gebruik historisch gemiddeld vermogen als het profiel al betrouwbaar is
    ref_w = power_w
    if profile and profile.sessions >= 3 and profile.avg_duration_min > 0:
        learned_avg_w = (profile.avg_kwh * 1000) / max(profile.avg_duration_min / 60, 0.1)
        if learned_avg_w > 0:
            ref_w = learned_avg_w

    if EBIKE_POWER_MIN <= ref_w <= EBIKE_POWER_MAX:
        return "ebike"
    elif SCOOTER_POWER_MIN <= ref_w <= SCOOTER_POWER_MAX:
        # Ambigue zone: pas beslissen op duur als we dat kunnen
        if AMBIGUOUS_POWER_MIN <= ref_w <= AMBIGUOUS_POWER_MAX:
            if profile and profile.avg_duration_min > 0:
                return "scooter" if profile.avg_duration_min >= 180 else "ebike"
            return "ambiguous_micro_ev"
        return "scooter"
    return "micro_ev"


class MicroMobilityTracker:
    """
    Volgt e-bike en scooter laadsessies van het hele gezin.

    Gebruik vanuit coordinator:
        tracker.update(nilm_devices, price_eur_kwh)
        data = tracker.get_data()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._sessions:       list[MicroEVSession] = []
        self._active:         dict[str, MicroEVSession] = {}   # device_id → active session
        self._profiles:       dict[str, VehicleProfile] = {}
        self._today_date      = ""
        self._today_sessions: list[MicroEVSession] = []
        self._dirty  = False
        self._last_save = 0.0
        self._last_seen: dict[str, float] = {}   # device_id → timestamp laatste ON-signaal

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for sd in saved.get("sessions", []):
            try:
                self._sessions.append(MicroEVSession.from_dict(sd))
            except Exception:
                pass
        self._rebuild_profiles()
        _LOGGER.info(
            "MicroMobilityTracker: %d sessies geladen, %d voertuigen",
            len(self._sessions), len(self._profiles),
        )

    def update(self, nilm_devices: list[dict], price_eur_kwh: float = 0.0) -> None:
        """
        Verwerk NILM-devices voor micro-EV herkenning.

        Wordt elke 10s aangeroepen vanuit de coordinator.
        """
        now   = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today_date:
            self._today_date     = today
            self._today_sessions = []

        active_ids = set()

        for dev in nilm_devices:
            dtype = dev.get("device_type", "")
            # Herken micro-EV laders: nieuw type OR bekende NILM-typen in juist vermogensbereik
            power_w = float(dev.get("current_power") or 0)
            # Directe herkenning op device_type (NILM of gebruiker heeft het al benoemd)
            is_micro_by_type = dtype in ("micro_ev_charger", "ebike", "scooter", "micro_ev")
            # Herkenning op vermogensbereik voor onbekende apparaten
            is_micro_by_power = (
                dev.get("is_on")
                and EBIKE_POWER_MIN <= power_w <= SCOOTER_POWER_MAX
                and dtype in ("unknown", "resistive", "")
                and dtype not in EXCLUDED_DEVICE_TYPES
            )
            is_micro = is_micro_by_type or is_micro_by_power
            # Sluit expliciet bekende niet-lader types uit (veiligheidsnet naast dtype-check)
            if dtype in EXCLUDED_DEVICE_TYPES:
                is_micro = False
            # ── Naam-gebaseerde uitsluiting ──────────────────────────────────────
            # Als NILM of de gebruiker al een naam heeft gegeven die duidelijk
            # geen lader is, nooit als micro-EV behandelen.
            _NON_CHARGER_NAME_KEYWORDS = (
                "purifier", "luchtreiniger", "heater", "verwarming", "lamp",
                "light", "koelkast", "fridge", "freezer", "vriezer",
                "tv", "television", "audio", "speaker", "printer",
                "router", "modem", "nas", "server", "computer",
                "wasmachine", "washing", "droger", "dryer", "vaatwasser", "dishwasher",
                "oven", "magnetron", "microwave", "kettle", "waterkoker",
                "boiler", "warmtepomp",
            )
            # label ophalen vóór de naamcheck (fix: label was niet gedefinieerd op dit punt)
            did         = dev.get("device_id", "")
            label       = dev.get("name") or dev.get("label") or f"Micro-EV {did[-4:]}"
            label_low = label.lower()
            # Sla naamcheck over als NILM/gebruiker het apparaat al als lader heeft benoemd
            if not is_micro_by_type and any(kw in label_low for kw in _NON_CHARGER_NAME_KEYWORDS):
                is_micro = False

            if not is_micro or not dev.get("is_on"):
                # Apparaat uit → sluit actieve sessie
                if did in self._active:
                    self._close_session(did, now, price_eur_kwh)
                continue


            vtype       = _classify_vehicle(power_w, self._profiles.get(did))
            active_ids.add(did)

            if did not in self._active:
                # Nieuwe sessie starten
                sess = MicroEVSession(
                    device_id       = did,
                    vehicle_type    = vtype,
                    label           = label,
                    start_ts        = now,
                    peak_power_w    = power_w,
                    current_power_w = power_w,
                    phase           = dev.get("phase", "L1"),
                )
                self._active[did] = sess
                _LOGGER.info("MicroMobility: sessie gestart — %s (%s, %.0fW)", label, vtype, power_w)
            else:
                # Sessie bijwerken
                sess = self._active[did]
                tick_kwh = power_w * (10.0 / 3600.0) / 1000.0  # 10s tick
                sess.kwh             += tick_kwh
                sess.cost_eur        += tick_kwh * price_eur_kwh
                sess.current_power_w  = power_w
                sess.peak_power_w     = max(sess.peak_power_w, power_w)
                self._dirty = True

        # Update last_seen voor actieve apparaten
        for did in active_ids:
            self._last_seen[did] = now

        # Sluit sessies voor verdwenen apparaten — maar wacht GRACE_PERIOD_S
        # voordat we definitief sluiten (NILM confidence kan kort wegvallen)
        for did in list(self._active.keys()):
            if did not in active_ids:
                last = self._last_seen.get(did, now)
                if (now - last) >= GRACE_PERIOD_S:
                    self._close_session(did, now, price_eur_kwh)
                    self._last_seen.pop(did, None)

    def _close_session(self, device_id: str, now: float, price_eur_kwh: float) -> None:
        sess = self._active.pop(device_id, None)
        if sess is None:
            return
        sess.end_ts = now
        duration_min = sess.duration_min
        duration_h   = duration_min / 60.0

        if duration_min < MIN_SESSION_MINUTES:
            _LOGGER.debug("MicroMobility: sessie te kort (%d min), genegeerd", duration_min)
            return
        if duration_h > MAX_SESSION_HOURS:
            _LOGGER.info(
                "MicroMobility: sessie '%s' te lang (%.1fh > %.0fh max) — "
                "waarschijnlijk continu verbruiker, genegeerd",
                sess.label, duration_h, MAX_SESSION_HOURS,
            )
            return
        if sess.kwh < MIN_SESSION_KWH:
            _LOGGER.debug(
                "MicroMobility: sessie '%s' te weinig energie (%.3f kWh < %.3f kWh min), genegeerd",
                sess.label, sess.kwh, MIN_SESSION_KWH,
            )
            return
        self._sessions.append(sess)
        self._today_sessions.append(sess)
        self._update_profile(sess)
        _LOGGER.info(
            "MicroMobility: sessie afgesloten — %s | %.2f kWh | %.0f min | €%.2f",
            sess.label, sess.kwh, sess.duration_min, sess.cost_eur,
        )
        self._dirty = True

    def _update_profile(self, sess: MicroEVSession) -> None:
        did = sess.device_id
        if did not in self._profiles:
            self._profiles[did] = VehicleProfile(
                device_id=did, vehicle_type=sess.vehicle_type, label=sess.label
            )
        p = self._profiles[did]
        p.sessions   += 1
        p.total_kwh  += sess.kwh
        alpha = 0.2
        p.avg_kwh          = alpha * sess.kwh          + (1 - alpha) * (p.avg_kwh or sess.kwh)
        p.avg_duration_min = alpha * sess.duration_min + (1 - alpha) * (p.avg_duration_min or sess.duration_min)
        p.avg_start_hour   = alpha * sess.start_hour   + (1 - alpha) * (p.avg_start_hour or sess.start_hour)
        p.peak_power_w     = max(p.peak_power_w, sess.peak_power_w)

        # Berekenen laadfrequentie (sessies per week)
        recent = [s for s in self._sessions[-30:] if s.device_id == did]
        if len(recent) >= 2:
            span_days = (recent[-1].start_ts - recent[0].start_ts) / 86400 or 1
            p.sessions_per_week = round(len(recent) / max(span_days, 1) * 7, 1)

        # Typische weekdagen
        wd_count: dict[int, int] = {}
        for s in self._sessions[-20:]:
            if s.device_id == did:
                wd_count[s.weekday] = wd_count.get(s.weekday, 0) + 1
        total = sum(wd_count.values())
        p.typical_weekdays = [wd for wd, cnt in wd_count.items() if total > 0 and cnt / total >= 0.2]

    def _rebuild_profiles(self) -> None:
        for sess in self._sessions:
            self._update_profile(sess)

    def get_data(self) -> MicroMobilityData:
        """Geeft huidige micro-mobiliteitsdata terug voor HA sensor."""
        kwh_today  = sum(s.kwh for s in self._today_sessions)
        cost_today = sum(s.cost_eur for s in self._today_sessions)

        # Actieve sessies
        active_list = [
            {
                "label":        s.label,
                "vehicle_type": s.vehicle_type,
                "power_w":      round(s.current_power_w, 0),
                "kwh_so_far":   round(s.kwh, 3),
                "duration_min": round(s.duration_min, 0),
                "cost_eur":     round(s.cost_eur, 2),
                "phase":        s.phase,
            }
            for s in self._active.values()
        ]

        # Afgesloten sessies vandaag
        today_list = [
            {
                "label":        s.label,
                "vehicle_type": s.vehicle_type,
                "kwh":          round(s.kwh, 3),
                "duration_min": round(s.duration_min, 0),
                "cost_eur":     round(s.cost_eur, 2),
                "start_hour":   s.start_hour,
            }
            for s in self._today_sessions
        ]

        # Voertuigprofielen
        profile_list = [
            {
                "label":             p.label,
                "vehicle_type":      p.vehicle_type,
                "sessions":          p.sessions,
                "avg_kwh":           round(p.avg_kwh, 2),
                "avg_duration_min":  round(p.avg_duration_min, 0),
                "avg_start_hour":    round(p.avg_start_hour, 0),
                "sessions_per_week": p.sessions_per_week,
                "peak_power_w":      p.peak_power_w,
                "typical_weekdays":  [DAYS_NL[wd] for wd in p.typical_weekdays if wd < 7],
                "total_kwh":         round(p.total_kwh, 1),
            }
            for p in self._profiles.values()
        ]

        # Beste laadtijd (uit PV-profiel of goedkoop uur — coördinatie met zelfconsumptie)
        # Heuristiek: midden van de dag als PV aanwezig, anders vroeg in de ochtend
        best_hour = None
        best_label = "onbekend"

        # Wekelijks gemiddelde kWh
        recent_sess = self._sessions[-50:]
        weekly_kwh  = 0.0
        if len(recent_sess) >= 2:
            span_days = (recent_sess[-1].start_ts - recent_sess[0].start_ts) / 86400 or 1
            weekly_kwh = round(sum(s.kwh for s in recent_sess) / max(span_days, 1) * 7, 2)

        # Advies
        n_profiles = len(self._profiles)
        n_today    = len(self._today_sessions) + len(self._active)
        if n_profiles == 0:
            advice = (
                "Nog geen micro-EV laders gedetecteerd. CloudEMS herkent e-bike en scooter "
                "laders automatisch via NILM (50–700 W, meerdere uren)."
            )
        elif n_today > 0:
            advice = (
                f"{n_today} voertuig(en) geladen vandaag ({kwh_today:.2f} kWh, €{cost_today:.2f}). "
                f"Het gezin heeft {n_profiles} voertuig(en) geregistreerd."
            )
        else:
            types = set(p.vehicle_type for p in self._profiles.values())
            type_str = " + ".join(sorted(types))
            advice = (
                f"{n_profiles} micro-EV({type_str}) lader(s) bekend. "
                f"Gemiddeld {weekly_kwh:.1f} kWh/week. "
                "Stel een slimme schakelaar in om te laden op PV-surplus of goedkoopste uur."
            )

        return MicroMobilityData(
            vehicles_today    = len(set(s.device_id for s in self._today_sessions)),
            kwh_today         = round(kwh_today, 3),
            cost_today_eur    = round(cost_today, 2),
            sessions_today    = today_list,
            active_sessions   = active_list,
            vehicle_profiles  = profile_list,
            best_charge_hour  = best_hour,
            best_charge_label = best_label,
            advice            = advice,
            total_sessions    = len(self._sessions),
            total_kwh         = round(sum(s.kwh for s in self._sessions), 1),
            weekly_kwh_avg    = weekly_kwh,
        )

    async def async_maybe_save(self) -> None:
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            await self._store.async_save({
                "sessions": [s.to_dict() for s in self._sessions[-500:]],   # max 500 sessies
            })
            self._dirty     = False
            self._last_save = time.time()
