# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. Unauthorized copying, redistribution, or commercial
# use of this file is strictly prohibited. See LICENSE for full terms.

"""
CloudEMS Apparaat Efficiëntie Drift Tracker — v1.0.0

Detecteert wanneer een apparaat meer stroom gaat verbruiken dan historisch
gebruikelijk, wat kan duiden op slijtage, kalkafzetting of een defect.

Methode:
  - Bij elke NILM-detectie: sla het gemeten vermogen op
  - Exponentieel voortschrijdend gemiddelde van vermogen per apparaat
  - Referentiegemiddelde = eerste 20 metingen (stabiele baseline)
  - Alert als huidig gemiddelde > DRIFT_THRESHOLD × referentie

Speciale case — koelkast:
  - Koelkasten zijn cyclisch (compressor aan/uit)
  - Meet ook duty_cycle (fractie van de tijd dat compressor aan is)
  - Hogere duty_cycle = slechtere isolatie of overvolle koelkast

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY     = "cloudems_device_drift_v1"
STORAGE_VERSION = 1

DRIFT_THRESHOLD     = 1.30   # 30% boven referentie → drift warning
ALERT_THRESHOLD     = 1.50   # 50% boven referentie → alert
DUTY_DRIFT_THRESH   = 0.25   # Duty cycle 25% hoger dan referentie → alert (koelkast)
MIN_BASELINE_SAMPLES = 15    # Metingen nodig voor baseline — 15 NILM-detecties = ~1 week normaal gebruik
ALPHA_CURRENT       = 0.10   # EMA voor huidig verbruik
ALPHA_BASELINE_FAST = 0.15   # EMA baseline eerste 7 samples (snel convergeren)
ALPHA_BASELINE_MID  = 0.05   # EMA baseline samples 7-15
ALPHA_BASELINE_SLOW = 0.02   # EMA baseline na freeze (langzame drift-correctie)
SAVE_INTERVAL_S          = 600
# Adaptive drift retention:
# - Apparaat heeft drift-alert → 4 uur (snel opruimen na herstel)
# - Baseline nog niet bevroren → 6 uur (apparaat nooit stabiel gezien)
# - Baseline bevroren, geen drift → 48 uur (actief apparaat, bewaren)
# Verlaagd t.o.v. vorige versie (was 8h / 72h) om stale profielen
# van kortstondige apparaten (gereedschap, keuken) sneller op te ruimen.
DRIFT_RETENTION_ALERT_H    =  4   # uur bewaren na drift-alert
DRIFT_RETENTION_LEARNING_H =  6   # uur bewaren als baseline nog niet klaar
DRIFT_RETENTION_NORMAL_H   = 48   # uur bewaren voor gezonde profielen

# Apparaattypen met van nature hoog variabel vermogen — hogere drempel nodig.
# power_tool staat NIET meer hier — het staat in DRIFT_SKIP_TYPES (zie hieronder).
HIGH_VARIANCE_TYPES = {
    "medical",      # CPAP (druk varieert per nacht)
    "gaming",       # gaming PC (idle vs full load)
}
HIGH_VARIANCE_ALERT_THRESHOLD = 2.00   # 100% boven referentie voor variabele apparaten
HIGH_VARIANCE_DRIFT_THRESHOLD = 1.60   # 60% boven referentie voor variabele apparaten

# Minimum absolute verschil in Watt — verhoogd van 50 naar 80W
# om ruis bij kleinere apparaten verder te reduceren.
MIN_ABSOLUTE_DRIFT_W = 80.0

# ── Apparaattypen die NOOIT drift-tracking krijgen ────────────────────────────
# Drift-tracking is alleen zinvol voor apparaten met een stabiel, herhalend
# vermogensprofiel dat over weken/maanden verslechtert (motor slijt, kalk bouwt op,
# filter verstopt). Apparaten met structureel variabel vermogen geven valse alerts.
#
# power_tool (cirkelzaag etc.) is hier expliciet toegevoegd omdat:
#   1. Vermogen hangt volledig af van belasting (dun/dik hout, aanzet-snelheid)
#   2. Baseline van 15 willekeurige zaagbewegingen is statistisch waardeloos
#   3. Slijtage van handgereedschap is niet zichtbaar in P1-data
#   4. Resultaat zonder skip: structurele valse alerts, ook midden in de nacht
#      terwijl het gereedschap niet in gebruik is (oude baseline blijft 72 uur)
DRIFT_SKIP_TYPES = {
    # Energieopwekking / -opslag
    "solar",       # PV-omvormer — productie varieert per seizoen/dag
    "inverter",    # AC-omvormer / PV-systeem
    "pv",          # Generieke PV-sensor
    "battery",     # Thuisbatterij — laad/ontlaad vermogen varieert van nature
    "ev_charger",  # EV-lader — wisselend laden (5-11 kW afhankelijk van auto)
    # Gereedschap & hobbyapparatuur
    "power_tool",  # cirkelzaag, tafelzaag, boor, slijper, lasser, compressor
    "garden",      # grasmaaier, heggeschaar — seizoensgebonden, sterk variabel
    # Overig variabel
    "lighting",    # LED-dimmer — verbruik varieert met dimstand
    # Keukenapparaten — vermogen hangt af van hoeveelheid water/voedsel, starttemperatuur
    # Koffiezetter op koude dag vs warme dag = 30% verschil, geen defect
    "kitchen",     # koffiezetter, waterkoker, magnetron, wafelijzer, mixer
}

# Label/entiteit-fragmenten — extra vangnet bij verkeerde device_type classificatie.
DRIFT_SKIP_LABEL_KEYWORDS = (
    # Energie
    "pv", "solar", "omvormer", "inverter",
    "growatt", "goodwe", "solaredge", "fronius", "enphase", "sma ",
    "output power", "energieproductie", "production",
    "battery", "batterij", "soc", "grid export", "grid import",
    "electricity meter",
    # Gereedschap
    "zaag", "saw", "drill", "boor", "slijp", "grinder", "welder", "lasser",
    "compressor", "cnc", "laser cutter", "router", "3d print",
    # Tuin
    "maaier", "mower", "hegge", "hedge",
)


@dataclass
class DeviceDriftProfile:
    """Vermogensprofiel per NILM-apparaat voor drift-detectie."""
    device_id:      str
    device_type:    str
    label:          str
    baseline_w:     float   = 0.0    # Referentie-gemiddelde (eerste weken)
    current_avg_w:  float   = 0.0    # Huidig voortschrijdend gemiddelde
    samples_total:  int     = 0      # Totaal aantal NILM-detecties
    baseline_frozen: bool   = False  # Baseline vastgezet na MIN_BASELINE_SAMPLES
    baseline_max_w:  float  = 0.0    # Hoogste geziene waarde tijdens baseline — voor variatie-bewuste drempel
    # Duty-cycle bijhouden (voor cyclische apparaten zoals koelkasten)
    duty_cycle_ref: float   = 0.0    # Referentie duty-cycle
    duty_cycle_now: float   = 0.0    # Huidige duty-cycle
    duty_samples:   int     = 0
    # Tijdstempel van de eerste/laatste drift
    first_drift_date: str   = ""
    last_updated:     str   = ""

    @property
    def drift_ratio(self) -> float:
        if self.baseline_w <= 0:
            return 1.0
        return self.current_avg_w / self.baseline_w

    @property
    def drift_pct(self) -> float:
        return round((self.drift_ratio - 1.0) * 100, 1)

    @property
    def _alert_threshold(self) -> float:
        return HIGH_VARIANCE_ALERT_THRESHOLD if self.device_type in HIGH_VARIANCE_TYPES else ALERT_THRESHOLD

    @property
    def _drift_threshold(self) -> float:
        return HIGH_VARIANCE_DRIFT_THRESHOLD if self.device_type in HIGH_VARIANCE_TYPES else DRIFT_THRESHOLD

    @property
    def _skip_drift(self) -> bool:
        """Sla drift-tracking over voor apparaattypen met van nature variabele productie."""
        if self.device_type in DRIFT_SKIP_TYPES:
            return True
        label_lower = self.label.lower()
        return any(kw in label_lower for kw in DRIFT_SKIP_LABEL_KEYWORDS)

    @property
    def _absolute_drift_w(self) -> float:
        return abs(self.current_avg_w - self.baseline_w)

    @property
    def _within_seen_range(self) -> bool:
        """True als huidig gemiddelde binnen het eerder geziene bereik valt.
        Voorkomt false positives bij apparaten met variabel vermogen:
        koffiezetter die soms 1400W trekt was al eens 1400W → geen drift.
        5% marge voor ruis."""
        if self.baseline_max_w <= 0:
            return False
        return self.current_avg_w <= self.baseline_max_w * 1.05

    @property
    def has_alert(self) -> bool:
        return (
            not self._skip_drift
            and self.baseline_frozen
            and self.drift_ratio >= self._alert_threshold
            and self._absolute_drift_w >= MIN_ABSOLUTE_DRIFT_W
            and not self._within_seen_range   # alleen alert als BUITEN eerder gezien bereik
        )

    @property
    def has_warning(self) -> bool:
        return (
            not self._skip_drift
            and self.baseline_frozen
            and self.drift_ratio >= self._drift_threshold
            and self._absolute_drift_w >= MIN_ABSOLUTE_DRIFT_W
            and not self._within_seen_range   # alleen warning als BUITEN eerder gezien bereik
        )


@dataclass
class DriftStatus:
    """Output voor één apparaat."""
    device_id:  str
    label:      str
    baseline_w: float
    current_w:  float
    drift_pct:  float
    level:      str    # "ok" | "warning" | "alert"
    message:    str


@dataclass
class DriftReport:
    """Globaal rapport van alle apparaatdrift."""
    devices: list[DriftStatus]
    any_alert: bool
    any_warning: bool
    summary: str


class DeviceDriftTracker:
    """
    Detecteert efficiëntiedrift bij NILM-apparaten.

    Gebruik vanuit coordinator:
        tracker.record_detection(device_id, device_type, label, power_w)
        tracker.record_duty_cycle(device_id, duty_cycle)
        report = tracker.get_report()
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store  = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._profiles: dict[str, DeviceDriftProfile] = {}
        self._dirty    = False
        self._last_save = 0.0

    async def async_setup(self) -> None:
        saved: dict = await self._store.async_load() or {}
        for did, d in saved.items():
            self._profiles[did] = DeviceDriftProfile(
                device_id       = d.get("device_id", did),
                device_type     = d.get("device_type", "unknown"),
                label           = d.get("label", did),
                baseline_w      = float(d.get("baseline_w", 0)),
                current_avg_w   = float(d.get("current_avg_w", 0)),
                samples_total   = int(d.get("samples_total", 0)),
                baseline_frozen = bool(d.get("baseline_frozen", False)),
                baseline_max_w  = float(d.get("baseline_max_w", 0)),
                duty_cycle_ref  = float(d.get("duty_cycle_ref", 0)),
                duty_cycle_now  = float(d.get("duty_cycle_now", 0)),
                duty_samples    = int(d.get("duty_samples", 0)),
                first_drift_date= d.get("first_drift_date", ""),
                last_updated    = d.get("last_updated", ""),
            )
        # Verwijder PV/batterij-profielen die per ongeluk opgeslagen zijn
        skip_ids = [did for did, p in self._profiles.items() if p._skip_drift]
        for did in skip_ids:
            del self._profiles[did]
        if skip_ids:
            _LOGGER.info(
                "DeviceDriftTracker: %d PV/batterij-profielen verwijderd bij opstarten",
                len(skip_ids),
            )
        self._prune_stale_profiles()
        _LOGGER.info("DeviceDriftTracker: %d profielen geladen", len(self._profiles))

    def record_detection(
        self,
        device_id: str,
        device_type: str,
        label: str,
        power_w: float,
    ) -> None:
        """Registreer een NILM-detectie met actueel vermogen."""
        if power_w <= 0:
            return

        # Sla PV/batterij-apparaten over op basis van device_type EN label
        _label_lower = label.lower()
        if device_type in DRIFT_SKIP_TYPES or any(kw in _label_lower for kw in DRIFT_SKIP_LABEL_KEYWORDS):
            return

        if device_id not in self._profiles:
            self._profiles[device_id] = DeviceDriftProfile(
                device_id=device_id, device_type=device_type, label=label
            )

        profile = self._profiles[device_id]
        profile.label       = label
        profile.device_type = device_type

        if not profile.baseline_frozen:
            # Adaptive EMA: fast at first, slows as baseline stabilises
            n = profile.samples_total
            alpha_bl = ALPHA_BASELINE_FAST if n < 7 else (ALPHA_BASELINE_MID if n < 15 else ALPHA_BASELINE_SLOW)
            if n == 0:
                profile.baseline_w    = power_w
                profile.current_avg_w = power_w
                profile.baseline_max_w = power_w
            else:
                profile.baseline_w    = alpha_bl * power_w + (1 - alpha_bl) * profile.baseline_w
                profile.current_avg_w = ALPHA_CURRENT * power_w + (1 - ALPHA_CURRENT) * profile.current_avg_w
                profile.baseline_max_w = max(profile.baseline_max_w, power_w)  # alleen tijdens leren

            bar = '#' * (n + 1) + '.' * max(0, MIN_BASELINE_SAMPLES - n - 1)
            _LOGGER.info(
                "DeviceDrift '%s': baseline leren %d/%d [%s] — huidig gemiddelde %.0f W",
                label, n + 1, MIN_BASELINE_SAMPLES, bar, profile.baseline_w,
            )

            if profile.samples_total + 1 >= MIN_BASELINE_SAMPLES:
                profile.baseline_frozen = True
                _LOGGER.info(
                    "DeviceDrift '%s': ✅ baseline vastgezet op %.0f W (na %d metingen)",
                    label, profile.baseline_w, profile.samples_total + 1,
                )
        else:
            # Update lopend gemiddelde (sneller dan baseline)
            # baseline_max_w NIET meer bijwerken na freeze — anders groeit de drempel mee met drift
            profile.current_avg_w = ALPHA_CURRENT * power_w + (1 - ALPHA_CURRENT) * profile.current_avg_w

            # Log eerste drift-moment
            if profile.has_warning and not profile.first_drift_date:
                profile.first_drift_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                _LOGGER.warning(
                    "DeviceDrift '%s': drift gedetecteerd! %.0f W → %.0f W (+%.1f%%)",
                    label, profile.baseline_w, profile.current_avg_w, profile.drift_pct,
                )

        profile.samples_total += 1
        profile.last_updated   = datetime.now(timezone.utc).isoformat()
        self._dirty = True

    def record_duty_cycle(self, device_id: str, duty_cycle: float) -> None:
        """Sla duty cycle op (voor cyclische apparaten zoals koelkast)."""
        if device_id not in self._profiles:
            return
        profile = self._profiles[device_id]

        if profile.duty_samples == 0:
            profile.duty_cycle_ref = duty_cycle
            profile.duty_cycle_now = duty_cycle
        elif not profile.baseline_frozen:
            dc_alpha = 0.10 if profile.duty_samples < 5 else 0.03
            profile.duty_cycle_ref = dc_alpha * duty_cycle + (1 - dc_alpha) * profile.duty_cycle_ref
            profile.duty_cycle_now = duty_cycle
        else:
            profile.duty_cycle_now = 0.05 * duty_cycle + 0.95 * profile.duty_cycle_now

        profile.duty_samples += 1
        self._dirty = True

    def get_report(self) -> DriftReport:
        """Genereer een driftrapport voor alle apparaten."""
        statuses: list[DriftStatus] = []

        for profile in self._profiles.values():
            if not profile.baseline_frozen or profile.baseline_w <= 0:
                continue   # Nog geen baseline

            level   = "ok"
            message = f"{profile.label} verbruikt gemiddeld {profile.current_avg_w:.0f} W — normaal."

            if profile.has_alert:
                level = "alert"
                message = (
                    f"{profile.label} verbruikt {profile.drift_pct:.0f}% meer dan normaal "
                    f"({profile.current_avg_w:.0f} W vs baseline {profile.baseline_w:.0f} W). "
                    "Mogelijke oorzaak: slijtage, kalkafzetting of defect. Controleer het apparaat."
                )
            elif profile.has_warning:
                level = "warning"
                message = (
                    f"{profile.label} verbruikt {profile.drift_pct:.0f}% meer dan bij de start "
                    f"({profile.current_avg_w:.0f} W vs {profile.baseline_w:.0f} W). "
                    "Let op mogelijke efficiency-daling."
                )

            # Duty cycle check voor koelkast
            if (profile.device_type == "refrigerator"
                    and profile.duty_cycle_ref > 0
                    and profile.duty_samples >= 20):
                duty_drift = (profile.duty_cycle_now - profile.duty_cycle_ref) / max(profile.duty_cycle_ref, 0.01)
                if duty_drift > DUTY_DRIFT_THRESH:
                    level = max(level, "warning", key=["ok", "warning", "alert"].index)
                    pct   = round(duty_drift * 100)
                    message += (
                        f" Bovendien is de compressor-duty-cycle {pct:.0f}% hoger dan normaal, "
                        "wat kan wijzen op een slechte afdichting of te volle koelkast."
                    )

            statuses.append(DriftStatus(
                device_id   = profile.device_id,
                label       = profile.label,
                baseline_w  = round(profile.baseline_w),
                current_w   = round(profile.current_avg_w),
                drift_pct   = profile.drift_pct,
                level       = level,
                message     = message,
            ))

        any_alert   = any(s.level == "alert" for s in statuses)
        any_warning = any(s.level in ("alert", "warning") for s in statuses)

        if not statuses:
            summary = "Nog geen apparaatprofielen beschikbaar."
        elif any_alert:
            alerts = [s for s in statuses if s.level == "alert"]
            summary = "; ".join(s.message for s in alerts)
        elif any_warning:
            warnings = [s for s in statuses if s.level == "warning"]
            summary = "; ".join(s.message for s in warnings)
        else:
            summary = f"Alle {len(statuses)} apparaten presteren normaal."

        return DriftReport(
            devices     = statuses,
            any_alert   = any_alert,
            any_warning = any_warning,
            summary     = summary,
        )

    def _prune_stale_profiles(self) -> int:
        """Verwijder profielen adaptief:
        - Alert actief   → 4 uur
        - Baseline leren → 8 uur
        - Normaal/gezond → 72 uur
        """
        now = datetime.now(timezone.utc)
        stale = []
        for did, p in list(self._profiles.items()):
            if not p.last_updated:
                stale.append(did)
                continue
            try:
                last = datetime.fromisoformat(p.last_updated).replace(tzinfo=timezone.utc)
            except ValueError:
                stale.append(did)
                continue
            age_h = (now - last).total_seconds() / 3600
            max_h = (
                DRIFT_RETENTION_ALERT_H    if p.has_alert else
                DRIFT_RETENTION_LEARNING_H if not p.baseline_frozen else
                DRIFT_RETENTION_NORMAL_H
            )
            if age_h > max_h:
                stale.append(did)
        for did in stale:
            del self._profiles[did]
        if stale:
            _LOGGER.info("DeviceDrift: %d verouderde profielen verwijderd (adaptief)", len(stale))
        return len(stale)

    async def async_clear_all(self) -> int:
        """Verwijder alle drift-profielen en wis de opgeslagen data.
        Wordt aangeroepen bij NILM cleanup scope='full' voor een schone start.
        Geeft het aantal verwijderde profielen terug.
        """
        count = len(self._profiles)
        self._profiles.clear()
        await self._store.async_save({})
        _LOGGER.info("DeviceDrift: %d profielen gewist (schone start)", count)
        return count

    async def async_maybe_save(self) -> None:
        # Prune stale profiles periodically (max 1x per save cycle)
        self._prune_stale_profiles()
        if self._dirty and (time.time() - self._last_save) >= SAVE_INTERVAL_S:
            data = {}
            for did, p in self._profiles.items():
                data[did] = {
                    "device_id":       p.device_id,
                    "device_type":     p.device_type,
                    "label":           p.label,
                    "baseline_w":      round(p.baseline_w, 2),
                    "current_avg_w":   round(p.current_avg_w, 2),
                    "samples_total":   p.samples_total,
                    "baseline_frozen": p.baseline_frozen,
                    "baseline_max_w":  round(p.baseline_max_w, 2),
                    "duty_cycle_ref":  round(p.duty_cycle_ref, 4),
                    "duty_cycle_now":  round(p.duty_cycle_now, 4),
                    "duty_samples":    p.duty_samples,
                    "first_drift_date":p.first_drift_date,
                    "last_updated":    p.last_updated,
                }
            await self._store.async_save(data)
            self._dirty     = False
            self._last_save = time.time()
