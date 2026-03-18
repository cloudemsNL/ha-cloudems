# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 CloudEMS (https://cloudems.eu)
# All rights reserved. See LICENSE for full terms.
"""CloudEMS — Generator & ATS/MTS manager (v1.0.0).

Beheert noodstroom-scenario's:
  - Automatische ATS: leest status-entiteit, reageert automatisch
  - Handmatige MTS:   detecteert netuitval, stuurt melding aan gebruiker
  - Auto-start:       stuurt puls naar generator-startschakelaar met verificatie
  - Lastbegrenzing:   beperkt zware lasten tot generator-capaciteit
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Drempels
GRID_LOST_THRESHOLD_W  = 10.0    # Net beschouwd als weg als import+export < dit
GRID_LOST_CONFIRM_S    = 15.0    # Seconden voor netuitval bevestigd is
AUTOSTART_TIMEOUT_S    = 30.0    # Timeout voor verificatie auto-start
MTS_NOTIFY_COOLDOWN_S  = 300.0   # Minimaal 5 min tussen MTS-meldingen
GEN_ACTIVE_MIN_W       = 50.0    # Min. vermogen om generator als actief te beschouwen


@dataclass
class GeneratorStatus:
    enabled:          bool  = False
    active:           bool  = False   # Draait op generator
    power_w:          float = 0.0
    max_power_w:      float = 5000.0
    ats_type:         str   = "none"  # "auto" | "manual" | "none"
    fuel_type:        str   = "diesel"
    fuel_cost_eur_kwh: float = 0.35
    load_headroom_w:  float = 0.0    # Resterende capaciteit
    grid_lost:        bool  = False
    ups_active:       bool  = False   # Netuitval maar generator nog niet actief = UPS fase
    autostart_active: bool  = False
    status_text:      str   = ""
    restrictions:     list  = field(default_factory=list)  # Wat beperkt wordt

    def to_dict(self) -> dict:
        return {
            "enabled":           self.enabled,
            "active":            self.active,
            "power_w":           round(self.power_w, 1),
            "max_power_w":       self.max_power_w,
            "ats_type":          self.ats_type,
            "fuel_type":         self.fuel_type,
            "fuel_cost_eur_kwh": self.fuel_cost_eur_kwh,
            "load_headroom_w":   round(self.load_headroom_w, 1),
            "grid_lost":         self.grid_lost,
            "ups_active":        self.ups_active,
            "autostart_active":  self.autostart_active,
            "status_text":       self.status_text,
            "restrictions":      self.restrictions,
        }


class GeneratorManager:
    """Beheert generator/ATS logica voor CloudEMS."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass       = hass
        self._config     = config
        self._status     = GeneratorStatus()
        self._grid_lost_since: Optional[float] = None
        self._autostart_sent_at: Optional[float] = None
        self._last_mts_notify: float = 0.0
        self._last_status_hash: str = ""

    @property
    def active(self) -> bool:
        return self._status.active

    @property
    def status(self) -> GeneratorStatus:
        return self._status

    def update(self, data: dict, hass_states: dict) -> GeneratorStatus:
        """Verwerk huidige data en bepaal generator-status."""
        cfg = self._config
        if not cfg.get("generator_enabled"):
            self._status = GeneratorStatus(enabled=False)
            return self._status

        ats_type    = cfg.get("ats_type", "none")
        max_power_w = float(cfg.get("generator_max_power_w", 5000))
        fuel_type   = cfg.get("generator_type", "diesel")
        fuel_cost   = float(cfg.get("generator_fuel_cost_eur_kwh", 0.35))

        # ── Vermogen lezen ────────────────────────────────────────────────────
        gen_power_w = 0.0
        power_eid = cfg.get("generator_power_sensor", "")
        if power_eid:
            st = hass_states.get(power_eid)
            if st and st.state not in ("unavailable", "unknown", ""):
                try:
                    gen_power_w = float(st.state)
                except (ValueError, TypeError):
                    pass

        # ── ATS-status lezen ──────────────────────────────────────────────────
        gen_active_via_ats = False
        status_eid = cfg.get("generator_status_entity", "")
        if status_eid and ats_type == "auto":
            st = hass_states.get(status_eid)
            if st:
                state_val = st.state.lower()
                # Accepts: "on", "generator", "gen", "1", "true", "backup"
                gen_active_via_ats = state_val in (
                    "on", "generator", "gen", "1", "true", "backup", "noodstroom"
                )

        # ── Netuitval detectie (voor MTS) ─────────────────────────────────────
        grid_w   = abs(float(data.get("grid_power_w") or data.get("grid_power", 0) or 0))
        solar_w  = float(data.get("solar_power_w") or data.get("solar_power", 0) or 0)
        grid_lost = grid_w < GRID_LOST_THRESHOLD_W and solar_w < GRID_LOST_THRESHOLD_W
        now = time.time()

        if grid_lost:
            if self._grid_lost_since is None:
                self._grid_lost_since = now
        else:
            self._grid_lost_since = None

        grid_confirmed_lost = (
            self._grid_lost_since is not None
            and (now - self._grid_lost_since) >= GRID_LOST_CONFIRM_S
        )

        # ── Bepaal of generator actief is ────────────────────────────────────
        if ats_type == "auto":
            gen_active = gen_active_via_ats
        elif ats_type == "manual":
            # Bij MTS: generator actief als vermogenssensor > drempel
            gen_active = gen_power_w >= GEN_ACTIVE_MIN_W
        else:
            gen_active = False

        # ── Lastbegrenzing bepalen ────────────────────────────────────────────
        restrictions = []
        load_headroom_w = max_power_w - gen_power_w if gen_active else 0.0
        if gen_active:
            if load_headroom_w < 1000:
                restrictions.append("ev_pause")      # EV laden pauzeren
            if load_headroom_w < 2000:
                restrictions.append("boiler_low")    # Boiler op laag setpoint
            if load_headroom_w < 500:
                restrictions.append("all_non_essential")  # Alles niet-essentieel uit

        # ── Status tekst ──────────────────────────────────────────────────────
        if not gen_active and not grid_confirmed_lost:
            status_text = "Netvoeding actief"
        elif gen_active:
            status_text = (
                f"Generator actief — {gen_power_w:.0f}W "
                f"/ {max_power_w:.0f}W ({fuel_type})"
            )
        elif grid_confirmed_lost and ats_type == "manual":
            status_text = "Netuitval gedetecteerd — schakel MTS om"
        else:
            status_text = "Netuitval gedetecteerd"

        # UPS-fase: netuitval bevestigd maar generator nog niet actief
        _ups_active = grid_confirmed_lost and not gen_active

        self._status = GeneratorStatus(
            enabled          = True,
            active           = gen_active,
            ups_active       = _ups_active,
            power_w          = gen_power_w,
            max_power_w      = max_power_w,
            ats_type         = ats_type,
            fuel_type        = fuel_type,
            fuel_cost_eur_kwh= fuel_cost,
            load_headroom_w  = load_headroom_w,
            grid_lost        = grid_confirmed_lost,
            autostart_active = self._autostart_sent_at is not None,
            status_text      = status_text,
            restrictions     = restrictions,
        )
        return self._status

    async def async_handle_notifications(self, data: dict) -> list[dict]:
        """Genereer notificaties voor MTS/auto-start. Geeft lijst van alerts terug."""
        cfg     = self._config
        alerts  = []
        now     = time.time()
        st      = self._status
        ats     = cfg.get("ats_type", "none")

        if not cfg.get("generator_enabled"):
            return alerts

        # MTS: netuitval melding + TTS
        if ats == "manual" and st.grid_lost:
            if now - self._last_mts_notify >= MTS_NOTIFY_COOLDOWN_S:
                self._last_mts_notify = now
                msg = (
                    "CloudEMS detecteert geen netspanning. "
                    "Zet de handmatige transferschakelaar om "
                    "en start de generator. "
                    "CloudEMS begrenst automatisch zware lasten zodra de "
                    "generator actief is."
                )
                alerts.append({
                    "key":      "generator_mts_manual",
                    "priority": "warning",
                    "title":    "⚡ Netuitval — schakel MTS om",
                    "message":  msg,
                    "persistent": True,
                })
                # TTS via HA notify service
                notify_svc = self._config.get("notification_service", "")
                if notify_svc:
                    tts_msg = "Let op! CloudEMS heeft geen netspanning gedetecteerd. Zet de schakelaar om en start de generator."
                    try:
                        svc_parts = notify_svc.split(".")
                        domain = svc_parts[0] if len(svc_parts) > 1 else "notify"
                        service = svc_parts[1] if len(svc_parts) > 1 else svc_parts[0]
                        await self._hass.services.async_call(
                            domain, service,
                            {"message": tts_msg, "title": "⚡ Netuitval"},
                            blocking=False,
                        )
                    except Exception as err:
                        _LOGGER.warning("GeneratorManager: TTS melding mislukt: %s", err)
                # TTS via tts.speak als er een tts_entity geconfigureerd is
                tts_entity = self._config.get("tts_entity", "")
                if tts_entity:
                    try:
                        await self._hass.services.async_call(
                            "tts", "speak",
                            {
                                "media_player_entity_id": tts_entity,
                                "message": "Let op! Netuitval gedetecteerd. Zet de MTS schakelaar om en start de generator.",
                            },
                            blocking=False,
                        )
                    except Exception as err:
                        _LOGGER.warning("GeneratorManager: TTS speak mislukt: %s", err)

        # Auto-start: verstuur startcommando
        autostart_eid = cfg.get("generator_autostart_switch", "")
        if ats in ("auto", "manual") and st.grid_lost and autostart_eid:
            if self._autostart_sent_at is None:
                _LOGGER.info("GeneratorManager: auto-start commando → %s", autostart_eid)
                try:
                    domain = autostart_eid.split(".")[0]
                    svc = "turn_on" if domain == "switch" else "press" if domain == "button" else "turn_on"
                    await self._hass.services.async_call(
                        domain, svc, {"entity_id": autostart_eid}, blocking=False
                    )
                    self._autostart_sent_at = now
                    alerts.append({
                        "key":      "generator_autostart",
                        "priority": "info",
                        "title":    "🔑 Generator auto-start verstuurd",
                        "message":  f"CloudEMS heeft het startcommando verstuurd naar '{autostart_eid}'. Verificatie over {AUTOSTART_TIMEOUT_S:.0f}s.",
                        "persistent": False,
                    })
                except Exception as err:
                    _LOGGER.warning("GeneratorManager: auto-start mislukt: %s", err)

            # Verificatie: als auto-start verstuurd maar generator nog niet actief
            elif (now - self._autostart_sent_at) > AUTOSTART_TIMEOUT_S and not st.active:
                alerts.append({
                    "key":      "generator_autostart_failed",
                    "priority": "warning",
                    "title":    "⚠️ Generator niet gestart",
                    "message":  (
                        f"Het startcommando is verstuurd ({AUTOSTART_TIMEOUT_S:.0f}s geleden) "
                        "maar de generator is nog niet actief. "
                        "Controleer de generator en start handmatig."
                    ),
                    "persistent": True,
                })

        # Reset auto-start als generator actief is
        if st.active and self._autostart_sent_at is not None:
            _LOGGER.info("GeneratorManager: generator actief — auto-start reset")
            self._autostart_sent_at = None

        # Als generator actief: informatieve melding over lastbegrenzing
        if st.active and st.restrictions:
            alerts.append({
                "key":      "generator_active_restrictions",
                "priority": "info",
                "title":    "🔋 Generator actief — lasten begrensd",
                "message":  (
                    f"CloudEMS draait op generator ({st.power_w:.0f}W / {st.max_power_w:.0f}W). "
                    + (", ".join([
                        "EV laden gepauzeerd" if "ev_pause" in st.restrictions else "",
                        "boiler op minimumsetpoint" if "boiler_low" in st.restrictions else "",
                        "niet-essentiële lasten uitgeschakeld" if "all_non_essential" in st.restrictions else "",
                    ])).strip(", ")
                ),
                "persistent": False,
            })

        return alerts

    def get_boiler_restriction(self) -> Optional[float]:
        """Geeft max. boilersetpoint als generator actief en te weinig headroom."""
        if not self._status.active:
            return None
        if "boiler_low" in self._status.restrictions:
            return 45.0  # Minimumtemperatuur legionellavrij
        return None

    def ev_should_pause(self) -> bool:
        """True als EV laden gepauzeerd moet worden vanwege generator."""
        return self._status.active and "ev_pause" in self._status.restrictions
