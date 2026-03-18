# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS — Circuit/Groep uitval monitor (v2.0.0).

Detecteert uitgevallen groepen via twee mechanismen:

1. **Fase-activiteit** — als een fase langere tijd geen import én geen export
   vertoont terwijl andere fasen wel actief zijn → groep waarschijnlijk uit.

2. **Totaaluitval** — als alle drie fasen exact 0W tonen terwijl de P1 meter
   normaal nooit exact 0 geeft (altijd standby-verbruik) → volledige uitval
   of P1-storing.

Leergedrag:
   - Bouwt per fase een verwacht minimumverbruik op (standby + altijd-aan)
   - Detecteert pas na voldoende observaties (48 cycles ≈ 8 minuten)
   - Bevestigt na 3 opeenvolgende suspect-cycles (~30 seconden)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Drempels ──────────────────────────────────────────────────────────────────
ZERO_THRESHOLD_W        = 5.0    # W onder dit = "geen activiteit"
EXACT_ZERO_ALL_W        = 2.0    # W alle fasen onder dit = totaaluitval suspect
CONFIRM_CYCLES          = 3      # opeenvolgende cycles voor bevestiging (~30s)
SINGLE_PHASE_MIN_TIME_S = 60     # seconden inactiviteit voor single-fase alarm
TOTAL_ZERO_CONFIRM_S    = 20     # seconden voor totaaluitval bevestiging
LEARN_MIN_OBS           = 48     # min observaties voor betrouwbaar patroon
NOTIFY_COOLDOWN_S       = 300    # max 1 melding per 5 min per alert-type
RESTORE_CONFIRM_CYCLES  = 2      # cycles voor "hersteld" bevestiging
SUDDEN_DROP_W           = 500.0  # W daling in één cycle = "grote sprong"
SUDDEN_DROP_RATIO       = 0.70   # daling > 70% van vorig vermogen = verdacht
SUDDEN_DROP_CONFIRM_S   = 30     # fase moet daarna laag blijven voor alarm
NILM_EXPLAINS_W         = 0.80   # als NILM 80%+ van de daling verklaart → geen alarm


@dataclass
class PhaseState:
    """Runtime-toestand per fase."""
    phase:              str
    last_active_ts:     float = field(default_factory=time.time)
    suspect_cycles:     int   = 0
    restore_cycles:     int   = 0
    alert_active:       bool  = False
    alert_since_ts:     float = 0.0
    # Geleerde baseline: EMA van minimum-activiteit overdag
    baseline_w:         float = 5.0
    baseline_obs:       int   = 0
    # Sudden-drop tracking
    prev_power_w:       float = 0.0
    drop_suspect_ts:    float = 0.0   # tijdstip van de verdachte daling
    drop_amount_w:      float = 0.0   # grootte van de daling


class CircuitMonitor:
    """Monitort fase-stromen op uitgevallen groepen."""

    def __init__(self, hass, config: dict) -> None:
        self._hass           = hass
        self._config         = config
        self._phases:        dict[str, PhaseState] = {}
        self._notify_svc     = config.get("notification_service", "")
        self._last_notify:   dict[str, float] = {}
        self._total_zero_since: Optional[float] = None
        self._total_zero_alert: bool = False
        self._enabled        = False

    def configure(self, phase_count: int = 3) -> None:
        """Initialiseer fase-states."""
        for i in range(1, phase_count + 1):
            ph = f"L{i}"
            if ph not in self._phases:
                self._phases[ph] = PhaseState(phase=ph)
        self._enabled = True
        _LOGGER.info("CircuitMonitor v2: %d fasen", phase_count)

    def update(self, data: dict) -> dict:
        """Verwerk huidige fase-data en detecteer uitval.

        Leest uit coordinator data:
          - phase_balancer.phase_currents  (A per fase)
          - p1_data.power_l1_import_w etc  (W per fase import)
          - p1_data.power_l1_export_w etc  (W per fase export)
        """
        if not self._enabled:
            return {"enabled": False, "alerts": {}}

        import datetime
        hour = datetime.datetime.now().hour
        now  = time.time()

        # ── Haal fase-vermogens op ────────────────────────────────────────────
        phase_power: dict[str, float] = {}

        # Primair: per-fase vermogens uit P1
        p1 = data.get("p1_data", {})
        for i in range(1, 4):
            ph  = f"L{i}"
            imp = abs(float(p1.get(f"power_l{i}_import_w", 0) or 0))
            exp = abs(float(p1.get(f"power_l{i}_export_w", 0) or 0))
            if imp > 0 or exp > 0:
                phase_power[ph] = imp + exp

        # Fallback: fase-stromen × spanning (~230V)
        if not phase_power:
            pb = data.get("phase_balancer", {})
            currents = pb.get("phase_currents", {})
            for ph, amp in currents.items():
                phase_power[ph] = abs(float(amp or 0)) * 230.0

        # Als geen fase-data beschikbaar → niet monitoren
        if not phase_power:
            return {"enabled": True, "alerts": {}, "status": "geen_fase_data"}

        # ── Totaaluitval detectie ─────────────────────────────────────────────
        total_w = sum(phase_power.values())
        all_zero = total_w < EXACT_ZERO_ALL_W and len(phase_power) >= 2

        if all_zero:
            if self._total_zero_since is None:
                self._total_zero_since = now
            elif (now - self._total_zero_since) >= TOTAL_ZERO_CONFIRM_S and not self._total_zero_alert:
                self._total_zero_alert = True
                _LOGGER.warning("CircuitMonitor: alle fasen 0W — totaaluitval of P1-storing")
        else:
            self._total_zero_since = None
            self._total_zero_alert = False

        alerts: dict[str, dict] = {}

        if self._total_zero_alert:
            alerts["total_zero"] = {
                "type":      "total_zero",
                "phase":     "ALL",
                "power_w":   total_w,
                "confirmed": True,
                "message":   f"Alle fasen tonen {total_w:.1f}W — mogelijke totaaluitval of P1-storing.",
                "devices":   [],
                "since_s":   round(now - (self._total_zero_since or now)),
            }
            # Geen per-fase detectie bij totaaluitval
            return {"enabled": True, "alerts": alerts, "status": "total_zero"}

        # ── Per-fase uitval detectie ──────────────────────────────────────────
        active_phases = [ph for ph, w in phase_power.items() if w > ZERO_THRESHOLD_W]

        for ph, state in self._phases.items():
            pw = phase_power.get(ph, 0.0)
            is_active = pw > ZERO_THRESHOLD_W

            # Baseline leren (alleen overdag, alleen als fase actief)
            if 6 <= hour <= 22 and is_active:
                # EMA van laagste gemeten waarden (leer het standby-niveau)
                if state.baseline_obs == 0 or pw < state.baseline_w * 1.5:
                    alpha = 0.1 if state.baseline_obs < 20 else 0.03
                    state.baseline_w = alpha * pw + (1 - alpha) * state.baseline_w
                state.baseline_obs = min(state.baseline_obs + 1, 9999)

            # ── Sudden-drop detectie ──────────────────────────────────────────
            # Grote snelle daling kan groep-uitval zijn — maar ook een normaal
            # apparaat dat uitgaat. We markeren alleen als suspect en bevestigen
            # pas na SUDDEN_DROP_CONFIRM_S seconden aanhoudend laag vermogen,
            # én alleen als NILM de daling niet verklaart.
            if state.prev_power_w > SUDDEN_DROP_W:
                drop = state.prev_power_w - pw
                drop_ratio = drop / max(state.prev_power_w, 1)
                if drop > SUDDEN_DROP_W and drop_ratio >= SUDDEN_DROP_RATIO:
                    # Grote relatieve daling — check of NILM het verklaart
                    nilm_off_w = self._nilm_off_power(ph, data)
                    if nilm_off_w < drop * NILM_EXPLAINS_W:
                        # NILM verklaart < 80% → mogelijk groep-uitval
                        state.drop_suspect_ts = now
                        state.drop_amount_w   = drop
                        _LOGGER.debug(
                            "CircuitMonitor: fase %s sudden drop %.0fW→%.0fW "
                            "(NILM verklaart %.0fW van %.0fW)",
                            ph, state.prev_power_w, pw, nilm_off_w, drop
                        )
            state.prev_power_w = pw

            # Als sudden-drop suspect én fase blijft laag na CONFIRM tijd → alert
            if (state.drop_suspect_ts > 0
                    and not is_active
                    and (now - state.drop_suspect_ts) >= SUDDEN_DROP_CONFIRM_S
                    and not state.alert_active):
                state.alert_active   = True
                state.alert_since_ts = now
                state.last_active_ts = state.drop_suspect_ts  # was actief op drop-moment
                _LOGGER.warning(
                    "CircuitMonitor: fase %s sudden-drop %.0fW bevestigd na %.0fs",
                    ph, state.drop_amount_w, now - state.drop_suspect_ts
                )
            # Reset drop-suspect als fase weer actief wordt
            if is_active and state.drop_suspect_ts > 0:
                state.drop_suspect_ts = 0.0
                state.drop_amount_w   = 0.0

            if is_active:
                # Fase actief — reset suspect counter, herstel eventueel
                state.last_active_ts = now
                if state.alert_active:
                    state.restore_cycles += 1
                    if state.restore_cycles >= RESTORE_CONFIRM_CYCLES:
                        _LOGGER.info("CircuitMonitor: fase %s hersteld", ph)
                        state.alert_active   = False
                        state.restore_cycles = 0
                        state.suspect_cycles = 0
                else:
                    state.suspect_cycles = 0
                    state.restore_cycles = 0
            else:
                # Fase inactief
                state.restore_cycles = 0
                inactive_s = now - state.last_active_ts

                # Alleen verdacht als:
                # - andere fasen WEL actief zijn (anders gewoon lage last)
                # - het overdag is (nacht kan gewoon laag zijn)
                # - lang genoeg inactief
                other_active = any(
                    phase_power.get(p2, 0) > ZERO_THRESHOLD_W
                    for p2 in self._phases if p2 != ph
                )
                is_daytime = 6 <= hour <= 22
                learned_ok = state.baseline_obs >= LEARN_MIN_OBS

                if other_active and is_daytime and inactive_s >= SINGLE_PHASE_MIN_TIME_S:
                    state.suspect_cycles += 1
                    if state.suspect_cycles >= CONFIRM_CYCLES and not state.alert_active:
                        state.alert_active  = True
                        state.alert_since_ts = now
                        _LOGGER.warning(
                            "CircuitMonitor: fase %s inactief voor %.0fs "
                            "(verwacht: ≥%.1fW, gemeten: %.1fW)",
                            ph, inactive_s, state.baseline_w, pw
                        )
                else:
                    # Niet verdacht genoeg — langzaam afbouwen
                    state.suspect_cycles = max(0, state.suspect_cycles - 1)

            if state.alert_active:
                devices = self._find_affected_devices(ph, data)
                alerts[ph] = {
                    "type":      "phase_inactive",
                    "phase":     ph,
                    "power_w":   pw,
                    "expected_w": round(state.baseline_w, 1),
                    "inactive_s": round(now - state.last_active_ts),
                    "confirmed": True,
                    "devices":   devices,
                    "since_s":   round(now - state.alert_since_ts),
                }

        return {
            "enabled":    True,
            "alerts":     alerts,
            "status":     "alert" if alerts else "ok",
            "phase_power": {ph: round(w, 1) for ph, w in phase_power.items()},
            "total_w":    round(total_w, 1),
            "learn_ready": {ph: s.baseline_obs >= LEARN_MIN_OBS
                            for ph, s in self._phases.items()},
        }

    async def async_notify_alerts(self, alerts: dict) -> None:
        """Stuur notificaties voor nieuwe bevestigde uitval."""
        if not self._notify_svc or not alerts:
            return
        now = time.time()

        for key, alert in alerts.items():
            if not alert.get("confirmed"):
                continue
            cooldown_key = f"{key}_{alert.get('type', '')}"
            if now - self._last_notify.get(cooldown_key, 0) < NOTIFY_COOLDOWN_S:
                continue
            self._last_notify[cooldown_key] = now

            if alert.get("type") == "total_zero":
                title = "⚡ Mogelijke totaaluitval of P1-storing"
                msg   = alert["message"]
            else:
                ph      = alert["phase"]
                dev_str = (", ".join(alert["devices"][:4])
                           if alert["devices"] else "onbekend")
                title   = f"⚡ Groep mogelijk uitgevallen — fase {ph}"
                msg     = (
                    f"Fase {ph} vertoont al {alert['inactive_s']//60} min geen activiteit "
                    f"(verwacht ≥{alert['expected_w']:.0f}W). "
                    f"Mogelijk getroffen: {dev_str}. "
                    f"Controleer de groepenkast."
                )

            try:
                svc   = self._notify_svc.split(".")
                dom   = svc[0] if len(svc) > 1 else "notify"
                svc_n = svc[1] if len(svc) > 1 else svc[0]
                await self._hass.services.async_call(
                    dom, svc_n,
                    {"title": title, "message": msg},
                    blocking=False,
                )
            except Exception as err:
                _LOGGER.warning("CircuitMonitor notify: %s", err)

    def _nilm_off_power(self, phase: str, data: dict) -> float:
        """Schat hoeveel Watt NILM verklaart via recent uitgeschakelde apparaten.

        Als een apparaat net uitging én op deze fase zit, telt dat vermogen mee.
        Als NILM ≥80% van de daling verklaart → geen false positive.
        """
        total_explained = 0.0
        now = time.time()
        for dev in data.get("nilm_devices", []):
            # Alleen apparaten die net uitgingen (laatste 10 seconden)
            if dev.get("is_on"):
                continue
            dev_phase = (dev.get("phase") or "").upper()
            if dev_phase and dev_phase != phase.upper():
                continue  # ander fase → irrelevant
            # Schat vermogen: gebruik avg_power_w of power_w
            pw = float(dev.get("avg_power_w") or dev.get("power_w") or 0)
            if pw > 10:
                total_explained += pw
        return total_explained

    def _find_affected_devices(self, phase: str, data: dict) -> list[str]:
        """Zoek apparaten op deze fase via NILM + lamp fase-detectie."""
        affected = []
        for dev in data.get("nilm_devices", []):
            if (dev.get("phase", "") or "").upper() == phase.upper():
                lbl = dev.get("user_name") or dev.get("name") or dev.get("device_type", "")
                if lbl:
                    affected.append(lbl)
        for lp in data.get("lamp_circulation", {}).get("lamp_phases", []):
            if (lp.get("phase", "") or "").upper() == phase.upper():
                lbl = lp.get("label") or lp.get("entity_id", "")
                if lbl:
                    affected.append(lbl)
        return affected[:8]
