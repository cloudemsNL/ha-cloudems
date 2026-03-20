# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
"""
appliance_health.py — v4.6.533

Twee modules voor apparaatgezondheid:

1. ApplianceDegradationMonitor
   Vergelijkt geleerd vermogensprofiel per apparaat met huidig gedrag.
   Detecteert degradatie: wasmachine die minder trekt dan vroeger.

2. StandbyDriftTracker
   Monitort of standby-verbruik van bevestigde apparaten over tijd omhoogkruipt.
   Router die van 8W naar 14W gaat over 6 maanden → hardware probleem.

Beide hebben cloud-sync: geanonimiseerde type-statistieken worden gedeeld
zodat andere installaties betere priors krijgen voor dezelfde apparaattypen.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cloud_sync_mixin import CloudSyncMixin

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_DEG     = "cloudems_appliance_degradation_v1"
STORAGE_KEY_STANDBY = "cloudems_standby_drift_v1"
STORAGE_VERSION     = 1

EMA_ALPHA_FAST  = 0.15   # snel leren in het begin
EMA_ALPHA_SLOW  = 0.05   # stabiel na veel data
MIN_SAMPLES     = 20
SAVE_INTERVAL   = 60

# Degradatiedrempels
DEG_WARN_FRAC   = 0.12   # >12% lager dan geleerd → waarschuwing
DEG_ALERT_FRAC  = 0.25   # >25% lager → alert

# Standby drift drempels
DRIFT_WARN_W    = 5.0    # >5W toename → waarschuwing
DRIFT_ALERT_W   = 15.0   # >15W toename → alert
DRIFT_WARN_FRAC = 0.30   # >30% toename → waarschuwing
DRIFT_WEEKS_MIN = 4      # minimaal 4 weken data voor uitspraak


# ─────────────────────────────────────────────────────────────────────────────
# ApplianceDegradationMonitor
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ApplianceProfile:
    """Geleerd vermogensprofiel van één apparaat."""
    device_type:     str
    ema_power_w:     float = 0.0
    baseline_power_w: float = 0.0    # gemiddelde van eerste MIN_SAMPLES cycli
    sample_count:    int   = 0
    baseline_locked: bool  = False   # True als baseline stabiel is
    classification:  str   = "learning"
    confidence:      float = 0.0
    last_seen_ts:    float = 0.0
    degradation_pct: float = 0.0

    def alpha(self) -> float:
        return EMA_ALPHA_SLOW if self.sample_count > 50 else EMA_ALPHA_FAST

    def to_dict(self) -> dict:
        return {
            "type":      self.device_type,
            "ema_w":     round(self.ema_power_w, 1),
            "base_w":    round(self.baseline_power_w, 1),
            "samples":   self.sample_count,
            "locked":    self.baseline_locked,
            "class":     self.classification,
            "conf":      round(self.confidence, 3),
            "deg_pct":   round(self.degradation_pct, 1),
        }

    def from_dict(self, d: dict) -> None:
        self.device_type      = d.get("type", "unknown")
        self.ema_power_w      = float(d.get("ema_w", 0.0))
        self.baseline_power_w = float(d.get("base_w", 0.0))
        self.sample_count     = int(d.get("samples", 0))
        self.baseline_locked  = bool(d.get("locked", False))
        self.classification   = d.get("class", "learning")
        self.confidence       = float(d.get("conf", 0.0))
        self.degradation_pct  = float(d.get("deg_pct", 0.0))


class ApplianceDegradationMonitor(CloudSyncMixin):
    """
    Leert het vermogensprofiel van apparaten en detecteert degradatie.
    Cloud-sync: deelt geanonimiseerde type-profielen.
    """

    _cloud_module_name = "appliance_degradation"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._profiles: Dict[str, ApplianceProfile] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_DEG)
        data = await self._store.async_load()
        if data:
            for dev_id, d in data.items():
                p = ApplianceProfile(device_type=d.get("type", "unknown"))
                p.from_dict(d)
                self._profiles[dev_id] = p

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {k: v.to_dict() for k, v in self._profiles.items()}
            )
            self._dirty_count = 0

    def observe_cycle(
        self,
        device_type: str,
        device_id:   str,
        power_w:     float,
    ) -> Optional[dict]:
        """
        Verwerk één apparaatcyclus (gemiddeld vermogen tijdens gebruik).
        Geeft degradatie-info terug als beschikbaar.
        """
        if power_w < 50:
            return None

        if device_id not in self._profiles:
            self._profiles[device_id] = ApplianceProfile(device_type=device_type)
        p = self._profiles[device_id]

        alpha = p.alpha()
        p.ema_power_w = alpha * power_w + (1 - alpha) * p.ema_power_w if p.sample_count > 0 else power_w
        p.sample_count += 1
        p.last_seen_ts = time.time()
        self._dirty_count += 1

        # Vergrendel baseline na genoeg data
        # v4.6.545: ook minimaal 30 minuten na start wachten — voorkomt
        # dat een corrupt baseline wordt vergrendeld op herstart-artefacten
        time_since_start = time.time() - self._start_ts
        if not p.baseline_locked and p.sample_count >= MIN_SAMPLES and time_since_start > 1800:
            p.baseline_power_w = p.ema_power_w
            p.baseline_locked  = True
            _LOGGER.info(
                "ApplianceDegradation: baseline vergrendeld voor %s (%s) = %.0fW",
                device_type, device_id[:20], p.baseline_power_w,
            )

        if not p.baseline_locked or p.baseline_power_w <= 0:
            return None

        # Bereken degradatie
        diff_w = p.baseline_power_w - p.ema_power_w
        deg_pct = diff_w / p.baseline_power_w * 100
        p.degradation_pct = max(0.0, deg_pct)

        old_class = p.classification
        if deg_pct > DEG_ALERT_FRAC * 100:
            p.classification = "degraded"
            p.confidence     = min(0.90, deg_pct / 50)
        elif deg_pct > DEG_WARN_FRAC * 100:
            p.classification = "degrading"
            p.confidence     = min(0.75, deg_pct / 30)
        else:
            p.classification = "ok"
            p.confidence     = min(0.99, 1.0 - deg_pct / (DEG_WARN_FRAC * 100))

        if p.classification != old_class and p.classification != "ok":
            self._emit_hint(device_type, device_id, p)
            self._log(device_type, device_id, p)

        return {
            "classification":  p.classification,
            "baseline_w":      round(p.baseline_power_w, 1),
            "current_ema_w":   round(p.ema_power_w, 1),
            "degradation_pct": round(deg_pct, 1),
            "confidence":      round(p.confidence, 3),
        }

    def _emit_hint(self, device_type: str, device_id: str, p: ApplianceProfile) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"appliance_degradation_{device_id[:40].replace('.','_')}",
                title      = f"Apparaat-degradatie: {device_type}",
                message    = (
                    f"Het apparaat '{device_type}' trekt nu gemiddeld {p.ema_power_w:.0f}W, "
                    f"maar de geleerde baseline was {p.baseline_power_w:.0f}W "
                    f"({p.degradation_pct:.0f}% lager). "
                    f"Mogelijke oorzaken: verwarmingselement aan het degraderen, "
                    f"kalkafzetting, of sensor-probleem."
                ),
                action     = f"Controleer apparaat '{device_type}'",
                confidence = p.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("ApplianceDegradation hint fout: %s", _e)

    def _log(self, device_type: str, device_id: str, p: ApplianceProfile) -> None:
        msg = (
            f"ApplianceDegradationMonitor: {device_type} ({device_id[:20]}) "
            f"→ {p.classification} ({p.degradation_pct:.1f}% degradatie)"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "appliance_degradation",
                    action   = p.classification,
                    reason   = device_type,
                    message  = msg,
                    extra    = {
                        "device_type":    device_type,
                        "baseline_w":     round(p.baseline_power_w, 1),
                        "current_w":      round(p.ema_power_w, 1),
                        "degradation_pct": round(p.degradation_pct, 1),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        """Cloud-sync: stuur type-gemiddelden, geen device-IDs."""
        type_stats: Dict[str, list] = {}
        for p in self._profiles.values():
            if p.baseline_locked:
                type_stats.setdefault(p.device_type, []).append(p.baseline_power_w)
        return {
            t: {
                "avg_baseline_w": self._round_for_cloud(sum(ws) / len(ws)),
                "count":          len(ws),
            }
            for t, ws in type_stats.items()
        }

    def _apply_prior(self, data: dict) -> None:
        """Verwerk cloud-prior: gebruik type-gemiddelden als startbaseline."""
        for dev_id, p in self._profiles.items():
            if not p.baseline_locked and p.device_type in data:
                prior_w = data[p.device_type].get("avg_baseline_w", 0)
                if prior_w > 50 and p.sample_count < MIN_SAMPLES // 2:
                    p.ema_power_w = prior_w
                    _LOGGER.debug(
                        "ApplianceDegradation: cloud prior voor %s = %.0fW",
                        p.device_type, prior_w,
                    )

    def get_diagnostics(self) -> dict:
        return {k: v.to_dict() for k, v in self._profiles.items()}


# ─────────────────────────────────────────────────────────────────────────────
# StandbyDriftTracker
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StandbyProfile:
    """Standby-vermogen van één apparaat over tijd."""
    device_type:   str
    device_name:   str = ""   # alleen lokaal, niet naar cloud
    ema_standby_w: float = 0.0
    baseline_w:    float = 0.0
    baseline_ts:   float = 0.0
    sample_count:  int   = 0
    baseline_locked: bool = False
    classification: str  = "learning"
    confidence:    float = 0.0
    drift_w:       float = 0.0
    drift_pct:     float = 0.0

    def to_dict(self) -> dict:
        return {
            "type":     self.device_type,
            "ema_w":    round(self.ema_standby_w, 2),
            "base_w":   round(self.baseline_w, 2),
            "base_ts":  round(self.baseline_ts, 0),
            "samples":  self.sample_count,
            "locked":   self.baseline_locked,
            "class":    self.classification,
            "conf":     round(self.confidence, 3),
            "drift_w":  round(self.drift_w, 2),
            "drift_pct": round(self.drift_pct, 1),
        }

    def from_dict(self, d: dict) -> None:
        self.device_type    = d.get("type", "unknown")
        self.ema_standby_w  = float(d.get("ema_w", 0.0))
        self.baseline_w     = float(d.get("base_w", 0.0))
        self.baseline_ts    = float(d.get("base_ts", 0.0))
        self.sample_count   = int(d.get("samples", 0))
        self.baseline_locked = bool(d.get("locked", False))
        self.classification = d.get("class", "learning")
        self.confidence     = float(d.get("conf", 0.0))
        self.drift_w        = float(d.get("drift_w", 0.0))
        self.drift_pct      = float(d.get("drift_pct", 0.0))


class StandbyDriftTracker(CloudSyncMixin):
    """
    Monitort of standby-verbruik van bevestigde apparaten omhoogkruipt over tijd.
    Cloud-sync: deelt geanonimiseerde type-statistieken.
    """

    _cloud_module_name = "standby_drift"

    def __init__(self, hass, hint_engine=None) -> None:
        self._hass   = hass
        self._hint_engine = hint_engine
        self._decisions_history = None
        self._start_ts = time.time()
        self._profiles: Dict[str, StandbyProfile] = {}
        self._store = None
        self._dirty_count = 0

    def set_decisions_history(self, dh) -> None:
        self._decisions_history = dh

    async def async_setup(self) -> None:
        from homeassistant.helpers.storage import Store
        self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY_STANDBY)
        data = await self._store.async_load()
        if data:
            for dev_id, d in data.items():
                p = StandbyProfile(device_type=d.get("type", "unknown"))
                p.from_dict(d)
                self._profiles[dev_id] = p

    async def async_maybe_save(self) -> None:
        if self._dirty_count >= SAVE_INTERVAL and self._store:
            await self._store.async_save(
                {k: v.to_dict() for k, v in self._profiles.items()}
            )
            self._dirty_count = 0

    def observe_standby(
        self,
        device_type: str,
        device_id:   str,
        standby_w:   float,
    ) -> Optional[dict]:
        """
        Verwerk standby-meting voor één apparaat.
        Aanroepen als apparaat 'uit' is maar nog stroom trekt.
        """
        if standby_w < 0.1 or standby_w > 200:
            return None

        if device_id not in self._profiles:
            self._profiles[device_id] = StandbyProfile(device_type=device_type)
        p = self._profiles[device_id]

        alpha = EMA_ALPHA_SLOW if p.sample_count > 100 else EMA_ALPHA_FAST
        p.ema_standby_w = alpha * standby_w + (1 - alpha) * p.ema_standby_w if p.sample_count > 0 else standby_w
        p.sample_count += 1
        self._dirty_count += 1

        # Vergrendel baseline na voldoende data
        # v4.6.545: ook minimaal 30 minuten na start wachten
        now = time.time()
        min_samples_needed = MIN_SAMPLES
        time_since_start = now - self._start_ts
        if not p.baseline_locked and p.sample_count >= min_samples_needed and time_since_start > 1800:
            p.baseline_w    = p.ema_standby_w
            p.baseline_ts   = now
            p.baseline_locked = True
            _LOGGER.info(
                "StandbyDrift: baseline vergrendeld voor %s = %.2fW",
                device_type, p.baseline_w,
            )

        if not p.baseline_locked or p.baseline_w <= 0:
            return None

        # Controleer tijdvenster — minimaal DRIFT_WEEKS_MIN weken
        weeks_elapsed = (now - p.baseline_ts) / (7 * 86400)
        if weeks_elapsed < DRIFT_WEEKS_MIN:
            return None

        drift_w   = p.ema_standby_w - p.baseline_w
        drift_pct = drift_w / p.baseline_w * 100 if p.baseline_w > 0 else 0
        p.drift_w   = drift_w
        p.drift_pct = drift_pct

        old_class = p.classification
        if drift_w > DRIFT_ALERT_W or drift_pct > 50:
            p.classification = "significant_drift"
            p.confidence     = min(0.90, drift_w / DRIFT_ALERT_W * 0.7 + drift_pct / 100 * 0.3)
        elif drift_w > DRIFT_WARN_W or drift_pct > DRIFT_WARN_FRAC * 100:
            p.classification = "minor_drift"
            p.confidence     = min(0.75, drift_w / DRIFT_WARN_W * 0.5)
        else:
            p.classification = "stable"
            p.confidence     = 0.85

        if p.classification != old_class and p.classification != "stable":
            self._emit_hint(device_type, device_id, p, weeks_elapsed)
            self._log(device_type, device_id, p)

        return {
            "classification": p.classification,
            "baseline_w":     round(p.baseline_w, 2),
            "current_w":      round(p.ema_standby_w, 2),
            "drift_w":        round(drift_w, 2),
            "drift_pct":      round(drift_pct, 1),
            "weeks_elapsed":  round(weeks_elapsed, 1),
        }

    def _emit_hint(
        self,
        device_type: str,
        device_id: str,
        p: StandbyProfile,
        weeks: float,
    ) -> None:
        if not self._hint_engine:
            return
        try:
            self._hint_engine._emit_hint(
                hint_id    = f"standby_drift_{device_id[:40].replace('.','_')}",
                title      = f"Standby-verbruik gestegen: {device_type}",
                message    = (
                    f"Het standby-verbruik van '{device_type}' is gestegen van "
                    f"{p.baseline_w:.1f}W naar {p.ema_standby_w:.1f}W "
                    f"(+{p.drift_w:.1f}W in {weeks:.0f} weken). "
                    f"Mogelijke oorzaken: slijtage, defecte condensatoren, "
                    f"of een achtergrondproces dat meer stroom vraagt."
                ),
                action     = f"Controleer apparaat '{device_type}' op hardwareproblemen",
                confidence = p.confidence,
            )
        except Exception as _e:
            _LOGGER.debug("StandbyDrift hint fout: %s", _e)

    def _log(self, device_type: str, device_id: str, p: StandbyProfile) -> None:
        msg = (
            f"StandbyDriftTracker: {device_type} → {p.classification} "
            f"(drift +{p.drift_w:.1f}W, {p.drift_pct:.0f}%)"
        )
        _LOGGER.warning(msg)
        if self._decisions_history:
            try:
                self._decisions_history.add(
                    category = "standby_drift",
                    action   = p.classification,
                    reason   = device_type,
                    message  = msg,
                    extra    = {
                        "device_type": device_type,
                        "baseline_w":  round(p.baseline_w, 2),
                        "current_w":   round(p.ema_standby_w, 2),
                        "drift_w":     round(p.drift_w, 2),
                    },
                )
            except Exception:
                pass

    def _get_learned_data(self) -> dict:
        type_stats: Dict[str, list] = {}
        for p in self._profiles.values():
            if p.baseline_locked:
                type_stats.setdefault(p.device_type, []).append(p.baseline_w)
        return {
            t: {
                "avg_standby_w": self._round_for_cloud(sum(ws) / len(ws)),
                "count":         len(ws),
            }
            for t, ws in type_stats.items()
        }

    def _apply_prior(self, data: dict) -> None:
        for dev_id, p in self._profiles.items():
            if not p.baseline_locked and p.device_type in data:
                prior_w = data[p.device_type].get("avg_standby_w", 0)
                if 0.5 < prior_w < 200 and p.sample_count < MIN_SAMPLES // 2:
                    p.ema_standby_w = prior_w

    def get_diagnostics(self) -> dict:
        return {k: v.to_dict() for k, v in self._profiles.items()}
